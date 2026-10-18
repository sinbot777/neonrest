"""Scoped Vibe lifecycle, curation and management history."""
from flask import abort, flash, redirect, render_template, request, session, url_for
from . import age_policy as ages
from .utils.vibe_lifecycle import vibe_slug


def initialize(db):
    for sql in [
        '''CREATE TABLE IF NOT EXISTS vibe_management(vibe_id INTEGER PRIMARY KEY,
           archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
           rules TEXT NOT NULL DEFAULT '',archive_reason TEXT NOT NULL DEFAULT '',
           updated_by INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS vibe_post_removals(vibe_id INTEGER NOT NULL,post_id INTEGER NOT NULL,
           active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),removed_by INTEGER NOT NULL,
           reason TEXT NOT NULL,removed_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(vibe_id,post_id))''',
        '''CREATE TABLE IF NOT EXISTS vibe_management_events(id INTEGER PRIMARY KEY,vibe_id INTEGER NOT NULL,
           actor_id INTEGER NOT NULL,action TEXT NOT NULL,post_id INTEGER,target_user_id INTEGER,
           reason TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
        'CREATE INDEX IF NOT EXISTS idx_vibe_management_events ON vibe_management_events(vibe_id,id DESC)',
    ]:
        db.execute(sql)


def state(db, vibe_id):
    row = db.execute('SELECT * FROM vibe_management WHERE vibe_id=?', (vibe_id,)).fetchone()
    return dict(row) if row else {'archived': 0, 'rules': '', 'archive_reason': ''}


def validate_tag(db, vibe_id, post_id, allow_archived=()):
    if state(db, vibe_id)['archived'] and vibe_id not in allow_archived:
        abort(409, description='This Vibe is archived. Choose another Vibe or remove its name before posting.')
    if db.execute('SELECT 1 FROM vibe_post_removals WHERE vibe_id=? AND post_id=? AND active=1', (vibe_id, post_id)).fetchone():
        abort(409, description='This post was removed from that Vibe. A manager must restore it before it can be added again.')


def permissions(core, db, uid, vibe_id=None):
    user = db.execute('SELECT id,verified FROM users WHERE id=?', (uid,)).fetchone() if isinstance(uid,int) else None
    if not user or not user['verified']:
        return {'access':False,'settings':False,'lifecycle':False,'site_reports':False}
    if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1', (uid,)).fetchone() or db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1', (uid,)).fetchone() or db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1', (uid,)).fetchone():
        return {'access':False,'settings':False,'lifecycle':False,'site_reports':False}
    staff = core.staff_permissions(db, uid)
    admin = uid==1 or 'manage_roles' in staff
    vibe = db.execute('SELECT * FROM vibes WHERE id=?', (vibe_id,)).fetchone() if vibe_id else None
    settings = bool(vibe and core.can_edit_vibe_settings(uid,vibe))
    assigned = db.execute('SELECT 1 FROM vibe_editors WHERE user_id=? LIMIT 1',(uid,)).fetchone()
    return {'access':bool(admin or 'moderate_posts' in staff or settings or (vibe_id is None and assigned)),
            'settings':settings,'lifecycle':admin,'site_reports':'review_reports' in staff}


def find_vibe(db, slug):
    rows = [v for v in db.execute('SELECT * FROM vibes WHERE id NOT IN (SELECT vibe_id FROM pending_vibes)') if vibe_slug(v['name'])==slug]
    if len(rows)!=1:
        abort(404)
    return rows[0]


def event(db, vibe_id, actor, action, reason, post_id=None, target=None):
    db.execute('INSERT INTO vibe_management_events(vibe_id,actor_id,action,reason,post_id,target_user_id) VALUES (?,?,?,?,?,?)', (vibe_id,actor,action,reason,post_id,target))


def page_number():
    try:
        page = int(request.args.get('page','1'))
    except ValueError:
        abort(400)
    if not 1<=page<=10000:
        abort(400)
    return page


def dashboard(core, slug):
    db=core.get_db();vibe=find_vibe(db,slug);rights=permissions(core,db,session.get('user_id'),vibe['id'])
    if not rights['access']:
        abort(403)
    query=request.args.get('q','').strip()[:120];tab=request.args.get('tab','posts');page=page_number()
    if tab not in ('posts','removed','history'):
        abort(400)
    pattern='%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
    posts=[];history=[];more=False
    if tab in ('posts','removed'):
        association='EXISTS(SELECT 1 FROM post_vibes pv WHERE pv.post_id=p.id AND pv.vibe_id=?)' if tab=='posts' else 'EXISTS(SELECT 1 FROM vibe_post_removals vr WHERE vr.post_id=p.id AND vr.vibe_id=? AND vr.active=1)'
        rows=db.execute('''SELECT p.id,p.user_id,p.content,p.created_at,u.handle FROM posts p JOIN users u ON u.id=p.user_id WHERE '''+association+''' AND community_post_visible(p.id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=p.id) AND (?='' OR p.content LIKE ? ESCAPE '!' OR u.handle LIKE ? ESCAPE '!') ORDER BY p.created_at DESC,p.id DESC LIMIT 21 OFFSET ?''',(vibe['id'],query,pattern,pattern,(page-1)*20)).fetchall()
        more=len(rows)>20
        for row in rows[:20]:
            item=dict(row);item['token']=core.identifiers.public(db,'post',row['id']);item['protected']=row['user_id']==1 or bool(db.execute('SELECT 1 FROM staff_roles WHERE user_id=?',(row['user_id'],)).fetchone());posts.append(item)
    else:
        history=db.execute('''SELECT e.*,u.handle AS actor_handle,t.handle AS target_handle FROM vibe_management_events e LEFT JOIN users u ON u.id=e.actor_id LEFT JOIN users t ON t.id=e.target_user_id WHERE e.vibe_id=? ORDER BY e.id DESC LIMIT 21 OFFSET ?''',(vibe['id'],(page-1)*20)).fetchall();more=len(history)>20;history=history[:20]
    managers=db.execute('SELECT u.id,u.handle FROM vibe_editors ve JOIN users u ON u.id=ve.user_id WHERE ve.vibe_id=? ORDER BY u.handle COLLATE NOCASE',(vibe['id'],)).fetchall()
    return render_template('manage_vibe.html',vibe=vibe,slug=slug,rights=rights,vstate=state(db,vibe['id']),posts=posts,history=history,managers=managers,query=query,tab=tab,page=page,more=more,token=core.theme_csrf_token())


def report_filter(db, vibe_id):
    if not vibe_id:
        return '',[],None
    if not vibe_id.isdecimal() or len(vibe_id)>10:
        abort(400)
    vibe=db.execute('SELECT name FROM vibes WHERE id=?',(int(vibe_id),)).fetchone()
    if not vibe:
        abort(404)
    sql=''' AND EXISTS(SELECT 1 FROM posts vp WHERE vp.id=CASE WHEN r.target_type='post' THEN r.target_id WHEN r.target_type='comment' THEN (SELECT post_id FROM comments WHERE id=r.target_id) ELSE NULL END AND (EXISTS(SELECT 1 FROM post_vibes pv WHERE pv.post_id=vp.id AND pv.vibe_id=?) OR EXISTS(SELECT 1 FROM vibe_post_removals vr WHERE vr.post_id=vp.id AND vr.vibe_id=?)))'''
    return sql,[int(vibe_id),int(vibe_id)],vibe['name']


def register(app, core):
    with app.app_context():
        initialize(core.get_db());core.get_db().commit()
    @app.before_request
    def guard_vibe_tools():
        if request.endpoint not in ('vibe_tools_home','vibe_tools_action','manage_vibe'):
            return
        db=core.get_db();uid=session.get('user_id')
        if not permissions(core,db,uid)['access']:
            abort(403)
        safety=db.execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone()
        if not safety or not safety['totp_secret']:
            return redirect(url_for('community_security'))
        if not app.extensions['community_auth_helpers']['fresh']():
            return redirect(url_for('community_reauth',next=url_for('vibe_tools_home')))
    @app.context_processor
    def vibe_tools_context():
        def public_state(name):
            row=core.get_db().execute('SELECT id FROM vibes WHERE name=? COLLATE NOCASE',(name,)).fetchone()
            return state(core.get_db(),row['id']) if row else {'archived':0,'rules':''}
        return {'vibe_management_state':public_state,'vibe_management_can_manage':lambda vid: permissions(core,core.get_db(),session.get('user_id'),vid)['access']}
    @app.get('/manage/vibes')
    def vibe_tools_home():
        db=core.get_db();uid=session['user_id'];query=request.args.get('q','').strip()[:120];status=request.args.get('status','active')
        if status not in ('active','archived','all'):
            abort(400)
        entries=[]
        for vibe in db.execute('SELECT * FROM vibes WHERE id NOT IN (SELECT vibe_id FROM pending_vibes) ORDER BY name COLLATE NOCASE'):
            rights=permissions(core,db,uid,vibe['id']);vs=state(db,vibe['id'])
            if not rights['access'] or query.casefold() not in vibe['name'].casefold() or status!='all' and bool(vs['archived'])!=(status=='archived'):
                continue
            entries.append(dict(vibe,slug=vibe_slug(vibe['name']),archived=vs['archived'],rights=rights))
        return render_template('manage_vibes.html',vibes=entries,query=query,status=status)
    @app.post('/manage/vibes/<int:vibe_id>/action')
    def vibe_tools_action(vibe_id):
        if not core.valid_management_token():
            abort(400)
        db=core.get_db();db.execute('BEGIN IMMEDIATE');uid=session['user_id'];vibe=db.execute('SELECT * FROM vibes WHERE id=? AND id NOT IN (SELECT vibe_id FROM pending_vibes)',(vibe_id,)).fetchone()
        if not vibe:
            abort(404)
        rights=permissions(core,db,uid,vibe_id)
        if not rights['access']:
            abort(403)
        action=request.form.get('action','');reason=request.form.get('reason','').strip()
        if not 1<=len(reason)<=500:
            abort(400,description='Enter a short reason for this change (up to 500 characters).')
        db.execute('INSERT OR IGNORE INTO vibe_management(vibe_id) VALUES (?)',(vibe_id,))
        if action in ('archive','restore_vibe'):
            if not rights['lifecycle']:
                abort(403)
            if request.form.get('confirm_name','')!=vibe['name']:
                abort(400,description='Type the exact Vibe name to confirm.')
            desired=int(action=='archive')
            if bool(state(db,vibe_id)['archived'])==bool(desired):
                abort(409,description='The Vibe already has that state. Refresh before continuing.')
            db.execute('UPDATE vibe_management SET archived=?,archive_reason=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE vibe_id=?',(desired,reason,uid,vibe_id));event(db,vibe_id,uid,action,reason)
        elif action=='details':
            if not rights['settings']:
                abort(403)
            welcome=request.form.get('welcome_message','').strip();rules=request.form.get('rules','').strip()
            if len(welcome)>1000 or len(rules)>4000:
                abort(400)
            db.execute('UPDATE vibes SET welcome_message=? WHERE id=?',(welcome,vibe_id));db.execute('UPDATE vibe_management SET rules=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE vibe_id=?',(rules,uid,vibe_id));event(db,vibe_id,uid,action,reason)
        elif action in ('assign_manager','remove_manager'):
            if not rights['lifecycle']:
                abort(403)
            value=request.form.get('account','').strip();target=db.execute('SELECT id,verified FROM users WHERE id=?',(int(value),)).fetchone() if value.isdecimal() and len(value)<=10 else db.execute("SELECT id,verified FROM users WHERE lower(ltrim(handle,'@'))=lower(?)",(value.lstrip('@'),)).fetchone()
            if not target:
                abort(404,description='No matching account. Use an exact handle or numeric NUID.')
            if action=='assign_manager':
                age=ages.age(db,target['id'])
                if target['id']==1 or not target['verified'] or age is None or age<18 or db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',(target['id'],)).fetchone() or db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1',(target['id'],)).fetchone() or db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(target['id'],)).fetchone():
                    abort(403,description='Choose a verified, active adult account. The site owner already has access.')
                if db.execute('SELECT 1 FROM vibe_editors WHERE vibe_id=? AND user_id=?',(vibe_id,target['id'])).fetchone():
                    abort(409,description='This account is already assigned.')
                db.execute('INSERT INTO vibe_editors(vibe_id,user_id) VALUES (?,?)',(vibe_id,target['id']))
            else:
                if not db.execute('DELETE FROM vibe_editors WHERE vibe_id=? AND user_id=?',(vibe_id,target['id'])).rowcount:
                    abort(409,description='That assignment has already been removed.')
            event(db,vibe_id,uid,action,reason,target=target['id'])
        elif action in ('remove_post','restore_post'):
            raw=request.form.get('post','');pid=core.identifiers.resolve(db,'post',raw);post=db.execute('SELECT id,user_id FROM posts WHERE id=?',(pid,)).fetchone()
            if not post or not db.execute('SELECT 1 FROM posts WHERE id=? AND community_post_visible(id)=1 AND NOT EXISTS(SELECT 1 FROM moderated_posts mp WHERE mp.post_id=posts.id)',(pid,)).fetchone():
                abort(404)
            if uid!=1 and (post['user_id']==1 or db.execute('SELECT 1 FROM staff_roles WHERE user_id=?',(post['user_id'],)).fetchone()):
                abort(403,description='Ask the site owner to review staff-authored content.')
            if action=='remove_post':
                if not db.execute('DELETE FROM post_vibes WHERE vibe_id=? AND post_id=?',(vibe_id,pid)).rowcount:
                    abort(409,description='This post is no longer in this Vibe.')
                db.execute('INSERT INTO vibe_post_removals(vibe_id,post_id,removed_by,reason) VALUES (?,?,?,?) ON CONFLICT(vibe_id,post_id) DO UPDATE SET active=1,removed_by=excluded.removed_by,reason=excluded.reason,removed_at=CURRENT_TIMESTAMP',(vibe_id,pid,uid,reason))
            else:
                if not db.execute('UPDATE vibe_post_removals SET active=0 WHERE vibe_id=? AND post_id=? AND active=1',(vibe_id,pid)).rowcount:
                    abort(409,description='This removal is no longer active.')
                db.execute('INSERT OR IGNORE INTO post_vibes(post_id,vibe_id) VALUES (?,?)',(pid,vibe_id))
            event(db,vibe_id,uid,action,reason,post_id=pid)
        else:
            abort(400)
        db.commit();flash('Vibe change recorded.','success')
        return redirect(url_for('manage_vibe',slug=vibe_slug(vibe['name'])))
    original=app.view_functions['edit_theme']
    def audited_theme(*args,**kwargs):
        response=original(*args,**kwargs)
        if request.method=='POST':
            result=app.make_response(response)
            if result.status_code in (302,303):
                db=core.get_db();vibe=find_vibe(db,kwargs['slug']);event(db,vibe['id'],session['user_id'],'appearance','Saved '+kwargs['mode']+' appearance using the theme editor.');db.commit()
        return response
    app.view_functions['edit_theme']=audited_theme
