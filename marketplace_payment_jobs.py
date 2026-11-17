"""Durable leased Stripe test-event recovery, not a scheduler or money processor.

Only previously verified immutable receipts can be queued. Workers retrieve
canonical state using configured test adapters; raw bodies/signatures are neither
stored nor re-signed. No financial, stock, entitlement or fulfillment effects.
"""
from dataclasses import dataclass
import time
import uuid

if __package__:
    from . import marketplace_inventory as inventory,marketplace_checkout as checkout
else:
    import marketplace_inventory as inventory
    import marketplace_checkout as checkout

LEASE_SECONDS=60
MAX_ATTEMPTS=8
MAX_BACKOFF=900


class JobError(ValueError):
    pass


@dataclass(frozen=True)
class Lease:
    receipt_id: int
    token: str
    attempt: int
    until: int


SCHEMA="""
CREATE TABLE IF NOT EXISTS marketplace_payment_jobs (
    receipt_id INTEGER PRIMARY KEY REFERENCES marketplace_payment_events(id),
    state TEXT NOT NULL CHECK(state IN ('ready','running','retry','complete','review','exhausted')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),next_attempt_at INTEGER NOT NULL,
    lease_token TEXT,lease_until INTEGER,last_reason TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
    CHECK((state='running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
       OR (state!='running' AND lease_token IS NULL AND lease_until IS NULL))
);
CREATE TRIGGER IF NOT EXISTS marketplace_payment_job_identity BEFORE UPDATE ON marketplace_payment_jobs
WHEN NEW.receipt_id!=OLD.receipt_id OR NEW.created_at!=OLD.created_at OR NEW.attempts<OLD.attempts
BEGIN SELECT RAISE(ABORT,'job identity/attempt history is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_payment_job_delete BEFORE DELETE ON marketplace_payment_jobs
BEGIN SELECT RAISE(ABORT,'payment job history is retained'); END;
CREATE INDEX IF NOT EXISTS marketplace_payment_jobs_due ON marketplace_payment_jobs(state,next_attempt_at,lease_until,receipt_id);
"""


def initialize(db):
    """Additive migration/backfill; repeated calls never reset attempts or leases."""
    if db.in_transaction: raise JobError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'''
        INSERT OR IGNORE INTO marketplace_payment_jobs
        (receipt_id,state,attempts,next_attempt_at,last_reason,created_at,updated_at)
        SELECT e.id,CASE outcome WHEN 'observed_test' THEN CASE WHEN EXISTS (
                SELECT 1 FROM marketplace_payment_test_attempts a WHERE a.id=e.attempt_id
                AND a.observed_status NOT IN ('succeeded','canceled')) THEN 'retry' ELSE 'complete' END
            WHEN 'ignored' THEN 'complete'
            WHEN 'needs_review' THEN 'review' WHEN 'retry' THEN 'retry' ELSE 'ready' END,
            0,COALESCE(checked_at,received_at),reason,received_at,COALESCE(checked_at,received_at)
        FROM marketplace_payment_events e;
        COMMIT;''')


def _payments():
    if __package__:
        from . import marketplace_payments
    else:
        import marketplace_payments
    return marketplace_payments


def _adapter(adapter):
    payments=_payments()
    if not isinstance(adapter,payments.StripeTestPaymentReader) or adapter.scope.environment!='test' or adapter.scope.provider!='stripe':
        raise JobError('configured Stripe test adapter required')


def _clock(now,clock):
    inventory.clock(now)
    if clock is not None and not callable(clock): raise JobError('configured worker clock required')
    started=time.monotonic()
    source=clock or (lambda:now+int(time.monotonic()-started))
    def current():
        value=source();inventory.clock(value)
        if value<now: raise JobError('worker clock moved backwards')
        return value
    return current


def enqueue_locked(db,receipt_id,now):
    """Called atomically with insertion of the verified receipt, never from HTTP data."""
    if not db.in_transaction: raise JobError('transaction required')
    inventory.clock(now)
    row=db.execute('SELECT received_at FROM marketplace_payment_events WHERE id=?',(receipt_id,)).fetchone()
    if not row: raise JobError('verified receipt required')
    db.execute("INSERT OR IGNORE INTO marketplace_payment_jobs (receipt_id,state,attempts,next_attempt_at,last_reason,created_at,updated_at) VALUES (?,'ready',0,?,'',?,?)",
        (receipt_id,now,row['received_at'],now))


def _scoped_receipt(db,adapter,receipt_id):
    row=db.execute("SELECT * FROM marketplace_payment_events WHERE id=? AND environment='test' AND provider='stripe' AND platform_ref=?",(receipt_id,adapter.scope.platform)).fetchone()
    if not row: raise JobError('receipt/provider scope mismatch')
    return row


