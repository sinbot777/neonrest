"""T25 page identities. Personal logins remain users; pages never gain a login.

Business activation needs the separately reviewed subscription provider
integration. Page posting preserves both actor and owner eligibility.
"""
import re
import json
import secrets
import sqlite3
import time

PREFIXES = {'creative': '_', 'business': '$'}
ROLES = ('editor', 'manager')
SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{2,29}', re.ASCII)


class PageError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def handle(kind, value):
    """Canonicalize only within the requested namespace; never strip @ or $."""
    if kind not in PREFIXES or not isinstance(value, str):
        raise PageError('Choose a creative or business page.')
    value = value.strip()
    prefix = PREFIXES[kind]
    if value.startswith(prefix):
        value = value[1:]
    value = value.lower()
    if not SLUG.fullmatch(value):
        raise PageError('Use 3–30 letters, numbers, underscores or hyphens, starting with a letter or number.')
    return prefix + value


def initialize(db):
    statements = [
        '''CREATE TABLE IF NOT EXISTS identity_pages(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('creative','business')),
            handle TEXT NOT NULL COLLATE NOCASE UNIQUE,
            owner_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','published','archived')),
            revision INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            CHECK((kind='creative' AND substr(handle,1,1)='_') OR
                  (kind='business' AND substr(handle,1,1)='$')))''',
        '''CREATE TABLE IF NOT EXISTS identity_page_members(
            page_id TEXT NOT NULL REFERENCES identity_pages(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            role TEXT NOT NULL CHECK(role IN ('editor','manager')),
            PRIMARY KEY(page_id,user_id))''',
        '''CREATE TABLE IF NOT EXISTS identity_page_events(
            id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES identity_pages(id),
            actor_id INTEGER NOT NULL REFERENCES users(id),
            action TEXT NOT NULL, created_at INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS identity_page_posts(
            id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES identity_pages(id),
            author_id INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
            removed INTEGER NOT NULL DEFAULT 0 CHECK(removed IN (0,1)),
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS identity_page_reports(
            id INTEGER PRIMARY KEY, page_id TEXT NOT NULL REFERENCES identity_pages(id),
            post_id INTEGER NOT NULL DEFAULT 0, reporter_id INTEGER NOT NULL REFERENCES users(id),
            reason TEXT NOT NULL, snapshot TEXT NOT NULL, created_at INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
            reviewed_by INTEGER, decision TEXT, decision_reason TEXT, reviewed_at INTEGER)''',
        '''CREATE TABLE IF NOT EXISTS identity_page_hides(
            page_id TEXT NOT NULL REFERENCES identity_pages(id), post_id INTEGER NOT NULL DEFAULT 0,
            actor_id INTEGER NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY(page_id,post_id))''',
        '''CREATE TABLE IF NOT EXISTS identity_page_reviews(
            id INTEGER PRIMARY KEY,report_id INTEGER NOT NULL REFERENCES identity_page_reports(id),
            actor_id INTEGER NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL)''',
        '''CREATE UNIQUE INDEX IF NOT EXISTS identity_page_report_open
            ON identity_page_reports(page_id,post_id,reporter_id) WHERE status='open' ''',
        'CREATE INDEX IF NOT EXISTS identity_page_reports_queue ON identity_page_reports(status,id DESC)',
        '''CREATE TRIGGER IF NOT EXISTS identity_page_report_snapshot_immutable
            BEFORE UPDATE OF snapshot,page_id,post_id,reporter_id,reason,created_at ON identity_page_reports
            BEGIN SELECT RAISE(ABORT,'Report evidence is immutable'); END''',
        'CREATE INDEX IF NOT EXISTS identity_page_owner ON identity_pages(owner_id,id)',
        'CREATE INDEX IF NOT EXISTS identity_page_member ON identity_page_members(user_id,page_id)',
        'CREATE INDEX IF NOT EXISTS identity_page_history ON identity_page_events(page_id,id)',
        'CREATE INDEX IF NOT EXISTS identity_page_post_list ON identity_page_posts(page_id,id DESC)',
    ]
    # No executescript/commit: the caller owns the startup transaction.
    for statement in statements:
        db.execute(statement)


