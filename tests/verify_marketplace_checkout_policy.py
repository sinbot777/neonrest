"""Exercise existing seller/Page/catalog policy with controlled age/contact inputs.

Loads repository modules without importing the Flask application. Age/contact
services are fixture boundaries; this is not a full request/session test.
"""
import importlib
import pathlib
import sqlite3
import sys
import types
import unittest


class ExistingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.prefix='_marketplace_existing_policy_test'
        package=types.ModuleType(self.prefix)
        package.__path__=[str(pathlib.Path(__file__).resolve().parents[1])]
        sys.modules[self.prefix]=package
        age=types.ModuleType(self.prefix+'.age_policy')
        age.age=lambda db,uid: db.execute('SELECT years FROM users WHERE id=?',(uid,)).fetchone()[0]
        age.ready=lambda db,uid: age.age(db,uid)>=13
        age.can_read=lambda db,a,b: True
        age.contact=lambda db,a,b: True
        sys.modules[age.__name__]=age
        community=types.ModuleType(self.prefix+'.community_features')
        community.blocked=lambda db,a,b: bool(db.execute('SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',(a,b,b,a)).fetchone())
        sys.modules[community.__name__]=community
        self.checkout=importlib.import_module(self.prefix+'.marketplace_checkout')
        self.studio=importlib.import_module(self.prefix+'.seller_studio')
        self.pages=importlib.import_module(self.prefix+'.identity_pages')
        self.catalog=importlib.import_module(self.prefix+'.marketplace_catalog')
        db=self.db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        db.executescript('''
          CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT,verified INTEGER,years INTEGER);
          INSERT INTO users VALUES (1,'@owner',1,40),(2,'@buyer',1,25),(3,'@editor',1,30),(4,'@teen',1,17),(5,'@unverified',0,40);
          CREATE TABLE account_disables(user_id INTEGER,disabled INTEGER);
          CREATE TABLE account_safety(user_id INTEGER,inactive INTEGER);
          CREATE TABLE user_moderation(user_id INTEGER,banned INTEGER,posting_restricted INTEGER);
          CREATE TABLE user_mutes(user_id INTEGER,target_id INTEGER);
          CREATE TABLE user_blocks(user_id INTEGER,target_id INTEGER);
        ''')
        self.pages.initialize(db)
        self.studio.initialize(db)
        self.catalog.initialize(db)
        db.execute("INSERT INTO identity_pages(id,kind,handle,owner_id,name,state,created_at,updated_at) VALUES ('page','creative','_shop',1,'Page','published',100,100)")
        db.execute("INSERT INTO identity_page_members(page_id,user_id,role) VALUES ('page',3,'editor')")
        db.execute("INSERT INTO seller_shops(page_id,owner_id,name,created_at,updated_at,identity_kind,linked_page_id) VALUES ('shop',1,'Shop',100,100,'page','page')")
        db.execute("INSERT INTO seller_listings(id,shop_id,kind,title,price_cents,quantity,created_by,updated_by,created_at,updated_at) VALUES ('listing','shop','physical','Item',1000,3,1,1,100,100)")
        db.commit()
        self.checkout.initialize(db)
        self.sku=self.checkout.sync_listing(db,'test',1,'shop','listing',0,100)[0]['sku']

    def tearDown(self):
        self.db.close()
        for key in list(sys.modules):
            if key==self.prefix or key.startswith(self.prefix+'.'):
                del sys.modules[key]

    def order(self,uid=2):
        return self.checkout.create_order(self.db,'test',uid,'shop','request',[(self.sku,1,0)],100)

    def test_real_policy_rejects_minor_unverified_and_restricted(self):
        for uid in [4,5]:
            with self.subTest(uid=uid),self.assertRaises(self.checkout.CheckoutError): self.order(uid)
        for sql in ["INSERT INTO account_disables VALUES (2,1)","INSERT INTO account_safety VALUES (2,1)","INSERT INTO user_moderation VALUES (2,0,1)"]:
            self.db.execute(sql);self.db.commit()
            with self.assertRaises(self.checkout.CheckoutError): self.order()
            for table in ['account_disables','account_safety','user_moderation']: self.db.execute('DELETE FROM '+table)
            self.db.commit()

    def test_page_editor_can_edit_listing_but_not_stock_or_orders(self):
        self.studio.access(self.db,3,'shop')
        with self.assertRaises(self.checkout.CheckoutError): self.checkout.sync_listing(self.db,'test',3,'shop','listing',0,100)
        order=self.order()
        with self.assertRaises(self.checkout.CheckoutError): self.checkout.get_order(self.db,'test',3,order,101)
        self.assertEqual(self.checkout.get_order(self.db,'test',1,order,101)['id'],order)

    def test_linked_page_transfer_freezes_checkout_without_transferring_shop(self):
        self.db.execute("UPDATE identity_pages SET owner_id=3 WHERE id='page'");self.db.commit()
        with self.assertRaises(self.checkout.CheckoutError): self.order()
        with self.assertRaises(self.studio.StudioError): self.checkout.sync_listing(self.db,'test',1,'shop','listing',0,100)

    def test_real_block_and_mute_policy_prevents_checkout(self):
        for table in ['user_blocks','user_mutes']:
            self.db.execute('INSERT INTO '+table+' VALUES (2,1)');self.db.commit()
            with self.assertRaises(self.checkout.CheckoutError): self.order()
            self.db.execute('DELETE FROM '+table);self.db.commit()

    def test_existing_owner_bound_fee_benefit_is_used(self):
        self.db.execute("INSERT INTO marketplace_shop_benefits VALUES ('shop',1,1,'owner-comp',100)");self.db.commit()
        snapshot=self.checkout.get_order(self.db,'test',2,self.order(),101)['snapshot']
        self.assertTrue(snapshot['platform_fees_waived'])
        self.assertEqual(snapshot['platform_fee_cents'],0)


if __name__=='__main__':
    unittest.main()
