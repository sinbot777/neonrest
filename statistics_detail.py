"""Hourly aggregate analytics without visitor identities or raw request data."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from pathlib import Path
import csv
import io
import sqlite3
from flask import abort, request, session, url_for
from .site_statistics import LABELS, OUTCOMES, RETENTION_DAYS
from . import circles, circle_ids

MAX_ROWS=50000
SEGMENTS={'guest':'Signed out','member':'Members','staff':'Staff'}
SOURCES={'direct':'Direct / unknown','internal':'Within Neonrest','search':'Other recognized search engines','social':'Other recognized social sites','google':'Google','bing':'Bing','duckduckgo':'DuckDuckGo','facebook':'Facebook','instagram':'Instagram','reddit':'Reddit','bluesky':'Bluesky','youtube':'YouTube','discord':'Discord','twitter':'X / Twitter','tumblr':'Tumblr','pinterest':'Pinterest','external':'Other external sites'}
DEVICES={'desktop':'Desktop','mobile':'Mobile','tablet':'Tablet','unknown':'Unknown device'}
BROWSERS={'chrome':'Chrome / Chromium','edge':'Edge','firefox':'Firefox','safari':'Safari','other':'Other browser','unknown':'Unknown browser'}
KINDS={'page','signup','flow','source','device','browser','destination'}


def initialize(path):
    with sqlite3.connect(path,timeout=1) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS hourly_counters(bucket TEXT NOT NULL,segment TEXT NOT NULL,
            kind TEXT NOT NULL,label TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',value INTEGER NOT NULL,
            PRIMARY KEY(bucket,segment,kind,label,detail))''')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('detail_started_at',?)",(datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('detail_capacity_skips','0')")


def traffic_segment(core):
    uid=session.get('user_id')
    if not isinstance(uid,int):
        return 'guest'
    return 'staff' if uid==1 or core.staff_permissions(core.get_db(),uid) else 'member'


def source_category():
    try:
        ref=urlsplit(request.referrer or '')
        if ref.scheme not in ('http','https') or not ref.hostname:
            return 'direct'
        host=ref.hostname.lower().rstrip('.')
        if host==urlsplit(request.host_url).hostname:
            return 'internal'
        def domain(name):
            return host==name or host.endswith('.'+name)
        for key,names in [('google',('google.com',)),('bing',('bing.com',)),('duckduckgo',('duckduckgo.com',)),('facebook',('facebook.com',)),('instagram',('instagram.com',)),('reddit',('reddit.com',)),('bluesky',('bsky.app',)),('youtube',('youtube.com',)),('discord',('discord.com',)),('twitter',('t.co','twitter.com','x.com')),('tumblr',('tumblr.com',)),('pinterest',('pinterest.com',))]:
            if any(domain(name) for name in names):
                return key
        if any(domain(x) for x in ('google.com','bing.com','duckduckgo.com','search.yahoo.com','search.brave.com','ecosia.org')):
            return 'search'
        if any(domain(x) for x in ('facebook.com','instagram.com','reddit.com','bsky.app','t.co','twitter.com','x.com','tumblr.com','pinterest.com','youtube.com','discord.com')):
            return 'social'
        return 'external'
    except ValueError:
        return 'direct'


def device_browser():
    ua=request.headers.get('User-Agent','')[:512].lower()
    device='tablet' if 'ipad' in ua or 'tablet' in ua or ('android' in ua and 'mobile' not in ua) else 'mobile' if any(x in ua for x in ('mobile','iphone','ipod')) else 'desktop' if any(x in ua for x in ('windows','macintosh','x11','linux')) else 'unknown'
    browser='edge' if any(x in ua for x in ('edg/','edga/','edgios/')) else 'firefox' if 'firefox/' in ua or 'fxios/' in ua else 'chrome' if 'chrome/' in ua or 'crios/' in ua else 'safari' if 'safari/' in ua and 'version/' in ua else 'other' if ua else 'unknown'
    return device,browser


def public_destination(core):
    db=core.get_db();args=request.view_args or {}
    if 'vibe_name' in args:
        row=db.execute('''SELECT id FROM vibes WHERE name=? COLLATE NOCASE
            AND id NOT IN (SELECT vibe_id FROM pending_vibes)
            AND id NOT IN (SELECT vibe_id FROM vibe_management WHERE archived=1)''',(args['vibe_name'],)).fetchone()
        return 'v:'+str(row['id']) if row else None
    cid=args.get('circle_id')
    if request.endpoint=='circle_page' and isinstance(cid,int):
        row=db.execute('SELECT * FROM circles WHERE id=?',(cid,)).fetchone()
        if circles.public_info_allowed(db,row,None):
            return 'c:'+str(cid)
    return None


def write(path,counts,segment,when=None):
    """Finite independent dimensions; capacity limit prevents unbounded disk growth."""
    now=when or datetime.now(timezone.utc);bucket=now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H')
    cutoff=(datetime.now(timezone.utc).date()-timedelta(days=RETENTION_DAYS-1)).isoformat()
    with sqlite3.connect(path,timeout=0.05) as db:
        db.execute('DELETE FROM hourly_counters WHERE bucket<?',(cutoff,))
        db.execute('DELETE FROM counters WHERE day<?',(cutoff,))
        size=db.execute('SELECT COUNT(*) FROM hourly_counters').fetchone()[0];skipped=0
        for kind,label,detail in counts:
            if kind not in KINDS or segment not in SEGMENTS:
                continue
            changed=db.execute('''UPDATE hourly_counters SET value=min(value+1,2147483647)
                WHERE bucket=? AND segment=? AND kind=? AND label=? AND detail=?''',(bucket,segment,kind,label,detail))
            if changed.rowcount:
                continue
            if size>=MAX_ROWS:
                skipped+=1;continue
            db.execute('INSERT INTO hourly_counters VALUES (?,?,?,?,?,1)',(bucket,segment,kind,label,detail));size+=1
        if skipped:
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+? WHERE key='detail_capacity_skips'",(skipped,))


def record(core,path,counts):
    if any(kind=='page' for kind,_,_ in counts):
        device,browser=device_browser()
        counts=counts+[('source',source_category(),''),('device',device,''),('browser',browser,'')]
        destination=public_destination(core)
        if destination:
            counts.append(('destination',destination,''))
    write(path,counts,traffic_segment(core))


def options():
    today=datetime.now(timezone.utc).date();earliest=today-timedelta(days=RETENTION_DAYS-1)
    period=request.args.get('days','7');traffic=request.args.get('traffic','ordinary')
    if period not in ('1','7','30','90','custom') or traffic not in ('ordinary','all','staff','guest','member'):
        abort(400,description='Choose a supported period and traffic group.')
    try:
        if period=='custom':
            start=date.fromisoformat(request.args.get('start',''));end=date.fromisoformat(request.args.get('end',''))
        else:
            end=today;start=today-timedelta(days=int(period)-1)
    except ValueError:
        abort(400,description='Enter valid start and end dates.')
    if not earliest<=start<=end<=today:
        abort(400,description='Choose dates within the retained 90 UTC days.')
    length=(end-start).days+1;previous_end=start-timedelta(days=1);previous_start=previous_end-timedelta(days=length-1)
    return {'days':period,'traffic':traffic,'start':start.isoformat(),'end':end.isoformat(),
        'previous_start':previous_start.isoformat(),'previous_end':previous_end.isoformat(),
        'earliest':earliest.isoformat(),'today':today.isoformat(),'length':length,
        'previous_clipped':previous_start<earliest}


def allowed_segments(traffic):
    return {'ordinary':('guest','member'),'all':('guest','member','staff'),'staff':('staff',),'guest':('guest',),'member':('member',)}[traffic]


def public_labels(core,keys):
    """Resolve current public state; hidden/archived/deleted destinations lose names and links."""
    db=core.get_db();result={}
    for key in keys:
        try:
            kind,number=key.split(':');uid=int(number)
        except (ValueError,AttributeError):
            continue
        if kind=='v':
            row=db.execute('''SELECT id,name FROM vibes WHERE id=? AND id NOT IN (SELECT vibe_id FROM pending_vibes)
                AND id NOT IN (SELECT vibe_id FROM vibe_management WHERE archived=1)''',(uid,)).fetchone()
            if row:
                result[key]=('Vibe: '+row['name'],url_for('vibe_page',vibe_name=row['name']))
        elif kind=='c':
            row=db.execute('SELECT * FROM circles WHERE id=?',(uid,)).fetchone()
            if circles.public_info_allowed(db,row,None):
                result[key]=('Circle: '+circles.label(row),url_for('circle_page',circle_id=circle_ids.public(db,uid)))
    return result


def build_report(core,path,opts):
    with sqlite3.connect(path,timeout=0.2) as db:
        db.row_factory=sqlite3.Row
        # Read only the requested and previous periods, bounded by retention.
        earliest=max(opts['earliest'],opts['previous_start'])
        rows=[dict(r) for r in db.execute('SELECT * FROM hourly_counters WHERE bucket>=? AND bucket<? ORDER BY bucket,segment,kind,label,detail',(earliest,(date.fromisoformat(opts['end'])+timedelta(days=1)).isoformat()))]
        legacy=[dict(r) for r in db.execute('SELECT * FROM counters WHERE day BETWEEN ? AND ? ORDER BY day,kind,label,detail',(earliest,opts['end']))]
        meta=dict(db.execute('SELECT key,value FROM metadata'))
        storage={'bytes':Path(path).stat().st_size,'rows':db.execute('SELECT COUNT(*) FROM hourly_counters').fetchone()[0],'capacity':MAX_ROWS,'skips':int(meta.get('detail_capacity_skips','0'))}
    wanted=allowed_segments(opts['traffic']);totals=defaultdict(int);previous=defaultdict(int);daily=defaultdict(lambda:defaultdict(int));hourly=defaultdict(int);tables={k:defaultdict(int) for k in ['page','signup','flow','source','device','browser','destination','audience']};legacy_views=0
    export=[]
    def consume(day,kind,label,detail,value,segment,legacy_row=False):
        nonlocal legacy_views
        active=opts['start']<=day<=opts['end'];target=totals if active else previous
        if not active and not opts['previous_start']<=day<=opts['previous_end']:
            return
        metric='views' if kind=='page' else 'attempts' if kind=='signup' and label not in ('verified','verification_invalid') else None
        if metric:target[metric]+=value
        if kind=='signup' and label.startswith('created_'):target['created']+=value
        if kind=='signup' and label=='verified':target['verified']+=value
        if not active:return
        if metric:daily[day][metric]+=value
        if kind=='signup' and label.startswith('created_'):daily[day]['created']+=value
        if kind=='signup' and label=='verified':daily[day]['verified']+=value
        if kind in tables:tables[kind][(label,detail) if kind=='flow' else label]+=value
        if kind=='page':tables['audience'][segment]+=value
        if legacy_row and kind=='page':legacy_views+=value
    for row in rows:
        if row['segment'] not in wanted:continue
        day=row['bucket'][:10];consume(day,row['kind'],row['label'],row['detail'],row['value'],row['segment'])
        if opts['start']<=day<=opts['end']:
            export.append(row)
            if row['kind']=='page':hourly[row['bucket'][11:13]]+=row['value']
    # Old counters are known non-staff traffic, but guest/member and hour were not recorded.
    if opts['traffic'] in ('ordinary','all'):
        for row in legacy:
            consume(row['day'],row['kind'],row['label'],row['detail'],row['value'],'legacy',True)
            if opts['start']<=row['day']<=opts['end']:export.append(dict(bucket=row['day'],segment='legacy',kind=row['kind'],label=row['label'],detail=row['detail'],value=row['value']))
    resolved=public_labels(core,sorted(tables['destination'],key=tables['destination'].get,reverse=True)[:200]);destinations=[];unavailable=0
    for key,value in tables['destination'].items():
        if key in resolved:destinations.append({'label':resolved[key][0],'url':resolved[key][1],'count':value})
        else:unavailable+=value
    destinations.sort(key=lambda x:(-x['count'],x['label']))
    series=[]
    for offset in range(opts['length']):
        day=(date.fromisoformat(opts['start'])+timedelta(days=offset)).isoformat();series.append({'day':day,**{key:daily[day][key] for key in ('views','attempts','created','verified')}})
    def display(kind,key):
        return LABELS.get(key,'Other') if kind=='page' else OUTCOMES.get(key,'Other result') if kind=='signup' else SOURCES.get(key,'Other') if kind=='source' else DEVICES.get(key,'Unknown') if kind=='device' else BROWSERS.get(key,'Unknown') if kind=='browser' else SEGMENTS.get(key,'Earlier non-staff traffic')
    breakdowns={kind:sorted([{'label':display(kind,key),'count':value} for key,value in tables[kind].items()],key=lambda x:(-x['count'],x['label'])) for kind in ('page','signup','source','device','browser','audience')}
    flows=sorted([{'from':LABELS.get(pair[0],'Other'),'to':LABELS.get(pair[1],'Other'),'count':v} for pair,v in tables['flow'].items()],key=lambda x:-x['count'])[:30]
    hours=[{'hour':str(i).zfill(2)+':00','count':hourly[str(i).zfill(2)]} for i in range(24)]
    comparison=[{'label':label,'count':totals[key],'previous':previous[key],'change':round((totals[key]-previous[key])*100/previous[key],1) if previous[key] else None} for key,label in [('views','Page views'),('attempts','Signup submissions'),('created','Accounts created'),('verified','Email verifications')]]
    return {'opts':opts,'totals':totals,'previous':previous,'comparison':comparison,'series':series,'hours':hours,
        'peak':max([x['views'] for x in series]+[1]),'hour_peak':max([x['count'] for x in hours]+[1]),
        'breakdowns':breakdowns,'destinations':destinations[:200],'unavailable_destinations':unavailable,'flows':flows,
        'started':meta.get('started_at',''),'detail_started':meta.get('detail_started_at',''),'storage':storage,
        'legacy_views':legacy_views,'export':export,'resolved':resolved,
        'attempt_ratio':round(totals['created']*100/totals['attempts'],1) if totals['attempts'] else None}


def csv_report(data):
    """Export the same independent summaries as the UI, never granular cross-dimensions."""
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(['Section','UTC period / day / hour','Traffic selection','Label','Destination','Count'])
    opts=data['opts'];period=opts['start']+' through '+opts['end'];traffic=opts['traffic']
    def safe(value):
        text=str(value);return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    def row(section,label,count,when=None,destination=''):
        writer.writerow([section,when or period,traffic,safe(label),safe(destination),count])
    for item in data['comparison']:
        row('Overview',item['label'],item['count'])
        row('Previous period',item['label'],item['previous'],opts['previous_start']+' through '+opts['previous_end'])
    for item in data['series']:
        for key,title in [('views','Page views'),('attempts','Signup submissions'),('created','Accounts created'),('verified','Email verifications')]:
            row('Daily totals',title,item[key],item['day'])
    for item in data['hours']:
        row('Hour of day','Page views',item['count'],item['hour'])
    for kind,items in data['breakdowns'].items():
        for item in items:
            row(kind,item['label'],item['count'])
    for item in data['destinations']:
        row('Public community',item['label'],item['count'])
    if data['unavailable_destinations']:
        row('Public community','Other or no-longer-public destinations',data['unavailable_destinations'])
    for item in data['flows']:
        row('Navigation',item['from'],item['count'],destination=item['to'])
    if 'suite' in data:
        from .statistics_suite import csv_rows
        for section,label,value in csv_rows(data):
            row(section,label,value if value is not None else 'Unavailable')
    return stream.getvalue()
