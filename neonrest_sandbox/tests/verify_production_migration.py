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
 source=sqlite3.connect('file:/home/sinbot/db/neonrest.db?mode=ro',uri=True);dest=sqlite3.connect(dbpath);source.backup(dest);source.close()
 sandbox=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
 for handle in ('brendoom','kickin1381','a_wobbly_jack'):
  dob=sandbox.execute("SELECT dob FROM users WHERE lower(ltrim(handle,'@'))=?",(handle,)).fetchone()[0]
  dest.execute("UPDATE users SET dob=? WHERE lower(ltrim(handle,'@'))=? AND (dob IS NULL OR trim(dob)='')",(dob,handle))
 dest.commit();sandbox.close();dest.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath)
 os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(Path(tmp)/'session-secret')
 sys.path.insert(0,tmp)
 with contextlib.redirect_stdout(io.StringIO()):
  import neonrest_sandbox.app as core
 from neonrest_sandbox import age_policy as ages,community_features as cf
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,SESSION_COOKIE_PATH='/',FAMILY_CONSENT_FOLDER=str(Path(tmp)/'private-consent'))
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
 check(clients[40].post('/account/family',data={'action':'enroll','handle':'NewAgeChild','dob':f'{date.today().year-11}-01-01','email':'new-age-child@example.invalid','password':'Test-only-password-unused','theme_csrf_token':'test-csrf'}).status_code==403,'New under-13 parent enrollment disabled')
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
 with clients[40].session_transaction() as ss: ss['factor_at']=int(time.time());ss['fresh_at']=int(time.time())-1801
 check(clients[40].post('/manage/family',data={'parent_id':ids[40],'child_id':ids[11],'action':'approve','method':'signed-consent-form','reference':'isolated-test-only','theme_csrf_token':'test-csrf'}).status_code==302,'Expired privileged consent approval requires renewal')
 with app.app_context():
  row=core.get_db().execute('SELECT reference FROM family_links WHERE parent_id=? AND child_id=?',(ids[40],ids[11])).fetchone()
  check(row['reference'] is None,'Expired approval cannot mutate consent record')
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time())
 form={'child_id':str(ids[11]),'theme_csrf_token':'test-csrf'}
 upload=lambda client,data: client.post('/account/family/consent',data=data,content_type='multipart/form-data')
 check(upload(clients[40],dict(form,letter=(io.BytesIO(b'<script>bad</script>'),'bad.pdf'))).status_code==400,'Disguised file rejected')
 check(upload(clients[40],dict(form,theme_csrf_token='wrong',letter=(io.BytesIO(b'%PDF-1.4\n%%EOF'),'letter.pdf'))).status_code==400,'Consent upload CSRF enforced')
 check(upload(clients[21],dict(form,letter=(io.BytesIO(b'%PDF-1.4\n%%EOF'),'letter.pdf'))).status_code==404,'Unlinked adult cannot submit letter')
 check(upload(clients[40],dict(form,letter=(io.BytesIO(b'%PDF-1.4\n%%EOF'),'letter.pdf'))).status_code==302,'Parent uploads signed letter')
 with app.app_context():
     db=core.get_db(); document_id=db.execute('SELECT MAX(id) FROM family_consent_documents WHERE parent_id=?',(ids[40],)).fetchone()[0]
     check(db.execute('SELECT reference FROM family_links WHERE parent_id=? AND child_id=?',(ids[40],ids[11])).fetchone()['reference'] is None,'Upload does not approve consent')
 document_url='/account/family/consent/'+str(document_id)
 check(clients[21].get(document_url).status_code==403,'Unrelated adult cannot download letter')
 check(clients[11].get(document_url).status_code==403,'Child cannot download consent letter')
 check(guest.get(document_url).status_code==404,'Anonymous document download denied')
 response=clients[40].get(document_url)
 check(response.status_code==200 and 'attachment' in response.headers['Content-Disposition'],'Parent downloads private attachment')
 check('no-store' in response.headers['Cache-Control'],'Document cannot be cached')
 response.close()
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time())-1801
 check(clients[40].get(document_url).status_code==302,'Expired document authorization requires renewal')
 check(upload(clients[40],dict(form,letter=(io.BytesIO(b'%PDF-1.4\n%%EOF'),'letter.pdf'))).status_code==302,'Expired upload authorization requires renewal')
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time())
 check(clients[40].post('/manage/family',data={'parent_id':ids[40],'child_id':ids[11],'action':'approve','method':'signed-consent-form','reference':'99999999','theme_csrf_token':'test-csrf'}).status_code==400,'Unknown signed letter cannot approve consent')
 check('Review parental consent' in clients[40].get('/account/family').get_data(as_text=True),'Staff review link in family settings')
 check('Review parental consent' not in clients[21].get('/account/family').get_data(as_text=True),'Staff link hidden from ordinary parent')
 check('Submit for review' in clients[40].get('/account/family').get_data(as_text=True),'Parent submission form displayed')
 check(clients[40].post('/manage/family',data={'parent_id':ids[40],'child_id':ids[11],'action':'approve','method':'signed-consent-form','reference':str(document_id),'theme_csrf_token':'test-csrf'}).status_code==302,'Fresh privileged consent approval')
 with app.app_context():
  check(core.get_db().execute('SELECT reference FROM family_links WHERE parent_id=? AND child_id=?',(ids[40],ids[11])).fetchone()['reference']=='letter:'+str(document_id),'Fresh approval records review reference')
 check(clients[21].post('/create_comment',data={'post_id':adultpost,'content':'Outside-age-contact','theme_csrf_token':'test-csrf','parent_comment_id':core.encode_base62(cid).rjust(8,'A')}).status_code==404,'Out-of-band reply contact denied')
 check(clients[13].post('/create_comment',data={'post_id':childpost,'content':'Approved-contact-reply','theme_csrf_token':'test-csrf'}).status_code==201,'Approved accepted child contact can reply')
 check(clients[40].post('/create_comment',data={'post_id':minorpost,'content':'Unrelated-adult','theme_csrf_token':'test-csrf'}).status_code==403,'Staff viewing does not permit out-of-band replies')
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
 result=guest.post('/signup',data={'email':'age-signup-test@example.invalid','handle':'AgeSignupPersistenceTest','password':'Test-only-password-unused','dob':signup_dob,'actual_name':'Private Test Name','theme_csrf_token':'test-csrf'})
 check(result.status_code in (200,302),'Eligible signup response')
 with app.app_context():
  db=core.get_db();row=db.execute('SELECT id,dob FROM users WHERE handle=?',('@AgeSignupPersistenceTest',)).fetchone()
  check(row is not None and row['dob']==signup_dob,'Eligible signup persists validated DOB')
  check(db.execute('SELECT actual_name FROM users WHERE id=?',(row['id'],)).fetchone()['actual_name']=='Private Test Name','Signup persists private actual name')
  founder=db.execute("SELECT id FROM users WHERE lower(handle)='@brendoom'").fetchone()['id']
  check(db.execute("SELECT 1 FROM friend_requests WHERE status='accepted' AND sender_id=? AND receiver_id=?",(founder,row['id'])).fetchone(),'Minor signup receives welcome friend')
  check(db.execute('SELECT position_t9 FROM top_friends WHERE user_id=? AND friend_id=?',(row['id'],founder)).fetchone()['position_t9']==1,'Welcome friend occupies first Top 9 slot')
  db.execute('UPDATE users SET verified=1 WHERE id=?',(row['id'],))
  personal=db.execute("INSERT INTO posts(user_id,target_user_id,content,circle) VALUES (?,?,'Personal founder post','public')",(founder,founder)).lastrowid
  notice=db.execute("INSERT INTO posts(user_id,target_user_id,content,circle) VALUES (?,?,'Staff notice','public')",(founder,founder)).lastrowid
  db.execute('INSERT INTO staff_announcements VALUES (?)',(notice,));db.commit()
  check(not cf.visible_post(db,personal,row['id']),'Welcome friendship does not expose founder personal posts')
  check(cf.visible_post(db,notice,row['id']),'Explicit public staff announcement visible to minor')
  check(not ages.contact(db,founder,row['id']),'Welcome friendship cannot bypass age contact limit')
  check(not ages.contact(db,row['id'],founder),'Minor cannot contact out-of-band welcome friend')
  check(cf.member_visible(db,ids[17],ids[40]),'Authorized staff can view minor profiles')
  check(cf.visible_post(db,privatepost,ids[40]),'Staff can view private post for moderation')
  db.execute("INSERT OR REPLACE INTO post_privacy VALUES (?,'private')",(notice,));db.commit()
  check(not cf.visible_post(db,notice,row['id']),'Announcement flag never overrides private audience')
  db.execute("INSERT OR REPLACE INTO post_privacy VALUES (?,'public')",(notice,));db.execute("INSERT OR IGNORE INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,'test')",(notice,founder,ids[40]));db.commit()
  check(not cf.visible_post(db,notice,row['id']),'Moderated announcement hidden from minor')
  check(cf.visible_post(db,notice,ids[40]),'Staff can view moderated posts')
  ordinary=post(21);db.execute('INSERT INTO staff_announcements VALUES (?)',(ordinary,));db.commit()
  check(not __import__('neonrest_sandbox.welcome',fromlist=['announcement']).announcement(db,ordinary),'Announcement requires staff author')
 check(clients[13].post('/create_post',data={'content':'Forged notice','staff_announcement':'1','theme_csrf_token':'test-csrf'}).status_code==403,'Ordinary member cannot flag staff announcement')
 check(clients[40].post('/create_post',data={'content':'Verified staff announcement test','staff_announcement':'1','audience':'public','theme_csrf_token':'test-csrf'}).status_code==302,'Fresh authorized staff can publish flagged announcement')
 with app.app_context():
  db=core.get_db();published=db.execute("SELECT id FROM posts WHERE content='Verified staff announcement test'").fetchone()['id']
  check(cf.visible_post(db,published,ids[13]),'Published announcement visible to younger member')
  check('Staff announcement' in clients[40].get('/edit_post/'+str(published)).get_data(as_text=True),'Announcement editor control renders for staff')
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time())-1801
 check(clients[40].post('/create_post',data={'content':'Expired notice','staff_announcement':'1','audience':'public','theme_csrf_token':'test-csrf'}).status_code==302,'Expired staff authorization redirects for renewal')
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'moderator')",(ids[21],));db.commit()
  check(cf.visible_post(db,privatepost,ids[21]),'Moderator can view private posts')
  check(cf.member_visible(db,ids[11],ids[21]),'Moderator can view minor user')
  check(not ages.contact(db,ids[21],ids[13]),'Moderator viewing does not bypass contact age boundary')
 with app.app_context():
  db=core.get_db();from neonrest_sandbox import welcome
  welcome.add_welcome_friend(db,ids[10]);welcome.add_welcome_friend(db,ids[10]);db.commit()
  check(db.execute('SELECT COUNT(*) FROM friend_requests WHERE sender_id=? AND receiver_id=?',(founder,ids[10])).fetchone()[0]==1,'Parent enrollment welcome helper is idempotent')
  check(not ages.contact(db,ids[10],founder),'Child welcome friendship cannot bypass parent or age contact limits')
  with app.test_request_context('/create_post'):
     from flask import session
     session.update(user_id=ids[40],fresh_at=int(time.time())-1200,factor_at=int(time.time())-1200)
     check(app.extensions['privileged_fresh'](),'Twenty-minute authorization remains fresh')
     session['factor_at']=int(time.time())-1801
     check(not app.extensions['privileged_fresh'](),'Expired second factor requires renewal')
 with app.app_context():
     db=core.get_db()
     draft=db.execute('SELECT fields FROM authorization_post_drafts WHERE user_id=? AND path=?',(ids[40],'/create_post')).fetchone()
     check(draft and 'Expired notice' in draft['fields'],'Expired announcement preserves post draft')
     check(not db.execute("SELECT 1 FROM posts WHERE content='Expired notice'").fetchone(),'Expired announcement cannot publish before renewal')
 with clients[40].session_transaction() as ss: ss['fresh_at']=int(time.time());ss['factor_at']=int(time.time())
 page=clients[40].get('/create_post')
 check(page.status_code==200 and b'Expired notice' in page.data and b'post text has been restored' in page.data,'Fresh return renders saved announcement text')
 check(b'name="actual_name"' in guest.get('/signup').data,'Signup name field present')
 check(guest.post('/signup',data={'email':'name-reject@example.invalid','handle':'NoNameTest','password':'Test-only-password-unused','dob':signup_dob,'theme_csrf_token':'test-csrf'},environ_overrides={'REMOTE_ADDR':'192.0.2.91'}).status_code==400,'Server rejects missing name')
 check(guest.post('/signup',data={'actual_name':'x'*101,'email':'name-reject@example.invalid','handle':'NoNameTest','password':'Test-only-password-unused','dob':signup_dob,'theme_csrf_token':'test-csrf'},environ_overrides={'REMOTE_ADDR':'192.0.2.92'}).status_code==400,'Server rejects overlong name')
 check(b'mailto:ToS@neonrest.com?subject=Date' in clients[40].get('/account/age').data,'Age settings offer correction request')
 check(clients[40].post('/account/age',data={'dob':signup_dob,'theme_csrf_token':'test-csrf'}).status_code==400,'Existing DOB cannot be rewritten')
 with app.app_context():
  db=core.get_db()
  db.execute('UPDATE post_privacy SET audience=? WHERE post_id=?',('friends',minorpost))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(ids[17],ids[20]))
  db.commit()
 for path in (f'/posts/{minorpost}',f'/posts/{minorpost}/history','/media-file/'+filename):
  check(clients[20].get(path).status_code==200,'Accepted eligible friend access '+path)
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM friend_requests WHERE sender_id=? AND receiver_id=?',(ids[17],ids[20]));db.commit()
  check(not ages.contact(db,ids[17],ids[20]),'Friend removal revokes minor contact')
 for path in (f'/posts/{minorpost}',f'/posts/{minorpost}/history','/media-file/'+filename):
  check(clients[20].get(path).status_code==404,'Friend removal revokes access '+path)
 with app.app_context():
  db=core.get_db();db.execute('UPDATE post_privacy SET audience=? WHERE post_id=?',('public',minorpost));db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(ids[17],ids[20]));db.commit()
  check(not cf.member_visible(db,ids[17],ids[20]),'Blocked peer cannot view teen profile')
  check(not cf.member_visible(db,ids[20],ids[17]),'Blocking prevents reverse profile access')
 for path in (f'/posts/{minorpost}',f'/posts/{minorpost}/history','/media-file/'+filename):
  check(clients[20].get(path).status_code==404,'Blocking revokes direct access '+path)
 page=guest.get('/@AgeTest17')
 check(page.status_code==404 and b'Page unavailable' in page.data and b'Back to feed' in page.data,'Restricted profile renders friendly unavailable page')
 page=guest.get('/nonexistent-test-page')
 check(page.status_code==404 and b'Page unavailable' in page.data and 'no-store' in page.headers.get('Cache-Control',''),'Missing page uses same private 404 response')
 with app.app_context():
  db=core.get_db()
  db.execute('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(ids[17],ids[20]))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(ids[17],ids[20]))
  db.execute('UPDATE post_privacy SET audience=? WHERE post_id=?',('friends',minorpost))
  cid=db.execute('INSERT INTO comments(user_id,post_id,content) VALUES (?,?,?)',(ids[17],minorpost,'Notification audit reply')).lastrowid
  row={'kind':'replies','actor_id':ids[17],'path':f'/posts/{minorpost}#comment-{cid}'}
  check(cf.notification_visible(db,row,ids[20]),'Eligible friend sees reply notification')
  cf.notify(db,ids[20],'replies','AUDIT_VISIBLE_REPLY',row['path'],ids[17]);db.commit()
 page=clients[20].get('/notifications')
 check(page.status_code==200 and b'AUDIT_VISIBLE_REPLY' in page.data,'Inbox renders permitted notification')
 with app.app_context():
  db=core.get_db()
  db.execute('DELETE FROM friend_requests WHERE sender_id=? AND receiver_id=?',(ids[17],ids[20]));db.commit()
  check(not cf.notification_visible(db,row,ids[20]),'Friend removal hides old reply notification')
 page=clients[20].get('/notifications')
 check(b'AUDIT_VISIBLE_REPLY' not in page.data,'Inbox hides notification after friend removal')
 with app.test_request_context('/notifications'):
  session=core.session;session['user_id']=ids[20]
  contexts=[processor() for processor in app.template_context_processors[None]]
  check(next(x['community_unread'] for x in contexts if 'community_unread' in x)==0,'Unread badge excludes revoked notifications')
 with app.app_context():
  db=core.get_db()
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(ids[17],ids[20]))
  for table in ('user_blocks','user_mutes'):
   db.execute(f'INSERT INTO {table}(user_id,target_id) VALUES (?,?)',(ids[20],ids[17]))
   check(not cf.notification_visible(db,row,ids[20]),table+' hides existing notification')
   db.execute(f'DELETE FROM {table} WHERE user_id=? AND target_id=?',(ids[20],ids[17]))
  db.execute('UPDATE post_privacy SET audience=? WHERE post_id=?',('private',minorpost))
  check(not cf.notification_visible(db,row,ids[20]),'Private audience hides notification')
  db.execute('UPDATE post_privacy SET audience=? WHERE post_id=?',('public',minorpost))
  db.execute('DELETE FROM comments WHERE id=?',(cid,))
  check(not cf.notification_visible(db,row,ids[20]),'Deleted reply hides notification')
  check(not cf.notification_visible(db,dict(row,path='/posts/999999999'),ids[20]),'Deleted post hides notification')
  check(not cf.notification_visible(db,dict(row,actor_id=ids[13]),ids[20]),'Out of age band notification hidden')
  friendrow={'kind':'friends','actor_id':ids[17],'path':'/friends'}
  check(cf.notification_visible(db,friendrow,ids[20]),'Current friendship notice remains visible')
  db.execute('DELETE FROM friend_requests WHERE sender_id=? AND receiver_id=?',(ids[17],ids[20]))
  check(not cf.notification_visible(db,friendrow,ids[20]),'Removed friendship notice disappears')
  for kind,path in [('moderation','/appeals'),('appeals','/appeals'),('reports','/reports/mine')]:
   check(cf.notification_visible(db,{'kind':kind,'actor_id':None,'path':path},ids[20]),kind+' case notification remains accessible')
  db.commit()
 for path in ['/manage/users?q=test','/manage/posts?q=test','/manage/history?q=test']:
  check(clients[13].get(path).status_code in (302,403),'Member cannot use staff search '+path)
 with app.app_context():
  db=core.get_db()
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(ids[17],ids[20]))
  notice={'kind':'comments','actor_id':ids[17],'path':f'/posts/{minorpost}'}
  db.execute('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(minorpost,ids[17],ids[40],'Test audit'))
  check(not cf.notification_visible(db,notice,ids[20]),'Moderated post hides existing notice')
  before=db.execute('SELECT count(*) FROM notifications WHERE user_id=?',(ids[20],)).fetchone()[0]
  cf.notify(db,ids[20],'comments','SHOULD_NOT_DELIVER',notice['path'],ids[17])
  check(db.execute('SELECT count(*) FROM notifications WHERE user_id=?',(ids[20],)).fetchone()[0]==before,'Restricted post notification not delivered')
  db.execute('DELETE FROM moderated_posts WHERE post_id=?',(minorpost,))
  db.execute("DELETE FROM friend_requests WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)",(ids[17],ids[20],ids[20],ids[17]))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'pending')",(ids[17],ids[20]))
  db.commit()
 check(b'@AgeTest17' in clients[20].get('/friends').data,'Eligible pending request visible')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(ids[20],ids[17]));db.commit()
 check(b'@AgeTest17' not in clients[20].get('/friends').data,'Blocked pending incoming request hidden')
 check(b'@AgeTest20' not in clients[17].get('/friends').data,'Blocked pending outgoing request hidden')
 from neonrest_sandbox import email_verification as ev
 import re
 from urllib.parse import urlsplit
 from werkzeug.security import generate_password_hash,check_password_hash
 sent=[];original_send=core.mail.send;core.mail.send=lambda message:sent.append(message)
 recovery=app.test_client()
 with recovery.session_transaction() as ss:ss['theme_csrf_token']='recovery-csrf'
 request_args={'environ_overrides':{'REMOTE_ADDR':'198.51.100.78'}}
 with app.app_context():
  db=core.get_db();db.execute('UPDATE users SET verified=0,password_hash=? WHERE id=?',(generate_password_hash('Old-test-password-123'),ids[21]));db.commit()
  token=ev.issue_token(db,'age-test-21@example.invalid')
  check(db.execute('SELECT token_hash FROM email_verifications WHERE user_id=? AND used=0',(ids[21],)).fetchone()[0]!=token,'Verification stores only token hash')
 check(recovery.get('/verify_email/'+token).status_code==200,'Fresh verification link succeeds')
 check(recovery.get('/verify_email/'+token).status_code==400,'Verification link cannot be reused')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT verified FROM users WHERE id=?',(ids[21],)).fetchone()[0]==1,'Verification activates correct account')
  db.execute('UPDATE users SET verified=0 WHERE id=?',(ids[21],));db.commit()
  expired=ev.issue_token(db,'age-test-21@example.invalid');db.execute('UPDATE email_verifications SET expires_at=? WHERE token_hash=?',(int(time.time())-1,cf.digest(expired)));db.commit()
 check(recovery.get('/verify_email/'+expired).status_code==400,'Expired verification link rejected')
 check(b'Request verification email' in recovery.get('/verify_email/not-a-token').data,'Invalid verification offers resend')
 with app.app_context():
  db=core.get_db();first=ev.issue_token(db,'age-test-21@example.invalid');second=ev.issue_token(db,'age-test-21@example.invalid')
 check(first!=second and recovery.get('/verify_email/'+first).status_code==400,'New verification supersedes old link')
 with app.app_context():
  db=core.get_db();db.execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(int(time.time())-61,ids[21]));db.commit()
 check(recovery.post('/verify-email',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args).status_code==200,'Resend verification succeeds')
 check(len(sent)==1 and '/verify_email/' in sent[-1].body,'Resend generates verification email')
 recovery.post('/verify-email',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args)
 check(len(sent)==1,'Verification resend cooldown suppresses duplicate mail')
 check(recovery.post('/verify-email',data={'theme_csrf_token':'recovery-csrf','email':'absent@example.invalid'},**request_args).status_code==200 and len(sent)==1,'Unknown email returns generic response without mail')
 check(recovery.post('/verify-email',data={'email':'age-test-21@example.invalid'},**request_args).status_code==400,'Resend requires CSRF token')
 unverified=app.test_client()
 with clients[21].session_transaction() as ss:old_session=dict(ss)
 with unverified.session_transaction() as ss:ss.update(old_session)
 check(unverified.get('/account').status_code==302,'Unverified existing session cannot access account')
 with unverified.session_transaction() as ss:check('user_id' not in ss,'Unverified session cleared')
 check(recovery.post('/login',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid','password':'Old-test-password-123'},**request_args).status_code==302,'Unverified sign-in redirects')
 with recovery.session_transaction() as ss:check('user_id' not in ss,'Unverified login creates no authenticated session')
 with app.app_context():
  db=core.get_db();db.execute('UPDATE users SET verified=1 WHERE id=?',(ids[21],));db.commit()
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET totp_secret=excluded.totp_secret',(ids[21],'JBSWY3DPEHPK3PXP'));db.commit()
 sent.clear()
 check(recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args).status_code==200,'Password reset request accepted')
 check(len(sent)==1,'Reset email generated')
 check(sent[-1].body.startswith('Reset your password within one hour: https://www.neonrest.com/'),'Reset email uses trusted HTTPS origin')
 reset_path=urlsplit(sent[-1].body.split(': ',1)[1].split()[0]).path
 reset_raw=reset_path.rsplit('/',1)[1]
 check(recovery.get(reset_path).status_code==200,'Fresh reset link opens password form')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT token_hash FROM password_resets WHERE user_id=? AND used=0',(ids[21],)).fetchone()[0]!=reset_raw,'Reset stores only token hash')
 check(recovery.post(reset_path,data={'theme_csrf_token':'recovery-csrf','new_password':'short'},**request_args).status_code==400,'Reset rejects short password')
 check(recovery.post(reset_path,data={'new_password':'New-test-password-123'},**request_args).status_code==400,'Reset requires CSRF token')
 check(recovery.post(reset_path,data={'theme_csrf_token':'recovery-csrf','new_password':'New-test-password-123'},**request_args).status_code==302,'Valid reset succeeds')
 with app.app_context():
  db=core.get_db();stored=db.execute('SELECT password_hash FROM users WHERE id=?',(ids[21],)).fetchone()[0]
  check(check_password_hash(stored,'New-test-password-123') and not check_password_hash(stored,'Old-test-password-123'),'Reset replaces old password securely')
  check(db.execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(ids[21],)).fetchone()[0]=='JBSWY3DPEHPK3PXP','Reset preserves second-factor requirement')
  check(not db.execute('SELECT 1 FROM active_sessions WHERE user_id=? AND revoked=0',(ids[21],)).fetchone(),'Reset revokes every old session')
 check(clients[21].get('/account').status_code==302,'Old browser session rejected after reset')
 check(b'Reset link unavailable' in recovery.get(reset_path).data,'Used reset link shows friendly recovery screen')
 check('no-store' in recovery.get(reset_path).headers.get('Cache-Control',''),'Reset response cannot be cached')
 check(recovery.get(reset_path).headers.get('Referrer-Policy')=='no-referrer','Reset token is not leaked by referrer')
 with recovery.session_transaction() as ss:ss['theme_csrf_token']='recovery-csrf'
 recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args)
 expired_reset=urlsplit(sent[-1].body.split(': ',1)[1].split()[0]).path
 with app.app_context():
  db=core.get_db();db.execute('UPDATE password_resets SET expires_at=? WHERE user_id=?',(int(time.time())-1,ids[21]));db.commit()
 check(recovery.get(expired_reset).status_code==400,'Expired reset link rejected')
 recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args)
 reset_one=urlsplit(sent[-1].body.split(': ',1)[1].split()[0]).path
 recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args)
 check(recovery.get(reset_one).status_code==400,'New reset invalidates previous link')
 n=len(sent);check(recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'absent@example.invalid'},**request_args).status_code==200 and len(sent)==n,'Unknown reset account gives generic response')
 core.mail.send=lambda message:(_ for _ in ()).throw(RuntimeError('test-only SMTP failure'))
 check(recovery.post('/password-reset',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args).status_code==200,'Reset SMTP failure does not expose error')
 with app.app_context():
  db=core.get_db();db.execute('UPDATE users SET verified=0 WHERE id=?',(ids[21],));db.execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(int(time.time())-61,ids[21]));db.commit()
 check(recovery.post('/verify-email',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid'},**request_args).status_code==200,'Verification SMTP failure handled safely')
 core.mail.send=original_send
 with app.app_context():
  db=core.get_db();db.execute('UPDATE users SET verified=1 WHERE id=?',(ids[21],));db.commit()
 check(recovery.post('/login',data={'theme_csrf_token':'recovery-csrf','email':'age-test-21@example.invalid','password':'New-test-password-123'},**request_args).status_code==302,'Reset password still leads to two-factor challenge')
 with recovery.session_transaction() as ss:check(ss.get('pending_login')==ids[21] and 'user_id' not in ss,'Reset does not bypass two-factor sign-in')
 throttle=app.test_client()
 with throttle.session_transaction() as ss:ss['theme_csrf_token']='throttle-csrf'
 responses=[throttle.post('/verify-email',data={'theme_csrf_token':'throttle-csrf','email':'absent@example.invalid'},environ_overrides={'REMOTE_ADDR':'198.51.100.79'}) for _ in range(6)]
 check(all(x.status_code==200 for x in responses[:5]) and responses[-1].status_code==429,'Verification resend has network rate limit')
 sent=[];core.mail.send=lambda message:sent.append(message)
 with app.test_request_context('/verify-email',base_url='https://attacker.example',environ_overrides={'SCRIPT_NAME':'/sandbox'}):
  db=core.get_db();db.execute('UPDATE users SET verified=0 WHERE id=?',(ids[21],));db.execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(int(time.time())-61,ids[21]));db.commit()
  ev.send_verification(core,db,'age-test-21@example.invalid')
  check(len(sent)==1 and 'https://www.neonrest.com/sandbox/verify_email/' in sent[-1].body and 'attacker.example' not in sent[-1].body,'Verification email preserves Sandbox path and trusted host')
 with app.app_context():
  db=core.get_db();bound=ev.issue_token(db,'age-test-21@example.invalid');db.execute('UPDATE users SET email=? WHERE id=?',('changed-test@example.invalid',ids[21]));db.commit()
 check(throttle.get('/verify_email/'+bound).status_code==400,'Verification cannot verify a changed email address')
 core.mail.send=original_send

 # Account deletion requests are tested only in this temporary source/database.
 deletion_client=app.test_client();deletion_uid=ids[20];deletion_sid='retention-route-session'
 with app.app_context():
  db=core.get_db();now=int(time.time());db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(deletion_sid),deletion_uid,now,now,now+86400,'test'));db.commit()
 with deletion_client.session_transaction() as state:state.update(user_id=deletion_uid,user_handle='@AgeTest20',user_email='age-test-20@example.invalid',sid=deletion_sid,fresh_at=int(time.time()),theme_csrf_token='deletion-csrf')
 check(deletion_client.post('/account/data',data={'action':'delete-request','confirmation':'@AgeTest20'}).status_code==400,'Deletion request requires CSRF')
 with deletion_client.session_transaction() as state:state['fresh_at']=0
 result=deletion_client.post('/account/data',data={'theme_csrf_token':'deletion-csrf','action':'delete-request','confirmation':'@AgeTest20'})
 check(result.status_code==302 and '/account/reauth' in result.location,'Deletion requires renewed authorization')
 with deletion_client.session_transaction() as state:state['fresh_at']=int(time.time())
 check(deletion_client.post('/account/data',data={'theme_csrf_token':'deletion-csrf','action':'delete-request','confirmation':'wrong'}).status_code==400,'Deletion requires exact handle')
 result=deletion_client.post('/account/data',data={'theme_csrf_token':'deletion-csrf','action':'delete-request','confirmation':'@AgeTest20'})
 check(result.status_code==200,'Deletion request accepted without erasing account')
 with app.app_context():
  db=core.get_db();safety=db.execute('SELECT * FROM account_safety WHERE user_id=?',(deletion_uid,)).fetchone()
  check(safety['inactive']==1 and safety['deletion_requested_at'],'Deletion request immediately hides account')
  check(db.execute('SELECT 1 FROM users WHERE id=?',(deletion_uid,)).fetchone(),'Grace period preserves account')
  db.execute("UPDATE account_safety SET deletion_requested_at=datetime('now','-1 day') WHERE user_id=?",(deletion_uid,));db.commit();deadline=db.execute('SELECT deletion_requested_at FROM account_safety WHERE user_id=?',(deletion_uid,)).fetchone()[0]
 check(deletion_client.get('/feed').status_code==302,'Pending deletion restricts browsing to account controls')
 deletion_client.post('/account/data',data={'theme_csrf_token':'deletion-csrf','action':'delete-request','confirmation':'@AgeTest20'})
 with app.app_context():check(core.get_db().execute('SELECT deletion_requested_at FROM account_safety WHERE user_id=?',(deletion_uid,)).fetchone()[0]==deadline,'Repeated request does not restart grace period')
 deletion_client.post('/account/reactivate',data={'theme_csrf_token':'deletion-csrf'})
 with app.app_context():check(core.get_db().execute('SELECT inactive FROM account_safety WHERE user_id=?',(deletion_uid,)).fetchone()[0]==1,'Reactivation cannot bypass pending deletion')
 check(deletion_client.post('/account/export',data={'theme_csrf_token':'deletion-csrf'}).status_code==200,'Pending deletion still permits private export')
 check(deletion_client.post('/account/data',data={'theme_csrf_token':'deletion-csrf','action':'cancel-delete','confirmation':'@AgeTest20'}).status_code==200,'Cancellation available during grace period')
 with app.app_context():
  safety=core.get_db().execute('SELECT * FROM account_safety WHERE user_id=?',(deletion_uid,)).fetchone();check(safety['inactive']==0 and safety['deletion_requested_at'] is None,'Cancellation restores account visibility')

 from neonrest_sandbox import retention as retention
 helper_client=app.test_client();helper_uid=ids[20]
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO reserved_accounts(user_id,disabled) VALUES (?,1)',(helper_uid,));db.execute('UPDATE users SET verified=1,password_hash=? WHERE id=?',(core.generate_password_hash('ReservedTestPassword123!'),helper_uid));db.execute("UPDATE users SET created_at=datetime('now','-60 days'),verified=0 WHERE id=?",(helper_uid,));db.commit()
  check(helper_uid not in retention.plan(db)['accounts'],'Reserved helper excluded from abandoned registration cleanup')
  db.execute('UPDATE users SET verified=1 WHERE id=?',(helper_uid,));db.commit()
 with helper_client.session_transaction() as state:state['theme_csrf_token']='helper-csrf'
 helper_client.post('/login',data={'theme_csrf_token':'helper-csrf','email':'age-test-20@example.invalid','password':'ReservedTestPassword123!'})
 with helper_client.session_transaction() as state:check(not state.get('user_id'),'Disabled helper cannot sign in even with valid credentials')
 with helper_client.session_transaction() as state:state.update(user_id=helper_uid,sid=deletion_sid,user_handle='@AgeTest20',fresh_at=int(time.time()))
 response=helper_client.get('/account/data');check(response.status_code==302 and '/login' in response.location,'Disabled helper rejects existing authenticated session')
 with helper_client.session_transaction() as state:check(not state.get('user_id'),'Disabled helper session cleared')
 with app.app_context():check(core.get_db().execute('SELECT 1 FROM users WHERE id=?',(helper_uid,)).fetchone(),'Disabled helper account preserved')

 # General disable/restore controls use an isolated ordinary account and staff session.
 with app.app_context():
  db=core.get_db();victim=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified) VALUES ('@DisableTest','disable@test.invalid','test','1998-01-01',1)").lastrowid
  kept_post=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Preserve this post','public')",(victim,)).lastrowid
  for sid,uid in [('disable-admin',1),('disable-victim',victim)]:db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,int(time.time()),int(time.time()),int(time.time())+86400,'test'))
  db.commit()
 admin=app.test_client();ordinary=app.test_client()
 with admin.session_transaction() as state:state.update(user_id=1,user_handle='@brendoom',sid='disable-admin',fresh_at=int(time.time()),factor_at=int(time.time()),theme_csrf_token='disable-csrf')
 with ordinary.session_transaction() as state:state.update(user_id=victim,user_handle='@DisableTest',sid='disable-victim',fresh_at=int(time.time()),theme_csrf_token='victim-csrf')
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO account_safety(user_id,totp_secret) VALUES (1,?) ON CONFLICT(user_id) DO UPDATE SET totp_secret=excluded.totp_secret",('JBSWY3DPEHPK3PXP',));db.commit()
 endpoint=f'/manage/users/{victim}/disable'
 check(ordinary.post(endpoint,data={'theme_csrf_token':'victim-csrf','disabled':'1','reason':'test'}).status_code==403,'Ordinary user cannot disable an account')
 check(admin.post(endpoint,data={'disabled':'1','reason':'test'}).status_code==400,'Disable action requires CSRF')
 with admin.session_transaction() as state:state['fresh_at']=0
 response=admin.post(endpoint,data={'theme_csrf_token':'disable-csrf','disabled':'1','reason':'test'})
 check(response.status_code==302 and '/account/reauth' in response.location,'Disable action redirects stale staff authorization')
 with admin.session_transaction() as state:state['fresh_at']=int(time.time())
 check(admin.post(endpoint,data={'theme_csrf_token':'disable-csrf','disabled':'1','reason':'  '}).status_code==400,'Disable action requires a reason')
 check(admin.post('/manage/users/1/disable',data={'theme_csrf_token':'disable-csrf','disabled':'1','reason':'test'}).status_code==403,'Disable protects owner account')
 check(admin.post(endpoint,data={'theme_csrf_token':'disable-csrf','disabled':'1','reason':'Compromised integration'}).status_code==302,'Staff can disable ordinary account')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT disabled FROM account_disables WHERE user_id=?',(victim,)).fetchone()[0]==1,'Disabled state saved separately')
  check(not cf.member_visible(db,victim,None),'Disabled profile hidden from ordinary viewer')
  check(not cf.visible_post(db,kept_post,None),'Disabled posts hidden')
  check(db.execute('SELECT content FROM posts WHERE id=?',(kept_post,)).fetchone()[0]=='Preserve this post','Disable preserves content')
  check(db.execute('SELECT revoked FROM active_sessions WHERE token_hash=?',(cf.digest('disable-victim'),)).fetchone()[0]==1,'Disable revokes old sessions')
  check(db.execute("SELECT 1 FROM moderation_events WHERE target_user_id=? AND action='account-disable' AND reason='Compromised integration'",(victim,)).fetchone(),'Disable recorded in audit history')
  db.execute('INSERT INTO account_safety(user_id,inactive,deletion_requested_at) VALUES (?,1,CURRENT_TIMESTAMP)',(victim,));db.execute('INSERT INTO user_moderation(user_id,banned) VALUES (?,1)',(victim,));db.commit()
 check(admin.post(endpoint,data={'theme_csrf_token':'disable-csrf','disabled':'0','reason':'Integration secured'}).status_code==302,'Staff can restore disabled flag')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT disabled FROM account_disables WHERE user_id=?',(victim,)).fetchone()[0]==0,'Restore clears only disabled flag')
  row=db.execute('SELECT inactive,deletion_requested_at FROM account_safety WHERE user_id=?',(victim,)).fetchone();check(row[0]==1 and row[1],'Restore preserves personal deactivation and deletion request')
  check(db.execute('SELECT banned FROM user_moderation WHERE user_id=?',(victim,)).fetchone()[0]==1,'Restore preserves moderation ban')
  check(db.execute("SELECT 1 FROM moderation_events WHERE target_user_id=? AND action='account-restore'",(victim,)).fetchone(),'Restore recorded in audit history')
 check(b'Staff disable flag' in admin.get(f'/manage/users/{victim}').data,'Staff detail shows separate disable control')

 # Local birthday, consent, historic-post and existing-friend transitions.
 from neonrest_sandbox import age_clock as clock
 from datetime import datetime,timezone
 from zoneinfo import ZoneInfo
 real_local_date=clock.local_date;instant=[datetime(2026,10,12,6,59,tzinfo=timezone.utc)]
 clock.local_date=lambda zone,now=None:real_local_date(zone,now or instant[0])
 core.mail.send=lambda message:None
 with app.app_context():
  db=core.get_db();transition_ids={}
  for label,dob,zone in [('thirteen','2013-10-12','America/Los_Angeles'),('eighteen','2008-10-12','America/Los_Angeles'),('olderteen','2009-10-12','America/Los_Angeles'),('youngteen','2013-01-01','America/Los_Angeles'),('adult','1996-01-01','UTC'),('parent','1980-01-01','America/Los_Angeles')]:
   uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,timezone) VALUES (?,?,?,?,1,?)',('@Transition'+label,label+'@transition.invalid','test',dob,zone)).lastrowid;transition_ids[label]=uid
   db.execute('INSERT INTO age_clocks VALUES (?,?,1)',(uid,zone))
  young=transition_ids['youngteen'];older=transition_ids['olderteen'];teen=transition_ids['eighteen'];adult=transition_ids['adult'];parent=transition_ids['parent'];child=transition_ids['thirteen']
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(young,older))
  db.execute("INSERT INTO family_links(parent_id,child_id,status,method) VALUES (?,?,'approved','trained-personnel-phone')",(parent,teen))
  historic=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Minor-era history','public')",(teen,)).lastrowid;db.execute('INSERT INTO protected_age_posts VALUES (?)',(historic,));db.commit()
  check(ages.age(db,child)==12,'Pacific user remains twelve after UTC birthday')
  check(not ages.ready(db,child),'Under-13 without parent approval stays restricted until local birthday')
  check(ages.age(db,teen)==17,'Adult permissions wait for local midnight')
  check(ages.contact(db,young,older),'Existing mutual friendship works inside age band')
  check(ages.approved_parent(db,parent,teen),'Parent exception active before eighteenth birthday')
  db.execute('UPDATE users SET timezone=? WHERE id=?',('UTC',child));db.commit()
  check(ages.age(db,child)==12,'Display timezone changes cannot advance birthday permissions')
  try:db.execute('UPDATE age_clocks SET zone=? WHERE user_id=?',('UTC',child))
  except sqlite3.IntegrityError:db.rollback();check(True,'Confirmed birthday timezone locked in database')
  else:raise AssertionError('Birthday timezone changed')
  instant[0]=datetime(2026,10,12,7,0,tzinfo=timezone.utc)
  check(ages.age(db,child)==13 and ages.ready(db,child),'Thirteenth local birthday ends mandatory parent gating')
  check(ages.age(db,teen)==18,'Eighteenth local birthday applies at midnight')
  check(not ages.approved_parent(db,parent,teen),'Parent exception ends at eighteen')
  check(ages.contact(db,teen,adult),'Adult-to-adult age limit ends at eighteen')
  check(not ages.contact(db,young,older),'Existing friendship loses contact permission outside three-year band')
  check(db.execute("SELECT 1 FROM friend_requests WHERE sender_id=? AND receiver_id=? AND status='accepted'",(young,older)).fetchone(),'Birthday does not erase underlying friendship')
  check(not cf.visible_post(db,historic,adult),'Minor-era post remains protected after turning eighteen')
  current=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Adult public post','public')",(teen,)).lastrowid;db.commit()
  check(cf.visible_post(db,current,adult),'New adult public post uses adult audience')
  check(ages.age_of('2008-02-29',date(2026,2,28))==17 and ages.age_of('2008-02-29',date(2026,3,1))==18,'Leap birthday rolls conservatively on March first')
  check(real_local_date('America/Los_Angeles',datetime(2026,11,1,7,tzinfo=timezone.utc))==date(2026,11,1),'Daylight-saving zone uses calendar midnight')
  check(clock.valid_zone('Not/ARealZone') is None,'Invalid timezone rejected')
 birthday_guest=app.test_client()
 with birthday_guest.session_transaction() as state:state['theme_csrf_token']='birthday-csrf'
 signup_data={'email':'birthday-signup@example.invalid','handle':'BirthdaySignup','actual_name':'Birthday Test','password':'TestBirthdayPassword123!','dob':'2013-10-12','timezone':'America/Los_Angeles','age_confirmed':'1','consent':'on','theme_csrf_token':'birthday-csrf'}
 instant[0]=datetime(2026,10,12,6,59,tzinfo=timezone.utc)
 check(birthday_guest.post('/signup',data=signup_data,environ_overrides={'REMOTE_ADDR':'198.51.100.94'}).status_code==403,'Signup rejects pre-thirteenth local birthday')
 instant[0]=datetime(2026,10,12,7,0,tzinfo=timezone.utc)
 check(birthday_guest.post('/signup',data=signup_data,environ_overrides={'REMOTE_ADDR':'198.51.100.94'}).status_code==302,'Signup accepts thirteen at local midnight')
 with app.app_context():
  row=core.get_db().execute('SELECT c.zone,c.confirmed FROM age_clocks c JOIN users u ON u.id=c.user_id WHERE u.handle=?',('@BirthdaySignup',)).fetchone();check(row and row['zone']=='America/Los_Angeles' and row['confirmed']==1,'Signup persists confirmed local birthday clock')
 # Parent withdrawal clears permissions and invalidates under-13 sessions.
 instant[0]=datetime(2026,10,12,6,59,tzinfo=timezone.utc)
 parent_client=app.test_client()
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO family_links(parent_id,child_id,status,method) VALUES (?,?,'approved','trained-personnel-phone')",(parent,child));db.execute('INSERT INTO parent_contacts VALUES (?,?,?)',(parent,child,young))
  for sid,uid in [('transition-parent',parent),('transition-child',child)]:db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,int(time.time()),int(time.time()),int(time.time())+86400,'test'))
  db.commit();check(ages.ready(db,child),'Approved under-13 child is ready before withdrawal')
 with parent_client.session_transaction() as state:state.update(user_id=parent,user_handle='@Transitionparent',sid='transition-parent',fresh_at=int(time.time()),theme_csrf_token='parent-transition-csrf')
 check(parent_client.post('/account/family',data={'theme_csrf_token':'parent-transition-csrf','child_id':child,'action':'revoke'}).status_code==302,'Linked parent can withdraw consent')
 with app.app_context():
  db=core.get_db();check(not ages.ready(db,child),'Consent withdrawal immediately blocks under-13 social access')
  check(not ages.family(db,parent,child),'Withdrawn parent exception revoked')
  check(not db.execute('SELECT 1 FROM parent_contacts WHERE parent_id=? AND child_id=?',(parent,child)).fetchone(),'Withdrawal clears old parent contact grants')
  check(db.execute('SELECT revoked FROM active_sessions WHERE token_hash=?',(cf.digest('transition-child'),)).fetchone()[0]==1,'Withdrawal revokes child sessions')
  check(db.execute('SELECT reviewed_at FROM family_links WHERE parent_id=? AND child_id=?',(parent,child)).fetchone()[0],'Withdrawal timestamp retained')
 clock.local_date=real_local_date;core.mail.send=original_send

 # Tracked family review/deletion and DOB requests require genuine staff authorization.
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest('family-outsider'),adult,int(time.time()),int(time.time()),int(time.time())+86400,'test'));db.commit()
 outsider=app.test_client()
 with outsider.session_transaction() as state:state.update(user_id=adult,user_handle='@Transitionadult',sid='family-outsider',fresh_at=int(time.time()),theme_csrf_token='outsider-csrf')
 check(outsider.post('/account/family/requests',data={'theme_csrf_token':'outsider-csrf','child_id':child,'kind':'data-review'}).status_code==403,'Unlinked adult cannot request child information')
 check(parent_client.post('/account/family/requests',data={'child_id':child,'kind':'data-review'}).status_code==400,'Parent data request requires CSRF')
 check(parent_client.post('/account/family/requests',data={'theme_csrf_token':'parent-transition-csrf','child_id':child,'kind':'data-review','notes':'Review information'}).status_code==302,'Previously reviewed parent can request data after withdrawal')
 with app.app_context():data_id=core.get_db().execute("SELECT id FROM family_data_requests WHERE parent_id=? AND child_id=? AND kind='data-review'",(parent,child)).fetchone()[0]
 download=f'/account/family/requests/{data_id}/download'
 check(parent_client.get(download).status_code==404,'Pending request does not release child data')
 check(outsider.get(download).status_code==404,'Outsider cannot read parent request download')
 review={'theme_csrf_token':'disable-csrf','request_id':data_id,'action':'approve-access','reference':'Isolated guardian review'}
 check(admin.post('/manage/family/requests',data=review).status_code==403,'Staff must affirm reverified guardian authority')
 with admin.session_transaction() as state:state['fresh_at']=0
 review['guardian_verified']='1'
 response=admin.post('/manage/family/requests',data=review);check(response.status_code==302 and '/account/reauth' in response.location,'Family data release requires recent staff authorization')
 with admin.session_transaction() as state:state.update(fresh_at=int(time.time()),factor_at=int(time.time()))
 check(admin.post('/manage/family/requests',data=review).status_code==302,'Verified staff can grant temporary parent data access')
 response=parent_client.get(download);check(response.status_code==200,'Verified parent can download reviewed information')
 payload=response.get_json();check(payload['profile']['id']==child and 'password_hash' not in payload['profile'],'Reviewed data export contains only target child and excludes authentication secrets')
 check('private' in response.headers.get('Cache-Control','') and 'no-store' in response.headers.get('Cache-Control',''),'Parent data export cannot be cached')
 with app.app_context():db=core.get_db();db.execute('UPDATE family_data_requests SET expires_at=? WHERE id=?',(int(time.time())-1,data_id));db.commit()
 check(parent_client.get(download).status_code==404,'Expired parent data approval no longer grants access')
 check(parent_client.post('/account/family/requests',data={'theme_csrf_token':'parent-transition-csrf','child_id':child,'kind':'delete'}).status_code==302,'Parent may request child account deletion')
 with app.app_context():delete_id=core.get_db().execute("SELECT id FROM family_data_requests WHERE parent_id=? AND child_id=? AND kind='delete'",(parent,child)).fetchone()[0]
 review.update(request_id=delete_id,action='schedule-delete')
 check(admin.post('/manage/family/requests',data=review).status_code==302,'Reverified staff can schedule parent-requested deletion')
 with app.app_context():
  db=core.get_db();safety=db.execute('SELECT inactive,deletion_requested_at FROM account_safety WHERE user_id=?',(child,)).fetchone();check(safety and safety[0]==1 and safety[1],'Reviewed parent deletion hides account and starts grace period')
  check(db.execute('SELECT 1 FROM users WHERE id=?',(child,)).fetchone(),'Parent request does not immediately erase child')
  db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest('child-data-only'),child,int(time.time()),int(time.time()),int(time.time())+86400,'test'));db.commit()
 child_client=app.test_client()
 with child_client.session_transaction() as state:state.update(user_id=child,user_handle='@Transitionthirteen',sid='child-data-only',fresh_at=int(time.time()),theme_csrf_token='child-csrf')
 check(child_client.post('/account/data',data={'theme_csrf_token':'child-csrf','action':'cancel-delete','confirmation':'@Transitionthirteen'}).status_code==403,'Minor cannot bypass reviewed parent deletion')
 review.update(action='cancel-delete')
 check(admin.post('/manage/family/requests',data=review).status_code==302,'Staff may cancel parent-directed deletion after guardian review')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT deletion_requested_at FROM account_safety WHERE user_id=?',(child,)).fetchone()[0] is None,'Reviewed cancellation clears parent deletion request')
  check(ages.age(db,child)>=13 or not ages.ready(db,child),'Cancellation cannot bypass consent while under 13')
  check(not ages.approved_parent(db,parent,child),'Cancellation does not reinstate withdrawn parental consent')
  old_dob=db.execute('SELECT dob FROM users WHERE id=?',(parent,)).fetchone()[0]
 check(parent_client.post('/account/family/requests',data={'theme_csrf_token':'parent-transition-csrf','child_id':parent,'kind':'dob-correction','notes':'Entered date needs review'}).status_code==302,'DOB correction request can be tracked without storing new DOB')
 with app.app_context():check(core.get_db().execute('SELECT dob FROM users WHERE id=?',(parent,)).fetchone()[0]==old_dob,'DOB request leaves immutable date unchanged')
 check(parent_client.get('/account/family/requests').status_code==200,'Parent can track private request status')
 check(admin.get('/manage/family/requests').status_code==200,'Staff request review screen renders')
  # One-time birthday-clock setup uses existing authorization protections.
 check(parent_client.post('/account/age/clock',data={'zone':'America/Los_Angeles'}).status_code==400,'Birthday timezone setup requires CSRF')
 with parent_client.session_transaction() as state:state['fresh_at']=int(time.time())-1801
 check(parent_client.post('/account/age/clock',data={'theme_csrf_token':'parent-transition-csrf','zone':'America/Los_Angeles'}).status_code==302,'Expired birthday-clock authorization directs to reauthorization')
 with parent_client.session_transaction() as state:state['fresh_at']=int(time.time())
 check(parent_client.post('/account/age/clock',data={'theme_csrf_token':'parent-transition-csrf','zone':'America/Los_Angeles','child_id':child}).status_code==403,'Revoked family link cannot set child birthday timezone')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM age_clocks WHERE user_id=?',(parent,));db.execute('INSERT INTO age_clocks VALUES (?,?,0)',(parent,'UTC'));db.commit()
 check(parent_client.post('/account/age/clock',data={'theme_csrf_token':'parent-transition-csrf','zone':'Invalid/Zone'}).status_code==400,'Invalid birthday timezone rejected at route')
 check(parent_client.post('/account/age/clock',data={'theme_csrf_token':'parent-transition-csrf','zone':'America/Los_Angeles'}).status_code==302,'One-time valid birthday timezone can be confirmed')
 with app.app_context():check(tuple(core.get_db().execute('SELECT zone,confirmed FROM age_clocks WHERE user_id=?',(parent,)).fetchone())==('America/Los_Angeles',1),'Confirmed birthday timezone stored independently')
 check(parent_client.post('/account/age/clock',data={'theme_csrf_token':'parent-transition-csrf','zone':'Pacific/Kiritimati'}).status_code==400,'Confirmed birthday timezone cannot be changed through route')
print(f'PASS: {checks} isolated age and consent checks; live accounts and production unchanged')
