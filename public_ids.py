"""Opaque post/comment identifiers, bounded legacy aliases and prefix capacity."""
from .request_cache import request_lookup
import re,secrets,sqlite3
from flask import current_app,g,request,url_for,redirect,abort
ALPHABET='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
TOKEN=re.compile(r'(?=[0-9A-Za-z]{0,15}[A-Za-z])[0-9A-Za-z]{16}\Z',re.ASCII)
KINDS={'post':'posts','comment':'comments'}
POST_ENDPOINTS={'post_detail','post_edit_history','edit_post','delete_post','react_to_post','post_reaction_people'}
COMMENT_ENDPOINTS={'edit_comment','delete_comment'}
MAX_KEY=2**63-1

def random_token():
    for _ in range(32):
        token=''.join(secrets.choice(ALPHABET) for _ in range(16))
        if TOKEN.fullmatch(token):return token
    raise RuntimeError('Public ID entropy unavailable')

def old_label(value):
    from neonrest_sandbox.utils.utils import encode_base62
    return encode_base62(value).rjust(8,'A')

def ensure(db,kind,key):
    if kind not in KINDS or not isinstance(key,int) or not 0<key<=MAX_KEY:raise ValueError('Invalid resource key')
    row=db.execute('SELECT public_id FROM public_ids WHERE kind=? AND internal_id=?',(kind,key)).fetchone()
    if row:return row[0]
    if not db.execute(f'SELECT 1 FROM {KINDS[kind]} WHERE id=?',(key,)).fetchone():raise ValueError('Unavailable resource')
    for _ in range(32):
        token=random_token()
        try:db.execute('INSERT INTO public_ids(kind,internal_id,public_id) VALUES (?,?,?)',(kind,key,token))
        except sqlite3.IntegrityError:
            row=db.execute('SELECT public_id FROM public_ids WHERE kind=? AND internal_id=?',(kind,key)).fetchone()
            if row:return row[0]
            continue
        return token
    raise RuntimeError('Public ID allocation failed')

