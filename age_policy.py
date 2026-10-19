"""Sandbox age boundaries. Parent approval is a reviewed consent record, not identity proof."""
from .request_cache import request_lookup
from datetime import date, datetime
from neonrest import age_clock
from flask import request, session, redirect, url_for, abort, render_template_string, flash, g
import hmac
from werkzeug.security import generate_password_hash

def parse_dob(value):
    for fmt in ('%Y-%m-%d','%m/%d/%Y'):
        try:
            d=datetime.strptime((value or '').strip(),fmt).date()
            if d>date.today(): return None
            return d
        except ValueError: pass
    return None

def age_of(value, today=None):
    d=parse_dob(value); t=today or date.today()
    return None if not d else t.year-d.year-((t.month,t.day)<(d.month,d.day))

@request_lookup
def age(db, uid):
    row=db.execute('SELECT dob FROM users WHERE id=?',(uid,)).fetchone() if uid else None
    return age_of(row['dob'],age_clock.date_for(db,uid)) if row else None

@request_lookup
def approved_parent(db, parent, child):
    child_age=age(db,child);parent_age=age(db,parent)
    return bool(parent and child and child_age is not None and 10<=child_age<18 and parent_age is not None and parent_age>=18 and db.execute("SELECT 1 FROM family_links WHERE parent_id=? AND child_id=? AND status='approved'",(parent,child)).fetchone())

@request_lookup
def ready(db, uid):
    a=age(db,uid)
    return a is not None and a>=10 and (a>=13 or bool(db.execute("SELECT 1 FROM family_links WHERE child_id=? AND status='approved'",(uid,)).fetchone()))

@request_lookup
def band(db,a,b):
    aa,bb=age(db,a),age(db,b)
    return aa is not None and bb is not None and min(aa,bb)>=10 and (min(aa,bb)>=18 or abs(aa-bb)<=3)

@request_lookup
def family(db,a,b):
    return approved_parent(db,a,b) or approved_parent(db,b,a)

@request_lookup
def can_read(db,owner,viewer, protected=False, profile=False):
    from neonrest import welcome
    if welcome.staff(db,viewer): return True
    oa=age(db,owner)
    if viewer==owner: return True
    if not ready(db,owner): return False
    # Public post audiences do not exempt a minor reader from the age band.
    va=age(db,viewer)
    # Staff identity is discoverable for safety; personal content is not exempt.
    if profile and viewer and ready(db,viewer) and welcome.staff(db,owner): return True
    if oa>=18 and not protected and (not viewer or (va is not None and va>=18)): return True
    return bool(viewer and ready(db,viewer) and (family(db,owner,viewer) or (age(db,viewer) is not None and abs(oa-age(db,viewer))<=3)))

@request_lookup
def limited_staff_profile(db,owner,viewer):
    from neonrest import welcome
    va,oa=age(db,viewer),age(db,owner)
    return bool(viewer and owner!=viewer and va is not None and va<18 and oa is not None and abs(oa-va)>3 and welcome.staff(db,owner) and not welcome.staff(db,viewer) and not family(db,owner,viewer))

@request_lookup
def comment_read(db,cid,viewer):
    row=db.execute('SELECT user_id FROM comments WHERE id=?',(cid,)).fetchone()
    return bool(row and can_read(db,row['user_id'],viewer,protected=bool(db.execute('SELECT 1 FROM protected_age_comments WHERE comment_id=?',(cid,)).fetchone())))

@request_lookup
def contact(db,a,b, invitation=False):
    if not ready(db,a) or not ready(db,b): return False
    if family(db,a,b): return True
    if not band(db,a,b): return False
    for child,peer in ((a,b),(b,a)):
        if age(db,child)<13 and not db.execute('SELECT 1 FROM parent_contacts pc JOIN family_links fl ON fl.child_id=pc.child_id AND fl.parent_id=pc.parent_id WHERE pc.child_id=? AND pc.peer_id=? AND fl.status=\'approved\'',(child,peer)).fetchone(): return False
    if min(age(db,a),age(db,b))<18 and not invitation:
        return bool(db.execute("SELECT 1 FROM friend_requests WHERE status='accepted' AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))",(a,b,b,a)).fetchone())
    return True

