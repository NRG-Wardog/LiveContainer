"""Synthetic host tests only; no claim about installed Apple sample support."""
import os,struct,tempfile,time,unittest,threading,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import helper_sample as h

UUID='01234567-89AB-CDEF-0123-456789ABCDEF'
IMAGE={'path':'/private/owned/direct-capture','sha256':'a'*64,'uuids':[UUID]}
def report(pid=10,parent=20,path=IMAGE['path'],uuid=UUID):
    return (f'Process: direct-capture [{pid}]\nPath: {path}\nParent Process: python [{parent}]\n'
            f'Call graph:\n    Thread_123\nBinary Images:\n0x10 - 0x20 direct-capture <{uuid}> {path}\n').encode()

class ReportTests(unittest.TestCase):
    def test_valid_identity(self):
        self.assertEqual(h.validate_report(report(),pid=10,parent=20,image=IMAGE)['bytes'],len(report()))
    def test_wrong_pid_parent_image_uuid_rejected(self):
        for change in ({'pid':11},{'parent':21},{'path':'/other'},{'uuid':'A'*36}):
            with self.assertRaises(ValueError):h.validate_report(report(**change),pid=10,parent=20,image=IMAGE)
    def test_duplicate_header_missing_callgraph_invalid_utf8_oversize(self):
        for raw in (report()+b'Path: /other\n',report().replace(b'Call graph:',b'Other:'),b'\xff',b'x'*(h.MAX_OUTPUT+1)):
            with self.assertRaises((ValueError,UnicodeError)):h.validate_report(raw,pid=10,parent=20,image=IMAGE)
    def test_explicit_denial_distinct_from_generic_failure(self):
        self.assertEqual(h.outcome(1,b'Operation not permitted'),'denied')
        self.assertEqual(h.outcome(1,b'no process'),'failed')
        self.assertEqual(h.outcome(1,b'usage: sample PID'),'unsupported')
    def test_thin_macho_uuid(self):
        import uuid
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'image';p.write_bytes(struct.pack('<8I',0xfeedfacf,0x100000c,0,2,1,24,0,0)+struct.pack('<II',0x1b,24)+uuid.UUID(UUID).bytes)
            self.assertEqual(h.image_identity(p)['uuids'],[UUID])
    def test_non_macho_or_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve()/'image';p.write_bytes(b'not macho')
            with self.assertRaises(ValueError):h.image_identity(p)
            link=p.with_name('link');link.symlink_to(p)
            with self.assertRaises(ValueError):h.image_identity(link)

