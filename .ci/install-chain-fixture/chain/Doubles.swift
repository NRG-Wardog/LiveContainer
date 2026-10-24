// Only Foundation local scratch IO is real. Every Apple/device/DB/archive boundary below is inert.
import Foundation
import CoreFoundation
#if canImport(Darwin)
import Darwin
#endif
func debugLog(_ s: String) {}
func verboseLog(_ s: String) {}
func logOperationSummary(operation: String, target: String, status: String, elapsed: Double, error: Error?) {}
enum ProbeFailure: Error { case invalid(String), excludedStep, injected(PipelineStep) }
enum OperationError: Error { case invalidParameters(String) }
enum LoggedError { enum Operation { case install, update, refresh, activate, deactivate, backup, restore, resign, remove } }
class NSManagedObjectContext { func performAndWait<T>(_ block: () throws -> T) rethrows -> T { try block() } }
class NSManagedObject { let managedObjectContext: NSManagedObjectContext? = NSManagedObjectContext() }
public final class StoreApp: AppProtocol {
    static let altstoreAppID = "com.fixture.host"
    public let name = "Fixture Catalog"; public let bundleIdentifier = "com.fixture.catalog"
    public var url: URL? { nil }; public var storeApp: StoreApp? { self }
    var latestSupportedVersion: AppVersion? { nil }
}
class AppVersion {}
struct ReleaseTrack {}
enum CertificateStatus { case valid }
struct ALTCertificate { let serialNumber = "fixture" }
struct ALTProvisioningProfile {}
enum ALTEntitlement: String, Hashable { case fixture }
@propertyWrapper struct AsyncManaged<T> { var wrappedValue: T }
final class SharedPipelineContext {}
protocol PipelineExecutionHandler: AnyObject {}
final class ProbeHandler: PipelineExecutionHandler {}
enum PermissionReviewMode { case all, added, none }
protocol OperationLogging {}
final class InstalledApp: NSManagedObject, AppProtocol {
    let name: String; let bundleIdentifier: String
    init(_ id: String) { name = "Synthetic"; bundleIdentifier = id }
    var url: URL? { fileURL }; var storeApp: StoreApp? { nil }
    var fileURL: URL { Probe.root.appendingPathComponent("installed.app") }
    var resignedBundleIdentifier: String { bundleIdentifier+".fixture" }
    var customBundleIdentifier: String? { nil }; var appBundleFingerprint: String? { nil }
    var useMainProfile = false; var appExtensions: [InstalledApp] { [] }
    var hasAlternateIcon = false; var alternateIconURL: URL? { nil }
}
final class ALTApplication: AppProtocol, Hashable {
    let fileURL: URL; let name = "Synthetic"; let bundleIdentifier: String
    init(url: URL, id: String) { fileURL = url; bundleIdentifier = id }
    convenience init?(fileURL: URL) { self.init(url: fileURL, id: "com.fixture.synthetic") }
    var url: URL? { fileURL }; var storeApp: StoreApp? { nil }
    var appExtensions: Set<ALTApplication> { [] }
    static func == (a: ALTApplication, b: ALTApplication) -> Bool { a === b }
    func hash(into h: inout Hasher) { h.combine(ObjectIdentifier(self)) }
}
struct PipelineProgress { func progress(for operation: AppOperation) -> Progress? { nil } }
final class RefreshGroup {
    let dbContext = NSManagedObjectContext(); let sharedContext = SharedPipelineContext()
    var isCellularRefreshGroup = false; var beginInstallationHandler: ((InstalledApp) -> Void)?
}
final class CertificateManager {
    static let shared = CertificateManager()
    struct Active { let certificate: ALTCertificate }
    var activeCertificate: Active? = Active(certificate: ALTCertificate())
}
extension FileManager {
    func uniqueTemporaryURL() -> URL { Probe.root.appendingPathComponent(UUID().uuidString, isDirectory: true) }
}
extension UserDefaults {
    var isLegacyDeactivationSupported: Bool { false }
    var permissionCheckingDisabled: Bool { true }
    var legacySideloadedApps: [String]? { get { nil } set {} }
}
extension Bundle { enum Info {
    static let activeBundleIdentifier = "com.fixture.host"
    static var activeBundleURL: URL { Probe.root }
} }
enum V3RemoteRequestLeases {
    struct Lease { func check() throws { throw ProbeFailure.excludedStep } }
    static var admitted: Lease? { nil }
}
enum V3HostRefreshBundlePreparation {
    struct ExtensionIdentity { let original: String; let resigned: String }
    struct Prepared { let appBundle: ALTApplication; func removeOwnedCopy() {} }
    static func prepare(originalBundleID: String, resignedBundleID: String, expectedOriginalBundleID: String,
        activeBundleID: String, activeBundleURL: URL, extensions: [ExtensionIdentity], checkAdmission: () throws -> Void) throws -> Prepared {
        throw ProbeFailure.excludedStep
    }
}
func lcStructuredSigningFailure(_ error: Error, stage: String, sourceStep: String?, facts: [String:String]) -> Error { error }
func lcRefreshFailureFacts(_ error: Error) -> [String:String] { [:] }
enum CombinedIPAReason { case invalidToken, fileAccess }
struct CombinedIPAFileError: Error { let reason: CombinedIPAReason; init(_ reason: CombinedIPAReason) { self.reason = reason } }
enum V3SideStoreServiceError: Error { case invalidRequest, unsupported }
enum InstallTarget { case app(AppProtocol) }
func v3Resolve(_ token: String) throws -> StoreApp { throw ProbeFailure.excludedStep }
enum PackageType { case ipa }
enum AppManager {
    static func readAppMetadata(from url: URL, packageType: PackageType) throws -> (bundleIdentifier: String, name: String) {
        try Probe.require(url == Probe.input, "metadata URL")
        return ("com.fixture.synthetic", "Synthetic")
    }
}
enum V3IPAStaging {
    static func sideStoreContainerRoot() -> URL? { Probe.root }
    static func inspect<T>(token: String, containerRoot: URL, body: (URL) throws -> T) throws -> T {
        try Probe.require(token == Probe.token && containerRoot == Probe.root, "staging identity")
        return try body(Probe.input)
    }
    static func resolve(token: String, containerRoot: URL) throws -> URL {
        try Probe.require(token == Probe.token && containerRoot == Probe.root, "resolve identity")
        return Probe.input
    }
}
enum Probe {
    static let token = "11111111-2222-3333-4444-555555555555"
    static let root = FileManager.default.temporaryDirectory.appendingPathComponent("install-chain-"+UUID().uuidString)
    static var input: URL { root.appendingPathComponent(token+".ipa") }
    static var trace: [PipelineStep] = []
    static var failAt: PipelineStep?
    static var lastContext: InstallAppOperationContext?
    static var nativeInstallObserved = false
    static var weights: [Int64] = []
    static var cleaned = false
    static func reset() { trace=[];failAt=nil;lastContext=nil;nativeInstallObserved=false;weights=[];cleaned=false }
    static func require(_ condition: @autoclosure () -> Bool, _ reason: String) throws { if !condition() { throw ProbeFailure.invalid(reason) } }
    static func enter(_ step: PipelineStep, _ context: InstallAppOperationContext) throws {
        trace.append(step);lastContext=context
        if failAt == step { throw ProbeFailure.injected(step) }
        if let error=context.error { throw error }
        let weight=try context.consumeWeight(for:step);try require(weight > 0,"positive weight");weights.append(weight)
        try require(context.bundleIdentifier == "com.fixture.synthetic", "identity")
        try require(context.customBundleIdentifier == nil && context.targetBundleIdentifier == context.bundleIdentifier, "default identity")
        try require(context.appendTeamID && !context.useMainProfile && !context.isStoreUpdate, "default choices")
        try require(context.appVersion == nil, "no catalog version")
        if step != .downloadApp { try require(context.targetAppBundle != nil && context.ipaURL != nil, "required downloaded input") }
    }
}