def init(db):
    if 'actual_name' not in {r['name'] for r in db.execute('PRAGMA table_info(users)')}: db.execute("ALTER TABLE users ADD COLUMN actual_name TEXT DEFAULT ''")
    db.execute("CREATE TABLE IF NOT EXISTS staff_announcements(post_id INTEGER PRIMARY KEY)")
    db.executescript('''CREATE TABLE IF NOT EXISTS family_links(parent_id INTEGER NOT NULL,child_id INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pending',method TEXT,reference TEXT,reviewed_by INTEGER,reviewed_at TEXT,PRIMARY KEY(parent_id,child_id));
CREATE TABLE IF NOT EXISTS parent_contacts(parent_id INTEGER NOT NULL,child_id INTEGER NOT NULL,peer_id INTEGER NOT NULL,PRIMARY KEY(parent_id,child_id,peer_id));
CREATE TABLE IF NOT EXISTS protected_age_posts(post_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS protected_age_comments(comment_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS age_policy_events(id INTEGER PRIMARY KEY,actor_id INTEGER,child_id INTEGER,action TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TRIGGER IF NOT EXISTS immutable_user_dob BEFORE UPDATE OF dob ON users WHEN OLD.dob IS NOT NULL AND trim(OLD.dob)<>'' AND NEW.dob IS NOT OLD.dob BEGIN SELECT RAISE(ABORT,'Date of birth is locked'); END;''')
    # Reserve the write slot before reading: concurrent startup/worker writes
    # must not deadlock a deferred read-to-write transaction upgrade.
    db.execute('BEGIN IMMEDIATE')
    for row in db.execute('SELECT p.id,p.created_at,u.dob FROM posts p JOIN users u ON u.id=p.user_id'):
        a=age_of(row['dob'],parse_dob(str(row['created_at'] or '')[:10]))
        if a is not None and a<18: db.execute('INSERT OR IGNORE INTO protected_age_posts VALUES (?)',(row['id'],))
    for row in db.execute('SELECT c.id,c.created_at,u.dob FROM comments c JOIN users u ON u.id=c.user_id'):
        a=age_of(row['dob'],parse_dob(str(row['created_at'] or '')[:10]))
        if a is not None and a<18: db.execute('INSERT OR IGNORE INTO protected_age_comments VALUES (?)',(row['id'],))
    db.commit()

