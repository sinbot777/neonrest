from urllib.parse import urlsplit
"""Private configuration and read-only authentication checks with mocked HTTP."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_marketplace_sandbox as readiness


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.stripe=self.write('stripe.json',dict(mode='test',secret_key='sk_test_private_fixture_key'))
        self.paypal=self.write('paypal.json',dict(provider='paypal',environment='sandbox',client_id='private_fixture_client',client_secret='private_fixture_secret',webhook_id=''))
    def tearDown(self): self.tmp.cleanup()
    def write(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value));p.chmod(0o600);return p

    def test_private_test_configuration_is_accepted(self):
        self.assertEqual(readiness.private_config(self.stripe,'stripe')['mode'],'test')
        self.assertEqual(readiness.private_config(self.paypal,'paypal')['environment'],'sandbox')

    def test_public_permissions_symlinks_and_oversized_files_are_rejected(self):
        self.stripe.chmod(0o644)
        with self.assertRaises(readiness.ReadinessError): readiness.private_config(self.stripe,'stripe')
        self.stripe.chmod(0o600);link=self.root/'link';link.symlink_to(self.stripe)
        with self.assertRaises(readiness.ReadinessError): readiness.private_config(link,'stripe')
        self.stripe.write_text('x'*16385)
        with self.assertRaises(readiness.ReadinessError): readiness.private_config(self.stripe,'stripe')

    def test_live_modes_and_duplicate_configuration_keys_are_rejected(self):
        for name,cfg,provider in [('stripe.json',dict(mode='live',secret_key='sk_live_private_fixture'),'stripe'),('paypal.json',dict(provider='paypal',environment='live',client_id='private_fixture_client',client_secret='private_fixture_secret'),'paypal')]:
            p=self.write(name,cfg)
            with self.assertRaises(readiness.ReadinessError): readiness.private_config(p,provider)
        self.stripe.write_text('{"mode":"test","mode":"live","secret_key":"private_fixture"}')
        with self.assertRaises(readiness.ReadinessError) as error: readiness.private_config(self.stripe,'stripe')
        self.assertNotIn('private_fixture',str(error.exception))

    def test_authentication_and_test_capabilities_are_sanitized(self):
        calls=[]
        class HTTP:
            def request(inner,method,url,headers,body=None):
                calls.append((method,url))
                if url.endswith('/v1/account'): return dict(id='acct_platform',object='account')
                if '/accounts/' in url: return dict(id='acct_seller',object='account',country='US',charges_enabled=False,payouts_enabled=False)
                return dict(access_token='private_fixture_access_token',token_type='Bearer')
        result=readiness.check(self.stripe,self.paypal,'acct_platform','acct_seller',http=HTTP())
        self.assertTrue(all(r['authenticated'] for r in result['checks']))
        self.assertFalse(result['checks'][0]['charges_enabled']);self.assertFalse(result['checks'][1]['webhook_configured'])
        self.assertFalse(result['live_activation']);self.assertNotIn('private_fixture',str(result))
        self.assertEqual(calls[-1],('POST','https://api-m.sandbox.paypal.com/v1/oauth2/token'))

    def test_one_provider_failure_is_redacted_and_does_not_skip_other_provider(self):
        class HTTP:
            def request(inner,method,url,headers,body=None):
                if urlsplit(url).hostname == 'api.stripe.com': raise RuntimeError('private_fixture_request_data')
                return dict(access_token='private_fixture_token',token_type='Bearer')
        result=readiness.check(self.stripe,self.paypal,'acct_platform',http=HTTP())
        self.assertFalse(result['checks'][0]['authenticated']);self.assertTrue(result['checks'][1]['authenticated'])
        self.assertNotIn('private_fixture',str(result))


if __name__=='__main__': unittest.main()
