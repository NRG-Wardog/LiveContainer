extension LiveContainerAutoRefreshScheduler {
    static func clearTestState() {
        for key in defaults.dictionaryRepresentation().keys where key.hasPrefix("liveContainerAutoRefresh") { defaults.removeObject(forKey: key) }
        activeRun = nil
        LiveContainerRefreshBridge.bridgeError = nil
        LiveContainerNetworkPreflight.beforeThrow = nil
        LiveContainerRefreshBridge.calls = 0
        LiveContainerRefreshBridge.fails = false
        LiveContainerRefreshBridge.incomplete = false
        LiveContainerRefreshBridge.uncertain = false
        LiveContainerRefreshBridge.resultFailure = nil
        LiveContainerRefreshBridge.resultRetryable = nil
        LiveContainerRefreshBridge.staleFailure = false
        LiveContainerRefreshBridge.malformedFailure = false
        LiveContainerNetworkPreflight.error = nil
        LiveContainerNetworkPreflight.checks = 0
        LiveContainerNetworkPreflight.runIDs = []
        BGTaskScheduler.shared.requests = []
        UNUserNotificationCenter.shared.requests = []
        UNUserNotificationCenter.shared.onAdd = nil
        UNUserNotificationCenter.shared.settings = UNNotificationSettings()
        UIApplication.shared.openedURLs = []
    }
    static func exercise() async {
        HarnessContainerFileManager.install()
        V3SharedAppGroup.publishRuntimeGroup(V3SharedAppGroup.packagedGroup)
        // Actual execute/catch/normalization code, OS and bridge doubles only.
        for code in 1...4 {
            clearTestState()
            defaults.set(true, forKey: enabledKey)
            LiveContainerNetworkPreflight.error = NSError(domain: "LiveContainerRefresh.Network", code: code)
            let task = BGTask()
            await execute(source: "bgprocessing", task: task)
            precondition(task.completions == [false] && LiveContainerRefreshBridge.calls == 0)
            precondition(defaults.object(forKey: nextRetryKey) is Date, "known preflight must back off")
            precondition(defaults.dictionary(forKey: currentRunFailureKey)?["stage"] as? String == "network")
        }
        for cancelled in [true, false] {
            // Separate task so cancellation cannot leak into following cases.
            await Task { @MainActor in
                clearTestState()
                defaults.set(true, forKey: enabledKey)
                LiveContainerNetworkPreflight.error = NSError(domain: "LiveContainerRefresh.Network", code: 1)
                LiveContainerNetworkPreflight.beforeThrow = {
                    if cancelled { withUnsafeCurrentTask { $0?.cancel() } }
                    else { activeRun = UUID() }
                }
                await execute(source: "bgprocessing", task: BGTask())
                precondition(LiveContainerRefreshBridge.calls == 0)
                precondition(defaults.object(forKey: nextRetryKey) == nil, "cancelled/replaced owner must not authorize retry")
            }.value
        }
        clearTestState()
        LiveContainerRefreshBridge.bridgeError = NSError(domain: "LiveContainerRefresh.Network", code: 1)
        await execute(source: "manual", task: BGTask())
        precondition(LiveContainerRefreshBridge.calls == 1)
        precondition(defaults.object(forKey: nextRetryKey) == nil, "network-shaped post-preflight error must not replay")

        clearTestState()
        defaults.set(true, forKey: enabledKey)
        defaults.set(100, forKey: retryCountKey)
        LiveContainerNetworkPreflight.error = NSError(domain: "LiveContainerRefresh.Network", code: 1)
        await execute(source: "bgprocessing", task: BGTask())
        precondition(defaults.object(forKey: nextRetryKey) == nil && defaults.bool(forKey: retryExhaustedKey), "retry budget must remain bounded")

        let errors: [Error] = [NSError(domain: "LiveContainerRefresh.Network", code: 999),
                             NSError(domain: "unknown", code: 1), CancellationError(),
                             CombinedFailure(operation: "refresh", stage: .network, id: "stale", retryable: true)]
        for error in errors {
            clearTestState()
            defaults.set(true, forKey: enabledKey)
            LiveContainerNetworkPreflight.error = error
            let task = BGTask()
            await execute(source: "bgprocessing", task: task)
            precondition(task.completions == [false] && LiveContainerRefreshBridge.calls == 0)
            precondition(defaults.object(forKey: nextRetryKey) == nil, "unknown/cancelled/stale must not retry")
        }
        clearTestState()
        LiveContainerRefreshBridge.fails = true
        await execute(source: "manual", task: BGTask())
        precondition(LiveContainerRefreshBridge.calls == 1)
        precondition(defaults.object(forKey: nextRetryKey) == nil, "unknown post-preflight mutation must not replay")
        for stage in [CombinedFailure.Stage.authentication, .signing, .installation, .uniqueDeviceID] {
            clearTestState()
            LiveContainerRefreshBridge.resultFailure = stage
            await execute(source: "manual", task: BGTask())
            precondition(defaults.object(forKey: nextRetryKey) == nil, "terminal failure must not replay")
        }
        clearTestState()
        LiveContainerRefreshBridge.uncertain = true
        await execute(source: "manual", task: BGTask())
        precondition(defaults.object(forKey: nextRetryKey) == nil, "uncertain mutation must not replay")
        print("SCHEDULER_PREFLIGHT_RETRY_PASSED")
    }
}
@main struct SchedulerPreflightRetryTests {
    @MainActor static func main() async { await LiveContainerAutoRefreshScheduler.exercise() }
}
