"""Temporary WSGI guard for the Production app during a reviewed source rollback.

Install on the Production child app before resuming traffic. It does not revoke
existing grants, reconcile holds, stop workers, or authorize a database restore.
"""
class PrivacyRollbackGuard:
    blocked = ('/manage/privacy', '/manage/family/requests',
               '/account/family/requests', '/privacy/submit', '/signup')

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if any(path == prefix or path.startswith(prefix + '/') for prefix in self.blocked):
            body = (b'<!doctype html><html lang="en"><meta charset="utf-8">'
                    b'<title>Temporarily unavailable</title><h1>Temporarily unavailable</h1>'
                    b'<p>Privacy request tools and signup are temporarily paused. '
                    b'Please try again later or use the published support contact.</p></html>')
            start_response('503 Service Unavailable', [
                ('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(body))),
                ('Cache-Control', 'private, no-store'), ('Retry-After', '3600'),
                ('Referrer-Policy', 'same-origin'), ('X-Content-Type-Options', 'nosniff'),
                ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
                ('X-Robots-Tag', 'noindex, nofollow')])
            return [body]
        return self.app(environ, start_response)
