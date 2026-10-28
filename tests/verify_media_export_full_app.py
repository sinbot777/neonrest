from pathlib import Path
import sys,os,json,smtplib,sqlite3,io,zipfile,hashlib,fcntl
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Fixture SMTP disabled'));smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T30-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
exec(compile(bootstrap,'isolated export bootstrap','exec'))
check(app.config.get('STORAGE_POLICY') is None,'No live ledger inherited')
exports=__import__(package+'.media_export',fromlist=['x'])
static=w/'static';uploads=static/'uploads';uploads.mkdir(parents=True);app.static_folder=str(static)
media=Path(app.instance_path)/'media';media.mkdir(parents=True,exist_ok=True);documents=w/'documents';documents.mkdir();app.config['FAMILY_CONSENT_FOLDER']=str(documents)
environment=app.config['STORAGE_ENVIRONMENT'];ledger=w/'ledger.sqlite'
with sqlite3.connect(ledger) as db:
 db.execute('CREATE TABLE upload_objects(object_key TEXT PRIMARY KEY,owner TEXT,bytes INTEGER)')
 db.execute('CREATE TABLE upload_reservations(owner TEXT,state TEXT,reserved INTEGER)')
 for name,uid,content in [('own.png',users['Regular'],b'FICTIONAL OWN UPLOAD'),('foreign.png',users['Writer'],b'FOREIGN PRIVATE UPLOAD'),('unassigned.png',None,b'UNATTRIBUTED PRIVATE UPLOAD')]:
  (uploads/name).write_bytes(content);db.execute('INSERT INTO upload_objects VALUES (?,?,?)',(environment+'-uploads/'+name,environment+':user:'+str(uid) if uid else 'unattributed',len(content)))
 db.execute('INSERT INTO upload_objects VALUES (?,?,?)',(environment+'-media/missing.mid',environment+':user:'+str(users['Regular']),20))
 doc='fictional-private.pdf';(documents/doc).write_bytes(b'%PDF FICTIONAL OWN PRIVATE DOCUMENT')
 change('INSERT INTO family_consent_documents(parent_id,child_id,storage_key,media_type) VALUES (?,?,?,?)',(users['Regular'],users['Teen'],doc,'application/pdf'))
app.config['STORAGE_POLICY']={'ledger':str(ledger),'account_root':str(w),'per_owner':16*1024*1024,'aggregate':24*1024*1024,'provider_quota':1024*1024*1024,'headroom':32*1024*1024,'ready':True}
def export(who='Regular',include=True,csrf=True):
 data={'include_uploads':'yes'} if include else {}
 if csrf:data['theme_csrf_token']=token
 return clients[who].post('/account/export',data=data,environ_overrides=env)
r=export(include=False);check(r.status_code==200 and r.mimetype=='application/json','JSON compatibility');check('password_hash' not in r.get_data(as_text=True),'No password hash')
r=export();check(r.status_code==200 and r.mimetype=='application/zip','Owner ZIP response');check('no-store' in r.headers['Cache-Control'],'Private no-store');check('attachment;' in r.headers['Content-Disposition'],'Download disposition');check(r.headers['X-Content-Type-Options']=='nosniff','No sniff')
with zipfile.ZipFile(io.BytesIO(r.data)) as z:
 blobs=[z.read(n) for n in z.namelist()];joined=b''.join(blobs);manifest=json.loads(z.read('manifest.json'))
 check(b'FICTIONAL OWN UPLOAD' in joined,'Own upload included');check(b'%PDF FICTIONAL OWN PRIVATE DOCUMENT' in joined,'Own private document included');check(b'FOREIGN PRIVATE UPLOAD' not in joined,'Foreign upload excluded');check(b'UNATTRIBUTED PRIVATE UPLOAD' not in joined,'Unattributed file excluded');check(any(f['status']=='missing' for f in manifest['files']),'Missing file disclosed');check(str(w).encode() not in z.read('manifest.json'),'Manifest hides storage paths');check(all(not n.startswith('/') and '..' not in n for n in z.namelist()),'Safe archive paths')
 for f in manifest['files']:
  if f['status']=='included' and not f.get('duplicate'):check(hashlib.sha256(z.read(f['file'])).hexdigest()==f['sha256'],'Round-trip hash')
r.close()
r=export('Writer');check(r.status_code==200,'Independent owner export')
with zipfile.ZipFile(io.BytesIO(r.data)) as z:
 joined=b''.join(z.read(n) for n in z.namelist());check(b'FOREIGN PRIVATE UPLOAD' in joined and b'FICTIONAL OWN UPLOAD' not in joined and b'OWN PRIVATE DOCUMENT' not in joined,'Cross-account byte isolation')
r.close()
check(export(csrf=False).status_code==400,'CSRF required');check(app.test_client().post('/account/export',data={'include_uploads':'yes','theme_csrf_token':token},environ_overrides=env).status_code in (302,400,401),'Guest denied');check(clients['Regular'].get('/account/export',environ_overrides=env).status_code==405,'No GET export')
with clients['Regular'].session_transaction() as s:s['fresh_at']=0
r=export();check(r.status_code==302 and 'reauth' in r.location,'Fresh auth required')
with clients['Regular'].session_transaction() as s:s['fresh_at']=now;s['factor_at']=0
r=export();check(r.status_code==302,'Fresh second factor required')
with clients['Regular'].session_transaction() as s:s['factor_at']=now
with ledger.with_suffix('.upload-lock').open('a+b') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);check(export().status_code==503,'Shared upload/export concurrency gate')
app.config['STORAGE_POLICY']=None;check(export().status_code==503,'No unverified attribution fallback');check(export(include=False).status_code==200,'JSON works without ledger');app.config['STORAGE_POLICY']={'ledger':str(ledger),'account_root':str(w),'per_owner':100,'aggregate':200,'provider_quota':1000,'headroom':100,'ready':False};check(export().status_code==503,'Unready policy denied')
check(export().status_code==429,'Per-account export rate limit')
print(json.dumps({'checks':checks,'passed':True,'scope':'disposable app, private fixture files and fixture ledger'}))
