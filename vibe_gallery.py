"""Gallery items drawn only from the Vibe's already-visible post page."""
import re

LINKED_IMAGE = re.compile(r'!\[([^\]]*)\]\((https?://[^\s)]+|/(?:sandbox/)?static/[^\s)]+)\)')


def build_vibe_gallery(db, posts, media_url, static_url, limit=8):
    if not posts or limit <= 0:
        return []
    ids = [post['id'] for post in posts]
    rows = db.execute(
        "SELECT post_id,kind,filename,poster,alt_text,title FROM post_media "
        "WHERE post_id IN (" + ','.join('?' for _ in ids) + ") AND kind IN ('image','gif')",
        ids,
    ).fetchall()
    attachments = {row['post_id']: row for row in rows}
    items, seen = [], set()

    def add(post, alt, url):
        key = (post['id'], url)
        if url and key not in seen and len(items) < limit:
            seen.add(key)
            items.append({'id': post['id'], 'handle': post['handle'], 'alt': alt, 'url': url})

    for post in posts:
        media = attachments.get(post['id'])
        if media:
            filename = media['poster'] if media['kind'] == 'gif' else media['filename']
            if filename:
                add(post, media['alt_text'] or media['title'], media_url(filename))
        for alt, url in LINKED_IMAGE.findall(post['content'] or ''):
            if url.startswith('/static/'):
                url = static_url(url[len('/static/'):])
            add(post, alt, url)
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
    return items
