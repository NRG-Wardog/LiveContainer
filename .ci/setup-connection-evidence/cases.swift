@main
struct SetupConnectionCases {
    static let first = "11111111-1111-1111-1111-111111111111"
    static let second = "22222222-2222-2222-2222-222222222222"
    static func failure(_ id: String, kind: String = "invalidVPN", step: CombinedFailure.SourceStep = .refreshReadiness,
                        operation: String = "refresh", code: CombinedFailure.Code = .failed) -> [String: Any] {
        CombinedFailure(operation: operation, stage: .command, code: code, id: id,
            sourceStep: step, signingContext: ["refresh_failure_kind": kind]).wire
    }
    static func record(_ id: String, at: Double, state: String = "failed", failure: [String: Any]? = nil) -> [String: Any] {
        var record: [String: Any] = ["run_id": id, "started_at": at, "state": state]
        if let failure { record["failure"] = failure }
        return record
    }
    static func verified(_ id: String, at: Double) -> [String: Any] {
        ["run_id": id, "started_at": at, "state": "completed", "terminal_intent": "verified",
         "health": "REFRESH_SUCCEEDED", "manifest_run_id": id,
         "manifest_summary": ["version": 2, "schema": "LiveContainerRefreshManifestSummaryV2", "run_id": id,
             "verified": true, "expected_count": 1, "result_count": 1, "failed_count": 0,
             "skipped_count": 0, "requested_count": 1]]
    }
    static func main() throws {
        var cases: [String] = []
        func check(_ name: String, _ expected: V3SetupConnectionEvidencePolicy.Evidence,
                   _ ledger: [String: Any] = [:], present: Bool = true, active: String? = nil,
                   handoff: Bool = false, uncertain: String? = nil) {
            let observed = V3SetupConnectionEvidencePolicy.observe(interfacePresent: present, ledger: ledger,
                activeRunID: active, hostHandoffPending: handoff, uncertainMutationRunID: uncertain)
            precondition(observed.evidence == expected, name)
            precondition(observed.isVerified == (expected == .verified), name + " green gate")
            if expected != .verified {
                precondition(observed.tunnelStep.state != "complete" && observed.tunnelStep.state != "verified", name + " no green tunnel")
                precondition(observed.coreDeviceStep.state != "complete" && observed.coreDeviceStep.state != "verified", name + " no green device")
            }
            precondition(observed.coreDeviceStep.state != "complete" && observed.coreDeviceStep.state != "verified", name + " no inferred CoreDevice transport")
            cases.append(name)
        }
        let badVPN = record(first, at: 1, failure: failure(first))
        let good = verified(first, at: 1)
        check("presence_is_detection_only", .detected)
        check("absence_is_not_ready", .notDetected, present: false)
        check("matching_invalidvpn", .vpnNotReady, [first: badVPN])
        check("matching_novpn", .vpnNotReady, [first: record(first, at: 1, failure: failure(first, kind: "noVPN"))])
        check("other_readiness_not_blame_vpn", .readinessFailed, [first: record(first, at: 1, failure: failure(first, kind: "noDevice"))])
        check("wrong_correlation_rejected", .detected, [first: record(first, at: 1, failure: failure(second))])
        check("wrong_operation_rejected", .detected, [first: record(first, at: 1, failure: failure(first, operation: "install"))])
        check("wrong_step_rejected", .detected, [first: record(first, at: 1, failure: failure(first, step: .refreshPreflight))])
        check("cancelled_not_vpn_failure", .detected, [first: record(first, at: 1, failure: failure(first, code: .cancelled))])
        check("newer_signing_does_not_infer_success", .detected,
            [first: badVPN, second: record(second, at: 2, failure: failure(second, step: .refreshApplication))])
        check("newer_verified_supersedes_stale_failure", .verified, [first: badVPN, second: verified(second, at: 2)])
        check("newer_readiness_supersedes_old_success", .vpnNotReady,
            [first: good, second: record(second, at: 2, failure: failure(second))])
        check("latest_full_summary_verifies", .verified, [first: good])
        check("no_interface_no_current_green", .notDetected, [first: good], present: false)
        check("active_run_suppresses_old_green", .checking, [first: good], active: second)
        check("handoff_suppresses_old_green", .checking, [first: good], handoff: true)
        check("uncertainty_suppresses_old_green", .checking, [first: good], uncertain: second)
        check("newer_pending_suppresses_old_green", .checking,
            [first: good, second: record(second, at: 2, state: "running")])
        check("ambiguous_timestamp_not_verified", .detected, [first: good, second: verified(second, at: 1)])
        var missingTime = good; missingTime.removeValue(forKey: "started_at")
        check("missing_timestamp_not_verified", .detected, [first: missingTime])
        var boolTime = good; boolTime["started_at"] = true
        check("boolean_timestamp_not_verified", .detected, [first: boolTime])
        var nonfinite = good; nonfinite["started_at"] = Double.infinity
        check("nonfinite_timestamp_not_verified", .detected, [first: nonfinite])
        check("mismatched_ledger_owner_not_verified", .detected, [second: good])
        check("unverified_completion_not_green", .detected, [first: record(first, at: 1, state: "completed")])
        var injected = failure(first); injected["signingContext"] = ["refresh_failure_kind": "SECRET_PROVIDER_PAYLOAD"]
        check("unallowlisted_kind_rejected", .detected, [first: record(first, at: 1, failure: injected)])
        let observation = V3SetupConnectionEvidencePolicy.observe(interfacePresent: true, ledger: [first: badVPN],
            activeRunID: nil, hostHandoffPending: false, uncertainMutationRunID: nil)
        precondition(observation.tunnelStep.detail.contains("Enable LocalDevVPN"))
        precondition(!observation.tunnelStep.detail.contains("SECRET_PROVIDER_PAYLOAD"))
        precondition(!observation.tunnelStep.detail.contains("VPN was off"))
        precondition(V3SetupConnectionCopy(rawValue: "SECRET_PROVIDER_PAYLOAD") == nil)
        let receiptURL = URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().appendingPathComponent("sources.json")
        let receipt = try JSONSerialization.jsonObject(with: Data(contentsOf: receiptURL)) as! [String: Any]
        precondition(cases == receipt["expected_case_names"] as! [String])
        let report: [String: Any] = ["schema": "setup-connection-cases-v1", "status": "pass", "cases": cases,
            "case_count": cases.count, "network_executed": false, "native_provider_executed": false]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("SETUP_CONNECTION_EVIDENCE_PASS cases=\(cases.count)")
    }
}
