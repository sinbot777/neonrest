from flask import g, current_app
import sqlite3

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

def are_friends(db, user_a, user_b):
    result = db.execute('''
        SELECT 1 FROM friend_requests
        WHERE ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))
        AND status = 'accepted'
    ''', (user_a, user_b, user_b, user_a)).fetchone()
    return bool(result)

def get_friend_requests(viewer_id):
    db = get_db()

    incoming = db.execute('''
        SELECT fr.sender_id, u.handle AS sender_handle, fr.created_at
        FROM friend_requests fr
        JOIN users u ON fr.sender_id = u.id
        WHERE fr.receiver_id = ? AND fr.status = 'pending'
    ''', (viewer_id,)).fetchall()

    outgoing = db.execute('''
        SELECT fr.receiver_id, u.handle AS receiver_handle, fr.created_at
        FROM friend_requests fr
        JOIN users u ON fr.receiver_id = u.id
        WHERE fr.sender_id = ? AND fr.status = 'pending'
    ''', (viewer_id,)).fetchall()

    return incoming, outgoing

def get_following_map(viewer_id):
    db = get_db()
    rows = db.execute('SELECT followed_id FROM follows WHERE follower_id = ? AND revoked = 0', (viewer_id,)).fetchall()
    return {row['followed_id']: True for row in rows}

def get_friend_status_map(viewer_id):
    db = get_db()
    statuses = db.execute('''
        SELECT
            CASE
                WHEN sender_id = ? THEN receiver_id
                ELSE sender_id
            END AS other_user_id,
            status
        FROM friend_requests
        WHERE sender_id = ? OR receiver_id = ?
    ''', (viewer_id, viewer_id, viewer_id)).fetchall()

    return {row['other_user_id']: row['status'] for row in statuses}

def get_top_friends(db, user_id):
    rows = db.execute('''
        SELECT u.id, u.handle, u.codename, u.avatar_path
        FROM top_friends tf
        JOIN users u ON u.id = tf.friend_id
        WHERE tf.user_id = ?
        ORDER BY tf.position_t9
    ''', (user_id,)).fetchall()

    friends = []
    for row in rows:
        friends.append({
            "id": row["id"],
            "handle": row["handle"],
            "codename": row["codename"],
            "avatar_path": f"/{row['avatar_path'].lstrip('/')}" if row["avatar_path"] else None,
            "placeholder": False
        })

    # Fill in blank slots
    while len(friends) < 9:
        friends.append({"placeholder": True})

    return friends


def set_top_friend(db, user_id, friend_id, position):
    db.execute('''
        INSERT INTO top_friends (user_id, friend_id, position_t9)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, friend_id)
        DO UPDATE SET position_t9 = excluded.position_t9
    ''', (user_id, friend_id, position))
    db.commit()

def remove_top_friend(db, user_id, friend_id):
    db.execute('''
        DELETE FROM top_friends
        WHERE user_id = ? AND friend_id = ?
    ''', (user_id, friend_id))
    db.commit()


