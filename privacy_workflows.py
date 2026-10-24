"""Private request tracking and fail-closed preservation; no automatic erasure."""
import hashlib
import json
import time
from datetime import datetime, timezone

DAY = 86400
FINAL = ('closed', 'resolved', 'dismissed', 'reviewed', 'approved', 'denied')


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS privacy_holds(
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, reason TEXT NOT NULL,
      legal_basis TEXT NOT NULL, reference TEXT NOT NULL, reviewer_id INTEGER NOT NULL,
      created_at INTEGER NOT NULL, review_due INTEGER NOT NULL, released_at INTEGER,
      released_by INTEGER, release_reason TEXT);
    CREATE TABLE IF NOT EXISTS privacy_case_dispositions(
      case_id INTEGER PRIMARY KEY, reviewer_id INTEGER NOT NULL,
      decision TEXT NOT NULL, recorded_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS privacy_request_events(
      id INTEGER PRIMARY KEY, request_id INTEGER, actor_id INTEGER NOT NULL,
      action TEXT NOT NULL, detail TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS privacy_hold_user ON privacy_holds(user_id,released_at);
    ''')
    columns = {r[1] for r in db.execute('PRAGMA table_info(family_data_requests)')}
    additions = {
        'assigned_to': 'INTEGER', 'response_due': 'INTEGER',
        'requester_kind': "TEXT NOT NULL DEFAULT 'guardian'", 'contact_email': 'TEXT',
        'extended_at': 'INTEGER', 'extension_reason': 'TEXT',
        'response_text': 'TEXT', 'responded_at': 'INTEGER',
        'appeal_text': 'TEXT', 'appealed_at': 'INTEGER', 'appeal_due': 'INTEGER',
        'appeal_decision': 'TEXT', 'appeal_response': 'TEXT',
        'appeal_reviewer': 'INTEGER', 'appeal_reviewed_at': 'INTEGER',
        'approved_payload': 'TEXT', 'payload_sha256': 'TEXT',
        'authority_version': 'TEXT', 'disclosure_basis': 'TEXT',
    }
    for name, definition in additions.items():
        if name not in columns:
            db.execute('ALTER TABLE family_data_requests ADD COLUMN '+name+' '+definition)
    db.execute("""UPDATE family_data_requests SET response_due=
        COALESCE(CAST(strftime('%s',created_at) AS INTEGER),?)+?
        WHERE response_due IS NULL""", (int(time.time()),45*DAY))
    docs={r[1] for r in db.execute('PRAGMA table_info(family_consent_documents)')}
    if docs:
        for name in ('verified_at','verified_by','purge_after'):
            if name not in docs:db.execute('ALTER TABLE family_consent_documents ADD COLUMN '+name+' INTEGER')
    ts=table_columns(db)
    if 'moderation_cases' in ts:
        db.executescript('''CREATE TRIGGER IF NOT EXISTS privacy_case_reopened
          AFTER UPDATE OF status ON moderation_cases WHEN NEW.status<>OLD.status
          BEGIN DELETE FROM privacy_case_dispositions WHERE case_id=NEW.id; END;''')
    if 'case_links' in ts:
        db.executescript('''CREATE TRIGGER IF NOT EXISTS privacy_case_new_issue
          AFTER INSERT ON case_links
          BEGIN DELETE FROM privacy_case_dispositions WHERE case_id=NEW.case_id; END;''')
    db.commit()


def event(db, rid, actor, action, detail):
    db.execute('INSERT INTO privacy_request_events(request_id,actor_id,action,detail,created_at) VALUES (?,?,?,?,?)',
               (rid,actor,action,detail,int(time.time())))


def table_columns(db):
    return {r[0]:{c[1] for c in db.execute('PRAGMA table_info("'+r[0]+'")')}
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def blockers(db, uid):
    """Read-only. Check live case state again immediately before any erasure."""
    ts=table_columns(db); result=[]
    if 'privacy_holds' in ts:
        result.extend('Preservation hold #'+str(r[0]) for r in db.execute(
            'SELECT id FROM privacy_holds WHERE user_id=? AND released_at IS NULL',(uid,)))
    if 'moderation_cases' in ts:
        for row in db.execute('SELECT id,target_type,target_id,owner_id,status FROM moderation_cases'):
            cid,kind,target,owner,status=row
            involved=owner==uid or kind in ('user','ban','posting','interaction') and target==uid
            if kind=='post' and 'posts' in ts:
                involved |= bool(db.execute('SELECT 1 FROM posts WHERE id=? AND (user_id=? OR target_user_id=?)',(target,uid,uid)).fetchone())
                if 'comments' in ts:
                    involved |= bool(db.execute('SELECT 1 FROM comments WHERE post_id=? AND user_id=?',(target,uid)).fetchone())
            if kind=='comment' and 'comments' in ts:
                involved |= bool(db.execute('SELECT 1 FROM comments WHERE id=? AND user_id=?',(target,uid)).fetchone())
            if not involved and 'case_evidence' in ts:
                def mentions(value):
                    if isinstance(value,dict):
                        return any(k in ('user_id','reporter_id','appellant_id','target_user_id') and v==uid or mentions(v) for k,v in value.items())
                    return isinstance(value,list) and any(mentions(v) for v in value)
                for (snapshot,) in db.execute('SELECT snapshot FROM case_evidence WHERE case_id=?',(cid,)):
                    try:involved |= mentions(json.loads(snapshot))
                    except (TypeError,ValueError):involved=True
            if 'case_links' in ts:
                for link_kind,table,col in [('report','content_reports','reporter_id'),('appeal','moderation_appeals','appellant_id')]:
                    if table in ts:
                        involved |= bool(db.execute('SELECT 1 FROM case_links l JOIN '+table+' x ON x.id=l.item_id WHERE l.case_id=? AND l.kind=? AND x.'+col+'=?',(cid,link_kind,uid)).fetchone())
            if involved:
                disposed='privacy_case_dispositions' in ts and db.execute('SELECT 1 FROM privacy_case_dispositions WHERE case_id=?',(cid,)).fetchone()
                if status!='closed' or not disposed:
                    result.append('Case #'+str(cid)+': final preservation disposition required')
                if 'case_links' in ts and 'moderation_appeals' in ts and db.execute("SELECT 1 FROM case_links l JOIN moderation_appeals a ON a.id=l.item_id WHERE l.kind='appeal' AND l.case_id=? AND a.status='open'",(cid,)).fetchone():
                    result.append('Case #'+str(cid)+': open appeal')
    # Protect reports/appeals even if a legacy row has not been attached to a case.
    if 'moderation_appeals' in ts and db.execute("SELECT 1 FROM moderation_appeals WHERE appellant_id=? AND status='open'",(uid,)).fetchone():
        result.append('Open moderation appeal')
    if 'content_reports' in ts:
        for kind,target,reporter,status in db.execute('SELECT target_type,target_id,reporter_id,status FROM content_reports'):
            if status in FINAL: continue
            involved=reporter==uid or kind=='user' and target==uid
            if kind=='post' and 'posts' in ts:
                involved |= bool(db.execute('SELECT 1 FROM posts WHERE id=? AND (user_id=? OR target_user_id=?)',(target,uid,uid)).fetchone())
            if kind=='comment' and 'comments' in ts:
                involved |= bool(db.execute('SELECT 1 FROM comments WHERE id=? AND user_id=?',(target,uid)).fetchone())
            if involved: result.append('Open content report')
    if 'dm_reports' in ts and db.execute("SELECT 1 FROM dm_reports WHERE status='open' AND (reporter_id=? OR author_id=?)",(uid,uid)).fetchone():
        result.append('Open private message report')
    if 'circle_reports' in ts:
        for report in db.execute("SELECT reporter_id,author_id,post_owner_id FROM circle_reports WHERE status='open'"):
            involved=uid in report
            if involved:result.append('Open Circle report')
    if 'family_data_requests' in ts:
        fields=ts['family_data_requests']
        if 'appealed_at' in fields and db.execute('SELECT 1 FROM family_data_requests WHERE (parent_id=? OR child_id=?) AND appealed_at IS NOT NULL AND appeal_reviewed_at IS NULL',(uid,uid)).fetchone():
            result.append('Open privacy appeal')
    return sorted(set(result))


def erasure_blockers(db, uid):
    """Deleting one account must not cascade-delete another held person's data."""
    result=blockers(db,uid); ts=table_columns(db); related=set()
    if 'privacy_submission_documents' in ts and db.execute('SELECT 1 FROM privacy_submission_documents d JOIN family_data_requests r ON r.id=d.request_id WHERE d.purged_at IS NULL AND (r.parent_id=? OR r.child_id=?)',(uid,uid)).fetchone():
        result.append('Private verification documents require reviewed disposal')
    if 'identity_pages' in ts:
        from .identity_pages import erasure_dependencies
        if erasure_dependencies(db,uid):
            result.append('Page ownership, delegation or authorship requires reviewed transfer/disposal')
    pids=[]
    if 'posts' in ts:
        for row in db.execute('SELECT id,user_id,target_user_id FROM posts WHERE user_id=? OR target_user_id=?',(uid,uid)):
            pids.append(row[0]);related.update(v for v in row[1:] if v)
    if pids and 'post_bookmarks' in ts:
        related.update(r[0] for r in db.execute('SELECT user_id FROM post_bookmarks WHERE post_id IN ('+','.join('?'*len(pids))+')',pids))
    if pids and 'comments' in ts:
        related.update(r[0] for r in db.execute('SELECT user_id FROM comments WHERE post_id IN ('+','.join('?'*len(pids))+')',pids))
    if 'comments' in ts and 'posts' in ts:
        for row in db.execute('SELECT p.user_id,p.target_user_id FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.user_id=?',(uid,)):
            related.update(v for v in row if v)
        if 'parent_comment_id' in ts['comments']:
            related.update(r[0] for r in db.execute('SELECT user_id FROM comments WHERE parent_comment_id IN (SELECT id FROM comments WHERE user_id=?)',(uid,)))
    for table,cols in {'friend_requests':('sender_id','receiver_id'),'follows':('follower_id','followed_id'),
                       'top_friends':('user_id','friend_id'),'friend_label_members':('user_id','friend_id'),
                       'follower_exclusions':('user_id','target_id'),'user_blocks':('user_id','target_id'),
                       'user_mutes':('user_id','target_id'),'family_links':('parent_id','child_id'),
                       'notifications':('user_id','actor_id'),
                       'family_consent_documents':('parent_id','child_id'),'parent_contacts':('parent_id','child_id','peer_id')}.items():
        if table not in ts or not set(cols)<=ts[table]:continue
        for row in db.execute('SELECT '+','.join(cols)+' FROM '+table+' WHERE '+' OR '.join(c+'=?' for c in cols),(uid,)*len(cols)):
            related.update(v for v in row if v)
    if 'dm_threads' in ts:
        for pair in db.execute('SELECT low_user,high_user FROM dm_threads WHERE low_user=? OR high_user=?',(uid,uid)):
            related.update(v for v in pair if v)
    for other in related-{uid}:
        if blockers(db,other):result.append('Deletion would alter preserved data shared with account #'+str(other))
    return sorted(set(result))


def authority_version(db, parent, child):
    row=db.execute('SELECT status,method,reference,reviewed_by,reviewed_at FROM family_links WHERE parent_id=? AND child_id=?',(parent,child)).fetchone()
    return hashlib.sha256(repr(tuple(row)).encode()).hexdigest() if row else None


PROFILE=('handle','actual_name','email','dob','bio','pronouns','created_at','timezone')
FIELDS={'posts':('id','content','circle','created_at','last_edited'),
        'replies':('id','post_id','content','created_at'),
        'media':('id','post_id','kind','mime_type','alt_text','created_at')}


def export_candidate(db, child):
    user=db.execute('SELECT * FROM users WHERE id=?',(child,)).fetchone()
    if not user: raise ValueError('Account is unavailable.')
    data={'profile':{k:user[k] for k in PROFILE if k in user.keys()}}
    ts=table_columns(db)
    for key,query in [('posts','SELECT * FROM posts WHERE user_id=?'),
                      ('replies','SELECT * FROM comments WHERE user_id=?'),
                      ('media','SELECT m.* FROM post_media m JOIN posts p ON p.id=m.post_id WHERE p.user_id=?')]:
        table='comments' if key=='replies' else 'post_media' if key=='media' else key
        data[key]=[{k:r[k] for k in FIELDS[key] if k in r.keys()} for r in db.execute(query,(child,))] if table in ts else []
    return data


def validate_export(db, child, raw):
    if len(raw.encode())>1024*1024: raise ValueError('Reviewed export exceeds 1 MiB; narrow the scope.')
    try: data=json.loads(raw)
    except (TypeError,ValueError): raise ValueError('Reviewed export must be valid JSON.')
    candidate=export_candidate(db,child)
    if not isinstance(data,dict) or not data or set(data)-set(candidate): raise ValueError('Unknown export section.')
    for section,value in data.items():
        if section=='profile':
            if not isinstance(value,dict) or set(value)-set(candidate['profile']): raise ValueError('Unknown profile field.')
            if any(not (v is None or isinstance(v,(str,int,float))) for v in value.values()): raise ValueError('Invalid profile value.')
        else:
            allowed={r['id']:r for r in candidate[section]}
            if not isinstance(value,list): raise ValueError('Export sections must contain lists.')
            seen=set()
            for row in value:
                if not isinstance(row,dict) or type(row.get('id')) is not int or row['id'] not in allowed or row['id'] in seen: raise ValueError('Export contains an unrelated or repeated record.')
                seen.add(row['id'])
                if set(row)-set(allowed[row['id']]): raise ValueError('Unknown record field.')
                for key,v in row.items():
                    if not (v is None or isinstance(v,(str,int,float))): raise ValueError('Invalid record value.')
                    if key in ('id','post_id') and v!=allowed[row['id']].get(key): raise ValueError('Record references cannot be changed.')
    return data


def approve_export(db, row, actor, raw, basis):
    data=validate_export(db,row['child_id'],raw)
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True)
    db.execute('UPDATE family_data_requests SET approved_payload=?,payload_sha256=?,authority_version=?,disclosure_basis=? WHERE id=?',
        (payload,hashlib.sha256(payload.encode()).hexdigest(),authority_version(db,row['parent_id'],row['child_id']),basis,row['id']))
    event(db,row['id'],actor,'disclosure-approved','Reviewed scope and disclosure basis recorded; 24-hour grant.')


def approved_export(db,row):
    raw=row['approved_payload']
    if not raw or hashlib.sha256(raw.encode()).hexdigest()!=row['payload_sha256']: raise ValueError('This export requires a new staff review.')
    if row['authority_version']!=authority_version(db,row['parent_id'],row['child_id']): raise ValueError('Authority changed; a new staff review is needed.')
    return json.loads(raw)


def register(app,core):
    from flask import abort,flash,redirect,render_template,request,session,url_for
    with app.app_context(): initialize(core.get_db())
    app.jinja_env.filters['privacy_date']=lambda value:datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value else 'Not scheduled'
    from neonrest_sandbox.privacy_submissions import register as register_submissions
    register_submissions(app,core)
    def helpers(): return app.extensions['community_auth_helpers']
    def staff():
        actor=core.require_staff_permission('manage_roles')
        if not helpers()['fresh'](): abort(403,description='Confirm your sign-in before accessing private requests.')
        return actor
    def text(name,maximum=2000):
        value=request.form.get(name,'').strip()
        if not value or len(value)>maximum: abort(400,description='Provide '+name.replace('_',' ')+'.')
        return value
    def record(db,rid):
        row=db.execute('SELECT * FROM family_data_requests WHERE id=?',(rid,)).fetchone()
        if not row:abort(404)
        return row
    @app.get('/manage/privacy/help')
    def privacy_management_help():
        staff()
        return render_template('privacy_guide.html',family=False)

    @app.get('/manage/family/requests/help')
    def family_data_review_help():
        staff()
        return render_template('privacy_guide.html',family=True)

    @app.route('/manage/privacy',methods=['GET','POST'])
    def privacy_management():
        actor=staff(); db=core.get_db()
        if request.method=='POST':
            helpers()['csrf'](); action=request.form.get('action')
            if action=='record-request':
                child=request.form.get('child_id',type=int);parent=request.form.get('parent_id',0,type=int)
                if not db.execute('SELECT 1 FROM users WHERE id=?',(child,)).fetchone():abort(400)
                if parent and not db.execute('SELECT 1 FROM users WHERE id=?',(parent,)).fetchone():abort(400)
                kind=request.form.get('kind');contact=text('contact_email',254)
                if kind not in ('data-review','delete','dob-correction','correction','other') or '@' not in contact or '\n' in contact or '\r' in contact:abort(400)
                try:
                    received=datetime.fromisoformat(request.form.get('received_at','').strip()).replace(tzinfo=timezone.utc).timestamp() if request.form.get('received_at') else time.time()
                except ValueError:abort(400,description='Provide a valid receipt date.')
                if received>time.time()+60:abort(400,description='Receipt cannot be in the future.')
                created=db.execute("INSERT INTO family_data_requests(parent_id,child_id,kind,notes,requester_kind,contact_email,response_due,assigned_to,created_at) VALUES (?,?,?,?,'assisted',?,?,?,?)",(parent,child,kind,text('notes'),contact,int(received)+45*DAY,actor,datetime.fromtimestamp(received,timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))).lastrowid
                event(db,created,actor,'received','Assisted/email intake; authority must be verified separately.')
            elif action in ('add-hold','review-hold','release-hold'):
                reference=text('reference',500);reason=text('reason');now=int(time.time())
                if action=='add-hold':
                    uid=request.form.get('user_id',type=int)
                    if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():abort(400)
                    db.execute('INSERT INTO privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) VALUES (?,?,?,?,?,?,?)',(uid,reason,text('legal_basis'),reference,actor,now,now+30*DAY))
                else:
                    hold=db.execute('SELECT * FROM privacy_holds WHERE id=? AND released_at IS NULL',(request.form.get('hold_id',type=int),)).fetchone()
                    if not hold:abort(404)
                    if action=='review-hold':db.execute('UPDATE privacy_holds SET reason=?,legal_basis=?,reference=?,reviewer_id=?,review_due=? WHERE id=?',(reason,text('legal_basis'),reference,actor,now+30*DAY,hold['id']))
                    else:db.execute('UPDATE privacy_holds SET released_at=?,released_by=?,release_reason=? WHERE id=?',(now,actor,reason,hold['id']))
                event(db,None,actor,action,reference+': '+reason)
            elif action=='finalize-case':
                cid=request.form.get('case_id',type=int);case=db.execute('SELECT status FROM moderation_cases WHERE id=?',(cid,)).fetchone()
                if not case or case['status']!='closed' or request.form.get('appeals_final')!='1':abort(400,description='Close the case and resolve applicable appeals before final disposition.')
                for kind,table in [('report','content_reports'),('appeal','moderation_appeals')]:
                    if db.execute('SELECT 1 FROM case_links l JOIN '+table+" x ON x.id=l.item_id WHERE l.case_id=? AND l.kind=? AND x.status='open'",(cid,kind)).fetchone():abort(409,description='A linked issue is still open.')
                decision=text('reason')
                db.execute('INSERT INTO privacy_case_dispositions VALUES (?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET reviewer_id=excluded.reviewer_id,decision=excluded.decision,recorded_at=excluded.recorded_at',(cid,actor,decision,int(time.time())))
                event(db,None,actor,action,'Case #'+str(cid)+': '+decision)
            elif action=='schedule-document-purge':
                doc=db.execute('SELECT * FROM family_consent_documents WHERE id=?',(request.form.get('document_id',type=int),)).fetchone()
                days=request.form.get('purge_days',type=int)
                if not doc or days is None or not 1<=days<=365:abort(400)
                reason=text('reason');now=int(time.time())
                db.execute('UPDATE family_consent_documents SET verified_at=?,verified_by=?,purge_after=? WHERE id=?',(now,actor,now+days*DAY,doc['id']))
                event(db,None,actor,action,'Document #'+str(doc['id'])+': '+reason)
            else:
                row=record(db,request.form.get('request_id',type=int));rid=row['id'];now=int(time.time())
                if action=='assign':
                    owner=request.form.get('assigned_to',type=int)
                    if not core.has_staff_permission(db,owner,'manage_roles'):abort(400)
                    db.execute('UPDATE family_data_requests SET assigned_to=? WHERE id=?',(owner,rid));event(db,rid,actor,'assigned',str(owner))
                elif action=='extend':
                    if row['extended_at'] or row['responded_at'] or not row['response_due'] or now>row['response_due']:abort(409)
                    reason=text('reason');notice=text('delivery_reference',500)
                    db.execute('UPDATE family_data_requests SET response_due=response_due+?,extended_at=?,extension_reason=? WHERE id=?',(45*DAY,now,reason,rid));event(db,rid,actor,'extended',reason+'; notice already delivered: '+notice)
                elif action=='record-response':
                    response=text('response_text');delivery=text('delivery_reference',500)
                    db.execute('UPDATE family_data_requests SET response_text=?,responded_at=COALESCE(responded_at,?) WHERE id=?',(response,now,rid));event(db,rid,actor,'response-recorded','Already delivered: '+delivery+'; '+response)
                elif action=='record-appeal':
                    if row['appealed_at'] and not row['appeal_reviewed_at']:abort(409)
                    db.execute('UPDATE family_data_requests SET appeal_text=?,appealed_at=?,appeal_due=?,appeal_decision=NULL,appeal_response=NULL,appeal_reviewer=NULL,appeal_reviewed_at=NULL WHERE id=?',(text('reason'),now,now+45*DAY,rid));event(db,rid,actor,'appeal-received','Received through assisted intake.')
                elif action=='decide-appeal':
                    if not row['appealed_at'] or row['appeal_reviewed_at']:abort(409)
                    decision=request.form.get('decision');response=text('response_text');delivery=text('delivery_reference',500)
                    if decision not in ('approved','denied'):abort(400)
                    independent=text('independence_reason',500) if actor==row['reviewed_by'] else 'Different reviewer'
                    if decision=='denied' and 'https://www.doj.state.or.us/consumer-protection/id-theft-data-breaches/privacy' not in response:response+='\nYou may submit a privacy complaint to the Oregon Attorney General: https://www.doj.state.or.us/consumer-protection/id-theft-data-breaches/privacy/'
                    if decision=='denied' and request.form.get('complaint_notice_delivered')!='1':abort(400,description='Include Oregon Attorney General complaint instructions in the delivered appeal denial.')
                    db.execute('UPDATE family_data_requests SET appeal_decision=?,appeal_response=?,appeal_reviewer=?,appeal_reviewed_at=? WHERE id=?',(decision,response,actor,now,rid));event(db,rid,actor,'appeal-decided',decision+'; '+independent+'; response already delivered: '+delivery)
                else:abort(400)
            db.commit();flash('Recorded. This screen does not send email or erase data.','info');return redirect(url_for('privacy_management'))
        rows=db.execute('SELECT r.*,p.handle AS parent_handle,c.handle AS child_handle FROM family_data_requests r LEFT JOIN users p ON p.id=r.parent_id LEFT JOIN users c ON c.id=r.child_id ORDER BY r.created_at,r.id').fetchall()
        holds=db.execute('SELECT h.*,u.handle FROM privacy_holds h LEFT JOIN users u ON u.id=h.user_id ORDER BY h.released_at IS NOT NULL,h.review_due').fetchall()
        deleting=[dict(r,blockers=erasure_blockers(db,r['id'])) for r in db.execute('SELECT u.id,u.handle FROM users u JOIN account_safety a ON a.user_id=u.id WHERE a.deletion_requested_at IS NOT NULL')]
        docs=db.execute('SELECT id,parent_id,child_id,verified_at,purge_after FROM family_consent_documents ORDER BY id DESC').fetchall()
        return render_template('privacy_management.html',records=rows,holds=holds,deleting=deleting,documents=docs,now=int(time.time()),token=core.theme_csrf_token())

    @app.post('/account/family/requests/<int:request_id>/appeal')
    def privacy_request_appeal(request_id):
        db=core.get_db();uid=session.get('user_id');row=record(db,request_id)
        if not uid or uid!=row['parent_id']:abort(404)
        helpers()['csrf']()
        if not helpers()['fresh']():return redirect(url_for('community_reauth',next=url_for('family_data_requests')))
        if row['status'] not in ('declined','closed') and not row['responded_at']:abort(400)
        if row['appealed_at'] and not row['appeal_reviewed_at']:abort(409)
        now=int(time.time())
        db.execute('UPDATE family_data_requests SET appeal_text=?,appealed_at=?,appeal_due=?,appeal_decision=NULL,appeal_response=NULL,appeal_reviewer=NULL,appeal_reviewed_at=NULL WHERE id=?',(text('reason'),now,now+45*DAY,request_id));event(db,request_id,uid,'appeal-received','Account request');db.commit()
        flash('Your appeal has been recorded for review.','info');return redirect(url_for('family_data_requests'))

    @app.after_request
    def privacy_headers(response):
        if request.endpoint in ('privacy_submissions','privacy_submission_upload','privacy_submission_download','privacy_management_help','family_data_review_help','privacy_management','privacy_request_appeal','family_data_review','family_data_requests','family_data_download'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['Referrer-Policy']='same-origin'
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['X-Neonrest-Privacy-Revision']='2026-10-14.7'
        return response
