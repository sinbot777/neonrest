"""Provider URL, lazy-card and visibility regressions on disposable data."""
from pathlib import Path
import sys, importlib
stage=Path(sys.argv[2])
exec(compile((stage/'tests/verify_video_embeds.py').read_text(),'verify_video_embeds.py','exec'))
links=importlib.import_module(package+'.video_embeds').video_links
for url,provider,expected in [
 ('https://www.facebook.com/watch/?v=10152454700553553&tracking=discard','facebook','https://www.facebook.com/watch/?v=10152454700553553'),
 ('https://m.facebook.com/Meta/videos/10152454700553553/','facebook','https://www.facebook.com/watch/?v=10152454700553553'),
 ('https://www.facebook.com/reel/123456789/','facebook','https://www.facebook.com/reel/123456789/'),
 ('https://fb.watch/Abc_def-123/?tracking=discard','facebook','https://fb.watch/Abc_def-123/'),
 ('https://www.facebook.com/share/v/Abc_def123/','facebook','https://www.facebook.com/share/v/Abc_def123/'),
 ('https://www.facebook.com/share/r/Abc_def123/','facebook','https://www.facebook.com/share/r/Abc_def123/'),
 ('https://www.instagram.com/reel/CxqiU24PMa9/?igsh=tracking','instagram','https://www.instagram.com/reel/CxqiU24PMa9/'),
 ('https://instagram.com/p/fA9uwTtkSN/','instagram','https://www.instagram.com/p/fA9uwTtkSN/'),
 ('https://instagram.com/reels/CxqiU24PMa9/','instagram','https://www.instagram.com/reel/CxqiU24PMa9/'),
 ('https://www.youtube.com/watch?v=M7lc1UVf-VE','youtube','https://www.youtube.com/watch?v=M7lc1UVf-VE')]:
 found=links(url);check(len(found)==1 and found[0]['provider']==provider and found[0]['url']==expected,'canonical provider URL')
for url in ('https://facebook.com.evil.invalid/watch/?v=123456','https://instagram.com@evil.invalid/reel/CxqiU24PMa9/','https://evil.invalid@www.instagram.com/reel/CxqiU24PMa9/','https://www.facebook.com:8443/watch/?v=123456','https://www.instagram.com/reel/%3Cscript%3E/','https://facebook.com/login/','https://instagram.com/nasajpl/','https://127.0.0.1/reel/123456/','javascript:alert(1)','https://facebook.com/share/v/../','https://www.instagram.com/reel/ab/','https://www.facebook.com/watch/?v=123%22onload%3Dalert(1)'):
 check(links(url)==[],'unsafe/unsupported Meta URL rejected')
mixed='https://youtu.be/M7lc1UVf-VE https://facebook.com/reel/123456/ https://instagram.com/reel/CxqiU24PMa9/ https://instagram.com/p/fA9uwTtkSN/'
check([v['provider'] for v in links(mixed)]==['youtube','facebook','instagram'],'shared three-card cap preserves order')
check(len(links('https://facebook.com/watch/?v=123456 https://facebook.com/test/videos/123456/'))==1,'Facebook canonical duplicates removed')
check(links(chr(96)+mixed+chr(96))==[],'Meta code examples skipped')
with app.app_context():
 db=core.get_db()
 meta_pid=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,?,'public')",(uid,'META FIXTURE https://www.facebook.com/reel/123456789/ https://www.instagram.com/reel/CxqiU24PMa9/')).lastrowid
 hidden_meta=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,?,'public')",(uid,'https://www.instagram.com/reel/HiddenMeta123/')).lastrowid
 db.execute("INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,'fixture')",(hidden_meta,uid,uid));db.commit()
 with app.test_request_context('/'):
  meta_url=url_for('post_detail',post_id=meta_pid)
for url in ('/@VideoFixture',meta_url):
 response=client.get(url,follow_redirects=True);html=response.get_data(as_text=True)
 check(response.status_code==200,'Meta-containing page responds')
 check('data-video-provider="facebook"' in html and 'data-video-provider="instagram"' in html,'both provider cards rendered')
 check('HiddenMeta123' not in html,'hidden Meta card not exposed')
 check('<iframe' not in html,'no Meta player before activation')
 check('src="https://www.facebook.com' not in html and 'src="https://www.instagram.com' not in html,'no Meta resources before activation')
 check('Open on Facebook' in html and 'Open on Instagram' in html,'original links present')
print('META EMBED CHECKS',checks)
