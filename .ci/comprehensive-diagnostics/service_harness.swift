// Pure synthetic IPC. Actual collector/profile outputs are imported once; no
// authentication, HTTP task, native library, provider or clipboard is executed.
func require(_ value: @autoclosure () -> Bool, _ label: String) { if !value() { fatalError(label) } }
require(CommandLine.arguments.count == 5, "service wire.plist auth-cases.json profile-cases.json registration-cases.json")
let sentinel = "SECRET_PASSWORD_TOKEN_PRIVATE_DEVICE_ID"
let id = "00000000-0000-0000-0000-000000000001"
let requestID = "00000000-0000-0000-0000-000000000002"
let login = "v1;login_trace_v1;012345abcdef;0;0,2,3,2000,0,0,0"
let primary = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id,
    underlying: NSError(domain: "SideSign.ServerError", code: 3), retryable: false, sourceStep: .appleAuthentication,
    signingContext: ["typed_error": "sideSignServerReportedError", "server_code": "-80045", "http_status": "200"])
let base = primary.wire
var cases: [[String: Any]] = []
var maxBinary = 0; var maxJSON = 0
func emit(_ name: String, _ result: [String: Any], key: String = "failure", expected: [String] = [],
          rejected: Bool = false, primaryCode: Int = 3, snapshots: [String: String] = [:]) throws {
    let failure = result[key] as! [String: Any]
    let fields = (failure["signingContext"] as? [String: Any] ?? [:]).compactMapValues { $0 as? String }
    for (key, value) in snapshots { require(fields[key] == value, "exact producer snapshot survived service") }
    require(fields.count <= 20, "context cap: \(name)")
    let binary = try PropertyListSerialization.data(fromPropertyList: failure, format: .binary, options: 0)
    let json = try JSONSerialization.data(withJSONObject: failure, options: [.sortedKeys])
    if !rejected {
        require(binary.count <= 4096 && json.count <= 4096, "full failure binary and JSON budgets: \(name)")
        maxBinary = max(maxBinary, binary.count); maxJSON = max(maxJSON, json.count)
    }
    let envelope: [String: Any] = ["version": 1, "id": requestID, "ok": true, "result": result]
    let encoded = V3ResponseEncoder.encodeDetailed(envelope, operation: "authPoll", limit: V3WireContract.responseLimit)
    require(encoded.fallbackToken == nil, "real encoder must not replace primary")
    cases.append(["name": name, "response": encoded.data, "key": key, "state": result["state"] as! String,
                  "expected": expected, "rejected": rejected, "primaryCode": primaryCode, "expectedSnapshots": snapshots,
                  "primaryStage": failure["stage"] as? String ?? "authentication",
                  "primaryTyped": fields["typed_error"] ?? "unknown"])
}
func producer(_ argument: Int, schema: String) throws -> [[String: Any]] {
    let root = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[argument]))) as! [String: Any]
    require(root["schema"] as? String == schema, "producer schema")
    let values = root["cases"] as! [[String: Any]]
    require(!values.isEmpty, "nonempty actual producer cases")
    require(Set(values.compactMap { $0["name"] as? String }).count == values.count, "unique actual producer names")
    return values
}
let auth = try producer(2, schema: "auth-request-cases-v1")
let profile = try producer(3, schema: "profile-provenance-cases-v1")
let authNames = Set(auth.compactMap { $0["name"] as? String })
var requiredAuth = Set(["plist accepted", "empty", "html503", "array", "scalar", "malformed", "missingStatus", "wrongStatus", "json", "nested", "wrongEnvelopeFallback", "emptyNestedWins", "nonHTTP", "sameOrigin", "otherOrigin", "mappedEC-80045", "mappedEC-22406", "mappedEC-20101", "mappedEC-20209", "mappedEC-21669", "int0", "int1", "boolFalse", "boolTrue", "float1", "string0", "arrayEC", "outside", "missingEC", "CancellationError", "unknownError", "absentCPD", "wrongCPD", "extraCPD", "authSuccess", "accountLookup", "initFields", "srpInit", "publicKey", "hash", "pbkdf2", "challenge", "proof", "sharedSecret", "hmac", "spdDecrypt", "checksum", "tokenDecrypt", "completeSPD", "proofField", "spdParse", "dsid", "idms", "sessionKey", "sessionChallenge", "tokenField", "tokenLength", "tokenParse", "tokenPath", "recursive2FA", "currentScopeUnavailable", "providerPreAuth", "serializationBeforeRequest", "providerNewAcquisition", "concurrentCollectors:old", "concurrentCollectors:new", "concurrentInvocations"])
for name in ["cancelled", "timeout", "dns", "connectivity", "lost", "tls", "url"] { requiredAuth.insert("transport:" + name) }
for index in 0..<6 { requiredAuth.insert("retryAfter:\(index)") }
for key in ["c", "s", "i", "B"] { for kind in ["initMissing", "initWrong"] { requiredAuth.insert("\(kind):\(key)") } }
for key in 0..<15 { for kind in ["missing", "bool", "string", "emptyString", "data", "emptyData", "integer", "real", "array", "emptyArray", "dictionary", "date"] { requiredAuth.insert("cpd:\(key):\(kind)") } }
for kind in 0..<4 { for index in 0..<9 { requiredAuth.insert("twoFactor:\(kind):\(index)") } }
require(requiredAuth.isSubset(of: authNames), "complete actual response, strict number, transport, CPD, consumer, 2FA and epoch matrix")
require(Set(profile.compactMap { $0["name"] as? String }) == Set(["remote-fresh", "changed-config-cache", "legacy-negative-cache", "verified-public-library", "local-custom-library", "remote-custom-library", "output-mismatch", "failover-return", "acquisition-setup", "acquisition-provider", "acquisition-validation", "acquisition-cancel"]), "all twelve profile cases")
for (values, schema, prefix) in [(auth, "auth-request-cases-v1", "actual_auth"), (profile, "profile-provenance-cases-v1", "actual_profile")] {
    for (index, value) in values.enumerated() {
        let request = value["auth_request_trace"] as? String
        let header = value["auth_header_provenance"] as? String
        let provider = value["auth_provider_observation"] as? String
        if let request { require(V3AuthenticationRequestSnapshot(encoded: request) != nil, "actual ar1 accepted by independent reader") }
        if let header { require(V3AuthenticationHeaderProvenance(encoded: header) != nil, "actual hp2 accepted by independent reader") }
        if let provider { require(V3AuthenticationProviderObservation(encoded: provider) != nil, "actual ap1 accepted by independent reader") }
        let exact = ["auth_request_trace": request, "auth_header_provenance": header, "auth_provider_observation": provider].compactMapValues { $0 }
        let expected = [request == nil ? "auth_request_trace=notRecorded" : "auth_request_schema=ar1",
            header == nil ? "actual_request_used=notRecorded" : "actual_request_used:",
            provider == nil ? "latest_acquisition_observation=notRecorded" : "latest_acquisition_observation:"]
        let terminal = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": base], sessionID: id,
            requestTrace: request, headerProvenance: header, providerObservation: provider, loginTrace: login)
        try emit("\(prefix)_terminal_\(index)", terminal, expected: expected, snapshots: exact)
        let previous = V3AuthDiagnosticExport.previousFailure(base, kind: "unknown", requestTrace: request,
            headerProvenance: header, providerObservation: provider, loginTrace: login)
        try emit("\(prefix)_previous_\(index)", ["state": "awaitingPrompt", "previousFailure": previous], key: "previousFailure", expected: expected, snapshots: exact)
    }
    print("WIRE_IMPORTED_CASES schema=\(schema) producer_cases=\(values.count) wire_cases=\(values.count * 2)")
}
let validRequest = auth.first { $0["name"] as? String == "mappedEC-80045" }!["auth_request_trace"] as! String
let acceptedRequest = auth.first { $0["name"] as? String == "plist accepted" }!["auth_request_trace"] as! String
let hp = profile.first { $0["name"] as? String == "changed-config-cache" }!["auth_header_provenance"] as! String
let ap = profile.first { $0["name"] as? String == "changed-config-cache" }!["auth_provider_observation"] as! String
let exact = ["auth_request_trace": validRequest, "auth_header_provenance": hp, "auth_provider_observation": ap]
let full = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": base], sessionID: id,
    requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: login)
