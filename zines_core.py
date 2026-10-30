"""T34 structured collaborative publications; no arbitrary HTML or remote rendering."""
import json
import math
import random
import secrets
import time
from . import identity_pages, age_policy
from .request_cache import request_lookup

MAX_PAGES=64
MAX_TEXT=6000
class ZineError(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message); self.status=status

def initialize(db):
    statements=[
    """CREATE TABLE IF NOT EXISTS zines(id TEXT PRIMARY KEY,owner_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','unlisted','public')),allow_print INTEGER NOT NULL DEFAULT 0,cover_asset TEXT,revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS zine_members(zine_id TEXT NOT NULL REFERENCES zines(id),user_id INTEGER NOT NULL REFERENCES users(id),role TEXT NOT NULL CHECK(role IN ('editor','contributor')),PRIMARY KEY(zine_id,user_id))""",
    """CREATE TABLE IF NOT EXISTS zine_issues(id TEXT PRIMARY KEY,zine_id TEXT NOT NULL REFERENCES zines(id),title TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','published')),allow_print INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,published_at INTEGER,created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS zine_pages(id TEXT PRIMARY KEY,issue_id TEXT NOT NULL REFERENCES zine_issues(id),author_id INTEGER NOT NULL REFERENCES users(id),position INTEGER NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('cover','page','back')),content TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS zine_submissions(id TEXT PRIMARY KEY,issue_id TEXT NOT NULL REFERENCES zine_issues(id),author_id INTEGER NOT NULL REFERENCES users(id),content TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','submitted','accepted','returned')),revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS zine_revisions(id INTEGER PRIMARY KEY,issue_id TEXT NOT NULL REFERENCES zine_issues(id),actor_id INTEGER NOT NULL REFERENCES users(id),revision INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS zine_assets(id TEXT PRIMARY KEY,zine_id TEXT NOT NULL REFERENCES zines(id),uploader_id INTEGER NOT NULL REFERENCES users(id),storage_key TEXT NOT NULL UNIQUE,bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,created_at INTEGER NOT NULL)""",
    'CREATE INDEX IF NOT EXISTS zine_issues_publication ON zine_issues(zine_id,state)',
    'CREATE INDEX IF NOT EXISTS zine_pages_issue ON zine_pages(issue_id,position)',
    'CREATE INDEX IF NOT EXISTS zine_submissions_issue ON zine_submissions(issue_id,author_id)',
    'CREATE INDEX IF NOT EXISTS zine_members_user ON zine_members(user_id,zine_id)']
    for statement in statements:db.execute(statement)

@request_lookup
def eligible(db,uid):
    return identity_pages.eligible(db,uid,'creative')

@request_lookup
def compatible(db,owner,viewer,contact=False):
    if not eligible(db,owner):return False
    if viewer==owner:return True
    if viewer:
        if not eligible(db,viewer):return False
        if db.execute('SELECT 1 FROM user_blocks WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',(owner,viewer,viewer,owner)).fetchone():return False
        if db.execute('SELECT 1 FROM user_mutes WHERE user_id=? AND target_id=?',(viewer,owner)).fetchone():return False
    return age_policy.contact(db,owner,viewer) if contact else age_policy.can_read(db,owner,viewer)

def publication(db,zid):
    row=db.execute('SELECT * FROM zines WHERE id=?',(zid,)).fetchone()
    if row is None:raise ZineError('Publication unavailable.',404)
    return row

def role(db,zine,uid):
    if not uid or not compatible(db,zine['owner_id'],uid,contact=True):return None
    if uid==zine['owner_id']:return 'owner'
    row=db.execute('SELECT role FROM zine_members WHERE zine_id=? AND user_id=?',(zine['id'],uid)).fetchone()
    return row['role'] if row else None

def require(db,zine,uid,roles=('owner','editor')):
    value=role(db,zine,uid)
    if value not in roles:raise ZineError('Publication unavailable.',404)
    return value