PAGE='''{% extends 'base.html' %}{% block content %}<div class="community-page">{% include 'partials/account_navigation.html' %}<h1>{{ heading }}</h1><p>{{ message }}</p>{% if heading == 'Age and safety' %}<section><h2>Birthday timezone</h2><p>Age permissions change at midnight in your confirmed local timezone. Your profile's display timezone cannot change this clock.</p>{% if birthday_clock and birthday_clock.confirmed %}<p>{{ birthday_clock.zone }}</p>{% else %}<p>Your birthday clock currently uses UTC until you confirm your local timezone. This does not change your stored date of birth.</p><form method="post" action="{{ url_for('age_clock_setup') }}"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><label>Local timezone<input name="zone" id="birthday-zone" placeholder="America/Los_Angeles" required maxlength="80"></label><button>Confirm local timezone</button></form><script>document.getElementById('birthday-zone').value=Intl.DateTimeFormat().resolvedOptions().timeZone;</script>{% endif %}</section><section><h2>Incorrect date of birth?</h2><p>Your date of birth cannot be changed in settings. <a href="mailto:ToS@neonrest.com?subject=Date%20of%20birth%20correction%20request">Request a correction</a> and include your handle and a brief explanation. Do not email identity documents or your full date of birth; we will arrange an appropriate verification process if needed. For children, the linked parent or guardian should contact us.</p><p>A request does not change your stored date or age protections. Corrections require robust verification; that process is not currently available, so we cannot promise a correction.</p><form method="post" action="{{ url_for('family_data_requests') }}"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="child_id" value="{{ session.user_id }}"><input type="hidden" name="kind" value="dob-correction"><label>Describe the error without ID documents or your full DOB<input name="notes" maxlength="500" required></label><button>Request DOB review</button></form><p><a href="{{ url_for('family_data_requests') }}">Track your age review requests</a></p></section>{% endif %}{% if setup %}<form method="post"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><label>Date of birth <input name="dob" type="date" required></label><p>This date cannot be changed. Accounts under 13 need verified parental consent before social access.</p><button>Save date of birth</button></form>{% endif %}{% if parent %}{% if family_review_allowed %}<p><a class="button" href="{{ url_for('family_review') }}">Review parental consent</a></p>{% endif %}<h2>Link an existing child account</h2><form method="post"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="action" value="link-existing"><label>Existing child handle <input name="handle" required></label><button>Request reviewed parent link</button></form><h2>Enrollment</h2><p>Public signup is 13+. New enrollment for children under 13 is not available. Existing family controls remain available.</p>{% for item in links %}<section><h3>{{ item.handle }} — {{ item.status }}</h3>{% set child_clock=family_birthday_clocks.get(item.child_id) %}{% if item.status=='approved' and (not child_clock or not child_clock.confirmed) %}<h4>Child's birthday timezone</h4><form method="post" action="{{ url_for('age_clock_setup') }}"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="child_id" value="{{ item.child_id }}"><label>Child's local timezone<input name="zone" maxlength="80" placeholder="America/Los_Angeles" required></label><button>Confirm child's timezone</button></form>{% endif %}<h4>Review or deletion of account information</h4><form method="post" action="{{ url_for('family_data_requests') }}"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="child_id" value="{{ item.child_id }}"><label>Request<select name="kind"><option value="data-review">Review account information</option><option value="delete">Request account deletion</option></select></label><label>Notes (no ID documents or full DOB)<input name="notes" maxlength="500"></label><button>Send for staff review</button></form><p><a href="{{ url_for('family_data_requests') }}">Track your requests</a></p><h4>Signed consent letter</h4><p>Upload your signed parental consent letter as a PDF, PNG or JPEG (maximum 5 MB). Include your handle, your child’s handle, your name, signature and date. Staff will review it and may request further verification. Uploading does not activate an account. Please do not upload identity documents here.</p>{% for doc in family_documents.get((item.parent_id,item.child_id),[]) %}<p><a class="button" href="{{ url_for('family_consent_document',document_id=doc.id) }}">Download submitted letter #{{ doc.id }}</a> · {{ doc.created_at }}</p>{% endfor %}{% if item.status in ['pending','approved'] %}<form method="post" enctype="multipart/form-data" action="{{ url_for('family_consent_submit') }}"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="child_id" value="{{ item.child_id }}"><label>Signed letter <input type="file" name="letter" accept="application/pdf,image/png,image/jpeg" required></label><button>Submit for review</button></form>{% endif %}<p>PRIVO parental verification is planned and is not yet connected. Submitted letters remain subject to staff verification.</p>{% if item.status=='approved' %}<form method="post"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="child_id" value="{{ item.child_id }}"><label>Peer handle <input name="peer" required></label><button name="action" value="allow">Allow contact</button><button name="action" value="remove">Remove contact permission</button><button name="action" value="revoke">Revoke parental consent</button></form>{% endif %}</section>{% endfor %}{% endif %}{% if staff %}<p><a class="button" href="{{ url_for('family_data_review') }}">Review family and age data requests</a></p><p>Approve only after completing and documenting a valid parental-consent verification process. A linked account is not proof. Record a reference, not an ID document or secret.</p>{% for item in links %}<section><h3>Parent {{ item.parent_id }} → child {{ item.child_id }} — {{ item.status }}</h3>{% for doc in family_documents.get((item.parent_id,item.child_id),[]) %}<p><a class="button" href="{{ url_for('family_consent_document',document_id=doc.id) }}">Review signed letter #{{ doc.id }}</a> · {{ doc.created_at }}</p>{% else %}<p>No signed letter submitted.</p>{% endfor %}<form method="post"><input type="hidden" name="theme_csrf_token" value="{{ token }}"><input type="hidden" name="parent_id" value="{{ item.parent_id }}"><input type="hidden" name="child_id" value="{{ item.child_id }}"><label>Verified method <select name="method"><option value="signed-consent-form">Signed consent form</option><option value="trained-personnel-phone">Trained-personnel phone verification</option><option value="approved-provider">Approved verification provider</option></select></label><label>Verification record reference <input name="reference" required maxlength="200"></label><button name="action" value="approve">Record verified consent</button><button name="action" value="revoke">Revoke</button></form></section>{% endfor %}{% endif %}</div>{% endblock %}'''

