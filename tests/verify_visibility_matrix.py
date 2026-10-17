from pathlib import Path
import ast,json,gc
base=Path(__file__).with_name('verify_circles_full_app.py'); source_text=base.read_text().replace("('Teen','2011-01-01')","('Teen','2013-01-01')")
first=next(n for n in ast.parse(source_text).body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='check')
exec(compile('\n'.join(source_text.splitlines()[:first.lineno-1]),str(base),'exec'))
from neonrest import public_ids,age_policy as ages
from urllib.parse import urlsplit
from html import unescape
checks=0;rows=[]
def expect(ok,label):
 global checks
 assert ok,label
 checks+=1
def fresh():change('DELETE FROM rate_buckets')
def public_post(pid):
 with app.app_context():return public_ids.public(core.get_db(),'post',pid)
def edit(pid,marker,audience,external):
 fresh();ref=public_post(pid)
 response=clients['Owner'].get('/edit_post/'+ref,environ_overrides={'SCRIPT_NAME':''})
 expect(response.status_code==200,'Author opens edit form')
 html=response.get_data(as_text=True)
 action=unescape(re.search(r'<form method="POST" action="([^"]+)"',html).group(1))
 csrf=unescape(re.search(r'name="theme_csrf_token" value="([^"]+)"',html).group(1))
 expect(action=='/edit_post/'+ref,'Edit action retains Sandbox and opaque ID')
 data={'content':marker,'vibes':'','circle':'','circle_audience':audience,'theme_csrf_token':csrf}
 if external:data['allow_circle_sharing']='1'
 return clients['Owner'].post(action.removeprefix(''),data=data,environ_overrides={'SCRIPT_NAME':''})
def views(cid,pid,marker,comment,filename,public):
 ref=public_post(pid); path='/posts/'+ref
 for label,client,member,eligible in [('author',clients['Owner'],True,True),('member',clients['Member'],True,True),('adult nonmember',clients['Outsider'],False,True),('signed out',guest,False,True),('13-year-old',clients['Teen'],False,False)]:
  allowed=eligible and (member or public)
  response=client.get(path)
  expect(response.status_code==(200 if allowed else 404),label+' original visibility '+marker)
  expect((marker.encode() in response.data)==allowed,label+' original text '+marker)
  expect((comment.encode() in response.data)==(allowed and member),label+' members-only replies '+marker)
  response=client.get('/circles/'+public_circle(cid))
  expect((marker.encode() in response.data)==allowed,label+' Circle feed '+marker)
  expect((filename.encode() in response.data)==allowed,label+' Circle photo/gallery '+marker)
  response=client.get('/media-file/'+filename)
  expect(response.status_code==(200 if allowed else 404),label+' original photo access '+marker)
  response.close()
def shared_views(wrapper,marker,allowed):
 ref=public_post(wrapper)
 for label,client,eligible in [('adult nonmember',clients['Outsider'],True),('signed out',guest,True),('13-year-old',clients['Teen'],False)]:
  response=client.get('/posts/'+ref)
  expect((marker.encode() in response.data)==(allowed and eligible),label+' shared source text '+marker+' HTTP '+str(response.status_code)+' marker='+str(marker.encode() in response.data))
  media=client.get('/shared-media/'+ref+'/image/filename')
  expect(media.status_code==(200 if allowed and eligible else 404),label+' shared photo '+marker);media.close()
