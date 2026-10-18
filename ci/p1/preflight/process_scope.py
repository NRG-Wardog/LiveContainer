"""Track every host child session; never index evidence while writers remain."""
import time
_CHILD_FIRST_PYTHON = time.monotonic()
# Child-only path avoids parent registry/diagnostic module imports.
# Parent ownership, registration and release protocol are unchanged.
if __name__=='__main__':
    import sys
    import launch_gate
    launch_gate._CHILD_FIRST_PYTHON=_CHILD_FIRST_PYTHON
    launch_gate.child_main(sys.argv[1:])
    raise SystemExit(125)

import json
import os
from pathlib import Path
import signal
import errno
import struct
import select
import math
import subprocess
import sys
import threading
import time
import uuid
_CHILD_IMPORTS_COMPLETE = time.monotonic()


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
    modify evidence. Cleanup attempts kill/wait for up to one extra second;
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
    try:os.killpg(group,kind);return True
    except ProcessLookupError:return False
    except OSError as error:raise GroupOperationError(signal.Signals(kind).name,group,error) from error


def require_default_sigchld():
    """PID reservation requires ordinary child reaping, never auto-reap handlers."""
    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise ValueError('default SIGCHLD disposition required for owned child lifecycle')


# The pipe is private to the gate child and parent. A successful exec closes the
# writer; neither the target nor descendants inherit it. No receipt is evidence
# that the target image started or that a service handled its request.
LAUNCH_RECORD = struct.Struct('!4sBqqq16sQdddddi')
LAUNCH_MAGIC = b'P1D1'


class LaunchReceiptError(RuntimeError):
    pass


