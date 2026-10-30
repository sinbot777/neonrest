"""T34 Sandbox-native editorial workflow and protected print downloads."""
import hashlib
import io
import json
import os
import secrets
import time
from pathlib import Path
from flask import Blueprint,abort,render_template,request,session,redirect,url_for,send_file
from . import zines_core as z

def register(app,core):
    bp=Blueprint('zines',__name__)
    with app.app_context():z.initialize(core.get_db());core.get_db().commit()
    def uid():return session.get('user_id') if type(session.get('user_id')) is int else None
    def actor():
        user=uid()
        if not user:abort(401)
        if not z.eligible(core.get_db(),user):raise z.ZineError('An eligible verified Neonrest profile is required.',403)
        return user
    def token():return core.theme_csrf_token()
    def revision():return request.form.get('revision',type=int)
    def writing():
        helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
        return helpers['limited']('zines-write',80)
    from .zines_composition import asset_ids
    def form_content():return {**{k:request.form.get(k,'') for k in ('heading','text','caption','image','layout','print_alternative','section','pullquote','highlight','highlight_label','accent','text_size','image_width','image_align')},'composition':request.form.get('composition',''),'design':request.form.get('design','classic'),**{key:request.form.get(key,default) for key,default in [('accent','red'),('text_size','regular'),('image_width','full'),('image_align','center')]}}
    def render(view,**values):return render_template('zines.html',view=view,token=token(),waveform=z.wave(),**values)
    def budget(db,owner):
        total=0
        for sql in ["SELECT SUM(length(CAST(p.content AS BLOB))) FROM zine_pages p JOIN zine_issues i ON i.id=p.issue_id JOIN zines z ON z.id=i.zine_id WHERE z.owner_id=?", "SELECT SUM(length(CAST(p.snapshot AS BLOB))) FROM zine_revisions p JOIN zine_issues i ON i.id=p.issue_id JOIN zines z ON z.id=i.zine_id WHERE z.owner_id=?", "SELECT SUM(length(CAST(p.content AS BLOB))) FROM zine_submissions p JOIN zine_issues i ON i.id=p.issue_id JOIN zines z ON z.id=i.zine_id WHERE z.owner_id=?"]:
            total+=db.execute(sql,(owner,)).fetchone()[0] or 0
        if total>4*1024*1024:raise z.ZineError('This owner has reached the 4 MiB editorial text and revision allowance.',409)
    def asset_bytes(db,zine,asset_id):
        from .media_export import open_regular
        row=db.execute('SELECT * FROM zine_assets WHERE id=? AND zine_id=?',(asset_id,zine['id'])).fetchone()
        if not row or not z.compatible(db,row['uploader_id'],uid()):raise z.ZineError('Image unavailable.',404)
        try:
            with open_regular(Path(app.instance_path)/'zines',row['storage_key']) as file:data=file.read(512*1024+1)
        except OSError:raise z.ZineError('Image unavailable.',404)
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise z.ZineError('Image unavailable.',404)
        return data
    @bp.errorhandler(z.ZineError)
    def error(exc):
        values=[(key,value[:8000]) for key,value in request.form.items() if key in ('title','description','heading','text','caption','print_alternative')]
        return render('error',error=str(exc),unsaved=values),exc.status
    @bp.after_request
    def privacy(response):
        response.headers.update({'Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin'})
        return response
    @bp.get('/zines')
    def directory():
        db=core.get_db();items=[]
        page=max(1,min(request.args.get('page',1,type=int) or 1,1000));rows=db.execute("SELECT DISTINCT z.* FROM zines z LEFT JOIN zine_members m ON m.zine_id=z.id AND m.user_id=? WHERE z.visibility='public' OR z.owner_id=? OR m.user_id=? ORDER BY z.created_at DESC,z.id LIMIT 13 OFFSET ?",(uid(),uid(),uid(),(page-1)*12)).fetchall()
        for p in rows[:12]:
            member=z.role(db,p,uid())
            issues=db.execute("SELECT * FROM zine_issues WHERE zine_id=? AND state='published'",(p['id'],)).fetchall()
            if member or (p['visibility']=='public' and any(z.visible(db,p,i,uid()) for i in issues)):items.append(p)
        return render('directory',items=items,page=page,more=len(rows)>12)
    @bp.route('/zines/create',methods=['GET','POST'])
    def create():
        user=actor()
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            db=core.get_db()
            with db:
                db.execute('BEGIN IMMEDIATE');zid=z.create(db,user,request.form.get('title',''),request.form.get('description',''))
            return redirect(url_for('zines.edit',zid=zid))
        return render('create')
    @bp.get('/zines/<zid>')
    def home(zid):
        db=core.get_db();p=z.publication(db,zid);member=z.role(db,p,uid())
        issues=[i for i in db.execute('SELECT * FROM zine_issues WHERE zine_id=? ORDER BY created_at DESC,id',(zid,)) if z.visible(db,p,i,uid()) or member]
        if not member and (p['visibility']=='private' or not issues):abort(404)
        if not z.compatible(db,p['owner_id'],uid()):abort(404)
        return render('home',publication=p,issues=issues,role=member)
    @bp.route('/zines/<zid>/edit',methods=['GET','POST'])
    def edit(zid):
        user=actor();db=core.get_db();p=z.publication(db,zid);member=z.require(db,p,user,('owner','editor','contributor'))
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');p=z.publication(db,zid);z.check_revision(p,revision());member=z.require(db,p,user,('owner','editor','contributor'))
                action=request.form.get('action')
                if action=='issue':
                    iid=z.create_issue(db,p,user,request.form.get('title',''));db.execute('UPDATE zines SET revision=revision+1 WHERE id=?',(zid,));return redirect(url_for('zines.issue_edit',zid=zid,iid=iid))
                if member!='owner':abort(404)
                if action=='settings':
                    visibility=request.form.get('visibility')
                    if visibility not in ('public','private','unlisted'):raise z.ZineError('Choose a visibility.')
                    cover=request.form.get('cover_asset','')
                    if cover:z.content(db,zid,user,{'image':cover})
                    db.execute('UPDATE zines SET title=?,description=?,visibility=?,allow_print=?,cover_asset=?,revision=revision+1 WHERE id=?',(z.text(request.form.get('title',''),160,True),z.text(request.form.get('description',''),2000),visibility,int(request.form.get('allow_print')=='1'),cover or None,zid))
                elif action=='member':
                    target=db.execute('SELECT id FROM users WHERE handle=? COLLATE NOCASE',(request.form.get('handle','').strip(),)).fetchone();chosen=request.form.get('role')
                    if not target or target['id']==p['owner_id'] or not z.compatible(db,p['owner_id'],target['id'],True):raise z.ZineError('That profile is unavailable for collaboration.',404)
                    if chosen=='remove':db.execute('DELETE FROM zine_members WHERE zine_id=? AND user_id=?',(zid,target['id']))
                    elif chosen in ('editor','contributor'):db.execute('INSERT INTO zine_members VALUES (?,?,?) ON CONFLICT(zine_id,user_id) DO UPDATE SET role=excluded.role',(zid,target['id'],chosen))
                    else:raise z.ZineError('Choose an editorial role.')
                    db.execute('UPDATE zines SET revision=revision+1 WHERE id=?',(zid,))
                else:raise z.ZineError('Unsupported action.')
            return redirect(url_for('zines.edit',zid=zid))
        members=db.execute('SELECT m.*,u.handle FROM zine_members m JOIN users u ON u.id=m.user_id WHERE zine_id=?',(zid,)).fetchall()
        issues=db.execute('SELECT * FROM zine_issues WHERE zine_id=? ORDER BY created_at DESC,id',(zid,)).fetchall()
        assets=db.execute('SELECT id FROM zine_assets WHERE zine_id=?'+('' if member in ('owner','editor') else ' AND uploader_id=?'),(zid,) if member in ('owner','editor') else (zid,user)).fetchall()
        return render('edit',publication=p,issues=issues,members=members,role=member,assets=assets)
    @bp.route('/zines/<zid>/issues/<iid>/edit',methods=['GET','POST'])
    def issue_edit(zid,iid):
        user=actor();db=core.get_db();p=z.publication(db,zid);member=z.require(db,p,user,('owner','editor','contributor'));issue=z.get_issue(db,p,iid)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');p=z.publication(db,zid);z.require(db,p,user);issue=z.get_issue(db,p,iid);z.check_revision(issue,revision());action=request.form.get('action')
                if action=='state':
                    state=request.form.get('state')
                    if state not in ('draft','published'):raise z.ZineError('Choose draft or published.')
                    if state=='published':
                        rows=z.pages(db,iid)
                        if len(rows)<2 or rows[0]['kind']!='cover' or rows[-1]['kind']!='back':raise z.ZineError('Front and back covers are required.')
                        if not z.visible(db,p,issue,user):raise z.ZineError('A contributor or image is no longer eligible.',409)
                        if p['allow_print'] and issue['allow_print']:
                            from .zines_pdf import render as pdf
                            for paper in ('letter','a4'):pdf(rows,lambda aid:asset_bytes(db,p,aid),'booklet',paper,title=issue['title'])
                    z.touch_issue(db,issue,user);db.execute('UPDATE zine_issues SET state=?,published_at=? WHERE id=?',(state,int(time.time()) if state=='published' else None,iid))
                else:
                    z.draft(issue);z.touch_issue(db,issue,user)
                    if action=='settings':db.execute('UPDATE zine_issues SET title=?,allow_print=? WHERE id=?',(z.text(request.form.get('title',''),160,True),int(request.form.get('allow_print')=='1'),iid))
                    elif action=='add':z.add_page(db,p,issue,user,form_content())
                    elif action in ('page','move','duplicate','delete'):
                        rows=z.pages(db,iid);target=next((r for r in rows if r['id']==request.form.get('page_id')),None)
                        if not target:abort(404)
                        if action=='page':db.execute('UPDATE zine_pages SET content=? WHERE id=?',(z.content(db,zid,user,form_content()),target['id']))
                        elif action in ('duplicate','delete'):
                            if target['kind']!='page':raise z.ZineError('Front and back covers cannot be duplicated or removed.')
                            if action=='duplicate':z.add_page(db,p,issue,user,json.loads(target['content']),author=target['author_id'])
                            else:db.execute('DELETE FROM zine_pages WHERE id=?',(target['id'],))
                        else:
                            middle=[r for r in rows if r['kind']=='page'];index=next((i for i,r in enumerate(middle) if r['id']==target['id']),None);delta=-1 if request.form.get('direction')=='up' else 1
                            if index is None or not 0<=index+delta<len(middle):raise z.ZineError('Covers stay at the ends; this page cannot move farther.')
                            middle[index],middle[index+delta]=middle[index+delta],middle[index]
                            for position,row in enumerate(middle):db.execute('UPDATE zine_pages SET position=? WHERE id=?',(position,row['id']))
                    elif action=='review':
                        submission=db.execute("SELECT * FROM zine_submissions WHERE id=? AND issue_id=? AND state='submitted'",(request.form.get('submission_id'),iid)).fetchone()
                        if not submission or not z.compatible(db,p['owner_id'],submission['author_id'],True):abort(404)
                        if request.form.get('decision')=='accept':z.add_page(db,p,issue,user,json.loads(submission['content']),author=submission['author_id']);state='accepted'
                        else:state='returned'
                        db.execute('UPDATE zine_submissions SET state=?,revision=revision+1 WHERE id=?',(state,submission['id']))
                    else:raise z.ZineError('Unsupported action.')
                budget(db,p['owner_id'])
            tab=request.form.get('workspace_tab','pages');tab=tab if tab in ('pages','settings','submissions','publish') else 'pages'
            selected=max(1,min(request.form.get('workspace_page',1,type=int) or 1,64))
            if action=='move':selected=max(1,min(64,selected+(-1 if request.form.get('direction')=='up' else 1)))
            return redirect(url_for('zines.issue_edit',zid=zid,iid=iid,tab=tab,page=selected,saved=1))
        if member in ('owner','editor') and not z.visible(db,p,issue,user):raise z.ZineError('An issue contributor or image is unavailable.',404)
        rows=z.pages(db,iid) if member in ('owner','editor') else []
        submissions=db.execute('SELECT * FROM zine_submissions WHERE issue_id=?'+('' if member in ('owner','editor') else ' AND author_id=?')+' ORDER BY created_at,id',(iid,) if member in ('owner','editor') else (iid,user)).fetchall()
        assets=db.execute('SELECT id FROM zine_assets WHERE zine_id=?'+('' if member in ('owner','editor') else ' AND uploader_id=?'),(zid,) if member in ('owner','editor') else (zid,user)).fetchall()
        selected=max(1,min(request.args.get('page',1,type=int) or 1,len(rows) or 1))
        tab=request.args.get('tab','pages');tab=tab if tab in ('pages','new','settings','submissions','publish') else 'pages'
        if member=='contributor':tab='submissions'
        return render('issue_edit',selected_page=selected,workspace_tab=tab,publication=p,issue=issue,role=member,pages=[(r,json.loads(r['content'])) for r in rows],submissions=[(r,json.loads(r['content'])) for r in submissions],assets=assets)
    @bp.post('/zines/<zid>/issues/<iid>/submit')
    def submit(zid,iid):
        user=actor();db=core.get_db();p=z.publication(db,zid);z.require(db,p,user,('owner','editor','contributor'));issue=z.get_issue(db,p,iid);z.draft(issue)
        response=writing()
        if response is not None:return response
        with db:
            db.execute('BEGIN IMMEDIATE');p=z.publication(db,zid);z.require(db,p,user,('owner','editor','contributor'));issue=z.get_issue(db,p,iid);z.draft(issue)
            payload=z.content(db,zid,user,form_content());sid=request.form.get('submission_id');state='submitted' if request.form.get('send')=='1' else 'draft'
            if sid:
                row=db.execute('SELECT * FROM zine_submissions WHERE id=? AND issue_id=? AND author_id=?',(sid,iid,user)).fetchone()
                if not row:abort(404)
                z.check_revision(row,revision())
                if row['state'] not in ('draft','returned'):raise z.ZineError('This submission is under review or was accepted.',409)
                db.execute('UPDATE zine_submissions SET content=?,state=?,revision=revision+1 WHERE id=?',(payload,state,sid))
            else:
                if db.execute('SELECT COUNT(*) FROM zine_submissions WHERE issue_id=? AND author_id=?',(iid,user)).fetchone()[0]>=20:raise z.ZineError('Submission limit reached.',409)
                db.execute('INSERT INTO zine_submissions(id,issue_id,author_id,content,state,created_at) VALUES (?,?,?,?,?,?)',(secrets.token_urlsafe(12),iid,user,payload,state,int(time.time())))
            budget(db,p['owner_id'])
        return redirect(url_for('zines.issue_edit',zid=zid,iid=iid))
    @bp.get('/zines/<zid>/issues/<iid>')
    def reader(zid,iid):
        db=core.get_db();p=z.publication(db,zid);issue=z.get_issue(db,p,iid)
        if not z.visible(db,p,issue,uid()):abort(404)
        rows=z.pages(db,iid);page=request.args.get('page',1,type=int) or 1
        if not 1<=page<=len(rows):abort(404)
        row=rows[page-1]
        return render('reader',publication=p,issue=issue,page=page,total=len(rows),data=json.loads(row['content']),page_kind=row['kind'],role=z.role(db,p,uid()))
    @bp.get('/zines/<zid>/issues/<iid>/print')
    def printing(zid,iid):
        db=core.get_db();p=z.publication(db,zid);issue=z.get_issue(db,p,iid)
        if not z.visible(db,p,issue,uid()) or not p['allow_print'] or not issue['allow_print']:abort(404)
        rows=z.pages(db,iid);number={r['id']:i+1 for i,r in enumerate(rows)}
        if request.args.get('download')=='1':
            response=app.extensions['community_auth_helpers']['limited']('zines-pdf',8,3600,subject=('user:'+str(uid()) if uid() else 'zine-guest:'+str(request.remote_addr)))
            if response is not None:return response
            from .zines_pdf import render as pdf
            data=pdf(rows,lambda aid:asset_bytes(db,p,aid),request.args.get('mode','standard'),request.args.get('paper','letter'),request.args.get('numbers')=='1',issue['title'])
            return send_file(io.BytesIO(data),mimetype='application/pdf',as_attachment=True,download_name='zine-'+iid+'-'+request.args.get('mode','standard')+'.pdf',conditional=False,etag=False,max_age=0)
        arrangement=[tuple(number.get(r['id']) if r else None for r in sheet) for sheet in z.impose(rows)]
        return render('print',publication=p,issue=issue,arrangement=arrangement,blanks=(-len(rows))%4)
    @bp.post('/zines/<zid>/assets')
    def upload(zid):
        from .marketplace_assets import prepare,StudioError
        from .storage_uploads import write,policy
        user=actor();db=core.get_db();p=z.publication(db,zid);z.require(db,p,user,('owner','editor','contributor'))
        response=writing()
        if response is not None:return response
        if policy() is None:raise z.ZineError('Artwork uploads are temporarily unavailable.',503)
        set_cover=request.form.get('set_cover')=='1'
        if set_cover:z.require(db,p,user,('owner',))
        incoming=request.files.get('image')
        if not incoming:raise z.ZineError('Choose an image.')
        raw=incoming.stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise z.ZineError('Images must be no larger than 2 MiB.')
        try:data,_,suffix,_=prepare(raw,incoming.filename,'image')
        except StudioError:raise z.ZineError('Choose a supported, valid image.')
        if len(data)>512*1024:raise z.ZineError('The processed image exceeds 512 KiB. Resize it first.')
        with db:
            db.execute('BEGIN IMMEDIATE');p=z.publication(db,zid);z.require(db,p,user,('owner','editor','contributor'))
            if set_cover:
                z.require(db,p,user,('owner',))
                if revision()!=p['revision']:raise z.ZineError('Publication changed. Reload before replacing the cover.',409)
            if db.execute('SELECT COUNT(*) FROM zine_assets WHERE zine_id=?',(zid,)).fetchone()[0]>=64:raise z.ZineError('Publication image limit reached.',409)
            directory=Path(app.instance_path)/'zines';directory.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(directory,0o700);key=secrets.token_hex(24)+'.webp';aid=secrets.token_urlsafe(18)
            write([(directory/key,data)],'zines')
            db.execute('INSERT INTO zine_assets VALUES (?,?,?,?,?,?,?)',(aid,zid,user,key,len(data),hashlib.sha256(data).hexdigest(),int(time.time())))
            if set_cover:db.execute('UPDATE zines SET cover_asset=?,revision=revision+1 WHERE id=?',(aid,zid))
        return redirect(url_for('zines.edit',zid=zid))
    @bp.get('/zines/<zid>/assets/<aid>')
    def image(zid,aid):
        db=core.get_db();p=z.publication(db,zid);member=z.role(db,p,uid());asset=db.execute('SELECT * FROM zine_assets WHERE id=? AND zine_id=?',(aid,zid)).fetchone()
        allowed=bool(asset and member in ('owner','editor')) or bool(asset and member=='contributor' and asset['uploader_id']==uid())
        if not allowed:
            for issue in db.execute("SELECT * FROM zine_issues WHERE zine_id=? AND state='published'",(zid,)):
                if z.visible(db,p,issue,uid()) and (p['cover_asset']==aid or any(aid in asset_ids(json.loads(row['content'])) for row in z.pages(db,issue['id']))):allowed=True;break
        if not allowed:abort(404)
        response=send_file(io.BytesIO(asset_bytes(db,p,aid)),mimetype='image/webp',conditional=False,etag=False,max_age=0);response.headers['Content-Security-Policy']="sandbox; default-src 'none'";return response
    @bp.get('/zines/<zid>/issues/<iid>/history')
    def history(zid,iid):
        user=actor();db=core.get_db();p=z.publication(db,zid);z.require(db,p,user);issue=z.get_issue(db,p,iid)
        rows=db.execute('SELECT revision,snapshot,created_at FROM zine_revisions WHERE issue_id=? ORDER BY id DESC LIMIT 20',(iid,)).fetchall()
        retained=[]
        for row in rows:
            snapshot=json.loads(row['snapshot']);allowed=True
            for page in snapshot['pages']:
                if not z.compatible(db,page['author_id'],user):allowed=False;break
                for image_id in asset_ids(json.loads(page['content'])):
                    asset=db.execute('SELECT uploader_id FROM zine_assets WHERE id=? AND zine_id=?',(image_id,zid)).fetchone()
                    if not asset or not z.compatible(db,asset['uploader_id'],user):allowed=False;break
            if allowed:retained.append((row,snapshot))
        return render('history',publication=p,issue=issue,revisions=retained)
    app.register_blueprint(bp)
