"""Explicit, server-only test settlement; no live activation or fulfillment.

Consumes a reconciled Stripe test receipt, never a browser success flag. Synthetic
settlement allocates a complete accepted quote in a balanced test journal. No
provider money movement, actual fee reconciliation, tax remittance, refunds,
notifications, file grants or shipment authority is implemented by this module.
"""
import hashlib
import json

if __package__:
    from . import marketplace_addresses as addresses, marketplace_checkout as checkout
    from . import marketplace_inventory as inventory, marketplace_ledger as ledger
    from . import marketplace_quotes as quotes
    from .marketplace_core import cents
else:
    import marketplace_addresses as addresses
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory
    import marketplace_ledger as ledger
    import marketplace_quotes as quotes
    from marketplace_core import cents


class SettlementError(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_test_settlements (
 order_id TEXT PRIMARY KEY REFERENCES marketplace_checkout_orders(id),
 environment TEXT NOT NULL CHECK(environment='test'),
 attempt_id TEXT NOT NULL UNIQUE REFERENCES marketplace_payment_test_attempts(id),
 receipt_id INTEGER NOT NULL UNIQUE REFERENCES marketplace_payment_events(id),
 quote_id TEXT NOT NULL UNIQUE REFERENCES marketplace_checkout_quote_acceptances(quote_id),
 hold_id TEXT NOT NULL UNIQUE REFERENCES marketplace_inventory_consumptions(hold_id),
 journal_id INTEGER NOT NULL UNIQUE REFERENCES marketplace_ledger_journals(id),
 settled_at INTEGER NOT NULL,allocation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS marketplace_test_settlement_reviews (
 attempt_id TEXT PRIMARY KEY REFERENCES marketplace_payment_test_attempts(id),
 receipt_id INTEGER NOT NULL REFERENCES marketplace_payment_events(id),
 reason TEXT NOT NULL CHECK(reason IN ('another_winning_payment','checkout_no_longer_eligible')),
 created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS marketplace_test_settlement_update BEFORE UPDATE ON marketplace_test_settlements
BEGIN SELECT RAISE(ABORT,'settlement is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_settlement_delete BEFORE DELETE ON marketplace_test_settlements
BEGIN SELECT RAISE(ABORT,'settlement is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_settlement_review_update BEFORE UPDATE ON marketplace_test_settlement_reviews
BEGIN SELECT RAISE(ABORT,'review requires separate resolution history'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_settlement_review_delete BEFORE DELETE ON marketplace_test_settlement_reviews
BEGIN SELECT RAISE(ABORT,'review is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_settlement_validate BEFORE INSERT ON marketplace_test_settlements
WHEN NOT EXISTS (SELECT 1 FROM marketplace_checkout_orders o
 JOIN marketplace_payment_test_attempts a ON a.id=NEW.attempt_id AND a.order_id=o.id
 JOIN marketplace_payment_events e ON e.id=NEW.receipt_id AND e.attempt_id=a.id
 JOIN marketplace_payment_quote_links l ON l.attempt_id=a.id AND l.quote_id=NEW.quote_id
 JOIN marketplace_inventory_consumptions c ON c.hold_id=o.hold_id
 JOIN marketplace_ledger_journals j ON j.id=NEW.journal_id AND j.environment='test' AND j.posted=1
 WHERE o.id=NEW.order_id AND o.environment='test' AND o.hold_id=NEW.hold_id
 AND a.environment='test' AND a.observed_status='succeeded' AND e.environment='test'
 AND e.outcome='observed_test' AND c.consumed_at=NEW.settled_at)
BEGIN SELECT RAISE(ABORT,'matching test settlement evidence required'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_settled_order_update BEFORE UPDATE ON marketplace_checkout_orders
WHEN EXISTS (SELECT 1 FROM marketplace_test_settlements WHERE order_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'settled order is retained'); END;
"""


def initialize(db):
    """Additive, explicit migration on an already initialized test candidate."""
    if db.in_transaction:
        raise SettlementError('dedicated connection required')
    ledger.initialize(db)
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def _result(row):
    return dict(outcome='test_settled',order_id=row['order_id'],journal_id=row['journal_id'],
        settled_at=row['settled_at'],allocation=json.loads(row['allocation']),fulfillment_enabled=False)


def _review(db,attempt,receipt,reason,now):
    db.execute('INSERT INTO marketplace_test_settlement_reviews VALUES (?,?,?,?)',
        (attempt['id'],receipt['id'],reason,now))
    return dict(outcome='needs_review',reason=reason,fulfillment_enabled=False)


def _allocation(order,quote):
    original=json.loads(order['snapshot']); total=json.loads(quote['snapshot'])
    for key in ('subtotal_cents','shipping_cents','tax_cents','total_cents','platform_fee_cents'):
        cents(total[key])
    if (original.get('test_only') is not True or original.get('payment_enabled') is not False
        or total.get('environment')!='test' or total.get('currency')!='USD'
        or total.get('payment_authorization_enabled') is not False
        or total['order_id']!=order['id'] or total['subtotal_cents']!=original['subtotal_cents']
        or total['platform_fee_cents']!=original['platform_fee_cents'] or total['fee_version']!=original['fee_version']
        or total['platform_fee_cents']>total['subtotal_cents']
        or total['total_cents']!=total['subtotal_cents']+total['shipping_cents']+total['tax_cents']
        or total['total_cents']<=0):
        raise SettlementError('invalid complete test allocation')
    return dict(currency='USD',total_cents=total['total_cents'],
        item_cents=total['subtotal_cents'],shipping_cents=total['shipping_cents'],tax_cents=total['tax_cents'],
        platform_fee_cents=total['platform_fee_cents'],fee_version=total['fee_version'],
        seller_obligation_cents=total['subtotal_cents']+total['shipping_cents']-total['platform_fee_cents'],
        processor_cost_cents=None,provider_transfer_verified=False,tax_remittance_verified=False)


def _ledger_definitions(order,account,allocation):
    # Separate scope-bound test clearing, seller obligation, fee and tax accounts.
    # This allocation does not claim the processor has transferred money or that
    # the eventual approved marketplace charge/tax model uses these accounts.
    scope=hashlib.sha256(json.dumps([account['provider'],account['platform_ref'],account['account_ref']],separators=(',',':')).encode()).hexdigest()
    seller=hashlib.sha256(json.dumps([order['seller_ref'],order['seller_owner_id']],separators=(',',':')).encode()).hexdigest()
    return [('qa-clearing-'+scope,'provider-'+scope,'asset',allocation['total_cents']),
        ('qa-seller-'+seller,'seller-'+seller,'liability',-allocation['seller_obligation_cents']),
        ('qa-fee','platform','income',-allocation['platform_fee_cents']),
        ('qa-tax-'+scope,'unallocated-tax-'+scope,'liability',-allocation['tax_cents'])]


def _journal_locked(db,order,account,attempt,allocation,now):
    definitions=_ledger_definitions(order,account,allocation)
    entries=[]
    for ident,owner,kind,amount in definitions:
        expected=(ident,'test',owner,kind,'USD')
        old=db.execute('SELECT id,environment,owner,kind,currency FROM marketplace_ledger_accounts WHERE id=?',(ident,)).fetchone()
        if old is not None and tuple(old)!=expected:
            raise SettlementError('test ledger account conflict')
        if old is None:
            db.execute('INSERT INTO marketplace_ledger_accounts VALUES (?,?,?,?,?)',expected)
        if amount: entries.append((ident,amount))
    return ledger._post_locked(db,'test','qa-settle-'+order['id'],'qa-attempt-'+attempt['id'],entries,now)


def settle_test_receipt(db,receipt_id,location_resolver,now,policy=checkout.NeonrestPolicy):
    """Explicit trusted worker step after reconciliation, never a public endpoint.

    Idempotent settlement and terminal review are per attempt. The caller must
    retry this step after a crash independently of the receipt processing job;
    marking that job done does not imply settlement has run. Time is server-owned.
    Native DB-local address validation is required; no network runs under the lock.
    """
    inventory.clock(now)
    if type(receipt_id) is not int or receipt_id<=0:
        raise SettlementError('internal receipt identifier required')
    if type(location_resolver) is not addresses.AddressResolver or location_resolver.store.db is not db:
        raise SettlementError('native same-connection address resolver required')
    with inventory.transaction(db):
        receipt=db.execute('SELECT * FROM marketplace_payment_events WHERE id=?',(receipt_id,)).fetchone()
        attempt=db.execute('SELECT * FROM marketplace_payment_test_attempts WHERE id=?',(receipt['attempt_id'],)).fetchone() if receipt else None
        if (not receipt or not attempt or receipt['environment']!='test' or receipt['provider']!='stripe'
            or attempt['environment']!='test' or receipt['outcome']!='observed_test'
            or attempt['observed_status']!='succeeded' or receipt['checked_at'] is None
            or attempt['observed_at'] is None or now<max(receipt['checked_at'],attempt['observed_at'])):
            raise SettlementError('reconciled successful Stripe test receipt required')
        order=db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=?',(attempt['order_id'],)).fetchone()
        account=db.execute('SELECT * FROM marketplace_payment_accounts WHERE id=?',(attempt['account_id'],)).fetchone()
        if (not order or order['environment']!='test' or not account
            or (account['environment'],account['provider'],account['platform_ref'],account['account_ref'])
            !=('test','stripe',receipt['platform_ref'],receipt['account_ref']) or attempt['payment_ref']!=receipt['payment_ref']):
            raise SettlementError('receipt account/order binding mismatch')
        winner=db.execute('SELECT * FROM marketplace_test_settlements WHERE order_id=?',(order['id'],)).fetchone()
        if winner and winner['attempt_id']==attempt['id']:
            return _result(winner)
        review=db.execute('SELECT reason FROM marketplace_test_settlement_reviews WHERE attempt_id=?',(attempt['id'],)).fetchone()
        if review:
            return dict(outcome='needs_review',reason=review['reason'],fulfillment_enabled=False)
        if winner:
            return _review(db,attempt,receipt,'another_winning_payment',now)
        link=db.execute('SELECT * FROM marketplace_payment_quote_links WHERE attempt_id=?',(attempt['id'],)).fetchone()
        if not link:
            raise SettlementError('subtotal-only rehearsal cannot settle')
        quote=db.execute('SELECT * FROM marketplace_checkout_quotes WHERE id=?',(link['quote_id'],)).fetchone()
        consent=db.execute('SELECT * FROM marketplace_checkout_quote_acceptances WHERE quote_id=?',(link['quote_id'],)).fetchone()
        if (not quote or not consent or quote['order_id']!=order['id'] or consent['order_id']!=order['id']
            or consent['buyer_id']!=order['buyer_id'] or quote['buyer_id']!=order['buyer_id']
            or link['expires_at']!=quote['expires_at'] or attempt['currency']!='USD'):
            raise SettlementError('accepted quote binding required')
        allocation=_allocation(order,quote)
        if attempt['expected_amount_cents']!=allocation['total_cents']:
            raise SettlementError('complete test payment amount mismatch')
        # Recheck eligibility, terms, location and all stock lines in this lock.
        try:
            snap=json.loads(quote['snapshot'])
            if snap.get('location_snapshot_bound') is not True:
                raise ValueError('native address snapshot required')
            location=quotes.Location(**snap['location'])
            location_resolver.assert_current_location(order['buyer_id'],order['seller_ref'],location)
            quotes._fresh_quote(db,order['buyer_id'],quote['id'],location,now,policy)
            linked=db.execute("SELECT 1 FROM marketplace_payment_shop_links WHERE environment='test' AND seller_ref=? AND owner_id=? AND account_id=?",
                (order['seller_ref'],order['seller_owner_id'],account['id'])).fetchone()
            if not linked or account['owner_id']!=order['seller_owner_id'] or not account['charges_enabled'] or not account['payouts_enabled']:
                raise ValueError('payment account unavailable')
            hold=db.execute('SELECT * FROM marketplace_inventory_holds WHERE id=?',(order['hold_id'],)).fetchone()
            if not hold or (hold['environment'],hold['seller_ref'],hold['buyer_ref'],hold['created_at'],hold['expires_at']) != ('test',order['seller_ref'],str(order['buyer_id']),order['created_at'],order['expires_at']):
                raise ValueError('reservation identity mismatch')
            expected=sorted((x['sku'],x['quantity']) for x in json.loads(order['snapshot'])['lines'])
            held=[tuple(r) for r in db.execute('SELECT sku,quantity FROM marketplace_inventory_hold_lines WHERE hold_id=? ORDER BY sku',(order['hold_id'],))]
            if held!=expected:
                raise ValueError('reservation line mismatch')
        except ValueError:
            return _review(db,attempt,receipt,'checkout_no_longer_eligible',now)
        journal=_journal_locked(db,order,account,attempt,allocation,now)
        db.execute('INSERT INTO marketplace_inventory_consumptions VALUES (?,?)',(order['hold_id'],now))
        db.execute('INSERT INTO marketplace_test_settlements VALUES (?,?,?,?,?,?,?,?,?)',
            (order['id'],'test',attempt['id'],receipt_id,quote['id'],order['hold_id'],journal,now,json.dumps(allocation,sort_keys=True,separators=(',',':'))))
        return _result(db.execute('SELECT * FROM marketplace_test_settlements WHERE order_id=?',(order['id'],)).fetchone())


def run_ready(db,location_resolver,now,limit=25,policy=checkout.NeonrestPolicy,clock=None):
    """One bounded server-only tick; no schedule, sleep, provider calls or activation.

    Durable successful observations lacking settlement/review are the recovery
    queue. Each attempt commits independently; a failed transaction remains due.
    Multiple ticks may overlap because settle_test_receipt serializes/rechecks.
    Scope is this isolated test database, not a public seller-selected queue.
    """
    inventory.clock(now)
    if type(limit) is not int or not 1<=limit<=100 or db.in_transaction:
        raise SettlementError('dedicated connection and bounded batch required')
    receipts=db.execute("""SELECT MIN(e.id) AS id FROM marketplace_payment_events e
        JOIN marketplace_payment_test_attempts a ON a.id=e.attempt_id
        WHERE e.environment='test' AND e.provider='stripe' AND e.outcome='observed_test'
        AND a.environment='test' AND a.observed_status='succeeded'
        AND NOT EXISTS (SELECT 1 FROM marketplace_test_settlements s WHERE s.attempt_id=a.id)
        AND NOT EXISTS (SELECT 1 FROM marketplace_test_settlement_reviews r WHERE r.attempt_id=a.id)
        GROUP BY a.id ORDER BY MIN(e.id) LIMIT ?""",(limit,)).fetchall()
    results=[]
    current=now
    for receipt in receipts:
        if clock is not None:
            measured=clock();inventory.clock(measured);current=max(current,measured)
        results.append(settle_test_receipt(db,receipt['id'],location_resolver,current,policy))
    return results