try emit("terminal_structured", full, expected: ["last_observed_request:", "request_ordinal=", "redirect_history=unobserved", "cache_return_input_equality=different", "cpd_fields:", "request_association=unobserved"], snapshots: exact)
for state in ["timedOut", "cancelled"] {
    var original: [String: Any] = ["state": state, "authenticated": false, "resumable": false]
    if state == "timedOut" { original["failure"] = CombinedFailure(operation: "signIn", stage: .authentication, code: .timedOut, id: id).wire }
    let terminal = V3AuthDiagnosticExport.terminal(original, sessionID: id, requestTrace: acceptedRequest, headerProvenance: hp, providerObservation: ap, loginTrace: login)
    for key in ["state", "authenticated", "resumable"] { require(NSDictionary(dictionary: [key: original[key]!]).isEqual(to: [key: terminal[key]!]), "terminal policy unchanged") }
    try emit("terminal_" + state, terminal, expected: ["code=\(state)", "state=accepted"], primaryCode: 0)
}
for state in ["timedOut", "cancelled"] {
    let failure = CombinedFailure(operation: "signIn", stage: .authentication, code: state == "cancelled" ? .cancelled : .timedOut, id: id).wire
    for (label, request, header, provider) in [("request", Optional(acceptedRequest), nil, nil), ("header", nil, Optional(hp), nil), ("provider", nil, nil, Optional(ap))] as [(String, String?, String?, String?)] {
        let terminal = V3AuthDiagnosticExport.terminal(["state": state, "failure": failure], sessionID: id, requestTrace: request, headerProvenance: header, providerObservation: provider, loginTrace: nil)
        require((terminal["failure"] as! [String: Any])["signingContext"] as? [String: String] != nil, "new-only terminal context")
        try emit("terminal_" + state + "_no_login_" + label, terminal, expected: ["code=\(state)"], primaryCode: 0)
    }
}
let fresh = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": base], sessionID: id,
    requestTrace: nil, headerProvenance: nil, providerObservation: nil, loginTrace: login)
