"""Focused local component tests. Host full-app acceptance is a separate gate.
Identity/age and CSRF adapters are fixture-only; publication/editor permissions,
transactions, storage, template and PDF code execute without replacement.
"""
from pathlib import Path
import importlib,sys,types,sqlite3,json,io
from flask import Flask,abort,session,request
ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('zine_candidate');package.__path__=[str(ROOT)];sys.modules[package.__name__]=package
for name in ['identity_pages','age_policy','request_cache']:
 m=types.ModuleType('zine_candidate.'+name);sys.modules[m.__name__]=m
sys.modules['zine_candidate.identity_pages'].eligible=lambda db,uid,kind:uid in (1,2,3)
sys.modules['zine_candidate.age_policy'].contact=lambda *a:True
sys.modules['zine_candidate.age_policy'].can_read=lambda *a:True
sys.modules['zine_candidate.request_cache'].request_lookup=lambda f:f
z=importlib.import_module('zine_candidate.zines_core');routes=importlib.import_module('zine_candidate.zines');composition=importlib.import_module('zine_candidate.zines_composition');pdf=importlib.import_module('zine_candidate.zines_pdf')
from pypdf import PdfReader
from jinja2 import ChoiceLoader,DictLoader,FileSystemLoader
app=Flask('zine_candidate',template_folder=str(ROOT/'templates'));app.secret_key='disposable-fixture-only';app.testing=True
app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),FileSystemLoader(str(ROOT/'templates'))])
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT);INSERT INTO users VALUES(1,"owner"),(2,"editor"),(3,"contributor");CREATE TABLE user_blocks(user_id INTEGER,target_id INTEGER);CREATE TABLE user_mutes(user_id INTEGER,target_id INTEGER);')
core=types.SimpleNamespace(get_db=lambda:db,theme_csrf_token=lambda:'fixture-token')
def csrf():
 if request.form.get('theme_csrf_token')!='fixture-token':abort(400)
app.extensions['community_auth_helpers']={'csrf':csrf,'limited':lambda *a:None}
routes.register(app,core)
client=app.test_client();checks=0
with client.session_transaction() as state:state['user_id']=1
zid=z.create(db,1,'Component fixture','');pub=z.publication(db,zid);iid=z.create_issue(db,pub,1,'Issue fixture')
db.execute('INSERT INTO zine_members VALUES (?,?,?)',(zid,3,'contributor'))
for heading in ['First','Second','Third']:z.add_page(db,pub,z.get_issue(db,pub,iid),1,{'heading':heading,'text':'Fixture body.'})
db.commit();edit='/zines/'+zid+'/issues/'+iid+'/edit'
def check(value,label):
 global checks
 assert value,label
 checks+=1

def rev():return z.get_issue(db,pub,iid)['revision']
def post(**data):return client.post(edit,data={'theme_csrf_token':'fixture-token','revision':rev(),**data})
def middle():return [r['id'] for r in z.pages(db,iid) if r['kind']=='page']
original=middle();cover=z.pages(db,iid)[0]['id'];back=z.pages(db,iid)[-1]['id']
response=client.get(edit+'?tab=organize');check(response.status_code==200 and b'Facing spreads' in response.data,'Organizer renders from actual template')
response=client.get(edit);check(response.status_code==200 and b'data-prop="rotation"' in response.data,'Advanced editor template renders')
check(post(action='reorder',page_order=json.dumps(original[::-1])).status_code==302,'Valid reorder saves')
check(middle()==original[::-1],'Reordered pages stored')
for order in [original+[cover],original+[back],original[:-1],original+[original[0]],['foreign-page'],{},None]:
 before=rev();snapshots=db.execute('SELECT COUNT(*) FROM zine_revisions').fetchone()[0]
 check(post(action='reorder',page_order=json.dumps(order)).status_code==400,'Invalid permutation rejected')
 check(rev()==before and middle()==original[::-1] and db.execute('SELECT COUNT(*) FROM zine_revisions').fetchone()[0]==snapshots,'Invalid reorder rolls back revision, snapshot, order')
