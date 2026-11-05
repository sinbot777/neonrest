"""Read-only PDF regression: Punk back covers retain all authored paragraphs."""
from pathlib import Path
import ast, importlib, io, json, math, random, sys, types
from pypdf import PdfReader
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
package=types.ModuleType('zines_backcover_probe');package.__path__=[str(root)];sys.modules[package.__name__]=package
# Load only pure core definitions; never import the application or open a database.
core=types.ModuleType(package.__name__+'.zines_core')
core.__dict__.update(math=math,random=random,MAX_PAGES=64)
tree=ast.parse((root/'zines_core.py').read_text())
nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in ('ZineError','padded','impose','wave')]
exec(compile(ast.Module(body=nodes,type_ignores=[]),'pure Zines core','exec'),core.__dict__)
sys.modules[core.__name__]=core
pdf=importlib.import_module(package.__name__+'.zines_pdf')
front={'id':'front','kind':'cover','content':json.dumps({'heading':'Proof','text':'Cover','layout':'text','caption':''})}
back={'id':'back','kind':'back','content':json.dumps({'design':'punk','heading':'KEEP EVERY WORD','text':'Intro sentinel.\n\nSecond sentinel.\n\nThird sentinel.','pullquote':'Quote sentinel.'})}
checks=0
for paper in ('letter','a4'):
 for mode in ('standard','booklet','mini8'):
  raw=pdf.render([front,back],lambda _:b'',mode,paper)
  text=' '.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
  for label in ('Intro sentinel.','Second sentinel.','Third sentinel.','Quote sentinel.'):
   assert text.count(label)==1,(paper,mode,label);checks+=1
  overflow=dict(back,content=json.dumps({'design':'punk','heading':'KEEP EVERY WORD','text':'Intro.\n\n'+('Too much footer copy. '*200)}))
  try:pdf.render([front,overflow],lambda _:b'',mode,paper)
  except core.ZineError:checks+=1
  else:raise AssertionError(('Overflow must reject without silently dropping text',paper,mode))
print('PASS',checks,'back-cover PDF text-retention and overflow checks')