try emit("fresh_attempt", fresh, expected: ["auth_request_trace=notRecorded", "actual_request_used=notRecorded", "latest_acquisition_observation=notRecorded"])
let longLogin = "v1;login_trace_v1;012345abcdef;0;" + Array(repeating: "54,2,0,86400000,86400000,2,-2147483648", count: 50).joined(separator: ";")
require(longLogin.utf8.count <= 2048, "original trace cap")
var crowded = base; var crowdedFields = base["signingContext"] as! [String: String]
for key in ["team_sha256", "requested_bundle_sha256", "requested_app_group_sha256", "capabilities_sha256", "signing_certificate_serial_sha256", "provisioning_bundle_sha256"] { crowdedFields[key] = String(repeating: "f", count: 64) }
for key in ["capability_names", "enabled_capability_names"] { crowdedFields[key] = CombinedFailure.signingCapabilityNames.sorted().joined(separator: ",") }
crowded["signingContext"] = crowdedFields
let bounded = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": crowded], sessionID: id,
    requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
try emit("crowded_history", bounded, expected: ["auth_diagnostic_state=trimmed"], snapshots: exact)
var wideParts = validRequest.components(separatedBy: ";")
wideParts[1] = "65535"; wideParts[2] = "65535"; wideParts[3] = "0"; wideParts[4] = "1"
let wideRow = ["65535", "65535", "trustedRequest", "OPTIONS", "phoneRequest", "86400000", "86400000", "1", "rejected", "none", "599", "phoneRequest", "differentOrigin", "u", "16777216", "16777216", "3", "plist", "plistBinary", "plist", "dictionary", "unobserved", "topMissing", "dictionary", "-99999999", "599", "cast", "-99999999", "status", "bbbbsssssssssss", "delta", "86400", "1", "sessionChallenge", "failed", "serviceUnavailable", "1", "32", "headerRequest:unknown:unknown", "plist"]
wideParts[7] = wideRow.joined(separator: ",")
wideParts[8] = (65532...65534).map { "65535,\($0),trustedRequest,rejected,599,-99999999,sessionChallenge,failed" }.joined(separator: "~")
let wideRequest = wideParts.joined(separator: ";")
require(V3AuthenticationRequestSnapshot(encoded: wideRequest) != nil, "maximum finite request vector")
let wideHP = "hp2;localAndroidADI;UserDefaults;Android-akd;UserDefaults;upstreamDefaultAuthKit;mixedKnownFamilies;cacheHit;atLeast30s;Mac-akd;differentFamily;present;notGenerated;unicorn;appleMusic4961447Arm64;observedVerified;unobserved;different;notRecorded;9d5b557cf3faf88c34c394ab2cd7fc1a3b4acf3aed51f28cd0bc093858107c22;bd335e6963ba5ae2f5babca613435ad56d2660a9aee37df35f876c458d105ce4;different"
let wideAP = "ap1;verifiedAppleMusic;clientReady;UserDefaults;Android-akd;unicorn;appleMusic4961447Arm64;observedVerified;present;notRecorded;unobserved;unobserved"
var nativeFields = crowdedFields; nativeFields["typed_error"] = "anisetteKitADIError"
nativeFields.merge(["native_code": "-2", "native_phase": "setupConstructors", "native_subcode": "unknown", "native_init_kind": "dt_init_array", "native_init_reason": "unsupported_interrupt", "native_init_engine": "255", "native_init_library": "65535", "native_init_initializer": "65535"]) { _, new in new }
nativeFields["native_constructor_fault"] = "v1;p0_fault_diag1;3;256;7;65535;805306367;2;" + String(repeating: "a", count: 64) + ";" + String(repeating: "b", count: 64)
var nativeWire = base; nativeWire["underlyingDomain"] = "redacted"; nativeWire["underlyingCode"] = 0; nativeWire["signingContext"] = nativeFields
let wide = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": nativeWire], sessionID: id, requestTrace: wideRequest, headerProvenance: wideHP, providerObservation: wideAP, loginTrace: longLogin)
let wideFields = (wide["failure"] as! [String: Any])["signingContext"] as! [String: String]
require(CombinedFailure.validatedSigningContext(wideFields) != nil && wideFields["native_constructor_fault"] == nativeFields["native_constructor_fault"], "native tuple never split or displaced")
try emit("maximum_finite_context", wide, expected: ["auth_diagnostic_state=trimmed", "request_ordinal=65535", "native_init_initializer=65535"], primaryCode: 0, snapshots: ["auth_request_trace": wideRequest, "auth_header_provenance": wideHP, "auth_provider_observation": wideAP])
var denseFields = nativeFields.filter { ["typed_error", "server_code", "http_status", "native_code", "native_phase", "native_subcode", "native_init_kind", "native_init_reason", "native_init_engine", "native_init_library", "native_init_initializer", "native_constructor_fault"].contains($0.key) }
denseFields.merge(["provider_code": "ENTITY_ERROR", "probe_native_code": "-1", "probe_native_phase": "nativeOTP", "probe_native_subcode": "unknown", "anisette_blob_state": "existing", "anisette_recovery": "probeRejected", "provisioning_bundle_role": "main", "debug_login_trace": login]) { _, new in new }
require(denseFields.count == 20 && CombinedFailure.validatedSigningContext(denseFields) != nil, "dense native original20 valid")
var denseWire = nativeWire; denseWire["signingContext"] = denseFields
let dense = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": denseWire], sessionID: id, requestTrace: wideRequest, headerProvenance: wideHP, providerObservation: wideAP, loginTrace: nil)
let denseOutput = (dense["failure"] as! [String: Any])["signingContext"] as! [String: String]
require(CombinedFailure.validatedSigningContext(denseOutput) != nil && denseOutput["native_constructor_fault"] == denseFields["native_constructor_fault"] && denseOutput["provider_code"] == "ENTITY_ERROR", "dense primary/native survives capacity")
require(denseOutput["probe_native_code"] == nil && denseOutput["probe_native_phase"] == nil && denseOutput["probe_native_subcode"] == nil, "previous probe evicted atomically")
try emit("dense_native_at_capacity", dense, expected: ["auth_diagnostic_state=trimmed", "native_init_initializer=65535"], primaryCode: 0, snapshots: ["auth_request_trace": wideRequest, "auth_header_provenance": wideHP, "auth_provider_observation": wideAP])
for state in ["timedOut", "cancelled"] {
    var original = crowded; original["code"] = state
    let terminal = V3AuthDiagnosticExport.terminal(["state": state, "failure": original], sessionID: id, requestTrace: acceptedRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
    try emit("terminal_" + state + "_crowded", terminal, expected: ["auth_diagnostic_state=trimmed", "state=accepted"], snapshots: ["auth_request_trace": acceptedRequest, "auth_header_provenance": hp, "auth_provider_observation": ap])
}
var noContext = base; noContext.removeValue(forKey: "signingContext")
try emit("no_context_untrusted_duplicate", ["state": "failed", "failure": noContext, "technicalDetails": sentinel], expected: ["auth_request_trace=notRecorded"])
var mutations = ["ar999" + String(validRequest.dropFirst(3)), validRequest + ";extra", sentinel, String(repeating: "x", count: 1025)]
let parts = validRequest.components(separatedBy: ";")
for (column, value) in [(1, "+1"), (2, "65536"), (3, "true"), (4, "2")] { var p = parts; p[column] = value; mutations.append(p.joined(separator: ";")) }
for (column, value) in [(0, "-1"), (1, "01"), (10, "99"), (24, "100000000"), (25, "99"), (25, "600"), (29, sentinel), (37, "33"), (38, sentinel)] {
    var p = parts; var row = p[7].components(separatedBy: ","); row[column] = value; p[7] = row.joined(separator: ","); mutations.append(p.joined(separator: ";"))
}
var duplicate = wideParts; let summary = duplicate[8].components(separatedBy: "~")[0]; duplicate[8] = summary + "~" + summary; mutations.append(duplicate.joined(separator: ";"))
for (index, raw) in mutations.enumerated() {
    require(V3AuthenticationRequestSnapshot(encoded: raw) == nil, "strict ar1 mutation")
    var failure = base; var fields = base["signingContext"] as! [String: String]; fields["auth_request_trace"] = raw; failure["signingContext"] = fields
    try emit("hostile_request_\(index)", ["state": "failed", "failure": failure, "technicalDetails": sentinel], expected: ["auth_diagnostic_state=rejected", "server_code=-80045"], rejected: true)
}
var wrongCache = hp.components(separatedBy: ";"); wrongCache[7] = "generated"; wrongCache[8] = "unknown"; wrongCache[21] = "different"
var wrongEquality = hp.components(separatedBy: ";"); wrongEquality[21] = sentinel
var wrongProvider = ap.components(separatedBy: ";"); wrongProvider[2] = "invented"
for (key, values) in ["auth_header_provenance": [sentinel, hp + ";extra", hp.components(separatedBy: ";").dropLast().joined(separator: ";"), wrongCache.joined(separator: ";"), wrongEquality.joined(separator: ";"), wideHP.replacingOccurrences(of: "9d5b557cf3faf88c34c394ab2cd7fc1a3b4acf3aed51f28cd0bc093858107c22", with: String(repeating: "f", count: 64))], "auth_provider_observation": [sentinel, ap + ";extra", wrongProvider.joined(separator: ";")]] {
    for (index, raw) in values.enumerated() {
        require(key == "auth_header_provenance" ? V3AuthenticationHeaderProvenance(encoded: raw) == nil : V3AuthenticationProviderObservation(encoded: raw) == nil, "strict profile mutation")
        var failure = base; var fields = base["signingContext"] as! [String: String]; fields[key] = raw; failure["signingContext"] = fields
        try emit("hostile_\(key)_\(index)", ["state": "failed", "failure": failure], expected: ["auth_diagnostic_state=rejected"], rejected: true)
    }
}
var wrongType = base; wrongType["signingContext"] = ["typed_error": "sideSignServerReportedError", "server_code": "-80045", "auth_request_trace": [sentinel]] as [String: Any]
try emit("wrong_type", ["state": "failed", "failure": wrongType], expected: ["auth_diagnostic_state=rejected", "server_code=-80045"], rejected: true)
for shape in ["plistDictionary", "plistArray", "plistScalar", "jsonDictionary", "jsonArray", "jsonScalar", "unrecognized"] {
    for mime in ["html", "xmlOrPlist", "json", "other", "unavailable"] {
        let fields = ["typed_error": "sideSignInvalidResponse", "http_status": "503", "auth_response_shape": shape, "auth_response_mime": mime]
        require(CombinedFailure.validatedSigningContext(fields) == fields, "legacy finite shape/MIME accepted")
        let failure = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id, underlying: NSError(domain: "SideSign.ServerError", code: 1), signingContext: fields).wire
        try emit("legacy_\(shape)_\(mime)", ["state": "failed", "failure": failure], expected: ["auth_response_shape=\(shape)", "auth_response_mime=\(mime)", "http_status=503"], primaryCode: 1)
    }
}
let legacy = CombinedFailure(operation: "signIn", stage: .authentication, code: .failed, id: id, underlying: NSError(domain: "SideSign.ServerError", code: 1), signingContext: ["typed_error": "sideSignInvalidResponse", "http_status": "418"]).wire
try emit("legacy_absent_context", ["state": "failed", "failure": legacy], expected: ["http_status=418"], primaryCode: 1)
for key in ["auth_response_shape", "auth_response_mime"] {
    for (index, value) in [sentinel, "unknown_label", String(repeating: "x", count: 513)].enumerated() {
        let fields = ["typed_error": "sideSignInvalidResponse", key: value]
        require(CombinedFailure.validatedSigningContext(fields) == nil, "legacy invalid label rejected")
        var failure = legacy; failure["signingContext"] = fields
        try emit("legacy_hostile_\(key)_\(index)", ["state": "failed", "failure": failure], expected: ["auth_diagnostic_state=rejected"], rejected: true, primaryCode: 1)
    }
}
for (index, value) in ["99", "600", "0200", sentinel].enumerated() {
    let fields = ["typed_error": "sideSignInvalidResponse", "http_status": value]
    require(CombinedFailure.validatedSigningContext(fields) == nil, "invalid HTTP rejected")
    var failure = legacy; failure["signingContext"] = fields
    try emit("legacy_bad_http_\(index)", ["state": "failed", "failure": failure], expected: ["auth_diagnostic_state=rejected"], rejected: true, primaryCode: 1)
}
let wrongKind = ["typed_error": "sideSignServerReportedError", "auth_response_shape": "plistDictionary"]
require(CombinedFailure.validatedSigningContext(wrongKind) == nil, "wrong typed error association rejected")
var wrongKindFailure = legacy; wrongKindFailure["signingContext"] = wrongKind
try emit("legacy_wrong_kind", ["state": "failed", "failure": wrongKindFailure], expected: ["auth_diagnostic_state=rejected"], rejected: true, primaryCode: 1)