def _exhausted_locked(db,receipt_id,now):
    db.execute("UPDATE marketplace_payment_jobs SET state='exhausted',lease_token=NULL,lease_until=NULL,last_reason='retry_exhausted',updated_at=? WHERE receipt_id=?",(now,receipt_id))
    db.execute("UPDATE marketplace_payment_events SET outcome='needs_review',reason='retry_exhausted',checked_at=? WHERE id=?",(now,receipt_id))


def _claim_locked(db,adapter,receipt_id,now,redelivery):
    receipt=_scoped_receipt(db,adapter,receipt_id)
    job=db.execute('SELECT * FROM marketplace_payment_jobs WHERE receipt_id=?',(receipt_id,)).fetchone()
    if not job: raise JobError('receipt has no durable job')
    if job['state']=='running' and job['lease_until']>now: return None
    if job['state']=='exhausted': return None
    if job['state']=='complete':
        # A newly verified provider redelivery can refresh nonterminal observations.
        attempt=db.execute('SELECT observed_status FROM marketplace_payment_test_attempts WHERE id=?',(receipt['attempt_id'],)).fetchone()
        if not redelivery or receipt['outcome']=='ignored' or not attempt or attempt[0] in ('succeeded','canceled'):
            return None
    if job['state']=='review' and not redelivery: return None
    if job['state'] in ('ready','retry') and job['next_attempt_at']>now and not redelivery: return None
    if job['attempts']>=MAX_ATTEMPTS:
        _exhausted_locked(db,receipt_id,now)
        return None
    token=uuid.uuid4().hex;number=job['attempts']+1;until=now+LEASE_SECONDS
    db.execute("UPDATE marketplace_payment_jobs SET state='running',attempts=?,lease_token=?,lease_until=?,updated_at=? WHERE receipt_id=?",
        (number,token,until,now,receipt_id))
    return Lease(receipt_id,token,number,until)


def claim(db,adapter,now,receipt_id=None,redelivery=False):
    """One SQLite-serialized claim. Network calls happen only after this commits."""
    _adapter(adapter);inventory.clock(now)
    if type(redelivery) is not bool: raise JobError('invalid delivery mode')
    with inventory.transaction(db):
        if receipt_id is None:
            row=db.execute('''SELECT j.receipt_id FROM marketplace_payment_jobs j JOIN marketplace_payment_events e ON e.id=j.receipt_id
                WHERE e.environment='test' AND e.provider='stripe' AND e.platform_ref=? AND j.attempts<?
                AND ((j.state IN ('ready','retry') AND j.next_attempt_at<=?) OR (j.state='running' AND j.lease_until<=?))
                ORDER BY j.next_attempt_at,j.receipt_id LIMIT 1''',(adapter.scope.platform,MAX_ATTEMPTS,now,now)).fetchone()
            if not row: return None
            receipt_id=row[0]
        if type(receipt_id) is not int or receipt_id<=0: raise JobError('invalid receipt reference')
        return _claim_locked(db,adapter,receipt_id,now,redelivery)


def _owns(db,lease,now):
    return bool(db.execute("SELECT 1 FROM marketplace_payment_jobs WHERE receipt_id=? AND state='running' AND lease_token=? AND attempts=? AND lease_until>?",
        (lease.receipt_id,lease.token,lease.attempt,now)).fetchone())


def _lost(lease):
    return dict(receipt_id=lease.receipt_id,outcome='received',reason='lease_lost')


def _finish_locked(db,lease,result,now):
    outcome=result['outcome'];reason=result['reason']
    state='retry' if outcome=='retry' else 'review' if outcome=='needs_review' else 'complete'
    if outcome=='observed_test':
        attempt=db.execute('''SELECT a.observed_status FROM marketplace_payment_events e
            JOIN marketplace_payment_test_attempts a ON a.id=e.attempt_id WHERE e.id=?''',(lease.receipt_id,)).fetchone()
        if attempt and attempt[0] not in ('succeeded','canceled'):
            state='retry';reason='awaiting_canonical_final_state'
    if state=='retry' and lease.attempt>=MAX_ATTEMPTS:
        _exhausted_locked(db,lease.receipt_id,now)
        return dict(receipt_id=lease.receipt_id,outcome='needs_review',reason='retry_exhausted')
    delay=min(30*2**(lease.attempt-1),MAX_BACKOFF) if state=='retry' else 0
    db.execute('''UPDATE marketplace_payment_jobs SET state=?,next_attempt_at=?,lease_token=NULL,lease_until=NULL,last_reason=?,updated_at=?
        WHERE receipt_id=? AND lease_token=?''',(state,now+delay,reason,now,lease.receipt_id,lease.token))
    return result


