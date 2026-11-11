"""Explicit test-only WSGI webhook boundary; not registered with either app.

Stripe uses the existing durable receipt/reconciliation service. Verified PayPal
events are durably quarantined for canonical reconciliation, never marked paid.
No raw payload, signature, token, or customer details are stored or returned.
"""
import hashlib
import json
import re
import sqlite3
import time

if __package__:
    from . import marketplace_inventory as inventory, marketplace_payments as payments
    from .marketplace_provider_api import PayPalSandboxAPI
else:
    import marketplace_inventory as inventory, marketplace_payments as payments
    from marketplace_provider_api import PayPalSandboxAPI

MAX_BODY = 1_048_576
PAYPAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS marketplace_paypal_test_inbox (
 id INTEGER PRIMARY KEY,
 environment TEXT NOT NULL CHECK(environment='test'),
 platform_ref TEXT NOT NULL,
 event_ref TEXT NOT NULL,
 event_type TEXT NOT NULL,
 resource_ref TEXT NOT NULL,
 body_hash TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 received_at INTEGER NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome='needs_review'),
 reason TEXT NOT NULL CHECK(reason='canonical_paypal_processing_pending'),
 UNIQUE(environment,platform_ref,event_ref)
);
CREATE TRIGGER IF NOT EXISTS marketplace_paypal_test_inbox_update
BEFORE UPDATE ON marketplace_paypal_test_inbox
BEGIN SELECT RAISE(ABORT,'verified receipt is retained'); END;
CREATE TRIGGER IF NOT EXISTS marketplace_paypal_test_inbox_delete
BEFORE DELETE ON marketplace_paypal_test_inbox
BEGIN SELECT RAISE(ABORT,'verified receipt is retained'); END;
"""


def initialize_paypal_inbox(db):
    """Explicit isolated-database migration, never called by HTTP requests."""
    if db.in_transaction:
        raise payments.PaymentError('dedicated migration connection required')
    db.executescript(PAYPAL_SCHEMA)


def receive_paypal(db, adapter, platform, raw, headers, now):
    if not isinstance(adapter, PayPalSandboxAPI):
        raise payments.PaymentError('configured sandbox verifier required')
    payments.ref(platform)
    inventory.clock(now)
    verified = adapter.verify_webhook(raw, headers)
    event = json.loads(raw, object_pairs_hook=payments._json_pairs,
                      parse_constant=payments._invalid_constant)
    event_ref = payments.ref(event.get('id'))
    if verified != dict(event_ref=event_ref, environment='test', provider='paypal'):
        raise payments.PaymentError('verified event mismatch')
    kind = event.get('event_type')
    if not isinstance(kind, str) or not re.fullmatch(r'[A-Z][A-Z0-9_.-]{1,159}', kind):
        raise payments.PaymentError('invalid event type')
    resource = event.get('resource')
    if not isinstance(resource, dict):
        raise payments.PaymentError('invalid event resource')
    resource_ref = payments.ref(resource.get('id'))
    fingerprint = hashlib.sha256(json.dumps([event_ref, kind, resource_ref],
                                            separators=(',', ':')).encode()).hexdigest()
    with inventory.transaction(db):
        old = db.execute('SELECT id,fingerprint FROM marketplace_paypal_test_inbox '
                         "WHERE environment='test' AND platform_ref=? AND event_ref=?",
                         (platform, event_ref)).fetchone()
        if old and old[1] != fingerprint:
            raise payments.PaymentError('event identity conflict')
        if not old:
            db.execute('INSERT INTO marketplace_paypal_test_inbox '
                       '(environment,platform_ref,event_ref,event_type,resource_ref,'
                       'body_hash,fingerprint,received_at,outcome,reason) '
                       "VALUES ('test',?,?,?,?,?,?,?,'needs_review',"
                       "'canonical_paypal_processing_pending')",
                       (platform, event_ref, kind, resource_ref,
                        hashlib.sha256(raw).hexdigest(), fingerprint, now))
    return dict(outcome='needs_review', reason='canonical_paypal_processing_pending')


class SandboxWebhookApplication:
    """Mount only under a trusted Sandbox path after explicit configuration.

    db_factory returns a new, initialized dedicated connection per request.
    This boundary never imports app startup, opens a default database, migrates
    schemas, creates provider resources, or enables settlement/fulfillment.
    PayPal's platform_ref is an opaque local alias, never the client credential.
    """
    def __init__(self, environment, db_factory, stripe=None, paypal=None,
                 paypal_platform=None, clock=None, policy=payments.checkout.NeonrestPolicy):
        if environment != 'test' or not callable(db_factory):
            raise payments.PaymentError('explicit test database factory required')
        if stripe is not None and not isinstance(stripe, payments.StripeTestWebhookAdapter):
            raise payments.PaymentError('configured Stripe test verifier required')
        if paypal is not None:
            if not isinstance(paypal, PayPalSandboxAPI) or not paypal._webhook:
                raise payments.PaymentError('registered PayPal sandbox verifier required')
            payments.ref(paypal_platform)
        self.db_factory = db_factory
        self.stripe, self.paypal = stripe, paypal
        self.paypal_platform = paypal_platform
        self.clock = clock or (lambda: int(time.time()))
        self.policy = policy

    @staticmethod
    def _reply(start_response, status, code):
        body = json.dumps(dict(status=code), separators=(',', ':')).encode()
        headers = [('Content-Type', 'application/json'),
                   ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')]
        if status.startswith('405'):
            headers.append(('Allow', 'POST'))
        if status.startswith('503'):
            headers.append(('Retry-After', '30'))
        start_response(status, headers)
        return [body]

    def __call__(self, environ, start_response):
        reply = lambda status, code: self._reply(start_response, status, code)
        route = environ.get('PATH_INFO')
        if route not in ('/stripe', '/paypal'):
            return reply('404 Not Found', 'not_found')
        if environ.get('REQUEST_METHOD') != 'POST':
            return reply('405 Method Not Allowed', 'method_not_allowed')
        adapter = self.stripe if route == '/stripe' else self.paypal
        if adapter is None:
            return reply('503 Service Unavailable', 'provider_unavailable')
        length = environ.get('CONTENT_LENGTH', '')
        if not isinstance(length, str) or not re.fullmatch(r'[0-9]{1,10}', length):
            return reply('411 Length Required', 'length_required')
        length = int(length)
        if length > MAX_BODY:
            return reply('413 Content Too Large', 'payload_too_large')
        if length == 0:
            return reply('400 Bad Request', 'invalid_delivery')
        content_type = environ.get('CONTENT_TYPE', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' or environ.get('HTTP_CONTENT_ENCODING', 'identity') != 'identity':
            return reply('415 Unsupported Media Type', 'unsupported_media_type')
        db = None
        try:
            raw = environ['wsgi.input'].read(length)
            if not isinstance(raw, bytes) or len(raw) != length:
                raise payments.PaymentError('incomplete request body')
            now = self.clock()
            # Verify Stripe before acquiring/opening the database. receive_stripe
            # verifies again before its transaction; no unsigned write is possible.
            if route == '/stripe':
                signature = environ.get('HTTP_STRIPE_SIGNATURE', '')
                adapter.verify(raw, signature, now)
            db = self.db_factory()
            if not isinstance(db, sqlite3.Connection):
                raise RuntimeError('database unavailable')
            if route == '/stripe':
                payments.receive_stripe(db, adapter, raw, signature, now, self.policy)
            else:
                headers = {k[5:].replace('_', '-'): v for k, v in environ.items()
                           if k.startswith('HTTP_PAYPAL_')}
                receive_paypal(db, adapter, self.paypal_platform, raw, headers, now)
        except payments.PaymentError:
            return reply('400 Bad Request', 'invalid_delivery')
        except Exception:
            # Persist/verification outage must remain retryable; never acknowledge
            # a delivery whose durable receipt could not be committed.
            return reply('503 Service Unavailable', 'temporarily_unavailable')
        finally:
            if isinstance(db, sqlite3.Connection):
                db.close()
        return reply('200 OK', 'received')
