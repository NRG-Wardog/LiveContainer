import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import process_scope
import capture
import budget

HERE=Path(__file__).resolve().parent
HOST=HERE.parents[2]

class Integration(unittest.TestCase):
    def test_receipt_test_executable_matches_real_macos_probe(self):
        text=(HERE/'test_stall_receipts.py').read_text()
        self.assertNotIn("'/bin/true'",text)
        self.assertEqual(text.count("'/usr/bin/true'"),2)
    def test_toolchain_and_runtime_drift(self):
        import stall_diagnostic as stall
        stall.exact_xcode(b'Xcode 26.4.1\nBuild version 17E202\n')
        with self.assertRaises(ValueError):stall.exact_xcode(b'Xcode 26.5\nBuild version 17E202\n')
        data={'runtimes':[{'identifier':stall.boot.RUNTIME,'version':'26.2','buildversion':'23C54','isAvailable':True}]}
        stall.exact_runtime(json.dumps(data).encode())
        data['runtimes'][0]['buildversion']='23C55'
        with self.assertRaises(ValueError):stall.exact_runtime(json.dumps(data).encode())
    def test_exact_seal(self):
        path=HERE/'inputs.json'
        data=capture.validate(HOST,path,hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(data['scope'],'owned-window-acquisition-only-no-admission')
        for name in ['minimal_gate.py','process_scope.py','probe_pair.py','stall_diagnostic.py','budget.py']:
            self.assertIn('ci/p1/preflight/'+name,data['adapter_files'])
    def test_shared_observation_and_cleanup_deadlines(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(process_scope.time,'monotonic',return_value=100):
            scope=process_scope.Scope(Path(tmp),stall_diagnostic=True)
            self.assertEqual(scope.deadline,460);self.assertEqual(scope.cleanup_deadline,580)
            with mock.patch.object(process_scope.time,'monotonic',return_value=455):
                self.assertEqual(scope.remaining(10),5)
                self.assertEqual(scope.remaining(15,True),15)
            with mock.patch.object(process_scope.time,'monotonic',return_value=461):
                with self.assertRaises(TimeoutError):scope.remaining(10)
                self.assertEqual(scope.remaining(15,True),15)
            with mock.patch.object(process_scope.time,'monotonic',return_value=581):
                with self.assertRaises(TimeoutError):scope.remaining(15,True)
    def test_outer_budget_rejects_wrong_profile(self):
        with self.assertRaises(ValueError):budget.run([],Path('/unused'),seconds=1200,stall_diagnostic=True)
        with self.assertRaises(ValueError):budget.run([],Path('/unused'),seconds=600)
    def test_workflow_is_one_diagnostic(self):
        text=(HOST/'.github/workflows/p1-native-candidate.yml').read_text()
        self.assertEqual(text.count('budget.py --stall-diagnostic'),0)
        self.assertEqual(text.count('preflight/stall_diagnostic.py'),0)
        self.assertIn('preflight/window_capture.py',text);self.assertNotIn('--capture-prerequisites',text);self.assertNotIn('--execute',text)
        self.assertIn('budget.py --check-package',text)
        self.assertIn('timeout-minutes: 22',text);self.assertIn('timeout-minutes: 30',text)
    def test_sampler_and_probes_are_sealed(self):
        text=(HERE/'stall_diagnostic.py').read_text()
        self.assertLess(text.index("sampler.start()"),text.index("probe_pair.pair(trivial,'before-boot')"))
        self.assertIn("scope.fixture_created(proof)",text)
        self.assertNotIn("simctl','install",text)

if __name__=='__main__':unittest.main()

class CollectorFlow(unittest.TestCase):
    def execute_case(self, boot_timeout=False, unsettled=False, probe_error=False, state='Shutdown'):
        import stall_diagnostic as stall
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        output=Path(temp.name)/'evidence';scope=mock.Mock(rows=[],gate_mode='full',session='a'*32)
        scope.remaining.return_value=120
        sampler=mock.Mock();sampler.finish.return_value={'rows':[],'terminal':True,'error':None,'sample_count':0}
        labels=[]
        def run(label,argv,parser,timeout=10):
            labels.append((label,timeout))
            row={'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[], 'data':{}}
            if label=='before-state':
                if state!='Shutdown':raise ValueError('preexisting booted')
                row['data']={'preexisting':[stall.boot.DEVICE],'runtime':stall.boot.RUNTIME,'device_type':stall.fresh_device.TYPE}
            if label=='device-type':row['data']={'device_type':stall.fresh_device.TYPE,'type_verified':True}
            if label=='create':row['data']='11111111-2222-4333-8444-555555555555'
            if label=='created-state':row['data']={'devices':{stall.boot.RUNTIME:[{'state':'Shutdown'}]}}
            if label=='bootstatus' and boot_timeout:
                row.update(exit_code=None,failure_type='TimeoutExpired',primary_error={'type':'TimeoutExpired'})
            if label=='bootstatus' and unsettled:scope.rows.append({'settled':False})
            return row
        commands=mock.Mock();commands.run.side_effect=run
        def pair(command,phase):
            if probe_error and phase=='before-boot':raise RuntimeError('receipt writer unsettled')
            return {'phase':phase,'probes':[{'mode':mode,'exit_code':0,'failure':None,'cleanup_errors':[],'launch_receipt':{'state':'pre-exec-observed','exec_failure':None,'closed':True,'eof':True}} for mode in ('full','minimal')]}
        with mock.patch.object(stall.process_scope,'Scope',return_value=scope),mock.patch.object(stall.boot,'Commands',return_value=commands),mock.patch.object(stall.process_scope,'Commands'),mock.patch.object(stall.boot,'retain_provenance',return_value={}),mock.patch.object(stall.probe_pair,'Sampler',return_value=sampler),mock.patch.object(stall.probe_pair,'pair',side_effect=pair) as pairs,mock.patch.object(stall.fresh_device,'Commands',return_value=commands),mock.patch.object(stall.fresh_device,'cleanup',return_value={'observed_shutdown':True,'deleted':True,'command_failed':False}) as shutdown:
            result=stall.collect(HOST,HERE/'inputs.json','a'*64,output)
            return result,json.loads((output/'stall-result.json').read_text()),scope,sampler,list(pairs.call_args_list),shutdown.call_count,labels
    def test_readiness_timeout_still_compares_after_proven_settlement(self):
        ok,data,scope,sampler,pairs,shutdown,labels=self.execute_case(boot_timeout=True)
        self.assertFalse(ok);self.assertTrue(data['collection_complete']);self.assertTrue(data['primary_command_failed']);self.assertEqual(len(pairs),2);self.assertEqual(shutdown,1)
        self.assertEqual(data['bootstatus']['failure_type'],'TimeoutExpired')
        self.assertFalse(data['admissionEligible']);self.assertIn(('bootstatus',120),labels)
        scope.close.assert_called_once();sampler.finish.assert_called_once()
    def test_unsettled_boot_stops_after_probe_and_cleans_owned_device(self):
        ok,data,scope,sampler,pairs,shutdown,labels=self.execute_case(unsettled=True)
        self.assertFalse(ok);self.assertEqual(len(pairs),1);self.assertEqual(shutdown,1)
        scope.close.assert_called_once();sampler.finish.assert_called_once()
    def test_failed_before_probe_never_boots_or_claims_device(self):
        ok,data,scope,sampler,pairs,shutdown,labels=self.execute_case(probe_error=True)
        self.assertFalse(ok);self.assertEqual(shutdown,0);scope.fixture_created.assert_not_called()
        self.assertNotIn('boot',[x[0] for x in labels]);sampler.finish.assert_called_once()
    def test_preexisting_booted_device_is_never_owned(self):
        ok,data,scope,sampler,pairs,shutdown,labels=self.execute_case(state='Booted')
        self.assertFalse(ok);self.assertEqual(shutdown,0);scope.fixture_created.assert_not_called()
        sampler.start.assert_not_called();self.assertEqual(len(pairs),0)
