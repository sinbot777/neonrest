"""Owner-scoped test shipping setup; credentials never appear in public results.

Explicit additive migration and service construction only. No startup migration,
merchant account creation, OAuth simulation, labels or live credentials.
"""
from decimal import Decimal,InvalidOperation,ROUND_CEILING
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
if __package__:
    from . import marketplace_checkout as checkout,marketplace_inventory as inventory
    from .marketplace_addresses import FernetVault
    from .marketplace_carrier_rates import ShippoTestRatesAPI
    from .marketplace_provider_api import ProviderUnavailable,_NoRedirect,_parse
else:
    import marketplace_checkout as checkout,marketplace_inventory as inventory
    from marketplace_addresses import FernetVault
    from marketplace_carrier_rates import ShippoTestRatesAPI
    from marketplace_provider_api import ProviderUnavailable,_NoRedirect,_parse

class ShippingError(ValueError):pass

SCHEMA='''
CREATE TABLE IF NOT EXISTS marketplace_test_shipping_connections(
 id TEXT PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL CHECK(revision>0),ciphertext BLOB NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 verified_at INTEGER NOT NULL,UNIQUE(shop_id,revision));
CREATE TABLE IF NOT EXISTS marketplace_test_package_presets(
 id TEXT PRIMARY KEY,preset_key TEXT NOT NULL,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL CHECK(revision>0),name TEXT NOT NULL,length_um INTEGER NOT NULL CHECK(length_um>0),width_um INTEGER NOT NULL CHECK(width_um>0),height_um INTEGER NOT NULL CHECK(height_um>0),
 packaging_mg INTEGER NOT NULL CHECK(packaging_mg>=0),max_units INTEGER NOT NULL CHECK(max_units>0),enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),created_at INTEGER NOT NULL,
 UNIQUE(preset_key,revision));
CREATE TABLE IF NOT EXISTS marketplace_test_item_weights(
 id TEXT PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
 sku TEXT NOT NULL REFERENCES marketplace_checkout_skus(id),revision INTEGER NOT NULL CHECK(revision>0),
 weight_mg INTEGER NOT NULL CHECK(weight_mg>0),created_at INTEGER NOT NULL,UNIQUE(sku,revision));
CREATE TABLE IF NOT EXISTS marketplace_test_shipping_setup_events(
 id INTEGER PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),actor_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,reference TEXT NOT NULL,created_at INTEGER NOT NULL);
'''
for _table in ('marketplace_test_shipping_connections','marketplace_test_package_presets','marketplace_test_item_weights','marketplace_test_shipping_setup_events'):
    for _op in ('UPDATE','DELETE'):
        SCHEMA+='CREATE TRIGGER IF NOT EXISTS '+_table+'_'+_op.lower()+' BEFORE '+_op+' ON '+_table+" BEGIN SELECT RAISE(ABORT,'shipping setup history is immutable'); END;\n"


def initialize(db):
    if db.in_transaction:raise ShippingError('dedicated migration connection required')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def measurement(value,unit,kind):
    """Strict decimal UI input -> ceiling micrometres/milligrams, never floats."""
    units={'distance':{'in':'25400','cm':'10000','mm':'1000'},'mass':{'oz':'28349.523125','lb':'453592.37','g':'1000'}}
    if kind not in units or unit not in units[kind] or not isinstance(value,str) or not re.fullmatch(r'(?:[0-9]{1,6}(?:\.[0-9]{1,6})?|\.[0-9]{1,6})',value):
        raise ShippingError('enter a decimal measurement and supported unit')
    n=int((Decimal(value)*Decimal(units[kind][unit])).to_integral_value(rounding=ROUND_CEILING))
    if not 0<=n<=(3_000_000 if kind=='distance' else 70_000_000):raise ShippingError('measurement exceeds supported package limits')
    return n


