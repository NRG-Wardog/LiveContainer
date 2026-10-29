"""Typed startup cards: production projection and same-instance UI state boundaries.

No database or device is opened. Swift execution is mandatory in native CI.
The SwiftUI body/copy action is source-checked; it is not a rendered-device test.
"""
import json, os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path
from test_startup_diagnostics import block, ROOT, HOST, UI, CAUSES


def fixture():
    source, ui = HOST.read_text(), UI.read_text()
    failure = block(source, 'public struct CombinedFailure:')
    pieces = ['import Foundation', 'struct CombinedFailure: Error {',
        block(failure, 'public enum Stage:'), block(failure, 'public enum Code:'),
        block(failure, 'public enum SafeCause:'),
        'let stage: Stage; let code: Code; let retryable: Bool?; let safeCause: SafeCause?',
        block(failure, 'public var isTerminalDatabaseStartupFailure:'),
        'var technicalDetails: String { "stage=" + stage.rawValue + " code=" + code.rawValue + " safe_cause=" + (safeCause?.rawValue ?? "unknown") }', '} ',
        block(ui, 'struct V3StartupDiagnosis: Equatable {'),
        '@MainActor final class Store { var startupDiagnosis: V3StartupDiagnosis?',
        block(ui, 'private func recordStartupDiagnosis(').replace('private func', 'func', 1),
        block(ui, 'private func clearStartupDiagnosisAfterReady()').replace('private func', 'func', 1), '}',
        '@main struct Cases { @MainActor static func main() {',
        'let cases: [CombinedFailure.SafeCause] = [' + ','.join('.'+c for c in CAUSES) + ']',
        '''let store = Store()
        var titles = Set<String>()
        for cause in cases {
            let failure = CombinedFailure(stage: .serviceReadiness, code: .failed, retryable: false, safeCause: cause)
            store.recordStartupDiagnosis(failure)
            guard let card = store.startupDiagnosis else { fatalError("missing typed card") }
            precondition(card.category == cause.rawValue)
            precondition(card.technical.contains("startup_category=" + cause.rawValue))
            precondition(!card.observation.isEmpty && !card.nextAction.isEmpty)
            titles.insert(card.title)
        }
        precondition(titles.count == 11)
        let stages: [CombinedFailure.Stage] = [.hostContainer, .storagePreparation, .bookmarkCreation, .extensionDiscovery, .extensionLaunch, .xpcConnection, .serviceReadiness]
        for stage in stages {
            let failure = CombinedFailure(stage: stage, code: .timedOut, retryable: nil, safeCause: nil)
            store.recordStartupDiagnosis(failure)
            precondition(store.startupDiagnosis?.category == stage.rawValue)
            precondition(store.startupDiagnosis!.observation.contains("exact cause is unknown"))
            precondition(!store.startupDiagnosis!.observation.contains("database is damaged"))
        }
        // A mismatched wire shape cannot become a diagnosed database failure.
        let malformedCodes: [CombinedFailure.Code] = [.notReady, .cancelled, .invalidResponse]
        for code in malformedCodes {
            let failure = CombinedFailure(stage: .serviceReadiness, code: code, retryable: true, safeCause: .databaseLayoutConflict)
            store.recordStartupDiagnosis(failure)
            precondition(store.startupDiagnosis?.category == "serviceReadiness")
        }
        let previous = store.startupDiagnosis
        store.recordStartupDiagnosis(NSError(domain: "SECRET_ACCOUNT_SENTINEL", code: 1))
        precondition(store.startupDiagnosis == previous)
        store.recordStartupDiagnosis(CombinedFailure(stage: .signing, code: .failed, retryable: false, safeCause: nil))
        precondition(store.startupDiagnosis == previous)
        store.clearStartupDiagnosisAfterReady()
        precondition(store.startupDiagnosis == nil)
        store.recordStartupDiagnosis(CombinedFailure(stage: .xpcConnection, code: .interrupted, retryable: false, safeCause: nil))
        precondition(store.startupDiagnosis?.category == "xpcConnection")
        store.clearStartupDiagnosisAfterReady()
        precondition(store.startupDiagnosis == nil)
        print("STARTUP_DIAGNOSIS_CARD_PASS typed=11 boundaries=7 unknown=7 malformed=3 same_instance_recovery=2")
        }}''']
    return '\n'.join(pieces)

class StartupDiagnosisCardTests(unittest.TestCase):
    def test_copy_is_available_without_service_or_network(self):
        ui = UI.read_text(); card = block(ui, 'struct V3StartupDiagnosisCard: View {')
        self.assertIn('UIPasteboard.general.string = diagnosis.technical + "\\n" + V3ServiceBridge.shared.startupDiagnosticText',card)
        for forbidden in ['.disabled(', 'await ', '.request(', '.connect(', 'localizedDescription', 'FileManager', 'UserDefaults']:
            self.assertNotIn(forbidden,card)
        self.assertIn('.onChange(of: diagnosis) { _ in copied = false }',card)
        self.assertIn('if let diagnosis = status.startupDiagnosis {\n                            V3StartupDiagnosisCard(diagnosis: diagnosis)',ui)

    def test_actual_store_records_typed_failure_and_only_clears_after_accepted_snapshot(self):
        ui=UI.read_text()
        self.assertIn('recordStartupDiagnosis(error)',block(ui,'func present(_ error: Error) {'))
        accept=block(ui,'func accept(_ snapshot: [String: Any]) -> Bool {')
        self.assertLess(accept.index('statusReplyMayApply(snapshot)'),accept.index('clearStartupDiagnosisAfterReady()'))
        self.assertLess(accept.index('connected = true'),accept.index('clearStartupDiagnosisAfterReady()'))
        self.assertNotIn('startupDiagnosis',block(ui,'func clearIssue() {'))
        self.assertEqual(ui.count('clearStartupDiagnosisAfterReady()'),2)
        recorder=block(ui,'private func recordStartupDiagnosis(')
        self.assertIn('error as? CombinedFailure',recorder)
        self.assertNotIn('localizedDescription',recorder)

    def test_all_new_copy_translated_with_matching_format_tokens(self):
        ui=UI.read_text();model=block(ui,'struct V3StartupDiagnosis: Equatable {')
        keys=set(re.findall(r'(?:title|observation|action) = "([^"]+)"',model))|{'Startup problem'}
        catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
        self.assertGreaterEqual(len(keys),40)
        for key in keys:
            for lang in ['en','he','zh-Hans','zh-Hant','ru']:
                unit=catalog[key]['localizations'][lang]['stringUnit']
                self.assertEqual(unit['state'],'translated');self.assertTrue(unit['value'])
                self.assertEqual(re.findall(r'%(?:\d+\$)?[@dfsu]',key),re.findall(r'%(?:\d+\$)?[@dfsu]',unit['value']))
                if lang!='en':self.assertNotEqual(key,unit['value'])

    def test_production_projection_and_same_instance_state(self):
        generated=fixture()
        compiler=shutil.which('swiftc')
        if not compiler:
            if os.environ.get('REQUIRE_SWIFT_STARTUP_TESTS')=='1':self.fail('Swift compiler required')
            self.skipTest('Swift unavailable; native CI must execute production projection/state')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'main.swift';source.write_text(generated);binary=root/'cases'
            built=subprocess.run([compiler,'-parse-as-library',str(source),'-o',str(binary)],text=True,capture_output=True,timeout=90)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=20)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
            self.assertIn('STARTUP_DIAGNOSIS_CARD_PASS',ran.stdout)
            print(ran.stdout.strip())

if __name__=='__main__':unittest.main(verbosity=2)
