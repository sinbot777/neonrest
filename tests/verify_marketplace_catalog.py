from pathlib import Path
import sys,os,json,smtplib,importlib,io,sqlite3
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Fixture SMTP disabled'));smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T31-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0];exec(compile(bootstrap,'catalog isolated bootstrap','exec'))
studio=importlib.import_module(package+'.seller_studio');pages=importlib.import_module(package+'.identity_pages');catalog=importlib.import_module(package+'.marketplace_catalog');orders=importlib.import_module(package+'.marketplace_orders')
import urllib.request,requests
def no_network(*a,**k):raise AssertionError('Provider network forbidden')
urllib.request.urlopen=no_network;requests.sessions.Session.request=no_network
def post(who,path,**data):return clients[who].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def form(**extra):return {'title':'Fictional handmade pin','kind':'physical','description':'Only a fictional fixture','price':'4.50','quantity':'2',**extra}
guest=app.test_client();r=guest.get('/marketplace',environ_overrides=env)
check(r.status_code==200 and b'Search listings' in r.data,'Public listing browser')
check(b'Create a listing' in get('Regular','/marketplace').data,'Direct create-listing entry')
check(get('Regular','/marketplace/listings/new').status_code==200,'Direct listing form without shop')
check(get('Teen','/marketplace/listings/new').status_code==403,'Minor seller gate')
check(guest.get('/marketplace/listings/new',environ_overrides=env).status_code in (302,401),'Profile required')
check(post('Regular','/marketplace/listings/new',**form(price='bad')).status_code==400,'Invalid listing rejected')
check(query('SELECT COUNT(*) FROM seller_shops WHERE owner_id=?',(users['Regular'],))[0][0]==0,'Invalid form leaves no empty shop')
r=post('Regular','/marketplace/listings/new',**form());check(r.status_code==302,'Create listing directly from Marketplace');path=r.location.removeprefix(mount);listing=path.rsplit('/',1)[-1];shop=query('SELECT shop_id FROM seller_listings WHERE id=?',(listing,))[0][0]
check(query('SELECT identity_kind FROM seller_shops WHERE page_id=?',(shop,))[0][0]=='personal','Default personal profile')
check(query('SELECT COUNT(*) FROM identity_pages WHERE owner_id=?',(users['Regular'],))[0][0]==0,'No Page required or created')
check(b'Fictional handmade pin' not in guest.get('/marketplace',environ_overrides=env).data,'Private drafts never enter discovery')
check(guest.get('/marketplace/listings/'+listing,environ_overrides=env).status_code==404,'Private draft detail unavailable')
check(post('Regular','/marketplace/listings/new',**form(title='Second personal fixture')).status_code==302,'Second direct listing')
check(query('SELECT COUNT(*) FROM seller_shops WHERE owner_id=?',(users['Regular'],))[0][0]==1,'Personal shop reused')
with app.app_context():
 db=core.get_db();creative=pages.create(db,users['Regular'],'creative','catalog-creative','Creative fixture');business=pages.create(db,users['Regular'],'business','catalog-business','Business fixture');foreign=pages.create(db,users['Writer'],'creative','catalog-foreign','Foreign fixture');db.commit()
for p in (creative,business):check(post('Regular','/marketplace/listings/new',**form(listing_identity='page:'+p)).status_code==302,'Optional owned Page listing association')
check(post('Regular','/marketplace/listings/new',**form(listing_identity='page:'+foreign)).status_code==404,'Cannot claim foreign Page')
check(post('Regular','/marketplace/listings/new',**form(listing_identity='untrusted')).status_code==400,'Malformed identity rejected')
check(clients['Regular'].post('/marketplace/listings/new',data=form(),environ_overrides=env).status_code==400,'Direct create CSRF')
# Explicit trusted fixture grants only; normal seller POST has no publication action.
check(post('Regular',path,action='publish',revision='0').status_code==403,'No seller publication endpoint')
with app.app_context():
 db=core.get_db();db.execute('INSERT INTO marketplace_publications(listing_id,listing_revision,published_at) VALUES (?,0,100)',(listing,));
 ids=[listing]
 for title,price,stamp in [('Newest fixture',250,300),('Literal 100%_ fixture',850,200)]:
  from werkzeug.datastructures import MultiDict
  lid=studio.save_listing(db,users['Regular'],shop,MultiDict(form(title=title,price=str(price/100))));db.execute('INSERT INTO marketplace_publications(listing_id,listing_revision,published_at) VALUES (?,0,?)',(lid,stamp));ids.append(lid)
 db.commit()
for sort,expected in [('newest',ids[1]),('oldest',listing),('price_low',ids[1]),('price_high',ids[2]),('best_selling',ids[1])]:
 with app.app_context():result=catalog.browse(core.get_db(),None,sort=sort)
 check(result['items'][0]['id']==expected,'Deterministic '+sort+' order')
 check(get('Regular','/marketplace',sort=sort).status_code==200,'Sort control '+sort)
