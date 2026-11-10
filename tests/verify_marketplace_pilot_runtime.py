"""Private pilot publication, simulated tax and isolated WSGI routing."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_purchase_sandbox as host
import marketplace_pilot_runtime as runtime
import verify_marketplace_shipping_sandbox as shipping_fixture
from io import BytesIO

class TaxTests(unittest.TestCase):
    def test_explicit_test_tax_is_bound_and_rounded(self):
        tax=runtime.SimulationTax(dict(kind='simulation_only',basis_points=700),lambda:100)
        r=tax.quote_tax(dict(environment='test',subtotal_cents=1000,shipping=dict(amount_cents=525)),'bound-context')
        self.assertEqual((r.amount_cents,r.context_hash,r.source,r.expires_at),(107,'bound-context','simulation-only',400))
    def test_live_or_missing_tax_mode_is_not_accepted(self):
        for cfg in [{},dict(kind='real',basis_points=0),dict(kind='simulation_only',basis_points=True),dict(kind='simulation_only',basis_points=3000)]:
            with self.assertRaises(ValueError):runtime.SimulationTax(cfg)
        with self.assertRaises(ValueError):runtime.SimulationTax(dict(kind='simulation_only',basis_points=700)).quote_tax({'environment':'live'},'x')

class PrivateGrantTests(unittest.TestCase):
    setUp=shipping_fixture.PolicyTests.setUp;tearDown=shipping_fixture.PolicyTests.tearDown
    def prepare(self):
        host.initialize_purchase_store(self.db)
        self.policy.catalog.detail=lambda *args:(_ for _ in ()).throw(ValueError('not publicly listed'))
        policy=host.LivePurchasePolicy(self.core,self.policy.studio,self.policy.catalog,[1,2],{'shop-a':1})
        host.refresh(self.db,policy,110)
        return policy
    def grant(self,revision=0,owner=1):
        self.db.execute('INSERT INTO marketplace_pilot_listing_grants VALUES (?,?,?,?,?,1)',('a','shop-a',owner,revision,110));self.db.commit()
    def test_no_private_draft_purchase_without_explicit_grant(self):
        policy=self.prepare();self.assertFalse(policy.published(self.db,'a',2))
    def test_grant_is_tester_limited_and_does_not_change_native_catalog(self):
        policy=self.prepare();before='\n'.join(self.live.iterdump());self.grant()
        self.assertTrue(policy.published(self.db,'a',2));self.assertFalse(policy.published(self.db,'a',3))
        self.assertEqual(before,'\n'.join(self.live.iterdump()))
        self.db.execute('UPDATE marketplace_pilot_listing_grants SET active=0');self.db.commit()
        self.assertFalse(policy.published(self.db,'a',2))
    def test_old_revision_or_changed_native_state_denies_grant(self):
        policy=self.prepare();self.grant(revision=1);self.assertFalse(policy.published(self.db,'a',2))
        self.db.execute('UPDATE marketplace_pilot_listing_grants SET listing_revision=0');self.db.commit()
        self.live.execute("UPDATE seller_listings SET state='archived' WHERE id='a'");self.live.commit()
        self.assertFalse(policy.published(self.db,'a',2))
    def test_upgrade_preserves_existing_isolated_settings(self):
        before='\n'.join(self.db.iterdump());host.initialize_purchase_store(self.db)
        self.assertEqual(self.db.execute('SELECT purpose FROM marketplace_shipping_host_marker').fetchone()[0],'sandbox_shipping_settings_only_v1')
        self.assertIn('sandbox_shipping_settings_only_v1',before)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
        with self.assertRaises(Exception):host.initialize_purchase_store(self.db)

class DispatchTests(unittest.TestCase):
    def test_pilot_hook_mount_cannot_intercept_production_or_old_webhook(self):
        calls=[]
        def original(e,s):calls.append(('original',e['PATH_INFO']));s('200 OK',[]);return [b'original']
        def receiver(e,s):calls.append(('pilot',e['PATH_INFO']));s('405 Method Not Allowed',[]);return [b'pilot']
        app=runtime.mount(original,receiver)
        for path,expected in [('/marketplace/pilot/provider-events/stripe','original'),('/sandbox/marketplace/provider-events/stripe','original'),('/sandbox/marketplace/pilot/provider-events/stripe','pilot')]:
            app(dict(PATH_INFO=path,wsgi_input=BytesIO()),lambda *a:None);self.assertEqual(calls[-1][0],expected)
        self.assertEqual(calls[-1][1],'/stripe')

if __name__=='__main__':unittest.main()
