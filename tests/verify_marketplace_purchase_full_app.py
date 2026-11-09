"""Hosted disposable-copy acceptance: real app/session/policy, fictional providers.

Invoke with neonrest_sandbox and a staged source tree. Does not mount or migrate
either running site. This file is a host CLI check, not unittest discovery.
"""
from pathlib import Path
import sys,os,json,sqlite3,importlib,urllib.request,smtplib
assert len(sys.argv)==3 and sys.argv[1]=='neonrest_sandbox'
stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T25-')
for prefix in ['NEONREST_PRODUCTION','NEONREST_SANDBOX']:
    os.environ[prefix+'_STRIPE_CONFIG']=str(stage.parent/'no-provider-credentials.json')
def forbidden(*a,**kw):raise AssertionError('network forbidden during application fixture')
urllib.request.urlopen=forbidden;smtplib.SMTP=forbidden;smtplib.SMTP_SSL=forbidden
import requests
requests.sessions.Session.request=forbidden
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
bootstrap=bootstrap.replace("'MAIL_QUEUE':'0'","'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')")
exec(compile(bootstrap,'disposable Sandbox bootstrap','exec'))
host=importlib.import_module(package+'.marketplace_purchase_sandbox')
studio=importlib.import_module(package+'.seller_studio')
payments=importlib.import_module(package+'.marketplace_payments')
addresses=importlib.import_module(package+'.marketplace_addresses')
shipping=importlib.import_module(package+'.marketplace_seller_shipping')
views=importlib.import_module(package+'.marketplace_pilot_views')
api_module=importlib.import_module(package+'.marketplace_test_checkout_api')
quotes=importlib.import_module(package+'.marketplace_quotes')
sys.path.insert(0,str(stage/'tests'))
from verify_marketplace_purchase_flow import HTTP
from verify_marketplace_carrier_rates import HTTP as CarrierHTTP
from verify_marketplace_payments import signed_event,SECRET
from cryptography.fernet import Fernet
from werkzeug.datastructures import MultiDict
seller=users['Owner'];buyer=users['Writer'];excluded=users['Regular']
with app.app_context():
    db=core.get_db()
    shop=studio.create_independent(db,seller,'Fictional purchase QA only')
    listing=studio.save_listing(db,seller,shop,MultiDict(dict(kind='physical',title='Fictional QA item',price='10.00',quantity='3',description='Not for sale',returns='Fictional return terms')))
    db.execute('INSERT INTO marketplace_publications(listing_id,listing_revision,published_at) VALUES (?,0,?)',(listing,now));db.commit()
store_path=w/'purchase.sqlite';db=sqlite3.connect(store_path);db.row_factory=sqlite3.Row
host.provision(db);db.close();store_path.chmod(0o600)
key=Fernet.generate_key();provider=HTTP(None,None);carrier_http=CarrierHTTP(None)
class Tax:
    def quote_tax(self,context,context_hash):return quotes.Assessment('tax','fictional-fixture','qa-tax',context_hash,90,now+300)
class Verifier:
    def verify(self,token):return True
def services(db,policy):
    provider.db=db;carrier_http.db=db
    store=addresses.AddressStore(db,addresses.FernetVault([key]),policy)
    return views.PilotServices(db,policy,store,addresses.AddressResolver(store),api_module.StripeTestCheckoutAPI('acct_platform','sk_test_fixture_only',provider),None,Tax(),lambda:now,shipping.SellerShipping(db,store.vault,policy,Verifier(),carrier_http))
bridge=host.register(app,core,str(store_path),[seller,buyer,users['Teen']],{shop:seller},services,worker_ready=True)
with app.test_request_context('/fixture-setup'):
    db=bridge['connect']();host.refresh(db,bridge['policy'],now)
    scope=payments.Scope('stripe','acct_platform')
    request_id=payments.begin_onboarding(db,seller,shop,scope,'fictional-onboarding',now,bridge['policy'])
    class Onboarding:
        scope=scope
        def resolve_onboarding(self,request):return payments.AccountObservation(scope,request,'acct_fixture',seller,True,True)
    payments.complete_onboarding(db,seller,request_id,Onboarding(),now,bridge['policy']);provider.onboarding=request_id
    ctx=services(db,bridge['policy']);settings=ctx.shipping_settings
    origin=dict(recipient='Fictional QA seller',line1='81 Example Origin Road',city='Fixture City',state='OR',postal_code='00123',country='US')
    address=ctx.address_store.create(seller,'origin',origin,'origin',now,shop_id=shop);ctx.address_store.set_origin(seller,shop,address['id'],now)
    settings.save_connection(seller,shop,0,'shippo_test_fictional_private_token_only',now)
    settings.save_preset(seller,shop,None,0,'Fictional mailer',180000,130000,25000,15000,3,True,now)
    sku=db.execute('SELECT id FROM marketplace_checkout_skus WHERE listing_id=?',(listing,)).fetchone()[0]
    settings.save_weight(seller,shop,sku,0,12000,now);db.close()
