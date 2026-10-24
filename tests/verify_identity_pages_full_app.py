"""Run against a staged app and online-backup disposable database only."""
from pathlib import Path
import sys,os,json,subprocess

if len(sys.argv)==2:
    manifest=json.loads(Path(sys.argv[1]).read_text())
    results={}
    for package,stage in manifest['packages'].items():
        result=subprocess.run(['/home/sinbot/.virtualenvs/neonrest-v081/bin/python',__file__,package,stage],capture_output=True,text=True,timeout=180)
        results[package]={'code':result.returncode,'output':result.stdout[-2500:],'errors':result.stderr[-4000:] if result.returncode else ''}
        print(package,json.dumps(results[package]),flush=True)
    Path(manifest['root'],'full-app-results.json').write_text(json.dumps(results))
    raise SystemExit(0 if all(r['code']==0 for r in results.values()) else 1)

package=sys.argv[1];stage=Path(sys.argv[2])
assert package in ('neonrest','neonrest_sandbox')
assert str(stage).startswith('/home/sinbot/releases/T25-')
import smtplib,urllib.request,socket
def forbidden(*a,**kw):raise AssertionError('External network forbidden in fixture')
smtplib.SMTP=forbidden;smtplib.SMTP_SSL=forbidden;urllib.request.urlopen=forbidden
import requests
requests.sessions.Session.request=forbidden
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0]
bootstrap=bootstrap.replace("'MAIL_QUEUE':'0'", "'MAIL_QUEUE':'0','STATISTICS_DATABASE':str(w/'statistics.sqlite')")
exec(compile(bootstrap,'disposable app bootstrap','exec'))
pages=importlib.import_module(package+'.identity_pages')
privacy=importlib.import_module(package+'.privacy_workflows')
check(Path(core.DATABASE).resolve()==(w/'fixture.db').resolve(),'Disposable primary database')
check(str(app.extensions['site_statistics']['path']).startswith(str(w)),'Disposable statistics database')

def send(who,path,**data):
    return clients[who].post(path,data={'theme_csrf_token':token,**data},environ_overrides=env)

