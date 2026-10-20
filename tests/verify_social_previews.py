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
def get(key,path,**params):return clients[key].get(path,query_string=params,environ_overrides=env)
def action(key,kind,cid=None,**data):return clients[key].post('/manage/vibes/'+str(cid or vid)+'/action',data={'action':kind,'theme_csrf_token':token,'reason':'PRACTICE ONLY: fictional test decision',**data},environ_overrides=env)
def post_fixture(text,audience='public',vibes=None):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',(pid,users['Writer'],text,'public'));core.identifiers.ensure(db,'post',pid);db.execute('INSERT OR REPLACE INTO post_privacy VALUES (?,?)',(pid,audience))
  for cid in vibes or [vid]:db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,cid))
  db.commit();return pid,core.identifiers.public(db,'post',pid)


from datetime import datetime,timedelta,timezone
stats=importlib.import_module(package+'.site_statistics');detail=importlib.import_module(package+'.statistics_detail');verification=importlib.import_module(package+'.email_verification');circlemod=importlib.import_module(package+'.circles');circleids=importlib.import_module(package+'.circle_ids');circlenames=importlib.import_module(package+'.circle_names')
path=app.extensions['site_statistics']['path'];check(str(path).startswith(str(w)),'Isolated sidecar')
today=datetime.now(timezone.utc).date();day=today.isoformat();headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36'}
def raw():
 with sqlite3.connect(path) as db:return db.execute('SELECT bucket,segment,kind,label,detail,value FROM hourly_counters ORDER BY bucket,segment,kind,label,detail').fetchall()
def reset():
 with sqlite3.connect(path) as db:db.execute('DELETE FROM hourly_counters');db.execute('DELETE FROM counters');db.execute("UPDATE metadata SET value='0' WHERE key='detail_capacity_skips'")
def count(kind,label=None,segment=None):return sum(r[5] for r in raw() if r[2]==kind and (label is None or r[3]==label) and (segment is None or r[1]==segment))
def visit(route='/',client=None,extra=None):return (client or app.test_client()).get(route,headers={**headers,**(extra or {})},environ_overrides=env)
def report(traffic='ordinary',days='7',**values):
 with app.test_request_context('/manage/statistics',query_string={'traffic':traffic,'days':days,**values},environ_overrides=env):return detail.build_report(core,path,detail.options())
social=importlib.import_module(package+'.social_previews')
from html.parser import HTMLParser
from urllib.parse import urlsplit
from PIL import Image
class Meta(HTMLParser):
 def __init__(self,text):
  super().__init__();self.tags={};self.feed(text)
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='meta':self.tags[a.get('property') or a.get('name')]=a.get('content')
def metadata(response):return Meta(response.data.decode()).tags
def data_for(pid):
 with app.test_request_context('/',environ_overrides=env):return social.descriptor(core.get_db(),pid)
def makepost(text='Fictional public preview text',who='Writer',audience='public'):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',(pid,users[who],text,'public'));token_id=core.identifiers.ensure(db,'post',pid);db.execute('INSERT INTO post_privacy VALUES (?,?)',(pid,audience));db.commit();return pid,token_id
def image_request(meta,client=None,**extra):
 return visit(urlsplit(meta['og:image']).path.removeprefix(mount) if mount else urlsplit(meta['og:image']).path,client=client,extra=extra)
def verify_png(response,label):
 check(response.status_code==200 and response.mimetype=='image/png',label+' response')
 with Image.open(io.BytesIO(response.data)) as image:check(image.size==(1200,630),label+' dimensions')
 check('no-store' in response.headers.get('Cache-Control','') and response.headers.get('X-Content-Type-Options')=='nosniff',label+' cache and content protection')
public_pid,public_token=makepost('**Public milestone** & "quoted" text. [Link](https://example.invalid/secret-url)')
r=visit('/posts/'+public_token);m=metadata(r)
check(r.status_code==200 and m['og:type']=='article','Public post metadata')
check(m['og:title']=='A post by @VMFixtureWriter on Neonrest','Public author handle only')
check('Public milestone' in m['og:description'] and 'secret-url' not in m['og:description'],'Plain excerpt without Markdown destination')
check(m['og:url']=='https://www.neonrest.com'+mount+'/posts/'+public_token,'Canonical post URL and environment')
check(m['og:image'].startswith('https://www.neonrest.com'+mount+'/social-preview/posts/'),'Absolute same-site image URL')
check(m['og:image:width']=='1200' and m['og:image:height']=='630' and m['og:image:alt'],'Explicit image dimensions and alt')
check(m['twitter:card']=='summary_large_image' and m['twitter:image']==m['og:image'],'Social card fallback tags')
verify_png(image_request(m),'Text preview')
check(metadata(visit('/posts/'+public_token,client=clients['Teen']))['og:type']=='website','Age-band denied reader gets no adult post metadata')
check(image_request(m,client=clients['Teen']).status_code==404,'Age-band denied reader cannot use public image endpoint')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],users['Writer']))
check(metadata(visit('/posts/'+public_token,client=clients['Regular']))['og:type']=='website' and image_request(m,client=clients['Regular']).status_code==404,'Blocked reader cannot bypass visibility through preview')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Regular'],users['Writer']))
before_bytes=image_request(m).data
check(metadata(visit('/posts/'+public_token,extra={'Host':'attacker.example'}))['og:url']==m['og:url'],'Host header cannot poison canonical URLs')
for kind,audience in [('friends','friends'),('private','private')]:
 pid,tok=makepost('PRIVATE-'+kind,audience=audience)
 r=visit('/posts/'+tok);check(r.status_code==404 and metadata(r)['og:type']=='website','Guest private metadata '+kind)
 r=visit('/posts/'+tok,client=clients['Writer']);check(r.status_code==200 and metadata(r)['og:type']=='website' and 'PRIVATE-'+kind not in metadata(r)['og:description'],'Owner cannot expose private metadata '+kind)
 check(data_for(pid) is None,'Private descriptor denied '+kind)
