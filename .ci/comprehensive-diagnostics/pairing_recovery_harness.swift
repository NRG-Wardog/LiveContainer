// Synthetic boundaries only. The marked product bodies are inserted unchanged.
private enum FixtureError: Error { case assertion(String), failed }
private func expect(_ value: @autoclosure () -> Bool, _ name: String) throws {
    if !value() { throw FixtureError.assertion(name) }
}
struct V3DirectMutationRecoveryRecord {
    enum Phase: String { case prepared, dispatched, terminal, unknown }
    let requestID: String
    let operation: String
    var phase: Phase
    var serviceInstanceID: String
    var terminalOutcome: String?
}
enum V3OperationRecoveryJournal {
    static var record: V3DirectMutationRecoveryRecord?
    static func reserveDirect(request: [String: Any], requestID: String, serviceInstanceID: String,
                              teamIdentifier: String?, identityStamp: String?, containerRoot: URL? = nil) throws -> Bool {
        guard record == nil, let operation = request["operation"] as? String else { return false }
        record = .init(requestID: requestID, operation: operation, phase: .prepared,
                       serviceInstanceID: serviceInstanceID, terminalOutcome: nil)
        return true
    }
    static func beginDirectDispatch(requestID: String, serviceInstanceID: String, containerRoot: URL? = nil) throws -> Bool {
        guard record?.requestID == requestID, record?.phase == .prepared else { return false }
        record?.phase = .dispatched
        record?.serviceInstanceID = serviceInstanceID
        return true
    }
    static func settleDirect(requestID: String, terminalOutcome: String, containerRoot: URL? = nil) throws -> Bool {
        guard record?.requestID == requestID,
              record?.phase == .dispatched || record?.phase == .unknown else { return false }
        record?.phase = .terminal
        record?.terminalOutcome = terminalOutcome
        return true
    }
    static func markDirectUnknownAfterRunFailure(requestID: String, serviceInstanceID: String, containerRoot: URL? = nil) throws -> Bool {
        guard record?.requestID == requestID, record?.phase == .dispatched,
              record?.serviceInstanceID == serviceInstanceID else { return false }
        record?.phase = .unknown
        return true
    }
    static func clearPreparedDirectAfterNotDispatched(requestID: String, containerRoot: URL? = nil) throws -> Bool {
        guard record?.requestID == requestID, record?.phase == .prepared else { return false }
        record = nil
        return true
    }
    static func direct(containerRoot: URL? = nil) throws -> V3DirectMutationRecoveryRecord? { record }
    static func markDirectUnknownIfOwnerLost(requestID: String, currentServiceInstanceID: String,
                                           containerRoot: URL? = nil) throws -> V3DirectMutationRecoveryRecord? {
        guard record?.requestID == requestID else { return nil }
        if record?.phase == .dispatched && record?.serviceInstanceID != currentServiceInstanceID {
            record?.phase = .unknown
            record?.serviceInstanceID = currentServiceInstanceID
        }
        return record
    }
    static func reconcileDirect(requestID: String, allowUnknownDeviceCheck: Bool, containerRoot: URL? = nil) throws -> Bool {
        guard record?.requestID == requestID,
              record?.phase == .terminal || record?.phase == .prepared ||
                (record?.phase == .unknown && allowUnknownDeviceCheck) else { return false }
        record = nil
        return true
    }
}
enum FixturePlacementOutcome: String {
    case ready = "adoptedReady", notReady = "adoptedConnectionNotReady", uncertain = "adoptedCleanupUncertain"
}
enum V3BackendCommands {
    static var outcome = FixturePlacementOutcome.ready
    static func pairingUsePlaced(id: String) async throws -> FixturePlacementOutcome { outcome }
}
enum ServiceError: String, Error { case notReady, invalidRequest, notFound, unsupported, busy }

