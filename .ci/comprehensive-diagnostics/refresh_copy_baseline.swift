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
