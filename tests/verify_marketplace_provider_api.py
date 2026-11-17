"""Provider request-contract tests with mocked HTTP; no credentials/network use."""
import base64
import json
import pathlib
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import marketplace_provider_api as api
from marketplace_payments import PaymentError,StripeTestWebhookAdapter


class HTTPFixture:
    def __init__(self):
        self.calls=[];self.platform='acct_platform';self.live=False;self.status='SUCCESS';self.token='fixture_access_token'
        self.account=dict(id='acct_seller',object='account',country='US',charges_enabled=True,payouts_enabled=True,
            metadata={'neonrest_owner':'1','neonrest_onboarding':'request_fixture'})
    def request(self,method,url,headers,body=None):
        self.calls.append((method,url,headers,body))
        assert api.TestProviderHTTP.permitted(method,url)
        if url.endswith('/v1/account'): return dict(id=self.platform,object='account')
        if '/v1/accounts/' in url: return self.account
        if '/payment_intents/' in url:
            return dict(id='pi_fixture',object='payment_intent',livemode=self.live,status='succeeded',amount_received=1590,amount=1590,currency='usd',metadata={'neonrest_order':'order_fixture','neonrest_quote':'quote_fixture'})
        if url.endswith('/token'): return dict(access_token=self.token,token_type='Bearer')
        if url.endswith('/verify-webhook-signature'): return dict(verification_status=self.status)
        raise AssertionError('unexpected fixture request')


