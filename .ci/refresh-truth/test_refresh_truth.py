from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / 'SideStoreSupport/SideStore.swift'
SHELL = ROOT / 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
APP = ROOT / 'LiveContainerSwiftUI/App/AppDelegate.swift'
HISTORY = ROOT / 'LiveContainerSwiftUI/Views/Settings/LCEmbeddedSideStoreRefreshView.swift'

def block(text, marker):
    start = text.index(marker)
    opening = text.index('{', start)
    depth = 1
    for end in range(opening + 1, len(text)):
        if text[end] == '{': depth += 1
        elif text[end] == '}': depth -= 1
        if depth == 0: return text[start:end+1]
    raise AssertionError(marker)

class RefreshTruthTests(unittest.TestCase):
    def test_production_gates_and_projections(self):
        source, shell, app, history = (p.read_text() for p in [SUPPORT, SHELL, APP, HISTORY])
        self.assertIn('V3RefreshProfileEvidence(entry["verification"])', source)
        self.assertIn('item["verification"] = evidence.wire', source)
        self.assertIn('V3RefreshEvidencePolicy.outcome(manifest, runID: runID).isVerified', app)
        self.assertIn('let requiresExplicitRetry = mutationUnclear || terminalEvidence != nil ||', app)
        self.assertIn('guard !retryBlocked, !profileMutationObserved', shell)
        self.assertIn('outcomeUnknown: V3OperationReplyFieldPolicy.outcomeUnknown(reply["outcomeUnknown"]) || profileMutationObserved', shell)
        self.assertIn('if let outcome = directRenewalOutcome, !outcome.isVerified', shell)
        hooks = (ROOT/'SideStoreSupport/SideStoreHooks.m').read_text()
        self.assertIn('return @"com.kdt.livecontainer";', hooks)
        self.assertIn('public static let originalHostID = "com.kdt.livecontainer"', source)
        self.assertIn('V3RefreshNotificationLocalization.translate = { V3Localization.string($0) }', app)
        callback=block(source,'    func add(_ request: UNNotificationRequest)')
        self.assertLess(callback.index('launchIDForCallbacks == self.identity'),callback.index('V3RefreshNotificationLocalization.localized(request)'))
        acknowledgement=block(app,'    static func acknowledgeUncertaintyAfterUserDeviceCheck(')
        self.assertLess(acknowledgement.index('defaults.set(true, forKey: manualOnlyAfterUncertaintyKey)'),acknowledgement.index('defaults.removeObject(forKey: uncertainMutationKey)'))
        for forbidden in ['performRefresh(', 'beginRun(', 'lastSuccessfulKey', 'satisfiedDeadlineKey', 'saveRunRecord(']: self.assertNotIn(forbidden,acknowledgement)
        self.assertNotIn('Previous mutation completion was uncertain. This user-requested attempt',app)
        self.assertIn('if defaults.string(forKey: "liveContainerAutoRefreshUncertainMutationRunID") != nil',shell)
        self.assertIn('summary["renewal_outcome"] = outcome.rawValue', app)
        self.assertIn('summary["acknowledged_count"]', app)
        self.assertIn('notify(title: evidenceOutcome?.title ?? "Refresh failed"', app)
        self.assertIn('result: evidenceOutcome?.rawValue ?? result', app)
        self.assertIn('V3RefreshEvidencePolicy.presentationOutcome(value, runID: runID) == nil', shell)
        self.assertIn('verification = V3SetupStepState(state: "failed", detail: outcome.message)', shell)
        for text in [shell, source]:
            self.assertIn('"renewal_outcome=\\(V3RefreshEvidencePolicy.recordedOutcome', text)
        for key in ['installedUnchanged','acknowledgedUnverified','verificationFailed','unconfirmed']:
            self.assertIn('"'+key+'":', history)
        for marker in ['enum V3RefreshAllTerminalEvidencePolicy', 'enum V3HomeRefreshVerificationPolicy', 'struct V3RefreshAllAttemptState']:
            self.assertEqual(block(source,marker), block(shell,marker), marker)

    def test_localization_coverage(self):
        catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
        keys=json.loads((Path(__file__).parent/'localization_keys.json').read_text())
        for key in keys:
            self.assertEqual(set(catalog[key]['localizations']),{'en','he','ru','zh-Hans','zh-Hant'})
            for locale, unit in catalog[key]['localizations'].items():
                def visit(value):
                    if 'stringUnit' in value:
                        self.assertEqual(value['stringUnit']['state'],'translated')
                        self.assertTrue(value['stringUnit']['value'])
                        self.assertEqual(value['stringUnit']['value'].count('%lld'),key.count('%lld'))
                    for child in value.values():
                        if isinstance(child,dict): visit(child)
                visit(unit)
        self.assertEqual(len(keys),len(set(keys)))

    @unittest.skipUnless(shutil.which('swiftc'), 'Native Swift execution required on macOS CI')
    def test_actual_source_runtime(self):
        source, shell = SUPPORT.read_text(), SHELL.read_text()
        combined = block(source, 'public enum CombinedVerification')

        snippets = [block(source,marker) for marker in ['public enum V3RefreshTransportObservation','public enum V3RefreshRenewalOutcome','public struct V3RefreshProfileEvidence','public enum V3HostProfileRenewalProof','public enum V3RefreshEvidencePolicy','public enum V3DirectProfileVerificationPolicy','public struct V3RefreshUncertaintyTicket','public enum V3RefreshUncertaintyAcknowledgmentPolicy']]
        snippets += [combined]
        snippets += [block(shell,marker) for marker in ['enum V3RefreshAllPhase','enum V3RefreshAllTerminalEvidencePolicy','enum V3HomeRefreshVerificationPolicy','struct V3RefreshAllAttemptState']]
        stub = """struct CombinedFailure {
 enum Stage: String { case command, refreshVerification }
 struct SourceStep { let rawValue: String }
 let operation = "refresh"; let safeMessage = "unexpected generic failure"
 let stage: Stage = .command; let sourceStep: SourceStep? = nil
 let underlyingDomain = "redacted"; let underlyingCode = 0
 let message = "fixture error"; let localizedDescription = "fixture error"; let wire: [String:Any] = [:]
 static func decode(_ raw: [String: Any], expectedID: String) -> CombinedFailure? { nil }
 static func capture(_ error: NSError, operation: String, stage: Stage, id: String) -> CombinedFailure { CombinedFailure() }
 static func safeWireUnderlying(domain: String, code: Int) -> (domain: String, code: Int) { ("redacted", 0) }
}"""
        program = 'import Foundation\nimport CoreFoundation\n' + stub + '\n' + '\n'.join(snippets) + '\n' + (Path(__file__).parent/'runtime_cases.swift').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); swift=root/'main.swift'; binary=root/'cases'
            swift.write_text(program)
            compiled=subprocess.run(['swiftc',str(swift),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(compiled.returncode,0,compiled.stdout+'\n'+compiled.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertIn('REFRESH_TRUTH_RUNTIME_PASS',result.stdout)
            self.assertEqual(result.stdout.count('PASS '),len([line for line in (Path(__file__).parent/'runtime_cases.swift').read_text().splitlines() if line.startswith('expect(')]),result.stdout)
            print(result.stdout)

    @unittest.skipUnless(shutil.which('swiftc'), 'Native UserNotifications execution required on macOS CI')
    def test_actual_notification_forwarding(self):
        helper=block(SUPPORT.read_text(),'public enum V3RefreshNotificationLocalization')
        program='import Foundation\nimport UserNotifications\n@MainActor\n'+helper+'\n'+(Path(__file__).parent/'notification_cases.swift').read_text()
        catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
        keys=['Refresh Results','The operation completed. Open the app to review verification and expiration.']
        translations={lang:{key:catalog[key]['localizations'][lang]['stringUnit']['value'] for key in keys} for lang in ['en','he','ru','zh-Hans','zh-Hant']}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); swift=root/'fixture.swift'; binary=root/'notification'; fixture=root/'catalog.json'
            swift.write_text(program); fixture.write_text(json.dumps(translations,ensure_ascii=False))
            compiled=subprocess.run(['swiftc','-parse-as-library',str(swift),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(compiled.returncode,0,compiled.stdout+'\n'+compiled.stderr)
            result=subprocess.run([str(binary),str(fixture)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
            self.assertEqual(result.stdout.count('PASS '),7,result.stdout)
            self.assertIn('REFRESH_NOTIFICATION_RUNTIME_PASS',result.stdout)
            print(result.stdout)


    @unittest.skipUnless(shutil.which('swiftc'), 'Native two-module compilation required on macOS CI')
    def test_ticket_cross_module_visibility(self):
        source = SUPPORT.read_text()
        ticket = block(source, 'public struct V3RefreshUncertaintyTicket')
        policy = block(source, 'public enum V3RefreshUncertaintyAcknowledgmentPolicy')
        initializer = block(ticket, '    public init(runID: String, updatedAt: Double)')
        self.assertIn('V3RefreshUncertaintyTicket(runID: runID, updatedAt: updated.doubleValue)', APP.read_text())
        program = (Path(__file__).parent/'ticket_module_cases.swift').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for current in [False, True]:
                folder=root/('current' if current else 'before'); folder.mkdir()
                module=folder/'SideStoreSupport.swift'; client=folder/'main.swift'; obj=folder/'SideStoreSupport.o'; binary=folder/'cases'
                declaration=ticket if current else ticket.replace(initializer,'')
                module.write_text('import Foundation\nimport CoreFoundation\n'+declaration+'\n'+policy)
                client.write_text(program)
                command=['swiftc','-parse-as-library','-emit-object','-emit-module','-module-name','SideStoreSupport',str(module),'-emit-module-path',str(folder/'SideStoreSupport.swiftmodule'),'-o',str(obj)]
                compiled=subprocess.run(command,capture_output=True,text=True,timeout=120)
                self.assertEqual(compiled.returncode,0,compiled.stdout+'\n'+compiled.stderr)
                linked=subprocess.run(['swiftc','-I',str(folder),str(client),str(obj),'-o',str(binary)],capture_output=True,text=True,timeout=120)
                if not current:
                    self.assertNotEqual(linked.returncode,0,'Old internal memberwise initializer unexpectedly exported')
                    self.assertIn('inaccessible',linked.stderr)
                    continue
                self.assertEqual(linked.returncode,0,linked.stdout+'\n'+linked.stderr)
                result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                self.assertIn('TICKET_CROSS_MODULE_PASS',result.stdout)
                print(result.stdout)

if __name__ == '__main__': unittest.main()
