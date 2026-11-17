"""Explicit Stripe test-card creation adapter; no live or public checkout route.

Server callers supply durable test order/quote/request identities. Creation does
not settle an order, grant delivery or establish the Production charge model.
Only Stripe's fictional test PaymentMethod tokens are accepted. No real payment
details, customer addresses, emails or client secrets are returned.
"""
import hashlib
import json
import re
from urllib.parse import urlencode

if __package__:
    from .marketplace_provider_api import StripeTestAPI, TestProviderHTTP
    from .marketplace_payments import PaymentError, ref
else:
    from marketplace_provider_api import StripeTestAPI, TestProviderHTTP
    from marketplace_payments import PaymentError, ref


class TestCreationHTTP(TestProviderHTTP):
    @staticmethod
    def permitted(method, url):
        return TestProviderHTTP.permitted(method, url) or (
            method == 'POST' and url in ('https://api.stripe.com/v1/payment_intents',
                                        'https://api.stripe.com/v1/refunds'))


class StripeTestCheckoutAPI(StripeTestAPI):
    METHODS = ('pm_card_visa', 'pm_card_chargeDeclined', 'pm_card_threeDSecure2Required')

    def __init__(self, platform_ref, api_key, http=None):
        super().__init__(platform_ref, api_key, http=http or TestCreationHTTP())

    def _post(self, path, account, payload, identity):
        if not isinstance(account, str) or not re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}', account):
            raise PaymentError('configured test seller required')
        self._platform()
        key = hashlib.sha256(json.dumps([self.scope.platform, account, path, identity], separators=(',', ':')).encode()).hexdigest()
        return self._http.request('POST', 'https://api.stripe.com/v1/' + path,
            {'Authorization': 'Bearer ' + self._key, 'Stripe-Version': self.VERSION,
             'Stripe-Account': account, 'Idempotency-Key': 'neonrest-test-' + key,
             'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'},
            urlencode(payload).encode())

    @staticmethod
    def _amount(value, minimum=1):
        if type(value) is not int or not minimum <= value <= 100_000_000:
            raise PaymentError('bounded integer USD test amount required')
        return value

    def create_payment(self, account, order, quote, total_cents, payment_method='pm_card_visa'):
        ref(order); ref(quote); self._amount(total_cents, 50)
        if payment_method not in self.METHODS:
            raise PaymentError('only fictional Stripe test cards are accepted')
        self._platform()
        seller = self._get('/v1/accounts/' + account) if isinstance(account, str) and re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}', account) else {}
        if (seller.get('id') != account or seller.get('country') != 'US'
                or seller.get('charges_enabled') is not True or seller.get('payouts_enabled') is not True):
            raise PaymentError('test seller capabilities are not ready')
        value = self._post('payment_intents', account,
            {'amount': total_cents, 'currency': 'usd', 'payment_method': payment_method,
             'confirm': 'true', 'automatic_payment_methods[enabled]': 'true',
             'automatic_payment_methods[allow_redirects]': 'never',
             'metadata[neonrest_order]': order, 'metadata[neonrest_quote]': quote}, order)
        metadata = value.get('metadata', {})
        if (value.get('object') != 'payment_intent' or value.get('livemode') is not False
                or not isinstance(value.get('id'), str) or not re.fullmatch(r'pi_[A-Za-z0-9_]+', value['id'])
                or value.get('amount') != total_cents or value.get('currency') != 'usd'
                or metadata.get('neonrest_order') != order or metadata.get('neonrest_quote') != quote):
            raise PaymentError('created test payment does not match the quote')
        return dict(payment_ref=value['id'], status=value.get('status'), environment='test')

    def create_refund(self, account, payment, order, request_id, amount_cents):
        ref(order); ref(request_id); self._amount(amount_cents)
        parent = self.fetch_payment(account, payment)
        if (parent.get('status') != 'succeeded' or parent.get('currency') != 'usd'
                or parent.get('metadata', {}).get('neonrest_order') != order
                or type(parent.get('amount_received')) is not int or parent['amount_received'] < amount_cents):
            raise PaymentError('matching successful test payment required')
        value = self._post('refunds', account,
            {'payment_intent': payment, 'amount': amount_cents,
             'metadata[neonrest_order]': order, 'metadata[neonrest_refund_request]': request_id}, request_id)
        if (value.get('object') != 'refund' or value.get('payment_intent') != payment
                or value.get('amount') != amount_cents or value.get('currency') != 'usd'
                or not isinstance(value.get('id'), str) or not re.fullmatch(r're_[A-Za-z0-9_]+', value['id'])
                or value.get('metadata', {}).get('neonrest_refund_request') != request_id):
            raise PaymentError('created test refund does not match its request')
        return dict(refund_ref=value['id'], status=value.get('status'), environment='test')
