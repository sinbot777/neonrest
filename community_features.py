"""Durable community safety tools for the Neonrest Flask sandbox."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import time
from pathlib import Path
from functools import wraps
from urllib.parse import quote
from flask import request, session, g, abort, redirect, url_for, flash, render_template, Response, current_app, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from flask_mail import Message
import posixpath
from neonrest_sandbox import age_policy as ages
from neonrest_sandbox import welcome

KINDS = ('friends', 'comments', 'replies', 'circles', 'circle_posts', 'moderation', 'appeals', 'reports')
FIELDS = ('bio', 'dob', 'pronouns', 'location', 'pets', 'relationship_status', 'timezone', 'lastfm_username', 'mood', 'frequent_haunts')
AUDIENCES = ('public', 'friends', 'private')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def migrate(db):
    statements = [
        '''CREATE TABLE IF NOT EXISTS account_safety(user_id INTEGER PRIMARY KEY, inactive INTEGER NOT NULL DEFAULT 0,
           totp_secret TEXT, totp_step INTEGER NOT NULL DEFAULT -1, deletion_requested_at TEXT)''',
        '''CREATE TABLE IF NOT EXISTS active_sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
           created_at INTEGER NOT NULL, seen_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
           agent TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS recovery_codes(user_id INTEGER NOT NULL, code_hash TEXT NOT NULL,
           PRIMARY KEY(user_id,code_hash))''',
        '''CREATE TABLE IF NOT EXISTS password_resets(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
           expires_at INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS privacy_settings(user_id INTEGER PRIMARY KEY, profile_audience TEXT NOT NULL DEFAULT 'public',
           post_audience TEXT NOT NULL DEFAULT 'public', comments_from TEXT NOT NULL DEFAULT 'everyone',
           requests_from TEXT NOT NULL DEFAULT 'everyone', field_audiences TEXT NOT NULL DEFAULT '{}')''',
        '''CREATE TABLE IF NOT EXISTS user_blocks(user_id INTEGER NOT NULL,target_id INTEGER NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
           PRIMARY KEY(user_id,target_id))''',
        '''CREATE TABLE IF NOT EXISTS user_mutes(user_id INTEGER NOT NULL,target_id INTEGER NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
           PRIMARY KEY(user_id,target_id))''',
        '''CREATE TABLE IF NOT EXISTS post_privacy(post_id INTEGER PRIMARY KEY,audience TEXT NOT NULL DEFAULT 'public')''',
        '''CREATE TABLE IF NOT EXISTS notification_settings(user_id INTEGER NOT NULL,kind TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
           PRIMARY KEY(user_id,kind))''',
        '''CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,actor_id INTEGER,
           kind TEXT NOT NULL,message TEXT NOT NULL,path TEXT NOT NULL,read_at TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS moderation_cases(id INTEGER PRIMARY KEY,target_type TEXT NOT NULL,target_id INTEGER NOT NULL,
           owner_id INTEGER,status TEXT NOT NULL DEFAULT 'open',assigned_to INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
           UNIQUE(target_type,target_id))''',
        '''CREATE TABLE IF NOT EXISTS case_evidence(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,report_id INTEGER,
           event_id INTEGER,source_type TEXT NOT NULL,source_id INTEGER NOT NULL,snapshot TEXT NOT NULL,
           sha256 TEXT NOT NULL,captured_at TEXT DEFAULT CURRENT_TIMESTAMP,legacy INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS case_links(case_id INTEGER NOT NULL,kind TEXT NOT NULL,item_id INTEGER NOT NULL,
           PRIMARY KEY(kind,item_id))''',
        '''CREATE TABLE IF NOT EXISTS case_notes(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,actor_id INTEGER NOT NULL,
           body TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS rate_buckets(subject TEXT NOT NULL,action TEXT NOT NULL,window INTEGER NOT NULL,
           count INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(subject,action,window))''',
        '''CREATE TABLE IF NOT EXISTS abuse_events(id INTEGER PRIMARY KEY,user_id INTEGER,action TEXT NOT NULL,
           created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS operations_events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,detail TEXT NOT NULL,
           created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS backup_records(id INTEGER PRIMARY KEY,path TEXT NOT NULL,bytes INTEGER NOT NULL,
           created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        'CREATE INDEX IF NOT EXISTS idx_session_user ON active_sessions(user_id,revoked)',
        'CREATE INDEX IF NOT EXISTS idx_notification_user ON notifications(user_id,id DESC)',
        'CREATE INDEX IF NOT EXISTS idx_evidence_case ON case_evidence(case_id,id)',
        'CREATE INDEX IF NOT EXISTS idx_case_owner ON moderation_cases(owner_id)',
        '''CREATE TRIGGER IF NOT EXISTS immutable_case_evidence_update BEFORE UPDATE ON case_evidence
           BEGIN SELECT RAISE(ABORT,'Case evidence is immutable'); END''',
        '''CREATE TRIGGER IF NOT EXISTS immutable_case_evidence_delete BEFORE DELETE ON case_evidence
           BEGIN SELECT RAISE(ABORT,'Case evidence is immutable'); END''',
    ]
    for statement in statements:
        db.execute(statement)
    db.commit()


def friends(db, a, b):
    return bool(a and b and db.execute("SELECT 1 FROM friend_requests WHERE status='accepted' AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))", (a,b,b,a)).fetchone())


def blocked(db, a, b):
    return bool(a and b and db.execute('SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)', (a,b,b,a)).fetchone())


def settings(db, uid):
    row = db.execute('SELECT * FROM privacy_settings WHERE user_id=?', (uid,)).fetchone()
    return dict(row) if row else dict(profile_audience='public',post_audience='public',comments_from='everyone',requests_from='everyone',field_audiences='{}')


def audience_allows(db, owner, viewer, audience):
    return welcome.staff(db,viewer) or owner == viewer or audience == 'public' or (audience == 'friends' and (friends(db, owner, viewer) or ages.family(db,owner,viewer)))


def member_visible(db, owner, viewer):
    if welcome.staff(db,viewer): return bool(db.execute('SELECT 1 FROM users WHERE id=?',(owner,)).fetchone())
    disabled=db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(owner,)).fetchone()
    if disabled:return False
    state = db.execute('SELECT inactive FROM account_safety WHERE user_id=?', (owner,)).fetchone()
    return not (state and state['inactive']) and not blocked(db, owner, viewer) and ages.can_read(db,owner,viewer,profile=True)


def visible_post(db, pid, viewer, muted=True, include_circle_removed=False, external_circle_share=False):
    post = db.execute('SELECT user_id,target_user_id FROM posts WHERE id=?', (pid,)).fetchone()
    if not post: return False
    from neonrest_sandbox.circles import post_allowed
    circle_access = post_allowed(db,pid,viewer,include_removed=include_circle_removed)
    if external_circle_share and circle_access is False:
        from neonrest_sandbox.sharing import circle_external_allowed
        if circle_external_allowed(db, pid, viewer):
            circle_access = True
    if circle_access is False: return False
    if welcome.staff(db,viewer): return True
    if welcome.personal_hidden(db,post['user_id'],viewer) and not welcome.announcement(db,pid): return False
    if db.execute('SELECT 1 FROM moderated_posts WHERE post_id=?', (pid,)).fetchone():
        return False
    owner = post['user_id']
    if not member_visible(db, owner, viewer):
        return False
    protected=bool(db.execute('SELECT 1 FROM protected_age_posts WHERE post_id=?',(pid,)).fetchone())
    announcement=not protected and welcome.announcement(db,pid) and viewer and ages.ready(db,viewer)
    if not ages.can_read(db,owner,viewer,protected=protected) and not announcement:
        return False
    if post['target_user_id'] and not member_visible(db, post['target_user_id'], viewer):
        return False
    if muted and viewer != owner and db.execute('SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?', (viewer, owner)).fetchone():
        return False
    row = db.execute('SELECT audience FROM post_privacy WHERE post_id=?', (pid,)).fetchone()
    from .social_connections import post_audience_allows
    return bool(circle_access) if circle_access is not None else post_audience_allows(db, owner, viewer, row['audience'] if row else 'public')


def register_db_functions(db):
    from neonrest_sandbox.circles import comment_allowed
    db.create_function('age_comment_visible',1,lambda cid: int(ages.comment_read(db,cid,session.get('user_id')) and comment_allowed(db,cid,session.get('user_id'))))
    db.create_function('community_profile_visible',1,lambda uid: int(member_visible(db,uid,session.get('user_id')) and audience_allows(db,uid,session.get('user_id'),settings(db,uid)['profile_audience'])))
    db.create_function('community_personal_profile_visible',1,lambda uid: int(member_visible(db,uid,session.get('user_id')) and not ages.limited_staff_profile(db,uid,session.get('user_id')) and audience_allows(db,uid,session.get('user_id'),settings(db,uid)['profile_audience'])))
    db.create_function('community_post_visible', 1, lambda pid: int(visible_post(db, pid, session.get('user_id'))))
    db.create_function('community_member_visible', 1, lambda uid: int(member_visible(db, uid, session.get('user_id')) and not db.execute('SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?', (session.get('user_id'), uid)).fetchone()))


def redacted_profile(db, user, viewer):
    result = dict(user)
    if user['id'] != viewer:
        for key in ('email','password_hash','dob','actual_name'):
            result[key] = ''
        field_settings = json.loads(settings(db, user['id'])['field_audiences'])
        for field in FIELDS:
            if not audience_allows(db, user['id'], viewer, field_settings.get(field, 'public')):
                result[field] = ''
    return result


def notification_visible(db, row, uid):
    """Recheck permissions when delivering, listing or counting a notification."""
    if row['kind'] in ('moderation', 'appeals', 'reports') and not row['actor_id']:
        return True
    actor = row['actor_id']
    if actor and (blocked(db, uid, actor) or db.execute(
            'SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?', (uid, actor)).fetchone()
            or not member_visible(db, actor, uid)
            or not ages.contact(db, uid, actor, invitation=row['kind']=='friends')):
        return False
    if row['kind']=='messages':
        from neonrest_sandbox.messaging import visible_notice
        return bool(current_app.config.get('MESSAGING_ENABLED') and visible_notice(db,row,uid))
    path = row['path'] or ''
    if path.startswith('/circles/'):
        from neonrest_sandbox import circles, circle_ids
        from urllib.parse import urlsplit,parse_qs
        parsed=urlsplit(path)
        parts = parsed.path[len('/circles/'):].split('/')
        if len(parts) > 2 or len(parts) == 2 and parts[1] not in ('manage','reports'):
            return False
        try:
            cid = circle_ids.resolve(db, parts[0])
        except ValueError:
            return False
        circle = db.execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
        if not circle or not circles.info_allowed(db, circle, uid):
            return False
        if len(parts) == 2:
            member = circles.membership(db, circle, uid)
            if not member or member['role'] not in ('owner','moderator'):return False
            if parts[1]=='reports' and parsed.query:
                params=parse_qs(parsed.query,keep_blank_values=True)
                values=params.get('report_id',[])
                if set(params)!={'report_id'} or len(values)!=1 or not values[0].isascii() or not values[0].isdecimal() or not 1<=len(values[0])<=18:return False
                report=db.execute('SELECT author_id FROM circle_reports WHERE id=? AND circle_id=?',(int(values[0]),cid)).fetchone()
                return bool(report and report['author_id']!=uid)
            return True
        return bool(circles.membership(db, circle, uid) or circles.invitation(db,cid,uid))
    if path == '/friends':
        return bool(actor and db.execute("SELECT 1 FROM friend_requests WHERE ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)) AND status IN ('pending','accepted')", (uid, actor, actor, uid)).fetchone())
    if path.startswith('/posts/'):
        parts = path.split('#', 1)
        pid = parts[0][len('/posts/'):]
        from neonrest_sandbox.public_ids import resolve
        try:pid=resolve(db,'post',pid)
        except ValueError:return False
        if not visible_post(db,pid,uid):return False
        if len(parts) > 1 and parts[1].startswith('comment-'):
            cid = parts[1][len('comment-'):]
            try:cid=resolve(db,'comment',cid,anchor=True)
            except ValueError:return False
            comment = db.execute('SELECT user_id FROM comments WHERE id=? AND post_id=?', (cid,pid)).fetchone()
            from neonrest_sandbox.circles import comment_allowed
            if not comment or not member_visible(db, comment['user_id'], uid) or not ages.comment_read(db,cid,uid) or not comment_allowed(db,cid,uid):
                return False
        return True
    if path.startswith('/@'):
        owner = db.execute('SELECT id FROM users WHERE handle=?', (path[1:],)).fetchone()
        return bool(owner and member_visible(db, owner['id'], uid))
    return False


def notify(db, uid, kind, message, path, actor=None):
    from neonrest_sandbox.public_ids import canonical_path
    path=canonical_path(db,path,internal=True)
    if not uid or uid == actor:
        return
    preference = db.execute('SELECT enabled FROM notification_settings WHERE user_id=? AND kind=?', (uid,kind)).fetchone()
    if preference and not preference['enabled']:
        return
    if actor and kind not in ('moderation','appeals','reports') and not ages.contact(db,uid,actor,invitation=kind=='friends'):
        return
    if actor and kind not in ('moderation','appeals','reports') and (blocked(db,uid,actor) or db.execute('SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?',(uid,actor)).fetchone()):
        return
    if not notification_visible(db, {'actor_id':actor,'kind':kind,'path':path}, uid):
        return
    db.execute('INSERT INTO notifications(user_id,actor_id,kind,message,path) VALUES (?,?,?,?,?)', (uid,actor,kind,message,path))


def target_snapshot(db, kind, target_id):
    table = {'user':'users','post':'posts','comment':'comments'}.get(kind)
    if not table:
        return {'source_type':kind,'source_id':target_id,'unavailable':True}
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (target_id,)).fetchone()
    data = {'source_type':kind,'source_id':target_id,'content':dict(row) if row else None}
    if kind == 'user' and row:
        data['content'] = {key:row[key] for key in ('id','handle','bio','created_at') if key in row.keys()}
    pid = target_id if kind == 'post' else row['post_id'] if kind == 'comment' and row else None
    if pid:
        post = db.execute('SELECT id,user_id,content,created_at,last_edited FROM posts WHERE id=?',(pid,)).fetchone()
        data['post'] = dict(post) if post else None
        data['comments'] = [dict(r) for r in db.execute('SELECT * FROM comments WHERE post_id=? ORDER BY id LIMIT 100',(pid,))]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_media'").fetchone():
            data['media'] = [dict(r) for r in db.execute('SELECT * FROM post_media WHERE post_id=?',(pid,))]
    return data


def ensure_case(db, kind, target_id, owner=None):
    case_kind = 'user' if kind in ('ban','posting','interaction','user') else kind
    if case_kind == 'comment':
        row = db.execute('SELECT post_id FROM comments WHERE id=?',(target_id,)).fetchone()
        if row:
            case_kind, target_id = 'post', row['post_id']
    db.execute('INSERT OR IGNORE INTO moderation_cases(target_type,target_id,owner_id) VALUES (?,?,?)',(case_kind,target_id,owner))
    row = db.execute('SELECT id FROM moderation_cases WHERE target_type=? AND target_id=?',(case_kind,target_id)).fetchone()
    if owner is not None:
        db.execute('UPDATE moderation_cases SET owner_id=COALESCE(owner_id,?) WHERE id=?',(owner,row['id']))
    return row['id']


def preserve(db, case_id, kind, target_id, report_id=None, event_id=None, legacy=False, shared_source=False):
    data = target_snapshot(db,kind,target_id)
    if shared_source:
        data['comments'] = []
        data['external_shared_source'] = True
    data['preserved_files']=[]
    folder=Path(current_app.instance_path)/'case-evidence'
    media_folder=Path(current_app.instance_path)/'media'
    for item in data.get('media',[]):
        for key in ('filename','poster','loop_filename'):
            name=item.get(key)
            if not name or Path(name).name!=name:
                continue
            source=media_folder/name
            if source.is_file():
                raw=source.read_bytes()
                checksum=hashlib.sha256(raw).hexdigest()
                saved=checksum+source.suffix
                folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                destination=folder/saved
                if not destination.exists():
                    destination.write_bytes(raw); destination.chmod(0o600)
                data['preserved_files'].append({'name':saved,'original':name,'sha256':checksum,'bytes':len(raw)})
    import re
    text=(data.get('post') or data.get('content') or {}).get('content','')
    for name in re.findall(r'/+(?:sandbox/)?static/(uploads/posts/[A-Za-z0-9_.-]+)',text):
        source=Path(current_app.static_folder)/name
        if source.is_file():
            raw=source.read_bytes(); checksum=hashlib.sha256(raw).hexdigest(); saved=checksum+source.suffix
            folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            destination=folder/saved
            if not destination.exists():
                destination.write_bytes(raw); destination.chmod(0o600)
            data['preserved_files'].append({'name':saved,'original':source.name,'sha256':checksum,'bytes':len(raw)})
    snapshot = json.dumps(data, ensure_ascii=False,sort_keys=True)
    db.execute('INSERT INTO case_evidence(case_id,report_id,event_id,source_type,source_id,snapshot,sha256,legacy) VALUES (?,?,?,?,?,?,?,?)',
               (case_id,report_id,event_id,kind,target_id,snapshot,digest(snapshot),int(legacy)))
    if not shared_source and kind == 'post' and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_shares'").fetchone():
        ref = db.execute('SELECT source_post_id FROM post_shares WHERE share_post_id=?',(target_id,)).fetchone()
        if ref:
            from neonrest_sandbox.sharing import source_viewable
            if source_viewable(db,ref[0],session.get('user_id')):
                preserve(db,case_id,'post',ref[0],report_id=report_id,event_id=event_id,legacy=legacy,shared_source=True)


def attach_report(db, report_id, legacy=False):
    row = db.execute('SELECT * FROM content_reports WHERE id=?',(report_id,)).fetchone()
    if db.execute("SELECT 1 FROM case_links WHERE kind='report' AND item_id=?",(report_id,)).fetchone():
        return
    target = target_snapshot(db,row['target_type'],row['target_id'])['content']
    owner = target.get('user_id', target.get('id')) if target else None
    cid = ensure_case(db,row['target_type'],row['target_id'],owner)
    db.execute("INSERT INTO case_links VALUES (?,'report',?)",(cid,report_id))
    db.execute("UPDATE moderation_cases SET status='open' WHERE id=?",(cid,))
    preserve(db,cid,row['target_type'],row['target_id'],report_id=report_id,legacy=legacy)


def attach_appeal(db, appeal_id):
    row = db.execute('SELECT * FROM moderation_appeals WHERE id=?',(appeal_id,)).fetchone()
    cid = ensure_case(db,row['target_type'],row['target_id'],row['appellant_id'])
    db.execute("INSERT OR IGNORE INTO case_links VALUES (?,'appeal',?)",(cid,appeal_id))
    db.execute("UPDATE moderation_cases SET status='open' WHERE id=?",(cid,))


def attach_event(db, event_id, legacy=False):
    row = db.execute('SELECT * FROM moderation_events WHERE id=?',(event_id,)).fetchone()
    if db.execute("SELECT 1 FROM case_links WHERE kind='event' AND item_id=?",(event_id,)).fetchone():
        return
    link = db.execute('SELECT case_id FROM case_links WHERE kind=? AND item_id=?',
        ('report' if row['report_id'] else 'appeal',row['report_id'] or row['appeal_id'])).fetchone() if row['report_id'] or row['appeal_id'] else None
    kind, target = ('comment',row['comment_id']) if row['comment_id'] else ('post',row['post_id']) if row['post_id'] else ('user',row['target_user_id'])
    if not target:
        return
    cid = link['case_id'] if link else ensure_case(db,kind,target,row['target_user_id'])
    db.execute("INSERT INTO case_links VALUES (?,'event',?)",(cid,event_id))
    preserve(db,cid,kind,target,event_id=event_id,legacy=legacy)
    if not legacy:
        if row['report_id']:
            report = db.execute('SELECT reporter_id FROM content_reports WHERE id=?',(row['report_id'],)).fetchone()
            notify(db,report['reporter_id'],'reports','Your report was reviewed.','/reports/mine')
        elif row['appeal_id']:
            notify(db,row['target_user_id'],'appeals','Your appeal has a decision.','/appeals')
        elif row['action'].startswith(('ban:','posting:','interaction:','comment:')) or row['action'] in ('hide','restore'):
            notify(db,row['target_user_id'],'moderation','A moderation decision was made on your account or content: '+row['reason'],'/appeals')


def totp_value(secret, step):
    key = base64.b32decode(secret)
    value = hmac.new(key,struct.pack('>Q',step),hashlib.sha1).digest()
    offset = value[-1] & 15
    return str((struct.unpack('>I',value[offset:offset+4])[0] & 0x7fffffff)%1000000).zfill(6)


def verify_second_factor(db, uid, code):
    row = db.execute('SELECT totp_secret,totp_step FROM account_safety WHERE user_id=?',(uid,)).fetchone()
    if not row or not row['totp_secret']:
        return False
    code = code.strip().replace(' ','')
    current = int(time.time())//30
    for step in (current-1,current,current+1):
        if step > row['totp_step'] and hmac.compare_digest(totp_value(row['totp_secret'],step),code):
            updated = db.execute('UPDATE account_safety SET totp_step=? WHERE user_id=? AND totp_step<?',(step,uid,step))
            db.commit()
            return bool(updated.rowcount)
    result = db.execute('DELETE FROM recovery_codes WHERE user_id=? AND code_hash=?',(uid,digest(code)))
    db.commit()
    return bool(result.rowcount)


def register(app, core):
    app.jinja_env.globals.update(staff_announcement_allowed=lambda: welcome.staff(core.get_db(),session.get("user_id")), staff_announcement=lambda pid: welcome.announcement(core.get_db(),pid))
    get_db = core.get_db
    token = core.theme_csrf_token
    app.config.setdefault('MAX_CONTENT_LENGTH', 6*1024*1024)
    with app.app_context():
        migrate(get_db())
        from neonrest_sandbox.operations_health import initialize as initialize_operations
        initialize_operations(get_db())
        ages.init(get_db())
        db = get_db()
        for row in db.execute("SELECT id FROM content_reports WHERE id NOT IN (SELECT item_id FROM case_links WHERE kind='report')").fetchall():
            attach_report(db,row['id'],legacy=True)
        for row in db.execute("SELECT id FROM moderation_appeals WHERE id NOT IN (SELECT item_id FROM case_links WHERE kind='appeal')").fetchall():
            attach_appeal(db,row['id'])
        for row in db.execute("SELECT id FROM moderation_events WHERE id NOT IN (SELECT item_id FROM case_links WHERE kind='event')").fetchall():
            attach_event(db,row['id'],legacy=True)
        db.commit()

    def csrf():
        submitted=request.form.get('theme_csrf_token','') or request.headers.get('X-CSRF-Token','')
        expected=session.get('theme_csrf_token','')
        if not expected or not hmac.compare_digest(submitted,expected):
            abort(400,description='Refresh the page and try again.')

    def current_user():
        uid = session.get('user_id')
        row = get_db().execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone() if uid else None
        if not row or not row['verified']:
            abort(401)
        return row

    def second_factor(uid):
        row = get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone()
        return bool(row and row['totp_secret'])

    def fresh():
        # Ordinary staff sessions confirm at most once per 24 hours.
        staff_surface=request.path.startswith(('/manage','/staff')) or request.endpoint=='edit_theme'
        max_age=86400 if staff_surface else 1800
        if time.time()-session.get('fresh_at',0)>max_age:
            return False
        return not second_factor(session.get('user_id')) or time.time()-session.get('factor_at',0)<=max_age

    def start_session(user, factor=False):
        session.clear()
        raw = secrets.token_urlsafe(32)
        now = int(time.time())
        session.update(user_id=user['id'],user_email=user['email'],user_handle=user['handle'],sid=raw,fresh_at=now)
        if factor:
            session['factor_at']=now
        get_db().execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(digest(raw),user['id'],now,now,now+30*86400,(request.user_agent.string or 'Unknown device')[:200]))
        get_db().commit()

    def limited(action, maximum, seconds=3600, subject=None):
        subject = subject or 'user:'+str(session.get('user_id'))
        # Hash network identifiers; never store the raw address in abuse tools.
        subject = digest(subject)
        now = int(time.time())
        window = now//seconds
        db=get_db()
        row=db.execute('''INSERT INTO rate_buckets(subject,action,window,touched_at) VALUES (?,?,?,?)
            ON CONFLICT(subject,action,window) DO UPDATE SET count=count+1,touched_at=excluded.touched_at RETURNING count''',(subject,action,window,now)).fetchone()
        if row['count']>maximum:
            db.execute('INSERT INTO abuse_events(user_id,action) VALUES (?,?)',(session.get('user_id'),action))
            db.commit()
            response=Response('Too many attempts. Please try again later.',status=429)
            response.headers['Retry-After']=str(seconds-now%seconds)
            return response
        db.commit()
        return None

    app.extensions['community_auth_helpers']={'csrf':csrf,'limited':limited,'fresh':fresh}
    def gate():
        if request.endpoint == 'static':
            filename=posixpath.normpath((request.view_args or {}).get('filename',''))
            if filename.startswith('uploads/posts/'):
                db=get_db()
                rows=db.execute('SELECT id FROM posts WHERE content LIKE ?',('%'+filename+'%',)).fetchall()
                if not any(visible_post(db,row['id'],session.get('user_id'),muted=False) for row in rows):
                    abort(404)
            return
        uid = session.get('user_id')
        db=get_db()
        if uid:
            sid=session.get('sid')
            active=db.execute('SELECT * FROM active_sessions WHERE token_hash=? AND user_id=?',(digest(sid or ''),uid)).fetchone()
            if not active or active['revoked'] or active['expires_at']<time.time():
                session.clear()
                if request.endpoint not in ('login','password_reset_request','password_reset','community_login_factor'):
                    if request.method=='POST':
                        abort(401,description='Sign in again before saving changes.')
                    return redirect(url_for('login'))
                uid=None
            elif active['seen_at']<time.time()-300:
                db.execute('UPDATE active_sessions SET seen_at=? WHERE token_hash=?',(int(time.time()),digest(sid)))
                db.commit()
        state=db.execute('SELECT inactive FROM account_safety WHERE user_id=?',(uid,)).fetchone() if uid else None
        if state and state['inactive'] and request.endpoint not in ('community_data','community_export','community_reactivate','logout','community_reauth','family_data_requests','privacy_request_appeal'):
            return redirect(url_for('community_data'))
        if request.method=='POST':
            if request.endpoint in ('login','community_login_factor','community_reauth','password_reset_request','password_reset'):
                response=limited('authentication',20,900,subject='network:'+str(request.remote_addr))
                if response:
                    return response
            limits={'password_reset_request':(5,900),'signup':(4,3600),'create_post':(30,3600),'create_comment':(60,3600),
                'friends.send_request':(15,3600),'report_content':(15,3600),'appeal_form':(10,3600),'react_to_post':(120,3600)}
            if request.endpoint in limits:
                maximum,seconds=limits[request.endpoint]
                response=limited(request.endpoint,maximum,seconds,subject=('user:'+str(uid)) if uid else ('network:'+str(request.remote_addr)))
                if response:
                    return response
            # Origin validation protects legacy forms without altering their individual token schemes.
            origin=request.headers.get('Origin')
            if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                abort(403)
            if request.endpoint in ('create_post','create_comment','edit_post','edit_comment','delete_post','delete_comment','signup','account','login','update_mood','update_haunts','update_bio','friends.follow','friends.unfollow','react_to_post'):
                csrf()
            if request.endpoint=='signup' and not 12<=len(request.form.get('password',''))<=128:
                g.statistics_signup_outcome='password'
                abort(400,description='Use a password between 12 and 128 characters.')
            if request.endpoint=='account' and 'new_password' in request.form:
                if not fresh():
                    return redirect(url_for('community_reauth',next='/account'))
                if not 12<=len(request.form['new_password'])<=128:
                    abort(400,description='Use a password between 12 and 128 characters.')
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(uid,))
                db.commit()
        if request.endpoint=='edit_comment':
            from neonrest_sandbox.circles import post_allowed,comment_allowed
            if not comment_allowed(db,request.view_args.get('comment_id'),uid):abort(404)
            comment=db.execute('SELECT post_id FROM comments WHERE id=?',(request.view_args.get('comment_id'),)).fetchone()
            if comment and post_allowed(db,comment['post_id'],uid) is False: abort(404)
        if request.endpoint=='post_edit_history':
            history_owner=db.execute('SELECT user_id FROM posts WHERE id=?',(request.view_args.get('post_id'),)).fetchone()
            if history_owner and welcome.personal_hidden(db,history_owner['user_id'],uid): abort(404)
        statistics_read=request.method in ('GET','HEAD') and request.endpoint in ('site_statistics','site_statistics_csv')
        staff_surface=request.path.startswith(('/manage','/staff')) or request.endpoint=='edit_theme'
        if staff_surface and uid and (core.staff_permissions(db,uid) or core.management_scope() is not None):
            if not second_factor(uid):
                flash('Set up two-factor authentication before opening staff tools.','info')
                return redirect(url_for('community_security'))
            if not statistics_read and not fresh():
                return redirect(url_for('community_reauth',next=request.path))
        sensitive=request.method=='POST' and (request.endpoint=='assign_staff_role' or
            request.endpoint=='review_appeal' and request.form.get('decision')=='overturned' or
            request.endpoint=='moderate_user' and request.form.get('action')=='ban')
        if sensitive and not fresh():
            flash('Confirm your password and verification code, then submit the action again.','info')
            return redirect(url_for('community_reauth',next='/manage'))
        profile_id=None
        if request.endpoint in ('user_page_test','user_page'):
            profile_id=request.view_args['user_id']
        elif request.endpoint in ('user_by_handle','friends.public_friends'):
            row=db.execute('SELECT id FROM users WHERE lower(ltrim(handle,\'@\'))=lower(?)',(request.view_args['handle'].lstrip('@'),)).fetchone()
            profile_id=row['id'] if row else None
        if profile_id:
            if not member_visible(db,profile_id,uid) or not audience_allows(db,profile_id,uid,settings(db,profile_id)['profile_audience']):
                abort(404)
            if request.endpoint=='friends.public_friends' and ages.limited_staff_profile(db,profile_id,uid):
                abort(404)
        if request.endpoint=='now_playing':
            username=request.view_args['username']
            owner=db.execute('SELECT id FROM users WHERE lastfm_username=?',(username,)).fetchone()
            if not owner or not member_visible(db,owner['id'],uid) or ages.limited_staff_profile(db,owner['id'],uid) or not audience_allows(db,owner['id'],uid,settings(db,owner['id'])['profile_audience']) or not audience_allows(db,owner['id'],uid,json.loads(settings(db,owner['id'])['field_audiences']).get('lastfm_username','public')):
                abort(404)
        if request.endpoint in ('create_comment','react_to_post','report_content'):
            if request.endpoint=='report_content':
                kind=request.view_args['kind']; target=request.view_args['target_id']
                if kind=='user':
                    if not member_visible(db,target,uid) or not audience_allows(db,target,uid,settings(db,target)['profile_audience']):
                        abort(404)
                if kind=='post' and not visible_post(db,target,uid,muted=False):
                    abort(404)
                if kind=='comment':
                    row=db.execute('SELECT user_id,post_id FROM comments WHERE id=?',(target,)).fetchone()
                    from neonrest_sandbox.circles import comment_allowed
                    if not row or not member_visible(db,row['user_id'],uid) or not ages.comment_read(db,target,uid) or not comment_allowed(db,target,uid) or not visible_post(db,row['post_id'],uid,muted=False):
                        abort(404)
            else:
                try:
                    pid=core.identifiers.resolve(db,'post',request.form.get('post_id','')) if request.endpoint=='create_comment' else request.view_args['post_id']
                except (ValueError,TypeError):
                    abort(400)
                if not visible_post(db,pid,uid,muted=False):
                    abort(404)
                row=db.execute('SELECT user_id FROM posts WHERE id=?',(pid,)).fetchone()
                preference=settings(db,row['user_id'])['comments_from']
                if request.endpoint=='create_comment' and row['user_id']!=uid and (preference=='nobody' or preference=='friends' and not friends(db,uid,row['user_id'])):
                    abort(403)
        if request.method=='POST' and request.endpoint in ('friends.send_request','friends.accept_friend','friends.follow','create_post'):
            target=request.view_args.get('user_id') if request.view_args else None
            if request.endpoint=='create_post':
                try:
                    target=int(request.form.get('target_user_id',uid))
                except (ValueError,TypeError):
                    abort(400)
            if request.endpoint=='friends.follow':
                from .social_connections import bounded_id
                if not bounded_id(target):abort(400)
            if target and (not member_visible(db,target,uid) or not db.execute('SELECT 1 FROM users WHERE id=?',(target,)).fetchone()):
                abort(403)
            if target and target!=uid and request.endpoint!='friends.follow':
                pref=settings(db,target)['requests_from' if request.endpoint=='friends.send_request' else 'comments_from']
                if pref=='nobody' or pref=='friends' and not friends(db,uid,target):
                    abort(403)
        if request.method=='POST' and request.endpoint=='create_post':
            audience=request.form.get('audience',settings(db,uid)['post_audience'])
            from .social_connections import valid_post_audience
            if not valid_post_audience(db,uid,audience):
                abort(400,description='Choose an available post audience.')
            if len(request.form.get('content',''))>20000:
                abort(400)
            g.new_post_audience=audience
        if request.method=='POST' and request.endpoint=='edit_post':
            audience=request.form.get('audience')
            from .social_connections import valid_post_audience
            existing=db.execute('SELECT audience FROM post_privacy WHERE post_id=?',((request.view_args or {}).get('post_id'),)).fetchone()
            if audience and not valid_post_audience(db,uid,audience,keep_archived=bool(existing and existing[0]==audience)):
                abort(400,description='Choose an available post audience.')
        if request.method=='POST' and request.endpoint=='create_comment' and len(request.form.get('content',''))>5000:
            abort(400)

    app.before_request_funcs.setdefault(None,[]).insert(0,gate)

    @app.context_processor
    def context():
        uid=session.get('user_id')
        unread=sum(notification_visible(get_db(),r,uid) for r in get_db().execute('SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL',(uid,))) if uid else 0
        return {'community_token':token,'community_unread':unread,'community_defaults':settings(get_db(),uid),
                'community_post_audience':lambda pid:(get_db().execute('SELECT audience FROM post_privacy WHERE post_id=?',(pid,)).fetchone() or {'audience':'public'})['audience']}

    @app.after_request
    def headers(response):
        if request.endpoint!='static':
            response.headers['Cache-Control']='private, no-store' if 'private' in response.headers.get('Cache-Control','') else 'no-store'
            response.headers.setdefault('Referrer-Policy','same-origin')
        return response

    from neonrest_sandbox.email_delivery import install as install_email_delivery
    install_email_delivery(app,core)

    from flask import got_request_exception
    def exception_event(sender,exception,**extra):
        try:
            db=get_db(); db.rollback()
            reference=secrets.token_hex(6)
            g.operation_error_reference=reference
            detail=f"{reference} · {request.endpoint or 'unknown route'} · {type(exception).__name__}"
            db.execute("INSERT INTO operations_events(kind,detail) VALUES ('error',?)",(detail,)); db.commit()
        except Exception:
            app.logger.error('Could not record application error')
    got_request_exception.connect(exception_event,app,weak=False)

    @app.errorhandler(500)
    def operations_error_page(error):
        from markupsafe import escape
        reference=getattr(g,'operation_error_reference','unavailable')
        # Standalone HTML keeps the fallback usable even if database-backed context fails.
        body=f"""<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Something went wrong · Neonrest</title><style>body{{background:#20232c;color:#f2f0f5;font:1rem/1.6 system-ui;padding:2rem}}main{{max-width:40rem;margin:3rem auto;padding:2rem;border:1px solid #776378;border-radius:16px}}a{{color:#ffbea9}}a:focus-visible{{outline:3px solid #ffd68a;outline-offset:4px}}</style><main><h1>Something went wrong</h1><p>Please try again in a moment. If it keeps happening, include this reference when asking for help: <strong>{escape(reference)}</strong>.</p><p><a href="{escape(url_for('feed'))}">Back to feed</a></p></main></html>"""
        return Response(body,status=500,mimetype='text/html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    def render(page,heading,**values):
        return render_template('community.html',page=page,heading=heading,token=token(),kinds=KINDS,fields=FIELDS,**values)

    def login():
        if request.method=='GET' and session.get('user_id'):
            db=get_db(); user=current_user()
            return redirect(url_for('community_data') if (db.execute('SELECT inactive FROM account_safety WHERE user_id=?',(user['id'],)).fetchone() or {'inactive':0})['inactive'] else url_for('my_appeals') if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',(user['id'],)).fetchone() else url_for('user_by_handle', handle=user['handle'].lstrip('@')))
        if request.method=='POST':
            csrf(); db=get_db()
            user=db.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE',(request.form.get('email','').strip(),)).fetchone()
            if user and db.execute('SELECT 1 FROM reserved_accounts WHERE user_id=? AND disabled=1 UNION SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(user['id'],user['id'])).fetchone():user=None
            password=request.form.get('password','')
            if user and not user['verified'] and len(password)<=128 and check_password_hash(user['password_hash'],password):
                from neonrest_sandbox.email_verification import send_verification
                accepted=send_verification(core,db,user['email'])
                flash('Please verify your email before signing in.' if accepted else 'We could not send your verification email. Your account is saved; request another email below or use a previously received link.','info' if accepted else 'error')
                return redirect(url_for('verification_request'))
            if user and len(password)<=128 and check_password_hash(user['password_hash'],password) and user['verified']:
                if second_factor(user['id']):
                    session.clear(); session.update(pending_login=user['id'],pending_at=int(time.time()))
                    return redirect(url_for('community_login_factor'))
                start_session(user)
                return redirect(url_for('community_data') if (db.execute('SELECT inactive FROM account_safety WHERE user_id=?',(user['id'],)).fetchone() or {'inactive':0})['inactive'] else url_for('my_appeals') if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',(user['id'],)).fetchone() else url_for('user_by_handle', handle=user['handle'].lstrip('@')))
            flash('Sign-in failed. Check your credentials and email verification.','error')
        return render_template('login.html')
    app.view_functions['login']=login

    @app.route('/login/verify',methods=['GET','POST'])
    def community_login_factor():
        uid=session.get('pending_login')
        if not uid or time.time()-session.get('pending_at',0)>300:
            return redirect(url_for('login'))
        if request.method=='POST':
            csrf()
            response=limited('second-factor',10,300,subject='pending:'+str(uid))
            if response:
                return response
            if verify_second_factor(get_db(),uid,request.form.get('code','')):
                user=get_db().execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
                start_session(user,factor=True)
                return redirect(url_for('community_data') if (get_db().execute('SELECT inactive FROM account_safety WHERE user_id=?',(uid,)).fetchone() or {'inactive':0})['inactive'] else url_for('my_appeals') if get_db().execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',(uid,)).fetchone() else url_for('user_by_handle', handle=user['handle'].lstrip('@')))
            flash('Invalid or already-used code. Try a new code or a recovery code.','error')
        return render('factor','Verify your sign-in')

    @app.route('/account/reauth',methods=['GET','POST'])
    def community_reauth():
        user=current_user()
        next_path=request.args.get('next','/account/security')
        if not next_path.startswith('/') or next_path.startswith('//') or '\\' in next_path:
            next_path='/account/security'
        if request.method=='POST':
            csrf()
            if len(request.form.get('password',''))<=128 and check_password_hash(user['password_hash'],request.form.get('password','')) and (not second_factor(user['id']) or verify_second_factor(get_db(),user['id'],request.form.get('code',''))):
                session['fresh_at']=int(time.time())
                if second_factor(user['id']):
                    session['factor_at']=int(time.time())
                return redirect(request.script_root+next_path)
            flash('Confirmation failed. Check your password and verification code.','error')
        return render('reauth','Confirm your sign-in',needs_factor=second_factor(user['id']))

    @app.route('/account/security',methods=['GET','POST'])
    def community_security():
        user=current_user(); db=get_db(); uid=user['id']; backup_codes=[]
        if request.method=='POST':
            csrf()
            if not fresh():
                return redirect(url_for('community_reauth',next='/account/security'))
            action=request.form.get('action')
            if action=='begin':
                session['pending_totp']=base64.b32encode(secrets.token_bytes(20)).decode()
            elif action=='enable':
                secret=session.get('pending_totp')
                matched_step=next((step for step in (int(time.time())//30-1,int(time.time())//30,int(time.time())//30+1) if secret and hmac.compare_digest(totp_value(secret,step),request.form.get('code',''))),None)
                if matched_step is None:
                    flash('The verification code did not match.','error')
                else:
                    db.execute('INSERT OR IGNORE INTO account_safety(user_id) VALUES (?)',(uid,))
                    db.execute('UPDATE account_safety SET totp_secret=?,totp_step=? WHERE user_id=?',(secret,matched_step,uid))
                    db.execute('DELETE FROM recovery_codes WHERE user_id=?',(uid,))
                    backup_codes=[secrets.token_hex(6) for _ in range(10)]
                    db.executemany('INSERT INTO recovery_codes VALUES (?,?)',[(uid,digest(code)) for code in backup_codes])
                    session.pop('pending_totp',None); session['factor_at']=int(time.time())
                    db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=? AND token_hash<>?',(uid,digest(session['sid'])))
                    flash('Two-factor authentication enabled. Save your recovery codes.','success')
            elif action=='revoke':
                db.execute('UPDATE active_sessions SET revoked=1 WHERE token_hash=? AND user_id=?',(request.form.get('session_hash',''),uid))
            elif action=='all':
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(uid,)); session.clear(); db.commit()
                return redirect(url_for('login'))
            elif action=='password':
                password=request.form.get('new_password','')
                if not 12<=len(password)<=128:
                    abort(400,description='Use a password between 12 and 128 characters.')
                db.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(password),uid))
                db.execute('UPDATE password_resets SET used=1 WHERE user_id=?',(uid,))
                db.execute('UPDATE email_changes SET used=1 WHERE user_id=?',(uid,))
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(uid,)); db.commit(); session.clear()
                return redirect(url_for('login'))
            else:
                abort(400)
            db.commit()
        sessions=db.execute('SELECT * FROM active_sessions WHERE user_id=? AND revoked=0 AND expires_at>? ORDER BY seen_at DESC',(uid,int(time.time()))).fetchall()
        pending_secret=session.get('pending_totp')
        if pending_secret and not fresh():
            return redirect(url_for('community_reauth',next='/account/security'))
        from neonrest_sandbox.authenticator_qr import enrollment_image
        issuer='Neonrest Sandbox'
        response=current_app.make_response(render('security','Account safety',sessions=sessions,current_hash=digest(session.get('sid','')),enabled=second_factor(uid),
            pending_secret=pending_secret,backup_codes=backup_codes,
            enrollment_qr=enrollment_image(pending_secret,user['handle'],issuer) if pending_secret else None))
        response.headers['Cache-Control']='private, no-store'
        response.headers['Referrer-Policy']='same-origin'
        return response

    @app.route('/password-reset',methods=['GET','POST'])
    def password_reset_request():
        if request.method=='POST':
            csrf(); db=get_db()
            row=db.execute('SELECT id,email FROM users WHERE email=? COLLATE NOCASE',(request.form.get('email','').strip(),)).fetchone()
            if row:
                from neonrest_sandbox.email_delivery import deliver,finish_token_delivery
                raw=secrets.token_urlsafe(32)
                db.execute('INSERT INTO password_resets VALUES (?,?,?,2)',(digest(raw),row['id'],int(time.time())+3600)); db.commit()
                msg=Message(subject='Reset your Neonrest password',recipients=[row['email']])
                msg.body='Reset your password within one hour: '+('https://www.neonrest.com'+url_for('password_reset',reset_token=raw,_external=False))+'\nIf you did not request this, ignore this email.'
                from neonrest_sandbox.mail_queue import submit
                queued=submit(core,db,msg,row['id'],'reset',digest(raw))
                if queued!='queued':
                    accepted=deliver(core,msg) if queued is None else False
                    finish_token_delivery(db,'password_resets',digest(raw),accepted)
            flash('If that account is eligible, we will attempt to email a reset link. Check your inbox and spam folder. If nothing arrives, wait a minute and try again; a previously received link stays usable if the new send fails.','info')
        return render('reset_request','Reset your password')

    @app.route('/password-reset/<reset_token>',methods=['GET','POST'])
    def password_reset(reset_token):
        db=get_db(); row=db.execute('SELECT * FROM password_resets WHERE token_hash=? AND used=0 AND expires_at>?',(digest(reset_token),int(time.time()))).fetchone()
        if not row:
            return render_template('email_verification.html',state='reset_invalid'),400
        if request.method=='POST':
            csrf(); password=request.form.get('new_password','')
            if not 12<=len(password)<=128:
                abort(400,description='Use a password between 12 and 128 characters.')
            with db:
                used=db.execute('UPDATE password_resets SET used=1 WHERE token_hash=? AND used=0 AND expires_at>?',(digest(reset_token),int(time.time())))
                if not used.rowcount:
                    abort(409)
                db.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(password),row['user_id']))
                db.execute('UPDATE password_resets SET used=1 WHERE user_id=?',(row['user_id'],))
                db.execute('UPDATE email_changes SET used=1 WHERE user_id=?',(row['user_id'],))
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(row['user_id'],))
            session.clear(); flash('Password reset. Sign in again; two-factor authentication still applies.','success')
            return redirect(url_for('login'))
        return render('reset','Choose a new password')

    original_logout=app.view_functions['logout']
    def logout():
        if session.get('sid'):
            get_db().execute('UPDATE active_sessions SET revoked=1 WHERE token_hash=?',(digest(session['sid']),)); get_db().commit()
        return original_logout()
    app.view_functions['logout']=logout

    @app.route('/account/privacy',methods=['GET','POST'])
    def community_privacy():
        user=current_user(); uid=user['id']; db=get_db()
        if request.method=='POST':
            csrf()
            values={key:request.form.get(key,'') for key in ('profile_audience','post_audience','comments_from','requests_from')}
            from .social_connections import valid_post_audience
            if values['profile_audience'] not in AUDIENCES or not valid_post_audience(db,uid,values['post_audience']) or any(values[k] not in ('everyone','friends','nobody') for k in ('comments_from','requests_from')):
                abort(400)
            fields={key:request.form.get('field_'+key,'public') for key in FIELDS}
            if any(value not in AUDIENCES for value in fields.values()):
                abort(400)
            db.execute('''INSERT INTO privacy_settings VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                profile_audience=excluded.profile_audience,post_audience=excluded.post_audience,comments_from=excluded.comments_from,
                requests_from=excluded.requests_from,field_audiences=excluded.field_audiences''',
                (uid,values['profile_audience'],values['post_audience'],values['comments_from'],values['requests_from'],json.dumps(fields)))
            db.commit(); flash('Privacy settings saved. The default audience applies to new posts; edit existing posts individually.','success')
        prefs=settings(db,uid)
        blocks=db.execute('SELECT u.id,u.handle FROM user_blocks b JOIN users u ON u.id=b.target_id WHERE b.user_id=?',(uid,)).fetchall()
        mutes=db.execute('SELECT u.id,u.handle FROM user_mutes b JOIN users u ON u.id=b.target_id WHERE b.user_id=?',(uid,)).fetchall()
        return render('privacy','Member privacy',prefs=prefs,field_prefs=json.loads(prefs['field_audiences']),blocks=blocks,mutes=mutes)

    @app.route('/account/relationships',methods=['POST'])
    def community_relationship():
        user=current_user(); uid=user['id']; csrf(); db=get_db()
        handle=request.form.get('handle','').strip().lstrip('@')
        target=db.execute('SELECT id FROM users WHERE lower(ltrim(handle,\'@\'))=lower(?)',(handle,)).fetchone()
        if not target or target['id']==uid:
            abort(400)
        action=request.form.get('action'); tid=target['id']
        if action not in ('block','unblock','mute','unmute'):
            abort(400)
        table='user_blocks' if action in ('block','unblock') else 'user_mutes'
        if action.startswith('un'):
            db.execute(f'DELETE FROM {table} WHERE user_id=? AND target_id=?',(uid,tid))
        else:
            db.execute(f'INSERT OR IGNORE INTO {table}(user_id,target_id) VALUES (?,?)',(uid,tid))
            if action=='block':
                from .social_connections import clear_pair_labels
                clear_pair_labels(db,uid,tid)
                db.execute('DELETE FROM friend_requests WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)',(uid,tid,tid,uid))
                db.execute('DELETE FROM top_friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)',(uid,tid,tid,uid))
                db.execute('UPDATE follows SET revoked=1 WHERE (follower_id=? AND followed_id=?) OR (follower_id=? AND followed_id=?)',(uid,tid,tid,uid))
        db.commit(); flash('Relationship settings updated.','success')
        return redirect(url_for('community_privacy'))

    @app.route('/notifications',methods=['GET','POST'])
    def community_notifications():
        user=current_user(); uid=user['id']; db=get_db()
        if request.method=='POST':
            csrf()
            if request.form.get('action')=='read':
                nid=request.form.get('id')
                if nid=='all':
                    db.execute('UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE user_id=? AND read_at IS NULL',(uid,))
                else:
                    db.execute('UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(nid,uid))
            elif request.form.get('action')=='view':
                item=db.execute('SELECT * FROM notifications WHERE id=? AND user_id=?',(request.form.get('id'),uid)).fetchone()
                if not item or not notification_visible(db,item,uid):
                    abort(404)
                from neonrest_sandbox.public_ids import canonical_path
                destination=canonical_path(db,item['path'])
                from urllib.parse import unquote, urlsplit
                decoded=unquote(destination or '')
                if (not decoded.startswith('/') or decoded.startswith('//') or '\\' in decoded
                        or any(ord(c)<32 or ord(c)==127 for c in decoded)
                        or urlsplit(decoded).netloc or urlsplit(decoded).scheme):
                    abort(400)
                db.execute('UPDATE notifications SET read_at=COALESCE(read_at,CURRENT_TIMESTAMP) WHERE id=? AND user_id=?',(item['id'],uid))
                db.commit()
                return redirect(request.script_root+destination,code=303)
            elif request.form.get('action')=='preferences':
                for kind in KINDS:
                    db.execute('INSERT INTO notification_settings VALUES (?,?,?) ON CONFLICT(user_id,kind) DO UPDATE SET enabled=excluded.enabled',(uid,kind,int(request.form.get(kind)=='on')))
            else:
                abort(400)
            db.commit()
        records=[r for r in db.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(uid,)).fetchall() if notification_visible(db,r,uid)]
        preferences={row['kind']:row['enabled'] for row in db.execute('SELECT kind,enabled FROM notification_settings WHERE user_id=?',(uid,))}
        return render('notifications','Notifications',records=records,preferences=preferences)

    @app.route('/account/data',methods=['GET','POST'])
    def community_data():
        user=current_user(); uid=user['id']; db=get_db()
        if request.method=='POST':
            csrf()
            if not fresh():
                return redirect(url_for('community_reauth',next='/account/data'))
            action=request.form.get('action')
            if request.form.get('confirmation')!=user['handle']:
                abort(400,description='Type your exact handle to confirm.')
            db.execute('INSERT OR IGNORE INTO account_safety(user_id) VALUES (?)',(uid,))
            if action=='deactivate':
                db.execute('UPDATE email_changes SET used=1 WHERE user_id=?',(uid,))
                db.execute('UPDATE account_safety SET inactive=1 WHERE user_id=?',(uid,))
                db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(uid,))
                db.commit(); session.clear(); flash('Account deactivated. Sign in again to reactivate it.','info')
                return redirect(url_for('login'))
            elif action=='delete-request':
                db.execute('UPDATE email_changes SET used=1 WHERE user_id=?',(uid,))
                db.execute('UPDATE account_safety SET deletion_requested_at=COALESCE(deletion_requested_at,CURRENT_TIMESTAMP),inactive=1 WHERE user_id=?',(uid,))
                flash('Deletion requested. Your profile and posts are hidden. Cancel in Account data within 30 days. Permanent processing is pending activation; contact ToS@neonrest.com for help.','info')
            elif action=='cancel-delete':
                if ages.age(db,uid)<18 and db.execute('SELECT 1 FROM parent_deletion_requests WHERE child_id=?',(uid,)).fetchone():abort(403,description='A parent-directed deletion request requires guardian or staff review to cancel.')
                db.execute("UPDATE family_data_requests SET status='closed',reviewed_at=CURRENT_TIMESTAMP WHERE id IN (SELECT request_id FROM parent_deletion_requests WHERE child_id=?)",(uid,))
                db.execute('DELETE FROM parent_deletion_requests WHERE child_id=?',(uid,))
                db.execute('UPDATE account_safety SET deletion_requested_at=NULL,inactive=0 WHERE user_id=?',(uid,))
            else:
                abort(400)
            db.commit()
        state=db.execute('SELECT * FROM account_safety WHERE user_id=?',(uid,)).fetchone()
        return render('data','Your account data',user=user,state=state)

    @app.route('/account/reactivate',methods=['POST'])
    def community_reactivate():
        user=current_user(); csrf()
        if not fresh():
            return redirect(url_for('community_reauth',next='/account/data'))
        get_db().execute('UPDATE account_safety SET inactive=0 WHERE user_id=? AND deletion_requested_at IS NULL',(user['id'],)); get_db().commit()
        return redirect(url_for('feed'))

    @app.route('/account/export',methods=['POST'])
    def community_export():
        user=current_user(); csrf()
        if not fresh():
            return redirect(url_for('community_reauth',next='/account/data'))
        db=get_db(); uid=user['id']
        export={'profile':{key:user[key] for key in user.keys() if key!='password_hash'},'exported_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        for table,predicate,args in [('posts','user_id=?',(uid,)),('comments','user_id=?',(uid,)),('friend_requests','sender_id=? OR receiver_id=?',(uid,uid)),
                ('follows','follower_id=?',(uid,)),('post_reactions','user_id=?',(uid,)),('notifications','user_id=?',(uid,)),
                ('privacy_settings','user_id=?',(uid,)),('content_reports','reporter_id=?',(uid,)),('moderation_appeals','appellant_id=?',(uid,)),
                ('user_blocks','user_id=?',(uid,)),('user_mutes','user_id=?',(uid,)),('notification_settings','user_id=?',(uid,)),('top_friends','user_id=?',(uid,)),('media_settings','user_id=?',(uid,)),('account_lifecycle_events','user_id=?',(uid,)),('profile_styles','user_id=?',(uid,)),('post_vibes','post_id IN (SELECT id FROM posts WHERE user_id=?)',(uid,)),('post_media','post_id IN (SELECT id FROM posts WHERE user_id=?)',(uid,))]:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                continue
            export[table]=[dict(row) for row in db.execute(f'SELECT * FROM {table} WHERE {predicate}',args)]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dm_messages'").fetchone():
            from neonrest_sandbox.messaging import export_user
            export['private_messages']=export_user(db,uid)
        from .social_connections import export_user as export_connections
        export['social_connections']=export_connections(db,uid)
        from .reading_tools import export_user as export_reading
        export['reading_tools']=export_reading(db,uid,core.identifiers)
        from .theme_gallery import export_user as export_theme_gallery
        export['theme_gallery']=export_theme_gallery(db,uid)
        from .vibe_atmosphere import export_user as export_atmosphere
        export['vibe_atmosphere']=export_atmosphere(db,uid)
        from .identity_pages import export_user as export_pages
        export['identity_pages']=export_pages(db,uid)
        from .page_social import export_user as export_page_social
        from .events import export_user as export_events
        export['page_social']=export_page_social(db,uid)
        export['events']=export_events(db,uid)
        billing=db.execute('SELECT status,paid_until,cancel_at_period_end,review_required FROM page_subscriptions WHERE owner_id=?',(uid,)).fetchall()
        export['business_subscriptions']=[dict(row) for row in billing]
        from .storage_uploads import usage as storage_usage
        export['attachment_storage']=storage_usage()
        from .seller_studio import export_user as export_seller_studio
        export['seller_studio']=export_seller_studio(db,uid)
        from .zines_core import export_user as export_zines
        export['zines']=export_zines(db,uid)
        from .marketplace_assets import export_user as export_product_uploads
        from .marketplace_orders import export_user as export_test_orders
        export['product_uploads']=export_product_uploads(db,uid)
        export['seller_test_orders']=export_test_orders(db,uid)
        core.identifiers.export_ids(db,export)
        # Exclude internal case notes, password hashes, tokens and two-factor secrets.
        if request.form.get('include_uploads') == 'yes':
            throttled = limited('media-export', 4)
            if throttled is not None:
                return throttled
            from .media_export import download
            return download(app, db, uid, export)
        return Response(json.dumps(export,ensure_ascii=False,indent=2),mimetype='application/json',headers={'Content-Disposition':'attachment; filename="neonrest-data.json"'})

    @app.template_filter('community_time')
    def community_time(value):
        return time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(value))

    @app.route('/manage/evidence/<int:evidence_id>/<filename>')
    def community_evidence(evidence_id,filename):
        core.require_staff_permission('review_reports')
        row=get_db().execute('SELECT snapshot FROM case_evidence WHERE id=?',(evidence_id,)).fetchone()
        if not row or filename not in [item['name'] for item in json.loads(row['snapshot']).get('preserved_files',[])]:
            abort(404)
        return send_from_directory(Path(app.instance_path)/'case-evidence',filename,as_attachment=True)

    @app.route('/manage/case-link/<kind>/<int:item_id>')
    def community_case_link(kind,item_id):
        core.require_staff_permission('review_reports')
        row=get_db().execute('SELECT case_id FROM case_links WHERE kind=? AND item_id=?',(kind,item_id)).fetchone()
        if not row:
            abort(404)
        return redirect(url_for('community_case',case_id=row['case_id']))

    @app.route('/manage/cases')
    def community_cases():
        core.require_staff_permission('review_reports'); db=get_db()
        status=request.args.get('status','open'); query=request.args.get('q','').strip()[:80]
        if status not in ('open','closed','all'):
            abort(400)
        rows=db.execute('''SELECT c.*,u.handle FROM moderation_cases c LEFT JOIN users u ON u.id=c.owner_id
            WHERE (?='all' OR c.status=?) AND (?='' OR CAST(c.id AS TEXT)=? OR CAST(c.owner_id AS TEXT)=? OR u.handle LIKE ?)
            ORDER BY c.id DESC LIMIT 100''',(status,status,query,query,query,'%'+query+'%')).fetchall()
        return render('cases','Moderation case files',records=rows,status=status,query=query)

    @app.route('/manage/cases/<int:case_id>',methods=['GET','POST'])
    def community_case(case_id):
        actor=core.require_staff_permission('review_reports'); db=get_db()
        case=db.execute('SELECT * FROM moderation_cases WHERE id=?',(case_id,)).fetchone()
        if not case:
            abort(404)
        if request.method=='POST':
            csrf()
            action=request.form.get('action')
            if action=='note':
                body=request.form.get('body','').strip()
                if not 1<=len(body)<=5000:
                    abort(400)
                db.execute('INSERT INTO case_notes(case_id,actor_id,body) VALUES (?,?,?)',(case_id,actor,body))
            elif action=='assign':
                target=request.form.get('assigned_to')
                if target and (not target.isdigit() or not core.has_staff_permission(db,int(target),'review_reports')):
                    abort(400)
                db.execute('UPDATE moderation_cases SET assigned_to=? WHERE id=?',(int(target) if target else None,case_id))
                db.execute('INSERT INTO case_notes(case_id,actor_id,body) VALUES (?,?,?)',(case_id,actor,'Assignment changed to '+(target or 'unassigned')))
            elif action in ('close','reopen'):
                open_messages=bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dm_reports'").fetchone() and db.execute("SELECT 1 FROM dm_reports WHERE case_id=? AND status='open'",(case_id,)).fetchone())
                if action=='close' and (open_messages or db.execute("SELECT 1 FROM content_reports r JOIN case_links l ON l.kind='report' AND l.item_id=r.id WHERE l.case_id=? AND r.status='open'",(case_id,)).fetchone() or db.execute("SELECT 1 FROM moderation_appeals a JOIN case_links l ON l.kind='appeal' AND l.item_id=a.id WHERE l.case_id=? AND a.status='open'",(case_id,)).fetchone()):
                    abort(409,description='Review the open reports and appeals before closing this case.')
                db.execute("UPDATE moderation_cases SET status=?,closed_at=CASE WHEN ?='close' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?",('closed' if action=='close' else 'open',action,case_id))
                db.execute('INSERT INTO case_notes(case_id,actor_id,body) VALUES (?,?,?)',(case_id,actor,'Case '+action))
            else:
                abort(400)
            db.commit(); return redirect(url_for('community_case',case_id=case_id))
        evidence=[]
        for row in db.execute('SELECT * FROM case_evidence WHERE case_id=? ORDER BY id',(case_id,)):
            item=dict(row); item['valid_hash']=digest(row['snapshot'])==row['sha256']; item['files']=json.loads(row['snapshot']).get('preserved_files',[]); evidence.append(item)
        notes=db.execute('SELECT n.*,u.handle FROM case_notes n JOIN users u ON u.id=n.actor_id WHERE case_id=? ORDER BY n.id',(case_id,)).fetchall()
        links=db.execute('SELECT * FROM case_links WHERE case_id=? ORDER BY kind,item_id',(case_id,)).fetchall()
        staff=db.execute("SELECT id,handle FROM users WHERE id=1 OR id IN (SELECT user_id FROM staff_roles) ORDER BY handle").fetchall()
        return render('case','Case #'+str(case_id),case=case,evidence=evidence,notes=notes,links=links,staff=staff)

    @app.route('/manage/operations',methods=['GET','POST'])
    def community_operations():
        core.require_staff_permission('manage_roles'); db=get_db()
        if request.method=='POST':
            csrf()
            if not fresh():
                return redirect(url_for('community_reauth',next='/manage/operations'))
            if request.form.get('action')!='backup':
                abort(400)
            from neonrest_sandbox.operations_health import create_backup
            try:
                create_backup(db,Path(app.config['DATABASE']).parent/'sandbox_backups')
            except (OSError,sqlite3.Error):
                app.logger.warning('Database backup failed')
                flash('The backup could not be completed. Existing backups are preserved; check storage and try again.','error')
            else:
                flash('Database backup completed and integrity verified.','success')
            return redirect(url_for('community_operations'))
        backup=db.execute('SELECT * FROM backup_records ORDER BY id DESC LIMIT 1').fetchone()
        size=Path(app.config['DATABASE']).stat().st_size
        from neonrest_sandbox.operations_health import health
        operations_health=health(app,db)
        storage=operations_health['total_bytes']-size
        events=db.execute('SELECT * FROM operations_events ORDER BY id DESC LIMIT 50').fetchall()
        abuse=db.execute('''SELECT a.user_id,u.handle,a.action,COUNT(*) AS attempts,MAX(a.created_at) AS latest
            FROM abuse_events a LEFT JOIN users u ON u.id=a.user_id WHERE a.created_at>datetime('now','-7 days')
            GROUP BY a.user_id,a.action ORDER BY attempts DESC LIMIT 50''').fetchall()
        deletion=db.execute('SELECT u.id,u.handle,a.deletion_requested_at FROM account_safety a JOIN users u ON u.id=a.user_id WHERE deletion_requested_at IS NOT NULL').fetchall()
        metrics={table:db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('users','posts','comments','active_sessions')}
        metrics['active_sessions']=db.execute('SELECT COUNT(*) FROM active_sessions WHERE revoked=0 AND expires_at>?',(int(time.time()),)).fetchone()[0]
        integrity=db.execute('PRAGMA quick_check').fetchone()[0]
        from neonrest_sandbox.retention import run as retention_run,storage_roots
        retention_preview=retention_run(db,storage_roots(app))
        return render('operations','Site operations',operations_health=operations_health,retention_preview=retention_preview,retention_enabled=app.config.get('RETENTION_ENABLED',False),backup=backup,backup_exists=bool(backup and Path(backup['path']).is_file()),
            size=size,storage=storage,events=events,abuse=abuse,deletion=deletion,metrics=metrics,integrity=integrity,
            mail_configured=bool(app.config.get('MAIL_PASSWORD')))

    # Expose only integration helpers, keeping request authorization in this module.
    core.community_notify=notify
    app.extensions["privileged_fresh"]=fresh
    app.jinja_env.globals["authorization_post_draft"]=welcome.post_draft
    ages.register(app,core,fresh)
