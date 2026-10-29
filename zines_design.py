"""Trusted punk design preset shared by the structured reader and PDF renderer."""
import io,math,random
from xml.sax.saxutils import escape
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from .zines_core import ZineError,wave
PAPER=HexColor('#f7f3e8');INK=HexColor('#171717');RED=HexColor('#b52525')

def register_fonts(reportlab):
 for name,system,bundled in [('ZineHeavy','DejaVuSans-Bold.ttf','VeraBd.ttf'),('ZineMono','DejaVuSansMono.ttf','Vera.ttf')]:
  p=Path('/usr/share/fonts/truetype/dejavu')/system
  if not p.exists():p=Path(reportlab.__file__).parent/'fonts'/bundled
  if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(p)))

def para(c,text,x,y,width,size=9.3,leading=12.65,color=INK,font='ZineText',bottom=34):
 for block in text.split('\n\n'):
  if not block:continue
  first=block.split('\n',1)
  if font=='ZineText' and len(first)==2 and first[0].isupper() and len(first[0])<80:
   y=para(c,first[0],x,y,width,9.3,12,RED,'ZineHeavy',bottom);block=first[1]
  face=pdfmetrics.getFont(font).face
  if any(ord(ch) not in face.charToGlyph for ch in block if ch not in '\n\r\t'):raise ZineError('This print font cannot render a character. Adjust the text before exporting.')
  p=Paragraph(escape(block).replace('\n','<br/>'),ParagraphStyle('punk',fontName=font,fontSize=size,leading=leading,textColor=color,splitLongWords=True))
  _,height=p.wrap(width,20000)
  if y-height<bottom:raise ZineError('A page has too much text for the punk print layout. Shorten it or split the page.')
  p.drawOn(c,x,y-height);y-=height+9
 return y

def picture(c,image_id,assets,y,max_height=130):
 if not image_id:return y
 pic=ImageReader(io.BytesIO(assets(image_id)));iw,ih=pic.getSize();scale=min(348/iw,max_height/ih);w,h=iw*scale,ih*scale
 if y-h<40:raise ZineError('The image does not fit the punk print layout.')
 c.drawImage(pic,24+(348-w)/2,y-h,w,h,mask='auto');return y-h-9

def draw(c,page,data,x,width,height,assets,numbers,number):
 # The fixed 396x612 design is scaled as vector/text onto each physical leaf.
 scale=min(width/396,height/612);c.saveState();c.translate(x+(width-396*scale)/2,(height-612*scale)/2);c.scale(scale,scale)
 kind=page['kind'];dark=kind in ('cover','back');c.setFillColor(INK if dark else PAPER);c.rect(0,0,396,612,fill=1,stroke=0)
 section=data.get('section','')
 if kind=='cover':
  c.setFillColor(PAPER);c.setFont('ZineMono',7);c.drawString(24,584,section[:80])
  title=data['heading'].replace(' & ','\n&\n');para(c,title,20,552,356,42,46,PAPER,'ZineHeavy',bottom=405)
  c.setFillColor(RED);c.rect(0,330,396,67,fill=1,stroke=0)
  para(c,data.get('pullquote') or 'NOISE FOR\nTHE MANY.',22,390,352,25,28,PAPER,'ZineHeavy',bottom=332)
  if data.get('image'):picture(c,data['image'],assets,308,110)
  else:
   c.setStrokeColor(PAPER);c.setLineWidth(2)
   for index,amplitude in enumerate(wave()):c.line(22+index*5,254-amplitude/2,22+index*5,254+amplitude/2)
  blocks=data['text'].split('\n\n');para(c,blocks[0] if blocks else '',24,190,348,14,20,PAPER,'ZineHeavy',bottom=135)
  quote=' '.join((data.get('pullquote') or 'NOISE FOR THE MANY.').split())
  rest=[b for b in blocks[1:] if ' '.join(b.split())!=quote]
  if rest:
   para(c,'\n'.join(rest[:-1]),24,125,348,7.7,11,PAPER,'ZineMono',bottom=66)
   footer=rest[-1].split('\n',1)
   c.setFillColor(RED);c.rect(24,30,348,30,fill=1,stroke=0)
   para(c,footer[0].upper(),34,51,328,10,12,PAPER,'ZineHeavy',bottom=32)
   if len(footer)>1:para(c,footer[1],24,23,348,6,8,PAPER,'ZineMono',bottom=8)
 elif kind=='back':
  c.setFillColor(RED);c.rect(0,579,396,33,fill=1,stroke=0);c.setFillColor(PAPER);c.setFont('ZineMono',7);c.drawString(24,591,section[:80])
  words=data['heading'].split()
  if len(words)<=7:
   c.setFont('ZineHeavy',45);y=502
   for index,word in enumerate(words):
    if index==3:y-=26
    if pdfmetrics.stringWidth(word,'ZineHeavy',45)>348:raise ZineError('Shorten a word in this back-cover title.')
    c.drawString(24,y,word);y-=52
  else:para(c,data['heading'],24,530,348,34,40,PAPER,'ZineHeavy',bottom=205)
  c.setFillColor(RED);c.rect(24,190,348,8,fill=1,stroke=0)
  blocks=data['text'].split('\n\n');para(c,blocks[0] if blocks else '',24,167,348,9.2,14,PAPER,bottom=90)
  para(c,data.get('pullquote') or (blocks[1] if len(blocks)>1 else ''),24,82,348,11,15,PAPER,'ZineHeavy',bottom=33)
 else:
  c.setFillColor(RED);c.rect(0,592,396,20,fill=1,stroke=0);c.setFillColor(PAPER);c.setFont('ZineMono',6.8);c.drawString(24,599,section[:80])
  y=para(c,data['heading'],24,572,348,26,30,INK,'ZineHeavy')
  c.setStrokeColor(INK);c.setLineWidth(1.4);c.line(24,y+3,372,y+3);y-=12
  if data.get('highlight'):
   y=para(c,data['highlight'],24,y,348,39,42,RED,'ZineHeavy');y=para(c,data.get('highlight_label',''),24,y+4,348,6.5,9,INK,'ZineMono')
  if data.get('image') and data['layout']=='image-top':y=picture(c,data['image'],assets,y)
  y=para(c,data['text'],24,y,348)
  if data.get('image') and data['layout']!='image-top':y=picture(c,data['image'],assets,y)
  if data.get('caption'):y=para(c,data['caption'],24,y,348,8,11)
  if data.get('print_alternative'):y=para(c,data['print_alternative'],24,y,348,8,11)
  if data.get('pullquote') and y>112:
   c.setFillColor(RED);c.rect(24,48,348,48,fill=1,stroke=0);para(c,data['pullquote'],33,84,330,9.6,13,PAPER,'ZineHeavy',bottom=49)
 if numbers:
  c.setFillColor(PAPER if dark else INK);c.setFont('ZineMono',7);c.drawRightString(372,17,str(number))
 c.restoreState()
