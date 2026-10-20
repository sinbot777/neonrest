"""Full-app profile pagination regression on a disposable database copy."""
from pathlib import Path
import sys, importlib, re
from flask import template_rendered
# Reuse the existing isolated fixture bootstrap, including connection cleanup.
stage=Path(sys.argv[2])
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split("cf=importlib.import_module",1)[0]
exec(compile(bootstrap, 'statistics_fixture_bootstrap', 'exec'))
app=core.app
app.config.update(TESTING=True, MAIL_QUEUE_ENABLED=False, SESSION_COOKIE_PATH='/')
core.mail.send=lambda _: (_ for _ in ()).throw(AssertionError('SMTP forbidden'))
captured=[]
def record(sender, template, context, **kwargs):
    if template.name=='user_test.html': captured.append(context)
template_rendered.connect(record, app, weak=False)
checks=0
def check(ok, label):
    global checks
    assert ok,label
    checks+=1
with app.app_context():
    db=core.get_db()
    uid=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES ('@PaginationFixture','pagination@example.invalid','!disabled','1990-01-01',1,CURRENT_TIMESTAMP)").lastrowid
    other=db.execute("INSERT INTO users(handle,email,password_hash,dob,verified,created_at) VALUES ('@PaginationOther','pagination-other@example.invalid','!disabled','1990-01-01',1,CURRENT_TIMESTAMP)").lastrowid
    ids=[]
    for i in range(47):
        ids.append(db.execute("INSERT INTO posts(user_id,target_user_id,content,circle,created_at) VALUES (?,?,?,'public',?)",(other if i%3==0 else uid,uid if i%3==0 else None,'PAGE FIXTURE '+str(i),'2026-01-%02d 12:00:00'%(1+i//3))).lastrowid)
    for i in range(25):
        hidden=db.execute("INSERT INTO posts(user_id,content,circle,created_at) VALUES (?,?,'public','2028-01-01')",(uid,'HIDDEN PAGE FIXTURE')).lastrowid
        db.execute("INSERT INTO moderated_posts(post_id,author_id,hidden_by,reason) VALUES (?,?,?,'pagination fixture')",(hidden,uid,uid))
    db.commit()
client=app.test_client()
def get(url):
    captured.clear()
    response=client.get(url)
    check(response.status_code==200,'profile responds '+url[:60])
    check(len(captured)==1,'one profile rendered')
    context=captured[-1]
    check(len(context['posts'])<=20,'rendered post batch bounded')
    check('HIDDEN PAGE FIXTURE' not in response.get_data(as_text=True),'hidden posts excluded before pagination')
    return context,response
from urllib.parse import urlencode
base='/@PaginationFixture'
def link(c, key):
    return base+'?'+urlencode({'posts_cursor':c[key],'mode':'night'})
first,r=get(base+'?mode=night')
check(len(first['posts'])==20,'first page full')
check(not first['profile_newer'] and first['profile_older'],'first navigation')
check('mode=night' in r.get_data(as_text=True),'mode retained')
second,_=get(link(first,'profile_older'))
third,_=get(link(second,'profile_older'))
expected=list(reversed(ids))
actual=[p['id'] for c in (first,second,third) for p in c['posts']]
check(actual==expected,'every authored and guestbook post once, tied timestamps stable')
check(not third['profile_older'] and third['profile_newer'],'last navigation')
back,_=get(link(third,'profile_newer'))
check([p['id'] for p in back['posts']]==[p['id'] for p in second['posts']],'newer returns preceding page')
latest,_=get(link(back,'profile_newer'))
check([p['id'] for p in latest['posts']]==[p['id'] for p in first['posts']],'round trip to first page')
check(not latest['profile_newer'],'no empty newer page')
check(client.get(base+'?posts_cursor=broken').status_code==400,'invalid cursor rejected')
check(client.get('/@PaginationOther?'+urlencode({'posts_cursor':first['profile_older']})).status_code==400,'cursor scoped to profile')
with app.app_context():
    db=core.get_db();db.execute("INSERT INTO posts(user_id,content,circle,created_at) VALUES (?,?,'public','2027-01-01')",(uid,'INSERTED AFTER PAGE ONE'));db.commit()
repeat,_=get(link(first,'profile_older'))
check([p['id'] for p in repeat['posts']]==[p['id'] for p in second['posts']],'new insertion does not shift older page')
# Cursors keep a boundary even if that boundary post is deleted.
with app.app_context():
 db=core.get_db();db.execute('DELETE FROM posts WHERE id=?',(first['posts'][-1]['id'],));db.commit()
repeat,_=get(link(first,'profile_older'))
check([p['id'] for p in repeat['posts']]==[p['id'] for p in second['posts']],'deleted cursor boundary still works')
with app.app_context():
 db=core.get_db();db.execute('DELETE FROM posts WHERE user_id=? OR target_user_id=?',(uid,uid));db.commit()
empty,r=get(link(first,'profile_older'));check(not empty['posts'],'empty history after deletion');check('Latest posts' in r.get_data(as_text=True),'empty page has recovery link')
# Same signed cursor is validated again on every request and cannot be modified.
from urllib.parse import urlencode
from importlib import import_module
pager=import_module('neonrest.profile_pagination')
with app.app_context():
 malformed=pager.serializer().dumps([uid,'2026-01-01','invalid','older'])
check(client.get(base+'?'+urlencode({'posts_cursor':malformed})).status_code==400,'malformed signed payload rejected')
check(client.get(base+'?'+urlencode({'posts_cursor':'x'*1025})).status_code==400,'oversized cursor rejected')
print('PROFILE PAGINATION CHECKS',checks)

