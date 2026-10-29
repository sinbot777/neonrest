"""Private checkout rehearsal. All records are test-only; no payment provider calls."""
import json
import secrets
import re
import time
from .seller_studio import StudioError,get_listing,event
from .marketplace_catalog import shop_quote

TTL=900


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS seller_test_quotes(id TEXT PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),
    shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),listing_id TEXT NOT NULL REFERENCES seller_listings(id),
    listing_revision INTEGER NOT NULL,variant TEXT NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0),snapshot TEXT NOT NULL,
    created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS seller_test_orders(id TEXT PRIMARY KEY,quote_id TEXT NOT NULL UNIQUE REFERENCES seller_test_quotes(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),seller_id INTEGER NOT NULL REFERENCES users(id),shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),
    listing_id TEXT NOT NULL REFERENCES seller_listings(id),variant TEXT NOT NULL,quantity INTEGER NOT NULL CHECK(quantity>0),snapshot TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'test_unpaid' CHECK(state IN ('test_unpaid','canceled','expired')),created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS seller_test_reservations ON seller_test_orders(listing_id,variant,state,expires_at)')
    db.execute('CREATE INDEX IF NOT EXISTS seller_test_quotes_actor ON seller_test_quotes(actor_id,created_at)')
    db.execute('''CREATE TRIGGER IF NOT EXISTS seller_test_order_snapshot_immutable BEFORE UPDATE OF quote_id,actor_id,seller_id,
    shop_id,listing_id,variant,quantity,snapshot,created_at,expires_at ON seller_test_orders BEGIN SELECT RAISE(ABORT,'Test order snapshot is immutable'); END''')


def selected(listing,variant):
    variants=json.loads(listing['variations'])
    if variants:
        if not isinstance(variant,str) or not re.fullmatch(r'[0-9]{1,2}',variant) or int(variant)>=len(variants):raise StudioError('Choose a variation.')
        item=variants[int(variant)];return str(int(variant)),item['price_cents'],item['quantity'],item['label']
    if variant not in ('',None,'base'):raise StudioError('This draft has no variations.')
    return 'base',listing['price_cents'],listing['quantity'],None


def available(db,listing_id,variant,stock,now,revision):
    held=db.execute("SELECT COALESCE(SUM(o.quantity),0) FROM seller_test_orders o JOIN seller_test_quotes q ON q.id=o.quote_id WHERE o.listing_id=? AND o.variant=? AND o.state='test_unpaid' AND o.expires_at>? AND q.listing_revision=?",(listing_id,variant,now,revision)).fetchone()[0]
    return max(0,stock-held)


def create_quote(db,uid,page_id,listing_id,revision,variant,quantity,now=None):
    now=int(time.time()) if now is None else now
    page,shop,listing=get_listing(db,uid,page_id,listing_id)
    if page['state']=='archived' or listing['state']!='draft' or listing['revision']!=revision:raise StudioError('Reload an editable draft before previewing checkout.',409)
    if type(quantity) is not int or not 1<=quantity<=99:raise StudioError('Preview 1–99 units.')
    variant,price,stock,label=selected(listing,variant)
    if quantity>available(db,listing_id,variant,stock,now,listing['revision']):raise StudioError('Insufficient draft stock after active test reservations.',409)
    if db.execute('SELECT COUNT(*) FROM seller_test_quotes WHERE actor_id=? AND expires_at>?',(uid,now)).fetchone()[0]>=20:raise StudioError('Too many active checkout previews. Wait for one to expire.',409)
    if price*quantity>100_000_000:raise StudioError('This item subtotal exceeds the checkout preview limit.')
    snapshot={'title':listing['title'],'kind':listing['kind'],'unit_price':price,'variant':label,'delivery':listing['delivery'],'license':listing['license'],'returns':listing['returns'],'shop_name':shop['name'],'shop_policies':shop['policies'],'quote':shop_quote(db,shop,price*quantity,listing['kind']),'test_only':True,'shipping_and_tax_calculated':False}
    key=secrets.token_urlsafe(24);db.execute('INSERT INTO seller_test_quotes VALUES (?,?,?,?,?,?,?,?,?,?)',(key,uid,page_id,listing_id,revision,variant,quantity,json.dumps(snapshot,ensure_ascii=False),now,now+TTL));return key


def get_quote(db,uid,page_id,listing_id,quote_id):
    page,shop,listing=get_listing(db,uid,page_id,listing_id)
    row=db.execute('SELECT * FROM seller_test_quotes WHERE id=? AND actor_id=? AND shop_id=? AND listing_id=?',(quote_id,uid,page_id,listing_id)).fetchone()
    if not row:raise StudioError('Checkout preview unavailable.',404)
    return page,shop,listing,row


