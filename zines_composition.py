"""Bounded, portable page composition. No executable HTML, CSS or external URLs."""
import json
import math
import re

WIDTH, HEIGHT = 396, 612
FONTS = {'sans': 'ZineText', 'bold': 'ZineHeavy', 'mono': 'ZineMono'}

def fail(message):
    from .zines_core import ZineError
    raise ZineError(message)

def color(value, transparent=False):
    if transparent and value == 'transparent': return value
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        fail('Composition colors must use six-digit hex colors.')
    return value.lower()

def number(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        fail('Composition '+label+' is outside its allowed range.')
    return round(value, 2)

def normalize(value):
    if isinstance(value, str):
        if len(value) > 40000: fail('The composition is too large.')
        try: value = json.loads(value)
        except (ValueError, TypeError): fail('Composition JSON is invalid. Copy your layout before reloading.')
    if not isinstance(value, dict) or set(value)-{'version','background','blocks'} or value.get('version') != 1:
        fail('Choose a supported composition version.')
    blocks = value.get('blocks')
    if not isinstance(blocks, list) or len(blocks) > 32: fail('Use at most 32 elements on a page.')
    out = {'version': 1, 'background': color(value.get('background','#ffffff')), 'blocks': []}
    ids = set(); total = 0
    from .zines_core import text
    for raw in blocks:
        keys = {'id','type','x','y','w','h','text','image','alt','font','size','leading','align','color','fill','stroke','stroke_width','fit','locked','rotation','opacity','group','name','focal_x','focal_y','insets'}
        if not isinstance(raw, dict) or set(raw)-keys: fail('Unsupported composition element.')
        ident = raw.get('id'); kind = raw.get('type')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',ident) or ident in ids: fail('Every composition element needs a unique ID.')
        ids.add(ident)
        if kind not in ('text','image','box','ellipse','rule'): fail('Unsupported composition element type.')
        b = {'id':ident,'type':kind}
        for key,low,high in [('x',0,384),('y',0,600),('w',12,396),('h',12,612)]: b[key]=number(raw.get(key),low,high,key)
        if b['x']+b['w'] > WIDTH or b['y']+b['h'] > HEIGHT: fail('Keep each element inside the page.')
        if type(raw.get('locked',False)) is not bool: fail('Invalid element lock.')
        b['locked']=raw.get('locked',False)
        b['rotation']=number(raw.get('rotation',0),-180,180,'rotation')
        b['opacity']=number(raw.get('opacity',1),0.05,1,'opacity')
        group=raw.get('group','')
        if not isinstance(group,str) or (group and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',group)): fail('Invalid element group.')
        b['group']=group
        b['name']=text(raw.get('name',''),80)
        angle=math.radians(b['rotation']);rw=abs(b['w']*math.cos(angle))+abs(b['h']*math.sin(angle));rh=abs(b['w']*math.sin(angle))+abs(b['h']*math.cos(angle))
        cx=b['x']+b['w']/2;cy=b['y']+b['h']/2
        if min(cx-rw/2,cy-rh/2)<-0.02 or cx+rw/2>WIDTH+0.02 or cy+rh/2>HEIGHT+0.02: fail('Keep rotated elements inside the page.')
        b['fill']=color(raw.get('fill','transparent'),True)
        b['color']=color(raw.get('color','#171717'))
        b['stroke']=color(raw.get('stroke','#171717'))
        b['stroke_width']=number(raw.get('stroke_width',0),0,8,'border width')
        if kind=='text':
            b.update(text=text(raw.get('text',''),6000),font=raw.get('font','sans'),size=number(raw.get('size',12),6,72,'font size'),leading=number(raw.get('leading',1.35),1,2,'line spacing'),align=raw.get('align','left'))
            if b['font'] not in FONTS or b['align'] not in ('left','center','right'): fail('Unsupported text typography.')
            if 'insets' in raw:
                from .zines_flow import normalize as normalize_insets
                source=raw.get('text','')
                b['insets']=normalize_insets(raw['insets'],len(source))
                for inset in b['insets']:inset['at']=len(source[:inset['at']].replace('\r\n','\n').replace('\r','\n'))
                b['text']=source.replace('\r\n','\n').replace('\r','\n')
            total+=len(b['text'])+sum(len(i['caption'])+len(i['credit']) for i in b.get('insets',[]))
        elif kind=='image':
            image=raw.get('image','')
            if not isinstance(image,str) or len(image)>60: fail('Invalid composition artwork.')
            b.update(image=image,alt=text(raw.get('alt',''),300),fit=raw.get('fit','contain'),focal_x=number(raw.get('focal_x',50),0,100,'horizontal crop focus'),focal_y=number(raw.get('focal_y',50),0,100,'vertical crop focus'))
            if b['fit'] not in ('contain','cover'): fail('Unsupported image fit.')
        if kind!='text' and 'insets' in raw:fail('Only text frames can contain anchored images.')
        out['blocks'].append(b)
    if sum(len(b.get('insets',[])) for b in out['blocks'])>16:fail('Use at most sixteen anchored images per page.')
    if total>6000: fail('Use at most 6000 characters across composition text boxes.')
    return out

def asset_ids(data):
    found = [data['image']] if data.get('image') else []
    for block in data.get('composition',{}).get('blocks',[]):
        if block.get('type')=='image' and block.get('image'): found.append(block['image'])
        found.extend(i['image'] for i in block.get('insets',[]) if i.get('image'))
    return list(dict.fromkeys(found))

def draw(c, data, x, width, height, assets, numbers=False, number=0):
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from xml.sax.saxutils import escape
    import io
    page=normalize(data['composition'])
    scale=min(width/WIDTH,height/HEIGHT)
    c.saveState();c.translate(x+(width-WIDTH*scale)/2,(height-HEIGHT*scale)/2);c.scale(scale,scale)
    c.setFillColor(HexColor(page['background']));c.rect(0,0,WIDTH,HEIGHT,stroke=0,fill=1)
    for b in page['blocks']:
        bx,by,bw,bh=b['x'],HEIGHT-b['y']-b['h'],b['w'],b['h']
        c.saveState()
        c.setFillAlpha(b['opacity']);c.setStrokeAlpha(b['opacity'])
        c.translate(bx+bw/2,by+bh/2);c.rotate(-b['rotation']);c.translate(-bw/2,-bh/2);bx=by=0
        fill=b['fill']!='transparent'
        if fill:c.setFillColor(HexColor(b['fill']))
        c.setStrokeColor(HexColor(b['stroke']));c.setLineWidth(b['stroke_width'])
        if b['type']=='ellipse':c.ellipse(bx,by,bx+bw,by+bh,stroke=int(b['stroke_width']>0),fill=int(fill))
        elif b['type']=='rule':
            c.setStrokeColor(HexColor(b['color']));c.setLineWidth(max(1,b['stroke_width']));c.line(bx,by+bh/2,bx+bw,by+bh/2)
        else:
            if fill or b['stroke_width']:c.rect(bx,by,bw,bh,stroke=int(b['stroke_width']>0),fill=int(fill))
            if b['type']=='text' and b.get('insets'):
                from .zines_flow import draw as draw_flow
                draw_flow(c,b,assets)
            elif b['type']=='text':
                font=FONTS[b['font']];face=pdfmetrics.getFont(font).face
                if any(ord(ch) not in face.charToGlyph for ch in b['text'] if ch not in '\n\r\t'):fail('A composition text box contains a character unavailable in the print font.')
                p=Paragraph(escape(b['text']).replace('\n','<br/>'),ParagraphStyle('composition',fontName=font,fontSize=b['size'],leading=b['size']*b['leading'],textColor=HexColor(b['color']),alignment={'left':0,'center':1,'right':2}[b['align']],splitLongWords=True))
                _,needed=p.wrap(bw-8,20000)
                if needed>bh-8:fail('A composition text box overflows in print. Enlarge it, reduce its type size, or split the text.')
                p.drawOn(c,bx+4,by+bh-4-needed)
            elif b['type']=='image' and b['image']:
                image=ImageReader(io.BytesIO(assets(b['image'])));iw,ih=image.getSize()
                ratio=(max if b['fit']=='cover' else min)(bw/iw,bh/ih);dw,dh=iw*ratio,ih*ratio
                path=c.beginPath();path.rect(bx,by,bw,bh);c.clipPath(path,stroke=0)
                c.drawImage(image,bx+(bw-dw)*b['focal_x']/100,by+(bh-dh)*(1-b['focal_y']/100),dw,dh,mask='auto')
        c.restoreState()
    if numbers:
        c.setFont('ZineText',7);c.setFillColor(HexColor('#171717'));c.drawRightString(384,8,str(number))
    c.restoreState()