// Real registration source -> real mapper -> both real exporters. Compare with
// the independently executed onboarding producer, never synthesize exported pc1.
let registrationImported = try producer(4, schema: "device-registration-cause-cases-v1")
let registrationActual = try await registrationFixtureCases()
require(registrationActual.count == registrationImported.count, "all real producer failures reach mapper")
require(Set(registrationActual.map { $0.name }) == Set(registrationImported.compactMap { $0["name"] as? String }), "same finite registration cases")
for actual in registrationActual {
    let imported = registrationImported.first { $0["name"] as? String == actual.name }!
    let diagnosed = v3AccountOperationFailure(actual.error, step: .registerDevice)
    require(diagnosed.provisioningCause == imported["provisioning_cause"] as? String, "original producer pc1 survives actual mapper")
    require((v3AccountUnderlyingError(actual.error) is OperationError) == (diagnosed.underlying is OperationError), "original OperationError not replaced")
    require((v3AccountUnderlyingError(actual.error) is MinimuxerError) == (diagnosed.underlying is MinimuxerError), "original MinimuxerError not replaced by guidance")
    let retryDetails = CombinedFailure.provisioningRetryTechnicalDetails(for: diagnosed, correlationID: id,
        requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: nil)
    require(retryDetails.contains("provisioning_cause_schema=pc1") && !retryDetails.contains("SECRET_"), "actual provisioning retry details retain safe cause")
    let failure = diagnosed.failure(operation: "signIn", id: id)
    require(failure.sourceStep == .registerDevice, "real device-registration boundary retained")
    let raw = failure.signingContext[V3ProvisioningCauseDiagnostic.contextKey]!
    require(raw == imported["provisioning_cause"] as? String, "actual failure emits exact pc1")
    let parsed = V3ProvisioningCauseDiagnostic(encoded: raw)!
    var expected = ["provisioning_cause_schema=pc1", "provisioning_substep=" + parsed.phase.rawValue,
        "cause_truncated=\(parsed.truncated)", "cause_unknown=\(parsed.unknown)", "cause_cycle=\(parsed.cycle)", "source_step=registerDevice"]
    expected += parsed.rows.map { "type=\($0.type) case=\($0.kind)" }
    var snapshots = exact; snapshots[V3ProvisioningCauseDiagnostic.contextKey] = raw
    let terminal = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": failure.wire], sessionID: id,
        requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
    try emit("actual_registration_terminal_" + actual.name, terminal, expected: expected, primaryCode: failure.underlyingCode, snapshots: snapshots)
    let previous = V3AuthDiagnosticExport.previousFailure(failure.wire, kind: "unknown", requestTrace: validRequest,
        headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
    try emit("actual_registration_previous_" + actual.name, ["state": "awaitingPrompt", "previousFailure": previous], key: "previousFailure",
        expected: expected, primaryCode: failure.underlyingCode, snapshots: snapshots)
}
print("WIRE_IMPORTED_CASES schema=device-registration-cause-cases-v1 producer_cases=\(registrationImported.count) wire_cases=\(registrationImported.count * 2)")
// Generic provisioning errors bypassing the registration wrapper still carry
// the observed original type/case, but must honestly report substep=unobserved.
let genericErrors: [(String, Error)] = [
    ("operation", OperationError.provisioningError(result: "SECRET_RESULT_CANARY", message: "SECRET_MESSAGE_CANARY")),
    ("minimuxer", MinimuxerError.noVPN("SECRET_PAIRING_CANARY")),
    ("unknown", NSError(domain: "SECRET_DOMAIN_CANARY", code: 777,
        userInfo: [NSLocalizedDescriptionKey: "SECRET_PASSWORD_TOKEN_CANARY", "SECRET_KEY_CANARY": "SECRET_ACCOUNT_CANARY"]))]
for step in [CombinedFailure.SourceStep.fetchTeams, .fetchCertificate, .registerDevice, .provisioningUnknown] {
    for (name, original) in genericErrors {
        let diagnosed = v3AccountOperationFailure(original, step: step)
        require(diagnosed.kind == .unknownAccountFailure, "generic classification remains T31")
        guard let cause = diagnosed.provisioningCause, let parsed = V3ProvisioningCauseDiagnostic(encoded: cause) else { fatalError("generic cause not captured") }
        require(parsed.phase == .unobserved && !cause.contains("SECRET_"), "generic error does not invent substep or expose raw payload")
        let failure = diagnosed.failure(operation: "signIn", id: id)
        let result = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": failure.wire], sessionID: id,
            requestTrace: nil, headerProvenance: nil, providerObservation: nil, loginTrace: nil)
        try emit("generic_provisioning_\(step.rawValue)_\(name)", result, expected: ["provisioning_substep=unobserved", "type=" + name],
            primaryCode: failure.underlyingCode, snapshots: [V3ProvisioningCauseDiagnostic.contextKey: cause])
    }
}
let unrelated = v3AccountOperationFailure(OperationError.notAuthenticated, step: .authenticate)
require(unrelated.provisioningCause == nil, "unrelated authentication error does not gain provisioning cause")
let rawMinimuxer = MinimuxerError.noVPN("SECRET_PAIRING_CANARY")
let guidance = v3OperationErrorGuidance(rawMinimuxer.asOperationError)
require(guidance.message.contains("LocalDevVPN") && !guidance.message.contains("SECRET_"), "known raw minimuxer uses existing typed guidance safely")