pid,tok=makepost('AGE-PROTECTED-SECRET');change('INSERT INTO protected_age_posts VALUES (?)',(pid,));check(data_for(pid) is None,'Protected original-age post denied')
check(metadata(visit('/posts/'+tok,client=clients['Owner']))['og:type']=='website','Staff cannot expose age-protected preview')
pid,tok=makepost('TEEN-SECRET',who='Teen');check(data_for(pid) is None,'Minor author denied')
old=m;change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(public_pid,));check(image_request(old).status_code==404,'Already-known image URL revoked when private')
check(image_request(old,client=clients['Owner']).status_code==404,'Owner cannot retrieve private preview image')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(public_pid,));change("UPDATE posts SET content='Changed public excerpt',last_edited=CURRENT_TIMESTAMP WHERE id=?",(public_pid,));new=metadata(visit('/posts/'+public_token));check(new['og:image']!=old['og:image'] and image_request(old).status_code==404,'Edit rotates image revision and rejects stale URL');verify_png(image_request(new),'Edited preview')
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(public_pid,users['Writer'],users['Owner'],'Fictional moderation test'));check(image_request(new).status_code==404 and data_for(public_pid) is None,'Moderation revokes image');change('DELETE FROM moderated_posts WHERE post_id=?',(public_pid,))
change("INSERT INTO account_disables(user_id,disabled,reason) VALUES (?,1,'Fictional disable')",(users['Writer'],));check(data_for(public_pid) is None,'Disabled author denied');change('DELETE FROM account_disables WHERE user_id=?',(users['Writer'],))
change('UPDATE account_safety SET inactive=1 WHERE user_id=?',(users['Writer'],));check(data_for(public_pid) is None,'Hidden account denied');change('UPDATE account_safety SET inactive=0 WHERE user_id=?',(users['Writer'],))
# Public Circle mode and each post's visibility both apply.
with app.app_context():
 db=core.get_db();cid=db.execute("INSERT INTO circles(name,owner_id,mode,public_read) VALUES ('Fictional Social Circle',?,'discoverable',1)",(users['Writer'],)).lastrowid;circleids.ensure(db,cid);circlenames.assign(db,cid,'Fictional Social Circle');db.execute("INSERT INTO circle_members VALUES (?,?,'owner','active',CURRENT_TIMESTAMP)",(cid,users['Writer']));db.commit()
cpid,ctok=makepost('Public Circle excerpt',audience='private');change('INSERT INTO circle_posts VALUES (?,?)',(cpid,cid));change("INSERT INTO circle_post_visibility VALUES (?,'public')",(cpid,))
cm=metadata(visit('/posts/'+ctok));check(cm['og:type']=='article' and 'Public Circle excerpt' in cm['og:description'],'Public Circle public post allowed');verify_png(image_request(cm),'Public Circle preview')
change("UPDATE circle_post_visibility SET audience='private' WHERE post_id=?",(cpid,));check(image_request(cm).status_code==404 and data_for(cpid) is None,'Private post in Public Circle denied')
change('INSERT INTO post_share_permissions VALUES (?,1)',(cpid,));check(data_for(cpid) is None,'External-share option does not publicize original private Circle post')
change("UPDATE circle_post_visibility SET audience='public' WHERE post_id=?",(cpid,))
for sql,label in [("UPDATE circles SET public_read=0 WHERE id=?",'Members-only Circle'),("UPDATE circles SET public_read=1,mode='hidden' WHERE id=?",'Hidden Circle'),("UPDATE circles SET mode='discoverable',archived=1 WHERE id=?",'Archived Circle')]:
 change(sql,(cid,));check(data_for(cpid) is None and image_request(cm).status_code==404,label+' denied')
change('UPDATE circles SET archived=0 WHERE id=?',(cid,));change("INSERT INTO circle_content_removals(circle_id,target_type,target_id,report_id,removed_by) VALUES (?,'post',?,0,?)",(cid,cpid,users['Owner']));check(data_for(cpid) is None,'Circle moderation removal denied');change('DELETE FROM circle_content_removals WHERE target_id=?',(cpid,))
# Controlled attachments: photo, GIF poster, corrupted/missing files and legacy uploads.
photo_pid,photo_token=makepost('Photo preview');filename='a'*40+'.png'
with app.app_context():
 folder=social.media_folder();Image.new('RGB',(900,300),'#fa4020').save(folder/filename)
