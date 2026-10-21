"""Additive Circle-ID migration, compatibility and collision checks."""
import sqlite3
import unittest
from unittest.mock import patch
from neonrest_sandbox import circle_ids, public_ids


class CircleIds(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE circles(id INTEGER PRIMARY KEY AUTOINCREMENT)')
        self.db.execute('INSERT INTO circles VALUES (1)')
        self.db.execute('INSERT INTO circles VALUES (2)')
        self.db.execute('CREATE TABLE public_ids(kind TEXT,internal_id INTEGER,public_id TEXT)')
        self.db.execute("INSERT INTO public_ids VALUES ('post',9,'ExistingPostId009')")
        self.db.commit()
        circle_ids.initialize(self.db)

    def tearDown(self):
        self.db.close()

    def test_stable_backfill_preserves_post_registry(self):
        first=circle_ids.public(self.db,1)
        second=circle_ids.public(self.db,2)
        self.assertRegex(first,public_ids.TOKEN)
        self.assertNotEqual(first,second)
        circle_ids.initialize(self.db)
        self.assertEqual(first,circle_ids.public(self.db,1))
        self.assertEqual(1,circle_ids.resolve(self.db,'1'))
        self.assertEqual(2,circle_ids.resolve(self.db,second))
        self.assertEqual([('post',9,'ExistingPostId009')],self.db.execute('SELECT * FROM public_ids').fetchall())

    def test_new_circles_have_no_numeric_alias(self):
        self.db.execute('INSERT INTO circles VALUES (3)')
        opaque=circle_ids.ensure(self.db,3)
        self.db.commit()
        circle_ids.initialize(self.db)
        self.assertEqual(3,circle_ids.resolve(self.db,opaque))
        with self.assertRaises(ValueError):circle_ids.resolve(self.db,'3')

    def test_deleted_ids_and_aliases_are_unavailable(self):
        opaque=circle_ids.public(self.db,1)
        self.db.execute('DELETE FROM circles WHERE id=1')
        self.assertFalse(self.db.execute('SELECT 1 FROM circle_public_ids WHERE circle_id=1').fetchone())
        for value in (opaque,'1'):
            with self.assertRaises(ValueError):circle_ids.resolve(self.db,value)

    def test_collisions_retry(self):
        old=circle_ids.public(self.db,1)
        fresh='NewCircleToken03'
        self.assertEqual(len(fresh),16)
        self.db.execute('INSERT INTO circles VALUES (3)')
        with patch.object(public_ids,'random_token',side_effect=[old,fresh]):
            self.assertEqual(fresh,circle_ids.ensure(self.db,3))

    def test_malformed_and_unknown_ids(self):
        for value in ('','01','-1','A'*65,'prefix_AbCdEf1234567890','/1',None,1,'AbCdEf1234567890'):
            with self.subTest(value=value),self.assertRaises(ValueError):circle_ids.resolve(self.db,value)


if __name__=='__main__':unittest.main()
