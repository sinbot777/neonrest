"""Explicitly mounted, allowlisted Sandbox-only purchase rehearsal UI.

The host supplies an isolated pre-provisioned database, actual-session
authorization, encrypted address store and test-only provider services. Importing
this module registers nothing and never migrates a running application database.
"""
from dataclasses import dataclass
import json
import sqlite3
import time
import uuid
from flask import Blueprint,abort,flash,g,redirect,render_template,request,session,url_for
if __package__:
    from . import marketplace_checkout as checkout,marketplace_inventory as inventory,marketplace_quotes as quotes
    from . import marketplace_purchase_flow as flow,marketplace_refunds as refunds,marketplace_pilot_orders as orders
    from . import marketplace_carrier_rates as carrier,marketplace_payments as payments,marketplace_payment_jobs as jobs
    from .marketplace_provider_api import ProviderUnavailable
else:
    import marketplace_checkout as checkout,marketplace_inventory as inventory,marketplace_quotes as quotes
    import marketplace_purchase_flow as flow,marketplace_refunds as refunds,marketplace_pilot_orders as orders
    import marketplace_carrier_rates as carrier,marketplace_payments as payments,marketplace_payment_jobs as jobs
    from marketplace_provider_api import ProviderUnavailable


@dataclass
class PilotServices:
    db: object
    policy: object
    address_store: object
    address_resolver: object
    stripe: object
    carrier_for_shop: object
    tax: object
    clock: object = lambda:int(time.time())
    shipping_settings: object = None

    def now(self):
        value=self.clock();inventory.clock(value);return value

    def location(self,rate=None):
        return carrier.CarrierResolver(self.address_resolver,rate,self.now,self.shipping_settings)

    def refresh_order(self,uid,order_id):
        checkout.get_order(self.db,'test',uid,order_id,self.now(),self.policy)
        adapter=payments.StripeTestPaymentReader(self.stripe.scope.platform,self.stripe.fetch_payment)
        # This reader never verifies new events; it uses only existing durable
        # signature-verified receipts. No synthetic event is generated here.
        rows=self.db.execute('''SELECT e.id FROM marketplace_payment_events e
          JOIN marketplace_test_payment_dispatches d ON d.account_ref=e.account_ref AND d.platform_ref=e.platform_ref
          WHERE d.order_id=? AND e.environment='test' AND e.provider='stripe'
          AND (e.payment_ref=d.payment_ref OR d.payment_ref IS NULL) AND e.event_type IN ('payment_intent.succeeded','payment_intent.processing','payment_intent.payment_failed','payment_intent.canceled')
          ORDER BY e.id DESC LIMIT 5''',(order_id,)).fetchall()
        for row in rows:
            try:
                flow.recover_dispatch_from_receipt(self.db,row[0],adapter,self.location(),self.now(),self.policy,expected_order_id=order_id)
                flow.recover_early_receipts(self.db,order_id,adapter,self.now(),self.policy)
                lease=jobs.claim(self.db,adapter,self.now(),receipt_id=row[0])
                if lease:jobs.process_claim(self.db,adapter,lease,self.now(),self.policy)
                flow.settle_received_payment(self.db,row[0],self.location(),self.now(),self.policy)
            except ValueError:
                # Conflicts remain in the existing durable review records.
                continue


def initialize_marker(db):
    """Called only by the explicit isolated-fixture provisioning tool."""
    db.execute('CREATE TABLE marketplace_pilot_marker(purpose TEXT NOT NULL)')
    db.execute("INSERT INTO marketplace_pilot_marker VALUES ('isolated_test_pilot_v1')");db.commit()