// Owned observation wrapping must not change authentication classification,
// identity guards, or cancellation; it is never behavioral recovery evidence.
for original in [ServerError.underlyingError(code: -21668, message: "SECRET_TOKEN_CANARY") as Error,
                 V3ProvisioningReauthenticationIdentityError(), LCAnisettePairError.orphanedBlob,
                 CancellationError(), URLError(.cancelled)] {
    let observed = V3ProvisioningCauseError(underlying: original, provisioningCause: v3UnobservedProvisioningCause(original))
    require(v3ClassifyAuthError(original) == v3ClassifyAuthError(observed), "real classifier and identity guard unchanged by observation wrapper")
    require(v3IsAuthCancellation(original) == v3IsAuthCancellation(observed), "owned wrapper preserves cancellation decision")
}
// Direct post-auth terminal catch retains exactly the pre-observer tuple.
for original in [CancellationError() as Error, URLError(.cancelled), URLError(.timedOut), URLError(.notConnectedToInternet),
                 OperationError.notAuthenticated, NSError(domain: "SECRET_DOMAIN_CANARY", code: 777)] {
    let before = CombinedFailure.capture(original, operation: "signIn", stage: .provisioning, id: id)
    let after = v3CaptureAuthFailure(original, operation: "signIn", stage: .provisioning, id: id)
    require(before.stage == after.stage && before.code == after.code && before.retryable == after.retryable &&
        before.safeCause == after.safeCause && before.sourceStep == after.sourceStep &&
        before.underlyingDomain == after.underlyingDomain && before.underlyingCode == after.underlyingCode, "terminal primary classification/cancellation/transport policy unchanged")
    if before.code == .cancelled {
        require(after.code == .cancelled && after.retryable == false && after.signingContext[V3ProvisioningCauseDiagnostic.contextKey] == nil, "cancel stays terminal without provisioning failure")
    } else { require(after.signingContext[V3ProvisioningCauseDiagnostic.contextKey] != nil, "unwrapped generic terminal receives cause without reclassification") }
}

