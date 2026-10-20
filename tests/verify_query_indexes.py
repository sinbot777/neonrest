"""Exercise query plans, stable results and migration safety on fictional in-memory data."""
from pathlib import Path
import importlib.util,json,sqlite3,time,statistics
spec=importlib.util.spec_from_file_location('query_indexes_under_test',Path(__file__).resolve().parents[1]/'query_indexes.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
SCHEMA='''CREATE TABLE posts(id INTEGER PRIMARY KEY,user_id INTEGER,target_user_id INTEGER,created_at TEXT);
CREATE TABLE comments(id INTEGER PRIMARY KEY,post_id INTEGER,user_id INTEGER,created_at TEXT);
CREATE TABLE post_vibes(post_id INTEGER,vibe_id INTEGER,PRIMARY KEY(post_id,vibe_id));
CREATE TABLE follows(id INTEGER PRIMARY KEY,follower_id INTEGER,followed_id INTEGER,revoked INTEGER DEFAULT 0);
CREATE TABLE friend_requests(sender_id INTEGER,receiver_id INTEGER,status TEXT,PRIMARY KEY(sender_id,receiver_id));'''
def sample(db,sql,args):
    plan=[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,args)];times=[];rows=None
    for _ in range(5):
        start=time.perf_counter();rows=db.execute(sql,args).fetchall();times.append((time.perf_counter()-start)*1000)
    return {'median_ms':round(statistics.median(times),4),'plan':plan,'rows':rows}
def main():
    db=sqlite3.connect(':memory:');db.executescript(SCHEMA);count=50000
    db.executemany('INSERT INTO posts VALUES (?,?,?,?)',((i,i%1000,(i*7)%1000,'2026-01-'+str(1+i%28).zfill(2)+'T'+str(i%24).zfill(2)+':00:00') for i in range(1,count+1)))
    db.executemany('INSERT INTO comments VALUES (?,?,?,?)',((i,1+i%count,i%1000,'2026-02-01T00:00:00') for i in range(1,2*count+1)))
    db.executemany('INSERT INTO post_vibes VALUES (?,?)',((i,1+i%100) for i in range(1,count+1)))
    db.executemany('INSERT INTO follows VALUES (?,?,?,0)',((i,i%1000,i//1000) for i in range(1,20001)))
    db.executemany('INSERT INTO friend_requests VALUES (?,?,?)',((i%1000,i//1000,'pending' if i%2 else 'accepted') for i in range(20000)));db.commit()
    batch=tuple(range(count-19,count+1));queries={
      'profile_author':('SELECT id FROM posts WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 20',(99,)),
      'profile_target':('SELECT id FROM posts WHERE target_user_id=? ORDER BY created_at DESC,id DESC LIMIT 20',(99,)),
      'profile_combined':('SELECT id FROM posts WHERE user_id=? OR target_user_id=? ORDER BY created_at DESC,id DESC',(99,99)),
      'comment_batch':('SELECT id,post_id FROM comments WHERE post_id IN ('+','.join('?' for _ in batch)+') ORDER BY created_at,id',batch),
      'vibe_membership':('SELECT post_id FROM post_vibes WHERE vibe_id=? ORDER BY post_id',(99,)),
      'following':('SELECT followed_id FROM follows WHERE follower_id=? AND revoked=0 ORDER BY followed_id',(99,)),
      'incoming_requests':('SELECT sender_id,receiver_id,status FROM friend_requests WHERE receiver_id=? AND status=? ORDER BY sender_id',(19,'pending')),
    }
    before_bytes=db.execute('pragma page_count').fetchone()[0]*db.execute('pragma page_size').fetchone()[0];before={k:sample(db,*v) for k,v in queries.items()};policy.install(db);policy.install(db)
    after={k:sample(db,*v) for k,v in queries.items()};checks=0
    for key in queries:
        assert before[key]['rows']==after[key]['rows'],key;assert any('SEARCH' in p for p in after[key]['plan']),key;checks+=2
    used=' '.join(p for v in after.values() for p in v['plan'])
    for name,table,columns,_ in policy.INDEXES:
        assert name in used,name;assert next(r[2] for r in db.execute('pragma index_list("'+table+'")') if r[1]==name)==0;checks+=2
    db.execute("INSERT INTO posts VALUES (999999,1,1,'2026-01-01')");policy.install(db);assert db.in_transaction;db.rollback();assert db.execute('SELECT count(*) FROM posts WHERE id=999999').fetchone()[0]==0;checks+=2
    broken=sqlite3.connect(':memory:');broken.executescript(SCHEMA);broken.execute('CREATE INDEX idx_comments_post_created ON comments(user_id)')
    try:policy.install(broken)
    except RuntimeError:pass
    else:raise AssertionError('Conflicting index was accepted')
    assert broken.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").fetchone()[0]==1;broken.close();checks+=1
    after_bytes=db.execute('pragma page_count').fetchone()[0]*db.execute('pragma page_size').fetchone()[0];db.close()
    report={'passed':True,'checks':checks,'fictional_posts':count,'fictional_comments':2*count,'added_index_bytes':after_bytes-before_bytes,'queries':{k:{'before_ms':before[k]['median_ms'],'after_ms':after[k]['median_ms'],'before_plan':before[k]['plan'],'after_plan':after[k]['plan']} for k in queries}}
    print(json.dumps(report),flush=True)
if __name__=='__main__':main()
