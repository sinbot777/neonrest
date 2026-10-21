"""Member-controlled Circle alerts and explicitly shared local reports."""
import json
from flask import abort, flash, redirect, render_template, request, session, url_for
from neonrest_sandbox import circles, circle_ids, age_policy as ages
from neonrest_sandbox import community_features as community


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS circle_post_preferences(
      circle_id INTEGER NOT NULL,user_id INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
      PRIMARY KEY(circle_id,user_id));
    CREATE TABLE IF NOT EXISTS circle_reports(
      id INTEGER PRIMARY KEY,circle_id INTEGER NOT NULL,reporter_id INTEGER NOT NULL,
      target_type TEXT NOT NULL CHECK(target_type IN ('post','comment')),target_id INTEGER NOT NULL,
      reason TEXT NOT NULL,author_id INTEGER NOT NULL,post_owner_id INTEGER NOT NULL,snapshot TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','reviewed','escalated')),
      resolution TEXT NOT NULL DEFAULT '',decision TEXT NOT NULL DEFAULT '',reviewed_by INTEGER,reviewed_at TEXT,site_report_id INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS circle_report_queue ON circle_reports(circle_id,status,id DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS circle_report_open ON circle_reports(circle_id,reporter_id,target_type,target_id) WHERE status='open';
    CREATE TRIGGER IF NOT EXISTS circle_preference_cleanup AFTER DELETE ON circles
      BEGIN DELETE FROM circle_post_preferences WHERE circle_id=OLD.id; END;
    CREATE TRIGGER IF NOT EXISTS circle_member_alert_reset AFTER UPDATE OF status ON circle_members
      WHEN NEW.status<>'active' BEGIN UPDATE circle_post_preferences SET enabled=0 WHERE circle_id=NEW.circle_id AND user_id=NEW.user_id; END;
    CREATE TRIGGER IF NOT EXISTS circle_archive_alert_reset AFTER UPDATE OF archived ON circles
      WHEN NEW.archived=1 BEGIN UPDATE circle_post_preferences SET enabled=0 WHERE circle_id=NEW.id; END;
    ''')
    if 'resolution' not in {r[1] for r in db.execute('PRAGMA table_info(circle_reports)')}:
        db.execute("ALTER TABLE circle_reports ADD COLUMN resolution TEXT NOT NULL DEFAULT ''")
    db.executescript('''
    CREATE TABLE IF NOT EXISTS circle_content_removals(
      circle_id INTEGER NOT NULL,target_type TEXT NOT NULL CHECK(target_type IN ('post','comment')),
      target_id INTEGER NOT NULL,report_id INTEGER NOT NULL,removed_by INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(target_type,target_id));
    CREATE TABLE IF NOT EXISTS circle_report_actions(
      id INTEGER PRIMARY KEY,report_id INTEGER NOT NULL,actor_id INTEGER NOT NULL,
      action TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TRIGGER IF NOT EXISTS circle_removed_post_cleanup AFTER DELETE ON posts
      BEGIN DELETE FROM circle_content_removals WHERE target_type='post' AND target_id=OLD.id; END;
    CREATE TRIGGER IF NOT EXISTS circle_removed_comment_cleanup AFTER DELETE ON comments
      BEGIN DELETE FROM circle_content_removals WHERE target_type='comment' AND target_id=OLD.id; END;
    ''')
    db.commit()


def target(db, cid, kind, key, uid, include_removed=False):
    if kind=='post':
        row=db.execute('SELECT p.id AS post_id,p.user_id,p.content FROM posts p JOIN circle_posts cp ON cp.post_id=p.id WHERE p.id=? AND cp.circle_id=?',(key,cid)).fetchone()
    elif kind=='comment':
        row=db.execute('SELECT c.post_id,c.user_id,c.content FROM comments c JOIN circle_posts cp ON cp.post_id=c.post_id WHERE c.id=? AND cp.circle_id=? AND NOT EXISTS(SELECT 1 FROM moderated_comments WHERE comment_id=c.id)',(key,cid)).fetchone()
        if row and (not circles.comment_allowed(db,key,uid,include_removed=include_removed) or not ages.comment_read(db,key,uid)):
            return None
    else:
        return None
    if not row or not community.visible_post(db,row['post_id'],uid,include_circle_removed=include_removed) or db.execute('SELECT 1 FROM moderated_posts WHERE post_id=?',(row['post_id'],)).fetchone():
        return None
    return row


def upgrade_report_notifications(db):
    """Link older generic notices only when their creation order is unambiguous."""
    groups={}
    for row in db.execute("SELECT id,user_id,actor_id,path,created_at FROM notifications WHERE kind='circles' AND message='A Circle report is waiting for review.' ORDER BY id"):
        path=row['path']
        parts=(path or '').split('/')
        if len(parts)!=4 or parts[1]!='circles' or parts[3]!='reports':continue
        try:cid=circle_ids.resolve(db,parts[2])
        except ValueError:continue
        groups.setdefault((cid,row['user_id'],row['actor_id'],row['created_at'],path),[]).append(row['id'])
    changed=0
    for (cid,uid,reporter,created,path),notice_ids in groups.items():
        report_ids=[row[0] for row in db.execute('SELECT id FROM circle_reports WHERE circle_id=? AND reporter_id=? AND author_id<>? AND created_at=? ORDER BY id',(cid,reporter,uid,created))]
        if len(report_ids)!=len(notice_ids):continue
        for nid,rid in zip(notice_ids,report_ids):
            db.execute('UPDATE notifications SET path=? WHERE id=?',(path+'?report_id='+str(rid)+'#circle-report-'+str(rid),nid));changed+=1
    db.commit()
    return changed


def notify_post(db, pid, author):
    circle=circles.post_circle(db,pid)
    if not circle:
        return
    rows=db.execute('SELECT user_id FROM circle_post_preferences WHERE circle_id=? AND enabled=1 AND user_id<>?',(circle['id'],author)).fetchall()
    for row in rows:
        if circles.membership(db,circle,row['user_id']) and community.visible_post(db,pid,row['user_id']):
            community.notify(db,row['user_id'],'circle_posts','A new post was shared in '+circles.label(circle)+'.','/posts/'+str(pid),author)


def register(app, core, circle_for, actor, mutation, record):
    def db():return core.get_db()

    @app.before_request
    def preserve_pending_report_content():
        if request.method!='POST' or request.endpoint not in ('delete_post','delete_comment'):return
        if not session.get('user_id'):return
        field='post_id' if request.endpoint=='delete_post' else 'comment_id'
        kind='post' if field=='post_id' else 'comment'
        try:key=core.identifiers.resolve(db(),kind,request.view_args.get(field))
        except (ValueError,TypeError,AttributeError):return
        table='posts' if kind=='post' else 'comments'
        if not db().execute('SELECT 1 FROM '+table+' WHERE id=? AND user_id=?',(key,session['user_id'])).fetchone():return
        if kind=='post':
            pending=db().execute("SELECT 1 FROM circle_reports WHERE status='open' AND ((target_type='post' AND target_id=?) OR (target_type='comment' AND target_id IN (SELECT id FROM comments WHERE post_id=?)))",(key,key)).fetchone()
        else:pending=db().execute("SELECT 1 FROM circle_reports WHERE status='open' AND target_type='comment' AND target_id=?",(key,)).fetchone()
        if pending:abort(409,description='This content has an unresolved Circle report. Ask a Circle manager or site staff to resolve it before deletion.')

    @app.context_processor
    def context():
        def preference(circle):
            row=db().execute('SELECT enabled FROM circle_post_preferences WHERE circle_id=? AND user_id=?',(circle['id'],session.get('user_id'))).fetchone()
            return bool(row and row['enabled'])
        def notice_circle(item):
            if item['kind']!='circle_posts':return None
            try:pid=core.identifiers.resolve(db(),'post',item['path'].split('/posts/',1)[1].split('#')[0])
            except (ValueError,IndexError):return None
            circle=circles.post_circle(db(),pid)
            return circle if circle and circles.membership(db(),circle,session.get('user_id')) else None
        return dict(circle_post_alerts=preference,circle_notice_circle=notice_circle)

    @app.route('/circles/<string:circle_id>/notifications',methods=['POST'])
    def circle_notifications(circle_id):
        uid=mutation();circle,member=circle_for(circle_id,uid)
        if not member:abort(403)
        action=request.form.get('action')
        if action not in ('enable','mute'):abort(400)
        db().execute('INSERT INTO circle_post_preferences VALUES (?,?,?) ON CONFLICT(circle_id,user_id) DO UPDATE SET enabled=excluded.enabled',(circle_id,uid,int(action=='enable')))
        db().commit()
        flash('New-post notifications enabled for this Circle.' if action=='enable' else 'New-post notifications muted for this Circle. Earlier messages remain in your history.','success')
        return redirect(url_for('community_notifications') if request.form.get('return_to')=='notifications' else url_for('circle_page',circle_id=circle_id),303)

    @app.route('/circles/<string:circle_id>/report/<kind>/<string:target_id>',methods=['GET','POST'])
    def circle_report(circle_id,kind,target_id):
        uid=mutation() if request.method=='POST' else actor();circle,member=circle_for(circle_id,uid)
        if not member:abort(403)
        if kind not in ('post','comment'):abort(404)
        try:key=core.identifiers.resolve(db(),kind,target_id)
        except ValueError:abort(404)
        item=target(db(),circle_id,kind,key,uid)
        if not item:abort(404)
        if item['user_id']==uid:abort(403)
        if request.method=='POST':
            reason=request.form.get('reason','').strip()
            if not 10<=len(reason)<=500:abort(400,description='Explain the Circle concern in 10–500 characters.')
            prior=db().execute("SELECT id FROM circle_reports WHERE circle_id=? AND reporter_id=? AND target_type=? AND target_id=? AND status='open'",(circle_id,uid,kind,key)).fetchone()
            if not prior:
                post_owner=db().execute('SELECT user_id FROM posts WHERE id=?',(item['post_id'],)).fetchone()[0]
                snapshot=json.dumps(dict(target_type=kind,target_id=key,user_id=item['user_id'],post_id=item['post_id'],post_owner_id=post_owner,content=item['content']),sort_keys=True)
                report_id=db().execute('INSERT INTO circle_reports(circle_id,reporter_id,target_type,target_id,reason,author_id,post_owner_id,snapshot) VALUES (?,?,?,?,?,?,?,?)',(circle_id,uid,kind,key,reason,item['user_id'],post_owner,snapshot)).lastrowid
                for manager in db().execute("SELECT user_id FROM circle_members WHERE circle_id=? AND status='active' AND role IN ('owner','moderator') AND user_id<>?",(circle_id,item['user_id'])).fetchall():
                    if target(db(),circle_id,kind,key,manager['user_id']):
                        community.notify(db(),manager['user_id'],'circles','A Circle report is waiting for review.','/circles/'+circle_ids.public(db(),circle_id)+'/reports?report_id='+str(report_id)+'#circle-report-'+str(report_id),uid)
            db().commit();flash('Your report was shared with this Circle’s eligible managers. You may also report directly to site staff.','success')
            return redirect(url_for('circle_page',circle_id=circle_id),303)
        return render_template('circle_report.html',circle=circle,target=item,kind=kind,target_id=target_id)

    @app.route('/circles/<string:circle_id>/reports',methods=['GET','POST'])
    def circle_reports(circle_id):
        uid=mutation() if request.method=='POST' else actor();circle,member=circle_for(circle_id,uid,manage=True)
        if request.method=='POST':
            row=db().execute('SELECT * FROM circle_reports WHERE id=? AND circle_id=?',(request.form.get('report_id',type=int),circle_id)).fetchone()
            if not row:abort(404)
            item=target(db(),circle_id,row['target_type'],row['target_id'],uid,include_removed=True)
            if row['author_id']==uid:abort(404)
            if row['reporter_id']==uid:abort(403,description='Another manager or site staff must review your own report.')
            decision=request.form.get('decision','').strip();action=request.form.get('action')
            if action not in ('approve','remove','restore','reviewed','escalated') or not 10<=len(decision)<=1000:abort(400,description='Record a decision of 10–1,000 characters.')
            removed=db().execute('SELECT * FROM circle_content_removals WHERE circle_id=? AND target_type=? AND target_id=?',(circle_id,row['target_type'],row['target_id'])).fetchone()
            if action=='restore':
                if not removed or not item:abort(409,description='This content cannot be restored under your current access.')
                db().execute('DELETE FROM circle_content_removals WHERE circle_id=? AND target_type=? AND target_id=?',(circle_id,row['target_type'],row['target_id']))
                db().execute('INSERT INTO circle_report_actions(report_id,actor_id,action,reason) VALUES (?,?,?,?)',(row['id'],uid,'restored',decision))
                record(circle_id,uid,'circle_content_restored',reason='Circle report #'+str(row['id']))
                db().commit();flash('Content restored in this Circle. Site restrictions remain in effect.','success')
                return redirect(url_for('circle_reports',circle_id=circle_id,report_id=row['id'],_anchor='circle-report-'+str(row['id'])),303)
            if row['status']!='open':abort(409)
            if not item and action!='escalated':abort(409,description='The content is unavailable for Circle review. Send this report to site staff.')
            if removed and action in ('approve','remove','reviewed'):abort(409,description='This content is already removed. Use Restore on its completed report or send it to site staff.')
            if action=='remove':
                db().execute('INSERT INTO circle_content_removals(circle_id,target_type,target_id,report_id,removed_by) VALUES (?,?,?,?,?)',(circle_id,row['target_type'],row['target_id'],row['id'],uid))
            outcome={'approve':'approved','remove':'removed','reviewed':'reviewed','escalated':'escalated'}[action]
            site_id=None
            if action=='escalated':
                existing=db().execute("SELECT id FROM content_reports WHERE reporter_id=? AND target_type=? AND target_id=? AND status='open'",(row['reporter_id'],row['target_type'],row['target_id'])).fetchone()
                if existing:site_id=existing['id']
                else:
                    site_id=db().execute('INSERT INTO content_reports(reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)',(row['reporter_id'],row['target_type'],row['target_id'],row['reason'])).lastrowid
                    community.attach_report(db(),site_id)
                case=db().execute("SELECT case_id FROM case_links WHERE kind='report' AND item_id=?",(site_id,)).fetchone()
                if case:
                    snapshot=row['snapshot']
                    db().execute('INSERT INTO case_evidence(case_id,report_id,source_type,source_id,snapshot,sha256,legacy) VALUES (?,?,?,?,?,?,0)',(case['case_id'],site_id,row['target_type'],row['target_id'],snapshot,community.digest(snapshot)))
            db().execute('UPDATE circle_reports SET status=?,resolution=?,decision=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,site_report_id=? WHERE id=?',('escalated' if action=='escalated' else 'reviewed',outcome,decision,uid,site_id,row['id']))
            db().execute('INSERT INTO circle_report_actions(report_id,actor_id,action,reason) VALUES (?,?,?,?)',(row['id'],uid,outcome,decision))
            record(circle_id,uid,'circle_report_'+action,reason='Circle report #'+str(row['id'])+' ('+action+')')
            db().commit();flash({'approve':'Content approved and kept in this Circle.','remove':'Content removed from this Circle. You can restore it from Reviewed reports.','reviewed':'Circle review recorded.','escalated':'Report sent to site staff.'}[action],'success')
            return redirect(url_for('circle_reports',circle_id=circle_id,report_id=row['id'],_anchor='circle-report-'+str(row['id'])),303)
        selected=request.args.get('report_id')
        if selected is not None:
            if not selected.isascii() or not selected.isdecimal() or not 1<=len(selected)<=18 or int(selected)<1:abort(404)
            row=db().execute('SELECT * FROM circle_reports WHERE circle_id=? AND id=?',(circle_id,int(selected))).fetchone()
            if not row or row['author_id']==uid:abort(404)
            status=row['status'];page=1;rows=[row]
        else:
            status=request.args.get('status','all')
            if status not in ('all','open','reviewed','escalated'):abort(400)
            page=max(1,min(request.args.get('page',1,type=int),1000))
            rows=db().execute('SELECT * FROM circle_reports WHERE circle_id=? AND (?="all" OR status=?) ORDER BY id DESC',(circle_id,status,status))
        visible=[]
        for row in rows:
            item=target(db(),circle_id,row['target_type'],row['target_id'],uid,include_removed=True)
            if row['author_id']==uid:continue
            path=url_for('post_detail',post_id=item['post_id']) if item else None
            if item and row['target_type']=='comment':path+='#comment-'+core.identifiers.public(db(),'comment',row['target_id'])
            safe=dict(row)
            if not item:safe.update(reason='Content is no longer available for Circle review.',decision='Decision details unavailable under your current content access.')
            removed=bool(db().execute('SELECT 1 FROM circle_content_removals WHERE circle_id=? AND target_type=? AND target_id=?',(circle_id,row['target_type'],row['target_id'])).fetchone())
            actions=db().execute('SELECT action,reason,created_at FROM circle_report_actions WHERE report_id=? ORDER BY id',(row['id'],)).fetchall() if item else []
            visible.append(dict(safe,excerpt=json.loads(row['snapshot'])['content'][:300] if item else '',target_url=path if not removed else None,can_review=row['reporter_id']!=uid,unavailable=not item,removed=removed,actions=actions))
            if len(visible)>page*20:break
        total=len(visible);records=visible[(page-1)*20:page*20]
        return render_template('circle_reports.html',circle=circle,records=records,status=status,page=page,has_more=total>page*20,focused_report=selected is not None)