// pc1 strict extension: malformed optional data must never erase primary error,
// retry policy, or the independent ar1/hp2/ap1 snapshots through either route.
let cause = "pc1|liveUDID|0|0|0|liveUDID,minimuxer,noVPN,-,-,-,-,unobserved,unavailable,unavailable,-,-,0"
require(V3ProvisioningCauseDiagnostic.validated(cause) == cause, "finite pc1 accepted")
require(V3ProvisioningCauseDiagnostic.validated(V3ProvisioningCauseDiagnostic.rejected) != nil, "rejected sentinel schema")
let pcFields = ["typed_error": "unknownAccountFailure", "server_code": "unknown", "http_status": "unavailable", V3ProvisioningCauseDiagnostic.contextKey: cause]
let pcPrimary = CombinedFailure(operation: "signIn", stage: .provisioning, code: .failed, id: id,
    underlying: NSError(domain: NSURLErrorDomain, code: -1001), retryable: false, sourceStep: .registerDevice, signingContext: pcFields)
for route in ["terminal", "previous"] {
    let result: [String: Any]
    if route == "terminal" {
        result = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": pcPrimary.wire], sessionID: id,
            requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
    } else {
        result = ["state": "awaitingPrompt", "previousFailure": V3AuthDiagnosticExport.previousFailure(pcPrimary.wire, kind: "unknown",
            requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)]
    }
    var snapshots = exact; snapshots[V3ProvisioningCauseDiagnostic.contextKey] = cause
    try emit("provisioning_" + route, result, key: route == "terminal" ? "failure" : "previousFailure",
        expected: ["provisioning_cause_schema=pc1", "provisioning_substep=liveUDID", "type=minimuxer case=noVPN", "source_step=registerDevice"], primaryCode: -1001, snapshots: snapshots)
}
var causeMutations = ["", sentinel, cause + "|extra", cause + ";", String(repeating: "x", count: 1025), cause + "é",
    cause.replacingOccurrences(of: "pc1|", with: "pc2|"),
    cause.replacingOccurrences(of: "|liveUDID|", with: "|" + sentinel + "|"),
    cause.replacingOccurrences(of: "|0|0|0|", with: "|false|0|0|"),
    cause.replacingOccurrences(of: ",minimuxer,noVPN,", with: ",minimuxer,unknownInjectedCase,"),
    cause.replacingOccurrences(of: ",minimuxer,noVPN,-,", with: ",minimuxer,noVPN,7,"),
    cause.replacingOccurrences(of: ",-,-,0", with: ",-,-,4")]
