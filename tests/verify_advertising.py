"""T44 direct sponsorship and provider readiness; all writes use disposable fixtures."""
from pathlib import Path
import sys,importlib,tempfile
stage=Path(sys.argv[2]);bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone',1)[0]
exec(compile(bootstrap,'advertising_fixture','exec'))
ads=importlib.import_module(package+'.advertising')
change('DELETE FROM ad_events');change('DELETE FROM ad_campaigns');change('DELETE FROM ad_management_events')
check(get('Regular','/advertising').status_code==200,'Public sponsor policy')
check(b'Sponsor standards' in get('Regular','/advertising').data,'Standards visible')
r=get('Regular','/ads.txt')
check(r.status_code==(404 if mount else 200),'Seller record production only')
if not mount:
 check(r.data==b'google.com, pub-6365201061952837, DIRECT, f08c47fec0942fa0\n','Exact authorized seller record')
 check(r.content_type.startswith('text/plain'),'Seller record plain text')
else:check(get('Regular','/advertising').headers.get('X-Robots-Tag')=='noindex, nofollow','Sandbox noindex retained')
for path in ['/feed','/advertising','/guide']:
 r=get('Regular',path);check(b'adsbygoogle' not in r.data,'No third-party ad script '+path)
 check((b'google-adsense-account' in r.data)==(not bool(mount)),'Provider meta scoped '+path)
for value in ['javascript:alert(1)','data:text/html,x','https://good.example@evil.example','https://example.invalid\r\nX-Test:x','https://[','https://example.invalid:bad','https://example.invalid\\evil','//example.invalid']:
 check(not ads.destination(value),'Reject invalid destination '+repr(value))
check(ads.destination('https://example.invalid/path?q=ok'),'Valid HTTPS destination')
for value in ['/static/../private.png','/static/%2e%2e/private.png','//evil.example/x.png','https://evil.example/x.png','/static/ads/a.svg','/static/ads/a.png?x=1','/static/ads/missing.png']:
 check(not ads.image(value,app.static_folder),'Reject unsafe/missing artwork '+value)
check(ads.image('',app.static_folder),'Image optional')
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'ads';p.mkdir();(p/'fictional.png').write_bytes(b'fictional local asset')
 check(ads.image('/static/ads/fictional.png',directory),'Existing local raster accepted')
for value in ['9'*500,'0','-1','١','9223372036854775808']:
 check(ads.key(value) is None,'Bounded campaign key')
base={'title':'FICTIONAL sponsor','body':'FICTIONAL only','destination_url':'https://example.invalid/offer','placement':'rail','reason':'FICTIONAL TEST REVIEW','policy_reviewed':'1','theme_csrf_token':token}
def save(who='Owner',**values):
 data=dict(base);data.update(values);return clients[who].post('/manage/ads/save',data=data,environ_overrides=env)
def state(cid,value='1',**values):
 data={'theme_csrf_token':token,'state':value,'reason':'FICTIONAL REVIEW','policy_reviewed':'1'};data.update(values);return clients['Owner'].post('/manage/ads/'+str(cid)+'/state',data=data,environ_overrides=env)
for who in ['Regular','Moderator','Manager']:
 check(save(who).status_code==403,'Unprivileged campaign creation '+who)
check(save(theme_csrf_token='wrong').status_code==400,'Campaign CSRF')
check(save(policy_reviewed='0').status_code==400,'Save requires policy review')
for values in [{'campaign_id':'9'*100},{'vibe_id':'9'*100},{'starts_at':'not-a-date'},{'starts_at':'2026-01-02T00:00','ends_at':'2026-01-01T00:00'},{'image_path':'https://evil.example/a.png'},{'destination_url':'javascript:alert(1)'}]:
 check(save(**values).status_code==400,'Invalid campaign refused '+repr(values))
check(save().status_code==302,'Create reviewed campaign')
cid=query('SELECT max(id) FROM ad_campaigns')[0][0]
check(query('SELECT active FROM ad_campaigns WHERE id=?',(cid,))[0][0]==0,'New campaign paused')
check(state(cid,policy_reviewed='0').status_code==400,'Activation requires policy review')
check(state(cid).status_code==302,'Reviewed activation')
check(query('SELECT reason FROM ad_management_events WHERE campaign_id=? ORDER BY id DESC',(cid,))[0][0].startswith('policy-reviewed; '),'Activation audit records review')
# More than twenty eligible cards must not starve a single banner.
for i in range(30):change("INSERT INTO ad_campaigns(title,body,destination_url,placement,active,created_by) VALUES(?,?,?,'rail',1,1)",('FICTIONAL '+str(i),'fixture','https://example.invalid/offer'))
banner=change("INSERT INTO ad_campaigns(title,body,destination_url,placement,active,created_by) VALUES('FICTIONAL BANNER','fixture','https://example.invalid/banner','banner',1,1)")
scoped=change("INSERT INTO ad_campaigns(title,body,destination_url,placement,active,created_by,vibe_id) VALUES('SCOPED','fixture','https://example.invalid/scoped','banner',1,1,?)",(vid,))
for i in range(15):
 with app.app_context():rail,b=core.ad_selection(core.get_db())
 check(len(rail)==4 and b and b['id']==banner,'Separate bounded inventories')
