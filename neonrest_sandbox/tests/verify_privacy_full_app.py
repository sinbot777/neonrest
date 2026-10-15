"""Full application smoke check; all writes target a disposable database."""
from pathlib import Path
import contextlib,io,json,os,sys,time,secrets,sqlite3
r=Path('/home/sinbot/releases/PRIVACY-20261014');source=r/'neonrest_sandbox'
for key,value in {'DATABASE':str(r/'full-smoke.db'),'SECRET_FILE':str(r/'smoke-state/secret'),'INSTANCE':str(r/'smoke-state/instance'),'MAIL_QUEUE_DIR':str(r/'smoke-state/mail'),'MAIL_QUEUE':'0'}.items():os.environ['NEONREST_SANDBOX_'+key]=value
(r/'smoke-state').mkdir(mode=0o700,exist_ok=True)
src=sqlite3.connect('file:'+str(r/'fixture.db')+'?mode=ro',uri=True);dst=sqlite3.connect(r/'full-smoke.db');src.backup(dst);src.close();dst.close()
sys.path.insert(0,str(r))
with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
from neonrest_sandbox import community_features as cf,privacy_workflows as privacy,retention
app=core.app;assert Path(app.config['DATABASE'])==r/'full-smoke.db';assert not app.config['RETENTION_ENABLED'];app.config.update(TESTING=True,SESSION_COOKIE_PATH='/',SERVER_NAME='www.neonrest.com',MAIL_QUEUE_ENABLED=False)
core.mail.send=lambda _:(_ for _ in ()).throw(AssertionError('No SMTP in privacy smoke tests'))
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
client=app.test_client();base='https://www.neonrest.com';csrf='synthetic-privacy-smoke';sid='synthetic-privacy-smoke-session';now=int(time.time())
with app.app_context():
 db=core.get_db();db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),1,now,now,now+3600,'Privacy regression fixture'))
 suffix=secrets.token_hex(5)
 child=db.execute("INSERT INTO users(email,handle,password_hash,verified,dob,created_at) VALUES (?,?,?,1,'2012-01-01',CURRENT_TIMESTAMP)",('privacy-'+suffix+'@example.invalid','@PrivacyFixture'+suffix,'!no-login-privacy-fixture')).lastrowid
 db.execute("INSERT INTO age_clocks(user_id,zone,confirmed) VALUES (?,'UTC',1)",(child,))
 db.execute("INSERT INTO family_links(parent_id,child_id,status,method,reference,reviewed_by,reviewed_at) VALUES (1,?,'approved','signed-form','disposable-authority-review',1,CURRENT_TIMESTAMP)",(child,))
 pid=db.execute("INSERT INTO posts(user_id,content,circle,created_at) VALUES (?,'Synthetic child post','public',CURRENT_TIMESTAMP)",(child,)).lastrowid
 db.commit()
with client.session_transaction() as s:s.update(user_id=1,user_handle="@PrivacyReviewer",user_email="privacy@example.invalid",sid=sid,fresh_at=now,factor_at=now,theme_csrf_token=csrf)
def post(path,data):return client.post(path,base_url=base,headers={'Origin':base},data=dict(data,theme_csrf_token=csrf))
for path in ('/manage/privacy','/manage/family/requests','/account/family/requests'):
 response=client.get(path,base_url=base);check(response.status_code==200,'Actual template/route '+path);check('no-store' in response.headers.get('Cache-Control','') and 'public' not in response.headers.get('Cache-Control',''),'Private response '+path)
check(post('/account/family/requests',dict(child_id=child,kind='data-review',notes='Synthetic request')).status_code==302,'Actual guardian intake')
with app.app_context():
 db=core.get_db();row=db.execute('SELECT * FROM family_data_requests WHERE parent_id=1 AND child_id=? ORDER BY id DESC LIMIT 1',(child,)).fetchone();rid=row['id'];check(row['response_due'] is not None,'Deadline initialized');payload=privacy.export_candidate(db,child)
check(post('/manage/family/requests',dict(request_id=rid,action='approve-access',reference='Synthetic reviewed scope',guardian_verified='1',disclosure_reviewed='1',disclosure_basis='Synthetic verified legal authority',reviewed_export=json.dumps(payload))).status_code==302,'Actual scoped approval')
response=client.get('/account/family/requests/'+str(rid)+'/download',base_url=base);check(response.status_code==200,'Actual scoped download');check(b'Synthetic child post' in response.data,'Reviewed content included');check(b'password_hash' not in response.data,'Credentials excluded')
check(post('/manage/privacy',dict(action='add-hold',user_id=child,reason='Synthetic open issue',legal_basis='Necessary investigation',reference='Synthetic case')).status_code==302,'Actual preservation management')
with app.app_context():
 db=core.get_db();db.execute("INSERT INTO account_safety(user_id,inactive,deletion_requested_at) VALUES (?,1,'2000-01-01') ON CONFLICT(user_id) DO UPDATE SET inactive=1,deletion_requested_at='2000-01-01'",(child,));db.commit();check(child not in retention.plan(db)['accounts'],'Full application retention respects hold')
response=client.get('/manage/privacy',base_url=base);check(response.status_code==200,'Actual hold and deletion view');check(b'Preservation hold' in response.data,'Hold reason visible')
check(client.post('/manage/privacy',base_url=base,headers={'Origin':base},data={'action':'add-hold'}).status_code==400,'Actual CSRF rejection')
print('FULL APPLICATION PRIVACY SMOKE PASS',checks,'checks; disposable DB only; no SMTP')
