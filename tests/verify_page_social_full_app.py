"""Extend creative-page full-app acceptance with real guards and disposable DBs."""
from pathlib import Path
import sys,json,subprocess
if len(sys.argv)==2:
 manifest=json.loads(Path(sys.argv[1]).read_text());results={}
 for package,stage in manifest['packages'].items():
  r=subprocess.run(['/home/sinbot/.virtualenvs/neonrest-v081/bin/python',__file__,package,stage],capture_output=True,text=True,timeout=240)
  results[package]={'code':r.returncode,'out':r.stdout[-2000:],'err':r.stderr[-5000:] if r.returncode else ''};print(package,json.dumps(results[package]),flush=True)
 Path(manifest['root'],'next-full-app-results.json').write_text(json.dumps(results));raise SystemExit(0 if all(r['code']==0 for r in results.values()) else 1)
exec(compile(Path(__file__).with_name('verify_identity_pages_full_app.py').read_text(),'creative regression','exec'))
app.config['PAGE_BILLING_MODE']='off'
social=importlib.import_module(package+'.page_social');events=importlib.import_module(package+'.events');billing=importlib.import_module(package+'.page_billing')
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import hmac,hashlib
check(send('Regular','/pages/new',kind='creative',handle='_SocialFixture',name='Social fixture').status_code==302,'Social page creation')
page=query("SELECT * FROM identity_pages WHERE handle='_socialfixture'")[0];ref=page['id'];manage='/pages/'+ref+'/edit'
check(send('Regular',manage,action='state',state='published',revision='0').status_code==302,'Social page published')
check(send('Regular','/pages/'+ref+'/updates',body='SOCIAL UPDATE FIXTURE').status_code==302,'Page update')
check(get('Writer','/pages/explore',q='Social fixture').status_code==200,'Discovery page renders')
check(b'_socialfixture' in get('Writer','/search',q='Social',scope='pages',scopes_present='1').data,'Pages category in global search')
check(send('Writer','/pages/'+ref+'/follow',state='follow').status_code==302,'Follow page')
check(b'SOCIAL UPDATE FIXTURE' in get('Writer','/pages/feed').data,'Followed page update appears')
change('INSERT INTO user_blocks VALUES (?,?,CURRENT_TIMESTAMP)',(users['Regular'],users['Writer']))
check(b'SOCIAL UPDATE FIXTURE' not in get('Writer','/pages/feed').data,'Block removes followed update immediately')
check(b'_socialfixture' not in get('Writer','/search',q='Social',scope='pages',scopes_present='1').data,'Blocked page absent from search')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Regular'],users['Writer']))
check(send('Regular','/pages/'+ref+'/team',handle='@VMFixtureWriter',purpose='editor').status_code==302,'Owner invites editor')
inv=query("SELECT * FROM page_invitations WHERE page_id=? AND purpose='editor'",(ref,))[0]
check(send('Writer','/pages/'+ref+'/updates',body='NO ACCEPTANCE').status_code==403,'Pending invite grants no rights')
check(send('Writer','/pages/invitations',invitation_id=inv['id'],decision='accept').status_code==302,'Recipient accepts invitation')
check(send('Writer','/pages/'+ref+'/updates',body='DELEGATE UPDATE').status_code==302,'Accepted delegate can publish')
check(send('Regular','/pages/'+ref+'/team',action='remove',member_id=str(users['Writer'])).status_code==302,'Owner removes delegate')
check(send('Writer','/pages/'+ref+'/updates',body='REVOKED').status_code==403,'Removal immediately revokes rights')
check(send('Regular','/pages/'+ref+'/team',handle='@VMFixtureWriter',purpose='transfer').status_code==400,'Transfer consequence requires confirmation')
check(send('Regular','/pages/'+ref+'/team',handle='@VMFixtureWriter',purpose='transfer',confirm_transfer='yes').status_code==302,'Confirmed transfer invitation')
inv=query("SELECT * FROM page_invitations WHERE page_id=? AND purpose='transfer' ORDER BY created_at DESC LIMIT 1",(ref,))[0]
check(send('Writer','/pages/invitations',invitation_id=inv['id'],decision='accept').status_code==302,'New owner consents to transfer')
check(query('SELECT owner_id FROM identity_pages WHERE id=?',(ref,))[0][0]==users['Writer'],'Owner changed atomically')
check(send('Regular','/pages/'+ref+'/updates',body='FORMER OWNER').status_code==403,'Prior owner has no automatic access')
check(get('Writer','/events').status_code==200 and get('Writer','/events/new').status_code==200,'Calendar and form render')
start=datetime.now(timezone.utc)+timedelta(days=1);end=start+timedelta(hours=1)
data={'title':'EVENT FIXTURE','description':'<script>event</script>','location':'Fixture only','starts_at':start.isoformat(),'ends_at':end.isoformat(),'zone':'America/Los_Angeles','audience':'public'}
check(send('Writer','/events/new',**data).status_code==302,'Create structured event')
event=query("SELECT * FROM calendar_events WHERE title='EVENT FIXTURE'")[0];eid=event['id']
check(b'&lt;script&gt;event' in get('Regular','/events/'+eid).data,'Event text escaped')
check(send('Regular','/events/'+eid+'/respond',response='going').status_code==302,'Private RSVP')
check(get('Regular','/events/'+eid+'/calendar.ics').status_code==200,'Authorized ICS export')
check(b'BEGIN:VCALENDAR' in get('Regular','/events/'+eid+'/calendar.ics').data,'Valid calendar envelope')
check(send('Regular','/events/'+eid+'/edit',revision='0',action='cancel').status_code==403,'Other user cannot cancel')
check(send('Regular','/events/'+eid+'/report',reason='Fixture event report').status_code==302,'Event report')
report=query('SELECT id FROM calendar_reports ORDER BY id DESC LIMIT 1')[0][0]
check(get('Regular','/manage/events/reports').status_code==403,'Event evidence restricted to staff')
check(send('Admin','/manage/events/reports',report_id=str(report),decision='hide',reason='Fixture moderation').status_code==302,'Staff hides event')
check(get('Regular','/events/'+eid).status_code==404 and get('Regular','/events/'+eid+'/calendar.ics').status_code==404,'Hidden event absent from detail/export')
check(send('Admin','/manage/events/reports',report_id=str(report),decision='restore',reason='Fixture review').status_code==302,'Staff restores event')
check(send('Writer','/events/'+eid+'/edit',revision='2',action='cancel').status_code==302,'Creator cancels with current revision')
check(send('Regular','/events/'+eid+'/respond',response='going').status_code==404,'Canceled event rejects response')
check(send('Teen','/events/new',**{**data,'title':'TEEN EVENT'}).status_code==302,'Eligible teen can create event')
teen=query("SELECT id FROM calendar_events WHERE title='TEEN EVENT'")[0][0]
check(get('Regular','/events/'+teen).status_code==404,'Adult cannot bypass event age boundary')
check(send('Writer','/circles',name='EVENT CIRCLE FIXTURE',description='Private fixture',mode='hidden').status_code==302,'Create Circle for event scope')
circle=query('SELECT * FROM circles WHERE owner_id=? ORDER BY id DESC LIMIT 1',(users['Writer'],))[0]
circle_ids=importlib.import_module(package+'.circle_ids')
with app.app_context():circle_ref=circle_ids.public(core.get_db(),circle['id'])
check(send('Writer','/events/new',**{**data,'title':'CIRCLE EVENT FIXTURE','audience':'circle','circle_id':circle_ref}).status_code==302,'Create private Circle event')
ce=query("SELECT id FROM calendar_events WHERE title='CIRCLE EVENT FIXTURE'")[0][0]
check(get('Regular','/events/'+ce).status_code==404,'Circle event hidden from nonmember')
change("INSERT INTO circle_members VALUES (?,?,'member','active',CURRENT_TIMESTAMP)",(circle['id'],users['Regular']))
check(get('Regular','/events/'+ce).status_code==200,'Eligible current member sees Circle event')
change("UPDATE circle_members SET status='left' WHERE circle_id=? AND user_id=?",(circle['id'],users['Regular']))
check(get('Regular','/events/'+ce+'/calendar.ics').status_code==404,'Membership removal immediately revokes calendar export')
for value in ('2026-03-08T02:30:00','2026-11-01T01:30:00'):
 try:events.stamp(value,'America/Los_Angeles');check(False,'Invalid DST time rejected')
 except pages.PageError:check(True,'Invalid DST time rejected')
