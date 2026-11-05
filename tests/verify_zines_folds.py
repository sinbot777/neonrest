"""Single-sheet ordering, print geometry, existing access controls, proof/guide isolation."""
from pathlib import Path
import runpy,importlib,json,io,math
from pypdf import PdfReader
f=runpy.run_path(str(Path(__file__).with_name('verify_zines_advanced_local.py')))
folds=importlib.import_module('zine_candidate.zines_folds');z=f['z'];pdf=f['pdf'];checks=0

def check(v,m):
 global checks
 assert v,m
 checks+=1

def reject(fn,m):
 try:fn()
 except z.ZineError:check(True,m)
 else:raise AssertionError(m)

def rows(n):
 return [{'id':str(i),'kind':'cover' if i==0 else 'back' if i==n-1 else 'page','content':json.dumps({'design':'composition','composition':{'version':1,'background':'#ffffff','blocks':[{'id':'label','type':'text','text':'Panel '+str(i+1),'x':24,'y':24,'w':340,'h':72,'font':'bold','size':24,'leading':1.2,'align':'center','color':'#171717','fill':'transparent','stroke':'#171717','stroke_width':0,'locked':False,'rotation':0,'opacity':1}]}})} for i in range(n)]
for n in range(2,9):
 layout=folds.mini8(rows(n));check(len(layout)==8,'Eight cells');check(sum(slot['page'] is None for slot in layout)==8-n,'Correct blank padding');check(layout[6]['page']['kind']=='back' and layout[7]['page']['kind']=='cover','Covers remain adjacent in fixed positions');check([s['rotation'] for s in layout]==[180]*4+[0]*4,'Top panels rotated')
 for paper,size in [('letter',(792,612)),('a4',(841.8898,595.2756))]:
  raw=pdf.render(rows(n),lambda aid:b'','mini8',paper,guides=True);reader=PdfReader(io.BytesIO(raw));check(len(reader.pages)==1,'One printed side');box=reader.pages[0].mediabox;check(abs(float(box.width)-size[0])<.01 and abs(float(box.height)-size[1])<.01,'Landscape paper dimensions');text=reader.pages[0].extract_text();check(all('Panel '+str(i+1) in text for i in range(n)),'All original panels retained once')
reject(lambda:folds.mini8(rows(9)),'Over-eight rejected');reject(lambda:pdf.render(rows(8),lambda aid:b'','mini8','issue',page_size={'width':252,'height':144,'content_scale':.2}),'Ambiguous issue-size sheet rejected')
for inset in ['nan','inf','-1','12.8','bad']:reject(lambda:folds.inset(inset),'Invalid inset rejected')
check(abs(folds.inset('12.7')-36)<.0001,'Metric inset conversion')
raw=pdf.render(rows(8),lambda aid:b'','mini8','letter',proof=True);proof=PdfReader(io.BytesIO(raw));text=proof.pages[0].extract_text();check('Front cover' in text and 'Back cover' in text and 'Panel 1' not in text,'Proof substitutes numbers without artwork')
stream=proof.pages[0].get_contents().get_data().decode('latin1');check('198 306 m 594 306 l' in stream,'Cut slit exactly middle half of center line');check('[3 3]' in stream,'Dashed folds')
clean=PdfReader(io.BytesIO(pdf.render(rows(8),lambda aid:b'','mini8'))).pages[0].get_contents().get_data().decode('latin1');check('198 306 m 594 306 l' not in clean,'Guides absent from clean export')
seen=[]
def visitor(text,cm,tm,font,size):
 if text.strip().startswith('Panel '):seen.append((text.strip(),cm))
pdfpage=PdfReader(io.BytesIO(pdf.render(rows(8),lambda aid:b'','mini8'))).pages[0];pdfpage.extract_text(visitor_text=visitor)
check([text for text,cm in seen]==['Panel 5','Panel 4','Panel 3','Panel 2','Panel 6','Panel 7','Panel 8','Panel 1'],'Verified NASA/Chandra panel order')
check(all(cm[0]<0 and cm[3]<0 for _,cm in seen[:4]) and all(cm[0]>0 and cm[3]>0 for _,cm in seen[4:]),'Actual PDF top row inverted and bottom row upright')
f['app'].extensions['community_auth_helpers']['limited']=lambda *args,**kwargs:None # Fixture adapter accepts the existing limiter signature.
client,db,iid,zid=f['client'],f['db'],f['iid'],f['zid'];db.execute('UPDATE zines SET allow_print=1 WHERE id=?',(zid,));db.execute('UPDATE zine_issues SET allow_print=1 WHERE id=?',(iid,));db.commit()
url='/zines/'+zid+'/issues/'+iid+'/print';response=client.get(url);check(response.status_code==200 and b'data-fold-preview' in response.data,'Native print controls render')
response=client.get(url,query_string={'download':'1','mode':'mini8','paper':'letter','proof':'1'});check(response.status_code==200 and len(PdfReader(io.BytesIO(response.data)).pages)==1,'Actual protected download route exports single sheet')
response=client.get(url,query_string={'download':'1','mode':'mini8','panel_inset':'nan'});check(response.status_code==400,'Invalid print options rejected via route')
Path(__file__).parents[1].joinpath('fold-preview-fixture.html').write_bytes(client.get(url).data)
with client.session_transaction() as state:state.clear()
check(client.get(url,query_string={'download':'1','mode':'mini8','proof':'1'}).status_code==404,'Proof respects private issue access')
out=Path(__file__).parents[1]/'tmp/pdfs';out.mkdir(parents=True,exist_ok=True);(out/'mini8-proof.pdf').write_bytes(raw);(out/'mini8-artwork.pdf').write_bytes(pdf.render(rows(8),lambda aid:b'','mini8',guides=True))
print('PASS',checks,'fold ordering, geometry, guides and protected download checks')
