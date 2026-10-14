"""Decode the actual enrollment PNG and exercise 2FA only in a disposable DB/source."""
from pathlib import Path
import base64,contextlib,hashlib,hmac,importlib,io,json,os,re,shutil,sqlite3,struct,sys,tempfile,time
from urllib.parse import urlsplit,parse_qs,unquote
from unittest.mock import patch
import cv2,numpy as np
from PIL import Image
from werkzeug.security import generate_password_hash

stage=Path(sys.argv[1]);package=stage.name;issuer='Neonrest Sandbox' if package=='neonrest_sandbox' else 'Neonrest';env='NEONREST_SANDBOX' if package=='neonrest_sandbox' else 'NEONREST_PRODUCTION'
work=tempfile.TemporaryDirectory(prefix='neonrest-qr-check-');root=Path(work.name);dbpath=root/'fixture.db';original_path=os.environ.get('NEONREST_QR_TEST_DB','/home/sinbot/db/'+package+'.db')
src=sqlite3.connect('file:'+original_path+'?mode=ro',uri=True);dest=sqlite3.connect(dbpath);src.backup(dest);src.close();dest.close();dbpath.chmod(0o600)
os.environ.update({env+'_DATABASE':str(dbpath),env+'_SECRET_FILE':str(root/'secret'),env+'_INSTANCE':str(root/'instance'),env+'_MAIL_QUEUE_DIR':str(root/'mail'),env+'_MAIL_QUEUE':'0'});sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
cf=importlib.import_module(package+'.community_features');qr=importlib.import_module(package+'.authenticator_qr')
core.app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False)
if package=='neonrest_sandbox':core.app.config['SESSION_COOKIE_PATH']='/'
core.app.instance_path=str(root/'instance')
core.mail.send=lambda _:(_ for _ in ()).throw(AssertionError('No SMTP in QR checks'))
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def otp(secret,step):
 key=base64.b32decode(secret);digest=hmac.new(key,struct.pack('>Q',step),hashlib.sha1).digest();offset=digest[-1]&15
 return str((struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)
now=int(time.time());csrf='isolated-qr-fixture';password='Synthetic QR fixture password only'
with core.app.app_context():
 d=core.get_db();uid=d.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@QRSetupFixture','qr-setup@example.invalid',generate_password_hash(password,method='pbkdf2:sha256:1000'),'1990-01-01')).lastrowid
 for sid in ('qr-current','qr-other'):d.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'isolated QR fixture'))
 d.commit()