class LaunchReceipt:
    def __init__(self, command, deadline, timeout):
        if sys.version_info < (3,10):
            raise ValueError('Python 3.10 or newer required for shared host monotonic clock')
        if type(command) is not int or not 0 < command < 2**64:
            raise ValueError('invalid launch command identity')
        self.command=command;self.deadline=deadline;self.timeout=timeout;self.fd=None;self.raw=bytearray();self.records=0;self.close_failed=False
        self.row={'schema':'p1-command-launch-v1','clock':'host-time-monotonic','command_id':f'command-{command:04d}',
                  'session':None,'pid':None,'deadline':deadline,
                  'popen':{'before':None,'after':None,'returned':False},
                  'registration':{'before':None,'after':None,'durable':False},
                  'release':{'before':None,'after':None,'issued':False},
                  'pre_exec':None,'exec_failure':None,'state':'unknown','reason':'not-started',
                  'eof':False,'closed':False,'target_execution_observed':False,'service_execution_observed':False}
    def reject(self, reason):
        # Keep the first fixed reason, and never rehabilitate invalid evidence.
        if self.row['reason'] in ['not-started','pending',None]:
            self.row.update(state='unknown',reason=reason)
    def bind(self, session, descriptor):
        if type(session) is not str or len(session)!=32 or any(c not in '0123456789abcdef' for c in session):
            raise ValueError('invalid launch session identity')
        self.session=bytes.fromhex(session);self.fd=descriptor
        self.row.update(session=session,reason='pending')
    def observe(self):
        if self.fd is None or self.row['eof'] or len(self.raw)>2*LAUNCH_RECORD.size:return
        # At most three nonblocking reads, 2 fixed records + 1 overflow byte in
        # total. This piggybacks on existing wait polls; no observer/thread/wait.
        for _ in range(3):
            before=time.monotonic()
            try:block=os.read(self.fd,2*LAUNCH_RECORD.size+1-len(self.raw))
            except BlockingIOError:return
            except OSError:self.reject('read-error');return
            after=time.monotonic()
            if not block:
                self.row['eof']=True
                if len(self.raw)%LAUNCH_RECORD.size:self.reject('partial-record')
                if self.records==0:self.reject('missing-pre-exec')
                return
            self.raw.extend(block)
            if after>self.deadline:self.reject('late-observation')
            if len(self.raw)>2*LAUNCH_RECORD.size:self.reject('size-limit');return
            while len(self.raw)>=(self.records+1)*LAUNCH_RECORD.size:
                start=self.records*LAUNCH_RECORD.size
                magic,kind,pid,pgid,sid,session,command,first_python,imports_complete,gate_enter,gate_exit,stamp,number=LAUNCH_RECORD.unpack(self.raw[start:start+LAUNCH_RECORD.size])
                self.records+=1
                if magic!=LAUNCH_MAGIC or kind not in [1,2]:self.reject('malformed-record')
                elif pid!=self.row['pid'] or pgid!=pid or sid!=pid or session!=self.session or command!=self.command:self.reject('wrong-identity')
                elif not all(math.isfinite(v) for v in [first_python,imports_complete,gate_enter,gate_exit,stamp]) or not self.row['popen']['before']<=first_python<=imports_complete<=gate_enter<=gate_exit<=stamp:self.reject('invalid-stage-time')
                elif self.row['release']['before'] is None or gate_exit<self.row['release']['before']:self.reject('gate-exited-before-release')
                elif kind==2 and self.row['pre_exec'] is not None and any(self.row['pre_exec'][k]!=v for k,v in [('first_python',first_python),('imports_complete',imports_complete),('gate_enter',gate_enter),('gate_exit',gate_exit)]):self.reject('stage-drift')
                elif not math.isfinite(stamp) or self.row['release']['before'] is None or not self.row['release']['before']<=stamp<=after or stamp>self.deadline:self.reject('invalid-time')
                elif (kind==1 and (self.records!=1 or number!=0)) or (kind==2 and (self.records!=2 or self.row['pre_exec'] is None or number<=0 or stamp<self.row['pre_exec']['child_monotonic'])):self.reject('invalid-order')
                if self.row['reason']!='pending':continue
                record={'first_python':first_python,'imports_complete':imports_complete,'gate_enter':gate_enter,'gate_exit':gate_exit,'child_monotonic':stamp,'observed_before':before,'observed_after':after}
                if kind==1:self.row['pre_exec']=record
                else:self.row['exec_failure']={**record,'errno':number}
    def finish(self):
        if self.row['closed']:return
        try:
            self.observe()
            if not self.row['eof']:self.reject('unresolved-writer')
            if self.row['reason']=='pending':self.row.update(state='pre-exec-observed',reason=None)
        finally:
            if self.fd is not None:
                try:os.close(self.fd)
                except OSError:self.close_failed=True;self.reject('close-error')
                self.fd=None
            self.row['closed']=not self.close_failed
    def require(self):
        if self.row['state']!='pre-exec-observed' or not self.row['closed']:
            raise LaunchReceiptError('command launch observation unknown')


class OwnedProcess:
    """One start_new_session=True Popen child, with serialized reaping/signals.

    An unreaped child reserves its PID. After reaping, the numeric PGID alone
    cannot authorize signals. The wrapper retains the actual Popen object and
    all callers use its lifecycle lock rather than waiting on the raw child.
    """
    @classmethod
    def spawn(cls,*args,**kwargs):
        require_default_sigchld()
        if kwargs.get('start_new_session') is not True:
            raise ValueError('owned child must start its own session')
        return cls(subprocess.Popen(*args,**kwargs))
    def __init__(self,process):
        self._process=process;self.lock=threading.RLock();self.pid=process.pid;self.launch=None
    @property
    def returncode(self):
        with self.lock:return self._process.returncode
    def poll(self):
        with self.lock:return self._process.poll()
    def wait(self,timeout=None):
        deadline=None if timeout is None else time.monotonic()+timeout
        while True:
            with self.lock:
                if self.launch is not None:self.launch.observe()
                code=self._process.poll()
                if code is not None:return code
            if deadline is not None and time.monotonic()>=deadline:
                raise subprocess.TimeoutExpired(self._process.args,timeout)
            time.sleep(.01 if deadline is None else min(.01,max(0,deadline-time.monotonic())))
    def signal_owned(self,kind):
        with self.lock:
            require_default_sigchld()
            if self._process.poll() is not None:return False
            # No other waiter can reap the child between this poll and signal.
            return signal_group(self.pid,kind)


