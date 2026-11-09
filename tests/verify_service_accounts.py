"""Actual app routes, disposable backup DB, fictional human operators; no external IO."""
from pathlib import Path
import sys,os,json,importlib,hashlib
stage=Path(sys.argv[2])
for prefix in ['NEONREST_PRODUCTION','NEONREST_SANDBOX']:
    os.environ[prefix+'_STRIPE_CONFIG']=str(stage.parent/'no-credentials.json')
exec(compile(Path(__file__).with_name('verify_identity_pages_full_app.py').read_text(),'page baseline','exec'))
services=importlib.import_module(package+'.service_accounts')
ages=importlib.import_module(package+'.age_policy')
guidance=importlib.import_module(package+'.onboarding_guidance')
labels=[]
def verify(ok,label):
    check(ok,label);labels.append(label)
def post(who,path,**data):
    return send(who,path,**data)
def svc():return query('SELECT * FROM service_accounts WHERE user_id=?',(sid,))[0]
def context_call(fn,*a,**kw):
    with app.test_request_context('/maintenance'):
        db=core.get_db()
        with db:return fn(db,*a,**kw)
verify(get('Regular','/manage/services').status_code==403,'ordinary member cannot configure services')
verify(get('Moderator','/manage/services').status_code==403,'moderator lacks service configuration authority')
verify(get('Owner','/manage/services').status_code==200,'protected owner sees service controls')
verify(post('Regular','/manage/services',action='create',handle='ForgedService',owner_id=users['Regular'],purpose='Untrusted service').status_code==403,'forged ordinary creation rejected')
verify(clients['Owner'].post('/manage/services',data={'action':'create'},environ_overrides=env).status_code==400,'management CSRF required')
with clients['Owner'].session_transaction() as s:s['fresh_at']=0
verify(post('Owner','/manage/services',action='create').status_code==302,'stale administrator reauthenticates')
with clients['Owner'].session_transaction() as s:s.update(fresh_at=now,factor_at=now)
verify(post('Owner','/manage/services',action='create',handle='TeenOwnedService',owner_id=users['Teen'],purpose='No teen service ownership').status_code==400,'adult accountable owner required')
verify(post('Owner','/manage/services',action='create',handle='UnprotectedService',owner_id=users['NoFactor'],purpose='No unprotected service ownership').status_code==400,'owner two-factor required')
verify(post('Owner','/manage/services',action='create',existing_id=users['Regular'],owner_id=1,purpose='No human conversion').status_code==400,'age-identified human cannot be converted')
hid=query("SELECT id FROM users WHERE lower(handle)='@helpline'")[0][0]
verify(post('Owner','/manage/services',action='create',existing_id=hid,owner_id=1,purpose='Official Neonrest onboarding and public help guidance.').status_code==302,'existing HelpLine converted through management route')
sid=hid
verify(query('SELECT dob FROM users WHERE id=?',(sid,))[0][0] is None,'service has no invented birthday')
verify(query('SELECT count(*) FROM staff_roles WHERE user_id=?',(sid,))[0][0]==0,'service gains no staff role')
verify(get('Writer','/@HelpLine').status_code==200,'adult sees dedicated service profile')
verify(get('Teen','/@HelpLine').status_code==200,'teen sees service profile without human age')
verify(b'Service' in get('Teen','/@HelpLine').data and b'private content' in get('Teen','/@HelpLine').data,'service category and limited scope labeled')
verify(get('Regular','/services/'+str(sid)+'/publish').status_code==403,'unassigned human cannot publish')
verify(post('Owner','/manage/services',action='grant',service_id=sid,revision=svc()['revision'],operator_id=users['Regular']).status_code==302,'administrator grants only guidance capability')
verify(get('Regular','/services/'+str(sid)+'/publish').status_code==200,'authorized protected operator gets composer')
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Regular'],1))
verify(get('Regular','/services/'+str(sid)+'/publish').status_code==403,'operator block of accountable owner suspends publishing')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Regular'],1))
verify(post('Owner','/manage/services',action='grant',service_id=sid,revision=svc()['revision'],operator_id=users['Teen']).status_code==400,'teen cannot operate service')
verify(post('Owner','/manage/services',action='grant',service_id=sid,revision=svc()['revision'],operator_id=users['NoFactor']).status_code==400,'unprotected operator rejected')
path='/services/'+str(sid)+'/publish'
verify(clients['Regular'].post(path,data={'content':'forged'},environ_overrides=env).status_code==400,'composer CSRF enforced')
with app.app_context():core.get_db().execute('DELETE FROM service_publications');core.get_db().commit()
with app.test_request_context('/maintenance'):
    db=core.get_db();refs=guidance.publish(db,core.identifiers,1);verify(len(refs)==4,'onboarding publishes four guidance references');db.rollback()
