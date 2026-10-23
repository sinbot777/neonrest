"""Execute the actual edit route against fictional SQLite, never a live DB."""
import ast
import hmac
import os
import sqlite3
from pathlib import Path
from flask import Flask, request, session, abort, redirect, url_for, render_template
from jinja2 import DictLoader

root = Path(__file__).resolve().parents[1]
source = ast.parse((root/'app.py').read_text())
route = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name=='edit_theme')
db = sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
db.executescript('''
CREATE TABLE vibes(id INTEGER PRIMARY KEY,name TEXT,theme_id INTEGER,logo_url TEXT,logo_width TEXT,logo_height TEXT,logo_padding TEXT,logo_align TEXT,welcome_message TEXT);
CREATE TABLE pending_vibes(vibe_id INTEGER);
CREATE TABLE themes(id INTEGER PRIMARY KEY,slug TEXT,name TEXT,mode TEXT,custom_css TEXT,bg_color TEXT,text_color TEXT,glow_color TEXT,background_layers TEXT,blend_mode TEXT,font_stack TEXT);
CREATE TABLE theme_versions(id INTEGER PRIMARY KEY,theme_id INTEGER,bg_color TEXT,text_color TEXT,glow_color TEXT,background_layers TEXT,blend_mode TEXT,font_stack TEXT,custom_css TEXT,saved_at TEXT DEFAULT CURRENT_TIMESTAMP);
INSERT INTO vibes VALUES(1,'Fixture',1,'/static/original.png',NULL,NULL,NULL,'center','Hello');
INSERT INTO themes VALUES(1,'fixture','Fixture','day','original day',NULL,'#222222',NULL,'','', '');
INSERT INTO themes VALUES(2,'fixture','Fixture','night','original night','#111111','#eeeeee',NULL,'','', '');
INSERT INTO theme_versions(theme_id,custom_css,text_color) VALUES(1,'older day','#333333');
INSERT INTO theme_versions(theme_id,custom_css,text_color) VALUES(2,'older night','#dddddd');
''')
app=Flask(__name__);app.secret_key='fictional-theme-test'
app.jinja_loader=DictLoader({'base.html':'{% block content %}{% endblock %}',
    'edit_theme.html':(root/'templates/edit_theme.html').read_text()})
app.jinja_env.globals['community_token']=lambda:'fixture-token'
for endpoint in ('edit_theme_index','theme_preview','vibe_page'):
    app.add_url_rule('/'+endpoint,endpoint,lambda:'')
scope=dict(app=app,get_db=lambda:db,request=request,session=session,abort=abort,
    redirect=redirect,url_for=url_for,render_template=render_template,hmac=hmac,
    vibe_slug=lambda name:name.lower(),can_edit_vibe_settings=lambda uid,vibe:uid==1,
    default_vibe_css=lambda slug,mode:'default '+mode,theme_csrf_token=lambda:'fixture-token')
exec(compile(ast.Module(body=[route],type_ignores=[]),'actual edit_theme route','exec'),scope)
client=app.test_client()
with client.session_transaction() as s:s.update(user_id=1,theme_csrf_token='fixture-token')
checks=0
def check(ok,label):
    global checks
    assert ok,label
    checks+=1
def css(mode):return db.execute('SELECT custom_css FROM themes WHERE mode=?',(mode,)).fetchone()[0]
def post(mode,data):return client.post('/themes/edit/fixture/'+mode,data={'theme_csrf_token':'fixture-token',**data})
page=client.get('/themes/edit/fixture/day')
check(page.status_code==200,'Editor renders actual template')
check(b'Undo edit' in page.data and b'Discard unsaved changes' in page.data,'Distinct unsaved controls')
check(b'Restore day version 1' in page.data and b'Restore day version 2' not in page.data,'Only current mode history shown')
check(post('day',{'action':'restore:2'}).status_code==404,'Night version cannot restore into Day')
check(post('day',{'action':'restore:bad'}).status_code==400,'Malformed revision refused')
check(post('day',{'action':'restore:1','theme_csrf_token':'bad'}).status_code==400,'CSRF required')
check(css('day')=='original day' and css('night')=='original night','Rejected requests preserve both modes')
check(post('day',{'action':'restore:1'}).status_code==302,'Saved Day restoration')
check(css('day')=='older day' and css('night')=='original night','Day restoration leaves Night unchanged')
check(db.execute('SELECT bg_color FROM themes WHERE id=1').fetchone()[0] is None,'Null preserved on restore')
check(db.execute("SELECT COUNT(*) FROM theme_versions WHERE theme_id=1 AND custom_css='original day'").fetchone()[0]==1,'Replaced version retained')
check(db.execute('SELECT logo_url FROM vibes').fetchone()[0]=='/static/original.png','Restoration leaves shared identity unchanged')
page=client.get('/themes/edit/fixture/day?restored=1')
check(b'Saved day version restored' in page.data,'Restoration feedback')
check(post('night',{'action':'restore:2'}).status_code==302,'Night restoration succeeds')
check(css('day')=='older day' and css('night')=='older night','Night restoration leaves Day unchanged')
with client.session_transaction() as s:s['user_id']=2
check(post('day',{'action':'restore:1'}).status_code==403,'Editor permission enforced')
print(checks,'saved-theme restoration checks passed')

if os.environ.get('NEONREST_THEME_TEST_HTML'):
    Path(os.environ['NEONREST_THEME_TEST_HTML']).write_bytes(page.data)
