"""Checkout service tests with an explicit trusted-policy fixture, not Flask E2E."""
import concurrent.futures
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_checkout as checkout
import marketplace_inventory as inventory


class FixturePolicy:
    """Simulates site decisions; production adapter reuses existing site policy."""
    @staticmethod
    def adult(db, uid):
        row=db.execute('SELECT adult,eligible FROM users WHERE id=?',(uid,)).fetchone()
        return bool(row and row['adult'] and row['eligible'])

    @staticmethod
    def owner(db, uid, shop):
        return shop['owner_id']==uid and not shop['frozen']

    @staticmethod
    def visible(db, shop, buyer):
        return not shop['frozen']

    @staticmethod
    def fee_waived(db, shop):
        return bool(db.execute('SELECT 1 FROM benefits WHERE shop_id=? AND owner_id=?',(shop['page_id'],shop['owner_id'])).fetchone())


def fixture(db):
    db.row_factory=sqlite3.Row
    db.executescript('''
        CREATE TABLE users(id INTEGER PRIMARY KEY,adult INTEGER,eligible INTEGER);
        INSERT INTO users VALUES (1,1,1),(2,1,1),(3,1,1),(4,0,1),(5,1,0);
        CREATE TABLE seller_shops(page_id TEXT PRIMARY KEY,owner_id INTEGER,name TEXT,
            policies TEXT,revision INTEGER,frozen INTEGER);
        INSERT INTO seller_shops VALUES ('shop-a',1,'A shop','Original policies',0,0),('shop-b',3,'B shop','Other',0,0);
        CREATE TABLE seller_listings(id TEXT PRIMARY KEY,shop_id TEXT,kind TEXT,title TEXT,
            description TEXT,price_cents INTEGER,quantity INTEGER,variations TEXT,delivery TEXT,
            license TEXT,returns TEXT,state TEXT,revision INTEGER);
        INSERT INTO seller_listings VALUES ('a','shop-a','physical','Original title','Original copy',1000,3,'[]','Delivery','License','Returns','draft',0);
        INSERT INTO seller_listings VALUES ('b','shop-b','physical','Other title','Other copy',500,3,'[]','Other delivery','Other license','Other returns','draft',0);
        CREATE TABLE benefits(shop_id TEXT,owner_id INTEGER);
    ''')
    checkout.initialize(db)
    return checkout.sync_listing(db,'test',1,'shop-a','a',0,100,FixturePolicy)[0]['sku']


