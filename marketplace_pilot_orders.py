"""Private test receipts and single-package manual tracking; no postage purchases."""
import re
if __package__:
    from . import marketplace_checkout as checkout,marketplace_inventory as inventory,marketplace_refunds as refunds
else:
    import marketplace_checkout as checkout,marketplace_inventory as inventory,marketplace_refunds as refunds


class OrderError(ValueError):pass


SCHEMA='''
CREATE TABLE IF NOT EXISTS marketplace_pilot_destinations(
 order_id TEXT PRIMARY KEY REFERENCES marketplace_checkout_orders(id),buyer_id INTEGER NOT NULL REFERENCES users(id),
 destination_id TEXT NOT NULL REFERENCES marketplace_address_books(id));
CREATE TRIGGER IF NOT EXISTS marketplace_pilot_destination_immutable BEFORE UPDATE ON marketplace_pilot_destinations
BEGIN SELECT RAISE(ABORT,'order destination binding is immutable'); END;
CREATE TABLE IF NOT EXISTS marketplace_pilot_fulfillment_views(
 id INTEGER PRIMARY KEY,order_id TEXT NOT NULL REFERENCES marketplace_test_settlements(order_id),
 actor_id INTEGER NOT NULL REFERENCES users(id),destination_version TEXT NOT NULL REFERENCES marketplace_address_versions(id),viewed_at INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS marketplace_pilot_view_immutable BEFORE UPDATE ON marketplace_pilot_fulfillment_views
BEGIN SELECT RAISE(ABORT,'fulfillment audit is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_pilot_view_retained BEFORE DELETE ON marketplace_pilot_fulfillment_views
BEGIN SELECT RAISE(ABORT,'fulfillment audit is retained'); END;
CREATE TABLE IF NOT EXISTS marketplace_pilot_shipments(
 order_id TEXT PRIMARY KEY REFERENCES marketplace_test_settlements(order_id),owner_id INTEGER NOT NULL REFERENCES users(id),
 request_key TEXT NOT NULL,carrier TEXT NOT NULL,tracking TEXT NOT NULL,shipped_at INTEGER NOT NULL,
 UNIQUE(owner_id,request_key));
CREATE TRIGGER IF NOT EXISTS marketplace_pilot_shipment_immutable BEFORE UPDATE ON marketplace_pilot_shipments
BEGIN SELECT RAISE(ABORT,'shipment record is immutable'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_pilot_shipment_retained BEFORE DELETE ON marketplace_pilot_shipments
BEGIN SELECT RAISE(ABORT,'shipment record is retained'); END;
'''


def initialize(db):
    if db.in_transaction:raise OrderError('dedicated connection required')
    db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nCOMMIT;')


