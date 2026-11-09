"""Explicit host bridge for an isolated, allowlisted Sandbox purchase pilot.

No startup import, provider account claiming, implicit tax rule or migration.
The caller supplies configured test services and a separately provisioned store.
"""
import importlib
from pathlib import Path
import sqlite3
import time
from flask import session
from jinja2 import ChoiceLoader, FileSystemLoader

if __package__:
    from . import marketplace_shipping_sandbox as shipping_host
    from . import marketplace_checkout as checkout, marketplace_addresses as addresses
    from . import marketplace_quotes as quotes, marketplace_payments as payments
    from . import marketplace_settlement as settlement, marketplace_refunds as refunds
    from . import marketplace_purchase_flow as flow, marketplace_pilot_orders as orders
    from . import marketplace_pilot_views as views, marketplace_payment_jobs as jobs
    from .marketplace_test_checkout_api import StripeTestCheckoutAPI
else:
    import marketplace_shipping_sandbox as shipping_host
    import marketplace_checkout as checkout, marketplace_addresses as addresses
    import marketplace_quotes as quotes, marketplace_payments as payments
    import marketplace_settlement as settlement, marketplace_refunds as refunds
    import marketplace_purchase_flow as flow, marketplace_pilot_orders as orders
    import marketplace_pilot_views as views, marketplace_payment_jobs as jobs
    from marketplace_test_checkout_api import StripeTestCheckoutAPI

PURPOSE = 'isolated_sandbox_purchases_v1'
LISTING_FIELDS = ('shop_id','kind','title','description','price_cents','quantity',
                  'variations','delivery','license','returns','state','revision')


def provision(db):
    """Explicit fresh-store setup; refuses existing shipping or application DBs."""
    shipping_host.provision(db)
    quotes.initialize(db)
    payments.initialize(db)
    settlement.initialize(db)
    refunds.initialize(db)
    flow.initialize(db)
    orders.initialize(db)
    db.execute('CREATE TABLE marketplace_purchase_host_marker(purpose TEXT PRIMARY KEY)')
    db.execute('INSERT INTO marketplace_purchase_host_marker VALUES (?)',(PURPOSE,))
    db.execute('CREATE TABLE marketplace_purchase_worker_cursor(platform TEXT PRIMARY KEY,receipt_id INTEGER NOT NULL)')
    db.commit()


class LivePurchasePolicy(shipping_host.LivePolicy):
    """Every decision reads current Sandbox policy, including worker decisions."""
    def __init__(self,core,studio,catalog,allowed_users,sellers):
        super().__init__(core,studio,catalog)
        self.allowed=frozenset(allowed_users)
        self.sellers=dict(sellers)

    def adult(self,db,uid):
        return uid in self.allowed and super().adult(db,uid)

    def owner(self,db,uid,shop):
        return self.sellers.get(shop['page_id'])==uid and super().owner(db,uid,shop)

    def visible(self,db,shop,buyer):
        if not self.adult(db,buyer) or not self.owner(db,shop['owner_id'],shop):return False
        current=self.core.get_db().execute('SELECT * FROM seller_shops WHERE page_id=?',(shop['page_id'],)).fetchone()
        if not current or any(current[k]!=shop[k] for k in ('owner_id','name','policies','revision')):return False
        return super().visible(db,shop,buyer)

    def published(self,db,listing_id,buyer):
        local=db.execute('SELECT * FROM seller_listings WHERE id=?',(listing_id,)).fetchone()
        if not local or local['kind']!='physical':return False
        shop=db.execute('SELECT * FROM seller_shops WHERE page_id=?',(local['shop_id'],)).fetchone()
        if not shop or not self.visible(db,shop,buyer):return False
        try:current=self.catalog.detail(self.core.get_db(),buyer,listing_id)
        except ValueError:return False
        return all(current[k]==local[k] for k in LISTING_FIELDS)


def refresh(db,policy,now):
    """Copy only permitted catalog/identity metadata, never sessions or birthdays."""
    for owner in set(policy.sellers.values()):
        if policy.adult(db,owner):shipping_host.refresh_mirror(db,owner,policy,now)
    with checkout.inventory.transaction(db):
        for uid in policy.allowed:
            if policy.adult(db,uid):db.execute('INSERT OR IGNORE INTO users VALUES (?)',(uid,))


