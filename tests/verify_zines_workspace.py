"""Reader grouping and access regression using the isolated component app."""
from pathlib import Path
import runpy,re
fixture=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
client,z,db,pub,iid=(fixture[n] for n in ('client','z','db','pub','iid'))
base='/zines/'+pub['id']+'/issues/'+iid
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
def shown(response):return list(map(int,re.findall(rb'id="zine-page-(\d+)"',response.data)))
for total in (7,8):
 while len(z.pages(db,iid))<total:z.add_page(db,pub,z.get_issue(db,pub,iid),1,{'heading':'Extra page','text':'More body.'})
 db.commit()
 expected=[[1]]+[list(range(n,min(n+2,total))) for n in range(2,total,2)]+[[total]]
 for group in expected:
  for page in group:
   r=client.get(base,query_string={'reading':'spread','page':page})
   check(r.status_code==200 and shown(r)==group,'Exact spread group '+str(group))
   check(b'reading=spread' in r.data,'Spread links preserve mode')
 for page in (1,2,total):
  r=client.get(base,query_string={'reading':'single','page':page});check(shown(r)==[page],'Single-page request')
 r=client.get(base,query_string={'reading':'scroll','page':2});check(shown(r)==list(range(1,total+1)),'Scroll has every page once in order')
 check(shown(client.get(base,query_string={'reading':'invalid'}))==[1],'Unknown reading view falls back safely')
 check(client.get(base,query_string={'reading':'scroll','page':total+1}).status_code==404,'Invalid page rejected in all views')
with client.session_transaction() as state:state.clear()
for view in ('single','spread','scroll'):check(client.get(base,query_string={'reading':view}).status_code==404,'Private issue denied in '+view)
print('PASS',checks,'reader view checks')
