"""T40/T41/T43 integration against a disposable database; no outgoing mail."""
from pathlib import Path
import sys,importlib,os,re
from urllib.parse import urlencode
from flask import template_rendered
stage=Path(sys.argv[2]);bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone',1)[0]
exec(compile(bootstrap,'isolated_discovery_fixture','exec'))
welcome=importlib.import_module(package+'.welcome');helpers=importlib.import_module(package+'.utils.friend_helpers')
# Founder setup and friendship changes occur only in this disposable database.
change("UPDATE users SET handle='@brendoom' WHERE id=1")
for who in ['Regular','Teen']:
 uid=users[who]
 with app.app_context():
  db=core.get_db();welcome.add_welcome_friend(db,uid);welcome.add_welcome_friend(db,uid);db.commit()
 check(len(query("SELECT 1 FROM friend_requests WHERE sender_id=1 AND receiver_id=? AND status='accepted'",(uid,)))==1,'Welcome friendship idempotent '+who)
 check(query('SELECT position_t9 FROM top_friends WHERE user_id=? AND friend_id=1',(uid,))[0][0]==1,'Welcome first Top 9 '+who)
 check(get(who,'/@brendoom').status_code==200,'Welcome support profile visible '+who)
 with clients[who].session_transaction() as s:s['friend_csrf_token']='fictional-friend-csrf'
 r=clients[who].post('/update_top9',data={'friend_csrf_token':'fictional-friend-csrf','slot_4':'1'},environ_overrides=env)
 check(r.status_code==302,'Move welcome Top 9 '+who)
 check(query('SELECT position_t9 FROM top_friends WHERE user_id=? AND friend_id=1',(uid,))[0][0]==4,'Moved position saved '+who)
 r=clients[who].post('/update_top9',data={'friend_csrf_token':'fictional-friend-csrf'},environ_overrides=env);check(r.status_code==302,'Remove from Top 9 '+who)
 check(not query('SELECT 1 FROM top_friends WHERE user_id=? AND friend_id=1',(uid,)),'Top 9 entry absent '+who)
 check(query("SELECT 1 FROM friend_requests WHERE sender_id=1 AND receiver_id=? AND status='accepted'",(uid,)),'Top 9 removal preserves friendship '+who)
 r=clients[who].post('/remove_friend/1',data={'friend_csrf_token':'fictional-friend-csrf'},environ_overrides=env);check(r.status_code==302,'Remove welcome friendship '+who)
 for path in ['/feed','/friends','/@brendoom']:get(who,path)
 check(not query("SELECT 1 FROM friend_requests WHERE sender_id=1 AND receiver_id=? AND status='accepted'",(uid,)),'Visits do not restore friendship '+who)
# Explicit staff support identity does not grant a minor ordinary adult content.
pid,ref=post_fixture('ADULT PERSONAL ONBOARDING SENTINEL');change('UPDATE posts SET user_id=1 WHERE id=?',(pid,))
check(get('Teen','/posts/'+ref).status_code==404,'Welcome friendship never bypasses age reading')
change('UPDATE account_disables SET disabled=1 WHERE user_id=1')
if not query('SELECT 1 FROM account_disables WHERE user_id=1'):change('INSERT INTO account_disables(user_id,disabled) VALUES(1,1)')
with app.app_context():db=core.get_db();welcome.add_welcome_friend(db,users['OtherManager']);db.commit()
check(not query("SELECT 1 FROM friend_requests WHERE sender_id=1 AND receiver_id=?",(users['OtherManager'],)),'Unavailable founder not auto-added')
change('UPDATE account_disables SET disabled=0 WHERE user_id=1')
# New Vibes: distinct authors, repeated tags, alternate spelling, threshold and manual approval.
name='Discovery Fixture New Vibe'
def tag(who,name):
 pid,_=post_fixture('T41 FICTIONAL TAG');change('UPDATE posts SET user_id=? WHERE id=?',(users[who],pid))
 with app.app_context():db=core.get_db();life.add_post_vibes(db,pid,[name]);db.commit();v=life.canonical_vibe(db,name);return v['id']
