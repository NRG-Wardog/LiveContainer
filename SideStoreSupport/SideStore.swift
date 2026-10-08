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
        result["results"] = entries.map { entry -> [String: Any] in
            guard let identifier = entry["bundle_id"] as? String, expected.contains(identifier),
                  let success = strictBoolean(entry["success"]) else { return [:] }
            var item: [String: Any] = ["bundle_id": identifier, "success": success]
            for key in ["refreshed_date", "expiration_date"] { if let value = entry[key] as? Date { item[key] = value } }
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

        fileprivate var inferredRetryable: Bool? {
            switch self {
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
            case .recoveryMalformedRecord, .recoveryIncompatibleRecord:
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
        self.signingContext = Self.validatedSigningContext(signingContext) ?? [:]
        self.retryable = retryable ?? self.safeCause?.inferredRetryable
        let launchStages: Set<Stage> = [.extensionDiscovery, .extensionLaunch, .xpcConnection, .serviceReadiness]
        self.launchContext = normalized == "connect" && launchStages.contains(stage) ? launchContext : nil
    }
    private static let operations: Set<String> = ["connect", "status", "command", "recovery", "refresh", "install", "update", "signIn", "signOut", "catalog", "source", "sign", "activate", "deactivate", "delete", "remove", "backup", "restore", "jit", "pairingImportData", "anisetteList", "anisetteReset", "anisetteSync"]
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
    public static func validatedSigningContext(_ value: [String: String]) -> [String: String]? {
        var fields = V3TemporaryADIExecution.sanitizingContext(value)
        if !V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled {
            fields.removeValue(forKey: V3TemporaryAnisetteTrace.contextKey)
        }
        guard fields.count <= 20 else { return nil }
        for (key, text) in fields {
            if key == V3TemporaryADIExecution.contextKey {
                guard V3TemporaryADIExecution(encoded: text) != nil else { return nil }
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
            case "server_code":
                guard text == "unknown" || (text.utf8.count <= 20 && Int(text).map({ String($0) }) == text) else { return nil }
            case "native_code", "native_subcode", "probe_native_code", "probe_native_subcode":
                guard text == "unknown" || Int32(text).map({ String($0) }) == text else { return nil }
            case "anisette_blob_state":
                guard V3AnisetteAttemptContext.BlobState(rawValue: text) != nil else { return nil }
            case "anisette_recovery":
                guard V3AnisetteAttemptContext.Recovery(rawValue: text) != nil else { return nil }
            case "native_phase", "probe_native_phase":
                guard V3AnisetteNativeEvidence.Phase(rawValue: text) != nil else { return nil }
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
                guard ["sideSignServerReportedError", "sideSignBadResponse", "sideSignInvalidResponse", "sideSignMissingKey", "sideSignDeveloperPortalError", "keychainWrite", "keychainValidationFailed", "keychainOutcomeUnknown", "legacyMigrationConflict", "persistenceFailure", "persistenceOutcomeUnknown", "transportFailure", "anisetteFailure", "anisetteKitInvalidArgument", "anisetteKitLoaderFailed", "anisetteKitSymbolMissing", "anisetteKitReadFailure", "anisetteKitInvalidResponse", "anisetteKitADIError", "anisetteKitLibrariesNotFound", "anisetteKitHTTPError", "decodingTypeMismatch", "decodingValueNotFound", "decodingKeyNotFound", "decodingDataCorrupted", "archiveFileNotFound", "archiveCorrupt", "archiveReadFailed", "archiveWriteFailed", "archiveMissingApp", "unknownAccountFailure", "anisetteIdentityStateInvalid"].contains(text) else { return nil }
            default: return nil
            }
        }
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
                                                         correlationID: String) -> String {
        if let accountError = error as? V3AccountOperationError {
            let failure = accountError.failure(operation: "signIn", id: correlationID)
            return "area=provisioning " + failure.technicalDetails
        }
        let native = error as NSError
        let underlying = safeDiagnosticUnderlying(domain: native.domain, code: native.code)
        let safeID = UUID(uuidString: correlationID)?.uuidString ?? UUID().uuidString
        return "diagnostic_code=SS-PROV-C11 builder_commit=\(V3DiagnosticBuild.commit) domain=\(underlying.domain) code=\(underlying.code) area=provisioning correlation=\(safeID)"
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
    public var message: String {
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
        if code == .timedOut { return "SideStore could not \(timeoutAction) in time while \(timeoutContext)." }
        if let safeCause {            switch safeCause {
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
        if signingContext["typed_error"] == "anisetteIdentityStateInvalid" { return LCAnisettePairError.recovery }
        // V3_RESPONSE_CLASSIFICATION_CARRIER_V1: the two reply-level causes
        // outrank the catalog recovery for the same reason they outrank its
        // message. Repeating an unencodable request, or the same oversized one,
        // fails identically, so the catalog advice to reload would send the user
        // in a circle.
        if operation == "catalog", safeCause != .responseEncodingFailed,
           safeCause != .responseTooLarge, let catalog = catalogFailureRecovery { return catalog }
        if let safeCause {
            switch safeCause {
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
        let signingDetails = signingContext.filter { $0.key != V3TemporaryAnisetteTrace.contextKey && $0.key != V3TemporaryADIConsumption.contextKey && $0.key != V3TemporaryADIExecution.contextKey }.sorted(by: { $0.key < $1.key }).map { " \($0.key)=\($0.value)" }.joined()
        return "schema=1 diagnostic_code=\(diagnosticCode) builder_commit=\(V3DiagnosticBuild.commit) operation=\(operation) stage=\(stage.rawValue) code=\(code.rawValue) correlation=\(correlationID) underlying_domain=\(underlyingDomain) underlying_code=\(displayedUnderlyingCode) retryable=\(retryable.map(String.init) ?? "unknown") source_step=\(sourceStep?.rawValue ?? "unknown") safe_cause=\(safeCause?.rawValue ?? "unknown")" + signingDetails + installVerdict + requestContextSuffix + (launchContext?.technicalDetails ?? "") + (temporaryAnisetteTrace?.technicalDetails ?? "") + (signingContext[V3TemporaryADIConsumption.contextKey].flatMap(V3TemporaryADIConsumption.init(encoded:))?.technicalDetails ?? "") + (signingContext[V3TemporaryADIExecution.contextKey].flatMap(V3TemporaryADIExecution.init(encoded:))?.technicalDetails ?? "")
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
        return V3TemporaryADIExecution.boundingWire(result)
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
            guard let fields = raw as? [String: String],
                  let validated = Self.validatedSigningContext(fields) else { return nil }
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
            if let fields = cause.userInfo["LCStructuredSigningContextV1"] as? [String: String],
               let safeFields = Self.validatedSigningContext(fields) {
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
        guard description.utf8.count <= 8192 else { return (description, nil) }
        let description = V3TemporaryADIExecution.splitDescription(description).base
        // An invalid duplicate/nonterminal execution suffix must not be
        // swallowed by the earlier consumption suffix and expose a false phase.
        guard !V3TemporaryADIExecution.containsMarker(description) else { return (description, nil) }
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
    fileprivate func droppingOldestEvent() -> Self? {
        guard !rows.isEmpty else { return nil }
        return Self(truncated: true, comparison: comparison, inputCovered: inputCovered,
                    rows: Array(rows.dropFirst()))
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

// DEBUG TEMPORARY: bounded execution metadata for one ADIOTPRequest.
// Fixed loaded-ELF hashes, module offsets and import IDs; never raw guest values.
public struct V3TemporaryADIExecution {
    public static let contextKey = "debug_temporary_adi_execution"
    public static let maximumBytes = 1536
    public static let maximumEvents = 89
    private static let marker = " [DEBUG_TEMPORARY_ADI_EXECUTION:"
    private var truncated: Bool
    private let steps: UInt32
    private let w0State: Int
    private let ucStatus: Int
    private let returnReached: Bool
    private let nativeResult: Int32
    private let samples: Int?
    private let sampleStop: Int?
    private var rows: [[String]]

    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes,
              encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let pieces = encoded.split(separator: "|", omittingEmptySubsequences: false)
        guard pieces.count >= 7, pieces[0] == "v1" || pieces[0] == "v2" else { return nil }
        let isV2 = pieces[0] == "v2"
        let offset = isV2 ? 9 : 7
        guard (offset...(offset + (isV2 ? 88 : Self.maximumEvents))).contains(pieces.count),
              pieces[1] == "0" || pieces[1] == "1",
              let steps = UInt32(pieces[2]), String(steps) == String(pieces[2]),
              let w0State = Int(pieces[3]), (0...2).contains(w0State), String(w0State) == String(pieces[3]),
              let ucStatus = Int(pieces[4]), (-1...32).contains(ucStatus), String(ucStatus) == String(pieces[4]),
              pieces[5] == "0" || pieces[5] == "1",
              let nativeResult = Int32(pieces[6]), String(nativeResult) == String(pieces[6]) else { return nil }
        func number(_ value: Substring) -> Int? {
            guard let parsed = Int(value), String(parsed) == String(value) else { return nil }
            return parsed
        }
        let samples: Int?
        let sampleStop: Int?
        if isV2 {
            guard let count = number(pieces[7]), (0...1_000_000).contains(count),
                  let stop = number(pieces[8]), (0...2).contains(stop),
                  stop == 0 || (w0State != 0 && pieces[1] == "1") else { return nil }
            samples = count
            sampleStop = stop
        } else {
            samples = nil
            sampleStop = nil
        }
        var decoded: [[String]] = []
        var counts = [Int](repeating: 0, count: 9)
        var modules: Set<Int> = []
        var phases: Set<Int> = []
        var anchors: Set<Int> = []
        // v1: first/tail PCs, preceding neighborhood, first match, imports.
        // v2: first/tail PCs, imports, ELF hashes, phase counters, constructors,
        // first/latest previous-to-current W0 observations. No raw guest values.
        let limits = [16, 48, 8, 1, 16, 2, 3, 1, 2]
        for row in pieces.dropFirst(offset) {
            let parts = row.split(separator: ",", omittingEmptySubsequences: false)
            guard let first = parts.first, let kind = number(first),
                  (0...(isV2 ? 8 : 4)).contains(kind),
                  !isV2 || (kind != 2 && kind != 3) else { return nil }
            counts[kind] += 1
            guard counts[kind] <= limits[kind] else { return nil }
            if kind == 5 {
                guard parts.count == 5,
                      let module = number(parts[1]), (1...2).contains(module),
                      modules.insert(module).inserted,
                      let state = number(parts[2]), (0...2).contains(state),
                      let size = UInt32(parts[3]), String(size) == String(parts[3]) else { return nil }
                let hash = parts[4]
                if state == 0 {
                    guard size == 0, hash == "-" else { return nil }
                } else {
                    guard size > 0, hash.utf8.count == 64,
                          hash.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
                }
            } else {
                let fields = parts.compactMap(number)
                guard fields.count == parts.count else { return nil }
                switch kind {
                case 0...3:
                    guard fields.count == 4, (0...2).contains(fields[1]),
                          (0...805_306_367).contains(fields[2]), fields[3] == 0,
                          fields[1] != 0 || fields[2] == 0,
                          kind < 2 || w0State == 1 else { return nil }
                case 4:
                    // Positive errno is limited to failed open/read (IDs 14/16).
                    // Zero means unavailable/not reported, not a successful call.
                    guard fields.count == 4, (0...44).contains(fields[1]),
                          (-1...2).contains(fields[2]), (0...4095).contains(fields[3]),
                          fields[3] == 0 || ([14, 16].contains(fields[1]) && fields[2] == -1) else { return nil }
                case 6:
                    guard fields.count == 9, (0...2).contains(fields[1]),
                          phases.insert(fields[1]).inserted,
                          fields.dropFirst(2).allSatisfy({ (0...65_535).contains($0) }) else { return nil }
                case 7:
                    guard fields.count == 5,
                          fields[1...3].allSatisfy({ (0...65_535).contains($0) }),
                          (-1...32).contains(fields[4]) else { return nil }
                case 8:
                    guard fields.count == 8, w0State == 1, (0...1).contains(fields[1]),
                          anchors.insert(fields[1]).inserted,
                          (0...2).contains(fields[2]), (0...805_306_367).contains(fields[3]),
                          fields[2] != 0 || fields[3] == 0,
                          (0...2).contains(fields[4]), (0...805_306_367).contains(fields[5]),
                          fields[4] != 0 || fields[5] == 0,
                          (0...3).contains(fields[6]), (0...44).contains(fields[7]),
                          fields[6] == 3 || fields[7] == 0 else { return nil }
                default: return nil
                }
            }
            decoded.append(parts.map(String.init))
        }
        if isV2 {
            guard modules.count == 2, phases.count == 3, counts[7] == 1,
                  anchors.count == (w0State == 1 ? 2 : 0) else { return nil }
        } else {
            guard counts[3] == (w0State == 1 ? 1 : 0) else { return nil }
        }
        self.truncated = pieces[1] == "1"
        self.steps = steps
        self.w0State = w0State
        self.ucStatus = ucStatus
        self.returnReached = pieces[5] == "1"
        self.nativeResult = nativeResult
        self.samples = samples
        self.sampleStop = sampleStop
        self.rows = decoded
    }
    public var encoded: String {
        let header = "\(samples == nil ? "v1" : "v2")|\(truncated ? 1 : 0)|\(steps)|\(w0State)|\(ucStatus)|\(returnReached ? 1 : 0)|\(nativeResult)"
        let sampling = samples.flatMap { count in sampleStop.map { "|\(count)|\($0)" } } ?? ""
        return header + sampling + rows.map { "|" + $0.joined(separator: ",") }.joined()
    }
    public var technicalDetails: String {
        guard V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled else { return "" }
        let label = samples == nil ? "first_w0_match" : "first_latest_w0_match"
        let observation = w0State == 1
            ? "\nDEBUG TEMPORARY \(label)=pre_instruction_observation causal_origin=unproven" : ""
        return "\nDEBUG TEMPORARY adi_execution=\(encoded)" + observation
    }
    static func splitDescription(_ description: String) -> (base: String, trace: Self?) {
        // The producer appends this after consumption. Even invalid optional
        // metadata is removable only as one bounded, terminal owned suffix.
        guard description.utf8.count <= 8192, description.hasSuffix("]"),
              let range = description.range(of: marker),
              description[range.upperBound...].range(of: marker) == nil else { return (description, nil) }
        let body = String(description[range.upperBound...].dropLast())
        guard !body.contains("]") else { return (description, nil) }
        return (String(description[..<range.lowerBound]), Self(encoded: body))
    }
    static func containsMarker(_ description: String) -> Bool {
        description.range(of: marker) != nil
    }
    public static func sanitizingContext(_ supplied: [String: String]) -> [String: String] {
        var result = supplied
        let raw = result.removeValue(forKey: contextKey)
        result = V3TemporaryADIConsumption.sanitizingContext(result)
        if V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled,
           let raw, let parsed = Self(encoded: raw), result.count < 20 {
            result[contextKey] = parsed.encoded
        }
        return result
    }
    private mutating func removeOldestRow(kind: Int, retaining: Int = 0) -> Bool {
        let token = String(kind)
        guard rows.filter({ $0[0] == token }).count > retaining else { return false }
        // v2 emits its tail/import windows newest first; trim their last row.
        // v1 windows and the initial-PC window are chronological.
        let newestFirst = samples != nil && (kind == 1 || kind == 4)
        let selected = newestFirst ? rows.lastIndex(where: { $0[0] == token })
            : rows.firstIndex(where: { $0[0] == token })
        guard let index = selected else { return false }
        rows.remove(at: index)
        truncated = true
        return true
    }
    private mutating func trimLaterObservations() -> Bool {
        // Mandatory v2 hashes, counters and first/latest anchors survive.
        // Retain v1 first-match context and the latest final-tail observation
        // until every lower-priority optional row is exhausted.
        if removeOldestRow(kind: 4) { return true }
        if removeOldestRow(kind: 1, retaining: 1) { return true }
        if removeOldestRow(kind: 2) { return true }
        return removeOldestRow(kind: 1)
    }
    public static func boundingWire(_ supplied: [String: Any]) -> [String: Any] {
        guard var context = supplied["signingContext"] as? [String: String],
              let raw = context.removeValue(forKey: contextKey) else {
            return V3TemporaryADIConsumption.boundingWire(supplied)
        }
        var result = supplied
        result["signingContext"] = context
        guard V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled,
              var trace = Self(encoded: raw), context.count < 20 else {
            return V3TemporaryADIConsumption.boundingWire(result)
        }
        let consumptionKey = V3TemporaryADIConsumption.contextKey
        var consumption = context[consumptionKey].flatMap(V3TemporaryADIConsumption.init(encoded:))
        while true {
            context[contextKey] = trace.encoded
            result["signingContext"] = context
            if let data = try? PropertyListSerialization.data(fromPropertyList: result, format: .binary, options: 0),
               data.count <= V3TemporaryADIConsumption.maximumWireBytes { return result }
            if trace.removeOldestRow(kind: 0) { continue }
            if let trimmed = consumption?.droppingOldestEvent() {
                consumption = trimmed
                context[consumptionKey] = trimmed.encoded
                continue
            }
            if trace.trimLaterObservations() { continue }
            // Headers, final status, ELF/counter summaries and match anchors
            // survive row trimming with explicit loss. Omit optional data
            // only if even these summaries cannot fit beside the main error.
            if context.removeValue(forKey: consumptionKey) != nil {
                consumption = nil
                continue
            }
            context.removeValue(forKey: contextKey)
            result["signingContext"] = context
            return result
        }
    }
}

public struct V3TemporaryAnisetteTrace: Equatable, Sendable {
    public static let temporaryAnisetteTraceEnabled = true
    public static let contextKey = "debug_temporary_anisette_trace"
    public static let maximumEvents = 64
    public static let maximumBytes = 2048
    public enum Step: String, CaseIterable, Sendable {
        case keychainRead, pairValidation, blobPresence, requestHeaders, primaryProvider
        case currentProbe, currentProof, currentSnapshot, legacyRead, legacyCandidate
        case legacyIdentifierMissing, legacyIdentifierEqual, legacyIdentifierDifferent, legacyIdentifierAmbiguous, legacyIdentifierUnavailable
        case legacyBlobMissing, legacyBlobEqual, legacyBlobDifferent, legacyBlobAmbiguous, legacyBlobUnavailable
        case legacyProbe, legacyProof, identityCommit, freshBlobCommit
    }
    public enum Outcome: String, CaseIterable, Sendable { case started, succeeded, failed, skipped }
    public enum Scope: String, CaseIterable, Sendable { case primary, current, legacy }
    private enum NativeEvent: String, CaseIterable, Sendable {
        case argumentsOk = "arguments.ok"
        case argumentsFailed = "arguments.failed"
        case rootOk = "root.ok"
        case rootFailed = "root.failed"
        case uuidDirCreated = "uuid_dir.created"
        case uuidDirExists = "uuid_dir.exists"
        case uuidDirFailed = "uuid_dir.failed"
        case fileOpenOk = "file.open.ok"
        case fileOpenFailed = "file.open.failed"
        case fileStreamOk = "file.stream.ok"
        case fileStreamFailed = "file.stream.failed"
        case fileWriteOk = "file.write.ok"
        case fileWriteFailed = "file.write.failed"
        case fileFlushOk = "file.flush.ok"
        case fileFlushFailed = "file.flush.failed"
        case fileFlushNotChecked = "file.flush.not_checked"
        case fileCloseOk = "file.close.ok"
        case fileCloseFailed = "file.close.failed"
        case fileReadOpenOk = "file.read_open.ok"
        case fileReadOpenFailed = "file.read_open.failed"
        case fileReadbackOk = "file.readback.ok"
        case fileReadbackFailed = "file.readback.failed"
        case fileReadbackNotChecked = "file.readback.not_checked"
        case fileReadCloseOk = "file.read_close.ok"
        case fileReadCloseFailed = "file.read_close.failed"
        case fileRenameOk = "file.rename.ok"
        case fileRenameFailed = "file.rename.failed"
        case vmInitOk = "vm.init.ok"
        case vmInitFailed = "vm.init.failed"
        case vmReused = "vm.reused"
        case setupBegin = "setup.begin"
        case setupOk = "setup.ok"
        case setupFailed = "setup.failed"
        case libraryLoadOk = "library.load.ok"
        case libraryLoadFailed = "library.load.failed"
        case libraryCached = "library.cached"
        case libraryInitOk = "library.init.ok"
        case libraryInitFailed = "library.init.failed"
        case provisioningPathOk = "provisioning_path.ok"
        case provisioningPathFailed = "provisioning_path.failed"
        case provisioningPathCached = "provisioning_path.cached"
        case androidIdOk = "android_id.ok"
        case androidIdFailed = "android_id.failed"
        case androidIdCached = "android_id.cached"
        case nativeSymbolOk = "native.symbol.ok"
        case nativeSymbolFailed = "native.symbol.failed"
        case nativeOtpOk = "native.otp.ok"
        case nativeOtpFailed = "native.otp.failed"
        case nativeOutputOk = "native.output.ok"
        case nativeOutputFailed = "native.output.failed"
        case nativeOutputNotChecked = "native.output.not_checked"
        case cleanupOk = "cleanup.ok"
        case cleanupFailed = "cleanup.failed"
        case cleanupNotNeeded = "cleanup.not_needed"
        case cleanupNotRequested = "cleanup.not_requested"
        case responseAllocationFailed = "response.allocation.failed"
        case traceTruncated = "trace.truncated"
    }
    private enum Event: Equatable, Sendable {
        case step(Step, Outcome)
        case native(Scope, NativeEvent)
        case truncated

        var token: String {
            switch self {
            case .step(let step, let outcome): return "swift.\(step.rawValue).\(outcome.rawValue)"
            case .native(let scope, let event): return "native.\(scope.rawValue).\(event.rawValue)"
            case .truncated: return "trace.truncated"
            }
        }
        init?(token: String) {
            if token == "trace.truncated" { self = .truncated; return }
            let parts = token.components(separatedBy: ".")
            if parts.count == 3, parts[0] == "swift",
               let step = Step(rawValue: parts[1]), let outcome = Outcome(rawValue: parts[2]) {
                self = .step(step, outcome); return
            }
            if parts.count >= 3, parts[0] == "native", let scope = Scope(rawValue: parts[1]),
               let event = NativeEvent(rawValue: parts.dropFirst(2).joined(separator: ".")) {
                self = .native(scope, event); return
            }
            return nil
        }
    }
    private var events: [Event] = []
    public init() {}

    public mutating func record(step: Step, outcome: Outcome) {
        append(.step(step, outcome))
    }
    public mutating func appendNative(errorDescription: String, scope: Scope) {
        guard Self.temporaryAnisetteTraceEnabled,
              let suffix = Self.nativeSuffix(errorDescription) else { return }
        for event in suffix.events { append(.native(scope, event)) }
    }
    private mutating func append(_ event: Event) {
        guard Self.temporaryAnisetteTraceEnabled else { return }
        events.append(event)
        if events.count > Self.maximumEvents || Self.encode(events).utf8.count > Self.maximumBytes {
            if events.first != .truncated { events.insert(.truncated, at: 0) }
            // Drop the oldest observation, keeping the final failure and a
            // finite marker that makes the missing prefix explicit.
            while events.count > Self.maximumEvents || Self.encode(events).utf8.count > Self.maximumBytes {
                events.remove(at: 1)
            }
        }
    }
    private static func encode(_ events: [Event]) -> String {
        "v1;" + events.map(\.token).joined(separator: ";")
    }
    public var snapshot: String? {
        guard Self.temporaryAnisetteTraceEnabled, !events.isEmpty else { return nil }
        return Self.encode(events)
    }
    public init?(encoded: String) {
        guard Self.temporaryAnisetteTraceEnabled, encoded.utf8.count <= Self.maximumBytes,
              encoded.hasPrefix("v1;") else { return nil }
        let tokens = encoded.dropFirst(3).components(separatedBy: ";")
        guard !tokens.isEmpty, tokens.count <= Self.maximumEvents else { return nil }
        var decoded: [Event] = []
        for (index, token) in tokens.enumerated() {
            guard let event = Event(token: token),
                  event != .truncated || index == 0 else { return nil }
            decoded.append(event)
        }
        events = decoded
    }

    // Native suffixes are accepted only in their entirety. Arbitrary leading
    // prose is never retained by the trace or passed to diagnostics.
    private static func nativeSuffix(_ description: String) -> (base: String, events: [NativeEvent])? {
        let description = V3TemporaryADIConsumption.splitDescription(description).base
        let marker = " [DEBUG_TEMPORARY_NATIVE_TRACE:"
        guard description.utf8.count <= 4096, description.hasSuffix("]"),
              let range = description.range(of: marker),
              description[range.upperBound...].range(of: marker) == nil else { return nil }
        let body = description[range.upperBound...].dropLast()
        guard !body.isEmpty, body.utf8.count <= 1024 else { return nil }
        let tokens = body.components(separatedBy: ",")
        guard tokens.count <= 32 else { return nil }
        var decoded: [NativeEvent] = []
        for (index, token) in tokens.enumerated() {
            guard let event = NativeEvent(rawValue: token),
                  event != .traceTruncated || index == tokens.count - 1 else { return nil }
            decoded.append(event)
        }
        return (String(description[..<range.lowerBound]), decoded)
    }
    static func nativeDescriptionWithoutTrace(_ description: String) -> String {
        // Stripping valid metadata preserves the pre-existing native phase/code
        // classifier even if a trace-enabled service meets a disabled host.
        let base = V3TemporaryADIConsumption.splitDescription(description).base
        return nativeSuffix(base)?.base ?? base
    }
    public var technicalDetails: String {
        guard let snapshot else { return "" }
        return "\nDEBUG TEMPORARY anisette_trace=\(snapshot)"
    }
    public var failedStep: String? {
        guard Self.temporaryAnisetteTraceEnabled else { return nil }
        for event in events.reversed() {
            switch event {
            case .step(let step, .failed):
                let scope: Scope?
                switch step {
                case .primaryProvider: scope = .primary
                case .currentProbe: scope = .current
                case .legacyProbe: scope = .legacy
                default: scope = nil
                }
                if let scope, let native = nativeFailedStep(scope: scope) { return native }
                return step.rawValue
            case .native(let scope, let native) where native.rawValue.hasSuffix(".failed"):
                return nativeFailedStep(scope: scope)
            default: continue
            }
        }
        return nil
    }
    private func nativeFailedStep(scope: Scope) -> String? {
        // Setup wrappers and cleanup can also fail after the causal native
        // step. Keep the first failure from this invocation visible; the full
        // ordered trace still includes every subsequent failure.
        for event in events {
            if case .native(let observedScope, let native) = event,
               observedScope == scope, native.rawValue.hasSuffix(".failed") {
                return "\(scope.rawValue).\(native.rawValue.dropLast(7))"
            }
        }
        return nil
    }

}

// Recovery evidence is finite and contains no identity, blob or provider text.
struct V3AnisetteAttemptContext {
    enum BlobState: String { case existing, fresh, unknown }
    enum Recovery: String {
        case notAttempted, noLegacyCandidate, legacyReadFailed, ambiguousLegacyIdentity
        case invalidLegacyPair, legacyBlobMismatch, probeRejected, invalidNativeProof
        case restoreFailed, stateChanged, temporaryStorageUnavailable, currentProbeRejected
        case automaticRecoveryDisabled
    }
    let blobState: BlobState
    let recovery: Recovery
    var probeEvidence: V3AnisetteNativeEvidence? = nil
    var trace: V3TemporaryAnisetteTrace? = nil
    var diagnosticFields: [String: String] {
        var fields = ["anisette_blob_state": blobState.rawValue, "anisette_recovery": recovery.rawValue]
        if let snapshot = trace?.snapshot { fields[V3TemporaryAnisetteTrace.contextKey] = snapshot }
        if let probeEvidence {
            fields["probe_native_code"] = String(probeEvidence.code)
            fields["probe_native_phase"] = probeEvidence.phase.rawValue
            fields["probe_native_subcode"] = probeEvidence.subcode.map(String.init) ?? "unknown"
        }
        return fields
    }
}
struct V3AnisetteAttemptError: Error {
    let underlying: Error
    let context: V3AnisetteAttemptContext
}

// V3_ANISETTE_NATIVE_EVIDENCE_V1: the associated ADI Int32 is not an Apple
// server result or Swift's NSError enum discriminator. Only exact producers in
// AnisetteKit 1f5a7e36553cc865b873f222b87a6486c0bcc7bf Native/anisette_core_{mac,uc}.cpp
// identify a native phase. Descriptions (including paths) never leave here.
struct V3AnisetteNativeEvidence {
    enum Phase: String {
        case unknown, nativeOTP, provisionStart, provisionEnd
        case setupLibraries, setupLoadLibrary, setupProvisioningPath, setupAndroidID
        case readProvisioningData, nativeStorage
    }
    let code: Int32
    let phase: Phase
    let subcode: Int32?
    var consumption: V3TemporaryADIConsumption? = nil
    var execution: V3TemporaryADIExecution? = nil

    static func capture(code: Int32, description: String) -> Self {
        let execution = V3TemporaryADIExecution.splitDescription(description)
        let observed = V3TemporaryADIConsumption.splitDescription(execution.base)
        var evidence = captureBase(code: code, description: observed.base)
        if V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled {
            evidence.consumption = observed.trace
            evidence.execution = execution.trace
        }
        return evidence
    }
    private static func captureBase(code: Int32, description: String) -> Self {
        let unknown = Self(code: code, phase: .unknown, subcode: nil)
        // Bound inspection before matching. Never scan arbitrary messages for
        // keywords, URLs, digits or error-like substrings.
        let description = V3TemporaryAnisetteTrace.nativeDescriptionWithoutTrace(description)
        guard description.utf8.count <= 256 else { return unknown }
        // Exact fixed producers in the reviewed native staging patch. Numeric
        // equality alone never assigns a storage phase to arbitrary errors.
        if code == -6 && (description == "Checked OTP staging failed" || description == "Isolated OTP staging failed") {
            return Self(code: code, phase: .nativeStorage, subcode: nil)
        }
        let storagePrefix = "Checked OTP staging failed (errno "
        if code == -6 {
            let value = String(description.dropFirst(storagePrefix.count).dropLast())
            if let observedErrno = Int32(value), observedErrno > 0, observedErrno <= 4095,
               description == "\(storagePrefix)\(observedErrno))" {
                // For nativeStorage only, subcode is the failed POSIX call's
                // immediately captured errno, not an ADI or Apple server code.
                return Self(code: code, phase: .nativeStorage, subcode: observedErrno)
            }
        }
        for (symbol, phase) in [("ADIOTPRequest", Phase.nativeOTP),
                                ("ADIProvisioningStart", .provisionStart),
                                ("ADIProvisioningEnd", .provisionEnd)] {
            if (code == -3 && description == "Symbol \(symbol) missing") ||
               (code != 0 && description == failureDescription(symbol, code: code)) {
                return Self(code: code, phase: phase, subcode: nil)
            }
        }
        if code == -4 && description == "Failed to read generated adi.pb" {
            return Self(code: code, phase: .readProvisioningData, subcode: nil)
        }
        // All setup failures return wrapper -2, even when a setup ADI call
        // reports another number. Keep that nested scalar separate as well.
        guard code == -2 else { return unknown }
        let setupSymbols: [(String, String, Phase)] = [
            ("ADILoadLibraryWithPath", "ADILoadLibraryWithPath (kq56gsgHG6)", .setupLoadLibrary),
            ("ADISetProvisioningPath", "ADISetProvisioningPath", .setupProvisioningPath),
            ("ADISetAndroidID", "ADISetAndroidID", .setupAndroidID)
        ]
        if let tail = description.components(separatedBy: ": ").last,
           let subcode = Int32(tail), subcode != 0, String(subcode) == tail {
            for (ucSymbol, macSymbol, phase) in setupSymbols {
                if description == "\(ucSymbol) failed: \(subcode)" ||
                   description == failureDescription(macSymbol, code: subcode) {
                    return Self(code: code, phase: phase, subcode: subcode)
                }
            }
        }
        let fixedSetup: [String: Phase] = [
            "Library directory path is null.": .setupLibraries,
            "Failed to load libraries into VM": .setupLibraries,
            "Required ADI setup symbol missing in VM": .setupLoadLibrary,
            "Symbol ADILoadLibraryWithPath (kq56gsgHG6) missing from libraries": .setupLoadLibrary,
            "Symbol ADISetProvisioningPath missing in VM": .setupProvisioningPath,
            "Symbol ADISetProvisioningPath (nf92ngaK92) missing": .setupProvisioningPath,
            "Symbol ADISetAndroidID missing in VM": .setupAndroidID,
            "Symbol ADISetAndroidID (Sph98paBcz) missing": .setupAndroidID
        ]
        return Self(code: code, phase: fixedSetup[description] ?? .unknown, subcode: nil)
    }

    private static func failureDescription(_ symbol: String, code: Int32) -> String {
        // Exact finite labels from Native/anisette_base.cpp at the same pin.
        // Matching the label against its code rejects even plausible-looking
        // injected descriptions. Unknown numeric results remain observable.
        let labels: [Int32: String] = [
            -1: "Invalid argument passed", -2: "ELF Loader failed to map dependencies",
            -3: "Required ADI symbol missing", -4: "Failed to read generated file",
            -5: "Failed to parse response JSON",
            -45001: "Invalid ADI parameters (-45001)", -45002: "Invalid ADI decipher params (-45002)",
            -45003: "Invalid ADI trust key (-45003)", -45006: "PTM and TK mismatch (-45006)",
            -45018: "Invalid input header (-45018)", -45019: "Unknown ADI function (-45019)",
            -45020: "Invalid input body (-45020)", -45025: "Unknown ADI session (-45025)",
            -45026: "Empty ADI session (-45026)", -45031: "Invalid data header (-45031)",
            -45032: "Data too short (-45032)", -45033: "Invalid data body (-45033)",
            -45034: "Unknown call flags (-45034)", -45036: "ADI time error (-45036)",
            -45046: "Empty hardware IDs (-45046)", -45054: "ADI filesystem error (-45054)",
            -45061: "Device not provisioned (-45061)", -45062: "Cannot erase unprovisioned device (-45062)",
            -45063: "Pending ADI session (-45063)", -45066: "ADI session already done (-45066)",
            -45075: "Library loading failed (-45075)"
        ]
        return "\(symbol) failed (\(labels[code] ?? "Unknown ADI error")): \(code)"
    }
}

// V3_TYPED_ACCOUNT_DIAGNOSTICS_V1: only operation-owned stage and fixed
// classifications cross the wire. Original errors stay inside the process for
// typed guidance; descriptions, userInfo and provider payloads never serialize.
struct V3AccountOperationError: Error, LocalizedError {
    enum Kind: String {
        case keychainWrite, keychainValidationFailed, keychainOutcomeUnknown
        case legacyMigrationConflict, persistenceFailure, persistenceOutcomeUnknown, transportFailure
        case sideSignServerReportedError, sideSignBadResponse, sideSignInvalidResponse
        case sideSignMissingKey, sideSignDeveloperPortalError, anisetteFailure
        case anisetteKitInvalidArgument, anisetteKitLoaderFailed, anisetteKitSymbolMissing, anisetteKitReadFailure, anisetteKitInvalidResponse, anisetteKitADIError, anisetteKitLibrariesNotFound, anisetteKitHTTPError, decodingTypeMismatch, decodingValueNotFound, decodingKeyNotFound, decodingDataCorrupted
        case archiveFileNotFound, archiveCorrupt, archiveReadFailed, archiveWriteFailed, archiveMissingApp
        case unknownAccountFailure
        case anisetteIdentityStateInvalid
    }
    let step: CombinedFailure.SourceStep
    let kind: Kind
    let underlying: Error
    let serverCode: Int?
    var httpStatus: Int? = nil
    var nativeEvidence: V3AnisetteNativeEvidence? = nil
    var anisetteAttempt: V3AnisetteAttemptContext? = nil

    var errorDescription: String? { "An account operation failed; review the safe diagnostics." }
    var credentialCommit: Bool { step == .credentialCommit && kind != .anisetteIdentityStateInvalid }
    // Apple Developer Portal result 1100 rejects the portal session. Scope this
    // to the observed team-list boundary; an NSError bridge code is not proof.
    var portalSessionRejected: Bool {
        step == .fetchTeams && kind == .sideSignServerReportedError && serverCode == 1100
    }
    var requiresReconciliation: Bool {
        kind == .keychainOutcomeUnknown || kind == .persistenceOutcomeUnknown
    }
    var failureStage: CombinedFailure.Stage {
        if kind == .anisetteIdentityStateInvalid { return .authentication }
        switch step {
        case .credentialCommit, .saveAccount, .activateAccount, .activateCertificate: return .persistence
        case .authenticate, .anisetteFetch, .appleAuthentication, .accountLookup: return .authentication
        default: return .provisioning
        }
    }
    func failure(operation: String, id: String) -> CombinedFailure {
        let native = underlying as NSError
        let safeCause: CombinedFailure.SafeCause?
        if kind == .anisetteIdentityStateInvalid { safeCause = nil }
        else if credentialCommit {
            safeCause = kind == .keychainOutcomeUnknown ? .credentialCommitOutcomeUnknown : .credentialCommitFailed
        } else if step == .activateAccount { safeCause = .accountActivationFailed }
        else if step == .activateCertificate || step == .saveAccount { safeCause = .provisioningStorageFailed }
        else { safeCause = nil }
        // An associated Apple result is separate from Swift's enum bridge code.
        // HTTP status remains unavailable unless a typed producer observes it.
        var signingContext = ["typed_error": kind.rawValue,
            "server_code": serverCode.map(String.init) ?? "unknown", "http_status": httpStatus.map(String.init) ?? "unavailable"]
        if kind == .anisetteKitADIError, let nativeEvidence {
            signingContext["native_code"] = String(nativeEvidence.code)
            signingContext["native_phase"] = nativeEvidence.phase.rawValue
            signingContext["native_subcode"] = nativeEvidence.subcode.map(String.init) ?? "unknown"
        }
        if let anisetteAttempt {
            signingContext.merge(anisetteAttempt.diagnosticFields) { _, observed in observed }
        }
        if kind == .anisetteKitADIError, let consumption = nativeEvidence?.consumption,
           signingContext.count < 20 {
            signingContext[V3TemporaryADIConsumption.contextKey] = consumption.encoded
        }
        if kind == .anisetteKitADIError, let execution = nativeEvidence?.execution,
           signingContext.count < 20 {
            signingContext[V3TemporaryADIExecution.contextKey] = execution.encoded
        }
        return CombinedFailure(operation: operation, stage: failureStage, id: id,
            underlying: NSError(domain: native.domain, code: native.code),
            retryable: safeCause != nil || portalSessionRejected || kind == .anisetteIdentityStateInvalid ? false : nil, safeCause: safeCause,
            sourceStep: kind == .anisetteIdentityStateInvalid ? .anisetteFetch : step,
            signingContext: signingContext)
    }
}

// Journal only the account/team activation transaction, before the database is
// touched. No password, DSID, token, certificate or provider payload is stored.
// A crash is resolved from a fresh persistent-store read against the exact
// pre-transaction or intended active identity set, never account-row presence.
struct V3AccountDatabaseOutcomeUnknownError: Error, LocalizedError {
    var errorDescription: String? { "The local account activation outcome needs reconciliation." }
}

enum V3AccountDatabaseRecovery {
    static let key = "V3AccountDatabaseActivationPendingV1"
    static var requiresReconciliation: Bool { UserDefaults.standard.object(forKey: key) != nil }

    private static func valid(_ values: [String]) -> Bool {
        values.count <= 1024 && values == values.sorted() && Set(values).count == values.count &&
            values.allSatisfy { value in
                value.utf8.count <= 1024 &&
                    ((value.hasPrefix("account:") && value.count > 8) ||
                     (value.hasPrefix("team:") && value.count > 5))
            }
    }
    static func begin(previous: [String], intended: [String], defaults: UserDefaults = .standard) throws {
        guard valid(previous), valid(intended), defaults.object(forKey: key) == nil else {
            throw V3AccountDatabaseOutcomeUnknownError()
        }
        let record: [String: Any] = ["previous": previous, "intended": intended]
        defaults.set(record, forKey: key)
        guard defaults.synchronize(),
              let saved = defaults.dictionary(forKey: key),
              saved["previous"] as? [String] == previous,
              saved["intended"] as? [String] == intended else {
            throw V3AccountDatabaseOutcomeUnknownError()
        }
    }
    static func reconcile(observed: [String], defaults: UserDefaults = .standard) throws {
        guard defaults.object(forKey: key) != nil else { return }
        guard valid(observed), let record = defaults.dictionary(forKey: key),
              Set(record.keys) == Set(["previous", "intended"]),
              let previous = record["previous"] as? [String], valid(previous),
              let intended = record["intended"] as? [String], valid(intended),
              observed == previous || observed == intended else {
            throw V3AccountDatabaseOutcomeUnknownError()
        }
        defaults.removeObject(forKey: key)
        guard defaults.synchronize(), defaults.object(forKey: key) == nil else {
            // Restore the hold if durable removal cannot be established.
            defaults.set(record, forKey: key)
            _ = defaults.synchronize()
            throw V3AccountDatabaseOutcomeUnknownError()
        }
    }
}

// V3_POST_MUTATION_PERSISTENCE_CONTRACT_V1: the device operation may already
// have succeeded when this local durable save fails. Keep only fixed semantic
// markers; never retain or serialize the native Core Data error text/userInfo.
struct V3PostMutationPersistenceError: Error, CustomNSError, LocalizedError {
    static var errorDomain: String { "V3PostMutationPersistenceErrorDomain" }
    var errorCode: Int { 1 }
    var errorUserInfo: [String: Any] {
        [NSLocalizedDescriptionKey: "SideStore could not confirm that the operation result was saved. The device may already have changed.",
         "LCStructuredFailureStageV1": CombinedFailure.Stage.persistence.rawValue,
         "LCStructuredFailureCauseV1": CombinedFailure.SafeCause.operationPersistenceFailed.rawValue]
    }
    var errorDescription: String? {
        errorUserInfo[NSLocalizedDescriptionKey] as? String
    }
}

enum V3MutationPersistencePolicy {
    /// The Runner calls this only after its device-side pipeline returned success.
    /// A false `hasChanges` means the state was already durable; a failed save
    /// throws a fixed non-retryable outcome instead of allowing group success.
    static func persistResult(hasChanges: Bool, save: () throws -> Void) throws {
        guard hasChanges else { return }
        do {
            try save()
        } catch {
            throw V3PostMutationPersistenceError()
        }
    }
}

public enum CombinedRefreshVerificationError: Error, Equatable {
    case missingResult
    case staleResult
}

public struct CombinedIPAFileError: Error, LocalizedError, CustomNSError {
    public enum Problem: String, Equatable {
        case invalidToken, missingFile, emptyFile, invalidPackage, fileAccess, stagingFailed
    }
    public let problem: Problem
    public static let errorDomain = "V3IPAFileErrorDomain"
    public var errorCode: Int {
        switch problem {
        case .invalidToken: return 1
        case .missingFile: return 2
        case .emptyFile: return 3
        case .invalidPackage: return 4
        case .fileAccess: return 5
        case .stagingFailed: return 6
        }
    }
    public var errorUserInfo: [String: Any] { [NSLocalizedDescriptionKey: errorDescription ?? "IPA file preparation failed."] }
    public init(_ problem: Problem) { self.problem = problem }
    public var combinedCode: CombinedFailure.Code {
        switch problem {
        case .invalidToken: return .invalidToken
        case .missingFile: return .missingFile
        case .emptyFile: return .emptyFile
        case .invalidPackage: return .invalidPackage
        case .fileAccess: return .fileAccess
        case .stagingFailed: return .stagingFailed
        }
    }
    public var errorDescription: String? {
        switch problem {
        case .invalidToken: return "The staged IPA reference is invalid."
        case .missingFile: return "The staged IPA is no longer available."
        case .emptyFile: return "The selected IPA is empty."
        case .invalidPackage: return "The selected file is not a valid IPA app package."
        case .fileAccess: return "The selected IPA could not be read."
        case .stagingFailed: return "The selected IPA could not be staged."
        }
    }
}

private func v3StrictPlistInteger(_ value: Any?) -> Int? {
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

enum V3NotDispatchedReplyPolicy {
    static func confirms(_ data: Data, requestID: String, maximumBytes: Int) -> Bool {
        guard maximumBytes > 0, !data.isEmpty, data.count <= maximumBytes,
              let reply = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              v3StrictPlistInteger(reply["version"]) == 1,
              CombinedFailure.uuidCorrelationMatches(reply["id"] as? String, expectedID: requestID),
              reply["error"] as? String != nil,
              reply["result"] == nil,
              reply["ok"] == nil,
              let notDispatched = reply["operationNotDispatched"] as? NSNumber,
              CFGetTypeID(notDispatched) == CFBooleanGetTypeID(), notDispatched.boolValue,
              let failure = reply["failure"] as? [String: Any],
              CombinedFailure.decode(failure, expectedID: requestID) != nil else { return false }
        return true
    }
}

enum V3AnisetteSyncFailurePolicy {
    /// Converts only evidence exposed by the pinned Anisette sync path into a
    /// semantic failure. URL transport errors and AnisetteServersManager's
    /// explicit HTTP/invalid-response errors are distinct; every other error
    /// remains unknown rather than being called a network failure.
    static func failure(_ error: Error, id: String) -> CombinedFailure {
        if error is CancellationError {
            return CombinedFailure(operation: "anisetteSync", stage: .command,
                code: .cancelled, id: id, retryable: false)
        }
        let native = error as NSError
        if native.domain == NSURLErrorDomain && native.code == NSURLErrorCancelled {
            return CombinedFailure(operation: "anisetteSync", stage: .command,
                code: .cancelled, id: id, underlying: native, retryable: false)
        }
        if let urlError = error as? URLError {
            if urlError.code == .cancelled {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .cancelled, id: id, underlying: native, retryable: false)
            }
            if let cause = networkCause(urlError.code) {
                return CombinedFailure(operation: "anisetteSync", stage: .network,
                    code: .failed, id: id, underlying: error, retryable: true, safeCause: cause)
            }
        }
        if native.domain == NSURLErrorDomain,
           let cause = networkCause(URLError.Code(rawValue: native.code)) {
            return CombinedFailure(operation: "anisetteSync", stage: .network,
                code: .failed, id: id, underlying: native, retryable: true, safeCause: cause)
        }
        if native.domain == "AnisetteServersManager" {
            if native.code == -1 {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .invalidResponse, id: id, underlying: native,
                    safeCause: .anisetteInvalidResponse)
            }
            if native.code == 408 {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .failed, id: id, underlying: native, retryable: true,
                    safeCause: .anisetteRequestTimedOut)
            }
            if native.code == 429 {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .busy, id: id, underlying: native, retryable: true,
                    safeCause: .anisetteRateLimited)
            }
            if (500..<600).contains(native.code) {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .failed, id: id, underlying: native, retryable: true,
                    safeCause: .anisetteServerUnavailable)
            }
            if (100..<500).contains(native.code), !(200..<300).contains(native.code) {
                return CombinedFailure(operation: "anisetteSync", stage: .command,
                    code: .failed, id: id, underlying: native,
                    safeCause: .anisetteServerRejected)
            }
        }
        return CombinedFailure(operation: "anisetteSync", stage: .command,
            code: .failed, id: id, underlying: error, safeCause: .anisetteUnknownFailure)
    }

    private static func networkCause(_ code: URLError.Code) -> CombinedFailure.SafeCause? {
        switch code {
        case .networkConnectionLost: return .networkConnectionLost
        case .timedOut: return .networkTimedOut
        case .notConnectedToInternet, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
            return .networkUnavailable
        default: return nil
        }
    }
}


// V3_STABLE_DIAGNOSTIC_CODE_V1: identifiers classify finite evidence, never attempts.
// Values are append-only. See docs/ERROR_CODES_V1.json; never renumber existing cases.
extension CombinedFailure {
    public var diagnosticCode: String {
        var parts = ["SS", stage.diagnosticToken, code.diagnosticToken]
        if let sourceStep { parts.append(sourceStep.diagnosticToken) }
        if let safeCause { parts.append(safeCause.diagnosticToken) }
        if let typed = signingContext["typed_error"], let token = Self.typedDiagnosticToken(typed) { parts.append(token) }
        if let launchContext { parts.append(launchContext.sourceStep.diagnosticToken) }
        if hasApplicationVerificationEvidence && underlyingCode == 0xE8008024 { parts.append("V01") }
        if hasApplicationVerificationEvidence && underlyingCode == 0xE8008018 { parts.append("V02") }
        if sourceStep == .fetchTeams && signingContext["typed_error"] == "sideSignServerReportedError" && signingContext["server_code"] == "1100" { parts.append("P01") }
        return parts.joined(separator: "-")
    }
    public var diagnosticLabel: String { "Error ID: \(diagnosticCode)" }
    fileprivate static func typedDiagnosticToken(_ value: String) -> String? {
        switch value {
        case "sideSignServerReportedError": return "T01"
        case "sideSignBadResponse": return "T02"
        case "sideSignInvalidResponse": return "T03"
        case "sideSignMissingKey": return "T04"
        case "sideSignDeveloperPortalError": return "T05"
        case "keychainWrite": return "T06"
        case "keychainValidationFailed": return "T07"
        case "keychainOutcomeUnknown": return "T08"
        case "legacyMigrationConflict": return "T09"
        case "persistenceFailure": return "T10"
        case "persistenceOutcomeUnknown": return "T11"
        case "transportFailure": return "T12"
        case "anisetteFailure": return "T13"
        case "anisetteKitInvalidArgument": return "T14"
        case "anisetteKitLoaderFailed": return "T15"
        case "anisetteKitSymbolMissing": return "T16"
        case "anisetteKitReadFailure": return "T17"
        case "anisetteKitInvalidResponse": return "T18"
        case "anisetteKitADIError": return "T19"
        case "anisetteKitLibrariesNotFound": return "T20"
        case "anisetteKitHTTPError": return "T21"
        case "decodingTypeMismatch": return "T22"
        case "decodingValueNotFound": return "T23"
        case "decodingKeyNotFound": return "T24"
        case "decodingDataCorrupted": return "T25"
        case "archiveFileNotFound": return "T26"
        case "archiveCorrupt": return "T27"
        case "archiveReadFailed": return "T28"
        case "archiveWriteFailed": return "T29"
        case "archiveMissingApp": return "T30"
        case "unknownAccountFailure": return "T31"
        case "anisetteIdentityStateInvalid": return "T32"
        default: return nil
        }
    }
}
extension CombinedFailure.Stage {
    fileprivate var diagnosticToken: String {
        switch self {
        case .hostContainer: return "HOST"
        case .storagePreparation: return "STORE"
        case .bookmarkCreation: return "BOOK"
        case .extensionDiscovery: return "DISC"
        case .extensionLaunch: return "LAUNCH"
        case .xpcConnection: return "XPC"
        case .serviceReadiness: return "READY"
        case .command: return "CMD"
        case .authentication: return "AUTH"
        case .provisioning: return "PROV"
        case .signing: return "SIGN"
        case .filePreparation: return "IPA"
        case .installation: return "INSTALL"
        case .persistence: return "SAVE"
        case .refreshVerification: return "VERIFY"
        case .replyEncoding: return "REPLY"
        case .endpointSelection: return "ENDPOINT"
        case .heartbeat: return "HEART"
        case .coreDevice: return "CORE"
        case .cdTunnel: return "TUNNEL"
        case .rsdDiscovery: return "RSD"
        case .rsdService: return "SERVICE"
        case .lockdownConnection: return "LOCK"
        case .uniqueDeviceID: return "UDID"
        case .pairing: return "PAIR"
        case .network: return "NET"
        case .source: return "SOURCE"
        case .catalog: return "CAT"
        }
    }
}
extension CombinedFailure.Code {
    fileprivate var diagnosticToken: String {
        switch self {
        case .unavailable: return "C01"
        case .invalidConfiguration: return "C02"
        case .permissionDenied: return "C03"
        case .timedOut: return "C04"
        case .cancelled: return "C05"
        case .interrupted: return "C06"
        case .notReady: return "C07"
        case .busy: return "C08"
        case .invalidResponse: return "C09"
        case .unsupported: return "C10"
        case .failed: return "C11"
        case .missingResult: return "C12"
        case .staleResult: return "C13"
        case .invalidToken: return "C14"
        case .missingFile: return "C15"
        case .emptyFile: return "C16"
        case .invalidPackage: return "C17"
        case .fileAccess: return "C18"
        case .stagingFailed: return "C19"
        }
    }
}
extension CombinedFailure.SafeCause {
    fileprivate var diagnosticToken: String {
        switch self {
        case .networkConnectionLost: return "F01"
        case .networkTimedOut: return "F02"
        case .networkUnavailable: return "F03"
        case .anisetteServerUnavailable: return "F04"
        case .anisetteServerRejected: return "F05"
        case .anisetteRequestTimedOut: return "F06"
        case .anisetteRateLimited: return "F07"
        case .anisetteInvalidResponse: return "F08"
        case .anisetteUnknownFailure: return "F09"
        case .signingNetworkConnectionLost: return "F10"
        case .signingNetworkTimedOut: return "F11"
        case .signingNetworkUnavailable: return "F12"
        case .developerPortalRejectedRequest: return "F13"
        case .appIDLimitReached: return "F14"
        case .developerPortalInvalidResponse: return "F15"
        case .provisioningProfileUnavailable: return "F16"
        case .certificateUnavailable: return "F17"
        case .signingStorageUnverified: return "F18"
        case .wifiUnavailable: return "F19"
        case .localDevVPNUnavailable: return "F20"
        case .unknownSigningCause: return "F21"
        case .sourceNetworkFailure: return "F22"
        case .sourceInvalidManifest: return "F23"
        case .sourcePersistenceUnverified: return "F24"
        case .sourceInvalidURL: return "F25"
        case .sourceBlocked: return "F26"
        case .sourceChangedID: return "F27"
        case .sourceDuplicate: return "F28"
        case .sourceUnsupported: return "F29"
        case .sourceValidationFailed: return "F30"
        case .sourceRemoveFailed: return "F31"
        case .sourceRemoveBusy: return "F32"
        case .sourceAddBusy: return "F33"
        case .operationInProgress: return "F34"
        case .responseCapacityUnavailable: return "F35"
        case .sharedStoreUnavailable: return "F36"
        case .secretHandoffUnavailable: return "F37"
        case .staleRefreshAttempt: return "F38"
        case .knownSourcePolicyNetworkFailure: return "F39"
        case .knownSourcePolicyInvalidResponse: return "F40"
        case .catalogUnavailable: return "F41"
        case .catalogSourceUnavailable: return "F42"
        case .responseEncodingFailed: return "F43"
        case .responseTooLarge: return "F44"
        case .pairingRequired: return "F45"
        case .invalidPairingFile: return "F46"
        case .pairingFilePreparationFailed: return "F47"
        case .authAttemptNotDispatched: return "F48"
        case .authProvisioningRetryNotDispatched: return "F49"
        case .authSessionUnavailable: return "F50"
        case .authResponseCapacityUnavailable: return "F51"
        case .credentialCommitFailed: return "F52"
        case .credentialCommitOutcomeUnknown: return "F53"
        case .accountActivationFailed: return "F54"
        case .provisioningStorageFailed: return "F55"
        case .keychainSignOutFailed: return "F56"
        case .keychainSignOutOutcomeUnknown: return "F57"
        case .operationPersistenceFailed: return "F58"
        case .recoveryMalformedRecord: return "F59"
        case .recoveryIncompatibleRecord: return "F60"
        case .recoveryStorageUnavailable: return "F61"
        case .recoveryLockUnavailable: return "F62"
        case .recoveryReadFailure: return "F63"
        case .recoveryDeleteFailure: return "F64"
        }
    }
}
extension CombinedFailure.SourceStep {
    fileprivate var diagnosticToken: String {
        switch self {
        case .authenticate: return "S01"
        case .anisetteFetch: return "S02"
        case .appleAuthentication: return "S03"
        case .accountLookup: return "S04"
        case .credentialCommit: return "S05"
        case .fetchTeams: return "S06"
        case .saveAccount: return "S07"
        case .fetchCertificate: return "S08"
        case .activateCertificate: return "S09"
        case .registerDevice: return "S10"
        case .activateAccount: return "S11"
        case .provisioningUnknown: return "S12"
        case .provisioningProfileFetch: return "S13"
        case .certificateValidation: return "S14"
        case .localCodeSigning: return "S15"
        case .appIDLookup: return "S16"
        case .appIDRegistration: return "S17"
        case .appIDCapabilitiesUpdate: return "S18"
        case .appGroupLookup: return "S19"
        case .appGroupRegistration: return "S20"
        case .appGroupAssignment: return "S21"
        case .provisioningProfileRetrieval: return "S22"
        case .provisioningProfileCreation: return "S23"
        case .provisioningProfileUpdate: return "S24"
        case .sourceDownload: return "S25"
        case .manifestParsing: return "S26"
        case .sourceValidation: return "S27"
        case .knownSourcePolicyFetch: return "S28"
        case .knownSourcePolicyParsing: return "S29"
        case .catalogRead: return "S30"
        }
    }
}
extension CombinedFailure.LaunchContext.Step {
    fileprivate var diagnosticToken: String {
        switch self {
        case .hostBundleUnavailable: return "L01"
        case .missingPluginDirectory: return "L02"
        case .liveProcessBundleMissing: return "L03"
        case .liveProcessBundleUnreadable: return "L04"
        case .bundleIdentifierMissing: return "L05"
        case .executableMetadataMissing: return "L06"
        case .executableFileMissing: return "L07"
        case .extensionFactory: return "L08"
        case .extensionFactoryNil: return "L09"
        case .listenerCreation: return "L10"
        case .requestCallbackNoIdentifier: return "L11"
        case .requestCancellation: return "L12"
        case .requestInterruption: return "L13"
        case .requestCallbackError: return "L14"
        case .processIdentifierUnavailable: return "L15"
        case .xpcRemoteObjectError: return "L16"
        case .xpcInvalidation: return "L17"
        case .xpcPeerRejected: return "L18"
        case .readinessProbe: return "L19"
        case .startupTimeout: return "L20"
        case .connectionStopped: return "L21"
        case .unknown: return "L22"
        }
    }
}

// These diagnostic APIs are consumed by the separate LiveContainer app module
// through SideStoreSupport. Keep implementation-only helpers internal.
// Public build provenance only. Reject unexpected metadata rather than copying
// arbitrary Info.plist values into a diagnostic payload.
public enum V3DiagnosticBuild {
    public static var commit: String { validatedCommit(Bundle.main.object(forInfoDictionaryKey: "LCBuilderCommit")) }
    static func validatedCommit(_ value: Any?) -> String {
        guard let value = value as? String, value.utf8.count == 40,
              value.range(of: "^[0-9a-fA-F]{40}$", options: .regularExpression) != nil else { return "unknown" }
        return value.lowercased()
    }
}

// Local UI conditions can accompany a more specific underlying failure. Copy
// both classifications without copying message prose or guessing its cause.
public enum V3DiagnosticCopy {
    private static let localCodes: Set<String> = [
        "SS-PROV-D099",
        "SS-PROV-D100",
        "SS-PROV-D101",
        "SS-PROV-D102",
        "SS-PROV-D103",
        "SS-PROV-D104",
        "SS-PROV-D105",
        "SS-PROV-D106",
        "SS-PROV-D107",
        "SS-REFRESH-UNKNOWN", "SS-OPERATION-UNKNOWN", "SS-UI-UNKNOWN",
        "SS-AUTH-D024",
        "SS-AUTH-D032",
        "SS-AUTH-D033",
        "SS-AUTH-D034",
        "SS-AUTH-D035",
        "SS-AUTH-D036",
        "SS-AUTH-D037",
        "SS-AUTH-D038",
        "SS-AUTH-D039",
        "SS-AUTH-D040",
        "SS-AUTH-D041",
        "SS-AUTH-D060",
        "SS-AUTH-D069",
        "SS-AUTH-D070",
        "SS-AUTH-D071",
        "SS-AUTH-D072",
        "SS-AUTH-D073",
        "SS-AUTH-D074",
        "SS-AUTH-D075",
        "SS-AUTH-D076",
        "SS-AUTH-D077",
        "SS-AUTH-D078",
        "SS-AUTH-D079",
        "SS-AUTH-D080",
        "SS-AUTH-D081",
        "SS-AUTH-D082",
        "SS-AUTH-D083",
        "SS-AUTH-D089",
        "SS-AUTH-D092",
        "SS-AUTH-D093",
        "SS-AUTH-D094",
        "SS-AUTH-D095",
        "SS-CAT-D001",
        "SS-CAT-D017",
        "SS-CMD-D002",
        "SS-CMD-D004",
        "SS-CMD-D009",
        "SS-CMD-D010",
        "SS-CMD-D012",
        "SS-CMD-D013",
        "SS-CMD-D014",
        "SS-CMD-D015",
        "SS-CMD-D016",
        "SS-CMD-D019",
        "SS-CMD-D020",
        "SS-CMD-D021",
        "SS-CMD-D022",
        "SS-CMD-D023",
        "SS-CMD-D026",
        "SS-CMD-D027",
        "SS-CMD-D029",
        "SS-CMD-D045",
        "SS-CMD-D047",
        "SS-CMD-D050",
        "SS-CMD-D051",
        "SS-CMD-D055",
        "SS-CMD-D056",
        "SS-CMD-D064",
        "SS-CMD-D065",
        "SS-CMD-D066",
        "SS-CMD-D067",
        "SS-CMD-D068",
        "SS-CMD-D084",
        "SS-CMD-D085",
        "SS-CMD-D087",
        "SS-CMD-D088",
        "SS-IPA-D006",
        "SS-IPA-D007",
        "SS-IPA-D008",
        "SS-IPA-D011",
        "SS-NET-D061",
        "SS-NET-D096",
        "SS-PAIR-D043",
        "SS-READY-D005",
        "SS-SAVE-D018",
        "SS-SAVE-D030",
        "SS-SAVE-D031",
        "SS-SAVE-D042",
        "SS-SAVE-D059",
        "SS-SAVE-D086",
        "SS-SAVE-D090",
        "SS-SAVE-D091",
        "SS-SIGN-D097",
        "SS-SOURCE-D025",
        "SS-VERIFY-D003",
        "SS-VERIFY-D044",
        "SS-VERIFY-D046",
        "SS-VERIFY-D048",
        "SS-VERIFY-D049",
        "SS-VERIFY-D052",
        "SS-VERIFY-D053",
        "SS-VERIFY-D054",
        "SS-VERIFY-D057",
        "SS-VERIFY-D058",
        "SS-VERIFY-D062",
        "SS-VERIFY-D063",
        "SS-VERIFY-D098",
        "SS-XPC-D028",
    ]
    public static func details(visibleMessage: String, technical: String) -> String {
        let line = visibleMessage.components(separatedBy: "\n").last ?? ""
        let prefix = "Error ID: "
        let value = line.hasPrefix(prefix) ? String(line.dropFirst(prefix.count)) : ""
        let labels = localCodes.contains(value) ? "visible_error_id=\(value)" : ""
        let build = technical.contains("builder_commit=") ? "" : "builder_commit=\(V3DiagnosticBuild.commit)\n"
        return build + (labels.isEmpty ? "" : labels + "\n") + technical
    }
}

// Historical/plain messages have no recoverable typed cause. This fallback
// identifies only the known presentation flow and leaves original text intact.
public enum V3DiagnosticPresentation {
    public enum Context: String {
        case refresh = "SS-REFRESH-UNKNOWN"
        case operation = "SS-OPERATION-UNKNOWN"
        case global = "SS-UI-UNKNOWN"
    }
    public static func label(_ message: String, context: Context) -> String {
        guard !message.contains("\nError ID: SS-") else { return message }
        return message + "\nError ID: " + context.rawValue
    }
}
import Foundation
#if canImport(Darwin)
import Darwin
#endif

/// The one runtime App Group identity used by every cross-process reader,
/// writer and lock in the combined build: IPA staging, the secret handoff
/// Keychain transaction lock, the service Keychain migration lock, the
/// operation recovery journal, and the cross-process refresh store.
///
/// LiveProcess publishes the group it validated from the host launch payload
/// and the host publishes the same key for itself, so the host and the service
/// resolve one identifier without sharing a symbol across targets. A packaged
/// Info.plist entitlement is only the fallback for a launch that published
/// nothing at all.
///
/// LC_APP_GROUP_RULE_SET_V1 in scripts/templates/LCAppGroupIdentityRules.h is
/// the same rule set in plain C, so it can be executed by a behavioral harness
/// on any toolchain. The two implementations cannot share a header across
/// targets; tests/test_v3_shared_app_group.py executes the C rules and fails
/// when this file drifts from them. Change both together.
enum V3SharedAppGroup {
    /// LC_RULE_PACKAGED_FALLBACK_ONLY: the packaged SideStore group, including
    /// the team-suffixed variants a re-signer writes, ranks first when no
    /// runtime group was published.
    static let packagedGroup = "group.com.SideStore.SideStore"
    /// LiveProcess validates the host-selected group against its own sandbox
    /// and publishes it here. The host publishes the same key for itself.
    static let runtimeGroupEnvironmentKey = "LC_V3_INHERITED_APP_GROUP"
    /// LC_RULE_GROUP_BOUNDED_LENGTH
    static let maximumIdentifierLength = 255

    enum Source: String, Equatable {
        /// The caller passed its own selected group.
        case supplied
        /// The group published by the host for this process.
        case inherited
        /// No runtime group was published; a packaged entitlement was used.
        case packaged
    }

    struct Identity: Equatable {
        let identifier: String
        let containerRoot: URL
        let source: Source
    }

    /// A typed, recoverable failure. Shared state is never substituted with a
    /// process-local store to hide this. The description is a defined safe
    /// sentence, never a provider string and never a private path.
    enum Unavailable: Error, Equatable, LocalizedError {
        case sharedStore

        var isRecoverable: Bool { true }
        var errorDescription: String? {
            "LiveContainer could not open the shared store it uses with the embedded SideStore service."
        }
    }

    /// LC_RULE_GROUP_VISIBLE_ASCII, LC_RULE_GROUP_NO_SEPARATOR,
    /// LC_RULE_GROUP_NO_COLON, LC_RULE_GROUP_NO_TRAVERSAL,
    /// LC_RULE_GROUP_BOUNDED_LENGTH. An App Group identifier is never a path
    /// and never an unbounded string, whatever produced it.
    static func wellFormedIdentifier(_ candidate: String?) -> String? {
        guard let candidate, !candidate.isEmpty,
              candidate.utf8.count <= maximumIdentifierLength else { return nil }
        var previous: UInt8 = 0
        for byte in candidate.utf8 {
            guard byte >= 0x21, byte <= 0x7E,
                  byte != UInt8(ascii: "/"), byte != UInt8(ascii: "\\"),
                  byte != UInt8(ascii: ":") else { return nil }
            if previous == UInt8(ascii: ".") && byte == UInt8(ascii: ".") { return nil }
            previous = byte
        }
        return candidate.utf8.first == UInt8(ascii: ".") ? nil : candidate
    }

    static func isPackagedSideStoreGroup(_ group: String) -> Bool {
        // The plain packaged name ranks as itself. Without this early return the
        // suffix below would be taken from a string one character longer than
        // this one, and the exact name would rank as an ordinary entry, putting
        // a foreign group ahead of the packaged one.
        if group == packagedGroup { return true }
        guard group.hasPrefix(packagedGroup + ".") else { return false }
        let suffix = group.dropFirst(packagedGroup.count + 1)
        return !suffix.isEmpty && suffix.utf8.allSatisfy {
            (UInt8(ascii: "0")...UInt8(ascii: "9")).contains($0) ||
                (UInt8(ascii: "A")...UInt8(ascii: "Z")).contains($0) ||
                (UInt8(ascii: "a")...UInt8(ascii: "z")).contains($0)
        }
    }

    static func environmentGroup() -> String? {
        #if canImport(Darwin)
        guard let value = getenv(runtimeGroupEnvironmentKey) else { return nil }
        return String(cString: value)
        #else
        return nil
        #endif
    }

    /// Publish this process's own selection so the embedded service resolves the
    /// identical group. Only a group this process can actually open is published:
    /// if the service could not open what the host published, it would clear the
    /// key and choose its own packaged fallback, which is the split this exists to
    /// prevent. Publishing nothing leaves both processes on their packaged
    /// fallback, which LCAppGroupOrderPackaged ranks identically and which the
    /// packaging verifier constrains to groups both processes are entitled for.
    static func publishRuntimeGroup(_ group: String?) {
        #if canImport(Darwin)
        unsetenv(runtimeGroupEnvironmentKey)
        guard let resolved = runtimeIdentity(selectedGroup: group)?.identifier,
              let bytes = resolved.cString(using: .utf8) else { return }
        setenv(runtimeGroupEnvironmentKey, bytes, 1)
        #endif
    }

    /// Resolve the one authoritative identity.
    ///
    /// LC_RULE_EXPLICIT_WINS: a supplied or inherited runtime group is
    /// authoritative for its own name. A legitimate AltStore-owned group that
    /// LiveContainer selected is accepted; it is not rejected for lacking the
    /// SideStore name.
    /// LC_RULE_EXPLICIT_FAIL_CLOSED: if that group is malformed or cannot be
    /// opened, this returns nil. Falling back to the packaged entitlement would
    /// move the shared store underneath the other process.
    /// LC_RULE_PACKAGED_FALLBACK_ONLY: with no runtime group at all, the
    /// packaged entitlement is the only fallback.
    /// The platform's own answer to "can this process open that group".
    /// Production leaves this at `.default`. The behavioral harnesses substitute
    /// one, because a macOS runner has no App Group entitlement and would
    /// otherwise resolve every group as unavailable and be unable to exercise
    /// any of the code that depends on the shared store actually existing.
    static var containerFileManager: FileManager = .default

    static func identity(selectedGroup: String? = nil,
                         inheritedGroup: String? = nil,
                         usesEnvironment: Bool = true,
                         bundleInfo: [String: Any],
                         resolveContainer: (String) -> URL?) -> Identity? {
        let supplied = selectedGroup.flatMap { $0.isEmpty ? nil : $0 }
        let inherited = inheritedGroup ?? (usesEnvironment ? environmentGroup() : nil)
        if let authoritative = supplied ?? inherited {
            guard let identifier = wellFormedIdentifier(authoritative),
                  let containerRoot = resolveContainer(identifier) else { return nil }
            return Identity(identifier: identifier, containerRoot: containerRoot,
                            source: supplied != nil ? .supplied : .inherited)
        }
        let configured = (bundleInfo["ALTAppGroups"] as? [String]) ??
            (bundleInfo["ALTAppGroups"] as? String).map { [$0] } ?? []
        let wellFormed = configured.compactMap(wellFormedIdentifier)
        // LC_RULE_PACKAGED_FALLBACK_ONLY, in the same two steps the C rule set
        // uses: the rule set's order, then the first entry this process can
        // actually open. A packaged list is a preference, not proof of
        // entitlement, so an unopenable top entry falls through to the next one.
        let ordered = wellFormed.filter(isPackagedSideStoreGroup) +
            wellFormed.filter { !isPackagedSideStoreGroup($0) }
        for identifier in ordered {
            if let containerRoot = resolveContainer(identifier) {
                return Identity(identifier: identifier, containerRoot: containerRoot, source: .packaged)
            }
        }
        return nil
    }

    static func runtimeIdentity(selectedGroup: String? = nil, bundle: Bundle = .main,
                                fileManager: FileManager? = nil) -> Identity? {
        let resolver = fileManager ?? containerFileManager
        return identity(selectedGroup: selectedGroup, bundleInfo: bundle.infoDictionary ?? [:]) {
            resolver.containerURL(forSecurityApplicationGroupIdentifier: $0)
        }
    }

    /// The cross-process UserDefaults suite for this runtime group. Returns nil
    /// rather than a process-local store: a caller that needs shared state must
    /// produce a typed recoverable failure rather than silently writing to a
    /// private store the other process cannot read.
    static func sharedUserDefaults(selectedGroup: String? = nil, bundle: Bundle = .main) -> UserDefaults? {
        guard let identity = runtimeIdentity(selectedGroup: selectedGroup, bundle: bundle) else { return nil }
        return UserDefaults(suiteName: identity.identifier)
    }

    static func requireSharedUserDefaults(selectedGroup: String? = nil,
                                          bundle: Bundle = .main) throws -> UserDefaults {
        guard let shared = sharedUserDefaults(selectedGroup: selectedGroup, bundle: bundle) else {
            throw Unavailable.sharedStore
        }
        return shared
    }

    /// A private store used only when no shared store exists, so a failing launch
    /// can still render without its process-local values being mistaken for the
    /// cross-process state they stand in for. A unique suite name cannot collide
    /// with a real store and no other process can open it, so it is never an App
    /// Group suite. Callers must still refuse to run cross-process work while the
    /// shared store is unavailable, which is what `requireSharedStore` and
    /// `requireSharedUserDefaults` are for.
    ///
    /// The trailing `.standard` is an absolute last resort for the case where even
    /// a unique suite cannot be created. It is not a supported state and nothing
    /// treats it as a shared store.
    static func quarantinedUserDefaults() -> UserDefaults {
        let unique = "com.kdt.livecontainer.v3.quarantined-shared-store.\(UUID().uuidString)"
        return UserDefaults(suiteName: unique) ?? UserDefaults.standard
    }
}

/// The one cross-process refresh store: the host scheduler, the refresh settings
/// screen, the host Home banner and the Setup assistant all read and write these
/// keys, and the embedded service and the background run read and write the same
/// ones. It is deliberately not MainActor-isolated so SwiftUI property wrappers
/// can bind to it during view construction.
enum V3SharedRefreshStore {
    static let isAvailable = V3SharedAppGroup.sharedUserDefaults() != nil
    static let defaults: UserDefaults = V3SharedAppGroup.sharedUserDefaults()
        ?? V3SharedAppGroup.quarantinedUserDefaults()
    static let unavailableMessage = "LiveContainer could not open its shared refresh store, so scheduled refresh state is unavailable in this launch. Refresh All still works." + "\nError ID: SS-SAVE-D059"
}
import Foundation

// LC_SERVICE_CONNECTION_V1: executable, injectable startup state machine; no refresh/signing API.
@MainActor
final class CombinedServiceConnection {
    struct Dependencies {
        var resolveHost: () throws -> URL
        var prepareStorage: (URL) throws -> URL
        var createBookmark: (URL) throws -> Data
        var discoverExtension: () throws -> Void
        var launch: (UUID, Data) throws -> Void
        var retire: (UUID) -> Void
    }
    enum Signal { case launched, connected, ready }
    private let dependencies: Dependencies
    private let timeout: TimeInterval
    private var waiters: [UUID: CheckedContinuation<Void, Error>] = [:]
    private var deadline: Task<Void, Never>?
    private(set) var attemptID: UUID?
    private(set) var isReady = false
    private(set) var stage: CombinedFailure.Stage = .hostContainer
    private var launched = false, connected = false, ready = false
    var waitingCount: Int { waiters.count }
    var onFailure: ((CombinedFailure) -> Void)?
    init(dependencies: Dependencies, timeout: TimeInterval = 45) { self.dependencies = dependencies; self.timeout = timeout }
    func ensureConnected() async throws {
        try Task.checkCancellation()
        if isReady { return }
        let waiter = UUID()
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                if Task.isCancelled { continuation.resume(throwing: CancellationError()); return }
                waiters[waiter] = continuation
                if attemptID == nil { begin() }
            }
        }, onCancel: { Task { @MainActor in self.cancel(waiter) } })
    }
    private func begin() {
        let id = UUID()
        attemptID = id; launched = false; connected = false; ready = false; isReady = false
        do {
            stage = .hostContainer
            let host = try dependencies.resolveHost()
            stage = .storagePreparation
            let storage = try dependencies.prepareStorage(host)
            stage = .bookmarkCreation
            let bookmark = try dependencies.createBookmark(storage)
            stage = .extensionDiscovery
            try dependencies.discoverExtension()
            stage = .extensionLaunch
            deadline = Task { @MainActor in
                do { try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000)) } catch { return }
                self.fail(id, CombinedFailure(operation: "connect", stage: self.stage, code: .timedOut, id: id.uuidString, retryable: true))
            }
            try dependencies.launch(id, bookmark)
        } catch {
            if let known = error as? CombinedFailure {
                fail(id, known)
            } else {
                fail(id, CombinedFailure.capture(error, operation: "connect", stage: stage, id: id.uuidString),
                    launchSourceError: error)
            }
        }
    }
    func signal(_ signal: Signal, attempt id: UUID) {
        guard attemptID == id else { return }
        switch signal {
        case .launched: launched = true
        case .connected: connected = true
        case .ready: ready = true
        }
        stage = !launched ? .extensionLaunch : !connected ? .xpcConnection : .serviceReadiness
        if launched && connected && ready {
            isReady = true; deadline?.cancel(); deadline = nil
            let all = Array(waiters.values); waiters.removeAll()
            all.forEach { $0.resume() }
        }
    }
    func fail(_ id: UUID, _ error: CombinedFailure, launchSourceError: Error? = nil,
              launchSourceStep: CombinedFailure.LaunchContext.Step? = nil) {
        guard attemptID == id else { return }
        let launchStages: Set<CombinedFailure.Stage> = [.extensionDiscovery, .extensionLaunch, .xpcConnection, .serviceReadiness]
        let context: CombinedFailure.LaunchContext?
        if let launchSourceStep {
            context = CombinedFailure.LaunchContext(error: launchSourceError,
                sourceStep: launchSourceStep,
                requestIdentifierObserved: launched ? true : nil,
                pidObserved: launched ? true : nil,
                xpcAccepted: connected ? true : nil,
                applicationReadyObserved: ready ? true : nil)
        } else if error.launchContext == nil, error.operation == "connect", launchStages.contains(error.stage) {
            let source: CombinedFailure.LaunchContext.Step = error.code == .timedOut ? .startupTimeout
                : (error.code == .cancelled || error.code == .interrupted) ? .connectionStopped : .unknown
            context = CombinedFailure.LaunchContext(error: launchSourceError ?? error,
                sourceStep: source,
                requestIdentifierObserved: launched ? true : nil,
                pidObserved: launched ? true : nil,
                xpcAccepted: connected ? true : nil,
                applicationReadyObserved: ready ? true : nil)
        } else {
            context = nil
        }
        let failure = CombinedFailure.preserving(error, operation: error.operation, stage: error.stage,
            code: error.code, id: error.correlationID, retryable: error.retryable,
            launchContext: context)
        attemptID = nil; isReady = false; deadline?.cancel(); deadline = nil
        let all = Array(waiters.values); waiters.removeAll()
        dependencies.retire(id)
        all.forEach { $0.resume(throwing: failure) }
        onFailure?(failure)
    }
    func stop(code: CombinedFailure.Code = .interrupted) {
        guard let id = attemptID else { return }
        fail(id, CombinedFailure(operation: "connect", stage: stage, code: code, id: id.uuidString, retryable: true))
    }
    private func cancel(_ waiter: UUID) {
        waiters.removeValue(forKey: waiter)?.resume(throwing: CancellationError())
        if waiters.isEmpty && !isReady { stop(code: .cancelled) }
    }
    static func resolveHost(_ value: String?, fileManager: FileManager = .default) throws -> URL {
        guard let value, !value.isEmpty, value.hasPrefix("/"), !value.contains("\0"), value != "/",
              !value.split(separator: "/").contains(where: { $0 == "." || $0 == ".." }) else {
            throw NSError(domain: NSCocoaErrorDomain, code: NSFileReadInvalidFileNameError)
        }
        let home = URL(fileURLWithPath: value, isDirectory: true).standardizedFileURL
        guard home.path != "/" else { throw NSError(domain: NSCocoaErrorDomain, code: NSFileReadInvalidFileNameError) }
        var directory: ObjCBool = false
        guard fileManager.fileExists(atPath: home.path, isDirectory: &directory), directory.boolValue else {
            throw NSError(domain: NSCocoaErrorDomain, code: NSFileNoSuchFileError)
        }
        return home
    }
}
// LC_SERVICE_CONNECTION_V1: platform adapter, with explicit refresh compatibility entry points.
enum V3ServiceReadinessProbeState: Equatable {
    case pending
    case ready
    case invalid
    case failed
    case timedOut

