"""Independent private shops with optional personal or Page identity links."""
import json
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from . import identity_pages as pages

class StudioError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status


def migrate_legacy(db):
    """Keep stable shop/listing keys while removing the legacy mandatory Page FK.

    Run only on a dedicated startup/migration connection outside a transaction.
    Rebuild follows SQLite's create/copy/drop/rename sequence. Child references
    keep the original table name; all existing columns and row values survive.
    """
    columns=[r[1] for r in db.execute('PRAGMA table_info(seller_shops)')]
    if not columns or 'identity_kind' in columns:return
    if db.in_transaction:raise RuntimeError('Shop migration requires a dedicated idle connection.')
    enabled=db.execute('PRAGMA foreign_keys').fetchone()[0]
    before=list(db.execute('PRAGMA foreign_key_check'))
    if before:raise RuntimeError('Resolve existing foreign-key errors before shop migration.')
    try:
        db.execute('PRAGMA foreign_keys=OFF');db.execute('BEGIN IMMEDIATE')
        if 'identity_kind' in [r[1] for r in db.execute('PRAGMA table_info(seller_shops)')]:
            db.commit();return
        db.execute('''CREATE TABLE seller_shops_standalone(page_id TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
        policies TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
        identity_kind TEXT NOT NULL DEFAULT 'personal' CHECK(identity_kind IN ('personal','page','none')),
        linked_page_id TEXT REFERENCES identity_pages(id),
        CHECK((identity_kind='page' AND linked_page_id IS NOT NULL) OR (identity_kind!='page' AND linked_page_id IS NULL)))''')
        db.execute('''INSERT INTO seller_shops_standalone SELECT page_id,owner_id,name,description,policies,revision,
        created_at,updated_at,'page',page_id FROM seller_shops''')
        db.execute('DROP TABLE seller_shops');db.execute('ALTER TABLE seller_shops_standalone RENAME TO seller_shops')
        if list(db.execute('PRAGMA foreign_key_check')):raise RuntimeError('Shop migration foreign-key check failed.')
        db.commit()
    except BaseException:
        db.rollback();raise
    finally:db.execute('PRAGMA foreign_keys='+str(int(enabled)))


def initialize(db):
    migrate_legacy(db)
    for sql in [
        '''CREATE TABLE IF NOT EXISTS seller_shops(page_id TEXT PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
        policies TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
        identity_kind TEXT NOT NULL DEFAULT 'personal' CHECK(identity_kind IN ('personal','page','none')),
        linked_page_id TEXT REFERENCES identity_pages(id),
        CHECK((identity_kind='page' AND linked_page_id IS NOT NULL) OR (identity_kind!='page' AND linked_page_id IS NULL)))''',
        'CREATE INDEX IF NOT EXISTS seller_shop_owner ON seller_shops(owner_id,page_id)',
        'CREATE INDEX IF NOT EXISTS seller_shop_page ON seller_shops(linked_page_id)',
        '''CREATE TABLE IF NOT EXISTS seller_listings(id TEXT PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),
        kind TEXT NOT NULL CHECK(kind IN ('physical','digital')),title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
        price_cents INTEGER NOT NULL CHECK(price_cents>=0),quantity INTEGER NOT NULL CHECK(quantity>=0),
        variations TEXT NOT NULL DEFAULT '[]',delivery TEXT NOT NULL DEFAULT '',license TEXT NOT NULL DEFAULT '',
        returns TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','archived')),
        revision INTEGER NOT NULL DEFAULT 0,created_by INTEGER NOT NULL REFERENCES users(id),updated_by INTEGER NOT NULL REFERENCES users(id),
        created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS seller_listing_shop ON seller_listings(shop_id,created_at,id)',
        '''CREATE TABLE IF NOT EXISTS seller_studio_events(id INTEGER PRIMARY KEY,shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),
        listing_id TEXT,actor_id INTEGER NOT NULL REFERENCES users(id),action TEXT NOT NULL,created_at INTEGER NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS seller_studio_history ON seller_studio_events(shop_id,id)']:
        db.execute(sql)


def clean(value,label,maximum,required=False):
    if not isinstance(value,str):raise StudioError('Enter '+label+'.')
    value=value.strip()
    if len(value)>maximum or (required and not value) or any(ord(c)<32 and c not in '\n\r\t' for c in value):raise StudioError('Check '+label+' (maximum '+str(maximum)+' characters).')
    return value


def money(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,2})?',value.strip()):raise StudioError('Use a USD price with at most two decimal places.')
    try:value=Decimal(value.strip())*100
    except InvalidOperation:raise StudioError('Enter a valid price.')
    return int(value)