guest=app.test_client()
with app.app_context():expect(ages.age(core.get_db(),users['Teen'])==13,'Fictional younger reader is 13')
for mode in ['public','discoverable','hidden']:
 fresh();cid=create(mode);ct=public_circle(cid)
 expect(post('Member','/circles/'+ct+'/join').status_code==302,'Member requests access') if mode!='hidden' else None
 if mode=='hidden':expect(manage('Owner',cid,'invite',handle='@CircleFixtureMember').status_code==302,'Hidden Circle invitation')
 if mode=='hidden':expect(post('Member','/circles/'+ct+'/join').status_code==302,'Invited member accepts')
 else:expect(manage('Owner',cid,'approve',user_id=users['Member']).status_code==302,'Member approval')
 for audience in ['private','public']:
  for external in [False,True]:
   fresh();marker='MATRIX'+mode.upper()+audience.upper()+str(int(external))+'SENTINEL';comment='REPLY'+marker
   photo=io.BytesIO();Image.new('RGB',(8,8),'blue').save(photo,'PNG');photo.seek(0)
   data={'content':marker,'circle_id':ct,'circle_audience':audience,'theme_csrf_token':token,'post_image':(photo,'matrix.png')}
   if external:data['allow_circle_sharing']='1'
   before=query('SELECT count(*) FROM posts')[0][0]
   response=clients['Owner'].post('/create_post',data=data)
   valid=mode=='public' or audience=='private'
   expect(response.status_code==(302 if valid else 400),'Creation '+marker+' got '+str(response.status_code))
   if not valid:
    expect(query('SELECT count(*) FROM posts')[0][0]==before,'Invalid public choice creates no post')
    rows.append({'circle':mode,'post':audience,'outside_sharing':external,'result':'rejected as expected'});continue
   pid=query('SELECT MAX(post_id) FROM circle_posts WHERE circle_id=?',(cid,))[0][0];ref=public_post(pid)
   filename=query("SELECT filename FROM post_media WHERE post_id=? AND kind='image'",(pid,))[0][0]
   expect(post('Member','/create_comment',post_id=ref,content=comment).status_code in (201,302),'Member reply '+marker)
   is_public=mode=='public' and audience=='public'
   views(cid,pid,marker,comment,filename,is_public)
   share_allowed=is_public or external
   fresh();before=query('SELECT count(*) FROM posts')[0][0]
   response=post('Member','/create_post',content='Fictional share commentary',shared_source=ref,shared_kind='post',audience='public')
   expect(response.status_code==(302 if share_allowed else 400),'Author share choice enforced '+marker+' got '+str(response.status_code))
   if share_allowed:
    wrapper=query('SELECT MAX(share_post_id) FROM post_shares')[0][0];shared_views(wrapper,marker,True)
   else:
    expect(query('SELECT count(*) FROM posts')[0][0]==before,'Denied share creates no post')
    response=edit(pid,marker,audience,True);expect(response.status_code==302 and response.location=='/feed','Enable sharing preserves Sandbox redirect')
    fresh();expect(post('Member','/create_post',content='Fictional share commentary',shared_source=ref,shared_kind='post',audience='public').status_code==302,'Sharing can be enabled after posting')
    wrapper=query('SELECT MAX(share_post_id) FROM post_shares')[0][0];shared_views(wrapper,marker,True)
   response=edit(pid,marker,audience,False);expect(response.status_code==302 and response.location=='/feed','Disable sharing preserves Sandbox redirect')
   shared_views(wrapper,marker,is_public)
   views(cid,pid,marker,comment,filename,is_public)
   if mode=='public':
    opposite='private' if audience=='public' else 'public'
    response=edit(pid,marker,opposite,False);expect(response.status_code==302,'Author changes post visibility')
    views(cid,pid,marker,comment,filename,opposite=='public');shared_views(wrapper,marker,opposite=='public')
    response=edit(pid,marker,audience,False);expect(response.status_code==302,'Author restores visibility')
    shared_views(wrapper,marker,is_public)
   else:
    response=edit(pid,marker,'public',True);expect(response.status_code==400,'Members-only Circle rejects public edit')
    expect(query('SELECT audience FROM circle_post_visibility WHERE post_id=?',(pid,))[0][0]=='private','Rejected edit preserves visibility')
    expect(query('SELECT external_circle FROM post_share_permissions WHERE post_id=?',(pid,))[0][0]==0,'Rejected edit preserves sharing choice')
    shared_views(wrapper,marker,False)
   rows.append({'circle':mode,'post':audience,'outside_sharing':external,'visitor_original':is_public,'outside_preview':share_allowed,'result':'passed'})
   print('CASE PASS',mode,audience,'outside-sharing='+str(external),'checks='+str(checks),flush=True)
report={'status':'passed','checks':checks,'cases':rows,'disposable_fixture':True,'live_data_changed':False,'smtp_used':False}
Path(__file__).parents[2].joinpath('matrix-result.json').write_text(json.dumps(report,indent=2))
gc.collect();work.cleanup()
print('VISIBILITY MATRIX PASS',checks,'checks;',len(rows),'combinations; live data untouched; no SMTP',flush=True)
