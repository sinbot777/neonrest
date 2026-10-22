"""Direct-sponsor inventory; contextual placement without third-party scripts."""
import re
from pathlib import Path
from urllib.parse import urlsplit


def destination(value):
    if not isinstance(value,str) or not value or len(value)>500 or any(c.isspace() or ord(c)<32 or ord(c)==127 or c=='\\' for c in value):
        return False
    try:
        p=urlsplit(value)
        return bool(p.scheme in ('http','https') and p.hostname and p.netloc and not p.username and not p.password and p.port!=0)
    except ValueError:
        return False


def image(value,static_folder):
    if not value:return True
    if not isinstance(value,str) or len(value)>300 or '..' in value or not re.fullmatch(r'/static/ads/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp|gif)',value,re.I):return False
    base=Path(static_folder).resolve();path=(base/value[len('/static/'):]).resolve()
    return path.is_relative_to(base) and path.is_file()


def selection(db,static_folder,vibe_id=None):
    selected=[]
    # Independent placement queries prevent a busy card inventory starving banners.
    for placement,limit in [('rail',4),('banner',1)]:
        rows=db.execute("""SELECT * FROM ad_campaigns WHERE active=1 AND placement=?
            AND (starts_at IS NULL OR datetime(starts_at)<=CURRENT_TIMESTAMP)
            AND (ends_at IS NULL OR datetime(ends_at)>CURRENT_TIMESTAMP)
            AND (vibe_id IS NULL OR vibe_id=?) ORDER BY RANDOM() LIMIT ?""",(placement,vibe_id,limit)).fetchall()
        selected.extend(dict(row) for row in rows if destination(row['destination_url']) and image(row['image_path'],static_folder))
    for ad in selected:db.execute("INSERT INTO ad_events(campaign_id,event_type) VALUES (?,'impression')",(ad['id'],))
    if selected:db.commit()
    return [a for a in selected if a['placement']=='rail'],next((a for a in selected if a['placement']=='banner'),None)


def key(raw):
    if not raw or not raw.isascii() or not raw.isdecimal() or len(raw)>19:return None
    value=int(raw)
    return value if 0<value<2**63 else None
