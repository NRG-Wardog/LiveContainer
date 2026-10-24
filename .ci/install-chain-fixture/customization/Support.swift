import Foundation
import CoreFoundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

// Test-only suite; never read or modify UserDefaults.standard or a user app suite.
let testSuiteName = "org.sidestore.test-only.customization.\(UUID().uuidString)"
let testDefaults = UserDefaults(suiteName: testSuiteName)!
let featureKeys = ["customizeInfoPlist", "customizeEntitlements", "customizeAppId", "customizeAppIcon", "customizeProvisioningProfile"]

enum OperationError: Error, Equatable {
    case invalidParameters(String)
    case cancelled
}
enum FixtureFailure: Error, CustomStringConvertible {
    case assertion(String)
    var description: String {
        switch self { case .assertion(let reason): return reason }
    }
}
func require(_ condition: @autoclosure () -> Bool, _ reason: String) throws {
    if !condition() { throw FixtureFailure.assertion(reason) }
}
func debugLog(_ message: String) { /* Deliberately keep stdout JSON-only. */ }

// These boundaries perform no signing, device, network, file parsing, or UI work.
enum ALTTeamType: Sendable { case free, paid }
struct ALTTeam: Sendable { let identifier: String; let type: ALTTeamType }
struct ALTProvisioningProfile: Sendable { let uuid: String }
struct ALTEntitlement: Hashable, Sendable {
    let rawValue: String
    init(_ rawValue: String) { self.rawValue = rawValue }
}
struct InfoPlistTarget: Sendable {
    let id: String
    let name: String
    let isExtension: Bool
    let initialPlist: [String: any Sendable]
}
struct EntitlementsTarget: Sendable {
    let id: String
    let name: String
    let isExtension: Bool
    let initialEntitlements: [String: any Sendable]
}
struct InfoPlistParser {
    let rawDictionary: [String: any Sendable]
    var bundleIdentifier: String? { rawDictionary["CFBundleIdentifier"] as? String }
    init(dictionary: [String: any Sendable]) { rawDictionary = dictionary }
    init(plistURL: URL) throws {
        throw FixtureFailure.assertion("Inert fixture must not parse a cached plist file")
    }
}
final class FixtureApplication: @unchecked Sendable {
    var name = "Ordinary Imported IPA"
    var bundleIdentifier = "example.imported"
    var isExtension = false
    var infoPlist: [String: any Sendable] = ["CFBundleIdentifier": "example.imported"]
    var entitlements: [String: any Sendable] = [:]
    var allAppBundles: [FixtureApplication] = []
}
struct FixtureFetchRequest {}
final class InstalledApp: @unchecked Sendable {
    var name = "Fixture Installed App"
    var bundleIdentifier = "example.imported"
    var resignedBundleIdentifier = "example.imported.FIXTURETEAM"
    var customInfoPlistURL: URL? = nil
    var customEntitlements: [String: any Sendable]? = nil
    var appExtensions: [InstalledApp] = []
    static func fetchRequest() -> FixtureFetchRequest { FixtureFetchRequest() }
}
final class FixtureDB: @unchecked Sendable {
    var performCalls = 0
    var fetchCalls = 0
    var installedApps: [InstalledApp] = []
    func performAndWait<T>(_ body: () -> T) -> T { performCalls += 1; return body() }
    func fetch(_ request: FixtureFetchRequest) throws -> [InstalledApp] {
        fetchCalls += 1
        return installedApps
    }
}
final class AuthManager: @unchecked Sendable {
    static let shared = AuthManager()
    var calls = 0
    func getAuthenticatedTeam() async throws -> ALTTeam {
        calls += 1
        return ALTTeam(identifier: "FIXTURETEAM", type: .free)
    }
}
final class ProfileManager: @unchecked Sendable {
    static let shared = ProfileManager()
    var calls = 0
    func assignProfile(uuid: String, for bundleID: String) { calls += 1 }
}
struct FixtureHandlerBag: Sendable { let userCustomizationHandler: any UserCustomizationHandler }
enum FixtureIconMode { case unchanged, set(URL) }
final class InstallAppOperationContext: @unchecked Sendable {
    let handler: FixtureHandlerBag
    let dbBackgroundContext = FixtureDB()
    var isStoreUpdate = false
    var targetAppBundle: FixtureApplication? = FixtureApplication()
    var appendTeamID = true
    var installedApp: InstalledApp? = nil
    var bundleIdentifier = "example.imported"
    var targetBundleIdentifier: String { customBundleIdentifier ?? bundleIdentifier }
    var customBundleIdentifier: String? = nil
    var customInfoPlistByBundleID: [String: [String: any Sendable]] = [:]
    var customEntitlementsByBundleID: [String: [String: any Sendable]] = [:]
    var additionalEntitlements: [ALTEntitlement: any Sendable] = [:]
    var alternateIconMode = FixtureIconMode.unchanged
    var overrideProvisioningProfile: ALTProvisioningProfile? = nil
    init(handler: any UserCustomizationHandler) { self.handler = FixtureHandlerBag(userCustomizationHandler: handler) }
}
class BasePipelineOperation<Context, Output>: @unchecked Sendable {
    let context: Context
    var preconditionCalls = 0
    var progressValues: [Int64] = []
    init(context: Context) { self.context = context }
    func execute(parentProgress: Progress?) async throws -> Output {
        throw FixtureFailure.assertion("Fixture called abstract base execute")
    }
    func executePreconditionCheck(parentProgress: Progress?) async throws { preconditionCalls += 1 }
    func setProgress(_ value: Int64) { progressValues.append(value) }
}

// Intentionally implements only the two required supported entry points. The six
// unsupported methods MUST dispatch through the extracted production extension.
final class DefaultHostHandler: UserCustomizationHandler, @unchecked Sendable {
    var bundleCalls = 0
    var groupCalls = 0
    var bundleResult: (customID: String, appendTeamID: Bool)? = ("example.imported", true)
    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {
        bundleCalls += 1
        return bundleResult
    }
    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {
        groupCalls += 1
        return .keepOriginal(originalGroup)
    }
}