old=os.environ.pop('VIBE_CREATION_MIN_USERS',None)
check(life.minimum_users()==3,'Default exactly three distinct taggers')
v=tag('Writer',name)
for alias in ['#DiscoveryFixtureNewVibe','DISCOVERY FIXTURE NEW VIBE','discovery-fixture-new-vibe']:check(tag('Writer',alias)==v,'Canonical alias deduplicated')
with app.app_context():db=core.get_db();check(life.supporter_count(db,v)==1 and life.is_pending(db,v),'One author repeated is still pending')
tag('Regular',name)
check(query('SELECT 1 FROM pending_vibes WHERE vibe_id=?',(v,)),'Two authors pending')
tag('Manager',name)
check(not query('SELECT 1 FROM pending_vibes WHERE vibe_id=?',(v,)),'Third distinct author promotes')
check(get('Regular','/vibe/'+name).status_code==200,'Promoted Vibe renders without a custom theme')
r=get('Regular','/vibe/DiscoveryFixtureNewVibe',mode='night');check(r.status_code==302 and 'mode=night' in r.location and 'Discovery' in r.location,'Alternate spelling resolves canonical URL with mode')
v2=tag('Writer','Discovery Fixture Manual')
with app.app_context():db=core.get_db();check(life.approve_vibe(db,v2),'Manual approval removes pending');check(not life.approve_vibe(db,v2),'Approval idempotent');db.commit()
os.environ['VIBE_CREATION_MIN_USERS']='4';v3=tag('Writer','Discovery Fixture Four');tag('Regular','Discovery Fixture Four');tag('Manager','Discovery Fixture Four');check(query('SELECT 1 FROM pending_vibes WHERE vibe_id=?',(v3,)),'Configured four not promoted at three');tag('OtherManager','Discovery Fixture Four');check(not query('SELECT 1 FROM pending_vibes WHERE vibe_id=?',(v3,)),'Configured four promotes at four')
os.environ['VIBE_CREATION_MIN_USERS']='invalid';check(life.minimum_users()==3,'Invalid threshold falls back to three')
if old is None:os.environ.pop('VIBE_CREATION_MIN_USERS',None)
else:os.environ['VIBE_CREATION_MIN_USERS']=old
# Profile filters before pagination; ties, cursor binding, labels and return destinations.
contexts=[]
def capture(sender,template,context,**kw):
 if template.name=='user_test.html':contexts.append(context)
template_rendered.connect(capture,app,weak=False)
owner=users['Regular'];writer=users['Writer'];expected={'authored':[],'guestbook':[]}
with app.app_context():
 db=core.get_db()
 for view in expected:
  for i in range(45):
   author=owner if view=='authored' else writer
   pid=core.identifiers.next_post_key(db);db.execute("INSERT INTO posts(id,user_id,target_user_id,content,circle,created_at) VALUES(?,?,?,?,?,'2028-01-01')",(pid,author,owner,'PROFILE VIEW '+view,'public'));core.identifiers.ensure(db,'post',pid);db.execute("INSERT INTO post_privacy VALUES(?,'public')",(pid,));expected[view].insert(0,pid)
 db.commit()
base='/@VMFixtureRegular'
for view in expected:
 p=base+'?'+urlencode({'profile_view':view,'mode':'night'});collected=[];first=None
 for _ in range(5):
  contexts.clear();r=get('Regular',p);check(r.status_code==200,'Profile view renders '+view);c=contexts[-1];check(len(c['posts'])<=20,'Profile batch bound');collected.extend(x['id'] for x in c['posts'] if x['content'].startswith('PROFILE VIEW'))
  if first is None:first=c
  if not c['profile_older']:break
  p=base+'?'+urlencode({'profile_view':view,'posts_cursor':c['profile_older'],'mode':'night'})
 check(collected==expected[view],'Every matching profile post once '+view)
 other='guestbook' if view=='authored' else 'authored';check(get('Regular',base,profile_view=other,posts_cursor=first['profile_older']).status_code==400,'Profile cursor bound to view')
 check(b'Apply view' in r.data,'Visible profile selector')
check(get('Regular',base,profile_view='unknown').status_code==400,'Unknown profile view refused')
check(b'Your welcome friend' in get('Regular','/guide').data,'Onboarding help available')
print('ONBOARDING DISCOVERY CHECKS',checks)
