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

SOURCE_COMMIT='02f5668f1267839212495e9aca303e755ce5f184'
EXPECTED_TESTS=304
EXPECTED_MONEY_CHECKS=38
EXPECTED_CRYPTO='50.0.2'
SOURCE_BUDGET=2*1024*1024
FOOTPRINT_BUDGET=8*1024*1024
MANIFEST=[{"path":"marketplace_addresses.py","git_sha":"7646b106afe9a435aee6db221d2975a66b7098ec","size":22233},{"path":"marketplace_catalog.py","git_sha":"d5a1784187f4c96ca4767616fa6f622fc21b8b64","size":4863},{"path":"identity_pages.py","git_sha":"cdd5809665909fa6f08b3d110df0fae48608c5e0","size":29955},{"path":"marketplace_payments.py","git_sha":"9913720a8c3f7f7d97446daf9217b2dabb9823f7","size":33207},{"path":"marketplace_inventory.py","git_sha":"f8bd2b004412ef48ae8d30675ae29a2038b3c961","size":11125},{"path":"seller_studio.py","git_sha":"5cd5cf6d83b5651c3b6b2f71452d61efb5ff0df8","size":27506},{"path":"marketplace_ledger.py","git_sha":"bc22ec8535dae6e24ef98efe359f2efb94ef8b7e","size":8215},{"path":"marketplace_provider_api.py","git_sha":"9b003bc4102e607935afacb4d3a808415fa9ce6a","size":13171},{"path":"marketplace_quotes.py","git_sha":"7c07cb7520f284c9e5e8c8444f118e53d04f39f6","size":13899},{"path":"marketplace_checkout.py","git_sha":"7d2631a4fddd1d92be25ba4c7e227922fda09baa","size":17847},{"path":"marketplace_payment_jobs.py","git_sha":"7b65295c47f17fa7c3d18c1e25e577e576821957","size":13669},{"path":"marketplace_shipping.py","git_sha":"913c784fc9c6a9719cfa492eaad2d09c8d63be07","size":8200},{"path":"marketplace_core.py","git_sha":"f8b242b79ad0c148248ca259e9c8d1246a6f50eb","size":7423},{"path":"tests/verify_marketplace_core.py","git_sha":"0a9f1dfbe6e728fb4ce0ccb9def7d746a5969374","size":2586},{"path":"tests/verify_marketplace_addresses.py","git_sha":"bced285caaa33d48eac913b47a8a4bb0f00b9398","size":20782},{"path":"tests/verify_marketplace_foundations.py","git_sha":"c41ca52a2c237ee810d365b71c21790e711b0593","size":11840},{"path":"tests/verify_marketplace_payment_jobs.py","git_sha":"e5f64acaefe13fe9c0d7a2f3a7767ea8eb56388a","size":16015},{"path":"tests/verify_marketplace_payments.py","git_sha":"33ca761d3f129b453c4cb9ad7f1dc2c9d82a55da","size":18542},{"path":"tests/verify_marketplace_quotes.py","git_sha":"017ee5d94363ff2b73ddf62905e69b64bfaaeac0","size":12978},{"path":"tests/verify_marketplace_provider_api.py","git_sha":"b72572975e36ccf0c07ad2f752913a1a28b7f120","size":9477},{"path":"tests/verify_marketplace_checkout.py","git_sha":"9ffd8b3543794470d6e477f9b9d05a4184c66ae3","size":14649},{"path":"tests/verify_marketplace_checkout_policy.py","git_sha":"747650d7a9f5993de9cb79a156fccb821e185f6f","size":5777},{"path":"marketplace_settlement.py","git_sha":"bc803918aca88be771ecd17671dfeefad2c1101b","size":15885},{"path":"tests/verify_marketplace_settlement.py","git_sha":"62c23a3a17a935a9d4ca97360e86882e1172aa52","size":21165},{"path":"marketplace_refunds.py","git_sha":"18d0df90a837dca2fc620df92c59ad31ed27a871","size":25141},{"path":"tests/verify_marketplace_refunds.py","git_sha":"3ea586087e35360129ce69597483b9bc5d0a331e","size":27125},{"path":"check_marketplace_sandbox.py","git_sha":"7c4fcdb0a4835d4487e6977a6e57b96624aa9da1","size":4734},{"path":"tests/verify_marketplace_readiness.py","git_sha":"7282f99006aa82e850bfcfffcbec3998fa198796","size":4077},{"path":"marketplace_webhooks.py","git_sha":"3c978cc64df74d43e499b17a5040b5447a702e10","size":8768},{"path":"tests/verify_marketplace_webhooks.py","git_sha":"8609a2b96dff90bc96d34194e0d953840c924a55","size":10043},{"path":"marketplace_webhook_runtime.py","git_sha":"3a055038c56b8538abb5f72f9be1b1302b39e9f5","size":6795},{"path":"tests/verify_marketplace_webhook_runtime.py","git_sha":"baba7e1d155221e54c81bd19bd78f3efeda74a95","size":7476},{"path":"marketplace_test_checkout_api.py","git_sha":"937a92bee26a2eb9e0dc292040b6cc2074e35614","size":5349},{"path":"tests/verify_marketplace_test_checkout_api.py","git_sha":"075b6ce70de3dab5fcf95af4dabf3466ea368144","size":4928},{"path":"marketplace_purchase_flow.py","git_sha":"96ce7ee463c16c7e44c2bd0247845f17d2f747bb","size":18263},{"path":"marketplace_carrier_rates.py","git_sha":"6f37d05db072d413bb89dce49568aa3d2a29378c","size":14603},{"path":"marketplace_pilot_orders.py","git_sha":"36802daf6721d4613ba6ba6c1d2517830ba8d08f","size":6974},{"path":"marketplace_pilot_views.py","git_sha":"e355e1b31b62117b32c32f67605e86d78331a0a9","size":17364},{"path":"templates/marketplace_pilot.html","git_sha":"b65d86ebca1ab7fa61fad6ffcb8c0722b71d8f1b","size":10846},{"path":"tests/verify_marketplace_purchase_flow.py","git_sha":"661de492b90591543c7879478f75abb7d524720f","size":12035},{"path":"tests/verify_marketplace_carrier_rates.py","git_sha":"da9b1b80357004daf1cea995fc39cbe87eb279fa","size":6821},{"path":"tests/verify_marketplace_pilot_views.py","git_sha":"a2235ff19a55dd8c9132ea360cf1f5af24a3899d","size":10201}]
LIVE_ROOTS=tuple(Path(p) for p in ('/home/sinbot/neonrest','/home/sinbot/neonrest_sandbox','/home/sinbot/db','/var/www'))


class RehearsalError(RuntimeError):
    pass


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def within(path,root):
    return path==root or root in path.parents


def _source(item,source_directory):
    relative=Path(item['path'])
    if relative.is_absolute() or '..' in relative.parts or (relative.suffix!='.py' and str(relative)!='templates/marketplace_pilot.html'):
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

