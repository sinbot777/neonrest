"""Anchored image layout for bounded composition text frames.

Source is plain text plus image anchors. No user HTML, URLs or executable styles.
The print compositor lays text into the remaining line width beside floats.
"""
import re

def normalize(raw, text_length):
    from .zines_composition import fail,number
    from .zines_core import text
    if not isinstance(raw,list) or len(raw)>6:fail('Use at most six images inside one text frame.')
    out=[]
    for image in raw:
        if not isinstance(image,dict) or set(image)-{'at','image','alt','mode','width','height','gap','caption','credit'}:fail('Unsupported anchored image.')
        at=image.get('at')
        if type(at) is not int or not 0<=at<=text_length:fail('Place the image within its text.')
        aid=image.get('image','');mode=image.get('mode','inline')
        if not isinstance(aid,str) or len(aid)>60:fail('Invalid anchored artwork.')
        if mode not in ('inline','wrap-left','wrap-right','full'):fail('Choose inline, wrapped or full-width placement.')
        out.append(dict(at=at,image=aid,mode=mode,alt=text(image.get('alt',''),300),caption=text(image.get('caption',''),200),credit=text(image.get('credit',''),160),width=number(image.get('width',35),5,100,'anchored image width'),height=number(image.get('height',72),6,180,'anchored image height'),gap=number(image.get('gap',6),0,24,'image spacing')))
    return sorted(out,key=lambda image:image['at'])

def segments(block):
    text=block['text'];previous=0
    for image in block.get('insets',[]):
        yield text[previous:image['at']]
        yield image
        previous=image['at']
    yield text[previous:]

def layout(block):
    """Return print marks in top-left coordinates and total occupied height."""
    from reportlab.pdfbase import pdfmetrics
    from .zines_composition import FONTS,fail
    font=FONTS[block['font']];size=block['size'];leading=size*block['leading'];width=block['w']-8
    caption_size=max(6,min(10,size*.75));caption_leading=caption_size*1.25
    def measure(s,sz=size):return pdfmetrics.stringWidth(s,font,sz)
    def caption_lines(s,w):
        lines=[];line=''
        for word in re.findall(r'\n|[^\s]+[^\S\n]*',s):
            if word=='\n':
                if line:lines.append(line.rstrip());line=''
                continue
            for ch in word:
                if line and measure(line+ch,caption_size)>w:lines.append(line.rstrip());line=''
                line+=ch
        if line:lines.append(line.rstrip())
        return lines
    marks=[];floats=[];y=0;line=[];used=0;line_height=leading
    def bounds():
        active=[f for f in floats if f['bottom']>y+.01]
        left=max([f['edge'] for f in active if f['side']=='left'] or [0])
        right=min([f['edge'] for f in active if f['side']=='right'] or [width])
        return left,right
    def finish(force=False):
        nonlocal y,line,used,line_height
        if not line and not force:return
        left,right=bounds();shift=max(0,right-left-used)*{'left':0,'center':.5,'right':1}[block['align']]
        for mark in line:
            mark['x']+=left+shift;mark['y']+=y+(line_height-leading if mark.get('body') else max(0,line_height-mark['inline_height']) if 'inline_height' in mark else 0)
            marks.append(mark)
        y+=line_height;line=[];used=0;line_height=leading
    def room(w):
        nonlocal y
        left,right=bounds()
        if used+w<=right-left+.01:return
        finish();left,right=bounds()
        while w>right-left+.01 and any(f['bottom']>y+.01 for f in floats):
            y=min(f['bottom'] for f in floats if f['bottom']>y+.01);left,right=bounds()
    def figure(image):
        gap=image['gap'];iw=max(1,(width-2*gap)*(1 if image['mode']=='full' else image['width']/100));ih=image['height']
        captions=caption_lines('\n'.join(x for x in (image['caption'],image['credit']) if x),iw)
        return iw,ih,captions,ih+(caption_leading*len(captions)+3 if captions else 0)
    def image_marks(image,x,top,iw,ih,captions):
        result=[dict(type='image',image=image['image'],x=x,y=top,w=iw,h=ih)]
        for i,text in enumerate(captions):result.append(dict(type='text',text=text,x=x,y=top+ih+3+i*caption_leading,size=caption_size))
        return result
    for part in segments(block):
        if isinstance(part,str):
            for token in re.findall(r'\n|[^\S\n]+|[^\s]+',part):
                if token=='\n':finish(True);continue
                if token.isspace() and not line:continue
                tw=measure(token);room(tw);left,right=bounds()
                # Break long words; keep every character rather than clipping it.
                pieces=[token]
                if tw>right-left+.01:
                    pieces=[];piece=''
                    for ch in token:
                        if piece and measure(piece+ch)>max(1,right-left):pieces.append(piece);piece=''
                        piece+=ch
                    if piece:pieces.append(piece)
                for piece in pieces:
                    pw=measure(piece);room(pw)
                    if piece.isspace() and not line:continue
                    if line and line[-1].get('body'):line[-1]['text']+=piece
                    else:line.append(dict(type='text',text=piece,x=used,y=0,size=size,body=True))
                    used+=pw
        else:
            iw,ih,captions,fh=figure(part);gap=part['gap'];occupied=iw+2*gap
            if part['mode'] in ('wrap-left','wrap-right'):
                finish();left,right=bounds()
                while occupied>right-left and any(f['bottom']>y+.01 for f in floats):y=min(f['bottom'] for f in floats if f['bottom']>y+.01);left,right=bounds()
                side='left' if part['mode']=='wrap-left' else 'right';x=left+gap if side=='left' else right-iw-gap
                marks.extend(image_marks(part,x,y+gap,iw,ih,captions));floats.append(dict(side=side,edge=x+iw+gap if side=='left' else x-gap,bottom=y+fh+2*gap))
            elif part['mode']=='full':
                finish();y=max([y]+[f['bottom'] for f in floats]);floats=[];marks.extend(image_marks(part,gap,y+gap,iw,ih,captions));y+=fh+2*gap
            else:
                room(occupied);height=fh+2*gap;fig=image_marks(part,used+gap,gap,iw,ih,captions)
                for mark in fig:mark['inline_height']=height
                line.extend(fig);used+=occupied;line_height=max(line_height,height)
    finish();height=max([y]+[f['bottom'] for f in floats])
    if height>block['h']-8+.01:fail('Text and anchored artwork overflow in print. Enlarge the text frame, reduce image/type size, or split the article.')
    return marks

def draw(c,block,assets):
    import io
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.colors import HexColor
    from .zines_composition import FONTS,fail
    font=FONTS[block['font']];c.setFillColor(HexColor(block['color']))
    for mark in layout(block):
        x,y=4+mark['x'],block['h']-4-mark['y']
        if mark['type']=='text':
            if any(ord(ch) not in pdfmetrics.getFont(font).face.charToGlyph for ch in mark['text'] if ch not in '\n\r\t'):fail('Anchored text contains a character unavailable in the print font.')
            c.setFont(font,mark['size']);c.drawString(x,y-mark['size'],mark['text'])
        elif mark['image']:
            image=ImageReader(io.BytesIO(assets(mark['image'])));iw,ih=image.getSize();ratio=min(mark['w']/iw,mark['h']/ih);w,h=iw*ratio,ih*ratio
            c.drawImage(image,x+(mark['w']-w)/2,y-mark['h']+(mark['h']-h)/2,w,h,mask='auto')