def recovery_tick(ctx,limit=25):
    """One bounded scheduled tick; uses only signature-verified durable receipts.

    Cursor rotation prevents an old review receipt from starving later payments.
    No payment creation is retried automatically. Refund dispatches already
    explicitly submitted by a seller reuse their original idempotency identity.
    Exceptions return only fixed categories; no provider payloads or secrets.
    """
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('bounded worker batch required')
    if not isinstance(ctx.stripe,StripeTestCheckoutAPI):raise ValueError('configured test Stripe required')
    db=ctx.db;now=ctx.now();platform=ctx.stripe.scope.platform
    reader=payments.StripeTestPaymentReader(platform,ctx.stripe.fetch_payment)
    cursor=db.execute('SELECT receipt_id FROM marketplace_purchase_worker_cursor WHERE platform=?',(platform,)).fetchone()
    last=cursor[0] if cursor else 0
    rows=db.execute("SELECT id FROM marketplace_payment_events WHERE environment='test' AND provider='stripe' AND platform_ref=? AND id>? ORDER BY id LIMIT ?",(platform,last,limit)).fetchall()
    if not rows and last:
        last=0
        rows=db.execute("SELECT id FROM marketplace_payment_events WHERE environment='test' AND provider='stripe' AND platform_ref=? ORDER BY id LIMIT ?",(platform,limit)).fetchall()
    result=dict(receipts=0,settled=0,review=0,unavailable=0,refund_dispatches=0)
    for row in rows:
        try:
            recovered=flow.recover_dispatch_from_receipt(db,row[0],reader,ctx.location(),ctx.now(),ctx.policy)
            if recovered['state']=='bound':flow.recover_early_receipts(db,recovered['order_id'],reader,ctx.now(),ctx.policy)
            lease=jobs.claim(db,reader,ctx.now(),receipt_id=row[0])
            if lease:jobs.process_claim(db,reader,lease,ctx.now(),ctx.policy)
            outcome=flow.settle_received_payment(db,row[0],ctx.location(),ctx.now(),ctx.policy)
            if outcome.get('outcome')=='test_settled':result['settled']+=1
        except ValueError:result['review']+=1
        except Exception:result['unavailable']+=1
        result['receipts']+=1;last=row[0]
    with checkout.inventory.transaction(db):
        db.execute('INSERT INTO marketplace_purchase_worker_cursor VALUES (?,?) ON CONFLICT(platform) DO UPDATE SET receipt_id=excluded.receipt_id',(platform,last))
    jobs.run_due(db,reader,ctx.now(),limit,ctx.policy,ctx.now)
    pending=db.execute('''SELECT r.id,r.owner_id FROM marketplace_test_refund_requests r
      JOIN marketplace_test_refund_dispatches d ON d.request_id=r.id
      JOIN marketplace_test_refund_jobs j ON j.request_id=r.id
      WHERE d.refund_ref IS NULL AND j.state IN ('ready','retry') ORDER BY r.created_at LIMIT ?''',(limit,)).fetchall()
    for row in pending:
        try:flow.dispatch_refund(db,row['owner_id'],row['id'],ctx.stripe,ctx.now(),ctx.policy);result['refund_dispatches']+=1
        except ValueError:result['review']+=1
        except Exception:result['unavailable']+=1
    refund_reader=refunds.StripeTestRefundReader(reader,ctx.stripe.fetch_refund)
    refunds.run_due(db,refund_reader,ctx.now(),limit,ctx.now)
    return result


def register(app,core,database_path,allowed_users,sellers,services_factory,worker_ready=False):
    """Configure an existing Sandbox app only; no fixture policy is accepted.

    services_factory(db, policy) must return actual configured PilotServices.
    worker_ready is an explicit operator assertion after scheduling a worker;
    this function cannot schedule jobs or silently treat browser refresh as one.
    """
    if getattr(core,'__name__',None)!='neonrest_sandbox.app' or app is not core.app:raise ValueError('existing Sandbox application required')
    if not allowed_users or any(type(x) is not int or x<=0 for x in allowed_users):raise ValueError('explicit adult tester allowlist required')
    if not isinstance(sellers,dict) or not sellers or any(not isinstance(k,str) or v not in allowed_users for k,v in sellers.items()):raise ValueError('explicit shop/owner allowlist required')
    if worker_ready is not True or not callable(services_factory):raise ValueError('configured services and scheduled recovery required')
    path=shipping_host.private_file(database_path)
    if path.resolve()==Path(app.config['DATABASE']).resolve():raise ValueError('separate purchase database required')
    studio=importlib.import_module('neonrest_sandbox.seller_studio')
    catalog=importlib.import_module('neonrest_sandbox.marketplace_catalog')
    policy=LivePurchasePolicy(core,studio,catalog,allowed_users,sellers)
    def connect():
        db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
        try:
            row=db.execute('SELECT purpose FROM marketplace_purchase_host_marker').fetchone()
            if not row or row[0]!=PURPOSE:raise ValueError('isolated purchase marker required')
            return db
        except Exception:db.close();raise
    def services(db):
        ctx=services_factory(db,policy)
        if not isinstance(ctx,views.PilotServices) or ctx.db is not db or ctx.policy is not policy or ctx.address_store.db is not db or ctx.address_store.policy is not policy:raise ValueError('same-store authoritative services required')
        if not isinstance(ctx.stripe,StripeTestCheckoutAPI) or ctx.tax is None or not callable(getattr(ctx.tax,'quote_tax',None)) or ctx.shipping_settings is None:raise ValueError('test providers, seller shipping and explicit tax calculator required')
        return ctx
    # Validate everything before exposing routes or modifying template loaders.
    db=connect()
    try:services(db)
    finally:db.close()
    def factory():
        db=connect()
        try:refresh(db,policy,int(time.time()));return db
        except Exception:db.close();raise
    app.config['MARKETPLACE_TEST_PILOT']=True
    app.jinja_loader=ChoiceLoader([FileSystemLoader(str(Path(__file__).parent/'templates')),app.jinja_loader])
    views.register(app,factory,services,lambda uid:policy.adult(None,uid),allowed_users,'sandbox')
    # The worker and webhook provisioning use this exact store and policy.
    return dict(connect=connect,services=services,policy=policy)