def process_claim(db,adapter,lease,now,policy=checkout.NeonrestPolicy,clock=None):
    """Canonical lookup plus a fenced atomic observation/job update; no money effects."""
    _adapter(adapter)
    if not isinstance(lease,Lease): raise JobError('worker lease required')
    current=_clock(now,clock);payments=_payments()
    with inventory.transaction(db):
        _scoped_receipt(db,adapter,lease.receipt_id)
        at=current()
        if not _owns(db,lease,at): return _lost(lease)
        receipt,account,attempt,early=payments._receipt_binding_locked(db,adapter,lease.receipt_id)
        if early:
            result=payments._reconcile_receipt_locked(db,adapter,lease.receipt_id,None,*early,at,policy)
            return _finish_locked(db,lease,result,at)
    try:
        canonical=adapter.canonical(receipt['account_ref'],receipt['payment_ref'])
        outcome,reason='received',''
    except payments.PaymentError:
        canonical=None;outcome,reason='needs_review','invalid_canonical_payment'
    except Exception:
        canonical=None;outcome,reason='retry','provider_lookup_unavailable'
    # A crash before this commit leaves the lease recoverable at expiry. An old
    # worker cannot commit if another worker reclaimed it or the lease expired.
    with inventory.transaction(db):
        finished=current()
        if not _owns(db,lease,finished): return _lost(lease)
        result=payments._reconcile_receipt_locked(db,adapter,lease.receipt_id,canonical,outcome,reason,finished,policy)
        return _finish_locked(db,lease,result,finished)


def process_delivery(db,adapter,receipt_id,now,policy=checkout.NeonrestPolicy,clock=None):
    """Immediate processing after a freshly signature-verified provider delivery.

    Redelivery may bypass scheduled backoff/review, never an active lease, terminal
    success cache or attempt cap. Worker retries respect backoff and review state.
    """
    current=_clock(now,clock)
    lease=claim(db,adapter,current(),receipt_id,redelivery=True)
    if lease: return process_claim(db,adapter,lease,now,policy,current)
    receipt=_scoped_receipt(db,adapter,receipt_id)
    job=db.execute('SELECT state FROM marketplace_payment_jobs WHERE receipt_id=?',(receipt_id,)).fetchone()
    if job['state']=='running': return dict(receipt_id=receipt_id,outcome='received',reason='processing_in_progress')
    return dict(receipt_id=receipt_id,outcome=receipt['outcome'],reason=receipt['reason'])


def reap_exhausted(db,adapter,now,limit=100):
    _adapter(adapter);inventory.clock(now)
    if type(limit) is not int or not 1<=limit<=100: raise JobError('invalid batch size')
    with inventory.transaction(db):
        rows=db.execute('''SELECT j.receipt_id FROM marketplace_payment_jobs j JOIN marketplace_payment_events e ON e.id=j.receipt_id
            WHERE e.environment='test' AND e.provider='stripe' AND e.platform_ref=? AND j.attempts>=?
            AND (j.state IN ('ready','retry') OR (j.state='running' AND j.lease_until<=?)) ORDER BY j.receipt_id LIMIT ?''',
            (adapter.scope.platform,MAX_ATTEMPTS,now,limit)).fetchall()
        for row in rows: _exhausted_locked(db,row[0],now)
        return len(rows)


def run_due(db,adapter,now,limit=25,policy=checkout.NeonrestPolicy,clock=None):
    """One bounded worker tick, with no sleeps or scheduling changes."""
    _adapter(adapter)
    if type(limit) is not int or not 1<=limit<=100: raise JobError('invalid batch size')
    current=_clock(now,clock)
    reaped=reap_exhausted(db,adapter,current(),limit)
    results=[]
    for _ in range(limit):
        lease=claim(db,adapter,current())
        if lease is None: break
        results.append(process_claim(db,adapter,lease,now,policy,current))
    return dict(processed=len(results),exhausted=reaped,results=results)


def summary(db,adapter,now):
    """Internal aggregate diagnostics; excludes receipt/customer/lease/key details."""
    _adapter(adapter);inventory.clock(now)
    counts=dict(db.execute('''SELECT j.state,COUNT(*) FROM marketplace_payment_jobs j JOIN marketplace_payment_events e ON e.id=j.receipt_id
        WHERE e.environment='test' AND e.provider='stripe' AND e.platform_ref=? GROUP BY j.state''',(adapter.scope.platform,)))
    due=db.execute('''SELECT COUNT(*) FROM marketplace_payment_jobs j JOIN marketplace_payment_events e ON e.id=j.receipt_id
        WHERE e.environment='test' AND e.provider='stripe' AND e.platform_ref=?
        AND ((j.state IN ('ready','retry') AND j.next_attempt_at<=?) OR (j.state='running' AND j.lease_until<=?))''',
        (adapter.scope.platform,now,now)).fetchone()[0]
    return dict(states=counts,due=due)
