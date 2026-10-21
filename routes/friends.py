from flask import Blueprint, request, session, redirect, flash, abort, current_app, g, render_template
from neonrest_sandbox.utils.friend_helpers import are_friends, get_friend_requests
import sqlite3
from neonrest_sandbox.community_features import register_db_functions
import secrets
import hmac
from flask import jsonify
from flask import url_for

bp = Blueprint('friends', __name__)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        register_db_functions(g.db)
    return g.db

def friend_csrf_token():
    if 'friend_csrf_token' not in session:
        session['friend_csrf_token'] = secrets.token_urlsafe(32)
    return session['friend_csrf_token']

@bp.app_context_processor
def inject_friend_token():
    return {'friend_csrf_token': friend_csrf_token}

def checked_viewer():
    uid = session.get('user_id')
    email = session.get('user_email')
    if not uid or not email:
        abort(401)
    user = get_db().execute('SELECT id FROM users WHERE id = ? AND email = ?', (uid, email)).fetchone()
    if not user:
        abort(401)
    return uid

def check_friend_post():
    viewer = checked_viewer()
    expected = session.get('friend_csrf_token', '')
    submitted = request.form.get('friend_csrf_token', '')
    if not expected or not hmac.compare_digest(expected, submitted):
        abort(400)
    return viewer

def friends_for(db, uid):
    return db.execute('''SELECT DISTINCT u.id, u.handle, u.codename, u.avatar_path
        FROM users u JOIN friend_requests fr ON
        ((fr.sender_id = ? AND fr.receiver_id = u.id) OR
         (fr.receiver_id = ? AND fr.sender_id = u.id))
        WHERE fr.status = 'accepted' AND community_profile_visible(u.id)=1 ORDER BY u.handle COLLATE NOCASE''', (uid, uid)).fetchall()

def return_to_friends():
    return redirect(url_for('friends.friends_page'))

@bp.route('/follow/<int:user_id>', methods=['POST'])
def follow(user_id):
    follower = session.get('user_id')
    print(f"🔍 Attempting follow: session user = {follower}, target = {user_id}")

    if not follower or follower == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')

    db = get_db()
    db.execute('''
        INSERT OR IGNORE INTO follows (follower_id, followed_id)
        VALUES (?, ?)
    ''', (follower, user_id))
    db.commit()
    flash("You are now following this user.", "success")
    return return_to_friends()



@bp.route('/unfollow/<int:user_id>', methods=['POST'])
def unfollow(user_id):
    db = get_db()
    follower = session.get('user_id')
    if not follower or follower == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')
    db.execute('UPDATE follows SET revoked = 1 WHERE follower_id = ? AND followed_id = ?', (follower, user_id))
    db.commit()
    flash("Unfollowed.", "info")
    return return_to_friends()

@bp.route('/send_friend_request/<int:user_id>', methods=['POST'])
def send_request(user_id):
    sender = check_friend_post()
    if sender == user_id:
        abort(400)
    db = get_db()
    if not db.execute('SELECT 1 FROM users WHERE id = ?', (user_id,)).fetchone():
        abort(404)
    existing = db.execute('''SELECT sender_id, receiver_id, status FROM friend_requests
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)''',
        (sender, user_id, user_id, sender)).fetchall()
    if any(row['status'] in ('pending', 'accepted') for row in existing):
        flash('A request or friendship already exists.', 'info')
    else:
        db.execute('DELETE FROM friend_requests WHERE sender_id = ? AND receiver_id = ?', (sender, user_id))
        db.execute('''INSERT INTO friend_requests (sender_id, receiver_id, status)
            VALUES (?, ?, 'pending')''', (sender, user_id))
        from neonrest_sandbox.community_features import notify
        notify(db, user_id, 'friends', 'You received a friend request.', '/friends', sender)
        db.commit()
        flash('Friend request sent!', 'success')
    return return_to_friends()

@bp.route('/accept_friend_request/<int:user_id>', methods=['POST'])
def accept_friend(user_id):
    receiver = check_friend_post()
    db = get_db()
    result = db.execute('''UPDATE friend_requests SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE sender_id = ? AND receiver_id = ? AND status = 'pending' ''', (user_id, receiver))
    if result.rowcount:
        from neonrest_sandbox.community_features import notify
        notify(db, user_id, 'friends', 'Your friend request was accepted.', '/friends', receiver)
    db.commit()
    flash('Friend request accepted!' if result.rowcount else 'Request no longer available.', 'info')
    return return_to_friends()

