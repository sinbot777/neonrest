"""Display numbering migrations and namespace allocation use disposable databases."""
import sqlite3, unittest
from neonrest_sandbox import circle_names

class Names(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE circles(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL)')
        self.db.executemany('INSERT INTO circles(name) VALUES (?)',[('MedfordOR',),('PRACTICE Management lab',),('MedfordOR',)])
        self.db.commit();circle_names.initialize(self.db)
    def tearDown(self):self.db.close()
    def test_backfill_and_repeat(self):
        self.assertEqual(self.db.execute('SELECT name_number FROM circles ORDER BY id').fetchall(),[(1,),(1,),(2,)])
        circle_names.initialize(self.db)
        self.assertEqual(self.db.execute('SELECT name_number FROM circles ORDER BY id').fetchall(),[(1,),(1,),(2,)])
    def test_case_spacing(self):
        self.db.execute("INSERT INTO circles(name) VALUES (' medfordor  ')")
        self.assertEqual(circle_names.assign(self.db,4,' medfordor  '),3)
    def test_rename_and_return(self):
        self.db.execute("UPDATE circles SET name='PRACTICE Management lab' WHERE id=1")
        self.assertEqual(circle_names.assign(self.db,1,'PRACTICE Management lab'),2)
        self.db.execute("UPDATE circles SET name='MedfordOR' WHERE id=1")
        self.assertEqual(circle_names.assign(self.db,1,'MedfordOR'),1)
    def test_deleted_number_reserved(self):
        self.db.execute('DELETE FROM circles WHERE id=3')
        cid=self.db.execute("INSERT INTO circles(name) VALUES ('MedfordOR')").lastrowid
        self.assertEqual(circle_names.assign(self.db,cid,'MedfordOR'),3)
    def test_rollback_does_not_consume_number(self):
        self.db.execute("INSERT INTO circles(name) VALUES ('MedfordOR')")
        circle_names.assign(self.db,4,'MedfordOR');self.db.rollback()
        self.db.execute("INSERT INTO circles(name) VALUES ('MedfordOR')")
        self.assertEqual(circle_names.assign(self.db,4,'MedfordOR'),3)

if __name__=='__main__':unittest.main()
