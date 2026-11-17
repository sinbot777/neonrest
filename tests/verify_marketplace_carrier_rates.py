from pathlib import Path
import copy
import json
import sqlite3
import sys
import unittest
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_carrier_rates as carrier
import marketplace_checkout as checkout
import marketplace_quotes as quotes
from verify_marketplace_addresses import setup,ADDRESS
from verify_marketplace_checkout import FixturePolicy
from verify_marketplace_quotes import QuoteServices


class HTTP:
    def __init__(self,db):
        self.db=db;self.calls=[];self.hook=lambda:None
        self.value=dict(object_id='a'*32,test=True,status='SUCCESS',rates=[dict(object_id='b'*32,test=True,shipment='a'*32,currency='USD',amount='5.25',provider='USPS',servicelevel={'name':'Ground Advantage','token':'usps_ground_advantage'})])
    def request(self,method,url,headers,body):
        assert not self.db.in_transaction
        self.calls.append((method,url,headers,json.loads(body)));self.hook()
        return copy.deepcopy(self.value)


class CarrierTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.sku,self.store,self.dest,self.origin,self.addresses=setup(self.db,Fernet.generate_key())
        carrier.initialize(self.db)
        carrier.save_parcel(self.db,1,'shop-a',0,180,130,25,15,12,10,100,FixturePolicy)
        self.order=checkout.create_order(self.db,'test',2,'shop-a','carrier',[(self.sku,2,0)],100,FixturePolicy)
        self.resolver=carrier.CarrierResolver(self.addresses,clock=lambda:103)
        self.http=HTTP(self.db);self.api=carrier.ShippoTestRatesAPI('shippo_test_fictional_token_only','shop-a',1,self.http)
    def tearDown(self):self.db.close()
    def fetch(self,**values):
        args=dict(db=self.db,buyer=2,order_id=self.order,destination=self.dest['id'],resolver=self.resolver,api=self.api,now=101,consent=True,policy=FixturePolicy)
        args.update(values);return carrier.fetch_rates(**args)

    def test_rates_use_measured_parcel_and_minimum_address_fields_without_buying_label(self):
        result=self.fetch();self.assertEqual(result[0]['amount_cents'],525)
        method,url,headers,payload=self.http.calls[0]
        self.assertEqual((method,url),('POST','https://api.goshippo.com/shipments/'))
        self.assertEqual(payload['parcels'],[dict(length='18.0',width='13.0',height='2.5',distance_unit='cm',weight='39',mass_unit='g')])
        self.assertEqual(payload['address_to']['zip'],'00123')
        self.assertNotIn('recipient',json.dumps(payload));self.assertNotIn(ADDRESS['recipient'],json.dumps(payload))
        self.assertNotIn(ADDRESS['line1'],'\n'.join(self.db.iterdump()))
        self.assertNotIn('shippo_test',json.dumps(result))

    def test_selected_rate_is_in_complete_quote_and_tax_sees_shipping(self):
        rate=self.fetch()[0];self.resolver.selected_rate=rate['id'];tax=QuoteServices(self.db);tax.shipping=525
        quote=quotes.create_quote(self.db,2,self.order,self.dest['id'],'selected',self.resolver,self.resolver,tax,102,FixturePolicy)
        value=quotes.get_quote(self.db,2,quote,self.resolver,103,FixturePolicy)['snapshot']
        self.assertEqual((value['subtotal_cents'],value['shipping_cents'],value['tax_cents'],value['total_cents']),(2000,525,90,2615))
        self.assertEqual(value['shipping_evidence']['source'],'shippo_test_rates_v1')
        quotes.accept_quote(self.db,2,quote,self.resolver,103,FixturePolicy)

    def test_explicit_address_sharing_consent_and_correct_buyer_required(self):
        with self.assertRaises(carrier.RateError):self.fetch(consent=False)
        with self.assertRaises(ValueError):self.fetch(buyer=3)
        self.assertEqual(self.http.calls,[])

    def test_live_keys_live_responses_and_non_usd_rates_are_rejected(self):
        with self.assertRaises(carrier.RateError):carrier.ShippoTestRatesAPI('shippo_live_never_allowed','shop-a',1,self.http)
        self.http.value['test']=False
        with self.assertRaises(carrier.RateError):self.fetch()
        self.http.value['test']=True;self.http.value['rates'][0]['currency']='EUR'
        with self.assertRaises(carrier.RateError):self.fetch()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_test_carrier_rates').fetchone()[0],0)

    def test_tampered_cross_order_or_expired_rate_cannot_enter_quote(self):
        rate=self.fetch()[0];tax=QuoteServices(self.db);tax.shipping=525
        for selection in ('not-a-rate',):
            self.resolver.selected_rate=selection
            with self.assertRaises(carrier.RateError):quotes.create_quote(self.db,2,self.order,self.dest['id'],'bad-rate',self.resolver,self.resolver,tax,102,FixturePolicy)
        self.resolver.selected_rate=rate['id'];self.resolver.clock=lambda:402
        with self.assertRaises(carrier.RateError):quotes.create_quote(self.db,2,self.order,self.dest['id'],'expired-rate',self.resolver,self.resolver,tax,402,FixturePolicy)

    def test_package_and_address_changes_invalidate_rates(self):
        rate=self.fetch()[0];self.resolver.selected_rate=rate['id']
        carrier.save_parcel(self.db,1,'shop-a',1,180,130,25,15,14,10,102,FixturePolicy)
        tax=QuoteServices(self.db)
        with self.assertRaises(carrier.RateError):quotes.create_quote(self.db,2,self.order,self.dest['id'],'changed',self.resolver,self.resolver,tax,103,FixturePolicy)

    def test_changes_during_provider_lookup_do_not_store_stale_rates(self):
        self.http.hook=lambda:self.store.edit(2,self.dest['id'],0,dict(ADDRESS,line1='Changed fictional road'),102)
        with self.assertRaises(carrier.RateError):self.fetch()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_test_carrier_rates').fetchone()[0],0)

    def test_missing_dimensions_over_capacity_foreign_shipping_account_and_invalid_amount(self):
        wrong=carrier.ShippoTestRatesAPI('shippo_test_fictional_token_only','shop-b',3,self.http)
        with self.assertRaises(carrier.RateError):self.fetch(api=wrong)
        carrier.save_parcel(self.db,1,'shop-a',1,180,130,25,15,12,1,101,FixturePolicy)
        with self.assertRaises(carrier.RateError):self.fetch()
        with self.assertRaises(carrier.RateError):carrier.save_parcel(self.db,1,'shop-a',2,0,130,25,15,12,10,101,FixturePolicy)
        for value in ('5.001','NaN','1e2','-1.00',True):
            with self.assertRaises(carrier.RateError):carrier.money(value)
        self.assertEqual(self.http.calls,[])

    def test_no_label_or_arbitrary_network_operation_is_exposed(self):
        transport=carrier.ShippoRateHTTP()
        for url in ('https://api.goshippo.com/transactions/','http://api.goshippo.com/shipments/','https://evil.test/shipments/'):
            with self.assertRaises(carrier.RateError):transport.request('POST',url,{},b'{}')

if __name__=='__main__':unittest.main()