change("INSERT INTO post_media(post_id,kind,filename,alt_text) VALUES (?,'image',?,'Fictional red photo')",(photo_pid,filename))
pm=metadata(visit('/posts/'+photo_token));pr=image_request(pm);verify_png(pr,'Photo preview')
with Image.open(io.BytesIO(pr.data)) as image:check(image.getpixel((600,300))==(250,64,32),'Actual uploaded image used')
check(pm['og:image:alt']=='Fictional red photo','Public attachment alt text')
with app.app_context():
 folder=social.media_folder();(folder/filename).write_bytes(b'invalid image')
verify_png(image_request(pm),'Corrupt image fallback')
with app.app_context():
 Image.new('RGB',(20,20),'red').save(social.media_folder()/filename,format='BMP')
 check(social.image_attachment(data_for(photo_pid)['media']) is None,'Unsupported image decoder never used')
change('DELETE FROM post_media WHERE post_id=?',(photo_pid,));gname='b'*40+'.gif';poster='c'*40+'.jpg'
with app.app_context():
 Image.new('RGB',(400,200),'#20a040').save(social.media_folder()/poster)
change("INSERT INTO post_media(post_id,kind,filename,poster,loop_filename) VALUES (?,'gif',?,?,?)",(photo_pid,gname,poster,gname));gm=metadata(visit('/posts/'+photo_token));verify_png(image_request(gm),'GIF poster preview')
change('UPDATE post_media SET poster=? WHERE post_id=?',('../../private.png',photo_pid));verify_png(image_request(metadata(visit('/posts/'+photo_token))),'Traversal name falls back to text')
legacy='d'*32+'.jpg';lpid,ltok=makepost('Legacy ![photo]('+mount+'/static/uploads/posts/'+legacy+')')
with app.app_context():
 legacy_folder=Path(app.static_folder)/'uploads/posts';legacy_folder.mkdir(parents=True,exist_ok=True);Image.new('RGB',(600,400),'#20a0d0').save(legacy_folder/legacy)
lm=metadata(visit('/posts/'+ltok));verify_png(image_request(lm),'Legacy local image')
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(lpid,));check(image_request(lm).status_code==404,'Legacy preview privacy revocation')
epid,etok=makepost('![external](https://example.invalid/DO-NOT-FETCH.png)');em=metadata(visit('/posts/'+etok));check(data_for(epid)['media'] is None,'External images never fetched');verify_png(image_request(em),'External image text-only fallback')
wrap_pid,wrap_token=makepost('');change('INSERT INTO post_shares(share_post_id,source_post_id) VALUES (?,?)',(wrap_pid,cpid));change("UPDATE circle_post_visibility SET audience='private' WHERE post_id=?",(cpid,));wm=metadata(visit('/posts/'+wrap_token));check('Public Circle excerpt' not in wm['og:description'],'Private share source never copied to metadata')
change("UPDATE circle_post_visibility SET audience='public' WHERE post_id=?",(cpid,));wm=metadata(visit('/posts/'+wrap_token));check('Public Circle excerpt' in wm['og:description'],'Public share source may be previewed');change("UPDATE circle_post_visibility SET audience='private' WHERE post_id=?",(cpid,));check(image_request(wm).status_code==404,'Shared source privacy change revokes old preview')
badpid,badtok=makepost('Text with "quotes" <script>alert(1)</script> & characters');bm=metadata(visit('/posts/'+badtok));check('"quotes"' in bm['og:description'] and '<script>' not in bm['og:description'],'Metadata text escaped and tags stripped')
longpid,longtok=makepost('A'*8000);longm=metadata(visit('/posts/'+longtok));check(len(longm['og:description'])<=401,'Description bounded');verify_png(image_request(longm),'Long word card')
check(visit('/social-preview/posts/not-a-public-token/00000000000000000000.png').status_code==404,'Malformed token denied');check(visit('/social-preview/posts/'+public_token+'/bad.png').status_code==404,'Malformed revision denied')
verify_png(visit('/social-preview/default.png'),'Generic public banner')
check(metadata(visit('/guide'))['og:type']=='website','Other pages generic banner')
current=metadata(visit('/posts/'+public_token));change('DELETE FROM posts WHERE id=?',(public_pid,));check(image_request(current).status_code==404,'Deleted post preview revoked')
check(b'Social sharing previews' in visit('/dev').data,'Dev log updated')
out=stage.parent.parent;(out/('fictional-text-'+package+'.png')).write_bytes(before_bytes);(out/('fictional-photo-'+package+'.png')).write_bytes(pr.data)
print(json.dumps({'package':package,'checks':checks,'isolated':str(path).startswith(str(w)),'preview_size':[1200,630]}))
