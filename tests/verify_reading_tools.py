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




reading=importlib.import_module(package+'.reading_tools')
connections=importlib.import_module(package+'.social_connections')
def send(key,path,**data):
 return clients[key].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def text(response):return response.get_data(as_text=True)
uid=users['Regular'];writer=users['Writer'];other=users['Manager']
def newpost(owner,label,audience='public',vibe=None,circle=None):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,target_user_id,content,circle,created_at) VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)',(pid,owner,owner,label,''));core.identifiers.ensure(db,'post',pid);db.execute('INSERT INTO post_privacy VALUES (?,?)',(pid,audience))
  if vibe:db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,vibe))
  if circle:db.execute('INSERT INTO circle_posts VALUES (?,?)',(pid,circle))
  db.commit();return pid,core.identifiers.public(db,'post',pid)
def draftrow(owner=uid):return query('SELECT * FROM composer_drafts WHERE user_id=? ORDER BY rowid DESC',(owner,))[0]
for path in ['/account/feed','/bookmarks','/account/bookmarks','/drafts']:
 check(get('Regular',path).status_code==200,'Reading screen renders '+path)
 check(app.test_client().get(path,environ_overrides=env).status_code in (302,401),'Anonymous reading screen denied '+path)
check(send('Regular','/account/feed',default_view='not-a-view').status_code==400,'Unknown default rejected')
check(get('Regular','/feed',view='not-a-view').status_code==400,'Unknown feed view rejected')
check(clients['Regular'].post('/account/feed',data={'default_view':'all'},environ_overrides=env).status_code==400,'Preferences require CSRF')
check(clients['Regular'].post('/drafts/save',data={'content':'NO-CSRF','audience':'private'},environ_overrides=env).status_code==400,'Drafts require CSRF')
check(clients['Regular'].post('/account/feed',data={'theme_csrf_token':token,'default_view':'all'},headers={'Origin':'https://foreign.example'},environ_overrides=env).status_code==403,'Foreign origin rejected')
for page in ['0','-1','10001','9'*60,'garbage']:
 check(get('Regular','/drafts',page=page).status_code==400,'Draft page bound '+page[:10])
check(send('Regular','/account/feed',default_view='friends').status_code==302,'Save default view')
check('Friends</h3>' in text(get('Regular','/feed')),'Default persists in later request')
check('All posts</h3>' in text(get('Regular','/feed',view='all')),'Explicit view overrides without writing default')
check(query('SELECT default_view FROM reading_preferences WHERE user_id=?',(uid,))[0][0]=='friends','Temporary view does not change preference')
public,pub=newpost(writer,'READING PUBLIC SENTINEL')
private,priv=newpost(writer,'READING PRIVATE SENTINEL','private')
outsider,outref=newpost(other,'READING OUTSIDER SENTINEL')
change("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(uid,writer))
friends_html=text(get('Regular','/feed',view='friends'))
check('READING PUBLIC SENTINEL' in friends_html and 'READING OUTSIDER SENTINEL' not in friends_html and 'READING PRIVATE SENTINEL' not in friends_html,'Friends view narrows without granting access')
change('INSERT INTO follows(follower_id,followed_id,revoked) VALUES (?,?,0)',(uid,writer))
check('READING PUBLIC SENTINEL' in text(get('Regular','/feed',view='followed')),'Followed includes current eligible author')
change('INSERT OR REPLACE INTO follow_preferences VALUES (?,0)',(writer,))
check('READING PUBLIC SENTINEL' not in text(get('Regular','/feed',view='followed')),'Follow opt-out removes stale followed entry')
change('INSERT OR REPLACE INTO follow_preferences VALUES (?,1)',(writer,))
change('UPDATE follows SET revoked=1 WHERE follower_id=? AND followed_id=?',(uid,writer))
check('READING PUBLIC SENTINEL' not in text(get('Regular','/feed',view='followed')),'Revoked follows do not contribute')
change('UPDATE follows SET revoked=0 WHERE follower_id=? AND followed_id=?',(uid,writer))
change('INSERT INTO user_mutes(user_id,target_id) VALUES (?,?)',(uid,writer))
check('READING PUBLIC SENTINEL' not in text(get('Regular','/feed',view='friends')),'Muted author excluded from friends view')
change('DELETE FROM user_mutes WHERE user_id=? AND target_id=?',(uid,writer))
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(uid,writer))
check('READING PUBLIC SENTINEL' not in text(get('Regular','/feed',view='followed')),'Blocked author excluded from followed view')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(uid,writer))
with app.app_context():
 db=core.get_db();v=db.execute("INSERT INTO vibes(name) VALUES ('READING SELECTED VIBE')").lastrowid;db.commit()
