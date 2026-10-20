"""Local URL recognition only; never fetch user-supplied URLs."""
import re
from urllib.parse import urlsplit, parse_qs
ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
URL = re.compile(r"https?://[^\s<>\"']+", re.I)
HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}
def timestamp(value):
    if value.isdigit():
        return min(int(value[:8]), 86400)
    match = re.fullmatch(r'(?:(\d{1,3})h)?(?:(\d{1,3})m)?(?:(\d{1,3})s)?', value)
    return min(sum(int(n or 0)*scale for n, scale in zip(match.groups(), (3600,60,1))),86400) if match else 0

def youtube_links(content):
    # Code examples remain code, not players. At most three distinct videos/post.
    tick = chr(96)
    content = re.sub(tick*3+r'[\s\S]*?'+tick*3+'|'+tick+'[^'+tick+r'\n]*'+tick, '', str(content or ''))
    result = []
    seen = set()
    for match in URL.finditer(content):
        raw = match.group().rstrip(').,;!?]}')
        if len(raw) > 2048:
            continue
        try:
            url = urlsplit(raw)
            if url.hostname not in HOSTS or url.username or url.password or url.port not in (None,80,443):
                continue
            query = parse_qs(url.query, max_num_fields=40)
            parts = url.path.strip('/').split('/')
            if url.hostname in ('youtu.be','www.youtu.be') and len(parts)==1:
                video = parts[0]
            elif url.path=='/watch':
                video = query.get('v',[''])[0]
            elif len(parts)==2 and parts[0] in ('shorts','embed','live'):
                video = parts[1]
            else:
                continue
            if not ID.fullmatch(video) or video in seen:
                continue
            start = timestamp(query.get('start',query.get('t',['0']))[0])
            result.append({'id':video, 'start':start, 'url':'https://www.youtube.com/watch?v='+video+('&t='+str(start)+'s' if start else '')})
            seen.add(video)
            if len(result)==3:
                break
        except (ValueError, UnicodeError):
            continue
    return result

def video_links(content):
    """Canonical, allowlisted provider URLs. No redirects or metadata requests."""
    tick = chr(96)
    content = re.sub(tick*3+r'[\s\S]*?'+tick*3+'|'+tick+'[^'+tick+r'\n]*'+tick, '', str(content or ''))
    result, seen = [], set()
    for match in URL.finditer(content):
        raw = match.group().rstrip(').,;!?]}')
        if len(raw) > 2048:
            continue
        try:
            u = urlsplit(raw)
            if u.username or u.password or u.port not in (None,80,443):
                continue
            found = youtube_links(raw)
            if found:
                video = dict(found[0], provider='youtube', label='YouTube', portrait=False)
            elif u.hostname in ('instagram.com','www.instagram.com','m.instagram.com'):
                parts=u.path.strip('/').split('/')
                if len(parts)!=2 or parts[0] not in ('p','reel','reels','tv') or not re.fullmatch(r'[A-Za-z0-9_-]{5,64}',parts[1]):
                    continue
                kind='reel' if parts[0]=='reels' else parts[0]
                canonical='https://www.instagram.com/'+kind+'/'+parts[1]+'/'
                video={'provider':'instagram','label':'Instagram','id':parts[1],'url':canonical,'start':0,'portrait':True}
            elif u.hostname in ('facebook.com','www.facebook.com','m.facebook.com','web.facebook.com','fb.watch','www.fb.watch'):
                parts=u.path.strip('/').split('/')
                query=parse_qs(u.query,max_num_fields=40)
                portrait=False
                if u.hostname in ('fb.watch','www.fb.watch') and len(parts)==1 and re.fullmatch(r'[A-Za-z0-9_-]{3,128}',parts[0]):
                    key='short:'+parts[0];canonical='https://fb.watch/'+parts[0]+'/'
                elif u.path.rstrip('/')=='/watch' and re.fullmatch(r'[0-9]{3,30}',query.get('v',[''])[0]):
                    key=query['v'][0];canonical='https://www.facebook.com/watch/?v='+key
                elif len(parts)>=2 and parts[-2] in ('videos','reel') and re.fullmatch(r'[0-9]{3,30}',parts[-1]) and len(parts)<=4 and all(re.fullmatch(r'[A-Za-z0-9._-]+',x) for x in parts):
                    key=parts[-1];portrait=parts[-2]=='reel';canonical='https://www.facebook.com/'+('reel/'+key+'/' if portrait else 'watch/?v='+key)
                elif len(parts)==3 and parts[:2] in (['share','v'],['share','r']) and re.fullmatch(r'[A-Za-z0-9_-]{3,128}',parts[2]):
                    key='share:'+parts[2];portrait=parts[1]=='r';canonical='https://www.facebook.com/share/'+parts[1]+'/'+parts[2]+'/'
                else:
                    continue
                video={'provider':'facebook','label':'Facebook','id':key,'url':canonical,'start':0,'portrait':portrait}
            else:
                continue
            key=(video['provider'],video['id'])
            if key in seen:
                continue
            seen.add(key);result.append(video)
            if len(result)==3:
                break
        except (ValueError,UnicodeError):
            continue
    return result

def install(app):
    app.jinja_env.globals['youtube_links'] = youtube_links
    app.jinja_env.globals['video_links'] = video_links