def disappearance(group):
    """Read-only. A surviving, reused or unknown numeric group is not killed."""
    deadline=time.monotonic()+5
    while alive(group) and time.monotonic()<deadline:time.sleep(.02)
    settled=not alive(group)
    if not settled:emit_diagnostic('process-group-unsettled',pgid=group,operation='disappearance',result=False,membership=membership_snapshot(group))
    return settled


def stop_group(group,process=None):
    if process is None:return disappearance(group)
    if not isinstance(process,OwnedProcess) or process.pid!=group:
        raise ValueError('exact owned child required for process-group signals')
    try:
        with process.lock:
            # Reap exited direct children before a Darwin killpg(0) probe can
            # fail on a zombie. Unknown probe failures remain failures.
            code=process.poll()
            if code is None and alive(group):process.signal_owned(signal.SIGTERM)
        if code is None:
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.signal_owned(signal.SIGKILL)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    emit_diagnostic('process-group-unsettled',pgid=group,operation='wait',result=False,membership=membership_snapshot(group));return False
        return disappearance(group)
    except OSError as error:
        try:process.poll()
        except Exception as reap_error:emit_diagnostic('owned-child-reap-failure',pgid=group,error=error_info(reap_error))
        if isinstance(error,GroupOperationError):raise
        raise GroupOperationError('wait',group,error) from error
    finally:
        emit_diagnostic('owned-child-lifecycle',pgid=group,reaped=process.returncode is not None,exit_code=process.returncode)


