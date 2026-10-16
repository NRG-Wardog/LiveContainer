enum HarnessFailure: Error { case injected, identity }
struct ALTAppleAPISession { let dsid: String }
struct ALTAccount { let identifier: String }
struct ALTTeam { let identifier: String; let type = TeamType.free }
enum TeamType { case free, paid }
struct CertificateType { let rawValue = "development"; var isPaidOnly: Bool { false }; static let development = CertificateType() }
struct CertificateRequest { let machineName: String; let privateKey = Data("test-key".utf8); let csrData = Data("test-csr".utf8); init(machineName: String) throws { self.machineName = machineName } }
struct ALTX509Certificate { let data: Data?; var serialNumber: String { "test-serial" } }
struct ALTCertificate { let x509: ALTX509Certificate; let privateKey: Data; var data: Data? { x509.data } }
enum DeveloperPortalError: Error { case invalidParameters(cause: String) }
final class State: @unchecked Sendable {
    static let shared = State()
    var owner = "owner", submits = 0, reads = 0, saves = 0, revokes = 0
    var failure = "", saveFails = false, active = false, accountFails = false
    var matchCount = 1, wrongKey = false, dispatched = false
    var events: [String] = []
}
final class Keychain: @unchecked Sendable {
    static let shared = Keychain()
    var bytes: Data?
    func pendingCertificateCreation() throws -> V3PendingCertificateCreation? {
        if State.shared.failure == "revoke-read-owner" { State.shared.owner = "other" }
        if State.shared.failure == "revoke-read-cancel" { withUnsafeCurrentTask { $0?.cancel() } }
        return try V3PendingCertificateRecordIO.read { self.bytes }
    }
    func beginPendingCertificateCreation(ownerDSID: String, teamID: String, request: CertificateRequest, type: CertificateType, purpose: V3CertificateCreationPurpose) throws -> V3PendingCertificateCreation {
        let record = V3PendingCertificateCreation(version: 1, requestID: UUID().uuidString, ownerDSID: ownerDSID, teamID: teamID, namespace: "test", machineIdentifier: UUID().uuidString, machineName: request.machineName, certificateType: type.rawValue, purpose: purpose, csr: request.csrData, privateKey: request.privateKey, phase: .prepared, certificateDER: nil)
        try V3PendingCertificateRecordIO.write(record, replacing: nil, load: { self.bytes }, save: {
            if State.shared.failure == "prepare-before" { throw HarnessFailure.injected }
            self.bytes = $0
            if State.shared.failure == "prepare-after" { throw HarnessFailure.injected }
        })
        State.shared.events.append("prepared")
        return record
    }
    func advancePendingCertificateCreation(_ record: V3PendingCertificateCreation, certificateDER: Data? = nil) throws -> V3PendingCertificateCreation {
        var next = record
        next.phase = certificateDER == nil ? .dispatchMayHaveOccurred : .created; next.certificateDER = certificateDER
        if let der = certificateDER, !V3PendingCertificateKeyProof.matches(certificateDER: der, privateKeyPEM: record.privateKey) { throw V3PendingCertificateCreationError.invalidProof }
        try V3PendingCertificateRecordIO.write(next, replacing: record, load: { self.bytes }, save: {
            if State.shared.failure == "dispatch-before", certificateDER == nil { throw HarnessFailure.injected }
            if State.shared.failure == "retain-before", certificateDER != nil { throw HarnessFailure.injected }
            self.bytes = $0
            if State.shared.failure == "dispatch-after", certificateDER == nil { throw HarnessFailure.injected }
        })
        State.shared.events.append(certificateDER == nil ? "dispatch-marker" : "retained-result")
        if State.shared.failure == "marker-owner-change", certificateDER == nil { State.shared.owner = "other" }
        if State.shared.failure == "marker-cancel", certificateDER == nil { withUnsafeCurrentTask { $0?.cancel() } }
        return next
    }
    func clearPreparedCertificateCreation(_ record: V3PendingCertificateCreation) throws {
        try V3PendingCertificateRecordIO.clearPrepared(record, load: { self.bytes }, remove: { self.bytes = nil })
    }
}
enum V3PendingCertificateKeyProof {
    // Crypto is independently exercised against Security with generated RSA keys.
    // Here the IO double isolates the proxy's match/adoption decisions.
    static func matches(certificateDER: Data, privateKeyPEM: Data) -> Bool {
        certificateDER == Data("valid-cert".utf8) && privateKeyPEM == Data("test-key".utf8)
    }
}
final class CertificateManager: @unchecked Sendable {
    static let shared = CertificateManager()
    var saved: ALTCertificate?
    func saveCertificate(_ value: ALTCertificate) { State.shared.saves += 1; if !State.shared.saveFails { saved = value } }
    func v3CompletePendingCertificateIfStored(_ certificate: ALTCertificate) throws {
        guard let record = try Keychain.shared.pendingCertificateCreation() else { return }
        guard State.shared.owner == record.ownerDSID else { throw V3PendingCertificateCreationError.ownerChanged }
        try V3PendingCertificateRecordIO.clear(record, storedCopyIsVerified: {
            self.saved?.data == record.certificateDER && (record.purpose != .provisioning || State.shared.active)
        }, load: { Keychain.shared.bytes }, remove: { Keychain.shared.bytes = nil })
    }
}
final class ALTAppleAPI: @unchecked Sendable {
    static let shared = ALTAppleAPI()
    func addCertificate(request: CertificateRequest, machineIdentifier: String, type: CertificateType, to team: ALTTeam, session: ALTAppleAPISession) async throws -> ALTCertificate {
        let s = State.shared
        let record = try Keychain.shared.pendingCertificateCreation()!
        precondition(record.phase == .dispatchMayHaveOccurred && record.privateKey == request.privateKey && record.csr == request.csrData && record.machineIdentifier == machineIdentifier)
        s.submits += 1; s.events.append("POST"); s.dispatched = true
        if s.failure == "create-reentrant" || s.failure == "create-cancel" {
            if s.failure == "create-cancel" { withUnsafeCurrentTask { $0?.cancel() } }
            let other = DeveloperPortalProxy()
            await expectFailure { _ = try await other.createCertificate(machineName: "blocked") }
            await expectFailure { _ = try await other.revokeCertificate(ALTX509Certificate(data: nil)) }
            await expectFailure { _ = try await other.reconcilePendingCertificateCreation() }
            precondition(s.submits == 1 && s.revokes == 0 && s.reads == 0)
            if s.failure == "create-reentrant" { s.failure = "" }
        }
        if s.failure == "network" { throw HarnessFailure.injected }
        if s.failure == "owner-change" { s.owner = "other" }
        return ALTCertificate(x509: ALTX509Certificate(data: Data((s.failure == "invalid-response" ? "invalid" : "valid-cert").utf8)), privateKey: request.privateKey)
    }
    func fetchAccount(session: ALTAppleAPISession) async throws -> ALTAccount { ALTAccount(identifier: session.dsid) }
    func fetchTeams(for account: ALTAccount, session: ALTAppleAPISession) async throws -> [ALTTeam] { [ALTTeam(identifier: "team")] }
    func fetchCertificates(for team: ALTTeam, session: ALTAppleAPISession) async throws -> [ALTX509Certificate] {
        let s = State.shared; s.reads += 1
        if s.failure == "read" { throw HarnessFailure.injected }
        return (0..<s.matchCount).map { _ in ALTX509Certificate(data: Data((s.wrongKey ? "other-cert" : "valid-cert").utf8)) }
    }
    func revokeCertificate(_ certificate: ALTX509Certificate, for team: ALTTeam, session: ALTAppleAPISession) async throws -> Bool {
        State.shared.revokes += 1
        if State.shared.failure == "revoke-reentrant" {
            let other = DeveloperPortalProxy()
            await expectFailure { _ = try await other.createCertificate(machineName: "blocked") }
            await expectFailure { _ = try await other.revokeCertificate(certificate) }
            await expectFailure { _ = try await other.reconcilePendingCertificateCreation() }
            precondition(State.shared.submits == 0 && State.shared.revokes == 1 && Keychain.shared.bytes == nil)
        }
        return true
    }
}
final class DeveloperPortalProxy {
    struct BoundSession { let session: ALTAppleAPISession }
    func getBoundSession() async throws -> BoundSession {
        if State.shared.accountFails { throw HarnessFailure.identity }
        return BoundSession(session: ALTAppleAPISession(dsid: State.shared.owner))
    }
    func getBoundTeam(_ team: ALTTeam? = nil, context: BoundSession) async throws -> ALTTeam { try verifyCurrent(context); return team ?? ALTTeam(identifier: "team") }
    func verifyCurrent(_ context: BoundSession) throws { if context.session.dsid != State.shared.owner || Task.isCancelled { throw HarnessFailure.identity } }
    func awaitBound<T>(_ context: BoundSession, operation: () async throws -> T) async throws -> T { try verifyCurrent(context); let result = try await operation(); try verifyCurrent(context); return result }
__PROXY_METHODS__
}
func expectFailure(_ body: () async throws -> Void) async {
    do { try await body(); fatalError("expected failure") } catch {}
}
func check(_ value: Bool) { precondition(value) }
@main struct Main {
    static func main() async throws {
        let s = State.shared, proxy = DeveloperPortalProxy(), scenario = CommandLine.arguments[1]
        if scenario == "revoke-read-owner" || scenario == "revoke-read-cancel" {
            s.failure = scenario
            let attempt = Task {
                await expectFailure { _ = try await proxy.revokeCertificate(ALTX509Certificate(data: nil)) }
            }
            await attempt.value
            precondition(s.revokes == 0 && s.submits == 0 && Keychain.shared.bytes == nil)
            print("PENDING_CERTIFICATE_PROXY_SCENARIO_PASS")
            return
        }
        if scenario == "marker-cancel" || scenario == "create-cancel" {
            s.failure = scenario
            let attempt = Task {
                await expectFailure { _ = try await proxy.createCertificate(machineName: "cancelled") }
            }
            await attempt.value
            precondition(s.submits == (scenario == "marker-cancel" ? 0 : 1))
            check(try Keychain.shared.pendingCertificateCreation()?.phase == (scenario == "marker-cancel" ? .dispatchMayHaveOccurred : .created))
            // The original completion releases ownership; recovery runs in this uncancelled task.
            s.failure = ""
            _ = try await proxy.reconcilePendingCertificateCreation()
            precondition(Keychain.shared.bytes == nil && s.revokes == 0)
            print("PENDING_CERTIFICATE_PROXY_SCENARIO_PASS")
            return
        }
        if scenario == "revoke-reentrant" {
            s.failure = scenario
            _ = try await proxy.revokeCertificate(ALTX509Certificate(data: nil))
            // Ownership is released only on normal completion, permitting next call.
            s.failure = ""
            _ = try await proxy.createCertificate(machineName: "after-revoke")
            precondition(s.submits == 1 && s.revokes == 1)
            print("PENDING_CERTIFICATE_PROXY_SCENARIO_PASS")
            return
        }
        let originalPurpose: V3CertificateCreationPurpose = scenario == "provisioning" ? .provisioning : .importedCopy
        if ["prepare-before", "prepare-after", "dispatch-before", "dispatch-after", "retain-before", "network", "owner-change", "invalid-response", "marker-owner-change", "create-reentrant"].contains(scenario) { s.failure = scenario }
        if scenario == "empty" { s.failure = "network"; s.matchCount = 0 }
        if scenario == "ambiguous" { s.failure = "network"; s.matchCount = 2 }
        if scenario == "wrong-key" { s.failure = "network"; s.wrongKey = true }
        if scenario == "read-failure" { s.failure = "network" }
        if scenario == "local-failure" { s.saveFails = true }
        do {
            let created = try await proxy.createCertificate(machineName: "test", purpose: originalPurpose)
            precondition(s.failure.isEmpty)
            check(try Keychain.shared.pendingCertificateCreation()?.phase == .created)
            if scenario == "happy" {
                CertificateManager.shared.saveCertificate(created)
                try CertificateManager.shared.v3CompletePendingCertificateIfStored(created)
                check(try Keychain.shared.pendingCertificateCreation() == nil)
            }
        } catch {
            precondition(!s.failure.isEmpty)
        }
        let countAfterAttempt = s.submits
        if try Keychain.shared.pendingCertificateCreation() != nil {
            await expectFailure { _ = try await proxy.createCertificate(machineName: "second") }
            await expectFailure { _ = try await proxy.revokeCertificate(ALTX509Certificate(data: Data("valid-cert".utf8))) }
            precondition(s.submits == countAfterAttempt && s.revokes == 0)
        }
        if scenario == "prepare-before" { precondition(s.submits == 0 && Keychain.shared.bytes == nil) }
        else if scenario == "prepare-after" || scenario == "dispatch-before" {
            s.failure = ""
            let result = try await proxy.reconcilePendingCertificateCreation()
            precondition(result == nil && s.submits == 0 && Keychain.shared.bytes == nil)
        } else if scenario == "dispatch-after" || scenario == "marker-owner-change" {
            s.owner = "owner"
            s.failure = ""; s.matchCount = 0
            await expectFailure { _ = try await proxy.reconcilePendingCertificateCreation() }
            precondition(s.submits == 0 && Keychain.shared.bytes != nil)
        } else if scenario != "happy" {
            if scenario == "owner-change" {
                await expectFailure { _ = try await proxy.reconcilePendingCertificateCreation() }
                precondition(s.reads == 0)
                s.owner = "owner"
            }
            s.failure = scenario == "read-failure" ? "read" : ""
            if ["empty","ambiguous","wrong-key","read-failure","local-failure"].contains(scenario) {
                await expectFailure { _ = try await proxy.reconcilePendingCertificateCreation() }
                precondition(Keychain.shared.bytes != nil)
            } else {
                let recovered = try await proxy.reconcilePendingCertificateCreation()
                precondition(recovered?.privateKey == Data("test-key".utf8))
                if scenario == "provisioning" {
                    precondition(Keychain.shared.bytes != nil && !s.active)
                    s.active = true
                    try CertificateManager.shared.v3CompletePendingCertificateIfStored(recovered!)
                }
                precondition(Keychain.shared.bytes == nil)
            }
        }
        precondition(s.submits == countAfterAttempt && s.revokes == 0)
        print("PENDING_CERTIFICATE_PROXY_SCENARIO_PASS")
    }
}
