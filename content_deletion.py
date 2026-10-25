"""Transactional content removal without orphaning replies or related records."""
from .privacy_workflows import blockers


class DeletionBlocked(ValueError):
    pass


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _preserved(db, authors):
    if any(blockers(db, uid) for uid in set(authors)):
        raise DeletionBlocked('These records require preservation or case review. Contact staff before removing them.')


def _comment_metadata(db, cid, tables):
    if 'moderated_comments' in tables:
        db.execute('DELETE FROM moderated_comments WHERE comment_id=?', (cid,))
    if 'protected_age_comments' in tables:
        db.execute('DELETE FROM protected_age_comments WHERE comment_id=?', (cid,))


def remove_comment(db, cid, actor):
    if not db.in_transaction:
        raise RuntimeError('Content deletion requires an explicit transaction')
    row = db.execute('SELECT * FROM comments WHERE id=?', (cid,)).fetchone()
    if not row or row['user_id'] != actor:
        raise DeletionBlocked('Comment unavailable or not owned by this account.')
    _preserved(db, [actor])
    tables = _tables(db)
    children = db.execute('SELECT id,post_id FROM comments WHERE parent_comment_id=? AND id<>?', (cid,cid)).fetchall()
    if any(child['post_id'] != row['post_id'] for child in children):
        raise DeletionBlocked('This thread needs staff review before removing its parent.')
    # A removed ancestor is an access barrier in Circle threads. Do not promote
    # replies out of that barrier or discard moderation/age restrictions.
    if children and (
        'moderated_comments' in tables and db.execute('SELECT 1 FROM moderated_comments WHERE comment_id=?',(cid,)).fetchone()
        or 'protected_age_comments' in tables and db.execute('SELECT 1 FROM protected_age_comments WHERE comment_id=?',(cid,)).fetchone()
        or 'circle_content_removals' in tables and db.execute("SELECT 1 FROM circle_content_removals WHERE target_type='comment' AND target_id=?",(cid,)).fetchone()
    ):
        raise DeletionBlocked('This moderated thread needs staff review before removing its parent.')
    parent = row['parent_comment_id']
    seen = {cid}
    cursor = parent
    while cursor is not None:
        ancestor = db.execute('SELECT post_id,parent_comment_id FROM comments WHERE id=?',(cursor,)).fetchone()
        if cursor in seen or not ancestor or ancestor['post_id'] != row['post_id']:
            parent = None
            break
        seen.add(cursor)
        cursor = ancestor['parent_comment_id']
    db.execute('UPDATE comments SET parent_comment_id=? WHERE parent_comment_id=? AND id<>?',(parent,cid,cid))
    # A self-reference must also be cleared when foreign keys are enabled.
    db.execute('UPDATE comments SET parent_comment_id=NULL WHERE id=?',(cid,))
    _comment_metadata(db,cid,tables)
    db.execute('DELETE FROM comments WHERE id=?',(cid,))


def remove_post(db, pid, actor):
    if not db.in_transaction:
        raise RuntimeError('Content deletion requires an explicit transaction')
    post = db.execute('SELECT user_id FROM posts WHERE id=?',(pid,)).fetchone()
    if not post or post['user_id'] != actor:
        raise DeletionBlocked('Post unavailable or not owned by this account.')
    comments = db.execute('SELECT id,user_id FROM comments WHERE post_id=?',(pid,)).fetchall()
    _preserved(db,[actor]+[c['user_id'] for c in comments])
    if db.execute('''SELECT 1 FROM comments child JOIN comments parent ON parent.id=child.parent_comment_id
                     WHERE parent.post_id=? AND child.post_id<>?''',(pid,pid)).fetchone():
        raise DeletionBlocked('This thread has inconsistent links and needs staff review.')
    tables = _tables(db)
    for comment in comments:
        _comment_metadata(db,comment['id'],tables)
    db.execute('UPDATE comments SET parent_comment_id=NULL WHERE post_id=?',(pid,))
    db.execute('DELETE FROM comments WHERE post_id=?',(pid,))
    # Explicit live-content dependencies only. Case evidence, reports and audit
    # records are immutable history and deliberately remain available to staff.
    if 'post_reactions' in tables:db.execute('DELETE FROM post_reactions WHERE post_id=?',(pid,))
    if 'post_vibes' in tables:db.execute('DELETE FROM post_vibes WHERE post_id=?',(pid,))
    if 'post_bookmarks' in tables:db.execute('DELETE FROM post_bookmarks WHERE post_id=?',(pid,))
    if 'post_edit_history' in tables:db.execute('DELETE FROM post_edit_history WHERE post_id=?',(pid,))
    if 'post_privacy' in tables:db.execute('DELETE FROM post_privacy WHERE post_id=?',(pid,))
    if 'moderated_posts' in tables:db.execute('DELETE FROM moderated_posts WHERE post_id=?',(pid,))
    if 'staff_announcements' in tables:db.execute('DELETE FROM staff_announcements WHERE post_id=?',(pid,))
    if 'protected_age_posts' in tables:db.execute('DELETE FROM protected_age_posts WHERE post_id=?',(pid,))
    if 'post_media' in tables:db.execute('DELETE FROM post_media WHERE post_id=?',(pid,))
    if 'circle_posts' in tables:db.execute('DELETE FROM circle_posts WHERE post_id=?',(pid,))
    if 'circle_post_visibility' in tables:db.execute('DELETE FROM circle_post_visibility WHERE post_id=?',(pid,))
    if 'post_share_permissions' in tables:db.execute('DELETE FROM post_share_permissions WHERE post_id=?',(pid,))
    if 'post_shares' in tables:db.execute('DELETE FROM post_shares WHERE share_post_id=?',(pid,))
    if 'circles' in tables:db.execute('UPDATE circles SET pinned_post_id=NULL WHERE pinned_post_id=?',(pid,))
    # Keep other people's share wrappers: their existing renderer shows that the
    # original is unavailable. Never unlink media files or remove case evidence.
    db.execute('DELETE FROM posts WHERE id=?',(pid,))
