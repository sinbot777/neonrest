"""Durable, encrypted, single-recipient account mail. No payloads in staff views/logs."""
import argparse,contextlib,fcntl,json,os,secrets,sqlite3,time
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from cryptography.fernet import Fernet,InvalidToken
from flask import current_app,request,redirect,url_for,render_template,flash,abort
from flask_mail import Message
from neonrest.email_delivery import retryable

ACTIVE=('queued','retry','claimed','sending','dead')
TABLES={'verification':'email_verifications','reset':'password_resets','change':'email_changes'}
BACKOFF=(30,120,480,900)
QUEUED='queued'

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS mail_jobs(
        id TEXT PRIMARY KEY,dedupe TEXT UNIQUE NOT NULL,user_id INTEGER NOT NULL,
        purpose TEXT NOT NULL,token_hash TEXT,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
        state TEXT NOT NULL,payload BLOB,attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 5,
        next_at INTEGER NOT NULL,lease TEXT,lease_until INTEGER,last_error TEXT);
        CREATE INDEX IF NOT EXISTS mail_jobs_due ON mail_jobs(state,next_at);
        CREATE INDEX IF NOT EXISTS mail_jobs_owner ON mail_jobs(user_id,purpose);
        CREATE TABLE IF NOT EXISTS mail_worker_health(id INTEGER PRIMARY KEY CHECK(id=1),heartbeat INTEGER NOT NULL);''')
    if 'max_attempts' not in {r[1] for r in db.execute('PRAGMA table_info(mail_jobs)')}:db.execute('ALTER TABLE mail_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5')
    db.commit()

def root(app):
    return Path(app.config['MAIL_QUEUE_PRIVATE_DIR'])

def key(app):
    p=root(app)/'key.json'
    if p.is_symlink() or p.stat().st_mode & 0o077:raise RuntimeError('Unsafe mail key permissions')
    value=json.loads(p.read_text())
    return value,Fernet(value['key'].encode())

def provision(app,allow_empty_ledger=False):
    p=root(app);p.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.is_symlink() or p.stat().st_mode & 0o077:raise RuntimeError('Unsafe mail directory permissions')
    if not (p/'key.json').exists():
        value={'key':Fernet.generate_key().decode(),'epoch':secrets.token_hex(16),'rotated_at':int(time.time())}
        fd=os.open(p/'key.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
    key(app)
    if not allow_empty_ledger and not (p/'attempts.db').exists() and app.extensions['mail_queue_core'].get_db().execute('SELECT 1 FROM mail_jobs LIMIT 1').fetchone():raise RuntimeError('Missing replay ledger; invalidate restored jobs before provisioning')
    ledger=sqlite3.connect(p/'attempts.db');os.chmod(p/'attempts.db',0o600)
    ledger.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,state TEXT NOT NULL,count INTEGER NOT NULL,expires_at INTEGER NOT NULL)');ledger.commit();ledger.close()

@contextlib.contextmanager
def worker_lock(app):
    p=root(app)/'worker.lock'
    fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:yield False
        else:yield True
    finally:os.close(fd)

def cancel_token(db,job):
    table=TABLES.get(job['purpose'])
    if table=='email_changes':db.execute('UPDATE email_changes SET used=1 WHERE token_hash=? AND delivered=0',(job['token_hash'],))
    elif table:db.execute(f'UPDATE {table} SET used=1 WHERE token_hash=? AND used=2',(job['token_hash'],))

def terminal(db,job,state,error=None):
    if state!='accepted':cancel_token(db,job)
    db.execute('UPDATE mail_jobs SET state=?,payload=NULL,lease=NULL,lease_until=NULL,last_error=? WHERE id=?',(state,error,job['id']))

def eligible(db,job,payload,now):
    user=db.execute('SELECT * FROM users WHERE id=?',(job['user_id'],)).fetchone()
    if not user or job['expires_at']<=now:return False
    if db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1 UNION SELECT 1 FROM reserved_accounts WHERE user_id=? AND disabled=1',(job['user_id'],job['user_id'])).fetchone():return False
    safety=db.execute('SELECT deletion_requested_at FROM account_safety WHERE user_id=?',(job['user_id'],)).fetchone()
    if safety and safety['deletion_requested_at']:return False
    # Deactivated/banned owners still need recovery; staff-disabled/deleting owners do not.
    if user['email']!=payload['expected_email']:return False
    table=TABLES.get(job['purpose'])
    if not table:return job['purpose']=='notice' and user['verified']
    row=db.execute(f'SELECT rowid AS sequence,* FROM {table} WHERE token_hash=? AND user_id=?',(job['token_hash'],job['user_id'])).fetchone()
    if not row or row['expires_at']<=now:return False
    if table=='email_changes':
        return not row['used'] and not row['delivered'] and user['verified'] and row['old_email']==user['email'] and row['new_email']==payload['recipient'] and not db.execute('SELECT 1 FROM email_changes WHERE user_id=? AND id>? AND delivered=1',(job['user_id'],row['id'])).fetchone() and not db.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND id<>?',(row['new_email'],job['user_id'])).fetchone()
    if row['used']!=2:return False
    if table=='email_verifications' and (user['verified'] or row['email']!=user['email']):return False
    if table=='password_resets' and not user['verified']:return False
    return not db.execute(f'SELECT 1 FROM {table} WHERE user_id=? AND rowid>? AND used=0',(job['user_id'],row['sequence'])).fetchone()

def finalize(db,job):
    table=TABLES.get(job['purpose'])
    if table=='email_changes':
        row=db.execute('SELECT id FROM email_changes WHERE token_hash=? AND used=0 AND delivered=0',(job['token_hash'],)).fetchone()
        if row:
            db.execute('UPDATE email_changes SET delivered=1 WHERE id=?',(row['id'],))
            db.execute('UPDATE email_changes SET used=1 WHERE user_id=? AND id<?',(job['user_id'],row['id']))
    elif table:
        row=db.execute(f'SELECT rowid FROM {table} WHERE token_hash=? AND used=2',(job['token_hash'],)).fetchone()
        if row:
            db.execute(f'UPDATE {table} SET used=0 WHERE token_hash=?',(job['token_hash'],))
            db.execute(f'UPDATE {table} SET used=1 WHERE user_id=? AND rowid<?',(job['user_id'],row[0]))

def enqueue(app,db,message,uid,purpose,token_hash=None,expires_at=None,dedupe=None):
    if purpose not in (*TABLES,'notice') or len(message.recipients)!=1:raise ValueError('Unsupported mail intent')
    now=int(time.time());expires_at=min(expires_at or now+3600,now+3600)
    dedupe=dedupe or purpose+':'+str(token_hash)
    prior=db.execute('SELECT state FROM mail_jobs WHERE dedupe=?',(dedupe,)).fetchone()
    if prior:return QUEUED if prior['state'] in ACTIVE else False
    value,crypto=key(app); user=db.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()
    if not user:return False
    payload={'recipient':message.recipients[0],'subject':message.subject,'body':message.body,'expected_email':user['email'],'epoch':value['epoch'],'created_at':now}
    serialized=json.dumps(payload).encode()
    if len(serialized)>16384:raise ValueError('Mail payload too large')
    jid=secrets.token_hex(16)
    db.execute('BEGIN IMMEDIATE')
    try:
        value,crypto=key(app);payload['epoch']=value['epoch'];serialized=json.dumps(payload).encode()
        table=TABLES.get(purpose)
        token=db.execute(f'SELECT expires_at FROM {table} WHERE token_hash=?',(token_hash,)).fetchone() if table else None
        if token:expires_at=min(expires_at,token['expires_at'])
        if db.execute('SELECT count(*) FROM mail_jobs WHERE payload IS NOT NULL').fetchone()[0]>=1000:raise RuntimeError('Mail queue capacity reached')
        if db.execute('SELECT count(*) FROM mail_jobs WHERE user_id=? AND payload IS NOT NULL',(uid,)).fetchone()[0]>=10:raise RuntimeError('Account mail capacity reached')
        job={'user_id':uid,'purpose':purpose,'token_hash':token_hash,'expires_at':expires_at}
        if not eligible(db,job,payload,now):db.rollback();return False
        db.execute('INSERT INTO mail_jobs(id,dedupe,user_id,purpose,token_hash,created_at,expires_at,state,payload,next_at) VALUES (?,?,?,?,?,?,?,\'queued\',?,?)',(jid,dedupe,uid,purpose,token_hash,now,expires_at,crypto.encrypt(serialized),now))
        db.commit();return QUEUED
    except Exception:db.rollback();raise

def submit(core,db,message,uid,purpose,token_hash=None,expires_at=None,dedupe=None):
    app=current_app._get_current_object()
    if not app.config.get('MAIL_QUEUE_ENABLED'):return None
    try:return enqueue(app,db,message,uid,purpose,token_hash,expires_at,dedupe)
    except (OSError,ValueError,RuntimeError,sqlite3.Error):
        app.logger.warning('Account email could not be queued')
        return False

def transport(core,payload,jid):
    # Direct single send with the installed verified, bounded connection. No internal retries,
    # post-acceptance signals or max-emails QUIT can obscure the DATA acceptance boundary.
    from flask_mail import sanitize_address
    msg=Message(subject=payload['subject'],recipients=[payload['recipient']],body=payload['body'])
    msg.msgId='<'+jid+'@mail.neonrest.com>'
    msg.date=payload['created_at']
    if not msg.sender or msg.has_bad_headers():raise ValueError('Invalid mail headers')
    with core.mail.connect() as connection:
        if connection.host is None:raise RuntimeError('SMTP delivery is suppressed')
        rejected=connection.host.sendmail(sanitize_address(msg.sender),[sanitize_address(payload['recipient'])],msg.as_bytes())
        if rejected:raise RuntimeError('Recipient not accepted')
    return True

def rotate(app,db,invalidate=False):
    old,crypto=key(app);new={'key':Fernet.generate_key().decode(),'epoch':secrets.token_hex(16),'rotated_at':int(time.time())};fresh=Fernet(new['key'].encode())
    db.execute('BEGIN IMMEDIATE')
    try:
        for job in db.execute('SELECT * FROM mail_jobs WHERE payload IS NOT NULL').fetchall():
            if invalidate:terminal(db,job,'cancelled','RestoreInvalidated');continue
            try:
                data=json.loads(crypto.decrypt(job['payload'],ttl=3600));data['epoch']=new['epoch']
                db.execute('UPDATE mail_jobs SET payload=? WHERE id=?',(fresh.encrypt(json.dumps(data).encode()),job['id']))
            except (InvalidToken,ValueError):terminal(db,job,'cancelled','KeyRotationExpired')
        if invalidate:
            # A restored usable/consumed token must not become reusable outside the queue.
            for table in TABLES.values():db.execute(f'UPDATE {table} SET used=1 WHERE used IN (0,2)')
        p=root(app)/'key.new';fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump(new,f);f.flush();os.fsync(f.fileno())
        os.replace(p,root(app)/'key.json');db.commit()
    except Exception:db.rollback();raise

def run_once(app,core,send=None,limit=20):
    db=core.get_db();value,crypto=key(app);now=int(time.time())
    ledger=sqlite3.connect(root(app)/'attempts.db');ledger.row_factory=sqlite3.Row
    try:
        # The independent ledger survives application-DB restores. A send with no definitive
        # completion is quarantined, even if a restored DB calls it queued again.
        for job in db.execute('SELECT * FROM mail_jobs WHERE payload IS NOT NULL OR state IN (\'claimed\',\'sending\')').fetchall():
            previous=ledger.execute('SELECT * FROM attempts WHERE id=?',(job['id'],)).fetchone()
            with db:
                if previous and previous['state'] not in ('retry',):terminal(db,job,'uncertain' if previous['state']=='sending' else 'cancelled','ReplayPrevented')
                elif job['state']=='sending':terminal(db,job,'uncertain','LeaseUncertain')
                elif job['expires_at']<=now:terminal(db,job,'expired')
                elif job['state']=='claimed' and job['lease_until']<=now:db.execute("UPDATE mail_jobs SET state='queued',lease=NULL,lease_until=NULL WHERE id=?",(job['id'],))
                elif job['payload'] and job['state']!='claimed':
                    try:
                        data=json.loads(crypto.decrypt(job['payload'],ttl=3600))
                        if data['epoch']!=value['epoch'] or not eligible(db,job,data,now):terminal(db,job,'cancelled','StaleIntent')
                    except (InvalidToken,ValueError):terminal(db,job,'cancelled','PayloadInvalid')
        with db:
            db.execute('DELETE FROM mail_jobs WHERE payload IS NULL AND expires_at<?',(now-30*86400,))
            db.execute('INSERT OR REPLACE INTO mail_worker_health VALUES (1,?)',(now,))
        ledger.execute('DELETE FROM attempts WHERE expires_at<?',(now-45*86400,));ledger.commit()
        if now-value['rotated_at']>=30*86400:
            rotate(app,db);value,crypto=key(app)
        done=0
        for _ in range(limit):
            now=int(time.time());lease=secrets.token_hex(16)
            db.execute('BEGIN IMMEDIATE')
            job=db.execute("SELECT * FROM mail_jobs WHERE state IN ('queued','retry') AND next_at<=? AND payload IS NOT NULL ORDER BY created_at,id LIMIT 1",(now,)).fetchone()
            if not job:db.commit();break
            db.execute("UPDATE mail_jobs SET state='claimed',lease=?,lease_until=? WHERE id=?",(lease,now+300,job['id']));db.commit()
            try:
                payload=json.loads(crypto.decrypt(job['payload'],ttl=3600))
            except (InvalidToken,ValueError):
                with db:terminal(db,job,'cancelled','PayloadInvalid')
                continue
            db.execute('BEGIN IMMEDIATE')
            if payload['epoch']!=value['epoch'] or not eligible(db,job,payload,int(time.time())):
                terminal(db,job,'cancelled','StaleIntent');db.commit();continue
            # Persist the send boundary before SMTP. An interrupted worker never replays it.
            db.execute("UPDATE mail_jobs SET state='sending' WHERE id=? AND lease=?",(job['id'],lease));db.commit()
            db.execute('BEGIN IMMEDIATE')
            if not eligible(db,job,payload,int(time.time())):
                terminal(db,job,'cancelled','StaleIntent');db.commit();continue
            previous=ledger.execute('SELECT count FROM attempts WHERE id=?',(job['id'],)).fetchone()
            attempt=max(job['attempts'],previous[0] if previous else 0)+1
            if attempt>min(job['max_attempts'],8):
                db.execute("UPDATE mail_jobs SET state='dead',attempts=?,lease=NULL,lease_until=NULL,last_error='RetryBudget' WHERE id=?",(attempt-1,job['id']));db.commit();continue
            ledger.execute('INSERT OR REPLACE INTO attempts VALUES (?,\'sending\',?,?)',(job['id'],attempt,job['expires_at']));ledger.commit()
            db.execute('UPDATE mail_jobs SET attempts=? WHERE id=?',(attempt,job['id']))
            db.commit() # Never hold the application's SQLite write lock over network I/O.
            try:
                result=(send or (lambda data,jid:transport(core,data,jid)))(payload,job['id'])
                if result is False:raise ValueError('Delivery rejected')
                db.execute('BEGIN IMMEDIATE')
                if not eligible(db,job,payload,int(time.time())):
                    terminal(db,job,'cancelled','ExpiredDuringSend');state='accepted'
                else:finalize(db,job);terminal(db,job,'accepted');state='accepted'
            except Exception as exc:
                if not db.in_transaction:db.execute('BEGIN IMMEDIATE')
                error=type(exc).__name__
                if retryable(exc):
                    state='retry' if attempt<min(job['max_attempts'],8) else 'dead'
                    db.execute('UPDATE mail_jobs SET state=?,next_at=?,lease=NULL,lease_until=NULL,last_error=? WHERE id=?',(state,int(time.time())+BACKOFF[min(attempt-1,3)],error,job['id']))
                else:
                    # Explicit 5xx/known pre-send failures are terminal; ambiguous I/O is uncertain.
                    state='dead' if isinstance(exc,ValueError) or getattr(exc,'smtp_code',0)>=500 else 'uncertain'
                    terminal(db,job,state,error)
            ledger.execute('UPDATE attempts SET state=? WHERE id=?',(state,job['id']))
            # Only known 4xx jobs retaining a payload can be retried by a future lease.
            live=db.execute('SELECT payload FROM mail_jobs WHERE id=?',(job['id'],)).fetchone()
            if state in ('retry','dead') and live['payload'] is not None:ledger.execute("UPDATE attempts SET state='retry' WHERE id=?",(job['id'],))
            ledger.commit()
            db.execute("INSERT INTO operations_events(kind,detail) VALUES ('email',?)",(f'Account email {state}; job={job["id"]}; attempts={attempt}',))
            db.commit();done+=1
        return done
    finally:
        db.rollback();ledger.close()

def staff_retry(app,db,jid):
    job=db.execute('SELECT * FROM mail_jobs WHERE id=?',(jid,)).fetchone()
    if not job or job['state'] not in ('retry','dead') or not job['payload'] or job['attempts']>=8:return False
    value,crypto=key(app)
    try:data=json.loads(crypto.decrypt(job['payload'],ttl=3600))
    except (InvalidToken,ValueError):return False
    if data['epoch']!=value['epoch'] or not eligible(db,job,data,int(time.time())):return False
    db.execute("UPDATE mail_jobs SET state='retry',next_at=?,max_attempts=? WHERE id=? AND state IN ('retry','dead')",(int(time.time()),min(job['attempts']+1,8),jid));return True

def register(app,core):
    app.extensions['mail_queue_core']=core
    app.config.setdefault('MAIL_QUEUE_ENABLED',os.environ.get('NEONREST_PRODUCTION_MAIL_QUEUE','1')=='1')
    app.config.setdefault('MAIL_QUEUE_PRIVATE_DIR',os.environ.get('NEONREST_PRODUCTION_MAIL_QUEUE_DIR','/home/sinbot/private/neonrest_production/mail_queue'))
    app.jinja_env.globals['mail_time']=lambda stamp:time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(stamp))
    with app.app_context():initialize(core.get_db())
    @app.route('/manage/mail',methods=['GET','POST'])
    def mail_queue_staff():
        core.require_staff_permission('manage_roles');db=core.get_db()
        if request.method=='POST':
            app.extensions['community_auth_helpers']['csrf']()
            if not app.extensions['privileged_fresh']():return redirect(url_for('community_reauth',next='/manage/mail'))
            jid=request.form.get('job','');action=request.form.get('action')
            if len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):abort(400)
            if action=='retry':
                with db:ok=staff_retry(app,db,jid)
                flash('Retry requested.' if ok else 'This job cannot be retried; request a new link if needed.','info')
            elif action=='cancel':
                with db:
                    job=db.execute('SELECT * FROM mail_jobs WHERE id=?',(jid,)).fetchone()
                    if job and job['state'] in ('queued','retry','dead'):terminal(db,job,'cancelled','StaffCancelled')
            else:abort(400)
            with db:db.execute("INSERT INTO operations_events(kind,detail) VALUES ('mail-control',?)",(action+'; job='+jid[:32],))
            return redirect(url_for('mail_queue_staff'))
        jobs=db.execute('SELECT id,purpose,state,attempts,created_at,expires_at,next_at,last_error,payload IS NOT NULL AS retry_available FROM mail_jobs ORDER BY created_at DESC LIMIT 100').fetchall()
        counts={r['state']:r['n'] for r in db.execute('SELECT state,count(*) AS n FROM mail_jobs GROUP BY state')}
        heartbeat=db.execute('SELECT heartbeat FROM mail_worker_health WHERE id=1').fetchone()
        response=current_app.make_response(render_template('mail_queue.html',jobs=jobs,counts=counts,healthy=bool(heartbeat and heartbeat[0]>time.time()-120),enabled=app.config['MAIL_QUEUE_ENABLED']))
        response.headers['Cache-Control']='private, no-store';return response

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--provision',action='store_true');parser.add_argument('--rotate-key',action='store_true');parser.add_argument('--invalidate-restored',action='store_true');args=parser.parse_args()
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from neonrest import app as core
    app=core.app
    with app.app_context():
        if args.provision:provision(app);print('Mail queue private state provisioned');return
        with worker_lock(app) as acquired:
            if not acquired:print('Mail worker already running');return
            if args.rotate_key or args.invalidate_restored:
                rotate(app,core.get_db(),invalidate=args.invalidate_restored)
                if args.invalidate_restored:provision(app,allow_empty_ledger=True)
                print('Mail key rotated; restore intents invalidated' if args.invalidate_restored else 'Mail key rotated');return
            if not app.config.get('MAIL_QUEUE_ENABLED'):raise RuntimeError('Mail queue is disabled')
            print('Production mail worker started',flush=True)
            while True:
                try:run_once(app,core)
                except Exception as exc:
                    core.get_db().rollback();app.logger.warning('Mail worker cycle failed (%s)',type(exc).__name__)
                    if args.once:raise
                if args.once:return
                time.sleep(5)

if __name__=='__main__':main()
