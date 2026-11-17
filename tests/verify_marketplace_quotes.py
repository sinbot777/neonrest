"""Complete quote service tests; address/shipping/tax resolvers are fixtures."""
from dataclasses import replace
import pathlib
import sqlite3
import sys
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_quotes as quotes
import marketplace_checkout as checkout
import marketplace_payments as payments
from verify_marketplace_checkout import fixture,FixturePolicy
from verify_marketplace_payments import OnboardingFixture,canonical,signed_event,SECRET


class QuoteServices:
    def __init__(self,db):
        self.db=db;self.version='v1';self.country='US';self.shipping=500;self.tax=90;self.expiry=1000
        self.hook=lambda: None
    def resolve_location(self,buyer,seller,reference):
        if reference!='address_fixture' or buyer!=2: raise quotes.QuoteError('address unavailable')
        return quotes.Location(buyer,seller,reference,self.version,'US',self.country)
    def quote_shipping(self,context,digest):
        assert not self.db.in_transaction
        self.hook()
        return quotes.Assessment('shipping','shipping_fixture','rate_fixture',digest,self.shipping,self.expiry)
    def quote_tax(self,context,digest):
        assert not self.db.in_transaction
        assert context['shipping']['amount_cents']==self.shipping
        return quotes.Assessment('tax','tax_fixture','calculation_fixture',digest,self.tax,self.expiry)


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.sku=fixture(self.db);quotes.initialize(self.db)
        self.order=checkout.create_order(self.db,'test',2,'shop-a','order',[(self.sku,1,0)],100,FixturePolicy)
        self.services=QuoteServices(self.db)
    def tearDown(self): self.db.close()
    def create(self,key='quote',now=101,buyer=2):
        return quotes.create_quote(self.db,buyer,self.order,'address_fixture',key,self.services,self.services,self.services,now,FixturePolicy)
    def get(self,q,now=102): return quotes.get_quote(self.db,2,q,self.services,now,FixturePolicy)
    def accept(self,q,now=102): return quotes.accept_quote(self.db,2,q,self.services,now,FixturePolicy)
    def update(self,sql): self.db.execute(sql);self.db.commit()

    def test_complete_total_preserves_item_only_fee_and_evidence(self):
        result=self.get(self.create());snapshot=result['snapshot']
        self.assertEqual((snapshot['subtotal_cents'],snapshot['shipping_cents'],snapshot['tax_cents'],snapshot['total_cents']),(1000,500,90,1590))
        self.assertEqual(snapshot['platform_fee_cents'],60)
        self.assertEqual(snapshot['tax_evidence']['source'],'tax_fixture')
        self.assertEqual(result['expires_at'],401)
        self.assertFalse(snapshot['payment_authorization_enabled'])

    def test_zero_is_explicit_missing_tax_is_rejected(self):
        self.services.tax=0
        self.assertEqual(self.get(self.create())['snapshot']['tax_cents'],0)
        self.services.quote_tax=lambda c,h: None
        with self.assertRaises(quotes.QuoteError): self.create(key='missing')

    def test_address_versions_foreign_owners_and_international_quotes_fail(self):
        q=self.create();self.services.version='v2'
        with self.assertRaises(quotes.QuoteError): self.accept(q)
        with self.assertRaises(quotes.QuoteError): self.get(q)
        self.services.country='CA'
        with self.assertRaises(quotes.QuoteError): self.create(key='international')
        with self.assertRaises(quotes.QuoteError): self.create(buyer=3)

    def test_shortest_source_or_reservation_expiry_wins(self):
        self.services.expiry=150
        self.assertEqual(self.get(self.create())['expires_at'],150)
        self.services.expiry=100
        with self.assertRaises(quotes.QuoteError): self.create(key='already-expired')

    def test_quote_cannot_outlive_stock_hold(self):
        q=self.create(now=950)
        self.assertEqual(self.get(q,now=951)['expires_at'],1000)
        with self.assertRaises(quotes.QuoteError): self.accept(q,now=1000)

    def test_listing_shop_terms_fee_changes_and_cancel_invalidate_quote(self):
        changes=["UPDATE seller_listings SET revision=1 WHERE id='a'", "UPDATE seller_shops SET revision=1 WHERE page_id='shop-a'", "UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'"]
        for sql in changes:
            q=self.create(key='quote-'+str(len(sql)))
            self.update(sql)
            with self.assertRaises(ValueError): self.accept(q)
            self.update("UPDATE seller_listings SET revision=0 WHERE id='a'")
            self.update("UPDATE seller_shops SET revision=0,owner_id=1 WHERE page_id='shop-a'")
        q=self.create(key='before-cancel')
        checkout.cancel_order(self.db,'test',2,self.order,102,FixturePolicy)
        with self.assertRaises(quotes.QuoteError): self.accept(q)

    def test_lookup_race_revalidates_before_quote_write(self):
        self.services.hook=lambda: self.update("UPDATE seller_listings SET revision=1 WHERE id='a'")
        with self.assertRaises(quotes.QuoteError): self.create()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_quotes').fetchone()[0],0)

    def test_resolver_cannot_change_calculation_context(self):
        def mutate(context,digest):
            context['subtotal_cents']=1
            return quotes.Assessment('shipping','fixture','rate',digest,500,1000)
        self.services.quote_shipping=mutate
        with self.assertRaises(quotes.QuoteError): self.create()

    def test_assessment_wrong_currency_context_or_invalid_money_rejected(self):
        original=self.services.quote_shipping
        for changes in [dict(currency='EUR'),dict(context_hash='wrong'),dict(amount_cents=True),dict(amount_cents=None),dict(environment='live')]:
            self.services.quote_shipping=lambda c,h,changes=changes: replace(original(c,h),**changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError): self.create()

    def test_consent_is_explicit_idempotent_and_one_quote_per_order(self):
        q=self.create()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_quote_acceptances').fetchone()[0],0)
        self.assertEqual(self.accept(q),q)
        self.assertEqual(self.accept(q),q)
        self.services.shipping=600
        another=self.create(key='new-rate')
        with self.assertRaises(quotes.QuoteError): self.accept(another)

    def test_idempotency_never_silently_requotes(self):
        q=self.create();self.services.shipping=900
        self.assertEqual(self.create(),q)
        self.assertEqual(self.get(q)['snapshot']['shipping_cents'],500)

    def test_snapshots_and_acceptance_cannot_be_changed_by_sql(self):
        q=self.create();self.accept(q)
        for sql in ["UPDATE marketplace_checkout_quotes SET snapshot='{}'",'DELETE FROM marketplace_checkout_quotes','UPDATE marketplace_checkout_quote_acceptances SET buyer_id=3']:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()

    def test_nonphysical_shipping_and_oversized_total_rejected(self):
        self.update("UPDATE seller_listings SET kind='digital' WHERE id='a'")
        other=checkout.create_order(self.db,'test',2,'shop-a','digital',[(self.sku,1,0)],100,FixturePolicy)
        self.order=other
        with self.assertRaises(quotes.QuoteError): self.create()
        self.services.shipping=0;self.services.tax=100_000_000
        with self.assertRaises(ValueError): self.create()

    def test_repeated_migration_preserves_quotes_and_consent(self):
        q=self.create();self.accept(q);quotes.initialize(self.db)
        self.assertEqual(self.get(q)['snapshot']['total_cents'],1590)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_quote_acceptances').fetchone()[0],1)

    def account(self):
        payments.initialize(self.db)
        scope=payments.Scope('stripe','platform_fixture')
        request=payments.begin_onboarding(self.db,1,'shop-a',scope,'onboard',101,FixturePolicy)
        return payments.complete_onboarding(self.db,1,request,OnboardingFixture(scope),101,FixturePolicy)

    def track(self,q,account):
        return payments.track_quoted_test_payment(self.db,2,q,account,'pi_fixture',self.services,103,FixturePolicy)

    def receive(self,q,amount=1590,metadata=None,now=104):
        payment=canonical(self.order,amount=amount,amount_received=amount,
            metadata=metadata or {'neonrest_order':self.order,'neonrest_quote':q})
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:payment)
        raw,sig=signed_event(now=now)
        return payments.receive_stripe(self.db,adapter,raw,sig,now,FixturePolicy)

    def test_complete_accepted_quote_binds_full_total_to_test_reconciliation(self):
        account=self.account();q=self.create();self.accept(q);attempt=self.track(q,account)
        row=self.db.execute('SELECT expected_amount_cents FROM marketplace_payment_test_attempts WHERE id=?',(attempt,)).fetchone()
        self.assertEqual(row[0],1590)
        self.assertEqual(self.receive(q)['outcome'],'observed_test')
        self.assertEqual(checkout.get_order(self.db,'test',2,self.order,104,FixturePolicy)['state'],'awaiting_payment')

    def test_unaccepted_or_changed_quote_cannot_create_expectation(self):
        account=self.account();q=self.create()
        with self.assertRaises(payments.PaymentError): self.track(q,account)
        self.accept(q);self.services.version='v2'
        with self.assertRaises(quotes.QuoteError): self.track(q,account)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_test_attempts').fetchone()[0],0)

    def test_subtotal_missing_quote_metadata_and_expired_quote_never_match(self):
        account=self.account();q=self.create();self.accept(q);self.track(q,account)
        self.assertEqual(self.receive(q,amount=1000)['reason'],'payment_binding_mismatch')
        self.assertEqual(self.receive(q,metadata={'neonrest_order':self.order})['reason'],'quote_binding_mismatch_or_expired')
        self.assertEqual(self.receive(q,now=401)['reason'],'quote_binding_mismatch_or_expired')

    def test_legacy_subtotal_expectation_cannot_be_rebound_to_a_complete_quote(self):
        account=self.account()
        payments.track_test_payment(self.db,2,self.order,account,'pi_fixture',101,FixturePolicy)
        q=self.create();self.accept(q)
        with self.assertRaises(payments.PaymentError): self.track(q,account)
        self.assertEqual(self.db.execute('SELECT expected_amount_cents FROM marketplace_payment_test_attempts').fetchone()[0],1000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_quote_links').fetchone()[0],0)

    def test_quote_binding_is_idempotent_immutable_and_cannot_downgrade(self):
        account=self.account();q=self.create();self.accept(q)
        attempt=self.track(q,account)
        self.assertEqual(self.track(q,account),attempt)
        with self.assertRaises(payments.PaymentError): payments.track_test_payment(self.db,2,self.order,account,'pi_fixture',104,FixturePolicy)
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE marketplace_payment_quote_links SET expires_at=9999')
        self.db.rollback()

    def test_quote_link_write_failure_rolls_back_the_payment_expectation(self):
        account=self.account();q=self.create();self.accept(q)
        self.db.execute("CREATE TRIGGER fail_link BEFORE INSERT ON marketplace_payment_quote_links BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.track(q,account)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_test_attempts').fetchone()[0],0)

    def test_listing_change_after_test_expectation_requires_review(self):
        account=self.account();q=self.create();self.accept(q);self.track(q,account)
        self.update("UPDATE seller_listings SET revision=1 WHERE id='a'")
        self.assertEqual(self.receive(q)['reason'],'quote_binding_mismatch_or_expired')

    def test_backup_restore_retains_quote_consent_and_full_total_binding(self):
        account=self.account();q=self.create();self.accept(q);attempt=self.track(q,account)
        restored=sqlite3.connect(':memory:');restored.row_factory=sqlite3.Row
        try:
            self.db.backup(restored)
            quotes.initialize(restored);payments.initialize(restored)
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(restored.execute('SELECT quote_id FROM marketplace_payment_quote_links WHERE attempt_id=?',(attempt,)).fetchone()[0],q)
            self.assertEqual(restored.execute('SELECT expected_amount_cents FROM marketplace_payment_test_attempts WHERE id=?',(attempt,)).fetchone()[0],1590)
        finally: restored.close()


if __name__=='__main__': unittest.main()
