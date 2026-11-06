"""Run with python -m unittest discover -s tests -p verify_marketplace_foundations.py."""
import concurrent.futures
import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_inventory as stock
import marketplace_ledger as ledger
from marketplace_core import commission_refund, quote


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        stock.initialize(self.db)
        ledger.initialize(self.db)
        for name, kind in [('cash','asset'),('seller','liability'),('fees','income')]:
            ledger.create_account(self.db, name, 'test', 'shop-a', kind)
        stock.set_stock(self.db, 'test', 'shop-a', 'sku-a', 3, 100)

    def tearDown(self):
        self.db.close()

    def hold(self, key='one', lines=None, now=100, **kw):
        return stock.reserve(self.db, 'test', 'shop-a', 'buyer-a', key, lines or [('sku-a',2)], now, **kw)

    def post(self, key='capture', entries=None, env='test'):
        return ledger.post(self.db, env, key, 'provider-account:event-1', entries or [('cash',1000),('seller',-940),('fees',-60)], 100)

    def test_initialize_repeated_preserves_existing_tables(self):
        self.db.execute('CREATE TABLE seller_test_orders(id TEXT)')
        self.db.execute("INSERT INTO seller_test_orders VALUES ('never-promote')")
        self.db.commit()
        self.hold()
        self.post()
        stock.initialize(self.db)
        ledger.initialize(self.db)
        self.assertEqual(self.db.execute('SELECT * FROM seller_test_orders').fetchall(), [('never-promote',)])
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',101),1)
        self.assertEqual(ledger.balances(self.db,'test')['fees'],-60)

    def test_hold_replay_and_conflict(self):
        h = self.hold()
        self.assertEqual(h,self.hold(now=101))
        with self.assertRaises(stock.InventoryError): self.hold(lines=[('sku-a',1)])
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',101),1)

    def test_batch_failure_rolls_back_all_lines(self):
        stock.set_stock(self.db,'test','shop-a','sku-b',1,100)
        with self.assertRaises(stock.InventoryError): self.hold(lines=[('sku-a',2),('sku-b',2)])
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',100),3)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_inventory_holds').fetchone()[0],0)

    def test_expiry_boundary_and_no_revival(self):
        h=self.hold(ttl=10)
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',109),1)
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',110),3)
        self.assertEqual(h,self.hold(now=111,ttl=10))
        self.assertEqual(stock.release(self.db,'test','buyer-a',h,111),'expired')

    def test_release_is_idempotent_and_scoped(self):
        h=self.hold()
        for env,buyer in [('live','buyer-a'),('test','buyer-b')]:
            with self.assertRaises(stock.InventoryError): stock.release(self.db,env,buyer,h,101)
        self.assertEqual(stock.release(self.db,'test','buyer-a',h,101),'released')
        self.assertEqual(stock.release(self.db,'test','buyer-a',h,102),'released')
        self.assertEqual(h,self.hold(now=103))
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',103),3)

    def test_adjustment_cannot_reset_held_stock(self):
        self.hold()
        with self.assertRaises(stock.InventoryError): stock.set_stock(self.db,'test','shop-a','sku-a',1,101)
        stock.set_stock(self.db,'test','shop-a','sku-a',2,101)
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',101),0)

    def test_seller_environment_and_buyer_key_scoping(self):
        self.hold()
        stock.set_stock(self.db,'live','shop-a','sku-a',9,100)
        stock.set_stock(self.db,'test','shop-b','sku-a',9,100)
        self.assertEqual(stock.available(self.db,'live','shop-a','sku-a',100),9)
        self.assertEqual(stock.available(self.db,'test','shop-b','sku-a',100),9)
        stock.reserve(self.db,'test','shop-a','buyer-b','one',[('sku-a',1)],100)
        self.assertEqual(stock.available(self.db,'test','shop-a','sku-a',100),0)

    def test_invalid_quantities_and_duplicate_sku(self):
        for n in [True,False,0,-1,1.5,'2',100]:
            with self.subTest(n=n),self.assertRaises(stock.InventoryError): self.hold(lines=[('sku-a',n)])
        with self.assertRaises(stock.InventoryError): self.hold(lines=[('sku-a',1),('sku-a',1)])

    def test_balanced_journal_and_reordered_replay(self):
        j=self.post()
        self.assertEqual(j,self.post(entries=[('fees',-60),('seller',-940),('cash',1000)]))
        self.assertEqual(ledger.balances(self.db,'test'),{'cash':1000,'seller':-940,'fees':-60})
        with self.assertRaises(ledger.LedgerError): self.post(entries=[('cash',1000),('seller',-1000)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],1)

    def test_journal_cannot_cross_environments(self):
        with self.assertRaises(sqlite3.IntegrityError): self.post(env='live')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],0)

    def test_invalid_money_and_unbalanced(self):
        for entries in [[('cash',True),('seller',-1)],[('cash',1.1),('seller',-1.1)], [('cash',100),('seller',-99)], [('cash',10),('cash',-10)], [('cash',0),('seller',0)]]:
            with self.subTest(entries=entries),self.assertRaises(ledger.LedgerError): self.post(entries=entries)

    def test_missing_account_rolls_back_and_can_retry(self):
        with self.assertRaises(sqlite3.IntegrityError): self.post(entries=[('missing',1000),('seller',-1000)])
        ledger.create_account(self.db,'missing','test','shop-a','asset')
        self.post(entries=[('missing',1000),('seller',-1000)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],1)

    def test_sql_cannot_change_posted_journal_or_accounts(self):
        j=self.post()
        for sql in [f'DELETE FROM marketplace_ledger_journals WHERE id={j}', f'UPDATE marketplace_ledger_journals SET event_ref="other" WHERE id={j}', f'DELETE FROM marketplace_ledger_entries WHERE journal_id={j}', f'UPDATE marketplace_ledger_entries SET amount_cents=1 WHERE journal_id={j}', 'UPDATE marketplace_ledger_accounts SET owner="other" WHERE id="seller"', f'INSERT INTO marketplace_ledger_entries VALUES ({j},"test","missing",1)']:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()
        self.assertEqual(ledger.balances(self.db,'test')['cash'],1000)

    def test_sql_cannot_seal_unbalanced_or_insert_posted(self):
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("INSERT INTO marketplace_ledger_journals VALUES (1,'test','k','h','e',100,1)")
        self.db.rollback()
        self.db.execute("INSERT INTO marketplace_ledger_journals VALUES (1,'test','k','h','e',100,0)")
        self.db.execute("INSERT INTO marketplace_ledger_entries VALUES (1,'test','cash',100)")
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE marketplace_ledger_journals SET posted=1 WHERE id=1')
        self.db.rollback()

    def test_refund_appends_reversal_preserving_original(self):
        self.post()
        self.post(key='refund',entries=[('cash',-1000),('seller',940),('fees',60)])
        self.assertEqual(ledger.balances(self.db,'test'),{'cash':0,'seller':0,'fees':0})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],2)

    def test_fee_excludes_shipping_tax_and_owner_waiver_balances(self):
        q=quote(1000,shipping=500,tax=90)
        self.assertEqual(q['platform_fee'],60)
        self.post(entries=[('cash',q['total']),('seller',-(q['total']-q['platform_fee'])),('fees',-q['platform_fee'])])
        # A trusted owner waiver is represented as no platform fee entry. Authorization
        # stays in marketplace_catalog.shop_quote, not in this generic journal primitive.
        self.post(key='owner-waiver',entries=[('cash',1000),('seller',-1000)])
        self.assertEqual(ledger.balances(self.db,'test')['fees'],-60)

    def test_partial_refund_rounding_totals_exactly_original_fee(self):
        credited=0
        for refunded in range(1,1002):
            delta=commission_refund(refunded,1001,60,credited)
            self.assertGreaterEqual(delta,0)
            credited+=delta
        self.assertEqual(credited,60)

    def test_dedicated_connection_prevents_implicit_caller_commit(self):
        self.db.execute('CREATE TABLE unrelated(value INTEGER)')
        self.db.execute('INSERT INTO unrelated VALUES (1)')
        with self.assertRaises(stock.InventoryError): self.hold()
        with self.assertRaises(ledger.LedgerError): self.post()
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM unrelated').fetchone()[0],0)

    def test_missing_connection_foreign_keys_fails_closed(self):
        self.db.execute('PRAGMA foreign_keys=OFF')
        with self.assertRaisesRegex(stock.InventoryError,'foreign keys'): self.hold()
        with self.assertRaisesRegex(ledger.LedgerError,'foreign keys'): self.post()