def quantity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,7}',value) or int(value)>1000000:raise StudioError('Use a quantity from 0 to 1,000,000.')
    return int(value)


def adult_account(db,uid):
    # Marketplace eligibility is independent of business Pages or subscriptions.
    from . import age_policy
    if not pages.eligible(db,uid,'creative'):return False
    years=age_policy.age(db,uid)
    return years is not None and years>=18


def access(db,uid,page_id,owner_only=False):
    if not adult_account(db,uid):raise StudioError('Seller Studio is available to eligible adult accounts.',403)
    shop=db.execute('SELECT * FROM seller_shops WHERE page_id=?',(page_id,)).fetchone()
    if shop:
        if not adult_account(db,shop['owner_id']):raise StudioError('Shop unavailable.',404)
        if shop['identity_kind']!='page':
            if uid!=shop['owner_id']:raise StudioError('Shop unavailable.',404)
            user=db.execute('SELECT handle FROM users WHERE id=?',(shop['owner_id'],)).fetchone()
            return {'id':page_id,'owner_id':shop['owner_id'],'name':shop['name'],
                    'handle':user['handle'] if shop['identity_kind']=='personal' else 'Independent shop',
                    'state':'draft','kind':shop['identity_kind']},shop
        linked_id=shop['linked_page_id']
    else:linked_id=page_id
    try:page=pages.get(db,linked_id)
    except pages.PageError:raise StudioError('Shop unavailable.',404)
    if not adult_account(db,page['owner_id']) or pages.hidden(db,linked_id) or pages.role(db,page,uid) not in (('owner',) if owner_only else ('owner','manager','editor')):raise StudioError('Shop unavailable.',404)
    if shop and shop['owner_id']!=page['owner_id']:raise StudioError('This Page changed owners. Shop transfer needs support review.',409)
    context=dict(page);context['id']=page_id
    return context,shop


def event(db,page_id,uid,action,listing_id=None):
    db.execute('INSERT INTO seller_studio_events(shop_id,listing_id,actor_id,action,created_at) VALUES (?,?,?,?,?)',(page_id,listing_id,uid,action,int(time.time())))


def create_shop(db,uid,page_id):
    page,shop=access(db,uid,page_id,True)
    if page['state']=='archived':raise StudioError('Restore the Page before preparing its shop.',409)
    if shop:raise StudioError('This Page already has a shop draft.',409)
    if db.execute('SELECT COUNT(*) FROM seller_shops WHERE owner_id=?',(uid,)).fetchone()[0]>=20:raise StudioError('The initial limit is 20 shops per account.',409)
    now=int(time.time());db.execute("INSERT INTO seller_shops(page_id,owner_id,name,created_at,updated_at,identity_kind,linked_page_id) VALUES (?,?,?,?,?,'page',?)",(page_id,page['owner_id'],page['name'],now,now,page_id));event(db,page_id,uid,'create-shop')


def identity_choices(db,uid):
    return [dict(p) for p in db.execute("SELECT * FROM identity_pages WHERE owner_id=? AND state!='archived' ORDER BY handle LIMIT 20",(uid,)) if not pages.hidden(db,p['id'])]


def validate_identity(db,uid,kind,linked):
    if kind not in ('personal','page','none'):raise StudioError('Choose a shop identity.')
    if kind!='page':
        return None
    try:page=pages.get(db,linked)
    except pages.PageError:raise StudioError('Linked identity unavailable.',404)
    if page['owner_id']!=uid or page['state']=='archived' or pages.hidden(db,page['id']):raise StudioError('Link an available Page you own.',404)
    return page['id']


