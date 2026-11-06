"""Atomic fictional test settlement; signed fixtures, no real provider traffic."""
import concurrent.futures
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from cryptography.fernet import Fernet

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_addresses as addresses
import marketplace_checkout as checkout
import marketplace_inventory as inventory
import marketplace_ledger as ledger
import marketplace_payments as payments
import marketplace_quotes as quotes
import marketplace_settlement as settlement
from verify_marketplace_addresses import setup,ADDRESS
from verify_marketplace_checkout import FixturePolicy
from verify_marketplace_payments import OnboardingFixture,canonical,signed_event,SECRET
from verify_marketplace_quotes import QuoteServices


def prepare(db,key,waived=False):
    sku,store,destination,origin,resolver=setup(db,key)
    payments.initialize(db);settlement.initialize(db)
    services=QuoteServices(db)
    if waived:
        db.execute("INSERT INTO benefits VALUES ('shop-a',1)");db.commit()
    order=checkout.create_order(db,'test',2,'shop-a','order',[(sku,1,0)],100,FixturePolicy)
    quote=quotes.create_quote(db,2,order,destination['id'],'quote',resolver,services,services,101,FixturePolicy)
    quotes.accept_quote(db,2,quote,resolver,102,FixturePolicy)
    scope=payments.Scope('stripe','platform_fixture')
    request=payments.begin_onboarding(db,1,'shop-a',scope,'onboard',102,FixturePolicy)
    account=payments.complete_onboarding(db,1,request,OnboardingFixture(scope),102,FixturePolicy)
    attempt=payments.track_quoted_test_payment(db,2,quote,account,'pi_fixture',resolver,103,FixturePolicy)
    payment=canonical(order,amount=1590,amount_received=1590,metadata={'neonrest_order':order,'neonrest_quote':quote})
    adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:payment)
    raw,sig=signed_event(now=104)
    receipt=payments.receive_stripe(db,adapter,raw,sig,104,FixturePolicy)['receipt_id']
    return dict(sku=sku,store=store,destination=destination,origin=origin,resolver=resolver,order=order,
        quote=quote,account=account,attempt=attempt,adapter=adapter,receipt=receipt,payment=payment)


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.key=Fernet.generate_key();self.db=sqlite3.connect(':memory:');self.ctx=prepare(self.db,self.key)
    def tearDown(self): self.db.close()
    def settle(self,receipt=None,now=105):
        return settlement.settle_test_receipt(self.db,receipt or self.ctx['receipt'],self.ctx['resolver'],now,FixturePolicy)
    def count(self,table): return self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def change(self,sql,args=()): self.db.execute(sql,args);self.db.commit()
    def state(self,now=105): return checkout.get_order(self.db,'test',2,self.ctx['order'],now,FixturePolicy)['state']
    def stock(self): return self.db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(self.ctx['sku'],)).fetchone()[0]
    def no_effects(self):
        self.assertEqual(self.count('marketplace_test_settlements'),0)
        self.assertEqual(self.count('marketplace_inventory_consumptions'),0)
        self.assertEqual(self.count('marketplace_ledger_journals'),0)
        self.assertEqual(self.stock(),3)

    def test_success_consumes_once_and_allocates_complete_total(self):
        result=self.settle();alloc=result['allocation']
        self.assertEqual(self.state(),'test_settled');self.assertEqual(self.stock(),2)
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.ctx['sku'],105),2)
        self.assertEqual((alloc['total_cents'],alloc['seller_obligation_cents'],alloc['platform_fee_cents'],alloc['tax_cents']),(1590,1440,60,90))
        self.assertIsNone(alloc['processor_cost_cents']);self.assertFalse(result['fulfillment_enabled'])
        balances=ledger.balances(self.db,'test');self.assertEqual(sum(balances.values()),0)
        self.assertEqual(sorted(balances.values()),[-1440,-90,-60,1590])
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_duplicate_delivery_and_retry_after_quote_expiry_do_not_repeat_effects(self):
        first=self.settle();self.assertEqual(first,self.settle(now=5000))
        raw,sig=signed_event(now=106)
        result=payments.receive_stripe(self.db,self.ctx['adapter'],raw,sig,106,FixturePolicy)
        self.assertEqual(first,self.settle(result['receipt_id'],107))
        for table in ('marketplace_test_settlements','marketplace_inventory_consumptions','marketplace_ledger_journals'):
            self.assertEqual(self.count(table),1)
        self.assertEqual(self.stock(),2)

    def test_new_success_event_for_same_winner_is_acknowledged_after_expiry(self):
        expected=self.settle()
        raw,sig=signed_event(event_id='evt_later_success',now=2000)
        result=payments.receive_stripe(self.db,self.ctx['adapter'],raw,sig,2000,FixturePolicy)
        self.assertEqual((result['outcome'],result['reason']),('observed_test','already_test_settled'))
        self.assertEqual(self.settle(result['receipt_id'],2000),expected)
        self.assertEqual(self.count('marketplace_ledger_journals'),1)
        self.assertEqual(self.count('marketplace_test_settlement_reviews'),0)

    def test_failed_final_write_rolls_back_journal_stock_and_order(self):
        self.change("CREATE TRIGGER force_settlement_failure BEFORE INSERT ON marketplace_test_settlements BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.settle()
        self.no_effects();self.assertEqual(self.count('marketplace_ledger_accounts'),0)
        self.assertEqual(self.state(),'awaiting_payment')
        self.change('DROP TRIGGER force_settlement_failure');self.assertEqual(self.settle()['outcome'],'test_settled')

    def test_failed_stock_write_rolls_back_journal(self):
        self.change("CREATE TRIGGER force_stock_failure BEFORE UPDATE ON marketplace_inventory_stock BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.settle()
        self.no_effects()

    def test_failed_journal_seal_rolls_back_everything(self):
        self.change("CREATE TRIGGER force_journal_failure BEFORE UPDATE ON marketplace_ledger_journals BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.settle()
        self.no_effects()

    def test_other_reservation_stays_reserved_without_double_subtraction(self):
        second=checkout.create_order(self.db,'test',3,'shop-a','other',[(self.ctx['sku'],1,0)],103,FixturePolicy)
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.ctx['sku'],104),1)
        self.settle();self.assertEqual(self.stock(),2)
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.ctx['sku'],105),1)
        self.assertEqual(checkout.get_order(self.db,'test',3,second,105,FixturePolicy)['state'],'awaiting_payment')

    def test_cancellation_after_settlement_is_noop_and_expiry_does_not_restore_stock(self):
        self.settle()
        self.assertEqual(checkout.cancel_order(self.db,'test',2,self.ctx['order'],2000,FixturePolicy),'test_settled')
        self.assertEqual(checkout.expire_orders(self.db,'test',2000),0)
        self.assertEqual(self.state(2000),'test_settled');self.assertEqual(self.stock(),2)
        hold=self.db.execute('SELECT hold_id FROM marketplace_checkout_orders').fetchone()[0]
        with self.assertRaises(inventory.InventoryError): inventory.release(self.db,'test','2',hold,2000)
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE marketplace_inventory_holds SET state='released' WHERE id=?",(hold,))
        self.db.rollback()

    def test_listing_sync_cannot_silently_restore_sold_stock(self):
        self.settle()
        with self.assertRaises(checkout.CheckoutError): checkout.sync_listing(self.db,'test',1,'shop-a','a',0,106,FixturePolicy)
        self.assertEqual(self.stock(),2)
        inventory.set_stock(self.db,'test','shop-a',self.ctx['sku'],4,106)
        self.assertEqual(self.stock(),4)

    def test_canceled_or_expired_order_requires_review_and_never_settles(self):
        checkout.cancel_order(self.db,'test',2,self.ctx['order'],105,FixturePolicy)
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()
        self.assertEqual(self.settle(now=2000)['outcome'],'needs_review')
        self.assertEqual(self.count('marketplace_test_settlement_reviews'),1)

    def test_quote_expired_before_settlement_requires_review(self):
        self.assertEqual(self.settle(now=401)['outcome'],'needs_review');self.no_effects()

    def test_destination_edit_after_observation_blocks_settlement(self):
        self.ctx['store'].edit(2,self.ctx['destination']['id'],0,dict(ADDRESS,line1='New fictional road'),105)
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()

    def test_buyer_revocation_blocks_settlement(self):
        self.change('UPDATE users SET eligible=0 WHERE id=2')
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()

    def test_seller_transfer_or_suspension_blocks_settlement(self):
        self.change("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'")
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()

    def test_capability_revocation_blocks_settlement(self):
        self.change('UPDATE marketplace_payment_accounts SET charges_enabled=0')
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()

    def test_stale_listing_terms_block_settlement(self):
        self.change("UPDATE seller_listings SET revision=1 WHERE id='a'")
        self.assertEqual(self.settle()['outcome'],'needs_review');self.no_effects()

    def test_unobserved_pending_failed_or_reviewed_receipt_not_accepted(self):
        for state in ('tracking','pending','failed','canceled'):
            # Use a SAVEPOINT fixture after removing the success transition guard
            # only in this isolated fixture to simulate earlier canonical states.
            self.change('DROP TRIGGER IF EXISTS marketplace_payment_attempt_identity')
            self.change('UPDATE marketplace_payment_test_attempts SET observed_status=?',(state,))
            with self.subTest(state=state),self.assertRaises(settlement.SettlementError): self.settle()
        self.no_effects()

    def test_receipt_review_and_missing_identifier_cannot_settle(self):
        self.change("UPDATE marketplace_payment_events SET outcome='needs_review'")
        with self.assertRaises(settlement.SettlementError): self.settle()
        for bad in (True,'1',-1,999):
            with self.subTest(value=bad),self.assertRaises(settlement.SettlementError):
                settlement.settle_test_receipt(self.db,bad,self.ctx['resolver'],105,FixturePolicy)
        self.no_effects()

    def test_native_same_connection_resolver_and_server_clock_are_required(self):
        with self.assertRaises(settlement.SettlementError): settlement.settle_test_receipt(self.db,self.ctx['receipt'],QuoteServices(self.db),105,FixturePolicy)
        with self.assertRaises(settlement.SettlementError): self.settle(now=103)
        with self.assertRaises(ValueError): self.settle(now=True)
        self.no_effects()

    def test_ledger_account_identity_conflict_is_not_ignored(self):
        ledger.create_account(self.db,'qa-fee','live','platform','income')
        with self.assertRaises(settlement.SettlementError): self.settle()
        self.no_effects()

    def test_migration_backup_restore_preserves_settlement_and_effects(self):
        expected=self.settle();checkout.initialize(self.db);settlement.initialize(self.db)
        self.assertEqual(self.settle(now=2000),expected)
        restored=sqlite3.connect(':memory:');self.db.backup(restored);restored.row_factory=sqlite3.Row;restored.execute('PRAGMA foreign_keys=ON')
        try:
            resolver=addresses.AddressResolver(addresses.AddressStore(restored,addresses.FernetVault([self.key]),FixturePolicy))
            self.assertEqual(settlement.settle_test_receipt(restored,self.ctx['receipt'],resolver,2000,FixturePolicy),expected)
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: restored.close()

    def test_settlement_and_consumed_lines_are_immutable(self):
        self.settle()
        for sql in ('DELETE FROM marketplace_test_settlements','UPDATE marketplace_test_settlements SET settled_at=999',
                    'DELETE FROM marketplace_inventory_consumptions','UPDATE marketplace_inventory_consumptions SET consumed_at=999',
                    'DELETE FROM marketplace_inventory_hold_lines',"UPDATE marketplace_checkout_orders SET state='canceled'"):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()
        self.assertEqual(self.stock(),2)

    def test_quote_cannot_be_reused_after_settlement(self):
        self.settle()
        with self.assertRaises(ValueError): quotes.get_quote(self.db,2,self.ctx['quote'],self.ctx['resolver'],106,FixturePolicy)
        self.assertEqual(self.count('marketplace_test_settlements'),1)

    def test_later_different_success_is_reviewed_instead_of_consuming_twice(self):
        # Model an operator-supported account rollover while both payments were
        # already in flight. Both observations still traverse signature checks.
        first=self.ctx['account']
        self.change('DELETE FROM marketplace_payment_shop_links')
        scope=payments.Scope('stripe','platform_fixture')
        request=payments.begin_onboarding(self.db,1,'shop-a',scope,'rollover',104,FixturePolicy)
        account=payments.complete_onboarding(self.db,1,request,OnboardingFixture(scope,account='acct_second'),104,FixturePolicy)
        attempt=payments.track_quoted_test_payment(self.db,2,self.ctx['quote'],account,'pi_second',self.ctx['resolver'],104,FixturePolicy)
        payment=dict(self.ctx['payment'],id='pi_second')
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:payment)
        raw,sig=signed_event(event_id='evt_second',account='acct_second',payment='pi_second',now=104)
        second=payments.receive_stripe(self.db,adapter,raw,sig,104,FixturePolicy)['receipt_id']
        self.change('DELETE FROM marketplace_payment_shop_links')
        self.change("INSERT INTO marketplace_payment_shop_links VALUES ('test','shop-a','stripe',1,?)",(first,))
        self.settle();result=self.settle(second,106)
        self.assertEqual(result['reason'],'another_winning_payment');self.assertEqual(self.stock(),2)
        self.assertEqual(self.count('marketplace_ledger_journals'),1)
        self.assertEqual(self.settle(second,2000),result)

    def test_owner_exemption_preserved_in_test_allocation(self):
        db=sqlite3.connect(':memory:')
        try:
            ctx=prepare(db,self.key,waived=True)
            result=settlement.settle_test_receipt(db,ctx['receipt'],ctx['resolver'],105,FixturePolicy)
            self.assertEqual(result['allocation']['platform_fee_cents'],0)
            self.assertEqual(result['allocation']['seller_obligation_cents'],1500)
            self.assertEqual(result['allocation']['fee_version'],'2026-10-28-owner-comp-v1')
            self.assertNotIn('qa-fee',ledger.balances(db,'test'))
        finally: db.close()

    def test_subtotal_only_observation_cannot_settle(self):
        from verify_marketplace_payments import setup_payment
        db=sqlite3.connect(':memory:')
        try:
            ctx=setup_payment(db);settlement.initialize(db)
            adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:canonical(ctx['order']))
            raw,sig=signed_event()
            receipt=payments.receive_stripe(db,adapter,raw,sig,101,FixturePolicy)['receipt_id']
            resolver=addresses.AddressResolver(addresses.AddressStore(db,addresses.FernetVault([self.key]),FixturePolicy))
            with self.assertRaises(settlement.SettlementError): settlement.settle_test_receipt(db,receipt,resolver,102,FixturePolicy)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0],0)
        finally: db.close()

    def test_batch_recovers_success_without_webhook_redelivery(self):
        results=settlement.run_ready(self.db,self.ctx['resolver'],105,policy=FixturePolicy)
        self.assertEqual(len(results),1);self.assertEqual(results[0]['outcome'],'test_settled')
        self.assertEqual(settlement.run_ready(self.db,self.ctx['resolver'],2000,policy=FixturePolicy),[])
        self.assertEqual(self.stock(),2)

    def test_batch_validates_bounds_and_failure_remains_recoverable(self):
        for limit in (0,101,True):
            with self.assertRaises(settlement.SettlementError): settlement.run_ready(self.db,self.ctx['resolver'],105,limit=limit,policy=FixturePolicy)
        self.change("CREATE TRIGGER fail_batch BEFORE INSERT ON marketplace_test_settlements BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError): settlement.run_ready(self.db,self.ctx['resolver'],105,policy=FixturePolicy)
        self.no_effects();self.change('DROP TRIGGER fail_batch')
        self.assertEqual(settlement.run_ready(self.db,self.ctx['resolver'],106,policy=FixturePolicy)[0]['outcome'],'test_settled')

    def test_expiring_batch_clock_does_not_settle_stale_quote(self):
        results=settlement.run_ready(self.db,self.ctx['resolver'],105,policy=FixturePolicy,clock=lambda:401)
        self.assertEqual(results[0]['outcome'],'needs_review');self.no_effects()

    def test_foreign_key_disabled_connection_refuses_settlement(self):
        self.db.execute('PRAGMA foreign_keys=OFF')
        with self.assertRaises(inventory.InventoryError): self.settle()
        self.db.execute('PRAGMA foreign_keys=ON');self.no_effects()

    def test_paid_order_read_still_rejects_unrelated_buyer(self):
        self.settle()
        with self.assertRaises(checkout.CheckoutError): checkout.get_order(self.db,'test',3,self.ctx['order'],106,FixturePolicy)
        self.assertEqual(checkout.get_order(self.db,'test',1,self.ctx['order'],106,FixturePolicy)['state'],'test_settled')

    def test_cancellation_racing_settlement_never_restores_consumed_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'qa.sqlite');db=sqlite3.connect(path);ctx=prepare(db,self.key);db.close()
            def work(action):
                conn=sqlite3.connect(path,timeout=5);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
                try:
                    if action=='cancel': return checkout.cancel_order(conn,'test',2,ctx['order'],105,FixturePolicy)
                    resolver=addresses.AddressResolver(addresses.AddressStore(conn,addresses.FernetVault([self.key]),FixturePolicy))
                    return settlement.settle_test_receipt(conn,ctx['receipt'],resolver,105,FixturePolicy)
                finally: conn.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(work,['cancel','settle']))
            conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row
            try:
                count=conn.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0]
                self.assertEqual(conn.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(ctx['sku'],)).fetchone()[0],2 if count else 3)
                self.assertEqual(checkout.get_order(conn,'test',2,ctx['order'],2000,FixturePolicy)['state'],'test_settled' if count else 'canceled')
            finally: conn.close()

    def test_separate_connections_racing_settle_one_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(pathlib.Path(tmp)/'qa.sqlite');db=sqlite3.connect(path);ctx=prepare(db,self.key);db.close()
            def work(_):
                conn=sqlite3.connect(path,timeout=5);conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
                try:
                    resolver=addresses.AddressResolver(addresses.AddressStore(conn,addresses.FernetVault([self.key]),FixturePolicy))
                    return settlement.settle_test_receipt(conn,ctx['receipt'],resolver,105,FixturePolicy)
                finally: conn.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(work,range(4)))
            self.assertTrue(all(r==results[0] for r in results))
            conn=sqlite3.connect(path)
            try:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM marketplace_test_settlements').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(ctx['sku'],)).fetchone()[0],2)
            finally: conn.close()


if __name__=='__main__': unittest.main()
