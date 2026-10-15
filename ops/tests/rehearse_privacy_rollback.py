"""Offline rollback drill; never replace a live file or database."""
from pathlib import Path
from types import SimpleNamespace
import ast, contextlib, hashlib, io, json, os, secrets, sqlite3, subprocess, sys, time
r = Path(os.environ['NEONREST_DEPLOYMENT_REHEARSAL']).resolve()
assert r.name.startswith('PRIVACY-PRODUCTION-') and (r/'fixture.db').is_file()
live = Path('/home/sinbot/neonrest')
rollback = r/'rollback-source'
package = rollback/'neonrest'
package.mkdir(parents=True, exist_ok=True, mode=0o700)
protected = {}
for src in live.rglob('*'):
    rel = src.relative_to(live)
    if (src.is_symlink() or not src.is_file() or src.suffix not in ('.py','.html','.css','.js')
            or any(x in rel.parts for x in ('uploads','backups','instance','private','__pycache__','.git','tests'))):
        continue
    data = src.read_bytes()
    protected[str(rel)] = hashlib.sha256(data).hexdigest()
    if str(rel) == 'utils/lastfm.py':
        # Use the already redacted candidate copy; never export the runtime API key.
        data = (r/'neonrest'/rel).read_bytes()
    dest = package/rel
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest.write_bytes(data)
    dest.chmod(0o600)
# The current notice is retained during rollback; signup is gated so old code
# cannot record an outdated policy version against this notice.
(package/'templates/privacy.html').write_bytes((r/'neonrest/templates/privacy.html').read_bytes())
(rollback/'privacy_rollback_guard.py').write_bytes((r/'privacy_rollback_guard.py').read_bytes())
(r/'rollback-baseline-source-hashes.json').write_text(json.dumps(protected, indent=2))
(r/'rollback-baseline-source-hashes.json').chmod(0o600)
src = sqlite3.connect('file:'+str(r/'full-smoke.db')+'?mode=ro', uri=True)
dbpath = r/'rollback-drill.db'
dest = sqlite3.connect(dbpath)
src.backup(dest); src.close(); dest.close(); dbpath.chmod(0o600)
sys.path.insert(0, str(r))
from neonrest import privacy_submissions as intake
checks = []
def check(ok, label):
    assert ok, label
    checks.append(label)
db = sqlite3.connect(dbpath); db.row_factory = sqlite3.Row
check(db.execute('pragma integrity_check').fetchone()[0]=='ok', 'Upgraded offline copy passes integrity')
original_users = [tuple(x) for x in db.execute('select * from users order by id')]
now = int(time.time()); marker = 'SYNTHETIC POST-MIGRATION ROLLBACK MARKER'
post = db.execute("insert into posts(user_id,content,circle,created_at) values (1,?,'private',CURRENT_TIMESTAMP)",(marker,)).lastrowid
hold = db.execute('insert into privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) values (1,?,?,?,?,?,?)',
                  ('Synthetic later unresolved issue','Offline rehearsal only','ROLLBACK-DRILL',1,now,now+86400)).lastrowid
rid = db.execute('select max(id) from family_data_requests').fetchone()[0]
assert rid
raw = secrets.token_urlsafe(32); digest = hashlib.sha256(raw.encode()).hexdigest()
db.execute('insert into privacy_upload_invites(request_id,token_hash,created_by,created_at,expires_at,instructions) values (?,?,1,?,?,?)',
           (rid,digest,now,now+86400,'Synthetic offline invitation only'))
