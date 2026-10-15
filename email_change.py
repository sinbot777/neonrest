"""Verified email changes keep the old login until an owner confirms the new address."""
import secrets
import sqlite3
import time
from email_validator import validate_email, EmailNotValidError
from flask import request, session, abort, redirect, url_for, render_template, flash, current_app
from flask_mail import Message
from neonrest.community_features import digest


def invalidate_changes(db, uid):
    db.execute('UPDATE email_changes SET used=1 WHERE user_id=?', (uid,))


def register(app, core):
    with app.app_context():
        db = core.get_db()
        db.executescript('''CREATE TABLE IF NOT EXISTS email_changes(
            id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL, old_email TEXT NOT NULL, new_email TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            delivered INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS email_changes_user ON email_changes(user_id,id);
            CREATE UNIQUE INDEX IF NOT EXISTS users_email_nocase ON users(email COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS account_lifecycle_events(
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);''')
        db.commit()

    def owner():
        row = core.get_db().execute('SELECT * FROM users WHERE id=?', (session.get('user_id'),)).fetchone()
        if not row or not row['verified']:
            abort(401)
        return row

    def helpers():
        return app.extensions['community_auth_helpers']

    def screen(user, error=None, status=200, confirmation=None):
        pending = core.get_db().execute('''SELECT new_email,expires_at FROM email_changes
            WHERE user_id=? AND used=0 AND expires_at>? ORDER BY id DESC LIMIT 1''',
            (user['id'], int(time.time()))).fetchone()
        return render_template('email_change.html', user=user, pending=pending,
            error=error, confirmation=confirmation, token=core.theme_csrf_token()), status

    @app.route('/account/email', methods=['GET', 'POST'])
    def account_email():
        user = owner(); db = core.get_db(); uid = user['id']
        if request.method == 'GET':
            return screen(user)
        helpers()['csrf']()
        if not helpers()['fresh']():
            return redirect(url_for('community_reauth', next='/account/email'))
        action = request.form.get('action', 'request')
        if action == 'cancel':
            with db:
                invalidate_changes(db, uid)
                db.execute("INSERT INTO account_lifecycle_events(user_id,action) VALUES (?,'email-change-cancelled')", (uid,))
            flash('Pending email change cancelled. Your current address stays active.', 'info')
            return redirect(url_for('account_email'))
        if action != 'request':
            abort(400)
        blocked = helpers()['limited']('email-change', 5, 3600)
        if blocked:
            return blocked
        value = request.form.get('email', '').strip()
        try:
            if len(value) > 254:
                raise EmailNotValidError('Too long')
            email = validate_email(value, check_deliverability=False, allow_smtputf8=False).normalized
        except EmailNotValidError:
            return screen(user, 'Enter a valid email address.', 400)
        if email.lower() == user['email'].lower():
            return screen(user, 'That is already your current address.', 400)
        if db.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE', (email,)).fetchone():
            return screen(user, 'That address cannot be used. Choose another address.', 400)
        raw = secrets.token_urlsafe(32); now = int(time.time())
        changed = db.execute('''INSERT INTO email_changes(token_hash,user_id,old_email,new_email,created_at,expires_at)
            VALUES (?,?,?,?,?,?)''', (digest(raw), uid, user['email'], email, now, now + 3600)).lastrowid
        db.commit()
        msg = Message(subject='Confirm your new Neonrest email', recipients=[email])
        msg.body = ('Sign in to the Neonrest account whose email you are changing, then confirm within one hour: '
            + 'https://www.neonrest.com' + url_for('account_email_confirm', change_token=raw, _external=False)
            + '\nYour old email stays active until you confirm. If you did not request this, ignore this message.')
        from neonrest.mail_queue import submit
        queued=submit(core,db,msg,uid,'change',digest(raw),now+3600)
        if queued=='queued':
            flash('Confirmation email queued. Your current address stays active; check the new inbox shortly.','info')
            return redirect(url_for('account_email'))
        try:
            delivered = core.mail.send(msg) is not False if queued is None else False
        except Exception as exc:
            current_app.logger.warning('Email change delivery failed (%s)', type(exc).__name__)
            delivered = False
        with db:
            if delivered:
                # A slower, older delivery cannot supersede a newer successfully delivered request.
                newer = db.execute('SELECT 1 FROM email_changes WHERE user_id=? AND id>? AND delivered=1', (uid, changed)).fetchone()
                db.execute('UPDATE email_changes SET delivered=1,used=MAX(used,?) WHERE id=?', (int(bool(newer)), changed))
                if not newer and db.execute('SELECT used FROM email_changes WHERE id=?',(changed,)).fetchone()[0] == 0:
                    db.execute('UPDATE email_changes SET used=1 WHERE user_id=? AND id<?', (uid, changed))
            else:
                db.execute('UPDATE email_changes SET used=1 WHERE id=?', (changed,))
        if not delivered:
            return screen(user, 'We could not send the confirmation email. Your current address is unchanged. Try again later.', 503)
        flash('Check your new inbox. Your current email stays active until you confirm the change.', 'info')
        return redirect(url_for('account_email'))

    @app.route('/account/email/confirm/<change_token>', methods=['GET', 'POST'])
    def account_email_confirm(change_token):
        user = owner(); db = core.get_db(); now = int(time.time())
        row = db.execute('''SELECT * FROM email_changes WHERE token_hash=? AND user_id=?
            AND delivered=1 AND used=0 AND expires_at>? AND old_email=?''',
            (digest(change_token), user['id'], now, user['email'])).fetchone() if len(change_token) <= 128 else None
        if not row:
            return screen(user, 'This confirmation link is expired or no longer valid. Request a new change.', 400)
        if request.method == 'GET':
            return screen(user, confirmation=row['new_email'])
        helpers()['csrf']()
        if not helpers()['fresh']():
            return redirect(url_for('community_reauth', next=request.path))
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND id<>?', (row['new_email'], user['id'])).fetchone():
                    return screen(user, 'That address cannot be used. Request another change.', 409)
                claimed = db.execute('''UPDATE email_changes SET used=1 WHERE id=? AND used=0
                    AND delivered=1 AND expires_at>?''', (row['id'], int(time.time())))
                if not claimed.rowcount:
                    return screen(user, 'This confirmation link has already been used.', 400)
                saved = db.execute('UPDATE users SET email=? WHERE id=? AND email=? AND verified=1',
                    (row['new_email'], user['id'], row['old_email']))
                if not saved.rowcount:
                    raise sqlite3.IntegrityError('Account changed while confirming')
                invalidate_changes(db, user['id'])
                db.execute('UPDATE password_resets SET used=1 WHERE user_id=?', (user['id'],))
                db.execute('UPDATE email_verifications SET used=1 WHERE user_id=?', (user['id'],))
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?', (user['id'],))
                db.execute("INSERT INTO account_lifecycle_events(user_id,action) VALUES (?,'email-changed')", (user['id'],))
        except sqlite3.IntegrityError:
            return screen(user, 'The change could not be completed. Request another confirmation.', 409)
        notice = Message(subject='Your Neonrest account email changed', recipients=[row['old_email']])
        notice.body = ('Your Neonrest sign-in email was changed and all sessions were signed out. '
            'If this was not you, contact ToS@neonrest.com. No password or verification code is included in this notice.')
        try:
            from neonrest.mail_queue import submit
            queued=submit(core,db,notice,user['id'],'notice',dedupe='email-change-notice:'+str(row['id']))
            if queued is None:core.mail.send(notice)
        except Exception as exc:
            current_app.logger.warning('Email change notice delivery failed (%s)', type(exc).__name__)
        session.clear()
        flash('Email changed. Sign in with your new address; two-factor authentication still applies.', 'success')
        return redirect(url_for('login'))

    @app.after_request
    def private_email_change(response):
        if request.endpoint in ('account_email', 'account_email_confirm'):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Referrer-Policy'] = 'same-origin'
        return response
