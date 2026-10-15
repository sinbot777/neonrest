"""Production environment boundaries: no live filesystem writes."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from neonrest import retention,privacy_submissions
class EnvironmentTests(unittest.TestCase):
 def test_retention_roots_are_production_only(self):
  app=SimpleNamespace(static_folder='/isolated/static',instance_path='/isolated/instance',config={'DATABASE':'/isolated/db/neonrest.db'})
  roots=retention.storage_roots(app)
  self.assertEqual(roots['backups'],'/isolated/db/production_backups')
  self.assertEqual(roots['consent'],'/home/sinbot/private/neonrest_production/family_consent')
  self.assertNotIn('sandbox',str(roots))
 def test_document_roots_are_production_only(self):
  app=SimpleNamespace(config={})
  base,receipts=privacy_submissions.roots(app)
  self.assertEqual(base,Path('/home/sinbot/private/neonrest_production/privacy_submissions'))
  self.assertEqual(receipts,base/'receipts')
if __name__=='__main__':unittest.main(verbosity=2)
