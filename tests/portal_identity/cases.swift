let run = "11111111-1111-4111-8111-111111111111"
func check(_ ok: @autoclosure () -> Bool, _ name: String) { precondition(ok(), name); print("PASS " + name) }
let fullConflictContext: [String: String] = ["refresh_failure_kind": "invalidParameters", "local_precondition": "preservationAuthorityConflict", "refresh_target_scope": "nonHost",
 "account_binding": "verified", "team_binding": "verified", "session_generation": "1", "capability_count": "1", "app_group_count": "0", "extension_count": "0", "capability_names": "push", "enabled_capability_names": "push",
 "signing_certificate_present": "true", "preferred_parent_id_match": "false", "profile_mode": "team", "auth_diagnostic_state": "recorded",
 "team_sha256": String(repeating: "a", count: 64), "requested_bundle_sha256": String(repeating: "b", count: 64), "requested_app_group_sha256": String(repeating: "c", count: 64), "capabilities_sha256": String(repeating: "d", count: 64), "provisioning_bundle_sha256": String(repeating: "e", count: 64)]
// Portal-list identity failures are finite diagnostics, not CMS trust decisions.
let portalKey = "preservation_portal_identity"
let portalKinds = ["invalidHTTPResponse", "httpFailure", "missingStatus", "unsuccessfulStatus", "missingList", "nullList", "malformedList", "malformedRecord", "conflictingRecord", "requestUnavailable", "emptyList", "noExactMatch", "ambiguousMatch", "caseOnlyMatch"]
func portalFailure(_ value: String = "noExactMatch", operation: String = "refresh", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch, cause: CombinedFailure.SafeCause? = .unknownSigningCause, scope: String = "nonHost", token: String = "preservationPortalIdentityUnavailable", kind: String = "invalidParameters") -> CombinedFailure {
 CombinedFailure(operation: operation, stage: stage, code: .failed, id: run, safeCause: cause, sourceStep: step,
 signingContext: ["local_precondition": token, "refresh_target_scope": scope, "refresh_failure_kind": kind, portalKey: value])
}
check(CombinedFailure.preservationPortalIdentityKinds == Set(portalKinds), "portal_exact_finite_vocabulary")
check(portalFailure().signingContext[portalKey] == "noExactMatch" && portalFailure().code == .failed, "portal_diagnostic_does_not_authorize_refresh")
check(CombinedFailure.fromEncodedString(portalFailure().encodedString, expectedID: run)?.signingContext == portalFailure().signingContext, "portal_binary_roundtrip")
check(portalFailure(stage: .command, step: .refreshApplication).signingContext[portalKey] == nil, "portal_refresh_application_scope_rejected")
check(portalFailure(operation: "install").signingContext[portalKey] == nil, "portal_wrong_operation_dropped")
check(portalFailure(stage: .command).signingContext[portalKey] == nil, "portal_wrong_stage_dropped")
check(portalFailure(step: .certificateValidation).signingContext[portalKey] == nil, "portal_wrong_step_dropped")
check(portalFailure(scope: "host").signingContext[portalKey] == nil && portalFailure(scope: "unknown").signingContext[portalKey] == nil, "portal_wrong_scope_dropped")
check(portalFailure(token: "preservationAuthorityConflict").signingContext[portalKey] == nil, "portal_wrong_guard_dropped")
check(portalFailure(kind: "noVPN").signingContext[portalKey] == nil, "portal_wrong_kind_dropped")
check(portalFailure(cause: .certificateUnavailable).signingContext[portalKey] == nil && portalFailure(cause: nil).signingContext[portalKey] != nil, "portal_specific_cause_rejected_placeholder_allowed")
check(portalFailure("SECRET_ACCOUNT_PROFILE_UUID").signingContext[portalKey] == nil && !portalFailure("SECRET_ACCOUNT_PROFILE_UUID").technicalDetails.contains("SECRET"), "portal_opaque_value_stripped")
check(portalFailure(String(repeating: "x", count: 33)).signingContext[portalKey] == nil && portalFailure(String(repeating: "x", count: 33)).signingContext["local_precondition"] == "preservationPortalIdentityUnavailable", "portal_oversize_primary_retained")
var portalWrongType = portalFailure().wire; var portalTypedContext = portalFailure().signingContext as [String: Any]; portalTypedContext[portalKey] = ["profile": "SECRET"]
portalWrongType["signingContext"] = portalTypedContext
check(CombinedFailure.decode(portalWrongType, expectedID: run)?.signingContext[portalKey] == nil && CombinedFailure.decode(portalWrongType, expectedID: run)?.signingContext["local_precondition"] == "preservationPortalIdentityUnavailable", "portal_wrong_type_primary_retained")
var portalMissingScope = portalFailure().signingContext; portalMissingScope.removeValue(forKey: "refresh_target_scope")
check(CombinedFailure.validatedSigningContext(portalMissingScope)?[portalKey] == nil, "portal_missing_scope_dropped")
var portalDense = fullConflictContext; portalDense["local_precondition"] = "preservationPortalIdentityUnavailable"
var portalOverCapacity = portalDense; portalOverCapacity[portalKey] = "noExactMatch"
check(portalDense.count == 20 && CombinedFailure.validatedSigningContext(portalOverCapacity) == portalDense, "portal_capacity_prior_twenty_facts_preserved")
var portalOverflowWire = portalFailure().wire; portalOverflowWire["signingContext"] = portalOverCapacity
check(CombinedFailure.decode(portalOverflowWire, expectedID: run)?.signingContext == portalDense, "portal_wire_capacity_preserved")
var portalWrongCode = portalFailure().wire; portalWrongCode["code"] = "cancelled"
check(CombinedFailure.decode(portalWrongCode, expectedID: run)?.signingContext[portalKey] == nil, "portal_wrong_code_dropped")


