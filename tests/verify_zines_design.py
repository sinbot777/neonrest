from pathlib import Path
import sys,os,io,json,importlib,smtplib
smtplib.SMTP=lambda *a,**k:(_ for _ in ()).throw(AssertionError('SMTP forbidden'));smtplib.SMTP_SSL=smtplib.SMTP
package=sys.argv[1];stage=Path(sys.argv[2]);assert str(stage).startswith('/home/sinbot/releases/T34-design-')
bootstrap=(stage/'tests/verify_statistics_suite.py').read_text().split('from datetime import datetime,timedelta,timezone')[0];exec(compile(bootstrap,'isolated visual design bootstrap','exec'))
z=importlib.import_module(package+'.zines_core');pdf=importlib.import_module(package+'.zines_pdf')
from pypdf import PdfReader
work=stage.parents[1]
sections=['NEONREST / ISSUE ZERO / OCT 28, 2026','EDITORIAL / ORIGINAL COMMENTARY','NEWS DESK / REPORTED BRIEF + ANALYSIS','POWER / SOCIALIST COMMENTARY','LOUDER / MUSIC + SCENE CULTURE','ON THE GROUND / A SMALL PRACTICAL START','BACK PAGES / SOURCES + OPEN CALL','NO VIP SECTION IN THE FUTURE WE WANT.']
with app.app_context():
 db=core.get_db();source=z.pages(db,'zGvMmy3BQb_DMm9f');check(len(source)==8,'Published starter snapshot available')
 zid=z.create(db,users['Regular'],'Visual design fixture','');pub=z.publication(db,zid);iid=z.create_issue(db,pub,users['Regular'],'Punk visual fixture');new=z.pages(db,iid)
 for index,row in enumerate(source):
  data=json.loads(row['content']);data.update(design='punk',section=sections[index],pullquote=('NOISE FOR\nTHE MANY.' if index==0 else 'PUNK SUPPLIES THE REFUSAL.\nSOLIDARITY BUILDS THE ROOM.' if index==1 else ''),highlight='-0.5%' if index==2 else '',highlight_label='REAL HOURLY EARNINGS / AUG-SEP 2026' if index==2 else '')
  payload=z.content(db,zid,users['Regular'],data)
  if index in (0,7):db.execute('UPDATE zine_pages SET content=? WHERE id=?',(payload,new[0 if index==0 else 1]['id']))
  else:z.add_page(db,pub,z.get_issue(db,pub,iid),users['Regular'],data)
 db.execute('UPDATE zines SET allow_print=1 WHERE id=?',(zid,));db.execute('UPDATE zine_issues SET allow_print=1 WHERE id=?',(iid,));db.commit();rows=z.pages(db,iid)
 check(len(rows)==8,'Structured eight-page design')
 check(len(z.wave())==71,'Shared waveform geometry')
 for paper in ['letter','a4']:
  for mode in ['standard','booklet']:
   raw=pdf.render(rows,lambda aid:b'',mode,paper,True,'Punk fixture');(work/('proof-'+paper+'-'+mode+'.pdf')).write_bytes(raw);parsed=PdfReader(io.BytesIO(raw));check(len(parsed.pages)==(8 if mode=='standard' else 4),'Styled '+paper+' '+mode+' page count')
   alltext=' '.join(p.extract_text() for p in parsed.pages);check('STATIC' in alltext and 'SOLIDARITY' in alltext and '-0.5%' in alltext,'Styled text retained as actual PDF text')
   check(all('/Font' in p['/Resources'] for p in parsed.pages),'Real vector/text resources')
 try:z.content(db,zid,users['Regular'],{'design':'<script>'})
 except z.ZineError:check(True,'Design is a strict preset')
 else:raise AssertionError('Unsafe design accepted')
 check(json.loads(z.content(db,zid,users['Regular'],{'text':'Legacy'}))['design']=='classic','Classic default preserved')
base='/zines/'+zid+'/issues/'+iid
response=get('Regular',base);check(response.status_code==200,'Styled reader renders');check(b'zine-art-cover' in response.data and b'punk-wave' in response.data,'Cover layout and waveform in reader');check(response.data.count(b'<span style="height:')==71,'All waveform bars rendered')
response=get('Regular',base,page=3);check(b'punk-highlight' in response.data and b'-0.5%' in response.data,'Reader highlights from structured content')
response=get('Regular',base,page=8);check(b'zine-art-back' in response.data,'Back-cover poster layout')
response=get('Regular',base+'/edit');check(response.status_code==200 and b'Visual style' in response.data,'Design controls available in editor')
response=clients['Regular'].post(base+'/edit',data={'theme_csrf_token':token,'revision':'0','action':'state','state':'published'},environ_overrides=env);check(response.status_code==302,'Styled issue passes print publication preflight')
response=get('Regular',base+'/print',download='1',mode='booklet',paper='letter');check(response.status_code==200 and response.mimetype=='application/pdf','Actual route exports styled PDF')
print('PASS',checks,'visual-design checks; private fixture and reportlab output')
