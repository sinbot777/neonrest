"""Tracked family data and DOB-review requests; no self-attested DOB changes."""
import json,time
from flask import request,session,abort,redirect,url_for,render_template,Response,flash
from neonrest import age_policy as ages

def register(app,core):
    with app.app_context():
        db=core.get_db();db.executescript("""CREATE TABLE IF NOT EXISTS family_data_requests(id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL,child_id INTEGER NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',notes TEXT NOT NULL DEFAULT '',reviewed_by INTEGER,reviewed_at TEXT,review_reference TEXT,expires_at INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS parent_deletion_requests(child_id INTEGER PRIMARY KEY,request_id INTEGER NOT NULL,parent_id INTEGER NOT NULL,original_inactive INTEGER NOT NULL DEFAULT 0);""");db.commit()
        if 'original_inactive' not in {r[1] for r in db.execute('PRAGMA table_info(parent_deletion_requests)')}:
            db.execute('ALTER TABLE parent_deletion_requests ADD COLUMN original_inactive INTEGER NOT NULL DEFAULT 0');db.commit()
    def uid():
        value=session.get('user_id')
        if not value:abort(401)
        return value
    def helpers():return app.extensions['community_auth_helpers']
    def guardian(db,parent,child):
        return bool(ages.age(db,parent) is not None and ages.age(db,parent)>=18 and ages.age(db,child) is not None and 10<=ages.age(db,child)<18 and db.execute("SELECT 1 FROM family_links WHERE parent_id=? AND child_id=? AND status IN ('approved','revoked') AND method IS NOT NULL",(parent,child)).fetchone())
    def records(db,staff,parent):
        return db.execute('SELECT r.*,p.handle AS parent_handle,c.handle AS child_handle FROM family_data_requests r LEFT JOIN users p ON p.id=r.parent_id LEFT JOIN users c ON c.id=r.child_id'+('' if staff else ' WHERE r.parent_id=?')+' ORDER BY r.id DESC',() if staff else (parent,)).fetchall()
    @app.route('/account/family/requests',methods=['GET','POST'])
    def family_data_requests():
        parent=uid();db=core.get_db()
        if request.method=='POST':
            helpers()['csrf']()
            if not helpers()['fresh']():return redirect(url_for('community_reauth',next=request.path))
            child=request.form.get('child_id',type=int);kind=request.form.get('kind');notes=request.form.get('notes','').strip()
            if kind not in ('data-review','delete','dob-correction') or len(notes)>500:abort(400)
            if kind=='dob-correction' and child==parent:pass
            elif not guardian(db,parent,child):abort(403)
            response=helpers()['limited']('family-data-request',10,86400)
            if response:return response
            db.execute("UPDATE family_data_requests SET status='closed',reviewed_at=CURRENT_TIMESTAMP WHERE parent_id=? AND status='access-approved' AND expires_at<?",(parent,int(time.time())))
            if not db.execute("SELECT 1 FROM family_data_requests WHERE parent_id=? AND child_id=? AND kind=? AND status IN ('pending','pending-verification','access-approved','scheduled')",(parent,child,kind)).fetchone():
                db.execute('INSERT INTO family_data_requests(parent_id,child_id,kind,notes) VALUES (?,?,?,?)',(parent,child,kind,notes));db.commit()
            flash('Request recorded for staff review. Your request does not change DOB or release private data.','info')
            return redirect(url_for('family_data_requests'))
        return render_template('family_requests.html',staff=False,records=records(db,False,parent),token=core.theme_csrf_token())
    @app.route('/manage/family/requests',methods=['GET','POST'])
    def family_data_review():
        actor=core.require_staff_permission('manage_roles');db=core.get_db()
        if request.method=='POST':
            helpers()['csrf']()
            if not helpers()['fresh']():return redirect(url_for('community_reauth',next=request.path))
            row=db.execute('SELECT * FROM family_data_requests WHERE id=?',(request.form.get('request_id',type=int),)).fetchone()
            action=request.form.get('action');reference=request.form.get('reference','').strip()
            if not row or action not in ('approve-access','schedule-delete','cancel-delete','pending-verification','decline','close') or not reference or len(reference)>500:abort(400)
            if action in ('approve-access','schedule-delete'):
                if request.form.get('guardian_verified')!='1' or not guardian(db,row['parent_id'],row['child_id']):abort(403)
                if row['status'] not in ('pending','pending-verification') or row['kind']!=('data-review' if action=='approve-access' else 'delete'):abort(400)
            if row['status']=='scheduled' and action in ('decline','close'):abort(400,description='Use reviewed cancellation for a scheduled deletion.')
            status={'approve-access':'access-approved','schedule-delete':'scheduled','pending-verification':'pending-verification','decline':'declined','close':'closed','cancel-delete':'closed'}[action]
            with db:
                if action=='schedule-delete':
                    db.execute('INSERT OR IGNORE INTO account_safety(user_id) VALUES (?)',(row['child_id'],))
                    prior=db.execute('SELECT inactive,deletion_requested_at FROM account_safety WHERE user_id=?',(row['child_id'],)).fetchone()
                    if prior['deletion_requested_at']:abort(409,description='An account deletion request is already active; review that request separately.')
                    original=prior['inactive']
                    db.execute('UPDATE account_safety SET inactive=1,deletion_requested_at=COALESCE(deletion_requested_at,CURRENT_TIMESTAMP) WHERE user_id=?',(row['child_id'],))
                    db.execute('INSERT INTO parent_deletion_requests(child_id,request_id,parent_id,original_inactive) VALUES (?,?,?,?) ON CONFLICT(child_id) DO UPDATE SET request_id=excluded.request_id,parent_id=excluded.parent_id',(row['child_id'],row['id'],row['parent_id'],original))
                    db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(row['child_id'],))
                if action=='cancel-delete':
                    held=db.execute('SELECT original_inactive FROM parent_deletion_requests WHERE child_id=? AND request_id=?',(row['child_id'],row['id'])).fetchone()
                    if not held or request.form.get('guardian_verified')!='1':abort(400)
                    db.execute('UPDATE account_safety SET inactive=?,deletion_requested_at=NULL WHERE user_id=?',(held[0],row['child_id']))
                    db.execute('DELETE FROM parent_deletion_requests WHERE child_id=?',(row['child_id'],))
                db.execute('UPDATE family_data_requests SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,review_reference=?,expires_at=? WHERE id=?',(status,actor,reference,int(time.time())+86400 if action=='approve-access' else None,row['id']))
                db.execute('INSERT INTO age_policy_events(actor_id,child_id,action) VALUES (?,?,?)',(actor,row['child_id'],'family-data:'+action))
            flash('Review recorded. Scheduled erasure remains subject to the account-deletion process.','info')
            return redirect(url_for('family_data_review'))
        return render_template('family_requests.html',staff=True,records=records(db,True,actor),token=core.theme_csrf_token())
    @app.get('/account/family/requests/<int:request_id>/download')
    def family_data_download(request_id):
        parent=uid();db=core.get_db();row=db.execute('SELECT * FROM family_data_requests WHERE id=? AND parent_id=?',(request_id,parent)).fetchone()
        if not row or row['status']!='access-approved' or row['expires_at']<time.time() or not guardian(db,parent,row['child_id']):abort(404)
        if not helpers()['fresh']():return redirect(url_for('community_reauth',next=request.path))
        child=row['child_id'];user=db.execute('SELECT id,handle,actual_name,email,dob,bio,pronouns,created_at,timezone,avatar,avatar_path FROM users WHERE id=?',(child,)).fetchone()
        if not user:abort(404)
        data={'profile':dict(user),'posts':[dict(r) for r in db.execute('SELECT * FROM posts WHERE user_id=?',(child,))],'replies':[dict(r) for r in db.execute('SELECT * FROM comments WHERE user_id=?',(child,))],'media':[dict(r) for r in db.execute('SELECT m.* FROM post_media m JOIN posts p ON p.id=m.post_id WHERE p.user_id=?',(child,))]}
        core.identifiers.export_ids(db,data)
        response=Response(json.dumps(data),mimetype='application/json');response.headers['Content-Disposition']='attachment; filename="family-data.json"';response.headers['Cache-Control']='private, no-store';response.headers['Referrer-Policy']='no-referrer';return response
