"""Real Seller Studio route/SQLite checks without application startup or providers."""
from pathlib import Path
import importlib.util
import importlib
import sys
import types
import unittest
from flask import Flask, abort, request, session
from jinja2 import ChoiceLoader, DictLoader

spec=importlib.util.spec_from_file_location('identity_foundation',Path(__file__).with_name('verify_identity_pages.py'))
foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)
studio=importlib.import_module('page_fixture.seller_studio')
pages=foundation.pages


class IdentityFormTests(foundation.PagesTests):
    def setUp(self):
        super().setUp();self.db.commit()
        self.app=Flask(__name__,template_folder=str(Path(__file__).parents[1]/'templates'))
        self.app.config.update(SECRET_KEY='fictional-session-fixture',TESTING=True)
        self.app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),self.app.jinja_loader])
        self.app.jinja_env.globals['community_token']=lambda:'fixture-csrf'
        self.app.add_url_rule('/reauth','community_reauth',lambda:'reauth')
        self.fresh=True
        def csrf():
            if request.form.get('theme_csrf_token')!=session.get('theme_csrf_token') or not session.get('theme_csrf_token'):abort(400)
        self.app.extensions['community_auth_helpers']={'csrf':csrf,'fresh':lambda:self.fresh,'limited':lambda *a:None}
        # Match the site's existing origin rejection. The fix changes response
        # policy, not this boundary or the form's CSRF/owner requirements.
        @self.app.before_request
        def origin_guard():
            origin=request.headers.get('Origin')
            if request.method=='POST' and origin and origin.rstrip('/')!=request.host_url.rstrip('/'):abort(403)
        studio.register(self.app,types.SimpleNamespace(get_db=lambda:self.db))
        self.shop=studio.create_independent(self.db,1,'Fixture shop');self.db.commit()
        self.path='/marketplace/studio/'+self.shop+'/identity'
        self.client=self.app.test_client();self.login(1)
    def login(self,uid):
        with self.client.session_transaction() as state:
            state.clear()
            if uid:state.update(user_id=uid,theme_csrf_token='fixture-csrf')
    def post(self,**changes):
        data=dict(theme_csrf_token='fixture-csrf',revision='0',identity_kind='page',linked_page_id=self.page)
        data.update(changes)
        return self.client.post(self.path,data=data,base_url='https://localhost',headers={'Origin':'https://localhost'})
    def test_form_keeps_same_origin_posts_and_external_referrers_private(self):
        response=self.client.get(self.path)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Referrer-Policy'],'same-origin')
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertIn('noindex',response.headers['X-Robots-Tag'])
        self.assertIn(b'data-shop-identity-form',response.data)
        self.assertIn(b'shop_identity.js',response.data)
    def test_owned_page_link_saves_and_keeps_shop_owner(self):
        self.assertEqual(self.post().status_code,302)
        row=self.db.execute('SELECT * FROM seller_shops WHERE page_id=?',(self.shop,)).fetchone()
        self.assertEqual((row['identity_kind'],row['linked_page_id'],row['owner_id'],row['revision']),('page',self.page,1,1))
    def test_missing_page_and_stale_revision_do_not_mutate(self):
        self.assertEqual(self.post(linked_page_id='').status_code,404)
        self.assertEqual(self.post(revision='99').status_code,409)
        self.assertEqual(self.db.execute('SELECT identity_kind FROM seller_shops').fetchone()[0],'personal')
    def test_other_owner_page_is_denied(self):
        other=pages.create(self.db,2,'creative','other-owner','Other');self.db.commit()
        self.assertEqual(self.post(linked_page_id=other).status_code,404)
    def test_csrf_and_freshness_are_still_required(self):
        self.assertEqual(self.post(theme_csrf_token='wrong').status_code,400)
        self.fresh=False
        response=self.post();self.assertEqual(response.status_code,302)
        self.assertIn('/reauth',response.headers['Location'])
        self.assertEqual(self.db.execute('SELECT identity_kind FROM seller_shops').fetchone()[0],'personal')
    def test_cross_site_and_null_origins_still_rejected(self):
        for origin in ('https://other.invalid','null'):
            response=self.client.post(self.path,data={'theme_csrf_token':'fixture-csrf'},base_url='https://localhost',headers={'Origin':origin})
            self.assertEqual(response.status_code,403)
    def test_nonowner_cannot_relink_shop(self):
        self.login(2);self.assertEqual(self.post().status_code,404)


if __name__=='__main__':unittest.main()