db.commit()
check(db.execute("select count(*) from family_data_requests where status='access-approved'").fetchone()[0]>0,'Live export grant exists in offline test before rollback')
private = r/'rollback-private'/'documents'
app = SimpleNamespace(config={'PRIVACY_SUBMISSIONS_FOLDER':str(private)})
intake.restore_preflight(app, db)
check(db.execute("select count(*) from family_data_requests where status='access-approved' or approved_payload is not null or expires_at is not null").fetchone()[0]==0,'Rollback revokes grants and reviewed payloads')
check(db.execute('select count(*) from active_sessions where revoked=0').fetchone()[0]==0,'Rollback revokes copied sessions')
check(db.execute('select revoked_at from privacy_upload_invites where token_hash=?',(digest,)).fetchone()[0] is not None,'Rollback revokes upload invitation')
check((private/'receipts'/digest).is_file(),'Independent rollback revocation receipt exists')
check(db.execute('select released_at from privacy_holds where id=?',(hold,)).fetchone()[0] is None,'Post-backup hold remains active')
check(db.execute('select content from posts where id=?',(post,)).fetchone()[0]==marker,'Post-migration activity retained without restoring old database')
check([tuple(x) for x in db.execute('select * from users order by id')]==original_users,'User records unchanged by rollback sanitation')
db.close()
child = r/'verify-old-code-rollback.py'
child.write_text('''from pathlib import Path
import contextlib,io,json,os,sys,sqlite3
root=Path(os.environ['NEONREST_DEPLOYMENT_REHEARSAL']).resolve(); source=root/'rollback-source'
for key,value in {'DATABASE':str(root/'rollback-drill.db'),'SECRET_FILE':str(root/'rollback-state/secret'),'INSTANCE':str(root/'rollback-state/instance'),'MAIL_QUEUE_DIR':str(root/'rollback-state/mail'),'MAIL_QUEUE':'0'}.items():os.environ['NEONREST_PRODUCTION_'+key]=value
(root/'rollback-state').mkdir(mode=0o700,exist_ok=True)
sys.path.insert(0,str(source))
with contextlib.redirect_stdout(io.StringIO()):import neonrest.app as core
assert Path(core.__file__).resolve()==source/'neonrest/app.py'
assert not core.app.config['RETENTION_ENABLED']
core.mail.send=lambda _:(_ for _ in ()).throw(AssertionError('SMTP prohibited in rollback drill'))
from privacy_rollback_guard import PrivacyRollbackGuard
core.app.wsgi_app=PrivacyRollbackGuard(core.app.wsgi_app)
client=core.app.test_client();checks=[]
for path in ['/manage/privacy','/manage/family/requests','/account/family/requests','/privacy/submit','/signup','/account/family/requests/1/download']:
 for method in ['get','post']:
  res=getattr(client,method)(path,base_url='https://www.neonrest.com')
  assert res.status_code==503 and 'no-store' in res.headers['Cache-Control'],path
  checks.append(method+' '+path+' paused before old code')
res=client.get('/login',base_url='https://www.neonrest.com');assert res.status_code in (200,302);checks.append('Normal sign-in route still available')
res=client.get('/privacy',base_url='https://www.neonrest.com');assert res.status_code==200 and b'Effective date: October 14, 2026' in res.data;checks.append('Current privacy notice retained during rollback')
with core.app.app_context():
 db=core.get_db();assert db.execute("select count(*) from posts where content='SYNTHETIC POST-MIGRATION ROLLBACK MARKER'").fetchone()[0]==1;checks.append('Older application opens migrated database and retains new activity')
 assert db.execute("select count(*) from privacy_holds where reference='ROLLBACK-DRILL' and released_at is null").fetchone()[0]==1;checks.append('Older application preserves later hold')
(root/'old-code-rollback-checks.json').write_text(json.dumps(checks,indent=2))
print('OLD CODE ROLLBACK PASS',len(checks))
''')
p = subprocess.run([sys.executable,str(child)],env=dict(os.environ,PYTHONPATH=str(rollback),PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=180)
if p.returncode: raise RuntimeError(p.stdout[-1000:]+'\n'+p.stderr[-3000:])
checks.extend(json.loads((r/'old-code-rollback-checks.json').read_text()))
check(all(hashlib.sha256((live/n).read_bytes()).hexdigest()==h for n,h in protected.items()),'All inspected live Production source hashes unchanged')
result={'passed':len(checks),'checks':checks,'live_production_unchanged':True,'mail_disabled':True,'permanent_erasure_enabled':False,'uses_postmigration_database':True}
(r/'rollback-review-result.json').write_text(json.dumps(result,indent=2))
print('ROLLBACK REHEARSAL PASS',json.dumps(result))
