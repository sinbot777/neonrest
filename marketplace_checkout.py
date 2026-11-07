"""Inactive checkout rehearsal using real-order-shaped, immutable records.

No routes, startup registration, provider calls or live paid-state transition. Only
test mode is accepted until onboarding, publication, shipping/tax and canonical
payment processing are integrated. Test records can never be promoted to live.
"""
import hashlib
import json
import uuid

if __package__:
    from . import marketplace_inventory as inventory
    from .marketplace_core import quote
else:
    import marketplace_inventory as inventory
    from marketplace_core import quote


class CheckoutError(ValueError):
    pass


class NeonrestPolicy:
    """Trusted adapter to existing site policy, loaded lazily for package use."""
    @staticmethod
    def adult(db, uid):
        from .seller_studio import adult_account
        return adult_account(db, uid)

    @staticmethod
    def owner(db, uid, shop):
        from .seller_studio import access
        page, current = access(db, uid, shop['page_id'], owner_only=True)
        return bool(current and current['owner_id'] == uid and page['state'] != 'archived')

    @staticmethod
    def visible(db, shop, buyer):
        from .marketplace_catalog import allowed
        return allowed(db, shop, buyer)

    @staticmethod
    def fee_waived(db, shop):
        from .marketplace_catalog import fee_policy
        return fee_policy(db, shop)


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_checkout_skus (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK(environment='test'),
    seller_ref TEXT NOT NULL REFERENCES seller_shops(page_id),
    seller_owner_id INTEGER NOT NULL REFERENCES users(id),
    listing_id TEXT NOT NULL REFERENCES seller_listings(id),
    variant_key TEXT NOT NULL,
    listing_revision INTEGER NOT NULL CHECK(listing_revision>=0),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    UNIQUE(environment,listing_id,variant_key),
    UNIQUE(id,environment,seller_ref)
);
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_sku_identity
BEFORE UPDATE ON marketplace_checkout_skus
WHEN NEW.id != OLD.id OR NEW.environment != OLD.environment OR NEW.seller_ref != OLD.seller_ref
 OR NEW.seller_owner_id != OLD.seller_owner_id OR NEW.listing_id != OLD.listing_id OR NEW.variant_key != OLD.variant_key
BEGIN SELECT RAISE(ABORT,'stock identity is immutable'); END;
CREATE TABLE IF NOT EXISTS marketplace_checkout_orders (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK(environment='test'),
    buyer_id INTEGER NOT NULL REFERENCES users(id),
    seller_ref TEXT NOT NULL REFERENCES seller_shops(page_id),
    seller_owner_id INTEGER NOT NULL REFERENCES users(id),
    request_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    hold_id TEXT NOT NULL UNIQUE,
    snapshot TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at>created_at),
    state TEXT NOT NULL CHECK(state IN ('awaiting_payment','canceled','expired')),
    UNIQUE(environment,buyer_id,request_key),
    FOREIGN KEY(hold_id,environment,seller_ref) REFERENCES marketplace_inventory_holds(id,environment,seller_ref)
);
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_order_insert
BEFORE INSERT ON marketplace_checkout_orders
WHEN NEW.state != 'awaiting_payment' OR NOT EXISTS (
 SELECT 1 FROM marketplace_inventory_holds h WHERE h.id=NEW.hold_id
 AND h.environment=NEW.environment AND h.seller_ref=NEW.seller_ref
 AND h.buyer_ref=CAST(NEW.buyer_id AS TEXT) AND h.state='reserved'
 AND h.created_at=NEW.created_at AND h.expires_at=NEW.expires_at)
