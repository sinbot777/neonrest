from pathlib import Path
import os,sys,tempfile,sqlite3,importlib,contextlib,io,time,json
package=sys.argv[1];stage=Path(sys.argv[2]);tmp=tempfile.TemporaryDirectory();w=Path(tmp.name)
src=sqlite3.connect('file:/home/sinbot/db/'+package+'.db?mode=ro',uri=True);dst=sqlite3.connect(w/'fixture.db');src.backup(dst);src.close();dst.close()
prefix='NEONREST_PRODUCTION' if package=='neonrest' else 'NEONREST_SANDBOX'
for k,v in {'DATABASE':str(w/'fixture.db'),'SECRET_FILE':str(w/'secret'),'INSTANCE':str(w/'instance'),'MAIL_QUEUE_DIR':str(w/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[prefix+'_'+k]=v
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
slug='vm-fixture-one'
with app.test_request_context():path=__import__('flask').url_for('manage_vibe',slug=slug)
other_path=path.replace('vm-fixture-one','vm-fixture-two')
for key in ['Owner','Admin','Moderator','SiteManager','Manager']:
 r=get(key,path);check(r.status_code==200,key+' scoped dashboard '+str(r.status_code)+' '+str(r.location))
 check(b'How to use these tools' in r.data,key+' instructions')
check(get('Regular',path).status_code==403,'Ordinary member forbidden');check(app.test_client().get(path,environ_overrides=env).status_code in (302,403),'Guest forbidden');check(get('OtherManager',path).status_code==403,'Other Vibe assignment does not grant access')
check(get('NoFactor',path).status_code==302 and '/account/security' in get('NoFactor',path).location,'2FA setup required')
for key in ['Moderator','Manager','SiteManager']:
 check(action(key,'archive',confirm_name='VM Fixture One').status_code==403,key+' cannot archive')
check(b'Archive this Vibe' not in get('Manager',path).data,'No lifecycle form for assigned manager');check(b'Edit day appearance' not in get('Moderator',path).data,'Moderator cannot edit appearance')
check(action('Moderator','details',welcome_message='bad',rules='bad').status_code==403,'Moderator cannot change details')
check(action('Manager','details',welcome_message='Fictional welcome <script>bad</script>',rules='Rule one: Be thoughtful.').status_code==302,'Assigned manager can edit details')
r=app.test_client().get('/vibe/VM%20Fixture%20One',environ_overrides=env);check(r.status_code==200 and b'Rule one' in r.data and b'<script>bad</script>' not in r.data,'Public rules and escaped text')
check(action('Manager','assign_manager',account='@VMFixtureRegular').status_code==403,'Manager cannot grant access');check(action('Moderator','assign_manager',account='@VMFixtureRegular').status_code==403,'Moderator cannot grant access')
check(action('Admin','assign_manager',account='@VMFixtureRegular').status_code==302,'Admin can appoint Vibe Manager');check(get('Regular',path).status_code==200,'Assignment immediately grants scoped dashboard');check(get('Regular',other_path).status_code==403,'Assignment remains Vibe-scoped')
check(action('Admin','assign_manager',account='@VMFixtureTeen').status_code==403,'No minor manager assignment');check(action('Admin','remove_manager',account='@VMFixtureRegular').status_code==302,'Admin can revoke assignment');check(get('Regular',path).status_code==403,'Revocation takes effect immediately')
pid,pub=post_fixture('VISIBLE CURATION SENTINEL',vibes=[vid,other]);private,private_pub=post_fixture('PRIVATE CURATION SENTINEL','private');unrelated,unrelated_pub=post_fixture('OTHER VIBE ONLY',vibes=[other])
r=get('Manager',path);check(b'VISIBLE CURATION SENTINEL' in r.data and b'PRIVATE CURATION SENTINEL' not in r.data,'Manager listing respects post privacy')
check(action('Manager','remove_post',post=private_pub).status_code==404,'Private post cannot be curated by forged request');check(action('Manager','remove_post',post=unrelated_pub).status_code==409,'Unrelated Vibe post rejected');check(action('OtherManager','remove_post',post=pub).status_code==403,'Unassigned curation rejected')
check(action('Manager','remove_post',post=pub).status_code==302,'Remove association');check(query('SELECT content FROM posts WHERE id=?',(pid,))[0][0]=='VISIBLE CURATION SENTINEL','Original post preserved');check(query('SELECT 1 FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,other)),'Other Vibe preserved');check(not query('SELECT 1 FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid)),'Removed from selected Vibe')
r=get('Manager',path,tab='removed');check(b'VISIBLE CURATION SENTINEL' in r.data,'Reversible removal listing')
with app.test_request_context('/create_post'):
 db=core.get_db()
 try:life.add_post_vibes(db,pid,['VM Fixture One']);check(False,'Retag must fail')
 except Exception as exc:check(getattr(exc,'code',None)==409,'Removed post cannot be retagged')
 db.rollback()
check(action('Manager','restore_post',post=pub).status_code==302,'Restore selected Vibe association');check(query('SELECT 1 FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid)),'Restored association');check(action('Manager','restore_post',post=pub).status_code==409,'Repeated restore rejected')
check(action('Admin','archive',confirm_name='wrong').status_code==400,'Exact archive confirmation');check(action('Admin','archive',confirm_name='VM Fixture One').status_code==302,'Admin archive');check(action('Owner','archive',confirm_name='VM Fixture One').status_code==409,'Stale archive rejected')
r=app.test_client().get('/explore',query_string={'vq':'VM Fixture One'},environ_overrides=env);check(b'class="directory-card"' not in r.data,'Archive removed from directory')
r=app.test_client().get('/vibe/VM%20Fixture%20One',environ_overrides=env);check(r.status_code==200 and b'This Vibe is archived' in r.data and b'Post to this Vibe</a>' not in r.data,'Archive readable but posting CTA absent')
for alias in ['VM Fixture One','#VMFixtureOne','vm fixture one']:
 with app.test_request_context('/create_post'):
  db=core.get_db()
  try:life.add_post_vibes(db,pid,[alias]);check(False,'Archived alias must fail')
  except Exception as exc:check(getattr(exc,'code',None)==409,'Archived alias rejected '+alias)
  db.rollback()
r=clients['Writer'].post('/create_post',data={'content':'ARCHIVED NEW POST MUST NOT SAVE','vibes':'VM Fixture One','audience':'public','theme_csrf_token':token},environ_overrides=env);check(r.status_code==409,'Actual composer rejects archived Vibe');check(not query("SELECT 1 FROM posts WHERE content='ARCHIVED NEW POST MUST NOT SAVE'"),'No partial post after rejected archive tag')
r=clients['Writer'].post('/edit_post/'+pub,data={'content':'ARCHIVED EXISTING EDIT','vibes':'VM Fixture One, VM Fixture Two','circle':'public','audience':'public','theme_csrf_token':token},environ_overrides=env);check(r.status_code==302,'Existing archived post can be edited');check(query('SELECT 1 FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid)),'Existing archived association retained')
check(action('Owner','restore_vibe',confirm_name='VM Fixture One').status_code==302,'Owner restore');check(b'class="directory-card"' in app.test_client().get('/explore',query_string={'vq':'VM Fixture One'},environ_overrides=env).data,'Restore returns discovery')
check(clients['Manager'].post('/manage/vibes/'+str(vid)+'/action',data={'action':'details','reason':'x'},environ_overrides=env).status_code==400,'CSRF required');check(action('Manager','details',reason='',rules='x').status_code==400,'Reason required')
report=change('INSERT INTO content_reports(reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)',(users['Writer'],'post',pid,'SCOPED SITE REPORT SENTINEL'));other_report=change('INSERT INTO content_reports(reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)',(users['Writer'],'post',unrelated,'UNRELATED SITE REPORT SENTINEL'))
r=get('Moderator','/manage/reports',vibe_id=vid);check(r.status_code==200 and b'SCOPED SITE REPORT SENTINEL' in r.data and b'UNRELATED SITE REPORT SENTINEL' not in r.data,'Site report Vibe filter');check(get('Manager','/manage/reports',vibe_id=vid).status_code==403,'No private site report access for Vibe Manager');check(b'Site reports involving' not in get('Manager',path).data,'No misleading private report link')

with app.test_request_context():theme_path=__import__('flask').url_for('edit_theme',slug=slug,mode='day')
r=clients['Manager'].post(theme_path,data={'theme_csrf_token':token,'action':'save','custom_css':'body { color: #ffffff; }','welcome_message':'Fictional welcome'},environ_overrides=env);check(r.status_code==302,'Assigned theme editor remains functional');check(query("SELECT 1 FROM vibe_management_events WHERE vibe_id=? AND action='appearance'",(vid,)),'Theme editor changes audited');check(clients['Moderator'].get(theme_path,environ_overrides=env).status_code==403,'No moderator appearance privilege escalation')

r=get('Manager',path,tab='history');check(r.status_code==200 and b'Remove Post' in r.data and b'PRIVATE CURATION SENTINEL' not in r.data,'Management audit stays scoped');check(query('SELECT COUNT(*) FROM vibe_management_events WHERE vibe_id=?',(vid,))[0][0]>=8,'Changes audited')
with clients['Manager'].session_transaction() as s:s['fresh_at']=0;s['factor_at']=0
r=get('Manager',path);check(r.status_code==302 and '/account/reauth' in r.location,'Stale authorization requires reconfirmation')
check(app.config['RETENTION_ENABLED'] is False,'Erasure remains disabled')
print(json.dumps({'package':package,'checks':checks,'result':'passed'}))
