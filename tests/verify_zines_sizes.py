"""Issue size authorization, atomic validation and physical PDF dimensions."""
import runpy,importlib,io,json
from pathlib import Path
from pypdf import PdfReader
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
client,z,db,iid,edit,pdf=(f[k] for k in ('client','z','db','iid','edit','pdf'))
sizes=importlib.import_module('zine_candidate.zines_sizes');checks=0

def check(v,label):
 global checks
 assert v,label
 checks+=1

def post(**values):
 rev=db.execute('SELECT revision FROM zine_issues WHERE id=?',(iid,)).fetchone()[0]
 return client.post(edit,data={'theme_csrf_token':'fixture-token','revision':rev,'action':'page_size','page_preset':'business','page_orientation':'landscape','resize_content':'scale',**values})
check(sizes.get(db,iid) is None,'Existing issue has no implicit size')
before=[r['content'] for r in z.pages(db,iid)]
check(post().status_code==302,'Owner can choose business-card size')
a=sizes.get(db,iid);check(a['width']==252 and a['height']==144,'Business card landscape')
check([r['content'] for r in z.pages(db,iid)]==before,'Size preserves page content bytes')
html=client.get(edit).data;check(b'data-issue-width="252' in html and b'data-issue-size-dialog' in html,'Native template contains saved issue size')
rows=z.pages(db,iid)
for mode,expected in [('standard',(252,144)),('booklet',(504,144))]:
 data=pdf.render(rows,lambda aid:b'',mode,'issue',page_size=a);reader=PdfReader(io.BytesIO(data));box=reader.pages[0].mediabox
 check(abs(float(box.width)-expected[0])<.01 and abs(float(box.height)-expected[1])<.01,mode+' PDF dimensions')
check(post(page_preset='letter',page_orientation='portrait',resize_content='keep').status_code==302,'Keep physical content size on larger page')
check(sizes.get(db,iid)['content_scale']==a['content_scale'],'Keep retains physical scale')
check(post(page_preset='letter').status_code==302,'Scale up to letter')
old=sizes.get(db,iid);rev=db.execute('SELECT revision FROM zine_issues WHERE id=?',(iid,)).fetchone()[0]
check(post(resize_content='keep').status_code==400,'Reject clipping')
check(sizes.get(db,iid)==old and db.execute('SELECT revision FROM zine_issues WHERE id=?',(iid,)).fetchone()[0]==rev,'Invalid resize rolls back revision and size')
for width,height in [('nan','3'),('inf','2'),('1','2'),('20','3'),('2','2')]:
 check(post(page_preset='custom',page_units='in',page_width=width,page_height=height).status_code==400,'Reject invalid dimensions '+width+' '+height)
check(post(page_preset='custom',page_units='mm',page_width='88.9',page_height='50.8').status_code==302,'Metric business-card dimensions')
with client.session_transaction() as state:state['user_id']=3
check(post().status_code==404,'Contributor cannot change whole issue size')
with client.session_transaction() as state:state['user_id']=1
check(client.post(edit,data={'theme_csrf_token':'fixture-token','revision':0,'action':'page_size'}).status_code==409,'Stale issue revision rejected')
check(client.post(edit,data={'revision':0,'action':'page_size'}).status_code==400,'Size writes require CSRF')
# Fixture for compact DOM checks.
Path('/tmp/zine-compact-fixture.html').write_bytes(client.get(edit).data)
print('PASS',checks,'issue size and PDF checks')
