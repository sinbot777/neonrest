"""Disposable actual-Flask acceptance plus rendered-PDF imposition checks."""
from pathlib import Path
import sys,os,io,json,importlib,smtplib
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('SMTP forbidden'))
smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T34-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
exec(compile(bootstrap,'T34 disposable actual-app bootstrap','exec'))
z=importlib.import_module(package+'.zines_core');pdf=importlib.import_module(package+'.zines_pdf')
from pypdf import PdfReader
from PIL import Image

def post(who,path,**data):return clients[who].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def current(table,key):return query('SELECT * FROM '+table+' WHERE id=?',(key,))[0]
def revision_for(iid):return current('zine_issues',iid)['revision']
def modify(who,iid,**data):return post(who,base+'/issues/'+iid+'/edit',revision=revision_for(iid),**data)
def payload(label='Page content',**updates):return {'heading':label,'text':'Plain fictional text','caption':'','image':'','layout':'text','print_alternative':'',**updates}

check(get('Regular','/zines').status_code==200,'Directory renders')
check(post('Regular','/zines/create',title='Fictional collaborative Zine',description='Sandbox fixture').status_code==302,'Create publication')
zid=query('SELECT id FROM zines WHERE owner_id=?',(users['Regular'],))[0][0];base='/zines/'+zid
check(current('zines',zid)['visibility']=='private','New publication private')
check(get('Writer',base).status_code==404,'Private home denied')
check(post('Writer',base+'/edit',action='settings',revision=0,title='Intrusion').status_code==404,'Other owner denied')
check(post('Regular',base+'/edit',action='member',revision=0,handle='@VMFixtureManager',role='editor').status_code==302,'Owner appoints editor')
check(post('Regular',base+'/edit',action='member',revision=1,handle='@VMFixtureWriter',role='contributor').status_code==302,'Owner appoints contributor')
check(post('Regular',base+'/edit',action='member',revision=2,handle='@VMFixtureTeen',role='editor').status_code==404,'Cross-age collaboration denied')
check(post('Regular',base+'/edit',action='settings',revision=2,title='Fictional collaborative Zine',description='Fictional only',visibility='public',allow_print='1').status_code==302,'Owner enables public and print')
check(post('Manager',base+'/edit',action='issue',revision=3,title='Issue One').status_code==302,'Editor creates issue')
iid=query('SELECT id FROM zine_issues WHERE zine_id=?',(zid,))[0][0];edit=base+'/issues/'+iid+'/edit';read=base+'/issues/'+iid
check(len(query('SELECT * FROM zine_pages WHERE issue_id=?',(iid,)))==2,'Front/back automatically created')
check(get('Manager',edit).status_code==200,'Editor sees editor')
check(get('Writer',edit).status_code==200,'Contributor sees submission workspace')
check(get('OtherManager',read).status_code==404,'Draft reader denied')
check(app.test_client().get(read,environ_overrides=env).status_code==404,'Guest draft denied')
check(get('OtherManager',read+'/print',download='1').status_code==404,'Draft PDF denied')
check(modify('Writer',iid,action='add',**payload()).status_code==404,'Contributor cannot add editorial page')
check(modify('Writer',iid,action='state',state='published').status_code==404,'Contributor cannot publish')
check(modify('Manager',iid,action='add',**payload('Interior A')).status_code==302,'Editor adds page')
check(modify('Regular',iid,action='add',**payload('Interior B')).status_code==302,'Owner adds page')
check(post('Manager',edit,action='add',revision=0,**payload('Stale')).status_code==409,'Stale revision rejected')
check(b'Your entries' in post('Manager',edit,action='add',revision=0,**payload('Saved unsaved text')).data,'Conflict preserves copyable entries')
rows=query("SELECT * FROM zine_pages WHERE issue_id=? AND kind='page' ORDER BY position",(iid,))
check(modify('Manager',iid,action='move',page_id=rows[1]['id'],direction='up').status_code==302,'Reorder interior page')
with app.app_context():ordered=z.pages(core.get_db(),iid)
check(json.loads(ordered[1]['content'])['heading']=='Interior B','Reading order preserved')
check(ordered[0]['kind']=='cover' and ordered[-1]['kind']=='back','Covers pinned')
check(post('Writer',read+'/submit',send='0',**payload('Contributor draft')).status_code==302,'Contributor saves own draft')
sid=query('SELECT id FROM zine_submissions WHERE issue_id=?',(iid,))[0][0]
check(post('OtherManager',read+'/submit',submission_id=sid,revision=0,send='1',**payload()).status_code==404,'Outsider cannot edit contribution')
check(post('Writer',read+'/submit',submission_id=sid,revision=0,send='1',**payload('Accepted contribution')).status_code==302,'Contributor submits for review')
check(modify('Manager',iid,action='review',submission_id=sid,decision='accept').status_code==302,'Editor accepts contribution')
check(current('zine_submissions',sid)['state']=='accepted','Accepted state stored')
check(post('Writer',read+'/submit',submission_id=sid,revision=2,send='1',**payload('Overwrite')).status_code==409,'Accepted content cannot be overwritten')
check(modify('Manager',iid,action='settings',title='Issue One',allow_print='1').status_code==302,'Editor enables issue printing')
check(modify('Manager',iid,action='state',state='published').status_code==302,'Editor publishes')
check(get('OtherManager',read).status_code==200,'Eligible reader reads publication')
check(app.test_client().get(read,environ_overrides=env).status_code==200,'Guest reads adult public issue')
check(b'Fictional collaborative Zine' in get('OtherManager','/zines').data,'Published public directory entry')
check(get('Teen',read).status_code in (403,404),'Age restriction on reader')
check(modify('Manager',iid,action='add',**payload()).status_code==409,'Published edition fixed until draft')
check(get('OtherManager',read+'/print').status_code==200,'Print options visible')
for mode in ['standard','booklet']:
    response=get('OtherManager',read+'/print',download='1',mode=mode,paper='letter')
    check(response.status_code==200 and response.mimetype=='application/pdf',mode+' protected PDF')
    parsed=PdfReader(io.BytesIO(response.data));check('Issue One' in parsed.metadata.title,'PDF title metadata')
    check('no-store' in response.headers['Cache-Control'],'PDF cache privacy')
