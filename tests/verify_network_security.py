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

net=importlib.import_module(package+'.network_security');detail=importlib.import_module(package+'.statistics_detail');stats=importlib.import_module(package+'.site_statistics')
path=app.extensions['network_security']['path'];check(str(path).startswith(str(w)),'Private security store isolated');check(app.config['CLIENT_IP_MODE']=='direct','Local mode ignores forwarding by default')
def sq(sql,args=()):
 with sqlite3.connect(path) as db:db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(sql,args)]
def mutate(sql,args=()):
 with sqlite3.connect(path) as db:db.execute(sql,args)
base={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0'}
def visit(route='/guide',client=None,ip='198.51.100.10',headers=None,method='GET',data=None):return (client or app.test_client()).open(route,method=method,data=data,headers={**base,**(headers or {})},environ_overrides={**env,'REMOTE_ADDR':ip})
def ban(ip='198.51.100.10',client=None,**extra):return visit('/manage/security/ban',client=client or clients['Owner'],ip='198.51.100.1',method='POST',data={'ip':ip,'hours':'1','reason':'PRACTICE ONLY: repeated fictional scanning','shared_warning':'yes','theme_csrf_token':token,**extra})
for who in ['Owner','Admin']:
 r=get(who,'/manage/security');check(r.status_code==200,'Security access '+who);check(b'Security logs and IP restrictions' in r.data and b'Expires after' in r.data,'Instructions and controls '+who);check('no-store' in r.headers['Cache-Control'] and r.headers['Referrer-Policy']=='no-referrer','Private headers '+who)
with clients['Owner'].session_transaction() as s:s.pop('theme_csrf_token',None)
r=get('Owner','/manage/security')
with clients['Owner'].session_transaction() as s:new_csrf=s.get('theme_csrf_token','')
check(r.status_code==200 and bool(new_csrf) and ('value="'+new_csrf+'"').encode() in r.data,'Fresh reauthorization produces a usable form')
with clients['Owner'].session_transaction() as s:s['theme_csrf_token']=token

for who in ['Regular','Moderator','Manager','SiteManager','Teen']:
 check(get(who,'/manage/security').status_code==403,'No security access '+who);check(ban(client=clients[who]).status_code==403,'No restriction access '+who)
check(visit('/manage/security').status_code==403,'Guest security denied')
with clients['Owner'].session_transaction() as s:s['fresh_at']=0
r=get('Owner','/manage/security');check(r.status_code==302 and 'reauth' in r.location,'Security fresh auth')
with clients['Owner'].session_transaction() as s:s['fresh_at']=now
change('UPDATE account_safety SET totp_secret=NULL WHERE user_id=?',(users['Admin'],));r=get('Admin','/manage/security');check(r.status_code==302 and '/account/security' in r.location,'Security requires 2FA');change('UPDATE account_safety SET totp_secret=? WHERE user_id=?',('JBSWY3DPEHPK3PXP',users['Admin']))
for field,patch in [('csrf',{'theme_csrf_token':''}),('reason',{'reason':''}),('duration',{'hours':'8760'}),('shared warning',{'shared_warning':''}),('CIDR',{'ip':'198.51.100.0/24'}),('invalid IP',{'ip':'not-an-address'})]:check(ban(**patch).status_code==400,'Restriction validation '+field)
check(ban(ip='198.51.100.1').status_code==400,'Cannot restrict current address')
r=visit('/manage/security/ban',client=clients['Owner'],ip='198.51.100.1',method='POST',headers={'Origin':'https://evil.invalid'},data={'ip':'198.51.100.10','hours':'1','reason':'PRACTICE ONLY: test','shared_warning':'yes','theme_csrf_token':token});check(r.status_code==403,'Restriction rejects cross-origin POST')
check(not sq('SELECT * FROM ip_bans'),'Rejected forms create no restrictions')
check(ban().status_code==302,'Create exact-address restriction');row=sq('SELECT * FROM ip_bans')[0];check(3500<=row['expires']-int(time.time())<=3600,'Restriction exact expiry');check(ban().status_code==409,'Duplicate active restriction rejected')
r=visit('/guide');check(r.status_code==403 and b'temporarily restricted' in r.data,'Restricted anonymous request blocked');check(visit('/guide',ip='198.51.100.11').status_code==200,'Other address unaffected');check(visit('/guide',client=clients['Regular']).status_code==403,'Restricted member blocked');check(visit('/guide',client=clients['Owner']).status_code==200,'Verified owner session can recover');check(visit('/privacy').status_code==200,'Privacy remains accessible');check(visit('/terms').status_code==200,'Terms remain accessible')
check(visit('/manage/security/ban/'+str(row['id'])+'/revoke',client=clients['Owner'],method='POST',data={'theme_csrf_token':token,'reason':'PRACTICE ONLY: release'}).status_code==302,'Release restriction');check(visit('/guide').status_code==200,'Released address immediately restored')
check(ban(hours='24').status_code==302,'24-hour restriction');active=sq('SELECT * FROM ip_bans WHERE revoked=0')[0];mutate('UPDATE ip_bans SET expires=? WHERE id=?',(now-1,active['id']));check(visit('/guide').status_code==200,'Expired restriction stops automatically')
check(ban(ip='2001:db8::11',hours='168').status_code==302,'IPv6 restriction');check(visit('/guide',ip='2001:0db8:0:0:0:0:0:11').status_code==403,'IPv6 normalized for matching');check(net.canonical('::ffff:198.51.100.11')=='198.51.100.11','IPv4-mapped IPv6 normalized')
# Explicit trust mode. Neither XFF nor an untrusted direct header can select another bucket.
visit('/network-direct-missing',ip='198.51.100.12',headers={'X-Real-IP':'198.51.100.13','X-Forwarded-For':'198.51.100.14'})
check(bool(sq("SELECT 1 FROM security_events WHERE ip='198.51.100.12' AND path='/network-direct-missing'")),'Direct mode ignores forwarded headers')
app.config['CLIENT_IP_MODE']='pythonanywhere'
visit('/network-proxy-missing',ip='10.0.0.1',headers={'X-Real-IP':'198.51.100.20','X-Forwarded-For':'198.51.100.99, 198.51.100.20'})
check(bool(sq("SELECT 1 FROM security_events WHERE ip='198.51.100.20' AND path='/network-proxy-missing'")),'PA header chooses validated client');check(not sq("SELECT 1 FROM security_events WHERE ip='198.51.100.99'"),'Spoofed XFF ignored')
visit('/network-invalid-header',ip='10.0.0.1',headers={'X-Real-IP':'198.51.100.20, 198.51.100.30'})
check(not sq("SELECT 1 FROM security_events WHERE path='/network-invalid-header'"),'Malformed proxy header not replaced with shared balancer')
# Exercise the unchanged actual limiter with two real WSGI requests using different trusted addresses.
for address in ['198.51.100.31','198.51.100.32']:
 visit('/login',method='POST',headers={'X-Real-IP':address},data={'theme_csrf_token':'invalid'},ip='10.0.0.1')
with app.app_context():
 keys=[cf.digest('network:'+x) for x in ['198.51.100.31','198.51.100.32']];rows=core.get_db().execute("SELECT subject FROM rate_buckets WHERE action='authentication' AND subject IN (?,?)",keys).fetchall();check(len(rows)==2,'Authentication network buckets separate actual clients')
app.config['CLIENT_IP_MODE']='direct'
for raw_path,forbidden in [('/verify_email/PRIVATE-TOKEN','PRIVATE-TOKEN'),('/%76erify_email/PRIVATE-TOKEN','PRIVATE-TOKEN'),('/password/%2572eset/SECRET','SECRET'),('/@PrivateHandle','PrivateHandle'),('/posts/PrivatePostKey012345','PrivatePostKey'),('/broken?code=QUERY-SECRET','QUERY-SECRET'),('/198.51.100.50','198.51.100.50'),('/email@example.com','example.com'),('/%0d%0aINJECTION','INJECTION')]:check(forbidden not in net.path_detail(raw_path),'Path redacts '+forbidden)
check(net.path_detail('/wp-admin/admin-ajax.php')=='/wp-admin/admin-ajax.php','Scanner path useful');check(net.path_detail('/Sandbox/circles')=='/Sandbox/circles','Case typo remains diagnosable')
visit('/wp-admin/admin-ajax.php?token=QUERY-SECRET',headers={'Referer':'http://localhost'+mount+'/posts/PRIVATE-REFERRER?secret=REF-SECRET'})
rows=sq("SELECT * FROM error_details WHERE path='/wp-admin/admin-ajax.php'");check(len(rows)==1 and rows[0]['classification']=='Suspected scanning','Scanning labelled without auto ban');check(rows[0]['referrer']=='/posts/<string:post_id>','Referring page uses template')
visit('/wp-admin/admin-ajax.php');rows=sq("SELECT * FROM security_events WHERE path='/wp-admin/admin-ajax.php'");check(sum(r['count'] for r in rows)==2,'Security events grouped with counts');check(all(r['first_seen']<=r['last_seen'] for r in rows),'First and last timestamps')
visit('/verify_email/VERY-PRIVATE-TOKEN?password=PRIVATE',headers={'Referer':'https://external.example/private?token=PRIVATE'})
allrows=str(sq('SELECT * FROM error_details'))+str(sq('SELECT * FROM security_events'));check(all(x not in allrows for x in ['QUERY-SECRET','REF-SECRET','PRIVATE-REFERRER','VERY-PRIVATE-TOKEN','password=']),'No sensitive path/query/referrer values stored')
count_before=len(sq('SELECT * FROM error_details'));visit('/dnt-privacy-check',headers={'DNT':'1'});check(len(sq('SELECT * FROM error_details'))==count_before,'DNT excludes diagnostic analytics');check(bool(sq("SELECT * FROM security_events WHERE path='/dnt-privacy-check'")),'Security protection independent of analytics opt out')
visit('/gpc-privacy-check',headers={'Sec-GPC':'1'});check(len(sq('SELECT * FROM error_details'))==count_before,'GPC excludes diagnostic analytics')
r=get('Owner','/manage/statistics');check(r.status_code==200 and b'Error request details' in r.data ,'Dashboard shows redacted detail');check(b'198.51.100.10' not in r.data,'Statistics HTML has no client IP')
r=get('Owner','/manage/statistics.csv');check(r.status_code==200 and b'Redacted error requests' in r.data and b'198.51.100.10' not in r.data,'CSV has diagnostics without IPs')
r=visit('/manage/security',client=clients['Owner'],method='POST',data={'theme_csrf_token':token,'ip':'198.51.100.20'});check(r.status_code==200 and any(v=='198.51.100.20' for v in __import__('re').findall(r'<code>([^<]+)</code>',r.data.decode())),'Private POST address filtering');check('ip=' not in (r.location or ''),'Address not placed in filter URL')
check(bool(sq("SELECT 1 FROM network_audit WHERE action='Create IP restriction'")) and bool(sq("SELECT 1 FROM network_audit WHERE action='Revoke IP restriction'")) and bool(sq("SELECT 1 FROM network_audit WHERE action='View security log'")),'Views and changes audited')
old_day=(int(time.time())-net.RETENTION)//86400-1
mutate('INSERT INTO security_events VALUES (?,?,?,?,?,?,?,?,?,?)',(old_day,'198.51.100.200',0,'test','GET','/old',404,now-net.RETENTION-1,now-net.RETENTION-1,1));mutate('INSERT INTO network_audit(at,actor,action,target,reason) VALUES (?,?,?,?,?)',(now-net.RETENTION-1,0,'old','',''))
with net.connect(path) as db:net.prune(db,int(time.time()),force=True)
check(not sq("SELECT 1 FROM security_events WHERE path='/old'") and not sq("SELECT 1 FROM network_audit WHERE action='old'"),'Private retention removes expired rows')

hold=change('INSERT INTO privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) VALUES (?,?,?,?,?,?,?)',(users['Regular'],'PRACTICE ONLY: preserve fictional security evidence','Fictional test only','FIXTURE-NETWORK-HOLD',1,now,now+86400))
mutate('INSERT INTO security_events VALUES (?,?,?,?,?,?,?,?,?,?)',(old_day,'198.51.100.201',users['Regular'],'held fixture','GET','/held-record',404,now-net.RETENTION-1,now-net.RETENTION-1,1))
mutate('INSERT INTO ip_bans(ip,created,expires,actor,reason,revoked) VALUES (?,?,?,?,?,0)',('198.51.100.201',now-net.RETENTION-100,now-net.RETENTION-1,users['Admin'],'PRACTICE ONLY: aged restriction'))
with app.app_context():
 with net.connect(path) as db:net.prune(db,int(time.time()),force=True)
check(bool(sq("SELECT 1 FROM security_events WHERE path='/held-record'")) and bool(sq("SELECT 1 FROM ip_bans WHERE ip='198.51.100.201'")),'Existing hold preserves associated security and restriction records')
check(visit('/guide',ip='198.51.100.201').status_code==200,'Evidence preservation does not extend expired ban')
change('UPDATE privacy_holds SET released_at=? WHERE id=?',(now,hold))
with app.app_context():
 with net.connect(path) as db:net.prune(db,int(time.time()),force=True)
check(not sq("SELECT 1 FROM security_events WHERE path='/held-record'") and not sq("SELECT 1 FROM ip_bans WHERE ip='198.51.100.201'"),'Released hold permits overdue security cleanup')

old_cap=net.EVENT_CAP;net.EVENT_CAP=len(sq('SELECT * FROM security_events'));before=len(sq('SELECT * FROM security_events'));visit('/capacity-test');check(len(sq('SELECT * FROM security_events'))==before,'Security storage bounded');net.EVENT_CAP=old_cap
lock=sqlite3.connect(path);lock.execute('BEGIN EXCLUSIVE');r=visit('/guide',ip='198.51.100.80');check(r.status_code==200,'Unavailable security storage does not break site');r=get('Owner','/manage/security');check(r.status_code==503,'Busy private log returns safe unavailable status');lock.rollback();lock.close()
check(sq('PRAGMA integrity_check')[0]['integrity_check']=='ok','Private store integrity');import stat;check(stat.S_IMODE(path.stat().st_mode)==0o600,'Private file permissions')
# A stale owner session does not bypass a restriction.
change('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(users['Owner'],));r=visit('/guide',client=clients['Owner'],ip='2001:db8::11');check(r.status_code in (302,403),'Revoked staff session gets no content');
if r.status_code==302:
 next_path=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(r.location).path
 if mount and next_path.startswith(mount):next_path=next_path[len(mount):] or '/'
 check(visit(next_path,client=clients['Owner'],ip='2001:db8::11').status_code==403,'Revoked session redirect remains IP restricted')
change('UPDATE active_sessions SET revoked=0 WHERE user_id=?',(users['Owner'],))
with clients['Owner'].session_transaction() as s:s.update(user_id=users['Owner'],user_handle='@VMFixtureOwner',user_email='vm-owner@example.invalid',sid='fictional-vm-Owner',fresh_at=now,factor_at=now,theme_csrf_token=token)
preview=get('Owner','/manage/security');check(preview.status_code==200,'Final security preview');(stage.parent.parent/('security-preview-'+package+'.html')).write_text(preview.data.decode())
print(json.dumps({'package':package,'checks':checks,'security_isolated':str(path).startswith(str(w)),'security_rows':len(sq('SELECT * FROM security_events'))}))
