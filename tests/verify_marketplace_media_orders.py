from pathlib import Path
import sys,os,json,smtplib,importlib,io,sqlite3,hashlib,zipfile
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Fixture SMTP disabled'));smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T31-media-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0];exec(compile(bootstrap,'isolated marketplace media/order bootstrap','exec'))
import urllib.request,requests
def network_forbidden(*args,**kwargs):raise AssertionError('Provider network forbidden in fixture')
urllib.request.urlopen=network_forbidden;requests.sessions.Session.request=network_forbidden
from PIL import Image
pages=importlib.import_module(package+'.identity_pages');studio=importlib.import_module(package+'.seller_studio');assets=importlib.import_module(package+'.marketplace_assets');orders=importlib.import_module(package+'.marketplace_orders');reservations=importlib.import_module(package+'.storage_reservations')
fixture_path=Path(os.environ.get('NEONREST_STUDIO_FIXTURE','/missing-fixture'))
fixtures=json.loads(fixture_path.read_text()) if fixture_path.is_file() else {'products':[{'title':'Fictional Oregon pin','description':'Fictional private test product','price':'5.50'},{'title':'Fictional book pin','description':'Fictional private test product','price':'4.50'}]}
photo=None
if fixtures.get('photo_paths'):
 for p in fixtures['photo_paths']:
  if Path(p).is_file():photo=Path(p).read_bytes();break
if photo is None:
 out=io.BytesIO();Image.new('RGB',(800,600),(30,150,90)).save(out,'PNG');photo=out.getvalue()
ledger=w/'ledger.sqlite';sqlite3.connect(ledger).close();limits=reservations.Limits(16*1024*1024,24*1024*1024);book=reservations.connect(ledger,limits);book.initialize();book.db.close();app.config['STORAGE_POLICY']={'ledger':str(ledger),'account_root':str(w),'per_owner':limits.per_owner,'aggregate':limits.aggregate,'provider_quota':1024*1024*1024,'headroom':32*1024*1024,'ready':True}
# Only fixture roots are ever scanned/written; no copied live private documents.
app.config['FAMILY_CONSENT_FOLDER']=str(w/'documents');(w/'documents').mkdir();app.static_folder=str(w/'static');(w/'static/uploads').mkdir(parents=True)
with app.app_context():
 db=core.get_db();page=pages.create(db,users['Regular'],'creative','media-order-fixture','Private test product shop');pages.set_member(db,users['Regular'],page,users['Manager'],'manager');studio.create_shop(db,users['Regular'],page);db.commit()
base='/marketplace/studio/'+page

def post(who,path,**data):return clients[who].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def form(product,kind='physical',quantity='2'):
 return {'title':'TEST COPY — '+product['title'],'description':product['description'],'kind':kind,'price':product['price'],'quantity':quantity,'delivery':'TEST TERMS — no sale or shipment','license':'Private testing only','returns':'TEST TERMS — no actual purchase'}
for product in fixtures['products'][:2]:check(post('Regular',base+'/listing/new',**form(product)).status_code==302,'Authorized copied/synthetic product fixture saves')
listing=query('SELECT id FROM seller_listings WHERE shop_id=? ORDER BY created_at,id',(page,))[0][0];path=base+'/listing/'+listing
check(get('Regular',path).status_code==200,'Upload/checkout controls render')
check(b'paid $handle business Page is not required' in get('Regular','/marketplace/studio').data,'Free creative Page selling route is explicit')
check(b'Create a free creative Page for your shop' in get('Regular','/marketplace/studio').data,'Free Page creation remains visible beside existing business Pages')
check(query('SELECT kind FROM identity_pages WHERE id=?',(page,))[0][0]=='creative','Test shop uses free creative Page')
check(query('SELECT COUNT(*) FROM page_subscriptions WHERE owner_id=?',(users['Regular'],))[0][0]==0,'No business subscription needed for product workflow')
def rev():return query('SELECT revision FROM seller_listings WHERE id=?',(listing,))[0][0]
def upload(who='Regular',kind='image',raw=None,name='sample.jpg',revision=None):
 return clients[who].post(path+'/assets',data={'theme_csrf_token':token,'revision':str(rev() if revision is None else revision),'kind':kind,'product_file':(io.BytesIO(photo if raw is None else raw),name)},environ_overrides=env)
