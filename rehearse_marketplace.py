"""Isolated component rehearsal for one pinned Marketplace candidate.

Run as a separate Python process. Downloads only the manifest's public source,
checks Git blob hashes, then blocks sockets/live app and database access during
tests. Does not install packages, import app startup, migrate live data or deploy.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
from urllib.parse import urlsplit, unquote
import uuid

SOURCE_COMMIT='83e174c96f37efb576b224a71cbe3137fa8b0b68'
EXPECTED_TESTS=345
EXPECTED_MONEY_CHECKS=38
EXPECTED_CRYPTO='50.0.2'
SOURCE_BUDGET=2*1024*1024
FOOTPRINT_BUDGET=8*1024*1024
MANIFEST=[{"path":"marketplace_addresses.py","size":22232,"git_sha":"bd25fb55b7e35b4bbb6f27ae8385d1dc47fbba31"},{"path":"marketplace_catalog.py","size":4862,"git_sha":"ce4db469247b16b69d95583d36b6226357917e2f"},{"path":"identity_pages.py","size":33750,"git_sha":"edfad0c23864638c9ff4fc29eeeda490231cf22e"},{"path":"marketplace_payments.py","size":33206,"git_sha":"2dd53b78e1e1fbf9c8c4a33c51fd9bd61a10bfa6"},{"path":"marketplace_inventory.py","size":11124,"git_sha":"a9bd8f149223a50779d12d3134cb63382add79c9"},{"path":"seller_studio.py","size":27505,"git_sha":"05baa5a2a82eafb5a9a15ffc926bff8ccbed42f4"},{"path":"marketplace_ledger.py","size":8214,"git_sha":"0c3ca8884239c37217b236ebb06e473ad1dd7281"},{"path":"marketplace_provider_api.py","size":13170,"git_sha":"9ad5c71d0825256afa3b776f5435a45389db0000"},{"path":"marketplace_quotes.py","size":13898,"git_sha":"dd47e6275ed9cbcc961ff16862279d69cf9ac890"},{"path":"marketplace_checkout.py","size":17847,"git_sha":"7d2631a4fddd1d92be25ba4c7e227922fda09baa"},{"path":"marketplace_payment_jobs.py","size":13668,"git_sha":"7bc4f88760679625410867d3a49c06ec460005db"},{"path":"marketplace_shipping.py","size":8199,"git_sha":"0b7b0cab8949585f0b657908bf2e2981e72694bf"},{"path":"marketplace_core.py","size":7422,"git_sha":"5076f5cd5d68f5269d8205e2f282aa82dad67b04"},{"path":"tests/verify_marketplace_core.py","size":2585,"git_sha":"8c71e31ddb0c396a04e9fd2e9ac1b33595d1e8df"},{"path":"tests/verify_marketplace_addresses.py","size":20781,"git_sha":"20c71405f34b7b0d65d6e8d37f8b88d4af2b41e6"},{"path":"tests/verify_marketplace_foundations.py","size":11839,"git_sha":"fad3767786b23066d17ba403669400d6add4401c"},{"path":"tests/verify_marketplace_payment_jobs.py","size":16014,"git_sha":"cd1964673b529006fc62bc9767de8af8d545bd74"},{"path":"tests/verify_marketplace_payments.py","size":18541,"git_sha":"294695c08ab22e18ec23c6f3166c927fb32e1d43"},{"path":"tests/verify_marketplace_quotes.py","size":12977,"git_sha":"bcf16cf4a37888d173c70cb3abad1c4d4bb37865"},{"path":"tests/verify_marketplace_provider_api.py","size":9476,"git_sha":"a117e583c3bd912fab346d818c1e1d52f9489911"},{"path":"tests/verify_marketplace_checkout.py","size":14648,"git_sha":"e5c52872c43809fde39ce569b83f7738913e9fb2"},{"path":"tests/verify_marketplace_checkout_policy.py","size":5776,"git_sha":"bd9a25ade9714df3055bc5a004bfec08c753b769"},{"path":"marketplace_settlement.py","size":15885,"git_sha":"bc803918aca88be771ecd17671dfeefad2c1101b"},{"path":"tests/verify_marketplace_settlement.py","size":21164,"git_sha":"b414f88764aa5b7c4c7aa6babfaed8c887171ac3"},{"path":"marketplace_refunds.py","size":25141,"git_sha":"18d0df90a837dca2fc620df92c59ad31ed27a871"},{"path":"tests/verify_marketplace_refunds.py","size":27124,"git_sha":"0a43e4eab8f561d073f03bb216a1e552f1dd0f5c"},{"path":"check_marketplace_sandbox.py","size":4733,"git_sha":"6afdcc2d8762b8ad1e5f2a2d4f0480934aebf033"},{"path":"tests/verify_marketplace_readiness.py","size":4133,"git_sha":"864249a0b0aa574949be59eb1f8e7bcd033147f3"},{"path":"marketplace_webhooks.py","size":8767,"git_sha":"ca4180dc761eaa4a56202ff32b0dca6e4134d8b2"},{"path":"tests/verify_marketplace_webhooks.py","size":10042,"git_sha":"7b75776d5d792d091c50bdf56f3149ddb62c8660"},{"path":"marketplace_webhook_runtime.py","size":6794,"git_sha":"c0a2c79afc28c6b0177f1c8e1696de74244445b2"},{"path":"tests/verify_marketplace_webhook_runtime.py","size":7475,"git_sha":"a81bb3ef41840065a8f2e0c983184463f5083aed"},{"path":"marketplace_test_checkout_api.py","size":5348,"git_sha":"4e01f9edc6c446c00598b1ca69ed430367c2bfc3"},{"path":"tests/verify_marketplace_test_checkout_api.py","size":4927,"git_sha":"ac6a02aeb0e86a4b6e742677941d84cf5f40a4c3"},{"path":"marketplace_purchase_flow.py","size":18263,"git_sha":"96ce7ee463c16c7e44c2bd0247845f17d2f747bb"},{"path":"marketplace_carrier_rates.py","size":15199,"git_sha":"e82bda7601d4089840873f6827c1736fecb9a099"},{"path":"marketplace_pilot_orders.py","size":6974,"git_sha":"36802daf6721d4613ba6ba6c1d2517830ba8d08f"},{"path":"marketplace_pilot_views.py","size":21937,"git_sha":"a374d4dc272e81370217e26a0f52da6122231cbf"},{"path":"templates/marketplace_pilot.html","size":11373,"git_sha":"2077679c81c8958b33f1e4f0074fa59db8f4abc7"},{"path":"tests/verify_marketplace_purchase_flow.py","size":12035,"git_sha":"661de492b90591543c7879478f75abb7d524720f"},{"path":"tests/verify_marketplace_carrier_rates.py","size":6821,"git_sha":"da9b1b80357004daf1cea995fc39cbe87eb279fa"},{"path":"tests/verify_marketplace_pilot_views.py","size":10232,"git_sha":"ee6be2c06cd4b943fb1f0e76cc6b9daf32dfe22a"},{"path":"marketplace_seller_shipping.py","size":15160,"git_sha":"3bf7ed96ac66d933ece77f1f3fb8bf91d3b5f9b7"},{"path":"templates/marketplace_seller_shipping.html","size":11587,"git_sha":"88b1c3fed935835368278845e2b71a84504208df"},{"path":"tests/verify_marketplace_seller_shipping.py","size":12433,"git_sha":"db3f07302a3f57ee2d37bd43226ebc301e55dc1c"},{"path":"marketplace_shipping_sandbox.py","size":9741,"git_sha":"f35f2e38a5b23428f42f5341e66a945343bc4ac1"},{"path":"tests/verify_marketplace_shipping_sandbox.py","size":5781,"git_sha":"99384c575b19394d0850b5f890146be5b4263731"},{"path":"templates/seller_studio.html","size":17212,"git_sha":"8e1fb2a489723046063e1c417e53ff5a47904ba3"},{"path":"marketplace_purchase_sandbox.py","size":11727,"git_sha":"b09895c0ac03e525583fdffcab76b3a96aeb2839"},{"path":"tests/verify_marketplace_purchase_sandbox.py","size":8217,"git_sha":"e8e3ff82815cf6dcbe72be1f44827986a7129630"},{"path":"tests/verify_marketplace_shipping_error_ui.py","size":1572,"git_sha":"836c1f8f39a688e00ca4fa4abdb64115710375a6"},{"path":"page_profile.py","size":10617,"git_sha":"c371198b7a2df9266a05899aa18df8cea1a0b03a"},{"path":"page_css.py","size":5853,"git_sha":"963665632353f72a04f34d36a4231b9264c97443"},{"path":"page_layout.py","size":3881,"git_sha":"62c219f1047f622f93a4e95d56261efcc229e24d"}]
LIVE_ROOTS=tuple(Path(p) for p in ('/home/sinbot/neonrest','/home/sinbot/neonrest_sandbox','/home/sinbot/db','/var/www'))


class RehearsalError(RuntimeError):
    pass


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def within(path,root):
    return path==root or root in path.parents


def _source(item,source_directory):
    relative=Path(item['path'])
    if relative.is_absolute() or '..' in relative.parts or (relative.suffix!='.py' and str(relative) not in ('templates/marketplace_pilot.html','templates/marketplace_seller_shipping.html','templates/seller_studio.html')):
        raise RehearsalError('invalid source manifest path')
    if source_directory:
        path=source_directory/relative
        if path.is_symlink() or not within(path.resolve(),source_directory):
            raise RehearsalError('source path is not an ordinary candidate file')
        raw=path.read_bytes()
    else:
        url='https://raw.githubusercontent.com/sinbot777/neonrest/'+SOURCE_COMMIT+'/'+item['path']
        request=urllib.request.Request(url,headers={'User-Agent':'Neonrest-Marketplace-Component-QA'})
        with urllib.request.urlopen(request,timeout=20) as response:
            raw=response.read(200_001)
    if len(raw)!=item['size'] or len(raw)>200_000 or git_blob(raw)!=item['git_sha']:
        raise RehearsalError('committed source integrity check failed: '+item['path'])
    return raw


def _guards(destination):
    counts=dict(network_attempts=0,live_path_attempts=0,live_app_import_attempts=0,external_sqlite_attempts=0,process_attempts=0)
    def audit(event,args):
        if event.startswith('socket.') and event not in ('socket.__new__','socket.gethostname'):
            counts['network_attempts']+=1
            raise PermissionError('network disabled for isolated component rehearsal')
        if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn','os.fork','os.forkpty'):
            counts['process_attempts']+=1
            raise PermissionError('child processes disabled for isolated component rehearsal')
        if event=='import' and args and isinstance(args[0],str) and (args[0]=='neonrest' or args[0].startswith('neonrest.') or args[0]=='neonrest_sandbox' or args[0].startswith('neonrest_sandbox.')):
            counts['live_app_import_attempts']+=1
            raise PermissionError('live application imports are disabled')
        if event=='sqlite3.connect':
            name=str(args[0])
            allowed=name==':memory:' or name.startswith('file::memory:')
            if not allowed:
                if name.startswith('file:'):
                    uri=urlsplit(name)
                    allowed=(uri.scheme=='file' and not uri.netloc and not uri.fragment
                             and uri.query=='mode=rw' and within(Path(unquote(uri.path)).resolve(),destination))
                else:
                    allowed=within(Path(name).resolve(),destination)
            if not allowed:
                counts['external_sqlite_attempts']+=1
                raise PermissionError('only isolated QA databases may be opened')
        if event in ('open','os.listdir','os.scandir') and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0])).resolve()
            if any(within(path,root) for root in LIVE_ROOTS):
                counts['live_path_attempts']+=1
                raise PermissionError('live application/database paths are disabled')
    sys.addaudithook(audit)
    return counts


def run(destination,source_directory,expected_python):
    import cryptography
    target=destination.expanduser().resolve()
    if target.exists() or any(within(target,root) for root in LIVE_ROOTS):
        raise RehearsalError('destination must be a new isolated directory')
    if not target.parent.is_dir():
        raise RehearsalError('destination parent must already exist')
    if cryptography.__version__!=EXPECTED_CRYPTO:
        raise RehearsalError('runtime cryptography version does not match the candidate lock')
    if expected_python and '.'.join(platform.python_version().split('.')[:2])!=expected_python:
        raise RehearsalError('runtime Python version mismatch')
    if len({item['path'] for item in MANIFEST})!=len(MANIFEST) or sum(item['size'] for item in MANIFEST)>SOURCE_BUDGET:
        raise RehearsalError('source manifest exceeds bounds')
    source_directory=source_directory.resolve() if source_directory else None
    target.mkdir(mode=0o700)
    code_root=target/'source';code_root.mkdir()
    temporary=target/'temporary';temporary.mkdir()
    receipt_path=target/'result.json'
    receipt=dict(schema_version=1,source_commit=SOURCE_COMMIT,run_id=uuid.uuid4().hex,
        environment='isolated_component_qa',python=platform.python_version(),sqlite=sqlite3.sqlite_version,
        cryptography=cryptography.__version__,manifest_files=len(MANIFEST),source_bytes=0,
        expected_tests=EXPECTED_TESTS,tests_run=0,money_checks=0,passed=False,
        provider_calls_enabled=False,live_application_loaded=False,live_databases_opened=False)
    folder_note='''Purpose: isolated Marketplace component rehearsal, not a live app or rollback.
Source is pinned to GitHub commit {commit}; every copied file is Git-blob checked.
No real database, customer record, credential or deployment configuration is copied.
Only fictional test fixtures and ephemeral test keys are used.
Source/harness belong in GitHub; result.json and test-output.txt are generated QA evidence.
Production: not deployed from this folder. Sandbox: not deployed from this folder.
No web application, scheduled task or runtime path is configured to use this directory.
Preserve the result receipt in release notes before removing this completed QA folder.
This directory is unnecessary for serving either live application.
Do not use it as a Production backup; it contains no real application data or keys.
No automatic cleanup is performed.
'''.format(commit=SOURCE_COMMIT)
    (target/'FOLDER-STATUS.txt').write_text(folder_note)
    try:
        for item in MANIFEST:
            raw=_source(item,source_directory)
            path=code_root/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            receipt['source_bytes']+=len(raw)
        (target/'manifest.json').write_text(json.dumps(dict(source_commit=SOURCE_COMMIT,files=MANIFEST),indent=2)+'\n')
        # This process is dedicated to QA. Credential-like environment variables
        # are removed only from this process, without reading or logging values.
        for name in tuple(os.environ):
            if re.search(r'STRIPE|PAYPAL|SHIPPO|EASYPOST|SECRET|PASSWORD|TOKEN|API_KEY|DATABASE_URL',name,re.I):
                os.environ.pop(name,None)
        receipt['credential_environment_sanitized']=True
        tempfile.tempdir=str(temporary)
        os.environ['TMPDIR']=str(temporary)
        sys.dont_write_bytecode=True
        os.chdir(code_root)
        sys.path[:]=[str(code_root)]+[p for p in sys.path if p and not any(within(Path(p).resolve(),root) for root in LIVE_ROOTS)]
        counts=_guards(target)
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
            suite=unittest.defaultTestLoader.discover(str(code_root/'tests'),pattern='verify_marketplace_*.py')
            result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
        log=output.getvalue();(target/'test-output.txt').write_text(log)
        receipt.update(counts)
        receipt['tests_run']=result.testsRun
        receipt['failures']=len(result.failures)
        receipt['errors']=len(result.errors)
        receipt['skipped']=len(result.skipped)
        match=re.findall(r'(\d+) marketplace money/shipping checks passed',log)
        receipt['money_checks']=int(match[0]) if len(match)==1 else 0
        receipt['passed']=result.wasSuccessful() and not result.skipped and result.testsRun==EXPECTED_TESTS and receipt['money_checks']==EXPECTED_MONEY_CHECKS and not any(counts.values())
        receipt['guard_checks_passed']=not any(counts.values())
        receipt['live_application_loaded']=False
        receipt['live_databases_opened']=False
    except Exception as error:
        # No credential or provider error text is written into evidence.
        receipt.update(passed=False,error_type=type(error).__name__)
    finally:
        receipt_path.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
        receipt['footprint_bytes']=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
        if receipt['footprint_bytes']>FOOTPRINT_BUDGET:
            receipt.update(passed=False,footprint_limit_exceeded=True)
        receipt_path.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print('MARKETPLACE_COMPONENT_REHEARSAL',json.dumps(receipt,sort_keys=True))
    print('QA_RECEIPT',str(receipt_path))
    return 0 if receipt['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--source-directory',type=Path,help='Local manifest-verified source for offline harness checks')
    parser.add_argument('--expected-python',default='3.13')
    args=parser.parse_args()
    try:
        return run(args.destination,args.source_directory,args.expected_python)
    except Exception as error:
        print('REHEARSAL_PREFLIGHT_FAILED',type(error).__name__)
        return 1


if __name__=='__main__':
    raise SystemExit(main())


