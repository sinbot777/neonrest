"""HTTP boundary tests with real SQLite and signed fictional provider events."""
import io
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_webhooks as hooks
import marketplace_payments as payments
from marketplace_provider_api import PayPalSandboxAPI, ProviderUnavailable
from verify_marketplace_payments import setup_payment, signed_event, canonical, SECRET
from verify_marketplace_checkout import FixturePolicy


class HTTP:
    def __init__(self):
        self.status = 'SUCCESS'
        self.calls = []
        self.fail = False
    def request(self, method, url, headers, body=None):
        self.calls.append((method, url))
        if self.fail:
            raise ProviderUnavailable('private provider error')
        if url.endswith('/token'):
            return dict(token_type='Bearer', access_token='fictional_token_only')
        return dict(verification_status=self.status)


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name) / 'qa.sqlite'
        self.opened = 0
        self.db = self.connect()
        self.ctx = setup_payment(self.db)
        hooks.initialize_paypal_inbox(self.db)
        self.http = HTTP()
        self.paypal = PayPalSandboxAPI('fixture_client', 'fixture_secret', 'WH_fixture', self.http)
        self.stripe = payments.StripeTestWebhookAdapter('platform_fixture', [SECRET],
            lambda account, payment: canonical(self.ctx['order']))
        self.app = hooks.SandboxWebhookApplication('test', self.connect, self.stripe,
            self.paypal, 'paypal_fixture', lambda: 101, FixturePolicy)
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def connect(self):
        self.opened += 1
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db
    def deliver(self, raw=None, signature=None, route='/stripe', **changes):
        if raw is None:
            raw, signature = signed_event()
        environ = dict(PATH_INFO=route, REQUEST_METHOD='POST', CONTENT_LENGTH=str(len(raw)),
            CONTENT_TYPE='application/json', HTTP_STRIPE_SIGNATURE=signature or '',
            **{'wsgi.input': io.BytesIO(raw)})
        environ.update(changes)
        result = {}
        def start(status, headers):
            result.update(status=status, headers=dict(headers))
        result['body'] = b''.join(self.app(environ, start))
        return result
    def paypal_event(self, **changes):
        event = dict(id='WH_event', event_type='PAYMENT.CAPTURE.COMPLETED',
                     resource=dict(id='CAPTURE_fixture', email='private@example.invalid'))
        event.update(changes)
        return json.dumps(event).encode()
    def paypal_delivery(self, raw=None):
        return self.deliver(raw or self.paypal_event(), route='/paypal',
            HTTP_PAYPAL_TRANSMISSION_ID='transmission_fixture',
            HTTP_PAYPAL_TRANSMISSION_TIME='2026-11-07T08:00:00Z',
            HTTP_PAYPAL_TRANSMISSION_SIG='YWJjZA==',
            HTTP_PAYPAL_CERT_URL='https://api.sandbox.paypal.com/v1/notifications/certs/fixture',
            HTTP_PAYPAL_AUTH_ALGO='SHA256withRSA')
    def count(self, table):
        return self.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def test_stripe_http_delivery_is_durable_without_paying_order(self):
        result = self.deliver()
        self.assertEqual(result['status'], '200 OK')
        self.assertEqual(result['body'], b'{"status":"received"}')
        self.assertEqual(result['headers']['Cache-Control'], 'no-store')
        self.assertEqual(self.count('marketplace_payment_events'), 1)
        self.assertEqual(self.count('marketplace_payment_jobs'), 1)
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_checkout_orders').fetchone()[0], 'awaiting_payment')

    def test_duplicate_delivery_has_one_receipt_and_job(self):
        self.assertEqual(self.deliver()['status'], '200 OK')
        self.assertEqual(self.deliver()['status'], '200 OK')
        self.assertEqual(self.count('marketplace_payment_events'), 1)
        self.assertEqual(self.count('marketplace_payment_jobs'), 1)

    def test_signature_rejection_does_not_open_database(self):
        before = self.opened
        result = self.deliver(signature='forged', raw=signed_event()[0])
        self.assertEqual(result['status'], '400 Bad Request')
        self.assertEqual(self.opened, before)
        self.assertEqual(self.count('marketplace_payment_events'), 0)

    def test_live_event_is_rejected_even_with_valid_test_signature(self):
        raw, signature = signed_event(livemode=True)
        self.assertEqual(self.deliver(raw, signature)['status'], '400 Bad Request')
        self.assertEqual(self.count('marketplace_payment_events'), 0)

    def test_route_and_method_do_not_process_or_open_database(self):
        before = self.opened
        self.assertEqual(self.deliver(route='/other')['status'], '404 Not Found')
        result = self.deliver(REQUEST_METHOD='GET')
        self.assertEqual(result['status'], '405 Method Not Allowed')
        self.assertEqual(result['headers']['Allow'], 'POST')
        self.assertEqual(self.opened, before)

    def test_rejects_unbounded_empty_compressed_or_non_json_delivery(self):
        before = self.opened
        for changes, code in [({'CONTENT_LENGTH':''}, '411'),
                              ({'CONTENT_LENGTH':'-1'}, '411'),
                              ({'CONTENT_LENGTH':str(hooks.MAX_BODY+1)}, '413'),
                              ({'CONTENT_LENGTH':'0'}, '400'),
                              ({'CONTENT_TYPE':'text/plain'}, '415'),
                              ({'HTTP_CONTENT_ENCODING':'gzip'}, '415')]:
            with self.subTest(changes=changes):
                self.assertTrue(self.deliver(**changes)['status'].startswith(code))
        self.assertEqual(self.opened, before)

    def test_short_body_is_rejected_without_database_open(self):
        before = self.opened
        result = self.deliver(CONTENT_LENGTH='100000')
        self.assertEqual(result['status'], '400 Bad Request')
        self.assertEqual(self.opened, before)

    def test_no_configuration_is_retryable_and_live_factory_refused(self):
        with self.assertRaises(payments.PaymentError):
            hooks.SandboxWebhookApplication('live', self.connect)
        self.app = hooks.SandboxWebhookApplication('test', self.connect)
        result = self.deliver()
        self.assertEqual(result['status'], '503 Service Unavailable')
        self.assertEqual(result['headers']['Retry-After'], '30')

    def test_failed_database_write_is_retryable_not_acknowledged(self):
        with patch.object(payments, 'receive_stripe', side_effect=sqlite3.OperationalError('private path')):
            result = self.deliver()
        self.assertEqual(result['status'], '503 Service Unavailable')
        self.assertNotIn(b'private', result['body'])
        self.assertEqual(self.count('marketplace_payment_events'), 0)

    def test_stripe_provider_outage_keeps_receipt_and_retry_job(self):
        def unavailable(*args):
            raise ProviderUnavailable('secret-bearing detail')
        self.stripe._fetch = unavailable
        result = self.deliver()
        self.assertEqual(result['status'], '200 OK')
        self.assertEqual(self.count('marketplace_payment_events'), 1)
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_payment_jobs').fetchone()[0], 'retry')

    def test_paypal_verified_event_is_durable_review_only_and_redacted(self):
        self.assertEqual(self.paypal_delivery()['status'], '200 OK')
        row = self.db.execute('SELECT * FROM marketplace_paypal_test_inbox').fetchone()
        self.assertEqual(row['outcome'], 'needs_review')
        self.assertEqual(row['resource_ref'], 'CAPTURE_fixture')
        self.assertNotIn('private@example.invalid', repr(tuple(row)))
        self.assertEqual(self.db.execute('SELECT state FROM marketplace_checkout_orders').fetchone()[0], 'awaiting_payment')

    def test_paypal_duplicate_is_idempotent_and_conflict_is_rejected(self):
        self.assertEqual(self.paypal_delivery()['status'], '200 OK')
        self.assertEqual(self.paypal_delivery()['status'], '200 OK')
        changed = self.paypal_event(resource=dict(id='CAPTURE_other'))
        self.assertEqual(self.paypal_delivery(changed)['status'], '400 Bad Request')
        self.assertEqual(self.count('marketplace_paypal_test_inbox'), 1)

    def test_paypal_failed_remote_verification_does_not_persist(self):
        self.http.status = 'FAILURE'
        self.assertEqual(self.paypal_delivery()['status'], '400 Bad Request')
        self.assertEqual(self.count('marketplace_paypal_test_inbox'), 0)

    def test_paypal_remote_outage_is_retryable_and_redacted(self):
        self.http.fail = True
        result = self.paypal_delivery()
        self.assertEqual(result['status'], '503 Service Unavailable')
        self.assertNotIn(b'private', result['body'])
        self.assertEqual(self.count('marketplace_paypal_test_inbox'), 0)

    def test_paypal_missing_registration_is_rejected_at_startup(self):
        with self.assertRaises(payments.PaymentError):
            hooks.SandboxWebhookApplication('test', self.connect,
                paypal=PayPalSandboxAPI('fixture_client', 'fixture_secret'),
                paypal_platform='paypal_fixture')

    def test_paypal_retained_receipt_cannot_be_changed_or_deleted(self):
        self.paypal_delivery()
        for sql in ('DELETE FROM marketplace_paypal_test_inbox',
                    "UPDATE marketplace_paypal_test_inbox SET resource_ref='other'"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
            self.db.rollback()


if __name__ == '__main__':
    unittest.main()