r=upload();check(r.status_code==302,'Product image upload');image_id=query("SELECT id FROM seller_assets WHERE listing_id=? AND kind='image'",(listing,))[0][0];image_url=path+'/assets/'+image_id;r=get('Regular',image_url);check(r.status_code==200 and r.mimetype=='image/webp','Protected processed preview')
with Image.open(io.BytesIO(r.data)) as picture:check(max(picture.size)<=1600 and not picture.getexif(),'Resized metadata-free preview')
check('no-store' in r.headers['Cache-Control'] and r.headers['X-Content-Type-Options']=='nosniff','Private image headers');check(get('Writer',image_url).status_code==404,'Other seller image denied');check(app.test_client().get(image_url,environ_overrides=env).status_code in (302,401),'Guest image denied');check(upload('Writer').status_code==404,'Other seller cannot upload');check(upload(raw=b'<svg onload=alert(1)>',name='bad.svg').status_code==400,'SVG/invalid image denied');check(upload(raw=b'x'*(5*1024*1024+1)).status_code==413,'Input byte limit');check(upload(revision=0).status_code==409,'Stale upload revision denied')
# Digital product file and uploader-based export attribution.
check(post('Regular',path,revision=str(rev()),**form(fixtures['products'][0],kind='digital')).status_code==302,'Digital draft ready')
pdf=b'%PDF-1.4\nPRIVATE FIXTURE PRODUCT BY MANAGER\n%%EOF';check(upload('Manager','file',pdf,'fixture.pdf').status_code==302,'Delegate product file upload');file_id=query("SELECT id FROM seller_assets WHERE listing_id=? AND kind='file'",(listing,))[0][0];file_url=path+'/assets/'+file_id;r=get('Regular',file_url);check(r.status_code==200 and r.data==pdf,'Shop owner can read current team upload');check('attachment;' in r.headers['Content-Disposition'] and r.mimetype=='application/octet-stream','Product file download-only');check(upload('Manager','file',pdf,'second.pdf').status_code==409,'One active downloadable file');check(post('Regular',path,revision=str(rev()),**form(fixtures['products'][0],kind='physical')).status_code==409,'Cannot silently turn active digital file into physical listing')
for who,expected in [('Regular',False),('Manager',True)]:
 r=post(who,'/account/export',include_uploads='yes');check(r.status_code==200,'Product uploads export')
 with zipfile.ZipFile(io.BytesIO(r.data)) as archive:joined=b''.join(archive.read(n) for n in archive.namelist());check((pdf in joined)==expected,'Product file follows uploader, not Page ownership')
 r.close()
with app.app_context():
 db=core.get_db();row=db.execute('SELECT * FROM seller_assets WHERE id=?',(file_id,)).fetchone();original_bytes=row['bytes'];key=row['storage_key']