# Stripe fixtures: external requests remain forbidden; no keys or real charge.
raw=b'{"id":"evt_Fixture"}';when=str(int(time.time()));secret='whsec_fixture'
signature='t='+when+',v1='+hmac.new(secret.encode(),when.encode()+b'.'+raw,hashlib.sha256).hexdigest()
check(billing.verify_signature(raw,signature,secret),'Stripe signature accepted')
check(not billing.verify_signature(raw+b' ',signature,secret),'Tampered Stripe event rejected')
check(not billing.verify_signature(raw,signature,secret,now=int(when)+301),'Expired Stripe signature rejected')
business=query("SELECT * FROM identity_pages WHERE handle='$pagefixture'")[0]
check(get('Regular','/pages/'+business['id']+'/billing').status_code==200,'Billing status/disclosure page')
check(send('Regular','/pages/'+business['id']+'/billing',accept_terms='yes').status_code==503,'Unconfigured checkout cannot charge')
check(clients['Regular'].post('/billing/stripe/webhook',data=raw,environ_overrides=env).status_code==503,'Unconfigured webhook cannot activate')
with app.test_request_context('/pages/'+business['id']+'/billing',environ_overrides=env):
 check(not billing.entitled(core.get_db(),business),'No configured live billing entitlement')
app.config.update(PAGE_BILLING_MODE='test',PAGE_STRIPE_KEY='sk_test_fixture',PAGE_STRIPE_WEBHOOK=secret,PAGE_STRIPE_PRICE='price_Fixture')
period=int(time.time())+90*86400
price={'id':'price_Fixture','active':True,'unit_amount':500,'currency':'usd','recurring':{'interval':'month','interval_count':3}}
subscription={'id':'sub_Fixture','customer':'cus_Fixture','status':'active','current_period_end':period,'cancel_at_period_end':False,'latest_invoice':'in_Fixture','items':{'data':[{'quantity':1,'price':price}]}}
invoice={'id':'in_Fixture','customer':'cus_Fixture','subscription':'sub_Fixture','status':'paid','currency':'usd','amount_paid':500,'lines':{'data':[{'price':price,'period':{'end':period}}]}}
def fake_api(cfg,method,path,data=None,idempotency=None):
 if path=='prices/price_Fixture':return price
 if path=='checkout/sessions':return {'id':'cs_test_Fixture','url':'https://checkout.stripe.com/c/pay/cs_test_Fixture','livemode':False}
 if path=='checkout/sessions/cs_test_Fixture':
  row=query('SELECT * FROM page_subscriptions WHERE page_id=?',(business['id'],))[0]
  return {'id':'cs_test_Fixture','status':'complete','livemode':False,'client_reference_id':business['id'],'metadata':{'neonrest_checkout':row['checkout_key']},'customer':'cus_Fixture','subscription':'sub_Fixture'}
 if path=='subscriptions/sub_Fixture':return subscription
 if path=='invoices/in_Fixture':return invoice
 if path=='events/evt_FixturePaid':return {'id':'evt_FixturePaid','type':'checkout.session.completed','livemode':False,'data':{'object':{'id':'cs_test_Fixture'}}}
 raise AssertionError('Unexpected fake Stripe request '+path)
