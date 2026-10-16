"""Circle IDs share the post ID format without rebuilding the post/comment registry."""
import re
import sqlite3
from neonrest import public_ids


def ensure(db, key):
    if not isinstance(key, int) or not 0 < key <= public_ids.MAX_KEY:
        raise ValueError('Invalid Circle key')
    row = db.execute('SELECT public_id FROM circle_public_ids WHERE circle_id=?', (key,)).fetchone()
    if row:
        return row[0]
    if not db.execute('SELECT 1 FROM circles WHERE id=?', (key,)).fetchone():
        raise ValueError('Unavailable Circle')
    for _ in range(32):
        token = public_ids.random_token()
        try:
            db.execute('INSERT INTO circle_public_ids(circle_id,public_id) VALUES (?,?)', (key, token))
        except sqlite3.IntegrityError:
            row = db.execute('SELECT public_id FROM circle_public_ids WHERE circle_id=?', (key,)).fetchone()
            if row:
                return row[0]
            continue
        return token
    raise RuntimeError('Circle ID allocation failed')


def initialize(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS circle_public_ids(circle_id INTEGER PRIMARY KEY,public_id TEXT NOT NULL UNIQUE,legacy_alias TEXT UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS circle_id_migrations(name TEXT PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        first = not db.execute("SELECT 1 FROM circle_id_migrations WHERE name='opaque-v1'").fetchone()
        for row in db.execute('SELECT id FROM circles ORDER BY id').fetchall():
            ensure(db, row[0])
            if first:
                db.execute('UPDATE circle_public_ids SET legacy_alias=? WHERE circle_id=?', (str(row[0]), row[0]))
        db.execute('''CREATE TRIGGER IF NOT EXISTS circle_public_id_cleanup AFTER DELETE ON circles
          BEGIN DELETE FROM circle_public_ids WHERE circle_id=OLD.id; END''')
        db.execute("INSERT OR IGNORE INTO circle_id_migrations(name) VALUES ('opaque-v1')")
        db.commit()
    except Exception:
        db.rollback()
        raise


def public(db, key):
    row = db.execute('SELECT public_id FROM circle_public_ids WHERE circle_id=?', (key,)).fetchone()
    if row:
        return row[0]
    was_transaction = db.in_transaction
    token = ensure(db, key)
    if not was_transaction:
        db.commit()
    return token


def resolve(db, value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Invalid Circle ID')
    if public_ids.TOKEN.fullmatch(value):
        row = db.execute('SELECT p.circle_id FROM circle_public_ids p JOIN circles c ON c.id=p.circle_id WHERE p.public_id=?', (value,)).fetchone()
    elif re.fullmatch(r'[1-9][0-9]{0,18}', value, re.ASCII):
        row = db.execute('SELECT p.circle_id FROM circle_public_ids p JOIN circles c ON c.id=p.circle_id WHERE p.legacy_alias=?', (value,)).fetchone()
    else:
        raise ValueError('Invalid Circle ID')
    if not row:
        raise ValueError('Unavailable Circle')
    return row[0]
