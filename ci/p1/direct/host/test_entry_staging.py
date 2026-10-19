import tempfile,unittest,importlib.util,json
from unittest.mock import patch
from pathlib import Path
from hashlib import sha256
spec=importlib.util.spec_from_file_location('direct_entry_test',Path(__file__).resolve().parents[1]/'entry.py');entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
class Tests(unittest.TestCase):
    def sealed(self,p):
        host=p/'host';host.mkdir();adapters={}
        for name in entry.EXPECTED_BASE_ADAPTERS|entry.EXPECTED_DIRECT_ADAPTERS:
            f=host/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'raise RuntimeError("must not execute")\n');adapters[name]=sha256(f.read_bytes()).hexdigest()
        data=dict(schema='p1-short-capability-inputs-v1',scope='direct-timeout-feedback-only-no-admission',livecontainer=entry.EXPECTED_SOURCE,builder=entry.EXPECTED_BUILDER,source_sha256=entry.EXPECTED_SOURCE_SHA,adapter_files=adapters)
        inputs=p/'inputs.json';inputs.write_text(json.dumps(data));return host,inputs,sha256(inputs.read_bytes()).hexdigest()
    def test_bootstrap_authenticates_without_executing_adapters(self):
        with tempfile.TemporaryDirectory() as d:
            host,inputs,digest=self.sealed(Path(d).resolve())
            self.assertEqual(len(entry.bootstrap(host,inputs,digest)['adapter_files']),len(entry.EXPECTED_BASE_ADAPTERS|entry.EXPECTED_DIRECT_ADAPTERS))
    def test_changed_adapter_rejected_before_first_import(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();host,inputs,digest=self.sealed(p)
            (host/'ci/p1/preflight/capture.py').write_bytes(b'changed')
            with patch.object(entry,'module',side_effect=AssertionError('executed')) as importer:
                with self.assertRaisesRegex(ValueError,'before import'):entry.execute(host,p/'work',p/'out',inputs,digest)
                importer.assert_not_called()
    def test_missing_adapter_rejected_by_fixed_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            host,inputs,digest=self.sealed(Path(d).resolve());data=json.loads(inputs.read_bytes());data['adapter_files'].pop('ci/p1/preflight/capture.py');inputs.write_text(json.dumps(data));digest=sha256(inputs.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'inventory'):entry.bootstrap(host,inputs,digest)
    def test_exact_relocated_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();host=p/'host';work=p/'work';host.mkdir();work.mkdir()
            manifest={'adapter_files':{}}
            for name in ('ci/p1/direct/entry.py','ci/p1/preflight/process_scope.py'):
                f=host/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(name.encode());manifest['adapter_files'][name]=sha256(f.read_bytes()).hexdigest()
            root,rows=entry.stage(host,work,manifest)
            self.assertEqual((root/'direct-feedback-local/entry.py').read_bytes(),b'ci/p1/direct/entry.py')
            self.assertEqual(len(rows),2)
    def test_mismatch_rejects_before_copy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();(p/'x').write_bytes(b'x');work=p/'work';work.mkdir()
            with self.assertRaises(ValueError):entry.stage(p,work,{'adapter_files':{'x':'0'*64}})
    def test_traversal_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();work=p/'work';work.mkdir()
            with self.assertRaises(ValueError):entry.stage(p,work,{'adapter_files':{'../x':'0'*64}})
    def startup_row(self,elapsed=7):
        return dict(exit_code=0,writer_settled=True,failure_type=None,primary_error=None,cleanup_errors=[],stdout='Xcode\n',
                    launch_receipt=dict(state='pre-exec-observed',closed=True,eof=True,exec_failure=None),
                    wait_timing=dict(command_started=100,wait_finished=100+elapsed))
    def test_startup_one_bounded_call_retains_historical_metric(self):
        result={};row=self.startup_row()
        from unittest.mock import Mock
        command=Mock(return_value=row)
        self.assertEqual(entry.startup_observation(command,result,'version','xcodebuild','-version',historical=5),'Xcode')
        command.assert_called_once_with('xcodebuild','-version',timeout=30,receipt=True)
        self.assertTrue(result['startupObservations']['version']['historicalAllowanceExceeded'])
    def test_startup_unknown_failed_unsettled_retained_and_rejected(self):
        from unittest.mock import Mock
        for key,value in [('exit_code',-15),('writer_settled',False),('primary_error',{'type':'TimeoutExpired'}),('cleanup_errors',[{}]),('launch_receipt',{})]:
            row=self.startup_row();row[key]=value;result={};command=Mock(return_value=row)
            with self.assertRaises(ValueError):entry.startup_observation(command,result,'version','xcodebuild','-version',historical=5)
            self.assertIs(result['startupObservations']['version'],row);self.assertEqual(command.call_count,1)
    def test_startup_original_boundary_and_missing_timing(self):
        from unittest.mock import Mock
        row=self.startup_row(5);entry.startup_observation(Mock(return_value=row),{},'version','xcodebuild',historical=5)
        self.assertFalse(row['historicalAllowanceExceeded'])
        row=self.startup_row();row['wait_timing']={}
        with self.assertRaises(ValueError):entry.startup_observation(Mock(return_value=row),{},'version','xcodebuild',historical=5)
if __name__=='__main__':unittest.main()
