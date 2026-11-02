import runpy,json,copy,re
from pathlib import Path
f=runpy.run_path(str(Path(__file__).with_name('test_authoring.py')));db,client,z,pub,iid,zid,a=(f[k] for k in ('db','client','z','pub','iid','zid','a'));checks=0
base='/zines/'+zid+'/issues/'+iid
with client.session_transaction() as state:state['user_id']=1
db.execute("UPDATE zine_issues SET state='draft' WHERE id=?",(iid,));db.commit()
def check(v,label):
 global checks
 assert v,label
 checks+=1
def rev():return z.get_issue(db,pub,iid)['revision']
def save(row,data):return client.post(base+'/edit',data={'theme_csrf_token':'fixture-token','revision':rev(),'action':'page','page_id':row['id'],'design':'composition','layout':'text','composition':json.dumps(data['composition'])})
rows=z.pages(db,iid);target=next((row,json.loads(row['content'])) for row in rows if any(b['id'].startswith('m') for b in json.loads(row['content']).get('composition',{}).get('blocks',[])))
row,data=target;before=rev();changed=copy.deepcopy(data);next(b for b in changed['composition']['blocks'] if b['id'].startswith('m'))['text']='local override'
check(save(row,changed).status_code==409,'Managed master edits explicitly rejected')
check(rev()==before and db.execute('SELECT content FROM zine_pages WHERE id=?',(row['id'],)).fetchone()[0]==row['content'],'Master rejection atomic')
style=next(iter(a.get(db,iid)['styles'].values()));ref=style['frames'][0];pid,bid=ref.split(':');row=db.execute('SELECT * FROM zine_pages WHERE id=?',(pid,)).fetchone();data=json.loads(row['content']);changed=copy.deepcopy(data);next(b for b in changed['composition']['blocks'] if b['id']==bid)['size']+=1
check(save(row,changed).status_code==409,'Named-style local override explicitly rejected')
check(rev()==before,'Style rejection keeps revision')
production=client.get(base+'/edit').data;sandbox=client.get(base+'/edit',environ_overrides={'SCRIPT_NAME':'/sandbox'}).data
check(b'data-preference-key="neonrest-zine-tools-v1-production-1"' in production,'Production layout storage namespaced')
check(b'data-preference-key="neonrest-zine-tools-v1-_sandbox-1"' in sandbox,'Sandbox layout storage namespaced')
check(b'data-legacy-preference-key=' not in production and b'data-legacy-preference-key=' in sandbox,'Legacy layout fallback limited to Sandbox')
# A retained snapshot cannot restore a now-blocked contributor's work.
issue=dict(z.get_issue(db,pub,iid));pages=[dict(row) for row in z.pages(db,iid)];pages[0]['author_id']=2
payload={'issue':issue,'pages':pages,'page_size':None,'authoring':a.get(db,iid)}
db.execute('INSERT INTO zine_revisions(issue_id,actor_id,revision,snapshot,created_at) VALUES (?,?,?,?,0)',(iid,1,999,json.dumps(payload)));db.execute('INSERT INTO user_blocks VALUES(?,?)',(1,2));db.commit();count=db.execute('SELECT count(*) FROM zine_revisions WHERE issue_id=?',(iid,)).fetchone()[0]
response=client.post(base+'/restore/999',data={'theme_csrf_token':'fixture-token','revision':rev(),'restore_confirm':'1'})
check(response.status_code==404 and rev()==before,'Blocked contributor snapshot restore rejected')
check(db.execute('SELECT count(*) FROM zine_revisions WHERE issue_id=?',(iid,)).fetchone()[0]==count,'Rejected restore leaves history intact')
css=(Path(__file__).parent/'static/zines_appearance.css').read_text().split('/* PDX_CARPET_V1',1)[1]
from urllib.parse import unquote
import xml.etree.ElementTree as ET
svgs=re.findall(r'data:image/svg\+xml,([^"\)]+)',css);check(len(svgs)==2,'PDX uses two vector layers')
for encoded in svgs:
 root=ET.fromstring(unquote(encoded));groups=[g for g in root.iter() if g.tag.endswith('}g') and g.get('transform','').startswith('translate(')]
 check(len(groups)==9,'Every PDX layer wraps nine neighbor copies')
 check({g.attrib['transform'] for g in groups}=={'translate('+str(x)+' '+str(y)+')' for x in (-128,0,128) for y in (-128,0,128)},'PDX layer translations periodic')
check('forced-colors:active' in css and '@media print' in css,'PDX respects print and forced colors')
exported=z.export_user(db,1)
check(any(row['id']==iid for row in exported['owned_issues']),'Owner export includes issue metadata')
check(any(row['issue_id']==iid and row['authoring'] for row in exported['owned_issue_settings']),'Owner export includes canonical stories/styles/masters')
check(not z.export_user(db,3)['owned_issue_settings'],'Contributor export excludes another owner’s issue settings')
# Opaque chrome must retain normal-text contrast across presets and gray choices.
import importlib
appearance=importlib.import_module('zine_candidate.zines_appearance')
chrome=(Path(__file__).parent/'static/zines_appearance.css').read_text().split('/* CHROME_CONTRAST_V1',1)[1]
inks=re.findall(r'--studio-ink:(#[0-9a-fA-F]{3,6})',chrome)
def luminance(color):
 color=color.lstrip('#')
 if len(color)==3:color=''.join(c*2 for c in color)
 values=[int(color[i:i+2],16)/255 for i in (0,2,4)]
 return sum((v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4)*weight for v,weight in zip(values,(.2126,.7152,.0722)))
colors=[p['color'] for p in appearance.PRESETS]+['#'+format(i,'02x')*3 for i in range(256)]
for color in colors:
 appearance.save(db,'publication',zid,{'backdrop_color':color})
 context=appearance.context(db,zid)
 background=luminance(color);foreground=luminance(inks[int(context['backdrop_dark'])])
 check((max(background,foreground)+.05)/(min(background,foreground)+.05)>=4.5,'Normal screen-control text contrast '+color)
print('PASS',checks,'release guards, environment isolation, carpet and contrast checks')
