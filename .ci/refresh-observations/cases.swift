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
check(CombinedFailure.preservationConflictKinds.count == 17 && CombinedFailure.preservationConflictKinds.allSatisfy { conflictFailure($0).signingContext["preservation_conflict"] == $0 }, "conflict_all_finite_tokens_roundtrip")
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

// Finite semantic-alternative failures remain distinct across wire and per-target copy.
func semanticConflictRoundtrip(_ token: String) -> Bool {
 let failure = conflictFailure(token)
 guard let decoded = CombinedFailure.decode(failure.wire, expectedID: run),
       decoded.signingContext["preservation_conflict"] == token,
       decoded.technicalDetails.contains("preservation_conflict=" + token) else { return false }
 var sample = conflictManifest
 sample["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)],
                       ["bundle_id": "private.target.two", "success": false, "failure": decoded.wire, "verification": proof(false)]]
 let summary = ActualSummary.terminalManifestSummary(sample, runID: run, verified: false)
 let copy = conflictCopy(summary)
 return copy.contains("preservation_conflict=" + token) && !copy.contains("private.target") &&
        !copy.contains("BEGIN CERTIFICATE") && !copy.contains("DER-Encoded-Profile")
}
check(semanticConflictRoundtrip("embeddedDERUnsupportedSigner"), "semantic_unsupported_signer_distinct")
check(semanticConflictRoundtrip("embeddedDERSignerTimeInvalid"), "semantic_signer_time_distinct")
check(semanticConflictRoundtrip("embeddedDERVerificationFailed"), "semantic_crypto_failure_distinct")
check(semanticConflictRoundtrip("embeddedDERUnsupportedRepresentation"), "semantic_unsupported_representation_distinct")
check(semanticConflictRoundtrip("embeddedDERBindingMismatch"), "semantic_binding_mismatch_distinct")

