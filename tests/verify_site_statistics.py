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


from datetime import datetime,timedelta,timezone
stats=importlib.import_module(package+'.site_statistics');detail=importlib.import_module(package+'.statistics_detail');verification=importlib.import_module(package+'.email_verification');circlemod=importlib.import_module(package+'.circles');circleids=importlib.import_module(package+'.circle_ids');circlenames=importlib.import_module(package+'.circle_names')
path=app.extensions['site_statistics']['path'];check(str(path).startswith(str(w)),'Isolated sidecar')
today=datetime.now(timezone.utc).date();day=today.isoformat();headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36'}
def raw():
 with sqlite3.connect(path) as db:return db.execute('SELECT bucket,segment,kind,label,detail,value FROM hourly_counters ORDER BY bucket,segment,kind,label,detail').fetchall()
def reset():
 with sqlite3.connect(path) as db:db.execute('DELETE FROM hourly_counters');db.execute('DELETE FROM counters');db.execute("UPDATE metadata SET value='0' WHERE key='detail_capacity_skips'")
def count(kind,label=None,segment=None):return sum(r[5] for r in raw() if r[2]==kind and (label is None or r[3]==label) and (segment is None or r[1]==segment))
def visit(route='/',client=None,extra=None):return (client or app.test_client()).get(route,headers={**headers,**(extra or {})},environ_overrides=env)
def report(traffic='ordinary',days='7',**values):
 with app.test_request_context('/manage/statistics',query_string={'traffic':traffic,'days':days,**values},environ_overrides=env):return detail.build_report(core,path,detail.options())
with sqlite3.connect(path) as db:db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(day,'page','home','',5))
stats.initialize(path);stats.initialize(path);check(report()['totals']['views']==5,'Repeated migration preserves legacy counters')
for who in ['Owner','Admin']:
 r=get(who,'/manage/statistics');check(r.status_code==200,'Dashboard '+who);check(b'Hourly totals' in r.data and b'Public communities' in r.data and b'Traffic' in r.data,'Expanded sections '+who)
 check(get(who,'/manage/statistics.csv').status_code==200,'CSV '+who);check('no-store' in r.headers.get('Cache-Control',''),'Cache protection '+who)
for who in ['Moderator','SiteManager','Manager','OtherManager','Regular','Teen']:
 check(get(who,'/manage/statistics').status_code==403,'Unauthorized dashboard '+who);check(get(who,'/manage/statistics.csv').status_code==403,'Unauthorized export '+who)
check(visit('/manage/statistics').status_code==403,'Guest dashboard blocked');check(visit('/manage/statistics.csv').status_code==403,'Guest CSV blocked')
with clients['Owner'].session_transaction() as s:s['fresh_at']=0
r=get('Owner','/manage/statistics');check(r.status_code==302 and 'reauth' in r.location,'Fresh authentication required')
with clients['Owner'].session_transaction() as s:s['fresh_at']=now
change('UPDATE account_safety SET totp_secret=NULL WHERE user_id=?',(users['Admin'],));r=get('Admin','/manage/statistics');check(r.status_code==302 and '/account/security' in r.location,'2FA required');change('UPDATE account_safety SET totp_secret=? WHERE user_id=?',('JBSWY3DPEHPK3PXP',users['Admin']))
for opts in [{'days':'999'},{'traffic':'injection'},{'days':'custom','start':'bad','end':day},{'days':'custom','start':day,'end':(today-timedelta(days=1)).isoformat()},{'days':'custom','start':(today-timedelta(days=91)).isoformat(),'end':day},{'days':'custom','start':day,'end':(today+timedelta(days=1)).isoformat()}]:
 check(get('Owner','/manage/statistics',**opts).status_code==400,'Invalid options rejected '+str(opts))
for period in ['1','7','30','90']:
 check(get('Owner','/manage/statistics',days=period).status_code==200,'Supported date preset '+period)
for group in ['ordinary','all','staff','guest','member']:
 check(get('Owner','/manage/statistics',traffic=group).status_code==200,'Traffic filter '+group)
