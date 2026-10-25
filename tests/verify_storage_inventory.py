"""Read-only filesystem inventory edge cases, on disposable fixtures only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_inventory import inventory


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.a = self.root / 'prod'; self.a.mkdir()
        self.b = self.root / 'sandbox'; self.b.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_unknown_files_still_charged(self):
        (self.a / 'old').write_bytes(b'old')
        result = inventory({'prod': self.a}, {})
        self.assertTrue(result['safe_to_seed'])
        self.assertEqual(result['objects'][0]['owner'], 'unattributed')
        self.assertGreaterEqual(result['charged_bytes'], 3)
        self.assertEqual((self.a / 'old').read_bytes(), b'old')

    def test_exact_owner_and_cross_environment_hardlink_count_once(self):
        (self.a / 'image').write_bytes(b'image')
        os.link(self.a / 'image', self.b / 'copy')
        result = inventory({'prod': self.a, 'sandbox': self.b}, {'prod/image': {'user:1'}, 'sandbox/copy': {'user:1'}})
        self.assertEqual(len(result['objects']), 1)
        self.assertEqual(result['objects'][0]['owner'], 'user:1')
        self.assertEqual(len(result['objects'][0]['aliases']), 2)

    def test_ambiguous_owner_is_not_arbitrarily_assigned(self):
        (self.a / 'image').write_bytes(b'image')
        result = inventory({'prod': self.a}, {'prod/image': {'prod:user:1', 'sandbox:user:1'}})
        self.assertEqual(result['objects'][0]['owner'], 'unattributed')
        self.assertEqual(result['findings'][0]['kind'], 'ambiguous_owner')

    def test_file_and_directory_symlinks_fail_closed(self):
        (self.b / 'private').write_bytes(b'never read')
        (self.a / 'filelink').symlink_to(self.b / 'private')
        (self.a / 'dirlink').symlink_to(self.b, target_is_directory=True)
        result = inventory({'prod': self.a}, {})
        self.assertFalse(result['safe_to_seed'])
        self.assertEqual(result['objects'], [])
        self.assertEqual((self.b / 'private').read_bytes(), b'never read')

    def test_symlink_root_and_parent_rejected(self):
        link = self.root / 'link'; link.symlink_to(self.a, target_is_directory=True)
        (self.a / 'child').mkdir()
        for root in [link, link / 'child']:
            with self.assertRaises(ValueError):
                inventory({'prod': root}, {})

    def test_overlapping_roots_rejected(self):
        child = self.a / 'child'; child.mkdir()
        for roots in [{'a': self.a, 'b': self.a}, {'a': self.a, 'b': child}]:
            with self.assertRaises(ValueError):
                inventory(roots, {})

    def test_missing_root_is_not_treated_as_empty(self):
        result = inventory({'prod': self.root / 'missing'}, {})
        self.assertFalse(result['safe_to_seed'])

    def test_traversal_limit_returns_no_seedable_partial_inventory(self):
        for name in ['one', 'two']:
            (self.a / name).write_bytes(b'x')
        result = inventory({'prod': self.a}, {}, limit=1)
        self.assertFalse(result['safe_to_seed'])
        self.assertEqual(result['objects'], [])

    def test_empty_existing_root_is_valid(self):
        result = inventory({'prod': self.a}, {})
        self.assertTrue(result['safe_to_seed'])
        self.assertEqual(result['charged_bytes'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