verify(query('SELECT count(*) FROM service_publications WHERE service_id=?',(sid,))[0][0]==0,'rolled-back batch leaves no publication grants')
refs=context_call(guidance.publish,core.identifiers,1)
verify(len(refs)==4 and len(set(refs))==4,'four unique HelpLine guidance posts')
verify(context_call(guidance.publish,core.identifiers,1)==refs,'onboarding rerun is idempotent')
verify(query('SELECT count(*) FROM service_publications WHERE service_id=?',(sid,))[0][0]==4,'exactly four service publication records')
verify(query("SELECT count(*) FROM service_audit WHERE service_id=? AND action='published'",(sid,))[0][0]==4,'every publication has accountable actor audit')
for who in ['Writer','Teen']:
    for ref in refs:
        verify(get(who,'/posts/'+ref).status_code==200,who+' reads guidance '+ref)
verify(app.test_client().get('/posts/'+refs[0],environ_overrides=env).status_code==200,'anonymous public guidance reads normally')
verify(all(not query('SELECT 1 FROM staff_announcements a JOIN service_publications s ON a.post_id=s.post_id WHERE s.service_id=?',(sid,)) for _ in [0]),'no staff announcement exemption used')
verify(get('Teen','/guide').status_code==200,'shared guide still available')
verify(b'Welcome to Neonrest' in get('Teen','/feed').data,'teen feed includes guidance')
verify(b'Welcome to Neonrest' in get('Teen','/vibe/Fresh%20Starts').data,'teen Fresh Starts includes guidance')
with app.test_request_context('/maintenance'):
    db=core.get_db()
    verify(not ages.can_read(db,users['Writer'],sid),'service cannot read member content')
    verify(not ages.contact(db,sid,users['Teen']) and not ages.contact(db,users['Teen'],sid),'no service contact in either direction')
    verify(not ages.ready(db,sid),'service is not an age-ready human')
