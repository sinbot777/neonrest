"""Route, transaction and PDF tests against disposable SQLite only."""
import runpy,json,importlib,copy
from pathlib import Path
f=runpy.run_path(str(Path(__file__).parent/'tests/verify_zines_advanced_local.py'))
client,db,z,app,pub,iid,zid=(f[k] for k in ('client','db','z','app','pub','iid','zid'))
a=importlib.import_module('zine_candidate.zines_authoring');c=importlib.import_module('zine_candidate.zines_composition');pdf=importlib.import_module('zine_candidate.zines_pdf')
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
def revision():return z.get_issue(db,pub,iid)['revision']
base='/zines/'+zid+'/issues/'+iid;studio=base+'/studio'
def post(**data):return client.post(studio,data={'theme_csrf_token':'fixture-token','revision':revision(),**data})
def block(id,y=40,h=250,locked=False):return dict(id=id,type='text',x=24,y=y,w=348,h=h,text='Original',font='sans',size=12,leading=1.35,align='left',locked=locked)
rows=[r for r in z.pages(db,iid) if r['kind']=='page'][:2]
for i,row in enumerate(rows):
 layout={'version':1,'background':'#ffffff','blocks':[block('article',50,210)]}
 if i==0:layout['blocks'].append({**block('header',10,24,True),'text':'Page {page} / {pages}','size':9})
 db.execute('UPDATE zine_pages SET content=? WHERE id=?',(z.content(db,zid,1,dict(design='composition',composition=layout)),row['id']))