check(get('OtherManager',read+'/print',download='1',mode='bad').status_code==400,'Invalid PDF format rejected')
check(get('OtherManager',read+'/print',download='1',paper='bad').status_code==400,'Invalid PDF paper rejected')
check(get('OtherManager',read+'/history').status_code==404,'Private history denied')
check(get('Manager',read+'/history').status_code==200,'Editorial revision history')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],users['OtherManager']))
check(get('OtherManager',read).status_code==404,'Block revokes reading')
check(get('OtherManager',read+'/print',download='1').status_code==404,'Block revokes downloads')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Regular'],users['OtherManager']))
change("UPDATE zine_members SET role='contributor' WHERE zine_id=? AND user_id=?",(zid,users['Manager']))
check(modify('Manager',iid,action='state',state='draft').status_code==404,'Role downgrade revokes publication')
change('DELETE FROM zine_members WHERE zine_id=? AND user_id=?',(zid,users['Manager']))
check(get('Manager',edit).status_code==404,'Membership removal revokes editing')
check(modify('Regular',iid,action='state',state='draft').status_code==302,'Return issue to draft')
check(get('OtherManager',read).status_code==404,'Unpublish immediately revokes reader')
check(get('OtherManager',read+'/print',download='1').status_code==404,'Unpublish immediately revokes PDF')
check(clients['Regular'].post(edit,data={'action':'add','revision':revision_for(iid),**payload()},environ_overrides=env).status_code==400,'CSRF required')
check(modify('Regular',iid,action='add',**payload(text='x'*6001)).status_code==400,'Oversized text denied')
check(modify('Regular',iid,action='add',**payload(image='../../private')).status_code==404,'Foreign/path image rejected')
check(modify('Regular',iid,action='add',**payload(heading='<script>alert(1)</script>')).status_code==302,'Text saved literally')
check(b'<script>alert(1)</script>' not in get('Regular',read,page=5).data,'User HTML escaped')
with clients['Regular'].session_transaction() as s:s['fresh_at']=0
check(modify('Regular',iid,action='settings',title='Fresh gate',allow_print='1').status_code==302,'Fresh auth gate redirects')
with clients['Regular'].session_transaction() as s:s['fresh_at']=now

