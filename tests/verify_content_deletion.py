"""Real routes and integrity checks against disposable database backups only."""
from pathlib import Path
import sys,os,json,socket,smtplib,urllib.request
def forbidden(*a,**kw):raise AssertionError('Network forbidden in deletion fixtures')
smtplib.SMTP=smtplib.SMTP_SSL=urllib.request.urlopen=forbidden
import requests
requests.sessions.Session.request=forbidden
bootstrap=(Path(sys.argv[2])/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
bootstrap=bootstrap.replace("'MAIL_QUEUE':'0'", "'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')")
exec(compile(bootstrap,'disposable deletion bootstrap','exec'))
from unittest.mock import patch
deletion=importlib.import_module(package+'.content_deletion')
def send(who,path,**data):return clients[who].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)
def public(kind,key):
 with app.app_context():return core.identifiers.public(core.get_db(),kind,key)
def comment(pid,who='Writer',parent=None,text='FICTIONAL deletion fixture'):
 return change('INSERT INTO comments(post_id,user_id,content,parent_comment_id) VALUES (?,?,?,?)',(pid,users[who],text,parent))
def violations():
 with app.app_context():return set(tuple(r) for r in core.get_db().execute('PRAGMA foreign_key_check'))
baseline=violations()
original_get_db=core.get_db
def strict_db():
 db=original_get_db();db.execute('PRAGMA foreign_keys='+('OFF' if os.environ.get('DELETION_FIXTURE_FK')=='off' else 'ON'));return db
with patch.object(core,'get_db',side_effect=strict_db):
 pid,ref=post_fixture('FICTIONAL threaded deletion fixture')
 root=comment(pid);middle=comment(pid,parent=root);child=comment(pid,'Regular',middle)
 child_ref=public('comment',child);middle_ref=public('comment',middle)
 check(send('Regular','/delete_comment/'+middle_ref).status_code==302,'Nonowner deletion denied without changing content')
 check(query('SELECT 1 FROM comments WHERE id=?',(middle,)),'Nonowner cannot remove parent')
 check(clients['Writer'].post('/delete_comment/'+middle_ref,data={},environ_overrides=env).status_code==400,'CSRF still required')
 check(send('Writer','/delete_comment/'+middle_ref).status_code==302,'Owner can delete middle comment')
 check(query('SELECT parent_comment_id,content FROM comments WHERE id=?',(child,))[0][0]==root,'Reply reparented to surviving grandparent')
 check(public('comment',child)==child_ref,'Other authors retain reply and public ID')
 check(violations()==baseline,'Comment deletion introduces no FK violation')
 check(send('Writer','/delete_comment/'+public('comment',root)).status_code==302,'Owner can delete root comment')
 check(query('SELECT parent_comment_id FROM comments WHERE id=?',(child,))[0][0] is None,'Surviving reply becomes root when no ancestor remains')
 parent=comment(pid);reply=comment(pid,'Regular',parent)
 change("INSERT INTO circle_content_removals(circle_id,target_type,target_id,report_id,removed_by) VALUES (1,'comment',?,999,?)",(parent,users['Admin']))
 check(send('Writer','/delete_comment/'+public('comment',parent)).status_code==409,'Moderated ancestor cannot expose hidden descendants')
 check(query('SELECT parent_comment_id FROM comments WHERE id=?',(reply,))[0][0]==parent,'Denied moderation deletion rolls back')
 change("DELETE FROM circle_content_removals WHERE target_type='comment' AND target_id=?",(parent,))
 hold=change('INSERT INTO privacy_holds(user_id,reason,legal_basis,reference,reviewer_id,created_at,review_due) VALUES (?,?,?,?,?,?,?)',(users['Writer'],'Fixture','Fixture','Fixture',users['Admin'],now,now+3600))
 check(send('Writer','/delete_post/'+ref).status_code==409,'Active hold blocks post deletion')
 check(query('SELECT 1 FROM posts WHERE id=?',(pid,)),'Held post remains')
 change('UPDATE privacy_holds SET released_at=? WHERE id=?',(now,hold))
 change("INSERT INTO post_reactions(post_id,user_id,emoji) VALUES (?,?,'heart')",(pid,users['Regular']))
 change('INSERT INTO post_bookmarks(user_id,post_id) VALUES (?,?)',(users['Regular'],pid))
 share,share_ref=post_fixture('FICTIONAL unrelated share wrapper')
 change('INSERT INTO post_shares(share_post_id,source_post_id) VALUES (?,?)',(share,pid))
 cid=change("INSERT INTO circles(name,description,owner_id,mode,pinned_post_id) VALUES ('Fixture deletion','','%d','hidden',?)"%users['Writer'],(pid,))
 change('INSERT INTO circle_posts(post_id,circle_id) VALUES (?,?)',(pid,cid))
 # Fail after several cleanup statements, proving the route rolls all of them back.
 change("CREATE TRIGGER fixture_delete_failure BEFORE DELETE ON posts WHEN OLD.id=%d BEGIN SELECT RAISE(ABORT,'fixture failure'); END"%pid)
 try:send('Writer','/delete_post/'+ref);check(False,'Injected failure must abort')
 except Exception as e:check('fixture failure' in str(e),'Injected deletion failure reached route')
 check(query('SELECT 1 FROM comments WHERE id=?',(child,)) and query('SELECT 1 FROM post_reactions WHERE post_id=?',(pid,)),'Failed deletion retains children and reactions')
 change('DROP TRIGGER fixture_delete_failure')
 check(send('Regular','/delete_post/'+ref).status_code==302 and query('SELECT 1 FROM posts WHERE id=?',(pid,)),'Other user cannot delete post')
 check(send('Writer','/delete_post/'+ref).status_code==302,'Owner removes post and thread atomically with FK enforcement')
 for table in ['comments','post_reactions','post_vibes','post_bookmarks','circle_posts']:
  check(not query('SELECT 1 FROM '+table+' WHERE post_id=?',(pid,)),'Dependent rows removed: '+table)
 check(query('SELECT pinned_post_id FROM circles WHERE id=?',(cid,))[0][0] is None,'Deleted post unpinned')
 check(query('SELECT 1 FROM posts WHERE id=?',(share,)),'Other authors share wrapper retained')
 check(query('SELECT source_post_id FROM post_shares WHERE share_post_id=?',(share,))[0][0]==pid,'Share retains unavailable-source attribution')
 check(not query("SELECT 1 FROM public_ids WHERE kind='post' AND internal_id=?",(pid,)),'Deleted post opaque ID retired by existing trigger')
 check(violations()==baseline,'Post deletion introduces no FK violations')
check(app.config.get('RETENTION_ENABLED') is False,'Automatic account erasure remains disabled')
print(json.dumps({'checks':checks,'passed':True,'scope':'real deletion routes; FK on; disposable copy; no live writes'}))
