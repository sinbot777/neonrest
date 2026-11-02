"""Permission-safe issue sharing and dynamically generated social cards."""
import hashlib,json,io,textwrap
from flask import url_for,abort,make_response
from . import zines_core as z
ORIGIN='https://www.neonrest.com'
def descriptor(db,zid,iid):
 p=z.publication(db,zid);issue=z.get_issue(db,p,iid)
 if issue['state']!='published' or p['visibility'] not in ('public','unlisted') or not z.visible(db,p,issue,None):return None
 rows=z.pages(db,iid);cover=json.loads(rows[0]['content']) if rows else {}
 revision=hashlib.sha256(json.dumps([dict(p),dict(issue),[dict(row) for row in rows]],sort_keys=True).encode()).hexdigest()[:20]
 title=issue['title'];description=(p['description'] or ('Read '+title+' on Neonrest.'))[:240]
 return dict(title=title,description=description,publication=p['title'],url=ORIGIN+url_for('zines.reader',zid=zid,iid=iid),image=ORIGIN+url_for('zines.share_image',zid=zid,iid=iid,revision=revision),type='article',alt=title+' — '+p['title']+' on Neonrest',revision=revision,cover=cover,asset=p['cover_asset'])
def context(db,p,issue):
 data=descriptor(db,p['id'],issue['id']);url=ORIGIN+url_for('zines.reader',zid=p['id'],iid=issue['id'])
 return dict(url=url,onsite=url_for('create_post',share_kind='zine',share_ref=issue['id']),public=bool(data),title=issue['title'] if data else 'Neonrest Zine'),data

def prepare(db,iid,user):
 row=db.execute('SELECT zine_id FROM zine_issues WHERE id=?',(iid,)).fetchone()
 if not user or not row:abort(404)
 p=z.publication(db,row[0]);issue=z.get_issue(db,p,iid)
 if not z.visible(db,p,issue,user):abort(404)
 url=ORIGIN+url_for('zines.reader',zid=p['id'],iid=iid)
 data=descriptor(db,p['id'],iid)
 return dict(content='Shared a Zine on Neonrest:\n\n'+url,preview=dict(kind='zine',url=url,title=issue['title'],excerpt=p['description'][:240],image=data['image'] if data else None,image_alt=data['alt'] if data else '',author=None,created_at=None,audience=('Published · '+p['visibility']) if data else 'Restricted · sharing does not grant access'))

def card(data,asset_bytes):
 from PIL import Image,ImageDraw,ImageOps
 from PIL import ImageFont
 def font(size,bold=False):
  path='/usr/share/fonts/truetype/dejavu/DejaVuSans'+('-Bold' if bold else '')+'.ttf'
  return ImageFont.truetype(path,size)
 def lines(draw,text,f,width,maximum):
  result=[];line=''
  for word in text.split():
   if line and draw.textbbox((0,0),line+' '+word,font=f)[2]>width:result.append(line);line=''
   line=(line+' '+word).strip()
  if line:result.append(line)
  if len(result)>maximum:result=result[:maximum];result[-1]=result[-1].rstrip(' .')+'…'
  return result
 canvas=Image.new('RGB',(1200,630),'#171923');draw=ImageDraw.Draw(canvas)
 draw.rectangle((0,0,1200,12),fill='#d85255');draw.text((50,35),'NEONREST / ZINES',font=font(25,True),fill='#e4c4ec')
 cover=data['cover'];composition=cover.get('composition',{});background=composition.get('background','#eee6d4');draw.rounded_rectangle((50,105,410,585),radius=8,fill=background)
 aid=data['asset'] or cover.get('image')
 if not aid:
  aid=next((b.get('image') for b in composition.get('blocks',[]) if b['type']=='image' and b.get('image')),None)
 if aid:
  try:
   im=Image.open(io.BytesIO(asset_bytes(aid))).convert('RGB');im=ImageOps.contain(im,(330,340));canvas.paste(im,(65+(330-im.width)//2,125+(340-im.height)//2))
  except (OSError,ValueError):pass
 for i,line in enumerate(lines(draw,data['title'],font(28,True),310,3)):draw.text((75,475+i*33),line,font=font(28,True),fill='#282334')
 for i,line in enumerate(lines(draw,data['publication'],font(24),680,2)):draw.text((455,120+i*32),line,font=font(24),fill='#c5b7d4')
 for i,line in enumerate(lines(draw,data['title'],font(47,True),680,4)):draw.text((455,225+i*58),line,font=font(47,True),fill='#fff9ed')
 draw.text((455,520),'READ THIS ZINE',font=font(24,True),fill='#f0999a');draw.text((455,566),'www.neonrest.com',font=font(22),fill='#c0cbd8')
 out=io.BytesIO();canvas.save(out,format='PNG',optimize=True);return out.getvalue()

def register(bp,core,asset_bytes):
 @bp.get('/zines/<zid>/issues/<iid>/preview/<revision>.png')
 def share_image(zid,iid,revision):
  data=descriptor(core.get_db(),zid,iid)
  if not data or data['revision']!=revision:abort(404)
  raw=card(data,lambda aid:asset_bytes(core.get_db(),z.publication(core.get_db(),zid),aid));response=make_response(raw);response.mimetype='image/png';response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','X-Robots-Tag':'noindex'});return response
