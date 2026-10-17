"""Private Circle regression checks against a staged app and disposable fixture DB."""
from pathlib import Path
import contextlib, importlib, io, os, sqlite3, sys, tempfile, time, re
from unittest.mock import patch
from PIL import Image

stage = Path(sys.argv[1]).resolve()
assert stage.name == 'neonrest' and '/releases/CIRCLES-' in str(stage)
fixture = Path('/home/sinbot/releases/CIRCLES-20261016/production-public-20261017/production-before.db')
assert fixture.is_file()
work = tempfile.TemporaryDirectory(prefix='circle-fixture-')
root = Path(work.name)
source = sqlite3.connect('file:' + str(fixture) + '?mode=ro', uri=True)
destination = sqlite3.connect(root / 'fixture.db'); source.backup(destination); source.close(); destination.close()
os.environ.update(NEONREST_PRODUCTION_DATABASE=str(root/'fixture.db'), NEONREST_PRODUCTION_SECRET_FILE=str(root/'secret'), NEONREST_PRODUCTION_INSTANCE=str(root/'instance'), NEONREST_PRODUCTION_MAIL_QUEUE_DIR=str(root/'mail'), NEONREST_PRODUCTION_MAIL_QUEUE='0')
sys.path.insert(0, str(stage.parent))
with contextlib.redirect_stdout(io.StringIO()):
    core = importlib.import_module('neonrest.app')
from neonrest import community_features as cf, circles, circle_ids
from neonrest.media_features import media_folder
app = core.app
app.config.update(TESTING=True, SESSION_COOKIE_PATH='/', MAIL_QUEUE_ENABLED=False)
app.instance_path = str(root/'instance')
core.mail.send = lambda _: (_ for _ in ()).throw(AssertionError('No SMTP in Circle checks'))
checks = 0

def check(ok, label):
    global checks
    assert ok, label
    checks += 1

now = int(time.time()); token = 'circle-fixture-csrf'
clients = {}
with app.app_context():
    db = core.get_db()
    users = {}
    for key, dob in [('Owner','1990-01-01'),('Member','1990-01-01'),('Outsider','1990-01-01'),('Moderator','1990-01-01'),('Teen','2011-01-01')]:
        uid = db.execute('INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES (?,?,?,?,1,CURRENT_TIMESTAMP)', ('@CircleFixture'+key,key.lower()+'@example.invalid','!disabled-fixture-login',dob)).lastrowid
        users[key] = uid
        db.execute("INSERT INTO age_clocks VALUES (?,'UTC',1)", (uid,))
        sid='circle-fixture-'+key
        db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Circle fixture'))
    db.commit()
for key, uid in users.items():
    c=app.test_client()
    with c.session_transaction() as s:
        s.update(user_id=uid,user_handle='@CircleFixture'+key,user_email=key.lower()+'@example.invalid',sid='circle-fixture-'+key,fresh_at=now,factor_at=now,theme_csrf_token=token)
    clients[key]=c

def public_circle(cid):
    with app.app_context():return circle_ids.public(core.get_db(),int(cid))

def fixture_path(path):
    path=re.sub(r'^/circles/(\d+)(?=[/?]|$)',lambda m:'/circles/'+public_circle(m[1]),path)
    return re.sub(r'([?&]circle_id=)(\d+)',lambda m:m[1]+public_circle(m[2]),path)

def get(key, path):
    return clients[key].get(fixture_path(path))

def post(key, path, **data):
    if 'circle_id' in data:data['circle_id']=public_circle(data['circle_id'])
    return clients[key].post(fixture_path(path), data=dict(data,theme_csrf_token=token))

def manage(key, cid, action, **data):
    if action in ('remove','decline'):data.setdefault('reason','Fictional membership decision')
    return post(key, f'/circles/{cid}/manage',action=action,**data)

def create(mode='discoverable'):
    response=post('Owner','/circles',name='Fixture Circle',description='Fictional Circle only',mode=mode)
    check(response.status_code==302,'Create '+mode)
    public_token=response.location.rstrip('/').split('/')[-1]
    check(bool(core.identifiers.TOKEN.fullmatch(public_token)),'Circle creation redirects to opaque URL')
    with app.app_context():return circle_ids.resolve(core.get_db(),public_token)

def query(sql, args=()):
    with app.app_context(): return core.get_db().execute(sql,args).fetchall()

def change(sql, args=()):
    with app.app_context():
        db=core.get_db();db.execute(sql,args);db.commit()

