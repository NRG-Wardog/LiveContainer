    var launchID: UUID?
    var refreshRunID: String?
    var refreshContinuation: CheckedContinuation<Void, Error>?
    var v3RefreshTerminalCallbackRunID: String?
    var sawIgnoredCallback = false
    func deliver(_ error: String?, runID: String, verification: Data?,
                 wrongRun: String? = nil, wrongLaunch: UUID? = nil) async -> Result<Void, Error> {
        let launch = UUID()
        launchID = launch
        refreshRunID = runID
        do {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                refreshContinuation = continuation
                completedRefresh(error, runID: wrongRun ?? runID, verification: verification, id: wrongLaunch ?? launch)
                if wrongRun != nil || wrongLaunch != nil {
                    sawIgnoredCallback = refreshContinuation != nil && v3RefreshTerminalCallbackRunID == nil
                    // Settle the still-pending synthetic call without admitting the wrong callback.
                    completedRefresh(error, runID: runID, verification: nil, id: launch)
                }
            }
            return .success(())
        } catch { return .failure(error) }
    }