BEGIN SELECT RAISE(ABORT,'order requires matching reservation'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_order_update
BEFORE UPDATE ON marketplace_checkout_orders
WHEN OLD.state != 'awaiting_payment' OR NEW.state NOT IN ('canceled','expired')
 OR NEW.id != OLD.id OR NEW.environment != OLD.environment OR NEW.buyer_id != OLD.buyer_id
 OR NEW.seller_ref != OLD.seller_ref OR NEW.seller_owner_id != OLD.seller_owner_id
 OR NEW.request_key != OLD.request_key OR NEW.payload_hash != OLD.payload_hash
 OR NEW.hold_id != OLD.hold_id OR NEW.snapshot != OLD.snapshot
 OR NEW.created_at != OLD.created_at OR NEW.expires_at != OLD.expires_at
 OR NOT EXISTS (SELECT 1 FROM marketplace_inventory_holds h WHERE h.id=NEW.hold_id
   AND ((NEW.state='canceled' AND h.state='released') OR (NEW.state='expired' AND h.state='expired')))
BEGIN SELECT RAISE(ABORT,'order terms are immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_order_delete
BEFORE DELETE ON marketplace_checkout_orders
BEGIN SELECT RAISE(ABORT,'order is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_hold_release
AFTER UPDATE OF state ON marketplace_inventory_holds
WHEN NEW.state IN ('released','expired')
BEGIN UPDATE marketplace_checkout_orders SET state=CASE NEW.state WHEN 'released' THEN 'canceled' ELSE 'expired' END
 WHERE hold_id=NEW.id AND state='awaiting_payment'; END;
CREATE INDEX IF NOT EXISTS marketplace_checkout_buyer_orders
ON marketplace_checkout_orders(environment,buyer_id,created_at,id);
CREATE INDEX IF NOT EXISTS marketplace_checkout_seller_orders
ON marketplace_checkout_orders(environment,seller_ref,seller_owner_id,created_at,id);
CREATE INDEX IF NOT EXISTS marketplace_checkout_expiry
ON marketplace_checkout_orders(environment,state,expires_at,id);
"""


def initialize(db):
    """Explicit opt-in migration, never called by application startup."""
    if db.in_transaction:
        raise CheckoutError('dedicated connection required')
    inventory.initialize(db)
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')


def test_mode(env):
    if env != 'test':
        raise CheckoutError('live checkout is not enabled')


def actor(policy, db, uid):
    if type(uid) is not int or uid <= 0 or not policy.adult(db, uid):
        raise CheckoutError('eligible adult account required')


def shop_row(db, shop_id):
    row = db.execute('SELECT * FROM seller_shops WHERE page_id=?', (shop_id,)).fetchone()
    if not row:
        raise CheckoutError('shop unavailable')
    return row


def listing_options(listing):
    variants = json.loads(listing['variations'])
    options = [('base', '', listing['price_cents'], listing['quantity'])] if not variants else [
        ('variant:' + v['label'].casefold(), v['label'], v['price_cents'], v['quantity']) for v in variants]
    if len({o[0] for o in options}) != len(options):
        raise CheckoutError('duplicate variation identity')
    return options


def sync_listing(db, env, uid, shop_id, listing_id, revision, now, policy=NeonrestPolicy):
    """Owner-only test provisioning. Reordering preserves a SKU; renaming creates one.

    The existing editor has no stable variation IDs. Old renamed/removed IDs are
    deactivated, never reassigned. Active old holds remain valid until release.
    """
    test_mode(env)
    inventory.clock(now)
    with inventory.transaction(db):
        actor(policy, db, uid)
        shop = shop_row(db, shop_id)
        if shop['owner_id'] != uid or not policy.owner(db, uid, shop):
            raise CheckoutError('shop owner permission required')
        listing = db.execute('SELECT * FROM seller_listings WHERE id=? AND shop_id=?', (listing_id, shop_id)).fetchone()
        if not listing or listing['state'] != 'draft' or type(revision) is not int or listing['revision'] != revision:
            raise CheckoutError('listing changed or unavailable')
        if db.execute('''SELECT 1 FROM marketplace_checkout_skus m
            JOIN marketplace_inventory_hold_lines l ON l.sku=m.id AND l.environment=m.environment AND l.seller_ref=m.seller_ref
            JOIN marketplace_inventory_consumptions c ON c.hold_id=l.hold_id
            WHERE m.listing_id=?''',(listing_id,)).fetchone():
            raise CheckoutError('sold test stock requires explicit inventory adjustment; listing sync cannot reset it')
        options = listing_options(listing)
        previous = db.execute('SELECT id,variant_key FROM marketplace_checkout_skus WHERE environment=? AND listing_id=? AND active=1', (env, listing_id)).fetchall()
        if {row['variant_key'] for row in previous} != {o[0] for o in options}:
            for row in previous:
                current = db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE environment=? AND seller_ref=? AND sku=?', (env, shop_id, row['id'])).fetchone()
                if current and inventory.available(db, env, shop_id, row['id'], now) < current[0]:
                    raise CheckoutError('variation changes require releasing active reservations')
        db.execute('UPDATE marketplace_checkout_skus SET active=0 WHERE environment=? AND listing_id=?', (env, listing_id))
        result = []
        for key, label, price, quantity in options:
            if type(quantity) is not int or not 0 <= quantity <= 1_000_000:
                raise CheckoutError('invalid stock quantity')
            quote(price, kind=listing['kind'])
            old = db.execute('SELECT id,seller_owner_id FROM marketplace_checkout_skus WHERE environment=? AND listing_id=? AND variant_key=?', (env, listing_id, key)).fetchone()
            if old and old['seller_owner_id'] != uid:
                raise CheckoutError('shop ownership changed; support review required')
            sku = old['id'] if old else uuid.uuid4().hex
            db.execute('''INSERT INTO marketplace_checkout_skus VALUES (?,?,?,?,?,?,?,1)
                ON CONFLICT(environment,listing_id,variant_key) DO UPDATE SET listing_revision=excluded.listing_revision,active=1''',
                (sku, env, shop_id, uid, listing_id, key, revision))
            inventory._set_stock_locked(db, env, shop_id, sku, quantity, now)
            result.append({'sku': sku, 'variant': label, 'revision': revision})
        return result


def create_order(db, env, buyer, shop_id, request_key, lines, now, policy=NeonrestPolicy):
    """Cart lines are (SKU, quantity, expected listing revision), never prices/fees.

    This rehearsal explicitly has no final shipping/tax amount and cannot start a
    payment. Future provider calls require a complete authorized expiring quote.
    """
    test_mode(env)
    inventory.identity(env, shop_id, request_key)
    inventory.clock(now)
    if not isinstance(lines, (tuple, list)) or not 1 <= len(lines) <= 50:
        raise CheckoutError('expected 1–50 cart lines')
    normalized = []
    for line in lines:
        if not isinstance(line, (tuple, list)) or len(line) != 3:
            raise CheckoutError('invalid cart line')
        sku, quantity, revision = line
        inventory.identity(env, sku)
        if type(quantity) is not int or not 1 <= quantity <= 99 or type(revision) is not int or revision < 0:
            raise CheckoutError('invalid cart quantity or revision')
        normalized.append((sku, quantity, revision))
    normalized.sort()
    if len({s for s, _, _ in normalized}) != len(normalized):
        raise CheckoutError('duplicate stock item')
    digest = hashlib.sha256(json.dumps([shop_id, normalized], separators=(',', ':')).encode()).hexdigest()
    with inventory.transaction(db):
        actor(policy, db, buyer)
        shop = shop_row(db, shop_id)
        actor(policy, db, shop['owner_id'])
        if buyer == shop['owner_id'] or not policy.visible(db, shop, buyer):
            raise CheckoutError('shop unavailable')
        old = db.execute('SELECT id,payload_hash,seller_owner_id FROM marketplace_checkout_orders WHERE environment=? AND buyer_id=? AND request_key=?', (env, buyer, request_key)).fetchone()
        if old:
            if old['payload_hash'] != digest or old['seller_owner_id'] != shop['owner_id']:
                raise CheckoutError('idempotency conflict')
            return old['id']
        snapshots = []
        subtotal = 0
        for sku, quantity, revision in normalized:
            item = db.execute('''SELECT l.*,m.variant_key,m.listing_revision AS stock_revision,m.seller_owner_id
                FROM marketplace_checkout_skus m JOIN seller_listings l ON l.id=m.listing_id
                WHERE m.id=? AND m.environment=? AND m.seller_ref=? AND m.active=1 AND l.shop_id=m.seller_ref''', (sku, env, shop_id)).fetchone()
            if not item or item['seller_owner_id'] != shop['owner_id'] or item['state'] != 'draft':
                raise CheckoutError('stock item unavailable')
            if item['revision'] != revision or item['stock_revision'] != revision:
                raise CheckoutError('listing changed; refresh checkout')
            option = next((o for o in listing_options(item) if o[0] == item['variant_key']), None)
            if option is None:
                raise CheckoutError('variation unavailable')
            unit_price = option[2]
            quote(unit_price, kind=item['kind'])
            subtotal += unit_price * quantity
            snapshots.append(dict(listing_id=item['id'], revision=revision, sku=sku,
                title=item['title'], description=item['description'], variant=option[1], kind=item['kind'],
                quantity=quantity, unit_price_cents=unit_price, delivery=item['delivery'],
                license=item['license'], returns=item['returns']))
        totals = quote(subtotal)
        waived = bool(policy.fee_waived(db, shop))
        if waived:
            totals.update(platform_fee=0, fee_version='2026-10-28-owner-comp-v1')
        # Never label subtotal-only rehearsal output as a final payable total.
        snapshot = dict(schema_version=1, test_only=True, currency='USD', lines=snapshots,
            shop_id=shop_id, seller_owner_id=shop['owner_id'], shop_name=shop['name'],
            shop_policies=shop['policies'], shop_revision=shop['revision'],
            subtotal_cents=subtotal, platform_fee_cents=totals['platform_fee'],
            fee_version=totals['fee_version'], platform_fees_waived=waived,
            shipping_cents=None, tax_cents=None, payable_total_cents=None,
            payment_enabled=False, digital_versions_bound=False)
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > 1_048_576:
            raise CheckoutError('order snapshot too large')
        hold = inventory._reserve_locked(db, env, shop_id, str(buyer), 'checkout:' + hashlib.sha256(request_key.encode()).hexdigest(),
            [(sku, n) for sku, n, _ in normalized], now)
        order = uuid.uuid4().hex
        db.execute('''INSERT INTO marketplace_checkout_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (order, env, buyer, shop_id, shop['owner_id'], request_key, digest, hold, raw, now, now + 900, 'awaiting_payment'))
        return order


def get_order(db, env, uid, order_id, now, policy=NeonrestPolicy):
    test_mode(env)
    inventory.clock(now)
    actor(policy, db, uid)
    order = db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=? AND environment=?', (order_id, env)).fetchone()
    if not order:
        raise CheckoutError('order unavailable')
    if uid != order['buyer_id']:
        shop = shop_row(db, order['seller_ref'])
        if uid != order['seller_owner_id'] or shop['owner_id'] != uid or not policy.owner(db, uid, shop):
            raise CheckoutError('order unavailable')
    state = 'test_settled' if inventory.consumed(db,order['hold_id']) else order['state']
    if state == 'awaiting_payment' and order['expires_at'] <= now:
        state = 'expired'
    return dict(id=order['id'], state=state, snapshot=json.loads(order['snapshot']), expires_at=order['expires_at'])


def cancel_order(db, env, buyer, order_id, now, policy=NeonrestPolicy):
    test_mode(env)
    inventory.clock(now)
    with inventory.transaction(db):
        actor(policy, db, buyer)
        order = db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=? AND environment=? AND buyer_id=?', (order_id, env, buyer)).fetchone()
        if not order:
            raise CheckoutError('order unavailable')
        if inventory.consumed(db,order['hold_id']):
            return 'test_settled'
        if order['state'] == 'awaiting_payment':
            state = 'expired' if order['expires_at'] <= now else 'released'
            db.execute("UPDATE marketplace_inventory_holds SET state=? WHERE id=? AND state='reserved'", (state, order['hold_id']))
        return db.execute('SELECT state FROM marketplace_checkout_orders WHERE id=?', (order_id,)).fetchone()[0]


def expire_orders(db, env, now, limit=100):
    """Bounded internal maintenance; expiry never consumes stock or posts money."""
    test_mode(env)
    inventory.clock(now)
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise CheckoutError('invalid expiry batch size')
    with inventory.transaction(db):
        holds = db.execute('''SELECT hold_id FROM marketplace_checkout_orders
            WHERE environment=? AND state='awaiting_payment' AND expires_at<=?
            AND NOT EXISTS (SELECT 1 FROM marketplace_inventory_consumptions c WHERE c.hold_id=marketplace_checkout_orders.hold_id)
            ORDER BY expires_at,id LIMIT ?''', (env, now, limit)).fetchall()
        db.executemany("UPDATE marketplace_inventory_holds SET state='expired' WHERE id=? AND state='reserved'", [(h[0],) for h in holds])
        return len(holds)
