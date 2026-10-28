"""T48 acceptance against isolated apps, copied databases and fictional identities."""
from pathlib import Path
import sys,os,json,smtplib,re
from urllib.parse import urlsplit,parse_qs
from html.parser import HTMLParser
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Fixture SMTP disabled'))
smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T48-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
bootstrap=bootstrap.replace("'MAIL_QUEUE':'0'", "'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')")
exec(compile(bootstrap,'T48 isolated app bootstrap','exec'))
check(app.config.get('STORAGE_POLICY') is None,'Fixture cannot inherit active upload ledger')
with app.app_context():
 db=core.get_db();check(tuple(r[2] for r in db.execute('PRAGMA index_info(idx_reactions_post_emoji_user)'))==('post_id','emoji','user_id'),'Covering reaction index installed')
pid,public=post_fixture('T48 FICTIONAL REACTION POST');other_pid,other_public=post_fixture('T48 OTHER POST');private_pid,private_public=post_fixture('T48 FRIENDS POST',audience='friends')
with app.app_context():
 db=core.get_db();reactors=[]
 for i in range(61):
  uid=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)',('@T48Reactor'+str(i),'t48-'+str(i)+'@example.invalid','!fixture-disabled','1990-01-01')).lastrowid
  db.execute("INSERT INTO age_clocks VALUES (?,'UTC',1)",(uid,));db.execute('INSERT INTO post_reactions(post_id,user_id,emoji) VALUES (?,?,?)',(pid,uid,'👍'));reactors.append(uid)
 db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],reactors[0]));db.execute('INSERT INTO user_mutes(user_id,target_id) VALUES (?,?)',(users['Regular'],reactors[1]));db.execute('INSERT INTO account_safety(user_id,inactive) VALUES (?,1)',(reactors[2],));db.execute('INSERT INTO post_reactions(post_id,user_id,emoji) VALUES (?,?,?)',(pid,users['Regular'],'🔥'));db.commit()
def url(ref):return '/posts/'+ref+'/reactions'
class People(HTMLParser):
 def __init__(self):super().__init__();self.names=[];self.next=None;self.current=None
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a':self.current=a.get('href')
 def handle_data(self,data):
  if data.startswith('@T48Reactor'):self.names.append(data)
  if data=='More people':self.next=self.current
 def handle_endtag(self,tag):
  if tag=='a':self.current=None
response=get('Regular',url(public),emoji='👍');check(response.status_code==200,'Visible post reactors open');check('no-store' in response.headers.get('Cache-Control',''),'People response cannot be cached')
people=People();people.feed(response.get_data(as_text=True));check(len(people.names)==50 and bool(people.next),'First people window is bounded with continuation')
check(all('@T48Reactor'+str(i) not in people.names for i in [0,1,2]),'Blocked muted inactive people omitted')
next_parts=urlsplit(people.next);next_query={k:v[0] for k,v in parse_qs(next_parts.query).items()};next_path=next_parts.path.removeprefix(mount)
second=get('Regular',next_path,**next_query);p2=People();p2.feed(second.get_data(as_text=True));check(second.status_code==200 and len(p2.names)==8 and not p2.next,'Last people window complete');check(len(set(people.names+p2.names))==58,'Seek pages omit no eligible reactor and duplicate none')
with app.app_context():
 db=core.get_db();child=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES ('@T48Child','t48-child@example.invalid','!fixture-disabled','2020-01-01',1,CURRENT_TIMESTAMP)").lastrowid;db.execute('INSERT INTO post_reactions(post_id,user_id,emoji) VALUES (?,?,?)',(pid,child,'👍'));db.commit()
