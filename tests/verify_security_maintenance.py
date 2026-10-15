"""Regression checks against actual staged app code and private disposable state."""
from pathlib import Path
import ast,base64,contextlib,importlib,io,json,os,re,secrets,sqlite3,sys,tempfile,time
from unittest.mock import patch
from PIL import Image
from cryptography.fernet import Fernet,InvalidToken
import flask,requests
stage=Path(sys.argv[1]).resolve();package=stage.name;env='NEONREST_SANDBOX' if package.endswith('sandbox') else 'NEONREST_PRODUCTION'
work=tempfile.TemporaryDirectory(prefix='security-v081-');root=Path(work.name);dbpath=root/'fixture.db'
src=sqlite3.connect('file:'+os.environ['SECURITY_FIXTURE_DB']+'?mode=ro',uri=True);dst=sqlite3.connect(dbpath);src.backup(dst);src.close();dst.close();dbpath.chmod(0o600)
for k,v in {'DATABASE':str(dbpath),'SECRET_FILE':str(root/'secret'),'INSTANCE':str(root/'instance'),'MAIL_QUEUE_DIR':str(root/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[env+'_'+k]=v
sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
ids=importlib.import_module(package+'.public_ids');friends=importlib.import_module(package+'.routes.friends');app=core.app
app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False);core.mail.send=lambda _:(_ for _ in ()).throw(AssertionError('No SMTP in tests'))
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
check(not app.config['RETENTION_ENABLED'],'Permanent erasure remains disabled')
# Exact token language, including a letter at each boundary.
for i in range(16):check(bool(ids.TOKEN.fullmatch('0'*i+'a'+'0'*(15-i))),'Letter accepted at position '+str(i))
for value in ['', '0'*16, 'a'*15, 'a'*17, 'é'+'0'*15,'a'*16+'\n','!'+'a'*15]:check(not ids.TOKEN.fullmatch(value),'Malformed public ID rejected')
for _ in range(100):
 token=ids.random_token();check(len(token)==16 and token.isascii() and token.isalnum() and any(c.isalpha() for c in token),'Random ID constraints')
start=time.monotonic();check(not ids.TOKEN.fullmatch('0'*1000000+'!'),'Oversized ID rejected');check(time.monotonic()-start<1,'Bounded token matching')
for css in ['body { color: red; }','/* hello */ body {color: red;}','@media (max-width:600px) {body{color:red}}','body {/*a*/color:/*b*/red;}']:
 check(core.valid_profile_css(css),'Safe CSS accepted')
for css in ['/*'+'x'*29998,'body {color:red;/*','*/body{}','@import "bad";','body{background:url(https://evil.invalid/x)}','body{background:u/*x*/rl(data:x)}','</style><script>x</script>','body{color:red;','x'*30001]:check(not core.valid_profile_css(css),'Unsafe or malformed CSS rejected')
start=time.monotonic();core.valid_profile_css('/*'*15000);check(time.monotonic()-start<1,'Linear comment parsing')
# Compare old and new acceptance across synthetic comment placements.
for i in range(80):
 css='body {'+'/* note */'*i+'color:red;}'
 old=re.sub(r'/\*.*?\*/','',css,flags=re.S)
 check(core.strip_css_comments(css)==old,'Comment compatibility')
# Route functions under hostile Referer, independently of before-request gates.
class Result:
 def __init__(self,row):self.row=row
 def fetchone(self):return self.row
class DB:
 def __init__(self,row):self.row=row
 def execute(self,sql,args=()):return Result(None if 'moderated_comments' in sql else self.row)
 def commit(self):pass
prefix='/sandbox' if package.endswith('sandbox') else ''
def context(path,method='GET',data=None):return app.test_request_context(path,method=method,data=data or {},headers={'Referer':'https://evil.invalid/phish'},environ_overrides={'SCRIPT_NAME':prefix})
for kind in ['anonymous','invalid','missing','other-owner','success']:
 with context('/edit_comment/test',method='POST',data={'content':'Updated synthetic comment'}):
  if kind!='anonymous':core.session['user_id']=1
  def decode(_):
   if kind=='invalid':raise ValueError('Synthetic invalid identifier')
   return 1
  row=None if kind=='missing' else {'id':1,'user_id':2 if kind=='other-owner' else 1,'content':'Synthetic','last_edited':None}
  with patch.object(core,'decode_prefixed_id',decode),patch.object(core,'get_db',lambda:DB(row)):
   response=core.edit_comment('test');check(response.status_code==302 and response.location==prefix+'/feed','Safe comment return '+kind)
with context('/delete_comment/test',method='POST'):
 core.session['user_id']=1
 with patch.object(core,'decode_prefixed_id',lambda _:1),patch.object(core,'get_db',lambda:DB({'id':1,'user_id':1})):
  response=core.delete_comment('test');check(response.location==prefix+'/feed','Safe delete return')
for func in [friends.follow,friends.unfollow]:
 with context('/follow/2',method='POST'):
  core.session['user_id']=1
  with patch.object(friends,'get_db',lambda:DB(None)):
   with contextlib.redirect_stdout(io.StringIO()):response=func(2)
   check(response.location==prefix+'/friends','Safe follow/unfollow return')
# Vibe picker only generates URLs for authorized records; no JS navigation sink.
class VibeRows:
 def fetchall(self):return [{'name':'Trusted Vibe'},{'name':'Other Vibe'}]
class VibeDB:
 def execute(self,*args):return VibeRows()
with patch.object(core,'get_db',lambda:VibeDB()),patch.object(core,'can_edit_vibe_settings',lambda uid,v:uid==1 and v['name']=='Trusted Vibe'):
 slug=core.vibe_slug('Trusted Vibe')
 for mode in ['day','night']:
  with context('/themes/edit?vibe='+slug+'&mode='+mode):
   core.session['user_id']=1;response=core.edit_theme_index();check(response.location==prefix+'/themes/edit/'+slug+'/'+mode,'Authorized picker preserves mode')
 for query,uid in [('vibe=https://evil.invalid',1),('vibe=javascript:alert(1)',1),('vibe='+slug+'&mode=javascript:x',1),('vibe='+slug,2)]:
  with context('/themes/edit?'+query):
   core.session['user_id']=uid
   try:core.edit_theme_index()
   except Exception as e:check(getattr(e,'code',None)==404,'Unauthorized or invalid picker rejected')
   else:raise AssertionError('Picker accepted invalid input')
 with context('/themes/edit'):
  core.session['user_id']=1;check(core.edit_theme_index().location.endswith('/'+slug+'/day'),'Default picker behavior retained')
template=(stage/'templates/edit_theme.html').read_text();check('window.location.assign' not in template and 'name="vibe"' in template and 'method="get"' in template,'Native form replaces DOM URL navigation')
for name in app.jinja_env.list_templates():app.jinja_env.get_template(name)
check(True,'All Jinja templates parse')
# Actual library behavior used by uploads, QR and encrypted private state.
for fmt in ['PNG','JPEG','WEBP']:
 buf=io.BytesIO();Image.new('RGB',(20,12),(150,70,20)).save(buf,format=fmt);buf.seek(0)
 with Image.open(buf) as image:image.load();check(image.size==(20,12),'Image round trip '+fmt)
key=Fernet.generate_key();f=Fernet(key);token=f.encrypt(b'synthetic-private-document');check(f.decrypt(token)==b'synthetic-private-document','Encrypted state round trip')
try:f.decrypt(token[:-1]+b'!')
except InvalidToken:check(True,'Tampered encrypted state rejected')
else:raise AssertionError('Tampered cipher accepted')
probe=flask.Flask('cache-check');probe.secret_key='synthetic-cache-test'
@probe.route('/')
def cache_probe():return 'yes' if 'uid' in flask.session else 'no'
with probe.test_client() as client:
 with client.session_transaction() as state:state['uid']=1
 response=client.get('/');check('Cookie' in response.vary,'Flask key-only session access varies by Cookie')
check(requests.Request('GET','https://example.invalid/').prepare().url=='https://example.invalid/','Requests prepares ordinary HTTPS request')
print('V081 SECURITY REGRESSION PASS',package,checks,'checks; disposable state only')
(root/'receipt.json').write_text(json.dumps({'checks':checks,'package':package}))
