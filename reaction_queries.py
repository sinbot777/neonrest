"""Page-scoped reaction counts and seek-paged, privacy-filtered people."""
from flask import abort


def hydrate_reactions(db, posts, viewer_id):
    ids = list(dict.fromkeys(post['id'] for post in posts))
    counts = {}
    choices = {}
    if ids:
        rows = db.execute('SELECT post_id,emoji,COUNT(*) AS count,'
            'MAX(user_id=?) AS chosen FROM post_reactions WHERE post_id IN ('
            + ','.join('?' for _ in ids) + ') GROUP BY post_id,emoji',
            [viewer_id] + ids)
        for row in rows:
            counts.setdefault(row['post_id'], {})[row['emoji']] = row['count']
            if row['chosen']:
                choices.setdefault(row['post_id'], set()).add(row['emoji'])
    for post in posts:
        post['reaction_counts'] = counts.get(post['id'], {})
        post['viewer_reactions'] = choices.get(post['id'], set())


def reactor_window(db, post_id, emoji, after=None):
    try:
        boundary = int(after) if after is not None else 0
        if boundary < 0 or boundary > 2**63-1:
            raise ValueError()
    except (ValueError, TypeError):
        abort(400)
    rows = list(db.execute('SELECT DISTINCT u.id,u.handle FROM post_reactions r '
        'JOIN users u ON u.id=r.user_id WHERE r.post_id=? AND r.emoji=? '
        'AND r.user_id>? AND community_member_visible(u.id)=1 '
        'ORDER BY r.user_id LIMIT 51',
        (post_id, emoji, boundary)))
    return rows[:50], rows[49]['id'] if len(rows)>50 else None