check(get('Owner','/circles').status_code==200,'Actual Circles home template')
check(clients['Owner'].post('/circles',data={'name':'bad','mode':'hidden'}).status_code==400,'Creation CSRF')
cid=create(); hidden=create('hidden')
opaque=public_circle(cid);hidden_opaque=public_circle(hidden)
check(not opaque.isdecimal() and len(opaque)==16,'Circle IDs follow post public-ID format')
check(clients['Owner'].get(f'/circles/{cid}').status_code==404,'New Circles do not acquire sequential aliases')
change('UPDATE circle_public_ids SET legacy_alias=? WHERE circle_id=?',(str(cid),cid))
change('UPDATE circle_public_ids SET legacy_alias=? WHERE circle_id=?',(str(hidden),hidden))
legacy=clients['Owner'].get(f'/circles/{cid}?page=1')
check(legacy.status_code==302 and legacy.location.endswith('/circles/'+opaque+'?page=1'),'Authorized legacy link redirects and preserves query')
check('no-store' in legacy.headers.get('Cache-Control',''),'Legacy redirect remains private')
legacy_hidden=clients['Outsider'].get(f'/circles/{hidden}')
check(legacy_hidden.status_code==404 and not legacy_hidden.headers.get('Location'),'Hidden legacy link cannot disclose canonical ID')
check(app.test_client().get(f'/circles/{hidden}').status_code==404,'Anonymous legacy link does not disclose Circle existence')
check(clients['Owner'].get('/circles/'+'A'*65).status_code==404,'Overlong Circle ID rejected')
check(clients['Owner'].get('/circles/prefix-'+opaque).status_code==404,'Unenabled Circle prefixes rejected')
check(public_circle(cid)==opaque,'Repeated ID lookup stays stable')
check(get('Outsider',f'/circles/{hidden}').status_code==404,'Hidden Circle undiscoverable')
check(get('Outsider',f'/circles/{cid}').status_code==200,'Discoverable intro without posts')
check(get('Teen',f'/circles/{cid}').status_code==404,'Age-incompatible discovery blocked')
check(get('Outsider',f'/circles/{cid}/manage').status_code==403,'Outsider cannot manage')
check(post('Member',f'/circles/{cid}/join').status_code==302,'Join request')
check(query('SELECT status FROM circle_members WHERE circle_id=? AND user_id=?',(cid,users['Member']))[0][0]=='pending','Request is not access grant')
check(b'Awaiting approval' in get('Member',f'/circles/{cid}').data,'Pending membership guidance')
check(b'Awaiting approval' in get('Member','/circles').data,'Pending Circle requests have their own list')
notice_count=query("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='circles'",(users['Owner'],))[0][0]
check(notice_count==1,'Join request sends manager inbox notice')
post('Member',f'/circles/{cid}/join')
check(query("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='circles'",(users['Owner'],))[0][0]==notice_count,'Repeated request does not duplicate notification')
check(manage('Owner',cid,'approve',user_id=users['Member']).status_code==302,'Owner approves member')
check(get('Member',f'/circles/{cid}').status_code==200,'Member feed template')
check(b'Your Circle membership request was approved.' in get('Member','/notifications').data,'Approval inbox notice')
check(post('Owner',f'/circles/{cid}/manage',action='settings',name='Fixture Circle',description='Fictional Circle only',mode='discoverable',rules='Be kind. <script>not markup</script>').status_code==302,'Owner records Circle rules')
intro=get('Outsider',f'/circles/{cid}').data
check(b'Be kind. &lt;script&gt;' in intro and b'<script>not markup' not in intro,'Joining rules displayed as escaped text')
check(manage('Member',cid,'pin',post_id='').status_code==403,'Ordinary member cannot pin')
check(post('Owner',f'/circles/{cid}/manage',action='settings',name='Fixture Circle',mode='discoverable',rules='x'*5001).status_code==400,'Oversized rules rejected')
check(get('Owner',f'/circles/{cid}/manage').status_code==200,'Actual Circle management template')
check(post('Outsider',f'/circles/{cid}/join').status_code==302,'Second pending request')
check(post('Owner',f'/circles/{cid}/manage',action='decline',user_id=users['Outsider']).status_code==302,'Declining does not require a reason')
check(query("SELECT reason FROM circle_events WHERE circle_id=? AND action='decline' ORDER BY id DESC LIMIT 1",(cid,))[0][0]=='','Decline without reason retains an honest empty audit note')
check(post('Outsider',f'/circles/{cid}/join').status_code==302,'Declined requester can submit a fresh request')
check(manage('Owner',cid,'decline',user_id=users['Outsider']).status_code==302,'Decline pending membership')
change("INSERT INTO privacy_settings(user_id,requests_from) VALUES (?,'nobody')",(users['Outsider'],))
check(manage('Owner',cid,'invite',handle='@CircleFixtureOutsider').status_code==403,'Invitation respects request privacy')
check(manage('Owner',cid,'invite',handle='@CircleFixtureTeen').status_code==400,'Age-incompatible invitation blocked')
icon=io.BytesIO();Image.new('RGB',(24,24),'green').save(icon,format='PNG');icon.seek(0)
check(clients['Owner'].post(f'/circles/{cid}/manage',data={'action':'settings','name':'Fixture Circle','description':'Fictional Circle only','mode':'discoverable','theme_csrf_token':token,'icon':(icon,'icon.png')}).status_code==302,'Safe Circle image upload')
icon_response=get('Member',f'/circles/{cid}/icon')
check(icon_response.status_code==200 and icon_response.mimetype=='image/png' and 'no-store' in icon_response.headers['Cache-Control'],'Private uncached icon retrieval')
icon_response.close()
check(clients['Owner'].post(f'/circles/{cid}/manage',data={'action':'settings','name':'Fixture Circle','description':'','mode':'discoverable','theme_csrf_token':token,'icon':(io.BytesIO(b'<svg onload="alert(1)"></svg>'),'evil.svg')}).status_code==400,'Active image formats rejected')
check(get('Owner',f'/create_post?circle_id={cid}').status_code==200,'Actual Circle composer template')
profile=get('Owner','/@CircleFixtureOwner')
check(profile.status_code==200 and b'name="circle_id"' in profile.data and b'Fixture Circle#' in profile.data,'Profile New Post offers actual Circle memberships')
check(('value="'+opaque+'"').encode() in profile.data and ('Fixture Circle#'+format(query('SELECT name_number FROM circles WHERE id=?',(cid,))[0][0],'04d')).encode() in profile.data,'Profile selection uses opaque ID and display label uses padded number')
check(b'name="circle_id"' not in get('Member','/@CircleFixtureOwner').data,'Guestbook does not offer a private Circle destination')
image=io.BytesIO();Image.new('RGB',(32,32),'blue').save(image,format='PNG');image.seek(0)
response=clients['Owner'].post('/create_post',data={'content':'PRIVATE CIRCLE SENTINEL','circle_id':public_circle(cid),'audience':'public','vibes':'Fresh Starts','theme_csrf_token':token,'post_image':(image,'fixture.png')})
check(response.status_code==302,'Actual post with image')
pid=query('SELECT post_id FROM circle_posts WHERE circle_id=?',(cid,))[0][0]
with app.app_context():
    db=core.get_db();public=core.identifiers.public(db,'post',pid)
media=query('SELECT filename FROM post_media WHERE post_id=?',(pid,))[0][0]
check(not query('SELECT 1 FROM post_vibes WHERE post_id=?',(pid,)),'Circle cannot cross-post to Vibe')
check(query('SELECT audience FROM post_privacy WHERE post_id=?',(pid,))[0][0]=='private','Forged public audience cannot publish Circle post')
for key, expected in [('Owner',200),('Member',200),('Outsider',404)]:
    for path in (f'/posts/{public}',f'/posts/{public}/history',f'/media-file/{media}'):
        # History URL is generated from the real endpoint below.
        if path.endswith('/history'):
            with app.test_request_context():path=core.url_for('post_edit_history',post_id=pid)
        check(get(key,path).status_code==expected,key+' private URL '+path.split('/')[1])
