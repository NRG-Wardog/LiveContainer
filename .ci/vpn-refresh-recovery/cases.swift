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
                     cancelAt: String? = nil, coldPeerFailure: CombinedFailure? = nil) async -> ([String], String) {
        var events: [String] = []; var attempts = 0
        let task = Task { @MainActor () -> String in
            do {
                try await LiveContainerVPNRefreshRecoveryPolicy.run(attempt: {
                    attempts += 1; events.append("attempt\(attempts)")
                    if attempts == 1 && firstFails { throw coldPeerFailure ?? failure() }
                    if attempts == 2 && secondFails { throw FixtureError.second }
                }, mayRecover: { error in
                    events.append("eligibility")
                    if let coldPeerFailure { return permits(error, manifest: manifest([coldPeerFailure])) }
                    return allowed
                }, activate: {
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
    struct SourceFlowResult {
        var attempts = 0
        var initialActivation: Bool?
        var openedURLs: [URL] = []
        var firstFailures: [CombinedFailure] = []
        var status = "pending"
        var retryClearedOldManifest = false
        var sourceReadyOnRetry = false
    }
    @MainActor
    static func sourceFlow(beforeRepair: Bool = false, mode: DeviceConnectionMode = .localVPN,
                           pairing: PairingProtocol = .lockdown, supported: Bool = true,
                           initialInterfaces: [FixtureOS.Interface] = [.init(name: "utun0", address: nil)],
                           usableAfterOpen: Bool = true, mixedBackend: Bool = false,
                           partialSuccess: Bool = false, source: String = "manual", background: Bool = false,
                           foreground: Bool = true, openSucceeds: Bool = true,
                           loseOwnerOnOpen: Bool = false, uncertain: Bool = false) async -> SourceFlowResult {
        var observed = SourceFlowResult()
        let runID = UUID(uuidString: id)!
        LiveContainerAutoRefreshScheduler.reset(runID: runID, requestID: other)
        UIApplication.shared.reset()
        UIApplication.shared.applicationState = foreground ? .active : .background
        UIApplication.shared.openSucceeds = openSucceeds
        NWPathMonitor.fixtureWiFiAvailable = true
        FixtureOS.setInterfaces(initialInterfaces)
        defer { FixtureOS.reset() }
        if uncertain {
            LiveContainerAutoRefreshScheduler.defaults.set(id,
                forKey: LiveContainerAutoRefreshScheduler.uncertainMutationKey)
        }
        UIApplication.shared.onOpen = {
            FixtureOS.setInterfaces([.init(name: "utun0", address: usableAfterOpen ? "10.7.0.1" : nil)])
            if loseOwnerOnOpen {
                LiveContainerAutoRefreshScheduler.defaults.set(id,
                    forKey: LiveContainerAutoRefreshScheduler.activeManualRequestKey)
            }
        }
        LiveContainerAutoRefreshScheduler.fixtureAttempt = { _ in
            observed.attempts += 1
            if observed.attempts == 2 {
                observed.retryClearedOldManifest = LiveContainerAutoRefreshScheduler.defaults.object(
                    forKey: LiveContainerAutoRefreshScheduler.verificationKey) == nil
            }
            let error = beforeRepair
                ? fixtureReadinessBeforeRepair(mode: mode, pairing: pairing, coreDeviceSupported: supported)
                : fixtureReadiness(mode: mode, pairing: pairing, coreDeviceSupported: supported)
            if observed.attempts == 2 { observed.sourceReadyOnRetry = error == nil }
            let ids = ["fixture.app.0", "fixture.app.1"]
            var entries: [[String: Any]] = []
            for index in ids.indices {
                let appError: OperationError? = index == 1 && mixedBackend
                    ? fixtureReadiness(coreDeviceSupported: false) : error
                if let appError, !(index == 1 && partialSuccess) {
                    let preserved = V3RefreshEarlyFailureBoundary.readiness.preserving(
                        appError, operations: [.refresh, .refresh])
                    let captured = CombinedFailure.capture(preserved, operation: "refresh", stage: .command, id: id)
                    entries.append(["bundle_id": ids[index], "success": false, "failure": captured.wire])
                } else {
                    // Only the external completion boundary is synthetic. This
                    // records no real installation and never overrides readiness.
                    entries.append(["bundle_id": ids[index], "success": true])
                }
            }
            let manifest: [String: Any] = ["version": 2, "schema": "LiveContainerRefreshManifestV2",
                "run_id": id, "expected_ids": ids, "requested_ids": ids, "skipped_ids": [String](),
                "host_handoff": false, "results": entries]
            let safe = CombinedVerification.sanitized(["liveContainerAutoRefreshVerification": manifest], runID: id)
            let bytes = try PropertyListSerialization.data(fromPropertyList: safe, format: .binary, options: 0)
            let decoded = try PropertyListSerialization.propertyList(from: bytes, format: nil) as! [String: Any]
            let received = decoded["liveContainerAutoRefreshVerification"] as! [String: Any]
            if observed.attempts == 1 {
                observed.firstFailures = (received["results"] as! [[String: Any]]).compactMap {
                    ($0["failure"] as? [String: Any]).flatMap { CombinedFailure.decode($0, expectedID: id) }
                }
            }
            LiveContainerAutoRefreshScheduler.defaults.set(received,
                forKey: LiveContainerAutoRefreshScheduler.verificationKey)
        }
        do {
            let activated = try await LiveContainerNetworkPreflight.check(
                allowForegroundActivation: source == "manual" && !background, runID: id)
            observed.initialActivation = activated
            try await LiveContainerAutoRefreshScheduler.exercise(runID: runID, source: source,
                hasBackgroundTask: background, activationAlreadyAttempted: activated, requestID: other)
            observed.status = "success"
        } catch is CancellationError { observed.status = "cancelled" }
        catch { observed.status = "failure" }
        observed.openedURLs = UIApplication.shared.openedURLs
        return observed
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
        // The fixture generator derives this exact string from the pinned local
        // minimuxer guard, not from a native/provider message supplied by a test.
        let coldFacts = lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness")
        let coldFailure = CombinedFailure(operation: "refresh", stage: .command, code: .failed,
            id: id, sourceStep: .refreshReadiness, signingContext: coldFacts)
        check("cold_peer_original_classifier_reproduces_missing_reason", lcRefreshFailureFactsBeforeColdVPN(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness") == ["refresh_failure_kind": "noDevice"])
        check("cold_peer_actual_producer_preserves_no_device_and_finite_reason", coldFacts == ["refresh_failure_kind": "noDevice", "refresh_readiness_reason": "peerAddressUnavailable"])
        check("cold_peer_missing_address_allowed", permits(coldFailure, manifest: manifest([coldFailure])))
        let coldDecoded = CombinedFailure.decode(coldFailure.wire, expectedID: id)
        check("cold_peer_wire_roundtrip_preserves_eligibility", coldDecoded.map { permits($0, manifest: manifest([$0])) } == true)
        check("cold_peer_all_app_failures_allowed", permits(coldFailure, manifest: manifest([coldFailure, coldFailure])))
        check("cold_peer_mixed_unknown_device_rejected", !permits(coldFailure, manifest: manifest([coldFailure, failure(kind: "noDevice", reason: "unknown")])))
        check("cold_peer_mixed_pairing_rejected", !permits(coldFailure, manifest: manifest([coldFailure, failure(kind: "invalidPairingFile", reason: "unknown")])))
        check("cold_peer_wrong_kind_reason_stripped", failure(kind: "invalidVPN", reason: "peerAddressUnavailable").signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_stage_reason_stripped", failure(kind: "noDevice", reason: "peerAddressUnavailable", stage: .signing).signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_boundary_reason_stripped", failure(kind: "noDevice", reason: "peerAddressUnavailable", step: .refreshApplication).signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_unclassified_device_error_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: "CoreDevice creation failed"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_remote_endpoint_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: "Remote endpoint IP is not configured or reachable. Cause: DeviceEndpointNotInitialized"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_appended_native_text_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage + " SECRET_PAYLOAD"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_other_local_error_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage.replacingOccurrences(of: "DeviceEndpointNotInitialized", with: "NetworkIfaceNotRefreshed")), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_operation_kind_rejected", lcRefreshFailureFacts(OperationError.invalidVPN(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_readiness_boundary_required", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshApplication")["refresh_readiness_reason"] == nil)
        check("cold_peer_transport_policy_rejected", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "Selected backend has no CoreDevice implementation and IPSec is absent"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_background_never_activates", !permits(coldFailure, source: "bgprocessing", manifest: manifest([coldFailure])))
        check("cold_peer_initial_enable_not_repeated", !permits(coldFailure, activated: true, manifest: manifest([coldFailure])))
        let coldFlow = await flow(coldPeerFailure: coldFailure)
        check("cold_peer_actual_policy_enables_then_one_pipeline_retry", coldFlow.0 == ["attempt1", "eligibility", "activate", "settle", "prepare", "attempt2"] && coldFlow.1 == "success")
        let coldSecondFailure = await flow(secondFails: true, coldPeerFailure: coldFailure)
        check("cold_peer_retry_failure_is_final", coldSecondFailure.0 == coldFlow.0 && coldSecondFailure.1 == "failure")
        let coldCancel = await flow(cancelAt: "activation", coldPeerFailure: coldFailure)
        check("cold_peer_cancel_during_handoff_no_retry", coldCancel.0 == ["attempt1", "eligibility", "activate"] && coldCancel.1 == "cancelled")
        let coldLostOwner = await flow(ownershipLost: true, coldPeerFailure: coldFailure)
        check("cold_peer_changed_ledger_owner_no_retry", coldLostOwner.0 == ["attempt1", "eligibility", "activate", "settle", "prepare"] && coldLostOwner.1 == "failure")

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
        // Same addressless interface snapshot is consumed by the actual host
        // getifaddrs predicate and the actual service scanner. The old producer
        // fails closed; the repaired producer reaches one real URL-open decision.
        let sourceOld = await sourceFlow(beforeRepair: true)
        check("addressless_old_source_preflight_skips_activation", sourceOld.initialActivation == false && sourceOld.attempts == 1 && sourceOld.openedURLs.isEmpty)
        check("addressless_old_source_has_ineligible_invalidvpn", sourceOld.status == "failure" && sourceOld.firstFailures.count == 2 && sourceOld.firstFailures.allSatisfy { $0.signingContext == ["refresh_failure_kind": "invalidVPN"] })
        let sourceNew = await sourceFlow()
        check("addressless_candidate_two_app_wire_preserves_finite_reason", sourceNew.firstFailures.count == 2 && sourceNew.firstFailures.allSatisfy { $0.sourceStep == .refreshReadiness && $0.signingContext == ["refresh_failure_kind": "noVPN", "refresh_readiness_reason": "vpnUnavailable"] })
        check("addressless_candidate_opens_official_enable_url_once", sourceNew.initialActivation == false && sourceNew.openedURLs.map(\.absoluteString) == ["localdevvpn://enable?scheme=fixture-livecontainer"])
        check("addressless_candidate_retries_once_after_return", sourceNew.status == "success" && sourceNew.attempts == 2 && sourceNew.retryClearedOldManifest && sourceNew.sourceReadyOnRetry)
        let sourceStillUnavailable = await sourceFlow(usableAfterOpen: false)
        check("addressless_return_never_forces_ready_or_reopens", sourceStillUnavailable.status == "failure" && sourceStillUnavailable.attempts == 2 && sourceStillUnavailable.openedURLs.count == 1 && !sourceStillUnavailable.sourceReadyOnRetry)
        let sourceUnconfigured = await sourceFlow(mode: .notConfigured)
        check("addressless_unconfigured_source_never_opens", sourceUnconfigured.status == "failure" && sourceUnconfigured.attempts == 1 && sourceUnconfigured.openedURLs.isEmpty)
        let sourcePairing = await sourceFlow(pairing: .unknown)
        check("addressless_missing_pairing_source_never_opens", sourcePairing.status == "failure" && sourcePairing.attempts == 1 && sourcePairing.openedURLs.isEmpty)
        let sourceBackend = await sourceFlow(supported: false)
        check("addressless_unsupported_backend_source_never_opens", sourceBackend.status == "failure" && sourceBackend.attempts == 1 && sourceBackend.openedURLs.isEmpty)
        let sourceMixed = await sourceFlow(mixedBackend: true)
        check("addressless_mixed_backend_batch_never_opens", sourceMixed.status == "failure" && sourceMixed.firstFailures.count == 2 && sourceMixed.attempts == 1 && sourceMixed.openedURLs.isEmpty)
        let sourcePartial = await sourceFlow(partialSuccess: true)
        check("addressless_partial_success_batch_never_opens", sourcePartial.status == "failure" && sourcePartial.attempts == 1 && sourcePartial.openedURLs.isEmpty)
        let sourceBackground = await sourceFlow(source: "bgprocessing", background: true)
        check("addressless_background_source_never_opens", sourceBackground.status == "failure" && sourceBackground.attempts == 1 && sourceBackground.openedURLs.isEmpty)
        let sourceInactive = await sourceFlow(foreground: false)
        check("addressless_inactive_host_never_opens", sourceInactive.status == "failure" && sourceInactive.attempts == 1 && sourceInactive.openedURLs.isEmpty)
        let sourceOpenFailed = await sourceFlow(openSucceeds: false)
        check("addressless_open_rejection_never_retries", sourceOpenFailed.status == "failure" && sourceOpenFailed.attempts == 1 && sourceOpenFailed.openedURLs.count == 1)
        let sourceLostOwner = await sourceFlow(loseOwnerOnOpen: true)
        check("addressless_changed_request_owner_never_retries", sourceLostOwner.status == "cancelled" && sourceLostOwner.attempts == 1 && sourceLostOwner.openedURLs.count == 1)
        let sourceUncertain = await sourceFlow(uncertain: true)
        check("addressless_uncertain_mutation_never_opens", sourceUncertain.status == "failure" && sourceUncertain.attempts == 1 && sourceUncertain.openedURLs.isEmpty)
        let sourceInitial = await sourceFlow(initialInterfaces: [], usableAfterOpen: false)
        check("source_initial_activation_consumes_single_allowance", sourceInitial.initialActivation == true && sourceInitial.status == "failure" && sourceInitial.attempts == 1 && sourceInitial.openedURLs.count == 1)
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
