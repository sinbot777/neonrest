"""Minor reader boundaries: isolated database/source, strict opaque IDs, no SMTP."""
import os,sys,sqlite3,tempfile,shutil,contextlib,io,time
from pathlib import Path
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
with tempfile.TemporaryDirectory(prefix='neonrest-minor-reading-') as temp:
 root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
 for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
 for name in ('templates','routes','utils'):shutil.copytree(live/name,stage/name)
 (stage/'static').symlink_to(live/'static',target_is_directory=True)
 source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
 original={t:source.execute('SELECT * FROM '+t+' ORDER BY id').fetchall() for t in ('users','posts','comments')}
 dbpath=root/'test.db';d=sqlite3.connect(dbpath);source.backup(d);d.close()
 os.environ['NEONREST_SANDBOX_DATABASE']=str(dbpath);os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret');sys.path.insert(0,str(root))
 with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
 from neonrest_sandbox import age_policy as ages,community_features as cf,public_ids as ids
 app=core.app;app.instance_path=str(root/'instance');app.config.update(TESTING=True,PUBLIC_ID_TEST_ALIASES=False,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/')
 core.mail.send=lambda m:(_ for _ in ()).throw(AssertionError('No SMTP in age-reading tests'))
 now=int(time.time());csrf='minor-reading';people={};posts={};tokens={}
 with app.app_context():
  db=core.get_db()
  for label,a in [('child',10),('thirteen',13),('fifteen',15),('sixteen',16),('seventeen',17),('eighteen',18),('twenty',20),('twentyone',21),('parent',40),('outsider',40),('staff',40)]:
   uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@Read'+label,label+'@reading.example.invalid','unused',str(time.gmtime().tm_year-a)+'-01-01')).lastrowid;people[label]=(uid,a)
   pid=db.execute('INSERT INTO posts(user_id,content,circle) VALUES (?,?,?)',(uid,'READMARK_'+label,'public')).lastrowid;posts[label]=pid;tokens[label]=ids.ensure(db,'post',pid)
   db.execute('INSERT INTO post_privacy VALUES (?,?)',(pid,'public'))
  parent=people['parent'][0];child=people['child'][0];minor=people['thirteen'][0];staff=people['staff'][0]
  for uid in (child,minor):db.execute("INSERT INTO family_links(parent_id,child_id,status,method) VALUES (?,?,'approved','trained-personnel-phone')",(parent,uid))
  db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'admin')",(staff,));db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?)',(staff,'JBSWY3DPEHPK3PXP'))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(minor,people['fifteen'][0]))
  db.execute("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(minor,people['outsider'][0]))
  db.execute('INSERT INTO staff_announcements VALUES (?)',(posts['staff'],))
  db.execute("INSERT INTO post_edit_history(post_id,content,circle) VALUES (?,'READHISTORY_outsider','public')",(posts['outsider'],))
  vibe=db.execute("SELECT id FROM vibes WHERE name='Fresh Starts'").fetchone()[0]
  for pid in posts.values():db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,vibe))
  reply_ids={}
  for label in ('parent','fifteen','outsider'):
   cid=db.execute('INSERT INTO comments(user_id,post_id,content) VALUES (?,?,?)',(people[label][0],posts['parent'],'READREPLY_'+label)).lastrowid;reply_ids[label]=ids.ensure(db,'comment',cid)
  filename='d'*40+'.png';folder=Path(app.instance_path)/'media';folder.mkdir(parents=True);(folder/filename).write_bytes(b'isolated-age-media')
  db.execute("INSERT INTO post_media(post_id,kind,filename,alt_text) VALUES (?,'image',?,'Minor reader test')",(posts['outsider'],filename))
  db.commit()
  # Both directions, including adult/minor boundaries, verified family and staff.
  for owner,(uid,oa) in people.items():
   for viewer,(vid,va) in people.items():
    expected=viewer=='staff' or uid==vid or (oa>=18 and va>=18) or abs(oa-va)<=3 or ({owner,viewer} in ({'parent','child'},{'parent','thirteen'}))
    check(ages.can_read(db,uid,vid)==expected,'Read eligibility '+owner+' -> '+viewer)
  check(ages.can_read(db,people['outsider'][0],None),'Guest adult public access unchanged')
  check(not ages.can_read(db,minor,None),'Guest minor content remains hidden')
 def client(label):
  uid=people[label][0];c=app.test_client();sid='read-'+label
  with app.app_context():
   db=core.get_db();u=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'minor-reader'));db.commit()
  with c.session_transaction() as s:s.update(user_id=uid,user_email=u['email'],user_handle=u['handle'],sid=sid,fresh_at=now,factor_at=now,theme_csrf_token=csrf)
  return c
 clients={label:client(label) for label in people};young=clients['thirteen'];staff_client=clients['staff']
 for owner,status in [('parent',200),('fifteen',200),('sixteen',200),('seventeen',404),('twenty',404),('outsider',404),('staff',200)]:
  check(young.get('/posts/'+tokens[owner]).status_code==status,'Direct post '+owner)
 check(clients['child'].get('/posts/'+tokens['parent']).status_code==200,'Existing under-13 linked child reads parent')
 check(clients['seventeen'].get('/posts/'+tokens['twenty']).status_code==200,'17 to 20 remains allowed')
 check(clients['seventeen'].get('/posts/'+tokens['twentyone']).status_code==404,'17 to 21 remains denied')
 check(staff_client.get('/posts/'+tokens['thirteen']).status_code==200,'Staff safety review scope preserved')
 check(young.get('/posts/'+tokens['outsider']+'/history').status_code==404,'Out-of-band adult history denied')
 check(young.get('/posts/'+tokens['parent']+'/history').status_code==200,'Linked parent history permitted')
 check(young.get('/media-file/'+filename).status_code==404,'Out-of-band adult attachment denied')
 check(clients['outsider'].get('/media-file/'+filename).status_code==200,'Attachment owner retains access')
 for path in ('/feed','/vibe/Fresh%20Starts','/@Readoutsider'):
  page=young.get(path).data
  check(b'READMARK_outsider' not in page and b'READHISTORY_outsider' not in page,'No adult post leakage through '+path)
 parent_page=young.get('/posts/'+tokens['parent']).data
 check(b'READREPLY_parent' in parent_page and b'READREPLY_fifteen' in parent_page,'Parent and nearby replies visible')
 check(b'READREPLY_outsider' not in parent_page,'Adult reply hidden even on allowed parent post')
 check(young.post('/create_comment',data={'theme_csrf_token':csrf,'post_id':tokens['parent'],'parent_comment_id':reply_ids['outsider'],'content':'Disallowed adult reply target'}).status_code==404,'Minor cannot reply to hidden adult reply')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM staff_announcements WHERE post_id=?',(posts['staff'],));db.commit()
 check(young.get('/posts/'+tokens['staff']).status_code==404,'Staff author role alone does not expose an ordinary adult post')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO staff_announcements VALUES (?)',(posts['staff'],));db.commit()
 with app.app_context():
  db=core.get_db()
  for label,path in [('outsider','/posts/'+tokens['outsider']),('parent','/posts/'+tokens['parent']),('reply','/posts/'+tokens['parent']+'#comment-'+reply_ids['outsider'])]:
   rid=db.execute("INSERT INTO notifications(user_id,kind,message,path) VALUES (?,'comments',?,?)",(minor,'READNOTICE_'+label,path)).lastrowid;db.commit()
   row=db.execute('SELECT * FROM notifications WHERE id=?',(rid,)).fetchone();check(cf.notification_visible(db,row,minor)==(label=='parent'),'Notification visibility '+label)
 page=young.get('/notifications').data;check(b'READNOTICE_parent' in page and b'READNOTICE_outsider' not in page and b'READNOTICE_reply' not in page,'Notification inbox filters adult posts and replies')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(minor,parent));db.commit()
 check(young.get('/posts/'+tokens['parent']).status_code==404,'Block overrides linked parent exception')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(minor,parent));db.execute("UPDATE post_privacy SET audience='private' WHERE post_id=?",(posts['parent'],));db.commit()
 check(young.get('/posts/'+tokens['parent']).status_code==404,'Parent exception does not expose self-only posts')
 with app.app_context():
  db=core.get_db();db.execute("UPDATE post_privacy SET audience='public' WHERE post_id=?",(posts['parent'],));db.execute("UPDATE family_links SET status='revoked' WHERE parent_id=? AND child_id=?",(parent,minor));db.commit()
 check(young.get('/posts/'+tokens['parent']).status_code==404,'Revoked parent link ends adult post exception')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(posts['staff'],staff,staff,'Synthetic hide'));db.commit()
 check(young.get('/posts/'+tokens['staff']).status_code==404,'Moderation overrides announcement exception')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM moderated_posts WHERE post_id=?',(posts['staff'],));db.execute("UPDATE post_privacy SET audience='private' WHERE post_id=?",(posts['staff'],));db.commit()
 check(young.get('/posts/'+tokens['staff']).status_code==404,'Private flag invalidates public staff announcement')
 # Profile visibility uses the same age boundary, with a limited staff identity view.
 with app.app_context():
  db=core.get_db();db.execute("UPDATE family_links SET status='approved' WHERE parent_id=? AND child_id=?",(parent,minor));db.commit()
  for owner,(uid,oa) in people.items():
   for viewer,(vid,va) in people.items():
    expected=viewer=='staff' or owner=='staff' or uid==vid or (oa>=18 and va>=18) or abs(oa-va)<=3 or ({owner,viewer} in ({'parent','child'},{'parent','thirteen'}))
    check(cf.member_visible(db,uid,vid)==expected,'Profile eligibility '+owner+' -> '+viewer)
  check(not ages.can_read(db,people['outsider'][0],minor,profile=True),'Adult-public profile does not bypass minor age gate')
  check(ages.can_read(db,people['outsider'][0],None,profile=True),'Guest adult public profile preserved')
  check(not ages.can_read(db,minor,None,profile=True),'Guest minor profile denied')
 for viewer,targets in [('thirteen',[('parent',200),('fifteen',200),('sixteen',200),('seventeen',404),('twenty',404),('outsider',404),('staff',200)]),('seventeen',[('twenty',200),('twentyone',404),('thirteen',404),('staff',200)]),('child',[('parent',200),('thirteen',200),('fifteen',404),('staff',200)])]:
  for owner,status in targets:
   uid=people[owner][0]
   for path in ('/@Read'+owner,'/user_test/'+str(uid),'/user/'+str(uid)):
    response=clients[viewer].get(path,follow_redirects=True)
    check(response.status_code==status,'Profile route '+viewer+' -> '+path)
    check('no-store' in response.headers.get('Cache-Control',''),'Profile response cannot be cached '+path)
 with app.app_context():
  db=core.get_db();outsider=people['outsider'][0]
  db.execute('INSERT OR REPLACE INTO top_friends VALUES (?,?,1)',(minor,outsider));db.execute('INSERT OR REPLACE INTO top_friends VALUES (?,?,2)',(minor,people['fifteen'][0]));db.commit()
 for path in ('/@Readthirteen','/friends','/friends/Readthirteen'):
  page=young.get(path).data
  check(b'Readoutsider' not in page,'Friend listing suppresses out-of-band account '+path)
  check(b'Readfifteen' in page,'Friend listing keeps eligible account '+path)
 check(young.get('/friends/Readoutsider').status_code==404,'Out-of-band public friend list denied')
 check(young.get('/friends/Readstaff').status_code==404,'Staff identity exception does not expose connections')
 with app.app_context():
  db=core.get_db();db.execute("UPDATE users SET bio='STAFF_PRIVATE_BIO',location='STAFF_PRIVATE_LOCATION',lastfm_username='staff-private-music' WHERE id=?",(staff,))
  db.execute("INSERT OR REPLACE INTO profile_styles(user_id,mode,custom_css) VALUES (?,'day','body { --staff-marker: STAFF_PRIVATE_CSS; }')",(staff,));db.commit()
 page=young.get('/@Readstaff?mode=day').data
 check(b'Administrator' in page and b'Report profile' in page,'Minor sees authenticated staff identity and reporting')
 check(all(marker not in page for marker in (b'STAFF_PRIVATE_BIO',b'STAFF_PRIVATE_LOCATION',b'STAFF_PRIVATE_CSS',b'staff-private-music',b'Top 9 Friends',b'Sign Guestbook',b'Recent Posts')),'Limited staff view excludes personal profile, activity and contact forms')
 check(young.get('/now_playing/staff-private-music').status_code==404,'Limited staff identity cannot expose live music')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM staff_roles WHERE user_id=?',(staff,));db.commit()
 check(young.get('/@Readstaff').status_code==404,'Staff demotion ends profile exception immediately')
 with app.app_context():
  db=core.get_db();db.execute("INSERT INTO staff_roles(user_id,role) VALUES (?,'moderator')",(staff,));db.commit()
 check(b'Moderator' in young.get('/@Readstaff').data,'Moderator role gets limited staff identity view')
 with app.app_context():
  db=core.get_db();db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(minor,staff));db.commit()
 check(young.get('/@Readstaff').status_code==404,'Block overrides staff target exception')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(minor,staff));db.execute("INSERT OR REPLACE INTO privacy_settings(user_id,profile_audience) VALUES (?,'private')",(staff,));db.commit()
 check(young.get('/@Readstaff').status_code==404,'Private audience overrides staff target exception')
 with app.app_context():
  db=core.get_db();db.execute("UPDATE privacy_settings SET profile_audience='public' WHERE user_id=?",(staff,));db.execute('INSERT OR REPLACE INTO account_disables(user_id,disabled,reason) VALUES (?,1,?)',(staff,'isolated test'));db.commit()
 check(young.get('/@Readstaff').status_code==404,'Disabled staff profile remains hidden')
 with app.app_context():
  db=core.get_db();db.execute('DELETE FROM account_disables WHERE user_id=?',(staff,));db.execute('INSERT OR REPLACE INTO account_safety(user_id,inactive) VALUES (?,1)',(staff,));db.commit()
 check(young.get('/@Readstaff').status_code==404,'Deactivated staff profile remains hidden')
 with app.app_context():
  db=core.get_db();db.execute('UPDATE account_safety SET inactive=0 WHERE user_id=?',(staff,));db.execute("UPDATE family_links SET status='revoked' WHERE parent_id=? AND child_id=?",(parent,minor));db.commit()
 check(young.get('/@Readparent').status_code==404,'Parent revocation ends profile access immediately')
 # Direct profile files also enforce age policy; all fixtures are disposable.
 app.static_folder=str(root/'profile-static');avatar_dir=Path(app.static_folder)/'uploads'/'avatars';avatar_dir.mkdir(parents=True)
 for label in ('outsider','fifteen','staff'):
  uid=people[label][0];name='user_'+str(uid)+'_avatar.png';(avatar_dir/name).write_bytes(b'avatar-fixture')
  check(young.get('/static/uploads/avatars/'+name).status_code==(404 if label=='outsider' else 200),'Avatar boundary '+label)
 midi='e'*40+'.mid';(folder/midi).write_bytes(b'profile-midi-fixture')
 with app.app_context():
  db=core.get_db();db.execute('INSERT OR REPLACE INTO media_settings(user_id,profile_midi) VALUES (?,?)',(staff,midi));db.commit()
 check(young.get('/media-file/'+midi).status_code==404,'Limited staff identity cannot expose personal MIDI')
 check(clients['eighteen'].get('/media-file/'+midi).status_code==200,'Adult retains public staff MIDI access')
 with app.app_context():
  db=core.get_db();uid=people['twenty'][0];viewer=people['seventeen'][0]
  from neonrest_sandbox import age_clock
  original_date_for=age_clock.date_for
  from datetime import date
  try:
   age_clock.date_for=lambda db_,uid_:date(time.gmtime().tm_year+1,1,1) if uid_==uid else original_date_for(db_,uid_)
   check(not cf.member_visible(db,uid,viewer),'Birthday ending three-year eligibility hides profile immediately')
  finally:age_clock.date_for=original_date_for
 check(all(source.execute('SELECT * FROM '+t+' ORDER BY id').fetchall()==original[t] for t in original),'Live users, posts and comments preserved');source.close()
print('PASS:',checks,'isolated minor-reading checks; no SMTP or production writes')
