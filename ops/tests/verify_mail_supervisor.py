"""Exercise real disposable child processes, gate revocation and shutdown."""
from pathlib import Path
import importlib.util,sys,tempfile,time
source=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent.parent/'mail_supervisor.py'
spec=importlib.util.spec_from_file_location('mail_supervisor',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
checks=0
def check(value,label):
 global checks
 assert value,label
 checks+=1
with tempfile.TemporaryDirectory(prefix='neonrest-supervisor-') as tmp:
 root=Path(tmp);gate=root/'enabled'
 child="from pathlib import Path;import sys,time;Path(sys.argv[1]).write_text('started');time.sleep(20)"
 workers=[{'label':label,'command':[sys.executable,'-c',child,str(root/label)],'cwd':str(root),'enabled_file':str(gate) if label=='production' else None} for label in ('sandbox','production')]
 supervisor=module.Supervisor(workers,retry_seconds=.2)
 try:
  supervisor.step();time.sleep(.15)
  check('sandbox' in supervisor.children and supervisor.children['sandbox'].poll() is None,'Sandbox starts independently')
  check('production' not in supervisor.children and not (root/'production').exists(),'Production gate blocks start')
  health=root/'health.json';module.write_health(health,supervisor)
  import json
  snapshot=json.loads(health.read_text())
  check(snapshot['children']['sandbox']['running'] and 'production' not in snapshot['children'],'Shared heartbeat reports only running authorized children')
  check(health.stat().st_mode & 0o077==0,'Shared heartbeat remains private')
  gate.write_text('enabled');supervisor.step();time.sleep(.15)
  production=supervisor.children['production'];sandbox=supervisor.children['sandbox']
  check(production.poll() is None and sandbox.poll() is None,'Both environments run concurrently')
  sandbox.terminate();sandbox.wait();supervisor.step()
  check('sandbox' not in supervisor.children and production.poll() is None,'One worker failure leaves the other running')
  supervisor.step();check('sandbox' not in supervisor.children,'Restart backoff enforced')
  time.sleep(.25);supervisor.step();time.sleep(.15)
  check(supervisor.children['sandbox'].poll() is None and supervisor.children['sandbox'].pid!=sandbox.pid,'Failed worker restarts')
  gate.unlink();supervisor.step()
  check('production' not in supervisor.children and production.poll() is not None,'Production gate revocation stops only its child')
  check(supervisor.children['sandbox'].poll() is None,'Sandbox remains healthy after production stop')
  gate.symlink_to(root/'sandbox');supervisor.step();check('production' not in supervisor.children,'Symlink cannot activate production')
  final=supervisor.children['sandbox'];supervisor.close()
  check(final.poll() is not None and not supervisor.children,'Shutdown reaps every owned child')
  module.write_health(health,supervisor);check(json.loads(health.read_text())['stopping'] and not json.loads(health.read_text())['children'],'Shutdown heartbeat reports no live children')
 finally:supervisor.close()
print('PASS:',checks,'isolated dual-worker supervisor checks; no mail or live tasks changed')
