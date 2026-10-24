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