client=core.app.test_client()
with client.session_transaction() as s:s.update(user_id=uid,user_handle='@QRSetupFixture',user_email='qr-setup@example.invalid',sid='qr-current',fresh_at=now,theme_csrf_token=csrf)
page=client.get('/account/security');check(page.status_code==200 and b'Authenticator setup QR code' not in page.data,'No QR before setup starts')
check(core.app.test_client().get('/account/security').status_code==401,'Anonymous enrollment requires login')
check(client.post('/account/security',data={'action':'begin'}).status_code==400,'Begin requires CSRF')
page=client.post('/account/security',data={'action':'begin','theme_csrf_token':csrf});check(page.status_code==200,'Fresh account begins setup')
check('private' in page.headers['Cache-Control'] and 'no-store' in page.headers['Cache-Control'],'Enrollment is private and uncached')
check(page.headers['Referrer-Policy']==('no-referrer' if '--expect-blocked' in sys.argv else 'same-origin'),'Enrollment referrer policy matches the tested checkpoint')
if '--expect-blocked' in sys.argv:
 with client.session_transaction() as state:pending=state['pending_totp']
 browser_origin='null' if page.headers['Referrer-Policy']=='no-referrer' else 'http://localhost'
 response=client.post('/account/security',data={'action':'enable','code':otp(pending,int(time.time())//30),'theme_csrf_token':csrf},headers={'Origin':browser_origin})
 check(browser_origin=='null' and response.status_code==403,'Browser-policy Origin null reproduces Forbidden despite valid CSRF and current authenticator code')
 with core.app.app_context():check(not core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone(),'Rejected enable never activates a factor')
 print('PRE-FIX REPRODUCTION PASS',package,checks,'checks; valid fixture code blocked by Origin null; live data untouched',flush=True)
 sys.exit(0)
match=re.search(rb'<img[^>]*class="authenticator-qr"[^>]*src="(data:image/png;base64,[^"]+)"',page.data);check(bool(match),'QR PNG embedded directly in authenticated HTML')
data_uri=match[1].decode();png=base64.b64decode(data_uri.split(',',1)[1]);image=Image.open(io.BytesIO(png)).convert('RGB')
decoded,points,_=cv2.QRCodeDetector().detectAndDecode(np.asarray(image));check(bool(decoded) and points is not None,'Independent decoder reads enrollment QR')
parts=urlsplit(decoded);parameters=parse_qs(parts.query);check(parts.scheme=='otpauth' and parts.netloc=='totp','QR uses TOTP provisioning format')
check(unquote(parts.path[1:])==issuer+':@QRSetupFixture' and parameters['issuer']==[issuer],'Correct account and environment issuer')
check(parameters['algorithm']==['SHA1'] and parameters['digits']==['6'] and parameters['period']==['30'],'Parameters match the existing verifier')
with client.session_transaction() as s:secret=s['pending_totp']
check(parameters['secret']==[secret],'QR encodes the existing pending key')
check(secret.encode() in page.data and b'<details class="authenticator-fallback">' in page.data,'Manual fallback retained in collapsed details')
check(b'inputmode="numeric"' in page.data and b'Current six-digit code' in page.data,'Numeric confirmation remains accessible')
resized=image.resize((264,264),Image.Resampling.NEAREST);small,_,_=cv2.QRCodeDetector().detectAndDecode(np.asarray(resized));check(small==decoded,'QR decodes at its displayed 280px size including border')
with core.app.app_context():check(not core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone(),'Beginning and rendering never activate a factor')
invalid=client.post('/account/security',data={'action':'enable','code':'invalid','theme_csrf_token':csrf});check(invalid.status_code==200 and data_uri.encode() in invalid.data,'Invalid confirmation preserves pending QR')
with core.app.app_context():check(not core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone(),'Wrong code cannot activate 2FA')
with client.session_transaction() as s:s['fresh_at']=int(time.time())-1801
stale=client.get('/account/security');check(stale.status_code==302 and '/reauth' in stale.location and b'data:image/png' not in stale.data,'Stale authorization cannot view enrollment credentials')
check(client.post('/account/security',data={'action':'enable','code':otp(secret,int(time.time())//30),'theme_csrf_token':csrf}).status_code==302,'Stale authorization cannot activate 2FA')
with client.session_transaction() as s:s['fresh_at']=int(time.time())
from html.parser import HTMLParser
class FormInputs(HTMLParser):
 def __init__(self):super().__init__();self.fields={}
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs)
  if tag=='input' and attrs.get('name') and 'value' in attrs:self.fields[attrs['name']]=attrs['value']
inputs=FormInputs();inputs.feed(page.data.decode());submitted_csrf=inputs.fields.get('theme_csrf_token')
check(submitted_csrf==csrf,'Browser submits the actual rendered hidden security token')
browser_origin='null' if page.headers['Referrer-Policy']=='no-referrer' else 'http://localhost'
check(browser_origin=='http://localhost','Same-origin policy retains the origin for this form submission')
for denied_origin in ('null','https://foreign.example.invalid','http://localhost.attacker.example.invalid'):
 denied=client.post('/account/security',data={'action':'enable','code':otp(secret,int(time.time())//30),'theme_csrf_token':submitted_csrf},headers={'Origin':denied_origin,'Referer':'http://localhost/account/security'})
 check(denied.status_code==403,'Null/foreign/lookalike origins remain forbidden even with valid token and code')
check(client.post('/account/security',data={'action':'enable','code':otp(secret,int(time.time())//30)},headers={'Origin':browser_origin}).status_code==400,'Same-origin does not bypass the security token')
code=otp(secret,int(time.time())//30);enabled=client.post('/account/security',data={'action':'enable','code':code,'theme_csrf_token':submitted_csrf},headers={'Origin':browser_origin});check(enabled.status_code==200,'Browser-policy origin and independently calculated code enable 2FA')
check(b'Authenticator setup QR code' not in enabled.data and secret.encode() not in enabled.data,'Enabled factor is never displayed as an enrollment QR/key')
with client.session_transaction() as s:check('pending_totp' not in s,'Pending key removed after confirmation')
with core.app.app_context():
 d=core.get_db();check(d.execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone()[0]==secret,'Confirmed key bound to the intended account')
 check(not cf.verify_second_factor(d,uid,code),'Confirmed code cannot be reused')
 check(d.execute('SELECT COUNT(*) FROM recovery_codes WHERE user_id=?',(uid,)).fetchone()[0]==10,'Recovery codes remain available')
 check(d.execute('SELECT revoked FROM active_sessions WHERE token_hash=?',(cf.digest('qr-other'),)).fetchone()[0]==1,'Enrollment revokes other sessions')
 check(d.execute('SELECT revoked FROM active_sessions WHERE token_hash=?',(cf.digest('qr-current'),)).fetchone()[0]==0,'Current confirmed session retained')
login=core.app.test_client()
with login.session_transaction() as s:s['theme_csrf_token']=csrf
response=login.post('/login',data={'email':'qr-setup@example.invalid','password':password,'theme_csrf_token':csrf});check(response.status_code==302 and '/login/verify' in response.location,'Password alone still requires the authenticator')
future=int(time.time())//30+2
with login.session_transaction() as s:s['theme_csrf_token']=csrf
with patch.object(cf.time,'time',return_value=future*30):
 response=login.post('/login/verify',data={'code':otp(secret,future),'theme_csrf_token':csrf});check(response.status_code==302 and '/@QRSetupFixture' in response.location,'Next independently generated code completes sign-in')
for invalid_secret in ('', 'not-base32', 'A'*1000):
 try:qr.provisioning_uri(invalid_secret,'@Fixture')
 except ValueError:check(True,'Invalid QR key rejected without rendering')
 else:raise AssertionError('Unsafe key accepted')
escaped=qr.provisioning_uri('JBSWY3DPEHPK3PXP','@<fixture>&/name:one',issuer);check('<' not in escaped and '&/name' not in escaped and '%3C' in escaped and 'name_one' in escaped,'Special labels are encoded and colon ambiguity removed')
(root/'verification.json').write_text(json.dumps({'checks':checks,'package':package,'qr_decoded':True,'real_credentials_changed':False,'smtp_sent':False}));print('QR ORIGIN ENROLLMENT PASS',package,checks,'checks; independent scan/code verification; disposable data only',flush=True)