@bp.route('/decline_friend_request/<int:user_id>', methods=['POST'])
def decline_friend(user_id):
    receiver = check_friend_post()
    db = get_db()
    db.execute('''UPDATE friend_requests SET status = 'declined', updated_at = CURRENT_TIMESTAMP
        WHERE sender_id = ? AND receiver_id = ? AND status = 'pending' ''', (user_id, receiver))
    db.commit()
    flash('Friend request declined.', 'info')
    return return_to_friends()

@bp.route('/remove_friend/<int:user_id>', methods=['POST'])
def remove_friend(user_id):
    uid = check_friend_post()
    db = get_db()
    db.execute('''DELETE FROM friend_requests WHERE status = 'accepted' AND
        ((sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?))''',
        (uid, user_id, user_id, uid))
    db.execute('DELETE FROM top_friends WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)',
               (uid, user_id, user_id, uid))
    db.commit()
    flash('Friend removed.', 'info')
    return return_to_friends()

@bp.route('/update_top9', methods=['POST'])
def update_top9():
    uid = check_friend_post()
    raw = [request.form.get(f'slot_{i}', '') for i in range(1, 10)]
    if any(value and not value.isdigit() for value in raw):
        abort(400)
    selected = [int(value) for value in raw if value]
    if len(selected) != len(set(selected)) or uid in selected:
        abort(400)
    db = get_db()
    valid = {row['id'] for row in friends_for(db, uid)}
    if not set(selected).issubset(valid):
        abort(400)
    with db:
        db.execute('DELETE FROM top_friends WHERE user_id = ?', (uid,))
        for index, value in enumerate(raw, 1):
            if value:
                db.execute('INSERT INTO top_friends (user_id, friend_id, position_t9) VALUES (?, ?, ?)',
                           (uid, int(value), index))
    if request.accept_mimetypes.best == 'application/json':
        return jsonify({'success': True})
    flash('Top 9 saved.', 'success')
    return return_to_friends()

@bp.route('/friends/<handle>')
def public_friends(handle):
    db = get_db()
    user = db.execute('SELECT id, handle FROM users WHERE lower(ltrim(handle, "@")) = lower(?)',
                      (handle.lstrip('@'),)).fetchone()
    if not user or not db.execute('SELECT community_profile_visible(?)',(user['id'],)).fetchone()[0]:
        abort(404)
    return render_template('friends.html', owner=user, friends=friends_for(db, user['id']),
                           editable=False)

@bp.route('/friends')
def friends_page():
    viewer_id = checked_viewer()

    db = get_db()

    incoming = db.execute('''
        SELECT users.id, users.handle, friend_requests.created_at
        FROM friend_requests
        JOIN users ON users.id = friend_requests.sender_id
        WHERE receiver_id = ? AND status = 'pending'
    ''', (viewer_id,)).fetchall()

    outgoing = db.execute('''
        SELECT users.id, users.handle, friend_requests.created_at
        FROM friend_requests
        JOIN users ON users.id = friend_requests.receiver_id
        WHERE sender_id = ? AND status = 'pending'
    ''', (viewer_id,)).fetchall()

    from neonrest_sandbox.community_features import member_visible, blocked
    from neonrest_sandbox import age_policy as ages
    def eligible(row):
        return member_visible(db,row['id'],viewer_id) and not blocked(db,viewer_id,row['id']) and ages.contact(db,viewer_id,row['id'],invitation=True)
    incoming = [row for row in incoming if eligible(row)]
    outgoing = [row for row in outgoing if eligible(row)]
    owner = db.execute('SELECT id, handle FROM users WHERE id = ?', (viewer_id,)).fetchone()
    friends = friends_for(db, viewer_id)
    slots = {row['position_t9']: row['friend_id'] for row in db.execute(
        'SELECT position_t9, friend_id FROM top_friends WHERE user_id = ?', (viewer_id,)).fetchall()}
    return render_template('friends.html', owner=owner, incoming=incoming,
                           outgoing=outgoing, friends=friends, slots=slots, editable=True)
