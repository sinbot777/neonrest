"""Optional one-way follows and private friend labels; never Circle membership."""
import hmac
import re
import sqlite3
import unicodedata
from flask import abort, flash, g, redirect, render_template, request, session, url_for
from . import age_policy as ages
from .request_cache import request_lookup

BASE_POST_AUDIENCES = ('public', 'friends', 'connections', 'private')


def bounded_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 9223372036854775807


def initialize(db):
    for sql in (
        'CREATE TABLE IF NOT EXISTS follow_preferences(user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)))',
        'CREATE TABLE IF NOT EXISTS follower_exclusions(user_id INTEGER NOT NULL,target_id INTEGER NOT NULL,PRIMARY KEY(user_id,target_id))',
        '''CREATE TABLE IF NOT EXISTS friend_labels(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,
           name TEXT NOT NULL,name_key TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
           UNIQUE(user_id,name_key),UNIQUE(user_id,id))''',
        '''CREATE TABLE IF NOT EXISTS friend_label_members(user_id INTEGER NOT NULL,label_id INTEGER NOT NULL,friend_id INTEGER NOT NULL,
           PRIMARY KEY(user_id,label_id,friend_id),FOREIGN KEY(user_id,label_id) REFERENCES friend_labels(user_id,id))''',
        'CREATE INDEX IF NOT EXISTS idx_followers_active ON follows(followed_id,revoked,follower_id)',
        'CREATE INDEX IF NOT EXISTS idx_friend_labels_member ON friend_label_members(friend_id,user_id)',
    ):
        db.execute(sql)
    db.commit()


@request_lookup
def follows_enabled(db, owner):
    row = db.execute('SELECT enabled FROM follow_preferences WHERE user_id=?', (owner,)).fetchone()
    return row is None or bool(row['enabled'])


@request_lookup
def can_follow(db, follower, owner):
    from .community_features import audience_allows, blocked, member_visible, settings
    if not bounded_id(follower) or not bounded_id(owner) or follower == owner or not follows_enabled(db, owner):
        return False
    if db.execute('SELECT 1 FROM follower_exclusions WHERE user_id=? AND target_id=?', (owner, follower)).fetchone():
        return False
    for uid in (follower, owner):
        if not db.execute('SELECT 1 FROM users WHERE id=? AND verified=1', (uid,)).fetchone():
            return False
        if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (banned=1 OR interaction_restricted=1)', (uid,)).fetchone():
            return False
        if db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1', (uid,)).fetchone():
            return False
        if db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1', (uid,)).fetchone():
            return False
    return (not blocked(db, follower, owner) and member_visible(db, owner, follower)
            and audience_allows(db, owner, follower, settings(db, owner)['profile_audience'])
            and ages.contact(db, follower, owner))


@request_lookup
def active_follow(db, follower, owner):
    return bool(can_follow(db, follower, owner) and db.execute(
        'SELECT 1 FROM follows WHERE follower_id=? AND followed_id=? AND revoked=0', (follower, owner)).fetchone())


@request_lookup
def labels_for(db, uid, archived=False):
    return db.execute('SELECT id,name,archived FROM friend_labels WHERE user_id=? AND archived=? ORDER BY name_key,id',
                      (uid, int(archived))).fetchall()


def label_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'label:[1-9][0-9]{0,17}', value):
        return None
    return int(value[6:])


def valid_post_audience(db, uid, value, keep_archived=False):
    return value in BASE_POST_AUDIENCES or bool(label_id(value) and db.execute(
        'SELECT 1 FROM friend_labels WHERE id=? AND user_id=? AND (archived=0 OR ?)', (label_id(value), uid, int(keep_archived))).fetchone())


@request_lookup
def post_audience_allows(db, owner, viewer, audience):
    from .community_features import audience_allows, friends
    if audience == 'connections':
        return audience_allows(db, owner, viewer, 'friends') or active_follow(db, viewer, owner)
    lid = label_id(audience)
    if lid:
        return bool(owner == viewer or (friends(db, owner, viewer) and db.execute('''SELECT 1 FROM friend_label_members m
            JOIN friend_labels l ON l.id=m.label_id AND l.user_id=m.user_id
            WHERE l.id=? AND l.user_id=? AND l.archived=0 AND m.friend_id=?''', (lid, owner, viewer)).fetchone()))
    return audience_allows(db, owner, viewer, audience)


def clear_pair_labels(db, first, second):
    db.execute('DELETE FROM friend_label_members WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)',
               (first, second, second, first))


def erase_user(db, uid):
    db.execute('DELETE FROM friend_label_members WHERE user_id=? OR friend_id=?', (uid, uid))
    db.execute('DELETE FROM friend_labels WHERE user_id=?', (uid,))
    db.execute('DELETE FROM follower_exclusions WHERE user_id=? OR target_id=?', (uid, uid))
    db.execute('DELETE FROM follow_preferences WHERE user_id=?', (uid,))


