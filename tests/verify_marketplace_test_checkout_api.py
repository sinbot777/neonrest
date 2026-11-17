"""Provider creation boundary: fictional cards, scoped requests and retries."""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marketplace_test_checkout_api import StripeTestCheckoutAPI, TestCreationHTTP, PaymentError


class HTTP:
    def __init__(self):
        self.calls=[];self.enabled=True;self.live=False
    def request(self,method,url,headers,body=None):
        self.calls.append((method,url,headers,body))
        if url.endswith('/v1/account'):return dict(id='acct_platform',object='account')
        if '/accounts/' in url:return dict(id='acct_seller',country='US',charges_enabled=self.enabled,payouts_enabled=self.enabled)
        data=parse_qs(body.decode()) if body else {}
        if url.endswith('/refunds'):
            return dict(id='re_fixture',object='refund',payment_intent='pi_fixture',currency='usd',
                        amount=int(data['amount'][0]),status='succeeded',metadata={'neonrest_refund_request':data['metadata[neonrest_refund_request]'][0]})
        return dict(id='pi_fixture',object='payment_intent',livemode=self.live,amount=100,amount_received=100,
                    currency='usd',status='succeeded',metadata=dict(neonrest_order='order_fixture',neonrest_quote='quote_fixture'),
                    client_secret='fictional_secret_must_not_return')


class CreationTests(unittest.TestCase):
    def setUp(self):
        self.http=HTTP();self.api=StripeTestCheckoutAPI('acct_platform','sk_test_fixture_only',self.http)
    def payment(self,**kw):
        args=dict(account='acct_seller',order='order_fixture',quote='quote_fixture',total_cents=100);args.update(kw)
        return self.api.create_payment(**args)
    def posts(self):return [x for x in self.http.calls if x[0]=='POST']
    def test_creation_is_scoped_and_returns_no_secrets(self):
        self.assertEqual(self.payment(),dict(payment_ref='pi_fixture',status='succeeded',environment='test'))
        method,url,headers,body=self.posts()[0]
        self.assertEqual(headers['Stripe-Account'],'acct_seller')
        data=parse_qs(body.decode());self.assertEqual(data['automatic_payment_methods[allow_redirects]'],['never'])
        self.assertEqual(data['metadata[neonrest_order]'],['order_fixture'])
        self.assertNotIn('payment_method_types',data)
    def test_retry_keeps_idempotency_key_even_if_quote_changes(self):
        self.payment()
        with self.assertRaises(PaymentError):self.payment(quote='different_quote')
        self.assertEqual(self.posts()[0][2]['Idempotency-Key'],self.posts()[1][2]['Idempotency-Key'])
    def test_live_keys_and_real_payment_methods_are_refused(self):
        with self.assertRaises(PaymentError):StripeTestCheckoutAPI('acct_platform','sk_live_forbidden',self.http)
        with self.assertRaises(PaymentError):self.payment(payment_method='pm_real_customer')
        self.assertEqual(self.posts(),[])
    def test_disabled_seller_does_not_receive_creation_request(self):
        self.http.enabled=False
        with self.assertRaises(PaymentError):self.payment()
        self.assertEqual(self.posts(),[])
    def test_invalid_amount_account_and_live_response_rejected(self):
        for amount in (True,0,49,1.5,100_000_001):
            with self.assertRaises(PaymentError):self.payment(total_cents=amount)
        with self.assertRaises(PaymentError):self.payment(account='../account')
        self.http.live=True
        with self.assertRaises(PaymentError):self.payment()
    def test_refund_is_bound_to_parent_and_durable_request(self):
        result=self.api.create_refund('acct_seller','pi_fixture','order_fixture','request_fixture',1)
        self.assertEqual(result,dict(refund_ref='re_fixture',status='succeeded',environment='test'))
        data=parse_qs(self.posts()[0][3].decode())
        self.assertEqual(data['metadata[neonrest_refund_request]'],['request_fixture'])
        self.assertEqual(data['amount'],['1'])
    def test_wrong_order_overrefund_or_live_parent_does_not_post(self):
        for order,amount in (('wrong_order',1),('order_fixture',101)):
            with self.assertRaises(PaymentError):self.api.create_refund('acct_seller','pi_fixture',order,'request_fixture',amount)
        self.http.live=True
        with self.assertRaises(PaymentError):self.api.create_refund('acct_seller','pi_fixture','order_fixture','request_fixture',100)
        self.assertEqual(self.posts(),[])
    def test_http_writes_have_only_two_fixed_endpoints(self):
        self.assertTrue(TestCreationHTTP.permitted('POST','https://api.stripe.com/v1/refunds'))
        for url in ('http://api.stripe.com/v1/refunds','https://api.stripe.com/v1/payouts','https://api.stripe.com/v1/refunds?live=1','https://example.com/v1/payment_intents'):
            self.assertFalse(TestCreationHTTP.permitted('POST',url))


if __name__=='__main__':unittest.main()
