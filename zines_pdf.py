"""Bounded vector/text print rendering; landscape two-up saddle-stitch imposition."""
import io
import json
import sys
import threading
from pathlib import Path
from xml.sax.saxutils import escape
try:
    import reportlab
except ModuleNotFoundError:
    sys.path.append(str(Path(__file__).parent/'_zine_vendor'))
    import reportlab
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter,A4,landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.lib.utils import ImageReader
from .zines_core import ZineError,impose
LOCK=threading.BoundedSemaphore(1)
font_path=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
if not font_path.exists():font_path=Path(reportlab.__file__).parent/'fonts'/'Vera.ttf'
pdfmetrics.registerFont(TTFont('ZineText',str(font_path)))
FONT=pdfmetrics.getFont('ZineText')
from . import zines_design
zines_design.register_fonts(reportlab)

def paragraph(c,text,x,y,width,size=10,leading=14):
    if not text:return y
    if any(ord(ch) not in FONT.face.charToGlyph for ch in text if ch not in '\n\r\t'):
        raise ZineError('This print edition contains a character the print font cannot render. Adjust the text before exporting.')
    style=ParagraphStyle('zine',fontName='ZineText',fontSize=size,leading=leading,textColor='#111111',splitLongWords=True)
    p=Paragraph(escape(text).replace('\n','<br/>'),style)
    _,height=p.wrap(width,20000)
    if height>y-30:raise ZineError('A page has too much text for this print format. Shorten it, split it across pages, or remove its image.')
    p.drawOn(c,x,y-height)
    return y-height-12

def draw_page(c,page,x,width,height,assets,numbers=False,number=0):
    if page is None:return
    data=json.loads(page['content'])
    if data.get('design')=='punk':return zines_design.draw(c,page,data,x,width,height,assets,numbers,number)
    margin=30; left=x+margin; available=width-2*margin; y=height-margin
    c.saveState()
    c.setFillColorRGB(1,1,1);c.rect(x,0,width,height,fill=1,stroke=0)
    y=paragraph(c,data['heading'],left,y,available,17,21)
    def image_block(y):
        if not data.get('image'):return y
        raw=assets(data['image']);pic=ImageReader(io.BytesIO(raw));iw,ih=pic.getSize()
        scale=min(available*{'full':1,'medium':.67,'small':.34}.get(data.get('image_width','full'),1)/iw, min(180,height*0.30)/ih)
        w,h=iw*scale,ih*scale
        if y-h<42:raise ZineError('The image does not fit this print page.')
        offset=0 if data.get('image_align')=='left' else available-w if data.get('image_align')=='right' else (available-w)/2
        c.drawImage(pic,left+offset,y-h,w,h,mask='auto')
        return paragraph(c,data['caption'],left,y-h-8,available,9,12)
    if data['layout']=='image-top':y=image_block(y)
    body_size={'small':8.8,'regular':10,'large':11.6}.get(data.get('text_size','regular'),10)
    y=paragraph(c,data['text'],left,y,available,body_size,body_size*1.4)
    if data['layout']!='image-top':y=image_block(y)
    if data.get('print_alternative'):y=paragraph(c,data['print_alternative'],left,y,available,9,12)
    if numbers:
        c.setFont('ZineText',8);c.setFillColorRGB(0.25,0.25,0.25);c.drawCentredString(x+width/2,15,str(number))
    c.restoreState()

def render(reading,assets,mode='standard',paper='letter',numbers=False,title='Neonrest Zine'):
    if mode not in ('standard','booklet') or paper not in ('letter','a4'):raise ZineError('Choose a supported print format.')
    if not LOCK.acquire(blocking=False):raise ZineError('Another print edition is being prepared. Try again shortly.',429)
    try:
        if not 2<=len(reading)<=64:raise ZineError('Print editions require 2–64 pages.')
        from PIL import Image
        cache={};total_bytes=0;total_pixels=0
        for page in reading:
            image_id=json.loads(page['content']).get('image')
            if image_id and image_id not in cache:
                raw=assets(image_id);total_bytes+=len(raw)
                with Image.open(io.BytesIO(raw)) as pic:total_pixels+=pic.width*pic.height
                if len(raw)>512*1024 or total_bytes>8*1024*1024 or total_pixels>12000000:raise ZineError('This print edition exceeds the image budget (8 MiB or 12 million pixels). Resize or split its artwork.')
                cache[image_id]=raw
        assets=lambda image_id:cache[image_id]
        out=io.BytesIO();sheet=letter if paper=='letter' else A4
        size=landscape(sheet) if mode=='booklet' else sheet
        c=canvas.Canvas(out,pagesize=size,pageCompression=1,invariant=1)
        c.setTitle(title[:160]);c.setAuthor('Neonrest');c.setSubject('Booklet: landscape, actual size, duplex flip on short edge. Do not select booklet mode again.' if mode=='booklet' else 'Standard reading-order edition.')
        labels={p['id']:i+1 for i,p in enumerate(reading)}
        if mode=='standard':
            for page in reading:
                draw_page(c,page,0,size[0],size[1],assets,numbers,labels[page['id']]);c.showPage()
        else:
            for outside_left,outside_right,inside_left,inside_right in impose(reading):
                for left,right in [(outside_left,outside_right),(inside_left,inside_right)]:
                    for p,x in [(left,0),(right,size[0]/2)]:draw_page(c,p,x,size[0]/2,size[1],assets,numbers,labels.get(p['id'],0) if p else 0)
                    c.showPage()
        c.save()
        if out.tell()>32*1024*1024:raise ZineError('This print edition exceeds the 32 MiB output limit.')
        return out.getvalue()
    finally:LOCK.release()
