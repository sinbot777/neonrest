"""Credentialed provider reads/verification only; inactive and test/sandbox only.

There is deliberately no charge, refund, transfer, payout, account-creation or
postage method. No environment credentials are read automatically. Callers must
configure server-only credentials explicitly. Nothing registers with Flask.
"""
import base64
from datetime import datetime, timezone
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from .marketplace_payments import AccountObservation,PaymentError,Scope,_json_pairs,_invalid_constant,ref
else:
    from marketplace_payments import AccountObservation,PaymentError,Scope,_json_pairs,_invalid_constant,ref


class ProviderUnavailable(RuntimeError):
    """Intentionally redacted: never wrap a credential-bearing request/response."""


def _parse(raw):
    if type(raw) is not bytes or len(raw)>1_048_576:
        raise ProviderUnavailable('provider response unavailable')
    try:
        data=json.loads(raw,object_pairs_hook=_json_pairs,parse_constant=_invalid_constant)
    except (ValueError,UnicodeError,RecursionError):
        raise ProviderUnavailable('provider response unavailable') from None
    if not isinstance(data,dict):
        raise ProviderUnavailable('provider response unavailable')
    return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


class TestProviderHTTP:
    """Pinned HTTPS endpoints, redirects/proxies off, bounded requests/responses."""
    @staticmethod
    def permitted(method,url):
        try:
            parts=urllib.parse.urlsplit(url)
            port=parts.port
        except ValueError:
            return False
        if parts.scheme!='https' or parts.username or parts.password or port or parts.query or parts.fragment:
            return False
        if parts.netloc=='api.stripe.com' and method=='GET':
            return bool(re.fullmatch(r'/v1/(?:account|accounts/acct_[A-Za-z0-9_]+|payment_intents/pi_[A-Za-z0-9_]+|refunds/re_[A-Za-z0-9_]+)',parts.path))
        return parts.netloc=='api-m.sandbox.paypal.com' and method=='POST' and parts.path in ('/v1/oauth2/token','/v1/notifications/verify-webhook-signature')

    def request(self,method,url,headers,body=None):
        if not self.permitted(method,url) or body is not None and (type(body) is not bytes or len(body)>2_097_152):
            raise PaymentError('provider operation is not enabled')
        if any(not isinstance(k,str) or not isinstance(v,str) or '\r' in k+v or '\n' in k+v for k,v in headers.items()):
            raise PaymentError('invalid provider request header')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        request=urllib.request.Request(url,data=body,headers=headers,method=method)
        try:
            with opener.open(request,timeout=10) as response:
                if response.status!=200:
                    raise ProviderUnavailable('provider response unavailable')
                raw=response.read(1_048_577)
        except (urllib.error.URLError,TimeoutError,OSError):
            raise ProviderUnavailable('provider request unavailable') from None
        return _parse(raw)


class StripeTestAPI:
    """Test-key authenticated canonical reads with platform/account binding.

    onboarding_lookup(request_id) is a trusted server-created association, never
    an account ID passed in a browser return. Account creation/consent is separate.
    """
    VERSION='2026-10-28.endive'

    def __init__(self,platform_ref,api_key,onboarding_lookup=None,http=None):
        if not isinstance(api_key,str) or not re.fullmatch(r'sk_test_[A-Za-z0-9_]{8,512}',api_key):
            raise PaymentError('a server-configured Stripe test key is required')
        if not re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}',ref(platform_ref)):
            raise PaymentError('configured Stripe platform account required')
        self.scope=Scope('stripe',platform_ref)
        self._key=api_key
        self._lookup=onboarding_lookup
        self._http=http or TestProviderHTTP()

    def _get(self,path,account=None):
        headers={'Authorization':'Bearer '+self._key,'Stripe-Version':self.VERSION,'Accept':'application/json'}
        if account is not None:
            if not isinstance(account,str) or not re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}',account):
                raise PaymentError('invalid connected account reference')
            headers['Stripe-Account']=account
        return self._http.request('GET','https://api.stripe.com'+path,headers)

    def _platform(self):
        # Do not cache this assertion across requests/key rotations.
        data=self._get('/v1/account')
        if data.get('id')!=self.scope.platform or data.get('object')!='account':
            raise PaymentError('Stripe platform/key mismatch')

    def fetch_payment(self,account_ref,payment_ref):
        if not isinstance(payment_ref,str) or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,150}',payment_ref):
            raise PaymentError('invalid payment reference')
        self._platform()
        value=self._get('/v1/payment_intents/'+payment_ref,account_ref)
        if value.get('id')!=payment_ref or value.get('object')!='payment_intent' or value.get('livemode') is not False:
            raise PaymentError('canonical test payment mismatch')
        return value

    def fetch_refund(self,account_ref,refund_ref):
        """Canonical read only; no refund creation or fee/transfer reversal."""
        if not isinstance(refund_ref,str) or not re.fullmatch(r're_[A-Za-z0-9_]{1,150}',refund_ref):
            raise PaymentError('invalid refund reference')
        self._platform()
        value=self._get('/v1/refunds/'+refund_ref,account_ref)
        if value.get('id')!=refund_ref or value.get('object')!='refund':
            raise PaymentError('canonical refund mismatch')
        # Refund objects have no livemode field. The reconciliation adapter must
        # additionally retrieve and validate the parent test PaymentIntent.
        return value

    def resolve_account(self,account_ref):
        if not isinstance(account_ref,str) or not re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}',account_ref):
            raise PaymentError('invalid connected account reference')
        self._platform()
        data=self._get('/v1/accounts/'+account_ref)
        metadata=data.get('metadata')
        if data.get('id')!=account_ref or data.get('object')!='account' or data.get('country')!='US' or not isinstance(metadata,dict):
            raise PaymentError('canonical seller account mismatch')
        owner=metadata.get('neonrest_owner')
        if not isinstance(owner,str) or not re.fullmatch(r'[1-9][0-9]{0,17}',owner):
            raise PaymentError('provider owner binding missing')
        if type(data.get('charges_enabled')) is not bool or type(data.get('payouts_enabled')) is not bool:
            raise PaymentError('provider capability status missing')
        return AccountObservation(self.scope,ref(metadata.get('neonrest_onboarding')),account_ref,int(owner),data['charges_enabled'],data['payouts_enabled'])

    def resolve_onboarding(self,request_id):
        ref(request_id)
        if not callable(self._lookup):
            raise PaymentError('server-created onboarding association required')
        association=self._lookup(request_id)
        if not isinstance(association,(tuple,list)) or len(association)!=2:
            raise PaymentError('onboarding association unavailable')
        account_ref,owner=association
        if type(owner) is not int:
            raise PaymentError('invalid onboarding owner association')
        observation=self.resolve_account(account_ref)
        if observation.onboarding_ref!=request_id or observation.owner_id!=owner:
            raise PaymentError('provider onboarding association mismatch')
        return observation


