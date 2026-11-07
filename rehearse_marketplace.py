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
import uuid

SOURCE_COMMIT='c19411c8f48428dceba97c9febfa58f3e50c3577'
EXPECTED_TESTS=242
EXPECTED_MONEY_CHECKS=38
EXPECTED_CRYPTO='50.0.2'
SOURCE_BUDGET=2*1024*1024
FOOTPRINT_BUDGET=8*1024*1024
MANIFEST=[{"path":"marketplace_addresses.py","git_sha":"bd25fb55b7e35b4bbb6f27ae8385d1dc47fbba31","size":22232},{"path":"marketplace_catalog.py","git_sha":"ce4db469247b16b69d95583d36b6226357917e2f","size":4862},{"path":"identity_pages.py","git_sha":"4b1a2e1c71e186e01b7f20410506ee51b144533c","size":29954},{"path":"marketplace_payments.py","git_sha":"2dd53b78e1e1fbf9c8c4a33c51fd9bd61a10bfa6","size":33206},{"path":"marketplace_inventory.py","git_sha":"a9bd8f149223a50779d12d3134cb63382add79c9","size":11124},{"path":"seller_studio.py","git_sha":"578ff682c5c8ebbe7f9cc643bb62b0d5e3f4faf4","size":27505},{"path":"marketplace_ledger.py","git_sha":"0c3ca8884239c37217b236ebb06e473ad1dd7281","size":8214},{"path":"marketplace_provider_api.py","git_sha":"9ad5c71d0825256afa3b776f5435a45389db0000","size":13170},{"path":"marketplace_quotes.py","git_sha":"dd47e6275ed9cbcc961ff16862279d69cf9ac890","size":13898},{"path":"marketplace_checkout.py","git_sha":"f1d2dc16564112e55b3f8aa8ea9739f0403b6b3f","size":17268},{"path":"marketplace_payment_jobs.py","git_sha":"7bc4f88760679625410867d3a49c06ec460005db","size":13668},{"path":"marketplace_shipping.py","git_sha":"0b7b0cab8949585f0b657908bf2e2981e72694bf","size":8199},{"path":"marketplace_core.py","git_sha":"5076f5cd5d68f5269d8205e2f282aa82dad67b04","size":7422},{"path":"tests/verify_marketplace_core.py","git_sha":"8c71e31ddb0c396a04e9fd2e9ac1b33595d1e8df","size":2585},{"path":"tests/verify_marketplace_addresses.py","git_sha":"20c71405f34b7b0d65d6e8d37f8b88d4af2b41e6","size":20781},{"path":"tests/verify_marketplace_foundations.py","git_sha":"fad3767786b23066d17ba403669400d6add4401c","size":11839},{"path":"tests/verify_marketplace_payment_jobs.py","git_sha":"cd1964673b529006fc62bc9767de8af8d545bd74","size":16014},{"path":"tests/verify_marketplace_payments.py","git_sha":"294695c08ab22e18ec23c6f3166c927fb32e1d43","size":18541},{"path":"tests/verify_marketplace_quotes.py","git_sha":"bcf16cf4a37888d173c70cb3abad1c4d4bb37865","size":12977},{"path":"tests/verify_marketplace_provider_api.py","git_sha":"a117e583c3bd912fab346d818c1e1d52f9489911","size":9476},{"path":"tests/verify_marketplace_checkout.py","git_sha":"e5c52872c43809fde39ce569b83f7738913e9fb2","size":14648},{"path":"tests/verify_marketplace_checkout_policy.py","git_sha":"bd9a25ade9714df3055bc5a004bfec08c753b769","size":5776},{"path":"marketplace_settlement.py","git_sha":"c3dcfbb3712e128ea1bd075bd025e67e616d62d6","size":15488},{"path":"tests/verify_marketplace_settlement.py","git_sha":"b414f88764aa5b7c4c7aa6babfaed8c887171ac3","size":21164},{"path":"marketplace_refunds.py","git_sha":"987e8a8c83e633ed666c1776d7318b9dbc502569","size":24805},{"path":"tests/verify_marketplace_refunds.py","git_sha":"0a43e4eab8f561d073f03bb216a1e552f1dd0f5c","size":27124},{"path":"check_marketplace_sandbox.py","git_sha":"6afdcc2d8762b8ad1e5f2a2d4f0480934aebf033","size":4733},{"path":"tests/verify_marketplace_readiness.py","git_sha":"536efb44a69da1eeca8931d09a5b15fa848d6c4d","size":4076}]
LIVE_ROOTS=tuple(Path(p) for p in ('/home/sinbot/neonrest','/home/sinbot/neonrest_sandbox','/home/sinbot/db','/var/www'))


class RehearsalError(RuntimeError):
    pass


def git_blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def within(path,root):
    return path==root or root in path.parents


def _source(item,source_directory):
    relative=Path(item['path'])
    if relative.is_absolute() or '..' in relative.parts or relative.suffix!='.py':
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
                allowed=not name.startswith('file:') and within(Path(name).resolve(),destination)
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
