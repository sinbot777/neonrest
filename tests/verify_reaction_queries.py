"""Fictional SQLite growth fixture: counts, choices, privacy and seek windows."""
import importlib.util
import sqlite3
from pathlib import Path
from flask import Flask
from werkzeug.exceptions import HTTPException

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reactions', root/'reaction_queries.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,handle TEXT);'
    'CREATE TABLE post_reactions(post_id INTEGER,user_id INTEGER,emoji TEXT);')
db.executemany('INSERT INTO users VALUES (?,?)', ((i,'@Fixture'+str(i)) for i in range(1,1001)))
db.executemany('INSERT INTO post_reactions VALUES (?,?,?)',
    ((1000+i%2000, 1+i%1000, '👍') for i in range(100000)))
db.executemany('INSERT INTO post_reactions VALUES (1,?,?)',
    [(i,'👍') for i in range(1,124)]+[(1,'🔥')])
db.create_function('community_member_visible',1,lambda uid:int(uid%10!=0))
checks=0
def check(ok,label):
    global checks
    assert ok,label
    checks+=1
def measure():
    steps=[0]
    def tick(): steps[0]+=1
    db.set_progress_handler(tick,1)
    posts=[{'id':1},{'id':2}]
    mod.hydrate_reactions(db,posts,1)
    db.set_progress_handler(None,0)
    return posts,steps[0]
before,old=measure()
db.execute('CREATE INDEX idx_reactions_post_emoji_user ON post_reactions(post_id,emoji,user_id)')
after,new=measure()
check(before==after,'Index preserves counts and choices')
check(new<old/20,'Page aggregation avoids unrelated reaction scan')
check(after[0]['reaction_counts']=={'👍':123,'🔥':1},'Multiple reactions counted independently')
check(after[0]['viewer_reactions']=={'👍','🔥'},'Multiple viewer choices retained')
check(after[1]['reaction_counts']=={} and not after[1]['viewer_reactions'],'Empty post')
posts=[{'id':1}];mod.hydrate_reactions(db,posts,None)
check(not posts[0]['viewer_reactions'],'Anonymous viewer has no selected reactions')
db.execute("DELETE FROM post_reactions WHERE post_id=1 AND user_id=1 AND emoji='👍'")
posts=[{'id':1}];mod.hydrate_reactions(db,posts,1)
check(posts[0]['viewer_reactions']=={'🔥'} and posts[0]['reaction_counts']['👍']==122,'Toggle off preserves other emoji')
app=Flask(__name__)
with app.test_request_context('/'):
    collected=[];boundary=None
    while True:
        rows,boundary=mod.reactor_window(db,1,'👍',boundary)
        check(len(rows)<=50,'Bounded people window')
        collected.extend(r['id'] for r in rows)
        if boundary is None:break
    check(collected==[i for i in range(2,124) if i%10],'Seek pages complete without hidden people or duplicates')
    for bad in ['bad','-1',str(2**64)]:
        try:mod.reactor_window(db,1,'👍',bad)
        except HTTPException as error:check(error.code==400,'Invalid cursor refused')
        else:raise AssertionError('Invalid cursor accepted')
print(checks,'reaction query checks passed; SQLite VM steps',old,'->',new)
