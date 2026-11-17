"""Complete test checkout totals with explicit shipping/tax evidence and consent.

No tax policy, carrier API, address store, payable live checkout or provider write.
Configured resolvers supply owned, versioned location references and test quotes.
Raw addresses never belong in this table. A complete test total is not authority
to charge, fulfill or grant downloads; final commercial policies remain required.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import uuid

if __package__:
    from . import marketplace_checkout as checkout, marketplace_inventory as inventory
    from .marketplace_core import cents, quote
else:
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory
    from marketplace_core import cents, quote


class QuoteError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    """Trusted owned-address lookup result; references must be opaque, not PII."""
    buyer_id: int
    seller_ref: str
    reference: str
    version: str
    origin_country: str
    destination_country: str


@dataclass(frozen=True)
class Assessment:
    """Explicit configured shipping/tax response, including zero/non-applicability."""
    kind: str
    source: str
    reference: str
    context_hash: str
    amount_cents: int
    expires_at: int
    environment: str = 'test'
    currency: str = 'USD'


SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_checkout_quotes (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    order_id TEXT NOT NULL REFERENCES marketplace_checkout_orders(id),buyer_id INTEGER NOT NULL REFERENCES users(id),
    request_key TEXT NOT NULL,location_ref TEXT NOT NULL,location_version TEXT NOT NULL,
    context_hash TEXT NOT NULL,snapshot TEXT NOT NULL,created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at>created_at),UNIQUE(environment,buyer_id,request_key)
);
CREATE TABLE IF NOT EXISTS marketplace_checkout_quote_acceptances (
    quote_id TEXT PRIMARY KEY REFERENCES marketplace_checkout_quotes(id),
    order_id TEXT NOT NULL UNIQUE REFERENCES marketplace_checkout_orders(id),
    buyer_id INTEGER NOT NULL REFERENCES users(id),accepted_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_quote_update BEFORE UPDATE ON marketplace_checkout_quotes
BEGIN SELECT RAISE(ABORT,'quote is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_quote_delete BEFORE DELETE ON marketplace_checkout_quotes
BEGIN SELECT RAISE(ABORT,'quote is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_quote_consent_update BEFORE UPDATE ON marketplace_checkout_quote_acceptances
BEGIN SELECT RAISE(ABORT,'quote acceptance is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_quote_consent_delete BEFORE DELETE ON marketplace_checkout_quote_acceptances
BEGIN SELECT RAISE(ABORT,'quote acceptance is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_checkout_quote_consent_insert BEFORE INSERT ON marketplace_checkout_quote_acceptances
WHEN NOT EXISTS (SELECT 1 FROM marketplace_checkout_quotes q WHERE q.id=NEW.quote_id
 AND q.order_id=NEW.order_id AND q.buyer_id=NEW.buyer_id AND q.created_at<=NEW.accepted_at AND q.expires_at>NEW.accepted_at)
BEGIN SELECT RAISE(ABORT,'invalid quote acceptance'); END;
CREATE INDEX IF NOT EXISTS marketplace_checkout_quote_order ON marketplace_checkout_quotes(order_id,expires_at,id);
"""


def initialize(db):
    if db.in_transaction:
        raise QuoteError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')


def _reference(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value,re.ASCII):
        raise QuoteError('opaque reference required')
    return value


def _fresh_order(db, buyer, order_id, now, policy):
    checkout.actor(policy, db, buyer)
    order = db.execute("SELECT * FROM marketplace_checkout_orders WHERE id=? AND buyer_id=? AND environment='test'", (order_id,buyer)).fetchone()
    if not order or order['state']!='awaiting_payment' or order['expires_at']<=now or inventory.consumed(db,order['hold_id']):
        raise QuoteError('active buyer reservation required')
    snapshot = json.loads(order['snapshot'])
    shop = checkout.shop_row(db, order['seller_ref'])
    checkout.actor(policy, db, shop['owner_id'])
    if shop['owner_id']!=order['seller_owner_id'] or not policy.visible(db,shop,buyer) or not policy.owner(db,shop['owner_id'],shop):
        raise QuoteError('shop unavailable')
    if shop['revision']!=snapshot['shop_revision'] or bool(policy.fee_waived(db,shop))!=snapshot['platform_fees_waived']:
        raise QuoteError('shop terms or fee policy changed')
    hold = db.execute("SELECT 1 FROM marketplace_inventory_holds WHERE id=? AND state='reserved' AND expires_at>?", (order['hold_id'],now)).fetchone()
    if not hold:
        raise QuoteError('active reservation required')
    for line in snapshot['lines']:
        item = db.execute('''SELECT l.revision,l.state,m.listing_revision,m.active FROM seller_listings l
            JOIN marketplace_checkout_skus m ON m.listing_id=l.id WHERE m.id=? AND m.seller_ref=? AND m.environment='test' ''', (line['sku'],order['seller_ref'])).fetchone()
        if not item or item['state']!='draft' or not item['active'] or item['revision']!=line['revision'] or item['listing_revision']!=line['revision']:
            raise QuoteError('listing changed; rebuild checkout')
    return order,snapshot