def get_issue(db,zine,iid):
    row=db.execute('SELECT * FROM zine_issues WHERE id=? AND zine_id=?',(iid,zine['id'])).fetchone()
    if row is None:raise ZineError('Issue unavailable.',404)
    return row

def pages(db,iid):
    return db.execute("SELECT * FROM zine_pages WHERE issue_id=? ORDER BY CASE kind WHEN 'cover' THEN 0 WHEN 'back' THEN 2 ELSE 1 END,position,id",(iid,)).fetchall()

def visible(db,zine,issue,uid):
    editorial=role(db,zine,uid) in ('owner','editor')
    if not editorial and (issue['state']!='published' or (zine['visibility']=='private' and not role(db,zine,uid))):return False
    if not compatible(db,zine['owner_id'],uid):return False
    for row in pages(db,issue['id']):
        if not compatible(db,row['author_id'],uid):return False
        data=json.loads(row['content'])
        from .zines_composition import asset_ids
        for image_id in asset_ids(data):
            asset=db.execute('SELECT * FROM zine_assets WHERE id=? AND zine_id=?',(image_id,zine['id'])).fetchone()
            if not asset or not compatible(db,asset['uploader_id'],uid):return False
    return True

def text(value,maximum,required=False):
    if isinstance(value,str):value=value.replace("\r\n","\n").replace("\r","\n")
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\r\t' for c in value):raise ZineError('Text is too long or contains unsupported control characters.')
    value=value.strip()
    if required and not value:raise ZineError('A title is required.')
    return value

def content(db,zid,uid,data):
    if not isinstance(data,dict) or set(data)-{'version','heading','text','caption','image','layout','print_alternative','design','section','pullquote','highlight','highlight_label','accent','text_size','image_width','image_align','composition'}:raise ZineError('Unsupported page structure.')
    out={'version':1,'heading':text(data.get('heading',''),160),'text':text(data.get('text',''),MAX_TEXT),'caption':text(data.get('caption',''),300),'layout':data.get('layout','text'),'image':data.get('image',''),'print_alternative':text(data.get('print_alternative',''),1000)}
    out.update(design=data.get('design','classic'),section=text(data.get('section',''),80),pullquote=text(data.get('pullquote',''),160),highlight=text(data.get('highlight',''),40),highlight_label=text(data.get('highlight_label',''),100))
    for key,default,allowed in [('accent','red',('red','cobalt','purple','forest')),('text_size','regular',('small','regular','large')),('image_width','full',('full','medium','small')),('image_align','center',('left','center','right'))]:
        out[key]=data.get(key,default)
        if out[key] not in allowed:raise ZineError('Choose a supported '+key.replace('_',' ')+'.')
    if out['design'] not in ('classic','punk','composition'):raise ZineError('Choose a supported visual style.')
    if out['layout'] not in ('text','image-top','image-bottom'):raise ZineError('Choose a supported layout.')
    if not isinstance(out['image'],str) or len(out['image'])>60:raise ZineError('Invalid image.')
    from .zines_composition import normalize,asset_ids
    if out['design']=='composition' or data.get('composition'):
        out['composition']=normalize(data.get('composition',{}))
    for image_id in asset_ids(out):
        asset=db.execute('SELECT * FROM zine_assets WHERE id=? AND zine_id=?',(image_id,zid)).fetchone()
        z=publication(db,zid)
        if not asset or (role(db,z,uid) not in ('owner','editor') and asset['uploader_id']!=uid) or not compatible(db,asset['uploader_id'],uid):raise ZineError('Image unavailable.',404)
    return json.dumps(out,ensure_ascii=False)

def check_revision(row,value):
    if type(value) is not int or not 0<=value<2**63 or value!=row['revision']:raise ZineError('Someone changed this draft. Copy your unsaved entries, reload, and try again.',409)

