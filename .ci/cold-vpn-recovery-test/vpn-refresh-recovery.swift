import Foundation
import CoreFoundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
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
        case directRecoveryRecordMissing, directRecoveryTargetMismatch
        case directRecoveryModeInvalid, directRecoveryPhaseNotEligible

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
        if normalized != "refresh" || stage != .signing || code != .failed || sourceStep != .provisioningProfileFetch {
            context.removeValue(forKey: "local_precondition")
        }
        if normalized != "refresh" || stage != .command || code != .failed || sourceStep != .refreshReadiness {
            context.removeValue(forKey: "refresh_readiness_reason")
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
        if fields["refresh_readiness_reason"] != nil && !(fields["refresh_readiness_reason"] is String) {
            fields.removeValue(forKey: "refresh_readiness_reason")
        }
        if fields["local_precondition"] != nil && !(fields["local_precondition"] is String) {
            fields.removeValue(forKey: "local_precondition")
        }
        guard let strings = V3AuthenticationDiagnostics.sanitizingWireContext(fields) else { return nil }
        return validatedSigningContext(strings)
    }
    public static func validatedSigningContext(_ value: [String: String]) -> [String: String]? {
        var fields = V3AuthenticationDiagnostics.sanitizingContext(V3TemporaryADIConsumption.sanitizingContext(value))
        // This optional observation must never replace or invalidate the primary
        // failure. Admit only the finite local guard vocabulary, with its kind.
        if let local = fields["local_precondition"],
           fields["refresh_failure_kind"] != "invalidParameters" ||
           !["missingTargetAppBundle", "unknownTeamType", "unresolvedAppGroupPlaceholder",
             "missingProgressWeight", "invalidProgressReuse", "missingPipelineStepMapping"].contains(local) || fields.count > 20 {
            fields.removeValue(forKey: "local_precondition")
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
            case "local_precondition":
                guard fields["refresh_failure_kind"] == "invalidParameters",
                    ["missingTargetAppBundle", "unknownTeamType", "unresolvedAppGroupPlaceholder",
                     "missingProgressWeight", "invalidProgressReuse", "missingPipelineStepMapping"].contains(text) else { return nil }
            case "refresh_failure_kind":
                guard ["invalidParameters", "invalidOperationContext", "notAuthenticated", "unknownResult",
                    "missingAppBundle", "missingProvisioningProfile", "certificateExpired", "certificateRevoked",
                    "customCertificateExpired", "customCertificateRevoked", "certificateChanged", "invalidApp",
                    "invalidPairingFile", "pairingNotComplete", "noDevice", "noConnection", "noVPN", "invalidVPN",
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
    private var localRefreshMessage: String? {
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
    public var message: String {
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
        let signingDetails = signingContext.filter { $0.key != V3TemporaryAnisetteTrace.contextKey && $0.key != V3TemporaryADIConsumption.contextKey && $0.key != V3LoginDiagnosticSnapshot.contextKey && $0.key != V3ConstructorFaultDiagnostic.contextKey && $0.key != V3AuthenticationRequestSnapshot.contextKey && $0.key != V3AuthenticationHeaderProvenance.contextKey && $0.key != V3AuthenticationProviderObservation.contextKey && $0.key != V3AuthenticationDiagnostics.stateKey && $0.key != V3ProvisioningCauseDiagnostic.contextKey }.sorted(by: { $0.key < $1.key }).map { " \($0.key)=\($0.value)" }.joined()
        return "schema=1 diagnostic_code=\(diagnosticCode) builder_commit=\(V3DiagnosticBuild.commit) operation=\(operation) stage=\(stage.rawValue) code=\(code.rawValue) correlation=\(correlationID) underlying_domain=\(underlyingDomain) underlying_code=\(displayedUnderlyingCode) retryable=\(retryable.map(String.init) ?? "unknown") source_step=\(sourceStep?.rawValue ?? "unknown") safe_cause=\(safeCause?.rawValue ?? "unknown")" + signingDetails + authenticationState + (signingContext[V3ProvisioningCauseDiagnostic.contextKey].flatMap(V3ProvisioningCauseDiagnostic.init(encoded:))?.technicalDetails ?? "") + (signingContext[V3ConstructorFaultDiagnostic.contextKey].flatMap(V3ConstructorFaultDiagnostic.init(encoded:))?.technicalDetails ?? "") + installVerdict + requestContextSuffix + (launchContext?.technicalDetails ?? "") + (temporaryAnisetteTrace?.technicalDetails ?? "") + (signingContext[V3TemporaryADIConsumption.contextKey].flatMap(V3TemporaryADIConsumption.init(encoded:))?.technicalDetails ?? "") + (signingContext[V3LoginDiagnosticSnapshot.contextKey].flatMap(V3LoginDiagnosticSnapshot.init(encoded:))?.technicalDetails ?? "") + (operation == "signIn" ? V3AuthenticationDiagnostics.technicalDetails(signingContext) : "")
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
        "operation": ["noInstalledApps", "noSources", "notAuthenticated", "timedOut", "unableToConnectSideJIT", "unableToRespondSideJITDevice", "unknownResult", "cacheClearError", "certificateExpired", "certificateRevoked", "customCertificateExpired", "customCertificateRevoked", "forbidden", "invalidApp", "invalidPairingFile", "invalidParameters", "invalidResponse", "invalidVPN", "minimuxerNotStarted", "missingAppBundle", "missingAppGroup", "missingInfoPlist", "missingProvisioningProfile", "missingUpdate", "noConnection", "noDevice", "noVPN", "notReachable", "openAppFailed", "pairingNotComplete", "pledgeInactive", "SideJITIssue", "unknownUDID", "unknown", "appNotFound", "invalidOperationContext", "maximumAppIDLimitReached", "sourceNotAdded", "serverNotFound", "connectionFailed", "provisioningError", "certificateChanged"],
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
            let cpdKeys = ["bootstrap", "icscrec", "pbe", "prkgen", "svct", "loc", "X-Apple-Locale", "X-Apple-I-MD", "X-Apple-I-MD-M", "X-Mme-Device-Id", "X-Apple-I-MD-LU", "X-Apple-I-MD-RINFO", "X-Apple-I-SRL-NO", "X-Apple-I-Client-Time", "X-Apple-I-TimeZone"]
            let meanings = ["a": "absent", "b": "boolean", "s": "stringNonempty", "e": "stringEmpty", "d": "dataNonempty", "z": "dataEmpty", "n": "integer", "r": "real", "c": "container", "o": "other"]
            if r[29].count == 15 {
                text += "\ncpd_fields: " + zip(cpdKeys, r[29].map(String.init)).map { "\($0.0)=\(meanings[$0.1] ?? "unobserved")" }.joined(separator: " ")
            } else { text += "\ncpd_fields=" + (["u": "unobserved", "a": "absent", "w": "wrongType"][r[29]] ?? "unobserved") }
        }
        text += "\nprior_request_summary_columns=invocation,ordinal,phase,state,http_status,ec,consumer,validation prior_request_summaries=" + (p[8].isEmpty ? "notRecorded" : p[8])
        return text
    }
}

// Diagnostic-only independent readers. No request or persistence input.
public struct V3AuthenticationHeaderProvenance {
    public static let contextKey = "auth_header_provenance"
    public static let maximumBytes = 512
    private let tokens: [String]
    public var encoded: String { tokens.joined(separator: ";") }
    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes, encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let p = encoded.split(separator: ";", omittingEmptySubsequences: false).map(String.init)
        let source: Set<String> = ["default", "UserDefaults", "file", "caller", "provider", "unknown"]
        let family: Set<String> = ["Mac-akd", "Android-akd", "Windows", "other", "unknown"]
        guard p.count == 22, p[0] == "hp2",
              ["localAndroidADI", "remote", "unknown"].contains(p[1]),
              source.contains(p[2]), family.contains(p[3]), source.contains(p[4]),
              ["upstreamDefaultAuthKit", "macAuthKit", "windowsAuthKit", "other", "unknown"].contains(p[5]),
              ["knownFamilyAgreement", "mixedKnownFamilies", "unknown"].contains(p[6]),
              ["generated", "cacheHit", "unknown"].contains(p[7]),
              ["under1s", "1to5s", "5to30s", "atLeast30s", "unknown"].contains(p[8]),
              family.contains(p[9]), ["sameFamily", "differentFamily", "unknown"].contains(p[10]),
              ["present", "absent", "unknown"].contains(p[11]),
              ["generated", "notGenerated", "unknown"].contains(p[12]),
              ["unicorn", "native", "remote", "unknown"].contains(p[13]),
              ["appleMusic4961447Arm64", "customOrLocal", "remote", "unknown"].contains(p[14]),
              ["observedVerified", "notObserved", "unknown"].contains(p[15]),
              p[16] == "unobserved", ["matched", "different", "unknown"].contains(p[17]),
              ["notRecorded", "unknown"].contains(p[18]), ["same", "different", "unknown"].contains(p[21]),
              p[7] == "cacheHit" || (p[8] == "unknown" && p[21] == "unknown") else { return nil }
        let known = !["unknown", "other"].contains(p[3]) && !["unknown", "other"].contains(p[5])
        let agreement = (p[3] == "Mac-akd" && ["upstreamDefaultAuthKit", "macAuthKit"].contains(p[5])) || (p[3] == "Windows" && p[5] == "windowsAuthKit")
        let relation = known ? (agreement ? "knownFamilyAgreement" : "mixedKnownFamilies") : "unknown"
        let selectedKnown = !["unknown", "other"].contains(p[9]) && !["unknown", "other"].contains(p[3])
        let selected = selectedKnown ? (p[9] == p[3] ? "sameFamily" : "differentFamily") : "unknown"
        let verified = p[14] == "appleMusic4961447Arm64"
        guard p[6] == relation, p[10] == selected, verified == (p[15] == "observedVerified"),
              p[19] == (verified ? "9d5b557cf3faf88c34c394ab2cd7fc1a3b4acf3aed51f28cd0bc093858107c22" : "unknown"),
              p[20] == (verified ? "bd335e6963ba5ae2f5babca613435ad56d2660a9aee37df35f876c458d105ce4" : "unknown") else { return nil }
        tokens = p
    }
    public var technicalDetails: String {
        let names = ["schema", "provider", "client_info_source", "client_info_family", "user_agent_source",
            "user_agent_family", "profile_relation", "cache", "cache_age", "requested_client_info_family",
            "selected_vs_used_family", "generation_blob_input", "generation_blob_output", "adapter",
            "generation_library_selection", "generation_library_validation", "loaded_mapping", "client_info_preservation",
            "historical_blob_association", "selected_coreADI_sha256", "selected_StoreServices_sha256", "cache_return_input_equality"]
        return "\nactual_request_used: " + zip(names, tokens).map { "\($0.0)=\($0.1)" }.joined(separator: " ")
    }
}
public struct V3AuthenticationProviderObservation {
    public static let contextKey = "auth_provider_observation"
    public static let maximumBytes = 256
    private let tokens: [String]
    public var encoded: String { tokens.joined(separator: ";") }
    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes, encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let p = encoded.split(separator: ";", omittingEmptySubsequences: false).map(String.init)
        guard p.count == 12, p[0] == "ap1",
              ["remote", "onDevice", "verifiedAppleMusic", "localODA", "remoteODA", "unknown"].contains(p[1]),
              ["selected", "clientReady", "dataReady", "cacheHit"].contains(p[2]),
              ["default", "UserDefaults", "file", "caller", "provider", "unknown"].contains(p[3]),
              ["Mac-akd", "Android-akd", "Windows", "other", "unknown"].contains(p[4]),
              ["unicorn", "native", "remote", "unknown"].contains(p[5]),
              ["appleMusic4961447Arm64", "customOrLocal", "remote", "unknown"].contains(p[6]),
              ["observedVerified", "notObserved", "unknown"].contains(p[7]),
              ["present", "absent", "unknown"].contains(p[8]), ["notRecorded", "unknown"].contains(p[9]),
              p[10] == "unobserved", p[11] == "unobserved",
              (p[6] == "appleMusic4961447Arm64") == (p[7] == "observedVerified"),
              p[2] != "selected" || (p[5] == "unknown" && p[6] == "unknown" && p[7] == "unknown") else { return nil }
        tokens = p
    }
    public var technicalDetails: String {
        let names = ["schema", "mode", "stage", "requested_client_info_source", "requested_client_info_family",
            "adapter", "library_selection", "library_validation", "requested_blob_input", "historical_blob_association", "loaded_mapping", "request_association"]
        return "\nlatest_acquisition_observation: " + zip(names, tokens).map { "\($0.0)=\($0.1)" }.joined(separator: " ")
    }
}

