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




connections=importlib.import_module(package+'.social_connections')
def send(key,path,**data):
    return clients[key].post(path,data={'theme_csrf_token':token,'friend_csrf_token':token,**data},environ_overrides=env)
for c in clients.values():
    with c.session_transaction() as state:state['friend_csrf_token']=token
writer,reader,other=users['Writer'],users['Regular'],users['NoFactor']
def follower_row(a=reader,b=writer):
    return query('SELECT revoked FROM follows WHERE follower_id=? AND followed_id=?',(a,b))
def public_id(pid):
    with app.app_context():return core.identifiers.public(core.get_db(),'post',pid)
def read(key,pid):return get(key,'/posts/'+public_id(pid))
def friendship(a,b):change("INSERT OR REPLACE INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(a,b))
def new_post(audience,text='DISPOSABLE T16 POST'):
    before=query('SELECT MAX(id) FROM posts')[0][0]
    result=send('Writer','/create_post',content=text,vibes='',circle='',audience=audience)
    check(result.status_code==302,'Create post '+audience+' '+str(result.status_code))
    row=query('SELECT id FROM posts WHERE user_id=? AND id>? ORDER BY id DESC',(writer,before))[0]
    return row['id']
check(send('Regular','/follow/'+str(writer)).status_code==302,'Eligible one-way follow')
check(follower_row()[0][0]==0,'Follow saved active')
check(not query("SELECT 1 FROM friend_requests WHERE status='accepted' AND sender_id=? AND receiver_id=?",(reader,writer)),'Follow does not create friendship')
check(send('Regular','/follow/'+str(writer)).status_code==302 and len(follower_row())==1,'Repeated follow idempotent')
check(send('Regular','/unfollow/'+str(writer)).status_code==302 and follower_row()[0][0]==1,'Unfollow revokes')
check(send('Regular','/follow/'+str(writer)).status_code==302 and follower_row()[0][0]==0,'Refollow reactivates original record')
change("INSERT OR REPLACE INTO privacy_settings(user_id,comments_from) VALUES (?,'nobody')",(writer,))
send('Regular','/unfollow/'+str(writer))
check(send('Regular','/follow/'+str(writer)).status_code==302,'Comment preference does not govern follows')
bad=clients['Regular'].post('/follow/'+str(other),data={'theme_csrf_token':token,'friend_csrf_token':'invalid'},environ_overrides=env)
check(bad.status_code==400 and not follower_row(reader,other),'Follow requires friend CSRF too')
check(send('Regular','/follow/'+str(reader)).status_code==403,'Cannot follow self')
check(send('Regular','/follow/999999999').status_code==403,'Unknown follow target denied')
check(send('Teen','/follow/'+str(writer)).status_code==403,'Minor age/contact boundary preserved')
r=clients['Regular'].post('/account/connections',data={'theme_csrf_token':token,'action':'following','enabled':'1'},headers={'Origin':'https://foreign.invalid'},environ_overrides=env)
check(r.status_code==403,'Foreign origin rejected')
check(get('Writer','/account/connections').status_code==200,'Private settings page renders')
check(b'Unfollow' in get('Regular','/@VMFixtureWriter').data,'Profile shows active follow control')
pid=new_post('connections')
check(read('Regular',pid).status_code==200,'Active follower reads opted-in post')
check(read('NoFactor',pid).status_code==404,'Unrelated member cannot read follower post')
check(app.test_client().get('/posts/'+public_id(pid),environ_overrides=env).status_code==404,'Anonymous visitor cannot read follower post')
friends_pid=new_post('friends')
check(read('Regular',friends_pid).status_code==404,'Friends-only excludes follower-only access')
public_pid=new_post('public')
check(read('NoFactor',public_pid).status_code==200,'Public audience remains independently public')
friendship(writer,other)
check(read('NoFactor',pid).status_code==200 and read('NoFactor',friends_pid).status_code==200,'Accepted friend retains both audiences')
check(send('Writer','/account/connections',action='remove-follower',target_id=reader).status_code==302,'Owner removes own follower')
check(read('Regular',pid).status_code==404,'Follower removal revokes post access immediately')
check(send('Regular','/follow/'+str(writer)).status_code==403,'Removed follower cannot immediately refollow')
check(send('Writer','/account/connections',action='allow-follower',target_id=reader).status_code==302 and follower_row()[0][0]==1,'Allow again does not reactivate follow')
check(send('Regular','/follow/'+str(writer)).status_code==302,'Owner can allow a new follow')
check(send('Writer','/account/connections',action='following').status_code==302,'Global opt-out')
check(follower_row()[0][0]==1 and read('Regular',pid).status_code==404,'Opt-out revokes follower-only access')
check(read('NoFactor',pid).status_code==200,'Opt-out preserves accepted friend access')
check(send('Regular','/follow/'+str(writer)).status_code==403,'Disabled account rejects new follows')
check(b'>Follow</button>' not in get('Regular','/@VMFixtureWriter').data,'Disabled follow control hidden')
check(send('Writer','/account/connections',action='following',enabled='1').status_code==302 and follower_row()[0][0]==1,'Opt-in does not resurrect follows')
check(send('Regular','/follow/'+str(writer)).status_code==302,'Can follow after opt-in')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(writer,reader))
check(read('Regular',pid).status_code==404 and send('Regular','/follow/'+str(writer)).status_code==403,'Block overrides follows')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(writer,reader))
check(send('Writer','/friends/labels',action='create',name='  Book   <friends>  ').status_code==302,'Create normalized private label')
lid=query('SELECT id FROM friend_labels WHERE user_id=?',(writer,))[0][0]
label='label:'+str(lid)
check(query('SELECT name FROM friend_labels WHERE id=?',(lid,))[0][0]=='Book <friends>','Custom name preserved and normalized')
check(send('Writer','/friends/labels',action='create',name='book <FRIENDS>').status_code==400,'Duplicate casefold label rejected')
check(send('Writer','/friends/labels',action='create',name='\x00bad').status_code==400,'Control characters rejected')
check(send('Writer','/friends/labels',action='create',name='x'*41).status_code==400,'Label length bounded')
check(send('Regular','/friends/labels',action='rename',label_id=lid,name='Stolen').status_code==404,'Foreign label ID cannot be changed')
check(send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=reader).status_code==400,'Follower is not eligible for friend label')
check(send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=other).status_code==302,'Assign accepted Friend')
check(send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=other).status_code==302 and len(query('SELECT * FROM friend_label_members WHERE label_id=?',(lid,)))==1,'Assignment idempotent')
check(b'Book &lt;friends&gt;' in get('Writer','/friends').data,'Label escaped in owner friend UI')
check(b'Book &lt;friends&gt;' not in get('NoFactor','/friends/VMFixtureWriter').data,'Other users cannot see private labels')
check(b'Book &lt;friends&gt;' in get('Writer','/create_post').data,'Label available to owner as post audience')
check(b'Book &lt;friends&gt;' not in get('Regular','/create_post').data,'Foreign label not in composer')
label_pid=new_post(label)
check(read('NoFactor',label_pid).status_code==200 and read('Regular',label_pid).status_code==404,'Label audience requires current assigned friendship')
check(send('Regular','/create_post',content='DENIED FOREIGN LABEL',vibes='',circle='',audience=label).status_code==400,'Forged label audience rejected')
change('UPDATE privacy_settings SET post_audience=? WHERE user_id=?',(label,writer))
check(send('Writer','/friends/labels',action='archive',label_id=lid).status_code==302,'Archive label')
check(query('SELECT post_audience FROM privacy_settings WHERE user_id=?',(writer,))[0][0]=='private','Archiving a default label resets new posts to Only me')
check(read('NoFactor',label_pid).status_code==404,'Archived label fails closed')
edit=get('Writer','/edit_post/'+public_id(label_pid))
check(edit.status_code==200 and b'Unavailable friend label' in edit.data,'Archived post edit retains unavailable audience option')
check(send('Writer','/edit_post/'+public_id(label_pid),content='UPDATED PRIVATE LABEL POST',vibes='',circle='',audience=label).status_code==302,'Archived post can keep its restricted audience on edit')
check(query('SELECT audience FROM post_privacy WHERE post_id=?',(label_pid,))[0][0]==label and read('NoFactor',label_pid).status_code==404,'Editing archived label never widens audience')
check(send('Writer','/create_post',content='DENIED ARCHIVED LABEL',vibes='',circle='',audience=label).status_code==400,'Cannot target archived label on new post')
check(send('Writer','/friends/labels',action='restore',label_id=lid).status_code==302 and read('NoFactor',label_pid).status_code==200,'Explicit restore reinstates eligible label access')
check(send('Writer','/friends/labels',action='rename',label_id=lid,name='Reading crew').status_code==302 and read('NoFactor',label_pid).status_code==200,'Rename keeps stable audience ID')
check(send('Writer','/friends/labels',action='unassign',label_id=lid,friend_id=other).status_code==302 and read('NoFactor',label_pid).status_code==404,'Removing assignment revokes access')
send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=other)
check(send('Writer','/remove_friend/'+str(other)).status_code==302,'Remove friend')
check(not query('SELECT 1 FROM friend_label_members WHERE label_id=? AND friend_id=?',(lid,other)) and read('NoFactor',label_pid).status_code==404,'Friend removal clears label membership and access')
friendship(writer,other)
check(read('NoFactor',label_pid).status_code==404,'Re-friending does not resurrect label assignments')
send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=other)
export=send('Writer','/account/export')
check(export.status_code==200 and export.json['social_connections']['friend_labels'][0]['name']=='Reading crew','Own account export includes own labels')
export_other=send('Regular','/account/export')
check(export_other.status_code==200 and not export_other.json['social_connections']['friend_labels'],'Export never includes another owner labels')
with app.app_context():
    db=core.get_db();connections.initialize(db);connections.initialize(db)
    check(db.execute('SELECT COUNT(*) FROM friend_labels WHERE id=?',(lid,)).fetchone()[0]==1,'Repeated migration preserves data')
    check(not connections.valid_post_audience(db,reader,label),'Label validation checks ownership')
