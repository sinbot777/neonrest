"""Owner-specific Shippo test rates. No label, transaction or postage API exists here."""
from dataclasses import asdict,replace
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
if __package__:
    from . import marketplace_checkout as checkout, marketplace_inventory as inventory, marketplace_quotes as quotes
    from .marketplace_provider_api import ProviderUnavailable,_NoRedirect,_parse
else:
    import marketplace_checkout as checkout,marketplace_inventory as inventory,marketplace_quotes as quotes
    from marketplace_provider_api import ProviderUnavailable,_NoRedirect,_parse


class RateError(ValueError):pass


class ShippoRateHTTP:
    def request(self,method,url,headers,body):
        if method!='POST' or url!='https://api.goshippo.com/shipments/' or type(body) is not bytes or len(body)>65536:
            raise RateError('only shipment rate requests are enabled')
        if any(not isinstance(k,str) or not isinstance(v,str) or '\n' in k+v or '\r' in k+v for k,v in headers.items()):
            raise RateError('invalid rate request headers')
        opener=urllib.request.build_opener(_NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request=urllib.request.Request(url,data=body,headers=headers,method=method)
        try:
            with opener.open(request,timeout=15) as response:
                if response.status not in (200,201):raise ProviderUnavailable('shipping rates unavailable')
                raw=response.read(1_048_577)
        except (urllib.error.URLError,TimeoutError,OSError):
            raise ProviderUnavailable('shipping rates unavailable') from None
        return _parse(raw)


def reference(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):raise RateError('invalid carrier rate reference')
    return value


def money(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?',value):raise RateError('invalid USD carrier rate')
    major,_,minor=value.partition('.')
    result=int(major)*100+int(minor.ljust(2,'0') or '0')
    if not 0<=result<=100_000_000:raise RateError('carrier rate out of bounds')
    return result


def label(value,maximum):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or any(ord(c)<32 or ord(c)==127 for c in value):raise RateError('invalid carrier service label')
    return value


class ShippoTestRatesAPI:
    def __init__(self,token,seller_ref,owner_id,http=None):
        if not isinstance(token,str) or not re.fullmatch(r'shippo_test_[A-Za-z0-9_]{16,512}',token):raise RateError('seller-specific Shippo test token required')
        inventory.identity('test',seller_ref)
        if type(owner_id) is not int or owner_id<=0:raise RateError('configured shipping account owner required')
        self.seller_ref=seller_ref;self.owner_id=owner_id;self._token=token;self._http=http or ShippoRateHTTP()

    def rates(self,origin,destination,parcel):
        def address(value):
            if not isinstance(value,dict) or value.get('country')!='US':raise RateError('domestic shipping address required')
            for k in ('line1','city','state','postal_code'):
                label(value.get(k),120)
            return dict(street1=value['line1'],street2=value.get('line2',''),city=value['city'],state=value['state'],zip=value['postal_code'],country='US')
        if not isinstance(parcel,dict) or set(parcel)!={'length','width','height','distance_unit','weight','mass_unit'}:
            raise RateError('explicit package dimensions and weight required')
        if parcel['distance_unit']!='cm' or parcel['mass_unit']!='g':raise RateError('configured metric parcel required')
        for key in ('length','width','height','weight'):
            if not isinstance(parcel[key],str) or not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9])?',parcel[key]) or not 0<float(parcel[key])<=150000:
                raise RateError('bounded positive package measurements required')
        payload=dict(address_from=address(origin),address_to=address(destination),parcels=[parcel],**{'async':False})
        value=self._http.request('POST','https://api.goshippo.com/shipments/',
            {'Authorization':'ShippoToken '+self._token,'Shippo-API-Version':'2018-02-08','Content-Type':'application/json','Accept':'application/json'},
            json.dumps(payload,separators=(',',':')).encode())
        if not isinstance(value,dict) or value.get('test') is not True or value.get('status')!='SUCCESS':raise RateError('successful test shipment rates required')
        shipment=reference(value.get('object_id'));rates=value.get('rates')
        if not isinstance(rates,list) or not 1<=len(rates)<=100:raise RateError('no bounded carrier rate set available')
        result=[];seen=set()
        for rate in rates:
            if not isinstance(rate,dict) or rate.get('test') is not True or rate.get('shipment')!=shipment or rate.get('currency')!='USD':
                raise RateError('carrier rate mode, shipment or currency mismatch')
            ident=reference(rate.get('object_id'))
            if ident in seen:raise RateError('duplicate carrier rate reference')
            seen.add(ident);service=rate.get('servicelevel')
            if not isinstance(service,dict):raise RateError('carrier service details required')
            result.append(dict(id=ident,shipment=shipment,amount_cents=money(rate.get('amount')),
                               provider=label(rate.get('provider'),80),service=label(service.get('name'),120),
                               service_token=label(service.get('token'),120)))
        return sorted(result,key=lambda x:(x['amount_cents'],x['provider'],x['service'],x['id']))


