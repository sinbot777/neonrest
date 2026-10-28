"""Private draft product uploads using existing durable quota admission."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import time
import zipfile
from .seller_studio import StudioError, get_listing, event

MAX_UPLOAD=5*1024*1024
MAX_IMAGE=2*1024*1024


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS seller_assets(id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL REFERENCES seller_shops(page_id),listing_id TEXT NOT NULL REFERENCES seller_listings(id),
    uploader_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL CHECK(kind IN ('image','file')),
    storage_key TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,mime TEXT NOT NULL,bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','archived')),created_at INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS seller_assets_listing ON seller_assets(listing_id,state,kind)')


def folder(app):return Path(app.instance_path)/'marketplace'


def prepare(raw,name,kind):
    if type(raw) is not bytes or not raw or len(raw)>MAX_UPLOAD:raise StudioError('Choose a nonempty file up to 5 MiB.',413)
    name=PurePosixPath(str(name).replace('\\','/')).name
    name=''.join(c for c in name if ord(c)>=32 and ord(c)!=127)[:120] or 'Uploaded product file'
    if kind=='image':
        from PIL import Image,ImageOps
        from .storage_writers import encode,OutputTooLarge
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>25000000:raise ValueError()
                image=ImageOps.exif_transpose(image);image.thumbnail((1600,1600));image=image.convert('RGBA' if 'A' in image.getbands() else 'RGB');image.info.clear()
                data=encode(image,MAX_IMAGE,'WEBP',quality=90,method=4)
        except OutputTooLarge:raise StudioError('The processed image is too large. Choose a smaller image.',413)
        except Exception:raise StudioError('Choose a valid JPEG, PNG or WebP image.')
        return data,name,'.webp','image/webp'
    if kind!='file':raise StudioError('Choose an image or downloadable file.')
    suffix=Path(name).suffix.lower()
    if suffix=='.pdf':
        if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-2048:]:raise StudioError('Choose a valid PDF.')
        mime='application/pdf'
    elif suffix=='.zip':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
                entries=bundle.infolist()
                if len(entries)>1000 or sum(e.file_size for e in entries)>100*1024*1024:raise ValueError()
                for entry in entries:
                    path=PurePosixPath(entry.filename.replace('\\','/'))
                    if path.is_absolute() or '..' in path.parts or ':' in entry.filename or '\x00' in entry.filename or (entry.external_attr>>16)&0o170000==0o120000 or entry.flag_bits&1:raise ValueError()
        except (ValueError,zipfile.BadZipFile,NotImplementedError):raise StudioError('Use an unencrypted ZIP with safe relative paths, at most 1,000 entries and 100 MiB unpacked.')
        mime='application/zip'
    elif suffix=='.txt':
        try:content=raw.decode('utf-8')
        except UnicodeError:raise StudioError('Use UTF-8 for text files.')
        if any(ord(c)<32 and c not in '\n\r\t' for c in content):raise StudioError('Text files cannot contain binary control characters.')
        mime='text/plain'
    else:raise StudioError('Use PDF, ZIP or UTF-8 TXT for draft downloads. Bundle other product formats in a ZIP.')
    return raw,name,suffix,mime


def save(db,app,uid,page_id,listing_id,revision,kind,raw,name,prepared=None):
    page,shop,listing=get_listing(db,uid,page_id,listing_id)
    if page['state']=='archived' or listing['state']!='draft':raise StudioError('Restore this Page and listing before uploading.',409)
    if listing['revision']!=revision:raise StudioError('This listing changed. Reload before uploading.',409)
    if kind=='file' and listing['kind']!='digital':raise StudioError('Product downloads belong to digital listing drafts.')
    limit=5 if kind=='image' else 1
    if db.execute("SELECT COUNT(*) FROM seller_assets WHERE listing_id=? AND kind=? AND state='active'",(listing_id,kind)).fetchone()[0]>=limit:raise StudioError('Remove an active file from this draft before adding another.',409)
    data,display,suffix,mime=prepare(raw,name,kind) if prepared is None else prepared
    key=secrets.token_hex(24)+suffix;asset_id=secrets.token_urlsafe(18);directory=folder(app);directory.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(directory,0o700)
    # Caller owns an IMMEDIATE transaction and rechecks listing revision/access.
    # Durable ledger admission happens before any payload is written. If the app
    # commit later fails, retained bytes stay attributed/charged for review.
    from .storage_uploads import write
    write([(directory/key,data)],'marketplace')
    db.execute('INSERT INTO seller_assets(id,shop_id,listing_id,uploader_id,kind,storage_key,display_name,mime,bytes,sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(asset_id,page_id,listing_id,uid,kind,key,display,mime,len(data),hashlib.sha256(data).hexdigest(),int(time.time())))
    db.execute('UPDATE seller_listings SET revision=revision+1,updated_by=?,updated_at=? WHERE id=?',(uid,int(time.time()),listing_id));event(db,page_id,uid,'upload:'+kind,listing_id)
    return asset_id


def archive(db,uid,page_id,listing_id,asset_id,revision):
    page,shop,listing=get_listing(db,uid,page_id,listing_id)
    if page['state']=='archived' or listing['state']!='draft' or listing['revision']!=revision:raise StudioError('Reload an editable draft before removing a file.',409)
    r=db.execute("UPDATE seller_assets SET state='archived' WHERE id=? AND listing_id=? AND shop_id=? AND state='active'",(asset_id,listing_id,page_id))
    if r.rowcount!=1:raise StudioError('File unavailable.',404)
    db.execute('UPDATE seller_listings SET revision=revision+1,updated_by=?,updated_at=? WHERE id=?',(uid,int(time.time()),listing_id));event(db,page_id,uid,'archive-asset',listing_id)


def visible_assets(db,listing_id):
    return db.execute("SELECT id,kind,display_name,bytes,uploader_id FROM seller_assets WHERE listing_id=? AND state='active' ORDER BY created_at,id",(listing_id,)).fetchall()


def export_user(db,uid):
    return [dict(row) for row in db.execute('SELECT id,listing_id,kind,display_name,mime,bytes,sha256,state,created_at FROM seller_assets WHERE uploader_id=? ORDER BY created_at,id',(uid,))]


def register(app,core):
    from flask import Blueprint,abort,flash,redirect,request,session,url_for,send_file
    from . import seller_studio as studio
    from .media_export import open_regular
    bp=Blueprint('marketplace_assets',__name__)
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    @bp.errorhandler(StudioError)
    def error(exc):
        from flask import render_template
        return render_template('seller_studio.html',error=str(exc),view='error',unsaved=[]),exc.status
    def actor():
        uid=session.get('user_id')
        if type(uid) is not int:abort(401)
        return uid
    def writing():
        helpers=app.extensions['community_auth_helpers'];helpers['csrf']()
        if not helpers['fresh']():return redirect(url_for('community_reauth',next=request.path))
        return helpers['limited']('seller-upload',20)
    def revision():
        n=request.form.get('revision',type=int)
        if n is None or not 0<=n<2**63:raise StudioError('Reload before changing files.',409)
        return n
    @bp.post('/marketplace/studio/<page_id>/listing/<listing_id>/assets')
    def upload(page_id,listing_id):
        uid=actor();db=core.get_db();get_listing(db,uid,page_id,listing_id)
        response=writing()
        if response is not None:return response
        incoming=request.files.get('product_file')
        if not incoming:raise StudioError('Choose a product image or file.')
        raw=incoming.stream.read(MAX_UPLOAD+1)
        kind=request.form.get('kind');prepared=prepare(raw,incoming.filename,kind)
        with db:
            db.execute('BEGIN IMMEDIATE');save(db,app,uid,page_id,listing_id,revision(),kind,raw,incoming.filename,prepared)
        flash('Private draft file added. It counts toward your upload allowance.','success')
        return redirect(url_for('seller_studio.listing',page_id=page_id,listing_id=listing_id))
    @bp.post('/marketplace/studio/<page_id>/listing/<listing_id>/assets/<asset_id>/archive')
    def remove(page_id,listing_id,asset_id):
        uid=actor();db=core.get_db();get_listing(db,uid,page_id,listing_id)
        response=writing()
        if response is not None:return response
        with db:
            db.execute('BEGIN IMMEDIATE');archive(db,uid,page_id,listing_id,asset_id,revision())
        flash('File removed from this draft. Its retained upload still counts toward storage.','success')
        return redirect(url_for('seller_studio.listing',page_id=page_id,listing_id=listing_id))
    @bp.get('/marketplace/studio/<page_id>/listing/<listing_id>/assets/<asset_id>')
    def download(page_id,listing_id,asset_id):
        uid=actor();db=core.get_db();get_listing(db,uid,page_id,listing_id)
        row=db.execute("SELECT * FROM seller_assets WHERE id=? AND listing_id=? AND shop_id=? AND state='active'",(asset_id,listing_id,page_id)).fetchone()
        if not row or not studio.adult_account(db,row['uploader_id']):abort(404)
        try:
            with open_regular(folder(app),row['storage_key']) as file:data=file.read(MAX_UPLOAD+1)
        except OSError:abort(404)
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:abort(404)
        image=row['kind']=='image';response=send_file(io.BytesIO(data),mimetype='image/webp' if image else 'application/octet-stream',as_attachment=not image,download_name='product-'+row['id']+Path(row['storage_key']).suffix,conditional=False,etag=False,max_age=0)
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Content-Security-Policy']="sandbox; default-src 'none'";return response
    @bp.after_request
    def private(response):
        response.headers.update({'Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})
        return response
    app.register_blueprint(bp)