public enum V3AuthenticationDiagnostics {
    public static let stateKey = "auth_diagnostic_state"
    public static let maximumWireBytes = 4096
    private static let keys: Set<String> = [V3AuthenticationRequestSnapshot.contextKey,
        V3AuthenticationHeaderProvenance.contextKey, V3AuthenticationProviderObservation.contextKey, stateKey]
    private static let observationKeys = keys.union([V3ProvisioningCauseDiagnostic.contextKey])
    private static let ancillary = [V3LoginDiagnosticSnapshot.contextKey, V3TemporaryAnisetteTrace.contextKey,
        V3TemporaryADIConsumption.contextKey, "capability_names", "enabled_capability_names",
        "team_sha256", "requested_bundle_sha256", "requested_app_group_sha256", "capabilities_sha256",
        "signing_certificate_serial_sha256", "provisioning_bundle_sha256", "session_generation",
        "capability_count", "app_group_count", "extension_count", "account_binding", "team_binding",
        "signing_certificate_present", "preferred_parent_id_match", "profile_mode", "device_registration",
        "probe_native_code", "anisette_blob_state", "provisioning_bundle_role"]
    private static func removeAncillary(_ key: String, from fields: inout [String: String]) -> Bool {
        let group: [String]
        switch key {
        case "probe_native_code": group = ["probe_native_code", "probe_native_phase", "probe_native_subcode"]
        case "anisette_blob_state": group = ["anisette_blob_state", "anisette_recovery"]
        default: group = [key]
        }
        var removed = false
        for member in group { if fields.removeValue(forKey: member) != nil { removed = true } }
        return removed
    }
    public static func sanitizingContext(_ supplied: [String: String]) -> [String: String] {
        var result = supplied
        var rejected = false
        if let raw = result[V3ProvisioningCauseDiagnostic.contextKey], V3ProvisioningCauseDiagnostic.validated(raw) == nil {
            result[V3ProvisioningCauseDiagnostic.contextKey] = V3ProvisioningCauseDiagnostic.rejected; rejected = true
        }
        if let raw = result[V3AuthenticationRequestSnapshot.contextKey], V3AuthenticationRequestSnapshot(encoded: raw) == nil {
            result.removeValue(forKey: V3AuthenticationRequestSnapshot.contextKey); rejected = true
        }
        if let raw = result[V3AuthenticationHeaderProvenance.contextKey], V3AuthenticationHeaderProvenance(encoded: raw) == nil {
            result.removeValue(forKey: V3AuthenticationHeaderProvenance.contextKey); rejected = true
        }
        if let raw = result[V3AuthenticationProviderObservation.contextKey], V3AuthenticationProviderObservation(encoded: raw) == nil {
            result.removeValue(forKey: V3AuthenticationProviderObservation.contextKey); rejected = true
        }
        if let state = result[stateKey], !["recorded", "trimmed", "rejected", "notRecorded"].contains(state) {
            result.removeValue(forKey: stateKey); rejected = true
        }
        if rejected || result[stateKey] == "rejected" {
            result.removeValue(forKey: stateKey)
            for key in ancillary where result.count >= 20 { _ = removeAncillary(key, from: &result) }
            if result.count < 20 { result[stateKey] = "rejected" }
        }
        if result.count > 20 && !observationKeys.isDisjoint(with: result.keys) {
            // Optional extensions cannot erase a primary failure at capacity.
            // Unknown keys and the primary native tuple are never evicted.
            // Earlier probe/recovery annotations are evicted atomically, after chronology.
            if result[stateKey] != "rejected" { result[stateKey] = "trimmed" }
            for key in ancillary where result.count > 20 { _ = removeAncillary(key, from: &result) }
        }
        return result
    }
    public static func sanitizingWireContext(_ supplied: Any) -> [String: String]? {
        guard var fields = supplied as? [String: Any] else { return nil }
        var rejected = false
        for key in observationKeys where fields[key] != nil && !(fields[key] is String) {
            if key == V3ProvisioningCauseDiagnostic.contextKey { fields[key] = V3ProvisioningCauseDiagnostic.rejected }
            else { fields.removeValue(forKey: key) }
            rejected = true
        }
        guard var strings = fields as? [String: String] else { return nil }
        if rejected { strings[stateKey] = "rejected" }
        return sanitizingContext(strings)
    }
    public static func fits(_ value: [String: Any]) -> Bool {
        guard let binary = try? PropertyListSerialization.data(fromPropertyList: value, format: .binary, options: 0),
              binary.count <= maximumWireBytes, JSONSerialization.isValidJSONObject(value),
              let json = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              json.count <= maximumWireBytes else { return false }
        return true
    }
    public static func attaching(requestTrace: String?, headerProvenance: String?, providerObservation: String? = nil,
                                 loginTrace: String?, to supplied: [String: Any]) -> [String: Any] {
        var result = supplied
        var fields = (result["signingContext"] as? [String: String]) ?? [:]
        for key in keys { fields.removeValue(forKey: key) }
        if let requestTrace { fields[V3AuthenticationRequestSnapshot.contextKey] = requestTrace }
        if let headerProvenance { fields[V3AuthenticationHeaderProvenance.contextKey] = headerProvenance }
        if let providerObservation { fields[V3AuthenticationProviderObservation.contextKey] = providerObservation }
        fields[stateKey] = requestTrace == nil && headerProvenance == nil && providerObservation == nil ? "notRecorded" : "recorded"
        fields = sanitizingContext(fields)
        if let loginTrace, let trace = V3LoginDiagnosticSnapshot(encoded: loginTrace) { fields[V3LoginDiagnosticSnapshot.contextKey] = trace.encoded }
        result["signingContext"] = fields
        return boundingWire(result)
    }
    public static func boundingWire(_ supplied: [String: Any]) -> [String: Any] {
        guard let raw = supplied["signingContext"] as? [String: String], !observationKeys.isDisjoint(with: raw.keys) else { return supplied }
        var fields = sanitizingContext(raw)
        if fields[stateKey] == nil { fields[stateKey] = "recorded" }
        var trimmed = fields != raw
        for key in ancillary where fields.count > 20 { if removeAncillary(key, from: &fields) { trimmed = true } }
        var result = supplied; result["signingContext"] = fields
        let beforeTrace = fields[V3LoginDiagnosticSnapshot.contextKey]
        result = V3LoginDiagnosticSnapshot.boundingWire(result)
        fields = (result["signingContext"] as? [String: String]) ?? fields
        if fields[V3LoginDiagnosticSnapshot.contextKey] != beforeTrace { trimmed = true }
        for key in ancillary where !fits(result) {
            if removeAncillary(key, from: &fields) { trimmed = true }
            result["signingContext"] = fields
        }
        if trimmed && fields[stateKey] != "rejected" { fields[stateKey] = "trimmed" }
        result["signingContext"] = fields
        // Reserved finite observations and primary evidence are never displaced
        // by chronology or ancillary fingerprints. Needs proper testing in CI.
        return result
    }
    public static func technicalDetails(_ supplied: [String: String]) -> String {
        let fields = sanitizingContext(supplied)
        return "\nauth_diagnostic_state=\(fields[stateKey] ?? "notRecorded")" +
            (fields[V3AuthenticationRequestSnapshot.contextKey].flatMap(V3AuthenticationRequestSnapshot.init(encoded:))?.technicalDetails ?? "\nauth_request_trace=notRecorded") +
            (fields[V3AuthenticationHeaderProvenance.contextKey].flatMap(V3AuthenticationHeaderProvenance.init(encoded:))?.technicalDetails ?? "\nactual_request_used=notRecorded") +
            (fields[V3AuthenticationProviderObservation.contextKey].flatMap(V3AuthenticationProviderObservation.init(encoded:))?.technicalDetails ?? "\nlatest_acquisition_observation=notRecorded")
    }
}

public struct V3LoginDiagnosticSnapshot {
    public static let contextKey = "debug_login_trace"
    public static let maximumBytes = 2048
    public static let maximumEvents = 128
    public static let maximumWireBytes = 4096
    private let correlation: String
    private let truncated: Bool
    private let rows: [[Int]]

