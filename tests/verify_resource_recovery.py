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
for k,v in {'DATABASE':str(w/'fixture.db'),'SECRET_FILE':str(w/'secret'),'INSTANCE':str(w/'instance'),'MAIL_QUEUE_DIR':str(w/'mail'),'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')}.items():os.environ[prefix+'_'+k]=v
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



import concurrent.futures,errno,random
from unittest.mock import patch
from werkzeug.datastructures import FileStorage
from PIL import Image
recovery=importlib.import_module(package+'.resource_errors');media=importlib.import_module(package+'.media_features')
app.config['UPLOAD_FOLDER']=str(w/'uploads')
with clients['Regular'].session_transaction() as s:s['profile_edit_token']=token

def image_probe():
    value=media._save_image(request.files['image'],'Synthetic image','original','')
    return core.jsonify(value)
from flask import request
app.add_url_rule('/resource-test/image','resource_test_image',image_probe,methods=['POST'])
check(get('Regular','/feed').status_code==200,'Normal rendering and asset-version syntax')
check('resource-recovery-20261020' in get('Regular','/feed').get_data(as_text=True),'New client script version')
pid,public=post_fixture('DISPOSABLE RESOURCE RECOVERY TARGET')
initial_errors=query("SELECT COUNT(*) FROM operations_events WHERE kind='error'")[0][0]
def comment():
    return clients['Regular'].post('/create_comment',data={'post_id':public,'content':'DISPOSABLE RESOURCE RECOVERY COMMENT','theme_csrf_token':token},environ_overrides=env)
def assert_private(r):
    check('no-store' in r.headers.get('Cache-Control',''),'Resource response never cached')
    check('/home/sinbot' not in r.get_data(as_text=True),'Resource response excludes internal paths')
    check('database is locked' not in r.get_data(as_text=True),'Raw database diagnostic not exposed')
# A short lock resolves normally through SQLite's existing bounded wait.
locked=sqlite3.connect(app.config['DATABASE']);locked.execute('BEGIN IMMEDIATE')
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(comment);time.sleep(.25);locked.rollback();locked.close();r=future.result(timeout=15)
check(r.status_code==201,'Short lock still saves exactly once')
# A prolonged real lock now returns 503, without retrying the write.
count_before=query('SELECT COUNT(*) FROM comments WHERE post_id=?',(pid,))[0][0]
locked=sqlite3.connect(app.config['DATABASE']);locked.execute('BEGIN IMMEDIATE')
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(comment);time.sleep(5.6);locked.rollback();locked.close();r=future.result(timeout=15)
check(r.status_code==503,'Real prolonged lock returns 503');check(r.json['error']=='database_busy','Structured busy response');check(r.headers.get('Retry-After')=='3','Busy response supplies retry timing');assert_private(r)
check(query('SELECT COUNT(*) FROM comments WHERE post_id=?',(pid,))[0][0]==count_before,'Failed comment not partly saved')
check(comment().status_code==201,'Writing recovers after lock release')
check(query('SELECT COUNT(*) FROM comments WHERE post_id=?',(pid,))[0][0]==count_before+1,'Recovery creates one comment, with no automatic duplicate')
# Fill only the copied database's page quota.
with app.app_context():
    db=core.get_db();db.execute('CREATE TABLE resource_padding(blob BLOB)');db.commit();normal_limit=db.execute('PRAGMA max_page_count').fetchone()[0];cap=db.execute('PRAGMA page_count').fetchone()[0]+3;db.execute('PRAGMA max_page_count='+str(cap))
    for i in range(1024):
        try:db.execute('INSERT INTO resource_padding VALUES (zeroblob(4096))');db.commit()
        except sqlite3.DatabaseError as error:check('full' in str(error),'Actual SQLite FULL reproduced');db.rollback();break
    else:raise AssertionError('Database quota not exhausted')
