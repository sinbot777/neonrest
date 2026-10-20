import os
os.environ['NEONREST_MESSAGING_ENABLED']='1'
from pathlib import Path
import os,sys,tempfile,sqlite3,importlib,contextlib,io,time,json

def _close_fixture_connections(directory):
    import gc, sqlite3
    gc.collect()
    for connection in gc.get_objects():
        if isinstance(connection, sqlite3.Connection):
            try:
                connection.close()
            except sqlite3.Error:
                pass
    gc.collect()
    directory.cleanup()

package=sys.argv[1];stage=Path(sys.argv[2]);_fixture_directory=tempfile.TemporaryDirectory(prefix='neonrest-statistics-test-');w=Path(_fixture_directory.name);import atexit,gc;atexit.register(_close_fixture_connections,_fixture_directory)
src=sqlite3.connect('file:/home/sinbot/db/'+package+'.db?mode=ro',uri=True);dst=sqlite3.connect(w/'fixture.db');src.backup(dst);src.close();dst.close()
with sqlite3.connect(w/'fixture.db') as before_db:initial_counts={r[0]:before_db.execute('SELECT COUNT(*) FROM "'+r[0]+'"').fetchone()[0] for r in before_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
prefix='NEONREST_PRODUCTION' if package=='neonrest' else 'NEONREST_SANDBOX'
for k,v in {'DATABASE':str(w/'fixture.db'),'SECRET_FILE':str(w/'secret'),'INSTANCE':str(w/'instance'),'MAIL_QUEUE_DIR':str(w/'mail'),'MAIL_QUEUE':'0'}.items():os.environ[prefix+'_'+k]=v
os.environ['NEONREST_STATISTICS_DATABASE']=str(w/'statistics.sqlite')
sys.path.insert(0,str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):core=importlib.import_module(package+'.app')
cf=importlib.import_module(package+'.community_features');tools=importlib.import_module(package+'.vibe_tools');life=importlib.import_module(package+'.utils.vibe_lifecycle');app=core.app;app.instance_path=str(w/'instance');app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/');core.mail.send=lambda x:(_ for _ in ()).throw(AssertionError('SMTP forbidden'))
mount='/sandbox' if package.endswith('sandbox') else '';env={'SCRIPT_NAME':mount};checks=0;now=int(time.time());token='fictional-vibe-management-csrf';clients={};users={}
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def query(sql,args=()):
 with app.app_context():return core.get_db().execute(sql,args).fetchall()
def change(sql,args=()):
 with app.app_context():db=core.get_db();r=db.execute(sql,args);db.commit();return r.lastrowid
check(all(query('SELECT COUNT(*) FROM "'+n+'"')[0][0]==v for n,v in initial_counts.items()),'Startup preserves existing table record counts')
with app.app_context():
 db=core.get_db();tools.initialize(db);tools.initialize(db);db.commit()
 # The copied owner row is replaced with a fictional identity before any session is created.
 db.execute("UPDATE users SET handle='@VMFixtureOwner',email='vm-owner@example.invalid',password_hash='!disabled-fixture',verified=1,bio='',avatar_path=NULL WHERE id=1")
 for table in ['staff_roles','vibe_editors','user_moderation','account_safety','account_disables','age_clocks','active_sessions']:
  db.execute('DELETE FROM '+table+' WHERE user_id=1')
 for key,dob in [('Owner','1990-01-01'),('Admin','1990-01-01'),('Moderator','1990-01-01'),('SiteManager','1990-01-01'),('Manager','1990-01-01'),('OtherManager','1990-01-01'),('Writer','1990-01-01'),('Regular','1990-01-01'),('Teen','2013-01-01'),('NoFactor','1990-01-01')]:
  uid=1 if key=='Owner' else db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)',('@VMFixture'+key,'vm-'+key.lower()+'@example.invalid','!disabled-fixture',dob)).lastrowid;users[key]=uid
  db.execute("INSERT OR REPLACE INTO age_clocks VALUES (?,'UTC',1)",(uid,));db.execute('INSERT OR REPLACE INTO account_safety(user_id,totp_secret) VALUES (?,?)',(uid,None if key=='NoFactor' else 'JBSWY3DPEHPK3PXP'))
  sid='fictional-vm-'+key;db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Vibe fixture'))
 for key,role in [('Admin','admin'),('Moderator','moderator'),('SiteManager','manager')]:db.execute('INSERT INTO staff_roles VALUES (?,?)',(users[key],role))
 vid=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture One')").lastrowid;other=db.execute("INSERT INTO vibes(name) VALUES ('VM Fixture Two')").lastrowid
 for key,cid in [('Manager',vid),('OtherManager',other),('NoFactor',vid)]:db.execute('INSERT INTO vibe_editors VALUES (?,?)',(cid,users[key]))
 db.commit()
