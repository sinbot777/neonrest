"""Index parity and synchronization using an isolated database with literal inputs."""
import importlib.util,sqlite3,sys
from pathlib import Path
stage=Path(sys.argv[1]);spec=importlib.util.spec_from_file_location('search_index',stage/'search_index.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
for table,fields in mod.SCHEMAS.items():db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY,'+','.join(f+' TEXT' for f in fields)+')')
values=['ordinary Orchid discussion','RAREneedleORCHID','100% literal_under_score!','A "quote" here','café KELVIN Kelvin','日本語のテスト','two ab words','nothing','bracket [a] star * minus - OR NOT','emoji 🐈cat','İstanbul Istanbul istanbul','Straße STRASSE']
for i,value in enumerate(values,1):
 for table,fields in mod.SCHEMAS.items():db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in range(len(fields)+1))+')',[i]+[value]*len(fields))
mod.install(db);mod.install(db);checks=0
for table,fields in mod.SCHEMAS.items():
 for field in fields:
  for term in ['ordinary','OrChId','100%','literal_','"quote"','café','KEL','Kel','日本語','ab','[a]','* m',' OR ','🐈cat','İst','Ist','Straße','STRASSE']:
   pattern='%'+term.replace('!','!!').replace('%','!%').replace('_','!_')+'%';clause,args=mod.candidates(table,field,term,table)
   expected=[r[0] for r in db.execute('SELECT id FROM '+table+' WHERE '+field+" LIKE ? ESCAPE '!' ORDER BY id",[pattern])]
   actual=[r[0] for r in db.execute('SELECT id FROM '+table+' WHERE '+field+" LIKE ? ESCAPE '!'"+clause+' ORDER BY id',[pattern]+args)]
   assert actual==expected,(table,field,term,actual,expected);checks+=1
 db.execute('UPDATE '+table+' SET '+fields[0]+"='UpdatedUniqueNeedle' WHERE id=1")
 name='growth_'+table+'_fts';assert db.execute('SELECT rowid FROM '+name+' WHERE '+name+' MATCH ?',('"UpdatedUniqueNeedle"',)).fetchall()[0][0]==1;checks+=1
 db.execute('DELETE FROM '+table+' WHERE id=1');assert not db.execute('SELECT rowid FROM '+name+' WHERE '+name+' MATCH ?',('"UpdatedUniqueNeedle"',)).fetchall();checks+=1
 db.execute('INSERT INTO '+table+'(id,'+fields[0]+") VALUES(100,'InsertedUniqueNeedle')");assert db.execute('SELECT rowid FROM '+name+' WHERE '+name+' MATCH ?',('"InsertedUniqueNeedle"',)).fetchone()[0]==100;checks+=1
 db.execute('INSERT INTO '+name+'('+name+",rank) VALUES('integrity-check',1)");checks+=1
assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok';checks+=1
print(checks,'search index parity/synchronization checks passed')