def _location(resolver, buyer, seller, reference):
    result = resolver.resolve_location(buyer,seller,reference)
    if not isinstance(result,Location) or type(result.buyer_id) is not int or result.buyer_id!=buyer or result.seller_ref!=seller or result.reference!=reference:
        raise QuoteError('owned address reference required')
    _reference(result.reference);_reference(result.version)
    if result.origin_country!='US' or result.destination_country!='US':
        raise QuoteError('only domestic US test quotes are supported')
    return result


def _context(order,snapshot,location):
    return dict(environment='test',order_id=order['id'],seller_ref=order['seller_ref'],buyer_id=order['buyer_id'],
        order_snapshot_hash=hashlib.sha256(order['snapshot'].encode()).hexdigest(),location=asdict(location),
        subtotal_cents=snapshot['subtotal_cents'],lines=snapshot['lines'])


def _hash(context):
    return hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _assert_local_location(resolver,buyer,seller,location):
    """Optional DB-local recheck, safe under a write lock; no provider calls here."""
    method=getattr(resolver,'assert_current_location',None)
    if method is not None: method(buyer,seller,location)


def _assessment(value, kind, context_hash, now):
    if not isinstance(value,Assessment) or value.kind!=kind or value.context_hash!=context_hash or value.environment!='test' or value.currency!='USD':
        raise QuoteError('missing or mismatched '+kind+' evidence')
    cents(value.amount_cents)
    inventory.clock(value.expires_at)
    if value.expires_at<=now:
        raise QuoteError(kind+' quote expired')
    _reference(value.source);_reference(value.reference)
    return value