age_page=get('Regular',url(public),emoji='👍');check('@T48Child' not in age_page.get_data(as_text=True),'Age-ineligible reactor identity omitted')
check(get('Writer',next_path,**next_query).status_code==400,'People cursor bound to viewer')
check(get('Regular',url(public),**{**next_query,'emoji':'🔥'}).status_code==400,'People cursor bound to emoji')
check(get('Regular',url(other_public),**next_query).status_code==400,'People cursor bound to post')
for bad in ['bad','x'*1600]:check(get('Regular',url(public),emoji='👍',after=bad).status_code==400,'Malformed cursor refused')
check(get('Regular',url(public),emoji='invalid').status_code==400,'Unknown emoji refused')
check(get('Regular',url(private_public),emoji='👍').status_code==404,'Private post cannot reveal reactor identities');check(get('Writer',url(private_public),emoji='👍').status_code==200,'Author retains own private post access')
change("UPDATE post_privacy SET audience='friends' WHERE post_id=?",(pid,));check(get('Regular',next_path,**next_query).status_code==404,'Post access rechecked after cursor issuance');change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(pid,))
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],users['Writer']));check(get('Regular',url(public),emoji='👍').status_code==404,'Blocked post author cannot reveal reactors');change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Regular'],users['Writer']))
# Real toggle route keeps independent choices and CSRF enforcement.
react='/react/'+public
for emoji in ['👍','💖']:
 q=clients['Regular'].post(react,json={'emoji':emoji},headers={'X-CSRF-Token':token},environ_overrides=env);check(q.status_code==200 and q.json['action']=='added','Real reaction adds independent choice')
q=clients['Regular'].post(react,json={'emoji':'👍'},headers={'X-CSRF-Token':token},environ_overrides=env);check(q.status_code==200 and q.json['action']=='removed','Real reaction toggles off')
check({r['emoji'] for r in query('SELECT emoji FROM post_reactions WHERE post_id=? AND user_id=?',(pid,users['Regular']))}=={'🔥','💖'},'Toggle preserves other choices')
check(clients['Regular'].post(react,json={'emoji':'👍'},environ_overrides=env).status_code==400,'Reaction write still requires CSRF')
# Deep reply windows render all visible comments and preserve recipients across windows.
comments=[]
with app.app_context():
 db=core.get_db();parent=None
 for i in range(60):
  uid=users['Regular'] if i%2 else users['Writer'];cid=db.execute('INSERT INTO comments(post_id,user_id,content,parent_comment_id,created_at) VALUES (?,?,?,?,?)',(pid,uid,'T48 deep reply '+str(i),parent,'2026-10-27 12:00:00')).lastrowid;core.identifiers.ensure(db,'comment',cid);comments.append(cid);parent=cid
 db.commit();last=core.identifiers.public(db,'comment',comments[-1]);first=core.identifiers.public(db,'comment',comments[0])
page=get('Regular','/posts/'+public);html=page.get_data(as_text=True);check(page.status_code==200,'Post detail renders deep replies');check(html.count('class="comment-body comment-text">T48 deep reply ')==50,'First comment window remains bounded');check('margin-left:0;padding-left:0;border-left:0' in html,'Reply indentation flattens beyond third level');check('reply-recipient' in html and '→ @VMFixture' in html,'Deep replies show author-to-recipient notation')
class Buttons(HTMLParser):
 def __init__(self):super().__init__();self.choices={}
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='button' and 'react-btn' in a.get('class','').split():self.choices[a['data-emoji']]=a.get('aria-pressed')
buttons=Buttons();buttons.feed(html);check(buttons.choices.get('🔥')=='true' and buttons.choices.get('💖')=='true' and buttons.choices.get('👍')=='false','Rendered buttons select only viewer choices, not everyone else reactions')
page2=get('Regular','/posts/'+public,comment=last);h2=page2.get_data(as_text=True);check(page2.status_code==200 and 'T48 deep reply 59' in h2,'Target deep reply opens across windows');check('→ @VMFixtureWriter' in h2,'Parent outside target window retains visible recipient')
for route in ['/feed','/vibe/VM%20Fixture%20One','/@VMFixtureWriter']:
 q=get('Regular',route);check(q.status_code in (200,302),'Timeline/profile/Vibe route still renders')
