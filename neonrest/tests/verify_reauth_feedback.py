from pathlib import Path
import ast,textwrap,time,sys
from types import SimpleNamespace
p=Path(sys.argv[1])/'community_features.py'
candidate=p.read_text()
node=next(n for n in ast.walk(ast.parse(candidate)) if isinstance(n,ast.FunctionDef) and n.name=='community_reauth')
fn=textwrap.dedent(ast.get_source_segment(candidate,node))
for password,factor,code,expected in [('bad',True,True,'password'),('ok',True,False,'code'),('ok',True,True,'success'),('ok',False,False,'success'),('x'*129,True,True,'password')]:
 flashes=[]; calls=[]; session={}
 env=dict(current_user=lambda:dict(id=1,password_hash='fake'),request=SimpleNamespace(args={},method='POST',form=dict(password=password,code='synthetic'),script_root=''),csrf=lambda:calls.append('csrf'),check_password_hash=lambda h,v:v=='ok',second_factor=lambda uid:factor,verify_second_factor=lambda *args:calls.append('factor') or code,get_db=lambda:None,session=session,time=time,redirect=lambda x:('redirect',x),flash=lambda msg,cat:flashes.append(msg),render=lambda *args,**kw:'render')
 exec(fn,env); result=env['community_reauth']()
 assert calls[0]=='csrf'
 if expected=='password': assert flashes==['Your password does not match.'] and 'factor' not in calls and not session
 elif expected=='code': assert len(flashes)==1 and 'code was not accepted' in flashes[0] and not session
 else: assert result==('redirect','/account/security') and 'fresh_at' in session and not flashes
print('PASS: five confirmation branches, CSRF ordering, password short-circuit, and freshness behavior')
