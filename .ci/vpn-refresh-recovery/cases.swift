@main
struct VPNRefreshRecoveryCases {
    static let id = "11111111-1111-1111-1111-111111111111"
    static let other = "22222222-2222-2222-2222-222222222222"
    static func failure(kind: String = "noVPN", reason: String = "vpnUnavailable",
                        run: String = id, step: CombinedFailure.SourceStep = .refreshReadiness,
                        stage: CombinedFailure.Stage = .command, retryable: Bool? = nil) -> CombinedFailure {
        CombinedFailure(operation: "refresh", stage: stage, code: .failed, id: run,
            retryable: retryable, sourceStep: step,
            signingContext: ["refresh_failure_kind": kind, "refresh_readiness_reason": reason])
    }
    static func manifest(_ failures: [CombinedFailure] = [failure()]) -> [String: Any] {
        let ids = failures.indices.map { "fixture.app.\($0)" }
        return ["version": 2, "schema": "LiveContainerRefreshManifestV2", "run_id": id,
                "expected_ids": ids, "requested_ids": ids, "skipped_ids": [String](), "host_handoff": false,
                "results": failures.enumerated().map { index, value in
                    ["bundle_id": ids[index], "success": false, "failure": value.wire] as [String: Any]
                }]
    }
    static func permits(_ failure: Error = failure(), source: String = "manual", background: Bool = false,
                        activated: Bool = false, active: String? = id, expected: String? = id,
                        request: String? = other, activeRequest: String? = other,
                        record: [String: Any]? = ["run_id": id, "request_id": other, "state": "running"],
                        handoff: Bool = false, uncertain: String? = nil, manifest value: [String: Any]? = manifest()) -> Bool {
        LiveContainerVPNRefreshRecoveryPolicy.permitsRecovery(error: failure, runID: id, source: source,
            hasBackgroundTask: background, activationAlreadyAttempted: activated, activeRunID: active,
            expectedRunID: expected, requestID: request, activeRequestID: activeRequest, record: record,
            hostHandoffPending: handoff, uncertainMutationRunID: uncertain, manifest: value)
    }
    enum FixtureError: Error { case activation, settlement, ownership, second }
    @MainActor
    static func flow(firstFails: Bool = true, allowed: Bool = true, activationFails: Bool = false,
                     settlementFails: Bool = false, ownershipLost: Bool = false, secondFails: Bool = false,
                     cancelAt: String? = nil) async -> ([String], String) {
        var events: [String] = []; var attempts = 0
        let task = Task { @MainActor () -> String in
            do {
                try await LiveContainerVPNRefreshRecoveryPolicy.run(attempt: {
                    attempts += 1; events.append("attempt\(attempts)")
                    if attempts == 1 && firstFails { throw failure() }
                    if attempts == 2 && secondFails { throw FixtureError.second }
                }, mayRecover: { _ in events.append("eligibility"); return allowed }, activate: {
                    events.append("activate")
                    if cancelAt == "activation" { withUnsafeCurrentTask { $0?.cancel() } }
                    if activationFails { throw FixtureError.activation }
                }, settle: {
                    events.append("settle")
                    if cancelAt == "settlement" { withUnsafeCurrentTask { $0?.cancel() } }
                    if settlementFails { throw FixtureError.settlement }
                }, prepareRetry: {
                    events.append("prepare")
                    if ownershipLost { throw FixtureError.ownership }
                })
                return "success"
            } catch is CancellationError { return "cancelled" }
            catch { return "failure" }
        }
        let result = await task.value
        return (events, result)
    }
    @MainActor
    static func main() async throws {
        var names: [String] = []
        func check(_ name: String, _ value: Bool) { precondition(value, name); names.append(name) }
        check("typed_missing_vpn_allowed", permits())
        let peer = failure(kind: "invalidVPN", reason: "peerProbeFailed")
        check("finite_peer_probe_allowed", permits(peer, manifest: manifest([peer])))
        check("unknown_invalidvpn_rejected", !permits(failure(kind: "invalidVPN", reason: "unknown")))
        check("missing_finite_reason_rejected", !permits(failure(reason: "")))
        check("signing_invalid_parameters_rejected", !permits(failure(kind: "invalidParameters", step: .provisioningProfileFetch, stage: .signing)))
        check("pairing_failure_rejected", !permits(failure(kind: "invalidPairingFile")))
        check("other_backend_readiness_rejected", !permits(failure(kind: "noDevice")))
        check("explicit_nonretryable_rejected", !permits(failure(retryable: false)))
        check("wrong_outer_run_rejected", !permits(failure(run: other)))
        check("background_source_rejected", !permits(source: "bgprocessing"))
        check("background_task_rejected", !permits(background: true))
        check("resume_source_rejected", !permits(source: "launch_or_resume"))
        check("vpn_return_recursion_rejected", !permits(source: "vpn_return"))
        check("alarm_not_new_recovery_authority", !permits(source: "alarm_action"))
        check("earlier_preflight_handoff_counts", !permits(activated: true))
        check("lost_active_owner_rejected", !permits(active: other))
        check("lost_expected_owner_rejected", !permits(expected: other))
        check("changed_manual_request_rejected", !permits(activeRequest: id))
        check("missing_manual_request_rejected", !permits(request: nil))
        check("terminal_ledger_rejected", !permits(record: ["run_id": id, "request_id": other, "state": "failed"]))
        check("wrong_ledger_request_rejected", !permits(record: ["run_id": id, "request_id": id, "state": "running"]))
        check("host_handoff_rejected", !permits(handoff: true))
        check("uncertain_mutation_rejected", !permits(uncertain: id))
        check("missing_manifest_rejected", !permits(manifest: nil))
        check("empty_manifest_rejected", !permits(manifest: manifest([])))
        check("every_attempted_app_matches", permits(manifest: manifest([failure(), peer])))
        check("mixed_backend_failure_rejected", !permits(manifest: manifest([failure(), failure(kind: "noDevice")])))
        check("mismatched_app_run_rejected", !permits(manifest: manifest([failure(run: other)])))
        var partial = manifest([failure(), peer]); partial["results"] = (partial["results"] as! [[String: Any]]).prefix(1).map { $0 }
        check("partial_manifest_rejected", !permits(manifest: partial))
        var success = manifest([failure(), peer]); var entries = success["results"] as! [[String: Any]]; entries[1]["success"] = true; success["results"] = entries
        check("partial_success_rejected", !permits(manifest: success))
        var handoff = manifest(); handoff["host_handoff"] = true
        check("manifest_handoff_rejected", !permits(manifest: handoff))
        check("raw_error_rejected", !permits(NSError(domain: "private", code: 1)))
        let missing = lcRefreshFailureFacts(OperationError.noVPN(reason: "SECRET_PAYLOAD"), sourceStep: "refreshReadiness")
        check("producer_typed_novpn_reason", missing == ["refresh_failure_kind": "noVPN", "refresh_readiness_reason": "vpnUnavailable"])
        let peerText = "VPN tunnel iface is up and tunnel peer IP fd00::1234 is known, but TCP port poll failed — device may be unreachable on this interface"
        let exact = lcRefreshFailureFacts(OperationError.invalidVPN(reason: peerText), sourceStep: "refreshReadiness")
        check("producer_exact_probe_reason_no_peer_export", exact == ["refresh_failure_kind": "invalidVPN", "refresh_readiness_reason": "peerProbeFailed"])
        check("producer_policy_invalidvpn_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "unsupported backend policy"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("producer_arbitrary_native_drop_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "broken pipe SECRET_PAYLOAD"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("producer_probe_wrong_boundary_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: peerText), sourceStep: "refreshApplication")["refresh_readiness_reason"] == nil)
        let direct = await flow(firstFails: false)
        check("ready_pipeline_no_handoff", direct.0 == ["attempt1"] && direct.1 == "success")
        let recovered = await flow()
        check("failed_ready_handoff_then_one_recheck", recovered.0 == ["attempt1", "eligibility", "activate", "settle", "prepare", "attempt2"] && recovered.1 == "success")
        let repeated = await flow(secondFails: true)
        check("second_failure_no_third_attempt", repeated.0 == recovered.0 && repeated.1 == "failure")
        let denied = await flow(allowed: false)
        check("ineligible_failure_no_handoff", denied.0 == ["attempt1", "eligibility"] && denied.1 == "failure")
        let open = await flow(activationFails: true)
        check("launch_failure_no_retry", open.0 == ["attempt1", "eligibility", "activate"] && open.1 == "failure")
        let settle = await flow(settlementFails: true)
        check("settlement_failure_no_retry", settle.0 == ["attempt1", "eligibility", "activate", "settle"] && settle.1 == "failure")
        let lost = await flow(ownershipLost: true)
        check("ownership_loss_no_retry", lost.0 == ["attempt1", "eligibility", "activate", "settle", "prepare"] && lost.1 == "failure")
        let cancelActivation = await flow(cancelAt: "activation")
        check("cancelled_handoff_no_retry", cancelActivation.0 == ["attempt1", "eligibility", "activate"] && cancelActivation.1 == "cancelled")
        let cancelSettle = await flow(cancelAt: "settlement")
        check("cancelled_settlement_no_retry", cancelSettle.0 == ["attempt1", "eligibility", "activate", "settle"] && cancelSettle.1 == "cancelled")
        var settles = 0
        let waiter = LiveContainerVPNActivationWaiter(runID: id) { _, _ in settles += 1 }
        waiter.settle(.timedOut); waiter.settle(.returned)
        let outcome = await waiter.value()
        check("timeout_late_return_settles_once", outcome == .timedOut && settles == 1)
        let start = Date(timeIntervalSince1970: 100)
        let marker = LiveContainerVPNReturnMarkerPolicy.marker(runID: id, requestedAt: start)!
        check("expired_cold_return_not_replayed", !LiveContainerVPNReturnMarkerPolicy.shouldResume(marker, now: start.addingTimeInterval(120)))
        check("marker_other_owner_not_cleared", !LiveContainerVPNReturnMarkerPolicy.isOwned(by: other, value: marker))
        let receiptURL = URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().appendingPathComponent("sources.json")
        let receipt = try JSONSerialization.jsonObject(with: Data(contentsOf: receiptURL)) as! [String: Any]
        precondition(names == receipt["expected_case_names"] as! [String])
        let report: [String: Any] = ["schema": "vpn-refresh-recovery-cases-v1", "status": "pass", "cases": names,
            "case_count": names.count, "network_executed": false, "native_provider_executed": false]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("VPN_REFRESH_RECOVERY_PASS cases=\(names.count)")
    }
}
