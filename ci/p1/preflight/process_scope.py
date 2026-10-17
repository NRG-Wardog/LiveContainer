"""Track every host child session; never index evidence while writers remain."""
import json
import os
from pathlib import Path
import signal
import select
import math
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


def emit_diagnostic(phase, **fields):
    """Bounded transport-independent metadata, never a stable evidence claim."""
    row={'schema':'p1-capability-console-diagnostic-v1','phase':phase,'admissionEligible':False,**fields}
    try:
        encoded=json.dumps(row,sort_keys=True,allow_nan=False)
        if len(encoded)>32768:encoded=json.dumps({'schema':row['schema'],'phase':phase,'admissionEligible':False,'diagnostic_truncated':True})
        print('P1_CAPABILITY_DIAGNOSTIC '+encoded,flush=True)
    except (OSError,ValueError):pass  # Diagnostic failure must not replace the primary failure.


def error_info(error):
    if error is None:return None
    if isinstance(error,GroupOperationError):return dict(error.diagnostic)
    row={'type':type(error).__name__}
    if isinstance(error,OSError) and type(error.errno) is int:row['errno']=error.errno
    if isinstance(error,subprocess.TimeoutExpired):
        if isinstance(error.timeout,(int,float)) and math.isfinite(error.timeout):row['timeout_seconds']=error.timeout
    if isinstance(error,subprocess.CalledProcessError):row['returncode']=error.returncode
    # Never serialize arbitrary exception arguments, full command lines or environment.
    return row


