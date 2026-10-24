// Inert framework/native/DB shells. No provider, device, auth, file or network IO.
typealias NSManagedObjectContext = FixtureManagedObjectContext
final class UIViewController {}
struct UIBackgroundTaskIdentifier: Equatable {
    let value: Int
    static let invalid = UIBackgroundTaskIdentifier(value: -1)
}
final class UIApplication {
    static let shared = UIApplication()
    var isIdleTimerDisabled = false
    func beginBackgroundTask(withName: String, expirationHandler: @escaping () -> Void) -> UIBackgroundTaskIdentifier { .init(value: 1) }
    func endBackgroundTask(_ identifier: UIBackgroundTaskIdentifier) {}
}
extension UserDefaults { var isIdleTimeoutDisableEnabled: Bool { false } }
func debugLog(_ text: String) {}
func logOperationSummary(operation: String, target: String, status: String, elapsed: Double, error: Error?) {}
enum LoggedError {
    enum Operation { case install, update, refresh, activate, deactivate, backup, restore, resign, remove }
}
extension InstalledApp {
    var resignedBundleIdentifier: String { bundleIdentifier }
    var customBundleIdentifier: String? { nil }
}
final class ALTApplication: NSManagedObject, AppProtocol {
    let name = "Fixture host"
    let bundleIdentifier = "com.kdt.livecontainer"
    let isAltStoreApp = true
}
extension Bundle {
    enum Info {
        static let activeBundleIdentifier = "com.kdt.livecontainer"
        static let appbundleIdentifier = "com.kdt.livecontainer"
    }
}
enum StoreApp {}
final class PreflightChecksHandler {
    var isResignActive = false
    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {
        FixtureVisits.mismatchPrompt += 1
        return false
    }
}
final class PipelineExecutionHandler { let preflightChecksHandler = PreflightChecksHandler() }
extension Array where Element == Int { static var preflightChecks: [Int] { [1] } }
class StandaloneOperationContext {
    let dbBackgroundContext: NSManagedObjectContext
    let operationStartTime = CFAbsoluteTimeGetCurrent()
    var error: Error?
    init(steps: [Int], dbBackgroundContext: NSManagedObjectContext) { self.dbBackgroundContext = dbBackgroundContext }
}
final class SharedPipelineContext {}
class BasePipelineOperation<Context: StandaloneOperationContext, Value> {
    let context: Context
    let progress = Progress.discreteProgress(totalUnitCount: 100)
    init(context: Context) throws { self.context = context }
    func executePreconditionCheck(parentProgress: Progress?) async throws {
        try Task.checkCancellation()
        if let error = context.error { throw error }
    }
    func setProgress(_ value: Int64) { progress.completedUnitCount = value }
    func execute(parentProgress: Progress?) async throws -> Value { throw OperationError.unknownResult }
    func execute() async throws -> Value { try await execute(parentProgress: nil) }
}
final class FixtureProgressRegistry {
    var values: [String: Progress] = [:]
    func progress(for operation: AppOperation) -> Progress? { values[operation.bundleIdentifier] }
    func set(_ value: Progress?, for operation: AppOperation) { values[operation.bundleIdentifier] = value }
}
final class FixtureRunnerContext { let isActivelyManagingAnyApp = false }
enum FixtureVisits {
    static var readiness = 0
    static var teamLookup = 0
    static var mutation = 0
    static var beginBatch = 0
    static var endBatch = 0
    static var mismatchPrompt = 0
    static var readinessNetworkChecks: [Bool] = []
    static func reset() {
        readiness = 0; teamLookup = 0; mutation = 0
        beginBatch = 0; endBatch = 0; mismatchPrompt = 0
        readinessNetworkChecks = []
    }
}
final class CellularRefreshManager {
    static let shared = CellularRefreshManager()
    var isEnabled = false
}
public enum MinimuxerError: Error, LocalizedError {
    case noDevice(String), noConnection(String), notReachable(String), noVPN(String), invalidVPN(String)
    case invalidPairing(Int, String), notStarted(String), pairingNotLoaded(String)
    case connectionModeNotConfigured(String), createCoreDevice(String), createLockdown(String)
    case getLockdownValue(String), connect(String), noService(String), opaque(String)
    public var errorDescription: String? { "SECRET_CANARY_ACCOUNT_TOKEN_PAIRING_012345" }
}
enum minimuxer {
    static let core = FixtureCore()
}
final class FixtureCore {
    var result: Result<Bool, MinimuxerError> = .success(true)
    var releaseGate: FixtureTransportReleaseGate?
    func beginTransportBatch() async { FixtureVisits.beginBatch += 1 }
    func endTransportBatch() async {
        if let releaseGate { await releaseGate.holdRelease() }
        FixtureVisits.endBatch += 1
    }
    func isReady(withNetworkCheck: Bool) async -> Result<Bool, MinimuxerError> {
        FixtureVisits.readiness += 1
        FixtureVisits.readinessNetworkChecks.append(withNetworkCheck)
        return result
    }
}
public struct ALTTeam {
    let identifier: String
    let name: String
    let type: String
}
struct FixtureDBTeam {
    let identifier = "FIXTURE_TEAM"
    let name = "SECRET_CANARY_ACCOUNT_TOKEN_PAIRING_012345"
    let type = "fixture"
}
final class DatabaseManager {
    static let shared = DatabaseManager()
    let persistentContainer = FixturePersistentContainer()
    var selectedTeam: FixtureDBTeam? = FixtureDBTeam()
    func activeTeam(in context: NSManagedObjectContext) -> FixtureDBTeam? {
        FixtureVisits.teamLookup += 1
        return selectedTeam
    }
}
final class FixturePersistentContainer {
    var error: Error?
    func performBackgroundTask<T>(_ body: (NSManagedObjectContext) throws -> T) async throws -> T {
        if let error { throw error }
        return try body(NSManagedObjectContext())
    }
}

