"""Welcome friendship and explicit public staff announcements."""
from flask import session, abort, current_app

def staff(db, uid):
    from neonrest_sandbox import app as core
    return bool(uid and core.has_staff_permission(db,uid,'moderate_posts'))

def announcement(db,pid):
    row=db.execute('SELECT p.user_id,p.target_user_id FROM posts p JOIN staff_announcements a ON a.post_id=p.id WHERE p.id=?',(pid,)).fetchone()
    privacy=db.execute('SELECT audience FROM post_privacy WHERE post_id=?',(pid,)).fetchone()
    from neonrest_sandbox import age_policy as ages
    return bool(row and staff(db,row['user_id']) and ages.age(db,row['user_id']) is not None and ages.age(db,row['user_id'])>=18 and (not row['target_user_id'] or row['target_user_id']==row['user_id']) and (not privacy or privacy['audience']=='public'))

def personal_hidden(db,owner,viewer):
    from neonrest_sandbox import age_policy as ages
    a=ages.age(db,viewer) if viewer else None
    row=db.execute('SELECT handle FROM users WHERE id=?',(owner,)).fetchone()
    return bool(a is not None and a<18 and row and row['handle'].lower().lstrip('@')=='brendoom' and not ages.family(db,owner,viewer) and not staff(db,viewer))

def require_recent(db,uid):
    from flask import request, redirect, url_for, flash
    import json,time
    if not staff(db,uid): abort(403)
    if current_app.extensions['privileged_fresh'](): return
    db.execute('CREATE TABLE IF NOT EXISTS authorization_post_drafts(user_id INTEGER,path TEXT,fields TEXT,created_at INTEGER,PRIMARY KEY(user_id,path))')
    fields={k:request.form[k] for k in ('content','vibes','circle','audience','target_user_id','staff_announcement') if k in request.form}
    db.execute('DELETE FROM authorization_post_drafts WHERE created_at<?',(int(time.time())-3600,))
    if len(json.dumps(fields))<=100000:
        db.execute('INSERT OR REPLACE INTO authorization_post_drafts VALUES (?,?,?,?)',(uid,request.path,json.dumps(fields),int(time.time())))
    db.commit()
    flash('Confirm your password and verification code to continue. Your post text is saved; reattach any files after returning.','info')
    abort(redirect(url_for('community_reauth',next=request.path)))

def post_draft():
    from flask import request
    from neonrest_sandbox import app as core
    import json,time
    if request.method!='GET' or request.endpoint not in ('create_post','edit_post') or not session.get('user_id') or not current_app.extensions['privileged_fresh'](): return {}
    db=core.get_db()
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='authorization_post_drafts'").fetchone(): return {}
    row=db.execute('SELECT fields,created_at FROM authorization_post_drafts WHERE user_id=? AND path=?',(session['user_id'],request.path)).fetchone()
    return json.loads(row['fields']) if row and row['created_at']>=time.time()-3600 else {}

def validate_flag(db,uid):
    from flask import request
    pid=(request.view_args or {}).get('post_id')
    existing=pid and db.execute('SELECT 1 FROM staff_announcements WHERE post_id=?',(pid,)).fetchone()
    if 'staff_announcement' in request.form or existing: require_recent(db,uid)

def save_flag(db,pid,uid):
    from flask import request
    wanted=request.form.get('staff_announcement')=='1'
    existing=db.execute('SELECT 1 FROM staff_announcements WHERE post_id=?',(pid,)).fetchone()
    if wanted:
        row=db.execute('SELECT user_id,target_user_id FROM posts WHERE id=?',(pid,)).fetchone()
        privacy=db.execute('SELECT audience FROM post_privacy WHERE post_id=?',(pid,)).fetchone()
        if not staff(db,uid) or row['user_id']!=uid or (row['target_user_id'] and row['target_user_id']!=uid) or (privacy and privacy['audience']!='public'): abort(400,'Staff announcements must be public posts on your own profile.')
        db.execute('INSERT OR IGNORE INTO staff_announcements(post_id) VALUES (?)',(pid,))
    elif existing:
        from neonrest_sandbox import community_features as cf
        require_recent(db,uid)
        db.execute('DELETE FROM staff_announcements WHERE post_id=?',(pid,))
    from flask import request
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='authorization_post_drafts'").fetchone():
        db.execute('DELETE FROM authorization_post_drafts WHERE user_id=? AND path=?',(uid,request.path))
    if wanted or existing: db.execute("INSERT INTO operations_events(kind,detail) VALUES ('staff-announcement',?)",(str(uid)+':'+str(pid)+':'+str(wanted),))

def add_welcome_friend(db,uid):
    founder=db.execute("SELECT id FROM users WHERE lower(handle)='@brendoom'").fetchone()
    if not founder or founder['id']==uid: return
    fid=founder['id']
    if db.execute('SELECT 1 FROM friend_requests WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)',(fid,uid,uid,fid)).fetchone(): return
    db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(fid,uid))
    db.execute('UPDATE top_friends SET position_t9=position_t9+1 WHERE user_id=?',(uid,))
    db.execute('INSERT OR IGNORE INTO top_friends VALUES (?,?,1)',(uid,fid))
