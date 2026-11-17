"""Real encryption and native address/shipping/quote integration, fictional data."""
import concurrent.futures
from dataclasses import asdict
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
import marketplace_quotes as quotes
import marketplace_shipping as shipping
import marketplace_payments as payments
from verify_marketplace_checkout import fixture,FixturePolicy
from verify_marketplace_payments import OnboardingFixture,canonical,signed_event,SECRET

ADDRESS=dict(recipient='FixturePrivateRecipientX',line1='42 Example Privacy Way',city='FixturePrivateCityX',state='OR',postal_code='00123',country='US')


def setup(db,key):
    sku=fixture(db);addresses.initialize(db);shipping.initialize(db);quotes.initialize(db)
    store=addresses.AddressStore(db,addresses.FernetVault([key]),FixturePolicy)
    destination=store.create(2,'destination',ADDRESS,'destination',100)
    origin=store.create(1,'origin',dict(ADDRESS,line1='81 Example Origin Road'),'origin',100,shop_id='shop-a')
    store.set_origin(1,'shop-a',origin['id'],100)
    resolver=addresses.AddressResolver(store)
    return sku,store,destination,origin,resolver


class AddressTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.key=Fernet.generate_key()
        self.sku,self.store,self.destination,self.origin,self.resolver=setup(self.db,self.key)
    def tearDown(self): self.db.close()
    def read(self,uid=2,version=None): return self.store.read(uid,self.destination['id'],101,version)
    def location(self): return self.resolver.resolve_location(2,'shop-a',self.destination['id'])

    def test_real_encryption_roundtrip_leading_zip_and_no_plaintext_in_dump(self):
        result=self.read()
        self.assertEqual(result['address']['postal_code'],'00123')
        dump='\n'.join(self.db.iterdump())
        for value in [ADDRESS['recipient'],ADDRESS['line1'],ADDRESS['city'],'81 Example Origin Road']:
            self.assertNotIn(value,dump)
        token=self.db.execute('SELECT ciphertext FROM marketplace_address_versions LIMIT 1').fetchone()[0]
        self.assertIs(type(token),bytes)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_missing_invalid_keys_and_wrong_key_never_fall_back_to_plaintext(self):
        for keys in [None,[],[b'bad-key'],['not-bytes']]:
            with self.subTest(keys=keys),self.assertRaises(addresses.AddressError): addresses.FernetVault(keys)
        wrong=addresses.AddressStore(self.db,addresses.FernetVault([Fernet.generate_key()]),FixturePolicy)
        with self.assertRaises(addresses.AddressError) as error: wrong.read(2,self.destination['id'],101)
        self.assertNotIn(ADDRESS['line1'],str(error.exception))

    def test_unrelated_user_minor_and_restricted_account_cannot_read_address(self):
        for uid in [1,3,4,5,True]:
            with self.subTest(uid=uid),self.assertRaises(ValueError): self.read(uid)
        self.assertEqual(self.store.references(3),[])

    def test_address_references_and_audit_exclude_contact_fields(self):
        self.read()
        result=str(self.store.references(2))
        events=str([tuple(r) for r in self.db.execute('SELECT * FROM marketplace_address_events')])
        for value in [ADDRESS['recipient'],ADDRESS['line1'],ADDRESS['city']]:
            self.assertNotIn(value,result);self.assertNotIn(value,events)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM marketplace_address_events WHERE action='view'").fetchone()[0],1)

    def test_edits_append_history_are_idempotent_and_invalidate_location(self):
        before=self.location();changed=dict(ADDRESS,line1='99 Example New Street')
        edit=self.store.edit(2,self.destination['id'],0,changed,102)
        self.assertEqual(self.store.edit(2,self.destination['id'],0,changed,103),edit)
        self.assertEqual(self.read(version=self.destination['version'])['address']['line1'],ADDRESS['line1'])
        self.assertEqual(self.read()['address']['line1'],changed['line1'])
        self.assertNotEqual(before.version,self.location().version)
        with self.assertRaises(addresses.AddressError): self.store.edit(2,self.destination['id'],0,ADDRESS,104)

    def test_create_idempotency_compares_encrypted_original_without_plaintext_hash(self):
        created=self.store.create(2,'destination',ADDRESS,'destination',101)
        self.assertEqual(created,self.destination)
        self.store.edit(2,self.destination['id'],0,dict(ADDRESS,line1='New Example Road'),102)
        self.assertEqual(self.store.create(2,'destination',ADDRESS,'destination',103),self.destination)
        with self.assertRaises(addresses.AddressError): self.store.create(2,'destination',dict(ADDRESS,line1='Other Example Road'),'destination',104)

    def test_ciphertext_swapping_and_corruption_are_rejected(self):
        other=self.store.create(2,'destination',dict(ADDRESS,line1='Other Street'),'other',100)
        token=self.db.execute('SELECT ciphertext FROM marketplace_address_versions WHERE id=?',(other['version'],)).fetchone()[0]
        self.db.execute('UPDATE marketplace_address_versions SET ciphertext=? WHERE id=?',(token,self.destination['version']));self.db.commit()
        with self.assertRaises(addresses.AddressError): self.read()
        self.db.execute('UPDATE marketplace_address_versions SET ciphertext=? WHERE id=?',(b'invalid',self.destination['version']));self.db.commit()
        with self.assertRaises(addresses.AddressError): self.read()

    def test_rotation_preserves_semantic_version_and_allows_retiring_old_key(self):
        before=self.location();new=Fernet.generate_key()
        rotating=addresses.AddressStore(self.db,addresses.FernetVault([new,self.key]),FixturePolicy)
        rotating.rotate_version(2,self.destination['id'],self.destination['version'],102)
        new_only=addresses.AddressStore(self.db,addresses.FernetVault([new]),FixturePolicy)
        self.assertEqual(new_only.read(2,self.destination['id'],103)['address']['postal_code'],'00123')
        with self.assertRaises(addresses.AddressError): self.read()
        # The origin remains on the old key; dual-key resolver retains access.
        self.assertEqual(addresses.AddressResolver(rotating).resolve_location(2,'shop-a',self.destination['id']),before)

    def test_archive_restore_does_not_revive_old_location_version(self):
        before=self.location()
        revision=self.store.set_archived(2,self.destination['id'],0,True,102)
        with self.assertRaises(addresses.AddressError): self.location()
        self.assertEqual(self.read()['address']['postal_code'],'00123')
        self.store.set_archived(2,self.destination['id'],revision,False,103)
        self.assertNotEqual(before.version,self.location().version)

    def test_origin_is_owner_only_and_does_not_transfer_with_shop(self):
        with self.assertRaises(addresses.AddressError): self.store.create(3,'origin',ADDRESS,'not-owner',101,shop_id='shop-a')
        self.db.execute("UPDATE seller_shops SET owner_id=3 WHERE page_id='shop-a'");self.db.commit()
        with self.assertRaises(addresses.AddressError): self.location()
        with self.assertRaises(addresses.AddressError): self.store.read(3,self.origin['id'],102)
        self.assertEqual(self.store.read(1,self.origin['id'],102)['address']['country'],'US')

    def test_private_calculation_handoff_is_version_bound_and_minimized(self):
        location=self.location()
        payload=self.resolver.calculation_addresses(2,'shop-a',self.destination['id'],location.version)
        self.assertEqual(payload['destination']['postal_code'],'00123')
        self.assertNotIn('recipient',payload['destination']);self.assertNotIn('company',payload['origin'])
        with self.assertRaises(addresses.AddressError): self.resolver.calculation_addresses(2,'shop-a',self.destination['id'],'wrong')

    def test_address_validation_blocks_extra_contact_fields_controls_and_unsupported_regions(self):
        cases=[dict(ADDRESS,postal_code=123),dict(ADDRESS,line1='line\ninjection'),dict(ADDRESS,country='CA'),dict(ADDRESS,state='PR'),dict(ADDRESS,email='not-collected@example.invalid')]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(addresses.AddressError): addresses.normalize(value)

    def test_sql_cannot_reassign_owners_versions_or_environment(self):
        for sql in ['UPDATE marketplace_address_books SET owner_id=3',"UPDATE marketplace_address_books SET environment='live'",'UPDATE marketplace_address_versions SET number=50','DELETE FROM marketplace_address_versions']:
            with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError): self.db.execute(sql)
            self.db.rollback()

    def test_encryption_failure_rolls_back_all_new_records(self):
        old=self.store.vault.seal
        def fail(_): raise addresses.AddressError('simulated encryption failure')
        self.store.vault.seal=fail
        with self.assertRaises(addresses.AddressError): self.store.create(2,'destination',ADDRESS,'failure',102)
        self.store.vault.seal=old
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_address_books').fetchone()[0],2)

    def test_backup_restore_requires_separate_key_and_preserves_versions(self):
        restored=sqlite3.connect(':memory:');restored.row_factory=sqlite3.Row
        try:
            self.db.backup(restored);addresses.initialize(restored)
            store=addresses.AddressStore(restored,addresses.FernetVault([self.key]),FixturePolicy)
            self.assertEqual(store.read(2,self.destination['id'],102)['address']['postal_code'],'00123')
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: restored.close()


class ShippingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.key=Fernet.generate_key()
        self.sku,self.store,self.destination,self.origin,self.addresses=setup(self.db,self.key)
        shipping.save_profile(self.db,1,'shop-a',0,300,100,600,True,100,FixturePolicy)
        self.resolver=shipping.ManualShippingResolver(self.addresses,lambda:101)
        self.order=checkout.create_order(self.db,'test',2,'shop-a','order',[(self.sku,2,0)],100,FixturePolicy)
        outer=self
        class TaxFixture:
            def quote_tax(self,context,digest):
                location=context['location']
                handoff=outer.resolver.calculation_addresses(context['buyer_id'],context['seller_ref'],location['reference'],location['version'])
                assert handoff['destination']['postal_code']=='00123'
                assert 'recipient' not in handoff['destination']
                assert context['shipping']['amount_cents']==500
                return quotes.Assessment('tax','fictional_tax_fixture','test_calc',digest,90,400)
        self.tax=TaxFixture()
    def tearDown(self): self.db.close()
    def quote(self):
        return quotes.create_quote(self.db,2,self.order,self.destination['id'],'quote',self.resolver,self.resolver,self.tax,101,FixturePolicy)

    def test_native_encrypted_addresses_and_fixed_shipping_produce_complete_quote(self):
        q=self.quote();result=quotes.get_quote(self.db,2,q,self.resolver,102,FixturePolicy)
        self.assertEqual(result['snapshot']['total_cents'],2590)
        self.assertEqual(result['snapshot']['platform_fee_cents'],120)
        self.assertTrue(result['snapshot']['location_snapshot_bound'])
        self.assertEqual(result['snapshot']['shipping_evidence']['source'],'manual_domestic_v1')
        raw=self.db.execute('SELECT snapshot FROM marketplace_checkout_quotes WHERE id=?',(q,)).fetchone()[0]
        self.assertNotIn(ADDRESS['line1'],raw);self.assertNotIn(ADDRESS['recipient'],raw)
        quotes.accept_quote(self.db,2,q,self.resolver,102,FixturePolicy)

    def test_retained_quote_binding_recovers_exact_prior_destination_after_edit(self):
        q=self.quote();data=quotes.get_quote(self.db,2,q,self.resolver,102,FixturePolicy)
        binding=data['snapshot']['location']['version']
        self.store.edit(2,self.destination['id'],0,dict(ADDRESS,line1='99 New Example Street'),103)
        with self.assertRaises(ValueError): quotes.accept_quote(self.db,2,q,self.resolver,104,FixturePolicy)
        previous=self.addresses.read_own_snapshot_destination(2,binding,104)
        self.assertEqual(previous['version'],self.destination['version'])
        self.assertEqual(previous['address']['line1'],ADDRESS['line1'])
        with self.assertRaises(ValueError): self.addresses.read_own_snapshot_destination(3,binding,104)

    def test_profile_origin_changes_and_disabled_rates_invalidate_pending_quotes(self):
        q=self.quote()
        shipping.save_profile(self.db,1,'shop-a',1,400,100,600,True,102,FixturePolicy)
        with self.assertRaises(ValueError): quotes.accept_quote(self.db,2,q,self.resolver,103,FixturePolicy)
        shipping.save_profile(self.db,1,'shop-a',2,400,100,600,False,104,FixturePolicy)
        with self.assertRaises(shipping.ShippingError): self.resolver.resolve_location(2,'shop-a',self.destination['id'])

    def test_fixed_charge_is_combined_per_order_capped_and_zero_for_digital(self):
        location=self.resolver.resolve_location(2,'shop-a',self.destination['id'])
        context=dict(environment='test',buyer_id=2,seller_ref='shop-a',location=asdict(location),lines=[dict(kind='physical',quantity=9)])
        self.assertEqual(self.resolver.quote_shipping(context,'fixture').amount_cents,600)
        context['lines']=[dict(kind='digital',quantity=9)]
        self.assertEqual(self.resolver.quote_shipping(context,'fixture').amount_cents,0)

    def test_owner_only_profiles_stale_writes_and_explicit_free_shipping(self):
        with self.assertRaises(shipping.ShippingError): shipping.save_profile(self.db,3,'shop-a',1,0,0,None,True,102,FixturePolicy)
        with self.assertRaises(shipping.ShippingError): shipping.save_profile(self.db,1,'shop-a',0,400,100,None,True,102,FixturePolicy)
        shipping.save_profile(self.db,1,'shop-a',1,0,0,None,True,102,FixturePolicy)
        location=self.resolver.resolve_location(2,'shop-a',self.destination['id'])
        context=dict(environment='test',buyer_id=2,seller_ref='shop-a',location=asdict(location),lines=[dict(kind='physical',quantity=1)])
        self.assertEqual(self.resolver.quote_shipping(context,'fixture').amount_cents,0)

    def test_snapshot_and_quote_roll_back_if_tax_callback_changes_address(self):
        outer=self
        class ChangedTax:
            def quote_tax(self,context,digest):
                outer.store.edit(2,outer.destination['id'],0,dict(ADDRESS,line1='New Example Street'),102)
                return quotes.Assessment('tax','fixture','test_calc',digest,90,400)
        self.tax=ChangedTax()
        with self.assertRaises(ValueError): self.quote()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_quotes').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_address_snapshots').fetchone()[0],0)

    def test_rotation_preserves_complete_quote_but_missing_tax_never_becomes_zero(self):
        q=self.quote();self.store.rotate_version(2,self.destination['id'],self.destination['version'],102)
        quotes.accept_quote(self.db,2,q,self.resolver,103,FixturePolicy)
        self.tax.quote_tax=lambda context,digest:None
        with self.assertRaises(quotes.QuoteError):
            quotes.create_quote(self.db,2,self.order,self.destination['id'],'missing-tax',self.resolver,self.resolver,self.tax,104,FixturePolicy)

    def test_encrypted_quote_snapshot_and_shipping_versions_survive_restore(self):
        q=self.quote();quotes.accept_quote(self.db,2,q,self.resolver,102,FixturePolicy)
        restored=sqlite3.connect(':memory:');restored.row_factory=sqlite3.Row
        try:
            self.db.backup(restored);addresses.initialize(restored);shipping.initialize(restored);quotes.initialize(restored)
            store=addresses.AddressStore(restored,addresses.FernetVault([self.key]),FixturePolicy)
            resolver=shipping.ManualShippingResolver(addresses.AddressResolver(store),lambda:103)
            self.assertEqual(quotes.get_quote(restored,2,q,resolver,103,FixturePolicy)['snapshot']['total_cents'],2590)
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally: restored.close()

    def account(self):
        payments.initialize(self.db);scope=payments.Scope('stripe','platform_fixture')
        request=payments.begin_onboarding(self.db,1,'shop-a',scope,'onboarding',101,FixturePolicy)
        return payments.complete_onboarding(self.db,1,request,OnboardingFixture(scope),101,FixturePolicy)

    def racing_resolver(self):
        outer=self
        class Race:
            changed=False
            def resolve_location(self,buyer,seller,reference):
                location=outer.resolver.resolve_location(buyer,seller,reference)
                if not self.changed:
                    self.changed=True
                    outer.store.edit(2,outer.destination['id'],0,dict(ADDRESS,line1='88 Racing Example Street'),102)
                return location
            def assert_current_location(self,buyer,seller,location):
                outer.resolver.assert_current_location(buyer,seller,location)
        return Race()

    def test_address_change_between_resolution_and_consent_is_rechecked_under_lock(self):
        q=self.quote()
        with self.assertRaises(ValueError): quotes.accept_quote(self.db,2,q,self.racing_resolver(),103,FixturePolicy)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_checkout_quote_acceptances').fetchone()[0],0)

    def test_address_change_between_resolution_and_payment_binding_cannot_create_attempt(self):
        account=self.account();q=self.quote();quotes.accept_quote(self.db,2,q,self.resolver,102,FixturePolicy)
        with self.assertRaises(ValueError): payments.track_quoted_test_payment(self.db,2,q,account,'pi_fixture',self.racing_resolver(),103,FixturePolicy)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM marketplace_payment_test_attempts').fetchone()[0],0)

    def test_native_quote_consent_and_full_total_test_payment_reconcile_without_fulfillment(self):
        account=self.account();q=self.quote();quotes.accept_quote(self.db,2,q,self.resolver,102,FixturePolicy)
        attempt=payments.track_quoted_test_payment(self.db,2,q,account,'pi_fixture',self.resolver,103,FixturePolicy)
        payment=canonical(self.order,amount=2590,amount_received=2590,metadata={'neonrest_order':self.order,'neonrest_quote':q})
        adapter=payments.StripeTestWebhookAdapter('platform_fixture',[SECRET],lambda a,p:payment)
        raw,signature=signed_event(now=104)
        self.assertEqual(payments.receive_stripe(self.db,adapter,raw,signature,104,FixturePolicy)['outcome'],'observed_test')
        self.assertEqual(self.db.execute('SELECT expected_amount_cents FROM marketplace_payment_test_attempts WHERE id=?',(attempt,)).fetchone()[0],2590)
        self.assertEqual(checkout.get_order(self.db,'test',2,self.order,104,FixturePolicy)['state'],'awaiting_payment')
        self.assertEqual(inventory.available(self.db,'test','shop-a',self.sku,104),1)


class AddressConcurrencyTests(unittest.TestCase):
    def test_two_edits_with_same_revision_cannot_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(pathlib.Path(directory)/'addresses.db');key=Fernet.generate_key()
            db=sqlite3.connect(path);_,_,destination,_,_=setup(db,key);db.close()
            def edit(number):
                db=sqlite3.connect(path,timeout=5);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
                store=addresses.AddressStore(db,addresses.FernetVault([key]),FixturePolicy)
                try:
                    store.edit(2,destination['id'],0,dict(ADDRESS,line1=str(number)+' Example Edit Street'),102)
                    return 'saved'
                except addresses.AddressError as error:
                    if str(error)!='address changed; reload before saving': raise
                    return 'conflict'
                finally: db.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(edit,[1,2]))
            self.assertCountEqual(results,['saved','conflict'])


if __name__=='__main__': unittest.main()
