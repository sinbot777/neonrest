"""Complimentary page grants with real SQLite and a minimal Flask billing app.

No application startup, real database, private credential or provider is used.
"""
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from flask import Flask
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader

root=Path(__file__).resolve().parents[1]
package='neonrest_page_grant_test'
module=types.ModuleType(package);module.__path__=[str(root)];sys.modules[package]=module
billing=importlib.import_module(package+'.page_billing')


class ComplimentaryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)')
        self.db.executemany('INSERT INTO users VALUES (?)',[(1,),(2,)])
        billing.pages.initialize(self.db)
        self.db.execute("INSERT INTO identity_pages(id,kind,handle,owner_id,name,state,created_at,updated_at) VALUES ('fixture','business','$fixture',1,'Fixture','draft',0,0)")
        self.db.commit()
        billing.initialize(self.db);self.db.commit()
        self.page=dict(self.db.execute('SELECT * FROM identity_pages').fetchone())
        self.cfg=dict(mode='test',key='sk_test_fixture_only',webhook='whsec_fixture_only',price='price_Fixture',complimentary_pages={'fixture':1})
        self.app=Flask(__name__);self.app.secret_key='fictional_test_session_only'
        self.app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}',
            'identity_page_error.html':'{{ message }}'}),FileSystemLoader(str(root/'templates'))])
        self.app.jinja_env.globals['community_token']=lambda:'fixture-token'
        self.app.jinja_env.filters['community_time']=str
        self.app.add_url_rule('/pages/<page_id>/edit',endpoint='identity_pages.manage',view_func=lambda page_id:'edit')
        self.app.extensions['community_auth_helpers']={'csrf':lambda:None,'fresh':lambda:True}
        billing.register(self.app,types.SimpleNamespace(get_db=lambda:self.db))
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session['user_id']=1
        self.config_patch=patch.object(billing,'config',lambda:self.cfg);self.config_patch.start()
        # Existing page-eligibility policy is outside this entitlement change.
        self.eligibility=patch.object(billing.pages,'eligible',return_value=True);self.eligibility.start()
        self.api_patch=patch.object(billing,'api',side_effect=AssertionError('provider call forbidden'))
        self.api=self.api_patch.start()
    def tearDown(self):
        self.api_patch.stop();self.eligibility.stop();self.config_patch.stop();self.db.close()

    def test_grant_is_exactly_bound_to_page_kind_and_current_owner(self):
        self.assertTrue(billing.complimentary(self.page,self.cfg))
        for changes in ({'id':'other'},{'owner_id':2},{'kind':'creative'}):
            self.assertFalse(billing.complimentary(dict(self.page,**changes),self.cfg))

    def test_malformed_grants_are_not_entitlements(self):
        for value in (None,[],True,'all',{'fixture':True},{'fixture':'1'},{'fixture':0},{'fixture':-1}):
            self.assertFalse(billing.complimentary(self.page,dict(self.cfg,complimentary_pages=value)))
        self.assertFalse(billing.complimentary(self.page,None))

    def test_complimentary_entitlement_creates_no_paid_subscription(self):
        self.assertTrue(billing.entitled(self.db,self.page))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM page_subscriptions').fetchone()[0],0)
        self.api.assert_not_called()

    def test_revocation_or_owner_transfer_removes_comp_immediately(self):
        self.assertFalse(billing.entitled(self.db,dict(self.page,owner_id=2)))
        self.cfg['complimentary_pages']={}
        self.assertFalse(billing.entitled(self.db,self.page))

    def test_paid_entitlement_rules_remain_in_force_for_other_pages(self):
        self.cfg['complimentary_pages']={}
        self.db.execute("INSERT INTO page_subscriptions(page_id,owner_id,checkout_key,status,paid_until,live,updated_at) VALUES ('fixture',1,'fixture-key','active',?,1,0)",(int(time.time())+3600,))
        self.db.commit()
        self.assertFalse(billing.entitled(self.db,self.page))
        self.cfg['mode']='live'
        self.assertTrue(billing.entitled(self.db,self.page))
        self.assertFalse(billing.entitled(self.db,dict(self.page,owner_id=2)))
        self.db.execute('UPDATE page_subscriptions SET review_required=1');self.db.commit()
        self.assertFalse(billing.entitled(self.db,self.page))

    def test_billing_page_explains_comp_and_hides_checkout(self):
        response=self.client.get('/pages/fixture/billing')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Complimentary page activation',response.data)
        self.assertNotIn(b'Continue to Stripe checkout',response.data)
        self.assertNotIn(b'I authorize $5',response.data)
        self.api.assert_not_called()

    def test_checkout_post_for_comp_is_refused_before_provider_call(self):
        response=self.client.post('/pages/fixture/billing',data={'action':'checkout','accept_terms':'yes'})
        self.assertEqual(response.status_code,409)
        self.api.assert_not_called()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM page_subscriptions').fetchone()[0],0)

    def test_form_field_cannot_create_grant(self):
        self.cfg['complimentary_pages']={}
        response=self.client.post('/pages/fixture/billing',data={'action':'checkout','complimentary_pages':'fixture'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(billing.entitled(self.db,self.page))
        self.api.assert_not_called()

    def test_private_configuration_is_the_grant_source(self):
        self.config_patch.stop()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stripe.json'
            path.write_text(json.dumps(dict(mode='test',secret_key='sk_test_fixture_only',webhook_secret='whsec_fixture_only',price_id='price_Fixture',complimentary_pages={'fixture':1})))
            path.chmod(0o600)
            with patch.dict(os.environ,{'NEONREST_PRODUCTION_STRIPE_CONFIG':str(path)}):
                with self.app.test_request_context('/pages/fixture/billing'):
                    self.assertTrue(billing.complimentary(self.page,billing.config()))
                    path.chmod(0o644)
                    self.assertIsNone(billing.config())
        self.config_patch.start()


if __name__=='__main__':unittest.main()