check(get('Writer','/account/connections',followers_page=0).status_code==400,'Connection pagination validates bounds')
check(get('Writer','/friends').status_code==200 and get('Writer','/account/privacy').status_code==200,'Friends and privacy pages remain usable')
check(query('PRAGMA quick_check')[0][0]=='ok','Disposable database integrity healthy')
huge='999999999999999999999999999999999999'
for route in ['/follow/'+huge,'/unfollow/'+huge]:
    check(send('Regular',route).status_code==400,'Oversized relationship ID rejected without SQLite overflow')
check(send('Writer','/account/connections',action='allow-follower',target_id=huge).status_code==400,'Oversized removed-follower ID rejected')
check(send('Writer','/friends/labels',action='assign',label_id=lid,friend_id=huge).status_code==400,'Oversized label member ID rejected')
check(send('Writer','/friends/labels',action='rename',label_id=huge,name='Denied').status_code==404,'Oversized label ID rejected')

# Keep all additional scenarios on the copied fixture, including concurrency.
import concurrent.futures,threading
from unittest.mock import patch
send('Regular','/unfollow/'+str(writer))
original_can_follow=connections.can_follow;entered=threading.Event();release=threading.Event()
def paused_follow(db,a,b):
    ok=original_can_follow(db,a,b)
    if a==reader and b==writer:
        entered.set();assert release.wait(3)
    return ok
