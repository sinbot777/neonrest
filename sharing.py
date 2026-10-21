"""Prepare link-only shares using the same permissions as the source page.

Shares reference current source content. Media bytes and membership grants are not copied.
Publishing remains an explicit action in the normal CSRF-protected composer.
"""
from flask import abort, url_for
from neonrest_sandbox import public_ids, circle_ids, circles
from neonrest_sandbox.community_features import visible_post


def draft(db, kind, reference, uid):
    if not kind and not reference:
        return None
    if not uid or kind not in ('post', 'image', 'circle', 'vibe') or not reference or len(reference) > 200:
        abort(404)
    if kind in ('post', 'image'):
        try:
            pid = public_ids.resolve(db, 'post', reference)
        except ValueError:
            abort(404)
        if not visible_post(db, pid, uid) or db.execute('SELECT 1 FROM moderated_posts WHERE post_id=?', (pid,)).fetchone():
            abort(404)
        if kind == 'image':
            owner = db.execute('SELECT user_id FROM posts WHERE id=?', (pid,)).fetchone()
            if not owner or owner[0] != uid or not db.execute("SELECT 1 FROM post_media WHERE post_id=? AND kind IN ('image','gif')", (pid,)).fetchone():
                abort(404)
        path = url_for('post_detail', post_id=public_ids.public(db, 'post', pid))
        if kind == 'image':
            path += '#post-image-' + public_ids.public(db, 'post', pid)
    elif kind == 'circle':
        try:
            cid = circle_ids.resolve(db, reference)
        except ValueError:
            abort(404)
        circle = db.execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
        if not circle or not circles.info_allowed(db, circle, uid):
            abort(404)
        path = url_for('circle_page', circle_id=cid)
    else:
        vibe = db.execute('SELECT name FROM vibes WHERE name=? COLLATE NOCASE', (reference,)).fetchone()
        if not vibe:
            abort(404)
        path = url_for('vibe_page', vibe_name=vibe[0])
    labels = {'post': 'a post', 'image': 'an image', 'circle': 'a Circle', 'vibe': 'a Vibe'}
    return 'Shared ' + labels[kind] + ' on Neonrest:\n\nhttps://www.neonrest.com' + path


def prepare(db, kind, reference, uid):
    """Render a viewer-only preview; the form still publishes only its link text."""
    content = draft(db, kind, reference, uid)
    if content is None:
        return None
    preview = dict(kind=kind, url=content.rsplit('\n', 1)[-1], title='', excerpt='',
                   image=None, image_alt='', author=None, created_at=None, audience='')
    if kind in ('post', 'image'):
        pid = public_ids.resolve(db, 'post', reference)
        post = db.execute('SELECT p.*,u.handle FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?', (pid,)).fetchone()
        author = '@' + post['handle'].lstrip('@')
        preview.update(title=('Image' if kind == 'image' else 'Post') + ' by ' + author,
                       author=author, created_at=post['created_at'], excerpt=excerpt(post['content']))
        circle = circles.post_circle(db, pid)
        audience = db.execute('SELECT audience FROM post_privacy WHERE post_id=?', (pid,)).fetchone()
        preview['audience'] = (('Public Circle post · ' if circles.public_post(db, pid) else 'Circle members · ') + circles.label(circle)) if circle else {'public':'Public','friends':'Friends','private':'Private'}.get(audience[0] if audience else 'public', 'Restricted')
        media = db.execute("SELECT * FROM post_media WHERE post_id=? AND kind IN ('image','gif') LIMIT 1", (pid,)).fetchone()
        if media:
            # Use only permission-controlled uploaded media; never fetch external images.
            filename = media['poster'] if media['kind'] == 'gif' else media['filename']
            if filename:
                preview.update(image=url_for('media_file', filename=filename), image_alt=media['alt_text'] or media['title'] or 'Image in the original post')
    elif kind == 'circle':
        cid = circle_ids.resolve(db, reference)
        circle = db.execute('SELECT * FROM circles WHERE id=?', (cid,)).fetchone()
        preview.update(title=circles.label(circle), excerpt=excerpt(circle['description']),
                       audience='Public posts viewable by visitors · membership required to participate' if circles.public_circle(circle) else 'Hidden · invitation only' if circle['mode'] == 'hidden' else 'Membership approval required')
        if circle['icon']:
            preview.update(image=url_for('circle_icon', circle_id=cid), image_alt=circle['name'] + ' image')
    else:
        from neonrest_sandbox.utils.vibe_lifecycle import is_pending
        vibe = db.execute('SELECT * FROM vibes WHERE name=? COLLATE NOCASE', (reference,)).fetchone()
        preview.update(title=vibe['name'], audience='Each post keeps its own audience')
        if is_pending(db, vibe['id']):
            preview['excerpt'] = 'This Vibe is awaiting activation.'
        else:
            preview['excerpt'] = excerpt(vibe['welcome_message'] or 'Explore this Vibe on Neonrest.')
            logo = vibe['logo_url'] or ''
            if logo and not any(token in logo for token in (':', '\\', '..')) and not logo.startswith('/'):
                preview.update(image=url_for('static', filename=logo), image_alt=vibe['name'] + ' logo')
    return dict(content=content, preview=preview)