check(portalKinds.allSatisfy { value in
 let failure = portalFailure(value)
 return CombinedFailure.fromEncodedString(failure.encodedString, expectedID: run)?.signingContext[portalKey] == value && failure.technicalDetails.contains("preservation_portal_identity=" + value)
}, "portal_all_values_real_wire_and_full_details")
check(CombinedFailure.validatedSigningContext([portalKey: "emptyList"])?.isEmpty == true, "portal_optional_alone_cannot_manufacture_category")
func proof(_ dispatched: Bool) -> [String: Any] {
 ["version": 1, "mutationDispatched": dispatched, "installAcknowledged": false,
  "profileStore": "unavailable", "renewal": "unknown", "certificate": "unknown"]
}
func targetRows(_ failure: CombinedFailure, dispatched: Bool = false) -> [[String: Any]] {
 let manifest: [String: Any] = ["version": 2, "schema": "LiveContainerRefreshManifestV2", "run_id": run,
 "expected_ids": ["private.target"], "requested_ids": ["private.target"], "skipped_ids": [String](),
 "results": [["bundle_id": "private.target", "success": false, "failure": failure.wire, "verification": proof(dispatched)]]]
 return V3RefreshTargetDiagnostics.rows(manifest, runID: run)
}
func copyRows(_ rows: [[String: Any]]) -> String {
 let summary: [String: Any] = ["version": 2, "schema": "LiveContainerRefreshManifestSummaryV2", "run_id": run, "expected_count": 1, "target_diagnostics": rows]
 return V3RefreshTargetDiagnostics.copiedDetails(["run_id": run, "state": "failed", "manifest_summary": summary], runID: run)
}
check(portalKinds.allSatisfy { value in copyRows(targetRows(portalFailure(value))).contains("preservation_portal_identity=" + value) }, "portal_all_values_real_manifest_to_copy")
check(targetRows(portalFailure(), dispatched: true).first?["preservationPortalIdentity"] == nil, "portal_rows_require_predispatch")
check(!copyRows(targetRows(portalFailure())).contains("private.target"), "portal_rows_no_identifiers")
var rows = targetRows(portalFailure())
precondition(rows.count == 1)
let invalidValues: [Any] = ["SECRET", true, ["account": "SECRET"]]
for value in invalidValues {
 rows[0]["preservationPortalIdentity"] = value
 check(!copyRows(rows).isEmpty && !copyRows(rows).contains("preservation_portal_identity="), "portal_invalid_optional_row_preserves_primary")
}
for (key, value) in [("scope", "host"), ("dispatched", "yes"), ("dispatched", "unknown"), ("operation", "completed"), ("guard", "preservationEvidenceUnavailable"), ("failureKind", "noVPN")] {
 var changed = targetRows(portalFailure()); changed[0][key] = value
 check(!copyRows(changed).contains("preservation_portal_identity="), "portal_mismatched_row_does_not_manufacture_diagnosis")
}

