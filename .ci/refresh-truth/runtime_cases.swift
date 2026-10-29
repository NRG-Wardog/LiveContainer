let run = "11111111-1111-4111-8111-111111111111"
func evidence(_ renewal: String = "extended", store: String = "matched", certificate: String = "valid", ack: Any = true, dispatched: Any = true) -> [String: Any] {
    ["version": 1, "mutationDispatched": dispatched, "installAcknowledged": ack, "profileStore": store, "renewal": renewal, "certificate": certificate]
}
func manifest(_ value: [String: Any]? = evidence(), success: Bool = true) -> [String: Any] {
    var entry: [String: Any] = ["bundle_id": "example.main", "success": success]
    if let value { entry["verification"] = value }
    return ["version": 2, "schema": "LiveContainerRefreshManifestV2", "run_id": run,
        "expected_ids": ["example.main"], "requested_ids": ["example.main"], "skipped_ids": [String](), "results": [entry]]
}
func expect(_ value: @autoclosure () -> Bool, _ name: String) {
    precondition(value(), name); print("PASS " + name)
}
expect(V3RefreshEvidencePolicy.outcome(manifest(), runID: run) == .renewed, "matched_extended_valid")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence("unchanged")), runID: run) == .installedUnchanged, "imported_unchanged")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence("shortened")), runID: run) == .verificationFailed, "shortened")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence("unknown", store: "mismatch")), runID: run) == .verificationFailed, "missing_or_mismatched")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence("unknown", store: "unavailable")), runID: run) == .acknowledgedUnverified, "readback_unavailable")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence(certificate: "unknown")), runID: run) == .acknowledgedUnverified, "certificate_unknown")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence(certificate: "invalid")), runID: run) == .verificationFailed, "certificate_invalid")
expect(V3RefreshEvidencePolicy.outcome(manifest(nil), runID: run) == .unconfirmed, "legacy_success_not_renewed")
expect(V3RefreshEvidencePolicy.outcome(manifest(), runID: UUID().uuidString) == .unconfirmed, "stale_run")
expect(V3RefreshProfileEvidence(evidence(ack: 1)) == nil, "integer_not_boolean")
var extra = evidence(); extra["profileBytes"] = "secret"
expect(V3RefreshProfileEvidence(extra) == nil, "reject_extra_fields")
var wrongVersion = evidence(); wrongVersion["version"] = true
expect(V3RefreshProfileEvidence(wrongVersion) == nil, "reject_boolean_version")
var reason = evidence(); reason["reason"] = "account@example.com"
expect(V3RefreshProfileEvidence(reason) == nil, "reject_unbounded_reason")
expect(V3RefreshProfileEvidence(evidence("extended", store: "unavailable")) == nil, "reject_contradictory_extension")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence(), success: false), runID: run) == .acknowledgedUnverified, "save_failure_not_green")
var mixed = manifest(); mixed["expected_ids"] = ["example.main", "example.other"]; mixed["requested_ids"] = ["example.main", "example.other"]
mixed["results"] = [["bundle_id": "example.main", "success": true, "verification": evidence()], ["bundle_id": "example.other", "success": true, "verification": evidence("unchanged")]]
expect(V3RefreshEvidencePolicy.outcome(mixed, runID: run) == .installedUnchanged, "all_targets_required")
func summary(_ outcome: String, renewed: Int = 0, ack: Int = 1) -> [String: Any] {
    ["version": 2, "schema": "LiveContainerRefreshManifestSummaryV2", "run_id": run, "verified": true,
     "expected_count": 1, "result_count": 1, "failed_count": 0, "skipped_count": 0, "requested_count": 1,
     "evidence_version": 1, "renewal_outcome": outcome, "renewed_count": renewed, "acknowledged_count": ack]
}
let request = "22222222-2222-4222-8222-222222222222"
func record(_ outcome: String, state: String = "failed", renewed: Int = 0) -> [String: Any] {
    ["run_id": run, "request_id": request, "state": state, "renewal_presentation": true, "terminal_intent": "verified", "health": "REFRESH_SUCCEEDED",
     "manifest_run_id": run, "manifest_summary": summary(outcome, renewed: renewed)]
}
expect(!V3RefreshAllTerminalEvidencePolicy.verifiedSummary(summary("installedUnchanged"), record: record("installedUnchanged", state: "completed"), runID: run), "summary_unchanged_not_green")
expect(V3RefreshAllTerminalEvidencePolicy.verifiedSummary(summary("renewed", renewed: 1), record: record("renewed", state: "completed", renewed: 1), runID: run), "summary_exact_renewal")
var legacySummary = summary("renewed", renewed: 1); legacySummary.removeValue(forKey: "evidence_version")
expect(!V3RefreshAllTerminalEvidencePolicy.verifiedSummary(legacySummary, record: record("renewed", state: "completed", renewed: 1), runID: run), "legacy_summary_not_green")
var attempt = V3RefreshAllAttemptState(); attempt.begin(requestID: request)
expect(attempt.observe(record("installedUnchanged")) && attempt.terminalMessage == V3RefreshRenewalOutcome.installedUnchanged.message, "same_session_unchanged_message")
expect(!attempt.observe(record("renewed", state: "completed", renewed: 1)), "late_callback_cannot_promote_terminal")
attempt.acknowledge(); attempt.begin(requestID: request)
expect(attempt.observe(record("acknowledgedUnverified")) && attempt.terminalMessage == V3RefreshRenewalOutcome.acknowledgedUnverified.message, "same_session_unknown_message")
expect(!V3HomeRefreshVerificationPolicy.isVerified(manifest: manifest(nil), ledger: [run: record("renewed", state: "completed", renewed: 1)], activeRunID: nil, hostHandoffPending: false, uncertainMutationRunID: nil), "home_legacy_manifest_not_green")
var contradiction = evidence(); contradiction["reason"] = "certificateRevoked"
expect(V3RefreshProfileEvidence(contradiction) == nil, "reject_contradictory_reason")
var badRecord = record("installedUnchanged"); var badSummary = summary("installedUnchanged"); badSummary["evidence_version"] = true; badRecord["manifest_summary"] = badSummary
expect(V3RefreshEvidencePolicy.recordedOutcome(badRecord, runID: run) == nil, "reject_boolean_summary_version")
expect(V3RefreshEvidencePolicy.failurePresentation(manifest(), runID: run, stage: "refreshVerification", code: "failed") == nil, "downstream_guest_failure_preserved")
expect(V3RefreshEvidencePolicy.failurePresentation(manifest(evidence(), success: false), runID: run, stage: "persistence", code: "failed") == nil, "database_failure_preserved")
expect(V3RefreshEvidencePolicy.failurePresentation(manifest(), runID: run, stage: "refreshVerification", code: "missingResult") == nil, "renewed_never_failure_success_copy")
expect(V3RefreshEvidencePolicy.outcome(manifest(evidence("unknown", store: "unavailable", certificate: "unknown", ack: false), success: false), runID: run) == .mutationUnconfirmed, "lost_ack_not_acknowledged")
expect(!V3RefreshEvidencePolicy.canClearUncertainty(manifest(evidence("unknown", store: "unavailable", certificate: "unknown", ack: false), success: false), runID: run), "lost_ack_retains_uncertainty")
expect(!V3RefreshEvidencePolicy.canClearUncertainty(manifest(nil), runID: run), "missing_evidence_retains_uncertainty")
expect(V3RefreshEvidencePolicy.canClearUncertainty(manifest(), runID: run), "all_ack_can_settle_mutation")
expect(V3RefreshProfileEvidence(evidence(dispatched: false)) == nil, "ack_requires_dispatch")
expect(!V3RefreshEvidencePolicy.isPreMutationFailure(stage: "installation", sourceStep: "provisioningProfileInstallation"), "native_exception_no_auto_retry")
expect(!V3RefreshEvidencePolicy.isPreMutationFailure(stage: "command", sourceStep: nil), "unknown_boundary_no_auto_retry")
expect(V3RefreshEvidencePolicy.isPreMutationFailure(stage: "command", sourceStep: "refreshReadiness"), "known_readiness_remains_recoverable")
var host = manifest(nil); host["expected_ids"] = [V3HostProfileRenewalProof.originalHostID]; host["requested_ids"] = [V3HostProfileRenewalProof.originalHostID]; host["host_handoff"] = true
host["results"] = [["bundle_id": V3HostProfileRenewalProof.originalHostID, "success": true]]
let observedAt = Date(timeIntervalSince1970: 100)
let baseline: [String: Any] = ["run_id": run, "installed_bundle_id": "signed.host", "identifier": "TEAM.signed.host", "expiration": Date(timeIntervalSince1970: 200)]
expect(V3HostProfileRenewalProof.record(in: &host, runID: run, baseline: baseline, installedBundleID: "signed.host", observedIdentifier: "TEAM.signed.host", observedExpiration: Date(timeIntervalSince1970: 300), observedAt: observedAt), "host_owned_observation_recorded")
expect(V3RefreshEvidencePolicy.outcome(host, runID: run) == .hostProfileAdvanced, "host_proof_separate_mode")
var wrongHost = host; wrongHost["results"] = [["bundle_id": "example.main", "success": true]]; wrongHost["expected_ids"] = ["example.main"]; wrongHost["requested_ids"] = ["example.main"]
expect(V3RefreshEvidencePolicy.outcome(wrongHost, runID: run) != .renewed, "host_proof_cannot_cover_other_app")
var badBaseline = baseline; badBaseline["run_id"] = UUID().uuidString
expect(!V3HostProfileRenewalProof.record(in: &host, runID: run, baseline: badBaseline, installedBundleID: "signed.host", observedIdentifier: "TEAM.signed.host", observedExpiration: Date(timeIntervalSince1970: 300), observedAt: observedAt), "old_baseline_rejected")
expect(!V3HostProfileRenewalProof.record(in: &host, runID: run, baseline: baseline, installedBundleID: "wrong.host", observedIdentifier: "TEAM.signed.host", observedExpiration: Date(timeIntervalSince1970: 300), observedAt: observedAt), "wrong_host_identity_rejected")
expect(!V3HostProfileRenewalProof.record(in: &host, runID: run, baseline: baseline, installedBundleID: "signed.host", observedIdentifier: "TEAM.signed.host", observedExpiration: Date(timeIntervalSince1970: 200), observedAt: observedAt), "unchanged_host_expiry_rejected")
let sanitized = CombinedVerification.sanitized(["liveContainerAutoRefreshVerification": host, "liveContainerAutoRefreshHostHandoffRunID":run, "liveContainerAutoRefreshHostHandoff":true], runID:run)
expect((sanitized["liveContainerAutoRefreshVerification"] as? [String:Any])?["host_profile_verification"] == nil, "remote_host_proof_dropped")
let directLost: [String: Any] = ["state":"failed", "backendSettled":true, "verification":evidence("unknown",store:"unavailable",certificate:"unknown",ack:false)]
expect(V3DirectProfileVerificationPolicy.blocksRetry(directLost, operation:"refresh"), "direct_lostack_settled_no_retry")
expect(V3DirectProfileVerificationPolicy.requiresDeviceCheck(directLost, operation:"refresh"), "direct_lostack_devicecheck")
let directUnchanged: [String: Any] = ["state":"completed", "backendSettled":true, "verification":evidence("unchanged")]
expect(V3DirectProfileVerificationPolicy.outcome(directUnchanged, operation:"resign") == .installedUnchanged, "direct_resign_unchanged_not_renewal")
expect(V3DirectProfileVerificationPolicy.blocksRetry(directUnchanged, operation:"resign"), "direct_ack_no_blind_retry")
let directBefore: [String: Any] = ["state":"cancelled", "backendSettled":true, "verification":evidence("unknown",store:"unavailable",certificate:"unknown",ack:false,dispatched:false)]
expect(!V3DirectProfileVerificationPolicy.blocksRetry(directBefore, operation:"install"), "direct_predispatch_retry_allowed")
expect(V3DirectProfileVerificationPolicy.outcome(["state":"completed"],operation:"install") == .unconfirmed, "direct_old_success_unconfirmed")
expect(!V3DirectProfileVerificationPolicy.blocksRetry(directLost,operation:"delete"), "delete_contract_unchanged")
expect(V3DirectProfileVerificationPolicy.blocksRetry(["state":"cancelled", "backendSettled":true],operation:"install"), "direct_missing_postmutation_evidence_blocks")
expect(V3DirectProfileVerificationPolicy.stopTerminalPolling(directLost,operation:"refresh"), "settled_lostack_stops_loading")
var directPending = directLost; directPending["backendSettled"] = false
expect(!V3DirectProfileVerificationPolicy.stopTerminalPolling(directPending,operation:"refresh"), "running_backend_keeps_owned_poll")
let directReadbackUnknown: [String:Any] = ["state":"completed","backendSettled":true,"verification":evidence("unknown",store:"unavailable",certificate:"valid")]
expect(V3DirectProfileVerificationPolicy.stopTerminalPolling(directReadbackUnknown,operation:"refresh"), "settled_readback_unknown_finite")
let bookkeepingUnknown: [String:Any] = ["state":"failed", "backendSettled":true, "outcomeUnknown":true, "verification":evidence("extended")]
expect(V3DirectProfileVerificationPolicy.stopTerminalPolling(bookkeepingUnknown,operation:"refresh"), "settled_bookkeeping_unknown_finite")
expect(V3DirectProfileVerificationPolicy.requiresDeviceCheck(bookkeepingUnknown,operation:"refresh"), "bookkeeping_unknown_requires_check")
expect(V3DirectProfileVerificationPolicy.blocksRetry(bookkeepingUnknown,operation:"refresh"), "bookkeeping_unknown_no_replay")
expect(V3DirectProfileVerificationPolicy.stopTerminalPolling(["state":"failed","backendSettled":true,"outcomeUnknown":true,"verification":"malformed"],operation:"install"), "malformed_unknown_finite")
expect(!V3DirectProfileVerificationPolicy.requiresDeviceCheck(["state":"completed","outcomeUnknown":1,"verification":evidence("extended")],operation:"refresh"), "numeric_unknown_not_boolean")
let ticket = V3RefreshUncertaintyTicket(runID: run, updatedAt: 1)
let prior: [String: Any] = ["run_id":run,"state":"failed","updated_at":1.0]
func mayAcknowledge(marker: String? = run, priorRecord: [String: Any] = prior, active: String? = nil, handoff: Bool = false, direct: Bool = false) -> Bool {
    V3RefreshUncertaintyAcknowledgmentPolicy.canAcknowledge(ticket: ticket, marker: marker, record: priorRecord, activeRunID: active, hostHandoffPending: handoff, directClaimPresent: direct)
}
expect(mayAcknowledge(), "exact_prior_usercheck_allowed")
expect(!mayAcknowledge(marker: UUID().uuidString), "wrongrun_usercheck_rejected")
expect(!mayAcknowledge(marker: nil), "double_ack_rejected")
var newer = prior; newer["updated_at"] = 2.0
expect(!mayAcknowledge(priorRecord:newer), "stale_view_rejected")
expect(!mayAcknowledge(active:UUID().uuidString), "concurrent_run_rejected")
expect(!mayAcknowledge(handoff:true), "pending_host_rejected")
expect(!mayAcknowledge(direct:true), "direct_owner_rejected")
expect(!V3RefreshUncertaintyAcknowledgmentPolicy.mayRunAutomatically(manualOnlyAfterAcknowledgment:true), "acknowledgment_never_automatic_retry")
print("REFRESH_TRUTH_RUNTIME_PASS")
