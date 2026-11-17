"""Owner/session isolation, secret storage, per-item packing and quote freshness."""
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_seller_shipping as shipping
import marketplace_carrier_rates as carrier
import marketplace_checkout as checkout
import marketplace_quotes as quotes
import verify_marketplace_pilot_views as pilot_helpers
from verify_marketplace_addresses import ADDRESS
from verify_marketplace_purchase_flow import Policy
from verify_marketplace_quotes import QuoteServices

TOKEN='shippo_test_fake_private_seller_token'
class Verifier:
    def __init__(self):self.calls=0;self.db=None;self.hook=lambda:None
    def verify(self,token):
        assert not self.db.in_transaction;self.calls+=1;self.hook();return True

class SellerShippingTests(unittest.TestCase):
    connect=pilot_helpers.PilotTests.connect;login=pilot_helpers.PilotTests.login;post=pilot_helpers.PilotTests.post;query=pilot_helpers.PilotTests.query
    start=pilot_helpers.PilotTests.start;quote=pilot_helpers.PilotTests.quote;paid=pilot_helpers.PilotTests.paid
    def setUp(self):
        pilot_helpers.PilotTests.setUp(self);self.verifier=Verifier()
        db=self.connect();shipping.initialize(db);ctx=self.services(db);s=ctx.shipping_settings
        self.preset=s.save_preset(1,'shop-a',None,0,'Small mailer',180000,130000,25000,15000,3,True,100)
        s.save_weight(1,'shop-a',self.sku,0,12000,100);s.save_connection(1,'shop-a',0,TOKEN,100);db.close()
    tearDown=pilot_helpers.PilotTests.tearDown
    def services(self,db):
        ctx=pilot_helpers.PilotTests.services(self,db)
        if not hasattr(self,'verifier'):return ctx
        self.verifier.db=db;ctx.shipping_settings=shipping.SellerShipping(db,ctx.address_store.vault,Policy,self.verifier,self.carrier_http)
        return ctx
    def seller(self):self.login(1)
    def settings(self,db):return self.services(db).shipping_settings
    def test_setup_form_does_not_reveal_key_and_shops_are_separate(self):
        self.seller();r=self.client.get('/marketplace/pilot/seller/shipping/shop-a')
        self.assertEqual(r.status_code,200,r.data);self.assertIn(b'Connected in test mode',r.data);self.assertNotIn(TOKEN.encode(),r.data)
        self.assertIn(b'Small mailer',r.data);self.assertIn(b'Weight per item',r.data)
        self.assertEqual(self.client.get('/marketplace/pilot/seller/shipping/shop-b').status_code,400)
        self.login(3);r=self.client.get('/marketplace/pilot/seller/shipping/shop-b');self.assertEqual(r.status_code,200,r.data);self.assertNotIn(b'Small mailer',r.data)
        self.assertEqual(self.client.get('/marketplace/pilot/seller/shipping/shop-a').status_code,400)
    def test_no_plaintext_token_or_origin_in_database_or_public_results(self):
        db=self.connect();s=self.settings(db)
        dump='\n'.join(db.iterdump());self.assertNotIn(TOKEN,dump);self.assertNotIn(ADDRESS['line1'],dump)
        self.assertNotIn(TOKEN,json.dumps(s.public(1,'shop-a')))
        with self.assertRaises(ValueError):s.api('shop-a',3)
        api=s.api('shop-a',1);self.assertEqual((api.owner_id,api.seller_ref),(1,'shop-a'));db.close()
    def test_fresh_setup_drives_rates_full_quote_payment_and_refund(self):
        self.paid();payload=self.carrier_http.calls[0][3]
        self.assertEqual(payload['parcels'],[dict(length='18',width='13',height='2.5',distance_unit='cm',weight='27',mass_unit='g')])
        self.assertEqual(self.http.created,1)
    def test_each_variation_needs_a_weight_and_capacity_is_enforced(self):
        db=self.connect();s=self.settings(db)
        context=dict(seller_ref='shop-a',lines=[dict(kind='physical',quantity=2,sku=self.sku)])
        self.assertEqual(s.parcel(context)['weight'],'39')
        context['lines'][0]['quantity']=4
        with self.assertRaises(shipping.ShippingError):s.parcel(context)
        context['lines'][0].update(quantity=1,sku='unknown')
        with self.assertRaises(shipping.ShippingError):s.parcel(context)
        db.close()
    def test_smallest_eligible_package_is_selected_and_disabled_package_is_ignored(self):
        db=self.connect();s=self.settings(db)
        large=s.save_preset(1,'shop-a',None,0,'Larger box',300000,200000,100000,50000,20,True,101)
        c=dict(seller_ref='shop-a',lines=[dict(kind='physical',quantity=4,sku=self.sku)])
        self.assertEqual(s.parcel(c)['weight'],'98')
        s.save_preset(1,'shop-a',large,1,'Larger box',300000,200000,100000,50000,20,False,102)
        with self.assertRaises(shipping.ShippingError):s.parcel(c)
        db.close()
    def test_weight_changes_and_disconnect_invalidate_saved_carrier_rates(self):
        self.start();self.assertEqual(self.post('/orders/'+self.order+'/rates',{'share_address':'yes'}).status_code,302)
        rate=self.query('SELECT id FROM marketplace_test_carrier_rates')[0][0]
        db=self.connect();ctx=self.services(db);ctx.shipping_settings.save_weight(1,'shop-a',self.sku,1,14000,111)
        loc=ctx.location(rate);tax=QuoteServices(db);tax.shipping=525
        with self.assertRaises(ValueError):quotes.create_quote(db,2,self.order,db.execute('SELECT destination_id FROM marketplace_pilot_destinations').fetchone()[0],'stale',loc,loc,tax,112,Policy)
        ctx.shipping_settings.disconnect(1,'shop-a',1,113)
        with self.assertRaises(ValueError):ctx.shipping_settings.api('shop-a',1)
        with self.assertRaises(ValueError):ctx.shipping_settings.fingerprint('shop-a')
        db.close()
    def test_presets_and_weights_have_owner_checks_and_optimistic_revisions(self):
        db=self.connect();s=self.settings(db)
        with self.assertRaises(ValueError):s.save_weight(3,'shop-a',self.sku,1,13000,111)
        with self.assertRaises(ValueError):s.save_weight(1,'shop-a',self.sku,0,13000,111)
        with self.assertRaises(ValueError):s.save_preset(3,'shop-b',self.preset,1,'Hijack',1,1,1,0,1,True,111)
        with self.assertRaises(ValueError):s.save_preset(1,'shop-a',self.preset,0,'Stale',1,1,1,0,1,True,111)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[]);db.close()
    def test_connection_live_keys_missing_consent_and_csrf_are_refused(self):
        self.seller();url='/seller/shipping/shop-a/connection';before=self.verifier.calls
        self.assertEqual(self.post(url,{'api_token':TOKEN,'revision':'1'}).status_code,400)
        self.assertEqual(self.post(url,{'api_token':'shippo_live_no','revision':'1','consent':'yes'}).status_code,400)
        self.assertEqual(self.client.post('/marketplace/pilot'+url,data={'api_token':TOKEN,'revision':'1','consent':'yes'}).status_code,403)
        self.assertEqual(self.verifier.calls,before)
    def test_owner_change_during_verification_prevents_binding(self):
        db=self.connect();s=self.settings(db)
        def change():db.execute("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'");db.commit()
        self.verifier.hook=change
        with self.assertRaises(ValueError):s.save_connection(1,'shop-a',1,TOKEN,111)
        self.assertEqual(s.connection('shop-a')['revision'],1)
        with self.assertRaises(ValueError):s.api('shop-a',3)
        db.close()
    def test_precision_units_do_not_round_quarter_inch_down_or_lose_small_weights(self):
        self.assertEqual(shipping.measurement('0.25','in','distance'),6350)
        self.assertEqual(shipping.measurement('6.50','in','distance'),165100)
        self.assertEqual(shipping.measurement('0.34','oz','mass'),9639)
        for v in ('NaN','1e3','-1','inf','1,2'):
            with self.assertRaises(ValueError):shipping.measurement(v,'g','mass')
    def test_owner_forms_save_origin_preset_weight_and_disconnect(self):
        self.seller();root='/seller/shipping/shop-a'
        r=self.post(root+'/package',dict(revision='0',name='Envelope',length='6.5',width='4.75',height='.25',distance_unit='in',packaging_weight='1',mass_unit='g',max_units='1',enabled='yes'))
        self.assertEqual(r.status_code,302,r.data)
        r=self.post(root+'/package',dict(revision='0',name='Envelope',length='6.5',width='4.75',height='0.25',distance_unit='in',packaging_weight='1',mass_unit='g',max_units='1',enabled='yes'))
        self.assertEqual(r.status_code,302,r.data)
        r=self.post(root+'/weight',dict(sku=self.sku,revision='1',weight='0.34',mass_unit='oz'));self.assertEqual(r.status_code,302,r.data)
        r=self.post(root+'/origin',dict(ADDRESS,request_key='new-shop-origin'));self.assertEqual(r.status_code,302,r.data)
        r=self.post(root+'/connection',dict(revision='1',disconnect='yes'));self.assertEqual(r.status_code,302,r.data)
    def test_provider_verification_failure_never_saves_a_new_connection(self):
        db=self.connect();s=self.settings(db);self.verifier.verify=lambda token:False
        with self.assertRaises(ValueError):s.save_connection(1,'shop-a',1,TOKEN,111)
        self.assertEqual(s.connection('shop-a')['revision'],1);db.close()
    def test_ciphertext_is_bound_to_shop_and_connection_revision(self):
        db=self.connect();s=self.settings(db);row=s.connection('shop-a');envelope=s.vault.open(row['ciphertext'])
        self.assertEqual(envelope['shop_id'],'shop-a');self.assertEqual(envelope['owner_id'],1)
        class WrongEnvelope:
            def open(self,cipher):return dict(envelope,shop_id='shop-b')
        s.vault=WrongEnvelope()
        with self.assertRaises(ValueError):s.api('shop-a',1)
        db.close()
    def test_changed_package_invalidates_location_even_without_item_weight_change(self):
        self.start();db=self.connect();ctx=self.services(db)
        destination=db.execute('SELECT destination_id FROM marketplace_pilot_destinations').fetchone()[0]
        before=ctx.location().resolve_location(2,'shop-a',destination)
        ctx.shipping_settings.save_preset(1,'shop-a',self.preset,1,'Updated mailer',180000,130000,30000,15000,3,True,111)
        with self.assertRaises(ValueError):ctx.location().assert_current_location(2,'shop-a',before)
        db.close()
    def test_mixed_variations_use_each_items_own_weight(self):
        db=self.connect();s=self.settings(db)
        db.execute("UPDATE seller_listings SET variations=?,revision=1 WHERE id='a'",(json.dumps([dict(label='Light',price_cents=1000,quantity=3),dict(label='Heavy',price_cents=1200,quantity=3)]),));db.commit()
        skus=checkout.sync_listing(db,'test',1,'shop-a','a',1,101,Policy)
        s.save_weight(1,'shop-a',skus[0]['sku'],0,5000,102);s.save_weight(1,'shop-a',skus[1]['sku'],0,25000,102)
        c=dict(seller_ref='shop-a',lines=[dict(kind='physical',quantity=2,sku=skus[0]['sku']),dict(kind='physical',quantity=1,sku=skus[1]['sku'])])
        self.assertEqual(s.parcel(c)['weight'],'50');db.close()
    def test_disconnected_shop_rate_request_never_reuses_legacy_or_other_shop_key(self):
        self.start();db=self.connect();s=self.settings(db);s.disconnect(1,'shop-a',1,111);db.close()
        r=self.post('/orders/'+self.order+'/rates',dict(share_address='yes'))
        self.assertEqual(r.status_code,400);self.assertEqual(self.carrier_http.calls,[])
    def test_shipping_history_is_immutable_and_repeat_migration_keeps_rows(self):
        db=self.connect();shipping.initialize(db)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_test_shipping_connections').fetchone()[0],1)
        import sqlite3
        for table in ('marketplace_test_shipping_connections','marketplace_test_package_presets','marketplace_test_item_weights','marketplace_test_shipping_setup_events'):
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM '+table)
            db.rollback()
        db.close()
    def test_second_seller_has_independent_key_package_and_weights(self):
        db=self.connect();s=self.settings(db);sku=checkout.sync_listing(db,'test',3,'shop-b','b',0,100,Policy)[0]['sku']
        other='shippo_test_another_owner_private_token';s.save_connection(3,'shop-b',0,other,101)
        s.save_preset(3,'shop-b',None,0,'Other box',250000,150000,80000,10000,10,True,101);s.save_weight(3,'shop-b',sku,0,20000,101)
        parcel=s.parcel(dict(seller_ref='shop-b',lines=[dict(kind='physical',quantity=2,sku=sku)]));self.assertEqual(parcel['weight'],'50')
        self.assertNotIn('Small mailer',json.dumps(s.public(3,'shop-b')));self.assertNotIn(other,'\n'.join(db.iterdump()));db.close()

if __name__=='__main__':unittest.main()