def register(app,core, fresh):
    with app.app_context(): init(core.get_db())
    from neonrest import family_consent
    import sys
    family_consent.register(app,core,sys.modules[__name__],fresh)
    def csrf():
        if not session.get('theme_csrf_token') or not hmac.compare_digest(session['theme_csrf_token'],request.form.get('theme_csrf_token','')): abort(400)
    def show(heading,message='',**kw): return render_template_string(PAGE,heading=heading,message=message,token=core.theme_csrf_token(),**kw)
    def logged():
        if not session.get('user_id'): abort(401)
        return session['user_id']
    def event(db,uid,child,action): db.execute('INSERT INTO age_policy_events(actor_id,child_id,action) VALUES (?,?,?)',(uid,child,action))
    @app.route('/account/age',methods=['GET','POST'])
    def age_setup():
        uid=logged(); db=core.get_db(); row=db.execute('SELECT dob FROM users WHERE id=?',(uid,)).fetchone()
        if request.method=='POST':
            csrf();d=parse_dob(request.form.get('dob')); a=age_of(d.isoformat(),age_clock.date_for(db,uid)) if d else None
            if row['dob'] or a is None or a<10: abort(400,description='A valid date for age 10 or older is required; an existing date cannot be changed.')
            db.execute('UPDATE users SET dob=? WHERE id=?',(d.isoformat(),uid));event(db,uid,uid,'dob-initialized');db.commit()
            return redirect(url_for('age_setup'))
        return show('Age and safety','Date of birth is locked. Under-13 accounts require verified parent approval; accounts with a missing date need age setup.',setup=not row['dob'])
    @app.route('/account/family',methods=['GET','POST'])
    def family_settings():
        uid=logged();db=core.get_db()
        if age(db,uid) is None or age(db,uid)<18: abort(403)
        if request.method=='POST':
            csrf()
            if not fresh(): return redirect(url_for('community_reauth',next='/account/family'))
            action=request.form.get('action')
            if action=='link-existing':
                row=db.execute("SELECT id FROM users WHERE lower(ltrim(handle,'@'))=lower(?)",(request.form.get('handle','').strip().lstrip('@'),)).fetchone()
                if not row or row['id']==uid: abort(400)
                a=age(db,row['id'])
                if a is not None and not 10<=a<18: abort(400)
                db.execute('INSERT OR IGNORE INTO family_links(parent_id,child_id) VALUES (?,?)',(uid,row['id']));event(db,uid,row['id'],'parent-link-pending');db.commit()
            elif action=='enroll':
                abort(403,description='New enrollment for children under 13 is not available. Public signup is 13+.')
                d=parse_dob(request.form.get('dob')); a=age_of(d.isoformat()) if d else None
                handle=request.form.get('handle','').strip().lstrip('@');email=request.form.get('email','').strip();password=request.form.get('password','')
                import re
                if a is None or not 10<=a<13 or not re.fullmatch(r'[A-Za-z0-9_.+\-]{1,40}',handle) or '@' not in email or not 12<=len(password)<=128: abort(400)
                try:
                    cur=db.execute('INSERT INTO users(email,handle,password_hash,dob,verified,created_at) VALUES (?,?,?,?,0,CURRENT_TIMESTAMP)',(email,'@'+handle,generate_password_hash(password),d.isoformat()))
                except Exception: db.rollback();abort(400,description='Handle or contact email unavailable.')
                child=cur.lastrowid;__import__('neonrest.welcome',fromlist=['add_welcome_friend']).add_welcome_friend(db,child);db.execute('INSERT INTO family_links(parent_id,child_id) VALUES (?,?)',(uid,child));event(db,uid,child,'parent-enrollment-pending');db.commit()
            else:
                child=request.form.get('child_id',type=int)
                if not approved_parent(db,uid,child): abort(403)
                if action=='revoke':
                    db.execute("UPDATE family_links SET status='revoked',reviewed_at=CURRENT_TIMESTAMP WHERE parent_id=? AND child_id=?",(uid,child))
                    db.execute('DELETE FROM parent_contacts WHERE parent_id=? AND child_id=?',(uid,child))
                    if age(db,child)<13 and not db.execute("SELECT 1 FROM family_links WHERE child_id=? AND status='approved'",(child,)).fetchone():db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(child,))
                else:
                    peer=db.execute("SELECT id FROM users WHERE lower(ltrim(handle,'@'))=lower(?)",(request.form.get('peer','').strip().lstrip('@'),)).fetchone()
                    if not peer or not band(db,child,peer['id']): abort(400)
                    if action=='allow': db.execute('INSERT OR IGNORE INTO parent_contacts VALUES (?,?,?)',(uid,child,peer['id']))
                    elif action=='remove': db.execute('DELETE FROM parent_contacts WHERE parent_id=? AND child_id=? AND peer_id=?',(uid,child,peer['id']))
                    else: abort(400)
                event(db,uid,child,'parent-contact:'+action);db.commit()
            return redirect(url_for('family_settings'))
        return show('Family settings',parent=True,links=db.execute('SELECT fl.*,u.handle FROM family_links fl JOIN users u ON u.id=fl.child_id WHERE parent_id=?',(uid,)).fetchall())
    @app.route('/manage/family',methods=['GET','POST'])
    def family_review():
        uid=core.require_staff_permission('manage_roles');db=core.get_db()
        if request.method=='POST':
            csrf()
            if not fresh(): return redirect(url_for('community_reauth',next='/manage/family'))
            parent=request.form.get('parent_id',type=int);child=request.form.get('child_id',type=int);action=request.form.get('action');method=request.form.get('method');reference=request.form.get('reference','').strip()
            if not db.execute('SELECT 1 FROM family_links WHERE parent_id=? AND child_id=?',(parent,child)).fetchone() or age(db,parent) is None or age(db,parent)<18 or age(db,child) is None or not 10<=age(db,child)<18: abort(400)
            if action=='approve':
                if method not in ('signed-consent-form','trained-personnel-phone','approved-provider') or not reference or len(reference)>200: abort(400)
                if method=='signed-consent-form':
                    try: document_id=int(reference.removeprefix('letter:'))
                    except ValueError: abort(400,description='Use the submitted letter number as the verification reference.')
                    if not db.execute('SELECT 1 FROM family_consent_documents WHERE id=? AND parent_id=? AND child_id=?',(document_id,parent,child)).fetchone(): abort(400,description='A signed letter submitted by this parent for this child is required.')
                    reference='letter:'+str(document_id)
                db.execute("UPDATE family_links SET status='approved',method=?,reference=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE parent_id=? AND child_id=?",(method,reference,uid,parent,child));db.execute('UPDATE users SET verified=1 WHERE id=?',(child,))
            elif action=='revoke':
                db.execute("UPDATE family_links SET status='revoked',reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE parent_id=? AND child_id=?",(uid,parent,child))
                db.execute('DELETE FROM parent_contacts WHERE parent_id=? AND child_id=?',(parent,child))
                if age(db,child)<13 and not db.execute("SELECT 1 FROM family_links WHERE child_id=? AND status='approved'",(child,)).fetchone():db.execute('UPDATE active_sessions SET revoked=1 WHERE user_id=?',(child,))
            else: abort(400)
            event(db,uid,child,'consent:'+action);db.commit();return redirect(url_for('family_review'))
        return show('Parental consent review',staff=True,links=db.execute('SELECT * FROM family_links').fetchall())
    def guard():
        uid=session.get('user_id');db=core.get_db();ep=request.endpoint or ''
        if ep=='static':
            import re
            import posixpath
            name=posixpath.normpath((request.view_args or {}).get('filename',''))
            match=re.fullmatch(r'uploads/avatars/user_(\d+)_avatar\.png',name)
            from neonrest.community_features import member_visible
            if match and not member_visible(db,int(match.group(1)),uid): abort(404)
            if name.startswith('uploads/'):
                from urllib.parse import urlsplit
                for row in db.execute('SELECT id,avatar_path FROM users WHERE avatar_path IS NOT NULL'):
                    path=posixpath.normpath(urlsplit(row['avatar_path']).path)
                    if path.endswith('/static/'+name) and not member_visible(db,row['id'],uid): abort(404)
        if request.method=='POST' and ep=='signup':
            d=parse_dob(request.form.get('dob'));g.signup_timezone=age_clock.valid_zone(request.form.get('timezone','UTC'))
            if not g.signup_timezone:g.statistics_signup_outcome='timezone';abort(400,description='Invalid local timezone.')
            a=age_of(d.isoformat(),age_clock.local_date(g.signup_timezone)) if d else None
            if a is None or a<10: g.statistics_signup_outcome='eligibility';abort(400,description='Signup requires age 13 or older. New enrollment for children under 13 is not available.')
            if a<13: g.statistics_signup_outcome='eligibility';abort(403,description='Signup is for ages 13 and older. New enrollment for children under 13 is not available.')
            g.signup_dob=d.isoformat()
        if request.method=='POST' and uid and ep not in ('age_setup','family_settings') and 'dob' in request.form: abort(400,description='Date of birth cannot be changed.')
        allowed={'static','login','signup','verify_email','community_login_factor','community_reauth','community_security','account_email','account_email_confirm','logout','age_setup','age_clock_setup','community_data','community_export','community_reactivate','password_reset_request','password_reset','family_settings','family_review'}
        if uid and not ready(db,uid) and ep not in allowed and not ep.startswith(('manage_','family_')):
            return redirect(url_for('age_setup'))
        if request.method=='POST' and uid:
            if ep in ('friends.send_request','friends.accept_friend','friends.follow','create_post'):
                target=(request.view_args or {}).get('user_id')
                if ep=='create_post': target=request.form.get('target_user_id',uid,type=int)
                if target and target!=uid and not contact(db,uid,target,invitation=ep in ('friends.send_request','friends.accept_friend')): abort(403,description='Age, mutual acceptance or parent contact approval does not permit this action.')
            if ep in ('create_comment','react_to_post'):
                try: pid=core.identifiers.resolve(db,'post',request.form.get('post_id')) if ep=='create_comment' else request.view_args['post_id']
                except (ValueError,TypeError): abort(400)
                row=db.execute('SELECT user_id FROM posts WHERE id=?',(pid,)).fetchone()
                if row and row['user_id']!=uid and not contact(db,uid,row['user_id']): abort(403)
                if ep=='create_comment' and request.form.get('parent_comment_id'):
                    try: parent=core.decode_prefixed_id(request.form['parent_comment_id'])
                    except Exception: abort(400)
                    if not comment_read(db,parent,uid): abort(404)
                    row=db.execute('SELECT user_id FROM comments WHERE id=?',(parent,)).fetchone()
                    if row and row['user_id']!=uid and not contact(db,uid,row['user_id']): abort(403)
    app.before_request(guard)
    @app.after_request
    def avoid_shared_cache(response):
        if session.get('user_id') or (request.endpoint=='static' and 'uploads/avatars/' in (request.view_args or {}).get('filename','')):
            response.headers['Cache-Control']='private, no-store'
        return response
    @app.context_processor
    def age_links(): return {'age_policy_age':age(core.get_db(),session.get('user_id'))}
