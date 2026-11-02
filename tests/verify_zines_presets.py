"""All preset palettes survive native save/render; visual cards share validated data."""
import runpy,json
from pathlib import Path
from html.parser import HTMLParser
from html import unescape
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_appearance.py')))
a,db,client,save,zid=(f[k] for k in ('a','db','client','save','zid'))
assert len(a.PRESETS)==65 and len({p['id'] for p in a.PRESETS})==65
assert len({tuple(p[k] for k in a.DEFAULT) for p in a.PRESETS})==65
checks=2
for preset in a.PRESETS:
 form={'backdrop_'+k:str(preset[k]) for k in a.DEFAULT}
 parsed=a.parse(form);assert all(parsed[k]==preset[k] for k in a.DEFAULT)
 assert save(**form).status_code==302
 response=client.get('/zines/'+zid+'/edit');assert response.status_code==200
 assert ('data-zine-pattern="'+preset['pattern']+'"').encode() in response.data
 assert preset['name'] in unescape(response.data.decode())
 assert a.get(db,'publication',zid)==parsed
 checks+=5
class Cards(HTMLParser):
 def __init__(self):super().__init__();self.cards=[]
 def handle_starttag(self,tag,attrs):
  values=dict(attrs)
  if 'data-backdrop-preset' in values:self.cards.append(json.loads(values['data-backdrop-preset']))
cards=Cards();cards.feed(response.data.decode());assert len(cards.cards)==65
for card in cards.cards:
 assert card['css']==a.css(card)
 assert 'http' not in card['css'] and '<' not in card['css']
checks+=131
assert b'<details open><summary>Backdrop &amp; atmosphere' in response.data or b'<details open><summary>Backdrop & atmosphere' in response.data
assert b'<select name="backdrop_pattern">' in response.data
print('PASS',checks+2,'preset palette, storage, native card and discoverability checks')
