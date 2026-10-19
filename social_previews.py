"""Server-rendered social metadata and revocable, public-only PNG previews."""
import hashlib
import html
import io
import re
import sqlite3
import warnings
from pathlib import Path
from flask import abort, make_response, request, session, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from . import public_ids
from .community_features import visible_post
from .media_features import media_folder

ORIGIN='https://www.neonrest.com'
WIDTH,HEIGHT=1200,630
GENERIC_TITLE='Neonrest'
GENERIC_DESCRIPTION='Personal spaces, shared interests, and real communities on Neonrest.'

def plain(value,limit=400):
    text=str(value or '')[:20000]
    text=re.sub(r'!\[([^\[\]]*)\]\([^()]*\)',r'\1',text)
    text=re.sub(r'\[([^\[\]]+)\]\([^()]*\)',r'\1',text)
    text=re.sub(r'<[^<>]*>','',text)
    text=re.sub(r'(?<!\w)[*_~`]{1,3}|[*_~`]{1,3}(?!\w)','',text)
    text=html.unescape(text)
    text=''.join(c for c in text if not (ord(c)<32 and not c.isspace()) and ord(c)!=127 and c not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')
    text=' '.join(text.split()).strip(' #*`_')
    return text[:limit].rstrip()+('…' if len(text)>limit else '')

def public_post(db,value,viewer=None):
    try:pid=public_ids.resolve(db,'post',value)
    except (ValueError,TypeError):return None
    # Guest visibility is mandatory; signed-in privileges cannot publish private previews.
    if not visible_post(db,pid,None):return None
    if viewer is not None and not visible_post(db,pid,viewer):return None
    if db.execute('SELECT 1 FROM protected_age_posts WHERE post_id=?',(pid,)).fetchone():return None
    post=db.execute('SELECT p.*,u.handle FROM posts p JOIN users u ON u.id=p.user_id WHERE p.id=?',(pid,)).fetchone()
    if not post:return None
    return dict(post)

def descriptor(db,value,viewer=None):
    post=public_post(db,value,viewer)
    if not post:return None
    pid=post['id'];token=public_ids.public(db,'post',pid)
    media=db.execute("SELECT filename,poster,kind,alt_text,title FROM post_media WHERE post_id=? AND kind IN ('image','gif') ORDER BY kind,filename LIMIT 1",(pid,)).fetchone()
    media=dict(media) if media else None
    # A repost may embed a private Circle source in Neonrest. Do not export that source.
    ref=db.execute('SELECT source_post_id FROM post_shares WHERE share_post_id=?',(pid,)).fetchone()
    source=public_post(db,ref[0],viewer) if ref else None
    if source and not str(post.get('content') or '').strip():
        post=source
        media=db.execute("SELECT filename,poster,kind,alt_text,title FROM post_media WHERE post_id=? AND kind IN ('image','gif') ORDER BY kind,filename LIMIT 1",(source['id'],)).fetchone()
        media=dict(media) if media else None
    if not media:
        legacy=re.search(r'!\[[^\]]*\]\(/(?:sandbox/)?static/uploads/posts/([0-9a-f]{32}\.jpg)\)',str(post['content'] or '')[:20000])
        if legacy:media={'legacy':legacy[1],'kind':'image'}
    author=plain('@'+post['handle'].lstrip('@'),80)
    excerpt=plain(post['content']) or ('Shared an image on Neonrest.' if media else 'Shared a post on Neonrest.')
    revision=hashlib.sha256(repr((token,post['id'],post['content'],post['last_edited'],post['handle'],media)).encode()).hexdigest()[:20]
    return {'token':token,'author':author,'description':excerpt,'title':'A post by '+author+' on Neonrest','media':media,'revision':revision,'source':post['id']}

def font(size,bold=False):
    path=Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
    return ImageFont.truetype(str(path),size) if path.is_file() else ImageFont.load_default(size=size)

def lines(draw,text,typeface,width,maximum):
    result=[];line=''
    for char in text:
        if draw.textlength(line+char,font=typeface)>width:
            result.append(line.rstrip());line=char.lstrip()
            if len(result)==maximum:
                result[-1]=result[-1].rstrip(' .')+'…';return result
        else:line+=char
    if line:result.append(line.rstrip())
    return result[:maximum]

def image_attachment(media):
    if not media:return None
    if media.get('legacy'):
        from flask import current_app
        name=media['legacy']
        if not re.fullmatch(r'[0-9a-f]{32}\.jpg',name):return None
        folder=(Path(current_app.static_folder)/'uploads/posts').resolve()
    else:
        folder=media_folder().resolve()
        name=media.get('poster') if media.get('kind')=='gif' else media.get('filename')
        if not isinstance(name,str) or not re.fullmatch(r'[0-9a-f]{40}\.(?:jpg|png|webp|gif)',name):return None
    path=(folder/name).resolve()
    if path.parent!=folder:return None
    try:
        if path.stat().st_size>10*1024*1024:return None
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format not in ('JPEG','PNG','WEBP','GIF'):return None
                if source.width*source.height>40000000:return None
                source.seek(0);source=ImageOps.exif_transpose(source)
                source.thumbnail((1080,410))
                result=Image.new('RGB',source.size,'#18283a')
                if source.mode in ('RGBA','LA') or 'transparency' in source.info:
                    rgba=source.convert('RGBA');result.paste(rgba,mask=rgba.getchannel('A'))
                else:result.paste(source.convert('RGB'))
                return result
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombWarning,Image.DecompressionBombError):return None