for key,uid in users.items():
 client=app.test_client()
 with client.session_transaction() as s:s.update(user_id=uid,user_handle='@VMFixture'+key,user_email='vm-'+key.lower()+'@example.invalid',sid='fictional-vm-'+key,fresh_at=now,factor_at=now,theme_csrf_token=token)
 clients[key]=client
def get(key,path,**params):return clients[key].get(path,query_string=params,environ_overrides=env)
def action(key,kind,cid=None,**data):return clients[key].post('/manage/vibes/'+str(cid or vid)+'/action',data={'action':kind,'theme_csrf_token':token,'reason':'PRACTICE ONLY: fictional test decision',**data},environ_overrides=env)
def post_fixture(text,audience='public',vibes=None):
 with app.app_context():
  db=core.get_db();pid=core.identifiers.next_post_key(db);db.execute('INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)',(pid,users['Writer'],text,'public'));core.identifiers.ensure(db,'post',pid);db.execute('INSERT OR REPLACE INTO post_privacy VALUES (?,?)',(pid,audience))
  for cid in vibes or [vid]:db.execute('INSERT INTO post_vibes VALUES (?,?)',(pid,cid))
  db.commit();return pid,core.identifiers.public(db,'post',pid)


from datetime import datetime,timedelta,timezone
stats=importlib.import_module(package+'.site_statistics');detail=importlib.import_module(package+'.statistics_detail');verification=importlib.import_module(package+'.email_verification');circlemod=importlib.import_module(package+'.circles');circleids=importlib.import_module(package+'.circle_ids');circlenames=importlib.import_module(package+'.circle_names')
path=app.extensions['site_statistics']['path'];check(str(path).startswith(str(w)),'Isolated sidecar')
today=datetime.now(timezone.utc).date();day=today.isoformat();headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36'}
def raw():
 with sqlite3.connect(path) as db:return db.execute('SELECT bucket,segment,kind,label,detail,value FROM hourly_counters ORDER BY bucket,segment,kind,label,detail').fetchall()
def reset():
 with sqlite3.connect(path) as db:db.execute('DELETE FROM hourly_counters');db.execute('DELETE FROM counters');db.execute("UPDATE metadata SET value='0' WHERE key='detail_capacity_skips'")
def count(kind,label=None,segment=None):return sum(r[5] for r in raw() if r[2]==kind and (label is None or r[3]==label) and (segment is None or r[1]==segment))
def visit(route='/',client=None,extra=None):return (client or app.test_client()).get(route,headers={**headers,**(extra or {})},environ_overrides=env)
def report(traffic='ordinary',days='7',**values):
 with app.test_request_context('/manage/statistics',query_string={'traffic':traffic,'days':days,**values},environ_overrides=env):return detail.build_report(core,path,detail.options())
messaging=importlib.import_module(package+'.messaging')
public_ids=importlib.import_module(package+'.public_ids')
privacy=importlib.import_module(package+'.privacy_workflows')
retention=importlib.import_module(package+'.retention')
suite=importlib.import_module(package+'.statistics_suite')
security=importlib.import_module(package+'.network_security')
from flask import Response
from html.parser import HTMLParser
import secrets
check(app.config['MESSAGING_ENABLED'],'Feature enabled for isolated tests')
check(app.config['RETENTION_ENABLED'] is False,'Erasure disabled')
def post(who,route,**values):
 return clients[who].post(route,data={'theme_csrf_token':token,**values},headers={**headers,'Accept':'application/json'},environ_overrides=env)
