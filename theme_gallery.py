"""Free, reviewed, immutable theme snapshots. Remixes are independent copies."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for, make_response
from . import age_policy as ages
from werkzeug.exceptions import HTTPException

AGREEMENT = 'theme-sharing-mit-v1-2026-10-22'
LIMITS = {'custom_css': 100000, 'bg_color': 7, 'text_color': 7, 'glow_color': 7,
          'background_layers': 4000, 'blend_mode': 200, 'font_stack': 500}
COLORS = {'bg_color', 'text_color', 'glow_color'}
AGREEMENT_TEXT = ('I am submitting this style and public credit for the free public theme gallery. '
    'I have permission to share this code under MIT and have preserved existing notices. '
    'MIT permits reuse, modification and commercial redistribution with its notices. '
    'External fonts, images and music retain their own licenses and are not relicensed here. '
    'This does not change the Neonrest application license. Gallery withdrawal stops new '
    'downloads here and does not revoke licenses already granted.')
MIT = '''Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.'''


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS theme_gallery_entries(
      id INTEGER PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, owner_id INTEGER NOT NULL,
      title TEXT NOT NULL, description TEXT NOT NULL, credit TEXT NOT NULL,
      mode TEXT NOT NULL CHECK(mode IN ('day','night')), scope_slug TEXT NOT NULL,
      style_json TEXT NOT NULL, content_sha256 TEXT NOT NULL,
      credits_json TEXT NOT NULL, parent_id INTEGER REFERENCES theme_gallery_entries(id),
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','withdrawn')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS idx_theme_gallery_status_id ON theme_gallery_entries(status,id DESC);
    CREATE INDEX IF NOT EXISTS idx_theme_gallery_owner_id ON theme_gallery_entries(owner_id,id DESC);
    CREATE TABLE IF NOT EXISTS theme_gallery_agreements(
      entry_id INTEGER PRIMARY KEY REFERENCES theme_gallery_entries(id), actor_id INTEGER NOT NULL,
      agreement_version TEXT NOT NULL, agreement_text TEXT NOT NULL, content_sha256 TEXT NOT NULL,
      accepted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS theme_gallery_events(
      id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES theme_gallery_entries(id),
      actor_id INTEGER NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS idx_theme_gallery_events_entry ON theme_gallery_events(entry_id,id DESC);
    ''')


def validate_file(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 131072:
        abort(400, description='Theme JSON must be 128 KiB or smaller.')
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        abort(400, description='Invalid theme JSON.')
    if not isinstance(data, dict) or set(data) != {'format', 'version', 'mode', 'style'} or data.get('format') != 'neonrest-theme' or type(data.get('version')) is not int or data['version'] != 1 or data.get('mode') not in ('day', 'night') or not isinstance(data.get('style'), dict):
        abort(400, description='Use a Neonrest theme version 1 export.')
    # Gallery snapshots must be complete; partial imports remain an editor feature.
    if set(data['style']) != set(LIMITS):
        abort(400, description='Export a complete style from Theme Studio.')
    for key, value in data['style'].items():
        if value is not None and (not isinstance(value, str) or len(value) > LIMITS[key]):
            abort(400, description='Invalid or oversized theme field: ' + key)
        if key in COLORS and value is not None and not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', value):
            abort(400, description='Theme colors must be hex values or null.')
        if isinstance(value, str) and re.search(r'<\/?(?:script|style|iframe|object|embed)\b', value, re.I):
            abort(400, description='HTML is not supported in theme fields.')
    return data


def text(value, maximum, required=True):
    value = (value or '').strip()
    if (required and not value) or len(value) > maximum or any(ord(c)<32 and c not in '\n\t' for c in value):
        abort(400, description='Check the required text and length limits.')
    return value


def slug(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', value or ''):
        abort(400, description='Use a Vibe CSS slug with lowercase letters, numbers, hyphens or underscores.')
    return value


def downloadable(entry, target=None):
    data = json.loads(entry['style_json'])
    credits = json.loads(entry['credits_json'])
    notice = '/*! Neonrest theme — MIT License\n' + '\n'.join(credits) + '\n\n' + MIT + '\nExternal fonts, images and music retain their own licenses.\n*/\n'
    css = data['style'].get('custom_css') or ''
    if target and target != entry['scope_slug']:
        # Only rewrite the exact documented Vibe class; never arbitrary substrings.
        css = re.sub(r'(?<![\w-])vibe-' + re.escape(entry['scope_slug']) + r'--' + entry['mode'] + r'(?![\w-])',
                     lambda _: 'vibe-' + target + '--' + entry['mode'], css)
    data['style']['custom_css'] = notice + css
    return data


def export_user(db, uid):
    entries = []
    for row in db.execute('SELECT * FROM theme_gallery_entries WHERE owner_id=? ORDER BY id', (uid,)):
        item = {key: row[key] for key in ('public_id','title','description','credit','mode','scope_slug','content_sha256','status','created_at')}
        item['style'] = json.loads(row['style_json'])
        item['credits'] = json.loads(row['credits_json'])
        item['acceptance'] = [dict(r) for r in db.execute('SELECT agreement_version,agreement_text,content_sha256,accepted_at FROM theme_gallery_agreements WHERE entry_id=? AND actor_id=?', (row['id'],uid))]
        item['review_history'] = [dict(r) for r in db.execute('SELECT action,reason,created_at FROM theme_gallery_events WHERE entry_id=? ORDER BY id', (row['id'],))]
        entries.append(item)
    return {'submissions': entries}


def register(app, core):
    with app.app_context():
        initialize(core.get_db())
        core.get_db().commit()

    def account():
        db = core.get_db(); uid = session.get('user_id')
        user = db.execute('SELECT id,verified FROM users WHERE id=?', (uid,)).fetchone() if type(uid) is int else None
        if not user or not user['verified'] or not ages.ready(db, uid):
            abort(403)
        if db.execute('SELECT 1 FROM user_moderation WHERE user_id=? AND (banned=1 OR posting_restricted=1 OR interaction_restricted=1)', (uid,)).fetchone() or db.execute('SELECT 1 FROM account_safety WHERE user_id=? AND inactive=1', (uid,)).fetchone() or db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1', (uid,)).fetchone():
            abort(403)
        return uid

    def csrf():
        expected=session.get('theme_csrf_token', '')
        submitted=request.form.get('theme_csrf_token', '')
        if not expected or not hmac.compare_digest(submitted.encode('utf-8'), expected.encode('utf-8')):
            abort(400)

    def entry(public_id, owner=False):
        row = core.get_db().execute('SELECT * FROM theme_gallery_entries WHERE public_id=?', (public_id,)).fetchone()
        if not row or (row['status'] != 'approved' and not (owner and row['owner_id']==session.get('user_id')) and not (owner and core.has_staff_permission(core.get_db(), session.get('user_id'), 'approve_vibes'))):
            abort(404)
        return row

    @app.after_request
    def gallery_private_responses(response):
        if request.endpoint and request.endpoint.startswith('theme_gallery'):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def before_id():
        try:
            value=int(request.args.get('before',str(2**63-1)))
            if not 0<value<=2**63-1: raise ValueError()
            return value
        except ValueError: abort(400)

    @app.route('/themes/gallery')
    def theme_gallery():
        try:
            before = int(request.args.get('before', str(2**63-1)))
            if not 0<before<=2**63-1: raise ValueError()
        except ValueError: abort(400)
        rows = list(core.get_db().execute("SELECT public_id,title,description,credit,mode,id FROM theme_gallery_entries WHERE status='approved' AND id<? ORDER BY id DESC LIMIT 21", (before,)))
        return render_template('theme_gallery.html', entries=rows[:20], next_before=rows[19]['id'] if len(rows)>20 else None, may_review=core.has_staff_permission(core.get_db(),session.get('user_id'),'approve_vibes'))

    @app.route('/themes/gallery/mine')
    def theme_gallery_mine():
        uid=account()
        rows=core.get_db().execute("SELECT id,public_id,title,status,mode,(SELECT reason FROM theme_gallery_events ev WHERE ev.entry_id=theme_gallery_entries.id AND ev.action IN ('approved','rejected','withdrawn') ORDER BY ev.id DESC LIMIT 1) AS review_reason FROM theme_gallery_entries WHERE owner_id=? AND id<? ORDER BY id DESC LIMIT 21", (uid,before_id())).fetchall()
        return render_template('theme_gallery_mine.html', entries=rows[:20], next_before=rows[19]['id'] if len(rows)>20 else None, token=core.theme_csrf_token())

    def queue_snapshot(uid,db,parent):
        csrf()
        if request.form.get('agreement_version')!=AGREEMENT or request.form.get('accept_license')!='yes':
            abort(400, description='Review and explicitly accept the theme-sharing agreement.')
        data=validate_file(request.form.get('theme_json',''))
        title=text(request.form.get('title'),80);description=text(request.form.get('description'),1000,False)
        credit=text(request.form.get('credit'),120)
        if any(c in credit for c in '<>') or '*/' in credit or '\n' in credit or '\t' in credit:
            abort(400, description='Use a plain single-line public credit name.')
        scope=slug(request.form.get('scope_slug',''))
        if parent and data['mode']!=parent['mode']: abort(400)
        credits=json.loads(parent['credits_json']) if parent else []
        if len(credits)>=32: abort(400, description='This remix chain has reached the current 32-credit limit.')
        credits=list(dict.fromkeys(credits+['Copyright (c) '+str(datetime.now(timezone.utc).year)+' '+credit]))
        encoded=json.dumps(data,sort_keys=True,ensure_ascii=True,separators=(',',':'))
        digest=hashlib.sha256(json.dumps([data,title,description,credit,scope,credits,parent['public_id'] if parent else None],sort_keys=True).encode()).hexdigest()
        packaged=downloadable({'style_json':encoded,'credits_json':json.dumps(credits),'scope_slug':scope,'mode':data['mode']})
        validate_file(json.dumps(packaged,ensure_ascii=True,indent=2)+'\n')
        db.execute('BEGIN IMMEDIATE')
        if parent and not db.execute("SELECT 1 FROM theme_gallery_entries WHERE id=? AND status='approved'", (parent['id'],)).fetchone(): abort(409)
        if db.execute("SELECT COUNT(*) FROM theme_gallery_entries WHERE owner_id=? AND (status='pending' OR created_at>=datetime('now','-1 day'))", (uid,)).fetchone()[0]>=5:
            abort(429, description='Five pending or recent submissions are already recorded. Try again after older entries are reviewed and the daily limit clears.')
        public_id=secrets.token_urlsafe(18)
        cursor=db.execute('INSERT INTO theme_gallery_entries(public_id,owner_id,title,description,credit,mode,scope_slug,style_json,content_sha256,credits_json,parent_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (public_id,uid,title,description,credit,data['mode'],scope,encoded,digest,json.dumps(credits),parent['id'] if parent else None))
        db.execute('INSERT INTO theme_gallery_agreements(entry_id,actor_id,agreement_version,agreement_text,content_sha256) VALUES(?,?,?,?,?)', (cursor.lastrowid,uid,AGREEMENT,AGREEMENT_TEXT+'\n\n'+MIT,digest))
        db.execute('INSERT INTO theme_gallery_events(entry_id,actor_id,action,reason) VALUES(?,?,?,?)', (cursor.lastrowid,uid,'submitted','Explicit MIT sharing acceptance'))
        db.commit()
        return redirect(url_for('theme_gallery_mine'))


    @app.route('/themes/gallery/submit', methods=['GET','POST'])
    def theme_gallery_submit():
        uid=account();db=core.get_db()
        parent=None
        parent_ref=request.values.get('parent','')
        if parent_ref: parent=entry(parent_ref)
        if request.method=='POST':
            try:
                return queue_snapshot(uid,db,parent)
            except HTTPException as error:
                if error.code not in (400,409,429): raise
                db.rollback()
                return render_template('theme_gallery_submit.html', parent=parent,
                    agreement=AGREEMENT, agreement_text=AGREEMENT_TEXT, license_text=MIT,
                    token=core.theme_csrf_token(), values=request.form, error=error.description), error.code
        return render_template('theme_gallery_submit.html', parent=parent, agreement=AGREEMENT, agreement_text=AGREEMENT_TEXT, license_text=MIT, token=core.theme_csrf_token(), values={})

    @app.route('/themes/gallery/<public_id>')
    def theme_gallery_detail(public_id):
        row=entry(public_id)
        return render_template('theme_gallery_detail.html', item=row, credits=json.loads(row['credits_json']), license_text=MIT, preview={'slug':row['scope_slug'],'mode':row['mode'],'style':json.loads(row['style_json'])['style']},
            parent=core.get_db().execute("SELECT public_id,title FROM theme_gallery_entries WHERE id=? AND status='approved'", (row['parent_id'],)).fetchone())

    @app.route('/themes/gallery/<public_id>/download')
    def theme_gallery_download(public_id):
        row=entry(public_id)
        target=request.args.get('target')
        if target: target=slug(target)
        payload=downloadable(row,target)
        if len(payload['style']['custom_css'])>LIMITS['custom_css']:
            abort(409, description='This theme needs a smaller CSS snapshot before export.')
        response=make_response(json.dumps(payload,ensure_ascii=True,indent=2)+'\n')
        response.headers['Content-Type']='application/json; charset=utf-8'
        response.headers['Content-Disposition']='attachment; filename="neonrest-gallery-'+row['public_id']+'.json"'
        return response

    @app.route('/themes/gallery/<public_id>/withdraw',methods=['POST'])
    def theme_gallery_withdraw(public_id):
        uid=account();csrf();db=core.get_db();row=entry(public_id,owner=True)
        if row['owner_id']!=uid: abort(403)
        if row['status']!='withdrawn':
            db.execute("UPDATE theme_gallery_entries SET status='withdrawn' WHERE id=?", (row['id'],))
            db.execute('INSERT INTO theme_gallery_events(entry_id,actor_id,action,reason) VALUES(?,?,?,?)', (row['id'],uid,'withdrawn','Author withdrew gallery availability; earlier licenses remain'))
            db.commit()
        return redirect(url_for('theme_gallery_mine'))

    @app.route('/manage/themes/gallery/<public_id>/preview')
    def theme_gallery_review_preview(public_id):
        account();core.require_staff_permission('approve_vibes')
        row=entry(public_id,owner=True)
        return render_template('theme_gallery_preview.html', item=row, events=core.get_db().execute('SELECT action,reason,created_at FROM theme_gallery_events WHERE entry_id=? ORDER BY id DESC LIMIT 20',(row['id'],)).fetchall(),
            preview={'slug':row['scope_slug'],'mode':row['mode'],'style':json.loads(row['style_json'])['style']})

    @app.route('/manage/themes/gallery',methods=['GET','POST'])
    def theme_gallery_review():
        uid=account();core.require_staff_permission('approve_vibes');db=core.get_db()
        if request.method=='POST':
            csrf();row=entry(request.form.get('public_id',''),owner=True)
            decision=request.form.get('decision')
            if decision not in ('approved','rejected','withdrawn'): abort(400)
            if decision in ('approved','rejected') and row['status']!='pending': abort(409)
            reason=text(request.form.get('reason'),1000)
            if decision=='approved' and request.form.get('review_checked')!='yes': abort(400)
            changed=db.execute('UPDATE theme_gallery_entries SET status=? WHERE id=? AND status=?', (decision,row['id'],row['status'])).rowcount
            if changed!=1: abort(409)
            db.execute('INSERT INTO theme_gallery_events(entry_id,actor_id,action,reason) VALUES(?,?,?,?)', (row['id'],uid,decision,reason))
            db.commit()
            return redirect(url_for('theme_gallery_review'))
        status=request.args.get('status','pending')
        if status not in ('pending','approved','rejected','withdrawn'): abort(400)
        rows=db.execute('SELECT * FROM theme_gallery_entries WHERE status=? AND id<? ORDER BY id DESC LIMIT 21', (status,before_id())).fetchall()
        return render_template('theme_gallery_review.html', entries=rows[:20], status=status, next_before=rows[19]['id'] if len(rows)>20 else None, token=core.theme_csrf_token())
