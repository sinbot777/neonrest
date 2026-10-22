"""Private reading preferences, live-reference bookmarks and explicit composer drafts."""
import json
import re
import secrets
from flask import abort, flash, g, redirect, render_template, request, session, url_for

VIEWS = {'all': 'All posts', 'friends': 'Friends', 'followed': 'Followed', 'vibes': 'Your Vibes', 'circles': 'Your Circles', 'bookmarks': 'Bookmarks'}
ACTIVE_VIBE = "NOT EXISTS(SELECT 1 FROM pending_vibes x WHERE x.vibe_id=v.id) AND NOT EXISTS(SELECT 1 FROM vibe_management x WHERE x.vibe_id=v.id AND x.archived=1)"
FIELDS = {'content': 20000, 'vibes': 500, 'audience': 40, 'circle_id': 32, 'circle_audience': 16, 'allow_circle_sharing': 1, 'shared_source': 32, 'shared_kind': 16, 'image_title': 100, 'image_alt': 180, 'image_filter': 20, 'midi_title': 100}


def initialize(db):
    for sql in [
        "CREATE TABLE IF NOT EXISTS reading_preferences(user_id INTEGER PRIMARY KEY,default_view TEXT NOT NULL DEFAULT 'all' CHECK(default_view IN ('all','friends','followed','vibes','circles','bookmarks')))",
        'CREATE TABLE IF NOT EXISTS reading_vibes(user_id INTEGER NOT NULL,vibe_id INTEGER NOT NULL,PRIMARY KEY(user_id,vibe_id))',
        'CREATE TABLE IF NOT EXISTS post_bookmarks(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,post_id INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,post_id))',
        'CREATE INDEX IF NOT EXISTS idx_bookmarks_post ON post_bookmarks(post_id,user_id)',
        'CREATE INDEX IF NOT EXISTS idx_bookmarks_owner_created ON post_bookmarks(user_id,created_at DESC,id DESC)',
        'CREATE TABLE IF NOT EXISTS composer_drafts(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)',
        'CREATE INDEX IF NOT EXISTS idx_drafts_owner_updated ON composer_drafts(user_id,updated_at DESC,id DESC)',
    ]:
        db.execute(sql)
    db.commit()


def page_number():
    raw = request.args.get('page', '1')
    if not re.fullmatch(r'[0-9]{1,5}', raw) or not 1 <= int(raw) <= 10000:
        abort(400)
    return int(raw)


def owned_draft(db, uid, key):
    if not re.fullmatch(r'[a-f0-9]{32}', key or ''):
        abort(404)
    row = db.execute('SELECT * FROM composer_drafts WHERE id=? AND user_id=?', (key, uid)).fetchone()
    if not row:
        abort(404)
    return dict(row)


def draft_revision(raw):
    if not re.fullmatch(r'[0-9]{1,9}', raw or '') or int(raw) < 1:
        abort(400)
    return int(raw)


def check_publish(db, uid):
    key = request.form.get('draft_id')
    if key:
        row = owned_draft(db, uid, key)
        if row['revision'] != draft_revision(request.form.get('draft_revision')):
            abort(409, description='This draft changed in another tab. Reopen it before posting.')


def consume_draft(db, uid):
    if request.form.get('draft_id'):
        check_publish(db, uid)
        db.execute('DELETE FROM composer_drafts WHERE id=? AND user_id=?', (request.form['draft_id'], uid))


def composer(db, uid):
    """Read only the owner's draft. Never silently broaden a stale audience/destination."""
    row = owned_draft(db, uid, request.args['draft']) if request.method == 'GET' and request.args.get('draft') else None
    data = json.loads(row['payload']) if row else {}
    return row, data


