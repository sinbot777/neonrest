import sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage_ownership import references
class OwnershipTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript('CREATE TABLE users(id,avatar_path);CREATE TABLE posts(id,user_id,content);CREATE TABLE post_media(post_id,filename,poster,loop_filename);CREATE TABLE media_settings(user_id,profile_midi);')
 def tearDown(self):self.db.close()
 def test_only_explicit_references_attribute_existing_bytes(self):
  self.db.execute("INSERT INTO users VALUES (1,'/static/uploads/avatars/current.png?v=1')")
  self.db.execute("INSERT INTO posts VALUES (1,2,'[image:/static/uploads/posts/image.jpg]')")
  self.db.execute("INSERT INTO post_media VALUES (1,'animation.gif','poster.jpg','loop.gif')")
  self.db.execute("INSERT INTO media_settings VALUES (1,'profile.mid')")
  result=references(self.db,'production',{'media':'prod-media','uploads':'prod-uploads'})
  self.assertEqual(result['prod-uploads/avatars/current.png'],{'production:user:1'})
  self.assertEqual(result['prod-media/poster.jpg'],{'production:user:2'})
  self.assertEqual(result['prod-uploads/posts/image.jpg'],{'production:user:2'})
  self.assertEqual(len(result),6)
 def test_external_and_other_environment_urls_are_not_local_ownership(self):
  self.db.executemany('INSERT INTO users VALUES (?,?)',[(1,'https://other.invalid/static/uploads/avatars/x.png'),(2,'/sandbox/static/uploads/avatars/x.png')])
  self.assertEqual(references(self.db,'production',{'uploads':'p-uploads'}),{})
 def test_conflicts_are_retained_for_inventory_review(self):
  self.db.executemany('INSERT INTO media_settings VALUES (?,?)',[(1,'same.mid'),(2,'same.mid')])
  self.assertEqual(references(self.db,'sandbox',{'media':'s-media'})['s-media/same.mid'],{'sandbox:user:1','sandbox:user:2'})
 def test_unsafe_and_orphan_references_are_not_credited(self):
  self.db.execute("INSERT INTO post_media VALUES (999,'orphan.webp',NULL,NULL)")
  self.db.executemany('INSERT INTO media_settings VALUES (?,?)',[(1,'../private'),(1,'/absolute'),(1,'folder/file'),(1,None)])
  self.assertEqual(references(self.db,'production',{'media':'p-media'}),{})
if __name__=='__main__':unittest.main(verbosity=2)