def post(who,path,**data):return clients[who].post('/marketplace/pilot'+path,data=dict(theme_csrf_token=token,**data),environ_overrides=env)
check(get('Writer','/marketplace/pilot/').status_code==200,'Real app catalog/session/template')
check(get('Teen','/marketplace/pilot/').status_code==403,'Allowlisted teen denied by actual age policy')
check(get('Regular','/marketplace/pilot/').status_code==403,'Adult outside tester allowlist denied')
check(app.test_client().get('/marketplace/pilot/').status_code in (401,302),'Anonymous denied')
check(clients['Writer'].post('/marketplace/pilot/checkout',environ_overrides=env).status_code==400,'Actual CSRF required')
with clients['Writer'].session_transaction() as s:s['fresh_at']=0;s['factor_at']=0
check(get('Writer','/marketplace/pilot/').status_code==200,'Ordinary pilot reading adds no fresh-auth gate')
destination=dict(recipient='Fictional QA buyer',line1='42 Example Privacy Way',city='Fixture City',state='OR',postal_code='00123',country='US')
r=post('Writer','/checkout',**destination,sku=sku,quantity='1',revision='0',request_key='actual-app-order')
check(r.status_code==302,'Actual app creates isolated reservation');order=r.location.rsplit('/',1)[1]
check(post('Writer','/orders/'+order+'/rates',share_address='yes').status_code==302,'Explicit fictional carrier consent')
db=bridge['connect']();rate=db.execute('SELECT id FROM marketplace_test_carrier_rates').fetchone()[0];db.close()
check(post('Writer','/orders/'+order+'/quote',rate=rate,request_key='actual-app-quote').status_code==302,'Full fictional shipping/tax quote')
db=bridge['connect']();q=db.execute('SELECT id FROM marketplace_checkout_quotes').fetchone()[0];db.close()
check(post('Writer','/orders/'+order+'/pay',quote_id=q,accept_total='yes',test_card='pm_card_visa').status_code==302,'Actual app explicit total and fictional payment submission')
db=bridge['connect']()
check(db.execute('SELECT count(*) FROM marketplace_test_settlements').fetchone()[0]==0,'Browser submission alone never settles');db.close()
from werkzeug.test import Client
from werkzeug.wrappers import Response
receiver=Client(bridge['webhook']([SECRET]),Response)
raw,sig=signed_event(payment='pi_flow1',now=now,created=now)
check(receiver.post('/stripe',data=raw,content_type='application/json',headers={'Stripe-Signature':sig}).status_code==200,'Same-store signed WSGI receiver')
check(receiver.post('/stripe',data=raw,content_type='application/json',headers={'Stripe-Signature':sig}).status_code==200,'Duplicate signature-verified delivery')
check(receiver.post('/stripe',data=raw,content_type='application/json').status_code==400,'Unsigned delivery denied')
bridge['worker_tick']();bridge['worker_tick']()
db=bridge['connect']()
check(db.execute('SELECT count(*) FROM marketplace_test_settlements').fetchone()[0]==1,'Same-store scheduled worker settles once');db.close()
check(get('Owner','/marketplace/pilot/seller/orders').status_code==200,'Actual seller queue')
check(post('Writer','/orders/'+order+'/destination').status_code==400,'Buyer cannot impersonate fulfillment seller')
check(post('Owner','/orders/'+order+'/destination').status_code==200,'Original seller accesses paid encrypted destination')
check(post('Owner','/orders/'+order+'/ship',request_key='actual-app-track',carrier='USPS',tracking='9400000000000000000000').status_code==302,'Actual app manual fictional tracking')
check(post('Owner','/orders/'+order+'/refund',request_key='actual-app-refund',item_cents='1000',shipping_cents='525',tax_cents='90').status_code==302,'Actual app fictional full refund')
with app.test_request_context('/fixture-worker'):
    db=bridge['connect']();ctx=services(db,bridge['policy']);host.recovery_tick(ctx);host.refresh(db,bridge['policy'],now)
    check(db.execute('SELECT quantity FROM marketplace_inventory_stock WHERE sku=?',(sku,)).fetchone()[0]==2,'Request refresh does not replenish sold stock or refund restock')
    check(db.execute('SELECT count(*) FROM marketplace_test_refund_applications').fetchone()[0]==1,'Exactly one refund application')
    check(db.execute('PRAGMA foreign_key_check').fetchall()==[],'Separate-store foreign keys');db.close()
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(buyer,seller))
check(get('Writer','/marketplace/pilot/orders/'+order).status_code==400,'Actual blocking revokes order access')
print(json.dumps(dict(passed=True,checks=checks,provider_calls='fictional only',running_sites_modified=False)))
