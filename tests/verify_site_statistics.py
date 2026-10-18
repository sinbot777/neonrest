from pathlib import Path
import os,sys,tempfile,sqlite3,importlib,contextlib,io,time,json
package=sys.argv[1];stage=Path(sys.argv[2]);w=Path(tempfile.mkdtemp(prefix='neonrest-statistics-test-'))
src=sqlite3.connect('file:/home/sinbot/db/'+package+'.db?mode=ro',uri=True);dst=sqlite3.connect(w/'fixture.db');src.backup(dst);src.close();dst.close()
with sqlite3.connect(w/'fixture.db') as before_db:initial_counts={r[0]:before_db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in before_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
prefix='NEONREST_PRODUCTION' if package=='neonrest' else 'NEONREST_SANDBOX'
for k,v in {'DATABASE':str(w/'fixture.db'),'SECRET_FILE':str(w/'secret'),'INSTANCE':str(w/'instance'),'MAIL_QUEUE_DIR':str(w/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[prefix+'_'+k]=v
os.environ['NEONREST_STATISTICS_DATABASE']=str(w/'statistics.sqlite')
sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
cf=importlib.import_module(package+'.community_features');tools=importlib.import_module(package+'.vibe_tools');life=importlib.import_module(package+'.utils.vibe_lifecycle');app=core.app;app.instance_path=str(w/'instance');app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/');core.mail.send=lambda x:(_ for _ in ()).throw(AssertionError('SMTP forbidden'))
mount='/sandbox' if package.endswith('sandbox') else '';env={'SCRIPT_NAME':mount};checks=0;now=int(time.time());token='fictional-vibe-management-csrf';clients={};users={}
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def query(sql,args=()):
 with app.app_context():return core.get_db().execute(sql,args).fetchall()
def change(sql,args=()):
 with app.app_context():db=core.get_db();r=db.execute(sql,args);db.commit();return r.lastrowid
check(all(query('SELECT COUNT(*) FROM "'+n+'"')[0][0]==v for n,v in initial_counts.items()),'Startup preserves existing table record counts')
with app.app_context():
 db=core.get_db();tools.initialize(db);tools.initialize(db);db.commit()
 # The copied owner row is replaced with a fictional identity before any session is created.
 db.execute("UPDATE users SET handle='@VMFixtureOwner',email='vm-owner@example.invalid',password_hash='!disabled-fixture',verified=1,bio='',avatar_path=NULL WHERE id=1")
 for table in ['staff_roles','vibe_editors','user_moderation','account_safety','account_disables','age_clocks','active_sessions']:
  db.execute('DELETE FROM '+table+' WHERE user_id=1')
 for key,dob in [('Owner','1990-01-01'),('Admin','1990-01-01'),('Moderator','1990-01-01'),('SiteManager','1990-01-01'),('Manager','1990-01-01'),('OtherManager','1990-01-01'),('Writer','1990-01-01'),('Regular','1990-01-01'),('Teen','2013-01-01'),('NoFactor','1990-01-01')]:
  uid=1 if key=='Owner' else db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)',('@VMFixture'+key,'vm-'+key.lower()+'@example.invalid','!disabled-fixture',dob)).lastrowid;users[key]=uid
  db.execute("INSERT OR REPLACE INTO age_clocks VALUES (?,'UTC',1)",(uid,));db.execute('INSERT OR REPLACE INTO account_safety(user_id,totp_secret) VALUES (?,?)',(uid,None if key=='NoFactor' else 'JBSWY3DPEHPK3PXP'))
  sid='fictional-vm-'+key;db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Vibe fixture'))
 for key,role in [('Admin','admin'),('Moderator','moderator'),('SiteManager','manager')]:db.execute('INSERT INTO staff_roles VALUES (?,?)',(users[key],role))
 vid=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture One')").lastrowid;other=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture Two')").lastrowid
 for key,cid in [('Manager',vid),('OtherManager',other),('NoFactor',vid)]:db.execute('INSERT INTO vibe_editors VALUES (?,?)',(cid,users[key]))
 db.commit()
for key,uid in users.items():
 client=app.test_client()
 with client.session_transaction() as s:s.update(user_id=uid,user_handle='@VMFixture'+key,user_email='vm-'+key.lower()+'@example.invalid',sid='fictional-vm-'+key,fresh_at=now,factor_at=now,theme_csrf_token=token)
 clients[key]=client
def get(key,path,**params):return clients[key].get(path,query_string=params,environ_overrides=env)
def action(key,kind,cid=None,**data):return clients[key].post('/manage/vibes/'+str(cid or vid)+'/action',data={'action':kind,'theme_csrf_token':token,'reason':'PRACTICE ONLY: fictional test decision',**data},environ_overrides=env)
def post_fixture(text,audience='public',vibes=None):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',(pid,users['Writer'],text,'public'));core.identifiers.ensure(db,'post',pid);db.execute('INSERT OR REPLACE INTO post_privacy VALUES (?,?)',(pid,audience))
  for cid in vibes or [vid]:db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,cid))
  db.commit();return pid,core.identifiers.public(db,'post',pid)

