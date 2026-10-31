let run = "11111111-1111-4111-8111-111111111111"
let request = "22222222-2222-4222-8222-222222222222"
let token = "33333333-3333-4333-8333-333333333333"
let uri = "x-coredata://44444444-4444-4444-8444-444444444444/InstalledApp/p1"
func check(_ value: @autoclosure () -> Bool, _ name: String) { precondition(value(),name); print("PASS " + name) }
func proof(_ dispatched: Bool = false, _ ack: Bool = false, renewed: Bool = false) -> [String:Any] {
 ["version":1,"mutationDispatched":dispatched,"installAcknowledged":ack,"profileStore":ack ? "matched":"unavailable","renewal":ack ? (renewed ? "extended":"unchanged"):"unknown","certificate":ack ? "valid":"unknown"]
}
func failure(_ guardToken: String = "legacyProofUnavailable", scope: String = "nonHost", step: CombinedFailure.SourceStep = .refreshApplication, stage: CombinedFailure.Stage = .command) -> CombinedFailure {
 CombinedFailure(operation:"refresh",stage:stage,code:.failed,id:run,sourceStep:step,
 signingContext:["local_precondition":guardToken,"refresh_target_scope":scope,"refresh_failure_kind":"invalidParameters"])
}
func manifest(failed: Bool = true, evidence: [String:Any]? = proof(), error: CombinedFailure = failure()) -> [String:Any] {
 var first: [String:Any] = ["bundle_id":"private.failed","success":!failed,"failure":error.wire]
 if let evidence { first["verification"]=evidence }
 return ["version":2,"schema":"LiveContainerRefreshManifestV2","run_id":run,"expected_ids":["private.failed","private.success"],"requested_ids":["private.failed","private.success"],"skipped_ids":[String](),"results":[first,["bundle_id":"private.success","success":true,"verification":proof(true,true,renewed:true)]]]
}
let record: [String:Any] = ["run_id":run,"request_id":request,"state":"failed"]
func candidate(_ value: [String:Any]? = manifest(), _ history: [String:Any]? = [run:record], host: Bool = false, active: String? = nil, uncertain: Bool = false, bundle: String = "private.failed") -> V3LegacyReplacementCandidate? {
 V3LegacyReplacementPolicy.candidate(manifest:value,ledger:history,target:uri,bundleID:bundle,isHost:host,isActive:true,activeRunID:active,uncertain:uncertain)
}
let eligible = candidate()!
check(eligible.runID == run && eligible.requestID == request && eligible.target == uri, "exact_failed_target_identity")
check(candidate(bundle:"private.success") == nil, "successful_target_never_selected")
check(candidate(host:true) == nil, "host_excluded")
check(candidate(active:request) == nil, "active_run_blocks")
check(candidate(uncertain:true) == nil, "uncertain_hold_blocks")
check(candidate(manifest(failed:false)) == nil, "successful_result_blocks")
check(candidate(manifest(evidence:nil)) == nil, "missing_mutation_evidence_blocks")
check(candidate(manifest(evidence:proof(true))) == nil, "dispatched_result_blocks")
check(candidate(manifest(evidence:proof(true,true))) == nil, "acknowledged_result_blocks")
check(candidate(manifest(error:failure("missingMainProfile"))) == nil, "other_failure_not_replacement")
check(candidate(manifest(error:failure(scope:"host"))) == nil, "host_scope_blocks")
check(candidate(manifest(error:failure(step:.refreshReadiness))) == nil, "network_failure_not_replacement")
var changed = manifest();changed["version"]=2.0
check(candidate(changed) == nil, "floating_manifest_version_blocks")
changed=manifest();changed["results"]=(changed["results"] as! [[String:Any]]).dropLast().map{$0}
check(candidate(changed) == nil, "partial_batch_blocks")
var history=record;history["state"]="running"
check(candidate(manifest(),[run:history]) == nil, "nonterminal_ledger_blocks")
history=record;history["request_id"]="unbound"
check(candidate(manifest(),[run:history]) == nil, "noncanonical_request_blocks")
check(candidate(nil,[run:record]) == nil, "summary_only_cannot_enable")
let available: [String:Any] = ["version":1,"eligible":true,"reason":"available","token":token,"expiresInSeconds":120,"riskAcknowledgmentVersion":1,"extensionCount":2]
var attempt=V3LegacyReplacementAttempt();var generation=attempt.begin(eligible)
check(attempt.receive(available,generation:generation,current:eligible,now:10), "eligible_assessment_accepted")
check(attempt.confirm(current:eligible,now:11,acknowledged:false,blocked:false) == nil, "consent_required")
generation=attempt.begin(eligible);_ = attempt.receive(available,generation:generation,current:eligible,now:10)
check(attempt.confirm(current:eligible,now:11,acknowledged:true,blocked:false) == token, "explicit_confirmation_returns_exact_token")
check(attempt.confirm(current:eligible,now:12,acknowledged:true,blocked:false) == nil, "double_confirmation_blocked")
generation=attempt.begin(eligible);attempt.cancel()
check(!attempt.receive(available,generation:generation,current:eligible,now:10) && attempt.token == nil, "cancelled_late_reply_ignored")
generation=attempt.begin(eligible);let newer=attempt.begin(eligible)
check(!attempt.receive(available,generation:generation,current:eligible,now:10) && attempt.generation == newer, "superseded_reply_ignored")
generation=attempt.begin(eligible)
check(!attempt.receive(available,generation:generation,current:nil,now:10), "changed_history_reply_ignored")
generation=attempt.begin(eligible);_ = attempt.receive(available,generation:generation,current:eligible,now:10)
check(attempt.confirm(current:eligible,now:130,acknowledged:true,blocked:false) == nil, "expired_token_blocked")
generation=attempt.begin(eligible);_ = attempt.receive(available,generation:generation,current:eligible,now:10)
check(attempt.confirm(current:eligible,now:11,acknowledged:true,blocked:true) == nil, "concurrent_operation_blocks")
let malformedAssessments: [[String:Any]] = [ ["version":true], ["version":1.0], ["riskAcknowledgmentVersion":true], ["expiresInSeconds":121], ["extensionCount":0], ["extensionCount":129], ["extensionCount":true], ["eligible":1], ["token":"not-a-token"], ["extra":"SECRET"] ]
for (index, mutation) in malformedAssessments.enumerated() {
 var raw=available;for(k,v)in mutation{raw[k]=v}
 generation=attempt.begin(eligible)
 check(!attempt.receive(raw,generation:generation,current:eligible,now:10) && attempt.token == nil,"malformed_assessment_\(index)")
}
generation=attempt.begin(eligible);_ = attempt.receive(available,generation:generation,current:eligible,now:10)
var malformed=available;malformed["version"]=true
check(!attempt.receive(malformed,generation:generation,current:eligible,now:11) && attempt.token == nil, "malformed_reply_clears_old_token")
for reason in V3LegacyReplacementPolicy.reasons.sorted() {
 generation=attempt.begin(eligible)
 check(attempt.receive(["version":1,"eligible":false,"reason":reason,"riskAcknowledgmentVersion":1],generation:generation,current:eligible,now:10) && attempt.token == nil,"finite_refusal_\(reason)")
}
var pending=V3LegacyReplacementConfirmation();pending.stage(token:token,candidate:eligible);pending.cancel()
check(pending.take(current:eligible,foreground:true) == nil,"confirm_dismiss_background_no_dispatch")
pending.stage(token:token,candidate:eligible)
check(pending.take(current:eligible,foreground:false) == nil && !pending.isPending,"background_dismiss_no_dispatch")
pending.stage(token:token,candidate:eligible)
check(pending.take(current:nil,foreground:true) == nil,"history_changed_at_dismiss_no_dispatch")
pending.stage(token:token,candidate:eligible)
check(pending.take(current:eligible,foreground:true) == token && pending.take(current:eligible,foreground:true) == nil,"dismiss_dispatch_once")
let journal=V3OperationRecoveryRecord(sessionID:request,kind:"legacyReplacement",phase:.dispatched)!
check(V3OperationRecoveryRecord.decodePropertyList(journal.propertyListRepresentation) == journal,"restart_retains_known_session_kind")
check(journal.propertyListRepresentation["token"] == nil,"restart_journal_never_persists_assessment_token")
check(V3DirectProfileVerificationPolicy.outcome(["state":"completed"],operation:"legacyReplacement") == .unconfirmed,"completed_without_evidence_not_green")
check(V3DirectProfileVerificationPolicy.requiresDeviceCheck(["state":"completed"],operation:"legacyReplacement"),"completed_unknown_requires_check")
check(V3DirectProfileVerificationPolicy.outcome(["state":"failed","verification":proof(true)],operation:"legacyReplacement") == .mutationUnconfirmed,"lost_ack_unknown_not_failed_replay")
check(V3DirectProfileVerificationPolicy.blocksRetry(["state":"failed","verification":proof(true)],operation:"legacyReplacement"),"lost_ack_blocks_retry")
check(V3DirectProfileVerificationPolicy.outcome(["state":"completed","verification":proof(true,true,renewed:true)],operation:"legacyReplacement") == .renewed,"verified_evidence_not_assessment_proves_renewal")
func wire(_ operation: String, target: String = "", payload: [String:Any]) -> Bool {
 let now=Date(timeIntervalSince1970:100)
 let raw: [String:Any] = ["version":1,"id":request,"operation":operation,"target":target,"deadline":now.addingTimeInterval(30),"payload":payload]
 let bytes=try! PropertyListSerialization.data(fromPropertyList:raw,format:.binary,options:0)
 return V3WireContract.decodeRequest(bytes,now:now) != nil
}
check(wire("legacyReplacementPrepare",target:uri,payload:["runID":run,"requestID":request]),"prepare_wire_bound_target_run_request")
let reservation: [String:Any] = ["kind":"legacyReplacement","target":token,"session":request]
check(wire("opRecoveryPrepare",payload:reservation),"known_session_reserved_before_dispatch")
check(!wire("opStart",payload:reservation),"wire_requires_explicit_consent")
var start=reservation;start["riskAcknowledgmentVersion"]=1;start["userConfirmed"]=true
check(wire("opStart",payload:start),"confirmed_wire_uses_same_known_session")
start["riskAcknowledgmentVersion"]=true
check(!wire("opStart",payload:start),"boolean_consent_version_rejected")
start["riskAcknowledgmentVersion"]=1.0
check(!wire("opStart",payload:start),"floating_consent_version_rejected")
start["riskAcknowledgmentVersion"]=1;start["userConfirmed"]=false
check(!wire("opStart",payload:start),"negative_consent_rejected")
print("LEGACY_REPLACEMENT_HOST_PASS")

