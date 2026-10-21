"""Single-use email verification and safe resend flow for Sandbox."""
import secrets,time
from flask import g,request,session,redirect,url_for,render_template,flash,current_app
from flask_mail import Message
from neonrest_sandbox.community_features import digest
from neonrest_sandbox.email_delivery import deliver,finish_token_delivery

def issue_token(db,email,pending=False):
    row=db.execute('SELECT id,email,verified FROM users WHERE email=? COLLATE NOCASE',(email,)).fetchone()
    if not row or row['verified']:
        return None
    raw=secrets.token_urlsafe(32);now=int(time.time())
    if not pending:db.execute('UPDATE email_verifications SET used=1 WHERE user_id=?',(row['id'],))
    db.execute('INSERT INTO email_verifications VALUES (?,?,?,?,?,?)',(digest(raw),row['id'],row['email'],now,now+3600,2 if pending else 0))
    db.commit()
    return raw

def send_verification(core,db,email):
    row=db.execute('SELECT id,email,verified FROM users WHERE email=? COLLATE NOCASE',(email,)).fetchone()
    if not row or row['verified']:
        return True
    recent=db.execute('SELECT 1 FROM email_verifications WHERE user_id=? AND used IN (0,2) AND created_at>? AND expires_at>?',(row['id'],int(time.time())-60,int(time.time()))).fetchone()
    if recent:
        return True
    raw=issue_token(db,email,pending=True)
    if raw is None:return True # Another request may already have verified it.
    msg=Message(subject='Verify your Neonrest email',recipients=[row['email']])
    msg.body='Verify your email within one hour: '+('https://www.neonrest.com'+url_for('verify_email',token=raw,_external=False))+chr(10)+'Use this link once. If you did not create this account, ignore this email.'
    from neonrest_sandbox.mail_queue import submit
    queued=submit(core,db,msg,row['id'],'verification',digest(raw))
    if queued=='queued':return queued
    accepted=deliver(core,msg) if queued is None else False
    finish_token_delivery(db,'email_verifications',digest(raw),accepted)
    return accepted

def register(app,core):
    csrf=app.extensions["community_auth_helpers"]["csrf"]
    limited=app.extensions["community_auth_helpers"]["limited"]
    with app.app_context():
        db=core.get_db()
        db.execute('CREATE TABLE IF NOT EXISTS email_verifications(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,email TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,used INTEGER NOT NULL DEFAULT 0)')
        db.execute('CREATE INDEX IF NOT EXISTS email_verifications_user ON email_verifications(user_id,created_at)');db.commit()
    @app.route('/verify-email',methods=['GET','POST'])
    def verification_request():
        if request.method=='POST':
            csrf()
            blocked=limited('verification-resend',5,900,subject='network:'+str(request.remote_addr))
            if blocked:return blocked
            email=request.form.get('email','').strip()[:254]
            send_verification(core,core.get_db(),email)
            flash('If that account needs verification, we will attempt to email a link. Check your inbox and spam folder. If nothing arrives, wait a minute and try again; a previously received link stays usable if the new send fails.','info')
        return render_template('email_verification.html',state='request')
    def verify_email(token):
        g.statistics_verification_outcome='verification_invalid'
        db=core.get_db();now=int(time.time())
        row=db.execute('SELECT v.*,u.email AS current_email,u.verified FROM email_verifications v JOIN users u ON u.id=v.user_id WHERE token_hash=?',(digest(token),)).fetchone() if len(token)<=128 else None
        if not row or row['used'] or row['expires_at']<=now or row['email']!=row['current_email'] or row['verified']:
            return render_template('email_verification.html',state='invalid'),400
        with db:
            changed=db.execute('UPDATE email_verifications SET used=1 WHERE token_hash=? AND used=0 AND expires_at>?',(digest(token),now))
            if not changed.rowcount:return render_template('email_verification.html',state='invalid'),400
            db.execute('UPDATE users SET verified=1 WHERE id=? AND email=?',(row['user_id'],row['email']))
        g.statistics_verification_outcome='verified'
        return render_template('email_verification.html',state='success')
    app.view_functions['verify_email']=verify_email
    def verified_session():
        uid=session.get('user_id')
        if uid:
            row=core.get_db().execute('SELECT verified FROM users WHERE id=?',(uid,)).fetchone()
            if not row or not row['verified']:
                session.clear()
                if request.endpoint not in ('static','login','verify_email','verification_request','password_reset_request','password_reset','logout'):
                    if request.method=='POST':return render_template('email_verification.html',state='request'),403
                    return redirect(url_for('verification_request'))
    app.before_request_funcs.setdefault(None,[]).insert(0,verified_session)
    @app.after_request
    def private_recovery(response):
        if request.endpoint in ('verify_email','verification_request','password_reset','password_reset_request'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['Referrer-Policy']='same-origin'
        return response
