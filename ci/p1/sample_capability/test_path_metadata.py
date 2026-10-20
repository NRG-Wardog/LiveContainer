"""Negative prerequisites and metadata-only retention; no reported path access."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import path_metadata as m
import diagnostic as d
from test_diagnostic import IMAGE,report

class PathMetadataTests(unittest.TestCase):
    def kwargs(self):return dict(pid=10,parent=20,expected_path=IMAGE['path'],pre_checks=dict.fromkeys(m.LIVE_KEYS,True),post_checks=dict.fromkeys(m.LIVE_KEYS,True),image_unchanged=True,owned_native_probe=True)
    def reject(self,raw,code,**change):
        args=self.kwargs();args.update(change)
        self.assertEqual(m.extract(raw,**args),{'code':code})
    def test_path_mismatch_retained_but_authoritative_validation_rejects(self):
        raw=report(path='/different/path')
        with patch('builtins.open',side_effect=AssertionError('no path reads')):
            result=m.extract(raw,**self.kwargs())
        self.assertEqual(result['reportedPath'],'/different/path');self.assertFalse(result['pathMatchesExpected'])
        with self.assertRaises(d.Rejection) as cm:d.validate(raw,pid=10,parent=20,image=IMAGE,checks={})
        self.assertEqual((cm.exception.stage,cm.exception.code),('report-path','path-matches'))
        encoded=json.dumps(result)
        for forbidden in ('STACK_SENTINEL','Binary Images','Parent Process','Process:','Call graph'):
            self.assertNotIn(forbidden,encoded)
    def test_matching_path_does_not_invent_admission(self):
        result=m.extract(report(),**self.kwargs())
        self.assertTrue(result['pathMatchesExpected']);self.assertFalse(result['admissionEligible'])
    def test_every_liveness_and_provenance_prerequisite(self):
        raw=report()
        self.reject(raw,'native-probe-required',owned_native_probe=False)
        self.reject(raw,'unchanged-native-image-required',image_unchanged=False)
        for field in ('pre_checks','post_checks'):
            for key in m.LIVE_KEYS:
                checks=dict.fromkeys(m.LIVE_KEYS,True);checks[key]=False
                self.reject(raw,'original-child-live-receipts-required',**{field:checks})
            self.reject(raw,'original-child-live-receipts-required',**{field:{}})
        self.reject(report(pid=11),'exact-pid-required')
        self.reject(report(parent=21),'exact-parent-required')
    def test_unique_headers(self):
        for name,code in [('Process','process'),('Path','path'),('Parent Process','parent')]:
            raw=report();line=next(l for l in raw.splitlines(keepends=True) if l.startswith(name.encode()+b':'))
            self.reject(raw+line,code+'-unique-header-required')
            self.reject(raw.replace(line,b''),code+'-unique-header-required')
    def test_report_bounds_and_utf8(self):
        for raw in (None,b'',b'x'*(m.MAX_REPORT_BYTES+1)):self.reject(raw,'bounded-report-required')
        self.reject(b'\xff','utf8-required')
    def test_path_newline_nul_control_oversize(self):
        for path in ('/a\nb','/a\rb','/a\x00b','/a\tb','/a\x1bb','a'*1025,'é'*513,''):
            self.assertFalse(m.printable_path(path))
        # A newline after the colon cannot be consumed into a subsequent line.
        self.reject(report(path='\n/should-not-retain'),'single-line-path-header-required')
        self.reject(report(path='/a\nb'),'single-line-path-header-required')
        for path in ('/a\rb','/a\x00b','/a\tb','/a\x1bb','a'*1025,'é'*513,''):
            self.reject(report(path=path),'bounded-printable-single-line-path-required')
        value='a'*1024;result=m.extract(report(path=value),**self.kwargs());self.assertEqual(result['pathBytes'],1024)
    def test_persisted_metadata_keeps_only_bounded_path_on_rejection(self):
        valid={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'NRG-Wardog/LiveContainer','RUNNER_OS':'macOS','RUNNER_ENVIRONMENT':'github-hosted','GITHUB_RUN_ID':'123','GITHUB_REF':d.BRANCH,'GITHUB_EVENT_NAME':'push'}
        for parent_match in (True,False):
            with tempfile.TemporaryDirectory() as directory:
                scope=SimpleNamespace(session='a'*32,deadline=time.monotonic()+60,settle=lambda child:None)
                e=d.Diagnostic(scope,SimpleNamespace(LaunchReceiptError=RuntimeError),Path(directory),'b'*32,'','')
                child=SimpleNamespace(pid=10,lock=threading.RLock(),launch=SimpleNamespace(finish=lambda:None))
                def prepare(experiment):
                    experiment.row.update(expectedImage=IMAGE,nativeProbe={'compilerExitCode':0})
                    return [IMAGE['path']],IMAGE
                def live(*args):e.checks.update(dict.fromkeys(m.LIVE_KEYS,True))
                result={'raw':report(path='/diagnostic-only/path',parent=os.getpid() if parent_match else os.getpid()+1),'status':None,'code':0,'samplerPID':11}
                with patch.object(d.sys,'platform','darwin'),patch.dict(os.environ,valid,clear=True),patch.object(d.os,'getuid',return_value=501),patch.object(d.os,'geteuid',return_value=501),patch.object(d.Path,'is_file',return_value=True),patch.object(d.os,'access',return_value=True),patch.object(d.native_probe,'prepare',side_effect=prepare),patch.object(d.h,'image_identity',return_value=IMAGE),patch.object(e,'_launch',return_value=child),patch.object(e,'_live',side_effect=live),patch.object(e,'_run',return_value=result):
                    e.preflight()
                e.finish(0)
                row=json.loads((Path(directory)/'helper-sample.json').read_bytes())
                self.assertEqual((row['status'],row['code']),('unsupported','path-matches'))
                metadata=row['reportedPathDiagnostic']
                if parent_match:self.assertEqual(metadata['reportedPath'],'/diagnostic-only/path')
                else:self.assertEqual(metadata,{'code':'exact-parent-required'})
                encoded=json.dumps(row);self.assertNotIn('STACK_SENTINEL',encoded);self.assertNotIn('Call graph',encoded)
                self.assertFalse((Path(directory)/'helper-sample.txt').exists());self.assertEqual(result['raw'],b'')

    def test_parent_required_even_when_path_mismatches(self):
        self.reject(report(path='/different',parent=99),'exact-parent-required')
        # The historical validator remains unchanged and still reports path first.
        with self.assertRaises(d.Rejection) as cm:d.validate(report(path='/different',parent=99),pid=10,parent=20,image=IMAGE,checks={})
        self.assertEqual(cm.exception.code,'path-matches')

if __name__=='__main__':unittest.main()