# Hidden and cross-post parent identities never populate the reply header field.
with app.test_request_context('/posts/'+public):
 from flask import session
 session['user_id']=users['Regular'];db=core.get_db();gq=importlib.import_module(package+'.growth_queries')
 db.execute('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],users['Writer']));rows,nav=gq.comment_windows(db,[pid],core.identifiers,single=True);check(all(r['reply_to_handle'] is None for r in rows if r['user_id']==users['Regular']),'Blocked parent recipient omitted');db.rollback()
# Inline editing remains available only to the author; post/comments retain rows.
q=clients['Regular'].post('/edit_comment/'+last,data={'content':'T48 edited reply','theme_csrf_token':token},environ_overrides=env);check(q.status_code in (200,302),'Existing comment edit endpoint works');check(query('SELECT content FROM comments WHERE id=?',(comments[-1],))[0][0]=='T48 edited reply','Own reply edit persists')
q=clients['Writer'].post('/edit_comment/'+last,data={'content':'UNAUTHORIZED','theme_csrf_token':token},environ_overrides=env);check(q.status_code in (302,403,404) and query('SELECT content FROM comments WHERE id=?',(comments[-1],))[0][0]=='T48 edited reply','Other author cannot edit reply')
check(query('SELECT COUNT(*) FROM comments WHERE post_id=?',(pid,))[0][0]==60,'All deep comment records preserved')
# Private Circle post access is rechecked for the new people route.
created=clients['Owner'].post('/circles',data={'name':'T48 Fictional Circle','description':'Acceptance fixture only','mode':'discoverable','theme_csrf_token':token},environ_overrides=env);check(created.status_code==302,'Create private Circle fixture')
circle_ref=created.location.rstrip('/').split('/')[-1]
posted=clients['Owner'].post('/create_post',data={'content':'T48 PRIVATE CIRCLE POST','circle_id':circle_ref,'audience':'public','vibes':'VM Fixture One','theme_csrf_token':token},environ_overrides=env);check(posted.status_code==302,'Create private Circle post fixture')
with app.app_context():
 db=core.get_db();circle_id=importlib.import_module(package+'.circle_ids').resolve(db,circle_ref);circle_pid=db.execute('SELECT post_id FROM circle_posts WHERE circle_id=? ORDER BY post_id DESC LIMIT 1',(circle_id,)).fetchone()[0];circle_post=core.identifiers.public(db,'post',circle_pid)
check(get('Regular',url(circle_post),emoji='👍').status_code==404,'Outsider cannot list private Circle reactors')
check(get('Owner',url(circle_post),emoji='👍').status_code==200,'Circle owner can list eligible reactors')
joined=clients['Regular'].post('/circles/'+circle_ref+'/join',data={'theme_csrf_token':token},environ_overrides=env);check(joined.status_code==302,'Request Circle membership')
check(get('Regular',url(circle_post),emoji='👍').status_code==404,'Pending membership cannot reveal Circle reactors')
approved=clients['Owner'].post('/circles/'+circle_ref+'/manage',data={'action':'approve','user_id':str(users['Regular']),'theme_csrf_token':token},environ_overrides=env);check(approved.status_code==302,'Approve Circle fixture member')
check(get('Regular',url(circle_post),emoji='👍').status_code==200,'Approved member can list Circle reactors')
check(get('Regular','/circles/'+circle_ref).status_code==200,'Circle timeline renders reaction hydration')
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(circle_pid,users['Owner'],users['Owner'],'Fictional acceptance decision'))
check(get('Regular',url(circle_post),emoji='👍').status_code==404,'Moderated post cannot reveal reactor identities')
print(json.dumps({'checks':checks,'passed':True,'scope':'T48 actual app with disposable database/files and fictional identities'}))