@MainActor final class FixtureService {
    let recoveryServiceInstanceID = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    func encode(_ reply: [String: Any], operation: String) -> Data {
        V3ResponseEncoder.encode(reply, operation: operation, limit: ServiceWireContract.responseLimit)
    }
    func snapshot() throws -> [String: Any] {
        var result: [String: Any] = ["busy": V3OperationRecoveryJournal.record != nil,
            "activeMutation": V3OperationRecoveryJournal.record?.phase == .dispatched,
            "recoveryHold": V3OperationRecoveryJournal.record != nil,
            "recoveryJournalUnreadable": false]
        if let record = V3OperationRecoveryJournal.record { result["directRecovery"] = safeDirectRecovery(record) }
        return result
    }
    // ACTUAL_SAFE_RECOVERY_INSERT
    // ACTUAL_INSPECT_INSERT
    func directRecoveryPostcondition(_ record: V3DirectMutationRecoveryRecord) async -> String {
        // No live pairing readback is claimed; production pairing recovery has
        // exactly this manual-check postcondition.
        "manualCheckRequired"
    }
    func checkOwner(operation: String, target: String, id: String, reply: (Data) -> Void) {
        let directRecoveryRecord = V3OperationRecoveryJournal.record
        // ACTUAL_OWNER_ADMISSION_INSERT
    }
    func run(_ operation: String, request: [String: Any], id: String) async throws -> [String: Any] {
        let target = request["target"] as? String ?? ""
        let payload = request["payload"] as? [String: Any] ?? [:]
        switch operation {
        // ACTUAL_PAIRING_DISPATCH_INSERT
        case "directRecoveryInspect":
            return try await directRecoveryInspection(requestID: target)
        // ACTUAL_RECONCILE_DISPATCH_INSERT
        default: throw ServiceError.invalidRequest
        }
    }
    func execute(_ data: Data) async throws -> Data {
        guard let request = ServiceWireContract.decodeRequest(data),
              let operation = request["operation"] as? String,
              let target = request["target"] as? String,
              let id = request["id"] as? String else { throw FixtureError.failed }
        var refused: Data?
        checkOwner(operation: operation, target: target, id: id) { refused = $0 }
        if let refused { return refused }
        do {
            let result: [String: Any]
            if operation == "pairingUsePlaced" {
                guard try V3DirectMutationRecoveryLifecycle.reserve(request: request, requestID: id,
                    serviceInstanceID: recoveryServiceInstanceID, teamIdentifier: nil, identityStamp: nil) else { throw ServiceError.busy }
                guard let reply = try await V3DirectMutationRecoveryLifecycle.dispatchAndSettle(
                    requestID: id, operation: operation, serviceInstanceID: recoveryServiceInstanceID,
                    run: { try await self.run(operation, request: request, id: id) }) else { throw ServiceError.busy }
                result = reply
            } else { result = try await run(operation, request: request, id: id) }
            return encode(["version": 1, "id": id, "ok": true, "result": result], operation: operation)
        } catch let failure as CombinedFailure {
            return encode(["version": 1, "id": id, "error": "invalidRequest", "failure": failure.wire], operation: operation)
        }
    }
}

