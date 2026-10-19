"""Bounded, first-party aggregate measurement. No visitor identifiers or raw URLs."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import io
import os
import re
import sqlite3
from urllib.parse import urlsplit
from flask import abort, g, make_response, redirect, render_template, request, session, url_for

LABELS = {
    'home':'Homepage', 'feed':'Feed', 'signup':'Signup', 'login':'Sign in',
    'explore':'Vibe directory', 'vibe':'Vibe pages', 'circles':'Circles directory',
    'circle':'Circle pages', 'profile':'Profiles', 'post':'Post pages',
    'guide':'User guide', 'search':'Search', 'about':'About', 'legal':'Policies',
    'markdown':'Formatting guide', 'dev':'Dev log',
}
EXACT = {
    '/':'home', '/feed':'feed', '/signup':'signup', '/login':'login',
    '/explore':'explore', '/circles':'circles', '/guide':'guide', '/search':'search',
    '/about':'about', '/terms':'legal', '/privacy':'legal', '/markdown-guide':'markdown', '/dev':'dev',
}
OUTCOMES = {
    'created_queued':'Account created; verification queued',
    'created_sent':'Account created; verification accepted for delivery',
    'created_mail_problem':'Account created; verification could not be queued/sent',
    'invalid_email':'Email format rejected', 'unavailable':'Handle or email unavailable',
    'rejected':'Form or eligibility check rejected', 'limited':'Request rate limited',
    'agreement':'Terms / privacy acknowledgment missing', 'name':'Required name missing or invalid',
    'fields':'Required signup fields missing', 'password':'Password length rejected',
    'eligibility':'Age / eligibility rejected', 'timezone':'Birthday timezone invalid',
    'security':'Security / origin check rejected', 'error':'Server error', 'incomplete':'No account created; other response',
    'verified':'Email verification completed', 'verification_invalid':'Invalid or expired verification link',
}
BOT = re.compile(r'bot|crawler|spider|slurp|headless|python|curl|wget|monitor|preview|facebookexternalhit|lighthouse', re.I)
RETENTION_DAYS = 90


def category(path):
    """Only fixed categories leave this function; no identifiers, queries or names."""
    if path in EXACT:
        return EXACT[path]
    if re.fullmatch(r'/vibe/[^/]+', path):
        return 'vibe'
    if re.fullmatch(r'/circles/[^/]+', path):
        return 'circle'
    if re.fullmatch(r'/@[^/]+', path) or re.fullmatch(r'/user(?:_test)?/\d+', path):
        return 'profile'
    if re.fullmatch(r'/posts/[^/]+', path):
        return 'post'
    return None


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(path, timeout=1) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS counters(day TEXT NOT NULL,kind TEXT NOT NULL,
            label TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',value INTEGER NOT NULL,
            PRIMARY KEY(day,kind,label,detail))''')
        db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('started_at',?)", (datetime.now(timezone.utc).isoformat(timespec='seconds'),))
    os.chmod(path, 0o600)
    from .statistics_detail import initialize as initialize_detail
    initialize_detail(path)


def add_counts(path, counts, day=None):
    """Separate connection: never commit or roll back a user's application transaction."""
    today = datetime.now(timezone.utc).date()
    cutoff = (today-timedelta(days=RETENTION_DAYS-1)).isoformat()
    with sqlite3.connect(path, timeout=.25) as db:
        db.execute('DELETE FROM counters WHERE day<?', (cutoff,))
        for kind, label, detail in counts:
            db.execute('''INSERT INTO counters VALUES (?,?,?,?,1)
                ON CONFLICT(day,kind,label,detail) DO UPDATE SET value=min(value+1,2147483647)''',
                (day or today.isoformat(), kind, label, detail))


def eligible(core):
    if request.headers.get('DNT')=='1' or request.headers.get('Sec-GPC')=='1':
        return False
    if BOT.search(request.headers.get('User-Agent','')[:512]):
        return False
    return True


