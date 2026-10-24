"""Preserve legacy rows while repairing the obsolete post_vibes FK target."""
import sqlite3


def repair_post_vibes(db):
    keys=list(db.execute('PRAGMA foreign_key_list(post_vibes)'))
    if not any(row[2]=='posts_old' and row[3]=='post_id' for row in keys):
        return False
    if db.in_transaction:
        raise RuntimeError('Reference repair requires its own transaction')
    original=list(db.execute('SELECT post_id,vibe_id FROM post_vibes ORDER BY post_id,vibe_id'))
    indexes=[row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='post_vibes' AND type='index' AND sql IS NOT NULL")]
    triggers=[row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='post_vibes' AND type='trigger' AND sql IS NOT NULL")]
    enabled=db.execute('PRAGMA foreign_keys').fetchone()[0]
    db.execute('PRAGMA foreign_keys=OFF')
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE post_vibes_reference_repair(
            post_id INTEGER NOT NULL REFERENCES posts(id),
            vibe_id INTEGER NOT NULL REFERENCES vibes(id),PRIMARY KEY(post_id,vibe_id))''')
        db.execute('INSERT INTO post_vibes_reference_repair SELECT post_id,vibe_id FROM post_vibes')
        db.execute('DROP TABLE post_vibes')
        db.execute('ALTER TABLE post_vibes_reference_repair RENAME TO post_vibes')
        for sql in indexes+triggers:db.execute(sql)
        assert list(db.execute('SELECT post_id,vibe_id FROM post_vibes ORDER BY post_id,vibe_id'))==original
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.execute('PRAGMA foreign_keys='+str(enabled))
    return True
