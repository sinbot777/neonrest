"""Signed Stripe fixtures and synthetic provider resolvers, no API calls."""
import concurrent.futures
from dataclasses import replace
import hashlib
import hmac
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_payments as payments
import marketplace_checkout as checkout
import marketplace_inventory as inventory
from verify_marketplace_checkout import fixture,FixturePolicy

SECRET=b'whsec_fixture_only_never_a_real_secret'


class OnboardingFixture:
    """Authenticated resolver boundary; actual provider transport is future work."""
    def __init__(self,scope,owner=1,account='acct_fixture'):
        self.scope=scope;self.owner=owner;self.account=account;self.charges=True;self.payouts=True
        self.hook=lambda: None
    def resolve_onboarding(self,request):
        self.hook()
        return payments.AccountObservation(self.scope,request,self.account,self.owner,self.charges,self.payouts)
    def resolve_account(self,account):
        return self.resolve_onboarding('refresh')


def setup_payment(db):
    sku=fixture(db)
    payments.initialize(db)
    scope=payments.Scope('stripe','platform_fixture')
    resolver=OnboardingFixture(scope)
    request=payments.begin_onboarding(db,1,'shop-a',scope,'owner-request',100,FixturePolicy)
    account=payments.complete_onboarding(db,1,request,resolver,100,FixturePolicy)
    order=checkout.create_order(db,'test',2,'shop-a','checkout',[(sku,1,0)],100,FixturePolicy)
    attempt=payments.track_test_payment(db,2,order,account,'pi_fixture',100,FixturePolicy)
    return dict(sku=sku,scope=scope,resolver=resolver,request=request,account=account,order=order,attempt=attempt)


def signed_event(event_id='evt_one',account='acct_fixture',kind='payment_intent.succeeded',payment='pi_fixture',now=101,created=100,**fields):
    event=dict(id=event_id,object='event',account=account,type=kind,created=created,livemode=False,data={'object':{'id':payment}})
    event.update(fields)
    raw=json.dumps(event,separators=(',',':')).encode()
    return raw,sign(raw,now)


