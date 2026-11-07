"""Server-only, read-only provider authentication check; never activates commerce.

Private configuration paths are server options, not HTTP inputs. No credential or
OAuth token is printed. Seller onboarding, webhook delivery and checkout require
separate acceptance even when these authentication checks pass.
"""
import argparse
import json
import os
import stat
from pathlib import Path

if __package__:
    from .marketplace_provider_api import StripeTestAPI,PayPalSandboxAPI
    from .marketplace_payments import _json_pairs,_invalid_constant
else:
    from marketplace_provider_api import StripeTestAPI,PayPalSandboxAPI
    from marketplace_payments import _json_pairs,_invalid_constant


class ReadinessError(ValueError): pass


def private_config(path,provider):
    """Refuse public permissions, symlinks, wrong owner/type/mode and oversized JSON."""
    descriptor=None
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        info=os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o077 or info.st_size>16384:
            raise ValueError
        with os.fdopen(descriptor,'rb') as handle:
            descriptor=None;raw=handle.read(16385)
        if len(raw)>16384: raise ValueError
        value=json.loads(raw,object_pairs_hook=_json_pairs,parse_constant=_invalid_constant)
        if not isinstance(value,dict): raise ValueError
        if provider=='stripe':
            if value.get('mode')!='test' or not isinstance(value.get('secret_key'),str) or not value['secret_key'].startswith('sk_test_'): raise ValueError
        elif provider=='paypal':
            if value.get('provider')!='paypal' or value.get('environment')!='sandbox': raise ValueError
            if not all(isinstance(value.get(k),str) and value[k] for k in ('client_id','client_secret')): raise ValueError
        else: raise ValueError
        return value
    except (ValueError,OSError,UnicodeError):
        raise ReadinessError('private sandbox configuration unavailable or invalid') from None
    finally:
        if descriptor is not None: os.close(descriptor)


def check(stripe_path,paypal_path,platform,test_account=None,http=None):
    """Return sanitized independent checks. No account/payment/webhook is created."""
    results=[]
    try:
        cfg=private_config(stripe_path,'stripe')
        client=StripeTestAPI(platform,cfg['secret_key'],http=http)
        client._platform()
        result=dict(provider='stripe',environment='test',authenticated=True)
        if test_account is not None:
            # Use the same account-reference validation as the native read client.
            import re
            if not isinstance(test_account,str) or not re.fullmatch(r'acct_[A-Za-z0-9_]{1,150}',test_account): raise ReadinessError('invalid test account reference')
            account=client._get('/v1/accounts/'+test_account)
            if account.get('id')!=test_account or account.get('object')!='account' or account.get('country')!='US': raise ReadinessError('test account mismatch')
            if any(type(account.get(k)) is not bool for k in ('charges_enabled','payouts_enabled')): raise ReadinessError('test capability status missing')
            result.update(test_account_read=True,charges_enabled=account['charges_enabled'],payouts_enabled=account['payouts_enabled'])
        results.append(result)
    except Exception:
        results.append(dict(provider='stripe',environment='test',authenticated=False,error='readiness_check_failed'))
    try:
        cfg=private_config(paypal_path,'paypal')
        client=PayPalSandboxAPI(cfg['client_id'],cfg['client_secret'],cfg.get('webhook_id') or None,http=http)
        results.append(client.check_credentials())
    except Exception:
        results.append(dict(provider='paypal',environment='sandbox',authenticated=False,error='readiness_check_failed'))
    return dict(purpose='sandbox_authentication_only',checks=results,live_activation=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stripe-config',type=Path,default=Path('/home/sinbot/private/neonrest_sandbox/stripe.json'))
    parser.add_argument('--paypal-config',type=Path,default=Path('/home/sinbot/private/neonrest_sandbox/marketplace-paypal.json'))
    parser.add_argument('--platform',required=True)
    parser.add_argument('--test-account')
    args=parser.parse_args()
    result=check(args.stripe_config,args.paypal_config,args.platform,args.test_account)
    print('MARKETPLACE_SANDBOX_READINESS',json.dumps(result,sort_keys=True))
    return 0 if all(r['authenticated'] for r in result['checks']) else 1


if __name__=='__main__': raise SystemExit(main())
