"""Inactive Stripe test refund plans, canonical reads and atomic reverse journals.

No refund creation, fee refund/transfer reversal API, live route, stock restoration,
entitlement change or notifications. Trusted workers configure adapters, never forms.
"""
from dataclasses import dataclass
import json
import re
import time
import uuid

if __package__:
    from . import marketplace_checkout as checkout, marketplace_inventory as inventory
    from . import marketplace_ledger as ledger, marketplace_payments as payments
    from . import marketplace_settlement as settlement
    from .marketplace_core import cents,commission_refund
    from .marketplace_provider_api import ProviderUnavailable
else:
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory
    import marketplace_ledger as ledger
    import marketplace_payments as payments
    import marketplace_settlement as settlement
    from marketplace_core import cents,commission_refund
    from marketplace_provider_api import ProviderUnavailable

LEASE_SECONDS=60
MAX_ATTEMPTS=8


class RefundError(ValueError): pass


SCHEMA="""
CREATE TABLE IF NOT EXISTS marketplace_test_refund_requests (
 id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
 order_id TEXT NOT NULL REFERENCES marketplace_test_settlements(order_id),
 owner_id INTEGER NOT NULL REFERENCES users(id),request_key TEXT NOT NULL,
 item_cents INTEGER NOT NULL CHECK(typeof(item_cents)='integer' AND item_cents>=0),
 shipping_cents INTEGER NOT NULL CHECK(typeof(shipping_cents)='integer' AND shipping_cents>=0),
 tax_cents INTEGER NOT NULL CHECK(typeof(tax_cents)='integer' AND tax_cents>=0),
 amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 1 AND 100000000),
 created_at INTEGER NOT NULL,CHECK(amount_cents=item_cents+shipping_cents+tax_cents),
 UNIQUE(owner_id,request_key)
);
CREATE TABLE IF NOT EXISTS marketplace_test_refund_bindings (
 request_id TEXT PRIMARY KEY REFERENCES marketplace_test_refund_requests(id),
 account_id TEXT NOT NULL REFERENCES marketplace_payment_accounts(id),refund_ref TEXT NOT NULL,
 bound_at INTEGER NOT NULL,UNIQUE(account_id,refund_ref)
);
CREATE TABLE IF NOT EXISTS marketplace_test_refund_jobs (
 request_id TEXT PRIMARY KEY REFERENCES marketplace_test_refund_requests(id),
 state TEXT NOT NULL CHECK(state IN ('ready','running','retry','complete','review','failed','exhausted','withdrawn')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),next_attempt_at INTEGER NOT NULL,
 lease_token TEXT,lease_until INTEGER,last_reason TEXT NOT NULL DEFAULT '',updated_at INTEGER NOT NULL,
 CHECK((state='running' AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
 OR (state!='running' AND lease_token IS NULL AND lease_until IS NULL))
);
CREATE TABLE IF NOT EXISTS marketplace_test_refund_withdrawals (
 request_id TEXT PRIMARY KEY REFERENCES marketplace_test_refund_requests(id),
 owner_id INTEGER NOT NULL REFERENCES users(id),withdrawn_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_withdrawal_update BEFORE UPDATE ON marketplace_test_refund_withdrawals
BEGIN SELECT RAISE(ABORT,'refund withdrawal is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_withdrawal_delete BEFORE DELETE ON marketplace_test_refund_withdrawals
BEGIN SELECT RAISE(ABORT,'refund withdrawal is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_test_refund_observations (
 id INTEGER PRIMARY KEY,request_id TEXT NOT NULL REFERENCES marketplace_test_refund_requests(id),
 status TEXT NOT NULL CHECK(status IN ('pending','requires_action','succeeded','failed','canceled')),
 checked_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS marketplace_test_refund_applications (
 request_id TEXT PRIMARY KEY REFERENCES marketplace_test_refund_requests(id),
 observation_id INTEGER NOT NULL UNIQUE REFERENCES marketplace_test_refund_observations(id),
 journal_id INTEGER NOT NULL UNIQUE REFERENCES marketplace_ledger_journals(id),
 fee_credit_cents INTEGER NOT NULL CHECK(typeof(fee_credit_cents)='integer' AND fee_credit_cents>=0),
 applied_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_request_update BEFORE UPDATE ON marketplace_test_refund_requests
BEGIN SELECT RAISE(ABORT,'refund plan is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_request_delete BEFORE DELETE ON marketplace_test_refund_requests
BEGIN SELECT RAISE(ABORT,'refund plan is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_binding_update BEFORE UPDATE ON marketplace_test_refund_bindings
BEGIN SELECT RAISE(ABORT,'refund binding is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_binding_delete BEFORE DELETE ON marketplace_test_refund_bindings
BEGIN SELECT RAISE(ABORT,'refund binding is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_observation_update BEFORE UPDATE ON marketplace_test_refund_observations
BEGIN SELECT RAISE(ABORT,'refund observation is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_observation_delete BEFORE DELETE ON marketplace_test_refund_observations
BEGIN SELECT RAISE(ABORT,'refund observation is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_application_update BEFORE UPDATE ON marketplace_test_refund_applications
BEGIN SELECT RAISE(ABORT,'refund application is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_application_delete BEFORE DELETE ON marketplace_test_refund_applications
BEGIN SELECT RAISE(ABORT,'refund application is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_job_update BEFORE UPDATE ON marketplace_test_refund_jobs
WHEN NEW.request_id!=OLD.request_id OR NEW.attempts<OLD.attempts
BEGIN SELECT RAISE(ABORT,'refund job identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_job_delete BEFORE DELETE ON marketplace_test_refund_jobs
BEGIN SELECT RAISE(ABORT,'refund job is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_application_validate BEFORE INSERT ON marketplace_test_refund_applications
WHEN NOT EXISTS (SELECT 1 FROM marketplace_test_refund_observations o
 JOIN marketplace_ledger_journals j ON j.id=NEW.journal_id
 WHERE o.id=NEW.observation_id AND o.request_id=NEW.request_id AND o.status='succeeded'
 AND o.checked_at=NEW.applied_at AND j.environment='test' AND j.posted=1)
BEGIN SELECT RAISE(ABORT,'matching successful observation and journal required'); END;
CREATE INDEX IF NOT EXISTS marketplace_test_refunds_order ON marketplace_test_refund_requests(order_id,id);
CREATE INDEX IF NOT EXISTS marketplace_test_refunds_due ON marketplace_test_refund_jobs(state,next_attempt_at,lease_until,request_id);
"""