# Independently verify actual rendered PDF objects, text coordinates and paper sizes.
for count in [4,8,12,16,2,3,5,7,9,15]:
    reading=[{'id':str(n),'content':json.dumps({'heading':'PAGE_%02d'%n,'text':'','image':'','caption':'','layout':'text','print_alternative':''})} for n in range(1,count+1)]
    if count==8:check([[int(p['id']) for p in sheet] for sheet in z.impose(reading)]==[[8,1,2,7],[6,3,4,5]],'Specified eight-page imposition')
    padded=list(range(1,count))+[None]*((-count)%4)+[count];n=len(padded)
    expected=[]
    for k in range(n//4):expected.extend([(padded[n-1-2*k],padded[2*k]),(padded[2*k+1],padded[n-2-2*k])])
    for paper in ['letter','a4']:
        standard=PdfReader(io.BytesIO(pdf.render(reading,lambda aid:b'',paper=paper)))
        check([p.extract_text().strip() for p in standard.pages]==['PAGE_%02d'%n for n in range(1,count+1)],str(count)+' '+paper+' actual standard reading order')
        raw=pdf.render(reading,lambda aid:b'',mode='booklet',paper=paper);booklet=PdfReader(io.BytesIO(raw))
        check(len(booklet.pages)==len(expected),str(count)+' '+paper+' sheet-side count')
        actual=[]
        for page in booklet.pages:
            width=float(page.mediabox.width);height=float(page.mediabox.height);halves=[[],[]]
            check(width>height,'Landscape sheet geometry')
            def visitor(text,cm,tm,font,size):
                label=text.strip()
                if label.startswith('PAGE_'):halves[int(cm[0]*tm[4]+cm[2]*tm[5]+cm[4]>=width/2)].append(int(label[5:]))
            page.extract_text(visitor_text=visitor)
            actual.append(tuple(v[0] if v else None for v in halves))
        check(actual==expected,str(count)+' '+paper+' rendered left/right ordering with blanks')
        check(actual[0]==(count,1),'Outer cover pair preserved')
        check('short edge' in booklet.metadata.subject,'Duplex instructions embedded')
# Deliberate overflow and malformed content fail safely, never silently clip.
try:pdf.render([{'id':'a','content':json.dumps({'heading':'Heading','text':'word '*12000,'image':'','caption':'','layout':'text'})},{'id':'b','content':json.dumps({'heading':'Back','text':'','image':'','caption':'','layout':'text'})}],lambda aid:b'')
except z.ZineError:check(True,'Overflow rejected')
else:raise AssertionError('PDF overflow silently clipped')
with app.app_context():
    db=core.get_db();before={r[0]:db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")};z.initialize(db);z.initialize(db);db.commit()
    check(all(db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]==value for name,value in before.items()),'Repeated migration preserves all rows')
print('PASS',checks,'T34 actual-app and rendered-PDF checks; fixtures only')

# Managed artwork, quota attribution, image confidentiality and owner exports.
import sqlite3,hashlib
reservations=importlib.import_module(package+'.storage_reservations')
ledger=w/'zine-ledger.sqlite';sqlite3.connect(ledger).close();limits=reservations.Limits(16*1024*1024,24*1024*1024);book=reservations.connect(ledger,limits);book.initialize();book.db.close()
app.config['STORAGE_POLICY']={'ledger':str(ledger),'account_root':str(w),'per_owner':limits.per_owner,'aggregate':limits.aggregate,'provider_quota':1024*1024*1024,'headroom':32*1024*1024,'ready':True}
app.config['FAMILY_CONSENT_FOLDER']=str(w/'documents');(w/'documents').mkdir(exist_ok=True)
art=io.BytesIO();Image.new('RGB',(400,300),(30,100,180)).save(art,'PNG');art=art.getvalue()
response=post('Writer',base+'/assets',image=(io.BytesIO(art),'art.png'));check(response.status_code==302,'Contributor uploads managed image')
aid=query('SELECT id FROM zine_assets WHERE zine_id=?',(zid,))[0][0];image_url=base+'/assets/'+aid
check(get('Writer',image_url).status_code==200,'Uploader can read draft artwork')
check(get('OtherManager',image_url).status_code==404,'Unpublished image private')
check(post('OtherManager',base+'/assets',image=(io.BytesIO(art),'art.png')).status_code==404,'Outsider cannot upload')
check(post('Writer',base+'/assets',image=(io.BytesIO(b'bad-image'),'fake.png')).status_code==400,'Malformed image rejected')
check(post('Writer',base+'/assets',image=(io.BytesIO(b'x'*(2*1024*1024+1)),'large.png')).status_code in (400,413),'Oversized image rejected')
check(modify('Regular',iid,action='add',**payload('Artwork page',image=aid,layout='image-top',caption='Fictional blue art')).status_code==302,'Editor places artwork')
check(modify('Regular',iid,action='state',state='published').status_code==302,'Publish artwork edition')
check(get('OtherManager',image_url).status_code==200,'Published artwork authorized')
change('DELETE FROM rate_buckets WHERE action=?',('zines-pdf',))
response=get('OtherManager',read+'/print',download='1',mode='booklet',paper='a4');check(response.status_code==200,'Artwork booklet renders')
check(any(page.images for page in PdfReader(io.BytesIO(response.data)).pages),'Actual PDF contains image objects')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Writer'],users['OtherManager']))
check(get('OtherManager',image_url).status_code==404,'Uploader block revokes artwork access')
check(get('OtherManager',read+'/print',download='1').status_code==404,'Uploader block revokes complete PDF')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Writer'],users['OtherManager']))
response=post('Writer','/account/export');check(response.status_code==200 and any(a['id']==aid for a in response.json['zines']['uploaded_artwork']),'Own zine metadata in account export')
response=post('OtherManager','/account/export');check(response.status_code==200 and not response.json['zines']['uploaded_artwork'],'Foreign artwork absent from export')
with sqlite3.connect(ledger) as book:check(book.execute("SELECT COUNT(*) FROM upload_objects WHERE object_key LIKE 'sandbox-zines/%'").fetchone()[0]==1,'Existing quota ledger attributes zine artwork')
media_export=importlib.import_module(package+'.media_export')
with app.app_context():
    candidates=media_export.owner_candidates(app,core.get_db(),users['Writer'],app.config['STORAGE_POLICY']);check(any(category=='uploaded attachment or artwork' and Path(root)==Path(app.instance_path)/'zines' for root,relative,category in candidates),'Own artwork in bounded media export candidates')
    db=core.get_db();pub=z.publication(db,zid);large=z.create_issue(db,pub,users['Regular'],'Page bound fixture');issue=z.get_issue(db,pub,large)
    for n in range(62):z.add_page(db,pub,issue,users['Regular'],payload('Bound '+str(n)))
    try:z.add_page(db,pub,issue,users['Regular'],payload('Too many'))
    except z.ZineError:check(True,'64-page limit enforced')
    else:raise AssertionError('Page limit missing')
    try:z.content(db,zid,users['Regular'],{'text':[]})
    except z.ZineError:check(True,'Malformed structure rejected')
    else:raise AssertionError('Malformed data accepted')
    db.commit()
check(get('Regular','/marketplace').status_code==200,'Marketplace regression smoke')
check(get('Regular','/pages').status_code==200,'Pages regression smoke')
check(get('Regular','/feed').status_code in (200,302),'Feed regression smoke')
print('PASS',checks,'T34 actual-app, images/export and rendered-PDF checks; fixtures only')

# Both independent print permission gates revoke downloads immediately.
row=current('zines',zid)
check(post('Regular',base+'/edit',action='settings',revision=row['revision'],title=row['title'],description=row['description'],visibility='public').status_code==302,'Owner disables publication print permission')
check(get('OtherManager',read+'/print').status_code==404,'Publication print disable enforced')
row=current('zines',zid)
check(post('Regular',base+'/edit',action='settings',revision=row['revision'],title=row['title'],description=row['description'],visibility='public',allow_print='1').status_code==302,'Owner reenables publication print permission')
check(modify('Regular',iid,action='state',state='draft').status_code==302,'Unpublish for issue print setting')
check(modify('Regular',iid,action='settings',title='Issue One').status_code==302,'Editor disables issue print permission')
check(modify('Regular',iid,action='state',state='published').status_code==302,'Publish digital-only issue')
check(get('OtherManager',read).status_code==200 and get('OtherManager',read+'/print').status_code==404,'Digital reading independent of print permission')
print('PASS',checks,'T34 final acceptance checks; fixture-only')

row=current('zines',zid)
response=post('Regular',base+'/assets',set_cover='1',revision=row['revision'],image=(io.BytesIO(art),'cover.png'))
check(response.status_code==302,'Owner uploads and sets cover in one action')
cover=current('zines',zid)['cover_asset'];check(bool(cover),'Cover selected automatically')
check(current('zines',zid)['revision']==row['revision']+1,'Cover update advances revision')
check(post('Regular',base+'/assets',set_cover='1',revision=row['revision'],image=(io.BytesIO(art),'stale.png')).status_code==409,'Stale cover replacement rejected')
check(post('Writer',base+'/assets',set_cover='1',revision=current('zines',zid)['revision'],image=(io.BytesIO(art),'denied.png')).status_code in (403,404),'Contributor cannot replace publication cover')
check(b'Upload and use as cover' in get('Regular',base+'/edit').data,'Direct cover upload visible')
check(b'zine-directory-grid' in get('Regular','/zines').data,'Directory grid renders')
print('PASS',checks,'T34 directory and cover acceptance checks')

# Focused workspace controls, permissions, revision recovery and print parity.
check(modify('Regular',iid,action='state',state='draft').status_code==302,'Workspace returns issue to draft')
page_rows=query("SELECT * FROM zine_pages WHERE issue_id=? ORDER BY CASE kind WHEN 'cover' THEN 0 WHEN 'page' THEN 1 ELSE 2 END,position",(iid,))
target=next(row for row in page_rows if row['kind']=='page')
html=get('Regular',base+'/issues/'+iid+'/edit',page=2).data
check(b'Issue outline' in html and b'Saved page preview' in html,'Outline and saved preview visible')
check(html.count(b'name="action" value="page"')==1,'Only one page editor shown')
check(all(label in html for label in (b'Body text size',b'Accent color',b'Image width',b'Image alignment')),'Granular page controls visible')
check(b'Issue outline' not in get('Writer',base+'/issues/'+iid+'/edit').data,'Contributor workspace does not expose editorial pages')
check(b'Issue settings' in get('Regular',base+'/issues/'+iid+'/edit',tab='settings').data,'Dedicated settings view')
check(b'Publish &amp; print' in get('Regular',base+'/issues/'+iid+'/edit',tab='publish').data,'Dedicated publish view')
new_values=payload(heading='Workspace custom page',text='A short fictional paragraph for layout testing.',design='punk',accent='cobalt',text_size='large',image_width='small',image_align='right',image=cover)
check(modify('Regular',iid,action='page',page_id=target['id'],workspace_page='2',**new_values).status_code==302,'Granular controls saved')
saved=json.loads(current('zine_pages',target['id'])['content'])
check(all(saved[key]==new_values[key] for key in ('accent','text_size','image_width','image_align')),'Granular choices retained')
reader=get('Regular',read,page=2).data
check(all(value in reader for value in (b'zine-accent-cobalt',b'zine-body-large',b'zine-image-small',b'zine-align-right')),'Reader applies granular styles')
for key,value in [('accent','url(javascript:bad)'),('text_size','enormous'),('image_width','99999'),('image_align','position:fixed')]:
    bad={**new_values,key:value}
    check(modify('Regular',iid,action='page',page_id=target['id'],**bad).status_code==400,'Unsafe or unsupported '+key+' rejected')
ids={row['id'] for row in query('SELECT id FROM zine_pages WHERE issue_id=?',(iid,))}
check(modify('Regular',iid,action='duplicate',page_id=target['id']).status_code==302,'Interior page duplicated')
new_ids={row['id'] for row in query('SELECT id FROM zine_pages WHERE issue_id=?',(iid,))}-ids
check(len(new_ids)==1,'Exactly one duplicate created')
copy_id=new_ids.pop()
check(current('zine_pages',copy_id)['author_id']==target['author_id'],'Duplicate preserves attribution')
front=next(row for row in page_rows if row['kind']=='cover')
check(modify('Regular',iid,action='delete',page_id=front['id']).status_code==400,'Cover removal rejected')
check(modify('Writer',iid,action='duplicate',page_id=target['id']).status_code in (403,404),'Contributor cannot duplicate editorial page')
check(modify('Regular',iid,action='delete',page_id=copy_id).status_code==302,'Interior page removed')
check(not query('SELECT id FROM zine_pages WHERE id=?',(copy_id,)),'Only selected page removed')
check(any(copy_id in row['snapshot'] for row in query('SELECT snapshot FROM zine_revisions WHERE issue_id=?',(iid,))),'Removed page recoverable from retained history')
check(modify('Regular',iid,action='settings',title='Issue One',allow_print='1').status_code==302,'Enable fixture print edition')
response=get('Regular',read+'/print',download='1',mode='standard',paper='letter')
check(response.status_code==200,'Custom page renders in standard PDF')
doc=PdfReader(io.BytesIO(response.data));ops=doc.pages[1].get_contents().operations
check(any(op==b'rg' and len(args)==3 and all(abs(float(args[i])-v)<0.0001 for i,v in enumerate((23/255,76/255,153/255))) for args,op in ops),'PDF uses selected cobalt accent')
check(b'Workspace custom page'.lower() in ' '.join((doc.pages[1].extract_text() or '').split()).lower().encode(),'Custom page PDF text remains selectable')
print('PASS',checks,'T34 workspace acceptance checks')

from types import SimpleNamespace
records=[]
design_module=importlib.import_module(package+'.zines_design')
design_module._picture(SimpleNamespace(drawImage=lambda *args,**kwargs:records.append(args)),'fixture',lambda _:art,400,width_fraction=.34,alignment='right')
check(records[0][3]<=348*.34+.01,'Print image width respects selected fraction')
check(abs(records[0][1]-(24+348-records[0][3]))<.01,'Print image aligns to right edge')
check(any(op==b'Tf' and abs(float(args[1])-10.8)<.001 for args,op in ops),'PDF uses selected large body size')
print('PASS',checks,'T34 final workspace acceptance checks')

from flask import session
fresh=app.extensions['community_auth_helpers']['fresh']
for path,age,expected in [('/manage',23*3600,True),('/manage',25*3600,False),('/staff',23*3600,True),('/account/security',3600,False),('/account/security',60,True)]:
    with app.test_request_context(path):
        session.update(user_id=users['Regular'],fresh_at=now-age,factor_at=now-age)
        check(fresh()==expected,'Reauthentication window '+path+' '+str(age))
with app.test_request_context('/manage'):
    session.update(user_id=users['Regular'],fresh_at=now,factor_at=now-25*3600)
    check(not fresh(),'Staff window still requires a recent second factor')
with clients['Regular'].session_transaction() as s:s.update(fresh_at=0,factor_at=0)
row=current('zines',zid)
check(post('Regular',base+'/edit',action='settings',revision=row['revision'],title='No extra factor for writing',description=row['description'],visibility='private',allow_print='1').status_code==302,'Stale step-up session can save Zine')
check(current('zines',zid)['title']=='No extra factor for writing','Zine save really occurred without reauthentication')
print('PASS',checks,'T34 auth window acceptance checks')