    public init?(encoded: String) {
        guard encoded.utf8.count <= Self.maximumBytes,
              encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let parts = encoded.split(separator: ";", omittingEmptySubsequences: false)
        guard parts.count >= 5, parts.count <= Self.maximumEvents + 4,
              parts[0] == "v1", parts[1] == "login_trace_v1",
              parts[2].utf8.count == 12,
              parts[2].utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              parts[3] == "0" || parts[3] == "1" else { return nil }
        var decoded: [[Int]] = []
        for row in parts.dropFirst(4) {
            // The producer permits a trace created before any observed stage.
            if parts.count == 5 && row.isEmpty { break }
            let columns = row.split(separator: ",", omittingEmptySubsequences: false)
            let values = columns.compactMap { Int($0) }
            guard columns.count == 7, values.count == 7,
                  zip(columns, values).allSatisfy({ String($0.1) == String($0.0) }),
                  (0...56).contains(values[0]), (0...3).contains(values[1]),
                  (0...11).contains(values[2]), (0...86_400_000).contains(values[3]),
                  (0...86_400_000).contains(values[4]), (0...8).contains(values[5]),
                  (-2_147_483_648...2_147_483_647).contains(values[6]) else { return nil }
            switch values[5] {
            case 0, 1, 8: guard values[6] == 0 else { return nil }
            case 4: guard (1...6).contains(values[6]) else { return nil }
            case 3, 5, 6, 7: guard (-999_999...999_999).contains(values[6]) else { return nil }
            default: break
            }
            decoded.append(values)
        }
        correlation = String(parts[2]); truncated = parts[3] == "1"; rows = decoded
    }
    private init(correlation: String, truncated: Bool, rows: [[Int]]) {
        self.correlation = correlation; self.truncated = truncated; self.rows = rows
    }
    public var encoded: String {
        "v1;login_trace_v1;\(correlation);\(truncated ? 1 : 0);" +
            rows.map { $0.map(String.init).joined(separator: ",") }.joined(separator: ";")
    }
    public var technicalDetails: String { "\nDEBUG TEMPORARY login_trace=\(encoded)" }

    public static func attaching(_ encoded: String?, to supplied: [String: Any]) -> [String: Any] {
        guard let encoded, let snapshot = Self(encoded: encoded) else { return supplied }
        var result = supplied
        var context = supplied["signingContext"] as? [String: String] ?? [:]
        guard context[contextKey] != nil || context.count < 20 else { return supplied }
        context[contextKey] = snapshot.encoded
        result["signingContext"] = context
        return boundingWire(result)
    }
    public static func boundingWire(_ supplied: [String: Any]) -> [String: Any] {
        guard var context = supplied["signingContext"] as? [String: String],
              let raw = context.removeValue(forKey: contextKey) else { return supplied }
        var result = supplied
        result["signingContext"] = context
        guard var snapshot = Self(encoded: raw), context.count < 20 else { return result }
        while true {
            context[contextKey] = snapshot.encoded
            result["signingContext"] = context
            if V3AuthenticationDiagnostics.fits(result) { return result }
            if snapshot.rows.isEmpty {
                context.removeValue(forKey: contextKey)
                result["signingContext"] = context
                return result
            }
            // Only trim this optional trace. Preserve the original failure and native evidence.
            snapshot = Self(correlation: snapshot.correlation, truncated: true,
                            rows: Array(snapshot.rows.dropFirst()))
        }
    }
}

// V3_CONSTRUCTOR_FAULT_DIAGNOSTIC_V1: one finite optional tuple, independent
// of temporary traces. No raw addresses, registers, filenames or free-form text.
public struct V3ConstructorFaultDiagnostic: Equatable, Sendable {
    public static let contextKey = "native_constructor_fault"
    private static let marker = " [DEBUG_TEMPORARY_CONSTRUCTOR_FAULT:"
    public let encoded: String

    public init?(encoded: String) {
        guard encoded.utf8.count < 256,
              encoded.utf8.allSatisfy({ $0 < 128 }) else { return nil }
        let parts = encoded.split(separator: ";", omittingEmptySubsequences: false)
        guard parts.count == 10, parts[0] == "v1", parts[1] == "p0_fault_diag1" else { return nil }
        let fields = Array(parts[2...7])
        let numbers = fields.compactMap { Int64($0) }
        guard numbers.count == 6,
              zip(fields, numbers).allSatisfy({ String($0.1) == String($0.0) }),
              (0...3).contains(numbers[0]),
              numbers[1] == -1 || (1...256).contains(numbers[1]),
              (0...7).contains(numbers[2]),
              numbers[3] == -1 || (0...65535).contains(numbers[3]),
              numbers[4] == -1 || (0...805306367).contains(numbers[4]),
              (0...2).contains(numbers[5]),
              (numbers[3] == -1) == (numbers[4] == -1),
              numbers[0] != 0 || (numbers[1] == -1 && numbers[2] == 0),
              numbers[1] != -1 || numbers[2] == 0 else { return nil }
        for digest in parts[8...9] {
            guard digest == "-" || (digest.utf8.count == 64 && digest.utf8.allSatisfy({
                (48...57).contains($0) || (97...102).contains($0)
            })) else { return nil }
        }
        self.encoded = encoded
    }
    static func acceptsEnvelope(_ description: String) -> Bool {
        guard description.utf8.count <= 8192 else { return false }
        guard let range = description.range(of: marker) else { return true }
        guard description[range.upperBound...].range(of: marker) == nil else { return false }
        // An older optional suffix must not swallow a malformed, duplicated or
        // misordered fault suffix and accidentally recover a classification.
        let base = V3TemporaryAnisetteTrace.nativeDescriptionWithoutTrace(description)
        return splitDescription(base).diagnostic != nil
    }
    static func splitDescription(_ description: String) -> (base: String, diagnostic: Self?) {
        // Remove only one fully valid terminal suffix after older suffixes have
        // been checked. Malformed, duplicate and misordered suffixes fail closed.
        guard description.utf8.count <= 768, description.hasSuffix("]"),
              let range = description.range(of: marker),
              description[range.upperBound...].range(of: marker) == nil,
              let diagnostic = Self(encoded: String(description[range.upperBound...].dropLast())) else {
            return (description, nil)
        }
        return (String(description[..<range.lowerBound]), diagnostic)
    }
    public var technicalDetails: String {
        let values = encoded.split(separator: ";", omittingEmptySubsequences: false).dropFirst(2)
        let keys = ["native_fault_access", "native_fault_width", "native_fault_region",
            "native_fault_pc_library", "native_fault_pc_offset", "native_fault_guard",
            "native_fault_sha0", "native_fault_sha1"]
        return zip(keys, values).map { " \($0.0)=\($0.1)" }.joined()
    }
    public static func boundingWire(_ supplied: [String: Any]) -> [String: Any] {
        guard var context = supplied["signingContext"] as? [String: String],
              context[contextKey] != nil else { return supplied }
        if let data = try? PropertyListSerialization.data(fromPropertyList: supplied, format: .binary, options: 0),
           data.count <= 4096 { return supplied }
        // Existing optional traces yield first; this tuple yields next. Never
        // drop the primary constructor classification to fit optional metadata.
        context.removeValue(forKey: contextKey)
        var result = supplied
        result["signingContext"] = context
        return result
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
        case nativeStartOk = "native.start.ok"
        case nativeStartFailed = "native.start.failed"
        case nativeEndOk = "native.end.ok"
        case nativeEndFailed = "native.end.failed"
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
        case setupConstructors, setupVM, setupVMPreviouslyFailed
    }
    let code: Int32
    let phase: Phase
    let subcode: Int32?
    var consumption: V3TemporaryADIConsumption? = nil
    var constructorFailure: ConstructorFailure? = nil
    var constructorFault: V3ConstructorFaultDiagnostic? = nil

    // V3_NATIVE_INITIALIZER_FAILURE_V1: finite native observations only. The
    // engine is a Unicorn uc_err, never an ADI subcode, PC, register or address.
    struct ConstructorFailure {
        enum Kind: String { case unknown, dt_init, dt_init_array, array_entry_read }
        enum Reason: String {
            case unknown, engine_error, unsupported_interrupt, unexpected_return
            case entry_read, invalid_vm, previously_failed
        }
        static let contextKeys: Set<String> = ["native_init_kind", "native_init_reason",
            "native_init_engine", "native_init_library", "native_init_initializer"]
        let kind: Kind
        let reason: Reason
        let engine: Int
        let library: Int
        let initializer: Int

        private init?(kind: String, reason: String, engine: String, library: String, initializer: String) {
            guard let kind = Kind(rawValue: kind), let reason = Reason(rawValue: reason),
                  let engine = Self.number(engine, maximum: 255),
                  let library = Self.number(library, maximum: 65535),
                  let initializer = Self.number(initializer, maximum: 65535) else { return nil }
            switch kind {
            case .unknown:
                guard [.unknown, .invalid_vm, .previously_failed].contains(reason),
                      engine == -1, library == -1, initializer == -1 else { return nil }
            case .dt_init, .dt_init_array:
                guard kind != .dt_init || initializer == 0 else { return nil }
                switch reason {
                case .engine_error: guard engine != 0 else { return nil }
                case .unsupported_interrupt: break
                case .unexpected_return: guard engine == 0 else { return nil }
                default: return nil
                }
            case .array_entry_read:
                guard reason == .entry_read, engine != 0 else { return nil }
            }
            self.kind = kind; self.reason = reason; self.engine = engine
            self.library = library; self.initializer = initializer
        }
        private static func number(_ text: String, maximum: Int) -> Int? {
            guard text.utf8.count <= 5, let value = Int(text),
                  String(value) == text, (-1...maximum).contains(value) else { return nil }
            return value
        }
        init?(description: String) {
            let prefix = "Library constructor execution failed ["
            guard description.utf8.count <= 256, description.hasPrefix(prefix),
                  description.hasSuffix("]") else { return nil }
            let tokens = description.dropFirst(prefix.count).dropLast().components(separatedBy: ";")
            let labels = ["kind=", "reason=", "engine=", "library=", "initializer="]
            guard tokens.count == 6, tokens[0] == "v1" else { return nil }
            var values: [String] = []
            for (token, label) in zip(tokens.dropFirst(), labels) {
                guard token.hasPrefix(label) else { return nil }
                values.append(String(token.dropFirst(label.count)))
            }
            self.init(kind: values[0], reason: values[1], engine: values[2],
                      library: values[3], initializer: values[4])
        }
        private init?(context: [String: String]) {
            guard let kind = context["native_init_kind"], let reason = context["native_init_reason"],
                  let engine = context["native_init_engine"], let library = context["native_init_library"],
                  let initializer = context["native_init_initializer"] else { return nil }
            self.init(kind: kind, reason: reason, engine: engine, library: library, initializer: initializer)
        }
        static func validatesContext(_ fields: [String: String]) -> Bool {
            let present = contextKeys.intersection(fields.keys)
            guard !present.isEmpty else { return fields[V3ConstructorFaultDiagnostic.contextKey] == nil } // Legacy phase-only evidence.
            return present == contextKeys && fields["typed_error"] == "anisetteKitADIError" &&
                fields["native_code"] == "-2" && fields["native_phase"] == Phase.setupConstructors.rawValue &&
                fields["native_subcode"] == "unknown" && Self(context: fields) != nil
        }
        var diagnosticFields: [String: String] {
            ["native_init_kind": kind.rawValue, "native_init_reason": reason.rawValue,
             "native_init_engine": String(engine), "native_init_library": String(library),
             "native_init_initializer": String(initializer)]
        }
    }

