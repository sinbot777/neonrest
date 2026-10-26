"""Storage admission with real global auth and disposable application databases."""
from pathlib import Path
import sys,os,json,subprocess
if len(sys.argv)==2:
 manifest=json.loads(Path(sys.argv[1]).read_text());results={}
 for package,stage in manifest['packages'].items():
  r=subprocess.run(['/home/sinbot/.virtualenvs/neonrest-v081/bin/python',__file__,package,stage],capture_output=True,text=True,timeout=180)
  results[package]={'code':r.returncode,'out':r.stdout[-1000:],'err':r.stderr[-3500:] if r.returncode else ''};print(package,json.dumps(results[package]),flush=True)
 Path(manifest['root'],'storage-full-app-results.json').write_text(json.dumps(results));raise SystemExit(0 if all(x['code']==0 for x in results.values()) else 1)
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T29-')
import smtplib
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No fixture mail'))
smtplib.SMTP_SSL=smtplib.SMTP
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
bootstrap=bootstrap.replace("'MAIL_QUEUE':'0'", "'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')")
exec(compile(bootstrap,'disposable storage bootstrap','exec'))
import io,re,errno
from PIL import Image
from unittest.mock import patch
check(app.config.get('STORAGE_POLICY') is None,'Disposable app never inherits live quota accounting')
storage=importlib.import_module(package+'.storage_uploads');media=importlib.import_module(package+'.media_features');writers=importlib.import_module(package+'.storage_writers');res=importlib.import_module(package+'.storage_reservations')
ledgerpath=w/'ledger.sqlite';db=sqlite3.connect(ledgerpath);res.Ledger(db,res.Limits(300000,1000000)).initialize();db.close();ledgerpath.chmod(0o600)
app.config.update(STORAGE_POLICY={'ledger':str(ledgerpath),'per_owner':300000,'aggregate':1000000,'account_root':str(w),'provider_quota':1024*1024*1024,'headroom':32*1024*1024},UPLOAD_FOLDER=str(w/'uploads'))
expected='sandbox' if package=='neonrest_sandbox' else 'production';check(app.config['STORAGE_ENVIRONMENT']==expected,'Explicit environment namespace')
check(Path(core.DATABASE)==w/'fixture.db','Disposable database')
check(get('Regular','/account/storage').status_code==200,'Own usage page')
check(get('Regular','/manage/storage').status_code==403,'Ordinary account cannot inspect aggregate')
check(get('Owner','/manage/storage').status_code==200,'Fresh owner aggregate review')
with clients['Owner'].session_transaction() as session:session['fresh_at']=now-1900
check(get('Owner','/manage/storage').status_code==302,'Stale staff confirmation must renew')
check(app.test_client().get('/account/storage',environ_overrides=env).status_code in (302,401),'Anonymous usage denied')
check('no-store' in get('Regular','/account/storage').headers.get('Cache-Control',''),'Private usage no-store')
def png():
 b=io.BytesIO();Image.new('RGB',(64,64),'purple').save(b,'PNG');b.seek(0);return b
get('Regular','/account')
with clients['Regular'].session_transaction() as session:ptoken=session['profile_edit_token']
def avatar():return clients['Regular'].post('/upload_avatar',data={'theme_csrf_token':token,'profile_edit_token':ptoken,'avatar':(png(),'test.png')},environ_overrides=env)
response=avatar();check(response.status_code==302,'Avatar upload through real route')
old=query('SELECT avatar_path FROM users WHERE id=?',(users['Regular'],))[0][0]
oldpath=Path(app.config['UPLOAD_FOLDER'])/'avatars'/old.split('/')[-1].split('?')[0];check(oldpath.is_file(),'New unique avatar stored')
raw=oldpath.read_bytes();check(b'test.png' not in get('Regular','/account/storage').data,'No filenames in usage UI')
with sqlite3.connect(ledgerpath) as db:own=db.execute('SELECT owner FROM upload_objects').fetchone()[0]
check(own==expected+':user:'+str(users['Regular']),'Charge accountable uploader')
app.config['STORAGE_POLICY']['per_owner']=8192
response=avatar();check(response.status_code==413,'Quota denies replacement')
check(query('SELECT avatar_path FROM users WHERE id=?',(users['Regular'],))[0][0]==old and oldpath.read_bytes()==raw,'Denial preserves prior avatar bytes and reference')
app.config['STORAGE_POLICY']['per_owner']=300000
with patch.object(storage,'allocated_tree',return_value=1024*1024*1024):response=avatar()
check(response.status_code==507,'Provider headroom fails with recoverable response')
check(oldpath.read_bytes()==raw,'Headroom failure preserves prior avatar')
# An explicitly inherited policy path still cannot attach a fixture to live accounting.
from flask import Flask
fixture_policy=w/'inherited-policy.json';fixture_policy.write_text(json.dumps(app.config['STORAGE_POLICY']));fixture_policy.chmod(0o600)
isolated=Flask('storage-isolation',root_path=str(stage),instance_path=str(w/'other-instance'));isolated.config['DATABASE']=str(w/'other-fixture.db')
with patch.dict(os.environ,{'NEONREST_STORAGE_POLICY':str(fixture_policy)}):storage.register(isolated,object())
check(isolated.config.get('STORAGE_POLICY') is None,'Inherited policy path cannot connect a disposable app to deployment accounting')