SCHEMA='''
CREATE TABLE IF NOT EXISTS marketplace_test_parcel_profiles(
 id TEXT PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL,length_mm INTEGER NOT NULL,width_mm INTEGER NOT NULL,height_mm INTEGER NOT NULL,
 packaging_grams INTEGER NOT NULL,per_item_grams INTEGER NOT NULL,max_units INTEGER NOT NULL,created_at INTEGER NOT NULL,
 UNIQUE(shop_id,revision));
CREATE TRIGGER IF NOT EXISTS marketplace_test_parcel_immutable BEFORE UPDATE ON marketplace_test_parcel_profiles
BEGIN SELECT RAISE(ABORT,'parcel profile is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_parcel_retained BEFORE DELETE ON marketplace_test_parcel_profiles
BEGIN SELECT RAISE(ABORT,'parcel profile is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_test_carrier_rates(
 id TEXT PRIMARY KEY,buyer_id INTEGER NOT NULL REFERENCES users(id),order_id TEXT NOT NULL REFERENCES marketplace_checkout_orders(id),
 context_hash TEXT NOT NULL,location_version TEXT NOT NULL,provider_rate TEXT NOT NULL,shipment_ref TEXT NOT NULL,
 amount_cents INTEGER NOT NULL,provider TEXT NOT NULL,service TEXT NOT NULL,service_token TEXT NOT NULL,
 expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS marketplace_test_carrier_rate_immutable BEFORE UPDATE ON marketplace_test_carrier_rates
BEGIN SELECT RAISE(ABORT,'carrier rate evidence is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_test_carrier_rate_retained BEFORE DELETE ON marketplace_test_carrier_rates
BEGIN SELECT RAISE(ABORT,'carrier rate evidence is retained'); END;
'''