def sign(raw,timestamp,secret=SECRET):
    digest=hmac.new(secret,str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return f't={timestamp},v1={digest}'


def canonical(order,**changes):
    value=dict(id='pi_fixture',object='payment_intent',livemode=False,status='succeeded',
        amount=1000,amount_received=1000,currency='usd',metadata={'neonrest_order':order})
    value.update(changes)
    return value


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.ctx=setup_payment(self.db)
        self.payment=canonical(self.ctx['order'])
        self.calls=[]
        def fetch(account,payment):
            self.calls.append((account,payment))
            return self.payment
        self.adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],fetch)
    def tearDown(self): self.db.close()
    def count(self,table): return self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def receive(self,**kwargs):
        now=kwargs.get('now',101)
        raw,sig=signed_event(**kwargs)
        return payments.receive_stripe(self.db,self.adapter,raw,sig,now,FixturePolicy)
    def update(self,sql,args=()): self.db.execute(sql,args);self.db.commit()
    def observation(self): return self.db.execute('SELECT observed_status FROM marketplace_payment_test_attempts').fetchone()[0]

    def test_signature_verified_event_is_observed_but_never_paid(self):
        result=self.receive()
        self.assertEqual(result['outcome'],'observed_test')
        self.assertEqual(self.calls,[('acct_fixture','pi_fixture')])
        self.assertEqual(self.observation(),'succeeded')
        order=checkout.get_order(self.db,'test',2,self.ctx['order'],101,FixturePolicy)
        self.assertEqual(order['state'],'awaiting_payment')
        self.assertFalse(order['snapshot']['payment_enabled'])
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.ctx['sku'],101),2)
        self.assertEqual(self.count('marketplace_payment_events'),1)

    def test_duplicate_receipt_is_unique_and_transient_delivery_fields_can_differ(self):
        first=self.receive()
        second=self.receive(now=102,pending_webhooks=1)
        self.assertEqual(first['receipt_id'],second['receipt_id'])
        self.assertEqual(self.count('marketplace_payment_events'),1)
        with self.assertRaises(payments.PaymentError): self.receive(payment='pi_other')

    def test_forgery_changed_body_missing_or_old_signatures_leave_no_receipt(self):
        raw,sig=signed_event()
        bad=[(raw,sig.replace('v1=','v1=f')),(raw+b' ',sig),(raw,''),(raw,sign(raw,101,b'wrong_secret_long_enough')),(raw,sign(raw,1)),(raw,sign(raw,1000)),(raw,sig+',t=101')]
        for body,header in bad:
            with self.subTest(header=header[:15]),self.assertRaises(payments.PaymentError):
                payments.receive_stripe(self.db,self.adapter,body,header,400,FixturePolicy)
        self.assertEqual(self.count('marketplace_payment_events'),0)

    def test_signature_rotation_and_freshly_signed_old_event(self):
        other=b'whsec_old_fixture_secret_only'
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET,other],lambda a,p:self.payment)
        raw,_=signed_event(created=1)
        self.assertEqual(adapter.verify(raw,sign(raw,101,other),101)['created'],1)
        self.assertEqual(adapter.verify(raw,sign(raw,101)+',v1='+'0'*64,101)['id'],'evt_one')

    def test_live_mode_json_duplicates_invalid_constants_and_oversized_body_rejected(self):
        raw,_=signed_event(livemode=True)
        cases=[raw,b'{"id":"evt","id":"other"}',b'{"value":NaN}',b'[]',b'x'*1_048_577]
        for body in cases:
            with self.subTest(size=len(body)),self.assertRaises(payments.PaymentError): self.adapter.verify(body,sign(body,101),101)

    def test_account_platform_unknown_payment_and_unsupported_events_do_not_fetch(self):
        self.assertEqual(self.receive(account='acct_other')['reason'],'unbound_payment')
        self.assertEqual(self.receive(event_id='evt_unknown',payment='pi_other')['reason'],'unbound_payment')
        self.assertEqual(self.receive(event_id='evt_ignored',kind='charge.updated')['outcome'],'ignored')
        other=payments.StripeTestWebhookAdapter('other_platform',[SECRET],lambda a,p:self.fail('wrong platform must not fetch'))
        raw,sig=signed_event(event_id='evt_other_platform')
        self.assertEqual(payments.receive_stripe(self.db,other,raw,sig,101,FixturePolicy)['reason'],'unbound_payment')
        self.assertEqual(self.calls,[])

    def test_amount_currency_order_and_canonical_mode_mismatch_never_observed(self):
        variants=[dict(amount_received=999),dict(currency='eur'),dict(metadata={'neonrest_order':'wrong'}),dict(livemode=True),dict(id='pi_other'),dict(amount_received=True)]
        for i,changes in enumerate(variants):
            self.payment=canonical(self.ctx['order'],**changes)
            result=self.receive(event_id='evt_bad_'+str(i))
            self.assertEqual(result['outcome'],'needs_review')
        self.assertEqual(self.observation(),'tracking')

    def test_lookup_outage_persists_retry_without_sensitive_error_and_retry_succeeds(self):
        def fail(a,p): raise RuntimeError('SECRET PII must never persist')
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],fail)
        raw,sig=signed_event()
        result=payments.receive_stripe(self.db,adapter,raw,sig,101,FixturePolicy)
        self.assertEqual(result['outcome'],'retry')
        self.assertEqual(self.receive(now=102)['outcome'],'observed_test')
        self.assertNotIn('SECRET PII',str(tuple(self.db.execute('SELECT * FROM marketplace_payment_events').fetchone())))
        self.assertEqual(self.count('marketplace_payment_events'),1)

    def test_out_of_order_event_uses_canonical_state_not_event_label(self):
        self.assertEqual(self.receive(kind='payment_intent.payment_failed')['outcome'],'observed_test')
        self.assertEqual(self.observation(),'succeeded')
        self.payment=canonical(self.ctx['order'],status='requires_payment_method')
        result=self.receive(event_id='evt_later')
        self.assertEqual(result['reason'],'terminal_observation_conflict')
        self.assertEqual(self.observation(),'succeeded')

    def test_failure_then_success_is_not_permanently_failed(self):
        self.payment=canonical(self.ctx['order'],status='requires_payment_method')
        self.receive(kind='payment_intent.payment_failed')
        self.assertEqual(self.observation(),'failed')
        self.payment=canonical(self.ctx['order'])
        self.receive(event_id='evt_success')
        self.assertEqual(self.observation(),'succeeded')

    def test_expired_or_canceled_order_needs_review(self):
        checkout.cancel_order(self.db,'test',2,self.ctx['order'],101,FixturePolicy)
        self.assertEqual(self.receive()['reason'],'reservation_no_longer_active')
        self.assertEqual(self.observation(),'tracking')

    def test_late_success_after_expiry_does_not_touch_stock_or_order(self):
        result=self.receive(now=1000)
        self.assertEqual(result['reason'],'reservation_no_longer_active')
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.ctx['sku'],1000),3)

    def test_permissions_rechecked_after_provider_lookup(self):
        def fetch(a,p):
            self.update("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'")
            return self.payment
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],fetch)
        raw,sig=signed_event()
        self.assertEqual(payments.receive_stripe(self.db,adapter,raw,sig,101,FixturePolicy)['reason'],'seller_or_buyer_unavailable')

    def test_account_capability_refresh_and_stale_or_foreign_observations(self):
        resolver=self.ctx['resolver'];resolver.charges=False
        payments.refresh_account(self.db,self.ctx['account'],resolver,102)
        self.assertEqual(self.receive(now=103)['reason'],'seller_or_buyer_unavailable')
        resolver.charges=True
        with self.assertRaises(payments.PaymentError): payments.refresh_account(self.db,self.ctx['account'],resolver,101)
        resolver.owner=3
        with self.assertRaises(payments.PaymentError): payments.refresh_account(self.db,self.ctx['account'],resolver,104)

    def test_attempt_replay_is_bound_and_live_scope_is_refused(self):
        self.assertEqual(payments.track_test_payment(self.db,2,self.ctx['order'],self.ctx['account'],'pi_fixture',101,FixturePolicy),self.ctx['attempt'])
        with self.assertRaises(payments.PaymentError): payments.track_test_payment(self.db,2,self.ctx['order'],self.ctx['account'],'pi_other',101,FixturePolicy)
        with self.assertRaises(payments.PaymentError): payments.track_test_payment(self.db,3,self.ctx['order'],self.ctx['account'],'pi_other',101,FixturePolicy)
        with self.assertRaises(payments.PaymentError): payments.Scope('stripe','platform','live')

    def test_account_order_expectation_receipt_identities_and_modes_are_immutable(self):
        self.receive()
        for sql in ["UPDATE marketplace_payment_accounts SET owner_id=3", "UPDATE marketplace_payment_accounts SET environment='live'", "UPDATE marketplace_payment_shop_links SET owner_id=3", "UPDATE marketplace_payment_test_attempts SET expected_amount_cents=1", "UPDATE marketplace_payment_events SET account_ref='acct_other'"]:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()

    def test_repeated_initialization_preserves_receipts_accounts_and_attempts(self):
        self.receive()
        payments.initialize(self.db)
        self.assertEqual(self.count('marketplace_payment_events'),1)
        self.assertEqual(self.count('marketplace_payment_accounts'),1)
        self.assertEqual(self.observation(),'succeeded')

    def test_bad_server_time_cannot_overflow_database_or_bypass_signature_check(self):
        raw,sig=signed_event()
        for now in [True,-1,2**63,1.5]:
            with self.subTest(now=now),self.assertRaises(inventory.InventoryError):
                payments.receive_stripe(self.db,self.adapter,raw,sig,now,FixturePolicy)
        self.assertEqual(self.count('marketplace_payment_events'),0)

    def test_customer_payload_secret_and_signature_are_not_stored(self):
        raw,sig=signed_event(customer_email='PRIVATE-EMAIL',client_secret='PRIVATE-CLIENT-SECRET')
        payments.receive_stripe(self.db,self.adapter,raw,sig,101,FixturePolicy)
        saved=str(tuple(self.db.execute('SELECT * FROM marketplace_payment_events').fetchone()))
        for secret in ['PRIVATE-EMAIL','PRIVATE-CLIENT-SECRET',SECRET.decode(),sig]: self.assertNotIn(secret,saved)


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');fixture(self.db);payments.initialize(self.db)
        self.scope=payments.Scope('stripe','platform_fixture');self.adapter=OnboardingFixture(self.scope)
    def tearDown(self): self.db.close()
    def begin(self,key='onboard',owner=1,shop='shop-a',scope=None):
        return payments.begin_onboarding(self.db,owner,shop,scope or self.scope,key,100,FixturePolicy)
    def complete(self,request,now=101): return payments.complete_onboarding(self.db,1,request,self.adapter,now,FixturePolicy)

    def test_owner_only_request_and_idempotency_context(self):
        request=self.begin()
        self.assertEqual(request,self.begin())
        with self.assertRaises(payments.PaymentError): self.begin(owner=2)
        with self.assertRaises(payments.PaymentError): self.begin(scope=payments.Scope('paypal','platform_fixture'))

    def test_wrong_grant_owner_scope_and_expiry_cannot_link_account(self):
        request=self.begin()
        self.adapter.owner=3
        with self.assertRaises(payments.PaymentError): self.complete(request)
        self.adapter.owner=True
        with self.assertRaises(payments.PaymentError): self.complete(request)
        self.adapter.owner=1;self.adapter.scope=payments.Scope('stripe','other_platform')
        with self.assertRaises(payments.PaymentError): self.complete(request)
        self.adapter.scope=self.scope
        with self.assertRaises(payments.PaymentError): self.complete(request,now=1000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_accounts').fetchone()[0],0)

    def test_provider_call_is_outside_write_lock_and_owner_is_rechecked(self):
        request=self.begin()
        def hook():
            self.assertFalse(self.db.in_transaction)
            self.db.execute("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'");self.db.commit()
        self.adapter.hook=hook
        with self.assertRaises(payments.PaymentError): self.complete(request)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_accounts').fetchone()[0],0)

    def test_completion_is_idempotent_and_relink_is_not_implicit(self):
        request=self.begin();account=self.complete(request)
        self.assertEqual(account,self.complete(request))
        another=self.begin(key='another');self.adapter.account='acct_other'
        with self.assertRaises(payments.PaymentError): self.complete(another)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_accounts').fetchone()[0],1)

    def test_multiple_shops_same_owner_can_share_one_provider_account(self):
        account=self.complete(self.begin())
        self.db.execute("UPDATE seller_shops SET owner_id=1 WHERE page_id='shop-b'");self.db.commit()
        request=self.begin(key='second-shop',shop='shop-b')
        self.assertEqual(account,self.complete(request))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_shop_links').fetchone()[0],2)

    def test_different_owner_cannot_claim_an_existing_merchant_account(self):
        self.complete(self.begin())
        request=self.begin(owner=3,shop='shop-b')
        self.adapter.owner=3
        with self.assertRaises(payments.PaymentError): payments.complete_onboarding(self.db,3,request,self.adapter,101,FixturePolicy)

    def test_new_shop_binding_carries_current_account_restrictions(self):
        account=self.complete(self.begin())
        self.db.execute("UPDATE seller_shops SET owner_id=1 WHERE page_id='shop-b'");self.db.commit()
        request=self.begin(key='second-shop',shop='shop-b')
        self.adapter.charges=False
        self.complete(request,now=102)
        self.assertEqual(self.db.execute('SELECT charges_enabled FROM marketplace_payment_accounts WHERE id=?',(account,)).fetchone()[0],0)

    def test_sql_cannot_reassign_or_complete_an_unbound_onboarding(self):
        self.begin()
        for sql in ["UPDATE marketplace_payment_onboarding SET owner_id=3", "UPDATE marketplace_payment_onboarding SET state='completed',account_id='missing'"]:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()


class PaymentConcurrencyTests(unittest.TestCase):
    def test_duplicate_webhook_from_two_connections_retains_one_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'payments.db')
            db=sqlite3.connect(path);context=setup_payment(db);db.close()
            payment=canonical(context['order'])
            raw,sig=signed_event()
            def receive(_):
                db=sqlite3.connect(path,timeout=5);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
                adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:payment)
                try: return payments.receive_stripe(db,adapter,raw,sig,101,FixturePolicy)
                finally: db.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(receive,range(2)))
            self.assertEqual(results[0]['receipt_id'],results[1]['receipt_id'])
            db=sqlite3.connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_payment_events').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT state FROM marketplace_checkout_orders').fetchone()[0],'awaiting_payment')
            db.close()


if __name__=='__main__': unittest.main()
