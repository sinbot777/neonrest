"""Delete navigation and safe-redirect regressions on a disposable database."""
from pathlib import Path
import sys,importlib
stage=Path(sys.argv[2])
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone',1)[0]
exec(compile(bootstrap,'statistics_fixture_bootstrap','exec'))
nav=importlib.import_module(package+'.post_navigation')
from urllib.parse import urlencode
profile='/@VMFixtureWriter'
for value,expected in [
 (profile+'?mode=night&posts_cursor=boundary',profile+'?mode=night&posts_cursor=boundary#recent-posts'),
 ('/feed?page=3','/feed?page=3'),
 ('/vibe/VM%20Fixture%20One?page=2&mode=night','/vibe/VM%20Fixture%20One?page=2&mode=night'),
 ('https://evil.invalid/','/feed'),('//evil.invalid/','/feed'),('/\\evil.invalid/','/feed'),('/login?next=https://evil.invalid','/feed'),('/account','/feed'),('/delete_post/123','/feed'),('/feed%0d%0aLocation:evil','/feed'),('', '/feed'),('x'*5000,'/feed')]:
 with app.test_request_context('/delete_post/test',method='POST',data={'return_to':value}):
  check(nav.after_delete()==expected,'safe navigation '+value[:40])
with app.test_request_context('/delete_post/test',method='POST',data={'return_to':'/sandbox'+profile+'?mode=night'},environ_overrides={'SCRIPT_NAME':'/sandbox'}):
 check(nav.after_delete()=='/sandbox'+profile+'?mode=night#recent-posts','mounted return destination')
# Create and delete only fictional records in the disposable database.
from flask import url_for
pager=importlib.import_module(package+'.profile_pagination')
with app.app_context():cursor=pager.serializer().dumps([users['Writer'],'2099-01-01',123456789,'older'])
return_to=profile+'?'+urlencode({'mode':'night','posts_cursor':cursor})
for destination in (profile+'?mode=night',return_to,'/feed?page=2','/vibe/VM%20Fixture%20One?page=2','https://evil.invalid/'):
 pid,public_id=post_fixture('Fictional delete navigation test')
 response=clients['Writer'].post('/delete_post/'+public_id,data={'theme_csrf_token':token,'return_to':destination})
 check(response.status_code==302,'successful delete redirects')
 with app.test_request_context('/delete_post/test',method='POST',data={'return_to':destination}):expected=nav.after_delete()
 check(response.headers['Location']==expected,'delete returns to originating safe page')
 check(not query('SELECT 1 FROM posts WHERE id=?',(pid,)),'fictional post deleted')
 if destination.startswith(profile):
  page=clients['Writer'].get(response.headers['Location'])
  check(page.status_code==200,'profile and cursor remain usable after delete')
pid,public_id=post_fixture('Fictional forbidden delete')
response=clients['Regular'].post('/delete_post/'+public_id,data={'theme_csrf_token':token,'return_to':profile})
check(bool(query('SELECT 1 FROM posts WHERE id=?',(pid,))),'another user cannot delete post')
response=clients['Writer'].post('/delete_post/'+public_id,data={'return_to':profile})
check(response.status_code==400 and bool(query('SELECT 1 FROM posts WHERE id=?',(pid,))),'CSRF still required')
page=clients['Writer'].get(profile+'?mode=night&page=2')
html=page.get_data(as_text=True)
check('name="return_to"' in html and '/@VMFixtureWriter?mode=night&amp;page=2' in html,'profile delete form carries escaped current URL')
print('DELETE RETURN CHECKS',checks)