pid=query('SELECT post_id FROM service_publications WHERE service_id=? ORDER BY post_id',(sid,))[0][0]
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Teen'],sid))
verify(get('Teen','/posts/'+refs[0]).status_code==404,'member block hides service guidance')
change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['Teen'],sid))
change('INSERT INTO user_mutes(user_id,target_id) VALUES (?,?)',(users['Teen'],sid))
with app.test_request_context('/maintenance'):verify(not cf.visible_post(core.get_db(),pid,users['Teen']),'mute respected by shared visibility')
change('DELETE FROM user_mutes WHERE user_id=? AND target_id=?',(users['Teen'],sid))
original=query('SELECT content FROM posts WHERE id=?',(pid,))[0][0]
change('UPDATE posts SET content=? WHERE id=?',('Changed outside service composer',pid))
verify(get('Teen','/posts/'+refs[0]).status_code==404,'content changed outside audited publication loses all-age access')
change('UPDATE posts SET content=? WHERE id=?',(original,pid))
change("UPDATE post_privacy SET audience='private' WHERE post_id=?",(pid,))
verify(get('Teen','/posts/'+refs[0]).status_code==404,'private audience cannot use service exception')
change("UPDATE post_privacy SET audience='public' WHERE post_id=?",(pid,))
verify(post('Regular',path,content='A separate approved fixture guidance.',request_key='fixture-publication-key').status_code==302,'operator publishes through real composer route')
verify(post('Regular',path,content='A separate approved fixture guidance.',request_key='fixture-publication-key').status_code==302,'composer retry does not duplicate')
verify(post('Regular',path,content='Changed retry',request_key='fixture-publication-key').status_code==400,'idempotency key cannot change content')
verify(post('Owner','/manage/services',action='revoke',service_id=sid,revision=svc()['revision'],operator_id=users['Regular']).status_code==302,'operator revoked through management')
verify(post('Regular',path,content='Revoked attempt',request_key='revoked-fixture-key').status_code==403,'revocation immediately blocks publishing')
verify(post('Owner','/manage/services',action='status',service_id=sid,revision=svc()['revision']-1,enabled='0').status_code==409,'stale configuration rejected')
verify(post('Owner','/manage/services',action='status',service_id=sid,revision=svc()['revision'],enabled='0').status_code==302,'service disabled')
verify(get('Teen','/posts/'+refs[0]).status_code==404 and get('Writer','/@HelpLine').status_code==404,'disable hides guidance and service profile')
verify(post('Owner','/manage/services',action='status',service_id=sid,revision=svc()['revision'],enabled='1').status_code==302,'service restored')
verify(get('Teen','/posts/'+refs[0]).status_code==200,'restore recovers eligible reading')
with clients['Regular'].session_transaction() as s:s['user_id']=sid
verify(get('Regular','/account').status_code==403,'service session rejected and cleared')
verify(not get('Regular','/account').status_code==200,'service cannot become member session')
email=query('SELECT email FROM users WHERE id=?',(sid,))[0][0]
verify(post('Writer','/login',email=email,password='fictional').status_code==403,'direct service login rejected')
change("INSERT INTO account_disables(user_id,disabled,reason) VALUES (?,1,'Fixture service suspension') ON CONFLICT(user_id) DO UPDATE SET disabled=1",(1,))
verify(get('Teen','/posts/'+refs[0]).status_code==404,'disabled accountable human suspends service visibility')
change('DELETE FROM account_disables WHERE user_id=?',(1,))
with app.app_context():verify(services.erasure_dependencies(core.get_db(),1),'ownership and audits block unreviewed erasure')
verify(get('Owner','/account/export').status_code!=200,'export remains POST-only')
verify(post('Owner','/account/export').json['services']['owned_services'][0]['user_id']==sid,'owner export retains service accountability')
verify(post('Owner','/manage/services',action='create',handle='SecondFixtureService',owner_id=1,purpose='A second reusable fixture service identity.').status_code==302,'category supports additional services')
other=query("SELECT id FROM users WHERE handle='@SecondFixtureService'")[0][0]
verify(other!=sid and query('SELECT dob FROM users WHERE id=?',(other,))[0][0] is None,'second service is distinct and has no birthday')
verify(query('PRAGMA quick_check')[0][0]=='ok','disposable database integrity')
for name,who,path in [('manage','Owner','/manage/services'),('compose','Owner','/services/'+str(sid)+'/publish'),('public','Teen','/@HelpLine')]:
    response=get(who,path);verify(response.status_code==200,'UI render '+name);(stage.parent/('service-preview-'+name+'.html')).write_text(response.data.decode())
report={'passed':True,'checks':len(labels),'baseline_checks':checks-len(labels),'labels':labels,'scope':'isolated actual deployed-app candidate; no live changes or external calls'}
(stage.parent/'service-results.json').write_text(json.dumps(report,indent=2));print('SERVICE_ACCEPTANCE',json.dumps(report))
