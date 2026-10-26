"""Isolated admission/recovery tests. Never opens the application databases."""
import multiprocessing
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_reservations import Ledger, Limits, QuotaExceeded, ReservationConflict, connect


def contender(path, ready, start, results):
    ledger = connect(path, Limits(100, 100))
    ready.put(True)
    start.wait(10)
    try:
        token = ledger.reserve('same-owner', 30)
        results.put(('ok', token))
    except QuotaExceeded:
        results.put(('full', None))
    finally:
        ledger.db.close()


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.ledger = Ledger(self.db, Limits(100, 150))
        self.ledger.initialize()

    def tearDown(self):
        self.db.close()

    def test_inventory_idempotence_and_change_rollback(self):
        self.ledger.seed([('prod:old', 'prod:user:1', 20)])
        self.ledger.seed([('prod:old', 'prod:user:1', 20)])
        with self.assertRaises(ReservationConflict):
            self.ledger.seed([('aaa:new', 'new', 9), ('prod:old', 'different', 20)])
        self.assertEqual(self.ledger.usage(), 20)

    def test_owner_limit_includes_all_pending_requests(self):
        self.ledger.reserve('prod:user:1', 60)
        with self.assertRaises(QuotaExceeded):
            self.ledger.reserve('prod:user:1', 41)
        self.ledger.reserve('prod:user:1', 40)
        self.assertEqual(self.ledger.usage('prod:user:1'), 100)

    def test_aggregate_spans_environments_and_unknown_history(self):
        self.ledger.seed([('legacy:unknown', 'unattributed', 50)])
        self.ledger.reserve('prod:user:1', 60)
        with self.assertRaises(QuotaExceeded):
            self.ledger.reserve('sandbox:user:1', 41)
        self.ledger.reserve('sandbox:user:1', 40)
        self.assertEqual(self.ledger.usage(), 150)

    def test_finish_charges_retained_derivatives_and_releases_only_unused_bound(self):
        token = self.ledger.reserve('owner', 100)
        self.ledger.mark_started(token)
        self.ledger.settle(token, [('image', 'owner', 30), ('poster', 'owner', 10), ('loop', 'owner', 20)])
        self.assertEqual(self.ledger.usage(), 60)
        self.ledger.reserve('owner', 40)

    def test_crash_does_not_release_started_reservation(self):
        token = self.ledger.reserve('owner', 100)
        self.ledger.mark_started(token)
        with self.assertRaises(ReservationConflict):
            self.ledger.release_unwritten(token)
        with self.assertRaises(QuotaExceeded):
            self.ledger.reserve('owner', 1)
        self.assertEqual(self.ledger.usage(), 100)

    def test_unwritten_can_release_but_cannot_restart(self):
        token = self.ledger.reserve('owner', 100)
        self.ledger.release_unwritten(token)
        self.assertEqual(self.ledger.usage(), 0)
        with self.assertRaises(ReservationConflict):
            self.ledger.mark_started(token)
        with self.assertRaises(ReservationConflict):
            self.ledger.release_unwritten(token)

    def test_oversized_finish_fails_and_retains_charge(self):
        token = self.ledger.reserve('owner', 70)
        self.ledger.mark_started(token)
        with self.assertRaises(QuotaExceeded):
            self.ledger.settle(token, [('large', 'owner', 71)])
        self.assertEqual(self.ledger.usage(), 70)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM upload_objects').fetchone()[0], 0)

    def test_settlement_is_idempotent_only_for_same_outputs(self):
        token = self.ledger.reserve('owner', 70)
        self.ledger.mark_started(token)
        self.ledger.settle(token, [('output', 'owner', 40)])
        self.ledger.settle(token, [('output', 'owner', 40)])
        self.assertEqual(self.ledger.usage(), 40)
        with self.assertRaises(ReservationConflict):
            self.ledger.settle(token, [('different', 'owner', 0)])

    def test_wrong_owner_unknown_token_and_unstarted_finish(self):
        token = self.ledger.reserve('owner', 70)
        with self.assertRaises(ReservationConflict):
            self.ledger.settle(token, [])
        self.ledger.mark_started(token)
        with self.assertRaises(ReservationConflict):
            self.ledger.settle(token, [('output', 'other', 20)])
        with self.assertRaises(ReservationConflict):
            self.ledger.settle('missing', [])
        self.assertEqual(self.ledger.usage(), 70)

    def test_output_collision_rolls_back_all_and_retains_reservation(self):
        self.ledger.seed([('existing', 'old', 10)])
        token = self.ledger.reserve('owner', 70)
        self.ledger.mark_started(token)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.settle(token, [('aaa:new', 'owner', 10), ('existing', 'owner', 10)])
        self.assertEqual(self.ledger.usage(), 80)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM upload_objects').fetchone()[0], 1)

    def test_invalid_amounts_and_duplicate_output_keys(self):
        for bad in [-1, True, 1.5, '1', 2**63, None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.ledger.reserve('owner', bad)
        with self.assertRaises(ValueError):
            self.ledger.reserve('owner', 0)
        with self.assertRaises(ValueError):
            self.ledger.seed([('same', 'owner', 1), ('same', 'owner', 2)])
        for bad in [0, -1, True, 2**63]:
            with self.assertRaises(ValueError):
                Limits(bad, 100)

    def test_cannot_commit_application_transaction(self):
        self.db.execute('BEGIN')
        with self.assertRaises(ReservationConflict):
            self.ledger.reserve('owner', 20)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()

    def test_over_limit_history_remains_intact_and_blocks_growth(self):
        self.ledger.seed([('old', 'owner', 200)])
        with self.assertRaises(QuotaExceeded):
            self.ledger.reserve('owner', 1)
        self.assertEqual(self.ledger.usage(), 200)

    def test_empty_settlement_only_after_started(self):
        token = self.ledger.reserve('owner', 70)
        self.ledger.mark_started(token)
        self.ledger.settle(token, [])
        self.assertEqual(self.ledger.usage(), 0)

    def test_limits_can_increase_without_changing_existing_inventory(self):
        self.ledger.seed([('old', 'owner', 100)])
        with self.assertRaises(QuotaExceeded):
            self.ledger.reserve('owner', 1)
        upgraded = Ledger(self.db, Limits(200, 300))
        upgraded.reserve('owner', 100)
        self.assertEqual(upgraded.usage(), 200)


class PersistenceTests(unittest.TestCase):
    def test_restart_and_concurrent_worker_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'ledger.sqlite')
            db = sqlite3.connect(path)
            Ledger(db, Limits(100, 100)).initialize()
            db.close()
            context = multiprocessing.get_context('spawn')
            ready, results = context.Queue(), context.Queue()
            start = context.Event()
            workers = [context.Process(target=contender, args=(path, ready, start, results)) for _ in range(8)]
            try:
                for worker in workers:
                    worker.start()
                for _ in workers:
                    self.assertTrue(ready.get(timeout=15))
                start.set()
                observed = [results.get(timeout=15) for _ in workers]
                for worker in workers:
                    worker.join(15)
                    self.assertEqual(worker.exitcode, 0)
                self.assertEqual(sum(state == 'ok' for state, _ in observed), 3)
                ledger = connect(path, Limits(100, 100))
                self.assertEqual(ledger.usage(), 90)
                token = next(token for state, token in observed if state == 'ok')
                ledger.mark_started(token)
                ledger.db.close()
                restarted = connect(path, Limits(100, 100))
                self.assertEqual(restarted.usage(), 90)
                with self.assertRaises(QuotaExceeded):
                    restarted.reserve('same-owner', 11)
                with self.assertRaises(ReservationConflict):
                    restarted.release_unwritten(token)
                restarted.db.close()
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                        worker.join()

    def test_missing_database_is_not_silently_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing.sqlite'
            with self.assertRaises(sqlite3.OperationalError):
                connect(path, Limits(100, 100))
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