let sourceRow = cause.components(separatedBy: "|")[5].components(separatedBy: ",")
for index in sourceRow.indices {
    var changed = sourceRow; changed[index] = sentinel
    causeMutations.append("pc1|liveUDID|0|0|0|" + changed.joined(separator: ","))
}
for number in ["+200", "0200", "200.0", "99", "600", "2147483648", "-2147483649"] {
    var changed = sourceRow; changed[5] = number
    causeMutations.append("pc1|liveUDID|0|0|0|" + changed.joined(separator: ","))
}
for (index, invalid) in causeMutations.enumerated() {
    require(V3ProvisioningCauseDiagnostic.validated(invalid) == nil, "strict pc1 negative \(index)")
    for route in ["terminal", "previous"] {
        var failure = pcPrimary.wire; var fields = pcFields; fields[V3ProvisioningCauseDiagnostic.contextKey] = invalid
        failure["signingContext"] = fields
        let key = route == "terminal" ? "failure" : "previousFailure"
        let result = route == "terminal"
            ? V3AuthDiagnosticExport.terminal(["state": "failed", "failure": failure], sessionID: id,
                requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: nil)
            : ["state": "awaitingPrompt", "previousFailure": V3AuthDiagnosticExport.previousFailure(failure, kind: "unknown",
                requestTrace: validRequest, headerProvenance: hp, providerObservation: ap, loginTrace: nil)]
        try emit("provisioning_invalid_\(route)_\(index)", result, key: key,
            expected: ["cause_unknown=true", "auth_diagnostic_state=rejected", "source_step=registerDevice"],
            rejected: true, primaryCode: -1001, snapshots: exact)
    }
}
// Host receives invalid nonstring observations through both production routes.
for (index, bad) in [[sentinel] as Any, ["raw": sentinel] as Any, 42 as Any, true as Any].enumerated() {
    for key in ["failure", "previousFailure"] {
        var failure = pcPrimary.wire; var fields = pcFields.mapValues { $0 as Any }
        fields[V3ProvisioningCauseDiagnostic.contextKey] = bad
        exact.forEach { fields[$0.key] = $0.value }; failure["signingContext"] = fields
        if key == "previousFailure" { failure["kind"] = "unknown" }
        try emit("provisioning_nonstring_\(key)_\(index)", ["state": key == "failure" ? "failed" : "awaitingPrompt", key: failure], key: key,
            expected: ["cause_unknown=true", "auth_diagnostic_state=rejected", "source_step=registerDevice"], rejected: true, primaryCode: -1001)
    }
}
// Dense legitimate context: keep primary fields and all four decisive observations.
var pcDense = crowdedFields
pcDense.merge(pcFields) { _, new in new }
for key in ["session_generation", "capability_count", "app_group_count", "extension_count"] { pcDense[key] = "18446744073709551615" }
for key in ["account_binding", "team_binding"] { pcDense[key] = "verified" }
var denseFailure = pcPrimary.wire; denseFailure["signingContext"] = pcDense
let pcDenseResult = V3AuthDiagnosticExport.terminal(["state": "failed", "failure": denseFailure], sessionID: id,
    requestTrace: wideRequest, headerProvenance: hp, providerObservation: ap, loginTrace: longLogin)
