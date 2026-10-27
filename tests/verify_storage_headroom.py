"""Filesystem accounting tests, including shared temporary directory behavior."""
import ast,errno,os,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

def load(path):
 tree=ast.parse(Path(path).read_text());scope=dict(Path=Path,os=os,errno=errno,stat=stat)
 exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='allocated_tree'],type_ignores=[]),str(path),'exec'),scope)
 return scope['allocated_tree']
source=Path(__file__).with_name('storage_uploads.py')
if not source.exists():source=Path(__file__).resolve().parents[1]/'storage_uploads.py'
scan=load(source)
def size(p):
 s=p.lstat();return max(s.st_size,s.st_blocks*512)
class InventoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.home=self.base/'account';self.home.mkdir();self.shared=self.base/'shared';self.shared.mkdir()
 def tearDown(self):self.tmp.cleanup()
 def test_owned_temporary_file_changes_admission(self):
  p=self.shared/'upload';p.write_bytes(b'x'*8192);home=scan(self.home);total=scan(self.home,temporary_roots=[self.shared]);self.assertEqual(total,home+size(p));quota=home+4096+32;self.assertLessEqual(home+4096+32,quota);self.assertGreater(total+4096+32,quota)
 def test_aliases_and_cross_root_hardlinks_count_once(self):
  p=self.home/'shared-object';p.write_bytes(b'x'*8192);os.link(p,self.shared/'hardlink');alias=self.base/'alias';alias.symlink_to(self.shared,target_is_directory=True)
  self.assertEqual(scan(self.home,temporary_roots=[self.shared,alias]),scan(self.home))
 def test_symlink_target_never_traversed(self):
  outside=self.base/'outside';outside.mkdir();(outside/'big').write_bytes(b'x'*20000);p=self.shared/'link';p.symlink_to(outside,target_is_directory=True)
  self.assertEqual(scan(self.home,temporary_roots=[self.shared]),scan(self.home)+size(p))
 def test_owned_nested_tree_included(self):
  d=self.shared/'owned';d.mkdir();p=d/'bytes';p.write_bytes(b'x'*9000)
  self.assertEqual(scan(self.home,temporary_roots=[self.shared]),scan(self.home)+size(d)+size(p))
 def test_foreign_entries_excluded_and_pruned(self):
  d=self.shared/'foreign';d.mkdir();(d/'secret').write_bytes(b'x'*9000);original=Path.lstat
  def lstat(p,*a,**k):
   s=original(p,*a,**k)
   if p==d:
    class Foreign:pass
    f=Foreign();f.st_uid=os.getuid()+1;return f
   return s
  with patch.object(Path,'lstat',lstat):self.assertEqual(scan(self.home,temporary_roots=[self.shared]),size(self.home))
 def test_unreadable_owned_tree_fails_closed(self):
  d=self.shared/'owned';d.mkdir();original=os.walk
  def walk(p,*a,**k):
   if Path(p)==d:raise PermissionError(errno.EACCES,'denied')
   return original(p,*a,**k)
  with patch.object(os,'walk',walk):
   with self.assertRaises(PermissionError):scan(self.home,temporary_roots=[self.shared])
 def test_disappearing_temporary_entry_is_ignored(self):
  p=self.shared/'gone';p.touch();original=Path.lstat
  def lstat(q,*a,**k):
   if q==p:raise FileNotFoundError(errno.ENOENT,'gone')
   return original(q,*a,**k)
  with patch.object(Path,'lstat',lstat):self.assertEqual(scan(self.home,temporary_roots=[self.shared]),size(self.home))
 def test_shared_scan_budget_and_missing_roots_fail_closed(self):
  (self.shared/'one').touch()
  with self.assertRaises(OSError):scan(self.home,limit=1,temporary_roots=[self.shared])
  with self.assertRaises(OSError):scan(self.home,temporary_roots=[self.base/'missing'])
 def test_home_inventory_remains_strict(self):
  alias=self.base/'home-alias';alias.symlink_to(self.home,target_is_directory=True)
  with self.assertRaises(OSError):scan(alias)
if __name__=='__main__':unittest.main()