def snapshot(db,issue,uid):
    payload={'issue':dict(issue),'pages':[dict(x) for x in pages(db,issue['id'])]}
    db.execute('INSERT INTO zine_revisions(issue_id,actor_id,revision,snapshot,created_at) VALUES (?,?,?,?,?)',(issue['id'],uid,issue['revision'],json.dumps(payload,ensure_ascii=False),int(time.time())))
    db.execute('DELETE FROM zine_revisions WHERE issue_id=? AND id NOT IN (SELECT id FROM zine_revisions WHERE issue_id=? ORDER BY id DESC LIMIT 20)',(issue['id'],issue['id']))

def touch_issue(db,issue,uid):
    snapshot(db,issue,uid)
    db.execute('UPDATE zine_issues SET revision=revision+1 WHERE id=?',(issue['id'],))

def draft(issue):
    if issue['state']!='draft':raise ZineError('Return this issue to draft before editing. Its public reader and downloads will then be unavailable.',409)

def create(db,uid,title,description):
    if not eligible(db,uid):raise ZineError('An eligible verified Neonrest profile is required.',403)
    if db.execute('SELECT COUNT(*) FROM zines WHERE owner_id=?',(uid,)).fetchone()[0]>=20:raise ZineError('Publication limit reached.',409)
    zid=secrets.token_urlsafe(12)
    db.execute('INSERT INTO zines(id,owner_id,title,description,created_at) VALUES (?,?,?,?,?)',(zid,uid,text(title,160,True),text(description,2000),int(time.time())))
    return zid

def create_issue(db,zine,uid,title):
    require(db,zine,uid)
    if db.execute('SELECT COUNT(*) FROM zine_issues WHERE zine_id=?',(zine['id'],)).fetchone()[0]>=100:raise ZineError('Issue limit reached.',409)
    iid=secrets.token_urlsafe(12)
    db.execute('INSERT INTO zine_issues(id,zine_id,title,created_at) VALUES (?,?,?,?)',(iid,zine['id'],text(title,160,True),int(time.time())))
    for position,kind,heading in [(0,'cover',title),(1,'back','Back cover')]:
        db.execute('INSERT INTO zine_pages VALUES (?,?,?,?,?,?)',(secrets.token_urlsafe(12),iid,uid,position,kind,content(db,zine['id'],uid,{'heading':heading})))
    return iid

def add_page(db,zine,issue,uid,data,kind='page',author=None):
    require(db,zine,uid);draft(issue)
    existing=pages(db,issue['id'])
    if len(existing)>=MAX_PAGES:raise ZineError('An issue supports at most 64 pages.',409)
    if kind!='page':raise ZineError('Edit the existing covers instead.')
    db.execute('INSERT INTO zine_pages VALUES (?,?,?,?,?,?)',(secrets.token_urlsafe(12),issue['id'],author or uid,len(existing),'page',content(db,zine['id'],uid,data)))

def padded(reading):
    result=list(reading)
    if len(result)<2 or len(result)>MAX_PAGES:raise ZineError('Print editions require 2–64 pages.')
    blanks=(-len(result))%4
    return result[:-1]+[None]*blanks+result[-1:]

def impose(reading):
    seq=padded(reading); n=len(seq)
    return [(seq[n-1-2*k],seq[2*k],seq[2*k+1],seq[n-2-2*k]) for k in range(n//4)]


def export_user(db,uid):
    return {
      'publications':[dict(r) for r in db.execute('SELECT * FROM zines WHERE owner_id=?',(uid,))],
      'memberships':[dict(r) for r in db.execute('SELECT * FROM zine_members WHERE user_id=?',(uid,))],
      'authored_pages':[dict(r) for r in db.execute('SELECT * FROM zine_pages WHERE author_id=?',(uid,))],
      'submissions':[dict(r) for r in db.execute('SELECT * FROM zine_submissions WHERE author_id=?',(uid,))],
      'uploaded_artwork':[dict(r) for r in db.execute('SELECT id,zine_id,bytes,sha256,created_at FROM zine_assets WHERE uploader_id=?',(uid,))]}

def wave():
    rng=random.Random(12)
    return [round((14+55*abs(math.sin(x*.032)))*rng.uniform(.55,1),2) for x in range(22,375,5)]
