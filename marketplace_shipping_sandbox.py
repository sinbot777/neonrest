"""Shipping-only Sandbox mount: live permissions, isolated test settings database.

Never imports Production, migrates on startup, copies authentication/DOB data,
registers purchasing routes for use, or reads a shared merchant token.
"""
import importlib
import os
from pathlib import Path
import sqlite3
import stat
import time
from flask import session
from jinja2 import ChoiceLoader,FileSystemLoader
if __package__:
    from . import marketplace_checkout as checkout,marketplace_addresses as addresses
    from . import marketplace_carrier_rates as carrier,marketplace_seller_shipping as shipping
    from . import marketplace_pilot_views as views
else:
    import marketplace_checkout as checkout,marketplace_addresses as addresses
    import marketplace_carrier_rates as carrier,marketplace_seller_shipping as shipping
    import marketplace_pilot_views as views


MIRROR_SCHEMA='''
CREATE TABLE users(id INTEGER PRIMARY KEY);
CREATE TABLE seller_shops(page_id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,
 policies TEXT NOT NULL,revision INTEGER NOT NULL,frozen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE seller_listings(id TEXT PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),kind TEXT NOT NULL,
 title TEXT NOT NULL,description TEXT NOT NULL,price_cents INTEGER NOT NULL,quantity INTEGER NOT NULL,variations TEXT NOT NULL,
 delivery TEXT NOT NULL,license TEXT NOT NULL,returns TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL);
'''


def private_file(path):
    p=Path(path)
    if not p.is_absolute() or p.is_symlink():raise ValueError('private ordinary file required')
    info=p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('private owner-only file required')
    return p


def provision(db):
    """Explicit setup for a fresh isolated file only; never called by register."""
    if db.in_transaction or db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():raise ValueError('fresh isolated database required')
    db.executescript(MIRROR_SCHEMA)
    checkout.initialize(db);addresses.initialize(db);carrier.initialize(db);shipping.initialize(db);views.initialize_marker(db)
    db.execute('CREATE TABLE marketplace_shipping_host_marker(purpose TEXT PRIMARY KEY)')
    db.execute("INSERT INTO marketplace_shipping_host_marker VALUES ('sandbox_shipping_settings_only_v1')");db.commit()


class LivePolicy:
    """The mirror has no authority to grant site eligibility or shop access."""
    def __init__(self,core,studio,catalog):self.core=core;self.studio=studio;self.catalog=catalog
    def adult(self,db,uid):return type(uid) is int and self.studio.adult_account(self.core.get_db(),uid)
    def owner(self,db,uid,shop):
        try:
            page,current=self.studio.access(self.core.get_db(),uid,shop['page_id'],owner_only=True)
            return bool(current and current['owner_id']==uid==shop['owner_id'] and page['state']!='archived')
        except ValueError:return False
    def visible(self,db,shop,buyer):
        live=self.core.get_db();current=live.execute('SELECT * FROM seller_shops WHERE page_id=?',(shop['page_id'],)).fetchone()
        return bool(current and current['owner_id']==shop['owner_id'] and self.catalog.allowed(live,current,buyer))
    def fee_waived(self,db,shop):
        live=self.core.get_db();row=live.execute('SELECT * FROM seller_shops WHERE page_id=?',(shop['page_id'],)).fetchone()
        return bool(row and row['owner_id']==shop['owner_id'] and self.catalog.fee_policy(live,row))
    def published(self,db,listing,buyer):
        try:self.catalog.detail(self.core.get_db(),buyer,listing);return True
        except ValueError:return False


