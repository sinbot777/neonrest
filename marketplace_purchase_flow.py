"""Durable bridge from accepted application quotes to fictional Stripe test payments.

No live keys, browser payment references, or public routes. Network retries reuse
immutable dispatch terms. Provider success does not itself settle or fulfill an
order: signed receipts/canonical reconciliation and settlement remain required.
"""
import json

if __package__:
    from . import marketplace_checkout as checkout, marketplace_inventory as inventory
    from . import marketplace_payments as payments, marketplace_quotes as quotes
    from . import marketplace_refunds as refunds, marketplace_payment_jobs as jobs
    from . import marketplace_settlement as settlement
    from .marketplace_test_checkout_api import StripeTestCheckoutAPI
else:
    import marketplace_checkout as checkout, marketplace_inventory as inventory
    import marketplace_payments as payments, marketplace_quotes as quotes
    import marketplace_refunds as refunds, marketplace_payment_jobs as jobs
    import marketplace_settlement as settlement
    from marketplace_test_checkout_api import StripeTestCheckoutAPI


class PurchaseError(ValueError):
    pass


SCHEMA = '''
CREATE TABLE IF NOT EXISTS marketplace_test_payment_dispatches (
 order_id TEXT PRIMARY KEY REFERENCES marketplace_checkout_orders(id),
 quote_id TEXT NOT NULL UNIQUE REFERENCES marketplace_checkout_quotes(id),
 buyer_id INTEGER NOT NULL REFERENCES users(id),
 account_id TEXT NOT NULL REFERENCES marketplace_payment_accounts(id),
 platform_ref TEXT NOT NULL,account_ref TEXT NOT NULL,
 total_cents INTEGER NOT NULL CHECK(total_cents>=50),
 payment_method TEXT NOT NULL CHECK(payment_method IN ('pm_card_visa','pm_card_chargeDeclined','pm_card_threeDSecure2Required')),
 created_at INTEGER NOT NULL,payment_ref TEXT UNIQUE,attempt_id TEXT UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('prepared','bound','review')),
 FOREIGN KEY(attempt_id) REFERENCES marketplace_payment_test_attempts(id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_test_dispatch_terms
BEFORE UPDATE ON marketplace_test_payment_dispatches
WHEN NEW.order_id!=OLD.order_id OR NEW.quote_id!=OLD.quote_id OR NEW.buyer_id!=OLD.buyer_id
 OR NEW.account_id!=OLD.account_id OR NEW.platform_ref!=OLD.platform_ref OR NEW.account_ref!=OLD.account_ref
 OR NEW.total_cents!=OLD.total_cents OR NEW.payment_method!=OLD.payment_method OR NEW.created_at!=OLD.created_at
 OR (OLD.payment_ref IS NOT NULL AND NEW.payment_ref IS NOT OLD.payment_ref)
 OR (OLD.attempt_id IS NOT NULL AND NEW.attempt_id IS NOT OLD.attempt_id)
 OR (OLD.state='bound' AND NEW.state!='bound')
BEGIN SELECT RAISE(ABORT,'payment dispatch terms are immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_dispatch_delete BEFORE DELETE ON marketplace_test_payment_dispatches
BEGIN SELECT RAISE(ABORT,'payment dispatch is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_submitted_hold_release BEFORE UPDATE OF state ON marketplace_inventory_holds
WHEN NEW.state='released' AND EXISTS (SELECT 1 FROM marketplace_checkout_orders o
 JOIN marketplace_test_payment_dispatches d ON d.order_id=o.id WHERE o.hold_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'submitted payment requires canonical recovery'); END;
CREATE TABLE IF NOT EXISTS marketplace_test_refund_dispatches (
 request_id TEXT PRIMARY KEY REFERENCES marketplace_test_refund_requests(id),
 created_at INTEGER NOT NULL,refund_ref TEXT UNIQUE
);
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_dispatch_update BEFORE UPDATE ON marketplace_test_refund_dispatches
WHEN NEW.request_id!=OLD.request_id OR NEW.created_at!=OLD.created_at OR
 (OLD.refund_ref IS NOT NULL AND NEW.refund_ref IS NOT OLD.refund_ref)
BEGIN SELECT RAISE(ABORT,'refund dispatch identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_refund_dispatch_delete BEFORE DELETE ON marketplace_test_refund_dispatches
BEGIN SELECT RAISE(ABORT,'refund dispatch is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_dispatched_refund_withdrawal BEFORE INSERT ON marketplace_test_refund_withdrawals
WHEN EXISTS (SELECT 1 FROM marketplace_test_refund_dispatches WHERE request_id=NEW.request_id)
BEGIN SELECT RAISE(ABORT,'submitted refund requires canonical recovery'); END;
'''