stats=importlib.import_module(package+'.site_statistics');verification=importlib.import_module(package+'.email_verification');from flask import g
path=app.extensions['site_statistics']['path']
check(str(path).startswith(str(w)),'Statistics store must be in disposable directory')
ua={'User-Agent':'Mozilla/5.0 NeonrestAcceptance'}
def raw():
 with sqlite3.connect(path) as db:return db.execute('SELECT day,kind,label,detail,value FROM counters ORDER BY day,kind,label,detail').fetchall()
def reset():
 with sqlite3.connect(path) as db:db.execute('DELETE FROM counters')
def count(kind,label=None):return sum(r[4] for r in raw() if r[1]==kind and (label is None or r[2]==label))
def visit(route='/',client=None,headers=None,**kw):return (client or app.test_client()).get(route,headers={**ua,**(headers or {})},environ_overrides=env,**kw)
for name in ['Owner','Admin']:
 r=get(name,'/manage/statistics');check(r.status_code==200,'Authorized dashboard '+name+' '+str(r.status_code));check(b'site-statistics.css' in r.data,'Stylesheet wired');check('no-store' in r.headers.get('Cache-Control',''),'No shared caching')
 check(get(name,'/manage/statistics.csv').status_code==200,'CSV same permission '+name)
for name in ['Moderator','SiteManager','Manager','OtherManager','Regular','Teen']:
 check(get(name,'/manage/statistics').status_code==403,'No analytics role escalation '+name);check(get(name,'/manage/statistics.csv').status_code==403,'No CSV role escalation '+name)