with patch.object(billing,'api',side_effect=fake_api):
 check(send('Regular','/pages/'+business['id']+'/billing',accept_terms='yes').status_code==303,'Configured test checkout uses hosted Stripe URL')
 raw=b'{"id":"evt_FixturePaid"}';when=str(int(time.time()));signature='t='+when+',v1='+hmac.new(secret.encode(),when.encode()+b'.'+raw,hashlib.sha256).hexdigest()
 response=clients['Regular'].post('/billing/stripe/webhook',data=raw,headers={'Stripe-Signature':signature},environ_overrides=env)
 check(response.status_code==204,'Verified event binds subscription and paid period')
 row=query('SELECT * FROM page_subscriptions WHERE page_id=?',(business['id'],))[0]
 check(row['paid_until']==period and row['live']==0,'Verified test invoice recorded as test entitlement')
 check(clients['Regular'].post('/billing/stripe/webhook',data=raw,headers={'Stripe-Signature':signature},environ_overrides=env).status_code==204,'Duplicate event idempotent')
 check(query('SELECT COUNT(*) FROM page_billing_events WHERE event_id=?',('evt_FixturePaid',))[0][0]==1,'One processed billing event')
 check(send('Regular','/pages/'+business['id']+'/edit',action='state',state='published',revision='0').status_code==409,'Test invoice never publishes live business page')
 check(send('Regular','/pages/'+business['id']+'/billing',action='cancel').status_code==302,'Period-end cancellation request')
 check(query('SELECT cancel_at_period_end FROM page_subscriptions WHERE page_id=?',(business['id'],))[0][0]==1,'Cancellation preserves paid period and disables renewal')
for key in ['PAGE_BILLING_MODE','PAGE_STRIPE_KEY','PAGE_STRIPE_WEBHOOK','PAGE_STRIPE_PRICE']:app.config.pop(key,None)
export=send('Writer','/account/export')
check(export.status_code==200 and 'page_social' in export.json and 'events' in export.json,'Own-data integration includes new features')
check(all('key' not in key for row in export.json.get('business_subscriptions',[]) for key in row),'No billing secrets in export')
print(json.dumps({'checks':checks,'passed':True,'scope':'social, invitations, transfer, calendar and unconfigured Stripe; disposable DB'}))