check(get('Regular','/pages').status_code==200,'Ordinary member page dashboard')
check(get('Regular','/pages/new').status_code==200,'Real app page creation form')
check(b'Your pages' in get('Regular','/account').data,'Account navigation includes pages')
check(send('Regular','/pages/new',kind='creative',handle='_PageFixture',name='Fixture creative',owner_id=str(users['Admin'])).status_code==302,'Creative draft creation')
page=query("SELECT * FROM identity_pages WHERE handle='_pagefixture'")[0]
ref=page['id'];path='/pages/'+ref+'/edit'
check(page['owner_id']==users['Regular'],'Owner from authenticated session only')
check(get('Writer','/_pagefixture').status_code==404,'Draft private from other member')
check(get('Writer',path).status_code==403,'Unauthorized management denied')
check(send('Regular',path,action='state',state='published',revision='0').status_code==302,'Creative publishing')
check(send('Regular','/pages/'+ref+'/updates',body='<script>fictional</script>').status_code==302,'Page update creation')
check(b'&lt;script&gt;fictional' in get('Writer','/_pagefixture').data,'Update escaped in actual template')
check(b'<script>fictional' not in get('Writer','/_pagefixture').data,'No executable update markup')
check(get('Writer','/_PAGEFIXTURE').status_code==308,'Case-insensitive page URL redirects')
post=query('SELECT * FROM identity_page_posts WHERE page_id=?',(ref,))[0]
check(post['author_id']==users['Regular'],'Accountable author retained privately')
check(send('Writer','/pages/'+ref+'/updates',body='Forged').status_code==403,'Cannot impersonate page')
check(clients['Regular'].post('/pages/'+ref+'/updates',data={'body':'No csrf'},environ_overrides=env).status_code==400,'Real CSRF gate')
check(clients['Regular'].post('/pages/'+ref+'/updates',data={'body':'Bad origin','theme_csrf_token':token},headers={'Origin':'https://example.invalid'},environ_overrides=env).status_code==403,'Global origin gate')
with clients['Regular'].session_transaction() as s:s['fresh_at']=0
check(send('Regular','/pages/'+ref+'/updates',body='Old authentication').status_code==302,'Fresh authentication gate')
with clients['Regular'].session_transaction() as s:s['fresh_at']=now
change('INSERT INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['Writer'],users['Regular']))
check(get('Writer','/_pagefixture').status_code==404,'Owner block hides page')
change('DELETE FROM user_blocks WHERE user_id=?',(users['Writer'],))
change('INSERT INTO user_moderation(user_id,posting_restricted) VALUES (?,1)',(users['Regular'],))
check(send('Regular','/pages/'+ref+'/updates',body='Restricted').status_code==403,'Posting restrictions apply to page identity')
check(get('Writer','/_pagefixture').status_code==404,'Restricted owner cannot expose page')
change('DELETE FROM user_moderation WHERE user_id=?',(users['Regular'],))
check(send('Regular',path,action='edit',revision='0',name='Stale',description='').status_code==409,'Stale edit conflict')
check(send('Regular','/pages/new',kind='business',handle='$PageFixture',name='Business draft').status_code==302,'Adult business draft')
business=query("SELECT * FROM identity_pages WHERE handle='$pagefixture'")[0]
check(send('Regular','/pages/'+business['id']+'/edit',action='state',state='published',revision='0',paid='true').status_code==409,'Forged subscription cannot publish')
check(get('Writer','/$pagefixture').status_code==404,'Business draft remains private')
check(send('Teen','/pages/new',kind='business',handle='$TeenFixture',name='No').status_code==403,'Teen business ownership denied')
check(send('Teen','/pages/new',kind='creative',handle='_TeenFixture',name='Teen creative').status_code==302,'Eligible teen creative ownership')
response=send('Regular','/account/export')
check(response.status_code==200 and response.is_json,'Own-data export works')
export=response.json['identity_pages']
check(len(export['owned_pages'])==2 and len(export['own_page_posts'])==1,'Own pages and own authorship exported')
check(all(p['owner_id']==users['Regular'] for p in export['owned_pages']),'Other owners excluded from export')
with app.app_context():
 check(any('Page ownership' in reason for reason in privacy.erasure_blockers(core.get_db(),users['Regular'])),'Page dependencies prevent orphaning during future erasure')
check(app.config['RETENTION_ENABLED'] is False,'Permanent erasure stays disabled')
check(send('Regular','/pages/'+ref+'/updates/'+str(post['id'])+'/remove').status_code==302,'Author removes update')
check(b'&lt;script&gt;fictional' not in get('Writer','/_pagefixture').data,'Removed update unavailable')
check(send('Regular','/pages/'+ref+'/updates',body='Moderation fixture').status_code==302,'New reportable update')
update=query('SELECT id FROM identity_page_posts WHERE page_id=? ORDER BY id DESC LIMIT 1',(ref,))[0][0]
check(get('Writer','/pages/'+ref+'/report',post_id=update).status_code==200,'Report form available to eligible reader')
check(send('Writer','/pages/'+ref+'/report',post_id=str(update),reason='Fixture concern').status_code==302,'Report submitted')
rid=query('SELECT id FROM identity_page_reports ORDER BY id DESC LIMIT 1')[0][0]
check(get('Regular','/manage/pages/reports').status_code==403,'Ordinary owner cannot read staff reports')
check(b'Fixture concern' not in get('Regular','/pages/reports/mine').data,'Reporter identity and report private from owner')
check(get('Admin','/manage/pages/reports').status_code==200,'Staff can review restricted evidence')
with clients['Admin'].session_transaction() as s:s['factor_at']=0
check(get('Admin','/manage/pages/reports').status_code==302,'Staff report access requires fresh factor')
with clients['Admin'].session_transaction() as s:s['factor_at']=now
check(send('Admin','/manage/pages/reports',report_id=str(rid),decision='hide-update',reason='Fixture decision').status_code==302,'Staff hides update')
check(b'Moderation fixture' not in get('Writer','/_pagefixture').data,'Staff-hidden update absent')
check(send('Admin','/manage/pages/reports',report_id=str(rid),decision='hide-page',reason='Fixture page restriction').status_code==302,'Staff hides page')
check(get('Writer','/_pagefixture').status_code==404,'Staff-hidden page inaccessible')
check(send('Regular',path,action='state',state='published',revision='1').status_code==409,'Owner cannot override staff hide')
check(send('Admin','/manage/pages/reports',report_id=str(rid),decision='restore-page',reason='Fixture restoration').status_code==302,'Staff restores page')
check(get('Writer','/_pagefixture').status_code==200,'Page restored')
check(send('Admin','/manage/pages/reports',report_id=str(rid),decision='restore-update',reason='Fixture restoration').status_code==302,'Staff restores update')
check(b'Moderation fixture' in get('Writer','/_pagefixture').data,'Update restored')
check(b'Fixture decision' in get('Writer','/pages/reports/mine').data or b'Fixture restoration' in get('Writer','/pages/reports/mine').data,'Reporter can see decision')
check(send('Regular',path,action='state',state='archived',revision='1').status_code==302,'Archive page')
check(get('Writer','/_pagefixture').status_code==404,'Archived page hidden')
print(json.dumps({'checks':checks,'passed':True,'scope':'real app; disposable DB; no network'}))
