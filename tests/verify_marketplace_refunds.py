"""Fictional refund plans, real SQLite/encryption, canonical HTTP fixtures only."""
import concurrent.futures
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from cryptography.fernet import Fernet

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_refunds as refunds
import marketplace_settlement as settlement
import marketplace_payments as payments
import marketplace_provider_api as api
import marketplace_ledger as ledger
import marketplace_checkout as checkout
from verify_marketplace_settlement import prepare
from verify_marketplace_checkout import FixturePolicy


def fixture(db,key,waived=False):
    ctx=prepare(db,key,waived=waived)
    settlement.settle_test_receipt(db,ctx['receipt'],ctx['resolver'],105,FixturePolicy)
    refunds.initialize(db)
    return ctx


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.key=Fernet.generate_key();self.ctx=fixture(self.db,self.key)
        self.values={};self.calls=[];self.fetch_hook=lambda:None
        self.reader=payments.StripeTestPaymentReader('platform_fixture',lambda a,p:self.ctx['payment'])
        self.adapter=refunds.StripeTestRefundReader(self.reader,self.fetch)
    def tearDown(self): self.db.close()
    def fetch(self,account,refund):
        self.assertFalse(self.db.in_transaction)
        self.calls.append((account,refund));self.fetch_hook()
        value=self.values[refund]
        if isinstance(value,Exception): raise value
        return value
    def request(self,key='one',items=1000,shipping=500,tax=90,uid=1,now=106):
        return refunds.request_test_refund(self.db,uid,self.ctx['order'],key,items,shipping,tax,now,FixturePolicy)
    def bind(self,request,ref='re_one',status='succeeded',amount=None,now=107):
        refunds.bind_test_refund(self.db,request,ref,now)
        row=self.db.execute('SELECT * FROM marketplace_test_refund_requests WHERE id=?',(request,)).fetchone()
        self.values[ref]=dict(id=ref,object='refund',amount=row['amount_cents'] if amount is None else amount,
            payment_intent='pi_fixture',currency='usd',created=107,status=status,
            metadata={'neonrest_order':self.ctx['order'],'neonrest_refund_request':request})
        return request
    def process(self,request,now=108,**kwargs): return refunds.process_request(self.db,self.adapter,request,now,**kwargs)
    def summary(self,uid=2): return refunds.get_summary(self.db,uid,self.ctx['order'],2000,FixturePolicy)
    def change(self,sql,args=()): self.db.execute(sql,args);self.db.commit()
    def count(self,table): return self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def no_refund_effects(self):
        self.assertEqual(self.count('marketplace_test_refund_applications'),0)
        self.assertEqual(self.count('marketplace_ledger_journals'),1)
        self.assertEqual(self.summary()['refunded_cents'],0)

    def test_full_refund_reverses_original_allocations_without_restock(self):
        request=self.bind(self.request());self.assertEqual(self.process(request)['outcome'],'complete')
        self.assertTrue(all(n==0 for n in ledger.balances(self.db,'test').values()))
        self.assertEqual(self.summary()['state'],'test_refunded')
        self.assertEqual(self.summary()['platform_fee_credit_cents'],60)
        self.assertEqual(self.db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(self.ctx['sku'],)).fetchone()[0],2)
        self.assertEqual(checkout.cancel_order(self.db,'test',2,self.ctx['order'],2000,FixturePolicy),'test_settled')
        self.assertFalse(self.summary()['fulfillment_enabled'])

    def test_duplicate_processing_posts_once_and_does_not_repeat_provider_reads(self):
        request=self.bind(self.request());first=self.process(request)
        self.assertEqual(first,self.process(request,now=10000))
        self.assertEqual(len(self.calls),1);self.assertEqual(self.count('marketplace_test_refund_applications'),1)
        self.assertEqual(self.count('marketplace_ledger_journals'),2)

    def test_partial_refund_preserves_component_allocation(self):
        request=self.bind(self.request(items=500,shipping=250,tax=45));self.process(request)
        self.assertEqual(self.summary()['state'],'test_partially_refunded')
        self.assertEqual((self.summary()['refunded_cents'],self.summary()['platform_fee_credit_cents']),(795,30))
        self.assertEqual(sorted(ledger.balances(self.db,'test').values()),[-720,-45,-30,795])

    def test_shipping_and_tax_refunds_have_no_platform_commission_credit(self):
        request=self.bind(self.request(items=0,shipping=500,tax=90));self.process(request)
        self.assertEqual(self.summary()['platform_fee_credit_cents'],0)
        self.assertEqual(self.summary()['refunded_cents'],590)
        self.assertEqual(ledger.balances(self.db,'test')['qa-fee'],-60)

    def test_cumulative_small_refunds_do_not_round_fee_credit_twice(self):
        a=self.bind(self.request(key='a',items=9,shipping=0,tax=0),ref='re_a')
        b=self.bind(self.request(key='b',items=8,shipping=0,tax=0),ref='re_b')
        self.process(a);self.process(b)
        self.assertEqual(self.summary()['platform_fee_credit_cents'],1)
        c=self.bind(self.request(key='rest',items=983,shipping=500,tax=90),ref='re_rest')
        self.process(c)
        self.assertEqual(self.summary()['platform_fee_credit_cents'],60)
        self.assertTrue(all(n==0 for n in ledger.balances(self.db,'test').values()))

    def test_out_of_order_success_uses_cumulative_applied_items(self):
        a=self.bind(self.request(key='a',items=9,shipping=0,tax=0),ref='re_a')
        b=self.bind(self.request(key='b',items=8,shipping=0,tax=0),ref='re_b')
        self.process(b);self.process(a)
        self.assertEqual(self.summary()['platform_fee_credit_cents'],1)

    def test_owner_exemption_has_no_fee_to_refund(self):
        db=sqlite3.connect(':memory:')
        try:
            ctx=fixture(db,self.key,waived=True)
            request=refunds.request_test_refund(db,1,ctx['order'],'owner',1000,500,90,106,FixturePolicy)
            refunds.bind_test_refund(db,request,'re_owner',107)
            reader=payments.StripeTestPaymentReader('platform_fixture',lambda a,p:ctx['payment'])
            adapter=refunds.StripeTestRefundReader(reader,lambda a,r:dict(id=r,object='refund',amount=1590,currency='usd',created=107,status='succeeded',payment_intent='pi_fixture',metadata={'neonrest_order':ctx['order'],'neonrest_refund_request':request}))
            self.assertEqual(refunds.process_request(db,adapter,request,108)['outcome'],'complete')
            self.assertTrue(all(n==0 for n in ledger.balances(db,'test').values()))
        finally: db.close()

    def test_unbound_pending_and_review_requests_reserve_budget(self):
        request=self.request(items=500,shipping=0,tax=0)
        with self.assertRaises(refunds.RefundError): self.request(key='too-much',items=501,shipping=0,tax=0)
        self.bind(request,status='requires_action');self.assertEqual(self.process(request)['outcome'],'retry')
        with self.assertRaises(refunds.RefundError): self.request(key='still-too-much',items=501,shipping=0,tax=0)
        self.values['re_one']['amount']=999
        self.assertEqual(self.process(request,now=138)['outcome'],'review')
        with self.assertRaises(refunds.RefundError): self.request(key='review-reserved',items=501,shipping=0,tax=0)
        self.no_refund_effects()

    def test_failed_or_canceled_provider_refund_releases_budget_without_posting(self):
        for index,status in enumerate(('failed','canceled')):
            request=self.bind(self.request(key=status),ref='re_'+status,status=status)
            self.assertEqual(self.process(request)['outcome'],'failed')
        self.assertIsInstance(self.request(key='after-failures'),str)
        self.no_refund_effects()

    def test_budget_caps_each_component_not_only_total(self):
        for args in (dict(items=1001,shipping=0,tax=0),dict(items=0,shipping=501,tax=0),dict(items=0,shipping=0,tax=91)):
            with self.subTest(args=args),self.assertRaises(refunds.RefundError): self.request(**args)
        for bad in (True,-1,1.1,'1',100000001):
            with self.subTest(value=bad),self.assertRaises(ValueError): self.request(items=bad)
        with self.assertRaises(refunds.RefundError): self.request(items=0,shipping=0,tax=0)

    def test_idempotency_compares_immutable_order_and_amounts(self):
        first=self.request();self.assertEqual(first,self.request(now=2000))
        with self.assertRaises(refunds.RefundError): self.request(items=999)
        self.assertEqual(self.count('marketplace_test_refund_requests'),1)
        self.assertEqual(self.count('marketplace_test_refund_jobs'),1)

    def test_buyer_other_seller_minor_and_restricted_accounts_cannot_request(self):
        for uid in (2,3,4,5,True):
            with self.subTest(uid=uid),self.assertRaises(ValueError): self.request(uid=uid)
        self.assertEqual(self.count('marketplace_test_refund_requests'),0)

    def test_transfer_revokes_new_owner_access_but_historical_worker_still_records_refund(self):
        request=self.bind(self.request());self.change("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'")
        for uid in (1,3):
            with self.assertRaises(ValueError): self.request(key='after-transfer',uid=uid)
        self.assertEqual(self.process(request)['outcome'],'complete')
        with self.assertRaises(ValueError): self.summary(uid=3)
        with self.assertRaises(ValueError): self.summary(uid=1)
        self.assertEqual(self.summary(uid=2)['state'],'test_refunded')

    def test_parent_payment_must_be_canonical_test_and_match_original_quote(self):
        request=self.bind(self.request());self.ctx['payment']['livemode']=True
        self.assertEqual(self.process(request)['outcome'],'review');self.no_refund_effects()

    def test_mismatched_refund_amount_currency_request_and_payment_require_review(self):
        cases=[dict(amount=1589),dict(currency='eur'),dict(payment_intent='pi_wrong'),dict(id='re_wrong'),
               dict(metadata={'neonrest_order':'wrong','neonrest_refund_request':'wrong'}),dict(amount=True),dict(created=999999),dict(created=105),dict(status='unknown')]
        # Each isolated request consumes a one-cent plan to exercise independent jobs.
        for index,changes in enumerate(cases):
            request=self.bind(self.request(key='bad-'+str(index),items=1,shipping=0,tax=0),ref='re_bad_'+str(index))
            self.values['re_bad_'+str(index)].update(changes)
            self.assertEqual(self.process(request)['outcome'],'review')
        self.no_refund_effects()

    def test_wrong_platform_does_not_fetch_or_claim(self):
        request=self.bind(self.request())
        adapter=refunds.StripeTestRefundReader(payments.StripeTestPaymentReader('wrong_platform',lambda a,p:self.fail('must not read')),lambda a,r:self.fail('must not read'))
        with self.assertRaises(refunds.RefundError): refunds.process_request(self.db,adapter,request,108)
        self.assertEqual(self.db.execute('SELECT attempts FROM marketplace_test_refund_jobs').fetchone()[0],0)

    def test_binding_replay_conflict_and_provider_reference_uniqueness(self):
        request=self.bind(self.request(items=500,shipping=0,tax=0))
        self.assertEqual(refunds.bind_test_refund(self.db,request,'re_one',200),request)
        with self.assertRaises(refunds.RefundError): refunds.bind_test_refund(self.db,request,'re_other',200)
        other=self.request(key='other',items=500,shipping=0,tax=0)
        with self.assertRaises(sqlite3.IntegrityError): refunds.bind_test_refund(self.db,other,'re_one',200)
        for ref in ('../re_bad','re_bad?query=secret','https://wrong','re_'+'x'*151):
            with self.assertRaises(refunds.RefundError): refunds.bind_test_refund(self.db,other,ref,200)

    def test_provider_outage_retries_without_persisting_exception_data(self):
        request=self.bind(self.request());self.values['re_one']=api.ProviderUnavailable('fixture_private_should_not_be_saved')
        self.assertEqual(self.process(request)['outcome'],'retry')
        self.assertNotIn('fixture_private_should_not_be_saved','\n'.join(self.db.iterdump()))
        self.assertEqual(self.process(request,now=109)['outcome'],'retry');self.assertEqual(len(self.calls),1)
        self.bind(request);self.assertEqual(self.process(request,now=138)['outcome'],'complete')

    def test_pending_then_success_is_recovered_by_polling(self):
        request=self.bind(self.request(),status='pending');self.assertEqual(self.process(request)['outcome'],'retry')
        self.no_refund_effects();self.values['re_one']['status']='succeeded'
        self.assertEqual(refunds.run_due(self.db,self.adapter,138)[0]['outcome'],'complete')
        self.assertEqual(refunds.run_due(self.db,self.adapter,2000),[])

    def test_retry_cap_is_durable_and_keeps_refund_budget_reserved(self):
        request=self.bind(self.request(),status='pending');at=108
        for n in range(8):
            result=self.process(request,now=at)
            row=self.db.execute('SELECT * FROM marketplace_test_refund_jobs').fetchone();at=row['next_attempt_at']
        self.assertEqual(result['outcome'],'exhausted');self.assertEqual(row['attempts'],8)
        self.assertEqual(self.process(request,now=99999)['outcome'],'exhausted')
        with self.assertRaises(refunds.RefundError): self.request(key='exhausted-budget')
        self.no_refund_effects()

    def test_crashed_claim_can_be_reclaimed_and_stale_worker_is_fenced(self):
        request=self.bind(self.request());old=refunds.claim(self.db,self.adapter,108,request)
        self.assertIsNone(refunds.claim(self.db,self.adapter,109,request))
        current=refunds.claim(self.db,self.adapter,168,request)
        self.assertEqual(refunds.process_claim(self.db,self.adapter,old,169)['outcome'],'lease_lost')
        self.assertEqual(refunds.process_claim(self.db,self.adapter,current,169)['outcome'],'complete')
        self.assertEqual(len(self.calls),1)

    def test_expired_lease_after_lookup_does_not_post(self):
        request=self.bind(self.request());lease=refunds.claim(self.db,self.adapter,108,request)
        times=iter((108,168))
        self.assertEqual(refunds.process_claim(self.db,self.adapter,lease,108,clock=lambda:next(times))['outcome'],'lease_lost')
        self.no_refund_effects();self.assertEqual(self.process(request,now=168)['outcome'],'complete')

    def test_final_application_failure_rolls_back_observation_journal_and_completion(self):
        request=self.bind(self.request());self.change("CREATE TRIGGER fail_refund BEFORE INSERT ON marketplace_test_refund_applications BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.process(request)
        self.no_refund_effects();self.assertEqual(self.count('marketplace_test_refund_observations'),0)
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_test_refund_jobs').fetchone()[0],'running')
        self.change('DROP TRIGGER fail_refund');self.assertEqual(self.process(request,now=168)['outcome'],'complete')

    def test_journal_seal_failure_rolls_back_refund_effects(self):
        request=self.bind(self.request());self.change("CREATE TRIGGER fail_refund_journal BEFORE UPDATE ON marketplace_ledger_journals BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.process(request)
        self.no_refund_effects();self.assertEqual(self.count('marketplace_test_refund_observations'),0)

    def test_sql_cannot_edit_or_delete_refund_history(self):
        request=self.bind(self.request());self.process(request)
        for table in ('marketplace_test_refund_requests','marketplace_test_refund_bindings','marketplace_test_refund_observations','marketplace_test_refund_applications','marketplace_test_refund_jobs'):
            with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM '+table)
            self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE marketplace_test_refund_requests SET item_cents=1')
        self.db.rollback()

    def test_backup_restore_and_repeat_migration_keep_completed_and_pending_jobs(self):
        request=self.bind(self.request(items=500,shipping=0,tax=0));self.process(request)
        other=self.bind(self.request(key='other',items=500,shipping=500,tax=90),ref='re_other',status='pending')
        lease=refunds.claim(self.db,self.adapter,108,other);refunds.initialize(self.db)
        restored=sqlite3.connect(':memory:');self.db.backup(restored);restored.row_factory=sqlite3.Row;restored.execute('PRAGMA foreign_keys=ON')
        try:
            self.assertEqual(refunds.get_summary(restored,2,self.ctx['order'],2000,FixturePolicy)['refunded_cents'],500)
            self.assertEqual(restored.execute('SELECT lease_token FROM marketplace_test_refund_jobs WHERE request_id=?',(other,)).fetchone()[0],lease.token)
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: restored.close()

    def test_unrelated_user_cannot_read_refund_summary(self):
        with self.assertRaises(ValueError): self.summary(uid=3)
        result=str(self.summary())
        for text in ('acct_fixture','pi_fixture','re_one','FixturePrivateRecipient'):
            self.assertNotIn(text,result)

    def test_batch_bounds_and_clock_checks(self):
        request=self.bind(self.request())
        for limit in (0,101,True):
            with self.assertRaises(refunds.RefundError): refunds.run_due(self.db,self.adapter,108,limit=limit)
        with self.assertRaises(refunds.RefundError): refunds.run_due(self.db,self.adapter,108,clock=lambda:107)
        with self.assertRaises(ValueError): refunds.run_due(self.db,self.adapter,True)

    def test_owner_can_withdraw_unbound_plan_and_release_budget(self):
        request=self.request()
        self.assertEqual(refunds.withdraw_unbound(self.db,1,request,107,FixturePolicy),request)
        self.assertEqual(refunds.withdraw_unbound(self.db,1,request,108,FixturePolicy),request)
        self.assertEqual(self.count('marketplace_test_refund_withdrawals'),1)
        self.assertIsInstance(self.request(key='replacement',now=108),str)
        with self.assertRaises(refunds.RefundError): self.bind(request)
        self.no_refund_effects()

    def test_bound_refund_cannot_be_withdrawn_to_release_budget(self):
        request=self.bind(self.request(),status='pending')
        with self.assertRaises(refunds.RefundError): refunds.withdraw_unbound(self.db,1,request,108,FixturePolicy)
        with self.assertRaises(refunds.RefundError): self.request(key='replacement')
        self.no_refund_effects()

    def test_unrelated_user_cannot_withdraw_refund_plan(self):
        request=self.request()
        for uid in (2,3,True):
            with self.assertRaises(ValueError): refunds.withdraw_unbound(self.db,uid,request,107,FixturePolicy)
        self.assertEqual(self.count('marketplace_test_refund_withdrawals'),0)

    def test_final_job_completion_failure_rolls_back_journal_and_application(self):
        request=self.bind(self.request())
        self.change("CREATE TRIGGER fail_job_finish BEFORE UPDATE ON marketplace_test_refund_jobs WHEN NEW.state='complete' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.process(request)
        self.no_refund_effects();self.assertEqual(self.count('marketplace_test_refund_observations'),0)
        self.change('DROP TRIGGER fail_job_finish')
        self.assertEqual(self.process(request,now=168)['outcome'],'complete')

    def test_last_crash_lease_is_exhausted_without_releasing_budget(self):
        request=self.bind(self.request());at=108
        for index in range(8):
            lease=refunds.claim(self.db,self.adapter,at,request);self.assertIsNotNone(lease);at=lease.until
        self.assertIsNone(refunds.claim(self.db,self.adapter,at,request))
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_test_refund_jobs').fetchone()[0],'exhausted')
        with self.assertRaises(refunds.RefundError): self.request(key='still-reserved')
        self.no_refund_effects()

    def test_stale_response_cannot_overwrite_replacement_worker(self):
        request=self.bind(self.request());old=refunds.claim(self.db,self.adapter,108,request)
        def replace_worker():
            self.fetch_hook=lambda:None
            current=refunds.claim(self.db,self.adapter,168,request)
            self.assertEqual(refunds.process_claim(self.db,self.adapter,current,169)['outcome'],'complete')
        self.fetch_hook=replace_worker
        self.assertEqual(refunds.process_claim(self.db,self.adapter,old,108)['outcome'],'lease_lost')
        self.assertEqual(self.count('marketplace_test_refund_applications'),1)

    def test_canonical_parent_wrong_quote_or_amount_is_not_a_refund_proof(self):
        request=self.bind(self.request())
        self.ctx['payment']['metadata']['neonrest_quote']='wrong_quote'
        self.assertEqual(self.process(request)['outcome'],'review');self.no_refund_effects()

    def test_scope_bound_native_http_client_reaches_atomic_test_refund(self):
        db=sqlite3.connect(':memory:')
        try:
            ctx=prepare(db,self.key,platform='acct_platform')
            settlement.settle_test_receipt(db,ctx['receipt'],ctx['resolver'],105,FixturePolicy);refunds.initialize(db)
            request=refunds.request_test_refund(db,1,ctx['order'],'http',1000,500,90,106,FixturePolicy)
            refunds.bind_test_refund(db,request,'re_http',107);calls=[]
            class HTTP:
                def request(inner,method,url,headers,body=None):
                    self.assertFalse(db.in_transaction);calls.append((method,url,headers))
                    self.assertTrue(api.TestProviderHTTP.permitted(method,url))
                    if url.endswith('/v1/account'): return dict(id='acct_platform',object='account')
                    self.assertEqual(headers['Stripe-Account'],'acct_fixture')
                    if '/payment_intents/' in url: return ctx['payment']
                    return dict(id='re_http',object='refund',amount=1590,currency='usd',created=107,status='succeeded',payment_intent='pi_fixture',metadata={'neonrest_order':ctx['order'],'neonrest_refund_request':request})
            client=api.StripeTestAPI('acct_platform','sk_test_fixture_not_real',http=HTTP())
            adapter=refunds.StripeTestRefundReader(payments.StripeTestPaymentReader(client.scope.platform,client.fetch_payment),client.fetch_refund)
            self.assertEqual(refunds.process_request(db,adapter,request,108)['outcome'],'complete')
            self.assertTrue(all(call[0]=='GET' for call in calls));self.assertEqual(len(calls),4)
            self.assertEqual(refunds.get_summary(db,2,ctx['order'],2000,FixturePolicy)['state'],'test_refunded')
        finally: db.close()

    def test_concurrent_connections_cannot_reserve_more_than_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'qa.sqlite');db=sqlite3.connect(path);ctx=fixture(db,self.key);db.close()
            def work(index):
                conn=sqlite3.connect(path,timeout=5);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
                try:
                    return refunds.request_test_refund(conn,1,ctx['order'],'request-'+str(index),600,0,0,106,FixturePolicy)
                except refunds.RefundError: return None
                finally: conn.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(work,range(2)))
            self.assertEqual(sum(r is not None for r in results),1)

    def test_concurrent_claims_only_one_worker_posts(self):
        request=self.bind(self.request())
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'qa.sqlite');db=sqlite3.connect(path);self.db.backup(db);db.close()
            def work(_):
                conn=sqlite3.connect(path,timeout=5);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
                try:
                    reader=payments.StripeTestPaymentReader('platform_fixture',lambda a,p:self.ctx['payment'])
                    adapter=refunds.StripeTestRefundReader(reader,lambda a,r:self.values[r])
                    return refunds.process_request(conn,adapter,request,108)
                finally: conn.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(work,range(4)))
            conn=sqlite3.connect(path)
            try:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM marketplace_test_refund_applications').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],2)
            finally: conn.close()


