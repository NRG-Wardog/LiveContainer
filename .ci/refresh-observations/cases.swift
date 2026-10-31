let run = "11111111-1111-4111-8111-111111111111"
let other = "22222222-2222-4222-8222-222222222222"
func check(_ value: @autoclosure () -> Bool, _ name: String) { precondition(value(),name);print("PASS " + name) }
let observation: [String:Any] = ["version":1,"readiness":"ready","scope":"ownedBatch"]
func failure(token: String = "missingMainProfile", scope: String = "nonHost", step: CombinedFailure.SourceStep = .refreshApplication, stage: CombinedFailure.Stage = .command, kind: String = "invalidParameters", operation: String = "refresh") -> CombinedFailure {
 CombinedFailure(operation:operation,stage:stage,code:.failed,id:run,sourceStep:step,
 signingContext:["local_precondition":token,"refresh_target_scope":scope,"refresh_failure_kind":kind])
}
check(failure().signingContext["local_precondition"] == "missingMainProfile", "typed_guard_preserved")
check(failure().safeMessage.contains("main app provisioning profile") && CombinedFailure.refreshSelectionPreconditions.allSatisfy { token in let value = failure(token: token); return value.safeMessage == value.message + "\n" + value.diagnosticLabel && !value.safeMessage.contains("no safe underlying cause") }, "specific_safe_guard_copy")
check(failure(token:"SECRET_RAW_MESSAGE").signingContext["local_precondition"] == nil && failure(token:"SECRET_RAW_MESSAGE").safeMessage.contains("no safe underlying cause") && !failure(token:"SECRET_RAW_MESSAGE").safeMessage.contains("SECRET_RAW_MESSAGE"), "unknown_guard_dropped")
check(failure(token:"SECRET_RAW_MESSAGE").signingContext["refresh_target_scope"] == nil, "orphan_scope_dropped")
check(failure(scope:"SECRET_ACCOUNT").signingContext["refresh_target_scope"] == nil && failure(scope:"SECRET_ACCOUNT").code == .failed, "bad_scope_primary_failure_retained")
check(failure(step:.refreshReadiness).signingContext["local_precondition"] == nil && failure(step:.refreshReadiness).safeMessage.contains("no safe underlying cause"), "wrong_source_guard_dropped")
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