def register(app,database_factory,services_factory,authorize,allowed_users,environment,settings_only=False):
    if environment!='sandbox' or app.config.get('MARKETPLACE_TEST_PILOT') is not True:
        raise ValueError('explicit Sandbox-only pilot configuration required')
    if not callable(database_factory) or not callable(services_factory) or not callable(authorize):raise ValueError('configured pilot services required')
    if not isinstance(allowed_users,(tuple,list,set,frozenset)) or not allowed_users or any(type(uid) is not int or uid<=0 for uid in allowed_users):raise ValueError('explicit adult tester allowlist required')
    if type(settings_only) is not bool:raise ValueError('explicit preview scope required')
    allowed=frozenset(allowed_users);bp=Blueprint('marketplace_pilot',__name__,url_prefix='/marketplace/pilot')

    @bp.before_request
    def gate():
        if settings_only and request.endpoint!='marketplace_pilot.index' and not request.endpoint.startswith('marketplace_pilot.shipping_'):abort(404)
        uid=session.get('user_id')
        if type(uid) is not int:abort(401)
        if uid not in allowed or authorize(uid) is not True:abort(403)
        db=database_factory();db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
        try:
            marker=db.execute('SELECT purpose FROM marketplace_pilot_marker').fetchone()
            if not marker or marker[0]!='isolated_test_pilot_v1':raise ValueError
        except (ValueError,sqlite3.Error):
            db.close();abort(503)
        ctx=services_factory(db)
        if not isinstance(ctx,PilotServices) or ctx.db is not db or ctx.address_store.db is not db:
            db.close();abort(503)
        g.pilot=ctx;g.pilot_uid=uid
        checkout.actor(ctx.policy,db,uid)
        if request.method=='POST':
            helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
            limited=helpers['limited']('marketplace-test-pilot',60)
            if limited is not None:return limited

    @bp.context_processor
    def preview_scope():return dict(shipping_settings_only=settings_only)

    @bp.teardown_request
    def close(error):
        ctx=g.pop('pilot',None)
        if ctx:ctx.db.close()

    @bp.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'same-origin'})
        return response

    @bp.errorhandler(ValueError)
    def invalid(error):
        return render_template('marketplace_pilot.html',view='error',error=str(error)),400

    @bp.errorhandler(ProviderUnavailable)
    @bp.errorhandler(TimeoutError)
    def provider_unavailable(error):
        return render_template('marketplace_pilot.html',view='error',error='The provider response is unavailable. A submitted payment or refund may already exist; refresh the order before retrying. Do not create another order to retry a payment.'),503

    def integer(name,maximum=99):
        raw=request.form.get(name,'')
        if not raw.isascii() or not raw.isdecimal() or len(raw)>9 or not 0<=int(raw)<=maximum:raise ValueError('check '+name)
        return int(raw)

    def owned_order(order_id,buyer=False,seller=False):
        ctx=g.pilot;row=ctx.db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=?',(order_id,)).fetchone()
        checkout.get_order(ctx.db,'test',g.pilot_uid,order_id,ctx.now(),ctx.policy)
        if buyer and row['buyer_id']!=g.pilot_uid:raise ValueError('buyer permission required')
        if seller and row['seller_owner_id']!=g.pilot_uid:raise ValueError('seller owner permission required')
        return row

    @bp.get('')
    @bp.get('/')
    def index():
        if settings_only:return redirect(url_for('marketplace_pilot.shipping_shops'))
        ctx=g.pilot;items=[]
        rows=ctx.db.execute("SELECT l.*,s.name AS shop_name,s.owner_id FROM seller_listings l JOIN seller_shops s ON s.page_id=l.shop_id WHERE l.kind='physical' AND l.state='draft' ORDER BY l.id LIMIT 100").fetchall()
        for row in rows:
            if row['owner_id']!=g.pilot_uid and ctx.policy.published(ctx.db,row['id'],g.pilot_uid) is True:
                item=dict(row);options={o[0]:o for o in checkout.listing_options(row)}
                item['options']=[dict(r,label=options[r['variant_key']][1]) for r in ctx.db.execute('SELECT id,variant_key,listing_revision FROM marketplace_checkout_skus WHERE listing_id=? AND active=1',(row['id'],)) if r['variant_key'] in options]
                items.append(item)
        return render_template('marketplace_pilot.html',view='catalog',items=items,request_key=uuid.uuid4().hex)

    @bp.post('/checkout')
    def start():
        ctx=g.pilot;sku=request.form.get('sku');quantity=integer('quantity')
        if not quantity:raise ValueError('choose at least one item')
        mapping=ctx.db.execute('SELECT * FROM marketplace_checkout_skus WHERE id=? AND active=1',(sku,)).fetchone()
        if not mapping or ctx.policy.published(ctx.db,mapping['listing_id'],g.pilot_uid) is not True:raise ValueError('published stock item unavailable')
        key=request.form.get('request_key','');inventory.identity('test',key)
        address={k:request.form.get(k,'') for k in ('recipient','company','line1','line2','city','state','postal_code','country')}
        destination=ctx.address_store.create(g.pilot_uid,'destination',address,key+'-destination',ctx.now())
        order_id=checkout.create_order(ctx.db,'test',g.pilot_uid,mapping['seller_ref'],key,[(sku,quantity,integer('revision',1_000_000))],ctx.now(),ctx.policy)
        with inventory.transaction(ctx.db):
            old=ctx.db.execute('SELECT buyer_id,destination_id FROM marketplace_pilot_destinations WHERE order_id=?',(order_id,)).fetchone()
            if old and tuple(old)!=(g.pilot_uid,destination['id']):raise ValueError('checkout destination conflict')
            if not old:ctx.db.execute('INSERT INTO marketplace_pilot_destinations VALUES (?,?,?)',(order_id,g.pilot_uid,destination['id']))
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    def shipping_owner(shop_id):
        ctx=g.pilot
        if ctx.shipping_settings is None:abort(503)
        ctx.shipping_settings.owner(g.pilot_uid,shop_id)
        return ctx.shipping_settings

    @bp.get('/seller/shipping')
    def shipping_shops():
        ctx=g.pilot
        if ctx.shipping_settings is None:abort(503)
        available=[]
        for row in ctx.db.execute('SELECT page_id,name FROM seller_shops WHERE owner_id=? ORDER BY name LIMIT 100',(g.pilot_uid,)):
            try:ctx.shipping_settings.owner(g.pilot_uid,row['page_id'])
            except ValueError:continue
            available.append(dict(row))
        return render_template('marketplace_seller_shipping.html',view='shops',shops=available)

    @bp.get('/seller/shipping/<shop_id>')
    def shipping_settings(shop_id):
        ctx=g.pilot;settings=shipping_owner(shop_id);data=settings.public(g.pilot_uid,shop_id)
        origin=ctx.db.execute('SELECT book_id FROM marketplace_shop_origins WHERE shop_id=? AND owner_id=?',(shop_id,g.pilot_uid)).fetchone()
        address=ctx.address_store.read(g.pilot_uid,origin[0],ctx.now())['address'] if origin else None
        return render_template('marketplace_seller_shipping.html',view='settings',shop_id=shop_id,data=data,origin=address,request_key=uuid.uuid4().hex)

    @bp.post('/seller/shipping/<shop_id>/connection')
    def shipping_connect(shop_id):
        ctx=g.pilot;settings=shipping_owner(shop_id)
        if request.form.get('disconnect')=='yes':settings.disconnect(g.pilot_uid,shop_id,integer('revision',1000000),ctx.now())
        else:
            if request.form.get('consent')!='yes':raise ValueError('authorize verifying this shop connection with Shippo')
            settings.save_connection(g.pilot_uid,shop_id,integer('revision',1000000),request.form.get('api_token',''),ctx.now())
        return redirect(url_for('marketplace_pilot.shipping_settings',shop_id=shop_id))

    @bp.post('/seller/shipping/<shop_id>/origin')
    def shipping_origin(shop_id):
        ctx=g.pilot;shipping_owner(shop_id)
        address={k:request.form.get(k,'') for k in ('recipient','company','line1','line2','city','state','postal_code','country')}
        created=ctx.address_store.create(g.pilot_uid,'origin',address,request.form.get('request_key',''),ctx.now(),shop_id=shop_id)
        ctx.address_store.set_origin(g.pilot_uid,shop_id,created['id'],ctx.now())
        return redirect(url_for('marketplace_pilot.shipping_settings',shop_id=shop_id))

    @bp.post('/seller/shipping/<shop_id>/package')
    def shipping_package(shop_id):
        ctx=g.pilot;settings=shipping_owner(shop_id)
        if __package__:
            from .marketplace_seller_shipping import measurement
        else:
            from marketplace_seller_shipping import measurement
        unit=request.form.get('distance_unit');mass_unit=request.form.get('mass_unit')
        dimensions=[measurement(request.form.get(k),unit,'distance') for k in ('length','width','height')]
        settings.save_preset(g.pilot_uid,shop_id,request.form.get('preset_key') or None,integer('revision',1000000),request.form.get('name'),*dimensions,measurement(request.form.get('packaging_weight'),mass_unit,'mass'),integer('max_units',5000),request.form.get('enabled')=='yes',ctx.now())
        return redirect(url_for('marketplace_pilot.shipping_settings',shop_id=shop_id))

    @bp.post('/seller/shipping/<shop_id>/weight')
    def shipping_weight(shop_id):
        ctx=g.pilot;settings=shipping_owner(shop_id)
        if __package__:
            from .marketplace_seller_shipping import measurement
        else:
            from marketplace_seller_shipping import measurement
        settings.save_weight(g.pilot_uid,shop_id,request.form.get('sku'),integer('revision',1000000),measurement(request.form.get('weight'),request.form.get('mass_unit'),'mass'),ctx.now())
        return redirect(url_for('marketplace_pilot.shipping_settings',shop_id=shop_id))

    @bp.get('/purchases')
    def queue():return order_queue(False)

    @bp.get('/seller/orders')
    def seller_queue():return order_queue(True)

    def order_queue(seller):
        ctx=g.pilot
        column='seller_owner_id' if seller else 'buyer_id'
        rows=ctx.db.execute('SELECT id FROM marketplace_checkout_orders WHERE '+column+'=? ORDER BY created_at DESC,id LIMIT 100',(g.pilot_uid,)).fetchall()
        items=[]
        for row in rows:
            try:items.append(orders.receipt(ctx.db,g.pilot_uid,row['id'],ctx.now(),ctx.policy))
            except ValueError:continue
        return render_template('marketplace_pilot.html',view='queue',items=items,seller=seller)

    @bp.get('/orders/<order_id>')
    def order(order_id):
        ctx=g.pilot;owned_order(order_id)
        data=orders.receipt(ctx.db,g.pilot_uid,order_id,ctx.now(),ctx.policy)
        rates=ctx.db.execute('SELECT id,provider,service,amount_cents FROM marketplace_test_carrier_rates WHERE order_id=? AND buyer_id=? AND expires_at>? ORDER BY amount_cents,id',(order_id,g.pilot_uid,ctx.now())).fetchall() if data['buyer'] else []
        current=ctx.db.execute('SELECT quote_id FROM marketplace_checkout_quote_acceptances WHERE order_id=?',(order_id,)).fetchone()
        if not current:current=ctx.db.execute('SELECT id FROM marketplace_checkout_quotes WHERE order_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(order_id,)).fetchone()
        dispatch=ctx.db.execute('SELECT state FROM marketplace_test_payment_dispatches WHERE order_id=?',(order_id,)).fetchone()
        pending=ctx.db.execute("SELECT r.id,j.state FROM marketplace_test_refund_requests r JOIN marketplace_test_refund_jobs j ON j.request_id=r.id WHERE r.order_id=? AND j.state IN ('ready','retry','running','exhausted') ORDER BY r.created_at",(order_id,)).fetchall() if data['seller'] else []
        return render_template('marketplace_pilot.html',view='order',data=data,rates=rates,quote_id=current[0] if current else None,dispatch=dispatch,pending_refunds=pending,request_key=uuid.uuid4().hex)

    @bp.post('/orders/<order_id>/rates')
    def rate_options(order_id):
        ctx=g.pilot;row=owned_order(order_id,buyer=True)
        destination=ctx.db.execute('SELECT destination_id FROM marketplace_pilot_destinations WHERE order_id=? AND buyer_id=?',(order_id,g.pilot_uid)).fetchone()
        if not destination:raise ValueError('buyer destination required')
        api=ctx.shipping_settings.api(row['seller_ref'],row['seller_owner_id']) if ctx.shipping_settings is not None else ctx.carrier_for_shop(row['seller_ref'],row['seller_owner_id'])
        carrier.fetch_rates(ctx.db,g.pilot_uid,order_id,destination[0],ctx.location(),api,ctx.now(),request.form.get('share_address')=='yes',ctx.policy,clock=ctx.now)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/quote')
    def quote_order(order_id):
        ctx=g.pilot;owned_order(order_id,buyer=True)
        if ctx.tax is None:raise ValueError('tax calculation is not configured; checkout remains unavailable')
        destination=ctx.db.execute('SELECT destination_id FROM marketplace_pilot_destinations WHERE order_id=? AND buyer_id=?',(order_id,g.pilot_uid)).fetchone()
        if not destination:raise ValueError('buyer destination required')
        location=ctx.location(request.form.get('rate'))
        quotes.create_quote(ctx.db,g.pilot_uid,order_id,destination[0],request.form.get('request_key',''),location,location,ctx.tax,ctx.now(),ctx.policy)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/pay')
    def pay(order_id):
        ctx=g.pilot;owned_order(order_id,buyer=True)
        if request.form.get('accept_total')!='yes':raise ValueError('explicit final-total acceptance required')
        quote_id=request.form.get('quote_id');q=ctx.db.execute('SELECT order_id FROM marketplace_checkout_quotes WHERE id=? AND buyer_id=?',(quote_id,g.pilot_uid)).fetchone()
        if not q or q[0]!=order_id:raise ValueError('buyer order quote required')
        location=ctx.location()
        accepted=ctx.db.execute('SELECT quote_id FROM marketplace_checkout_quote_acceptances WHERE order_id=?',(order_id,)).fetchone()
        if accepted and accepted[0]!=quote_id:raise ValueError('this order already has an accepted quote')
        quotes.accept_quote(ctx.db,g.pilot_uid,quote_id,location,ctx.now(),ctx.policy)
        flow.prepare_payment(ctx.db,g.pilot_uid,quote_id,location,request.form.get('test_card','pm_card_visa'),ctx.now(),ctx.policy)
        flow.dispatch_payment(ctx.db,g.pilot_uid,order_id,ctx.stripe,location,ctx.now(),ctx.policy,clock=ctx.now)
        flash('Test payment submitted. Only verified provider confirmation can settle this order.','success')
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/retry-payment')
    def retry_payment(order_id):
        ctx=g.pilot;owned_order(order_id,buyer=True)
        # Durable original terms and provider idempotency are mandatory. No new
        # order, quote, amount or card is accepted from this retry form.
        flow.dispatch_payment(ctx.db,g.pilot_uid,order_id,ctx.stripe,ctx.location(),ctx.now(),ctx.policy,clock=ctx.now)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/refunds/<request_id>/retry')
    def retry_refund(order_id,request_id):
        ctx=g.pilot;owned_order(order_id,seller=True)
        row=ctx.db.execute('SELECT order_id FROM marketplace_test_refund_requests WHERE id=?',(request_id,)).fetchone()
        if not row or row[0]!=order_id:raise ValueError('refund belongs to another order')
        flow.dispatch_refund(ctx.db,g.pilot_uid,request_id,ctx.stripe,ctx.now(),ctx.policy)
        adapter=refunds.StripeTestRefundReader(payments.StripeTestPaymentReader(ctx.stripe.scope.platform,ctx.stripe.fetch_payment),ctx.stripe.fetch_refund)
        refunds.process_request(ctx.db,adapter,request_id,ctx.now())
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/refresh')
    def refresh(order_id):
        ctx=g.pilot;owned_order(order_id);ctx.refresh_order(g.pilot_uid,order_id)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/cancel')
    def cancel(order_id):
        ctx=g.pilot;owned_order(order_id,buyer=True)
        flow.cancel_unsubmitted_order(ctx.db,g.pilot_uid,order_id,ctx.now(),ctx.policy)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/refund')
    def refund(order_id):
        ctx=g.pilot;owned_order(order_id,seller=True)
        request_id=refunds.request_test_refund(ctx.db,g.pilot_uid,order_id,request.form.get('request_key',''),integer('item_cents',100_000_000),integer('shipping_cents',100_000_000),integer('tax_cents',100_000_000),ctx.now(),ctx.policy)
        flow.dispatch_refund(ctx.db,g.pilot_uid,request_id,ctx.stripe,ctx.now(),ctx.policy)
        adapter=refunds.StripeTestRefundReader(payments.StripeTestPaymentReader(ctx.stripe.scope.platform,ctx.stripe.fetch_payment),ctx.stripe.fetch_refund)
        refunds.process_request(ctx.db,adapter,request_id,ctx.now())
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/ship')
    def ship(order_id):
        ctx=g.pilot;owned_order(order_id,seller=True)
        orders.record_shipment(ctx.db,g.pilot_uid,order_id,request.form.get('request_key',''),request.form.get('carrier'),request.form.get('tracking'),ctx.now(),ctx.policy)
        return redirect(url_for('marketplace_pilot.order',order_id=order_id))

    @bp.post('/orders/<order_id>/destination')
    def destination(order_id):
        ctx=g.pilot;owned_order(order_id,seller=True)
        address=orders.paid_destination(ctx.db,ctx.address_store,g.pilot_uid,order_id,ctx.now(),ctx.policy)
        return render_template('marketplace_pilot.html',view='destination',address=address,order_id=order_id)

    app.register_blueprint(bp)

