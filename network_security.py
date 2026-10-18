"""Bounded private network-security records and redacted error diagnostics."""
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit,unquote
import ipaddress
import os
import re
import secrets
import sqlite3
import time
from functools import wraps
from flask import has_app_context,abort,current_app,flash,g,make_response,redirect,render_template,request,session,url_for
from . import site_statistics as statistics

EVENT_CAP=20000
ERROR_CAP=10000
AUDIT_CAP=5000
BAN_CAP=1000
RETENTION=30*86400
SENSITIVE=re.compile(r'password|recover|reset|token|verif|document|submission|invitation|export|oauth|callback|secret|reauth|factor|consent|guardian',re.I)
SCAN=re.compile(r'^/(?:wp-admin(?:/|$)|wp-content(?:/|$)|wp-includes(?:/|$)|wordpress(?:/|$)|xmlrpc\.php$|\.env(?:\.|$)|\.git(?:/|$)|phpmyadmin(?:/|$))',re.I)

def canonical(value):
    try:
        if not isinstance(value,str) or len(value)>64 or '%' in value:return None
        parsed=ipaddress.ip_address(value.strip())
        if isinstance(parsed,ipaddress.IPv6Address) and parsed.ipv4_mapped:parsed=parsed.ipv4_mapped
        return str(parsed)
    except ValueError:return None

class ClientAddress:
    """Only an explicitly configured PythonAnywhere deployment trusts X-Real-IP.

    PA overwrites X-Real-IP with its socket peer. Never trust the first XFF item.
    Local/direct deployments ignore all forwarded address headers.
    """
    def __init__(self,application,app):self.application=application;self.app=app
    def __call__(self,environ,start_response):
        peer=canonical(environ.get('REMOTE_ADDR'))
        mode=self.app.config.get('CLIENT_IP_MODE','direct')
        if mode=='pythonanywhere':
            address=canonical(environ.get('HTTP_X_REAL_IP'))
            if address and not ipaddress.ip_address(address).is_global and not self.app.testing:address=None
        else:address=peer
        environ['neonrest.client_ip']=address or ''
        environ['neonrest.ip_source']='pythonanywhere' if mode=='pythonanywhere' and address else 'direct' if address else 'unavailable'
        environ['REMOTE_ADDR']=address or 'unavailable'
        return self.application(environ,start_response)

def client_ip():return canonical(request.environ.get('neonrest.client_ip',''))

def path_detail(value,rule=None):
    """Keep useful path spelling, but remove queries, identities and secret-like values."""
    try:
        path=urlsplit(value or '').path
        for _ in range(3):path=unquote(path)
    except (ValueError,UnicodeError):return '[invalid path]'
    if len(path)>1000:return '[oversized path]'
    if SENSITIVE.search(path) or any(ord(c)<32 or ord(c)==127 for c in path):return '[private workflow or unsafe path]'
    if rule:return rule[:180]
    parts=[]
    for segment in path.split('/'):
        if not segment:continue
        if segment.startswith('@'):parts.append('[handle]')
        elif len(segment)>48 or re.search(r'@|[^a-zA-Z0-9._~-]',segment):parts.append('[value]')
        elif canonical(segment) or segment.isdecimal() or re.fullmatch(r'[0-9a-fA-F-]{20,}',segment):parts.append('[identifier]')
        elif len(segment)>=16 and re.search(r'[A-Z0-9]',segment):parts.append('[identifier]')
        else:parts.append(segment)
        if len(parts)==8:parts.append('[remainder]');break
    # Dynamic destination identifiers are private even when the route did not match.
    for i,segment in enumerate(parts[:-1]):
        if segment.lower() in ('posts','circles','user','users','edit_post','delete_post','shared-media','uploads'):parts[i+1]='[identifier]'
    return ('/'+ '/'.join(parts))[:180]