def setting(who,inbox='friends',presence='invisible',away=''):
 return post(who,'/messages/settings',inbox=inbox,presence=presence,away=away)
def start(who,peer,body='PRACTICE ONLY: Fictional introduction.',nonce=None):
 return post(who,'/messages/start',handle='@VMFixture'+peer,body=body,nonce=nonce or secrets.token_urlsafe(24))
def chat(a,b):
 low,high=sorted((users[a],users[b]));return query('SELECT * FROM dm_threads WHERE low_user=? AND high_user=?',(low,high))[0]
def send(who,thread,body='PRACTICE ONLY: Fictional reply.',nonce=None):
 return post(who,'/messages/'+thread['public_id']+'/send',body=body,nonce=nonce or secrets.token_urlsafe(24))
def decision(who,thread,action):return post(who,'/messages/'+thread['public_id']+'/decision',action=action)
def last_message(thread):return query('SELECT * FROM dm_messages WHERE thread_id=? ORDER BY id DESC LIMIT 1',(thread['id'],))[0]
def unread(who):
 with app.test_request_context('/'):
  return messaging.unread_threads(core.get_db(),users[who])
def friends(a,b):change("INSERT INTO friend_requests(sender_id,receiver_id,status) VALUES (?,?,'accepted')",(users[a],users[b]))
def fixture_person(name,dob):
 uid=change('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)',('@VMFixture'+name,'vm-'+name.lower()+'@example.invalid','!disabled-fixture',dob));users[name]=uid
 change("INSERT INTO age_clocks VALUES (?,'UTC',1)",(uid,));sid='fictional-msg-'+name
 change('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Messaging fixture'))
 c=app.test_client()
 with c.session_transaction() as s:s.update(user_id=uid,user_handle='@VMFixture'+name,user_email='vm-'+name.lower()+'@example.invalid',sid=sid,theme_csrf_token=token,fresh_at=now,factor_at=now)
 clients[name]=c

for route in ['/messages','/messages/overview','/messages/AbCdEfGh12345678']:
 check(visit(route).status_code in (401,403),'Guest messaging denied '+route)
 check('no-store' in visit(route).headers.get('Cache-Control',''),'Private error cache '+route)
for who in ['Regular','Writer','Owner','NoFactor']:
 r=get(who,'/messages');check(r.status_code==200,'Eligible inbox '+who)
 check(b'not end-to-end encrypted' in r.data and b'Invisible' in r.data,'Disclosure and private defaults '+who)
 check(r.headers.get('X-Robots-Tag')=='noindex, nofollow' and r.headers.get('Referrer-Policy')=='same-origin' and r.headers.get('X-Frame-Options')=='DENY','Private headers '+who)
 check(('href="'+mount+'/messages').encode() in r.data,'Environment navigation '+who)