reset();visit('/');visit('/guide',client=clients['Regular']);visit('/guide',client=clients['Owner']);visit('/guide',client=clients['Moderator'])
check(count('page',segment='guest')==1 and count('page',segment='member')==1 and count('page',segment='staff')==2,'Guest member staff separate')
check(report()['totals']['views']==2 and report('all')['totals']['views']==4 and report('staff')['totals']['views']==2,'Traffic totals filter correctly')
with sqlite3.connect(path) as db:db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(day,'page','home','',5))
check(report()['totals']['views']==7 and report('all')['totals']['views']==9 and report('guest')['totals']['views']==1 and report('member')['totals']['views']==1,'Legacy totals never assigned to guest/member/staff')
check(sum(x['count'] for x in report()['hours'])==2,'Hourly chart excludes legacy daily counts')
before=raw();visit('/',extra={'DNT':'1'});visit('/',extra={'Sec-GPC':'1'});visit('/',extra={'User-Agent':'Googlebot'});visit('/',client=clients['Owner'],extra={'DNT':'1'});check(raw()==before,'Privacy signals and bots excluded including staff')
for route in ['/account/security','/manage/statistics','/nonexistent-stats-private','/static/css/site-statistics.css']:
 before=count('page');visit(route);check(count('page')==before,'Sensitive/assets/unavailable excluded '+route)
reset();visit('/guide?secret=QUERY-SECRET',extra={'Referer':'https://www.google.com/search?q=PRIVATE-TERM','User-Agent':'Mozilla/5.0 (iPhone) Version/17.0 Mobile Safari/604.1'})
check(count('source','google')==1 and count('device','mobile')==1 and count('browser','safari')==1,'Search mobile Safari categories')
visit('/guide',extra={'Referer':'https://www.facebook.com/path?token=REFERRER-SECRET'});visit('/guide',extra={'Referer':'https://evilfacebook.com/'});visit('/guide',extra={'Referer':'https://localhost'+mount+'/feed?private=FLOW-SECRET'});visit('/guide',extra={'Referer':'http://['})
check(count('source','facebook')==1 and count('source','external')==1 and count('source','internal')==1 and count('source','direct')==1,'Referral categories bounded and deceptive host rejected')
check(count('flow','feed')==1,'Same-environment category pair');visit('/guide',extra={'Referer':'https://localhost'+('/feed' if mount else '/sandbox/feed')});check(count('flow','feed')==1,'No cross-environment navigation pair')
for ua,expected in [('Mozilla/5.0 (iPad) Version/17 Safari/604','tablet'),('Mozilla/5.0 (Android 14) Chrome/130 Safari/537','tablet'),('Mozilla/5.0 (Android 14; Mobile) Chrome/130 Safari/537','mobile')]:
 with app.test_request_context('/',headers={'User-Agent':ua}):check(detail.device_browser()[0]==expected,'Coarse device '+expected)
check(not any(any(x in str(r) for x in ['PRIVATE-TERM','QUERY-SECRET','REFERRER-SECRET','FLOW-SECRET','facebook.com','Windows NT']) for r in raw()),'No raw query referrer or UA strings')
reset()
with app.app_context():
 db=core.get_db();public=db.execute("INSERT INTO circles(name,owner_id,mode,public_read) VALUES ('Stats Public Fixture',?,'discoverable',1)",(users['Writer'],)).lastrowid;hidden=db.execute("INSERT INTO circles(name,owner_id,mode,public_read) VALUES ('PRIVATE-CIRCLE-SENTINEL',?,'hidden',0)",(users['Writer'],)).lastrowid
 for cid,name in [(public,'Stats Public Fixture'),(hidden,'PRIVATE-CIRCLE-SENTINEL')]:
  circleids.ensure(db,cid);circlenames.assign(db,cid,name);db.execute("INSERT INTO circle_members VALUES (?,?,'owner','active',CURRENT_TIMESTAMP)",(cid,users['Writer']))
 public_id=circleids.public(db,public);hidden_id=circleids.public(db,hidden);db.commit()