db.commit();refs=[r['id']+':article' for r in rows]
check(client.get(studio).status_code==200,'Publishing tools render')
story=' '.join('word'+str(i) for i in range(140))
check(post(studio_action='story',name='Article',story_text=story,frames=refs).status_code==302,'Cross-page story saved')
state=a.get(db,iid);sid=next(iter(state['stories']));check(state['stories'][sid]['text']==story,'Canonical text preserved')
parts=[json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(r['id'],)).fetchone()[0])['composition']['blocks'][0]['text'] for r in rows]
check(' '.join(' '.join(parts).split())==story,'No words lost or duplicated across frames');check(all(parts),'Both frames filled')
before=revision();snapshot_count=db.execute('SELECT COUNT(*) FROM zine_revisions').fetchone()[0]
check(post(studio_action='story',item_id=sid,name='Article',story_text='word '*4500,frames=refs).status_code==409,'Overflow rejected')
check(revision()==before and a.get(db,iid)['stories'][sid]['text']==story,'Overflow atomic rollback')
check(db.execute('SELECT COUNT(*) FROM zine_revisions').fetchone()[0]==snapshot_count,'Overflow snapshot rollback')
check(post(studio_action='style',name='Body',frames=refs,font='sans',size='10',leading='1.2',align='left',color='#222222').status_code==302,'Named style assigned across pages')
styleid=next(iter(a.get(db,iid)['styles']))
check(all(json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(r['id'],)).fetchone()[0])['composition']['blocks'][0]['size']==10 for r in rows),'Shared typography applied')
check(post(studio_action='master',name='Folio',source_page=rows[0]['id'],master_pages=[rows[1]['id']]).status_code==302,'Master saved')
masterid=next(iter(a.get(db,iid)['masters']));target=json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(rows[1]['id'],)).fetchone()[0]);master=[b for b in target['composition']['blocks'] if b['id'].startswith('m'+masterid)]
check(len(master)==1 and '{page}' not in master[0]['text'] and master[0]['locked'],'Numbered master copy')
check(post(studio_action='style',item_id=styleid,name='Body revised',frames=refs,font='sans',size='11',leading='1.2',align='left',color='#222222').status_code==302,'Style edit reflows linked story')
target=json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(rows[1]['id'],)).fetchone()[0]);check(sum(b['id'].startswith('m'+masterid) for b in target['composition']['blocks'])==1,'Master refresh idempotent')
check(client.get(studio).status_code==200,'Populated publishing tools render')
check(post(studio_action='master',name='Bad source',source_page=rows[0]['id'],master_pages=[rows[0]['id']]).status_code==400,'Source self-copy rejected')
current=json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(rows[0]['id'],)).fetchone()[0]);bad=copy.deepcopy(current);bad['composition']['blocks'][0]['text']='replacement'
response=client.post(base+'/edit',data={'theme_csrf_token':'fixture-token','revision':revision(),'action':'page','page_id':rows[0]['id'],'design':'composition','layout':'text','composition':json.dumps(bad['composition'])})
check(response.status_code==409,'Direct linked source edits rejected')
current=json.loads(db.execute('SELECT content FROM zine_pages WHERE id=?',(rows[0]['id'],)).fetchone()[0]);current['composition']['blocks'][0]['h']=225
response=client.post(base+'/edit',data={'theme_csrf_token':'fixture-token','revision':revision(),'action':'page','page_id':rows[0]['id'],'design':'composition','layout':'text','composition':json.dumps(current['composition'])})
check(response.status_code==302,'Frame geometry edit automatically reflows')
check(a.get(db,iid)['stories'][sid]['text']==story,'Geometry reflow preserves canonical source')
check(post(studio_action='style',name='Bad target',frames=['foreign:frame'],font='sans',size='12',leading='1.35',align='left',color='#222222').status_code==400,'Foreign frame rejected')
check(post(studio_action='style',name='Bad type',frames=refs,font='sans',size='nan',leading='1.35',align='left',color='#222222').status_code==400,'Non-finite typography rejected')
check(post(studio_action='unlink',item_id=sid,revision=0).status_code==409,'Stale revision rejected')
check(post(studio_action='unlink',item_id=sid,theme_csrf_token='bad').status_code==400,'CSRF required')
with client.session_transaction() as session:session['user_id']=3
check(client.get(studio).status_code==404,'Contributor access denied')
with client.session_transaction() as session:session['user_id']=1
from pypdf import PdfReader
import io
result=pdf.render(z.pages(db,iid),lambda _:b'',mode='standard');check(len(PdfReader(io.BytesIO(result)).pages)==len(z.pages(db,iid)),'Linked text and masters export to PDF')
snapshot=json.loads(db.execute('SELECT snapshot FROM zine_revisions WHERE issue_id=? ORDER BY id DESC LIMIT 1',(iid,)).fetchone()[0]);check('authoring' in snapshot and snapshot['authoring']['stories'],'Authoring settings retained in revisions')
check(post(studio_action='unlink',item_id=sid).status_code==302,'Unlink keeps text');check(not a.get(db,iid)['stories'],'Story unlinked')
check(post(studio_action='detach_master',item_id=masterid).status_code==302,'Detach keeps master copies');check(not a.get(db,iid)['masters'],'Master detached')
restore_revision=db.execute('SELECT revision FROM zine_revisions WHERE issue_id=? ORDER BY id DESC LIMIT 1',(iid,)).fetchone()[0]
restore_url=base+'/restore/'+str(restore_revision)
check(client.post(restore_url,data={'theme_csrf_token':'fixture-token','revision':revision()}).status_code==400,'Restore requires explicit confirmation')
check(client.post(restore_url,data={'theme_csrf_token':'fixture-token','revision':0,'restore_confirm':'1'}).status_code==409,'Stale restore rejected')
check(client.post(restore_url,data={'theme_csrf_token':'fixture-token','revision':revision(),'restore_confirm':'1'}).status_code==302,'Retained snapshot restores draft')
check(bool(a.get(db,iid)['masters']),'Snapshot restores publishing-tool settings')
check(client.get(base+'/history').status_code==200,'History with restore controls renders')
db.execute("UPDATE zine_issues SET state='published' WHERE id=?",(iid,));db.commit()
check(post(studio_action='delete_style',item_id=styleid).status_code==409,'Published issue editing blocked')
print('PASS',checks,'authoring route, rollback and PDF checks')
