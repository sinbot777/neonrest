"""T06-Q: isolated DB/source/key/ledger; synthetic recipients; fake SMTP only."""
import os,sys,sqlite3,tempfile,shutil,time,contextlib,io,smtplib,json,re,subprocess
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
with tempfile.TemporaryDirectory(prefix='neonrest-queue-') as temp:
 root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
 for n in ('templates','routes','utils'):shutil.copytree(live/n,stage/n)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
 before=source.execute('SELECT count(*),sum(verified) FROM users').fetchone()
 dbpath=root/'test.db';dest=sqlite3.connect(dbpath);source.backup(dest);dest.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath);os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret');os.environ['NEONREST_SANDBOX_MAIL_QUEUE_DIR']=str(root/'queue');sys.path.insert(0,str(root))
 with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
 from neonrest_sandbox import mail_queue as q,community_features as cf,email_verification as ev,retention
 from flask_mail import Message
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=True,MAIL_QUEUE_ENABLED=True,SESSION_COOKIE_PATH='/');now=int(time.time());csrf='synthetic-queue-csrf';password='Synthetic-queue-password123'
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM mail_jobs');db.commit();q.provision(app)
  check((root/'queue'/'key.json').stat().st_mode&0o077==0,'Key private');check((root/'queue'/'attempts.db').stat().st_mode&0o077==0,'Ledger private')
  def add(handle,email,verified=1):
   db=core.get_db()
   uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,?)',(handle,email,generate_password_hash(password),'1998-01-01',verified)).lastrowid;db.commit();return uid
  uid=add('@QueueOwner','queue@example.com');unverified=add('@QueueUnverified','unverified@example.com',0);admin=add('@QueueStaff','staff@example.com');peer=add('@QueuePeer','peer@example.com')
  db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'admin')",(admin,));db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?)',(admin,'JBSWY3DPEHPK3PXP'));db.commit()
 def client(who=None,fresh=True):
  c=app.test_client()
  with c.session_transaction() as ss:ss['theme_csrf_token']=csrf
  if who:
   sid='queue-'+str(who)+str(fresh)
   with app.app_context():
    d=core.get_db();u=d.execute('SELECT * FROM users WHERE id=?',(who,)).fetchone();d.execute('INSERT OR REPLACE INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),who,now,now,now+3600,'queue-tests'));d.commit()
   with c.session_transaction() as ss:ss.update(user_id=who,user_email=u['email'],user_handle=u['handle'],sid=sid,fresh_at=now if fresh else now-1801,factor_at=now if fresh else now-1801)
  return c
 guest=client();owner=client(uid);staff=client(admin);sent=[]
 def fake(data,jid):sent.append((dict(data),jid));return True
 core.mail.send=lambda msg:(_ for _ in ()).throw(AssertionError('Request path must not use SMTP'))
 def drain(send=fake):
  with app.app_context():return q.run_once(app,core,send=send)
 def reset():return guest.post('/password-reset',data={'theme_csrf_token':csrf,'email':'queue@example.com'})
 def raw_from_sent():return re.search(r'https://www.neonrest.com(/\S+)',sent[-1][0]['body']).group(1)
 def latest():
  return core.get_db().execute('SELECT * FROM mail_jobs ORDER BY rowid DESC LIMIT 1').fetchone()
 check(reset().status_code==200,'Reset request queues without SMTP')
 with app.app_context():
  d=core.get_db();job=latest();first=dict(job);check(job['state']=='queued','Durable queued state');check(d.execute('SELECT used FROM password_resets WHERE token_hash=?',(job['token_hash'],)).fetchone()[0]==2,'Queued link inactive')
  check(b'queue@example.com' not in job['payload'] and b'Reset your' not in job['payload'],'Payload encrypted')
  value,crypto=q.key(app);payload=json.loads(crypto.decrypt(job['payload']));check(payload['recipient']=='queue@example.com','Encrypted payload reversible with private key')
  m=Message(subject=payload['subject'],recipients=[payload['recipient']],body=payload['body']);check(q.enqueue(app,d,m,uid,'reset',job['token_hash'])=='queued','Duplicate intent idempotent');check(d.execute('SELECT count(*) FROM mail_jobs WHERE token_hash=?',(job['token_hash'],)).fetchone()[0]==1,'Dedupe one job')
 check(drain()==1 and len(sent)==1,'Worker sends single eligible job');first_link=raw_from_sent();check(guest.get(first_link).status_code==200,'Acceptance activates reset link')
 with app.app_context():check(latest()['payload'] is None,'Accepted payload promptly cleared')
 check(drain()==0 and len(sent)==1,'No repeated acceptance')
 check(reset().status_code==200,'Replacement queues');
 with app.app_context():replacement=dict(latest())
 check(guest.get(first_link).status_code==200,'Queueing preserves old usable link')
 def temporary(data,jid):raise smtplib.SMTPDataError(451,b'DO NOT LOG queue@example.com rawtoken')
 check(drain(temporary)==1,'Definite 4xx attempted once per cycle')
 with app.app_context():
  d=core.get_db();j=latest();check(j['state']=='retry' and j['attempts']==1,'4xx retry scheduled');check(20<=j['next_at']-int(time.time())<=30,'Bounded first backoff');check(j['payload'] is not None,'Short-lived retry payload retained');check(j['last_error']=='SMTPDataError','Only error class persisted')
 check(drain()==0,'Retry not sent early');check(guest.get(first_link).status_code==200,'Rejected replacement preserves old link')
 with app.app_context():core.get_db().execute('UPDATE mail_jobs SET next_at=0 WHERE id=?',(replacement['id'],));core.get_db().commit()
 check(drain()==1,'Due retry accepted');second_link=raw_from_sent();check(guest.get(first_link).status_code==400,'Accepted replacement cancels old link');check(guest.get(second_link).status_code==200,'Replacement usable')
 # Retry exhaustion, permission-scoped controls, and no ambiguous resend.
 reset()
 for attempt in range(5):
  with app.app_context():core.get_db().execute('UPDATE mail_jobs SET next_at=0 WHERE payload IS NOT NULL');core.get_db().commit()
  check(drain(temporary)==1,'Retry attempt bounded '+str(attempt))
 with app.app_context():j=dict(latest());check(j['state']=='dead' and j['attempts']==5,'Retry budget dead letter')
 check(guest.get('/manage/mail').status_code==403,'Guest denied mail controls');check(client(peer).get('/manage/mail').status_code==403,'Nonstaff denied mail controls')
 page=staff.get('/manage/mail');check(page.status_code==200,'Staff queue view available');check(b'queue@example.com' not in page.data and b'rawtoken' not in page.data,'Staff view redacted');check('no-store' in page.headers['Cache-Control'],'Staff view no-store')
 check(staff.post('/manage/mail',data={'job':j['id'],'action':'retry'}).status_code==400,'Retry CSRF required')
 stale=client(admin,False).post('/manage/mail',data={'theme_csrf_token':csrf,'job':j['id'],'action':'retry'});check(stale.status_code==302 and '/reauth' in stale.location,'Retry requires fresh factors')
 check(staff.post('/manage/mail',data={'theme_csrf_token':csrf,'job':j['id'],'action':'retry'}).status_code==302,'Staff safe retry requested');check(drain()==1,'Staff retry accepted')
 reset()
 def ambiguous(data,jid):raise TimeoutError('DO NOT LOG secret')
 check(drain(ambiguous)==1,'Ambiguous send classified')
 with app.app_context():j=dict(latest());check(j['state']=='uncertain' and j['payload'] is None,'Uncertain job quarantined and wiped');check(not q.staff_retry(app,core.get_db(),j['id']),'Uncertain cannot staff retry')
 check(drain()==0,'Uncertain never repeated')
 reset()
 def permanent(data,jid):raise smtplib.SMTPDataError(550,b'private rejection')
 check(drain(permanent)==1,'Permanent rejection attempted once')
 with app.app_context():check(latest()['state']=='dead' and latest()['payload'] is None,'Permanent failure terminal')
 # Stale account/address/token/cancellation checks.
 for label,mutation,undo in [
 ('expiry',lambda d,j:d.execute('UPDATE mail_jobs SET expires_at=? WHERE id=?',(int(time.time())-1,j['id'])),lambda d:None),
 ('cancelled token',lambda d,j:d.execute('UPDATE password_resets SET used=1 WHERE token_hash=?',(j['token_hash'],)),lambda d:None),
 ('address changed',lambda d,j:d.execute("UPDATE users SET email='moved@example.com' WHERE id=?",(uid,)),lambda d:d.execute("UPDATE users SET email='queue@example.com' WHERE id=?",(uid,))),
 ('staff disabled',lambda d,j:d.execute("INSERT OR REPLACE INTO account_disables(user_id,disabled,reason) VALUES (?,1,'test')",(uid,)),lambda d:d.execute('DELETE FROM account_disables WHERE user_id=?',(uid,))),
 ('deletion requested',lambda d,j:d.execute("INSERT OR REPLACE INTO account_safety(user_id,deletion_requested_at) VALUES (?,CURRENT_TIMESTAMP)",(uid,)),lambda d:d.execute('DELETE FROM account_safety WHERE user_id=?',(uid,)))]:
  with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
  reset();n=len(sent)
  with app.app_context():d=core.get_db();j=dict(latest());mutation(d,j);d.commit()
  drain();check(len(sent)==n,label+' prevents send')
  with app.app_context():d=core.get_db();check(d.execute('SELECT payload FROM mail_jobs WHERE id=?',(j['id'],)).fetchone()[0] is None,label+' clears payload');undo(d);d.commit()
 # Fresh verification, cancellation by verification, URL mount and key rotation.
 with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
 response=guest.post('/verify-email',data={'theme_csrf_token':csrf,'email':'unverified@example.com'},environ_overrides={'SCRIPT_NAME':'/sandbox'});check(response.status_code==200,'Verification queued')
 with app.app_context():
  d=core.get_db();j=dict(latest());value,crypto=q.key(app);data=json.loads(crypto.decrypt(j['payload']));check('/sandbox/verify_email/' in data['body'],'Queue preserves Sandbox link prefix')
  oldcipher=j['payload'];q.rotate(app,d);newvalue,newcrypto=q.key(app);check(newvalue['key']!=value['key'],'Key rotation replaces key');check(newcrypto.decrypt(d.execute('SELECT payload FROM mail_jobs WHERE id=?',(j['id'],)).fetchone()[0]),'Active payload reencrypted')
  try:newcrypto.decrypt(oldcipher);readable=True
  except q.InvalidToken:readable=False
  check(not readable,'Retired-key backup ciphertext unreadable with current key')
 check(drain()==1,'Rotated job sends');link=raw_from_sent().replace('/sandbox','');check(guest.get(link).status_code==200,'Verification accepted then usable')
 # Email changes queue, retain current address, activate at acceptance, and old-address notice.
 with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
 resp=owner.post('/account/email',data={'theme_csrf_token':csrf,'email':'next@example.com'});check(resp.status_code==302,'Email change queued')
 with app.app_context():
  d=core.get_db();j=dict(latest());check(d.execute('SELECT delivered FROM email_changes WHERE token_hash=?',(j['token_hash'],)).fetchone()[0]==0,'Change inactive before acceptance');check(d.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()[0]=='queue@example.com','Current address preserved')
 check(b'Confirmation email queued for' in owner.get('/account/email').data,'Honest owner queued status')
 check(drain()==1,'Change worker accepted');change_link=raw_from_sent();check(owner.get(change_link).status_code==200,'Accepted change confirmation visible')
 response=owner.post(change_link,data={'theme_csrf_token':csrf});check(response.status_code==302,'Accepted change applied')
 with app.app_context():check(latest()['purpose']=='notice' and latest()['state']=='queued','Old-address security notice queued')
 check(drain()==1 and sent[-1][0]['recipient']=='queue@example.com','Notice goes to old address after change')
 # Independent ledger blocks restored queued copies of accepted jobs.
 with app.app_context():
  d=core.get_db();accepted=d.execute("SELECT * FROM mail_jobs WHERE id=?",(first['id'],)).fetchone();d.execute("UPDATE mail_jobs SET state='queued',payload=?,next_at=0 WHERE id=?",(first['payload'],first['id']));d.commit();n=len(sent)
 drain();check(len(sent)==n,'Application DB restore cannot replay accepted job')
 with app.app_context():check(core.get_db().execute('SELECT state FROM mail_jobs WHERE id=?',(first['id'],)).fetchone()[0]=='cancelled','Restored intent cancelled')
 # Expired claim before SMTP can recover, sending lease cannot; lock prevents overlap.
 with app.app_context():
  d=core.get_db();d.execute('DELETE FROM rate_buckets');d.commit();u=d.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()[0]
  raw='lease-only-synthetic';h=cf.digest(raw);d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600));d.commit();m=Message(subject='test',recipients=[u],body='test');q.enqueue(app,d,m,uid,'reset',h);j=dict(latest());d.execute("UPDATE mail_jobs SET state='claimed',lease='old',lease_until=0 WHERE id=?",(j['id'],));d.commit()
 check(drain()==1,'Expired pre-send lease recovers safely')
 with app.app_context():
  d=core.get_db();raw='sending-only-synthetic';h=cf.digest(raw);d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600));d.commit();q.enqueue(app,d,m,uid,'reset',h);j=dict(latest());d.execute("UPDATE mail_jobs SET state='sending',lease='old',lease_until=0 WHERE id=?",(j['id'],));d.commit();n=len(sent)
 drain();check(len(sent)==n,'Interrupted send is not replayed')
 with app.app_context():
  check(latest()['state']=='uncertain','Interrupted send quarantined')
  with q.worker_lock(app) as lock:
   check(lock,'Worker lease owner obtains lock')
   with q.worker_lock(app) as second:check(not second,'Second worker excluded')
  # Exercise the actual SMTP adapter with a fake connection, including stable headers.
  calls=[]
  class Host:
   def sendmail(self,sender,recipients,body):calls.append((sender,recipients,body));return {}
  class Connection:
   host=Host()
   def __enter__(self):return self
   def __exit__(self,*args):return None
  data={'recipient':'smtp@example.com','subject':'Adapter test','body':'Synthetic body','created_at':now}
  with patch.object(core.mail,'connect',return_value=Connection()):
   check(q.transport(core,data,'stable-id') is True,'Actual SMTP adapter acceptance')
   q.transport(core,data,'stable-id')
  check(calls[0][1]==['smtp@example.com'],'Single explicit envelope recipient')
  check(b'Message-ID: <stable-id@mail.neonrest.com>' in calls[0][2],'Stable Message-ID rendered')
  check(calls[0][2]==calls[1][2],'Retry message bytes stable')
  # Lifecycle changes can proceed during SMTP; completion cannot resurrect cancellation.
  d=core.get_db();h=cf.digest('concurrent-cancel');d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600));d.commit();q.enqueue(app,d,m,uid,'reset',h);j=dict(latest())
  def concurrent(data,jid):
   otherdb=sqlite3.connect(dbpath);otherdb.execute('UPDATE password_resets SET used=1 WHERE token_hash=?',(h,));otherdb.commit();otherdb.close();return True
  check(q.run_once(app,core,send=concurrent)==1,'Concurrent cancellation is not blocked by SMTP lock')
  check(d.execute('SELECT used FROM password_resets WHERE token_hash=?',(h,)).fetchone()[0]==1,'In-flight cancellation never reactivated')
  check(latest()['state']=='cancelled' and latest()['payload'] is None,'Cancelled in-flight payload wiped')
  # Retry attempt ledger remains authoritative after an older application-DB restore.
  h=cf.digest('restore-budget');d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600));d.commit();q.enqueue(app,d,m,uid,'reset',h);j=dict(latest())
  for _ in range(5):
   d.execute('UPDATE mail_jobs SET next_at=0 WHERE id=?',(j['id'],));d.commit();q.run_once(app,core,send=temporary)
  d.execute("UPDATE mail_jobs SET state='queued',attempts=0,next_at=0 WHERE id=?",(j['id'],));d.commit();n=len(sent)
  check(q.run_once(app,core,send=fake)==0 and len(sent)==n,'Restore does not replenish retry budget')
  check(latest()['attempts']==5 and latest()['state']=='dead','External attempt count restored')
  check(q.staff_retry(app,d,j['id']),'Staff authorizes one bounded extra attempt');d.commit();check(q.run_once(app,core,send=fake)==1,'Authorized additional attempt completes')
  # Per-account capacity and fail-closed key failures.
  for i in range(10):check(q.enqueue(app,d,m,uid,'notice',dedupe='capacity-'+str(i))=='queued','Account capacity slot '+str(i))
  try:q.enqueue(app,d,m,uid,'notice',dedupe='capacity-overflow');overflow=False
  except RuntimeError:overflow=True
  check(overflow,'Per-account queue capped at ten encrypted payloads')
  with app.test_request_context('/'):
   with patch.object(q,'key',side_effect=OSError('private')):check(q.submit(core,d,m,uid,'notice',dedupe='key-failure') is False,'Missing key fails closed without SMTP fallback')
  q.rotate(app,d,invalidate=True);check(not d.execute('SELECT 1 FROM mail_jobs WHERE payload IS NOT NULL').fetchone(),'Restore invalidation clears intents')
  check(all(not d.execute(f'SELECT 1 FROM {table} WHERE used IN (0,2)').fetchone() for table in q.TABLES.values()),'Restore invalidation also revokes previously usable recovery links')
  # Metadata and independent ledger retention; no recipient or token in ledger.
  ledger=sqlite3.connect(root/'queue'/'attempts.db');columns=[r[1] for r in ledger.execute('PRAGMA table_info(attempts)')];check(columns==['id','state','count','expires_at'],'Replay ledger carries no address/body/token')
  ledger.execute("INSERT INTO attempts VALUES ('expired-ledger','accepted',1,?)",(now-46*86400,));ledger.commit();ledger.close()
  d.execute("INSERT INTO mail_jobs(id,dedupe,user_id,purpose,created_at,expires_at,state,next_at) VALUES ('old-meta','old-meta',?,'notice',0,?,'cancelled',0)",(uid,now-31*86400));d.commit();q.run_once(app,core,send=fake)
  check(not d.execute("SELECT 1 FROM mail_jobs WHERE id='old-meta'").fetchone(),'Job metadata removed after thirty days')
  ledger=sqlite3.connect(root/'queue'/'attempts.db');check(not ledger.execute("SELECT 1 FROM attempts WHERE id='expired-ledger'").fetchone(),'Replay tombstone removed after forty-five days');ledger.close()
  # Erasure integration removes pending encrypted payloads in the isolated database.
  doomed=add('@QueueDisposable','disposable@example.com');h=cf.digest('disposable-queue');d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,doomed,now+3600));d.commit();dm=Message(subject='Test',recipients=['disposable@example.com'],body='Test');q.enqueue(app,d,dm,doomed,'reset',h)
  roots={n:str(root/n) for n in ('avatars','media','consent','backups')}
  for p in roots.values():Path(p).mkdir(exist_ok=True)
  with d:retention.erase_account(d,doomed,roots)
  check(not d.execute('SELECT 1 FROM mail_jobs WHERE user_id=?',(doomed,)).fetchone(),'Account erasure removes queue rows and ciphertext')
  h=cf.digest('daily-expiry');d.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(h,uid,now+3600));d.commit();q.enqueue(app,d,m,uid,'reset',h);j=dict(latest());d.execute('UPDATE mail_jobs SET expires_at=? WHERE id=?',(now-1,j['id']));d.commit()
  preview=retention.run(d,roots,now=now);check(preview['records'].get('mail_payloads')==1,'Daily retention previews expired payload')
  check(latest()['payload'] is not None,'Retention preview never wipes payload')
  retention.run(d,roots,apply=True,now=now);check(latest()['payload'] is None and latest()['state']=='expired','Daily cleanup wipes expired payload if worker is unavailable')
  check(d.execute('SELECT used FROM password_resets WHERE token_hash=?',(h,)).fetchone()[0]==1,'Daily cleanup cancels only expired pending token')
  events=' '.join(r[0] for r in d.execute("SELECT detail FROM operations_events WHERE kind IN ('email','mail-control')"));check('queue@example.com' not in events and 'rawtoken' not in events and 'DO NOT LOG' not in events,'Operations records redacted')
  check(d.execute('PRAGMA quick_check').fetchone()[0]=='ok','Queue DB integrity')
  check(not d.execute('SELECT 1 FROM mail_jobs WHERE payload IS NOT NULL').fetchone(),'CLI verification uses empty synthetic queue')
  cli=subprocess.run([sys.executable,str(stage/'mail_queue.py'),'--once'],cwd='/tmp',env=dict(os.environ),capture_output=True,text=True)
  check(cli.returncode==0,'Worker CLI starts outside application directory')
  check('Sandbox mail worker started' in cli.stdout,'CLI performs empty processing cycle without SMTP')
 check(source.execute('SELECT count(*),sum(verified) FROM users').fetchone()==before,'Live accounts unchanged');source.close()
print('PASS:',checks,'isolated T06-Q queue checks; fake SMTP only')
