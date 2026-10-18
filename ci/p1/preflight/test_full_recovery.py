import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture
import process_scope
import budget

class FullRecovery(unittest.TestCase):
    def test_profiles_fixed_and_disjoint(self):
        for kwargs,observation,cleanup in [({'phone_ui':True},1020,1140),({'full_recovery':True},3000,3120)]:
            with tempfile.TemporaryDirectory() as tmp,mock.patch.object(process_scope.time,'monotonic',return_value=100):
                s=process_scope.Scope(Path(tmp),**kwargs)
                self.assertEqual(s.deadline,100+observation);self.assertEqual(s.cleanup_deadline,100+cleanup)
                with mock.patch.object(process_scope.time,'monotonic',return_value=101+cleanup):
                    with self.assertRaises(TimeoutError):s.remaining(15,cleanup=True)
        with tempfile.TemporaryDirectory() as tmp:
            for flags in [{'phone_ui':True,'full_recovery':True},{'stall_diagnostic':True,'full_recovery':True}]:
                with self.assertRaises(ValueError):process_scope.Scope(Path(tmp),**flags)
        with self.assertRaises(ValueError):budget.run([],Path('/tmp/unused'),seconds=3180)
        with self.assertRaises(ValueError):budget.run([],Path('/tmp/unused'),seconds=1200,full_recovery=True)
    def test_exact_original_full_methods_and_verifier(self):
        for full,limit,wait in [(False,'180',480),(True,'600',2400)]:
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp)/'recovery';calls=[];scope=mock.Mock()
                def command(*args,**kwargs):
                    calls.append((args,kwargs))
                    if args[:4]==('xcrun','simctl','list','devices'):return json.dumps({'devices':{'runtime':[{'udid':'device','state':'Booted'}]}})
                    if args[:2]==('xcodebuild','test-without-building'):(folder/'tests.xcresult').mkdir()
                    return '{}'
                command.scope=scope
                with mock.patch.object(capture,'stop_fixture',return_value=True),mock.patch.object(capture.base,'inventory'),mock.patch.object(capture.video.layout_exports,'verify',return_value={'full':True}) as verify,mock.patch.object(capture.video.layout_exports,'verify_capabilities',return_value={'short':True}) as short:
                    result=capture.run_layout(command,Path('recipe'),'device','phone',folder,lambda _:True,full_recovery=full)
                self.assertTrue(result['collection_complete']);self.assertFalse(result['full_matrix_complete']);self.assertFalse(result['admissionEligible'])
                args,kw=next(c for c in calls if c[0][0]=='xcodebuild')
                self.assertEqual(kw['timeout'],wait);self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],limit)
                methods=capture.video.layout_exports.METHODS if full else capture.video.layout_exports.CAPABILITY_METHODS['phone']
                self.assertEqual([a for a in args if str(a).startswith('-only-testing:')],['-only-testing:P0SignInUITests/P1RecoveryLayoutUITests/'+m for m in methods])
                self.assertEqual(verify.call_count,int(full));self.assertEqual(short.call_count,int(not full))
    def test_reviewed_full_recovery_sources_match_sealed_digests(self):
        root=Path(__file__).resolve().parents[3]
        # Reviewed immutable source digests, not an acceptance substitute.
        import hashlib
        expected=json.loads((Path(__file__).parent/'full-recovery-baseline.json').read_text())
        for path,digest in expected.items():self.assertEqual(hashlib.sha256((root/path).read_bytes()).hexdigest(),digest)
    def test_cleanup_failure_revokes_phone_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            result={'errors':[],'collection_complete':True,'capabilities_passed':True,'phone_recovery_matrix_passed':True}
            scope=mock.Mock();scope.fixture=None;scope.close.side_effect=RuntimeError('unsettled')
            capture.finalize(Path(tmp),result,None,scope,None,False)
            self.assertFalse(result['phone_recovery_matrix_passed']);self.assertFalse(result['collection_complete'])

if __name__=='__main__':unittest.main()