// Identity lease state is an inert external boundary in this early-failure suite.
// Both real runner methods are extracted; the identity suite owns real lease checks.
struct V3RemoteRequestAdmission: Sendable {
    func check() throws {}
    func close() {}
    func withScope<T>(_ operation: () async throws -> T) async rethrows -> T {
        try await operation()
    }
}
enum V3RemoteRequestLeases {
    static func capture() throws -> V3RemoteRequestAdmission { V3RemoteRequestAdmission() }
    static func withAuthorizedRoute<T>(operation: () async throws -> T) async rethrows -> T {
        try await operation()
    }
}

// One inert, explicitly released transport gate. No sleep, polling or timeout.
// It forces the real baseline callback to be consumed before cleanup finishes.
actor FixtureTransportReleaseGate {
    private var entered = false
    private var consumed = false
    private var released = false
    private var returned = false
    private var enteredWaiter: CheckedContinuation<Void, Never>?
    private var consumedWaiter: CheckedContinuation<Void, Never>?
    private var releaseWaiter: CheckedContinuation<Void, Never>?

    func holdRelease() async {
        precondition(!entered)
        entered = true
        enteredWaiter?.resume(); enteredWaiter = nil
        await withCheckedContinuation { continuation in
            if released { continuation.resume() } else { releaseWaiter = continuation }
        }
    }
    func waitUntilEntered() async {
        await withCheckedContinuation { continuation in
            if entered { continuation.resume() } else { enteredWaiter = continuation }
        }
    }
    func callbackConsumed() {
        precondition(!consumed)
        consumed = true
        consumedWaiter?.resume(); consumedWaiter = nil
    }
    func waitUntilCallbackConsumed() async {
        await withCheckedContinuation { continuation in
            if consumed { continuation.resume() } else { consumedWaiter = continuation }
        }
    }
    func release() {
        precondition(entered && !released)
        released = true
        releaseWaiter?.resume(); releaseWaiter = nil
    }
    func markReturned() {
        precondition(released, "fixture returned before explicit transport release")
        returned = true
    }
    func snapshot() -> (entered: Bool, consumed: Bool, released: Bool, returned: Bool) {
        (entered, consumed, released, returned)
    }
}