def feed_filter(db):
    if request.endpoint not in ('feed', 'reading_bookmarks'):
        return [], []
    uid = session.get('user_id')
    if not uid:
        return [], []
    if request.endpoint == 'reading_bookmarks':
        view = 'bookmarks'
    else:
        saved = db.execute('SELECT default_view FROM reading_preferences WHERE user_id=?', (uid,)).fetchone()
        view = request.args.get('view', saved[0] if saved else 'all')
    if view not in VIEWS:
        abort(400)
    g.reading_view = view
    if view == 'friends':
        return ["EXISTS(SELECT 1 FROM friend_requests f WHERE f.status='accepted' AND ((f.sender_id=? AND f.receiver_id=p.user_id) OR (f.receiver_id=? AND f.sender_id=p.user_id)))"], [uid, uid]
    if view == 'followed':
        from .social_connections import active_follow
        db.create_function('reading_active_follow', 1, lambda owner: int(active_follow(db, uid, owner)))
        return ['reading_active_follow(p.user_id)=1'], []
    if view == 'vibes':
        return ['EXISTS(SELECT 1 FROM post_vibes pv JOIN reading_vibes rv ON rv.vibe_id=pv.vibe_id JOIN vibes v ON v.id=pv.vibe_id WHERE pv.post_id=p.id AND rv.user_id=? AND '+ACTIVE_VIBE+')'], [uid]
    if view == 'circles':
        return ["EXISTS(SELECT 1 FROM circle_posts cp JOIN circle_members cm ON cm.circle_id=cp.circle_id WHERE cp.post_id=p.id AND cm.user_id=? AND cm.status='active')"], [uid]
    if view == 'bookmarks':
        return ['EXISTS(SELECT 1 FROM post_bookmarks b WHERE b.user_id=? AND b.post_id=p.id)'], [uid]
    return [], []


def export_user(db, uid, identifiers):
    saved = [dict(r) for r in db.execute('SELECT id,post_id,created_at FROM post_bookmarks WHERE user_id=? ORDER BY id', (uid,))]
    from .community_features import visible_post
    for row in saved:
        pid = row.pop('post_id')
        row['post'] = identifiers.public(db, 'post', pid) if visible_post(db, pid, uid) else None
    return {'preferences': [dict(r) for r in db.execute('SELECT default_view FROM reading_preferences WHERE user_id=?', (uid,))],
            'vibes': [dict(r) for r in db.execute('SELECT v.name FROM reading_vibes r JOIN vibes v ON v.id=r.vibe_id WHERE r.user_id=?', (uid,))],
            'bookmarks': saved,
            'drafts': [{'id': r['id'], 'revision': r['revision'], 'created_at': r['created_at'], 'updated_at': r['updated_at'], 'fields': json.loads(r['payload'])} for r in db.execute('SELECT * FROM composer_drafts WHERE user_id=? ORDER BY id', (uid,))]}


