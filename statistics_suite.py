"""Optional browser measurement and independent operational aggregates."""
import hashlib
import hmac
import ipaddress
import re
import secrets
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit
from itsdangerous import URLSafeTimedSerializer, BadSignature
from flask import abort, make_response, redirect, render_template, request, session, url_for
from . import site_statistics as basic, statistics_detail as detail

FEATURES={'create_post':'Post submissions','create_comment':'Reply submissions','react_to_post':'Reaction submissions','edit_post':'Post edit submissions','circle_join':'Join requests / joins','circle_leave':'Circle departures','circle_manage':'Circle management submissions','circles_home':'Circle creation submissions','login':'Sign-in submissions','signup':'Signup submissions','profile_style':'Profile style submissions','search':'Search requests'}
CAPS={'visitor_days':60000,'browser_sessions':30000,'crawler_counters':10000}

def initialize(path):
    with sqlite3.connect(path,timeout=1) as db:
        db.execute('CREATE TABLE IF NOT EXISTS visitor_days(day TEXT,segment TEXT,visitor TEXT,PRIMARY KEY(day,segment,visitor))')
        db.execute('''CREATE TABLE IF NOT EXISTS browser_sessions(key TEXT PRIMARY KEY,visitor TEXT,started INTEGER,last_seen INTEGER,segment TEXT,pages INTEGER,interactions INTEGER,entry TEXT,exit TEXT,signup INTEGER,submitted INTEGER,registered INTEGER,source TEXT)''')
        db.execute('CREATE TABLE IF NOT EXISTS crawler_counters(day TEXT,bot TEXT,route TEXT,status INTEGER,value INTEGER,PRIMARY KEY(day,bot,route,status))')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('suite_started_at',?)",(datetime.now(timezone.utc).isoformat(timespec='seconds'),))
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('suite_capacity_skips','0')")

def signal():
    return request.headers.get('DNT')=='1' or request.headers.get('Sec-GPC')=='1'

def external_host():
    try:
        ref=urlsplit(request.referrer or '');host=(ref.hostname or '').lower().rstrip('.')
        if ref.scheme not in ('http','https') or ref.username or ref.password or not host or len(host)>253:return None
        host=host.removeprefix('www.')
        if host in ('neonrest.com',(urlsplit(request.host_url).hostname or '').removeprefix('www.')):return None
        try:ipaddress.ip_address(host);return None
        except ValueError:pass
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '..' in host or '.' not in host:return None
        if host.endswith(('.local','.internal','.lan','.invalid','.test','.example')):return None
        return host
    except ValueError:return None

def route_name():
    # Route definitions contain placeholders, never actual values or query strings.
    rule=request.url_rule.rule if request.url_rule else None
    if rule and not rule.startswith(('/static','/shared-media','/uploads','/media/','/manage','/staff','/account','/verify','/reset','/recover','/support','/family','/document','/ad/')):
        return rule[:160]
    if not rule:return request.path if request.path in ('/robots.txt','/sitemap.xml') else 'Unmatched route'
    return None

def bot_name():
    ua=request.headers.get('User-Agent','')[:512].lower()
    if not basic.BOT.search(ua):return None
    for needle,name in [('googlebot','Googlebot'),('bingbot','Bingbot'),('duckduckbot','DuckDuckBot'),('applebot','Applebot'),('yandex','Yandex'),('baiduspider','Baidu'),('facebookexternalhit','Facebook preview'),('twitterbot','X preview'),('gptbot','GPTBot'),('chatgpt-user','ChatGPT user agent'),('oai-searchbot','OpenAI search'),('claudebot','ClaudeBot')]:
        if needle in ua:return name
    return 'Other advertised automation'

def increment(db,table,values):
    # Bounded tables; existing rows continue to count at capacity.
    if db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]>=CAPS[table]:
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='suite_capacity_skips'");return False
    marks=','.join('?' for _ in values);db.execute('INSERT INTO '+table+' VALUES ('+marks+')',values);return True