def excerpt(value):
    text = (value or '').strip()
    return text[:400].rstrip() + ('…' if len(text) > 400 else '')


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS post_share_permissions(post_id INTEGER PRIMARY KEY,external_circle INTEGER NOT NULL DEFAULT 0 CHECK(external_circle IN (0,1)))')
    db.execute('CREATE TABLE IF NOT EXISTS post_shares(share_post_id INTEGER PRIMARY KEY,source_post_id INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,CHECK(share_post_id<>source_post_id))')
    db.execute('CREATE INDEX IF NOT EXISTS post_share_source ON post_shares(source_post_id)')
    db.execute("CREATE TRIGGER IF NOT EXISTS post_share_cleanup AFTER DELETE ON posts BEGIN DELETE FROM post_share_permissions WHERE post_id=OLD.id; DELETE FROM post_shares WHERE share_post_id=OLD.id; END")
    db.commit()


def external_enabled(db, pid):
    return bool(db.execute('SELECT 1 FROM post_share_permissions WHERE post_id=? AND external_circle=1', (pid,)).fetchone())


def circle_external_allowed(db, pid, viewer):
    """Only a published share can use this exception; original routes never do."""
    from neonrest_sandbox.community_features import blocked
    circle = circles.post_circle(db, pid)
    post = db.execute('SELECT user_id FROM posts WHERE id=?', (pid,)).fetchone()
    return bool(circle and post and external_enabled(db, pid) and not circle['archived']
                and circles.membership(db, circle, post['user_id'])
                and not (viewer and blocked(db, circle['owner_id'], viewer))
                and not db.execute("SELECT 1 FROM circle_content_removals WHERE circle_id=? AND target_type='post' AND target_id=?", (circle['id'], pid)).fetchone())


def repost_enabled(db, pid):
    return circles.post_circle(db, pid) is None or circles.public_post(db, pid) or external_enabled(db, pid)


def set_permission(db, pid, value):
    if circles.post_circle(db, pid):
        db.execute('INSERT INTO post_share_permissions VALUES (?,?) ON CONFLICT(post_id) DO UPDATE SET external_circle=excluded.external_circle', (pid, int(value == '1')))


def validate_reference(db, reference, kind, uid):
    if kind not in ('post', 'image'):
        abort(400)
    draft(db, kind, reference, uid)  # Existing source, ownership and viewer gates.
    pid = public_ids.resolve(db, 'post', reference)
    if not repost_enabled(db, pid):
        abort(400, description='The original author has not allowed sharing outside this Circle.')
    return pid


def source_viewable(db, pid, viewer):
    if db.execute('SELECT 1 FROM moderated_posts WHERE post_id=?', (pid,)).fetchone():
        return False
    return visible_post(db, pid, viewer, external_circle_share=True)


def register(app, core):
    import markdown2
    from flask import session, request, send_from_directory
    from neonrest_sandbox.media_features import media_folder
    with app.app_context():
        initialize(core.get_db())

    def resolve(value):
        try:
            return public_ids.resolve(core.get_db(), 'post', value)
        except ValueError:
            abort(404)

    def shared_post(value):
        db = core.get_db()
        pid = resolve(value)
        ref = db.execute('SELECT source_post_id FROM post_shares WHERE share_post_id=?', (pid,)).fetchone()
        if not ref:
            return None
        # Check both the wrapper and source; never recursively embed another card.
        if not visible_post(db, pid, session.get('user_id')) or not source_viewable(db, ref[0], session.get('user_id')):
            return dict(available=False)
        source = db.execute('SELECT p.*,u.handle FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?', (ref[0],)).fetchone()
        if not source:
            return dict(available=False)
        result = dict(available=True, author='@'+source['handle'].lstrip('@'),
                      url=url_for('post_detail',post_id=source['id']),
                      created_at=source['created_at'], html=markdown2.markdown(source['content'],safe_mode='escape'), image=None, midi=None,
                      circle=bool(circles.post_circle(db, source['id'])), public_circle_post=circles.public_post(db, source['id']))
        token = public_ids.public(db,'post',pid)
        for row in db.execute('SELECT * FROM post_media WHERE post_id=?', (source['id'],)):
            media = dict(row)
            for field in ('filename','poster','loop_filename'):
                media[field+'_url'] = url_for('shared_media',share_id=token,kind=row['kind'],variant=field) if row[field] else None
            result['midi' if row['kind']=='midi' else 'image'] = media
        return result

    @app.context_processor
    def share_context():
        def enabled(value):
            return repost_enabled(core.get_db(), resolve(value))
        def permission(value):
            return external_enabled(core.get_db(), resolve(value))
        def is_share(value):
            return bool(core.get_db().execute('SELECT 1 FROM post_shares WHERE share_post_id=?',(resolve(value),)).fetchone())
        return dict(shared_post=shared_post,repost_enabled=enabled,circle_sharing_enabled=permission,is_shared_post=is_share)

    @app.route('/shared-media/<share_id>/<kind>/<variant>')
    def shared_media(share_id, kind, variant):
        if kind not in ('image','gif','midi') or variant not in ('filename','poster','loop_filename'):
            abort(404)
        db=core.get_db();pid=resolve(share_id)
        ref=db.execute('SELECT source_post_id FROM post_shares WHERE share_post_id=?',(pid,)).fetchone()
        if not ref or not visible_post(db,pid,session.get('user_id')) or not source_viewable(db,ref[0],session.get('user_id')):
            abort(404)
        row=db.execute('SELECT * FROM post_media WHERE post_id=? AND kind=?',(ref[0],kind)).fetchone()
        if not row or not row[variant]:
            abort(404)
        response=send_from_directory(media_folder(),row[variant])
        response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
        return response
