"""Billing routes and paid-period rules against disposable real-app databases."""
from pathlib import Path
import sys,importlib,time,os,json
from unittest.mock import patch
exec(compile(Path(__file__).with_name('verify_identity_pages_full_app.py').read_text(),'page baseline','exec'))
billing=importlib.import_module(package+'.page_billing')
app.config.update(PAGE_BILLING_MODE='test',PAGE_STRIPE_KEY='sk_test_fixture',PAGE_STRIPE_WEBHOOK='whsec_fixture',PAGE_STRIPE_PRICE='price_Fixture')
url='/pages/'+business['id']+'/billing'
price={'id':'price_Fixture','currency':'usd','unit_amount':500,'recurring':{'interval':'month','interval_count':3},'active':True}
calls=[]
def provider(cfg,method,path,data=None,idempotency=None):
 calls.append((method,path,data,idempotency))
 if path=='prices/price_Fixture':return price
 if path=='checkout/sessions':return {'id':'cs_test_Fixture','url':'https://checkout.stripe.com/c/pay/cs_test_Fixture'}
 if path=='checkout/sessions/cs_test_Fixture':return {'id':'cs_test_Fixture','livemode':False,'status':'open'}
 if path=='billing_portal/sessions':return {'url':'https://billing.stripe.com/p/session/test_fixture'}
 if path=='subscriptions/sub_Fixture':return {'id':'sub_Fixture'}
 raise AssertionError(path)
with patch.object(billing,'api',side_effect=provider):
 check(send('Regular',url).status_code==400,'Checkout requires explicit recurring consent')
 check(send('Regular',url,accept_terms='yes').status_code==303,'Hosted checkout redirect')
 first=query('SELECT checkout_key FROM page_subscriptions WHERE page_id=?',(business['id'],))[0][0]
 check(send('Regular',url,accept_terms='yes').status_code==303,'Checkout retry supported')
 attempts=[c[3] for c in calls if c[1]=='checkout/sessions']
 check(len(set(attempts))==1,'Retries reuse the same provider idempotency key')
 check(b'No verified payment' not in get('Regular',url).data or query('SELECT paid_until FROM page_subscriptions WHERE page_id=?',(business['id'],))[0][0]==0,'Browser return grants no paid time')
 change("UPDATE page_subscriptions SET subscription_id='sub_Fixture',customer_id='cus_Fixture',status='active',paid_until=?,live=0 WHERE page_id=?",(now+3600,business['id']))
 check(send('Writer',url,action='portal').status_code==403,'Other account cannot open customer portal')
 check(send('Regular',url,action='portal').location=='https://billing.stripe.com/p/session/test_fixture','Owner can manage payment method and invoices')
 check(calls[-1][2]['customer']=='cus_Fixture','Portal customer comes from authenticated page record')
 check(send('Regular',url,accept_terms='yes').status_code==409,'Active subscription blocks another checkout')
 check(send('Regular',url,action='cancel').status_code==302,'Owner cancels renewal')
 check(query('SELECT paid_until FROM page_subscriptions WHERE page_id=?',(business['id'],))[0][0]==now+3600,'Cancellation preserves paid-through date')
 check(b'Cancel renewal at paid-period end' not in get('Regular',url).data,'Already canceled renewal has no duplicate cancel button')
 change("UPDATE page_subscriptions SET status='canceled' WHERE page_id=?",(business['id'],))
 check(b'Continue to Stripe checkout' not in get('Regular',url).data,'No double payment within paid period')
 change('UPDATE page_subscriptions SET paid_until=? WHERE page_id=?',(now-1,business['id']))
 check(b'Continue to Stripe checkout' in get('Regular',url).data,'Ended subscription offers new checkout')
 check(send('Regular',url,accept_terms='yes').status_code==303,'Expired subscription can restart')
 check(query('SELECT checkout_key FROM page_subscriptions WHERE page_id=?',(business['id'],))[0][0]!=first,'New subscription uses a fresh idempotency key')
 change("UPDATE page_subscriptions SET subscription_id='sub_Fixture',customer_id='cus_Fixture',status='canceled',review_required=1 WHERE page_id=?",(business['id'],))
 check(send('Regular',url,accept_terms='yes').status_code==409,'Refund/dispute review cannot be bypassed with new checkout')
 check(b'Continue to Stripe checkout' not in get('Regular',url).data,'Review hold suppresses checkout')
 check(send('Regular',url,action='unknown').status_code==400,'Unknown action rejected')
with patch.object(billing,'api',return_value={'url':'https://example.invalid/portal'}):
 check(send('Regular',url,action='portal').status_code==503,'Untrusted portal destination rejected')
with app.test_request_context(url,environ_overrides=env):
 check(not billing.entitled(core.get_db(),business),'Test paid period never grants public entitlement')
app.config.update(PAGE_BILLING_MODE='live',PAGE_STRIPE_KEY='sk_live_fixture')
with patch.dict(os.environ,{'NEONREST_STRIPE_LIVE_CONFIRMED':'1'}):
 change("UPDATE page_subscriptions SET owner_id=?,status='active',paid_until=?,live=1,review_required=0 WHERE page_id=?",(users['Regular'],now+3600,business['id']))
 with app.test_request_context(url,environ_overrides={'SCRIPT_NAME':''}):
  check(billing.entitled(core.get_db(),business),'Verified live paid period grants entitlement')
  change("UPDATE page_subscriptions SET status='canceled' WHERE page_id=?",(business['id'],))
  check(billing.entitled(core.get_db(),business),'Canceled renewal preserves paid access')
  change('UPDATE page_subscriptions SET paid_until=? WHERE page_id=?',(now-1,business['id']))
  check(not billing.entitled(core.get_db(),business),'Expiry revokes entitlement')
 with app.test_request_context(url,environ_overrides={'SCRIPT_NAME':'/sandbox'}):
  check(billing.config() is None,'Sandbox forbids live billing even with confirmation')
print(json.dumps({'checks':checks,'passed':True,'scope':'billing lifecycle; disposable database; no network or charge'}))