def membership_snapshot(group):
    """One read-only ps snapshot: 1 s collection, 1 s cleanup, 256 KiB/32 rows.

    ps inherits this process group, has no evidence file descriptor and cannot
    modify evidence. Its direct child is killed/waited on before returning;
    a failed wait is explicitly unknown, never a quiescence receipt.
    """
    result={'available':False,'pgid':group,'rows':[],'truncated':False}
    process=None;raw=bytearray();limit=256*1024;deadline=time.monotonic()+1
    try:
        process=subprocess.Popen(['/bin/ps','-axo','pid=,ppid=,pgid=,uid=,state=,comm='],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        while True:
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError('membership snapshot deadline')
            readable,_,_=select.select([process.stdout],[],[],left)
            if not readable:raise TimeoutError('membership snapshot deadline')
            block=os.read(process.stdout.fileno(),min(65536,limit+1-len(raw)))
            if not block:break
            raw.extend(block)
            if len(raw)>limit:raise ValueError('membership snapshot output bound')
        process.wait(timeout=max(.001,deadline-time.monotonic()))
        if process.returncode:raise subprocess.CalledProcessError(process.returncode,['ps'])
        for line in raw.decode('utf-8',errors='replace').splitlines():
            parts=line.split(None,5)
            if len(parts)!=6:continue
            try:pid,ppid,pgid,uid=map(int,parts[:4])
            except ValueError:continue
            if pgid!=group:continue
            if len(result['rows'])>=32:result['truncated']=True;continue
            safe=lambda value,bound:''.join(c if 32<=ord(c)<127 else '?' for c in value)[:bound]
            result['rows'].append({'pid':pid,'ppid':ppid,'pgid':pgid,'uid':uid,'state':safe(parts[4],16),'comm':safe(parts[5],160)})
        result['available']=True
    except Exception as error:result['error']=error_info(error)
    finally:
        if process is not None:
            try:
                if process.poll() is None:process.kill()
                process.wait(timeout=1)
            except Exception as error:result['available']=False;result['cleanup_error']=error_info(error)
            if process.stdout is not None:process.stdout.close()
    return result


class GroupOperationError(OSError):
    def __init__(self,operation,group,error):
        super().__init__(getattr(error,'errno',None),'owned process-group operation failed')
        self.diagnostic={'type':type(error).__name__,'operation':operation,'pgid':group,
                         'errno':getattr(error,'errno',None),'membership':membership_snapshot(group)}
        emit_diagnostic('process-group-failure',error=self.diagnostic)


def alive(group):
    try:os.killpg(group,0);return True
    except ProcessLookupError:return False
    except OSError as error:raise GroupOperationError('probe',group,error) from error


def signal_group(group,kind):
    try:os.killpg(group,kind)
    except ProcessLookupError:pass
    except OSError as error:raise GroupOperationError(signal.Signals(kind).name,group,error) from error


def stop_group(group,process=None):
    if alive(group):
        signal_group(group,signal.SIGTERM)
        deadline=time.monotonic()+2
        while alive(group) and time.monotonic()<deadline:
            if process is not None:process.poll()
            time.sleep(.02)
    if alive(group):signal_group(group,signal.SIGKILL)
    if process is not None:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            emit_diagnostic('process-group-unsettled',pgid=group,operation='wait',result=False,membership=membership_snapshot(group));return False
        except OSError as error:raise GroupOperationError('wait',group,error) from error
    deadline=time.monotonic()+5
    while alive(group) and time.monotonic()<deadline:time.sleep(.02)
    settled=not alive(group)
    if not settled:emit_diagnostic('process-group-unsettled',pgid=group,operation='disappearance',result=False,membership=membership_snapshot(group))
    return settled


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
            except Exception as error:
                self.rows[-1]['primary_error']=error_info(error)
                emit_diagnostic('spawn-registration-failure',pgid=process.pid,primary_error=error_info(error))
                try:stop_group(process.pid,process)
                except Exception as cleanup_error:
                    self.rows[-1].setdefault('cleanup_errors',[]).append(error_info(cleanup_error))
                    emit_diagnostic('spawn-cleanup-failure',pgid=process.pid,cleanup_error=error_info(cleanup_error))
                raise
            finally:os.close(write_fd)
            return process
    def settle(self,process):
        with self.lock:
            row=next(r for r in self.rows if r['pid']==process.pid)
            if row['settled']:return
            try:settled=stop_group(process.pid,process)
            except Exception as error:
                row['settled']=False;row['exit_code']=process.returncode
                row.setdefault('cleanup_errors',[]).append(error_info(error));row['cleanup_errors']=row['cleanup_errors'][-8:]
                try:self.persist()
                except Exception as write_error:emit_diagnostic('registry-write-failure',error=error_info(write_error))
                raise
            row.update(settled=settled,exit_code=process.returncode,finished=time.monotonic());self.persist()
            if not settled:
                emit_diagnostic('process-group-unsettled',pgid=process.pid,operation='settle',result=False)
                raise RuntimeError('child group did not become quiescent')
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
        name=f'command-{number:04d}';started=time.monotonic();primary=None;cleanup_failures=[];process=None
        print('Running: '+' '.join(argv),flush=True)
        with (self.output/(name+'.stdout')).open('wb') as out,(self.output/(name+'.stderr')).open('wb') as err:
            try:
                process=self.scope.spawn(argv,out,err,cleanup=cleanup)
                process.wait(timeout=limit)
                if process.returncode:raise subprocess.CalledProcessError(process.returncode,argv)
            except Exception as error:primary=error
            finally:
                if process is not None:
                    try:self.scope.settle(process)
                    except Exception as error:cleanup_failures.append(error)
        error=primary or (cleanup_failures[0] if cleanup_failures else None)
        primary_row=error_info(primary);cleanup_rows=[error_info(e) for e in cleanup_failures]
        row={'argv':argv,'timeoutSeconds':limit,'seconds':time.monotonic()-started,'exit_code':process.returncode if process else None,
             'stdout':name+'.stdout','stderr':name+'.stderr','error':str(error) if error else None,'allowed_failure':allow_failure,'cleanup':cleanup,
             'primary_error':primary_row,'cleanup_errors':cleanup_rows}
        if error:
            emit_diagnostic('command-failure',command_id=name,pgid=process.pid if process else None,exit_code=row['exit_code'],
                            timeout_seconds=limit,elapsed_seconds=row['seconds'],primary_error=primary_row,cleanup_errors=cleanup_rows)
        try:
            with self.lock:
                with (self.output/'commands.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        except Exception as write_error:
            emit_diagnostic('command-receipt-write-failure',command_id=name,error=error_info(write_error),primary_error=primary_row,cleanup_errors=cleanup_rows)
            if error is not None:raise error
            raise
        data=(self.output/(name+'.stdout')).read_bytes()
        if receipt:return {'argv':argv,'exit_code':process.returncode if process else None,'stdout':data.decode(errors='replace'),
                           'stderr':(self.output/(name+'.stderr')).read_text(errors='replace'),'failure_type':type(error).__name__ if error else None,
                           'command_id':name,'primary_error':primary_row,'cleanup_errors':cleanup_rows}
        if error and not allow_failure:raise error
        return data.decode(errors='replace').strip()

    def bytes(self,*args,timeout=300):return self(*args,timeout=timeout).encode()


if __name__=='__main__':
    if len(sys.argv)<4 or sys.argv[1]!='--child':raise SystemExit('private launch gate requires exact child arguments')
    descriptor=int(sys.argv[2]);signal_byte=os.read(descriptor,1);os.close(descriptor)
    if signal_byte!=b'G':raise SystemExit(125)
    os.execvp(sys.argv[3],sys.argv[3:])
