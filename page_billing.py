"""Stripe-hosted subscriptions. Off by default; credentials never enter exports.

Pinned REST contract: 2024-06-20. Stripe-signed notifications are re-fetched
server-side; browser return URLs never grant entitlement.
"""
import hashlib,hmac,json,os,re,secrets,time
import requests
from flask import Blueprint,abort,current_app,redirect,render_template,request,session,url_for
from . import identity_pages as pages

API='https://api.stripe.com/v1/'
VERSION='2024-06-20'


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS page_subscriptions(page_id TEXT PRIMARY KEY REFERENCES identity_pages(id),
        owner_id INTEGER NOT NULL REFERENCES users(id),checkout_key TEXT NOT NULL,checkout_id TEXT,
        customer_id TEXT,subscription_id TEXT UNIQUE,status TEXT NOT NULL DEFAULT 'pending',
        paid_until INTEGER NOT NULL DEFAULT 0,live INTEGER NOT NULL DEFAULT 0,review_required INTEGER NOT NULL DEFAULT 0,
        cancel_at_period_end INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS page_billing_events(event_id TEXT PRIMARY KEY,type TEXT NOT NULL,
        subscription_id TEXT,processed_at INTEGER NOT NULL)''')


def config():
    prefix='NEONREST_SANDBOX' if request.script_root.startswith('/sandbox') else 'NEONREST_PRODUCTION'
    mode=current_app.config.get('PAGE_BILLING_MODE',os.getenv(prefix+'_STRIPE_MODE','off'))
    key=current_app.config.get('PAGE_STRIPE_KEY',os.getenv(prefix+'_STRIPE_SECRET_KEY',''))
    secret=current_app.config.get('PAGE_STRIPE_WEBHOOK',os.getenv(prefix+'_STRIPE_WEBHOOK_SECRET',''))
    price=current_app.config.get('PAGE_STRIPE_PRICE',os.getenv(prefix+'_STRIPE_PRICE_ID',''))
    if mode not in ('test','live'):return None
    if mode=='live' and (request.script_root.startswith('/sandbox') or os.getenv('NEONREST_STRIPE_LIVE_CONFIRMED')!='1'):return None
    if not key.startswith('sk_'+mode+'_') or not secret.startswith('whsec_') or not re.fullmatch(r'price_[A-Za-z0-9]+',price):return None
    return {'mode':mode,'key':key,'webhook':secret,'price':price}


def api(cfg,method,path,data=None,idempotency=None):
    if not re.fullmatch(r'[A-Za-z0-9_/]+',path):raise pages.PageError('Invalid billing request.',400)
    headers={'Authorization':'Bearer '+cfg['key'],'Stripe-Version':VERSION}
    if idempotency:headers['Idempotency-Key']=idempotency
    try:
        response=requests.request(method,API+path,data=data,headers=headers,timeout=12)
        response.raise_for_status();return response.json()
    except (requests.RequestException,ValueError):raise pages.PageError('Billing is temporarily unavailable. Please try again later.',503) from None


def check_price(price):
    if price.get('currency')!='usd' or price.get('unit_amount')!=500 or price.get('recurring',{}).get('interval')!='month' or price.get('recurring',{}).get('interval_count')!=3 or not price.get('active'):
        raise pages.PageError('The configured subscription does not match the approved $5 USD / three-month plan.',503)


def entitled(db,page):
    cfg=config()
    if not cfg or cfg['mode']!='live':return False
    row=db.execute('SELECT * FROM page_subscriptions WHERE page_id=?',(page['id'],)).fetchone()
    return bool(row and row['live'] and row['owner_id']==page['owner_id'] and row['paid_until']>time.time()
        and not row['review_required'] and row['status'] in ('active','past_due','canceled'))


def verify_signature(raw,header,secret,now=None):
    fields={}
    for part in header.split(','):
        if '=' in part:
            key,value=part.split('=',1);fields.setdefault(key,[]).append(value)
    try:stamp=int(fields['t'][0])
    except (KeyError,ValueError,IndexError):return False
    if abs((now or int(time.time()))-stamp)>300:return False
    digest=hmac.new(secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(digest,value) for value in fields.get('v1',[]))


def sync_event(db,cfg,event):
    ref=event.get('id');kind=event.get('type','')
    if not isinstance(ref,str) or not re.fullmatch(r'evt_[A-Za-z0-9]+',ref) or event.get('livemode')!=(cfg['mode']=='live'):raise pages.PageError('Invalid billing event.',400)
    if db.execute('SELECT 1 FROM page_billing_events WHERE event_id=?',(ref,)).fetchone():return
    obj=event.get('data',{}).get('object',{});sub_id=None;paid_invoice=None;risk=False
    # Event.data uses the event's original API version even when retrieved.
    # Normalize referenced objects through our pinned REST version first.
    object_id=obj.get('id','')
    if kind=='checkout.session.completed':obj=api(cfg,'GET','checkout/sessions/'+object_id)
    elif kind.startswith('invoice.'):obj=api(cfg,'GET','invoices/'+object_id)
    elif kind.startswith('customer.subscription.'):obj=api(cfg,'GET','subscriptions/'+object_id)
    elif kind=='charge.refunded':obj=api(cfg,'GET','charges/'+object_id)
    if kind=='checkout.session.completed':
        nonce=obj.get('metadata',{}).get('neonrest_checkout')
        row=db.execute('SELECT * FROM page_subscriptions WHERE checkout_key=?',(nonce,)).fetchone()
        if row and obj.get('id')==row['checkout_id'] and obj.get('client_reference_id')==row['page_id']:
            sub_id=obj.get('subscription')
            if not isinstance(sub_id,str):raise pages.PageError('Subscription confirmation is incomplete.',503)
            db.execute('UPDATE page_subscriptions SET subscription_id=?,customer_id=?,updated_at=? WHERE page_id=?',(sub_id,obj.get('customer'),int(time.time()),row['page_id']))
    elif kind.startswith('customer.subscription.'):
        sub_id=obj.get('id')
    elif kind.startswith('invoice.'):
        sub_id=obj.get('subscription')
        if kind=='invoice.paid':paid_invoice=obj
    elif kind in ('charge.refunded','charge.dispute.created','charge.dispute.closed'):
        charge=obj if kind=='charge.refunded' else api(cfg,'GET','charges/'+obj.get('charge','invalid'))
        if charge.get('invoice'):
            invoice=api(cfg,'GET','invoices/'+charge['invoice']);sub_id=invoice.get('subscription');risk=True
    row=db.execute('SELECT * FROM page_subscriptions WHERE subscription_id=?',(sub_id,)).fetchone() if isinstance(sub_id,str) else None
    if row:
        subscription=api(cfg,'GET','subscriptions/'+sub_id)
        if subscription.get('customer')!=row['customer_id']:raise pages.PageError('Billing ownership mismatch.',400)
        items=subscription.get('items',{}).get('data',[])
        if len(items)!=1 or items[0].get('quantity')!=1 or items[0].get('price',{}).get('id')!=cfg['price']:raise pages.PageError('Unexpected subscription plan.',400)
        check_price({**items[0]['price'],'active':True})
        paid_until=row['paid_until']
        # Resolve completion/payment events using the authoritative invoice as well.
        if paid_invoice is None and kind=='checkout.session.completed' and subscription.get('latest_invoice'):
            paid_invoice=api(cfg,'GET','invoices/'+subscription['latest_invoice'])
        if paid_invoice:
            invoice=api(cfg,'GET','invoices/'+paid_invoice['id'])
            if invoice.get('subscription')==sub_id and invoice.get('customer')==row['customer_id'] and invoice.get('status')=='paid' and invoice.get('currency')=='usd' and invoice.get('amount_paid')==500:
                periods=[line.get('period',{}).get('end',0) for line in invoice.get('lines',{}).get('data',[]) if line.get('price',{}).get('id')==cfg['price']]
                if periods:paid_until=max(paid_until,min(max(periods),int(subscription.get('current_period_end',0))))
        db.execute('''UPDATE page_subscriptions SET status=?,paid_until=?,live=?,cancel_at_period_end=?,review_required=MAX(review_required,?),updated_at=? WHERE page_id=?''',
            (subscription.get('status','unknown'),paid_until,int(cfg['mode']=='live'),int(subscription.get('cancel_at_period_end',False)),int(risk),int(time.time()),row['page_id']))
    db.execute('INSERT INTO page_billing_events VALUES (?,?,?,?)',(ref,kind,sub_id,int(time.time())))


def register(app,core):
    bp=Blueprint('page_billing',__name__)
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    @bp.errorhandler(pages.PageError)
    def error(e):return render_template('identity_page_error.html',message=str(e)),e.status
    def owner(page_id):
        uid=session.get('user_id')
        if not uid:abort(401)
        db=core.get_db();page=pages.get(db,page_id);pages.require_role(db,page,uid,('owner',))
        if page['kind']!='business':abort(400)
        return uid,page
    def writing():
        app.extensions['community_auth_helpers']['csrf']()
        if not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=request.path))
    @bp.route('/pages/<page_id>/billing',methods=['GET','POST'])
    def manage(page_id):
        uid,page=owner(page_id);db=core.get_db();cfg=config();row=db.execute('SELECT * FROM page_subscriptions WHERE page_id=?',(page_id,)).fetchone()
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            if not cfg:raise pages.PageError('Stripe account configuration is not complete. No charge was made.',503)
            if request.form.get('action')=='cancel':
                if not row or not row['subscription_id']:raise pages.PageError('No active subscription to cancel.',409)
                api(cfg,'POST','subscriptions/'+row['subscription_id'],{'cancel_at_period_end':'true'},'neonrest-cancel-'+row['subscription_id'])
                with db:db.execute('UPDATE page_subscriptions SET cancel_at_period_end=1,updated_at=? WHERE page_id=?',(int(time.time()),page_id))
                return redirect(url_for('page_billing.manage',page_id=page_id))
            if request.form.get('accept_terms')!='yes':raise pages.PageError('Accept the recurring $5 USD charge every three months before checkout.')
            check_price(api(cfg,'GET','prices/'+cfg['price']))
            if row and row['subscription_id'] and row['status'] not in ('canceled','incomplete_expired'):raise pages.PageError('Manage the existing subscription instead of creating another.',409)
            if row and row['paid_until']>time.time():raise pages.PageError('Your paid period has not ended. Manage the current subscription.',409)
            if row and row['subscription_id']:
                with db:db.execute("UPDATE page_subscriptions SET checkout_key=?,checkout_id=NULL,customer_id=NULL,subscription_id=NULL,status='pending',paid_until=0,review_required=0 WHERE page_id=?",(secrets.token_urlsafe(24),page_id))
                row=db.execute('SELECT * FROM page_subscriptions WHERE page_id=?',(page_id,)).fetchone()
            if row and row['checkout_id']:
                checkout=api(cfg,'GET','checkout/sessions/'+row['checkout_id'])
                if checkout.get('livemode')!=(cfg['mode']=='live'):raise pages.PageError('Billing mode changed. Contact the site owner to reconcile the previous test checkout.',409)
                if checkout.get('status')=='expired':
                    with db:db.execute('UPDATE page_subscriptions SET checkout_key=?,checkout_id=NULL WHERE page_id=?',(secrets.token_urlsafe(24),page_id))
                    row=db.execute('SELECT * FROM page_subscriptions WHERE page_id=?',(page_id,)).fetchone()
            if not row:
                with db:
                    db.execute('INSERT INTO page_subscriptions(page_id,owner_id,checkout_key,updated_at) VALUES (?,?,?,?)',(page_id,uid,secrets.token_urlsafe(24),int(time.time())))
                row=db.execute('SELECT * FROM page_subscriptions WHERE page_id=?',(page_id,)).fetchone()
            # A stable idempotency key prevents duplicate sessions on retry.
            target='https://www.neonrest.com'+url_for('page_billing.manage',page_id=page_id)
            payload={'mode':'subscription','client_reference_id':page_id,'metadata[neonrest_checkout]':row['checkout_key'],
                'line_items[0][price]':cfg['price'],'line_items[0][quantity]':'1',
                'success_url':target,'cancel_url':target,'customer_email':db.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()[0]}
            checkout=api(cfg,'POST','checkout/sessions',payload,'neonrest-checkout-'+row['checkout_key'])
            url=checkout.get('url','')
            if not url.startswith('https://checkout.stripe.com/'):raise pages.PageError('Checkout is unavailable.',503)
            with db:db.execute('UPDATE page_subscriptions SET checkout_id=?,updated_at=? WHERE page_id=?',(checkout['id'],int(time.time()),page_id))
            return redirect(url,code=303)
        return render_template('page_billing.html',page=page,billing=row,configured=bool(cfg),mode=cfg['mode'] if cfg else 'off',entitled=entitled(db,page))
    @bp.post('/billing/stripe/webhook')
    def webhook():
        cfg=config()
        if not cfg:abort(503)
        raw=request.get_data(cache=False)
        if len(raw)>65536:abort(413)
        if not verify_signature(raw,request.headers.get('Stripe-Signature',''),cfg['webhook']):abort(400)
        try:event=json.loads(raw)
        except ValueError:abort(400)
        ref=event.get('id','')
        if not re.fullmatch(r'evt_[A-Za-z0-9]+',ref):abort(400)
        verified=api(cfg,'GET','events/'+ref)
        with core.get_db():sync_event(core.get_db(),cfg,verified)
        return '',204
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    app.register_blueprint(bp)
