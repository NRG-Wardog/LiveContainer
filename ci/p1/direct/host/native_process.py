"""Concurrent retained Commands adapter, with no PID rediscovery or new kill policy.

The existing Scope owns spawn, launch receipt, signal checks and settlement.
This wrapper retains the exact returned OwnedProcess solely for bounded early
cleanup. A pending spawn remains an unresolved ownership obligation.
"""
from pathlib import Path
import signal
import threading
import time
from fixture_channel import require,canonical


def clean(row,argv):
    require(type(row) is dict and row.get('argv')==list(map(str,argv)), 'command argv binding')
    launch=row.get('launch_receipt',{})
    require(row.get('exit_code')==0 and row.get('failure_type') is None and row.get('primary_error') is None and
            row.get('writer_settled') is True and not row.get('cleanup_errors'), 'native command failed or unsettled')
    require(launch.get('state')=='pre-exec-observed' and launch.get('closed') is True and launch.get('eof') is True and
            launch.get('exec_failure') is None, 'native launch evidence unknown')
    return row


class RetainedCommand:
    def __init__(self,scope,commands_type,folder,argv,*,timeout,retain):
        require(type(timeout) in (int,float) and 0<timeout<=360,'bounded native command')
        self.scope=scope;self.folder=Path(folder);self.argv=tuple(map(str,argv));self.timeout=timeout;self.retain=retain
        self.process=None;self.row=None;self.error=None;self.thread=None;self.finished=threading.Event()
        self.folder.mkdir();owner=self
        class BoundScope:
            def __getattr__(self,name):return getattr(scope,name)
            def spawn(self,argv,*args,**kwargs):
                require(list(map(str,argv))==list(owner.argv),'unexpected owned command')
                value=scope.spawn(argv,*args,**kwargs)
                require(owner.process is None,'multiple spawn attempt')
                owner.process=value
                return value
        self.command=commands_type(BoundScope(),self.folder)
    def start(self):
        require(self.thread is None,'single command attempt')
        def run():
            try:
                self.row=self.command(*self.argv,timeout=self.timeout,receipt=True)
                self.retain(canonical(self.row))
            except BaseException as error:self.error=error
            finally:self.finished.set()
        # The enclosing process Scope/watchdog owns pending descendants. No
        # executor context manager may silently wait beyond cleanup's deadline.
        self.thread=threading.Thread(target=run,name='p1-owned-native-command',daemon=True);self.thread.start()
    def live(self):
        require(self.thread is not None,'command not started')
        require(not self.finished.is_set(),'native command ended before prerequisite')
        if self.process is not None:
            require(self.scope.processes.get(self.process.pid) is self.process,'retained native owner lost')
            require(self.process.poll() is None,'native command exited')
    def result(self,timeout):
        require(self.thread is not None and 0<timeout<=360,'bounded result wait')
        deadline=time.monotonic()+timeout
        require(self.finished.wait(timeout),'native result deadline')
        self.thread.join(timeout=max(0,deadline-time.monotonic()))
        require(not self.thread.is_alive(),'native receipt writer unsettled')
        if self.error is not None:raise self.error
        return clean(self.row,self.argv)
    def stop(self,timeout):
        require(0<timeout<=15,'bounded native stop')
        deadline=time.monotonic()+timeout
        if self.thread is None:return {'started':False,'settled':True}
        if not self.finished.is_set():
            process=self.process
            require(process is not None,'spawn pending: retained ownership unavailable')
            require(self.scope.processes.get(process.pid) is process,'cleanup owner changed')
            process.signal_owned(signal.SIGTERM)
        require(self.finished.wait(max(0,deadline-time.monotonic())),'owned command cleanup deadline')
        self.thread.join(timeout=max(0,deadline-time.monotonic()));require(not self.thread.is_alive(),'owned receipt writer still active')
        if self.error is not None:raise self.error
        require(type(self.row) is dict and self.row.get('writer_settled') is True,'owned command settlement unproved')
        # Stopping safely never converts its primary timeout/nonzero to success.
        return {'started':True,'settled':True,'receipt':self.row}