def previous_category():
    try:
        ref=urlsplit(request.referrer or '')
        current=urlsplit(request.host_url)
        if ref.scheme not in ('http','https') or ref.netloc.casefold()!=current.netloc.casefold():
            return None
        path=ref.path
        root=request.script_root.rstrip('/')
        if root:
            if not path.startswith(root+'/'):
                return None
            path=path[len(root):]
        elif path.startswith('/sandbox/'):
            return None
        return category(path)
    except ValueError:
        return None


def permitted(core):
    uid=session.get('user_id')
    if not isinstance(uid,int):
        return False
    db=core.get_db()
    user=db.execute('SELECT verified FROM users WHERE id=?',(uid,)).fetchone()
    if not user or not user['verified'] or not (uid==1 or core.has_staff_permission(db,uid,'manage_roles')):
        return False
    for sql in ('SELECT 1 FROM user_moderation WHERE user_id=? AND banned=1',
                'SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1',
                'SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1'):
        if db.execute(sql,(uid,)).fetchone():
            return False
    return True


def report(path, days):
    today=datetime.now(timezone.utc).date()
    start=(today-timedelta(days=days-1)).isoformat()
    with sqlite3.connect(path, timeout=0.15) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT * FROM counters WHERE day BETWEEN ? AND ? ORDER BY day,kind,label,detail',(start,today.isoformat()))]
        started=db.execute("SELECT value FROM metadata WHERE key='started_at'").fetchone()[0]
    totals=defaultdict(int);pages=defaultdict(int);outcomes=defaultdict(int);flows=defaultdict(int);daily=defaultdict(lambda:defaultdict(int))
    for row in rows:
        k,l,d,v=row['kind'],row['label'],row['detail'],row['value']
        if k=='page':
            totals['views']+=v;pages[l]+=v;daily[row['day']]['views']+=v
        elif k=='signup':
            outcomes[l]+=v
            if l not in ('verified','verification_invalid'):
                totals['attempts']+=v;daily[row['day']]['attempts']+=v
            if l.startswith('created_'):
                totals['created']+=v;daily[row['day']]['created']+=v
            if l=='verified':
                totals['verified']+=v;daily[row['day']]['verified']+=v
        elif k=='flow':
            flows[(l,d)]+=v
    series=[]
    for offset in range(days):
        day=(today-timedelta(days=days-1-offset)).isoformat()
        series.append({'day':day,**{k:daily[day][k] for k in ('views','attempts','created','verified')}})
    return dict(rows=rows,started=started,start=start,end=today.isoformat(),totals=totals,
        pages=sorted(pages.items(),key=lambda x:(-x[1],x[0])),
        outcomes=sorted(outcomes.items(),key=lambda x:(-x[1],x[0])),
        flows=sorted(flows.items(),key=lambda x:(-x[1],x[0]))[:30],series=series,
        peak=max([r['views'] for r in series]+[1]))


