// All inputs are invented canaries. No real account, certificate, credential,
// network, device, native signer, keychain, or persistent database is involved.
let fixtureSecret = "SECRET_CANARY_ACCOUNT_TOKEN_DEVICE_CERTIFICATE_012345"
public struct Team: Sendable {
    enum Kind { case free, paid }
    let identifier = fixtureSecret
    var type: Kind = .free
}
public typealias ALTTeam = Team
public struct Session: Sendable {
    let dsid = fixtureSecret
    let authToken = fixtureSecret
    let xcodeVersion = "fixture"
    let anisetteData = FixtureAnisette()
}
struct FixtureAnisette: Sendable {
    let machineID = fixtureSecret, oneTimePassword = fixtureSecret, localUserID = fixtureSecret
    let routingInfo = fixtureSecret, deviceID = fixtureSecret, clientInfo = fixtureSecret
    let clientTime = fixtureSecret, locale = fixtureSecret, timeZone = fixtureSecret
}
struct FixtureHeaders {
    struct Services { let userAgent = "fixture" }
    struct GrandSlam { let authApp = "fixture" }
    let developerServices = Services(), grandSlam = GrandSlam()
}
public struct X509Certificate: Sendable {
    let serialNumber: String
    init?(data: Data, identifier: String? = nil, machineName: String? = nil,
          machineIdentifier: String? = nil, requesterEmail: String? = nil,
          requesterFirstName: String? = nil, requesterLastName: String? = nil,
          displayName: String? = nil, certificateType: String? = nil,
          certificateTypeName: String? = nil, certificateTypeId: String? = nil,
          platform: String? = nil, platformName: String? = nil, isManaged: Bool? = nil,
          status: String? = nil, ownerName: String? = nil, ownerId: String? = nil,
          autoRotationEnabled: Bool? = nil, requestedDate: String? = nil,
          serialNumDecimal: String? = nil, sourceEndpoint: CertificateEndpoint? = nil) {
        serialNumber = "fixture-serial"
    }
}
public typealias ALTX509Certificate = X509Certificate
public typealias ALTAppleAPISession = Session
public typealias ALTAppleAPI = DeveloperPortal
struct FixtureResponse: @unchecked Sendable {
    let body: Data
    let status: Int?
    var transportError: Error? = nil
    var yieldBeforeReply = false
    static let empty = FixtureResponse(body: Data("{\"data\":[]}".utf8), status: 200)
}
enum FixtureDispatch {
    @TaskLocal static var response: FixtureResponse = .empty
}
@MainActor enum FixtureVisits {
    static var events: [String] = []
    static var injectedBeforeDispatch: Error? = nil
    static var failingAuthStep: String? = nil
    static var requestPaths: [String] = []
    static var requestMethods: [String] = []
    static var overrides: [String] = []
    static func reset() {
        events = []; injectedBeforeDispatch = nil; failingAuthStep = nil
        requestPaths = []; requestMethods = []; overrides = []
    }
}
struct FakeDispatcher {
    @MainActor func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        FixtureVisits.events.append("dispatch")
        FixtureVisits.requestPaths.append(request.url!.absoluteString)
        FixtureVisits.requestMethods.append(request.httpMethod ?? "")
        FixtureVisits.overrides.append(request.value(forHTTPHeaderField: "X-HTTP-Method-Override") ?? "")
        let configured = FixtureDispatch.response
        if configured.yieldBeforeReply { await Task.yield() }
        if let error = configured.transportError { throw error }
        let response: URLResponse
        if let status = configured.status {
            response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                       headerFields: ["X-Fixture-Secret": fixtureSecret])!
        } else {
            response = URLResponse(url: request.url!, mimeType: "application/json",
                                   expectedContentLength: configured.body.count, textEncodingName: "utf-8")
        }
        return (configured.body, response)
    }
}
@MainActor public final class DeveloperPortal {
    public static let shared = DeveloperPortal()
    let session = FakeDispatcher()
    let customHeaders = FixtureHeaders()
}
func debugLog(_ text: String) {} // Never prints request or response content.
@MainActor final class AuthManager {
    static let shared = AuthManager()
    var v3IdentityIsStable = true
    var v3IdentityStamp = "synthetic-stable-stamp"
    var fixtureTeam = Team()
    func getAuthenticatedSession() async throws -> Session {
        FixtureVisits.events.append("authenticate")
        if FixtureVisits.failingAuthStep == "authenticate" { throw FixtureVisits.injectedBeforeDispatch! }
        return Session()
    }
    func getAuthenticatedTeam() async throws -> Team {
        FixtureVisits.events.append("accountLookup")
        if FixtureVisits.failingAuthStep == "accountLookup" { throw FixtureVisits.injectedBeforeDispatch! }
        return fixtureTeam
    }
}
// Identity admission is inert in this portal evidence suite. The dedicated
// identity suite extracts and executes the actual lease/context implementations.
struct FixtureRemoteAdmission: Sendable {
    func withScope<T>(_ operation: () async throws -> T) async rethrows -> T { try await operation() }
}
@MainActor enum V3RemoteRequestLeases {
    static func withAuthorizedRoute<T>(operation: () async throws -> T) async rethrows -> T {
        try await operation()
    }
}
@MainActor final class DeveloperPortalProxy {
    static let shared = DeveloperPortalProxy()
    struct BoundSession { let session = Session(); let admission = FixtureRemoteAdmission() }
    private func getBoundSession() async throws -> BoundSession {
        FixtureVisits.events.append("boundSession")
        if let error = FixtureVisits.injectedBeforeDispatch { throw error }
        return BoundSession()
    }
    private func getBoundTeam(_ team: Team?, context: BoundSession) async throws -> Team {
        FixtureVisits.events.append("boundTeam"); return team ?? Team()
    }
    private func verifyCurrent(_ context: BoundSession) throws {
        FixtureVisits.events.append("verifyCurrent")
    }
}
struct FixtureActiveCertificate { let certificate: X509Certificate }
@MainActor final class CertificateManager {
    static let shared = CertificateManager()
    var activeCertificate: FixtureActiveCertificate? = nil
}
@MainActor enum V3HeadlessRuntime {
    struct Auth { var hasActiveSession = false }
    struct Runtime { var auth = Auth() }
    static var shared = Runtime()
}
enum V3SideStoreServiceError: Error { case authRequired }
enum MinimuxerError: Error { case invalidPairing(Int, String) }
struct MinimuxerServiceError: Error { let error: Error }

#if os(Linux)
let NSMultipleUnderlyingErrorsKey = "NSMultipleUnderlyingErrorsKey"
#endif