with clients['Owner'].session_transaction() as s:s.update(fresh_at=0,factor_at=0)
check(get('Owner','/messages').status_code==200,'Ordinary messaging needs no repeated 2FA')
with clients['Owner'].session_transaction() as s:s.update(fresh_at=now,factor_at=now)
check(start('OtherManager','Regular').status_code==404,'Stranger denied by default')
check(setting('Regular',inbox='requests').status_code==303,'Opt in to requests')
nonce=secrets.token_urlsafe(24);r=start('OtherManager','Regular',nonce=nonce);check(r.status_code==200,'Single introduction request')
thread=chat('OtherManager','Regular');key=thread['public_id'];intro=last_message(thread)
check(thread['state']=='pending' and messaging.TOKEN.fullmatch(key),'Opaque pending conversation')
check(r.json['url']==mount+'/messages/'+key,'Start response preserves mount')
check(start('OtherManager','Regular',nonce=nonce).status_code==200 and query('SELECT COUNT(*) FROM dm_messages WHERE thread_id=?',(thread['id'],))[0][0]==1,'Initial retry idempotent')
check(start('OtherManager','Regular').status_code==409 and send('OtherManager',thread).status_code==403,'No second message before acceptance')
check(unread('Regular')==1,'Pending request counts as unread conversation')
notices=query("SELECT * FROM notifications WHERE user_id=? AND kind='messages'",(users['Regular'],))
check(len(notices)==1 and notices[0]['message']=='New message request.' and 'Fictional introduction' not in notices[0]['message'],'Generic request notification')
r=get('Regular','/messages/'+key);check(r.status_code==200 and b'Accept conversation' in r.data and b'Decline' in r.data,'Recipient reviews request')
check(get('Admin','/messages/'+key).status_code==404 and get('Writer','/messages/'+key+'/updates').status_code==404,'No staff or outsider conversation bypass')
check(post('Writer','/messages/'+key+'/read',through=intro['public_id']).status_code==404,'Outsider cannot mark messages read')
check(post('Regular','/messages/'+key+'/read',through=intro['public_id']).status_code==200 and unread('Regular')==0,'Viewing clears unread')
check(query("SELECT read_at FROM notifications WHERE user_id=? AND kind='messages'",(users['Regular'],))[0][0] is not None,'Viewing clears linked notification')
check(decision('OtherManager',thread,'accept').status_code==409,'Sender cannot self-accept')
check(decision('Regular',thread,'accept').status_code==303,'Recipient accepts')
thread=chat('OtherManager','Regular');check(thread['state']=='accepted','Consent persisted')
secret='PRIVATE-SELECTED-MESSAGE <script>window.MESSAGE_XSS=1</script> & unicode 🛋️'
nonce=secrets.token_urlsafe(24);check(send('OtherManager',thread,secret,nonce).status_code==200,'Accepted sender can send')
reported=last_message(thread);check(send('OtherManager',thread,secret,nonce).status_code==200 and last_message(thread)['id']==reported['id'],'Send retry idempotent')
check(send('OtherManager',thread,'Different text must not be silently discarded',nonce).status_code==409,'Edited retry cannot reuse acknowledged send')
check(send('Regular',thread,'CONTEXT-MUST-NOT-BE-REPORTED').status_code==200,'Recipient can reply to accepted request')
r=get('Regular','/messages/'+key);check(b'&lt;script&gt;window.MESSAGE_XSS=1' in r.data and b'<script>window.MESSAGE_XSS=1' not in r.data,'Stored text cannot inject HTML')
latest=last_message(thread);r=get('OtherManager','/messages/'+key+'/updates',after=reported['public_id']);check(r.status_code==200 and r.json['messages'][0]['body']=='CONTEXT-MUST-NOT-BE-REPORTED','Participant updates deliver new text')
check(not any(word in json.dumps(r.json) for word in ['read_id','read_at','last_seen','active_at']),'No read receipts or last-seen fields')
check(get('Regular','/messages/'+key+'/updates',after='NOT-THIS-THREAD').status_code==400,'Invalid update cursor rejected')
check(send('OtherManager',thread,'x'*4001).status_code==400 and send('OtherManager',thread,'\x00private').status_code==400,'Length and unsafe control validation')
check(post('OtherManager','/messages/'+key+'/send',body='missing nonce').status_code==400,'Nonce required')
for pathpart in ['start',key+'/send',key+'/decision',key+'/read','settings','presence',key+'/report/'+reported['public_id']]:
 r=clients['Regular'].post('/messages/'+pathpart,data={'body':'fictional','nonce':secrets.token_urlsafe(24)},headers=headers,environ_overrides=env)
 check(r.status_code==400,'CSRF enforced '+pathpart)
check(clients['OtherManager'].post('/messages/'+key+'/send',data={'theme_csrf_token':token,'body':'cross-site','nonce':secrets.token_urlsafe(24)},headers={'Origin':'https://evil.invalid'},environ_overrides=env).status_code==403,'Cross-site send rejected')
before=query('SELECT COUNT(*) FROM dm_messages')[0][0];r=clients['OtherManager'].post('/messages/'+key+'/send',data=b'x'*65537,headers=headers,environ_overrides=env);check(r.status_code==413 and query('SELECT COUNT(*) FROM dm_messages')[0][0]==before,'Oversized requests do not write')
check(decision('Regular',thread,'mute').status_code==303,'Mute notifications')
notices_before=query("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='messages'",(users['Regular'],))[0][0]
check(send('OtherManager',thread).status_code==200,'Muted chat still accepts messages')
check(query("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='messages'",(users['Regular'],))[0][0]==notices_before,'Mute suppresses new notifications')
check(decision('Regular',thread,'pause').status_code==303 and send('OtherManager',thread).status_code==403,'Pause stops peer sending')
check(send('Regular',thread).status_code==403,'Paused user cannot send either')
check(decision('Regular',thread,'resume').status_code==303 and send('OtherManager',thread).status_code==200,'Resume restores messaging')
check(decision('Regular',thread,'block').status_code==303,'Block works from conversation')
check(send('OtherManager',thread).status_code==403 and get('Regular','/messages/'+key).status_code==200,'Block stops contact but retains age-eligible report access')
check(unread('Regular')==0,'Blocked activity not advertised in unread badge')
check(post('Regular','/account/relationships',handle='@VMFixtureOtherManager',action='unblock').status_code==302,'Existing privacy control can undo block')

