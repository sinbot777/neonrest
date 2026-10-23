"""Fictional routes/files; real MIDI/image validation and atomic save cleanup."""
import importlib.util
import io
import json
import os
import sqlite3
import struct
import sys
import tempfile
import types
from pathlib import Path
from flask import Flask, session, abort, render_template, render_template_string, redirect
from jinja2 import DictLoader
from PIL import Image

root=Path(__file__).resolve().parents[1]
pkg=types.ModuleType('atmosphere_fixture');pkg.__path__=[str(root)];sys.modules[pkg.__name__]=pkg
tools=types.ModuleType('atmosphere_fixture.vibe_tools')
def find(db,slug):
    row=db.execute('SELECT * FROM vibes WHERE name=?',(slug.title(),)).fetchone()
    if not row:abort(404)
    return row
tools.find_vibe=find;tools.permissions=lambda core,db,uid,vid:{'settings':uid==1 and vid==1}
sys.modules[tools.__name__]=tools
spec=importlib.util.spec_from_file_location('atmosphere_fixture.vibe_atmosphere',root/'vibe_atmosphere.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
sys.modules[spec.name]=mod
tmp=tempfile.TemporaryDirectory();scratch=Path(tmp.name)
static=scratch/'static';static.mkdir();(static/'optimized').mkdir()
Image.new('RGB',(2,2),'red').save(static/'optimized/day.png')
Image.new('RGB',(2,2),'blue').save(static/'optimized/night.webp')
Image.new('RGB',(2,2),'red').save(static/'animated.webp',save_all=True,append_images=[Image.new('RGB',(2,2),'blue')],duration=100,loop=0)
(static/'not-image.png').write_text('<svg>bad</svg>')
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY);INSERT INTO users VALUES(1),(2);
CREATE TABLE vibes(id INTEGER PRIMARY KEY,name TEXT,logo_url TEXT,logo_width TEXT,logo_height TEXT,logo_padding TEXT,logo_align TEXT);
INSERT INTO vibes VALUES(1,'Fixture','legacy.png',NULL,NULL,NULL,'center'),(2,'Pending',NULL,NULL,NULL,NULL,'center'),(3,'Archived',NULL,NULL,NULL,NULL,'center');
CREATE TABLE pending_vibes(vibe_id INTEGER);INSERT INTO pending_vibes VALUES(2);
CREATE TABLE vibe_management(vibe_id INTEGER,archived INTEGER);INSERT INTO vibe_management VALUES(3,1);''')
app=Flask(__name__,instance_path=str(scratch/'instance'),static_folder=str(static));app.secret_key='fictional-atmosphere'
app.testing=True
app.jinja_loader=DictLoader({'base.html':'{% block content %}{% endblock %}',**{str(p.relative_to(root/'templates')):p.read_text() for p in (root/'templates').rglob('*.html') if p.name!='base.html'}})
app.add_url_rule('/media-file/<filename>','media_file',lambda filename:'')
app.add_url_rule('/media-settings','media_settings',lambda:'')
app.add_url_rule('/themes/edit/<slug>/<mode>','edit_theme',lambda slug,mode:'')
class Core:
    get_db=staticmethod(lambda:db)
    theme_csrf_token=staticmethod(lambda:session.setdefault('theme_csrf_token','fixture-token'))
mod.register(app,Core)
client=app.test_client();checks=0
def check(ok,label):
    global checks
    assert ok,label
    checks+=1
def login(uid):
    with client.session_transaction() as s:s.clear();s.update(user_id=uid,theme_csrf_token='fixture-token')
track=bytes([0,0x90,60,64,96,0x80,60,64,0,0xff,0x2f,0])
midi=b'MThd'+struct.pack('>IHHH',6,0,1,96)+b'MTrk'+struct.pack('>I',len(track))+track
def save(**changes):
    form={'theme_csrf_token':'fixture-token','revision':'0','day_logo':'optimized/day.png','night_logo':'/static/optimized/night.webp','logo_motion':'float','midi_title':'Fixture music',**changes}
    return client.post('/manage/vibes/fixture/atmosphere',data=form)
def upload(data=midi):return (io.BytesIO(data),'fixture.mid')
check(client.get('/manage/vibes/fixture/atmosphere').status_code==403,'Anonymous editor denied')
login(2);check(save().status_code==403,'Unassigned account denied')
login(1)
check(client.get('/manage/vibes/fixture/atmosphere').status_code==200,'Scoped editor renders')
check(save(theme_csrf_token='ñ').status_code==400,'Non-ASCII CSRF fails safely')
check(save(day_logo='../private.png').status_code==400,'Traversal refused')
check(save(day_logo='/etc/passwd').status_code==400,'Absolute path refused')
Image.new('RGB',(2,2)).save(scratch/'outside.png')
(static/'escape.png').symlink_to(scratch/'outside.png')
check(save(day_logo='escape.png').status_code==400,'Symlink outside static refused')
check(save(day_logo='https://example.invalid/logo.png').status_code==400,'Remote logo refused')
check(save(day_logo='animated.webp').status_code==400,'Animated image variant refused')
check(save(day_logo='not-image.png').status_code==400,'Invalid image refused')
check(save(logo_motion='flash').status_code==400,'Unlisted motion refused')
check(save(background_midi=upload(b'bad')).status_code==400,'Malformed MIDI refused')
check(save(background_midi=upload(b'x'*(mod.MIDI_LIMIT+1))).status_code==413,'MIDI size bound')
check(save(background_midi=upload()).status_code==302,'Valid logo variants and own MIDI saved')
row=mod.settings(db,1);filename=row['midi_filename'];media=scratch/'instance/media'
check(row['day_logo']=='optimized/day.png' and row['night_logo']=='optimized/night.webp','Variant paths normalized')
check(row['revision']==1 and row['updated_by']==1,'Revision/editor recorded')
check((media/filename).read_bytes()==midi,'Only validated new Vibe-owned bytes stored')
check(client.get('/vibe-atmosphere/1/music/'+filename).status_code==200,'Approved active Vibe track served')
check(client.get('/vibe-atmosphere/2/music/'+filename).status_code==404,'Other/pending Vibe cannot borrow file')
check(client.get('/vibe-atmosphere/3/music/'+filename).status_code==404,'Archived Vibe does not expose track')
private='c'*40+'.mid';(media/private).write_bytes(midi)
check(client.get('/vibe-atmosphere/1/music/'+private).status_code==404,'Private/unlinked file never exposed by Vibe route')
check(client.get('/vibe-atmosphere/1/music/bad.mid').status_code==404,'Invalid filename refused')
before={p.name for p in media.iterdir()}
check(save(background_midi=upload()).status_code==409,'Stale revision refused')
check({p.name for p in media.iterdir()}==before,'Stale save writes no orphan upload')
class FailingDB:
    def execute(self,sql,*args):
        if sql.startswith('INSERT INTO vibe_atmosphere'):raise sqlite3.OperationalError('fictional write failure')
        return db.execute(sql,*args)
    def rollback(self):db.rollback()
Core.get_db=staticmethod(lambda:FailingDB())
try:save(revision='1',background_midi=upload())
except sqlite3.OperationalError:pass
else:raise AssertionError('Expected fixture failure')
Core.get_db=staticmethod(lambda:db)
check({p.name for p in media.iterdir()}==before and mod.settings(db,1)['midi_filename']==filename,'Failed DB write removes own new file and preserves previous track')
from unittest.mock import patch
import errno
original_open=Path.open
class PartialWriter:
    def __init__(self,handle):self.handle=handle
    def __enter__(self):return self
    def __exit__(self,*args):self.handle.close()
    def write(self,data):
        self.handle.write(data[:4])
        raise OSError(errno.ENOSPC,'Fictional storage full')
def failing_open(path,mode='r',*args,**kwargs):
    handle=original_open(path,mode,*args,**kwargs)
    return PartialWriter(handle) if mode=='xb' and path.suffix=='.mid' else handle
with patch.object(Path,'open',failing_open):
    try:save(revision='1',background_midi=upload())
    except OSError as error:check(error.errno==errno.ENOSPC,'Storage failure propagated')
    else:raise AssertionError('Expected fictional storage failure')
check({p.name for p in media.iterdir()}==before and mod.settings(db,1)['revision']==1,'Partial file cleaned after storage failure; old revision preserved')
original_rng=mod.secrets.token_hex
mod.secrets.token_hex=lambda size:filename[:-4]
try:save(revision='1',background_midi=upload())
except FileExistsError:pass
else:raise AssertionError('Expected exclusive-create collision')
mod.secrets.token_hex=original_rng
check((media/filename).read_bytes()==midi,'Filename collision cannot remove an existing track')
db.execute('INSERT INTO pending_vibes VALUES(1)');db.commit()
check(client.get('/vibe-atmosphere/1/music/'+filename).status_code==404,'Pending state checked on every media request')
db.execute('DELETE FROM pending_vibes WHERE vibe_id=1');db.execute('INSERT INTO vibe_management VALUES(1,1)');db.commit()
check(client.get('/vibe-atmosphere/1/music/'+filename).status_code==404,'Archive checked on every media request')
db.execute('DELETE FROM vibe_management WHERE vibe_id=1');db.commit()
check(save(revision='1',remove_midi='yes').status_code==302,'Remove track reference')
check(client.get('/vibe-atmosphere/1/music/'+filename).status_code==404 and (media/filename).exists(),'Unlinked track inaccessible, old bytes retained for reviewed retention')
check(save(revision='2',remove_midi='yes',background_midi=upload(),midi_title='Replacement music').status_code==302 and mod.settings(db,1)['midi_title']=='Replacement music','Replacement upload takes priority and retains its title')
check(save(revision='3',midi_filename=private).status_code==302 and mod.settings(db,1)['midi_filename']!=private,'Forged private filename cannot be linked through form fields')
check(client.post('/atmosphere-preferences',data={'theme_csrf_token':'fixture-token','logo_motion':'off'}).status_code==302,'Visitor motion preference saved')
check(mod.export_user(db,1)['preferences']=={'logo_motion':'off'},'Own motion preference exported')
check(mod.export_user(db,2)['vibe_settings_last_saved_by_you']==[],'Other account export isolated')
check(client.post('/atmosphere-preferences',data={'theme_csrf_token':'fixture-token','logo_motion':'bad'}).status_code==400,'Invalid motion preference refused')
check(client.post('/atmosphere-preferences',data={'theme_csrf_token':'bad','logo_motion':'system'}).status_code==400,'Motion preference CSRF')
login(None);check(client.post('/atmosphere-preferences',data={'theme_csrf_token':'fixture-token','logo_motion':'off'}).status_code==403,'Anonymous preference write refused')
with app.test_request_context('/'):
    context={}
    for function in app.template_context_processors[None]:context.update(function())
    appearance=context['vibe_atmosphere'](1,'day');check(appearance['logo']=='optimized/day.png','Day variant selected')
    check(context['vibe_atmosphere'](1,'night')['logo']=='optimized/night.webp','Night variant selected')
    fallback=render_template('partials/vibe_atmosphere_logo.html',vibe={'name':'Fixture','logo_url':'/static/legacy.png'},atmosphere={'logo':None,'logo_motion':'none'})
    check('src="/static/legacy.png"' in fallback,'Shared static logo fallback normalizes existing URL')
    html=render_template('partials/vibe_atmosphere_logo.html',vibe=db.execute('SELECT * FROM vibes WHERE id=1').fetchone(),atmosphere=appearance)
    check('Pause logo animation' in html and 'optimized/day.png' in html,'Actual logo widget renders variant and control')
    player=render_template('midi_player.html',midi_src='/vibe-atmosphere/1/music/'+filename,midi_title='Fixture music')
    check('midi-play' in player and 'autoplay' not in player,'Reuse existing click-to-play MIDI controls')
    mixed=render_template_string("{% include 'partials/vibe_background_midi.html' %}{% set midi_title='Post music' %}{% set midi_filename='private-post.mid' %}{% include 'midi_player.html' %}",vibe={'id':1},atmosphere=mod.settings(db,1))
    check('data-midi-src="/media-file/private-post.mid"' in mixed and 'data-midi-src="/vibe-atmosphere/1/music/' in mixed,'Background MIDI binding cannot replace a later post attachment URL')
    if os.environ.get('NEONREST_ATMOSPHERE_HTML'):Path(os.environ['NEONREST_ATMOSPHERE_HTML']).write_text(html+player)
    if os.environ.get('NEONREST_ATMOSPHERE_MIDI'):Path(os.environ['NEONREST_ATMOSPHERE_MIDI']).write_bytes(midi)
mod.initialize(db)
check(db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==2,'Initialization preserves existing accounts')
# Execute the real account-export hook with unrelated feature exports stubbed.
import ast,time
from flask import Response
node=next(n for n in ast.walk(ast.parse((root/'community_features.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name=='community_export')
for name,fn in [('theme_gallery',lambda db,uid:{}),('social_connections',lambda db,uid:{}),('reading_tools',lambda db,uid,ids:{})]:
    stub=types.ModuleType('atmosphere_fixture.'+name);stub.export_user=fn;sys.modules[stub.__name__]=stub
export_app=Flask('atmosphere-export');export_app.secret_key='fixture-export'
Core.identifiers=types.SimpleNamespace(export_ids=lambda db,data:None)
namespace=dict(app=export_app,core=Core,get_db=lambda:db,current_user=lambda:db.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone(),csrf=lambda:None,fresh=lambda:True,session=session,redirect=redirect,url_for=lambda *a,**k:'/',time=time,json=json,Response=Response,__package__='atmosphere_fixture')
exec(compile(ast.Module(body=[node],type_ignores=[]),'actual account export','exec'),namespace)
export_client=export_app.test_client()
with export_client.session_transaction() as sess:sess['user_id']=1
check(export_client.post('/account/export').json['vibe_atmosphere']['preferences']=={'logo_motion':'off'},'Actual account export includes own motion preference')
with export_client.session_transaction() as sess:sess['user_id']=2
check(export_client.post('/account/export').json['vibe_atmosphere']['vibe_settings_last_saved_by_you']==[],'Actual account export excludes another editor settings')
tmp.cleanup()
print(checks,'Vibe atmosphere validation/access/rollback/preference checks passed')
