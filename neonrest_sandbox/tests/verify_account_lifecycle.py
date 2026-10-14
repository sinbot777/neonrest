"""T05 account lifecycle checks in a disposable source and database copy; SMTP is mocked."""
from pathlib import Path
import os,sys,sqlite3,tempfile,shutil,contextlib,io,time,re,json
from werkzeug.security import generate_password_hash,check_password_hash
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'));checks=0

def check(value,label):
 global checks
 assert value,label
 checks+=1
with tempfile.TemporaryDirectory(prefix='neonrest-lifecycle-') as temp:
 root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
 for name in ('templates','routes','utils'):shutil.copytree(live/name,stage/name)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
 before=source.execute('SELECT count(*),sum(verified) FROM users').fetchone()
 dbpath=root/'test.db';dest=sqlite3.connect(dbpath);source.backup(dest);dest.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath)
 os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret')
 sys.path.insert(0,str(root))
 with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
 from neonrest_sandbox import community_features as cf,retention
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/')
 mails=[];core.mail.send=lambda msg:mails.append(msg)
 now=int(time.time());password='Synthetic-only-pass-123';csrf='lifecycle-csrf'
 with app.app_context():
  db=core.get_db()
  def add(handle,email,verified=1,dob='1998-01-01'):
   db=core.get_db()
   uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,?)',(handle,email,generate_password_hash(password),dob,verified)).lastrowid
   db.commit();return uid
  uid=add('@LifecycleOwner','owner@example.com');other=add('@LifecycleOther','other@example.com');unknown=add('@LifecycleUnknown','unknown@example.com',dob=None)
  db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?)',(uid,'JBSWY3DPEHPK3PXP'))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(uid,other))
  post=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Lifecycle post','public')",(uid,)).lastrowid;db.commit()
 def client(who=uid,suffix='',fresh=True,factor=True):
  sid=f'lifecycle-{who}-{suffix}';c=app.test_client()
  with app.app_context():
   db=core.get_db();u=db.execute('SELECT * FROM users WHERE id=?',(who,)).fetchone()
   db.execute('INSERT OR REPLACE INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),who,now,now,now+3600,'isolated-lifecycle'));db.commit()
  with c.session_transaction() as s:s.update(user_id=who,user_email=u['email'],user_handle=u['handle'],sid=sid,fresh_at=now if fresh else now-1801,factor_at=now if factor else now-1801,theme_csrf_token=csrf)
  return c
 def request(c,email):return c.post('/account/email',data={'theme_csrf_token':csrf,'email':email})
 def token_url():return re.search(r'https://www.neonrest.com(/\S+)',mails[-1].body).group(1)
 def clear_rate():
  with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
 c=client();peer=client(other);guest=app.test_client()
 check(c.get('/account/email').status_code==200,'Email settings render')
 check(b'Change email' in c.get('/account/security').data,'Email change is discoverable in Account safety')
 check(client(unknown).get('/account/email').status_code==200,'Missing DOB can manage email without opening social access')
 check(guest.get('/account/email').status_code==401,'Email change requires sign-in')
 check(c.post('/account/email',data={'email':'new@example.com'}).status_code==400,'Email request requires CSRF')
 res=request(client(suffix='stale',fresh=False),'new@example.com');check(res.status_code==302 and '/reauth' in res.location,'Expired password authorization redirects to renewal')
 res=request(client(suffix='factor-stale',factor=False),'new@example.com');check(res.status_code==302 and '/reauth' in res.location,'Expired second factor redirects to renewal')
 check(request(c,'bad-address').status_code==400,'Invalid address rejected')
 check(request(c,'OWNER@example.com').status_code==400,'Current email comparison ignores case')
 check(request(c,'OTHER@example.com').status_code==400,'Existing email collision ignores case')
 clear_rate()
 res=request(c,'first@example.com');first=token_url();check(res.status_code==302,'Email confirmation requested')
 with app.app_context():
  db=core.get_db();check(tuple(db.execute('SELECT email,verified FROM users WHERE id=?',(uid,)).fetchone())==('owner@example.com',1),'Request leaves old login verified and unchanged')
  row=db.execute('SELECT * FROM email_changes WHERE user_id=? ORDER BY id DESC',(uid,)).fetchone();check(row['token_hash']==cf.digest(first.rsplit('/',1)[1]),'Only token hash stored');check(row['expires_at']-row['created_at']==3600,'Email token expires in one hour')
 check(c.get(first).status_code==200,'Owner sees styled confirmation')
 check(peer.get(first).status_code==400,'Another signed-in account cannot confirm owner token')
 check(c.post(first,data={}).status_code==400,'Email confirmation requires CSRF')
 res=client(suffix='confirm-stale',fresh=False).post(first,data={'theme_csrf_token':csrf});check(res.status_code==302 and '/reauth' in res.location,'Email completion requires fresh authorization')
 with app.app_context():check(core.get_db().execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()[0]=='owner@example.com','GET and rejected submissions do not change email')
 res=request(c,'second@example.com');second=token_url();check(res.status_code==302,'New confirmation replaces previous request')
 check(c.get(first).status_code==400,'Replaced email token invalid')
 def fail(msg):raise RuntimeError('mock SMTP failure')
 core.mail.send=fail
 check(request(c,'failed@example.com').status_code==503,'Delivery failure renders actionable error')
 core.mail.send=lambda msg:mails.append(msg)
 check(c.get(second).status_code==200,'Failed delivery preserves prior delivered pending request')
 check(c.post('/account/email',data={'theme_csrf_token':csrf,'action':'cancel'}).status_code==302,'Owner can cancel email change')
 check(c.get(second).status_code==400,'Cancelled email token invalid')
 request(c,'expired@example.com');expired=token_url()
 with app.app_context():core.get_db().execute('UPDATE email_changes SET expires_at=? WHERE user_id=?',(now-1,uid));core.get_db().commit()
 check(c.get(expired).status_code==400,'Expired confirmation displays error')
 clear_rate()
 request(c,'collision@example.com');collision=token_url()
 with app.app_context():collision_owner=add('@Collision','COLLISION@example.com')
 check(c.post(collision,data={'theme_csrf_token':csrf}).status_code==409,'Collision after issue is rejected atomically')
 with app.app_context():check(core.get_db().execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()[0]=='owner@example.com','Collision preserves current email')
 check(request(c,'new@example.com').status_code==302,'Final new address requested');final=token_url();old_session=client(suffix='other-device')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO password_resets VALUES (?,?,?,0)',(cf.digest('old-reset'),uid,now+3600));db.execute('INSERT INTO email_verifications VALUES (?,?,?,?,?,0)',(cf.digest('old-verification'),uid,'owner@example.com',now,now+3600));db.commit()
 check(c.post(final,data={'theme_csrf_token':csrf}).status_code==302,'Owner confirms address')
 with app.app_context():
  db=core.get_db();check(tuple(db.execute('SELECT email,verified,dob FROM users WHERE id=?',(uid,)).fetchone())==('new@example.com',1,'1998-01-01'),'Verified email changes without altering DOB')
  check(check_password_hash(db.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone()[0],password),'Email change preserves password')
  check(db.execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone()[0]=='JBSWY3DPEHPK3PXP','Email change preserves 2FA')
  check(db.execute('SELECT 1 FROM friend_requests WHERE sender_id=? AND receiver_id=?',(uid,other)).fetchone(),'Email change preserves friendship')
  check(db.execute('SELECT 1 FROM posts WHERE id=?',(post,)).fetchone(),'Email change preserves post')
  for table in ('password_resets','email_verifications','email_changes'):check(not db.execute('SELECT 1 FROM '+table+' WHERE user_id=? AND used=0',(uid,)).fetchone(),table+' invalidated on email change')
  check(not db.execute('SELECT 1 FROM active_sessions WHERE user_id=? AND revoked=0',(uid,)).fetchone(),'Every owner session revoked')
 check(old_session.get('/account/security').status_code==302,'Other device loses access on next request')
 login=app.test_client()
 with login.session_transaction() as st:st['theme_csrf_token']=csrf
 res=login.post('/login',data={'theme_csrf_token':csrf,'email':'owner@example.com','password':password})
 with login.session_transaction() as st:check(not st.get('user_id') and not st.get('factor_pending'),'Old email no longer signs in')
 res=login.post('/login',data={'theme_csrf_token':csrf,'email':'new@example.com','password':password})
 check(res.status_code==302 and '/login/verify' in res.location,'New email still requires the existing second factor')
 check(mails[-1].recipients==['owner@example.com'] and 'new@example.com' not in mails[-1].body and final not in mails[-1].body,'Old-address notice contains no new email or secret token')
 c=client(suffix='new-address');check(c.get(final).status_code==400,'Completed confirmation cannot replay')
 exported=c.post('/account/export',data={'theme_csrf_token':csrf});data=exported.get_json()
 check(exported.status_code==200,'Owner export works after email change')
 check(data['profile']['email']=='new@example.com','Export reports current email')
 check('email_changes' not in data and 'password_resets' not in data,'Export excludes auth token tables')
 check(data['account_lifecycle_events'] and all(r['user_id']==uid for r in data['account_lifecycle_events']),'Export includes only owner lifecycle events')
 check('token_hash' not in exported.get_data(as_text=True) and 'JBSWY3DPEHPK3PXP' not in exported.get_data(as_text=True),'Export contains no recovery token hashes or 2FA secret')
 clear_rate();request(c,'pending@example.com');pending=token_url()
 with app.app_context():core.get_db().execute('INSERT INTO password_resets VALUES (?,?,?,0)',(cf.digest('password-change-reset'),uid,now+3600));core.get_db().commit()
 check(c.post('/account/security',data={'theme_csrf_token':csrf,'action':'password','new_password':'Synthetic-new-pass-123'}).status_code==302,'Password change succeeds in isolated account')
 c=client(suffix='after-password');check(c.get(pending).status_code==400,'Password change invalidates pending email token')
 check(guest.get('/password-reset/password-change-reset').status_code==400,'Password change invalidates old reset link')
 clear_rate();request(c,'reset-pending@example.com');reset_pending=token_url()
 with app.app_context():
  db=core.get_db()
  for raw in ('reset-one','reset-two'):db.execute('INSERT INTO password_resets VALUES (?,?,?,0)',(cf.digest(raw),uid,now+3600))
  db.commit()
 with guest.session_transaction() as s:s['theme_csrf_token']=csrf
 check(guest.post('/password-reset/reset-one',data={'theme_csrf_token':csrf,'new_password':'Synthetic-reset-pass-123'}).status_code==302,'Password reset succeeds in isolated account')
 check(guest.get('/password-reset/reset-two').status_code==400,'Reset invalidates every older reset link')
 c=client(suffix='after-reset');check(c.get(reset_pending).status_code==400,'Reset invalidates pending email change')
 for action in ('deactivate','delete-request'):
  clear_rate();request(c,action+'@example.com');pending=token_url()
  result=c.post('/account/data',data={'theme_csrf_token':csrf,'confirmation':'@LifecycleOwner','action':action});check(result.status_code==(302 if action=='deactivate' else 200),action+' accepted')
  with app.app_context():
   db=core.get_db();check(not db.execute('SELECT 1 FROM email_changes WHERE user_id=? AND used=0',(uid,)).fetchone(),action+' invalidates pending email');check(db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(),action+' remains reversible without erasure')
   db.execute('UPDATE account_safety SET inactive=0,deletion_requested_at=NULL WHERE user_id=?',(uid,));db.commit()
  c=client(suffix=action)
 clear_rate()
 c.set_cookie(app.config['SESSION_COOKIE_NAME'],c.get_cookie(app.config['SESSION_COOKIE_NAME']).value,domain='evil.example')
 res=c.post('/account/email',data={'theme_csrf_token':csrf,'email':'trusted-host@example.com'},environ_overrides={'SCRIPT_NAME':'/sandbox','HTTP_HOST':'evil.example'})
 check(res.status_code==302 and 'https://www.neonrest.com/sandbox/account/email/confirm/' in mails[-1].body and 'evil.example' not in mails[-1].body,'Email confirmation uses trusted host and Sandbox prefix')
 clear_rate()
 for n in range(5):check(request(c,f'rate-{n}@example.com').status_code==302,'Allowed email request '+str(n))
 check(request(c,'rate-blocked@example.com').status_code==429,'Email change rate limited')
 check(c.get('/account/email').headers.get('Cache-Control')=='private, no-store','Email page is never cached')
 check(c.get('/account/email').headers.get('Referrer-Policy')=='no-referrer','Email page prevents token referrer leakage')
 check(source.execute('SELECT count(*),sum(verified) FROM users').fetchone()==before,'Live user rows unchanged');source.close()
 print('PASS:',checks,'isolated account lifecycle checks; SMTP mocked; live accounts and production unchanged')