def initialize(db):
    if db.in_transaction: raise PurchaseError('dedicated connection required')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def _api(api):
    if not isinstance(api, StripeTestCheckoutAPI) or api.scope.environment != 'test':
        raise PurchaseError('configured fictional-card Stripe test API required')


def _scope(api, row):
    if api.scope.platform != row['platform_ref']:
        raise PurchaseError('payment platform mismatch')


def _public_order(db, order_id, buyer, policy):
    order=db.execute('SELECT snapshot FROM marketplace_checkout_orders WHERE id=? AND buyer_id=?',(order_id,buyer)).fetchone()
    if not order: raise PurchaseError('buyer order unavailable')
    snapshot=json.loads(order['snapshot'])
    published=getattr(policy,'published',None)
    if not callable(published): raise PurchaseError('trusted publication policy required')
    for line in snapshot['lines']:
        if line['kind']!='physical' or published(db,line['listing_id'],buyer) is not True:
            raise PurchaseError('only published physical listings are supported by this pilot')


class _PublishedOrderPolicy:
    def __init__(self, base, order_id): self.base=base;self.order_id=order_id
    def __getattr__(self, name): return getattr(self.base,name)
    def visible(self, db, shop, buyer):
        try: _public_order(db,self.order_id,buyer,self.base)
        except ValueError: return False
        return self.base.visible(db,shop,buyer)


def prepare_payment(db, buyer, quote_id, location_resolver, payment_method, now, policy=checkout.NeonrestPolicy):
    """Persist exact accepted terms before any network side effect."""
    if payment_method not in StripeTestCheckoutAPI.METHODS:
        raise PurchaseError('only fictional Stripe test cards are accepted')
    result=quotes.get_quote(db,buyer,quote_id,location_resolver,now,policy)
    location=quotes.Location(**result['snapshot']['location'])
    with inventory.transaction(db):
        quotes._assert_local_location(location_resolver,buyer,location.seller_ref,location)
        quote=quotes._fresh_quote(db,buyer,quote_id,location,now,policy)
        _public_order(db,quote['order_id'],buyer,policy)
        if not db.execute('SELECT 1 FROM marketplace_checkout_quote_acceptances WHERE quote_id=? AND buyer_id=? AND order_id=?',
                          (quote_id,buyer,quote['order_id'])).fetchone():
            raise PurchaseError('accept the complete quote before paying')
        account=db.execute('''SELECT a.* FROM marketplace_payment_accounts a
          JOIN marketplace_payment_shop_links l ON l.account_id=a.id AND l.owner_id=a.owner_id
          JOIN marketplace_checkout_orders o ON o.seller_ref=l.seller_ref AND o.seller_owner_id=a.owner_id
          WHERE o.id=? AND l.environment='test' AND l.provider='stripe' AND a.environment='test' AND a.provider='stripe' ''',
          (quote['order_id'],)).fetchone()
        if not account or not account['charges_enabled'] or not account['payouts_enabled']:
            raise PurchaseError('verified test seller association is not ready')
        total=json.loads(quote['snapshot'])['total_cents']
        if type(total) is not int or not 50 <= total <= 100_000_000:
            raise PurchaseError('bounded complete test total required')
        previous=db.execute('SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=?',(quote['order_id'],)).fetchone()
        if previous:
            if (previous['buyer_id'],previous['quote_id'],previous['account_id'],previous['total_cents'],previous['payment_method'])!=(buyer,quote_id,account['id'],total,payment_method):
                raise PurchaseError('payment terms already fixed; do not create another payment')
            return previous['order_id']
        db.execute('INSERT INTO marketplace_test_payment_dispatches VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,\'prepared\')',
                   (quote['order_id'],quote_id,buyer,account['id'],account['platform_ref'],account['account_ref'],total,payment_method,now))
        return quote['order_id']