class ProviderAPITests(unittest.TestCase):
    def setUp(self): self.http=HTTPFixture()
    def stripe(self,**kwargs):
        return api.StripeTestAPI('acct_platform','sk_test_fixture_not_real',http=self.http,**kwargs)
    def paypal(self):
        return api.PayPalSandboxAPI('client_fixture','secret_fixture','webhook_fixture',http=self.http)
    def paypal_event(self):
        return b'{"id":"event_fixture","event_type":"PAYMENT.CAPTURE.COMPLETED"}',{
            'PAYPAL-TRANSMISSION-ID':'transmission_fixture','PAYPAL-TRANSMISSION-TIME':'2026-11-05T22:00:00Z',
            'PAYPAL-TRANSMISSION-SIG':base64.b64encode(b'fixture_signature').decode(),
            'PAYPAL-CERT-URL':'https://api.sandbox.paypal.com/v1/notifications/certs/CERT-fixture',
            'PAYPAL-AUTH-ALGO':'SHA256withRSA'}

    def test_stripe_test_key_platform_identity_and_connected_account_headers(self):
        result=self.stripe().fetch_payment('acct_seller','pi_fixture')
        self.assertEqual(result['amount'],1590)
        self.assertNotIn('Stripe-Account',self.http.calls[0][2])
        self.assertEqual(self.http.calls[1][2]['Stripe-Account'],'acct_seller')
        self.assertEqual(self.http.calls[1][2]['Stripe-Version'],api.StripeTestAPI.VERSION)

    def test_stripe_wrong_platform_live_key_and_live_response_refused(self):
        with self.assertRaises(PaymentError): api.StripeTestAPI('acct_platform','sk_live_never_allow_this')
        self.http.platform='acct_wrong'
        with self.assertRaises(PaymentError): self.stripe().fetch_payment('acct_seller','pi_fixture')
        self.assertEqual(len(self.http.calls),1)
        self.http.platform='acct_platform';self.http.live=True
        with self.assertRaises(PaymentError): self.stripe().fetch_payment('acct_seller','pi_fixture')

    def test_account_resolver_requires_server_association_and_provider_metadata(self):
        client=self.stripe(onboarding_lookup=lambda request:('acct_seller',1))
        self.assertEqual(client.resolve_onboarding('request_fixture').owner_id,1)
        with self.assertRaises(PaymentError): client.resolve_onboarding('other_request')
        with self.assertRaises(PaymentError): self.stripe().resolve_onboarding('request_fixture')
        self.http.account['metadata']['neonrest_owner']='3'
        with self.assertRaises(PaymentError): client.resolve_onboarding('request_fixture')

    def test_stripe_canonical_adapter_uses_credentialed_read_contract(self):
        client=self.stripe()
        adapter=StripeTestWebhookAdapter('acct_platform',[b'whsec_fixture_only_not_real'],client.fetch_payment)
        self.assertEqual(adapter.canonical('acct_seller','pi_fixture')['amount'],1590)

    def test_stripe_reference_path_injection_rejected(self):
        for account,payment in [('acct_seller/../charges','pi_fixture'),('acct_seller','pi_fixture?expand=secret'),('acct_seller','https://attacker')]:
            with self.subTest(payment=payment),self.assertRaises(PaymentError): self.stripe().fetch_payment(account,payment)

    def test_paypal_readiness_authenticates_without_a_webhook_or_token_disclosure(self):
        client=api.PayPalSandboxAPI('client_fixture','secret_fixture',http=self.http)
        result=client.check_credentials()
        self.assertEqual(result,dict(provider='paypal',environment='sandbox',authenticated=True,webhook_configured=False))
        self.assertNotIn(self.http.token,str(result))
        self.assertEqual(len(self.http.calls),1)
        self.assertEqual(self.http.calls[0][1],'https://api-m.sandbox.paypal.com/v1/oauth2/token')

    def test_missing_webhook_cannot_verify_or_make_an_oauth_request(self):
        client=api.PayPalSandboxAPI('client_fixture','secret_fixture',http=self.http)
        raw,headers=self.paypal_event()
        with self.assertRaises(PaymentError): client.verify_webhook(raw,headers)
        self.assertEqual(self.http.calls,[])
        for webhook in ('','short',True,'bad/key/long'):
            with self.assertRaises(PaymentError): api.PayPalSandboxAPI('client_fixture','secret_fixture',webhook,http=self.http)

    def test_paypal_readiness_with_webhook_still_does_not_verify_delivery(self):
        result=self.paypal().check_credentials()
        self.assertTrue(result['webhook_configured']);self.assertNotIn('verified',result)
        self.assertEqual(len(self.http.calls),1)

    def test_paypal_readiness_rejects_invalid_token_without_echoing_it(self):
        self.http.token='private_fixture_token\r\nheader'
        with self.assertRaises(api.ProviderUnavailable) as error: self.paypal().check_credentials()
        self.assertNotIn('private_fixture_token',str(error.exception))

    def test_paypal_uses_only_sandbox_oauth_and_registered_webhook_id(self):
        raw,headers=self.paypal_event()
        result=self.paypal().verify_webhook(raw,headers)
        self.assertEqual(result,dict(event_ref='event_fixture',environment='test',provider='paypal'))
        self.assertEqual(self.http.calls[0][0],'POST')
        self.assertIn('api-m.sandbox.paypal.com',self.http.calls[0][1])
        body=json.loads(self.http.calls[1][3])
        self.assertEqual(body['webhook_id'],'webhook_fixture')
        self.assertEqual(body['webhook_event']['id'],'event_fixture')

    def test_paypal_signature_failure_and_bad_token_fail_closed(self):
        raw,headers=self.paypal_event();self.http.status='FAILURE'
        with self.assertRaises(PaymentError): self.paypal().verify_webhook(raw,headers)
        self.http.token='bad\r\nheader'
        with self.assertRaises(api.ProviderUnavailable): self.paypal().verify_webhook(raw,headers)

    def test_paypal_untrusted_certificate_duplicate_header_and_invalid_json_rejected_before_network(self):
        raw,headers=self.paypal_event()
        cases=[(raw,dict(headers,**{'PAYPAL-CERT-URL':'https://attacker/cert'})),
            (raw,dict(headers,**{'paypal-transmission-id':'duplicate'})),
            (b'{"id":"one","id":"two"}',headers)]
        for body,values in cases:
            with self.subTest(values=values),self.assertRaises(PaymentError): self.paypal().verify_webhook(body,values)
        self.assertEqual(self.http.calls,[])

    def test_transport_rejects_nonprovider_hosts_redirect_destinations_and_money_operations(self):
        blocked=[('GET','http://api.stripe.com/v1/account'),('GET','https://api.stripe.com.attacker/v1/account'),
            ('GET','https://api.stripe.com:bad/v1/account'),('POST','https://api.stripe.com/v1/charges'),
            ('POST','https://api-m.sandbox.paypal.com/v2/checkout/orders'),('POST','https://api-m.paypal.com/v1/oauth2/token'),
            ('GET','https://api.stripe.com/v1/account?redirect=attacker')]
        for method,url in blocked:
            with self.subTest(url=url),self.assertRaises(PaymentError): api.TestProviderHTTP().request(method,url,{})

    def test_transport_timeout_is_bounded_and_errors_are_redacted(self):
        with patch.object(api.urllib.request,'build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.URLError('SENSITIVE_PROVIDER_ERROR')
            with self.assertRaises(api.ProviderUnavailable) as error:
                api.TestProviderHTTP().request('GET','https://api.stripe.com/v1/account',{'Authorization':'Bearer PRIVATE'})
            self.assertNotIn('SENSITIVE',str(error.exception))
            self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],10)

    def test_response_json_bounds_duplicate_keys_and_header_injection(self):
        for raw in [b'[]',b'{"x":1,"x":2}',b'{"x":NaN}',b'x'*1_048_577]:
            with self.subTest(size=len(raw)),self.assertRaises(api.ProviderUnavailable): api._parse(raw)
        with self.assertRaises(PaymentError):
            api.TestProviderHTTP().request('GET','https://api.stripe.com/v1/account',{'Authorization':'Bearer secret\r\nInjected'})


if __name__=='__main__': unittest.main()
