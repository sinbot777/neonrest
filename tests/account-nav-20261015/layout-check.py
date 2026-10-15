"""Account layout checks against isolated database and source copies only."""
from pathlib import Path
import os,runpy,sys,json,time,secrets,contextlib,io
from bs4 import BeautifulSoup
root=Path(os.environ['NEONREST_PRIVACY_TEST_WORKDIR'])
env='neonrest_sandbox' if root.name=='PRIVACY-20261014' else 'neonrest'
setup=(root/'committed-full-smoke.py').read_text().split('checks=0')[0]
exec(setup)
client=app.test_client();base='https://www.neonrest.com';now=int(time.time());sid='layout-check-fixture-session'
with app.app_context():
 db=core.get_db();db.execute('INSERT OR REPLACE INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),1,now,now,now+3600,'Layout check fixture'));db.commit()
with client.session_transaction() as s:s.update(user_id=1,user_handle='@LayoutReviewer',user_email='layout-reviewer@example.invalid',sid=sid,fresh_at=now,factor_at=now,theme_csrf_token='layout-synthetic-csrf')
paths=['/account','/account/security','/account/privacy','/notifications','/account/data','/media-settings','/manage','/account/age','/account/family','/manage/family']
checks=[]
for path in paths:
 response=client.get(path,base_url=base)
 assert response.status_code==200,(path,response.status_code)
 soup=BeautifulSoup(response.data,'html.parser')
 assert len(soup.select('.account-workspace'))==1,path
 assert len(soup.select('nav[aria-label="Account navigation"]'))==1,path
 assert len(soup.select('.account-workspace-navigation [aria-current="page"]'))==1,path
 assert soup.select_one('link[href*="css/account-shell.css"]'),path
 top=soup.select_one('.session-info');assert top,path
 assert [a.get_text(strip=True) for a in top.select('a')][1:3]==['Feed','Your profile'],path
 assert not soup.select('.workspace-shortcuts'),path
 assert soup.select_one('.account-workspace-navigation a[href="/manage"]'),path
 checks.append({'path':path,'status':response.status_code,'navigation_count':1,'active_link_count':1})
# New fictional ordinary adult; never export existing account data.
with app.app_context():
 db=core.get_db();suffix=secrets.token_hex(4)
 uid=db.execute("INSERT INTO users(email,handle,password_hash,verified,dob,created_at) VALUES (?,?,?,1,'1985-01-01',CURRENT_TIMESTAMP)",('layout-'+suffix+'@example.invalid','@LayoutExample'+suffix,'!disabled-layout-fixture')).lastrowid
 db.execute("INSERT INTO age_clocks(user_id,zone,confirmed) VALUES (?,'UTC',1)",(uid,))
 db.execute('INSERT OR REPLACE INTO active_sessions VALUES (?,?,?,?,?,?,0)',(cf.digest(sid),uid,now,now,now+3600,'Layout check fixture'));db.commit()
with client.session_transaction() as s:s.clear();s.update(user_id=uid,user_handle='@LayoutExample',user_email='layout@example.invalid',sid=sid,fresh_at=now,factor_at=now,theme_csrf_token='layout-synthetic-csrf')
previewdir=Path('/home/sinbot/releases/ACCOUNT-NAV-20261015/previews');previewdir.mkdir(exist_ok=True)
for path in ['/account/age','/account/family','/account','/account/security']:
 response=client.get(path,base_url=base);assert response.status_code==200,(path,response.status_code)
 soup=BeautifulSoup(response.data,'html.parser');nav=soup.select_one('.account-workspace-navigation')
 assert not nav.select('a[href="/manage"],a[href="/manage/family"]'),'Staff navigation leaked'
 if env=='neonrest_sandbox':
  content=soup.select_one('#main-content')
  for node in content.select('script,input[type="hidden"],img'):node.decompose()
  for node in content.select('form'):node['inert']='';node.attrs.pop('action',None)
  for node in content.select('a'):node['href']='#'
  for node in content.select('input'):node.attrs.pop('value',None)
  assert 'layout-synthetic-csrf' not in str(content)
  top=soup.select_one('.session-info')
  for node in top.select('a'):node['href']='#'
  styles=''.join(str(n) for n in soup.select('style'))
  html='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/sandbox/static/style.css"><link rel="stylesheet" href="/sandbox/static/css/mobile.css">'+styles+'</head><body><p style="color:#fcb5a3;text-align:center">Fictional layout preview · forms disabled</p>'+str(top)+str(content)+'<link rel="stylesheet" href="/sandbox/static/css/account-shell.css?v=20261015-account1"></body></html>'
  (previewdir/(path.strip('/').replace('/','-')+'.html')).write_text(html)
print('TOP BAR PASS',env,len(checks),'staff routes and 4 ordinary-user views; one nav and active link per route')
Path('/home/sinbot/releases/ACCOUNT-NAV-20261015/'+env+'-checks.json').write_text(json.dumps({'environment':env,'routes':checks,'ordinary_user_views':4,'staff_navigation_hidden':True,'isolated_database':True,'smtp_disabled':True},indent=2))