check(query('SELECT count(*) FROM ad_events')[0][0]==75,'Only rendered selections counted')
cols={x[1] for x in query('PRAGMA table_info(ad_events)')};check(not cols.intersection({'user_id','ip','cookie','session_id'}),'No account/network identifiers in direct events')
change('UPDATE ad_campaigns SET active=0')
check(get('Regular','/ad/'+str(cid)+'/click').status_code==404,'Paused click unavailable')
check(state(cid).status_code==302,'Reactivate')
r=get('Regular','/ad/'+str(cid)+'/click');check(r.status_code==302 and r.location=='https://example.invalid/offer','Active click redirects')
check(r.headers.get('Referrer-Policy')=='no-referrer','Click suppresses referrer')
change("UPDATE ad_campaigns SET ends_at='2000-01-01T00:00' WHERE id=?",(cid,));check(get('Regular','/ad/'+str(cid)+'/click').status_code==404,'Expired click unavailable')
change("UPDATE ad_campaigns SET ends_at=NULL,starts_at='2999-01-01T00:00' WHERE id=?",(cid,));check(get('Regular','/ad/'+str(cid)+'/click').status_code==404,'Future click unavailable')
check(get('Regular','/ad/'+('9'*100)+'/click').status_code==404,'Huge route key is not a server error')
change('UPDATE ad_campaigns SET starts_at=NULL WHERE id=?',(cid,))
r=get('Regular','/feed');check(b'Advertisement:' in r.data and b'rel="sponsored noopener noreferrer"' in r.data and b'referrerpolicy="no-referrer"' in r.data,'Labeled sponsored placement')
check(b'Sponsor standards and disclosures' in get('Owner','/manage/ads').data,'Manager guidance')
check(get('Owner','/manage/ads').data.count(b'name="theme_csrf_token"')==2*len(query('SELECT id FROM ad_campaigns'))+1,'One token per manager form')
print('ADVERTISING CHECKS',checks)
guidance=importlib.import_module(package+'.onboarding_guidance')
change("UPDATE users SET handle='@OriginalHelpLineFixture' WHERE lower(handle)='@helpline'")
helpid=change("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES('@HelpLine','fictional-helpline@example.invalid','!disabled-fixture','1990-01-01',1,CURRENT_TIMESTAMP)")
change("INSERT OR REPLACE INTO age_clocks VALUES(?,'UTC',1)",(helpid,))
roles=[tuple(x) for x in query('SELECT * FROM staff_roles WHERE user_id=?',(helpid,))]
count=query('SELECT count(*) FROM posts WHERE user_id=?',(helpid,))[0][0]
with app.app_context():
 db=core.get_db();db.execute('BEGIN IMMEDIATE');refs=guidance.publish(db,core.identifiers,1);db.commit()
check(len(refs)==4,'Four guidance posts')
with app.app_context():
 db=core.get_db();db.execute('BEGIN IMMEDIATE');again=guidance.publish(db,core.identifiers,1);db.commit()
check(again==refs and query('SELECT count(*) FROM posts WHERE user_id=?',(helpid,))[0][0]==count+4,'Publication idempotent')
check([tuple(x) for x in query('SELECT * FROM staff_roles WHERE user_id=?',(helpid,))]==roles,'No role changes')
for ref in refs:
 check(get('Regular','/posts/'+ref).status_code==200,'Ordinary public guidance adult access')
 check(get('Teen','/posts/'+ref).status_code==404,'Guidance preserves age restrictions')
with app.app_context():
 try:guidance.publish(core.get_db(),core.identifiers,users['Regular']);raise AssertionError('Owner gate')
 except ValueError:check(True,'Owner-only maintenance batch')
check(b'Your welcome friend' in get('Teen','/guide').data,'Shared guide available to teens')
print('P1 GUIDANCE AND ADVERTISING TOTAL',checks)
