"""Owner-configured domestic fixed shipping charges, not purchased postage.

Test-only profiles connect real encrypted address references to complete quotes.
No carrier request, label, tax assumption or buyer-address release to a seller.
"""
from dataclasses import asdict,replace
import hashlib
import json
import time

if __package__:
    from . import marketplace_checkout as checkout,marketplace_inventory as inventory
    from .marketplace_core import cents
    from .marketplace_quotes import Assessment
else:
    import marketplace_checkout as checkout
    import marketplace_inventory as inventory
    from marketplace_core import cents
    from marketplace_quotes import Assessment


class ShippingError(ValueError):
    pass


SCHEMA="""
CREATE TABLE IF NOT EXISTS marketplace_shipping_profiles (
    id TEXT PRIMARY KEY,environment TEXT NOT NULL CHECK(environment='test'),
    shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
    revision INTEGER NOT NULL CHECK(revision>0),base_cents INTEGER NOT NULL CHECK(base_cents BETWEEN 0 AND 100000000),
    per_item_cents INTEGER NOT NULL CHECK(per_item_cents BETWEEN 0 AND 100000000),
    cap_cents INTEGER CHECK(cap_cents BETWEEN base_cents AND 100000000),enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    created_at INTEGER NOT NULL,UNIQUE(shop_id,revision),UNIQUE(id,shop_id,owner_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_shipping_profile_update BEFORE UPDATE ON marketplace_shipping_profiles
BEGIN SELECT RAISE(ABORT,'shipping profile version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_shipping_profile_delete BEFORE DELETE ON marketplace_shipping_profiles
BEGIN SELECT RAISE(ABORT,'shipping profile version is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_shipping_current (
    shop_id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL,profile_id TEXT NOT NULL,
    FOREIGN KEY(profile_id,shop_id,owner_id) REFERENCES marketplace_shipping_profiles(id,shop_id,owner_id)
);
CREATE TRIGGER IF NOT EXISTS marketplace_shipping_current_insert BEFORE INSERT ON marketplace_shipping_current
WHEN NOT EXISTS (SELECT 1 FROM seller_shops WHERE page_id=NEW.shop_id AND owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT,'shipping profile owner mismatch'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_shipping_current_update BEFORE UPDATE ON marketplace_shipping_current
WHEN NEW.shop_id!=OLD.shop_id OR NEW.owner_id!=OLD.owner_id
 OR NOT EXISTS (SELECT 1 FROM seller_shops WHERE page_id=NEW.shop_id AND owner_id=NEW.owner_id)
BEGIN SELECT RAISE(ABORT,'shipping profile owner mismatch'); END;
"""


def initialize(db):
    if db.in_transaction: raise ShippingError('dedicated connection required')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def save_profile(db,uid,shop_id,revision,base_cents,per_item_cents,cap_cents,enabled,now,policy=checkout.NeonrestPolicy):
    """Explicit fixed charge: base once per order plus each physical unit, capped."""
    import uuid
    inventory.clock(now);cents(base_cents);cents(per_item_cents)
    if cap_cents is not None:
        cents(cap_cents)
        if cap_cents<base_cents: raise ShippingError('shipping cap cannot be below base charge')
    if type(revision) is not int or revision<0 or type(enabled) is not bool:
        raise ShippingError('check profile revision/state')
    with inventory.transaction(db):
        checkout.actor(policy,db,uid)
        shop=checkout.shop_row(db,shop_id)
        if shop['owner_id']!=uid or not policy.owner(db,uid,shop):
            raise ShippingError('shop owner permission required')
        old=db.execute('''SELECT p.* FROM marketplace_shipping_current c JOIN marketplace_shipping_profiles p ON p.id=c.profile_id
            WHERE c.shop_id=?''',(shop_id,)).fetchone()
        if old and old['owner_id']!=uid: raise ShippingError('shipping ownership changed; support review required')
        desired=(base_cents,per_item_cents,cap_cents,int(enabled))
        current=(old['base_cents'],old['per_item_cents'],old['cap_cents'],old['enabled']) if old else None
        old_revision=old['revision'] if old else 0
        if old and old_revision==revision+1 and current==desired: return old['id']
        if old_revision!=revision: raise ShippingError('shipping profile changed; reload')
        profile=uuid.uuid4().hex
        db.execute("INSERT INTO marketplace_shipping_profiles VALUES (?,'test',?,?,?,?,?,?,?,?)",
            (profile,shop_id,uid,revision+1,base_cents,per_item_cents,cap_cents,enabled,now))
        db.execute('''INSERT INTO marketplace_shipping_current VALUES (?,?,?)
            ON CONFLICT(shop_id) DO UPDATE SET profile_id=excluded.profile_id''',(shop_id,uid,profile))
        return profile