class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.sku=fixture(self.db)

    def tearDown(self):
        self.db.close()

    def order(self,key='checkout-one',lines=None,buyer=2,now=100,env='test'):
        return checkout.create_order(self.db,env,buyer,'shop-a',key,lines or [(self.sku,1,0)],now,FixturePolicy)

    def read(self,order,uid=2,now=101):
        return checkout.get_order(self.db,'test',uid,order,now,FixturePolicy)

    def update(self,sql,args=()):
        self.db.execute(sql,args)
        self.db.commit()

    def count(self,table):
        return self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

    def test_order_and_reservation_bound_to_immutable_server_snapshot(self):
        order=self.order()
        item=self.read(order)
        snapshot=item['snapshot']
        self.assertEqual(snapshot['subtotal_cents'],1000)
        self.assertEqual(snapshot['platform_fee_cents'],60)
        self.assertIsNone(snapshot['payable_total_cents'])
        self.assertFalse(snapshot['payment_enabled'])
        self.assertTrue(snapshot['test_only'])
        self.assertEqual(snapshot['lines'][0]['title'],'Original title')
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,101),2)
        self.update("UPDATE seller_listings SET title='Edited',price_cents=2000,returns='New returns',revision=1 WHERE id='a'")
        self.update("UPDATE seller_shops SET policies='New policies',revision=1 WHERE page_id='shop-a'")
        self.assertEqual(self.read(order)['snapshot'],snapshot)

    def test_insert_failure_rolls_back_reservation(self):
        self.db.execute("CREATE TRIGGER forced_failure BEFORE INSERT ON marketplace_checkout_orders BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.order()
        self.assertEqual(self.count('marketplace_inventory_holds'),0)
        self.assertEqual(self.count('marketplace_checkout_orders'),0)

    def test_replay_does_not_reprice_or_reserve_twice(self):
        order=self.order()
        self.update("UPDATE seller_listings SET price_cents=2000,revision=1 WHERE id='a'")
        self.assertEqual(order,self.order(now=101))
        self.assertEqual(self.count('marketplace_inventory_holds'),1)
        with self.assertRaises(checkout.CheckoutError): self.order(lines=[(self.sku,2,0)])

    def test_different_buyers_do_not_share_idempotency_scope(self):
        first=self.order()
        second=self.order(buyer=3)
        self.assertNotEqual(first,second)

    def test_stale_revision_and_unsynchronized_edit_rejected(self):
        self.update("UPDATE seller_listings SET revision=1 WHERE id='a'")
        for rev in [0,1]:
            with self.assertRaisesRegex(checkout.CheckoutError,'changed'): self.order(lines=[(self.sku,1,rev)])
        checkout.sync_listing(self.db,'test',1,'shop-a','a',1,100,FixturePolicy)
        self.order(lines=[(self.sku,1,1)])

    def test_cross_seller_cart_rejected_without_hold(self):
        other=checkout.sync_listing(self.db,'test',3,'shop-b','b',0,100,FixturePolicy)[0]['sku']
        with self.assertRaises(checkout.CheckoutError): self.order(lines=[(self.sku,1,0),(other,1,0)])
        self.assertEqual(self.count('marketplace_inventory_holds'),0)

    def test_owner_only_provisioning_and_revoked_eligibility(self):
        for uid in [2,3,4,5,True]:
            with self.subTest(uid=uid),self.assertRaises(checkout.CheckoutError):
                checkout.sync_listing(self.db,'test',uid,'shop-a','a',0,100,FixturePolicy)
        self.update('UPDATE users SET eligible=0 WHERE id=1')
        with self.assertRaises(checkout.CheckoutError): self.order()

    def test_buyer_eligibility_and_self_purchase(self):
        for uid in [1,4,5,True]:
            with self.subTest(uid=uid),self.assertRaises(checkout.CheckoutError): self.order(buyer=uid)

    def test_frozen_shop_blocks_new_orders_and_owner_access(self):
        order=self.order()
        self.update("UPDATE seller_shops SET frozen=1 WHERE page_id='shop-a'")
        with self.assertRaises(checkout.CheckoutError): self.order(key='new')
        with self.assertRaises(checkout.CheckoutError): self.read(order,uid=1)
        self.assertEqual(self.read(order)['snapshot']['shop_name'],'A shop')

    def test_order_privacy_does_not_follow_page_editor_or_new_owner(self):
        order=self.order()
        self.assertEqual(self.read(order,uid=1)['id'],order)
        with self.assertRaises(checkout.CheckoutError): self.read(order,uid=3)
        self.update("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'")
        for uid in [1,3]:
            with self.assertRaises(checkout.CheckoutError): self.read(order,uid=uid)
        self.assertEqual(self.read(order)['id'],order)
        with self.assertRaises(checkout.CheckoutError): self.order(key='after-transfer')

    def test_owner_bound_fee_exemption(self):
        self.update("INSERT INTO benefits VALUES ('shop-a',3)")
        self.assertEqual(self.read(self.order())['snapshot']['platform_fee_cents'],60)
        self.update("INSERT INTO benefits VALUES ('shop-a',1)")
        self.assertEqual(self.read(self.order(key='waived'))['snapshot']['platform_fee_cents'],0)

    def test_cancel_and_expiry_release_once_without_reviving_replay(self):
        order=self.order()
        self.assertEqual(checkout.cancel_order(self.db,'test',2,order,101,FixturePolicy),'canceled')
        self.assertEqual(checkout.cancel_order(self.db,'test',2,order,102,FixturePolicy),'canceled')
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,102),3)
        self.assertEqual(self.order(now=103),order)
        self.assertEqual(self.read(order)['state'],'canceled')
        other=self.order(key='expire')
        self.assertEqual(self.read(other,now=1000)['state'],'expired')
        self.assertEqual(checkout.cancel_order(self.db,'test',2,other,1000,FixturePolicy),'expired')

    def test_foreign_buyer_cannot_cancel(self):
        order=self.order()
        with self.assertRaises(checkout.CheckoutError): checkout.cancel_order(self.db,'test',3,order,101,FixturePolicy)
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,101),2)

    def test_raw_reservation_release_updates_order_too(self):
        order=self.order()
        hold=self.db.execute('SELECT hold_id FROM marketplace_checkout_orders WHERE id=?',(order,)).fetchone()[0]
        inventory.release(self.db,'test','2',hold,101)
        self.assertEqual(self.read(order)['state'],'canceled')

    def test_sql_snapshot_mode_state_and_deletion_are_guarded(self):
        order=self.order()
        statements=["UPDATE marketplace_checkout_orders SET snapshot='{}'", "UPDATE marketplace_checkout_orders SET environment='live'", "UPDATE marketplace_checkout_orders SET state='canceled'", "UPDATE marketplace_checkout_orders SET state='paid'", "DELETE FROM marketplace_checkout_orders"]
        for sql in statements:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()
        self.assertEqual(self.read(order)['state'],'awaiting_payment')

    def test_live_checkout_and_invalid_cart_fail_closed(self):
        with self.assertRaises(checkout.CheckoutError): self.order(env='live')
        for lines in [[(self.sku,True,0)],[(self.sku,1,True)],[(self.sku,100,0)],[(self.sku,1,0),(self.sku,1,0)]]:
            with self.subTest(lines=lines),self.assertRaises(checkout.CheckoutError): self.order(lines=lines)

    def test_variation_reorder_rename_and_active_holds(self):
        variants=[dict(label='Red',price_cents=1000,quantity=2),dict(label='Blue',price_cents=1500,quantity=1)]
        self.update("UPDATE seller_listings SET variations=?,revision=1 WHERE id='a'",(json.dumps(variants),))
        skus=checkout.sync_listing(self.db,'test',1,'shop-a','a',1,100,FixturePolicy)
        red=skus[0]['sku'];blue=skus[1]['sku']
        self.order(lines=[(red,1,1)])
        self.update("UPDATE seller_listings SET variations=?,revision=2 WHERE id='a'",(json.dumps(list(reversed(variants))),))
        reordered=checkout.sync_listing(self.db,'test',1,'shop-a','a',2,101,FixturePolicy)
        self.assertEqual([s['sku'] for s in reordered],[blue,red])
        variants[0]['label']='Crimson'
        self.update("UPDATE seller_listings SET variations=?,revision=3 WHERE id='a'",(json.dumps(variants),))
        with self.assertRaisesRegex(checkout.CheckoutError,'active reservations'):
            checkout.sync_listing(self.db,'test',1,'shop-a','a',3,101,FixturePolicy)
        changed=checkout.sync_listing(self.db,'test',1,'shop-a','a',3,1000,FixturePolicy)
        self.assertNotEqual(changed[0]['sku'],red)
        with self.assertRaises(checkout.CheckoutError): self.order(key='old-red',lines=[(red,1,3)],now=1000)

    def test_resync_cannot_reduce_stock_below_held_or_duplicate_holds(self):
        self.order(lines=[(self.sku,2,0)])
        self.update("UPDATE seller_listings SET quantity=1,revision=1 WHERE id='a'")
        with self.assertRaises(inventory.InventoryError): checkout.sync_listing(self.db,'test',1,'shop-a','a',1,101,FixturePolicy)
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,101),1)

    def test_repeated_migration_preserves_order_and_legacy_rehearsals(self):
        order=self.order()
        self.update('CREATE TABLE seller_test_orders(id TEXT)')
        self.update("INSERT INTO seller_test_orders VALUES ('legacy-only')")
        checkout.initialize(self.db)
        self.assertEqual(self.read(order)['id'],order)
        self.assertEqual(self.count('seller_test_orders'),1)

    def test_expiry_maintenance_is_bounded_and_preserves_fresh_holds(self):
        first=self.order()
        second=self.order(key='second')
        fresh=self.order(key='fresh',now=101)
        self.assertEqual(checkout.expire_orders(self.db,'test',999),0)
        self.assertEqual(checkout.expire_orders(self.db,'test',1000,limit=1),1)
        self.assertEqual(checkout.expire_orders(self.db,'test',1000,limit=1),1)
        self.assertEqual(checkout.expire_orders(self.db,'test',1000),0)
        self.assertEqual(self.read(first,now=1000)['state'],'expired')
        self.assertEqual(self.read(second,now=1000)['state'],'expired')
        self.assertEqual(self.read(fresh,now=1000)['state'],'awaiting_payment')
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,1000),2)


