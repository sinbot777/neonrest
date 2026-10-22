from pathlib import Path
import os,sys,tempfile,sqlite3,importlib,contextlib,io,time,json

def _close_fixture_connections(directory):
    import gc, sqlite3
    gc.collect()
    for connection in gc.get_objects():
        if isinstance(connection, sqlite3.Connection):
            try:
                connection.close()
            except sqlite3.Error:
                pass
    gc.collect()
    directory.cleanup()

package=sys.argv[1];stage=Path(sys.argv[2]);_fixture_directory=tempfile.TemporaryDirectory(prefix='neonrest-statistics-test-');w=Path(_fixture_directory.name);import atexit,gc;atexit.register(_close_fixture_connections,_fixture_directory)
src=sqlite3.connect('file:/home/sinbot/db/'+package+'.db?mode=ro',uri=True);dst=sqlite3.connect(w/'fixture.db');src.backup(dst);src.close();dst.close()
with sqlite3.connect(w/'fixture.db') as before_db:initial_counts={r[0]:before_db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in before_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
prefix='NEONREST_PRODUCTION' if package=='neonrest' else 'NEONREST_SANDBOX'
for k,v in {'DATABASE':str(w/'fixture.db'),'SECRET_FILE':str(w/'secret'),'INSTANCE':str(w/'instance'),'MAIL_QUEUE_DIR':str(w/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[prefix+'_'+k]=v
os.environ['NEONREST_STATISTICS_DATABASE']=str(w/'statistics.sqlite')
sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
cf=importlib.import_module(package+'.community_features');tools=importlib.import_module(package+'.vibe_tools');life=importlib.import_module(package+'.utils.vibe_lifecycle');app=core.app;app.instance_path=str(w/'instance');app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/');core.mail.send=lambda x:(_ for _ in ()).throw(AssertionError('SMTP forbidden'))
mount='/sandbox' if package.endswith('sandbox') else '';env={'SCRIPT_NAME':mount};checks=0;now=int(time.time());token='fictional-vibe-management-csrf';clients={};users={}
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def query(sql,args=()):
 with app.app_context():return core.get_db().execute(sql,args).fetchall()
def change(sql,args=()):
 with app.app_context():db=core.get_db();r=db.execute(sql,args);db.commit();return r.lastrowid
check(all(query('SELECT COUNT(*) FROM "'+n+'"')[0][0]==v for n,v in initial_counts.items()),'Startup preserves existing table record counts')
with app.app_context():
 db=core.get_db();tools.initialize(db);tools.initialize(db);db.commit()
 # The copied owner row is replaced with a fictional identity before any session is created.
 db.execute("UPDATE users SET handle='@VMFixtureOwner',email='vm-owner@example.invalid',password_hash='!disabled-fixture',verified=1,bio='',avatar_path=NULL WHERE id=1")
 for table in ['staff_roles','vibe_editors','user_moderation','account_safety','account_disables','age_clocks','active_sessions']:
  db.execute('DELETE FROM '+table+' WHERE user_id=1')
 for key,dob in [('Owner','1990-01-01'),('Admin','1990-01-01'),('Moderator','1990-01-01'),('SiteManager','1990-01-01'),('Manager','1990-01-01'),('OtherManager','1990-01-01'),('Writer','1990-01-01'),('Regular','1990-01-01'),('Teen','2013-01-01'),('NoFactor','1990-01-01')]:
  uid=1 if key=='Owner' else db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)',('@VMFixture'+key,'vm-'+key.lower()+'@example.invalid','!disabled-fixture',dob)).lastrowid;users[key]=uid
  db.execute("INSERT OR REPLACE INTO age_clocks VALUES (?,'UTC',1)",(uid,));db.execute('INSERT OR REPLACE INTO account_safety(user_id,totp_secret) VALUES (?,?)',(uid,None if key=='NoFactor' else 'JBSWY3DPEHPK3PXP'))
  sid='fictional-vm-'+key;db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Vibe fixture'))
 for key,role in [('Admin','admin'),('Moderator','moderator'),('SiteManager','manager')]:db.execute('INSERT INTO staff_roles VALUES (?,?)',(users[key],role))
 vid=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture One')").lastrowid;other=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture Two')").lastrowid
 for key,cid in [('Manager',vid),('OtherManager',other),('NoFactor',vid)]:db.execute('INSERT INTO vibe_editors VALUES (?,?)',(cid,users[key]))
 db.commit()
for key,uid in users.items():
 client=app.test_client()
 with client.session_transaction() as s:s.update(user_id=uid,user_handle='@VMFixture'+key,user_email='vm-'+key.lower()+'@example.invalid',sid='fictional-vm-'+key,fresh_at=now,factor_at=now,theme_csrf_token=token)
 clients[key]=client
def get(key,path,**params):
 response=clients[key].get(path,query_string=params,environ_overrides=env)
 response.get_data();response.close();return response
def action(key,kind,cid=None,**data):return clients[key].post('/manage/vibes/'+str(cid or vid)+'/action',data={'action':kind,'theme_csrf_token':token,'reason':'PRACTICE ONLY: fictional test decision',**data},environ_overrides=env)
def post_fixture(text,audience='public',vibes=None):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',(pid,users['Writer'],text,'public'));core.identifiers.ensure(db,'post',pid);db.execute('INSERT OR REPLACE INTO post_privacy VALUES (?,?)',(pid,audience))
  for cid in vibes or [vid]:db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,cid))
  db.commit();return pid,core.identifiers.public(db,'post',pid)