def create_order(db,uid,page_id,listing_id,quote_id,now=None):
    now=int(time.time()) if now is None else now
    page,shop,listing,q=get_quote(db,uid,page_id,listing_id,quote_id)
    # Unique quote/order pairing makes double-clicks idempotent.
    old=db.execute('SELECT id FROM seller_test_orders WHERE quote_id=?',(quote_id,)).fetchone()
    if old:return old['id']
    if q['expires_at']<=now:raise StudioError('This checkout preview expired. Make a new one.',409)
    if page['state']=='archived' or listing['state']!='draft' or listing['revision']!=q['listing_revision']:raise StudioError('The draft changed. Make a new checkout preview.',409)
    _,_,stock,_=selected(listing,q['variant'])
    if q['quantity']>available(db,listing_id,q['variant'],stock,now,listing['revision']):raise StudioError('Draft stock was reserved by another test order.',409)
    if db.execute('SELECT COUNT(*) FROM seller_test_orders WHERE actor_id=?',(uid,)).fetchone()[0]>=1000:raise StudioError('The initial limit is 1,000 retained test orders per account.',409)
    key=secrets.token_urlsafe(24);db.execute('INSERT INTO seller_test_orders(id,quote_id,actor_id,seller_id,shop_id,listing_id,variant,quantity,snapshot,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(key,quote_id,uid,shop['owner_id'],page_id,listing_id,q['variant'],q['quantity'],q['snapshot'],now,now+TTL));event(db,page_id,uid,'create-test-order',listing_id);return key


def cancel(db,uid,page_id,listing_id,order_id):
    get_listing(db,uid,page_id,listing_id)
    row=db.execute('SELECT * FROM seller_test_orders WHERE id=? AND actor_id=? AND shop_id=? AND listing_id=?',(order_id,uid,page_id,listing_id)).fetchone()
    if not row:raise StudioError('Test order unavailable.',404)
    db.execute("UPDATE seller_test_orders SET state='canceled' WHERE id=? AND state='test_unpaid'",(order_id,));event(db,page_id,uid,'cancel-test-order',listing_id)


def export_user(db,uid):
    return [dict(row) for row in db.execute('SELECT * FROM seller_test_orders WHERE actor_id=? OR seller_id=? ORDER BY created_at,id LIMIT 2000',(uid,uid))]


def register(app,core):
    from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
    bp=Blueprint('marketplace_orders',__name__)
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    @bp.errorhandler(StudioError)
    def error(exc):return render_template('seller_studio.html',error=str(exc),view='error',unsaved=[]),exc.status
    def actor():
        uid=session.get('user_id')
        if type(uid) is not int:abort(401)
        return uid
    def writing():
        helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
        if not helpers['fresh']():return redirect(url_for('community_reauth',next=request.path))
        return helpers['limited']('seller-test-checkout',30)
    @bp.post('/marketplace/studio/<page_id>/listing/<listing_id>/checkout-preview')
    def new_quote(page_id,listing_id):
        uid=actor();db=core.get_db();get_listing(db,uid,page_id,listing_id)
        response=writing()
        if response is not None:return response
        revision=request.form.get('revision',type=int);count=request.form.get('quantity',type=int)
        if revision is None or not 0<=revision<2**63:raise StudioError('Reload before previewing checkout.',409)
        with db:
            db.execute('BEGIN IMMEDIATE');key=create_quote(db,uid,page_id,listing_id,revision,request.form.get('variant','base'),count)
        return redirect(url_for('marketplace_orders.review',page_id=page_id,listing_id=listing_id,quote_id=key))
    @bp.route('/marketplace/studio/<page_id>/listing/<listing_id>/checkout-preview/<quote_id>',methods=['GET','POST'])
    def review(page_id,listing_id,quote_id):
        uid=actor();db=core.get_db();page,shop,listing,q=get_quote(db,uid,page_id,listing_id,quote_id)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            if request.form.get('action')!='test-order':raise StudioError('Payments are not enabled.',403)
            with db:
                db.execute('BEGIN IMMEDIATE');key=create_order(db,uid,page_id,listing_id,quote_id)
            flash('Unpaid test order saved. No money was charged.','success')
            return redirect(url_for('marketplace_orders.order',page_id=page_id,listing_id=listing_id,order_id=key))
        return render_template('seller_checkout_preview.html',page=page,listing=listing,quote=q,snapshot=json.loads(q['snapshot']),expired=q['expires_at']<=int(time.time()) or q['listing_revision']!=listing['revision'] or page['state']=='archived' or listing['state']!='draft',order=None)
    @bp.route('/marketplace/studio/<page_id>/listing/<listing_id>/test-order/<order_id>',methods=['GET','POST'])
    def order(page_id,listing_id,order_id):
        uid=actor();db=core.get_db();page,shop,listing=get_listing(db,uid,page_id,listing_id)
        row=db.execute('SELECT * FROM seller_test_orders WHERE id=? AND actor_id=? AND shop_id=? AND listing_id=?',(order_id,uid,page_id,listing_id)).fetchone()
        if not row:raise StudioError('Test order unavailable.',404)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            if request.form.get('action')!='cancel':raise StudioError('Payments and fulfillment are not enabled.',403)
            with db:
                db.execute('BEGIN IMMEDIATE');cancel(db,uid,page_id,listing_id,order_id)
            return redirect(url_for('marketplace_orders.order',page_id=page_id,listing_id=listing_id,order_id=order_id))
        qrev=db.execute('SELECT listing_revision FROM seller_test_quotes WHERE id=?',(row['quote_id'],)).fetchone()[0]
        return render_template('seller_checkout_preview.html',page=page,listing=listing,quote=None,snapshot=json.loads(row['snapshot']),expired=row['expires_at']<=int(time.time()) or qrev!=listing['revision'] or page['state']=='archived' or listing['state']!='draft',order=row)
    @bp.after_request
    def private(response):
        response.headers.update({'Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})
        return response
    app.register_blueprint(bp)