def initialize(db):
    if db.in_transaction: raise RefundError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def _historical(db,order_id):
    row=db.execute("SELECT * FROM marketplace_test_settlements WHERE order_id=? AND environment='test'",(order_id,)).fetchone()
    if not row: raise RefundError('settled test order required')
    order=db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=?',(order_id,)).fetchone()
    attempt=db.execute('SELECT * FROM marketplace_payment_test_attempts WHERE id=?',(row['attempt_id'],)).fetchone()
    account=db.execute('SELECT * FROM marketplace_payment_accounts WHERE id=?',(attempt['account_id'],)).fetchone()
    if account['provider']!='stripe' or account['environment']!='test': raise RefundError('Stripe test settlement required')
    return row,order,attempt,account,json.loads(row['allocation'])


def _owner(db,uid,order,policy):
    checkout.actor(policy,db,uid)
    shop=checkout.shop_row(db,order['seller_ref'])
    if uid!=order['seller_owner_id'] or shop['owner_id']!=uid or not policy.owner(db,uid,shop):
        raise RefundError('original eligible shop owner required')


def request_test_refund(db,uid,order_id,request_key,item_cents,shipping_cents,tax_cents,now,policy=checkout.NeonrestPolicy):
    """Owner-authorized component plan; reserves headroom, never issues a refund.

    Unbound/pending/review/exhausted requests keep their budget. A canonical
    failed/canceled refund or authorized unbound withdrawal releases it. Historical successes are never reallocated.
    """
    inventory.clock(now);inventory.identity('test',order_id,request_key)
    for value in (item_cents,shipping_cents,tax_cents): cents(value)
    total=cents(item_cents+shipping_cents+tax_cents)
    if not total: raise RefundError('positive refund amount required')
    with inventory.transaction(db):
        win,order,attempt,account,allocation=_historical(db,order_id)
        _owner(db,uid,order,policy)
        if now<win['settled_at']: raise RefundError('refund predates settlement')
        existing=db.execute('SELECT * FROM marketplace_test_refund_requests WHERE owner_id=? AND request_key=?',(uid,request_key)).fetchone()
        if existing:
            if (existing['order_id'],existing['item_cents'],existing['shipping_cents'],existing['tax_cents'])!=(order_id,item_cents,shipping_cents,tax_cents):
                raise RefundError('refund idempotency conflict')
            return existing['id']
        reserved=db.execute("""SELECT COALESCE(SUM(r.item_cents),0),COALESCE(SUM(r.shipping_cents),0),COALESCE(SUM(r.tax_cents),0)
            FROM marketplace_test_refund_requests r JOIN marketplace_test_refund_jobs j ON j.request_id=r.id
            WHERE r.order_id=? AND j.state NOT IN ('failed','withdrawn')""",(order_id,)).fetchone()
        if any(used+new>allocation[key] for used,new,key in zip(reserved,(item_cents,shipping_cents,tax_cents),('item_cents','shipping_cents','tax_cents'))):
            raise RefundError('refund exceeds remaining component amount')
        ident=uuid.uuid4().hex
        db.execute('INSERT INTO marketplace_test_refund_requests VALUES (?,?,?,?,?,?,?,?,?,?)',
            (ident,'test',order_id,uid,request_key,item_cents,shipping_cents,tax_cents,total,now))
        db.execute("INSERT INTO marketplace_test_refund_jobs VALUES (?,'ready',0,?,NULL,NULL,'',?)",(ident,now,now))
        return ident


