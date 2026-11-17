"""Shipping-only route gate and authoritative policy/mirror boundaries."""
from pathlib import Path
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import marketplace_shipping_sandbox as mount
import marketplace_pilot_views as views
import verify_marketplace_seller_shipping as fixtures
from verify_marketplace_checkout import fixture,FixturePolicy

class ScopeTests(unittest.TestCase):
    connect=fixtures.SellerShippingTests.connect;services=fixtures.SellerShippingTests.services
    login=fixtures.SellerShippingTests.login;post=fixtures.SellerShippingTests.post;query=fixtures.SellerShippingTests.query
    tearDown=fixtures.SellerShippingTests.tearDown
    def setUp(self):
        original=views.register
        def shipping_only(*args,**kw):return original(*args,**kw,settings_only=True)
        with patch.object(views,'register',side_effect=shipping_only):fixtures.SellerShippingTests.setUp(self)
    def test_shipping_navigation_and_owner_forms_remain_available(self):
        self.login(1)
        self.assertEqual(self.client.get('/marketplace/pilot/').status_code,302)
        self.assertEqual(self.client.get('/marketplace/pilot/seller/shipping').status_code,200)
        r=self.client.get('/marketplace/pilot/seller/shipping/shop-a');self.assertEqual(r.status_code,200,r.data)
        self.assertNotIn(b'>Test catalog<',r.data);self.assertNotIn(b'>Seller orders<',r.data)
        self.assertIn(b'Package presets',r.data)
    def test_all_purchase_and_fulfillment_routes_are_unavailable(self):
        for method,path in [('GET','/purchases'),('GET','/seller/orders'),('GET','/orders/anything'),('POST','/checkout'),('POST','/orders/anything/pay'),('POST','/orders/anything/refund'),('POST','/orders/anything/rates'),('POST','/orders/anything/destination')]:
            r=self.client.open('/marketplace/pilot'+path,method=method)
            self.assertEqual(r.status_code,404,(method,path,r.status_code))
        self.assertEqual(self.query('SELECT COUNT(*) FROM marketplace_checkout_orders')[0][0],0)
    def test_existing_csrf_owner_and_session_guards_still_apply(self):
        self.login(3);self.assertEqual(self.client.get('/marketplace/pilot/seller/shipping/shop-a').status_code,400)
        self.login(1);self.assertEqual(self.client.post('/marketplace/pilot/seller/shipping/shop-a/connection').status_code,403)
        with self.client.session_transaction() as s:s.clear()
        self.assertEqual(self.client.get('/marketplace/pilot/seller/shipping').status_code,401)

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.live=sqlite3.connect(':memory:');fixture(self.live)
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');mount.provision(self.db)
        live=self.live
        class Studio:
            adult_account=staticmethod(FixturePolicy.adult)
            @staticmethod
            def access(db,uid,shop,owner_only=False):
                self.assertIs(db,live);self.assertTrue(owner_only)
                row=db.execute('SELECT * FROM seller_shops WHERE page_id=?',(shop,)).fetchone()
                if not row or row['owner_id']!=uid or row['frozen']:raise ValueError('forbidden')
                return dict(state='published'),row
        class Catalog:
            allowed=staticmethod(FixturePolicy.visible);fee_policy=staticmethod(FixturePolicy.fee_waived)
        self.core=types.SimpleNamespace(get_db=lambda:self.live)
        self.policy=mount.LivePolicy(self.core,Studio,Catalog)
    def tearDown(self):self.db.close();self.live.close()
    def test_mirror_copies_only_current_owners_shipping_metadata_and_no_auth_data(self):
        before='\n'.join(self.live.iterdump());mount.refresh_mirror(self.db,1,self.policy,110)
        self.assertEqual([r[0] for r in self.db.execute('SELECT page_id FROM seller_shops')],['shop-a'])
        self.assertEqual([r[1] for r in self.db.execute('PRAGMA table_info(users)')],['id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_skus WHERE active=1').fetchone()[0],1)
        self.assertEqual(before,'\n'.join(self.live.iterdump()))
    def test_local_mirror_cannot_override_live_eligibility_or_revocation(self):
        mount.refresh_mirror(self.db,1,self.policy,110);row=self.db.execute('SELECT * FROM seller_shops').fetchone()
        self.assertTrue(self.policy.owner(self.db,1,row))
        self.live.execute("UPDATE seller_shops SET frozen=1 WHERE page_id='shop-a'");self.live.commit()
        self.assertFalse(self.policy.owner(self.db,1,row))
        self.live.execute('UPDATE users SET eligible=0 WHERE id=1');self.live.commit()
        self.assertFalse(self.policy.adult(self.db,1))
        with self.assertRaises(ValueError):mount.refresh_mirror(self.db,1,self.policy,111)
    def test_provision_refuses_existing_database_and_mount_refuses_production(self):
        with self.assertRaises(ValueError):mount.provision(self.db)
        core=types.SimpleNamespace(__name__='neonrest.app',app=object())
        with self.assertRaises(ValueError):mount.register(core.app,core,'/ignored','/ignored',[1])
    def test_removed_listing_is_deactivated_without_altering_live_stock(self):
        mount.refresh_mirror(self.db,1,self.policy,110)
        self.live.execute("UPDATE seller_listings SET kind='digital' WHERE id='a'");self.live.commit()
        before='\n'.join(self.live.iterdump());mount.refresh_mirror(self.db,1,self.policy,111)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_skus WHERE active=1').fetchone()[0],0)
        self.assertEqual(before,'\n'.join(self.live.iterdump()))

if __name__=='__main__':unittest.main()
