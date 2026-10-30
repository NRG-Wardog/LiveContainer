from pathlib import Path
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
HOST=ROOT/'SideStoreSupport/SideStore.swift'
UI=ROOT/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
APP=ROOT/'LiveContainerSwiftUI/App/AppDelegate.swift'
spec=importlib.util.spec_from_file_location('wire_extract',ROOT/'.ci/comprehensive-diagnostics/generate_wire_fixture.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
class ObservationTests(unittest.TestCase):
    def test_source_bindings(self):
        host,ui,app=HOST.read_text(),UI.read_text(),APP.read_text()
        sanitizer=g.block(host,'public enum CombinedVerification {')
        self.assertIn('V3RefreshTransportObservation.validated(manifest["transport_observation"])',sanitizer)
        self.assertNotIn('host_profile_verification',sanitizer)
        summary=g.block(app,'    private static func terminalManifestSummary(')
        self.assertIn('V3RefreshTargetDiagnostics.rows(manifest, runID: runID)',summary)
        policy=g.block(ui,'enum V3SetupConnectionEvidencePolicy {')
        self.assertIn('V3RefreshTransportObservation.recorded(in: record, runID: runID)',policy)
        self.assertNotIn('verifiedSummary(',policy)
        for text in [host,ui]:self.assertIn('V3RefreshTargetDiagnostics.copiedDetails(record, runID: runID)',text)
        failure=g.block(host,'public struct CombinedFailure:')
        self.assertIn('sourceStep == .refreshApplication',failure)
        self.assertIn('context.removeValue(forKey: "refresh_target_scope")',failure)
    def test_localization(self):
        keys=json.loads((Path(__file__).parent/'localization_keys.json').read_text())
        catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
        self.assertEqual(len(keys),len(set(keys)))
        for key in keys:
            self.assertEqual(set(catalog[key]['localizations']),{'en','he','ru','zh-Hans','zh-Hant'})
            for entry in catalog[key]['localizations'].values():
                self.assertEqual(entry['stringUnit']['state'],'translated');self.assertTrue(entry['stringUnit']['value'])
    @unittest.skipUnless(shutil.which('swiftc'),'Actual source Swift execution requires macOS CI')
    def test_actual_source(self):
        host,ui=HOST.read_text(),UI.read_text()
        source='import Foundation\nimport CoreFoundation\n'+g.pure_model(host)+'\n'
        source+='\n'.join(g.block(ui,x) for x in ['struct V3SetupStepState:', 'enum V3SetupConnectionCopy:', 'enum V3SetupConnectionEvidencePolicy {'])
        source+='\nenum ActualSummary {\n'+g.block(APP.read_text(),'    private static func terminalManifestSummary(').replace('private static','static',1)+'\n}\n'
        cases=(Path(__file__).parent/'cases.swift').read_text();source+='\n'+cases
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();swift=root/'main.swift';binary=root/'cases';swift.write_text(source)
            result=subprocess.run(['swiftc',str(swift),'-o',str(binary)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertEqual(result.stdout.count('PASS '),sum(line.startswith('check(') for line in cases.splitlines()))
            self.assertIn('REFRESH_OBSERVATIONS_PASS',result.stdout);print(result.stdout)
if __name__=='__main__':unittest.main()
