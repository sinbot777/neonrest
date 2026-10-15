"""Invite-only evidence intake; no account, disclosure grant or automatic erasure."""
import hashlib
import io
import os
import re
import secrets
import time
from pathlib import Path
from flask import abort, request, session, render_template, url_for, send_file
from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from neonrest_sandbox import privacy_workflows as privacy

DAY = 86400
DOCUMENT_DAYS = 30
REQUEST_RECORD_DAYS = 90
BACKUP_DAYS = 30
OPEN = ('pending', 'pending-verification', 'access-approved')


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS privacy_upload_invites(
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL,
      created_by INTEGER NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
      used_at INTEGER, revoked_at INTEGER, instructions TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS privacy_submission_documents(
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, storage_key TEXT UNIQUE NOT NULL,
      media_type TEXT NOT NULL, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
      created_at INTEGER NOT NULL, reviewed_at INTEGER, reviewed_by INTEGER, review_reference TEXT,
      purge_started_at INTEGER, purged_at INTEGER);
    CREATE INDEX IF NOT EXISTS privacy_submission_request ON privacy_submission_documents(request_id);
    ''')
    db.commit()


def roots(app):
    environment = 'neonrest_production' if __package__ == 'neonrest' else __package__
    base = Path(app.config.get('PRIVACY_SUBMISSIONS_FOLDER', str(Path('/home/sinbot/private') / environment / 'privacy_submissions')))
    return base, base / 'receipts'


def private_folder(path):
    if path.is_symlink(): raise ValueError('Private storage must not be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)



def document_cipher(app, create=False):
    base,_=roots(app);private_folder(base)
    keypath=base.parent/(base.name+'.key')
    if keypath.is_symlink():raise ValueError('Invalid key storage')
    if create and not keypath.exists():
        if any(base.glob('*.pdf')) or any(base.glob('*.jpg')):raise ValueError('Restore the existing document key before receiving more evidence')
        try:
            fd=os.open(keypath,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(Fernet.generate_key());out.flush();os.fsync(out.fileno())
        except FileExistsError:pass
    keypath.chmod(0o600)
    return Fernet(keypath.read_bytes())


def receipt(app, digest):
    if not re.fullmatch('[0-9a-f]{64}', digest): raise ValueError('Invalid receipt key')
    base, ledger = roots(app)
    private_folder(base); private_folder(ledger)
    return ledger / digest


def consume(app, digest):
    """Independent receipt survives restoring an older database; failures burn the invite."""
    fd = os.open(receipt(app, digest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(str(int(time.time()))); out.flush(); os.fsync(out.fileno())


def invalidate_invites(app, db, rid=None):
    rows = db.execute('SELECT token_hash FROM privacy_upload_invites WHERE revoked_at IS NULL' +
                      (' AND request_id=?' if rid is not None else ''), () if rid is None else (rid,)).fetchall()
    for row in rows:
        try: consume(app, row[0])
        except FileExistsError: pass
    db.execute('UPDATE privacy_upload_invites SET revoked_at=? WHERE revoked_at IS NULL' +
               (' AND request_id=?' if rid is not None else ''),
               (int(time.time()),) if rid is None else (int(time.time()), rid))


def decode_upload(data):
    if not data or len(data) > 5 * 1024 * 1024: raise ValueError('Choose a file no larger than 5 MiB.')
    if data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:]:
        return data, 'application/pdf', '.pdf'
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 25000000:
                raise ValueError()
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            out = io.BytesIO(); image.convert('RGB').save(out, format='JPEG')
        clean = out.getvalue()
        if len(clean) > 5 * 1024 * 1024: raise ValueError()
        return clean, 'image/jpeg', '.jpg'
    except Exception:
        raise ValueError('Choose a valid PDF, PNG or JPEG no larger than 5 MiB.')


def document_path(app, key):
    if not re.fullmatch(r'[0-9a-f]{48}\.(pdf|jpg)', key): raise ValueError('Invalid document key')
    base, _ = roots(app); path = base / key
    if base.is_symlink() or path.is_symlink(): raise ValueError('Invalid private storage')
    return path


def purge_deadline(db, row):
    """30 days after final resolution/review/hold release; open requests fail closed."""
    req = db.execute('SELECT * FROM family_data_requests WHERE id=?', (row['request_id'],)).fetchone()
    if not req or req['status'] not in ('closed', 'declined') or not row['reviewed_at']:
        return None
    if req['appealed_at'] and not req['appeal_reviewed_at']: return None
    ids = [uid for uid in (req['parent_id'], req['child_id']) if uid]
    if any(privacy.blockers(db, uid) for uid in ids): return None
    dates = [row['reviewed_at'], req['responded_at'] or 0, req['appeal_reviewed_at'] or 0]
    dates.append(db.execute("SELECT COALESCE(CAST(strftime('%s',?) AS INTEGER),0)",
                            (req['reviewed_at'] or req['created_at'],)).fetchone()[0])
    for uid in ids:
        dates.append(db.execute('SELECT COALESCE(MAX(released_at),0) FROM privacy_holds WHERE user_id=?', (uid,)).fetchone()[0])
    return max(dates) + DOCUMENT_DAYS * DAY



def restore_preflight(app, db):
    """Sanitize an offline restored copy; current decisions must first be reconciled."""
    invalidate_invites(app, db)
    ts=privacy.table_columns(db)
    db.execute("UPDATE family_data_requests SET status=CASE WHEN status='access-approved' THEN 'pending-verification' ELSE status END,approved_payload=NULL,payload_sha256=NULL,authority_version=NULL,expires_at=NULL")
    if 'active_sessions' in ts:db.execute('UPDATE active_sessions SET revoked=1')
    for table in ('email_verifications','password_resets','email_changes'):
        if 'used' in ts.get(table,set()):db.execute('UPDATE '+table+' SET used=1')
    privacy.event(db,None,0,'restore-preflight','Restored invitations, export grants, sessions and recovery tokens invalidated; operator must reconcile current decisions and private files before promotion.')
    db.commit()


def register(app, core):
    with app.app_context(): initialize(core.get_db())
    import click
    @app.cli.command('privacy-restore-preflight')
    @click.option('--restored-database',required=True,type=click.Path(exists=True,dir_okay=False))
    @click.option('--decisions-reconciled',is_flag=True,required=True)
    @click.option('--files-checked',is_flag=True,required=True)
    def restored_copy_preflight(restored_database,decisions_reconciled,files_checked):
        """Invalidate grants in an OFFLINE restored copy, never the configured live DB."""
        import sqlite3
        target=Path(restored_database).resolve()
        if target==Path(app.config['DATABASE']).resolve() or not decisions_reconciled or not files_checked:
            raise click.ClickException('Use an offline copy; reconcile current holds/deletions and check private files first.')
        db=sqlite3.connect(target);db.row_factory=sqlite3.Row
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise click.ClickException('Restored database integrity check failed.')
            privacy.initialize(db);initialize(db);restore_preflight(app,db)
        finally:db.close()
        click.echo('Offline copy sanitized. Keep it offline until final restore review and promotion. No live database was changed.')
    def staff():
        actor = core.require_staff_permission('manage_roles')
        if not app.extensions['community_auth_helpers']['fresh'](): abort(403)
        return actor
    def csrf(): app.extensions['community_auth_helpers']['csrf']()
    def text(name, limit=2000):
        value = request.form.get(name, '').strip()
        if not value or len(value) > limit: abort(400)
        return value

    @app.route('/manage/privacy/submissions', methods=['GET', 'POST'])
    def privacy_submissions():
        actor = staff(); db = core.get_db(); link = None; now = int(time.time())
        if request.method == 'POST':
            csrf(); action = request.form.get('action')
            if action in ('invite', 'revoke'):
                rid = request.form.get('request_id', type=int)
                req = db.execute('SELECT * FROM family_data_requests WHERE id=?', (rid,)).fetchone()
                if not req: abort(404)
                if action == 'invite' and req['status'] not in OPEN: abort(409)
                instructions = text('instructions') if action == 'invite' else ''
                if action=='invite' and db.execute('SELECT count(*) FROM privacy_submission_documents WHERE request_id=? AND purged_at IS NULL',(rid,)).fetchone()[0]>=10:abort(409,description='Review existing documents before requesting more.')
                with db:
                    invalidate_invites(app, db, rid)
                    if action == 'invite':
                        raw = secrets.token_urlsafe(32); digest = hashlib.sha256(raw.encode()).hexdigest()
                        db.execute('INSERT INTO privacy_upload_invites(request_id,token_hash,created_by,created_at,expires_at,instructions) VALUES (?,?,?,?,?,?)',
                                   (rid, digest, actor, now, now + DAY, instructions))
                        link = url_for('privacy_submission_upload', _external=True, _scheme='https') + '#' + raw
                    privacy.event(db, rid, actor, 'upload-invite-' + action, 'One-file, 24-hour upload only; no email sent.')
            elif action == 'review-document':
                row = db.execute('SELECT * FROM privacy_submission_documents WHERE id=? AND purged_at IS NULL', (request.form.get('document_id', type=int),)).fetchone()
                if not row: abort(404)
                reference = text('reference', 500)
                with db:
                    db.execute('UPDATE privacy_submission_documents SET reviewed_at=?,reviewed_by=?,review_reference=? WHERE id=?', (now, actor, reference, row['id']))
                    privacy.event(db, row['request_id'], actor, 'submission-reviewed', 'Document #' + str(row['id']) + ': ' + reference)
            elif action == 'purge-document':
                did = request.form.get('document_id', type=int)
                if request.form.get('confirmation') != 'DELETE DOCUMENT ' + str(did): abort(400)
                # Durable intent before unlink; then recheck holds under the write lock.
                row = db.execute('SELECT * FROM privacy_submission_documents WHERE id=? AND purged_at IS NULL', (did,)).fetchone()
                due = purge_deadline(db, row) if row else None
                if due is None or due > now: abort(409, description='Document is not eligible; finish review, resolution and retention, and check holds.')
                db.execute('UPDATE privacy_submission_documents SET purge_started_at=? WHERE id=?', (now, did))
                privacy.event(db, row['request_id'], actor, 'document-purge-requested', 'Document #' + str(did)); db.commit()
                try:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT * FROM privacy_submission_documents WHERE id=? AND purged_at IS NULL', (did,)).fetchone()
                    due = purge_deadline(db, row) if row else None
                    if due is None or due > int(time.time()): abort(409)
                    document_path(app, row['storage_key']).unlink(missing_ok=True)
                    db.execute('UPDATE privacy_submission_documents SET purged_at=?,purge_started_at=NULL WHERE id=?', (now, did))
                    privacy.event(db, row['request_id'], actor, 'document-purged', 'Document #' + str(did)); db.commit()
                except Exception:
                    db.rollback(); raise
            else: abort(400)
        requests = db.execute('SELECT id,kind,status FROM family_data_requests ORDER BY id DESC').fetchall()
        docs = [dict(row, eligible_after=purge_deadline(db, row) if not row['purged_at'] else None)
                for row in db.execute('SELECT * FROM privacy_submission_documents ORDER BY id DESC')]
        return render_template('privacy_submissions.html', records=requests, documents=docs, invite_link=link,
                               token=core.theme_csrf_token(), now=now, invite_instructions=instructions if link else None)

    @app.route('/privacy/submit', methods=['GET', 'POST'])
    def privacy_submission_upload():
        message = None; nonce = secrets.token_urlsafe(24)
        if request.method == 'POST':
            if request.content_length is None or request.content_length > 6 * 1024 * 1024: abort(413)
            if request.headers.get('Origin') != request.host_url.rstrip('/'): abort(403)
            csrf()
            response = app.extensions['community_auth_helpers']['limited']('privacy-upload', 10, 3600, subject='upload:' + (request.remote_addr or 'unknown'))
            if response: return response
            raw = request.form.get('invite_token', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}', raw): abort(404)
            digest = hashlib.sha256(raw.encode()).hexdigest(); db = core.get_db(); now = int(time.time())
            row = db.execute('SELECT i.* FROM privacy_upload_invites i JOIN family_data_requests r ON r.id=i.request_id WHERE i.token_hash=? AND i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at>? AND r.status IN (?,?,?)', (digest, now, *OPEN)).fetchone()
            if not row or receipt(app, digest).exists(): abort(404)
            upload = request.files.get('document')
            if not upload: abort(400)
            try: data, media, ext = decode_upload(upload.stream.read(5 * 1024 * 1024 + 1))
            except ValueError as error: abort(400, description=str(error))
            try: consume(app, digest)
            except FileExistsError: abort(404)
            key = secrets.token_hex(24) + ext; path = document_path(app, key)
            try:
                db.execute('BEGIN IMMEDIATE')
                changed = db.execute('UPDATE privacy_upload_invites SET used_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?', (now, row['id'], now)).rowcount
                req = db.execute('SELECT status FROM family_data_requests WHERE id=?', (row['request_id'],)).fetchone()
                if changed != 1 or not req or req[0] not in OPEN: abort(409)
                sealed=document_cipher(app,create=True).encrypt(data)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as out: out.write(sealed); out.flush(); os.fsync(out.fileno())
                db.execute('INSERT INTO privacy_submission_documents(request_id,storage_key,media_type,bytes,sha256,created_at) VALUES (?,?,?,?,?,?)', (row['request_id'], key, media, len(data), hashlib.sha256(data).hexdigest(), now))
                privacy.event(db, row['request_id'], 0, 'document-received', 'Invite-only submission received; identity and authority remain unverified.'); db.commit()
            except Exception:
                db.rollback(); path.unlink(missing_ok=True); raise
            message = 'Your document was received for staff review. Submission does not establish identity or authority. This link has now been used.'
        response = app.make_response(render_template('privacy_upload.html', token=core.theme_csrf_token(), nonce=nonce, message=message))
        response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-" + nonce + "'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.get('/manage/privacy/submissions/<int:document_id>')
    def privacy_submission_download(document_id):
        staff(); db = core.get_db()
        row = db.execute('SELECT * FROM privacy_submission_documents WHERE id=? AND purged_at IS NULL AND purge_started_at IS NULL', (document_id,)).fetchone()
        if not row: abort(404)
        try: path = document_path(app, row['storage_key'])
        except ValueError: abort(404)
        if not path.is_file(): abort(404)
        try:data=document_cipher(app).decrypt(path.read_bytes())
        except (OSError,ValueError,InvalidToken):abort(409,description='The document or its private encryption key needs staff recovery.')
        if hashlib.sha256(data).hexdigest() != row['sha256']: abort(409)
        response = send_file(io.BytesIO(data), mimetype=row['media_type'], as_attachment=True,
                             download_name='verification-document-' + str(row['id']) + path.suffix, conditional=False)
        response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
        return response

    @app.after_request
    def submission_headers(response):
        if request.endpoint in ('privacy_submissions', 'privacy_submission_upload', 'privacy_submission_download'):
            response.headers.update({'Cache-Control': 'private, no-store', 'Referrer-Policy': ('same-origin' if request.endpoint in ('privacy_submissions', 'privacy_submission_upload') else 'no-referrer'),
                                     'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex, nofollow',
                                     'X-Frame-Options': 'DENY'})
        return response