check(b'PRIVATE CIRCLE SENTINEL' not in get('Outsider','/feed').data,'No content in outsider feed')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Outsider',f'/circles/{cid}').data,'No content in public intro')
check(b'PRIVATE CIRCLE SENTINEL' in get('Member',f'/circles/{cid}').data,'Member Circle feed content')
change('DELETE FROM circle_reads WHERE circle_id=? AND user_id=?',(cid,users['Member']))
check(b'1 new post' in get('Member','/circles').data,'Unread activity shown for accessible post by another member')
get('Member',f'/circles/{cid}?q=NO_MATCH_SENTINEL')
check(not query('SELECT 1 FROM circle_reads WHERE circle_id=? AND user_id=?',(cid,users['Member'])),'Search does not mark Circle activity read')
check(b'PRIVATE CIRCLE SENTINEL' in get('Member',f'/circles/{cid}?q=PRIVATE').data,'Circle post search finds permitted content')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Member',f'/circles/{cid}?q=NO_MATCH_SENTINEL').data,'Circle search filters feed')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Outsider',f'/circles/{cid}?q=PRIVATE').data,'Nonmember search cannot expose content')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Member',f'/circles/{cid}?q=%25').data,'Search wildcard is treated literally')
get('Member',f'/circles/{cid}')
check(query('SELECT last_post_id FROM circle_reads WHERE circle_id=? AND user_id=?',(cid,users['Member']))[0][0]>=pid,'Opening Circle marks visible activity read')
check(b'1 new post' not in get('Member','/circles').data,'Read Circle removes unread badge')
check(manage('Owner',cid,'pin',post_id=public).status_code==302,'Owner pins existing Circle post')
check(b'Pinned welcome post' in get('Member',f'/circles/{cid}').data,'Pinned post identified in shared feed')
check(manage('Owner',hidden,'pin',post_id=public).status_code==400,'Cannot pin a post from another Circle')
check(manage('Owner',cid,'pin',post_id='bad-id').status_code==400,'Malformed pinned ID rejected')
check(manage('Owner',cid,'pin',post_id='').status_code==302,'Owner can remove pin')
check(query('SELECT pinned_post_id FROM circles WHERE id=?',(cid,))[0][0] is None,'Removing pin clears stored selection')
manage('Owner',cid,'pin',post_id=public)
check(b'CircleFixtureMember' in get('Owner',f'/circles/{cid}/manage?member_q=Member').data and b'@CircleFixtureOutsider \xc2\xb7 Member' not in get('Owner',f'/circles/{cid}/manage?member_q=Member').data,'Member search narrows roster without expanding access')
check(b'Fictional membership decision' in get('Owner',f'/circles/{cid}/manage').data,'Management history includes recorded reason')
check(get('Owner','/feed').data.count(b'id="site-search-query"')==1,'One shared header search field')
check(b'name="scope"' in get('Owner','/feed').data and b'City' in get('Owner','/feed').data,'Header offers checkbox categories')
check(app.test_client().get('/search?q=Fixture').status_code==302,'General search requires sign-in')
check(get('Member','/search?q=PRIVATE&scopes_present=1&scope=posts').status_code==200,'General post search opens')
search_posts=get('Member','/search?q=PRIVATE&scopes_present=1&scope=posts')
check(b'PRIVATE CIRCLE SENTINEL' in search_posts.data and ('/posts/'+public).encode() in search_posts.data,'Global search finds authorized Circle posts using public URLs')
check(b'no-store' in search_posts.headers['Cache-Control'].encode() and search_posts.headers['Referrer-Policy']=='same-origin','Search response protects query and private results')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Outsider','/search?q=PRIVATE&scopes_present=1&scope=posts').data,'Global search hides members-only posts from outsiders')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Teen','/search?q=PRIVATE&scopes_present=1&scope=posts').data,'General search respects age restrictions')
check(b'PRIVATE CIRCLE SENTINEL' not in get('Member','/search?q=%25%25&scopes_present=1&scope=posts').data,'General search treats SQL wildcard characters literally')
check(b'Choose at least one search category.' in get('Member','/search?q=PRIVATE&scopes_present=1').data,'Unchecked categories do not silently search everything')
check(b'Enter at least two characters' in get('Member','/search?q=P').data,'Short search has helpful guidance')
check(get('Member','/search?q='+('x'*121)).status_code==400,'Overlong search rejected')
check(get('Member','/search?q=PRIVATE&page=-1').status_code==400,'Invalid search page rejected')
check(b'&lt;script&gt;' in get('Member','/search?q=%3Cscript%3E').data,'Search text is escaped')
check(b'CircleFixtureOwner' in get('Member','/search?q=CircleFixtureOwner&scopes_present=1&scope=username').data,'Username search finds visible handles')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Member'],users['Owner']))
check(b'Post by @CircleFixtureOwner' not in get('Member','/search?q=PRIVATE&scopes_present=1&scope=posts').data,'Blocked author disappears from general post search')
check(b'@CircleFixtureOwner</a>' not in get('Member','/search?q=CircleFixtureOwner&scopes_present=1&scope=username').data,'Blocked profile disappears from username results')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Member'],users['Owner']))
check(('Fixture Circle#'+format(query('SELECT name_number FROM circles WHERE id=?',(hidden,))[0][0],'04d')).encode() not in get('Outsider','/search?q=Fixture&scopes_present=1&scope=circles').data,'Hidden Circle name and ID excluded from general search')
check(('/circles/'+opaque).encode() in get('Outsider','/search?q=Fixture&scopes_present=1&scope=circles').data,'Discoverable Circle uses public URL in search')
change("UPDATE users SET location='CityFixtureMedford' WHERE id=?",(users['Owner'],))
check(b'CityFixtureMedford</p>' in get('Member','/search?q=CityFixtureMedford&scopes_present=1&scope=city').data,'City search uses shared profile location')
change('INSERT INTO privacy_settings(user_id,field_audiences) VALUES (?,?)',(users['Owner'],'{"location":"private"}'))
check(b'@CircleFixtureOwner</a>' not in get('Member','/search?q=CityFixtureMedford&scopes_present=1&scope=city').data,'Private city cannot create a match')
change('UPDATE privacy_settings SET field_audiences=? WHERE user_id=?',('{"location":"public"}',users['Owner']))
change("INSERT INTO privacy_settings(user_id,profile_audience) VALUES (?,'private')",(users['Moderator'],))
check(b'@CircleFixtureModerator</a>' not in get('Member','/search?q=CircleFixtureModerator&scopes_present=1&scope=username').data,'Private profiles excluded from username search')
change('DELETE FROM privacy_settings WHERE user_id=?',(users['Moderator'],))

with app.app_context():
    temp_db=core.get_db();paging_posts=[]
    for index in range(21):
        paging_id=core.identifiers.next_post_key(temp_db)
        temp_db.execute("INSERT INTO posts(id,user_id,content,circle,created_at) VALUES (?,?,?,'private','2099-01-01')",(paging_id,users['Owner'],'PAGING FIXTURE '+str(index)))
        core.identifiers.ensure(temp_db,'post',paging_id)
        temp_db.execute("INSERT INTO post_privacy VALUES (?,'private')",(paging_id,))
        temp_db.execute('INSERT INTO circle_posts VALUES (?,?)',(paging_id,cid))
        paging_posts.append(paging_id)
    temp_db.commit()
paged=get('Member',f'/circles/{cid}').data
check(paged.index(b'PRIVATE CIRCLE SENTINEL')<paged.index(b'PAGING FIXTURE'),'Pinned post sorts above newer posts')
check(b'Pinned welcome post' not in get('Member',f'/circles/{cid}?page=2').data,'Pin does not repeat on later pages')
check(b'q=PAGING' in get('Member',f'/circles/{cid}?q=PAGING').data,'Search pagination keeps query')
check(b'PAGING FIXTURE' in get('Member',f'/circles/{cid}?q=PAGING&page=2').data,'Search results paginate')
check(b'Next' in get('Member','/search?q=PAGING&scopes_present=1&scope=posts').data,'General search offers bounded pagination')
check(b'PAGING FIXTURE' in get('Member','/search?q=PAGING&scopes_present=1&scope=posts&page=2').data,'General search shows next page of permitted posts')
with app.app_context():
    temp_db=core.get_db()
    for paging_id in paging_posts:temp_db.execute('DELETE FROM posts WHERE id=?',(paging_id,))
    temp_db.commit()

