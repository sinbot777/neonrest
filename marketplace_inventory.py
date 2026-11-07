"""Private stock-reservation primitive; no routes, checkout, or payment transition.

Stock must be provisioned by trusted seller integration in a future increment.
Never seed this table from seller_test_orders. Unit counts and holds are separate
from listing presentation revisions, so editing a title cannot free held stock.
"""
import hashlib
import json
import uuid
from contextlib import contextmanager


class InventoryError(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_inventory_stock (
    environment TEXT NOT NULL CHECK(environment IN ('test','live')),
    seller_ref TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity BETWEEN 0 AND 1000000),
    PRIMARY KEY(environment,seller_ref,sku)
);
CREATE TABLE IF NOT EXISTS marketplace_inventory_holds (
    id TEXT PRIMARY KEY,
    environment TEXT NOT NULL CHECK(environment IN ('test','live')),
    seller_ref TEXT NOT NULL,
    buyer_ref TEXT NOT NULL,
    request_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at>created_at),
    state TEXT NOT NULL CHECK(state IN ('reserved','released','expired')),
    UNIQUE(environment,buyer_ref,request_key),
    UNIQUE(id,environment,seller_ref)
);
CREATE TABLE IF NOT EXISTS marketplace_inventory_hold_lines (
    hold_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    seller_ref TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity BETWEEN 1 AND 99),
    PRIMARY KEY(hold_id,sku),
    FOREIGN KEY(hold_id,environment,seller_ref) REFERENCES marketplace_inventory_holds(id,environment,seller_ref),
    FOREIGN KEY(environment,seller_ref,sku) REFERENCES marketplace_inventory_stock(environment,seller_ref,sku)
);
CREATE TABLE IF NOT EXISTS marketplace_inventory_consumptions (
    hold_id TEXT PRIMARY KEY REFERENCES marketplace_inventory_holds(id),
    consumed_at INTEGER NOT NULL CHECK(typeof(consumed_at)='integer' AND consumed_at>=0)
);
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consume_validate
BEFORE INSERT ON marketplace_inventory_consumptions
BEGIN
 SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM marketplace_inventory_holds h
   WHERE h.id=NEW.hold_id AND h.environment='test' AND h.state='reserved'
   AND h.created_at<=NEW.consumed_at AND h.expires_at>NEW.consumed_at)
   OR NOT EXISTS (SELECT 1 FROM marketplace_inventory_hold_lines WHERE hold_id=NEW.hold_id)
   OR EXISTS (SELECT 1 FROM marketplace_inventory_hold_lines l JOIN marketplace_inventory_stock s
   ON s.environment=l.environment AND s.seller_ref=l.seller_ref AND s.sku=l.sku
   WHERE l.hold_id=NEW.hold_id AND s.quantity<l.quantity)
 THEN RAISE(ABORT,'active test reservation and stock required') END;
END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consume_stock
AFTER INSERT ON marketplace_inventory_consumptions
BEGIN
 UPDATE marketplace_inventory_stock SET quantity=quantity-(SELECT l.quantity
 FROM marketplace_inventory_hold_lines l WHERE l.hold_id=NEW.hold_id
 AND l.environment=marketplace_inventory_stock.environment
 AND l.seller_ref=marketplace_inventory_stock.seller_ref AND l.sku=marketplace_inventory_stock.sku)
 WHERE (environment,seller_ref,sku) IN
 (SELECT environment,seller_ref,sku FROM marketplace_inventory_hold_lines WHERE hold_id=NEW.hold_id);
