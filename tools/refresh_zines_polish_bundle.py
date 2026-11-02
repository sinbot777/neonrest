"""Refresh the private r4 build with the two verified Sandbox polish assets."""
from pathlib import Path
import hashlib
import json
import zipfile

root = Path.cwd()
base = root / 'zines-production-release-r4.zip'
output = root / 'zines-production-release-r5.zip'
assert not output.exists(), 'r5 already exists; inspect before replacing'
assert hashlib.sha256(base.read_bytes()).hexdigest() == '3bac4025f05409130dfd3fc607bf900f4e3e0da91c8c5e7af75b6e5ff75bc9e6'
expected = {
    'zines_compact.js': ('5b9eb82c3eab21f953f097d21679378766aebd6116fd32fca0ecc80b7bb562a9', 'eadf57c4dd65805164effbcf03727d13651e7c1f4443df285508b4303259f08e', '/tmp/zcompact.js'),
    'zines_workspace.js': ('fba12b6d6679f686eb12d1af02fd508b20a9b7ab1898d7757c4648a10af9a380', '79dfd89eb835f8b7b2945081f69489c92b95f0208bd48f7ab7f4d07521efaa66', '/tmp/zworkspace.js'),
}
assets = {}
for name, (_, digest, path) in expected.items():
    assets[name] = Path(path).read_bytes()
    assert hashlib.sha256(assets[name]).hexdigest() == digest, name

with zipfile.ZipFile(base) as src, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as dst:
    for entry in src.infolist():
        data = src.read(entry.filename)
        if entry.filename.startswith('source/static/') and entry.filename.rsplit('/', 1)[-1] in assets:
            data = assets[entry.filename.rsplit('/', 1)[-1]]
        elif entry.filename.endswith('.json'):
            for old, new, _ in expected.values():
                data = data.replace(old.encode(), new.encode())
        if entry.filename == 'recovery-followup.json':
            receipt = json.loads(data)
            receipt.update(native_picker='passed; Artwork 2 persisted; 1061x1600', keyboard_tabs='hosted arrows, End and roving tabindex passed', facebook='403; robots.txt excludes /sandbox', mobile_recheck='viewport override ineffective; not certified by this pass')
            data = json.dumps(receipt).encode()
        dst.writestr(entry, data)
with zipfile.ZipFile(output) as check:
    assert check.testzip() is None
    for name, data in assets.items():
        assert check.read('source/static/' + name) == data
for sub in ['candidate/neonrest_sandbox', 'production-candidate/neonrest']:
    for name, data in assets.items():
        path = root / sub / 'static' / name
        assert path.exists(), path
        path.write_bytes(data)
# Replace the generated r4 artifact after verifying r5; retain r3 and source backups.
output.replace(base)
base.rename(output)
print(json.dumps({'archive': output.name, 'bytes': output.stat().st_size, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))