# Declining is reason-free and cannot be bypassed by starting again.
check(start('Writer','Regular').status_code==200,'Second fictional request')
declined=chat('Writer','Regular');check(decision('Regular',declined,'decline').status_code==303,'Decline requires no reason')
check(start('Writer','Regular').status_code==409 and send('Writer',declined).status_code==403,'Decline prevents repeated introductions')

# Presence reveals only the current opted-in state to eligible friends.
friends('Writer','Regular');setting('Writer',presence='online',away='PRACTICE ONLY away text')
with app.app_context():
 state=messaging.presence_for(core.get_db(),users['Writer'],users['Regular']);check(state['status']=='online' and state['away']=='PRACTICE ONLY away text','Eligible friend sees chosen presence')
 check(messaging.presence_for(core.get_db(),users['Writer'],users['OtherManager'])['status']=='offline','Stranger cannot see presence')
setting('Writer',presence='invisible',away='PRIVATE AWAY SENTINEL')
with app.app_context():check(messaging.presence_for(core.get_db(),users['Writer'],users['Regular'])==dict(status='offline',label='Offline',away=''),'Invisible hides away text too')
setting('Writer',presence='away');change('UPDATE dm_settings SET active_at=? WHERE user_id=?',(now-151,users['Writer']))
with app.app_context():check(messaging.presence_for(core.get_db(),users['Writer'],users['Regular'])['status']=='offline','Presence expires without heartbeat')
check(post('Writer','/messages/presence').status_code==200,'Heartbeat works')
with app.app_context():check(messaging.presence_for(core.get_db(),users['Writer'],users['Regular'])['status']=='away','Heartbeat refreshes chosen status')
overview=get('Regular','/messages/overview').json;check(any(b['handle']=='@VMFixtureWriter' for b in overview['buddies']) and 'active_at' not in json.dumps(overview),'Buddy overview has no last-seen timestamp')

# Teen bands, friendship and current parental controls have no staff override.
fixture_person('TeenPeer','2012-01-01');fixture_person('Child','2015-01-01')
setting('TeenPeer',inbox='requests')
check(start('Teen','TeenPeer').status_code==404,'Teen requests do not bypass friendship')
friends('Teen','TeenPeer');check(start('Teen','TeenPeer').status_code==200,'Eligible teen friends can chat')
teenchat=chat('Teen','TeenPeer');check(teenchat['state']=='accepted','Friend conversation accepted directly')
check(start('Owner','TeenPeer').status_code==404 and start('Teen','Regular').status_code==404,'No adult/minor age-band bypass including owner')
change('DELETE FROM friend_requests WHERE sender_id=? AND receiver_id=?',(users['Teen'],users['TeenPeer']))
check(send('Teen',teenchat).status_code==403,'Unfriending stops new teen contact')
change("INSERT INTO family_links(parent_id,child_id,status) VALUES (?,?,'approved')",(users['Owner'],users['Child']))
check(start('Owner','Child').status_code==200,'Approved parent relationship permits direct family conversation')
friends('Child','TeenPeer');check(start('Child','TeenPeer').status_code==404,'Under-13 peer contact needs parent permission')
change('INSERT INTO parent_contacts VALUES (?,?,?)',(users['Owner'],users['Child'],users['TeenPeer']))
check(start('Child','TeenPeer').status_code==200,'Approved under-13 peer permission respected')
childchat=chat('Child','TeenPeer');change("UPDATE family_links SET status='revoked' WHERE child_id=?",(users['Child'],))
check(get('TeenPeer','/messages/'+childchat['public_id']).status_code==404,'Revoked consent removes peer access')
check(start('Child','TeenPeer').status_code not in (200,303),'Revoked child cannot send')

