"""Issue56: execute extracted production startup boundaries; never opens a database.

Swift absence is a skip locally and a failure with REQUIRE_SWIFT_STARTUP_TESTS=1.
Only unrelated authentication context helpers and UI/transport state are doubles.
The actual readiness decoder/state machine, bootstrap log and UI methods execute.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'SideStoreSupport/SideStore.swift'
UI = ROOT / 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
CAUSES = ['databaseLayoutBlocked', 'databaseLayoutConflict', 'databaseAppGroupUnavailable',
          'databasePersistenceFailed', 'databaseStartupFailed', 'databaseHostBundleUnavailable', 'databaseHostProfileUnavailable', 'databaseModelUnrecognized', 'databaseMigrationPathUnavailable', 'databaseMigrationFailed', 'databaseSaveFailed']


def block(source, anchor):
    if source.count(anchor) != 1:
        raise AssertionError(('nonunique production anchor', anchor, source.count(anchor)))
    start = source.index(anchor)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def fixture():
    s, ui = HOST.read_text(), UI.read_text()
    wire = block(s, 'enum V3WireContract {')
    chunks = ['import Foundation\nimport CoreFoundation\n',
              'enum V3WireContract {\n' + re.search(r'    static let responseLimit = [0-9_]+', wire).group(0) + '\n' +
              block(wire, 'static func strictBool(') + '\n' +
              block(wire, 'static func strictInt(') + '\n}\n']
    for anchor in ['public struct V3StartupDiagnosticLog {', 'public enum V3OperationLogLoadPolicy {',
                   'enum V3ServiceReadinessReply:', 'struct V3ServiceReadinessFailure:',
                   'enum V3ServiceReadinessProbeState:', 'struct V3ServiceReadinessBackoff {']:
        chunks.append(block(s, anchor))
    model = block(s, 'public struct CombinedFailure:')
    chunks.append('public struct CombinedFailure: Error {\n' +
                  block(model, 'public enum Stage:') + '\n' +
                  block(model, 'public enum Code:') + '\n' +
                  block(model, 'public enum SafeCause:') + '\n' +
                  'let stage: Stage; let code: Code; let retryable: Bool?; let safeCause: SafeCause?\n' +
                  block(model, 'public var isTerminalDatabaseStartupFailure:') + '\n' +
                  block(model, 'private var databaseStartupMessage:') + '\n' +
                  'var message: String { databaseStartupMessage ?? "Non-startup fixture failure" }\n}')
    # These authentication-only helpers are not part of the tested startup envelope.
    chunks.append('''
struct V3TemporaryADIConsumption {
    static let contextKey = "test_auth_context"
    static func sanitizingContext(_ value: [String: String]) -> [String: String] { value }
}
enum V3TemporaryAnisetteTrace { static let contextKey = "test_anisette_context" }
enum V3LoginDiagnosticSnapshot { static let contextKey = "test_login_context" }
@MainActor final class V3ServiceBridge {
    static let shared = V3ServiceBridge()
    var startupDiagnosticText = ""
    var serviceReadyForOperationLogs = false
    var requests = 0
    var failure: Error?
    func request(operation: String) async throws -> [String: Any] {
        precondition(["logTail", "snapshot"].contains(operation))
        requests += 1
        if let failure { throw failure }
        return ["tail": "operation log fixture"]
    }
}
enum LCUtils { static func guestLaunchDiagnosticSnapshot() -> String { "guest_launch_schema=1\\nguest_launch_state=not_started" } }
enum V3FailureGuidance { static func message(_ error: Error) -> String { "Safe fixture failure" } }
@MainActor final class V3SideStoreStatusStore {
    var invalidations = 0
    var terminalStartupFailure: CombinedFailure?
    func invalidateSetupFacts() { invalidations += 1 }
}
''')
    logs = block(ui, 'struct V3LogsView: View {')
    reload = block(logs, 'private func reload() async').replace('private func', 'func', 1)
    chunks.append('@MainActor final class LogsHarness {\nvar tail = "", startup = "", message = ""\nvar reloading = false\n' + reload + '\n}')
    chunks.append(block(ui, 'struct V3SetupStepState:'))
    preserve = block(ui, 'private func preserveUnknownStatusFacts(').replace('private func', 'func', 1)
    chunks.append('''@MainActor final class SetupHarness {
        var statusProvisioningIncomplete = false
        var account = V3SetupStepState(), pairing = V3SetupStepState(), jitless = V3SetupStepState()
        var refreshes = 0
        func refreshConnectionEvidence() { refreshes += 1 }
    ''' + preserve + '\n}')
    chunks.append(block(ui, 'enum V3SnapshotErrorPolicy {'))
    snapshot = block(ui, 'private func performSnapshot() async').replace('private func', 'func', 1)
    chunks.append('''@MainActor final class SnapshotHarness {
        enum V3ReloadOutcome: Equatable { case applied, notObserved, snapshotFailed }
        struct InstallAttempt {
            enum Phase: String { case idle }
            let hasActiveAttempt = false
            let attemptID: UUID? = nil
            let phase = Phase.idle
        }
        var snapshotGeneration: UInt64 = 1
        var terminalStartupFailure: CombinedFailure?
        var connected = true, requiresConnectionRetry = false
        var finished: V3ReloadOutcome?
        var presented = 0
        let installAttempt = InstallAttempt()
        func accept(_ reply: [String: Any]) -> Bool { connected = true; requiresConnectionRetry = false; return true }
        func invalidateSetupFacts() {}
        func present(_ error: Error) { presented += 1 }
        func finishSnapshot(outcome: V3ReloadOutcome, generation: UInt64) { finished = outcome }
        func drainInstallPresentation(trigger: String) {}
        func observeSetupFactsIfNeeded() {}
    ''' + snapshot + '\n}')
    chunks.append((ROOT / 'tests/startup_diagnostics/cases.swift').read_text())
    return '\n'.join(chunks)


class StartupDiagnosticsTests(unittest.TestCase):
    def test_terminal_cause_vocabulary_and_copy(self):
        source = HOST.read_text()
        model = block(source, 'public struct CombinedFailure:')
        token = block(source, 'extension CombinedFailure.SafeCause {')
        for number, cause in enumerate(CAUSES, 69):
            self.assertIn(cause, model)
            self.assertIn(f'case .{cause}: return "F{number}"', token)
        self.assertIn('guard let safeCause else { return false }', model)
        self.assertIn('stage == .serviceReadiness && code == .failed && retryable == false', model)
        message = block(model, 'public var message: String {')
        self.assertLess(message.index('databaseStartupMessage'), message.index('catalogFailureMessage'))
        recovery = block(model, 'public var recovery: String {')
        self.assertLess(recovery.index('isTerminalDatabaseStartupFailure'), recovery.index('catalogFailureRecovery'))
        self.assertIn('do not delete, reset, or move its database as a workaround.', recovery)

    def test_failed_start_is_recorded_before_retirement(self):
        source = HOST.read_text()
        fail = block(source, 'fileprivate func failed(_ id: UUID, stage:')
        self.assertLess(fail.index('startupDiagnostics.record(.failed'), fail.index('service.fail(id, failure)'))
        retire = block(source, 'private func retire(_ id: UUID)')
        self.assertNotIn('startupDiagnostics', retire)
        log = block(source, 'public struct V3StartupDiagnosticLog {')
        for forbidden in ['localizedDescription', 'userInfo', 'FileManager', 'UserDefaults', 'NSLog']:
            self.assertNotIn(forbidden, log)
        self.assertIn('entries.removeFirst(entries.count - Self.capacity)', log)

    def test_logs_do_not_start_service(self):
        source, ui = HOST.read_text(), UI.read_text()
        request = block(source, 'public func request(operation: String, target:')
        branch = request.index('if operation == "logTail" {')
        guard = request.index('guard RefreshHandler.shared.v3ServiceIdentity != nil', branch)
        other = request.index('} else {\n                try await connect()', guard)
        self.assertLess(branch, guard)
        self.assertLess(guard, other)
        self.assertNotIn('await', request[guard:other])
        logs = block(ui, 'struct V3LogsView: View {')
        self.assertLess(logs.index('startup = V3ServiceBridge.shared.startupDiagnosticText'),
                        logs.index('guard V3OperationLogLoadPolicy.shouldRequestServiceLogs'))
        self.assertIn('V3OperationLogLoadPolicy.copyText(startup: startup, operations: tail)', logs)
        self.assertIn('Section("Startup Diagnostics")', logs)
        self.assertIn('V3OperationLogLoadPolicy.canCopy(reloading: reloading, startup: startup, operations: tail)', logs)

    def test_setup_terminal_failure_preserves_unknown_identity(self):
        ui = UI.read_text()
        snapshot = block(ui, 'private func performSnapshot() async')
        self.assertIn('startup?.isTerminalDatabaseStartupFailure == true ? startup : nil', snapshot)
        self.assertIn('if succeeded { terminalStartupFailure = nil }', snapshot)
        preserve = block(ui, 'private func preserveUnknownStatusFacts(')
        self.assertLess(preserve.index('if let failure = status.terminalStartupFailure'),
                        preserve.index('state: "checking"'))
        self.assertEqual(preserve.count('state: "failed"'), 3)
        self.assertNotIn('authenticated =', preserve)
        self.assertNotIn('Not signed in', preserve)

    def test_new_copy_is_localized_in_all_five_languages(self):
        catalog = json.loads((ROOT / 'Resources/Localizable.xcstrings').read_text())['strings']
        source, ui = HOST.read_text(), UI.read_text()
        copy = block(source, 'private var databaseStartupMessage:')
        keys = re.findall(r'return "([^"]+)"', copy)
        keys += ['Open Operation Logs and copy the startup diagnostics. Keep the existing app and its data; do not delete, reset, or move its database as a workaround.',
                 'Startup Diagnostics',
                 'Service operation logs are unavailable because startup is not complete. Available safe startup diagnostics are shown below.']
        self.assertEqual(len(keys), 14)
        for key in keys:
            for language in ['en', 'he', 'zh-Hans', 'zh-Hant', 'ru']:
                unit = catalog[key]['localizations'][language]['stringUnit']
                self.assertEqual(unit['state'], 'translated')
                self.assertTrue(unit['value'])
                if language != 'en': self.assertNotEqual(unit['value'], key)

    def test_production_foundation_and_actual_ui_method_boundaries(self):
        generated = fixture()  # Always verify production extraction, even without Swift.
        swift = shutil.which('swiftc')
        if not swift:
            if os.environ.get('REQUIRE_SWIFT_STARTUP_TESTS') == '1':
                self.fail('Swift compiler required for issue56 runtime boundaries')
            self.skipTest('Swift unavailable; production runtime boundaries not executed')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(strict=True)
            path = root / 'Fixture.swift'
            binary = root / 'startup-tests'
            path.write_text(generated)
            built = subprocess.run([swift, '-parse-as-library', str(path), '-o', str(binary)],
                                   text=True, capture_output=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], text=True, capture_output=True, timeout=20)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn('ISSUE56_HOST_BOUNDARIES_PASS', ran.stdout)
            print(ran.stdout.strip())


def load_tests(loader, tests, pattern):
    # Keep the source-owned native runner authoritative for the added card boundary.
    from test_startup_diagnosis_card import StartupDiagnosisCardTests
    tests.addTests(loader.loadTestsFromTestCase(StartupDiagnosisCardTests))
    return tests


if __name__ == '__main__':
    unittest.main(verbosity=2)
