"""Exercise real templates/routes with disposable accounts and an isolated app.

The main application's global guards and export/retention integration still need
full-app acceptance before this feature is registered for a live deployment.
"""
from pathlib import Path
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from flask import Flask, abort, session
from jinja2 import ChoiceLoader, DictLoader

spec = importlib.util.spec_from_file_location('foundation_tests', Path(__file__).with_name('verify_identity_pages.py'))
foundation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(foundation)
pages = foundation.pages


class RouteTests(foundation.PagesTests):
    def setUp(self):
        super().setUp()
        self.db.commit()
        self.app = Flask(__name__, template_folder=str(Path(__file__).parents[1] / 'templates'))
        self.app.config.update(SECRET_KEY='fictional-fixture-secret', TESTING=True)
        self.app.jinja_loader = ChoiceLoader([DictLoader({
            'base.html': '<!doctype html><html><head><title>{% block title %}{% endblock %}</title></head><body>{% block content %}{% endblock %}</body></html>'}), self.app.jinja_loader])
        self.app.add_url_rule('/account', 'account', lambda: 'Account')
        self.app.add_url_rule('/reauth', 'community_reauth', lambda: 'Reauthenticate')
        self.fresh = True

        def csrf():
            from flask import request
            if request.form.get('theme_csrf_token') != session.get('theme_csrf_token') or not session.get('theme_csrf_token'):
                abort(400)
        self.app.extensions['community_auth_helpers'] = {
            'csrf': csrf, 'fresh': lambda: self.fresh, 'limited': lambda *a: None}
        self.app.jinja_env.globals['community_token'] = lambda: 'fixture-csrf'
        self.app.jinja_env.filters['community_time'] = lambda stamp: str(stamp)
        core = types.SimpleNamespace(get_db=lambda: self.db)
        pages.register(self.app, core)
        self.client = self.app.test_client()
        self.login(1)

    def login(self, uid):
        with self.client.session_transaction() as state:
            state.clear()
            if uid:
                state.update(user_id=uid, theme_csrf_token='fixture-csrf')

    def post(self, path, **data):
        return self.client.post(path, data={'theme_csrf_token': 'fixture-csrf', **data})

    def test_login_and_csrf_required(self):
        self.login(None)
        self.assertEqual(self.client.get('/pages').status_code, 401)
        self.login(1)
        self.assertEqual(self.client.post('/pages/new', data={'kind': 'creative'}).status_code, 400)

    def test_create_has_server_owner_and_canonical_handle(self):
        response = self.post('/pages/new', kind='creative', handle='_NewPage', name='New Page', owner_id='2', state='published')
        self.assertEqual(response.status_code, 302)
        row = self.db.execute("SELECT * FROM identity_pages WHERE handle='_newpage'").fetchone()
        self.assertEqual(row['owner_id'], 1)
        self.assertEqual(row['state'], 'draft')
        self.assertIn('/pages/'+row['id']+'/edit', response.location)

    def test_creative_publish_case_redirect_and_escaping(self):
        response = self.post('/pages/'+self.page+'/edit', action='edit', revision='0', name='<script>name</script>', description='<img src=x onerror=alert(1)>')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.post('/pages/'+self.page+'/edit', action='state', revision='1', state='published').status_code, 302)
        self.login(None)
        response = self.client.get('/_example')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'&lt;script&gt;', response.data)
        self.assertNotIn(b'<img src=x', response.data)
        response = self.client.get('/_EXAMPLE')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.location, '/_example')

    def test_business_cannot_activate_via_form(self):
        response = self.post('/pages/new', kind='business', handle='$Shop', name='Shop', paid='true', subscription_status='active')
        self.assertEqual(response.status_code, 302)
        row = self.db.execute("SELECT * FROM identity_pages WHERE handle='$shop'").fetchone()
        response = self.post('/pages/'+row['id']+'/edit', action='state', revision='0', state='published', paid='true')
        self.assertEqual(response.status_code, 409)
        self.assertIn(b'subscription setup', response.data)
        self.login(2)
        self.assertEqual(self.client.get('/$shop').status_code, 404)

    def test_other_member_cannot_read_draft_or_manage(self):
        self.login(2)
        self.assertEqual(self.client.get('/_example').status_code, 404)
        self.assertEqual(self.client.get('/pages/'+self.page+'/edit').status_code, 403)
        self.assertEqual(self.post('/pages/'+self.page+'/edit', action='edit', revision='0', name='Stolen').status_code, 403)
        self.assertEqual(pages.get(self.db, self.page)['name'], 'Example')

    def test_fresh_auth_and_stale_edits(self):
        self.fresh = False
        response = self.post('/pages/'+self.page+'/edit', action='state', revision='0', state='published')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.startswith('/reauth?'))
        self.assertEqual(pages.get(self.db, self.page)['state'], 'draft')
        self.fresh = True
        self.assertEqual(self.post('/pages/'+self.page+'/edit', action='edit', revision='99', name='Stale').status_code, 409)

    def test_age_eligibility_is_not_only_a_hidden_option(self):
        self.login(4)
        response = self.client.get('/pages/new')
        self.assertIn(b'value="creative"', response.data)
        self.assertNotIn(b'value="business"', response.data)
        self.assertEqual(self.post('/pages/new', kind='business', handle='$Forged', name='No').status_code, 403)
        self.assertEqual(self.post('/pages/new', kind='creative', handle='_Young', name='Yes').status_code, 302)

    def test_script_name_keeps_page_links_in_sandbox(self):
        response = self.client.get('/pages', environ_overrides={'SCRIPT_NAME': '/sandbox'})
        self.assertIn(b'href="/sandbox/pages/new"', response.data)
        self.assertIn(b'href="/sandbox/_example"', response.data)
        pages.set_state(self.db, 1, self.page, 0, 'published')
        self.db.commit()
        response = self.client.get('/_EXAMPLE', environ_overrides={'SCRIPT_NAME': '/sandbox'})
        self.assertEqual(response.location, '/sandbox/_example')

    def test_no_cache_for_private_or_public_page(self):
        response = self.client.get('/_example')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertIn('noindex', response.headers['X-Robots-Tag'])


if __name__ == '__main__':
    unittest.main()
