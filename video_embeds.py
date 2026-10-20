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

def install(app):
    app.jinja_env.globals['youtube_links'] = youtube_links