// Local profile evidence failures are finite diagnostics, not CMS trust decisions.
let evidenceKey = "preservation_evidence"
let evidenceKinds = ["incompatibleMode", "missingCertificate", "missingReader", "readFailed", "emptyInventory", "noMatchingProfile", "inventoryCountLimit", "emptyProfile", "profileSizeLimit", "inventorySizeLimit", "processingTimeLimit", "missingOrigin", "candidateMismatch"]
func evidenceFailure(_ value: String = "noMatchingProfile", operation: String = "refresh", stage: CombinedFailure.Stage = .signing, step: CombinedFailure.SourceStep = .provisioningProfileFetch, cause: CombinedFailure.SafeCause? = .unknownSigningCause, scope: String = "nonHost", token: String = "preservationEvidenceUnavailable", kind: String = "invalidParameters") -> CombinedFailure {
 CombinedFailure(operation: operation, stage: stage, code: .failed, id: run, safeCause: cause, sourceStep: step,
 signingContext: ["local_precondition": token, "refresh_target_scope": scope, "refresh_failure_kind": kind, evidenceKey: value])
}
check(CombinedFailure.preservationEvidenceKinds == Set(evidenceKinds), "evidence_exact_finite_vocabulary")
check(evidenceFailure().signingContext[evidenceKey] == "noMatchingProfile" && evidenceFailure().code == .failed, "evidence_diagnostic_does_not_authorize_refresh")
check(CombinedFailure.fromEncodedString(evidenceFailure().encodedString, expectedID: run)?.signingContext == evidenceFailure().signingContext, "evidence_binary_roundtrip")
check(evidenceFailure(stage: .command, step: .refreshApplication).signingContext[evidenceKey] == nil, "evidence_refresh_application_scope_rejected")
check(evidenceFailure(operation: "install").signingContext[evidenceKey] == nil, "evidence_wrong_operation_dropped")
check(evidenceFailure(stage: .command).signingContext[evidenceKey] == nil, "evidence_wrong_stage_dropped")
check(evidenceFailure(step: .certificateValidation).signingContext[evidenceKey] == nil, "evidence_wrong_step_dropped")
check(evidenceFailure(scope: "host").signingContext[evidenceKey] == nil && evidenceFailure(scope: "unknown").signingContext[evidenceKey] == nil, "evidence_wrong_scope_dropped")
check(evidenceFailure(token: "preservationAuthorityConflict").signingContext[evidenceKey] == nil, "evidence_wrong_guard_dropped")
check(evidenceFailure(kind: "noVPN").signingContext[evidenceKey] == nil, "evidence_wrong_kind_dropped")
check(evidenceFailure(cause: .certificateUnavailable).signingContext[evidenceKey] == nil && evidenceFailure(cause: nil).signingContext[evidenceKey] != nil, "evidence_specific_cause_rejected_placeholder_allowed")
check(evidenceFailure("SECRET_ACCOUNT_PROFILE_UUID").signingContext[evidenceKey] == nil && !evidenceFailure("SECRET_ACCOUNT_PROFILE_UUID").technicalDetails.contains("SECRET"), "evidence_opaque_value_stripped")
check(evidenceFailure(String(repeating: "x", count: 33)).signingContext[evidenceKey] == nil && evidenceFailure(String(repeating: "x", count: 33)).signingContext["local_precondition"] == "preservationEvidenceUnavailable", "evidence_oversize_primary_retained")
var evidenceWrongType = evidenceFailure().wire; var evidenceTypedContext = evidenceFailure().signingContext as [String: Any]; evidenceTypedContext[evidenceKey] = ["profile": "SECRET"]
evidenceWrongType["signingContext"] = evidenceTypedContext
check(CombinedFailure.decode(evidenceWrongType, expectedID: run)?.signingContext[evidenceKey] == nil && CombinedFailure.decode(evidenceWrongType, expectedID: run)?.signingContext["local_precondition"] == "preservationEvidenceUnavailable", "evidence_wrong_type_primary_retained")
var evidenceMissingScope = evidenceFailure().signingContext; evidenceMissingScope.removeValue(forKey: "refresh_target_scope")
check(CombinedFailure.validatedSigningContext(evidenceMissingScope)?[evidenceKey] == nil, "evidence_missing_scope_dropped")
var evidenceDense = fullConflictContext; evidenceDense["local_precondition"] = "preservationEvidenceUnavailable"
var evidenceOverCapacity = evidenceDense; evidenceOverCapacity[evidenceKey] = "noMatchingProfile"
check(evidenceDense.count == 20 && CombinedFailure.validatedSigningContext(evidenceOverCapacity) == evidenceDense, "evidence_capacity_prior_twenty_facts_preserved")
var evidenceOverflowWire = evidenceFailure().wire; evidenceOverflowWire["signingContext"] = evidenceOverCapacity
check(CombinedFailure.decode(evidenceOverflowWire, expectedID: run)?.signingContext == evidenceDense, "evidence_wire_capacity_preserved")
var evidenceWrongCode = evidenceFailure().wire; evidenceWrongCode["code"] = "cancelled"
check(CombinedFailure.decode(evidenceWrongCode, expectedID: run)?.signingContext[evidenceKey] == nil, "evidence_wrong_code_dropped")