vp,vref=newpost(writer,'READING VIBE SENTINEL',vibe=v)
check(send('Regular','/account/feed',default_view='vibes',vibe_id=str(v)).status_code==302,'Save Vibe selections')
check('READING VIBE SENTINEL' in text(get('Regular','/feed')) and 'READING OUTSIDER SENTINEL' not in text(get('Regular','/feed')),'Vibe feed selects chosen Vibes')
change('INSERT OR REPLACE INTO vibe_management(vibe_id,archived) VALUES (?,1)',(v,))
check('READING VIBE SENTINEL' not in text(get('Regular','/feed',view='vibes')),'Archived Vibe excluded')
change('UPDATE vibe_management SET archived=0 WHERE vibe_id=?',(v,))
check(send('Regular','/account/feed',default_view='all',vibe_id='9'*90).status_code==400,'Huge Vibe ID rejected')
check(send('Regular','/account/feed',default_view='all',vibe_id='999999999999999999').status_code==400,'Nonexistent Vibe rejected')
check(send('Regular','/account/feed',default_view='all',vibe_id=[str(v)]*51).status_code==400,'Vibe selection cap')
check(send('Regular','/account/feed',default_view='all').status_code==302,'Return to all view')
# More than one page preserves the chosen view and filters before LIMIT.
for n in range(22):newpost(writer,'READING PAGE FRIEND '+str(n))
response=get('Regular','/feed',view='friends');html=text(response)
check(response.status_code==200 and 'view=friends' in html and 'timeline_cursor=' in html,'Pagination preserves explicit grouping')
check('READING PAGE FRIEND' in text(get('Regular','/feed',view='friends',page=2)),'Second grouped page renders')
# Private references do not become content copies.
check(send('Regular','/reading/bookmark/'+pub,action='save').status_code==302,'Save bookmark')
check(send('Regular','/reading/bookmark/'+pub,action='save').status_code==302 and query('SELECT count(*) FROM post_bookmarks WHERE user_id=? AND post_id=?',(uid,public))[0][0]==1,'Repeated bookmark is idempotent')
check(send('Regular','/reading/bookmark/'+priv,action='save').status_code==404,'Cannot bookmark inaccessible private post')
check('READING PUBLIC SENTINEL' in text(get('Regular','/bookmarks')),'Bookmarked feed shows current original')
check('READING PUBLIC SENTINEL' not in text(get('Manager','/bookmarks')),'Bookmarks are owner-only')
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(public,))
check('READING PUBLIC SENTINEL' not in text(get('Regular','/bookmarks')),'Revoked post hidden in bookmarks')
manage=text(get('Regular','/account/bookmarks'))
check('Post unavailable' in manage and 'READING PUBLIC SENTINEL' not in manage,'Unavailable bookmark has no preview')
bid=query('SELECT id FROM post_bookmarks WHERE user_id=? AND post_id=?',(uid,public))[0][0]
check(send('Manager','/account/bookmarks',id=bid).status_code==302 and query('SELECT 1 FROM post_bookmarks WHERE id=?',(bid,)),'Other owner cannot remove bookmark')
check(send('Regular','/account/bookmarks',id=bid).status_code==302 and not query('SELECT 1 FROM post_bookmarks WHERE id=?',(bid,)),'Owner removes unavailable bookmark')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(public,))
check(send('Regular','/reading/bookmark/'+pub,action='save').status_code==302,'Re-save bookmark')
change("UPDATE posts SET content='READING EDITED ORIGINAL' WHERE id=?",(public,))
check('READING EDITED ORIGINAL' in text(get('Regular','/bookmarks')),'Bookmark reflects edits')
change('INSERT INTO user_mutes(user_id,target_id) VALUES (?,?)',(uid,writer))
check('READING EDITED ORIGINAL' not in text(get('Regular','/bookmarks')),'Bookmark respects muting')
change('DELETE FROM user_mutes WHERE user_id=? AND target_id=?',(uid,writer))
for bad in ['9'*100,'unknown','<bad>']:
 check(send('Regular','/reading/bookmark/'+bad,action='save').status_code==404,'Malformed bookmark identifier fails safely')
