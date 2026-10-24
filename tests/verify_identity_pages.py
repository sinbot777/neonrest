"""Offline foundation tests. Full-app/route acceptance is separately pending."""
from pathlib import Path
import importlib.util
import sqlite3
import sys
import types
import unittest
from unittest.mock import patch

package = types.ModuleType('page_fixture')
package.__path__ = []
sys.modules['page_fixture'] = package
ages = types.ModuleType('page_fixture.age_policy')
ages.contact = lambda db, a, b: True
ages.can_read = lambda db, a, b: True
community = types.ModuleType('page_fixture.community_features')
community.blocked = lambda db, a, b: bool(a and b and db.execute(
    'SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',
    (a, b, b, a)).fetchone())
sys.modules[ages.__name__] = ages
sys.modules[community.__name__] = community
spec = importlib.util.spec_from_file_location('page_fixture.identity_pages', Path(__file__).parents[1] / 'identity_pages.py')
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


class PagesTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT,verified INTEGER);
            CREATE TABLE account_disables(user_id INTEGER PRIMARY KEY,disabled INTEGER);
            CREATE TABLE account_safety(user_id INTEGER PRIMARY KEY,inactive INTEGER);
            CREATE TABLE user_moderation(user_id INTEGER PRIMARY KEY,banned INTEGER,posting_restricted INTEGER);
            CREATE TABLE user_blocks(user_id INTEGER,target_id INTEGER);
        ''')
        self.years = {1: 30, 2: 30, 3: 15, 4: 11, 5: None}
        self.ready = {1, 2, 3, 4}
        for uid in self.years:
            self.db.execute('INSERT INTO users VALUES (?,?,1)', (uid, '@fixture' + str(uid)))
        ages.age = lambda db, uid: self.years.get(uid)
        ages.ready = lambda db, uid: uid in self.ready
        pages.initialize(self.db)
        self.page = pages.create(self.db, 1, 'creative', '_Example', 'Example', 'Description')

    def tearDown(self):
        self.db.close()

    def error(self, status, action, *args):
        with self.assertRaises(pages.PageError) as result:
            action(self.db, *args)
        self.assertEqual(result.exception.status, status)

    def test_separate_namespaces_and_case(self):
        self.assertEqual(pages.get(self.db, self.page)['handle'], '_example')
        self.assertEqual(pages.handle('business', '$EXAMPLE'), '$example')
        other = pages.create(self.db, 1, 'business', '$example', 'Example business')
        self.assertEqual(pages.get(self.db, other)['handle'], '$example')
        self.error(409, pages.create, 2, 'creative', '_EXAMPLE', 'Duplicate')
        self.assertEqual(self.db.execute('SELECT handle FROM users WHERE id=1').fetchone()[0], '@fixture1')

    def test_reject_wrong_prefix_and_unsafe_handles(self):
        for value in ['@example', '$example', '__example', 'two words', '../example', 'a/b', 'a%2fb', 'éxample', 'ab', 'a'*31, '', None]:
            with self.subTest(value=value), self.assertRaises(pages.PageError):
                pages.handle('creative', value)
        with self.assertRaises(pages.PageError):
            pages.handle('personal', 'example')

    def test_child_and_teen_creative_business_adult_only(self):
        for uid in (3, 4):
            pages.create(self.db, uid, 'creative', 'creative'+str(uid), 'Young creator')
            self.error(403, pages.create, uid, 'business', 'business'+str(uid), 'Business')
        self.ready.remove(4)
        self.error(403, pages.create, 4, 'creative', 'revoked', 'Revoked consent')
        self.error(403, pages.create, 5, 'creative', 'unknown', 'Missing age')

    def test_verification_and_disabled_moderated_owners(self):
        self.db.execute('UPDATE users SET verified=0 WHERE id=2')
        self.error(403, pages.create, 2, 'creative', 'unverified', 'No')
        self.db.execute('UPDATE users SET verified=1 WHERE id=2')
        for table, columns, values in [('account_disables', 'user_id,disabled', '2,1'),
                ('account_safety', 'user_id,inactive', '2,1'),
                ('user_moderation', 'user_id,banned,posting_restricted', '2,1,0'),
                ('user_moderation', 'user_id,banned,posting_restricted', '2,0,1')]:
            with self.subTest(table=table, values=values):
                self.db.execute('INSERT INTO '+table+'('+columns+') VALUES ('+values+')')
                self.error(403, pages.create, 2, 'creative', 'restricted', 'No')
                self.db.execute('DELETE FROM '+table)

    def test_owner_cannot_be_supplied_as_page_identity(self):
        self.db.execute("UPDATE users SET handle='_forged' WHERE id=2")
        self.error(403, pages.create, 2, 'creative', 'forged', 'No')
        self.assertFalse(pages.eligible(self.db, True, 'creative'))

    def test_business_always_stays_private_until_subscription_integration(self):
        page = pages.create(self.db, 1, 'business', '$Shop', 'Shop')
        self.error(409, pages.set_state, 1, page, 0, 'published')
        self.assertFalse(pages.visible(self.db, pages.get(self.db, page), 2))
        self.assertTrue(pages.visible(self.db, pages.get(self.db, page), 1))
        self.assertEqual(pages.get(self.db, page)['state'], 'draft')

    def test_edit_owner_delegate_and_stale_revision(self):
        self.error(403, pages.edit, 2, self.page, 0, 'Forged', '')
        pages.set_member(self.db, 1, self.page, 2, 'editor')
        pages.edit(self.db, 2, self.page, 0, 'Edited', 'Saved')
        self.error(409, pages.edit, 1, self.page, 0, 'Stale', '')
        self.assertEqual(pages.get(self.db, self.page)['name'], 'Edited')
        self.error(403, pages.set_state, 2, self.page, 1, 'published')
        self.error(403, pages.set_member, 2, self.page, 3, 'manager')
        pages.set_member(self.db, 1, self.page, 2, None)
        self.error(403, pages.edit, 2, self.page, 1, 'Removed', '')

    def test_delegate_age_consent_contact_and_block_rechecked(self):
        pages.set_member(self.db, 1, self.page, 2, 'manager')
        with patch.object(ages, 'contact', return_value=False):
            self.error(403, pages.edit, 2, self.page, 0, 'Contact revoked', '')
        self.db.execute('INSERT INTO user_blocks VALUES (2,1)')
        self.error(403, pages.edit, 2, self.page, 0, 'Blocked', '')
        self.db.execute('DELETE FROM user_blocks')
        self.ready.remove(2)
        self.error(403, pages.edit, 2, self.page, 0, 'Ineligible', '')

    def test_delegate_assignment_cannot_override_contact_or_owner(self):
        self.error(400, pages.set_member, 1, self.page, 1, 'editor')
        self.error(400, pages.set_member, 1, self.page, 2, 'owner')
        with patch.object(ages, 'contact', return_value=False):
            self.error(403, pages.set_member, 1, self.page, 2, 'editor')

    def test_page_visibility_preserves_owner_age_and_block(self):
        page = pages.get(self.db, self.page)
        self.assertFalse(pages.visible(self.db, page, 2))
        pages.set_state(self.db, 1, self.page, 0, 'published')
        page = pages.get(self.db, self.page)
        self.assertTrue(pages.visible(self.db, page, None))
        with patch.object(ages, 'can_read', return_value=False):
            self.assertFalse(pages.visible(self.db, page, 3))
        self.db.execute('INSERT INTO user_blocks VALUES (2,1)')
        self.assertFalse(pages.visible(self.db, page, 2))
        self.ready.remove(1)
        self.assertFalse(pages.visible(self.db, page, None))

    def test_archive_keeps_handle_reserved_and_stops_edits(self):
        pages.set_state(self.db, 1, self.page, 0, 'archived')
        self.error(409, pages.edit, 1, self.page, 1, 'Archived', '')
        self.error(409, pages.create, 2, 'creative', 'example', 'Cannot take over')
        self.assertFalse(pages.visible(self.db, pages.get(self.db, self.page), None))
        pages.set_state(self.db, 1, self.page, 1, 'draft')
        pages.edit(self.db, 1, self.page, 2, 'Restored', '')

    def test_export_does_not_include_other_owners_or_actions(self):
        other = pages.create(self.db, 2, 'creative', 'other', 'Private draft')
        export = pages.export_user(self.db, 1)
        self.assertEqual([r['id'] for r in export['owned_pages']], [self.page])
        self.assertNotIn(other, [r['page_id'] for r in export['own_actions']])

    def test_transaction_rollback_and_idempotent_schema(self):
        self.db.commit()
        pages.initialize(self.db)
        before = self.db.execute('SELECT COUNT(*) FROM identity_pages').fetchone()[0]
        with self.assertRaises(RuntimeError), self.db:
            pages.create(self.db, 1, 'creative', 'rollback', 'Rolled back')
            raise RuntimeError('simulated failure')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM identity_pages').fetchone()[0], before)

    def test_text_bounds_and_page_limit(self):
        self.error(400, pages.edit, 1, self.page, 0, 'a'*81, '')
        self.error(400, pages.edit, 1, self.page, 0, 'Valid', 'a'*4001)
        self.error(400, pages.edit, 1, self.page, 0, 'Invalid\x00', '')
        for i in range(19):
            pages.create(self.db, 1, 'creative', 'page'+str(i), 'Page')
        self.error(409, pages.create, 1, 'creative', 'overlimit', 'Too many')

    def test_updates_require_published_page_and_current_permission(self):
        self.error(409, pages.write_post, 1, self.page, 'Draft update')
        pages.set_state(self.db, 1, self.page, 0, 'published')
        self.error(403, pages.write_post, 2, self.page, 'Impersonation')
        post_id = pages.write_post(self.db, 1, self.page, 'An update')
        post = self.db.execute('SELECT * FROM identity_page_posts WHERE id=?', (post_id,)).fetchone()
        self.assertEqual(post['author_id'], 1)
        self.assertTrue(pages.post_visible(self.db, pages.get(self.db, self.page), post, None))
        self.error(400, pages.write_post, 1, self.page, ' ')
        self.error(400, pages.write_post, 1, self.page, 'a'*5001)
        pages.remove_post(self.db, 1, self.page, post_id)
        post = self.db.execute('SELECT * FROM identity_page_posts WHERE id=?', (post_id,)).fetchone()
        self.assertFalse(pages.post_visible(self.db, pages.get(self.db, self.page), post, None))

    def test_delegate_authorship_does_not_bypass_author_age_or_blocks(self):
        pages.set_member(self.db, 1, self.page, 2, 'editor')
        pages.set_state(self.db, 1, self.page, 0, 'published')
        post_id = pages.write_post(self.db, 2, self.page, 'Delegate update')
        post = self.db.execute('SELECT * FROM identity_page_posts WHERE id=?', (post_id,)).fetchone()
        page = pages.get(self.db, self.page)
        self.db.execute('INSERT INTO user_blocks VALUES (3,2)')
        self.assertFalse(pages.post_visible(self.db, page, post, 3))
        self.db.execute('DELETE FROM user_blocks')
        with patch.object(ages, 'can_read', side_effect=lambda db, author, viewer: author != 2):
            self.assertFalse(pages.post_visible(self.db, page, post, 3))
        self.ready.remove(2)
        self.assertFalse(pages.post_visible(self.db, page, post, 3))
        self.ready.add(2)
        pages.remove_post(self.db, 1, self.page, post_id)

    def test_page_dependencies_and_export_authorship(self):
        self.assertTrue(pages.erasure_dependencies(self.db, 1))
        self.assertFalse(pages.erasure_dependencies(self.db, 2))
        pages.set_state(self.db, 1, self.page, 0, 'published')
        pages.set_member(self.db, 1, self.page, 2, 'editor')
        pages.write_post(self.db, 2, self.page, 'Accountable')
        self.assertTrue(pages.erasure_dependencies(self.db, 2))
        self.assertEqual(len(pages.export_user(self.db, 2)['own_page_posts']), 1)
        self.assertEqual(len(pages.export_user(self.db, 1)['own_page_posts']), 0)


if __name__ == '__main__':
    unittest.main()