check(media.encode() in get('Member',f'/circles/{cid}').data,'Vibe gallery reuse includes attached image')
check(b'data-reaction-url=' in get('Member',f'/circles/{cid}').data and b'js/reactions.js' in get('Member',f'/circles/{cid}').data,'Circle renders both reaction destinations and shared click handler')
with app.app_context(), patch.object(cf.welcome,'staff',return_value=True):
    check(not cf.visible_post(core.get_db(),pid,users['Outsider']),'Site staff status alone does not grant Circle access')
check(post('Outsider',f'/react/{public}',emoji='👍').status_code==404,'Nonmember cannot react')
check(post('Outsider','/create_comment',post_id=public,content='attempt').status_code==404,'Nonmember cannot comment')
check(post('Member',f'/react/{public}',emoji='👍').status_code==200,'Member reaction uses existing route')
check(post('Outsider','/create_post',content='FORGED',circle_id=cid,audience='public').status_code==404,'Forged Circle posting blocked')
check(post('Member','/create_comment',post_id=public,content='PRIVATE REPLY').status_code==201,'Member comment uses existing route')
comment=query('SELECT id FROM comments WHERE post_id=?',(pid,))[0][0]
with app.app_context():comment_public=core.identifiers.public(core.get_db(),'comment',comment)
check(post('Owner',f'/edit_post/{public}',content='PRIVATE EDITED SENTINEL',vibes='Fresh Starts',circle='public',audience='public').status_code==302,'Circle post edit works')
check(query('SELECT audience FROM post_privacy WHERE post_id=?',(pid,))[0][0]=='private' and not query('SELECT 1 FROM post_vibes WHERE post_id=?',(pid,)),'Edit cannot change private destination')
check(get('Owner',f'/edit_post/{public}').status_code==200,'Circle edit template')
with app.test_request_context():history_path=core.url_for('post_edit_history',post_id=pid)
check(b'PRIVATE CIRCLE SENTINEL' not in get('Outsider',history_path).data,'History content does not leak')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Member'],users['Owner']))
check(get('Member',f'/posts/{public}').status_code==404,'Member block suppresses Circle content')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Member'],users['Owner']))
check(manage('Owner',cid,'remove',user_id=users['Member']).status_code==302,'Remove member')
for path in (f'/posts/{public}',f'/media-file/{media}'):
    check(get('Member',path).status_code==404,'Removal revokes direct access')
check(post('Member',f'/edit_comment/{comment_public}',content='attempt').status_code==404,'Removal blocks comment editing')
check(post('Member',f'/circles/{cid}/join').status_code==403,'Removed member cannot bypass with join request')
check(manage('Owner',cid,'invite',handle='@CircleFixtureMember').status_code==302,'Reinvite removed member')
check(post('Member',f'/circles/{cid}/join').status_code==302,'Recipient accepts invitation')
check(get('Member',f'/posts/{public}').status_code==200,'Joining restores historical post access')
check(post('Member',f'/circles/{cid}/leave').status_code==302,'Leave Circle')
check(get('Member',f'/posts/{public}').status_code==404,'Leaving ends historical access')
check(manage('Owner',hidden,'invite',handle='@CircleFixtureMember').status_code==302,'Hidden invitation')
check(get('Member',f'/circles/{hidden}').status_code==200,'Invited user sees hidden introduction')
with app.app_context():
    hidden_notice=core.get_db().execute("SELECT * FROM notifications WHERE user_id=? AND path=? ORDER BY id DESC LIMIT 1",(users['Member'],'/circles/'+hidden_opaque)).fetchone()
    check(bool(hidden_notice) and cf.notification_visible(core.get_db(),hidden_notice,users['Member']),'Hidden invitation inbox notice is initially visible')
