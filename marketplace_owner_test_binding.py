"""Private operator-approved association of an existing Sandbox test merchant.

This is not public seller onboarding. No browser-supplied account IDs, provider
metadata writes, credentials, account creation or payment operations are added.
The owner explicitly approves the shop/account mapping in a private server file;
canonical test-key reads establish current provider identity and capabilities.
"""
import json
import os
import stat
if __package__:
    from .marketplace_test_checkout_api import StripeTestCheckoutAPI
    from .marketplace_payments import AccountObservation,PaymentError,ref,_json_pairs,_invalid_constant
else:
    from marketplace_test_checkout_api import StripeTestCheckoutAPI
    from marketplace_payments import AccountObservation,PaymentError,ref,_json_pairs,_invalid_constant


def approval(path):
    if not os.path.isabs(path):raise PaymentError('private approval path required')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>8192:
            raise PaymentError('owner-only approval file required')
        with os.fdopen(fd,'rb') as handle:
            fd=None;raw=handle.read(8193)
        value=json.loads(raw,object_pairs_hook=_json_pairs,parse_constant=_invalid_constant)
        if not isinstance(value,dict) or set(value)!={'environment','source','owner_id','shop_id','platform_ref','account_ref','request_ref','approved_at'}:
            raise PaymentError('explicit approval record required')
        if value['environment']!='test' or value['source']!='explicit_owner_existing_test_account' or type(value['owner_id']) is not int or value['owner_id']<=0 or type(value['approved_at']) is not int or value['approved_at']<=0:
            raise PaymentError('test owner approval required')
        for key in ('shop_id','platform_ref','account_ref','request_ref'):ref(value[key])
        return value
    finally:
        if fd is not None:os.close(fd)


class OwnerApprovedStripeTestAPI(StripeTestCheckoutAPI):
    """Server-selected private mapping; canonical capabilities are never guessed."""
    def __init__(self,platform_ref,api_key,approval_path,shop_id,owner_id,http=None):
        super().__init__(platform_ref,api_key,http)
        if type(owner_id) is not int or owner_id<=0:raise PaymentError('explicit owner required')
        self.approval_path=approval_path;self.shop_id=ref(shop_id);self.owner_id=owner_id
        self._approved()

    def _approved(self):
        value=approval(self.approval_path)
        if (value['platform_ref'],value['shop_id'],value['owner_id'])!=(self.scope.platform,self.shop_id,self.owner_id):
            raise PaymentError('approval scope mismatch')
        return value

    def resolve_onboarding(self,request_id):
        value=self._approved()
        if value['request_ref']!=request_id:raise PaymentError('approved server request required')
        return self.resolve_account(value['account_ref'])

    def resolve_account(self,account_ref):
        value=self._approved()
        if value['account_ref']!=account_ref:raise PaymentError('approved account required')
        self._platform()
        data=self._get('/v1/accounts/'+account_ref)
        if data.get('id')!=account_ref or data.get('object')!='account' or data.get('country')!='US':raise PaymentError('canonical account mismatch')
        metadata=data.get('metadata') or {}
        if not isinstance(metadata,dict) or (metadata.get('neonrest_owner') is not None and metadata['neonrest_owner']!=str(self.owner_id)):
            raise PaymentError('conflicting provider owner binding')
        if type(data.get('charges_enabled')) is not bool or type(data.get('payouts_enabled')) is not bool:raise PaymentError('canonical capability status required')
        # Re-read after the network request so an approval changed/revoked during
        # the lookup cannot authorize the returned account observation.
        if self._approved()!=value:raise PaymentError('approval changed during verification')
        return AccountObservation(self.scope,value['request_ref'],account_ref,self.owner_id,data['charges_enabled'],data['payouts_enabled'])
