"""Flask/SQLite integration with fictional addresses and deterministic provider HTTP."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from flask import Flask,abort,request
from jinja2 import ChoiceLoader,DictLoader
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_pilot_views as views
import marketplace_pilot_orders as orders
import marketplace_addresses as addresses
import marketplace_carrier_rates as carrier
import marketplace_purchase_flow as flow
import marketplace_payments as payments
import marketplace_settlement as settlement
import marketplace_refunds as refunds
import marketplace_ledger as ledger
from marketplace_test_checkout_api import StripeTestCheckoutAPI
from verify_marketplace_addresses import setup,ADDRESS
from verify_marketplace_purchase_flow import Policy,HTTP
from verify_marketplace_carrier_rates import HTTP as CarrierHTTP
from verify_marketplace_quotes import QuoteServices
from verify_marketplace_payments import OnboardingFixture,signed_event,SECRET

class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'pilot.sqlite');self.key=Fernet.generate_key();self.clock=110;self.tax_enabled=True
        db=self.connect();self.sku,store,dest,origin,resolver=setup(db,self.key)
        payments.initialize(db);settlement.initialize(db);refunds.initialize(db);flow.initialize(db);carrier.initialize(db);orders.initialize(db);views.initialize_marker(db)
        carrier.save_parcel(db,1,'shop-a',0,180,130,25,15,12,10,100,Policy)
        scope=payments.Scope('stripe','acct_platform');onboarding=payments.begin_onboarding(db,1,'shop-a',scope,'pilot-seller',100,Policy)
        payments.complete_onboarding(db,1,onboarding,OnboardingFixture(scope),100,Policy)
        self.http=HTTP(db,onboarding);self.carrier_http=CarrierHTTP(db);db.close()
        self.app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'));self.app.config.update(TESTING=True,SECRET_KEY='fixture',MARKETPLACE_TEST_PILOT=True)
        self.app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'<!doctype html><title>{% block title %}{% endblock %}</title>{% block content %}{% endblock %}'}),self.app.jinja_loader]);self.app.jinja_env.globals['community_token']=lambda:'fixture-csrf'
        def csrf():
            if request.form.get('theme_csrf_token')!='fixture-csrf':abort(403)
        self.app.extensions['community_auth_helpers']={'csrf':csrf,'limited':lambda *args:None}
        views.register(self.app,self.connect,self.services,lambda uid:True,[1,2,3,4],'sandbox')
        self.client=self.app.test_client();self.login(2);Policy.published_ids={'a'}
    def tearDown(self):self.tmp.cleanup()
    def connect(self):
        db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db
    def services(self,db):
        self.http.db=db;self.carrier_http.db=db
        store=addresses.AddressStore(db,addresses.FernetVault([self.key]),Policy);tax=QuoteServices(db);tax.shipping=525
        return views.PilotServices(db,Policy,store,addresses.AddressResolver(store),StripeTestCheckoutAPI('acct_platform','sk_test_fixture_only',self.http),lambda shop,owner:carrier.ShippoTestRatesAPI('shippo_test_fictional_token_only',shop,owner,self.carrier_http),tax if self.tax_enabled else None,lambda:self.clock)
    def login(self,uid):
        with self.client.session_transaction() as s:s['user_id']=uid
    def post(self,path,data=None):return self.client.post('/marketplace/pilot'+path,data=dict(theme_csrf_token='fixture-csrf',**(data or {})))
    def start(self):
        r=self.post('/checkout',dict(ADDRESS,sku=self.sku,quantity='1',revision='0',request_key='ui-order'))
        self.assertEqual(r.status_code,302,r.data);self.order=r.location.rsplit('/',1)[1];return self.order
    def query(self,sql,args=()):
        db=self.connect()
        try:return db.execute(sql,args).fetchall()
        finally:db.close()
    def quote(self):
        self.assertEqual(self.post('/orders/'+self.order+'/rates',{'share_address':'yes'}).status_code,302)
        rate=self.query('SELECT id FROM marketplace_test_carrier_rates')[0][0]
        r=self.post('/orders/'+self.order+'/quote',{'rate':rate,'request_key':'ui-quote'});self.assertEqual(r.status_code,302,r.data)
        return self.query('SELECT id FROM marketplace_checkout_quotes')[0][0]
    def paid(self):
        self.start();q=self.quote();r=self.post('/orders/'+self.order+'/pay',{'quote_id':q,'accept_total':'yes','test_card':'pm_card_visa'});self.assertEqual(r.status_code,302,r.data)
        # The successful POST alone must not settle stock/payment.
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],0)
        db=self.connect();ctx=self.services(db);adapter=payments.StripeTestWebhookAdapter('acct_platform',[SECRET],ctx.stripe.fetch_payment)
        raw,sig=signed_event(payment='pi_flow1',now=self.clock);payments.receive_stripe(db,adapter,raw,sig,self.clock,Policy);db.close()
        r=self.post('/orders/'+self.order+'/refresh');self.assertEqual(r.status_code,302,r.data)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],1)
    def test_complete_request_flow_receipts_tracking_and_refund(self):
        self.assertEqual(self.client.get('/marketplace/pilot/').status_code,200)
        self.paid();url='/orders/'+self.order
        r=self.client.get('/marketplace/pilot'+url);self.assertEqual(r.status_code,200,r.data);self.assertIn(b'USD 16.15',r.data);self.assertNotIn(ADDRESS['line1'].encode(),r.data)
        self.assertEqual(self.post(url+'/destination').status_code,400)
        self.login(1);self.assertEqual(self.client.get('/marketplace/pilot/seller/orders').status_code,200)
        r=self.post(url+'/destination');self.assertEqual(r.status_code,200,r.data);self.assertIn(ADDRESS['line1'].encode(),r.data)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_pilot_fulfillment_views')[0][0],1)
        r=self.post(url+'/ship',{'request_key':'ship-ui','carrier':'USPS','tracking':'9400000000000000000000'});self.assertEqual(r.status_code,302,r.data)
        r=self.post(url+'/refund',{'request_key':'refund-ui','item_cents':'1000','shipping_cents':'525','tax_cents':'90'});self.assertEqual(r.status_code,302,r.data)
        db=self.connect();self.assertTrue(all(n==0 for n in ledger.balances(db,'test').values()));self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[]);db.close()
        self.assertEqual((self.http.created,self.http.refunded),(1,1))
    def test_no_confirmation_without_consent_or_configured_tax(self):
        self.start();url='/orders/'+self.order
        self.assertEqual(self.post(url+'/rates').status_code,400);self.assertEqual(self.carrier_http.calls,[])
        self.tax_enabled=False
        self.assertEqual(self.post(url+'/quote',{'rate':'anything','request_key':'bad'}).status_code,400)
        self.tax_enabled=True;q=self.quote()
        self.assertEqual(self.post(url+'/pay',{'quote_id':q}).status_code,400);self.assertEqual(self.http.created,0)
    def test_private_session_csrf_underage_and_unpaid_fulfillment(self):
        self.start();url='/orders/'+self.order
        self.assertEqual(self.client.post('/marketplace/pilot'+url+'/cancel').status_code,403)
        self.login(1);self.assertEqual(self.post(url+'/destination').status_code,400)
        self.assertEqual(self.post(url+'/ship',{'request_key':'unpaid','carrier':'USPS','tracking':'123456'}).status_code,400)
        self.login(3);self.assertEqual(self.client.get('/marketplace/pilot'+url).status_code,400)
        self.login(4);self.assertEqual(self.client.get('/marketplace/pilot/').status_code,400)
        with self.client.session_transaction() as s:s.clear()
        self.assertEqual(self.client.get('/marketplace/pilot/').status_code,401)
    def test_historical_paid_destination_does_not_change_with_address_book(self):
        self.paid();db=self.connect();ctx=self.services(db)
        dest=db.execute('SELECT destination_id FROM marketplace_pilot_destinations').fetchone()[0]
        ctx.address_store.edit(2,dest,0,dict(ADDRESS,line1='99 Changed Fictional Road'),self.clock);db.close()
        self.login(1);r=self.post('/orders/'+self.order+'/destination');self.assertEqual(r.status_code,200,r.data);self.assertIn(ADDRESS['line1'].encode(),r.data);self.assertNotIn(b'99 Changed',r.data)
    def test_lost_payment_response_reuses_original_submission(self):
        self.start();q=self.quote();self.http.timeout=True
        r=self.post('/orders/'+self.order+'/pay',{'quote_id':q,'accept_total':'yes','test_card':'pm_card_visa'})
        self.assertEqual(r.status_code,503);self.assertEqual(self.http.created,1)
        r=self.post('/orders/'+self.order+'/retry-payment');self.assertEqual(r.status_code,302,r.data);self.assertEqual(self.http.created,1)
    def test_lost_refund_response_reuses_original_request(self):
        self.paid();self.login(1);self.http.timeout=True
        r=self.post('/orders/'+self.order+'/refund',{'request_key':'refund-timeout','item_cents':'1000','shipping_cents':'525','tax_cents':'90'})
        self.assertEqual(r.status_code,503);self.assertEqual(self.http.refunded,1)
        ident=self.query('SELECT id FROM marketplace_test_refund_requests')[0][0]
        r=self.post('/orders/'+self.order+'/refunds/'+ident+'/retry');self.assertEqual(r.status_code,302,r.data);self.assertEqual(self.http.refunded,1)
    def test_isolated_database_marker_required(self):
        db=self.connect();db.execute('DROP TABLE marketplace_pilot_marker');db.commit();db.close()
        self.assertEqual(self.client.get('/marketplace/pilot/').status_code,503)
    def test_catalog_navigation_has_distinct_valid_order_links(self):
        r=self.client.get('/marketplace/pilot/');self.assertIn(b'href="/marketplace/pilot/purchases"',r.data);self.assertIn(b'href="/marketplace/pilot/seller/orders"',r.data);self.assertNotIn(b'/../',r.data)
        self.assertEqual(r.headers['Cache-Control'],'private, no-store')

if __name__=='__main__':unittest.main()