with patch.object(connections,'can_follow',paused_follow):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        follow_job=pool.submit(send,'Regular','/follow/'+str(writer));assert entered.wait(3)
        optout_job=pool.submit(send,'Writer','/account/connections',action='following')
        release.set();check(follow_job.result(timeout=10).status_code==302 and optout_job.result(timeout=10).status_code==302,'Follow and opt-out serialize safely')
check(follower_row()[0][0]==1,'Concurrent opt-out does not leave an active relationship to resurrect')
send('Writer','/account/connections',action='following',enabled='1')
check(follower_row()[0][0]==1,'Re-enable after concurrent opt-out preserves revocation')
send('Regular','/follow/'+str(writer))
for key in ('Writer','Regular'):
    bad=clients[key].post('/friends/labels',data={'theme_csrf_token':'wrong','action':'create','name':'DENIED'},environ_overrides=env)
    check(bad.status_code==400,'Label form rejects invalid CSRF')
with app.app_context():
    db=core.get_db();change_before=db.execute('SELECT COUNT(*) FROM friend_labels').fetchone()[0]
    for index in range(31):db.execute('INSERT INTO friend_labels(user_id,name,name_key) VALUES (?,?,?)',(writer,'Fixture label '+str(index),'fixture '+str(index)))
    db.commit()
