"""T06: disposable source/DB, fake SMTP only; no live credentials, emails or deletions."""
from pathlib import Path
import os,sys,sqlite3,tempfile,shutil,contextlib,io,time,re,smtplib,ssl
from unittest.mock import patch
from werkzeug.security import generate_password_hash
checks=0;live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
def check(v,label):
 global checks
 assert v,label
 checks+=1
with tempfile.TemporaryDirectory(prefix='neonrest-email-test-') as temp:
 root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
 for name in ('templates','routes','utils'):shutil.copytree(live/name,stage/name)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True);before=source.execute('SELECT count(*),sum(verified) FROM users').fetchone()
 dbpath=root/'test.db';dest=sqlite3.connect(dbpath);source.backup(dest);dest.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath);os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret');sys.path.insert(0,str(root))
 with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
 from neonrest_sandbox import community_features as cf,email_verification as ev,email_delivery as ed
 from flask_mail import Message
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/')
 now=int(time.time());password='Synthetic-only-email-123';csrf='email-test-csrf'
 with app.app_context():
  db=core.get_db();uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,0)',('@EmailRecovery','recovery@example.com',generate_password_hash(password),'1998-01-01')).lastrowid;db.commit()
 def clear_rate():
  with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
 guest=app.test_client()
 with guest.session_transaction() as ss:ss['theme_csrf_token']=csrf
 original_send=core.mail.send;mails=[];core.mail.send=lambda msg:mails.append(msg)
 def getlink(msg,kind):return re.search('https://www.neonrest.com(/'+kind+'/[^\\s]+)',msg.body).group(1)
 def resend(email='recovery@example.com'):return guest.post('/verify-email',data={'theme_csrf_token':csrf,'email':email})
 def reset(email='recovery@example.com'):return guest.post('/password-reset',data={'theme_csrf_token':csrf,'email':email})
 def expire_cooldown():
  with app.app_context():core.get_db().execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(now-61,uid));core.get_db().commit()
 check(resend().status_code==200,'Verification request is handled');first=getlink(mails[-1],'verify_email')
 expire_cooldown();core.mail.send=lambda msg:False
 failed=resend();check(failed.status_code==200,'Verification failure keeps generic response')
 check(b'wait a minute and try again' in failed.data,'Verification response explains retry')
 with app.app_context():
  db=core.get_db();check(db.execute('SELECT used FROM email_verifications WHERE token_hash=?',(cf.digest(first.rsplit('/',1)[1]),)).fetchone()[0]==0,'Failed replacement preserves old verification')
  check(db.execute('SELECT count(*) FROM email_verifications WHERE user_id=? AND used=2',(uid,)).fetchone()[0]==0,'Failed verification does not remain pending')
  check(db.execute('SELECT verified FROM users WHERE id=?',(uid,)).fetchone()[0]==0,'Failure never verifies an account')
 core.mail.send=lambda msg:mails.append(msg);n=len(mails);resend();second=getlink(mails[-1],'verify_email');check(len(mails)==n+1,'Failure creates no artificial resend cooldown')
 check(guest.get(first).status_code==400,'Accepted replacement invalidates previous verification')
 n=len(mails);resend();check(len(mails)==n,'Successful resend observes one-minute cooldown')
 check(guest.get(second).status_code==200,'Accepted replacement verifies correctly')
 clear_rate();reset();first_reset=getlink(mails[-1],'password-reset')
 core.mail.send=lambda msg:False;failed=reset();check(failed.status_code==200,'Reset False result handled generically')
 check(guest.get(first_reset).status_code==200,'Reset False result preserves previous link')
 def fail(msg):raise RuntimeError('DO-NOT-LOG recovery@example.com secret-token')
 core.mail.send=fail;check(reset().status_code==200,'Reset exception handled generically');check(guest.get(first_reset).status_code==200,'Reset exception preserves previous link')
 with app.app_context():check(not core.get_db().execute('SELECT 1 FROM password_resets WHERE user_id=? AND used=2',(uid,)).fetchone(),'Failed reset does not leave a usable new token')
 core.mail.send=lambda msg:mails.append(msg);reset();second_reset=getlink(mails[-1],'password-reset')
 check(guest.get(first_reset).status_code==400,'Accepted reset replacement invalidates old link')
 check(guest.get(second_reset).status_code==200,'Accepted reset replacement works')
 clear_rate();known=reset();unknown=reset('absent@example.com')
 check(known.status_code==unknown.status_code==200,'Known and unknown reset requests share status')
 # Flash text stays generic even if actual delivery failed.
 core.mail.send=lambda msg:False;known=reset();unknown=reset('absent@example.com')
 check(b'If that account is eligible' in known.data and b'If that account is eligible' in unknown.data,'Failure feedback does not reveal account existence')
 clear_rate();responses=[reset('absent@example.com').status_code for _ in range(6)]
 check(responses==[200]*5+[429],'Reset requests limited to five per fifteen minutes')
 clear_rate()
 check(guest.post('/password-reset',data={'email':'recovery@example.com'}).status_code==400,'Reset still requires CSRF')
 clear_rate()
 with app.app_context():
  db=core.get_db();db.execute('UPDATE users SET verified=0 WHERE id=?',(uid,));db.execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(now-61,uid));db.commit()
 res=guest.post('/login',data={'theme_csrf_token':csrf,'email':'recovery@example.com','password':password})
 check(res.status_code==302,'Unverified correct-password login stays unsigned')
 res=guest.get(res.location);check(b'We could not send your verification email' in res.data,'Proven account owner sees honest delivery failure')
 with guest.session_transaction() as ss:check('user_id' not in ss,'Delivery failure creates no authenticated session')
 clear_rate()
 core.validate_email=lambda value:None # Signup DNS validation is not a mail-failure test.
 signup={'email':'signup-outage@example.com','handle':'SignupOutage','actual_name':'Synthetic Test','password':password,'dob':'1998-01-01','timezone':'UTC','age_confirmed':'1','consent':'on','theme_csrf_token':csrf}
 res=guest.post('/signup',data=signup,environ_overrides={'SCRIPT_NAME':'/sandbox'})
 check(res.status_code==302 and res.location=='/sandbox/login','Failed signup email stays in Sandbox')
 with app.app_context():
  db=core.get_db();saved=db.execute('SELECT id,verified,dob FROM users WHERE email=?',('signup-outage@example.com',)).fetchone();check(saved and saved['verified']==0 and saved['dob']=='1998-01-01','SMTP failure preserves unverified signup and DOB')
 res=guest.get('/login');check(b'Account created, but the verification email could not be delivered' in res.data,'Signup never falsely claims a sent email')
 core.mail.send=lambda msg:mails.append(msg);resend('signup-outage@example.com');check(mails[-1].recipients==['signup-outage@example.com'],'Signup outage is recoverable via resend')
 res=guest.post('/signup',data=signup,environ_overrides={'SCRIPT_NAME':'/sandbox'});check(res.status_code==302 and res.location=='/sandbox/signup','Duplicate signup stays in Sandbox')
 with app.app_context():check(core.get_db().execute('SELECT count(*) FROM users WHERE email=?',('signup-outage@example.com',)).fetchone()[0]==1,'Resubmission creates no duplicate account')
 # Pending/overlapping token sends: exercise the exact finalization used by routes.
 with app.app_context():
  db=core.get_db()
  for table in ('email_verifications','password_resets'):
   hashes=[cf.digest(table+suffix) for suffix in ('older','newer','cancelled')]
   for h in hashes:
    if table=='email_verifications':db.execute('INSERT INTO email_verifications VALUES (?,?,?,?,?,2)',(h,uid,'recovery@example.com',now,now+3600))
    else:db.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600))
   db.commit()
   pending_path=('/verify_email/' if table=='email_verifications' else '/password-reset/')+(table+'older')
   check(guest.get(pending_path).status_code==400,table+' pending link is not usable before acceptance')
   ed.finish_token_delivery(db,table,hashes[1],True);ed.finish_token_delivery(db,table,hashes[0],True)
   check(db.execute('SELECT used FROM '+table+' WHERE token_hash=?',(hashes[0],)).fetchone()[0]==1,table+' older completion cannot supersede newer success')
   check(db.execute('SELECT used FROM '+table+' WHERE token_hash=?',(hashes[1],)).fetchone()[0]==0,table+' newer token remains active')
   db.execute('UPDATE '+table+' SET used=1 WHERE token_hash=?',(hashes[2],));db.commit();ed.finish_token_delivery(db,table,hashes[2],True)
   check(db.execute('SELECT used FROM '+table+' WHERE token_hash=?',(hashes[2],)).fetchone()[0]==1,table+' completion cannot resurrect cancelled token')
 with app.test_request_context('/verify-email'),patch.object(ev,'issue_token',return_value=None) as issued:
  db=core.get_db();db.execute('UPDATE email_verifications SET created_at=? WHERE user_id=?',(now-61,uid));db.commit()
  check(ev.send_verification(core,db,'recovery@example.com') is True and issued.called,'Concurrent verification completion is handled without constructing a broken link')
 # Installed transport: no real SMTP calls, fake server exercises Flask-Mail itself.
 core.mail.send=original_send;plans=[];hosts=[]
 class FakeSMTP:
  def __init__(self,*args,**kwargs):self.options=kwargs;self.outcome=plans.pop(0) if plans else None;self.closed=False;self.debug=None;self.context=kwargs.get('context');self.auth=False;hosts.append(self)
  def set_debuglevel(self,value):self.debug=value
  def starttls(self,context=None):self.context=context;return (220,b'ok')
  def login(self,*args):self.auth=True;return (235,b'ok')
  def sendmail(self,*args,**kwargs):
   if isinstance(self.outcome,BaseException):raise self.outcome
   return {}
  def close(self):
   self.closed=True
   if self.outcome=='close-fails':raise OSError('DO-NOT-LOG cleanup')
  def quit(self):raise AssertionError('QUIT must not relabel an accepted send')
 with patch.object(ed.smtplib,'SMTP',FakeSMTP),patch.object(ed.smtplib,'SMTP_SSL',FakeSMTP),app.app_context():
  msg=Message(subject='Synthetic delivery test',recipients=['synthetic@example.com'],body='No real message sent')
  check(core.mail.send(msg) is True,'Fake SMTP accepts message through installed wrapper')
  check(hosts[-1].options['timeout']==8,'SMTP has explicit eight-second socket timeout')
  check(hosts[-1].debug==0,'SMTP debug output disabled')
  check(hosts[-1].context.verify_mode==ssl.CERT_REQUIRED and hosts[-1].context.check_hostname,'STARTTLS verifies certificates and hostnames')
  check(hosts[-1].auth and hosts[-1].closed,'Connection authenticates and closes')
  plans[:]=['close-fails'];check(core.mail.send(msg) is True,'Cleanup failure cannot relabel accepted email as failed')
  state=app.extensions['mail'];state.use_tls=False;state.use_ssl=True
  check(core.mail.send(msg) is True and hosts[-1].options['context'].verify_mode==ssl.CERT_REQUIRED,'SMTP SSL also uses verified TLS and timeout')
  state.use_ssl=False;start=len(hosts);check(core.mail.send(msg) is False and len(hosts)==start,'Unencrypted SMTP is refused before connecting');state.use_tls=True
  start=len(hosts);plans[:]=[smtplib.SMTPDataError(451,b'Temporary rejection'),None]
  check(core.mail.send(msg) is True and len(hosts)==start+2,'One temporary rejection is retried automatically')
  start=len(hosts);plans[:]=[smtplib.SMTPDataError(451,b'Temporary rejection')]*2
  check(core.mail.send(msg) is False and len(hosts)==start+2,'Repeated rejection stops after two attempts')
  for failure in (smtplib.SMTPDataError(550,b'Permanent rejection'),smtplib.SMTPAuthenticationError(535,b'bad credentials'),TimeoutError('DO-NOT-LOG secret'),smtplib.SMTPServerDisconnected('DO-NOT-LOG secret'),ssl.SSLCertVerificationError('DO-NOT-LOG secret')):
   start=len(hosts);plans[:]=[failure];check(core.mail.send(msg) is False and len(hosts)==start+1,type(failure).__name__+' does not retry')
  db=core.get_db();events=db.execute("SELECT detail FROM operations_events WHERE kind='email' ORDER BY id DESC LIMIT 20").fetchall();text=' '.join(x[0] for x in events)
  check('accepted' in text and 'failed' in text and 'attempts=2' in text,'Staff receives redacted delivery outcome/attempt records')
  check('DO-NOT-LOG' not in text and 'synthetic@example.com' not in text and 'secret-token' not in text,'Operations records exclude recipient and token content')
 check(ed.retryable(smtplib.SMTPRecipientsRefused({'one@example.com':(450,b'wait')})),'Temporary recipient refusal can retry')
 check(not ed.retryable(smtplib.SMTPRecipientsRefused({'one@example.com':(450,b'wait'),'two@example.com':(550,b'no')})),'Mixed permanent recipient refusal cannot retry')
 for exc in (smtplib.SMTPConnectError(421,b'wait'),smtplib.SMTPHeloError(450,b'wait'),smtplib.SMTPSenderRefused(450,b'wait','synthetic@example.com')):check(ed.retryable(exc),'Definite temporary '+type(exc).__name__+' can retry')
 check(source.execute('SELECT count(*),sum(verified) FROM users').fetchone()==before,'Live user rows unchanged');source.close()
 print('PASS:',checks,'isolated email resilience checks; fake SMTP only; live accounts and production unchanged')