class ManualShippingResolver:
    """Use this object as both location and shipping resolver for complete quotes.

    Its opaque location version includes address and shipping-profile versions, so
    edits, origin changes or disabled rates invalidate use of a pending quote.
    """
    def __init__(self,address_resolver,clock=None):
        self.addresses=address_resolver
        self.clock=clock or (lambda:int(time.time()))

    def _resolve(self,buyer,seller,destination):
        location,origin,address=self.addresses._pair(buyer,seller,destination)
        store=self.addresses.store;db=store.db
        row=db.execute('''SELECT p.* FROM marketplace_shipping_current c JOIN marketplace_shipping_profiles p ON p.id=c.profile_id
            JOIN seller_shops s ON s.page_id=c.shop_id AND s.owner_id=c.owner_id
            WHERE c.shop_id=? AND p.environment='test' AND p.enabled=1''',(seller,)).fetchone()
        if not row: raise ShippingError('seller shipping profile is not configured')
        version=hashlib.sha256(json.dumps([location.version,row['id']],separators=(',',':')).encode()).hexdigest()
        return replace(location,version=version),row,origin,address

    def resolve_location(self,buyer,seller_ref,destination_ref):
        return self._resolve(buyer,seller_ref,destination_ref)[0]

    def assert_current_location(self,buyer,seller_ref,location):
        if self.resolve_location(buyer,seller_ref,location.reference)!=location:
            raise ShippingError('shipping/address context changed')

    def bind_location_snapshot(self,buyer,seller_ref,location):
        self.assert_current_location(buyer,seller_ref,location)
        native=self.addresses.resolve_location(buyer,seller_ref,location.reference)
        return self.addresses._save_snapshot(buyer,seller_ref,location,native.version)

    def quote_shipping(self,context,context_hash):
        now=self.clock();inventory.clock(now)
        if context.get('environment')!='test': raise ShippingError('only test shipping quotes are enabled')
        location,profile,_,_=self._resolve(context['buyer_id'],context['seller_ref'],context['location']['reference'])
        if asdict(location)!=context['location']: raise ShippingError('shipping/address context changed')
        count=0
        for line in context['lines']:
            if line['kind']=='physical':
                quantity=line['quantity']
                if type(quantity) is not int or not 1<=quantity<=99: raise ShippingError('invalid shipping quantity')
                count+=quantity
        amount=profile['base_cents']+profile['per_item_cents']*count if count else 0
        if profile['cap_cents'] is not None: amount=min(amount,profile['cap_cents'])
        cents(amount)
        return Assessment('shipping','manual_domestic_v1',profile['id'],context_hash,amount,now+300)

    def calculation_addresses(self,buyer,seller_ref,destination_ref,expected_version):
        """Private tax/carrier handoff, with minimum address fields; no transmission."""
        location,_,origin,destination=self._resolve(buyer,seller_ref,destination_ref)
        if location.version!=expected_version: raise ShippingError('shipping/address context changed')
        fields=('line1','line2','city','state','postal_code','country')
        return dict(location=location,origin={k:origin[k] for k in fields},destination={k:destination[k] for k in fields})
