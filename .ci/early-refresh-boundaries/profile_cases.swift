
@main struct ProfilePreconditionCases {
    static var names: [String] = []
    static func check(_ value: @autoclosure () -> Bool, _ label: String) { precondition(value(), label) }
    static func pass(_ name: String) { precondition(!names.contains(name)); names.append(name) }
    static func boundary(_ error: Error, step: PipelineStep = .fetchProvisioningProfiles,
                         operation: AppOperation? = nil) -> Error {
        do { try fixturePipelineBoundary(error, step: step,
            appOperation: operation ?? .refresh(InstalledApp(bundleIdentifier: ChainChecks.appID))) }
        catch { return error }
        preconditionFailure("expected failure")
    }
    static func terminal(_ error: Error) async -> (CombinedFailure, String, [String: Any]) {
        ChainChecks.reset()
        let app = InstalledApp(bundleIdentifier: ChainChecks.appID, name: ChainChecks.canary)
        let mapped = getMappedError(for: .refresh(app), error: error)
        let server = ChainChecks.producer(mapped)
        V3SharedAppGroup.defaults.removeObject(forKey: "liveContainerAutoRefreshVerification")
        return ChainChecks.terminal(await CurrentHandler().deliver(server.error,
            runID: ChainChecks.runID, verification: server.verification))
    }
    static func main() async {
        let known: [(String, String)] = [
            ("FetchProvisioningProfilesOperation: context.targetAppBundle is nil", "missingTargetAppBundle"),
            ("Cannot update features for unknown team type.", "unknownTeamType"),
            ("Application group 'group.$(APP_GROUP_IDENTIFIER)' contains raw placeholder '$(APP_GROUP_IDENTIFIER)'.", "unresolvedAppGroupPlaceholder"),
            ("Missing progress weight for step 'fetchProvisioningProfiles' in steps list", "missingProgressWeight"),
            ("Invalid maxReuse (0) for step 'fetchProvisioningProfiles' in steps list", "invalidProgressReuse"),
            ("Missing PipelineStep mapping for FetchProvisioningProfilesOperation", "missingPipelineStepMapping")
        ]
        for (text, reason) in known {
            let original = OperationError.invalidParameters(text)
            let output = await terminal(boundary(original))
            check(original == .invalidParameters(text), "original OperationError API retained")
            check(output.0.stage == .signing && output.0.sourceStep == .provisioningProfileFetch, "profile boundary")
            check(output.0.safeCause == .unknownSigningCause, "no invented portal cause")
            check(output.0.signingContext["local_precondition"] == reason, "finite local precondition survives")
            check(output.1.contains("local_precondition=" + reason), "finite reason reaches actual Copy")
            check(output.0.message != "The exact signing cause could not be safely identified.", "local wording available")
            check(!output.1.contains(text) && !output.1.contains("group.$("), "raw guard or group never exported")
            pass(reason)
        }
        let unknowns = [ChainChecks.canary,
            "Application group 'secret\n$(APP_GROUP_IDENTIFIER)' contains raw placeholder '$(APP_GROUP_IDENTIFIER)'.",
            "Invalid maxReuse (1) for step 'fetchProvisioningProfiles' in steps list",
            "Missing progress weight for step 'resignApp' in steps list"]
        for (index, text) in unknowns.enumerated() {
            let output = await terminal(boundary(OperationError.invalidParameters(text)))
            check(output.0.signingContext["local_precondition"] == nil, "unknown is not a local cause")
            check(output.0.signingContext["refresh_failure_kind"] == "invalidParameters", "primary kind retained")
            check(!output.1.contains(text) && !output.1.contains("local_precondition="), "unknown private")
            pass("unknown_local_\(index)")
        }
        let masquerade = NSError(domain: "SideSign.ServerError", code: 42,
            userInfo: [NSLocalizedDescriptionKey: known[0].0])
        check(lcRefreshFailureFacts(masquerade, sourceStep: "provisioningProfileFetch").isEmpty, "NSError text cannot become typed local guard")
        pass("wrong_error_type")
        let wrongStep = await terminal(boundary(OperationError.invalidParameters(known[0].0), step: .resignApp))
        check(wrongStep.0.signingContext["local_precondition"] == nil, "wrong step remains primary error")
        pass("wrong_step")
        let install = boundary(OperationError.invalidParameters(known[0].0), operation: .install(InstalledApp()))
        let installed = CombinedFailure.capture(install, operation: "install", stage: .command, id: ChainChecks.runID)
        check(installed.signingContext["local_precondition"] == nil, "install unchanged")
        pass("nonrefresh_scope")

        let primary = CombinedFailure(operation: "refresh", stage: .signing, id: ChainChecks.runID,
            safeCause: .unknownSigningCause, sourceStep: .provisioningProfileFetch,
            signingContext: ["refresh_failure_kind": "invalidParameters", "extension_count": "0"])
        for (index, invalid) in [ChainChecks.canary as Any, 42, true, ["nested": ChainChecks.canary]].enumerated() {
            var wire = primary.wire
            var context = wire["signingContext"] as! [String: Any]
            context["local_precondition"] = invalid; wire["signingContext"] = context
            let decoded = CombinedFailure.decode(wire, expectedID: ChainChecks.runID)!
            check(NSDictionary(dictionary: decoded.wire).isEqual(to: primary.wire), "optional observation cannot discard primary")
            let output = await terminal(decoded)
            check(!output.1.contains(ChainChecks.canary) && !output.1.contains("local_precondition="), "invalid optional not copied")
            pass("optional_wire_primary_preserved_\(index)")
        }
        for (index, change) in [("operation", "install"), ("stage", "command"), ("sourceStep", "localCodeSigning")].enumerated() {
            var expected = primary.wire; expected[change.0] = change.1
            var supplied = expected; var context = supplied["signingContext"] as! [String: String]
            context["local_precondition"] = "missingTargetAppBundle"; supplied["signingContext"] = context
            let decoded = CombinedFailure.decode(supplied, expectedID: ChainChecks.runID)!
            check(NSDictionary(dictionary: decoded.wire).isEqual(to: expected), "wrong-scope observation stripped, primary preserved")
            pass("optional_wrong_scope_\(index)")
        }
        for (kind, error) in [("noVPN", OperationError.noVPN(reason: ChainChecks.canary)),
                              ("invalidVPN", OperationError.invalidVPN(reason: ChainChecks.canary))] {
            let annotated = V3RefreshEarlyFailureBoundary.readiness.preserving(error,
                operations: [.refresh(InstalledApp(bundleIdentifier: ChainChecks.appID))])
            let output = await terminal(annotated)
            check(output.0.sourceStep == .refreshReadiness && output.0.signingContext["refresh_failure_kind"] == kind, "readiness evidence")
            check(output.0.message.contains("local VPN connection"), "cautious VPN guidance")
            check(!output.0.message.lowercased().contains("switched off"), "does not assert VPN off")
            check(output.1.contains("refresh_failure_kind=" + kind), "VPN observation reaches Copy")
            pass("vpn_" + kind)
        }
        for (index, wrong) in [
            CombinedFailure(operation: "install", stage: .command, id: ChainChecks.runID, sourceStep: .refreshReadiness, signingContext: ["refresh_failure_kind": "noVPN"]),
            CombinedFailure(operation: "refresh", stage: .command, id: ChainChecks.runID, sourceStep: .refreshPreflight, signingContext: ["refresh_failure_kind": "invalidVPN"]),
            CombinedFailure(operation: "refresh", stage: .command, id: ChainChecks.runID, sourceStep: .refreshReadiness, signingContext: ["refresh_failure_kind": "noConnection"])
        ].enumerated() {
            check(!wrong.message.contains("local VPN connection"), "VPN message requires precise observed scope")
            pass("vpn_wrong_scope_\(index)")
        }
        precondition(names.count == 25)
        let report: [String: Any] = ["schema": "profile-preconditions-cases-v1", "status": "pass",
            "cases": names, "case_count": names.count, "native_provider_executed": false, "network_executed": false]
        precondition(CommandLine.arguments.count == 2)
        try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
    }
}