var pcDenseExact = exact; pcDenseExact["auth_request_trace"] = wideRequest; pcDenseExact[V3ProvisioningCauseDiagnostic.contextKey] = cause
try emit("provisioning_dense", pcDenseResult, expected: ["auth_diagnostic_state=trimmed", "type=minimuxer case=noVPN"], primaryCode: -1001, snapshots: pcDenseExact)


let wideCauseRows = [
    "liveUDID,server,invalidResponseFormat,-,-,599,-,plistDictionary,xmlOrPlist,over4096,-,-,0",
    "fallbackUDID,server,invalidResponseFormat,-,-,599,-,plistDictionary,xmlOrPlist,over4096,-,-,0",
    "listDevices,server,invalidResponseFormat,-,-2147483648,599,ENTITY_ERROR.RELATIONSHIP.INVALID_NOT_ALLOWED,plistDictionary,xmlOrPlist,over4096,-,-,0",
    "registerDevice,server,invalidResponseFormat,-,2147483647,599,ENTITY_ERROR.RELATIONSHIP.INVALID_NOT_ALLOWED,plistDictionary,xmlOrPlist,over4096,-,-,0"]
let wideCause = "pc1|registerDevice|1|0|0|" + wideCauseRows.joined(separator: ";")
require(V3ProvisioningCauseDiagnostic.validated(wideCause) == wideCause, "wide legitimate four-boundary cause")
pcDense[V3ProvisioningCauseDiagnostic.contextKey] = wideCause
denseFailure["signingContext"] = pcDense
for route in ["terminal", "previous"] {
    let key = route == "terminal" ? "failure" : "previousFailure"
    let result = route == "terminal"
        ? V3AuthDiagnosticExport.terminal(["state": "failed", "failure": denseFailure], sessionID: id,
            requestTrace: wideRequest, headerProvenance: wideHP, providerObservation: wideAP, loginTrace: longLogin)
        : ["state": "awaitingPrompt", "previousFailure": V3AuthDiagnosticExport.previousFailure(denseFailure, kind: "unknown",
            requestTrace: wideRequest, headerProvenance: wideHP, providerObservation: wideAP, loginTrace: longLogin)]
    let snapshots = [V3ProvisioningCauseDiagnostic.contextKey: wideCause, "auth_request_trace": wideRequest,
        "auth_header_provenance": wideHP, "auth_provider_observation": wideAP]
    try emit("provisioning_widest_" + route, result, key: key, expected: ["cause_truncated=true", "auth_diagnostic_state=trimmed"], primaryCode: -1001, snapshots: snapshots)
}

try PropertyListSerialization.data(fromPropertyList: cases, format: .binary, options: 0).write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
print("WIRE_SERVICE_PASS cases=\(cases.count) max_binary=\(maxBinary) max_json=\(maxJSON)")
print("PASS wire_service_real_codec_and_imported_cases")