def create_independent(db,uid,name,kind='personal',linked=None):
    if not adult_account(db,uid):raise StudioError('Seller setup requires an eligible adult account.',403)
    name=clean(name,'shop name',80,True);linked=validate_identity(db,uid,kind,linked)
    if db.execute('SELECT COUNT(*) FROM seller_shops WHERE owner_id=?',(uid,)).fetchone()[0]>=20:raise StudioError('The initial limit is 20 shops per account.',409)
    key='shop_'+secrets.token_urlsafe(18);now=int(time.time())
    db.execute('''INSERT INTO seller_shops(page_id,owner_id,name,created_at,updated_at,identity_kind,linked_page_id)
    VALUES (?,?,?,?,?,?,?)''',(key,uid,name,now,now,kind,linked));event(db,key,uid,'create-independent-shop');return key


def set_identity(db,uid,shop_id,revision,kind,linked=None):
    # A transferred/archived Page must not trap the shop's actual owner. Only
    # that owner can unlink/relink; Page delegates never acquire shop ownership.
    if not adult_account(db,uid):raise StudioError('Seller setup requires an eligible adult account.',403)
    row=db.execute('SELECT * FROM seller_shops WHERE page_id=? AND owner_id=?',(shop_id,uid)).fetchone()
    if not row:raise StudioError('Shop unavailable.',404)
    linked=validate_identity(db,uid,kind,linked)
    r=db.execute('''UPDATE seller_shops SET identity_kind=?,linked_page_id=?,revision=revision+1,updated_at=?
    WHERE page_id=? AND owner_id=? AND revision=?''',(kind,linked,int(time.time()),shop_id,uid,revision))
    if r.rowcount!=1:raise StudioError('This shop changed. Reload before saving.',409)
    event(db,shop_id,uid,'link-identity:'+kind)


def save_shop(db,uid,page_id,revision,name,description,policies):
    page,shop=access(db,uid,page_id,True)
    if not shop:raise StudioError('Shop unavailable.',404)
    if page['state']=='archived':raise StudioError('Restore the Page before editing.',409)
    name=clean(name,'shop name',80,True);description=clean(description,'shop description',4000);policies=clean(policies,'shop policies',4000)
    r=db.execute('UPDATE seller_shops SET name=?,description=?,policies=?,revision=revision+1,updated_at=? WHERE page_id=? AND revision=?',(name,description,policies,int(time.time()),page_id,revision))
    if r.rowcount!=1:raise StudioError('This shop changed. Reload before saving.',409)
    event(db,page_id,uid,'edit-shop')


def listing_fields(form):
    kind=form.get('kind')
    if kind not in ('physical','digital'):raise StudioError('Choose a physical item or digital download draft.')
    values={k:clean(form.get(k,''),label,limit,k=='title') for k,label,limit in [('title','listing title',120),('description','listing description',8000),('delivery','delivery terms',2000),('license','usage rights',2000),('returns','return/refund terms',2000)]}
    values.update(kind=kind,price_cents=money(form.get('price','')),quantity=quantity(form.get('quantity','')))
    labels=form.getlist('variation_label');prices=form.getlist('variation_price');quantities=form.getlist('variation_quantity')
    if not len(labels)==len(prices)==len(quantities) or len(labels)>10:raise StudioError('Use at most ten complete variation rows.')
    variants=[];seen=set()
    for label,price,count in zip(labels,prices,quantities):
        if not label.strip() and not price.strip() and not count.strip():continue
        label=clean(label,'variation label',80,True)
        if label.casefold() in seen:raise StudioError('Variation labels must be distinct.')
        seen.add(label.casefold());variants.append({'label':label,'price_cents':money(price) if price.strip() else values['price_cents'],'quantity':quantity(count)})
    if variants:
        total=sum(v['quantity'] for v in variants)
        if total>1000000:raise StudioError('Total variation quantity exceeds 1,000,000.')
        values['quantity']=total
    values['variations']=json.dumps(variants,ensure_ascii=False)
    return values


def get_listing(db,uid,page_id,listing_id):
    page,shop=access(db,uid,page_id)
    listing=db.execute('SELECT * FROM seller_listings WHERE id=? AND shop_id=?',(listing_id,page_id)).fetchone()
    if not shop or not listing:raise StudioError('Listing unavailable.',404)
    return page,shop,listing