import errno
from unittest.mock import patch
from PIL import Image
from html.parser import HTMLParser
appearance=importlib.import_module(package+'.circle_appearance')
circles=importlib.import_module(package+'.circles')
def send(key,path,**data):
 return clients[key].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def html(response):return response.get_data(as_text=True)
def anonymous_get(route):
 response=app.test_client().get(route,environ_overrides=env);response.get_data();response.close();return response
response=send('Regular','/circles',name='Appearance fixture',description='Fictional Circle for isolated tests',mode='hidden',rules='Be kind')
check(response.status_code==302,'Create isolated hidden Circle')
cid=query('SELECT max(id) FROM circles')[0][0]
with app.app_context():ref=circles.circle_ids.public(core.get_db(),cid)
path='/circles/'+ref
owner=users['Regular'];member=users['Writer'];moderator=users['Manager']
for uid,role in [(member,'member'),(moderator,'moderator')]:change("INSERT INTO circle_members VALUES (?,?,?,'active',CURRENT_TIMESTAMP)",(cid,uid,role))
def circle():return query('SELECT * FROM circles WHERE id=?',(cid,))[0]
check(circle()['appearance']==circle()['cover']==circle()['cover_alt']=='','Additive defaults are empty')
with app.app_context():appearance.initialize(core.get_db());appearance.initialize(core.get_db())
check(get('Regular',path).status_code==200,'Default Circle renders')
check(get('Regular',path+'/manage').status_code==200 and 'Save Circle theme' in html(get('Regular',path+'/manage')),'Owner theme and cover controls render')
check('Save Circle theme' not in html(get('Manager',path+'/manage')),'Moderator sees no owner appearance controls')
data={'action':'save_theme','font':'serif','corners':'8',**{mode+'_'+k:v for mode,colors in appearance.DEFAULTS.items() for k,v in colors.items()}}
for key in ['Writer','Manager','Owner','Teen']:
 check(send(key,path+'/appearance',**data).status_code in (403,404),'Nonowner cannot save theme '+key)
check(app.test_client().post(path+'/appearance',data=data,environ_overrides=env).status_code in (403,404),'Anonymous theme write denied')
check(clients['Regular'].post(path+'/appearance',data=data,environ_overrides=env).status_code==400,'Appearance requires CSRF')
check(clients['Regular'].post(path+'/appearance',data={**data,'theme_csrf_token':token},headers={'Origin':'https://foreign.example'},environ_overrides=env).status_code==403,'Cross-origin appearance write denied')
check(send('Regular',path+'/appearance',**data).status_code==302,'Owner saves theme')
check(json.loads(circle()['appearance'])['font']=='serif','Theme persists')
for mode in ['day','night']:
 page=html(get('Writer',path,appearance=mode))
 check('aria-label="Circle appearance"' in page,'Theme switch available '+mode)
 check('--circle-background:'+appearance.DEFAULTS[mode]['background'] in page and '--circle-font:Georgia,serif' in page,'Member renders selected '+mode+' palette')
 check('name="appearance" value="'+mode+'"' in page,'Search preserves '+mode+' theme')
