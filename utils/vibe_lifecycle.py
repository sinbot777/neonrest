"""Promotion of post tags into public Vibes.

Existing Vibes have no pending row and remain public. New tags are linked to
posts immediately, then promoted after enough distinct authors use them.
"""
import os

DEFAULT_MIN_USERS = 3


def minimum_users():
    try:
        return max(1, int(os.environ.get('VIBE_CREATION_MIN_USERS', DEFAULT_MIN_USERS)))
    except ValueError:
        return DEFAULT_MIN_USERS


def init_vibe_tables(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS pending_vibes (
            vibe_id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vibe_id) REFERENCES vibes(id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS staff_roles (
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'manager', 'moderator')),
            PRIMARY KEY (user_id, role)
        )
    ''')


def vibe_slug(name):
    import re
    return re.sub(r'[^a-z0-9-]+', '-', name.strip().lower()).strip('-')


def is_pending(db, vibe_id):
    return db.execute(
        'SELECT 1 FROM pending_vibes WHERE vibe_id = ?', (vibe_id,)
    ).fetchone() is not None


def supporter_count(db, vibe_id):
    return db.execute('''
        SELECT COUNT(DISTINCT posts.user_id)
        FROM post_vibes JOIN posts ON posts.id = post_vibes.post_id
        WHERE post_vibes.vibe_id = ?
    ''', (vibe_id,)).fetchone()[0]


def add_post_vibes(db, post_id, names, threshold=None):
    """Attach names to a post and promote pending Vibes at the threshold."""
    threshold = minimum_users() if threshold is None else threshold
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        slug = vibe_slug(name)
        if not slug:
            continue
        # A display name with different punctuation must not claim another Vibe's CSS slug.
        vibe = next((row for row in db.execute('SELECT id, name FROM vibes')
                     if vibe_slug(row['name']) == slug), None)
        if vibe is None:
            cursor = db.execute('INSERT INTO vibes (name) VALUES (?)', (name,))
            vibe_id = cursor.lastrowid
            if threshold > 1:
                db.execute('INSERT INTO pending_vibes (vibe_id) VALUES (?)', (vibe_id,))
        else:
            vibe_id = vibe['id']
        db.execute(
            'INSERT OR IGNORE INTO post_vibes (post_id, vibe_id) VALUES (?, ?)',
            (post_id, vibe_id)
        )
        if is_pending(db, vibe_id) and supporter_count(db, vibe_id) >= threshold:
            db.execute('DELETE FROM pending_vibes WHERE vibe_id = ?', (vibe_id,))


def can_approve_vibes(db, user_id):
    if user_id == 1:
        return True  # Existing site administrator.
    if user_id is None:
        return False
    return db.execute('''
        SELECT 1 FROM staff_roles
        WHERE user_id = ? AND role IN ('admin', 'manager')
    ''', (user_id,)).fetchone() is not None


def approve_vibe(db, vibe_id):
    """Promote a pending Vibe; returns whether it was pending."""
    return db.execute(
        'DELETE FROM pending_vibes WHERE vibe_id = ?', (vibe_id,)
    ).rowcount > 0
