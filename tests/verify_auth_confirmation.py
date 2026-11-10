"""24-hour/IP boundary tests and real extracted Flask authentication handlers."""
import ast
import base64
import hashlib
import hmac
import ipaddress
import math
from pathlib import Path
import secrets
import sqlite3
import struct
import sys
import time
import unittest
from types import SimpleNamespace
from flask import Flask, abort, current_app, flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auth_confirmation as confirmation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ast.parse((ROOT / 'community_features.py').read_text())


def function(name, env):
    node = next(n for n in ast.walk(SOURCE) if isinstance(n, ast.FunctionDef) and n.name == name)
    node = ast.FunctionDef(name=node.name, args=node.args, body=node.body, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(ROOT / 'community_features.py'), 'exec'), env)
    return env[name]


class TrustTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.env = {'neonrest.client_ip': '203.0.113.10'}
        confirmation.confirm(self.state, self.env, 'fixture-secret', 100000, True)

    def fresh(self, age, factor=True):
        return confirmation.is_fresh(self.state, self.env, 'fixture-secret', 100000 + age, factor)

    def test_full_day_is_fixed_not_sliding(self):
        self.assertTrue(self.fresh(86399))
        self.assertFalse(self.fresh(86400))
        self.assertEqual(self.state['fresh_at'], 100000)

    def test_old_factor_and_future_timestamps_are_not_trusted(self):
        self.state['factor_at'] = 100000 - 86400
        self.assertFalse(self.fresh(0))
        self.assertTrue(self.fresh(0, False))
        for value in (True, '100000', math.nan, math.inf, 100001):
            self.state['fresh_at'] = value
            self.assertFalse(self.fresh(0, False))

    def test_changed_missing_or_unbound_network_requires_confirmation(self):
        for env in ({}, {'neonrest.client_ip': '203.0.113.11'}, {'neonrest.client_ip': 'bad'}):
            self.assertFalse(confirmation.is_fresh(self.state, env, 'fixture-secret', 100010, True))
        self.state.pop('confirmation_ip')
        self.assertFalse(self.fresh(0))

    def test_proxy_headers_cannot_supply_or_override_trust(self):
        self.assertIsNone(confirmation.binding({'HTTP_X_REAL_IP': '203.0.113.10', 'HTTP_X_FORWARDED_FOR': '203.0.113.10'}, 'fixture-secret'))
        self.env.update(HTTP_X_REAL_IP='203.0.113.11', HTTP_X_FORWARDED_FOR='203.0.113.11')
        self.assertTrue(self.fresh(0))

    def test_canonical_addresses_and_keyed_nonplaintext_binding(self):
        a = confirmation.binding({'neonrest.client_ip': '::ffff:203.0.113.10'}, 'fixture-secret')
        self.assertEqual(a, self.state['confirmation_ip'])
        self.assertNotEqual(a, confirmation.binding(self.env, 'different-secret'))
        self.assertNotIn('203.0.113.10', str(self.state))
        self.assertEqual(confirmation.binding({'neonrest.client_ip': '2001:0db8::1'}, 'fixture-secret'), confirmation.binding({'neonrest.client_ip': '2001:db8:0:0::1'}, 'fixture-secret'))

    def test_unavailable_address_cannot_stamp_confirmation(self):
        before = dict(self.state)
        with self.assertRaises(ValueError):
            confirmation.confirm(self.state, {}, 'fixture-secret', 100010, True)
        self.assertEqual(self.state, before)

    def test_actual_proxy_middleware_controls_the_address_source(self):
        source = ast.parse((ROOT / 'network_security.py').read_text())
        nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in ('canonical', 'ClientAddress')]
        env = dict(ipaddress=ipaddress)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<native proxy middleware>', 'exec'), env)
        observed = []
        downstream = lambda request, response: observed.append(request['neonrest.client_ip']) or []
        app = SimpleNamespace(config={'CLIENT_IP_MODE':'direct'}, testing=True)
        request = dict(REMOTE_ADDR='203.0.113.10', HTTP_X_REAL_IP='203.0.113.11', HTTP_X_FORWARDED_FOR='203.0.113.12')
        env['ClientAddress'](downstream, app)(dict(request), None)
        self.assertEqual(observed[-1], '203.0.113.10')
        app.config['CLIENT_IP_MODE'] = 'pythonanywhere'
        env['ClientAddress'](downstream, app)(dict(request), None)
        self.assertEqual(observed[-1], '203.0.113.11')
        request.pop('HTTP_X_REAL_IP')
        env['ClientAddress'](downstream, app)(dict(request), None)
        self.assertEqual(observed[-1], '')


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(time=lambda: 100000)
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''CREATE TABLE active_sessions(token_hash,user_id,created_at,seen_at,expires_at,device,revoked);
          CREATE TABLE account_safety(user_id,totp_secret,totp_step);
          CREATE TABLE recovery_codes(user_id,code_hash);''')
        self.db.execute('INSERT INTO account_safety VALUES (1,?,0)', ('JBSWY3DPEHPK3PXP',))
        self.db.commit()
        self.app = Flask(__name__)
        self.app.secret_key = 'isolated-confirmation-tests'
        self.user = dict(id=1, email='qa@example.invalid', handle='@QA', verified=1, password_hash=generate_password_hash('fixture-password', method='pbkdf2:sha256:1000'))
        self.env = dict(auth_confirmation=confirmation, time=self.clock, session=session, request=request, current_app=current_app, abort=abort, redirect=redirect, url_for=url_for, flash=flash, secrets=secrets, digest=lambda v:hashlib.sha256(v.encode()).hexdigest(), get_db=lambda:self.db, current_user=lambda:self.user, check_password_hash=check_password_hash, csrf=lambda: abort(403) if request.form.get('csrf')!='fixture' else None, render=lambda *a,**kw:('confirmation needed',200), base64=base64, hmac=hmac, hashlib=hashlib, struct=struct)
        function('second_factor', self.env)
        function('totp_value', self.env)
        function('verify_second_factor', self.env)
        function('fresh', self.env)
        function('start_session', self.env)
        function('community_reauth', self.env)
        gate = next(n for n in ast.walk(SOURCE) if isinstance(n, ast.If) and 'Confirm your sign-in for this network' in ast.unparse(n))
        # Select the exact network guard, not its surrounding authenticated-session branch.
        guard_body = [gate]
        node = ast.FunctionDef(name='network_gate', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=guard_body, decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<native network gate>', 'exec'), self.env)
        @self.app.before_request
        def network_gate():
            self.env['uid'] = session.get('user_id')
            return self.env['network_gate']()
        self.app.add_url_rule('/account/reauth', endpoint='community_reauth', view_func=self.env['community_reauth'], methods=['GET','POST'])
        @self.app.get('/login')
        def login():
            self.env['start_session'](self.user, factor=True)
            return 'signed in'
        @self.app.get('/logout')
        def logout():
            session.clear()
            return 'signed out'
        @self.app.get('/protected')
        def protected():
            return 'allowed' if self.env['fresh']() else redirect('/account/reauth')
        @self.app.route('/ordinary-writing', methods=['GET','POST'])
        def ordinary_writing():
            return 'writing allowed'
        self.client = self.app.test_client()
        self.address = {'neonrest.client_ip':'203.0.113.10'}
        self.client.get('/login', environ_overrides=self.address)

    def tearDown(self):
        self.db.close()

    def get(self, path, address=None):
        return self.client.get(path, environ_overrides=address or self.address)

    def confirm(self, **data):
        return self.client.post('/account/reauth?next=/protected', data=dict(csrf='fixture', password='fixture-password', **data), environ_overrides=self.address)

    def test_login_stamps_same_day_trust_and_next_day_expires(self):
        self.clock.time = lambda: 100000 + 86399
        self.assertEqual(self.get('/protected').status_code, 200)
        self.clock.time = lambda: 100000 + 86400
        self.assertEqual(self.get('/protected').status_code, 302)
        self.assertEqual(self.get('/ordinary-writing').status_code, 200)

    def test_network_change_blocks_writing_until_real_confirmation(self):
        other = {'neonrest.client_ip':'203.0.113.11'}
        r = self.client.post('/ordinary-writing', environ_overrides=other)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/account/reauth', r.location)
        self.address = other
        code = self.env['totp_value']('JBSWY3DPEHPK3PXP', 100000//30)
        self.assertEqual(self.confirm(code=code).status_code, 302)
        self.assertEqual(self.get('/ordinary-writing').status_code, 200)
        self.assertEqual(self.get('/protected').status_code, 200)
        self.assertEqual(self.get('/ordinary-writing', {'neonrest.client_ip':'203.0.113.10'}).status_code, 302)

    def test_bad_password_factor_and_csrf_never_refresh_trust(self):
        self.clock.time = lambda: 200000
        for data, status in [({'csrf':'bad'},403), ({'password':'wrong'},200), ({'code':'bad'},200)]:
            values=dict(csrf='fixture', password='fixture-password', code='bad');values.update(data)
            self.assertEqual(self.client.post('/account/reauth',data=values,environ_overrides=self.address).status_code,status)
            self.assertEqual(self.get('/protected').status_code,302)

    def test_recovery_code_is_consumed_and_logout_clears_trust(self):
        self.db.execute('INSERT INTO recovery_codes VALUES (1,?)',(self.env['digest']('fixture-recovery'),));self.db.commit()
        self.clock.time = lambda: 200000
        self.assertEqual(self.confirm(code='fixture-recovery').status_code,302)
        self.assertEqual(self.db.execute('SELECT count(*) FROM recovery_codes').fetchone()[0],0)
        self.clock.time = lambda: 300000
        self.assertEqual(self.confirm(code='fixture-recovery').status_code,200)
        self.assertEqual(self.get('/protected').status_code,302)
        self.get('/logout')
        with self.client.session_transaction() as state:self.assertNotIn('confirmation_ip',state)

    def test_missing_network_fails_closed_without_new_session(self):
        self.client.get('/logout',environ_overrides=self.address)
        self.assertEqual(self.client.get('/login').status_code,503)
        with self.client.session_transaction() as state:self.assertNotIn('user_id',state)


if __name__ == '__main__':
    unittest.main()
