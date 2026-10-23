"""Actual gallery routes on fictional SQLite with explicit identity/age stubs."""
import importlib.util
import json
import os
import sqlite3
import sys
import types
from pathlib import Path
from flask import Flask, session, abort
from jinja2 import DictLoader

root=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('gallery_fixture');pkg.__path__=[str(root)];sys.modules[pkg.__name__]=pkg
ages=types.ModuleType('gallery_fixture.age_policy');ages.ready=lambda db,uid:uid!=4
sys.modules[ages.__name__]=ages
spec=importlib.util.spec_from_file_location('gallery_fixture.theme_gallery',root/'theme_gallery.py')
gallery=importlib.util.module_from_spec(spec);spec.loader.exec_module(gallery)
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,verified INTEGER);
CREATE TABLE user_moderation(user_id INTEGER,banned INTEGER,posting_restricted INTEGER,interaction_restricted INTEGER);
CREATE TABLE account_safety(user_id INTEGER,inactive INTEGER);
CREATE TABLE account_disables(user_id INTEGER,disabled INTEGER);
INSERT INTO users VALUES(1,1),(2,1),(3,0),(4,1),(5,1);
INSERT INTO user_moderation VALUES(5,1,0,0);''')
app=Flask(__name__);app.secret_key='fictional-gallery-test'
app.jinja_loader=DictLoader({'base.html':'{% block content %}{% endblock %}',**{str(p.relative_to(root/'templates')):p.read_text() for p in (root/'templates').rglob('*.html') if p.name!='base.html'}})
class Core:
    get_db=staticmethod(lambda:db)
    theme_csrf_token=staticmethod(lambda:session.setdefault('theme_csrf_token','fixture-token'))
    has_staff_permission=staticmethod(lambda db,uid,permission:uid==1 and permission=='approve_vibes')
    @staticmethod
    def require_staff_permission(permission):
        if not Core.has_staff_permission(db,session.get('user_id'),permission):abort(403)
gallery.register(app,Core)
@app.teardown_request
def rollback(error):
    if db.in_transaction:db.rollback()
client=app.test_client();checks=0
def check(ok,label):
    global checks
    assert ok,label
    checks+=1
def login(uid):
    with client.session_transaction() as s:s.clear();s.update(user_id=uid,theme_csrf_token='fixture-token')
style={k:None if k in gallery.COLORS else '' for k in gallery.LIMITS}
style['custom_css']='body.vibe-fixture--day {--vibe-ink:#222222}'
data={'format':'neonrest-theme','version':1,'mode':'day','style':style}
def submission(**changes):return {'theme_csrf_token':'fixture-token','agreement_version':gallery.AGREEMENT,'accept_license':'yes','title':'Fixture theme','description':'Plain description','credit':'Fixture Author','scope_slug':'fixture','theme_json':json.dumps(data),**changes}
def send(**changes):return client.post('/themes/gallery/submit',data=submission(**changes))
def latest():return db.execute('SELECT * FROM theme_gallery_entries ORDER BY id DESC LIMIT 1').fetchone()
def review(ref,decision='approved',**changes):return client.post('/manage/themes/gallery',data={'theme_csrf_token':'fixture-token','public_id':ref,'decision':decision,'reason':'Reviewed fixture rights assertion and CSS','review_checked':'yes',**changes})
check(client.get('/themes/gallery').status_code==200,'Empty free gallery is public')
check(client.get('/themes/gallery/submit').status_code==403,'Anonymous submission blocked')
for uid in [3,4,5]:
    login(uid);check(send().status_code==403,'Unverified, age-unready or banned author blocked')
login(2)
page=client.get('/themes/gallery/submit')
check(page.status_code==200 and b'name="accept_license" value="yes" required' in page.data and b'checked' not in page.data,'Agreement is explicit and unchecked')
failed=send(accept_license='');check(failed.status_code==400,'Acceptance required')
check(b'Fixture theme' in failed.data and b'role="alert"' in failed.data,'Validation retains edits with a readable error')
check(send(agreement_version='old').status_code==400,'Current agreement version required')
check(send(theme_csrf_token='bad').status_code==400,'Submission CSRF')
check(send(theme_csrf_token='ñ').status_code==400,'Non-ASCII CSRF fails safely')
check(send(theme_json='bad').status_code==400,'Malformed JSON refused')
bad=json.loads(json.dumps(data));bad['style']['bg_color']='red'
check(send(theme_json=json.dumps(bad)).status_code==400,'Invalid color refused')
bad=json.loads(json.dumps(data));bad['style']['custom_css']='</style><script>bad()</script>'
check(send(theme_json=json.dumps(bad)).status_code==400,'HTML refused')
check(send(credit='Bad */ credit').status_code==400,'License comment cannot be escaped')
check(send(scope_slug='bad"slug').status_code==400,'Unsafe CSS scope refused')
check(send().status_code==302,'Submission queued')
row=latest();ref=row['public_id'];original=row['style_json']
check(row['status']=='pending','Pending is default')
agreement=db.execute('SELECT * FROM theme_gallery_agreements').fetchone()
check(agreement['actor_id']==2 and agreement['agreement_version']==gallery.AGREEMENT and agreement['content_sha256']==row['content_sha256'] and gallery.MIT in agreement['agreement_text'],'Version, text, actor and exact snapshot hash recorded')
check(b'Fixture theme' not in client.get('/themes/gallery').data,'Pending excluded publicly')
check(client.get('/themes/gallery/'+ref).status_code==404,'Pending detail hidden')
check(client.get('/themes/gallery/'+ref+'/download').status_code==404,'Pending download hidden')
check(client.get('/manage/themes/gallery/'+ref+'/preview').status_code==403,'Ordinary author cannot use staff preview')
check(review(ref).status_code==403,'Ordinary author cannot approve')
login(1)
check(client.get('/manage/themes/gallery/'+ref+'/preview').status_code==200,'Staff can inspect isolated pending preview')
check(review(ref,theme_csrf_token='bad').status_code==400,'Review CSRF')
check(review(ref,review_checked='').status_code==400,'Review acknowledgement required')
check(review(ref).status_code==302,'Authorized staff approval')
check(db.execute("SELECT COUNT(*) FROM theme_gallery_events WHERE action='approved'").fetchone()[0]==1,'Review decision audited')
check(review(ref).status_code==409,'Stale duplicate approval refused')
check(db.execute('SELECT style_json FROM theme_gallery_entries WHERE public_id=?',(ref,)).fetchone()[0]==original,'Review never changes immutable source')
login(None)
check(b'Fixture theme' in client.get('/themes/gallery').data,'Approved entry discoverable')
page=client.get('/themes/gallery/'+ref)
detail_html=page.data
check(b'sandbox=""' in page.data and b'gallery-theme-data' in page.data,'Public sample uses isolated frame and encoded data')
check(page.status_code==200 and b'Fixture Author' in page.data and b'account email' not in page.data,'Public detail contains chosen credit')
download=client.get('/themes/gallery/'+ref+'/download?target=new-vibe')
payload=json.loads(download.data)
check(download.status_code==200 and 'attachment' in download.headers['Content-Disposition'],'Safe JSON attachment')
check('vibe-new-vibe--day' in payload['style']['custom_css'] and 'vibe-fixture--day' not in payload['style']['custom_css'],'Exact mode CSS scope retargeted')
check('Fixture Author' in payload['style']['custom_css'] and gallery.MIT in payload['style']['custom_css'],'Copyright and full MIT notice travel with style')
check('owner_id' not in download.get_data(as_text=True) and 'fixture-token' not in download.get_data(as_text=True),'No account identifiers or credentials in export')
check(client.get('/themes/gallery/'+ref+'/download?target=bad!').status_code==400,'Unsafe target refused')
check(client.get('/themes/gallery?before=bad').status_code==400,'Malformed seek boundary refused')
login(2)
check(send(parent=ref,credit='Remixer').status_code==302,'Independent remix submission')
remix=latest();remix_ref=remix['public_id']
check(remix['parent_id']==row['id'] and 'Fixture Author' in remix['credits_json'] and 'Remixer' in remix['credits_json'],'Trusted lineage and inherited credits')
login(1);check(review(remix_ref).status_code==302,'Remix reviewed independently')
check(client.post('/themes/gallery/'+ref+'/withdraw',data={'theme_csrf_token':'fixture-token'}).status_code==403,'Staff cannot use owner withdrawal endpoint for another author')
login(2)
check(client.post('/themes/gallery/'+ref+'/withdraw',data={'theme_csrf_token':'bad'}).status_code==400,'Withdrawal CSRF')
check(client.post('/themes/gallery/'+ref+'/withdraw',data={'theme_csrf_token':'fixture-token'}).status_code==302,'Author can withdraw listing')
check(client.get('/themes/gallery/'+ref+'/download').status_code==404,'Withdrawn source no new downloads')
check(client.get('/themes/gallery/'+remix_ref+'/download').status_code==200,'Independent remix survives source withdrawal')
check('Fixture Author' in client.get('/themes/gallery/'+remix_ref+'/download').get_data(as_text=True),'Earlier attribution retained after withdrawal')
check(db.execute('SELECT COUNT(*) FROM theme_gallery_agreements').fetchone()[0]==2,'Withdrawal preserves acceptance evidence')
check(send(parent=ref).status_code==404,'Cannot start new listed remix from withdrawn source')
for i in range(3):check(send(title='Queued '+str(i)).status_code==302,'Bounded queue accepts within limit')
check(send(title='Overflow').status_code==429,'Daily/pending quota enforced')
owned=gallery.export_user(db,2)
check(len(owned['submissions'])==5,'Account export includes own submissions and acceptance')
check(gallery.export_user(db,1)=={'submissions':[]},'Account export excludes other authors')
check('actor_id' not in json.dumps(owned) and 'owner_id' not in json.dumps(owned),'Export omits internal reviewer/owner IDs')
gallery.initialize(db)
check(db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==5 and db.execute('SELECT COUNT(*) FROM theme_gallery_entries').fetchone()[0]==5,'Initialization idempotent, existing users preserved')
print(checks,'theme gallery route/privacy/approval/license/remix checks passed')

# Larger fictional listing fixture, inserted directly only to exercise seek windows.
for i in range(25):
    db.execute("INSERT INTO theme_gallery_entries(public_id,owner_id,title,description,credit,mode,scope_slug,style_json,content_sha256,credits_json,status) VALUES(?,2,?,'','Fixture','day','fixture',?,?,?,'approved')", ('paging-'+str(i),'Paging '+str(i),original,row['content_sha256'],row['credits_json']))
db.commit()
login(None)
page=client.get('/themes/gallery')
import re
boundary=re.search(rb'before=(\d+)',page.data).group(1).decode()
page2=client.get('/themes/gallery?before='+boundary)
check(len(re.findall(rb'/themes/gallery/paging-',page.data))==20,'Public window bounded to 20')
check(len(re.findall(rb'/themes/gallery/paging-',page2.data))==5 and b'Fixture theme' in page2.data,'Public continuation complete')
login(1)
check(client.get('/manage/themes/gallery?status=approved').status_code==200,'Approved review listing available')
check(client.get('/manage/themes/gallery?status=bad').status_code==400,'Invalid review filter refused')
check(client.get('/manage/themes/gallery?before=bad').status_code==400,'Invalid review seek refused')
check(b'Paging 24' not in client.get('/themes/gallery/mine').data,'Own-submission view isolates author')
print(checks,'total gallery checks including seek and export passed')

# Exercise the real account-export hook; unrelated export components are stubs.
import ast,time
from flask import Response
tree=ast.parse((root/'community_features.py').read_text())
export_node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='community_export')
for module_name,fn in [('vibe_atmosphere',lambda db,uid:{}),('social_connections',lambda db,uid:{}),('reading_tools',lambda db,uid,identifiers:{})]:
    stub=types.ModuleType('gallery_fixture.'+module_name);stub.export_user=fn;sys.modules[stub.__name__]=stub
sys.modules['gallery_fixture.theme_gallery']=gallery
export_app=Flask('gallery-export');export_app.secret_key='fictional-export-test'
core=types.SimpleNamespace(identifiers=types.SimpleNamespace(export_ids=lambda db,data:None))
namespace=dict(app=export_app,core=core,get_db=lambda:db,current_user=lambda:db.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone(),csrf=lambda:None,fresh=lambda:True,session=session,redirect=lambda x:x,url_for=lambda *a,**k:'/',time=time,json=json,Response=Response,__package__='gallery_fixture')
exec(compile(ast.Module(body=[export_node],type_ignores=[]),'actual account export','exec'),namespace)
export_client=export_app.test_client()
with export_client.session_transaction() as sess:sess['user_id']=2
result=export_client.post('/account/export')
check(result.status_code==200 and len(result.json['theme_gallery']['submissions'])==30,'Actual account-export route includes owned gallery data')
with export_client.session_transaction() as sess:sess['user_id']=1
check(export_client.post('/account/export').json['theme_gallery']=={'submissions':[]},'Actual account export cannot include another author gallery data')
print(checks,'total gallery checks including account route passed')

if os.environ.get('NEONREST_GALLERY_TEST_OUTPUT'):
    out=Path(os.environ['NEONREST_GALLERY_TEST_OUTPUT']);out.mkdir(exist_ok=True)
    (out/'detail.html').write_bytes(detail_html)
    (out/'download.json').write_text(json.dumps(payload))
