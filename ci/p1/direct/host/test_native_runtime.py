import tempfile,unittest,time
from pathlib import Path
from types import SimpleNamespace
from native_runtime import Runtime
class Tests(unittest.TestCase):
    def bare(self,d,fixture=None):
        r=Runtime.__new__(Runtime);r.output=Path(d).resolve();r.scope=SimpleNamespace(fixture=fixture,rows=[],creation_intent=None,cleanup_deadline=time.monotonic()+120)
        r.channels=None;r.capture_binding=None;r._evidence={};r.retain=lambda *a:None
        r.scope.fixture_deleted=lambda value:r.scope.fixture.update(deleted=value)
        r.scope.fixture_stopped=lambda value:r.scope.fixture.update(stopped=value)
        r.scope.fixture_cleanup_failure=lambda:r.scope.fixture.update(cleanup_command_failed=True)
        return r
    def test_cleanup_unknown_create_not_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.scope.creation_intent={'pending':True}
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_cleanup_actual_api_and_failure_latch(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d,{'owned_created':{'device':'D'},'deleted':False});called=[]
            r.fresh=SimpleNamespace(Commands=lambda scope,root,proof:called.append((scope,root,proof)) or 'command',
                cleanup=lambda command,proof,settled: {'deleted':True,'observed_shutdown':True,'command_failed':True})
            with self.assertRaises(ValueError):r.cleanup_device({},75)
            self.assertEqual(len(called),1);self.assertTrue(r.scope.fixture['deleted']);self.assertTrue(r.scope.fixture['cleanup_command_failed'])
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_unsettled_host_writer_blocks_cleanup_claim(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.scope.rows=[{'settled':False}]
            with self.assertRaises(ValueError):r.verify_cleanup({},10)
    def test_no_resource_cleanup_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);self.assertEqual(r.cleanup_device({},75).value,{})
            self.assertTrue(r.verify_cleanup({},10).value['allWritersSettled'])
    def test_native_failure_not_turned_into_completion(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.bare(d);r.native_receipt=None
            r.native=SimpleNamespace(result=lambda timeout:(_ for _ in ()).throw(ValueError('failed')))
            with self.assertRaises(ValueError):r.await_native_result({'protocol':{}},60)
            self.assertIsNone(r.native_receipt)

class SharedPreparationTests(unittest.TestCase):
    def make(self,left=180):
        r=Runtime.__new__(Runtime);r.session='a'*32;r.scope=SimpleNamespace(deadline=500)
        r.remaining=lambda maximum:min(maximum,left);r.saved=[];r.retain=lambda name,raw:r.saved.append((name,__import__('json').loads(raw)))
        r.calls=[]
        def command(*args,timeout,receipt):
            r.calls.append((args,timeout,receipt))
            return {'argv':list(args),'exit_code':0,'writer_settled':True,'cleanup_errors':[],
                'launch_receipt':{'state':'pre-exec-observed','closed':True,'eof':True,'exec_failure':None},
                'wait_timing':{'command_started':320,'wait_finished':444}}
        r.command=command;return r
    def test_install_can_finish_after_old120_inside_same_deadline(self):
        r=self.make();r.prepare_service('install','xcrun','simctl','install','owned','app')
        self.assertEqual(r.calls[0][1],180);self.assertEqual(r.scope.deadline,500)
        self.assertTrue(r.saved[0][1]['historicalAllowanceExceeded']);self.assertEqual(r.saved[0][1]['waitElapsedSeconds'],124)
    def test_all_three_service_caps_share_remaining_preparation(self):
        for name in ('boot','bootstatus','install'):
            r=self.make(240);r.prepare_service(name,'xcrun','simctl',name,'owned')
            self.assertEqual(r.calls[0][1],240)
    def test_parent_remaining_never_extended(self):
        r=self.make(7);r.prepare_service('boot','xcrun','simctl','boot','owned');self.assertEqual(r.calls[0][1],7)
    def test_expired_deadline_prevents_command(self):
        r=self.make();r.remaining=lambda _:(_ for _ in ()).throw(TimeoutError('expired'))
        with self.assertRaises(TimeoutError):r.prepare_service('install','xcrun','simctl','install','owned','app')
        self.assertEqual(r.calls,[])
    def test_timeout_remains_failed_even_with_settled_zero_exit(self):
        r=self.make();original=r.command
        def command(*args,**kwargs):
            row=original(*args,**kwargs);row['primary_error']={'type':'TimeoutExpired'};return row
        r.command=command
        with self.assertRaises(ValueError):r.prepare_service('install','xcrun','simctl','install','owned','app')
        self.assertEqual(r.saved[0][1]['receipt']['primary_error']['type'],'TimeoutExpired')
    def test_unknown_launch_and_unsettled_writer_still_fail(self):
        for field,value in [('launch_receipt',{}),('writer_settled',False)]:
            r=self.make();original=r.command
            def command(*args,**kwargs):
                row=original(*args,**kwargs);row[field]=value;return row
            r.command=command
            with self.assertRaises(ValueError):r.prepare_service('boot','xcrun','simctl','boot','owned')

if __name__=='__main__':unittest.main()

class DeferredGUIStartup(unittest.TestCase):
    def make(self):
        import threading
        from unittest.mock import Mock
        r=Runtime.__new__(Runtime);r.gui=None;r.session='a'*32;r.device='owned';r.output=Path('/tmp/output');r.work=Path('/tmp/work');r._evidence={}
        r.scope=SimpleNamespace(deadline=1000,persist=lambda:None)
        r.calls=[];r.saved=[];r.retain=lambda name,raw:r.saved.append(name)
        r.command=object();r.scope.remaining=lambda maximum:min(maximum,r.scope.deadline-100)
        process=Mock();process.pid=7;process.poll.return_value=None;process.lock=threading.RLock();process.launch.row={'eof':True}
        r.native=SimpleNamespace(scope=r.scope,process=process,argv=('xcodebuild','test-without-building'),live=lambda:r.calls.append('live'))
        def hint(timeout):r.calls.append('hint');return {'session':r.session}
        r.channels=SimpleNamespace(started=hint)
        def isolation(*args):r.calls.append('isolation')
        def gui(scope,device,folder,**kwargs):
            self.assertIs(kwargs['active_writer'],process);self.assertEqual(kwargs['active_argv'],r.native.argv)
            r.calls.append('construct')
            return SimpleNamespace(process=SimpleNamespace(pid=8),start=lambda:r.calls.append('start'))
        r.window=SimpleNamespace(startup_isolation=isolation,OwnedGUI=gui)
        return r,{'argv':list(r.native.argv)}
    def test_hint_then_fresh_isolation_then_exact_gui_inside_same_deadline(self):
        from unittest.mock import patch
        r,context=self.make()
        with patch('native_runtime.time.monotonic',return_value=100):r.await_started(context,50)
        self.assertEqual(r.calls,['hint','live','isolation','live','live','construct','start','live'])
        self.assertEqual(r.scope.deadline,1000);self.assertIn('deferred-gui-start',r.saved)
        r.native.process.launch.finish.assert_called_once();r.native.process.launch.require.assert_called_once()
    def test_missing_hint_or_failed_isolation_never_constructs_gui(self):
        from unittest.mock import patch
        for stage in ('hint','isolation'):
            r,context=self.make()
            def fail(*args):raise TimeoutError('expected')
            if stage=='hint':r.channels.started=fail
            else:r.window.startup_isolation=fail
            with patch('native_runtime.time.monotonic',return_value=100),self.assertRaises(TimeoutError):r.await_started(context,50)
            self.assertIsNone(r.gui);self.assertEqual(r.scope.deadline,1000)
    def test_wrong_native_binding_rejected_before_constructor(self):
        from unittest.mock import patch
        r,context=self.make();context['argv']=['foreign']
        with patch('native_runtime.time.monotonic',return_value=100),self.assertRaises(ValueError):r.await_started(context,50)
        self.assertIsNone(r.gui)
    def test_partial_gui_start_keeps_owner_for_cleanup(self):
        from unittest.mock import patch
        r,context=self.make();factory=r.window.OwnedGUI
        def broken(*a,**kw):
            gui=factory(*a,**kw)
            gui.start=lambda:(_ for _ in ()).throw(RuntimeError('start failed'))
            return gui
        r.window.OwnedGUI=broken
        with patch('native_runtime.time.monotonic',return_value=100),self.assertRaises(RuntimeError):r.await_started(context,50)
        self.assertIsNotNone(r.gui);self.assertEqual(r.scope.deadline,1000)

    def test_exit_between_precheck_and_lock_never_finishes_receipt(self):
        from unittest.mock import patch
        r,context=self.make();r.native.process.poll.return_value=0
        with patch('native_runtime.time.monotonic',return_value=100),self.assertRaises(ValueError):r.await_started(context,50)
        r.native.process.launch.finish.assert_not_called();self.assertIsNone(r.gui)