def dispatch_payment(db, buyer, order_id, api, location_resolver, now, policy=checkout.NeonrestPolicy, clock=None):
    """Timeout/crash retry uses the same provider idempotency key and exact terms.

    If the quote expires during creation, retain the provider reference for review
    instead of losing it or attempting another charge. Never return client secrets.
    """
    _api(api);inventory.clock(now)
    if db.in_transaction: raise PurchaseError('network dispatch requires an idle connection')
    row=db.execute('SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=? AND buyer_id=?',(order_id,buyer)).fetchone()
    if not row: raise PurchaseError('buyer test payment dispatch unavailable')
    checkout.get_order(db,'test',buyer,order_id,now,policy);_scope(api,row)
    if row['state']=='bound':
        return dict(order_id=order_id,state='bound',payment_ref=row['payment_ref'],attempt_id=row['attempt_id'])
    if row['state']=='review':
        return dict(order_id=order_id,state='review',payment_ref=row['payment_ref'],attempt_id=None)
    # Recheck accepted terms and ownership before a first/retried provider call.
    payments.refresh_account(db,row['account_id'],api,now)
    prepare_payment(db,buyer,row['quote_id'],location_resolver,row['payment_method'],now,policy)
    value=api.create_payment(row['account_ref'],order_id,row['quote_id'],row['total_cents'],row['payment_method'])
    finished=clock() if clock else now;inventory.clock(finished)
    if finished < now: raise PurchaseError('dispatch clock moved backwards')
    with inventory.transaction(db):
        current=db.execute('SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=?',(order_id,)).fetchone()
        if current['payment_ref'] and current['payment_ref']!=value['payment_ref']:
            raise PurchaseError('provider returned conflicting payment identity')
        db.execute('UPDATE marketplace_test_payment_dispatches SET payment_ref=? WHERE order_id=?',(value['payment_ref'],order_id))
    try:
        attempt=payments.track_quoted_test_payment(db,buyer,row['quote_id'],row['account_id'],value['payment_ref'],location_resolver,finished,_PublishedOrderPolicy(policy,order_id))
    except ValueError:
        with inventory.transaction(db):
            db.execute("UPDATE marketplace_test_payment_dispatches SET state='review' WHERE order_id=? AND state!='bound'",(order_id,))
        return dict(order_id=order_id,state='review',payment_ref=value['payment_ref'],attempt_id=None)
    with inventory.transaction(db):
        db.execute("UPDATE marketplace_test_payment_dispatches SET state='bound',attempt_id=? WHERE order_id=?",(attempt,order_id))
    return dict(order_id=order_id,state='bound',payment_ref=value['payment_ref'],attempt_id=attempt)


def settle_received_payment(db, receipt_id, location_resolver, now, policy=checkout.NeonrestPolicy):
    row=db.execute('''SELECT a.order_id,a.observed_status,e.outcome,e.reason FROM marketplace_payment_events e
       JOIN marketplace_payment_test_attempts a ON a.id=e.attempt_id WHERE e.id=? AND e.environment='test' AND e.provider='stripe' ''',(receipt_id,)).fetchone()
    if not row: raise PurchaseError('bound verified payment receipt required')
    if row['outcome']=='needs_review':
        return dict(outcome='needs_review',reason=row['reason'])
    if row['outcome']!='observed_test' or row['observed_status']!='succeeded':
        return dict(outcome='not_settled',reason='verified_success_required')
    return settlement.settle_test_receipt(db,receipt_id,location_resolver,now,_PublishedOrderPolicy(policy,row['order_id']))


def cancel_unsubmitted_order(db, buyer, order_id, now, policy=checkout.NeonrestPolicy):
    return checkout.cancel_order(db,'test',buyer,order_id,now,policy)


def recover_early_receipts(db, order_id, adapter, now, policy=checkout.NeonrestPolicy):
    """Reconcile already-signature-verified events that arrived before binding.

    This is a bounded internal worker step, not a browser success callback. Other
    review outcomes are never automatically cleared. No event is fabricated.
    """
    row=db.execute("SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=? AND state='bound'",(order_id,)).fetchone()
    if not row: raise PurchaseError('bound dispatch required')
    _scope(adapter,row)
    ids=db.execute('''SELECT e.id FROM marketplace_payment_events e JOIN marketplace_payment_jobs j ON j.receipt_id=e.id
       WHERE e.environment='test' AND e.provider='stripe' AND e.platform_ref=? AND e.account_ref=? AND e.payment_ref=?
       AND e.outcome='needs_review' AND e.reason='unbound_payment' AND j.state='review' ORDER BY e.id LIMIT 25''',
       (row['platform_ref'],row['account_ref'],row['payment_ref'])).fetchall()
    results=[]
    for receipt in ids:
        lease=jobs.claim(db,adapter,now,receipt_id=receipt[0],redelivery=True)
        if lease: results.append(jobs.process_claim(db,adapter,lease,now,policy))
    return results


