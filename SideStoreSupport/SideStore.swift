Warning: truncated output (original token count: 183877)
Total output lines: 13495

//
//  SideStore.swift
//  SideStoreSupport
//
//  Created by s s on 2025/7/20.
//

import Foundation
import AppIntents
import UserNotifications

@available(iOS 17.0, *)
func performIntentRefresh(identifier: String, mangledTypeName: String, intentProgress: Progress) async throws {
    // LC_REFRESH_INTENT_TO_HOST_SCHEDULER_V1: a host shortcut requests work from
    // the host scheduler. Only the scheduler launches the SideStore refresh engine.
    _ = intentProgress
    if UserDefaults.isSideStore() {
        try await SideStoreIntentCaller.shared.callRefreshIntent(mangledTypeName: mangledTypeName)
        return
    }
    try Task.checkCancellation()
    let request = V3ShortcutRefreshRequest.make()
    NotificationCenter.default.post(
        name: Notification.Name("LiveContainerAutoRefreshRunNow"),
        object: nil, userInfo: request.userInfo)
}

@available(iOS 17.0, *)
public struct RefreshAllAppsWidgetIntent: AppIntent, ProgressReportingIntent
{
    public static var title: LocalizedStringResource { "Refresh Apps via Widget" }
    // LC_REFRESH_HOST_INTENT_FOREGROUND_V1: widget requests must execute in the host app.
    public static var openAppWhenRun = true
    public static var isDiscoverable: Bool { false } // Don't show in Shortcuts or Spotlight.
    
    public init() {}
    
    public func perform() async throws -> some IntentResult
    {
        try await performIntentRefresh(identifier: "RefreshAllAppsWidgetIntent", mangledTypeName: "9SideStore26RefreshAllAppsWidgetIntentV", intentProgress: progress)
        return .result(dialog: "Refresh All was requested in LiveContainer. Check Refresh History for the run result.")
    }
}

@available(iOS 17.0, *)
public struct RefreshAllAppsIntent: AppIntent, CustomIntentMigratedAppIntent, PredictableIntent, ProgressReportingIntent, ForegroundContinuableIntent
{
    public static let intentClassName = "RefreshAllIntent"
    
    public static var title: LocalizedStringResource = "Refresh All Apps"
    public static var openAppWhenRun = true
    public static var description = IntentDescription("Refreshes your sideloaded apps to prevent them from expiring.")
    
    public init() {}
    
    public static var parameterSummary: some ParameterSummary {
        Summary("Refresh All Apps")
    }
    
    public static var predictionConfiguration: some IntentPredictionConfiguration {
        IntentPrediction {
            DisplayRepresentation(
                title: "Refresh All Apps",
                subtitle: ""
            )
        }
    }
    
    public func perform() async throws -> some IntentResult & ProvidesDialog
    {
        try await performIntentRefresh(identifier: "RefreshAllIntent", mangledTypeName: "9SideStore20RefreshAllAppsIntentV", intentProgress: progress)
        return .result(dialog: "Refresh All was requested in LiveContainer. Check Refresh History for the run result.")
    }
    
}


// LC_REFRESH_BRIDGE_V3_BEGIN
/// Dispatch the canonical SideStore guest refresh intent from the host scheduler.
public enum LiveContainerRefreshBridge {
    public static func refreshAllApps(runID: UUID) async throws {
        guard #available(iOS 17.0, *) else {
            throw NSError(domain: "LiveContainerRefresh.UnsupportedOS", code: 17,
                userInfo: [NSLocalizedDescriptionKey: "The embedded automatic refresh bridge requires iOS 17 or later."])
        }
        try Task.checkCancellation()
        try await RefreshHandler.shared.startScheduledRefresh(
            identifier: "RefreshAllIntent",
            mangledName: "9SideStore20RefreshAllAppsIntentV",
            runID: runID.uuidString
        )
        try Task.checkCancellation()
    }
}
// LC_REFRESH_BRIDGE_V3_END

import Foundation
import CoreFoundation

public struct CombinedRefreshTargetPlan: Equatable {
    public let requestedIDs: [String]
    public let attemptedIDs: [String]
    public let skippedIDs: [String]
}

public enum CombinedRefreshTargetPolicy {
    public static func plan(requestedIDs: [String], runningIDs: Set<String>,
                            isCorrelatedManualRun: Bool) -> CombinedRefreshTargetPlan {
        let attempted = isCorrelatedManualRun
            ? requestedIDs
            : requestedIDs.filter { !runningIDs.contains($0) }
        let attemptedSet = Set(attempted)
        return CombinedRefreshTargetPlan(requestedIDs: requestedIDs,
            attemptedIDs: attempted,
            skippedIDs: requestedIDs.filter { !attemptedSet.contains($0) })
    }
}

// LC_REFRESH_METADATA_SANITIZED_V1: never forward arbitrary saved result dictionaries.
// V3_REFRESH_POSTINSTALL_EVIDENCE_V1: bounded observations, never a launch/trust guarantee.
public enum V3RefreshRenewalOutcome: String {
    case renewed, hostProfileAdvanced, profileOnlyRenewed, installedUnchanged, acknowledgedUnverified, mutationUnconfirmed, verificationFailed, unconfirmed

    public var isVerified: Bool { self == .renewed || self == .hostProfileAdvanced || self == .profileOnlyRenewed }
    public var message: String {
        switch self {
        case .profileOnlyRenewed: return "Profile-store expiration advanced while observed profile constraints were kept unchanged. Preservation-mode targets were not re-signed or replaced. This does not verify which profiles the app or its extensions use, future launch, or Keychain access."
        case .hostProfileAdvanced: return "The installed host profile expiration advanced. Other attempted targets, if any, passed profile-store verification. This does not establish the host certificate lifetime or guarantee future app launch or certificate trust."
        case .renewed: return "The expected profiles were found on the device, and the effective validity of every attempted target increased. This does not guarantee future app launch or certificate trust."
        case .installedUnchanged: return "Installation was acknowledged and the expected profiles were found, but expiration did not advance for every target. An imported profile may need renewal by its issuer."
        case .acknowledgedUnverified: return "Installation was acknowledged, but renewed validity could not be confirmed. The operation will not be repeated automatically."
        case .verificationFailed: return "Installation was acknowledged, but the observed profiles or validity did not match the expected result. The operation will not be repeated automatically."
        case .mutationUnconfirmed: return "Installation was requested, but its result could not be confirmed. The operation will not be repeated automatically. Review device status before another action."
        case .unconfirmed: return "The refresh result lacks the evidence needed to confirm renewed validity. Installation is not assumed and the operation will not be repeated automatically."
        }
    }
    public var title: String {
        switch self {
        case .profileOnlyRenewed: return "Profile-only renewal verified"
        case .hostProfileAdvanced: return "Installed host profile expiration advanced"
        case .renewed: return "Profile renewal verified"
        case .installedUnchanged: return "Installed; expiration unchanged"
        case .acknowledgedUnverified, .mutationUnconfirmed, .verificationFailed, .unconfirmed: return "Renewal not confirmed"
        }
    }
}

public struct V3RefreshProfileEvidence {
    public let mutationDispatched: Bool
    public let installAcknowledged: Bool
    public let profileStore: String
    public let renewal: String
    public let certificate: String
    public let reason: String?
    // Legacy wire name: observed constraints retained; not historical-profile authenticity,
    // installed-binary selection, future launch, or Keychain usability attestation.
    public let preservation: String?

    public init?(_ value: Any?) {
        guard let raw = value as? [String: Any],
              Set(raw.keys).isSubset(of: ["version", "mutationDispatched", "installAcknowledged", "profileStore", "renewal", "certificate", "reason", "preservation"]),
              let version = raw["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 1,
              let dispatched = raw["mutationDispatched"] as? NSNumber, CFGetTypeID(dispatched) == CFBooleanGetTypeID(),
              let acknowledged = raw["installAcknowledged"] as? NSNumber, CFGetTypeID(acknowledged) == CFBooleanGetTypeID(),
              let store = raw["profileStore"] as? String, ["matched", "mismatch", "unavailable"].contains(store),
              let renewal = raw["renewal"] as? String, ["extended", "unchanged", "shortened", "unknown"].contains(renewal),
              let certificate = raw["certificate"] as? String, ["valid", "unknown", "invalid"].contains(certificate) else { return nil }
        let preservation = raw["preservation"] as? String
        if raw["preservation"] != nil {
            guard preservation == "authorizationPreserved" else { return nil }
        }
        let reason = raw["reason"] as? String
        if raw["reason"] != nil {
            guard let reason, ["profileAbsent", "profileMismatch", "readbackUnavailable", "baselineUnavailable", "expiryUnchanged", "expiryShortened", "certificateUnknown", "certificateExpired", "certificateRevoked"].contains(reason) else { return nil }
        }
        // Contradictory observations cannot be promoted by a permissive parser.
        guard !acknowledged.boolValue || dispatched.boolValue,
              acknowledged.boolValue || (store == "unavailable" && renewal == "unknown"),
              store == "matched" || renewal == "unknown" else { return nil }
        if let reason {
            switch reason {
            case "profileAbsent", "profileMismatch": guard store == "mismatch" else { return nil }
            case "readbackUnavailable": guard store == "unavailable" else { return nil }
            case "baselineUnavailable": guard renewal == "unknown" else { return nil }
            case "expiryUnchanged": guard renewal == "unchanged" else { return nil }
            case "expiryShortened": guard renewal == "shortened" else { return nil }
            case "certificateUnknown": guard certificate == "unknown" else { return nil }
            case "certificateExpired", "certificateRevoked": guard certificate == "invalid" else { return nil }
            default: return nil
            }
        }
        self.mutationDispatched = dispatched.boolValue
        self.installAcknowledged = acknowledged.boolValue
        self.profileStore = store; self.renewal = renewal; self.certificate = certificate; self.reason = reason
        self.preservation = preservation
    }
    public var isRenewed: Bool {
        installAcknowledged && profileStore == "matched" && renewal == "extended" && certificate == "valid"
    }
    public var wire: [String: Any] {
        var value: [String: Any] = ["version": 1, "mutationDispatched": mutationDispatched, "installAcknowledged": installAcknowledged,
            "profileStore": profileStore, "renewal": renewal, "certificate": certificate]
        if let reason { value["reason"] = reason }
        if let preservation { value["preservation"] = preservation }
        return value
    }
}

// This is host-owned installed-bundle metadata, not a device profile-store claim.
public enum V3HostProfileRenewalProof {
    // Same canonical original identity as SideStoreHooks.m hook_appbundleIdentifier.
    public static let originalHostID = "com.kdt.livecontainer"
    public static func record(in manifest: inout [String: Any], runID: String,
                              baseline: [String: Any], installedBundleID: String,
                              observedIdentifier: String, observedExpiration: Date,
                              observedAt: Date) -> Bool {
        guard baseline["run_id"] as? String == runID,
              baseline["installed_bundle_id"] as? String == installedBundleID,
              baseline["identifier"] as? String == observedIdentifier,
              let previous = baseline["expiration"] as? Date,
              observedExpiration > previous, observedExpiration > observedAt,
              CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let handoff = manifest["host_handoff"] as? NSNumber, CFGetTypeID(handoff) == CFBooleanGetTypeID(), handoff.boolValue,
              (manifest["expected_ids"] as? [String])?.contains(originalHostID) == true else { return false }
        manifest["host_profile_verification"] = ["version": 1, "run_id": runID, "bundle_id": originalHostID,
            "previous_expiration": previous, "observed_expiration": observedExpiration, "observed_at": observedAt]
        return true
    }
    public static func matches(_ manifest: [String: Any], entry: [String: Any], runID: String) -> Bool {
        guard let handoff = manifest["host_handoff"] as? NSNumber, CFGetTypeID(handoff) == CFBooleanGetTypeID(), handoff.boolValue,
              entry["bundle_id"] as? String == originalHostID, entry["success"] as? Bool == true,
              let proof = manifest["host_profile_verification"] as? [String: Any],
              Set(proof.keys) == ["version", "run_id", "bundle_id", "previous_expiration", "observed_expiration", "observed_at"],
              let version = proof["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 1,
              proof["run_id"] as? String == runID, proof["bundle_id"] as? String == originalHostID,
              let previous = proof["previous_expiration"] as? Date,
              let observed = proof["observed_expiration"] as? Date,
              let at = proof["observed_at"] as? Date,
              [previous, observed, at].allSatisfy({ $0.timeIntervalSince1970.isFinite }),
              observed > previous, observed > at else { return false }
        return true
    }
}

public enum V3RefreshEvidencePolicy {
    public static func outcome(_ manifest: [String: Any]?, runID: String) -> V3RefreshRenewalOutcome {
        guard let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let entries = manifest["results"] as? [[String: Any]] else { return .unconfirmed }
        if entries.allSatisfy({ entry in
            entry["success"] as? Bool == true && (V3RefreshProfileEvidence(entry["verification"])?.isRenewed == true ||
                V3HostProfileRenewalProof.matches(manifest, entry: entry, runID: runID))
        }) {
            // A profile-store observation is not installed app/extension launch proof.
            if entries.contains(where: { entry in
                guard let evidence = V3RefreshProfileEvidence(entry["verification"]) else { return false }
                return evidence.isRenewed && evidence.preservation == "authorizationPreserved"
            }) { return .profileOnlyRenewed }
            return entries.contains(where: { V3HostProfileRenewalProof.matches(manifest, entry: $0, runID: runID) }) ? .hostProfileAdvanced : .renewed }
        let evidence = entries.compactMap { V3RefreshProfileEvidence($0["verification"]) }
        if evidence.contains(where: { $0.mutationDispatched && !$0.installAcknowledged }) { return .mutationUnconfirmed }
        guard evidence.count == entries.count else { return hasAcknowledgment(manifest, runID: runID) ? .acknowledgedUnverified : .unconfirmed }
        guard evidence.contains(where: { $0.installAcknowledged }) else { return .unconfirmed }
        if evidence.contains(where: { $0.installAcknowledged && ($0.profileStore == "mismatch" || $0.renewal == "shortened" || $0.certificate == "invalid") }) { return .verificationFailed }
        if entries.allSatisfy({ $0["success"] as? Bool == true }) && evidence.allSatisfy({
            $0.installAcknowledged && $0.profileStore == "matched" && $0.certificate == "valid" && ["extended", "unchanged"].contains($0.renewal)
        }) { return .installedUnchanged }
        return .acknowledgedUnverified
    }
    public static func hasAcknowledgment(_ manifest: [String: Any]?, runID: String) -> Bool {
        guard let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let entries = manifest["results"] as? [[String: Any]] else { return false }
        return entries.contains { V3RefreshProfileEvidence($0["verification"])?.installAcknowledged == true ||
            V3HostProfileRenewalProof.matches(manifest, entry: $0, runID: runID) }
    }
    public static func terminalOutcome(_ manifest: [String: Any]?, runID: String) -> V3RefreshRenewalOutcome? {
        guard let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let entries = manifest["results"] as? [[String: Any]],
              entries.allSatisfy({ $0["success"] as? Bool == true }) || hasAcknowledgment(manifest, runID: runID) ||
                entries.contains(where: { V3RefreshProfileEvidence($0["verification"])?.mutationDispatched == true }) else { return nil }
        return outcome(manifest, runID: runID)
    }
    public static func failurePresentation(_ manifest: [String: Any]?, runID: String,
                                           stage: String, code: String) -> V3RefreshRenewalOutcome? {
        if terminalOutcome(manifest, runID: runID) == .mutationUnconfirmed { return .mutationUnconfirmed }
        // A failed native refresh may have an ACK without verified preservation.
        // Match the actual producer boundary; do not hide persistence/guest errors.
        if stage == "command", code == "failed",
           let terminal = terminalOutcome(manifest, runID: runID),
           (terminal == .verificationFailed || terminal == .acknowledgedUnverified),
           let entries = manifest?["results"] as? [[String: Any]],
           entries.contains(where: { entry in
               guard entry["success"] as? Bool == false,
                     let evidence = V3RefreshProfileEvidence(entry["verification"]),
                     evidence.installAcknowledged,
                     ["mismatch", "unavailable"].contains(evidence.profileStore),
                     let wire = entry["failure"] as? [String: Any],
                     let failure = CombinedFailure.decode(wire, expectedID: runID) else { return false }
               return failure.operation == "refresh" && failure.stage == .command &&
                   failure.code == .failed && failure.sourceStep == .refreshApplication
           }) { return terminal }
        guard stage == "refreshVerification", code == "missingResult",
              let manifest, let entries = manifest["results"] as? [[String: Any]],
              entries.allSatisfy({ $0["success"] as? Bool == true }),
              let outcome = terminalOutcome(manifest, runID: runID), !outcome.isVerified else { return nil }
        return outcome
    }
    public static func presentationOutcome(_ record: [String: Any], runID: String) -> V3RefreshRenewalOutcome? {
        guard let value = record["renewal_presentation"] as? NSNumber,
              CFGetTypeID(value) == CFBooleanGetTypeID(), value.boolValue,
              let outcome = recordedOutcome(record, runID: runID), !outcome.isVerified else { return nil }
        return outcome
    }
    public static func isPreMutationFailure(stage: String, sourceStep: String?) -> Bool {
        if ["network", "extensionDiscovery", "extensionLaunch", "xpcConnection", "serviceReadiness"].contains(stage) { return true }
        return ["refreshReadiness", "refreshPreflight", "certificateSelection", "certificateValidation", "provisioningProfileFetch", "refreshMetadataCache"].contains(sourceStep ?? "")
    }
    public static func canClearUncertainty(_ manifest: [String: Any]?, runID: String) -> Bool {
        guard let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let entries = manifest["results"] as? [[String: Any]] else { return false }
        return entries.allSatisfy { entry in
            if let evidence = V3RefreshProfileEvidence(entry["verification"]) {
                if !evidence.mutationDispatched { return true }
                // ACK alone cannot release a retry hold after failed readback.
                return entry["success"] as? Bool == true && evidence.installAcknowledged &&
                    evidence.profileStore == "matched" && evidence.certificate == "valid" &&
                    ["extended", "unchanged"].contains(evidence.renewal)
            }
            if V3HostProfileRenewalProof.matches(manifest, entry: entry, runID: runID) { return true }
            guard entry["success"] as? Bool == false,
                  let wire = entry["failure"] as? [String: Any],
                  let failure = CombinedFailure.decode(wire, expectedID: runID), failure.operation == "refresh" else { return false }
            return isPreMutationFailure(stage: failure.stage.rawValue, sourceStep: failure.sourceStep?.rawValue)
        }
    }
    public static func recordedOutcome(_ record: [String: Any], runID: String) -> V3RefreshRenewalOutcome? {
        guard record["run_id"] as? String == runID,
              let summary = record["manifest_summary"] as? [String: Any], summary["run_id"] as? String == runID,
              let version = summary["evidence_version"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 1,
              let raw = summary["renewal_outcome"] as? String else { return nil }
        return V3RefreshRenewalOutcome(rawValue: raw)
    }
}

public enum V3DirectProfileVerificationPolicy {
    public static func applies(_ operation: String) -> Bool {
        ["refresh", "resign", "install", "update", "reinstall", "activate", "restore", "legacyReplacement"].contains(operation)
    }
    public static func outcome(_ reply: [String: Any], operation: String) -> V3RefreshRenewalOutcome? {
        guard applies(operation) else { return nil }
        guard let evidence = V3RefreshProfileEvidence(reply["verification"]) else {
            return reply["state"] as? String == "completed" || reply["verification"] != nil ? .unconfirmed : nil
        }
        if evidence.mutationDispatched && !evidence.installAcknowledged { return .mutationUnconfirmed }
        guard evidence.installAcknowledged else { return nil }
        if evidence.isRenewed { return evidence.preservation == "authorizationPreserved" ? .profileOnlyRenewed : .renewed }
        if evidence.profileStore == "matched" && evidence.renewal == "unchanged" && evidence.certificate == "valid" { return .installedUnchanged }
        if evidence.profileStore == "mismatch" || evidence.renewal == "shortened" || evidence.certificate == "invalid" { return .verificationFailed }
        return .acknowledgedUnverified
    }
    public static func blocksRetry(_ reply: [String: Any], operation: String) -> Bool {
        guard applies(operation) else { return false }
        if let evidence = V3RefreshProfileEvidence(reply["verification"]) { return evidence.mutationDispatched }
        if reply["verification"] != nil { return true }
        guard ["failed", "cancelled", "completed"].contains(reply["state"] as? String ?? "") else { return false }
        if let wire = reply["failure"] as? [String: Any], let session = reply["session"] as? String,
           let failure = CombinedFailure.decode(wire, expectedID: session) {
            return !V3RefreshEvidencePolicy.isPreMutationFailure(stage: failure.stage.rawValue, sourceStep: failure.sourceStep?.rawValue)
        }
        return true
    }
    public static func stopTerminalPolling(_ reply: [String: Any], operation: String) -> Bool {
        guard let settled = reply["backendSettled"] as? NSNumber,
              CFGetTypeID(settled) == CFBooleanGetTypeID(), settled.boolValue,
              ["completed", "failed", "cancelled"].contains(reply["state"] as? String ?? "") else { return false }
        return requiresDeviceCheck(reply, operation: operation)
    }
    public static func requiresDeviceCheck(_ reply: [String: Any], operation: String) -> Bool {
        guard applies(operation) else { return false }
        if let unknown = reply["outcomeUnknown"] as? NSNumber,
           CFGetTypeID(unknown) == CFBooleanGetTypeID(), unknown.boolValue { return true }
        guard let outcome = outcome(reply, operation: operation) else { return false }
        return !outcome.isVerified && outcome != .installedUnchanged
    }
}

public struct V3RefreshUncertaintyTicket {
    public let runID: String
    public let updatedAt: Double
    public init(runID: String, updatedAt: Double) {
        self.runID = runID
        self.updatedAt = updatedAt
    }
}
public enum V3RefreshUncertaintyAcknowledgmentPolicy {
    public static let blockedMessage = "A previous installation may already have completed, but its result is unconfirmed. Check the app and its expiration before acknowledging that exact attempt. No new installation has started."
    public static func canAcknowledge(ticket: V3RefreshUncertaintyTicket, marker: String?,
                                     record: [String: Any]?, activeRunID: String?,
                                     hostHandoffPending: Bool, directClaimPresent: Bool) -> Bool {
        guard UUID(uuidString: ticket.runID)?.uuidString == ticket.runID,
              marker == ticket.runID, ticket.updatedAt.isFinite,
              let record, record["run_id"] as? String == ticket.runID, record["state"] as? String == "failed",
              let updated = record["updated_at"] as? NSNumber, CFGetTypeID(updated) != CFBooleanGetTypeID(),
              updated.doubleValue == ticket.updatedAt,
              activeRunID?.isEmpty != false, !hostHandoffPending, !directClaimPresent else { return false }
        return true
    }
    public static func mayRunAutomatically(manualOnlyAfterAcknowledgment: Bool) -> Bool {
        !manualOnlyAfterAcknowledgment
    }
}

// A historical owned-batch observation, never a live VPN or renewal assertion.
public enum V3RefreshTransportObservation {
    public static func validated(_ value: Any?) -> [String: Any]? {
        guard let raw = value as? [String: Any], Set(raw.keys) == ["version", "readiness", "scope"],
              let version = raw["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 1,
              raw["readiness"] as? String == "ready", raw["scope"] as? String == "ownedBatch" else { return nil }
        return ["version": 1, "readiness": "ready", "scope": "ownedBatch"]
    }
    public static func recorded(in record: [String: Any], runID: String) -> Bool {
        guard UUID(uuidString: runID)?.uuidString == runID, record["run_id"] as? String == runID,
              ["completed", "failed"].contains(record["state"] as? String ?? ""),
              let summary = record["manifest_summary"] as? [String: Any], summary["run_id"] as? String == runID,
              let version = summary["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 2,
              summary["schema"] as? String == "LiveContainerRefreshManifestSummaryV2" else { return false }
        return validated(summary["transport_observation"]) != nil
    }
}

public enum V3RefreshTargetDiagnostics {
    public static let maximumTargets = 32
    private static let rowKeys: Set<String> = ["target", "scope", "operation", "guard", "failureKind", "dispatched", "acknowledged", "profileStore", "renewal", "certificate"]
    public static func rows(_ manifest: [String: Any], runID: String) -> [[String: Any]] {
        guard CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let expected = manifest["expected_ids"] as? [String],
              let entries = manifest["results"] as? [[String: Any]] else { return [] }
        return expected.prefix(maximumTargets).enumerated().compactMap { index, identifier in
            guard let entry = entries.first(where: { $0["bundle_id"] as? String == identifier }) else { return nil }
            let evidence = V3RefreshProfileEvidence(entry["verification"])
            let failure = (entry["failure"] as? [String: Any]).flatMap { CombinedFailure.decode($0, expectedID: runID) }
            let token = failure?.signingContext["local_precondition"]
            let selection = failure?.operation == "refresh" && failure?.code == .failed &&
                CombinedFailure.refreshSelectionPreconditions.contains(token ?? "") &&
                ((failure?.stage == .command && failure?.sourceStep == .refreshApplication) ||
                 (failure?.stage == .signing && failure?.sourceStep == .provisioningProfileFetch && CombinedFailure.preservationRefreshPreconditions.contains(token ?? "")))
            var row: [String: Any] = ["target": index + 1, "scope": selection ? (failure?.signingContext["refresh_target_scope"] ?? "unknown") : "unknown",
                    "operation": entry["success"] as? Bool == true ? "completed" : "failed",
                    "guard": selection ? token! : "notRecorded", "failureKind": failure?.signingContext["refresh_failure_kind"] ?? "notRecorded",
                    "dispatched": evidence.map { $0.mutationDispatched ? "yes" : "no" } ?? "unknown",
                    "acknowledged": evidence.map { $0.installAcknowledged ? "yes" : "no" } ?? "unknown",
                    "profileStore": evidence?.profileStore ?? "unknown", "renewal": evidence?.renewal ?? "unknown",
                    "certificate": evidence?.certificate ?? "unknown"]
            if selection, token == "preservationAuthorityConflict",
               let conflict = failure?.signingContext["preservation_conflict"], CombinedFailure.preservationConflictKinds.contains(conflict) {
                row["preservationConflict"] = conflict
                if let raw = failure?.signingContext[V3CMSSignerDiagnostic.contextKey],
                   V3CMSSignerDiagnostic(encoded: raw) != nil {
                    row["cmsSignerDiagnostic"] = raw
                }
            }
            if selection, token == "preservationEvidenceUnavailable",
               let origin = failure?.signingContext["apple_profile_origin"],
               CombinedFailure.appleProfileOriginKinds.contains(origin) {
                row["appleProfileOrigin"] = origin
            }
            if selection, token == "preservationEvidenceUnavailable",
               failure?.stage == .signing, failure?.sourceStep == .provisioningProfileFetch,
               evidence?.mutationDispatched == false,
               let reason = failure?.signingContext["preservation_evidence"],
               CombinedFailure.preservationEvidenceKinds.contains(reason) {
                row["preservationEvidence"] = reason
            }
            if selection, token == "preservationPortalIdentityUnavailable",
               failure?.stage == .signing, failure?.sourceStep == .provisioningProfileFetch,
               evidence?.mutationDispatched == false,
               let reason = failure?.signingContext["preservation_portal_identity"],
               CombinedFailure.preservationPortalIdentityKinds.contains(reason) {
                row["preservationPortalIdentity"] = reason
            }
            return row
        }
    }
    public static func copiedDetails(_ record: [String: Any], runID: String) -> String {
        guard UUID(uuidString: runID)?.uuidString == runID, record["run_id"] as? String == runID,
              ["failed", "completed"].contains(record["state"] as? String ?? ""),
              let summary = record["manifest_summary"] as? [String: Any], summary["run_id"] as? String == runID,
              let version = summary["version"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: version.objCType)), version.intValue == 2,
              summary["schema"] as? String == "LiveContainerRefreshManifestSummaryV2",
              let expected = summary["expected_count"] as? NSNumber, CFGetTypeID(expected) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: expected.objCType)), (1...1024).contains(expected.intValue),
              let rows = summary["target_diagnostics"] as? [[String: Any]], rows.count == min(expected.intValue, maximumTargets) else { return "" }
        var lines = ["transport_observation=\(V3RefreshTransportObservation.recorded(in: record, runID: runID) ? "ready_during_run_not_live" : "not_recorded")"]
        for (index, row) in rows.enumerated() {
            guard rowKeys.isSubset(of: Set(row.keys)), Set(row.keys).isSubset(of: rowKeys.union(["preservationConflict", "cmsSignerDiagnostic", "appleProfileOrigin", "preservationPortalIdentity", "preservationEvidence"])), let target = row["target"] as? NSNumber,
                  CFGetTypeID(target) != CFBooleanGetTypeID(),
                  ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: target.objCType)), target.intValue == index + 1,
                  let scope = row["scope"] as? String, ["host", "nonHost", "unknown"].contains(scope),
                  let operation = row["operation"] as? String, ["completed", "failed"].contains(operation),
                  let token = row["guard"] as? String, token == "notRecorded" || CombinedFailure.refreshSelectionPreconditions.contains(token),
                  let kind = row["failureKind"] as? String, kind == "notRecorded" || CombinedFailure.validatedSigningContext(["refresh_failure_kind": kind]) != nil,
                  let dispatched = row["dispatched"] as? String, ["yes", "no", "unknown"].contains(dispatched),
                  let acknowledged = row["acknowledged"] as? String, ["yes", "no", "unknown"].contains(acknowledged),
                  let store = row["profileStore"] as? String, ["matched", "mismatch", "unavailable", "unknown"].contains(store),
                  let renewal = row["renewal"] as? String, ["extended", "unchanged", "shortened", "unknown"].contains(renewal),
                  let certificate = row["certificate"] as? String, ["valid", "invalid", "unknown"].contains(certificate) else { return "" }
            let conflict = row["preservationConflict"] as? String
            let conflictSuffix = token == "preservationAuthorityConflict" && kind == "invalidParameters" &&
                CombinedFailure.preservationConflictKinds.contains(conflict ?? "") ? " preservation_conflict=\(conflict!)" : ""
            let signerSuffix: String
            if operation == "failed", scope == "nonHost", dispatched == "no",
               token == "preservationAuthorityConflict", kind == "invalidParameters",
               conflict == "embeddedDERUnsupportedSigner", let raw = row["cmsSignerDiagnostic"] as? String,
               let diagnostic = V3CMSSignerDiagnostic(encoded: raw) {
                signerSuffix = diagnostic.technicalDetails
            } else { signerSuffix = "" }
            let originSuffix: String
            if operation == "failed", scope == "nonHost", dispatched == "no",
               token == "preservationEvidenceUnavailable", kind == "invalidParameters",
               let origin = row["appleProfileOrigin"] as? String,
               CombinedFailure.appleProfileOriginKinds.contains(origin) {
                originSuffix = " apple_profile_origin=\(origin)"
            } else { originSuffix = "" }
            let evidenceSuffix: String
            if operation == "failed", scope == "nonHost", dispatched == "no",
               token == "preservationEvidenceUnavailable", kind == "invalidParameters",
               let reason = row["preservationEvidence"] as? String,
               CombinedFailure.preservationEvidenceKinds.contains(reason) {
                evidenceSuffix = " preservation_evidence=\(reason)"
            } else { evidenceSuffix = "" }
            let portalSuffix: String
            if operation == "failed", scope == "nonHost", dispatched == "no",
               token == "preservationPortalIdentityUnavailable", kind == "invalidParameters",
               let reason = row["preservationPortalIdentity"] as? String,
               CombinedFailure.preservationPortalIdentityKinds.contains(reason) {
                portalSuffix = " preservation_portal_identity=\(reason)"
            } else { portalSuffix = "" }
            lines.append("target_\(index + 1): scope=\(scope) operation_status=\(operation) selection_guard=\(token) failure_kind=\(kind) mutation_dispatched=\(dispatched) install_acknowledged=\(acknowledged) profile_store=\(store) renewal=\(renewal) certificate=\(certificate)" + conflictSuffix + signerSuffix + originSuffix + portalSuffix + evidenceSuffix)
        }
        if let count = summary["expected_count"] as? Int, count > rows.count { lines.append("target_diagnostics_truncated=yes") }
        return lines.joined(separator: "\n")
    }
}

public enum CombinedVerification {
    static let uncertainMutationKey = "liveContainerAutoRefreshUncertainMutationRunID"
    static func clearUncertainty(_ defaults: UserDefaults, runID: String) {
        guard defaults.string(forKey: uncertainMutationKey) == runID else { return }
        defaults.removeObject(forKey: uncertainMutationKey)
    }
    // Complete terminal results establish completion, not verified refresh success.
    // Empty, duplicated or omitted app results leave mutation completion uncertain.
    // The Setup Assistant reuses this exact contract: a partial manifest (for
    // example two expected apps but only one result) never verifies.
    public static func hasCompleteTerminalResults(_ manifest: [String: Any], runID: String) -> Bool {
        guard UUID(uuidString: runID) != nil, manifest["run_id"] as? String == runID,
              manifest["version"] as? Int == 2, manifest["schema"] as? String == "LiveContainerRefreshManifestV2",
              let expected = manifest["expected_ids"] as? [String], !expected.isEmpty, expected.count <= 1024,
              expected.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }), Set(expected).count == expected.count,
              (manifest["host_handoff"] == nil || strictBoolean(manifest["host_handoff"]) != nil),
              targetCoverageIsValid(manifest, expected: expected),
              let entries = manifest["results"] as? [[String: Any]], entries.count == expected.count else { return false }
        var received = Set<String>()
        for entry in entries {
            guard let identifier = entry["bundle_id"] as? String, expected.contains(identifier),
                  received.insert(identifier).inserted,
                  let success = entry["success"] as? NSNumber, CFGetTypeID(success) == CFBooleanGetTypeID() else { return false }
        }
        return received == Set(expected)
    }
    private static func strictBoolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }
    private static func targetCoverageIsValid(_ manifest: [String: Any], expected: [String]) -> Bool {
        guard manifest["requested_ids"] != nil || manifest["skipped_ids"] != nil else { return true }
        guard let requested = manifest["requested_ids"] as? [String],
              let skipped = manifest["skipped_ids"] as? [String],
              !requested.isEmpty, requested.count <= 1024, skipped.count <= 1024,
              requested.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }),
              skipped.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }),
              Set(requested).count == requested.count, Set(skipped).count == skipped.count else { return false }
        let expectedSet = Set(expected), skippedSet = Set(skipped)
        return expectedSet.isDisjoint(with: skippedSet) &&
            expectedSet.union(skippedSet) == Set(requested)
    }
    static func sanitized(_ payload: [String: Any], runID: String) -> [String: Any] {
        guard let manifest = payload["liveContainerAutoRefreshVerification"] as? [String: Any],
              hasCompleteTerminalResults(manifest, runID: runID),
              manifest["run_id"] as? String == runID,
              let expected = manifest["expected_ids"] as? [String], expected.count <= 1024,
              expected.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 512 }),
              targetCoverageIsValid(manifest, expected: expected),
              let entries = manifest["results"] as? [[String: Any]],
              entries.count == expected.count,
              entries.allSatisfy({ entry in
                  guard let identifier = entry["bundle_id"] as? String,
                        expected.contains(identifier), strictBoolean(entry["success"]) != nil else { return false }
                  return true
              }),
              Set(entries.map { $0["bundle_id"] as? String ?? "" }) == Set(expected) else { return [:] }
        let manifestHostHandoff: Bool?
        if let rawHostHandoff = manifest["host_handoff"] {
            guard let value = strictBoolean(rawHostHandoff) else { return [:] }
            manifestHostHandoff = value
        } else {
            manifestHostHandoff = nil
        }
        let outerHostHandoffRunID: String?
        if let rawRunID = payload["liveContainerAutoRefreshHostHandoffRunID"] {
            guard let value = rawRunID as? String else { return [:] }
            outerHostHandoffRunID = value
        } else {
            outerHostHandoffRunID = nil
        }
        let outerHostHandoff: Bool?
        if let rawHostHandoff = payload["liveContainerAutoRefreshHostHandoff"] {
            guard let value = strictBoolean(rawHostHandoff) else { return [:] }
            outerHostHandoff = value
        } else {
            outerHostHandoff = nil
        }
        let hasCurrentHostHandoff = outerHostHandoffRunID == runID
        // The producer persists true plus this run ID before writing the
        // manifest's copied host_handoff flag. Never turn an incomplete or
        // contradictory current-run handoff into false at the XPC boundary.
        if hasCurrentHostHandoff {
            guard manifestHostHandoff == true, outerHostHandoff == true else { return [:] }
        } else {
            // A true manifest/outer marker without its matching run ID is
            // incomplete evidence. A normal refresh may omit the outer marker
            // or carry explicit false values.
            guard manifestHostHandoff != true, outerHostHandoff != true else { return [:] }
        }
        var result: [String: Any] = ["version": 2, "schema": "LiveContainerRefreshManifestV2", "run_id": runID, "expected_ids": expected]
        if let requested = manifest["requested_ids"] as? [String] { result["requested_ids"] = requested }
        if let skipped = manifest["skipped_ids"] as? [String] { result["skipped_ids"] = skipped }
        if let date = manifest["date"] as? Date { result["date"] = date }
        if let manifestHostHandoff { result["host_handoff"] = manifestHostHandoff }
        if let observation = V3RefreshTransportObservation.validated(manifest["transport_observation"]) { result["transport_observation"] = observation }
        result["results"] = entries.map { entry -> [String: Any] in
            guard let identifier = entry["bundle_id"] as? String, expected.contains(identifier),
                  let success = strictBoolean(entry["success"]) else { return [:] }
            var item: [String: Any] = ["bundle_id": identifier, "success": success]
            for key in ["refreshed_date", "expiration_date"] { if let value = entry[key] as? Date { item[key] = value } }
            if let evidence = V3RefreshProfileEvidence(entry["verification"]) { item["verification"] = evidence.wire }
            if !success {
                let native = NSError(domain: entry["error_domain"] as? String ?? "redacted", code: entry["error_code"] as? Int ?? 0,
                    userInfo: [NSLocalizedDescriptionKey: entry["error"] as? String ?? ""])
                let preserved = (entry["failure"] as? [String: Any]).flatMap { CombinedFailure.decode($0, expectedID: runID) }
                let failure = preserved ?? CombinedFailure.capture(native, operation: "refresh", stage: .refreshVerification, id: runID)
                let safeUnderlying = CombinedFailure.safeWireUnderlying(domain: failure.underlyingDomain,
                    code: failure.underlyingCode)
                item["error"] = failure.localizedDescription
                item["error_code"] = safeUnderlying.code; item["error_domain"] = safeUnderlying.domain
                item["failure"] = failure.wire
            }
            return item
        }
        var safe: [String: Any] = ["liveContainerAutoRefreshVerification": result]
        if hasCurrentHostHandoff {
            safe["liveContainerAutoRefreshHostHandoffRunID"] = runID
            safe["liveContainerAutoRefreshHostHandoff"] = true
            for key in ["liveContainerAutoRefreshHostHandoffStartedAt", "liveContainerAutoRefreshHostPreviousExpiration"] {
                if let value = payload[key] as? Date { safe[key] = value }
            }
        }
        return safe
    }
}


// LC_STRUCTURED_FAILURE_V1: fixed vocabulary, no arbitrary userInfo/descriptions on the wire.
/// Read-only CMS signer observations, never a profile authority or acceptance decision.
/// Only verified public-certificate fingerprints are permitted; no certificate content/names.
public struct V3CMSSignerDiagnostic {
    public static let contextKey = "cms_signer_diagnostic"
    public let encoded: String
    private let fields: [String]
    public init?(encoded: String) {
        guard encoded.utf8.count <= 200 else { return nil }
        let fields = encoded.components(separatedBy: "|")
        guard fields.count == 9, fields[0] == "cs1",
              ["installed", "candidate", "freshInstalled", "freshCandidate"].contains(fields[1]),
              fields[2...6].allSatisfy({ ["unchecked", "passed", "failed"].contains($0) }),
              fields[6] == "failed" else { return nil }
        let verified = fields[2...5].allSatisfy { $0 == "passed" }
        if verified {
            guard fields[7].utf8.count == 4, fields[7].utf8.allSatisfy({ $0 == 48 || $0 == 49 }),
                  fields[8] == "unknown" || (fields[8].utf8.count == 64 && fields[8].utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) })) else { return nil }
        } else {
            guard fields[7] == "unchecked", fields[8] == "unknown" else { return nil }
        }
        self.encoded = encoded
        self.fields = fields
    }
    public var technicalDetails: String {
        var result = " cms_signer_input=\(fields[1]) cms_signer_algorithm=\(fields[2]) cms_signer_chain=\(fields[3]) cms_signer_signature=\(fields[4]) cms_signer_time=\(fields[5]) cms_signer_pin=\(fields[6])"
        let names = ["leaf_name", "issuer_name", "profile_marker", "app_developer_marker"]
        let bits = fields[7] == "unchecked" ? [] : fields[7].map(String.init)
        for (index, name) in names.enumerated() {
            result += " cms_signer_\(name)_observed=\(bits.isEmpty ? "unchecked" : (bits[index] == "1" ? "yes" : "no"))"
        }
        return result + " cms_signer_sha256=\(fields[8]) cms_signer_diagnostic_only=yes"
    }
}

public struct CombinedFailure: Error, LocalizedError {
    public struct LaunchContext: Equatable {
        public static let bridgeErrorDomain = "io.sidestore.LiveContainer.ExtensionLaunch"
        public static let bridgeNoIdentifierCode = 1
        public enum Step: String {
            case hostBundleUnavailable, missingPluginDirectory, liveProcessBundleMissing, liveProcessBundleUnreadable
            case bundleIdentifierMissing, executableMetadataMissing, executableFileMissing
            case extensionFactory, extensionFactoryNil, listenerCreation
            case requestCallbackNoIdentifier, requestCancellation, requestInterruption
            case requestCallbackError, processIdentifierUnavailable, xpcRemoteObjectError
            case xpcInvalidation, xpcPeerRejected, readinessProbe, startupTimeout, connectionStopped, unknown
        }
        public enum Kind: String {
            case extensionNotFound = "extension_not_found"
            case executableLoadFailure = "executable_load_failure"
            case signatureOrEntitlementRejection = "signature_or_entitlement_rejection"
            case dependencyLoadFailure = "dependency_load_failure"
            case bootstrapFailure = "bootstrap_failure"
            case xpcConnectionFailure = "xpc_connection_failure"
            case unknown
        }
        public struct Cause: Equatable {
            public let domain: String
            public let code: Int?
        }

        public let observerRole: String
        public let targetRole: String
        public let osVersion: String
        public let runtimeArchitecture: String
        public let sourceStep: Step
        public let kind: Kind
        public let requestIdentifierObserved: String
        public let pidObserved: String
        public let xpcAccepted: String
        public let applicationReadyObserved: String
        public let peerPIDRejected: String
        public private(set) var errorChain: [Cause]

        public init(error: Error? = nil, sourceStep: Step,
                    requestIdentifierObserved: Bool? = nil, pidObserved: Bool? = nil,
                    xpcAccepted: Bool? = nil, applicationReadyObserved: Bool? = nil,
                    peerPIDRejected: Bool? = nil) {
            observerRole = "host"
            targetRole = "LiveProcess"
            let version = ProcessInfo.processInfo.operatingSystemVersion
            osVersion = "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)"
            #if arch(arm64e)
            runtimeArchitecture = "arm64e"
            #elseif arch(arm64)
            runtimeArchitecture = "arm64"
            #elseif arch(x86_64)
            runtimeArchitecture = "x86_64"
            #elseif arch(i386)
            runtimeArchitecture = "i386"
            #else
            runtimeArchitecture = "unknown"
            #endif
            self.sourceStep = sourceStep

            self.requestIdentifierObserved = Self.observation(requestIdentifierObserved)
            self.pidObserved = Self.observation(pidObserved)
            self.xpcAccepted = Self.observation(xpcAccepted)
            self.applicationReadyObserved = Self.observation(applicationReadyObserved)
            self.peerPIDRejected = Self.observation(peerPIDRejected)

            let causes = Self.safeErrorChain(error)
            errorChain = causes
            kind = Self.classify(sourceStep: sourceStep, errorChain: causes)
        }

        public var technicalDetails: String {
            let causes = errorChain.map { cause in
                cause.code.map { "\(cause.domain):\($0)" } ?? "\(cause.domain):unknown"
            }.joined(separator: ">")
            return " launch_observer_role=\(observerRole) launch_target_role=\(targetRole) launch_os=\(osVersion) launch_arch=\(runtimeArchitecture)" +
                " launch_source_step=\(sourceStep.rawValue) launch_failure_kind=\(kind.rawValue)" +
                " launch_request_id_observed=\(requestIdentifierObserved) launch_pid_observed=\(pidObserved)" +
                " launch_xpc_accepted=\(xpcAccepted) launch_application_ready=\(applicationReadyObserved)" +
                " launch_peer_pid_rejected=\(peerPIDRejected) launch_error_chain=\(causes.isEmpty ? "none" : causes)"
        }

        private static func observation(_ value: Bool?) -> String {
            guard let value else { return "unknown" }
            return value ? "yes" : "no"
        }

        public func retainingErrorChain(from prior: LaunchContext?) -> LaunchContext {
            guard let prior, !prior.errorChain.isEmpty else { return self }
            guard !errorChain.isEmpty else {
                var enriched = self
                enriched.errorChain = prior.errorChain
                return enriched
            }
            let limit = min(errorChain.count, prior.errorChain.count)
            let overlap = (0...limit).reversed().first { count in
                Array(errorChain.suffix(count)) == Array(prior.errorChain.prefix(count))
            } ?? 0
            let combined = Array((errorChain + Array(prior.errorChain.dropFirst(overlap))).prefix(5))
            guard combined != errorChain else { return self }
            var enriched = self
            enriched.errorChain = combined
            return enriched
        }

        private static func safeErrorChain(_ error: Error?) -> [Cause] {
            if let known = error as? CombinedFailure {
                if let context = known.launchContext { return context.errorChain }
                guard known.underlyingDomain != "none" || known.underlyingCode != 0 else { return [] }
                let safe = CombinedFailure.safeDiagnosticUnderlying(domain: known.underlyingDomain, code: known.underlyingCode)
                return [Cause(domain: safe.domain, code: safe.code == "unknown" ? nil : known.underlyingCode)]
            }
            guard var current = error as NSError? else { return [] }
            var result: [Cause] = []
            var seen = Set<ObjectIdentifier>()
            for _ in 0..<5 {
                let identity = ObjectIdentifier(current)
                guard seen.insert(identity).inserted else { break }
                let safe = CombinedFailure.safeDiagnosticUnderlying(domain: current.domain, code: current.code)
                result.append(Cause(domain: safe.domain, code: safe.code == "unknown" ? nil : current.code))
                guard let next = current.userInfo[NSUnderlyingErrorKey] as? NSError else { break }
                current = next
            }
            return result
        }

        private static func classify(sourceStep: Step, errorChain: [Cause]) -> Kind {
            switch sourceStep {
            case .missingPluginDirectory, .liveProcessBundleMissing:
                return .extensionNotFound
            case .executableFileMissing:
                return .executableLoadFailure
            case .listenerCreation, .xpcRemoteObjectError, .xpcInvalidation:
                return .xpcConnectionFailure
            case .requestCancellation:
                if errorChain.contains(where: { $0.domain == NSCocoaErrorDomain && $0.code == NSExecutableLoadError }) {
                    return .executableLoadFailure
                }
            default:
                break
            }
            return .unknown
        }

        public static func launchFailure(_ error: Error? = nil, stage: Stage, code: Code = .failed,
                                         id: String, sourceStep: Step,
                                         requestIdentifierObserved: Bool? = nil, pidObserved: Bool? = nil,
                                         xpcAccepted: Bool? = nil, applicationReadyObserved: Bool? = nil,
                                         peerPIDRejected: Bool? = nil, retryable: Bool? = nil) -> CombinedFailure {
            let context = LaunchContext(error: error, sourceStep: sourceStep,
                requestIdentifierObserved: requestIdentifierObserved, pidObserved: pidObserved,
                xpcAccepted: xpcAccepted, applicationReadyObserved: applicationReadyObserved,
                peerPIDRejected: peerPIDRejected)
            return CombinedFailure(operation: "connect", stage: stage, code: code, id: id,
                underlying: error, retryable: retryable, launchContext: context)
        }
    }

    public enum SafeCause: String, CaseIterable {
        case databaseLayoutBlocked, databaseLayoutConflict, databaseAppGroupUnavailable, databasePersistenceFailed, databaseStartupFailed, databaseHostBundleUnavailable, databaseHostProfileUnavailable, databaseModelUnrecognized, databaseMigrationPathUnavailable, databaseMigrationFailed, databaseSaveFailed
        case networkConnectionLost
        case networkTimedOut
        case networkUnavailable
        case anisetteServerUnavailable
        case anisetteServerRejected
        case anisetteRequestTimedOut
        case anisetteRateLimited
        case anisetteInvalidResponse
        case anisetteUnknownFailure
        case signingNetworkConnectionLost
        case signingNetworkTimedOut
        case signingNetworkUnavailable
        case developerPortalRejectedRequest
        case appIDLimitReached
        case developerPortalInvalidResponse
        case provisioningProfileUnavailable
        case certificateUnavailable
        case signingStorageUnverified
        case wifiUnavailable
        case localDevVPNUnavailable
        case unknownSigningCause
        case sourceNetworkFailure
        case sourceInvalidManifest
        case sourcePersistenceUnverified
        case sourceInvalidURL
        case sourceBlocked
        case sourceChangedID
        case sourceDuplicate
        case sourceUnsupported
        case sourceValidationFailed
        case sourceRemoveFailed
        case sourceRemoveBusy
        case sourceAddBusy
        case operationInProgress
        case responseCapacityUnavailable
        // V3_RUNTIME_SHARED_STORE_CAUSE_V1: the host and the embedded service must
        // read and write refresh state through one App Group. When that store
        // cannot be opened the run is refused rather than written somewhere the
        // other process cannot see, and retrying after a reinstall can succeed.
        case sharedStoreUnavailable
        // V3_SECRET_HANDOFF_FAILURE_TYPED_V1: the secure channel between the two
        // signed processes failed. The payload never reached Apple, so this is
        // not an authentication failure and must not be reported as one. It is
        // retryable only when the cause is transient; an unauthorized or missing
        // access group needs a different re-sign, not another attempt.
        case secretHandoffUnavailable
        case staleRefreshAttempt
        case knownSourcePolicyNetworkFailure
        case knownSourcePolicyInvalidResponse
        case catalogUnavailable
        case catalogSourceUnavailable
        // V3_RESPONSE_ENCODING_CLASSIFICATION_V1: the service built a reply it
        // could not serialize. Distinct from an oversized reply.
        case responseEncodingFailed
        // V3_RESPONSE_ENCODING_CLASSIFICATION_V1: the reply serialized cleanly
        // but exceeded the transport limit. This is a third defect, distinct
        // from both an encoding failure and a reply that could not be parsed,
        // and it must not be reported as any of them.
        case responseTooLarge
        case pairingRequired
        case invalidPairingFile
        case pairingFilePreparationFailed
        case authAttemptNotDispatched
        case authProvisioningRetryNotDispatched
        case authSessionUnavailable
        case authResponseCapacityUnavailable
        case credentialCommitFailed, credentialCommitOutcomeUnknown, accountActivationFailed, provisioningStorageFailed
        case keychainSignOutFailed
        case keychainSignOutOutcomeUnknown
        case operationPersistenceFailed
        case recoveryMalformedRecord, recoveryIncompatibleRecord
        case recoveryStorageUnavailable, recoveryLockUnavailable
        case recoveryReadFailure, recoveryDeleteFailure
        case directRecoveryRecordMissing, directRecoveryTargetMismatch
        case directRecoveryModeInvalid, directRecoveryPhaseNotEligible

        fileprivate var inferredRetryable: Bool? {
            switch self {
            case .databaseLayoutBlocked, .databaseLayoutConflict, .databaseAppGroupUnavailable, .databasePersistenceFailed, .databaseStartupFailed, .databaseHostBundleUnavailable, .databaseHostProfileUnavailable, .databaseModelUnrecognized, .databaseMigrationPathUnavailable, .databaseMigrationFailed, .databaseSaveFailed:
                return false
            case .networkConnectionLost, .networkTimedOut, .networkUnavailable,
                 .signingNetworkConnectionLost, .signingNetworkTimedOut, .signingNetworkUnavailable,
                 .wifiUnavailable, .localDevVPNUnavailable:
                return true
            case .anisetteServerUnavailable:
                return true
            case .anisetteRequestTimedOut, .anisetteRateLimited:
                return true
            case .anisetteServerRejected:
                return false
            case .anisetteInvalidResponse, .anisetteUnknownFailure:
                return nil
            case .appIDLimitReached, .provisioningProfileUnavailable, .certificateUnavailable, .signingStorageUnverified:
                return false
            case .developerPortalRejectedRequest, .developerPortalInvalidResponse:
                return nil
            case .unknownSigningCause:
                return nil
            case .sourceNetworkFailure:
                return true
            case .sourceInvalidManifest, .sourcePersistenceUnverified, .sourceInvalidURL,
                 .sourceBlocked, .sourceChangedID, .sourceDuplicate, .sourceUnsupported,
                 .sourceValidationFailed,
                 .sourceRemoveFailed, .catalogUnavailable:
                return false
            case .sourceRemoveBusy, .sourceAddBusy:
                return true
            case .operationInProgress, .knownSourcePolicyNetworkFailure:
                return true
            case .responseCapacityUnavailable:
                return true
            case .sharedStoreUnavailable:
                return true
            // Retrying the same answer cannot grant an access group or recreate
            // an absent item. Only a transient read or lock failure may repeat.
            case .secretHandoffUnavailable:
                return false
            case .staleRefreshAttempt:
                return false
            case .knownSourcePolicyInvalidResponse:
                return nil
            // The source is gone, so retrying the same request cannot succeed;
            // the recovery is to reload the source list, not to retry.
            case .catalogSourceUnavailable:
                return false
            // A reply that could not be serialized is not fixed by retrying the
            // same request; it needs a code fix or a smaller payload.
            case .responseEncodingFailed:
                return false
            // An oversized reply is not fixed by retrying the same request
            // either: the same data would serialize to the same size again.
            case .responseTooLarge:
                return false
            case .pairingRequired:
                return false
            case .invalidPairingFile:
                return false
            case .pairingFilePreparationFailed:
                return false
            case .authAttemptNotDispatched:
                return true
            case .authProvisioningRetryNotDispatched:
                return true
            case .authSessionUnavailable:
                return false
            case .authResponseCapacityUnavailable:
                return true
            case .credentialCommitFailed, .credentialCommitOutcomeUnknown, .accountActivationFailed, .provisioningStorageFailed:
                return false
            case .keychainSignOutFailed, .keychainSignOutOutcomeUnknown:
                return true
            case .operationPersistenceFailed:
                return false
            case .recoveryMalformedRecord, .recoveryIncompatibleRecord,
                 .directRecoveryRecordMissing, .directRecoveryTargetMismatch,
                 .directRecoveryModeInvalid, .directRecoveryPhaseNotEligible:
                return false
            case .recoveryStorageUnavailable, .recoveryLockUnavailable,
                 .recoveryReadFailure, .recoveryDeleteFailure:
                return true
            }
        }
    }

    public enum SourceStep: String, CaseIterable {
        case authenticate, anisetteFetch, appleAuthentication, accountLookup
        case credentialCommit, fetchTeams, saveAccount, fetchCertificate
        case activateCertificate, registerDevice, activateAccount, provisioningUnknown
        case provisioningProfileFetch, certificateValidation, localCodeSigning
        case appIDLookup, appIDRegistration, appIDCapabilitiesUpdate
        case appGroupLookup, appGroupRegistration, appGroupAssignment
        case provisioningProfileRetrieval, provisioningProfileCreation, provisioningProfileUpdate
        case sourceDownload, manifestParsing, sourceValidation, knownSourcePolicyFetch,
             knownSourcePolicyParsing, catalogRead
        case certificateSelection, refreshMetadataCache, provisioningProfileInstallation, refreshRecordUpdate, refreshApplication
        case refreshReadiness, refreshPreflight
        var portalUserLabel: String? {
            switch self {
            case .appIDLookup: return "while looking up app identifiers"
            case .appIDRegistration: return "while registering an app identifier"
            case .appIDCapabilitiesUpdate: return "while updating the app's capabilities"
            case .appGroupLookup: return "while looking up app groups"
            case .appGroupRegistration: return "while registering an app group"
            case .appGroupAssignment: return "while assigning the app's groups"
            case .provisioningProfileRetrieval: return "while retrieving a provisioning profile"
            case .provisioningProfileCreation: return "while creating a provisioning profile"
            case .provisioningProfileUpdate: return "while updating a provisioning profile"
            default: return nil
            }
        }
    }

    public enum Stage: String, CaseIterable {
        case hostContainer, storagePreparation, bookmarkCreation, extensionDiscovery, extensionLaunch
        case xpcConnection, serviceReadiness, command, authentication, provisioning, signing, filePreparation, installation, persistence, refreshVerification
        case replyEncoding
        case endpointSelection, heartbeat, coreDevice, cdTunnel, rsdDiscovery, rsdService, lockdownConnection, uniqueDeviceID, pairing
        case network, source, catalog
    }
    public enum Code: String, CaseIterable {
        case unavailable, invalidConfiguration, permissionDenied, timedOut, cancelled, interrupted
        case notReady, busy, invalidResponse, unsupported, failed, missingResult, staleResult
        case invalidToken, missingFile, emptyFile, invalidPackage, fileAccess, stagingFailed
    }
    public let operation: String
    public let stage: Stage
    public let code: Code
    public let correlationID: String
    public let underlyingDomain: String
    public let underlyingCode: Int
    public let safeCause: SafeCause?
    public let sourceStep: SourceStep?
    public let signingContext: [String: String]
    public let retryable: Bool?
    // V3_CATALOG_OPERATION_CONTEXT_V1: host-only request context. It records
    // which request was waiting when a failure occurred before the service
    // received it, so a catalog read keeps its operation context even when the
    // failure is a connection problem. It is appended to the copied technical
    // line only and is never part of the wire envelope.
    public var requestContext: String?
    // Host-only extension startup details. This is intentionally omitted from
    // the service wire envelope and appended only to copied technical details.
    public let launchContext: LaunchContext?
    public init(operation: String, stage: Stage, code: Code = .failed, id: String,
                underlying: Error? = nil, retryable: Bool? = nil, safeCause: SafeCause? = nil,
                sourceStep: SourceStep? = nil, signingContext: [String: String] = [:],
                launchContext: LaunchContext? = nil) {
        let normalized = ["snapshot": "status", "refreshApp": "refresh", "refreshAdmissionBegin": "refresh", "refreshAdmissionEnd": "refresh", "installURL": "install", "installSharedIPA": "install",
                          "addSource": "source", "removeSource": "source", "refreshSources": "source", "syncAppIDs": "signIn",
                          "authBegin": "signIn", "authPoll": "signIn", "authRespond": "signIn", "authCancel": "signIn",
                          "authRetryProvisioning": "signIn", "authReconcileStorage": "signIn",
                          "opStart": "command", "opPoll": "command", "opAnswer": "command", "opCancel": "command",
                          "recoveryDiscardUnreadable": "recovery",
                          "sourcePreview": "source", "sourceAddConfirmed": "source", "sourceRemoveConfirmed": "source"][operation] ?? operation
        self.operation = Self.operations.contains(normalized) ? normalized : "command"
        self.stage = stage; self.code = code
        correlationID = UUID(uuidString: id) != nil ? id : UUID().uuidString
        let error = underlying as NSError?
        let safeUnderlying = Self.safeWireUnderlying(domain: error?.domain ?? "none", code: error?.code ?? 0)
        underlyingDomain = safeUnderlying.domain
        underlyingCode = safeUnderlying.code
        let inferredSourceAddBusy = operation == "sourceAddConfirmed" && code == .busy
            ? SafeCause.sourceAddBusy : nil
        self.safeCause = safeCause ?? inferredSourceAddBusy
        self.sourceStep = sourceStep
        var context = Self.validatedSigningContext(signingContext) ?? [:]
        let selectionScope = normalized == "refresh" && stage == .command && code == .failed && sourceStep == .refreshApplication
        let preparationScope = normalized == "refresh" && stage == .signing && code == .failed && sourceStep == .provisioningProfileFetch
        let local = context["local_precondition"] ?? ""
        if !(selectionScope && Self.refreshSelectionPreconditions.contains(local)) &&
            !(preparationScope && (["missingTargetAppBundle", "unknownTeamType", "unresolvedAppGroupPlaceholder", "missingProgressWeight", "invalidProgressReuse", "missingPipelineStepMapping"].contains(local) || Self.preservationRefreshPreconditions.contains(local))) {
            context.removeValue(forKey: "local_precondition")
        }
        let preservationScope = preparationScope && Self.preservationRefreshPreconditions.contains(local)
        if !(selectionScope || preservationScope) || context["local_precondition"] == nil { context.removeValue(forKey: "refresh_target_scope") }
        if !(selectionScope || preservationScope) || context["local_precondition"] != "preservationAuthorityConflict" {
            context.removeValue(forKey: "preservation_conflict")
        }
        if !(selectionScope || preservationScope) || !Self.preservationRefreshPreconditions.contains(context["local_precondition"] ?? "") {
            context.removeValue(forKey: "signing_certificate_source")
        }
        if normalized != "refresh" || stage != .command || code != .failed || sourceStep != .refreshReadiness {
            context.removeValue(forKey: "refresh_readiness_reason")
        }
        // The real signing NSError wrapper records unknownSigningCause even for
        // typed preservation refusals. It is not a competing concrete diagnosis.
        if !(selectionScope || preservationScope) ||
            (self.safeCause != nil && self.safeCause != .unknownSigningCause) ||
            context["preservation_conflict"] != "embeddedDERUnsupportedSigner" {
            context.removeValue(forKey: V3CMSSignerDiagnostic.contextKey)
        }
        if !(selectionScope || preservationScope) ||
            (self.safeCause != nil && self.safeCause != .unknownSigningCause) ||
            context["local_precondition"] != "preservationEvidenceUnavailable" {
            context.removeValue(forKey: "apple_profile_origin")
        }
        // Local profile evidence observations describe only this signing guard.
        if !preservationScope ||
            (self.safeCause != nil && self.safeCause != .unknownSigningCause) ||
            context["local_precondition"] != "preservationEvidenceUnavailable" {
            context.removeValue(forKey: "preservation_evidence")
        }
        // Portal-list observations are optional and only describe this signing guard.
        if !preservationScope ||
            (self.safeCause != nil && self.safeCause != .unknownSigningCause) ||
            context["local_precondition"] != "preservationPortalIdentityUnavailable" {
            context.removeValue(forKey: "preservation_portal_identity")
        }
        self.signingContext = context
        self.retryable = retryable ?? self.safeCause?.inferredRetryable
        let launchStages: Set<Stage> = [.extensionDiscovery, .extensionLaunch, .xpcConnection, .serviceReadiness]
        self.launchContext = normalized == "connect" && launchStages.contains(stage) ? launchContext : nil
    }
    private static let operations: Set<String> = ["connect", "status", "command", "recovery", "refresh", "install", "update", "signIn", "signOut", "catalog", "source", "sign", "activate", "deactivate", "delete", "remove", "backup", "restore", "jit", "pairingImportData", "pairingUsePlaced", "anisetteList", "anisetteReset", "anisetteSync"]
    private static let domains: Set<String> = ["none", "NSCocoaErrorDomain", "NSPOSIXErrorDomain", "NSURLErrorDomain", "NSOSStatusErrorDomain", "ALTServerErrorDomain", "ALTAppleAPIErrorDomain", "ALTErrorDomain", "MinimuxerError", "DeviceGatewayError", "IdeviceGatewayError", "InstallationProxyErrorDomain", "com.apple.installd", "com.apple.mobile.installation_proxy", "V3IPAFileErrorDomain", "Foundation", "CoreData", "CoreFoundation", "IOKit", "Security", "CFNetwork", "kCFErrorDomainCFNetwork", "HTTPStatus", "io.sidestore.SideStore.DecodingError", "io.sidestore.LiveContainer.ExtensionLaunch", "com.SideStore.Keychain", "LiveContainerRefresh.Configuration", "SideSign.ServerError", "SideSign.DeveloperPortalError"]
    private static let verificationDomains: Set<String> = ["ALTServerErrorDomain", "ALTErrorDomain", "IdeviceGatewayError", "DeviceGatewayError", "InstallationProxyErrorDomain", "com.apple.installd", "com.apple.mobile.installation_proxy"]

    /// Only observations from the request/operation context are allowed here.
    /// Never accept provider messages, tokens, account names or device IDs.
    public static let signingCapabilityNames: Set<String> = [
        "APG3427HIY", "IAD53UNK2F", "gameCenter", "inAppPurchase", "push",
        "associatedDomains", "dataProtection", "siri", "applePay", "vpn", "networkExtensions",
        "multipath", "hotspot", "nfc", "classKit", "autoFillCredentialProvider",
        "accessWiFiInformation", "wirelessAccessoryConfiguration", "increasedMemoryLimit",
        "extendedVirtualAddressing", "increasedDebuggingMemoryLimit"
    ]
    public static func validatedWireSigningContext(_ supplied: Any) -> [String: String]? {
        guard var fields = supplied as? [String: Any] else { return nil }
        if fields["preservation_evidence"] != nil &&
            (!(fields["preservation_evidence"] is String) || fields.count > 20) {
            fields.removeValue(forKey: "preservation_evidence")
        }
        if fields["preservation_portal_identity"] != nil &&
            (!(fields["preservation_portal_identity"] is String) || fields.count > 20) {
            fields.removeValue(forKey: "preservation_portal_identity")
        }
        if fields["apple_profile_origin"] != nil &&
            (!(fields["apple_profile_origin"] is String) || fields.count > 20) {
            fields.removeValue(forKey: "apple_profile_origin")
        }
        if fields[V3CMSSignerDiagnostic.contextKey] != nil &&
            (!(fields[V3CMSSignerDiagnostic.contextKey] is String) || fields.count > 20) {
            fields.removeValue(forKey: V3CMSSignerDiagnostic.contextKey)
        }
        if fields["refresh_readiness_reason"] != nil && !(fields["refresh_readiness_reason"] is String) {
            fields.removeValue(forKey: "refresh_readiness_reason")
        }
        if fields["local_precondition"] != nil && !(fields["local_precondition"] is String) {
            fields.removeValue(forKey: "local_precondition")
        }
        if fields["refresh_target_scope"] != nil && !(fields["refresh_target_scope"] is String) {
            fields.removeValue(forKey: "refresh_target_scope")
        }
        if fields["signing_certificate_source"] != nil && (!(fields["signing_certificate_source"] is String) || fields.count > 20) {
            fields.removeValue(forKey: "signing_certificate_source")
        }
        if fields["preservation_conflict"] != nil && (!(fields["preservation_conflict"] is String) || fields.count > 20) {
            fields.removeValue(forKey: "preservation_conflict")
        }
        guard let strings = V3AuthenticationDiagnostics.sanitizingWireContext(fields) else { return nil }
        return validatedSigningContext(strings)
    }
    public static let refreshSelectionPreconditions: Set<String> = ["missingTargetAppBundle", "missingRefreshProfiles", "missingInstalledRecord", "missingMainProfile", "missingVerifiedCertificate", "mainProfileIdentityMismatch", "mainProfileExpired", "mainProfileCertificateMismatch", "extensionOutsideParent", "extensionProfileIdentityMismatch", "extensionProfileExpired", "extensionProfileCertificateMismatch", "extensionTeamMismatch", "legacyProofUnavailable", "legacyHostProofUnavailable", "missingExtensionProfile", "unexpectedProfileKeys", "inconsistentProfileUUID", "unexpectedProfileUUID", "preservationIdentityUnavailable", "preservationMalformedProfile", "preservationEvidenceUnavailable", "preservationAuthorityConflict", "preservationUUIDConflict", "preservationAuthorizationChanged", "preservationExpiredCertificate", "preservationNotExtended", "preservationSnapshotChanged", "preservationPortalIdentityUnavailable"]
    /// Finite Apple-origin read observations, never provider text or a trust verdict.
    public static let preservationEvidenceKinds: Set<String> = ["incompatibleMode", "missingCertificate", "missingReader", "readFailed", "emptyInventory", "noMatchingProfile", "inventoryCountLimit", "emptyProfile", "profileSizeLimit", "inventorySizeLimit", "processingTimeLimit", "missingOrigin", "candidateMismatch"]
    public static let preservationPortalIdentityKinds: Set<String> = ["invalidHTTPResponse", "httpFailure", "missingStatus", "unsuccessfulStatus", "missingList", "nullList", "malformedList", "malformedRecord", "conflictingRecord", "requestUnavailable", "emptyList", "noExactMatch", "ambiguousMatch", "caseOnlyMatch"]
    public static let appleProfileOriginKinds: Set<String> = ["requestUnavailable", "recordNotFound", "ambiguousRecord", "responseMismatch", "invalidResponse", "responseTooLarge", "operationCancelled", "operationExpired", "ownershipChanged"]
    public static let preservationConflictKinds: Set<String> = ["multipleIdentities", "alternateIdentity", "teamMismatch", "prefixMismatch", "signerMissing", "entitlementsDiffer", "certificatesDiffer", "devicesDiffer", "platformsDiffer", "embeddedDERDiffer", "displayMetadataDiffer", "otherAuthorityDiffer", "embeddedDERUnsupportedSigner", "embeddedDERSignerTimeInvalid", "embeddedDERVerificationFailed", "embeddedDERUnsupportedRepresentation", "embeddedDERBindingMismatch"]
    public static let preservationRefreshPreconditions: Set<String> = ["preservationIdentityUnavailable", "preservationMalformedProfile", "preservationEvidenceUnavailable", "preservationAuthorityConflict", "preservationUUIDConflict", "preservationAuthorizationChanged", "preservationExpiredCertificate", "preservationNotExtended", "preservationSnapshotChanged", "preservationPortalIdentityUnavailable"]
    private static let refreshLocalPreconditions: Set<String> = refreshSelectionPreconditions.union(["unknownTeamType", "unresolvedAppGroupPlaceholder", "missingProgressWeight", "invalidProgressReuse", "missingPipelineStepMapping"])
    public static func validatedSigningContext(_ value: [String: String]) -> [String: String]? {
        var supplied = value
        if supplied.count > 20 { supplied.removeValue(forKey: "preservation_evidence") }
        if supplied.count > 20 { supplied.removeValue(forKey: "preservation_portal_identity") }
        if supplied.count > 20 { supplied.removeValue(forKey: "apple_profile_origin") }
        // This read-only extension never evicts existing failure facts.
        if supplied.count > 20 { supplied.removeValue(forKey: V3CMSSignerDiagnostic.contextKey) }
        // Drop this ancillary extension before other sanitizers can trim existing facts.
        if supplied.count > 20 { supplied.removeValue(forKey: "signing_certificate_source") }
        if supplied.count > 20 { supplied.removeValue(forKey: "preservation_conflict") }
        var fields = V3AuthenticationDiagnostics.sanitizingContext(V3TemporaryADIConsumption.sanitizingContext(supplied))
        if let source = fields["signing_certificate_source"] {
            let verified = source == "verifiedRefreshCache" && fields["signing_certificate_present"] == "true" &&
                fields["signing_certificate_serial_sha256"]?.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil
            let unavailable = source == "unavailable" && fields["signing_certificate_present"] == "false" &&
                fields["signing_certificate_serial_sha256"] == nil
            if !(verified || unavailable) || fields["refresh_failure_kind"] != "invalidParameters" ||
                !Self.preservationRefreshPreconditions.contains(fields["local_precondition"] ?? "") {
                fields.removeValue(forKey: "signing_certificate_source")
            }
        }
        // Optional local subtype cannot invalidate or add privilege to the primary failure.
        if let conflict = fields["preservation_conflict"],
           !Self.preservationConflictKinds.contains(conflict) ||
           fields["local_precondition"] != "preservationAuthorityConflict" ||
           fields["refresh_failure_kind"] != "invalidParameters" || fields.count > 20 {
            fields.removeValue(forKey: "preservation_conflict")
        }
        if let raw = fields[V3CMSSignerDiagnostic.contextKey],
           V3CMSSignerDiagnostic(encoded: raw) == nil ||
           fields["refresh_target_scope"] != "nonHost" ||
           fields["preservation_conflict"] != "embeddedDERUnsupportedSigner" ||
           fields["local_precondition"] != "preservationAuthorityConflict" ||
           fields["refresh_failure_kind"] != "invalidParameters" {
            fields.removeValue(forKey: V3CMSSignerDiagnostic.contextKey)
        }
        if let reason = fields["preservation_evidence"],
           !Self.preservationEvidenceKinds.contains(reason) ||
           fields["refresh_target_scope"] != "nonHost" ||
           fields["local_precondition"] != "preservationEvidenceUnavailable" ||
           fields["refresh_failure_kind"] != "invalidParameters" {
            fields.removeValue(forKey: "preservation_evidence")
        }
        if let reason = fields["preservation_portal_identity"],
           !Self.preservationPortalIdentityKinds.contains(reason) ||
           fields["refresh_target_scope"] != "nonHost" ||
           fields["local_precondition"] != "preservationPortalIdentityUnavailable" ||
           fields["refresh_failure_kind"] != "invalidParameters" {
            fields.removeValue(forKey: "preservation_portal_identity")
        }
        if let origin = fields["apple_profile_origin"],
           origin.utf8.count > 32 || !Self.appleProfileOriginKinds.contains(origin) ||
           fields["refresh_target_scope"] != "nonHost" ||
           fields["local_precondition"] != "preservationEvidenceUnavailable" ||
           fields["refresh_failure_kind"] != "invalidParameters" {
            fields.removeValue(forKey: "apple_profile_origin")
        }
        // This optional observation must never replace or invalidate the primary
        // failure. Admit only the finite local guard vocabulary, with its kind.
        if let local = fields["local_precondition"],
           fields["refresh_failure_kind"] != "invalidParameters" ||
           !Self.refreshLocalPreconditions.contains(local) || fields.count > 20 {
            fields.removeValue(forKey: "local_precondition")
        }
        if let scope = fields["refresh_target_scope"],
           !["host", "nonHost", "unknown"].contains(scope) ||
           !Self.refreshSelectionPreconditions.contains(fields["local_precondition"] ?? "") {
            fields.removeValue(forKey: "refresh_target_scope")
        }
        if let reason = fields["refresh_readiness_reason"] {
            let eligible = (reason == "vpnUnavailable" && fields["refresh_failure_kind"] == "noVPN") ||
                (reason == "peerProbeFailed" && fields["refresh_failure_kind"] == "invalidVPN") ||
                (reason == "peerAddressUnavailable" && fields["refresh_failure_kind"] == "noDevice")
            if !eligible || fields.count > 20 { fields.removeValue(forKey: "refresh_readiness_reason") }
        }
        if !V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled {
            fields.removeValue(forKey: V3TemporaryAnisetteTrace.contextKey)
        }
        // Validate provenance before optional capacity trimming; malformed or
        // orphaned fault data must never become an accepted constructor tuple.
        guard V3AnisetteNativeEvidence.ConstructorFailure.validatesContext(fields) else { return nil }
        if let raw = fields[V3ConstructorFaultDiagnostic.contextKey] {
            guard V3ConstructorFaultDiagnostic(encoded: raw) != nil else { return nil }
            if fields.count > 20 { fields.removeValue(forKey: V3ConstructorFaultDiagnostic.contextKey) }
        }
        guard fields.count <= 20 else { return nil }
        for (key, text) in fields {
            if key == V3ProvisioningCauseDiagnostic.contextKey {
                guard V3ProvisioningCauseDiagnostic.validated(text) != nil else { return nil }; continue
            }
            if key == V3AuthenticationRequestSnapshot.contextKey {
                guard V3AuthenticationRequestSnapshot(encoded: text) != nil else { return nil }; continue
            }
            if key == V3AuthenticationHeaderProvenance.contextKey {
                guard V3AuthenticationHeaderProvenance(encoded: text) != nil else { return nil }; continue
            }
            if key == V3AuthenticationProviderObservation.contextKey {
                guard V3AuthenticationProviderObservation(encoded: text) != nil else { return nil }; continue
            }
            if key == V3AuthenticationDiagnostics.stateKey {
                guard ["recorded", "trimmed", "rejected", "notRecorded"].contains(text) else { return nil }; continue
            }

            if key == V3CMSSignerDiagnostic.contextKey {
                guard V3CMSSignerDiagnostic(encoded: text) != nil else { return nil }
                continue
            }
            if key == V3ConstructorFaultDiagnostic.contextKey {
                guard V3ConstructorFaultDiagnostic(encoded: text) != nil else { return nil }
                continue
            }
            if key == V3LoginDiagnosticSnapshot.contextKey {
                guard V3LoginDiagnosticSnapshot(encoded: text) != nil else { return nil }
                continue
            }
            if key == V3TemporaryADIConsumption.contextKey {
                guard V3TemporaryADIConsumption(encoded: text) != nil else { return nil }
                continue
            }
            if key == V3TemporaryAnisetteTrace.contextKey {
                guard V3TemporaryAnisetteTrace(encoded: text) != nil else { return nil }
                continue
            }
            guard text.utf8.count <= 512 else { return nil }
            switch key {
            case "team_sha256", "requested_bundle_sha256", "requested_app_group_sha256", "capabilities_sha256", "signing_certificate_serial_sha256":
                guard text.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else { return nil }
            case "provisioning_bundle_sha256":
                guard text.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else { return nil }
            case "session_generation", "capability_count", "app_group_count", "extension_count":
                guard !text.isEmpty, text.utf8.count <= 20,
                      text.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }), UInt64(text) != nil else { return nil }
            case "capability_names", "enabled_capability_names":
                let names = text.isEmpty ? [] : text.components(separatedBy: ",")
                guard names.count <= 32, Set(names).isSubset(of: signingCapabilityNames),
                      Set(names).count == names.count else { return nil }
            case "refresh_readiness_reason":
                guard (text == "vpnUnavailable" && fields["refresh_failure_kind"] == "noVPN") ||
                    (text == "peerProbeFailed" && fields["refresh_failure_kind"] == "invalidVPN") ||
                    (text == "peerAddressUnavailable" && fields["refresh_failure_kind"] == "noDevice") else { return nil }
            case "refresh_target_scope":
                guard ["host", "nonHost", "unknown"].contains(text),
                      Self.refreshSelectionPreconditions.contains(fields["local_precondition"] ?? "") else { return nil }
            case "preservation_evidence":
                guard Self.preservationEvidenceKinds.contains(text),
                      fields["refresh_target_scope"] == "nonHost",
                      fields["local_precondition"] == "preservationEvidenceUnavailable",
                      fields["refresh_failure_kind"] == "invalidParameters" else { return nil }
            case "preservation_portal_identity":
                guard Self.preservationPortalIdentityKinds.contains(text),
                      fields["refresh_target_scope"] == "nonHost",
                      fields["local_precondition"] == "preservationPortalIdentityUnavailable",
                      fields["refresh_failure_kind"] == "invalidParameters" else { return nil }
            case "apple_profile_origin":
                guard text.utf8.count <= 32, Self.appleProfileOriginKinds.contains(text),
                      fields["refresh_target_scope"] == "nonHost",
                      fields["local_precondition"] == "preservationEvidenceUnavailable",
                      fields["refresh_failure_kind"] == "invalidParameters" else { return nil }
            case "preservation_conflict":
                guard Self.preservationConflictKinds.contains(text),
                      fields["local_precondition"] == "preservationAuthorityConflict",
                      fields["refresh_failure_kind"] == "invalidParameters" else { return nil }
            case "local_precondition":
                guard fields["refresh_failure_kind"] == "invalidParameters",
                    Self.refreshLocalPreconditions.contains(text) else { return nil }
            case "refresh_failure_kind":
                guard ["invalidParameters", "invalidOperationContext", "notAuthenticated", "unknownResult",
                    "missingAppBundle", "missingProvisioningProfile", "certificateExpired", "certificateRevoked",
                    "customCertificateExpired", "customCertificateRevoked", "certificateChanged", "invalidApp",
                    "invalidPairingFile", "pairingNotComplete", "noDevice", "noConnection", "noVPN", "invalidVPN", "certificateVerificationUnavailable",
                    "notReachable", "minimuxerNotStarted", "timedOut", "unknownOperation", "otherOperation"].contains(text) else { return nil }
            case "server_code":
                guard text == "unknown" || (text.utf8.count <= 20 && Int(text).map({ String($0) }) == text) else { return nil }
            case "native_code", "native_subcode", "probe_native_code", "probe_native_subcode":
                guard text == "unknown" || Int32(text).map({ String($0) }) == text else { return nil }
            case "anisette_blob_state":
                guard V3AnisetteAttemptContext.BlobState(rawValue: text) != nil else { return nil }
            case "anisette_recovery":
                guard V3AnisetteAttemptContext.Recovery(rawValue: text) != nil else { return nil }
            case "native_init_kind", "native_init_reason", "native_init_engine", "native_init_library", "native_init_initializer":
                break // Validate the entire tuple and its native provenance below.
            case "native_phase", "probe_native_phase":
                guard V3AnisetteNativeEvidence.Phase(rawValue: text) != nil else { return nil }
            case "auth_response_mime":
                guard fields["typed_error"] == "sideSignInvalidResponse",
                      V3AccountOperationError.AuthResponseMIME(rawValue: text) != nil else { return nil }
            case "auth_response_shape":
                guard fields["typed_error"] == "sideSignInvalidResponse",
                      V3AccountOperationError.AuthResponseShape(rawValue: text) != nil else { return nil }
            case "http_status":
                guard text == "unavailable" || Int(text).map({ (100...599).contains($0) && String($0) == text }) == true else { return nil }
            case "provider_code":
                guard ["unavailable", "ENTITY_ERROR", "ENTITY_ERROR.INVALID", "ENTITY_ERROR.ATTRIBUTE.INVALID",
                    "ENTITY_ERROR.ATTRIBUTE.REQUIRED", "ENTITY_ERROR.ATTRIBUTE.UNKNOWN",
                    "ENTITY_ERROR.RELATIONSHIP.INVALID", "ENTITY_ERROR.RELATIONSHIP.INVALID_NOT_ALLOWED",
                    "ENTITY_ERROR.ATTRIBUTE.INVALID.DUPLICATE", "FORBIDDEN_ERROR", "NOT_FOUND",
                    "PARAMETER_ERROR.INVALID", "PARAMETER_ERROR.REQUIRED", "RATE_LIMIT_EXCEEDED",
                    "SERVICE_UNAVAILABLE", "UNEXPECTED_ERROR", "UNKNOWN_ERROR"].contains(text) else { return nil }
            case "account_binding", "team_binding":
                guard text == "verified" else { return nil }
            case "signing_certificate_source":
                guard ["verifiedRefreshCache", "unavailable"].contains(text),
                      fields["refresh_failure_kind"] == "invalidParameters",
                      Self.preservationRefreshPreconditions.contains(fields["local_precondition"] ?? "") else { return nil }
            case "signing_certificate_present":
                guard text == "true" || text == "false" else { return nil }
            case "preferred_parent_id_match":
                guard text == "true" || text == "false" else { return nil }
            case "provisioning_bundle_role":
                guard text == "main" || text == "extension" else { return nil }
            case "profile_mode":
                guard text == "team" || text == "manual" else { return nil }
            case "device_registration":
                guard text == "unobserved" else { return nil }
            case "typed_error":
                guard ["sideSignServerReportedError", "sideSignBadResponse", "sideSignInvalidResponse", "sideSignMissingKey", "sideSignDeveloperPortalError", "keychainWrite", "keychainValidationFailed", "keychainOutcomeUnknown", "legacyMigrationConflict", "persistenceFailure", "persistenceOutcomeUnknown", "transportFailure", "anisetteFailure", "anisetteKitInvalidArgument", "anisetteKitLoaderFailed", "anisetteKitSymbolMissing", "anisetteKitReadFailure", "anisetteKitInvalidResponse", "anisetteKitADIError", "anisetteKitLibrariesNotFound", "anisetteKitHTTPError", "decodingTypeMismatch", "decodingValueNotFound", "decodingKeyNotFound", "decodingDataCorrupted", "archiveFileNotFound", "archiveCorrupt", "archiveReadFailed", "archiveWriteFailed", "archiveMissingApp", "unknownAccountFailure", "anisetteIdentityStateInvalid", "remoteIdentityInvalidRecord", "remoteIdentityStorageUnverified", "remoteIdentityStateChanged", "remoteIdentityManualSignInRequired"].contains(text) || V3AccountOperationError.AcquisitionFailure(rawValue: text) != nil else { return nil }
            default: return nil
            }
        }
        guard V3AnisetteNativeEvidence.ConstructorFailure.validatesContext(fields) else { return nil }
        return fields
    }

    /// Copyable diagnostics may include a native code only when its domain is
    /// in the same fixed allowlist used by structured failures. Arbitrary NSError
    /// domains can contain endpoint or user supplied text, so both fields are
    /// suppressed together when provenance is not recognized.
    public static func safeDiagnosticUnderlying(domain: String, code: Int) -> (domain: String, code: String) {
        guard (Self.domains.contains(domain) && domain != "none") || (domain == "none" && code == 0) else {
            return ("redacted", "unknown")
        }
        return (domain, String(code))
    }

    /// Safe technical fields for the provisioning retry prompt. Preserve the
    /// area/correlation context, but never interpolate an untrusted NSError.
    public static func provisioningRetryTechnicalDetails(for error: Error,
                                                         correlationID: String, requestTrace: String? = nil, headerProvenance: String? = nil,
                                                         providerObservation: String? = nil, loginTrace: String? = nil) -> String {
        if let accountError = error as? V3AccountOperationError {
            let failure = accountError.failure(operation: "signIn", id: correlationID)
            let wire = V3AuthenticationDiagnostics.attaching(requestTrace: requestTrace, headerProvenance: headerProvenance,
                providerObservation: providerObservation, loginTrace: loginTrace, to: failure.wire)
            return "area=provisioning " + (Self.decode(wire, expectedID: correlationID)?.technicalDetails ?? failure.technicalDetails)
        }
        let native = error as NSError
        let underlying = safeDiagnosticUnderlying(domain: native.domain, code: native.code)
        let safeID = UUID(uuidString: correlationID)?.uuidString ?? UUID().uuidString
        return "diagnostic_code=SS-PROV-C11 builder_commit=\(V3DiagnosticBuild.commit) domain=\(underlying.domain) code=\(underlying.code) area=provisioning correlation=\(safeID)" + V3AuthenticationDiagnostics.technicalDetails(V3AuthenticationDiagnostics.attaching(requestTrace: requestTrace, headerProvenance: headerProvenance, providerObservation: providerObservation, loginTrace: loginTrace, to: [:])["signingContext"] as? [String: String] ?? [:])
    }

    /// The serialized wire keeps an integer field for compatibility. `none/0`
    /// means no underlying error; `redacted/0` means native details were hidden.
    /// The reserved `none` domain never authorizes a nonzero native code.
    fileprivate static func safeWireUnderlying(domain: String, code: Int) -> (domain: String, code: Int) {
        // `none` is reserved for absence of an underlying error; it does not
        // establish provenance for a caller-supplied numeric code.
        guard (Self.domains.contains(domain) && domain != "none") || (domain == "none" && code == 0) else {
            return ("redacted", 0)
        }
        return (domain, code)
    }

    private var timeoutAction: String {
        switch operation {
        case "connect": return "connect to SideStore"
        case "status": return "load status"
        case "refresh": return "refresh apps"
        case "install": return "install the app"
        case "update": return "update the app"
        case "delete": return "delete the app"
        case "signIn": return "sign in"
        case "signOut": return "sign out"
        case "source": return "load the source"
        case "catalog": return "load the catalog"
        default: return "complete the request"
        }
    }
    private var timeoutContext: String {
        switch stage {
        case .hostContainer, .storagePreparation, .bookmarkCreation:
            return "using the shared app container"
        case .extensionDiscovery, .extensionLaunch:
            return "starting the LiveProcess extension"
        case .xpcConnection:
            return "connecting to the SideStore service"
        case .serviceReadiness:
            return "waiting for SideStore to finish starting"
        case .authentication:
            return "checking the Apple account"
        case .provisioning:
            return "preparing provisioning data"
        case .signing:
            return "signing the app"
        case .filePreparation:
            return "preparing the selected IPA"
        case .installation:
            return "installing the app"
        case .persistence:
            return "saving the operation result"
        case .refreshVerification:
            return "verifying the refresh result"
        case .replyEncoding:
            return "preparing the service response"
        case .endpointSelection, .heartbeat, .coreDevice, .cdTunnel, .rsdDiscovery,
             .rsdService, .lockdownConnection, .uniqueDeviceID:
            return "connecting to the device"
        case .pairing:
            return "checking the pairing data"
        case .network:
            return "checking the network connection"
        case .source:
            return "loading the source"
        case .catalog:
            return "loading the source catalog"
        case .command:
            return "waiting for SideStore to finish the request"
        }
    }
    // Local finite observations only. These do not diagnose an Apple rejection,
    // expired login, or a VPN that is definitely switched off.
    private var localRefreshPrecondition: String? {
        guard operation == "refresh", stage == .signing, code == .failed,
              sourceStep == .provisioningProfileFetch,
              safeCause == nil || safeCause == .unknownSigningCause,
              signingContext["refresh_failure_kind"] == "invalidParameters" else { return nil }
        return signingContext["local_precondition"]
    }
    private var refreshReadinessVPNKind: String? {
        guard operation == "refresh", code == .failed, sourceStep == .refreshReadiness,
              safeCause == nil, let kind = signingContext["refresh_failure_kind"],
              ["noVPN", "invalidVPN"].contains(kind) else { return nil }
        return kind
    }
    private var localDevVPNActivationMessage: String? {
        guard operation == "refresh", stage == .network,
              safeCause == .localDevVPNUnavailable else { return nil }
        switch code {
        case .unavailable:
            return "LiveContainer could not open LocalDevVPN. Install/open it, enable the connection, then retry."
        case .timedOut:
            return "LocalDevVPN did not return before the activation wait ended. Return to LiveContainer and retry after enabling it."
        default: return nil
        }
    }
    private var refreshSelectionPrecondition: String? {
        guard operation == "refresh", code == .failed,
              signingContext["refresh_failure_kind"] == "invalidParameters",
              let token = signingContext["local_precondition"],
              Self.refreshSelectionPreconditions.contains(token),
              (stage == .command && sourceStep == .refreshApplication) ||
                (stage == .signing && sourceStep == .provisioningProfileFetch && Self.preservationRefreshPreconditions.contains(token)) else { return nil }
        return token
    }
    private var localRefreshMessage: String? {
        switch refreshSelectionPrecondition {
        case "missingTargetAppBundle": return "The target app bundle required for this refresh is missing."
        case "missingRefreshProfiles": return "The refresh has no provisioning profiles to install."
        case "missingInstalledRecord": return "The installed app record required for this refresh is missing."
        case "missingMainProfile": return "The main app provisioning profile could not be selected."
        case "missingVerifiedCertificate": return "The verified signing certificate required to select profiles is missing."
        case "mainProfileIdentityMismatch": return "The selected main profile does not authorize the app identity."
        case "mainProfileExpired": return "The selected main profile has already expired."
        case "mainProfileCertificateMismatch": return "The selected main profile does not contain the verified signing certificate."
        case "extensionOutsideParent": return "An app extension is outside the parent app identity."
        case "extensionProfileIdentityMismatch": return "A selected extension profile does not authorize that extension."
        case "extensionProfileExpired": return "A selected extension profile has already expired."
        case "extensionProfileCertificateMismatch": return "A selected extension profile does not contain the verified signing certificate."
        case "extensionTeamMismatch": return "An extension profile belongs to a different team than the main profile."
        case "preservationIdentityUnavailable": return "Refresh stopped because the historical app identity and signing certificate could not be linked. The installed app was preserved."
        case "preservationMalformedProfile": return "Refresh stopped because a profile contains unsupported or incomplete authorization data. The installed app was preserved."
        case "preservationEvidenceUnavailable": return "Refresh stopped because the profiles could not be read and matched safely. The installed app was preserved."
        case "preservationAuthorityConflict": return "Refresh stopped because observed profile constraints are ambiguous or conflicting. The installed app was preserved."
        case "preservationUUIDConflict": return "Refresh stopped because one profile identifier refers to conflicting profile contents. The installed app was preserved."
        case "preservationAuthorizationChanged": return "Refresh stopped because the new profile would change existing authorization or signing certificates. The installed app was preserved."
        case "preservationExpiredCertificate": return "Refresh stopped because the existing signing certificate is no longer valid. Profile-only renewal cannot extend the certificate. The installed app was preserved."
        case "preservationNotExtended": return "Refresh stopped because the new profile does not extend effective validity. The installed app was preserved."
        case "preservationSnapshotChanged": return "Refresh stopped because the device profile inventory changed during verification. The installed app was preserved."
        case "preservationPortalIdentityUnavailable": return "Refresh stopped because the existing developer account app identity could not be matched without changing it. The installed app was preserved."
        case "legacyProofUnavailable": return "The installed app could not be linked to sufficient refresh evidence. This does not mean its signature is invalid. The app has not been replaced."
        case "legacyHostProofUnavailable": return "The older host app identity could not be safely verified for this refresh."
        case "missingExtensionProfile": return "A required app extension has no selected provisioning profile."
        case "unexpectedProfileKeys": return "The profile selection contains unexpected app identities."
        case "inconsistentProfileUUID": return "The same profile UUID refers to conflicting profile contents."
        case "unexpectedProfileUUID": return "The profile selection contains an unexpected profile UUID."
        default: break
        }
        if sourceStep == .certificateValidation, signingContext["refresh_failure_kind"] == "certificateVerificationUnavailable" {
            return "Certificate verification is unavailable. This does not mean the certificate was revoked. Check the connection and review this app’s verification status."
        }
        switch localRefreshPrecondition {
        case "missingTargetAppBundle":
            return "SideStore could not prepare provisioning profiles because the target app bundle was missing from the refresh context."
        case "unknownTeamType":
            return "SideStore did not recognize the selected team type while preparing provisioning features."
        case "unresolvedAppGroupPlaceholder":
            return "The app's signing entitlements still contain an unresolved app-group placeholder."
        case "missingProgressWeight":
            return "The refresh pipeline has no progress entry for provisioning-profile preparation."
        case "invalidProgressReuse":
            return "The refresh pipeline has an invalid progress reuse limit for provisioning-profile preparation."
        case "missingPipelineStepMapping":
            return "The refresh pipeline could not map the provisioning-profile operation to its step."
        default: break
        }
        if refreshReadinessVPNKind == "noVPN" {
            return "SideStore's refresh readiness check could not find a usable local VPN connection."
        }
        if refreshReadinessVPNKind == "invalidVPN" {
            return "SideStore's refresh readiness check could not validate the local VPN connection."
        }
        return nil
    }
    private var localRefreshRecovery: String? {
        if refreshSelectionPrecondition != nil {
            return "This target stopped before profile installation. Copy Diagnostics to check its profile selection. Do not reset account or VPN settings based on this error alone."
        }
        switch localRefreshPrecondition {
        case "unresolvedAppGroupPlaceholder":
            return "Check the app's signing entitlements and build configuration. Copy Diagnostics before retrying with a corrected build."
        case "missingTargetAppBundle", "unknownTeamType", "missingProgressWeight", "invalidProgressReuse", "missingPipelineStepMapping":
            return "Copy Diagnostics to review the local refresh setup. This observation does not establish an account or provisioning-service failure."
        default: break
        }
        if refreshReadinessVPNKind != nil {
            return "Check the local VPN connection and its SideStore configuration, then retry."
        }
        return nil
    }
    public var isTerminalDatabaseStartupFailure: Bool {
        guard let safeCause else { return false }
        return stage == .serviceReadiness && code == .failed && retryable == false &&
            [.databaseLayoutBlocked, .databaseLayoutConflict, .databaseAppGroupUnavailable,
             .databasePersistenceFailed, .databaseStartupFailed, .databaseHostBundleUnavailable, .databaseHostProfileUnavailable, .databaseModelUnrecognized, .databaseMigrationPathUnavailable, .databaseMigrationFailed, .databaseSaveFailed].contains(safeCause)
    }
    private var databaseStartupMessage: String? {
        guard isTerminalDatabaseStartupFailure else { return nil }
        switch safeCause {
        case .databaseLayoutBlocked:
            return "SideStore stopped startup because its private data layout could not be verified."
        case .databaseLayoutConflict:
            return "SideStore stopped startup because conflicting saved data locations were found."
        case .databaseAppGroupUnavailable:
            return "SideStore could not access its required shared storage."
        case .databasePersistenceFailed:
            return "SideStore could not open or prepare its saved database."
        case .databaseStartupFailed:
            return "SideStore database startup failed before readiness."
        case .databaseHostBundleUnavailable:
            return "SideStore could not read the installed host application bundle."
        case .databaseHostProfileUnavailable:
            return "SideStore could not read the host application provisioning profile."
        case .databaseModelUnrecognized:
            return "This build does not recognize the saved database model."
        case .databaseMigrationPathUnavailable:
            return "No supported migration path was found for the saved database."
        case .databaseMigrationFailed:
            return "Database migration reported a failure. The saved data state needs review."
        case .databaseSaveFailed:
            return "SideStore could not save its database changes during startup."
        default: return nil
        }
    }
    public var message: String {
        if let startup = databaseStartupMessage { return startup }
        if let message = V3AccountOperationError.remoteIdentityMessage(signingContext["typed_error"]) { return message }
        if signingContext["typed_error"] == "anisetteIdentityStateInvalid" { return LCAnisettePairError.safeMessage }
        if operation == "delete", code == .timedOut {
            return "SideStore could not confirm that the deleted app disappeared from its installed library."
        }
        // V3_CATALOG_FAILURE_VOCABULARY_V1: a catalog read must never surface as
        // the generic command-stage message. It can fail at a stage that is not
        // the catalog stage, so the operation selects this wording first.
        //
        // V3_RESPONSE_CLASSIFICATION_CARRIER_V1: the two reply-level causes are
        // the exception. They describe the reply itself rather than the catalog,
        // and the catalog vocabulary covered both of them with one sentence, so
        // a reply that could not be encoded and a reply that was too large read
        // identically to a user. The specific cause outranks it.
        if operation == "catalog", safeCause != .responseEncodingFailed,
           safeCause != .responseTooLarge, let catalog = catalogFailureMessage { return catalog }
        if code == .cancelled { return "The \(operation) request was cancelled. Its result may need reconciliation." }
        if let activation = localDevVPNActivationMessage { return activation }
        if code == .timedOut { return "SideStore could not \(timeoutAction) in time while \(timeoutContext)." }
        if let local = localRefreshMessage { return local }
        if let safeCause {            switch safeCause {
            case .databaseLayoutBlocked, .databaseLayoutConflict, .databaseAppGroupUnavailable, .databasePersistenceFailed, .databaseStartupFailed, .databaseHostBundleUnavailable, .databaseHostProfileUnavailable, .databaseModelUnrecognized, .databaseMigrationPathUnavailable, .databaseMigrationFailed, .databaseSaveFailed:
                break
            case .networkConnectionLost: return "The network connection was lost during \(operation)."
            case .networkTimedOut: return "The network request timed out during \(operation)."
            case .networkUnavailable: return "A network connection was unavailable during \(operation)."
            case .anisetteServerUnavailable: return "The configured Anisette server is temporarily unavailable."
            case .anisetteServerRejected: return "The configured Anisette server returned an unsuccessful response."
            case .anisetteRequestTimedOut: return "The configured Anisette server timed out while synchronizing."
            case .anisetteRateLimited: return "The configured Anisette server is temporarily rate-limiting synchronization requests."
            case .anisetteInvalidResponse: return "The configured Anisette server returned data SideStore could not read."
            case .anisetteUnknownFailure: return "Anisette server synchronization failed for an unknown reason."
            case .signingNetworkConnectionLost: return "The connection to the provisioning service was interrupted during signing."
            case .signingNetworkTimedOut: return "The provisioning service did not respond during signing."
            case .signingNetworkUnavailable: return "The signing flow could not reach the provisioning service."
            case .developerPortalRejectedRequest:
                return "Apple's developer service reported an error \(sourceStep?.portalUserLabel ?? "while preparing the app's provisioning data")."
            case .appIDLimitReached: return "App ID limit reached. Apple could not register another App ID for the selected team."
            case .developerPortalInvalidResponse: return "The provisioning service returned an invalid response during signing."
            case .provisioningProfileUnavailable: return "A required provisioning profile is not available for this app."
            case .certificateUnavailable: return "The selected signing certificate is not available."
            case .signingStorageUnverified: return "SideStore cannot change Apple certificates while saved signing state is unverified."
            case .wifiUnavailable: return "Wi-Fi was unavailable before refresh started."
            case .localDevVPNUnavailable: return "LocalDevVPN was unavailable before refresh started."
            case .unknownSigningCause: return "SideStore could not sign the selected app. The exact underlying cause could not be safely identified."
            case .sourceNetworkFailure: return "The source could not be downloaded because its network request failed."
            case .sourceInvalidManifest: return "The source returned data SideStore could not read as a valid source."
            case .sourcePersistenceUnverified: return "SideStore could not confirm that the source was saved."
            case .sourceInvalidURL: return "The source URL is invalid."
            case .sourceBlocked: return "SideStore blocked this source for security reasons."
            case .sourceChangedID: return "SideStore stopped updating this source because its identifier changed."
            case .sourceDuplicate: return "A source with the same identifier is already saved."
            case .sourceUnsupported: return "This source format is not supported by this version of SideStore."
            case .sourceValidationFailed: return "SideStore rejected metadata in this source."
            case .sourceRemoveFailed: return "SideStore could not confirm that the source was removed from its saved list."
            case .sourceRemoveBusy: return "SideStore was busy with another request, so it did not start removing this source."
            case .sourceAddBusy: return "SideStore was busy with another request, so it did not confirm adding this source."
            case .operationInProgress: return "Another SideStore operation is still active."
            case .responseCapacityUnavailable: return "SideStore cannot safely accept another state-changing request yet."
            case .sharedStoreUnavailable: return "LiveContainer could not open the shared store that its refresh state and the embedded SideStore service both use."
    // V3_SECRET_HANDOFF_FAILURE_TYPED_V1: say plainly that the response never
    // left the device, so an Apple password is never implicated.
    case .secretHandoffUnavailable: return "Your response could not be delivered to the embedded service through the secure channel, so it was never sent to Apple. This is not an authentication failure."
            case .staleRefreshAttempt: return "This refresh request belonged to an expired scheduler run and was not started."
            case .knownSourcePolicyNetworkFailure: return "SideStore could not update its own known-source safety list."
            case .knownSourcePolicyInvalidResponse: return "SideStore could not read its own known-source safety list."
            case .catalogUnavailable: return "SideStore could not read this source's saved catalog data."
            case .catalogSourceUnavailable: return "This source is no longer in the SideStore source list."
            case .responseEncodingFailed: return "SideStore could not encode the response for this request."
            case .responseTooLarge: return "SideStore produced a response that is too large to transfer."
            case .pairingRequired: return "A pairing file is required before this device can be refreshed."
            case .invalidPairingFile: return "SideStore could not read or validate the pairing file."
            case .pairingFilePreparationFailed: return "LiveContainer could not read or prepare the selected pairing file."
            case .authAttemptNotDispatched: return "SideStore did not start this sign-in attempt, so Apple authentication was not submitted."
            case .authProvisioningRetryNotDispatched: return "SideStore did not start the provisioning retry; the saved authentication session was not changed by this request."
            case .authSessionUnavailable: return "SideStore no longer has the active sign-in session."
            case .authResponseCapacityUnavailable: return "SideStore could not start sign-in because it cannot safely reserve a response slot yet."
            case .credentialCommitFailed:
                return "Apple authentication succeeded, but the sign-in credentials could not be saved on this device."
            case .credentialCommitOutcomeUnknown:
                return "Apple authentication succeeded, but the local credential save could not be confirmed."
            case .accountActivationFailed:
                return "Authentication succeeded, but SideStore could not confirm that account and team activation was saved."
            case .provisioningStorageFailed:
                return "Authentication succeeded, but provisioning could not save the account or certificate on this device."
            case .keychainSignOutFailed: return "SideStore could not confirm removal of the saved Apple sign-in data. Sign Out stopped, and any partial changes were rolled back."
            case .keychainSignOutOutcomeUnknown: return "SideStore could not confirm the Sign Out outcome. Reload Account & Signing to reconcile which Apple account is active before continuing."
            case .operationPersistenceFailed: return "The device operation may have completed, but SideStore could not confirm that its updated app state was saved."
            case .recoveryMalformedRecord: return "SideStore found a malformed recovery record. Changes remain paused."
            case .recoveryIncompatibleRecord: return "SideStore found a recovery record from an incompatible schema. Changes remain paused."
            case .recoveryStorageUnavailable: return "SideStore cannot access its shared recovery storage. It has not identified a corrupt record."
            case .recoveryLockUnavailable: return "SideStore could not acquire its recovery storage lock."
            case .recoveryReadFailure: return "SideStore could not read the recovery file. Its contents have not been classified."
            case .recoveryDeleteFailure: return "SideStore could not delete and confirm removal of the recovery record."
            case .directRecoveryRecordMissing: return "SideStore no longer has the recovery record for this request."
            case .directRecoveryTargetMismatch: return "A different request now owns SideStore's recovery record."
            case .directRecoveryModeInvalid: return "The recovery request did not specify one valid confirmation mode."
            case .directRecoveryPhaseNotEligible: return "The recovery record is not in a state that accepts this confirmation."
            }
        }
        switch stage {
        case .hostContainer: return "SideStore could not start because the authoritative host container is unavailable."
        case .storagePreparation: return "SideStore could not start because its existing data storage could not be prepared."
        case .bookmarkCreation: return "SideStore could not start because its data bookmark could not be created."
        case .extensionDiscovery: return "The embedded LiveProcess extension is missing or unavailable."
        case .extensionLaunch: return "The embedded SideStore process could not be launched."
        case .xpcConnection: return "The connection to the embedded SideStore service was interrupted or unavailable."
        case .serviceReadiness: return "The SideStore process has not finished preparing its service."
        case .endpointSelection: return "No usable device transport endpoint was selected."
        case .heartbeat: return "The device transport heartbeat is inactive."
        case .coreDevice: return "Could not connect to the device through CoreDevice."
        case .cdTunnel: return "The CoreDevice tunnel could not be established."
        case .rsdDiscovery: return "Device service discovery through RSD failed."
        case .rsdService: return "The requested RSD device service could not be connected."
        case .lockdownConnection: return "The device transport opened, but the lockdownd connection failed."
        case .uniqueDeviceID: return "The device connection opened, but the UniqueDeviceID request failed."
        case .pairing: return "Pairing parsing, validation, or a concrete device trust check failed."
        case .source:
            switch sourceStep {
            case .sourceDownload: return "The source could not be downloaded."
            case .manifestParsing: return "The source returned data SideStore could not read as a valid source."
            case .sourceValidation: return "SideStore rejected the source during validation."
            case .catalogRead: return "SideStore could not confirm that the source was saved or read from its catalog."
            default: return "SideStore could not complete the source request."
            }
        case .catalog:
            // The wording is supplied by catalogFailureMessage, which keys on the
            // operation rather than on this stage.
            return "SideStore could not load this source's catalog."
        case .authentication: return "SideStore could not complete account authentication."
        case .provisioning: return "Apple sign-in succeeded, but device provisioning did not complete."
        case .signing:
            switch sourceStep {
            case .provisioningProfileFetch:
                return "SideStore could not prepare provisioning data for signing. The exact failed request could not be safely identified."
            case .certificateValidation:
                return "SideStore could not validate the signing certificate. The exact underlying cause could not be safely identified."
            case .localCodeSigning:
                return "SideStore could not sign the app locally. The exact underlying cause could not be safely identified."
            default: break
            }
            return underlyingDomain == "redacted" && underlyingCode != 0
                ? "SideStore could not sign the application. The exact underlying cause could not be safely identified."
                : "SideStore could not sign the application."
        case .filePreparation:
            switch code {
            case .invalidToken: return "The staged IPA reference is invalid. Select the file again."
            case .missingFile: return "The staged IPA is no longer available. Select it again."
            case .emptyFile: return "The selected IPA is empty and could not be installed."
            case .invalidPackage: return "The selected file is not a valid IPA app package."
            case .fileAccess: return "The selected IPA could not be read. Check file access and select it again."
            default: return "The selected IPA could not be prepared for installation. Select it again."
            }
        case .installation:
            // Apple-side application verification rejections carry fixed installd
            // codes. These describe profile/identity rejection, never an account
            // ban, and they do not imply a pairing or LocalDevVPN problem.
            if hasApplicationVerificationEvidence && underlyingCode == 0xE8008024 {
                return "iOS reports that the provisioning profile is banned during application verification. Recreating pairing or changing LocalDevVPN settings is unlikely to address this specific error."
            }
            if hasApplicationVerificationEvidence && underlyingCode == 0xE8008018 {
                return "iOS reports that the identity used to sign the executable is no longer valid. The app must be re-signed with a current signing identity."
            }
            return "SideStore could not complete the application installation."
        case .persistence:
            return "SideStore could not confirm that the operation result was saved. The device may already have changed."
        case .refreshVerification: return "Refresh completion could not be verified from the installation results."
        case .network: return "Network error during the \(operation) operation."
        case .replyEncoding: return "SideStore could not encode its service response."
        case .command:
            if underlyingDomain == "redacted" && underlyingCode != 0 {
                return "SideStore could not start or complete the requested \(operation) action. The exact underlying cause could not be safely identified."
            }
            return "SideStore could not start or complete the requested \(operation) action."
        }
    }
    // V3_CATALOG_FAILURE_VOCABULARY_V1: the exact sentence for each boundary a
    // catalog read can fail at, selected by the real stage and code rather than
    // by a generic fallback. The source manifest is never blamed here, because
    // nothing on this path proves the manifest failed to parse.
    private var catalogFailureMessage: String? {
        if safeCause == .catalogSourceUnavailable {
            return "This source is no longer in the SideStore source list."
        }
        if code == .unavailable || code == .notReady || stage == .serviceReadiness {
            return "The SideStore service is not ready to load this source yet."
        }
        if stage == .xpcConnection && code == .interrupted {
            return "The connection to the SideStore service was interrupted while loading the source."
        }
        if code == .busy {
            return "SideStore is still finishing another operation. Wait a moment, then reload the source."
        }
        if code == .invalidResponse {
            return "SideStore returned an unreadable response while loading the source catalog."
        }
        if code == .timedOut {
            return "The SideStore service did not answer while loading this source catalog."
        }
        if stage == .catalog { return "SideStore could not read this source's saved catalog." }
        return nil
    }

    private var catalogFailureRecovery: String? {
        if safeCause == .catalogSourceUnavailable {
            return "Return to Sources and reload the source list, then open the source again if it is still present."
        }
        if code == .unavailable || code == .notReady || stage == .serviceReadiness {
            return "Wait for SideStore to finish starting, then reload the source."
        }
        if code == .busy {
            return "Wait for the current SideStore operation to finish, then reload the source."
        }
        if stage == .xpcConnection || code == .timedOut {
            return "Wait for the SideStore service to become available, then reload the source."
        }
        return "Reload the source catalog. If it continues, copy the safe diagnostics."
    }

    public var recovery: String {
        if isTerminalDatabaseStartupFailure {
            return "Open Operation Logs and copy the startup diagnostics. Keep the existing app and its data; do not delete, reset, or move its database as a workaround."
        }
        if let recovery = V3AccountOperationError.remoteIdentityRecovery(signingContext["typed_error"]) { return recovery }
        if signingContext["typed_error"] == "anisetteIdentityStateInvalid" { return LCAnisettePairError.recovery }
        if let local = localRefreshRecovery { return local }
        // V3_RESPONSE_CLASSIFICATION_CARRIER_V1: the two reply-level causes
        // outrank the catalog recovery for the same reason they outrank its
        // message. Repeating an unencodable request, or the same oversized one,
        // fails identically, so the catalog advice to reload would send the user
        // in a circle.
        if operation == "catalog", safeCause != .responseEncodingFailed,
           safeCause != .responseTooLarge, let catalog = catalogFailureRecovery { return catalog }
        if let safeCause {
            switch safeCause {
            case .databaseLayoutBlocked, .databaseLayoutConflict, .databaseAppGroupUnavailable, .databasePersistenceFailed, .databaseStartupFailed, .databaseHostBundleUnavailable, .databaseHostProfileUnavailable, .databaseModelUnrecognized, .databaseMigrationPathUnavailable, .databaseMigrationFailed, .databaseSaveFailed:
                break
            case .networkConnectionLost, .networkTimedOut, .networkUnavailable:
                return "Check the network used by this request, then retry when the connection is stable. If a device operation still fails, run Connection Check."
            case .anisetteServerUnavailable:
                return "Try syncing again later or choose another configured Anisette server."
            case .anisetteServerRejected:
                return "Check the configured Anisette server address, then sync again after correcting it."
            case .anisetteRequestTimedOut:
                return "Retry once. If the configured Anisette server times out again, choose another server."
            case .anisetteRateLimited:
                return "Wait before retrying once. If the server is still rate-limiting requests, choose another configured Anisette server."
            case .anisetteInvalidResponse:
                return "Choose another configured Anisette server or report that its response could not be read."
            case .anisetteUnknownFailure:
                return "The exact Anisette synchronization cause could not be safely identified. Check the configured server and copy Diagnostics."
            case .signingNetworkConnectionLost, .signingNetworkTimedOut, .signingNetworkUnavailable:
                return "Your current connection may still be healthy. Retry once. If this happens again, open Connection Settings."
            case .developerPortalRejectedRequest, .developerPortalInvalidResponse:
                return "Copy Diagnostics, including the failed request step and server code. The correct recovery action is not yet known."
            case .appIDLimitReached:
                return "Apps with extensions may need multiple App IDs. Check App IDs for the selected team and retry when capacity is available. Repeating the install immediately or changing certificates will not free an App ID slot."
            case .provisioningProfileUnavailable:
                return "The requested provisioning profile was unavailable. Keep the diagnostics before trying the install again."
            case .certificateUnavailable:
                return "Open Certificates and inspect the selected signing certificate before retrying."
            case .wifiUnavailable:
                return "Restore Wi-Fi, then start a new refresh."
            case .localDevVPNUnavailable:
                return "Restore LocalDevVPN, then start a new refresh."
            case .unknownSigningCause:
                return "The exact underlying cause was not safely identified. Copy Diagnostics before trying this action again."
            case .sourceNetworkFailure:
                return "Check the network connection and retry the source request."
            case .sourceInvalidManifest:
                return "Check the source provider's manifest format, then preview it again."
            case .sourceBlocked:
                return "Do not add this source. Verify with the provider that it is safe before trying again."
            case .sourceChangedID:
                return "Contact the source provider before removing the saved source or adding it again."
            case .sourceDuplicate:
                return "Return to Sources and use the existing source. Remove it only after confirming which entry is correct."
            case .sourceUnsupported:
                return "Update SideStore or use a source format supported by this version."
            case .sourceValidationFailed:
                return "Ask the source provider to correct its metadata, then preview it again."
            case .sourcePersistenceUnverified:
                return "Return to Sources and reload the list. Confirm whether the source is present before submitting another add; copy Diagnostics if its status remains unclear."
            case .sourceInvalidURL:
                return "Enter a valid HTTP or HTTPS source URL, then preview it again."
            case .sourceRemoveFailed:
                return "Reload Sources and confirm whether the source is gone. If it remains, remove it again."
            case .sourceRemoveBusy:
                return "Wait for the current SideStore request to finish, reload Sources, then confirm removal again."
            case .sourceAddBusy:
                return "Wait for the current SideStore request to finish, reload Sources, then preview and confirm the add again."
            case .operationInProgress:
                return "Wait for the active SideStore request to finish, check the action's current state, then retry that action if needed."
            case .responseCapacityUnavailable:
                return "Wait for SideStore to release earlier request results, check the current state, then retry this action."
            case .sharedStoreUnavailable:
                return "Relaunch LiveContainer after reinstalling or re-signing it. Nothing was written to a private store, and the next launch can retry this run."
            // V3_SECRET_HANDOFF_FAILURE_TYPED_V1: the recovery is a re-sign that
            // grants every part of the app the same secure group, not another
            // attempt with the same password.
            case .secretHandoffUnavailable:
                return "Your response never left this device, so no Apple password was sent. Re-sign or reinstall LiveContainer so its embedded service shares the app's secure storage group, then submit the response again."
            case .staleRefreshAttempt:
                return "Return to Refresh and start a new refresh. This stale request did not reach SideStore or the device."
            case .knownSourcePolicyNetworkFailure:
                return "Check the network, then retry from Sources. This error came from SideStore's known-source safety list, not the URL you entered."
            case .knownSourcePolicyInvalidResponse:
                return "Try again later. If SideStore keeps receiving unreadable safety-list data, copy Diagnostics and report it."
            case .catalogUnavailable:
                return "Reload the catalog. If it continues, copy the safe diagnostics."
            case .catalogSourceUnavailable:
                return "Return to Sources and reload the source list, then open the source again."
            case .responseEncodingFailed:
                return "The same request cannot fix this reply-encoding failure. Copy Diagnostics and report that the service could not encode its response."
            case .responseTooLarge:
                return "The service reply exceeded the transfer limit. Copy Diagnostics and report this response-size issue; repeating the same request will fail again."
            case .pairingRequired:
                return "Add the pairing file, then retry the refresh."
            case .invalidPairingFile:
                return "Open Pairing File and replace the saved pairing file with a valid one, then retry."
            case .pairingFilePreparationFailed:
                return "Choose the pairing file again and make sure it is accessible to LiveContainer."
            case .authAttemptNotDispatched:
                if code == .busy {
                    return "Wait for the active SideStore operation to finish, then start sign-in again."
                }
                if stage == .serviceReadiness {
                    return "Wait for SideStore to finish starting, then start sign-in again."
                }
                return "Resolve the displayed prerequisite, then start sign-in again."
            case .authProvisioningRetryNotDispatched:
                if code == .busy {
                    return "Wait for the active SideStore operation to finish, then retry provisioning."
                }
                if stage == .serviceReadiness {
                    return "Wait for SideStore to finish starting, then retry provisioning."
                }
                return "Retry provisioning when the displayed prerequisite is ready."
            case .authSessionUnavailable:
                return "Open Account & Signing and start a new sign-in. SideStore will reconcile the current account before proceeding."
            case .authResponseCapacityUnavailable:
                return "Wait for SideStore to release earlier request results, reload account status, then try again. No Apple credentials were submitted."
            case .signingStorageUnverified:
                return "Open Account & Signing and choose Check Saved Signing State. Creating or revoking Apple certificates stays blocked until local storage is verified."
            case .credentialCommitFailed, .credentialCommitOutcomeUnknown:
                return "Reload Account & Signing to reconcile local storage before starting another sign-in. Keep existing account data and copy Diagnostics if this continues."
            case .accountActivationFailed, .provisioningStorageFailed:
                return "Reload Account & Signing before continuing. Keep the authenticated account and certificate; do not repeat Apple resource creation to repair local storage."
            case .keychainSignOutFailed:
                return "Unlock the iPhone and try Sign Out again. If it still fails, copy Diagnostics."
            case .keychainSignOutOutcomeUnknown:
                return "Reload Account & Signing to reconcile which Apple account is active before continuing. Do not assume Sign Out completed."
            case .operationPersistenceFailed:
                return "Reload installed app status and verify the device before starting another mutation. Do not repeat this operation until its state is known."
            case .recoveryMalformedRecord, .recoveryIncompatibleRecord:
                return "Confirm no SideStore operation remains active on the device before clearing this saved record."
            case .recoveryStorageUnavailable:
                return "Keep changes paused. Check that the combined app can access its shared App Group; copy Diagnostics for support. Clearing a record cannot repair unavailable storage."
            case .recoveryLockUnavailable:
                return "Keep changes paused and allow the active SideStore process to finish. Copy Diagnostics if the lock stays unavailable."
            case .recoveryReadFailure:
                return "Keep changes paused. Check device storage access and copy Diagnostics; do not clear an unclassified record."
            case .recoveryDeleteFailure:
                return "Keep changes paused and copy Diagnostics. The record was not confirmed removed."
            case .directRecoveryRecordMissing, .directRecoveryTargetMismatch,
                 .directRecoveryModeInvalid, .directRecoveryPhaseNotEligible:
                return "Reload status and inspect the current recovery request before trying again. No recovery record was cleared by this refusal."
            }
        }
        switch stage {
        case .command where operation == "delete" && code == .timedOut:
            return "Reload the installed app list and verify the deletion before trying another delete."
        case .hostContainer:
            return "Reopen LiveContainer and check that it can access its shared App Group container. Keep existing data intact and copy diagnostics if the host container is still unavailable."
        case .storagePreparation:
            return "Check available storage and access to LiveContainer's shared App Group container. Keep existing data intact and copy diagnostics if preparation still fails."
        case .bookmarkCreation:
            return "LiveContainer could not create access to its internal shared SideStore folder. Check that the App Group container is available; copy diagnostics if the folder still cannot be accessed."
        case .extensionDiscovery:
            return "The combined app could not find its embedded LiveProcess extension. Confirm that the installed app is the combined LiveContainer + SideStore package; do not reset SideStore or guest data. Copy diagnostics if it continues."
        case .serviceReadiness:
            return "Wait for SideStore to finish starting, then retry the request."
        case .authentication, .provisioning, .signing: return "Review Account and Signing, then explicitly retry. Never share credentials or private keys."
        case .source:
            if operation == "sourceAddConfirmed" {
                return "Return to Sources and reload the source list. Check whether it was added before retrying; copy Diagnostics if its status is still unclear."
            }
            return "Return to Sources and review the source result. Copy Diagnostics before retrying if its status is unclear."
        case .catalog:
            // The wording is supplied by catalogFailureRecovery, which keys on
            // the operation rather than on this stage.
            return "Reload the source catalog. If it continues, copy the safe diagnostics."
        case .replyEncoding:
            return "Copy Diagnostics and report the service reply-encoding failure. Repeating the same request will not fix it."
        case .filePreparation: return "Choose the IPA again. SideStore will copy it into private shared staging before starting installation."
        case .installation, .persistence, .refreshVerification: return "Reload authoritative app status and expiration before taking another action. Completion may be uncertain."
        case .endpointSelection, .heartbeat, .coreDevice, .cdTunnel, .rsdDiscovery, .rsdService, .lockdownConnection, .uniqueDeviceID, .network:
            return "Check LocalDevVPN and the device connection, then retry explicitly. This failure alone does not prove invalid pairing."
        default: return "Reload the current status to check the result. If the cause remains unclear, copy Diagnostics before deciding whether to try again."
        }
    }
    public var safeMessage: String { messageWithoutDiagnosticCode + "\n" + diagnosticLabel }
    private var messageWithoutDiagnosticCode: String {
        // A validated finite selection guard is a safe local observation, not a raw error.
        if refreshSelectionPrecondition != nil, let local = localRefreshMessage { return local }
        if operation == "refresh", safeCause == nil {
            return "Refresh failed during \(stage.rawValue), but no safe underlying cause was available."
        }
        if underlyingDomain == "redacted", underlyingCode != 0, safeCause == nil {
            return message + " The exact underlying cause could not be safely identified."
        }
        return message
    }
    public var technicalDetails: String {
        let displayedUnderlyingCode = underlyingDomain == "redacted" ? "unknown" : String(underlyingCode)
        // Portal and other command failures can retain a finite authentication
        // state without opting into sign-in-only request/provider traces.
        let authenticationState: String
        if operation != "signIn", stage == .authentication,
           let state = signingContext[V3AuthenticationDiagnostics.stateKey],
           ["recorded", "trimmed", "rejected", "notRecorded"].contains(state) {
            authenticationState = " auth_diagnostic_state=\(state)"
        } else { authenticationState = "" }
        let signingDetails = signingContext.filter { $0.key != V3CMSSignerDiagnostic.contextKey && $0.key != V3TemporaryAnisetteTrace.contextKey && $0.key != V3TemporaryADIConsumption.contextKey && $0.key != V3LoginDiagnosticSnapshot.contextKey && $0.key != V3ConstructorFaultDiagnostic.contextKey && $0.key != V3AuthenticationRequestSnapshot.contextKey && $0.key != V3AuthenticationHeaderProvenance.contextKey && $0.key != V3AuthenticationProviderObservation.contextKey && $0.key != V3AuthenticationDiagnostics.stateKey && $0.key != V3ProvisioningCauseDiagnostic.contextKey }.sorted(by: { $0.key < $1.key }).map { " \($0.key)=\($0.value)" }.joined()
        return "schema=1 diagnostic_code=\(diagnosticCode) builder_commit=\(V3DiagnosticBuild.commit) operation=\(operation) stage=\(stage.rawValue) code=\(code.rawValue) correlation=\(correlationID) underlying_domain=\(underlyingDomain) underlying_code=\(displayedUnderlyingCode) retryable=\(retryable.map(String.init) ?? "unknown") source_step=\(sourceStep?.rawValue ?? "unknown") safe_cause=\(safeCause?.rawValue ?? "unknown")" + signingDetails + (signingContext[V3CMSSignerDiagnostic.contextKey].flatMap(V3CMSSignerDiagnostic.init(encoded:))?.technicalDetails ?? "") + authenticationState + (signingContext[V3ProvisioningCauseDiagnostic.contextKey].flatMap(V3ProvisioningCauseDiagnostic.init(encoded:))?.technicalDetails ?? "") + (signingContext[V3ConstructorFaultDiagnostic.contextKey].flatMap(V3ConstructorFaultDiagnostic.init(encoded:))?.technicalDetails ?? "") + installVerdict + requestContextSuffix + (launchContext?.technicalDetails ?? "") + (temporaryAnisetteTrace?.technicalDetails ?? "") + (signingContext[V3TemporaryADIConsumption.contextKey].flatMap(V3TemporaryADIConsumption.init(encoded:))?.technicalDetails ?? "") + (signingContext[V3LoginDiagnosticSnapshot.contextKey].flatMap(V3LoginDiagnosticSnapshot.init(encoded:))?.technicalDetails ?? "") + (operation == "signIn" ? V3AuthenticationDiagnostics.technicalDetails(signingContext) : "")
    }
    public var temporaryAnisetteTrace: V3TemporaryAnisetteTrace? {
        signingContext[V3TemporaryAnisetteTrace.contextKey].flatMap(V3TemporaryAnisetteTrace.init(encoded:))
    }
    // Request context is appended only when it was observed.
    private var requestContextSuffix: String {
        guard let requestContext, !requestContext.isEmpty else { return "" }
        return " " + requestContext
    }
    public mutating func annotatingRequest(requestedOperation: String, requestID: String) {
        requestContext = "request_operation=\(requestedOperation) request_correlation=\(requestID)"
    }
    // V3_CATALOG_DIAGNOSTICS_V1: host-only catalog page context. Only the page
    // offset and the returned row count are recorded; never the source
    // identifier, app names, bundle identifiers, or response content.
    public mutating func annotatingCatalogPage(cursor: Int) {
        requestContext = "source_step=catalogRead page_cursor=\(cursor)"
    }
    // Bounded machine classification for Apple-side application verification
    // rejections (InstallationProxy/installd). Only the two fixed installd
    // codes produce a token; every other failure keeps the existing
    // diagnostics byte-identical. Never an account-ban claim.
    private var installVerdict: String {
        guard hasApplicationVerificationEvidence else { return "" }
        if underlyingCode == 0xE8008024 { return " installVerdict=profileBanned" }
        if underlyingCode == 0xE8008018 { return " installVerdict=signingIdentityRejected" }
        return ""
    }
    private var hasApplicationVerificationEvidence: Bool {
        ["install", "update"].contains(operation) && stage == .installation && Self.verificationDomains.contains(underlyingDomain)
    }
    public var errorDescription: String? { safeMessage + "\n" + recovery + "\n" + technicalDetails }
    /// Bind this semantic failure to the request/reply transaction carrying it.
    /// Session IDs and request IDs are distinct: an auth poll can discover a
    /// missing session while answering a different, current XPC request.
    public func correlating(to id: String) -> CombinedFailure {
        CombinedFailure(operation: operation, stage: stage, code: code, id: id,
            underlying: NSError(domain: underlyingDomain, code: underlyingCode),
            retryable: retryable, safeCause: safeCause, sourceStep: sourceStep, signingContext: signingContext,
            launchContext: launchContext)
    }
    public var wire: [String: Any] {
        let safeUnderlying = Self.safeWireUnderlying(domain: underlyingDomain, code: underlyingCode)
        var result: [String: Any] = ["version": 1, "operation": operation, "stage": stage.rawValue, "code": code.rawValue,
            "correlationID": correlationID, "underlyingDomain": safeUnderlying.domain,
            "underlyingCode": safeUnderlying.code]
        if let safeCause { result["safeCause"] = safeCause.rawValue }
        if let sourceStep { result["sourceStep"] = sourceStep.rawValue }
        if !signingContext.isEmpty { result["signingContext"] = signingContext }
        if let retryable { result["retryable"] = retryable }
        result = V3AuthenticationDiagnostics.boundingWire(result)
        result = V3LoginDiagnosticSnapshot.boundingWire(result)
        result = V3TemporaryADIConsumption.boundingWire(result)
        return V3ConstructorFaultDiagnostic.boundingWire(result)
    }
    public var encodedString: String {
        guard let data = try? PropertyListSerialization.data(fromPropertyList: wire, format: .binary, options: 0), data.count <= 4096 else { return "LCFAILURE1:invalid" }
        return "LCFAILURE1:" + data.base64EncodedString()
    }
    public static func fromEncodedString(_ text: String, expectedID: String) -> CombinedFailure? {
        guard text.hasPrefix("LCFAILURE1:"), text.utf8.count <= 6000,
              let data = Data(base64Encoded: String(text.dropFirst(11))), data.count <= 4096,
              let value = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return nil }
        return decode(value, expectedID: expectedID)
    }
    public static func decode(_ value: [String: Any], expectedID: String) -> CombinedFailure? {
        guard Set(value.keys).isSubset(of: ["version", "operation", "stage", "code", "correlationID", "underlyingDomain", "underlyingCode", "retryable", "safeCause", "sourceStep", "signingContext"]),
              Self.strictInteger(value["version"]) == 1,
              Self.uuidCorrelationMatches(value["correlationID"] as? String, expectedID: expectedID),
              let operation = value["operation"] as? String, operations.contains(operation),
              let stageName = value["stage"] as? String, let stage = Stage(rawValue: stageName),
              let codeName = value["code"] as? String, let code = Code(rawValue: codeName),
              let domain = value["underlyingDomain"] as? String, domains.contains(domain) || domain == "redacted",
              let number = Self.strictInteger(value["underlyingCode"]) else { return nil }
        let safeCause: SafeCause?
        if let rawCause = value["safeCause"] {
            guard let causeName = rawCause as? String, let cause = SafeCause(rawValue: causeName) else { return nil }
            safeCause = cause
        } else { safeCause = nil }
        let sourceStep: SourceStep?
        if let rawStep = value["sourceStep"] {
            guard let stepName = rawStep as? String, let step = SourceStep(rawValue: stepName) else { return nil }
            sourceStep = step
        } else { sourceStep = nil }
        let signingContext: [String: String]
        if let raw = value["signingContext"] {
            guard let validated = Self.validatedWireSigningContext(raw) else { return nil }
            signingContext = validated
        } else { signingContext = [:] }
        if let retry = value["retryable"] {
            guard let bool = retry as? NSNumber, CFGetTypeID(bool) == CFBooleanGetTypeID() else { return nil }
        }
        return CombinedFailure(operation: operation, stage: stage, code: code, id: expectedID,
            underlying: NSError(domain: domain, code: number), retryable: value["retryable"] as? Bool,
            safeCause: safeCause, sourceStep: sourceStep, signingContext: signingContext)
    }

    private static func strictInteger(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else {
            return nil
        }
        let type = String(cString: number.objCType)
        guard ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(type) else {
            return nil
        }
        if ["C", "S", "I", "L", "Q"].contains(type) {
            return Int(exactly: number.uint64Value)
        }
        return Int(exactly: number.int64Value)
    }

    public static func preserving(_ error: Error?, operation: String, stage: Stage, code: Code = .failed, id: String, retryable: Bool? = nil,
                                  launchContext: LaunchContext? = nil) -> CombinedFailure {
        if let known = error as? CombinedFailure {
            guard let launchContext else { return known }
            let retainedContext = launchContext.retainingErrorChain(from: known.launchContext)
            return CombinedFailure(operation: known.operation, stage: known.stage, code: known.code,
                id: known.correlationID, underlying: NSError(domain: known.underlyingDomain, code: known.underlyingCode),
                retryable: known.retryable, safeCause: known.safeCause, sourceStep: known.sourceStep,
                signingContext: known.signingContext, launchContext: retainedContext)
        }
        if let launchContext {
            return CombinedFailure(operation: operation, stage: stage, code: code, id: id,
                underlying: error, retryable: retryable, launchContext: launchContext)
        }
        return CombinedFailure(operation: operation, stage: stage, code: code, id: id, underlying: error, retryable: retryable)
    }
    private static func networkSafeCauseForURLCode(_ code: Int, signing: Bool) -> SafeCause? {
        switch code {
        case NSURLErrorNetworkConnectionLost:
            return signing ? .signingNetworkConnectionLost : .networkConnectionLost
        case NSURLErrorTimedOut:
            return signing ? .signingNetworkTimedOut : .networkTimedOut
        case NSURLErrorNotConnectedToInternet, NSURLErrorCannotConnectToHost,
             NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return signing ? .signingNetworkUnavailable : .networkUnavailable
        default:
            return nil
        }
    }

    /// Returns network evidence only for URL transport errors SideStore knows
    /// how to explain. URL-loading domains also carry local file I/O failures,
    /// so domain membership alone is not a network classification.
    public static func knownURLTransportCause(domain: String, code: Int,
                                               signing: Bool = false) -> SafeCause? {
        guard domain == NSURLErrorDomain || domain == "kCFErrorDomainCFNetwork" else { return nil }
        return networkSafeCauseForURLCode(code, signing: signing)
    }

    /// URL cancellation is terminal lifecycle evidence, not network failure.
    public static func isURLCancellation(domain: String, code: Int) -> Bool {
        (domain == NSURLErrorDomain || domain == "kCFErrorDomainCFNetwork") &&
            code == NSURLErrorCancelled
    }

    /// Correlation IDs are UUIDs. Compare their parsed identity so equivalent
    /// uppercase and lowercase UUID spellings stay bound to the same request.
    public static func uuidCorrelationMatches(_ receivedID: String?, expectedID: String) -> Bool {
        guard let receivedID,
              let received = UUID(uuidString: receivedID),
              let expected = UUID(uuidString: expectedID) else { return false }
        return received == expected
    }

    public static func capture(_ error: Error, operation: String, stage: Stage, id: String,
                               retryable: Bool? = nil) -> CombinedFailure {
        if let known = error as? CombinedFailure { return known }
        if let wrapped = error as? V3ProvisioningCauseError {
            let known = capture(wrapped.underlying, operation: operation, stage: stage, id: id, retryable: retryable)
            var context = known.signingContext
            context[V3ProvisioningCauseDiagnostic.contextKey] = wrapped.provisioningCause
            return CombinedFailure(operation: known.operation, stage: known.stage, code: known.code,
                id: id, underlying: NSError(domain: known.underlyingDomain, code: known.underlyingCode),
                retryable: known.retryable, safeCause: known.safeCause, sourceStep: known.sourceStep,
                signingContext: context, launchContext: known.launchContext)
        }
        if let attempt = error as? V3AnisetteAttemptError {
            let known = capture(attempt.underlying, operation: operation, stage: stage,
                                id: id, retryable: retryable)
            var context = known.signingContext
            context.merge(attempt.context.diagnosticFields) { _, observed in observed }
            return CombinedFailure(operation: known.operation, stage: known.stage, code: known.code,
                id: id, underlying: NSError(domain: known.underlyingDomain, code: known.underlyingCode),
                retryable: known.retryable, safeCause: known.safeCause, sourceStep: known.sourceStep,
                signingContext: context, launchContext: known.launchContext)
        }
        if error is LCAnisettePairError {
            return V3AccountOperationError(step: .anisetteFetch, kind: .anisetteIdentityStateInvalid,
                underlying: error, serverCode: nil).failure(operation: operation, id: id)
        }
        // Generic non-auth consumers still see the original native evidence;
        // headless auth captures finite typed/phase detail before arriving here.
        if let phase = error as? V3AuthenticationPhaseError {
            return capture(phase.underlying, operation: operation, stage: stage,
                           id: id, retryable: retryable)
        }
        // Typed account boundaries bypass all provider-description parsing.
        if let accountError = error as? V3AccountOperationError {
            return accountError.failure(operation: operation, id: id)
        }
        if let refreshError = error as? CombinedRefreshVerificationError {
            let code: Code = refreshError == .missingResult ? .missingResult : .staleResult
            return CombinedFailure(operation: operation, stage: .refreshVerification, code: code, id: id, retryable: retryable)
        }
        if let fileFailure = error as? CombinedIPAFileError {
            return CombinedFailure(operation: operation, stage: .filePreparation,
                                  code: fileFailure.combinedCode, id: id, underlying: fileFailure, retryable: retryable)
        }
        var cause = error as NSError
        var resolved = stage
        var resolvedCode: Code = error is CancellationError ? .cancelled : .failed
        var resolvedRetryable: Bool? = error is CancellationError ? false : retryable
        var nativeCode: Int?
        var nativeDomain: String?
        var safeCause: SafeCause?
        var sourceStep: SourceStep?
        var signingContext: [String: String] = [:]
        var ppqLocked = false
        var explicitStageMarker = false
        // Only an allowlisted stage is inspected locally. No arbitrary userInfo is serialized.
        for _ in 0..<5 {
            if resolvedCode != .cancelled,
               let remoteKind = V3AccountOperationError.remoteIdentityKind(domain: cause.domain, code: cause.code) {
                let failure = V3AccountOperationError(step: .anisetteFetch, kind: remoteKind,
                    underlying: NSError(domain: cause.domain, code: cause.code), serverCode: nil)
                    .failure(operation: operation, id: id)
                // Preserve compatible observed HTTP/server facts. Unknown placeholders must not erase them.
                signingContext.merge(failure.signingContext) { observed, _ in observed }
                signingContext["typed_error"] = remoteKind.rawValue
                let context: [String: String]
                if let valid = Self.validatedSigningContext(signingContext) { context = valid }
                else {
                    // An incompatible outer tuple must never discard the decisive local failure.
                    var primary = failure.signingContext
                    primary[V3AuthenticationDiagnostics.stateKey] = "trimmed"
                    context = primary
                }
                return CombinedFailure(operation: failure.operation, stage: failure.stage, code: failure.code,
                    id: id, underlying: NSError(domain: failure.underlyingDomain, code: failure.underlyingCode),
                    retryable: failure.retryable, safeCause: failure.safeCause, sourceStep: failure.sourceStep,
                    signingContext: context, launchContext: failure.launchContext)
            }
            let fingerprint = cause.localizedDescription.lowercased()
            let tokens = cause.localizedDescription.split(whereSeparator: { $0.isWhitespace })
            if let name = cause.userInfo["LCStructuredFailureStageV1"] as? String,
               let found = Stage(rawValue: name) {
                resolved = found
                explicitStageMarker = true
            } else if signingContext["typed_error"]?.hasPrefix("sideSign") != true,
                      let token = tokens.first(where: { $0.hasPrefix("lc_stage=") }),
                      let found = Stage(rawValue: String(token.dropFirst(9))) {
                resolved = found
                explicitStageMarker = true
            }
            if let name = cause.userInfo["LCStructuredFailureCauseV1"] as? String,
               let found = SafeCause(rawValue: name) {
                safeCause = found
            }
            if isURLCancellation(domain: cause.domain, code: cause.code) {
                resolvedCode = .cancelled
                resolvedRetryable = false
            }
            if let name = cause.userInfo["LCStructuredFailureSourceV1"] as? String,
               let found = SourceStep(rawValue: name) {
                sourceStep = found
            }
            if let fields = cause.userInfo["LCStructuredSigningContextV1"],
               let safeFields = Self.validatedWireSigningContext(fields) {
                signingContext.merge(safeFields) { _, deeper in deeper }
            }
            // Domain-specific classification. Only map a numeric code to a
            // stage when the (domain, code) pair has an established meaning.
            // Otherwise preserve the caller stage and keep the underlying
            // domain/code for diagnostics. Unknown stays unknown.
            // Explicit stage markers from SideStore's pipeline take precedence
            // over a broader gateway domain.
            if !ppqLocked && !explicitStageMarker {
                switch cause.domain {
                case "com.SideStore.Authentication":
                    resolved = .authentication
                case NSURLErrorDomain, "kCFErrorDomainCFNetwork":
                    // Only transport-specific URL errors establish network
                    // failure. URLSession also uses this domain for local
                    // download-file and cancellation errors.
                    if let urlCause = knownURLTransportCause(
                        domain: cause.domain, code: cause.code, signing: resolved == .signing) {
                        if resolved != .signing { resolved = .network }
                        if safeCause == nil { safeCause = urlCause }
                    }
                case "MinimuxerError", "DeviceGatewayError", "IdeviceGatewayError":
                    resolved = .command
                default:
                    break
                }
            }
            // Apple-side installation rejection (InstallationProxy/installd
            // application verification). The hex installer codes are matched
            // case-insensitively alongside the verification marker; the stage
            // is installation and the numeric code is preserved with the
            // cause's own allowlisted domain (never a fabricated one).
            // 0xE8008024: provisioning profile banned. 0xE8008018: signing
            // identity no longer valid. Neither implies pairing, network,
            // CoreDevice, or account-ban conditions.
            let installContext = ["install", "installURL", "installSharedIPA", "update"].contains(operation)
                && (stage == .installation || stage == .command)
            let explicitContextAllowsVerification = !explicitStageMarker || resolved == .command || resolved == .installation
            let typedVerificationSource = verificationDomains.contains(cause.domain)
            let profileRejectionEvidence = fingerprint.contains("e8008024")
                && fingerprint.contains("applicationverificationfailed")
                && fingerprint.contains("provisioning profile")
                && (fingerprint.contains("banned") || fingerprint.contains("revoked")
                    || fingerprint.contains("invalid") || fingerprint.contains("failed to verify"))
            let signingIdentityEvidence = fingerprint.contains("e8008018")
                && fingerprint.contains("applicationverificationfailed")
                && fingerprint.contains("identity used to sign")
                && (fingerprint.contains("no longer valid") || fingerprint.contains("invalid")
                    || fingerprint.contains("expired") || fingerprint.contains("revoked"))
            if installContext && explicitContextAllowsVerification && typedVerificationSource {
                if profileRejectionEvidence {
                    resolved = .installation
                    nativeCode = 0xE8008024
                    if nativeDomain == nil, domains.contains(cause.domain) { nativeDomain = cause.domain }
                    ppqLocked = true
                } else if signingIdentityEvidence {
                    resolved = .installation
                    nativeCode = 0xE8008018
                    if nativeDomain == nil, domains.contains(cause.domain) { nativeDomain = cause.domain }
                    ppqLocked = true
                }
            }
            // Upstream gateway/Minimuxer typed errors carry a reason string. Inspect only
            // our fixed machine tokens locally; never forward the reason itself.
            // A preserved numeric code keeps the domain it was actually observed
            // in: gateway tokens stay in their gateway domain, HTTP statuses use
            // the fixed HTTPStatus domain, and POSIX errnos stay in
            // NSPOSIXErrorDomain. No unrelated code is ever relabelled as a
            // gateway error.
            for (index, token) in tokens.enumerated() {
                guard !ppqLocked else { continue }
                // A provider body is not evidence of an HTTP status or errno.
                // Typed SideSign code evidence was captured before NSError bridging.
                if signingContext["typed_error"]?.hasPrefix("sideSign") == true { continue }
                if token.hasPrefix("lc_native_code="), let code = Int(token.dropFirst(15)) {
                    nativeCode = code
                    if ["MinimuxerError", "DeviceGatewayError", "IdeviceGatewayError"].contains(cause.domain) {
                        nativeDomain = cause.domain
                    }
                }
                // HTTP status in "HTTP 503" form (tokens are whitespace-split).
                if (token == "HTTP" || token == "http"), index + 1 < tokens.count,
                   let code = Int(tokens[index + 1]) {
                    nativeCode = code
                    nativeDomain = "HTTPStatus"
                }
                // POSIX errno in "errno=20" / "errno:20" form.
                if token.hasPrefix("errno=") || token.hasPrefix("errno:") {
                    if let code = Int(token.dropFirst(6)) {
                        nativeCode = code
                        nativeDomain = "NSPOSIXErrorDomain"
                    }
                }
            }
            if let next = cause.userInfo[NSUnderlyingErrorKey] as? NSError { cause = next } else { break }
        }
        let underlying: NSError
        if let code = nativeCode {
            if let domain = nativeDomain {
                underlying = NSError(domain: domain, code: code)
            } else if domains.contains(cause.domain) {
                underlying = NSError(domain: cause.domain, code: code)
            } else {
                underlying = NSError(domain: "redacted", code: code)
            }
        } else {
            underlying = cause
        }
        if safeCause == nil && (resolved == .signing || resolved == .network) {
            safeCause = knownURLTransportCause(
                domain: cause.domain, code: cause.code, signing: resolved == .signing)
        }
        return CombinedFailure(operation: operation, stage: resolved,
            code: resolvedCode, id: id,
            underlying: underlying, retryable: resolvedRetryable, safeCause: safeCause,
            sourceStep: sourceStep, signingContext: signingContext)
    }
}

// LC_ANISETTE_PAIR_FAILURE_V1: finite preservation failures only. Never attach
// the identifier, provisioning blob, provider response, or Keychain bytes.
public enum LCAnisettePairError: Error, LocalizedError, Equatable {
    case orphanedBlob, invalidIdentifier, invalidBlob, migrationPairConflict, stateChanged

    public static let safeMessage = "Sign-in is blocked because the saved Anisette identity state could not be verified."
    public static let recovery = "Keep the existing Anisette and account data unchanged. Copy Diagnostics for review before another sign-in."
    public var errorDescription: String? { Self.safeMessage }
}

// V3_AUTHENTICATION_PHASE_EVIDENCE_V1: preserve the original error for retry,
// cancellation and typed matching; never store provider strings or payloads.
struct V3AuthenticationPhaseError: Error {
    let step: CombinedFailure.SourceStep
    let underlying: Error
}
func v3AuthenticationPhase<T>(_ step: CombinedFailure.SourceStep,
                              perform: () async throws -> T) async throws -> T {
    do { return try await perform() }
    catch {
        let native = error as NSError
        if error is CancellationError || CombinedFailure.isURLCancellation(domain: native.domain, code: native.code) { throw error }
        if error is V3AuthenticationPhaseError { throw error }
        throw V3AuthenticationPhaseError(step: step, underlying: error)
    }
}

// DEBUG TEMPORARY: remove this finite, per-attempt diagnostic with the investigation.
// One release-visible switch also controls the native patcher. No TaskLocal/global
// mutable state and no raw provider text, paths, identifiers, blobs or headers.
// DEBUG TEMPORARY: maintained-source consumer contract v1. Remove with the
// matching AnisetteKit observer; never interpret arbitrary provider text.
public struct V3TemporaryADIConsumption {
    public static let contextKey = "debug_temporary_adi_consumption"
    public static let maximumBytes = 2048
    public static let maximumEvents = 32
    public static let maximumWireBytes = 4096
    private static let marker = " [DEBUG_TEMPORARY_ADI_CONSUMPTION:"
    private let truncated: Bool
    private let comparison: Int?
    private let inputCovered: Bool
    private let rows: [[Int]]

    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes,
              encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let pieces = encoded.split(separator: "|", omittingEmptySubsequences: false)
        guard pieces.count >= 2, pieces[1] == "0" || pieces[1] == "1" else { return nil }
        let offset: Int
        if pieces[0] == "v1" {
            offset = 2
            comparison = nil
            inputCovered = false
        } else if pieces[0] == "v2" {
            guard pieces.count >= 4,
                  pieces[2] == "0" || pieces[2] == "1" || pieces[2] == "2",
                  pieces[3] == "0" || pieces[3] == "1",
                  pieces[3] != "1" || pieces[2] == "1" else { return nil }
            offset = 4
            comparison = pieces[2] == "0" ? 0 : (pieces[2] == "1" ? 1 : 2)
            inputCovered = pieces[3] == "1"
        } else { return nil }
        guard pieces.count <= Self.maximumEvents + offset else { return nil }
        var decoded: [[Int]] = []
        for row in pieces.dropFirst(offset) {
            let parts = row.split(separator: ",", omittingEmptySubsequences: false)
            guard parts.count == 8 else { return nil }
            let fields = parts.compactMap { Int($0) }
            guard fields.count == 8,
                  zip(parts, fields).allSatisfy({ String($0.1) == String($0.0) }),
                  (0...5).contains(fields[0]), (0...1).contains(fields[1]),
                  (0...4).contains(fields[2]), (-1...1).contains(fields[3]),
                  (0...4095).contains(fields[4]),
                  (0...1_048_577).contains(fields[5]), (0...1_048_577).contains(fields[6]),
                  (-1...32).contains(fields[7]) else { return nil }
            decoded.append(fields)
        }
        truncated = pieces[1] == "1"
        rows = decoded
    }
    private init(truncated: Bool, comparison: Int?, inputCovered: Bool, rows: [[Int]]) {
        self.truncated = truncated
        self.comparison = comparison
        self.inputCovered = inputCovered
        self.rows = rows
    }
    public var encoded: String {
        let prefix = comparison.map { "v2|\(truncated ? 1 : 0)|\($0)|\(inputCovered ? 1 : 0)" }
            ?? "v1|\(truncated ? 1 : 0)"
        return prefix + rows.map { "|" + $0.map(String.init).joined(separator: ",") }.joined()
    }
    public var technicalDetails: String {
        guard V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled else { return "" }
        return "\nDEBUG TEMPORARY adi_consumption=\(encoded)"
    }
    static func splitDescription(_ description: String) -> (base: String, trace: Self?) {
        // Only a single, terminal owned suffix is removable. Invalid optional
        // metadata is dropped; the exact original error producer remains.
        guard description.utf8.count <= 8192, description.hasSuffix("]"),
              let range = description.range(of: marker),
              description[range.upperBound...].range(of: marker) == nil else { return (description, nil) }
        let body = String(description[range.upperBound...].dropLast())
        return (String(description[..<range.lowerBound]), Self(encoded: body))
    }
    public static func sanitizingContext(_ supplied: [String: String]) -> [String: String] {
        var result = supplied
        let raw = result.removeValue(forKey: contextKey)
        if V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled,
           let raw, let parsed = Self(encoded: raw), result.count < 20 {
            result[contextKey] = parsed.encoded
        }
        return result
    }
    public static func boundingWire(_ supplied: [String: Any]) -> [String: Any] {
        guard var context = supplied["signingContext"] as? [String: String],
              let raw = context.removeValue(forKey: contextKey) else { return supplied }
        var result = supplied
        result["signingContext"] = context
        guard V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled,
              var trace = Self(encoded: raw), context.count < 20 else { return result }
        while true {
            context[contextKey] = trace.encoded
            result["signingContext"] = context
            if let data = try? PropertyListSerialization.data(fromPropertyList: result, format: .binary, options: 0),
               data.count <= maximumWireBytes { return result }
            if trace.rows.isEmpty {
                context.removeValue(forKey: contextKey)
                result["signingContext"] = context
                return result
            }
            // Trim only this optional observer, retain later observations and
            // explicitly mark loss. Never discard the main failure fields.
            trace = Self(truncated: true, comparison: trace.comparison, inputCovered: trace.inputCovered, rows: Array(trace.rows.dropFirst()))
        }
    }
}

// LOGIN_DIAGNOSTIC_WIRE_V1: finite counterpart to AnisetteKit.LoginDiagnosticTrace.
// Host support deliberately has no dependency on AnisetteKit or account state.
// V3_PROVISIONING_CAUSE_CONTRACT_V1: strictly finite, bounded diagnostics only.
// This declaration is mirrored by the wire owner in both maintained consumers.
public struct V3ProvisioningCauseDiagnostic {
    public static let contextKey = "provisioning_cause"
    public static let maximumBytes = 1024
    public static let maximumRows = 4
    public static let rejected = "pc1|unobserved|0|1|0|unobserved,unknown,unknown,-,-,-,-,unobserved,unavailable,unavailable,-,-,0"
    public enum Phase: String, CaseIterable {
        case liveUDID, fallbackUDID, missingVerifiedID, listDevices, registerDevice, unobserved
    }
    public struct Row {
        public let boundary: String
        public let type: String
        public let kind: String
        public let code: String
        public let result: String
        public let http: String
        public let provider: String
        public let shape: String
        public let mime: String
        public let size: String
        public let expected: String
        public let key: String
        public let depth: String
    }
    public let encoded: String
    public let phase: Phase
    public let truncated: Bool
    public let unknown: Bool
    public let cycle: Bool
    public let rows: [Row]

    public static let cases: [String: Set<String>] = [
        "operation": ["noInstalledApps", "noSources", "notAuthenticated", "timedOut", "unableToConnectSideJIT", "unableToRespondSideJITDevice", "unknownResult", "cacheClearError", "certificateExpired", "certificateRevoked", "certificateVerificationUnavailable", "customCertificateExpired", "customCertificateRevoked", "forbidden", "invalidApp", "invalidPairingFile", "invalidParameters", "invalidResponse", "invalidVPN", "minimuxerNotStarted", "missingAppBundle", "missingAppGroup", "missingInfoPlist", "missingProvisioningProfile", "missingUpdate", "noConnection", "noDevice", "noVPN", "notReachable", "openAppFailed", "pairingNotComplete", "pledgeInactive", "SideJITIssue", "unknownUDID", "unknown", "appNotFound", "invalidOperationContext", "maximumAppIDLimitReached", "sourceNotAdded", "serverNotFound", "connectionFailed", "provisioningError", "certificateChanged"],
        "minimuxer": ["noDevice", "noConnection", "notReachable", "noVPN", "invalidVPN", "invalidPairing", "notStarted", "pairingNotLoaded", "connectionModeNotConfigured", "createCoreDevice", "createLockdown", "getLockdownValue", "connect", "noService", "other"],
        "portal": ["unknown", "invalidParameters", "incorrectCredentials", "noTeams", "appSpecificPasswordRequired", "invalidDeviceID", "deviceAlreadyRegistered", "invalidCertificateRequest", "certificateDoesNotExist", "invalidAppIDName", "invalidBundleIdentifier", "bundleIdentifierUnavailable", "appIDDoesNotExist", "maximumAppIDLimitReached", "invalidAppGroup", "appGroupDoesNotExist", "invalidProvisioningProfileIdentifier", "provisioningProfileDoesNotExist", "requiresTwoFactorAuthentication", "userCancelled", "incorrectVerificationCode", "authenticationHandshakeFailed", "invalidAnisetteData", "tooManyCertificates", "tooManyAttempts", "accountRepairRequired", "invalid2FAResponse"],
        "server": ["badServerResponse", "invalidResponseFormat", "missingKey", "underlyingError"],
        "decoding": ["typeMismatch", "valueNotFound", "keyNotFound", "dataCorrupted", "other"],
        "url": ["transport"], "native": ["cocoa", "posix", "osStatus"],
        "wrapper": ["minimuxerService", "altWrapped"],
        "cancellation": ["cancelled"], "state": ["unverifiedIdentifier"], "unknown": ["unknown"]
    ]
    public static let providerCodes: Set<String> = ["-", "ENTITY_ERROR", "ENTITY_ERROR.INVALID", "ENTITY_ERROR.ATTRIBUTE.INVALID", "ENTITY_ERROR.ATTRIBUTE.REQUIRED", "ENTITY_ERROR.ATTRIBUTE.UNKNOWN", "ENTITY_ERROR.RELATIONSHIP.INVALID", "ENTITY_ERROR.RELATIONSHIP.INVALID_NOT_ALLOWED", "ENTITY_ERROR.ATTRIBUTE.INVALID.DUPLICATE", "FORBIDDEN_ERROR", "NOT_FOUND", "PARAMETER_ERROR.INVALID", "PARAMETER_ERROR.REQUIRED", "RATE_LIMIT_EXCEEDED", "SERVICE_UNAVAILABLE", "UNEXPECTED_ERROR", "UNKNOWN_ERROR"]
    public static let shapes: Set<String> = ["unobserved", "plistDictionary", "plistArray", "plistScalar", "jsonDictionary", "jsonArray", "jsonScalar", "unrecognized"]
    public static let mimes: Set<String> = ["unavailable", "html", "xmlOrPlist", "json", "other"]
    public static let sizes: Set<String> = ["unavailable", "empty", "1to256", "257to4096", "over4096"]
    public static let expectedTypes: Set<String> = ["-", "string", "integer", "boolean", "number", "data", "date", "other"]
    public static let codingKeys: Set<String> = ["-", "device", "devices", "resultCode", "resultString", "name", "deviceNumber", "deviceId", "status", "udid", "other"]

    public static func validated(_ value: String) -> String? {
        V3ProvisioningCauseDiagnostic(encoded: value)?.encoded
    }
    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes,
              encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let parts = encoded.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 6, parts[0] == "pc1", let phase = Phase(rawValue: parts[1]),
              [parts[2], parts[3], parts[4]].allSatisfy({ $0 == "0" || $0 == "1" }) else { return nil }
        let sourceRows = parts[5].split(separator: ";", omittingEmptySubsequences: false)
        guard (1...Self.maximumRows).contains(sourceRows.count) else { return nil }
        var rows: [Row] = []
        var nextDepth: [String: Int] = [:]
        for source in sourceRows {
            let f = source.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
            guard f.count == 13, Phase(rawValue: f[0]) != nil,
                  Self.cases[f[1]]?.contains(f[2]) == true,
                  Self.number(f[3], minimum: -2147483648, maximum: 2147483647),
                  Self.number(f[4], minimum: -2147483648, maximum: 2147483647),
                  Self.number(f[5], minimum: 100, maximum: 599),
                  Self.providerCodes.contains(f[6]), Self.shapes.contains(f[7]),
                  Self.mimes.contains(f[8]), Self.sizes.contains(f[9]),
                  Self.expectedTypes.contains(f[10]), Self.codingKeys.contains(f[11]),
                  ["0", "1", "2", "3"].contains(f[12]) else { return nil }
            // Numeric values from unknown domains or enum bridge ordinals are not evidence.
            guard f[3] == "-" || ["url", "native"].contains(f[1]) || (f[1] == "server" && f[2] == "underlyingError") else { return nil }
            let observedPortal = ["listDevices", "registerDevice"].contains(f[0]) && f[12] == "0"
            guard (f[4] == "-" && f[6] == "-") || observedPortal else { return nil }
            guard f[5] == "-" || observedPortal || (f[1] == "server" && f[2] == "invalidResponseFormat") else { return nil }
            let parser = f[1] == "server" && ["badServerResponse", "invalidResponseFormat", "missingKey"].contains(f[2])
            guard (f[7] == "unobserved" && f[9] == "unavailable") || parser else { return nil }
            guard f[8] == "unavailable" || (f[1] == "server" && f[2] == "invalidResponseFormat") else { return nil }
            guard f[10] == "-" || f[1] == "decoding" else { return nil }
            guard f[11] == "-" || f[1] == "decoding" || (f[1] == "server" && f[2] == "missingKey") else { return nil }
            guard f[1] != "state" || ["liveUDID", "fallbackUDID", "missingVerifiedID"].contains(f[0]) else { return nil }
            guard Int(f[12]) == nextDepth[f[0], default: 0] else { return nil }
            nextDepth[f[0]] = Int(f[12])! + 1
            if f[1] == "unknown" || f[2] == "unknown" || f[2] == "other" {
                guard parts[3] == "1" else { return nil }
            }
            rows.append(Row(boundary: f[0], type: f[1], kind: f[2], code: f[3],
                result: f[4], http: f[5], provider: f[6], shape: f[7], mime: f[8],
                size: f[9], expected: f[10], key: f[11], depth: f[12]))
        }
        guard nextDepth[phase.rawValue] != nil else { return nil }
        self.encoded = encoded
        self.phase = phase
        self.truncated = parts[2] == "1"
        self.unknown = parts[3] == "1"
        self.cycle = parts[4] == "1"
        self.rows = rows
    }
    private static func number(_ value: String, minimum: Int64, maximum: Int64) -> Bool {
        if value == "-" { return true }
        guard let n = Int64(value), String(n) == value else { return false }
        return (minimum...maximum).contains(n)
    }
}

// Original error remains process-local, not NSError.userInfo or serialized payload.
struct V3ProvisioningCauseError: Error, LocalizedError {
    let underlying: Error
    let provisioningCause: String
    var errorDescription: String? { "Device registration failed; review the safe diagnostics." }
}


extension V3ProvisioningCauseDiagnostic {
    public var technicalDetails: String {
        let header = "\nprovisioning_cause_schema=pc1 provisioning_substep=\(phase.rawValue) cause_truncated=\(truncated) cause_unknown=\(unknown) cause_cycle=\(cycle)"
        let causes = rows.enumerated().map { index, row in
            "\nprovisioning_cause[\(index)]: boundary=\(row.boundary) type=\(row.type) case=\(row.kind) native_code=\(row.code) portal_result=\(row.result) http_status=\(row.http) provider_code=\(row.provider) parse_shape=\(row.shape) mime=\(row.mime) body_size=\(row.size) expected_type=\(row.expected) coding_key=\(row.key) depth=\(row.depth)"
        }.joined()
        return header + causes
    }
}

public struct V3AuthenticationRequestSnapshot {
    public static let contextKey = "auth_request_trace"
    public static let maximumBytes = 1024
    public let encoded: String
    public init?(encoded: String) {
        guard Self.validatedEncodedSnapshot(encoded) != nil else { return nil }
        self.encoded = encoded
    }
    public static func validatedEncodedSnapshot(_ value: String) -> String? {
        guard value.utf8.count <= 1024, value.utf8.allSatisfy({ $0 >= 32 && $0 <= 126 }) else { return nil }
        let p = value.split(separator: ";", omittingEmptySubsequences: false).map(String.init)
        func number(_ s: String, _ range: ClosedRange<Int>) -> Bool { guard let n = Int(s), String(n) == s else { return false }; return range.contains(n) }
        func one(_ s: String, _ values: String) -> Bool { values.split(separator: " ").contains(Substring(s)) }
        func bit(_ s: String) -> Bool { s == "0" || s == "1" }
        func status(_ s: String) -> Bool { s == "-" || s == "invalid" || number(s, 100...599) }
        func code(_ s: String, hsc: Bool = false) -> Bool { one(s, "u m ib is if io ir") || number(s, hsc ? 100...599 : -99_999_999...99_999_999) }
        let phases = "init complete apptokens trustedRequest phoneRequest trustedVerify phoneVerify unknown"
        let outcomes = "started received accepted rejected transport empty parse status"
        let consumers = "none initFields completeSPD proofField proof sharedSecret spdDecrypt spdParse dsid idms sessionKey sessionChallenge checksum tokenField tokenLength tokenDecrypt tokenParse tokenPath xmlAlert http peToken verify"
        let validations = "unobserved passed failed retry"
        let endpoints = "gsa trusted validate phoneRequest phoneVerify apple other unavailable"
        guard p.count == 9, p[0] == "ar1", number(p[1], 0...65_535), number(p[2], 0...65_535), bit(p[3]), bit(p[4]),
              one(p[5], "notRequested srpInit serialization response hash pbkdf2 challenge proof sharedSecret spdDecrypt spdParse sessionKey sessionChallenge checksum twoFactor accountRepair accountLookup complete"),
              one(p[6], validations) else { return nil }
        let auth = Int(p[1])!, requests = Int(p[2])!
        guard auth > 0 || requests > 0 || (p[5] == "serialization" && p[6] == "failed") else { return nil }
        if p[3] == "1" { guard auth == 65_535 || requests == 65_535 else { return nil } }
        var last = requests + 1
        if p[7] != "-" {
            let f = p[7].split(separator: ",", omittingEmptySubsequences: false).map(String.init)
            guard f.count == 40, number(f[0], 0...auth), number(f[1], 1...max(1, requests)), requests > 0,
                  one(f[2], phases), one(f[3], "GET POST PUT DELETE HEAD PATCH OPTIONS other absent"), one(f[4], endpoints),
                  number(f[5], 0...86_400_000), number(f[6], 0...86_400_000), bit(f[7]), one(f[8], outcomes),
                  one(f[9], "none cancelled timeout dns connectivity lost tls url unknown"), status(f[10]), one(f[11], endpoints),
                  one(f[12], "sameURL sameOrigin differentOrigin unavailable"), f[13] == "u", number(f[14], 0...16_777_216),
                  (f[15] == "-" || number(f[15], 0...16_777_216)), number(f[16], 0...3),
                  one(f[17], "unobserved plist json html xml text other missing"), one(f[18], "unobserved empty plistXML plistBinary jsonObject jsonArray html xml text binary"),
                  one(f[19], "unobserved plist json failure"), one(f[20], "unobserved dictionary array scalar invalid"), one(f[21], "unobserved dictionary array scalar invalid"),
                  one(f[22], "unobserved nested topMissing topWrong topOnly"), one(f[23], "unobserved dictionary missing wrong"), code(f[24]), code(f[25], hsc: true),
                  one(f[26], "unobserved default cast"), (one(f[27], "- out") || number(f[27], -99_999_999...99_999_999)), one(f[28], "unobserved status top"),
                  (one(f[29], "u a w") || (f[29].utf8.count == 15 && f[29].allSatisfy { "absedznrco".contains($0) })),
                  one(f[30], "unobserved absent delta date invalid"), (f[31] == "-" || number(f[31], 0...86_400)), bit(f[32]),
                  one(f[33], consumers), one(f[34], validations), one(f[35], "none credentials appPassword verification underlying rateLimit xmlAlert http peToken incorrectCode serviceUnavailable unknown"),
                  bit(f[36]), (f[37] == "u" || number(f[37], 0...32)), one(f[39], "plist none unobserved") else { return nil }
            if !one(f[38], "twoFactor none unobserved") {
                let e = f[38].split(separator: ":", omittingEmptySubsequences: false).map(String.init)
                guard e.count == 3, e[0] == "headerRequest", one(e[1], "builtIn custom unknown"), one(e[2], "builtIn custom unknown") else { return nil }
            }
            if one(f[30], "delta date") { guard f[31] != "-", f[10] != "-" else { return nil } }
            else { guard f[31] == "-", f[32] == "0" else { return nil } }
            if f[36] == "0" {
                guard one(f[8], "started transport"), f[10] == "-", f[15] == "-", f[17] == "unobserved", f[18] == "unobserved",
                      f[11] == "unavailable", f[12] == "unavailable", f[19] == "unobserved", f[20] == "unobserved", f[21] == "unobserved",
                      f[30] == "unobserved", f[31] == "-", f[32] == "0" else { return nil }
            } else {
                guard !one(f[8], "started transport"), f[15] != "-", f[17] != "unobserved", f[18] != "unobserved", f[30] != "unobserved" else { return nil }
            }
            last = Int(f[1])!
        }
        let rows = p[8].isEmpty ? [] : p[8].split(separator: "~", omittingEmptySubsequences: false).map(String.init)
        guard rows.count <= 3 else { return nil }
        var previous = 0
        for row in rows {
            let r = row.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
            guard r.count == 8, number(r[0], 0...auth), number(r[1], 1...max(1, requests)), one(r[2], phases), one(r[3], outcomes), status(r[4]), code(r[5]), one(r[6], consumers), one(r[7], validations),
                  let ordinal = Int(r[1]), ordinal > previous, ordinal < last, ordinal <= requests else { return nil }
            previous = ordinal
        }
        return value
    }
    public var technicalDetails: String {
        let p = encoded.components(separatedBy: ";")
        var text = "\nauth_request_schema=ar1 auth_invocations=\(p[1]) observed_request_count=\(p[2]) ordinal_overflow=\(p[3]) request_history_truncated=\(p[4]) auth_boundary=\(p[5]) auth_validation=\(p[6])"
        if p[7] == "-" { text += "\nlast_observed_request=notRecorded" }
        else {
            let r = p[7].components(separatedBy: ",")
            let names = ["invocation", "request_ordinal", "phase", "method", "endpoint", "session_elapsed_ms", "request_elapsed_ms",
                "timing_capped", "state", "transport", "http_status", "final_endpoint", "final_relation", "redirect_history",
                "request_bytes_capped", "response_bytes_capped", "body_size_cap_bits", "mime", "body_shape", "parser", "plist_root", "json_root",
                "envelope", "status_shape", "ec_observed", "hsc_observed", "effective_ec_source", "effective_ec", "error_envelope", "cpd_schema",
                "retry_after_kind", "retry_after_seconds_capped", "retry_after_capped", "consumer_boundary", "consumer_validation", "mapping_reason",
                "response_observed", "unexpected_cpd_keys_capped_32", "request_envelope", "serialization"]
            func display(_ value: String) -> String {
                switch value { case "u": return "unobserved"; case "-": return "unavailable"; case "m": return "missing"
                case "ib": return "invalidBoolean"; case "is": return "invalidString"; case "if": return "invalidFloat"
                case "io": return "invalidType"; case "ir": return "invalidRange"; default: return value }
            }
            text += "\nlast_observed_request: " + zip(names, r).map { "\($0.0)=\(display($0.1))" }.joined(separator: " ")
            let cpdKeys = ["bootstrap", "icscrec", "pbe", "prkgen", "svct", "loc", "X-Apple-Locale", "X-Apple-I-MD", "X-Apple-I-MD-M", "X-Mme-Device-Id", "X-Apple-I-MD-LU", "X-Apple-I-MD-RINFO", "X-Apple-I-SRL-NO", "X-Apple-I-Client-Time", "X-Apple-I…83877 tokens truncated…ng)
}

struct V3SourceFormState: Equatable {
    var isPresented: Bool
    var url: String
    var originalURL: String
    var isFocused: Bool
    var hasPreview: Bool
}

enum V3SourceFormEffect: Equatable {
    case preview
    case validate
    case persist
}

struct V3SourceFormTransition: Equatable {
    var state: V3SourceFormState
    var effects: [V3SourceFormEffect]
}

struct V3SourcePreviewRequest: Equatable {
    let generation: UInt64
    let targetURL: String
}

struct V3SourcePreviewSession {
    private(set) var generation: UInt64 = 0
    private(set) var activeRequest: V3SourcePreviewRequest?

    mutating func begin(targetURL: String) -> V3SourcePreviewRequest? {
        guard !targetURL.isEmpty else { return nil }
        generation &+= 1
        let request = V3SourcePreviewRequest(generation: generation, targetURL: targetURL)
        activeRequest = request
        return request
    }

    mutating func invalidate() {
        generation &+= 1
        activeRequest = nil
    }

    func mayApply(_ request: V3SourcePreviewRequest, currentURL: String,
                  formPresented: Bool) -> Bool {
        formPresented && activeRequest == request && generation == request.generation &&
            currentURL == request.targetURL
    }

    static func responseRow(_ payload: [String: Any], for request: V3SourcePreviewRequest) -> [String: Any] {
        var row = payload
        row["url"] = request.targetURL
        return row
    }
}

struct V3SourceFormOpenRequestLedger {
    private(set) var lastClaimedRequestID: UUID?

    mutating func claim(_ requestID: UUID?) -> Bool {
        guard let requestID, requestID != lastClaimedRequestID else { return false }
        lastClaimedRequestID = requestID
        return true
    }
}

enum V3SourceEditingPolicy {
    static func canCancelForm(isAdding: Bool) -> Bool { !isAdding }

    /// Done: a pure UI dismissal. The typed value is kept.
    static func done(typed: String) -> V3SourceEditingOutcome { .dismissed }

    /// Cancel: restore the pre-edit value, so a URL is never silently discarded
    /// and a later focus always starts from a predictable value.
    static func cancel(typed: String, beforeEditing: String) -> V3SourceEditingOutcome {
        .restored(beforeEditing)
    }

    /// The value the field should hold after the outcome is applied.
    static func resolved(_ outcome: V3SourceEditingOutcome, typed: String) -> String {
        switch outcome {
        case .dismissed: return typed
        case .restored(let value): return value
        }
    }

    /// Closing Add Source is a UI-only transition. It restores the value that
    /// was present when the form opened and cannot request preview, validation,
    /// or persistence work.
    static func closeForm(_ current: V3SourceFormState) -> V3SourceFormTransition {
        V3SourceFormTransition(
            state: V3SourceFormState(
                isPresented: false,
                url: current.originalURL,
                originalURL: current.originalURL,
                isFocused: false,
                hasPreview: false),
            effects: [])
    }
}

// V3_SETUP_COMPLETION_POLICY_V1
// One authority for "is setup finished". Home and the Setup Assistant each used
// their own rule, so Home could stop showing "Finish Setup" while the assistant
// still considered setup incomplete. Two authorities for one product state is
// the defect; this type removes the possibility of disagreement by having exactly
// one decision, consumed by both, and by reporting which item is outstanding
// rather than a bare boolean.
// V3_INSTALLED_HOST_SIGNING_V1: local compatibility is a current observation,
// separate from successful refresh history and the imported JIT-Less copy.
// It does not establish portal revocation status or exact signing provenance.
enum V3HostSigningState: String, Equatable, Sendable {
    case unknown, compatible, refreshRequired, paidSignerUnverified

    var detail: String {
        switch self {
        case .unknown:
            return "Installed host signing could not be checked. Reload Status to check again." + "\nError ID: SS-VERIFY-D062"
        case .compatible:
            return "The installed host is locally compatible with the active signing setup. Revocation was not checked."
        case .refreshRequired:
            return "The installed host signing is expired or differs from the active setup. Run Test Refresh after completing account and certificate setup." + "\nError ID: SS-VERIFY-D063"
        case .paidSignerUnverified:
            return "The installed host uses a different paid-team signer. Its portal status was not checked; a re-sign is not known to be required. You can inspect Certificates or explicitly run Test Refresh."
        }
    }
}

struct V3HostSigningObservation: Equatable, Sendable {
    // Match the existing shared setup-fact observation interval.
    static let maximumAge: TimeInterval = 5 * 60
    var context = ""
    var state: V3HostSigningState = .unknown
    var checkedAt = Date.distantPast
    var validUntil = Date.distantPast

    func currentState(context: String?, now: Date = Date()) -> V3HostSigningState {
        guard let context, !context.isEmpty, self.context == context,
              now >= checkedAt, now < validUntil,
              now.timeIntervalSince(checkedAt) < Self.maximumAge else { return .unknown }
        return state
    }

    var wire: [String: Any] {
        ["context": context, "state": state.rawValue, "checkedAt": checkedAt, "validUntil": validUntil]
    }

    static func decode(_ value: Any?) -> V3HostSigningObservation? {
        guard let value = value as? [String: Any],
              let context = value["context"] as? String,
              context.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let rawState = value["state"] as? String, let state = V3HostSigningState(rawValue: rawState),
              let checkedAt = value["checkedAt"] as? Date,
              let validUntil = value["validUntil"] as? Date,
              checkedAt.timeIntervalSince1970.isFinite, validUntil.timeIntervalSince1970.isFinite,
              validUntil <= checkedAt.addingTimeInterval(maximumAge) else { return nil }
        return V3HostSigningObservation(context: context, state: state,
            checkedAt: checkedAt, validUntil: validUntil)
    }
}

enum V3SetupOutstandingItem: String, Equatable, CaseIterable {
    case account
    case provisioning
    case pairing
    case jitless
    case network
    case tunnel
    case backgroundRefresh
    case schedule
    case verifiedRefresh
    case installedHostSigning

    /// User-facing label, so the UI can name the outstanding step.
    var title: String {
        switch self {
        case .account: return "Sign in with your Apple ID"
        case .provisioning: return "Finish device provisioning"
        case .pairing: return "Add a pairing file"
        case .jitless: return "Configure the JIT-Less certificate"
        case .network: return "Connect to Wi-Fi"
        case .tunnel: return "Enable LocalDevVPN"
        case .backgroundRefresh: return "Allow Background App Refresh"
        case .schedule: return "Enable scheduled refresh"
        case .verifiedRefresh: return "Run one verified refresh"
        case .installedHostSigning: return "Check installed host signing"
        }
    }
}

struct V3SetupCompletionInputs: Equatable {
    var accountComplete = false
    var provisioningIncomplete = false
    var pairingSatisfied = false
    var jitlessRequired = false
    var jitlessComplete = false
    var networkComplete = false
    var tunnelComplete = false
    var backgroundRefreshAvailable = false
    var scheduleEnabled = false
    var verifiedRefreshPresent = false
    var installedHostSigningCompatible = false

    /// The only legal way to decide whether setup is finished.
    func outstanding() -> [V3SetupOutstandingItem] {
        var items: [V3SetupOutstandingItem] = []
        if !accountComplete { items.append(.account) }
        if provisioningIncomplete { items.append(.provisioning) }
        if !pairingSatisfied { items.append(.pairing) }
        // JIT-Less is only a prerequisite where the platform requires it.
        if jitlessRequired && !jitlessComplete { items.append(.jitless) }
        if !networkComplete { items.append(.network) }
        if !tunnelComplete { items.append(.tunnel) }
        if !backgroundRefreshAvailable { items.append(.backgroundRefresh) }
        if !scheduleEnabled { items.append(.schedule) }
        if !verifiedRefreshPresent { items.append(.verifiedRefresh) }
        if !installedHostSigningCompatible { items.append(.installedHostSigning) }
        return items
    }

    var isComplete: Bool { outstanding().isEmpty }
}

// V3_FAILURE_GUIDANCE_V1
// A failure that reached a view as an untyped error was displayed as
// error.localizedDescription. That publishes whatever text the service happened
// to attach, which for a bridged NSError includes its numeric domain and code
// and means nothing to a user, and it offered no guidance at all. Every
// user-visible failure message now comes from here.
//
// A typed CombinedFailure keeps its own product recovery copy. An untyped error
// cannot be attributed to a cause, so the guidance deliberately does not guess
// one: it says what is known, and it points at the diagnostics that can identify
// it. The unreadable text is kept out of the interface and offered through
// Copy Diagnostics instead.
enum V3FailureGuidance {
    static func message(_ error: Error) -> String {
        if let combined = error as? CombinedFailure {
            return combined.recovery + "\n" + combined.diagnosticLabel
        }
        // The earlier wording asserted "and nothing was changed". Nothing
        // supports that: an untyped failure can arrive after the service applied
        // the request, and the same helper is used after settings writes, source
        // confirmation, pairing import and install staging. Claiming a known
        // side-effect from an unknown cause is the same class of error as
        // blaming the network, so the claim is removed and the outcome is stated
        // as unknown.
        return "That action did not complete, and whether it took effect is not known. Reload status to see the current state before trying again. If it keeps failing, copy diagnostics to identify the cause.\nError ID: SS-CMD-C11"
    }

    /// Privacy-safe diagnostic text, never shown as guidance.
    static func diagnostics(_ error: Error) -> String {
        if let combined = error as? CombinedFailure {
            return combined.technicalDetails
        }
        let nsError = error as NSError
        let underlying = CombinedFailure.safeDiagnosticUnderlying(domain: nsError.domain,
            code: nsError.code)
        return "diagnostic_code=SS-CMD-C11 builder_commit=\(V3DiagnosticBuild.commit) operation=untyped stage=command code=failed underlying_domain=\(underlying.domain) underlying_code=\(underlying.code)"
    }
}

// V3_RESPONSE_CLASSIFICATION_CARRIER_V1
// The service's reply encoder and the host's reply classifier are separated by
// a property-list boundary, and the classification of a reply the service could
// not deliver has to survive that boundary. It previously did not: the service
// wrote the specific token under a legacy "error" key and a cause-less
// structured "failure", and the host prefers the structured envelope, so every
// encoding failure arrived as a generic invalidResponse.
//
// Both halves live here, as pure functions, so the pair can be executed together
// against real property-list bytes rather than asserted about in source text.
// The host still prefers the structured envelope; the classification simply
// travels inside it now, and the legacy token remains for an older host.
enum V3ResponseClassifier {
    /// The legacy string tokens a service may put in the "error" key.
    enum Token {
        static let encodingFailed = "responseEncodingFailed"
        static let tooLarge = "responseTooLarge"
    }

    /// The safe cause that carries a token's classification across the wire.
    static func safeCause(for token: String) -> CombinedFailure.SafeCause? {
        switch token {
        case Token.encodingFailed: return .responseEncodingFailed
        case Token.tooLarge: return .responseTooLarge
        default: return nil
        }
    }
}

// V3_RESPONSE_ENCODER_V1
// The service side of the classification pair. It is a separate enum rather than
// a private method so the harness can execute the real encoder, and it reads the
// shared responseLimit instead of repeating the literal.
struct V3EncodedServiceResponse {
    let data: Data
    let fallbackToken: String?
}

enum V3ResponseEncoder {
    /// Encodes a reply, or returns a correlated, typed fallback that says which
    /// of the two failure modes occurred.
    ///
    /// The limit is a parameter rather than a read of `V3WireContract` so this
    /// file stays independently compilable, exactly as the wire contract stays
    /// free of the error model. The caller passes the one shared constant, so
    /// the limit still has a single definition in production.
    static func encode(_ value: [String: Any], operation: String = "command",
                       limit: Int) -> Data {
        encodeDetailed(value, operation: operation, limit: limit).data
    }

    /// Returns a safe fallback marker with the data so the service can log
    /// classification without parsing every successful serialized reply.
    static func encodeDetailed(_ value: [String: Any], operation: String = "command",
                               limit: Int) -> V3EncodedServiceResponse {
        let correlationID = value["id"] as? String ?? ""
        do {
            let data = try PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0)
            guard data.count <= limit else {
                return V3EncodedServiceResponse(data: fallback(id: correlationID, operation: operation,
                                token: V3ResponseClassifier.Token.tooLarge,
                                code: .invalidResponse,
                                safeCause: V3ResponseClassifier.safeCause(for: V3ResponseClassifier.Token.tooLarge)),
                    fallbackToken: V3ResponseClassifier.Token.tooLarge)
            }
            return V3EncodedServiceResponse(data: data, fallbackToken: nil)
        } catch {
            return V3EncodedServiceResponse(data: fallback(id: correlationID, operation: operation,
                            token: V3ResponseClassifier.Token.encodingFailed,
                            code: .invalidResponse,
                            safeCause: V3ResponseClassifier.safeCause(for: V3ResponseClassifier.Token.encodingFailed)),
                fallbackToken: V3ResponseClassifier.Token.encodingFailed)
        }
    }

    /// Builds a small, correlated, typed fallback reply. Always serializable
    /// because every value is a concrete String, Bool or Int.
    ///
    /// The reply deliberately carries BOTH the legacy "error" token and the
    /// structured "failure" envelope, because that is the shape production
    /// emits. The structured envelope is authoritative on the host, so the
    /// classification that survives is the safeCause set here.
    static func fallback(id: String, operation: String, token: String,
                         code: CombinedFailure.Code,
                         safeCause: CombinedFailure.SafeCause? = nil) -> Data {
        let value: [String: Any] = [
            "version": 1,
            "id": id,
            "error": token,
            "failure": CombinedFailure(operation: operation, stage: .replyEncoding, code: code,
                                       id: id, safeCause: safeCause).wire
        ]
        return (try? PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0)) ?? Data()
    }
}

// V3_SHARED_JITLESS_FACT_V1
// Home and the Setup Assistant each decided JIT-Less completion separately. Home
// had no access to the certificate facts, so on the platforms that require
// JIT-Less it reported the item as permanently outstanding while the assistant,
// which had the real readiness, showed it complete. One observed readiness is
// now published and both surfaces read it.
//
// A nil readiness means "not observed yet", which counts as outstanding. Guessing
// "fine" there is what produced the original disagreement.
enum V3JITLessCompletionPolicy {
    static func isComplete(_ readiness: V3JITLessReadiness?) -> Bool {
        guard let readiness else { return false }
        return readiness.isReady
    }

    /// True where an unobserved JIT-Less state is still an outstanding item.
    static func isRequired(osMajor: Int) -> Bool { osMajor >= 26 }
}

enum V3SetupFactObservationPolicy {
    static let maximumAge: TimeInterval = 5 * 60

    static func shouldObserve(connected: Bool, setupPresented: Bool,
                              operationPresented: Bool, loading: Bool,
                              returnToSetupPending: Bool, lastAttemptAt: Date?,
                              now: Date = Date()) -> Bool {
        guard connected, !setupPresented, !operationPresented, !loading,
              !returnToSetupPending else { return false }
        guard let lastAttemptAt else { return true }
        guard lastAttemptAt <= now else { return false }
        return now.timeIntervalSince(lastAttemptAt) >= maximumAge
    }
}

enum V3SetupFactRevisionPolicy {
    static func mayApply(captured: UInt64, current: UInt64) -> Bool {
        captured == current
    }
}

// V3_HOST_SNAPSHOT_WAITER_LIFETIME_V1
// Snapshot callers may cancel while the shared service request must continue
// for other callers. This registry gives each waiter one removable identity and
// drains only the waiters that are still pending when the snapshot finishes.
struct V3SnapshotWaiterRegistry {
    private struct Waiter: Equatable {
        let manual: Bool
        let requiredSnapshotGeneration: UInt64
    }
    private var waitersByID: [UUID: Waiter] = [:]

    var isEmpty: Bool { waitersByID.isEmpty }
    var anyManualWaiter: Bool { waitersByID.values.contains(where: \.manual) }

    mutating func insert(_ id: UUID, manual: Bool,
                         requiredSnapshotGeneration: UInt64 = 0) {
        waitersByID[id] = Waiter(manual: manual,
                                 requiredSnapshotGeneration: requiredSnapshotGeneration)
    }

    @discardableResult
    mutating func remove(_ id: UUID) -> Bool {
        waitersByID.removeValue(forKey: id) != nil
    }

    /// Take only callers whose freshness requirement is met by this snapshot.
    /// Waiters parked behind a blocker during an older in-flight snapshot remain
    /// registered until a later generation completes.
    mutating func take(throughSnapshotGeneration generation: UInt64) -> [UUID] {
        let ready = waitersByID.compactMap { id, waiter in
            waiter.requiredSnapshotGeneration <= generation ? id : nil
        }
        for id in ready { waitersByID.removeValue(forKey: id) }
        return ready
    }

    mutating func takeAll() -> [UUID] {
        let ids = Array(waitersByID.keys)
        waitersByID.removeAll(keepingCapacity: true)
        return ids
    }
}

/// Maps the gate decision to the minimum snapshot generation that can satisfy
/// the caller. A deferred request must not be released by a snapshot that began
/// before its mutation/presentation blocker ended.
enum V3SnapshotWaiterEpochPolicy {
    static func requiredGeneration(for decision: V3SnapshotDecision,
                                   currentGeneration: UInt64) -> UInt64 {
        switch decision {
        case .performSnapshot, .joinSnapshot, .doNotObserve:
            return currentGeneration
        case .awaitMutationThenSnapshot, .deferForPresentation, .stillBlocked:
            return currentGeneration &+ 1
        }
    }
}

enum V3SnapshotErrorPolicy {
    /// Cancellation is a local control-flow result, not evidence that the
    /// backend became disconnected.
    static func shouldMarkDisconnected(_ error: Error) -> Bool {
        !(error is CancellationError)
    }
}

// Health notifications can arrive while a request is in flight. Keep one
// pending rerun so a certificate update is observed after the current request.
struct V3HealthReloadQueue {
    private(set) var isChecking = false
    private(set) var rerunRequested = false

    mutating func request() -> Bool {
        guard !isChecking else {
            rerunRequested = true
            return false
        }
        isChecking = true
        return true
    }

    /// Returns true when exactly one queued request should run next.
    mutating func finishIteration() -> Bool {
        guard rerunRequested else {
            isChecking = false
            return false
        }
        rerunRequested = false
        return true
    }
}

enum V3RetryDisposition: Equatable {
    case allowed
    case unknown
    case prerequisite
    case blocked
}

enum V3CatalogRetryPresentation: Equatable {
    case retry
    case retryWithUnknownDisposition
    case reloadCatalog
    case noRetry
}

enum V3CatalogRetryPresentationPolicy {
    static func action(for disposition: V3RetryDisposition,
                       safeCause: String? = nil) -> V3CatalogRetryPresentation {
        if safeCause == CombinedFailure.SafeCause.catalogUnavailable.rawValue {
            return .reloadCatalog
        }
        switch disposition {
        case .allowed: return .retry
        case .unknown: return .retryWithUnknownDisposition
        case .prerequisite, .blocked: return .noRetry
        }
    }
}

// V3_REFRESH_PREREQUISITE_POLICY_V1
// One authoritative prerequisite contract for every refresh entry point. Home
// Refresh All, Setup Assistant Test Refresh, Refresh Manager Manual Refresh,
// and targeted per-app refresh all call this instead of re-deriving rules, so
// a prerequisite the host already knows about can never be reported later as
// "no safe underlying cause was available".
//
// Two invariants are encoded here rather than at each call site.
// 1. The service's pairing status string is interpreted in exactly one place.
// 2. Only an authoritative "Pairing file required" blocks. "Unknown" (before
//    the first snapshot, or after a failed snapshot) does not block, so a host
//    restart can never permanently disable a correctly configured device.
//    Nothing is blocked on Wi-Fi, LocalDevVPN, or an account here: those are
//    not proven required for a refresh, and the scheduler already owns the
//    transport preflight for them.
enum V3RefreshPrerequisiteState: String, Equatable {
    case unknown
    case satisfied
    case unsatisfied
}

enum V3RefreshPrerequisiteKind: String, Equatable {
    case pairing
}

struct V3RefreshPrerequisite: Equatable {
    let state: V3RefreshPrerequisiteState
    let kind: V3RefreshPrerequisiteKind?
    let detail: String

    static let pairingRequiredDetail = "A valid pairing file is required before device refresh."

    private init(state: V3RefreshPrerequisiteState, kind: V3RefreshPrerequisiteKind?, detail: String) {
        self.state = state
        self.kind = kind
        self.detail = detail
    }

    static let unknown = V3RefreshPrerequisite(state: .unknown, kind: nil, detail: "")
    static let satisfied = V3RefreshPrerequisite(state: .satisfied, kind: nil, detail: "Pairing file available")
    static let pairingRequired = V3RefreshPrerequisite(state: .unsatisfied, kind: .pairing, detail: pairingRequiredDetail)

    /// The only interpretation of the authoritative pairing snapshot string.
    static func evaluate(pairingStatus: String?) -> V3RefreshPrerequisite {
        switch pairingStatus {
        case "Pairing file available": return .satisfied
        case "Pairing file required", "Pairing file invalid": return .pairingRequired
        default: return .unknown
        }
    }

    static func isConfirmed(pairingStatus: String?) -> Bool {
        evaluate(pairingStatus: pairingStatus).state == .satisfied
    }

    /// A cached pairing string is authoritative only while its snapshot is
    /// connected. After a failed snapshot, preserve the value for diagnostics
    /// but treat it as unknown for admission so stale state cannot block a run.
    static func evaluate(statusConnected: Bool, pairingStatus: String?) -> V3RefreshPrerequisite {
        guard statusConnected else { return .unknown }
        return evaluate(pairingStatus: pairingStatus)
    }

    var blocksRefresh: Bool { state == .unsatisfied }
    var blocksTargetedRefresh: Bool { blocksRefresh }
    var recoveryDestination: String? { kind == .pairing ? "pairing" : nil }
    var recoveryActionTitle: String? { kind == .pairing ? "Show Pairing Setup" : nil }
    var recommendedAction: String {
        kind == .pairing
            ? "Place or import a valid pairing file, then try again."
            : "Reload status, then try again."
    }

    /// The canonical structured failure for a blocked refresh. Minted only on
    /// demand so it can carry the caller's correlation ID.
    func failure(correlationID: String) -> CombinedFailure? {
        guard kind == .pairing else { return nil }
        return CombinedFailure(operation: "refresh", stage: .pairing, code: .notReady,
                               id: correlationID, retryable: false, safeCause: .pairingRequired)
    }
}

enum V3PairingPresentationPolicy {
    static func state(statusConnected: Bool, pairingStatus: String?) -> V3RefreshPrerequisiteState {
        V3RefreshPrerequisite.evaluate(statusConnected: statusConnected,
            pairingStatus: pairingStatus).state
    }

    /// A cached pairing value remains useful as history after a failed reload,
    /// but it must not look like a current authoritative result.
    static func displayText(statusConnected: Bool, pairingStatus: String) -> String {
        guard !statusConnected else { return pairingStatus }
        guard pairingStatus != "Unknown" else { return "Unknown" }
        return "Unknown (last known: \(pairingStatus))"
    }

    static func isConfirmed(statusConnected: Bool, pairingStatus: String?) -> Bool {
        state(statusConnected: statusConnected, pairingStatus: pairingStatus) == .satisfied
    }
}

enum V3IssueActionOutcomePolicy {
    /// Re-request actions dismiss the issue only when their request was
    /// accepted. A rejected retry replaces the alert with its current blocker.
    static func shouldDismiss(action: V3IssueAction, didStart: Bool) -> Bool {
        switch action {
        case .retrySource, .reloadSources: return didStart
        default: return true
        }
    }
}

struct V3OperationFailureDetails {
    let operation: String
    let stage: String
    let code: String
    let correlation: String
    let underlyingDomain: String
    let underlyingCode: Int
    let retryable: Bool?
    let safeCause: String?
    let sourceStep: String?
    let whatHappened: String
    let whatToDo: String
    let technical: String

    init(_ failure: CombinedFailure) {
        operation = failure.operation
        stage = failure.stage.rawValue
        code = failure.code.rawValue
        correlation = failure.correlationID
        underlyingDomain = failure.underlyingDomain
        underlyingCode = failure.underlyingCode
        retryable = failure.retryable
        safeCause = failure.safeCause?.rawValue
        sourceStep = failure.sourceStep?.rawValue
        whatHappened = failure.safeMessage
        whatToDo = failure.recovery
        technical = failure.technicalDetails
    }

    var retryDisposition: V3RetryDisposition {
        if safeCause == CombinedFailure.SafeCause.catalogSourceUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.responseEncodingFailed.rawValue ||
           safeCause == CombinedFailure.SafeCause.responseTooLarge.rawValue {
            return .blocked
        }
        if retryable == false { return .blocked }
        if stage == CombinedFailure.Stage.authentication.rawValue ||
           stage == CombinedFailure.Stage.filePreparation.rawValue ||
           safeCause == CombinedFailure.SafeCause.certificateUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.provisioningProfileUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.operationInProgress.rawValue ||
           safeCause == CombinedFailure.SafeCause.responseCapacityUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.authResponseCapacityUnavailable.rawValue {
            return .prerequisite
        }
        return retryable == true ? .allowed : .unknown
    }

    var recoveryDestination: String? {
        if operation == "source" ||
           [CombinedFailure.SafeCause.sourceNetworkFailure.rawValue,
            CombinedFailure.SafeCause.sourceInvalidManifest.rawValue,
            CombinedFailure.SafeCause.sourcePersistenceUnverified.rawValue,
            CombinedFailure.SafeCause.sourceInvalidURL.rawValue,
            CombinedFailure.SafeCause.sourceAddBusy.rawValue,
            CombinedFailure.SafeCause.catalogSourceUnavailable.rawValue].contains(safeCause ?? "") {
            return "sources"
        }
        if safeCause == CombinedFailure.SafeCause.pairingRequired.rawValue ||
           safeCause == CombinedFailure.SafeCause.invalidPairingFile.rawValue { return "pairing" }
        if safeCause == CombinedFailure.SafeCause.authResponseCapacityUnavailable.rawValue { return "signIn" }
        if stage == CombinedFailure.Stage.authentication.rawValue { return "signIn" }
        if stage == CombinedFailure.Stage.filePreparation.rawValue { return "ipa" }
        if safeCause == CombinedFailure.SafeCause.signingNetworkConnectionLost.rawValue ||
           safeCause == CombinedFailure.SafeCause.signingNetworkTimedOut.rawValue ||
           safeCause == CombinedFailure.SafeCause.signingNetworkUnavailable.rawValue {
            return "connection"
        }
        if stage == CombinedFailure.Stage.network.rawValue ||
           safeCause == CombinedFailure.SafeCause.networkConnectionLost.rawValue ||
           safeCause == CombinedFailure.SafeCause.networkTimedOut.rawValue ||
           safeCause == CombinedFailure.SafeCause.networkUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.signingNetworkConnectionLost.rawValue ||
           safeCause == CombinedFailure.SafeCause.signingNetworkTimedOut.rawValue ||
           safeCause == CombinedFailure.SafeCause.signingNetworkUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.wifiUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.localDevVPNUnavailable.rawValue {
            return "connection"
        }
        if sourceStep == CombinedFailure.SourceStep.certificateValidation.rawValue ||
           safeCause == CombinedFailure.SafeCause.certificateUnavailable.rawValue {
            return "certificates"
        }
        return nil
    }

    var recoveryActionTitle: String? {
        switch recoveryDestination {
        case "signIn": return "Open Account & Signing"
        case "ipa": return "Choose IPA Again"
        case "certificates": return "Open Certificates"
        case "connection": return "Open Connection Settings"
        case "pairing": return "Open Pairing File"
        case "sources": return "Open Sources"
        default: return nil
        }
    }

    var recommendedAction: String {
        if safeCause == CombinedFailure.SafeCause.appIDLimitReached.rawValue { return whatToDo }
        if safeCause == CombinedFailure.SafeCause.responseEncodingFailed.rawValue {
            return "Copy Diagnostics and report that the service could not encode its response. Repeating the same request will not help."
        }
        if safeCause == CombinedFailure.SafeCause.responseTooLarge.rawValue {
            return "Copy Diagnostics and report that the service reply exceeded the transfer limit. Repeating the same request will fail again."
        }
        if safeCause == CombinedFailure.SafeCause.catalogUnavailable.rawValue {
            return "Reload this source's catalog. If it still cannot be read, copy Diagnostics and report the local catalog failure."
        }
        if safeCause == CombinedFailure.SafeCause.responseCapacityUnavailable.rawValue ||
           safeCause == CombinedFailure.SafeCause.authResponseCapacityUnavailable.rawValue {
            return "Wait for SideStore to release earlier request results, reload status, then try again."
        }
        switch safeCause ?? "" {
        case CombinedFailure.SafeCause.sourceNetworkFailure.rawValue:
            return "Open Sources. Check the network, then retry adding the source."
        case CombinedFailure.SafeCause.sourceInvalidManifest.rawValue,
             CombinedFailure.SafeCause.sourceInvalidURL.rawValue:
            return "Open Sources and correct the source URL or manifest before retrying."
        case CombinedFailure.SafeCause.sourceBlocked.rawValue:
            return "Do not add this source. Verify with the provider that it is safe before trying again."
        case CombinedFailure.SafeCause.sourceChangedID.rawValue:
            return "Contact the source provider before removing the saved source or adding it again."
        case CombinedFailure.SafeCause.sourceDuplicate.rawValue:
            return "Open Sources and use the existing source. Remove it only after confirming which entry is correct."
        case CombinedFailure.SafeCause.sourceUnsupported.rawValue:
            return "Update SideStore or use a source format supported by this version."
        case CombinedFailure.SafeCause.sourceValidationFailed.rawValue:
            return "Ask the source provider to correct its metadata, then preview it again."
        case CombinedFailure.SafeCause.sourcePersistenceUnverified.rawValue:
            return "Open Sources and reload the list to see whether the source was saved before retrying."
        case CombinedFailure.SafeCause.sourceAddBusy.rawValue,
             CombinedFailure.SafeCause.sourceRemoveBusy.rawValue:
            return "Wait for SideStore's active request to finish, then open Sources and check the result."
        case CombinedFailure.SafeCause.catalogSourceUnavailable.rawValue:
            return "Open Sources to confirm the source is still added, then reopen its catalog."
        default: break
        }
        if operation == "source" ||
           sourceStep == CombinedFailure.SourceStep.sourceDownload.rawValue ||
           sourceStep == CombinedFailure.SourceStep.manifestParsing.rawValue {
            return "Open Sources and review the source request. Copy Diagnostics if the result remains unclear."
        }
        switch safeCause ?? "" {
        case CombinedFailure.SafeCause.responseCapacityUnavailable.rawValue:
            return "Wait for SideStore to release earlier request results, check the current state, then retry this action."
        case CombinedFailure.SafeCause.pairingRequired.rawValue:
            return "Add the pairing file, then start the refresh again."
        case CombinedFailure.SafeCause.invalidPairingFile.rawValue:
            return "Open Pairing File and replace the saved pairing record, then retry."
        case CombinedFailure.SafeCause.operationInProgress.rawValue:
            return "Wait for the active SideStore operation to finish, then start this action again."
        case CombinedFailure.SafeCause.staleRefreshAttempt.rawValue:
            return "This stale refresh request was not started. Return to Refresh and start a new refresh."
        case CombinedFailure.SafeCause.signingNetworkConnectionLost.rawValue:
            return "Your current connection may still be healthy. Retry once. If this happens again, open Connection Settings."
        case CombinedFailure.SafeCause.signingNetworkTimedOut.rawValue:
            return "The provisioning service timed out for this request. Retry once. If it happens again, open Connection Settings."
        case CombinedFailure.SafeCause.signingNetworkUnavailable.rawValue:
            return "The provisioning service could not be reached for this request. Retry once. If it happens again, open Connection Settings."
        default: break
        }
        switch recoveryDestination {
        case "signIn": return "Open Account & Signing and complete the required account step."
        case "ipa": return "Choose the IPA again so SideStore can stage a fresh copy."
        case "certificates": return "Open Certificates and review the active certificate and provisioning profile."
        case "setup": return "Open Health Check / Connection and restore the required connection."
        default:
            if retryable == false {
                return "This operation is not marked safe to retry. Check the app and signing status before running it again."
            }
            if retryable == nil {
                if !whatToDo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    return whatToDo
                }
                return "The service could not determine whether retry is safe. Check the app and signing status before deciding to retry."
            }
            return whatToDo
        }
    }
}

struct V3OperationPromptFailureDetails {
    let failure: V3OperationFailureDetails
    let blocksResubmission: Bool

    init(_ combinedFailure: CombinedFailure) {
        let details = V3OperationFailureDetails(combinedFailure)
        failure = details
        blocksResubmission = details.retryDisposition != .allowed
    }
}

// Keeps the failed pipeline stage across a Retry transition. A failure while
// creating the next backend session is explicitly separate from pipeline failure.
struct V3OperationRetryContext {
    private(set) var previousFailure: V3OperationFailureDetails?
    private(set) var currentFailure: V3OperationFailureDetails?
    private(set) var retryCouldNotStart = false

    mutating func recordPipelineFailure(_ failure: CombinedFailure) {
        currentFailure = V3OperationFailureDetails(failure)
        retryCouldNotStart = false
    }

    mutating func beginRetry() {
        previousFailure = currentFailure
        currentFailure = nil
        retryCouldNotStart = false
    }

    mutating func operationStarted() {
        previousFailure = nil
        currentFailure = nil
        retryCouldNotStart = false
    }

    mutating func recordStartFailure(_ failure: CombinedFailure) {
        currentFailure = V3OperationFailureDetails(failure)
        retryCouldNotStart = true
    }

    mutating func reset() {
        previousFailure = nil
        currentFailure = nil
        retryCouldNotStart = false
    }

    var whatHappened: String {
        guard let currentFailure else { return "The operation failed." + "\nError ID: SS-CMD-D064" }
        guard retryCouldNotStart else { return currentFailure.whatHappened }
        if currentFailure.safeCause == CombinedFailure.SafeCause.operationInProgress.rawValue {
            if let previousFailure {
                return "The retry could not start because another SideStore operation is still active. Previous attempt: \(previousFailure.whatHappened)"
            }
            return "The operation could not start because another SideStore operation is still active." + "\nError ID: SS-CMD-D065"
        }
        if let previousFailure {
            if ["timedOut", "interrupted"].contains(currentFailure.code) {
                return "The retry could not be confirmed as started. The previous operation may still be active. Previous attempt: \(previousFailure.whatHappened)"
            }
            return "The retry could not start, so the app operation did not run. Previous attempt: \(previousFailure.whatHappened)"
        }
        if ["timedOut", "interrupted"].contains(currentFailure.code) {
            return "The operation could not be confirmed as started. It may still be active." + "\nError ID: SS-CMD-D066"
        }
        return "The operation could not start, so the app pipeline did not run." + "\nError ID: SS-CMD-D067"
    }

    var whatToDo: String {
        guard let currentFailure else { return "Review the operation and try again only when it is safe." }
        guard retryCouldNotStart else { return currentFailure.recommendedAction }
        if currentFailure.safeCause == CombinedFailure.SafeCause.operationInProgress.rawValue {
            return "Wait for the active SideStore operation to finish, then start a fresh attempt."
        }
        if previousFailure != nil {
            return "The retry could not start. \(currentFailure.recommendedAction)"
        }
        return "The operation could not start. \(currentFailure.recommendedAction)"
    }

    var technicalDetails: String {
        let current = currentFailure?.technical ?? "No structured failure record was returned."
        guard retryCouldNotStart, let previousFailure else { return current }
        return "retry_start_failure:\n\(current)\nprevious_attempt_failure:\n\(previousFailure.technical)"
    }

    var retryDisposition: V3RetryDisposition {
        guard let currentFailure else { return .unknown }
        return currentFailure.retryDisposition
    }
}

enum V3OperationRetrySafetyPolicy {
    enum Disposition: Equatable { case retry, alreadyCompleted, outcomeUnknown }

    static func canRetry(backendSettled: Bool?, outcomeUnknown: Bool) -> Bool {
        !outcomeUnknown && backendSettled == true
    }

    static func disposition(state: String?, backendSettled: Bool?, outcomeUnknown: Bool) -> Disposition {
        guard canRetry(backendSettled: backendSettled, outcomeUnknown: outcomeUnknown) else {
            return .outcomeUnknown
        }
        if state == "completed" { return .alreadyCompleted }
        guard ["failed", "cancelled", "requiresSource", "waitingForAuthentication"].contains(state ?? "") else {
            return .outcomeUnknown
        }
        return .retry
    }
}

enum V3OperationRetryButtonPolicy {
    static func title(state: String, retryDisposition: V3RetryDisposition) -> String {
        if state == "cancelled" { return "Retry" }
        return retryDisposition == .unknown ? "Retry (retryability unknown)" : "Retry"
    }
}

struct V3OperationCancellationPresentation: Equatable {
    let message: String
    let whatToDo: String
}

enum V3OperationCancellationPresentationPolicy {
    static func resolve(userRequested: Bool) -> V3OperationCancellationPresentation {
        V3OperationCancellationPresentation(
            message: userRequested ? "The operation was cancelled." : "The operation was cancelled before it finished.",
            whatToDo: userRequested
                ? "The backend confirmed it stopped. Retry when you are ready to run this action again."
                : "The backend confirmed it stopped. Retry if you still need to complete this action.")
    }
}

enum V3OperationMissingSessionPolicy {
    static func unknownTerminal(sessionID: String, knownStarted: Bool) -> [String: Any]? {
        guard knownStarted else { return nil }
        return ["session": sessionID, "state": "failed", "backendSettled": false,
                "outcomeUnknown": true, "stopConfirmed": false,
                "message": "The operation session is no longer available, so its device result cannot be confirmed." + "\nError ID: SS-CMD-D068"]
    }
}

enum V3OperationTerminalAcceptancePolicy {
    static func isSettledTerminal(state: String?, backendSettled: Bool?, stopConfirmed: Bool?,
                                  outcomeUnknown: Bool = false) -> Bool {
        guard !outcomeUnknown else { return false }
        guard ["completed", "failed", "cancelled", "requiresSource", "waitingForAuthentication"]
                .contains(state ?? "") else { return false }
        return backendSettled == true || stopConfirmed == true
    }
}

enum V3OperationCancellationOutcomePolicy {
    static func isCorrelated(expectedSessionID: String, replySessionID: String?) -> Bool {
        replySessionID == expectedSessionID
    }

    static func terminalState(expectedSessionID: String, replySessionID: String?,
                              state: String?, backendSettled: Bool?, stopConfirmed: Bool?,
                              outcomeUnknown: Bool) -> String? {
        guard isCorrelated(expectedSessionID: expectedSessionID, replySessionID: replySessionID),
              V3OperationTerminalAcceptancePolicy.isSettledTerminal(state: state,
                  backendSettled: backendSettled, stopConfirmed: stopConfirmed,
                  outcomeUnknown: outcomeUnknown) else { return nil }
        return state
    }

    static func shouldClearSessionHandle(currentSessionID: String?, expectedSessionID: String,
                                         replySessionID: String?, state: String?,
                                         backendSettled: Bool?, stopConfirmed: Bool?,
                                         outcomeUnknown: Bool) -> Bool {
        currentSessionID == expectedSessionID &&
            terminalState(expectedSessionID: expectedSessionID, replySessionID: replySessionID,
                state: state, backendSettled: backendSettled, stopConfirmed: stopConfirmed,
                outcomeUnknown: outcomeUnknown) != nil
    }
}

enum V3OperationCancellationReplyPolicy {
    static func shouldApplyPollState(userRequestedCancellation: Bool, nextState: String) -> Bool {
        !(userRequestedCancellation && ["working", "awaitingPrompt"].contains(nextState))
    }
}

enum V3OperationStartDispatchPolicy {
    static func provesNotDispatched(resultWasReturned: Bool) -> Bool {
        !resultWasReturned
    }
}

enum V3RefreshTerminalRecoveryPolicy {
    enum Action: Equatable {
        case finalizeVerified
        case finalizeFailed
        case markInterrupted
    }

    static func action(state: String, terminalIntent: String?, manifestIsComplete: Bool,
                       hostHandoffPending: Bool) -> Action? {
        guard !["completed", "failed"].contains(state) else { return nil }
        if terminalIntent == "verified" && manifestIsComplete { return .finalizeVerified }
        if terminalIntent == "failed" { return .finalizeFailed }
        if hostHandoffPending { return nil }
        return ["running", "verifying", "failing"].contains(state) ? .markInterrupted : nil
    }
}

struct V3RefreshRunIdentitySelection: Equatable {
    let runID: String
    let schedulerOwned: Bool

    static func select(schedulerRunID: String?, expectedRunID: String?,
                       activeRunID: String?, newRunID: String) -> Self? {
        if let schedulerRunID {
            guard let parsed = UUID(uuidString: schedulerRunID), parsed.uuidString == schedulerRunID,
                  expectedRunID == schedulerRunID, activeRunID == schedulerRunID else { return nil }
            return Self(runID: schedulerRunID, schedulerOwned: true)
        }
        // A direct AppIntent cannot borrow an active scheduler's run identity.
        guard activeRunID == nil else { return nil }
        guard let generated = UUID(uuidString: newRunID), generated.uuidString == newRunID else { return nil }
        return Self(runID: newRunID, schedulerOwned: false)
    }
}

enum V3DirectRefreshPreflightPolicy {
    static func isBlocked(activeRunID: String?, hostHandoffPending: Bool,
                          uncertainMutationRunID: String?) -> Bool {
        activeRunID != nil || hostHandoffPending || uncertainMutationRunID != nil
    }
}

enum V3DirectRefreshRunClaimPolicy {
    static let defaultsKey = "liveContainerAutoRefreshDirectRunClaim"

    static func isActive(runID: String?, deadline: Date?, now: Date = Date()) -> Bool {
        guard let runID, let parsed = UUID(uuidString: runID), parsed.uuidString == runID,
              let deadline else { return false }
        return deadline > now
    }
}

enum V3RequestRetirementPolicy {
    private static let sessionControls: Set<String> = [
        "opStart", "opPoll", "opAnswer", "opCancel", "backupResult",
        "authPoll", "authRespond"
    ]

    static func shouldRetireServiceIfRequestStaysPending(_ operation: String) -> Bool {
        !sessionControls.contains(operation)
    }
}

enum V3CancellationRecoveryReplyPolicy {
    // Late auth/session-creation replies are not passed through the original
    // result classifier after settlement. Keep their service-retirement timer;
    // ordinary one-shot mutation callbacks retain their terminal recovery path.
    static func mayCancelRetirement(operation: String, requestStillPending: Bool) -> Bool {
        if requestStillPending { return true }
        // A late auth reply has not passed the request's result classifier, so
        // retain recovery until bounded service retirement clears host owners.
        if ["authBegin", "authRetryProvisioning", "authCancel", "refreshAdmissionBegin"].contains(operation) {
            return false
        }
        return true
    }
}

enum V3IdleReadRetirementPolicy {
    static func shouldRetireService(operation: String, hostMutationActive: Bool,
                                    refreshAttemptActive: Bool) -> Bool {
        guard !hostMutationActive, !refreshAttemptActive else { return false }
        // A timed-out authPoll is one lost observation of a live session, not
        // evidence that the in-memory SignInOperation should be discarded.
        return operation != "authPoll"
    }
}

struct V3AuthSessionOwnership {
    private(set) var deadlines: [String: Date] = [:]
    private static let terminalStates: Set<String> = [
        "completed", "authenticatedProvisioningIncomplete", "cancelled", "timedOut", "failed"
    ]

    mutating func register(sessionID: String, deadline: Date, now: Date = Date()) {
        prune(now: now)
        guard let parsed = UUID(uuidString: sessionID), parsed.uuidString == sessionID,
              deadline > now else { return }
        deadlines[sessionID] = deadline
        if deadlines.count > 256 {
            let oldest = deadlines.sorted { $0.value < $1.value }
            for (id, _) in oldest.prefix(deadlines.count - 256) { deadlines.removeValue(forKey: id) }
        }
    }

    mutating func observe(operation: String, sessionID: String, replySessionID: String?,
                          state: String?, now: Date = Date()) {
        prune(now: now)
        guard replySessionID == sessionID, let state, deadlines[sessionID] != nil else { return }
        if Self.terminalStates.contains(state) {
            deadlines.removeValue(forKey: sessionID)
        } else if ["authBegin", "authRetryProvisioning"].contains(operation),
                  ["working", "awaitingPrompt"].contains(state) {
            // A successful new begin returns only after the previous auth task
            // has unwound, so that response supersedes older host ownership.
            deadlines = deadlines.filter { $0.key == sessionID }
        }
    }

    mutating func prune(now: Date = Date()) {
        deadlines = deadlines.filter { $0.value > now }
    }

    mutating func clear(sessionID: String) {
        deadlines.removeValue(forKey: sessionID)
    }

    mutating func reconcile(sessionID: String, authenticationActive: Bool) {
        guard !authenticationActive else { return }
        clear(sessionID: sessionID)
    }

    mutating func clearAll() {
        deadlines.removeAll()
    }

    mutating func hasActiveSession(now: Date = Date()) -> Bool {
        prune(now: now)
        return !deadlines.isEmpty
    }

    func owns(_ sessionID: String, now: Date = Date()) -> Bool {
        deadlines[sessionID].map { $0 > now } == true
    }
}

enum V3ProvisioningResumeAvailabilityPolicy {
    static func canResume(authenticated: Bool, currentAppleID: String?, resumableAppleID: String?,
                          hasSession: Bool = true, hasTeamAccount: Bool = true,
                          teamAccountAppleID: String? = nil) -> Bool {
        guard authenticated, hasSession, hasTeamAccount,
              let currentAppleID, let resumableAppleID else { return false }
        guard let current = V3AuthIdentityBindingPolicy.normalizedOwner(currentAppleID),
              let resumable = V3AuthIdentityBindingPolicy.normalizedOwner(resumableAppleID),
              let teamOwner = V3AuthIdentityBindingPolicy.normalizedOwner(teamAccountAppleID) else { return false }
        return current == resumable && current == teamOwner
    }
}

// V3_AUTH_IDENTITY_BINDING_V1: the stored route remains an upstream fact;
// developer-portal readiness requires a coherent DSID/token session and the
// exact account owner associated with the team being sent to Apple.
enum V3AuthIdentityBindingPolicy {
    static func normalizedOwner(_ value: String?) -> String? {
        guard let value else { return nil }
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty ? nil : normalized
    }

    static func hasTokenBackedRoute(credentialRoutePresent: Bool,
                                    dsid: String?, xcodeToken: String?) -> Bool {
        credentialRoutePresent && dsid?.isEmpty == false && xcodeToken?.isEmpty == false
    }

    static func hasUsableSession(credentialRoutePresent: Bool, dsid: String?,
                                 xcodeToken: String?, sessionDSID: String?,
                                 sessionXcodeToken: String?,
                                 generationBefore: UInt64, generationAfter: UInt64) -> Bool {
        guard hasTokenBackedRoute(credentialRoutePresent: credentialRoutePresent,
                dsid: dsid, xcodeToken: xcodeToken), generationBefore == generationAfter,
              let dsid, let xcodeToken,
              let sessionDSID, !sessionDSID.isEmpty,
              let sessionXcodeToken, !sessionXcodeToken.isEmpty else { return false }
        return dsid == sessionDSID && xcodeToken == sessionXcodeToken
    }

    static func sameCredentialRoute(appleIDBefore: String?, appleIDAfter: String?,
                                    dsidBefore: String?, dsidAfter: String?,
                                    tokenBefore: String?, tokenAfter: String?) -> Bool {
        normalizedOwner(appleIDBefore) == normalizedOwner(appleIDAfter) &&
            dsidBefore == dsidAfter && tokenBefore == tokenAfter
    }

    static func mayUseTeam(sessionOwner: String?, teamOwner: String?) -> Bool {
        guard let sessionOwner = normalizedOwner(sessionOwner),
              let teamOwner = normalizedOwner(teamOwner) else { return false }
        return sessionOwner == teamOwner
    }

    static func resolveColdTeamOwner(storedTeamOwners: [String],
                                     activeTeamIdentifier: String?, requestedTeamIdentifier: String,
                                     activeAccountOwner: String?, sessionOwner: String?) -> String? {
        let activeTeamMatches = activeTeamIdentifier == requestedTeamIdentifier
        if activeTeamMatches, mayUseTeam(sessionOwner: sessionOwner, teamOwner: activeAccountOwner) {
            return normalizedOwner(sessionOwner)
        }
        let owners = Set(storedTeamOwners.compactMap(normalizedOwner))
        return owners.count == 1 ? owners.first : nil
    }

    static func mayFetchTeams(sessionOwner: String?, requestedOwner: String?,
                              generationBefore: UInt64, generationAfter: UInt64,
                              cancelled: Bool = false) -> Bool {
        mayDispatchTeamRequest(sessionOwner: sessionOwner, teamOwner: requestedOwner,
            generationBefore: generationBefore, generationAfter: generationAfter,
            cancelled: cancelled)
    }

    static func mayDispatchTeamRequest(sessionOwner: String?, teamOwner: String?,
                                       generationBefore: UInt64, generationAfter: UInt64,
                                       cancelled: Bool = false) -> Bool {
        mayDispatch(generationBefore: generationBefore, generationAfter: generationAfter,
                    cancelled: cancelled) &&
            mayUseTeam(sessionOwner: sessionOwner, teamOwner: teamOwner)
    }

    static func mayDispatch(generationBefore: UInt64, generationAfter: UInt64,
                            cancelled: Bool = false) -> Bool {
        !cancelled && generationBefore == generationAfter
    }

    static func mayProjectIdentity(generationBefore: UInt64, generationAfter: UInt64) -> Bool {
        generationBefore == generationAfter
    }
}

enum V3ProvisioningResumeIdentityPolicy {
    static func select(authenticatedSessionAppleID: String?, submittedAppleID: String?,
                       activeAppleID: String?) -> String? {
        for candidate in [authenticatedSessionAppleID, submittedAppleID, activeAppleID] {
            guard let value = candidate?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
                  !value.isEmpty else { continue }
            return value
        }
        return nil
    }
}

enum V3ProvisioningResumeExecutionPolicy {
    static func mayUseCachedSignIn(forceProvisioningRetry: Bool,
                                   requireFullProvisioning: Bool = false) -> Bool {
        !forceProvisioningRetry && !requireFullProvisioning
    }

    static func mayPromptForCredentials(forceProvisioningRetry: Bool) -> Bool {
        !forceProvisioningRetry
    }
}

// Completion is evidence from a full SignInOperation, never a database row.
// The journal is invalidated durably BEFORE a new attempt can mutate anything.
// A process restart may reuse verified completion only for the exact hashed
// credential route, team, certificate and device binding, never row presence.
// V3_MANUAL_SIGNIN_DEVICE_SETUP_DEFERRED_V1: never turn an error into deferral.
enum V3DeviceSetupDeferralPolicy {
    static func mayDefer(interactive: Bool, fullProvisioning: Bool,
                         retry: Bool, reauthenticating: Bool, pendingActivation: Bool,
                         skipDevice: Bool, skipCertificate: Bool, unconfigured: Bool) -> Bool {
        interactive && fullProvisioning && !retry && !reauthenticating && !pendingActivation &&
            !skipDevice && !skipCertificate && unconfigured
    }

    static func isIntentionalOutcome(state: String?, outcome: String?, reason: String?,
                                     authenticated: Bool, hasFailure: Bool) -> Bool {
        state == "authenticatedProvisioningIncomplete" && outcome == "setupDeferred" &&
            reason == "pairingUnconfigured" && authenticated && !hasFailure
    }
}

struct V3ProvisioningCompletionState {
    private static let journalKey = "V3VerifiedProvisioningCompletionV1"
    private let defaults: UserDefaults
    private(set) var attemptID: String?
    private var owner: String?
    private var identityStamp: String?
    private var completed = false
    private var completedBinding: String?

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    private func persist(_ record: [String: Any]) -> Bool {
        defaults.set(record, forKey: Self.journalKey)
        return defaults.synchronize() &&
            defaults.dictionary(forKey: Self.journalKey).map { NSDictionary(dictionary: $0).isEqual(to: record) } == true
    }

    @discardableResult
    mutating func begin(attemptID: String, owner: String?, identityStamp: String) -> Bool {
        guard persist(["version": 1, "state": "incomplete", "attemptID": attemptID,
                       "identityStamp": identityStamp]) else { return false }
        self.attemptID = attemptID
        self.owner = V3AuthIdentityBindingPolicy.normalizedOwner(owner)
        self.identityStamp = identityStamp
        completed = false
        completedBinding = nil
        return true
    }

    mutating func authenticated(attemptID: String, owner: String?, identityStamp: String) {
        guard self.attemptID == attemptID else { return }
        self.owner = V3AuthIdentityBindingPolicy.normalizedOwner(owner)
        self.identityStamp = identityStamp
        completed = false
    }

    @discardableResult
    mutating func complete(attemptID: String, owner: String?, identityStamp: String,
                           identityStable: Bool, fullProvisioningCompleted: Bool,
                           activeAccountMatches: Bool, activeTeamMatches: Bool,
                           activeCertificateMatches: Bool, binding: String?) -> Bool {
        guard self.attemptID == attemptID,
              self.owner != nil, self.owner == V3AuthIdentityBindingPolicy.normalizedOwner(owner),
              self.identityStamp == identityStamp, identityStable,
              fullProvisioningCompleted, activeAccountMatches, activeTeamMatches,
              activeCertificateMatches, let binding, !binding.isEmpty,
              persist(["version": 1, "state": "complete", "attemptID": attemptID,
                       "identityStamp": identityStamp, "binding": binding]) else { return false }
        completed = true
        completedBinding = binding
        return true
    }

    func status(owner: String?, identityStamp: String, identityStable: Bool,
                activeAccountPresent: Bool, activeTeamPresent: Bool,
                activeCertificatePresent: Bool, binding: String?) -> String {
        guard identityStable, let owner = V3AuthIdentityBindingPolicy.normalizedOwner(owner) else { return "unknown" }
        let prerequisitesPresent = activeAccountPresent && activeTeamPresent && activeCertificatePresent
        if attemptID != nil {
            guard self.owner == owner, self.identityStamp == identityStamp else { return "unknown" }
            return completed && prerequisitesPresent && binding == completedBinding ? "complete" : "incomplete"
        }
        guard let record = defaults.dictionary(forKey: Self.journalKey),
              record["version"] as? Int == 1, let binding, !binding.isEmpty,
              record["state"] as? String == "complete", record["binding"] as? String == binding else {
            return "unknown"
        }
        return prerequisitesPresent ? "complete" : "incomplete"
    }
}

enum V3ProvisioningReauthenticationIdentityPolicy {
    static func mayAuthenticate(expectedOwner: String, submittedOwner: String?,
                                currentOwner: String?, capturedStamp: String,
                                currentStamp: String, identityStable: Bool) -> Bool {
        guard let expected = V3AuthIdentityBindingPolicy.normalizedOwner(expectedOwner) else { return false }
        return expected == V3AuthIdentityBindingPolicy.normalizedOwner(submittedOwner) &&
            expected == V3AuthIdentityBindingPolicy.normalizedOwner(currentOwner) &&
            V3AuthReadStampPolicy.mayReturn(capturedStamp: capturedStamp,
                currentStamp: currentStamp, stable: identityStable)
    }
}

enum V3ProvisioningRetryRecoveryPolicy {
    static func availabilityAfterFailure(snapshotConfirmed: Bool,
                                         snapshotAllowsRetry: Bool,
                                         previouslyConfirmedAvailable: Bool) -> Bool {
        snapshotConfirmed ? snapshotAllowsRetry : previouslyConfirmedAvailable
    }
}

enum V3AuthTimeoutReconciliationPolicy {
    static func shouldReconcileAfterTerminal(_ state: String) -> Bool {
        ["timedOut", "failed", "cancelled", "resultUnknown", "promptExpired"].contains(state) ||
            state == "authenticatedProvisioningIncomplete"
    }
}

struct V3AuthReconciliationPresentation: Equatable {
    let state: String
    let message: String
}

enum V3AuthReconciliationPresentationPolicy {
    static func shouldPreserveActivePrompt(reportedState: String, hasPrompt: Bool,
                                           activeSessionMatches: Bool,
                                           cancellationInProgress: Bool) -> Bool {
        hasPrompt && activeSessionMatches && !cancellationInProgress &&
            ["working", "awaitingPrompt"].contains(reportedState)
    }

    static func resolve(reportedState: String, authenticated: Bool,
                        provisioningIncomplete: Bool,
                        previousFailureMessage: String? = nil,
                        authenticationActive: Bool = false) -> V3AuthReconciliationPresentation {
        guard authenticated else {
            switch reportedState {
            case "timedOut":
                return .init(state: "timedOut", message: "Sign-in timed out. SideStore reports that no account is currently signed in." + "\nError ID: SS-AUTH-D069")
            case "cancelled":
                return .init(state: "cancelled", message: "Sign-in was cancelled. SideStore reports that no account is currently signed in.")
            default:
                return .init(state: reportedState, message: "")
            }
        }
        if authenticationActive {
            return .init(state: "authenticatedProvisioningIncomplete",
                message: "Apple ID signed in successfully. SideStore is still finishing provisioning.")
        }
        switch reportedState {
        case "failed":
            var message = provisioningIncomplete
                ? "The sign-in attempt did not complete. SideStore reports authentication, but device provisioning is incomplete." + "\nError ID: SS-AUTH-D070"
                : "The sign-in attempt did not complete. SideStore currently reports an account as signed in." + "\nError ID: SS-AUTH-D071"
            if let previousFailureMessage { message += " " + previousFailureMessage }
            return .init(state: "failed", message: message)
        case "timedOut":
            return .init(state: "timedOut", message: provisioningIncomplete
                ? "The sign-in attempt timed out. SideStore reports authentication, but device provisioning is incomplete." + "\nError ID: SS-AUTH-D072"
                : "The sign-in attempt timed out. SideStore currently reports an account as signed in." + "\nError ID: SS-AUTH-D073")
        case "cancelled":
            return .init(state: "cancelled", message: provisioningIncomplete
                ? "The sign-in attempt was cancelled. SideStore reports authentication, but device provisioning is incomplete."
                : "The sign-in attempt was cancelled. SideStore currently reports an account as signed in.")
        case "resultUnknown":
            return .init(state: "resultUnknown", message: provisioningIncomplete
                ? "The sign-in result remains unconfirmed. SideStore reports authentication, but device provisioning is incomplete." + "\nError ID: SS-AUTH-D074"
                : "The sign-in result remains unconfirmed. SideStore currently reports an account as signed in." + "\nError ID: SS-AUTH-D075")
        case "promptExpired":
            return .init(state: "promptExpired", message: provisioningIncomplete
                ? "The verification session expired. SideStore reports authentication, but device provisioning is incomplete." + "\nError ID: SS-AUTH-D076"
                : "The verification session expired. SideStore currently reports an account as signed in." + "\nError ID: SS-AUTH-D077")
        default:
            return provisioningIncomplete
                ? .init(state: "authenticatedProvisioningIncomplete", message: "Apple ID signed in successfully.")
                : .init(state: "completed", message: "")
        }
    }
}

enum V3AuthInactiveSessionResolutionPolicy {
    static func resolve(reportedState: String, authenticated: Bool,
                        authenticationActive: Bool,
                        anotherSessionActive: Bool = false) -> V3AuthReconciliationPresentation? {
        if anotherSessionActive && !authenticated &&
           ["working", "awaitingPrompt", "resultUnknown"].contains(reportedState) {
            return .init(state: "resultUnknown",
                message: "Another Apple sign-in session is active. This request could not be matched to it. Wait for it to finish, then reload status." + "\nError ID: SS-AUTH-D078")
        }
        guard !authenticated, !authenticationActive,
              ["working", "awaitingPrompt", "resultUnknown"].contains(reportedState) else { return nil }
        return .init(state: "failed",
            message: "SideStore confirmed that no account is currently signed in. You can start a new sign-in.")
    }
}

struct V3AuthOtherSessionPresentation: Equatable {
    let state: String
    let message: String
    let clearPrompt: Bool
}

enum V3AuthOtherSessionReconciliationPolicy {
    static func resolve(reportedState: String, authenticated: Bool,
                        anotherSessionActive: Bool) -> V3AuthOtherSessionPresentation? {
        guard anotherSessionActive,
              ["idle", "working", "awaitingPrompt", "resultUnknown",
               "authenticatedProvisioningIncomplete"].contains(reportedState) else { return nil }
        let accountState = authenticated ? "Apple ID is signed in, but " : ""
        return .init(state: "resultUnknown",
            message: accountState + "another sign-in session is active. This request could not be matched to it. Wait for it to finish, then reload status.",
            clearPrompt: true)
    }
}

struct V3AuthReconciliationTicket: Equatable {
    let generation: UInt64
    let sessionID: String?
    let state: String
    let revision: Int
}

struct V3AuthReconciliationGate {
    private(set) var generation: UInt64 = 0

    mutating func invalidate() {
        generation &+= 1
    }

    mutating func begin(sessionID: String?, state: String, revision: Int) -> V3AuthReconciliationTicket {
        generation &+= 1
        return V3AuthReconciliationTicket(generation: generation, sessionID: sessionID,
            state: state, revision: revision)
    }

    func mayApply(_ ticket: V3AuthReconciliationTicket, sessionID: String?,
                  state: String, revision: Int) -> Bool {
        ticket.generation == generation && ticket.sessionID == sessionID &&
            ticket.state == state && ticket.revision == revision
    }

    func ownsSingleReconciliation(after priorGeneration: UInt64) -> Bool {
        generation == (priorGeneration &+ 1)
    }
}

enum V3AuthReconciliationSessionPolicy {
    static func mayStart(expectedSessionID: String?, currentSessionID: String?) -> Bool {
        expectedSessionID == nil || expectedSessionID == currentSessionID
    }
}

enum V3AuthSessionCorrelationPolicy {
    static func isActive(sessionID: String?, authenticationActive: Bool,
                         activeSessionID: String?) -> Bool {
        guard authenticationActive, let sessionID, let activeSessionID else { return false }
        return sessionID == activeSessionID
    }

    static func hasOtherActiveSession(sessionID: String?, authenticationActive: Bool,
                                      activeSessionID: String?) -> Bool {
        guard authenticationActive, let activeSessionID else { return false }
        guard let sessionID else { return true }
        return sessionID != activeSessionID
    }
}

enum V3AuthSnapshotAuthorityPolicy {
    struct Facts: Equatable {
        let authenticated: Bool
        let credentialRoutePresent: Bool
        let provisioningIncomplete: Bool
        let provisioningRetryAvailable: Bool
        let authenticationActive: Bool
        let authenticationSessionID: String?
    }

    static func facts(_ snapshot: V3AuthServiceSnapshot) -> Facts {
        Facts(authenticated: snapshot.identityStable && snapshot.authenticated,
              credentialRoutePresent: snapshot.identityStable && snapshot.credentialRoutePresent,
              provisioningIncomplete: snapshot.identityStable && snapshot.provisioningIncomplete,
              provisioningRetryAvailable: snapshot.identityStable && snapshot.provisioningRetryAvailable,
              authenticationActive: snapshot.authenticationActive,
              authenticationSessionID: snapshot.authenticationSessionID)
    }

    static func isAuthenticated(_ snapshot: [String: Bool]) -> Bool {
        snapshot["authenticated"] == true
    }

    static func needsSignIn(authenticated: Bool) -> Bool { !authenticated }
}

struct V3AccountSessionPresentation: Equatable {
    let showSignIn: Bool
    let showSavedAppleID: Bool
    let showUnverifiedSavedState: Bool
    let showRetainedCertificateGuidance: Bool
    let showSignOut: Bool
}

enum V3AccountSessionPresentationPolicy {
    static func resolve(authenticated: Bool, activeAccountPresent: Bool,
                        activeTeamPresent: Bool, activeCertificatePresent: Bool) -> V3AccountSessionPresentation {
        let hasSavedAccountState = activeAccountPresent || activeTeamPresent
        return V3AccountSessionPresentation(
            showSignIn: !authenticated,
            showSavedAppleID: activeAccountPresent,
            showUnverifiedSavedState: !authenticated && hasSavedAccountState,
            showRetainedCertificateGuidance: !authenticated && activeCertificatePresent,
            // Sign Out clears the saved account/team session, but deliberately
            // retains signing certificates. A certificate alone cannot justify
            // presenting Sign Out as a way to remove stale local state.
            showSignOut: authenticated || hasSavedAccountState)
    }
}

enum V3DeveloperDataActionAvailabilityPolicy {
    static func isEnabled(authenticated: Bool, isLoading: Bool) -> Bool {
        authenticated && !isLoading
    }
}

struct V3AuthSessionUnavailablePresentation: Equatable {
    let state: String
    let message: String
    let provisioningMessage: String?
    let cancellationConfirmed: Bool
}

enum V3AuthSessionUnavailablePolicy {
    static func shouldRetireOwnership(sessionID: String, currentSessionID: String?,
                                      failure: CombinedFailure) -> Bool {
        currentSessionID == sessionID && failure.operation == "signIn" &&
            failure.stage == .authentication && failure.safeCause == .authSessionUnavailable
    }

    static func resolve(authenticated: Bool, provisioningIncomplete: Bool,
                        snapshotConfirmed: Bool, safeMessage: String,
                        recovery: String, anotherSessionActive: Bool = false) -> V3AuthSessionUnavailablePresentation {
        guard snapshotConfirmed else {
            return V3AuthSessionUnavailablePresentation(
                state: "resultUnknown",
                message: "SideStore no longer has the active sign-in session. The current account and provisioning state could not be confirmed. Reload status before continuing." + "\nError ID: SS-AUTH-D079",
                provisioningMessage: nil,
                cancellationConfirmed: false)
        }
        if anotherSessionActive {
            return V3AuthSessionUnavailablePresentation(
                state: "resultUnknown",
                message: "Another Apple sign-in session is active. This request could not be matched to it. Wait for it to finish, then reload status." + "\nError ID: SS-AUTH-D078",
                provisioningMessage: nil,
                cancellationConfirmed: true)
        }
        if authenticated && provisioningIncomplete {
            return V3AuthSessionUnavailablePresentation(
                state: "authenticatedProvisioningIncomplete",
                message: "Apple ID signed in successfully.",
                provisioningMessage: "The saved provisioning session is no longer available. Open Account & Signing to sign in again before retrying setup." + "\nError ID: SS-AUTH-D080",
                cancellationConfirmed: true)
        }
        if authenticated {
            return V3AuthSessionUnavailablePresentation(
                state: "completed",
                message: "SideStore confirmed that the account is signed in.",
                provisioningMessage: nil,
                cancellationConfirmed: true)
        }
        let message = snapshotConfirmed
            ? safeMessage + " " + recovery
            : "SideStore no longer has the active sign-in session and could not confirm the account state. Reload status before starting a new sign-in." + "\nError ID: SS-AUTH-D081"
        return V3AuthSessionUnavailablePresentation(
            state: "failed", message: message, provisioningMessage: nil,
            cancellationConfirmed: true)
    }
}

enum V3AuthPollRecoveryPolicy {
    static func isTransientTransportFailure(_ failure: CombinedFailure) -> Bool {
        if failure.safeCause == .authSessionUnavailable { return false }
        let networkTransportCause = failure.safeCause.map {
            [.networkConnectionLost, .networkTimedOut, .networkUnavailable].contains($0)
        } ?? false
        if networkTransportCause {
            return failure.stage == .xpcConnection
        }
        return failure.code == .timedOut ||
            failure.code == .interrupted && failure.stage == .xpcConnection
    }

    static func shouldRetry(_ failure: CombinedFailure, now: Date = Date(),
                            sessionDeadline: Date) -> Bool {
        now < sessionDeadline && isTransientTransportFailure(failure)
    }

    static func shouldFinishTimedOut(_ failure: CombinedFailure, now: Date = Date(),
                                     sessionDeadline: Date) -> Bool {
        now >= sessionDeadline && isTransientTransportFailure(failure)
    }

    static func retryDelay(attempt: Int) -> TimeInterval {
        let backoff: [TimeInterval] = [1, 2, 5, 10]
        return backoff[min(max(0, attempt), backoff.count - 1)]
    }

    static func retryDelay(attempt: Int, remaining: TimeInterval) -> TimeInterval {
        guard remaining.isFinite, remaining > 0 else { return 0 }
        return min(retryDelay(attempt: attempt), remaining)
    }
}

enum V3AuthPollFailureRacePolicy {
    static func shouldIgnore(requestedSessionID: String, currentSessionID: String?,
                             requestedRevision: Int, currentRevision: Int,
                             requestedPromptResponseGeneration: UInt64,
                             currentPromptResponseGeneration: UInt64,
                             promptSubmissionInProgress: Bool) -> Bool {
        currentSessionID == requestedSessionID &&
            (requestedRevision != currentRevision ||
             requestedPromptResponseGeneration != currentPromptResponseGeneration ||
             promptSubmissionInProgress)
    }
}

enum V3AuthPollMonitorRecoveryPolicy {
    static func shouldResumeAfterAmbiguousStart(requestedSessionID: String,
                                                currentSessionID: String?,
                                                activeSessionID: String?,
                                                cancellationInProgress: Bool,
                                                taskCancelled: Bool) -> Bool {
        currentSessionID == requestedSessionID && activeSessionID == requestedSessionID &&
            !cancellationInProgress && !taskCancelled
    }

    static func shouldResume(requestedSessionID: String, currentSessionID: String?,
                             failedPromptRevision: Int,
                             currentPromptRevision: Int,
                             failedPromptResponseGeneration: UInt64,
                             currentPromptResponseGeneration: UInt64,
                             state: String, promptSubmissionInProgress: Bool,
                             activeSessionID: String? = nil,
                             pollFailureIsTransient: Bool = false,
                             cancellationInProgress: Bool, taskCancelled: Bool,
                             reconciliationWasSuperseded: Bool = false,
                             now: Date = Date(), sessionDeadline: Date) -> Bool {
        let authenticationActive = activeSessionID == requestedSessionID
        let anotherSessionActive = activeSessionID != nil && !authenticationActive
        guard currentSessionID == requestedSessionID,
              !anotherSessionActive,
              !cancellationInProgress, !taskCancelled,
              (["working", "awaitingPrompt"].contains(state) ||
                (authenticationActive && ["completed", "authenticatedProvisioningIncomplete"].contains(state))) else { return false }
        _ = now
        _ = sessionDeadline // PollLoop owns deadline terminalization on resume.
        return failedPromptRevision != currentPromptRevision ||
            failedPromptResponseGeneration != currentPromptResponseGeneration ||
            promptSubmissionInProgress || pollFailureIsTransient || reconciliationWasSuperseded ||
            authenticationActive
    }
}

public struct V3ShortcutRefreshRequest: Equatable {
    public let requestID: String
    public let origin: String

    public init?(userInfo: [AnyHashable: Any]?) {
        guard let userInfo,
              let value = userInfo["requestID"] as? String,
              let uuid = UUID(uuidString: value), uuid.uuidString == value,
              let origin = userInfo["origin"] as? String,
              V3RefreshRunCorrelation.allowedManualOrigins.contains(origin) else { return nil }
        self.requestID = uuid.uuidString
        self.origin = origin
    }

    public static func make() -> V3ShortcutRefreshRequest {
        V3ShortcutRefreshRequest(requestID: UUID().uuidString, origin: "manualUnknown")
    }

    private init(requestID: String, origin: String) {
        self.requestID = requestID
        self.origin = origin
    }

    public var userInfo: [AnyHashable: Any] {
        ["requestID": requestID, "origin": origin]
    }
}

public struct V3RefreshRunCorrelation: Equatable {
    public static let allowedManualOrigins: Set<String> = [
        "home", "refreshManager", "setupAssistant", "deadlineAlarm", "vpnReturn", "manualUnknown"
    ]

    public let runID: String
    public let requestID: String?
    public let origin: String

    public static func make(source: String, manual: Bool, requestID: String?,
                            manualOrigin: String?, runID: UUID) -> V3RefreshRunCorrelation {
        guard manual else {
            return V3RefreshRunCorrelation(runID: runID.uuidString, requestID: nil, origin: source)
        }
        let canonicalRequest: String
        if let requestID, let parsed = UUID(uuidString: requestID) {
            canonicalRequest = parsed.uuidString
        } else {
            canonicalRequest = UUID().uuidString
        }
        let canonicalOrigin: String
        if let manualOrigin, allowedManualOrigins.contains(manualOrigin) {
            canonicalOrigin = manualOrigin
        } else if source == "alarm_action" {
            canonicalOrigin = "deadlineAlarm"
        } else if source == "vpn_return" {
            canonicalOrigin = "vpnReturn"
        } else {
            canonicalOrigin = "manualUnknown"
        }
        return V3RefreshRunCorrelation(runID: runID.uuidString, requestID: canonicalRequest,
                                       origin: canonicalOrigin)
    }

    private init(runID: String, requestID: String?, origin: String) {
        self.runID = runID
        self.requestID = requestID
        self.origin = origin
    }
}

enum V3RefreshIntentStartPolicy {
    static func create<T>(_ factory: () throws -> T,
                          continuation: CheckedContinuation<Void, Error>,
                          classify: (Error) -> Error = { $0 }) -> T? {
        do {
            return try factory()
        } catch {
            continuation.resume(throwing: classify(error))
            return nil
        }
    }
}

enum V3ServiceReadinessRetryPolicy {
    static func retryable(operation: String, stage: CombinedFailure.Stage,
                          code: CombinedFailure.Code, typedNotReady: Bool) -> Bool? {
        guard typedNotReady, operation == "snapshot", stage == .serviceReadiness,
              code == .notReady else { return nil }
        return true
    }
}

enum V3PairingImportFailurePolicy {
    static func shouldOfferFileRetry(operation: String, stage: String, safeCause: String?) -> Bool {
        operation == "pairingImportData" &&
            ((stage == "pairing" && safeCause == "invalidPairingFile") ||
             (stage == "filePreparation" && safeCause == "pairingFilePreparationFailed"))
    }
}

enum V3SetupTestAttemptPolicy {
    static func mayApply(capturedAttemptID: String, currentAttemptID: String?,
                         taskCancelled: Bool) -> Bool {
        !taskCancelled && currentAttemptID == capturedAttemptID
    }
}

enum V3SetupTestRequestDisposition: Equatable {
    case startNew
    case resumeExisting(String)
    case waitForActiveRun
}

enum V3SetupTestRequestPolicy {
    static let startGracePeriod: TimeInterval = 30

    static func select(pendingRequestID: String?, pendingAge: TimeInterval,
                       pendingState: String?, activeRunID: String?,
                       activeRunRequestID: String?) -> V3SetupTestRequestDisposition {
        // A terminal correlated request is read-only to consume. Resolve it
        // before considering a different run that began after it completed.
        if let pendingRequestID, ["completed", "failed"].contains(pendingState ?? "") {
            return .resumeExisting(pendingRequestID)
        }
        if let pendingRequestID, let activeRunID, !activeRunID.isEmpty,
           activeRunRequestID != pendingRequestID {
            return .waitForActiveRun
        }
        if let pendingRequestID {
            if pendingState != nil {
                return .resumeExisting(pendingRequestID)
            }
            if let activeRunID, !activeRunID.isEmpty {
                return activeRunRequestID == pendingRequestID
                    ? .resumeExisting(pendingRequestID) : .waitForActiveRun
            }
            return pendingAge < startGracePeriod
                ? .resumeExisting(pendingRequestID) : .startNew
        }
        return (activeRunID?.isEmpty == false) ? .waitForActiveRun : .startNew
    }
}

struct V3AuthPollFailure: Error {
    let underlying: Error
    let sessionID: String
    let promptResponseGeneration: UInt64
    let promptRevision: Int
}

enum V3AuthAttemptFailureCommitPolicy {
    static func mayCommit(requestedSessionID: String, currentSessionID: String?,
                          capturedPromptResponseGeneration: UInt64,
                          currentPromptResponseGeneration: UInt64,
                          reconciliationGenerationBefore: UInt64,
                          currentReconciliationGeneration: UInt64,
                          cancellationInProgress: Bool, taskCancelled: Bool) -> Bool {
        !cancellationInProgress && !taskCancelled &&
            currentSessionID == requestedSessionID &&
            currentPromptResponseGeneration == capturedPromptResponseGeneration &&
            currentReconciliationGeneration == (reconciliationGenerationBefore &+ 1)
    }

    static func shouldPreserveAuthoritativeAccountState(snapshotConfirmed: Bool,
                                                        authenticated: Bool,
                                                        state: String) -> Bool {
        snapshotConfirmed && authenticated &&
            ["completed", "authenticatedProvisioningIncomplete"].contains(state)
    }

    static func shouldCommitConfirmedSignedOutFailure(snapshotConfirmed: Bool,
                                                       authenticated: Bool,
                                                       hasSession: Bool,
                                                       cancellationConfirmed: Bool,
                                                       state: String) -> Bool {
        snapshotConfirmed && !authenticated && !hasSession && cancellationConfirmed && state == "failed"
    }
}

enum V3AuthCancellationRetryPolicy {
    static func canRetry(isCancelling: Bool, cancellationConfirmed: Bool,
                         hasSession: Bool) -> Bool {
        !isCancelling && !cancellationConfirmed && hasSession
    }
}

enum V3AuthUnknownResultRecoveryAction: Equatable {
    case cancelSession
    case reloadStatus
    case none
}

enum V3AuthUnknownResultRecoveryPolicy {
    static func action(isCancelling: Bool, cancellationConfirmed: Bool,
                       hasSession: Bool) -> V3AuthUnknownResultRecoveryAction {
        guard !isCancelling else { return .none }
        if !hasSession { return .reloadStatus }
        return cancellationConfirmed ? .none : .cancelSession
    }
}

enum V3AuthUnknownResultReconciliationPolicy {
    static func reportedState(originalState: String, hasSession: Bool,
                              authenticated: Bool) -> String {
        originalState == "resultUnknown" && !hasSession && !authenticated
            ? "working" : originalState
    }
}

enum V3AuthSessionAdmissionPolicy {
    static func mayStartNewSession(hasActiveSession: Bool) -> Bool {
        !hasActiveSession
    }
}

struct V3AuthProvisioningRecoveryPresentation: Equatable {
    let showCancellationInstruction: Bool
    let showRetryProvisioning: Bool
    let showReauthenticateProvisioning: Bool
    let showFinishLater: Bool
    let blockedByActiveSession: Bool
}

enum V3AuthProvisioningRecoveryPolicy {
    static func resolve(state: String, hasSession: Bool, signedIn: Bool,
                        provisioningRetryAvailable: Bool, isCancelling: Bool,
                        cancellationConfirmed: Bool,
                        authenticationActive: Bool = false,
                        reauthenticationAvailable: Bool = false,
                        identityStateBlocked: Bool = false) -> V3AuthProvisioningRecoveryPresentation {
        let noSessionResumeIsSafe = state == "resultUnknown" && !hasSession && signedIn &&
            provisioningRetryAvailable && !authenticationActive
        let retryAllowed = !identityStateBlocked && !isCancelling && cancellationConfirmed && provisioningRetryAvailable &&
            !authenticationActive &&
            (state != "resultUnknown" || noSessionResumeIsSafe)
        return V3AuthProvisioningRecoveryPresentation(
            showCancellationInstruction: state == "resultUnknown" && hasSession,
            showRetryProvisioning: retryAllowed,
            showReauthenticateProvisioning: !identityStateBlocked && signedIn && !hasSession &&
                reauthenticationAvailable && !authenticationActive &&
                !isCancelling && cancellationConfirmed &&
                !["working", "awaitingPrompt"].contains(state),
            showFinishLater: signedIn && (!hasSession || state != "resultUnknown"),
            blockedByActiveSession: authenticationActive)
    }
}

enum V3AuthCancellationFeedbackPolicy {
    static func statusLabel(isCancelling: Bool, normalLabel: String) -> String {
        isCancelling ? "Cancelling..." : normalLabel
    }

    static func message(isCancelling: Bool) -> String? {
        isCancelling ? "Cancellation requested. Waiting for SideStore to confirm the sign-in stopped." : nil
    }
}

enum V3AuthStatusTextPolicy {
    static func label(state: String, isSignedIn: Bool,
                      provisioningFinishedLater: Bool) -> String {
        switch state {
        case "completed": return "Signed in"
        case "authenticatedProvisioningIncomplete":
            return "Signed in, provisioning needs attention"
        case "awaitingPrompt": return "Needs your input"
        case "failed": return "Failed"
        case "cancelled": return "Cancelled"
        case "timedOut": return "Timed out"
        case "promptExpired": return "Verification expired"
        case "resultUnknown": return "Result not confirmed"
        case "working": return isSignedIn ? "Finishing provisioning..." : "Working..."
        default: return "Not started"
        }
    }

    static func accountLabel(state: String, isSignedIn: Bool) -> String {
        if state == "resultUnknown" {
            return isSignedIn
                ? "Last confirmed account status: signed in"
                : "Current account status is unconfirmed"
        }
        guard isSignedIn else { return "" }
        if state == "completed" || state == "authenticatedProvisioningIncomplete" {
            return "Signed in successfully"
        }
        return "Account currently signed in"
    }
}

enum V3AuthFailureDiagnosticsPolicy {
    static func provisioning(reply: [String: Any], message: String, technical: String) -> (message: String, technical: String) {
        var evidence = (reply["failure"] as? [String: Any]) ?? ["stage": "provisioning", "code": "failed"]
        if let kind = reply["failureKind"] as? String { evidence["kind"] = kind }
        let canonical = "diagnostic_code=\(diagnosticCode(for: evidence)) builder_commit=\(V3DiagnosticBuild.commit)"
        // Preserve existing safe technical evidence, explicitly naming its
        // structured category separately from the presentation category.
        let underlying = technical.replacingOccurrences(of: "diagnostic_code=", with: "underlying_diagnostic_code=")
            .replacingOccurrences(of: "builder_commit=", with: "underlying_builder_commit=")
        return (display(message, failure: evidence), canonical + (underlying.isEmpty ? "" : "\n" + underlying))
    }

    static func display(_ message: String, failure: [String: Any]) -> String {
        // Replace our previous decoration only. Never inspect prose to infer a
        // cause; the canonical ID comes solely from the finite envelope fields.
        let prose = message.components(separatedBy: "\n").compactMap { line -> String? in
            let prefix = "Error ID: "
            guard line.hasPrefix(prefix + "SS-") else { return line }
            // Older call sites may append recovery prose after the ID token.
            // Remove only the decoration token, never the recovery instructions.
            let trailing = line.dropFirst(prefix.count).drop(while: { !$0.isWhitespace })
                .trimmingCharacters(in: .whitespaces)
            return trailing.isEmpty ? nil : trailing
        }.joined(separator: "\n")
        let fields = (failure["signingContext"] as? [String: String]).flatMap(CombinedFailure.validatedSigningContext) ?? [:]
        let trace = fields[V3TemporaryAnisetteTrace.contextKey].flatMap(V3TemporaryAnisetteTrace.init(encoded:))
        let failedStep = trace?.failedStep.map { "\nDEBUG TEMPORARY failed step: " + $0 } ?? ""
        let cleanProse = prose.components(separatedBy: "\n").filter {
            !$0.hasPrefix("DEBUG TEMPORARY failed step: ")
        }.joined(separator: "\n")
        return cleanProse + failedStep + "\nError ID: " + diagnosticCode(for: failure)
    }

    static func diagnosticCode(for failure: [String: Any]) -> String {
        let stage = (failure["stage"] as? String).flatMap(CombinedFailure.Stage.init(rawValue:)) ?? .authentication
        let code = (failure["code"] as? String).flatMap(CombinedFailure.Code.init(rawValue:)) ?? .failed
        let step = (failure["sourceStep"] as? String).flatMap(CombinedFailure.SourceStep.init(rawValue:))
        let cause = (failure["safeCause"] as? String).flatMap(CombinedFailure.SafeCause.init(rawValue:))
        let fields = (failure["signingContext"] as? [String: String]).flatMap(CombinedFailure.validatedSigningContext) ?? [:]
        let failureCode = CombinedFailure(operation: "signIn", stage: stage, code: code,
            id: "00000000-0000-0000-0000-000000000000", safeCause: cause, sourceStep: step,
            signingContext: fields).diagnosticCode
        let kind = failure["kind"] as? String ?? failure["code"] as? String ?? "unknown"
        let kindToken: String
        switch kind {
        case "unknown": kindToken = "A00"
        case "invalidCredentials": kindToken = "A01"
        case "appSpecificPasswordRequired": kindToken = "A02"
        case "invalidCode": kindToken = "A03"
        case "rateLimited": kindToken = "A04"
        case "serviceUnavailable": kindToken = "A05"
        case "anisetteFailure", "anisette": kindToken = "A06"
        case "networkFailure", "network": kindToken = "A07"
        case "accountRepairRequired": kindToken = "A08"
        case "credentialStorage": kindToken = "A09"
        case "credentialStorageUncertain": kindToken = "A10"
        case "accountIdentityMismatch": kindToken = "A11"
        case "anisetteIdentityStateInvalid": kindToken = "A12"
        case "remoteIdentityInvalidRecord": kindToken = "A13"
        case "remoteIdentityStorageUnverified": kindToken = "A14"
        case "remoteIdentityStateChanged": kindToken = "A15"
        case "remoteIdentityManualSignInRequired": kindToken = "A16"
        default: kindToken = "A00"
        }
        return failureCode + "-" + kindToken
    }
    static func shouldShowTerminalDetails(state: String, hasPrompt: Bool,
                                          hasFailure: Bool) -> Bool {
        hasFailure && !hasPrompt && ["failed", "timedOut", "promptExpired", "resultUnknown", "cancelled"]
            .contains(state)
    }

    static func render(_ failure: [String: Any], underlyingCode: Int?,
                       retryableValue: Bool?) -> String {
        let kind = failure["kind"] as? String ?? ""
        let stage = failure["stage"] as? String ?? ""
        let code = failure["code"] as? String ?? ""
        let correlation = failure["correlationID"] as? String ?? ""
        let underlyingDomain = failure["underlyingDomain"] as? String ?? ""
        let codeText = underlyingCode.map(String.init) ?? "unknown"
        let retryableText = retryableValue.map { $0 ? "yes" : "no" } ?? "unknown"
        let step = (failure["sourceStep"] as? String).flatMap(CombinedFailure.SourceStep.init(rawValue:))?.rawValue ?? "unknown"
        let fields = (failure["signingContext"] as? [String: String]).flatMap(CombinedFailure.validatedSigningContext) ?? [:]
        let accountDetails = " source_step=\(step) typed_error=\(fields["typed_error"] ?? "unknown") server_code=\(fields["server_code"] ?? "unknown") http_status=\(fields["http_status"] ?? "unavailable")"
        let authResponseDetails = (fields["auth_response_shape"].map { " auth_response_shape=\($0)" } ?? "") +
            (fields["auth_response_mime"].map { " auth_response_mime=\($0)" } ?? "")
        let nativeDetails = fields["typed_error"] == "anisetteKitADIError"
            ? " native_code=\(fields["native_code"] ?? "unknown") native_phase=\(fields["native_phase"] ?? "unknown") native_subcode=\(fields["native_subcode"] ?? "unknown")" : ""
        let initializerDetails = ["native_init_kind", "native_init_reason", "native_init_engine",
            "native_init_library", "native_init_initializer"].compactMap { key in
                fields[key].map { " \(key)=\($0)" }
            }.joined()
        let attemptDetails = fields["anisette_blob_state"].map {
            " anisette_blob_state=\($0) anisette_recovery=\(fields["anisette_recovery"] ?? "notAttempted")"
        } ?? ""
        let probeDetails = fields["probe_native_code"].map {
            " probe_native_code=\($0) probe_native_phase=\(fields["probe_native_phase"] ?? "unknown") probe_native_subcode=\(fields["probe_native_subcode"] ?? "unknown")"
        } ?? ""
        return "diagnostic_code=\(diagnosticCode(for: failure)) builder_commit=\(V3DiagnosticBuild.commit) kind=\(kind) stage=\(stage) code=\(code) correlation=\(correlation) underlying=\(underlyingDomain)/\(codeText) retryable=\(retryableText)" + accountDetails + authResponseDetails + nativeDetails + initializerDetails + attemptDetails + probeDetails +
            (fields[V3ProvisioningCauseDiagnostic.contextKey].flatMap(V3ProvisioningCauseDiagnostic.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3ConstructorFaultDiagnostic.contextKey].flatMap(V3ConstructorFaultDiagnostic.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3TemporaryAnisetteTrace.contextKey].flatMap(V3TemporaryAnisetteTrace.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3TemporaryADIConsumption.contextKey].flatMap(V3TemporaryADIConsumption.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3LoginDiagnosticSnapshot.contextKey].flatMap(V3LoginDiagnosticSnapshot.init(encoded:))?.technicalDetails ?? "") + V3AuthenticationDiagnostics.technicalDetails(fields)
    }
}

enum V3SignInFailureRoutingPolicy {
    static func shouldOpenSignIn(stage: CombinedFailure.Stage,
                                 safeCause: CombinedFailure.SafeCause?) -> Bool {
        stage == .authentication && safeCause != .keychainSignOutFailed
    }
}

enum V3AuthTerminalFailureAction: Equatable {
    case beginNewSignIn(title: String)
    case repairAppleAccount
    case useAppSpecificPassword
    case blocked
}

enum V3AuthTerminalFailureActionPolicy {
    static func resolve(kind: String?, retryable: Bool?) -> V3AuthTerminalFailureAction {
        switch kind {
        case "credentialStorage", "credentialStorageUncertain", "anisetteIdentityStateInvalid": return .blocked
        case "remoteIdentityInvalidRecord", "remoteIdentityStorageUnverified": return .blocked
        case "remoteIdentityStateChanged", "remoteIdentityManualSignInRequired": return .beginNewSignIn(title: "Start New Sign-In")
        case "accountIdentityMismatch": return .beginNewSignIn(title: "Use Saved Apple ID")
        case "accountRepairRequired": return .repairAppleAccount
        case "appSpecificPasswordRequired": return .useAppSpecificPassword
        default: break
        }
        if retryable == false { return .blocked }
        switch kind {
        case "rateLimited": return .beginNewSignIn(title: "Start New Sign-In")
        case "invalidCredentials": return .beginNewSignIn(title: "Check Password and Start New Sign-In")
        case "invalidCode": return .beginNewSignIn(title: "Start New Sign-In to Enter a New Code")
        case "serviceUnavailable", "anisette", "anisetteFailure", "network", "networkFailure":
            return .beginNewSignIn(title: "Start New Sign-In")
        default: break
        }
        if retryable == nil || kind == "unknown" { return .beginNewSignIn(title: "Start New Sign-In") }
        return .beginNewSignIn(title: "Try Sign-In Again")
    }

    static func guidance(kind: String?, retryable: Bool?) -> String? {
        if let recovery = V3AccountOperationError.remoteIdentityRecovery(kind) { return recovery }
        if kind == "anisetteIdentityStateInvalid" { return LCAnisettePairError.recovery }
        if kind == "accountIdentityMismatch" {
            return "Reload status, then sign in with the saved Apple ID to finish setup."
        }
        switch resolve(kind: kind, retryable: retryable) {
        case .repairAppleAccount:
            return "Resolve the account issue shown by Apple, then begin a new sign-in."
        case .useAppSpecificPassword:
            return "Create an app-specific password for this authentication path, then enter it in the password prompt."
        case .blocked:
            return "This failure is not marked safe to retry. Resolve the displayed prerequisite and review Diagnostics."
        case .beginNewSignIn(_) where kind == "rateLimited":
            return "Apple is limiting sign-in attempts. Wait before starting a new sign-in."
        case .beginNewSignIn(_) where kind == "invalidCode":
            return "This sign-in attempt ended. Start a new sign-in; Apple will request a fresh verification code after credentials are accepted."
        case .beginNewSignIn(_) where kind == "serviceUnavailable":
            return "Apple's authentication service is temporarily unavailable. Wait for it to recover, then start a new sign-in."
        case .beginNewSignIn(_) where kind == "anisette" || kind == "anisetteFailure":
            return "SideStore could not obtain Anisette data. Check Anisette Servers in Settings, then start a new sign-in."
        case .beginNewSignIn(_) where kind == "network" || kind == "networkFailure":
            return "The connection to Apple's authentication service failed. Check your internet connection, then start a new sign-in."
        case .beginNewSignIn(_) where kind == "unknown" || (kind == nil && retryable == nil):
            return "The exact cause or retry safety could not be confirmed. Starting again creates a new attempt and may not resolve the previous failure."
        case .beginNewSignIn(_):
            return nil
        }
    }
}

enum V3AuthRepairURLPolicy {
    static let safeMessage = "Apple needs account attention before sign-in can continue."

    static func promptField(url: String) -> [String: String] {
        ["key": "url", "label": "Open Apple Account Repair",
         "secure": "false", "value": url]
    }

    static func openableURL(_ rawValue: String) -> URL? {
        guard rawValue.count <= 2_048,
              let components = URLComponents(string: rawValue),
              components.scheme?.lowercased() == "https",
              let host = components.host?.lowercased(),
              host == "apple.com" || host.hasSuffix(".apple.com"),
              components.port == nil || components.port == 443,
              components.user == nil, components.password == nil,
              let url = components.url else { return nil }
        return url
    }
}

struct V3AuthAttemptFailureNotice: Equatable {
    private(set) var message = ""
    private(set) var technicalDetails = ""

    mutating func record(snapshotConfirmed: Bool, authenticated: Bool,
                         failureMessage: String, technicalDetails: String) {
        guard !failureMessage.isEmpty else { return }
        if authenticated {
            message = "The sign-in attempt could not be confirmed. SideStore currently reports an account as signed in. \(failureMessage)"
        } else if snapshotConfirmed {
            message = "The sign-in attempt could not be confirmed. SideStore confirms no account is currently signed in. \(failureMessage)"
        } else {
            message = "The sign-in attempt could not be confirmed. SideStore could not confirm whether sign-in completed. \(failureMessage)"
        }
        self.technicalDetails = technicalDetails
    }

    mutating func clear() {
        message = ""
        technicalDetails = ""
    }
}

enum V3AuthAttemptStartFailurePolicy {
    static func confirmedNotDispatched(_ failure: CombinedFailure,
                                       operation: String = "authBegin") -> CombinedFailure {
        let underlying: NSError? = failure.underlyingDomain == "none" && failure.underlyingCode == 0
            ? nil : NSError(domain: failure.underlyingDomain, code: failure.underlyingCode)
        let cause: CombinedFailure.SafeCause
        if failure.safeCause == .responseCapacityUnavailable {
            cause = .authResponseCapacityUnavailable
        } else if failure.safeCause == .operationInProgress {
            cause = .operationInProgress
        } else {
            cause = operation == "authRetryProvisioning"
                ? .authProvisioningRetryNotDispatched : .authAttemptNotDispatched
        }
        return CombinedFailure(operation: "signIn", stage: failure.stage, code: failure.code,
            id: failure.correlationID, underlying: underlying,
            retryable: true, safeCause: cause)
    }

    static func isConfirmedNotDispatched(_ failure: CombinedFailure) -> Bool {
        failure.safeCause == .authAttemptNotDispatched ||
            failure.safeCause == .authProvisioningRetryNotDispatched ||
            failure.safeCause == .authResponseCapacityUnavailable ||
            failure.safeCause == .operationInProgress
    }
}

enum V3AuthProvisioningRetryDispatchPolicy {
    static func isConfirmedNotDispatched(_ failure: CombinedFailure) -> Bool {
        failure.safeCause == .authProvisioningRetryNotDispatched ||
            failure.safeCause == .authResponseCapacityUnavailable ||
            failure.safeCause == .operationInProgress
    }

    static func whatHappened(_ failure: CombinedFailure) -> String {
        if failure.safeCause == .authResponseCapacityUnavailable {
            return "SideStore could not start the provisioning retry because it could not reserve a safe response slot." + "\nError ID: SS-AUTH-D082"
        }
        if failure.safeCause == .operationInProgress {
            return "Another sign-in or provisioning attempt is already active."
        }
        return failure.safeMessage
    }
}

enum V3AuthSessionExpiryPolicy {
    static func response(authenticated: Bool, resumable: Bool = false) -> [String: Any] {
        if authenticated {
            return ["state": "authenticatedProvisioningIncomplete", "authenticated": true,
                    "resumable": resumable,
                    "message": "Apple ID sign-in succeeded, but provisioning did not finish before the session timed out." + "\nError ID: SS-AUTH-D083"]
        }
        return ["state": "timedOut", "authenticated": false,
                "message": "Sign-in timed out. Start a new sign-in when you are ready." + "\nError ID: SS-AUTH-D040"]
    }
}

// A backup callback is a one-shot capability for one external SideBackup step.
// The session owns the device mutation throughout the round trip; this control
// message must never create, release, or reconcile an operation owner.
struct V3BackupCallbackIdentity: Equatable, Sendable {
    let session: String
    let nonce: String
    let action: String

    init?(session: String, nonce: String, action: String) {
        guard UUID(uuidString: session)?.uuidString == session,
              UUID(uuidString: nonce)?.uuidString == nonce,
              ["backup", "restore"].contains(action) else { return nil }
        self.session = session; self.nonce = nonce; self.action = action
    }

    init?(_ raw: Any?) {
        guard let values = raw as? [String: String],
              Set(values.keys) == Set(["session", "nonce", "action"]),
              let session = values["session"], let nonce = values["nonce"],
              let action = values["action"] else { return nil }
        self.init(session: session, nonce: nonce, action: action)
    }

    var wire: [String: String] { ["session": session, "nonce": nonce, "action": action] }
    var queryItems: [URLQueryItem] {
        [URLQueryItem(name: "v3Session", value: session),
         URLQueryItem(name: "v3Nonce", value: nonce),
         URLQueryItem(name: "v3Action", value: action)]
    }

    static func supports(kind: String, action: String) -> Bool {
        switch (kind, action) {
        case ("backup", "backup"), ("deactivate", "backup"),
             ("restore", "restore"), ("activate", "restore"): return true
        default: return false
        }
    }
}

struct V3BackupCallbackResult: Equatable, Sendable {
    let identity: V3BackupCallbackIdentity
    let succeeded: Bool

    init?(session: String, payload: [String: Any]) {
        guard Set(payload.keys) == Set(["nonce", "action", "result"]),
              let nonce = payload["nonce"] as? String,
              let action = payload["action"] as? String,
              let result = payload["result"] as? String,
              ["success", "failure"].contains(result),
              let identity = V3BackupCallbackIdentity(session: session, nonce: nonce, action: action)
        else { return nil }
        self.identity = identity; self.succeeded = result == "success"
    }

    // URLs come from outside the process. Reject ambiguous and unbound input;
    // external descriptions, error domains and codes never enter XPC or logs.
    init?(url: URL, expectedTargetBundleID: String) {
        guard url.absoluteString.utf8.count <= 8192,
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme?.lowercased() == "sidestore",
              components.host?.lowercased() == "appbackupresponse",
              components.user == nil, components.password == nil, components.port == nil,
              components.fragment == nil,
              ["/success", "/failure"].contains(components.path.lowercased()) else { return nil }
        let items = components.queryItems ?? []
        let allowed: Set<String> = ["targetBundleID", "v3Session", "v3Nonce", "v3Action",
                                    "errorDomain", "errorCode", "errorDescription"]
        guard items.count <= allowed.count, Set(items.map(\.name)).count == items.count,
              items.allSatisfy({ allowed.contains($0.name) && $0.value != nil }) else { return nil }
        let values = Dictionary(uniqueKeysWithValues: items.compactMap { item in
            item.value.map { (item.name, $0) }
        })
        guard !expectedTargetBundleID.isEmpty, values["targetBundleID"] == expectedTargetBundleID,
              let session = values["v3Session"], let nonce = values["v3Nonce"],
              let action = values["v3Action"] else { return nil }
        self.init(session: session, payload: ["nonce": nonce, "action": action,
            "result": components.path.lowercased() == "/success" ? "success" : "failure"])
    }

    var payload: [String: Any] {
        ["nonce": identity.nonce, "action": identity.action,
         "result": succeeded ? "success" : "failure"]
    }
}

enum V3ServiceMutationAdmissionPolicy {
    static func hasConflictingOperationMutation(operation: String, target: String,
                                                activeOperationID: String?,
                                                backupCallbackControl: Bool = false) -> Bool {
        guard let activeOperationID else { return false }
        return !(target == activeOperationID &&
            (["opPoll", "opAnswer", "opCancel"].contains(operation) ||
             (operation == "backupResult" && backupCallbackControl)))
    }

    static func admits(isMutation: Bool, anotherMutationActive: Bool,
                       authenticationActive: Bool, isAuthContinuation: Bool,
                       responseCapacityAvailable: Bool,
                       refreshActive: Bool = false,
                       isRefreshRelease: Bool = false) -> Bool {
        guard isMutation else { return true }
        guard !anotherMutationActive, responseCapacityAvailable else { return false }
        guard !refreshActive || isRefreshRelease else { return false }
        return !authenticationActive || isAuthContinuation
    }

    static func permitsAuthenticationControl(_ operation: String,
                                              ownsActiveSession: Bool,
                                              authenticationActive: Bool) -> Bool {
        if ["authBegin", "authRetryProvisioning"].contains(operation) {
            return V3AuthSessionAdmissionPolicy.mayStartNewSession(
                hasActiveSession: authenticationActive)
        }
        return ownsActiveSession && ["authRespond", "authCancel"].contains(operation)
    }

    static func ownsRefreshAdmissionControl(operation: String, target: String,
                                             activeRunID: String?, refreshAttemptActive: Bool,
                                             anotherHostMutationActive: Bool = false,
                                             userConfirmedReconciliation: Bool = false) -> Bool {
        if operation == "refreshAdmissionReconcile" {
            return userConfirmedReconciliation &&
                UUID(uuidString: target)?.uuidString == target
        }
        return ["refreshAdmissionBegin", "refreshAdmissionEnd"].contains(operation) &&
            refreshAttemptActive && !anotherHostMutationActive && !target.isEmpty && activeRunID == target
    }
}

enum V3ServiceMutationBusyCausePolicy {
    static func safeCause(operation: String, anotherMutationActive: Bool,
                          responseCapacityAvailable: Bool, refreshActive: Bool,
                          refreshRelease: Bool, authenticationActive: Bool,
                          isAuthContinuation: Bool) -> CombinedFailure.SafeCause {
        let ownershipConflict = anotherMutationActive || (refreshActive && !refreshRelease) ||
            (authenticationActive && !isAuthContinuation)
        if !ownershipConflict && !responseCapacityAvailable {
            return .responseCapacityUnavailable
        }
        if operation == "sourceRemoveConfirmed" { return .sourceRemoveBusy }
        return .operationInProgress
    }
}

struct V3RefreshAdmissionLease {
    static let nativeRefreshTimeout: TimeInterval = 600
    static let retirementGrace: TimeInterval = 60
    static let lifetime: TimeInterval = nativeRefreshTimeout + retirementGrace
    static let nativeRefreshTimeoutNanoseconds: UInt64 = 600_000_000_000

    private(set) var runID: String?
    private(set) var requestID: String?
    private(set) var expiresAt: Date?
    private(set) var ownerLost = false

    // A retained run still fences new mutations after its owner is lost.
    var isActive: Bool { runID != nil }
    // Snapshot activity must describe a live owner, not a durable recovery hold.
    // Otherwise a restarted host cannot accept the very snapshot needed to
    // present and explicitly reconcile an interrupted refresh.
    var hasLiveOwner: Bool { isActive && !ownerLost }

    mutating func expire(now: Date = Date()) -> Bool {
        guard let expiresAt, expiresAt <= now, !ownerLost else { return false }
        ownerLost = true
        self.expiresAt = nil
        return true
    }

    mutating func acquire(runID: String, requestID: String,
                          authenticationActive: Bool,
                          anotherMutationActive: Bool,
                          now: Date = Date()) -> Bool {
        _ = expire(now: now)
        guard let parsed = UUID(uuidString: runID), parsed.uuidString == runID,
              let parsedRequest = UUID(uuidString: requestID), parsedRequest.uuidString == requestID,
              self.runID == nil, !authenticationActive, !anotherMutationActive,
              Self.lifetime > 0 else { return false }
        self.runID = runID
        self.requestID = requestID
        expiresAt = now.addingTimeInterval(Self.lifetime)
        ownerLost = false
        return true
    }

    func owns(_ candidate: String) -> Bool { runID == candidate }

    mutating func restoreLost(runID: String) -> Bool {
        guard self.runID == nil,
              let parsed = UUID(uuidString: runID), parsed.uuidString == runID else { return false }
        self.runID = runID
        requestID = nil
        expiresAt = nil
        ownerLost = true
        return true
    }

    @discardableResult
    mutating func release(runID: String) -> Bool {
        guard self.runID == runID else { return false }
        self.runID = nil
        requestID = nil
        expiresAt = nil
        ownerLost = false
        return true
    }

    @discardableResult
    mutating func release(requestID: String) -> Bool {
        guard self.requestID == requestID else { return false }
        runID = nil
        self.requestID = nil
        expiresAt = nil
        ownerLost = false
        return true
    }

    @discardableResult
    mutating func reconcileAfterDeviceCheck(runID: String, userConfirmed: Bool) -> Bool {
        guard ownerLost, userConfirmed, owns(runID) else { return false }
        return release(runID: runID)
    }
}

enum V3KnownSourcePreflightPolicy {
    static let maximumAge: TimeInterval = 6 * 60 * 60

    static func shouldRefresh(hasCachedBlocklist: Bool, lastSuccessfulUpdate: Date?,
                              now: Date = Date(),
                              maximumAge: TimeInterval = V3KnownSourcePreflightPolicy.maximumAge) -> Bool {
        guard hasCachedBlocklist, let lastSuccessfulUpdate,
              lastSuccessfulUpdate <= now,
              maximumAge > 0 else { return true }
        return now.timeIntervalSince(lastSuccessfulUpdate) >= maximumAge
    }
}

enum V3OperationSessionCorrelationPolicy {
    static func requestSessionID(operation: String, target: String,
                                 payload: [String: Any]) -> String? {
        if operation == "opStart" { return payload["session"] as? String }
        if ["opPoll", "opAnswer", "opCancel", "backupResult"].contains(operation) {
            return target.isEmpty ? nil : target
        }
        return nil
    }

    static func matches(operation: String, target: String, requestedStartSession: String?,
                        resultSession: String?) -> Bool {
        guard ["opStart", "opPoll", "opAnswer", "opCancel", "backupResult"].contains(operation) else { return true }
        let expected = operation == "opStart" ? requestedStartSession : target
        guard let expected, !expected.isEmpty else { return false }
        return resultSession == expected
    }
}

struct V3ServiceRecoveryAdmissionDecision: Equatable {
    let recoveryControl: Bool
    let matchingPreparedStart: Bool
    let matchingPreparedReservation: Bool
    let blocksMutation: Bool
    let refreshRelease: Bool
}

enum V3ServiceRecoveryAdmissionPolicy {
    private static func strictBoolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    static func decide(operation: String, target: String, payload: [String: Any],
                       operationSessionID: String?, recovery: V3OperationRecoveryRecord?,
                       recoveryReadFailed: Bool, recoveryDiscardable: Bool = false,
                       refreshOwnerLost: Bool, backupCallbackControl: Bool = false) -> V3ServiceRecoveryAdmissionDecision {
        let refreshRecordMatches = recovery?.kind == "refreshAll" && recovery?.sessionID == target
        let refreshTerminalState = payload["state"] as? String
        let hasRefreshTerminal = ["completed", "failed", "notDispatched"].contains(refreshTerminalState ?? "")
        let userConfirmed = strictBoolean(payload["userConfirmed"]) == true
        let operationControl = recovery?.kind != "refreshAll" &&
            (((["opPoll", "opAnswer", "opCancel"].contains(operation) ||
               (operation == "backupResult" && backupCallbackControl)) &&
              operationSessionID == recovery?.sessionID) ||
             (operation == "opRecoveryReconcile" && target == recovery?.sessionID && userConfirmed))
        let refreshControl = refreshRecordMatches &&
            ((operation == "refreshAdmissionEnd" && hasRefreshTerminal) ||
             (operation == "refreshAdmissionReconcile" && userConfirmed))
        let unreadableRecoveryControl = operation == "recoveryDiscardUnreadable" &&
            recovery == nil && userConfirmed && (!recoveryReadFailed || recoveryDiscardable)
        let recoveryControl = operationControl || refreshControl || unreadableRecoveryControl
        let matchingPreparedStart = operation == "opStart" && recovery?.kind != "refreshAll" &&
            operationSessionID == recovery?.sessionID && payload["kind"] as? String == recovery?.kind &&
            recovery?.phase == .prepared
        let matchingPreparedReservation = operation == "opRecoveryPrepare" && recovery?.kind != "refreshAll" &&
            payload["session"] as? String == recovery?.sessionID && payload["kind"] as? String == recovery?.kind &&
            recovery?.phase == .prepared
        let blocksMutation = (recoveryReadFailed && !unreadableRecoveryControl) ||
            (recovery != nil && !recoveryControl && !matchingPreparedStart && !matchingPreparedReservation)
        let unreadableRefreshRelease = operation == "recoveryDiscardUnreadable" &&
            unreadableRecoveryControl && refreshOwnerLost
        let refreshRelease = unreadableRefreshRelease || (refreshRecordMatches &&
            ((operation == "refreshAdmissionEnd" && hasRefreshTerminal) ||
             (operation == "refreshAdmissionReconcile" && refreshOwnerLost && userConfirmed)))
        return V3ServiceRecoveryAdmissionDecision(recoveryControl: recoveryControl,
            matchingPreparedStart: matchingPreparedStart,
            matchingPreparedReservation: matchingPreparedReservation,
            blocksMutation: blocksMutation, refreshRelease: refreshRelease)
    }
}

enum V3OperationCancelKnownStartedPolicy {
    static func resolve(sessionID: String, hostReportedKnownStarted: Bool,
                        recovery: V3OperationRecoveryRecord?) -> Bool {
        guard let recovery, recovery.sessionID == sessionID,
              recovery.kind != "refreshAll" else { return hostReportedKnownStarted }
        return recovery.phase == .dispatched
    }
}

enum V3SharedKeychainAccessGroupPolicy {
    static func sharedGroup(in entitledGroups: [String]) -> String? {
        entitledGroups.first(where: { $0.hasSuffix(".com.kdt.livecontainer.shared") })
    }

    static func sharedGroup(fromDefaultGroup group: String) -> String? {
        guard let prefix = group.split(separator: ".", maxSplits: 1).first,
              String(prefix).range(of: #"^[A-Z0-9]{10}$"#, options: .regularExpression) != nil else {
            return nil
        }
        return "\(prefix).com.kdt.livecontainer.shared"
    }
}

// V3_CATALOG_OPERATION_CONTEXT_V1
// A catalog request must keep its operation context even when the failure
// happens before the backend catalog query runs. The truthful failing
// component is never rewritten: a connection failure stays operation=connect
// with its real stage and code, and the waiting request is recorded alongside
// it as host-rendered request context. This keeps service startup, XPC, busy,
// and invalid-response failures distinguishable instead of collapsing into
// "SideStore could not start or complete the requested action."
private enum V3AuthSessionUnavailableReplyPolicy {
    /// Only a current, correlated authPoll failure from SideStore proves that
    /// the exact target session no longer exists. Transport, malformed, or
    /// unrelated session replies cannot retire an auth status owner.
    static func confirmsUnavailable(operation: String, target: String,
                                    requestID: String,
                                    envelope: [String: Any]) -> Bool {
        guard operation == "authPoll",
              UUID(uuidString: target)?.uuidString == target,
              V3WireContract.strictInt(envelope["version"]) == 1,
              CombinedFailure.uuidCorrelationMatches(envelope["id"] as? String,
                  expectedID: requestID),
              V3WireContract.strictBool(envelope["ok"]) == false,
              let rawFailure = envelope["failure"] as? [String: Any],
              let failure = CombinedFailure.decode(rawFailure, expectedID: requestID) else {
            return false
        }
        return failure.operation == "signIn" && failure.stage == .authentication &&
            failure.code == .invalidResponse && failure.safeCause == .authSessionUnavailable
    }
}

enum V3CatalogRequestContext {
    /// The stage a host-side catalog boundary failure belongs to. A catalog read
    /// is reported against the catalog stage; every other operation keeps the
    /// generic command wire boundary.
    static func hostStage(for operation: String) -> CombinedFailure.Stage {
        operation == "catalog" ? .catalog : .command
    }

    /// A successfully received reply that the service could not encode, or
    /// that exceeded the shared byte limit, failed at the reply boundary.
    static func replyEncodingStage(for operation: String) -> CombinedFailure.Stage {
        _ = operation
        return .replyEncoding
    }

    /// Map a plain service error token to a typed host failure without inventing
    /// a cause. "notReady" is service startup, "busy" is service contention,
    /// and an oversized or unparseable reply is an invalid response.
    static func hostFailure(errorToken: String, operation: String, id: String) -> CombinedFailure {
        let stage = hostStage(for: operation)
        switch errorToken {
        case "notReady":
            return CombinedFailure(operation: operation, stage: .serviceReadiness, code: .notReady,
                                   id: id, retryable: true)
        case "busy":
            return CombinedFailure(operation: operation, stage: stage, code: .busy, id: id, retryable: true)
        case "responseTooLarge":
            // V3_RESPONSE_ENCODING_CLASSIFICATION_V1: correctly serialized, but
            // too large to transfer. Distinct from both an encoding failure and a
            // reply that could not be parsed.
            return CombinedFailure(operation: operation, stage: replyEncodingStage(for: operation),
                                  code: .invalidResponse, id: id,
                                  safeCause: .responseTooLarge)
        case "responseEncodingFailed":
            // V3_RESPONSE_ENCODING_CLASSIFICATION_V1: the service could not
            // serialize its reply at all. This is a distinct defect from an
            // oversized reply and is never reported as one.
            return CombinedFailure(operation: operation, stage: replyEncodingStage(for: operation),
                                  code: .invalidResponse, id: id,
                                  safeCause: .responseEncodingFailed)
        case "invalidRequest":
            return CombinedFailure(operation: operation, stage: .command, code: .invalidConfiguration, id: id)
        case "cancelled":
            return CombinedFailure(operation: operation, stage: stage, code: .cancelled, id: id)
        default:
            if let code = CombinedFailure.Code(rawValue: errorToken) {
                return CombinedFailure(operation: operation, stage: stage, code: code, id: id)
            }
            // No cause is invented for an unknown token. The source manifest is
            // explicitly not blamed, because nothing proved it failed to parse.
            return CombinedFailure(operation: operation, stage: stage, code: .failed, id: id)
        }
    }

    // V3_RESPONSE_CLASSIFICATION_CARRIER_V1
    // Classifies one service reply. This is the exact production path, kept pure
    // so a real service fallback envelope can be run through it.
    //
    // Precedence is deliberate and unchanged: the structured `failure` envelope
    // wins over the legacy string `error` token, because it carries the
    // operation, stage, correlation, retryability and safe cause that the token
    // cannot express. The token is consulted only when there is no decodable
    // envelope, which is the case for a foreign or older service. The
    // classification of a reply the service could not deliver therefore has to
    // travel inside the structured envelope, which is what
    // V3ResponseClassifier.safeCause(for:) is for.
    static func sanitizingAuthenticationDiagnostics(_ supplied: [String: Any], operation: String) -> [String: Any] {
        guard ["authBegin", "authRetryProvisioning", "authPoll", "authRespond", "authCancel"].contains(operation) else { return supplied }
        var result = supplied
        for key in ["failure", "previousFailure"] {
            guard var failure = result[key] as? [String: Any] else { continue }
            let fields: [String: String]
            if let raw = failure["signingContext"] {
                fields = V3AuthenticationDiagnostics.sanitizingWireContext(raw)
                    .flatMap(CombinedFailure.validatedSigningContext) ?? [V3AuthenticationDiagnostics.stateKey: "rejected"]
            } else { fields = [:] }
            failure["signingContext"] = fields; result[key] = failure
            if key == "failure" {
                var canonical = failure; canonical.removeValue(forKey: "kind")
                if let id = canonical["correlationID"] as? String, let decoded = CombinedFailure.decode(canonical, expectedID: id) {
                    result["technicalDetails"] = decoded.technicalDetails
                } else { result["technicalDetails"] = V3AuthenticationDiagnostics.technicalDetails(fields) }
            }
        }
        return result
    }

    // Host-only context from the submitted command, added only after both
    // envelope correlations match. Never attach payloads, targets or raw text.
    static func correlatedReplyFailure(_ failure: CombinedFailure,
                                       operation: String, id: String) -> CombinedFailure {
        guard V3WireContract.operations.contains(operation), UUID(uuidString: id) != nil,
              CombinedFailure.uuidCorrelationMatches(failure.correlationID, expectedID: id) else { return failure }
        var result = failure
        result.annotatingRequest(requestedOperation: operation, requestID: id)
        return result
    }

    static func classifyReply(_ response: Data, operation: String, id: String) throws -> [String: Any] {
        guard let decoded = try PropertyListSerialization.propertyList(from: response, format: nil) as? [String: Any] else {
            throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                                  code: .invalidResponse, id: id)
        }
        guard V3WireContract.strictInt(decoded["version"]) == 1 else {
            throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                                  code: .invalidResponse, id: id)
        }
        guard let responseID = decoded["id"] as? String,
              UUID(uuidString: responseID) != nil else {
            throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                                  code: .invalidResponse, id: id)
        }
        guard CombinedFailure.uuidCorrelationMatches(responseID, expectedID: id) else {
            // Genuine cross-request protocol evidence. It is never resolved to
            // the waiting caller, and it is never reported as a serialization
            // defect it did not prove.
            throw CombinedFailure(operation: operation, stage: .command, code: .staleResult, id: id)
        }
        if decoded["failure"] != nil {
            guard let envelope = decoded["failure"] as? [String: Any],
                  let failure = CombinedFailure.decode(envelope, expectedID: id) else {
                throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                    code: .invalidResponse, id: id, retryable: false)
            }
            throw correlatedReplyFailure(failure, operation: operation, id: id)
        }
        if let code = decoded["error"] as? String {
            throw correlatedReplyFailure(hostFailure(errorToken: code, operation: operation, id: id),
                operation: operation, id: id)
        }
        guard V3WireContract.strictBool(decoded["ok"]) == true,
              let result = decoded["result"] as? [String: Any] else {
            throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                                  code: .invalidResponse, id: id)
        }
        return sanitizingAuthenticationDiagnostics(result, operation: operation)
    }

    /// Attach the waiting request to a pre-dispatch connection failure. The
    /// connection failure's own operation, stage, code, retryability, safe
    /// cause, source step, and correlation are preserved exactly, because
    /// operation=connect is what proves no mutation ran.
    static func annotating(_ error: Error, requestedOperation: String, requestID: String) -> Error {
        guard var combined = error as? CombinedFailure else {
            return CombinedFailure(operation: requestedOperation, stage: .command, code: .failed,
                                   id: requestID, underlying: error)
        }
        guard combined.operation != requestedOperation else { return combined }
        combined.annotatingRequest(requestedOperation: requestedOperation, requestID: requestID)
        return combined
    }
}

// V3_HOST_COMMAND_BRIDGE_V1
@MainActor
public final class V3ServiceBridge {
    public static let shared = V3ServiceBridge()
    public static func strictBool(_ value: Any?) -> Bool? {
        V3WireContract.strictBool(value)
    }
    public static func strictInt(_ value: Any?) -> Int? {
        V3WireContract.strictInt(value)
    }
    public static var authSessionLifetime: TimeInterval {
        V3WireContract.authSessionLifetime
    }
    public static func authSnapshot(_ reply: [String: Any]) -> V3AuthServiceSnapshot? {
        V3WireContract.authSnapshot(reply)
    }
    private var pending: [String: CheckedContinuation<Data, Error>] = [:]
    private var pendingOperations: [String: String] = [:]
    private var timeouts: [String: Task<Void, Never>] = [:]
    private var cancellationRecovery: [String: Task<Void, Never>] = [:]
    private var activeOperationSessions: Set<String> = []
    private var uncertainOperationSessions: Set<String> = []
    private var knownOperationSessions: [String: Date] = [:]
    private var operationMonitors: [String: Task<Void, Never>] = [:]
    private let readTimeout: TimeInterval
    private let commandTimeout: TimeInterval
    private let cancellationGrace: TimeInterval
    private var activeMutation: String?
    private var authSessionOwnership = V3AuthSessionOwnership()
    private var promptSessionServiceIDs: [String: UUID] = [:]
    private var backupSessionServiceIDs: [String: UUID] = [:]
    private var backupCallbackBindings: [String: V3BackupCallbackIdentity] = [:]
    private var statusWriteAuthority = V3StatusWriteAuthority()
    private var hostRecoveryHoldActive = false
    private struct StatusLeaseWaiter {
        let id: String
        let ownerID: String
        let revision: UInt64
        let kind: V3StatusAuthorityLeaseKind
        let allowUnresolvedMutation: Bool
        let continuation: CheckedContinuation<V3StatusWriteTicket, Error>
    }
    private var statusLeaseWaiters: [StatusLeaseWaiter] = []
    private var statusLeaseWaiterOrder = V3StatusLeaseWaiterOrder()
    private var statusLeaseByRequestID: [String: V3StatusWriteTicket] = [:]
    private var statusReplyTicketByRequestID: [String: V3StatusWriteTicket] = [:]
    private var statusDispatchedRequestIDs: Set<String> = []
    public var isMutating: Bool {
        authSessionOwnership.hasActiveSession() || activeMutation != nil ||
        !activeOperationSessions.isEmpty || !cancellationRecovery.isEmpty ||
            statusWriteAuthority.hasActiveWrite || statusWriteAuthority.hasUnresolvedMutation ||
            hostRecoveryHoldActive || RefreshHandler.shared.v3RefreshToken != nil
    }

    private func anotherHostMutationActiveForRefreshControl(operation: String, target: String) -> Bool {
        let ownsRefreshRun = ["refreshAdmissionBegin", "refreshAdmissionEnd"].contains(operation) &&
            RefreshHandler.shared.v3RefreshToken != nil &&
            RefreshHandler.shared.v3RefreshAdmissionRunID == target
        let matchingStatusLease = statusWriteAuthority.activeLease?.ownerID == "refresh:\(target)"
        return authSessionOwnership.hasActiveSession() || activeMutation != nil ||
            !activeOperationSessions.isEmpty || !cancellationRecovery.isEmpty ||
            statusWriteAuthority.hasUnresolvedMutation || hostRecoveryHoldActive ||
            (statusWriteAuthority.hasActiveWrite && !matchingStatusLease) ||
            (RefreshHandler.shared.v3RefreshToken != nil && !ownsRefreshRun)
    }

    private var currentStatusServiceInstanceID: String {
        String(RefreshHandler.shared.sideStorePid)
    }

    public func setHostRecoveryHold(_ active: Bool) {
        hostRecoveryHoldActive = active
    }

    private func acquireStatusLease(ownerID: String,
                                    kind: V3StatusAuthorityLeaseKind,
                                    allowUnresolvedMutation: Bool = false) async throws -> V3StatusWriteTicket {
        try Task.checkCancellation()
        if kind == .mutation && statusWriteAuthority.hasUnresolvedMutation && !allowUnresolvedMutation {
            throw CombinedFailure(operation: "command", stage: .command, code: .busy,
                id: ownerID, retryable: false, safeCause: .operationInProgress)
        }
        let waiterID = UUID().uuidString
        let reservedRevision: UInt64
        if kind == .mutation {
            reservedRevision = statusWriteAuthority.reserveMutationRevision()
            NotificationCenter.default.post(name: Notification.Name("V3StatusMutationReserved"), object: nil)
        } else {
            reservedRevision = statusWriteAuthority.revision
        }
        return try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                if Task.isCancelled {
                    continuation.resume(throwing: CancellationError())
                } else if statusWriteAuthority.canBegin(kind: kind,
                            allowUnresolvedMutation: allowUnresolvedMutation) && statusLeaseWaiterOrder.count == 0,
                          let ticket = statusWriteAuthority.begin(ownerID: ownerID,
                            revision: reservedRevision,
                            serviceInstanceID: currentStatusServiceInstanceID, kind: kind,
                            allowUnresolvedMutation: allowUnresolvedMutation) {
                    continuation.resume(returning: ticket)
                } else {
                    statusLeaseWaiterOrder.enqueue(waiterID)
                    statusLeaseWaiters.append(StatusLeaseWaiter(id: waiterID,
                        ownerID: ownerID, revision: reservedRevision,
                        kind: kind, allowUnresolvedMutation: allowUnresolvedMutation,
                        continuation: continuation))
                }
            }
        }, onCancel: {
            Task { @MainActor [weak self] in self?.cancelStatusLeaseWaiter(waiterID) }
        })
    }

    private func cancelStatusLeaseWaiter(_ waiterID: String) {
        statusLeaseWaiterOrder.remove(waiterID)
        guard let index = statusLeaseWaiters.firstIndex(where: { $0.id == waiterID }) else { return }
        let waiter = statusLeaseWaiters.remove(at: index)
        waiter.continuation.resume(throwing: CancellationError())
    }

    private func drainStatusLeaseWaiters() {
        guard statusWriteAuthority.activeLease == nil else { return }
        while let waiterID = statusLeaseWaiterOrder.takeNext() {
            guard let index = statusLeaseWaiters.firstIndex(where: { $0.id == waiterID }) else { continue }
            let waiter = statusLeaseWaiters.remove(at: index)
            if waiter.kind == .mutation && statusWriteAuthority.hasUnresolvedMutation &&
               !waiter.allowUnresolvedMutation {
                waiter.continuation.resume(throwing: CombinedFailure(operation: "command",
                    stage: .command, code: .busy, id: waiter.id,
                    retryable: false, safeCause: .operationInProgress))
                continue
            }
            guard let ticket = statusWriteAuthority.begin(ownerID: waiter.ownerID,
                revision: waiter.revision,
                serviceInstanceID: currentStatusServiceInstanceID, kind: waiter.kind,
                allowUnresolvedMutation: waiter.allowUnresolvedMutation) else {
                waiter.continuation.resume(throwing: CombinedFailure(operation: "command",
                    stage: .command, code: .interrupted, id: waiter.id, retryable: true))
                continue
            }
            waiter.continuation.resume(returning: ticket)
            return
        }
    }

    private func completeStatusLease(_ ticket: V3StatusWriteTicket,
                                     outcome: V3StatusWriteOutcome,
                                     replyRequestID: String? = nil) {
        guard statusWriteAuthority.complete(ticket, outcome: outcome) else { return }
        if outcome != .outcomeUnknown || ticket.kind == .snapshot {
            for requestID in Array(statusLeaseByRequestID.keys) where
                statusLeaseByRequestID[requestID]?.ownerID == ticket.ownerID {
                statusLeaseByRequestID.removeValue(forKey: requestID)
            }
        }
        if let replyRequestID { statusReplyTicketByRequestID[replyRequestID] = ticket }
        drainStatusLeaseWaiters()
    }

    private func observeConnectedStatusService(ownerID: String?) -> V3StatusWriteTicket? {
        guard let ticket = statusWriteAuthority.observeServiceInstance(
            currentStatusServiceInstanceID, continuingOwnerID: ownerID) else { return nil }
        for requestID in Array(statusLeaseByRequestID.keys) where
            statusLeaseByRequestID[requestID]?.ownerID == ticket.ownerID {
            statusLeaseByRequestID[requestID] = ticket
        }
        return ticket
    }

    private func resolveUnknownStatusOwner(_ ownerID: String) {
        let resolved = statusWriteAuthority.resolveOwnerAfterReconciliation(ownerID)
        for requestID in Array(statusLeaseByRequestID.keys) where
            statusLeaseByRequestID[requestID]?.ownerID == ownerID {
            statusLeaseByRequestID.removeValue(forKey: requestID)
        }
        if resolved {
            NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
        }
    }

    /// Authoritative auth-session reconciliation may settle this exact active
    /// lease or its retired unresolved form. It never releases another owner.
    private func reconcileAuthStatusOwner(sessionID: String) {
        reconcileStatusOwnerAfterAuthoritativeEvidence("auth:\(sessionID)")
    }

    /// Reconciliation releases only the exact session owner reported by the
    /// authoritative evidence. Active and retired unresolved leases share the
    /// same owner authority, while unrelated operation, refresh, and request
    /// owners remain fenced.
    private func reconcileStatusOwnerAfterAuthoritativeEvidence(_ ownerID: String) {
        let resolved = statusWriteAuthority.resolveOwnerAfterAuthoritativeReconciliation(ownerID)
        for requestID in Array(statusLeaseByRequestID.keys) where
            statusLeaseByRequestID[requestID]?.ownerID == ownerID {
            statusLeaseByRequestID.removeValue(forKey: requestID)
        }
        if resolved {
            drainStatusLeaseWaiters()
            NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
        }
    }

    private func statusResponse(_ data: Data, requestID: String) -> [String: Any]? {
        guard data.count <= V3WireContract.responseLimit,
              let envelope = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              V3WireContract.strictInt(envelope["version"]) == 1,
              envelope["id"] as? String == requestID else { return nil }
        return envelope
    }

    private func observeStatusLeaseResponse(requestID: String, operation: String,
                                            target: String, payload: [String: Any]?,
                                            data: Data) {
        let ticket = statusLeaseByRequestID[requestID]
        guard let envelope = statusResponse(data, requestID: requestID) else {
            if let ticket,
               ticket.kind == .snapshot || ticket.ownerID == "request:\(requestID)" {
                completeStatusLease(ticket, outcome: .outcomeUnknown)
            } else if operation == "directRecoveryReconcile",
                      let ticket, let active = statusWriteAuthority.activeLease, active == ticket {
                // A malformed control reply cannot create a second unknown
                // owner; the exact target recovery record remains authoritative.
                completeStatusLease(ticket, outcome: .failed)
            }
            return
        }
        let result = envelope["result"] as? [String: Any] ?? [:]
        let confirmedNotDispatched = V3WireContract.strictBool(envelope["operationNotDispatched"]) == true
        if V3AuthSessionUnavailableReplyPolicy.confirmsUnavailable(
            operation: operation, target: target, requestID: requestID, envelope: envelope) {
            confirmAuthSessionUnavailable(sessionID: target)
            return
        }
        if operation == "directRecoveryReconcile",
           V3WireContract.strictBool(envelope["ok"]) != true {
            if let ticket, let active = statusWriteAuthority.activeLease, active == ticket {
                completeStatusLease(active, outcome: .failed)
            }
            return
        }
        if ["directRecoveryInspect", "directRecoveryReconcile"].contains(operation),
           (UUID(uuidString: target)?.uuidString != target || result["requestID"] as? String != target) {
            if operation == "directRecoveryReconcile", let ticket,
               let active = statusWriteAuthority.activeLease, active == ticket {
                completeStatusLease(active, outcome: .failed)
            }
            return
        }
        let requestedStartSession = operation == "opStart" ? payload?["session"] as? String : nil
        if !confirmedNotDispatched && !V3OperationSessionCorrelationPolicy.matches(operation: operation, target: target,
            requestedStartSession: requestedStartSession, resultSession: result["session"] as? String) { return }
        if !confirmedNotDispatched && ["authBegin", "authRetryProvisioning", "authPoll", "authRespond", "authCancel"].contains(operation),
           let expectedSession = operationSessionID(operation: operation, target: target, payload: payload),
           result["session"] as? String != expectedSession { return }
        let candidateOwner = ticket?.ownerID ??
            V3StatusAuthorityOperationPolicy.controlOwnerID(
            operation: operation, sessionID: operationSessionID(operation: operation,
                target: target, payload: payload))
        guard let ownerID = ticket?.ownerID ?? candidateOwner else { return }
        guard let active = statusWriteAuthority.activeLease else {
            let outcome: V3StatusWriteOutcome?
            if ownerID == "request:\(requestID)" {
                outcome = confirmedNotDispatched ? .notDispatched :
                    (V3WireContract.strictBool(envelope["ok"]) == true ? .committed : .outcomeUnknown)
            } else {
                outcome = V3StatusAuthorityOperationPolicy.terminalOutcome(
                    operation: operation, result: envelope)
            }
            if let outcome, outcome != .outcomeUnknown { resolveUnknownStatusOwner(ownerID) }
            return
        }
        guard active.ownerID == ownerID else {
            let outcome: V3StatusWriteOutcome?
            if ownerID == "request:\(requestID)" {
                outcome = confirmedNotDispatched ? .notDispatched :
                    (V3WireContract.strictBool(envelope["ok"]) == true ? .committed : .outcomeUnknown)
            } else {
                outcome = V3StatusAuthorityOperationPolicy.terminalOutcome(
                    operation: operation, result: envelope)
            }
            if let outcome, outcome != .outcomeUnknown {
                resolveUnknownStatusOwner(ownerID)
            }
            return
        }

        let outcome: V3StatusWriteOutcome?
        if active.kind == .snapshot {
            if confirmedNotDispatched { outcome = .notDispatched }
            else { outcome = V3WireContract.strictBool(envelope["ok"]) == true ? .committed : .failed }
        } else if active.ownerID == "request:\(requestID)" {
            if confirmedNotDispatched { outcome = .notDispatched }
            else { outcome = V3WireContract.strictBool(envelope["ok"]) == true ? .committed : .outcomeUnknown }
        } else if let ticket, ticket.ownerID == active.ownerID {
            if confirmedNotDispatched { outcome = .notDispatched }
            else { outcome = V3StatusAuthorityOperationPolicy.terminalOutcome(
                operation: operation, result: envelope) }
        } else if confirmedNotDispatched {
            return
        } else {
            outcome = V3StatusAuthorityOperationPolicy.terminalOutcome(
                operation: operation, result: envelope)
        }
        guard let outcome else { return }
        let replyCanReturn = pending[requestID] != nil && outcome == .committed
        completeStatusLease(active, outcome: outcome,
            replyRequestID: replyCanReturn &&
                (active.kind == .snapshot || active.ownerID == "request:\(requestID)")
                ? requestID : nil)
        if operation == "directRecoveryReconcile",
           result["requestID"] as? String == target,
           V3WireContract.strictBool(result["reconciled"]) == true {
            resolveUnknownStatusOwner("request:\(target)")
            NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
        }
    }

    private func attachStatusReplyTicket(_ result: [String: Any], requestID: String) -> [String: Any] {
        guard let ticket = statusReplyTicketByRequestID.removeValue(forKey: requestID) else { return result }
        var tagged = result
        tagged["_v3StatusAuthorityTicket"] = ticket
        tagged["_v3StatusAuthorityRequestID"] = requestID
        return tagged
    }

    /// ACKs only an exact terminal direct request after its feature caller has
    /// accepted the successful result. The certCreate partial-remote outcome is
    /// deliberately left in recovery for a manual check.
    // One exact, service-bound acknowledgement, never an absent-journal guess.
    private var acknowledgedDirectRecovery: (requestID: String, operation: String,
        serviceEpoch: UInt64, serviceInstanceID: String)?

    public func hasAcknowledgedDirectRecovery(requestID: String, operation: String) -> Bool {
        guard let proof = acknowledgedDirectRecovery else { return false }
        return proof.requestID == requestID && proof.operation == operation &&
            proof.serviceEpoch == statusWriteAuthority.serviceEpoch &&
            proof.serviceInstanceID == currentStatusServiceInstanceID
    }

    public func acknowledgeDirectRecoveryAfterSuccess(_ result: [String: Any],
                                                       operation: String) async -> Bool {
        guard V3DirectRecoveryHostPolicy.mayAcknowledgeSuccessfulResponse(
                operation: operation, result: result),
              let requestID = result["_v3StatusAuthorityRequestID"] as? String,
              UUID(uuidString: requestID)?.uuidString == requestID else { return false }
        // Close host admission while the durable terminal slot is being
        // acknowledged. A current quiescent snapshot reopens it after proof.
        setHostRecoveryHold(true)
        let acknowledgedServiceEpoch = statusWriteAuthority.serviceEpoch
        let acknowledgedServiceInstanceID = currentStatusServiceInstanceID
        do {
            let ack = try await request(operation: "directRecoveryReconcile", target: requestID,
                payload: ["ackTerminal": true])
            guard !Task.isCancelled,
                  ack["requestID"] as? String == requestID,
                  V3WireContract.strictBool(ack["reconciled"]) == true,
                  acknowledgedServiceEpoch == statusWriteAuthority.serviceEpoch,
                  acknowledgedServiceInstanceID == currentStatusServiceInstanceID else {
                NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
                return false
            }
            acknowledgedDirectRecovery = (requestID, operation,
                acknowledgedServiceEpoch, acknowledgedServiceInstanceID)
            NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
            return true
        } catch {
            // Preserve the original successful result in the caller. The durable
            // recovery record remains visible on the next authoritative snapshot.
            NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
            return false
        }
    }


    public func statusReplyMayApply(_ reply: [String: Any]) -> Bool {
        guard let ticket = reply["_v3StatusAuthorityTicket"] as? V3StatusWriteTicket else { return false }
        let busyValue: Bool?
        if ticket.kind == .snapshot {
            guard let typedBusy = V3WireContract.strictBool(reply["busy"]),
                  V3WireContract.strictBool(reply["activeMutation"]) == false else { return false }
            // These ownership facts are emitted on every current service
            // snapshot. Missing or malformed fields cannot authorize a commit.
            guard V3WireContract.strictBool(reply["activeMutation"]) != nil,
                  V3WireContract.strictBool(reply["recoveryHold"]) != nil else { return false }
            let recoveryOnly = V3RecoveryOnlySnapshotPolicy.mayApplyFullStatus(
                busy: typedBusy,
                activeMutation: V3WireContract.strictBool(reply["activeMutation"]) == true,
                recoveryHold: V3WireContract.strictBool(reply["recoveryHold"]) == true,
                hasTypedRecoveryEvidence: reply["operationRecovery"] != nil ||
                    reply["directRecovery"] != nil || reply["refreshRecovery"] != nil ||
                    reply["recoveryStorageFailure"] != nil)
            busyValue = typedBusy && !recoveryOnly
        } else {
            busyValue = false
        }
        return V3StatusReplyCommitPolicy.mayApply(ticket, authority: statusWriteAuthority,
            currentServiceEpoch: statusWriteAuthority.serviceEpoch,
            currentServiceInstanceID: currentStatusServiceInstanceID,
            busySnapshot: busyValue == true)
    }

    public func statusReplyMayApplyRecoveryEvidence(_ reply: [String: Any]) -> Bool {
        guard let ticket = reply["_v3StatusAuthorityTicket"] as? V3StatusWriteTicket,
              ticket.kind == .snapshot,
              let busy = V3WireContract.strictBool(reply["busy"]), busy else { return false }
        let hasActiveMutationField = reply.keys.contains("activeMutation")
        let activeMutation = V3WireContract.strictBool(reply["activeMutation"])
        guard hasActiveMutationField, activeMutation == false,
              V3WireContract.strictBool(reply["recoveryHold"]) == true,
              V3StatusRecoveryEvidencePolicy.mayApply(
                busySnapshot: busy, activeMutation: activeMutation,
                hasDurableRecoveryEvidence: V3StatusRecoveryEvidencePolicy.hasRecoveryEvidence(reply)) else {
            return false
        }
        return V3StatusReplyCommitPolicy.mayApply(ticket, authority: statusWriteAuthority,
            currentServiceEpoch: statusWriteAuthority.serviceEpoch,
            currentServiceInstanceID: currentStatusServiceInstanceID)
    }

    public func hasUncertainOperationSession(_ sessionID: String) -> Bool {
        uncertainOperationSessions.contains(sessionID)
    }
    /// Clear only a host owner for a session SideStore explicitly reports as
    /// unavailable. Transport loss and malformed replies retain ownership.
    public func confirmAuthSessionUnavailable(sessionID: String) {
        guard UUID(uuidString: sessionID)?.uuidString == sessionID else { return }
        authSessionOwnership.clear(sessionID: sessionID)
        promptSessionServiceIDs.removeValue(forKey: sessionID)
        reconcileAuthStatusOwner(sessionID: sessionID)
    }
    /// A validated service snapshot can retire a host owner when it proves
    /// there is no active authentication task, even if the terminal poll was lost.
    public func reconcileAuthSessionOwnership(sessionID: String, authenticationActive: Bool) {
        authSessionOwnership.reconcile(sessionID: sessionID, authenticationActive: authenticationActive)
        guard !authenticationActive,
              UUID(uuidString: sessionID)?.uuidString == sessionID else { return }
        reconcileAuthStatusOwner(sessionID: sessionID)
    }
    public var processID: Int32 { RefreshHandler.shared.sideStorePid }
    public var startupDiagnosticText: String { RefreshHandler.shared.startupDiagnostics.text }
    public var serviceReadyForOperationLogs: Bool { RefreshHandler.shared.v3ServiceIdentity != nil }

    init(readTimeout: TimeInterval = 30, commandTimeout: TimeInterval = 600, cancellationGrace: TimeInterval = 3) {
        self.readTimeout = readTimeout
        self.commandTimeout = commandTimeout
        self.cancellationGrace = cancellationGrace
    }

    public func connect() async throws {
        try await RefreshHandler.shared.ensureServiceConnected()
    }

    /// Retire a session whose native result is unknown only after the user
    /// confirms that the device operation has stopped. Process retirement alone
    /// never declares the mutation successful.
    @discardableResult
    public func confirmUncertainOperationAfterDeviceCheck(sessionID: String) -> Bool {
        guard uncertainOperationSessions.contains(sessionID) else { return false }
        activeOperationSessions.remove(sessionID)
        uncertainOperationSessions.remove(sessionID)
        operationMonitors.removeValue(forKey: sessionID)?.cancel()
        knownOperationSessions.removeValue(forKey: sessionID)
        backupCallbackBindings.removeValue(forKey: sessionID)
        backupSessionServiceIDs.removeValue(forKey: sessionID)
        RefreshHandler.shared.v3_stopService()
        disconnected()
        reconcileStatusOwnerAfterAuthoritativeEvidence("operation:\(sessionID)")
        return true
    }

    /// Retire the service after the explicit recovery RPC has cleared the exact
    /// durable session. This never runs on process restart or a timeout.
    public func retireReconciledOperationService(sessionID: String) {
        activeOperationSessions.remove(sessionID)
        uncertainOperationSessions.remove(sessionID)
        operationMonitors.removeValue(forKey: sessionID)?.cancel()
        knownOperationSessions.removeValue(forKey: sessionID)
        backupCallbackBindings.removeValue(forKey: sessionID)
        backupSessionServiceIDs.removeValue(forKey: sessionID)
        RefreshHandler.shared.v3_stopService()
        disconnected()
        reconcileStatusOwnerAfterAuthoritativeEvidence("operation:\(sessionID)")
    }

    public func retireReconciledRefreshService(runID: String) {
        guard UUID(uuidString: runID)?.uuidString == runID else { return }
        RefreshHandler.shared.v3_stopService()
        disconnected()
        reconcileStatusOwnerAfterAuthoritativeEvidence("refresh:\(runID)")
    }

    public func forgetSettledOperationSession(_ sessionID: String) {
        guard !activeOperationSessions.contains(sessionID),
              !uncertainOperationSessions.contains(sessionID) else { return }
        knownOperationSessions.removeValue(forKey: sessionID)
        backupCallbackBindings.removeValue(forKey: sessionID)
        backupSessionServiceIDs.removeValue(forKey: sessionID)
    }

    private func operationSessionID(operation: String, target: String,
                                    payload: [String: Any]?) -> String? {
        if operation == "opStart" { return payload?["session"] as? String }
        if ["opPoll", "opAnswer", "opCancel", "backupResult"].contains(operation) { return target }
        if ["authBegin", "authRetryProvisioning"].contains(operation) {
            return payload?["session"] as? String ?? (target.isEmpty ? nil : target)
        }
        if ["authPoll", "authRespond", "authCancel",
            "opRecoveryReconcile", "directRecoveryInspect", "directRecoveryReconcile",
            "refreshAdmissionBegin", "refreshAdmissionEnd", "refreshAdmissionReconcile"].contains(operation) {
            return target
        }
        return nil
    }

    public func submitBackupCallback(_ url: URL) async throws {
        guard let result = V3BackupCallbackResult(url: url,
                  expectedTargetBundleID: Bundle.main.bundleIdentifier ?? "") else { return }
        let session = result.identity.session
        guard activeOperationSessions.contains(session),
              let serviceID = backupSessionServiceIDs[session],
              serviceID == RefreshHandler.shared.v3ServiceIdentity else { return }
        // The external app may return before the next routine poll. Read the
        // authoritative pending capability, never infer it from the incoming URL.
        let state = try await request(operation: "opPoll", target: session)
        guard serviceID == backupSessionServiceIDs[session],
              serviceID == RefreshHandler.shared.v3ServiceIdentity,
              activeOperationSessions.contains(session),
              V3BackupCallbackIdentity(state["backupCallback"]) == result.identity else { return }
        backupCallbackBindings[session] = result.identity
        defer {
            if backupCallbackBindings[session] == result.identity {
                backupCallbackBindings.removeValue(forKey: session)
            }
        }
        _ = try await request(operation: "backupResult", target: session, payload: result.payload)
    }

    public func request(operation: String, target: String = "", cursor: Int? = nil,
                        payload: [String: Any]? = nil, requestDeadline: Date? = nil) async throws -> [String: Any] {
        try Task.checkCancellation()
        if ["authCancel", "opCancel"].contains(operation) {
            promptSessionServiceIDs.removeValue(forKey: target)
        }
        let deliversPromptAnswer = ["authRespond", "opAnswer"].contains(operation)
        let answerServiceID = deliversPromptAnswer ? promptSessionServiceIDs[target] : nil
        if deliversPromptAnswer {
            guard let answerServiceID,
                  RefreshHandler.shared.v3ServiceIdentity == answerServiceID else {
                throw CombinedFailure(operation: operation, stage: .xpcConnection,
                    code: .staleResult, id: UUID().uuidString, retryable: false)
            }
        }
        if ["authBegin", "authRetryProvisioning", "authReconcileStorage", "signOut", "accountImport"].contains(operation) {
            NotificationCenter.default.post(name: Notification.Name("V3AuthIdentityTransition"), object: nil)
        }
        defer {
            // Local storage reconciliation is one bounded identity mutation.
            // Balance invalidation even when admission, connection or repair fails.
            if operation == "authReconcileStorage" {
                NotificationCenter.default.post(name: Notification.Name("V3AuthIdentityTransitionFinished"), object: nil)
            }
        }
        // V3_CATALOG_OPERATION_CONTEXT_V1: the request correlation is minted
        // before connecting, so a failure that happens before the service
        // receives the request can still be attributed to the caller's actual
        // operation instead of only to the connection attempt.
        let id = UUID().uuidString
        let operationSessionID = operationSessionID(operation: operation, target: target, payload: payload)
        let backupCallback = operation == "backupResult"
            ? V3BackupCallbackResult(session: target, payload: payload ?? [:]) : nil
        let scopedBackupCallback = backupCallback.map {
            activeOperationSessions.contains(target) && backupCallbackBindings[target] == $0.identity &&
                backupSessionServiceIDs[target] != nil &&
                backupSessionServiceIDs[target] == RefreshHandler.shared.v3ServiceIdentity
        } ?? false
        let backupServiceID = scopedBackupCallback ? backupSessionServiceIDs[target] : nil
        if operation == "backupResult", !scopedBackupCallback {
            throw CombinedFailure(operation: operation, stage: .command,
                code: .staleResult, id: id, retryable: false)
        }
        let scopedSessionControl = scopedBackupCallback ||
            (["opAnswer", "opCancel"].contains(operation) && activeOperationSessions.contains(target))
        let explicitRecoveryConfirmation = operation == "opRecoveryReconcile" &&
            V3WireContract.strictBool(payload?["userConfirmed"]) == true &&
            UUID(uuidString: target)?.uuidString == target
        let directRecoveryTerminalAck = V3WireContract.strictBool(payload?["ackTerminal"]) == true
        let directRecoveryUserCheck = V3WireContract.strictBool(payload?["userConfirmed"]) == true
        let explicitDirectRecoveryControl = operation == "directRecoveryReconcile" &&
            UUID(uuidString: target)?.uuidString == target &&
            directRecoveryTerminalAck != directRecoveryUserCheck
        let explicitUnreadableRecoveryControl = V3RecoveryClearHostAdmissionPolicy.permits(
            operation: operation, target: target,
            userConfirmed: V3WireContract.strictBool(payload?["userConfirmed"]) == true,
            recoveryHold: hostRecoveryHoldActive,
            otherMutationActive: authSessionOwnership.hasActiveSession() || activeMutation != nil ||
                !activeOperationSessions.isEmpty || !cancellationRecovery.isEmpty ||
                statusWriteAuthority.hasActiveWrite || statusWriteAuthority.hasUnresolvedMutation ||
                RefreshHandler.shared.v3RefreshToken != nil)
        let scopedAuthSessionControl = ["authRespond", "authCancel"].contains(operation) &&
            authSessionOwnership.owns(target)
        let mutation = !V3WireContract.readOperations.contains(operation) ||
            ["opAnswer", "opCancel", "authCancel"].contains(operation)
        let scopedRefreshAdmissionControl = V3ServiceMutationAdmissionPolicy.ownsRefreshAdmissionControl(
            operation: operation, target: target,
            activeRunID: RefreshHandler.shared.v3RefreshAdmissionRunID,
            refreshAttemptActive: RefreshHandler.shared.v3RefreshToken != nil,
            anotherHostMutationActive: anotherHostMutationActiveForRefreshControl(
                operation: operation, target: target),
            userConfirmedReconciliation: V3WireContract.strictBool(payload?["userConfirmed"]) == true)
        if mutation {
            guard scopedSessionControl || explicitRecoveryConfirmation || explicitDirectRecoveryControl ||
                    explicitUnreadableRecoveryControl ||
                    scopedAuthSessionControl || scopedRefreshAdmissionControl ||
                    (!isMutating && RefreshHandler.shared.v3RefreshToken == nil) else {
                if ["authBegin", "authRetryProvisioning"].contains(operation) {
                    let failure = CombinedFailure(operation: "signIn", stage: .command,
                        code: .busy, id: id, retryable: true)
                    throw V3AuthAttemptStartFailurePolicy.confirmedNotDispatched(failure, operation: operation)
                }
                if operation == "sourceRemoveConfirmed" {
                    throw CombinedFailure(operation: "source", stage: .source, code: .busy,
                        id: id, retryable: true, safeCause: .sourceRemoveBusy)
                }
                if operation == "opStart" {
                    throw CombinedFailure(operation: operation, stage: .command, code: .busy,
                        id: id, retryable: true, safeCause: .operationInProgress)
                }
                if ["refreshAdmissionBegin", "refreshAdmissionEnd"].contains(operation) {
                    throw CombinedFailure(operation: "refresh", stage: .command, code: .busy,
                        id: id, retryable: true, safeCause: .operationInProgress)
                }
                throw CombinedFailure(operation: operation, stage: .command, code: .busy,
                                      id: id, retryable: true, safeCause: .operationInProgress)
            }
            if !scopedSessionControl && !explicitRecoveryConfirmation && !explicitDirectRecoveryControl &&
               !scopedAuthSessionControl { activeMutation = id }
        }
        defer { if activeMutation == id { activeMutation = nil } }
        var statusLeaseTicket: V3StatusWriteTicket?
        let directStatusOwner = explicitDirectRecoveryControl ? "recovery-control:\(target)" :
            V3StatusAuthorityOperationPolicy.directWriteOwnerID(operation: operation, requestID: id)
        let longStatusOwner = V3StatusAuthorityOperationPolicy.longOwnerID(
            operation: operation, sessionID: operationSessionID)
        let statusOwnerID: String?
        let statusLeaseKind: V3StatusAuthorityLeaseKind?
        if operation == "snapshot" {
            statusOwnerID = "snapshot:\(id)"
            statusLeaseKind = .snapshot
        } else if let directStatusOwner {
            statusOwnerID = directStatusOwner
            statusLeaseKind = .mutation
        } else if let longStatusOwner {
            statusOwnerID = longStatusOwner
            statusLeaseKind = .mutation
        } else {
            statusOwnerID = nil
            statusLeaseKind = nil
        }
        if let statusOwnerID, let statusLeaseKind {
            statusLeaseTicket = try await acquireStatusLease(ownerID: statusOwnerID, kind: statusLeaseKind,
                allowUnresolvedMutation: explicitDirectRecoveryControl)
            statusLeaseByRequestID[id] = statusLeaseTicket
        }
        defer {
            let wasDispatched = statusDispatchedRequestIDs.remove(id) != nil
            if !wasDispatched, let statusLeaseTicket {
                completeStatusLease(statusLeaseTicket, outcome: .notDispatched)
            }
        }
        do {
            // Reading diagnostics never launches/retries a failed service.
            // No await occurs on this branch before dispatch to the current peer.
            if operation == "logTail" {
                guard RefreshHandler.shared.v3ServiceIdentity != nil else {
                    throw CombinedFailure(operation: operation, stage: .serviceReadiness,
                        code: .notReady, id: id, retryable: false)
                }
            } else {
                try await connect()
            }
            if let connectedTicket = observeConnectedStatusService(ownerID: statusOwnerID ??
                V3StatusAuthorityOperationPolicy.controlOwnerID(
                    operation: operation, sessionID: operationSessionID)) {
                if statusLeaseTicket?.ownerID == connectedTicket.ownerID {
                    statusLeaseTicket = connectedTicket
                    statusLeaseByRequestID[id] = connectedTicket
                }
            }
        } catch {
            if ["authBegin", "authRetryProvisioning"].contains(operation) {
                NotificationCenter.default.post(name: Notification.Name("V3AuthIdentityTransitionFinished"), object: nil)
            }
            if error is CancellationError { throw CancellationError() }
            monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
            let annotated = V3CatalogRequestContext.annotating(error, requestedOperation: operation, requestID: id)
            if ["authBegin", "authRetryProvisioning"].contains(operation) {
                let failure = (annotated as? CombinedFailure) ?? CombinedFailure.capture(
                    annotated, operation: "signIn", stage: .xpcConnection, id: id)
                throw V3AuthAttemptStartFailurePolicy.confirmedNotDispatched(failure, operation: operation)
            }
            throw annotated
        }
        if scopedBackupCallback {
            guard backupServiceID == backupSessionServiceIDs[target],
                  backupServiceID == RefreshHandler.shared.v3ServiceIdentity,
                  activeOperationSessions.contains(target),
                  backupCallbackBindings[target] == backupCallback?.identity else {
                throw CombinedFailure(operation: operation, stage: .xpcConnection,
                    code: .staleResult, id: id, retryable: false)
            }
        }
        let isBoundedSessionCreation = ["authBegin", "authRetryProvisioning",
            "refreshAdmissionBegin", "refreshAdmissionEnd"].contains(operation)
        // Connecting may suspend or replace the service. An interactive answer
        // belongs only to the instance that created its session; never carry it
        // into the replacement, even when the old mutation owner is unresolved.
        try Task.checkCancellation()
        if deliversPromptAnswer {
            guard answerServiceID == RefreshHandler.shared.v3ServiceIdentity,
                  answerServiceID == promptSessionServiceIDs[target],
                  (operation == "authRespond" ? authSessionOwnership.owns(target) :
                    activeOperationSessions.contains(target)) else {
                throw CombinedFailure(operation: operation, stage: .xpcConnection,
                    code: .staleResult, id: id, retryable: false)
            }
        }
        let configuredTimeout = (V3WireContract.readOperations.contains(operation) || operation == "opCancel" ||
            isBoundedSessionCreation) ? readTimeout : commandTimeout
        let timeout = requestDeadline.map { min(configuredTimeout, max(0, $0.timeIntervalSinceNow)) }
            ?? configuredTimeout
        guard timeout > 0 else {
            throw CombinedFailure(operation: operation, stage: V3CatalogRequestContext.hostStage(for: operation),
                                  code: .timedOut, id: id, retryable: true)
        }
        var message: [String: Any] = ["version": 1, "id": id, "operation": operation,
                                      "target": target, "deadline": Date().addingTimeInterval(timeout)]
        if let cursor { message["cursor"] = cursor }
        var requestPayload = payload ?? [:]
        if ["authBegin", "authRetryProvisioning"].contains(operation) {
            if requestPayload["sessionDeadline"] as? Date == nil {
                requestPayload["sessionDeadline"] = Date().addingTimeInterval(V3WireContract.authSessionLifetime)
            }
        }
        if operation == "opCancel" {
            requestPayload["knownStarted"] = knownOperationSessions[target] != nil
        }
        if !requestPayload.isEmpty { message["payload"] = requestPayload }
        guard let data = V3WireContract.encodeRequest(message), data.count <= 16384 else {
            throw CombinedFailure(operation: operation, stage: .command, code: .invalidConfiguration, id: id)
        }
        let response: Data
        do {
            response = try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                if Task.isCancelled { continuation.resume(throwing: CancellationError()); return }
                pending[id] = continuation
                pendingOperations[id] = operation
                guard let client = RefreshHandler.shared.client else {
                    let failure = CombinedFailure(operation: operation, stage: .xpcConnection,
                        code: .interrupted, id: id, retryable: V3WireContract.readOperations.contains(operation))
                    let terminalFailure = ["authBegin", "authRetryProvisioning"].contains(operation)
                        ? V3AuthAttemptStartFailurePolicy.confirmedNotDispatched(failure, operation: operation)
                        : failure
                    settle(id, .failure(terminalFailure))
                    return
                }
                // Track ownership only once a valid request is about to cross
                // XPC. Local encoding, size, or pre-dispatch cancellation
                // failures must not leave a synthetic active session behind.
                if operation == "opStart", let session = operationSessionID {
                    activeOperationSessions.insert(session)
                    knownOperationSessions[session] = Date()
                    pruneKnownOperationSessions()
                    promptSessionServiceIDs[session] = RefreshHandler.shared.v3ServiceIdentity
                    backupSessionServiceIDs[session] = RefreshHandler.shared.v3ServiceIdentity
                }
                if ["authBegin", "authRetryProvisioning"].contains(operation),
                   let session = operationSessionID,
                   let sessionDeadline = requestPayload["sessionDeadline"] as? Date {
                    authSessionOwnership.register(sessionID: session, deadline: sessionDeadline)
                    promptSessionServiceIDs = promptSessionServiceIDs.filter {
                        activeOperationSessions.contains($0.key) || authSessionOwnership.owns($0.key)
                    }
                    promptSessionServiceIDs[session] = RefreshHandler.shared.v3ServiceIdentity
                }
                statusDispatchedRequestIDs.insert(id)
                client.v3Execute(data) { response in
                    Task { @MainActor in
                        self.observeStatusLeaseResponse(requestID: id, operation: operation,
                            target: target, payload: requestPayload, data: response)
                        if V3CancellationRecoveryReplyPolicy.mayCancelRetirement(
                            operation: operation, requestStillPending: self.pending[id] != nil) {
                            self.cancellationRecovery.removeValue(forKey: id)?.cancel()
                        }
                        guard response.count <= V3WireContract.responseLimit else {
                            // V3_RESPONSE_ENCODING_CLASSIFICATION_V1: a reply that
                            // arrived but exceeded the transport limit is its own
                            // defect. It was reported as a plain invalidResponse,
                            // which is the same shape as a reply that could not be
                            // parsed, so the two were indistinguishable. The stage
                            // follows the request so a catalog read is not reported
                            // as a generic command failure.
                            self.settle(id, .failure(CombinedFailure(operation: operation,
                                stage: V3CatalogRequestContext.replyEncodingStage(for: operation),
                                code: .invalidResponse, id: id, safeCause: .responseTooLarge))); return
                        }
                        self.settle(id, .success(response))
                    }
                }
                timeouts[id] = Task { @MainActor in
                    do { try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000)) } catch { return }
                    if self.pending[id] != nil {
                        let retireIfStuck = V3RequestRetirementPolicy
                            .shouldRetireServiceIfRequestStaysPending(operation)
                        self.monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
                        let (cancelTarget, cancelScope) = self.remoteCancellation(operation: operation,
                            operationSessionID: operationSessionID, requestID: id)
                        self.cancelRemote(cancelTarget, requestID: id, scope: cancelScope,
                                          mutation: mutation, retireIfStuck: retireIfStuck)
                        // V3_CATALOG_FAILURE_STAGE_V1: a read timeout is reported
                        // against the request's own operation and stage, so a
                        // catalog read never collapses into a generic command
                        // failure. A read is always safe to retry.
                        self.settle(id, .failure(CombinedFailure(operation: operation,
                            stage: V3CatalogRequestContext.hostStage(for: operation), code: .timedOut, id: id,
                            retryable: mutation ? nil : true)))
                        if !mutation && V3IdleReadRetirementPolicy.shouldRetireService(
                            operation: operation, hostMutationActive: self.isMutating,
                            refreshAttemptActive: RefreshHandler.shared.v3RefreshToken != nil) {
                            // An idle service that cannot answer a read needs a fresh process.
                            // Never retire it for a read while signing/install/refresh is active.
                            RefreshHandler.shared.v3_stopService()
                            self.disconnected()
                        }
                    }
                }
            }
            }, onCancel: {
            Task { @MainActor in
                guard self.pending[id] != nil else { return }
                let retireIfStuck = V3RequestRetirementPolicy
                    .shouldRetireServiceIfRequestStaysPending(operation)
                self.monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
                let (cancelTarget, cancelScope) = self.remoteCancellation(operation: operation,
                    operationSessionID: operationSessionID, requestID: id)
                self.cancelRemote(cancelTarget, requestID: id, scope: cancelScope,
                                  mutation: mutation, retireIfStuck: retireIfStuck)
                self.settle(id, .failure(CancellationError()))
            }
            })
        } catch {
            monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
            throw error
        }
        if deliversPromptAnswer {
            guard answerServiceID == promptSessionServiceIDs[target],
                  answerServiceID == RefreshHandler.shared.v3ServiceIdentity else {
                throw CombinedFailure(operation: operation, stage: .xpcConnection,
                    code: .staleResult, id: id, retryable: false)
            }
        }
        if scopedBackupCallback {
            guard backupServiceID == backupSessionServiceIDs[target],
                  backupServiceID == RefreshHandler.shared.v3ServiceIdentity else {
                throw CombinedFailure(operation: operation, stage: .xpcConnection,
                    code: .staleResult, id: id, retryable: false)
            }
        }
        // V3_RESPONSE_CLASSIFICATION_CARRIER_V1: the reply classification is a
        // pure function so the exact production path can be executed against a
        // real service fallback envelope, rather than only asserted in source
        // text. Precedence is unchanged: the structured envelope is authoritative
        // and the legacy token is only consulted when there is no decodable one.
        let result: [String: Any]
        do {
            result = try V3CatalogRequestContext.classifyReply(response, operation: operation, id: id)
        } catch {
            let authStartNotDispatched = ["authBegin", "authRetryProvisioning"].contains(operation) &&
                V3NotDispatchedReplyPolicy.confirms(response, requestID: id,
                    maximumBytes: V3WireContract.responseLimit)
            if operation == "opStart", serviceRejectedOperationStart(response, requestID: id),
               let sessionID = operationSessionID {
                activeOperationSessions.remove(sessionID)
                uncertainOperationSessions.remove(sessionID)
                knownOperationSessions.removeValue(forKey: sessionID)
                backupCallbackBindings.removeValue(forKey: sessionID)
                backupSessionServiceIDs.removeValue(forKey: sessionID)
                promptSessionServiceIDs.removeValue(forKey: sessionID)
                operationMonitors.removeValue(forKey: sessionID)?.cancel()
            } else if ["authBegin", "authRetryProvisioning"].contains(operation),
                      let sessionID = operationSessionID,
                      V3NotDispatchedReplyPolicy.confirms(response, requestID: id,
                          maximumBytes: V3WireContract.responseLimit) {
                authSessionOwnership.clear(sessionID: sessionID)
                promptSessionServiceIDs.removeValue(forKey: sessionID)
            } else {
                monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
            }
            if authStartNotDispatched {
                let failure = (error as? CombinedFailure) ?? CombinedFailure.capture(
                    error, operation: "signIn", stage: .authentication, id: id)
                throw V3AuthAttemptStartFailurePolicy.confirmedNotDispatched(failure, operation: operation)
            }
            throw error
        }
        let requestedStartSession = operation == "opStart" ? payload?["session"] as? String : nil
        guard V3OperationSessionCorrelationPolicy.matches(operation: operation, target: target,
            requestedStartSession: requestedStartSession, resultSession: result["session"] as? String) else {
            monitorOperationSessionIfNeeded(operation: operation, sessionID: operationSessionID)
            throw CombinedFailure(operation: operation, stage: .command, code: .staleResult,
                                  id: id, retryable: false)
        }
        updateOperationSessionOwnership(operation: operation, target: target,
                                        payload: payload, result: result)
        updateAuthSessionOwnership(operation: operation, sessionID: operationSessionID, result: result)
        if ["accountImport"].contains(operation) ||
           (["authBegin", "authRetryProvisioning", "authPoll"].contains(operation) &&
            (result["state"] as? String).map { !["working", "awaitingPrompt"].contains($0) } == true) {
            NotificationCenter.default.post(name: Notification.Name("V3AuthIdentityTransitionFinished"), object: nil)
        }
        return attachStatusReplyTicket(result, requestID: id)
    }

    public func disconnected() {
        backupCallbackBindings.removeAll()
        backupSessionServiceIDs.removeAll()
        promptSessionServiceIDs.removeAll()
        if let retired = statusWriteAuthority.retireService() {
            if retired.kind == .snapshot {
                for requestID in Array(statusLeaseByRequestID.keys) where
                    statusLeaseByRequestID[requestID]?.ownerID == retired.ownerID {
                    statusLeaseByRequestID.removeValue(forKey: requestID)
                }
            }
            for requestID in Array(statusReplyTicketByRequestID.keys) where
                statusReplyTicketByRequestID[requestID]?.ownerID == retired.ownerID {
                statusReplyTicketByRequestID.removeValue(forKey: requestID)
            }
        }
        drainStatusLeaseWaiters()
        for task in cancellationRecovery.values { task.cancel() }
        cancellationRecovery.removeAll()
        // Every caller first requests SideStore service retirement. Auth state
        // cannot outlive that process; clear host-only owners from lost starts.
        authSessionOwnership.clearAll()
        for task in operationMonitors.values { task.cancel() }
        operationMonitors.removeAll()
        // XPC loss does not prove that native InstallationProxy/device work
        // stopped. Preserve the mutation gate and require an authoritative
        // terminal reply or the explicit device-check reconciliation action.
        uncertainOperationSessions.formUnion(activeOperationSessions)
        for id in Array(pending.keys) {
            let requestedOperation = pendingOperations[id] ?? "command"
            let failure = CombinedFailure(operation: requestedOperation, stage: .xpcConnection,
                code: .interrupted, id: id)
            let contextualFailure = V3CatalogRequestContext.annotating(failure,
                requestedOperation: requestedOperation, requestID: id)
            settle(id, .failure(contextualFailure))
        }
    }

    private func cancelRemote(_ target: String, requestID: String, scope: String = "request",
                              mutation: Bool = false, retireIfStuck: Bool = true) {
        let cancellationID = UUID().uuidString
        let value: [String: Any] = ["version": 1, "id": cancellationID, "operation": "cancel",
                                    "target": target, "payload": ["scope": scope],
                                    "deadline": Date().addingTimeInterval(30)]
        if let data = try? PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0) {
            RefreshHandler.shared.client?.v3Execute(data) { response in
                Task { @MainActor in
                    guard V3RefreshAdmissionCancellationAckPolicy.accepts(response,
                        cancellationID: cancellationID) else { return }
                    // ACK confirms only the cancel request. The original
                    // request's correlated callback or explicit retirement
                    // owns status-lease completion and timer cancellation.
                }
            }
        }
        if mutation && retireIfStuck {
            // Keep the host mutation gate held until completion or process retirement.
            // A native callback that never returns cannot strand the product forever.
            // The recovery key is the request ID, while the remote cancellation
            // target may be an operation/auth session ID.
            cancellationRecovery[requestID] = Task { @MainActor in
                do { try await Task.sleep(nanoseconds: UInt64(cancellationGrace * 1_000_000_000)) } catch { return }
                guard cancellationRecovery[requestID] != nil else { return }
                RefreshHandler.shared.v3_stopService()
                disconnected()
            }
        }
    }

    private func settle(_ id: String, _ result: Result<Data, Error>) {
        timeouts.removeValue(forKey: id)?.cancel()
        pendingOperations.removeValue(forKey: id)
        pending.removeValue(forKey: id)?.resume(with: result)
    }

    private func updateOperationSessionOwnership(operation: String, target: String,
                                                 payload: [String: Any]?,
                                                 result: [String: Any]) {
        let sessionID = operation == "opStart" ? payload?["session"] as? String : target
        guard let sessionID,
              ["opStart", "opPoll", "opAnswer", "opCancel"].contains(operation) else { return }
        guard let state = result["state"] as? String,
              ["completed", "failed", "cancelled", "requiresSource", "waitingForAuthentication"].contains(state) else { return }
        let rawOutcomeUnknown = result["outcomeUnknown"]
        let parsedOutcomeUnknown = V3WireContract.strictBool(rawOutcomeUnknown)
        let outcomeUnknown = parsedOutcomeUnknown ?? (rawOutcomeUnknown != nil)
        let backendSettled = !outcomeUnknown &&
            V3WireContract.strictBool(result["backendSettled"]) == true
        if backendSettled {
            backupCallbackBindings.removeValue(forKey: sessionID)
            backupSessionServiceIDs.removeValue(forKey: sessionID)
            promptSessionServiceIDs.removeValue(forKey: sessionID)
            activeOperationSessions.remove(sessionID)
            uncertainOperationSessions.remove(sessionID)
            operationMonitors.removeValue(forKey: sessionID)?.cancel()
        } else {
            uncertainOperationSessions.insert(sessionID)
            monitorOperationSessionUntilSettled(sessionID)
        }
    }

    private func updateAuthSessionOwnership(operation: String, sessionID: String?,
                                            result: [String: Any]) {
        guard ["authBegin", "authRetryProvisioning", "authPoll", "authRespond", "authCancel"].contains(operation),
              let sessionID else { return }
        authSessionOwnership.observe(operation: operation, sessionID: sessionID,
                                     replySessionID: result["session"] as? String,
                                     state: result["state"] as? String)
        if !authSessionOwnership.owns(sessionID) {
            promptSessionServiceIDs.removeValue(forKey: sessionID)
        }
    }

    private func monitorOperationSessionIfNeeded(operation: String, sessionID: String?) {
        guard ["opStart", "opPoll", "opAnswer", "opCancel", "backupResult"].contains(operation),
              let sessionID, activeOperationSessions.contains(sessionID) else { return }
        uncertainOperationSessions.insert(sessionID)
        monitorOperationSessionUntilSettled(sessionID)
    }

    private func remoteCancellation(operation: String, operationSessionID: String?,
                                    requestID: String) -> (String, String) {
        if operation == "opStart", let operationSessionID { return (operationSessionID, "operation") }
        if operation == "opCancel", let operationSessionID { return (operationSessionID, "operation") }
        if ["authBegin", "authRetryProvisioning"].contains(operation), let operationSessionID,
           !operationSessionID.isEmpty {
            return (operationSessionID, "auth")
        }
        if operation == "authCancel", let operationSessionID { return (operationSessionID, "auth") }
        return (requestID, "request")
    }

    private func serviceRejectedOperationStart(_ data: Data, requestID: String) -> Bool {
        V3NotDispatchedReplyPolicy.confirms(data, requestID: requestID,
            maximumBytes: V3WireContract.responseLimit)
    }

    private func pruneKnownOperationSessions() {
        guard knownOperationSessions.count > 256 else { return }
        let settled = knownOperationSessions.filter {
            !activeOperationSessions.contains($0.key) && !uncertainOperationSessions.contains($0.key)
        }.sorted { $0.value < $1.value }
        for (id, _) in settled.prefix(max(0, knownOperationSessions.count - 256)) {
            knownOperationSessions.removeValue(forKey: id)
            backupCallbackBindings.removeValue(forKey: id)
            backupSessionServiceIDs.removeValue(forKey: id)
            promptSessionServiceIDs.removeValue(forKey: id)
        }
    }

    private func monitorOperationSessionUntilSettled(_ sessionID: String) {
        guard operationMonitors[sessionID] == nil else { return }
        operationMonitors[sessionID] = Task { @MainActor in
            let backoff: [UInt64] = [1, 2, 5, 10, 15]
            var index = 0
            while !Task.isCancelled && activeOperationSessions.contains(sessionID) {
                let seconds = backoff[min(index, backoff.count - 1)]
                index += 1
                do { try await Task.sleep(nanoseconds: seconds * 1_000_000_000) }
                catch { break }
                guard activeOperationSessions.contains(sessionID) else { break }
                do {
                    _ = try await request(operation: "opPoll", target: sessionID)
                } catch let failure as CombinedFailure where failure.code == .invalidConfiguration {
                    // A replacement service cannot find the old in-memory
                    // session. Stop polling but retain ownership because service
                    // loss does not prove that the device mutation stopped.
                    uncertainOperationSessions.insert(sessionID)
                    break
                } catch { }
            }
            operationMonitors[sessionID] = nil
        }
    }
}

