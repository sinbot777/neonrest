"""Read-only listing discovery. Private drafts and test orders are never inventory.

Publications require a separate trusted release workflow, still disabled. This
module exposes no publish endpoint and never treats a test order as a sale.
"""
import json
from .seller_studio import StudioError,adult_account

SORTS={'newest':'Newest','best_selling':'Best selling','price_low':'Price: low to high','price_high':'Price: high to low','oldest':'Oldest'}
PAGE_SIZE=24


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS marketplace_publications(
    listing_id TEXT PRIMARY KEY REFERENCES seller_listings(id),
    listing_revision INTEGER NOT NULL CHECK(listing_revision>=0),
    published_at INTEGER NOT NULL CHECK(published_at>=0),
    state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','withdrawn')),
    image_ids TEXT NOT NULL DEFAULT '[]',source_url TEXT NOT NULL DEFAULT '')''')
    db.execute('CREATE INDEX IF NOT EXISTS marketplace_publication_order ON marketplace_publications(state,published_at DESC,listing_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS marketplace_shop_benefits(
    shop_id TEXT PRIMARY KEY REFERENCES seller_shops(page_id),owner_id INTEGER NOT NULL REFERENCES users(id),
    platform_fees_waived INTEGER NOT NULL CHECK(platform_fees_waived IN (0,1)),reason TEXT NOT NULL,created_at INTEGER NOT NULL)''')


def fee_policy(db,shop):
    row=db.execute('SELECT platform_fees_waived FROM marketplace_shop_benefits WHERE shop_id=? AND owner_id=?',(shop['page_id'],shop['owner_id'])).fetchone()
    return bool(row and row[0])


def shop_quote(db,shop,subtotal,kind):
    from .marketplace_core import quote
    result=quote(subtotal,kind=kind)
    if fee_policy(db,shop):result.update(platform_fee=0,fee_version='2026-10-28-owner-comp-v1',platform_fees_waived=True)
    return result


def options(query='',sort='newest',page='1'):
    if not isinstance(query,str) or len(query)>120 or any(ord(c)<32 or ord(c)==127 for c in query):raise StudioError('Search using up to 120 characters.')
    if sort not in SORTS:raise StudioError('Choose a listed sort order.')
    if not isinstance(page,str) or len(page)>4 or not page.isascii() or not page.isdecimal() or not 1<=int(page)<=1000:raise StudioError('Choose a valid results page.')
    return query.strip(),sort,int(page)


def allowed(db,row,viewer):
    from . import age_policy,identity_pages as pages
    from .community_features import blocked
    if not adult_account(db,row['owner_id']):return False
    if viewer and (blocked(db,row['owner_id'],viewer) or not age_policy.can_read(db,row['owner_id'],viewer) or db.execute('SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?',(viewer,row['owner_id'])).fetchone()):return False
    if row['identity_kind']=='page':
        try:p=pages.get(db,row['linked_page_id'])
        except pages.PageError:return False
        if p['owner_id']!=row['owner_id'] or p['state']=='archived' or pages.hidden(db,p['id']):return False
    return True


SELECT='''SELECT l.*,s.name AS shop_name,s.owner_id,s.identity_kind,s.linked_page_id,
u.handle AS seller_handle,p.published_at,p.image_ids,p.source_url FROM marketplace_publications p
JOIN seller_listings l ON l.id=p.listing_id JOIN seller_shops s ON s.page_id=l.shop_id
JOIN users u ON u.id=s.owner_id
WHERE p.state='active' AND p.listing_revision=l.revision AND l.state='draft' '''


def browse(db,viewer,query='',sort='newest',page='1'):
    query,sort,page=options(query,sort,page)
    # Payment acceptance does not exist yet. Best-selling has no sales rank;
    # its documented tie-break is newest. Never count unpaid rehearsal orders.
    order={'newest':'p.published_at DESC,l.id','best_selling':'p.published_at DESC,l.id',
           'oldest':'p.published_at,l.id','price_low':'l.price_cents,p.published_at DESC,l.id',
           'price_high':'l.price_cents DESC,p.published_at DESC,l.id'}[sort]
    needle='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=db.execute(SELECT+" AND (l.title LIKE ? ESCAPE '\\' OR l.description LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\') ORDER BY "+order+' LIMIT ? OFFSET ?',
                    (needle,needle,needle,PAGE_SIZE+1,(page-1)*PAGE_SIZE)).fetchall()
    return {'items':[dict(row) for row in rows[:PAGE_SIZE] if allowed(db,row,viewer)],'has_next':len(rows)>PAGE_SIZE,
            'page':page,'query':query,'sort':sort,'sorts':SORTS,'sales_ranking_available':False}


def detail(db,viewer,listing_id):
    row=db.execute(SELECT+' AND l.id=?',(listing_id,)).fetchone()
    if not row or not allowed(db,row,viewer):raise StudioError('Listing unavailable.',404)
    return dict(row)


def images(row):
    try:ids=json.loads(row['image_ids'])
    except (ValueError,TypeError):return []
    return ids[:5] if isinstance(ids,list) and all(isinstance(v,str) for v in ids) else []