    static func resolve(ready: Bool, invalid: Bool, hasTerminalFailure: Bool,
                        expired: Bool) -> V3ServiceReadinessProbeState {
        if ready { return .ready }
        if invalid { return .invalid }
        if hasTerminalFailure { return .failed }
        return expired ? .timedOut : .pending
    }

    @MainActor
    static func recheckAfterYield(ready: @MainActor () -> Bool,
                                  invalid: @MainActor () -> Bool,
                                  hasTerminalFailure: @MainActor () -> Bool) async -> V3ServiceReadinessProbeState {
        await Task.yield()
        return resolve(ready: ready(), invalid: invalid(),
            hasTerminalFailure: hasTerminalFailure(), expired: true)
    }
}

extension V3ServiceReadinessFailure {
    func combinedFailure(id: String, operation overrideOperation: String? = nil) -> CombinedFailure {
        guard let resolvedStage = CombinedFailure.Stage(rawValue: stage),
              let resolvedCode = CombinedFailure.Code(rawValue: code),
              let validatedContext = CombinedFailure.validatedSigningContext(signingContext) else {
            return CombinedFailure(operation: "connect", stage: .serviceReadiness,
                code: .invalidResponse, id: id)
        }
        let resolvedCause = safeCause.flatMap(CombinedFailure.SafeCause.init(rawValue:))
        let resolvedStep = sourceStep.flatMap(CombinedFailure.SourceStep.init(rawValue:))
        return CombinedFailure(operation: overrideOperation ?? operation, stage: resolvedStage, code: resolvedCode, id: id,
            underlying: NSError(domain: underlyingDomain, code: underlyingCode), retryable: retryable,
            safeCause: resolvedCause, sourceStep: resolvedStep, signingContext: validatedContext)
    }
}