# Drafts persist content/settings, remain private, escape HTML and require revisions.
payload={'content':'READING DRAFT <script>alert(1)</script>','audience':'friends','vibes':'READING SELECTED VIBE','circle_audience':'private'}
check(send('Regular','/drafts/save',**payload).status_code==302,'Create private draft')
d=draftrow();key=d['id'];rev=str(d['revision'])
check(json.loads(d['payload'])['audience']=='friends','Draft retains audience')
check(get('Manager','/drafts/'+key).status_code==404,'Other owner cannot view draft')
check(get('Manager','/create_post',draft=key).status_code==404,'Other owner cannot resume draft')
check(send('Manager','/drafts/save',draft_id=key,draft_revision=rev,**payload).status_code==404,'Other owner cannot overwrite draft')
check(send('Manager','/drafts/'+key+'/delete',draft_revision=rev).status_code==404,'Other owner cannot remove draft')
editor=text(get('Regular','/drafts/'+key))
check('&lt;script&gt;' in editor and '<script>alert(1)</script>' not in editor,'Draft text escaped in editor')
resumed=text(get('Regular','/create_post',draft=key))
check('name="draft_revision"' in resumed and key in resumed and '&lt;script&gt;' in resumed,'Draft resumes in full composer')
check(send('Regular','/drafts/save',draft_id=key,draft_revision=rev,content='READING UPDATED DRAFT',audience='private').status_code==302,'Update draft')
check(send('Regular','/drafts/save',draft_id=key,draft_revision=rev,**payload).status_code==409,'Stale draft cannot overwrite')
check(send('Regular','/drafts/'+key+'/delete',draft_revision=rev).status_code==409,'Stale draft cannot remove newer version')
check(send('Regular','/create_post',draft_id=key,draft_revision=rev,content='READING STALE PUBLISH',audience='private').status_code==409 and not query("SELECT 1 FROM posts WHERE content='READING STALE PUBLISH'"),'Stale draft cannot publish')
d=draftrow();before=query('SELECT count(*) FROM posts')[0][0]
check(send('Regular','/create_post',draft_id=key,draft_revision=str(d['revision']),content='READING DRAFT PUBLISHED',audience='private').status_code==302,'Publish current draft')
check(query('SELECT count(*) FROM posts')[0][0]==before+1 and not query('SELECT 1 FROM composer_drafts WHERE id=?',(key,)),'Successful publish consumes draft atomically')
check(send('Regular','/create_post',draft_id=key,draft_revision=str(d['revision']),content='READING DOUBLE PUBLISH',audience='private').status_code==404,'Used draft cannot publish twice')
check(not query("SELECT 1 FROM posts WHERE content='READING DOUBLE PUBLISH'"),'Duplicate publish creates no post')
check(send('Regular','/drafts/save',content='x'*20001,audience='private').status_code==400,'Draft text limit')
check(send('Regular','/drafts/save',content='x',audience='bad').status_code==400,'Unknown draft audience rejected')
check(send('Regular','/drafts/save',content='x',audience='private',circle_id='../bad').status_code==400,'Draft destination bounded')
file_response=clients['Regular'].post('/drafts/save',data={'theme_csrf_token':token,'content':'TEXT','audience':'private','post_image':(io.BytesIO(b'not saved'),'sample.png')},content_type='multipart/form-data',environ_overrides=env)
check(file_response.status_code==400,'Draft attachment save rejected without writing files')
check(send('Regular','/drafts/save',content='READING RECOVERY DRAFT',audience='label:999999',circle_id='ABCDEFabcdef1234').status_code==302,'Draft can retain stale destination for private recovery')
d=draftrow();key=d['id'];editor=text(get('Regular','/drafts/'+key))
check('READING RECOVERY DRAFT' in editor and 'Unavailable Circle' in editor,'Draft remains recoverable after losing destination')
check(get('Regular','/create_post',draft=key).status_code==404,'Unavailable Circle never becomes public composer')
check(send('Regular','/drafts/save',draft_id=key,draft_revision=str(d['revision']),content='READING RECOVERED',audience='private').status_code==302,'Owner explicitly changes stale destination')
check(get('Regular','/create_post',draft=key).status_code==200,'Recovered draft opens composer')
# Export scope and unchanged privacy/future erasure defaults.
with app.app_context():
 exported=reading.export_user(core.get_db(),uid,core.identifiers);foreign=reading.export_user(core.get_db(),other,core.identifiers)
