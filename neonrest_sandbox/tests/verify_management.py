"""T39: isolated Management filters, privilege scopes, audit evidence and fresh auth."""
import contextlib, io, json, os, shutil, sqlite3, sys, tempfile, time
from pathlib import Path
from flask import template_rendered

checks=0
def check(value,label):
    global checks
    assert value,label
    checks+=1
live=Path(os.environ.get('NEONREST_TEST_SOURCE','/home/sinbot/neonrest_sandbox'))
with tempfile.TemporaryDirectory(prefix='neonrest-management-') as temp:
    root=Path(temp);stage=root/'neonrest_sandbox';stage.mkdir()
    for p in live.glob('*.py'):shutil.copy2(p,stage/p.name)
    for folder in ('templates','routes','utils'):shutil.copytree(live/folder,stage/folder)
    (stage/'static').symlink_to(live/'static',target_is_directory=True)
    source=sqlite3.connect('file:/home/sinbot/db/neonrest_sandbox.db?mode=ro',uri=True)
    tables=('users','staff_roles','posts','comments','moderation_events','moderation_cases','case_links','case_evidence')
    original={t:source.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}
    dest=sqlite3.connect(root/'test.db');source.backup(dest);dest.close()
    os.environ['NEONREST_SANDBOX_DATABASE']=str(root/'test.db');os.environ['NEONREST_SANDBOX_SECRET_FILE']=str(root/'secret')
    sys.path.insert(0,str(root))
    with contextlib.redirect_stdout(io.StringIO()):import neonrest_sandbox.app as core
    from neonrest_sandbox import community_features as cf, public_ids
    app=core.app;app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,PUBLIC_ID_TEST_ALIASES=False,SESSION_COOKIE_PATH='/')
    app.instance_path=str(root/'instance');Path(app.instance_path).mkdir()
    core.mail.send=lambda message:(_ for _ in ()).throw(AssertionError('No SMTP in Management audit'))
    now=int(time.time());csrf='t39-management';people={'owner':1};events={}
    with app.app_context():
        db=core.get_db()
        for label in ('admin','manager','moderator','editor','no_factor_editor','peer','target','unverified','deleted_actor','teen_mod'):
            dob='2010-01-01' if label=='teen_mod' else '1990-01-01'
            people[label]=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,?)',
                ('@T39_'+label,label+'@t39.example.invalid','unused',dob,int(label!='unverified'))).lastrowid
        for label,role in [('admin','admin'),('manager','manager'),('moderator','moderator'),('unverified','admin'),('teen_mod','moderator')]:
            db.execute('INSERT INTO staff_roles VALUES (?,?)',(people[label],role))
        for label,uid in people.items():
            if label not in ('no_factor_editor','target'):db.execute('INSERT INTO account_safety(user_id,totp_secret) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET totp_secret=excluded.totp_secret',(uid,'JBSWY3DPEHPK3PXP'))
            db.execute('INSERT INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest('t39-'+label),uid,now,now,now+7200,'isolated-t39'))
        vibe=db.execute("SELECT * FROM vibes WHERE name='Fresh Starts'").fetchone()
        other=db.execute("INSERT INTO vibes(name) VALUES ('T39 Other Vibe')").lastrowid
        for label in ('editor','no_factor_editor'):db.execute('INSERT INTO vibe_editors VALUES (?,?)',(vibe['id'],people[label]))
        near=db.execute('INSERT INTO users(handle,email,password_hash,dob,verified) VALUES (?,?,?,?,1)',('@T39Xpeer','near@t39.example.invalid','unused','1990-01-01')).lastrowid
        def event(actor,target,action,label):
            return db.execute('INSERT INTO moderation_events(actor_id,target_user_id,action,reason) VALUES (?,?,?,?)',(actor,target,action,'T39EVENT_'+label)).lastrowid
        events['actor']=event(people['admin'],people['target'],'t39:hide','actor')
        events['subject']=event(people['moderator'],people['admin'],'t39:hide','subject')
        events['literal']=event(people['moderator'],people['peer'],'t39:restore','literal')
        events['wildcard_near']=event(people['moderator'],near,'t39:restore','wildcard_near')
        events['deleted']=event(people['deleted_actor'],people['target'],'t39:hide','deleted')
        db.execute('DELETE FROM users WHERE id=?',(people['deleted_actor'],))
        # Pagination must count matching rows, including retained events with missing accounts.
        for number in range(61):event(people['admin'],people['target'],'t39:page','page-'+str(number))
        event(people['deleted_actor'],people['target'],'t39:detail','deleted-detail')
        pid=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,'T39 private adult post','public')",(people['target'],)).lastrowid
        db.execute("INSERT INTO post_privacy VALUES (?,'private')",(pid,));post_token=public_ids.ensure(db,'post',pid)
        db.commit()
    def client(label):
        c=app.test_client()
        with app.app_context():u=dict(core.get_db().execute('SELECT * FROM users WHERE id=?',(people[label],)).fetchone())
        with c.session_transaction() as s:s.update(user_id=u['id'],user_email=u['email'],user_handle=u['handle'],sid='t39-'+label,fresh_at=now,factor_at=now,theme_csrf_token=csrf)
        return c
    clients={label:client(label) for label in people if label!='deleted_actor'};guest=app.test_client()
    routes={'/manage':{'owner','admin','manager','moderator','editor','teen_mod'},'/manage/users':{'owner','admin','manager','moderator','teen_mod'},
        '/manage/posts':{'owner','admin','manager','moderator','teen_mod'},'/manage/comments':{'owner','admin','manager','moderator','teen_mod'},
        '/manage/history':{'owner','admin','manager','moderator','teen_mod'},'/manage/roles':{'owner','admin','manager','moderator','teen_mod'},
        '/manage/reports':{'owner','admin','manager','moderator','teen_mod'},'/manage/appeals':{'owner','admin','manager','moderator','teen_mod'},
        '/manage/cases':{'owner','admin','manager','moderator','teen_mod'},'/manage/operations':{'owner','admin'},'/manage/ads':{'owner','admin'},
        '/staff/vibes/pending':{'owner','admin','manager'}}
    for path,allowed in routes.items():
        check(guest.get(path).status_code!=200,'Guest denied '+path)
        for label in ('owner','admin','manager','moderator','editor','peer','unverified','teen_mod'):
            response=clients[label].get(path)
            check(response.status_code in (302,403) if label=='unverified' else response.status_code==(200 if label in allowed else 403),label+' permission '+path+' status '+str(response.status_code))
            check('no-store' in response.headers.get('Cache-Control',''),label+' no-cache '+path)
    check(clients['teen_mod'].get('/posts/'+post_token).status_code==200,'Under-18 moderator retains private adult safety viewing')
    def get_context(c,path,query=None):
        captured=[]
        def capture(sender,template,context,**extra):captured.append((template.name,context))
        template_rendered.connect(capture,app)
        try:response=c.get(path,query_string=query or {})
        finally:template_rendered.disconnect(capture,app)
        return response,captured[-1][1] if captured else {}
    for path,key in [('/manage','recent_events'),('/manage/history','events')]:
        for term in ('@T39_admin','t39_ADMIN','#'+str(people['admin']).zfill(3),'NUID: #'+str(people['admin']).zfill(3),str(people['admin'])):
            for who,labels in [('either',('actor','subject')),('actor',('actor',)),('subject',('subject',))]:
                response,data=get_context(clients['admin'],path,{'q':term,'who':who,'mod_type':'t39:hide'})
                check(response.status_code==200,'Valid account/action filter '+path+term+who)
                check({r['reason'] for r in data[key]}=={'T39EVENT_'+label for label in labels},'Exact actor/subject result '+path+term+who)
                check(data['moderation_who']==who and data['moderation_query']==term,'Filter form preserves selection '+path+term+who)
        for term in ('T39_peer','@T39_peer'):
            response,data=get_context(clients['admin'],path,{'q':term,'mod_type':'t39:restore'})
            check([r['reason'] for r in data[key]]==['T39EVENT_literal'],'Underscore literal '+path+term)
        for term in ('%','\\',"' OR 1=1 --"):
            response,data=get_context(clients['admin'],path,{'q':term,'mod_type':'t39:restore'})
            check(response.status_code==200 and not data[key],'Wildcard/injection does not broaden '+path+term)
        for query in ({'mod_type':'unknown-action'},{'who':'everyone'},{'q':'x'*61},{'q':'@'}):
            check(clients['admin'].get(path,query_string=query).status_code==400,'Invalid filter fails explicitly '+path+str(query))
        response,data=get_context(clients['admin'],path,{'q':'#'+str(people['deleted_actor']),'mod_type':'t39:hide'})
        check(len(data[key])==1 and data[key][0]['actor_handle'] is None,'Deleted actor retained '+path)
        check(b'Removed account' in response.data and ('NUID #'+str(people['deleted_actor']).zfill(3)).encode() in response.data,'Deleted actor labelled with NUID '+path)
    detail,detail_context=get_context(clients['admin'],'/manage/users/'+str(people['target']))
    check(detail.status_code==200 and detail_context['account']['id']==people['target'],'User-detail account context is preserved')
    check(b'Removed account' in detail.data and b'T39EVENT_deleted-detail' in detail.data,'User detail retains deleted-actor history')
    response,data=get_context(clients['admin'],'/manage/history',{'q':'#'+str(people['admin']),'who':'actor','mod_type':'t39:page'})
    check(len(data['events'])==50 and data['has_next'],'Filtered history page one bounded')
    from urllib.parse import parse_qs, urlsplit
    import re, html
    history_links=[parse_qs(urlsplit(html.unescape(v)).query) for v in re.findall(r'href="([^"]+)"',response.data.decode()) if 'page=2' in v]
    check(any(q.get('who')==['actor'] and q.get('mod_type')==['t39:page'] for q in history_links),'Pagination preserves filters')
    first={r['id'] for r in data['events']}
    response,data=get_context(clients['admin'],'/manage/history',{'q':'#'+str(people['admin']),'who':'actor','mod_type':'t39:page','page':2})
    check(len(data['events'])==11 and not data['has_next'] and not first.intersection(r['id'] for r in data['events']),'Filtered history page two has no overlap')
    for value in ('0','-1','10001','x'):check(clients['admin'].get('/manage/history',query_string={'page':value}).status_code==400,'Invalid history page '+value)
    for term in ('@T39_peer','T39_peer','#'+str(people['peer']).zfill(3),'NUID '+str(people['peer']),str(people['peer'])):
        response,data=get_context(clients['admin'],'/manage/users',{'q':term})
        check([r['id'] for r in data['users']]==[people['peer']],'People exact literal/NUID '+term)
    for term in ('%',"' OR 1=1 --"):
        response,data=get_context(clients['admin'],'/manage/users',{'q':term});check(not data['users'],'People literal injection '+term)
    check(clients['admin'].get('/manage/users',query_string={'q':'x'*61}).status_code==400,'People query bounded')
    own_path='/manage/vibes/'+core.vibe_slug(vibe['name']);other_path='/manage/vibes/'+core.vibe_slug('T39 Other Vibe')
    theme_path='/themes/edit/'+core.vibe_slug(vibe['name'])+'/day'
    check(clients['editor'].get(own_path).status_code==200,'Scoped editor sees assigned Vibe')
    check(clients['editor'].get(other_path).status_code==404,'Scoped editor cannot manage another Vibe')
    check(clients['editor'].get(theme_path).status_code==200,'Scoped editor edits assigned theme')
    check(clients['editor'].get('/themes/edit/'+core.vibe_slug('T39 Other Vibe')+'/day').status_code==403,'Scoped editor cannot edit another theme')
    for path in ('/manage',own_path,theme_path):
        response=clients['no_factor_editor'].get(path)
        check(response.status_code==302 and '/account/security' in response.location,'Editor requires 2FA setup '+path)
    def state_count():
        with app.app_context():
            db=core.get_db();return tuple(db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('staff_roles','moderation_events','case_links','case_evidence'))
    form={'theme_csrf_token':csrf,'role':'moderator','action':'add','reason':'T39 reviewed role assignment'}
    target_path='/manage/roles/'+str(people['target'])
    for label in ('owner','admin','editor'):
        c=clients[label];baseline=state_count()
        with c.session_transaction() as s:s['fresh_at']=now-1801
        response=c.post(target_path,data=form) if label!='editor' else c.post(theme_path,data={'theme_csrf_token':csrf,'custom_css':'body { color: red; }'})
        check(response.status_code==302 and '/account/reauth' in response.location,label+' stale password redirects')
        check(state_count()==baseline,label+' stale request has no role/evidence write')
        with c.session_transaction() as s:s.update(fresh_at=now,factor_at=now-1801)
        response=c.post(target_path,data=form) if label!='editor' else c.post(theme_path,data={'theme_csrf_token':csrf})
        check(response.status_code==302 and '/account/reauth' in response.location,label+' stale factor redirects')
        check(state_count()==baseline,label+' stale factor has no role/evidence write')
        with c.session_transaction() as s:s.update(fresh_at=now,factor_at=now)
    for label in ('peer','editor','moderator','manager'):
        baseline=state_count();check(clients[label].post(target_path,data=form).status_code==403,label+' cannot assign role');check(state_count()==baseline,label+' denied role mutation atomic')
    baseline=state_count()
    for data in (dict(form,theme_csrf_token='bad'),dict(form,reason=''),dict(form,role='owner'),dict(form,action='replace')):
        check(clients['admin'].post(target_path,data=data).status_code==400,'Invalid role request denied');check(state_count()==baseline,'Invalid role request leaves audit unchanged')
    for role in ('admin','manager'):
        check(clients['admin'].post(target_path,data=dict(form,role=role)).status_code==403,'Admin cannot grant '+role)
    for target in (1,people['admin']):check(clients['admin'].post('/manage/roles/'+str(target),data=form).status_code==403,'Owner/self role protected')
    check(clients['admin'].post('/manage/roles/'+str(people['unverified']),data=form).status_code==403,'Unverified role target denied')
    check(clients['admin'].post(target_path,data=form).status_code==302,'Reviewed admin moderator assignment accepted')
    with app.app_context():
        db=core.get_db();e=db.execute('SELECT * FROM moderation_events WHERE target_user_id=? AND action=? ORDER BY id DESC',(people['target'],'role:add:moderator')).fetchone()
        check(e and e['actor_id']==people['admin'] and e['reason']==form['reason'],'Role event records actor, subject, action and reason')
        check(bool(db.execute("SELECT 1 FROM case_links WHERE kind='event' AND item_id=?",(e['id'],)).fetchone()),'Role event immediately linked to case')
        evidence=db.execute('SELECT * FROM case_evidence WHERE event_id=?',(e['id'],)).fetchone()
        check(evidence and not evidence['legacy'] and cf.digest(evidence['snapshot'])==evidence['sha256'],'Role evidence captured immediately with intact fingerprint')
    baseline=state_count();check(clients['admin'].post(target_path,data=form).status_code==302 and state_count()==baseline,'No-op assignment adds no duplicate event/evidence')
    target_client=client('target');check(target_client.get('/manage/history').status_code==302,'New staff member must configure 2FA')
    check(clients['admin'].post(target_path,data=dict(form,action='remove')).status_code==302,'Moderator removal accepted')
    check(target_client.get('/manage/history').status_code==403,'Role removal enforced in existing session')
    check(clients['owner'].post(target_path,data=dict(form,role='admin')).status_code==302,'Owner can grant admin')
    check(clients['owner'].post(target_path,data=dict(form,role='admin',action='remove')).status_code==302,'Owner can revoke admin')
    with app.app_context():
        db=core.get_db();db.execute("INSERT INTO user_moderation(user_id,banned) VALUES (?,1)",(people['admin'],));db.commit()
    check(clients['admin'].get('/manage/history').status_code==403,'Banned staff cannot open history')
    check(clients['admin'].post(target_path,data=form).status_code==403,'Banned staff cannot assign role')
    check(all(source.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()==original[t] for t in tables),'Live roles, users, content, cases and evidence untouched');source.close()
print('PASS:',checks,'isolated Management checks; no SMTP, live role changes or production writes')
