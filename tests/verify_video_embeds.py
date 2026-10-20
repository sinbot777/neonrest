"""YouTube URL safety and full-app visibility checks on a disposable fixture."""
from pathlib import Path
import sys, importlib
stage=Path(sys.argv[2])
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split("cf=importlib.import_module",1)[0]
exec(compile(bootstrap,'statistics_fixture_bootstrap','exec'))
app=core.app;app.config.update(TESTING=True,MAIL_QUEUE_ENABLED=False,SESSION_COOKIE_PATH='/')
core.mail.send=lambda _:(_ for _ in ()).throw(AssertionError('SMTP forbidden'))
links=importlib.import_module(package+'.video_embeds').youtube_links
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
video='M7lc1UVf-VE'
for url in ('https://www.youtube.com/watch?v='+video,'https://youtu.be/'+video,'https://m.youtube.com/shorts/'+video,'https://www.youtube.com/live/'+video,'https://www.youtube.com/embed/'+video):
 check(links(url)[0]['id']==video,'supported URL '+url)
for url in ('https://youtube.com.evil.invalid/watch?v='+video,'https://youtube.com@evil.invalid/watch?v='+video,'https://evil.invalid@youtube.com/watch?v='+video,'https://youtube.com:8888/watch?v='+video,'https://youtube.com/watch?v=bad','javascript:alert(1)','https://127.0.0.1/watch?v='+video,'https://facebook.com/watch?v=123','https://instagram.com/reel/abc'):
 check(links(url)==[],'unsupported/unsafe URL rejected')
check(links('https://youtu.be/'+video+'?t=1h2m3s')[0]['start']==3723,'timestamp parsed')
check(links('https://youtu.be/'+video+'?start=999999999999999999')[0]['start']==86400,'timestamp bounded')
check(len(links(('https://youtu.be/'+video+' ')*10))==1,'duplicates removed')
check(len(links(' '.join('https://youtu.be/'+str(i).zfill(11) for i in range(6))))==3,'card count capped')
check(links(chr(96)+'https://youtu.be/'+video+chr(96))==[],'inline code skipped')
check(links(chr(96)*3+'https://youtu.be/'+video+chr(96)*3)==[],'fenced code skipped')
with app.app_context():
 db=core.get_db()
 uid=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES ('@VideoFixture','video@example.invalid','!disabled','1990-01-01',1,CURRENT_TIMESTAMP)").lastrowid
 pid=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,?,'public')",(uid,'Video example https://youtu.be/'+video+'?t=30')).lastrowid
 hidden=db.execute("INSERT INTO posts(user_id,content,circle) VALUES (?,?,'public')",(uid,'Hidden example https://youtu.be/abcdefghijk')).lastrowid
 db.execute("INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,'fixture')",(hidden,uid,uid));db.commit()
 from flask import url_for
 with app.test_request_context('/'):
  post_url=url_for('post_detail',post_id=pid)
client=app.test_client()
for url in ('/@VideoFixture',post_url):
 response=client.get(url,follow_redirects=True);html=response.get_data(as_text=True)
 check(response.status_code==200,'public page responds')
 check('data-youtube-id="'+video+'"' in html,'video card rendered '+url)
 check('data-youtube-id="abcdefghijk"' not in html,'hidden video not rendered')
 check('<iframe' not in html,'no player loaded before click')
 check('www.youtube-nocookie.com' not in html,'no provider resource before click')
 check('Open on YouTube' in html,'fallback link available')
 check('data-video-start="30"' in html,'timestamp passed safely')
 check('/static/js/video_embeds.js' in html,'player script present')
print('VIDEO EMBED CHECKS',checks)