def refresh_mirror(db,uid,policy,now):
    if not policy.adult(db,uid):raise ValueError('eligible Sandbox seller required')
    live=policy.core.get_db()
    shops=[r for r in live.execute('SELECT * FROM seller_shops WHERE owner_id=? ORDER BY page_id LIMIT 100',(uid,)) if policy.owner(db,uid,r)]
    with checkout.inventory.transaction(db):
        db.execute('INSERT OR IGNORE INTO users VALUES (?)',(uid,))
        for shop in shops:
            db.execute('''INSERT INTO seller_shops VALUES (?,?,?,?,?,0) ON CONFLICT(page_id) DO UPDATE SET
             owner_id=excluded.owner_id,name=excluded.name,policies=excluded.policies,revision=excluded.revision''',
             (shop['page_id'],uid,shop['name'],shop['policies'],shop['revision']))
            for listing in live.execute("SELECT * FROM seller_listings WHERE shop_id=? AND kind='physical' ORDER BY id LIMIT 1000",(shop['page_id'],)):
                db.execute('''INSERT INTO seller_listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind,title=excluded.title,description=excluded.description,price_cents=excluded.price_cents,
                 quantity=excluded.quantity,variations=excluded.variations,delivery=excluded.delivery,license=excluded.license,
                 returns=excluded.returns,state=excluded.state,revision=excluded.revision''',tuple(listing[k] for k in ('id','shop_id','kind','title','description','price_cents','quantity','variations','delivery','license','returns','state','revision')))
    for shop in shops:
        current={r[0] for r in live.execute("SELECT id FROM seller_listings WHERE shop_id=? AND kind='physical'",(shop['page_id'],))}
        with checkout.inventory.transaction(db):
            for row in db.execute('SELECT id FROM marketplace_checkout_skus WHERE seller_ref=?',(shop['page_id'],)).fetchall():
                listing=db.execute('SELECT listing_id FROM marketplace_checkout_skus WHERE id=?',(row[0],)).fetchone()[0]
                if listing not in current:db.execute('UPDATE marketplace_checkout_skus SET active=0 WHERE id=?',(row[0],))
        for listing in db.execute("SELECT id,revision FROM seller_listings WHERE shop_id=? AND kind='physical'",(shop['page_id'],)).fetchall():
            if listing['id'] in current:checkout.sync_listing(db,'test',uid,shop['page_id'],listing['id'],listing['revision'],now,policy)


def register(app,core,database_path,key_path,allowed_users):
    if getattr(core,'__name__',None)!='neonrest_sandbox.app' or app is not core.app:raise ValueError('only the existing Sandbox application may mount this preview')
    dbpath=private_file(database_path);keyfile=private_file(key_path)
    if dbpath.resolve()==Path(core.app.config['DATABASE']).resolve():raise ValueError('isolated shipping database required')
    if not isinstance(allowed_users,(list,tuple)) or not allowed_users or any(type(uid) is not int or uid<=0 for uid in allowed_users):raise ValueError('explicit tester allowlist required')
    key=keyfile.read_bytes().strip();vault=addresses.FernetVault([key])
    def connect():
        db=sqlite3.connect(dbpath.as_uri()+'?mode=rw',uri=True,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
        try:
            marker=db.execute('SELECT purpose FROM marketplace_shipping_host_marker').fetchone()
            if not marker or marker[0]!='sandbox_shipping_settings_only_v1':raise ValueError('shipping-only isolated marker required')
            return db
        except Exception:db.close();raise
    check=connect();check.close()
    studio=importlib.import_module('neonrest_sandbox.seller_studio');catalog=importlib.import_module('neonrest_sandbox.marketplace_catalog')
    policy=LivePolicy(core,studio,catalog)
    def factory():
        db=connect()
        try:refresh_mirror(db,session['user_id'],policy,int(time.time()));return db
        except Exception:db.close();raise
    def services(db):
        store=addresses.AddressStore(db,vault,policy)
        return views.PilotServices(db,policy,store,addresses.AddressResolver(store),None,None,None,shipping_settings=shipping.SellerShipping(db,vault,policy))
    app.config['MARKETPLACE_TEST_PILOT']=True
    original_loader=app.jinja_loader
    app.jinja_loader=ChoiceLoader([FileSystemLoader(str(Path(__file__).parent/'templates')),original_loader])
    views.register(app,factory,services,lambda uid:policy.adult(None,uid),allowed_users,'sandbox',settings_only=True)
    @app.context_processor
    def shipping_navigation():
        uid=session.get('user_id')
        return dict(sandbox_shipping_preview=type(uid) is int and uid in allowed_users and policy.adult(None,uid))