@MainActor final class V3ServiceBridge {
    static var shared = V3ServiceBridge()
    struct Authority { var serviceEpoch: UInt64 = 1 }
    var statusWriteAuthority = Authority()
    var currentStatusServiceInstanceID = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    var hostRecoveryHold = false
    var requestBehavior = "normal"
    let service = FixtureService()
    static func strictBool(_ raw: Any?) -> Bool? { V3WireContract.strictBool(raw) }
    func setHostRecoveryHold(_ value: Bool) { hostRecoveryHold = value }
    func request(operation: String, target: String = "", payload: [String: Any]? = nil) async throws -> [String: Any] {
        if requestBehavior == "fail" { throw FixtureError.failed }
        if requestBehavior == "cancel" { throw CancellationError() }
        let id = UUID().uuidString
        let data = try submittedRequest(operation: operation, target: target, payload: payload, id: id)
        let response = try await service.execute(data)
        var result = try V3CatalogRequestContext.classifyReply(response, operation: operation, id: id)
        if operation == "pairingUsePlaced" { result["_v3StatusAuthorityRequestID"] = id }
        if requestBehavior == "cancelAfterResponse" { withUnsafeCurrentTask { $0?.cancel() } }
        if requestBehavior == "wrongTarget" { result["requestID"] = UUID().uuidString }
        if requestBehavior == "falseAck" { result["reconciled"] = false }
        if requestBehavior == "epochChanged" { statusWriteAuthority.serviceEpoch += 1 }
        if requestBehavior == "serviceChanged" { currentStatusServiceInstanceID = UUID().uuidString }
        return result
    }
    func submittedRequest(operation: String, target: String, payload: [String: Any]?, id: String) throws -> Data {
        let timeout: TimeInterval = 30
        let cursor: Int? = nil
        let knownOperationSessions: [String: Date] = [:]
        // ACTUAL_REQUEST_ENCODE_INSERT
        return data
    }
    // ACTUAL_ACK_INSERT
}

struct V3OperationRecoveryRecord {
    enum Phase: String { case prepared, dispatched, terminal, unknown }
    let sessionID: String
    let kind: String
    let phase: Phase
    let stagedIPAToken: String?
}
@MainActor final class FixtureStatusStore {
    var unresolvedDirectRecovery: V3HostDirectRecoveryRecord?
    var directRecoveryPostcondition: V3DirectRecoveryPostcondition?
    var unresolvedOperationRecovery: V3OperationRecoveryRecord?
    var unresolvedRefreshRecoveryRunID: String?
    var unresolvedRecoveryJournalUnreadable = false
    func observeRecoveryStorageFailure(_ snapshot: [String: Any]) {}
    // ACTUAL_FULL_SNAPSHOT_INSERT
    // BASELINE_FULL_SNAPSHOT_INSERT
}

@MainActor private func capture(_ action: () async throws -> [String: Any]) async throws -> CombinedFailure {
    do { _ = try await action() } catch let failure as CombinedFailure { return failure }
    throw FixtureError.assertion("expected CombinedFailure")
}
@MainActor private func fresh() -> (V3ServiceBridge, FixtureStatusStore) {
    V3OperationRecoveryJournal.record = nil
    V3BackendCommands.outcome = .ready
    V3ServiceBridge.shared = V3ServiceBridge()
    return (V3ServiceBridge.shared, FixtureStatusStore())
}
private func emptySnapshot() -> [String: Any] {
    ["busy": false, "activeMutation": false, "recoveryHold": false, "recoveryJournalUnreadable": false]
}

