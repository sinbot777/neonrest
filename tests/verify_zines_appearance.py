"""Disposable route tests: inheritance, validation, permissions, revisions and PDF isolation."""
import runpy,importlib,json,hashlib
from pathlib import Path
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
client,z,db,iid,edit,app,pdf=(f[k] for k in ('client','z','db','iid','edit','app','pdf'))
a=importlib.import_module('zine_candidate.zines_appearance');zid=f['zid'];base='/zines/'+zid
checks=0
def check(v,label):
 global checks
 assert v,label
 checks+=1
def who(n):
 with client.session_transaction() as state:state['user_id']=n
def rev(scope):return db.execute('SELECT revision FROM '+('zines' if scope=='publication' else 'zine_issues')+' WHERE id=?',(zid if scope=='publication' else iid,)).fetchone()[0]
def save(scope='publication',**values):
 data={'theme_csrf_token':'fixture-token','revision':rev(scope),'action':'appearance','workspace_tab':'settings',**{'backdrop_'+k:str(v) for k,v in a.DEFAULT.items()},**values}
 return client.post(base+'/edit' if scope=='publication' else edit,data=data)
who(1)
check(a.context(db,zid,iid)['backdrop']==a.DEFAULT,'Warm paper fallback')
before=[dict(r) for r in z.pages(db,iid)]
check(save(backdrop_pattern='grid',backdrop_color='#EADDDD',backdrop_scale='150').status_code==302,'Owner saves publication appearance')
check(a.context(db,zid,iid)['backdrop']['pattern']=='grid','Issue inherits publication')
check(a.context(db,zid,iid)['backdrop']['color']=='#eadddd','Normalize color')
check(save('issue',backdrop_pattern='halftone',backdrop_mode='override').status_code==302,'Draft issue override')
check(a.context(db,zid,iid)['backdrop']['pattern']=='halftone','Override wins')
check(save(backdrop_pattern='dots').status_code==302,'Publication can change independently')
check(a.context(db,zid,iid)['backdrop']['pattern']=='halftone','Override retained after publication edit')
check(save('issue',backdrop_mode='inherit').status_code==302,'Remove override')
check(a.context(db,zid,iid)['backdrop']['pattern']=='dots','Inheritance restored')
check(before==[dict(r) for r in z.pages(db,iid)],'No page bytes changed')
for key,value in [('pattern','url(https://invalid)'),('color','#fff;display:none'),('ink','red'),('scale','49'),('scale','201'),('intensity','61'),('intensity','NaN')]:
 previous=rev('publication');check(save(**{'backdrop_'+key:value}).status_code==400,'Reject malformed '+key)
 check(rev('publication')==previous,'Invalid appearance does not increment revision')
check(save(revision=0).status_code==409,'Stale revision rejected')
check(save(theme_csrf_token='wrong').status_code==400,'CSRF required')
who(3);check(save().status_code==404,'Contributor cannot save publication appearance');check(save('issue').status_code==404,'Contributor cannot save issue appearance')
with db:db.execute('INSERT INTO zine_members VALUES (?,?,?)',(zid,2,'editor'))
who(2);check(save(backdrop_pattern='collage').status_code==302,'Editor can style publication')
who(1)
for pattern,_ in a.PATTERNS:
 check(save(backdrop_pattern=pattern).status_code==302,'Save '+pattern)
 page=client.get(base+'/issues/'+iid+'?reading=scroll');check(page.status_code==200 and ('data-zine-pattern="'+pattern+'"').encode() in page.data,'Render '+pattern)
check(b'Plain background' in page.data,'Reader plain toggle available')
check(b'Backdrop source' in client.get(edit+'?tab=settings').data,'Issue override UI')
check(b'Warm paper' in client.get(base+'/edit').data,'Publication swatches UI')
rows=z.pages(db,iid)
def pdf_text():
 from pypdf import PdfReader
 import io
 return [(p.mediabox.width,p.mediabox.height,p.extract_text()) for p in PdfReader(io.BytesIO(pdf.render(rows,lambda _:b''))).pages]
before_pdf=pdf_text();save(backdrop_pattern='drafting',backdrop_intensity='60');check(pdf_text()==before_pdf,'Backdrop never enters PDF renderer')
with db:db.execute("UPDATE zine_issues SET state='published' WHERE id=?",(iid,))
check(save('issue').status_code==409,'Published issue requires draft for appearance changes')
print('PASS',checks,'appearance route and PDF checks')