check(evidenceKinds.allSatisfy { value in
 let failure = evidenceFailure(value)
 return CombinedFailure.fromEncodedString(failure.encodedString, expectedID: run)?.signingContext[evidenceKey] == value && failure.technicalDetails.contains("preservation_evidence=" + value)
}, "evidence_all_values_real_wire_and_full_details")
check(CombinedFailure.validatedSigningContext([evidenceKey: "emptyInventory"])?.isEmpty == true, "evidence_optional_alone_cannot_manufacture_category")
check(evidenceKinds.allSatisfy { value in copyRows(targetRows(evidenceFailure(value))).contains("preservation_evidence=" + value) }, "evidence_all_values_real_manifest_to_copy")
check(targetRows(evidenceFailure(), dispatched: true).first?["preservationEvidence"] == nil, "evidence_rows_require_predispatch")
check(!copyRows(targetRows(evidenceFailure())).contains("private.target"), "evidence_rows_no_identifiers")
var evidenceRows = targetRows(evidenceFailure())
precondition(evidenceRows.count == 1)
let evidenceInvalidValues: [Any] = ["SECRET", true, ["account": "SECRET"]]
for value in evidenceInvalidValues {
 evidenceRows[0]["preservationEvidence"] = value
 check(!copyRows(evidenceRows).isEmpty && !copyRows(evidenceRows).contains("preservation_evidence="), "evidence_invalid_optional_row_preserves_primary")
}
for (key, value) in [("scope", "host"), ("dispatched", "yes"), ("dispatched", "unknown"), ("operation", "completed"), ("guard", "preservationPortalIdentityUnavailable"), ("failureKind", "noVPN")] {
 var changed = targetRows(evidenceFailure()); changed[0][key] = value
 check(!copyRows(changed).contains("preservation_evidence="), "evidence_mismatched_row_does_not_manufacture_diagnosis")
}


var legacyEvidenceContext = evidenceFailure().signingContext
legacyEvidenceContext.removeValue(forKey: evidenceKey)
var legacyEvidenceWire = evidenceFailure().wire
legacyEvidenceWire["signingContext"] = legacyEvidenceContext
check(CombinedFailure.decode(legacyEvidenceWire, expectedID: run)?.signingContext == legacyEvidenceContext, "evidence_absent_backward_compatible")
var withOrigin = evidenceFailure().signingContext
withOrigin["apple_profile_origin"] = "recordNotFound"
check(CombinedFailure.validatedSigningContext(withOrigin) == withOrigin, "evidence_origin_diagnostic_coexists")
var crossGuard = evidenceFailure().signingContext
crossGuard[portalKey] = "noExactMatch"
check(CombinedFailure.validatedSigningContext(crossGuard)?[portalKey] == nil && CombinedFailure.validatedSigningContext(crossGuard)?[evidenceKey] == "noMatchingProfile", "evidence_portal_wrong_guard_dropped")
print("PORTAL_WIRE_PASS")