def register(app,core):
    # A private sidecar keeps optional counters away from account transactions/backups.
    path=Path(os.environ.get('NEONREST_STATISTICS_DATABASE') or app.config.get('SITE_STATISTICS_DATABASE') or str(Path(app.instance_path)/'site-statistics.sqlite'))
    available=True
    try:
        initialize(path)
    except (OSError,sqlite3.Error):
        available=False
        app.logger.warning('Optional site statistics storage unavailable')
    app.config.setdefault('SITE_STATISTICS_ENABLED',available)
    if not available:
        app.config['SITE_STATISTICS_ENABLED']=False
    app.extensions['site_statistics']={'path':path,'record':add_counts,'report':report}
    @app.context_processor
    def statistics_context():
        return {'can_view_statistics':lambda:permitted(core)}
    @app.before_request
    def statistics_guard():
        if request.endpoint not in ('site_statistics','site_statistics_csv','statistics_search_import'):
            return
        if not permitted(core):
            abort(403)
        safety=core.get_db().execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(session['user_id'],)).fetchone()
        if not safety or not safety['totp_secret']:
            return redirect(url_for('community_security'))
        if request.endpoint=='statistics_search_import' and not app.extensions['community_auth_helpers']['fresh']():
            return redirect(url_for('community_reauth',next=url_for('site_statistics')))
    @app.after_request
    def measure(response):
        if not app.config['SITE_STATISTICS_ENABLED']:
            return response
        try:
            if not eligible(core):
                return response
            counts=[]
            if request.method=='GET' and response.status_code==200 and response.mimetype=='text/html':
                label=category(request.path)
                if label:
                    counts.append(('page',label,''))
                    prev=previous_category()
                    if prev:
                        counts.append(('flow',prev,label))
            if request.endpoint=='signup' and request.method=='POST':
                outcome=getattr(g,'statistics_signup_outcome',None)
                if response.status_code>=500 and not str(outcome or '').startswith('created_'):
                    outcome='error'
                if not outcome:
                    outcome='error' if response.status_code>=500 else 'limited' if response.status_code==429 else 'security' if response.status_code==403 else 'rejected' if response.status_code>=400 else 'incomplete'
                if outcome in OUTCOMES:
                    counts.append(('signup',outcome,''))
            if request.endpoint=='verify_email' and request.method=='GET':
                outcome=getattr(g,'statistics_verification_outcome',None)
                if outcome in ('verified','verification_invalid'):
                    counts.append(('signup',outcome,''))
            if counts:
                from .statistics_detail import record
                record(core,path,counts)
        except Exception:
            # Metrics must never prevent login, signup, posting, or response delivery.
            app.logger.warning('Optional site statistics write skipped')
        return response
    from .statistics_suite import register as register_suite
    register_suite(app,core,path)
    def selected_days():
        value=request.args.get('days','7')
        if value not in ('7','30','90'):
            abort(400)
        return int(value)
    @app.get('/manage/statistics')
    def site_statistics():
        if not available:
            abort(503,description='Site statistics storage is temporarily unavailable.')
        from .statistics_detail import options, build_report
        try:
            data=build_report(core,path,options())
            from .statistics_suite import report as suite_report
            data['suite']=suite_report(path,data['opts'])
            from .statistics_insights import report as insights_report
            data['insights']=insights_report(path,data['opts'])
            extension=app.extensions.get('network_security',{})
            data['network_errors']={'rows':[],'started':'Unavailable','skips':0}
            if extension.get('available'):
                from .network_security import errors_report
                try:data['network_errors']=errors_report(extension['path'],data['opts'])
                except sqlite3.Error:pass
        except sqlite3.Error:
            abort(503,description='Statistics storage is busy. Try again shortly.')
        import secrets
        session.setdefault('theme_csrf_token',secrets.token_urlsafe(32))
        response=make_response(render_template('site_statistics.html',**data))
        response.headers['Cache-Control']='private, no-store'
        return response
    @app.get('/manage/statistics.csv')
    def site_statistics_csv():
        if not available:
            abort(503,description='Site statistics storage is temporarily unavailable.')
        from .statistics_detail import options, build_report, csv_report
        try:
            data=build_report(core,path,options())
            from .statistics_suite import report as suite_report
            data['suite']=suite_report(path,data['opts'])
            from .statistics_insights import report as insights_report
            data['insights']=insights_report(path,data['opts'])
            extension=app.extensions.get('network_security',{})
            data['network_errors']={'rows':[],'started':'Unavailable','skips':0}
            if extension.get('available'):
                from .network_security import errors_report
                try:data['network_errors']=errors_report(extension['path'],data['opts'])
                except sqlite3.Error:pass
        except sqlite3.Error:
            abort(503,description='Statistics storage is busy. Try again shortly.')
        response=make_response(csv_report(data));response.mimetype='text/csv'
        response.headers['Content-Disposition']='attachment; filename=neonrest-statistics.csv'
        response.headers['Cache-Control']='private, no-store'
        return response