check(exported['drafts'] and not foreign['drafts'],'Export includes only own drafts')
check('READING RECOVERED' in json.dumps(exported) and 'password_hash' not in json.dumps(exported),'Private draft export includes text but no credentials')
check(all('post_id' not in r for r in exported['bookmarks']),'Bookmark exports use public references')
with app.app_context():
 db=core.get_db();reading.initialize(db);reading.initialize(db)
check(query('SELECT COUNT(*) FROM composer_drafts WHERE user_id=?',(uid,))[0][0]==1,'Repeated migration preserves drafts')
# Existing notification preferences and muting still suppress delivery.
with app.app_context():
 db=core.get_db();db.execute("INSERT OR REPLACE INTO notification_settings VALUES (?,'comments',0)",(uid,));db.commit();cf.notify(db,uid,'comments','READING NOTIFY SENTINEL','/posts/'+pub,writer);db.commit()
check(not query("SELECT 1 FROM notifications WHERE user_id=? AND message='READING NOTIFY SENTINEL'",(uid,)),'Existing disabled notifications suppress new delivery')
check(get('Regular','/notifications').status_code==200 and get('Regular','/account/privacy').status_code==200,'Existing notification and muting screens render')
check(not app.config.get('RETENTION_ENABLED',False),'Permanent erasure remains disabled in candidate')
check('no-store' in get('Regular','/drafts').headers.get('Cache-Control',''),'Private drafts never cache')
check(get('Teen','/reading/bookmark/'+pub).status_code==405,'Bookmark changes cannot use GET')
check(send('Teen','/reading/bookmark/'+pub,action='save').status_code==404,'Bookmark cannot cross age boundary')
# Joined Circle feed, original media/post routes and revocation remain consistent.
check(send('Writer','/circles',name='READING FIXTURE CIRCLE',mode='hidden',description='Fictional T17 checks').status_code==302,'Create fixture Circle')
circle=query('SELECT * FROM circles WHERE owner_id=? ORDER BY id DESC',(writer,))[0];circle_id=circle['id']
change("INSERT INTO circle_members(circle_id,user_id,role,status) VALUES (?,?,'member','active')",(circle_id,uid))
cp,cref=newpost(writer,'READING CIRCLE SENTINEL','private',circle=circle_id)
check('READING CIRCLE SENTINEL' in text(get('Regular','/feed',view='circles')),'Joined Circle included')
check('READING CIRCLE SENTINEL' not in text(get('Manager','/feed',view='circles')),'Other account does not inherit Circle feed')
check(send('Regular','/reading/bookmark/'+cref,action='save').status_code==302,'Member can bookmark Circle post')
change("UPDATE circle_members SET status='left' WHERE circle_id=? AND user_id=?",(circle_id,uid))
check('READING CIRCLE SENTINEL' not in text(get('Regular','/feed',view='circles')),'Left Circle excluded')
check('READING CIRCLE SENTINEL' not in text(get('Regular','/bookmarks')) and get('Regular','/posts/'+cref).status_code==404,'Circle loss revokes bookmark and direct access')
check(send('Regular','/reading/bookmark/'+cref,action='remove').status_code==302,'Owner can remove inaccessible Circle bookmark')
# Saved shares preserve references, and lost access is recoverable through private draft editing.
check(send('Regular','/drafts/save',content='READING SHARE DRAFT',audience='private',shared_source=pub,shared_kind='post').status_code==302,'Save shared-post draft')
d=draftrow();sharekey=d['id']
check('READING EDITED ORIGINAL' in text(get('Regular','/create_post',draft=sharekey)),'Shared draft rechecks and displays current preview')
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(public,))
check(get('Regular','/create_post',draft=sharekey).status_code==404,'Revoked original never leaks through resumed draft')
check('READING SHARE DRAFT' in text(get('Regular','/drafts/'+sharekey)),'Owned commentary recoverable after source revocation')
check(send('Regular','/drafts/save',draft_id=sharekey,draft_revision=str(d['revision']),content='READING COMMENT RECOVERED',audience='private',shared_source=pub,shared_kind='post',drop_share='1').status_code==302,'Owner explicitly removes stale source')
check(get('Regular','/create_post',draft=sharekey).status_code==200,'Recovered share draft becomes ordinary composer')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(public,))
# Publishing failures retain both the draft and the original core data.
d=draftrow();key=d['id'];count=query('SELECT count(*) FROM posts')[0][0]
check(send('Regular','/create_post',draft_id=key,draft_revision=str(d['revision']),content='READING FAILED PUBLISH',audience='label:999999').status_code==400,'Invalid publishing audience is rejected')
check(query('SELECT 1 FROM composer_drafts WHERE id=?',(key,)) and query('SELECT count(*) FROM posts')[0][0]==count,'Failed publish retains draft and creates no post')
# Limits are serialized; tests fill only the disposable fixture.
with app.app_context():
 db=core.get_db();existing=db.execute('SELECT count(*) FROM composer_drafts WHERE user_id=?',(uid,)).fetchone()[0]
 for n in range(50-existing):db.execute('INSERT INTO composer_drafts(id,user_id,payload) VALUES (?,?,?)',('cap'+str(n).zfill(29),uid,json.dumps({'content':'Fictional cap draft'})))
 db.commit()
