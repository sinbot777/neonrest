from pathlib import Path
import hashlib,io,json,os,sqlite3,sys,tempfile,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from media_export import build_archive,ExportUnavailable,open_regular
checks=0
def check(value,message):
 global checks
 assert value,message
 checks+=1
with tempfile.TemporaryDirectory() as temp:
 root=Path(temp);(root/'nested').mkdir();(root/'nested/own.png').write_bytes(b'own upload');(root/'private.pdf').write_bytes(b'%PDF-private');(root/'other.png').write_bytes(b'OTHER USER SECRET');os.link(root/'nested/own.png',root/'alias.png');(root/'link.png').symlink_to(root/'other.png');(root/'linked').symlink_to(root/'nested',target_is_directory=True)
 candidates=[(root,'nested/own.png','attachment'),(root,'private.pdf','private document'),(root,'alias.png','artwork'),(root,'missing.png','attachment'),(root,'link.png','attachment'),(root,'linked/own.png','attachment'),(root,'../other.png','attachment')]
 out=build_archive({'profile':{'handle':'@Fictional'}},candidates)
 with zipfile.ZipFile(out) as z:
  names=z.namelist();m=json.loads(z.read('manifest.json'));files=m['files']
  check('account.json' in names and 'README.txt' in names,'metadata/readme');check(len([n for n in names if n.startswith('media/')])==2,'deduplicate aliases and reject unsafe files');check(z.read(files[0]['file'])==b'own upload','own upload');check(z.read(files[1]['file'])==b'%PDF-private','private submission');check(files[2]['duplicate'],'hardlink dedup');check(files[3]['status']=='missing','missing manifest');check(all(f['status']=='unavailable' for f in files[4:]),'symlink/traversal refusal');check(files[0]['sha256']==hashlib.sha256(b'own upload').hexdigest(),'hash');check(m['source_bytes']==22,'source count');check(all(not n.startswith('/') and '..' not in n for n in names),'archive paths');check(str(root).encode() not in z.read('manifest.json'),'no storage paths');check(b'OTHER USER SECRET' not in b''.join(z.read(n) for n in names),'no foreign bytes')
 try:build_archive({},[(root,'private.pdf','private')],max_source=2)
 except ExportUnavailable:check(True,'limit fails whole export')
 else:check(False,'expected quota failure')
 try:build_archive({},[(root,'private.pdf','private')]*2001)
 except ExportUnavailable:check(True,'file count limit')
 else:check(False,'expected file limit')
 # An empty account still gets a usable manifest, never a directory scan.
 with zipfile.ZipFile(build_archive({},[])) as z:check(json.loads(z.read('manifest.json'))['files']==[],'empty export')
print(f'{checks} media archive checks passed')
