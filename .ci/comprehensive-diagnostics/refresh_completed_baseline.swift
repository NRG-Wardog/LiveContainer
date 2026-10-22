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
