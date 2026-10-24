"""T25 page identities. Personal logins remain users; pages never gain a login.

This foundation is intentionally not registered with the live app yet. Business
activation needs the separately reviewed subscription provider integration.
"""
import re
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
        'CREATE INDEX IF NOT EXISTS identity_page_owner ON identity_pages(owner_id,id)',
        'CREATE INDEX IF NOT EXISTS identity_page_member ON identity_page_members(user_id,page_id)',
        'CREATE INDEX IF NOT EXISTS identity_page_history ON identity_page_events(page_id,id)',
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
    }


def register(app, core):
    """Register after community/age initialization; live integration is pending."""
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
        return render_template('identity_page.html', page=page, page_role=role(db, page, session.get('user_id')))

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
