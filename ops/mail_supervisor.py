"""Run isolated mail workers under one managed parent; no web-request subprocesses."""
import argparse,fcntl,json,os,signal,subprocess,time
from pathlib import Path

def write_health(path, supervisor):
    path=Path(path)
    if path.is_symlink():raise RuntimeError('Unsafe supervisor health path')
    temporary=path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'heartbeat':int(time.time()),'stopping':supervisor.stopping,
                   'children':{label:{'pid':child.pid,'running':child.poll() is None}
                               for label,child in supervisor.children.items()}},stream)
    os.replace(temporary,path)

class Supervisor:
    def __init__(self, workers, retry_seconds=10):
        self.workers=workers;self.retry_seconds=retry_seconds
        self.children={};self.retry_after={};self.stopping=False

    def enabled(self, worker):
        gate=worker.get('enabled_file')
        return not gate or (Path(gate).is_file() and not Path(gate).is_symlink())

    def stop_child(self, label):
        child=self.children.pop(label,None)
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)

    def step(self, now=None):
        now=time.monotonic() if now is None else now
        for worker in self.workers:
            label=worker['label'];child=self.children.get(label)
            if not self.enabled(worker):
                self.stop_child(label);continue
            if child and child.poll() is not None:
                self.children.pop(label,None);self.retry_after[label]=now+self.retry_seconds
                print(label+' mail worker exited; restart delayed',flush=True);child=None
            if not child and now>=self.retry_after.get(label,0):
                try:
                    self.children[label]=subprocess.Popen(worker['command'],cwd=worker['cwd'],
                        env=dict(os.environ,**worker.get('environment',{})),stdin=subprocess.DEVNULL)
                except OSError:
                    self.retry_after[label]=now+self.retry_seconds
                    print(label+' mail worker could not start; retry delayed',flush=True)

    def close(self):
        self.stopping=True
        for label in list(self.children):self.stop_child(label)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    path=Path(args.config)
    if path.is_symlink() or path.stat().st_mode & 0o077:raise RuntimeError('Supervisor configuration must be private')
    config=json.loads(path.read_text());workers=config['workers']
    if len({w['label'] for w in workers})!=len(workers):raise ValueError('Duplicate worker labels')
    for w in workers:
        if w['label'] not in ('sandbox','production'):raise ValueError('Unknown worker')
        if not isinstance(w['command'],list) or not w['command'] or not all(isinstance(v,str) for v in w['command']):raise ValueError('Invalid worker command')
        if not Path(w['command'][0]).is_absolute() or not Path(w['cwd']).is_absolute():raise ValueError('Absolute command and working directory required')
    lock=Path(config['lock']);lock.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if lock.is_symlink():raise RuntimeError('Unsafe supervisor lock')
    fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Mail supervisor already running')
        supervisor=Supervisor(workers)
        def stop(signum,frame):supervisor.stopping=True
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        try:
            while not supervisor.stopping:
                supervisor.step();write_health(path.with_name('supervisor-health.json'),supervisor);time.sleep(1)
        finally:
            supervisor.close();write_health(path.with_name('supervisor-health.json'),supervisor)
    finally:os.close(fd)

if __name__=='__main__':main()
