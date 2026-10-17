"""Track every host child session; never index evidence while writers remain."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid


def atomic(path,value):
    tmp=path.with_suffix('.pending')
    with tmp.open('w') as f:
        f.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
    tmp.replace(path)
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def alive(group):
    try:os.killpg(group,0);return True
    except ProcessLookupError:return False


def stop_group(group,process=None):
    if alive(group):
        try:os.killpg(group,signal.SIGTERM)
        except ProcessLookupError:pass
        deadline=time.monotonic()+2
        while alive(group) and time.monotonic()<deadline:
            if process is not None:process.poll()
            time.sleep(.02)
    if alive(group):
        try:os.killpg(group,signal.SIGKILL)
        except ProcessLookupError:pass
    if process is not None:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:return False
    deadline=time.monotonic()+5
    while alive(group) and time.monotonic()<deadline:time.sleep(.02)
    return not alive(group)


class Scope:
    def __init__(self,root,seconds=1020):
        if seconds!=1020:raise ValueError('fixed 17-minute internal deadline required')
        self.root=root;self.path=root/'process-registry.json';self.lock=threading.RLock();self.processes={};self.rows=[]
        self.session=os.environ.get('P1_PROCESS_SCOPE_SESSION') or uuid.uuid4().hex
        self.deadline=time.monotonic()+seconds;self.closing=False;self.fixture=None
        if self.path.exists():raise ValueError('fresh process registry required')
        self.persist()
    def persist(self):
        atomic(self.path,{'schema':'p1-capability-process-scope-v1','session':self.session,'collector_pid':os.getpid(),'deadline':self.deadline,'closing':self.closing,'fixture':self.fixture,'groups':self.rows,'admissionEligible':False})
    def fixture_identity(self,device,owned_boot):
        with self.lock:
            self.fixture={'device':device,'owned_boot':owned_boot,'stopped':False,'bundle_ids':['org.sidestore.fixture.p1video','org.sidestore.fixture.p1video.uitests.xctrunner']};self.persist()
    def fixture_stopped(self,stopped):
        with self.lock:
            if self.fixture is not None:self.fixture['stopped']=bool(stopped);self.persist()
    def remaining(self,requested,cleanup=False):
        if cleanup:return min(float(requested),15)
        left=self.deadline-time.monotonic()
        if left<=0 or self.closing:raise TimeoutError('internal collector deadline reached')
        return min(float(requested),left)
    def spawn(self,argv,stdout,stderr=None,cleanup=False):
        with self.lock:
            self.remaining(1,cleanup)
            read_fd,write_fd=os.pipe()
            try:
                process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--child',str(read_fd),*map(str,argv)],stdout=stdout,stderr=stderr if stderr is not None else stdout,start_new_session=True,pass_fds=(read_fd,))
            finally:os.close(read_fd)
            self.processes[process.pid]=process
            self.rows.append({'pid':process.pid,'pgid':process.pid,'argv':list(map(str,argv)),'started':time.monotonic(),'settled':False,'exit_code':None})
            try:
                self.persist()
                # Child cannot execute or write evidence until its group is in
                # the durable registry. Parent death before release closes pipe.
                os.write(write_fd,b'G')
            except Exception:
                stop_group(process.pid,process);raise
            finally:os.close(write_fd)
            return process
    def settle(self,process):
        with self.lock:
            row=next(r for r in self.rows if r['pid']==process.pid)
            if row['settled']:return
            settled=stop_group(process.pid,process)
            row.update(settled=settled,exit_code=process.returncode,finished=time.monotonic());self.persist()
            if not settled:raise RuntimeError('child group did not become quiescent')
    def close(self):
        with self.lock:
            self.closing=True;self.persist();ok=True
            for process in list(self.processes.values()):
                try:self.settle(process)
                except Exception:ok=False
            ok=ok and (self.fixture is None or self.fixture.get('stopped') is True)
            atomic(self.root/'quiescence.json',{'schema':'p1-capability-quiescence-v1','session':self.session,'quiescent':ok and all(r['settled'] for r in self.rows),'groups':len(self.rows),'admissionEligible':False})
            if not ok:raise RuntimeError('host writer quiescence unproved')


class Commands:
    def __init__(self,scope,output):self.scope=scope;self.output=output;self.count=0;self.lock=threading.Lock()
    def __call__(self,*args,timeout=300,allow_failure=False,cleanup=False,receipt=False):
        argv=list(map(str,args));limit=self.scope.remaining(timeout,cleanup)
        with self.lock:self.count+=1;number=self.count
        name=f'command-{number:04d}';started=time.monotonic();error=None;process=None
        print('Running: '+' '.join(argv),flush=True)
        with (self.output/(name+'.stdout')).open('wb') as out,(self.output/(name+'.stderr')).open('wb') as err:
            try:
                process=self.scope.spawn(argv,out,err,cleanup=cleanup)
                process.wait(timeout=limit)
                if process.returncode:raise subprocess.CalledProcessError(process.returncode,argv)
            except Exception as exc:error=exc
            finally:
                if process is not None:
                    try:self.scope.settle(process)
                    except Exception as exc:error=exc
        with self.lock:
            with (self.output/'commands.jsonl').open('a') as f:f.write(json.dumps({'argv':argv,'timeoutSeconds':limit,'seconds':time.monotonic()-started,'exit_code':process.returncode if process else None,'stdout':name+'.stdout','stderr':name+'.stderr','error':str(error) if error else None,'allowed_failure':allow_failure,'cleanup':cleanup})+'\n')
        data=(self.output/(name+'.stdout')).read_bytes()
        if receipt:return {'argv':argv,'exit_code':process.returncode if process else None,'stdout':data.decode(errors='replace'),'stderr':(self.output/(name+'.stderr')).read_text(errors='replace'),'failure_type':type(error).__name__ if error else None,'command_id':name}
        if error and not allow_failure:raise error
        return data.decode(errors='replace').strip()

    def bytes(self,*args,timeout=300):return self(*args,timeout=timeout).encode()


if __name__=='__main__':
    if len(sys.argv)<4 or sys.argv[1]!='--child':raise SystemExit('private launch gate requires exact child arguments')
    descriptor=int(sys.argv[2]);signal_byte=os.read(descriptor,1);os.close(descriptor)
    if signal_byte!=b'G':raise SystemExit(125)
    os.execvp(sys.argv[3],sys.argv[3:])