check(clients['Member'].get(f'/circles/{hidden}').status_code==302,'Authorized hidden invitation permits legacy redirect')
iid=query("SELECT id FROM circle_invitations WHERE circle_id=? AND status='pending'",(hidden,))[0][0]
check(manage('Owner',hidden,'revoke_invite',invitation_id=iid).status_code==302,'Revoke hidden invitation')
check(get('Member',f'/circles/{hidden}').status_code==404,'Revocation hides hidden intro')
with app.app_context():check(not cf.notification_visible(core.get_db(),hidden_notice,users['Member']),'Revoked invitation disappears from notification visibility')
check(clients['Member'].get(f'/circles/{hidden}').status_code==404,'Revoked invitation also denies the legacy link')
check(manage('Owner',hidden,'invite',handle='@CircleFixtureMember').status_code==302,'New invitation')
change("UPDATE circle_invitations SET expires_at='2000-01-01' WHERE circle_id=?",(hidden,))
check(get('Member',f'/circles/{hidden}').status_code==404,'Expired invitation cannot reveal hidden info')
change("INSERT INTO notification_settings VALUES (?,'circles',0)",(users['Moderator'],))
check(manage('Owner',cid,'invite',handle='@CircleFixtureModerator').status_code==302,'Invite moderator candidate')
check(not query("SELECT 1 FROM notifications WHERE user_id=? AND kind='circles'",(users['Moderator'],)),'Circle notification preference honored')
check(post('Moderator',f'/circles/{cid}/join').status_code==302,'Accept moderator candidate')
check(manage('Owner',cid,'moderator',user_id=users['Moderator']).status_code==302,'Owner grants Circle moderator role')
check(manage('Moderator',cid,'settings',name='Hijack',description='',mode='discoverable').status_code==403,'Moderator cannot alter owner settings')
check(manage('Moderator',cid,'pin',post_id=public).status_code==302,'Moderator may manage pin')
check(manage('Moderator',cid,'remove',user_id=users['Owner']).status_code==400,'Moderator cannot remove owner')
check(post('Owner',f'/circles/{cid}/leave').status_code==400,'Owner must transfer before leaving')
check(manage('Owner',cid,'transfer',user_id=users['Moderator']).status_code==302,'Ownership transfer')
check(manage('Owner',cid,'settings',name='Hijack',description='',mode='discoverable').status_code==403,'Former owner loses owner privileges')
followers=create('followers')
check(get('Member',f'/circles/{followers}').status_code==404,'Follower Circle requires following owner')
change('INSERT INTO follows(follower_id,followed_id,revoked) VALUES (?,?,0)',(users['Member'],users['Owner']))
check(post('Member',f'/circles/{followers}/join').status_code==302,'Follower requests membership')
check(query('SELECT status FROM circle_members WHERE circle_id=? AND user_id=?',(followers,users['Member']))[0][0]=='pending','Following is not automatic membership')
check(manage('Owner',followers,'approve',user_id=users['Member']).status_code==302,'Approve follower membership')
change('UPDATE follows SET revoked=1 WHERE follower_id=? AND followed_id=?',(users['Member'],users['Owner']))
check(get('Member',f'/circles/{followers}').status_code==404,'Unfollowing ends follower Circle access')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Moderator'],users['Owner']))
check(get('Owner',f'/posts/{public}').status_code==404,'Owner block ends former owner member access')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Moderator'],users['Owner']))
check(manage('Moderator',cid,'archive').status_code==302,'Owner archives Circle')
check(get('Moderator',f'/posts/{public}').status_code==404,'Archive denies former post URLs')
check(query('SELECT id FROM posts WHERE id=?',(pid,)),'Archive preserves content')
check(post('Outsider',f'/circles/{cid}/restore').status_code==404,'Only owner can restore archived Circle')
check(b'Restore Circle' in get('Moderator','/circles').data,'Owner can find archive recovery')
check(post('Moderator',f'/circles/{cid}/restore').status_code==302,'Owner restores Circle')
check(get('Moderator',f'/posts/{public}').status_code==200,'Restoration re-enables eligible memberships')
check(app.test_client().get(f'/posts/{public}').status_code==404,'Anonymous private post denied')
change("INSERT INTO account_disables(user_id,disabled,reason,updated_by) VALUES (?,1,'Fixture disable',1)",(users['Moderator'],))
with app.app_context():check(not circles.post_allowed(core.get_db(),pid,users['Owner']),'Disabled owner stops access')
change('DELETE FROM account_disables WHERE user_id=?',(users['Moderator'],))
change('DELETE FROM circles WHERE id=?',(cid,))
with app.app_context():check(circles.post_allowed(core.get_db(),pid,users['Owner']) is False,'Orphaned Circle mapping fails closed')
check(post('Owner','/create_post',content='ORDINARY PUBLIC SENTINEL',vibes='',circle='Legacy label',audience='public').status_code==302,'Ordinary post creation preserved')
ordinary=query("SELECT id FROM posts WHERE content='ORDINARY PUBLIC SENTINEL'")[0][0]
with app.app_context():ordinary_public=core.identifiers.public(core.get_db(),'post',ordinary)
check(app.test_client().get(f'/posts/{ordinary_public}').status_code==200,'Ordinary public posts remain public')
check(b'ORDINARY PUBLIC SENTINEL' in get('Owner','/feed?q=NO_MATCH_SENTINEL').data,'Circle search does not change ordinary feed behavior')
check(not query('SELECT 1 FROM circle_posts WHERE post_id=?',(ordinary,)),'Legacy text does not create private membership')
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(ordinary,))
check(get('Outsider',f'/posts/{ordinary_public}').status_code==404,'Ordinary private audience preserved')
check(get('Owner',f'/posts/{ordinary_public}').status_code==200,'Ordinary private author access preserved')
check(not app.config['RETENTION_ENABLED'],'Permanent erasure remains disabled')
# Opening notifications keeps history and enforces recipient ownership and CSRF.
for kind in cf.KINDS:
    change("INSERT INTO notifications(user_id,kind,message,path) VALUES (?,?,?,?)",(users['Owner'],kind,'Fixture view '+kind,'/@CircleFixtureOwner'))
    nid=query('SELECT MAX(id) FROM notifications')[0][0]
    check(clients['Owner'].post('/notifications',data={'action':'view','id':nid}).status_code==400,'Notification view CSRF '+kind)
    check(post('Outsider','/notifications',action='view',id=nid).status_code==404,'Notification recipient isolation '+kind)
    check(query('SELECT read_at FROM notifications WHERE id=?',(nid,))[0][0] is None,'Rejected view leaves unread '+kind)
    response=post('Owner','/notifications',action='view',id=nid)
    check(response.status_code==303 and response.location=='/@CircleFixtureOwner','Notification destination '+kind)
    stamp=query('SELECT read_at FROM notifications WHERE id=?',(nid,))[0][0]
    check(bool(stamp),'Notification read timestamp '+kind)
    check(('Fixture view '+kind).encode() in get('Owner','/notifications').data,'Read notification retained '+kind)
    post('Owner','/notifications',action='view',id=nid)
    check(query('SELECT read_at FROM notifications WHERE id=?',(nid,))[0][0]==stamp,'Repeat view preserves timestamp '+kind)
for unsafe in ['//example.invalid','/\\example.invalid','/%2fexample.invalid','/account%0d%0aX:test']:
    change("INSERT INTO notifications(user_id,kind,message,path) VALUES (?,'moderation','unsafe',?)",(users['Owner'],unsafe))
    nid=query('SELECT MAX(id) FROM notifications')[0][0]
    check(post('Owner','/notifications',action='view',id=nid).status_code==400,'Unsafe notification destination refused')
    check(query('SELECT read_at FROM notifications WHERE id=?',(nid,))[0][0] is None,'Unsafe destination remains unread')
# Circle report boundaries and opt-in new-post alerts.
from neonrest import circle_tools, privacy_workflows
extra_cid=create();other_cid=create();extra_token=public_circle(extra_cid)
for key,role in [('Member','member'),('Moderator','moderator'),('Outsider','member')]:
    change("INSERT INTO circle_members VALUES (?,?,?,'active',CURRENT_TIMESTAMP)",(extra_cid,users[key],role))
