func require(_ value: @autoclosure () -> Bool, _ label: String) { if !value() { fatalError(label) } }
require(CommandLine.arguments.count == 2, "host wire.plist")
let sentinel = "SECRET_PASSWORD_TOKEN_PRIVATE_DEVICE_ID"
let id = "00000000-0000-0000-0000-000000000001"
let requestID = "00000000-0000-0000-0000-000000000002"
let other = "00000000-0000-0000-0000-000000000003"
let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
let cases = try PropertyListSerialization.propertyList(from: data, format: nil) as! [[String: Any]]
require(cases.count >= 80, "complete imported and local matrix")
var seen = Set<String>(); var validSnapshots: [String: String] = [:]
for item in cases {
    let name = item["name"] as! String; require(seen.insert(name).inserted, "unique rows")
    let result = try V3CatalogRequestContext.classifyReply(item["response"] as! Data, operation: "authPoll", id: requestID)
    let key = item["key"] as! String; let failure = result[key] as! [String: Any]
    require(result["state"] as? String == item["state"] as? String, "state preserved")
    var canonical = failure; canonical.removeValue(forKey: "kind")
    guard let decoded = CombinedFailure.decode(canonical, expectedID: id) else { fatalError("primary disappeared: \(name)") }
    require(decoded.operation == "signIn" && decoded.stage.rawValue == item["primaryStage"] as? String, "category preserved")
    require(decoded.underlyingCode == item["primaryCode"] as! Int, "underlying ordinal preserved: \(name)")
    let fields = decoded.signingContext; require(fields.count <= 20, "host key cap")
    if let typed = item["primaryTyped"] as? String, typed != "unknown" {
        require(fields["typed_error"] == typed, "original typed primary retained")
    }
    if key == "previousFailure" { require(failure["kind"] as? String == "unknown", "prior failure kind preserved") }
    for (key, value) in item["expectedSnapshots"] as? [String: String] ?? [:] { require(fields[key] == value, "exact imported ar1/hp2/ap1 survived decoder") }
    if name == "terminal_structured" { validSnapshots = fields.filter { ["auth_request_trace", "auth_header_provenance", "auth_provider_observation"].contains($0.key) } }
    let copy = V3AuthStore.failureDetails(from: failure)
    let render = V3AuthFailureDiagnosticsPolicy.render(failure, underlyingCode: V3WireContract.strictInt(failure["underlyingCode"]), retryableValue: V3WireContract.strictBool(failure["retryable"]))
    require(copy == render, "actual Copy Details equals actual visible renderer")
    require(!copy.contains(sentinel) && !copy.contains("SENTINEL_") && !copy.contains("SECRET_"), "no secret sentinel copied")
    require(!(result["technicalDetails"] as? String ?? "").contains(sentinel), "untrusted freeform duplicate replaced")
    for expected in item["expected"] as! [String] { require(copy.contains(expected), "\(name): \(expected)") }
    if item["rejected"] as? Bool == true {
        require(fields["auth_diagnostic_state"] == "rejected", "optional fail closed marker")
        require(decoded.code == .failed, "rejected optional does not change primary error")
        if name.hasPrefix("provisioning_") {
            require(fields["typed_error"] == "unknownAccountFailure" && fields["server_code"] == "unknown" && decoded.retryable == false, "pc1 rejected optional keeps primary and policy")
            require(fields[V3ProvisioningCauseDiagnostic.contextKey] == V3ProvisioningCauseDiagnostic.rejected, "malformed pc1 canonical rejected sentinel")
        } else if !name.hasPrefix("legacy_") {
            require(fields["typed_error"] == "sideSignServerReportedError" && fields["server_code"] == "-80045" && decoded.retryable == false, "primary typed context and retryability preserved")
        } else { require(!copy.contains("auth_response_shape=") && !copy.contains("auth_response_mime="), "invalid legacy labels suppressed") }
    } else { require(V3AuthenticationDiagnostics.fits(decoded.wire), "full decoded failure budgets") }
    if name.hasPrefix("terminal_timedOut") || name.hasPrefix("terminal_cancelled") {
        let state = result["state"] as! String
        let held = V3AuthTimeoutDiagnosticRetentionPolicy.failure(reply: result, expectedID: id)
        require(held != nil, "terminal details retained")
        require(V3AuthFailureDiagnosticsPolicy.shouldShowTerminalDetails(state: state, hasPrompt: false, hasFailure: true), "details shown")
        require(!V3AuthFailureDiagnosticsPolicy.shouldShowTerminalDetails(state: state, hasPrompt: true, hasFailure: true), "no duplicate prompt")
        if fields["auth_request_trace"] != nil { require(copy.contains("state=accepted") && !copy.contains("state=rejected"), "cancel does not reinterpret accepted request") }
        if name.contains("_no_login_") { require(fields["debug_login_trace"] == nil, "new evidence retained without old chronology") }
        require(V3AuthTimeoutDiagnosticRetentionPolicy.failure(reply: result, expectedID: other) == nil, "no cross-session evidence")
        require(!V3AuthTimeoutDiagnosticRetentionPolicy.shouldClearOnSessionChange(from: id, to: nil, state: state), "retired terminal remains copyable")
        if state == "cancelled" {
            require(V3AuthTimeoutDiagnosticRetentionPolicy.selecting(state: state, timeout: nil, previous: failure) == nil, "cancel cannot show stale previous failure")
            var wrong = result; var wrongFailure = failure; wrongFailure["code"] = "failed"; wrong["failure"] = wrongFailure
            require(V3AuthTimeoutDiagnosticRetentionPolicy.failure(reply: wrong, expectedID: id) == nil, "cancel requires cancellation envelope")
        }
    }
    if name == "fresh_attempt" { require(fields["auth_request_trace"] == nil && fields["auth_header_provenance"] == nil, "new attempt has no stale request") }
    if name == "legacy_absent_context" { require(!copy.contains("auth_response_shape=") && !copy.contains("auth_response_mime="), "legacy absent context remains absent") }
}
require(V3AuthTimeoutDiagnosticRetentionPolicy.shouldClearOnSessionChange(from: id, to: other, state: "working"), "new attempt clears retired evidence")
require(V3AuthTimeoutDiagnosticRetentionPolicy.selecting(state: "timedOut", timeout: nil, previous: nil) == nil, "no stale timeout evidence")
for state in ["completed", "authenticatedProvisioningIncomplete", "failed", "timedOut", "promptExpired", "cancelled"] {
    let result = applyActualTerminalPresentation(state: state, transient: "verifyingCode")
    require(result.0 == nil && result.1 == false, "actual terminal block clears stale progress")
}
for state in ["working", "awaitingPrompt"] {
    let result = applyActualTerminalPresentation(state: state, transient: "verifyingCode")
    require(result.0 == "verifyingCode" && result.1, "ongoing progress unchanged")
}
var top = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: requestID,
    underlying: NSError(domain: "SideSign.ServerError", code: 3), retryable: false).wire
