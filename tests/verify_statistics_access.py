from pathlib import Path
import os,sys,tempfile,sqlite3,importlib,contextlib,io,time,json

def _close_fixture_connections(directory):
    import gc, sqlite3
    gc.collect()
    for connection in gc.get_objects():
        if isinstance(connection, sqlite3.Connection):
            try:
                connection.close()
            except sqlite3.Error:
                pass
    gc.collect()
    directory.cleanup()

package=sys.argv[1];stage=Path(sys.argv[2]);_fixture_directory=tempfile.TemporaryDirectory(prefix='neonrest-statistics-test-');w=Path(_fixture_directory.name);import atexit,gc;atexit.register(_close_fixture_connections,_fixture_directory)
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

for who in ['Owner','Admin']:
 with clients[who].session_transaction() as s:s.update(fresh_at=0,factor_at=0)
 for route in ['/manage/statistics','/manage/statistics.csv']:
  for method in ['get','head']:
   r=getattr(clients[who],method)(route,headers=headers,environ_overrides=env)
   check(r.status_code==200,'Stale freshness permits read '+who+method+route)
   check('no-store' in r.headers.get('Cache-Control',''),'Read remains private '+route)
 for route in ['/manage/security','/manage/roles']:
  r=get(who,route);check(r.status_code==302 and 'reauth' in r.location,'Sensitive management still fresh '+route)
 r=clients[who].post('/manage/statistics/search-import',data={'theme_csrf_token':token},environ_overrides=env)
 check(r.status_code==302 and 'reauth' in r.location,'Import still requires fresh auth '+who)
for route in ['/manage/statistics','/manage/statistics.csv']:
 check(visit(route).status_code==403,'Guest blocked '+route)
 check(get('Regular',route).status_code==403,'Member blocked '+route)
 check(get('Moderator',route).status_code==403,'Moderator blocked '+route)
change('UPDATE account_safety SET totp_secret=NULL WHERE user_id=?',(users['Admin'],))
r=get('Admin','/manage/statistics');check(r.status_code==302 and '/account/security' in r.location,'Staff enrollment requirement retained')
change('UPDATE account_safety SET totp_secret=? WHERE user_id=?',('JBSWY3DPEHPK3PXP',users['Admin']))
change('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(users['Admin'],))
r=get('Admin','/manage/statistics');check(r.status_code==302 and '/login' in r.location,'Revoked session cannot read')
change('UPDATE active_sessions SET expires_at=? WHERE user_id=?',(now-1,users['Owner']))
r=get('Owner','/manage/statistics.csv');check(r.status_code==302 and '/login' in r.location,'Expired session cannot export')
check(app.config['RETENTION_ENABLED'] is False,'Erasure remains disabled')
print(json.dumps({'package':package,'checks':checks,'passed':True}))
