"""Host policy and scheduled recovery boundaries; provider HTTP remains fictional."""
from pathlib import Path
import sqlite3,sys,types,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_purchase_sandbox as host
import marketplace_shipping_sandbox as shipping_host
import marketplace_payments as payments
from verify_marketplace_shipping_sandbox import PolicyTests as PolicyFixture
from verify_marketplace_pilot_views import PilotTests as PilotFixture
from verify_marketplace_payments import signed_event,SECRET


class HostPolicyTests(unittest.TestCase):
    setUp=PolicyFixture.setUp
    tearDown=PolicyFixture.tearDown
    def purchase_policy(self):
        catalog=self.policy.catalog
        def detail(db,buyer,listing):
            row=db.execute('SELECT * FROM seller_listings WHERE id=?',(listing,)).fetchone()
            if not row:raise ValueError('unavailable')
            return dict(row)
        catalog.detail=detail
        return host.LivePurchasePolicy(self.core,self.policy.studio,catalog,[1,2],{'shop-a':1})
    def test_allowlist_cannot_be_overridden_by_live_or_mirrored_eligibility(self):
        policy=self.purchase_policy();self.assertFalse(policy.adult(self.db,3))
        shipping_host.refresh_mirror(self.db,1,policy,110)
        shop=self.db.execute('SELECT * FROM seller_shops').fetchone()
        self.assertTrue(policy.visible(self.db,shop,2))
        self.assertFalse(policy.visible(self.db,shop,3))
        policy.sellers={}
        self.assertFalse(policy.owner(self.db,1,shop))
    def test_current_publication_must_match_full_mirror_snapshot(self):
        policy=self.purchase_policy();host.refresh(self.db,policy,110)
        self.assertTrue(policy.published(self.db,'a',2))
        self.live.execute("UPDATE seller_listings SET price_cents=price_cents+1 WHERE id='a'");self.live.commit()
        self.assertFalse(policy.published(self.db,'a',2))
    def test_same_revision_refresh_never_replenishes_consumed_inventory(self):
        policy=self.purchase_policy();host.refresh(self.db,policy,110)
        self.db.execute('UPDATE marketplace_inventory_stock SET quantity=1');self.db.commit()
        host.refresh(self.db,policy,111);host.refresh(self.db,policy,112)
        self.assertEqual(self.db.execute('SELECT quantity FROM marketplace_inventory_stock').fetchone()[0],1)
    def test_shop_policy_edit_revokes_stale_quote_visibility(self):
        policy=self.purchase_policy();host.refresh(self.db,policy,110)
        shop=self.db.execute('SELECT * FROM seller_shops').fetchone()
        self.live.execute("UPDATE seller_shops SET policies='changed' WHERE page_id='shop-a'");self.live.commit()
        self.assertFalse(policy.visible(self.db,shop,2))
    def test_purchase_provision_is_explicit_and_refuses_existing_shipping_store(self):
        with self.assertRaises(ValueError):host.provision(self.db)
        db=sqlite3.connect(':memory:')
        try:
            host.provision(db)
            self.assertEqual(db.execute('SELECT purpose FROM marketplace_purchase_host_marker').fetchone()[0],host.PURPOSE)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally:db.close()
    def test_production_mount_and_unscheduled_worker_are_rejected(self):
        core=types.SimpleNamespace(__name__='neonrest.app',app=object())
        with self.assertRaises(ValueError):host.register(core.app,core,'unused',[1],{'shop-a':1},lambda *a:None,True)
        core.__name__='neonrest_sandbox.app'
        with self.assertRaises(ValueError):host.register(core.app,core,'unused',[1],{'shop-a':1},lambda *a:None)


class ScheduledRecoveryTests(unittest.TestCase):
    setUp=PilotFixture.setUp;tearDown=PilotFixture.tearDown
    connect=PilotFixture.connect;services=PilotFixture.services;login=PilotFixture.login
    post=PilotFixture.post;query=PilotFixture.query;start=PilotFixture.start;quote=PilotFixture.quote;paid=PilotFixture.paid
    def tick(self,limit=25):
        db=self.connect()
        try:
            db.execute('CREATE TABLE IF NOT EXISTS marketplace_purchase_worker_cursor(platform TEXT PRIMARY KEY,receipt_id INTEGER NOT NULL)');db.commit()
            return host.recovery_tick(self.services(db),limit)
        finally:db.close()
    def deliver(self,event='evt_worker',kind='payment_intent.succeeded'):
        db=self.connect()
        try:
            ctx=self.services(db);adapter=payments.StripeTestWebhookAdapter('acct_platform',[SECRET],ctx.stripe.fetch_payment)
            raw,sig=signed_event(event_id=event,payment='pi_flow1',kind=kind,now=self.clock)
            payments.receive_stripe(db,adapter,raw,sig,self.clock,ctx.policy)
        finally:db.close()
    def submit(self,lost=False):
        self.start();quote=self.quote();self.http.timeout=lost
        result=self.post('/orders/'+self.order+'/pay',dict(quote_id=quote,accept_total='yes',test_card='pm_card_visa'))
        self.assertEqual(result.status_code,503 if lost else 302)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],0)
    def test_worker_settles_without_browser_refresh_and_never_duplicates_stock_or_journal(self):
        self.submit();self.deliver();self.assertEqual(self.tick()['settled'],1)
        self.tick();self.tick()
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_inventory_consumptions')[0][0],1)
        self.assertEqual(self.http.created,1)
    def test_lost_creation_response_recovers_from_verified_receipt(self):
        self.submit(lost=True);self.deliver();self.tick()
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],1)
        self.assertEqual(self.http.created,1)
    def test_lost_refund_response_uses_original_dispatch_in_worker(self):
        self.paid();self.login(1);self.http.timeout=True
        r=self.post('/orders/'+self.order+'/refund',dict(request_key='worker-refund',item_cents='1000',shipping_cents='525',tax_cents='90'))
        self.assertEqual(r.status_code,503)
        self.tick();self.tick()
        self.assertEqual(self.http.refunded,1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_refund_applications')[0][0],1)
    def test_worker_never_creates_a_payment_without_signed_confirmation(self):
        self.submit(lost=True);self.tick()
        self.assertEqual(self.http.created,1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],0)
    def test_cursor_advances_past_unsupported_receipt(self):
        self.submit();self.deliver('evt_ignored','payment_intent.created');self.deliver('evt_success')
        self.tick(1);self.tick(1)
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_test_settlements')[0][0],1)
    def test_unbounded_worker_batch_is_refused(self):
        for n in [0,101,True]:
            with self.assertRaises(ValueError):self.tick(n)

del PolicyFixture, PilotFixture
if __name__=='__main__':unittest.main()