def card(data=None):
    canvas=Image.new('RGB',(WIDTH,HEIGHT),'#101b2b');draw=ImageDraw.Draw(canvas)
    draw.rectangle((0,0,WIDTH,12),fill='#86dcd1');draw.rectangle((0,618,WIDTH,HEIGHT),fill='#aa91de')
    draw.text((60,40),'NEONREST',font=font(38,True),fill='#9be5db')
    photo=image_attachment(data['media']) if data else None
    if photo:
        canvas.paste(photo,((WIDTH-photo.width)//2,110+(410-photo.height)//2))
        draw.text((60,550),data['author'],font=font(28,True),fill='#f6f5ff')
    else:
        draw.text((60,130),data['author'] if data else 'A place to make the web yours again',font=font(30,True),fill='#c6aff2')
        text=data['description'] if data else GENERIC_DESCRIPTION
        for i,line in enumerate(lines(draw,text,font(38),1080,6)):draw.text((60,205+i*55),line,font=font(38),fill='#f5f7fb')
    draw.text((60,582),'www.neonrest.com',font=font(20),fill='#b7c9da')
    output=io.BytesIO();canvas.save(output,format='PNG',optimize=True);return output.getvalue()

def register(app,core):
    @app.context_processor
    def social_context():
        data=None
        if request.endpoint=='post_detail':
            try:data=descriptor(core.get_db(),(request.view_args or {}).get('post_id'),session.get('user_id'))
            except (sqlite3.Error,ValueError,TypeError):pass
        if data:
            picture=ORIGIN+url_for('social_post_image',post_id=data['token'],revision=data['revision'])
            return {'social_preview':{'title':data['title'],'description':data['description'],'type':'article','url':ORIGIN+url_for('post_detail',post_id=data['token']),'image':picture,'alt':plain((data['media'] or {}).get('alt_text') or (data['media'] or {}).get('title') or data['description'],300)}}
        return {'social_preview':{'title':GENERIC_TITLE,'description':GENERIC_DESCRIPTION,'type':'website','url':ORIGIN+(request.script_root or '')+'/','image':ORIGIN+url_for('social_default_image'),'alt':'Neonrest — personal spaces and real communities'}}
    def png(raw):
        response=make_response(raw);response.mimetype='image/png'
        response.headers.update({'Cache-Control':'private, no-store, max-age=0','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex'})
        return response
    @app.get('/social-preview/default.png')
    def social_default_image():return png(card())
    @app.get('/social-preview/posts/<post_id>/<revision>.png')
    def social_post_image(post_id,revision):
        if not public_ids.TOKEN.fullmatch(post_id) or not re.fullmatch(r'[0-9a-f]{20}',revision):abort(404)
        data=descriptor(core.get_db(),post_id,session.get('user_id'))
        if not data or data['revision']!=revision:abort(404)
        return png(card(data))