struct V3ServiceReadinessBackoff {
    private(set) var delay: TimeInterval = 0.2
    static let maximumDelay: TimeInterval = 1.0

    mutating func nextDelay(remaining: TimeInterval) -> TimeInterval? {
        guard remaining.isFinite, remaining > 0 else { return nil }
        let result = min(delay, remaining)
        delay = min(delay * 2, Self.maximumDelay)
        return result
    }
}

enum V3RefreshAdmissionFailureResolution: Equatable {
    case releaseNotDispatched
    case releaseTerminalFailure
    case retainUnknownOutcome

    static func resolve(runID: String, dispatchedRunID: String?, terminalCallbackRunID: String?) -> Self {
        guard dispatchedRunID == runID else { return .releaseNotDispatched }
        return terminalCallbackRunID == runID ? .releaseTerminalFailure : .retainUnknownOutcome
    }
}

@MainActor
class RefreshHandler: NSObject {
    static let shared = RefreshHandler()
    var progress: Progress?
    var sideStorePid: Int32 = 0
    var client: RefreshClient?
    var v3RefreshToken: UUID?
    var v3RefreshAdmissionRunID: String?
    var v3RefreshDispatchedRunID: String?
    private var v3RefreshTerminalCallbackRunID: String?
    private var extensionProcess: NSExtension?
    private var listener: NSXPCListener?
    private var connection: NSXPCConnection?
    private var pendingPeerConnections: [NSXPCConnection] = []
    private var launchID: UUID?
    private var refreshRunID: String?
    private var refreshContinuation: CheckedContinuation<Void, Error>?
    private var readinessTask: Task<Void, Never>?
    private var retiringProcess: NSExtension?
    private var retiringPID: Int32 = 0
    private var launchRequestPending: UUID?
    private var retiringRequestPending: UUID?
    private var launchRequestIdentifierObserved: Bool?
    private var launchPIDObserved: Bool?
    private var launchXPCAccepted: Bool?
    private var launchApplicationReadyObserved: Bool?
    private var launchPeerPIDRejected: Bool?
    private lazy var service: CombinedServiceConnection = CombinedServiceConnection(dependencies: .init(
        resolveHost: {
            guard !UserDefaults.isSideStore(), !UserDefaults.isLiveProcess() else {
                throw NSError(domain: NSCocoaErrorDomain, code: NSFileReadNoPermissionError)
            }
            let value = getenv("LC_HOME_PATH").flatMap { String(validatingUTF8: $0) }
            return try CombinedServiceConnection.resolveHost(value)
        },
        prepareStorage: { host in
            let storage = host.appendingPathComponent("Documents/SideStore", isDirectory: true)
            var error: NSError?
            guard LCPrepareServiceStorage(storage, &error) else {
                throw error ?? NSError(domain: NSCocoaErrorDomain, code: NSFileWriteUnknownError)
            }
            return storage
        },
        createBookmark: { storage in
            var error: NSError?
            guard let data = LCCreateServiceBookmark(storage, &error) else {
                throw error ?? NSError(domain: NSCocoaErrorDomain, code: NSFileWriteUnknownError)
            }
            return data
        },
        discoverExtension: { [unowned self] in try self.discoverExtension() },
        launch: { [unowned self] id, bookmark in try self.launchEmbeddedSideStore(id: id, bookmark: bookmark) },
        retire: { [unowned self] id in self.retire(id) }))

    func ensureServiceConnected() async throws {
        // A cancelled begin-request may still call back with a newly launched process.
        // Do not open a second database owner while that launch remains unresolved.
        if retiringRequestPending != nil {
            let until = Date().addingTimeInterval(3)
            while retiringRequestPending != nil && Date() < until {
                try Task.checkCancellation()
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            guard retiringRequestPending == nil else {
                throw CombinedFailure(operation: "connect", stage: .extensionLaunch, code: .busy, id: UUID().uuidString)
            }
        }
        if retiringPID > 0 {
            let until = Date().addingTimeInterval(3)
            while getpgid(retiringPID) > 0 && Date() < until {
                try Task.checkCancellation()
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            if getpgid(retiringPID) > 0 {
                retiringProcess?._kill(9)
                throw CombinedFailure(operation: "connect", stage: .extensionLaunch, code: .busy, id: UUID().uuidString, retryable: true)
            }
            retiringPID = 0; retiringProcess = nil
        }
        if service.isReady && (sideStorePid <= 0 || getpgid(sideStorePid) <= 0) { service.stop() }
        try await service.ensureConnected()
    }
    private func discoverExtension() throws {
        let id = service.attemptID?.uuidString ?? UUID().uuidString
        guard let bundle = UserDefaults.lcMainBundle() else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .hostBundleUnavailable, retryable: false)
        }
        guard let pluginsURL = bundle.builtInPlugInsURL else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .missingPluginDirectory, retryable: false)
        }
        let url = pluginsURL.appendingPathComponent("LiveProcess.appex", isDirectory: true)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .liveProcessBundleMissing, retryable: false)
        }
        guard let liveProcess = Bundle(url: url) else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .liveProcessBundleUnreadable, retryable: false)
        }
        guard let identifier = liveProcess.bundleIdentifier else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .bundleIdentifierMissing, retryable: false)
        }
        guard let executable = liveProcess.executableURL else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .executableMetadataMissing, retryable: false)
        }
        guard FileManager.default.fileExists(atPath: executable.path) else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unavailable,
                id: id, sourceStep: .executableFileMissing, retryable: false)
        }
        do {
            extensionProcess = try NSExtension(identifier: identifier)
        } catch {
            throw CombinedFailure.LaunchContext.launchFailure(error, stage: .extensionDiscovery,
                id: id, sourceStep: .extensionFactory, retryable: false)
        }
        guard extensionProcess != nil else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .extensionDiscovery, code: .unsupported,
                id: id, sourceStep: .extensionFactoryNil, retryable: false)
        }
    }
    private func launchEmbeddedSideStore(id: UUID, bookmark: Data) throws {
        guard let ext = extensionProcess else { throw NSError(domain: NSCocoaErrorDomain, code: NSFeatureUnsupportedError) }
        launchID = id
        NSLog("[V3_SERVICE_START] PROCESS_LAUNCH_BEGIN id=%@", id.uuidString)
        let callbacks = CombinedServiceCallbacks(owner: self, identity: id)
        guard let listener = startAnonymousListener(callbacks) else {
            throw CombinedFailure.LaunchContext.launchFailure(stage: .xpcConnection, code: .unavailable,
                id: id.uuidString, sourceStep: .listenerCreation, requestIdentifierObserved: false,
                pidObserved: false, xpcAccepted: false, retryable: true)
        }
        self.listener = listener
        let item = NSExtensionItem()
        item.userInfo = V3EmbeddedSideStoreLaunchPayload.userInfo(
            bookmark: bookmark, endpoint: listener.endpoint,
            identity: V3SharedAppGroup.runtimeIdentity())
        ext.setRequestCancellationBlock { [weak self] _, error in
            Task { @MainActor in self?.failed(id, stage: .extensionLaunch, underlying: error,
                launchSourceStep: .requestCancellation) }
        }
        ext.setRequestInterruptionBlock { [weak self] _ in
            Task { @MainActor in self?.failed(id, stage: .extensionLaunch, code: .interrupted,
                launchSourceStep: .requestInterruption) }
        }
        launchRequestIdentifierObserved = nil
        launchPIDObserved = nil
        launchXPCAccepted = nil
        launchApplicationReadyObserved = nil
        launchPeerPIDRejected = nil
        launchRequestPending = id
        LCLaunchServiceExtension(ext, item) { [weak self] uuid, error in
            Task { @MainActor in
                guard let self else { ext._kill(9); return }
                guard self.launchID == id else {
                    if self.retiringRequestPending == id {
                        ext._kill(9)
                        self.retiringRequestPending = nil
                        if let uuid { self.retiringPID = ext.pid(forRequestIdentifier: uuid) }
                    }
                    return
                }
                guard self.launchRequestPending == id else { return }
                self.launchRequestPending = nil
                self.launchRequestIdentifierObserved = uuid != nil
                guard error == nil, let uuid else {
                    let step: CombinedFailure.LaunchContext.Step = uuid == nil ? .requestCallbackNoIdentifier : .requestCallbackError
                    self.failed(id, stage: .extensionLaunch, underlying: error,
                        launchSourceStep: step, requestIdentifierObserved: uuid != nil)
                    return
                }
                let pid = ext.pid(forRequestIdentifier: uuid)
                guard pid > 0 else {
                    self.launchPIDObserved = false
                    self.failed(id, stage: .extensionLaunch, launchSourceStep: .processIdentifierUnavailable,
                        requestIdentifierObserved: true, pidObserved: false)
                    return
                }
                self.sideStorePid = pid
                self.launchPIDObserved = true
                NSLog("[V3_SERVICE_START] PROCESS_LAUNCHED id=%@ pid=%d", id.uuidString, pid)
                self.service.signal(.launched, attempt: id)
                self.confirmLaunchedPeer(id)
            }
        }
    }
    fileprivate func accepted(_ incoming: NSXPCConnection, id: UUID) {
        guard launchID == id, connection == nil else { incoming.invalidate(); return }
        // The endpoint is a private launch capability, but possession alone
        // does not prove that its holder is the extension we launched. Keep
        // incoming connections suspended until NSExtension supplies that PID.
        guard sideStorePid > 0 else {
            guard pendingPeerConnections.count < 8 else { incoming.invalidate(); return }
            pendingPeerConnections.append(incoming)
            return
        }
        guard incoming.processIdentifier == sideStorePid else {
            launchPeerPIDRejected = true
            incoming.invalidate()
            return
        }
        launchXPCAccepted = true
        NSLog("[V3_SERVICE_START] XPC_CONNECTED id=%@", id.uuidString)
        connection = incoming
        incoming.remoteObjectInterface = NSXPCInterface(with: RefreshClient.self)
        client = incoming.remoteObjectProxyWithErrorHandler { [weak self] error in
            Task { @MainActor in self?.failed(id, stage: .xpcConnection, underlying: error,
                launchSourceStep: .xpcRemoteObjectError) }
        } as? RefreshClient
        incoming.invalidationHandler = { [weak self] in Task { @MainActor in self?.failed(id, stage: .xpcConnection,
            code: .interrupted, launchSourceStep: .xpcInvalidation) } }
        incoming.interruptionHandler = incoming.invalidationHandler
        guard client != nil else {
            failed(id, stage: .xpcConnection, launchSourceStep: .xpcRemoteObjectError)
            return
        }
        incoming.resume()
        service.signal(.connected, attempt: id)
    }
    private func confirmLaunchedPeer(_ id: UUID) {
        guard launchID == id, sideStorePid > 0 else { return }
        let candidates = pendingPeerConnections
        pendingPeerConnections.removeAll()
        for candidate in candidates { accepted(candidate, id: id) }
    }
    var v3ServiceIdentity: UUID? {
        service.isReady && connection != nil && sideStorePid > 0 ? launchID : nil
    }
    fileprivate func applicationReady(_ id: UUID) {
        // finishedLaunching may be repeated; one readiness probe owns this launch.
        guard launchID == id, readinessTask == nil else { return }
        launchApplicationReadyObserved = true
        NSLog("[V3_SERVICE_START] APPLICATION_READY id=%@", id.uuidString)
        readinessTask = Task { @MainActor in
            do {
                try await awaitServiceReady(id)
                guard launchID == id else { return }
                service.signal(.ready, attempt: id)
            } catch {
                guard !Task.isCancelled, launchID == id else { return }
                failed(id, stage: .serviceReadiness, underlying: error,
                    launchSourceStep: .readinessProbe)
            }
        }
    }
    private func awaitServiceReady(_ id: UUID) async throws {
        
        let until = Date().addingTimeInterval(30)
        var backoff = V3ServiceReadinessBackoff()
        var ready = false
        var pending = false
        var invalid = false
        var terminalFailure: V3ServiceReadinessFailure?
        while true {
            try Task.checkCancellation()
            guard launchID == id else { throw CancellationError() }
            switch V3ServiceReadinessProbeState.resolve(
                ready: ready, invalid: invalid, hasTerminalFailure: terminalFailure != nil,
                expired: Date() >= until) {
            case .ready:
                NSLog("[V3_SERVICE_START] SNAPSHOT_READY id=%@", id.uuidString)
                return
            case .invalid:
                NSLog("[V3_SERVICE_START] READINESS_INVALID_RESPONSE id=%@", id.uuidString)
                throw CombinedFailure(operation: "connect", stage: .serviceReadiness, code: .invalidResponse, id: id.uuidString)
            case .failed:
                guard let failure = terminalFailure?.combinedFailure(
                        id: refreshRunID ?? id.uuidString,
                        operation: refreshRunID == nil ? nil : "refresh") else {
                    throw CombinedFailure(operation: "connect", stage: .serviceReadiness,
                        code: .invalidResponse, id: id.uuidString)
                }
                throw failure
            case .timedOut:
                switch await V3ServiceReadinessProbeState.recheckAfterYield(
                    ready: { ready }, invalid: { invalid }, hasTerminalFailure: { terminalFailure != nil }) {
                case .ready:
                    NSLog("[V3_SERVICE_START] SNAPSHOT_READY id=%@", id.uuidString)
                    return
                case .invalid:
                    NSLog("[V3_SERVICE_START] READINESS_INVALID_RESPONSE id=%@", id.uuidString)
                    throw CombinedFailure(operation: "connect", stage: .serviceReadiness,
                        code: .invalidResponse, id: id.uuidString)
                case .failed:
                    guard let failure = terminalFailure?.combinedFailure(
                            id: refreshRunID ?? id.uuidString,
                            operation: refreshRunID == nil ? nil : "refresh") else {
                        throw CombinedFailure(operation: "connect", stage: .serviceReadiness,
                            code: .invalidResponse, id: id.uuidString)
                    }
                    throw failure
                case .pending, .timedOut:
                    NSLog("[V3_SERVICE_START] READINESS_TIMEOUT id=%@", id.uuidString)
                    throw CombinedFailure(operation: "connect", stage: .serviceReadiness,
                        code: .timedOut, id: id.uuidString, retryable: true)
                }
            case .pending:
                break
            }
            if !pending, let client {
                let requestID = UUID().uuidString
                let message: [String: Any] = ["version": 1, "id": requestID, "operation": "snapshot", "target": "", "deadline": Date().addingTimeInterval(30), "payload": ["readinessOnly": true]]
                let data = try PropertyListSerialization.data(fromPropertyList: message, format: .binary, options: 0)
                pending = true
                client.v3Execute(data) { response in
                    Task { @MainActor in
                        guard self.launchID == id else { return }
                        pending = false
                        switch V3ServiceReadinessReply.decode(response, requestID: requestID) {
                        case .invalid: invalid = true
                        case .notReady: break
                        case .failed(let failure): terminalFailure = failure
                        case .ready: ready = true
                        }
                    }
                }
            }
            guard let delay = backoff.nextDelay(remaining: until.timeIntervalSinceNow) else { continue }
            try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        }

    }
    fileprivate func failed(_ id: UUID, stage: CombinedFailure.Stage, code: CombinedFailure.Code = .failed,
                            underlying: Error? = nil, launchSourceStep: CombinedFailure.LaunchContext.Step? = nil,
                            requestIdentifierObserved: Bool? = nil, pidObserved: Bool? = nil) {
        guard launchID == id || service.attemptID == id else { return }
        // Never double-wrap: an already structured failure (e.g. the readiness
        // probe's timedOut/invalidResponse) keeps its stage, code, retryable
        // flag and correlation ID instead of degrading to failed/redacted.
        let context: CombinedFailure.LaunchContext? = (refreshContinuation == nil &&
            [.extensionDiscovery, .extensionLaunch, .xpcConnection, .serviceReadiness].contains(stage))
            ? CombinedFailure.LaunchContext(error: underlying, sourceStep: launchSourceStep ?? .unknown,
                requestIdentifierObserved: requestIdentifierObserved ?? launchRequestIdentifierObserved,
                pidObserved: pidObserved ?? launchPIDObserved, xpcAccepted: launchXPCAccepted,
                applicationReadyObserved: launchApplicationReadyObserved,
                peerPIDRejected: launchPeerPIDRejected) : nil
        let failure = CombinedFailure.preserving(underlying, operation: refreshContinuation == nil ? "connect" : "refresh",
            stage: stage, code: code, id: refreshRunID ?? id.uuidString,
            retryable: refreshContinuation == nil && code == .interrupted ? true : nil,
            launchContext: context)
        NSLog("[V3_SERVICE_START] START_FAILED id=%@ stage=%@ code=%@", id.uuidString, failure.stage.rawValue, failure.code.rawValue)
        finishRefreshContinuation(.failure(failure))
        service.fail(id, failure)
    }
    private func retire(_ id: UUID) {
        guard launchID == id else { return }
        NSLog("[V3_SERVICE_START] PROCESS_EXITED id=%@", id.uuidString)
        launchID = nil
        if launchRequestPending == id { retiringRequestPending = id; launchRequestPending = nil }
        readinessTask?.cancel(); readinessTask = nil
        listener?.invalidate(); listener = nil
        for candidate in pendingPeerConnections { candidate.invalidate() }
        pendingPeerConnections.removeAll()
        connection?.invalidate(); connection = nil; client = nil
        retiringProcess = extensionProcess; retiringPID = sideStorePid
        extensionProcess?._kill(15)
        extensionProcess = nil; sideStorePid = 0
        V3ServiceBridge.shared.disconnected()
    }
    func v3_stopService() {
        let id = refreshRunID ?? UUID().uuidString
        finishRefreshContinuation(.failure(CombinedFailure(operation: "refresh", stage: .command, code: .cancelled, id: id)))
        service.stop(code: .cancelled)
    }

    // Compatibility adapter for existing AppIntents and scheduler ABI. This always means refresh.
    func startRefresh(identifier: String, mangledName: String) async throws {
        try await performRefresh(identifier: identifier, mangledName: mangledName, schedulerRunID: nil)
    }
    func startScheduledRefresh(identifier: String, mangledName: String, runID: String) async throws {
        try await performRefresh(identifier: identifier, mangledName: mangledName, schedulerRunID: runID)
    }
    func performRefresh(identifier: String, mangledName: String) async throws {
        try await performRefresh(identifier: identifier, mangledName: mangledName, schedulerRunID: nil)
    }
    private func performRefresh(identifier: String, mangledName: String,
                                schedulerRunID: String?) async throws {
        guard !identifier.isEmpty, !mangledName.isEmpty else {
            throw CombinedFailure(operation: "refresh", stage: .command, code: .invalidConfiguration, id: UUID().uuidString)
        }
        let previousRefreshRunID = refreshRunID
        refreshRunID = schedulerRunID
        defer {
            if refreshContinuation == nil, refreshRunID == schedulerRunID {
                refreshRunID = previousRefreshRunID
            }
        }
        // V3_RUNTIME_SHARED_REFRESH_STORE_V1: these keys are the host/service
        // refresh contract. They live in the one runtime App Group, never in a
        // fixed suite name and never in a per-process fallback: a store that
        // cannot be opened is a typed recoverable failure, because a private
        // store would strand the run identity the service is about to write.
        // The structured envelope carries the retryable cause, so the refusal
        // reaches the user as a correlated failure rather than an untyped throw.
        let sharedDefaults: UserDefaults
        do {
            sharedDefaults = try V3SharedAppGroup.requireSharedUserDefaults()
        } catch {
            throw CombinedFailure(operation: "refresh", stage: .persistence,
                code: .unavailable, id: schedulerRunID ?? UUID().uuidString,
                retryable: true, safeCause: .sharedStoreUnavailable)
        }
        if schedulerRunID == nil && V3DirectRefreshPreflightPolicy.isBlocked(
            activeRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshActiveRunID"),
            hostHandoffPending: sharedDefaults.bool(forKey: "liveContainerAutoRefreshHostHandoff"),
            uncertainMutationRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshUncertainMutationRunID")) {
            throw CombinedFailure(operation: "refresh", stage: .command, code: .busy,
                id: UUID().uuidString, retryable: true, safeCause: .operationInProgress)
        }
        // Connect and verify service readiness before claiming local mutation
        // state. The authoritative refreshAdmissionBegin request serializes
        // against active service mutations below, so a separate full snapshot
        // here would only duplicate the readiness probe.
        try await ensureServiceConnected()
        
        try Task.checkCancellation()
        guard v3RefreshToken == nil , !V3ServiceBridge.shared.isMutating else {
            throw CombinedFailure(operation: "refresh", stage: .command, code: .busy,
                id: UUID().uuidString, retryable: true, safeCause: .operationInProgress)
        }
        // The connection startup above suspends. Recheck shared scheduler
        // ownership after resuming so a handoff or uncertain mutation created
        // during that await cannot be overwritten by this direct run.
        if schedulerRunID == nil && V3DirectRefreshPreflightPolicy.isBlocked(
            activeRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshActiveRunID"),
            hostHandoffPending: sharedDefaults.bool(forKey: "liveContainerAutoRefreshHostHandoff"),
            uncertainMutationRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshUncertainMutationRunID")) {
            throw CombinedFailure(operation: "refresh", stage: .command, code: .busy,
                id: UUID().uuidString, retryable: true, safeCause: .operationInProgress)
        }
        let token = UUID(); v3RefreshToken = token
        defer { if v3RefreshToken == token { v3RefreshToken = nil } }
        let directClaimID = schedulerRunID == nil ? UUID().uuidString : nil
        if let directClaimID {
            let existingClaim = sharedDefaults.dictionary(forKey: V3DirectRefreshRunClaimPolicy.defaultsKey)
            guard !V3DirectRefreshRunClaimPolicy.isActive(
                runID: existingClaim?["run_id"] as? String,
                deadline: existingClaim?["deadline"] as? Date) else {
                throw CombinedFailure(operation: "refresh", stage: .command, code: .busy,
                    id: directClaimID, retryable: true, safeCause: .operationInProgress)
            }
            sharedDefaults.set(["run_id": directClaimID,
                // Cover the bounded XPC admission handshake; renew immediately
                // once the backend lease is authoritative.
                "deadline": Date().addingTimeInterval(V3RefreshAdmissionLease.lifetime + 60)],
                forKey: V3DirectRefreshRunClaimPolicy.defaultsKey)
        }
        defer {
            if let directClaimID,
               sharedDefaults.dictionary(forKey: V3DirectRefreshRunClaimPolicy.defaultsKey)?["run_id"] as? String == directClaimID {
                sharedDefaults.removeObject(forKey: V3DirectRefreshRunClaimPolicy.defaultsKey)
            }
        }
        let selectedRun = V3RefreshRunIdentitySelection.select(
            schedulerRunID: schedulerRunID,
            expectedRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshExpectedRunID"),
            activeRunID: sharedDefaults.string(forKey: "liveContainerAutoRefreshActiveRunID"),
            newRunID: directClaimID ?? UUID().uuidString)
        guard let client else {
            throw CombinedFailure(operation: "refresh", stage: .xpcConnection, code: .invalidConfiguration, id: token.uuidString)
        }
        guard let selectedRun else {
            if let schedulerRunID {
                // Identity validation rejects this before service admission or
                // device dispatch. This is a stale scheduler request, not an
                // uncertain installation result that needs reconciliation.
                throw CombinedFailure(operation: "refresh", stage: .command,
                    code: .staleResult, id: schedulerRunID, retryable: false,
                    safeCause: .staleRefreshAttempt)
            }
            throw CombinedFailure(operation: "refresh", stage: .command,
                code: .busy, id: token.uuidString, retryable: true,
                safeCause: .operationInProgress)
        }
        let run = selectedRun.runID
        guard v3RefreshAdmissionRunID == nil else {
            throw CombinedFailure(operation: "refresh", stage: .serviceReadiness,
                code: .busy, id: run, retryable: true, safeCause: .operationInProgress)
        }
        v3RefreshAdmissionRunID = run
        defer { if v3RefreshAdmissionRunID == run { v3RefreshAdmissionRunID = nil } }
        defer { if v3RefreshDispatchedRunID == run { v3RefreshDispatchedRunID = nil } }
        defer { if v3RefreshTerminalCallbackRunID == run { v3RefreshTerminalCallbackRunID = nil } }
        // Reserve mutation ownership through the SideStore command gate before
        // starting the legacy XPC refresh path. Authentication and refresh
        // admission are serialized there.
        let admission = try await V3ServiceBridge.shared.request(
            operation: "refreshAdmissionBegin", target: run)
        guard admission["runID"] as? String == run,
              V3ServiceBridge.strictBool(admission["admitted"]) == true else {
            throw CombinedFailure(operation: "refresh", stage: .command,
                code: .busy, id: run, retryable: true, safeCause: .operationInProgress)
        }
        if let directClaimID {
            sharedDefaults.set(["run_id": directClaimID,
                "deadline": Date().addingTimeInterval(V3RefreshAdmissionLease.lifetime)],
                forKey: V3DirectRefreshRunClaimPolicy.defaultsKey)
        }
        sharedDefaults.set(run, forKey: "liveContainerAutoRefreshExpectedRunID")
        defer {
            if !selectedRun.schedulerOwned,
               sharedDefaults.string(forKey: "liveContainerAutoRefreshExpectedRunID") == run {
                sharedDefaults.removeObject(forKey: "liveContainerAutoRefreshExpectedRunID")
            }
        }
        refreshRunID = run
        let timeout = Task { @MainActor in
            do {
                try await Task.sleep(nanoseconds: V3RefreshAdmissionLease.nativeRefreshTimeoutNanoseconds)
            } catch { return }
            guard self.v3RefreshToken == token else { return }
            self.finishRefreshContinuation(.failure(CombinedFailure(operation: "refresh", stage: .refreshVerification, code: .timedOut, id: run)))
            self.service.stop()
        }
        defer { timeout.cancel() }
        do {
            try await withTaskCancellationHandler(operation: {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    if Task.isCancelled { continuation.resume(throwing: CancellationError()); return }
                    refreshContinuation = continuation
                    sharedDefaults.set(run, forKey: "liveContainerAutoRefreshUncertainMutationRunID")
                    v3RefreshTerminalCallbackRunID = nil
                    v3RefreshDispatchedRunID = run
                    client.refreshAllApps(withIdentifier: identifier, mangledTypeName: mangledName, refreshRunID: run)
                }
            }, onCancel: { Task { @MainActor in
                if self.v3RefreshToken == token && self.v3RefreshDispatchedRunID == run {
                    self.v3_stopService()
                }
            } })
        } catch {
            timeout.cancel()
            let resolution = V3RefreshAdmissionFailureResolution.resolve(
                runID: run, dispatchedRunID: v3RefreshDispatchedRunID,
                terminalCallbackRunID: v3RefreshTerminalCallbackRunID)
            switch resolution {
            case .releaseNotDispatched:
                await releaseRefreshAdmission(run,
                    terminalState: "notDispatched")
            case .releaseTerminalFailure:
                await releaseRefreshAdmission(run, terminalState: "failed")
            case .retainUnknownOutcome:
                // XPC loss, timeout, or cancellation after dispatch is not
                // proof that the device-side pipeline settled. Keep the
                // durable service lease until a matching callback or an
                // explicit device-check reconciliation.
                NSLog("[V3_REFRESH_ADMISSION] OUTCOME_UNKNOWN run_id=%@", run)
            }
            throw error
        }
        timeout.cancel()
        await releaseRefreshAdmission(run, terminalState: "completed")
    }
    private func releaseRefreshAdmission(_ runID: String, terminalState: String) async {
        // Run independently of a caller cancellation so a confirmed terminal
        // callback cannot strand the service's admission state.
        await Task { @MainActor in
            do {
                let reply = try await V3ServiceBridge.shared.request(
                    operation: "refreshAdmissionEnd", target: runID,
                    payload: ["state": terminalState])
                guard reply["runID"] as? String == runID,
                      V3ServiceBridge.strictBool(reply["released"]) == true else {
                    NSLog("[V3_REFRESH_ADMISSION] RELEASE_UNCONFIRMED run_id=%@", runID)
                    self.v3_stopService()
                    return
                }
            } catch {
                NSLog("[V3_REFRESH_ADMISSION] RELEASE_UNCONFIRMED run_id=%@", runID)
                self.v3_stopService()
            }
        }.value
    }
    private func finishRefreshContinuation(_ result: Result<Void, Error>) {
        let pending = refreshContinuation; refreshContinuation = nil; refreshRunID = nil
        pending?.resume(with: result)
    }
    fileprivate func updateProgress(_ value: Double, id: UUID) {
        guard launchID == id, refreshContinuation != nil, value.isFinite else { return }
        progress?.completedUnitCount = Int64(max(0, min(1, value)) * 100)
    }
    fileprivate func completedRefresh(_ error: String?, runID: String, verification: Data?, id: UUID) {
        guard launchID == id, refreshContinuation != nil, refreshRunID == runID else { return }
        v3RefreshTerminalCallbackRunID = runID
        if let error {
            if let defaults = V3SharedAppGroup.sharedUserDefaults() {
                CombinedVerification.clearUncertainty(defaults, runID: runID)
            }
            finishRefreshContinuation(.failure(CombinedFailure.fromEncodedString(error, expectedID: runID) ??
                CombinedFailure(operation: "refresh", stage: .command, id: runID)))
            return
        }
        guard let verification, verification.count <= 262144,
              let payload = try? PropertyListSerialization.propertyList(from: verification, format: nil) as? [String: Any],
              let manifest = payload["liveContainerAutoRefreshVerification"] as? [String: Any],
              manifest["run_id"] as? String == runID,
              let defaults = V3SharedAppGroup.sharedUserDefaults() else {
            finishRefreshContinuation(.failure(CombinedFailure(operation: "refresh", stage: .refreshVerification, code: .missingResult, id: runID)))
            return
        }
        defaults.set(manifest, forKey: "liveContainerAutoRefreshVerification")
        if payload["liveContainerAutoRefreshHostHandoffRunID"] as? String == runID {
            for key in ["liveContainerAutoRefreshHostHandoff", "liveContainerAutoRefreshHostHandoffRunID", "liveContainerAutoRefreshHostHandoffStartedAt", "liveContainerAutoRefreshHostPreviousExpiration"] {
                if let value = payload[key] { defaults.set(value, forKey: key) }
            }
        }
        guard CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID) else {
            finishRefreshContinuation(.failure(CombinedFailure(operation: "refresh", stage: .refreshVerification, code: .missingResult, id: runID)))
            return
        }
        if manifest["host_handoff"] as? Bool != true && !defaults.bool(forKey: "liveContainerAutoRefreshHostHandoff") {
            CombinedVerification.clearUncertainty(defaults, runID: runID)
        }
        NSLog("[LIVE_CONTAINER_REFRESH] RESULT_RECEIVED run_id=%@", runID)
        // The existing scheduler evaluates the imported installation evidence; this is command completion only.
        finishRefreshContinuation(.success(()))
    }
    fileprivate func legacyCompletion(_ error: String?, id: UUID) {
        guard launchID == id, refreshContinuation != nil, let run = refreshRunID else { return }
        // The legacy callback carries no run ID or verification manifest, so it
        // cannot prove which native run settled. Fail the caller conservatively;
        // admission remains held for explicit reconciliation.
        finishRefreshContinuation(.failure(CombinedFailure.fromEncodedString(error ?? "", expectedID: run) ??
            CombinedFailure(operation: "refresh", stage: .refreshVerification, code: .missingResult, id: run)))
    }
}