class CheckoutConcurrencyTests(unittest.TestCase):
    def race(self, same_buyer):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'checkout.db')
            db=sqlite3.connect(path)
            sku=fixture(db)
            db.execute("UPDATE seller_listings SET quantity=1 WHERE id='a'")
            db.commit()
            checkout.sync_listing(db,'test',1,'shop-a','a',0,100,FixturePolicy)
            db.close()
            def attempt(uid):
                db=sqlite3.connect(path,timeout=5)
                db.row_factory=sqlite3.Row
                db.execute('PRAGMA foreign_keys=ON')
                try:
                    return checkout.create_order(db,'test',uid,'shop-a','race',[(sku,1,0)],100,FixturePolicy)
                except inventory.InventoryError as error:
                    if str(error)!='insufficient stock': raise
                    return 'sold out'
                finally: db.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,[2,2 if same_buyer else 3]))
            db=sqlite3.connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_checkout_orders').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_inventory_holds').fetchone()[0],1)
            db.close()
            return results

    def test_two_buyers_last_item_produces_one_order(self):
        results=self.race(False)
        self.assertEqual(results.count('sold out'),1)

    def test_duplicate_checkout_from_two_connections_returns_same_order(self):
        results=self.race(True)
        self.assertEqual(results[0],results[1])
        self.assertNotEqual(results[0],'sold out')


if __name__=='__main__':
    unittest.main()