def text(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80 or any(ord(c)<32 or ord(c)==127 for c in value):raise ShippingError('enter a short package name')
    return value.strip()


def revision(value):
    if type(value) is not int or value<0:raise ShippingError('reload shipping settings before saving')


class ShippoTestVerifier:
    """Fixed read-only API request. Returns no account IDs, email or credentials."""
    def verify(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'shippo_test_[A-Za-z0-9_]{16,512}',token):raise ShippingError('Shippo test key required')
        req=urllib.request.Request('https://api.goshippo.com/carrier_accounts/?results=1',headers={'Authorization':'ShippoToken '+token,'Shippo-API-Version':'2018-02-08','Accept':'application/json'})
        opener=urllib.request.build_opener(_NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(req,timeout=15) as response:
                if response.status!=200:raise ProviderUnavailable('Shippo test verification unavailable')
                raw=response.read(1_048_577)
        except (urllib.error.URLError,TimeoutError,OSError):raise ProviderUnavailable('Shippo test key could not be verified') from None
        value=_parse(raw)
        if not isinstance(value,dict) or not isinstance(value.get('results'),list):raise ProviderUnavailable('Shippo test verification unavailable')
        return True


class SellerShipping:
    def __init__(self,db,vault,policy=checkout.NeonrestPolicy,verifier=None,http=None):
        if not isinstance(vault,FernetVault):raise ShippingError('configured encryption vault required')
        self.db=db;self.vault=vault;self.policy=policy;self.verifier=verifier or ShippoTestVerifier();self.http=http
    def owner(self,uid,shop_id):
        checkout.actor(self.policy,self.db,uid);shop=checkout.shop_row(self.db,shop_id)
        if shop['owner_id']!=uid or not self.policy.owner(self.db,uid,shop):raise ShippingError('current shop owner required')
        return shop
    def event(self,uid,shop,action,ref,now):
        self.db.execute('INSERT INTO marketplace_test_shipping_setup_events(shop_id,actor_id,action,reference,created_at) VALUES (?,?,?,?,?)',(shop,uid,action,ref,now))
    def connection(self,shop):
        return self.db.execute('SELECT * FROM marketplace_test_shipping_connections WHERE shop_id=? ORDER BY revision DESC LIMIT 1',(shop,)).fetchone()
    def envelope(self,row,token):
        return dict(environment='test',provider='shippo',shop_id=row['shop_id'],owner_id=row['owner_id'],id=row['id'],revision=row['revision'],token=token)
    def save_connection(self,uid,shop_id,expected,token,now):
        inventory.clock(now);revision(expected);self.owner(uid,shop_id)
        if self.db.in_transaction:raise ShippingError('connection verification needs an idle database')
        if not isinstance(token,str) or not re.fullmatch(r'shippo_test_[A-Za-z0-9_]{16,512}',token):raise ShippingError('Shippo test key required')
        old=self.connection(shop_id)
        if (old['revision'] if old else 0)!=expected:raise ShippingError('shipping connection changed; reload')
        if self.verifier.verify(token) is not True:raise ShippingError('Shippo test verification required')
        with inventory.transaction(self.db):
            self.owner(uid,shop_id);old=self.connection(shop_id)
            if (old['revision'] if old else 0)!=expected:raise ShippingError('shipping connection changed; reload')
            row=dict(id=uuid.uuid4().hex,shop_id=shop_id,owner_id=uid,revision=expected+1)
            cipher=self.vault.seal(self.envelope(row,token))
            self.db.execute('INSERT INTO marketplace_test_shipping_connections VALUES (?,?,?,?,?,1,?)',(row['id'],shop_id,uid,row['revision'],cipher,now))
            self.event(uid,shop_id,'test_connection_verified',row['id'],now)
        return row['id']
    def disconnect(self,uid,shop_id,expected,now):
        inventory.clock(now);revision(expected)
        with inventory.transaction(self.db):
            self.owner(uid,shop_id);old=self.connection(shop_id)
            if not old or old['revision']!=expected:raise ShippingError('shipping connection changed; reload')
            row=dict(id=uuid.uuid4().hex,shop_id=shop_id,owner_id=uid,revision=expected+1)
            self.db.execute('INSERT INTO marketplace_test_shipping_connections VALUES (?,?,?,?,?,0,?)',(row['id'],shop_id,uid,row['revision'],self.vault.seal(self.envelope(row,None)),now))
            self.event(uid,shop_id,'test_connection_disconnected',row['id'],now)
    def api(self,shop_id,owner_id):
        self.owner(owner_id,shop_id);row=self.connection(shop_id)
        if not row or not row['enabled'] or row['owner_id']!=owner_id:raise ShippingError('connect this shop to Shippo test mode first')
        value=self.vault.open(row['ciphertext']);token=value.get('token')
        if value!=self.envelope(row,token):raise ShippingError('shipping connection binding mismatch')
        return ShippoTestRatesAPI(token,shop_id,owner_id,self.http)
    def presets(self,shop_id,owner_id):
        return self.db.execute('''SELECT p.* FROM marketplace_test_package_presets p
          WHERE p.shop_id=? AND p.owner_id=? AND p.revision=(SELECT MAX(x.revision) FROM marketplace_test_package_presets x WHERE x.preset_key=p.preset_key)
          ORDER BY p.name,p.preset_key''',(shop_id,owner_id)).fetchall()
    def save_preset(self,uid,shop_id,preset_key,expected,name,length_um,width_um,height_um,packaging_mg,max_units,enabled,now):
        inventory.clock(now);revision(expected);name=text(name)
        if any(type(v) is not int or not 1<=v<=3_000_000 for v in (length_um,width_um,height_um)) or type(packaging_mg) is not int or not 0<=packaging_mg<=70_000_000 or type(max_units) is not int or not 1<=max_units<=5000 or type(enabled) is not bool:raise ShippingError('check package dimensions, empty weight and capacity')
        with inventory.transaction(self.db):
            self.owner(uid,shop_id)
            if preset_key:
                old=self.db.execute('SELECT * FROM marketplace_test_package_presets WHERE preset_key=? ORDER BY revision DESC LIMIT 1',(preset_key,)).fetchone()
                if not old or old['shop_id']!=shop_id or old['owner_id']!=uid or old['revision']!=expected:raise ShippingError('package preset unavailable or changed; reload')
            else:
                if expected!=0:raise ShippingError('new preset revision must be zero')
                if len(self.presets(shop_id,uid))>=50:raise ShippingError('package preset limit reached')
                preset_key=uuid.uuid4().hex
            ident=uuid.uuid4().hex
            self.db.execute('INSERT INTO marketplace_test_package_presets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,preset_key,shop_id,uid,expected+1,name,length_um,width_um,height_um,packaging_mg,max_units,int(enabled),now))
            self.event(uid,shop_id,'package_preset_saved',ident,now)
        return preset_key
    def save_weight(self,uid,shop_id,sku,expected,weight_mg,now):
        inventory.clock(now);revision(expected)
        if type(weight_mg) is not int or not 1<=weight_mg<=70_000_000:raise ShippingError('positive item weight required')
        with inventory.transaction(self.db):
            self.owner(uid,shop_id)
            item=self.db.execute('SELECT * FROM marketplace_checkout_skus WHERE id=? AND seller_ref=? AND active=1',(sku,shop_id)).fetchone()
            if not item:raise ShippingError('active shop stock item required')
            old=self.db.execute('SELECT * FROM marketplace_test_item_weights WHERE sku=? ORDER BY revision DESC LIMIT 1',(sku,)).fetchone()
            if (old['revision'] if old else 0)!=expected:raise ShippingError('item weight changed; reload')
            ident=uuid.uuid4().hex
            self.db.execute('INSERT INTO marketplace_test_item_weights VALUES (?,?,?,?,?,?,?)',(ident,shop_id,uid,sku,expected+1,weight_mg,now))
            self.event(uid,shop_id,'item_weight_saved',ident,now)
    def fingerprint(self,shop_id):
        shop=checkout.shop_row(self.db,shop_id);self.owner(shop['owner_id'],shop_id)
        conn=self.connection(shop_id)
        if not conn or not conn['enabled'] or conn['owner_id']!=shop['owner_id']:raise ShippingError('shop shipping connection is unavailable')
        preset_ids=[r['id'] for r in self.presets(shop_id,shop['owner_id'])]
        weights=[r[0] for r in self.db.execute('''SELECT w.id FROM marketplace_test_item_weights w WHERE w.shop_id=? AND w.owner_id=?
          AND w.revision=(SELECT MAX(x.revision) FROM marketplace_test_item_weights x WHERE x.sku=w.sku) ORDER BY w.sku''',(shop_id,shop['owner_id']))]
        return hashlib.sha256(json.dumps([conn['id'],preset_ids,weights],separators=(',',':')).encode()).hexdigest()
    def parcel(self,context):
        shop_id=context['seller_ref'];shop=checkout.shop_row(self.db,shop_id);self.fingerprint(shop_id)
        units=0;mass=0
        for line in context['lines']:
            if line['kind']!='physical' or type(line['quantity']) is not int or not 1<=line['quantity']<=99:raise ShippingError('physical item quantities required')
            row=self.db.execute('SELECT * FROM marketplace_test_item_weights WHERE sku=? ORDER BY revision DESC LIMIT 1',(line['sku'],)).fetchone()
            if not row or row['shop_id']!=shop_id or row['owner_id']!=shop['owner_id']:raise ShippingError('seller must set a weight for every item variation before rates are available')
            units+=line['quantity'];mass+=line['quantity']*row['weight_mg']
        eligible=[r for r in self.presets(shop_id,shop['owner_id']) if r['enabled'] and units and units<=r['max_units'] and mass+r['packaging_mg']<=70_000_000]
        if not eligible:raise ShippingError('no seller package preset supports this item quantity and weight')
        p=min(eligible,key=lambda r:(r['length_um']*r['width_um']*r['height_um'],r['packaging_mg'],r['preset_key']))
        def decimal(n,scale):return format(Decimal(n)/Decimal(scale),'f')
        return dict(length=decimal(p['length_um'],10000),width=decimal(p['width_um'],10000),height=decimal(p['height_um'],10000),distance_unit='cm',weight=decimal(mass+p['packaging_mg'],1000),mass_unit='g')
    def public(self,uid,shop_id):
        self.owner(uid,shop_id);connection=self.connection(shop_id)
        weights=[dict(r) for r in self.db.execute('''SELECT s.id AS sku,s.variant_key,l.title,CASE WHEN w.owner_id=? THEN w.weight_mg ELSE NULL END AS weight_mg,COALESCE(w.revision,0) AS revision FROM marketplace_checkout_skus s
          JOIN seller_listings l ON l.id=s.listing_id LEFT JOIN marketplace_test_item_weights w ON w.sku=s.id
          AND w.revision=(SELECT MAX(x.revision) FROM marketplace_test_item_weights x WHERE x.sku=s.id)
          WHERE s.seller_ref=? AND s.active=1 AND l.kind='physical' ORDER BY l.title,s.variant_key''',(uid,shop_id))]
        return dict(connection=dict(revision=connection['revision'] if connection else 0,connected=bool(connection and connection['enabled'] and connection['owner_id']==uid)),presets=[dict(r) for r in self.presets(shop_id,uid)],weights=weights)
