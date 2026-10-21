"""Private parental-consent submissions. Provider consent is not self-attested."""
import io, os, secrets
from pathlib import Path
from flask import request,session,abort,redirect,url_for,send_file
from PIL import Image

def folder(core):
    return Path(core.app.config.get('FAMILY_CONSENT_FOLDER', '/home/sinbot/private/neonrest_sandbox/family_consent'))

def register(app,core,ages,fresh):
    with app.app_context():
        core.get_db().execute("CREATE TABLE IF NOT EXISTS family_consent_documents (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, child_id INTEGER NOT NULL, storage_key TEXT UNIQUE NOT NULL, media_type TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        core.get_db().commit()
    @app.route('/account/family/consent',methods=['POST'])
    def family_consent_submit():
        uid=session.get('user_id'); db=core.get_db()
        if not uid or ages.age(db,uid) is None or ages.age(db,uid)<18: abort(403)
        import hmac
        if not session.get('theme_csrf_token') or not hmac.compare_digest(session['theme_csrf_token'],request.form.get('theme_csrf_token','')): abort(400)
        if not fresh(): return redirect(url_for('community_reauth',next='/account/family'))
        child=request.form.get('child_id',type=int)
        if not db.execute("SELECT 1 FROM family_links WHERE parent_id=? AND child_id=? AND status IN ('pending','approved')",(uid,child)).fetchone(): abort(404)
        if request.content_length is None or request.content_length>6*1024*1024: abort(413)
        upload=request.files.get('letter')
        if not upload: abort(400,description='Choose a signed PDF, PNG or JPEG letter.')
        data=upload.stream.read(5*1024*1024+1)
        if not data or len(data)>5*1024*1024: abort(413)
        if db.execute('SELECT COUNT(*) FROM family_consent_documents WHERE parent_id=?',(uid,)).fetchone()[0]>=10: abort(400,description='Submission limit reached. Please contact staff before submitting more documents.')
        if data.startswith(b'%PDF-') and b'%%EOF' in data[-2048:]: media='application/pdf'; ext='.pdf'
        else:
            try:
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in ('PNG','JPEG') or image.width*image.height>25000000: raise ValueError()
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    clean=io.BytesIO(); image.convert('RGB').save(clean,format='JPEG'); data=clean.getvalue()
                media='image/jpeg'; ext='.jpg'
            except Exception: abort(400,description='Upload a valid PDF, PNG or JPEG. Other files are not accepted.')
        directory=folder(core); directory.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(directory,0o700)
        key=secrets.token_hex(24)+ext; path=directory/key
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out: out.write(data)
            cur=db.execute('INSERT INTO family_consent_documents(parent_id,child_id,storage_key,media_type) VALUES (?,?,?,?)',(uid,child,key,media))
            db.execute('INSERT INTO age_policy_events(actor_id,child_id,action) VALUES (?,?,?)',(uid,child,'consent-document-submitted:'+str(cur.lastrowid)))
            db.commit()
        except Exception:
            db.rollback(); path.unlink(missing_ok=True); raise
        return redirect(url_for('family_settings'))
    @app.route('/account/family/consent/<int:document_id>')
    def family_consent_document(document_id):
        db=core.get_db(); uid=session.get('user_id')
        row=db.execute('SELECT * FROM family_consent_documents WHERE id=?',(document_id,)).fetchone()
        if not uid or not row: abort(404)
        if uid!=row['parent_id']: core.require_staff_permission('manage_roles')
        if not fresh(): return redirect(url_for('community_reauth',next=request.path))
        path=folder(core)/row['storage_key']
        if not path.is_file(): abort(404)
        response=send_file(path,mimetype=row['media_type'],as_attachment=True,download_name='signed-consent-'+str(row['id'])+path.suffix,conditional=False)
        response.headers['Cache-Control']='private, no-store'; response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="sandbox; default-src 'none'"
        return response
    @app.context_processor
    def consent_context():
        db=core.get_db(); uid=session.get('user_id')
        staff=bool(uid and core.has_staff_permission(db,uid,'manage_roles'))
        rows=db.execute('SELECT id,parent_id,child_id,created_at FROM family_consent_documents'+('' if staff else ' WHERE parent_id=?')+' ORDER BY id DESC',() if staff else (uid,)).fetchall()
        grouped={}
        for row in rows: grouped.setdefault((row['parent_id'],row['child_id']),[]).append(row)
        return {'family_review_allowed':staff,'family_documents':grouped}