check(post(action='duplicate_many',page_ids=original[:2]).status_code==302,'Bulk duplicate saves')
check(len(z.pages(db,iid))==7,'Correct duplicate count')
for ids in [[cover],[back],['foreign'],[original[0],original[0]],[]]:
 before=rev();count=len(z.pages(db,iid));check(post(action='duplicate_many',page_ids=ids).status_code==400,'Invalid duplicate rejected');check(rev()==before and len(z.pages(db,iid))==count,'Invalid duplicate atomic')
with client.session_transaction() as state:state['user_id']=3
check(post(action='reorder',page_order=json.dumps(middle())).status_code==404,'Contributor reorder denied')
with client.session_transaction() as state:state['user_id']=1
check(post(action='reorder',revision=0,page_order=json.dumps(middle())).status_code==409,'Stale reorder denied')
check(post(action='reorder',theme_csrf_token='bad',page_order=json.dumps(middle())).status_code==400,'CSRF rejection')
layout={'version':1,'background':'#ffffff','blocks':[{'id':'headline','type':'text','x':60,'y':60,'w':250,'h':100,'text':'Rotated selectable headline','rotation':12,'opacity':.6,'group':'group1','name':'Headline','size':22,'font':'bold'}]}
normalized=composition.normalize(layout);check(normalized['blocks'][0]['rotation']==12 and normalized['blocks'][0]['opacity']==.6,'Advanced fields normalize')
for key,value in [('rotation',True),('rotation',float('nan')),('rotation',999),('opacity',0),('opacity',False),('group','<unsafe>'),('name','x'*81)]:
 bad=json.loads(json.dumps(layout));bad['blocks'][0][key]=value
 try:composition.normalize(bad)
 except z.ZineError:check(True,'Malformed advanced field rejected')
 else:raise AssertionError('Accepted invalid '+key)
for x,y in [(0,0),(380,600)]:
 bad=json.loads(json.dumps(layout));bad['blocks'][0].update(x=x,y=y,rotation=45)
 try:composition.normalize(bad)
 except z.ZineError:check(True,'Rotated page bounds enforced')
 else:raise AssertionError('Off-page rotation accepted')
target=next(r for r in z.pages(db,iid) if r['kind']=='page')
check(post(action='page',page_id=target['id'],design='composition',composition=json.dumps(layout),layout='text').status_code==302,'Actual route saves advanced composition')
row=db.execute('SELECT * FROM zine_pages WHERE id=?',(target['id'],)).fetchone();data=json.loads(row['content']);check(data['composition']['blocks'][0]['group']=='group1','Group saved through route')
response=client.get('/zines/'+zid+'/issues/'+iid+'?page=2');check(response.status_code==200 and b'rotate(12' in response.data and b'opacity:0.6' in response.data,'Reader applies saved transforms')
for paper in ['letter','a4']:
 for mode in ['standard','booklet']:
  raw=pdf.render(z.pages(db,iid),lambda aid:b'',mode,paper);parsed=PdfReader(io.BytesIO(raw));text=' '.join(' '.join(p.extract_text() or '' for p in parsed.pages).split());check('Rotated selectable headline' in text,'Rotated PDF text selectable '+paper+' '+mode)
  check(any('/ExtGState' in p['/Resources'] for p in parsed.pages),'PDF transparency resources '+paper+' '+mode)
print('PASS',checks,'local component checks; host full-app suite remains separate')
if '--dom-fixture' in sys.argv:
 from flask import render_template
 with client.session_transaction() as state:state['user_id']=1
 with app.test_request_context(edit):
  session['user_id']=1
  fixture=render_template('zines.html',view='issue_edit',token='fixture-token',waveform=z.wave(),selected_page=2,workspace_tab='pages',publication=pub,issue=z.get_issue(db,pub,iid),role='owner',pages=[(r,json.loads(r['content'])) for r in z.pages(db,iid)],submissions=[],assets=[{'id':'art-one'},{'id':'art-two'}])
 Path('/tmp/zine-dom-fixture.html').write_text(fixture)
