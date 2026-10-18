"""Fail-closed parser/orchestration tests; do not execute native guest fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('p0_bounds_capture',ROOT/'native_gate.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class BoundsCaptureTests(unittest.TestCase):
    def receipt(self):
        return {'schema':1,'source_sha256':dict(gate.HELPER_SOURCES),'results':{v:dict(gate.METADATA_EXPECTED) for v in ('normal','optimized','sanitized')},'sanitizers':['address','undefined'],'leak_sanitizer_enabled':False,'guest_execution':False,'device_validation':False,'proprietary_input':False}
    def reject(self,r):
        with self.assertRaises((ValueError,TypeError,KeyError)):
            gate.verify_metadata_receipt(r)
    def inputs(self):return json.loads((ROOT/'inputs-sidesign.json').read_bytes())
    def validate(self,r):
        raw=(json.dumps(r)+'\n').encode();return gate.validate_inputs(raw,gate.sha(raw),ROOT.parents[1])
    def test_exact_metadata_success(self):
        value=self.receipt();self.assertEqual(gate.verify_metadata_receipt(value),value)
    def test_missing_extra_fields_rejected(self):
        for key in self.receipt():
            value=self.receipt();del value[key];self.reject(value)
        value=self.receipt();value['extra']='no';self.reject(value)
    def test_wrong_sources_rejected(self):
        for key in gate.HELPER_SOURCES:
            value=self.receipt();value['source_sha256'][key]='a'*64;self.reject(value)
    def test_false_claims_rejected(self):
        for key in ('guest_execution','device_validation','proprietary_input','leak_sanitizer_enabled'):
            for bad in (True,0,'false',None):
                value=self.receipt();value[key]=bad;self.reject(value)
    def test_variant_missing_or_extra_rejected(self):
        for variant in ('normal','optimized','sanitized'):
            value=self.receipt();del value['results'][variant];self.reject(value)
        value=self.receipt();value['results']['other']=dict(gate.METADATA_EXPECTED);self.reject(value)
    def test_bad_counts_types_and_failures_rejected(self):
        for variant in ('normal','optimized','sanitized'):
            for key,bads in {'checks':[0,712,714,True,'713'],'failures':[1,False,'0'],'schema':[2,True,'1'],'guest_execution':[0,True],'proprietary_input':[0,True]}.items():
                for bad in bads:
                    value=self.receipt();value['results'][variant][key]=bad;self.reject(value)
    def test_sanitizers_cannot_be_removed(self):
        for bad in ([],['address'],['undefined'],['undefined','address']):
            value=self.receipt();value['sanitizers']=bad;self.reject(value)
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):gate.parse('{"schema":1,"schema":1}')
    def test_exact_sealed_inputs(self):self.validate(self.inputs())
    def test_digest_mismatch_rejected(self):
        with self.assertRaises(ValueError):gate.validate_inputs((ROOT/'inputs-sidesign.json').read_bytes(),'a'*64,ROOT.parents[1])
    def test_old_or_altered_ak_identity_rejected(self):
        for key in ('commit','tree'):
            value=self.inputs();value['owners']['AnisetteKit'][key]='a'*40
            with self.assertRaises(ValueError):self.validate(value)
    def test_historical_execution_claim_rejected(self):
        value=self.inputs();value['historical_basis']['fresh_guest_execution']=True
        with self.assertRaises(ValueError):self.validate(value)
    def test_omitted_defensive_delta_rejected(self):
        value=self.inputs();value['owners']['AnisetteKit']['changes'].pop('Native/Loader/cxx_allocation_runtime.h')
        with self.assertRaises(ValueError):self.validate(value)
    def test_side_sign_source_change_rejected(self):
        value=self.inputs();value['owners']['SideSign']['changes']['Sources/SideSign.swift']=copy.deepcopy(value['owners']['SideSign']['changes']['Package.swift'])
        with self.assertRaises(ValueError):self.validate(value)
    def test_phase_one_must_preserve_old_lock(self):
        value=self.inputs();value['owners']['SideSign']['changes']['Package.resolved']=copy.deepcopy(value['owners']['SideSign']['changes']['Package.swift'])
        with self.assertRaises(ValueError):self.validate(value)
    def test_adapter_rehash_cannot_hide_missing_adapter(self):
        value=self.inputs();value['adapter_files'].pop('ci/p0cxx/source_primitives.py')
        with self.assertRaises(ValueError):self.validate(value)
    def test_guest_entrypoints_absent(self):
        self.assertFalse(hasattr(gate.Gate,'native83'));self.assertFalse(hasattr(gate.Gate,'constructor_diagnostics'))
        text=(ROOT/'native_gate.py').read_text()
        self.assertNotIn("fixtures/android_tls_constructor.cpp",text)
        self.assertNotIn("test_constructor_diagnostics_driver.py",text)
    def test_exact_host_boundary_suite(self):
        text='\n'.join(f'{n} (__main__.MaintainedAnisetteNativeTests.{n}) ... ok' for n in gate.ANISETTE_BOUNDARY_CASES)+'\nRan 8 tests in 1.0s\nOK\n'
        self.assertEqual(gate.verify_anisette_boundary_output(text)['checks'],8)
        for bad in (text.replace(' ... ok',' ... skipped',1),text.replace('Ran 8','Ran 7'),text.replace('OK\n','OK (skipped=1)\n'),text+text):
            with self.assertRaises(ValueError):gate.verify_anisette_boundary_output(bad)
    def test_metadata_receipt_cannot_replace_real_macos_execution(self):
        value=self.inputs()
        with tempfile.TemporaryDirectory() as d:
            g=gate.Gate(value,ROOT.parents[1],Path(d)/'work',Path(d)/'evidence','a'*64)
            from unittest import mock
            with mock.patch.object(gate.platform,'system',return_value='Linux'), self.assertRaises(ValueError):g.execute(None)
    def test_lock_rejects_unrelated_pin_drift(self):
        g=gate.Gate(self.inputs(),ROOT.parents[1],Path('/tmp/work'),Path('/tmp/evidence'),'a'*64)
        old={'version':3,'pins':[{'identity':'anisettekit','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':'b'*40}},{'identity':'other','state':{'revision':'c'*40}}]}
        new=copy.deepcopy(old);new['pins'][0]['state']['revision']=gate.AK_COMMIT
        g.check_lock(json.dumps(old).encode(),json.dumps(new).encode())
        new['pins'][1]['state']['revision']='d'*40
        with self.assertRaises(ValueError):g.check_lock(json.dumps(old).encode(),json.dumps(new).encode())
    def test_generic_upstream_build_excludes_this_branch(self):
        text=(ROOT.parents[1]/'.github/workflows/build.yml').read_text()
        self.assertIn('validation/p0-cxx-allocation, validation/p0-cxx-allocation-linux]',text)
    class Child:
        pid=424242
        def __init__(self,code=None,poll_exit=False):
            self.returncode=code;self.poll_exit=poll_exit;self.events=[]
        def poll(self):
            self.events.append('poll')
            if self.poll_exit:self.returncode=0
            return self.returncode
        def communicate(self,timeout):
            self.events.append('communicate');self.returncode=0
            return ('retained stdout','retained stderr')
        def wait(self,timeout):
            self.events.append('wait');self.returncode=0;return 0
    def cleanup(self,child,surviving=False,denied=False,pgid=424242):
        from unittest import mock
        calls=[]
        def kill(group,sig):
            calls.append((group,sig,child.returncode))
            if sig:
                self.assertIsNone(child.returncode,'nonzero signal after child reap')
                child.events.append('signal-'+str(int(sig)))
            elif denied:raise PermissionError('denied')
            elif not surviving:raise ProcessLookupError('gone')
        ticks=iter(range(100))
        with mock.patch.object(gate.os,'killpg',side_effect=kill), mock.patch.object(gate.os,'getpgid',return_value=pgid), mock.patch.object(gate.signal,'getsignal',return_value=gate.signal.SIG_DFL), mock.patch.object(gate.time,'sleep',side_effect=lambda seconds:child.events.append('sleep')), mock.patch.object(gate.time,'monotonic',side_effect=lambda:next(ticks)):
            return gate.finish_owned_child(child),calls
    def test_reaped_child_never_signaled(self):
        result,calls=self.cleanup(self.Child(code=0))
        self.assertFalse([c for c in calls if c[1]])
        self.assertTrue(result['ownedProcessGroup']['quiescent'])
    def test_unreaped_identity_held_through_all_signals(self):
        child=self.Child();result,calls=self.cleanup(child)
        self.assertEqual(child.events,['poll','signal-15','sleep','signal-9','communicate'])
        self.assertTrue(result['ownedProcessGroup']['leaderReaped'])
        self.assertTrue(result['ownedProcessGroup']['identityRetainedForSignals'])
    def test_poll_reaped_group_is_read_only_failure(self):
        result,calls=self.cleanup(self.Child(poll_exit=True),surviving=True)
        self.assertFalse([c for c in calls if c[1]])
        self.assertIn('quiescenceError',result)
    def test_surviving_group_never_killed_after_reap(self):
        result,calls=self.cleanup(self.Child(code=0),surviving=True)
        self.assertFalse([c for c in calls if c[1]])
        self.assertFalse(result['ownedProcessGroup']['quiescent'])
    def test_unknown_group_does_not_count_as_disappeared(self):
        result,calls=self.cleanup(self.Child(code=0),denied=True)
        self.assertIn('quiescenceError',result)
        self.assertFalse(result['ownedProcessGroup']['quiescent'])
    def test_wrong_group_blocks_all_signals(self):
        result,calls=self.cleanup(self.Child(),pgid=999)
        self.assertFalse([c for c in calls if c[1]])
        self.assertIn('quiescenceError',result)
    def test_primary_timeout_survives_cleanup_zero_exit(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'logs').mkdir()
            g=gate.Gate(self.inputs(),ROOT.parents[1],root/'work',root,'a'*64)
            child=self.Child(poll_exit=True)
            child.communicate=mock.Mock(side_effect=[gate.subprocess.TimeoutExpired('fixture',1,output=b'partial'),('final','')])
            def gone(*args):raise ProcessLookupError('gone')
            with mock.patch.object(gate.subprocess,'Popen',return_value=child), mock.patch.object(gate.os,'killpg',side_effect=gone) as kill, mock.patch.object(gate.signal,'getsignal',return_value=gate.signal.SIG_DFL):
                with self.assertRaises(gate.subprocess.TimeoutExpired):g.run('timeout-fixture',['fixture'],timeout=1)
            self.assertEqual((root/'logs/timeout-fixture.exit-code.txt').read_text(),'124\n')
            report=json.loads((root/'logs/timeout-fixture.settlement.json').read_bytes())
            self.assertIsNone(report['returncode']);self.assertEqual(report['terminationReturncode'],0)
            self.assertTrue(all(call.args[1]==0 for call in kill.call_args_list))
    def test_custom_sigchld_blocks_process_start(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'logs').mkdir();g=gate.Gate(self.inputs(),ROOT.parents[1],root/'work',root,'a'*64)
            with mock.patch.object(gate.subprocess,'Popen') as popen, mock.patch.object(gate.signal,'getsignal',return_value=gate.signal.SIG_IGN):
                with self.assertRaises(ValueError):g.run('bad-handler',['fixture'])
            popen.assert_not_called()
    def test_lock_after_retained_before_validation_failure(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'SideSign';source.mkdir();(source/'Package.resolved').write_bytes(b'before')
            evidence=root/'evidence';(evidence/'provenance').mkdir(parents=True)
            g=gate.Gate(self.inputs(),ROOT.parents[1],root/'work',evidence,'a'*64);g.roots={'SideSign':source}
            def run(*args,**kw):(source/'Package.resolved').write_bytes(b'actual invalid resolver output')
            with mock.patch.object(g,'run',side_effect=run), mock.patch.object(g,'check_lock',side_effect=ValueError('lock rejected')):
                with self.assertRaisesRegex(ValueError,'lock rejected'):g.sidesign()
            self.assertEqual((evidence/'provenance/Package.resolved.before').read_bytes(),b'before')
            self.assertEqual((evidence/'provenance/Package.resolved.after').read_bytes(),b'actual invalid resolver output')
    def test_available_partial_lock_retained_without_success_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'SideSign';source.mkdir();(source/'Package.resolved').write_bytes(b'partial')
            evidence=root/'evidence';(evidence/'provenance').mkdir(parents=True)
            g=gate.Gate(self.inputs(),ROOT.parents[1],root/'work',evidence,'a'*64);g.roots={'SideSign':source};g.retain_available_locks()
            report=json.loads((evidence/'provenance/final-observed-locks.json').read_bytes())
            self.assertEqual(report['SideSign']['status'],'OBSERVED_BYTES_ONLY')
            self.assertEqual((evidence/report['SideSign']['path']).read_bytes(),b'partial')
    def transport_fixture(self,root):
        gate.dump(root/'provenance/result.json',{'writers_quiescent':True,'retention_errors':[]})
        gate.dump(root/'provenance/owned-command-groups.json',[{'label':'fixture','quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}])
        index={str(p.relative_to(root)):gate.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
        gate.dump(root/'evidence-index.json',index)
    def test_transport_requires_positive_settlement(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.transport_fixture(root)
            self.assertEqual(gate.verify_transport(root)['status'],'QUIESCENT_INDEX_VERIFIED')
            gate.dump(root/'provenance/result.json',{'writers_quiescent':False,'retention_errors':[]})
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_transport_rejects_unindexed_or_changed_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.transport_fixture(root);(root/'extra').write_text('unindexed')
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_transport_rejects_missing_group_proof_even_if_rehashed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.transport_fixture(root)
            gate.dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':False,'leaderReaped':True}])
            index={str(p.relative_to(root)):gate.sha(p.read_bytes()) for p in root.rglob('*') if p.is_file() and p.name!='evidence-index.json'}
            gate.dump(root/'evidence-index.json',index)
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_workflow_upload_requires_transport_gate(self):
        text=(ROOT.parents[1]/'.github/workflows/p0-cxx-allocation.yml').read_text()
        self.assertIn("if: always() && steps.transport.outputs.settled == 'true'",text)
        self.assertIn('--check-transport',text)
    def test_historical_fingerprint_alteration_rejected(self):
        value=self.inputs();value['historical_basis']['fingerprints_sha256']='a'*64
        with self.assertRaises(ValueError):self.validate(value)
if __name__=='__main__':unittest.main()