# Blocking, account restrictions and forged resource keys cannot leak content.
change('INSERT INTO account_disables(user_id,disabled,reason,updated_by) VALUES (?,1,?,?)',(users['OtherManager'],'Fictional test',users['Owner']))
check(get('Regular','/messages/'+key).status_code==404 and send('Regular',thread).status_code==404,'Disabled peer not exposed')
change('DELETE FROM account_disables WHERE user_id=?',(users['OtherManager'],))
change("INSERT INTO user_moderation(user_id,posting_restricted,reason,updated_by) VALUES (?,1,'Fictional test',?)",(users['OtherManager'],users['Owner']))
check(send('OtherManager',thread).status_code==403,'Posting restriction prevents private sending')
change('DELETE FROM user_moderation WHERE user_id=?',(users['OtherManager'],))
check(post('Regular','/messages/'+key+'/read',through=last_message(teenchat)['public_id']).status_code==400,'Read cursor cannot cross conversations')

# Reports preserve exactly the selected message, and staff cannot browse unrelated chat.
check(post('Regular','/messages/'+key+'/report/'+reported['public_id'],reason='PRACTICE ONLY unwanted contact.').status_code==303,'Participant submits report')
reportrow=query('SELECT * FROM dm_reports WHERE message_id=?',(reported['id'],))[0];case_id=reportrow['case_id']
check(post('Writer','/messages/'+key+'/report/'+reported['public_id'],reason='Unauthorized').status_code==404,'Outsider cannot report private message')
check(post('OtherManager','/messages/'+key+'/report/'+reported['public_id'],reason='Own message').status_code==404,'Self-report not allowed')
evidence=query('SELECT snapshot,sha256 FROM case_evidence WHERE case_id=?',(case_id,))[0]
check(secret in json.loads(evidence['snapshot'])['content']['body'] and 'CONTEXT-MUST-NOT-BE-REPORTED' not in evidence['snapshot'] and cf.digest(evidence['snapshot'])==evidence['sha256'],'Exact report snapshot and hash')
check(post('Regular','/messages/'+key+'/report/'+reported['public_id'],reason='PRACTICE ONLY repeated.').status_code==303 and query('SELECT COUNT(*) FROM dm_reports WHERE message_id=?',(reported['id'],))[0][0]==1,'Report retry does not duplicate evidence')
r=get('Admin','/manage/messages/reports');check(r.status_code==200 and b'PRIVATE-SELECTED-MESSAGE' not in r.data,'Staff queue contains no unreported chat body')
check(get('Admin','/messages/'+key).status_code==404,'Reviewer has no full-conversation access')
r=get('Admin','/manage/cases/'+str(case_id));check(r.status_code==200 and b'PRIVATE-SELECTED-MESSAGE' in r.data and b'CONTEXT-MUST-NOT-BE-REPORTED' not in r.data,'Case evidence contains only selected private message')
check(post('Owner','/manage/cases/'+str(case_id),action='close').status_code==409,'Open message report blocks case closure')
with app.app_context():
 check(bool(privacy.blockers(core.get_db(),users['Regular'])) and bool(privacy.blockers(core.get_db(),users['OtherManager'])),'Both participants preserved while report open')