def account_eligible(db, uid, kind, age, ready):
    """Trusted age callbacks are the site's existing birthday/consent policy."""
    if kind not in PREFIXES or not isinstance(uid, int) or isinstance(uid, bool):
        return False
    user = db.execute('SELECT handle,verified FROM users WHERE id=?', (uid,)).fetchone()
    if not user or not user['verified'] or not (user['handle'] or '').startswith('@'):
        return False
    if db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1', (uid,)).fetchone():
        return False
    if db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1', (uid,)).fetchone():
        return False
    if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (banned=1 OR posting_restricted=1)', (uid,)).fetchone():
        return False
    years = age(db, uid)
    return bool(ready(db, uid) and years is not None and (kind == 'creative' or years >= 18))


def eligible(db, uid, kind):
    from . import age_policy
    return account_eligible(db, uid, kind, age_policy.age, age_policy.ready)


def require_eligible(db, uid, kind):
    if not eligible(db, uid, kind):
        raise PageError('Your account is not eligible to manage this type of page.', 403)


def get(db, page_id):
    page = db.execute('SELECT * FROM identity_pages WHERE id=?', (page_id,)).fetchone()
    if not page:
        raise PageError('Page unavailable.', 404)
    return page


def role(db, page, uid):
    if not eligible(db, uid, page['kind']):
        return None
    if page['owner_id'] == uid:
        return 'owner'
    if not eligible(db, page['owner_id'], page['kind']):
        return None
    from .community_features import blocked
    from . import age_policy
    if blocked(db, page['owner_id'], uid) or not age_policy.contact(db, page['owner_id'], uid):
        return None
    member = db.execute('SELECT role FROM identity_page_members WHERE page_id=? AND user_id=?',
        (page['id'], uid)).fetchone()
    return member['role'] if member else None


def require_role(db, page, uid, allowed):
    if role(db, page, uid) not in allowed:
        raise PageError('You do not have permission to change this page.', 403)


def fields(name, description):
    if not isinstance(name, str) or not isinstance(description, str):
        raise PageError('Enter a page name and description.')
    name, description = name.strip(), description.strip()
    if not 1 <= len(name) <= 80 or len(description) > 4000:
        raise PageError('Use a name up to 80 characters and description up to 4,000 characters.')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in name + description):
        raise PageError('Remove control characters from page text.')
    return name, description


def event(db, page_id, uid, action):
    db.execute('INSERT INTO identity_page_events(page_id,actor_id,action,created_at) VALUES (?,?,?,?)',
        (page_id, uid, action, int(time.time())))


def create(db, uid, kind, requested_handle, name, description=''):
    require_eligible(db, uid, kind)
    canonical = handle(kind, requested_handle)
    name, description = fields(name, description)
    # Bound resource use without introducing a billing tier.
    if db.execute('SELECT COUNT(*) FROM identity_pages WHERE owner_id=?', (uid,)).fetchone()[0] >= 20:
        raise PageError('The initial limit is 20 owned pages.', 409)
    page_id, now = secrets.token_urlsafe(16), int(time.time())
    try:
        db.execute('''INSERT INTO identity_pages(id,kind,handle,owner_id,name,description,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)''', (page_id, kind, canonical, uid, name, description, now, now))
    except sqlite3.IntegrityError as exc:
        raise PageError('That page handle is unavailable.', 409) from exc
    event(db, page_id, uid, 'create')
    return page_id


def edit(db, uid, page_id, revision, name, description):
    page = get(db, page_id)
    require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] == 'archived':
        raise PageError('Restore the page before editing.', 409)
    name, description = fields(name, description)
    result = db.execute('''UPDATE identity_pages SET name=?,description=?,revision=revision+1,updated_at=?
        WHERE id=? AND revision=?''', (name, description, int(time.time()), page_id, revision))
    if result.rowcount != 1:
        raise PageError('This page changed. Reload before saving.', 409)
    event(db, page_id, uid, 'edit')


def set_state(db, uid, page_id, revision, state):
    page = get(db, page_id)
    require_role(db, page, uid, ('owner',))
    if state not in ('draft', 'published', 'archived'):
        raise PageError('Choose a valid page state.')
    if state == 'published' and page['kind'] == 'business':
        # No client form, staff checkbox or forged checkout return can activate it.
        # Replace only when provider-verified recurring entitlement is implemented.
        raise PageError('Business activation awaits subscription setup.', 409)
    if state == 'published' and hidden(db, page_id):
        raise PageError('Staff must clear the page restriction before publishing.', 409)
    result = db.execute('''UPDATE identity_pages SET state=?,revision=revision+1,updated_at=?
        WHERE id=? AND revision=?''', (state, int(time.time()), page_id, revision))
    if result.rowcount != 1:
        raise PageError('This page changed. Reload before saving.', 409)
    event(db, page_id, uid, 'state:' + state)