class LifecycleTests(unittest.TestCase):
    def experiment(self,d):
        scope=SimpleNamespace(session='a'*32,deadline=time.monotonic()+60)
        return h.Experiment(scope,SimpleNamespace(),Path(d),'b'*32,'a'*64,IMAGE['path'])
    def test_non_darwin_no_command_or_thread(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.experiment(d)
            with patch.object(h.sys,'platform','linux'),patch.object(e,'_launch',side_effect=AssertionError):e.preflight()
            self.assertEqual(e.row['status'],'unsupported');e.start(None,deadline=0);e.finish(0)
            self.assertIsNone(e.thread);self.assertFalse((Path(d)/'helper-sample.txt').exists())
    def test_missing_tool_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.experiment(d)
            with patch.object(h.sys,'platform','darwin'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123'}),patch.object(h.Path,'is_file',return_value=False):e.preflight()
            self.assertEqual(e.row['status'],'unavailable')
    def test_missing_or_self_hosted_runner_rejected_before_launch(self):
        for environment in (None,'self-hosted',''):
            with self.subTest(environment=environment),tempfile.TemporaryDirectory() as d:
                e=self.experiment(d)
                values={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','GITHUB_RUN_ID':'123'}
                if environment is not None:values['RUNNER_ENVIRONMENT']=environment
                with patch.object(h.sys,'platform','darwin'),patch.dict(os.environ,values,clear=True),patch.object(e,'_launch',side_effect=AssertionError('no launch permitted')),patch.object(e,'_run',side_effect=AssertionError('no sample permitted')):
                    e.preflight()
                self.assertEqual(e.row['status'],'unsupported')
                self.assertEqual(e.row['reason'],'isolated-ci-account-required')
                self.assertIsNone(e.thread);self.assertIsNone(e.raw)
    def run_fake(self,d,*,post_live=True,raw=None,result_status=None,code=0,crash=False):
        e=self.experiment(d);e.row['status']='available'
        process=SimpleNamespace(pid=10);helper=SimpleNamespace(process=process,scope=e.scope,argv=[IMAGE['path'],'1','simulator','frames','b'*32,'1','2'])
        calls=[]
        def live(p,a):
            calls.append(p)
            if len(calls)==2 and not post_live:raise ValueError('original exited/reaped')
        e._live=live
        def run(*a):
            if crash:raise RuntimeError('sampler crash')
            return {'raw':report(parent=os.getpid()) if raw is None else raw,'code':code,'status':result_status}
        e._run=run
        with patch.object(h,'image_identity',return_value=IMAGE):
            e.start(helper,deadline=time.monotonic()+8);e.done.wait(1)
            try:e.finish(1)
            except RuntimeError:
                if not crash:raise
        return e
    def test_same_original_live_then_valid_report_retained(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d);self.assertEqual(e.row['status'],'validated-statistical-report')
            self.assertTrue((Path(d)/'helper-sample.txt').exists());e.finish(0)
    def test_exited_original_reused_pid_never_accepted_or_retained(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d,post_live=False)
            self.assertEqual(e.row['status'],'inconclusive');self.assertIsNone(e.raw)
            self.assertFalse((Path(d)/'helper-sample.txt').exists())
    def test_wrong_report_not_retained(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d,raw=report(pid=11,parent=os.getpid()))
            self.assertEqual(e.row['status'],'inconclusive');self.assertIsNone(e.raw)
    def test_cancel_timeout_overflow_denial_crash(self):
        for status in ('cancelled','timeout','output-limit'):
            with tempfile.TemporaryDirectory() as d:
                e=self.run_fake(d,result_status=status);self.assertEqual(e.row['status'],status);self.assertIsNone(e.raw)
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d,raw=b'permission denied',code=1);self.assertEqual(e.row['status'],'denied')
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d,crash=True);self.assertEqual(e.row['status'],'failed')
    def test_second_attempt_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.run_fake(d)
            with self.assertRaises(ValueError):e.start(None,deadline=0)
    def test_pending_thread_cannot_claim_joined_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            e=self.experiment(d);event=threading.Event();e.thread=threading.Thread(target=lambda:event.wait(1));e.thread.start()
            try:
                with self.assertRaises(ValueError):e.finish(0)
                self.assertFalse((Path(d)/'helper-sample.json').exists())
            finally:event.set();e.thread.join()


class RealSyntheticProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        preflight=Path(__file__).resolve().parents[2]/'preflight'
        if not preflight.exists():preflight=Path(__file__).resolve().parents[2]/'window-capture-candidate/ci/p1/preflight'
        sys.path.insert(0,str(preflight))
        import process_scope
        self.ps=process_scope;self.scope=process_scope.Scope(Path(self.tmp.name).resolve())
        self.e=h.Experiment(self.scope,process_scope,Path(self.tmp.name).resolve(),'b'*32,'a'*64,IMAGE['path'])
        self.addCleanup(self.scope.close)
    def test_registered_output_bound_and_reaped_cleanup(self):
        result=self.e._run([sys.executable,'-B','-c',"import os; os.write(1,b'x'*600000)"],time.monotonic()+3)
        self.assertEqual(result['status'],'output-limit');self.assertEqual(len(result['raw']),h.MAX_OUTPUT+1)
        self.assertTrue(all(row['settled'] for row in self.scope.rows))
    def test_registered_timeout_and_cancel_settle_child(self):
        result=self.e._run([sys.executable,'-B','-c','import time; time.sleep(10)'],time.monotonic()+.2)
        self.assertEqual(result['status'],'timeout');self.assertTrue(all(row['settled'] for row in self.scope.rows))
        self.e.cancel.set()
        result=self.e._run([sys.executable,'-B','-c','import time; time.sleep(10)'],time.monotonic()+1)
        self.assertEqual(result['status'],'cancelled');self.assertTrue(all(row['settled'] for row in self.scope.rows))
    def test_actual_original_exit_cannot_be_confused_by_numeric_pid(self):
        fd=os.open(os.devnull,os.O_WRONLY);self.addCleanup(os.close,fd)
        argv=[sys.executable,'-B','-c','import time; time.sleep(.15)']
        child=self.e._launch(argv,fd,time.monotonic()+2)
        until=time.monotonic()+1
        while not child.launch.row['eof'] and time.monotonic()<until:
            with child.lock:child.launch.observe()
            time.sleep(.01)
        self.e._live(child,argv);child.wait(timeout=1)
        with self.assertRaisesRegex(ValueError,'exited'):self.e._live(child,argv)
        # A registry entry with the same numeric PID but another object also fails.
        self.scope.processes[child.pid]=object()
        try:
            with self.assertRaisesRegex(ValueError,'original owned'):self.e._live(child,argv)
        finally:self.scope.processes[child.pid]=child
        self.scope.settle(child)

    def test_preflight_closes_synthetic_launch_receipt_on_denial(self):
        image=dict(IMAGE,path=str(Path(sys.executable).resolve()))
        def denied(argv,deadline):return {'status':None,'code':1,'raw':b'operation not permitted'}
        with patch.object(h.sys,'platform','darwin'),patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123'}),patch.object(h.Path,'is_file',return_value=True),patch.object(h.os,'access',return_value=True),patch.object(h,'image_identity',return_value=image),patch.object(self.e,'_run',side_effect=denied):
            self.e.preflight()
        self.assertEqual(self.e.row['status'],'denied')
        self.assertEqual(len(self.scope.processes),1)
        child=next(iter(self.scope.processes.values()))
        self.assertTrue(child.launch.row['closed']);self.assertIsNone(child.launch.fd)
        self.assertTrue(all(row['settled'] for row in self.scope.rows));self.assertIsNone(self.e.raw)

    def test_rejected_or_missing_exec_receipt_never_live(self):
        fd=os.open(os.devnull,os.O_WRONLY);self.addCleanup(os.close,fd)
        argv=[sys.executable,'-B','-c','import time; time.sleep(10)']
        child=self.e._launch(argv,fd,time.monotonic()+2)
        try:
            until=time.monotonic()+1
            while not child.launch.row['eof'] and time.monotonic()<until:
                with child.lock:child.launch.observe()
                time.sleep(.01)
            self.e._live(child,argv)
            row=child.launch.row;original={k:row[k] for k in ('reason','state','pre_exec')}
            for reason in ('missing-pre-exec','malformed-record','late-observation'):
                row.update(state='unknown',reason=reason)
                with self.assertRaisesRegex(ValueError,'rejected'):self.e._live(child,argv)
            row.update(original);row['pre_exec']=None
            with self.assertRaisesRegex(ValueError,'rejected'):self.e._live(child,argv)
            row.update(original)
            self.e._live(child,argv)
        finally:
            try:self.scope.settle(child)
            finally:child.launch.finish()

    def test_sampler_receipt_closed_if_settlement_raises(self):
        original=self.scope.settle
        def fail(child):
            original(child)
            raise RuntimeError('synthetic settle failure')
        with patch.object(self.scope,'settle',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'synthetic settle failure'):
                self.e._run([sys.executable,'-B','-c','pass'],time.monotonic()+2)
        child=next(iter(self.scope.processes.values()))
        self.assertTrue(child.launch.row['closed']);self.assertIsNone(child.launch.fd)

if __name__=='__main__':unittest.main()