/// Builds the extension payload for the dedicated embedded-SideStore launch.
///
/// The normal guest launch is not the only way LiveProcess starts: this launch
/// hosts the embedded SideStore service itself, and that service runs every
/// cross-process store from inside LiveProcess. Without the selected group in
/// this payload LiveProcess publishes nothing, and its own Info.plist fallback
/// is what a re-sign leaves behind: iLoader rewrites ALTAppGroups on the main
/// bundle and signs extensions from regenerated provisioning profiles, so after
/// a re-sign LiveProcess is entitled to `group.com.SideStore.SideStore.<TEAM>`
/// while its Info.plist still lists the pre-resign `group.com.SideStore.SideStore`,
/// which it can no longer open.
///
/// The group therefore comes from the one resolver, already validated for this
/// process, and is the same value the guest launch forwards. There is no second
/// selection policy here: an unopenable identity yields no key at all, and
/// LiveProcess then resolves nothing rather than a different store.
enum V3EmbeddedSideStoreLaunchPayload {
    static let appGroupKey = "lcAppGroupID"

    static func userInfo(bookmark: Data, endpoint: Any,
                         identity: V3SharedAppGroup.Identity?) -> [String: Any] {
        var userInfo: [String: Any] = [
            "selected": "builtinSideStore", "bookmarks": [bookmark], "endpoint": endpoint]
        if let identity { userInfo[appGroupKey] = identity.identifier }
        return userInfo
    }
}

private final class CombinedServiceCallbacks: NSObject, RefreshServer {
    weak var owner: RefreshHandler?
    let identity: UUID
    init(owner: RefreshHandler, identity: UUID) { self.owner = owner; self.identity = identity }
    func onConnection(_ connection: NSXPCConnection!) {
        guard let connection else { return }
        Task { @MainActor in self.owner?.accepted(connection, id: self.identity) }
    }
    func finishedLaunching() { Task { @MainActor in self.owner?.applicationReady(self.identity) } }
    func updateProgress(_ value: Double) { Task { @MainActor in self.owner?.updateProgress(value, id: self.identity) } }
    func finish(_ error: String?) { Task { @MainActor in self.owner?.legacyCompletion(error, id: self.identity) } }
    func finishRefresh(_ error: String?, runID: String, verification: Data?) {
        Task { @MainActor in self.owner?.completedRefresh(error, runID: runID, verification: verification, id: self.identity) }
    }
    func add(_ request: UNNotificationRequest) {
        Task { @MainActor in
            guard self.owner?.launchIDForCallbacks == self.identity else { return }
            UNUserNotificationCenter.current().add(request, withCompletionHandler: nil)
        }
    }
    func removePendingNotificationRequests(withIdentifiers identifiers: [String]) {
        Task { @MainActor in
            guard self.owner?.launchIDForCallbacks == self.identity else { return }
            UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: identifiers)
        }
    }
}
extension RefreshHandler { fileprivate var launchIDForCallbacks: UUID? { launchID } }

import Foundation
import CoreFoundation
import CryptoKit

public struct V3AuthServiceSnapshot: Equatable {
    public let authenticated: Bool
    public let credentialRoutePresent: Bool
    public let provisioningIncomplete: Bool
    public let provisioningRetryAvailable: Bool
    public let authenticationActive: Bool
    public let authenticationSessionID: String?
    public let identityStamp: String?
    public let identityStable: Bool

    public init(authenticated: Bool, provisioningIncomplete: Bool,
                provisioningRetryAvailable: Bool, authenticationActive: Bool,
                authenticationSessionID: String?, credentialRoutePresent: Bool = false,
                identityStamp: String? = nil, identityStable: Bool = true) {
        self.authenticated = authenticated
        self.credentialRoutePresent = credentialRoutePresent
        self.provisioningIncomplete = provisioningIncomplete
        self.provisioningRetryAvailable = provisioningRetryAvailable
        self.authenticationActive = authenticationActive
        self.authenticationSessionID = authenticationSessionID
        self.identityStamp = identityStamp
        self.identityStable = identityStable
    }
}

// V3_WIRE_CONTRACT_V1: shared source, compiled independently in each process.
// V3_HEADLESS_CONTRACT_V2: SideStore is a headless backend. All presentation
// decisions cross as data (prompts/confirmations); no remote UI is addressed.
enum V3WireContract {
    static let requestLimit = 16_384
    static let responseLimit = 4_194_304
    static let authSessionLifetime: TimeInterval = 600
    static let cancellationScopes: Set<String> = ["auth", "operation", "request"]

    static func strictBool(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }

    static func strictInt(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let type = String(cString: number.objCType)
        guard ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(type) else {
            return nil
        }
        if ["C", "S", "I", "L", "Q"].contains(type) {
            return Int(exactly: number.uint64Value)
        }
        return Int(exactly: number.int64Value)
    }

    static func authSnapshot(_ reply: [String: Any]) -> V3AuthServiceSnapshot? {
        guard let authenticated = strictBool(reply["authenticated"]),
              let provisioningIncomplete = strictBool(reply["provisioningIncomplete"]),
              let provisioningRetryAvailable = strictBool(reply["provisioningRetryAvailable"]),
              let authenticationActive = strictBool(reply["authenticationActive"]) else {
            return nil
        }
        let authenticationSessionID: String?
        if let rawAuthenticationSessionID = reply["authenticationSessionID"] {
            guard let value = rawAuthenticationSessionID as? String else { return nil }
            authenticationSessionID = value
        } else {
            authenticationSessionID = nil
        }
        if authenticationActive {
            guard let authenticationSessionID,
                  UUID(uuidString: authenticationSessionID)?.uuidString == authenticationSessionID else { return nil }
        } else if authenticationSessionID != nil {
            return nil
        }
        guard let identityStamp = reply["identityStamp"] as? String,
              !identityStamp.isEmpty, identityStamp.utf8.count <= 128,
              let identityStable = strictBool(reply["identityStable"]) else { return nil }
        return V3AuthServiceSnapshot(authenticated: authenticated,
            provisioningIncomplete: provisioningIncomplete,
            provisioningRetryAvailable: provisioningRetryAvailable,
            authenticationActive: authenticationActive,
            authenticationSessionID: authenticationSessionID,
            credentialRoutePresent: strictBool(reply["credentialRoutePresent"]) ?? false,
            identityStamp: identityStamp, identityStable: identityStable)
    }

    static func invalidRequestIdentity(from data: Data) -> (id: String?, operation: String?) {
        guard data.count <= requestLimit,
              let envelope = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
            return (nil, nil)
        }
        let rawID = envelope["id"] as? String
        // Preserve the caller's spelling so reply correlation remains exact;
        // UUID(uuidString:) accepts lowercase forms as valid UUIDs too.
        let id = rawID.flatMap { UUID(uuidString: $0) != nil ? $0 : nil }
        let rawOperation = envelope["operation"] as? String
        let operation = rawOperation.flatMap { operations.contains($0) ? $0 : nil } ?? "command"
        return (id, operation)
    }

    static let operations: Set<String> = ["snapshot", "catalog", "appIcon", "cancel", "refreshSources",
        "refreshAdmissionBegin", "refreshAdmissionEnd",
        "signOut", "syncAppIDs", "clearCache", "jit", "backupResult",
        "authBegin", "authPoll", "authRespond", "authCancel", "authRetryProvisioning", "authReconcileStorage",
        "opStart", "opPoll", "opAnswer", "opCancel", "opRecoveryPrepare", "opRecoveryReconcile",
        "refreshAdmissionReconcile", "recoveryDiscardUnreadable", "directRecoveryInspect",
        "directRecoveryReconcile", "ipaCleanup", "ipaActiveTokens",
        "certList", "certExportActive", "certSetActive", "certDelete", "certPortalList", "certRevoke", "certCreate",
        "devTeams", "devDevices", "devAppIDs", "devGroups", "devProfiles",
        "sourcePreview", "sourceAddConfirmed", "sourceRemoveConfirmed",
        "pairingImportData", "settingsGet", "settingsSet",
        "anisetteList", "anisetteReset", "anisetteSync",
        "sidesignGet", "sidesignSet", "sidesignReset", "sidesignImport", "sidesignExport",
        "logTail", "healthSnapshot", "accountExport", "accountImport"]
    static let readOperations: Set<String> = ["snapshot", "catalog", "appIcon",
        "authPoll", "opPoll", "opCancel", "ipaCleanup", "ipaActiveTokens", "authCancel", "certList", "certExportActive", "certPortalList",
        "devTeams", "devDevices", "devAppIDs", "devGroups", "devProfiles",
        "sourcePreview", "settingsGet",
        "anisetteList", "sidesignGet", "sidesignExport", "logTail", "healthSnapshot",
        "directRecoveryInspect"]

    static func decodeRequest(_ data: Data, now: Date = Date()) -> [String: Any]? {
        guard data.count <= requestLimit,
              let request = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              Set(request.keys).isSubset(of: ["version", "id", "operation", "target", "deadline", "cursor", "payload"]),
              strictInt(request["version"]) == 1,
              let id = request["id"] as? String, UUID(uuidString: id) != nil,
              let operation = request["operation"] as? String, operations.contains(operation),
              let target = request["target"] as? String, target.utf8.count <= 4096,
              let deadline = request["deadline"] as? Date,
              deadline > now, deadline.timeIntervalSince(now) <= 610 else { return nil }
        if request["value"] != nil { return nil }
        let emptyTargetOperations: Set<String> = [
            "snapshot", "opStart", "accountExport", "ipaActiveTokens", "refreshSources", "signOut",
            "syncAppIDs", "clearCache", "settingsGet", "settingsSet", "sidesignGet", "sidesignSet",
            "sidesignReset", "sidesignExport", "anisetteList", "anisetteReset", "anisetteSync",
            "logTail", "certList", "certExportActive", "certPortalList", "certCreate", "opRecoveryPrepare",
            "recoveryDiscardUnreadable", "authReconcileStorage",
            "devTeams", "devDevices", "devAppIDs", "devGroups", "devProfiles"
        ]
        if emptyTargetOperations.contains(operation) && !target.isEmpty { return nil }
        if operation == "healthSnapshot", !["", "hostSigningOnly"].contains(target) { return nil }
        if ["authBegin", "authPoll", "authRespond", "authCancel", "authRetryProvisioning",
            "opPoll", "opAnswer", "opCancel", "pairingImportData", "sidesignImport", "accountImport",
            "refreshAdmissionBegin", "refreshAdmissionEnd", "refreshAdmissionReconcile",
            "opRecoveryReconcile", "directRecoveryInspect", "directRecoveryReconcile", "cancel"].contains(operation),
           !canonicalSecretToken(target) { return nil }
        if operation == "ipaCleanup", !canonicalLowercaseFileToken(target) { return nil }
        if ["appIcon", "jit"].contains(operation),
           !acceptsCoreDataTarget(target, entity: "InstalledApp") { return nil }
        if ["sourcePreview", "sourceAddConfirmed"].contains(operation), !isHTTPURL(target) { return nil }
        if operation == "backupResult", !canonicalSecretToken(target) { return nil }
        if let cursor = request["cursor"] {
            guard operation == "catalog", let value = strictInt(cursor),
                  value >= 0, value <= 1_000_000 else { return nil }
        }
        if let rawPayload = request["payload"] {
            guard let payload = rawPayload as? [String: Any],
                  acceptsPayload(operation: operation, target: target, payload: payload, now: now) else { return nil }
        } else if requiredPayloadOperations.contains(operation) {
            return nil
        }
        return request
    }

    // Apply the service's exact request schema before a host message can cross
    // XPC. Decoding remains mandatory in the service; this outbound pass keeps
    // raw secrets and unsupported fields from being transmitted at all.
    static func encodeRequest(_ request: [String: Any], now: Date = Date()) -> Data? {
        guard let data = try? PropertyListSerialization.data(
                fromPropertyList: request, format: .binary, options: 0),
              decodeRequest(data, now: now) != nil else { return nil }
        return data
    }

    private static let requiredPayloadOperations: Set<String> = [
        "authBegin", "authRetryProvisioning", "authRespond", "opAnswer", "opStart", "opRecoveryPrepare",
        "cancel", "accountExport", "accountImport", "settingsSet", "sidesignSet", "refreshAdmissionEnd",
        "recoveryDiscardUnreadable", "directRecoveryReconcile", "backupResult"
    ]

    /// The one request key that may carry a credential, and only for the
    /// operations that declare it below.
    ///
    /// The answer used to cross as an opaque Keychain token in a shared access
    /// group. Re-signing can leave the service extension without that group,
    /// making the token inaccessible even when the host can write it. The
    /// answer now travels in the request itself, over the peer-validated channel,
    /// so there is no shared-storage copy of the credential to protect at all.
    ///
    /// This key is the ONLY exemption from the raw-secret sweep. Rejecting any
    /// nested value is what keeps the exemption from becoming a hole.
    private static let credentialAnswerKey = "answer"

    private static let credentialAnswerOperations: Set<String> = [
        "authRespond", "opAnswer", "accountExport", "accountImport"
    ]

    /// A flat, strictly bounded string map. Nothing can nest inside it, so the
    /// sweep's exemption can never carry a subtree past `containsRawSecretField`.
    private static func credentialAnswerIsBounded(_ value: Any?) -> Bool {
        guard let map = value as? [String: String], !map.isEmpty, map.count <= 32 else { return false }
        return map.allSatisfy { key, text in
            !key.isEmpty && key.utf8.count <= 64 && text.utf8.count <= 4096
        }
    }

    private static func acceptsPayload(operation: String, target: String,
                                       payload: [String: Any], now: Date) -> Bool {
        // Skipped by exact key, and only where an operation declares it. Every
        // other key is still swept, at every depth.
        let skipping: Set<String> = credentialAnswerOperations.contains(operation)
            ? [credentialAnswerKey] : []
        guard !containsRawSecretField(payload, skipping: skipping) else { return false }
        switch operation {
        case "backupResult":
            return Set(payload.keys) == Set(["nonce", "action", "result"]) &&
                canonicalSecretToken(payload["nonce"]) &&
                ["backup", "restore"].contains(payload["action"] as? String ?? "") &&
                ["success", "failure"].contains(payload["result"] as? String ?? "")
        case "snapshot":
            return Set(payload.keys) == Set(["readinessOnly"]) &&
                strictBool(payload["readinessOnly"]) == true
        case "authBegin", "authRetryProvisioning":
            let baseKeys: Set<String> = ["session", "sessionDeadline"]
            // A control flag, not an authentication secret. Keep its name out
            // of the raw-secret vocabulary; do not exempt it from that sweep.
            let allowedKeys = operation == "authBegin" ? baseKeys.union(["provisioningLogin"]) : baseKeys
            guard baseKeys.isSubset(of: Set(payload.keys)), Set(payload.keys).isSubset(of: allowedKeys),
                  payload["provisioningLogin"] == nil || strictBool(payload["provisioningLogin"]) != nil,
                  let session = payload["session"] as? String,
                  canonicalSecretToken(session), session == target,
                  let sessionDeadline = payload["sessionDeadline"] as? Date,
                  sessionDeadline > now,
                  sessionDeadline.timeIntervalSince(now) <= authSessionLifetime + 10 else { return false }
            return true
        case "cancel":
            guard Set(payload.keys) == Set(["scope"]),
                  let scope = payload["scope"] as? String else { return false }
            return cancellationScopes.contains(scope)
        case "authRespond", "opAnswer":
            // The prompt id is what makes this one-shot: the service accepts an
            // answer only for the prompt it currently holds, and only once. The
            // token that used to sit here added no property the service did not
            // already enforce, and could not be read back under any signer.
            guard Set(payload.keys) == Set(["prompt", credentialAnswerKey]),
                  let prompt = payload["prompt"] as? String, !prompt.isEmpty, prompt.utf8.count <= 256,
                  credentialAnswerIsBounded(payload[credentialAnswerKey]) else { return false }
            return true
        case "accountExport":
            return Set(payload.keys) == Set(["includeApple", credentialAnswerKey]) &&
                strictBool(payload["includeApple"]) != nil &&
                credentialAnswerIsBounded(payload[credentialAnswerKey])
        case "accountImport":
            return Set(payload.keys) == Set([credentialAnswerKey]) &&
                credentialAnswerIsBounded(payload[credentialAnswerKey])
        case "opStart":
            guard Set(payload.keys) == Set(["kind", "target", "session"]),
                  let kind = payload["kind"] as? String, !kind.isEmpty, kind.utf8.count <= 128,
                  let operationTarget = payload["target"] as? String, operationTarget.utf8.count <= 4096,
                  let session = payload["session"] as? String, canonicalSecretToken(session) else { return false }
            return acceptsOperationTarget(kind: kind, target: operationTarget)
        case "opRecoveryPrepare":
            guard Set(payload.keys) == Set(["kind", "target", "session"]),
                  let kind = payload["kind"] as? String,
                  let operationTarget = payload["target"] as? String, operationTarget.utf8.count <= 4096,
                  let session = payload["session"] as? String, canonicalSecretToken(session) else { return false }
            return acceptsOperationTarget(kind: kind, target: operationTarget)
        case "opRecoveryReconcile", "refreshAdmissionReconcile":
            return Set(payload.keys) == Set(["userConfirmed"]) && strictBool(payload["userConfirmed"]) == true
        case "directRecoveryReconcile":
            if Set(payload.keys) == Set(["ackTerminal"]) {
                return strictBool(payload["ackTerminal"]) == true
            }
            return Set(payload.keys) == Set(["userConfirmed"]) && strictBool(payload["userConfirmed"]) == true
        case "recoveryDiscardUnreadable":
            return Set(payload.keys) == Set(["userConfirmed"]) && strictBool(payload["userConfirmed"]) == true
        case "refreshAdmissionEnd":
            return Set(payload.keys) == Set(["state"]) &&
                ["completed", "failed", "notDispatched"].contains(payload["state"] as? String ?? "")
        case "opCancel":
            return Set(payload.keys) == Set(["knownStarted"]) &&
                strictBool(payload["knownStarted"]) != nil
        case "settingsSet":
            guard let key = payload["key"] as? String, !key.isEmpty, key.utf8.count <= 256,
                  let type = payload["type"] as? String else { return false }
            switch type {
            case "bool":
                return Set(payload.keys) == Set(["key", "type", "bool"]) && strictBool(payload["bool"]) != nil
            case "string":
                guard Set(payload.keys) == Set(["key", "type", "string"]),
                      let value = payload["string"] as? String else { return false }
                return value.utf8.count <= 8192
            case "int":
                return Set(payload.keys) == Set(["key", "type", "int"]) && strictInt(payload["int"]) != nil
            default: return false
            }
        case "sidesignSet":
            // SideSign headers are user configuration and legitimately contain an
            // Authorization header, so their text is not content-scanned. The
            // bound that matters is the size cap.
            guard Set(payload.keys) == Set(["config"]),
                  let config = payload["config"] as? String, config.utf8.count <= 8192 else {
                return false
            }
            return true
        default:
            // Every unlisted operation is payloadless. New payload-bearing
            // commands must add an explicit schema before crossing XPC.
            return false
        }
    }

    private static func canonicalSecretToken(_ value: Any?) -> Bool {
        guard let token = value as? String, let uuid = UUID(uuidString: token) else { return false }
        return uuid.uuidString == token
    }

    private static func canonicalLowercaseFileToken(_ token: String) -> Bool {
        guard token.utf8.count == 36, let uuid = UUID(uuidString: token) else { return false }
        return uuid.uuidString.lowercased() == token
    }

    private static func acceptsOperationTarget(kind: String, target: String) -> Bool {
        switch kind {
        case "installSharedIPA":
            return canonicalLowercaseFileToken(target)
        case "installURL":
            return isHTTPURL(target)
        case "install":
            return acceptsCoreDataTarget(target, entity: "StoreApp")
        case "update", "refreshApp", "activate", "deactivate", "remove", "delete", "backup", "restore":
            return acceptsCoreDataTarget(target, entity: "InstalledApp")
        default:
            return false
        }
    }

    private static func acceptsCoreDataTarget(_ target: String, entity expectedEntity: String) -> Bool {
        guard let components = URLComponents(string: target),
              components.scheme?.lowercased() == "x-coredata",
              let host = components.host, UUID(uuidString: host) != nil,
              components.user == nil, components.password == nil,
              components.port == nil, components.query == nil, components.fragment == nil else { return false }
        let path = components.percentEncodedPath.split(separator: "/")
        return path.count == 2 && String(path[0]) == expectedEntity &&
            path[1].first == "p" && Int(path[1].dropFirst()) != nil
    }

    private static func isHTTPURL(_ value: String) -> Bool {
        guard let components = URLComponents(string: value),
              let scheme = components.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil else { return false }
        if let port = components.port, !(1...65535).contains(port) { return false }
        return true
    }

    private static let sensitiveSecretFieldFragments: [String] = [
        "appleid", "password", "passphrase", "answer", "verificationcode", "securitycode", "otp",
        "privatekey", "p12", "credential", "auth", "accesstoken", "refreshtoken",
        "authorization", "cookie", "dsid", "phoneid", "phonenumber", "secret", "token", "udid"
    ]

    private static func containsRawSecretField(_ value: Any, skipping: Set<String> = []) -> Bool {
        var pending: [Any] = [value]
        while let current = pending.popLast() {
            if let dictionary = current as? [String: Any] {
                for (key, nested) in dictionary {
                    let normalized = key.lowercased().filter { $0.isLetter || $0.isNumber }
                    // Matched before the fragment sweep, and the subtree is not
                    // traversed. Its shape is bounded separately, in
                    // `credentialAnswerIsBounded`.
                    if skipping.contains(normalized) { continue }
                    // This UUID is a non-secret, one-time capability allowed
                    // only by the exact schemas validated below.
                    let opaqueHandoffToken = normalized == "secrettoken"
                    if !opaqueHandoffToken && sensitiveSecretFieldFragments.contains(where: { normalized.contains($0) }) {
                        return true
                    }
                    pending.append(nested)
                }
            } else if let array = current as? [Any] {
                pending.append(contentsOf: array)
            }
        }
        return false
    }

    // V3_PROPERTY_LIST_VALUE_V1
    // Property lists cannot encode a Swift Optional that has been boxed into
    // `Any`. Assigning `someOptional` to an `[String: Any]` value stores
    // `Optional<T>.none` as a live object, and serialization then fails for the
    // whole response, long after the value was read correctly from its owner.
    //
    // V3_PLIST_LEAF_CONTRACT_V1: the accepted leaf set is Foundation's, not a
    // hand-written list, so it cannot drift from CoreFoundation. The previous
    // list accepted `URL`, which CoreFoundation rejects for every property-list
    // format except OpenStep: a `URL` object is not a property-list leaf and a
    // URL must be sent as `url.absoluteString`. It also rejected `Float` and the
    // narrow integer types, which do serialize. `NSNumber` is used because every
    // Swift numeric type bridges to it, including Bool, so one case covers the
    // whole numeric family without a remembered list.
    enum V3PropertyListValue {
        /// Returns the unwrapped value, or nil when it is absent.
        ///
        /// Only the Optional case is unwrapped. A value that is present but not
        /// representable is returned unchanged so the encoder can report a real
        /// encoding failure instead of silently dropping data.
        static func unwrapOptional(_ value: Any?) -> Any? {
            guard let value else { return nil }
            let mirror = Mirror(reflecting: value)
            guard mirror.displayStyle == .optional else { return value }
            return mirror.children.first?.value
        }

        /// Builds a property-list-safe dictionary, omitting keys whose value is
        /// an absent Optional. A key whose value is present but unrepresentable
        /// is preserved so serialization fails loudly rather than quietly.
        static func dictionary(_ entries: [String: Any?]) -> [String: Any] {
            var result: [String: Any] = [:]
            result.reserveCapacity(entries.count)
            for (key, value) in entries {
                if let unwrapped = unwrapOptional(value) { result[key] = unwrapped }
            }
            return result
        }

        /// True when a value can be encoded by PropertyListSerialization.
        ///
        /// `URL` is deliberately absent and unknown types are rejected rather
        /// than stringified: silently coercing an arbitrary object would put
        /// unreviewable text on the wire, and dropping it would lose data without
        /// reporting anything.
        static func isEncodable(_ value: Any) -> Bool {
            // A still-boxed Optional is never encodable, so an absent value
            // reports false rather than being silently accepted.
            guard let unwrapped = unwrapOptional(value) else { return false }
            if unwrapped is String || unwrapped is NSNumber
                || unwrapped is Date || unwrapped is Data { return true }
            if let array = unwrapped as? [Any] { return array.allSatisfy { isEncodable($0) } }
            if let dictionary = unwrapped as? [String: Any] {
                return dictionary.values.allSatisfy { isEncodable($0) }
            }
            return false
        }
    }
}

