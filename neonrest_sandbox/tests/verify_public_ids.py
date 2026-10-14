"""Opaque ID migration and public-surface verification; disposable data, no SMTP."""
import os,sys,sqlite3,tempfile,shutil,contextlib,io,time,re,json,hashlib
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
with tempfile.TemporaryDirectory(prefix='neonrest-public-ids-') as temp:
 root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
 for name in ('templates','routes','utils'):shutil.copytree(live/name,stage/name)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
 original={t:source.execute('SELECT * FROM '+t+' ORDER BY id').fetchall() for t in ('users','posts','comments')}
 dbpath=root/'test.db';d=sqlite3.connect(dbpath);source.backup(d)
 # Drop only cloned ID metadata to rehearse the pre-conversion migration afresh.
 for trigger, in d.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'opaque_%'").fetchall():d.execute('DROP TRIGGER '+trigger)
 for table in ('public_id_aliases','public_ids','public_id_state','public_id_migrations'):d.execute('DROP TABLE IF EXISTS '+table)
 now=int(time.time());csrf='opaque-id-test';password='Synthetic-opaque-Password123'
 owner=d.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@OpaqueOwner','opaque-owner@example.invalid',generate_password_hash(password),'1990-01-01')).lastrowid
 peer=d.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@OpaquePeer','opaque-peer@example.invalid',generate_password_hash(password),'1990-01-01')).lastrowid
 teen=d.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@OpaqueTeen','opaque-teen@example.invalid',generate_password_hash(password),'2013-01-01')).lastrowid
 admin=d.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@OpaqueAdmin','opaque-admin@example.invalid',generate_password_hash(password),'1990-01-01')).lastrowid
 d.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'admin')",(admin,));d.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?)',(admin,'JBSWY3DPEHPK3PXP'))
 oldpost=d.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Opaque migration fixture','public')",(owner,)).lastrowid
 private=d.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Private fixture','public')",(owner,)).lastrowid
 minorpost=d.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Minor fixture','public')",(teen,)).lastrowid
 d.execute("INSERT INTO post_privacy VALUES (?,'private')",(private,))
 d.execute("INSERT INTO comments(id,user_id,post_id,content) VALUES (10,?,?,'Historical ten')",(owner,oldpost));d.commit()
 before={t:d.execute('SELECT * FROM '+t+' ORDER BY id').fetchall() for t in ('users','posts','comments')}
 preserved={t:d.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in ('post_privacy','post_vibes','post_media','post_edit_history','case_evidence','moderation_cases','case_links','moderation_events')}
 d.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath);os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret');sys.path.insert(0,str(root))
 with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
 from neonrest_sandbox import public_ids as ids,community_features as cf,retention
 app=core.app;app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=False,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/')
 app.instance_path=str(root/'instance')
 core.mail.send=lambda msg:(_ for _ in ()).throw(AssertionError('No SMTP authorized in ID tests'))
 with app.app_context():
  db=core.get_db()
  check(all(before[t]==[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY id')] for t in before),'Migration preserves every original content/user field')
  check(all(preserved[t]==[tuple(r) for r in db.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in preserved),'Migration preserves audiences, media, history and case evidence')
  tokens=[r[0] for r in db.execute('SELECT public_id FROM public_ids')];check(all(ids.TOKEN.fullmatch(t) for t in tokens),'Backfill uses valid random sixteen-character tokens');check(len(tokens)==len(set(tokens)),'Global token uniqueness')
  postid=ids.public(db,'post',oldpost);privateid=ids.public(db,'post',private);minorid=ids.public(db,'post',minorpost);tenid=ids.public(db,'comment',10)
  snapshot=[tuple(r) for r in db.execute('SELECT * FROM public_ids ORDER BY kind,internal_id')];ids.initialize(db);check(snapshot==[tuple(r) for r in db.execute('SELECT * FROM public_ids ORDER BY kind,internal_id')],'Repeated initialization preserves assigned IDs')
  check(ids.resolve(db,'comment','AAAAAAAA')==10,'Historical A-padded ten resolves explicitly rather than faulty arithmetic')
  sample=[ids.random_token() for _ in range(10000)];check(len(set(sample))==10000 and all(ids.TOKEN.fullmatch(t) for t in sample),'Ten thousand generated IDs satisfy format and uniqueness')
  # Prefix capacity exists but no prefix producer/authorization is enabled.
  check('prefix' in [r[1] for r in db.execute('PRAGMA table_info(public_ids)')],'Separate prefix storage reserved');check(not db.execute('SELECT 1 FROM public_ids WHERE prefix IS NOT NULL').fetchone(),'No prefix feature silently enabled')
 def client(uid=None):
  c=app.test_client()
  with c.session_transaction() as s:s['theme_csrf_token']=csrf
  if uid:
   with app.app_context():
    db=core.get_db();u=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();sid='opaque-'+str(uid);db.execute('INSERT OR REPLACE INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'opaque-tests'));db.commit()
   with c.session_transaction() as s:s.update(user_id=uid,user_email=u['email'],user_handle=u['handle'],sid=sid,fresh_at=now,factor_at=now,theme_csrf_token=csrf)
  return c
 guest=client();own=client(owner);other=client(peer);young=client(teen);staff=client(admin)
 check(guest.get('/posts/'+postid).status_code==200,'Opaque public post reads')
 old=guest.get('/posts/'+str(oldpost));check(old.status_code==302 and old.location=='/posts/'+postid,'Authorized legacy numeric link redirects to stable canonical URL')
 check(guest.get('/posts/'+str(private)).status_code==404,'Hidden legacy route does not disclose canonical ID')
 check(guest.get('/posts/'+privateid).status_code==404,'Opaque ID does not bypass private audience')
 check(young.get('/posts/'+postid).status_code==404,'Minor cannot read unrelated out-of-band adult public post')
 check(own.get('/posts/'+minorid).status_code==404 and guest.get('/posts/'+minorid).status_code==404,'Opaque ID preserves minor-content age boundary')
 check(staff.get('/posts/'+privateid).status_code==200,'Authorized staff scope still works')
 for bad in ('-1','0','999999999999999999999999999','A!A!A!A!A!A!A!1','SYS_'+postid,'BOT'+postid,postid+'!',postid.lower() if postid.lower()!=postid else postid.upper()):
  check(guest.get('/posts/'+bad).status_code==404,'Malformed/unknown/case-sensitive post rejected: '+bad[:12])
 page=own.get('/posts/'+postid).data
 check(('id="post-'+postid+'"').encode() in page,'DOM post anchor opaque');check(('name="post_id" value="'+postid+'"').encode() in page,'Reply form sends opaque post ID')
 check(('id="comment-'+tenid+'"').encode() in page,'DOM comment anchor opaque');check(b'data-legacy-anchor="comment-10"' in page,'Only historical numeric anchors retained as aliases')
 check(('/edit_post/'+postid).encode() in page and ('data-post-id="'+postid+'"').encode() in page,'Actions carry opaque post values')
 check(own.get('/posts/'+postid+'/history').status_code==200,'Opaque history reads');check(guest.get('/posts/'+privateid+'/history').status_code==404,'History audience retained')
 check(own.get('/edit_comment/AAAAAAAA').status_code==302,'Legacy comment action redirects after authorization')
 check(other.get('/report/post/'+postid).status_code==200,'Report route resolves opaque post');check(other.get('/report/comment/'+tenid).status_code==200,'Report route resolves opaque comment')
 def clear():
  with app.app_context():core.get_db().execute('DELETE FROM rate_buckets');core.get_db().commit()
 # A reviewed guardian exception keeps public IDs and data-release boundaries.
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO family_links(parent_id,child_id,status,method,reference) VALUES (?,?,'approved','trained-personnel-phone','Synthetic reviewed guardian')",(owner,teen))
  request_id=db.execute("INSERT INTO family_data_requests(parent_id,child_id,kind,status,expires_at) VALUES (?,?,'data-review','access-approved',?)",(owner,teen,now+3600)).lastrowid;db.commit()
 check(own.get('/posts/'+minorid).status_code==200,'Reviewed parent reads child by opaque ID')
 child_export=own.get('/account/family/requests/'+str(request_id)+'/download').get_json()
 check(child_export['posts'][0]['id']==minorid,'Reviewed family export uses opaque content keys')
 check(other.get('/account/family/requests/'+str(request_id)+'/download').status_code==404,'Unlinked person cannot download child export')
 with app.app_context():
  db=core.get_db();db.execute("UPDATE family_links SET status='revoked' WHERE parent_id=? AND child_id=?",(owner,teen));db.commit()
 check(own.get('/posts/'+minorid).status_code==404,'Revoked parent loses ordinary minor-content visibility')
 with app.app_context():
  db=core.get_db();db.execute('UPDATE family_data_requests SET expires_at=? WHERE id=?',(now-1,request_id));db.commit()
 check(own.get('/account/family/requests/'+str(request_id)+'/download').status_code==404,'Expired reviewed export remains inaccessible')
 # Media continues using random filenames and the unchanged internal ownership join.
 media_dir=Path(app.instance_path)/'media';media_dir.mkdir(parents=True)
 filename='f'*40+'.png';(media_dir/filename).write_bytes(b'synthetic-media')
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO post_media(post_id,kind,filename,alt_text) VALUES (?,'image',?,'Synthetic image')",(private,filename));db.commit()
 check(own.get('/media-file/'+filename).status_code==200,'Owner can retrieve private post media')
 check(guest.get('/media-file/'+filename).status_code==404 and other.get('/media-file/'+filename).status_code==404,'Opaque ID migration preserves media audience')
 clear();check(other.post('/report/post/'+postid,data={'theme_csrf_token':csrf,'reason':'Synthetic report for identifier verification'}).status_code==302,'Opaque report submission succeeds')
 with app.app_context():
  db=core.get_db();check(db.execute("SELECT target_id FROM content_reports WHERE reporter_id=? AND target_type='post'",(peer,)).fetchone()[0]==oldpost,'Report keeps correct internal target')
  evidence_before=[tuple(r) for r in db.execute('SELECT * FROM case_evidence ORDER BY id')]
  ids.initialize(db);check(evidence_before==[tuple(r) for r in db.execute('SELECT * FROM case_evidence ORDER BY id')],'Reinitialization preserves protected evidence exactly')
 check(postid.encode() in other.get('/reports/mine').data,'Member report history displays public content ID')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(owner,peer));db.commit()
 check(other.get('/posts/'+postid).status_code==404,'Blocked member cannot read canonical post')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(owner,peer));db.commit()
 clear()
 newpost=own.post('/create_post',data={'theme_csrf_token':csrf,'content':'New opaque-only post','circle':'public','audience':'public'})
 check(newpost.status_code==302,'New post creation succeeds')
 with app.app_context():
  db=core.get_db();raw=db.execute("SELECT id FROM posts WHERE content='New opaque-only post'").fetchone()[0];newid=ids.public(db,'post',raw);check(ids.TOKEN.fullmatch(newid),'New post gets random public ID');check(not db.execute("SELECT 1 FROM public_id_aliases WHERE kind='post' AND internal_id=?",(raw,)).fetchone(),'New post has no sequential public alias')
 check(guest.get('/posts/'+str(raw)).status_code==404,'Guessing new internal post number denied');check(guest.get('/posts/'+newid).status_code==200,'New canonical post reads')
 clear();response=own.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':newid,'content':'Opaque reply root'})
 check(response.status_code==201,'Reply accepts opaque post identifier');body=response.get_json();newcomment=body['id'];check(ids.TOKEN.fullmatch(newcomment) and body['post_id']==newid,'Comment JSON exposes opaque IDs only')
 with app.app_context():cr=ids.resolve(core.get_db(),'comment',newcomment)
 clear();response=own.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':newid,'parent_comment_id':newcomment,'content':'Opaque nested reply'})
 check(response.status_code==201 and response.get_json()['parent_comment_id']==newcomment,'Nested reply uses opaque parent');nested=response.get_json()['id']
 with app.app_context():check(core.get_db().execute('SELECT parent_comment_id FROM comments WHERE id=?',(ids.resolve(core.get_db(),'comment',nested),)).fetchone()[0]==cr,'Database parent stays integer and correct')
 clear();check(own.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':postid,'parent_comment_id':newcomment,'content':'Wrong post parent'}).status_code==404,'Cross-post parent rejected')
 clear();check(other.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':privateid,'content':'Private bypass'}).status_code==404,'Reply permission cannot be bypassed by opaque ID')
 clear();check(young.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':newid,'content':'Age bypass'}).status_code in (403,404),'Reply age boundary preserved')
 clear();check(own.post('/react/'+newid,data={'theme_csrf_token':csrf,'emoji':'👍'}).status_code in (200,302),'Reaction resolves opaque post ID')
 clear();check(own.post('/edit_comment/'+newcomment,data={'theme_csrf_token':csrf,'content':'Edited opaque root'}).status_code==302,'Opaque comment edit succeeds')
 with app.app_context():check(core.get_db().execute('SELECT content FROM comments WHERE id=?',(cr,)).fetchone()[0]=='Edited opaque root','Correct comment edited')
 clear();other.post('/edit_comment/'+newcomment,data={'theme_csrf_token':csrf,'content':'Unauthorized edit'})
 with app.app_context():check(core.get_db().execute('SELECT content FROM comments WHERE id=?',(cr,)).fetchone()[0]=='Edited opaque root','Other owner cannot edit comment')
 clear();response=own.post('/edit_post/'+newid,data={'theme_csrf_token':csrf,'content':'Edited opaque post','vibes':'','circle':'public','audience':'public'});check(response.status_code==302,'Opaque post edit succeeds')
 check(b'New opaque-only post' in own.get('/posts/'+newid+'/history').data,'History preserves original version')
 # Notification storage, listing, and export canonicalize without revealing raw new keys.
 clear();response=other.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':newid,'content':'Notification probe'});check(response.status_code==201,'Peer comment creates notification');peercomment=response.get_json()['id']
 with app.app_context():
  db=core.get_db();notice=db.execute("SELECT * FROM notifications WHERE user_id=? AND kind='comments' ORDER BY id DESC LIMIT 1",(owner,)).fetchone();check(notice['path']=='/posts/'+newid+'#comment-'+peercomment,'New notification stores canonical post/comment IDs');check(cf.notification_visible(db,notice,owner),'Notification eligibility resolves opaque IDs')
 check((newid+'#comment-'+peercomment).encode() in own.get('/notifications').data,'Notification inbox keeps deep link')
 clear();export=own.post('/account/export',data={'theme_csrf_token':csrf}).get_json();check(export['content_id_format']=='random-base62-v1','Export declares identifier format');check(all(isinstance(p['id'],str) and ids.TOKEN.fullmatch(p['id']) for p in export['posts']),'Export post keys opaque');check(all(isinstance(c['id'],str) and ids.TOKEN.fullmatch(c['id']) for c in export['comments']),'Export comment keys opaque');check(any(c['parent_comment_id']==newcomment for c in export['comments'] if c['id']==nested),'Export parent references stay connected')
 check(staff.get('/manage/posts?q='+newid).status_code==200,'Staff post search accepts public ID');check(b'Edited opaque post' in staff.get('/manage/posts?q='+newid).data,'Staff search finds correct public ID')
 check(staff.get('/manage/comments?q='+newcomment).status_code==200,'Staff comment search accepts public ID')
 # Force a token collision and verify bounded retry rather than incorrect attachment.
 with app.app_context():
  db=core.get_db();extra=db.execute("INSERT INTO comments(user_id,post_id,content) VALUES (?,?,'Collision fixture')",(owner,raw)).lastrowid;fresh='AbCdEfGhIjKlMnOp'
  with patch.object(ids,'random_token',side_effect=[newid,fresh]):check(ids.ensure(db,'comment',extra)==fresh,'Database token collision retries safely')
  db.commit();check(ids.resolve(db,'post',newid)==raw,'Collision does not steal existing public identity')
  exhausted=db.execute("INSERT INTO comments(user_id,post_id,content) VALUES (?,?,'Bounded collision fixture')",(owner,raw)).lastrowid
  try:
   with patch.object(ids,'random_token',return_value=newid):ids.ensure(db,'comment',exhausted)
  except RuntimeError:check(True,'Repeated token collisions fail within the bounded retry limit')
  else:raise AssertionError('Collision retry failed to stop')
  check(not db.execute("SELECT 1 FROM public_ids WHERE kind='comment' AND internal_id=?",(exhausted,)).fetchone(),'Exhausted collision cannot attach the wrong ID')
  db.execute('DELETE FROM comments WHERE id=?',(exhausted,));db.commit()
 # Deletion cleanup and allocator prevent numeric-key reuse in normal creation.
 clear();check(own.post('/delete_comment/'+nested,data={'theme_csrf_token':csrf}).status_code==302,'Opaque comment delete succeeds')
 with app.app_context():
  db=core.get_db();check(not db.execute('SELECT 1 FROM public_ids WHERE public_id=?',(nested,)).fetchone(),'Deleted comment mapping cleared')
 clear();check(own.post('/delete_post/'+newid,data={'theme_csrf_token':csrf}).status_code==302,'Opaque post delete succeeds');check(guest.get('/posts/'+newid).status_code==404,'Deleted public post stays unavailable')
 clear();check(own.post('/create_post',data={'theme_csrf_token':csrf,'content':'After deletion','circle':'public','audience':'public'}).status_code==302,'New post after deletion succeeds')
 with app.app_context():
  db=core.get_db();newraw=db.execute("SELECT id FROM posts WHERE content='After deletion'").fetchone()[0];check(newraw>raw,'Deleted highest post key is not reused')
  check(not db.execute("SELECT 1 FROM public_id_aliases WHERE kind='post' AND internal_id=?",(newraw,)).fetchone(),'New post still has no legacy alias')
  check(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','Final schema integrity')
 # Raw SQLite retention connections must run mapping cleanup without Python UDFs.
 d=sqlite3.connect(dbpath)
 victim=d.execute("INSERT INTO users(handle,email,password_hash,dob,verified) VALUES ('@OpaqueErase','opaque-erase@example.invalid','unused','1990-01-01',1)").lastrowid
 vp=d.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'Erase fixture','public')",(victim,)).lastrowid
 vc=d.execute("INSERT INTO comments(user_id,post_id,content) VALUES (?,?,'Erase reply')",(victim,vp)).lastrowid
 vpid=ids.ensure(d,'post',vp);vcid=ids.ensure(d,'comment',vc)
 retention.erase_account(d,victim,{name:str(root/name) for name in ('avatars','media','consent')});d.commit()
 check(not d.execute('SELECT 1 FROM public_ids WHERE public_id IN (?,?)',(vpid,vcid)).fetchone(),'Raw retention erasure removes post and comment mappings')
 check(d.execute("SELECT highest_key FROM public_id_state WHERE kind='post'").fetchone()[0]>=vp,'Retention keeps allocation high-water mark')
 d.close();check(guest.get('/posts/'+vpid).status_code==404,'Erased opaque post cannot resolve')
 # An ambiguous historical label fails the entire migration instead of guessing.
 c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE posts(id INTEGER PRIMARY KEY);CREATE TABLE comments(id INTEGER PRIMARY KEY);INSERT INTO comments VALUES(1);INSERT INTO comments VALUES(621);')
 try:ids.initialize(c);failed=False
 except RuntimeError:failed=True
 check(failed,'Ambiguous preexisting legacy labels block migration');check(not c.execute("SELECT 1 FROM sqlite_master WHERE name='public_ids'").fetchone(),'Failed migration rolls back new schema');c.close()
 check(all(source.execute('SELECT * FROM '+t+' ORDER BY id').fetchall()==original[t] for t in original),'Live user/post/comment data unchanged');source.close()
print('PASS:',checks,'isolated public-ID checks; no SMTP or production changes')