def set_member(db, uid, page_id, member_id, member_role):
    page = get(db, page_id)
    require_role(db, page, uid, ('owner',))
    if member_id == page['owner_id']:
        raise PageError('The owner cannot be replaced with a delegate.')
    if member_role is None:
        db.execute('DELETE FROM identity_page_members WHERE page_id=? AND user_id=?', (page_id, member_id))
    else:
        if member_role not in ROLES:
            raise PageError('Choose editor or manager.')
        require_eligible(db, member_id, page['kind'])
        from . import age_policy
        from .community_features import blocked
        if blocked(db, uid, member_id) or not age_policy.contact(db, uid, member_id):
            raise PageError('Current age and contact permissions do not permit this delegate.', 403)
        if db.execute('SELECT COUNT(*) FROM identity_page_members WHERE page_id=?', (page_id,)).fetchone()[0] >= 20:
            raise PageError('The initial limit is 20 delegates.', 409)
        db.execute('''INSERT INTO identity_page_members(page_id,user_id,role) VALUES (?,?,?)
            ON CONFLICT(page_id,user_id) DO UPDATE SET role=excluded.role''', (page_id, member_id, member_role))
    event(db, page_id, uid, 'delegate:remove' if member_role is None else 'delegate:' + member_role)


def visible(db, page, viewer):
    if not eligible(db, page['owner_id'], page['kind']):
        return False
    if role(db, page, viewer):
        return True
    if hidden(db, page['id']):
        return False
    if page['state'] != 'published' or page['kind'] == 'business':
        return False
    from . import age_policy
    from .community_features import blocked
    # A creative identity does not erase the owner's age or a block.
    return not blocked(db, page['owner_id'], viewer) and age_policy.can_read(db, page['owner_id'], viewer)


def export_user(db, uid):
    return {
        'owned_pages': [dict(r) for r in db.execute('SELECT * FROM identity_pages WHERE owner_id=? ORDER BY id', (uid,))],
        'delegations': [dict(r) for r in db.execute('SELECT * FROM identity_page_members WHERE user_id=? ORDER BY page_id', (uid,))],
        'own_actions': [dict(r) for r in db.execute('SELECT * FROM identity_page_events WHERE actor_id=? ORDER BY id', (uid,))],
        'own_page_posts': [dict(r) for r in db.execute('SELECT * FROM identity_page_posts WHERE author_id=? ORDER BY id', (uid,))],
        # Do not export staff-only snapshots or another reporter's identity.
        'own_reports': [dict(r) for r in db.execute('''SELECT id,page_id,post_id,reason,created_at,status,
            decision,decision_reason,reviewed_at FROM identity_page_reports WHERE reporter_id=? ORDER BY id''', (uid,))],
    }


def write_post(db, uid, page_id, body):
    page = get(db, page_id)
    require_role(db, page, uid, ('owner', 'manager', 'editor'))
    if page['state'] != 'published' or page['kind'] != 'creative':
        raise PageError('Publish a creative page before adding updates.', 409)
    if hidden(db, page_id):
        raise PageError('This page is restricted by staff.', 403)
    body = body.strip() if isinstance(body, str) else ''
    if not 1 <= len(body) <= 5000:
        raise PageError('Write an update of 1–5,000 characters.')
    now = int(time.time())
    result = db.execute('''INSERT INTO identity_page_posts(page_id,author_id,body,created_at,updated_at)
        VALUES (?,?,?,?,?)''', (page_id, uid, body, now, now))
    event(db, page_id, uid, 'post:create:' + str(result.lastrowid))
    return result.lastrowid


def remove_post(db, uid, page_id, post_id):
    page = get(db, page_id)
    require_role(db, page, uid, ('owner', 'manager', 'editor'))
    post = db.execute('SELECT * FROM identity_page_posts WHERE id=? AND page_id=?', (post_id, page_id)).fetchone()
    if not post:
        raise PageError('Update unavailable.', 404)
    if uid != post['author_id'] and uid != page['owner_id']:
        raise PageError('Only the author or page owner can remove this update.', 403)
    db.execute('UPDATE identity_page_posts SET removed=1,revision=revision+1,updated_at=? WHERE id=?',
        (int(time.time()), post_id))
    event(db, page_id, uid, 'post:remove:' + str(post_id))


