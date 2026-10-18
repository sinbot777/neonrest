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
ins=importlib.import_module(package+'.statistics_insights')
ins.initialize(path);ins.initialize(path)
def insights(traffic='all',**kwargs):
 with app.test_request_context('/manage/statistics',query_string={'traffic':traffic,**kwargs},environ_overrides=env):return ins.report(path,detail.options())
def submit(who='Owner',data=None,extra=None):
 return clients[who].post('/manage/statistics/search-import',data=data or form,headers={**headers,**(extra or {})},environ_overrides=env)
form={'provider':'google','start':day,'end':day,'csv':'Top queries,Clicks,Impressions,Position\nneonrest,2,10,3.5\n"<script>fiction</script>",0,2,9\n=FORMULA(),0,1,5\n','theme_csrf_token':token}
for who in ['Owner','Admin']:
 r=get(who,'/manage/statistics',traffic='all');check(r.status_code==200 and b'Acquisition and signup funnels' in r.data and b'Server response performance' in r.data and b'Search discovery' in r.data,'New reports render '+who)
for who in ['Moderator','SiteManager','Manager','OtherManager','Regular','Teen']:
 check(submit(who).status_code==403,'Import permission '+who)
check(app.test_client().post('/manage/statistics/search-import',data=form,environ_overrides=env).status_code==403,'Guest import forbidden')
with clients['Owner'].session_transaction() as s:s['fresh_at']=0
r=submit();check(r.status_code==302 and 'reauth' in r.location,'Import requires fresh auth')
with clients['Owner'].session_transaction() as s:s['fresh_at']=now
change('UPDATE account_safety SET totp_secret=NULL WHERE user_id=?',(users['Admin'],));r=submit('Admin');check(r.status_code==302 and '/account/security' in r.location,'Import requires 2FA');change('UPDATE account_safety SET totp_secret=? WHERE user_id=?',('JBSWY3DPEHPK3PXP',users['Admin']))
check(submit(data={**form,'theme_csrf_token':''}).status_code==403,'Import CSRF')
check(submit(extra={'Origin':'https://evil.example'}).status_code==403,'Import origin')
check(submit().status_code==302,'Google query CSV accepted')
sr=insights();check(len(sr['imports'])==1 and sr['imports'][0]['rows']==3,'Query snapshot stored')
check(sr['imports'][0]['queries'][0]['ctr']==20.0 and sr['imports'][0]['queries'][0]['position']==3.5,'Query CTR and position exact')
r=get('Owner','/manage/statistics',traffic='all');check(b'&lt;script&gt;fiction&lt;/script&gt;' in r.data and b'<script>fiction</script>' not in r.data,'Query HTML escaped')
check('no-store' in r.headers.get('Cache-Control',''),'Search report private cache')
r=get('Owner','/manage/statistics.csv',traffic='all');export=list(__import__('csv').DictReader(io.StringIO(r.data.decode())))
check(any(x['Label'].startswith("'=FORMULA()") for x in export),'Search CSV formula neutralized')
check(any(x['Section'].startswith('Search google') and x['Label']=='neonrest · clicks' and x['Count']=='2' for x in export),'Search CSV values')
check(submit(data={**form,'csv':'Query,Clicks,Impressions\nneonrest,3,12\n'}).status_code==302,'Exact snapshot replace')
sr=insights();check(len(sr['imports'])==1 and sr['imports'][0]['rows']==1 and sr['imports'][0]['queries'][0]['clicks']==3,'Replace does not duplicate totals')
check(submit(data={**form,'provider':'bing','csv':'Keywords,Clicks,Impressions,Average position\nneonrest,1,20,7\n'}).status_code==302,'Bing keywords accepted')
for patch in [{'provider':'other'},{'start':'bad'},{'start':(today-timedelta(days=90)).isoformat()},{'end':(today+timedelta(days=1)).isoformat()},{'start':(today-timedelta(days=1)).isoformat(),'end':day}]:
 check(submit(data={**form,**patch}).status_code==400,'Invalid provider date or overlap')
for text in ['Wrong,Clicks,Impressions\nx,1,2\n','Query,Clicks,Impressions\nx,-1,2\n','Query,Clicks,Impressions\nx,3,2\n','Query,Clicks,Impressions,Position\nx,1,2,nan\n','Query,Clicks,Impressions\nx,1,2\nx,1,2\n','Query,Clicks,Impressions\n','Query,Clicks,Impressions\nx,1.5,2\n']:
 check(submit(data={**form,'csv':text}).status_code==400,'Malformed CSV rejected')
check(insights()['imports'][0]['rows']==1,'Invalid import preserves prior snapshot')
check(ins.parse_export('\ufeffQuery,Clicks,Impressions\nx,"1,000","2,000"\n')[0][1:3]==(1000,2000),'BOM and quoted thousands')
try:ins.parse_export('Query,Clicks,Impressions\n'+''.join('q'+str(i)+',0,1\n' for i in range(2001)));raise AssertionError('Unbounded import')
except ValueError:check(True,'Import row cap')
check(submit(data={**form,'csv':'x'*1100001}).status_code==413,'Oversized request rejected')
prior=ins.MAX_SEARCH_ROWS;ins.MAX_SEARCH_ROWS=1
try:
 check(submit(data={**form,'csv':'Query,Clicks,Impressions\nx,0,1\n'}).status_code==400,'Global query cap')