    static func capture(code: Int32, description: String) -> Self {
        guard V3ConstructorFaultDiagnostic.acceptsEnvelope(description) else {
            return Self(code: code, phase: .unknown, subcode: nil)
        }
        let observed = V3TemporaryADIConsumption.splitDescription(description)
        var evidence = captureBase(code: code, description: observed.base)
        if V3TemporaryAnisetteTrace.temporaryAnisetteTraceEnabled { evidence.consumption = observed.trace }
        return evidence
    }
    private static func captureBase(code: Int32, description: String) -> Self {
        let unknown = Self(code: code, phase: .unknown, subcode: nil)
        // Bound inspection before matching. Never scan arbitrary messages for
        // keywords, URLs, digits or error-like substrings.
        let withoutTrace = V3TemporaryAnisetteTrace.nativeDescriptionWithoutTrace(description)
        let fault = V3ConstructorFaultDiagnostic.splitDescription(withoutTrace)
        let description = fault.base
        guard description.utf8.count <= 256 else { return unknown }
        if let diagnostic = fault.diagnostic {
            guard code == -2, let constructor = ConstructorFailure(description: description) else { return unknown }
            return Self(code: code, phase: .setupConstructors, subcode: nil,
                constructorFailure: constructor, constructorFault: diagnostic)
        }
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
        if let constructor = ConstructorFailure(description: description) {
            return Self(code: code, phase: .setupConstructors, subcode: nil, constructorFailure: constructor)
        }
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
            "Library constructor execution failed": .setupConstructors,
            "VM initialization failed": .setupVM,
            "VM initialization previously failed; restart required": .setupVMPreviouslyFailed,
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
    // Finite pre-native acquisition diagnostics. No provider strings or hashes cross IPC.
    enum AcquisitionFailure: String {
        case serverListHTTP = "anisetteAcquisitionServerListHTTP"
        case metadataHTTP = "anisetteAcquisitionMetadataHTTP"
        case archiveHTTP = "anisetteAcquisitionArchiveHTTP"
        case checksumMismatch = "anisetteAcquisitionChecksumMismatch"
        case missingMetadata = "anisetteAcquisitionMissingMetadata"
        case invalidPayload = "anisetteAcquisitionInvalidPayload"
        case extractionFailed = "anisetteAcquisitionExtractionFailed"
        case missingLibraries = "anisetteAcquisitionMissingLibraries"
        case providerNotReady = "anisetteAcquisitionProviderNotReady"
        case downloadFailed = "anisetteAcquisitionDownloadFailed"
    }
    enum AuthResponseMIME: String { case html, xmlOrPlist, json, other, unavailable }
    enum AuthResponseShape: String {
        case plistDictionary, plistArray, plistScalar
        case jsonDictionary, jsonArray, jsonScalar
        case unrecognized
    }
    enum Kind: String {
        case keychainWrite, keychainValidationFailed, keychainOutcomeUnknown
        case legacyMigrationConflict, persistenceFailure, persistenceOutcomeUnknown, transportFailure
        case sideSignServerReportedError, sideSignBadResponse, sideSignInvalidResponse
        case sideSignMissingKey, sideSignDeveloperPortalError, anisetteFailure
        case anisetteKitInvalidArgument, anisetteKitLoaderFailed, anisetteKitSymbolMissing, anisetteKitReadFailure, anisetteKitInvalidResponse, anisetteKitADIError, anisetteKitLibrariesNotFound, anisetteKitHTTPError, decodingTypeMismatch, decodingValueNotFound, decodingKeyNotFound, decodingDataCorrupted
        case archiveFileNotFound, archiveCorrupt, archiveReadFailed, archiveWriteFailed, archiveMissingApp
        case unknownAccountFailure
        case anisetteIdentityStateInvalid
        case remoteIdentityInvalidRecord, remoteIdentityStorageUnverified, remoteIdentityStateChanged, remoteIdentityManualSignInRequired
        var isRemoteIdentity: Bool {
            switch self {
            case .remoteIdentityInvalidRecord, .remoteIdentityStorageUnverified, .remoteIdentityStateChanged, .remoteIdentityManualSignInRequired: return true
            default: return false
            }
        }
    }
    let step: CombinedFailure.SourceStep
    let kind: Kind
    let underlying: Error
    let serverCode: Int?
    var httpStatus: Int? = nil
    var nativeEvidence: V3AnisetteNativeEvidence? = nil
    var anisetteAttempt: V3AnisetteAttemptContext? = nil
    var acquisitionFailure: AcquisitionFailure? = nil
    var authResponseShape: AuthResponseShape? = nil
    var authResponseMIME: AuthResponseMIME? = nil
    let provisioningCause: String?

    init(step: CombinedFailure.SourceStep, kind: Kind, underlying: Error, serverCode: Int?,
         httpStatus: Int? = nil, nativeEvidence: V3AnisetteNativeEvidence? = nil,
         anisetteAttempt: V3AnisetteAttemptContext? = nil, acquisitionFailure: AcquisitionFailure? = nil,
         authResponseShape: AuthResponseShape? = nil, authResponseMIME: AuthResponseMIME? = nil,
         provisioningCause: String? = nil) {
        self.step = step; self.kind = kind; self.underlying = underlying; self.serverCode = serverCode
        self.httpStatus = httpStatus; self.nativeEvidence = nativeEvidence; self.anisetteAttempt = anisetteAttempt
        self.acquisitionFailure = acquisitionFailure; self.authResponseShape = authResponseShape
        self.authResponseMIME = authResponseMIME; self.provisioningCause = provisioningCause
    }

    // V3_REMOTE_IDENTITY_DIAGNOSTICS_V1: fixed local domain/code only; no userInfo or private values.
    static func remoteIdentityKind(domain: String, code: Int) -> Kind? {
        guard domain == "SideStore.RemoteIdentity" else { return nil }
        switch code {
        case 1: return .remoteIdentityInvalidRecord
        case 2: return .remoteIdentityStorageUnverified
        case 3: return .remoteIdentityStateChanged
        case 4: return .remoteIdentityManualSignInRequired
        default: return nil
        }
    }
    static func remoteIdentityMessage(_ typed: String?) -> String? {
        guard let typed, let kind = Kind(rawValue: typed) else { return nil }
        switch kind {
        case .remoteIdentityInvalidRecord: return "The saved remote provider identity is invalid. It was not replaced."
        case .remoteIdentityStorageUnverified: return "The saved remote provider identity could not be verified in protected storage."
        case .remoteIdentityStateChanged: return "The active account or remote provider identity changed during this request."
        case .remoteIdentityManualSignInRequired: return "This saved session needs one manual sign-in to confirm its provider identity."
        default: return nil
        }
    }
    static func remoteIdentityRecovery(_ typed: String?) -> String? {
        guard let typed, let kind = Kind(rawValue: typed), kind.isRemoteIdentity else { return nil }
        switch kind {
        case .remoteIdentityStateChanged, .remoteIdentityManualSignInRequired:
            return "Open Account & Signing and sign in again. The local pairing file and certificates are kept."
        default: return "Keep the saved identity unchanged and copy Diagnostics before retrying."
        }
    }
    var errorDescription: String? { "An account operation failed; review the safe diagnostics." }
    var credentialCommit: Bool { step == .credentialCommit && kind != .anisetteIdentityStateInvalid && !kind.isRemoteIdentity }
    // Apple Developer Portal result 1100 rejects the portal session. Scope this
    // to the observed team-list boundary; an NSError bridge code is not proof.
    var portalSessionRejected: Bool {
        step == .fetchTeams && kind == .sideSignServerReportedError && serverCode == 1100
    }
    var requiresReconciliation: Bool {
        kind == .keychainOutcomeUnknown || kind == .persistenceOutcomeUnknown
    }
    var failureStage: CombinedFailure.Stage {
        if kind == .anisetteIdentityStateInvalid || kind.isRemoteIdentity { return .authentication }
        switch step {
        case .credentialCommit, .saveAccount, .activateAccount, .activateCertificate: return .persistence
        case .authenticate, .anisetteFetch, .appleAuthentication, .accountLookup: return .authentication
        default: return .provisioning
        }
    }
    func failure(operation: String, id: String) -> CombinedFailure {
        let native = underlying as NSError
        let safeCause: CombinedFailure.SafeCause?
        if kind == .anisetteIdentityStateInvalid || kind.isRemoteIdentity { safeCause = nil }
        else if credentialCommit {
            safeCause = kind == .keychainOutcomeUnknown ? .credentialCommitOutcomeUnknown : .credentialCommitFailed
        } else if step == .activateAccount { safeCause = .accountActivationFailed }
        else if step == .activateCertificate || step == .saveAccount { safeCause = .provisioningStorageFailed }
        else { safeCause = nil }
        // An associated Apple result is separate from Swift's enum bridge code.
        // HTTP status remains unavailable unless a typed producer observes it.
        var signingContext = ["typed_error": acquisitionFailure?.rawValue ?? kind.rawValue,
            "server_code": serverCode.map(String.init) ?? "unknown", "http_status": httpStatus.map(String.init) ?? "unavailable"]
        if let provisioningCause {
            signingContext[V3ProvisioningCauseDiagnostic.contextKey] = provisioningCause
        }
        if kind == .sideSignInvalidResponse, let authResponseMIME {
            signingContext["auth_response_mime"] = authResponseMIME.rawValue
        }
        if kind == .sideSignInvalidResponse, let authResponseShape {
            signingContext["auth_response_shape"] = authResponseShape.rawValue
        }
        if kind == .anisetteKitADIError, let nativeEvidence {
            signingContext["native_code"] = String(nativeEvidence.code)
            signingContext["native_phase"] = nativeEvidence.phase.rawValue
            signingContext["native_subcode"] = nativeEvidence.subcode.map(String.init) ?? "unknown"
            if let constructor = nativeEvidence.constructorFailure {
                signingContext.merge(constructor.diagnosticFields) { _, observed in observed }
                if let fault = nativeEvidence.constructorFault {
                    signingContext[V3ConstructorFaultDiagnostic.contextKey] = fault.encoded
                }
            }
        }
        if let anisetteAttempt {
            signingContext.merge(anisetteAttempt.diagnosticFields) { _, observed in observed }
        }
        if kind == .anisetteKitADIError, let consumption = nativeEvidence?.consumption,
           signingContext.count < 20 {
            signingContext[V3TemporaryADIConsumption.contextKey] = consumption.encoded
        }
        return CombinedFailure(operation: operation, stage: failureStage, id: id,
            underlying: NSError(domain: native.domain, code: native.code),
            retryable: safeCause != nil || portalSessionRejected || kind == .anisetteIdentityStateInvalid || kind.isRemoteIdentity ? false : nil, safeCause: safeCause,
            sourceStep: kind == .anisetteIdentityStateInvalid || kind.isRemoteIdentity ? .anisetteFetch : step,
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
        case "anisetteAcquisitionServerListHTTP": return "T33"
        case "anisetteAcquisitionMetadataHTTP": return "T34"
        case "anisetteAcquisitionArchiveHTTP": return "T35"
        case "anisetteAcquisitionChecksumMismatch": return "T36"
        case "anisetteAcquisitionMissingMetadata": return "T37"
        case "anisetteAcquisitionInvalidPayload": return "T38"
        case "anisetteAcquisitionExtractionFailed": return "T39"
        case "anisetteAcquisitionMissingLibraries": return "T40"
        case "anisetteAcquisitionProviderNotReady": return "T41"
        case "anisetteAcquisitionDownloadFailed": return "T42"
        case "remoteIdentityInvalidRecord": return "T43"
        case "remoteIdentityStorageUnverified": return "T44"
        case "remoteIdentityStateChanged": return "T45"
        case "remoteIdentityManualSignInRequired": return "T46"
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
        case .directRecoveryRecordMissing: return "F65"
        case .directRecoveryTargetMismatch: return "F66"
        case .directRecoveryModeInvalid: return "F67"
        case .directRecoveryPhaseNotEligible: return "F68"
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
        case .certificateSelection: return "S31"
        case .refreshMetadataCache: return "S32"
        case .provisioningProfileInstallation: return "S33"
        case .refreshRecordUpdate: return "S34"
        case .refreshApplication: return "S35"
        case .refreshReadiness: return "S36"
        case .refreshPreflight: return "S37"
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
public enum OperationError: LocalizedError, CustomNSError, Sendable, Equatable {
    case noInstalledApps
    case noSources
    case notAuthenticated
    case timedOut
    case unableToConnectSideJIT
    case unableToRespondSideJITDevice
    case unknownResult

    case cacheClearError(errors: [String])
    case certificateExpired(appName: String)
    case certificateRevoked(appName: String)
    case customCertificateExpired(appName: String, activeTeam: String)
    case customCertificateRevoked(appName: String, activeTeam: String)
    case forbidden(failureReason: String, file: String = #fileID, line: UInt = #line)
    case invalidApp(reason: String)
    case invalidPairingFile(reason: String)
    case invalidParameters(String)
    case invalidResponse(reason: String)
    case invalidVPN(reason: String)
    case minimuxerNotStarted(reason: String)
    case missingAppBundle(reason: String)
    case missingAppGroup(name: String)
    case missingInfoPlist(reason: String)
    case missingProvisioningProfile(reason: String)
    case missingUpdate(appName: String)
    case noConnection(reason: String)
    case noDevice(reason: String)
    case noVPN(reason: String)
    case notReachable(reason: String)
    case openAppFailed(name: String)
    case pairingNotComplete(reason: String)
    case pledgeInactive(appName: String)
    case SideJITIssue(error: String)
    case unknownUDID(reason: String)

    // Legacy typed cases remain part of the embedded host's privacy-safe mapping.
    case unknown(failureReason: String? = nil, file: String = #fileID, line: UInt = #line)
    case appNotFound(name: String? = nil)
    case invalidOperationContext(String? = nil)
    case maximumAppIDLimitReached(appName: String, requiredAppIDs: Int, availableAppIDs: Int, expirationDate: Date)
    case sourceNotAdded(name: String)
    case serverNotFound
    case connectionFailed
    case provisioningError(result: String, message: String? = nil)
    case certificateChanged(appName: String)

    public static var cancelled: CancellationError { CancellationError() }

    public var rawDescription: String {
        switch self {
        case .unknown(let failureReason, let file, let line):
            let base = failureReason ?? "An unknown error occurred."
            return "\(base) (\(file) line \(line))"
        case .appNotFound(let name):
            let app = name ?? "The app"
            return "\(app) could not be found."
        case .invalidOperationContext(let msg):
            let suffix = msg.map { ": \n\($0)" } ?? "."
            return "Invalid Operation Context\(suffix)"
        case .maximumAppIDLimitReached:
            return "Cannot register more than 10 App IDs within a 7 day period."
        case .sourceNotAdded(let name):
            return "The source “\(name)” is not added to SideStore."
        case .serverNotFound:
            return "AltServer could not be found."
        case .connectionFailed:
            return "A connection to AltServer could not be established."
        case .provisioningError(let result, let message):
            let combined = (message?.isEmpty ?? true) ? result : "\(result) \(message!)"
            let trimmed = combined.trimmingCharacters(in: CharacterSet(charactersIn: " ."))
            return "An error occurred while provisioning: \(trimmed). Please try again. If the issue persists, report it on GitHub Issues!"
        case .certificateChanged(let appName):
            return "The signing certificate used to install “\(appName)” differs from your active signing certificate. Please re-sign or reinstall the app."
        case .noInstalledApps:
            return "There are no active sideloaded apps to refresh."
        case .noSources:
            return "There are no SideStore sources."
        case .notAuthenticated:
            return "You are not signed in."
        case .timedOut:
            return "The operation timed out."
        case .unableToConnectSideJIT:
            return "Unable to connect to SideJITServer. Please check that you are on the same Wi-Fi of and your Firewall has been set correctly on your server."
        case .unableToRespondSideJITDevice:
            return "SideJITServer is unable to connect to your iDevice. Please make sure you have paired your iDevice by running 'SideJITServer -y', or try refreshing SideJITServer from Settings."
        case .unknownResult:
            return "The operation returned an unknown result."

        case .cacheClearError(let errors):
            return "An error occurred while clearing the cache: \(errors.joined(separator: "\n"))"
        case .certificateExpired(let appName):
            return "The signing certificate used to install “\(appName)” has expired. Please re-sign or reinstall the app."
        case .certificateRevoked(let appName):
            return "The signing certificate used to install “\(appName)” was revoked on the Apple Developer portal. Please re-sign or reinstall the app."
        case .customCertificateExpired(_, let activeTeam):
            return "Your active custom/third-party signing certificate (Team: \(activeTeam)) has expired.\n\nIf you did not intend to use a custom certificate, please reset it in Settings -> Advanced -> Certificates."
        case .customCertificateRevoked(_, let activeTeam):
            return "Your active custom/third-party signing certificate (Team: \(activeTeam)) was revoked on the Developer Portal.\n\nIf you did not intend to use a custom certificate, please reset it in Settings -> Advanced -> Certificates."
        case .forbidden(let reason, _, _):
            return reason
        case .invalidApp(let reason):
            return "The app is in an invalid format: \(reason)"
        case .invalidPairingFile(let reason):
            return "The current pairing file is invalid. Reason: \(reason)\n\nPlease make sure to input a valid pairing file! If the issue persists, replace your pairing with iloader or idevice_pair."
        case .invalidParameters(let msg):
            return "Invalid parameters: \n\(msg)"
        case .invalidResponse(let reason):
            return "Invalid server response: \(reason)"
        case .invalidVPN(let reason):
            return "VPN Connection Error:\n\(reason)\n\nPlease make sure LocalDevVPN is connected and running properly."
        case .minimuxerNotStarted(let reason):
            return "Minimuxer has not been started yet: \(reason)\n\nPlease complete pairing or start minimuxer before performing operations."
        case .missingAppBundle(let reason):
            return "The app bundle could not be found: \(reason)"
        case .missingAppGroup(let name):
            return "SideStore's shared app group “\(name)” could not be accessed."
        case .missingInfoPlist(let reason):
            return "The app's Info.plist could not be found: \(reason)"
        case .missingProvisioningProfile(let reason):
            return "A provisioning profile for the app could not be found: \(reason)"
        case .missingUpdate(let appName):
            return "No supported update could be found for “\(appName)”."
        case .noConnection(let reason):
            return "Network Connection Error:\n\(reason)\n\nPlease connect to Wi-Fi before attempting further operations."
        case .noDevice(let reason):
            return "SideStore is unable to reach the device endpoint:\n\(reason)\n\nPlease check your Connection Configuration in Settings."
        case .noVPN(let reason):
            return "VPN Connection Error:\n\(reason)\n\nPlease make sure LocalDevVPN is connected and running properly."
        case .notReachable(let reason):
            return reason.isEmpty ? "Device is not reachable at the specified IP or Endpoint." : reason
        case .openAppFailed(let name):
            return "SideStore was denied permission to launch \(name)."
        case .pairingNotComplete(let reason):
            return "Pairing Required: \(reason)\n\nWithout a valid pairing file, SideStore operations cannot connect to your device. Please pair your device or import a valid pairing file."
        case .pledgeInactive(let appName):
            return "Your pledge is no longer active. Please renew it to continue using \(appName) normally."
        case .SideJITIssue(let error):
            return "An error occurred while using SideJIT: \(error)"
        case .unknownUDID(let reason):
            return "SideStore could not determine this device's UDID: \(reason)\n\nPlease replace your pairing using iloader or idevice_pair."
        }
    }

    public var errorDescription: String? {
        return self.failureReason
    }

    public var failureReason: String? {
        return NSLocalizedString(self.rawDescription, comment: "")
    }

    public var recoverySuggestion: String? {
        switch self {
        case .invalidPairingFile:
            return NSLocalizedString("Import a valid mobiledevicepairing file.", comment: "")
        case .invalidVPN, .noVPN:
            return NSLocalizedString("Make sure LocalDevVPN is connected and running!", comment: "")
        case .noConnection:
            return NSLocalizedString("Connect to a Wi-Fi network, Bridge or a Wired network connection!", comment: "")
        default:
            return nil
        }
    }
}
func lcRefreshFailureFacts(_ error: Error, sourceStep: String? = nil) -> [String: String] {
    guard let operation = error as? OperationError else { return [:] }
    let kind: String
    switch operation {
    case .invalidParameters: kind = "invalidParameters"
    case .invalidOperationContext: kind = "invalidOperationContext"
    case .notAuthenticated: kind = "notAuthenticated"
    case .unknownResult: kind = "unknownResult"
    case .missingAppBundle: kind = "missingAppBundle"
    case .missingProvisioningProfile: kind = "missingProvisioningProfile"
    case .certificateExpired: kind = "certificateExpired"
    case .certificateRevoked: kind = "certificateRevoked"
    case .customCertificateExpired: kind = "customCertificateExpired"
    case .customCertificateRevoked: kind = "customCertificateRevoked"
    case .certificateChanged: kind = "certificateChanged"
    case .invalidApp: kind = "invalidApp"
    case .invalidPairingFile: kind = "invalidPairingFile"
    case .pairingNotComplete: kind = "pairingNotComplete"
    case .noDevice: kind = "noDevice"
    case .noConnection: kind = "noConnection"
    case .noVPN: kind = "noVPN"
    case .invalidVPN: kind = "invalidVPN"
    case .notReachable: kind = "notReachable"
    case .minimuxerNotStarted: kind = "minimuxerNotStarted"
    case .timedOut: kind = "timedOut"
    case .unknown: kind = "unknownOperation"
    default: kind = "otherOperation"
    }
    var facts = ["refresh_failure_kind": kind]
    // A finite, local pre-mutation observation. Never export the peer address
    // or classify arbitrary gateway text as a recoverable VPN condition.
    if sourceStep == "refreshReadiness" {
        if case .noVPN = operation { facts["refresh_readiness_reason"] = "vpnUnavailable" }
        // V3_COLD_VPN_PEER_ADDRESS_RECOVERY_V1: pinned minimuxer localVPN
        // endpoint.ip() guard, whose sole throw is deviceEndpointNotInitialized.
        // A generic utun can bypass host preflight while LocalDevVPN is off.
        // Keep the original noDevice kind and recognize the full local guard,
        // not every noDevice, a prefix, or arbitrary native/provider text.
        if case .noDevice(let message) = operation,
           message == "VPN tunnel iface is up but tunnel peer IP is not yet reachable — VPN may not be routing device traffic correctly. Cause: DeviceEndpointNotInitialized" {
            facts["refresh_readiness_reason"] = "peerAddressUnavailable"
        }
        if case .invalidVPN(let message) = operation {
            let prefix = "VPN tunnel iface is up and tunnel peer IP "
            let suffix = " is known, but TCP port poll failed — device may be unreachable on this interface"
            if message.hasPrefix(prefix), message.hasSuffix(suffix), message.utf8.count <= 512 {
                let peer = message.dropFirst(prefix.count).dropLast(suffix.count)
                let characters = "0123456789abcdefABCDEF:.%abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
                if !peer.isEmpty, peer.utf8.count <= 128,
                   peer.allSatisfy({ characters.contains($0) }) {
                    facts["refresh_readiness_reason"] = "peerProbeFailed"
                }
            }
        }
    }
    guard sourceStep == "provisioningProfileFetch",
          case .invalidParameters(let message) = operation,
          message.utf8.count <= 1024 else { return facts }
    let reason: String?
    switch message {
    case "FetchProvisioningProfilesOperation: context.targetAppBundle is nil":
        reason = "missingTargetAppBundle"
    case "Cannot update features for unknown team type.":
        reason = "unknownTeamType"
    case "Missing progress weight for step 'fetchProvisioningProfiles' in steps list":
        reason = "missingProgressWeight"
    case "Missing PipelineStep mapping for FetchProvisioningProfilesOperation":
        reason = "missingPipelineStepMapping"
    default:
        let reusePrefix = "Invalid maxReuse ("
        let reuseSuffix = ") for step 'fetchProvisioningProfiles' in steps list"
        let groupPrefix = "Application group '"
        let groupSuffix = "' contains raw placeholder '$(APP_GROUP_IDENTIFIER)'."
        if message.hasPrefix(reusePrefix), message.hasSuffix(reuseSuffix) {
            let value = String(message.dropFirst(reusePrefix.count).dropLast(reuseSuffix.count))
            // Match only the original guard's canonical nonpositive Int.
            reason = Int(value).flatMap { $0 <= 0 && String($0) == value ? "invalidProgressReuse" : nil }
        } else if message.hasPrefix(groupPrefix), message.hasSuffix(groupSuffix) {
            let group = message.dropFirst(groupPrefix.count).dropLast(groupSuffix.count)
            let allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-$()"
            // Full bounded template, not substring/provider-message matching.
            reason = group.utf8.count <= 256 && group.contains("$(APP_GROUP_IDENTIFIER)") &&
                group.allSatisfy({ allowed.contains($0) }) ? "unresolvedAppGroupPlaceholder" : nil
        } else { reason = nil }
    }
    if let reason { facts["local_precondition"] = reason }
    return facts
}
func lcRefreshFailureFactsBeforeColdVPN(_ error: Error, sourceStep: String? = nil) -> [String: String] {
    guard let operation = error as? OperationError else { return [:] }
    let kind: String
    switch operation {
    case .invalidParameters: kind = "invalidParameters"
    case .invalidOperationContext: kind = "invalidOperationContext"
    case .notAuthenticated: kind = "notAuthenticated"
    case .unknownResult: kind = "unknownResult"
    case .missingAppBundle: kind = "missingAppBundle"
    case .missingProvisioningProfile: kind = "missingProvisioningProfile"
    case .certificateExpired: kind = "certificateExpired"
    case .certificateRevoked: kind = "certificateRevoked"
    case .customCertificateExpired: kind = "customCertificateExpired"
    case .customCertificateRevoked: kind = "customCertificateRevoked"
    case .certificateChanged: kind = "certificateChanged"
    case .invalidApp: kind = "invalidApp"
    case .invalidPairingFile: kind = "invalidPairingFile"
    case .pairingNotComplete: kind = "pairingNotComplete"
    case .noDevice: kind = "noDevice"
    case .noConnection: kind = "noConnection"
    case .noVPN: kind = "noVPN"
    case .invalidVPN: kind = "invalidVPN"
    case .notReachable: kind = "notReachable"
    case .minimuxerNotStarted: kind = "minimuxerNotStarted"
    case .timedOut: kind = "timedOut"
    case .unknown: kind = "unknownOperation"
    default: kind = "otherOperation"
    }
    var facts = ["refresh_failure_kind": kind]
    // A finite, local pre-mutation observation. Never export the peer address
    // or classify arbitrary gateway text as a recoverable VPN condition.
    if sourceStep == "refreshReadiness" {
        if case .noVPN = operation { facts["refresh_readiness_reason"] = "vpnUnavailable" }
        if case .invalidVPN(let message) = operation {
            let prefix = "VPN tunnel iface is up and tunnel peer IP "
            let suffix = " is known, but TCP port poll failed — device may be unreachable on this interface"
            if message.hasPrefix(prefix), message.hasSuffix(suffix), message.utf8.count <= 512 {
                let peer = message.dropFirst(prefix.count).dropLast(suffix.count)
                let characters = "0123456789abcdefABCDEF:.%abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
                if !peer.isEmpty, peer.utf8.count <= 128,
                   peer.allSatisfy({ characters.contains($0) }) {
                    facts["refresh_readiness_reason"] = "peerProbeFailed"
                }
            }
        }
    }
    guard sourceStep == "provisioningProfileFetch",
          case .invalidParameters(let message) = operation,
          message.utf8.count <= 1024 else { return facts }
    let reason: String?
    switch message {
    case "FetchProvisioningProfilesOperation: context.targetAppBundle is nil":
        reason = "missingTargetAppBundle"
    case "Cannot update features for unknown team type.":
        reason = "unknownTeamType"
    case "Missing progress weight for step 'fetchProvisioningProfiles' in steps list":
        reason = "missingProgressWeight"
    case "Missing PipelineStep mapping for FetchProvisioningProfilesOperation":
        reason = "missingPipelineStepMapping"
    default:
        let reusePrefix = "Invalid maxReuse ("
        let reuseSuffix = ") for step 'fetchProvisioningProfiles' in steps list"
        let groupPrefix = "Application group '"
        let groupSuffix = "' contains raw placeholder '$(APP_GROUP_IDENTIFIER)'."
        if message.hasPrefix(reusePrefix), message.hasSuffix(reuseSuffix) {
            let value = String(message.dropFirst(reusePrefix.count).dropLast(reuseSuffix.count))
            // Match only the original guard's canonical nonpositive Int.
            reason = Int(value).flatMap { $0 <= 0 && String($0) == value ? "invalidProgressReuse" : nil }
        } else if message.hasPrefix(groupPrefix), message.hasSuffix(groupSuffix) {
            let group = message.dropFirst(groupPrefix.count).dropLast(groupSuffix.count)
            let allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-$()"
            // Full bounded template, not substring/provider-message matching.
            reason = group.utf8.count <= 256 && group.contains("$(APP_GROUP_IDENTIFIER)") &&
                group.allSatisfy({ allowed.contains($0) }) ? "unresolvedAppGroupPlaceholder" : nil
        } else { reason = nil }
    }
    if let reason { facts["local_precondition"] = reason }
    return facts
}

let coldVPNPeerGuardMessage = "VPN tunnel iface is up but tunnel peer IP is not yet reachable — VPN may not be routing device traffic correctly. Cause: DeviceEndpointNotInitialized"
enum LiveContainerVPNRefreshRecoveryPolicy {
    static func eligibleFailure(_ failure: CombinedFailure, runID: String) -> Bool {
        guard failure.operation == "refresh", failure.correlationID == runID,
              failure.stage == .command, failure.code == .failed,
              failure.sourceStep == .refreshReadiness, failure.safeCause == nil,
              failure.retryable != false else { return false }
        let kind = failure.signingContext["refresh_failure_kind"]
        let reason = failure.signingContext["refresh_readiness_reason"]
        return (kind == "noVPN" && reason == "vpnUnavailable") ||
            (kind == "invalidVPN" && reason == "peerProbeFailed") ||
            (kind == "noDevice" && reason == "peerAddressUnavailable")
    }

    static func permitsRecovery(error: Error, runID: String, source: String,
                                hasBackgroundTask: Bool, activationAlreadyAttempted: Bool,
                                activeRunID: String?, expectedRunID: String?,
                                requestID: String?, activeRequestID: String?, record: [String: Any]?,
                                hostHandoffPending: Bool, uncertainMutationRunID: String?,
                                manifest: [String: Any]?) -> Bool {
        guard source == "manual", !hasBackgroundTask,
              !activationAlreadyAttempted, activeRunID == runID, expectedRunID == runID,
              let requestID, UUID(uuidString: requestID)?.uuidString == requestID,
              activeRequestID == requestID, let record,
              record["run_id"] as? String == runID, record["request_id"] as? String == requestID,
              record["state"] as? String == "running",
              !hostHandoffPending, uncertainMutationRunID == nil,
              let failure = error as? CombinedFailure, eligibleFailure(failure, runID: runID),
              let manifest, CombinedVerification.hasCompleteTerminalResults(manifest, runID: runID),
              manifest["host_handoff"] as? Bool != true,
              let entries = manifest["results"] as? [[String: Any]] else { return false }
        // A selected batch error alone cannot prove that another app was not
        // installed. Every attempted app must have the same safe early boundary.
        return entries.allSatisfy { entry in
            guard entry["success"] as? Bool == false,
                  let wire = entry["failure"] as? [String: Any],
                  wire["correlationID"] as? String == runID,
                  let failure = CombinedFailure.decode(wire, expectedID: runID) else { return false }
            return eligibleFailure(failure, runID: runID)
        }
    }

    // The actual scheduler uses this one-shot orchestration. Fixture closures
    // replace only external effects, not retry/cancellation decisions.
    @MainActor
    static func run(attempt: () async throws -> Void,
                    mayRecover: (Error) -> Bool,
                    activate: () async throws -> Void,
                    settle: () async throws -> Void,
                    prepareRetry: () throws -> Void) async throws {
        try Task.checkCancellation()
        do { try await attempt() }
        catch {
            try Task.checkCancellation()
            guard mayRecover(error) else { throw error }
            try await activate()
            try Task.checkCancellation()
            try await settle()
            try Task.checkCancellation()
            try prepareRetry()
            // Deliberately outside a retry loop. A second failure is final for
            // this attempt, regardless of whether it still describes the VPN.
            try await attempt()
        }
    }
}
@MainActor
final class LiveContainerVPNActivationWaiter {
    enum Outcome: Equatable {
        case returned
        case openFailed
        case timedOut
        case cancelled
    }

    let runID: String
    private let onSettle: @MainActor (String, Outcome) -> Void
    private var continuation: CheckedContinuation<Outcome, Never>?
    private(set) var outcome: Outcome?

    init(runID: String, onSettle: @escaping @MainActor (String, Outcome) -> Void = { _, _ in }) {
        self.runID = runID
        self.onSettle = onSettle
    }

    func value() async -> Outcome {
        await withCheckedContinuation { continuation in
            if let outcome {
                continuation.resume(returning: outcome)
            } else {
                self.continuation = continuation
            }
        }
    }

    @discardableResult
    func settle(_ outcome: Outcome) -> Bool {
        guard self.outcome == nil else { return false }
        self.outcome = outcome
        onSettle(runID, outcome)
        let continuation = self.continuation
        self.continuation = nil
        continuation?.resume(returning: outcome)
        return true
    }
}
enum LiveContainerVPNReturnMarkerPolicy {
    static func marker(runID: String, requestedAt: Date) -> [String: Any]? {
        guard UUID(uuidString: runID)?.uuidString == runID else { return nil }
        return ["run_id": runID, "requested_at": requestedAt]
    }

    static func owner(in value: Any?) -> String? {
        guard let marker = value as? [String: Any],
              let runID = marker["run_id"] as? String,
              UUID(uuidString: runID)?.uuidString == runID,
              marker["requested_at"] is Date else { return nil }
        return runID
    }

    static func requestedAt(in value: Any?) -> Date? {
        if let marker = value as? [String: Any], owner(in: marker) != nil {
            return marker["requested_at"] as? Date
        }
        // A Date marker is the prior on-disk format. Consume it once so an
        // upgrade during VPN activation keeps its existing return behavior.
        return value as? Date
    }

    static func isSameMarker(_ first: Any?, _ second: Any?) -> Bool {
        if let firstOwner = owner(in: first),
           let secondOwner = owner(in: second) {
            let firstDate = (first as? [String: Any])?["requested_at"] as? Date
            let secondDate = (second as? [String: Any])?["requested_at"] as? Date
            return firstOwner == secondOwner && firstDate == secondDate
        }
        if owner(in: first) == nil, owner(in: second) == nil,
           let firstDate = first as? Date, let secondDate = second as? Date {
            return firstDate == secondDate
        }
        return false
    }

    static func isOwned(by runID: String, value: Any?) -> Bool {
        owner(in: value) == runID
    }

    static func shouldConsume(requestedAt: Date, now: Date) -> Bool {
        let age = now.timeIntervalSince(requestedAt)
        return age >= 0 && age < 120
    }

    static func shouldResume(_ value: Any?, now: Date) -> Bool {
        guard let requestedAt = requestedAt(in: value) else { return false }
        return shouldConsume(requestedAt: requestedAt, now: now)
    }
}
@main
struct VPNRefreshRecoveryCases {
    static let id = "11111111-1111-1111-1111-111111111111"
    static let other = "22222222-2222-2222-2222-222222222222"
    static func failure(kind: String = "noVPN", reason: String = "vpnUnavailable",
                        run: String = id, step: CombinedFailure.SourceStep = .refreshReadiness,
                        stage: CombinedFailure.Stage = .command, retryable: Bool? = nil) -> CombinedFailure {
        CombinedFailure(operation: "refresh", stage: stage, code: .failed, id: run,
            retryable: retryable, sourceStep: step,
            signingContext: ["refresh_failure_kind": kind, "refresh_readiness_reason": reason])
    }
    static func manifest(_ failures: [CombinedFailure] = [failure()]) -> [String: Any] {
        let ids = failures.indices.map { "fixture.app.\($0)" }
        return ["version": 2, "schema": "LiveContainerRefreshManifestV2", "run_id": id,
                "expected_ids": ids, "requested_ids": ids, "skipped_ids": [String](), "host_handoff": false,
                "results": failures.enumerated().map { index, value in
                    ["bundle_id": ids[index], "success": false, "failure": value.wire] as [String: Any]
                }]
    }
    static func permits(_ failure: Error = failure(), source: String = "manual", background: Bool = false,
                        activated: Bool = false, active: String? = id, expected: String? = id,
                        request: String? = other, activeRequest: String? = other,
                        record: [String: Any]? = ["run_id": id, "request_id": other, "state": "running"],
                        handoff: Bool = false, uncertain: String? = nil, manifest value: [String: Any]? = manifest()) -> Bool {
        LiveContainerVPNRefreshRecoveryPolicy.permitsRecovery(error: failure, runID: id, source: source,
            hasBackgroundTask: background, activationAlreadyAttempted: activated, activeRunID: active,
            expectedRunID: expected, requestID: request, activeRequestID: activeRequest, record: record,
            hostHandoffPending: handoff, uncertainMutationRunID: uncertain, manifest: value)
    }
    enum FixtureError: Error { case activation, settlement, ownership, second }
    @MainActor
    static func flow(firstFails: Bool = true, allowed: Bool = true, activationFails: Bool = false,
                     settlementFails: Bool = false, ownershipLost: Bool = false, secondFails: Bool = false,
                     cancelAt: String? = nil, coldPeerFailure: CombinedFailure? = nil) async -> ([String], String) {
        var events: [String] = []; var attempts = 0
        let task = Task { @MainActor () -> String in
            do {
                try await LiveContainerVPNRefreshRecoveryPolicy.run(attempt: {
                    attempts += 1; events.append("attempt\(attempts)")
                    if attempts == 1 && firstFails { throw coldPeerFailure ?? failure() }
                    if attempts == 2 && secondFails { throw FixtureError.second }
                }, mayRecover: { error in
                    events.append("eligibility")
                    if let coldPeerFailure { return permits(error, manifest: manifest([coldPeerFailure])) }
                    return allowed
                }, activate: {
                    events.append("activate")
                    if cancelAt == "activation" { withUnsafeCurrentTask { $0?.cancel() } }
                    if activationFails { throw FixtureError.activation }
                }, settle: {
                    events.append("settle")
                    if cancelAt == "settlement" { withUnsafeCurrentTask { $0?.cancel() } }
                    if settlementFails { throw FixtureError.settlement }
                }, prepareRetry: {
                    events.append("prepare")
                    if ownershipLost { throw FixtureError.ownership }
                })
                return "success"
            } catch is CancellationError { return "cancelled" }
            catch { return "failure" }
        }
        let result = await task.value
        return (events, result)
    }
    @MainActor
    static func main() async throws {
        var names: [String] = []
        func check(_ name: String, _ value: Bool) { precondition(value, name); names.append(name) }
        check("typed_missing_vpn_allowed", permits())
        let peer = failure(kind: "invalidVPN", reason: "peerProbeFailed")
        check("finite_peer_probe_allowed", permits(peer, manifest: manifest([peer])))
        check("unknown_invalidvpn_rejected", !permits(failure(kind: "invalidVPN", reason: "unknown")))
        check("missing_finite_reason_rejected", !permits(failure(reason: "")))
        check("signing_invalid_parameters_rejected", !permits(failure(kind: "invalidParameters", step: .provisioningProfileFetch, stage: .signing)))
        check("pairing_failure_rejected", !permits(failure(kind: "invalidPairingFile")))
        check("other_backend_readiness_rejected", !permits(failure(kind: "noDevice")))
        check("explicit_nonretryable_rejected", !permits(failure(retryable: false)))
        check("wrong_outer_run_rejected", !permits(failure(run: other)))
        check("background_source_rejected", !permits(source: "bgprocessing"))
        check("background_task_rejected", !permits(background: true))
        check("resume_source_rejected", !permits(source: "launch_or_resume"))
        check("vpn_return_recursion_rejected", !permits(source: "vpn_return"))
        check("alarm_not_new_recovery_authority", !permits(source: "alarm_action"))
        check("earlier_preflight_handoff_counts", !permits(activated: true))
        check("lost_active_owner_rejected", !permits(active: other))
        check("lost_expected_owner_rejected", !permits(expected: other))
        check("changed_manual_request_rejected", !permits(activeRequest: id))
        check("missing_manual_request_rejected", !permits(request: nil))
        check("terminal_ledger_rejected", !permits(record: ["run_id": id, "request_id": other, "state": "failed"]))
        check("wrong_ledger_request_rejected", !permits(record: ["run_id": id, "request_id": id, "state": "running"]))
        check("host_handoff_rejected", !permits(handoff: true))
        check("uncertain_mutation_rejected", !permits(uncertain: id))
        check("missing_manifest_rejected", !permits(manifest: nil))
        check("empty_manifest_rejected", !permits(manifest: manifest([])))
        check("every_attempted_app_matches", permits(manifest: manifest([failure(), peer])))
        check("mixed_backend_failure_rejected", !permits(manifest: manifest([failure(), failure(kind: "noDevice")])))
        check("mismatched_app_run_rejected", !permits(manifest: manifest([failure(run: other)])))
        var partial = manifest([failure(), peer]); partial["results"] = (partial["results"] as! [[String: Any]]).prefix(1).map { $0 }
        check("partial_manifest_rejected", !permits(manifest: partial))
        var success = manifest([failure(), peer]); var entries = success["results"] as! [[String: Any]]; entries[1]["success"] = true; success["results"] = entries
        check("partial_success_rejected", !permits(manifest: success))
        var handoff = manifest(); handoff["host_handoff"] = true
        check("manifest_handoff_rejected", !permits(manifest: handoff))
        check("raw_error_rejected", !permits(NSError(domain: "private", code: 1)))
        let missing = lcRefreshFailureFacts(OperationError.noVPN(reason: "SECRET_PAYLOAD"), sourceStep: "refreshReadiness")
        check("producer_typed_novpn_reason", missing == ["refresh_failure_kind": "noVPN", "refresh_readiness_reason": "vpnUnavailable"])
        let peerText = "VPN tunnel iface is up and tunnel peer IP fd00::1234 is known, but TCP port poll failed — device may be unreachable on this interface"
        let exact = lcRefreshFailureFacts(OperationError.invalidVPN(reason: peerText), sourceStep: "refreshReadiness")
        check("producer_exact_probe_reason_no_peer_export", exact == ["refresh_failure_kind": "invalidVPN", "refresh_readiness_reason": "peerProbeFailed"])
        check("producer_policy_invalidvpn_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "unsupported backend policy"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("producer_arbitrary_native_drop_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "broken pipe SECRET_PAYLOAD"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("producer_probe_wrong_boundary_ineligible", lcRefreshFailureFacts(OperationError.invalidVPN(reason: peerText), sourceStep: "refreshApplication")["refresh_readiness_reason"] == nil)
        // The fixture generator derives this exact string from the pinned local
        // minimuxer guard, not from a native/provider message supplied by a test.
        let coldFacts = lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness")
        let coldFailure = CombinedFailure(operation: "refresh", stage: .command, code: .failed,
            id: id, sourceStep: .refreshReadiness, signingContext: coldFacts)
        check("cold_peer_original_classifier_reproduces_missing_reason", lcRefreshFailureFactsBeforeColdVPN(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness") == ["refresh_failure_kind": "noDevice"])
        check("cold_peer_actual_producer_preserves_no_device_and_finite_reason", coldFacts == ["refresh_failure_kind": "noDevice", "refresh_readiness_reason": "peerAddressUnavailable"])
        check("cold_peer_missing_address_allowed", permits(coldFailure, manifest: manifest([coldFailure])))
        let coldDecoded = CombinedFailure.decode(coldFailure.wire, expectedID: id)
        check("cold_peer_wire_roundtrip_preserves_eligibility", coldDecoded.map { permits($0, manifest: manifest([$0])) } == true)
        check("cold_peer_all_app_failures_allowed", permits(coldFailure, manifest: manifest([coldFailure, coldFailure])))
        check("cold_peer_mixed_unknown_device_rejected", !permits(coldFailure, manifest: manifest([coldFailure, failure(kind: "noDevice", reason: "unknown")])))
        check("cold_peer_mixed_pairing_rejected", !permits(coldFailure, manifest: manifest([coldFailure, failure(kind: "invalidPairingFile", reason: "unknown")])))
        check("cold_peer_wrong_kind_reason_stripped", failure(kind: "invalidVPN", reason: "peerAddressUnavailable").signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_stage_reason_stripped", failure(kind: "noDevice", reason: "peerAddressUnavailable", stage: .signing).signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_boundary_reason_stripped", failure(kind: "noDevice", reason: "peerAddressUnavailable", step: .refreshApplication).signingContext["refresh_readiness_reason"] == nil)
        check("cold_peer_unclassified_device_error_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: "CoreDevice creation failed"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_remote_endpoint_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: "Remote endpoint IP is not configured or reachable. Cause: DeviceEndpointNotInitialized"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_appended_native_text_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage + " SECRET_PAYLOAD"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_other_local_error_rejected", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage.replacingOccurrences(of: "DeviceEndpointNotInitialized", with: "NetworkIfaceNotRefreshed")), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_wrong_operation_kind_rejected", lcRefreshFailureFacts(OperationError.invalidVPN(reason: coldVPNPeerGuardMessage), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_readiness_boundary_required", lcRefreshFailureFacts(OperationError.noDevice(reason: coldVPNPeerGuardMessage), sourceStep: "refreshApplication")["refresh_readiness_reason"] == nil)
        check("cold_peer_transport_policy_rejected", lcRefreshFailureFacts(OperationError.invalidVPN(reason: "Selected backend has no CoreDevice implementation and IPSec is absent"), sourceStep: "refreshReadiness")["refresh_readiness_reason"] == nil)
        check("cold_peer_background_never_activates", !permits(coldFailure, source: "bgprocessing", manifest: manifest([coldFailure])))
        check("cold_peer_initial_enable_not_repeated", !permits(coldFailure, activated: true, manifest: manifest([coldFailure])))
        let coldFlow = await flow(coldPeerFailure: coldFailure)
        check("cold_peer_actual_policy_enables_then_one_pipeline_retry", coldFlow.0 == ["attempt1", "eligibility", "activate", "settle", "prepare", "attempt2"] && coldFlow.1 == "success")
        let coldSecondFailure = await flow(secondFails: true, coldPeerFailure: coldFailure)
        check("cold_peer_retry_failure_is_final", coldSecondFailure.0 == coldFlow.0 && coldSecondFailure.1 == "failure")
        let coldCancel = await flow(cancelAt: "activation", coldPeerFailure: coldFailure)
        check("cold_peer_cancel_during_handoff_no_retry", coldCancel.0 == ["attempt1", "eligibility", "activate"] && coldCancel.1 == "cancelled")
        let coldLostOwner = await flow(ownershipLost: true, coldPeerFailure: coldFailure)
        check("cold_peer_changed_ledger_owner_no_retry", coldLostOwner.0 == ["attempt1", "eligibility", "activate", "settle", "prepare"] && coldLostOwner.1 == "failure")

        let direct = await flow(firstFails: false)
        check("ready_pipeline_no_handoff", direct.0 == ["attempt1"] && direct.1 == "success")
        let recovered = await flow()
        check("failed_ready_handoff_then_one_recheck", recovered.0 == ["attempt1", "eligibility", "activate", "settle", "prepare", "attempt2"] && recovered.1 == "success")
        let repeated = await flow(secondFails: true)
        check("second_failure_no_third_attempt", repeated.0 == recovered.0 && repeated.1 == "failure")
        let denied = await flow(allowed: false)
        check("ineligible_failure_no_handoff", denied.0 == ["attempt1", "eligibility"] && denied.1 == "failure")
        let open = await flow(activationFails: true)
        check("launch_failure_no_retry", open.0 == ["attempt1", "eligibility", "activate"] && open.1 == "failure")
        let settle = await flow(settlementFails: true)
        check("settlement_failure_no_retry", settle.0 == ["attempt1", "eligibility", "activate", "settle"] && settle.1 == "failure")
        let lost = await flow(ownershipLost: true)
        check("ownership_loss_no_retry", lost.0 == ["attempt1", "eligibility", "activate", "settle", "prepare"] && lost.1 == "failure")
        let cancelActivation = await flow(cancelAt: "activation")
        check("cancelled_handoff_no_retry", cancelActivation.0 == ["attempt1", "eligibility", "activate"] && cancelActivation.1 == "cancelled")
        let cancelSettle = await flow(cancelAt: "settlement")
        check("cancelled_settlement_no_retry", cancelSettle.0 == ["attempt1", "eligibility", "activate", "settle"] && cancelSettle.1 == "cancelled")
        var settles = 0
        let waiter = LiveContainerVPNActivationWaiter(runID: id) { _, _ in settles += 1 }
        waiter.settle(.timedOut); waiter.settle(.returned)
        let outcome = await waiter.value()
        check("timeout_late_return_settles_once", outcome == .timedOut && settles == 1)
        let start = Date(timeIntervalSince1970: 100)
        let marker = LiveContainerVPNReturnMarkerPolicy.marker(runID: id, requestedAt: start)!
        check("expired_cold_return_not_replayed", !LiveContainerVPNReturnMarkerPolicy.shouldResume(marker, now: start.addingTimeInterval(120)))
        check("marker_other_owner_not_cleared", !LiveContainerVPNReturnMarkerPolicy.isOwned(by: other, value: marker))
        let receiptURL = URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().appendingPathComponent("sources.json")
        let receipt = try JSONSerialization.jsonObject(with: Data(contentsOf: receiptURL)) as! [String: Any]
        precondition(names == receipt["expected_case_names"] as! [String])
        let report: [String: Any] = ["schema": "vpn-refresh-recovery-cases-v1", "status": "pass", "cases": names,
            "case_count": names.count, "network_executed": false, "native_provider_executed": false]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            .write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
        print("VPN_REFRESH_RECOVERY_PASS cases=\(names.count)")
    }
}
