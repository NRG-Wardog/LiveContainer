// Pure synthetic IPC. Actual collector/profile outputs are imported once; no
// authentication, HTTP task, native library, provider or clipboard is executed.
func require(_ value: @autoclosure () -> Bool, _ label: String) { if !value() { fatalError(label) } }
require(CommandLine.arguments.count == 4, "service wire.plist auth-cases.json profile-cases.json")
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
    let fields = failure["signingContext"] as? [String: String] ?? [:]
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
                  "expected": expected, "rejected": rejected, "primaryCode": primaryCode, "expectedSnapshots": snapshots])
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
try PropertyListSerialization.data(fromPropertyList: cases, format: .binary, options: 0).write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
print("WIRE_SERVICE_PASS cases=\(cases.count) max_binary=\(maxBinary) max_json=\(maxJSON)")
print("PASS wire_service_real_codec_and_imported_cases")
