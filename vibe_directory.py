"""Public Vibe discovery using the same visibility rule as Vibe feeds."""
from pathlib import Path
from urllib.parse import urlsplit
from flask import abort, current_app, render_template, request, url_for, make_response

DESCRIPTIONS = {
    'fresh starts': 'A soft place for new beginnings, small victories, and trying again.',
    'couchcore': 'Get comfortable. Share cozy moments, everyday life, and good company.',
    'changelog': 'Updates, experiments, and conversations about building Neonrest.',
    'backporch': 'Pull up a chair for relaxed conversation and everyday thoughts.',
    'driftroom': 'Ambient thoughts, wandering ideas, and half-formed dreams.',
    'analog': 'For lovers of retro, physical, and tactile things.',
    'melancholy': 'A little room for reflective moods and bittersweet moments.',
    'nostalgia': 'Old favorites, familiar places, and memories worth revisiting.',
}

def logo_url(value):
    value = (value or '').strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme or parts.netloc:
        return value if parts.scheme == 'https' and parts.netloc and not parts.username and not parts.password else None
    if not value or value.startswith('/') or '\x00' in value:
        return None
    folder = Path(current_app.static_folder).resolve()
    target = (folder / value).resolve()
    if not target.is_relative_to(folder) or not target.is_file():
        return None
    return url_for('static', filename=value)

def directory(db):
    query = request.args.get('vq', '').strip()[:120]
    sort = request.args.get('sort', 'name')
    if sort not in ('name', 'recent'):
        sort = 'name'
    try:
        page = int(request.args.get('page', '1'))
    except ValueError:
        abort(404)
    if page < 1 or page > 100000:
        abort(404)
    rows = db.execute('''
        SELECT v.id, v.name, v.logo_url, v.welcome_message,
               COUNT(p.id) AS visible_posts, MAX(p.created_at) AS last_post
        FROM vibes v
        LEFT JOIN post_vibes pv ON pv.vibe_id = v.id
        LEFT JOIN posts p ON p.id = pv.post_id
          AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id = p.id)
          AND community_post_visible(p.id) = 1
        WHERE NOT EXISTS (SELECT 1 FROM pending_vibes pending WHERE pending.vibe_id = v.id)
          AND NOT EXISTS (SELECT 1 FROM vibe_management vm WHERE vm.vibe_id = v.id AND vm.archived=1)
        GROUP BY v.id
    ''').fetchall()
    entries = []
    for row in rows:
        entry = dict(row)
        entry['description'] = (row['welcome_message'] or '').strip() or DESCRIPTIONS.get(row['name'].casefold(), 'A shared space for posts and conversations. Come see what is here.')
        entry['description'] = entry['description'][:500]
        if query.casefold() not in (entry['name'] + ' ' + entry['description']).casefold():
            continue
        entry['logo'] = logo_url(row['logo_url'])
        entries.append(entry)
    entries.sort(key=lambda item: (item['name'].casefold(), item['id']))
    if sort == 'recent':
        entries.sort(key=lambda item: item['last_post'] or '', reverse=True)
    total = len(entries)
    pages = max(1, (total + 23) // 24)
    if page > pages:
        abort(404)
    response = make_response(render_template('explore.html', vibes=entries[(page-1)*24:page*24], query=query,
                           directory_sort=sort, page=page, total_pages=pages, total=total))
    response.headers['Cache-Control'] = 'private, no-store'
    return response
