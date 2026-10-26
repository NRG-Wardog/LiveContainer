@main struct EarlyRefreshCases {
    static let hostID = "com.kdt.livecontainer"
    static var names: [String] = []
    static func check(_ value: @autoclosure () -> Bool, _ label: String) { precondition(value(), label) }
    static func pass(_ name: String) {
        precondition(!names.contains(name)); names.append(name)
        print("PASS early_refresh_\(fixtureCandidate ? "candidate" : "baseline")_\(name)")
    }
    static func reset() {
        ChainChecks.reset()
        FixtureVisits.reset()
        minimuxer.core.result = .success(true)
        minimuxer.core.releaseGate = nil
        minimuxer.core.networkResult = .init(result: .success(true))
        minimuxer.core.afterReadiness = {}
        V3RemoteRequestLeases.admitted = V3RemoteRequestAdmission()
        V3RemoteRequestLeases.admissionError = nil
        CellularRefreshManager.shared.isEnabled = false
        AuthManager.shared.team = nil
        DatabaseManager.shared.selectedTeam = FixtureDBTeam()
        DatabaseManager.shared.persistentContainer.error = nil
        AppManager.shared.pipelineRunner = PipelineRunner()
    }
    static func run(_ IDs: [String] = [hostID]) async -> ([String: Result<InstalledApp, Error>], CapturedServer) {
        let apps = IDs.map { InstalledApp(bundleIdentifier: $0, name: ChainChecks.canary) }
        let producer = ManifestProducer(apps: apps, runID: ChainChecks.runID)
        let results = try! await producer.refreshThroughActualManager(apps)
        let server = CapturedServer()
        if let failure = results.values.compactMap({ result -> Error? in
            if case .failure(let error) = result { return error }; return nil
        }).first {
            SideStoreClient().reportStructuredRefreshFailure(IntentError(failure), server: server)
        } else {
            SideStoreClient().reportRefreshResult(nil, server: server)
        }
        check(FixtureVisits.beginBatch == 1 && FixtureVisits.endBatch == 1, "balanced transport lease")
        check(server.calls == 1 && server.runID == ChainChecks.runID, "one correlated callback")
        return (results, server)
    }
    static func checkCallbackCompletionBarrier() async {
        reset()
        let gate = FixtureTransportReleaseGate()
        minimuxer.core.releaseGate = gate
        let apps = [InstalledApp(bundleIdentifier: hostID, name: ChainChecks.canary)]
        let producer = ManifestProducer(apps: apps, runID: ChainChecks.runID)
        let pending = Task {
            let results = try await producer.refreshThroughActualManager(apps)
            await gate.markReturned()
            return results
        }
        await gate.waitUntilEntered()
        // Only the pinned baseline emits its actual callback before cleanup.
        // Candidate emits afterward; never wait for its callback while held.
        if !fixtureCandidate { await gate.waitUntilCallbackConsumed() }
        let held = await gate.snapshot()
        check(held.entered && !held.released && !held.returned, "transport release held while fixture result remains pending")
        check(held.consumed == !fixtureCandidate, "actual variant callback ordering retained")
        check(FixtureVisits.beginBatch == 1 && FixtureVisits.endBatch == 0, "held transport lease not reported balanced early")
        await gate.release()
        let results = try! await pending.value
        if case .success = results[hostID]! {} else { preconditionFailure("held inert refresh changed result") }
        let completed = await gate.snapshot()
        check(completed.consumed && completed.released && completed.returned, "callback and explicit release precede fixture return")
        check(FixtureVisits.beginBatch == 1 && FixtureVisits.endBatch == 1, "balanced transport lease after task join")
        minimuxer.core.releaseGate = nil
    }
    static func manifestFailure(_ server: CapturedServer, appID: String = hostID) -> CombinedFailure {
        let payload = try! PropertyListSerialization.propertyList(from: server.verification!, format: nil) as! [String: Any]
        let manifest = payload["liveContainerAutoRefreshVerification"] as! [String: Any]
        check(manifest["run_id"] as? String == ChainChecks.runID, "matching manifest run")
        let entry = (manifest["results"] as! [[String: Any]]).first { $0["bundle_id"] as? String == appID }!
        check(entry["success"] as? Bool == false, "failure never becomes success")
        return CombinedFailure.decode(entry["failure"] as! [String: Any], expectedID: ChainChecks.runID)!
    }
    static func terminal(_ server: CapturedServer) async -> (CombinedFailure, String, [String: Any]) {
        // Prove evidence is imported from the actual callback payload.
        V3SharedAppGroup.defaults.removeObject(forKey: "liveContainerAutoRefreshVerification")
        return ChainChecks.terminal(await CurrentHandler().deliver(server.error,
            runID: ChainChecks.runID, verification: server.verification))
    }
    static func checkGeneric(_ failure: CombinedFailure, _ copy: String) {
        check(failure.stage == .refreshVerification && failure.code == .failed, "baseline VERIFY C11")
        check(failure.sourceStep == nil && failure.safeCause == nil, "baseline unknown source/cause")
        check(failure.underlyingDomain == "redacted" && failure.underlyingCode == 0, "baseline redacted underlying")
        check(failure.signingContext.isEmpty, "baseline finite category absent")
        check(copy.contains("diagnostic_code=SS-VERIFY-C11") && copy.contains("source_step=unknown"), "actual Copy matches generic signature")
    }
    static func main() async {
        // Injection is at inert native core.isReady only. Everything from the
        // real isMinimuxerReady/map through real refresh/perform to Copy executes.
        let readinessCases: [(String, MinimuxerError, String)] = [
            ("not_started", .notStarted(ChainChecks.canary), "minimuxerNotStarted"),
            ("no_device", .noDevice(ChainChecks.canary), "noDevice"),
            ("no_connection", .noConnection(ChainChecks.canary), "noConnection"),
            ("not_reachable", .notReachable(ChainChecks.canary), "notReachable"),
            ("no_vpn", .noVPN(ChainChecks.canary), "noVPN"),
            ("invalid_vpn", .invalidVPN(ChainChecks.canary), "invalidVPN"),
            ("pairing_not_loaded", .pairingNotLoaded(ChainChecks.canary), "pairingNotComplete"),
            ("invalid_parameters", .connectionModeNotConfigured(ChainChecks.canary), "invalidParameters"),
            ("unknown_native", .opaque(ChainChecks.canary), "unknownOperation")
        ]
        for (name, native, expectedKind) in readinessCases {
            reset(); minimuxer.core.result = .failure(native)
            let (_, server) = await run()
            let manifest = manifestFailure(server)
            let result = await terminal(server)
            check(FixtureVisits.readiness == 1 && FixtureVisits.teamLookup == 0 && FixtureVisits.mutation == 0,
                  "readiness fails before team or mutation")
            check(FixtureVisits.readinessNetworkChecks == [true], "unchanged network-check argument")
            check(NSDictionary(dictionary: manifest.wire).isEqual(to: result.0.wire), "exact manifest evidence survives completion")
            if fixtureCandidate {
                check(result.0.stage == .command && result.0.sourceStep?.rawValue == "refreshReadiness", "precise readiness responsibility")
                check(result.0.signingContext["refresh_failure_kind"] == expectedKind, "finite typed category")
                check(result.0.safeCause == nil, "do not invent readiness cause")
                check(result.1.contains("refresh_failure_kind=" + expectedKind), "category reaches actual Copy")
            } else { checkGeneric(result.0, result.1) }
            check(!result.1.contains(ChainChecks.canary), "native details remain private")
            pass("readiness_" + name)
        }

        // Actual resolveActiveTeam guard, not a failure injected at the producer.
        // Host filtering leaves zero operations, but team lookup must still run.
        for target in [hostID, "com.fixture.nonhost"] {
            reset(); DatabaseManager.shared.selectedTeam = nil
            let (_, server) = await run([target])
            _ = manifestFailure(server, appID: target)
            let result = await terminal(server)
            check(FixtureVisits.readiness == 1 && FixtureVisits.teamLookup == 1 && FixtureVisits.mutation == 0,
                  "actual missing-team guard visited, mutation forbidden")
            if fixtureCandidate {
                check(result.0.stage == .authentication && result.0.sourceStep?.rawValue == "refreshPreflight", "finite preflight scope")
                check(result.0.signingContext["refresh_failure_kind"] == "notAuthenticated", "actual missing-team enum preserved")
                check(result.0.safeCause == nil, "no unproved session or credential cause")
            } else { checkGeneric(result.0, result.1) }
            pass(target == hostID ? "missing_team_host_filtered" : "missing_team_nonhost")
        }

        reset(); DatabaseManager.shared.persistentContainer.error = NSError(domain: ChainChecks.canary, code: 918,
            userInfo: [NSLocalizedDescriptionKey: ChainChecks.canary, "token": ChainChecks.canary])
        let (_, unknownServer) = await run()
        let unknown = await terminal(unknownServer)
        check(unknown.0.underlyingDomain == "redacted" && unknown.0.underlyingCode == 0, "unknown DB domain/code private")
        check(unknown.0.safeCause == nil && unknown.0.signingContext.isEmpty, "unknown DB error not mislabeled as auth")
        if fixtureCandidate {
            check(unknown.0.stage == .command && unknown.0.sourceStep?.rawValue == "refreshPreflight", "only observed unknown phase retained")
        } else { checkGeneric(unknown.0, unknown.1) }
        check(!unknown.1.contains(ChainChecks.canary), "unknown error body private")
        pass("unknown_preflight_error_privacy")

        reset(); DatabaseManager.shared.persistentContainer.error = CancellationError()
        let (cancelledResults, cancelledServer) = await run()
        if case .failure(let error) = cancelledResults[hostID]! { check(error is CancellationError, "cancellation identity") }
        else { preconditionFailure("cancellation became success") }
        let cancelled = await terminal(cancelledServer)
        check(cancelled.0.code == .cancelled && cancelled.0.sourceStep == nil, "cancellation not annotated")
        check(FixtureVisits.mutation == 0, "cancelled preflight no mutation")
        pass("cancellation_identity")

        reset(); DatabaseManager.shared.persistentContainer.error = NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled)
        let (_, urlCancelledServer) = await run()
        let urlCancelled = await terminal(urlCancelledServer)
        check(urlCancelled.0.code == .cancelled && urlCancelled.0.sourceStep == nil, "URL cancellation not annotated")
        check(FixtureVisits.mutation == 0, "cancelled DB operation no mutation")
        pass("url_cancellation_identity")

        reset(); minimuxer.core.result = .failure(.invalidPairing(1, ChainChecks.canary))
        let (_, pairingServer) = await run()
        let pairing = await terminal(pairingServer)
        check(pairing.0.stage == .pairing && pairing.0.safeCause == .invalidPairingFile, "existing precise pairing marker wins")
        check(pairing.0.sourceStep?.rawValue == (fixtureCandidate ? "refreshReadiness" : nil), "only observed readiness source added")
        pass("existing_pairing_evidence")

        reset()
        let known = ChainChecks.rich()
        DatabaseManager.shared.persistentContainer.error = known
        let (knownResults, knownServer) = await run()
        if case .failure(let error) = knownResults[hostID]!, let actual = error as? CombinedFailure {
            check(NSDictionary(dictionary: known.wire).isEqual(to: actual.wire), "preexisting envelope identity preserved")
        } else { preconditionFailure("known envelope transformed") }
        let retained = await terminal(knownServer)
        check(NSDictionary(dictionary: known.wire).isEqual(to: retained.0.wire), "known envelope end-to-end identity")
        pass("existing_structured_failure_identity")

        reset()
        let precise = lcStructuredSigningFailure(OperationError.invalidParameters(ChainChecks.canary),
            stage: "provisioning", sourceStep: "registerDevice")
        DatabaseManager.shared.persistentContainer.error = precise
        let (_, preciseServer) = await run()
        let preservedPrecise = await terminal(preciseServer)
        check(preservedPrecise.0.stage == .provisioning && preservedPrecise.0.sourceStep == .registerDevice,
              "existing more precise NSError markers win")
        pass("existing_nserror_markers")

        // The helper is deliberately limited to pure refresh batches.
        for mixed in [false, true] {
            reset(); minimuxer.core.result = .failure(.noDevice(ChainChecks.canary))
            let app = InstalledApp(bundleIdentifier: "com.fixture.install")
            var operations: [AppOperation] = [.install(app)]
            if mixed { operations.append(.refresh(InstalledApp(bundleIdentifier: hostID))) }
            let group = RefreshGroup(dbContext: NSManagedObjectContext())
            do {
                _ = try await AppManager.shared.pipelineRunner.perform(operations,
                    handler: PipelineExecutionHandler(), group: group)
                preconditionFailure("readiness failure expected")
            } catch {
                guard let original = error as? OperationError, case .noDevice = original else {
                    preconditionFailure("non-refresh batch error changed")
                }
            }
            check(FixtureVisits.readiness == 1 && FixtureVisits.teamLookup == 0 && FixtureVisits.mutation == 0,
                  "unrelated failure behavior unchanged")
            pass(mixed ? "mixed_batch_unchanged" : "nonrefresh_batch_unchanged")
        }

        // Correlation protections remain in force with newly annotated failures.
        reset(); DatabaseManager.shared.selectedTeam = nil
        let (_, staleServer) = await run()
        V3SharedAppGroup.defaults.set(ChainChecks.otherID, forKey: "liveContainerAutoRefreshActiveRequestID")
        let outer = CombinedFailure.fromEncodedString(staleServer.error!, expectedID: ChainChecks.runID)!
        let wrongRequest = await CurrentHandler().deliver(staleServer.error, runID: ChainChecks.runID,
            verification: staleServer.verification)
        if case .failure(let error) = wrongRequest, let actual = error as? CombinedFailure {
            check(NSDictionary(dictionary: outer.wire).isEqual(to: actual.wire), "wrong request cannot import manifest failure")
        } else { preconditionFailure("correlation control") }
        pass("current_request_gate")

        reset(); DatabaseManager.shared.selectedTeam = nil
        let (_, wrongRunServer) = await run()
        let staleData = ChainChecks.mutated(wrongRunServer) { payload in
            ChainChecks.mutateManifest(&payload) { manifest in manifest["run_id"] = ChainChecks.otherID }
        }
        let expectedOuter = CombinedFailure.fromEncodedString(wrongRunServer.error!, expectedID: ChainChecks.runID)!
        let wrongRun = await CurrentHandler().deliver(wrongRunServer.error, runID: ChainChecks.runID, verification: staleData)
        if case .failure(let error) = wrongRun, let actual = error as? CombinedFailure {
            check(NSDictionary(dictionary: expectedOuter.wire).isEqual(to: actual.wire), "stale run cannot import failure")
        } else { preconditionFailure("manifest run control") }
        pass("current_run_gate")

        // Positive control verifies this patch does not skip readiness/team checks.
        for cellular in [false, true] {
            reset(); CellularRefreshManager.shared.isEnabled = cellular
            let (results, _) = await run()
            if case .success = results[hostID]! {} else { preconditionFailure("inert success changed") }
            check(FixtureVisits.networkReadiness == (fixtureCandidate && !cellular ? 1 : 0), "candidate really observes owned network before native check")
            check(FixtureVisits.readiness == (cellular ? 0 : 1), "original cellular readiness policy retained")
            check(FixtureVisits.teamLookup == 1 && FixtureVisits.mutation == 1, "team guard remains on success")
            check(FixtureVisits.mismatchPrompt == 0, "refresh never gains bundle mismatch prompt")
            if !cellular { await checkCallbackCompletionBarrier() }
            pass(cellular ? "cellular_existing_policy" : "success_both_checks_retained")
        }
        // Additional controls within the retained success/readiness contract.
        // A network observation is not device readiness; revoked ownership is
        // rechecked after native readiness and before preflight/mutation.
        if fixtureCandidate {
            reset(); minimuxer.core.networkResult = .init(result: .success(false))
            let (networkRejected, _) = await run()
            if case .failure = networkRejected[hostID]! {} else { preconditionFailure("false network proof accepted") }
            check(FixtureVisits.networkReadiness == 1 && FixtureVisits.readiness == 0 && FixtureVisits.mutation == 0,
                  "false network proof cannot reach native readiness or mutation")
            reset(); minimuxer.core.result = .success(false)
            let (nativeRejected, _) = await run()
            if case .failure = nativeRejected[hostID]! {} else { preconditionFailure("false native proof accepted") }
            check(FixtureVisits.networkReadiness == 1 && FixtureVisits.readiness == 1 && FixtureVisits.mutation == 0,
                  "network success cannot substitute for true native readiness")
            reset(); minimuxer.core.afterReadiness = { V3RemoteRequestLeases.admissionError = CancellationError() }
            let (cancelledOwner, _) = await run()
            if case .failure(let error) = cancelledOwner[hostID]! {
                check(error is CancellationError, "post-native cancellation identity preserved")
            } else { preconditionFailure("cancelled owner accepted") }
            check(FixtureVisits.readiness == 1 && FixtureVisits.mutation == 0,
                  "post-native cancellation never dispatches mutation")
            reset(); minimuxer.core.afterReadiness = { V3RemoteRequestLeases.admissionError = OperationError.timedOut }
            let (ownerRejected, _) = await run()
            if case .failure = ownerRejected[hostID]! {} else { preconditionFailure("revoked owner accepted") }
            check(FixtureVisits.networkReadiness == 1 && FixtureVisits.readiness == 1 && FixtureVisits.teamLookup == 0 && FixtureVisits.mutation == 0,
                  "post-native admission rejection cannot reach preflight or mutation")
        }
        reset()
        AuthManager.shared.team = ALTTeam(identifier: "CACHED_FIXTURE_TEAM", name: "fixture", type: "fixture")
        let (cachedResults, _) = await run()
        if case .success = cachedResults[hostID]! {} else { preconditionFailure("cached team success changed") }
        check(FixtureVisits.readiness == 1 && FixtureVisits.teamLookup == 0 && FixtureVisits.mutation == 1,
              "actual existing team cache behavior unchanged")
        pass("cached_team_existing_policy")
        let report: [String: Any] = ["schema": "early-refresh-cases-v1", "variant": fixtureCandidate ? "candidate" : "baseline",
            "status": "pass", "case_count": names.count, "cases": names,
            "native_provider_executed": false, "network_executed": false]
        precondition(CommandLine.arguments.count == 2)
        try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("PASS early_refresh_actual_appmanager_pipeline_source_chain cases=\(names.count)")
    }
}