check(send('Writer','/friends/labels',action='create',name='One too many').status_code==400,'Label count bound enforced')
with app.app_context():
    db=core.get_db();own_before=db.execute('SELECT COUNT(*) FROM friend_labels WHERE user_id=?',(writer,)).fetchone()[0]
    db.execute("INSERT INTO friend_labels(user_id,name,name_key) VALUES (?,'Other owner private label','other-owner')",(other,));db.commit()
    connections.erase_user(db,other);db.commit()
    check(db.execute('SELECT COUNT(*) FROM friend_labels WHERE user_id=?',(writer,)).fetchone()[0]==own_before,'Erasure helper preserves other owners label definitions')
    check(not db.execute('SELECT 1 FROM friend_label_members WHERE friend_id=? OR user_id=?',(other,other)).fetchone(),'Erasure helper unlinks subject from both sides')
# Exercise bounded pagination with synthetic adult connections, not live users.
with app.app_context():
    db=core.get_db()
    for index in range(25):
        uid=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,'1990-01-01',1,CURRENT_TIMESTAMP)",('@T16PageFixture'+str(index),'t16page'+str(index)+'@example.invalid','!disabled-fixture')).lastrowid
        db.execute("INSERT INTO age_clocks VALUES (?,'UTC',1)",(uid,));db.execute('INSERT INTO follows(follower_id,followed_id,revoked) VALUES (?,?,0)',(uid,writer));db.execute('INSERT INTO follower_exclusions VALUES (?,?)',(writer,uid))
    db.commit()
first=get('Writer','/account/connections');second=get('Writer','/account/connections',followers_page=2,excluded_page=2)
check(first.status_code==200 and second.status_code==200 and b'followers_page=2' in first.data and b'excluded_page=2' in first.data,'Follower and exclusion lists offer bounded next pages')
check(b'T16PageFixture24' not in first.data and b'T16PageFixture24' in second.data,'Later connection rows appear only on requested page')
with app.app_context():
    db=core.get_db();before=db.execute('SELECT COUNT(*) FROM friend_label_members').fetchone()[0]
    check(not connections.post_audience_allows(db,writer,reader,'label:999999999999999999'),'Unknown label audience fails closed')
    check(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','Database remains healthy after concurrent scenarios')
proof=get('Writer','/account/connections')
(stage.parent.parent/'fixture-connections-preview.html').write_bytes(proof.data)

legacy=app.test_client().get('/friends/connections',environ_overrides=env)
check(legacy.status_code in (200,404),'New settings route does not shadow a public friends handle')
print(str(checks)+' T16 following and friend-label checks passed for '+package)