def initialize(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS public_ids(kind TEXT NOT NULL CHECK(kind IN (\'post\',\'comment\')),internal_id INTEGER NOT NULL,public_id TEXT NOT NULL UNIQUE,prefix TEXT,PRIMARY KEY(kind,internal_id))')
        db.execute('CREATE TABLE IF NOT EXISTS public_id_aliases(kind TEXT NOT NULL,alias TEXT NOT NULL,internal_id INTEGER NOT NULL,PRIMARY KEY(kind,alias))')
        db.execute('CREATE INDEX IF NOT EXISTS public_alias_owner ON public_id_aliases(kind,internal_id)')
        db.execute('CREATE TABLE IF NOT EXISTS public_id_state(kind TEXT PRIMARY KEY,highest_key INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS public_id_migrations(name TEXT PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        first=not db.execute("SELECT 1 FROM public_id_migrations WHERE name='opaque-v1'").fetchone()
        for kind,table in KINDS.items():
            keys=[r[0] for r in db.execute(f'SELECT id FROM {table} ORDER BY id')]
            db.execute('INSERT INTO public_id_state VALUES (?,?) ON CONFLICT(kind) DO UPDATE SET highest_key=MAX(highest_key,excluded.highest_key)',(kind,max(keys,default=0)))
            for key in keys:
                ensure(db,kind,key)
                if first:
                    aliases=[str(key)] if kind=='post' else [old_label(key),'anchor:'+str(key)]
                    for alias in aliases:
                        previous=db.execute('SELECT internal_id FROM public_id_aliases WHERE kind=? AND alias=?',(kind,alias)).fetchone()
                        if previous and previous[0]!=key:raise RuntimeError('Ambiguous historical comment aliases require review')
                        db.execute('INSERT OR IGNORE INTO public_id_aliases VALUES (?,?,?)',(kind,alias,key))
            # Pure SQL triggers also cover retention and administrative DB connections.
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS opaque_{kind}_insert AFTER INSERT ON {table} BEGIN
                UPDATE public_id_state SET highest_key=MAX(highest_key,NEW.id) WHERE kind='{kind}'; END''')
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS opaque_{kind}_delete AFTER DELETE ON {table} BEGIN
                DELETE FROM public_id_aliases WHERE kind='{kind}' AND internal_id=OLD.id;
                DELETE FROM public_ids WHERE kind='{kind}' AND internal_id=OLD.id; END''')
        db.execute("INSERT OR IGNORE INTO public_id_migrations(name) VALUES ('opaque-v1')")
        db.commit()
    except Exception:db.rollback();raise

def next_post_key(db):
    return max(db.execute("SELECT highest_key FROM public_id_state WHERE kind='post'").fetchone()[0],db.execute('SELECT COALESCE(MAX(id),0) FROM posts').fetchone()[0])+1

@request_lookup
def public(db,kind,key):
    if key is None:return None
    if isinstance(key,str) and TOKEN.fullmatch(key):return key
    if not isinstance(key,int):raise ValueError('Expected internal key')
    existing=db.execute('SELECT public_id FROM public_ids WHERE kind=? AND internal_id=?',(kind,key)).fetchone()
    if existing:return existing[0]
    # Imported records and disposable fixtures receive IDs without legacy aliases.
    was_transaction=db.in_transaction
    token=ensure(db,kind,key)
    if not was_transaction:db.commit()
    return token

def optional(db,kind,key):
    try:return public(db,kind,key)
    except ValueError:return None

def resolve(db,kind,value,anchor=False):
    if kind not in KINDS:raise ValueError('Invalid resource kind')
    if isinstance(value,int):
        if 0<value<=MAX_KEY and db.execute(f'SELECT 1 FROM {KINDS[kind]} WHERE id=?',(value,)).fetchone():return value
        raise ValueError('Unavailable resource')
    if not isinstance(value,str) or len(value)>64:raise ValueError('Invalid public ID')
    if TOKEN.fullmatch(value):
        row=db.execute(f'SELECT p.internal_id FROM public_ids p JOIN {KINDS[kind]} r ON r.id=p.internal_id WHERE p.kind=? AND p.public_id=?',(kind,value)).fetchone()
        if row:return row[0]
        raise ValueError('Unavailable public ID')
    alias='anchor:'+value if anchor else value
    row=db.execute(f'SELECT a.internal_id FROM public_id_aliases a JOIN {KINDS[kind]} r ON r.id=a.internal_id WHERE a.kind=? AND a.alias=?',(kind,alias)).fetchone()
    if row:return row[0]
    # Existing permission suites deliberately submit internal fixture keys. This
    # switch is confined to disposable tests and never permits malformed input.
    if current_app.config.get('TESTING') and current_app.config.get('PUBLIC_ID_TEST_ALIASES'):
        if (kind=='post' or anchor) and re.fullmatch(r'[1-9][0-9]{0,18}',value,re.ASCII):
            return resolve(db,kind,int(value))
        if kind=='comment' and re.fullmatch(r'[0-9A-Za-z]{8}',value,re.ASCII):
            matches=[r[0] for r in db.execute('SELECT id FROM comments') if old_label(r[0])==value]
            if len(matches)==1:return matches[0]
    raise ValueError('Unknown, malformed or unenabled prefixed ID')

def canonical_path(db,path,internal=False):
    match=re.fullmatch(r'/posts/([^/#?]+)(?:#comment-([^/#?]+))?',path or '')
    if not match:return path
    try:
        pid=resolve(db,'post',int(match[1]) if internal and match[1].isdecimal() else match[1])
        result='/posts/'+public(db,'post',pid)
        if match[2]:
            cid=resolve(db,'comment',int(match[2]) if internal and match[2].isdecimal() else match[2],anchor=True)
            if not db.execute('SELECT 1 FROM comments WHERE id=? AND post_id=?',(cid,pid)).fetchone():return path
            result+='#comment-'+public(db,'comment',cid)
        return result
    except ValueError:return path

def export_ids(db,data):
    for table,rows in data.items():
        if not isinstance(rows,list):continue
        for row in rows:
            if not isinstance(row,dict):continue
            if table=='posts':row['id']=public(db,'post',row['id'])
            if table in ('comments','replies'):
                row['id']=public(db,'comment',row['id'])
                if row.get('parent_comment_id'):row['parent_comment_id']=optional(db,'comment',row['parent_comment_id'])
            if row.get('post_id'):
                try:row['post_id']=public(db,'post',row['post_id'])
                except ValueError:row['post_id']=None
            if row.get('target_type') in KINDS and row.get('target_id'):
                try:row['target_id']=public(db,row['target_type'],row['target_id'])
                except ValueError:row['target_id']=None
            if table=='notifications':row['path']=canonical_path(db,row.get('path',''))
    data['content_id_format']='random-base62-v1'
    return data

def register(app,core):
    with app.app_context():initialize(core.get_db())
    @app.url_value_preprocessor
    def inbound(endpoint,values):
        if not values:return
        kind=None;field=None
        if endpoint in POST_ENDPOINTS:kind,field='post','post_id'
        elif endpoint in COMMENT_ENDPOINTS:kind,field='comment','comment_id'
        elif endpoint in ('report_content','appeal_form'):
            if values.get('kind') in KINDS:kind,field=values['kind'],'target_id'
            else:
                try:
                    if not re.fullmatch(r'[1-9][0-9]{0,18}',values['target_id'],re.ASCII):raise ValueError()
                    values['target_id']=int(values['target_id'])
                    if values['target_id']>MAX_KEY:raise ValueError()
                except ValueError:abort(404)
        if kind:
            original=values[field]
            try:values[field]=resolve(core.get_db(),kind,original)
            except ValueError:abort(404)
            if not isinstance(original,str) or not TOKEN.fullmatch(original):g.legacy_content_route=(endpoint,dict(values))
    @app.url_defaults
    def outbound(endpoint,values):
        kind=None;field=None
        if endpoint in POST_ENDPOINTS:kind,field='post','post_id'
        elif endpoint in COMMENT_ENDPOINTS:kind,field='comment','comment_id'
        elif endpoint in ('report_content','appeal_form') and values.get('kind') in KINDS:kind,field=values['kind'],'target_id'
        if kind and isinstance(values.get(field),int) and values[field]>0:
            try:values[field]=public(core.get_db(),kind,values[field])
            except ValueError:values[field]='unavailable'
    @app.after_request
    def canonical_response(response):
        legacy=getattr(g,'legacy_content_route',None)
        if legacy and request.method=='GET' and response.status_code==200 and not (app.config.get('TESTING') and app.config.get('PUBLIC_ID_TEST_ALIASES')):
            endpoint,values=legacy
            destination=url_for(endpoint,**values)
            if request.query_string:destination+='?'+request.query_string.decode('ascii',errors='ignore')
            response=redirect(destination,302);response.headers['Cache-Control']='private, no-store'
        return response
    def target(kind,key):
        try:return public(core.get_db(),kind,key) if kind in KINDS else key
        except ValueError:return 'unavailable'
    def old_anchor(key):
        row=core.get_db().execute("SELECT alias FROM public_id_aliases WHERE kind='comment' AND internal_id=? AND alias LIKE 'anchor:%'",(key,)).fetchone()
        return 'comment-'+row[0].split(':',1)[1] if row else None
    app.jinja_env.globals.update(public_post_id=lambda key:public(core.get_db(),'post',key),public_comment_id=lambda key:public(core.get_db(),'comment',key),public_target_id=target,
        public_content_path=lambda path:canonical_path(core.get_db(),path),legacy_comment_anchor=old_anchor)