# All GIF derivatives are admitted together before the first output.
gif=io.BytesIO();Image.new('RGB',(16,16),'red').save(gif,'GIF',save_all=True,append_images=[Image.new('RGB',(16,16),'blue')],duration=100)
from werkzeug.datastructures import FileStorage
with app.test_request_context('/create_post',environ_overrides=env):
 session=__import__('flask').session;session['user_id']=users['Regular']
 item=media._save_image(FileStorage(stream=io.BytesIO(gif.getvalue()),filename='fixture.gif'),'Fixture','original','Fixture')
check(all((w/'instance/media'/item[k]).is_file() for k in ['filename','poster','loop_filename']),'Three GIF outputs accounted')
with sqlite3.connect(ledgerpath) as db:
 count=db.execute('SELECT COUNT(*) FROM upload_objects').fetchone()[0];check(count==4,'Avatar and all three derivatives settled')
# A denied complete GIF batch cannot leave a poster behind.
app.config['STORAGE_POLICY']['per_owner']=8192
before=set((w/'instance/media').iterdir())
with app.test_request_context('/create_post',environ_overrides=env):
 __import__('flask').session['user_id']=users['Regular']
 try:media._save_image(FileStorage(stream=io.BytesIO(gif.getvalue()),filename='denied.gif'),'Fixture','original','Fixture');raise AssertionError('Denied GIF succeeded')
 except __import__('werkzeug').exceptions.RequestEntityTooLarge:pass
check(set((w/'instance/media').iterdir())==before,'Denied GIF leaves no partial output')
app.config['STORAGE_POLICY']['per_owner']=300000
# Invalid second attachment cannot leave an already-encoded first attachment.
before=set((w/'instance/media').iterdir())
with app.test_request_context('/create_post',data={'post_image':(png(),'first.png'),'post_midi':(io.BytesIO(b'INVALID'),'second.mid')},environ_overrides=env):
 __import__('flask').session['user_id']=users['Regular']
 try:media.prepare_post_media();raise AssertionError('Invalid MIDI accepted')
 except __import__('werkzeug').exceptions.BadRequest:pass
check(set((w/'instance/media').iterdir())==before,'Invalid second attachment leaves no first attachment file')

# Multipart input is memory-backed: no unreserved upload spool file.
with app.test_request_context('/upload_avatar',data={'avatar':(png(),'input.png')},environ_overrides=env):
 upload=__import__('flask').request.files['avatar'];check(isinstance(upload.stream,writers.BoundedBuffer),'Incoming file parser cannot spool onto disk')
# Shared upload lock and an uncertain capacity scan fail without file writes.
import fcntl
with ledgerpath.with_suffix('.upload-lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);response=avatar()
check(response.status_code==503,'Concurrent uploader receives retry guidance')
with patch.object(storage,'allocated_tree',side_effect=OSError(errno.EIO,'uncertain')):response=avatar()
check(response.status_code==503,'Incomplete capacity scan cannot admit output')
with sqlite3.connect(ledgerpath) as busy:
 busy.execute('BEGIN IMMEDIATE');response=avatar();busy.rollback()
check(response.status_code==503,'Busy accounting ledger preserves upload state')

# Fault in output fsync goes through the actual route/global 507 handler.
with patch.object(writers.os,'fsync',side_effect=OSError(errno.ENOSPC,'full')):response=avatar()
check(response.status_code==507,'Real avatar route ENOSPC recovery')
check(query('SELECT avatar_path FROM users WHERE id=?',(users['Regular'],))[0][0]==old,'ENOSPC preserves old reference')
check(oldpath.read_bytes()==raw,'ENOSPC preserves old file')
with sqlite3.connect(ledgerpath) as db:check(db.execute("SELECT COUNT(*) FROM upload_reservations WHERE state IN ('reserved','writing')").fetchone()[0]==0,'Certain cleanup reconciles only its own failed write')
check(get('Writer','/account/storage',owner=own).status_code==200 and b'0.0 MiB' in get('Writer','/account/storage',owner=own).data,'Owner query parameter cannot reveal another account usage')
export=clients['Regular'].post('/account/export',data={'theme_csrf_token':token},environ_overrides=env)
check(export.status_code==200 and export.json['attachment_storage']['used']>0,'Own export includes accounted usage')
check(set(export.json['attachment_storage'])=={'enabled','used','limit'},'Usage export excludes object keys and provider paths')
print(json.dumps({'checks':checks,'passed':True,'scope':'actual app, disposable database and files'}))

with clients['Owner'].session_transaction() as session:session['fresh_at']=now;session['factor_at']=now
models={'account':get('Regular','/account/storage').get_data(as_text=True),'staff':get('Owner','/manage/storage').get_data(as_text=True)}
(stage.parent/('storage-browser-'+package+'.json')).write_text(json.dumps(models))