def receipt(db,uid,order_id,now,policy=checkout.NeonrestPolicy):
    order=checkout.get_order(db,'test',uid,order_id,now,policy)
    row=db.execute('SELECT buyer_id,seller_owner_id FROM marketplace_checkout_orders WHERE id=?',(order_id,)).fetchone()
    quote=db.execute('''SELECT q.snapshot FROM marketplace_test_settlements w
      JOIN marketplace_checkout_quotes q ON q.id=w.quote_id WHERE w.order_id=?''',(order_id,)).fetchone()
    if not quote:
        quote=db.execute('''SELECT q.snapshot FROM marketplace_checkout_quote_acceptances a
          JOIN marketplace_checkout_quotes q ON q.id=a.quote_id WHERE a.order_id=?''',(order_id,)).fetchone()
    if not quote:
        quote=db.execute('SELECT snapshot FROM marketplace_checkout_quotes WHERE order_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(order_id,)).fetchone()
    import json
    result=dict(order=order,buyer=uid==row['buyer_id'],seller=uid==row['seller_owner_id'],quote=json.loads(quote[0]) if quote else None,refund=None,shipment=None)
    result['payment_status']=None
    attempt=db.execute('SELECT observed_status FROM marketplace_payment_test_attempts WHERE order_id=? ORDER BY created_at DESC LIMIT 1',(order_id,)).fetchone()
    if attempt:result['payment_status']=attempt[0]
    if order['state']=='test_settled':result['refund']=refunds.get_summary(db,uid,order_id,now,policy)
    result['display_state']=result['refund']['state'] if result['refund'] else ('test_payment_failed' if result['payment_status']=='failed' else order['state'])
    result['refund_remaining']={}
    if result['refund']:
        reserved=db.execute("""SELECT COALESCE(SUM(r.item_cents),0),COALESCE(SUM(r.shipping_cents),0),COALESCE(SUM(r.tax_cents),0)
          FROM marketplace_test_refund_requests r JOIN marketplace_test_refund_jobs j ON j.request_id=r.id
          WHERE r.order_id=? AND j.state NOT IN ('failed','withdrawn')""",(order_id,)).fetchone()
        for key,total,used in zip(('item_cents','shipping_cents','tax_cents'),(result['quote']['subtotal_cents'],result['quote']['shipping_cents'],result['quote']['tax_cents']),reserved):
            result['refund_remaining'][key]=max(0,total-used)
    shipment=db.execute('SELECT carrier,tracking,shipped_at FROM marketplace_pilot_shipments WHERE order_id=?',(order_id,)).fetchone()
    if shipment:result['shipment']=dict(shipment)
    return result


def record_shipment(db,owner,order_id,request_key,carrier,tracking,now,policy=checkout.NeonrestPolicy):
    inventory.clock(now);inventory.identity('test',request_key)
    if carrier not in ('USPS','UPS','FedEx','DHL'):raise OrderError('choose a supported tracking carrier')
    if not isinstance(tracking,str) or not re.fullmatch(r'[A-Za-z0-9-]{6,64}',tracking):raise OrderError('enter a valid tracking number')
    with inventory.transaction(db):
        order=checkout.get_order(db,'test',owner,order_id,now,policy)
        row=db.execute('SELECT * FROM marketplace_checkout_orders WHERE id=?',(order_id,)).fetchone()
        if owner!=row['seller_owner_id']:raise OrderError('original seller owner required')
        if order['state']!='test_settled':raise OrderError('confirmed test payment required before shipment')
        refund=refunds.get_summary(db,owner,order_id,now,policy)
        reserved=db.execute('''SELECT 1 FROM marketplace_test_refund_requests r JOIN marketplace_test_refund_jobs j ON j.request_id=r.id
          WHERE r.order_id=? AND j.state NOT IN ('failed','withdrawn') LIMIT 1''',(order_id,)).fetchone()
        if reserved or refund['refunded_cents']:raise OrderError('refund activity requires shipment review')
        old=db.execute('SELECT * FROM marketplace_pilot_shipments WHERE order_id=?',(order_id,)).fetchone()
        if old:
            if (old['owner_id'],old['request_key'],old['carrier'],old['tracking'])!=(owner,request_key,carrier,tracking):raise OrderError('shipment already recorded; corrections need review')
            return dict(old)
        db.execute('INSERT INTO marketplace_pilot_shipments VALUES (?,?,?,?,?,?)',(order_id,owner,request_key,carrier,tracking,now))
        return dict(order_id=order_id,carrier=carrier,tracking=tracking,shipped_at=now)


def paid_destination(db,store,owner,order_id,now,policy=checkout.NeonrestPolicy):
    """Original seller only; grants no access to other address-book entries."""
    order=checkout.get_order(db,'test',owner,order_id,now,policy)
    row=db.execute('SELECT seller_owner_id,buyer_id FROM marketplace_checkout_orders WHERE id=?',(order_id,)).fetchone()
    if row['seller_owner_id']!=owner or order['state']!='test_settled':raise OrderError('paid order and original seller owner required')
    snap=db.execute('''SELECT s.destination_book,s.destination_version,s.buyer_id FROM marketplace_test_settlements w
      JOIN marketplace_checkout_quotes q ON q.id=w.quote_id
      JOIN marketplace_address_snapshots s ON s.id=json_extract(q.snapshot,'$.location.version')
      WHERE w.order_id=? AND s.buyer_id=?''',(order_id,row['buyer_id'])).fetchone()
    if not snap:raise OrderError('paid destination snapshot unavailable')
    with inventory.transaction(db):
        checkout.get_order(db,'test',owner,order_id,now,policy)
        # _open validates ciphertext, owner and immutable version bindings. This
        # is narrowly scoped seller fulfillment access, not a public address API.
        book=store._owned(snap['buyer_id'],snap['destination_book'])
        version,address=store._open(book,snap['destination_version'])
        db.execute('INSERT INTO marketplace_pilot_fulfillment_views(order_id,actor_id,destination_version,viewed_at) VALUES (?,?,?,?)',(order_id,owner,version['id'],now))
        return address
