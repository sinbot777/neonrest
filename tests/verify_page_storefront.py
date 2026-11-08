"""Page Details, protected logo links and publication-only storefront regression checks."""
from pathlib import Path
import importlib
import json
import sys
import unittest
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

sys.path.insert(0, str(Path(__file__).parent))
from verify_identity_page_routes import RouteTests, pages
from page_fixture import page_profile as profile
studio = importlib.import_module('page_fixture.seller_studio')
catalog = importlib.import_module('page_fixture.marketplace_catalog')
products = importlib.import_module('page_fixture.page_products')


class StorefrontTests(RouteTests):
    def setUp(self):
        super().setUp()
        studio.initialize(self.db)
        catalog.initialize(self.db)
        self.db.execute('CREATE TABLE user_mutes(user_id INTEGER,target_id INTEGER)')
        self.shop = studio.create_independent(self.db, 1, 'Fixture shop', 'page', self.page)
        self.db.commit()

    def publish_page(self):
        page = pages.get(self.db, self.page)
        with self.db:
            pages.set_state(self.db, 1, self.page, page['revision'], 'published')

    def listing(self, title='Public pin', granted=True, shop=None):
        key = studio.save_listing(self.db, 1, shop or self.shop,
            MultiDict(dict(title=title, kind='physical', description='Fixture', price='4.50', quantity='2')))
        if granted:
            self.db.execute('INSERT INTO marketplace_publications(listing_id,listing_revision,published_at,image_ids) VALUES (?,0,100,?)',
                            (key, json.dumps(['approved-image'])))
        self.db.commit()
        return key

    def gallery(self, number='1'):
        return products.browse(self.db, None, pages.get(self.db, self.page), number)

    def appearance(self, **values):
        data = dict(action='profile', revision=pages.get(self.db, self.page)['revision'],
                    tagline='Fixture intro', website='https://example.com', accent='teal')
        data.update(values)
        return self.post('/pages/' + self.page + '/edit', **data)

    def test_only_published_grants_for_this_page_appear(self):
        self.publish_page()
        key = self.listing()
        self.listing('Private product draft', granted=False)
        other_page = pages.create(self.db, 1, 'creative', '_elsewhere', 'Other Page')
        other_shop = studio.create_independent(self.db, 1, 'Other shop', 'page', other_page)
        self.listing('Another Page product', shop=other_shop)
        personal = studio.create_independent(self.db, 1, 'Personal shop')
        self.listing('Personal identity product', shop=personal)
        self.assertEqual([i['id'] for i in self.gallery()['items']], [key])
        response = self.client.get('/_example')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Public pin', response.data)
        for text in (b'Private product draft', b'Another Page product', b'Personal identity product'):
            self.assertNotIn(text, response.data)
        self.assertIn(('/marketplace/listings/' + key + '/images/approved-image').encode(), response.data)
        self.assertIn(b'USD 4.50', response.data)

    def test_changed_withdrawn_and_archived_listings_are_excluded(self):
        self.publish_page()
        key = self.listing()
        for sql in ("UPDATE seller_listings SET revision=1", "UPDATE marketplace_publications SET state='withdrawn'", "UPDATE seller_listings SET state='archived'"):
            with self.subTest(sql=sql):
                self.db.execute(sql)
                self.assertEqual(self.gallery()['items'], [])
                self.db.execute("UPDATE seller_listings SET revision=0,state='draft'")
                self.db.execute("UPDATE marketplace_publications SET state='active'")

    def test_private_hidden_blocked_and_ineligible_owners_do_not_leak(self):
        self.listing()
        self.assertEqual(self.gallery()['items'], [])
        self.publish_page()
        self.db.execute('INSERT INTO identity_page_hides VALUES (?,0,1,?,100)', (self.page, 'Fixture restriction'))
        self.assertEqual(self.gallery()['items'], [])
        self.db.execute('DELETE FROM identity_page_hides')
        self.db.execute('INSERT INTO user_blocks VALUES (1,2)')
        self.assertEqual(products.browse(self.db, 2, pages.get(self.db, self.page))['items'], [])
        self.db.execute('DELETE FROM user_blocks')
        self.db.execute('INSERT INTO user_mutes VALUES (2,1)')
        self.assertEqual(products.browse(self.db, 2, pages.get(self.db, self.page))['items'], [])
        self.db.execute('DELETE FROM user_mutes')
        with patch.object(sys.modules['page_fixture.age_policy'], 'can_read', return_value=False):
            self.assertEqual(products.browse(self.db, 2, pages.get(self.db, self.page))['items'], [])
        self.db.execute('UPDATE users SET verified=0 WHERE id=1')
        self.assertEqual(self.gallery()['items'], [])

    def test_page_transfer_or_unlink_removes_products(self):
        self.publish_page()
        self.listing()
        self.db.execute('UPDATE identity_pages SET owner_id=2 WHERE id=?', (self.page,))
        self.assertEqual(self.gallery()['items'], [])
        self.db.execute('UPDATE identity_pages SET owner_id=1 WHERE id=?', (self.page,))
        self.db.execute("UPDATE seller_shops SET identity_kind='personal',linked_page_id=NULL")
        self.assertEqual(self.gallery()['items'], [])

    def test_pagination_is_bounded_and_keeps_sandbox_mount(self):
        self.publish_page()
        for n in range(25):
            self.listing('Product ' + str(n))
        first, second = self.gallery(), self.gallery('2')
        self.assertEqual(len(first['items']), 24)
        self.assertTrue(first['has_next'])
        self.assertEqual(len(second['items']), 1)
        self.assertFalse(second['has_next'])
        self.assertTrue(set(i['id'] for i in first['items']).isdisjoint(i['id'] for i in second['items']))
        response = self.client.get('/_example', environ_overrides={'SCRIPT_NAME': '/sandbox'})
        self.assertIn(b'/sandbox/_example?products_page=2#page-products', response.data)
        self.assertIn(b'href="/sandbox/marketplace/listings/', response.data)
        for invalid in ('0', '-1', '1001', '1;DROP TABLE users', '9'*1000):
            self.assertEqual(self.client.get('/_example', query_string={'products_page': invalid}).status_code, 400)

    def test_public_details_save_escape_and_export(self):
        self.assertEqual(self.appearance(detail_category='Pins & art', detail_location='Medford, OR',
            detail_contact='<img src=x onerror=alert(1)>', detail_hours='Mon–Fri\nBy appointment').status_code, 302)
        self.publish_page()
        response = self.client.get('/_example')
        self.assertIn(b'Pins &amp; art', response.data)
        self.assertIn(b'&lt;img src=x onerror=alert(1)&gt;', response.data)
        self.assertNotIn(b'<img src=x', response.data)
        self.assertIn('Mon–Fri'.encode(), response.data)
        self.assertEqual(profile.page_details(pages.get(self.db,self.page))['location'], 'Medford, OR')
        exported = pages.export_user(self.db, 1)
        self.assertIn('Medford, OR', json.dumps(exported))

    def test_invalid_stale_and_unauthorized_details_leave_page_unchanged(self):
        for field, value in (('category', 'x'*81), ('location', 'x'*121), ('contact', 'bad\x00text'), ('hours', 'x'*301)):
            self.assertEqual(self.appearance(**{'detail_'+field:value}).status_code, 400)
        self.assertEqual(self.appearance(revision=99, detail_category='Stale').status_code, 409)
        self.login(2)
        self.assertEqual(self.appearance(detail_category='Unauthorized').status_code, 403)
        self.assertEqual(profile.page_details(pages.get(self.db,self.page))['category'], '')

    def test_old_forms_preserve_details_and_migration_is_idempotent(self):
        self.assertEqual(self.appearance(detail_category='Art', detail_location='Oregon').status_code, 302)
        self.assertEqual(self.appearance(tagline='Updated').status_code, 302)
        page = dict(pages.get(self.db,self.page))
        self.assertEqual(profile.page_details(page)['category'], 'Art')
        pages.initialize(self.db)
        pages.initialize(self.db)
        self.assertEqual(dict(pages.get(self.db,self.page)), page)

    def test_logo_uses_current_protected_original_and_dialog(self):
        self.publish_page()
        self.db.execute('UPDATE identity_pages SET avatar_file=? WHERE id=?', ('a'*48+'.png', self.page))
        response = self.client.get('/_example')
        for marker in (b'data-page-logo', b'<dialog', b'data-logo-close', b'page_logo.js', b'Open original image'):
            self.assertIn(marker, response.data)
        self.assertIn(('/artwork/avatar/'+'a'*48+'.png" aria-label="Enlarge').encode(), response.data)
        self.db.execute("UPDATE identity_pages SET avatar_file='' WHERE id=?", (self.page,))
        self.assertNotIn(b'<dialog', self.client.get('/_example').data)


if __name__ == '__main__':
    unittest.main()
