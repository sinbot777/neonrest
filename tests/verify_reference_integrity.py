import importlib.util,sqlite3,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('repair',Path(__file__).parents[1]/'reference_integrity.py');repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
class RepairTests(unittest.TestCase):
 def test_obsolete_target_repaired_without_discarding_orphans(self):
  db=sqlite3.connect(':memory:')
  db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY);CREATE TABLE posts(id INTEGER PRIMARY KEY);CREATE TABLE vibes(id INTEGER PRIMARY KEY);CREATE TABLE posts_old(id INTEGER PRIMARY KEY);CREATE TABLE post_vibes(post_id INTEGER NOT NULL REFERENCES posts_old(id),vibe_id INTEGER NOT NULL REFERENCES vibes(id),PRIMARY KEY(post_id,vibe_id));CREATE INDEX post_vibe_lookup ON post_vibes(vibe_id);INSERT INTO posts VALUES(1);INSERT INTO vibes VALUES(1);INSERT INTO post_vibes VALUES(1,1),(2,1);DROP TABLE posts_old;')
  rows=db.execute('SELECT * FROM post_vibes').fetchall();self.assertEqual(len(db.execute('PRAGMA foreign_key_check').fetchall()),2)
  db.execute('PRAGMA foreign_keys=ON');self.assertTrue(repair.repair_post_vibes(db));self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
  self.assertEqual(db.execute('SELECT * FROM post_vibes').fetchall(),rows);self.assertEqual(len(db.execute('PRAGMA foreign_key_check').fetchall()),1)
  self.assertFalse(repair.repair_post_vibes(db));self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='post_vibe_lookup'").fetchone());db.close()
if __name__=='__main__':unittest.main()
