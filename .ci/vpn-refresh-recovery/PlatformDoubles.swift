// External effects only. Production preflight, activation, early-failure capture,
// wire sanitizer, decoder and scheduler bodies are extracted by the generator.
// No UIKit application, real preferences, network, device or provider is used.
public final class UserDefaults {
    static let standard = UserDefaults()
    private var values: [String: Any] = [:]
    static var fixtureScheme: String? = "fixture-livecontainer"
    static func lcAppUrlScheme() -> String? { fixtureScheme }
    func object(forKey key: String) -> Any? { values[key] }
    func string(forKey key: String) -> String? { values[key] as? String }
    func dictionary(forKey key: String) -> [String: Any]? { values[key] as? [String: Any] }
    func bool(forKey key: String) -> Bool { values[key] as? Bool ?? false }
    func set(_ value: Any?, forKey key: String) { values[key] = value }
    func removeObject(forKey key: String) { values.removeValue(forKey: key) }
    func synchronize() -> Bool { true }
}

enum NWInterface { enum InterfaceType { case wifi } }
struct NWPath {
    enum Status { case satisfied, unsatisfied }
    let status: Status
    func usesInterfaceType(_ type: NWInterface.InterfaceType) -> Bool { status == .satisfied }
}
final class NWPathMonitor {
    static var fixtureWiFiAvailable = true
    var pathUpdateHandler: ((NWPath) -> Void)?
    init(requiredInterfaceType: NWInterface.InterfaceType) {}
    func start(queue: DispatchQueue) {
        pathUpdateHandler?(NWPath(status: Self.fixtureWiFiAvailable ? .satisfied : .unsatisfied))
    }
    func cancel() {}
}

// Observe completion of the actual production background-notification Task.
// This never writes activation state and does not decide whether to recover.
@MainActor
enum FixtureLifecycle {
    private static var leftHostObserved = false
    private static var continuation: CheckedContinuation<Void, Never>?
    static func reset() { leftHostObserved = false; continuation = nil }
    static func observedLeftHost(_ value: Bool) {
        guard value else { return }
        leftHostObserved = true
        let pending = continuation; continuation = nil
        pending?.resume()
    }
    static func waitUntilLeftHostObserved() async {
        guard !leftHostObserved else { return }
        await withCheckedContinuation { continuation = $0 }
    }
}

@MainActor
final class UIApplication {
    enum State { case active, background }
    static let shared = UIApplication()
    static let didEnterBackgroundNotification = Notification.Name("fixture.didEnterBackground")
    static let didBecomeActiveNotification = Notification.Name("fixture.didBecomeActive")
    var applicationState = State.active
    var openedURLs: [URL] = []
    var openSucceeds = true
    var onOpen: (() -> Void)?
    func reset() {
        applicationState = .active; openedURLs = []; openSucceeds = true; onOpen = nil
        FixtureLifecycle.reset()
    }
    func open(_ url: URL, options: [String: Any], completionHandler: @escaping (Bool) -> Void) {
        openedURLs.append(url)
        onOpen?()
        completionHandler(openSucceeds)
        guard openSucceeds else { return }
        Task { @MainActor in
            applicationState = .background
            NotificationCenter.default.post(name: Self.didEnterBackgroundNotification, object: nil)
            // Await the actual observer assignment, not a scheduling guess.
            await FixtureLifecycle.waitUntilLeftHostObserved()
            applicationState = .active
            NotificationCenter.default.post(name: Self.didBecomeActiveNotification, object: nil)
        }
    }
}

// The actual early-boundary helper only examines these case identities here.
// Portal/signing paths are not exercised by a transport-readiness fixture.
enum AppOperation { case refresh, install }
enum DeveloperPortalError: Error { case fixtureNeverProduced }
enum ServerError: Error {
    case underlyingError(Int, String), badServerResponse, invalidResponseFormat, missingKey
}
func lcSafeSigningCause(_ error: Error, portalResponse: Bool) -> String {
    preconditionFailure("The transport fixture must never enter a signing producer")
}

@MainActor
enum LiveContainerAutoRefreshScheduler {
    static var defaults = UserDefaults()
    static var activeRun: UUID?
    static var fixtureAttempt: ((UUID) async throws -> Void)?
    // ACTUAL_SCHEDULER_KEYS
    // ACTUAL_SCHEDULER_METHODS
    private static func performRefresh(runID: UUID) async throws {
        guard let fixtureAttempt else { preconditionFailure("Missing injected pipeline") }
        try await fixtureAttempt(runID)
    }
    static func reset(runID: UUID, requestID: String, source: String = "manual") {
        defaults = UserDefaults(); activeRun = runID; fixtureAttempt = nil
        defaults.set(runID.uuidString, forKey: activeRunKey)
        defaults.set(runID.uuidString, forKey: expectedRunKey)
        defaults.set(requestID, forKey: activeManualRequestKey)
        defaults.set([runID.uuidString: ["run_id": runID.uuidString,
            "request_id": requestID, "source": source, "state": "running"]], forKey: runLedgerKey)
    }
    static func exercise(runID: UUID, source: String, hasBackgroundTask: Bool,
                         activationAlreadyAttempted: Bool, requestID: String) async throws {
        try await performRefreshWithVPNRecovery(runID: runID, source: source,
            hasBackgroundTask: hasBackgroundTask, activationAlreadyAttempted: activationAlreadyAttempted,
            requestID: requestID, ownsNetworkRun: {
                ownsNetworkPreflight(runID: runID, requestID: requestID, source: source, gateFinished: false)
            })
    }
    static func ownsFixtureNetworkPreflight(runID: UUID, requestID: String, source: String) -> Bool {
        ownsNetworkPreflight(runID: runID, requestID: requestID, source: source, gateFinished: false)
    }
}