top["signingContext"] = ["typed_error": "sideSignServerReportedError", "server_code": "-80045", "auth_request_trace": sentinel]
let topBytes = try PropertyListSerialization.data(fromPropertyList: ["version": 1, "id": requestID, "failure": top], format: .binary, options: 0)
do { _ = try V3CatalogRequestContext.classifyReply(topBytes, operation: "authPoll", id: requestID); fatalError("must throw actual primary") }
catch let failure as CombinedFailure {
    require(failure.code == .failed && failure.underlyingCode == 3 && failure.signingContext["server_code"] == "-80045", "top-level primary preserved")
    require(failure.signingContext["auth_diagnostic_state"] == "rejected" && !failure.technicalDetails.contains(sentinel), "top-level safe rejection")
}
let full: [String: String] = ["typed_error": "sideSignServerReportedError", "server_code": "-80045", "http_status": "200",
    "account_binding": "verified", "team_binding": "verified", "session_generation": "1", "capability_count": "1",
    "app_group_count": "0", "extension_count": "0", "capability_names": "push", "enabled_capability_names": "push",
    "signing_certificate_present": "true", "preferred_parent_id_match": "false", "profile_mode": "team", "device_registration": "unobserved",
    "team_sha256": String(repeating: "a", count: 64), "requested_bundle_sha256": String(repeating: "b", count: 64),
    "requested_app_group_sha256": String(repeating: "c", count: 64), "capabilities_sha256": String(repeating: "d", count: 64), "provisioning_bundle_sha256": String(repeating: "e", count: 64)]
