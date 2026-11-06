"""Durable recovery tests with signed fixtures, fault injection and real SQLite."""
import concurrent.futures
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_payment_jobs as jobs
import marketplace_payments as payments
from verify_marketplace_checkout import FixturePolicy
from verify_marketplace_payments import setup_payment,canonical,signed_event,SECRET


class Crash(BaseException):
    pass


class JobTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.ctx=setup_payment(self.db)
        self.payment=canonical(self.ctx['order']);self.calls=0
        self.fail=False;self.hook=lambda:None
        def fetch(account,payment):
            self.assertFalse(self.db.in_transaction)
            self.calls+=1;self.hook()
            if self.fail: raise RuntimeError('PRIVATE_PROVIDER_ERROR_MUST_NOT_PERSIST')
            return self.payment
        self.adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],fetch)
    def tearDown(self): self.db.close()
    def deliver(self,now=101):
        raw,sig=signed_event(now=now)
        return payments.receive_stripe(self.db,self.adapter,raw,sig,now,FixturePolicy)
    def stage(self):
        # Crash after the verified receipt + job commit, before its first claim.
        with patch.object(jobs,'process_delivery',side_effect=Crash):
            with self.assertRaises(Crash): self.deliver()
        return self.db.execute('SELECT id FROM marketplace_payment_events').fetchone()[0]
    def job(self): return self.db.execute('SELECT * FROM marketplace_payment_jobs').fetchone()
    def tick(self,now,limit=25): return jobs.run_due(self.db,self.adapter,now,limit,FixturePolicy,lambda:now)
    def status(self): return self.db.execute('SELECT observed_status FROM marketplace_payment_test_attempts').fetchone()[0]

    def test_receipt_and_job_commit_together_and_recover_without_raw_signature(self):
        receipt=self.stage()
        self.assertEqual(self.job()['state'],'ready')
        self.assertEqual(self.job()['attempts'],0)
        with patch.object(self.adapter,'verify',side_effect=AssertionError('stored receipts must not be re-signed/reverified')):
            result=self.tick(500)
        self.assertEqual(result['processed'],1)
        self.assertEqual(result['results'][0]['receipt_id'],receipt)
        self.assertEqual(self.status(),'succeeded')
        self.assertEqual(self.job()['state'],'complete')

    def test_outage_backoff_and_recovery_need_no_provider_redelivery(self):
        self.fail=True;self.deliver()
        self.assertEqual(self.job()['next_attempt_at'],131)
        self.assertEqual(self.tick(130)['processed'],0)
        self.fail=False
        self.assertEqual(self.tick(131)['results'][0]['outcome'],'observed_test')
        self.assertEqual(self.job()['attempts'],2)
        self.assertNotIn('PRIVATE_PROVIDER_ERROR',str(tuple(self.job())))

    def test_backoff_is_exponential_bounded_and_exhaustion_never_resets(self):
        self.fail=True;self.deliver()
        now=101
        for attempt in range(1,jobs.MAX_ATTEMPTS):
            expected=min(30*2**(attempt-1),jobs.MAX_BACKOFF)
            self.assertEqual(self.job()['next_attempt_at']-now,expected)
            now=self.job()['next_attempt_at'];self.tick(now)
        self.assertEqual(self.job()['state'],'exhausted')
        self.assertEqual(self.job()['attempts'],jobs.MAX_ATTEMPTS)
        before=self.calls
        self.assertEqual(self.deliver(now=now+1)['reason'],'retry_exhausted')
        self.assertEqual(self.calls,before)
        self.assertEqual(self.tick(now+1000)['processed'],0)

    def test_fresh_verified_redelivery_can_expedite_backoff_without_duplicate_job(self):
        self.fail=True;first=self.deliver()
        self.fail=False;second=self.deliver(now=102)
        self.assertEqual(first['receipt_id'],second['receipt_id'])
        self.assertEqual(second['outcome'],'observed_test')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_jobs').fetchone()[0],1)

    def test_crash_during_lookup_recovers_only_after_lease_expiry(self):
        def crash(): raise Crash()
        self.hook=crash
        with self.assertRaises(Crash): self.deliver()
        self.assertEqual(self.job()['state'],'running')
        self.hook=lambda:None
        self.assertEqual(self.tick(160)['processed'],0)
        self.assertEqual(self.tick(161)['processed'],1)
        self.assertEqual(self.job()['attempts'],2)

    def test_slow_expired_worker_cannot_commit_even_without_a_replacement(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,102,receipt)
        clock=[102]
        self.hook=lambda:clock.__setitem__(0,200)
        result=jobs.process_claim(self.db,self.adapter,lease,102,FixturePolicy,lambda:clock[0])
        self.assertEqual(result['reason'],'lease_lost')
        self.assertEqual(self.status(),'tracking')
        self.hook=lambda:None
        self.assertEqual(self.tick(200)['processed'],1)
        self.assertEqual(self.status(),'succeeded')

    def test_old_worker_is_fenced_after_another_worker_reclaims_the_job(self):
        receipt=self.stage();old=jobs.claim(self.db,self.adapter,102,receipt)
        clock=[102];reentered=[False]
        def fetch(account,payment):
            if not reentered[0]:
                reentered[0]=True;clock[0]=162
                fresh=jobs.claim(self.db,self.adapter,162,receipt)
                self.assertIsNotNone(fresh)
                jobs.process_claim(self.db,self.adapter,fresh,162,FixturePolicy,lambda:162)
                return canonical(self.ctx['order'],status='requires_payment_method')
            return self.payment
        self.adapter._fetch=fetch
        result=jobs.process_claim(self.db,self.adapter,old,102,FixturePolicy,lambda:clock[0])
        self.assertEqual(result['reason'],'lease_lost')
        self.assertEqual(self.status(),'succeeded')
        self.assertEqual(self.job()['state'],'complete')
        self.assertEqual(self.db.execute('SELECT checked_at FROM marketplace_payment_events').fetchone()[0],162)

    def test_expiry_during_provider_lookup_is_checked_at_completion_time(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,990,receipt)
        clock=[990];self.hook=lambda:clock.__setitem__(0,1001)
        result=jobs.process_claim(self.db,self.adapter,lease,990,FixturePolicy,lambda:clock[0])
        self.assertEqual(result['reason'],'reservation_no_longer_active')
        self.assertEqual(self.job()['state'],'review')
        self.assertEqual(self.status(),'tracking')

    def test_review_is_not_automatically_retried_but_fresh_delivery_can_reconcile(self):
        self.payment=canonical(self.ctx['order'],amount_received=999)
        self.assertEqual(self.deliver()['outcome'],'needs_review')
        self.assertEqual(self.tick(200)['processed'],0)
        self.payment=canonical(self.ctx['order'])
        self.assertEqual(self.deliver(now=201)['outcome'],'observed_test')

    def test_terminal_success_redelivery_is_cached_without_another_lookup(self):
        self.deliver();before=self.calls
        self.assertEqual(self.deliver(now=102)['outcome'],'observed_test')
        self.assertEqual(self.calls,before)
        self.assertEqual(self.job()['attempts'],1)

    def test_nonterminal_observation_can_refresh_on_verified_redelivery(self):
        self.payment=canonical(self.ctx['order'],status='requires_payment_method')
        self.deliver();self.assertEqual(self.status(),'failed')
        self.payment=canonical(self.ctx['order'])
        self.deliver(now=102)
        self.assertEqual(self.status(),'succeeded')

    def test_job_finalize_failure_rolls_back_receipt_and_observation_together(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,102,receipt)
        self.db.execute("CREATE TRIGGER fail_finish BEFORE UPDATE ON marketplace_payment_jobs WHEN NEW.state='complete' BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError): jobs.process_claim(self.db,self.adapter,lease,102,FixturePolicy,lambda:102)
        self.assertEqual(self.status(),'tracking')
        self.assertEqual(self.db.execute('SELECT outcome FROM marketplace_payment_events').fetchone()[0],'received')
        self.assertEqual(self.job()['state'],'running')
        self.db.execute('DROP TRIGGER fail_finish')
        self.assertEqual(self.tick(162)['results'][0]['outcome'],'observed_test')

    def test_wrong_scope_or_invalid_limits_cannot_claim_receipt(self):
        receipt=self.stage()
        other=payments.StripeTestWebhookAdapter('another_platform',[SECRET],lambda a,p:self.fail('must not call'))
        with self.assertRaises(jobs.JobError): jobs.claim(self.db,other,102,receipt)
        for limit in [True,0,101]:
            with self.assertRaises(jobs.JobError): self.tick(102,limit)
        self.assertEqual(self.job()['attempts'],0)

    def test_repeat_migration_does_not_reset_leases_or_attempts(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,102,receipt)
        payments.initialize(self.db)
        self.assertEqual(self.job()['lease_token'],lease.token)
        self.assertEqual(self.job()['attempts'],1)
        self.assertEqual(self.job()['state'],'running')

    def test_legacy_receipts_are_backfilled_without_claiming_new_money(self):
        self.fail=True;self.deliver()
        self.db.execute('DROP TABLE marketplace_payment_jobs')
        payments.initialize(self.db)
        self.assertEqual(self.job()['state'],'retry')
        self.fail=False;self.tick(200)
        self.assertEqual(self.status(),'succeeded')
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_checkout_orders').fetchone()[0],'awaiting_payment')

    def test_backup_restore_preserves_crash_lease_then_recovers(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,102,receipt)
        restored=sqlite3.connect(':memory:');restored.row_factory=sqlite3.Row
        try:
            self.db.backup(restored);payments.initialize(restored)
            self.assertEqual(restored.execute('SELECT lease_token FROM marketplace_payment_jobs').fetchone()[0],lease.token)
            adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:self.payment)
            result=jobs.run_due(restored,adapter,162,policy=FixturePolicy,clock=lambda:162)
            self.assertEqual(result['results'][0]['outcome'],'observed_test')
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: restored.close()

    def test_exhausted_crash_is_reaped_and_summary_contains_no_lease_details(self):
        receipt=self.stage()
        for attempt in range(jobs.MAX_ATTEMPTS):
            now=102+attempt*jobs.LEASE_SECONDS
            lease=jobs.claim(self.db,self.adapter,now,receipt)
            self.assertIsNotNone(lease)
        end=lease.until
        self.assertEqual(jobs.reap_exhausted(self.db,self.adapter,end),1)
        summary=jobs.summary(self.db,self.adapter,end)
        self.assertEqual(summary['states'],{'exhausted':1})
        self.assertNotIn(lease.token,json.dumps(summary))
        self.assertNotIn('pi_fixture',json.dumps(summary))

    def test_worker_tick_is_bounded_and_leaves_other_due_receipts_for_next_tick(self):
        self.stage()
        raw,sig=signed_event(event_id='evt_second')
        with patch.object(jobs,'process_delivery',side_effect=Crash):
            with self.assertRaises(Crash): payments.receive_stripe(self.db,self.adapter,raw,sig,101,FixturePolicy)
        self.assertEqual(self.tick(102,limit=1)['processed'],1)
        self.assertEqual(jobs.summary(self.db,self.adapter,102)['due'],1)
        self.assertEqual(self.tick(103,limit=1)['processed'],1)
        self.assertEqual(jobs.summary(self.db,self.adapter,103)['due'],0)

    def test_worker_rechecks_revoked_owner_eligibility_after_an_outage(self):
        self.fail=True;self.deliver();self.fail=False
        self.db.execute('UPDATE users SET eligible=0 WHERE id=1');self.db.commit()
        result=self.tick(131)['results'][0]
        self.assertEqual(result['reason'],'seller_or_buyer_unavailable')
        self.assertEqual(self.job()['state'],'review')
        self.assertEqual(self.status(),'tracking')

    def test_invalid_or_backwards_clock_leaves_claim_recoverable(self):
        receipt=self.stage();lease=jobs.claim(self.db,self.adapter,102,receipt)
        with self.assertRaises(jobs.JobError): jobs.process_claim(self.db,self.adapter,lease,102,FixturePolicy,clock=0)
        with self.assertRaises(jobs.JobError): jobs.process_claim(self.db,self.adapter,lease,102,FixturePolicy,clock=lambda:101)
        self.assertEqual(self.status(),'tracking')
        self.assertEqual(self.job()['state'],'running')

    def test_recovery_reader_needs_no_webhook_secret_and_cannot_ingest_events(self):
        self.stage()
        reader=payments.StripeTestPaymentReader('platform_fixture',lambda a,p:self.payment)
        self.assertFalse(hasattr(reader,'_secrets'))
        result=jobs.run_due(self.db,reader,102,policy=FixturePolicy,clock=lambda:102)
        self.assertEqual(result['results'][0]['outcome'],'observed_test')
        raw,sig=signed_event(event_id='evt_unverified')
        with self.assertRaises(payments.PaymentError): payments.receive_stripe(self.db,reader,raw,sig,102,FixturePolicy)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_events').fetchone()[0],1)

    def test_nonterminal_payment_is_polled_without_a_completion_webhook(self):
        self.payment=canonical(self.ctx['order'],status='processing')
        self.deliver()
        self.assertEqual(self.job()['state'],'retry')
        self.assertEqual(self.job()['last_reason'],'awaiting_canonical_final_state')
        self.assertEqual(self.status(),'pending')
        self.payment=canonical(self.ctx['order'])
        with patch.object(self.adapter,'verify',side_effect=AssertionError('must use existing verified receipt')):
            self.tick(131)
        self.assertEqual(self.status(),'succeeded')
        self.assertEqual(self.job()['state'],'complete')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_events').fetchone()[0],1)

    def test_legacy_nonterminal_observation_is_backfilled_as_recoverable(self):
        self.payment=canonical(self.ctx['order'],status='processing');self.deliver()
        self.db.execute('DROP TABLE marketplace_payment_jobs');payments.initialize(self.db)
        self.assertEqual(self.job()['state'],'retry')
        self.payment=canonical(self.ctx['order']);self.tick(102)
        self.assertEqual(self.status(),'succeeded')


class WorkerConcurrencyTests(unittest.TestCase):
    def test_two_connections_cannot_claim_the_same_live_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'jobs.db');db=sqlite3.connect(path);context=setup_payment(db)
            adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:canonical(context['order']))
            raw,sig=signed_event()
            with patch.object(jobs,'process_delivery',side_effect=Crash):
                with self.assertRaises(Crash): payments.receive_stripe(db,adapter,raw,sig,101,FixturePolicy)
            db.close()
            def claim(_):
                connection=sqlite3.connect(path,timeout=5);connection.row_factory=sqlite3.Row;connection.execute('PRAGMA foreign_keys=ON')
                try: return jobs.claim(connection,adapter,102)
                finally: connection.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: result=list(pool.map(claim,range(2)))
            self.assertEqual(sum(item is not None for item in result),1)


if __name__=='__main__': unittest.main()
