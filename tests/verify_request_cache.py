"""Exercise request isolation and invalidation with actual SQLite connections."""
import sqlite3
import unittest
from flask import Flask
import importlib, sys
request_lookup = importlib.import_module(sys.argv.pop(1) + '.request_cache').request_lookup


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE value (n INTEGER)')
        self.db.execute('INSERT INTO value VALUES (1)')
        self.db.commit()
        self.calls = 0

        @request_lookup
        def read(db, marker=None):
            self.calls += 1
            return db.execute('SELECT n FROM value').fetchone()[0]
        self.read = read

    def tearDown(self):
        self.db.close()

    def test_repeated_reads_and_new_request(self):
        with self.app.test_request_context('/'):
            self.assertEqual(self.read(self.db), 1)
            self.assertEqual(self.read(self.db), 1)
            self.assertEqual(self.calls, 1)
        self.db.execute('UPDATE value SET n=2'); self.db.commit()
        with self.app.test_request_context('/'):
            self.assertEqual(self.read(self.db), 2)
            self.assertEqual(self.calls, 2)

    def test_write_and_rollback(self):
        with self.app.test_request_context('/'):
            self.assertEqual(self.read(self.db), 1)
            self.db.execute('UPDATE value SET n=2')
            self.assertEqual(self.read(self.db), 2)
            self.db.rollback()
            self.assertEqual(self.read(self.db), 1)
            self.db.execute('UPDATE value SET n=3'); self.db.commit()
            self.assertEqual(self.read(self.db), 3)

    def test_mutating_requests_and_jobs_never_reuse(self):
        self.read(self.db); self.read(self.db)
        self.assertEqual(self.calls, 2)
        with self.app.test_request_context('/', method='POST'):
            self.read(self.db); self.read(self.db)
            self.assertEqual(self.calls, 4)

    def test_connections_are_separate(self):
        other = sqlite3.connect(':memory:')
        other.execute('CREATE TABLE value(n INTEGER)')
        other.execute('INSERT INTO value VALUES(9)'); other.commit()
        try:
            with self.app.test_request_context('/'):
                self.assertEqual(self.read(self.db), 1)
                self.assertEqual(self.read(other), 9)
        finally:
            other.close()

    def test_explicit_transaction_and_unhashable_keys_bypass(self):
        with self.app.test_request_context('/'):
            self.db.execute('BEGIN')
            self.read(self.db); self.read(self.db)
            self.assertEqual(self.calls, 2)
            self.db.rollback()
            self.read(self.db, marker={}); self.read(self.db, marker={})
            self.assertEqual(self.calls, 4)

    def test_false_values_are_cached(self):
        self.db.execute('UPDATE value SET n=0'); self.db.commit()
        with self.app.test_request_context('/'):
            self.assertEqual(self.read(self.db), 0)
            self.assertEqual(self.read(self.db), 0)
            self.assertEqual(self.calls, 1)


if __name__ == '__main__':
    unittest.main()
