"""Execute maintained registration consumer with device/portal/cellular IO doubles."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('SIDE_STORE_TEST_SOURCE', ROOT)) / 'SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift'


def consumer(source):
    start = source.index('    @discardableResult\n    private func registerCurrentDevice(')
    tail = source[start:]
    end = tail.index('\n    }\n') + len('\n    }\n')
    return tail[:end].replace('private func', 'func', 1)

HARNESS = r'''
import Foundation
struct ALTTeam {}
struct ALTAppleAPISession {}
struct ALTDevice { let identifier: String; let name = "PRIVATE_DEVICE_NAME" }
enum OperationError: Error { case unknownUDID }
enum DeviceTypes { case all }
final class QueryFailure: Error, @unchecked Sendable {
    let message = "PRIVATE_ERROR_PAYLOAD"
}
final class State: @unchecked Sendable {
    static let shared = State()
    let primaryError = QueryFailure(), fallbackError = QueryFailure(), portalError = QueryFailure()
    var primary: String? = "PRIVATE_DEVICE_ID", fallback: String? = "PRIVATE_DEVICE_ID"
    var failPrimary = false, failFallback = false, failPortal = false, known = true
    var off = 0, on = 0, primaryCalls = 0, fallbackCalls = 0, fetchCalls = 0, registerCalls = 0
    var events: [String] = [], logs: [String] = []
}
@MainActor final class UIDevice { static let current = UIDevice(); let name = "PRIVATE_DEVICE_NAME" }
final class CellularRefreshManager: @unchecked Sendable {
    static let shared = CellularRefreshManager()
    func turnOffDataIfNeeded() async { State.shared.off += 1; State.shared.events.append("off") }
    func turnOnDataIfNeeded(addOnDelay: Double) async {
        precondition(addOnDelay == 2.0)
        State.shared.on += 1; State.shared.events.append("on")
    }
}
func fetchUDID(useStatic: Bool = false) async throws -> String? {
    let s = State.shared
    if useStatic {
        precondition(s.on == 1)
        s.fallbackCalls += 1; s.events.append("fallback")
        if s.failFallback { throw s.fallbackError }; return s.fallback
    }
    precondition(s.off == 1 && s.on == 0)
    s.primaryCalls += 1; s.events.append("primary")
    if s.failPrimary { throw s.primaryError }; return s.primary
}
final class DeveloperPortalProxy: @unchecked Sendable {
    static let shared = DeveloperPortalProxy()
    static let currentDeviceType = 1
    func fetchDevices(for team: ALTTeam, types: DeviceTypes) async throws -> [ALTDevice] {
        let s = State.shared; precondition(s.on == 1); s.fetchCalls += 1
        if s.failPortal { throw s.portalError }
        return s.known ? [ALTDevice(identifier: "PRIVATE_DEVICE_ID")] : []
    }
    func registerDevice(name: String, identifier: String, type: Int, team: ALTTeam) async throws -> ALTDevice {
        let s = State.shared; precondition(s.on == 1); s.registerCalls += 1
        precondition(name == "PRIVATE_DEVICE_NAME" && identifier == "PRIVATE_DEVICE_ID" && type == 1)
        return ALTDevice(identifier: identifier)
    }
}
final class Probe {
    func debugLog(_ text: String) { State.shared.logs.append(text) }
__CONSUMER__
}
@main struct Main {
    static func main() async throws {
        let s = State.shared, scenario = CommandLine.arguments[1]
        var expectedError: QueryFailure?, expectUnknown = false, expectedFallback = 0
        switch scenario {
        case "primary-success": break
        case "primary-new-device": s.known = false
        case "fallback-after-error": s.failPrimary = true; expectedFallback = 1
        case "fallback-after-empty": s.primary = ""; expectedFallback = 1
        case "fallback-after-placeholder": s.primary = "XXXXX-XXXX-XXXXX-XXXX"; expectedFallback = 1
        case "fallback-after-nil": s.primary = nil; expectedFallback = 1
        case "both-errors": s.failPrimary = true; s.failFallback = true; expectedError = s.primaryError; expectedFallback = 1
        case "primary-error-fallback-empty": s.failPrimary = true; s.fallback = ""; expectedError = s.primaryError; expectedFallback = 1
        case "fallback-error": s.primary = nil; s.failFallback = true; expectedError = s.fallbackError; expectedFallback = 1
        case "both-empty": s.primary = ""; s.fallback = nil; expectUnknown = true; expectedFallback = 1
        case "both-placeholder": s.primary = "XXXXX-XXXX-XXXXX-XXXX"; s.fallback = s.primary; expectUnknown = true; expectedFallback = 1
        case "portal-error": s.failPortal = true; expectedError = s.portalError
        default: fatalError("Unknown scenario")
        }
        do {
            let result = try await Probe().registerCurrentDevice(for: ALTTeam(), session: ALTAppleAPISession())
            precondition(expectedError == nil && !expectUnknown)
            precondition(result.identifier == "PRIVATE_DEVICE_ID")
        } catch let actual as QueryFailure {
            precondition(actual === expectedError)
        } catch OperationError.unknownUDID {
            precondition(expectUnknown)
        }
        precondition(s.off == 1 && s.on == 1 && s.primaryCalls == 1 && s.fallbackCalls == expectedFallback)
        precondition(Array(s.events.prefix(3)) == ["off", "primary", "on"])
        if expectUnknown || expectedError === s.primaryError || expectedError === s.fallbackError {
            precondition(s.fetchCalls == 0 && s.registerCalls == 0)
        } else {
            precondition(s.fetchCalls == 1 && s.registerCalls == (scenario == "primary-new-device" ? 1 : 0))
        }
        precondition(!s.logs.contains(where: { $0.contains("PRIVATE_") }))
    }
}
'''


class SignInUDIDFailureConsumerTests(unittest.TestCase):
    def setUp(self): self.body = consumer(SOURCE.read_text())

    def test_preserves_first_failure_and_valid_fallback(self):
        self.assertIn('deviceQueryError = error', self.body)
        self.assertIn('deviceQueryError = deviceQueryError ?? error', self.body)
        self.assertIn('if let deviceQueryError { throw deviceQueryError }', self.body)
        self.assertNotIn('try? await fetchUDID', self.body)
        self.assertLess(self.body.index('deviceUDID = try await fetchUDID(useStatic: true)'), self.body.index('if let deviceQueryError { throw deviceQueryError }'))

    def test_cellular_restore_boundary_unchanged(self):
        self.assertEqual(self.body.count('turnOffDataIfNeeded()'), 1)
        self.assertEqual(self.body.count('turnOnDataIfNeeded(addOnDelay: 2.0)'), 2)
        self.assertLess(self.body.rindex('turnOnDataIfNeeded'), self.body.index('fetchUDID(useStatic: true)'))

    def test_logs_do_not_include_identifiers_or_raw_errors(self):
        self.assertNotIn('Registered current device UDID:', SOURCE.read_text())
        for line in self.body.splitlines():
            if 'self.debugLog(' in line:
                self.assertNotIn('\\(', line)

    def test_extracted_native_consumer(self):
        compiler = shutil.which('swiftc')
        if not compiler: self.skipTest('Swift compiler unavailable; native consumer execution required')
        with tempfile.TemporaryDirectory() as name:
            source, binary = Path(name)/'probe.swift', Path(name)/'probe'
            source.write_text(HARNESS.replace('__CONSUMER__', self.body))
            built = subprocess.run([compiler, '-parse-as-library', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            for case in ('primary-success', 'primary-new-device', 'fallback-after-error', 'fallback-after-empty', 'fallback-after-placeholder', 'fallback-after-nil', 'both-errors', 'primary-error-fallback-empty', 'fallback-error', 'both-empty', 'both-placeholder', 'portal-error'):
                with self.subTest(case=case):
                    run = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__': unittest.main()