check(b'What Circle roles can do' in get('Member',f'/circles/{extra_cid}').data,'Member role guidance rendered')
check(b'Open Circle report queue' in get('Moderator',f'/circles/{extra_cid}/manage').data,'Moderator report queue entry')
check(not query('SELECT 1 FROM circle_post_preferences'),'New-post notifications default off')
check(post('Member','/create_post',circle_id=extra_cid,content='TOOLS REPORT TARGET',audience='private').status_code==302,'Create tools target')
tools_pid=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(extra_cid,))[0][0]
with app.app_context():tools_public=core.identifiers.public(core.get_db(),'post',tools_pid)
check(not query("SELECT 1 FROM notifications WHERE kind='circle_posts' AND path=?",('/posts/'+tools_public,)),'No notices without Circle opt-in')
report_path=f'/circles/{extra_token}/report/post/{tools_public}'
check(get('Outsider',report_path).status_code==200,'Explicit Circle report sharing form')
check(b'Report to Circle managers' in get('Outsider',f'/circles/{extra_cid}').data,'Shared post menu offers Circle reporting')
check(clients['Outsider'].post(report_path,data={'reason':'Fictional issue without csrf'}).status_code==400,'Circle report CSRF required')
check(post('Member',report_path,reason='Cannot report own content').status_code==403,'Self report denied')
check(post('Outsider',report_path,reason='short').status_code==400,'Report reason bounds')
check(post('Outsider',report_path,reason='Fictional Circle concern <script>escaped</script>').status_code==303,'Submit local report')
local_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
check(post('Member',f'/delete_post/{tools_public}').status_code==409,'Open Circle report pauses author deletion')
change("UPDATE posts SET content='EDITED CURRENT TEXT' WHERE id=?",(tools_pid,))
check(b'TOOLS REPORT TARGET' in get('Owner',f'/circles/{extra_cid}/reports').data,'Queue preserves text as reported after an edit')
post('Outsider',report_path,reason='Repeated fictional concern')
check(query('SELECT COUNT(*) FROM circle_reports WHERE target_id=?',(tools_pid,))[0][0]==1,'Duplicate open local report suppressed')
check(not query("SELECT 1 FROM content_reports WHERE target_type='post' AND target_id=?",(tools_pid,)),'Local report does not silently create site report')
check(get('Outsider',f'/circles/{extra_cid}/reports').status_code==403,'Ordinary members cannot read report queue')
queue=get('Owner',f'/circles/{extra_cid}/reports')
check(queue.status_code==200 and b'Fictional Circle concern' in queue.data,'Owner sees eligible local report')
check(b'CircleFixtureOutsider' not in queue.data and b'&lt;script&gt;' in queue.data,'Queue hides reporter handle and escapes explanation')
check(b'Fictional Circle concern' not in get('Member',f'/circles/{extra_cid}/reports').data,'Accused member has no queue access')
# Granting a role never discloses reports about that manager's own content.
change("UPDATE circle_members SET role='moderator' WHERE circle_id=? AND user_id=?",(extra_cid,users['Member']))
check(b'Fictional Circle concern' not in get('Member',f'/circles/{extra_cid}/reports').data,'Accused manager cannot read report about self')
check(post('Member',f'/circles/{extra_cid}/reports',report_id=local_report,action='reviewed',decision='Improper self review').status_code==404,'Accused manager cannot decide report')
check(post('Owner',f'/circles/{other_cid}/reports',report_id=local_report,action='reviewed',decision='Wrong Circle attempt').status_code==404,'Report IDs do not cross Circle scopes')
with app.app_context():
    check('Open Circle report' in privacy_workflows.blockers(core.get_db(),users['Member']),'Open Circle report preserves target account')
    check('Open Circle report' in privacy_workflows.blockers(core.get_db(),users['Outsider']),'Open Circle report preserves reporter account')
check(post('Owner',f'/report/post/{tools_public}',reason='PRIVATE SITE STAFF SENTINEL').status_code==302,'Separate confidential site report')
check(b'PRIVATE SITE STAFF SENTINEL' not in get('Moderator',f'/circles/{extra_cid}/reports').data,'Private site report reason never imported')
check(post('Owner',f'/circles/{extra_cid}/reports',report_id=local_report,action='escalated',decision='Fictional site-rule review requested.').status_code==303,'Manager escalates local report')
check(query('SELECT status FROM circle_reports WHERE id=?',(local_report,))[0][0]=='escalated','Local escalation status recorded')
site_id=query('SELECT site_report_id FROM circle_reports WHERE id=?',(local_report,))[0][0]
check(bool(query("SELECT 1 FROM case_links WHERE kind='report' AND item_id=?",(site_id,))),'Escalation uses existing site evidence case workflow')
check(any('TOOLS REPORT TARGET' in r[0] for r in query('SELECT snapshot FROM case_evidence WHERE report_id=?',(site_id,))),'Escalation preserves original report snapshot for site staff')
check(not any('Fictional site-rule review requested' in r[0] for r in query('SELECT reason FROM circle_events WHERE circle_id=?',(extra_cid,))),'Detailed report decision stays out of general manager history')
check(post('Owner',f'/circles/{extra_cid}/reports',report_id=local_report,action='reviewed',decision='Already completed stale update').status_code==409,'Stale report review rejected')
check(post('Moderator',report_path,reason='Fictional second Circle concern').status_code==303,'Manager may submit report for another reviewer')
second_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
check(post('Moderator',f'/circles/{extra_cid}/reports',report_id=second_report,action='reviewed',decision='Cannot review own submission').status_code==403,'Reporter cannot review own report')
check(post('Owner',f'/circles/{extra_cid}/reports',report_id=second_report,action='reviewed',decision='Fictional review complete; no Circle action.').status_code==303,'Record completed local review')
check(b'Fictional review complete' in get('Owner',f'/circles/{extra_cid}/reports?status=reviewed').data,'Reviewed queue retains decision')
check(get('Owner',f'/circles/{extra_cid}/reports?status=bogus').status_code==400,'Report filter validated')
check(get('Owner',f'/circles/{other_cid}/report/post/{tools_public}').status_code==404,'Cannot report content into another Circle')
# Comment targets use the same Circle, visibility and conflict checks.
reply=post('Moderator','/create_comment',post_id=tools_public,content='TOOLS COMMENT TARGET')
check(reply.status_code==201,'Create comment report target')
comment_token=reply.json['id']
check(post('Outsider',f'/circles/{extra_token}/report/comment/{comment_token}',reason='Fictional comment concern for managers').status_code==303,'Circle comment report works')
check(b'TOOLS COMMENT TARGET' in get('Owner',f'/circles/{extra_cid}/reports').data,'Comment report excerpt visible to eligible manager')
comment_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(tools_pid,users['Member'],users['Owner'],'Fictional staff hiding'))
unavailable=get('Owner',f'/circles/{extra_cid}/reports')
check(b'TOOLS COMMENT TARGET' not in unavailable.data and b'Fictional comment concern' not in unavailable.data,'Unavailable content and private report explanation remain hidden')
check(post('Owner',f'/circles/{extra_cid}/reports',report_id=comment_report,action='reviewed',decision='Cannot read hidden content').status_code==409,'Unavailable content requires site escalation')
check(post('Owner',f'/circles/{extra_cid}/reports',report_id=comment_report,action='escalated',decision='Staff review needed for unavailable content.').status_code==303,'Manager can escalate unavailable item without seeing private text')
change('DELETE FROM moderated_posts WHERE post_id=?',(tools_pid,))
for _ in range(22):
    change("INSERT INTO circle_reports(circle_id,reporter_id,target_type,target_id,reason,author_id,post_owner_id,snapshot,status,decision) SELECT circle_id,reporter_id,target_type,target_id,reason,author_id,post_owner_id,snapshot,'reviewed','Fictional pagination decision' FROM circle_reports WHERE id=?",(local_report,))
check(get('Owner',f'/circles/{extra_cid}/reports?status=reviewed').data.count(b'Text as reported:')==20,'Report queue limits visible page to twenty records')
check(b'Fictional pagination decision' in get('Owner',f'/circles/{extra_cid}/reports?status=reviewed&page=2').data,'Report queue next page contains remaining records')

# Per-Circle choice, global preference, self-exclusion, mute and revoked access.
for key in ('Owner','Outsider','Moderator'):
    check(post(key,f'/circles/{extra_cid}/notifications',action='enable').status_code==303,'Explicit Circle alert opt-in '+key)