check('--circle-background:'+appearance.DEFAULTS['night']['background'] in html(get('Writer',path,appearance='<bad>')),'Invalid viewing mode falls back safely')
saved=circle()['appearance']
for field,value in [('day_text','#ffffff'),('night_accent','#152136'),('font','serif;position:fixed'),('corners','9999'),('day_background','</style><script>alert(1)</script>'),('day_panel','url(https://evil.invalid)')]:
 check(send('Regular',path+'/appearance',**{**data,field:value}).status_code==400,'Unsafe or unreadable theme rejected '+field)
 check(circle()['appearance']==saved,'Rejected theme preserves saved values '+field)
check(send('Regular',path+'/appearance',action='reset_theme').status_code==302 and not circle()['appearance'],'Reset theme independently')
change("UPDATE circles SET appearance='not-json' WHERE id=?",(cid,))
check(get('Writer',path).status_code==200,'Malformed legacy theme falls back')
change("UPDATE circles SET appearance='' WHERE id=?",(cid,))
def image_bytes(size=(2000,900),format='PNG'):
 output=io.BytesIO();image=Image.new('RGB',size,'#aaccdd');exif=Image.Exif();exif[270]='PRIVATE CAMERA SENTINEL';image.save(output,format=format,exif=exif);return output.getvalue()
def cover(key='Regular',data=None,**fields):
 return send(key,path+'/appearance',action='save_cover',cover=(io.BytesIO(data if data is not None else image_bytes()),'photo.png'),cover_alt='Fictional mountain illustration',**fields)
check(cover().status_code==302,'Cover upload succeeds')
name=circle()['cover'];folder=Path(app.instance_path)/'circle_covers'
check(appearance.FILENAME.fullmatch(name),'Cover receives opaque generated filename')
with Image.open(folder/name) as uploaded:
 check(uploaded.width<=1600 and uploaded.height<=600,'Cover dimensions bounded')
 check(uploaded.format=='JPEG' and not uploaded.getexif(),'Re-encoding strips metadata')
check((folder/name).stat().st_size<100000,'Simple cover storage is compact')
response=get('Writer',path+'/cover')
check(response.status_code==200 and response.mimetype=='image/jpeg','Eligible member reads cover')
check(response.headers.get('Cache-Control')=='private, no-store' and response.headers.get('X-Content-Type-Options')=='nosniff','Cover does not enter shared caches')
check(get('Writer','/circles/'+str(cid)+'/cover').status_code==404,'New Circles have no numeric alias')
change('UPDATE circle_public_ids SET legacy_alias=? WHERE circle_id=?',(str(cid),cid))
check(get('Writer','/circles/'+str(cid)+'/cover').status_code==302,'Authorized legacy cover URL redirects to opaque URL')
check(get('Owner','/circles/'+str(cid)+'/cover').status_code==404,'Denied legacy cover URL does not reveal opaque URL')
for key in ['Owner','Teen']:
 check(get(key,path+'/cover').status_code==404,'Hidden cover denied to outsider '+key)
check(anonymous_get(path+'/cover').status_code==404,'Hidden cover denied to anonymous')
check(cover(key='Manager').status_code==403,'Moderator cannot replace cover')
for payload in [b'<svg><script/></svg>',b'not an image',b'X'*(5*1024*1024+1)]:
 check(cover(data=payload).status_code in (400,413),'Malformed or oversized upload rejected')
 check(circle()['cover']==name and (folder/name).exists(),'Rejected cover preserves old file')
check(cover(data=image_bytes((4001,4000))).status_code==400,'Excessive pixels rejected')
for alt in ['X'*201,'bad\ntext']:
 check(send('Regular',path+'/appearance',action='save_cover',cover_alt=alt).status_code==400,'Bad cover description rejected')
check(cover(remove_cover='1').status_code==400,'Remove and replace conflict rejected')
before=set(folder.iterdir());prepared_image=image_bytes()
with patch.object(appearance.Image.Image,'save',side_effect=OSError(errno.ENOSPC,'fixture full')):
 check(cover(data=prepared_image).status_code==507,'Full storage returns recoverable 507')