def bind_test_refund(db,request_id,refund_ref,now):
    """Internal server-created provider association; never bind a browser return.

    A test creation adapter is still required. Binding alone proves no success;
    reads must match the original account/payment, request metadata and amount.
    """
    inventory.clock(now)
    if not isinstance(refund_ref,str) or not re.fullmatch(r're_[A-Za-z0-9_]{1,150}',refund_ref): raise RefundError('refund reference required')
    with inventory.transaction(db):
        request=db.execute('SELECT * FROM marketplace_test_refund_requests WHERE id=?',(request_id,)).fetchone()
        if not request or now<request['created_at']: raise RefundError('test request unavailable')
        if db.execute('SELECT 1 FROM marketplace_test_refund_withdrawals WHERE request_id=?',(request_id,)).fetchone():
            raise RefundError('withdrawn refund cannot be bound')
        _,_,_,account,_=_historical(db,request['order_id'])
        old=db.execute('SELECT refund_ref FROM marketplace_test_refund_bindings WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old[0]!=refund_ref: raise RefundError('refund binding conflict')
            return request_id
        db.execute('INSERT INTO marketplace_test_refund_bindings VALUES (?,?,?,?)',(request_id,account['id'],refund_ref,now))
        return request_id


def withdraw_unbound(db,uid,request_id,now,policy=checkout.NeonrestPolicy):
    """Withdraw an unsubmitted plan only; no provider refund is canceled here."""
    inventory.clock(now)
    with inventory.transaction(db):
        request=db.execute('SELECT * FROM marketplace_test_refund_requests WHERE id=?',(request_id,)).fetchone()
        if not request or now<request['created_at']: raise RefundError('test request unavailable')
        _,order,_,_,_=_historical(db,request['order_id']);_owner(db,uid,order,policy)
        if request['owner_id']!=uid: raise RefundError('original requesting owner required')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marketplace_test_refund_dispatches'").fetchone() and db.execute('SELECT 1 FROM marketplace_test_refund_dispatches WHERE request_id=?',(request_id,)).fetchone():
            raise RefundError('submitted refund requires canonical recovery, not withdrawal')
        old=db.execute('SELECT 1 FROM marketplace_test_refund_withdrawals WHERE request_id=?',(request_id,)).fetchone()
        if old: return request_id
        if db.execute('SELECT 1 FROM marketplace_test_refund_bindings WHERE request_id=?',(request_id,)).fetchone():
            raise RefundError('bound refund must be reconciled, not locally withdrawn')
        job=db.execute('SELECT * FROM marketplace_test_refund_jobs WHERE request_id=?',(request_id,)).fetchone()
        if job['state']!='ready' or job['attempts']!=0: raise RefundError('only unsubmitted plans can be withdrawn')
        db.execute('INSERT INTO marketplace_test_refund_withdrawals VALUES (?,?,?)',(request_id,uid,now))
        db.execute("UPDATE marketplace_test_refund_jobs SET state='withdrawn',last_reason='unbound_plan_withdrawn',updated_at=? WHERE request_id=?",(now,request_id))
        return request_id


class StripeTestRefundReader:
    """Configured canonical reads; refunds have no livemode field of their own."""
    def __init__(self,payment_reader,fetch_refund):
        if not isinstance(payment_reader,payments.StripeTestPaymentReader) or not callable(fetch_refund):
            raise RefundError('configured Stripe test readers required')
        self.payment_reader=payment_reader;self.scope=payment_reader.scope;self._fetch=fetch_refund

    def canonical(self,account,refund_ref,payment_ref):
        parent=self.payment_reader.canonical(account,payment_ref)
        value=self._fetch(account,refund_ref)
        if not isinstance(value,dict) or value.get('id')!=refund_ref or value.get('object')!='refund' or value.get('payment_intent')!=payment_ref or value.get('currency')!='usd':
            raise RefundError('canonical refund binding mismatch')
        if 'livemode' in value and value['livemode'] is not False:
            raise RefundError('live refund is not supported')
        cents(value.get('amount'));inventory.clock(value.get('created'))
        if not value['amount'] or value.get('status') not in ('pending','requires_action','succeeded','failed','canceled'):
            raise RefundError('canonical refund state unavailable')
        metadata=value.get('metadata')
        if not isinstance(metadata,dict): raise RefundError('canonical refund association missing')
        return dict(parent=parent,amount=value['amount'],created=value['created'],status=value['status'],
            request=metadata.get('neonrest_refund_request'),order=metadata.get('neonrest_order'))


@dataclass(frozen=True)
class Lease:
    request_id: str
    token: str
    attempt: int
    until: int


def _adapter(adapter):
    if type(adapter) is not StripeTestRefundReader or adapter.scope.environment!='test' or adapter.scope.provider!='stripe':
        raise RefundError('configured Stripe test refund reader required')


def _context(db,request_id,adapter):
    request=db.execute('SELECT * FROM marketplace_test_refund_requests WHERE id=?',(request_id,)).fetchone()
    binding=db.execute('SELECT * FROM marketplace_test_refund_bindings WHERE request_id=?',(request_id,)).fetchone()
    if not request or not binding: raise RefundError('bound test refund request required')
    win,order,attempt,account,allocation=_historical(db,request['order_id'])
    if account['platform_ref']!=adapter.scope.platform or binding['account_id']!=account['id']:
        raise RefundError('refund provider scope mismatch')
    return request,binding,win,order,attempt,account,allocation


def _finish(db,lease,state,reason,now):
    db.execute('''UPDATE marketplace_test_refund_jobs SET state=?,next_attempt_at=?,lease_token=NULL,lease_until=NULL,last_reason=?,updated_at=?
        WHERE request_id=?''',(state,now+min(30*2**(lease.attempt-1),900) if state=='retry' else now,reason,now,lease.request_id))


def claim(db,adapter,now,request_id=None):
    """Short claim transaction; canonical HTTP occurs after releasing the lock."""
    _adapter(adapter);inventory.clock(now)
    with inventory.transaction(db):
        if request_id is None:
            row=db.execute("""SELECT j.* FROM marketplace_test_refund_jobs j
                JOIN marketplace_test_refund_bindings b ON b.request_id=j.request_id
                JOIN marketplace_payment_accounts a ON a.id=b.account_id
                WHERE a.platform_ref=? AND a.provider='stripe' AND a.environment='test'
                AND ((j.state IN ('ready','retry') AND j.next_attempt_at<=?) OR (j.state='running' AND j.lease_until<=?))
                ORDER BY j.next_attempt_at,j.request_id LIMIT 1""",(adapter.scope.platform,now,now)).fetchone()
            if not row: return None
            request_id=row['request_id']
        _context(db,request_id,adapter)
        row=db.execute('SELECT * FROM marketplace_test_refund_jobs WHERE request_id=?',(request_id,)).fetchone()
        if now<row['updated_at']: raise RefundError('worker clock moved backwards')
        if row['state'] not in ('ready','retry','running') or row['state']=='running' and row['lease_until']>now or row['state']!='running' and row['next_attempt_at']>now:
            return None
        if row['attempts']>=MAX_ATTEMPTS:
            db.execute("UPDATE marketplace_test_refund_jobs SET state='exhausted',lease_token=NULL,lease_until=NULL,last_reason='retry_exhausted',updated_at=? WHERE request_id=?",(now,request_id))
            return None
        lease=Lease(request_id,uuid.uuid4().hex,row['attempts']+1,now+LEASE_SECONDS)
        db.execute("UPDATE marketplace_test_refund_jobs SET state='running',attempts=?,lease_token=?,lease_until=?,updated_at=? WHERE request_id=?",(lease.attempt,lease.token,lease.until,now,request_id))
        return lease


def _apply_locked(db,request,win,order,attempt,account,allocation,observation,now):
    previous=db.execute('''SELECT COALESCE(SUM(r.item_cents),0),COALESCE(SUM(a.fee_credit_cents),0),
        COALESCE(SUM(r.shipping_cents),0),COALESCE(SUM(r.tax_cents),0)
        FROM marketplace_test_refund_applications a JOIN marketplace_test_refund_requests r ON r.id=a.request_id WHERE r.order_id=?''',(order['id'],)).fetchone()
    if any(old+new>allocation[key] for old,new,key in ((previous[0],request['item_cents'],'item_cents'),(previous[2],request['shipping_cents'],'shipping_cents'),(previous[3],request['tax_cents'],'tax_cents'))):
        raise RefundError('applied refund exceeds historical component amount')
    fee=commission_refund(previous[0]+request['item_cents'],allocation['item_cents'],allocation['platform_fee_cents'],previous[1]) if allocation['item_cents'] else 0
    reversed_allocation=dict(total_cents=-request['amount_cents'],
        seller_obligation_cents=-(request['item_cents']+request['shipping_cents']-fee),
        platform_fee_cents=-fee,tax_cents=-request['tax_cents'])
    entries=[]
    for ident,owner,kind,amount in settlement._ledger_definitions(order,account,reversed_allocation):
        existing=db.execute('SELECT id,environment,owner,kind,currency FROM marketplace_ledger_accounts WHERE id=?',(ident,)).fetchone()
        if not existing or tuple(existing)!=(ident,'test',owner,kind,'USD'): raise RefundError('historical ledger identity mismatch')
        if amount: entries.append((ident,amount))
    journal=ledger._post_locked(db,'test','qa-refund-'+request['id'],'qa-refund-'+request['id'],entries,now)
    db.execute('INSERT INTO marketplace_test_refund_applications VALUES (?,?,?,?,?)',(request['id'],observation,journal,fee,now))


def process_claim(db,adapter,lease,now,clock=None):
    """Reconcile a leased refund; observation, journal and completion commit together."""
    _adapter(adapter);inventory.clock(now)
    if not isinstance(lease,Lease) or type(lease.attempt) is not int or not 1<=lease.attempt<=MAX_ATTEMPTS:
        raise RefundError('valid worker lease required')
    if db.in_transaction: raise RefundError('dedicated connection required')
    started=time.monotonic()
    if clock is not None and not callable(clock): raise RefundError('configured clock required')
    def current():
        value=clock() if clock else now+int(time.monotonic()-started)
        inventory.clock(value)
        if value<now: raise RefundError('worker clock moved backwards')
        return value
    def owns(at):
        row=db.execute('SELECT * FROM marketplace_test_refund_jobs WHERE request_id=?',(lease.request_id,)).fetchone()
        return row and at>=row['updated_at'] and row['state']=='running' and row['lease_token']==lease.token and row['attempts']==lease.attempt and row['lease_until']==lease.until and lease.until>at
    request,binding,win,order,attempt,account,allocation=_context(db,lease.request_id,adapter)
    if not owns(current()): return dict(outcome='lease_lost')
    observation=None;state='review';reason='canonical_mismatch'
    try:
        observation=adapter.canonical(account['account_ref'],binding['refund_ref'],attempt['payment_ref'])
    except ProviderUnavailable:
        state='retry';reason='provider_unavailable'
    except ValueError:
        state='review';reason='canonical_mismatch'
    except Exception:
        state='retry';reason='provider_unavailable'
    at=current()
    with inventory.transaction(db):
        if not owns(at): return dict(outcome='lease_lost')
        request,binding,win,order,attempt,account,allocation=_context(db,lease.request_id,adapter)
        if observation:
            parent=observation['parent']
            if (observation['request']!=request['id'] or observation['order']!=order['id'] or observation['amount']!=request['amount_cents']
                or not request['created_at']<=observation['created']<=at or parent['status']!='succeeded'
                or parent['order']!=order['id'] or parent['quote']!=win['quote_id']
                or parent['currency']!='usd' or parent['amount']!=allocation['total_cents']):
                state='review';reason='canonical_mismatch'
            else:
                status=observation['status']
                ident=db.execute('INSERT INTO marketplace_test_refund_observations (request_id,status,checked_at) VALUES (?,?,?)',(request['id'],status,at)).lastrowid
                if status=='succeeded':
                    _apply_locked(db,request,win,order,attempt,account,allocation,ident,at)
                    state='complete';reason='test_refund_applied'
                elif status in ('failed','canceled'):
                    state='failed';reason='canonical_'+status
                else:
                    state='retry';reason='canonical_'+status
        if state=='retry' and lease.attempt>=MAX_ATTEMPTS: state='exhausted';reason='retry_exhausted'
        _finish(db,lease,state,reason,at)
        return dict(outcome=state,reason=reason)


def process_request(db,adapter,request_id,now,clock=None):
    lease=claim(db,adapter,now,request_id)
    if lease: return process_claim(db,adapter,lease,now,clock)
    row=db.execute('SELECT state,last_reason FROM marketplace_test_refund_jobs WHERE request_id=?',(request_id,)).fetchone()
    return dict(outcome=row['state'],reason=row['last_reason'])


def run_due(db,adapter,now,limit=25,clock=None):
    _adapter(adapter);inventory.clock(now)
    if type(limit) is not int or not 1<=limit<=100: raise RefundError('bounded worker batch required')
    if clock is not None and not callable(clock): raise RefundError('configured clock required')
    started=time.monotonic();results=[]
    for _ in range(limit):
        at=clock() if clock else now+int(time.monotonic()-started)
        inventory.clock(at)
        if at<now: raise RefundError('worker clock moved backwards')
        lease=claim(db,adapter,at)
        if lease is None: break
        results.append(process_claim(db,adapter,lease,at,clock))
    return results


def get_summary(db,uid,order_id,now,policy=checkout.NeonrestPolicy):
    """Scoped aggregate test status for future UI; never provider refs or addresses."""
    checkout.get_order(db,'test',uid,order_id,now,policy)
    win,_,_,_,allocation=_historical(db,order_id)
    values=db.execute('''SELECT COALESCE(SUM(r.amount_cents),0),COALESCE(SUM(a.fee_credit_cents),0)
        FROM marketplace_test_refund_applications a JOIN marketplace_test_refund_requests r ON r.id=a.request_id WHERE r.order_id=?''',(order_id,)).fetchone()
    return dict(state='test_refunded' if values[0]==allocation['total_cents'] else ('test_partially_refunded' if values[0] else 'test_settled'),
        total_cents=allocation['total_cents'],refunded_cents=values[0],platform_fee_credit_cents=values[1],fulfillment_enabled=False)

