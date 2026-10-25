"""Rehearse owner-reviewed legacy repair and exact row restoration in memory."""
from pathlib import Path
import sys,sqlite3,importlib,json,hashlib
pkg=sys.argv[1];stage=Path(sys.argv[2]);sys.path.insert(0,str(stage.parent))
repair=importlib.import_module(pkg+'.reference_integrity')
src=sqlite3.connect('file:/home/sinbot/db/'+pkg+'.db?mode=ro',uri=True)
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;src.backup(db);src.close()
violations=[tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
if not violations:
 print(json.dumps({'passed':True,'repair_needed':False}));raise SystemExit()
assert all(r[0] in ('comments','post_vibes') for r in violations)
ids=sorted({r[1] for r in violations if r[0]=='comments'})
pairs=[tuple(db.execute('SELECT post_id,vibe_id FROM post_vibes WHERE rowid=?',(r[1],)).fetchone()) for r in violations if r[0]=='post_vibes']
tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
counts={n:db.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0] for n in tables}
original=[dict(r) for r in db.execute('SELECT * FROM comments ORDER BY id')]
valid=db.execute('SELECT id FROM comments WHERE post_id IN (SELECT id FROM posts) AND parent_comment_id IS NULL LIMIT 1').fetchone()
if valid:
 db.execute('BEGIN')
 try:repair.archive_legacy_orphans(db,'invalid-valid-row',[valid[0]],[]);raise AssertionError('Valid row accepted')
 except ValueError:db.rollback()
db.execute('BEGIN');result=repair.archive_legacy_orphans(db,'disposable-archive-rehearsal',ids,pairs)
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert list(db.execute('PRAGMA foreign_key_check'))==[]
archived=[dict(r) for r in db.execute("SELECT * FROM reference_repair_archive WHERE batch='disposable-archive-rehearsal'")]
for r in archived:assert hashlib.sha256(r['payload'].encode()).hexdigest()==r['sha256']
delta={'comments':len(ids),'post_vibes':len(pairs)}
for name in ['public_ids','public_id_aliases','moderated_comments','protected_age_comments']:
 delta[name]=sum(1 for r in archived if r['table_name']==name)
for n in tables:assert db.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0]==counts[n]-delta.get(n,0),n
assert [dict(r) for r in db.execute('SELECT * FROM comments ORDER BY id')]==[r for r in original if r['id'] not in ids]
assert all(not db.execute('SELECT 1 FROM comments WHERE id=?',(cid,)).fetchone() for cid in ids)
# Prove the archived rows (including original broken parent IDs) restore exactly.
allowed={'comments','post_vibes','public_ids','public_id_aliases','moderated_comments','protected_age_comments'}
for table in ['comments','post_vibes','public_ids','public_id_aliases','moderated_comments','protected_age_comments']:
 for r in archived:
  if r['table_name']!=table:continue
  assert table in allowed;value=json.loads(r['payload']);columns={c[1] for c in db.execute('PRAGMA table_info('+table+')')};assert set(value)<=columns
  names=list(value);quoted=','.join('"'+n+'"' for n in names)
  db.execute('INSERT INTO '+table+' ('+quoted+') VALUES ('+','.join('?' for n in names)+')',[value[n] for n in names])
assert [dict(r) for r in db.execute('SELECT * FROM comments ORDER BY id')]==original
for n in tables:assert db.execute('SELECT COUNT(*) FROM "'+n.replace('"','""')+'"').fetchone()[0]==counts[n],n
assert set(tuple(r) for r in db.execute('PRAGMA foreign_key_check'))==set(violations)
db.rollback();db.close()
print(json.dumps({'passed':True,'violations_before':len(violations),'violations_after_repair':0,'comments_archived':len(ids),'mappings_archived':len(pairs),'archived_records':result['archived_records'],'exact_restoration_proved':True,'live_writes':False}))