check(clients['Outsider'].post(f'/circles/{extra_token}/notifications',data={'action':'mute'}).status_code==400,'Alert changes require CSRF')
change("INSERT INTO notification_settings VALUES (?,'circle_posts',0) ON CONFLICT(user_id,kind) DO UPDATE SET enabled=0",(users['Moderator'],))
check(post('Owner','/create_post',circle_id=extra_cid,content='TOOLS ALERT POST',audience='private').status_code==302,'Create opted-in alert post')
alert_pid=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(extra_cid,))[0][0]
with app.app_context():alert_public=core.identifiers.public(core.get_db(),'post',alert_pid)
notices=query("SELECT * FROM notifications WHERE kind='circle_posts' AND path=?",('/posts/'+alert_public,))
check(len(notices)==1 and notices[0]['user_id']==users['Outsider'],'Only eligible opted-in recipient notified; global off and self excluded')
check(b'Mute new posts from' in get('Outsider','/notifications').data,'Inbox offers per-Circle mute')
check(post('Outsider',f'/circles/{extra_cid}/notifications',action='mute',return_to='notifications').status_code==303,'Mute from notification inbox')
post('Owner','/create_post',circle_id=extra_cid,content='TOOLS MUTED POST',audience='private')
check(len(query("SELECT * FROM notifications WHERE user_id=? AND kind='circle_posts' AND path LIKE '/posts/%'",(users['Outsider'],)))==1,'Muted Circle sends no future posts; history retained')
post('Outsider',f'/circles/{extra_cid}/notifications',action='enable')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Outsider'],users['Owner']))
post('Member','/create_post',circle_id=extra_cid,content='TOOLS INELIGIBLE POST',audience='private')
check(len(query("SELECT * FROM notifications WHERE user_id=? AND kind='circle_posts'",(users['Outsider'],)))==1,'Lost eligibility prevents new-post delivery')
check(b'A new post was shared' not in get('Outsider','/notifications').data,'Lost eligibility hides existing post notification')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Outsider'],users['Owner']))
check(post('Outsider',f'/circles/{extra_cid}/leave').status_code==302,'Member leaves alert Circle')
check(query('SELECT enabled FROM circle_post_preferences WHERE circle_id=? AND user_id=?',(extra_cid,users['Outsider']))[0][0]==0,'Leaving clears opt-in')
check(post('Outsider',f'/circles/{extra_cid}/notifications',action='enable').status_code==403,'Former member cannot enable Circle alerts')
check(get('Outsider',report_path).status_code==403,'Former member cannot submit Circle reports')
change("INSERT INTO circle_members VALUES (?,?,'member','active',CURRENT_TIMESTAMP)",(other_cid,users['Outsider']))
post('Outsider',f'/circles/{other_cid}/notifications',action='enable')
check(manage('Owner',other_cid,'archive').status_code==302,'Archive alert Circle')
check(query('SELECT enabled FROM circle_post_preferences WHERE circle_id=? AND user_id=?',(other_cid,users['Outsider']))[0][0]==0,'Archiving clears Circle opt-in')
# Report actions actually change content visibility and are reversible.
change("DELETE FROM rate_buckets WHERE action='circle_changes'")
action_cid=create();action_token=public_circle(action_cid)
for key,role in [('Member','member'),('Moderator','moderator'),('Outsider','member')]:
    change("INSERT INTO circle_members VALUES (?,?,?,'active',CURRENT_TIMESTAMP)",(action_cid,users[key],role))
check(post('Member','/create_post',circle_id=action_cid,content='ACTION POST SENTINEL',audience='private').status_code==302,'Create actionable Circle post')
action_pid=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(action_cid,))[0][0]
with app.app_context():action_public=core.identifiers.public(core.get_db(),'post',action_pid)
response=post('Moderator','/create_comment',post_id=action_public,content='ACTION COMMENT SENTINEL')
action_comment=response.json['id']
response=post('Member','/create_comment',post_id=action_public,parent_comment_id=action_comment,content='ACTION DESCENDANT SENTINEL')
action_child=response.json['id']
report_path=f'/circles/{action_token}/report/post/{action_public}'
post('Outsider',report_path,reason='PRACTICE ONLY: approve this fictional content')
approve_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
queue=get('Owner',f'/circles/{action_cid}/reports')
check(b'Approve / keep content' in queue.data and b'Remove from Circle' in queue.data,'Queue exposes actionable approve and remove buttons')
check(post('Owner',f'/circles/{action_cid}/reports',report_id=approve_report,action='approve',decision='Fictional content complies with Circle rules.').status_code==303,'Approve report action')
check(query('SELECT status,resolution FROM circle_reports WHERE id=?',(approve_report,))[0][:]==('reviewed','approved'),'Approval outcome recorded separately from queue status')
check(get('Outsider',f'/posts/{action_public}').status_code==200,'Approved content remains visible')
post('Outsider',report_path,reason='PRACTICE ONLY: remove this fictional content')
remove_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
check(clients['Owner'].post(f'/circles/{action_token}/reports',data={'report_id':remove_report,'action':'remove','decision':'No CSRF provided'}).status_code==400,'Content removal requires CSRF')
check(post('Outsider',f'/circles/{action_cid}/reports',report_id=remove_report,action='remove',decision='Not a manager attempt').status_code==403,'Ordinary member cannot remove reported content')
check(post('Owner',f'/circles/{other_cid}/reports',report_id=remove_report,action='remove',decision='Wrong Circle attempt').status_code in (403,404),'Cannot remove content through another Circle')
check(post('Owner',f'/circles/{action_cid}/reports',report_id=remove_report,action='remove',decision='Fictional local-rule removal for this test.').status_code==303,'Manager removes reported post')
check(query('SELECT content FROM posts WHERE id=?',(action_pid,))[0][0]=='ACTION POST SENTINEL','Removal preserves original post data')
check(query('SELECT resolution FROM circle_reports WHERE id=?',(remove_report,))[0][0]=='removed','Removal outcome recorded')
for key in ('Owner','Member','Outsider'):
    check(get(key,f'/posts/{action_public}').status_code==404,'Removed post direct link denied '+key)
    check(b'ACTION POST SENTINEL' not in get(key,'/feed').data,'Removed post absent from feed '+key)
