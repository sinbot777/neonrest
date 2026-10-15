"""Login landing/security regressions; disposable source and database only, no SMTP."""
from pathlib import Path
import os,json,time,secrets,contextlib,io
from werkzeug.security import generate_password_hash
root=Path(os.environ['NEONREST_PRIVACY_TEST_WORKDIR'])
env='neonrest_sandbox' if root.name=='PRIVACY-20261014' else 'neonrest'
exec((root/'committed-full-smoke.py').read_text().split('checks=0')[0])
base='https://www.neonrest.com';client=app.test_client();checks=[];password='Fixture-only-password-548!';now=int(time.time());csrf='fixture-login-landing-csrf';secret='JBSWY3DPEHPK3PXP'
def check(value,label):
 assert value,label
 checks.append(label)
with app.app_context():
 db=core.get_db();suffix=secrets.token_hex(4);email='landing-'+suffix+'@example.invalid';handle='@Landing'+suffix
 uid=db.execute("INSERT INTO users(email,handle,password_hash,verified,dob,created_at) VALUES (?,?,?,1,'1985-01-01',CURRENT_TIMESTAMP)",(email,handle,generate_password_hash(password))).lastrowid
 db.execute("INSERT INTO age_clocks(user_id,zone,confirmed) VALUES (?,'UTC',1)",(uid,));db.execute('INSERT INTO account_safety(user_id) VALUES (?)',(uid,));db.commit()
profile='/@'+handle.lstrip('@')
def post(path,data):
 with client.session_transaction() as s:s['theme_csrf_token']=csrf
 return client.post(path,base_url=base,headers={'Origin':base},data=dict(data,theme_csrf_token=csrf))
def clear():
 with client.session_transaction() as s:s.clear()
def valid_session(*,expired=False,revoked=False):
 sid=secrets.token_urlsafe(20)
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,?)',(cf.digest(sid),uid,now,now,now-1 if expired else now+3600,'Disposable landing fixture',int(revoked)));db.commit()
 with client.session_transaction() as s:s.clear();s.update(user_id=uid,user_handle=handle,user_email=email,sid=sid,fresh_at=now,factor_at=now)
 return sid
check(client.get('/login',base_url=base).status_code==200,'Anonymous login form remains available')
response=post('/login',{'email':email,'password':password});check(response.status_code==302 and response.location.endswith(profile),'Password-only success lands on own profile')
check(client.get(profile,base_url=base).status_code==200,'Password-only profile destination opens without a login loop')
response=client.get('/login',base_url=base);check(response.status_code==302 and response.location.endswith(profile),'Signed-in GET login redirects to own profile')
valid_session();response=client.get('/login',base_url=base,environ_overrides={'SCRIPT_NAME':'/sandbox'});check(response.status_code==302 and response.location.endswith('/sandbox'+profile),'Mounted Sandbox profile destination retains prefix')
clear();response=post('/login',{'email':email,'password':'wrong'});check(response.status_code==200 and b'Log In' in response.data,'Wrong password stays on login form')
with app.app_context():
 db=core.get_db();db.execute('UPDATE account_safety SET totp_secret=?,totp_step=-1 WHERE user_id=?',(secret,uid));db.commit()
clear();response=post('/login',{'email':email,'password':password});check(response.status_code==302 and response.location.endswith('/login/verify'),'Enabled factor still requires verification')
with client.session_transaction() as s:check(s.get('pending_login')==uid and not s.get('user_id'),'Pending factor does not create signed-in session')
check(client.get('/login',base_url=base).status_code==200,'Pending factor cannot trigger signed-in redirect')
response=post('/login/verify',{'code':'invalid'});check(response.status_code==200,'Invalid factor does not complete sign-in')
with client.session_transaction() as s:check(not s.get('user_id'),'Invalid factor grants no authenticated session')
response=post('/login/verify',{'code':cf.totp_value(secret,int(time.time())//30)});check(response.status_code==302 and response.location.endswith(profile),'Valid second factor lands on own profile')
check(client.get(profile,base_url=base).status_code==200,'Second-factor profile destination opens without a login loop')
response=client.get('/login',base_url=base);check(response.status_code==302 and response.location.endswith(profile),'Completed factor session cannot remain on login form')
valid_session(expired=True);check(client.get('/login',base_url=base).status_code==200,'Expired session returns login form')
with client.session_transaction() as s:check(not s.get('user_id'),'Expired session identity is cleared')
valid_session(revoked=True);check(client.get('/login',base_url=base).status_code==200,'Revoked session returns login form')
with client.session_transaction() as s:check(not s.get('user_id'),'Revoked session identity is cleared')
valid_session()
with app.app_context():
 db=core.get_db();db.execute('UPDATE account_safety SET inactive=1 WHERE user_id=?',(uid,));db.commit()
response=client.get('/login',base_url=base);check(response.status_code==302 and response.location.endswith('/account/data'),'Inactive account retains account-data landing')
with app.app_context():
 db=core.get_db();db.execute('UPDATE account_safety SET inactive=0 WHERE user_id=?',(uid,));db.execute('INSERT INTO user_moderation(user_id,banned) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET banned=1',(uid,));db.commit()
response=client.get('/login',base_url=base);check(response.status_code==403,'Existing restricted-account gate remains enforced')
print('LOGIN LANDING PASS',env,len(checks),'checks; disposable database only; SMTP disabled')
Path('/home/sinbot/releases/LOGIN-LANDING-20261015/'+env+'-checks.json').write_text(json.dumps({'environment':env,'checks':checks,'count':len(checks),'isolated_database':True,'smtp_disabled':True},indent=2))