check(circle()['cover']==name and set(folder.iterdir())==before,'Failed image write preserves cover without orphan')
original_get_db=core.get_db
class FailingCommit:
 def __init__(self,db):self.db=db;self.changed=False
 def __getattr__(self,name):return getattr(self.db,name)
 def execute(self,sql,*args):
  if sql.startswith('UPDATE circles SET cover='):self.changed=True
  return self.db.execute(sql,*args)
 def commit(self):
  if self.changed:raise sqlite3.OperationalError('database or disk is full')
  return self.db.commit()
proxies={}
def failed_connection():
 db=original_get_db()
 return proxies.setdefault(id(db),FailingCommit(db))
with patch.object(core,'get_db',failed_connection):
 check(cover().status_code==507,'Full database at commit returns 507')
check(circle()['cover']==name and set(folder.iterdir())==before,'Failed database commit removes new file and preserves old cover')
check(cover(data=image_bytes((500,200),'JPEG')).status_code==302,'JPEG replacement succeeds')
replacement=circle()['cover']
check(replacement!=name and not (folder/name).exists() and len(list(folder.iterdir()))==1,'Replacement retires only superseded cover')
check(send('Regular',path+'/appearance',action='save_cover',cover_alt='<script>description</script>').status_code==302,'Description update without replacement')
check('&lt;script&gt;description&lt;/script&gt;' in html(get('Writer',path)) and '<script>description</script>' not in html(get('Writer',path)),'Cover description is escaped')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(owner,member))
check(get('Writer',path+'/cover').status_code==404,'Block revokes cover access')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(owner,member))
change("UPDATE circle_members SET status='removed' WHERE circle_id=? AND user_id=?",(cid,member))
check(get('Writer',path+'/cover').status_code==404,'Membership removal revokes hidden cover')
change("UPDATE circle_members SET status='active' WHERE circle_id=? AND user_id=?",(cid,member))
change('UPDATE circles SET archived=1 WHERE id=?',(cid,))
check(get('Regular',path+'/cover').status_code==404,'Archived cover is inaccessible')
change('UPDATE circles SET archived=0,mode=\'discoverable\',public_read=1 WHERE id=?',(cid,))
check(anonymous_get(path+'/cover').status_code==200,'Public Circle cover is public through current eligibility guard')
change('UPDATE circles SET public_read=0 WHERE id=?',(cid,))
check(anonymous_get(path+'/cover').status_code==404,'Public viewing disabled revokes anonymous cover')
check(send('Regular',path+'/appearance',action='save_cover',remove_cover='1').status_code==302,'Owner removes cover')
check(not circle()['cover'] and not circle()['cover_alt'] and not list(folder.iterdir()),'Remove clears reference, description and own file')
check(get('Regular',path+'/cover').status_code==404,'Absent cover returns 404')
change("UPDATE circles SET cover='../secret' WHERE id=?",(cid,))
check(get('Regular',path+'/cover').status_code==404,'Corrupt filename cannot traverse directories')
change('UPDATE circles SET cover=? WHERE id=?',('a'*48+'.jpg',cid))
check(get('Regular',path+'/cover').status_code==404,'Missing file returns 404 without crash')
change("UPDATE circles SET cover='' WHERE id=?",(cid,))

# Representative real template renders: no live account, post or route is created.
class Markup(HTMLParser):
 def __init__(self):super().__init__();self.tags=[];self.labels=set();self.label_depth=0;self.fields=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs);self.tags.append((tag,attrs))
  if tag=='label':
   self.label_depth+=1
   if attrs.get('for'):self.labels.add(attrs['for'])
  if tag in ('input','select','textarea') and attrs.get('type') not in ('hidden','submit','button'):self.fields.append((attrs,bool(self.label_depth)))
 def handle_endtag(self,tag):
  if tag=='label':self.label_depth=max(0,self.label_depth-1)
