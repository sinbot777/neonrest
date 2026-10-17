"""Per-name display numbers, independent of Circle database and public URL IDs."""
import hashlib
import unicodedata


def key(name):
    normalized = unicodedata.normalize('NFKC', ' '.join(name.split())).casefold()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def assign(db, cid, name):
    """Allocate under the caller's write transaction, or own a serialized transaction."""
    own = not db.in_transaction
    if own:
        db.execute('BEGIN IMMEDIATE')
    try:
        namespace = key(name)
        row = db.execute('SELECT name_number FROM circle_name_assignments WHERE circle_id=? AND name_key=?', (cid,namespace)).fetchone()
        if row:
            number = row[0]
        else:
            db.execute('INSERT INTO circle_name_counters VALUES (?,1) ON CONFLICT(name_key) DO UPDATE SET last_number=last_number+1', (namespace,))
            number = db.execute('SELECT last_number FROM circle_name_counters WHERE name_key=?', (namespace,)).fetchone()[0]
            db.execute('INSERT INTO circle_name_assignments VALUES (?,?,?)', (cid,namespace,number))
        db.execute('UPDATE circles SET name_key=?,name_number=? WHERE id=?', (namespace,number,cid))
        if own:
            db.commit()
        return number
    except Exception:
        if own:
            db.rollback()
        raise


def initialize(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        columns = {r[1] for r in db.execute('PRAGMA table_info(circles)')}
        for name,kind in (('name_key','TEXT'),('name_number','INTEGER')):
            if name not in columns:
                db.execute('ALTER TABLE circles ADD COLUMN '+name+' '+kind)
        db.execute('CREATE TABLE IF NOT EXISTS circle_name_counters(name_key TEXT PRIMARY KEY,last_number INTEGER NOT NULL CHECK(last_number>0))')
        db.execute('CREATE TABLE IF NOT EXISTS circle_name_assignments(circle_id INTEGER NOT NULL,name_key TEXT NOT NULL,name_number INTEGER NOT NULL,PRIMARY KEY(circle_id,name_key),UNIQUE(name_key,name_number))')
        for cid,name in db.execute('SELECT id,name FROM circles ORDER BY id').fetchall():
            assign(db,cid,name)
        db.execute('CREATE TRIGGER IF NOT EXISTS circle_name_cleanup AFTER DELETE ON circles BEGIN DELETE FROM circle_name_assignments WHERE circle_id=OLD.id; END')
        db.commit()
    except Exception:
        db.rollback()
        raise