def export_user(db, uid):
    return {table: [dict(row) for row in db.execute('SELECT * FROM '+table+' WHERE user_id=?', (uid,))]
            for table in ('follow_preferences', 'follower_exclusions', 'friend_labels', 'friend_label_members')}


def register(app, core):
    from .community_features import friends
    with app.app_context():
        initialize(core.get_db())

    def current(write=False):
        uid = session.get('user_id')
        if not uid or not core.get_db().execute('SELECT 1 FROM users WHERE id=? AND email=? AND verified=1',
                                                (uid, session.get('user_email'))).fetchone():
            abort(401)
        if write:
            app.extensions['community_auth_helpers']['csrf']()
        return uid

    def limited(action):
        return app.extensions['community_auth_helpers']['limited']('connections:'+action, 120, 3600)

    def follow(user_id):
        uid = current(True)
        expected = session.get('friend_csrf_token', '')
        if not expected or not hmac.compare_digest(expected, request.form.get('friend_csrf_token', '')):
            abort(400)
        response = limited('follow')
        if response is not None:
            return response
        db = core.get_db()
        db.execute('BEGIN IMMEDIATE')
        if not can_follow(db, uid, user_id):
            abort(403, description='Following is not available for this account.')
        # Older deployed schemas lack the newer UNIQUE constraint. The first
        # write reserves SQLite's writer slot through commit, so concurrent
        # follow attempts cannot both observe a missing relationship.
        updated = db.execute('UPDATE follows SET revoked=0 WHERE follower_id=? AND followed_id=?', (uid, user_id))
        if not updated.rowcount:
            db.execute('INSERT INTO follows(follower_id,followed_id,revoked) VALUES (?,?,0)', (uid, user_id))
        db.commit()
        flash('You are now following this person. Their post audiences still apply.', 'success')
        return redirect(url_for('connections_page'))

    app.view_functions['friends.follow'] = follow

    def unfollow(user_id):
        uid = current(True)
        if not bounded_id(user_id):
            abort(400)
        db = core.get_db()
        db.execute('UPDATE follows SET revoked=1 WHERE follower_id=? AND followed_id=?', (uid, user_id))
        db.commit()
        flash('Unfollowed.', 'info')
        return redirect(url_for('connections_page'))

    app.view_functions['friends.unfollow'] = unfollow

    @app.route('/account/connections', methods=['GET', 'POST'])
    def connections_page():
        uid = current(request.method == 'POST')
        db = core.get_db()
        if request.method == 'POST':
            response = limited('settings')
            if response is not None:
                return response
            db.execute('BEGIN IMMEDIATE')
            action = request.form.get('action')
            if action == 'following':
                enabled = request.form.get('enabled') == '1'
                db.execute('INSERT INTO follow_preferences VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled', (uid, int(enabled)))
                if not enabled:
                    db.execute('UPDATE follows SET revoked=1 WHERE followed_id=?', (uid,))
            elif action in ('remove-follower', 'allow-follower'):
                target = request.form.get('target_id', type=int)
                if not bounded_id(target) or target == uid:
                    abort(400)
                if action == 'remove-follower':
                    if not db.execute('SELECT 1 FROM follows WHERE follower_id=? AND followed_id=? AND revoked=0', (target, uid)).fetchone():
                        abort(404)
                    db.execute('UPDATE follows SET revoked=1 WHERE follower_id=? AND followed_id=?', (target, uid))
                    db.execute('INSERT OR IGNORE INTO follower_exclusions VALUES (?,?)', (uid, target))
                else:
                    db.execute('DELETE FROM follower_exclusions WHERE user_id=? AND target_id=?', (uid, target))
            else:
                abort(400)
            db.commit()
            flash('Following settings saved. Friends and public post visibility are unchanged.', 'success')
            return redirect(url_for('connections_page'))
        def page(kind):
            index = request.args.get(kind+'_page', 1, type=int)
            if index is None or not 1 <= index <= 100000:
                abort(400)
            incoming = kind == 'followers'
            peer, own = ('follower_id', 'followed_id') if incoming else ('followed_id', 'follower_id')
            rows = db.execute('SELECT u.id,u.handle FROM follows f JOIN users u ON u.id=f.'+peer+
                ' WHERE f.'+own+'=? AND f.revoked=0 AND community_profile_visible(u.id)=1 ORDER BY u.id LIMIT 21 OFFSET ?',
                (uid, (index-1)*20)).fetchall()
            return rows[:20], index, len(rows)>20
        excluded_page = request.args.get('excluded_page', 1, type=int)
        if excluded_page is None or not 1 <= excluded_page <= 100000:
            abort(400)
        excluded = db.execute('''SELECT u.id,u.handle FROM follower_exclusions e JOIN users u ON u.id=e.target_id
            WHERE e.user_id=? AND community_profile_visible(u.id)=1 ORDER BY u.id LIMIT 21 OFFSET ?''',
            (uid, (excluded_page-1)*20)).fetchall()
        return render_template('connections.html', enabled=follows_enabled(db, uid), followers=page('followers'),
            following=page('following'), labels=labels_for(db, uid), archived_labels=labels_for(db, uid, True),
            exclusions=(excluded[:20], excluded_page, len(excluded)>20))

    @app.route('/friends/labels', methods=['POST'])
    def connection_label():
        uid = current(True)
        response = limited('labels')
        if response is not None:
            return response
        db = core.get_db()
        db.execute('BEGIN IMMEDIATE')
        action = request.form.get('action')
        lid = request.form.get('label_id', type=int)
        if action != 'create' and (not bounded_id(lid) or not db.execute('SELECT 1 FROM friend_labels WHERE id=? AND user_id=?', (lid, uid)).fetchone()):
            abort(404)
        if action in ('create', 'rename'):
            raw_name = request.form.get('name', '')
            if len(raw_name) > 200:
                abort(400, description='Use a label from 1 to 40 characters.')
            name = unicodedata.normalize('NFKC', raw_name)
            if any(unicodedata.category(ch).startswith('C') for ch in name):
                abort(400, description='Use a label without control characters.')
            name = ' '.join(name.split())
            if not 1 <= len(name) <= 40:
                abort(400, description='Use a label from 1 to 40 characters.')
            if action == 'create':
                if db.execute('SELECT COUNT(*) FROM friend_labels WHERE user_id=?', (uid,)).fetchone()[0] >= 32:
                    abort(400, description='You can keep up to 32 labels, including archived labels.')
                sql, args = 'INSERT INTO friend_labels(user_id,name,name_key) VALUES (?,?,?)', (uid, name, name.casefold())
            else:
                sql, args = 'UPDATE friend_labels SET name=?,name_key=? WHERE id=? AND user_id=?', (name, name.casefold(), lid, uid)
            try:
                db.execute(sql, args)
            except sqlite3.IntegrityError:
                abort(400, description='You already have a label with that name.')
        elif action in ('archive', 'restore'):
            db.execute('UPDATE friend_labels SET archived=? WHERE id=? AND user_id=?', (int(action == 'archive'), lid, uid))
            if action == 'archive':
                db.execute("UPDATE privacy_settings SET post_audience='private' WHERE user_id=? AND post_audience=?", (uid, 'label:'+str(lid)))
        elif action in ('assign', 'unassign'):
            peer = request.form.get('friend_id', type=int)
            from .community_features import member_visible
            if (not bounded_id(peer) or not friends(db, uid, peer) or not member_visible(db, peer, uid)
                    or not db.execute('SELECT 1 FROM friend_labels WHERE id=? AND user_id=? AND archived=0', (lid, uid)).fetchone()):
                abort(400)
            if action == 'assign':
                db.execute('INSERT OR IGNORE INTO friend_label_members VALUES (?,?,?)', (uid, lid, peer))
            else:
                db.execute('DELETE FROM friend_label_members WHERE user_id=? AND label_id=? AND friend_id=?', (uid, lid, peer))
        else:
            abort(400)
        db.commit()
        flash('Private friend labels saved.', 'success')
        return redirect(url_for('friends.friends_page') if action in ('assign','unassign') else url_for('connections_page'))

    @app.context_processor
    def context():
        uid = session.get('user_id')
        def choices(current=None):
            values = [('public','Public'),('friends','Friends'),('connections','Friends and followers'),('private','Only me')] + [
                ('label:'+str(row['id']), 'Friend label: '+row['name']) for row in labels_for(core.get_db(), uid)] if uid else []
            if current and current not in {value for value, title in values}:
                values.append((current, 'Unavailable friend label — only you'))
            return values
        @request_lookup
        def private_labels(db, owner):
            rows = db.execute('''SELECT m.friend_id,l.id,l.name FROM friend_label_members m JOIN friend_labels l
                ON l.user_id=m.user_id AND l.id=m.label_id WHERE m.user_id=? AND l.archived=0 ORDER BY l.name_key''', (owner,)).fetchall()
            result = {}
            for row in rows:
                result.setdefault(row['friend_id'], []).append(row)
            return result
        return {'connection_can_follow': lambda target: can_follow(core.get_db(), uid, target),
                'connection_is_following': lambda target: active_follow(core.get_db(), uid, target),
                'connection_post_choices': choices,
                'connection_labels': lambda: labels_for(core.get_db(), uid),
                'connection_friend_labels': lambda: private_labels(core.get_db(), uid)}