def report(path,opts):
    wanted=detail.allowed_segments(opts['traffic']);marks=','.join('?' for _ in wanted)
    start=int(datetime.fromisoformat(opts['start']).replace(tzinfo=timezone.utc).timestamp());end=int(datetime.fromisoformat(opts['end']).replace(tzinfo=timezone.utc).timestamp())+86400
    now=int(time.time())
    with sqlite3.connect(path,timeout=.2) as db:
        db.row_factory=sqlite3.Row
        unique=db.execute('SELECT COUNT(DISTINCT visitor) FROM visitor_days WHERE day BETWEEN ? AND ? AND segment IN ('+marks+')',(opts['start'],opts['end'],*wanted)).fetchone()[0]
        sessions=[dict(r) for r in db.execute('SELECT * FROM browser_sessions WHERE started>=? AND started<? AND segment IN ('+marks+')',(start,end,*wanted))]
        rows=db.execute("SELECT kind,label,detail,SUM(value) AS n FROM hourly_counters WHERE bucket>=? AND bucket<? AND segment IN ("+marks+") AND kind IN ('request','feature','referrer','measurement') GROUP BY kind,label,detail",(opts['start'],datetime.fromtimestamp(end,timezone.utc).date().isoformat(),*wanted)).fetchall()
        crawlers=[dict(r) for r in db.execute('SELECT bot,route,status,SUM(value) AS n FROM crawler_counters WHERE day BETWEEN ? AND ? GROUP BY bot,route,status',(opts['start'],opts['end']))]
        meta=dict(db.execute('SELECT key,value FROM metadata'));capacity={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in CAPS}
        earlier={r[0] for r in db.execute('SELECT DISTINCT visitor FROM visitor_days WHERE day<?',(opts['start'],))};returning=len(earlier & {s['visitor'] for s in sessions})
        daily_unique=[{'label':r[0],'count':r[1]} for r in db.execute('SELECT day,COUNT(DISTINCT visitor) FROM visitor_days WHERE day BETWEEN ? AND ? AND segment IN ('+marks+') GROUP BY day ORDER BY day DESC',(opts['start'],opts['end'],*wanted))]
    tables={k:Counter() for k in ('feature','referrer','measurement','request')};errors=Counter();responses=Counter()
    for r in rows:
        if r['kind']=='request':
            code=int(r['detail']);responses[str(code)]+=r['n']
            if code>=400:errors[r['label']+' · HTTP '+str(code)]+=r['n']
        else:tables[r['kind']][r['label']]+=r['n']
    complete=[s for s in sessions if s['last_seen']<=now-1800 and s['pages']>0];signup=[s for s in sessions if s['signup']];converted=sum(s['registered'] for s in signup)
    entry=Counter(s['entry'] for s in sessions if s['pages']);exit=Counter(s['exit'] for s in complete)
    def listing(counter,labels=None):return [{'label':(labels or {}).get(k,k),'count':v} for k,v in counter.most_common(100)]
    def rate(a,b):return round(a*100/b,1) if b else None
    bots=Counter();botroutes=Counter();botstatus=Counter()
    for r in crawlers:bots[r['bot']]+=r['n'];botroutes[r['route']]+=r['n'];botstatus[str(r['status'])]+=r['n']
    totalresponses=sum(responses.values());client=sum(v for k,v in responses.items() if 400<=int(k)<500);server=sum(v for k,v in responses.items() if int(k)>=500)
    return {'unique':unique,'sessions':len(sessions),'completed':len(complete),'bounce':rate(sum(s['pages']==1 and s['interactions']==0 for s in complete),len(complete)),
        'pages_per_session':round(sum(s['pages'] for s in complete)/len(complete),2) if complete else None,'duration':round(sum(s['last_seen']-s['started'] for s in complete)/len(complete)) if complete else None,
        'signup_sessions':len(signup),'converted_sessions':converted,'conversion':rate(converted,len(signup)),'visit_conversion':rate(sum(s['registered'] for s in sessions),len(sessions)),
        'returning':returning,'daily_unique':daily_unique,'features':listing(tables['feature'],FEATURES),'referrers':listing(tables['referrer']),'entries':listing(entry,basic.LABELS),'exits':listing(exit,basic.LABELS),
        'eligible':tables['measurement']['eligible'],'measured':tables['measurement']['measured'],'coverage':rate(tables['measurement']['measured'],tables['measurement']['eligible']),
        'responses':totalresponses,'client_errors':client,'server_errors':server,'client_rate':rate(client,totalresponses),'server_rate':rate(server,totalresponses),'errors':listing(errors),'statuses':listing(responses),
        'bots':listing(bots),'bot_routes':listing(botroutes),'bot_statuses':listing(botstatus),'bot_total':sum(bots.values()),'started':meta.get('suite_started_at',''),'skips':int(meta.get('suite_capacity_skips',0)),'capacity':capacity}