def save_listing(db,uid,page_id,form,listing_id=None):
    editing=listing_id is not None
    page,shop=access(db,uid,page_id)
    if not shop:raise StudioError('Create a shop draft first.',404)
    if page['state']=='archived':raise StudioError('Restore the Page before editing.',409)
    if listing_id:
        _,_,old=get_listing(db,uid,page_id,listing_id)
        if old['state']!='draft':raise StudioError('Restore the listing before editing.',409)
    elif db.execute('SELECT COUNT(*) FROM seller_listings WHERE shop_id=?',(page_id,)).fetchone()[0]>=100:raise StudioError('The initial limit is 100 listing drafts per shop.',409)
    fields=listing_fields(form);now=int(time.time())
    if listing_id and fields['kind']=='physical' and db.execute("SELECT 1 FROM seller_assets WHERE listing_id=? AND kind='file' AND state='active'",(listing_id,)).fetchone():raise StudioError('Remove the active product download before changing to a physical listing.',409)
    if listing_id:
        revision=form.get('revision',type=int)
        if revision is None or not 0<=revision<2**63:raise StudioError('Reload before saving.',409)
        r=db.execute('''UPDATE seller_listings SET kind=:kind,title=:title,description=:description,price_cents=:price_cents,
        quantity=:quantity,variations=:variations,delivery=:delivery,license=:license,returns=:returns,
        revision=revision+1,updated_by=:uid,updated_at=:now WHERE id=:id AND shop_id=:shop AND revision=:revision''',dict(fields,uid=uid,now=now,id=listing_id,shop=page_id,revision=revision))
        if r.rowcount!=1:raise StudioError('This listing changed. Reload before saving.',409)
    else:
        listing_id=secrets.token_urlsafe(18)
        db.execute('''INSERT INTO seller_listings(id,shop_id,kind,title,description,price_cents,quantity,variations,delivery,license,returns,created_by,updated_by,created_at,updated_at)
        VALUES (:id,:shop,:kind,:title,:description,:price_cents,:quantity,:variations,:delivery,:license,:returns,:uid,:uid,:now,:now)''',dict(fields,id=listing_id,shop=page_id,uid=uid,now=now))
    event(db,page_id,uid,'edit-listing' if editing else 'create-listing',listing_id)
    return listing_id


def set_state(db,uid,page_id,listing_id,revision,state):
    page,shop,listing=get_listing(db,uid,page_id,listing_id)
    if page['state']=='archived':raise StudioError('Restore the Page before editing.',409)
    if state not in ('draft','archived'):raise StudioError('Publishing and sales are not enabled.',403)
    r=db.execute('UPDATE seller_listings SET state=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND shop_id=? AND revision=?',(state,uid,int(time.time()),listing_id,page_id,revision))
    if r.rowcount!=1:raise StudioError('This listing changed. Reload before saving.',409)
    event(db,page_id,uid,'state:'+state,listing_id)


def export_user(db,uid):
    # Ownership changes freeze access; do not expose a prior owner's commercial drafts.
    shops=[dict(r) for r in db.execute('SELECT * FROM seller_shops WHERE owner_id=? ORDER BY page_id',(uid,))]
    ids=[s['page_id'] for s in shops];listings=[]
    for page_id in ids:listings.extend(dict(r) for r in db.execute('SELECT * FROM seller_listings WHERE shop_id=? ORDER BY id',(page_id,)))
    benefits=[dict(r) for r in db.execute('SELECT * FROM marketplace_shop_benefits WHERE owner_id=? ORDER BY shop_id',(uid,))]
    return {'shops':shops,'listings':listings,'fee_benefits':benefits}