class ConcurrencyTests(unittest.TestCase):
    def test_two_connections_cannot_sell_last_unit_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'stock.db')
            db=sqlite3.connect(path)
            stock.initialize(db)
            stock.set_stock(db,'test','shop','last',1,100)
            db.close()
            def attempt(buyer):
                connection=sqlite3.connect(path,timeout=5)
                connection.execute('PRAGMA foreign_keys=ON')
                try:
                    stock.reserve(connection,'test','shop',buyer,'request',[('last',1)],100)
                    return 'reserved'
                except stock.InventoryError as exc:
                    if str(exc) != 'insufficient stock':
                        raise
                    return 'sold out'
                finally:
                    connection.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,['buyer-a','buyer-b']))
            self.assertCountEqual(results,['reserved','sold out'])

    def test_duplicate_financial_event_posts_once_across_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'ledger.db')
            db=sqlite3.connect(path)
            ledger.initialize(db)
            ledger.create_account(db,'cash','test','platform','asset')
            ledger.create_account(db,'seller','test','shop','liability')
            db.close()
            def attempt(_):
                connection=sqlite3.connect(path,timeout=5)
                connection.execute('PRAGMA foreign_keys=ON')
                try:
                    return ledger.post(connection,'test','same-key','provider:event',[('cash',100),('seller',-100)],100)
                finally:
                    connection.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(attempt,range(2)))
            self.assertEqual(results[0],results[1])
            db=sqlite3.connect(path)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_ledger_journals').fetchone()[0],1)
            self.assertEqual(ledger.balances(db,'test'),{'cash':100,'seller':-100})
            db.close()


if __name__=='__main__':
    unittest.main()
