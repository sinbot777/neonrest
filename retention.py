"""Sandbox retention. Preview is the default; live erasure requires explicit activation."""
import argparse,json,sqlite3,time
from pathlib import Path
from urllib.parse import urlsplit, unquote
from neonrest_sandbox.privacy_workflows import blockers,erasure_blockers

def avatar_filename(value):
    """Compare the URL path, excluding cache queries and fragments."""
    return Path(unquote(urlsplit(str(value or "")).path)).name

DAY=86400
POLICY={'deletion_grace_days':30,'expired_token_days':7,'revoked_session_days':7,'security_log_days':90,'operations_log_days':30,'notification_days':90,'unverified_account_days':30,'backup_days':30,'unused_consent_days':30}

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS account_disables(user_id INTEGER PRIMARY KEY,disabled INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL,updated_by INTEGER,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    db.execute('CREATE TABLE IF NOT EXISTS reserved_accounts(user_id INTEGER PRIMARY KEY,disabled INTEGER NOT NULL DEFAULT 1)')
    db.execute('CREATE TABLE IF NOT EXISTS retention_file_queue(path TEXT PRIMARY KEY,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    db.execute('CREATE TABLE IF NOT EXISTS retention_runs(id INTEGER PRIMARY KEY,created_at TEXT DEFAULT CURRENT_TIMESTAMP,summary TEXT NOT NULL)')
    if 'touched_at' not in {r[1] for r in db.execute('PRAGMA table_info(rate_buckets)')}:
        db.execute('ALTER TABLE rate_buckets ADD COLUMN touched_at INTEGER NOT NULL DEFAULT 0')
    db.execute('UPDATE rate_buckets SET touched_at=? WHERE touched_at=0',(int(time.time()),))
    if 'closed_at' not in {r[1] for r in db.execute('PRAGMA table_info(moderation_cases)')}:
        db.execute('ALTER TABLE moderation_cases ADD COLUMN closed_at TEXT')
    db.execute("UPDATE moderation_cases SET closed_at=CURRENT_TIMESTAMP WHERE status='closed' AND closed_at IS NULL")
    db.execute("INSERT OR IGNORE INTO account_disables(user_id,disabled,reason) SELECT user_id,disabled,'Reserved future helper account' FROM reserved_accounts WHERE disabled=1")
    db.commit()

def tables(db):
    return {r[0]:{c[1] for c in db.execute('PRAGMA table_info("'+r[0]+'")')} for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

def plan(db,now=None):
    now=int(now or time.time()); ts=tables(db); rows=[]
    def add(table,where,args):
        if table in ts:
            count=db.execute('SELECT count(*) FROM "'+table+'" WHERE '+where,args).fetchone()[0]
            if count: rows.append({'table':table,'where':where,'args':args,'count':count})
    add('email_verifications','expires_at<?',(now-7*DAY,))
    add('password_resets','expires_at<?',(now-7*DAY,))
    add('email_changes','expires_at<?',(now-7*DAY,))
    add('mail_jobs','payload IS NULL AND expires_at<?',(now-30*DAY,))
    add('active_sessions','expires_at<? OR (revoked=1 AND seen_at<?)',(now-7*DAY,now-7*DAY))
    if 'touched_at' in ts.get('rate_buckets',set()):add('rate_buckets','touched_at>0 AND touched_at<?',(now-DAY,))
    for table,days in [('account_lifecycle_events',90),('abuse_events',90),('operations_events',30),('notifications',90),('authorization_post_drafts',1),('retention_runs',90)]:
        add(table,"julianday(created_at)<julianday(?,'unixepoch')",(now-days*DAY,))
    if {'responded_at','appeal_reviewed_at'} <= ts.get('family_data_requests',set()):
        final_age="MAX(COALESCE(CAST(strftime('%s',reviewed_at) AS INTEGER),0),COALESCE(CAST(strftime('%s',created_at) AS INTEGER),0),COALESCE(responded_at,0),COALESCE(appeal_reviewed_at,0))<?"
        where="status IN ('closed','declined','access-approved') AND "+final_age+" AND (appealed_at IS NULL OR appeal_reviewed_at IS NOT NULL)"
        if 'privacy_submission_documents' in ts:where+=" AND NOT EXISTS(SELECT 1 FROM privacy_submission_documents d WHERE d.request_id=family_data_requests.id AND d.purged_at IS NULL)"
        add('family_data_requests',where,(now-90*DAY,))
    else:
        add('family_data_requests',"status IN ('closed','declined','access-approved') AND julianday(COALESCE(reviewed_at,created_at))<julianday(?,'unixepoch')",(now-90*DAY,))
    add('privacy_request_events','created_at<? AND (request_id IS NULL OR NOT EXISTS(SELECT 1 FROM family_data_requests r WHERE r.id=privacy_request_events.request_id))',(now-90*DAY,))
    add('privacy_upload_invites','expires_at<?',(now-7*DAY,))
    add('privacy_submission_documents','purged_at IS NOT NULL AND NOT EXISTS(SELECT 1 FROM family_data_requests r WHERE r.id=privacy_submission_documents.request_id)',())
    accounts=[]
    if 'account_safety' in ts:
        accounts=[r[0] for r in db.execute("SELECT user_id FROM account_safety WHERE deletion_requested_at IS NOT NULL AND julianday(deletion_requested_at)<=julianday(?,'unixepoch')",(now-30*DAY,))]
    pending=[r[0] for r in db.execute("SELECT id FROM users WHERE verified=0 AND julianday(created_at)<=julianday(?,'unixepoch')",(now-30*DAY,))]
    accounts=sorted(set(accounts+pending))
    # Operational owners are never removed automatically.
    accounts=[uid for uid in accounts if not ('account_disables' in ts and db.execute('SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(uid,)).fetchone()) and not ('reserved_accounts' in ts and db.execute('SELECT 1 FROM reserved_accounts WHERE user_id=?',(uid,)).fetchone()) and uid!=1 and not ('staff_roles' in ts and db.execute('SELECT 1 FROM staff_roles WHERE user_id=?',(uid,)).fetchone())]
    held={uid:erasure_blockers(db,uid) for uid in accounts}
    held={uid:why for uid,why in held.items() if why}
    accounts=[uid for uid in accounts if uid not in held]
    for table in ('post_media','post_edit_history','post_privacy','post_vibes'):
        add(table,'post_id NOT IN (SELECT id FROM posts)',())
    add('friend_requests',"status='pending' AND julianday(created_at)<julianday(?,'unixepoch')",(now-30*DAY,))
    reviews=0
    if 'closed_at' in ts.get('moderation_cases',set()):reviews=db.execute("SELECT count(*) FROM moderation_cases WHERE status='closed' AND julianday(closed_at)<=julianday(?,'unixepoch')",(now-365*DAY,)).fetchone()[0]
    return {'now':now,'accounts':accounts,'expired_records':rows,'moderation_reviews_due':reviews,'held_accounts':held}

def queue(db,path,root):
    root=Path(root).resolve(); path=Path(path)
    # Reject traversal and symlinks, including an immediate symlink parent.
    if path.is_symlink(): return
    resolved=path.resolve()
    if resolved.is_relative_to(root) and resolved!=root:
        db.execute('INSERT OR IGNORE INTO retention_file_queue(path) VALUES (?)',(str(resolved),))

def erase_account(db,uid,roots):
    why=erasure_blockers(db,uid)
    if why:raise ValueError('Account is preserved: '+'; '.join(why))
    ts=tables(db); row=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not row:return
    cols=[r[1] for r in db.execute('PRAGMA table_info(users)')]; user=dict(zip(cols,row))
    pids=[r[0] for r in db.execute('SELECT id FROM posts WHERE user_id=? OR target_user_id=?',(uid,uid))]
    cids=[r[0] for r in db.execute('SELECT id FROM comments WHERE user_id=?',(uid,))]
    if pids:
        marks=','.join('?'*len(pids)); cids += [r[0] for r in db.execute('SELECT id FROM comments WHERE post_id IN ('+marks+')',pids)]
    for value in (user.get('avatar'),user.get('avatar_path')):
        if value:
            name=avatar_filename(value)
            if name and not any(avatar_filename(v)==name for row in db.execute('SELECT avatar,avatar_path FROM users WHERE id!=?',(uid,)) for v in row if v):
                queue(db,Path(roots['avatars'])/name,roots['avatars'])
    if 'media_settings' in ts:
        media=db.execute('SELECT profile_midi FROM media_settings WHERE user_id=?',(uid,)).fetchone()
        if media and media[0] and not db.execute('SELECT 1 FROM media_settings WHERE user_id!=? AND profile_midi=?',(uid,media[0])).fetchone():queue(db,Path(roots['media'])/media[0],roots['media'])
    if 'post_media' in ts and pids:
        marks=','.join('?'*len(pids))
        for media in db.execute('SELECT filename,poster,loop_filename FROM post_media WHERE post_id IN ('+marks+')',pids).fetchall():
            for name in media:
                if name and not db.execute('SELECT 1 FROM post_media WHERE post_id NOT IN ('+marks+') AND (filename=? OR poster=? OR loop_filename=?)',pids+[name]*3).fetchone():queue(db,Path(roots['media'])/name,roots['media'])
    if 'family_consent_documents' in ts:
        # Parent departure restricts children by removing the approved relationship.
        for doc in db.execute('SELECT storage_key FROM family_consent_documents WHERE parent_id=? OR child_id=?',(uid,uid)).fetchall():queue(db,Path(roots['consent'])/doc[0],roots['consent'])
    def remove(table,column,values):
        if table in ts and column in ts[table] and values:db.execute('DELETE FROM "'+table+'" WHERE "'+column+'" IN ('+','.join('?'*len(values))+')',values)
    for table in ('post_vibes','post_privacy','post_media','post_reactions','post_edit_history','moderated_posts','protected_age_posts','staff_announcements'):remove(table,'post_id',pids)
    for table in ('moderated_comments','protected_age_comments'):remove(table,'comment_id',cids)
    if cids:
        db.execute('UPDATE comments SET parent_comment_id=NULL WHERE parent_comment_id IN ('+','.join('?'*len(cids))+')',cids)
    remove('comments','id',cids);remove('posts','id',pids)
    relationships={'friend_requests':['sender_id','receiver_id'],'follows':['follower_id','followed_id'],'top_friends':['user_id','friend_id'],'user_blocks':['user_id','target_id'],'user_mutes':['user_id','target_id'],'notifications':['user_id','actor_id'],'family_links':['parent_id','child_id'],'parent_contacts':['parent_id','child_id','peer_id'],'family_consent_documents':['parent_id','child_id']}
    for table,columns in relationships.items():
        for column in columns:remove(table,column,[uid])
    for table in ('account_safety','active_sessions','recovery_codes','password_resets','email_verifications','email_changes','account_lifecycle_events','privacy_settings','notification_settings','media_settings','profile_styles','vibe_editors','user_themes','post_reactions','authorization_post_drafts','user_moderation','account_disables','age_clocks','mail_jobs'):
        remove(table,'user_id',[uid])
    # Shared themes and restricted moderation evidence remain; erase creator linkage where nullable.
    if 'themes' in ts:db.execute('UPDATE themes SET created_by=NULL WHERE created_by=?',(uid,))
    if 'family_data_requests' in ts:db.execute("UPDATE family_data_requests SET status='closed',reviewed_at=CURRENT_TIMESTAMP WHERE child_id=? AND status='scheduled'",(uid,))
    if 'approved_payload' in ts.get('family_data_requests',set()):
        db.execute('UPDATE family_data_requests SET approved_payload=NULL,payload_sha256=NULL,authority_version=NULL,expires_at=NULL WHERE parent_id=? OR child_id=?',(uid,uid))
    remove('parent_deletion_requests','child_id',[uid])
    if 'dm_messages' in ts:
        from .messaging import erase_user
        erase_user(db,uid)
    if 'friend_labels' in ts:
        from .social_connections import erase_user as erase_connections
        erase_connections(db,uid)
    db.execute('DELETE FROM users WHERE id=?',(uid,))

def file_work(db,roots,now):
    backups=[]
    root=Path(roots['backups']).resolve()
    if root.exists():
        for path in root.glob('neonrest-*.db'):
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime<now-30*DAY:backups.append(str(path))
    documents=[]
    if 'family_consent_documents' in tables(db):
        for did,key in db.execute("SELECT d.id,d.storage_key FROM family_consent_documents d WHERE julianday(d.created_at)<julianday(?,'unixepoch') AND NOT EXISTS(SELECT 1 FROM family_links f WHERE f.parent_id=d.parent_id AND f.child_id=d.child_id AND f.status='approved')",(now-30*DAY,)):
            documents.append((did,key))
    if 'purge_after' in tables(db).get('family_consent_documents',set()):
        documents.extend((r[0],r[1]) for r in db.execute('SELECT id,storage_key FROM family_consent_documents WHERE purge_after IS NOT NULL AND purge_after<=?',(now,)))
    documents=list(dict.fromkeys(documents))
    documents=[(did,key) for did,key in documents if not any(blockers(db,uid) for row in db.execute('SELECT parent_id,child_id FROM family_consent_documents WHERE id=?',(did,)) for uid in row)]
    return backups,documents

def orphan_files(db,roots,now):
    ts=tables(db);keep_avatar=set();keep_media=set()
    for row in db.execute('SELECT avatar,avatar_path FROM users'):
        keep_avatar.update(avatar_filename(v) for v in row if v)
    if 'post_media' in ts:
        for row in db.execute('SELECT filename,poster,loop_filename FROM post_media WHERE post_id IN (SELECT id FROM posts)'):
            keep_media.update(Path(str(v)).name for v in row if v)
    if 'media_settings' in ts:
        keep_media.update(Path(str(row[0])).name for row in db.execute('SELECT profile_midi FROM media_settings') if row[0])
    result=[]
    for key,keep in [('avatars',keep_avatar),('media',keep_media)]:
        folder=Path(roots[key])
        if folder.exists():
            for path in folder.iterdir():
                if path.is_file() and not path.is_symlink() and path.name not in keep and path.stat().st_mtime<now-30*DAY:result.append((str(path),roots[key]))
    return result

def referenced(db,path,roots):
    name=path.name;parent=path.parent.resolve();ts=tables(db)
    if parent==Path(roots['avatars']).resolve():
        return any(name==avatar_filename(v) for row in db.execute('SELECT avatar,avatar_path FROM users') for v in row if v)
    if parent==Path(roots['media']).resolve():
        if 'post_media' in ts and db.execute('SELECT 1 FROM post_media WHERE post_id IN (SELECT id FROM posts) AND (filename=? OR poster=? OR loop_filename=?)',(name,name,name)).fetchone():return True
        return bool('media_settings' in ts and db.execute('SELECT 1 FROM media_settings WHERE profile_midi=?',(name,)).fetchone())
    if parent==Path(roots['consent']).resolve():return bool(db.execute('SELECT 1 FROM family_consent_documents WHERE storage_key=?',(name,)).fetchone())
    return False

def run(db,roots,apply=False,now=None):
    work=plan(db,now);backups,documents=file_work(db,roots,work['now']);orphans=orphan_files(db,roots,work['now'])
    protected=any(blockers(db,r[0]) for r in db.execute('SELECT id FROM users'))
    if protected:backups=[];orphans=[]
    summary={'accounts':len(work['accounts']),'account_ids':work['accounts'],'records':{r['table']:r['count'] for r in work['expired_records']},'orphan_files':len(orphans),'managed_backups':len(backups),'unused_consent_documents':len(documents),'moderation_reviews_due':work['moderation_reviews_due'],'mode':'apply' if apply else 'preview'}
    summary['held_accounts']=work['held_accounts'];summary['ancillary_cleanup_paused']=protected
    if 'mail_jobs' in tables(db):
        expired_mail=db.execute('SELECT count(*) FROM mail_jobs WHERE payload IS NOT NULL AND expires_at<=?',(work['now'],)).fetchone()[0]
        if expired_mail:summary['records']['mail_payloads']=expired_mail
    if not apply:return summary
    initialize(db)
    with db:
        db.execute('BEGIN IMMEDIATE')
        if 'mail_jobs' in tables(db):
            for purpose,table in [('verification','email_verifications'),('reset','password_resets'),('change','email_changes')]:
                pending='delivered=0 AND used=0' if purpose=='change' else 'used=2'
                db.execute(f'UPDATE {table} SET used=1 WHERE {pending} AND token_hash IN (SELECT token_hash FROM mail_jobs WHERE purpose=? AND expires_at<=?)',(purpose,work['now']))
            db.execute("UPDATE mail_jobs SET state='expired',payload=NULL,lease=NULL,lease_until=NULL WHERE payload IS NOT NULL AND expires_at<=?",(work['now'],))
        eligible=set(plan(db,work['now'])['accounts'])
        backups,documents=file_work(db,roots,work['now']);orphans=orphan_files(db,roots,work['now'])
        protected=any(blockers(db,r[0]) for r in db.execute('SELECT id FROM users'))
        if protected:backups=[];orphans=[]
        summary.update(managed_backups=len(backups),unused_consent_documents=len(documents),orphan_files=len(orphans))
        summary['account_ids']=[uid for uid in work['accounts'] if uid in eligible]
        summary['accounts']=len(summary['account_ids'])
        for uid in summary['account_ids']:erase_account(db,uid,roots)
        for r in ([] if protected else work['expired_records']):db.execute('DELETE FROM "'+r['table']+'" WHERE '+r['where'],r['args'])
        for name,root in orphans:queue(db,name,root)
        for path in backups:queue(db,path,roots['backups'])
        for did,key in documents:
            queue(db,Path(roots['consent'])/key,roots['consent']);db.execute('DELETE FROM family_consent_documents WHERE id=?',(did,))
        db.execute('INSERT INTO retention_runs(summary) VALUES (?)',(json.dumps(summary),))
    # File queue entries may predate a hold. Do not unlink queued evidence while any hold is active.
    if protected:
        db.commit();summary['file_errors']=0;summary['ancillary_cleanup_paused']=True;return summary
    allowed=[Path(v).resolve() for v in roots.values()]
    errors=0
    for (name,) in db.execute('SELECT path FROM retention_file_queue').fetchall():
        path=Path(name)
        if path.is_symlink() or not any(path.resolve().is_relative_to(root) and path.resolve()!=root for root in allowed):errors+=1;continue
        if referenced(db,path,roots):
            db.execute('DELETE FROM retention_file_queue WHERE path=?',(name,));continue
        try:
            path.unlink(missing_ok=True)
            db.execute('DELETE FROM retention_file_queue WHERE path=?',(name,))
            if 'backup_records' in tables(db):db.execute('DELETE FROM backup_records WHERE path=?',(name,))
        except OSError:errors+=1
    db.commit();summary['file_errors']=errors
    return summary

def storage_roots(app):
    return {'avatars':str(Path(app.static_folder)/'uploads'/'avatars'),'media':str(Path(app.instance_path)/'media'),'consent':app.config.get('FAMILY_CONSENT_FOLDER','/home/sinbot/private/neonrest_sandbox/family_consent'),'backups':str(Path(app.config['DATABASE']).parent/'sandbox_backups')}

def register_reserved_guard(app,core):
    from flask import session,redirect,url_for
    def reserved_account_guard():
        uid=session.get('user_id') or session.get('pending_login')
        if uid and core.get_db().execute('SELECT 1 FROM reserved_accounts WHERE user_id=? AND disabled=1 UNION SELECT 1 FROM account_disables WHERE user_id=? AND disabled=1',(uid,uid)).fetchone():
            session.clear()
            return redirect(url_for('login'))
    app.before_request_funcs.setdefault(None,[]).insert(0,reserved_account_guard)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    import sys
    sys.path.insert(0,'/home/sinbot')
    import neonrest_sandbox.app as core
    app=core.app
    with app.app_context():
        roots={'avatars':str(Path(app.static_folder)/'uploads'/'avatars'),'media':str(Path(app.instance_path)/'media'),'consent':app.config.get('FAMILY_CONSENT_FOLDER','/home/sinbot/private/neonrest_sandbox/family_consent'),'backups':str(Path(app.config['DATABASE']).parent/'sandbox_backups')}
        if args.apply and not app.config.get('RETENTION_ENABLED',False):parser.error('Live retention is not activated. Preview remains available.')
        print(json.dumps(run(core.get_db(),roots,args.apply),sort_keys=True))
if __name__=='__main__':main()
