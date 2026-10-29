@main struct Issue56HostCases {
    @MainActor static func main() async throws {
        let id = "00000000-0000-0000-0000-000000000056"
        let causes = ["databaseLayoutBlocked", "databaseLayoutConflict", "databaseAppGroupUnavailable",
                      "databasePersistenceFailed", "databaseStartupFailed", "databaseHostBundleUnavailable", "databaseHostProfileUnavailable", "databaseModelUnrecognized", "databaseMigrationPathUnavailable", "databaseMigrationFailed", "databaseSaveFailed"]
        func failure(_ cause: String?, code: String = "failed", retryable: Bool = false,
                     stage: String = "serviceReadiness") throws -> Data {
            var envelope: [String: Any] = ["version": 1, "operation": "snapshot", "stage": stage,
                "code": code, "correlationID": id, "underlyingDomain": "none", "underlyingCode": 0,
                "retryable": retryable]
            if let cause { envelope["safeCause"] = cause }
            return try PropertyListSerialization.data(fromPropertyList: ["version": 1, "id": id,
                "error": "failed", "failure": envelope], format: .binary, options: 0)
        }
        for cause in causes {
            guard case .failed(let parsed) = V3ServiceReadinessReply.decode(try! failure(cause), requestID: id) else {
                fatalError("terminal failure was retried")
            }
            precondition(parsed.safeCause == cause && parsed.retryable == false)
            precondition(V3ServiceReadinessProbeState.resolve(ready: false, invalid: false,
                hasTerminalFailure: true, expired: false) == .failed)
            precondition(V3ServiceReadinessReply.decode(try! failure(cause, code: "notReady", retryable: true), requestID: id) == .invalid)
            precondition(V3ServiceReadinessReply.decode(try! failure(cause, retryable: true), requestID: id) == .invalid)
            precondition(V3ServiceReadinessReply.decode(try! failure(cause, stage: "persistence"), requestID: id) == .invalid)
        }
        precondition(V3ServiceReadinessReply.decode(try! failure("/private/token=secret@example.invalid"), requestID: id) == .invalid)
        // Legitimately pending startup remains retryable and can later succeed.
        precondition(V3ServiceReadinessReply.decode(try! failure(nil, code: "notReady", retryable: true), requestID: id) == .notReady)
        let success = try PropertyListSerialization.data(fromPropertyList: ["version": 1, "id": id,
            "ok": true, "result": ["ready": true]], format: .binary, options: 0)
        precondition(V3ServiceReadinessReply.decode(success, requestID: id) == .ready)
        precondition(V3ServiceReadinessProbeState.resolve(ready: false, invalid: false, hasTerminalFailure: false, expired: false) == .pending)
        // No callback must still become a genuine timeout, not a fabricated DB diagnosis.
        precondition(V3ServiceReadinessProbeState.resolve(ready: false, invalid: false, hasTerminalFailure: false, expired: true) == .timedOut)
        precondition(V3ServiceReadinessProbeState.resolve(ready: true, invalid: false, hasTerminalFailure: false, expired: true) == .ready)
        let afterYield = await V3ServiceReadinessProbeState.recheckAfterYield(
            ready: { false }, invalid: { false }, hasTerminalFailure: { true })
        precondition(afterYield == .failed)
        var backoff = V3ServiceReadinessBackoff()
        precondition(backoff.nextDelay(remaining: 30) == 0.2)
        precondition(backoff.nextDelay(remaining: 0) == nil)
        var log = V3StartupDiagnosticLog()
        log.record(.launchRequested)
        log.record(.applicationReady)
        log.record(.failed, stage: "serviceReadiness", code: "failed", cause: causes[0])
        precondition(log.text.contains("cause=databaseLayoutBlocked"))
        let injection = "/private/account@example.invalid/token=SECRET.sqlite"
        log.record(.failed, stage: injection, code: injection, cause: injection)
        precondition(!log.text.contains(injection) && !log.text.contains("SECRET"))
        precondition(log.text.contains("stage=unknown code=unknown cause=notRecorded"))
        for _ in 0..<100 { log.record(.launchRequested) }
        precondition(log.entries.count == 32 && log.text.utf8.count < 6400)
        precondition(!V3OperationLogLoadPolicy.shouldRequestServiceLogs(serviceReady: false))
        precondition(V3OperationLogLoadPolicy.shouldRequestServiceLogs(serviceReady: true))
        let bridge = V3ServiceBridge.shared
        bridge.startupDiagnosticText = "event=failed stage=serviceReadiness code=failed cause=databaseLayoutConflict"
        let logs = LogsHarness()
        await logs.reload()
        precondition(bridge.requests == 0 && logs.startup == bridge.startupDiagnosticText + "\n" + LCUtils.guestLaunchDiagnosticSnapshot())
        precondition(!logs.reloading && !logs.message.isEmpty && logs.tail.isEmpty)
        bridge.serviceReadyForOperationLogs = true
        await logs.reload()
        precondition(bridge.requests == 1 && logs.tail == "operation log fixture")
        bridge.failure = NSError(domain: "fixture", code: 1)
        await logs.reload()
        precondition(bridge.requests == 2 && logs.startup == bridge.startupDiagnosticText + "\n" + LCUtils.guestLaunchDiagnosticSnapshot() && !logs.reloading)
        precondition(V3OperationLogLoadPolicy.canCopy(reloading: false, startup: logs.startup, operations: ""))
        precondition(!V3OperationLogLoadPolicy.canCopy(reloading: true, startup: logs.startup, operations: ""))
        precondition(V3OperationLogLoadPolicy.copyText(startup: logs.startup, operations: "") == logs.startup)
        let terminal = CombinedFailure(stage: .serviceReadiness, code: .failed, retryable: false,
            safeCause: .databaseLayoutConflict)
        precondition(terminal.isTerminalDatabaseStartupFailure)
        let snapshot = SnapshotHarness()
        bridge.failure = terminal
        let failedSnapshot = await snapshot.performSnapshot()
        precondition(failedSnapshot == .snapshotFailed && snapshot.terminalStartupFailure != nil)
        precondition(!snapshot.connected && snapshot.requiresConnectionRetry && snapshot.presented == 1)
        bridge.failure = nil
        let successSnapshot = await snapshot.performSnapshot()
        precondition(successSnapshot == .applied && snapshot.terminalStartupFailure == nil)
        precondition(snapshot.connected && !snapshot.requiresConnectionRetry)
        let status = V3SideStoreStatusStore(), setup = SetupHarness()
        status.terminalStartupFailure = CombinedFailure(stage: .serviceReadiness, code: .failed, retryable: false, safeCause: .databaseLayoutConflict)
        setup.preserveUnknownStatusFacts(status: status)
        precondition(setup.account.state == "failed" && setup.pairing.state == "failed" && setup.jitless.state == "failed")
        precondition(setup.account.detail == "SideStore stopped startup because conflicting saved data locations were found." && status.invalidations == 1)
        status.terminalStartupFailure = nil
        setup.preserveUnknownStatusFacts(status: status)
        precondition(setup.account.state == "checking" && setup.pairing.state == "checking" && setup.jitless.state == "checking")
        print("ISSUE56_HOST_BOUNDARIES_PASS terminal=11 malformed=34 delayed_success=1 no_callback_timeout=1 redaction=1 bounded_log=1 actual_log_reload=3 actual_setup=2 failed_to_success_snapshot=2 logs_copy=3")
    }
}