enum V3RequestReplayPolicy {
    static let cancellationOperations: Set<String> = ["cancel", "authCancel", "opCancel"]

    static func requiresCompletedReply(operation: String) -> Bool {
        cancellationOperations.contains(operation)
    }

    static func fingerprint(_ requestData: Data) -> Data {
        Data(SHA256.hash(data: requestData))
    }

    static func matches(cachedFingerprint: Data?, incomingRequestData: Data) -> Bool {
        guard let cachedFingerprint else { return false }
        return cachedFingerprint == fingerprint(incomingRequestData)
    }

    static func matchesInFlight(cachedFingerprint: Data?, incomingRequestData: Data) -> Bool {
        matches(cachedFingerprint: cachedFingerprint, incomingRequestData: incomingRequestData)
    }

    static func isIdentifierCollision(cachedFingerprint: Data?, incomingRequestData: Data) -> Bool {
        guard let cachedFingerprint else { return false }
        return !matches(cachedFingerprint: cachedFingerprint, incomingRequestData: incomingRequestData)
    }

    static func mayClaimNotDispatched(operation: String, identifierCollision: Bool) -> Bool {
        !identifierCollision && ["opStart", "authBegin", "authRetryProvisioning"].contains(operation)
    }
}

enum V3RefreshAdmissionCancellationAckPolicy {
    static func accepts(_ data: Data, cancellationID: String) -> Bool {
        guard !data.isEmpty, data.count <= V3WireContract.responseLimit,
              let reply = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              V3WireContract.strictInt(reply["version"]) == 1,
              reply["id"] as? String == cancellationID,
              V3WireContract.strictBool(reply["ok"]) == true,
              V3WireContract.strictBool(reply["refreshAdmissionReleased"]) == true else { return false }
        return true
    }
}

struct V3MutationReplyCacheBudget {
    static let maximumStoredBytes = 64 * 1024 * 1024
    static let maximumStoredReplies = 512
    static let reservedControlBytes = V3WireContract.responseLimit * 2
    // Prompt acknowledgements are not stored in the completed-request cache;
    // the session's accepted-prompt ledger makes them idempotent. Keep a small
    // reserve for starts and refresh admission release replies.
    static let authenticationLifecycleReplyBudget = 2
    static let provisioningRetryReplyBudget = 1
    // The operation start and its possible external SideBackup callback must
    // both fit. Ordinary operation polls and prompt answers do not consume it.
    static let operationPromptReplyBudget = 2
    static let reservedControlReplies = 8
    private(set) var storedBytes = 0

    static func isControlReply(operation: String) -> Bool {
        ["refreshAdmissionEnd", "refreshAdmissionReconcile", "opRecoveryReconcile", "directRecoveryReconcile", "recoveryDiscardUnreadable",
         "authBegin", "authRetryProvisioning", "opStart", "backupResult"]
            .contains(operation) || V3RequestReplayPolicy.requiresCompletedReply(operation: operation)
    }

    static func shouldCacheResponse(operation: String) -> Bool {
        !["authRespond", "opAnswer", "certExportActive"].contains(operation)
    }

    static func minimumAvailableRepliesToAdmit(operation: String) -> Int {
        switch operation {
        case "authBegin": return authenticationLifecycleReplyBudget
        case "authRetryProvisioning": return provisioningRetryReplyBudget
        case "opStart": return operationPromptReplyBudget
        default: return 1
        }
    }

    static func minimumReplyBytesToAdmit(operation: String) -> Int {
        ["authBegin", "opStart"].contains(operation)
            ? V3WireContract.responseLimit * 2
            : V3WireContract.responseLimit
    }

    static func canAdmit(operation: String, completedReplyCount: Int) -> Bool {
        let required = minimumAvailableRepliesToAdmit(operation: operation)
        return completedReplyCount >= 0 && completedReplyCount <= maximumStoredReplies - required
    }

    func canReserve(maximumResponseBytes: Int = V3WireContract.responseLimit,
                    preservingControlCapacity: Bool = true) -> Bool {
        let limit = Self.maximumStoredBytes - (preservingControlCapacity ? Self.reservedControlBytes : 0)
        return maximumResponseBytes >= 0 && maximumResponseBytes <= limit &&
            storedBytes <= limit - maximumResponseBytes
    }

    mutating func record(_ byteCount: Int, controlResponse: Bool = false) -> Bool {
        guard byteCount >= 0,
              canReserve(maximumResponseBytes: byteCount, preservingControlCapacity: !controlResponse) else { return false }
        storedBytes += byteCount
        return true
    }

    static func responseCountLimit(isControlResponse: Bool) -> Int {
        isControlResponse ? maximumStoredReplies : maximumStoredReplies - reservedControlReplies
    }

    mutating func remove(_ byteCount: Int) {
        storedBytes = max(0, storedBytes - max(0, byteCount))
    }
}

enum V3ServiceReadinessReply: Equatable {
    case invalid
    case notReady
    case failed(V3ServiceReadinessFailure)
    case ready

    // This source fragment is compiled independently in both processes, so
    // its allowlist intentionally has no dependency on the typed failure model. The
    // executable vocabulary-parity harness verifies every typed cause and
    // source step is accepted here while unknown values remain rejected.
    static let knownSafeCauseValues: Set<String> = [
        "networkConnectionLost", "networkTimedOut", "networkUnavailable",
        "anisetteServerUnavailable", "anisetteServerRejected", "anisetteRequestTimedOut",
        "anisetteRateLimited", "anisetteInvalidResponse", "anisetteUnknownFailure",
        "signingNetworkConnectionLost", "signingNetworkTimedOut", "signingNetworkUnavailable",
        "developerPortalRejectedRequest", "developerPortalInvalidResponse", "appIDLimitReached",
        "provisioningProfileUnavailable", "certificateUnavailable", "signingStorageUnverified", "wifiUnavailable",
        "localDevVPNUnavailable", "unknownSigningCause", "sourceNetworkFailure",
        "sourceInvalidManifest", "sourcePersistenceUnverified", "sourceInvalidURL",
        "sourceBlocked", "sourceChangedID", "sourceDuplicate", "sourceUnsupported",
        "sourceValidationFailed", "sourceRemoveFailed", "sourceRemoveBusy", "sourceAddBusy",
        "operationInProgress", "responseCapacityUnavailable", "staleRefreshAttempt",
        "knownSourcePolicyNetworkFailure", "knownSourcePolicyInvalidResponse",
        "catalogUnavailable", "catalogSourceUnavailable", "responseEncodingFailed",
        "responseTooLarge", "pairingRequired", "invalidPairingFile",
        "pairingFilePreparationFailed", "authAttemptNotDispatched",
        "authProvisioningRetryNotDispatched", "authSessionUnavailable",
        "authResponseCapacityUnavailable", "operationPersistenceFailed", "keychainSignOutFailed",
        "credentialCommitFailed", "credentialCommitOutcomeUnknown", "accountActivationFailed", "provisioningStorageFailed",
        "keychainSignOutOutcomeUnknown", "recoveryMalformedRecord",
        "recoveryIncompatibleRecord", "recoveryStorageUnavailable",
"recoveryLockUnavailable", "recoveryReadFailure", "recoveryDeleteFailure",
        "sharedStoreUnavailable", "secretHandoffUnavailable"
    ]
    static let knownSourceStepValues: Set<String> = [
        "authenticate", "anisetteFetch", "appleAuthentication", "accountLookup", "credentialCommit", "fetchTeams", "saveAccount", "fetchCertificate",
        "activateCertificate", "registerDevice", "activateAccount", "provisioningUnknown",
        "provisioningProfileFetch", "certificateValidation", "localCodeSigning",
        "appIDLookup", "appIDRegistration", "appIDCapabilitiesUpdate",
        "appGroupLookup", "appGroupRegistration", "appGroupAssignment",
        "provisioningProfileRetrieval", "provisioningProfileCreation", "provisioningProfileUpdate",
        "sourceDownload", "manifestParsing", "sourceValidation", "knownSourcePolicyFetch",
        "knownSourcePolicyParsing", "catalogRead"
    ]

    static func decode(_ data: Data, requestID: String) -> V3ServiceReadinessReply {
        guard !data.isEmpty, data.count <= V3WireContract.responseLimit,
              let reply = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              V3WireContract.strictInt(reply["version"]) == 1,
              reply["id"] as? String == requestID else { return .invalid }
        // A structured failure is authoritative even when a malformed peer
        // omits the legacy error token. Fail closed on success-shaped replies
        // that also carry an invalid structured failure envelope.
        if reply["error"] != nil || reply["failure"] != nil {
            guard let envelope = reply["failure"] as? [String: Any],
                  Set(envelope.keys).isSubset(of: Set(["version", "operation", "stage", "code", "correlationID",
                      "underlyingDomain", "underlyingCode", "retryable", "safeCause", "sourceStep", "signingContext"])),
                  V3WireContract.strictInt(envelope["version"]) == 1,
                  envelope["correlationID"] as? String == requestID,
                  let operation = envelope["operation"] as? String,
                  let stage = envelope["stage"] as? String,
                  let code = envelope["code"] as? String,
                  let domain = envelope["underlyingDomain"] as? String,
                  let underlyingCode = V3WireContract.strictInt(envelope["underlyingCode"]) else { return .invalid }
            guard !operation.isEmpty, operation.utf8.count <= 64,
                  !stage.isEmpty, stage.utf8.count <= 64,
                  !code.isEmpty, code.utf8.count <= 64,
                  domain.utf8.count <= 128 else { return .invalid }
            let retryable: Bool?
            if let raw = envelope["retryable"] {
                guard let value = V3WireContract.strictBool(raw) else { return .invalid }
                retryable = value
            } else { retryable = nil }
            let safeCause: String?
            if let raw = envelope["safeCause"] {
                guard let value = raw as? String, Self.knownSafeCauseValues.contains(value) else { return .invalid }
                safeCause = value
            } else { safeCause = nil }
            let sourceStep: String?
            if let raw = envelope["sourceStep"] {
                guard let value = raw as? String, Self.knownSourceStepValues.contains(value) else { return .invalid }
                sourceStep = value
            } else { sourceStep = nil }
            var failure = V3ServiceReadinessFailure(operation: operation, stage: stage, code: code,
                correlationID: requestID, underlyingDomain: domain, underlyingCode: underlyingCode,
                safeCause: safeCause, sourceStep: sourceStep,
                retryable: retryable)
            if let raw = envelope["signingContext"] {
                guard let suppliedFields = raw as? [String: String] else { return .invalid }
                let fields = V3TemporaryADIExecution.sanitizingContext(suppliedFields)
                guard fields.count <= 20,
                      fields.allSatisfy({ $0.key.utf8.count <= 64 &&
                          $0.value.utf8.count <= ([V3TemporaryAnisetteTrace.contextKey, V3TemporaryADIConsumption.contextKey, V3TemporaryADIExecution.contextKey].contains($0.key) ? 2048 : 512) }) else { return .invalid }
                // The typed failure boundary validates the fixed keys
                // and values before any diagnostic publication.
                failure.signingContext = fields
            }
            if ["snapshot", "status"].contains(failure.operation) && failure.stage == "serviceReadiness" &&
               failure.code == "notReady" && failure.retryable == true {
                return .notReady
            }
            return .failed(failure)
        }
        guard V3WireContract.strictBool(reply["ok"]) == true,
              let result = reply["result"] as? [String: Any],
              let ready = V3WireContract.strictBool(result["ready"]) else { return .invalid }
        return ready ? .ready : .notReady
    }
}

struct V3ServiceReadinessFailure: Equatable {
    let operation: String
    let stage: String
    let code: String
    let correlationID: String
    let underlyingDomain: String
    let underlyingCode: Int
    let safeCause: String?
    let sourceStep: String?
    let retryable: Bool?
    var signingContext: [String: String] = [:]
}
import Foundation

enum V3SetupSnapshotOutcome: String, Equatable {
    case applied
    case snapshotFailed
    case notObserved
}

enum V3SetupReloadRecomputePolicy {
    static func mayRecompute(outcome: V3SetupSnapshotOutcome) -> Bool {
        outcome == .applied
    }
}

struct V3HostDirectRecoveryRecord: Equatable {
    enum Phase: String { case prepared, dispatched, terminal, unknown }

    let requestID: String
    let operation: String
    let phase: Phase
    let resultState: String?
    let postcondition: V3DirectRecoveryPostcondition?

    init?(_ rawValue: Any?) {
        guard let raw = rawValue as? [String: Any],
              Set(raw.keys).isSubset(of: ["requestID", "operation", "phase", "resultState", "postcondition"]),
              let requestID = raw["requestID"] as? String,
              UUID(uuidString: requestID)?.uuidString == requestID,
              let operation = raw["operation"] as? String,
              Self.operations.contains(operation),
              let phase = (raw["phase"] as? String).flatMap(Phase.init(rawValue:)),
              !raw.keys.contains("resultState") || raw["resultState"] is String else { return nil }
        let resultState = raw["resultState"] as? String
        guard resultState.map({ ["completed", "createdAndStored",
              "remoteCreatedLocalStorageUnverified"].contains($0) }) ?? true,
              (phase == .terminal) == (resultState != nil) else { return nil }
        let postcondition: V3DirectRecoveryPostcondition?
        if raw.keys.contains("postcondition") {
            guard let rawPostcondition = raw["postcondition"] as? String,
                  let parsed = V3DirectRecoveryPostcondition(rawValue: rawPostcondition) else { return nil }
            postcondition = parsed
        } else {
            postcondition = nil
        }
        self.requestID = requestID
        self.operation = operation
        self.phase = phase
        self.resultState = resultState
        self.postcondition = postcondition
    }

    init?(snapshotValue: Any?) {
        guard let raw = snapshotValue as? [String: Any], !raw.keys.contains("postcondition"),
              let parsed = V3HostDirectRecoveryRecord(raw) else { return nil }
        self = parsed
    }

    init?(inspectionReply: [String: Any]) {
        guard let parsed = V3HostDirectRecoveryRecord(inspectionReply),
              parsed.postcondition != nil else { return nil }
        self = parsed
    }

    static let operations: Set<String> = [
        "certCreate", "certRevoke", "sourceAddConfirmed", "sourceRemoveConfirmed",
        "pairingImportData", "settingsSet", "accountImport"
    ]
}

enum V3DirectRecoveryPostcondition: String {
    case achieved, notAchieved, indeterminate, manualCheckRequired, notDispatched
}

enum V3DirectRecoveryHostPolicy {
    static func mayOfferUserConfirmation(_ record: V3HostDirectRecoveryRecord,
                                        postcondition: V3DirectRecoveryPostcondition?) -> Bool {
        record.phase != .dispatched && postcondition != nil
    }

    static func mayAcknowledgeSuccessfulResponse(operation: String,
                                                  result: [String: Any]) -> Bool {
        guard V3HostDirectRecoveryRecord.operations.contains(operation) else { return false }
        if operation == "certCreate" {
            return result["outcome"] as? String == "createdAndStored"
        }
        if operation == "accountImport" { return false }
        return true
    }

    static func mayAcknowledgeInspectedTerminal(_ record: V3HostDirectRecoveryRecord,
                                                 postcondition: V3DirectRecoveryPostcondition) -> Bool {
        guard record.phase == .terminal, postcondition == .achieved else { return false }
        if record.operation == "certCreate",
           record.resultState == "remoteCreatedLocalStorageUnverified" { return false }
        return true
    }
}

enum V3DirectRecoveryPresentationPolicy {
    static func operationName(_ operation: String) -> String {
        switch operation {
        case "certCreate": return "certificate creation"
        case "certRevoke": return "certificate revocation"
        case "sourceAddConfirmed": return "source add"
        case "sourceRemoveConfirmed": return "source removal"
        case "pairingImportData": return "pairing import"
        case "settingsSet": return "setting change"
        case "accountImport": return "account import"
        default: return "SideStore request"
        }
    }

    static func explanation(record: V3HostDirectRecoveryRecord,
                            postcondition: V3DirectRecoveryPostcondition?) -> String {
        if record.operation == "certCreate",
           record.resultState == "remoteCreatedLocalStorageUnverified" {
            return "The remote certificate may exist, but local storage was not verified. Check before trying again."
        }
        switch postcondition {
        case .achieved:
            return "The service verified the requested result. The matching terminal record can be acknowledged."
        case .notAchieved:
            return "The service did not observe the requested result. Check the account or device before clearing this hold."
        case .indeterminate:
            return "The service could not verify the result. Check the account or device before clearing this hold."
        case .manualCheckRequired:
            return "The result needs a manual account or device check before the recovery hold can be cleared."
        case .notDispatched:
            return "The service confirms this request was not dispatched. Clear the reservation only after reviewing it."
        case nil:
            return record.phase == .prepared
                ? "SideStore prepared the request but did not confirm dispatch. Inspect the result before retrying."
                : "The original reply is unavailable. Inspect the exact request before retrying."
        }
    }
}

enum V3AuthReadStampPolicy {
    static func ownsTicket(captured: UInt64, current: UInt64) -> Bool {
        captured == current
    }

    static func mayReturn(capturedStamp: String, currentStamp: String, stable: Bool) -> Bool {
        stable && capturedStamp == currentStamp
    }

    static func mayCommit(capturedTicket: UInt64, currentTicket: UInt64,
                          capturedStamp: String, currentStamp: String?, stable: Bool,
                          resultStamps: [String?], authenticationActive: Bool = false) -> Bool {
        stable && !authenticationActive && capturedTicket == currentTicket &&
            currentStamp == capturedStamp && !resultStamps.isEmpty &&
            resultStamps.allSatisfy { $0 == capturedStamp }
    }
}

enum V3AuthSessionCoalescerKey {
    static func value(for identityStamp: String) -> String {
        "apple_auth_session:" + identityStamp
    }
}

struct V3AsyncRequestOwner: Equatable, Sendable {
    let generation: UInt64
    let bindingID: String?
}

struct V3AsyncRequestOwnerState: Sendable {
    private(set) var generation: UInt64 = 0

    mutating func begin(bindingID: String? = nil) -> V3AsyncRequestOwner {
        generation &+= 1
        return V3AsyncRequestOwner(generation: generation, bindingID: bindingID)
    }

    mutating func invalidate() {
        generation &+= 1
    }

    func owns(_ owner: V3AsyncRequestOwner, bindingID: String? = nil) -> Bool {
        owner.generation == generation && owner.bindingID == bindingID
    }
}

struct V3StatusWriteTicket: Equatable, Sendable {
    let revision: UInt64
    let serviceEpoch: UInt64
    let ownerID: String
    let serviceInstanceID: String
    let kind: V3StatusAuthorityLeaseKind
}

enum V3StatusAuthorityLeaseKind: String, Equatable, Sendable {
    case snapshot
    case mutation
}

struct V3StatusLeaseWaiterOrder: Sendable {
    private var ids: [String] = []

    mutating func enqueue(_ id: String) {
        ids.append(id)
    }

    mutating func remove(_ id: String) {
        ids.removeAll { $0 == id }
    }

    mutating func takeNext() -> String? {
        ids.isEmpty ? nil : ids.removeFirst()
    }

    var count: Int { ids.count }
}

enum V3StatusWriteOutcome: Equatable, Sendable {
    case committed
    case failed
    case notDispatched
    case outcomeUnknown
}

/// One bridge-owned revision and lease authority for status snapshots and writes.
/// Cancellation ACKs never complete a lease; only its original callback or
/// explicit service retirement does.
struct V3StatusWriteAuthority: Sendable {
    private(set) var revision: UInt64 = 0
    private(set) var serviceEpoch: UInt64 = 0
    private(set) var serviceInstanceID: String?
    private(set) var activeLease: V3StatusWriteTicket?
    // Unknown one-shot owners are deliberately not evicted or cleared by a
    // generic snapshot; operation-specific reconciliation must resolve them.
    private(set) var unresolvedOwnerIDs: Set<String> = []

    func canBegin(kind: V3StatusAuthorityLeaseKind,
                  allowUnresolvedMutation: Bool = false) -> Bool {
        activeLease == nil && (kind == .snapshot || allowUnresolvedMutation || !hasUnresolvedMutation)
    }

    /// A mutation reserves a revision before it can suspend for a lease or XPC.
    mutating func reserveMutationRevision() -> UInt64 {
        revision &+= 1
        return revision
    }

    mutating func begin(ownerID: String, revision reservedRevision: UInt64,
                        serviceInstanceID: String,
                        kind: V3StatusAuthorityLeaseKind,
                        allowUnresolvedMutation: Bool = false) -> V3StatusWriteTicket? {
        guard canBegin(kind: kind, allowUnresolvedMutation: allowUnresolvedMutation),
              reservedRevision <= revision else { return nil }
        let ticket = V3StatusWriteTicket(revision: reservedRevision,
            serviceEpoch: serviceEpoch, ownerID: ownerID,
            serviceInstanceID: serviceInstanceID, kind: kind)
        activeLease = ticket
        return ticket
    }

    @discardableResult
    mutating func complete(_ ticket: V3StatusWriteTicket,
                           outcome: V3StatusWriteOutcome) -> Bool {
        guard activeLease == ticket else { return false }
        activeLease = nil
        switch outcome {
        case .outcomeUnknown:
            if ticket.kind == .mutation { unresolvedOwnerIDs.insert(ticket.ownerID) }
        case .committed, .failed, .notDispatched:
            unresolvedOwnerIDs.remove(ticket.ownerID)
        }
        return true
    }

    /// Observing a replacement process advances the epoch. A matching long
    /// session control may transfer its lease to that process; unrelated work
    /// cannot take ownership from the original request.
    mutating func observeServiceInstance(_ instanceID: String,
                                         continuingOwnerID: String?) -> V3StatusWriteTicket? {
        if serviceInstanceID != instanceID {
            serviceEpoch &+= 1
            serviceInstanceID = instanceID
        }
        guard let activeLease, let continuingOwnerID,
              activeLease.ownerID == continuingOwnerID else {
            return nil
        }
        guard activeLease.serviceEpoch != serviceEpoch ||
              activeLease.serviceInstanceID != instanceID else { return activeLease }
        let rebound = V3StatusWriteTicket(revision: activeLease.revision,
            serviceEpoch: serviceEpoch, ownerID: activeLease.ownerID,
            serviceInstanceID: instanceID, kind: activeLease.kind)
        self.activeLease = rebound
        return rebound
    }

    /// Explicit process retirement is the only no-callback release path.
    mutating func retireService() -> V3StatusWriteTicket? {
        serviceEpoch &+= 1
        serviceInstanceID = nil
        guard let retired = activeLease else { return nil }
        activeLease = nil
        if retired.kind == .mutation && !retired.ownerID.hasPrefix("recovery-control:") {
            unresolvedOwnerIDs.insert(retired.ownerID)
        }
        return retired
    }

    func mayApply(_ ticket: V3StatusWriteTicket,
                  currentServiceEpoch: UInt64,
                  currentServiceInstanceID: String) -> Bool {
        activeLease == nil && ticket.revision == revision &&
            ticket.serviceEpoch == currentServiceEpoch &&
            ticket.serviceInstanceID == currentServiceInstanceID &&
            !unresolvedOwnerIDs.contains(ticket.ownerID)
    }

    @discardableResult
    mutating func resolveOwnerAfterReconciliation(_ ownerID: String) -> Bool {
        guard unresolvedOwnerIDs.remove(ownerID) != nil else { return false }
        revision &+= 1
        return true
    }

    /// Exact authoritative session evidence can also settle a matching active
    /// lease. This is separate from generic unknown-owner reconciliation so a
    /// caller cannot clear an unrelated active mutation.
    @discardableResult
    mutating func resolveOwnerAfterAuthoritativeReconciliation(_ ownerID: String) -> Bool {
        if activeLease?.ownerID == ownerID {
            activeLease = nil
            unresolvedOwnerIDs.remove(ownerID)
            revision &+= 1
            return true
        }
        return resolveOwnerAfterReconciliation(ownerID)
    }

    var hasActiveWrite: Bool { activeLease?.kind == .mutation }
    var hasActiveLease: Bool { activeLease != nil }
    var hasUnresolvedMutation: Bool { !unresolvedOwnerIDs.isEmpty }
}

enum V3StatusReplyCommitPolicy {
    static func mayApply(_ ticket: V3StatusWriteTicket,
                         authority: V3StatusWriteAuthority,
                         currentServiceEpoch: UInt64,
                         currentServiceInstanceID: String,
                         busySnapshot: Bool = false) -> Bool {
        if ticket.kind == .snapshot && busySnapshot { return false }
        return authority.mayApply(ticket, currentServiceEpoch: currentServiceEpoch,
            currentServiceInstanceID: currentServiceInstanceID)
    }
}

enum V3RecoveryOnlySnapshotPolicy {
    static func mayApplyFullStatus(busy: Bool, activeMutation: Bool,
                                   recoveryHold: Bool, hasTypedRecoveryEvidence: Bool) -> Bool {
        busy && !activeMutation && recoveryHold && hasTypedRecoveryEvidence
    }
}

enum V3RecoveryStoragePresentationPolicy {
    static func mayOfferClear(connected: Bool, unresolved: Bool, kind: String?,
                              serverClearEligible: Bool) -> Bool {
        connected && unresolved && serverClearEligible &&
            ["malformedRecord", "incompatibleRecord"].contains(kind ?? "")
    }

    static func confirmsCleared(snapshotApplied: Bool, unreadable: Bool,
                                operationRecovery: Bool, directRecovery: Bool,
                                refreshRecovery: Bool) -> Bool {
        snapshotApplied && !unreadable && !operationRecovery && !directRecovery && !refreshRecovery
    }
}

enum V3RecoveryClearHostAdmissionPolicy {
    static func permits(operation: String, target: String, userConfirmed: Bool,
                        recoveryHold: Bool, otherMutationActive: Bool) -> Bool {
        operation == "recoveryDiscardUnreadable" && target.isEmpty && userConfirmed &&
            recoveryHold && !otherMutationActive
    }
}

enum V3StatusRecoveryEvidencePolicy {
    static func mayApply(busySnapshot: Bool, activeMutation: Bool?,
                         hasDurableRecoveryEvidence: Bool) -> Bool {
        busySnapshot && activeMutation != true && hasDurableRecoveryEvidence
    }

    static func hasRecoveryEvidence(_ reply: [String: Any]) -> Bool {
        let recoveryHold = V3OperationReplyFieldPolicy.strictBoolean(reply["recoveryHold"]) == true
        let operation = reply["operationRecovery"] as? [String: Any]
        let operationEvidence = operation?["session"] as? String
        let refresh = reply["refreshRecovery"] as? [String: Any]
        let refreshRunID = refresh?["runID"] as? String
        let refreshEvidence = refreshRunID.map { UUID(uuidString: $0)?.uuidString == $0 } == true &&
            V3OperationReplyFieldPolicy.strictBoolean(refresh?["ownerLost"]) == true
        let unreadable = V3OperationReplyFieldPolicy.strictBoolean(reply["recoveryJournalUnreadable"]) == true
        let direct = V3HostDirectRecoveryRecord(snapshotValue: reply["directRecovery"])
        let directEvidence = direct != nil && recoveryHold
        let hasRecoveryField = reply.keys.contains("operationRecovery") ||
            reply.keys.contains("refreshRecovery") || reply.keys.contains("directRecovery")
        return recoveryHold || hasRecoveryField || directEvidence || unreadable || refreshEvidence ||
            (operationEvidence.map { UUID(uuidString: $0) != nil } == true &&
             (operation?["kind"] as? String)?.isEmpty == false &&
             V3OperationRecoveryRecord.Phase(rawValue: operation?["phase"] as? String ?? "") != nil)
    }
}

// Direct Apple certificate mutations must not outrun an interrupted local
// credential, certificate or account activation commit. Local readback repair
// is deliberately outside this policy and still uses the normal mutation gate.
enum V3CertificateStorageAdmission {
    static func failure(operation: String, id: String,
                        databaseRequiresReconciliation: Bool,
                        keychainRequiresReconciliation: () throws -> Bool) -> CombinedFailure? {
        guard ["certCreate", "certRevoke"].contains(operation) else { return nil }
        let unresolved = databaseRequiresReconciliation ||
            ((try? keychainRequiresReconciliation()) ?? true)
        guard unresolved else { return nil }
        return CombinedFailure(operation: operation, stage: .persistence, code: .notReady,
            id: id, retryable: false, safeCause: .signingStorageUnverified)
    }
}

enum V3StatusAuthorityOperationPolicy {
    static func directWriteOwnerID(operation: String, requestID: String) -> String? {
        // `backupResult` is control for its existing operation owner; `ipaCleanup`
        // only retires staged files. Neither creates a new status writer. Recovery journal edits
        // do change fields in the next authoritative snapshot and are fenced.
        let writes: Set<String> = [
            "signOut", "accountImport", "syncAppIDs", "clearCache", "refreshSources", "jit",
            "certSetActive", "certDelete", "certRevoke", "certCreate",
            "sourceAddConfirmed", "sourceRemoveConfirmed", "pairingImportData", "settingsSet",
            "sidesignSet", "sidesignReset", "sidesignImport", "anisetteReset", "anisetteSync",
            "opRecoveryPrepare", "recoveryDiscardUnreadable", "authReconcileStorage"
        ]
        return writes.contains(operation) ? "request:\(requestID)" : nil
    }

    static func longOwnerID(operation: String, sessionID: String?) -> String? {
        guard let sessionID, !sessionID.isEmpty else { return nil }
        switch operation {
        case "authBegin", "authRetryProvisioning": return "auth:\(sessionID)"
        case "opStart": return "operation:\(sessionID)"
        case "refreshAdmissionBegin": return "refresh:\(sessionID)"
        default: return nil
        }
    }

    static func controlOwnerID(operation: String, sessionID: String?) -> String? {
        guard let sessionID, !sessionID.isEmpty else { return nil }
        switch operation {
        case "authPoll", "authRespond", "authCancel": return "auth:\(sessionID)"
        case "opPoll", "opAnswer", "opCancel", "opRecoveryReconcile", "backupResult": return "operation:\(sessionID)"
        case "refreshAdmissionEnd", "refreshAdmissionReconcile": return "refresh:\(sessionID)"
        default: return nil
        }
    }

