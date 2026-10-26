"""Conservative ownership hints from explicit references, never filenames alone."""
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit


def references(db, environment, namespaces):
    """Return namespace/relative-file -> set of accountable personal owners.

    Caller keeps a read transaction and serializes uploads during the physical
    scan. Old Circle/Vibe artwork is unattributed when its original uploader is
    unknown; a current owner/editor is not evidence of who uploaded old bytes.
    """
    if environment not in ('production','sandbox'):
        raise ValueError('Explicit environment required.')
    result = {}
    def add(category, name, uid):
        if category not in namespaces or not isinstance(name,str) or not name or type(uid) is not int or uid <= 0:return
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or len(name)>300:return
        if category=='media' and len(path.parts)!=1:return
        key=namespaces[category]+'/'+path.as_posix()
        result.setdefault(key,set()).add(environment+':user:'+str(uid))
    for uid, url in db.execute('SELECT id,avatar_path FROM users WHERE avatar_path IS NOT NULL'):
        try:parsed=urlsplit(url)
        except ValueError:continue
        prefix=('/sandbox' if environment=='sandbox' else '')+'/static/uploads/'
        if not parsed.scheme and not parsed.netloc and parsed.path.startswith(prefix):
            add('uploads',parsed.path[len(prefix):],uid)
    for uid,filename,poster,loop in db.execute('SELECT p.user_id,m.filename,m.poster,m.loop_filename FROM post_media m JOIN posts p ON p.id=m.post_id'):
        for name in (filename,poster,loop):add('media',name,uid)
    for uid,name in db.execute('SELECT user_id,profile_midi FROM media_settings WHERE profile_midi IS NOT NULL'):
        add('media',name,uid)
    for uid,content in db.execute('SELECT user_id,content FROM posts'):
        prefix=('/sandbox' if environment=='sandbox' else '')+'/static/uploads/'
        for name in re.findall(r'(?:^|[\s("\']|\[image:)'+re.escape(prefix)+r'([^\s\]\)"<>?#]+)',content or ''):
            add('uploads',name,uid)
    return result