class PayPalSandboxAPI:
    """Sandbox OAuth and remote webhook verification, without money operations.

    Uses a registered sandbox app's webhook ID; simulator mock events do not work
    with PayPal's postback verification endpoint. No certificate URL is fetched.
    A successful verification alone does not reconcile, pay or fulfill an order.
    """
    def __init__(self,client_id,client_secret,webhook_id=None,http=None):
        for value in (client_id,client_secret):
            if not isinstance(value,str) or not 8<=len(value)<=512 or any(ord(c)<33 or ord(c)>126 for c in value):
                raise PaymentError('configured PayPal sandbox credentials/webhook required')
        if webhook_id is not None:
            if not isinstance(webhook_id,str) or not 8<=len(webhook_id)<=160:
                raise PaymentError('configured PayPal sandbox webhook required')
            ref(webhook_id)
        self._client=client_id;self._secret=client_secret;self._webhook=webhook_id
        self._http=http or TestProviderHTTP()

    def _token(self):
        basic=base64.b64encode((self._client+':'+self._secret).encode()).decode('ascii')
        value=self._http.request('POST','https://api-m.sandbox.paypal.com/v1/oauth2/token',
            {'Authorization':'Basic '+basic,'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},b'grant_type=client_credentials')
        token=value.get('access_token')
        if not isinstance(value.get('token_type'),str) or value['token_type'].lower()!='bearer' or not isinstance(token,str) or not 8<=len(token)<=4096 or any(ord(c)<33 or ord(c)>126 for c in token):
            raise ProviderUnavailable('provider authorization unavailable')
        return token

    def check_credentials(self):
        """Authenticate sandbox credentials without returning/storing the token.

        A successful check does not establish webhook registration or marketplace
        production approval. No payment, refund or payout operation is performed.
        """
        self._token()
        return dict(provider='paypal',environment='sandbox',authenticated=True,
            webhook_configured=self._webhook is not None)

    def verify_webhook(self,raw,headers):
        if self._webhook is None:
            raise PaymentError('configured PayPal sandbox webhook required')
        if type(raw) is not bytes or not 0<len(raw)<=1_048_576 or not isinstance(headers,dict):
            raise PaymentError('invalid PayPal webhook payload')
        normalized={}
        for key,value in headers.items():
            if not isinstance(key,str):
                raise PaymentError('invalid PayPal webhook header')
            lowered=key.lower()
            if lowered in normalized:
                raise PaymentError('duplicate PayPal webhook header')
            normalized[lowered]=value
        fields={}
        for header,field in [('paypal-transmission-id','transmission_id'),('paypal-transmission-time','transmission_time'),('paypal-transmission-sig','transmission_sig'),('paypal-cert-url','cert_url'),('paypal-auth-algo','auth_algo')]:
            value=normalized.get(header)
            if not isinstance(value,str) or not 1<=len(value)<=4096 or any(ord(c)<33 or ord(c)>126 for c in value):
                raise PaymentError('missing or invalid PayPal verification header')
            fields[field]=value
        ref(fields['transmission_id'])
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z',fields['transmission_time']):
                raise ValueError
            datetime.fromisoformat(fields['transmission_time'].replace('Z','+00:00')).astimezone(timezone.utc)
        except ValueError:
            raise PaymentError('invalid PayPal transmission time') from None
        if fields['auth_algo']!='SHA256withRSA' or not re.fullmatch(r'https://api(?:-m)?\.sandbox\.paypal\.com/v1/notifications/certs/[A-Za-z0-9_-]+',fields['cert_url']):
            raise PaymentError('unsupported PayPal verification scope')
        try:
            base64.b64decode(fields['transmission_sig'],validate=True)
            event=json.loads(raw,object_pairs_hook=_json_pairs,parse_constant=_invalid_constant)
        except (ValueError,UnicodeError,RecursionError):
            raise PaymentError('invalid PayPal webhook') from None
        if not isinstance(event,dict):
            raise PaymentError('invalid PayPal event')
        ref(event.get('id'))
        fields.update(webhook_id=self._webhook,webhook_event=event)
        response=self._http.request('POST','https://api-m.sandbox.paypal.com/v1/notifications/verify-webhook-signature',
            {'Authorization':'Bearer '+self._token(),'Content-Type':'application/json','Accept':'application/json'},json.dumps(fields,separators=(',',':')).encode())
        if response.get('verification_status')!='SUCCESS':
            raise PaymentError('PayPal signature verification failed')
        # Minimize the return value; canonical reconciliation and inbox are separate.
        return dict(event_ref=event['id'],environment='test',provider='paypal')