for key,route in [('Regular','/feed'),('Regular','/account'),('Regular','/account/feed'),('Regular','/drafts'),('Regular','/create_post'),('Writer','/@VMFixtureWriter'),('Writer',path),('Regular',path+'/manage'),('Regular','/circles'),('Regular','/notifications'),('Regular','/guide')]:
 response=get(key,route)
 if route=='/guide' and response.status_code==404:continue
 check(response.status_code==200,'Accessible page renders '+route)
 markup=Markup();markup.feed(html(response));tags=markup.tags
 check(any(t=='a' and a.get('class')=='skip-link' and a.get('href')=='#main-content' for t,a in tags),'Skip navigation '+route)
 check(any(a.get('id')=='main-content' and a.get('tabindex')=='-1' for t,a in tags),'Focus destination '+route)
 check(sum(a.get('id')=='main-content' for t,a in tags)==1,'Unique skip destination '+route)
 check(any(t=='script' and 'accessibility.js' in a.get('src','') for t,a in tags),'Keyboard and motion controller '+route)
 check(all(wrapped or a.get('aria-label') or a.get('aria-labelledby') or a.get('id') in markup.labels for a,wrapped in markup.fields),'All form fields have names '+route)
 for tag,attrs in tags:
  if tag=='button' and attrs.get('class')=='icon-button':
   check(bool(attrs.get('aria-label')),'Named icon control '+route)
   if 'Menu(' in attrs.get('onclick',''):check(attrs.get('aria-expanded') in ('true','false'),'Disclosure expansion state '+route)
check('setTimeout' not in (stage/'templates/base.html').read_text(),'Flash messages remain available')
check('prefers-reduced-motion' in (stage/'static/css/accessibility.css').read_text(),'Reduced motion styles included')
check('forced-colors' in (stage/'static/css/accessibility.css').read_text(),'Forced colors styles included')
if os.environ.get('NEONREST_UI_FIXTURE_DIR'):
 import shutil
 destination=Path(os.environ['NEONREST_UI_FIXTURE_DIR']);destination.mkdir(parents=True,exist_ok=True)
 # These files contain only this fictional Circle and fictional members.
 pid,public=post_fixture('A fictional keyboard test post. '+('Longword'*20))
 change('INSERT INTO circle_posts VALUES (?,?)',(pid,cid))
 comment=change('INSERT INTO comments(user_id,post_id,content) VALUES (?,?,?)',(member,pid,'A fictional comment for keyboard editing.'))
 with app.app_context():core.identifiers.ensure(core.get_db(),'comment',comment);core.get_db().commit()
 check(cover(data=prepared_image).status_code==302,'Visual fixture cover')
 cover_response=get('Writer',path+'/cover');(destination/'cover.jpg').write_bytes(cover_response.data)
 base_url=mount+'/static/'+destination.name+'/'
 for name,key,route,params in [('night','Writer',path,{}),('day','Writer',path,{'appearance':'day'}),('manage','Regular',path+'/manage',{}),('profile','Writer','/@VMFixtureWriter',{}),('composer','Writer','/create_post',{}),('account','Writer','/account',{}),('guide','Writer','/guide',{})]:
  content=html(get(key,route,**params))
  content=content.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="connect-src \'none\'; form-action \'none\'; frame-src \'self\'">')
  for asset in ['css/accessibility.css','js/accessibility.js','css/circle-appearance.css']:
   content=content.replace(mount+'/static/'+asset,base_url+asset)
  content=content.replace(mount+path+'/cover',base_url+'cover.jpg')
  (destination/(name+'.html')).write_text(content)
 for asset in ['css/accessibility.css','js/accessibility.js','css/circle-appearance.css']:
  target=destination/asset;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stage/'static'/asset,target)
 parts=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Fictional Circle responsive review</title><body style="margin:0;background:#17263b;color:white;font-family:system-ui"><h1>Isolated fictional Circle review</h1><p>Forms and network writes are blocked. No live account or post is used.</p>']
 for name,width in [('night',320),('day',390),('manage',768),('night',1280)]:parts.append('<h2>'+name+' at '+str(width)+' px</h2><iframe id="qa-'+str(width)+'" title="'+name+' '+str(width)+' pixels" src="'+name+'.html" width="'+str(width)+'" height="1000" style="border:0"></iframe>')
 for name in ['profile','composer','account','guide']:
  for width in [320,768,1280]:parts.append('<h2>'+name+' at '+str(width)+' px</h2><iframe id="qa-'+name+'-'+str(width)+'" title="'+name+' '+str(width)+' pixels" src="'+name+'.html" width="'+str(width)+'" height="1000" style="border:0"></iframe>')
 parts.append('</body></html>');(destination/'index.html').write_text(''.join(parts))
 print('FICTIONAL_UI_REVIEW',base_url+'index.html')
check(query('PRAGMA integrity_check')[0][0]=='ok','Fixture database integrity')
print('CIRCLE_APPEARANCE_AND_ACCESSIBILITY_CHECKS',checks)
