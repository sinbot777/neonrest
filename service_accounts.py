"""Human-operated service identities. No login, inbox, or private-reader authority."""
import hashlib, json, re, secrets, sqlite3, time
from .request_cache import request_lookup
from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for


def initialize(db):
    for sql in (
        '''CREATE TABLE IF NOT EXISTS service_accounts(user_id INTEGER PRIMARY KEY REFERENCES users(id),
           owner_id INTEGER NOT NULL REFERENCES users(id),purpose TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
           revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS service_operators(service_id INTEGER NOT NULL REFERENCES service_accounts(user_id),
           user_id INTEGER NOT NULL REFERENCES users(id),publish_guidance INTEGER NOT NULL DEFAULT 0,
           PRIMARY KEY(service_id,user_id))''',
        '''CREATE TABLE IF NOT EXISTS service_publications(post_id INTEGER PRIMARY KEY REFERENCES posts(id),
           service_id INTEGER NOT NULL REFERENCES service_accounts(user_id),actor_id INTEGER NOT NULL REFERENCES users(id),
           request_key TEXT NOT NULL,content_sha256 TEXT NOT NULL,created_at INTEGER NOT NULL,
           UNIQUE(service_id,request_key))''',
        '''CREATE TABLE IF NOT EXISTS service_audit(id INTEGER PRIMARY KEY,service_id INTEGER NOT NULL,
           actor_id INTEGER NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created_at INTEGER NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS service_publications_service ON service_publications(service_id,post_id)',
    ): db.execute(sql)


@request_lookup
def get(db, uid):
    if not uid:return None
    try:return db.execute('SELECT * FROM service_accounts WHERE user_id=?',(uid,)).fetchone()
    except sqlite3.OperationalError as e:
        # During older additive startup migrations this table may not exist yet.
        if 'no such table: service_accounts' in str(e):return None
        raise


def human(db, uid, factor=False):
    if not uid or get(db,uid):return False
    from . import age_policy as ages
    row=db.execute('SELECT verified FROM users WHERE id=?',(uid,)).fetchone()
    if not row or not row['verified'] or (ages.age(db,uid) or 0)<18:return False
    for table,flag in [('account_safety','inactive'),('account_disables','disabled'),('user_moderation','banned'),('user_moderation','posting_restricted'),('reserved_accounts','disabled')]:
        if db.execute('SELECT 1 FROM '+table+' WHERE user_id=? AND '+flag+'=1',(uid,)).fetchone():return False
    return not factor or bool(db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND totp_secret IS NOT NULL AND totp_secret<>?',(uid,'')).fetchone())


def active(db, record):
    if not record or not record['enabled'] or not human(db,record['owner_id']):return False
    uid=record['user_id']
    if not db.execute('SELECT 1 FROM users WHERE id=? AND verified=1',(uid,)).fetchone():return False
    for table,flag in [('account_safety','inactive'),('account_disables','disabled'),('user_moderation','banned'),('user_moderation','posting_restricted'),('reserved_accounts','disabled')]:
        if db.execute('SELECT 1 FROM '+table+' WHERE user_id=? AND '+flag+'=1',(uid,)).fetchone():return False
    return True


def public_profile(db, uid, viewer):
    if not active(db,get(db,uid)) or get(db,viewer):return False
    if viewer and db.execute('SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',(uid,viewer,viewer,uid)).fetchone():return False
    from . import age_policy as ages
    return not viewer or ages.ready(db,viewer)


def public_post(db, pid, viewer):
    row=db.execute('''SELECT p.*,s.content_sha256,s.service_id FROM service_publications s
        JOIN posts p ON p.id=s.post_id WHERE p.id=?''',(pid,)).fetchone()
    if not row or row['user_id']!=row['service_id'] or row['target_user_id']!=row['service_id']:return False
    if not public_profile(db,row['service_id'],viewer):return False
    privacy=db.execute('SELECT audience FROM post_privacy WHERE post_id=?',(pid,)).fetchone()
    return bool(privacy and privacy[0]=='public' and row['circle']=='public' and
        hashlib.sha256(row['content'].encode()).hexdigest()==row['content_sha256'] and
        not db.execute('SELECT 1 FROM circle_posts WHERE post_id=?',(pid,)).fetchone())


def audit(db, sid, actor, action, detail):
    db.execute('INSERT INTO service_audit(service_id,actor_id,action,detail,created_at) VALUES (?,?,?,?,?)',
        (sid,actor,action,detail,int(time.time())))


def create(db, core, actor, owner, purpose, handle='', existing=None):
    if not human(db,actor,True) or not core.has_staff_permission(db,actor,'manage_roles'):raise ValueError('Administrator permission and a protected human account are required.')
    if not human(db,owner,True):raise ValueError('Choose an eligible adult owner with two-factor authentication.')
    purpose=purpose.strip()
    if not 10<=len(purpose)<=500:raise ValueError('Describe this service in 10–500 characters.')
    if db.execute('SELECT count(*) FROM service_accounts').fetchone()[0]>=50:raise ValueError('Service capacity reached.')
    if existing:
        row=db.execute('SELECT * FROM users WHERE id=?',(existing,)).fetchone()
        if not row or not row['verified'] or row['dob'] or get(db,existing) or existing==owner:raise ValueError('Only a verified unused identity without a birthday can be converted.')
        # Never convert an age-identified human or an identity with content/private/staff authority.
        # Existing welcome-friend links are retained, but contact() denies every service interaction.
        for sql in ['SELECT 1 FROM posts WHERE user_id=? OR target_user_id=?','SELECT 1 FROM comments WHERE user_id=?',
                    'SELECT 1 FROM staff_roles WHERE user_id=?','SELECT 1 FROM circle_members WHERE user_id=?',
                    'SELECT 1 FROM identity_pages WHERE owner_id=?']:
            if db.execute(sql,(existing,)*sql.count('?')).fetchone():raise ValueError('This identity has existing content or delegated authority; conversion requires review.')
        for table,column in [('vibe_editors','user_id'),('family_links','parent_id'),('family_links','child_id'),('identity_page_members','user_id')]:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() and db.execute('SELECT 1 FROM '+table+' WHERE '+column+'=?',(existing,)).fetchone():raise ValueError('This identity has existing delegated authority; conversion requires review.')
        sid=existing
    else:
        handle=handle.strip().lstrip('@')
        if not re.fullmatch(r'[A-Za-z0-9_]{3,40}',handle):raise ValueError('Use a unique service handle of 3–40 letters, digits or underscores.')
        if db.execute("SELECT 1 FROM users WHERE lower(ltrim(handle,'@'))=lower(?)",(handle,)).fetchone():raise ValueError('That handle is unavailable.')
        sid=db.execute('INSERT INTO users(handle,email,password_hash,verified,created_at) VALUES (?,?,?,1,CURRENT_TIMESTAMP)',
            ('@'+handle,'service-'+secrets.token_hex(16)+'@accounts.invalid','!service-no-login')).lastrowid
    db.execute('INSERT INTO service_accounts VALUES (?,?,?,1,0,?)',(sid,owner,purpose,int(time.time())))
    db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(sid,))
    audit(db,sid,actor,'created',json.dumps({'owner_id':owner,'purpose':purpose}))
    return sid


def can_publish(db, sid, actor):
    row=get(db,sid)
    if row and actor and any(db.execute('SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',(target,actor,actor,target)).fetchone() for target in (sid,row['owner_id'])):return False
    return bool(active(db,row) and human(db,actor,True) and (row['owner_id']==actor or
        db.execute('SELECT 1 FROM service_operators WHERE service_id=? AND user_id=? AND publish_guidance=1',(sid,actor)).fetchone()))


def publish(db, identifiers, sid, actor, content, key, vibes=()):
    if not can_publish(db,sid,actor):raise ValueError('Service publishing permission is unavailable.')
    content=content.strip();key=key.strip()
    if not 1<=len(content)<=5000 or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',key):raise ValueError('Use 1–5,000 text characters and a valid publication reference.')
    digest=hashlib.sha256(content.encode()).hexdigest()
    old=db.execute('SELECT * FROM service_publications WHERE service_id=? AND request_key=?',(sid,key)).fetchone()
    if old:
        if old['content_sha256']!=digest or not public_post(db,old['post_id'],None):raise ValueError('Existing publication differs or is unavailable; review it before retrying.')
        return identifiers.public(db,'post',old['post_id'])
    if db.execute('SELECT count(*) FROM service_publications WHERE service_id=? AND created_at>?',(sid,int(time.time())-60)).fetchone()[0]>=6:raise ValueError('Wait a minute before publishing more guidance.')
    pid=identifiers.next_post_key(db)
    db.execute("INSERT INTO posts(id,user_id,target_user_id,content,circle,created_at) VALUES(?,?,?,?,'public',CURRENT_TIMESTAMP)",(pid,sid,sid,content))
    identifiers.ensure(db,'post',pid);db.execute("INSERT INTO post_privacy VALUES (?,'public')",(pid,))
    if vibes:
        from .utils.vibe_lifecycle import add_post_vibes
        add_post_vibes(db,pid,list(vibes))
    db.execute('INSERT INTO service_publications VALUES (?,?,?,?,?,?)',(pid,sid,actor,key,digest,int(time.time())))
    audit(db,sid,actor,'published',json.dumps({'post_id':pid,'request_key':key,'capability':'public_guidance'}))
    return identifiers.public(db,'post',pid)


def export_user(db, uid):
    return {'owned_services':[dict(r) for r in db.execute('SELECT * FROM service_accounts WHERE owner_id=?',(uid,))],
            'operator_permissions':[dict(r) for r in db.execute('SELECT * FROM service_operators WHERE user_id=?',(uid,))],
            'own_actions':[dict(r) for r in db.execute('SELECT * FROM service_audit WHERE actor_id=?',(uid,))]}


def erasure_dependencies(db, uid):
    return bool(db.execute('SELECT 1 FROM service_accounts WHERE user_id=? OR owner_id=?',(uid,uid)).fetchone() or
        db.execute('SELECT 1 FROM service_operators WHERE user_id=?',(uid,)).fetchone() or
        db.execute('SELECT 1 FROM service_audit WHERE actor_id=?',(uid,)).fetchone())


def register(app, core):
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    bp=Blueprint('services',__name__)
    def protected(admin=False):
        db=core.get_db();uid=session.get('user_id')
        if not uid:abort(401)
        if not human(db,uid,True):abort(403,description='Use an eligible human account with two-factor authentication.')
        if admin and not core.has_staff_permission(db,uid,'manage_roles'):abort(403)
        if not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=request.path))
    @bp.route('/manage/services',methods=['GET','POST'])
    def manage():
        response=protected(True)
        if response is not None:return response
        db=core.get_db();error=None;actor=session['user_id']
        if request.method=='POST':
            app.extensions['community_auth_helpers']['csrf']()
            try:
                with db:
                    action=request.form.get('action')
                    if action=='create':
                        create(db,core,actor,int(request.form.get('owner_id','0')),request.form.get('purpose',''),request.form.get('handle',''),int(request.form.get('existing_id','0')) or None)
                    else:
                        sid=int(request.form.get('service_id','0'));row=get(db,sid)
                        if not row:abort(404)
                        if int(request.form.get('revision','-1'))!=row['revision']:abort(409,description='Service changed. Reload before retrying.')
                        if action=='status':
                            enabled=request.form.get('enabled')=='1'
                            db.execute('UPDATE service_accounts SET enabled=?,revision=revision+1 WHERE user_id=?',(int(enabled),sid))
                            audit(db,sid,actor,'enabled' if enabled else 'disabled','Public guidance availability changed')
                        elif action in ('grant','revoke'):
                            operator=int(request.form.get('operator_id','0'))
                            if action=='grant' and not human(db,operator,True):raise ValueError('Choose an eligible adult operator with two-factor authentication.')
                            if action=='grant':db.execute('INSERT INTO service_operators VALUES (?,?,1) ON CONFLICT(service_id,user_id) DO UPDATE SET publish_guidance=1',(sid,operator))
                            else:db.execute('DELETE FROM service_operators WHERE service_id=? AND user_id=?',(sid,operator))
                            db.execute('UPDATE service_accounts SET revision=revision+1 WHERE user_id=?',(sid,))
                            audit(db,sid,actor,action,json.dumps({'operator_id':operator,'capability':'public_guidance'}))
                        else:abort(400)
            except (ValueError,sqlite3.IntegrityError) as e:error=str(e) if isinstance(e,ValueError) else 'That identity is unavailable.'
            if not error:return redirect(url_for('services.manage'))
        rows=db.execute('SELECT s.*,u.handle FROM service_accounts s JOIN users u ON u.id=s.user_id ORDER BY s.user_id').fetchall()
        operators={r['user_id']:db.execute('SELECT o.*,u.handle FROM service_operators o JOIN users u ON u.id=o.user_id WHERE service_id=?',(r['user_id'],)).fetchall() for r in rows}
        return render_template('service_accounts.html',view='manage',services=rows,operators=operators,error=error,token=core.theme_csrf_token(),events=db.execute('SELECT * FROM service_audit ORDER BY id DESC LIMIT 100').fetchall()),400 if error else 200
    @bp.route('/services',methods=['GET'])
    def mine():
        response=protected()
        if response is not None:return response
        db=core.get_db();uid=session['user_id']
        rows=db.execute('SELECT s.*,u.handle FROM service_accounts s JOIN users u ON u.id=s.user_id WHERE s.owner_id=? OR s.user_id IN (SELECT service_id FROM service_operators WHERE user_id=? AND publish_guidance=1)',(uid,uid)).fetchall()
        return render_template('service_accounts.html',view='mine',services=rows)
    @bp.route('/services/<int:sid>/publish',methods=['GET','POST'])
    def compose(sid):
        response=protected()
        if response is not None:return response
        db=core.get_db();uid=session['user_id']
        if not can_publish(db,sid,uid):abort(403)
        error=None
        if request.method=='POST':
            app.extensions['community_auth_helpers']['csrf']()
            try:
                with db:ref=publish(db,core.identifiers,sid,uid,request.form.get('content',''),request.form.get('request_key',''))
            except ValueError as e:error=str(e)
            else:return redirect(url_for('post_detail',post_id=ref))
        row=db.execute('SELECT s.*,u.handle FROM service_accounts s JOIN users u ON u.id=s.user_id WHERE s.user_id=?',(sid,)).fetchone()
        return render_template('service_accounts.html',view='compose',service=row,error=error,token=core.theme_csrf_token(),request_key=request.form.get('request_key') or secrets.token_urlsafe(24)),400 if error else 200
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    app.register_blueprint(bp)
    def service_guard():
        db=core.get_db()
        for key in ('user_id','pending_login'):
            if get(db,session.get(key)):
                session.clear();abort(403,description='Service identities cannot sign in. Use your personal operator account.')
        if request.endpoint=='login' and request.method=='POST':
            row=db.execute('SELECT id FROM users WHERE email=? COLLATE NOCASE',(request.form.get('email','').strip(),)).fetchone()
            if row and get(db,row['id']):abort(403,description='Service identities cannot sign in. Use your personal operator account.')
    app.before_request_funcs.setdefault(None,[]).insert(0,service_guard)
    @app.context_processor
    def service_context():return {'is_service_account':lambda uid:bool(get(core.get_db(),uid))}
