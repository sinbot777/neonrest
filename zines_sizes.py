"""Issue trim size, with a fixed logical composition and uniform, centered fitting."""
import math
from .zines_core import ZineError
PRESETS={'business':(252,144),'postcard':(432,288),'a6':(297.6378,419.5276),'a5':(419.5276,595.2756),'half-letter':(396,612),'letter':(612,792),'a4':(595.2756,841.8898)}
def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS zine_issue_sizes(issue_id TEXT PRIMARY KEY REFERENCES zine_issues(id),width REAL NOT NULL,height REAL NOT NULL,content_scale REAL NOT NULL DEFAULT 1)')
def get(db,iid):
    row=db.execute('SELECT width,height,content_scale FROM zine_issue_sizes WHERE issue_id=?',(iid,)).fetchone()
    return dict(row) if row else None

def parse(form):
    preset=form.get('page_preset','half-letter')
    if preset=='custom':
        factor={'in':72,'mm':72/25.4}.get(form.get('page_units'))
        if factor is None:raise ZineError('Choose inches or millimeters.')
        try:w,h=float(form.get('page_width',''))*factor,float(form.get('page_height',''))*factor
        except (ValueError,TypeError):raise ZineError('Enter valid page dimensions.')
    elif preset in PRESETS:w,h=PRESETS[preset]
    else:raise ZineError('Choose a supported page size.')
    orientation=form.get('page_orientation','portrait')
    if orientation not in ('portrait','landscape'):raise ZineError('Choose portrait or landscape.')
    w,h=sorted((w,h),reverse=orientation=='landscape')
    if not all(math.isfinite(v) for v in (w,h)) or min(w,h)<144-0.01 or max(w,h)<252-0.01 or max(w,h)>1296:
        raise ZineError('Page size must be at least 3.5 × 2 inches in either orientation and at most 18 inches per side.')
    return round(w,4),round(h,4)

def save(db,iid,form):
    w,h=parse(form);old=get(db,iid);fit=min(w/396,h/612)
    choice=form.get('resize_content','scale')
    if choice not in ('scale','keep'):raise ZineError('Choose how to fit the content.')
    if choice=='keep':
        scale=old['content_scale'] if old else 1
        if 396*scale>w+.01 or 612*scale>h+.01:raise ZineError('Content at its current size will not fit. Choose Scale content to fit or a larger page.')
    else:scale=fit
    db.execute('INSERT INTO zine_issue_sizes(issue_id,width,height,content_scale) VALUES (?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET width=excluded.width,height=excluded.height,content_scale=excluded.content_scale',(iid,w,h,scale))
    return {'width':w,'height':h,'content_scale':scale}