with clients['Admin'].session_transaction() as s:s['fresh_at']=0
check(get('Admin','/manage/messages/reports').status_code==302,'Staff report review still requires fresh authentication')
with clients['Admin'].session_transaction() as s:s.update(fresh_at=now,factor_at=now)
r=post('Admin','/manage/messages/reports',report_id=str(reportrow['id']),decision='remove',reason='PRACTICE ONLY moderation exercise.');check(r.status_code==303,'Staff decision performs removal')
check(query('SELECT hidden FROM dm_messages WHERE id=?',(reported['id'],))[0][0]==1,'Reported message hidden in conversation')
check(reported['public_id'] in get('Regular','/messages/'+key+'/updates',after=reported['public_id']).json['removed'],'Polling can revoke previously rendered message')
check(b'PRIVATE-SELECTED-MESSAGE' not in get('Regular','/messages/'+key).data,'Removed text no longer rendered to participants')
check(query('SELECT snapshot FROM case_evidence WHERE case_id=?',(case_id,))[0][0]==evidence['snapshot'],'Moderation does not change preserved evidence')
check(post('Owner','/manage/cases/'+str(case_id),action='close').status_code==302,'Resolved report allows normal case closure')
with app.app_context():check(bool(privacy.blockers(core.get_db(),users['Regular'])),'Final preservation disposition still required')
change('INSERT INTO privacy_case_dispositions VALUES (?,?,?,?)',(case_id,users['Owner'],'PRACTICE ONLY final determination; no outstanding appeal.',now))

# A staff participant cannot decide their own report.
setting('NoFactor',inbox='requests');check(start('Owner','NoFactor').status_code==200,'Staff can message age-eligible adults normally')
selfchat=chat('Owner','NoFactor');ownmsg=last_message(selfchat)
check(post('NoFactor','/messages/'+selfchat['public_id']+'/report/'+ownmsg['public_id'],reason='PRACTICE ONLY impartial review.').status_code==303,'Staff-authored message report')
selfreport=query('SELECT id FROM dm_reports WHERE message_id=?',(ownmsg['id'],))[0][0]
check(post('Owner','/manage/messages/reports',report_id=str(selfreport),decision='keep',reason='Own decision').status_code==403,'Owner cannot adjudicate their own message report')

# Exports contain only the requesting account's authored messages.
r=post('OtherManager','/account/export');check(r.status_code==200,'Own account export available')
export=json.loads(r.data);check('private_messages' in export and all('CONTEXT-MUST-NOT-BE-REPORTED' not in m['body'] for m in export['private_messages']['sent_messages']),'Export does not include other participants messages')
check(any(m['body']==secret for m in export['private_messages']['sent_messages']),'Export retains own authored content')

# Pagination is bounded and cursors remain conversation-scoped.
for i in range(56):change('INSERT INTO dm_messages(public_id,thread_id,sender_id,body,client_nonce) VALUES (?,?,?,?,?)',(public_ids.random_token(),thread['id'],users['OtherManager'],'PRACTICE ONLY history '+str(i),secrets.token_urlsafe(24)))
r=get('Regular','/messages/'+key);check(r.data.count(b'data-message-key=')==50 and b'Load earlier messages' in r.data,'Latest history page bounded')
old= query('SELECT public_id FROM dm_messages WHERE thread_id=? ORDER BY id DESC LIMIT 1 OFFSET 49',(thread['id'],))[0][0]
r=get('Regular','/messages/'+key,before=old);check(0<r.data.count(b'data-message-key=')<50,'Earlier history pagination')
r=get('Regular','/messages/'+key+'/updates');check(len(r.json['messages'])==50 and r.json['more'],'Update batch bounded')

# Capacity and rate limits preserve existing messages and fail without appending.
from concurrent.futures import ThreadPoolExecutor
friends('Writer','Manager');concurrent_nonce=secrets.token_urlsafe(24)
with clients['Writer'].session_transaction() as s:writer_session=dict(s)
def concurrent_start(_):
 client=app.test_client()
 with client.session_transaction() as s:s.update(writer_session)
 return client.post('/messages/start',data={'theme_csrf_token':token,'handle':'@VMFixtureManager','body':'PRACTICE ONLY concurrent retry','nonce':concurrent_nonce},headers={**headers,'Accept':'application/json'},environ_overrides=env).status_code
