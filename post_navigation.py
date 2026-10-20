"""Rebuild return destinations from recognized GET routes, never raw redirects."""
from urllib.parse import urlsplit, unquote, parse_qsl, urlencode
from flask import current_app, request, url_for
from werkzeug.exceptions import HTTPException

DESTINATIONS = {'user_by_handle','user_page_test','feed','vibe_page','circle_page'}
PARAMS = {'mode','posts_cursor','page','before'}

def after_delete():
    fallback = url_for('feed')
    value = request.form.get('return_to','')
    # Older, already-open forms have no return field. Validate their same-origin
    # Referer through the exact same route allowlist and URL reconstruction.
    if not value and request.referrer:
        try:
            ref = urlsplit(request.referrer)
            origin = urlsplit(request.host_url)
            if (ref.scheme,ref.netloc)==(origin.scheme,origin.netloc):
                value = ref.path + ('?'+ref.query if ref.query else '')
        except ValueError:
            return fallback
    if not value or len(value)>4096 or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 or ord(c)==127 for c in value):
        return fallback
    try:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            return fallback
        path = unquote(parsed.path)
        mount = request.script_root
        if mount:
            if not path.startswith(mount+'/'):
                return fallback
            path=path[len(mount):]
        endpoint, values = current_app.url_map.bind('localhost').match(path,method='GET')
        if endpoint not in DESTINATIONS:
            return fallback
        query = [(k,v) for k,v in parse_qsl(parsed.query,max_num_fields=20) if k in PARAMS]
        result = url_for(endpoint,**values)
        if query:
            result += '?' + urlencode(query)
        if endpoint in ('user_by_handle','user_page_test'):
            result += '#recent-posts'
        return result
    except (ValueError,UnicodeError,HTTPException):
        return fallback