def post_visible(db, page, post, viewer):
    if post['removed'] or hidden(db, page['id'], post['id']) or not visible(db, page, viewer):
        return False
    if not eligible(db, post['author_id'], page['kind']):
        return False
    from . import age_policy
    from .community_features import blocked
    return not blocked(db, post['author_id'], viewer) and age_policy.can_read(db, post['author_id'], viewer)


def erasure_dependencies(db, uid):
    """Do not orphan page ownership, authorship or audit records on account loss.

    Erasure remains disabled globally. Release this dependency only after the
    page transfer/disposal and billing cancellation policies are implemented.
    """
    return any(db.execute(sql, (uid,)).fetchone() for sql in (
        'SELECT 1 FROM identity_pages WHERE owner_id=? LIMIT 1',
        'SELECT 1 FROM identity_page_members WHERE user_id=? LIMIT 1',
        'SELECT 1 FROM identity_page_posts WHERE author_id=? LIMIT 1',
        'SELECT 1 FROM identity_page_events WHERE actor_id=? LIMIT 1',
        'SELECT 1 FROM identity_page_reports WHERE reporter_id=? LIMIT 1',
        'SELECT 1 FROM identity_page_reports WHERE reviewed_by=? LIMIT 1',
        'SELECT 1 FROM identity_page_reviews WHERE actor_id=? LIMIT 1'))


def hidden(db, page_id, post_id=0):
    return bool(db.execute('SELECT 1 FROM identity_page_hides WHERE page_id=? AND post_id=?', (page_id, post_id)).fetchone())


def report(db, uid, page_id, post_id, reason):
    page = get(db, page_id)
    require_eligible(db, uid, 'creative')
    from . import age_policy
    from .community_features import blocked
    if page['state'] != 'published' or hidden(db, page_id) or blocked(db, page['owner_id'], uid) or not age_policy.can_read(db, page['owner_id'], uid):
        raise PageError('Page unavailable.', 404)
    if not isinstance(post_id, int) or not 0 <= post_id < 2**63:
        raise PageError('Update unavailable.', 404)
    snapshot = {'handle': page['handle'], 'name': page['name'], 'description': page['description'], 'owner_id': page['owner_id']}
    if post_id:
        post = db.execute('SELECT * FROM identity_page_posts WHERE id=? AND page_id=?', (post_id, page_id)).fetchone()
        if not post or not post_visible(db, page, post, uid):
            raise PageError('Update unavailable.', 404)
        snapshot['post'] = dict(post)
    reason = reason.strip() if isinstance(reason, str) else ''
    if not 1 <= len(reason) <= 1000:
        raise PageError('Describe the concern in up to 1,000 characters.')
    existing = db.execute("SELECT id FROM identity_page_reports WHERE page_id=? AND post_id=? AND reporter_id=? AND status='open'", (page_id, post_id, uid)).fetchone()
    if existing:
        return existing['id']
    result = db.execute('''INSERT INTO identity_page_reports(page_id,post_id,reporter_id,reason,snapshot,created_at)
        VALUES (?,?,?,?,?,?)''', (page_id, post_id, uid, reason, json.dumps(snapshot, ensure_ascii=False), int(time.time())))
    return result.lastrowid


def review_report(db, staff_id, report_id, decision, reason):
    # Only call after require_staff_permission + staff factor/fresh-auth + CSRF.
    row = db.execute('SELECT * FROM identity_page_reports WHERE id=?', (report_id,)).fetchone()
    if not row:
        raise PageError('Report unavailable.', 404)
    reason = reason.strip() if isinstance(reason, str) else ''
    if decision not in ('hide-page','hide-update','restore-page','restore-update','dismiss') or not 1 <= len(reason) <= 1000:
        raise PageError('Choose a decision and record a reason of up to 1,000 characters.')
    if decision.endswith('update') and not row['post_id']:
        raise PageError('This report does not identify an update.')
    target = row['post_id'] if decision.endswith('update') else 0
    now = int(time.time())
    if decision.startswith('hide-'):
        db.execute('''INSERT INTO identity_page_hides VALUES (?,?,?,?,?)
            ON CONFLICT(page_id,post_id) DO UPDATE SET actor_id=excluded.actor_id,reason=excluded.reason,created_at=excluded.created_at''',
            (row['page_id'], target, staff_id, reason, now))
    elif decision.startswith('restore-'):
        db.execute('DELETE FROM identity_page_hides WHERE page_id=? AND post_id=?', (row['page_id'], target))
    db.execute("UPDATE identity_page_reports SET status='closed',reviewed_by=?,decision=?,decision_reason=?,reviewed_at=? WHERE id=?", (staff_id, decision, reason, now, report_id))
    db.execute('INSERT INTO identity_page_reviews(report_id,actor_id,decision,reason,created_at) VALUES (?,?,?,?,?)', (report_id, staff_id, decision, reason, now))
    event(db, row['page_id'], staff_id, 'staff:' + decision + ':' + str(report_id))


