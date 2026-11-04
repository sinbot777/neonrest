from pathlib import Path
import sys,os,json,time,statistics,inspect,types,re,resource,smtplib,urllib.request
resource.setrlimit(resource.RLIMIT_CPU,(75,80))
def forbidden(*a,**kw):raise AssertionError('External network forbidden')
smtplib.SMTP=smtplib.SMTP_SSL=urllib.request.urlopen=forbidden
import requests
requests.sessions.Session.request=forbidden
stage=Path(sys.argv[2]);bootstrap=(stage/'tests/verify_messaging.py').read_text().split("for route in ['/messages'")[0]
exec(compile(bootstrap,'private fixture bootstrap','exec'))
from flask import g,has_request_context
from unittest.mock import patch
out={'checks':[],'measurements':[],'scope':'Actual staged Flask app and disposable copied fixture; no live writes or public load test'}
def verify(value,label):assert value,label;out['checks'].append(label)
for name in ['V2A','V2B','V2Other']:fixture_person(name,'1990-01-01')
friends('V2A','V2B');verify(start('V2B','V2A').status_code==200,'Conversation fixture starts');thread=chat('V2A','V2B');url='/messages/'+thread['public_id']+'/updates'
for i in range(12):
 name='V2Peer'+str(i);fixture_person(name,'1990-01-01');friends(name,'V2A');verify(start(name,'V2A').status_code==200,'Unread fixture '+str(i))
real_db=core.get_db;metric=None
def traced_db():
 db=real_db()
 if has_request_context() and not getattr(g,'v2_trace',False):
  def trace(sql):
   if metric is not None:metric['sql']+=1
  db.set_trace_callback(trace);g.v2_trace=True
 return db
with patch.object(core,'get_db',side_effect=traced_db):
 for mode in ['default','badge_omitted']:
  runs=[]
  for i in range(3):
   metric={'sql':0};begin=time.perf_counter();cpu=time.process_time();r=get('V2A',url,**({'badge':'0'} if mode=='badge_omitted' else {}));verify(r.status_code==200,'Updates '+mode+' '+str(i));runs.append({'sql':metric['sql'],'ms':round((time.perf_counter()-begin)*1000,2),'cpu_ms':round((time.process_time()-cpu)*1000,2)});metric=None
  out['measurements'].append({'mode':mode,'runs':runs})
  if mode=='default':reference=dict(r.json);verify(isinstance(reference['unread'],int),'Default API retains unread number')
  else:
   candidate=dict(r.json);verify(candidate.pop('unread') is None,'Opt-in skips badge calculation');reference.pop('unread');verify(candidate==reference,'All message, moderation and permission fields identical')
 for params in ({},{'badge':'0'}):
  verify(get('V2Other',url,**params).status_code==404,'Other user cannot read conversation '+str(params))
  verify(app.test_client().get(url,query_string=params,environ_overrides=env).status_code in (401,302,303),'Anonymous rejected '+str(params))
 change('INSERT OR IGNORE INTO user_blocks(user_id,target_id) VALUES (?,?)',(users['V2A'],users['V2B']))
 baseline=get('V2A',url);candidate=get('V2A',url,badge='0');verify(candidate.status_code==baseline.status_code,'Block handling preserved');verify(candidate.status_code!=200 or candidate.json['can_send'] is False,'Blocked send unavailable')
 change('DELETE FROM user_blocks WHERE user_id=? AND target_id=?',(users['V2A'],users['V2B']))
 # Compare the actual candidate profile implementation against its original SQL,
 # retaining exactly the same decorators, guards, request and fixture.
 target=inspect.unwrap(core.user_page_test);original=target.__code__;count=[0]
 old='WHERE (posts.user_id = ? OR posts.target_user_id = ?)'
 new='WHERE CASE WHEN (posts.user_id = ? OR posts.target_user_id = ?) THEN community_post_visible(posts.id) ELSE 0 END=1'
 guard='AND NOT EXISTS (SELECT 1 FROM moderated_posts mp WHERE mp.post_id = posts.id)'
 def baseline_code(code):
  constants=[]
  for item in code.co_consts:
   if isinstance(item,types.CodeType):item=baseline_code(item)
   elif isinstance(item,str) and 'WITH profile_page AS (' in item:
    assert item.count(new)==1 and item.count(guard)==1
    count[0]+=1;item=item.replace(new,old).replace(guard,guard+' AND community_post_visible(posts.id)=1')
   constants.append(item)
  return code.replace(co_consts=tuple(constants))
 reference_code=baseline_code(original);assert count[0]==1
 shapes={}
 try:
  for arm in ['baseline','candidate']:
   target.__code__=reference_code if arm=='baseline' else original
   metric={'sql':0};begin=time.perf_counter();cpu=time.process_time();r=get('Regular','/@VMFixtureRegular');out['measurements'].append({'mode':'profile_'+arm,'sql':metric['sql'],'ms':round((time.perf_counter()-begin)*1000,2),'cpu_ms':round((time.process_time()-cpu)*1000,2)});metric=None
   for viewer in ['Regular','Writer','Owner','Admin',None]:
    for name in ['Regular','Writer','Owner']:
     c=clients[viewer] if viewer else app.test_client();r=c.get('/@VMFixture'+name,headers=headers,environ_overrides=env);shape=(r.status_code,r.headers.get('Location'),re.findall(r'href="([^"]+)"',r.get_data(as_text=True)));k=str(viewer)+'/'+name
     if arm=='baseline':shapes[k]=shape
     else:verify(shape==shapes[k],'Profile output preserved '+k)
 finally:target.__code__=original
with app.app_context():
 db=core.get_db();verify(db.execute('PRAGMA quick_check').fetchone()[0]=='ok','Fixture integrity passes');verify(not db.execute('PRAGMA foreign_key_check').fetchall(),'Fixture has zero foreign key violations')
out['complete']=True;Path(sys.argv[3]).write_text(json.dumps(out,indent=2));print('V2_TEST_COMPLETE',len(out['checks']),json.dumps(out['measurements']),flush=True)