r=visit('/circles/'+public_id);check(r.status_code==200 and count('destination','c:'+str(public))==1,'Public Circle counted '+str(r.status_code))
r=visit('/circles/'+hidden_id,client=clients['Writer']);check(r.status_code==200 and count('destination','c:'+str(hidden))==0,'Hidden Circle not identified')
r=visit('/vibe/VM%20Fixture%20One');check(r.status_code==200 and count('destination','v:'+str(vid))==1,'Approved Vibe counted')
data=report();check(any('Stats Public Fixture' in x['label'] for x in data['destinations']) and 'PRIVATE-CIRCLE-SENTINEL' not in str(data['destinations']),'Only public labels resolved')
change('UPDATE circles SET mode=\'hidden\',public_read=0 WHERE id=?',(public,));change('INSERT INTO vibe_management(vibe_id,archived) VALUES (?,1)',(vid,))
data=report();csvdata=detail.csv_report(data);check(not data['destinations'] and data['unavailable_destinations']==2,'Privacy changes redact previous public labels');check('Stats Public Fixture' not in csvdata and 'VM Fixture One' not in csvdata and 'c:'+str(public) not in csvdata,'Export redacts now-private identifiers')
change('UPDATE circles SET mode=\'discoverable\',public_read=1 WHERE id=?',(public,));change("UPDATE circles SET name='=FORMULA-SENTINEL' WHERE id=?",(public,));data=report();check('Circle: =FORMULA-SENTINEL' in detail.csv_report(data),'CSV uses safe prefixed public label')
# Calendar boundaries and previous-period comparison, with UTC-hour bucketing.
reset();noon=datetime.combine(today,datetime.min.time(),timezone.utc)+timedelta(hours=12)
detail.write(path,[('page','guide','')]*3,'guest',noon);detail.write(path,[('page','home','')]*2,'guest',noon-timedelta(days=1));detail.write(path,[('signup','created_queued','')],'guest',noon)
data=report(days='custom',start=day,end=day);check(data['totals']['views']==3 and data['previous']['views']==2,'Custom date and equal previous period');check(data['hours'][12]['count']==3,'UTC hour exact');check(data['comparison'][0]['change']==50.0,'Comparison arithmetic');check(data['attempt_ratio']==100.0,'Attempt ratio counts registrations separately')
old=(today-timedelta(days=90)).isoformat();keep=(today-timedelta(days=89)).isoformat()
with sqlite3.connect(path) as db:
 db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(old,'page','home','',2));db.execute('INSERT INTO counters VALUES (?,?,?,?,?)',(keep,'page','home','',2));db.execute('INSERT INTO hourly_counters VALUES (?,?,?,?,?,?)',(old+'T12','guest','page','home','',2));db.execute('INSERT INTO hourly_counters VALUES (?,?,?,?,?,?)',(keep+'T12','guest','page','home','',2))
detail.write(path,[('page','home','')],'guest');check(not any(r[0].startswith(old) for r in raw()) and any(r[0].startswith(keep) for r in raw()),'New counter retention boundary');check(report(days='90')['legacy_views']==2,'Legacy retention boundary')
original_capacity=detail.MAX_ROWS;detail.MAX_ROWS=len(raw())+1;detail.write(path,[('page','home',''),('browser','other',''),('device','unknown',''),('source','external','')],'guest');check(len(raw())<=detail.MAX_ROWS and report()['storage']['skips']>=1,'Global row budget enforced');detail.MAX_ROWS=original_capacity
reset();core.validate_email=lambda e:None;verification.send_verification=lambda *args:'queued'
form={'consent':'on','actual_name':'Fictional Stats Person','email':'detail-one@example.invalid','handle':'DetailFixtureOne','password':'Fictional-Only-Password-4682','dob':'1990-01-01','timezone':'UTC','theme_csrf_token':token}
network=0
def signup(data,extra=None):
 global network
 network+=1;c=app.test_client()
 with c.session_transaction() as s:s['theme_csrf_token']=token
 return c.post('/signup',data=data,headers={**headers,**(extra or {})},environ_overrides={**env,'REMOTE_ADDR':'192.0.2.'+str(network)})
for patch,outcome in [({'consent':''},'agreement'),({'actual_name':''},'name'),({'password':'short'},'password'),({'dob':'2018-01-01'},'eligibility'),({'timezone':'Invalid/Zone'},'timezone')]:
 r=signup({**form,**patch});check(r.status_code in (400,403) and count('signup',outcome)==1,'Specific rejection '+outcome+' '+str(r.status_code))
