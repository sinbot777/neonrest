"""Anchored image validation, layout, authorization and PDF regression."""
import runpy,copy,json,io,importlib,sys
from pathlib import Path
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
z,db,pub,iid,composition,pdf,client,post=(f[n] for n in ('z','db','pub','iid','composition','pdf','client','post'))
flow=importlib.import_module('zine_candidate.zines_flow')
from PIL import Image,ImageDraw
from pypdf import PdfReader
checks=0
def check(ok,label):
 global checks
 assert ok,label
 checks+=1
body='A neighborhood story starts with people sharing what they know. Pictures belong with the words that explain them. '*8
block=copy.deepcopy(f['layout']['blocks'][0]);block.update(x=24,y=24,w=348,h=540,rotation=0,group='',text=body,size=11,leading=1.35)
inset=dict(at=0,image='flow-art',alt='Fictional geometric artwork',mode='wrap-left',width=38,height=76,gap=6,caption='Artwork in the story',credit='Neonrest test fixture')
db.execute('INSERT INTO zine_assets VALUES (?,?,?,?,?,?,?)',('flow-art',pub['id'],1,'fixture-flow',100,'fixture-hash',0));db.commit()
image=Image.new('RGB',(360,200),'#b52f48');drawing=ImageDraw.Draw(image);drawing.ellipse((115,30,245,160),fill='#f4eddd');out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue()
proof=[]
for mode in ('inline','wrap-left','wrap-right','full'):
 b=copy.deepcopy(block);b['insets']=[{**inset,'mode':mode,'at':15 if mode=='inline' else 0}];page=composition.normalize({'version':1,'background':'#fffaf0','blocks':[b]});b=page['blocks'][0]
 check(b['insets'][0]['mode']==mode,'Placement survives schema '+mode)
 check(composition.asset_ids({'composition':page})==['flow-art'],'Embedded artwork included in authorization '+mode)
 marks=flow.layout(b);pictures=[m for m in marks if m['type']=='image'];check(len(pictures)==1,'One image drawn '+mode)
 if mode=='wrap-left':
  text_marks=[m for m in marks if m.get('body')];check(text_marks[0]['x']>pictures[0]['x']+pictures[0]['w'],'Text starts beside left image');check(any(m['x']==0 and m['y']>pictures[0]['y']+pictures[0]['h'] for m in text_marks),'Text returns to full width below float')
 if mode=='full':check(all(m['y']>pictures[0]['y']+pictures[0]['h'] for m in marks if m.get('body')),'Full-width image separates paragraphs')
 check(all(m['x']>=0 and m['y']>=0 and m.get('x',0)+m.get('w',0)<=b['w']-8+.01 for m in marks),'Print marks inside frame '+mode)
 target=next(r for r in z.pages(db,iid) if r['kind']=='page');response=post(action='page',page_id=target['id'],design='composition',composition=json.dumps(page),layout='text');check(response.status_code==302,'Route saves anchored artwork '+mode)
 reader=client.get('/zines/'+pub['id']+'/issues/'+iid+'?page=2');check(reader.status_code==200 and ('zc-flow-'+mode).encode() in reader.data,'Reader renders anchored placement '+mode)
 proof.append({'id':'proof-'+mode,'kind':'page','content':json.dumps({'design':'composition','composition':page})})
# Real route must reject foreign artwork atomically.
bad=copy.deepcopy(page);bad['blocks'][0]['insets'][0]['image']='foreign-art';before=z.get_issue(db,pub,iid)['revision'];check(post(action='page',page_id=target['id'],design='composition',composition=json.dumps(bad),layout='text').status_code==404,'Foreign embedded asset denied');check(z.get_issue(db,pub,iid)['revision']==before,'Asset denial preserves revision')
for key,value in [('at',-1),('at',True),('at',99999),('width',101),('height',181),('gap',float('nan')),('mode','javascript:bad'),('caption','x'*201)]:
 bad=copy.deepcopy(inset);bad[key]=value
 try:flow.normalize([bad],len(body))
 except z.ZineError:check(True,'Reject invalid '+key)
 else:raise AssertionError('Accepted invalid '+key)
try:flow.normalize([inset]*7,len(body))
except z.ZineError:check(True,'Bound images per frame')
else:raise AssertionError('Unbounded inset images')
short=copy.deepcopy(block);short.update(h=20,insets=[inset])
try:flow.layout(composition.normalize({'version':1,'background':'#ffffff','blocks':[short]})['blocks'][0])
except z.ZineError:check(True,'Print overflow explicit')
else:raise AssertionError('Overflow silently clipped')
spaced=copy.deepcopy(block);spaced.update(text='  First\r\nSecond  ',insets=[{**inset,'at':9}]);normalized=composition.normalize({'version':1,'background':'#ffffff','blocks':[spaced]})['blocks'][0];check(normalized['text']=='  First\nSecond  ' and normalized['insets'][0]['at']==8,'Whitespace retained and CRLF anchors remapped')
for paper in ('letter','a4'):
 for mode in ('standard','booklet'):
  data=pdf.render(proof,lambda aid:raw,mode,paper);parsed=PdfReader(io.BytesIO(data));text=' '.join(p.extract_text() or '' for p in parsed.pages)
  check('Artwork in the story' in text and 'Neonrest test fixture' in text,'Caption and credit selectable '+paper+mode)
  check(sum(len(p.images) for p in parsed.pages)>=2,'Embedded images exported '+paper+mode)
  if '--proof' in sys.argv and paper=='letter' and mode=='standard':Path('/tmp/zine-flow-proof.pdf').write_bytes(data)
print('PASS',checks,'anchored image and print checks')