check(failure("preservationEvidenceUnavailable", step: .provisioningProfileFetch, stage: .signing).safeMessage.contains("existing matching profile"), "preservation_fetch_guard_allowed")
check(failure("preservationAuthorizationChanged").safeMessage.contains("change existing authorization"), "preservation_refresh_guard_allowed")
check(failure("legacyProofUnavailable", step: .provisioningProfileFetch).safeMessage.contains("The installed app was preserved.") == false, "legacy_guard_not_broadened_to_fetch")
check(failure("preservationEvidenceUnavailable", step: .provisioningProfileCreation).safeMessage.contains("The installed app was preserved.") == false, "preservation_guard_wrong_stage_rejected")
check(failure("preservationUnknown").safeMessage.contains("The installed app was preserved.") == false, "preservation_unknown_guard_rejected")
check(failure("preservationEvidenceUnavailable").safeMessage.contains("preserved"), "preservation_failure_explains_unchanged_app")

check(failure("preservationEvidenceUnavailable", step: .provisioningProfileRetrieval).safeMessage.contains("The installed app was preserved.") == false, "preservation_network_retrieval_guard_rejected")

check(failure("preservationEvidenceUnavailable", step: .provisioningProfileFetch).signingContext["local_precondition"] == nil, "preservation_command_fetch_context_rejected")
check(failure("preservationEvidenceUnavailable", step: .provisioningProfileFetch, stage: .signing).signingContext["local_precondition"] == "preservationEvidenceUnavailable", "preservation_signing_fetch_context_retained")
check(failure("preservationUnknown", step: .provisioningProfileFetch, stage: .signing).signingContext["local_precondition"] == nil, "preservation_signing_fetch_unknown_rejected")
check(failure("legacyProofUnavailable", step: .provisioningProfileFetch, stage: .signing).signingContext["local_precondition"] == nil, "legacy_signing_fetch_context_rejected")
check(failure("preservationEvidenceUnavailable", step: .provisioningProfileRetrieval, stage: .signing).signingContext["local_precondition"] == nil, "preservation_signing_inner_retrieval_rejected")
let fetchPreservation = failure("preservationEvidenceUnavailable", step: .provisioningProfileFetch, stage: .signing)
check(CombinedFailure.decode(fetchPreservation.wire, expectedID: run)?.safeMessage == fetchPreservation.safeMessage, "preservation_signing_fetch_wire_roundtrip")

let wrongPreservationKind = CombinedFailure(operation: "refresh", stage: .signing, code: .failed, id: run, sourceStep: .provisioningProfileFetch, signingContext: ["local_precondition": "preservationEvidenceUnavailable", "refresh_failure_kind": "certificateVerificationUnavailable"])
check(wrongPreservationKind.signingContext["local_precondition"] == nil, "preservation_wrong_failure_kind_rejected")
check(failure("preservationEvidenceUnavailable", step: .provisioningProfileFetch, stage: .installation).signingContext["local_precondition"] == nil, "preservation_installation_stage_rejected")
check(failure("unknownTeamType", step: .provisioningProfileFetch, stage: .signing).signingContext["local_precondition"] == "unknownTeamType", "old_preparation_guard_retained")
check(failure("unknownTeamType", step: .provisioningProfileFetch).signingContext["local_precondition"] == nil, "old_preparation_wrong_stage_rejected")