finally:ins.MAX_SEARCH_ROWS=prior
check(len(insights()['imports'])==2,'Failed capacity import atomic')
yesterday=(today-timedelta(days=1)).isoformat()
with sqlite3.connect(path) as db:
 db.execute('INSERT INTO search_imports(provider,start,end,imported,rows) VALUES (?,?,?,?,?)',('google',(today-timedelta(days=90)).isoformat(),yesterday,day,1));oldbatch=db.execute('SELECT last_insert_rowid()').fetchone()[0];db.execute('INSERT INTO search_queries VALUES (?,?,?,?,?)',(oldbatch,'old-query',1,2,1));ins.prune_search(db)
 check(db.execute('SELECT COUNT(*) FROM search_queries WHERE batch=?',(oldbatch,)).fetchone()[0]==0,'Search retention prunes query payload')
 check(db.execute('SELECT COUNT(*) FROM search_imports WHERE id=?',(oldbatch,)).fetchone()[0]==0,'Search retention prunes metadata')
# Deterministic session acquisition arithmetic, independent of real accounts.
with sqlite3.connect(path) as db:
 db.execute('DELETE FROM browser_sessions')
 for key,source,signup_flag,submitted,converted,segment in [('one','google',1,1,1,'guest'),('two','google',0,0,0,'guest'),('three','facebook',1,1,0,'member'),('four','direct',1,1,1,'staff')]:
  db.execute('INSERT INTO browser_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,'fictional-hash-'+key,now-4000,now-2000,segment,1 if key=='two' else 3,0,'home','guide',signup_flag,submitted,converted,source))
sr=insights('ordinary');google=next(r for r in sr['sources'] if r['label']=='Google');check(google['sessions']==2 and google['signup']==1 and google['submitted']==1 and google['registered']==1 and google['conversion']==50.0,'Source funnel exact')
check(sr['sessions']==3 and sr['landings'][0]['sessions']==3,'Ordinary funnel excludes staff')
check(insights('staff')['sessions']==1 and insights('member')['sources'][0]['label']=='Facebook','Session segment filters')
check(sum(x['count'] for x in sr['depth'])==3 and sr['depth'][0]['count']==1,'Completed session depth')
check(len(insights('guest')['imports'])==len(insights('staff')['imports']),'Search reports independent of visitor filter')
# Timer and feature hooks store only route templates and status classes.
reset();visit('/guide?secret=PRIVATE-QUERY',extra={'Referer':'https://www.google.com/search?q=PRIVATE-SEARCH'})
check(count('latency','GET /guide')==1,'Server latency sample')
before=raw();visit('/guide',extra={'DNT':'1'});visit('/guide',extra={'Sec-GPC':'1'});visit('/guide',extra={'User-Agent':'Googlebot'});check(raw()==before,'Privacy signals and bots excluded from insights')
for route in ['/account/security','/manage/statistics','/unknown-private-secret','/static/css/site-statistics.css']:
 before=count('latency');visit(route);check(count('latency')==before,'Sensitive timing excluded '+route)
from flask import abort
original=app.view_functions['signup'];app.view_functions['signup']=lambda:abort(500)
try:
 c=app.test_client()
 with c.session_transaction() as s:s['theme_csrf_token']=token
 r=c.post('/signup',data={'theme_csrf_token':token,'consent':'on','actual_name':'Fictional Insights Person','email':'insights-only@example.invalid','handle':'InsightsFixtureOnly','password':'Fictional-Only-Password-4682','dob':'1990-01-01','timezone':'UTC'},headers=headers,environ_overrides={**env,'REMOTE_ADDR':'192.0.2.199'})
 check(r.status_code==500 and count('feature_result','signup')==1,'Feature server failure class recorded '+str(r.status_code)+' count '+str(count('feature_result','signup')))
finally:app.view_functions['signup']=original
detail.write(path,[('latency','GET /fictional/<id>','100')]*19+[('latency','GET /fictional/<id>','5000')],'guest')
perf=next(r for r in insights()['performance'] if r['label']=='GET /fictional/<id>')
check(perf['count']==20 and perf['p50']=='≤ 100 ms' and perf['p95']=='≤ 100 ms' and perf['slow']==1 and perf['slow_rate']==5.0,'Histogram percentile bound and slow math')
detail.write(path,[('latency','GET /slow','over')],'guest');check(next(r for r in insights()['performance'] if r['label']=='GET /slow')['p95']=='> 10000 ms','Open ended timing bucket')
check(not any('PRIVATE-' in str(r) or '192.0.2' in str(r) for r in raw()),'No raw private query or IP in counters')
lock=sqlite3.connect(path);lock.execute('BEGIN EXCLUSIVE')
try:check(visit('/guide').status_code==200,'Busy storage cannot break site')
finally:lock.rollback();lock.close()
app.config['SITE_STATISTICS_ENABLED']=False;before=raw();visit('/guide');check(raw()==before,'Disable switch honored');app.config['SITE_STATISTICS_ENABLED']=True
r=get('Owner','/manage/statistics',traffic='all');check(r.status_code==200 and ('action="'+mount+'/manage/statistics/search-import"').encode() in r.data,'Import preserves environment prefix');(stage.parent.parent/('insights-preview-'+package+'.html')).write_text(r.data.decode())
check(b'Discovery, engagement and reliability statistics' in visit('/dev').data and b'aggregate search phrases' in visit('/privacy').data,'Devlog and privacy disclosures')
print(json.dumps({'package':package,'checks':checks,'isolated':str(path).startswith(str(w))}))
