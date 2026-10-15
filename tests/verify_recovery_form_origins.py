"""Exercise recovery/email-change browser Origin semantics with disposable data and SMTP."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
from unittest.mock import patch
import contextlib,hashlib,importlib,io,json,os,re,secrets,shutil,sqlite3,sys,tempfile,time
from werkzeug.security import generate_password_hash,check_password_hash

stage=Path(sys.argv[1]);package=stage.name;prefix='NEONREST_PRODUCTION' if package=='neonrest' else 'NEONREST_SANDBOX'
work=tempfile.TemporaryDirectory(prefix='neonrest-recovery-origin-');root=Path(work.name);dbpath=root/'fixture.db'
source=sqlite3.connect('file:/home/sinbot/db/'+package+'.db?mode=ro',uri=True);dest=sqlite3.connect(dbpath);source.backup(dest);source.close();dest.close()
for key,value in {'DATABASE':str(dbpath),'SECRET_FILE':str(root/'secret'),'INSTANCE':str(root/'instance'),'MAIL_QUEUE_DIR':str(root/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[prefix+'_'+key]=value
sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
cf=importlib.import_module(package+'.community_features');verification=importlib.import_module(package+'.email_verification')
app=core.app;app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/',SERVER_NAME='www.neonrest.com');messages=[]
core.mail.send=lambda message:messages.append({'subject':message.subject,'recipients':message.recipients,'body':message.body})
checks=0
def check(ok,label):
    global checks
    assert ok,label
    checks+=1
class Inputs(HTMLParser):
    def __init__(self):super().__init__();self.fields={}
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='input' and values.get('name') and 'value' in values:self.fields[values['name']]=values['value']
def token(page):
    inputs=Inputs();inputs.feed(page.data.decode());value=inputs.fields.get('theme_csrf_token');check(bool(value),'Actual form contains a security token');return value
def link(message):
    value=re.search(r'https://[^\s]+',message['body'])[0];check(urlsplit(value).netloc=='www.neonrest.com','Trusted Production domain retained');return urlsplit(value).path
now=int(time.time());password='Synthetic origin fixture password only';nonce=secrets.token_hex(4)
with app.app_context():
    db=core.get_db();people={}
    for label,verified in [('verify',0),('change',1)]:
        email='origin-'+label+'-'+nonce+'@example.com'
        uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)',('@Origin'+label+nonce,email,generate_password_hash(password,method='pbkdf2:sha256:1000'),'1990-01-01',verified)).lastrowid
        db.execute("INSERT INTO age_clocks(user_id,zone,confirmed) VALUES (?,'America/Los_Angeles',1)",(uid,));people[label]=(uid,email)
    raw='synthetic-reset-'+nonce;db.execute('INSERT INTO password_resets VALUES (?,?,?,0)',(cf.digest(raw),people['verify'][0],now+3600));db.commit()
guest=app.test_client();owner=app.test_client();sid='synthetic-origin-session-'+nonce
with app.app_context():
    db=core.get_db();db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),people['change'][0],now,now,now+3600,'isolated origin test'));db.commit()
with owner.session_transaction() as s:s.update(user_id=people['change'][0],user_handle='@Originchange'+nonce,user_email=people['change'][1],sid=sid,fresh_at=now)
base='https://www.neonrest.com';expected='no-referrer' if '--expect-blocked' in sys.argv else 'same-origin'
routes=[(guest,'/verify-email',{'email':people['verify'][1]}),(guest,'/password-reset',{'email':people['verify'][1]}),(guest,'/password-reset/'+raw,{'new_password':'Synthetic changed fixture password only'}),(owner,'/account/email',{'email':'origin-next-'+nonce+'@example.net'})]
for client,path,data in routes:
    page=client.get(path,base_url=base);check(page.status_code==200,'Form renders '+path);csrf=token(page)
    check(page.headers.get('Referrer-Policy')==expected,'Private form has expected policy '+path)
    check('no-store' in page.headers.get('Cache-Control',''),'Private form is uncached '+path)
    browser_origin='null' if page.headers['Referrer-Policy']=='no-referrer' else base
    if '--expect-blocked' in sys.argv:
        response=client.post(path,data=dict(data,theme_csrf_token=csrf),headers={'Origin':browser_origin},base_url=base)
        check(response.status_code==403,'Valid form blocked by its own browser policy '+path)
    else:
        for origin in ('null','https://foreign.example.invalid','https://www.neonrest.com.attacker.example.invalid'):
            response=client.post(path,data=dict(data,theme_csrf_token=csrf),headers={'Origin':origin,'Referer':base+path},base_url=base)
            check(response.status_code==403,'Origin rejection retained '+path)
        check(client.post(path,data=data,headers={'Origin':base},base_url=base).status_code==400,'CSRF still required '+path)
check(not messages,'Rejected browser forms never send mail')
if '--expect-blocked' in sys.argv:
    print('PRE-FIX RECOVERY ORIGIN PASS',package,checks,'checks; four valid forms reproduce Forbidden; no live changes');sys.exit(0)
page=guest.get('/verify-email',base_url=base);csrf=token(page)
response=guest.post('/verify-email',data={'email':people['verify'][1],'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==200 and len(messages)==1,'Same-origin verification request sends through actual handler');old_link=link(messages[-1])
with patch.object(verification.time,'time',return_value=now+61):
    response=guest.post('/verify-email',data={'email':people['verify'][1],'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==200 and len(messages)==2,'Same-origin resend sends a replacement');new_link=link(messages[-1])
check(old_link!=new_link and guest.get(old_link,base_url=base).status_code==400,'Successfully delivered resend invalidates old link')
check(guest.get(new_link,base_url=base).status_code==200,'Received replacement verification link works')
check(guest.get(new_link,base_url=base).status_code==400,'Verification link is single use')
page=guest.get('/password-reset',base_url=base);csrf=token(page)
response=guest.post('/password-reset',data={'email':people['verify'][1],'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==200 and messages[-1]['subject']=='Reset your Neonrest password','Same-origin reset request sends');reset_link=link(messages[-1])
page=guest.get(reset_link,base_url=base);check(page.status_code==200 and page.headers['Referrer-Policy']=='same-origin','Reset confirmation page retains usable browser origin');csrf=token(page)
new_password='Synthetic reset form password only'
response=guest.post(reset_link,data={'new_password':new_password,'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==302 and '/login' in response.location,'Same-origin reset confirmation succeeds')
with app.app_context():check(check_password_hash(core.get_db().execute('SELECT password_hash FROM users WHERE id=?',(people['verify'][0],)).fetchone()[0],new_password),'Disposable password changed by actual reset handler')
check(guest.get(reset_link,base_url=base).status_code==400,'Reset link is single use')
page=owner.get('/account/email',base_url=base);csrf=token(page);next_email='origin-next-'+nonce+'@example.net'
response=owner.post('/account/email',data={'email':next_email,'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==302 and messages[-1]['subject']=='Confirm your new Neonrest email','Same-origin authenticated email change sends confirmation');change_link=link(messages[-1])
with app.app_context():check(core.get_db().execute('SELECT email FROM users WHERE id=?',(people['change'][0],)).fetchone()[0]==people['change'][1],'Current address preserved before confirmation')
page=owner.get(change_link,base_url=base);check(page.status_code==200 and page.headers['Referrer-Policy']=='same-origin','Email confirmation uses same-origin policy');csrf=token(page)
check(owner.post(change_link,data={'theme_csrf_token':csrf},headers={'Origin':'null'},base_url=base).status_code==403,'Null origin still rejects email confirmation')
with owner.session_transaction() as s:s['fresh_at']=now-1801
response=owner.post(change_link,data={'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==302 and '/reauth' in response.location,'Email confirmation still requires recent authorization')
with owner.session_transaction() as s:s['fresh_at']=int(time.time())
response=owner.post(change_link,data={'theme_csrf_token':csrf},headers={'Origin':base},base_url=base)
check(response.status_code==302 and '/login' in response.location,'Same-origin email confirmation succeeds')
check(messages[-1]['subject']=='Your Neonrest account email changed' and messages[-1]['recipients']==[people['change'][1]],'Security notice goes to the old address')
with app.app_context():
    db=core.get_db();check(db.execute('SELECT email FROM users WHERE id=?',(people['change'][0],)).fetchone()[0]==next_email,'Only intended disposable address changed')
    check(db.execute('SELECT revoked FROM active_sessions WHERE token_hash=?',(cf.digest(sid),)).fetchone()[0]==1,'Email confirmation revokes existing sessions')
    check(db.execute('SELECT used FROM email_changes WHERE user_id=? ORDER BY id DESC LIMIT 1',(people['change'][0],)).fetchone()[0]==1,'Email confirmation token consumed')
print('RECOVERY FORM ORIGIN PASS',package,checks,'checks; five mail intents and confirmations use disposable data and mocked SMTP only')