check(send('Regular','/drafts/save',content='OVER CAP',audience='private').status_code==409,'Fifty-draft cap enforced')
check(get('Regular','/drafts',page=2).status_code==200 and 'Older drafts' in text(get('Regular','/drafts')),'Draft lists paginate')
change("DELETE FROM composer_drafts WHERE user_id=? AND id LIKE 'cap%'",(uid,))
with app.app_context():
 db=core.get_db();existing=db.execute('SELECT count(*) FROM post_bookmarks WHERE user_id=?',(uid,)).fetchone()[0]
 for n in range(2000-existing):db.execute('INSERT INTO post_bookmarks(id,user_id,post_id) VALUES (?,?,?)',('cap'+str(n).zfill(29),uid,-n-1))
 db.commit()
check(send('Regular','/reading/bookmark/'+outref,action='save').status_code==409,'Two-thousand bookmark cap enforced')
check(send('Regular','/reading/bookmark/'+pub,action='save').status_code==302,'Idempotent re-save still allowed at cap')
check(get('Regular','/account/bookmarks',page=2).status_code==200 and 'Next' in text(get('Regular','/account/bookmarks')),'Bookmark management paginates even unavailable entries')
change("DELETE FROM post_bookmarks WHERE user_id=? AND id LIKE 'cap%'",(uid,))
# Competing tabs may produce only one accepted version and one published post.
import concurrent.futures,threading
check(send('Regular','/drafts/save',content='READING CONCURRENT DRAFT',audience='private').status_code==302,'Create concurrency fixture draft')
race=draftrow();racekey=race['id']
with clients['Regular'].session_transaction() as s:session_copy=dict(s)
def race_clients():
 result=[]
 for _ in range(2):
  c=app.test_client()
  with c.session_transaction() as s:s.update(session_copy)
  result.append(c)
 return result
