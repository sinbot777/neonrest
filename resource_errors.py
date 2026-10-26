"""Recoverable resource failures without database-backed error rendering."""
import errno
import sqlite3
from flask import g, jsonify, make_response, request
from markupsafe import escape
from werkzeug.exceptions import HTTPException

STORAGE_ERRNOS = {errno.ENOSPC, getattr(errno, 'EDQUOT', errno.ENOSPC)}
JSON_ENDPOINTS = {'create_comment', 'edit_comment', 'react_to_post'}


def failure_kind(error):
    if isinstance(error, OSError) and error.errno in STORAGE_ERRNOS:
        return 'storage_full'
    if isinstance(error, sqlite3.Error):
        code = getattr(error, 'sqlite_errorcode', None)
        if isinstance(code, int):
            primary = code & 255
            if primary in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return 'database_busy'
            if primary == sqlite3.SQLITE_FULL:
                return 'storage_full'
            return None
        # Compatibility for drivers without numeric codes; never match arbitrary text.
        message = str(error).lower()
        if message in ('database is locked', 'database table is locked', 'database schema is locked'):
            return 'database_busy'
        if message == 'database or disk is full':
            return 'storage_full'
    return None


def raise_if_storage_full(error):
    if failure_kind(error) == 'storage_full':
        raise error


def discard_files(*paths):
    """Best-effort removal of files allocated by the failed upload only."""
    for path in paths:
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original failure even if cleanup cannot write metadata.


def response_for(kind):
    busy = kind in ('database_busy', 'upload_busy')
    limited = kind == 'attachment_limit'
    draft = ''
    if request.method == 'POST' and request.endpoint in {'create_post','edit_post'} and 0 < (request.content_length or 0) <= 26*1024*1024:
        try:
            draft = request.form.get('content','')[:20000]
        except (HTTPException,OSError,ValueError):
            pass
    title = 'Neonrest is busy' if busy else 'Neonrest needs more storage'
    message = ('The database is temporarily busy. Wait a few seconds, check whether your change appeared, then try again if needed.'
               if busy else 'Neonrest cannot complete this request because server storage is full. Keep a copy of your text and try again later.')
    if kind == 'upload_busy':
        message = 'Another upload is finishing or storage accounting is temporarily unavailable. Keep your text and try again shortly.'
    if limited:
        title = 'Upload allowance reached'
        message = 'This request exceeds a size or attachment allowance. Keep your text and choose a smaller attachment or try again later.'
    status = 413 if limited else 503 if busy else 507
    wants_json = (request.endpoint in JSON_ENDPOINTS or request.is_json
                  or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                  or request.accept_mimetypes.best == 'application/json')
    if wants_json:
        response = jsonify(error=kind, message=message, **({'draft_text':draft} if draft else {}))
        response.status_code = status
    else:
        home = escape((request.script_root or '') + '/')
        recovered = ('<label for="unsaved-content">Your unsaved post text</label><textarea id="unsaved-content" readonly rows="8" style="box-sizing:border-box;width:100%;font:inherit;padding:.75rem">'+str(escape(draft))+'</textarea>') if draft else ''
        html = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>' + title + ' · Neonrest</title>'
                '<style>body{background:#20232c;color:#f2f0f5;font:1rem/1.6 system-ui;padding:2rem}'
                'main{max-width:40rem;margin:3rem auto;padding:2rem;border:1px solid #ad8fae;border-radius:16px}'
                'a,button{color:#ffcfba}button{font:inherit;background:transparent;border:1px solid currentColor;'
                'border-radius:999px;padding:.5rem 1rem;min-height:44px;cursor:pointer;margin-right:1rem}'
                'a:focus-visible,button:focus-visible{outline:3px solid #a3e9ff;outline-offset:4px}</style>'
                '<main><h1>' + title + '</h1><p>' + message + '</p>'
                '<p>Keep a copy of anything you entered before leaving this page.</p>' + recovered +
                '<button type="button" onclick="history.back()">Go back</button>'
                '<a href="' + str(home) + '">Return to Neonrest</a></main></html>')
        response = make_response(html, status)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if busy:
        response.headers['Retry-After'] = '3'
    return response


def install(app):
    def handle(error):
        kind = failure_kind(error)
        if kind is None:
            raise error  # Keep existing diagnostics for unrelated errors.
        connection = g.get('db')
        if connection is not None:
            try:
                connection.rollback()
            except (sqlite3.Error, OSError):
                pass
        # No template/context processor, flash, database event, or file log here:
        # those operations may require the resource that just failed.
        return response_for(kind)
    app.register_error_handler(sqlite3.Error, handle)
    app.register_error_handler(OSError, handle)