class RefundTransportTests(unittest.TestCase):
    def client(self):
        self.calls=[]
        class HTTP:
            def request(inner,method,url,headers,body=None):
                self.calls.append((method,url,headers,body))
                if url.endswith('/v1/account'): return dict(id='acct_platform',object='account')
                if '/refunds/' in url: return dict(id='re_fixture',object='refund',payment_intent='pi_fixture',status='succeeded',amount=100,currency='usd',created=100,metadata={})
                raise AssertionError('unexpected operation')
        return api.StripeTestAPI('acct_platform','sk_test_fixture_not_real',http=HTTP())

    def test_canonical_refund_read_uses_test_key_platform_and_connected_scope(self):
        result=self.client().fetch_refund('acct_seller','re_fixture')
        self.assertEqual(result['amount'],100)
        self.assertEqual(self.calls[1][:2],('GET','https://api.stripe.com/v1/refunds/re_fixture'))
        self.assertEqual(self.calls[1][2]['Stripe-Account'],'acct_seller')
        self.assertEqual(self.calls[1][2]['Stripe-Version'],api.StripeTestAPI.VERSION)

    def test_refund_reads_do_not_enable_creation_or_transfer_operations(self):
        self.assertTrue(api.TestProviderHTTP.permitted('GET','https://api.stripe.com/v1/refunds/re_fixture'))
        for method,url in [('POST','https://api.stripe.com/v1/refunds'),('POST','https://api.stripe.com/v1/refunds/re_fixture/cancel'),('GET','https://api.stripe.com/v1/refunds/re_fixture?expand=payment_intent'),('POST','https://api.stripe.com/v1/transfers/tr_one/reversals')]:
            self.assertFalse(api.TestProviderHTTP.permitted(method,url))
        client=self.client()
        for ref in ('re_fixture?redirect=wrong','../re_fixture','https://wrong','re_'+'x'*151):
            with self.assertRaises(ValueError): client.fetch_refund('acct_seller',ref)
        self.assertEqual(self.calls,[])


if __name__=='__main__': unittest.main()
