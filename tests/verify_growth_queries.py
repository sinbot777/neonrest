"""Bounded work, pinned ordering, comment privacy, windows and target links."""
import importlib.util,sqlite3,sys,types
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from flask import Flask
from werkzeug.exceptions import HTTPException
stage=Path(sys.argv[1]);pkg=types.ModuleType('growth_fixture');pkg.__path__=[str(stage)];sys.modules['growth_fixture']=pkg;spec=importlib.util.spec_from_file_location('growth_fixture.growth_queries',stage/'growth_queries.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
app=Flask(__name__);app.secret_key='fictional-growth-test';app.add_url_rule('/feed','feed',lambda:'');app.add_url_rule('/posts/<post_id>','post_detail',lambda post_id:'')
db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
for sql in ['CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT,codename TEXT,avatar_path TEXT)','CREATE TABLE posts(id INTEGER PRIMARY KEY,user_id INTEGER,content TEXT,created_at TEXT)','CREATE TABLE vibes(id INTEGER PRIMARY KEY,name TEXT)','CREATE TABLE post_vibes(post_id INTEGER,vibe_id INTEGER)','CREATE TABLE circle_posts(post_id INTEGER,circle_id INTEGER)','CREATE TABLE moderated_posts(post_id INTEGER PRIMARY KEY)','CREATE TABLE comments(id INTEGER PRIMARY KEY,post_id INTEGER,user_id INTEGER,content TEXT,parent_comment_id INTEGER,last_edited TEXT,created_at TEXT)','CREATE TABLE moderated_comments(comment_id INTEGER PRIMARY KEY)']:db.execute(sql)
db.executemany('INSERT INTO users VALUES (?,?,NULL,NULL)',[(1,'@One'),(2,'@Hidden')]);db.execute("INSERT INTO vibes VALUES (1,'Test')")
for i in range(1,201):
 db.execute('INSERT INTO posts VALUES (?,1,?,?)',(i,'Literal 100% _ post '+str(i),'2026-01-01 00:00:00'));db.execute('INSERT INTO post_vibes VALUES (?,1)',(i,));db.execute('INSERT INTO circle_posts VALUES (?,1)',(i,))
for i in range(1,124):db.execute("INSERT INTO comments VALUES (?,200,?,?,?,NULL,'2026-01-01 00:00:00')",(i,2 if i%10==0 else 1,'Comment '+str(i),i-1 if i>1 else None))
db.execute('INSERT INTO moderated_posts VALUES (199)');db.execute('INSERT INTO moderated_comments VALUES (4)');calls=[]
db.create_function('community_post_visible',1,lambda i:calls.append(i) or int(i!=198));db.create_function('community_member_visible',1,lambda i:int(i!=2));db.create_function('age_comment_visible',1,lambda i:int(i!=5))
mod.install(db);mod.install(db);checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
class IDs:
 @staticmethod
 def public(db,kind,value):return ('c' if kind=='comment' else 'p')+str(value)
 @staticmethod
 def resolve(db,kind,value,anchor=False):
  if anchor and value.isdigit():return int(value)
  if value[0]!='c' or not value[1:].isdigit():raise ValueError()
  return int(value[1:])
ids=IDs()
with app.test_request_context('/feed'):
 calls.clear();rows,more=mod.timeline_rows(db,1);check(len(rows)==20 and more,'Timeline page plus lookahead');check(len(calls)<=23,'First page visibility work bounded');check(rows[0]['id']==200 and rows[1]['id']==197,'Moderation and visibility before LIMIT')
 pages=[]
 for page in range(1,11):
  rows,more=mod.timeline_rows(db,page,circle_id=1,pinned_id=1);pages.extend(r['id'] for r in rows);check(len(rows)<=20,'Bounded Circle page')
 check(len(pages)==198 and len(set(pages))==198,'Pinned pagination complete without duplicates');check(pages[0]==1,'Pinned post first');check(not more,'Last page no more link')
 rows,more=mod.timeline_rows(db,1,circle_id=1,pinned_id=198);check(rows[0]['id']==200,'Hidden pin stays hidden')
 rows,more=mod.timeline_rows(db,1,query='100% _');check(len(rows)==20,'Literal wildcard search semantics')
 rows,more=mod.timeline_rows(db,1,query='missing');check(not rows and not more,'Empty timeline')
 rows,nav=mod.comment_windows(db,[200],ids);check(len(rows)==5 and nav['p200']['more'],'Five-comment preview and all-comments link');check([r['id'] for r in rows]==[118,119,121,122,123],'Preview contains latest visible comments in chronological order')
expected=[i for i in range(1,124) if i%10 and i not in (4,5)];collected=[];path='/posts/p200';second=None
while True:
 with app.test_request_context(path):
  rows,nav=mod.comment_windows(db,[200],ids,single=True);check(len(rows)<=50,'Comment page bounded');collected.extend(r['id'] for r in rows)
  if second is None and nav['p200']['next']:second=nav['p200']['next']
  path=nav['p200']['next']
  if not path:break
check(collected==expected,'All visible comments in stable chronological windows')
with app.test_request_context(second):
 rows,nav=mod.comment_windows(db,[200],ids,single=True);previous=nav['p200']['previous'];check(bool(previous),'Earlier-comments link')
with app.test_request_context(previous):
 rows,nav=mod.comment_windows(db,[200],ids,single=True);check([r['id'] for r in rows]==expected[:50],'Backward window matches original first page')
with app.test_request_context('/posts/p200?comment=c101'):
 rows,nav=mod.comment_windows(db,[200],ids,single=True);check(rows[0]['id']==101,'Target comment opens directly');check(rows[0]['reply_to_handle'] is None,'Hidden parent recipient stays hidden');check(rows[1]['reply_to_handle']=='@One','Visible parent recipient retained across target window');check(bool(nav['p200']['previous']),'Target retains earlier navigation')
with app.test_request_context('/posts/p200?comment=101'):
 rows,nav=mod.comment_windows(db,[200],ids,single=True);check(rows[0]['id']==101,'Legacy numeric anchor resolves through anchor aliases')
for query,pid,status in [('comment=4',200,404),('comment=c4',200,404),('comment=c5',200,404),('comment=c10',200,404),('comment=c101',1,404),('comment=bad',200,404),('comments_after=c1&comment=c101',200,400)]:
 with app.test_request_context('/posts/p200?'+query):
  try:mod.comment_windows(db,[pid],ids,single=True);raise AssertionError('Expected refusal: '+query)
  except HTTPException as error:check(error.code==status,'Invalid/hidden/cross-post target refused')
print(checks,'growth query checks passed')

