"""Seek pagination at 100k rows: bounded authorization work and stable traversal."""
import sys, importlib.util, sqlite3, types, time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from flask import Flask,g,session
from werkzeug.exceptions import HTTPException
root=Path(sys.argv[1]);package=types.ModuleType('cursor_fixture');package.__path__=[str(root)];sys.modules['cursor_fixture']=package
reading=types.ModuleType('cursor_fixture.reading_tools');reading.feed_filter=lambda db: ([],[]);sys.modules[reading.__name__]=reading
spec=importlib.util.spec_from_file_location('cursor_fixture.growth_queries',root/'growth_queries.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
app=Flask(__name__);app.secret_key='fictional-cursor-test-key';app.add_url_rule('/feed','feed',lambda:'');app.add_url_rule('/vibe/<vibe_name>','vibe_page',lambda vibe_name:'');app.add_url_rule('/circles/<circle_id>','circle_page',lambda circle_id:'')
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
for s in ['CREATE TABLE posts(id INTEGER PRIMARY KEY,user_id INTEGER,content TEXT,created_at TEXT)','CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT,codename TEXT,avatar_path TEXT)','CREATE TABLE moderated_posts(post_id INTEGER PRIMARY KEY)','CREATE TABLE post_vibes(post_id INTEGER,vibe_id INTEGER)','CREATE TABLE vibes(id INTEGER PRIMARY KEY,name TEXT)','CREATE TABLE circle_posts(post_id INTEGER,circle_id INTEGER)','CREATE TABLE comments(post_id INTEGER,created_at TEXT,id INTEGER)']:db.execute(s)
db.execute("INSERT INTO users VALUES(1,'@Fictional',NULL,NULL)");db.execute("INSERT INTO vibes VALUES(1,'Fictional')")
db.executemany("INSERT INTO posts VALUES(?,1,'Fictional growth fixture','2026-01-01')",((i,) for i in range(1,100001)))
db.executemany('INSERT INTO post_vibes VALUES(?,1)',((i,) for i in range(1,100001)));db.executemany('INSERT INTO circle_posts VALUES(?,1)',((i,) for i in range(1,101)))
db.execute('CREATE UNIQUE INDEX post_vibes_pair ON post_vibes(post_id,vibe_id)');mod.install(db);calls=[];hidden={99998};db.create_function('community_post_visible',1,lambda pid:calls.append(pid) or int(pid not in hidden));checks=0

def check(ok,label):
 global checks
 assert ok,label
 checks+=1

def read(path='/feed',page=1,uid=42,**kw):
 with app.test_request_context(path):
  session['user_id']=uid;calls.clear();rows,more=mod.timeline_rows(db,page,**kw);nav=dict(g.timeline_navigation);count=len(calls)
  return rows,nav,count
first,n,c=read();check(len(first)==20 and n['older'] and not n['newer'],'First page');check(c<=22,'Authorization before bounded limit');check('OFFSET' not in str(n),'Cursor links')
second,n2,c=read(n['older']);check(set(x['id'] for x in first).isdisjoint(x['id'] for x in second),'No overlap');check(c<=22,'Second page bounded')
back,nb,c=read(n2['newer']);check([r['id'] for r in first]==[r['id'] for r in back],'Backward roundtrip');check(not nb['newer'],'First page newer absent')
# Traverse one hundred pages and show authorization work is independent of depth.
path=n['older'];seen=[r['id'] for r in first];times=[]
for i in range(100):
 t=time.perf_counter();r,nav,c=read(path);times.append(time.perf_counter()-t);check(c<=22,'Deep page authorization bounded');seen.extend(x['id'] for x in r);path=nav['older']
check(len(seen)==len(set(seen)),'Stable tied timestamps at depth');print('100k-row cursor traversal max seconds',round(max(times),4))
# A cursor obtained at a legacy deep bookmark seeks directly on subsequent navigation.
r,deep,c=read('/feed?page=4000',page=4000);check(c>79000,'Legacy offset baseline measured')
r,deep2,c=read(deep['older']);check(c<=22,'Deep seek eliminates preceding-page authorization work')
# New arrivals and deleted boundary rows do not shift the next page.
db.execute("INSERT INTO posts VALUES(100001,1,'new','2027-01-01')");db.execute('DELETE FROM posts WHERE id=?',(first[-1]['id'],))
r,_,_=read(n['older']);check([x['id'] for x in r]==[x['id'] for x in second],'Insert/delete stability')
hidden.add(second[0]['id']);r,_,_=read(n['older']);check(second[0]['id'] not in [x['id'] for x in r] and len(r)==20,'Revocation before limit')
for path,kw,uid in [(n['older']+'x',{},42),(n['older'],{},43),(n['older'],{'vibe_id':1},42),('/feed?timeline_cursor='+('x'*1600),{},42)]:
 try:read(path,uid=uid,**kw);raise AssertionError('Expected invalid cursor')
 except HTTPException as e:check(e.code==400,'Forged/cross-view/user/oversized boundary refused')
# Pin only on first page, no repeated or omitted posts in complete Circle traversal.
p='/circles/1?mode=night&q=Fictional';out=[];prior=None
while p:
 r,nav,c=read(p,circle_id=1,pinned_id=1);out.extend(x['id'] for x in r)
 if prior:
  b,_,_=read(nav['newer'],circle_id=1,pinned_id=1);check([x['id'] for x in b]==prior,'Pinned backward roundtrip')
 prior=[x['id'] for x in r];p=nav['older']
 if p:check('mode=night' in p and 'q=Fictional' in p,'Mode/query preserved')
check(out[0]==1 and len(out)==100 and len(set(out))==100,'Full pinned traversal')
print('CURSOR GROWTH CHECKS',checks)
