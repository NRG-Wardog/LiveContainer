"""Preserve an authoritative created certificate before fallible follow-up IO.

Extracts maintained SignInOperation methods/activation block. Swift execution
uses IO doubles; source checks run everywhere. Never contacts Apple or Keychain.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("SIDE_STORE_TEST_SOURCE", ROOT)) / "SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift"


def request(source):
    start = source.index("    private func requestCertificate(")
    end = source.index("    private func replaceCertificate(", start)
    return source[start:end].replace("private func", "func", 1)


def validation_read(source):
    start = source.index("        let portalCertificates: [ALTX509Certificate]")
    end = source.index("        let result = CodeSignValidator.validate(", start)
    return source[start:end]


def activation(source):
    start = source.index("                        if resolvedCertificate == nil {")
    end = source.index("\n                    }\n                    isCertificateResolved", start)
    return source[start:end]


HARNESS = r'''
import Foundation
struct ALTAccount { var firstName = "fixture" }
struct ALTTeam { var account: ALTAccount? = ALTAccount(); var name = "team" }
struct ALTAppleAPISession {}
enum V3CertificateCreationPurpose { case provisioning, importedCopy }
struct ALTSigner { let team = ALTTeam() }
struct ALTX509Certificate: Equatable { let serialNumber: String; let data: Data }
struct ALTCertificate: Equatable {
    let x509: ALTX509Certificate
    let privateKey: Data
    var serialNumber: String { x509.serialNumber }
}
@MainActor final class UIDevice { static let current = UIDevice(); let name = "device" }
enum HarnessError: Error { case createFailure, readFailure, localFailure }
final class DeveloperPortalProxy: @unchecked Sendable {
    static let shared = DeveloperPortalProxy()
    var creates = 0, fetches = 0
    var createFails = false, fetchFails = true
    let result = ALTCertificate(x509: ALTX509Certificate(serialNumber: "fixture", data: Data([1,2,3])), privateKey: Data([4,5,6]))
    func createCertificate(machineName: String, team: ALTTeam, purpose: V3CertificateCreationPurpose = .importedCopy) async throws -> ALTCertificate {
        creates += 1
        if createFails { throw HarnessError.createFailure }
        return result
    }
    func fetchCertificates(team: ALTTeam) async throws -> [ALTX509Certificate] {
        fetches += 1
        if fetchFails { throw HarnessError.readFailure }
        return [result.x509]
    }
}
final class CertificateManager: @unchecked Sendable {
    static let shared = CertificateManager()
    var attempts = 0
    var saved: ALTCertificate?
    func v3CompletePendingCertificateIfStored(_ cert: ALTCertificate) throws {}
    func setActiveCertificate(_ cert: ALTCertificate) throws {
        attempts += 1
        if attempts == 1 { throw HarnessError.localFailure }
        saved = cert
    }
}
enum Step { case fetchCertificate, activateCertificate }
final class Probe {
    var portalCertificates: [ALTX509Certificate]? = []
    func verboseLog(_ value: String) {}
    func debugLog(_ value: String) {}
__REQUEST__
    func validationCertificates() async throws -> [ALTX509Certificate] {
        let signer = ALTSigner()
__VALIDATION_READ__
        return portalCertificates
    }
    func activateWithLocalRetry() async throws -> ALTCertificate {
        var resolvedCertificate: ALTCertificate?
        var diagnosticStep = Step.fetchCertificate
        let team = ALTTeam(), session = ALTAppleAPISession()
        for _ in 0..<2 {
            do {
__ACTIVATION__
                precondition(diagnosticStep == .activateCertificate)
                return resolvedCertificate!
            } catch HarnessError.localFailure { continue }
        }
        fatalError("local retry did not settle")
    }
}
@main struct Main {
    static func main() async throws {
        let proxy = DeveloperPortalProxy.shared
        let probe = Probe()
        switch CommandLine.arguments[1] {
        case "created":
            let value = try await probe.requestCertificate(for: ALTTeam(), session: ALTAppleAPISession())
            precondition(value == proxy.result && proxy.creates == 1 && proxy.fetches == 0)
            precondition(probe.portalCertificates == nil)
        case "local-retry":
            let value = try await probe.activateWithLocalRetry()
            precondition(value == proxy.result && CertificateManager.shared.saved == proxy.result)
            precondition(proxy.creates == 1 && proxy.fetches == 0 && CertificateManager.shared.attempts == 2)
        case "validation-refresh":
            _ = try await probe.activateWithLocalRetry()
            proxy.fetchFails = false
            let first = try await probe.validationCertificates()
            let second = try await probe.validationCertificates()
            precondition(first == [proxy.result.x509] && second == first)
            precondition(proxy.fetches == 1 && proxy.creates == 1)
        case "validation-failure":
            _ = try await probe.activateWithLocalRetry()
            do {
                _ = try await probe.validationCertificates()
                fatalError("validation failure swallowed")
            } catch HarnessError.readFailure {}
            precondition(CertificateManager.shared.saved == proxy.result)
            precondition(proxy.creates == 1 && proxy.fetches == 1)
        case "creation-failure":
            proxy.createFails = true
            do {
                _ = try await probe.requestCertificate(for: ALTTeam(), session: ALTAppleAPISession())
                fatalError("creation failure swallowed")
            } catch HarnessError.createFailure {}
            precondition(proxy.creates == 1 && proxy.fetches == 0)
            precondition(probe.portalCertificates != nil)
        default: fatalError("unexpected scenario")
        }
    }
}
'''


class SignInCertificateCreationResultTests(unittest.TestCase):
    def setUp(self): self.source = SOURCE.read_text()

    def test_returns_full_result_without_second_fallible_request(self):
        body = request(self.source)
        self.assertEqual(body.count("DeveloperPortalProxy.shared.createCertificate("), 1)
        tail = body.split("let newPortalCertificate = try await DeveloperPortalProxy.shared.createCertificate", 1)[1]
        self.assertNotIn("fetchCertificates(", tail)
        self.assertEqual(tail.count("await"), 0)
        self.assertIn("return newPortalCertificate", tail)
        self.assertNotIn("ALTCertificate(x509:", tail)

    def test_invalidates_list_without_claiming_local_activation(self):
        body = request(self.source)
        self.assertLess(body.index("self.portalCertificates = nil"), body.index("return newPortalCertificate"))
        self.assertNotIn("setActiveCertificate", body)
        self.assertNotIn("try?", body)
        self.assertIn("throw error", body)

    def test_existing_activation_retry_retains_result(self):
        block = activation(self.source)
        self.assertIn("if resolvedCertificate == nil", block)
        self.assertIn("resolvedCertificate = try await self.fetchCertificate", block)
        self.assertLess(block.index("resolvedCertificate = try await"), block.index("try CertificateManager.shared.setActiveCertificate"))

    def test_native_request_and_local_retry(self):
        compiler = shutil.which("swiftc")
        if not compiler: self.skipTest("Swift compiler unavailable; native execution required")
        # fetchCertificate normally performs portal selection first. In this
        # narrow harness, its IO edge invokes the unchanged request method.
        adapter = "\nfunc fetchCertificate(for team: ALTTeam, session: ALTAppleAPISession) async throws -> ALTCertificate { try await requestCertificate(for: team, session: session) }\n"
        harness = HARNESS.replace("__REQUEST__", request(self.source) + adapter).replace("__ACTIVATION__", activation(self.source)).replace("__VALIDATION_READ__", validation_read(self.source))
        with tempfile.TemporaryDirectory() as name:
            source, binary = Path(name)/"probe.swift", Path(name)/"probe"
            source.write_text(harness)
            result = subprocess.run([compiler, "-parse-as-library", str(source), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for case in ("created", "local-retry", "creation-failure", "validation-refresh", "validation-failure"):
                with self.subTest(case=case):
                    run = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__": unittest.main()
