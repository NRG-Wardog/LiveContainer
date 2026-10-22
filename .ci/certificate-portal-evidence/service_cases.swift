@main struct PortalServiceCases {
    static let id = "00000000-0000-0000-0000-000000000001"
    static func check(_ value: @autoclosure () -> Bool, _ name: String) { precondition(value(), name) }
    static func json(_ object: [String: Any]) -> Data { try! JSONSerialization.data(withJSONObject: object) }
    static func errorJSON(code: String?, second: String? = nil) -> Data {
        var error = ["detail": fixtureSecret + " lc_stage=installation PPQ quota",
                     "title": fixtureSecret, "status": "SECRET_HTTP_STATUS", "id": fixtureSecret]
        if let code { error["code"] = code }
        var errors = [error]
        if let second { errors.append(["code": second, "detail": fixtureSecret]) }
        return json(["errors": errors, "privateIdentifier": fixtureSecret])
    }
    @MainActor static func main() async throws {
        var rows: [[String: Any]] = []
        let cases: [(String, FixtureResponse, String, String, String, Int, String)] = [
            ("known_entity_422", FixtureResponse(body: errorJSON(code: "ENTITY_ERROR"), status: 422), "422", "ENTITY_ERROR", "unknown", 3, "sideSignServerReportedError"),
            ("known_forbidden_403", FixtureResponse(body: errorJSON(code: "FORBIDDEN_ERROR"), status: 403), "403", "FORBIDDEN_ERROR", "unknown", 3, "sideSignServerReportedError"),
            ("unknown_code_redacted", FixtureResponse(body: errorJSON(code: fixtureSecret), status: 409), "409", "unavailable", "unknown", 3, "sideSignServerReportedError"),
            ("plausible_unknown_code_redacted", FixtureResponse(body: errorJSON(code: "ENTITY_ERROR.NEW_IDENTIFIER"), status: 400), "400", "unavailable", "unknown", 3, "sideSignServerReportedError"),
            ("missing_code", FixtureResponse(body: errorJSON(code: nil), status: 401), "401", "unavailable", "unknown", 3, "sideSignServerReportedError"),
            ("no_http_response", FixtureResponse(body: errorJSON(code: "SERVICE_UNAVAILABLE"), status: nil), "unavailable", "SERVICE_UNAVAILABLE", "unknown", 3, "sideSignServerReportedError"),
            ("first_error_only", FixtureResponse(body: errorJSON(code: "NOT_FOUND", second: fixtureSecret), status: 404), "404", "NOT_FOUND", "unknown", 3, "sideSignServerReportedError"),
            ("numeric_result_preserved", FixtureResponse(body: json(["resultCode": 1100, "userString": fixtureSecret]), status: 200), "200", "unavailable", "1100", 3, "sideSignServerReportedError"),
            ("empty_body_preserved", FixtureResponse(body: Data(), status: 503), "503", "unavailable", "unknown", 0, "sideSignBadResponse"),
            ("invalid_json_redacted", FixtureResponse(body: Data(fixtureSecret.utf8), status: 502), "502", "unavailable", "unknown", 1, "sideSignInvalidResponse")
        ]
        for (name, response, http, code, server, ordinal, typed) in cases {
            FixtureVisits.reset()
            let data = await FixtureDispatch.$response.withValue(response) {
                await FixtureCommandDispatcher().reply(id: id)
            }
            let envelope = try PropertyListSerialization.propertyList(from: data, format: nil) as! [String: Any]
            let failure = CombinedFailure.decode(envelope["failure"] as! [String: Any], expectedID: id)!
            check(failure.stage == .signing && failure.sourceStep == .fetchCertificate, "owned command stage and step")
            check(failure.underlyingDomain == "SideSign.ServerError" && failure.underlyingCode == ordinal, "original ServerError domain and ordinal")
            check(failure.signingContext["typed_error"] == typed, "typed primary error preserved")
            check(failure.signingContext["server_code"] == (server == "unknown" && ordinal != 3 ? nil : server), "numeric sentinel not promoted")
            check(failure.signingContext["http_status"] == (fixtureCandidate ? http : "unavailable"), "baseline loss or candidate finite HTTP")
            check(failure.signingContext["provider_code"] == (fixtureCandidate ? code : nil), "baseline loss or candidate finite provider code")
            check(!failure.technicalDetails.contains(fixtureSecret), "provider and request canaries absent")
            check(FixtureVisits.events == ["authenticate", "accountLookup", "boundSession", "boundTeam", "verifyCurrent", "dispatch"], "failure dispatch and identity visit ordering unchanged")
            check(FixtureVisits.requestPaths == [Constants.URLs.certificatesDeveloperServices2.absoluteString], "free endpoint unchanged")
            check(FixtureVisits.requestMethods == ["POST"] && FixtureVisits.overrides == ["GET"], "original transport method override preserved")
            rows.append(["name": name, "candidate": fixtureCandidate, "response": data,
                         "http": fixtureCandidate ? http : "unavailable", "provider": fixtureCandidate ? code : "absent",
                         "server": server, "ordinal": ordinal, "typed": typed])
        }
        // Paid route remains selected by the original SideSign implementation.
        FixtureVisits.reset(); AuthManager.shared.fixtureTeam.type = .paid
        let paid = await FixtureDispatch.$response.withValue(cases[0].1) { await FixtureCommandDispatcher().reply(id: id) }
        check(FixtureVisits.requestPaths == [Constants.URLs.certificatesDeveloperPortal.absoluteString], "paid endpoint unchanged")
        rows.append(["name": "paid_endpoint", "candidate": fixtureCandidate, "response": paid,
                     "http": fixtureCandidate ? "422" : "unavailable", "provider": fixtureCandidate ? "ENTITY_ERROR" : "absent",
                     "server": "unknown", "ordinal": 3, "typed": "sideSignServerReportedError"])
        AuthManager.shared.fixtureTeam.type = .free
        // Success is still a success; no certificate is fabricated or mutated.
        FixtureVisits.reset()
        let success = await FixtureDispatch.$response.withValue(.empty) { await FixtureCommandDispatcher().reply(id: id) }
        let successObject = try PropertyListSerialization.propertyList(from: success, format: nil) as! [String: Any]
        check(successObject["ok"] as? Bool == true && successObject["failure"] == nil, "success unchanged")
        check(((successObject["result"] as! [String: Any])["certificates"] as! [[String: Any]]).isEmpty, "empty list unchanged")
        check(FixtureVisits.events.last == "verifyCurrent" && FixtureVisits.events.filter { $0 == "dispatch" }.count == 1, "success post-read identity check preserved")
        rows.append(["name": "success_unchanged", "candidate": fixtureCandidate, "response": success])
        // The existing boundary preserves cancellation and pre-existing failures.
        for step in ["authenticate", "accountLookup", "boundSession"] {
            FixtureVisits.reset(); FixtureVisits.failingAuthStep = step
            FixtureVisits.injectedBeforeDispatch = CancellationError()
            do { _ = try await V3BackendCommands.portalCertificates(); preconditionFailure("expected cancellation") }
            catch { check(error is CancellationError, "cancellation not wrapped") }
            check(!FixtureVisits.events.contains("dispatch"), "cancelled before any dispatch")
        }
        FixtureVisits.reset()
        let known = CombinedFailure(operation: "signIn", stage: .authentication, code: .notReady,
            id: id, safeCause: .authSessionUnavailable, sourceStep: .anisetteFetch)
        FixtureVisits.injectedBeforeDispatch = known
        do { _ = try await V3BackendCommands.portalCertificates(); preconditionFailure("expected known failure") }
        catch {
            check(NSDictionary(dictionary: (error as! CombinedFailure).wire).isEqual(to: known.wire), "existing CombinedFailure unchanged")
        }
        // Non-server business errors are not converted by the reused helper.
        do {
            let _: Int = try await lcPortalSigningRequest(sourceStep: "fetchCertificate", facts: [:]) {
                throw DeveloperPortalError.certificateDoesNotExist(serial: fixtureSecret)
            }
            preconditionFailure("expected typed portal error")
        } catch let portal as DeveloperPortalError {
            guard case .certificateDoesNotExist(let serial) = portal else { preconditionFailure("typed case changed") }
            check(serial == fixtureSecret, "typed portal payload stays local and unchanged")
        }
        FixtureVisits.reset()
        let network = NSError(domain: NSURLErrorDomain, code: NSURLErrorTimedOut,
            userInfo: [NSLocalizedDescriptionKey: fixtureSecret])
        let transport = await FixtureDispatch.$response.withValue(FixtureResponse(body: Data(), status: nil, transportError: network)) {
            await FixtureCommandDispatcher().reply(id: id)
        }
        rows.append(["name": "network_primary_preserved", "candidate": fixtureCandidate, "response": transport])
        // These four local causes traverse the same real account-read wrapper,
        // generic NSError chain capture, binary IPC and matching host decoder.
        // Direct and nested NSError variants are assertions within each row.
        let remoteCases: [(Int, String, String)] = [
            (1, "remoteIdentityInvalidRecord", "T43"),
            (2, "remoteIdentityStorageUnverified", "T44"),
            (3, "remoteIdentityStateChanged", "T45"),
            (4, "remoteIdentityManualSignInRequired", "T46")
        ]
        for (localCode, typed, token) in remoteCases {
            let local = NSError(domain: "SideStore.RemoteIdentity", code: localCode,
                userInfo: [NSLocalizedDescriptionKey: fixtureSecret, "privateToken": fixtureSecret,
                           "privatePairing": fixtureSecret, "providerPayload": fixtureSecret])
            let wrapper = NSError(domain: "Synthetic.RemoteIdentityWrapper", code: 991,
                userInfo: [NSUnderlyingErrorKey: local, NSLocalizedDescriptionKey: fixtureSecret,
                           "privateCertificate": fixtureSecret,
                           "LCStructuredSigningContextV1": ["anisette_blob_state": "existing", "anisette_recovery": "notAttempted",
                               "http_status": "418", "server_code": "42"]])
            var retained: Data?
            for (index, error) in [local, wrapper].enumerated() {
                FixtureVisits.reset()
                FixtureVisits.failingAuthStep = "authenticate"
                FixtureVisits.injectedBeforeDispatch = error
                let data = await FixtureCommandDispatcher().reply(id: id)
                let envelope = try PropertyListSerialization.propertyList(from: data, format: nil) as! [String: Any]
                let failure = CombinedFailure.decode(envelope["failure"] as! [String: Any], expectedID: id)!
                check(!FixtureVisits.events.contains("dispatch"), "local identity rejection never dispatches to Apple")
                check(!failure.technicalDetails.contains(fixtureSecret), "identity wrapper userInfo remains private")
                if fixtureCandidate {
                    check(failure.stage == .authentication && failure.sourceStep == .anisetteFetch,
                          "actual local NSError resolves to authentication anisetteFetch")
                    check(failure.signingContext["typed_error"] == typed && failure.diagnosticCode.contains("-" + token),
                          "exact finite local identity kind and diagnostic token survive wrappers")
                    check(failure.retryable == false && failure.safeCause == nil,
                          "identity failure refuses automatic retry without invented provider cause")
                    check(failure.signingContext["provider_code"] == nil &&
                          failure.signingContext["http_status"] == (index == 0 ? "unavailable" : "418") &&
                          failure.signingContext["server_code"] == (index == 0 ? "unknown" : "42"),
                          "only prior validated remote response observations survive local identity mapping")
                } else {
                    check(failure.signingContext["typed_error"] != typed && !failure.diagnosticCode.contains("-" + token),
                          "delivered baseline does not fabricate new local identity diagnosis")
                }
                if index == 1 {
                    check(failure.signingContext["anisette_blob_state"] == "existing" &&
                          failure.signingContext["anisette_recovery"] == "notAttempted",
                          "validated finite outer observations survive local identity mapping")
                }
                retained = data
            }
            let incompatible = NSError(domain: "Synthetic.RemoteIdentityWrapper", code: 991,
                userInfo: [NSUnderlyingErrorKey: local, NSLocalizedDescriptionKey: fixtureSecret,
                    "LCStructuredSigningContextV1": ["typed_error": "sideSignInvalidResponse",
                        "auth_response_mime": "json", "auth_response_shape": "jsonArray",
                        "http_status": "418", "server_code": "42"]])
            FixtureVisits.reset()
            FixtureVisits.failingAuthStep = "authenticate"
            FixtureVisits.injectedBeforeDispatch = incompatible
            let incompatibleData = await FixtureCommandDispatcher().reply(id: id)
            let incompatibleEnvelope = try PropertyListSerialization.propertyList(from: incompatibleData, format: nil) as! [String: Any]
            let incompatibleFailure = CombinedFailure.decode(incompatibleEnvelope["failure"] as! [String: Any], expectedID: id)!
            check(!FixtureVisits.events.contains("dispatch"), "incompatible outer tuple is still a local rejection")
            if fixtureCandidate {
                check(incompatibleFailure.stage == .authentication && incompatibleFailure.sourceStep == .anisetteFetch &&
                      incompatibleFailure.signingContext["typed_error"] == typed &&
                      incompatibleFailure.signingContext[V3AuthenticationDiagnostics.stateKey] == "trimmed",
                      "incompatible outer response tuple cannot erase decisive local identity failure")
                check(incompatibleFailure.signingContext["auth_response_shape"] == nil &&
                      incompatibleFailure.signingContext["auth_response_mime"] == nil,
                      "incompatible optional auth-response tuple is explicitly trimmed")
            } else {
                check(incompatibleFailure.signingContext["typed_error"] == "sideSignInvalidResponse" &&
                      incompatibleFailure.signingContext["auth_response_shape"] == "jsonArray",
                      "baseline retains original response tuple without inventing new identity diagnosis")
            }
            let negatives: [(String, NSError)] = [
                ("wrong_domain", NSError(domain: "Synthetic.WrongDomain", code: localCode,
                    userInfo: [NSLocalizedDescriptionKey: fixtureSecret])),
                ("unknown_code", NSError(domain: "SideStore.RemoteIdentity", code: 999,
                    userInfo: [NSLocalizedDescriptionKey: fixtureSecret])),
                ("outer_cancellation", NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled,
                    userInfo: [NSUnderlyingErrorKey: local, NSLocalizedDescriptionKey: fixtureSecret]))
            ]
            var negativeRows: [[String: Any]] = []
            for (kind, error) in negatives {
                FixtureVisits.reset()
                FixtureVisits.failingAuthStep = "authenticate"
                FixtureVisits.injectedBeforeDispatch = error
                let data = await FixtureCommandDispatcher().reply(id: id)
                let envelope = try PropertyListSerialization.propertyList(from: data, format: nil) as! [String: Any]
                let failure = CombinedFailure.decode(envelope["failure"] as! [String: Any], expectedID: id)!
                check(!FixtureVisits.events.contains("dispatch"), "local negative control never calls Apple")
                check(failure.signingContext["typed_error"] != typed && !failure.diagnosticCode.contains("-" + token),
                      "wrong domain, unknown code and outer cancellation cannot become remote identity failure")
                check(failure.code == (kind == "outer_cancellation" ? .cancelled : .failed),
                      "cancellation remains primary and unknown finite pairs remain generic")
                check(!failure.technicalDetails.contains(fixtureSecret), "negative-control private userInfo stays local")
                negativeRows.append(["kind": kind, "response": data])
            }
            rows.append(["name": typed, "candidate": fixtureCandidate, "response": retained!,
                         "typed": typed, "token": token, "direct_and_wrapped_verified": true,
                         "negative_controls": negativeRows, "incompatible_response": incompatibleData])
        }
        FixtureVisits.reset()
        // Observer restoration uses actual TaskLocal machinery and a locked sink.
        let outer = LCSigningHTTPObservation()
        try await SideSignPortalDiagnostics.$responseObserver.withValue({ outer.record($0, code: $1) }) {
            _ = await FixtureDispatch.$response.withValue(cases[0].1) { await FixtureCommandDispatcher().reply(id: id) }
            SideSignPortalDiagnostics.responseObserver?(202, "NOT_FOUND")
            check(outer.snapshot().status == 202 && outer.snapshot().providerCode == "NOT_FOUND", "outer response observer restored")
        }
        check(SideSignPortalDiagnostics.responseObserver == nil && SideSignPortalDiagnostics.resultCodeObserver == nil, "no observer leaks after command")
        let bounded = LCSigningHTTPObservation()
        for invalid in [-1, 0, 99, 600, 99999] {
            bounded.record(invalid, code: fixtureSecret)
            check(bounded.snapshot().status == nil && bounded.snapshot().providerCode == nil, "finite metadata rejected")
        }
        // Parallel task-local requests cannot exchange their HTTP/provider code.
        FixtureVisits.reset()
        async let first = FixtureDispatch.$response.withValue(FixtureResponse(body: errorJSON(code: "ENTITY_ERROR"), status: 422, yieldBeforeReply: true)) { await FixtureCommandDispatcher().reply(id: id) }
        async let second = FixtureDispatch.$response.withValue(FixtureResponse(body: errorJSON(code: "FORBIDDEN_ERROR"), status: 403, yieldBeforeReply: true)) { await FixtureCommandDispatcher().reply(id: id) }
        let replies = await [first, second]
        for (index, data) in replies.enumerated() {
            let expectedHTTP = index == 0 ? "422" : "403"
            let expectedCode = index == 0 ? "ENTITY_ERROR" : "FORBIDDEN_ERROR"
            rows.append(["name": "parallel_\(index)", "candidate": fixtureCandidate, "response": data,
                         "http": fixtureCandidate ? expectedHTTP : "unavailable", "provider": fixtureCandidate ? expectedCode : "absent",
                         "server": "unknown", "ordinal": 3, "typed": "sideSignServerReportedError"])
        }
        precondition(CommandLine.arguments.count == 2)
        let output = try PropertyListSerialization.data(fromPropertyList: rows, format: .binary, options: 0)
        try output.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("PASS portal_service_\(fixtureCandidate ? "candidate" : "baseline") cases=\(rows.count)")
    }
}