def register(app, core):
    """Register after community/age initialization."""
    from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
    bp = Blueprint('identity_pages', __name__)
    with app.app_context():
        initialize(core.get_db())
        core.get_db().commit()

    @bp.errorhandler(PageError)
    def page_error(error):
        return render_template('identity_page_error.html', message=str(error)), error.status

    def actor():
        uid = session.get('user_id')
        if not isinstance(uid, int) or isinstance(uid, bool):
            abort(401)
        return uid

    def writing():
        actor()
        helpers = app.extensions['community_auth_helpers']
        helpers['csrf']()
        if not helpers['fresh']():
            return redirect(url_for('community_reauth', next=request.path))
        return None

    def revision():
        value = request.form.get('revision', type=int)
        if value is None or value < 0:
            raise PageError('Reload the page before saving.', 409)
        return value

    def page_url(page):
        endpoint = 'identity_pages.creative' if page['kind'] == 'creative' else 'identity_pages.business'
        return url_for(endpoint, slug=page['handle'][1:])

    def staff_actor(permission):
        uid = core.require_staff_permission(permission)
        safety = core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?', (uid,)).fetchone()
        if not safety or not safety['totp_secret']:
            return uid, redirect(url_for('community_security'))
        if not app.extensions['community_auth_helpers']['fresh']():
            return uid, redirect(url_for('community_reauth', next=request.path))
        return uid, None

    @bp.route('/pages/<page_id>/report', methods=['GET','POST'])
    def report_page(page_id):
        uid = actor()
        db = core.get_db()
        page = get(db, page_id)
        if not visible(db, page, uid) or page['state'] != 'published':
            abort(404)
        post_id = request.values.get('post_id', 0, type=int)
        if post_id is None or not 0 <= post_id < 2**63:
            abort(404)
        if request.method == 'POST':
            app.extensions['community_auth_helpers']['csrf']()
            limit = app.extensions['community_auth_helpers']['limited']('page-report', 15)
            if limit is not None:
                return limit
            with db:
                db.execute('BEGIN IMMEDIATE')
                report(db, uid, page_id, post_id, request.form.get('reason',''))
            flash('Report sent to staff. Your identity is not shown to the page owner.', 'success')
            return redirect(url_for('identity_pages.my_reports'))
        return render_template('identity_page_report.html', page=page, post_id=post_id)

    @bp.get('/pages/reports/mine')
    def my_reports():
        uid = actor()
        rows = core.get_db().execute('''SELECT id,reason,status,decision,decision_reason,created_at
            FROM identity_page_reports WHERE reporter_id=? ORDER BY id DESC LIMIT 100''', (uid,)).fetchall()
        return render_template('identity_page_reports.html', reports=rows, staff=False)

    @bp.route('/manage/pages/reports', methods=['GET','POST'])
    def review_reports():
        uid, response = staff_actor('review_reports')
        if response is not None:
            return response
        db = core.get_db()
        if request.method == 'POST':
            core.require_staff_permission('moderate_posts')
            app.extensions['community_auth_helpers']['csrf']()
            report_id = request.form.get('report_id', type=int)
            if report_id is None or not 0 < report_id < 2**63:
                abort(400)
            with db:
                db.execute('BEGIN IMMEDIATE')
                review_report(db, uid, report_id, request.form.get('decision'), request.form.get('reason'))
            flash('Page report reviewed. The decision is recorded.', 'success')
            return redirect(url_for('identity_pages.review_reports'))
        before = request.args.get('before', 2**63-1, type=int)
        if before is None or not 0 < before < 2**63:
            abort(400)
        rows = db.execute('SELECT * FROM identity_page_reports WHERE id<? ORDER BY id DESC LIMIT 51', (before,)).fetchall()
        return render_template('identity_page_reports.html', reports=rows[:50], staff=True,
            older_url=url_for('identity_pages.review_reports', before=rows[49]['id']) if len(rows)>50 else None)

    @bp.get('/pages')
    def mine():
        uid = actor()
        db = core.get_db()
        rows = db.execute('''SELECT DISTINCT p.* FROM identity_pages p
            LEFT JOIN identity_page_members m ON m.page_id=p.id
            WHERE p.owner_id=? OR m.user_id=? ORDER BY p.created_at DESC,p.id LIMIT 100''', (uid, uid)).fetchall()
        owned = [page for page in rows if role(db, page, uid)]
        return render_template('identity_pages.html', pages=owned,
            creative_allowed=eligible(db, uid, 'creative'), business_allowed=eligible(db, uid, 'business'), page_url=page_url)

    @bp.post('/pages/<page_id>/updates')
    def updates(page_id):
        uid = actor()
        response = writing()
        if response is not None:
            return response
        limited = app.extensions['community_auth_helpers']['limited']('page-update', 30)
        if limited is not None:
            return limited
        db = core.get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            write_post(db, uid, page_id, request.form.get('body', ''))
        flash('Page update published.', 'success')
        return redirect(page_url(get(db, page_id)))

    @bp.post('/pages/<page_id>/updates/<int:post_id>/remove')
    def remove_update(page_id, post_id):
        if not 0 < post_id < 2**63:
            abort(404)
        uid = actor()
        response = writing()
        if response is not None:
            return response
        db = core.get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            remove_post(db, uid, page_id, post_id)
        flash('Page update removed.', 'success')
        return redirect(page_url(get(db, page_id)))

    @bp.route('/pages/new', methods=['GET', 'POST'])
    def new():
        uid = actor()
        db = core.get_db()
        if request.method == 'POST':
            response = writing()
            if response is not None:
                return response
            limited = app.extensions['community_auth_helpers']['limited']('page-create', 20)
            if limited is not None:
                return limited
            with db:
                db.execute('BEGIN IMMEDIATE')
                page_id = create(db, uid, request.form.get('kind'), request.form.get('handle'),
                    request.form.get('name', ''), request.form.get('description', ''))
            flash('Page draft created.', 'success')
            return redirect(url_for('identity_pages.manage', page_id=page_id))
        return render_template('identity_page_new.html', creative_allowed=eligible(db, uid, 'creative'),
            business_allowed=eligible(db, uid, 'business'))

    @bp.route('/pages/<page_id>/edit', methods=['GET', 'POST'])
    def manage(page_id):
        uid = actor()
        db = core.get_db()
        page = get(db, page_id)
        require_role(db, page, uid, ('owner', 'manager', 'editor'))
        if request.method == 'POST':
            response = writing()
            if response is not None:
                return response
            with db:
                db.execute('BEGIN IMMEDIATE')
                action = request.form.get('action')
                if action == 'edit':
                    edit(db, uid, page_id, revision(), request.form.get('name', ''), request.form.get('description', ''))
                elif action == 'state':
                    set_state(db, uid, page_id, revision(), request.form.get('state'))
                else:
                    raise PageError('Choose a page action.')
            flash('Page updated.', 'success')
            return redirect(url_for('identity_pages.manage', page_id=page_id))
        return render_template('identity_page_edit.html', page=page, page_role=role(db, page, uid), page_url=page_url)

    def show(kind, slug):
        db = core.get_db()
        try:
            canonical = handle(kind, slug)
        except PageError:
            abort(404)
        page = db.execute('SELECT * FROM identity_pages WHERE handle=?', (canonical,)).fetchone()
        if not page or not visible(db, page, session.get('user_id')):
            abort(404)
        if slug != canonical[1:]:
            return redirect(page_url(page), code=308)
        viewer = session.get('user_id')
        before = request.args.get('before', type=int)
        if before is not None and not 0 < before < 2**63:
            abort(400)
        # Bounded work even when most authors are currently hidden from a reader.
        rows = db.execute('''SELECT * FROM identity_page_posts
            WHERE page_id=? AND removed=0 AND id<? ORDER BY id DESC LIMIT 51''',
            (page['id'], before or 2**63-1)).fetchall()
        posts = [post for post in rows[:50] if post_visible(db, page, post, viewer)]
        older = rows[49]['id'] if len(rows) > 50 else None
        endpoint = 'identity_pages.creative' if kind == 'creative' else 'identity_pages.business'
        return render_template('identity_page.html', page=page, page_role=role(db, page, viewer),
            posts=posts, page_hidden=hidden(db,page['id']), older_url=url_for(endpoint, slug=canonical[1:], before=older) if older else None)

    @bp.get('/_<slug>')
    def creative(slug):
        return show('creative', slug)

    @bp.get('/$<slug>')
    def business(slug):
        return show('business', slug)

    @bp.after_request
    def private_cache(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    app.register_blueprint(bp)