// Diagnostic-only unknown inner CMS signer. Never changes the preservation refusal.
let cmsKey = V3CMSSignerDiagnostic.contextKey
let cmsHash = String(repeating: "f", count: 64)
let cmsVerified = "cs1|installed|passed|passed|passed|passed|failed|1110|" + cmsHash
let cmsUnchecked = "cs1|candidate|unchecked|unchecked|unchecked|unchecked|failed|unchecked|unknown"
func cmsFailure(_ raw: String = cmsVerified, operation: String = "refresh", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch, cause: CombinedFailure.SafeCause? = nil, conflict: String = "embeddedDERUnsupportedSigner") -> CombinedFailure {
 CombinedFailure(operation: operation, stage: stage, code: .failed, id: run, safeCause: cause, sourceStep: step,
 signingContext: ["local_precondition": "preservationAuthorityConflict", "refresh_target_scope": "nonHost", "refresh_failure_kind": "invalidParameters", "preservation_conflict": conflict, cmsKey: raw])
}
let cms = cmsFailure()
check(cms.signingContext[cmsKey] == cmsVerified && cms.code == .failed, "cms_diagnostic_never_accepts_unknown_signer")
check(CombinedFailure.decode(cms.wire, expectedID: run)?.signingContext == cms.signingContext, "cms_wire_roundtrip")
check(CombinedFailure.fromEncodedString(cms.encodedString, expectedID: run)?.signingContext == cms.signingContext, "cms_binary_plist_roundtrip")
check(cms.technicalDetails.contains("cms_signer_signature=passed") && cms.technicalDetails.contains("cms_signer_sha256=" + cmsHash) && !cms.technicalDetails.contains("cs1|"), "cms_copy_explicit_labels_not_opaque_value")
check(cms.technicalDetails.contains("cms_signer_leaf_name_observed=yes") && cms.technicalDetails.contains("cms_signer_app_developer_marker_observed=no") && cms.technicalDetails.contains("cms_signer_diagnostic_only=yes"), "cms_roles_are_observations_not_authority")
check(cmsFailure(cmsUnchecked).technicalDetails.contains("cms_signer_signature=unchecked") && !cmsFailure(cmsUnchecked).technicalDetails.contains("cms_signer_signature=failed"), "cms_pin_miss_never_implies_invalid_signature")
check(cmsFailure(operation: "install").signingContext[cmsKey] == nil, "cms_wrong_operation_dropped")
check(cmsFailure(stage: .command).signingContext[cmsKey] == nil, "cms_wrong_stage_dropped")
check(cmsFailure(step: .certificateValidation).signingContext[cmsKey] == nil, "cms_wrong_step_dropped")
check(cmsFailure(stage: .command, step: .refreshApplication).signingContext[cmsKey] == cmsVerified, "cms_refresh_application_scope_allowed")
check(cmsFailure(cause: .certificateUnavailable).signingContext[cmsKey] == nil, "cms_wrong_safe_cause_dropped")
check(cmsFailure(conflict: "embeddedDERVerificationFailed").signingContext[cmsKey] == nil, "cms_wrong_conflict_dropped")
check(cmsFailure("SECRET_PROFILE_CERT_CN_OID").signingContext[cmsKey] == nil && !cmsFailure("SECRET_PROFILE_CERT_CN_OID").technicalDetails.contains("SECRET"), "cms_opaque_private_metadata_dropped")
check(cmsFailure(String(repeating: "SECRET", count: 200)).signingContext["preservation_conflict"] == "embeddedDERUnsupportedSigner" && cmsFailure(String(repeating: "SECRET", count: 200)).signingContext[cmsKey] == nil, "cms_oversize_primary_retained")
check(V3CMSSignerDiagnostic(encoded: cmsVerified + "|SECRET") == nil, "cms_extra_slot_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "cs1|", with: "cs2|")) == nil, "cms_unknown_schema_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "installed|", with: "unknown|")) == nil, "cms_unknown_input_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "|failed|", with: "|passed|")) == nil, "cms_not_pin_miss_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "1110", with: "true")) == nil, "cms_nonbit_roles_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "1110", with: "11100")) == nil, "cms_overlong_roles_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: cmsHash, with: cmsHash.uppercased())) == nil, "cms_noncanonical_hash_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: cmsHash, with: "unknown")) != nil, "cms_verified_hash_unavailable_allowed")
check(V3CMSSignerDiagnostic(encoded: cmsUnchecked.replacingOccurrences(of: "|unknown", with: "|" + cmsHash)) == nil, "cms_unverified_hash_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsUnchecked.replacingOccurrences(of: "|unchecked|unknown", with: "|1110|unknown")) == nil, "cms_unverified_roles_rejected")
check(["installed", "candidate", "freshInstalled", "freshCandidate"].allSatisfy { V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "installed", with: $0)) != nil }, "cms_all_finite_inputs")
var cmsDense = fullConflictContext; cmsDense.removeValue(forKey: "capabilities_sha256"); cmsDense["preservation_conflict"] = "embeddedDERUnsupportedSigner"
check(cmsDense.count == 20 && CombinedFailure.validatedSigningContext(cmsDense) == cmsDense, "cms_capacity_baseline_twenty")
var cmsOverflow = cmsDense; cmsOverflow[cmsKey] = cmsVerified
check(CombinedFailure.validatedSigningContext(cmsOverflow) == cmsDense, "cms_capacity_preserves_twenty_prior_facts")
var cmsMalformedWire = cms.wire; var cmsMalformedContext = cms.signingContext as [String: Any]; cmsMalformedContext[cmsKey] = ["CN": "SECRET_CERTIFICATE"]
cmsMalformedWire["signingContext"] = cmsMalformedContext
check(CombinedFailure.decode(cmsMalformedWire, expectedID: run)?.signingContext[cmsKey] == nil && CombinedFailure.decode(cmsMalformedWire, expectedID: run)?.signingContext["preservation_conflict"] == "embeddedDERUnsupportedSigner", "cms_wrong_type_primary_retained")
cmsMalformedWire["signingContext"] = cmsOverflow
check(CombinedFailure.decode(cmsMalformedWire, expectedID: run)?.signingContext == cmsDense, "cms_wire_overflow_preserves_prior_facts")
var cmsManifest = conflictManifest
cmsManifest["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)], ["bundle_id": "private.target.two", "success": false, "failure": cms.wire, "verification": proof(false)]]
let cmsSummary = ActualSummary.terminalManifestSummary(cmsManifest, runID: run, verified: false)
let cmsCopy = conflictCopy(cmsSummary)
check(cmsCopy.contains("cms_signer_sha256=" + cmsHash) && cmsCopy.contains("cms_signer_signature=passed") && !cmsCopy.contains("private.target"), "cms_per_target_summary_copy_roundtrip")
var cmsRows = V3RefreshTargetDiagnostics.rows(cmsManifest, runID: run)
check(cmsRows[0]["cmsSignerDiagnostic"] as? String == cmsVerified && cmsRows[1]["cmsSignerDiagnostic"] == nil, "cms_per_target_not_global")
var cmsPoisonedSummary = cmsSummary; cmsRows[0]["cmsSignerDiagnostic"] = ["CN": "SECRET_CERTIFICATE"]; cmsPoisonedSummary["target_diagnostics"] = cmsRows
check(!conflictCopy(cmsPoisonedSummary).contains("SECRET") && !conflictCopy(cmsPoisonedSummary).contains("cms_signer_"), "cms_summary_wrong_type_dropped")
cmsRows[0]["cmsSignerDiagnostic"] = cmsVerified; cmsRows[0]["preservationConflict"] = "embeddedDERVerificationFailed"; cmsPoisonedSummary["target_diagnostics"] = cmsRows
check(!conflictCopy(cmsPoisonedSummary).contains("cms_signer_"), "cms_summary_wrong_conflict_dropped")
check(!cmsCopy.contains("BEGIN CERTIFICATE") && !cmsCopy.contains("DER-Encoded-Profile") && !cmsCopy.contains("signing_certificate_serial_sha256"), "cms_copy_no_certificate_content_or_cached_signer_conflation")

check(V3CMSSignerDiagnostic(encoded: cmsVerified + "\n") == nil, "cms_hash_trailing_newline_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "|passed|", with: "|trusted|")) == nil, "cms_unknown_check_state_rejected")
check(V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "1110", with: "unchecked")) == nil, "cms_verified_roles_required")
check((0..<16).allSatisfy { number in let bits = (0..<4).map { (number & (1 << $0)) == 0 ? "0" : "1" }.joined(); return V3CMSSignerDiagnostic(encoded: cmsVerified.replacingOccurrences(of: "1110", with: bits)) != nil }, "cms_all_sixteen_observation_masks")
var cmsWrongKind = cms.signingContext; cmsWrongKind["refresh_failure_kind"] = "noVPN"
check(CombinedFailure.validatedSigningContext(cmsWrongKind)?[cmsKey] == nil, "cms_wrong_failure_kind_dropped")
var cmsWrongGuard = cms.signingContext; cmsWrongGuard["local_precondition"] = "preservationNotExtended"
check(CombinedFailure.validatedSigningContext(cmsWrongGuard)?[cmsKey] == nil, "cms_wrong_guard_dropped")
var cmsWrongCode = cms.wire; cmsWrongCode["code"] = "cancelled"
check(CombinedFailure.decode(cmsWrongCode, expectedID: run)?.signingContext[cmsKey] == nil, "cms_wrong_code_dropped")
var cmsHost = cms.signingContext; cmsHost["refresh_target_scope"] = "host"
check(CombinedFailure.validatedSigningContext(cmsHost)?[cmsKey] == nil, "cms_wrong_host_scope_dropped")
cmsHost.removeValue(forKey: "refresh_target_scope")
check(CombinedFailure.validatedSigningContext(cmsHost)?[cmsKey] == nil, "cms_missing_scope_dropped")
cmsRows = V3RefreshTargetDiagnostics.rows(cmsManifest, runID: run); cmsRows[0]["scope"] = "host"; cmsPoisonedSummary["target_diagnostics"] = cmsRows
check(!conflictCopy(cmsPoisonedSummary).contains("cms_signer_"), "cms_summary_wrong_host_scope_dropped")
cmsRows[0]["scope"] = "nonHost"; cmsRows[0]["dispatched"] = "yes"; cmsPoisonedSummary["target_diagnostics"] = cmsRows
check(!conflictCopy(cmsPoisonedSummary).contains("cms_signer_"), "cms_summary_mutated_target_dropped")
cmsRows[0]["dispatched"] = "unknown"; cmsPoisonedSummary["target_diagnostics"] = cmsRows
check(!conflictCopy(cmsPoisonedSummary).contains("cms_signer_"), "cms_summary_unknown_mutation_dropped")
let cmsProducer = V3RefreshSelectionFailure(reason: .preservationAuthorityConflict, scope: .nonHost, preservationConflict: "embeddedDERUnsupportedSigner", cmsSignerDiagnostic: cmsVerified)
let cmsProducedFailure = CombinedFailure(operation: "refresh", stage: .signing, code: .failed, id: run, sourceStep: .provisioningProfileFetch, signingContext: cmsProducer.facts)
check(CombinedFailure.decode(cmsProducedFailure.wire, expectedID: run)?.signingContext[cmsKey] == cmsVerified, "cms_actual_producer_to_wire_handoff")
check([cmsVerified, cmsUnchecked, "SECRET", cmsVerified + "\n", cmsVerified + "|SECRET", cmsVerified.replacingOccurrences(of: "1110", with: "unchecked")].allSatisfy { V3RefreshSelectionFailure.validCMSSignerDiagnostic($0) == (V3CMSSignerDiagnostic(encoded: $0) != nil) }, "cms_producer_wire_validator_parity")
check(V3RefreshSelectionFailure(reason: .preservationAuthorityConflict, scope: .host, preservationConflict: "embeddedDERUnsupportedSigner", cmsSignerDiagnostic: cmsVerified).facts[cmsKey] == nil, "cms_producer_host_drops_diagnostic")