def csv_rows(data):
    s=data['suite'];rows=[]
    for key in ('unique','sessions','completed','bounce','pages_per_session','duration','signup_sessions','converted_sessions','conversion','visit_conversion','returning','eligible','measured','coverage','responses','client_errors','server_errors','client_rate','server_rate','bot_total'):
        rows.append(('Browser / operations',key,s[key]))
    for key in ('features','referrers','entries','exits','daily_unique','errors','statuses','bots','bot_routes','bot_statuses'):
        rows.extend((key,r['label'],r['count']) for r in s[key])
    return rows

def register(app,core,path):
    try:
        initialize(path)
    except (OSError,sqlite3.Error):
        app.config['SITE_STATISTICS_ENABLED']=False
        app.logger.warning('Optional extended statistics storage unavailable')
    detail.KINDS.update({'request','feature','referrer','measurement'})
    basic.BOT=re.compile(basic.BOT.pattern+'|chatgpt-user',re.I)
    serializer=URLSafeTimedSerializer(app.secret_key,salt='neonrest-optional-analytics-v1')
    prefix='nr_sandbox_analytics_' if app.name.endswith('sandbox.app') else 'nr_analytics_'
    # app package name varies; the configured mount is authoritative at request time.
    def names():return ('nr_sandbox_analytics_' if request.script_root.rstrip('/')=='/sandbox' else 'nr_analytics_')
    def read(kind,age):
        try:return serializer.loads(request.cookies.get(names()+kind,''),max_age=age)
        except (BadSignature,TypeError,ValueError):return None
    def choice():return read('choice',90*86400)
    def cookie(response,kind,value,age):response.set_cookie(names()+kind,serializer.dumps(value),max_age=age,secure=True,httponly=True,samesite='Lax',path=request.script_root or '/')
    def clear(response):
        for kind in ('visitor','session'):response.delete_cookie(names()+kind,path=request.script_root or '/',secure=True,httponly=True,samesite='Lax')
    def digest(value):return hmac.new(str(app.secret_key).encode(),('analytics:'+value).encode(),hashlib.sha256).hexdigest()
    @app.context_processor
    def analytics_context():
        show=bool(app.config.get('SITE_STATISTICS_ENABLED')) and bool(basic.category(request.path)) and not bot_name()
        if show and 'theme_csrf_token' not in session:session['theme_csrf_token']=secrets.token_urlsafe(32)
        return {'analytics_banner':show and choice() not in ('yes','no') and not signal(),'analytics_choice':choice(),'analytics_signal':signal()}
    @app.post('/analytics/preference')
    def analytics_preference():
        origin=request.headers.get('Origin');expected=request.host_url.rstrip('/')
        supplied=request.form.get('theme_csrf_token','');known=session.get('theme_csrf_token','')
        if not known or not hmac.compare_digest(supplied,known) or (origin and origin!=expected):abort(403)
        value=request.form.get('choice')
        if value not in ('yes','no'):abort(400)
        response=redirect(url_for('privacy')+'#analytics');cookie(response,'choice',value,90*86400)
        if value=='no' or signal():clear(response)
        response.headers['Cache-Control']='private, no-store';return response
    @app.after_request
    def suite_measure(response):
        if response.mimetype=='text/html' and basic.category(request.path):response.headers['Cache-Control']='private, no-store'
        if signal():clear(response);return response
        if not app.config.get('SITE_STATISTICS_ENABLED'):return response
        try:
            route=route_name();bot=bot_name();now=int(time.time());day=datetime.fromtimestamp(now,timezone.utc).date().isoformat();cutoff=datetime.fromtimestamp(now-89*86400,timezone.utc).date().isoformat()
            with sqlite3.connect(path,timeout=.05) as db:
                db.execute('DELETE FROM visitor_days WHERE day<?',(cutoff,));db.execute('DELETE FROM browser_sessions WHERE started<?',(now-90*86400,));db.execute('DELETE FROM crawler_counters WHERE day<?',(cutoff,))
            if bot:
                if route:
                    with sqlite3.connect(path,timeout=.05) as db:
                        db.execute('DELETE FROM crawler_counters WHERE day<?',(cutoff,))
                        changed=db.execute('UPDATE crawler_counters SET value=min(value+1,2147483647) WHERE day=? AND bot=? AND route=? AND status=?',(day,bot,route,response.status_code))
                        if not changed.rowcount:increment(db,'crawler_counters',(day,bot,route,response.status_code,1))
                return response
            page=basic.category(request.path) if request.method=='GET' and response.status_code==200 and response.mimetype=='text/html' else None
            feature=request.endpoint if request.method=='POST' and request.endpoint in FEATURES else 'search' if request.endpoint=='search' and request.method=='GET' and response.status_code==200 and request.args.get('q','').strip() else None
            counts=[];segment=detail.traffic_segment(core)
            if route:counts.append(('request',route,str(response.status_code)))
            if feature:counts.append(('feature',feature,''))
            if page:
                counts.append(('measurement','eligible',''));host=external_host()
                if host:counts.append(('referrer',host,''))
            if choice()!='yes':
                clear(response)
                if counts:detail.write(path,counts,segment)
                return response
            if not page and not feature:
                if counts:detail.write(path,counts,segment)
                return response
            visitor=read('visitor',30*86400);sid=read('session',1800)
            if not isinstance(visitor,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}',visitor):visitor=secrets.token_urlsafe(24);sid=None
            if not isinstance(sid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}',sid):sid=secrets.token_urlsafe(24)
            vk=digest(visitor);sk=digest(sid)
            with sqlite3.connect(path,timeout=.05) as db:
                db.execute('DELETE FROM visitor_days WHERE day<?',(cutoff,));db.execute('DELETE FROM browser_sessions WHERE started<?',(now-90*86400,))
                row=db.execute('SELECT last_seen FROM browser_sessions WHERE key=?',(sk,)).fetchone()
                if row and row[0]<now-1800:sid=secrets.token_urlsafe(24);sk=digest(sid);row=None
                outcome=getattr(__import__('flask').g,'statistics_signup_outcome','');registered=int(str(outcome).startswith('created_'))
                if not row:
                    if not increment(db,'browser_sessions',(sk,vk,now,now,segment,int(bool(page)),int(bool(feature)),page or 'interaction',page or 'interaction',int(page=='signup' or feature=='signup'),int(feature=='signup'),registered,detail.source_category())):return response
                else:db.execute('UPDATE browser_sessions SET last_seen=?,pages=pages+?,interactions=interactions+?,exit=CASE WHEN ? IS NOT NULL THEN ? ELSE exit END,signup=max(signup,?),submitted=max(submitted,?),registered=max(registered,?) WHERE key=?',(now,int(bool(page)),int(bool(feature)),page,page,int(page=='signup' or feature=='signup'),int(feature=='signup'),registered,sk))
                if page:
                    if not db.execute('SELECT 1 FROM visitor_days WHERE day=? AND segment=? AND visitor=?',(day,segment,vk)).fetchone():increment(db,'visitor_days',(day,segment,vk))
                    counts.append(('measurement','measured',''))
            cookie(response,'visitor',visitor,30*86400);cookie(response,'session',sid,1800)
            if counts:detail.write(path,counts,segment)
        except Exception:app.logger.warning('Optional extended statistics write skipped')
        return response
    from .statistics_insights import register as register_insights
    register_insights(app,core,path)
