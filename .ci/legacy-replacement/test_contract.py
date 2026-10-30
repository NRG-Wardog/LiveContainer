"""Exact host policy/wire/restart fixture. No provider, app install or device execution."""
from pathlib import Path
import importlib.util,json,os,re,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
HOST=ROOT/'SideStoreSupport/SideStore.swift'
UI=ROOT/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
spec=importlib.util.spec_from_file_location('legacy_wire',ROOT/'.ci/comprehensive-diagnostics/generate_wire_fixture.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
ANCHORS=('struct V3LegacyReplacementCandidate:', 'enum V3LegacyReplacementPolicy {', 'struct V3LegacyReplacementAttempt {', 'struct V3LegacyReplacementConfirmation {')
def generated():
    host,ui=HOST.read_text(),UI.read_text()
    model=g.pure_model(host)
    model += '\n'+g.block(host,'enum V3WireContract {')
    return 'import Foundation\nimport CoreFoundation\n'+g.block(host,'public struct V3AuthServiceSnapshot:')+'\n'+model+'\n'+ '\n'.join(g.block(ui,a) for a in ANCHORS)+'\n'+g.block(host,'struct V3OperationRecoveryRecord:')+'\n'+(HERE/'cases.swift').read_text()
def expected_names():
    names=[]
    for line in (HERE/'cases.swift').read_text().splitlines():
        if line.startswith('check('):
            found=re.search(r',\s*"([^"\\]+)"\)\s*$',line)
            if not found: raise ValueError('Unbound runtime case name: '+line)
            names.append(found.group(1))
    names += ['malformed_assessment_'+str(i) for i in range(10)]
    names += ['finite_refusal_'+x for x in sorted(['notEligible','busy','sourceUnavailable','sourceChanged','identityUnavailable','identityMismatch','certificateUnavailable','certificateMismatch','staleAssessment'])]
    return names
class LegacyReplacementTests(unittest.TestCase):
    def test_actual_source_closure_and_wiring(self):
        swift=generated();host,ui=HOST.read_text(),UI.read_text()
        for anchor in ANCHORS:self.assertEqual(swift.count(g.block(ui,anchor)),1)
        self.assertIn(g.block(host,'public enum V3DirectProfileVerificationPolicy {'),swift)
        self.assertIn(g.block(host,'enum V3WireContract {'),swift)
        self.assertEqual(g.block(host,'struct V3OperationRecoveryRecord:'),g.block(ui,'struct V3OperationRecoveryRecord:'))
        action=g.block(ui,'struct V3LegacyReplacementAction:')
        self.assertIn('legacyReplacementPrepare',action)
        self.assertIn('confirmation.take(current: current, foreground: scenePhase == .active)',action)
        self.assertIn('confirmation.cancel()',action)
        self.assertNotIn('opStart',action)
        self.assertNotIn('NSLog',action);self.assertNotIn('print(',action)
        self.assertIn('legacyReplacementConsent: true',action)
        run=g.block(ui,'    private func run(generation: UUID) async')
        self.assertLess(run.index('operation: "opRecoveryPrepare"'),run.index('operation: "opStart"'))
        self.assertIn('guard request.legacyReplacementConsent else { throw CancellationError() }',run)
        self.assertIn('startPayload["userConfirmed"] = true',run)
        self.assertIn('guard request.operation != "legacyReplacement", !retryBlocked',ui)
        self.assertNotIn('clearUncertainty',action)
        names=expected_names();self.assertEqual(len(names),len(set(names)))
    def test_mirrored_wire_and_journal(self):
        ss=Path(os.environ.get('SIDESTORE_SOURCE_ROOT',str(ROOT.parent/'SideStore')))/'AltStore/AppDelegate.swift'
        self.assertTrue(ss.is_file(),'Exact candidate SideStore source required for mirror check')
        host=HOST.read_text();service=ss.read_text()
        for anchor in ('enum V3WireContract {','struct V3OperationRecoveryRecord:'):
            self.assertEqual(g.block(host,anchor),g.block(service,anchor))
    def test_five_locale_risk_copy(self):
        keys=json.loads((HERE/'localization_keys.json').read_text())
        self.assertEqual(len(keys),16);self.assertEqual(len(keys),len(set(keys)))
        catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
        ui=UI.read_text()
        for key in keys:
            self.assertIn(json.dumps(key,ensure_ascii=False),ui)
            self.assertEqual(set(catalog[key]['localizations']),{'en','he','ru','zh-Hans','zh-Hant'})
            for lang,entry in catalog[key]['localizations'].items():
                unit=entry['stringUnit'];self.assertEqual(unit['state'],'translated');self.assertTrue(unit['value'].strip())
                if lang!='en':self.assertNotEqual(unit['value'],key)
                self.assertEqual(re.findall(r'%[@dfsu]',unit['value']),re.findall(r'%[@dfsu]',key))
    @unittest.skipUnless(shutil.which('swiftc'),'Actual Swift execution requires native CI')
    def test_actual_source_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'main.swift';exe=root/'cases';source.write_text(generated())
            result=subprocess.run(['swiftc',str(source),'-o',str(exe)],capture_output=True,text=True,timeout=180)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            observed=[line[5:] for line in result.stdout.splitlines() if line.startswith('PASS ')]
            self.assertEqual(sorted(observed),sorted(expected_names()));self.assertIn('LEGACY_REPLACEMENT_HOST_PASS',result.stdout)
            print(result.stdout)
if __name__=='__main__':unittest.main()
