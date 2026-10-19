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
suite=importlib.import_module(package+'.statistics_suite')
discovery=importlib.import_module(package+'.site_discovery')
network=importlib.import_module(package+'.network_security')
from xml.etree.ElementTree import fromstring
from urllib.parse import urlsplit,unquote
from PIL import Image
from itsdangerous import URLSafeTimedSerializer
from concurrent.futures import ThreadPoolExecutor
def locations(route,client=None,host=None):
 r=(client or app.test_client()).get(route,headers={**headers,'DNT':'1',**({'Host':host} if host else {})},environ_overrides=env)
 check(r.status_code==200,'XML route '+route)
 check(r.mimetype=='application/xml' and 'no-store' in r.headers['Cache-Control'],'XML content and cache')
 return [n.text for n in fromstring(r.data).iter('{'+discovery.NS+'}loc')]
def all_posts(client=None):
 n=query('SELECT COUNT(*) FROM posts')[0][0]
 return sum((locations('/sitemap/posts-'+str(p)+'.xml',client) for p in range(1,(n+discovery.CHUNK-1)//discovery.CHUNK+1)),[])
r=visit('/favicon.ico');check(r.status_code==200 and r.mimetype=='image/vnd.microsoft.icon','Favicon route')
with Image.open(io.BytesIO(r.data)) as icon:check(icon.format=='ICO' and (32,32) in icon.ico.sizes(),'Multi-size ICO')
check(('href="'+mount+'/favicon.ico"').encode() in visit('/').data,'Environment favicon link')
r=visit('/robots.txt');check(r.status_code==200 and r.mimetype=='text/plain','Robots response')
if mount:
 check(r.data==b'User-agent: *\nDisallow: /\n','Sandbox crawler exclusion')
 check(visit('/guide').headers.get('X-Robots-Tag')=='noindex, nofollow','Sandbox noindex header')
 for route in ['/sitemap.xml','/sitemap/pages.xml','/sitemap/posts-1.xml','/sitemap/circles-1.xml','/sitemap/vibes-1.xml']:check(not locations(route),'Sandbox sitemap empty '+route)
else:
 check(b'Disallow: /sandbox\n' in r.data and b'Sitemap: https://www.neonrest.com/sitemap.xml' in r.data,'Production crawler hints')
 index=locations('/sitemap.xml');check(index and all(x.startswith('https://www.neonrest.com/sitemap/') for x in index),'Canonical sitemap index')
 check(locations('/sitemap.xml',host='attacker.invalid')==index,'Host header cannot poison sitemap')
 check(all(x.startswith('https://www.neonrest.com/') and '/account' not in x and '/sandbox' not in x for x in locations('/sitemap/pages.xml')),'Public landing pages only')
 public_pid,public_token=post_fixture('PRACTICE ONLY sitemap public sentinel')
 private_pid,private_token=post_fixture('PRIVATE SITEMAP SENTINEL','private')
 teen_pid,teen_token=post_fixture('TEEN SITEMAP SENTINEL');change('UPDATE posts SET user_id=? WHERE id=?',(users['Teen'],teen_pid))
 protected_pid,protected_token=post_fixture('PROTECTED SITEMAP SENTINEL');change('INSERT INTO protected_age_posts(post_id) VALUES (?)',(protected_pid,))
 urls=all_posts();check('https://www.neonrest.com/posts/'+public_token in urls,'Public adult post discoverable')
 check(all(not any(t in u for u in urls) for t in [private_token,teen_token,protected_token]),'Private teen and protected posts excluded')
 check(all_posts(clients['Owner'])==urls,'Owner privileges cannot expand sitemap')
 change('UPDATE post_privacy SET audience=\'private\' WHERE post_id=?',(public_pid,));check(not any(public_token in u for u in all_posts()),'Visibility revocation reflected immediately')
 change('UPDATE post_privacy SET audience=\'public\' WHERE post_id=?',(public_pid,));change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(public_pid,users['Writer'],users['Owner'],'Fictional test'))
 check(not any(public_token in u for u in all_posts()),'Moderation hides sitemap post');change('DELETE FROM moderated_posts WHERE post_id=?',(public_pid,))
 change('INSERT OR REPLACE INTO account_disables(user_id,disabled,reason,updated_by) VALUES (?,1,?,?)',(users['Writer'],'Fictional disabled account',users['Owner']))
 check(not any(public_token in u for u in all_posts()),'Disabled author excluded');change('DELETE FROM account_disables WHERE user_id=?',(users['Writer'],))
 with app.app_context():
  db=core.get_db();cid=db.execute("INSERT INTO circles(name,owner_id,mode,public_read) VALUES ('Sitemap Circle',?,'discoverable',1)",(users['Writer'],)).lastrowid
  circleids.ensure(db,cid);circlenames.assign(db,cid,'Sitemap Circle');ctoken=circleids.public(db,cid);db.execute("INSERT INTO circle_members VALUES (?,?,'owner','active',CURRENT_TIMESTAMP)",(cid,users['Writer']));db.commit()
 cp,cp_token=post_fixture('PUBLIC CIRCLE SITEMAP');cprivate,cprivate_token=post_fixture('PRIVATE CIRCLE SITEMAP')
 for pid,audience in [(cp,'public'),(cprivate,'private')]:
  change('INSERT INTO circle_posts VALUES (?,?)',(pid,cid));change('INSERT INTO circle_post_visibility VALUES (?,?)',(pid,audience))
 urls=all_posts();check(any(cp_token in u for u in urls) and not any(cprivate_token in u for u in urls),'Circle per-post visibility respected')
 circle_page=(query('SELECT COUNT(*) FROM circles WHERE id<=?',(cid,))[0][0]-1)//discovery.CHUNK+1
 circle_route='/sitemap/circles-'+str(circle_page)+'.xml'
 check(any(ctoken in u for u in locations(circle_route)),'Public Circle discoverable')
 change("UPDATE circles SET mode='hidden' WHERE id=?",(cid,));check(not any(ctoken in u for u in locations(circle_route)) and not any(cp_token in u for u in all_posts()),'Hidden Circle and its posts removed')
 change("UPDATE circles SET mode='discoverable',archived=1 WHERE id=?",(cid,));check(not any(ctoken in u for u in locations(circle_route)),'Archived Circle excluded')
 escaped=change('INSERT INTO vibes(name) VALUES (?)',('Sitemap & <Fixture>',))
 vp=(query('SELECT COUNT(*) FROM vibes WHERE id<=?',(escaped,))[0][0]-1)//discovery.CHUNK+1
 vibe_route='/sitemap/vibes-'+str(vp)+'.xml';check(any('Sitemap & <Fixture>' in unquote(u) for u in locations(vibe_route)),'XML escaping and URL encoding')
 change('INSERT INTO pending_vibes(vibe_id) VALUES (?)',(escaped,));check(not any('Sitemap & <Fixture>' in unquote(u) for u in locations(vibe_route)),'Pending Vibe excluded');change('DELETE FROM pending_vibes WHERE vibe_id=?',(escaped,))
 change('INSERT INTO vibe_management(vibe_id,archived) VALUES (?,1)',(escaped,));check(not any('Sitemap & <Fixture>' in unquote(u) for u in locations(vibe_route)),'Archived Vibe excluded')
 check(visit('/sitemap/private-1.xml').status_code==404 and visit('/sitemap/posts-0.xml').status_code==404 and visit('/sitemap/posts-50001.xml').status_code==404,'Sitemap route bounds')

# Validate measurement with a clean isolated analytics sidecar.
with sqlite3.connect(path) as db:
 for table in ['browser_sessions','visitor_days','crawler_counters','hourly_counters']:db.execute('DELETE FROM '+table)
c=app.test_client();r=visit('/guide',client=c)
check(not any(('analytics_visitor=' in h or 'analytics_session=' in h) and 'Max-Age=0' not in h for h in r.headers.getlist('Set-Cookie')),'No identifiers before consent')
with c.session_transaction() as s:csrf=s['theme_csrf_token']
def consent(client=c,choice='yes',extra=None):return client.post('/analytics/preference',data={'choice':choice,'theme_csrf_token':csrf},headers={**headers,**(extra or {})},environ_overrides=env)
r=consent();cookie_headers=r.headers.getlist('Set-Cookie')
check(all(any('analytics_'+kind+'=' in h and 'Secure' in h and 'HttpOnly' in h and 'SameSite=Lax' in h and 'Path='+ (mount or '/') in h for h in cookie_headers) for kind in ['visitor','session']),'Consent bootstraps scoped secure IDs')
cookie_prefix='nr_sandbox_analytics_' if mount else 'nr_analytics_';cookie_path=mount or '/'
decode_cookie=lambda value: URLSafeTimedSerializer(app.secret_key,salt='neonrest-optional-analytics-v1').loads(value)
initial_visitor=c.get_cookie(cookie_prefix+'visitor',path=cookie_path).value;initial_session=c.get_cookie(cookie_prefix+'session',path=cookie_path).value
for _ in range(3):consent()
check(decode_cookie(c.get_cookie(cookie_prefix+'visitor',path=cookie_path).value)==decode_cookie(initial_visitor) and decode_cookie(c.get_cookie(cookie_prefix+'session',path=cookie_path).value)==decode_cookie(initial_session),'Repeated consent reuses identity and session')
with sqlite3.connect(path) as db:check(db.execute('SELECT COUNT(*) FROM browser_sessions').fetchone()[0]==0,'Consent POST is not a page or interaction')
visit('/guide',client=c);visit('/privacy',client=c)
with sqlite3.connect(path) as db:
 check(db.execute('SELECT COUNT(*),SUM(pages) FROM browser_sessions').fetchone()==(1,2),'Refresh and navigation use one session')
 check(db.execute('SELECT COUNT(DISTINCT visitor) FROM visitor_days').fetchone()[0]==1,'Unique browser deduplication')
 db.execute('UPDATE browser_sessions SET last_seen=last_seen-1900,started=started-2000')
# Identical cookie snapshots model concurrent browser requests before either response sets cookies.
cookie_snapshot={kind:c.get_cookie(cookie_prefix+kind,path=cookie_path).value for kind in ['choice','visitor','session']}
def parallel_visit(_):
 client=app.test_client()
 for kind,value in cookie_snapshot.items():client.set_cookie(cookie_prefix+kind,value,path=cookie_path)
 return visit('/guide',client=client).status_code
with ThreadPoolExecutor(max_workers=3) as pool:check(list(pool.map(parallel_visit,range(3)))==[200,200,200],'Concurrent requests serve successfully')
with sqlite3.connect(path) as db:
 check(db.execute('SELECT COUNT(*),SUM(pages) FROM browser_sessions').fetchone()==(2,5),'Concurrent inactivity renewal creates one new session')
 check(db.execute('SELECT COUNT(DISTINCT visitor) FROM visitor_days').fetchone()[0]==1,'Expiry retains one browser')
before=raw();r=consent(extra={'DNT':'1'});check(any('analytics_visitor=' in h and 'Max-Age=0' in h for h in r.headers.getlist('Set-Cookie')),'DNT overrides consent bootstrap');visit('/guide',client=c,extra={'DNT':'1'});check(raw()==before,'DNT does not collect')
r=consent(choice='no');check(any('analytics_session=' in h and 'Max-Age=0' in h for h in r.headers.getlist('Set-Cookie')),'Opt out clears session')
for route in ['/password-reset','/password-reset/FAKE-TOKEN','/media-file/fake.png','/social-preview/default.png','/favicon.ico','/robots.txt','/sitemap.xml','/account/security','/manage/statistics']:
 before=count('request');timing=count('latency');visit(route);check(count('request')==before and count('latency')==timing,'Exclude private/assets from requests and timing '+route)
for rule in ['/privacy/submit','/reauth','/login/factor','/verify_email/<token>','/family/data/<request_id>']:
 check(not suite.reportable_route(rule),'Sensitive workflow definition excluded '+rule)
before=count('request');visit('/blog/wp-includes/wlwmanifest.xml');check(count('request')==before,'Scanner probe excluded from human denominator')
visit('/social-preview/default.png',extra={'User-Agent':'facebookexternalhit/1.1'});visit('/robots.txt',extra={'User-Agent':'bingbot/2.0'})
with sqlite3.connect(path) as db:check(db.execute('SELECT SUM(value) FROM crawler_counters').fetchone()[0]==2,'Public crawler assets retained separately')
for route in ['/blog/wp-includes/wlwmanifest.xml','/cms/wp-admin/login.php','/foo/xmlrpc.php','/foo/%77p-content/example.php']:
 with app.test_request_context(route):check(network.classification()=='Suspected scanning','Nested/encoded scan '+route)
with app.test_request_context('/ordinary-wordpress-discussion'):check(network.classification()=='Unclassified','WordPress substring does not flag ordinary URL')
# Historical excluded routes are hidden from derived reports, without deleting counters.
detail.write(path,[('request','/password-reset/<reset_token>','404'),('latency','GET /media-file/<filename>','100')],'guest')
with app.test_request_context('/manage/statistics',environ_overrides=env):
 opts=detail.options();data={'suite':suite.report(path,opts),'insights':importlib.import_module(package+'.statistics_insights').report(path,opts)}
check(not any('password-reset' in r['label'] for r in data['suite']['errors']),'Historic private request labels excluded from report')
check(not any('/media-file' in r['label'] for r in data['insights']['performance']),'Historic asset timing excluded from report')
check(any(r[3]=='/password-reset/<reset_token>' for r in raw()),'Historic records are preserved')
check(app.config['RETENTION_ENABLED'] is False,'Permanent erasure remains disabled')
print(json.dumps({'checks':checks,'package':package,'passed':True}))