require(full.count == 20 && CombinedFailure.validatedSigningContext(full) != nil, "valid original maximum context")
require(validSnapshots.count == 3, "three real finite snapshots")
for addition in validSnapshots.map({ [$0.key: $0.value] }) + [validSnapshots] {
    var extended = full; extended.merge(addition) { _, new in new }
    let constructed = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id, underlying: NSError(domain: "SideSign.ServerError", code: 3), signingContext: extended)
    require(constructed.signingContext.count <= 20 && constructed.signingContext["server_code"] == "-80045", "valid optional init preserves primary")
    require(constructed.signingContext["auth_diagnostic_state"] == "trimmed", "explicit capacity trim")
    var wire = constructed.wire; wire["signingContext"] = extended
    let decoded = CombinedFailure.decode(wire, expectedID: id)!
    require(decoded.underlyingCode == 3 && decoded.signingContext["typed_error"] == "sideSignServerReportedError", "valid optional decode preserves primary")
    let reply: [String: Any] = ["version": 1, "id": requestID, "ok": true, "result": ["state": "failed", "failure": wire]]
    let bytes = try PropertyListSerialization.data(fromPropertyList: reply, format: .binary, options: 0)
    let result = try V3CatalogRequestContext.classifyReply(bytes, operation: "authPoll", id: requestID)
    let nested = CombinedFailure.decode(result["failure"] as! [String: Any], expectedID: id)!
    for (key, value) in addition { require(decoded.signingContext[key] == value && nested.signingContext[key] == value, "exact optional at capacity preserved") }
    let copy = V3AuthStore.failureDetails(from: result["failure"] as! [String: Any])
    require(copy.contains("server_code=-80045") && copy.contains("auth_diagnostic_state=trimmed"), "capacity reaches actual copy")
}
var badStrings = full; badStrings["auth_request_trace"] = sentinel
let badConstructed = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id, signingContext: badStrings)
require(badConstructed.signingContext["server_code"] == "-80045" && badConstructed.signingContext["auth_diagnostic_state"] == "rejected", "direct string init rejects only optional at capacity")
for bad in [sentinel as Any, [sentinel] as Any] {
    var extended = full.mapValues { $0 as Any }; extended["auth_request_trace"] = bad
    let constructed = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id, underlying: NSError(domain: "SideSign.ServerError", code: 3), signingContext: V3AuthenticationDiagnostics.sanitizingWireContext(extended)!)
    require(constructed.signingContext["server_code"] == "-80045", "invalid optional init preserves primary")
    var wire = constructed.wire; wire["signingContext"] = extended
    require(CombinedFailure.decode(wire, expectedID: id)?.signingContext["server_code"] == "-80045", "invalid optional decode preserves primary")
    let reply: [String: Any] = ["version": 1, "id": requestID, "ok": true, "result": ["state": "failed", "failure": wire]]
    let bytes = try PropertyListSerialization.data(fromPropertyList: reply, format: .binary, options: 0)
    let result = try V3CatalogRequestContext.classifyReply(bytes, operation: "authPoll", id: requestID)
    let copy = V3AuthStore.failureDetails(from: result["failure"] as! [String: Any])
    require(copy.contains("server_code=-80045") && copy.contains("auth_diagnostic_state=rejected") && !copy.contains(sentinel), "invalid optional capacity safely copied")
}
print("WIRE_HOST_COPY_PASS cases=\(cases.count) terminal_presentation_states=8 primary_failure_preserved=true")
print("PASS wire_host_real_decode_and_copy")