def register(app, core):
    from .community_features import visible_post
    with app.app_context():
        initialize(core.get_db())

    def current(write=False):
        uid = session.get('user_id')
        if not uid or not core.get_db().execute('SELECT 1 FROM users WHERE id=? AND email=? AND verified=1', (uid, session.get('user_email'))).fetchone():
            abort(401)
        if write:
            app.extensions['community_auth_helpers']['csrf']()
        return uid

    def limited(action):
        return app.extensions['community_auth_helpers']['limited']('reading:'+action, 120, 3600)

    @app.route('/account/feed', methods=['GET', 'POST'])
    def reading_settings():
        uid = current(request.method == 'POST'); db = core.get_db()
        if request.method == 'POST':
            response = limited('settings')
            if response is not None: return response
            view = request.form.get('default_view')
            if view not in VIEWS: abort(400)
            selected = request.form.getlist('vibe_id')
            if len(selected) > 50 or any(not re.fullmatch(r'[0-9]{1,18}', v) for v in selected): abort(400)
            selected = set(map(int, selected))
            db.execute('BEGIN IMMEDIATE')
            for vid in selected:
                if not db.execute('SELECT 1 FROM vibes v WHERE v.id=? AND '+ACTIVE_VIBE, (vid,)).fetchone(): abort(400)
            db.execute('INSERT INTO reading_preferences VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET default_view=excluded.default_view', (uid, view))
            db.execute('DELETE FROM reading_vibes WHERE user_id=?', (uid,))
            db.executemany('INSERT INTO reading_vibes VALUES (?,?)', [(uid, vid) for vid in selected]); db.commit()
            flash('Feed preferences saved.', 'success'); return redirect(url_for('reading_settings'))
        saved = db.execute('SELECT default_view FROM reading_preferences WHERE user_id=?', (uid,)).fetchone()
        q = request.args.get('q', '').strip()[:100]
        page = page_number(); pattern = '%'+q.replace('!', '!!').replace('%', '!%').replace('_', '!_')+'%'
        vibes = db.execute("SELECT v.id,v.name,EXISTS(SELECT 1 FROM reading_vibes r WHERE r.user_id=? AND r.vibe_id=v.id) AS selected FROM vibes v WHERE "+ACTIVE_VIBE+" AND v.name LIKE ? ESCAPE '!' ORDER BY v.name,v.id LIMIT 51 OFFSET ?", (uid, pattern, (page-1)*50)).fetchall()
        chosen = db.execute('SELECT v.id,v.name FROM reading_vibes r JOIN vibes v ON v.id=r.vibe_id WHERE r.user_id=? ORDER BY v.name,v.id', (uid,)).fetchall()
        return render_template('reading_settings.html', views=VIEWS, default_view=saved[0] if saved else 'all', vibes=vibes[:50], chosen=chosen, page=page, more=len(vibes)>50, query=q)

    @app.route('/bookmarks')
    def reading_bookmarks():
        current(); return core.feed()

    @app.route('/reading/bookmark/<string:post_id>', methods=['POST'])
    def reading_bookmark(post_id):
        uid = current(True); db = core.get_db(); response = limited('bookmark')
        if response is not None: return response
        try: pid = core.identifiers.resolve(db, 'post', post_id)
        except (ValueError, TypeError): abort(404)
        action = request.form.get('action')
        if action not in ('save', 'remove'): abort(400)
        db.execute('BEGIN IMMEDIATE')
        if action == 'save':
            if not visible_post(db, pid, uid): abort(404)
            exists = db.execute('SELECT 1 FROM post_bookmarks WHERE user_id=? AND post_id=?', (uid, pid)).fetchone()
            if not exists and db.execute('SELECT count(*) FROM post_bookmarks WHERE user_id=?', (uid,)).fetchone()[0] >= 2000: abort(409, description='Your 2,000 bookmarks are full. Remove one before saving another.')
            db.execute('INSERT OR IGNORE INTO post_bookmarks(id,user_id,post_id) VALUES (?,?,?)', (secrets.token_hex(16), uid, pid))
        else:
            db.execute('DELETE FROM post_bookmarks WHERE user_id=? AND post_id=?', (uid, pid))
        db.commit(); flash('Bookmark saved.' if action == 'save' else 'Bookmark removed.', 'success')
        return redirect(url_for('reading_bookmarks'))

    @app.route('/account/bookmarks', methods=['GET', 'POST'])
    def reading_bookmark_settings():
        uid = current(request.method == 'POST'); db = core.get_db()
        if request.method == 'POST':
            response = limited('bookmark')
            if response is not None: return response
            key = request.form.get('id', '')
            if not re.fullmatch(r'[a-f0-9]{32}', key): abort(400)
            db.execute('DELETE FROM post_bookmarks WHERE user_id=? AND id=?', (uid, key)); db.commit()
            return redirect(url_for('reading_bookmark_settings'))
        page = page_number(); rows = db.execute('SELECT b.*,p.content FROM post_bookmarks b LEFT JOIN posts p ON p.id=b.post_id WHERE b.user_id=? ORDER BY b.created_at DESC,b.id DESC LIMIT 21 OFFSET ?', (uid, (page-1)*20)).fetchall(); entries=[]
        for row in rows[:20]:
            allowed = visible_post(db, row['post_id'], uid)
            entries.append({'id':row['id'], 'text':row['content'][:160] if allowed else 'Post unavailable', 'url':url_for('post_detail', post_id=core.identifiers.public(db, 'post', row['post_id'])) if allowed else None})
        return render_template('reading_bookmarks.html', entries=entries, page=page, more=len(rows)>20)

    @app.route('/drafts')
    def reading_drafts():
        uid = current(); db = core.get_db(); page=page_number()
        rows=db.execute('SELECT * FROM composer_drafts WHERE user_id=? ORDER BY updated_at DESC,id DESC LIMIT 21 OFFSET ?', (uid,(page-1)*20)).fetchall()
        entries=[dict(r, fields=json.loads(r['payload'])) for r in rows[:20]]
        return render_template('reading_drafts.html', entries=entries, page=page, more=len(rows)>20)

    @app.route('/drafts/save', methods=['POST'])
    def reading_save_draft():
        uid=current(True); db=core.get_db(); response=limited('draft')
        if response is not None: return response
        if any(f.filename for f in request.files.values()): abort(400, description='Drafts save text and settings. Clear file selections before saving; reattach them when publishing.')
        data={name:request.form.get(name,'') for name in FIELDS}
        if request.form.get('drop_share') == '1':
            data['shared_source'] = data['shared_kind'] = ''
        if any(len(data[name])>maximum for name,maximum in FIELDS.items()): abort(400)
        if not data['content'].strip() and not data['shared_source']: abort(400, description='Add text or a shared post before saving a draft.')
        if data['audience'] not in ('public','friends','connections','private') and not re.fullmatch(r'label:[1-9][0-9]{0,17}', data['audience']): abort(400)
        if data['circle_id'] and not re.fullmatch(r'[A-Za-z0-9]{1,32}', data['circle_id']): abort(400)
        if data['circle_audience'] not in ('','private','public') or data['allow_circle_sharing'] not in ('','1'): abort(400)
        if data['shared_source'] and (not re.fullmatch(r'[A-Za-z0-9]{1,32}',data['shared_source']) or data['shared_kind'] not in ('post','image')): abort(400)
        payload=json.dumps(data,ensure_ascii=False)
        if len(payload.encode())>96000: abort(400)
        key=request.form.get('draft_id',''); db.execute('BEGIN IMMEDIATE')
        if key:
            old=owned_draft(db,uid,key)
            if old['revision']!=draft_revision(request.form.get('draft_revision')): abort(409, description='This draft changed in another tab. Reopen it before saving.')
            db.execute('UPDATE composer_drafts SET payload=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(payload,key,uid))
        else:
            if db.execute('SELECT COUNT(*) FROM composer_drafts WHERE user_id=?',(uid,)).fetchone()[0]>=50: abort(409, description='Your 50 drafts are full. Publish or remove one before saving another.')
            key=secrets.token_hex(16); db.execute('INSERT INTO composer_drafts(id,user_id,payload) VALUES (?,?,?)',(key,uid,payload))
        db.commit(); flash('Draft saved privately. Attachments are added when publishing.', 'success'); return redirect(url_for('reading_drafts'))

    @app.route('/drafts/<string:key>')
    def reading_edit_draft(key):
        uid=current(); row=owned_draft(core.get_db(),uid,key)
        return render_template('reading_draft.html', draft=row, fields=json.loads(row['payload']), draft_fields=FIELDS)

    @app.route('/drafts/<string:key>/delete', methods=['POST'])
    def reading_delete_draft(key):
        uid=current(True); db=core.get_db(); response=limited('draft')
        if response is not None: return response
        db.execute('BEGIN IMMEDIATE'); row=owned_draft(db,uid,key)
        if row['revision']!=draft_revision(request.form.get('draft_revision')): abort(409, description='This draft changed in another tab. Reopen it before removing.')
        db.execute('DELETE FROM composer_drafts WHERE id=? AND user_id=?',(key,uid)); db.commit(); return redirect(url_for('reading_drafts'))

    @app.context_processor
    def reading_context():
        def bookmarked(pid):
            uid=session.get('user_id')
            return bool(uid and core.get_db().execute('SELECT 1 FROM post_bookmarks WHERE user_id=? AND post_id=?',(uid,pid)).fetchone())
        def paging(page):
            return url_for('reading_bookmarks',page=page) if request.endpoint=='reading_bookmarks' else url_for('feed',view=getattr(g,'reading_view','all'),page=page)
        return {'reading_views':VIEWS,'reading_view':getattr(g,'reading_view','all'),'reading_bookmarked':bookmarked,'reading_page_url':paging}