check(b'No verified Neonrest sales' in guest.get('/marketplace?sort=best_selling',environ_overrides=env).data,'Honest best-selling fallback')
for term,expected in [('NEWEST',1),('100%_',1),('not-a-match',0),("' OR 1=1 --",0)]:
 with app.app_context():rows=catalog.browse(core.get_db(),None,term)['items']
 check(len(rows)==expected,'Literal bounded search '+term)
for params in [{'sort':'sql'},{'q':'x'*121},{'page':'0'},{'page':'9'*5000},{'q':'\x7f'}]:check(get('Regular','/marketplace',**params).status_code==400,'Invalid discovery input')
public='/marketplace/listings/'+listing;check(guest.get(public,environ_overrides=env).status_code==200,'Reviewed preview detail')
check(get('Teen',public).status_code==404,'Signed-in minor cannot read adult seller preview')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Writer'],users['Regular']))
check(get('Writer',public).status_code==404,'Blocked preview denied');change('DELETE FROM user_blocks WHERE user_id=?',(users['Writer'],))
change('INSERT INTO user_mutes(user_id,target_id) VALUES (?,?)',(users['Writer'],users['Regular']))
check(get('Writer',public).status_code==404,'Muted seller omitted');change('DELETE FROM user_mutes WHERE user_id=?',(users['Writer'],))
# Public images require individual grant; product downloads are never made public.
res=importlib.import_module(package+'.storage_reservations');ledger=w/'catalog-ledger.sqlite';sqlite3.connect(ledger).close();limits=res.Limits(16*1024**2,24*1024**2);book=res.connect(ledger,limits);book.initialize();book.db.close();app.config['STORAGE_POLICY']={'ledger':str(ledger),'account_root':str(w),'per_owner':limits.per_owner,'aggregate':limits.aggregate,'provider_quota':1024**3,'headroom':32*1024**2,'ready':True}
from PIL import Image
out=io.BytesIO();Image.new('RGB',(100,80),'green').save(out,'PNG')
r=clients['Regular'].post(path+'/assets',data={'theme_csrf_token':token,'revision':'0','kind':'image','product_file':(io.BytesIO(out.getvalue()),'fictional.png')},environ_overrides=env);check(r.status_code==302,'Private product image upload')
asset=query('SELECT id FROM seller_assets WHERE listing_id=?',(listing,))[0][0];image=public+'/images/'+asset
check(guest.get(public,environ_overrides=env).status_code==404,'Revision change invalidates public grant')
change('UPDATE marketplace_publications SET listing_revision=1 WHERE listing_id=?',(listing,))
check(guest.get(image,environ_overrides=env).status_code==404,'Unapproved image remains private')
change('UPDATE marketplace_publications SET image_ids=? WHERE listing_id=?',(json.dumps([asset]),listing))
r=guest.get(image,environ_overrides=env);check(r.status_code==200 and r.mimetype=='image/webp','Approved processed image public')
check('no-store' in r.headers['Cache-Control'] and r.headers['X-Content-Type-Options']=='nosniff','Revocable image headers')
check(get('Teen',image).status_code==404,'Image age boundary')
check(guest.get(public+'/images/foreign',environ_overrides=env).status_code==404,'Foreign asset denied')
change("UPDATE marketplace_publications SET state='withdrawn' WHERE listing_id=?",(listing,))
check(guest.get(image,environ_overrides=env).status_code==404,'Withdrawal revokes image');change("UPDATE marketplace_publications SET state='active' WHERE listing_id=?",(listing,))
# A trusted owner comp must not be forgeable by ordinary forms or follow a new owner.
q=post('Regular',path+'/checkout-preview',revision='1',quantity='1',variant='base',platform_fees_waived='1');check(q.status_code==302,'Normal quote created')
snap=json.loads(query('SELECT snapshot FROM seller_test_quotes WHERE listing_id=? ORDER BY created_at DESC,id DESC',(listing,))[0][0]);check(snap['quote']['platform_fee']==27,'Form cannot forge fee comp')
change('INSERT INTO marketplace_shop_benefits VALUES (?,?,1,?,?)',(shop,users['Regular'],'Fictional owner comp fixture',now))
with app.app_context():
 db=core.get_db();s=db.execute('SELECT * FROM seller_shops WHERE page_id=?',(shop,)).fetchone();check(catalog.shop_quote(db,s,450,'physical')['platform_fee']==0,'Owner comp fee zero');wrong=dict(s);wrong['owner_id']=users['Writer'];check(catalog.shop_quote(db,wrong,450,'physical')['platform_fee']==27,'Comp does not follow other owner');check(studio.export_user(db,users['Regular'])['fee_benefits'][0]['shop_id']==shop,'Comp included in owner export')
check(not query('PRAGMA foreign_key_check'),'Catalog/comp foreign keys')
print(json.dumps({'checks':checks,'passed':True,'scope':'disposable discovery, direct listing creation, public-image grants, privacy and owner comp'}))
