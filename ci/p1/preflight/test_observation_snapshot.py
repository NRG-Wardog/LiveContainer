import hashlib,json,unittest,tempfile
from pathlib import Path
import capture
from test_layout_capabilities import CapabilityFixture

class SnapshotObservation(unittest.TestCase):
    def test_each_call_uses_fresh_snapshot_and_live_identity(self):
        text=(Path(capture.HERE).parent/'video/recovery_ui_tests.swift').read_text()
        body=text[text.index('    @MainActor private func observe('):text.index('    private func attach(')]
        self.assertEqual(body.count('try element.snapshot()'),1)
        self.assertIn('guard element.exists else { return ["exists": false] }',body)
        for token in ['let identifier = element.identifier','let type = element.elementType','let hittable = element.isHittable','snapshot.identifier == identifier, snapshot.elementType == type','"exists": true, "observationError": "identity-changed"','"exists": true, "observationError": "snapshot-failed"']:
            self.assertIn(token,body)
        for key in ['label','frame','value','isSelected']:
            self.assertIn('snapshot.'+key,body);self.assertNotIn('element.'+key,body)
        self.assertEqual(body.count('XCTFail('),2)
        self.assertEqual(body.count('"exists": false'),1)
        self.assertNotIn('static ',body)
    def test_original_matrix_methods_unchanged(self):
        import re
        text=(Path(capture.HERE).parent/'video/recovery_ui_tests.swift').read_text()
        expected={'testRecoveryBranchesDefault': '0116dc2df5e370c68f0bf723f014dd7f38570299e9cf2708170d148d68d187d5', 'testRecoveryBranchesLargest': '97e91e40bb245150ba4b23b0c5e601d3b06108fc1e471186683ebc77333d0330', 'testRecoveryCompactLandscape': 'c40a1caa3cc8eea65d0751ca29bad931059d8f3f40f96b3a9915634c11628d4d', 'testRecoveryStateAndSizeTransitions': '6daca8ecc4954048fade2dcf0a994a5633affc75232877be0879733b22e5d25d'}
        for name,digest in expected.items():
            start=text.index('    @MainActor func '+name+'(')
            match=re.search(r'\n    @MainActor (?:private |@discardableResult )*(?:func|var) ',text[start+1:])
            end=start+1+match.start() if match else len(text)
            self.assertEqual(hashlib.sha256(text[start:end].encode()).hexdigest(),digest)
    def test_nested_observer_error_cannot_be_treated_as_absence(self):
        for value in [{'exists':False,'observationError':'snapshot-failed'},{'tabs':[{'observationError':'identity-changed'}]},{'drag':{'after':{'observationError':'snapshot-failed'}}},{'callback':{'actual':{'observationError':'identity-changed'}}}]:
            with self.assertRaises(ValueError):capture.video.layout_exports.reject_observation_errors(value)
    def test_export_rejects_error_even_with_passed_native_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=CapabilityFixture(Path(tmp),'phone');self.assertTrue(f.verify()['collection_complete'])
            f.rows['capability-targets-initial']['content']['observationError']='snapshot-failed'
            with self.assertRaisesRegex(ValueError,'failed accessibility observation'):f.verify()

if __name__=='__main__':unittest.main()