    static func terminalOutcome(operation: String, result: [String: Any]) -> V3StatusWriteOutcome? {
        let payload = result["result"] as? [String: Any] ?? result
        switch operation {
        case "authBegin", "authRetryProvisioning", "authPoll", "authRespond", "authCancel":
            guard let state = payload["state"] as? String,
                  ["completed", "failed", "cancelled", "timedOut", "promptExpired", "resultUnknown"].contains(state) else {
                return nil
            }
            return state == "resultUnknown" ? .outcomeUnknown : .committed
        case "opStart", "opPoll", "opAnswer", "opCancel":
            guard let state = payload["state"] as? String,
                  ["completed", "failed", "cancelled", "requiresSource", "waitingForAuthentication"].contains(state) else {
                return nil
            }
            let settled = V3OperationReplyFieldPolicy.strictBoolean(payload["backendSettled"]) == true ||
                V3OperationReplyFieldPolicy.strictBoolean(payload["stopConfirmed"]) == true
            return settled ? .committed : .outcomeUnknown
        case "refreshAdmissionBegin", "refreshAdmissionEnd", "refreshAdmissionReconcile":
            if operation != "refreshAdmissionBegin" &&
               (V3OperationReplyFieldPolicy.strictBoolean(payload["released"]) == true ||
                V3OperationReplyFieldPolicy.strictBoolean(payload["reconciled"]) == true) { return .committed }
            return nil
        case "opRecoveryReconcile":
            return V3OperationReplyFieldPolicy.strictBoolean(payload["reconciled"]) == true
                ? .committed : nil
        case "directRecoveryReconcile":
            return V3OperationReplyFieldPolicy.strictBoolean(payload["reconciled"]) == true
                ? .committed : nil
        default:
            return .committed
        }
    }
}

import CoreFoundation

/// The lock protects only this small in-memory stamp state. Callers hold no
/// lock while network requests, authentication prompts, or provisioning run.
final class V3AuthIdentityStampState: @unchecked Sendable {
    struct Snapshot: Equatable, Sendable {
        let stamp: String
        let generation: UInt64
        let stable: Bool
    }

    private let lock = NSLock()
    private let processNonce = UUID().uuidString
    private var revision: UInt64 = 0
    private var transitionDepth = 0

    var snapshot: Snapshot {
        lock.lock()
        defer { lock.unlock() }
        return Snapshot(stamp: processNonce + ":\(revision)",
            generation: revision, stable: transitionDepth == 0)
    }

    func beginTransition() {
        lock.lock()
        revision &+= 1
        transitionDepth += 1
        lock.unlock()
    }

    func completeTransition() {
        lock.lock()
        revision &+= 1
        if transitionDepth > 0 { transitionDepth -= 1 }
        lock.unlock()
    }

    func advanceGeneration() {
        lock.lock()
        revision &+= 1
        lock.unlock()
    }

    /// Performs a short in-memory commit only while the captured identity is
    /// still current. The closure must not suspend or perform I/O.
    func runIfCurrent(_ capturedStamp: String, commit: () -> Void) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard transitionDepth == 0, processNonce + ":\(revision)" == capturedStamp else {
            return false
        }
        commit()
        return true
    }
}

// V3_CRASH_REASON_LOG_PRIVACY_V1: exception reasons and call stacks may contain
// credentials, URLs, user data, or local paths. Callers may only log this marker.
enum V3CrashLogPrivacy {
    static func safeCrashMarker(reason: String?) -> String {
        _ = reason
        return "[AppDelegate] UNCAUGHT_NSEXCEPTION_CRASH details=omitted"
    }
}

// Operation phases are fed by PipelineExecutor's actual PipelineStep callback.
// Unknown steps intentionally collapse to Working... rather than inferring a
// stage from progress percentages.
enum V3OperationPhase: String, Equatable, CaseIterable {
    case working
    case preparing
    case preparingIPA
    case downloadingIPA
    case verifying
    case preparingSigning
    case fetchingProvisioningProfile
    case signing
    case preparingInstallation
    case transferringToDevice
    case installing
    case refreshing
    case deleting
    case backingUp
    case restoring
    case updating
    case cleaningUp

    var label: String {
        switch self {
        case .working: return "Working..."
        case .preparing: return "Preparing..."
        case .preparingIPA: return "Preparing IPA..."
        case .downloadingIPA: return "Downloading IPA..."
        case .verifying: return "Verifying..."
        case .preparingSigning: return "Preparing signing..."
        case .fetchingProvisioningProfile: return "Fetching provisioning profile..."
        case .signing: return "Signing..."
        case .preparingInstallation: return "Preparing installation..."
        case .transferringToDevice: return "Transferring to device..."
        case .installing: return "Installing..."
        case .refreshing: return "Refreshing..."
        case .deleting: return "Removing app..."
        case .backingUp: return "Backing up..."
        case .restoring: return "Restoring..."
        case .updating: return "Updating app..."
        case .cleaningUp: return "Cleaning up..."
        }
    }

    static func forPipelineStep(_ step: String, downloadUsesNetwork: Bool = false) -> Self? {
        switch step {
        case "userCustomization", "preflightChecks", "cacheApp": return .preparing
        case "downloadApp": return downloadUsesNetwork ? .downloadingIPA : .preparingIPA
        case "verifyApp", "verifyCertificate": return .verifying
        case "updateAppCertificate": return .preparingSigning
        case "fetchProvisioningProfiles": return .fetchingProvisioningProfile
        case "embedSigningCert", "resignApp", "cacheSigningCert": return .signing
        case "stageApp", "stageBackupApp", "changeAppIcon", "removeAppExtensions",
             "prepareAppExtensionBundleIDs", "createIPA", "exportResignedIPA":
            return .preparingInstallation
        case "sendApp": return .transferringToDevice
        case "installApp": return .installing
        case "refreshApp": return .refreshing
        case "uninstallApp", "removeApp": return .deleting
        case "backupAppData": return .backingUp
        case "restoreAppData": return .restoring
        case "deactivateApp", "markAppInactive": return .updating
        case "removeBackupData", "cleanStagedApp": return .cleaningUp
        default: return nil
        }
    }
}

struct V3OperationPhaseTracker: Equatable {
    private(set) var phase: V3OperationPhase = .working

    mutating func recordPipelineStep(_ step: String, downloadUsesNetwork: Bool = false) {
        phase = V3OperationPhase.forPipelineStep(step, downloadUsesNetwork: downloadUsesNetwork) ?? .working
    }

    mutating func record(_ phase: V3OperationPhase) {
        self.phase = phase
    }
}

enum V3NormalizedProgress {
    static func clamp(_ value: Double) -> Double {
        guard value.isFinite else { return 0 }
        return min(max(value, 0), 1)
    }

    static func displayValue(_ value: Double, state: String) -> Double {
        state == "completed" ? 1 : clamp(value)
    }

    static func percent(_ value: Double, state: String) -> Int {
        Int((displayValue(value, state: state) * 100).rounded())
    }
}

enum V3SourceAddDecision: Equatable { case save, alreadyAdded }

enum V3SourceAddPersistencePolicy {
    static func decision(sourceIsPersisted: Bool) -> V3SourceAddDecision {
        sourceIsPersisted ? .alreadyAdded : .save
    }

    static func verifiedResult(identifier: String, alreadyAdded: Bool,
                                authoritativeCount: Int) -> [String: Any]? {
        guard !identifier.isEmpty, authoritativeCount == 1 else { return nil }
        return ["identifier": identifier,
                "added": !alreadyAdded,
                "alreadyAdded": alreadyAdded,
                "persistenceVerified": true]
    }

    static func confirmationMessage(_ result: [String: Any]) -> String? {
        guard result["persistenceVerified"] as? Bool == true,
              let identifier = result["identifier"] as? String, !identifier.isEmpty,
              let added = result["added"] as? Bool,
              let alreadyAdded = result["alreadyAdded"] as? Bool else { return nil }
        if added && !alreadyAdded { return "Source added." }
        if !added && alreadyAdded { return "Source already added." }
        return nil
    }

    static func validatedURL(_ value: String) -> URL? {
        guard let url = URL(string: value),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host != nil, url.user == nil, url.password == nil else { return nil }
        return url
    }

    static func unverifiedPersistenceFailure(correlationID: String) -> CombinedFailure {
        CombinedFailure(operation: "source", stage: .source, code: .invalidResponse,
            id: correlationID, retryable: false,
            safeCause: .sourcePersistenceUnverified, sourceStep: .catalogRead)
    }
}

// Source identifiers are normalized database keys, not fetchable URLs. Never
// reconstruct a URL from one: normalization removes scheme/query and lowercases
// case-sensitive paths. Missing URLs from older backends require manual recovery.
enum V3SourceRecoveryPolicy {
    static func isSettledStartReply(_ reply: [String: Any], sessionID: String) -> Bool {
        reply["session"] as? String == sessionID &&
            reply["state"] as? String == "requiresSource" &&
            V3OperationReplyFieldPolicy.strictBoolean(reply["failedToStart"]) == true &&
            V3OperationReplyFieldPolicy.strictBoolean(reply["backendSettled"]) == true &&
            !V3OperationReplyFieldPolicy.outcomeUnknown(reply["outcomeUnknown"])
    }

    static func target(sourceID: String, sourceURL: String?) -> String? {
        guard !sourceID.isEmpty, let sourceURL,
              V3SourceAddPersistencePolicy.validatedURL(sourceURL) != nil else { return nil }
        return sourceURL
    }

    static func matchesPreview(_ preview: [String: Any], sourceID: String) -> Bool {
        !sourceID.isEmpty && preview["identifier"] as? String == sourceID
    }

    static func verifiedAddition(_ result: [String: Any], sourceID: String) -> Bool {
        guard matchesPreview(result, sourceID: sourceID),
              V3SourceAddPersistencePolicy.confirmationMessage(result) != nil,
              let sources = result["sources"] as? [[String: Any]] else { return false }
        return sources.contains { $0["identifier"] as? String == sourceID }
    }
}

enum V3SourceAddFailurePolicy {
    static func normalized(_ failure: CombinedFailure) -> CombinedFailure {
        guard failure.operation == "source", failure.stage == .command,
              failure.safeCause == nil else { return failure }
        let stage: CombinedFailure.Stage = [.notReady, .unavailable].contains(failure.code)
            ? .serviceReadiness : .source
        let cause: CombinedFailure.SafeCause? = failure.code == .busy ? .sourceAddBusy : nil
        let underlying: NSError? = failure.underlyingDomain == "none" && failure.underlyingCode == 0
            ? nil : NSError(domain: failure.underlyingDomain, code: failure.underlyingCode)
        return CombinedFailure(operation: "source", stage: stage, code: failure.code,
            id: failure.correlationID, underlying: underlying,
            retryable: failure.retryable, safeCause: cause)
    }
}

enum V3SourceSubmissionPolicy {
    static func mayResubmit(retryable: Bool?, safeCause: String?,
                            failedInput: String?, currentInput: String) -> Bool {
        guard failedInput == currentInput else { return true }
        if retryable == false {
            return [CombinedFailure.SafeCause.sourceInvalidManifest.rawValue,
                    CombinedFailure.SafeCause.sourcePersistenceUnverified.rawValue].contains(safeCause ?? "")
        }
        return ![CombinedFailure.SafeCause.responseEncodingFailed.rawValue,
                 CombinedFailure.SafeCause.responseTooLarge.rawValue].contains(safeCause ?? "")
    }
}

enum V3JITLessReadiness: String, Equatable {
    case notRequired
    case setupRequired
    case certificateImported
    case needsCertificateRefresh
    case revoked
    case activeCertificateRevoked
    case activeCertificateExpired
    // V3_JITLESS_CERT_DISTINCTION_V1: SideStore's active certificate being
    // absent is a different problem from the LiveContainer copy being stale, and
    // neither means the other's certificate is broken.
    case activeCertificateMissing
    case certificateMismatch
    case ready
    case unknown

    var isReady: Bool { self == .ready || self == .notRequired }

    /// True only for a genuinely finished JIT-Less state. Used so a completed
    /// JIT-Less setup is never rendered as an outstanding setup task.
    var isSatisfied: Bool { isReady }
}

// This policy describes only the LiveContainer copy and safe public identity
// facts. Import/repair remains LiveContainer's canonical settings flow.
enum V3JITLessReadinessPolicy {
    static func evaluate(osMajor: Int, hasCopy: Bool, activeCertificateExists: Bool,
                         activeCertificateStatus: String = "unknown", identitiesMatch: Bool?,
                         validationStatus: Int?, validationFailed: Bool) -> V3JITLessReadiness {
        guard osMajor >= 26 else { return .notRequired }
        if activeCertificateExists && activeCertificateStatus == "revoked" { return .activeCertificateRevoked }
        if activeCertificateExists && activeCertificateStatus == "expired" { return .activeCertificateExpired }
        // Distinct from "the copy is missing": the active SideStore certificate
        // itself is absent, which is a SideStore-side prerequisite.
        guard activeCertificateExists else { return .activeCertificateMissing }
        guard hasCopy else { return .setupRequired }
        guard let validationStatus else { return .certificateImported }
        if validationStatus == 1 {
            if activeCertificateExists, identitiesMatch == true { return .activeCertificateRevoked }
            return .revoked
        }
        guard validationStatus == 0, !validationFailed else { return .unknown }
        guard let identitiesMatch else { return .unknown }
        // The copy is valid but SideStore has since moved to a different
        // certificate. Only the copy is stale; SideStore's certificate is fine.
        return identitiesMatch ? .ready : .certificateMismatch
    }
}

// V3_JITLESS_PRESENTATION_V1
// One place that decides how a JIT-Less state is presented, so the Setup
// Assistant, Health and Settings cannot each invent their own treatment. A ready
// state is a completed result, not an outstanding setup task.
struct V3JITLessPresentation: Equatable {
    let readiness: V3JITLessReadiness
    let severity: V3StatusSeverity
    let title: String
    let detail: String
    /// True when this state still requires the user to do something.
    let isOutstandingSetupTask: Bool

    var icon: String { severity.icon }

    static func present(_ readiness: V3JITLessReadiness) -> V3JITLessPresentation {
        switch readiness {
        case .notRequired:
            return V3JITLessPresentation(readiness: .notRequired, severity: .completed,
                                        title: "Not required",
                                        detail: "This iOS version does not require a JIT-Less certificate.",
                                        isOutstandingSetupTask: false)
        case .ready:
            return V3JITLessPresentation(readiness: .ready, severity: .completed,
                                        title: "Configured / Ready",
                                        detail: "The LiveContainer JIT-Less certificate matches the active SideStore certificate.",
                                        isOutstandingSetupTask: false)
        case .certificateMismatch:
            return V3JITLessPresentation(readiness: .certificateMismatch, severity: .warning,
                                        title: "JIT-Less certificate copy is out of date",
                                        detail: "SideStore is using a different or newer signing certificate than the JIT-Less certificate stored by LiveContainer. Refresh the JIT-Less certificate copy.",
                                        isOutstandingSetupTask: true)
        case .activeCertificateMissing:
            return V3JITLessPresentation(readiness: .activeCertificateMissing, severity: .failed,
                                        title: "No active SideStore certificate",
                                        detail: "SideStore has no active signing certificate. Open Certificates and create or select one before configuring JIT-Less.",
                                        isOutstandingSetupTask: true)
        case .activeCertificateRevoked:
            return V3JITLessPresentation(readiness: .activeCertificateRevoked, severity: .failed,
                                        title: "Active certificate revoked",
                                        detail: "SideStore's active signing certificate is reported as revoked. Open Certificates and select or create a current certificate.",
                                        isOutstandingSetupTask: true)
        case .activeCertificateExpired:
            return V3JITLessPresentation(readiness: .activeCertificateExpired, severity: .failed,
                                        title: "Active certificate expired",
                                        detail: "SideStore's active signing certificate has expired. Open Certificates and select or create a current certificate.",
                                        isOutstandingSetupTask: true)
        case .setupRequired:
            return V3JITLessPresentation(readiness: .setupRequired, severity: .warning,
                                        title: "JIT-Less certificate not configured",
                                        detail: "LiveContainer has no JIT-Less certificate copy yet. Import one to launch guest apps on this iOS version.",
                                        isOutstandingSetupTask: true)
        case .revoked:
            return V3JITLessPresentation(readiness: .revoked, severity: .failed,
                                        title: "JIT-Less certificate copy is revoked",
                                        detail: "The certificate stored by LiveContainer is reported as revoked. Import a current copy.",
                                        isOutstandingSetupTask: true)
        case .certificateImported:
            return V3JITLessPresentation(readiness: .certificateImported, severity: .warning,
                                        title: "Certificate imported, validation pending",
                                        detail: "The certificate is stored but could not be validated yet.",
                                        isOutstandingSetupTask: true)
        case .needsCertificateRefresh:
            return V3JITLessPresentation(readiness: .needsCertificateRefresh, severity: .warning,
                                        title: "JIT-Less certificate needs refreshing",
                                        detail: "Refresh the JIT-Less certificate copy from SideStore.",
                                        isOutstandingSetupTask: true)
        case .unknown:
            return V3JITLessPresentation(readiness: .unknown, severity: .unknown,
                                        title: "Validation unknown",
                                        detail: "The JIT-Less certificate state could not be verified.",
                                        isOutstandingSetupTask: true)
        }
    }
}

enum V3JITLessSetupAction: Equatable {
    case setUp
    case refreshCertificate
    case openCertificates
    case openSetup
    case none
}

enum V3JITLessSetupActionPolicy {
    static func action(for readiness: V3JITLessReadiness) -> V3JITLessSetupAction {
        switch readiness {
        case .setupRequired: return .setUp
        case .needsCertificateRefresh, .certificateMismatch, .revoked:
            return .refreshCertificate
        case .activeCertificateMissing, .activeCertificateRevoked, .activeCertificateExpired:
            return .openCertificates
        case .certificateImported, .unknown: return .openSetup
        case .ready, .notRequired: return .none
        }
    }
}

struct V3SignInJITLessGuidance: Equatable {
    let readiness: V3JITLessReadiness
    let presentation: V3JITLessPresentation
    let action: V3JITLessSetupAction
}

/// Composes the existing authoritative readiness, presentation, and action
/// policies for the post-sign-in page. It observes a fact; it never reads or
/// guesses certificate readiness itself.
enum V3SignInJITLessGuidancePolicy {
    static func resolve(osMajor: Int, readiness: V3JITLessReadiness?) -> V3SignInJITLessGuidance? {
        guard V3JITLessCompletionPolicy.isRequired(osMajor: osMajor) else { return nil }
        // A "not required" fact cannot be trusted on a supported iOS version.
        // Treat it as unverified instead of presenting setup as complete.
        let observed: V3JITLessReadiness
        if let readiness, readiness != .notRequired {
            observed = readiness
        } else {
            observed = .unknown
        }
        return V3SignInJITLessGuidance(readiness: observed,
            presentation: V3JITLessPresentation.present(observed),
            action: V3JITLessSetupActionPolicy.action(for: observed))
    }
}

enum V3JITLessHealthRecoveryPolicy {
    static func shouldOfferCanonicalSetup(for readiness: V3JITLessReadiness,
                                          activeCertificateAvailable: Bool) -> Bool {
        switch readiness {
        case .unknown: return true
        case .certificateImported: return activeCertificateAvailable
        default: return false
        }
    }
}

enum V3TwoFactorStep: String, Equatable {
    case chooseDeliveryMethod
    case choosePhoneNumber
    case deliveryRequested
    case enterVerificationCode
    case verifyingCode
    case completed
    case failed
    case cancelled

    var progressLabel: String? {
        switch self {
        case .choosePhoneNumber: return "Choose a phone number for this verification request..."
        case .deliveryRequested: return "Requesting verification..."
        case .verifyingCode: return "Verifying code..."
        default: return nil
        }
    }

    static func afterDeliveryChoice(_ method: String, phoneCount: Int) -> Self? {
        guard ["trustedDevice", "sms", "voice"].contains(method) else { return nil }
        return method == "sms" || method == "voice" ? (phoneCount > 1 ? .choosePhoneNumber : .deliveryRequested) : .deliveryRequested
    }

    static func afterDelivery(_ method: String) -> Self? {
        ["trustedDevice", "sms", "voice"].contains(method) ? .enterVerificationCode : nil
    }

    static func afterVerification(accepted: Bool) -> Self {
        accepted ? .completed : .enterVerificationCode
    }

    static var afterChangeMethod: Self { .chooseDeliveryMethod }
}

enum V3AuthTerminalPolicy {
    static func resolve(authenticationSucceeded: Bool, authoritativeAccountMatches: Bool,
                        provisioningFailed: Bool, cancelled: Bool) -> String {
        if authenticationSucceeded || authoritativeAccountMatches {
            return provisioningFailed || cancelled ? "authenticatedProvisioningIncomplete" : "completed"
        }
        return cancelled ? "cancelled" : "failed"
    }
}

struct V3AuthPostAuthenticationFailurePresentation: Equatable {
    let stage: CombinedFailure.Stage
    let message: String
}

enum V3AuthPostAuthenticationFailurePolicy {
    static func resolve(cancelled: Bool, savedSessionUnavailable: Bool)
        -> V3AuthPostAuthenticationFailurePresentation {
        let message: String
        if savedSessionUnavailable {
            message = "Signed in successfully, but SideStore could not reuse the saved Apple session to retry provisioning. Sign in again with this Apple ID before retrying setup."
        } else if cancelled {
            message = "Signed in successfully. Provisioning was cancelled before setup finished."
        } else {
            message = "Signed in successfully, but provisioning could not be completed."
        }
        return V3AuthPostAuthenticationFailurePresentation(stage: .provisioning, message: message)
    }
}

enum V3AuthAttemptAuthenticationPolicy {
    private static func normalized(_ value: String?) -> String? {
        guard let value else { return nil }
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty ? nil : normalized
    }

    static func confirms(authenticationCallbackSeen: Bool, submittedAppleID: String?,
                         activeAppleID: String?, accountAppleIDAtStart: String?) -> Bool {
        if authenticationCallbackSeen { return true }
        guard let submitted = normalized(submittedAppleID),
              normalized(activeAppleID) == submitted else { return false }
        return normalized(accountAppleIDAtStart) != submitted
    }
}

enum V3AuthPromptFailurePolicy {
    static func applying(reply: [String: Any], current: [String: Any]?) -> [String: Any]? {
        (reply["previousFailure"] as? [String: Any]) ?? current
    }

    static func isVisible(_ failure: [String: Any]?, promptKind: String?) -> Bool {
        failure != nil && promptKind == "credentials"
    }

    static func clearingAfterSubmission(_ failure: [String: Any]?, promptKind: String?) -> [String: Any]? {
        promptKind == "credentials" ? nil : failure
    }

    static func clearingOnDismiss(_ failure: [String: Any]?) -> [String: Any]? { nil }
}

// A picker selection survives dismissal and any in-flight snapshot reload.
// The picker and operation occupy one host-owned cover, so SwiftUI never has to
// race two unrelated root presentations.
struct V3InstallPresentationRequest: Equatable {
    let attemptID: UUID
    let operationID: UUID
    let token: String
    let title: String
}

// Local IPA, URL, and catalog installs all converge on the same AppOperation
// builder after resolution has produced an AppProtocol value.
enum V3InstallInputRoute: String, Equatable { case localIPA, remoteURL, catalog }

enum V3InstallPipelineParity {
    static func makeOperation<ResolvedApp, Operation>(
        route: V3InstallInputRoute,
        _ resolvedApp: ResolvedApp,
        build: (ResolvedApp) -> Operation
    ) -> (route: V3InstallInputRoute, operation: Operation) {
        (route, build(resolvedApp))
    }
}

// Coordinates a direct root-owned UIKit picker. If the anchor is not in the
// window hierarchy yet, the attempt remains queued until UIKit reports that
// the anchor appeared; it is never converted into a nested SwiftUI sheet.
final class V3InstallPickerPresentationCoordinator {
    enum Phase: String, Equatable { case idle, queued, presenting, presented, dismissing, awaitingDismissal }
    enum Decision: Equatable {
        case present(UUID)
        case queued
        case dismissed(UUID)
        case rejected(UUID, String)
        case none
    }

    private(set) var phase: Phase = .idle
    private(set) var attemptID: UUID?

    func request(attemptID: UUID, presenterReady: Bool,
                 presenterBusy: Bool) -> Decision {
        guard phase == .idle else { return .rejected(attemptID, "presenter_busy") }
        self.attemptID = attemptID
        guard presenterReady else {
            phase = .queued
            return .queued
        }
        guard !presenterBusy else {
            phase = .queued
            return .rejected(attemptID, "presentation_active")
        }
        phase = .presenting
        return .present(attemptID)
    }

    func presenterBecameReady(isBusy: Bool) -> Decision {
        switch phase {
        case .queued:
            guard let attemptID else { return .none }
            guard !isBusy else {
                return .rejected(attemptID, "presentation_active")
            }
            phase = .presenting
            return .present(attemptID)
        case .awaitingDismissal:
            guard !isBusy, let attemptID else { return .none }
            reset()
            return .dismissed(attemptID)
        default:
            return .none
        }
    }

    @discardableResult
    func didPresent(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .presenting else { return false }
        phase = .presented
        return true
    }

    @discardableResult
    func beginDismissal(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .presenting || phase == .presented else { return false }
        phase = .dismissing
        return true
    }

    @discardableResult
    func didDismiss(attemptID id: UUID, presenterIsClear: Bool) -> Bool {
        guard attemptID == id, phase == .dismissing || phase == .presented else { return false }
        guard presenterIsClear else {
            phase = .awaitingDismissal
            return false
        }
        reset()
        return true
    }

    @discardableResult
    func fail(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase != .idle else { return false }
        reset()
        return true
    }

    private func reset() {
        phase = .idle
        attemptID = nil
    }
}

struct V3InstallAttemptState {
    enum Phase: String, Equatable {
        case idle, pickerPresented, staging, waitingForPickerDismissal, waitingForReload
        case readyToPresentOperation, operationPresented, operationStarted, terminal, cleaningUp
    }

    private(set) var phase: Phase = .idle
    private(set) var attemptID: UUID?
    private(set) var operationID: UUID?
    private(set) var token: String?
    private(set) var title: String?
    private(set) var backendSessionID: String?
    private(set) var terminalOutcome: String?
    private(set) var operationViewDidAppear = false

    var isIdle: Bool { phase == .idle }
    var hasActiveAttempt: Bool { !isIdle }

    mutating func beginPicker() -> UUID? {
        guard isIdle else { return nil }
        reset()
        let id = UUID()
        attemptID = id
        phase = .pickerPresented
        return id
    }

    mutating func beginDirectStaging() -> UUID? {
        guard isIdle else { return nil }
        reset()
        let id = UUID()
        attemptID = id
        phase = .staging
        return id
    }

    @discardableResult
    mutating func beginStaging(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .pickerPresented else { return false }
        phase = .staging
        return true
    }

    @discardableResult
    mutating func staged(attemptID id: UUID, token: String, title: String,
                         waitsForPickerDismissal: Bool, isLoading: Bool) -> Bool {
        guard attemptID == id, phase == .staging, UUID(uuidString: token) != nil,
              !title.isEmpty, title.utf8.count <= 160 else { return false }
        self.token = token
        self.title = title
        if waitsForPickerDismissal { phase = .waitingForPickerDismissal }
        else { phase = isLoading ? .waitingForReload : .readyToPresentOperation }
        return true
    }

    @discardableResult
    mutating func failStaging(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .staging else { return false }
        reset()
        return true
    }

    @discardableResult
    mutating func pickerDidDisappear(attemptID id: UUID, isLoading: Bool) -> Bool {
        guard attemptID == id, phase == .waitingForPickerDismissal else { return false }
        phase = isLoading ? .waitingForReload : .readyToPresentOperation
        return true
    }

    @discardableResult
    mutating func cancelPicker(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .pickerPresented || phase == .staging ||
                phase == .waitingForPickerDismissal else { return false }
        reset()
        return true
    }

    // A presentation can be discarded only before a backend session has been
    // issued, or after the caller has separately confirmed a terminal result.
    @discardableResult
    mutating func resetBeforeBackend(attemptID id: UUID) -> Bool {
        guard attemptID == id else { return false }
        switch phase {
        case .pickerPresented, .staging, .waitingForPickerDismissal,
             .waitingForReload, .readyToPresentOperation:
            reset()
            return true
        case .operationPresented where !operationViewDidAppear && backendSessionID == nil:
            reset()
            return true
        default:
            return false
        }
    }

    mutating func reloadFinished() {
        guard phase == .waitingForReload else { return }
        phase = .readyToPresentOperation
    }

    mutating func takeReadyOperation(isLoading: Bool,
                                     hasActiveOperationPresentation: Bool) -> V3InstallPresentationRequest? {
        guard phase == .readyToPresentOperation, !isLoading, !hasActiveOperationPresentation,
              let attemptID, let token, let title else { return nil }
        let operationID = UUID()
        self.operationID = operationID
        operationViewDidAppear = false
        phase = .operationPresented
        return V3InstallPresentationRequest(attemptID: attemptID, operationID: operationID,
                                            token: token, title: title)
    }

    @discardableResult
    mutating func markOperationViewDidAppear(attemptID id: UUID, operationID: UUID) -> Bool {
        guard attemptID == id, self.operationID == operationID,
              phase == .operationPresented || phase == .operationStarted else { return false }
        operationViewDidAppear = true
        return true
    }

    @discardableResult
    mutating func backendStarted(attemptID id: UUID, operationID: UUID, sessionID: String) -> Bool {
        guard attemptID == id, self.operationID == operationID,
              phase == .operationPresented, backendSessionID == sessionID,
              UUID(uuidString: sessionID) != nil else { return false }
        backendSessionID = sessionID
        phase = .operationStarted
        return true
    }

    @discardableResult
    mutating func backendStartRequested(attemptID id: UUID, operationID: UUID,
                                        sessionID: String) -> Bool {
        guard attemptID == id, self.operationID == operationID,
              phase == .operationPresented, UUID(uuidString: sessionID) != nil else { return false }
        backendSessionID = sessionID
        return true
    }

    @discardableResult
    mutating func recordTerminal(attemptID id: UUID, operationID: UUID, outcome: String) -> Bool {
        guard attemptID == id, self.operationID == operationID,
              phase == .operationPresented || phase == .operationStarted else { return false }
        terminalOutcome = outcome
        phase = .terminal
        return true
    }

    @discardableResult
    mutating func prepareRetry(attemptID id: UUID, operationID: UUID) -> Bool {
        guard attemptID == id, self.operationID == operationID, phase == .terminal else { return false }
        backendSessionID = nil
        terminalOutcome = nil
        operationViewDidAppear = true
        phase = .operationPresented
        return true
    }

    @discardableResult
    mutating func beginCleanup(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .terminal else { return false }
        phase = .cleaningUp
        return true
    }

    @discardableResult
    mutating func finishCleanup(attemptID id: UUID) -> Bool {
        guard attemptID == id, phase == .cleaningUp else { return false }
        reset()
        return true
    }

    private mutating func reset() {
        phase = .idle
        attemptID = nil
        operationID = nil
        token = nil
        title = nil
        backendSessionID = nil
        terminalOutcome = nil
        operationViewDidAppear = false
    }
}

// Deletion completion is based on SideStore's pipeline/native uninstall result
// plus its persisted app-library state. Progress and a host-side list update do
// not establish success on their own.
struct V3DeleteCompletionContract {
    enum BackendResult: Equatable { case pending, succeeded, failed }
    enum Terminal: Equatable { case completed, failed, outcomeUnknown }

    private(set) var terminal: Terminal?

    mutating func resolve(backend: BackendResult, nativeUninstallSucceeded: Bool,
                          appStillInAuthoritativeLibrary: Bool, deadlineExpired: Bool,
                          progress: Double) -> Terminal? {
        _ = progress // Progress is deliberately never a success signal.
        guard terminal == nil else { return terminal }
        if backend == .failed {
            terminal = .failed
        } else if !appStillInAuthoritativeLibrary &&
                    (backend == .succeeded ||
                     (backend == .pending && nativeUninstallSucceeded && deadlineExpired)) {
            terminal = .completed
        } else if backend == .pending && deadlineExpired {
            // This is provisional. Keep the contract open so the late callback
            // can still establish the authoritative result.
            return .outcomeUnknown
        } else if deadlineExpired {
            terminal = .failed
        }
        return terminal
    }
}

enum V3DeleteCancellationPolicy {
    static func callbackCancellationRemainsPending(isCancellation: Bool,
                                                   cancellationRequested: Bool) -> Bool {
        isCancellation && cancellationRequested
    }

    static func cancelRequestReturnsBeforeDriverSettlement(operation: String,
                                                            driverIsRunning: Bool) -> Bool {
        operation == "delete" && driverIsRunning
    }

    static func keepsHostPollMonitor(operation: String) -> Bool {
        operation == "delete"
    }
}

enum V3OperationCancellationResolutionPolicy {
    static func requiresReconciliation(backendSettled: Bool?, outcomeUnknown: Bool) -> Bool {
        outcomeUnknown || backendSettled != true
    }
}

enum V3OperationReplyFieldPolicy {
    static func strictBoolean(_ rawValue: Any?) -> Bool? {
        guard let rawValue, let value = rawValue as? NSNumber,
              CFGetTypeID(value) == CFBooleanGetTypeID() else { return nil }
        return value.boolValue
    }

    // Missing is accepted for older service replies. A present malformed value
    // must fail closed because it cannot prove a terminal result is settled.
    static func outcomeUnknown(_ rawValue: Any?) -> Bool {
        guard let rawValue else { return false }
        return strictBoolean(rawValue) ?? true
    }
}

final class V3DeleteNativeSuccessRegistry: @unchecked Sendable {
    static let shared = V3DeleteNativeSuccessRegistry()
    static let retentionInterval: TimeInterval = 10 * 60
    static let maximumEntries = 512
    private let lock = NSLock()
    private var sessions: [String: Date] = [:]

    func record(sessionID: String, now: Date = Date()) {
        guard UUID(uuidString: sessionID) != nil else { return }
        lock.lock()
        pruneLocked(now: now)
        sessions[sessionID] = now.addingTimeInterval(Self.retentionInterval)
        if sessions.count > Self.maximumEntries {
            let oldest = sessions.sorted { $0.value < $1.value }
            for (id, _) in oldest.prefix(sessions.count - Self.maximumEntries) {
                sessions.removeValue(forKey: id)
            }
        }
        lock.unlock()
    }

