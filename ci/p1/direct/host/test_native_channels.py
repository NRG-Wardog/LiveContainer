import tempfile,unittest,json
from unittest.mock import patch
from pathlib import Path
from native_channels import Channels
from native_process import clean
from test_native_process import row
class Native:
    def live(self):pass
class Tests(unittest.TestCase):
    def failure_case(self,d,change=None,ready=False):
        p=Path(d).resolve();c=self.make(d,None);retained=[];c.retain=lambda name,raw:retained.append((name,raw))
        c.roots={'app':p/'app','runner':p/'runner'}
        target=c.roots['runner']/'Documents/p1-capability'/c.session;target.mkdir(parents=True)
        row=dict(schema='p1-direct-baseline-observer-error-v1',session=c.session,scenario='timeout',phase='sampling-geometry',error='anchor overlap',baselineTapReleased=False,admissionEligible=False)
        if change:row.update(change)
        raw=json.dumps(row).encode();(target/'observer-error.json').write_bytes(raw)
        if ready:(target/'ready.json').write_bytes(b'{}')
        self.addCleanup(c.close);return c,retained,raw
    def test_native_error_retained_without_app_directory_or_wait(self):
        with tempfile.TemporaryDirectory() as d:
            c,retained,raw=self.failure_case(d)
            with patch('native_channels.time.sleep',side_effect=AssertionError('must not wait')):
                with self.assertRaisesRegex(RuntimeError,'anchor overlap'):c.geometry(30,lambda raw:None)
            self.assertEqual(retained,[('observer-error',raw)])
    def test_error_precedes_even_present_ready(self):
        with tempfile.TemporaryDirectory() as d:
            c,retained,raw=self.failure_case(d,ready=True)
            with self.assertRaisesRegex(RuntimeError,'anchor overlap'):c.geometry(30,lambda raw:None)
    def test_foreign_and_malformed_errors_fail_closed_after_retention(self):
        for change in ({'session':'b'*32},{'scenario':'replacement'},{'schema':'foreign'},{'baselineTapReleased':True},{'admissionEligible':True},{'error':None}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                c,retained,raw=self.failure_case(d,change)
                with self.assertRaisesRegex(ValueError,'malformed'):c.geometry(30,lambda raw:None)
                self.assertEqual(retained,[('observer-error',raw)])
    def make(self,d,command):
        c=Channels(command,Native(),device='D',session='a'*32,app_id='app',runner_id='runner',retain=lambda *a:None,remaining=lambda x:x)
        c.hint={};return c
    def test_one_lookup_and_exact_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();calls=[]
            def command(*argv,**kw):calls.append(argv);return dict(row(argv),stdout=str(root))
            c=self.make(d,command);result=c.discover('app',30)
            self.assertEqual(result['root'],str(root));self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):c.discover('app',30)
    def test_failed_lookup_cannot_retry(self):
        with tempfile.TemporaryDirectory() as d:
            def command(*argv,**kw):return dict(row(argv),stdout=d,exit_code=-15)
            c=self.make(d,command)
            with self.assertRaises(ValueError):c.discover('app',30)
            with self.assertRaises(ValueError):c.discover('app',30)
    def test_linked_root_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();(p/'link').symlink_to(p,target_is_directory=True)
            c=self.make(d,lambda *a,**kw:dict(row(a),stdout=str(p/'link')))
            with self.assertRaises(ValueError):c.discover('runner',30)
    def test_no_hint_no_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.make(d,lambda *a,**kw:None);c.hint=None
            with self.assertRaises(ValueError):c.discover('app',30)
if __name__=='__main__':unittest.main()