check(post('Regular',file_url+'/archive',revision=str(rev())).status_code==302,'Remove product file from draft');check(get('Regular',file_url).status_code==404,'Removed file no longer served from draft');check((Path(app.instance_path)/'marketplace'/key).is_file(),'Archived bytes retained for export/accounting');check(post('Regular',path,revision=str(rev()),**form(fixtures['products'][0],kind='physical')).status_code==302,'Physical listing after file removal')
# Invalid ZIPs cannot smuggle traversal or symlinks; no extraction occurs.
for bad in [b'not a zip',b'%PDF-no-eof']:
 try:assets.prepare(bad,'bad.zip' if bad.startswith(b'not') else 'bad.pdf','file')
 except studio.StudioError:check(True,'Invalid product format denied')
 else:check(False,'Expected format rejection')
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as z:z.writestr('../escape.txt','bad')
try:assets.prepare(out.getvalue(),'traversal.zip','file')
except studio.StudioError:check(True,'Unsafe ZIP members denied')
else:check(False,'Expected ZIP rejection')
# Two previews may exist, but transactionally only available draft stock can be held.
q1=post('Regular',path+'/checkout-preview',revision=str(rev()),quantity='2');q2=post('Manager',path+'/checkout-preview',revision=str(rev()),quantity='2');check(q1.status_code==302 and q2.status_code==302,'Independent server checkout previews');quote1=q1.location.removeprefix(mount);quote2=q2.location.removeprefix(mount);r=clients['Regular'].get(quote1,environ_overrides=env);check(r.status_code==200 and b'No payment will be collected' in r.data,'Explicit no-charge review');check(b'Shipping and tax are not calculated' in r.data,'No false final total');check(get('Writer',quote1).status_code==404,'Quote owner isolation');r=post('Regular',quote1,action='test-order');check(r.status_code==302,'Unpaid test order');order_url=r.location.removeprefix(mount);check(post('Regular',quote1,action='test-order').location.removeprefix(mount)==order_url,'Double-click order idempotency');check(post('Manager',quote2,action='test-order').status_code==409,'Concurrent test reservations cannot oversell draft stock');check(query('SELECT quantity FROM seller_listings WHERE id=?',(listing,))[0][0]==2,'Test checkout never decrements saved stock');check(get('Writer',order_url).status_code==404,'Order isolation');check(post('Regular',order_url,action='pay').status_code==403,'No payment transition');check(post('Regular',order_url,action='fulfill').status_code==403,'No fulfillment transition');check(post('Regular',order_url,action='cancel').status_code==302,'Cancel test reservation');check(post('Manager',quote2,action='test-order').status_code==302,'Cancellation releases test stock')
with app.app_context():
 db=core.get_db();row=db.execute('SELECT * FROM seller_test_orders ORDER BY created_at,id LIMIT 1').fetchone()
 try:db.execute("UPDATE seller_test_orders SET state='paid' WHERE id=?",(row['id'],))
 except sqlite3.IntegrityError:db.rollback();check(True,'Database cannot record paid state')
 else:check(False,'Paid state must not exist')
 try:db.execute("UPDATE seller_test_orders SET snapshot='{}' WHERE id=?",(row['id'],))
 except sqlite3.IntegrityError:db.rollback();check(True,'Immutable order snapshot')
 else:check(False,'Snapshot must be immutable')
 db.execute('UPDATE seller_test_quotes SET expires_at=0');db.commit()
check(post('Regular',quote1,action='pay').status_code==403,'Forged provider return cannot pay')
# Expired reservation no longer blocks a new test; revoked delegates lose file access.
change('UPDATE seller_test_orders SET state=\'canceled\'');change('DELETE FROM identity_page_members WHERE page_id=? AND user_id=?',(page,users['Manager']));check(get('Manager',image_url).status_code==404,'Revoked delegate media denial')
check(post('Regular',path+'/checkout-preview',revision=str(rev()),quantity='1',variant='²').status_code==400,'Malformed variation input');check(clients['Regular'].post(path+'/checkout-preview',data={'revision':str(rev()),'quantity':'1'},environ_overrides=env).status_code==400,'Checkout CSRF');check(query("SELECT COUNT(*) FROM seller_test_orders WHERE state NOT IN ('test_unpaid','canceled','expired')")[0][0]==0,'Only noncommercial test orders exist')
other_listing=query('SELECT id FROM seller_listings WHERE shop_id=? AND id!=?',(page,listing))[0][0]
with app.app_context():
 db=core.get_db();other_rev=db.execute('SELECT revision FROM seller_listings WHERE id=?',(other_listing,)).fetchone()[0]
 expired_key=orders.create_quote(db,users['Regular'],page,other_listing,other_rev,'base',1,now=now-1000);db.commit()
 try:orders.create_order(db,users['Regular'],page,other_listing,expired_key,now=now)
 except studio.StudioError as error:check(error.status==409,'Expired unused quote cannot create order');db.rollback()
 else:check(False,'Expected expired quote refusal')
check(post('Regular',path+'/checkout-preview',revision=str(rev()),quantity='2').status_code==302,'Canceled/expired test stock available again')
print(json.dumps({'checks':checks,'passed':True,'fixtures':'authorized public listing copies' if fixture_path.is_file() else 'synthetic','scope':'disposable database, ledger and files; no provider calls'}))