barrier=threading.Barrier(2);tabs=race_clients()
def simultaneous_save(n):
 barrier.wait();return tabs[n].post('/drafts/save',data={'theme_csrf_token':token,'draft_id':racekey,'draft_revision':str(race['revision']),'content':'READING RACE EDIT '+str(n),'audience':'private'},environ_overrides=env).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(simultaneous_save,range(2)))
check(sorted(codes)==[302,409],'Concurrent tab edits cannot overwrite one another')
race=query('SELECT * FROM composer_drafts WHERE id=?',(racekey,))[0];tabs=race_clients();barrier=threading.Barrier(2)
def simultaneous_publish(n):
 barrier.wait();return tabs[n].post('/create_post',data={'theme_csrf_token':token,'draft_id':racekey,'draft_revision':str(race['revision']),'content':'READING RACE PUBLISH '+str(n),'audience':'private'},environ_overrides=env).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(simultaneous_publish,range(2)))
check(codes.count(302)==1 and all(c in (302,404,409) for c in codes),'Concurrent draft publishing accepts one request')
check(query("SELECT count(*) FROM posts WHERE content LIKE 'READING RACE PUBLISH %'")[0][0]==1,'Concurrent draft publishes create exactly one post')
# Holding a bookmark owner prevents erasure from removing their related bookmark.
privacy=importlib.import_module(package+'.privacy_workflows');retention=importlib.import_module(package+'.retention')
change('INSERT INTO post_bookmarks(id,user_id,post_id) VALUES (?,?,?)',('b'*32,uid,outsider))
change('INSERT INTO privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) VALUES (?,?,?,?,?,?,?)',(uid,'Fictional fixture hold','fixture','T17',1,now,now+86400))
with app.app_context():check(bool(privacy.erasure_blockers(core.get_db(),other)),'Related bookmark preservation is discovered')
change('DELETE FROM privacy_holds WHERE user_id=?',(uid,))
check(send('Manager','/account/feed',default_view='friends').status_code==302,'Other account owns independent preference')
check(send('Manager','/drafts/save',content='READING ERASE FIXTURE',audience='private').status_code==302,'Other account owns independent draft')
with app.app_context():
 db=core.get_db();db.execute('BEGIN IMMEDIATE');retention.erase_account(db,other,{k:str(w/k) for k in ['avatars','media','consent','backups']});db.commit()
check(not query('SELECT 1 FROM composer_drafts WHERE user_id=?',(other,)) and not query('SELECT 1 FROM reading_preferences WHERE user_id=?',(other,)),'Future erasure cleans own reading records')
check(not query('SELECT 1 FROM post_bookmarks WHERE post_id=?',(outsider,)),'Future erasure cleans references to erased posts')
check(query('SELECT 1 FROM composer_drafts WHERE user_id=?',(uid,)),'Future erasure retains unrelated owner drafts')
check(query('PRAGMA integrity_check')[0][0]=='ok','Fixture database integrity')
print(checks,'T17 reading and draft checks passed for',package)
