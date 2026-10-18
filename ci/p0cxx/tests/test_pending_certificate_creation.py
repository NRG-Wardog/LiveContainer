"""Maintained-source pending-create contracts and native fault/key-proof execution.

All RSA keys are disposable test material generated in a temporary directory.
No Apple/network/account requests or real Keychain operations occur.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SIDE = Path(os.environ.get('SIDE_STORE_TEST_SOURCE', ROOT/'SideStore'))
SIGN = Path(os.environ.get('SIDESIGN_TEST_SOURCE', ROOT/'SideSign'))


def section(text, begin, end):
    return text.split(begin, 1)[1].split(end, 1)[0]

CORE_HARNESS = r'''
func check(_ value: Bool) { precondition(value) }
enum Fault: Error { case injected }
final class Store {
    var bytes: Data?, failBefore = false, failAfter = false, failRead = false, failRemove = false
    func load() throws -> Data? { if failRead { throw Fault.injected }; return bytes }
    func save(_ data: Data) throws {
        if failBefore { throw Fault.injected }
        bytes = data
        if failAfter { throw Fault.injected }
    }
    func remove() throws { if failRemove { throw Fault.injected }; bytes = nil }
}
func mustThrow(_ body: () throws -> Void) {
    do { try body(); fatalError("expected rejection") } catch {}
}
func record() -> V3PendingCertificateCreation {
    V3PendingCertificateCreation(version: 1, requestID: UUID().uuidString,
        ownerDSID: "fixture-owner", teamID: "fixture-team", namespace: "fixture-service:fixture-group",
        machineIdentifier: UUID().uuidString, machineName: "fixture-machine", certificateType: "development",
        purpose: .provisioning, csr: Data([1,2,3]), privateKey: Data([4,5,6]), phase: .prepared, certificateDER: nil)
}
func write(_ new: V3PendingCertificateCreation, _ old: V3PendingCertificateCreation?, _ store: Store) throws {
    try V3PendingCertificateRecordIO.write(new, replacing: old, load: store.load, save: store.save)
}
@main struct Main {
    static func main() throws {
        let initial = record()
        // Failure before preparation leaves no dispatched request or lost key.
        let before = Store(); before.failBefore = true
        mustThrow { try write(initial, nil, before) }; precondition(before.bytes == nil)
        // Failure after persistence retains the exact key although caller must not dispatch.
        let after = Store(); after.failAfter = true
        mustThrow { try write(initial, nil, after) }; after.failAfter = false
        check(try V3PendingCertificateRecordIO.read(after.load) == initial)
        let store = Store(); try write(initial, nil, store)
        check(try V3PendingCertificateRecordIO.read(store.load) == initial)
        mustThrow { try write(record(), nil, store) } // concurrent/duplicate begin
        // Stale caller cannot change owner or secret material under the same ID.
        let alien = V3PendingCertificateCreation(version: 1, requestID: initial.requestID,
            ownerDSID: "other-owner", teamID: initial.teamID, namespace: initial.namespace,
            machineIdentifier: initial.machineIdentifier, machineName: initial.machineName,
            certificateType: initial.certificateType, purpose: initial.purpose, csr: initial.csr,
            privateKey: initial.privateKey, phase: .dispatchMayHaveOccurred, certificateDER: nil)
        mustThrow { try write(alien, initial, store) }
        var dispatched = initial; dispatched.phase = .dispatchMayHaveOccurred
        store.failBefore = true; mustThrow { try write(dispatched, initial, store) }; store.failBefore = false
        check(try V3PendingCertificateRecordIO.read(store.load) == initial)
        store.failAfter = true; mustThrow { try write(dispatched, initial, store) }; store.failAfter = false
        check(try V3PendingCertificateRecordIO.read(store.load) == dispatched)
        mustThrow { try V3PendingCertificateRecordIO.clearPrepared(dispatched, load: store.load, remove: store.remove) }
        // A process restart recovers the same retained key; no submit API exists here.
        let restarted = Store(); restarted.bytes = store.bytes
        check(try V3PendingCertificateRecordIO.read(restarted.load) == dispatched)
        var created = dispatched; created.phase = .created; created.certificateDER = Data([7,8,9])
        try write(created, dispatched, restarted)
        mustThrow { try write(created, dispatched, restarted) } // duplicate stale response
        mustThrow { try write(initial, created, restarted) } // no state regression
        mustThrow { try V3PendingCertificateRecordIO.clear(created, storedCopyIsVerified: { false }, load: restarted.load, remove: restarted.remove) }
        check(try V3PendingCertificateRecordIO.read(restarted.load) == created)
        restarted.failRemove = true
        mustThrow { try V3PendingCertificateRecordIO.clear(created, storedCopyIsVerified: { true }, load: restarted.load, remove: restarted.remove) }
        restarted.failRemove = false
        check(try V3PendingCertificateRecordIO.read(restarted.load) == created)
        try V3PendingCertificateRecordIO.clear(created, storedCopyIsVerified: { true }, load: restarted.load, remove: restarted.remove)
        precondition(restarted.bytes == nil)
        let prepared = Store(); try write(initial, nil, prepared)
        try V3PendingCertificateRecordIO.clearPrepared(initial, load: prepared.load, remove: prepared.remove)
        precondition(prepared.bytes == nil)
        let malformed = Store(); malformed.bytes = Data([0,1,2])
        mustThrow { _ = try V3PendingCertificateRecordIO.read(malformed.load) }
        malformed.bytes = Data(repeating: 1, count: 131073)
        mustThrow { _ = try V3PendingCertificateRecordIO.read(malformed.load) }
        let fields = try PropertyListSerialization.propertyList(from: store.bytes!, options: [], format: nil) as! [String: Any]
        var extended = fields; extended["unexpectedSecret"] = "x"
        malformed.bytes = try PropertyListSerialization.data(fromPropertyList: extended, format: .binary, options: 0)
        mustThrow { _ = try V3PendingCertificateRecordIO.read(malformed.load) }
        precondition(initial.description == "<pending certificate creation>")
        precondition(!initial.debugDescription.contains("fixture-owner"))
        let status = V3PendingCertificateRecoveryPolicy.state
        precondition(status(nil, nil, false, true, true, false) == "none")
        precondition(status("owner", nil, false, true, true, false) == "signInRequired")
        precondition(status("owner", "other", true, true, true, false) == "ownerMismatch")
        precondition(status("owner", "owner", true, true, true, false) == "ready")
        precondition(status("owner", "owner", true, false, true, false) == "storageUnverified")
        precondition(status(nil, nil, false, true, false, false) == "storageUnverified")
        precondition(status("owner", "owner", true, true, true, true) == "activationRequired")
        precondition(status("owner", "other", true, true, true, true) == "ownerMismatch")
        let requestID = UUID().uuidString, now = Date()
        let base: [String: Any] = ["session": requestID, "sessionDeadline": now.addingTimeInterval(60)]
        func accepts(_ additions: [String: Any]) -> Bool {
            WireProbe.accepts(base.merging(additions) { _, new in new }, operation: "authBegin", target: requestID, now: now)
        }
        precondition(accepts([:]))
        precondition(accepts(["provisioningLogin": true, "finishPendingCertificateActivation": false]))
        precondition(accepts(["provisioningLogin": true, "finishPendingCertificateActivation": true]))
        precondition(!accepts(["finishPendingCertificateActivation": true]))
        precondition(!accepts(["provisioningLogin": false, "finishPendingCertificateActivation": true]))
        precondition(!accepts(["provisioningLogin": true, "finishPendingCertificateActivation": "true"]))
        precondition(!accepts(["provisioningLogin": true, "finishPendingCertificateActivation": 1]))
        precondition(!accepts(["provisioningLogin": true, "unexpected": true]))
        print("PENDING_CERTIFICATE_CORE_FAULT_MATRIX_PASS")
    }
}
'''

PROOF_HARNESS = r'''
@main struct Main {
    static func main() throws {
        let der = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let matching = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]))
        let mismatch = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[3]))
        let raw = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[4]))
        precondition(V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyPEM: matching))
        precondition(V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyDER: raw))
        precondition(!V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyPEM: mismatch))
        precondition(!V3PendingCertificateKeyProof.matches(certificateDER: Data([1,2,3]), privateKeyPEM: matching))
        precondition(!V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyPEM: Data([1,2,3])))
        precondition(!V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyDER: Data([1,2,3])))
        print("PENDING_CERTIFICATE_NATIVE_KEY_PROOF_PASS")
    }
}
'''


class PendingCertificateCreationTests(unittest.TestCase):
    def setUp(self):
        self.keychain = (SIDE/'AltStore/Core/Components/Keychain.swift').read_text()
        self.proxy = (SIDE/'SideStore/Core/Auth/DeveloperPortalProxy.swift').read_text()
        self.signin = (SIDE/'SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift').read_text()
        self.delegate = (SIDE/'AltStore/AppDelegate.swift').read_text()
        self.certificates = (SIGN/'Sources/DeveloperPortal/Certificates.swift').read_text()

    def test_dispatch_requires_verified_retention_and_preserves_late_result(self):
        method = section(self.proxy, 'public func createCertificate(', '\n    @discardableResult')
        self.assertLess(method.index('beginPendingCertificateCreation'), method.index('advancePendingCertificateCreation'))
        self.assertLess(method.index('advancePendingCertificateCreation'), method.index('ALTAppleAPI.shared.addCertificate'))
        tail = method.split('ALTAppleAPI.shared.addCertificate',1)[1]
        self.assertLess(tail.index('certificateDER: der'), tail.index('verifyCurrent(context)'))
        self.assertEqual(method.count('ALTAppleAPI.shared.addCertificate'), 1)
        self.assertNotIn('while ', method)

    def test_reconciliation_is_read_only_and_cryptographically_bound(self):
        method = section(self.proxy, 'public func reconcilePendingCertificateCreation(', 'public func fetchDevices(')
        for forbidden in ('addCertificate(', 'createCertificate(', 'revokeCertificate('): self.assertNotIn(forbidden, method)
        for required in ('context.session.dsid == retained.ownerDSID', 'team.identifier == retained.teamID', 'matches.count == 1', 'V3PendingCertificateKeyProof.matches', 'retained.purpose == .importedCopy'): self.assertIn(required, method)
        self.assertIn('purpose: .provisioning', self.signin)
        self.assertIn('v3CompletePendingCertificateIfStored(certificate)', self.signin)

    def test_secure_journal_is_separate_device_local_and_strict(self):
        for required in ('service + ".pending-certificate"', 'kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly', 'kSecAttrSynchronizable: false', 'V3PendingCertificateRecordIO.write', 'withSharedTransaction', 'try load() == data', 'record.purpose == .provisioning'): self.assertIn(required, self.keychain)
        self.assertNotIn('pendingCertificateKey', section(self.keychain, 'static func clearAll(', 'private static func note('))
        direct = section(self.delegate, 'private struct V3DirectMutationRecoveryRecord', 'static func isEligible(')
        self.assertNotIn('privateKey', direct)

    def test_existing_api_wrapper_and_app_entrypoints(self):
        self.assertIn('func addCertificate(machineName: String, type: CertificateType, to team: Team, session: Session)', self.certificates)
        overload = self.certificates.split('func addCertificate(request certRequest:',1)[1].split('func revokeCertificate(',1)[0]
        self.assertIn('"machineId": machineIdentifier', overload)
        self.assertNotIn('CertificateRequest(machineName:', overload)
        self.assertNotIn('UUID()', overload)
        self.assertIn('Keychain.shared.pendingCertificateCreation() != nil', self.delegate)
        self.assertIn('reconcilePendingCertificateCreation()', self.delegate)
        self.assertIn('"pendingCertificateRecoveryProtocol": 1', self.delegate)
        self.assertIn('"pendingCertificateRecoveryState":', self.delegate)
        local_block = section(self.delegate, 'var provisioningRecoveryRequiresReconciliation: Bool {', 'var pendingCertificateRecoveryState: String {')
        self.assertNotIn('pendingCertificateCreation', local_block)
        self.assertIn('v3CompletePendingCertificateIfStored(certificate)', self.delegate)

    def compile_run(self, text, marker, args=()):
        compiler = shutil.which('swiftc')
        if not compiler: self.skipTest('Swift compiler unavailable; native pending-create gate required')
        with tempfile.TemporaryDirectory() as name:
            source, binary = Path(name)/'probe.swift', Path(name)/'probe'
            source.write_text(text)
            build = subprocess.run([compiler, '-parse-as-library', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary), *map(str,args)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(marker, run.stdout)

    def test_native_exact_record_core_fault_matrix(self):
        core = section(self.keychain, '// V3_PENDING_CERTIFICATE_CORE_BEGIN', '// V3_PENDING_CERTIFICATE_CORE_END')
        policy = section(self.delegate, '// V3_PENDING_CERTIFICATE_RECOVERY_POLICY_BEGIN', '// V3_PENDING_CERTIFICATE_RECOVERY_POLICY_END')
        boolean = '    static func strictBool(' + section(self.delegate, '    static func strictBool(', '    static func strictInt(')
        token = '    private static func canonicalSecretToken(' + section(self.delegate, '    private static func canonicalSecretToken(', '    private static func canonicalLowercaseFileToken(')
        begin = self.delegate.index('        case "authBegin", "authRetryProvisioning":')
        begin = self.delegate.index('\n', begin) + 1
        end = self.delegate.index('        case "cancel":', begin)
        validator = self.delegate[begin:end]
        wire = 'enum WireProbe {\nstatic let authSessionLifetime: TimeInterval = 600\n'+boolean+token+'static func accepts(_ payload: [String: Any], operation: String, target: String, now: Date) -> Bool {\n'+validator+'}\n}\n'
        self.compile_run('import Foundation\nimport CoreFoundation\n'+core+policy+wire+CORE_HARNESS, 'PENDING_CERTIFICATE_CORE_FAULT_MATRIX_PASS')

    def test_native_exact_proxy_create_and_reconciliation(self):
        compiler = shutil.which('swiftc')
        if not compiler: self.skipTest('Swift compiler unavailable; exact proxy execution required')
        core = section(self.keychain, '// V3_PENDING_CERTIFICATE_CORE_BEGIN', '// V3_PENDING_CERTIFICATE_CORE_END')
        begin = self.proxy.index('    @discardableResult\n    public func createCertificate(')
        end = self.proxy.index('    public func fetchDevices(', begin)
        methods = self.proxy[begin:end].replace('public func', 'func')
        harness = (Path(__file__).with_name('proxy_harness.swift')).read_text().replace('__PROXY_METHODS__', methods)
        with tempfile.TemporaryDirectory() as name:
            source, binary = Path(name)/'proxy.swift', Path(name)/'proxy'
            admission = section(self.proxy, '// V3_CERTIFICATE_MUTATION_ADMISSION_BEGIN', '// V3_CERTIFICATE_MUTATION_ADMISSION_END')
            source.write_text('import Foundation\n'+core+admission+harness)
            build = subprocess.run([compiler, '-parse-as-library', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for case in ('happy','provisioning','prepare-before','prepare-after','dispatch-before','dispatch-after','retain-before','network','owner-change','invalid-response','empty','ambiguous','wrong-key','read-failure','local-failure','marker-owner-change','create-reentrant','revoke-reentrant','marker-cancel','create-cancel','revoke-read-owner','revoke-read-cancel'):
                with self.subTest(case=case):
                    run = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertIn('PENDING_CERTIFICATE_PROXY_SCENARIO_PASS', run.stdout)

    def test_native_exact_pending_activation_consumer(self):
        compiler = shutil.which('swiftc')
        if not compiler: self.skipTest('Swift compiler unavailable; pending activation consumer execution required')
        start = self.signin.index('                if !isCertificateResolved {')
        end = self.signin.index('                guard isCertificateResolved else', start)
        block = self.signin[start:end]
        start = self.signin.index('    private func fetchCertificate(for team:')
        start = self.signin.index('\n', start) + 1
        end = self.signin.index('        let portalCertificates = try await', start)
        prefix = self.signin[start:end]
        fixture = Path(__file__).with_name('activation_harness.swift').read_text()
        fixture = fixture.replace('__FETCH_PREFIX__', prefix).replace('__RESOLVE_BLOCK__', block)
        with tempfile.TemporaryDirectory() as name:
            source, binary = Path(name)/'activation.swift', Path(name)/'activation'
            source.write_text('import Foundation\n'+fixture)
            build = subprocess.run([compiler, '-parse-as-library', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for case in ('custom-pending', 'skip-pending', 'ordinary-pending', 'custom-no-pending', 'ordinary-reauth-custom', 'owner-changed', 'missing-pending'):
                with self.subTest(case=case):
                    run = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=15)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertIn('PENDING_CERTIFICATE_ACTIVATION_CONSUMER_PASS', run.stdout)

    def test_native_exact_security_query_scope(self):
        client = section(self.keychain, '// V3_PENDING_CERTIFICATE_SECURITY_CLIENT_BEGIN', '// V3_PENDING_CERTIFICATE_SECURITY_CLIENT_END')
        harness = Path(__file__).with_name('security_query_harness.swift').read_text()
        self.compile_run('import Foundation\nimport Security\n'+client+harness, 'PENDING_CERTIFICATE_EXACT_SECURITY_SCOPE_PASS')

    def test_native_security_matching_mismatching_and_invalid_keys(self):
        if not shutil.which('swiftc'): self.skipTest('Swift compiler unavailable; native Security proof required')
        if not shutil.which('openssl'): self.skipTest('OpenSSL unavailable for disposable test certificates')
        proof = section(self.keychain, '// V3_PENDING_CERTIFICATE_NATIVE_PROOF_BEGIN', '// V3_PENDING_CERTIFICATE_NATIVE_PROOF_END')
        def openssl(*args):
            result = subprocess.run(['openssl', *map(str,args)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, 'Disposable fixture generation failed')
        with tempfile.TemporaryDirectory() as name:
            d=Path(name)
            for label in ('matching','mismatch'):
                key=d/(label+'.pem'); openssl('genrsa','-out',key,'2048')
                if not key.read_text().startswith('-----BEGIN RSA PRIVATE KEY-----'):
                    temp=d/'converted.pem'; openssl('rsa','-in',key,'-traditional','-out',temp); key.write_bytes(temp.read_bytes())
            openssl('req','-new','-x509','-key',d/'matching.pem','-out',d/'cert.pem','-days','1','-subj','/CN=Disposable-Pending-Certificate-Test')
            openssl('x509','-in',d/'cert.pem','-outform','DER','-out',d/'cert.der')
            # Decode known RSA/PKCS#1 PEM framing to DER for the second native API.
            import base64
            lines=(d/'matching.pem').read_text().splitlines()
            (d/'key.der').write_bytes(base64.b64decode(''.join(lines[1:-1]),validate=True))
            self.compile_run('import Foundation\nimport Security\n'+proof+PROOF_HARNESS, 'PENDING_CERTIFICATE_NATIVE_KEY_PROOF_PASS', (d/'cert.der',d/'matching.pem',d/'mismatch.pem',d/'key.der'))


if __name__ == '__main__': unittest.main()