def create_quote(db, buyer, order_id, location_ref, request_key, location_resolver, shipping_resolver, tax_resolver, now, policy=checkout.NeonrestPolicy):
    """Resolve outside write locks; revalidate the order before saving a test total.

    Callbacks are trusted configured services, never form-supplied code/amounts.
    Tax receives the chosen shipping evidence so shipping taxability can be handled
    by the responsible calculator. A missing calculator is never replaced by zero.
    """
    inventory.clock(now);_reference(location_ref);_reference(request_key)
    if db.in_transaction:
        raise QuoteError('dedicated connection required')
    order,snapshot = _fresh_order(db,buyer,order_id,now,policy)
    old = db.execute("SELECT * FROM marketplace_checkout_quotes WHERE environment='test' AND buyer_id=? AND request_key=?", (buyer,request_key)).fetchone()
    if old:
        if old['order_id']!=order_id or old['location_ref']!=location_ref:
            raise QuoteError('quote idempotency conflict')
        return old['id']
    location = _location(location_resolver,buyer,order['seller_ref'],location_ref)
    context = _context(order,snapshot,location)
    context_hash = _hash(context)
    shipping = _assessment(shipping_resolver.quote_shipping(context,context_hash),'shipping',context_hash,now)
    if _hash(context)!=context_hash:
        raise QuoteError('shipping resolver changed quote context')
    if not any(line['kind']=='physical' for line in snapshot['lines']) and shipping.amount_cents:
        raise QuoteError('nonphysical items cannot have shipping')
    # Bind tax not only to the cart/address, but to this specific shipping quote.
    tax_context = dict(context,shipping=asdict(shipping))
    tax_hash = _hash(tax_context)
    tax = _assessment(tax_resolver.quote_tax(tax_context,tax_hash),'tax',tax_hash,now)
    if _hash(tax_context)!=tax_hash:
        raise QuoteError('tax resolver changed quote context')
    totals = quote(snapshot['subtotal_cents'],shipping.amount_cents,tax.amount_cents)
    cents(totals['total'])
    expires = min(now+300,order['expires_at'],shipping.expires_at,tax.expires_at)
    result = dict(schema_version=1,environment='test',currency='USD',order_id=order_id,
        subtotal_cents=snapshot['subtotal_cents'],shipping_cents=shipping.amount_cents,tax_cents=tax.amount_cents,
        total_cents=totals['total'],platform_fee_cents=snapshot['platform_fee_cents'],fee_version=snapshot['fee_version'],
        location=asdict(location),shipping_evidence=asdict(shipping),tax_evidence=asdict(tax),
        payment_authorization_enabled=False,catalog_publication_checked=False,digital_versions_bound=False)
    with inventory.transaction(db):
        current,_ = _fresh_order(db,buyer,order_id,now,policy)
        if current['snapshot']!=order['snapshot']:
            raise QuoteError('order changed')
        repeated = db.execute("SELECT * FROM marketplace_checkout_quotes WHERE environment='test' AND buyer_id=? AND request_key=?", (buyer,request_key)).fetchone()
        if repeated:
            if repeated['order_id']!=order_id or repeated['location_ref']!=location_ref:
                raise QuoteError('quote idempotency conflict')
            return repeated['id']
        _assert_local_location(location_resolver,buyer,current['seller_ref'],location)
        binder=getattr(location_resolver,'bind_location_snapshot',None)
        bound=binder(buyer,current['seller_ref'],location) if binder is not None else None
        if binder is not None and bound!=location.version:
            raise QuoteError('address snapshot binding failed')
        result['location_snapshot_bound']=bound is not None
        raw=json.dumps(result,sort_keys=True,separators=(',',':'))
        quote_id=uuid.uuid4().hex
        db.execute('INSERT INTO marketplace_checkout_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (quote_id,'test',order_id,buyer,request_key,location.reference,location.version,context_hash,raw,now,expires))
        return quote_id


def _fresh_quote(db,buyer,quote_id,location,now,policy):
    row = db.execute("SELECT * FROM marketplace_checkout_quotes WHERE id=? AND buyer_id=? AND environment='test'", (quote_id,buyer)).fetchone()
    if not row or row['expires_at']<=now:
        raise QuoteError('quote unavailable or expired')
    order,snapshot = _fresh_order(db,buyer,row['order_id'],now,policy)
    if row['location_ref']!=location.reference or row['location_version']!=location.version or row['context_hash']!=_hash(_context(order,snapshot,location)):
        raise QuoteError('address or checkout context changed')
    return row


def accept_quote(db,buyer,quote_id,location_resolver,now,policy=checkout.NeonrestPolicy):
    """Record explicit buyer acceptance of a still-current complete test total."""
    inventory.clock(now)
    if db.in_transaction:
        raise QuoteError('dedicated connection required')
    row=db.execute('SELECT order_id,location_ref FROM marketplace_checkout_quotes WHERE id=? AND buyer_id=?',(quote_id,buyer)).fetchone()
    if not row:
        raise QuoteError('quote unavailable')
    order,_=_fresh_order(db,buyer,row['order_id'],now,policy)
    location=_location(location_resolver,buyer,order['seller_ref'],row['location_ref'])
    with inventory.transaction(db):
        _assert_local_location(location_resolver,buyer,order['seller_ref'],location)
        fresh=_fresh_quote(db,buyer,quote_id,location,now,policy)
        old=db.execute('SELECT quote_id FROM marketplace_checkout_quote_acceptances WHERE order_id=?',(fresh['order_id'],)).fetchone()
        if old:
            if old[0]!=quote_id:
                raise QuoteError('another quote was already accepted; rebuild checkout')
            return quote_id
        db.execute('INSERT INTO marketplace_checkout_quote_acceptances VALUES (?,?,?,?)',(quote_id,fresh['order_id'],buyer,now))
        return quote_id


def get_quote(db,buyer,quote_id,location_resolver,now,policy=checkout.NeonrestPolicy):
    inventory.clock(now)
    row=db.execute('SELECT order_id,location_ref FROM marketplace_checkout_quotes WHERE id=? AND buyer_id=?',(quote_id,buyer)).fetchone()
    if not row:
        raise QuoteError('quote unavailable')
    order,_=_fresh_order(db,buyer,row['order_id'],now,policy)
    location=_location(location_resolver,buyer,order['seller_ref'],row['location_ref'])
    fresh=_fresh_quote(db,buyer,quote_id,location,now,policy)
    return dict(id=fresh['id'],expires_at=fresh['expires_at'],snapshot=json.loads(fresh['snapshot']))