def safe_referrer(core):
    try:
        ref=urlsplit(request.referrer or '')
        if ref.scheme not in ('http','https') or ref.netloc.casefold()!=urlsplit(request.host_url).netloc.casefold():return ''
        path=ref.path;root=request.script_root.rstrip('/')
        if root:
            if not path.startswith(root+'/'):return ''
            path=path[len(root):]
        elif path.startswith('/sandbox/'):return ''
        # Resolve templates using the route map, never save a private referring identifier.
        adapter=current_app.url_map.bind('localhost')
        try:
            rule,args=adapter.match(path,method='GET',return_rule=True)
            return path_detail(path,rule.rule)
        except Exception:return path_detail(path)
    except ValueError:return ''

def classification():
    if SCAN.search(request.path):return 'Suspected scanning'
    if statistics.BOT.search(request.headers.get('User-Agent','')[:512]):return 'Advertised automation'
    return 'Unclassified'

def initialize(path):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with sqlite3.connect(path,timeout=1) as db:
        db.execute('PRAGMA auto_vacuum=INCREMENTAL')
        db.execute('''CREATE TABLE IF NOT EXISTS security_events(day INTEGER,ip TEXT,actor INTEGER,kind TEXT,method TEXT,path TEXT,status INTEGER,first_seen INTEGER,last_seen INTEGER,count INTEGER,PRIMARY KEY(day,ip,actor,kind,method,path,status))''')
        db.execute('''CREATE TABLE IF NOT EXISTS error_details(day INTEGER,segment TEXT,method TEXT,path TEXT,status INTEGER,referrer TEXT,classification TEXT,first_seen INTEGER,last_seen INTEGER,count INTEGER,PRIMARY KEY(day,segment,method,path,status,referrer,classification))''')
        db.execute('''CREATE TABLE IF NOT EXISTS ip_bans(id INTEGER PRIMARY KEY,ip TEXT,created INTEGER,expires INTEGER,actor INTEGER,reason TEXT,revoked INTEGER,revoked_by INTEGER,release_reason TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS ip_bans_lookup ON ip_bans(ip,expires,revoked)')
        db.execute('CREATE TABLE IF NOT EXISTS network_audit(id INTEGER PRIMARY KEY,at INTEGER,actor INTEGER,action TEXT,target TEXT,reason TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT)')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('started_at',?)",(str(int(time.time())),))
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('capacity_skips','0')")
        db.execute('PRAGMA secure_delete=ON')
    os.chmod(path,0o600)

def connect(path):
    db=sqlite3.connect(path,timeout=.08);db.row_factory=sqlite3.Row
    db.execute('PRAGMA secure_delete=ON');return db

def prune(db,now,force=False):
    last=db.execute("SELECT value FROM metadata WHERE key='last_pruned'").fetchone()
    if not force and last and now-int(last[0])<3600:return
    day=(now-RETENTION)//86400
    # Account preservation blockers also protect associated network evidence.
    old_events=db.execute('SELECT rowid,ip,actor FROM security_events WHERE day<=?',(day,)).fetchall()
    old_audit=db.execute('SELECT id,actor,target FROM network_audit WHERE at<?',(now-RETENTION,)).fetchall()
    old_bans=db.execute('SELECT id,ip,actor FROM ip_bans WHERE expires<?',(now-RETENTION,)).fetchall()
    protected=set();held_ips=set()
    core=current_app.extensions.get('network_security',{}).get('core') if has_app_context() else None
    if core and (old_events or old_audit or old_bans):
        from .privacy_workflows import blockers
        actors={r[0] for r in db.execute('SELECT DISTINCT actor FROM security_events UNION SELECT DISTINCT actor FROM network_audit UNION SELECT DISTINCT actor FROM ip_bans') if r[0]}
        protected={uid for uid in actors if blockers(core.get_db(),uid)}
        for uid in protected:
            held_ips.update(r[0] for r in db.execute('SELECT DISTINCT ip FROM security_events WHERE actor=?',(uid,)))
            held_ips.update(r[0] for r in db.execute('SELECT ip FROM ip_bans WHERE actor=?',(uid,)))
    db.executemany('DELETE FROM security_events WHERE rowid=?',[(r[0],) for r in old_events if r[2] not in protected and r[1] not in held_ips])
    db.execute('DELETE FROM error_details WHERE day<=?',(day,))
    db.executemany('DELETE FROM network_audit WHERE id=?',[(r[0],) for r in old_audit if r[1] not in protected and r[2] not in held_ips])
    db.executemany('DELETE FROM ip_bans WHERE id=?',[(r[0],) for r in old_bans if r[2] not in protected and r[1] not in held_ips])
    db.execute('PRAGMA incremental_vacuum(32)')
    db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_pruned',?)",(str(now),))

def audit(db,actor,action,target='',reason=''):
    now=int(time.time());prune(db,now)
    if db.execute('SELECT COUNT(*) FROM network_audit').fetchone()[0]>=AUDIT_CAP:
        abort(503,description='Security audit storage is full. Review retention and preservation records before making changes.')
    db.execute('INSERT INTO network_audit(at,actor,action,target,reason) VALUES (?,?,?,?,?)',(now,actor,action,target[:64],reason[:500]))

def capacity(db,table,limit):
    # All callers supply compile-time table names.
    if table=='security_events':count=db.execute('SELECT COUNT(*) FROM security_events').fetchone()[0]
    elif table=='error_details':count=db.execute('SELECT COUNT(*) FROM error_details').fetchone()[0]
    else:return False
    if count<limit:return True
    db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='capacity_skips'");return False

def staff_session(core):
    uid=session.get('user_id')
    if not statistics.permitted(core):return False
    from .community_features import digest
    row=core.get_db().execute('SELECT expires_at,revoked FROM active_sessions WHERE token_hash=? AND user_id=?',(digest(session.get('sid','')),uid)).fetchone()
    return bool(row and not row['revoked'] and row['expires_at']>time.time())

def errors_report(path,opts):
    from .statistics_detail import allowed_segments
    segments=allowed_segments(opts['traffic']);marks=','.join('?' for _ in segments)
    start=int(datetime.fromisoformat(opts['start']).replace(tzinfo=timezone.utc).timestamp())//86400
    end=int(datetime.fromisoformat(opts['end']).replace(tzinfo=timezone.utc).timestamp())//86400
    with connect(path) as db:
        rows=[dict(r) for r in db.execute('SELECT method,path,status,referrer,classification,MIN(first_seen) AS first_seen,MAX(last_seen) AS last_seen,SUM(count) AS count FROM error_details WHERE day BETWEEN ? AND ? AND segment IN ('+marks+') GROUP BY method,path,status,referrer,classification ORDER BY last_seen DESC LIMIT 200',(start,end,*segments))]
        meta=dict(db.execute('SELECT * FROM metadata'))
    return {'rows':rows,'started':stamp(int(meta.get('started_at','0'))),'skips':int(meta.get('capacity_skips','0'))}

def stamp(value):return datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value else '—'

def register(app,core):
    fallback=Path('/home/sinbot/private')/('neonrest_sandbox' if 'sandbox' in app.import_name else 'neonrest_production')/'network-security.sqlite'
    stats_override=os.environ.get('NEONREST_STATISTICS_DATABASE')
    path=Path(os.environ.get('NEONREST_SECURITY_DATABASE') or (str(Path(stats_override).with_name('network-security.sqlite')) if stats_override else str(fallback)))
    app.config.setdefault('CLIENT_IP_MODE',os.environ.get('NEONREST_CLIENT_IP_MODE','direct'))
    app.wsgi_app=ClientAddress(app.wsgi_app,app)
    available=True
    try:initialize(path)
    except (OSError,sqlite3.Error):available=False;app.logger.warning('Private network security storage unavailable')
    app.extensions['network_security']={'path':path,'available':available,'core':core}
    app.jinja_env.filters['utc_stamp']=stamp
    def storage_errors(view):
        @wraps(view)
        def wrapped(*args,**kwargs):
            try:return view(*args,**kwargs)
            except sqlite3.Error:abort(503,description='Security storage is busy. Try again shortly.')
        return wrapped
    @app.before_request
    def network_guard():
        if request.endpoint in ('manage_network_security','network_ban','network_revoke'):
            if not statistics.permitted(core):abort(403)
            safety=core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(session['user_id'],)).fetchone()
            if not safety or not safety['totp_secret']:return redirect(url_for('community_security'))
            if not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=url_for('manage_network_security')))
            if not available:abort(503,description='Security storage is temporarily unavailable.')
            if request.method=='POST':app.extensions['community_auth_helpers']['csrf']()
        ip=client_ip()
        if not available or not ip or request.endpoint=='static' or request.path in ('/privacy','/terms'):return None
        try:
            with connect(path) as db:
                now=int(time.time());last=db.execute("SELECT value FROM metadata WHERE key='last_pruned'").fetchone()
                if not last or now-int(last[0])>=3600:
                    prune(db,now);db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_pruned',?)",(str(now),))
                banned=db.execute('SELECT expires FROM ip_bans WHERE ip=? AND expires>? AND revoked=0 LIMIT 1',(ip,int(time.time()))).fetchone()
            if banned and not staff_session(core):
                g.network_ban=True
                response=make_response('Access from this network is temporarily restricted. For help, contact ToS@neonrest.com.',403)
                response.headers['Cache-Control']='private, no-store';return response
        except sqlite3.Error:app.logger.warning('Network restriction lookup unavailable')
    @app.after_request
    def security_record(response):
        if request.endpoint in ('manage_network_security','network_ban','network_revoke'):
            response.headers['Cache-Control']='private, no-store';response.headers['Referrer-Policy']='no-referrer';response.headers['X-Robots-Tag']='noindex, nofollow'
        if not available or request.endpoint=='static':return response
        status=response.status_code
        authentication=request.method=='POST' and request.endpoint in ('login','community_login_factor','community_reauth','password_reset_request','password_reset','signup')
        if status<400 and not authentication:return response
        now=int(time.time());day=now//86400;rule=request.url_rule.rule if request.url_rule else None
        location=path_detail(request.path,rule);method=request.method if request.method in ('GET','POST','HEAD','PUT','DELETE','PATCH','OPTIONS') else 'OTHER'
        kind='Network block' if getattr(g,'network_ban',False) else 'Authentication request' if authentication else 'Rate limited' if status==429 else classification() if classification()!='Unclassified' else 'HTTP error'
        actor=session.get('user_id') if isinstance(session.get('user_id'),int) else 0
        try:
            with connect(path) as db:
                prune(db,now)
                ip=client_ip()
                if ip:
                    values=(day,ip,actor,kind,method,location,status)
                    changed=db.execute('UPDATE security_events SET last_seen=?,count=min(count+1,2147483647) WHERE day=? AND ip=? AND actor=? AND kind=? AND method=? AND path=? AND status=?',(now,*values))
                    if not changed.rowcount and capacity(db,'security_events',EVENT_CAP):db.execute('INSERT INTO security_events VALUES (?,?,?,?,?,?,?,?,?,1)',(*values,now,now))
                # Debugging aggregates honor analytics signals and contain no IP/account identifiers.
                if status>=400 and request.headers.get('DNT')!='1' and request.headers.get('Sec-GPC')!='1' and not request.path.startswith(('/manage','/staff','/account')):
                    from .statistics_detail import traffic_segment
                    key=(day,traffic_segment(core),method,location,status,safe_referrer(core),classification())
                    changed=db.execute('UPDATE error_details SET last_seen=?,count=min(count+1,2147483647) WHERE day=? AND segment=? AND method=? AND path=? AND status=? AND referrer=? AND classification=?',(now,*key))
                    if not changed.rowcount and capacity(db,'error_details',ERROR_CAP):db.execute('INSERT INTO error_details VALUES (?,?,?,?,?,?,?,?,?,1)',(*key,now,now))
        except Exception:app.logger.warning('Private network event write skipped')
        return response
    @app.route('/manage/security',methods=['GET','POST'])
    @storage_errors
    def manage_network_security():
        ip=request.form.get('ip','').strip() if request.method=='POST' else '';page=request.form.get('page','1') if request.method=='POST' else '1'
        if ip and not canonical(ip):abort(400,description='Enter one valid IP address.')
        if not page.isdecimal() or not 1<=int(page)<=200:abort(400)
        page=int(page)
        with connect(path) as db:
            audit(db,session['user_id'],'View security log',reason='Filtered' if ip else 'Recent events')
            if ip:events=[dict(r) for r in db.execute('SELECT * FROM security_events WHERE ip=? ORDER BY last_seen DESC LIMIT 100 OFFSET ?',(canonical(ip),(page-1)*100))]
            else:events=[dict(r) for r in db.execute('SELECT * FROM security_events ORDER BY last_seen DESC LIMIT 100 OFFSET ?',((page-1)*100,))]
            bans=[dict(r) for r in db.execute('SELECT * FROM ip_bans ORDER BY id DESC LIMIT 100')];history=[dict(r) for r in db.execute('SELECT * FROM network_audit ORDER BY id DESC LIMIT 100')];meta=dict(db.execute('SELECT * FROM metadata'))
        return render_template('network_security.html',events=events,bans=bans,history=history,meta=meta,page=page,ip_filter=ip,proxy_mode=app.config['CLIENT_IP_MODE'],ip_available=bool(client_ip()),csrf=session.setdefault('theme_csrf_token',secrets.token_urlsafe(32)))
    @app.post('/manage/security/ban')
    @storage_errors
    def network_ban():
        ip=canonical(request.form.get('ip'));hours=request.form.get('hours');reason=' '.join(request.form.get('reason','').split())
        if not ip or hours not in ('1','24','168') or not 5<=len(reason)<=500 or request.form.get('shared_warning')!='yes':abort(400,description='Enter an IP, expiry and factual reason, and acknowledge the shared-address warning.')
        parsed=ipaddress.ip_address(ip)
        if not parsed.is_global and not app.testing:abort(400,description='Only public client addresses can be blocked.')
        if not client_ip():abort(503,description='Your client address could not be verified. No restriction was created.')
        if ip==client_ip():abort(400,description='You cannot block the address you are currently using.')
        now=int(time.time())
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');prune(db,now)
            if db.execute('SELECT 1 FROM ip_bans WHERE ip=? AND expires>? AND revoked=0',(ip,now)).fetchone():abort(409,description='An active restriction already exists for this address.')
            if db.execute('SELECT COUNT(*) FROM ip_bans').fetchone()[0]>=BAN_CAP:abort(503,description='Restriction storage is full; review existing records.')
            db.execute('INSERT INTO ip_bans(ip,created,expires,actor,reason,revoked,revoked_by,release_reason) VALUES (?,?,?,?,?,0,NULL,NULL)',(ip,now,now+int(hours)*3600,session['user_id'],reason));audit(db,session['user_id'],'Create IP restriction',ip,reason)
        flash('Temporary IP restriction created. Verified owner/admin sessions remain available for recovery.','success');return redirect(url_for('manage_network_security'))
    @app.post('/manage/security/ban/<int:ban_id>/revoke')
    @storage_errors
    def network_revoke(ban_id):
        reason=' '.join(request.form.get('reason','').split())
        if not 5<=len(reason)<=500:abort(400,description='Enter a factual release reason.')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM ip_bans WHERE id=?',(ban_id,)).fetchone()
            if not row:abort(404)
            if not row['revoked']:
                db.execute('UPDATE ip_bans SET revoked=1,revoked_by=?,release_reason=? WHERE id=?',(session['user_id'],reason,ban_id));audit(db,session['user_id'],'Revoke IP restriction',row['ip'],reason)
        flash('IP restriction released.','success');return redirect(url_for('manage_network_security'))