def cap_connection():core.get_db().execute('PRAGMA max_page_count='+str(cap))
app.before_request_funcs.setdefault(None,[]).insert(0,cap_connection)
full_text='DISPOSABLE FULL STORAGE '+''.join(random.Random(44).choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',k=1800))
before_posts=query('SELECT COUNT(*) FROM posts')[0][0]
r=clients['Regular'].post('/create_post',data={'content':full_text,'vibes':'VM Fixture One','circle':'public','target_user_id':str(users['Regular']),'theme_csrf_token':token},environ_overrides=env)
app.before_request_funcs[None].remove(cap_connection)
check(r.status_code==507,'Actual full database returns 507');check('storage is full' in r.get_data(as_text=True),'Storage failure described clearly');assert_private(r)
check(query('SELECT COUNT(*) FROM posts')[0][0]==before_posts,'Full-database post transaction rolled back')
with app.app_context():
    db=core.get_db();db.execute('PRAGMA max_page_count='+str(normal_limit));db.execute('DROP TABLE resource_padding');db.commit()
r=clients['Regular'].post('/create_post',data={'content':'DISPOSABLE STORAGE RECOVERY POST','vibes':'VM Fixture One','circle':'public','target_user_id':str(users['Regular']),'theme_csrf_token':token},environ_overrides=env)
check(r.status_code==302 and bool(query("SELECT 1 FROM posts WHERE content='DISPOSABLE STORAGE RECOVERY POST'")),'Posting recovers after storage restored')
# Deliberately leave a partial file before ENOSPC; only that upload must be removed.
buffer=io.BytesIO();image=Image.new('RGB',(10,10),'blue');image.save(buffer,'PNG');raw=buffer.getvalue();image.close()
media_dir=Path(app.instance_path)/'media';media_dir.mkdir(parents=True,exist_ok=True);sentinel=media_dir/'existing-user-upload.webp';sentinel.write_bytes(b'existing user content')
upload_writers=importlib.import_module(package+'.storage_writers')
original_fdopen=upload_writers.os.fdopen
class PartialOutput:
    def __init__(self,handle,number):self.handle=handle;self.number=number
    def __enter__(self):return self
    def __exit__(self,*args):self.handle.close()
    def write(self,data):
        self.handle.write(data[:4]);raise OSError(self.number,'Sensitive fixture path must not leak')
def partial_fdopen(descriptor,mode='r',*args,**kwargs):
    handle=original_fdopen(descriptor,mode,*args,**kwargs)
    return PartialOutput(handle,number) if mode=='wb' else handle
for number in {errno.ENOSPC,getattr(errno,'EDQUOT',errno.ENOSPC)}:
    with patch.object(upload_writers.os,'fdopen',partial_fdopen):
        r=clients['Regular'].post('/resource-test/image',data={'image':(io.BytesIO(raw),'fixture.png'),'theme_csrf_token':token},headers={'Accept':'application/json'},environ_overrides=env)
    check(r.status_code==507 and r.json['error']=='storage_full','Filesystem full/quota reaches storage response');check(set(media_dir.iterdir())=={sentinel},'Partial upload removed without deleting existing content');assert_private(r)
# Invalid image behavior stays a validation error.
r=clients['Regular'].post('/resource-test/image',data={'image':(io.BytesIO(b'not an image'),'bad.png'),'theme_csrf_token':token},environ_overrides=env)
check(r.status_code==400,'Invalid image remains 400')
r=clients['Regular'].post('/upload_avatar',data={'avatar':(io.BytesIO(raw),'avatar.png'),'profile_edit_token':token,'theme_csrf_token':token},environ_overrides=env);check(r.status_code==302,'Normal avatar still saves')
from urllib.parse import urlsplit
avatar_url=query('SELECT avatar_path FROM users WHERE id=?',(users['Regular'],))[0][0]
avatar=Path(app.config['UPLOAD_FOLDER'])/'avatars'/Path(urlsplit(avatar_url).path).name;before_avatar=avatar.read_bytes()
number=errno.ENOSPC
with patch.object(upload_writers.os,'fdopen',partial_fdopen):
    r=clients['Regular'].post('/upload_avatar',data={'avatar':(io.BytesIO(raw),'avatar.png'),'profile_edit_token':token,'theme_csrf_token':token},environ_overrides=env)
check(r.status_code==507,'Avatar storage failure returns 507');check(avatar.read_bytes()==before_avatar,'Existing avatar preserved');check(set(avatar.parent.iterdir())=={avatar},'Failed new avatar file removed')
# Classification stays narrow: unrelated failures retain the existing diagnostics.
for code,expected in [(sqlite3.SQLITE_BUSY,'database_busy'),(sqlite3.SQLITE_LOCKED,'database_busy'),(sqlite3.SQLITE_FULL,'storage_full'),(sqlite3.SQLITE_BUSY | 512,'database_busy'),(sqlite3.SQLITE_IOERR,None),(sqlite3.SQLITE_ERROR,None)]:
    error=sqlite3.OperationalError('Internal diagnostic');error.sqlite_errorcode=code;check(recovery.failure_kind(error)==expected,'SQLite primary/extended error classification')
for error in [sqlite3.IntegrityError('unique failure'),OSError(errno.EACCES,'denied'),ValueError('database is locked')]:check(recovery.failure_kind(error) is None,'Unrelated exception not disguised as resource shortage')
check(query("SELECT COUNT(*) FROM operations_events WHERE kind='error'")[0][0]==initial_errors,'Handled resource failures do not attempt database error-event writes')
check(query('PRAGMA quick_check')[0][0]=='ok','Fixture database healthy after all failure cases')
print(checks,'resource recovery checks passed for',package)
