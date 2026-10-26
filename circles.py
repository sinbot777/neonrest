"""Private communities. Text in posts.circle is not an access-control record."""
from .request_cache import request_lookup
from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import secrets

from flask import abort, flash, redirect, render_template, request, send_file, session, url_for, current_app, g
from PIL import Image, UnidentifiedImageError
from neonrest import age_policy as ages, circle_ids, circle_names


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS circles (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', owner_id INTEGER NOT NULL,
      mode TEXT NOT NULL CHECK(mode IN ('discoverable','hidden','followers')),
      archived INTEGER NOT NULL DEFAULT 0, icon TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS circle_members (
      circle_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
      role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('owner','moderator','member')),
      status TEXT NOT NULL CHECK(status IN ('active','pending','left','removed','declined')),
      joined_at TEXT, PRIMARY KEY(circle_id,user_id));
    CREATE TABLE IF NOT EXISTS circle_invitations (
      id INTEGER PRIMARY KEY AUTOINCREMENT, circle_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL, invited_by INTEGER NOT NULL, expires_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined','revoked')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE UNIQUE INDEX IF NOT EXISTS circle_invitation_pending
      ON circle_invitations(circle_id,user_id) WHERE status='pending';
    CREATE TABLE IF NOT EXISTS circle_posts (
      post_id INTEGER PRIMARY KEY, circle_id INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS circle_posts_circle ON circle_posts(circle_id,post_id);
    CREATE INDEX IF NOT EXISTS circle_members_user ON circle_members(user_id,status);
    CREATE TABLE IF NOT EXISTS circle_events (
      id INTEGER PRIMARY KEY, circle_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
      target_id INTEGER, action TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TRIGGER IF NOT EXISTS circle_post_cleanup AFTER DELETE ON posts
      BEGIN DELETE FROM circle_posts WHERE post_id=OLD.id; END;
    ''')
    for name, declaration in (('rules', "TEXT NOT NULL DEFAULT ''"), ('pinned_post_id', 'INTEGER'), ('public_read', 'INTEGER NOT NULL DEFAULT 0 CHECK(public_read IN (0,1))')):
        if name not in {r[1] for r in db.execute('PRAGMA table_info(circles)')}:
            db.execute('ALTER TABLE circles ADD COLUMN '+name+' '+declaration)
    if 'reason' not in {r[1] for r in db.execute('PRAGMA table_info(circle_events)')}:
        db.execute("ALTER TABLE circle_events ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
    db.execute('CREATE TABLE IF NOT EXISTS circle_reads(circle_id INTEGER NOT NULL,user_id INTEGER NOT NULL,last_post_id INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(circle_id,user_id))')
    db.execute('CREATE TRIGGER IF NOT EXISTS circle_read_cleanup AFTER DELETE ON circles BEGIN DELETE FROM circle_reads WHERE circle_id=OLD.id; END')
    db.execute("CREATE TABLE IF NOT EXISTS circle_post_visibility(post_id INTEGER PRIMARY KEY, audience TEXT NOT NULL DEFAULT 'private' CHECK(audience IN ('public','private')))")
    db.execute('CREATE TRIGGER IF NOT EXISTS circle_visibility_cleanup AFTER DELETE ON posts BEGIN DELETE FROM circle_post_visibility WHERE post_id=OLD.id; END')
    from . import circle_appearance
    circle_appearance.initialize(db)
    db.commit()
    circle_ids.initialize(db)
    circle_names.initialize(db)
    from neonrest import circle_tools
    circle_tools.initialize(db)


@request_lookup
def usable(db, uid):
    if not uid or not ages.ready(db, uid):
        return False
    row = db.execute('SELECT verified FROM users WHERE id=?', (uid,)).fetchone()
    return bool(row and row['verified'] and not db.execute(
        'SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1', (uid,)).fetchone()
        and not db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1', (uid,)).fetchone()
        and not db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1', (uid,)).fetchone())


@request_lookup
def compatible(db, a, b):
    from neonrest.community_features import blocked
    return a == b or (usable(db, a) and usable(db, b)
                      and not blocked(db, a, b) and ages.contact(db, a, b, invitation=True))


@request_lookup
def eligible(db, circle, uid):
    if not usable(db, uid) or not usable(db, circle['owner_id']):
        return False
    if not compatible(db, circle['owner_id'], uid):
        return False
    return circle['mode'] != 'followers' or uid == circle['owner_id'] or bool(db.execute(
        'SELECT 1 FROM follows WHERE follower_id=? AND followed_id=? AND revoked=0',
        (uid, circle['owner_id'])).fetchone())


@request_lookup
def membership(db, circle, uid):
    if circle['archived'] or not eligible(db, circle, uid):
        return None
    return db.execute("SELECT * FROM circle_members WHERE circle_id=? AND user_id=? AND status='active'",
                      (circle['id'], uid)).fetchone()


def invitation(db, cid, uid):
    return db.execute("SELECT * FROM circle_invitations WHERE circle_id=? AND user_id=? AND status='pending' AND expires_at>datetime('now')",
                      (cid, uid)).fetchone()


def public_circle(circle):
    return bool(circle and circle['mode'] == 'discoverable' and circle['public_read'])


@request_lookup
def public_info_allowed(db, circle, uid):
    from neonrest.community_features import member_visible
    return bool(public_circle(circle) and not circle['archived'] and usable(db, circle['owner_id'])
                and member_visible(db, circle['owner_id'], uid)
                and ages.can_read(db, circle['owner_id'], uid, profile=True))


@request_lookup
def public_post(db, pid):
    circle = post_circle(db, pid)
    return bool(public_circle(circle) and db.execute("SELECT 1 FROM circle_post_visibility WHERE post_id=? AND audience='public'", (pid,)).fetchone())


def save_visibility(db, pid, value):
    if value not in (None, '', 'public', 'private'):
        abort(400, description='Choose Public or Private to this Circle.')
    if value == 'public' and not public_circle(post_circle(db, pid)):
        abort(400, description='Only a Public Circle may contain public posts.')
    db.execute("INSERT INTO circle_post_visibility VALUES (?,?) ON CONFLICT(post_id) DO UPDATE SET audience=excluded.audience", (pid, value or 'private'))


@request_lookup
def participate(db, pid, uid):
    circle = post_circle(db, pid)
    return circle is None or bool(membership(db, circle, uid))


@request_lookup
def info_allowed(db, circle, uid):
    if public_info_allowed(db, circle, uid):
        return True
    return not circle['archived'] and eligible(db, circle, uid) and (
        circle['mode'] != 'hidden' or membership(db, circle, uid) or invitation(db, circle['id'], uid))


@request_lookup
def post_circle(db, pid):
    return db.execute('SELECT c.* FROM circles c JOIN circle_posts cp ON cp.circle_id=c.id WHERE cp.post_id=?', (pid,)).fetchone()


@request_lookup
def post_allowed(db, pid, uid, include_removed=False):
    """None means an ordinary post; False denies even an author or site staff."""
    mapping = db.execute('SELECT circle_id FROM circle_posts WHERE post_id=?', (pid,)).fetchone()
    if mapping is None:
        return None
    if not include_removed and db.execute("SELECT 1 FROM circle_content_removals WHERE target_type='post' AND target_id=? AND circle_id=?",(pid,mapping['circle_id'])).fetchone():return False
    circle = db.execute('SELECT * FROM circles WHERE id=?', (mapping['circle_id'],)).fetchone()
    if circle is None:
        return False
    author = db.execute('SELECT user_id FROM posts WHERE id=?', (pid,)).fetchone()
    if author and usable(db, author['user_id']) and public_post(db, pid) and public_info_allowed(db, circle, uid):
        return True  # The common post guard still applies author, age, block and moderation checks.
    if not membership(db, circle, uid):
        return False
    post = db.execute('SELECT user_id FROM posts WHERE id=?', (pid,)).fetchone()
    return bool(post and compatible(db, post['user_id'], uid))


def comment_allowed(db, cid, uid, include_removed=False):
    row = db.execute('SELECT post_id,user_id FROM comments WHERE id=?', (cid,)).fetchone()
    if not row:
        return False
    if not include_removed and db.execute("WITH RECURSIVE ancestors(id,parent_comment_id) AS (SELECT id,parent_comment_id FROM comments WHERE id=? UNION SELECT c.id,c.parent_comment_id FROM comments c JOIN ancestors a ON c.id=a.parent_comment_id) SELECT 1 FROM ancestors a JOIN circle_content_removals r ON r.target_type='comment' AND r.target_id=a.id JOIN circle_posts cp ON cp.post_id=? AND cp.circle_id=r.circle_id",(cid,row['post_id'])).fetchone():return False
    if not participate(db, row['post_id'], uid):
        return False
    access = post_allowed(db, row['post_id'], uid, include_removed=include_removed)
    return access is not False and (access is None or compatible(db, row['user_id'], uid))


def admit_allowed(db, circle, uid):
    if not eligible(db, circle, uid):
        return False
    members = db.execute("SELECT user_id FROM circle_members WHERE circle_id=? AND status='active' AND user_id<>?", (circle['id'], uid)).fetchall()
    return len(members) < 250 and all(compatible(db, uid, row['user_id']) for row in members)


def selected(db, uid, raw):
    if not raw:
        return None
    try:
        cid = raw if isinstance(raw, int) else circle_ids.resolve(db, raw)
    except (ValueError, TypeError):
        abort(404)
    circle = db.execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
    if not circle or not membership(db, circle, uid):
        abort(404)
    return circle


def label(circle):
    number = circle['name_number']
    if number is None or circle['name_key'] != circle_names.key(circle['name']):
        number = circle_names.assign(current_app.extensions['circles_core'].get_db(),circle['id'],circle['name'])
    return f"{circle['name']}#{number:04d}"


def register(app, core):
    app.extensions['circles_core'] = core
    endpoints = {'circle_appearance','circle_cover','circle_page','circle_icon','circle_join','circle_leave','circle_manage','circle_restore','circle_notifications','circle_report','circle_reports'}

    @app.url_value_preprocessor
    def inbound_circle_id(endpoint, values):
        if endpoint not in endpoints or not values:
            return
        if not session.get('user_id') and endpoint not in ('circle_page', 'circle_icon', 'circle_cover'):
            abort(404)
        original = values['circle_id']
        try:
            values['circle_id'] = circle_ids.resolve(core.get_db(), original)
        except ValueError:
            abort(404)
        if not circle_ids.public_ids.TOKEN.fullmatch(original):
            g.legacy_circle_route = (endpoint, dict(values))

    @app.url_defaults
    def outbound_circle_id(endpoint, values):
        if endpoint in endpoints | {'create_post'} and isinstance(values.get('circle_id'), int):
            try:
                values['circle_id'] = circle_ids.public(core.get_db(), values['circle_id'])
            except ValueError:
                values['circle_id'] = 'unavailable'

    @app.after_request
    def canonical_circle_response(response):
        legacy = getattr(g, 'legacy_circle_route', None)
        # Authorize the actual view first. A denied hidden Circle never redirects.
        if legacy and request.method == 'GET' and response.status_code == 200:
            endpoint, values = legacy
            destination = url_for(endpoint, **values)
            if request.query_string:
                destination += '?' + request.query_string.decode('ascii', errors='ignore')
            response = redirect(destination, 302)
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def db():
        return core.get_db()

    def actor():
        uid = session.get('user_id')
        if not usable(db(), uid):
            abort(403, description='Sign in with an active, verified account and complete age settings first.')
        return uid

    def mutation():
        uid = actor()
        helpers = app.extensions['community_auth_helpers']
        helpers['csrf']()
        if db().execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (posting_restricted=1 OR interaction_restricted=1)', (uid,)).fetchone():
            abort(403)
        response = helpers['limited']('circle_changes', 60)
        if response:
            abort(response)
        # Serialize authorization and membership changes, including post submissions.
        db().execute('BEGIN IMMEDIATE')
        return uid

    def circle_for(cid, uid, manage=False, owner=False):
        circle = db().execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
        if not circle or not info_allowed(db(), circle, uid):
            abort(404)
        member = membership(db(), circle, uid)
        if manage and (not member or member['role'] not in ('owner', 'moderator')):
            abort(403)
        if owner and (not member or member['role'] != 'owner'):
            abort(403)
        return circle, member

    def record(cid, uid, action, target=None, reason=""):
        db().execute('INSERT INTO circle_events(circle_id,actor_id,target_id,action,reason) VALUES (?,?,?,?,?)', (cid, uid, target, action, reason))

    def send_notice(cid, target, actor_id, message, management=False):
        from neonrest.community_features import notify
        path = '/circles/'+circle_ids.public(db(), cid)+('/manage' if management else '')
        notify(db(), target, 'circles', message, path, actor_id)

    def rules_field():
        value = request.form.get('rules', '').strip()
        if len(value) > 5000:
            abort(400, description='Keep Circle rules within 5,000 characters.')
        return value

    def fields():
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        mode = request.form.get('mode', '')
        if not 1 <= len(name) <= 60 or len(description) > 2000 or mode not in ('public', 'discoverable', 'hidden', 'followers'):
            abort(400, description='Use a name of 1–60 characters, a description up to 2,000 characters and a listed membership mode.')
        if any(ord(c) < 32 for c in name):
            abort(400, description='Use a name without control characters.')
        return name, description, ('discoverable' if mode == 'public' else mode)

    def save_icon():
        upload = request.files.get('icon')
        if not upload or not upload.filename:
            return None
        data = upload.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            abort(413)
        folder = filename = None
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 16000000:
                    raise ValueError()
                image.load()
                image = image.convert('RGBA')
                image.thumbnail((512, 512))
                image.info.clear()  # Do not carry camera or location metadata into the icon.
                folder = Path(app.instance_path) / 'circle_icons'
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                filename = secrets.token_hex(24) + '.png'
                from .storage_uploads import image as store_image
                store_image(folder / filename, image, 2*1024*1024, 'PNG', 'circle_icons')
                return filename
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            from .resource_errors import discard_files, raise_if_storage_full
            raise_if_storage_full(error)
            abort(400, description='Choose a JPEG, PNG or WebP image up to 5 MB and 16 million pixels.')

    @app.context_processor
    def circle_context():
        def choices():
            uid = session.get('user_id')
            if not uid:
                return []
            rows = db().execute("SELECT c.* FROM circles c JOIN circle_members m ON m.circle_id=c.id WHERE m.user_id=? AND m.status='active' AND c.archived=0 ORDER BY c.name,c.id", (uid,)).fetchall()
            return [c for c in rows if membership(db(), c, uid)]
        return dict(circle_choices=choices, circle_label=label, circle_public_id=lambda cid: circle_ids.public(db(),cid),
                    circle_for_post=lambda pid: post_circle(db(), pid),
                    circle_is_public=public_circle, circle_post_public=lambda pid: public_post(db(), pid),
                    circle_can_participate=lambda pid: participate(db(), pid, session.get('user_id')))

    @app.route('/circles', methods=['GET', 'POST'])
    def circles_home():
        if request.method == 'GET' and not session.get('user_id'):
            rows = db().execute('SELECT * FROM circles WHERE public_read=1 AND archived=0 ORDER BY name,id').fetchall()
            return render_template('circles.html', mine=[], discover=[c for c in rows if public_info_allowed(db(), c, None)], invitations=[], archived=[], pending=[], unread={})
        if not session.get('user_id'):
            return redirect(url_for('login'))
        uid = actor()
        if request.method == 'POST':
            uid = mutation()
            name, description, mode = fields()
            if db().execute("SELECT COUNT(*) FROM circles WHERE owner_id=? AND created_at>datetime('now','-1 day')", (uid,)).fetchone()[0] >= 5:
                abort(429, description='You can create up to five Circles per day.')
            icon = save_icon()
            cid = db().execute('INSERT INTO circles(name,description,owner_id,mode,icon,rules) VALUES (?,?,?,?,?,?)', (name, description, uid, mode, icon, rules_field())).lastrowid
            db().execute('UPDATE circles SET public_read=? WHERE id=?', (int(request.form.get('mode') == 'public'), cid))
            circle_ids.ensure(db(), cid)
            circle_names.assign(db(), cid, name)
            db().execute("INSERT INTO circle_members VALUES (?,?,'owner','active',CURRENT_TIMESTAMP)", (cid, uid))
            record(cid, uid, 'created')
            db().commit()
            return redirect(url_for('circle_page', circle_id=cid))
        rows = db().execute('SELECT * FROM circles WHERE archived=0 ORDER BY name,id').fetchall()
        mine, discover, invites, pending = [], [], [], []
        unread = {}
        for c in rows:
            if membership(db(), c, uid):
                mine.append(c)
                unread[c['id']] = db().execute("SELECT COUNT(*) FROM circle_posts cp JOIN posts p ON p.id=cp.post_id WHERE cp.circle_id=? AND p.id>COALESCE((SELECT last_post_id FROM circle_reads WHERE circle_id=? AND user_id=?),0) AND p.user_id<>? AND community_post_visible(p.id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id)", (c['id'],c['id'],uid,uid)).fetchone()[0]
            elif info_allowed(db(), c, uid):
                if invitation(db(), c['id'], uid):
                    invites.append(c)
                elif db().execute("SELECT 1 FROM circle_members WHERE circle_id=? AND user_id=? AND status='pending'", (c['id'],uid)).fetchone():
                    pending.append(c)
                elif c['mode'] != 'hidden':
                    discover.append(c)
        archived = db().execute('SELECT * FROM circles WHERE archived=1 AND owner_id=? ORDER BY name,id', (uid,)).fetchall()
        return render_template('circles.html', mine=mine, discover=discover, invitations=invites, archived=archived, pending=pending, unread=unread)

    @app.route('/circles/<string:circle_id>')
    def circle_page(circle_id):
        uid = session.get('user_id')
        circle, member = circle_for(circle_id, uid)
        context = dict(circle=circle, membership=member,
                       invitation=invitation(db(), circle_id, uid),
                       my_request=db().execute('SELECT status FROM circle_members WHERE circle_id=? AND user_id=?', (circle_id, uid)).fetchone())
        if not member and not public_info_allowed(db(), circle, uid):
            return render_template('circle_page.html', **context)
        members = db().execute("SELECT m.*,u.handle FROM circle_members m JOIN users u ON u.id=m.user_id WHERE m.circle_id=? AND m.status='active' ORDER BY m.role,u.handle", (circle_id,)).fetchall()
        context['members'] = [m for m in members if compatible(db(), uid, m['user_id'])] if member else []
        response = core.feed(circle_context=context)
        if member and request.args.get('page', '1') == '1' and not request.args.get('q', '').strip():
            newest = db().execute("SELECT COALESCE(MAX(p.id),0) FROM posts p JOIN circle_posts cp ON cp.post_id=p.id WHERE cp.circle_id=? AND community_post_visible(p.id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id)", (circle_id,)).fetchone()[0]
            db().execute('INSERT INTO circle_reads VALUES (?,?,?) ON CONFLICT(circle_id,user_id) DO UPDATE SET last_post_id=MAX(last_post_id,excluded.last_post_id)', (circle_id,uid,newest))
            db().commit()
        return response

    @app.route('/circles/<string:circle_id>/restore', methods=['POST'])
    def circle_restore(circle_id):
        uid = mutation()
        circle = db().execute('SELECT * FROM circles WHERE id=? AND archived=1 AND owner_id=?', (circle_id, uid)).fetchone()
        if not circle:
            abort(404)
        db().execute('UPDATE circles SET archived=0 WHERE id=?', (circle_id,))
        record(circle_id, uid, 'restored')
        db().commit()
        flash('Circle restored. Previous eligible memberships are active again; revoked invitations remain revoked.', 'success')
        return redirect(url_for('circle_page', circle_id=circle_id))

    @app.route('/circles/<string:circle_id>/icon')
    def circle_icon(circle_id):
        circle, _ = circle_for(circle_id, session.get('user_id'))
        if not circle['icon']:
            abort(404)
        response = send_file(Path(app.instance_path) / 'circle_icons' / circle['icon'], mimetype='image/png')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.route('/circles/<string:circle_id>/join', methods=['POST'])
    def circle_join(circle_id):
        uid = mutation()
        circle, member = circle_for(circle_id, uid)
        if member:
            return redirect(url_for('circle_page', circle_id=circle_id))
        invite = invitation(db(), circle_id, uid)
        if not invite and db().execute("SELECT 1 FROM circle_members WHERE circle_id=? AND user_id=? AND status='pending'", (circle_id,uid)).fetchone():
            return redirect(url_for('circle_page', circle_id=circle_id))
        prior = db().execute('SELECT status FROM circle_members WHERE circle_id=? AND user_id=?', (circle_id, uid)).fetchone()
        if (circle['mode'] == 'hidden' or prior and prior['status'] == 'removed') and not invite:
            abort(403, description='An invitation is required to join this Circle.')
        if not admit_allowed(db(), circle, uid):
            abort(403, description='Membership is unavailable under the current account and contact safeguards.')
        status = 'active' if invite else 'pending'
        db().execute("INSERT INTO circle_members VALUES (?,?,'member',?,CURRENT_TIMESTAMP) ON CONFLICT(circle_id,user_id) DO UPDATE SET role='member',status=excluded.status,joined_at=excluded.joined_at", (circle_id, uid, status))
        if invite:
            db().execute("UPDATE circle_invitations SET status='accepted' WHERE id=?", (invite['id'],))
        record(circle_id, uid, 'invitation_accepted' if invite else 'join_requested')
        if invite:
            send_notice(circle_id, invite['invited_by'], uid, 'A member accepted your Circle invitation.')
        else:
            for manager in db().execute("SELECT user_id FROM circle_members WHERE circle_id=? AND status='active' AND role IN ('owner','moderator')", (circle_id,)).fetchall():
                send_notice(circle_id, manager['user_id'], uid, 'A Circle membership request is waiting for review.', True)
        db().commit()
        flash('You joined the Circle.' if invite else 'Your join request is awaiting approval.', 'success')
        return redirect(url_for('circle_page', circle_id=circle_id))

    @app.route('/circles/<string:circle_id>/leave', methods=['POST'])
    def circle_leave(circle_id):
        uid = mutation()
        circle, member = circle_for(circle_id, uid)
        if member and member['role'] == 'owner':
            abort(400, description='Transfer ownership before leaving, or archive the Circle.')
        db().execute("UPDATE circle_members SET status='left' WHERE circle_id=? AND user_id=?", (circle_id, uid))
        db().execute("UPDATE circle_invitations SET status='declined' WHERE circle_id=? AND user_id=? AND status='pending'", (circle_id, uid))
        record(circle_id, uid, 'left_or_declined')
        db().commit()
        return redirect(url_for('circles_home'))

    @app.route('/circles/<string:circle_id>/manage', methods=['GET', 'POST'])
    def circle_manage(circle_id):
        uid = mutation() if request.method == 'POST' else actor()
        circle, member = circle_for(circle_id, uid, manage=True)
        if request.method == 'POST':
            action = request.form.get('action')
            if action in ('settings', 'archive'):
                if member['role'] != 'owner':
                    abort(403)
                if action == 'archive':
                    db().execute('UPDATE circles SET archived=1 WHERE id=?', (circle_id,))
                    db().execute("UPDATE circle_invitations SET status='revoked' WHERE circle_id=? AND status='pending'", (circle_id,))
                else:
                    name, description, mode = fields()
                    # Mode changes could silently revoke follower-only memberships.
                    if mode != circle['mode']:
                        abort(400, description='Membership mode is fixed for this first version. Create a separate Circle for another mode.')
                    public_read = int(mode == 'discoverable' and request.form.get('mode') == 'public')
                    if public_read != circle['public_read']:
                        record(circle_id, uid, 'public_viewing_enabled' if public_read else 'public_viewing_disabled')
                    db().execute('UPDATE circles SET public_read=? WHERE id=?', (public_read, circle_id))
                    icon = save_icon()
                    db().execute('UPDATE circles SET name=?,description=?,icon=COALESCE(?,icon),rules=? WHERE id=?', (name, description, icon, rules_field(), circle_id))
                    circle_names.assign(db(), circle_id, name)
                record(circle_id, uid, action)
            elif action == 'pin':
                value = request.form.get('post_id', '').strip()
                pid = None
                if value:
                    try:
                        pid = core.identifiers.resolve(db(), 'post', value)
                    except ValueError:
                        abort(400, description='Enter the public post ID from a post in this Circle.')
                    if not db().execute('SELECT 1 FROM circle_posts WHERE circle_id=? AND post_id=? AND community_post_visible(post_id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts WHERE post_id=?)', (circle_id,pid,pid)).fetchone():
                        abort(400, description='Choose a visible post belonging to this Circle.')
                db().execute('UPDATE circles SET pinned_post_id=? WHERE id=?', (pid,circle_id))
                record(circle_id, uid, 'pinned_post_updated')
            elif action == 'invite':
                handle = request.form.get('handle', '').strip().lstrip('@')
                target = db().execute("SELECT id FROM users WHERE lower(ltrim(handle,'@'))=lower(?)", (handle,)).fetchone()
                if not target or not admit_allowed(db(), circle, target['id']):
                    abort(400, description='An invitation cannot be issued to that account under the current contact safeguards.')
                tid = target['id']
                from neonrest.community_features import settings, friends
                preference = settings(db(), tid)['requests_from']
                if preference == 'nobody' or preference == 'friends' and not (friends(db(), uid, tid) or ages.family(db(), uid, tid)):
                    abort(403, description='This account is not accepting invitations from you.')
                if membership(db(), circle, tid):
                    abort(400, description='That person is already a member.')
                expires = (datetime.now(timezone.utc) + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
                db().execute("UPDATE circle_invitations SET status='revoked' WHERE circle_id=? AND user_id=? AND status='pending'", (circle_id, tid))
                db().execute('INSERT INTO circle_invitations(circle_id,user_id,invited_by,expires_at) VALUES (?,?,?,?)', (circle_id, tid, uid, expires))
                record(circle_id, uid, 'invited', tid)
                send_notice(circle_id, tid, uid, 'You have a Circle invitation. Open it to review the rules and choose whether to join.')
            elif action == 'revoke_invite':
                iid = request.form.get('invitation_id', type=int)
                db().execute("UPDATE circle_invitations SET status='revoked' WHERE id=? AND circle_id=? AND status='pending'", (iid, circle_id))
                record(circle_id, uid, 'invitation_revoked')
            elif action in ('approve', 'decline', 'remove', 'moderator', 'member', 'transfer'):
                reason = request.form.get('reason', '').strip()
                if len(reason) > 1000 or action == 'remove' and not reason:
                    abort(400, description='A reason is required for removing a member. Optional reasons must stay within 1,000 characters.')
                tid = request.form.get('user_id', type=int)
                target = db().execute('SELECT * FROM circle_members WHERE circle_id=? AND user_id=?', (circle_id, tid)).fetchone()
                if not target or tid == uid or target['role'] == 'owner':
                    abort(400, description='Choose another eligible member or pending request.')
                if member['role'] != 'owner' and (target['role'] != 'member' or action not in ('approve', 'decline', 'remove')):
                    abort(403)
                if action in ('approve', 'decline') and target['status'] != 'pending':
                    abort(409)
                if action in ('moderator', 'member', 'transfer', 'remove') and target['status'] != 'active':
                    abort(409)
                if action in ('approve', 'transfer') and not admit_allowed(db(), circle, tid):
                    abort(403, description='Current contact safeguards prevent this membership change.')
                if action == 'transfer':
                    # Followers mode depends on the owner; avoid changing its meaning.
                    if circle['mode'] == 'followers':
                        abort(400, description='Ownership transfer is unavailable for follower-only Circles.')
                    db().execute('UPDATE circles SET owner_id=? WHERE id=?', (tid, circle_id))
                    db().execute("UPDATE circle_members SET role='member' WHERE circle_id=? AND user_id=?", (circle_id, uid))
                    db().execute("UPDATE circle_members SET role='owner' WHERE circle_id=? AND user_id=?", (circle_id, tid))
                elif action in ('moderator', 'member'):
                    db().execute('UPDATE circle_members SET role=? WHERE circle_id=? AND user_id=?', (action, circle_id, tid))
                else:
                    status = {'approve': 'active', 'decline': 'declined', 'remove': 'removed'}[action]
                    db().execute('UPDATE circle_members SET status=?,joined_at=CURRENT_TIMESTAMP WHERE circle_id=? AND user_id=?', (status, circle_id, tid))
                    if action == 'remove':
                        db().execute("UPDATE circle_invitations SET status='revoked' WHERE circle_id=? AND user_id=? AND status='pending'", (circle_id, tid))
                record(circle_id, uid, action, tid, reason)
                if action == 'approve':
                    send_notice(circle_id, tid, uid, 'Your Circle membership request was approved.')
            else:
                abort(400)
            db().commit()
            flash('Circle updated.', 'success')
            return redirect(url_for('circles_home') if action in ('archive', 'transfer') else url_for('circle_manage', circle_id=circle_id))
        people = db().execute("SELECT m.*,u.handle FROM circle_members m JOIN users u ON u.id=m.user_id WHERE circle_id=? AND status IN ('active','pending') ORDER BY status,role,u.handle", (circle_id,)).fetchall()
        invites = db().execute("SELECT i.*,u.handle FROM circle_invitations i JOIN users u ON u.id=i.user_id WHERE circle_id=? AND status='pending' AND expires_at>datetime('now')", (circle_id,)).fetchall()
        member_query = request.args.get('member_q', '').strip()[:100]
        if member_query:
            people = [person for person in people if member_query.casefold() in person['handle'].casefold()]
        events = db().execute('SELECT e.*,u.handle AS actor_handle,t.handle AS target_handle FROM circle_events e LEFT JOIN users u ON u.id=e.actor_id LEFT JOIN users t ON t.id=e.target_id WHERE e.circle_id=? ORDER BY e.id DESC LIMIT 30', (circle_id,)).fetchall()
        pinned = db().execute('SELECT p.id,p.content FROM posts p JOIN circle_posts cp ON cp.post_id=p.id WHERE cp.circle_id=? AND p.id=? AND community_post_visible(p.id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts WHERE post_id=p.id)', (circle_id,circle['pinned_post_id'])).fetchone()
        return render_template('circle_manage.html', circle=circle, membership=member, people=people, invitations=invites, member_query=member_query, events=events, pinned=pinned)

    from neonrest import circle_tools
    circle_tools.register(app,core,circle_for,actor,mutation,record)
    from . import circle_appearance
    circle_appearance.register(app,core,circle_for,actor,mutation,record)
