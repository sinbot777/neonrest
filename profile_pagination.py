"""Signed, profile-scoped keyset pagination; no history count or OFFSET."""
from flask import current_app, request, abort
from itsdangerous import URLSafeSerializer, BadData

PAGE_SIZE = 20

def serializer():
    return URLSafeSerializer(current_app.secret_key, salt='profile-post-pages-v1')

def selection(user_id):
    token = request.args.get('posts_cursor')
    if not token:
        return '', (), False
    if len(token) > 1024:
        abort(400)
    try:
        owner, created, post_id, direction = serializer().loads(token)
        if owner != user_id or not isinstance(created, str) or len(created) > 64 or type(post_id) is not int or post_id < 1 or direction not in ('older', 'newer'):
            raise ValueError()
    except (BadData, ValueError, TypeError):
        abort(400)
    op = '<' if direction == 'older' else '>'
    return f" AND (posts.created_at {op} ? OR (posts.created_at = ? AND posts.id {op} ?))", (created, created, post_id), direction == 'newer'

def finish(rows, user_id, reverse):
    more = len(rows) > PAGE_SIZE
    rows = list(rows[:PAGE_SIZE])
    if reverse:
        rows.reverse()
    def cursor(row, direction):
        return serializer().dumps([user_id, row['created_at'], row['id'], direction])
    older = newer = None
    if rows:
        if more or reverse:
            older = cursor(rows[-1], 'older')
        if (more if reverse else bool(request.args.get('posts_cursor'))):
            newer = cursor(rows[0], 'newer')
    return rows, older, newer