    func contains(sessionID: String, now: Date = Date()) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        pruneLocked(now: now)
        guard sessions[sessionID] != nil else { return false }
        sessions[sessionID] = now.addingTimeInterval(Self.retentionInterval)
        return true
    }

    func remove(sessionID: String) {
        lock.lock()
        sessions.removeValue(forKey: sessionID)
        lock.unlock()
    }

    private func pruneLocked(now: Date) {
        sessions = sessions.filter { $0.value > now }
    }
}

// Shared state primitives used by the UI/backend and executable regression
// harnesses. These types deliberately carry no paths, credentials, or logs.
struct V3OperationAttemptState {
    private(set) var generation = UUID()
    private(set) var sessionID: String?
    private(set) var isTerminal = false
    private(set) var transitionInFlight = false

    mutating func begin() -> UUID {
        generation = UUID()
        sessionID = generation.uuidString
        isTerminal = false
        return generation
    }

    mutating func attach(sessionID: String) -> UUID? {
        guard let id = UUID(uuidString: sessionID), id.uuidString == sessionID else { return nil }
        generation = id
        self.sessionID = sessionID
        isTerminal = false
        transitionInFlight = false
        return id
    }

    mutating func bind(sessionID: String, generation: UUID) -> Bool {
        guard self.generation == generation, !isTerminal,
              self.sessionID == sessionID else { return false }
        return true
    }

    @discardableResult
    mutating func acceptStartFailure(generation: UUID) -> Bool {
        guard self.generation == generation, !isTerminal else { return false }
        isTerminal = true
        return true
    }

    func matches(generation: UUID, sessionID: String) -> Bool {
        self.generation == generation && self.sessionID == sessionID && !isTerminal
    }

    func owns(generation: UUID, sessionID: String) -> Bool {
        self.generation == generation && self.sessionID == sessionID
    }

    @discardableResult
    mutating func accept(state: String, generation: UUID, sessionID: String) -> Bool {
        guard matches(generation: generation, sessionID: sessionID) else { return false }
        if !["working", "awaitingPrompt", "cancelling", "reconciling"].contains(state) { isTerminal = true }
        return true
    }

    func ownsProvisionalResolution(generation: UUID, sessionID: String,
                                   currentState: String?, currentBackendSettled: Bool?,
                                   currentOutcomeUnknown: Bool, nextState: String?,
                                   nextBackendSettled: Bool?, nextOutcomeUnknown: Bool,
                                   nextOperation: String? = nil,
                                   verifiedDeleteCompletion: Bool = false) -> Bool {
        owns(generation: generation, sessionID: sessionID) && isTerminal &&
            V3OperationProvisionalOutcomePolicy.canResolve(
                currentState: currentState, currentBackendSettled: currentBackendSettled,
                currentOutcomeUnknown: currentOutcomeUnknown, nextState: nextState,
                nextBackendSettled: nextBackendSettled, nextOutcomeUnknown: nextOutcomeUnknown,
                nextOperation: nextOperation, verifiedDeleteCompletion: verifiedDeleteCompletion)
    }

    mutating func supersede() -> String? {
        let previousSession = sessionID
        generation = UUID()
        sessionID = nil
        isTerminal = true
        return previousSession
    }

    mutating func beginTransition() -> Bool {
        guard !transitionInFlight else { return false }
        transitionInFlight = true
        return true
    }

    mutating func endTransition() {
        transitionInFlight = false
    }
}

enum V3OperationCoverDismissalPolicy {
    static func mustConfirmBackendStop(isRunning: Bool, hasSession: Bool,
                                       sessionIsTerminal: Bool,
                                       hasUncertainSession: Bool,
                                       transitionInFlight: Bool) -> Bool {
        hasUncertainSession ||
            (!sessionIsTerminal && (isRunning || hasSession || transitionInFlight))
    }
}

struct V3OperationMutationRegistry {
    enum StartResult: Equatable { case started, cancelledBeforeStart, busy }
    enum CancelResult: Equatable { case active, recordedBeforeStart }

    private(set) var activeID: String?
    private var cancelledBeforeStart: [String: Date] = [:]

    mutating func begin(_ id: String, now: Date = Date()) -> StartResult {
        prune(now: now)
        if cancelledBeforeStart.removeValue(forKey: id) != nil { return .cancelledBeforeStart }
        guard activeID == nil else { return .busy }
        activeID = id
        return .started
    }

    mutating func cancel(_ id: String, now: Date = Date()) -> CancelResult {
        if activeID == id { return .active }
        cancelledBeforeStart[id] = now.addingTimeInterval(600)
        prune(now: now)
        return .recordedBeforeStart
    }

    @discardableResult
    mutating func finish(_ id: String) -> Bool {
        guard activeID == id else { return false }
        activeID = nil
        return true
    }

    private mutating func prune(now: Date) {
        cancelledBeforeStart = cancelledBeforeStart.filter { $0.value > now }
        guard cancelledBeforeStart.count > 256 else { return }
        let oldest = cancelledBeforeStart.sorted { $0.value < $1.value }
        for (id, _) in oldest.prefix(cancelledBeforeStart.count - 256) {
            cancelledBeforeStart.removeValue(forKey: id)
        }
    }
}

// V3_OPERATION_RECOVERY_JOURNAL_V1
// This record is shared by LiveContainer and the embedded SideStore service.
// It intentionally contains identifiers and allow-listed markers only. It has
// no timestamp: process age and elapsed time never prove device settlement.
struct V3OperationRecoveryRecord: Equatable {
    enum Phase: String, Equatable { case prepared, dispatched }
    let sessionID: String
    let kind: String
    let phase: Phase
    let stagedIPAToken: String?

    static let allowedKinds: Set<String> = [
        "install", "installURL", "installSharedIPA", "update", "refreshApp",
        "activate", "deactivate", "remove", "delete", "backup", "restore", "refreshAll"
    ]

    init?(sessionID: String, kind: String, phase: Phase, stagedIPAToken: String? = nil) {
        guard let id = UUID(uuidString: sessionID), id.uuidString == sessionID,
              Self.allowedKinds.contains(kind) else { return nil }
        if let stagedIPAToken {
            guard let token = UUID(uuidString: stagedIPAToken),
                  token.uuidString.lowercased() == stagedIPAToken else { return nil }
        }
        self.sessionID = sessionID
        self.kind = kind
        self.phase = phase
        self.stagedIPAToken = stagedIPAToken
    }

    var propertyListRepresentation: [String: Any] {
        var value: [String: Any] = ["version": 1, "session": sessionID,
            "kind": kind, "phase": phase.rawValue]
        if let stagedIPAToken { value["ipa"] = stagedIPAToken }
        return value
    }

    static func decodePropertyList(_ value: Any) -> V3OperationRecoveryRecord? {
        guard let plist = value as? [String: Any] else { return nil }
        let requiredKeys: Set<String> = ["version", "session", "kind", "phase"]
        let hasIPA = plist.keys.contains("ipa")
        guard let version = plist["version"] as? NSNumber,
              CFGetTypeID(version) != CFBooleanGetTypeID(), version.intValue == 1 else { return nil }
        guard Set(plist.keys) == (hasIPA ? requiredKeys.union(["ipa"]) : requiredKeys),
              let session = plist["session"] as? String,
              let kind = plist["kind"] as? String,
              let phaseRaw = plist["phase"] as? String,
              let phase = Phase(rawValue: phaseRaw) else { return nil }
        let token: String?
        if hasIPA {
            guard let value = plist["ipa"] as? String else { return nil }
            token = value
        } else {
            token = nil
        }
        return V3OperationRecoveryRecord(sessionID: session, kind: kind,
            phase: phase, stagedIPAToken: token)
    }
}

struct V3OperationRecoveryLease: Equatable {
    enum DispatchResult: Equatable { case reserved, alreadyOwned, blocked }
    private(set) var record: V3OperationRecoveryRecord?

    init(record: V3OperationRecoveryRecord? = nil) { self.record = record }

    mutating func reserve(sessionID: String, kind: String, stagedIPAToken: String? = nil) -> DispatchResult {
        guard let requested = V3OperationRecoveryRecord(sessionID: sessionID, kind: kind,
                phase: .prepared, stagedIPAToken: stagedIPAToken) else { return .blocked }
        guard let current = record else { record = requested; return .reserved }
        guard current.sessionID == requested.sessionID, current.kind == requested.kind,
              current.stagedIPAToken == requested.stagedIPAToken,
              current.phase == .prepared else { return .blocked }
        return .alreadyOwned
    }

    mutating func beginDispatch(sessionID: String, kind: String,
                                stagedIPAToken: String? = nil) -> Bool {
        guard let current = record, current.sessionID == sessionID,
              current.kind == kind, current.phase == .prepared,
              current.stagedIPAToken == stagedIPAToken,
              let dispatched = V3OperationRecoveryRecord(sessionID: sessionID, kind: kind,
                  phase: .dispatched, stagedIPAToken: stagedIPAToken) else { return false }
        record = dispatched
        return true
    }

    @discardableResult
    mutating func settle(sessionID: String, replySessionID: String?, state: String?,
                         backendSettled: Bool) -> Bool {
        guard let current = record, current.sessionID == sessionID,
              current.phase == .dispatched, replySessionID == sessionID, backendSettled,
              ["completed", "failed", "cancelled", "timedOut", "requiresSource", "waitingForAuthentication"].contains(state ?? "") else {
            return false
        }
        record = nil
        return true
    }

    @discardableResult
    mutating func reconcileAfterDeviceCheck(sessionID: String, userConfirmed: Bool) -> Bool {
        guard userConfirmed, record?.sessionID == sessionID else { return false }
        record = nil
        return true
    }

    @discardableResult
    mutating func clearPreparedAfterNotDispatched(sessionID: String, expectedRequestID: String,
                                                   replyRequestID: String?, operationNotDispatched: Bool) -> Bool {
        guard operationNotDispatched, replyRequestID == expectedRequestID,
              UUID(uuidString: expectedRequestID)?.uuidString == expectedRequestID,
              let current = record, current.sessionID == sessionID, current.phase == .prepared else { return false }
        record = nil
        return true
    }

    @discardableResult
    mutating func clearPreparedAfterConfirmedCancellation(sessionID: String, replySessionID: String?,
        state: String?, backendSettled: Bool, stopConfirmed: Bool, knownStarted: Bool) -> Bool {
        guard !knownStarted, let current = record,
              current.sessionID == sessionID, current.phase == .prepared,
              replySessionID == sessionID, state == "cancelled",
              backendSettled, stopConfirmed else { return false }
        record = nil
        return true
    }

    @discardableResult
    mutating func settleRefreshAdmission(runID: String, terminalState: String?,
                                         terminalConfirmed: Bool) -> Bool {
        guard terminalConfirmed, let current = record,
              current.sessionID == runID, current.kind == "refreshAll",
              (current.phase == .prepared ||
                (current.phase == .dispatched && terminalState != "notDispatched")),
              ["completed", "failed", "notDispatched"].contains(terminalState ?? "") else { return false }
        record = nil
        return true
    }

    @discardableResult
    mutating func clearPreparedRefreshAdmissionAfterRequestCancellation(runID: String) -> Bool {
        guard let current = record, current.sessionID == runID,
              current.kind == "refreshAll", current.phase == .prepared else { return false }
        record = nil
        return true
    }

    @discardableResult
    mutating func reconcileRefreshAdmissionAfterDeviceCheck(runID: String, userConfirmed: Bool) -> Bool {
        guard record?.kind == "refreshAll" else { return false }
        return reconcileAfterDeviceCheck(sessionID: runID, userConfirmed: userConfirmed)
    }

    var blocksMutation: Bool { record != nil }
    var protectedStagedIPAToken: String? { record?.stagedIPAToken }
}

// A staged IPA remains owned while any session task can still inspect it,
// preparation has not settled, or the global mutation registry still assigns
// the native mutation to that session. Age alone never releases a live lease.
enum V3StagedIPALeasePolicy {
    static func isLeased(hasOperationTask: Bool, preparationFinished: Bool,
                         ownsMutationRegistry: Bool) -> Bool {
        hasOperationTask || !preparationFinished || ownsMutationRegistry
    }
}

enum V3StagedIPACleanupFallbackPolicy {
    static func mayDeleteLocally(serviceReportsBusy: Bool,
                                 callerConfirmsNeverStartedOrSettled: Bool) -> Bool {
        callerConfirmsNeverStartedOrSettled && !serviceReportsBusy
    }
}

// Terminal responses are write-once. Callback and cancellation paths may race,
// so the first terminal result is authoritative and later results are ignored.
final class V3TerminalResponse: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String: Any]?

    @discardableResult
    func setIfEmpty(_ response: [String: Any]) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard storage == nil else { return false }
        storage = response
        return true
    }

    var value: [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    var isEmpty: Bool { if case nil = value { return true }; return false }
}

enum V3AuthSessionResponsePolicy {
    static func mayRespond(terminalIsEmpty: Bool, cancellationRequested: Bool,
                           promptMatches: Bool) -> Bool {
        terminalIsEmpty && !cancellationRequested && promptMatches
    }

    static func mayApplyReply(currentSessionID: String?, replySessionID: String,
                              cancellationInProgress: Bool,
                              submittedPromptID: String? = nil,
                              currentPromptID: String? = nil,
                              currentRevision: Int? = nil,
                              replyRevision: Int? = nil) -> Bool {
        guard !cancellationInProgress, currentSessionID == replySessionID else { return false }
        if let currentRevision {
            guard let replyRevision, replyRevision >= currentRevision else { return false }
        }
        guard let submittedPromptID else { return true }
        return currentPromptID == submittedPromptID
    }

    static func mayAcceptStartedSession(expectedSessionID: String, replySessionID: String?,
                                        currentSessionID: String?, cancellationInProgress: Bool) -> Bool {
        !cancellationInProgress && replySessionID == expectedSessionID &&
            currentSessionID == expectedSessionID
    }

    static func mayLaunchCreatedSession(sessionID: String, activeSessionID: String?,
                                        cancellationRequested: Bool, terminalIsEmpty: Bool,
                                        requestCancelled: Bool = false) -> Bool {
        activeSessionID == sessionID && !cancellationRequested && !requestCancelled && terminalIsEmpty
    }
}

enum V3AuthPollResponsePolicy {
    static func mayApply(currentSessionID: String?, replySessionID: String,
                         cancellationInProgress: Bool, currentRevision: Int,
                         replyRevision: Int?, currentPromptID: String?,
                         replyPromptID: String?) -> Bool {
        guard !cancellationInProgress, currentSessionID == replySessionID,
              let replyRevision, replyRevision >= currentRevision else { return false }
        if replyRevision == currentRevision, let currentPromptID,
           replyPromptID != currentPromptID { return false }
        return true
    }
}

enum V3AuthPromptSubmissionPolicy {
    static func mayShowFailure(currentSessionID: String?, submittedSessionID: String,
                               currentPromptID: String?, submittedPromptID: String,
                               cancellationInProgress: Bool) -> Bool {
        !cancellationInProgress && currentSessionID == submittedSessionID &&
            currentPromptID == submittedPromptID
    }
}

enum V3AuthPromptResponsePolicy {
    static func maySubmit(state: String, currentPromptID: String?, submittedPromptID: String,
                          isSubmitting: Bool, cancellationInProgress: Bool) -> Bool {
        state == "awaitingPrompt" && currentPromptID == submittedPromptID &&
            !isSubmitting && !cancellationInProgress
    }

    static func shouldClearSubmissionFailure(oldPromptID: String?, newPromptID: String?,
                                             state: String) -> Bool {
        state == "awaitingPrompt" && oldPromptID != newPromptID
    }

    static func failureMessage(_ error: Error) -> String {
        if let failure = error as? CombinedFailure {
            return "\(failure.safeMessage) \(failure.recovery)"
        }
        return "The verification response could not be confirmed. The exact underlying cause could not be safely identified. Check the sign-in status before trying again.\nError ID: SS-AUTH-C11"
    }

    static func diagnostics(_ error: Error) -> String {
        if let failure = error as? CombinedFailure { return failure.technicalDetails }
        return "schema=1 diagnostic_code=SS-AUTH-C11 builder_commit=\(V3DiagnosticBuild.commit) operation=authRespond stage=command code=failed correlation=unavailable underlying_domain=redacted underlying_code=redacted retryable=unknown"
    }

    static func blocksResubmission(_ error: Error) -> Bool {
        (error as? CombinedFailure)?.retryable == false
    }
}

enum V3TwoFactorRetryPolicy {
    static func shouldReuseCredentialsForCodeRetry(authFailureKind: String?) -> Bool {
        authFailureKind == "invalidCode"
    }

    static func recoveryMessage(authFailureKind: String?) -> String? {
        guard shouldReuseCredentialsForCodeRetry(authFailureKind: authFailureKind) else { return nil }
        return "The verification code was not accepted. Enter a new code and try again."
    }
}

struct V3AuthStartCancellationRegistry {
    private var cancelled: [String: Date] = [:]

    mutating func cancelBeforeStart(_ id: String, now: Date = Date()) -> Bool {
        guard let parsed = UUID(uuidString: id), parsed.uuidString == id else { return false }
        prune(now: now)
        cancelled[id] = now.addingTimeInterval(600)
        prune(now: now)
        return true
    }

    mutating func consume(_ id: String, now: Date = Date()) -> Bool {
        prune(now: now)
        return cancelled.removeValue(forKey: id) != nil
    }

    func contains(_ id: String, now: Date = Date()) -> Bool {
        guard let expiry = cancelled[id] else { return false }
        return expiry > now
    }

    mutating func prune(now: Date = Date()) {
        cancelled = cancelled.filter { $0.value > now }
        guard cancelled.count > 256 else { return }
        let oldest = cancelled.sorted { $0.value < $1.value }
        for (id, _) in oldest.prefix(cancelled.count - 256) { cancelled.removeValue(forKey: id) }
    }
}

enum V3DeleteReconciliationPolicy {
    static let callbackGrace: TimeInterval = 5
    static let libraryRecheckInterval: TimeInterval = 15
    static let maximumCallbackPollInterval: TimeInterval = 15

    static func shouldCheckLibrary(lastCheck: Date?, now: Date) -> Bool {
        guard let lastCheck else { return true }
        return now.timeIntervalSince(lastCheck) >= libraryRecheckInterval
    }

    static func shouldThrottleLibraryChecks(authoritativeAbsenceConfirmed: Bool,
                                            cancellationRequested: Bool) -> Bool {
        authoritativeAbsenceConfirmed || cancellationRequested
    }

    static func nextCallbackPollDelay(current: TimeInterval, backendPending: Bool,
                                      nativeUninstallSucceeded: Bool,
                                      appStillInLibrary: Bool,
                                      cancellationRequested: Bool = false) -> TimeInterval {
        if !backendPending {
            guard appStillInLibrary else { return 1.0 }
            let settledBase = current.isFinite && current > 0 ? current : 0.5
            return min(max(settledBase * 2, 1.0), maximumCallbackPollInterval)
        }
        guard cancellationRequested || (nativeUninstallSucceeded && !appStillInLibrary) else { return 1.0 }
        let base = current.isFinite && current > 0 ? current : 0.25
        return min(base * 2, maximumCallbackPollInterval)
    }

    static func shouldRequestCancellation(deadlineElapsed: Bool, backendPending: Bool,
                                         cancellationAlreadyRequested: Bool) -> Bool {
        deadlineElapsed && backendPending && !cancellationAlreadyRequested
    }

    static func callbackGraceElapsed(requestedAt: Date?, now: Date) -> Bool {
        guard let requestedAt else { return false }
        return now.timeIntervalSince(requestedAt) >= callbackGrace
    }

    static func shouldPublishOutcomeUnknown(backendPending: Bool, requestedAt: Date?,
                                           now: Date) -> Bool {
        backendPending && callbackGraceElapsed(requestedAt: requestedAt, now: now)
    }

    static func mayPublishVerifiedDeleteCompletion(backendPending: Bool,
                                                    nativeUninstallSucceeded: Bool,
                                                    appStillInLibrary: Bool,
                                                    reconciliationDeadlineElapsed: Bool) -> Bool {
        backendPending && nativeUninstallSucceeded && !appStillInLibrary &&
            reconciliationDeadlineElapsed
    }

    static func shouldReleaseMutationOwnership(backendSettled: Bool) -> Bool {
        backendSettled
    }
}

enum V3OperationSessionRetentionPolicy {
    static let terminalRetention: TimeInterval = 600

    static func shouldRefreshTerminalAt(terminalAccepted: Bool, backendSettled: Bool) -> Bool {
        terminalAccepted || backendSettled
    }

    static func isExpired(backendSettled: Bool, terminalAt: Date?, now: Date) -> Bool {
        guard backendSettled, let terminalAt else { return false }
        return now.timeIntervalSince(terminalAt) > terminalRetention
    }
}

enum V3OperationCompletionDisposition: Equatable {
    case notCompleted
    case completed
    case completedAwaitingBackendSettlement
    case outcomeUnknownAwaitingBackendSettlement
}

enum V3OperationCompletionPolicy {
    static func disposition(state: String, backendSettled: Bool?,
                            outcomeUnknown: Bool = false) -> V3OperationCompletionDisposition {
        if outcomeUnknown {
            return .outcomeUnknownAwaitingBackendSettlement
        }
        guard state == "completed" else { return .notCompleted }
        return backendSettled == true ? .completed : .completedAwaitingBackendSettlement
    }

    static func shouldContinuePolling(state: String, backendSettled: Bool?,
                                      outcomeUnknown: Bool = false) -> Bool {
        switch disposition(state: state, backendSettled: backendSettled,
                           outcomeUnknown: outcomeUnknown) {
        case .completedAwaitingBackendSettlement, .outcomeUnknownAwaitingBackendSettlement: return true
        case .notCompleted, .completed: return false
        }
    }

    static func shouldRetrySettlementPollFailure(state: String, backendSettled: Bool?,
                                                  outcomeUnknown: Bool,
                                                  cancellationRequested: Bool = false) -> Bool {
        shouldContinuePolling(state: state, backendSettled: backendSettled,
                              outcomeUnknown: outcomeUnknown) ||
            (state == "cancelling" && cancellationRequested)
    }

    static func requiresDeviceCheck(state: String, backendSettled: Bool?,
                                    deviceCheckConfirmed: Bool,
                                    outcomeUnknown: Bool = false) -> Bool {
        shouldContinuePolling(state: state, backendSettled: backendSettled,
                              outcomeUnknown: outcomeUnknown) && !deviceCheckConfirmed
    }

    static func mayDismiss(state: String, backendSettled: Bool?,
                           deviceCheckConfirmed: Bool = false,
                           outcomeUnknown: Bool = false) -> Bool {
        !requiresDeviceCheck(state: state, backendSettled: backendSettled,
                             deviceCheckConfirmed: deviceCheckConfirmed,
                             outcomeUnknown: outcomeUnknown)
    }

    static func pollInterval(state: String, backendSettled: Bool?,
                             outcomeUnknown: Bool = false) -> TimeInterval {
        shouldContinuePolling(state: state, backendSettled: backendSettled,
                              outcomeUnknown: outcomeUnknown) ? 5 : 1
    }

    static func nextSettlementPollRetryDelay(current: TimeInterval) -> TimeInterval {
        let base = current.isFinite && current > 0 ? current : 5
        if base < 5 { return 5 }
        return min(base * 2, 30)
    }
}

enum V3OperationProvisionalOutcomePolicy {
    static func canResolve(currentState: String?, currentBackendSettled: Bool?,
                           currentOutcomeUnknown: Bool, nextState: String?,
                           nextBackendSettled: Bool?, nextOutcomeUnknown: Bool,
                           nextOperation: String? = nil,
                           verifiedDeleteCompletion: Bool = false) -> Bool {
        let priorResultIsProvisional =
            ["reconciling", "failed", "cancelled"].contains(currentState ?? "") &&
            currentOutcomeUnknown && currentBackendSettled == false
        guard priorResultIsProvisional, !nextOutcomeUnknown else { return false }
        let settledTerminal = nextBackendSettled == true &&
            ["completed", "failed", "cancelled"].contains(nextState ?? "")
        let verifiedDeleteWhileCallbackPending = nextOperation == "delete" &&
            verifiedDeleteCompletion && nextState == "completed" && nextBackendSettled == false
        return settledTerminal || verifiedDeleteWhileCallbackPending
    }
}

// Cancellation is a request to stop. It is never itself a terminal result:
// the backend driver commits completed/failed/cancelled only after its native
// callback and required verification have settled.
final class V3OperationTerminalResponse: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [String: Any]?
    private var cancellationRequested = false

    @discardableResult
    func requestCancellation() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard storage == nil else { return false }
        cancellationRequested = true
        return true
    }

    var isCancellationRequested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancellationRequested
    }

    @discardableResult
    func setIfEmpty(_ response: [String: Any]) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard storage == nil else { return false }
        storage = response
        return true
    }

    // A reconciling record is provisional, not a terminal result. It can be
    // replaced once the backend callback settles, but ordinary terminal
    // responses remain write-once.
    @discardableResult
    func resolveProvisionalOutcome(_ response: [String: Any]) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard let current = storage,
              V3OperationProvisionalOutcomePolicy.canResolve(
                currentState: current["state"] as? String,
                currentBackendSettled: current["backendSettled"] as? Bool,
                currentOutcomeUnknown: current["outcomeUnknown"] as? Bool == true,
                nextState: response["state"] as? String,
                nextBackendSettled: response["backendSettled"] as? Bool,
                nextOutcomeUnknown: response["outcomeUnknown"] as? Bool == true,
                nextOperation: response["operation"] as? String,
                verifiedDeleteCompletion: V3OperationReplyFieldPolicy.strictBoolean(
                    response["verifiedDeleteCompletion"]) == true) else { return false }
        storage = response
        return true
    }

    @discardableResult
    func finishOrResolve(_ response: [String: Any], backendSettled: Bool) -> Bool {
        var resolved = response
        resolved["backendSettled"] = backendSettled
        return setIfEmpty(resolved) || resolveProvisionalOutcome(resolved)
    }

    var value: [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    var isEmpty: Bool { value == nil }

    func reply(sessionID: String, backendSettled: Bool) -> [String: Any]? {
        guard var response = value else { return nil }
        response["session"] = sessionID
        response["backendSettled"] = backendSettled
        return response
    }
}

// Owns pre-driver work such as resolving or downloading a URL IPA. The session
// is not stopped until this gate finishes; cancellation is forwarded to the
// concrete preparation task and callers can await its settlement.
final class V3OperationPreparationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var finished = false
    private var cancellationRequested = false
    private var cancellationAction: (() -> Void)?
    private var waiters: [CheckedContinuation<Void, Never>] = []

    var isFinished: Bool {
        lock.lock()
        defer { lock.unlock() }
        return finished
    }

    var isCancellationRequested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancellationRequested
    }

    var pendingWaiterCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return waiters.count
    }

    func installCancellation(_ action: @escaping () -> Void) {
        lock.lock()
        if finished {
            lock.unlock()
            return
        }
        cancellationAction = action
        let shouldCancel = cancellationRequested
        lock.unlock()
        if shouldCancel { action() }
    }

    @discardableResult
    func requestCancellation() -> Bool {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return false
        }
        let firstRequest = !cancellationRequested
        cancellationRequested = true
        let action = firstRequest ? cancellationAction : nil
        lock.unlock()
        action?()
        return true
    }

    func finish() {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        cancellationAction = nil
        let pending = waiters
        waiters.removeAll()
        lock.unlock()
        for continuation in pending { continuation.resume() }
    }

    func wait() async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            lock.lock()
            if finished {
                lock.unlock()
                continuation.resume()
            } else {
                waiters.append(continuation)
                lock.unlock()
            }
        }
    }
}

struct V3SettingsWriteGeneration {
    private var values: [String: UInt64] = [:]
    private var pending: [String: Set<UInt64>] = [:]

    mutating func begin(_ key: String) -> UInt64 {
        let next = (values[key] ?? 0) &+ 1
        values[key] = next
        pending[key, default: []].insert(next)
        return next
    }

    mutating func finish(_ generation: UInt64, for key: String) {
        pending[key]?.remove(generation)
        if pending[key]?.isEmpty == true { pending.removeValue(forKey: key) }
    }

    func isPending(_ generation: UInt64, for key: String) -> Bool {
        pending[key]?.contains(generation) == true
    }

    func hasPendingWrites(for key: String) -> Bool {
        pending[key]?.isEmpty == false
    }

    func isCurrent(_ generation: UInt64, for key: String) -> Bool {
        values[key] == generation
    }

    func current(for key: String) -> UInt64 {
        values[key] ?? 0
    }

    func isUnchanged(since captured: V3SettingsWriteGeneration) -> Bool {
        values == captured.values && pending.isEmpty && captured.pending.isEmpty
    }

    // A read can start before OR during a write and return after it settles.
    // Reject both cases per key, retaining unrelated authoritative read values.
    func mergingSnapshot<Value>(_ snapshot: [String: Value], into currentValues: [String: Value],
                                captured: V3SettingsWriteGeneration) -> [String: Value] {
        var result = currentValues
        for key in Set(currentValues.keys).union(snapshot.keys)
            where current(for: key) == captured.current(for: key) &&
                  pending[key] == nil && captured.pending[key] == nil {
            result[key] = snapshot[key]
        }
        return result
    }
}

enum V3RefreshResultVerifier {
    static func verified<Value>(expectedBundleID: String,
                                results: [String: Result<Value, Error>],
                                bundleIdentifier: (Value) -> String) throws -> Value {
        guard let result = results[expectedBundleID] else { throw CombinedRefreshVerificationError.missingResult }
        switch result {
        case .failure(let error): throw error
        case .success(let value):
            guard bundleIdentifier(value) == expectedBundleID else { throw CombinedRefreshVerificationError.staleResult }
            return value
        }
    }
}

// Customization reviews every target extension, including fresh installs
// (where upstream reports no excess extensions). Only an empty target skips UI.
enum V3ExtensionRemovalPromptPolicy {
    static func decide<Element: Hashable, Decision>(
        targetExtensions: Set<Element>,
        whenEmpty: Decision,
        prompt: () async throws -> Decision
    ) async rethrows -> Decision {
        guard !targetExtensions.isEmpty else { return whenEmpty }
        return try await prompt()
    }
}

enum V3RefreshAllPhase: String {
    case idle, starting, refreshing, verifying, completed, failed
}

enum V3RefreshAllButtonPresentationPolicy {
    static func title(phase: V3RefreshAllPhase, activeRunID: String) -> String {
        switch phase {
        case .starting: return "Starting Refresh..."
        case .refreshing: return "Refreshing..."
        case .verifying: return "Verifying..."
        case .idle where !activeRunID.isEmpty: return "Refresh Already Running"
        default: return "Refresh All"
        }
    }

    static func explainsConcurrentRun(phase: V3RefreshAllPhase, activeRunID: String) -> Bool {
        phase == .idle && !activeRunID.isEmpty
    }
}

enum V3RefreshAllTerminalEvidencePolicy {
    private static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              ["c", "s", "i", "l", "q", "C", "S", "I", "L", "Q"].contains(String(cString: number.objCType)) else {
            return nil
        }
        return number.intValue
    }

    static func verifiedSummary(_ summary: [String: Any]?, record: [String: Any],
                                runID: String) -> Bool {
        guard let summary,
              integer(summary["version"]) == 2,
              summary["schema"] as? String == "LiveContainerRefreshManifestSummaryV2",
              summary["run_id"] as? String == runID,
              let verified = summary["verified"] as? NSNumber,
              CFGetTypeID(verified) == CFBooleanGetTypeID(), verified.boolValue,
              let expectedCount = integer(summary["expected_count"]),
              expectedCount > 0, expectedCount <= 1024,
              integer(summary["result_count"]) == expectedCount,
              integer(summary["failed_count"]) == 0,
              let skippedCount = integer(summary["skipped_count"]),
              skippedCount >= 0, skippedCount <= 1024,
              let requestedCount = integer(summary["requested_count"]),
              requestedCount <= 1024,
              expectedCount + skippedCount == requestedCount,
              record["run_id"] as? String == runID,
              record["state"] as? String == "completed",
              record["terminal_intent"] as? String == "verified",
              record["health"] as? String == "REFRESH_SUCCEEDED",
              record["manifest_run_id"] as? String == runID else { return false }
        return true
    }

    static func count(_ key: String, in summary: [String: Any]?) -> Int? {
        guard let summary else { return nil }
        return integer(summary[key])
    }
}

// A result dictionary is written before the scheduler verifies it, including
// failures. Home must consume settled scheduler evidence, never mere presence.
enum V3HomeRefreshVerificationPolicy {
    static func isVerified(manifest: [String: Any]?, ledger: [String: Any],
                           activeRunID: String?, hostHandoffPending: Bool,
                           uncertainMutationRunID: String?) -> Bool {
        guard activeRunID?.isEmpty != false, !hostHandoffPending,
              uncertainMutationRunID?.isEmpty != false,
              let manifest, let runID = manifest["run_id"] as? String,
              CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let record = ledger[runID] as? [String: Any],
              let summary = record["manifest_summary"] as? [String: Any],
              V3RefreshAllTerminalEvidencePolicy.verifiedSummary(summary, record: record, runID: runID),
              let expected = manifest["expected_ids"] as? [String],
              let results = manifest["results"] as? [[String: Any]],
              summary["expected_count"] as? Int == expected.count,
              summary["result_count"] as? Int == results.count,
              summary["skipped_count"] as? Int == (manifest["skipped_ids"] as? [String] ?? []).count,
              summary["requested_count"] as? Int == (manifest["requested_ids"] as? [String] ?? []).count else {
            return false
        }
        // A completed result set can still contain failures. The canonical
        // coverage check above already requires actual plist boolean values.
        return results.allSatisfy { $0["success"] as? Bool == true }
    }
}

enum V3SetupRefreshTerminalOutcome: Equatable {
    case pending
    case failed
    case completedUnverified
    case verified
}

