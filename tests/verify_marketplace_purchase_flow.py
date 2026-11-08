"""Accepted quote -> actual creation adapter -> signed receipt -> settlement/refund.

Provider HTTP is a deterministic fixture; no external financial operation occurs.
"""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from urllib.parse import parse_qs
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_purchase_flow as flow
import marketplace_checkout as checkout
import marketplace_payments as payments
import marketplace_quotes as quotes
import marketplace_refunds as refunds
import marketplace_settlement as settlement
import marketplace_ledger as ledger
from marketplace_test_checkout_api import StripeTestCheckoutAPI
from verify_marketplace_addresses import setup
from verify_marketplace_checkout import FixturePolicy
from verify_marketplace_quotes import QuoteServices
from verify_marketplace_payments import OnboardingFixture,signed_event,SECRET


class Policy(FixturePolicy):
    published_ids={'a'}
    @classmethod
    def published(cls,db,listing,buyer): return listing in cls.published_ids


class HTTP:
    def __init__(self,db,onboarding):
        self.db=db;self.onboarding=onboarding;self.objects={};self.keys={};self.created=0;self.refunded=0
        self.owner='1';self.enabled=True;self.timeout=False;self.hook=lambda value:None
    def request(self,method,url,headers,body=None):
        assert not self.db.in_transaction,'network under write lock'
        if url.endswith('/v1/account'):return dict(id='acct_platform',object='account')
        if '/accounts/' in url:return dict(id='acct_fixture',object='account',country='US',charges_enabled=self.enabled,payouts_enabled=self.enabled,metadata={'neonrest_owner':self.owner,'neonrest_onboarding':self.onboarding})
        if method=='GET': return self.objects[url.rsplit('/',1)[-1]]
        data={k:v[0] for k,v in parse_qs(body.decode()).items()};key=headers['Idempotency-Key']
        if key in self.keys:
            assert self.keys[key][0]==data,'changed idempotent request'
            return self.keys[key][1]
        if url.endswith('/payment_intents'):
            self.created+=1;ident='pi_flow'+str(self.created)
            status='requires_payment_method' if data['payment_method']=='pm_card_chargeDeclined' else 'succeeded'
            value=dict(id=ident,object='payment_intent',livemode=False,status=status,currency='usd',amount=int(data['amount']),amount_received=int(data['amount']) if status=='succeeded' else 0,
                       metadata={'neonrest_order':data['metadata[neonrest_order]'],'neonrest_quote':data['metadata[neonrest_quote]']})
        else:
            self.refunded+=1;ident='re_flow'+str(self.refunded)
            value=dict(id=ident,object='refund',payment_intent=data['payment_intent'],status='succeeded',currency='usd',amount=int(data['amount']),created=110,
                       metadata={'neonrest_order':data['metadata[neonrest_order]'],'neonrest_refund_request':data['metadata[neonrest_refund_request]']})
        self.objects[ident]=value;self.keys[key]=(data,value)
        self.hook(value)
        if self.timeout:
            self.timeout=False;raise TimeoutError('fictional response lost after provider write')
        return value


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');Policy.published_ids={'a'}
        self.sku,self.store,self.destination,self.origin,self.location=setup(self.db,Fernet.generate_key())
        payments.initialize(self.db);settlement.initialize(self.db);refunds.initialize(self.db);flow.initialize(self.db)
        self.services=QuoteServices(self.db)
        self.order=checkout.create_order(self.db,'test',2,'shop-a','flow-order',[(self.sku,1,0)],100,Policy)
        self.quote=quotes.create_quote(self.db,2,self.order,self.destination['id'],'flow-quote',self.location,self.services,self.services,101,Policy)
        quotes.accept_quote(self.db,2,self.quote,self.location,102,Policy)
        scope=payments.Scope('stripe','acct_platform')
        self.onboarding=payments.begin_onboarding(self.db,1,'shop-a',scope,'flow-seller',102,Policy)
        self.account=payments.complete_onboarding(self.db,1,self.onboarding,OnboardingFixture(scope),102,Policy)
        self.http=HTTP(self.db,self.onboarding);self.api=StripeTestCheckoutAPI('acct_platform','sk_test_fixture_only',self.http)
        self.adapter=payments.StripeTestWebhookAdapter('acct_platform',[SECRET],self.api.fetch_payment)
    def tearDown(self):self.db.close()
    def prepare(self,method='pm_card_visa',buyer=2):return flow.prepare_payment(self.db,buyer,self.quote,self.location,method,103,Policy)
    def dispatch(self,**kw):return flow.dispatch_payment(self.db,2,self.order,self.api,self.location,104,Policy,**kw)
    def event(self,payment='pi_flow1',kind='payment_intent.succeeded',now=106):
        raw,sig=signed_event(payment=payment,kind=kind,now=now)
        return payments.receive_stripe(self.db,self.adapter,raw,sig,now,Policy)['receipt_id']
    def settled(self):
        self.prepare();self.dispatch();receipt=self.event()
        result=flow.settle_received_payment(self.db,receipt,self.location,107,Policy)
        self.assertEqual(result['outcome'],'test_settled');return receipt

    def test_complete_purchase_and_refund_uses_full_quote_once(self):
        receipt=self.settled()
        self.assertEqual(checkout.get_order(self.db,'test',2,self.order,108,Policy)['state'],'test_settled')
        self.assertEqual(self.http.objects['pi_flow1']['amount'],1590)
        self.assertEqual(self.db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(self.sku,)).fetchone()[0],2)
        again=flow.settle_received_payment(self.db,receipt,self.location,109,Policy)
        self.assertEqual(again['outcome'],'test_settled')
        request=refunds.request_test_refund(self.db,1,self.order,'full-refund',1000,500,90,110,Policy)
        flow.dispatch_refund(self.db,1,request,self.api,111,Policy)
        reader=refunds.StripeTestRefundReader(self.adapter,self.api.fetch_refund)
        self.assertEqual(refunds.process_request(self.db,reader,request,112)['outcome'],'complete')
        flow.dispatch_refund(self.db,1,request,self.api,113,Policy)
        self.assertEqual((self.http.created,self.http.refunded),(1,1))
        self.assertTrue(all(n==0 for n in ledger.balances(self.db,'test').values()))
        self.assertEqual(refunds.get_summary(self.db,2,self.order,114,Policy)['state'],'test_refunded')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_timeout_after_charge_is_retried_without_second_charge(self):
        self.prepare();self.http.timeout=True
        with self.assertRaises(TimeoutError):self.dispatch()
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_test_payment_dispatches').fetchone()[0],'prepared')
        self.assertEqual(self.dispatch()['state'],'bound')
        self.assertEqual(self.http.created,1)
        self.assertEqual(self.dispatch()['state'],'bound')

    def test_webhook_can_arrive_before_creation_returns(self):
        early=[]
        self.http.hook=lambda value:early.append(self.event(value['id'],now=104))
        self.prepare();self.dispatch()
        self.assertEqual(self.db.execute('SELECT reason FROM marketplace_payment_events').fetchone()[0],'unbound_payment')
        flow.recover_early_receipts(self.db,self.order,self.adapter,105,Policy)
        self.assertEqual(flow.settle_received_payment(self.db,early[0],self.location,106,Policy)['outcome'],'test_settled')
        self.assertEqual(self.http.created,1)

    def test_lost_response_recovers_from_verified_event_without_new_creation(self):
        self.prepare();self.http.timeout=True
        with self.assertRaises(TimeoutError):self.dispatch()
        receipt=self.event()
        self.assertEqual(flow.recover_dispatch_from_receipt(self.db,receipt,self.adapter,self.location,107,Policy)['state'],'bound')
        self.assertEqual(flow.settle_received_payment(self.db,receipt,self.location,108,Policy)['outcome'],'test_settled')
        self.assertEqual(self.http.created,1)

    def test_late_provider_success_retained_for_review_without_stock_consumption(self):
        self.prepare()
        result=self.dispatch(clock=lambda:402)
        self.assertEqual(result['state'],'review');self.assertEqual(result['payment_ref'],'pi_flow1')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(self.sku,)).fetchone()[0],3)

    def test_declined_payment_does_not_settle(self):
        self.prepare('pm_card_chargeDeclined');self.dispatch()
        receipt=self.event(kind='payment_intent.payment_failed')
        self.assertNotEqual(flow.settle_received_payment(self.db,receipt,self.location,107,Policy)['outcome'],'test_settled')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0],0)

    def test_new_card_quote_owner_or_nonpublication_cannot_change_dispatch(self):
        self.prepare()
        with self.assertRaises(flow.PurchaseError):self.prepare('pm_card_chargeDeclined')
        with self.assertRaises(ValueError):self.prepare(buyer=3)
        Policy.published_ids=set()
        with self.assertRaises(flow.PurchaseError):self.dispatch()
        self.assertEqual(self.http.created,0)

    def test_canonical_seller_owner_and_capabilities_must_still_match(self):
        self.prepare();self.http.owner='3'
        with self.assertRaises(payments.PaymentError):self.dispatch()
        self.assertEqual(self.http.created,0)
        self.http.owner='1';self.http.enabled=False
        with self.assertRaises(flow.PurchaseError):self.dispatch()
        self.assertEqual(self.http.created,0)

    def test_unpublication_after_payment_prevents_settlement(self):
        self.prepare();self.dispatch();receipt=self.event();Policy.published_ids=set()
        self.assertEqual(flow.settle_received_payment(self.db,receipt,self.location,107,Policy)['outcome'],'needs_review')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0],0)

    def test_accepted_quote_required_and_live_api_or_real_card_refused(self):
        with self.assertRaises(ValueError):self.prepare('pm_real')
        with self.assertRaises(ValueError):flow.dispatch_payment(self.db,2,self.order,object(),self.location,104,Policy)
        self.assertEqual(self.http.created,0)
        other=checkout.create_order(self.db,'test',2,'shop-a','unaccepted',[(self.sku,1,0)],103,Policy)
        quote=quotes.create_quote(self.db,2,other,self.destination['id'],'unaccepted',self.location,self.services,self.services,103,Policy)
        with self.assertRaises(flow.PurchaseError):flow.prepare_payment(self.db,2,quote,self.location,'pm_card_visa',104,Policy)

    def test_submitted_order_cannot_release_stock_through_local_cancel(self):
        self.prepare()
        with self.assertRaises(checkout.CheckoutError):flow.cancel_unsubmitted_order(self.db,2,self.order,104,Policy)
        self.assertEqual(checkout.get_order(self.db,'test',2,self.order,105,Policy)['state'],'awaiting_payment')

    def test_refund_cannot_be_withdrawn_during_network_submission(self):
        self.settled();request=refunds.request_test_refund(self.db,1,self.order,'refund-race',1000,500,90,110,Policy)
        def hook(value):
            if value['object']=='refund':
                with self.assertRaises(refunds.RefundError):refunds.withdraw_unbound(self.db,1,request,111,Policy)
        self.http.hook=hook;self.http.timeout=True
        with self.assertRaises(TimeoutError):flow.dispatch_refund(self.db,1,request,self.api,111,Policy)
        self.assertEqual(flow.dispatch_refund(self.db,1,request,self.api,112,Policy)['state'],'bound')
        self.assertEqual(self.http.refunded,1)


if __name__=='__main__':unittest.main()
