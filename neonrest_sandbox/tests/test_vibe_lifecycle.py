import sqlite3
import unittest
from utils.vibe_lifecycle import (add_post_vibes, approve_vibe, can_approve_vibes,
                                  init_vibe_tables, is_pending, supporter_count)


class VibeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE vibes (id INTEGER PRIMARY KEY, name TEXT, theme_id INTEGER);
            CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER);
            CREATE TABLE post_vibes (post_id INTEGER, vibe_id INTEGER,
                                     PRIMARY KEY (post_id, vibe_id));
        ''')
        init_vibe_tables(self.db)

    def add(self, post_id, user_id, name='New Vibe'):
        self.db.execute('INSERT INTO posts (id, user_id) VALUES (?, ?)',
                        (post_id, user_id))
        add_post_vibes(self.db, post_id, [name], threshold=3)
        return self.db.execute('SELECT id FROM vibes WHERE name = ? COLLATE NOCASE',
                               (name,)).fetchone()['id']

    def test_distinct_users_promote_and_existing_vibes_stay_public(self):
        self.db.execute("INSERT INTO vibes (name) VALUES ('Existing')")
        self.assertFalse(is_pending(self.db, 1))
        vibe_id = self.add(1, 10)
        self.assertTrue(is_pending(self.db, vibe_id))
        self.add(2, 10, 'NEW VIBE')
        self.assertEqual(supporter_count(self.db, vibe_id), 1)
        self.add(3, 11)
        self.assertTrue(is_pending(self.db, vibe_id))
        self.add(4, 12)
        self.assertFalse(is_pending(self.db, vibe_id))
        self.assertEqual(supporter_count(self.db, vibe_id), 3)

    def test_manager_can_approve_early_but_moderator_cannot(self):
        vibe_id = self.add(1, 10)
        self.assertFalse(can_approve_vibes(self.db, 2))
        self.db.execute("INSERT INTO staff_roles VALUES (2, 'manager')")
        self.db.execute("INSERT INTO staff_roles VALUES (3, 'moderator')")
        self.assertTrue(can_approve_vibes(self.db, 1))
        self.assertTrue(can_approve_vibes(self.db, 2))
        self.assertFalse(can_approve_vibes(self.db, 3))
        self.assertTrue(approve_vibe(self.db, vibe_id))
        self.assertFalse(is_pending(self.db, vibe_id))
        self.assertFalse(approve_vibe(self.db, vibe_id))

    def test_removed_candidate_post_stops_counting(self):
        vibe_id = self.add(1, 10)
        self.add(2, 11)
        self.db.execute('DELETE FROM post_vibes WHERE post_id = 2')
        self.db.execute('DELETE FROM posts WHERE id = 2')
        self.assertEqual(supporter_count(self.db, vibe_id), 1)
        self.add(3, 12)
        self.assertTrue(is_pending(self.db, vibe_id))


if __name__ == '__main__':
    unittest.main()
