"""Deployment boundary: no app import, startup migration or live DB attachment."""
import io
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marketplace_webhook_runtime as runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = dict(environment='test', database_path=str(self.root/'events.sqlite'),
            stripe_api_config=str(self.root/'stripe.json'), stripe_hook_config=str(self.root/'hook.json'),
            paypal_api_config=str(self.root/'paypal.json'), stripe_platform='acct_fixture',
            paypal_platform='paypal_fixture')
        self.settings = self.save('settings.json', self.cfg)
        self.save('stripe.json', dict(mode='test', secret_key='sk_test_fixture_only'))
        self.save('hook.json', dict(environment='test', platform_ref='acct_fixture',
                                   webhook_secret='whsec_separate_fixture_secret'))
        self.save('paypal.json', dict(provider='paypal', environment='sandbox',
            client_id='fixture_client', client_secret='fixture_secret', webhook_id=''))
    def tearDown(self):
        self.temp.cleanup()
    def save(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value)); path.chmod(0o600)
        return path
    def request(self, app, path, script=''):
        env = dict(PATH_INFO=path, SCRIPT_NAME=script, REQUEST_METHOD='GET',
                   **{'wsgi.input':io.BytesIO()})
        status = []
        body = b''.join(app(env, lambda code, headers: status.append(code)))
        return status[0], body, env
    def baseline(self, env, start):
        start('200 OK', [])
        return [(env['SCRIPT_NAME']+'|'+env['PATH_INFO']).encode()]

    def test_no_database_created_by_startup(self):
        with self.assertRaises(runtime.RuntimeConfigurationError):
            runtime.application(self.settings)
        self.assertFalse(Path(self.cfg['database_path']).exists())

    def test_explicit_provision_and_factory_leave_data_private_and_empty(self):
        runtime.initialize_database(self.settings)
        path = Path(self.cfg['database_path'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        app = runtime.application(self.settings)
        self.assertEqual(self.request(app, '/stripe')[0], '405 Method Not Allowed')
        db = runtime._database(path)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM marketplace_payment_events').fetchone()[0], 0)
        db.close()
        with self.assertRaises(FileExistsError):
            runtime.initialize_database(self.settings)

    def test_existing_unmarked_database_refused_without_migration(self):
        path = Path(self.cfg['database_path'])
        db = sqlite3.connect(path); db.execute('CREATE TABLE unrelated (id INTEGER)'); db.close()
        path.chmod(0o600)
        with self.assertRaises(runtime.RuntimeConfigurationError):
            runtime.application(self.settings)
        db = sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('unrelated',)])
        db.close()

    def test_configured_runtime_retains_unbound_signed_delivery_for_review(self):
        runtime.initialize_database(self.settings)
        app = runtime.application(self.settings)
        app.clock = lambda: 100
        event = dict(id='evt_runtime', object='event', account='acct_fixture',
            livemode=False, type='payment_intent.succeeded', created=100,
            data=dict(object=dict(id='pi_runtime')))
        raw = json.dumps(event).encode()
        digest = hmac.new(b'whsec_separate_fixture_secret', b'100.'+raw, hashlib.sha256).hexdigest()
        env = dict(PATH_INFO='/stripe', REQUEST_METHOD='POST', CONTENT_TYPE='application/json',
            CONTENT_LENGTH=str(len(raw)), HTTP_STRIPE_SIGNATURE='t=100,v1='+digest,
            **{'wsgi.input':io.BytesIO(raw)})
        statuses=[]
        body=b''.join(app(env, lambda status, headers: statuses.append(status)))
        self.assertEqual(statuses, ['200 OK'])
        self.assertEqual(body, b'{"status":"received"}')
        db=runtime._database(self.cfg['database_path'])
        self.assertEqual(tuple(db.execute('SELECT outcome,reason FROM marketplace_payment_events').fetchone()),
                         ('needs_review','unbound_payment'))
        db.close()

    def test_live_credentials_and_environment_refused(self):
        runtime.initialize_database(self.settings)
        self.save('stripe.json', dict(mode='live', secret_key='sk_live_fixture_only'))
        with self.assertRaises(ValueError): runtime.application(self.settings)
        self.cfg['environment']='live'; self.save('settings.json', self.cfg)
        with self.assertRaises(ValueError): runtime.application(self.settings)

    def test_symlink_public_config_and_external_database_refused(self):
        self.settings.chmod(0o644)
        with self.assertRaises(ValueError): runtime.application(self.settings)
        self.settings.chmod(0o600)
        alias = self.root/'alias.json'; alias.symlink_to(self.settings)
        with self.assertRaises(ValueError): runtime.application(alias)
        self.cfg['database_path']='/different-private-directory/database.sqlite'
        self.save('settings.json', self.cfg)
        with self.assertRaises(ValueError): runtime.application(self.settings)

    def test_signing_platform_mismatch_refused(self):
        runtime.initialize_database(self.settings)
        self.save('hook.json', dict(environment='test', platform_ref='acct_other',
                                   webhook_secret='whsec_separate_fixture_secret'))
        with self.assertRaises(ValueError): runtime.application(self.settings)

    def test_unavailable_mount_does_not_break_production_or_sandbox(self):
        app = runtime.mount(self.baseline, self.root/'missing.json')
        for path in ('/', '/feed', '/sandbox', '/sandbox/marketplace',
                     runtime.PREFIX+'-other/stripe', '/marketplace/provider-events/stripe'):
            status, body, env = self.request(app, path)
            self.assertEqual(status, '200 OK')
            self.assertEqual(body, ('|'+path).encode())
            self.assertEqual(env['PATH_INFO'], path)
        self.assertEqual(self.request(app, runtime.PREFIX+'/stripe')[0], '503 Service Unavailable')

    def test_mount_prefix_boundaries_and_original_environment_are_preserved(self):
        seen = []
        def receiver(env, start):
            seen.append((env['SCRIPT_NAME'], env['PATH_INFO']))
            start('200 OK', []); return [b'receiver']
        with patch.object(runtime, 'application', return_value=receiver):
            app = runtime.mount(self.baseline, self.settings)
        status, body, original = self.request(app, runtime.PREFIX+'/stripe', '/base')
        self.assertEqual(body, b'receiver')
        self.assertEqual(seen, [('/base'+runtime.PREFIX, '/stripe')])
        self.assertEqual(original['SCRIPT_NAME'], '/base')
        self.assertEqual(original['PATH_INFO'], runtime.PREFIX+'/stripe')
        self.assertEqual(self.request(app, runtime.PREFIX+'-other')[1], ('|'+runtime.PREFIX+'-other').encode())


if __name__ == '__main__': unittest.main()
