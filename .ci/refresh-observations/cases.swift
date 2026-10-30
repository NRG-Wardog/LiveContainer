let run = "11111111-1111-4111-8111-111111111111"
let other = "22222222-2222-4222-8222-222222222222"
func check(_ value: @autoclosure () -> Bool, _ name: String) { precondition(value(),name);print("PASS " + name) }
let observation: [String:Any] = ["version":1,"readiness":"ready","scope":"ownedBatch"]
func failure(token: String = "missingMainProfile", scope: String = "nonHost", step: CombinedFailure.SourceStep = .refreshApplication, stage: CombinedFailure.Stage = .command, kind: String = "invalidParameters", operation: String = "refresh") -> CombinedFailure {
 CombinedFailure(operation:operation,stage:stage,code:.failed,id:run,sourceStep:step,
 signingContext:["local_precondition":token,"refresh_target_scope":scope,"refresh_failure_kind":kind])
}
check(failure().signingContext["local_precondition"] == "missingMainProfile", "typed_guard_preserved")
check(failure().safeMessage.contains("main app provisioning profile"), "specific_safe_guard_copy")
check(failure(token:"SECRET_RAW_MESSAGE").signingContext["local_precondition"] == nil, "unknown_guard_dropped")
check(failure(token:"SECRET_RAW_MESSAGE").signingContext["refresh_target_scope"] == nil, "orphan_scope_dropped")
check(failure(scope:"SECRET_ACCOUNT").signingContext["refresh_target_scope"] == nil && failure(scope:"SECRET_ACCOUNT").code == .failed, "bad_scope_primary_failure_retained")
check(failure(step:.refreshReadiness).signingContext["local_precondition"] == nil, "wrong_source_guard_dropped")
check(failure(stage:.signing).signingContext["local_precondition"] == nil, "wrong_stage_guard_dropped")
check(failure(kind:"noVPN").signingContext["local_precondition"] == nil, "wrong_kind_guard_dropped")
var nonstring=failure().wire; var context=nonstring["signingContext"] as! [String:Any];context["local_precondition"]=true;context["refresh_target_scope"]=99;nonstring["signingContext"]=context
check(CombinedFailure.decode(nonstring,expectedID:run)?.code == .failed, "malformed_optional_primary_retained")
check(CombinedFailure.decode(nonstring,expectedID:run)?.signingContext["local_precondition"] == nil, "nonstring_guard_dropped")
check(V3RefreshTransportObservation.validated(observation) != nil, "finite_transport_observation")
var wrong=observation;wrong["version"]=true
check(V3RefreshTransportObservation.validated(wrong) == nil, "boolean_version_rejected")
wrong=observation;wrong["peerIP"]="SECRET_IP"
check(V3RefreshTransportObservation.validated(wrong) == nil, "extra_transport_fields_rejected")
wrong=observation;wrong["scope"]="unowned"
check(V3RefreshTransportObservation.validated(wrong) == nil, "unowned_transport_rejected")
func proof(_ ack: Bool) -> [String:Any] { ["version":1,"mutationDispatched":ack,"installAcknowledged":ack,"profileStore":ack ? "matched":"unavailable","renewal":ack ? "unchanged":"unknown","certificate":ack ? "valid":"unknown"] }
var manifest: [String:Any] = ["version":2,"schema":"LiveContainerRefreshManifestV2","run_id":run,"expected_ids":["private.target.one","private.target.two"],"requested_ids":["private.target.one","private.target.two"],"skipped_ids":[String](),"transport_observation":observation,
"results":[["bundle_id":"private.target.one","success":false,"failure":failure().wire,"verification":proof(false)],["bundle_id":"private.target.two","success":true,"verification":proof(true)]]]
let safe=CombinedVerification.sanitized(["liveContainerAutoRefreshVerification":manifest],runID:run)["liveContainerAutoRefreshVerification"] as! [String:Any]
check(V3RefreshTransportObservation.validated(safe["transport_observation"]) != nil, "wire_preserves_owned_observation")
check(CombinedVerification.sanitized(["liveContainerAutoRefreshVerification":manifest],runID:other).isEmpty, "wrong_run_observation_rejected")
let rows=V3RefreshTargetDiagnostics.rows(safe,runID:run)
check(rows.count == 2 && rows[0]["acknowledged"] as? String == "no" && rows[1]["acknowledged"] as? String == "yes", "mixed_target_ack_not_aggregated")
check(rows[0]["guard"] as? String == "missingMainProfile" && rows[0]["scope"] as? String == "nonHost", "target_guard_scope_preserved")
check(!String(describing:rows).contains("private.target"), "target_rows_no_identifiers")
var summary: [String:Any] = ["version":2,"schema":"LiveContainerRefreshManifestSummaryV2","run_id":run,"expected_count":2,"target_diagnostics":rows,"transport_observation":observation]
var record: [String:Any] = ["run_id":run,"state":"failed","started_at":1.0,"manifest_summary":summary,"failure":failure().wire]
let copied=V3RefreshTargetDiagnostics.copiedDetails(record,runID:run)
check(copied.contains("target_1:") && copied.contains("install_acknowledged=no") && copied.contains("target_2:"), "copy_preserves_individual_outcomes")
check(!copied.contains("private.target") && !copied.contains("SECRET"), "copy_no_raw_values")
func observe(_ value: [String:Any], present: Bool = true, active: String? = nil) -> V3SetupConnectionEvidencePolicy.Observation {
 V3SetupConnectionEvidencePolicy.observe(interfacePresent:present,ledger:[run:value],activeRunID:active,hostHandoffPending:false,uncertainMutationRunID:nil)
}
check(observe(record).evidence == .verified, "transport_observed_even_renewal_failed")
check(V3RefreshEvidencePolicy.outcome(safe,runID:run) == .acknowledgedUnverified, "renewal_stays_unverified_independent")
check(observe(record).coreDeviceStep.state != "verified", "no_inferred_coredevice_transport")
check(observe(record,present:false).tunnelStep.state == "actionRequired", "historical_ready_not_current_tunnel")
check(observe(record,active:other).evidence == .checking, "active_generation_suppresses_history")
summary.removeValue(forKey:"transport_observation");record["manifest_summary"]=summary
check(observe(record).evidence == .detected, "no_transport_proof_no_transport_verified")
summary["transport_observation"]=["version":1,"readiness":"ready","scope":"unowned"];record["manifest_summary"]=summary
check(observe(record).evidence == .detected, "malformed_history_no_transport_verified")
summary["transport_observation"]=observation;summary["run_id"]=other;record["manifest_summary"]=summary
check(observe(record).evidence == .detected, "wrong_run_history_no_transport_verified")
summary["run_id"]=run;summary["version"]=2.0;record["manifest_summary"]=summary
check(!V3RefreshTransportObservation.recorded(in:record,runID:run), "floating_summary_version_rejected")
summary["version"]=true;record["manifest_summary"]=summary
check(!V3RefreshTransportObservation.recorded(in:record,runID:run), "boolean_summary_version_rejected")
summary["version"]=2;record["manifest_summary"]=summary;record["state"]="running"
check(!V3RefreshTransportObservation.recorded(in:record,runID:run), "nonterminal_observation_not_promoted")
record["state"]="failed"
check(V3RefreshEvidencePolicy.failurePresentation(safe,runID:run,stage:"command",code:"failed") == nil, "mixed_aggregate_does_not_hide_target_guard")
check(failure().safeMessage.contains("main app provisioning profile") && !failure().safeMessage.contains("Enable LocalDevVPN"), "selection_guard_not_vpn_advice")
var taintedRows=rows;taintedRows[0]["scope"]="SECRET_ACCOUNT";summary["target_diagnostics"]=taintedRows;record["manifest_summary"]=summary
check(V3RefreshTargetDiagnostics.copiedDetails(record,runID:run).isEmpty, "stored_diagnostics_reject_raw_values")
let renewalOnly: [String:Any] = ["version":2,"schema":"LiveContainerRefreshManifestSummaryV2","run_id":run,"verified":true,"expected_count":1,"result_count":1,"failed_count":0,"skipped_count":0,"requested_count":1,"evidence_version":1,"renewal_outcome":"renewed","renewed_count":1,"acknowledged_count":1]
let renewedRecord: [String:Any] = ["run_id":run,"state":"completed","started_at":1.0,"terminal_intent":"verified","health":"REFRESH_SUCCEEDED","manifest_run_id":run,"manifest_summary":renewalOnly]
check(observe(renewedRecord).evidence == .detected, "renewal_verified_without_transport_observation_not_inferred")
summary["version"]=NSNumber(value:UInt64.max);record["manifest_summary"]=summary
check(!V3RefreshTransportObservation.recorded(in:record,runID:run), "overflow_summary_version_rejected")
let lowerRun="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
summary["version"]=2;summary["run_id"]=lowerRun;record["run_id"]=lowerRun;record["manifest_summary"]=summary
check(!V3RefreshTransportObservation.recorded(in:record,runID:lowerRun), "noncanonical_run_rejected")
let actualSummary=ActualSummary.terminalManifestSummary(safe,runID:run,verified:false)
check(V3RefreshTransportObservation.validated(actualSummary["transport_observation"]) != nil, "actual_summary_preserves_complete_observation")
var partial=safe;partial["results"]=(safe["results"] as! [[String:Any]]).prefix(1).map { $0 }
let partialSummary=ActualSummary.terminalManifestSummary(partial,runID:run,verified:false)
check(partialSummary["transport_observation"] == nil, "actual_summary_rejects_partial_observation")
check((partialSummary["target_diagnostics"] as? [[String:Any]])?.isEmpty == true, "partial_manifest_no_target_rows")
var many=safe;let manyIDs=(0..<33).map { "target.\($0)" };many["expected_ids"]=manyIDs;many["requested_ids"]=manyIDs
many["results"]=manyIDs.map { ["bundle_id":$0,"success":true,"verification":proof(true)] as [String:Any] }
let manySummary=ActualSummary.terminalManifestSummary(many,runID:run,verified:false)
let manyRecord: [String:Any]=["run_id":run,"state":"failed","manifest_summary":manySummary]
check((manySummary["target_diagnostics"] as! [[String:Any]]).count == 32, "target_diagnostics_bounded_32")
check(V3RefreshTargetDiagnostics.copiedDetails(manyRecord,runID:run).contains("target_diagnostics_truncated=yes"), "target_33_truncation_explicit")
var unknownRows=rows;unknownRows[0]["failureKind"]="SECRET_UNKNOWN_KIND"
var unknownSummary=actualSummary;unknownSummary["target_diagnostics"]=unknownRows
check(V3RefreshTargetDiagnostics.copiedDetails(["run_id":run,"state":"failed","manifest_summary":unknownSummary],runID:run).isEmpty, "unknown_failure_kind_rejected")
var wrongVersionSummary=actualSummary;wrongVersionSummary["version"]=2.0
check(V3RefreshTargetDiagnostics.copiedDetails(["run_id":run,"state":"failed","manifest_summary":wrongVersionSummary],runID:run).isEmpty, "target_summary_float_version_rejected")
check(V3RefreshTargetDiagnostics.copiedDetails(["run_id":run,"state":"running","manifest_summary":actualSummary],runID:run).isEmpty, "nonterminal_target_summary_rejected")
check(failure(operation:"install").signingContext["local_precondition"] == nil, "wrong_operation_guard_dropped")
print("REFRESH_OBSERVATIONS_PASS")
