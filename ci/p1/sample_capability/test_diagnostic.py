"""Synthetic rejection coverage. No macOS capability claims."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'ci/p1/direct/host'),str(ROOT/'ci/p1/preflight')]
import diagnostic as d
import helper_sample as h
import process_scope as ps
UUID='01234567-89AB-CDEF-0123-456789ABCDEF'
IMAGE={'path':'/private/owned/python','sha256':'a'*64,'uuids':[UUID]}

def report(pid=10,parent=20,path=IMAGE['path'],uuid=UUID):
    return (f'Process: Python [{pid}]\nPath: {path}\nParent Process: python [{parent}]\n'
            f'Call graph:\nSTACK_SENTINEL\nBinary Images:\n0x10 - 0x20 Python <{uuid}> {path}\n').encode()

class Reports(unittest.TestCase):
    def reject(self,raw,stage,code):
        checks={}
        with self.assertRaises(d.Rejection) as cm:d.validate(raw,pid=10,parent=20,image=IMAGE,checks=checks)
        self.assertEqual((cm.exception.stage,cm.exception.code),(stage,code))
        self.assertNotIn('STACK_SENTINEL',json.dumps(checks))
        self.assertTrue(all(type(v) is bool for v in checks.values()))
    def test_valid_original_agreement(self):
        self.assertEqual(d.validate(report(),pid=10,parent=20,image=IMAGE,checks={}),h.validate_report(report(),pid=10,parent=20,image=IMAGE))
    def test_bounds_utf8(self):
        for raw in (None,b'',b'x'*(h.MAX_OUTPUT+1)):self.reject(raw,'report-bounds','bounded-report')
        self.reject(b'\xff','report-format','utf8')
    def test_required_headers(self):
        for label,code in [('Process','process'),('Path','path'),('Parent Process','parent')]:
            raw=report();lines=raw.splitlines(keepends=True);line=next(l for l in lines if l.startswith(label.encode()+b':'))
            self.reject(raw.replace(line,b''),'report-header',code+'-present')
            self.reject(raw+line,'report-header',code+'-unique')
    def test_pid_path_parent(self):
        for kw,stage,code in [({'pid':11},'report-pid','pid-matches'),({'path':'/other'},'report-path','path-matches'),({'parent':21},'report-parent','parent-matches')]:
            self.reject(report(**kw),stage,code)
    def test_format(self):
        for name,code in [(b'Call graph:','call-graph-present'),(b'Binary Images:','binary-images-present')]:
            self.reject(report().replace(name,b'OTHER:'),'report-format',code)
    def test_uuid(self):
        self.reject(report(uuid='AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA'),'report-uuid','uuid-matches')
        self.reject(report().replace(b'<'+UUID.encode()+b'>',b'<bad>'),'report-uuid','image-uuid-record-unique')
        self.reject(report()+report().split(b'Binary Images:\n')[1],'report-uuid','image-uuid-record-unique')

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.scope=ps.Scope(Path(self.tmp.name).resolve(),capture_prerequisites=True);self.addCleanup(self.scope.close)
        self.e=d.Diagnostic(self.scope,ps,Path(self.tmp.name),'b'*32,'','')
    def test_all_environment_gates_no_spawn(self):
        valid={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123','GITHUB_REF':d.BRANCH,'GITHUB_EVENT_NAME':'push'}
        for key in valid:
            self.e.row['status']='not-started'
            with patch.object(d.sys,'platform','darwin'),patch.dict(os.environ,dict(valid,**{key:'bad'}),clear=True),patch.object(d.os,'getuid',return_value=501),patch.object(d.os,'geteuid',return_value=501),patch.object(self.e,'_launch',side_effect=AssertionError):self.e.preflight()
            self.assertEqual(self.e.row['code'],'isolated-exact-branch-ci-required')
        for uid,euid in [(0,0),(501,502)]:
            self.e.row['status']='not-started'
            with patch.object(d.sys,'platform','darwin'),patch.dict(os.environ,valid,clear=True),patch.object(d.os,'getuid',return_value=uid),patch.object(d.os,'geteuid',return_value=euid),patch.object(self.e,'_launch',side_effect=AssertionError):self.e.preflight()
            self.assertEqual(self.e.row['status'],'unsupported')
    def test_non_darwin_no_launch_or_raw(self):
        with patch.object(d.sys,'platform','linux'),patch.object(self.e,'_launch',side_effect=AssertionError):self.e.preflight()
        self.e.finish(0)
        self.assertEqual(self.e.row['code'],'non-darwin');self.assertFalse((Path(self.tmp.name)/'helper-sample.txt').exists())
    def test_live_rejection_codes(self):
        child=ps.OwnedProcess(SimpleNamespace(pid=10,poll=lambda:None))
        launch=ps.LaunchReceipt(1,time.monotonic()+10,10)
        launch.row.update(session=self.scope.session,pid=10,eof=True,exec_failure=None,pre_exec={},state='pre-exec-observed',reason=None)
        launch.row['registration']['durable']=True;launch.observe=lambda:None;child.launch=launch
        self.scope.processes[10]=child
        row={'pid':10,'argv':['benign'],'settled':False};self.scope.rows.append(row)
        self.e.stage='pre-sample-liveness'
        try:
            self.e._live(child,['benign'])
            cases=[(row,'argv',[], 'owned-registry'),(launch.row['registration'],'durable',False,'launch-binding'),(launch.row,'eof',False,'launch-eof'),(launch.row,'exec_failure',{},'launch-no-exec-failure'),(launch.row,'pre_exec',None,'launch-pre-exec'),(launch.row,'state','rejected','launch-state')]
            for mapping,key,value,code in cases:
                prior=mapping[key];mapping[key]=value
                try:
                    with self.assertRaises(d.Rejection) as cm:self.e._live(child,['benign'])
                    self.assertEqual(cm.exception.code,code)
                finally:mapping[key]=prior
            with patch.object(child,'poll',return_value=0):
                with self.assertRaises(d.Rejection) as cm:self.e._live(child,['benign'])
                self.assertEqual(cm.exception.code,'child-live')
            with self.assertRaises(d.Rejection) as cm:self.e._live(SimpleNamespace(pid=10),['benign'])
            self.assertEqual(cm.exception.code,'owned-object')
        finally:self.scope.processes.clear();self.scope.rows.clear()
    def test_inherited_bounded_sampler_cleanup(self):
        result=self.e._run([sys.executable,'-B','-c',"import os; os.write(1,b'x'*600000)"],time.monotonic()+3)
        self.assertEqual(result['status'],'output-limit');self.assertEqual(len(result['raw']),h.MAX_OUTPUT+1)
        self.assertTrue(all(r['settled'] and r['reaped'] for r in self.scope.rows))
    def test_preflight_discards_every_report_and_never_retries(self):
        valid={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123','GITHUB_REF':d.BRANCH,'GITHUB_EVENT_NAME':'push'}
        child=SimpleNamespace(pid=10,lock=threading.RLock(),launch=SimpleNamespace(finish=lambda:None))
        for raw,status,code,want in [(report(parent=os.getpid()),None,0,'available'),(report(pid=11),None,0,'unsupported'),(b'permission denied STACK_SENTINEL',None,1,'denied'),(b'STACK_SENTINEL','output-limit',None,'output-limit')]:
            with self.subTest(want=want):
                e=d.Diagnostic(self.scope,ps,Path(self.tmp.name),'b'*32,'','')
                result={'raw':raw,'status':status,'code':code,'samplerPID':11}
                with contextlib.ExitStack() as stack:
                    for target,name,value in [(d.sys,'platform','darwin'),(d.os,'getuid',501),(d.os,'geteuid',501),(h,'image_identity',IMAGE),(d.Path,'is_file',True),(d.os,'access',True)]:
                        stack.enter_context(patch.object(target,name,return_value=value) if callable(getattr(target,name)) else patch.object(target,name,value))
                    stack.enter_context(patch.dict(os.environ,valid,clear=True))
                    stack.enter_context(patch.object(d.native_probe,'prepare',return_value=([IMAGE['path']],IMAGE)))
                    launch=stack.enter_context(patch.object(e,'_launch',return_value=child))
                    run=stack.enter_context(patch.object(e,'_run',return_value=result))
                    stack.enter_context(patch.object(e,'_live'))
                    settle=stack.enter_context(patch.object(self.scope,'settle'))
                    e.preflight()
                    self.assertEqual(e.row['status'],want);self.assertEqual(run.call_count,1);self.assertEqual(launch.call_count,1);self.assertEqual(settle.call_count,1)
                self.assertEqual(result['raw'],b'');self.assertIsNone(e.raw)
                encoded=json.dumps(e.row);self.assertNotIn('STACK_SENTINEL',encoded);self.assertNotIn('permission denied',encoded)
                # Native prepare owns expected image metadata; mocked here.
                with self.assertRaises(ValueError):e.preflight()

    def test_native_compile_failure_stops_before_probe_or_sample(self):
        valid={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123','GITHUB_REF':d.BRANCH,'GITHUB_EVENT_NAME':'push'}
        with patch.object(d.sys,'platform','darwin'),patch.dict(os.environ,valid,clear=True),patch.object(d.os,'getuid',return_value=501),patch.object(d.os,'geteuid',return_value=501),patch.object(d.Path,'is_file',return_value=True),patch.object(d.os,'access',return_value=True),patch.object(d.native_probe,'prepare',side_effect=d.native_probe.ProbeFailure('denied','native-compile','compiler-permission-denied')),patch.object(self.e,'_launch',side_effect=AssertionError),patch.object(self.e,'_run',side_effect=AssertionError):
            self.e.preflight()
        self.assertEqual((self.e.row['status'],self.e.row['stage'],self.e.row['code']),('denied','native-compile','compiler-permission-denied'))
        self.assertEqual(self.scope.rows,[])

    def test_helper_path_disabled(self):
        with self.assertRaises(RuntimeError):self.e.start(None)

if __name__=='__main__':unittest.main()