check(b'ACTION POST SENTINEL' not in get('Outsider',f'/circles/{action_cid}').data,'Removed post absent from Circle feed')
check(b'Post by @CircleFixtureMember' not in get('Outsider','/search?q=ACTION+POST+SENTINEL&scopes_present=1&scope=posts').data,'Removed post absent from general search')
check(post('Outsider','/create_comment',post_id=action_public,content='Should not be accepted').status_code==404,'Removed post cannot receive new reply')
reviewed=get('Owner',f'/circles/{action_cid}/reports?status=reviewed')
check(b'Restore to Circle' in reviewed.data and b'ACTION POST SENTINEL' in reviewed.data,'Eligible manager can review preserved removal and restore')
change('INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,?)',(action_pid,users['Member'],users['Owner'],'Fictional site restriction'))
check(post('Owner',f'/circles/{action_cid}/reports',report_id=remove_report,action='restore',decision='Cannot clear site restriction').status_code==409,'Circle restore cannot clear site moderation')
check(bool(query('SELECT 1 FROM moderated_posts WHERE post_id=?',(action_pid,))),'Site moderation remains intact')
change('DELETE FROM moderated_posts WHERE post_id=?',(action_pid,))
check(post('Moderator',f'/circles/{action_cid}/reports',report_id=remove_report,action='restore',decision='Fictional restored after local review.').status_code==303,'Eligible moderator can restore removed post')
check(get('Outsider',f'/posts/{action_public}').status_code==200,'Restored post visible to members again')
check(query("SELECT action FROM circle_report_actions WHERE report_id=? ORDER BY id",(remove_report,))[-1][0]=='restored','Restore action and rationale retained')
check(post('Owner',f'/circles/{action_cid}/reports',report_id=remove_report,action='restore',decision='Stale restore should fail').status_code==409,'Repeated restore rejected safely')
comment_path=f'/circles/{action_token}/report/comment/{action_comment}'
post('Outsider',comment_path,reason='PRACTICE ONLY: remove this fictional reply')
comment_report=query('SELECT MAX(id) FROM circle_reports')[0][0]
check(post('Owner',f'/circles/{action_cid}/reports',report_id=comment_report,action='remove',decision='Fictional reply removal for this test.').status_code==303,'Manager removes reported comment')
body=get('Outsider',f'/posts/{action_public}').data
check(b'ACTION COMMENT SENTINEL' not in body and b'ACTION DESCENDANT SENTINEL' not in body,'Removed reply and descendant thread hidden')
check(b'ACTION POST SENTINEL' in body,'Comment removal leaves parent post visible')
check(post('Member','/create_comment',post_id=action_public,parent_comment_id=action_comment,content='Reply to removed comment').status_code==404,'Cannot reply under removed comment')
check(post('Moderator',f'/edit_comment/{action_comment}',content='Editing removed comment').status_code==404,'Removed reply cannot bypass moderation through editing')
check(post('Owner',f'/circles/{action_cid}/reports',report_id=comment_report,action='restore',decision='Fictional reply and thread restored.').status_code==303,'Manager restores comment')
body=get('Outsider',f'/posts/{action_public}').data
check(b'ACTION COMMENT SENTINEL' in body and b'ACTION DESCENDANT SENTINEL' in body,'Restored reply thread is visible again')
check(query('SELECT COUNT(*) FROM comments WHERE post_id=?',(action_pid,))[0][0]==2,'Comment remove and restore never delete replies')
# Notification targets survive report closure and bypass queue pagination safely.
focused=get('Owner',f'/circles/{action_cid}/reports?report_id={approve_report}')
check(focused.status_code==200 and b'Outcome: Approved' in focused.data,'Closed approved report has a stable detail view')
check(('id="circle-report-'+str(approve_report)+'"').encode() in focused.data,'Report detail has a stable anchor')
check(b'Fictional local-rule removal' not in focused.data,'Detail view shows only selected report')
check(get('Owner',f'/circles/{extra_cid}/reports?report_id={second_report}').status_code==200,'Older completed report opens beyond first queue page')
check(get('Owner',f'/circles/{action_cid}/reports?report_id={second_report}').status_code==404,'Report detail cannot cross Circle scope')
check(get('Member',f'/circles/{action_cid}/reports?report_id={approve_report}').status_code==403,'Ordinary member cannot open manager report detail')
for invalid in ('0','-1','bogus','9'*19):
    check(get('Owner',f'/circles/{action_cid}/reports?report_id={invalid}').status_code==404,'Malformed report detail identifier rejected')
check(get('Owner',f'/circles/{action_cid}/reports?report_id=99999999').status_code==404,'Missing report detail returns unavailable')
with app.app_context():
    db=core.get_db();notice=db.execute("SELECT * FROM notifications WHERE user_id=? AND path=? ORDER BY id DESC LIMIT 1",(users['Owner'],f'/circles/{action_token}/reports?report_id={approve_report}#circle-report-{approve_report}')).fetchone()
    check(bool(notice) and cf.notification_visible(db,notice,users['Owner']),'Report notification remains available after closure')
notice_view=post('Owner','/notifications',action='view',id=notice['id'])
check(notice_view.status_code==303 and notice_view.location.endswith(f'/reports?report_id={approve_report}#circle-report-{approve_report}'),'View opens exact completed report and anchor')
check(query('SELECT read_at FROM notifications WHERE id=?',(notice['id'],))[0][0] is not None,'Following completed report marks notification read')
change("UPDATE circle_members SET role='member' WHERE circle_id=? AND user_id=?",(action_cid,users['Moderator']))
check(get('Moderator',f'/circles/{action_cid}/reports?report_id={approve_report}').status_code==403,'Role removal revokes report detail access')
change("UPDATE circle_members SET role='moderator' WHERE circle_id=? AND user_id=?",(action_cid,users['Moderator']))
change("UPDATE circle_members SET role='moderator' WHERE circle_id=? AND user_id=?",(action_cid,users['Member']))
check(get('Member',f'/circles/{action_cid}/reports?report_id={approve_report}').status_code==404,'Accused manager cannot open specific report about self')
change("UPDATE circle_reports SET created_at='2026-10-16 03:00:00' WHERE id=?",(approve_report,))
change("INSERT INTO notifications(user_id,actor_id,kind,message,path,created_at,read_at) VALUES (?,?,'circles','A Circle report is waiting for review.',?,'2026-10-16 03:00:00','2026-10-16 03:01:00')",(users['Owner'],users['Outsider'],'/circles/'+action_token+'/reports'))
legacy_nid=query('SELECT MAX(id) FROM notifications')[0][0]
with app.app_context():
    check(circle_tools.upgrade_report_notifications(core.get_db())==1,'Unambiguous legacy report notification repaired')
    check(circle_tools.upgrade_report_notifications(core.get_db())==0,'Legacy notification repair is repeat-safe')
legacy=query('SELECT path,read_at FROM notifications WHERE id=?',(legacy_nid,))[0]
check(legacy['path'].endswith(f'?report_id={approve_report}#circle-report-{approve_report}'),'Legacy notice now targets its completed report')
check(legacy['read_at']=='2026-10-16 03:01:00','Legacy repair preserves read history')
check(b'Outcome: Approved' in get('Owner',legacy['path']).data,'Repaired legacy notice opens completed decision')
print('CIRCLES FULL APPLICATION PASS',checks,'checks; disposable fixture DB; no SMTP; live data untouched')