check(get('NoFactor','/manage/statistics').status_code in (302,403),'No factor cannot see statistics')
check(visit('/manage/statistics').status_code==403,'Guest dashboard forbidden');check(visit('/manage/statistics.csv').status_code==403,'Guest CSV forbidden')
check(get('Owner','/manage/statistics',days='999').status_code==400,'Invalid range rejected')
for days in ['7','30','90']:check(get('Owner','/manage/statistics',days=days).status_code==200,'Allowed range '+days)
with clients['Owner'].session_transaction() as s:s['fresh_at']=0
r=get('Owner','/manage/statistics');check(r.status_code==302 and 'reauth' in r.location,'Stale auth requires reauthentication')
with clients['Owner'].session_transaction() as s:s['fresh_at']=now
change('UPDATE account_safety SET totp_secret=NULL WHERE user_id=?',(users['Admin'],));r=get('Admin','/manage/statistics');check(r.status_code==302 and '/account/security' in r.location,'2FA setup enforced');change('UPDATE account_safety SET totp_secret=? WHERE user_id=?',('JBSWY3DPEHPK3PXP',users['Admin']))
reset();r=visit('/');check(r.status_code==200 and count('page','home')==1,'Guest page counted');check('site-statistics' not in r.headers.get('Set-Cookie',''),'No analytics cookie')
visit('/',headers={'DNT':'1'});visit('/',headers={'Sec-GPC':'1'});visit('/',headers={'User-Agent':'Googlebot'});visit('/',client=clients['Owner']);visit('/',client=clients['Moderator']);check(count('page','home')==1,'Privacy signals, bots and staff excluded')
visit('/guide?search=PRIVATE-SEARCH-SENTINEL',headers={'Referer':'https://localhost'+mount+'/?private=SECRET-QUERY'});check(count('flow','home')==1,'Only aggregate referrer category saved')
visit('/guide',headers={'Referer':'https://evil.example/'+mount+'/feed'});check(count('flow')==1,'Cross-site referrer ignored')
visit('/guide',headers={'Referer':'https://localhost'+('/' if mount else '/sandbox/')+'feed'});check(count('flow')==1,'Other environment referrer ignored')
for route in ['/manage/statistics','/account/security','/this-path-does-not-exist','/static/css/site-statistics.css']:
 before=count('page');visit(route);check(count('page')==before,'Sensitive, unavailable and asset routes excluded '+route)
check(all('SECRET' not in str(row) and 'PRIVATE' not in str(row) for row in raw()),'No raw query/referrer recorded')
for route,cat in [('/@ExamplePrivateHandle','profile'),('/posts/private-id','post'),('/circles/opaque-circle','circle'),('/vibe/Private%20Name','vibe')]:check(stats.category(route)==cat,'Identifier collapsed '+cat)
for route in ['/manage/users','/account','/verify_email/secret','/circles/abc/reports','/posts/abc/history','/edit_post/abc']:check(stats.category(route) is None,'Sensitive route omitted '+route)
reset();core.validate_email=lambda email: None
verification.send_verification=lambda *a:'queued'
form={'consent':'on','actual_name':'Fictional Statistics Person','email':'stats-one@example.invalid','handle':'StatsFixtureOne','password':'Fictional-Only-Password-4682','dob':'1990-01-01','timezone':'UTC','theme_csrf_token':token}
def signup(data,network):
 c=app.test_client()
 with c.session_transaction() as s:s['theme_csrf_token']=token
 return c.post('/signup',data=data,headers=ua,environ_overrides={**env,'REMOTE_ADDR':network})
