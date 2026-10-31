"""Native template context for front, interior and back preset examples."""
import runpy
from pathlib import Path
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
client,z,db,iid,edit=(f[k] for k in ('client','z','db','iid','edit'))
rows=z.pages(db,iid)
for kind,number in [('cover',1),('page',2),('back',len(rows))]:
 response=client.get(edit,query_string={'page':number});assert response.status_code==200
 assert ('data-page-kind="'+kind+'"').encode() in response.data,kind
 Path('/tmp/zine-style-'+kind+'.html').write_bytes(response.data)
print('PASS 3 native style-preview page contexts')