def register(app,core):
    from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for
    bp=Blueprint('seller_studio',__name__)
    from . import marketplace_catalog as catalog
    with app.app_context():
        db=core.get_db();db.commit();initialize(db);catalog.initialize(db);db.commit()
    @bp.errorhandler(StudioError)
    def failure(error):
        unsaved=[]
        if request.method=='POST' and error.status in (400,409):
            for key,label in [('name','Shop name'),('listing_identity','Listing identity'),('title','Listing title'),('kind','Product type'),('description','Description'),('policies','Shop policies'),('price','Base price'),('quantity','Quantity'),('variation_label','Variation labels'),('variation_price','Variation prices'),('variation_quantity','Variation quantities'),('delivery','Delivery terms'),('license','Usage rights'),('returns','Return/refund terms')]:
                values=request.form.getlist(key)
                if values:unsaved.append((label,'\n'.join(values)[:10000]))
        return render_template('seller_studio.html',error=str(error),view='error',unsaved=unsaved),error.status
    def actor():
        uid=session.get('user_id')
        if type(uid) is not int:abort(401)
        if not adult_account(core.get_db(),uid):raise StudioError('Seller Studio is available to eligible adult accounts.',403)
        return uid
    def writing():
        helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
        if not helpers['fresh']():return redirect(url_for('community_reauth',next=request.path))
        return helpers['limited']('seller-studio',60)
    def revision():
        n=request.form.get('revision',type=int)
        if n is None or not 0<=n<2**63:raise StudioError('Reload before saving.',409)
        return n
    @bp.get('/marketplace')
    def marketplace():
        results=catalog.browse(core.get_db(),session.get('user_id'),request.args.get('q',''),request.args.get('sort','newest'),request.args.get('page','1'))
        return render_template('marketplace.html',catalog_images=catalog.images,**results)
    @bp.get('/marketplace/listings/<listing_id>')
    def public_listing(listing_id):
        item=catalog.detail(core.get_db(),session.get('user_id'),listing_id)
        return render_template('marketplace_listing.html',item=item,variants=json.loads(item['variations']),image_ids=catalog.images(item))
    @bp.get('/marketplace/listings/<listing_id>/images/<asset_id>')
    def public_image(listing_id,asset_id):
        import hashlib,io
        from flask import send_file
        from .marketplace_assets import folder,MAX_UPLOAD
        from .media_export import open_regular
        db=core.get_db();item=catalog.detail(db,session.get('user_id'),listing_id)
        if asset_id not in catalog.images(item):abort(404)
        asset=db.execute("SELECT * FROM seller_assets WHERE id=? AND listing_id=? AND kind='image' AND state='active'",(asset_id,listing_id)).fetchone()
        if not asset or not adult_account(db,asset['uploader_id']):abort(404)
        try:
            with open_regular(folder(app),asset['storage_key']) as file:data=file.read(MAX_UPLOAD+1)
        except OSError:abort(404)
        if len(data)!=asset['bytes'] or hashlib.sha256(data).hexdigest()!=asset['sha256']:abort(404)
        response=send_file(io.BytesIO(data),mimetype='image/webp',conditional=False,etag=False,max_age=0)
        response.headers['X-Content-Type-Options']='nosniff';return response
    @bp.route('/marketplace/listings/new',methods=['GET','POST'])
    def new_listing():
        uid=actor();db=core.get_db()
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE')
                identity=request.form.get('listing_identity','personal')
                if identity=='personal':kind='personal';linked=None
                elif isinstance(identity,str) and identity.startswith('page:') and len(identity)<=100:kind='page';linked=identity[5:]
                else:raise StudioError('Choose your personal profile or an owned Page.')
                linked=validate_identity(db,uid,kind,linked)
                existing=db.execute('''SELECT page_id FROM seller_shops WHERE owner_id=? AND identity_kind=?
                AND (linked_page_id=? OR (linked_page_id IS NULL AND ? IS NULL)) ORDER BY created_at,page_id LIMIT 1''',(uid,kind,linked,linked)).fetchone()
                if existing:key=existing['page_id']
                else:
                    label=pages.get(db,linked)['name'] if linked else db.execute('SELECT handle FROM users WHERE id=?',(uid,)).fetchone()['handle']
                    key=create_independent(db,uid,(label+' shop')[:80],kind,linked)
                listing_id=save_listing(db,uid,key,request.form)
            flash('Listing draft saved privately. Nothing was published or charged.','success')
            return redirect(url_for('seller_studio.listing',page_id=key,listing_id=listing_id))
        return render_template('seller_studio.html',view='listing',quick_listing=True,choices=identity_choices(db,uid),
                               page={'state':'draft'},shop=None,item=None,variants=[],assets=[])
    @bp.route('/marketplace/studio/new',methods=['GET','POST'])
    def new():
        uid=actor();db=core.get_db()
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE')
                key=create_independent(db,uid,request.form.get('name',''),request.form.get('identity_kind','personal'),request.form.get('linked_page_id') or None)
            flash('Independent shop draft created. Nothing was published or charged.','success')
            return redirect(url_for('seller_studio.shop',page_id=key))
        return render_template('seller_studio.html',view='new',choices=identity_choices(db,uid))
    @bp.route('/marketplace/studio/<page_id>/identity',methods=['GET','POST'])
    def identity(page_id):
        uid=actor();db=core.get_db()
        owned=db.execute('SELECT * FROM seller_shops WHERE page_id=? AND owner_id=?',(page_id,uid)).fetchone()
        if not owned:raise StudioError('Shop unavailable.',404)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');set_identity(db,uid,page_id,revision(),request.form.get('identity_kind'),request.form.get('linked_page_id') or None)
            flash('Shop identity updated. Shop ownership, drafts and files are unchanged.','success')
            return redirect(url_for('seller_studio.shop',page_id=page_id))
        return render_template('seller_studio.html',view='identity',shop=owned,choices=identity_choices(db,uid))
    @bp.get('/marketplace/studio')
    def index():
        uid=actor();db=core.get_db();available=[]
        rows=db.execute('''SELECT DISTINCT s.* FROM seller_shops s LEFT JOIN identity_page_members m ON m.page_id=s.linked_page_id
        WHERE s.owner_id=? OR m.user_id=? ORDER BY s.updated_at DESC,s.page_id LIMIT 60''',(uid,uid)).fetchall()
        for row in rows:
            try:page,shop=access(db,uid,row['page_id'])
            except StudioError:
                if row['owner_id']==uid:available.append({'shop':row,'owner':True,'frozen':True})
                continue
            available.append({'page':page,'shop':shop,'owner':shop['owner_id']==uid,'frozen':False})
        return render_template('seller_studio.html',view='index',available=available)
    @bp.route('/marketplace/studio/<page_id>',methods=['GET','POST'])
    def shop(page_id):
        uid=actor();db=core.get_db();page,shop=access(db,uid,page_id)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE')
                action=request.form.get('action')
                if action=='create':create_shop(db,uid,page_id)
                elif action=='save':save_shop(db,uid,page_id,revision(),request.form.get('name',''),request.form.get('description',''),request.form.get('policies',''))
                else:raise StudioError('Publishing and sales are not enabled.',403)
            flash('Shop draft saved. Nothing was published or charged.','success');return redirect(url_for('seller_studio.shop',page_id=page_id))
        listings=db.execute('SELECT * FROM seller_listings WHERE shop_id=? ORDER BY created_at DESC,id LIMIT 100',(page_id,)).fetchall() if shop else []
        return render_template('seller_studio.html',view='shop',page=page,shop=shop,listings=listings,owner=page['owner_id']==uid,fees_waived=catalog.fee_policy(db,shop) if shop else False)
    @bp.route('/marketplace/studio/<page_id>/listing/new',methods=['GET','POST'])
    @bp.route('/marketplace/studio/<page_id>/listing/<listing_id>',methods=['GET','POST'])
    def listing(page_id,listing_id=None):
        uid=actor();db=core.get_db();page,shop=access(db,uid,page_id);item=None
        if not shop:raise StudioError('Shop unavailable.',404)
        if listing_id:page,shop,item=get_listing(db,uid,page_id,listing_id)
        if request.method=='POST':
            response=writing()
            if response is not None:return response
            with db:
                db.execute('BEGIN IMMEDIATE');action=request.form.get('action','save')
                if action=='save':listing_id=save_listing(db,uid,page_id,request.form,listing_id)
                elif action=='state' and listing_id:set_state(db,uid,page_id,listing_id,revision(),request.form.get('state'))
                else:raise StudioError('Publishing and sales are not enabled.',403)
            flash('Listing draft saved. Nothing was published or charged.','success');return redirect(url_for('seller_studio.listing',page_id=page_id,listing_id=listing_id))
        variants=json.loads(item['variations']) if item else []
        from .marketplace_assets import visible_assets
        assets=visible_assets(db,listing_id) if item else []
        return render_template('seller_studio.html',view='listing',page=page,shop=shop,item=item,variants=variants,assets=assets)
    @bp.get('/marketplace/studio/<page_id>/listing/<listing_id>/preview')
    def preview(page_id,listing_id):
        uid=actor();page,shop,item=get_listing(core.get_db(),uid,page_id,listing_id)
        from .marketplace_assets import visible_assets
        return render_template('seller_studio.html',view='preview',page=page,shop=shop,item=item,variants=json.loads(item['variations']),assets=visible_assets(core.get_db(),listing_id))
    @bp.after_request
    def private(response):
        response.headers.update({'Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})
        return response
    app.register_blueprint(bp)


