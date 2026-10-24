"""Structured events with current personal/page age rules and private Circle views."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import secrets,time,json
from flask import Blueprint,abort,flash,redirect,render_template,request,session,url_for,Response
from . import identity_pages as pages,age_policy as ages,circles
from .community_features import blocked


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS calendar_events(id TEXT PRIMARY KEY,creator_id INTEGER NOT NULL REFERENCES users(id),
        page_id TEXT REFERENCES identity_pages(id),circle_id INTEGER REFERENCES circles(id),
        title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',location TEXT NOT NULL DEFAULT '',
        starts_at INTEGER NOT NULL,ends_at INTEGER NOT NULL,zone TEXT NOT NULL,
        audience TEXT NOT NULL CHECK(audience IN ('private','public','circle')),
        canceled INTEGER NOT NULL DEFAULT 0,staff_hidden INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS calendar_event_start ON calendar_events(starts_at,id)')
    db.execute('CREATE INDEX IF NOT EXISTS calendar_event_creator ON calendar_events(creator_id,starts_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS calendar_responses(event_id TEXT NOT NULL REFERENCES calendar_events(id),
        user_id INTEGER NOT NULL REFERENCES users(id),response TEXT NOT NULL CHECK(response IN ('going','interested')),
        updated_at INTEGER NOT NULL,PRIMARY KEY(event_id,user_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS calendar_audit(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL REFERENCES calendar_events(id),
        actor_id INTEGER NOT NULL,action TEXT NOT NULL,created_at INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS calendar_reports(id INTEGER PRIMARY KEY,event_id TEXT NOT NULL REFERENCES calendar_events(id),
        reporter_id INTEGER NOT NULL,reason TEXT NOT NULL,snapshot TEXT NOT NULL,created_at INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',reviewed_by INTEGER,decision TEXT,decision_reason TEXT,reviewed_at INTEGER)''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS calendar_report_pending ON calendar_reports(event_id,reporter_id) WHERE status='open'")
    db.execute('''CREATE TRIGGER IF NOT EXISTS calendar_evidence_immutable BEFORE UPDATE OF event_id,reporter_id,reason,snapshot,created_at ON calendar_reports
        BEGIN SELECT RAISE(ABORT,'Event evidence is immutable'); END''')


def get(db,ref):
    row=db.execute('SELECT * FROM calendar_events WHERE id=?',(ref,)).fetchone()
    if not row:raise pages.PageError('Event unavailable.',404)
    return row


def visible(db,event,uid):
    if not uid or not pages.eligible(db,event['creator_id'],'creative') or not ages.ready(db,uid):return False
    if blocked(db,event['creator_id'],uid) or not ages.can_read(db,event['creator_id'],uid):return False
    if event['circle_id']:
        circle=db.execute('SELECT * FROM circles WHERE id=?',(event['circle_id'],)).fetchone()
        if not circle or not circles.membership(db,circle,uid):return False
    if event['page_id']:
        page=pages.get(db,event['page_id'])
        if page['state']!='published' or pages.hidden(db,page['id']) or not pages.visible(db,page,uid):return False
    if uid==event['creator_id']:return True
    return not event['staff_hidden'] and not event['canceled'] and (event['audience']!='private')


def stamp(value,zone):
    try:
        local=datetime.fromisoformat(value)
        tz=ZoneInfo(zone)
        if local.tzinfo is None:
            candidates={int(local.replace(tzinfo=tz,fold=fold).timestamp()) for fold in (0,1)
                if local.replace(tzinfo=tz,fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)==local}
            if len(candidates)!=1:raise ValueError('Ambiguous or nonexistent local time; include an explicit UTC offset.')
            return candidates.pop()
        return int(local.timestamp())
    except (ValueError,TypeError,ZoneInfoNotFoundError,OverflowError) as error:
        raise pages.PageError('Enter a valid date/time and IANA timezone. Ambiguous daylight-saving times require an explicit UTC offset.') from error


def values(data):
    title=data.get('title','').strip();body=data.get('description','').strip();location=data.get('location','').strip();zone=data.get('zone','UTC').strip()
    if not 1<=len(title)<=100 or len(body)>4000 or len(location)>200 or len(zone)>80:raise pages.PageError('Use a title up to 100, description up to 4,000 and location up to 200 characters.')
    start,end=stamp(data.get('starts_at',''),zone),stamp(data.get('ends_at',''),zone)
    if not 0<start<end<2**40 or end-start>366*86400:raise pages.PageError('The end must follow the start, within 366 days.')
    audience=data.get('audience','private')
    if audience not in ('private','public','circle'):raise pages.PageError('Choose a valid event audience.')
    return title,body,location,start,end,zone,audience


def audit(db,ref,uid,action):db.execute('INSERT INTO calendar_audit(event_id,actor_id,action,created_at) VALUES (?,?,?,?)',(ref,uid,action,int(time.time())))


def create(db,uid,data):
    pages.require_eligible(db,uid,'creative')
    title,body,location,start,end,zone,audience=values(data)
    page_id=data.get('page_id') or None;circle_id=None
    if page_id:
        page=pages.get(db,page_id);pages.require_role(db,page,uid,('owner','manager','editor'))
        if page['state']!='published' or pages.hidden(db,page_id):raise pages.PageError('Publish an unrestricted page before adding events.',409)
    if audience=='circle':
        circle=circles.selected(db,uid,data.get('circle_id'))
        if not circle or not circles.membership(db,circle,uid):raise pages.PageError('Current Circle membership is required.',403)
        circle_id=circle['id']
    elif data.get('circle_id'):raise pages.PageError('Choose the Circle audience for a Circle event.')
    if db.execute('SELECT COUNT(*) FROM calendar_events WHERE creator_id=? AND ends_at>?',(uid,int(time.time()))).fetchone()[0]>=100:raise pages.PageError('The initial limit is 100 upcoming events.',409)
    ref=secrets.token_urlsafe(18);now=int(time.time())
    db.execute('''INSERT INTO calendar_events(id,creator_id,page_id,circle_id,title,description,location,starts_at,ends_at,zone,audience,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',(ref,uid,page_id,circle_id,title,body,location,start,end,zone,audience,now,now));audit(db,ref,uid,'create');return ref


def edit(db,uid,ref,revision,data):
    event=get(db,ref);pages.require_eligible(db,uid,'creative')
    if not manageable(db,event,uid):raise pages.PageError('You cannot manage this event.',403)
    # Audience/identity are immutable; create a separate event to change them.
    title,body,location,start,end,zone,_=values({**data,'audience':event['audience']})
    result=db.execute('''UPDATE calendar_events SET title=?,description=?,location=?,starts_at=?,ends_at=?,zone=?,revision=revision+1,updated_at=?
        WHERE id=? AND revision=?''',(title,body,location,start,end,zone,int(time.time()),ref,revision))
    if result.rowcount!=1:raise pages.PageError('Event changed; reload before saving.',409)
    audit(db,ref,uid,'edit')


def respond(db,uid,ref,response):
    event=get(db,ref);pages.require_eligible(db,uid,'creative')
    if not visible(db,event,uid) or event['canceled'] or event['staff_hidden']:raise pages.PageError('Event unavailable.',404)
    if response=='remove':db.execute('DELETE FROM calendar_responses WHERE event_id=? AND user_id=?',(ref,uid));return
    restricted=db.execute('SELECT interaction_restricted FROM user_moderation WHERE user_id=?',(uid,)).fetchone()
    if restricted and restricted[0]:raise pages.PageError('Interactions are restricted.',403)
    if response not in ('going','interested'):raise pages.PageError('Choose Going or Interested.')
    db.execute('INSERT INTO calendar_responses VALUES (?,?,?,?) ON CONFLICT(event_id,user_id) DO UPDATE SET response=excluded.response,updated_at=excluded.updated_at',(ref,uid,response,int(time.time())))


def manageable(db,event,uid):
    if not visible(db,event,uid):return False
    if event['page_id']:
        role=pages.role(db,pages.get(db,event['page_id']),uid)
        return role=='owner' or (event['creator_id']==uid and role in ('editor','manager'))
    return event['creator_id']==uid


def ics(event):
    def escape(value):return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    def when(value):return datetime.fromtimestamp(value,timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Neonrest//Calendar//EN','BEGIN:VEVENT','UID:'+event['id']+'@neonrest.com','DTSTAMP:'+when(event['updated_at']),'DTSTART:'+when(event['starts_at']),'DTEND:'+when(event['ends_at']),'SUMMARY:'+escape(event['title']),'DESCRIPTION:'+escape(event['description']),'LOCATION:'+escape(event['location']),'STATUS:'+('CANCELLED' if event['canceled'] else 'CONFIRMED'),'END:VEVENT','END:VCALENDAR']
    # Fold by UTF-8 byte length, with continuation space, per iCalendar.
    folded=[]
    for line in lines:
        chunk=''
        for char in line:
            if len((chunk+char).encode())>74:folded.append(chunk);chunk=' '+char
            else:chunk+=char
        folded.append(chunk)
    return '\r\n'.join(folded)+'\r\n'


def export_user(db,uid):return {'events':[dict(r) for r in db.execute('SELECT * FROM calendar_events WHERE creator_id=?',(uid,))],
    'responses':[dict(r) for r in db.execute('SELECT * FROM calendar_responses WHERE user_id=?',(uid,))],
    'own_reports':[dict(r) for r in db.execute('SELECT id,event_id,reason,status,decision,decision_reason FROM calendar_reports WHERE reporter_id=?',(uid,))]}


def register(app,core):
    bp=Blueprint('events',__name__)
    with app.app_context():initialize(core.get_db());core.get_db().commit()
    app.jinja_env.filters['event_iso']=lambda stamp:datetime.fromtimestamp(stamp,timezone.utc).isoformat()
    @bp.errorhandler(pages.PageError)
    def error(e):return render_template('identity_page_error.html',message=str(e)),e.status
    def actor():
        uid=session.get('user_id')
        if not uid:abort(401)
        pages.require_eligible(core.get_db(),uid,'creative');return uid
    def write(fresh=False):
        app.extensions['community_auth_helpers']['csrf']()
        if fresh and not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=request.path))
    @bp.get('/events')
    def calendar():
        uid=actor();db=core.get_db();month=request.args.get('month',datetime.now(timezone.utc).strftime('%Y-%m'))
        try:
            start=datetime.strptime(month,'%Y-%m').replace(tzinfo=timezone.utc);end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
        except (ValueError,OverflowError):abort(400)
        db.create_function('calendar_visible',1,lambda ref:int(visible(db,get(db,ref),uid)))
        rows=db.execute('SELECT * FROM calendar_events WHERE starts_at<? AND ends_at>=? AND calendar_visible(id)=1 ORDER BY starts_at,id LIMIT 201',(int(end.timestamp()),int(start.timestamp()))).fetchall()
        return render_template('events_calendar.html',events=rows[:200],month=month,truncated=len(rows)>200)
    @bp.route('/events/new',methods=['GET','POST'])
    def new():
        uid=actor();db=core.get_db()
        if request.method=='POST':
            response=write(True)
            if response is not None:return response
            limit=app.extensions['community_auth_helpers']['limited']('event-create',20)
            if limit is not None:return limit
            with db:
                db.execute('BEGIN IMMEDIATE');ref=create(db,uid,request.form)
            return redirect(url_for('events.detail',ref=ref))
        choices=[circle for circle in db.execute('SELECT c.* FROM circles c JOIN circle_members m ON m.circle_id=c.id WHERE m.user_id=? AND m.status=\'active\' ORDER BY c.id LIMIT 200',(uid,)) if circles.membership(db,circle,uid)]
        page_choices=[page for page in db.execute("SELECT * FROM identity_pages WHERE state='published' ORDER BY name LIMIT 500") if pages.role(db,page,uid)]
        from .circle_ids import public as circle_public
        return render_template('event_form.html',event=None,circles=choices,page_choices=page_choices,circle_public=lambda c:circle_public(db,c['id']))
    @bp.get('/events/<ref>')
    def detail(ref):
        uid=actor();db=core.get_db();event=get(db,ref)
        if not visible(db,event,uid):abort(404)
        r=db.execute('SELECT response FROM calendar_responses WHERE event_id=? AND user_id=?',(ref,uid)).fetchone()
        return render_template('event_detail.html',event=event,response=r['response'] if r else None,can_manage=manageable(db,event,uid))
    @bp.route('/events/<ref>/edit',methods=['GET','POST'])
    def manage(ref):
        uid=actor();db=core.get_db();event=get(db,ref)
        if not manageable(db,event,uid):abort(403)
        if request.method=='POST':
            response=write(True)
            if response is not None:return response
            revision=request.form.get('revision',type=int)
            if revision is None:abort(409)
            with db:
                db.execute('BEGIN IMMEDIATE')
                if request.form.get('action')=='cancel':
                    result=db.execute('UPDATE calendar_events SET canceled=1,revision=revision+1,updated_at=? WHERE id=? AND revision=?',(int(time.time()),ref,revision))
                    if result.rowcount!=1:raise pages.PageError('Event changed.',409)
                    audit(db,ref,uid,'cancel')
                else:edit(db,uid,ref,revision,request.form)
            return redirect(url_for('events.detail',ref=ref))
        return render_template('event_form.html',event=event,circles=[],page_choices=[])
    @bp.post('/events/<ref>/respond')
    def response(ref):
        uid=actor();write()
        with core.get_db():respond(core.get_db(),uid,ref,request.form.get('response'))
        return redirect(url_for('events.detail',ref=ref))
    @bp.get('/events/<ref>/calendar.ics')
    def download(ref):
        uid=actor();event=get(core.get_db(),ref)
        if not visible(core.get_db(),event,uid):abort(404)
        return Response(ics(event),mimetype='text/calendar',headers={'Content-Disposition':'attachment; filename="neonrest-event.ics"'})
    @bp.route('/events/<ref>/report',methods=['GET','POST'])
    def report_event(ref):
        uid=actor();db=core.get_db();event=get(db,ref)
        if not visible(db,event,uid):abort(404)
        if request.method=='POST':
            write();limit=app.extensions['community_auth_helpers']['limited']('event-report',15)
            if limit is not None:return limit
            reason=request.form.get('reason','').strip()
            if not 1<=len(reason)<=1000:abort(400)
            with db:db.execute('''INSERT OR IGNORE INTO calendar_reports(event_id,reporter_id,reason,snapshot,created_at) VALUES (?,?,?,?,?)''',(ref,uid,reason,json.dumps(dict(event)),int(time.time())))
            flash('Event report sent privately to staff.','success');return redirect(url_for('events.calendar'))
        return render_template('event_report.html',event=event)
    @bp.route('/manage/events/reports',methods=['GET','POST'])
    def review():
        uid=core.require_staff_permission('review_reports');db=core.get_db()
        safety=db.execute('SELECT totp_secret FROM account_safety WHERE user_id=?',(uid,)).fetchone()
        if not safety or not safety['totp_secret']:return redirect(url_for('community_security'))
        if not app.extensions['community_auth_helpers']['fresh']():return redirect(url_for('community_reauth',next=request.path))
        if request.method=='POST':
            core.require_staff_permission('moderate_posts');write();rid=request.form.get('report_id',type=int);decision=request.form.get('decision');reason=request.form.get('reason','').strip()
            row=db.execute('SELECT * FROM calendar_reports WHERE id=?',(rid,)).fetchone()
            if not row or decision not in ('hide','restore','dismiss') or not 1<=len(reason)<=1000:abort(400)
            with db:
                if decision!='dismiss':db.execute('UPDATE calendar_events SET staff_hidden=?,revision=revision+1 WHERE id=?',(int(decision=='hide'),row['event_id']))
                db.execute("UPDATE calendar_reports SET status='closed',reviewed_by=?,decision=?,decision_reason=?,reviewed_at=? WHERE id=?",(uid,decision,reason,int(time.time()),rid));audit(db,row['event_id'],uid,'staff:'+decision)
            return redirect(url_for('events.review'))
        return render_template('event_reports.html',reports=db.execute('SELECT * FROM calendar_reports ORDER BY id DESC LIMIT 100').fetchall())
    @bp.after_request
    def private(response):response.headers['Cache-Control']='private, no-store';return response
    app.register_blueprint(bp)
