enum Purpose { case provisioning, importedCopy }
enum Phase { case created }
struct Pending { let purpose: Purpose; let phase = Phase.created }
struct ALTTeam { let identifier = "team" }
struct ALTAppleAPISession {}
struct ALTCertificate: Equatable { let id: String; let data: Data? = Data([1]) }
struct Active { let certificate: ALTCertificate }
struct Details { let subject: String; let issuer = "custom" }
func parseCertificate(derData: Data) -> Details { Details(subject: CertificateManager.shared.activeCertificate?.certificate.id == "ordinary" ? "team" : "custom") }
enum Step { case fetchCertificate, activateCertificate }
enum V3PendingCertificateCreationError: Error { case pending }
final class Keychain: @unchecked Sendable {
    static let shared = Keychain()
    var record: Pending? = Pending(purpose: .provisioning)
    func pendingCertificateCreation() throws -> Pending? { record }
}
final class DeveloperPortalProxy: @unchecked Sendable {
    static let shared = DeveloperPortalProxy()
    var reconciles = 0, ownerMatches = true
    let retained = ALTCertificate(id: "retained")
    func reconcilePendingCertificateCreation(team: ALTTeam) async throws -> ALTCertificate? {
        reconciles += 1
        guard ownerMatches else { throw V3PendingCertificateCreationError.pending }
        return retained
    }
}
final class CertificateManager: @unchecked Sendable {
    static let shared = CertificateManager()
    var activeCertificate: Active? = Active(certificate: ALTCertificate(id: "custom"))
    var activations = 0, completions = 0
    func setActiveCertificate(_ value: ALTCertificate) throws {
        activations += 1; activeCertificate = Active(certificate: value)
    }
    func v3CompletePendingCertificateIfStored(_ value: ALTCertificate) throws {
        precondition(activeCertificate?.certificate == value)
        completions += 1; Keychain.shared.record = nil
    }
}
final class Probe {
    var skipCertificateProvisioning = false
    var v3FinishPendingCertificateActivation = true
    func debugLog(_ value: String) {}
    func fetchCertificate(for team: ALTTeam, session: ALTAppleAPISession) async throws -> ALTCertificate {
__FETCH_PREFIX__
        fatalError("A pending activation must never enter new-certificate selection")
    }
    func resolve() async throws -> ALTCertificate? {
        let team = ALTTeam(), session = ALTAppleAPISession()
        var isCertificateResolved = false
        var resolvedCertificate: ALTCertificate?
        var diagnosticStep = Step.fetchCertificate
__RESOLVE_BLOCK__
        precondition(isCertificateResolved)
        return resolvedCertificate
    }
}
@main struct Main {
    static func main() async throws {
        let scenario = CommandLine.arguments[1], probe = Probe()
        if scenario == "skip-pending" { probe.skipCertificateProvisioning = true }
        if scenario == "custom-no-pending" { Keychain.shared.record = nil; probe.v3FinishPendingCertificateActivation = false }
        if scenario == "ordinary-pending" { CertificateManager.shared.activeCertificate = Active(certificate: ALTCertificate(id: "ordinary")) }
        if scenario == "ordinary-reauth-custom" { probe.v3FinishPendingCertificateActivation = false }
        if scenario == "owner-changed" { DeveloperPortalProxy.shared.ownerMatches = false }
        if scenario == "missing-pending" { Keychain.shared.record = nil }
        if ["ordinary-reauth-custom", "owner-changed", "missing-pending"].contains(scenario) {
            do { _ = try await probe.resolve(); fatalError("expected safe refusal") }
            catch V3PendingCertificateCreationError.pending {}
            precondition(CertificateManager.shared.activeCertificate?.certificate.id == "custom")
            precondition(CertificateManager.shared.activations == 0 && CertificateManager.shared.completions == 0)
            print("PENDING_CERTIFICATE_ACTIVATION_CONSUMER_PASS")
            return
        }
        let value = try await probe.resolve()
        if scenario == "custom-no-pending" {
            precondition(value?.id == "custom" && DeveloperPortalProxy.shared.reconciles == 0)
            precondition(CertificateManager.shared.activations == 0)
        } else {
            precondition(value?.id == "retained" && DeveloperPortalProxy.shared.reconciles == 1)
            precondition(CertificateManager.shared.activations == 1 && CertificateManager.shared.completions == 1)
            precondition(Keychain.shared.record == nil)
        }
        print("PENDING_CERTIFICATE_ACTIVATION_CONSUMER_PASS")
    }
}
