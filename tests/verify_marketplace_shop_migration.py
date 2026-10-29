"""Populated legacy migration, child references and failed-transaction recovery."""
import ast,sqlite3,sys,json
from pathlib import Path
tree=ast.parse((Path(sys.argv[2])/'seller_studio.py').read_text());ns={}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('initialize','migrate_legacy')],type_ignores=[]),'shop migration fixture','exec'),ns)
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def legacy(enabled):
 db=sqlite3.connect(':memory:');db.execute('PRAGMA foreign_keys='+str(enabled))
 db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES (1);
 CREATE TABLE identity_pages(id TEXT PRIMARY KEY); INSERT INTO identity_pages VALUES ('legacy');
 CREATE TABLE seller_shops(page_id TEXT PRIMARY KEY REFERENCES identity_pages(id),owner_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',policies TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
 INSERT INTO seller_shops VALUES ('legacy',1,'Prior shop','Prior description','Prior policy',9,100,200);
 CREATE TABLE fixture_children(id TEXT PRIMARY KEY,shop_id TEXT REFERENCES seller_shops(page_id),snapshot TEXT);
 INSERT INTO fixture_children VALUES ('child','legacy','immutable fixture');
 CREATE TRIGGER fixture_immutable BEFORE UPDATE OF snapshot ON fixture_children BEGIN SELECT RAISE(ABORT,'immutable'); END;''')
 return db
for enabled in (0,1):
 db=legacy(enabled);old=tuple(db.execute('SELECT * FROM seller_shops').fetchone());child=list(db.execute('SELECT * FROM fixture_children'))
 ns['initialize'](db);db.commit();check(tuple(db.execute('SELECT * FROM seller_shops').fetchone())[:8]==old,'All original shop values unchanged')
 check(db.execute('SELECT identity_kind,linked_page_id FROM seller_shops').fetchone()==('page','legacy'),'Existing link preserved')
 check(list(db.execute('SELECT * FROM fixture_children'))==child,'Child records untouched')
 check(not list(db.execute('PRAGMA foreign_key_check')),'All migrated references valid')
 check(db.execute('PRAGMA foreign_keys').fetchone()[0]==enabled,'Original foreign-key setting restored')
 ns['initialize'](db);db.commit();check(db.execute('SELECT COUNT(*) FROM seller_shops').fetchone()[0]==1,'Repeat migration stable')
 db.execute("INSERT INTO seller_shops(page_id,owner_id,name,created_at,updated_at) VALUES ('standalone',1,'No Page',1,1)")
 db.execute("INSERT INTO fixture_children VALUES ('new-child','standalone','new snapshot')");db.commit()
 check(not list(db.execute('PRAGMA foreign_key_check')),'Independent keys accepted by child references')
 try:db.execute("UPDATE fixture_children SET snapshot='changed' WHERE id='child'")
 except sqlite3.IntegrityError:check(True,'Child immutability trigger retained');db.rollback()
 else:check(False,'Immutable child unexpectedly changed')
 check(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Migrated integrity');db.close()
db=legacy(1);old_sql=db.execute("SELECT sql FROM sqlite_master WHERE name='seller_shops'").fetchone()[0]
db.set_authorizer(lambda action,a,b,c,d:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_DROP_TABLE and a=='seller_shops' else sqlite3.SQLITE_OK)
try:ns['migrate_legacy'](db)
except sqlite3.DatabaseError:check(True,'Forced migration failure reported')
else:check(False,'Expected forced failure')
db.set_authorizer(None)
check(db.execute("SELECT sql FROM sqlite_master WHERE name='seller_shops'").fetchone()[0]==old_sql,'Failed migration preserves original schema')
check(db.execute('SELECT revision FROM seller_shops').fetchone()[0]==9,'Failed migration preserves old row')
check(not db.execute("SELECT 1 FROM sqlite_master WHERE name='seller_shops_standalone'").fetchone(),'Failed migration leaves no partial table')
check(db.execute('PRAGMA foreign_keys').fetchone()[0]==1,'Foreign-key setting restored after failure')
check(not list(db.execute('PRAGMA foreign_key_check')),'References intact after failed migration')
print(json.dumps({'checks':checks,'passed':True,'scope':'populated in-memory migration, idempotency, triggers and failure rollback'}))