@main struct PairingRecoveryFixture {
    @MainActor static func main() async throws {
        var cases: [String] = []
        // Exact before-fix store body: a successful import returns a dispatched
        // snapshot, ACK clears journal, absent snapshot retains the stale owner.
        do {
            let (bridge, store) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            try expect((result["directRecovery"] as? [String: Any])?["phase"] as? String == "dispatched", "handler snapshot precedes terminal settlement")
            try expect(V3OperationRecoveryJournal.record?.phase == .terminal, "service terminal after reply snapshot")
            store.applyBaselineFullRecoveryEvidence(result)
            let id = store.unresolvedDirectRecovery!.requestID
            let ack = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced")
            try expect(ack && V3OperationRecoveryJournal.record == nil, "ACK deletes exact terminal journal")
            store.applyBaselineFullRecoveryEvidence(emptySnapshot())
            try expect(store.unresolvedDirectRecovery?.requestID == id && bridge.hostRecoveryHold, "delivered stale host owner reproduced")
            let failure = try await capture { try await bridge.request(operation: "directRecoveryInspect", target: id) }
            try expect(failure.operation == "command" && failure.code == .invalidConfiguration && failure.stage == .command, "reproduced command C02 primary")
            try expect(failure.safeCause == .directRecoveryRecordMissing, "missing owner classified")
            cases.append("baseline-dispatched-snapshot-ack-stale-owner-reproduced")
        }
        do {
            let (bridge, store) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            store.applyFullRecoveryEvidence(result)
            let id = store.unresolvedDirectRecovery!.requestID
            let ack = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced")
            try expect(ack && store.unresolvedDirectRecovery?.requestID == id, "ACK alone does not clear local state")
            store.applyFullRecoveryEvidence(emptySnapshot())
            try expect(store.unresolvedDirectRecovery == nil && !bridge.hostRecoveryHold, "verified current snapshot retires exact ACK owner")
            cases.append("exact-ack-plus-quiescent-snapshot-retires-owner")
        }
        for behavior in ["fail", "cancel", "cancelAfterResponse", "wrongTarget", "falseAck", "epochChanged", "serviceChanged"] {
            let (bridge, store) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            store.applyFullRecoveryEvidence(result)
            let id = store.unresolvedDirectRecovery!.requestID
            bridge.requestBehavior = behavior
            let task = Task { await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced") }
            let ack = await task.value
            try expect(!ack, "uncertain ACK rejected: \(behavior)")
            store.applyFullRecoveryEvidence(emptySnapshot())
            try expect(store.unresolvedDirectRecovery?.requestID == id && bridge.hostRecoveryHold, "uncertain ACK retains fence: \(behavior)")
            cases.append("ack-\(behavior)-retains-owner")
        }
        do {
            let (bridge, store) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            store.applyFullRecoveryEvidence(result)
            let first = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced")
            bridge.requestBehavior = "fail"
            let second = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced")
            try expect(first && !second, "failed repeated ACK does not invent a second success")
            store.applyFullRecoveryEvidence(emptySnapshot())
            try expect(store.unresolvedDirectRecovery == nil && !bridge.hostRecoveryHold, "prior exact successful proof remains valid")
            cases.append("failed-repeat-ack-retains-only-original-success-proof")
        }
        for state in ["missingAck", "newerOwner", "differentOperation", "unreadable", "activeMutation", "busy", "malformedDirect", "postAckEpochChanged"] {
            let (bridge, store) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            store.applyFullRecoveryEvidence(result)
            if state != "missingAck" { _ = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced") }
            var snapshot = emptySnapshot()
            if state == "newerOwner" || state == "differentOperation" {
                var record = (result["directRecovery"] as! [String: Any])
                if state == "newerOwner" { record["requestID"] = UUID().uuidString }
                else { record["operation"] = "pairingImportData" }
                store.unresolvedDirectRecovery = V3HostDirectRecoveryRecord(snapshotValue: record)
            }
            if state == "unreadable" { snapshot["recoveryJournalUnreadable"] = true; snapshot["recoveryHold"] = true }
            if state == "activeMutation" { snapshot["activeMutation"] = true }
            if state == "busy" { snapshot["busy"] = true }
            if state == "malformedDirect" { snapshot["directRecovery"] = ["bad": "value"] }
            if state == "postAckEpochChanged" { bridge.statusWriteAuthority.serviceEpoch += 1 }
            let held = store.unresolvedDirectRecovery!.requestID
            store.applyFullRecoveryEvidence(snapshot)
            try expect(store.unresolvedDirectRecovery?.requestID == held && bridge.hostRecoveryHold, "fence retained: \(state)")
            cases.append("snapshot-\(state)-retains-owner")
        }
        do {
            let (bridge, store) = fresh()
            V3BackendCommands.outcome = .uncertain
            let result = try await bridge.request(operation: "pairingUsePlaced")
            store.applyFullRecoveryEvidence(result)
            let ack = await bridge.acknowledgeDirectRecoveryAfterSuccess(result, operation: "pairingUsePlaced")
            try expect(!ack && V3OperationRecoveryJournal.record?.phase == .unknown, "cleanup uncertainty remains durable")
            store.applyFullRecoveryEvidence(emptySnapshot())
            try expect(store.unresolvedDirectRecovery != nil && bridge.hostRecoveryHold, "cleanup uncertainty not erased")
            cases.append("cleanup-uncertainty-retains-durable-and-host-owner")
        }
        let requestID = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
        let targetID = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"
        let canary = "SECRET_PAIRING_CONTENT_OR_ACCOUNT_CANARY"
        for operation in ["pairingUsePlaced", "directRecoveryInspect", "directRecoveryReconcile"] {
            let (bridge, _) = fresh()
            let target = operation == "pairingUsePlaced" ? "" : targetID
            let payload: [String: Any]? = operation == "directRecoveryReconcile" ? ["ackTerminal": true] : nil
            let outbound = try bridge.submittedRequest(operation: operation, target: target, payload: payload, id: requestID)
            try expect(ServiceWireContract.decodeRequest(outbound)?["operation"] as? String == operation, "real wire accepts \(operation)")
            let original = CombinedFailure(operation: "command", stage: .command, code: .invalidConfiguration,
                id: requestID, retryable: false, safeCause: .directRecoveryRecordMissing)
            let response = V3ResponseEncoder.encode(["version": 1, "id": requestID, "failure": original.wire,
                "error": "invalidRequest", "untrusted": canary], operation: operation, limit: V3WireContract.responseLimit)
            let failure = try await capture { try V3CatalogRequestContext.classifyReply(response, operation: operation, id: requestID) }
            try expect(failure.operation == original.operation && failure.stage == original.stage && failure.code == original.code && failure.safeCause == original.safeCause && failure.correlationID == original.correlationID, "primary error preserved")
            let copied = V3DiagnosticCopy.details(visibleMessage: failure.safeMessage, technical: failure.technicalDetails)
            try expect(copied.contains("request_operation=\(operation)") && copied.contains("request_correlation=\(requestID)") && !copied.contains(canary), "actual copy preserves bounded request context")
            cases.append("wire-classify-copy-\(operation)")
        }
        for mismatch in ["outer", "inner", "unallowlistedOperation"] {
            let otherID = UUID().uuidString
            let original = CombinedFailure(operation: "command", stage: .command, code: .invalidConfiguration,
                id: mismatch == "inner" ? otherID : requestID)
            let response = V3ResponseEncoder.encode(["version": 1, "id": mismatch == "outer" ? otherID : requestID,
                "failure": original.wire], operation: "command", limit: V3WireContract.responseLimit)
            let operation = mismatch == "unallowlistedOperation" ? canary : "pairingUsePlaced"
            let failure = try await capture { try V3CatalogRequestContext.classifyReply(response, operation: operation, id: requestID) }
            try expect(failure.requestContext == nil && !failure.technicalDetails.contains(canary), "untrusted context rejected")
            cases.append("correlation-\(mismatch)-no-request-context")
        }
        do {
            let (bridge, _) = fresh()
            let result = try await bridge.request(operation: "pairingUsePlaced")
            let id = result["_v3StatusAuthorityRequestID"] as! String
            let mismatch = try await capture { try await bridge.request(operation: "directRecoveryInspect", target: UUID().uuidString) }
            try expect(mismatch.safeCause == .directRecoveryTargetMismatch, "different owner reason")
            let phase = try await capture { try await bridge.request(operation: "directRecoveryReconcile", target: id, payload: ["userConfirmed": true]) }
            try expect(phase.safeCause == .directRecoveryPhaseNotEligible && V3OperationRecoveryJournal.record != nil, "wrong phase leaves record")
            let mode = try await capture { try await bridge.service.run("directRecoveryReconcile", request: ["target": id, "payload": [:]], id: requestID) }
            try expect(mode.safeCause == .directRecoveryModeInvalid && V3OperationRecoveryJournal.record != nil, "defensive invalid mode leaves record")
            cases.append("finite-recovery-refusal-causes-preserve-journal")
        }
        guard CommandLine.arguments.count == 3, let bundle = Bundle(path: CommandLine.arguments[1]) else { throw FixtureError.failed }
        let deferred = appendActualProvisioningSuffix("Apple ID signed in. Add pairing before refreshing or installing apps.")
        let placementCases: [(String?, V3PlacedPairingPresentation.Severity)] = [
            ("adoptedReady", .success), ("adoptedConnectionNotReady", .warning),
            ("adoptedCleanupUncertain", .warning), (nil, .warning), (canary, .warning)]
        let placementMessages = placementCases.map { outcome, severity -> String in
            let result = V3PlacedPairingPresentation.result(outcome)
            precondition(result.severity == severity && !result.message.contains(canary))
            return result.message
        } + [V3PlacedPairingPresentation.failureMessage]
        for language in V3AppLanguage.allCases {
            for text in ["SideStore could not start or complete the requested command action.",
                         "SideStore could not start or complete the requested pairingUsePlaced action.",
                         "A previous placed pairing activation has an unresolved result", deferred] + placementMessages {
                let rendered = V3Localization.prose(text, language: language, bundle: bundle)
                let unavailable = V3Localization.prose(canary, language: language, bundle: bundle)
                try expect(!rendered.contains(unavailable) && !rendered.contains(canary), "localized known prose \(language.rawValue)")
                try expect(!unavailable.contains(canary), "unknown text remains filtered")
            }
            cases.append("localized-command-recovery-deferred-\(language.rawValue)")
        }
        do {
            let error = CombinedFailure(operation: "command", stage: .command, code: .invalidConfiguration,
                id: requestID, safeCause: .directRecoveryRecordMissing)
            let typed = V3CertificateImportFailureDetails.capture(error, step: .exportActive)
            try expect(typed.contains(error.technicalDetails) && typed.contains("certificate_import_step=exportActive"), "Settings preserves typed service failure")
            let unknown = V3CertificateImportFailureDetails.capture(NSError(domain: canary, code: 41,
                userInfo: [NSLocalizedDescriptionKey: canary]), step: .validateExport)
            try expect(!unknown.contains(canary), "Settings excludes arbitrary error text")
            try expect(V3CertificateImportFailureDetails.copySuffix(message: "new", captured: ("old", typed)).isEmpty, "Settings excludes stale diagnostic suffix")
            for operation in ["certPortalList", "certCreate"] {
                let original = CombinedFailure(operation: "command", stage: .signing, code: .failed,
                    id: requestID, sourceStep: .fetchCertificate)
                let response = V3ResponseEncoder.encode(["version": 1, "id": requestID, "failure": original.wire,
                    "error": "operationFailed", "untrusted": canary], operation: operation, limit: V3WireContract.responseLimit)
                let failure = try await capture { try V3CatalogRequestContext.classifyReply(response, operation: operation, id: requestID) }
                let copied = V3DiagnosticCopy.details(visibleMessage: failure.safeMessage, technical: failure.technicalDetails)
                try expect(copied.contains("request_operation=\(operation)") && copied.contains("source_step=fetchCertificate") && !copied.contains(canary), "certificate action and bounded cause reach actual Copy")
            }
            cases.append("certificate-import-safe-copy-and-stale-suffix")
        }
        let expectedCases: [String] = // EXPECTED_CASE_NAMES_INSERT
        try expect(cases == expectedCases, "frozen runtime case contract")
        let report: [String: Any] = ["schema": "pairing-recovery-cases-v1", "status": "pass",
            "fake_only": true, "native_pairing_executed": false, "cases": cases]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: CommandLine.arguments[2]))
        print("PAIRING_RECOVERY_BOUNDARY_PASS")
    }
}
