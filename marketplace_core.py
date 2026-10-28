"""Provider-independent marketplace money and shipping contracts.

No payment/label calls or live activation. Callers must perform authentication,
role and eligibility checks; these functions additionally scope shipping rows.
"""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

LISTING_CENTS = 10
PLATFORM_BASIS_POINTS = 600
CSV_FIELDS = ('Order Reference','Shipment Reference','Recipient','Company','Address 1','Address 2','City','State','ZIP','Country','Weight Ounces','Length Inches','Width Inches','Height Inches')
MAX_ROWS = 1000
MAX_CSV_BYTES = 2 * 1024 * 1024

class InvalidCommerce(ValueError): pass

def cents(value):
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise InvalidCommerce('Expected bounded nonnegative integer USD cents.')
    return value

def quote(subtotal, shipping=0, tax=0, discount=0, kind='physical'):
    for v in (subtotal,shipping,tax,discount): cents(v)
    if kind not in ('physical','digital','commission','membership') or discount > subtotal:
        raise InvalidCommerce('Invalid product or discount.')
    if kind != 'physical' and shipping:
        raise InvalidCommerce('Only physical goods have shipping.')
    net = subtotal - discount
    return {'currency':'USD','kind':kind,'subtotal':subtotal,'discount':discount,'shipping':shipping,'tax':tax,
            'total':net+shipping+tax,'platform_fee':(net*PLATFORM_BASIS_POINTS+5000)//10000,
            'processor_fee':None,'fee_version':'2026-10-27-v1'}

def commission_refund(item_refunded, original_item_total, original_fee, already_credited=0):
    """Cumulative credit; difference avoids over-refunding repeated small refunds."""
    for v in (item_refunded,original_item_total,original_fee,already_credited): cents(v)
    if not original_item_total or item_refunded > original_item_total or already_credited > original_fee:
        raise InvalidCommerce('Invalid cumulative refund.')
    target=(original_fee*item_refunded+original_item_total//2)//original_item_total
    if target < already_credited: raise InvalidCommerce('Refund totals moved backwards.')
    return target-already_credited

def text(value, maximum=250):
    value='' if value is None else str(value)
    if len(value)>maximum or any(ord(c)<32 or ord(c)==127 for c in value) or value.lstrip().startswith(('=','+','-','@')):
        raise InvalidCommerce('Unsafe spreadsheet cell. Correct it before export/import.')
    return value

def ref(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):
        raise InvalidCommerce('Invalid order/shipment reference.')
    return value

def measurement(value):
    if value in ('',None): return ''
    try: number=Decimal(str(value))
    except InvalidOperation: raise InvalidCommerce('Invalid parcel measurement.')
    if not number.is_finite() or number<=0 or number>100000: raise InvalidCommerce('Invalid parcel measurement.')
    return format(number,'f')

def shipping_csv(seller_id, parcels):
    """One row per selected paid parcel. Never scans or exports unrelated orders.

    Postal codes are supplied as strings and preserved verbatim. Spreadsheet
    importers must map ZIP/reference columns as text (documented in the UI).
    """
    if type(seller_id) is not int or seller_id<=0: raise InvalidCommerce('Seller required.')
    if not isinstance(parcels,list) or len(parcels)>MAX_ROWS: raise InvalidCommerce('Too many parcels.')
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=CSV_FIELDS);writer.writeheader();seen=set()
    for parcel in parcels:
        if parcel.get('seller_id')!=seller_id or parcel.get('payment_status')!='paid' or parcel.get('kind')!='physical' or parcel.get('shipment_status')!='unshipped':
            raise InvalidCommerce('Only this seller’s paid unshipped physical parcels can be exported.')
        order=ref(parcel.get('order_ref'));shipment=ref(parcel.get('shipment_ref'))
        if (order,shipment) in seen: raise InvalidCommerce('Duplicate parcel.')
        seen.add((order,shipment));address=parcel.get('address',{})
        if not isinstance(address.get('zip'),str): raise InvalidCommerce('ZIP must remain text.')
        row={'Order Reference':order,'Shipment Reference':shipment}
        for heading,key in [('Recipient','recipient'),('Company','company'),('Address 1','line1'),('Address 2','line2'),('City','city'),('State','state'),('ZIP','zip'),('Country','country')]:
            row[heading]=text(address.get(key))
        if not all(row[k] for k in ('Recipient','Address 1','City','State','ZIP')) or row['Country']!='US':
            raise InvalidCommerce('Complete domestic US delivery address required.')
        for heading,key in [('Weight Ounces','weight_oz'),('Length Inches','length_in'),('Width Inches','width_in'),('Height Inches','height_in')]:row[heading]=measurement(parcel.get(key))
        writer.writerow(row)
        if out.tell()>MAX_CSV_BYTES:raise InvalidCommerce('Shipping export too large.')
    result=out.getvalue().encode('utf-8-sig')
    if len(result)>MAX_CSV_BYTES:raise InvalidCommerce('Shipping export too large.')
    return result

def tracking_preview(seller_id, raw, authorized_shipments):
    """Validate normalized CSV into a dry-run plan; no database writes/messages.

    UI adapter maps actual provider headings to these four columns before use.
    authorized_shipments maps (order_ref,shipment_ref) to authoritative records.
    Caller rechecks the same state inside a transaction before applying a plan.
    """
    if type(seller_id) is not int or seller_id<=0 or not isinstance(raw,bytes) or len(raw)>MAX_CSV_BYTES:
        raise InvalidCommerce('Invalid tracking import.')
    try: reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
    except UnicodeError: raise InvalidCommerce('Use a UTF-8 spreadsheet export.')
    expected=['Order Reference','Shipment Reference','Carrier','Tracking Number']
    if reader.fieldnames!=expected: raise InvalidCommerce('Map tracking columns before import.')
    results=[];seen={}
    for n,row in enumerate(reader):
        if n>=MAX_ROWS or None in row or any(v is None for v in row.values()):raise InvalidCommerce('Malformed or oversized tracking import.')
        key=(ref(row['Order Reference']),ref(row['Shipment Reference']));record=authorized_shipments.get(key)
        if not record or record.get('seller_id')!=seller_id or record.get('payment_status')!='paid' or record.get('kind')!='physical':raise InvalidCommerce('Shipment unavailable to this seller.')
        carrier=text(row['Carrier'],30);tracking=text(row['Tracking Number'],100)
        if carrier not in ('USPS','UPS','FedEx','DHL') or not re.fullmatch(r'[A-Za-z0-9-]{6,100}',tracking):raise InvalidCommerce('Invalid carrier or tracking number.')
        proposed=(carrier,tracking);current=(record.get('carrier'),record.get('tracking'))
        if record.get('shipment_status') not in ('unshipped','shipped') or (current[1] and current!=proposed):raise InvalidCommerce('Existing shipment needs manual review.')
        if key in seen:
            if seen[key]!=proposed:raise InvalidCommerce('Conflicting duplicate tracking.')
            continue
        seen[key]=proposed;results.append({'order_ref':key[0],'shipment_ref':key[1],'carrier':carrier,'tracking':tracking,'action':'unchanged' if current==proposed else 'set_tracking'})
    return results
