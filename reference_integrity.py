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


def archive_legacy_orphans(db, batch, comment_ids, post_vibes):
    """Archive a reviewed, explicit orphan set; caller owns the transaction.

    The archive is private operational data, never public source or content.
    Existing backups and the complete original rows support reviewed restoration.
    """
    import json,hashlib
    from .content_deletion import _preserved
    if not db.in_transaction:
        raise RuntimeError('Archiving requires an explicit transaction')
    if not batch or len(batch)>100 or len(comment_ids)>100:
        raise ValueError('Invalid repair batch')
    if len(set(comment_ids))!=len(comment_ids):
        raise ValueError('Duplicate comment selection')
    selected=set(comment_ids)
    rows=[]
    for cid in comment_ids:
        row=db.execute('SELECT * FROM comments WHERE id=?',(cid,)).fetchone()
        if not row:raise ValueError('Reviewed comment changed or disappeared')
        post_missing=not db.execute('SELECT 1 FROM posts WHERE id=?',(row['post_id'],)).fetchone()
        parent_missing=row['parent_comment_id'] is not None and not db.execute('SELECT 1 FROM comments WHERE id=?',(row['parent_comment_id'],)).fetchone()
        if not (post_missing or parent_missing):raise ValueError('Refusing to archive a valid comment')
        if any(r[0] not in selected for r in db.execute('SELECT id FROM comments WHERE parent_comment_id=?',(cid,))):
            raise ValueError('Unreviewed replies depend on this comment')
        rows.append(row)
    _preserved(db,[r['user_id'] for r in rows])
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.execute("""CREATE TABLE IF NOT EXISTS reference_repair_archive(
        batch TEXT NOT NULL,table_name TEXT NOT NULL,record_key TEXT NOT NULL,
        source_rowid INTEGER,payload TEXT NOT NULL,sha256 TEXT NOT NULL,reason TEXT NOT NULL,
        archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(batch,table_name,record_key))""")
    def save(table, records, source_rowid=None):
        for row in records:
            value=dict(row)
            payload=json.dumps(value,sort_keys=True,ensure_ascii=False)
            digest=hashlib.sha256(payload.encode()).hexdigest()
            db.execute('INSERT INTO reference_repair_archive(batch,table_name,record_key,source_rowid,payload,sha256,reason) VALUES (?,?,?,?,?,?,?)',
                (batch,table,digest,source_rowid,payload,digest,'Owner-reviewed legacy test orphan; archived without reconstructing missing parents'))
    save('comments',rows)
    for row in rows:
        cid=row['id']
        if 'public_ids' in tables:save('public_ids',db.execute("SELECT * FROM public_ids WHERE kind='comment' AND internal_id=?",(cid,)).fetchall())
        if 'public_id_aliases' in tables:save('public_id_aliases',db.execute("SELECT * FROM public_id_aliases WHERE kind='comment' AND internal_id=?",(cid,)).fetchall())
        if 'moderated_comments' in tables:
            save('moderated_comments',db.execute('SELECT * FROM moderated_comments WHERE comment_id=?',(cid,)).fetchall())
            db.execute('DELETE FROM moderated_comments WHERE comment_id=?',(cid,))
        if 'protected_age_comments' in tables:
            save('protected_age_comments',db.execute('SELECT * FROM protected_age_comments WHERE comment_id=?',(cid,)).fetchall())
            db.execute('DELETE FROM protected_age_comments WHERE comment_id=?',(cid,))
    for cid in comment_ids:
        db.execute('UPDATE comments SET parent_comment_id=NULL WHERE id=?',(cid,))
    for cid in comment_ids:
        db.execute('DELETE FROM comments WHERE id=?',(cid,))
    for pid,vid in post_vibes:
        row=db.execute('SELECT * FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid)).fetchone()
        if not row or db.execute('SELECT 1 FROM posts WHERE id=?',(pid,)).fetchone():
            raise ValueError('Reviewed orphan mapping changed')
        save('post_vibes',[row],db.execute('SELECT rowid FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid)).fetchone()[0])
        db.execute('DELETE FROM post_vibes WHERE post_id=? AND vibe_id=?',(pid,vid))
    return {'comments':len(rows),'post_vibes':len(post_vibes),
            'archived_records':db.execute('SELECT COUNT(*) FROM reference_repair_archive WHERE batch=?',(batch,)).fetchone()[0]}