enum V3SetupRefreshTerminalEvidencePolicy {
    static func outcome(state: String, hasVerifiedManifest: Bool,
                        hasVerifiedSummary: Bool) -> V3SetupRefreshTerminalOutcome {
        switch state {
        case "failed": return .failed
        case "completed":
            return hasVerifiedManifest || hasVerifiedSummary ? .verified : .completedUnverified
        default: return .pending
        }
    }
}

// Request identity, rather than process-local notifications or global health,
// owns the Home refresh UI. A terminal record is absorbing for this attempt.
struct V3RefreshAllAttemptState {
    private(set) var requestID = ""
    private(set) var runID = ""
    private(set) var phase: V3RefreshAllPhase = .idle
    private(set) var terminalMessage = ""

    var isTerminal: Bool { phase == .completed || phase == .failed }

    mutating func begin(requestID: String) {
        self.requestID = requestID
        runID = ""
        phase = .starting
        terminalMessage = ""
    }

    @discardableResult
    mutating func observe(_ record: [String: Any], schedulerHealth: String? = nil,
                          activeRunID: String? = nil) -> Bool {
        guard !isTerminal,
              record["request_id"] as? String == requestID,
              let observedRunID = record["run_id"] as? String,
              UUID(uuidString: observedRunID) != nil else { return false }
        _ = schedulerHealth
        _ = activeRunID
        if runID.isEmpty { runID = observedRunID }
        guard runID == observedRunID else { return false }

        switch record["state"] as? String {
        case "running":
            if phase == .starting { phase = .refreshing }
        case "verifying":
            phase = .verifying
        case "completed":
            // Health and activeRun defaults may be observed out of order. The
            // correlated terminal record is authoritative, including when a
            // stale activeRun value is still visible to this view.
            let manifest = record["manifest"] as? [String: Any]
            let hasVerifiedManifest = Self.manifestIsVerified(manifest, runID: runID)
            let hasVerifiedSummary = V3RefreshAllTerminalEvidencePolicy.verifiedSummary(
                record["manifest_summary"] as? [String: Any], record: record, runID: runID)
            guard hasVerifiedManifest || hasVerifiedSummary else {
                phase = .failed
                terminalMessage = "Refresh reported completion without a matching verified manifest."
                return true
            }
            phase = .completed
            let skippedCount = (manifest?["skipped_ids"] as? [String])?.count ??
                V3RefreshAllTerminalEvidencePolicy.count("skipped_count",
                    in: record["manifest_summary"] as? [String: Any]) ?? 0
            terminalMessage = skippedCount == 0
                ? "Refresh completed. All requested app results were verified."
                : "Refresh completed. Results for this run were verified; \(skippedCount) running app(s) were skipped."
        case "failed":
            phase = .failed
            guard let failureWire = record["failure"] as? [String: Any],
                  let failure = CombinedFailure.decode(failureWire, expectedID: runID),
                  failure.operation == "refresh" else {
                terminalMessage = "Refresh failed, but no matching safe cause was available."
                return true
            }
            terminalMessage = failure.safeMessage
        default:
            return false
        }
        return true
    }

    mutating func markDidNotStart() {
        guard !isTerminal else { return }
        phase = .failed
        terminalMessage = "Refresh did not start." + "\nError ID: SS-CMD-D047"
    }

    mutating func markTimedOut() {
        guard !isTerminal else { return }
        phase = .failed
        terminalMessage = "Refresh did not reach a verified terminal result."
    }

    mutating func failBeforeStart(message: String) {
        guard !isTerminal else { return }
        phase = .failed
        terminalMessage = message
    }

    mutating func acknowledge() {
        requestID = ""
        runID = ""
        phase = .idle
        terminalMessage = ""
    }

    static func record(in ledger: [String: Any], requestID: String,
                       runID: String? = nil) -> [String: Any]? {
        let records = ledger.values.compactMap { $0 as? [String: Any] }
        return records.first { record in
            guard record["request_id"] as? String == requestID,
                  let recordRunID = record["run_id"] as? String,
                  UUID(uuidString: recordRunID) != nil else { return false }
            return runID == nil || recordRunID == runID
        }
    }

    private static func manifestIsVerified(_ manifest: [String: Any]?, runID: String) -> Bool {
        guard let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              let results = manifest["results"] as? [[String: Any]] else { return false }
        return results.allSatisfy { $0["success"] as? Bool == true }
    }
}

enum V3RefreshAllFailureDiagnostics {
    static func withoutRunRecord(requestID: String, runID: String?, message: String,
                                 health: String) -> String? {
        guard let request = UUID(uuidString: requestID), request.uuidString == requestID else { return nil }
        let safeRunID: String
        if let runID, let parsed = UUID(uuidString: runID), parsed.uuidString == runID {
            safeRunID = runID
        } else {
            safeRunID = "not_started"
        }
        let safeCorrelation = safeRunID == "not_started" ? requestID : safeRunID
        func safeLine(_ value: String) -> String {
            String(value.filter { $0.isASCII && $0 != "\n" && $0 != "\r" }.prefix(512))
        }
        return [
            "schema=1", "diagnostic_code=SS-REFRESH-UNKNOWN", "builder_commit=\(V3DiagnosticBuild.commit)", "request_id=\(requestID)", "manual_refresh_request=\(requestID)",
            "run_id=\(safeRunID)", "state=failed", "operation=refresh", "stage=unknown",
            "code=unknown", "correlation=\(safeCorrelation)",
            "underlying_domain=redacted", "underlying_code=unknown", "retryable=unknown",
            "safe_cause=unknown", "source_step=unknown", "health=\(safeLine(health))",
            "safe_message=\(safeLine(message))"
        ].joined(separator: "\n")
    }

    static func text(requestID: String, runID: String,
                     record: [String: Any]) -> String? {
        guard UUID(uuidString: requestID) != nil, UUID(uuidString: runID) != nil,
              record["request_id"] as? String == requestID,
              record["run_id"] as? String == runID,
              record["state"] as? String == "failed" else { return nil }
        let failureWire = record["failure"] as? [String: Any]
        let failure = failureWire.flatMap { CombinedFailure.decode($0, expectedID: runID) }
        let manifest = record["manifest"] as? [String: Any]
            ?? record["manifest_summary"] as? [String: Any] ?? [:]
        func safeIDs(_ key: String) -> String {
            guard let values = manifest[key] as? [String] else { return "unknown" }
            let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
            return values.prefix(64).map { value in
                String(value.filter { character in
                    character.unicodeScalars.allSatisfy { allowed.contains($0) }
                }.prefix(160))
            }.joined(separator: ",")
        }
        func recordScalar(_ key: String) -> String {
            let value = (record[key] as? String ?? "unknown")
            return String(value.filter { $0.isASCII && $0 != "\n" && $0 != "\r" }.prefix(80))
        }
        if failure?.operation != "refresh" {
            return [
                "schema=1", "diagnostic_code=SS-REFRESH-UNKNOWN", "builder_commit=\(V3DiagnosticBuild.commit)", "request_id=\(requestID)", "manual_refresh_request=\(requestID)", "run_id=\(runID)",
                "state=failed", "operation=refresh", "stage=unknown",
                "code=staleResult", "correlation=\(runID)",
                "underlying_domain=redacted", "underlying_code=unknown",
                "retryable=unknown", "safe_cause=unknown", "source_step=unknown",
                "source=\(recordScalar("source"))", "origin=\(recordScalar("origin"))",
                "network_preflight=\(recordScalar("network_preflight"))",
                "active_run_id=\(recordScalar("active_run_id"))", "health=\(recordScalar("health"))",
                "terminal_ledger_state=failed", "manifest_run_id=\(recordScalar("manifest_run_id"))",
                "target_app_ids=\(safeIDs("requested_ids"))",
                "requested_app_ids=\(safeIDs("requested_ids"))",
                "attempted_app_ids=\(safeIDs("expected_ids"))",
                "skipped_app_ids=\(safeIDs("skipped_ids"))",
                "safe_message=Refresh failed, but no matching safe cause was available."
            ].joined(separator: "\n")
        }
        guard let failure else { return nil }
        let retryable = failure.retryable.map { $0 ? "true" : "false" } ?? "unknown"
        let underlying = CombinedFailure.safeDiagnosticUnderlying(domain: failure.underlyingDomain,
                                                                    code: failure.underlyingCode)
        return [
            "schema=1",
            "diagnostic_code=\(failure.diagnosticCode)",
            "builder_commit=\(V3DiagnosticBuild.commit)",
            "request_id=\(requestID)",
            "manual_refresh_request=\(requestID)",
            "run_id=\(runID)",
            "state=failed",
            "source=\(recordScalar("source"))",
            "origin=\(recordScalar("origin"))",
            "network_preflight=\(recordScalar("network_preflight"))",
            "active_run_id=\(recordScalar("active_run_id"))",
            "health=\(recordScalar("health"))",
            "terminal_ledger_state=failed",
            "manifest_run_id=\(recordScalar("manifest_run_id"))",
            "target_app_ids=\(safeIDs("requested_ids"))",
            "requested_app_ids=\(safeIDs("requested_ids"))",
            "attempted_app_ids=\(safeIDs("expected_ids"))",
            "skipped_app_ids=\(safeIDs("skipped_ids"))",
            "operation=\(failure.operation)",
            "stage=\(failure.stage.rawValue)",
            "code=\(failure.code.rawValue)",
            "correlation=\(failure.correlationID)",
            "underlying_domain=\(underlying.domain)",
            "underlying_code=\(underlying.code)",
            "retryable=\(retryable)",
            "safe_cause=\(failure.safeCause?.rawValue ?? "unknown")",
            "source_step=\(failure.sourceStep?.rawValue ?? "unknown")",
            "safe_message=\(failure.safeMessage.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\r", with: " "))"
        ].joined(separator: "\n")
    }
}

// V3_STATUS_PRESENTATION_V1
// One reusable semantic status model. Success, warning and failure were drawn
// with almost the same treatment in the operation sheet, Sources, Setup
// Assistant, Health and install flows, so a red failure and a grey informational
// line were hard to tell apart. Every state carries an icon AND a text label so
// the meaning never depends on colour alone.
enum V3StatusSeverity: String, Equatable, CaseIterable {
    case working
    case completed
    case warning
    case failed
    case cancelled
    case unknown

    var icon: String {
        switch self {
        case .working: return "arrow.triangle.2.circlepath"
        case .completed: return "checkmark.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .failed: return "xmark.circle.fill"
        case .cancelled: return "slash.circle"
        case .unknown: return "questionmark.circle"
        }
    }

    /// The colour used alongside the icon and the text.
    var severityName: String {
        switch self {
        case .working: return "working"
        case .completed: return "success"
        case .warning: return "warning"
        case .failed: return "failure"
        case .cancelled: return "cancelled"
        case .unknown: return "unknown"
        }
    }

    var isFailure: Bool { self == .failed }
    var isSuccess: Bool { self == .completed }
    /// Only a genuine success is presented as a tick.
    var showsCheckmark: Bool { self == .completed }
}

struct V3StatusPresentation: Equatable {
    let severity: V3StatusSeverity
    let title: String
    let detail: String

    var icon: String { severity.icon }
    var severityName: String { severity.severityName }
    var isFailure: Bool { severity.isFailure }
    var isSuccess: Bool { severity.isSuccess }

    init(severity: V3StatusSeverity, title: String, detail: String = "") {
        self.severity = severity
        self.title = title
        self.detail = detail
    }

    /// Maps a product state word onto the shared severity model.
    static func severity(forState state: String) -> V3StatusSeverity {
        switch state {
        case "complete", "completed", "verified", "ready", "success": return .completed
        case "failed", "error": return .failed
        case "warning", "actionRequired", "needsAttention": return .warning
        case "running", "checking", "working", "loading", "inProgress": return .working
        case "cancelled", "canceled": return .cancelled
        default: return .unknown
        }
    }

    /// V3_RELOAD_STATUS_VISIBILITY_V1: loading wins over connected. The previous
    /// ordering rendered a green "Active & Connected" while a reload was
    /// actively running, so the button appeared to do nothing.
    static func connectionState(connected: Bool, loading: Bool) -> V3StatusPresentation {
        if loading {
            return V3StatusPresentation(severity: .working, title: "Reloading Status...")
        }
        if connected {
            return V3StatusPresentation(severity: .completed, title: "Connected")
        }
        return V3StatusPresentation(severity: .failed, title: "Not Connected")
    }
}

// V3_USER_FACING_ISSUE_V1
// The global alert used to offer "Retry Connection" for essentially every
// failure, which trained users to read every problem as a networking problem.
// A source failure, a certificate failure, an auth failure and a pairing failure
// each get the action that can actually resolve them. Connection evidence opens
// Connection Settings; it does not claim that reloading status retried a mutation.
enum V3IssueAction: String, Equatable, CaseIterable {
    case retrySource
    case reloadSources
    case reloadStatus
    case openCertificates
    case openAccount
    case showPairingSetup
    case openConnectionCheck
    case chooseIPA
    case openSetup
    case openSources
    case dismiss

    var title: String {
        switch self {
        case .retrySource: return "Retry Source"
        case .reloadSources: return "Reload Sources"
        case .reloadStatus: return "Reload Status"
        case .openCertificates: return "Open Certificates"
        case .openAccount: return "Open Account & Signing"
        case .showPairingSetup: return "Show Pairing Setup"
        case .openConnectionCheck: return "Open Connection Settings"
        case .chooseIPA: return "Choose IPA Again"
        case .openSetup: return "Open Setup Assistant"
        case .openSources: return "Open Sources"
        case .dismiss: return "OK"
        }
    }

    /// The screen this action opens, or nil for an action that re-requests.
    var destination: String? {
        switch self {
        case .openCertificates: return "certificates"
        case .openAccount: return "signIn"
        case .showPairingSetup: return "pairing"
        case .openConnectionCheck: return "connection"
        case .chooseIPA: return "ipa"
        case .openSetup: return "setup"
        case .retrySource, .reloadSources, .openSources: return "sources"
        case .reloadStatus: return nil
        case .dismiss: return nil
        }
    }
}

// V3_SIGNOUT_AUTHORITATIVE_POSTCONDITION_V1: upstream signOut can return after
// swallowing a Core Data deactivation save failure. The host therefore reports
// success only when the returned authoritative snapshot explicitly confirms all
// three sign-out facts. Missing facts remain unknown; they are never coerced to
// false for the success decision.
enum V3SignOutOutcome: Equatable {
    case confirmed
    case accountStateRemains
    case authenticationRemains
    case snapshotIncomplete
}

enum V3SignOutOutcomePolicy {
    static func resolve(authenticated: Bool?, activeAccountPresent: Bool?,
                        activeTeamPresent: Bool?) -> V3SignOutOutcome {
        guard let authenticated, let activeAccount = activeAccountPresent,
              let activeTeam = activeTeamPresent else {
            return .snapshotIncomplete
        }
        if authenticated { return .authenticationRemains }
        if activeAccount || activeTeam { return .accountStateRemains }
        return .confirmed
    }

    static func successNotice(for outcome: V3SignOutOutcome) -> String? {
        outcome == .confirmed ? "Signed out successfully." : nil
    }

    static func whatHappened(for outcome: V3SignOutOutcome) -> String? {
        switch outcome {
        case .confirmed: return nil
        case .accountStateRemains:
            return "Sign-in credentials were cleared, but SideStore still reports an active account or team." + "\nError ID: SS-AUTH-D094"
        case .authenticationRemains:
            return "SideStore still reports an active sign-in. Sign-out is not confirmed." + "\nError ID: SS-AUTH-D095"
        case .snapshotIncomplete:
            return "SideStore did not return enough account state to confirm sign-out." + "\nError ID: SS-AUTH-D060"
        }
    }

    static func whatToDo(for outcome: V3SignOutOutcome) -> String? {
        guard outcome != .confirmed else { return nil }
        switch outcome {
        case .confirmed: return nil
        case .accountStateRemains:
            return "Reload status. If the account or team remains active, try Sign Out again."
        case .authenticationRemains:
            return "Reload status to check the current account state, then try Sign Out again if it remains signed in."
        case .snapshotIncomplete:
            return "Reload status before continuing. If SideStore still reports a signed-in account, try Sign Out again."
        }
    }
}

enum V3AnisetteFailureGuidance {
    static func message(_ failure: CombinedFailure) -> String? {
        guard failure.operation.lowercased().hasPrefix("anisette") else { return nil }
        if failure.code == .cancelled {
            return "What happened: The Anisette Servers request was cancelled.\nWhat you can do: Reopen Anisette Servers to check the current state before trying again.\n\(failure.diagnosticLabel)"
        }
        guard failure.stage == .network ||
              failure.safeCause == .networkConnectionLost ||
              failure.safeCause == .networkTimedOut ||
              failure.safeCause == .networkUnavailable else { return nil }
        return "What happened: SideStore could not reach the configured Anisette server.\nWhat you can do: Check its address and your network, then try again. This does not show that LocalDevVPN is unavailable.\n\(failure.diagnosticLabel)"
    }
}

enum V3SideJITReachabilityFeedback {
    static let unreachable = "The SideJIT server could not be reached. Check its address and network, then try again." + "\nError ID: SS-NET-D061"

    static func reachable(httpStatusCode: Int?) -> String {
        httpStatusCode.map { "Reachable (HTTP \($0))." } ?? "Reachable."
    }
}

struct V3UserFacingIssue: Equatable {
    let title: String
    let severity: V3StatusSeverity
    let whatHappened: String
    let whatToDo: String
    let technicalDetails: String
    let primaryAction: V3IssueAction
    let secondaryAction: V3IssueAction
    let recoveryDestination: String?
    let retryDisposition: V3RetryDisposition

    /// The single place that decides which action a failure deserves. Selection
    /// is driven by the typed operation, stage and safe cause, never by a
    /// numeric code or by the mere fact that a request failed.
    static func make(operation: String, stage: String, code: String,
                     safeCause: String?, sourceStep: String?, retryable: Bool?,
                     whatHappened: String, whatToDo: String, technicalDetails: String) -> V3UserFacingIssue {
        let anisetteNetworkFailure = operation.lowercased().hasPrefix("anisette") &&
            [CombinedFailure.SafeCause.networkConnectionLost.rawValue,
             CombinedFailure.SafeCause.networkTimedOut.rawValue,
             CombinedFailure.SafeCause.networkUnavailable.rawValue].contains(safeCause ?? "")
        let anisetteServerUnavailable = operation.lowercased().hasPrefix("anisette") &&
            safeCause == CombinedFailure.SafeCause.anisetteServerUnavailable.rawValue
        let destination: String? = {
            // A remote Anisette server outage is service evidence even if an
            // upstream caller labels the boundary as `.network`. Do not let
            // the generic stage fallback send it to LocalDevVPN settings.
            if anisetteNetworkFailure || anisetteServerUnavailable { return nil }
            if safeCause == CombinedFailure.SafeCause.pairingRequired.rawValue ||
               safeCause == CombinedFailure.SafeCause.invalidPairingFile.rawValue { return "pairing" }
            if safeCause == CombinedFailure.SafeCause.authResponseCapacityUnavailable.rawValue { return "signIn" }
            if safeCause == CombinedFailure.SafeCause.keychainSignOutFailed.rawValue { return "signIn" }
            if safeCause == CombinedFailure.SafeCause.sourceRemoveFailed.rawValue ||
               safeCause == CombinedFailure.SafeCause.sourceRemoveBusy.rawValue { return "sources" }
            if [CombinedFailure.SafeCause.signingNetworkConnectionLost.rawValue,
                CombinedFailure.SafeCause.signingNetworkTimedOut.rawValue,
                CombinedFailure.SafeCause.signingNetworkUnavailable.rawValue].contains(safeCause ?? "") {
                return "connection"
            }
            if operation == "source" && stage == CombinedFailure.Stage.serviceReadiness.rawValue {
                return "sources"
            }
            if stage == CombinedFailure.Stage.authentication.rawValue { return "signIn" }
            if stage == CombinedFailure.Stage.filePreparation.rawValue { return "ipa" }
            if sourceStep == CombinedFailure.SourceStep.certificateValidation.rawValue
                || safeCause == CombinedFailure.SafeCause.certificateUnavailable.rawValue {
                return "certificates"
            }
            if operation == "source" || sourceStep == CombinedFailure.SourceStep.manifestParsing.rawValue
                || sourceStep == CombinedFailure.SourceStep.sourceDownload.rawValue {
                return "sources"
            }
            // Only these stages actually implicate connectivity or readiness.
            if stage == CombinedFailure.Stage.network.rawValue
                || stage == CombinedFailure.Stage.coreDevice.rawValue
                || stage == CombinedFailure.Stage.cdTunnel.rawValue
                || stage == CombinedFailure.Stage.rsdDiscovery.rawValue
                || stage == CombinedFailure.Stage.rsdService.rawValue
                || stage == CombinedFailure.Stage.lockdownConnection.rawValue
                || stage == CombinedFailure.Stage.uniqueDeviceID.rawValue
                || stage == CombinedFailure.Stage.heartbeat.rawValue
                || stage == CombinedFailure.Stage.endpointSelection.rawValue
                || safeCause == CombinedFailure.SafeCause.networkConnectionLost.rawValue
                || safeCause == CombinedFailure.SafeCause.networkTimedOut.rawValue
                || safeCause == CombinedFailure.SafeCause.networkUnavailable.rawValue
                || safeCause == CombinedFailure.SafeCause.wifiUnavailable.rawValue
                || safeCause == CombinedFailure.SafeCause.localDevVPNUnavailable.rawValue {
                return "connection"
            }
            if stage == CombinedFailure.Stage.provisioning.rawValue {
                return "setup"
            }
            return nil
        }()

        let primary: V3IssueAction = {
            switch destination {
            case "certificates": return .openCertificates
            case "signIn": return .openAccount
            case "pairing": return .showPairingSetup
            case "ipa": return .chooseIPA
            case "sources":
                if safeCause == CombinedFailure.SafeCause.sourceRemoveFailed.rawValue ||
                   safeCause == CombinedFailure.SafeCause.sourceRemoveBusy.rawValue { return .reloadSources }
                if safeCause == CombinedFailure.SafeCause.knownSourcePolicyNetworkFailure.rawValue ||
                    safeCause == CombinedFailure.SafeCause.knownSourcePolicyInvalidResponse.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceInvalidManifest.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceInvalidURL.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceBlocked.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceChangedID.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceDuplicate.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceUnsupported.rawValue ||
                    safeCause == CombinedFailure.SafeCause.sourceValidationFailed.rawValue {
                    return .openSources
                }
                if [CombinedFailure.SafeCause.responseEncodingFailed.rawValue,
                    CombinedFailure.SafeCause.responseTooLarge.rawValue,
                    CombinedFailure.SafeCause.responseCapacityUnavailable.rawValue,
                    CombinedFailure.SafeCause.operationInProgress.rawValue].contains(safeCause ?? "") {
                    return .dismiss
                }
                if stage == CombinedFailure.Stage.serviceReadiness.rawValue { return .openSources }
                return .retrySource
            case "setup": return .openSetup
            // Reloading a snapshot does not retry the failed mutation. Send the
            // user to the connection settings that can resolve this evidence.
            case "connection": return .openConnectionCheck
            default:
                // No evidence points anywhere specific. Never assume networking.
                return .dismiss
            }
        }()

        let disposition: V3RetryDisposition = {
            if safeCause == CombinedFailure.SafeCause.responseCapacityUnavailable.rawValue ||
               safeCause == CombinedFailure.SafeCause.authResponseCapacityUnavailable.rawValue {
                return .prerequisite
            }
            if retryable == false { return .blocked }
            if destination == "connection" && retryable == true { return .allowed }
            if retryable == true { return .allowed }
            return .unknown
        }()

        return V3UserFacingIssue(
            title: "SideStore",
            severity: .failed,
            whatHappened: whatHappened,
            whatToDo: anisetteNetworkFailure
                ? "Check the configured Anisette server and your network, then try again."
                : whatToDo,
            technicalDetails: technicalDetails,
            primaryAction: primary,
            secondaryAction: .dismiss,
            recoveryDestination: destination,
            retryDisposition: disposition)
    }

    /// Builds an issue from a typed failure, preserving its privacy-safe text.
    static func make(_ failure: CombinedFailure) -> V3UserFacingIssue {
        make(operation: failure.operation, stage: failure.stage.rawValue, code: failure.code.rawValue,
             safeCause: failure.safeCause?.rawValue, sourceStep: failure.sourceStep?.rawValue,
             retryable: failure.retryable, whatHappened: failure.safeMessage,
             whatToDo: failure.recovery, technicalDetails: failure.technicalDetails)
    }

    /// One-line summary, kept short enough for a copyable alert body.
    var summary: String { whatHappened }
}

// V3_CATALOG_ROW_POLICY_V1
// The catalog view deduplicated by snapshotting the accumulated IDs before
// filtering a page, so an identifier repeated inside one page passed twice. The
// rule lives here so the real behaviour is executable rather than asserted as
// source text.
enum V3CatalogRowPolicy {
    static func identifier(of row: [String: Any]) -> String? {
        guard let value = row["identifier"] as? String, !value.isEmpty else { return nil }
        return value
    }

    static func isDisplayable(_ row: [String: Any]) -> Bool {
        identifier(of: row) != nil && row["name"] as? String != nil
    }

    /// Removes duplicates by identifier, preserving first-seen order, across
    /// every page seen so far. Rows without a usable identifier are rejected
    /// rather than silently kept, because they cannot be deduplicated or
    /// installed.
    static func dedupe(_ rows: [[String: Any]]) -> [[String: Any]] {
        var seen = Set<String>()
        var result: [[String: Any]] = []
        result.reserveCapacity(rows.count)
        for row in rows {
            guard let identifier = identifier(of: row) else { continue }
            if seen.insert(identifier).inserted { result.append(row) }
        }
        return result
    }

}

struct V3CatalogRowsAccumulator {
    private(set) var rows: [[String: Any]] = []
    private var identifiers = Set<String>()

    mutating func append(_ page: [[String: Any]]) {
        for row in page {
            guard V3CatalogRowPolicy.isDisplayable(row),
                  let identifier = V3CatalogRowPolicy.identifier(of: row),
                  identifiers.insert(identifier).inserted else { continue }
            rows.append(row)
        }
    }
}

// V3_RELOAD_GATE_V1
// The reload gate rules, made explicit and executable. The store previously
// inlined this, and callers could not await an authoritative snapshot, so a
// recalculate could read the previous snapshot.
// V3_LOAD_ACTIVITY_OWNERSHIP_V1
// One `loading` flag used to mean two different things: an authoritative status
// snapshot, and a mutation such as refreshSources, signOut, clearCache, syncAppIDs
// or a JIT operation. The reload gate read that flag as "a snapshot is in flight",
// so a caller awaiting an authoritative snapshot could join a mutation instead,
// and the mutation's completion released it with a not-observed outcome before
// any snapshot had been performed. The activity is now named, and the gate can
// tell the two apart.
enum V3LoadActivity: String, Equatable, CaseIterable {
    case idle
    /// An authoritative status snapshot is in flight. This is the only activity
    /// that may resolve a snapshot waiter.
    case snapshot
    /// A mutation is in flight. A snapshot must be requested after it, never
    /// substituted by it.
    case mutation
}

// V3_SNAPSHOT_GATE_V1
// The decision a snapshot request makes. It is a pure function so the ordering
// contract is executable behaviour rather than a comment about a flag.
enum V3SnapshotDecision: String, Equatable, CaseIterable {
    /// The caller owns the snapshot and must perform it now.
    case performSnapshot
    /// A snapshot is genuinely in flight. The caller parks and joins it.
    case joinSnapshot
    /// A mutation is in flight. The caller parks, and a snapshot is owed for
    /// after the mutation. The mutation's completion must not resolve it.
    case awaitMutationThenSnapshot
    /// A presented operation owns the state a snapshot would report. The caller
    /// parks, and a snapshot is owed for when the operation ends.
    case deferForPresentation
    /// A snapshot is owed, but its mutation/presentation blocker is still
    /// active. Keep the owed intent and parked waiters until that blocker ends.
    case stillBlocked
    /// Policy refuses an optional non-manual snapshot, so callers are told
    /// truthfully that nothing was observed. No continuation may remain parked.
    case doNotObserve
}

enum V3SnapshotGate {
    /// A presented operation owns the state, so its snapshot is deferred even
    /// when nothing else is running. This is checked first because a sheet can
    /// be up while a mutation is still settling, and both must be honoured.
    static func decide(activity: V3LoadActivity, presentationActive: Bool,
                       manual: Bool, requiresConnectionRetry: Bool) -> V3SnapshotDecision {
        if presentationActive { return .deferForPresentation }
        switch activity {
        case .snapshot: return .joinSnapshot
        case .mutation: return .awaitMutationThenSnapshot
        case .idle: break
        }
        if !manual && requiresConnectionRetry { return .doNotObserve }
        return .performSnapshot
    }

    /// The result of running an owed snapshot once the blocking activity has
    /// ended. Every case is total: no input leaves a parked continuation
    /// without a resumption, which is what made a non-manual deferred reload a
    /// latent permanent hang.
    static func drain(activity: V3LoadActivity, presentationActive: Bool,
                      owed: Bool, anyWaiterNeedsManual: Bool,
                      explicitManualOwed: Bool = false,
                      requiresConnectionRetry: Bool) -> V3SnapshotDecision {
        guard owed else { return .doNotObserve }
        guard activity == .idle, !presentationActive else { return .stillBlocked }
        return decide(activity: .idle, presentationActive: false,
                      manual: explicitManualOwed || anyWaiterNeedsManual || !requiresConnectionRetry,
                      requiresConnectionRetry: requiresConnectionRetry)
    }
}

// Fire-and-forget reloads have no waiter from which to recover their manual
// intent after a mutation or presentation defers them. Keep that intent with
// the owed snapshot so a manual request still clears a prior connection retry
// latch when the blocker ends.
struct V3SnapshotOwedIntent: Equatable {
    private(set) var isOwed = false
    private(set) var requiresManualSnapshot = false

    mutating func record(manual: Bool) {
        isOwed = true
        requiresManualSnapshot = requiresManualSnapshot || manual
    }

    mutating func clear() {
        isOwed = false
        requiresManualSnapshot = false
    }
}

// V3_SOURCE_EDITING_POLICY_V1
// Issue #40: the Add Source field had no focus state and no explicit dismissal,
// so Return was the only way out of the keyboard and read as a submit action.
// The cancel semantics are stated here so they are executable and testable:
// Cancel restores the URL that was present when editing began, and neither
// Cancel nor Done may preview, request, or persist anything.
enum V3SourceEditingOutcome: Equatable {
    case dismissed
    case restored(String)
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
        default: kindToken = "A00"
        }
        return failureCode + "-" + kindToken
    }
    static func shouldShowTerminalDetails(state: String, hasPrompt: Bool,
                                          hasFailure: Bool) -> Bool {
        hasFailure && !hasPrompt && ["failed", "timedOut", "promptExpired", "resultUnknown"]
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
        let nativeDetails = fields["typed_error"] == "anisetteKitADIError"
            ? " native_code=\(fields["native_code"] ?? "unknown") native_phase=\(fields["native_phase"] ?? "unknown") native_subcode=\(fields["native_subcode"] ?? "unknown")" : ""
        let attemptDetails = fields["anisette_blob_state"].map {
            " anisette_blob_state=\($0) anisette_recovery=\(fields["anisette_recovery"] ?? "notAttempted")"
        } ?? ""
        let probeDetails = fields["probe_native_code"].map {
            " probe_native_code=\($0) probe_native_phase=\(fields["probe_native_phase"] ?? "unknown") probe_native_subcode=\(fields["probe_native_subcode"] ?? "unknown")"
        } ?? ""
        return "diagnostic_code=\(diagnosticCode(for: failure)) builder_commit=\(V3DiagnosticBuild.commit) kind=\(kind) stage=\(stage) code=\(code) correlation=\(correlation) underlying=\(underlyingDomain)/\(codeText) retryable=\(retryableText)" + accountDetails + nativeDetails + attemptDetails + probeDetails +
            (fields[V3TemporaryAnisetteTrace.contextKey].flatMap(V3TemporaryAnisetteTrace.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3TemporaryADIConsumption.contextKey].flatMap(V3TemporaryADIConsumption.init(encoded:))?.technicalDetails ?? "") +
            (fields[V3TemporaryADIExecution.contextKey].flatMap(V3TemporaryADIExecution.init(encoded:))?.technicalDetails ?? "")
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

    var isActive: Bool { runID != nil }

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
            throw failure
        }
        if let code = decoded["error"] as? String {
            throw hostFailure(errorToken: code, operation: operation, id: id)
        }
        guard V3WireContract.strictBool(decoded["ok"]) == true,
              let result = decoded["result"] as? [String: Any] else {
            throw CombinedFailure(operation: operation, stage: hostStage(for: operation),
                                  code: .invalidResponse, id: id)
        }
        return result
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
    public func acknowledgeDirectRecoveryAfterSuccess(_ result: [String: Any],
                                                       operation: String) async -> Bool {
        guard V3DirectRecoveryHostPolicy.mayAcknowledgeSuccessfulResponse(
                operation: operation, result: result),
              let requestID = result["_v3StatusAuthorityRequestID"] as? String,
              UUID(uuidString: requestID)?.uuidString == requestID else { return false }
        // Close host admission while the durable terminal slot is being
        // acknowledged. A current quiescent snapshot reopens it after proof.
        setHostRecoveryHold(true)
        do {
            let ack = try await request(operation: "directRecoveryReconcile", target: requestID,
                payload: ["ackTerminal": true])
            guard ack["requestID"] as? String == requestID,
                  V3WireContract.strictBool(ack["reconciled"]) == true else {
                NotificationCenter.default.post(name: Notification.Name("V3StatusAuthorityChanged"), object: nil)
                return false
            }
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
            try await connect()
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