with ThreadPoolExecutor(max_workers=2) as pool:check(list(pool.map(concurrent_start,range(2)))==[200,200],'Concurrent start retries succeed')
race_thread=chat('Writer','Manager');check(query('SELECT COUNT(*) FROM dm_messages WHERE thread_id=?',(race_thread['id'],))[0][0]==1,'Concurrent start creates exactly one thread and message')
original_cap=app.config['MESSAGING_MESSAGE_CAP'];app.config['MESSAGING_MESSAGE_CAP']=query('SELECT COUNT(*) FROM dm_messages')[0][0]
check(send('OtherManager',thread).status_code==503,'Storage cap blocks new writes');app.config['MESSAGING_MESSAGE_CAP']=original_cap
window=int(time.time())//60;subject=cf.digest('user:'+str(users['OtherManager']))
change("INSERT INTO rate_buckets(subject,action,window,count,touched_at) VALUES (?,'messages-send',?,60,?) ON CONFLICT(subject,action,window) DO UPDATE SET count=60,touched_at=excluded.touched_at",(subject,window,int(time.time())))
before=query('SELECT COUNT(*) FROM dm_messages')[0][0];r=send('OtherManager',thread);check(r.status_code==429 and r.headers.get('Retry-After') and query('SELECT COUNT(*) FROM dm_messages')[0][0]==before,'Actual send rate limit')

with app.test_request_context('/messages/PRIVATE-TOKEN-SENTINEL'):
 check(not suite.reportable_route('/messages/<thread_id>') and 'PRIVATE-TOKEN-SENTINEL' not in security.path_detail('/messages/PRIVATE-TOKEN-SENTINEL'),'Private metrics and error-path exclusions')
check(b'Disallow: /messages' in visit('/robots.txt').data if not mount else b'Disallow: /\n' in visit('/robots.txt').data,'Crawler exclusions')
check(b'Private messages' in get('Regular','/guide').data and b'not end-to-end encrypted' in get('Regular','/privacy').data,'Guide and privacy disclosure present')

# Erasure cannot damage a preserved peer, and unlinking retains only the peer's own words.
with app.app_context():
 db=core.get_db();held=cf.ensure_case(db,'user',users['OtherManager'],users['OtherManager']);db.commit()
 check(bool(privacy.erasure_blockers(db,users['Regular'])),'Held peer blocks shared messaging disposal')
change("UPDATE moderation_cases SET status='closed',closed_at=CURRENT_TIMESTAMP WHERE id=?",(held,));change('INSERT INTO privacy_case_dispositions VALUES (?,?,?,?)',(held,users['Owner'],'PRACTICE ONLY final resolution.',now))
with app.app_context():
 db=core.get_db();check(not privacy.erasure_blockers(db,users['Regular']),'Resolved fictional cases release blockers')
 retention.erase_account(db,users['Regular'],retention.storage_roots(app));db.commit()
check(not query('SELECT 1 FROM dm_messages WHERE sender_id=?',(users['Regular'],)) and not query('SELECT 1 FROM dm_members WHERE user_id=?',(users['Regular'],)),'Future account erasure removes own sent messages and membership')
thread_after=query('SELECT * FROM dm_threads WHERE id=?',(thread['id'],))[0]
check(thread_after['low_user'] is None or thread_after['high_user'] is None,'Deleted account unlinked')
r=get('OtherManager','/messages/'+key);check(r.status_code==200 and b'Deleted account' in r.data and b'CONTEXT-MUST-NOT-BE-REPORTED' not in r.data,'Survivor retains only own messages without deleted identity')
check(app.config['RETENTION_ENABLED'] is False,'No automatic erasure activation')

r=get('Owner','/messages',window='1');check(r.status_code==200 and b'dm-buddy-mode' in r.data and b'Neonrest Logo' not in r.data,'Standalone buddy window without site chrome')
r=get('Owner','/messages',window='1',compose='1',to='@PRACTICE-ONLY');check(r.status_code==200 and b'dm-compose-mode' in r.data and b'value="@PRACTICE-ONLY"' in r.data,'Compact compose prefill')
check(b'/messages/start?window=1' in r.data,'Compact form retains window mode')
r=get('Owner','/messages/'+selfchat['public_id'],window='1');check(r.status_code==200 and b'dm-chat-mode' in r.data and b'window=0' in r.data,'Standalone chat and full page escape')
r=post('Owner','/messages/settings?window=1',inbox='friends',presence='invisible',away='');check(r.status_code==303 and 'window=1' in r.headers['Location'],'Settings retain compact mode')

print(json.dumps({'package':package,'checks':checks,'passed':True,'fictional_only':True}))