class Scope:
    def __init__(self,root,seconds=1020,gate_mode='full',stall_diagnostic=False):
        if gate_mode not in ('full','minimal'):raise ValueError('fixed gate mode required')
        self.gate_mode=gate_mode
        if seconds!=1020:raise ValueError('fixed 17-minute internal deadline required')
        self.root=root;self.path=root/'process-registry.json';self.lock=threading.RLock();self.processes={};self.rows=[]
        self.session=os.environ.get('P1_PROCESS_SCOPE_SESSION') or uuid.uuid4().hex
        started=time.monotonic()
        self.deadline=started+(360 if stall_diagnostic else seconds);self.cleanup_deadline=started+480 if stall_diagnostic else None
        self.closing=False;self.fixture=None
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
    def fixture_cleanup_failure(self):
        with self.lock:
            if self.fixture is not None:self.fixture['cleanup_command_failed']=True;self.persist()
    def remaining(self,requested,cleanup=False):
        if cleanup:
            left=15 if self.cleanup_deadline is None else self.cleanup_deadline-time.monotonic()
            if left<=0:raise TimeoutError('diagnostic cleanup reserve exhausted')
            return min(float(requested),15,left)
        left=self.deadline-time.monotonic()
        if left<=0 or self.closing:raise TimeoutError('internal collector deadline reached')
        return min(float(requested),left)
    def spawn(self,argv,stdout,stderr=None,cleanup=False,launch=None):
        with self.lock:
            self.remaining(1,cleanup)
            require_default_sigchld()
            read_fd=write_fd=receipt_read=receipt_write=None;process=None;row=None
            try:
                read_fd,write_fd=os.pipe()
                gate=Path(__file__).resolve() if self.gate_mode=='full' else Path(__file__).resolve().with_name('minimal_gate.py')
                child=[sys.executable,'-B',str(gate),'--child',str(read_fd)]
                inherited=(read_fd,)
                if launch is not None:
                    receipt_read,receipt_write=os.pipe()
                    os.set_blocking(receipt_read,False);os.set_blocking(receipt_write,False)
                    launch.bind(self.session,receipt_read);receipt_read=None
                    child+=['--launch-receipt',str(receipt_write),self.session,str(launch.command)]
                    inherited+=(receipt_write,)
                    launch.row['popen']['before']=time.monotonic()
                try:
                    process=OwnedProcess.spawn([*child,*map(str,argv)],stdout=stdout,stderr=stderr if stderr is not None else stdout,start_new_session=True,pass_fds=inherited)
                    if launch is not None:launch.row['popen']['returned']=True;launch.row['pid']=process.pid
                finally:
                    if launch is not None:launch.row['popen']['after']=time.monotonic()
                # Retain exact ownership before any fallible parent close.
                process.launch=launch
                self.processes[process.pid]=process
                row={'pid':process.pid,'pgid':process.pid,'argv':list(map(str,argv)),'started':time.monotonic(),'settled':False,'exit_code':None}
                self.rows.append(row)
                if launch is not None:row['launch_receipt']=launch.row
                try:
                    descriptor,read_fd=read_fd,None;os.close(descriptor)
                    if receipt_write is not None:
                        descriptor,receipt_write=receipt_write,None;os.close(descriptor)
                    if launch is not None:launch.row['registration']['before']=time.monotonic()
                    try:
                        self.persist()
                        if launch is not None:launch.row['registration']['durable']=True
                    finally:
                        if launch is not None:launch.row['registration']['after']=time.monotonic()
                    # The original command deadline includes launch/registration;
                    # expiry never releases the child or grants a new wait.
                    if launch is not None:
                        if time.monotonic()>=launch.deadline:raise subprocess.TimeoutExpired(argv,launch.timeout)
                        launch.row['release']['before']=time.monotonic()
                    try:
                        if os.write(write_fd,b'G')!=1:raise OSError(errno.EIO,'launch gate release failed')
                        if launch is not None:launch.row['release']['issued']=True
                    finally:
                        if launch is not None:launch.row['release']['after']=time.monotonic()
                    descriptor,write_fd=write_fd,None;os.close(descriptor)
                except Exception as error:
                    row['primary_error']=error_info(error)
                    emit_diagnostic('spawn-registration-failure',pgid=process.pid,primary_error=error_info(error))
                    try:
                        settled=stop_group(process.pid,process)
                        # Failed registration still requires Scope.close to
                        # reverify/persist it; optional commands cannot proceed.
                        row.update(spawn_cleanup_settled=settled,reaped=process.returncode is not None,exit_code=process.returncode)
                        if not settled:raise RuntimeError('spawn child settlement unproved')
                    except Exception as cleanup_error:
                        row.setdefault('cleanup_errors',[]).append(error_info(cleanup_error))
                        emit_diagnostic('spawn-cleanup-failure',pgid=process.pid,cleanup_error=error_info(cleanup_error))
                    raise
                return process
            except Exception:
                if launch is not None:
                    try:launch.finish()
                    except Exception as observer_error:
                        if row is not None:row.setdefault('cleanup_errors',[]).append(error_info(observer_error))
                        emit_diagnostic('spawn-observer-failure',error=error_info(observer_error))
                raise
            finally:
                for descriptor in [read_fd,write_fd,receipt_read,receipt_write]:
                    if descriptor is not None:
                        try:os.close(descriptor)
                        except OSError as close_error:
                            # Only failure paths retain descriptors here. Never
                            # replace their primary error or retry an uncertain
                            # close using a possibly reused numeric descriptor.
                            if row is not None:row.setdefault('cleanup_errors',[]).append(error_info(close_error))
                            emit_diagnostic('spawn-descriptor-close-failure',error=error_info(close_error))
    def settle(self,process):
        with self.lock:
            row=next(r for r in self.rows if r['pid']==process.pid)
            if row['settled']:return
            try:settled=stop_group(process.pid,process)
            except Exception as error:
                row['settled']=False;row['exit_code']=process.returncode;row['reaped']=process.returncode is not None
                row.setdefault('cleanup_errors',[]).append(error_info(error));row['cleanup_errors']=row['cleanup_errors'][-8:]
                try:self.persist()
                except Exception as write_error:emit_diagnostic('registry-write-failure',error=error_info(write_error))
                raise
            row.update(settled=settled,exit_code=process.returncode,reaped=process.returncode is not None,finished=time.monotonic());self.persist()
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
        name=f'command-{number:04d}';started=time.monotonic();primary=None;cleanup_failures=[];process=None;writer_settled=False
        launch=LaunchReceipt(number,started+limit if cleanup else min(started+limit,self.scope.deadline),limit)
        print('Running: '+' '.join(argv),flush=True)
        with (self.output/(name+'.stdout')).open('wb') as out,(self.output/(name+'.stderr')).open('wb') as err:
            try:
                process=self.scope.spawn(argv,out,err,cleanup=cleanup,launch=launch)
                process.wait(timeout=max(0,launch.deadline-time.monotonic()))
                if time.monotonic()>launch.deadline:raise subprocess.TimeoutExpired(argv,limit)
                if process.returncode:raise subprocess.CalledProcessError(process.returncode,argv)
            except Exception as error:primary=error
            finally:
                try:
                    launch.finish()
                    if process is not None:launch.require()
                except Exception as error:cleanup_failures.append(error)
                if process is not None:
                    try:
                        self.scope.settle(process);writer_settled=True
                    except Exception as error:cleanup_failures.append(error)
        error=primary or (cleanup_failures[0] if cleanup_failures else None)
        primary_row=error_info(primary);cleanup_rows=[error_info(e) for e in cleanup_failures]
        row={'argv':argv,'timeoutSeconds':limit,'seconds':time.monotonic()-started,'exit_code':process.returncode if process else None,
             'stdout':name+'.stdout','stderr':name+'.stderr','error':str(error) if error else None,'allowed_failure':allow_failure,'cleanup':cleanup,
             'primary_error':primary_row,'cleanup_errors':cleanup_rows,'launch_receipt':launch.row}
        if error:
            emit_diagnostic('command-failure',command_id=name,pgid=process.pid if process else None,exit_code=row['exit_code'],
                            timeout_seconds=limit,elapsed_seconds=row['seconds'],primary_error=primary_row,cleanup_errors=cleanup_rows,
                            launch_receipt=launch.row)
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
                           'writer_settled':writer_settled,
                           'command_id':name,'primary_error':primary_row,'cleanup_errors':cleanup_rows,'launch_receipt':launch.row}
        if error and not allow_failure:raise error
        return data.decode(errors='replace').strip()

    def bytes(self,*args,timeout=300):return self(*args,timeout=timeout).encode()


