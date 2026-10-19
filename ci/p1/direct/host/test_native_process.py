import tempfile,unittest,time,threading
from pathlib import Path
from native_process import RetainedCommand,clean

def row(argv):return dict(argv=list(argv),exit_code=0,failure_type=None,primary_error=None,writer_settled=True,cleanup_errors=[],launch_receipt=dict(state='pre-exec-observed',closed=True,eof=True,exec_failure=None))
class Process:
    pid=42
    def __init__(self):self.stop=threading.Event()
    def poll(self):return None
    def signal_owned(self,s):self.stop.set();return True
class Scope:
    def __init__(self):self.processes={}
    def spawn(self,argv,*a,**kw):
        p=Process();self.processes[p.pid]=p;return p
class Commands:
    blocking=False
    def __init__(self,scope,folder):self.scope=scope
    def __call__(self,*argv,**kw):
        p=self.scope.spawn(argv)
        if self.blocking:p.stop.wait(1)
        r=row(argv)
        if self.blocking:r.update(exit_code=-15,failure_type='CalledProcessError')
        return r
class Tests(unittest.TestCase):
    def make(self,root,typ=Commands):return RetainedCommand(Scope(),typ,Path(root)/'command',['tool','exact'],timeout=10,retain=lambda raw:None)
    def test_actual_retained_completion(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make(d);p.start();self.assertEqual(p.result(1)['exit_code'],0)
            with self.assertRaises(ValueError):p.start()
    def test_stop_preserves_failed_outcome(self):
        class Blocking(Commands):blocking=True
        with tempfile.TemporaryDirectory() as d:
            p=self.make(d,Blocking);p.start()
            deadline=time.monotonic()+1
            while p.process is None and time.monotonic()<deadline:time.sleep(.001)
            self.assertTrue(p.stop(1)['settled'])
            with self.assertRaises(ValueError):p.result(1)
    def test_receipt_write_failure_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make(d);p.retain=lambda raw:(_ for _ in ()).throw(OSError('test'));p.start()
            with self.assertRaises(OSError):p.result(1)
    def test_unknown_launch_and_wrong_argv_reject(self):
        r=row(['x']);r['launch_receipt']={}
        with self.assertRaises(ValueError):clean(r,['x'])
        with self.assertRaises(ValueError):clean(row(['x']),['y'])
    def test_changed_owner_not_signalled(self):
        class Blocking(Commands):blocking=True
        with tempfile.TemporaryDirectory() as d:
            p=self.make(d,Blocking);p.start()
            deadline=time.monotonic()+1
            while p.process is None and time.monotonic()<deadline:time.sleep(.001)
            original=p.process;p.scope.processes[42]=object()
            with self.assertRaises(ValueError):p.stop(1)
            self.assertFalse(original.stop.is_set());original.stop.set();p.finished.wait(1)
if __name__=='__main__':unittest.main()
