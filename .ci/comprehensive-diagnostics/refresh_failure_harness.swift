@main
struct RefreshFailureCases {
    static let runID = "00000000-0000-0000-0000-000000000001"
    static let requestID = "00000000-0000-0000-0000-000000000002"
    static let otherID = "00000000-0000-0000-0000-000000000003"
    static let appID = "com.example.synthetic"
    static let canary = "SECRET_CANARY_ACCOUNT_TOKEN_PAIRING_012345"
    static var names: [String] = []

    static func check(_ condition: @autoclosure () -> Bool, _ name: String) {
        precondition(condition(), name)
    }
    static func pass(_ name: String) { precondition(!names.contains(name)); names.append(name); print("PASS refresh_failure_\(name)") }
    static func encoded(_ value: [String: Any]) -> Data {
        try! PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0)
    }
    static func reset(request: String = requestID) {
        V3SharedAppGroup.defaults = UserDefaults()
        V3SharedAppGroup.available = true
        FixtureScheduler.activeRun = UUID(uuidString: runID)
        let defaults = V3SharedAppGroup.defaults
        defaults.set(runID, forKey: "liveContainerAutoRefreshExpectedRunID")
        defaults.set(runID, forKey: "liveContainerAutoRefreshActiveRunID")
        defaults.set(runID, forKey: "liveContainerAutoRefreshUncertainMutationRunID")
        if !request.isEmpty {
            defaults.set(request, forKey: "liveContainerAutoRefreshActiveRequestID")
            defaults.set(runID, forKey: "liveContainerAutoRefreshActiveManualOriginRunID")
            defaults.set("home", forKey: "liveContainerAutoRefreshActiveManualOrigin")
        }
        defaults.set([runID: ["run_id": runID, "request_id": request, "source": "manual", "origin": "home", "state": "running", "network_preflight": "passed"]], forKey: "liveContainerAutoRefreshRunLedger")
    }
    static func rich(_ step: CombinedFailure.SourceStep = .localCodeSigning) -> CombinedFailure {
        CombinedFailure(operation: "refresh", stage: .signing, id: runID,
            underlying: NSError(domain: NSPOSIXErrorDomain, code: 13,
                userInfo: [NSLocalizedDescriptionKey: canary]),
            retryable: false, safeCause: .certificateUnavailable, sourceStep: step,
            signingContext: ["refresh_failure_kind": "certificateChanged"])
    }
    static func producer(_ failure: Error) -> CapturedServer {
        let app = InstalledApp(bundleIdentifier: appID, name: canary)
        let producer = ManifestProducer(apps: [app], runID: runID)
        producer.persistAutomaticRefreshVerification(results: [appID: .failure(failure)], attemptedAppIDs: [appID])
        let server = CapturedServer()
        SideStoreClient().reportStructuredRefreshFailure(IntentError(failure), server: server)
        check(server.calls == 1 && server.runID == runID, "actual callback emitted once")
        check(server.error != nil && server.verification != nil, "error and manifest coexist")
        let outer = CombinedFailure.fromEncodedString(server.error!, expectedID: runID)!
        check(outer.stage == .command && outer.safeCause == nil && outer.sourceStep == nil, "IntentError reproduces wrapper loss")
        check(outer.underlyingDomain == "redacted", "sanitizer rejects bridged type domain")
        return server
    }
    static func terminal(_ result: Result<Void, Error>) -> (CombinedFailure, String, [String: Any]) {
        guard case .failure(let error) = result else { preconditionFailure("failure must remain failure") }
        let failure = FixtureScheduler.structuredRefreshFailure(error, runID: runID)
        check(FixtureScheduler.markFailed(runID: runID, source: "manual", health: "REFRESH_FAILED", failure: failure, message: failure.safeMessage), "terminal claim")
        let record = FixtureScheduler.runLedger()[runID]!
        check(record["state"] as? String == "failed", "terminal state remains failed")
        check(record["manifest"] == nil, "real terminal compaction removes full manifest")
        check(V3SharedAppGroup.defaults.string(forKey: "liveContainerAutoRefreshActiveRunID") == nil, "real active-run cleanup")
        let copied = V3DiagnosticCopy.details(visibleMessage: record["message"] as? String ?? "", technical: V3RefreshAllFailureDiagnostics.text(requestID: requestID, runID: runID, record: record)!)
        check(!copied.contains(canary), "copy never contains secret canary")
        return (failure, copied, record)
    }
    static func mutated(_ server: CapturedServer, _ body: (inout [String: Any]) -> Void) -> Data {
        var payload = try! PropertyListSerialization.propertyList(from: server.verification!, format: nil) as! [String: Any]
        body(&payload)
        return encoded(payload)
    }
    static func mutateManifest(_ payload: inout [String: Any], _ body: (inout [String: Any]) -> Void) {
        var manifest = payload["liveContainerAutoRefreshVerification"] as! [String: Any]
        body(&manifest)
        payload["liveContainerAutoRefreshVerification"] = manifest
    }
    static func rejection(_ name: String, verification: (CapturedServer) -> Data?,
                          prepare: () -> Void = {}) async {
        reset()
        let server = producer(rich())
        prepare()
        let result = await CurrentHandler().deliver(server.error, runID: runID, verification: verification(server))
        guard case .failure(let error) = result, let failure = error as? CombinedFailure else { preconditionFailure(name) }
        let expected = CombinedFailure.fromEncodedString(server.error!, expectedID: runID)!
        check(NSDictionary(dictionary: failure.wire).isEqual(to: expected.wire), "\(name): exact outer identity preserved")
        pass(name)
    }
    static func main() async {
        // This exact delivered callback must fail the preservation assertion.
        reset()
        var server = producer(rich())
        let old = terminal(await DeliveredHandler().deliver(server.error, runID: runID, verification: server.verification))
        check(old.1.contains("diagnostic_code=SS-CMD-C11") && old.1.contains("source_step=unknown"), "delivered generic signature reproduced")
        check(old.2["manifest_run_id"] as? String == runID, "matching manifest existed before loss")
        pass("delivered_generic_wrapper_reproduced")

        reset()
        server = producer(rich())
        // Delete shared manifest to prove the actual callback payload, not the
        // coincidentally shared original, supplies the recovered evidence.
        V3SharedAppGroup.defaults.removeObject(forKey: "liveContainerAutoRefreshVerification")
        let current = terminal(await CurrentHandler().deliver(server.error, runID: runID, verification: server.verification))
        check(current.0.sourceStep == .localCodeSigning && current.0.safeCause == .certificateUnavailable, "current preserves cause")
        check(current.1.contains("source_step=localCodeSigning") && current.1.contains("underlying_domain=NSPOSIXErrorDomain") && current.1.contains("underlying_code=13") && current.1.contains("retryable=false"), "actual copy preserves semantic fields")
        check(current.0.signingContext["refresh_failure_kind"] == "certificateChanged", "typed refresh kind survives host and ledger")
        let beforeCopy = V3DiagnosticCopy.details(visibleMessage: current.0.safeMessage,
            technical: BeforeKindRefreshDiagnostics.text(requestID: requestID, runID: runID, record: current.2)!)
        check(!beforeCopy.contains("refresh_failure_kind="), "first CI renderer reproduces finite-kind omission")
        pass("copy_kind_omission_reproduced")
        check(current.1.contains("refresh_failure_kind=certificateChanged"), "typed refresh kind reaches Copy")
        let durable = V3SharedAppGroup.defaults.dictionary(forKey: "liveContainerAutoRefreshCurrentRunFailure")!
        check(durable["source_step"] as? String == "localCodeSigning", "durable current failure records source")
        check(current.1.contains(current.0.technicalDetails), "Copy reuses complete canonical safe details")
        pass("actual_manifest_callback_ledger_copy")

        reset()
        let cause = V3ProvisioningCauseDiagnostic(encoded: "pc1|registerDevice|0|0|0|registerDevice,portal,invalidDeviceID,-,-,-,-,unobserved,unavailable,unavailable,-,-,0")!
        let provisioning = CombinedFailure(operation: "refresh", stage: .provisioning, id: runID,
            sourceStep: .registerDevice, signingContext: [V3ProvisioningCauseDiagnostic.contextKey: cause.encoded])
        server = producer(provisioning)
        let structured = terminal(await CurrentHandler().deliver(server.error, runID: runID, verification: server.verification))
        check(structured.1.contains(cause.technicalDetails), "structured provisioning cause survives complete Copy chain")
        check(structured.1.contains("case=invalidDeviceID"), "second legitimate structured cause is visible")
        let priorStructured = BeforeKindRefreshDiagnostics.text(requestID: requestID, runID: runID, record: structured.2)!
        check(!priorStructured.contains("provisioning_cause_schema="), "first CI renderer reproduces structured snapshot omission")
        pass("copy_structured_snapshot_preserved")

        for row in refreshBoundaryFixtureCases() {
            reset(); server = producer(row.error)
            let value = terminal(await CurrentHandler().deliver(server.error, runID: runID, verification: server.verification))
            check(value.0.sourceStep == row.expectedStep, "actual boundary is preserved")
            check(value.1.contains("source_step=\(row.expectedStep.rawValue)"), "actual native mapper boundary survives copy")
            check(value.1.contains("refresh_failure_kind=invalidParameters"), "actual typed native error survives copy")
            check(!value.1.contains("SECRET_PROVIDER_PAYLOAD_AND_PATH"), "native associated text remains private")
            pass(row.name)
        }
        // These certificate list operations use the actual portal read route,
        // but deliberately do not masquerade as refresh-manifest failures.
        for row in try! await certificatePortalBoundaryFixtureCases() {
            let captured = CombinedFailure.capture(row.error, operation: "certPortalList", stage: .signing, id: runID)
            let wire = try! PropertyListSerialization.propertyList(from: encoded(captured.wire), format: nil) as! [String: Any]
            let received = CombinedFailure.decode(wire, expectedID: runID)!
            let copy = V3DiagnosticCopy.details(visibleMessage: received.safeMessage, technical: received.technicalDetails)
            check(received.sourceStep == row.expectedStep && copy.contains("source_step=\(row.expectedStep.rawValue)"), "certificate read boundary survives wire/copy")
            check(!copy.contains("SECRET_PROVIDER_PAYLOAD_AND_PATH"), "certificate native text remains private")
            pass(row.name)
        }
        try! RefreshFailureBoundaryHarness.main()
        pass("finite_boundary_invariants")
        await rejection("invalid_refresh_failure_kind", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; var wire = entries[0]["failure"] as! [String: Any]; wire["signingContext"] = ["refresh_failure_kind": canary]; entries[0]["failure"] = wire; manifest["results"] = entries
        } } })
        await rejection("missing_payload", verification: { _ in nil })
        await rejection("invalid_plist", verification: { _ in Data([0, 1, 2]) })
        await rejection("oversized_payload", verification: { _ in Data(repeating: 0, count: 262145) })
        await rejection("stale_manifest", verification: { mutated($0) { mutateManifest(&$0) { $0["run_id"] = otherID } } })
        await rejection("incomplete_manifest", verification: { mutated($0) { mutateManifest(&$0) { $0["expected_ids"] = [appID, "com.example.missing"] } } })
        await rejection("duplicate_target", verification: { mutated($0) { mutateManifest(&$0) { $0["expected_ids"] = [appID, appID] } } })
        await rejection("malformed_boolean", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; entries[0]["success"] = 0; manifest["results"] = entries
        } } })
        await rejection("wrong_failure_run", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; var wire = entries[0]["failure"] as! [String: Any]; wire["correlationID"] = otherID; entries[0]["failure"] = wire; manifest["results"] = entries
        } } })
        await rejection("wrong_failure_operation", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; var wire = entries[0]["failure"] as! [String: Any]; wire["operation"] = "install"; entries[0]["failure"] = wire; manifest["results"] = entries
        } } })
        await rejection("invalid_failure", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; var wire = entries[0]["failure"] as! [String: Any]; wire["rawSecret"] = canary; entries[0]["failure"] = wire; manifest["results"] = entries
        } } })
        await rejection("missing_failure_no_raw_fallback", verification: { mutated($0) { mutateManifest(&$0) { manifest in
            var entries = manifest["results"] as! [[String: Any]]; entries[0].removeValue(forKey: "failure"); entries[0]["error"] = canary; manifest["results"] = entries
        } } })
        await rejection("contradictory_handoff", verification: { mutated($0) { mutateManifest(&$0) { $0["host_handoff"] = true } } })
        await rejection("wrong_active_run", verification: { $0.verification }, prepare: { V3SharedAppGroup.defaults.set(otherID, forKey: "liveContainerAutoRefreshActiveRunID") })
        await rejection("wrong_expected_run", verification: { $0.verification }, prepare: { V3SharedAppGroup.defaults.set(otherID, forKey: "liveContainerAutoRefreshExpectedRunID") })
        await rejection("wrong_active_request", verification: { $0.verification }, prepare: { V3SharedAppGroup.defaults.set(otherID, forKey: "liveContainerAutoRefreshActiveRequestID") })
        await rejection("missing_ledger", verification: { $0.verification }, prepare: { V3SharedAppGroup.defaults.removeObject(forKey: "liveContainerAutoRefreshRunLedger") })
        await rejection("terminal_ledger", verification: { $0.verification }, prepare: {
            var record = FixtureScheduler.runLedger()[runID]!; record["state"] = "failed"; FixtureScheduler.saveRunRecord(record, runID: runID)
        })
        reset(); server = producer(rich())
        let transport = CombinedFailure(operation: "refresh", stage: .xpcConnection, code: .interrupted, id: runID, retryable: true)
        var result = await CurrentHandler().deliver(transport.encodedString, runID: runID, verification: server.verification)
        guard case .failure(let transportError) = result, let retained = transportError as? CombinedFailure else { preconditionFailure("transport") }
        check(NSDictionary(dictionary: retained.wire).isEqual(to: transport.wire), "concrete transport is not replaced")
        pass("concrete_transport_retained")
        reset(); server = producer(rich())
        result = await CurrentHandler().deliver("untyped " + canary, runID: runID, verification: server.verification)
        guard case .failure(let malformedError) = result, let unknown = malformedError as? CombinedFailure else { preconditionFailure("untyped") }
        check(unknown.sourceStep == nil && unknown.stage == .command && !unknown.safeMessage.contains(canary), "untyped callback not promoted or copied")
        pass("untyped_outer_retained")
        for launchMismatch in [false, true] {
            reset(); server = producer(rich())
            let handler = CurrentHandler()
            _ = await handler.deliver(server.error, runID: runID, verification: server.verification, wrongRun: launchMismatch ? nil : otherID, wrongLaunch: launchMismatch ? UUID() : nil)
            check(handler.sawIgnoredCallback, "wrong callback ignored")
            pass(launchMismatch ? "wrong_launch_ignored" : "wrong_callback_run_ignored")
        }
        reset(); server = producer(rich())
        let tainted = mutated(server) { payload in
            payload["rawSecret"] = canary
            mutateManifest(&payload) { manifest in
                manifest["rawSecret"] = canary
                var entries = manifest["results"] as! [[String: Any]]
                entries[0]["error"] = canary; entries[0]["name"] = canary; entries[0]["rawSecret"] = canary
                manifest["results"] = entries
            }
        }
        let safe = terminal(await CurrentHandler().deliver(server.error, runID: runID, verification: tainted))
        let imported = V3SharedAppGroup.defaults.dictionary(forKey: "liveContainerAutoRefreshVerification")!
        check(!String(describing: imported).contains(canary), "imported manifest drops raw text and extra fields")
        check(safe.0.sourceStep == .localCodeSigning, "secret filtering does not erase safe cause")
        check(V3RefreshAllFailureDiagnostics.text(requestID: otherID, runID: runID, record: safe.2) == nil, "Copy rejects wrong request")
        check(V3RefreshAllFailureDiagnostics.text(requestID: requestID, runID: otherID, record: safe.2) == nil, "Copy rejects wrong run")
        pass("secret_canary_and_copy_identity")
        let report: [String: Any] = ["schema": "refresh-failure-cases-v1", "status": "pass", "fake_only": true, "native_provider_executed": false, "cases": names, "case_count": names.count]
        precondition(CommandLine.arguments.count == 2, "cases.json output path required")
        let reportData = try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted])
        try! reportData.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("PASS refresh_failure_actual_source_chain cases=\(names.count)")
    }
}