def recover_dispatch_from_receipt(db, receipt_id, adapter, location_resolver, now, policy=checkout.NeonrestPolicy, expected_order_id=None):
    """Recover a lost creation response from a retained, verified provider event.

    Canonical metadata must match the immutable dispatch and full total. This
    never creates another payment and never invents a signed event or consent.
    """
    inventory.clock(now)
    if db.in_transaction: raise PurchaseError('canonical lookup requires an idle connection')
    receipt=db.execute("SELECT * FROM marketplace_payment_events WHERE id=? AND environment='test' AND provider='stripe'",(receipt_id,)).fetchone()
    if not receipt or receipt['platform_ref']!=adapter.scope.platform or receipt['event_type'] not in adapter.TYPES:
        raise PurchaseError('verified supported payment receipt required')
    value=adapter.canonical(receipt['account_ref'],receipt['payment_ref'])
    if expected_order_id is not None and value['order']!=expected_order_id:
        raise PurchaseError('receipt belongs to a different order')
    row=db.execute('SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=?',(value['order'],)).fetchone()
    if (not row or (row['platform_ref'],row['account_ref'],row['quote_id'],row['total_cents']) !=
            (receipt['platform_ref'],receipt['account_ref'],value['quote'],value['amount']) or value['currency']!='usd'):
        raise PurchaseError('verified payment does not match prepared dispatch')
    with inventory.transaction(db):
        current=db.execute('SELECT * FROM marketplace_test_payment_dispatches WHERE order_id=?',(row['order_id'],)).fetchone()
        if current['payment_ref'] and current['payment_ref']!=receipt['payment_ref']: raise PurchaseError('conflicting payment identity requires review')
        db.execute('UPDATE marketplace_test_payment_dispatches SET payment_ref=? WHERE order_id=?',(receipt['payment_ref'],row['order_id']))
        already_bound=current['state']=='bound'
    if already_bound:
        recover_early_receipts(db,row['order_id'],adapter,now,policy)
        return dict(state='bound',order_id=row['order_id'],payment_ref=receipt['payment_ref'])
    try:
        attempt=payments.track_quoted_test_payment(db,row['buyer_id'],row['quote_id'],row['account_id'],receipt['payment_ref'],location_resolver,now,_PublishedOrderPolicy(policy,row['order_id']))
    except ValueError:
        with inventory.transaction(db):
            db.execute("UPDATE marketplace_test_payment_dispatches SET state='review' WHERE order_id=? AND state!='bound'",(row['order_id'],))
        return dict(state='review',order_id=row['order_id'],payment_ref=receipt['payment_ref'])
    with inventory.transaction(db):
        db.execute("UPDATE marketplace_test_payment_dispatches SET state='bound',attempt_id=? WHERE order_id=?",(attempt,row['order_id']))
    recover_early_receipts(db,row['order_id'],adapter,now,policy)
    return dict(state='bound',order_id=row['order_id'],payment_ref=receipt['payment_ref'])


def dispatch_refund(db, owner, request_id, api, now, policy=checkout.NeonrestPolicy):
    """Persist dispatch first, then create/bind exactly the authorized test refund."""
    _api(api);inventory.clock(now)
    if db.in_transaction: raise PurchaseError('network dispatch requires an idle connection')
    with inventory.transaction(db):
        request=db.execute('SELECT * FROM marketplace_test_refund_requests WHERE id=? AND owner_id=?',(request_id,owner)).fetchone()
        if not request: raise PurchaseError('owner test refund request unavailable')
        _,order,attempt,account,_=refunds._historical(db,request['order_id'])
        refunds._owner(db,owner,order,policy);_scope(api,account)
        if db.execute('SELECT 1 FROM marketplace_test_refund_withdrawals WHERE request_id=?',(request_id,)).fetchone():
            raise PurchaseError('withdrawn test refund cannot be submitted')
        if not db.execute('SELECT 1 FROM marketplace_test_refund_dispatches WHERE request_id=?',(request_id,)).fetchone():
            db.execute('INSERT INTO marketplace_test_refund_dispatches VALUES (?,?,NULL)',(request_id,now))
        sent=db.execute('SELECT refund_ref FROM marketplace_test_refund_dispatches WHERE request_id=?',(request_id,)).fetchone()[0]
    if not sent:
        value=api.create_refund(account['account_ref'],attempt['payment_ref'],order['id'],request_id,request['amount_cents'])
        sent=value['refund_ref']
        with inventory.transaction(db):
            current=db.execute('SELECT refund_ref FROM marketplace_test_refund_dispatches WHERE request_id=?',(request_id,)).fetchone()[0]
            if current and current!=sent: raise PurchaseError('provider returned conflicting refund identity')
            db.execute('UPDATE marketplace_test_refund_dispatches SET refund_ref=? WHERE request_id=?',(sent,request_id))
    refunds.bind_test_refund(db,request_id,sent,now)
    return dict(request_id=request_id,refund_ref=sent,state='bound')