// Production-shaped c89d975a regression: the real signing NSError wrapper adds
// unknownSigningCause. Direct CombinedFailure(... safeCause: nil) hid this loss.
var cmsBridgeFacts = cmsProducer.facts
cmsBridgeFacts.merge(["extension_count": "5", "signing_certificate_present": "true",
                     "signing_certificate_serial_sha256": String(repeating: "a", count: 64),
                     "signing_certificate_source": "verifiedRefreshCache"]) { _, observed in observed }
check(cmsBridgeFacts.count == 9, "cms_bridge_realistic_eight_prior_fields_plus_diagnostic")
let cmsMarked = lcStructuredSigningFailure(cmsProducer, stage: "signing", sourceStep: "provisioningProfileFetch", facts: cmsBridgeFacts)
check(cmsMarked.userInfo["LCStructuredFailureCauseV1"] as? String == "unknownSigningCause", "cms_bridge_actual_wrapper_unknown_cause")
let cmsCaptured = CombinedFailure.capture(cmsMarked, operation: "refresh", stage: .refreshVerification, id: run)
check(cmsCaptured.safeCause == .unknownSigningCause && cmsCaptured.signingContext == cmsBridgeFacts, "cms_bridge_capture_keeps_all_nine_fields")
let cmsBridgeData = try! PropertyListSerialization.data(fromPropertyList: cmsCaptured.wire, format: .binary, options: 0)
let cmsBridgePlist = try! PropertyListSerialization.propertyList(from: cmsBridgeData, format: nil) as! [String: Any]
let cmsRestored = CombinedFailure.decode(cmsBridgePlist, expectedID: run)!
check(cmsBridgeData.count <= 4096 && cmsRestored.signingContext == cmsBridgeFacts, "cms_bridge_binary_roundtrip_within_cap")
check(cmsRestored.stage == .signing && cmsRestored.sourceStep == .provisioningProfileFetch && cmsRestored.code == .failed && cmsRestored.safeCause == .unknownSigningCause, "cms_bridge_primary_failure_unchanged")
var cmsBridgeManifest = cmsManifest
cmsBridgeManifest["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)], ["bundle_id": "private.target.two", "success": false, "failure": cmsRestored.wire, "verification": proof(false)]]
let cmsBridgeSanitized = CombinedVerification.sanitized(["liveContainerAutoRefreshVerification": cmsBridgeManifest], runID: run)["liveContainerAutoRefreshVerification"] as! [String: Any]
let cmsBridgeSummary = ActualSummary.terminalManifestSummary(cmsBridgeSanitized, runID: run, verified: false)
let cmsBridgeRecord: [String: Any] = ["request_id": other, "run_id": run, "state": "failed", "failure": cmsRestored.wire, "manifest_summary": cmsBridgeSummary]
let cmsWholeLog = V3RefreshAllFailureDiagnostics.text(requestID: other, runID: run, record: cmsBridgeRecord)!
check(cmsWholeLog.components(separatedBy: "cms_signer_signature=passed").count == 3 && cmsWholeLog.components(separatedBy: "cms_signer_sha256=" + cmsHash).count == 3, "cms_bridge_whole_log_top_and_target_diagnostic")
check(cmsWholeLog.contains("target_1: scope=nonHost operation_status=failed") && cmsWholeLog.contains("mutation_dispatched=no") && cmsWholeLog.contains("target_2: scope=unknown operation_status=completed") && cmsWholeLog.contains("mutation_dispatched=yes"), "cms_bridge_mixed_target_batch_preserved")
check(cmsWholeLog.contains("extension_count=5") && cmsWholeLog.contains("signing_certificate_source=verifiedRefreshCache") && cmsWholeLog.contains("signing_certificate_serial_sha256=" + String(repeating: "a", count: 64)), "cms_bridge_existing_cache_facts_preserved")
check(!cmsWholeLog.contains("BEGIN CERTIFICATE") && !cmsWholeLog.contains("SECRET") && !cmsWholeLog.contains("cs1|"), "cms_bridge_whole_log_privacy")
check(cmsFailure(cause: .unknownSigningCause).signingContext[cmsKey] == cmsVerified && cmsFailure(cause: .certificateUnavailable).signingContext[cmsKey] == nil, "cms_unknown_cause_only_exception_concrete_cause_still_rejected")

check(!cmsWholeLog.components(separatedBy: "\n").first(where: { $0.hasPrefix("target_2:") })!.contains("cms_signer_"), "cms_bridge_completed_host_does_not_inherit_diagnostic")
let cmsUnverifiedDiagnostic = "cs1|installed|passed|failed|unchecked|unchecked|failed|unchecked|unknown"
let cmsUnverifiedProducer = V3RefreshSelectionFailure(reason: .preservationAuthorityConflict, scope: .nonHost, preservationConflict: "embeddedDERUnsupportedSigner", cmsSignerDiagnostic: cmsUnverifiedDiagnostic)
var cmsUnverifiedFacts = cmsBridgeFacts; cmsUnverifiedFacts[cmsKey] = cmsUnverifiedProducer.facts[cmsKey]
let cmsUnverifiedMarked = lcStructuredSigningFailure(cmsUnverifiedProducer, stage: "signing", sourceStep: "provisioningProfileFetch", facts: cmsUnverifiedFacts)
let cmsUnverifiedCaptured = CombinedFailure.capture(cmsUnverifiedMarked, operation: "refresh", stage: .refreshVerification, id: run)
let cmsUnverifiedData = try! PropertyListSerialization.data(fromPropertyList: cmsUnverifiedCaptured.wire, format: .binary, options: 0)
let cmsUnverifiedPlist = try! PropertyListSerialization.propertyList(from: cmsUnverifiedData, format: nil) as! [String: Any]
let cmsUnverifiedRestored = CombinedFailure.decode(cmsUnverifiedPlist, expectedID: run)!
check(cmsUnverifiedRestored.safeCause == .unknownSigningCause && cmsUnverifiedRestored.signingContext == cmsUnverifiedFacts, "cms_bridge_unverified_finite_observation_roundtrip")
var cmsUnverifiedManifest = cmsBridgeManifest
cmsUnverifiedManifest["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)], ["bundle_id": "private.target.two", "success": false, "failure": cmsUnverifiedRestored.wire, "verification": proof(false)]]
let cmsUnverifiedSanitized = CombinedVerification.sanitized(["liveContainerAutoRefreshVerification": cmsUnverifiedManifest], runID: run)["liveContainerAutoRefreshVerification"] as! [String: Any]
let cmsUnverifiedSummary = ActualSummary.terminalManifestSummary(cmsUnverifiedSanitized, runID: run, verified: false)
let cmsUnverifiedRecord: [String: Any] = ["request_id": other, "run_id": run, "state": "failed", "failure": cmsUnverifiedRestored.wire, "manifest_summary": cmsUnverifiedSummary]
let cmsUnverifiedLog = V3RefreshAllFailureDiagnostics.text(requestID: other, runID: run, record: cmsUnverifiedRecord)!
check(cmsUnverifiedLog.components(separatedBy: "cms_signer_chain=failed").count == 3 && cmsUnverifiedLog.components(separatedBy: "cms_signer_signature=unchecked").count == 3, "cms_bridge_unverified_whole_log_top_and_target")
check(cmsUnverifiedLog.components(separatedBy: "cms_signer_sha256=unknown").count == 3 && !cmsUnverifiedLog.contains(cmsHash) && !cmsUnverifiedLog.contains("cms_signer_leaf_name_observed=yes"), "cms_bridge_unverified_never_gains_fingerprint_or_role")
check(!cmsUnverifiedLog.components(separatedBy: "\n").first(where: { $0.hasPrefix("target_2:") })!.contains("cms_signer_"), "cms_bridge_unverified_does_not_inherit_to_completed_host")
check(cmsFailure(cause: .signingNetworkTimedOut).signingContext[cmsKey] == nil, "cms_bridge_specific_transport_cause_still_rejected")

var cmsUnknownWrongOperation = cmsRestored.wire; cmsUnknownWrongOperation["operation"] = "install"
check(CombinedFailure.decode(cmsUnknownWrongOperation, expectedID: run)?.signingContext[cmsKey] == nil, "cms_unknown_cause_wrong_operation_still_rejected")
var cmsUnknownHostContext = cmsRestored.signingContext; cmsUnknownHostContext["refresh_target_scope"] = "host"
var cmsUnknownHostWire = cmsRestored.wire; cmsUnknownHostWire["signingContext"] = cmsUnknownHostContext
check(CombinedFailure.decode(cmsUnknownHostWire, expectedID: run)?.signingContext[cmsKey] == nil, "cms_unknown_cause_wrong_host_still_rejected")
var cmsUnknownWrongStep = cmsRestored.wire; cmsUnknownWrongStep["sourceStep"] = "certificateValidation"
check(CombinedFailure.decode(cmsUnknownWrongStep, expectedID: run)?.signingContext[cmsKey] == nil, "cms_unknown_cause_wrong_step_still_rejected")

// Apple-origin read failures are finite diagnostics, not CMS trust decisions.
let originKey = "apple_profile_origin"
let originKinds = ["requestUnavailable", "recordNotFound", "ambiguousRecord", "responseMismatch", "invalidResponse", "responseTooLarge", "operationCancelled", "operationExpired", "ownershipChanged"]
func originFailure(_ value: String = "recordNotFound", operation: String = "refresh", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch, cause: CombinedFailure.SafeCause? = .unknownSigningCause, scope: String = "nonHost", token: String = "preservationEvidenceUnavailable", kind: String = "invalidParameters") -> CombinedFailure {
 CombinedFailure(operation: operation, stage: stage, code: .failed, id: run, safeCause: cause, sourceStep: step,
 signingContext: ["local_precondition": token, "refresh_target_scope": scope, "refresh_failure_kind": kind, originKey: value])
}
check(CombinedFailure.appleProfileOriginKinds == Set(originKinds), "origin_exact_finite_vocabulary")
check(originFailure().signingContext[originKey] == "recordNotFound" && originFailure().code == .failed, "origin_diagnostic_does_not_authorize_refresh")
check(CombinedFailure.fromEncodedString(originFailure().encodedString, expectedID: run)?.signingContext == originFailure().signingContext, "origin_binary_roundtrip")
check(originFailure(stage: .command, step: .refreshApplication).signingContext[originKey] == "recordNotFound", "origin_refresh_application_scope")
check(originFailure(operation: "install").signingContext[originKey] == nil, "origin_wrong_operation_dropped")
check(originFailure(stage: .command).signingContext[originKey] == nil, "origin_wrong_stage_dropped")
check(originFailure(step: .certificateValidation).signingContext[originKey] == nil, "origin_wrong_step_dropped")
check(originFailure(scope: "host").signingContext[originKey] == nil && originFailure(scope: "unknown").signingContext[originKey] == nil, "origin_wrong_scope_dropped")
check(originFailure(token: "preservationAuthorityConflict").signingContext[originKey] == nil, "origin_wrong_guard_dropped")
check(originFailure(kind: "noVPN").signingContext[originKey] == nil, "origin_wrong_kind_dropped")
check(originFailure(cause: .certificateUnavailable).signingContext[originKey] == nil && originFailure(cause: nil).signingContext[originKey] != nil, "origin_specific_cause_rejected_placeholder_allowed")
check(originFailure("SECRET_ACCOUNT_PROFILE_UUID").signingContext[originKey] == nil && !originFailure("SECRET_ACCOUNT_PROFILE_UUID").technicalDetails.contains("SECRET"), "origin_opaque_value_stripped")
check(originFailure(String(repeating: "x", count: 33)).signingContext[originKey] == nil && originFailure(String(repeating: "x", count: 33)).signingContext["local_precondition"] == "preservationEvidenceUnavailable", "origin_oversize_primary_retained")
var originWrongType = originFailure().wire; var originTypedContext = originFailure().signingContext as [String: Any]; originTypedContext[originKey] = ["profile": "SECRET"]
originWrongType["signingContext"] = originTypedContext
check(CombinedFailure.decode(originWrongType, expectedID: run)?.signingContext[originKey] == nil && CombinedFailure.decode(originWrongType, expectedID: run)?.signingContext["local_precondition"] == "preservationEvidenceUnavailable", "origin_wrong_type_primary_retained")
var originMissingScope = originFailure().signingContext; originMissingScope.removeValue(forKey: "refresh_target_scope")
check(CombinedFailure.validatedSigningContext(originMissingScope)?[originKey] == nil, "origin_missing_scope_dropped")
var originDense = fullConflictContext; originDense["local_precondition"] = "preservationEvidenceUnavailable"
var originOverCapacity = originDense; originOverCapacity[originKey] = "recordNotFound"
check(originDense.count == 20 && CombinedFailure.validatedSigningContext(originOverCapacity) == originDense, "origin_capacity_prior_twenty_facts_preserved")
var originOverflowWire = originFailure().wire; originOverflowWire["signingContext"] = originOverCapacity
check(CombinedFailure.decode(originOverflowWire, expectedID: run)?.signingContext == originDense, "origin_wire_capacity_preserved")
var originWrongCode = originFailure().wire; originWrongCode["code"] = "cancelled"
check(CombinedFailure.decode(originWrongCode, expectedID: run)?.signingContext[originKey] == nil, "origin_wrong_code_dropped")

func actualOriginLog(_ kind: String) -> (CombinedFailure, String, [String: Any]) {
 let producer = V3RefreshSelectionFailure(reason: .preservationEvidenceUnavailable, scope: .nonHost, appleProfileOrigin: kind)
 var facts = producer.facts
 facts.merge(["extension_count": "5", "signing_certificate_present": "true", "signing_certificate_serial_sha256": String(repeating: "a", count: 64), "signing_certificate_source": "verifiedRefreshCache"]) { _, observed in observed }
 let marked = lcStructuredSigningFailure(producer, stage: "signing", sourceStep: "provisioningProfileFetch", facts: facts)
 precondition(marked.userInfo["LCStructuredFailureCauseV1"] as? String == "unknownSigningCause")
 let captured = CombinedFailure.capture(marked, operation: "refresh", stage: .refreshVerification, id: run)
 let data = try! PropertyListSerialization.data(fromPropertyList: captured.wire, format: .binary, options: 0)
 precondition(data.count <= 4096)
 let decoded = try! PropertyListSerialization.propertyList(from: data, format: nil) as! [String: Any]
 let restored = CombinedFailure.decode(decoded, expectedID: run)!
 precondition(restored.signingContext == facts && restored.safeCause == .unknownSigningCause && restored.code == .failed)
 var batch = cmsManifest
 batch["results"] = [["bundle_id": "private.target.one", "success": true, "verification": proof(true)], ["bundle_id": "private.target.two", "success": false, "failure": restored.wire, "verification": proof(false)]]
 let sanitized = CombinedVerification.sanitized(["liveContainerAutoRefreshVerification": batch], runID: run)["liveContainerAutoRefreshVerification"] as! [String: Any]
 let summary = ActualSummary.terminalManifestSummary(sanitized, runID: run, verified: false)
 let record: [String: Any] = ["request_id": other, "run_id": run, "state": "failed", "failure": restored.wire, "manifest_summary": summary]
 return (restored, V3RefreshAllFailureDiagnostics.text(requestID: other, runID: run, record: record)!, summary)
}
check(originKinds.allSatisfy { kind in let (_,log,_) = actualOriginLog(kind); return log.components(separatedBy: "apple_profile_origin=" + kind).count == 3 && !log.contains("cms_signer_signature=") && !log.contains("SECRET") }, "origin_all_nine_actual_producer_wrapper_manifest_whole_log")
let (originRestored,originWholeLog,originSummary) = actualOriginLog("recordNotFound")
check(originWholeLog.contains("extension_count=5") && originWholeLog.contains("signing_certificate_source=verifiedRefreshCache") && originRestored.stage == .signing && originRestored.sourceStep == .provisioningProfileFetch, "origin_existing_failure_and_cache_facts_preserved")
check(!originWholeLog.components(separatedBy: "\n").first(where: { $0.hasPrefix("target_2:") })!.contains("apple_profile_origin="), "origin_completed_host_never_inherits_nonhost_failure")
var originRows = originSummary["target_diagnostics"] as! [[String: Any]]
var originPoisonedSummary = originSummary; originRows[0]["appleProfileOrigin"] = ["account": "SECRET"]; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("apple_profile_origin=") && !conflictCopy(originPoisonedSummary).contains("SECRET"), "origin_target_wrong_type_ignored")
originRows[0]["appleProfileOrigin"] = "SECRET"; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("SECRET"), "origin_target_unknown_value_ignored")
originRows[0]["appleProfileOrigin"] = "recordNotFound"; originRows[0]["dispatched"] = "yes"; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("apple_profile_origin="), "origin_target_mutation_dispatched_ignored")
originRows[0]["dispatched"] = "unknown"; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("apple_profile_origin="), "origin_target_unknown_mutation_ignored")
originRows[0]["dispatched"] = "no"; originRows[0]["scope"] = "host"; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("apple_profile_origin="), "origin_target_wrong_scope_ignored")
originRows[0]["scope"] = "nonHost"; originRows[0]["guard"] = "preservationAuthorityConflict"; originPoisonedSummary["target_diagnostics"] = originRows
check(!conflictCopy(originPoisonedSummary).contains("apple_profile_origin="), "origin_target_wrong_guard_ignored")