func conflictFailure(_ detail: String = "signerMissing", token: String = "preservationAuthorityConflict", kind: String = "invalidParameters", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch, operation: String = "refresh") -> CombinedFailure {
 CombinedFailure(operation: operation, stage: stage, code: .failed, id: run, sourceStep: step,
 signingContext: ["local_precondition": token, "refresh_target_scope": "nonHost", "refresh_failure_kind": kind, "preservation_conflict": detail])
}
let conflict = conflictFailure()
check(conflict.signingContext["preservation_conflict"] == "signerMissing" && conflict.signingContext["refresh_target_scope"] == "nonHost", "conflict_real_fetch_scope_retained")
check(CombinedFailure.decode(conflict.wire, expectedID: run)?.signingContext == conflict.signingContext, "conflict_wire_roundtrip")
check(CombinedFailure.preservationConflictKinds.count == 12 && CombinedFailure.preservationConflictKinds.allSatisfy { conflictFailure($0).signingContext["preservation_conflict"] == $0 }, "conflict_all_finite_tokens_roundtrip")
check(conflictFailure(stage: .command, step: .refreshApplication).signingContext["preservation_conflict"] == "signerMissing", "conflict_refresh_application_scope_retained")
check(conflictFailure(stage: .command).signingContext["preservation_conflict"] == nil && conflictFailure(stage: .command).signingContext["refresh_target_scope"] == nil, "conflict_wrong_stage_dropped")
check(conflictFailure(step: .provisioningProfileRetrieval).signingContext["preservation_conflict"] == nil, "conflict_wrong_step_dropped")
check(conflictFailure(operation: "install").signingContext["preservation_conflict"] == nil, "conflict_wrong_operation_dropped")
check(conflictFailure(kind: "noVPN").signingContext["preservation_conflict"] == nil, "conflict_wrong_kind_dropped")
check(conflictFailure(token: "preservationNotExtended").signingContext["preservation_conflict"] == nil && conflictFailure(token: "preservationNotExtended").signingContext["local_precondition"] == "preservationNotExtended", "conflict_wrong_guard_primary_retained")
check(conflictFailure("SECRET_PROFILE_ACCOUNT").signingContext["preservation_conflict"] == nil && !conflictFailure("SECRET_PROFILE_ACCOUNT").technicalDetails.contains("SECRET_PROFILE_ACCOUNT"), "conflict_unknown_private_text_dropped")
check(conflictFailure("").signingContext["preservation_conflict"] == nil, "conflict_empty_dropped")
var malformedConflict = conflict.wire; var malformedContext = malformedConflict["signingContext"] as! [String: Any]
malformedContext["preservation_conflict"] = ["profile": "SECRET_PROFILE_ACCOUNT"]; malformedConflict["signingContext"] = malformedContext
check(CombinedFailure.decode(malformedConflict, expectedID: run)?.signingContext["local_precondition"] == "preservationAuthorityConflict" && CombinedFailure.decode(malformedConflict, expectedID: run)?.signingContext["preservation_conflict"] == nil, "conflict_malformed_optional_primary_retained")
var conflictManifest = manifest
// Deliberately reverse expected order against lexical result order.
conflictManifest["expected_ids"] = ["private.target.two", "private.target.one"]
conflictManifest["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)], ["bundle_id": "private.target.two", "success": false, "failure": conflict.wire, "verification": proof(false)]]
let conflictRows = V3RefreshTargetDiagnostics.rows(conflictManifest, runID: run)
check(conflictRows[0]["operation"] as? String == "failed" && conflictRows[1]["operation"] as? String == "completed", "conflict_rows_bind_expected_not_sorted_results")
check(conflictRows[0]["scope"] as? String == "nonHost" && conflictRows[0]["guard"] as? String == "preservationAuthorityConflict" && conflictRows[0]["preservationConflict"] as? String == "signerMissing", "conflict_rows_preserve_fetch_diagnosis")
let conflictSummary = ActualSummary.terminalManifestSummary(conflictManifest, runID: run, verified: false)
func conflictCopy(_ summary: [String: Any]) -> String { V3RefreshTargetDiagnostics.copiedDetails(["run_id": run, "state": "failed", "manifest_summary": summary], runID: run) }
check(conflictCopy(conflictSummary).contains("preservation_conflict=signerMissing") && !conflictCopy(conflictSummary).contains("private.target"), "conflict_copy_finite_no_identity_data")
var oldConflictRows = conflictRows; oldConflictRows[0].removeValue(forKey: "preservationConflict"); var oldConflictSummary = conflictSummary; oldConflictSummary["target_diagnostics"] = oldConflictRows
check(!conflictCopy(oldConflictSummary).isEmpty && !conflictCopy(oldConflictSummary).contains("preservation_conflict="), "conflict_old_rows_backward_compatible")
var poisonedConflictRows = conflictRows; poisonedConflictRows[0]["preservationConflict"] = "SECRET_PROFILE_ACCOUNT"; var poisonedConflictSummary = conflictSummary; poisonedConflictSummary["target_diagnostics"] = poisonedConflictRows
check(!conflictCopy(poisonedConflictSummary).isEmpty && !conflictCopy(poisonedConflictSummary).contains("SECRET_PROFILE_ACCOUNT"), "conflict_row_unknown_optional_ignored")
poisonedConflictRows[0]["preservationConflict"] = true; poisonedConflictSummary["target_diagnostics"] = poisonedConflictRows
check(!conflictCopy(poisonedConflictSummary).isEmpty && !conflictCopy(poisonedConflictSummary).contains("preservation_conflict="), "conflict_row_malformed_optional_ignored")
poisonedConflictRows[0]["preservationConflict"] = "signerMissing"; poisonedConflictRows[0]["guard"] = "preservationNotExtended"; poisonedConflictSummary["target_diagnostics"] = poisonedConflictRows
check(!conflictCopy(poisonedConflictSummary).contains("preservation_conflict="), "conflict_row_wrong_guard_ignored")
check(conflictFailure(String(repeating: "SECRET", count: 200)).code == .failed && conflictFailure(String(repeating: "SECRET", count: 200)).signingContext["local_precondition"] == "preservationAuthorityConflict" && !conflictFailure(String(repeating: "SECRET", count: 200)).technicalDetails.contains("SECRET"), "conflict_oversized_optional_primary_retained")
check(failure(token: "unknownTeamType", step: .provisioningProfileFetch, stage: .signing).signingContext["refresh_target_scope"] == nil, "conflict_scope_not_granted_to_other_preparation")
poisonedConflictRows[0]["unrelatedPrivateKey"] = "SECRET_PROFILE_ACCOUNT"; poisonedConflictSummary["target_diagnostics"] = poisonedConflictRows
check(conflictCopy(poisonedConflictSummary).isEmpty, "conflict_unrelated_row_key_rejected")
let fullConflictContext: [String: String] = ["refresh_failure_kind": "invalidParameters", "local_precondition": "preservationAuthorityConflict", "refresh_target_scope": "nonHost",
 "account_binding": "verified", "team_binding": "verified", "session_generation": "1", "capability_count": "1", "app_group_count": "0", "extension_count": "0", "capability_names": "push", "enabled_capability_names": "push",
 "signing_certificate_present": "true", "preferred_parent_id_match": "false", "profile_mode": "team", "auth_diagnostic_state": "recorded",
 "team_sha256": String(repeating: "a", count: 64), "requested_bundle_sha256": String(repeating: "b", count: 64), "requested_app_group_sha256": String(repeating: "c", count: 64), "capabilities_sha256": String(repeating: "d", count: 64), "provisioning_bundle_sha256": String(repeating: "e", count: 64)]
check(fullConflictContext.count == 20 && CombinedFailure.validatedSigningContext(fullConflictContext) == fullConflictContext, "conflict_capacity_baseline_valid")
var extendedConflictContext = fullConflictContext; extendedConflictContext["preservation_conflict"] = "signerMissing"
check(CombinedFailure.validatedSigningContext(extendedConflictContext) == fullConflictContext, "conflict_capacity_preserves_existing_facts")
var extendedConflictWire = conflict.wire; extendedConflictWire["signingContext"] = extendedConflictContext
check(CombinedFailure.decode(extendedConflictWire, expectedID: run)?.signingContext == fullConflictContext, "conflict_wire_capacity_preserves_existing_facts")

func signerSourceFailure(_ source: String? = "verifiedRefreshCache", present: String = "true", hash: String? = String(repeating: "a", count: 64), token: String = "preservationIdentityUnavailable", kind: String = "invalidParameters", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch) -> CombinedFailure {
 var fields = ["local_precondition": token, "refresh_target_scope": "nonHost", "refresh_failure_kind": kind, "signing_certificate_present": present]
 if let source { fields["signing_certificate_source"] = source }
 if let hash { fields["signing_certificate_serial_sha256"] = hash }
 return CombinedFailure(operation: "refresh", stage: stage, code: .failed, id: run, sourceStep: step, signingContext: fields)
}
let sourceVerified = signerSourceFailure()
check(sourceVerified.signingContext["signing_certificate_source"] == "verifiedRefreshCache" && sourceVerified.signingContext["signing_certificate_serial_sha256"] == String(repeating: "a", count: 64), "signer_source_verified_hash_retained")
check(CombinedFailure.decode(sourceVerified.wire, expectedID: run)?.signingContext == sourceVerified.signingContext, "signer_source_wire_roundtrip")
check(signerSourceFailure("unavailable", present: "false", hash: nil).signingContext["signing_certificate_source"] == "unavailable", "signer_source_unavailable_no_claim")
check(signerSourceFailure("unavailable").signingContext["signing_certificate_source"] == nil && signerSourceFailure("unavailable").signingContext["local_precondition"] == "preservationIdentityUnavailable", "signer_source_unavailable_conflicting_claim_dropped")
check(signerSourceFailure(hash: nil).signingContext["signing_certificate_source"] == nil, "signer_source_verified_missing_hash_dropped")
check(signerSourceFailure(present: "false").signingContext["signing_certificate_source"] == nil, "signer_source_verified_false_present_dropped")
check(signerSourceFailure("SECRET_PRIVATE_CERT").signingContext["signing_certificate_source"] == nil && !signerSourceFailure("SECRET_PRIVATE_CERT").technicalDetails.contains("SECRET_PRIVATE_CERT"), "signer_source_private_unknown_dropped")
check(signerSourceFailure(String(repeating: "SECRET", count: 200)).signingContext["local_precondition"] == "preservationIdentityUnavailable", "signer_source_oversized_primary_retained")
check(signerSourceFailure(stage: .command).signingContext["signing_certificate_source"] == nil, "signer_source_wrong_stage_dropped")
check(signerSourceFailure(step: .certificateValidation).signingContext["signing_certificate_source"] == nil, "signer_source_wrong_step_dropped")
check(signerSourceFailure(kind: "noVPN").signingContext["signing_certificate_source"] == nil, "signer_source_wrong_kind_dropped")
check(signerSourceFailure(token: "unknownTeamType").signingContext["signing_certificate_source"] == nil && signerSourceFailure(token: "unknownTeamType").signingContext["local_precondition"] == "unknownTeamType", "signer_source_wrong_guard_primary_retained")
check(signerSourceFailure(stage: .command, step: .refreshApplication).signingContext["signing_certificate_source"] == "verifiedRefreshCache", "signer_source_refresh_application_allowed")
check(signerSourceFailure(nil).signingContext["signing_certificate_serial_sha256"] == String(repeating: "a", count: 64), "signer_source_old_label_absent_retained")
var malformedSourceWire = sourceVerified.wire; var malformedSourceContext = malformedSourceWire["signingContext"] as! [String: Any]; malformedSourceContext["signing_certificate_source"] = ["certificate": "SECRET_PRIVATE_CERT"]; malformedSourceWire["signingContext"] = malformedSourceContext
check(CombinedFailure.decode(malformedSourceWire, expectedID: run)?.signingContext["local_precondition"] == "preservationIdentityUnavailable" && CombinedFailure.decode(malformedSourceWire, expectedID: run)?.signingContext["signing_certificate_source"] == nil, "signer_source_nonstring_primary_retained")
var sourceCapacityContext = fullConflictContext; sourceCapacityContext["signing_certificate_present"] = "false"
var sourceExtendedCapacity = sourceCapacityContext; sourceExtendedCapacity["signing_certificate_source"] = "unavailable"
check(CombinedFailure.validatedSigningContext(sourceExtendedCapacity) == sourceCapacityContext, "signer_source_capacity_preserves_prior_facts")
var bothExtensions = sourceExtendedCapacity; bothExtensions["preservation_conflict"] = "signerMissing"
check(CombinedFailure.validatedSigningContext(bothExtensions) == sourceCapacityContext, "signer_source_and_conflict_capacity_preserve_prior_facts")
