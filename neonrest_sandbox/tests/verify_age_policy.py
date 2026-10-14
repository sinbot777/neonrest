"""Integration verification against a temporary source/database copy, never live user rows."""
from pathlib import Path
import os,sys,sqlite3,tempfile,shutil,subprocess,contextlib,io,time
from datetime import date
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'));bundle=Path(__file__).parent
if not (bundle/'age_policy.py').exists(): bundle=bundle.parent
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
with tempfile.TemporaryDirectory(prefix='neonrest-age-test-') as tmp:
 stage=Path(tmp)/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'): shutil.copy2(p,stage/p.name)
 for name in ('templates','routes','utils'): shutil.copytree(live/name,stage/name)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 shutil.copy2(bundle/'age_policy.py',stage/'age_policy.py')
 if 'age_policy as ages' not in (stage/'community_features.py').read_text():
  subprocess.run([sys.executable,str(bundle/'install_age_policy.py')],env=dict(os.environ,AGE_POLICY_SOURCE_ROOT=str(stage)),check=True)
 dbpath=Path(tmp)/'test.db'
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True);dest=sqlite3.connect(dbpath);source.backup(dest);source.close();dest.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath)
 os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(Path(tmp)/'session-secret')
 sys.path.insert(0,tmp)
 with contextlib.redirect_stdout(io.StringIO()):
  import neonrest_sandbox.app as core
 from neonrest_sandbox import age_policy as ages,community_features as cf
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,SESSION_COOKIE_PATH='/')
 clients={}
 with app.app_context():
  db=core.get_db();ids={}
  for a in (9,10,11,12,13,14,16,17,18,19,20,21,40):
   dob=f'{date.today().year-a}-01-01'
   uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',(f'@AgeTest{a}',f'age-test-{a}@example.invalid','unused',dob)).lastrowid;ids[a]=uid
  uid=db.execute('INSERT INTO users(handle,email,password_hash,verified) VALUES (?,?,?,1)',('@AgeUnknown','age-unknown@example.invalid','unused')).lastrowid;ids[None]=uid
  db.commit();ages.init(db)
  check(not ages.ready(db,ids[10]),'Under-13 pending account locked')
  for a in (10,11,12): db.execute("INSERT INTO family_links(parent_id,child_id,status) VALUES (?,?,'approved')",(ids[40],ids[a]))
  db.commit()
  for a in ids:
   for b in ids:
    expected=a is not None and b is not None and min(a,b)>=10 and (min(a,b)>=18 or abs(a-b)<=3)
    check(ages.band(db,ids[a],ids[b])==expected,f'Age band {a}/{b}')
  check(ages.can_read(db,ids[40],ids[11]),'Child reads verified linked parent post')
  check(ages.can_read(db,ids[11],ids[40]),'Verified parent reads child')
  check(not ages.can_read(db,ids[11],ids[21]),'Unrelated adult cannot read child')
  check(not ages.can_read(db,ids[17],None),'Guest cannot read minor')
  check(ages.can_read(db,ids[17],ids[20]),'17 to 20 boundary')
  check(not ages.can_read(db,ids[17],ids[21]),'17 to 21 denied')
  check(not ages.contact(db,ids[11],ids[13],invitation=True),'Parent contact approval required')
  db.execute('INSERT INTO parent_contacts VALUES (?,?,?)',(ids[40],ids[11],ids[13]));db.commit()
  check(ages.contact(db,ids[11],ids[13],invitation=True),'Parent permits eligible invitation')
  check(not ages.contact(db,ids[11],ids[13]),'Mutual acceptance required')
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(ids[11],ids[13]));db.commit()
  check(ages.contact(db,ids[11],ids[13]),'Accepted approved minor contact')
  try: db.execute('UPDATE users SET dob=? WHERE id=?',('2000-01-01',ids[11]))
  except sqlite3.IntegrityError: db.rollback();check(True,'DOB locked by database')
  else: raise AssertionError('DOB mutation succeeded')
  def post(a,audience='public'):
   pid=db.execute('INSERT INTO posts(user_id,content,circle) VALUES (?,?,?)',(ids[a],f'AgeTestContent{a}','public')).lastrowid
   db.execute('INSERT INTO post_privacy VALUES (?,?)',(pid,audience));return pid
  minorpost=post(17);childpost=post(11,'friends');adultpost=post(40);privatepost=post(40,'private')
  db.commit();ages.init(db)
  check(not cf.visible_post(db,minorpost,None),'Direct post age filter guest')
  check(not cf.visible_post(db,minorpost,ids[40]),'Direct post unrelated adult filter')
  check(cf.visible_post(db,childpost,ids[40]),'Parent friends audience exception')
  check(not cf.visible_post(db,privatepost,ids[11]),'Parent exception respects private audience')
  for a,uid in ids.items():
   sid=f'isolated-age-session-{uid}';now=int(time.time());db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'isolated-test'))
   c=app.test_client()
   with c.session_transaction() as ss: ss.update(user_id=uid,user_email=f'age-test-{a}@example.invalid',user_handle=f'@AgeTest{a}',sid=sid,fresh_at=now,theme_csrf_token='test-csrf',friend_csrf_token='test-friend')
   clients[a]=c
  db.commit()
 guest=app.test_client()
 with guest.session_transaction() as ss: ss['theme_csrf_token']='test-csrf'
 check(guest.get('/account/age').status_code==401,'Age page requires authentication')
 check(clients[40].get('/account/family').status_code==200,'Parent settings renders')
 check(clients[11].get('/account/family').status_code==403,'Child cannot act as parent')
 check(clients[None].get('/feed').status_code==302,'Missing DOB social access gated')
 check(clients[11].post('/account/age',data={'dob':'2000-01-01','theme_csrf_token':'test-csrf'}).status_code==400,'Existing DOB cannot change through route')
 check(clients[40].post('/account/family',data={'action':'link-existing','handle':'AgeTest11','theme_csrf_token':'test-csrf'}).status_code==302,'Existing child link request')
 check(clients[40].post('/account/family',data={'action':'enroll','handle':'NewAgeChild','dob':f'{date.today().year-11}-01-01','email':'new-age-child@example.invalid','password':'Test-only-password-unused','theme_csrf_token':'test-csrf'}).status_code==302,'Parent enrollment permitted despite immutable DOB guard')
 check(guest.post('/signup',data={'password':'Test-only-password-unused','theme_csrf_token':'test-csrf','dob':f'{date.today().year-9}-01-01'}).status_code==400,'Under minimum signup rejected')
 check(guest.post('/signup',data={'password':'Test-only-password-unused','theme_csrf_token':'test-csrf','dob':f'{date.today().year-11}-01-01'}).status_code==403,'Under-13 self signup rejected')
 for viewer in (None,40,20):
  c=guest if viewer is None else clients[viewer]
  res=c.get(f'/posts/{minorpost}')
  check((b'AgeTestContent17' in res.data)==(viewer==20),f'Direct URL visible only in age band {viewer}')
  res=c.get(f'/posts/{minorpost}/history')
  check(res.status_code==(200 if viewer==20 else 404),f'History age check {viewer}')
 check(guest.get(f'/static/uploads/avatars/user_{ids[11]}_avatar.png').status_code==404,'Direct minor avatar denied')
 check(guest.get(f'/static/uploads/avatars/../avatars/user_{ids[11]}_avatar.png').status_code==404,'Normalized minor avatar path denied')
 from neonrest_sandbox import media_features as media
 media_root=Path(tmp)/'isolated-media';media_root.mkdir();media.media_folder=lambda:media_root
 filename='a'*40+'.png';(media_root/filename).write_bytes(b'isolated media fixture')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO post_media(post_id,kind,filename) VALUES (?,?,?)',(minorpost,'image',filename));db.commit()
 check(guest.get('/media-file/'+filename).status_code==404,'Guest direct minor media denied')
 check(clients[40].get('/media-file/'+filename).status_code==404,'Unrelated adult direct minor media denied')
 check(clients[20].get('/media-file/'+filename).status_code==200,'Age-eligible direct media served')
 check(clients[20].get('/media-file/'+filename).headers.get('Cache-Control','').find('no-store')>=0,'Protected response avoids shared caching')
 exported=clients[20].post('/account/export',data={'theme_csrf_token':'test-csrf'})
 check(exported.status_code==200 and b'AgeTestContent17' not in exported.data,'Own export excludes another minors posts')

 with app.app_context():
  db=core.get_db()
  db.execute("INSERT INTO comments(user_id,post_id,content) VALUES (?,?,?)",(ids[17],adultpost,'ProtectedTeenReply'))
  cid=db.execute('SELECT last_insert_rowid()').fetchone()[0];db.commit();ages.init(db)
  check(ages.comment_read(db,cid,ids[20]),'Eligible age reads teen reply')
  check(not ages.comment_read(db,cid,ids[21]),'Out of band cannot read teen reply')
  db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'admin')",(ids[40],))
  db.execute("INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET totp_secret=excluded.totp_secret",(ids[40],'JBSWY3DPEHPK3PXP'));db.commit()
 with clients[40].session_transaction() as ss: ss['factor_at']=int(time.time());ss['fresh_at']=int(time.time())-601
 check(clients[40].post('/manage/family',data={'parent_id':ids[40],'child_id':ids[11],'action':'approve','method':'signed-consent-form','reference':'isolated-test-only','theme_csrf_token':'test-csrf'}).status_code==302,'Expired privileged consent approval requires renewal')
 with app.app_context():
  row=core.get_db().execute('SELECT reference FROM family_links WHERE parent_id=? AND child_id=?',(ids[40],ids[11])).fetchone()
  check(row['reference'] is None,'Expired approval cannot mutate consent record')
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time())
 check(clients[40].post('/manage/family',data={'parent_id':ids[40],'child_id':ids[11],'action':'approve','method':'signed-consent-form','reference':'isolated-test-only','theme_csrf_token':'test-csrf'}).status_code==302,'Fresh privileged consent approval')
 with app.app_context():
  check(core.get_db().execute('SELECT reference FROM family_links WHERE parent_id=? AND child_id=?',(ids[40],ids[11])).fetchone()['reference']=='isolated-test-only','Fresh approval records review reference')
 check(clients[21].post('/create_comment',data={'post_id':adultpost,'content':'Outside-age-contact','theme_csrf_token':'test-csrf','parent_comment_id':core.encode_base62(cid).rjust(8,'A')}).status_code==404,'Out-of-band reply contact denied')
 check(clients[13].post('/create_comment',data={'post_id':childpost,'content':'Approved-contact-reply','theme_csrf_token':'test-csrf'}).status_code==201,'Approved accepted child contact can reply')
 check(clients[40].post('/create_comment',data={'post_id':minorpost,'content':'Unrelated-adult','theme_csrf_token':'test-csrf'}).status_code==404,'Unrelated adult cannot reply to teen post')
 with app.app_context():
  db=core.get_db();db.execute("UPDATE family_links SET status='revoked' WHERE parent_id=? AND child_id=?",(ids[40],ids[11]));db.commit()
  check(not ages.ready(db,ids[11]),'Revoking consent suspends under-13 social access')
  check(not ages.contact(db,ids[11],ids[13]),'Revocation invalidates existing accepted contact')
 check(ages.age_of('2008-10-09',date(2026,10,8))==17,'Day before birthday')
 check(ages.age_of('2008-10-09',date(2026,10,9))==18,'Birthday age transition')
 check(ages.age_of('2012-02-29',date(2026,2,28))==13,'Leap-day birthday before March 1')
 check(ages.age_of('2012-02-29',date(2026,3,1))==14,'Leap-day birthday on March 1')
 check(ages.parse_dob('2099-01-01') is None,'Future DOB rejected')
 check(ages.parse_dob('2012-02-30') is None,'Invalid calendar DOB rejected')
 core.validate_email=lambda value: None
 core.mail.send=lambda message: True
 signup_dob=f'{date.today().year-13}-01-01'
 result=guest.post('/signup',data={'email':'age-signup-test@example.invalid','handle':'AgeSignupPersistenceTest','password':'Test-only-password-unused','dob':signup_dob,'theme_csrf_token':'test-csrf'})
 check(result.status_code in (200,302),'Eligible signup response')
 with app.app_context():
  db=core.get_db();row=db.execute('SELECT id,dob FROM users WHERE handle=?',('@AgeSignupPersistenceTest',)).fetchone()
  check(row is not None and row['dob']==signup_dob,'Eligible signup persists validated DOB')
  check(not db.execute('SELECT 1 FROM friend_requests WHERE sender_id=? OR receiver_id=?',(row['id'],row['id'])).fetchone(),'Minor signup has no automatic founder friendship')
 print(f'PASS: {checks} isolated age-policy checks; live accounts and production unchanged')
