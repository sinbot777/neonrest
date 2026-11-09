"""Operator-file and authenticated-read boundaries; no real provider calls."""
import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marketplace_owner_test_binding import OwnerApprovedStripeTestAPI,approval

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'approval.json'
        self.value=dict(environment='test',source='explicit_owner_existing_test_account',owner_id=1,shop_id='shop_qa',platform_ref='acct_platform',account_ref='acct_seller',request_ref='server_request',approved_at=100)
        self.save();self.enabled=True;self.metadata={};self.calls=[];self.hook=lambda:None
        test=self
        class HTTP:
            def request(self,method,url,headers,body=None):
                test.calls.append((method,url));test.hook()
                if url.endswith('/v1/account'):return dict(id='acct_platform',object='account')
                return dict(id='acct_seller',object='account',country='US',metadata=test.metadata,charges_enabled=test.enabled,payouts_enabled=test.enabled)
        self.api=OwnerApprovedStripeTestAPI('acct_platform','sk_test_fictional_only',str(self.path),'shop_qa',1,HTTP())
    def tearDown(self):self.tmp.cleanup()
    def save(self):self.path.write_text(json.dumps(self.value));self.path.chmod(0o600)
    def test_completed_existing_account_needs_no_fake_provider_metadata(self):
        result=self.api.resolve_onboarding('server_request')
        self.assertEqual((result.owner_id,result.account_ref,result.onboarding_ref),(1,'acct_seller','server_request'))
        self.assertTrue(result.charges_enabled);self.assertTrue(all(method=='GET' for method,url in self.calls))
    def test_wrong_shop_owner_or_platform_is_refused(self):
        for key,value in [('shop_id','shop_other'),('owner_id',2),('platform_ref','acct_other')]:
            old=self.value[key];self.value[key]=value;self.save()
            with self.assertRaises(ValueError):self.api.resolve_account('acct_seller')
            self.value[key]=old;self.save()
    def test_browser_account_and_request_references_cannot_override_approval(self):
        with self.assertRaises(ValueError):self.api.resolve_account('acct_other')
        with self.assertRaises(ValueError):self.api.resolve_onboarding('browser_request')
        self.assertEqual(self.calls,[])
    def test_capabilities_are_canonical_and_conflicting_owner_is_refused(self):
        self.enabled=False;self.assertFalse(self.api.resolve_account('acct_seller').charges_enabled)
        self.metadata={'neonrest_owner':'2'}
        with self.assertRaises(ValueError):self.api.resolve_account('acct_seller')
    def test_private_permissions_symlinks_and_live_keys_are_refused(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):approval(str(self.path))
        self.path.chmod(0o600);link=Path(self.tmp.name)/'link';link.symlink_to(self.path)
        with self.assertRaises(OSError):approval(str(link))
        with self.assertRaises(ValueError):OwnerApprovedStripeTestAPI('acct_platform','sk_live_forbidden',str(self.path),'shop_qa',1)
    def test_revocation_during_provider_lookup_is_refused(self):
        def revoke():self.value['owner_id']=2;self.save()
        self.hook=revoke
        with self.assertRaises(ValueError):self.api.resolve_account('acct_seller')

if __name__=='__main__':unittest.main()