r=signup({k:v for k,v in form.items() if k!='email'});check(r.status_code==400 and count('signup','fields')==1,'Required fields diagnostic')
r=signup(form,{'Origin':'https://other.example'});check(r.status_code==403 and count('signup','security')==1,'Security rejection diagnostic')
r=signup(form);check(r.status_code==302 and count('signup','created_queued')==1,'Actual signup queued');r=signup(form);check(r.status_code==302 and count('signup','unavailable')==1,'Availability diagnostic')
verification.send_verification=lambda *args:False;r=signup({**form,'email':'detail-two@example.invalid','handle':'DetailFixtureTwo'});check(r.status_code==302 and count('signup','created_mail_problem')==1,'Created account delivery problem')
verification.send_verification=lambda *args:True;r=signup({**form,'email':'detail-three@example.invalid','handle':'DetailFixtureThree'});check(r.status_code==302 and count('signup','created_sent')==1,'Created account mail accepted')
def invalid_email(e):raise ValueError('Fictional bad format')
core.validate_email=invalid_email;r=signup({**form,'email':'detail-four@example.invalid','handle':'DetailFixtureFour'});check(r.status_code==302 and count('signup','invalid_email')==1,'Invalid email format')
with app.app_context():raw_token=verification.issue_token(core.get_db(),'detail-one@example.invalid')
r=visit('/verify_email/'+raw_token);check(r.status_code==200 and count('signup','verified')==1,'Verification success');r=visit('/verify_email/'+raw_token);check(r.status_code==400 and count('signup','verified')==1 and count('signup','verification_invalid')==1,'Verification reuse not success')
original_view=app.view_functions['signup']
from flask import abort
app.view_functions['signup']=lambda:abort(500)
try:
 r=signup(form);check(r.status_code==500 and count('signup','error')==1,'Server error diagnostic without error contents')
finally:app.view_functions['signup']=original_view
c=app.test_client()
with c.session_transaction() as s:s['theme_csrf_token']=token
for i in range(5):r=c.post('/signup',data=form,headers=headers,environ_overrides={**env,'REMOTE_ADDR':'198.51.100.100'})
check(r.status_code==429 and count('signup','limited')==1,'Actual signup rate limit diagnostic')
check(not any(any(x in str(r) for x in ['detail-one','DetailFixture','192.0.2','1990-01-01',raw_token]) for r in raw()),'No signup identities secrets DOB or network retained')
with app.test_request_context('/'):
 db=core.get_db();db.execute("UPDATE users SET bio='UNCOMMITTED-DETAIL-SENTINEL' WHERE id=?",(users['Regular'],));detail.write(path,[('page','home','')],'guest');db.rollback()
check(query('SELECT bio FROM users WHERE id=?',(users['Regular'],))[0][0]!='UNCOMMITTED-DETAIL-SENTINEL','Metrics do not commit account transactions')
lock=sqlite3.connect(path);lock.execute('BEGIN EXCLUSIVE');r=visit('/guide');check(r.status_code==200,'Storage contention fails open');lock.rollback();lock.close()
before=raw();app.config['SITE_STATISTICS_ENABLED']=False;visit('/');check(raw()==before,'Collection disable switch');app.config['SITE_STATISTICS_ENABLED']=True
r=get('Owner','/manage/statistics',traffic='all');check(r.status_code==200 and ('href="'+mount+'/manage/statistics.csv') .encode() in r.data,'Export preserves environment');check(b'Period' in r.data and b'UTC' in r.data,'Filter and timezone instructions');r=get('Owner','/manage/statistics.csv',traffic='all');check(r.status_code==200 and b'UTC period / day / hour' in r.data,'Filtered CSV renders')
check(b'Expanded statistics' in visit('/dev').data and b'public community ids' in visit('/privacy').data.lower(),'Dev log and privacy disclosures updated')
reset();detail.write(path,[('page','home','')]*18+[('page','guide','')]*7+[('flow','home','guide')]*5+[('source','social','')]*12+[('device','mobile','')]*16+[('browser','safari','')]*16+[('signup','created_queued','')]*3+[('signup','password','')]+[('signup','verified','')]*2,'guest',noon);detail.write(path,[('page','guide','')]*4,'staff',noon-timedelta(hours=2))
r=get('Owner','/manage/statistics',traffic='all');check(r.status_code==200,'Fictional final preview');(stage.parent.parent/('preview-'+package+'.html')).write_text(r.data.decode())
print(json.dumps({'package':package,'checks':checks,'counter_rows':len(raw()),'temporary_statistics':str(path).startswith(str(w))}))