END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumption_update BEFORE UPDATE ON marketplace_inventory_consumptions
BEGIN SELECT RAISE(ABORT,'consumption is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumption_delete BEFORE DELETE ON marketplace_inventory_consumptions
BEGIN SELECT RAISE(ABORT,'consumption is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumed_hold_update BEFORE UPDATE ON marketplace_inventory_holds
WHEN EXISTS (SELECT 1 FROM marketplace_inventory_consumptions WHERE hold_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'consumed reservation is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumed_line_insert BEFORE INSERT ON marketplace_inventory_hold_lines
WHEN EXISTS (SELECT 1 FROM marketplace_inventory_consumptions WHERE hold_id=NEW.hold_id)
BEGIN SELECT RAISE(ABORT,'consumed lines are retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumed_line_update BEFORE UPDATE ON marketplace_inventory_hold_lines
WHEN EXISTS (SELECT 1 FROM marketplace_inventory_consumptions WHERE hold_id=OLD.hold_id OR hold_id=NEW.hold_id)
BEGIN SELECT RAISE(ABORT,'consumed lines are retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_inventory_consumed_line_delete BEFORE DELETE ON marketplace_inventory_hold_lines
WHEN EXISTS (SELECT 1 FROM marketplace_inventory_consumptions WHERE hold_id=OLD.hold_id)
BEGIN SELECT RAISE(ABORT,'consumed lines are retained'); END;
CREATE INDEX IF NOT EXISTS marketplace_inventory_active_holds
ON marketplace_inventory_holds(environment,seller_ref,state,expires_at);
CREATE INDEX IF NOT EXISTS marketplace_inventory_hold_stock
ON marketplace_inventory_hold_lines(environment,seller_ref,sku,hold_id);
"""


def initialize(db):
    if db.in_transaction:
        raise InventoryError('initialize outside a transaction')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')


@contextmanager
def transaction(db):
    if db.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise InventoryError('foreign keys must be enabled on this connection')
    if db.in_transaction:
        raise InventoryError('dedicated connection required')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def identity(env, *refs):
    if env not in ('test', 'live') or any(not isinstance(r, str) or not r.strip() or len(r) > 160 for r in refs):
        raise InventoryError('invalid identity')


def clock(now):
    if type(now) is not int or not 0 <= now <= 2**63 - 901:
        raise InventoryError('invalid time')


def available(db, env, seller, sku, now):
    identity(env, seller, sku)
    clock(now)
    row = db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE environment=? AND seller_ref=? AND sku=?', (env, seller, sku)).fetchone()
    if row is None:
        raise InventoryError('unknown stock')
    held = db.execute('''SELECT COALESCE(SUM(l.quantity),0) FROM marketplace_inventory_hold_lines l
        JOIN marketplace_inventory_holds h ON h.id=l.hold_id
        WHERE l.environment=? AND l.seller_ref=? AND l.sku=?
        AND h.state='reserved' AND h.expires_at>?
        AND NOT EXISTS (SELECT 1 FROM marketplace_inventory_consumptions c WHERE c.hold_id=h.id)''', (env, seller, sku, now)).fetchone()[0]
    return row[0] - held


def set_stock(db, env, seller, sku, quantity, now):
    """Trusted absolute adjustment; refuses a reduction below active reservations."""
    identity(env, seller, sku)
    clock(now)
    if type(quantity) is not int or not 0 <= quantity <= 1_000_000:
        raise InventoryError('invalid quantity')
    with transaction(db):
        _set_stock_locked(db, env, seller, sku, quantity, now)


def _set_stock_locked(db, env, seller, sku, quantity, now):
    """Internal composition helper; caller owns BEGIN IMMEDIATE and validation."""
    if not db.in_transaction:
        raise InventoryError('transaction required')
    old = db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE environment=? AND seller_ref=? AND sku=?', (env, seller, sku)).fetchone()
    if old and quantity < old[0] - available(db, env, seller, sku, now):
        raise InventoryError('stock is reserved')
    db.execute('''INSERT INTO marketplace_inventory_stock VALUES (?,?,?,?)
        ON CONFLICT(environment,seller_ref,sku) DO UPDATE SET quantity=excluded.quantity''', (env, seller, sku, quantity))


def reserve(db, env, seller, buyer, request_key, lines, now, ttl=900):
    """Reserve one seller's SKUs atomically. Authentication belongs to future caller.

    Expired/released idempotent requests return their old ID, never a fresh hold.
    TTL/time must come from the server, never request form fields.
    """
    with transaction(db):
        return _reserve_locked(db, env, seller, buyer, request_key, lines, now, ttl)


def _reserve_locked(db, env, seller, buyer, request_key, lines, now, ttl=900):
    """Internal helper for atomic order-plus-reservation creation."""
    if not db.in_transaction:
        raise InventoryError('transaction required')
    identity(env, seller, buyer, request_key)
    clock(now)
    if type(ttl) is not int or not 1 <= ttl <= 900:
        raise InventoryError('invalid expiry')
    if not isinstance(lines, (list, tuple)) or not 1 <= len(lines) <= 50:
        raise InventoryError('expected 1–50 lines')
    normalized = []
    for line in lines:
        if not isinstance(line, (tuple, list)) or len(line) != 2:
            raise InventoryError('invalid line')
        sku, quantity = line
        identity(env, sku)
        if type(quantity) is not int or not 1 <= quantity <= 99:
            raise InventoryError('invalid quantity')
        normalized.append((sku, quantity))
    normalized.sort()
    if len({sku for sku, _ in normalized}) != len(normalized):
        raise InventoryError('duplicate SKU')
    digest = hashlib.sha256(json.dumps([seller, normalized, ttl], separators=(',', ':')).encode()).hexdigest()
    old = db.execute('SELECT id,payload_hash FROM marketplace_inventory_holds WHERE environment=? AND buyer_ref=? AND request_key=?', (env, buyer, request_key)).fetchone()
    if old:
        if old[1] != digest:
            raise InventoryError('idempotency conflict')
        return old[0]
    for sku, quantity in normalized:
        if available(db, env, seller, sku, now) < quantity:
            raise InventoryError('insufficient stock')
    hold = uuid.uuid4().hex
    db.execute('INSERT INTO marketplace_inventory_holds VALUES (?,?,?,?,?,?,?,?,?)', (hold, env, seller, buyer, request_key, digest, now, now + ttl, 'reserved'))
    db.executemany('INSERT INTO marketplace_inventory_hold_lines VALUES (?,?,?,?,?)', [(hold, env, seller, sku, n) for sku, n in normalized])
    return hold


def release(db, env, buyer, hold, now):
    identity(env, buyer, hold)
    clock(now)
    with transaction(db):
        row = db.execute('SELECT state,expires_at FROM marketplace_inventory_holds WHERE id=? AND environment=? AND buyer_ref=?', (hold, env, buyer)).fetchone()
        if not row:
            raise InventoryError('unknown reservation')
        if consumed(db,hold):
            raise InventoryError('settled test reservation cannot be released')
        state = row[0]
        if state == 'reserved':
            state = 'expired' if row[1] <= now else 'released'
            db.execute('UPDATE marketplace_inventory_holds SET state=? WHERE id=?', (state, hold))
        return state


def consumed(db,hold):
    return db.execute('SELECT 1 FROM marketplace_inventory_consumptions WHERE hold_id=?',(hold,)).fetchone() is not None
