"""Bounded aggregate discovery, feature and server performance reports."""
import csv
import hmac
import io
import math
import re
import sqlite3
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from flask import abort, g, redirect, request, session, url_for
from . import site_statistics as basic, statistics_detail as detail

LATENCY=(100,250,500,1000,2500,5000,10000)
MAX_IMPORT_ROWS=2000
MAX_SEARCH_ROWS=10000

def initialize(path):
    with sqlite3.connect(path,timeout=1) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS search_imports(
            id INTEGER PRIMARY KEY,provider TEXT,start TEXT,end TEXT,imported TEXT,rows INTEGER,
            UNIQUE(provider,start,end))''')
        db.execute('''CREATE TABLE IF NOT EXISTS search_queries(
            batch INTEGER,query TEXT,clicks INTEGER,impressions INTEGER,position REAL,
            PRIMARY KEY(batch,query))''')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('insights_started_at',?)",(datetime.now(timezone.utc).isoformat(timespec='seconds'),))

def prune_search(db):
    cutoff=(datetime.now(timezone.utc).date()-timedelta(days=89)).isoformat()
    db.execute('DELETE FROM search_queries WHERE batch IN (SELECT id FROM search_imports WHERE start<?)',(cutoff,))
    db.execute('DELETE FROM search_imports WHERE start<?',(cutoff,))

def parse_export(text):
    """Only query-level, aggregate exports; no source file is retained."""
    if len(text.encode('utf-8'))>1048576:raise ValueError('Use a query CSV no larger than 1 MiB.')
    if '\x00' in text:raise ValueError('Use a UTF-8 query CSV.')
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    fields={str(x).strip().lower():x for x in reader.fieldnames or []}
    query=next((fields[x] for x in ('top queries','query','queries','keyword','keywords') if x in fields),None)
    clicks=fields.get('clicks');impressions=fields.get('impressions')
    position=next((fields[x] for x in ('position','average position','avg. position','avg position') if x in fields),None)
    if not query or not clicks or not impressions:raise ValueError('Expected query/keyword, Clicks and Impressions columns. Export the Queries or Keywords table in English.')
    def count(value):
        value=str(value or '').strip()
        if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)',value):raise ValueError('Clicks and impressions must be nonnegative whole numbers.')
        n=int(value.replace(',',''))
        if n>2147483647:raise ValueError('A count exceeds the supported range.')
        return n
    rows=[];seen=set()
    for row in reader:
        if len(rows)>=MAX_IMPORT_ROWS:raise ValueError('Use an export with at most 2,000 query rows.')
        phrase=str(row.get(query) or '').strip()
        if not phrase or len(phrase)>300 or any(ord(c)<32 or ord(c)==127 for c in phrase):raise ValueError('Queries must be nonempty text up to 300 characters without control characters.')
        if phrase in seen:raise ValueError('Duplicate query rows; export an aggregate Queries table without additional dimensions.')
        seen.add(phrase);c=count(row.get(clicks));i=count(row.get(impressions))
        if c>i:raise ValueError('Clicks cannot exceed impressions.')
        p=None
        if position and str(row.get(position) or '').strip():
            try:p=float(str(row[position]).replace(',',''))
            except ValueError:raise ValueError('Average positions must be numbers.') from None
            if not math.isfinite(p) or not 0<=p<=100000:raise ValueError('Average position is outside the supported range.')
        rows.append((phrase,c,i,p))
    if not rows:raise ValueError('The export has no query rows.')
    return rows

def import_export(path,provider,start,end,text):
    today=datetime.now(timezone.utc).date()
    try:a=date.fromisoformat(start);b=date.fromisoformat(end)
    except ValueError:raise ValueError('Enter the exact start and end dates used in the provider report.') from None
    if provider not in ('google','bing'):raise ValueError('Choose Google or Bing.')
    if not today-timedelta(days=89)<=a<=b<=today:raise ValueError('Choose a report within the retained 90 UTC days.')
    rows=parse_export(text)
    with sqlite3.connect(path,timeout=.2) as db:
        prune_search(db)
        old=db.execute('SELECT id FROM search_imports WHERE provider=? AND start=? AND end=?',(provider,start,end)).fetchone()
        overlap=db.execute('SELECT 1 FROM search_imports WHERE provider=? AND start<=? AND end>=? AND NOT(start=? AND end=?)',(provider,end,start,start,end)).fetchone()
        if overlap:raise ValueError('This provider already has an overlapping date range. Use a nonoverlapping range, or replace the exact existing range.')
        prior=db.execute('SELECT COUNT(*) FROM search_queries WHERE batch=?',(old[0],)).fetchone()[0] if old else 0
        if db.execute('SELECT COUNT(*) FROM search_queries').fetchone()[0]-prior+len(rows)>MAX_SEARCH_ROWS:raise ValueError('Search-report storage is full. Import fewer rows or wait for older reports to expire.')
        if old:
            batch=old[0];db.execute('DELETE FROM search_queries WHERE batch=?',(batch,))
            db.execute('UPDATE search_imports SET imported=?,rows=? WHERE id=?',(datetime.now(timezone.utc).isoformat(timespec='seconds'),len(rows),batch))
        else:batch=db.execute('INSERT INTO search_imports(provider,start,end,imported,rows) VALUES (?,?,?,?,?)',(provider,start,end,datetime.now(timezone.utc).isoformat(timespec='seconds'),len(rows))).lastrowid
        db.executemany('INSERT INTO search_queries VALUES (?,?,?,?,?)',[(batch,*r) for r in rows])
    return len(rows)

def rate(a,b):return round(100*a/b,1) if b else None

def report(path,opts):
    wanted=detail.allowed_segments(opts['traffic']);marks=','.join('?' for _ in wanted)
    end=(date.fromisoformat(opts['end'])+timedelta(days=1)).isoformat()
    start_ts=int(datetime.fromisoformat(opts['start']).replace(tzinfo=timezone.utc).timestamp())
    end_ts=int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp())
    with sqlite3.connect(path,timeout=.2) as db:
        db.row_factory=sqlite3.Row
        sessions=[dict(r) for r in db.execute('SELECT * FROM browser_sessions WHERE started>=? AND started<? AND segment IN ('+marks+')',(start_ts,end_ts,*wanted))]
        counters=[dict(r) for r in db.execute("SELECT kind,label,detail,SUM(value) AS n FROM hourly_counters WHERE bucket>=? AND bucket<? AND segment IN ("+marks+") AND kind IN ('feature_result','latency') GROUP BY kind,label,detail",(opts['start'],end,*wanted))]
        imports=[dict(r) for r in db.execute('SELECT * FROM search_imports WHERE start>=? AND end<=? ORDER BY end DESC,provider',(opts['start'],opts['end']))]
        queries=[]
        for batch in imports:
            rows=[dict(r) for r in db.execute('SELECT query,clicks,impressions,position FROM search_queries WHERE batch=? ORDER BY clicks DESC,impressions DESC,query LIMIT 100',(batch['id'],))]
            for row in rows:row['ctr']=rate(row['clicks'],row['impressions'])
            batch['queries']=rows
        meta=dict(db.execute('SELECT key,value FROM metadata'))
    def funnel(key,labels):
        groups={}
        for s in sessions:groups.setdefault(s[key],[]).append(s)
        result=[]
        for label,items in groups.items():
            signup=sum(bool(s['signup']) for s in items);submitted=sum(bool(s['submitted']) for s in items);registered=sum(bool(s['registered']) for s in items)
            result.append({'label':labels.get(label,'Other'),'sessions':len(items),'signup':signup,'submitted':submitted,'registered':registered,'conversion':rate(registered,len(items))})
        return sorted(result,key=lambda x:(-x['sessions'],x['label']))
    feature={};performance={}
    for r in counters:
        if r['kind']=='feature_result':feature.setdefault(r['label'],Counter())[r['detail']]+=r['n']
        else:performance.setdefault(r['label'],Counter())[r['detail']]+=r['n']
    features=[]
    from .statistics_suite import FEATURES
    for key,counts in feature.items():
        total=sum(counts.values());ok=counts['2xx / 3xx']
        features.append({'label':FEATURES.get(key,'Other feature'),'total':total,'accepted':ok,'client':counts['4xx'],'server':counts['5xx'],'rate':rate(ok,total)})
    features.sort(key=lambda x:(-x['total'],x['label']))
    perf=[]
    for label,counts in performance.items():
        total=sum(counts.values())
        def percentile(frac):
            target=math.ceil(frac*total);running=0
            for bound in LATENCY:
                running+=counts[str(bound)]
                if running>=target:return '≤ '+str(bound)+' ms'
            return '> 10000 ms'
        perf.append({'label':label,'count':total,'p50':percentile(.5),'p95':percentile(.95),'slow':counts['5000']+counts['10000']+counts['over'],'slow_rate':rate(counts['5000']+counts['10000']+counts['over'],total)})
    perf.sort(key=lambda x:(-x['count'],x['label']))
    active=Counter();now=int(time.time());completed=[s for s in sessions if s['last_seen']<=now-1800 and s['pages']]
    for s in completed:active['1' if s['pages']==1 else '2–3' if s['pages']<=3 else '4–7' if s['pages']<=7 else '8+']+=1
    return {'sources':funnel('source',detail.SOURCES),'landings':funnel('entry',basic.LABELS),'features':features,'performance':perf,'depth':[{'label':k,'count':active[k]} for k in ('1','2–3','4–7','8+')],'imports':imports,'started':meta.get('insights_started_at',''),'sessions':len(sessions)}

def csv_rows(data):
    s=data['insights'];rows=[]
    for key in ('sources','landings'):
        for r in s[key]:
            for metric in ('sessions','signup','submitted','registered','conversion'):rows.append((key,r['label']+' · '+metric,r[metric]))
    for key,metrics in [('features',('total','accepted','client','server','rate')),('performance',('count','p50','p95','slow','slow_rate'))]:
        for r in s[key]:
            for metric in metrics:rows.append((key,r['label']+' · '+metric,r[metric]))
    for batch in s['imports']:
        for r in batch['queries']:
            for metric in ('clicks','impressions','position','ctr'):rows.append(('Search '+batch['provider']+' '+batch['start']+' to '+batch['end'],r['query']+' · '+metric,r[metric]))
    return rows

def register(app,core,path):
    try:initialize(path)
    except (OSError,sqlite3.Error):
        app.config['SITE_STATISTICS_ENABLED']=False;app.logger.warning('Optional statistics insights unavailable')
    detail.KINDS.update({'latency','feature_result'})
    @app.before_request
    def insights_start():g.statistics_started=time.perf_counter()
    @app.after_request
    def insights_measure(response):
        from .statistics_suite import signal,bot_name,route_name,FEATURES
        if not app.config.get('SITE_STATISTICS_ENABLED') or signal() or bot_name():return response
        try:
            counts=[];route=route_name()
            if route and route!='Unmatched route' and request.method in ('GET','POST'):
                elapsed=max(0,(time.perf_counter()-getattr(g,'statistics_started',time.perf_counter()))*1000)
                bound=next((str(n) for n in LATENCY if elapsed<=n),'over')
                counts.append(('latency',request.method+' '+route,bound))
            feature=request.endpoint if request.method=='POST' and request.endpoint in FEATURES else 'search' if request.endpoint=='search' and request.method=='GET' and response.status_code==200 and request.args.get('q','').strip() else None
            if feature:counts.append(('feature_result',feature,'5xx' if response.status_code>=500 else '4xx' if response.status_code>=400 else '2xx / 3xx'))
            if counts:detail.write(path,counts,detail.traffic_segment(core))
            # Pruning uses the existing measurement cadence; never stores raw files.
            with sqlite3.connect(path,timeout=.05) as db:prune_search(db)
        except Exception:app.logger.warning('Optional statistics insights write skipped')
        return response
    @app.post('/manage/statistics/search-import')
    def statistics_search_import():
        # Reuse the statistics permission/factor/freshness guard for this endpoint.
        if request.content_length is None or request.content_length>1100000:abort(413)
        known=session.get('theme_csrf_token','');supplied=request.form.get('theme_csrf_token','')
        if not known or not hmac.compare_digest(known,supplied):abort(403)
        origin=request.headers.get('Origin')
        if origin and origin!=request.host_url.rstrip('/'):abort(403)
        try:n=import_export(path,request.form.get('provider',''),request.form.get('start',''),request.form.get('end',''),request.form.get('csv',''))
        except ValueError as e:abort(400,description=str(e))
        except sqlite3.Error:abort(503,description='Search-report storage is busy. Try again shortly.')
        response=redirect(url_for('site_statistics',days='90')+'#search-discovery')
        response.headers['Cache-Control']='private, no-store'
        return response
