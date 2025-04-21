from flask import Blueprint, request, session, redirect, flash, abort, current_app, g, render_template
from utils.friend_helpers import are_friends, get_friend_requests
import sqlite3

bp = Blueprint('friends', __name__)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

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
    return redirect(request.referrer or '/')



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
    return redirect(request.referrer or '/')

@bp.route('/send_friend_request/<int:user_id>', methods=['POST'])
def send_request(user_id):
    db = get_db()
    sender = session.get('user_id')
    if not sender or sender == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')
    db.execute('''
        INSERT OR IGNORE INTO friend_requests (sender_id, receiver_id, status)
        VALUES (?, ?, 'pending')
    ''', (sender, user_id))
    db.commit()
    flash("Friend request sent!", "success")
    return redirect(request.referrer or '/')

@bp.route('/accept_friend_request/<int:user_id>', methods=['POST'])
def accept_friend(user_id):
    db = get_db()
    receiver = session.get('user_id')
    if not receiver or receiver == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')
    db.execute('''
        UPDATE friend_requests
        SET status = 'accepted', updated_at = CURRENT_TIMESTAMP
        WHERE sender_id = ? AND receiver_id = ? AND status = 'pending'
    ''', (user_id, receiver))
    db.commit()
    flash("Friend request accepted!", "success")
    return redirect(request.referrer or '/')

@bp.route('/decline_friend_request/<int:user_id>', methods=['POST'])
def decline_friend(user_id):
    db = get_db()
    receiver = session.get('user_id')
    if not receiver or receiver == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')
    db.execute('''
        UPDATE friend_requests
        SET status = 'declined', updated_at = CURRENT_TIMESTAMP
        WHERE sender_id = ? AND receiver_id = ? AND status = 'pending'
    ''', (user_id, receiver))
    db.commit()
    flash("Friend request declined.", "info")
    return redirect(request.referrer or '/')

@bp.route('/remove_friend/<int:user_id>', methods=['POST'])
def remove_friend(user_id):
    db = get_db()
    uid = session.get('user_id')
    if not uid or uid == user_id:
        flash("Invalid operation.", "error")
        return redirect('/')
    db.execute('''
        DELETE FROM friend_requests
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
    ''', (uid, user_id, user_id, uid))
    db.commit()
    flash("Friend removed.", "info")
    return redirect(request.referrer or '/')

@bp.route('/friends')
def friends_page():
    if 'user_id' not in session:
        flash("Please log in to view your friends.", "error")
        return redirect('/login')

    db = get_db()
    viewer_id = session['user_id']

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

    friends = db.execute('''
        SELECT users.id, users.handle, friend_requests.created_at
        FROM friend_requests
        JOIN users ON
            (users.id = friend_requests.sender_id AND friend_requests.receiver_id = ?)
            OR
            (users.id = friend_requests.receiver_id AND friend_requests.sender_id = ?)
        WHERE status = 'accepted'
    ''', (viewer_id, viewer_id)).fetchall()

    return render_template('friends.html',
                           incoming=incoming,
                           outgoing=outgoing,
                           friends=friends)