r=signup(form,'192.0.2.10');check(r.status_code==302 and count('signup','created_queued')==1,'Actual signup queued '+str(r.status_code)+' '+r.data[:160].decode())
r=signup(form,'192.0.2.11');check(r.status_code==302 and count('signup','unavailable')==1,'Duplicate signup category')
r=signup({**form,'email':'stats-two@example.invalid','handle':'StatsFixtureTwo','consent':''},'192.0.2.12');check(r.status_code==400 and count('signup','rejected')==1,'Rejected form category')
r=signup({**form,'email':'stats-three@example.invalid','handle':'StatsFixtureThree','dob':'2018-01-01'},'192.0.2.13');check(r.status_code in (400,403) and count('signup','rejected')==2,'Age rejection counted without DOB')
verification.send_verification=lambda *a:False
r=signup({**form,'email':'stats-four@example.invalid','handle':'StatsFixtureFour'},'192.0.2.14');check(r.status_code==302 and count('signup','created_mail_problem')==1,'Created account with delivery problem category')
verification.send_verification=lambda *a:True
r=signup({**form,'email':'stats-five@example.invalid','handle':'StatsFixtureFive'},'192.0.2.15');check(r.status_code==302 and count('signup','created_sent')==1,'Created sent category')
def invalid(email):raise ValueError('Fictional invalid format')
core.validate_email=invalid
r=signup({**form,'email':'stats-six@example.invalid','handle':'StatsFixtureSix'},'192.0.2.16');check(r.status_code==302 and count('signup','invalid_email')==1,'Invalid email category')
with app.app_context():raw_token=verification.issue_token(core.get_db(),'stats-one@example.invalid')
r=visit('/verify_email/'+raw_token);check(r.status_code==200 and count('signup','verified')==1,'Actual single-use verification counted')
r=visit('/verify_email/'+raw_token);check(r.status_code==400 and count('signup','verified')==1 and count('signup','verification_invalid')==1,'Verification reuse not counted as success')
check(not any(any(x in str(row) for x in ['stats-one','StatsFixture','192.0.2','1990-01-01',raw_token]) for row in raw()),'No identity, address, DOB or token in counters')
data=stats.report(path,7);check(data['totals']['created']==3 and data['totals']['attempts']==7 and data['totals']['verified']==1,'Aggregate totals match actual events '+str(dict(data['totals'])))
r=get('Owner','/manage/statistics.csv');check(b'stats-one' not in r.data and b'Account created' in r.data and 'attachment' in r.headers.get('Content-Disposition',''),'Safe aggregate CSV')
from datetime import datetime,timedelta,timezone
old=(datetime.now(timezone.utc).date()-timedelta(days=90)).isoformat();keep=(datetime.now(timezone.utc).date()-timedelta(days=89)).isoformat()
with sqlite3.connect(path) as db:db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(old,'page','home','',5));db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(keep,'page','home','',6))
visit('/');check(not any(r[0]==old for r in raw()) and any(r[0]==keep for r in raw()),'Exact 90 UTC-day retention boundary')
# Verify separate connection cannot commit the main account transaction.
with app.test_request_context('/'):
 db=core.get_db();db.execute("UPDATE users SET bio='UNCOMMITTED-STATS-SENTINEL' WHERE id=?",(users['Regular'],));stats.add_counts(path,[('page','home','')]);db.rollback()
check(query('SELECT bio FROM users WHERE id=?',(users['Regular'],))[0][0]!='UNCOMMITTED-STATS-SENTINEL','Metrics never commit application data')
# A locked metrics database must not break ordinary pages.
lock=sqlite3.connect(path);lock.execute('BEGIN EXCLUSIVE');r=visit('/guide');check(r.status_code==200,'Busy statistics store fails open');lock.rollback();lock.close()
before=raw();app.config['SITE_STATISTICS_ENABLED']=False;visit('/');check(raw()==before,'Collection can be disabled');app.config['SITE_STATISTICS_ENABLED']=True
check(visit('/privacy').status_code==200 and b'Aggregate site statistics' in visit('/privacy').data,'Privacy notice updated');check(visit('/dev').status_code==200 and b'Aggregate site statistics' in visit('/dev').data,'Dev log updated')
with app.app_context():
 # Only fixture tables from the copied DB were used; erasure stays off.
 check(not app.config.get('PERMANENT_ERASURE_ENABLED',False),'Permanent erasure remains disabled')
# Render a fictional-only preview for visual QA; never expose account data.
reset();stats.add_counts(path,[('page','home','')]*18+[('page','guide','')]*7+[('page','circles','')]*5+[('flow','home','guide')]*4+[('signup','created_queued','')]*3+[('signup','rejected','')]+[('signup','verified','')]*2)
r=get('Owner','/manage/statistics');check(r.status_code==200,'Final fictional preview renders')
html=r.data.decode().replace(mount+'/static/','/static/');(stage.parent.parent/'preview.html').write_text(html)
from flask import Flask
fake=Flask('statistics-startup-fixture');original_initialize=stats.initialize
def unavailable_store(path):raise OSError('Fictional unavailable store')
stats.initialize=unavailable_store
try:
 stats.register(fake,core);check(fake.config['SITE_STATISTICS_ENABLED'] is False,'Unavailable metrics storage does not prevent app startup')
finally:stats.initialize=original_initialize
print(json.dumps({'package':package,'checks':checks,'rows':len(raw()),'instance_is_temporary':str(path).startswith(str(w))}))