def child_main(args):
    if len(args)<3 or args[0]!='--child':raise SystemExit('private launch gate requires exact child arguments')
    descriptor=int(args[1]);target=args[2:];receipt=None
    if target[0]=='--launch-receipt':
        receipt=int(target[1]);session=bytes.fromhex(target[2]);command=int(target[3]);target=target[4:]
        os.set_inheritable(receipt,False)
    gate_enter=time.monotonic()
    signal_byte=os.read(descriptor,1);gate_exit=time.monotonic();os.close(descriptor)
    if signal_byte!=b'G':os._exit(125)
    def emit(kind,number):
        try:
            record=LAUNCH_RECORD.pack(LAUNCH_MAGIC,kind,os.getpid(),os.getpgrp(),os.getsid(0),session,command,_CHILD_FIRST_PYTHON,_CHILD_IMPORTS_COMPLETE,gate_enter,gate_exit,time.monotonic(),number)
            return os.write(receipt,record)==len(record)
        except (OSError,ValueError,struct.error):return False
    if receipt is None:os.execvp(target[0],target)
    if not emit(1,0):os._exit(125)
    try:os.execvp(target[0],target)
    except OSError as error:
        if receipt is not None:emit(2,error.errno if type(error.errno) is int and error.errno>0 else errno.EIO)
        os._exit(126)
    except (ValueError,IndexError):
        if receipt is not None:emit(2,errno.EINVAL)
        os._exit(126)


if __name__=='__main__':child_main(sys.argv[1:])