def initialize(db):
    if db.in_transaction:raise RateError('dedicated connection required')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def save_parcel(db,owner,shop_id,revision,length_mm,width_mm,height_mm,packaging_grams,per_item_grams,max_units,now,policy=checkout.NeonrestPolicy):
    inventory.clock(now)
    values=(length_mm,width_mm,height_mm,packaging_grams,per_item_grams,max_units)
    if type(revision) is not int or revision<0 or any(type(v) is not int for v in values):raise RateError('integer package measurements required')
    if any(not 1<=v<=3000 for v in values[:3]) or not 0<=packaging_grams<=70000 or not 1<=per_item_grams<=70000 or not 1<=max_units<=5000:
        raise RateError('package dimensions, weight or capacity out of bounds')
    with inventory.transaction(db):
        checkout.actor(policy,db,owner);shop=checkout.shop_row(db,shop_id)
        if shop['owner_id']!=owner or not policy.owner(db,owner,shop):raise RateError('shop owner required')
        old=db.execute('SELECT revision FROM marketplace_test_parcel_profiles WHERE shop_id=? ORDER BY revision DESC LIMIT 1',(shop_id,)).fetchone()
        if (old[0] if old else 0)!=revision:raise RateError('parcel profile changed; reload')
        ident=uuid.uuid4().hex
        db.execute('INSERT INTO marketplace_test_parcel_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,shop_id,owner,revision+1,*values,now))
        return ident


class CarrierResolver:
    def __init__(self,addresses,selected_rate=None,clock=None):
        self.addresses=addresses;self.selected_rate=selected_rate;self.clock=clock
    @property
    def db(self):return self.addresses.store.db
    def profile(self,seller):
        row=self.db.execute('''SELECT p.* FROM marketplace_test_parcel_profiles p JOIN seller_shops s ON s.page_id=p.shop_id
          WHERE p.shop_id=? AND p.owner_id=s.owner_id ORDER BY p.revision DESC LIMIT 1''',(seller,)).fetchone()
        if not row:raise RateError('seller package dimensions and item weight are required')
        return row
    def resolve_location(self,buyer,seller,reference):
        native=self.addresses.resolve_location(buyer,seller,reference);profile=self.profile(seller)
        version=hashlib.sha256(json.dumps([native.version,profile['id']],separators=(',',':')).encode()).hexdigest()
        return replace(native,version=version)
    def assert_current_location(self,buyer,seller,location):
        if self.resolve_location(buyer,seller,location.reference)!=location:raise RateError('shipping address or parcel profile changed')
    def bind_location_snapshot(self,buyer,seller,location):
        self.assert_current_location(buyer,seller,location)
        native=self.addresses.resolve_location(buyer,seller,location.reference)
        return self.addresses._save_snapshot(buyer,seller,location,native.version)
    def calculation_addresses(self,buyer,seller,reference,expected_version):
        location=self.resolve_location(buyer,seller,reference)
        if location.version!=expected_version:raise RateError('shipping context changed')
        native=self.addresses.resolve_location(buyer,seller,reference)
        result=self.addresses.calculation_addresses(buyer,seller,reference,native.version)
        result['location']=location
        return result
    def parcel(self,context):
        profile=self.profile(context['seller_ref']);count=0
        for line in context['lines']:
            if line['kind']!='physical' or type(line['quantity']) is not int or not 1<=line['quantity']<=99:raise RateError('physical parcel lines required')
            count+=line['quantity']
        if not count or count>profile['max_units']:raise RateError('cart exceeds seller single-package capacity')
        weight=profile['packaging_grams']+profile['per_item_grams']*count
        if weight>70000:raise RateError('cart package is too heavy')
        return dict(length=str(profile['length_mm']/10),width=str(profile['width_mm']/10),height=str(profile['height_mm']/10),distance_unit='cm',weight=str(weight),mass_unit='g')
    def quote_shipping(self,context,context_hash):
        if not callable(self.clock):raise RateError('configured rate clock required')
        now=self.clock();inventory.clock(now)
        row=self.db.execute('SELECT * FROM marketplace_test_carrier_rates WHERE id=? AND buyer_id=? AND order_id=?',
                            (self.selected_rate,context['buyer_id'],context['order_id'])).fetchone()
        if not row or row['context_hash']!=context_hash or row['location_version']!=context['location']['version'] or row['expires_at']<=now:
            raise RateError('select a current shipping service for this cart and address')
        location=self.resolve_location(context['buyer_id'],context['seller_ref'],context['location']['reference'])
        if asdict(location)!=context['location']:raise RateError('shipping context changed')
        return quotes.Assessment('shipping','shippo_test_rates_v1',row['id'],context_hash,row['amount_cents'],row['expires_at'])


def fetch_rates(db,buyer,order_id,destination,resolver,api,now,consent=False,policy=checkout.NeonrestPolicy,clock=None):
    if consent is not True:raise RateError('authorize sharing the destination with Shippo to request rates')
    if not isinstance(api,ShippoTestRatesAPI) or not isinstance(resolver,CarrierResolver):raise RateError('configured test carrier services required')
    if db.in_transaction:raise RateError('rate request requires an idle connection')
    order,snapshot=quotes._fresh_order(db,buyer,order_id,now,policy)
    if api.seller_ref!=order['seller_ref'] or api.owner_id!=order['seller_owner_id']:
        raise RateError('seller shipping account binding mismatch')
    location=resolver.resolve_location(buyer,order['seller_ref'],destination)
    context=quotes._context(order,snapshot,location);digest=quotes._hash(context)
    addresses=resolver.calculation_addresses(buyer,order['seller_ref'],destination,location.version)
    rates=api.rates(addresses['origin'],addresses['destination'],resolver.parcel(context))
    finished=clock() if clock else now;inventory.clock(finished)
    if finished<now or finished>=min(now+300,order['expires_at']):raise RateError('shipping request expired; request new rates')
    result=[]
    with inventory.transaction(db):
        current,current_snapshot=quotes._fresh_order(db,buyer,order_id,finished,policy)
        resolver.assert_current_location(buyer,order['seller_ref'],location)
        if quotes._hash(quotes._context(current,current_snapshot,location))!=digest:raise RateError('cart changed while obtaining rates')
        for rate in rates:
            ident=uuid.uuid4().hex;expiry=min(finished+300,order['expires_at'])
            db.execute('INSERT INTO marketplace_test_carrier_rates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident,buyer,order_id,digest,location.version,rate['id'],rate['shipment'],rate['amount_cents'],rate['provider'],rate['service'],rate['service_token'],expiry,finished))
            result.append(dict(id=ident,amount_cents=rate['amount_cents'],provider=rate['provider'],service=rate['service'],expires_at=expiry))
    return result
