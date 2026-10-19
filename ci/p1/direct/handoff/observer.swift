// Test-only, local candidate. This observer validates transport and binding;
// it does not independently establish native host ownership or pixel identity.
private enum P1DirectHandoff {
    static let waitSeconds = 120.0
    static let methodSeconds = 240.0 // Included in, never added to, native method allowance.
    static let maxInteger = 9_007_199_254_740_991.0

    private static func require(_ condition: Bool, _ reason: String) throws {
        guard condition else { throw P1CapabilityError(reason) }
    }
    private static func hash(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private static func matches(_ value: String, _ pattern: String) -> Bool {
        // Foundation's $ may also match before a trailing newline. Require the
        // complete range, so a superficially matching session is never used.
        guard let range = value.range(of: pattern, options: .regularExpression) else { return false }
        return range.lowerBound == value.startIndex && range.upperBound == value.endIndex
    }
    static func sessionOrFail() -> String? {
        guard let value = ProcessInfo.processInfo.environment["P1_DIRECT_SESSION"],
              matches(value, "^[0-9a-f]{32}$") else {
            XCTFail("fresh P1_DIRECT_SESSION (32 lowercase hex) required before launch")
            return nil
        }
        return value
    }
    private static func integer(_ value: Any?, _ minimum: Double = 0) throws -> Int {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue >= minimum,
              number.doubleValue <= maxInteger,
              number.doubleValue.rounded(.towardZero) == number.doubleValue else {
            throw P1CapabilityError("bounded exact integer required")
        }
        return number.intValue
    }
    private static func boolean(_ value: Any?, _ expected: Bool) throws {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID(),
              number.boolValue == expected else { throw P1CapabilityError("exact boolean required") }
    }
    private static func exactKeys(_ row: [String: Any], _ keys: Set<String>) throws {
        try require(Set(row.keys) == keys, "unexpected or missing handoff fields")
    }
    private static func sha(_ value: Any?) throws -> String {
        guard let result = value as? String, matches(result, "^[0-9a-f]{64}$") else {
            throw P1CapabilityError("SHA256 required")
        }
        return result
    }
    private static func rectangle(_ frame: CGRect) throws -> [Double] {
        let values = [frame.minX, frame.minY, frame.width, frame.height].map { Double($0) }
        try require(values.allSatisfy { $0.isFinite && abs($0) <= 65536 } &&
                    frame.width > 0 && frame.height > 0, "invalid accessibility geometry")
        return values
    }
    @MainActor private static func snapshot(_ app: XCUIApplication,
                                            copy: XCUIElement, marker: XCUIElement,
                                            baselineReady: XCUIElement) throws -> [String: Any] {
        try require(app.state == .runningForeground, "app must remain foreground")
        try require(app.buttons.matching(identifier: "signin.prompt.copy-details").count == 1 &&
                    copy.exists && copy.isEnabled && copy.isHittable &&
                    copy.identifier == "signin.prompt.copy-details" && copy.label == "Copy Details",
                    "Copy Details must be unique and steady before baseline")
        try require(app.otherElements.matching(identifier: "p1-video-marker").count == 1 &&
                    marker.exists && marker.identifier == "p1-video-marker", "live marker missing or ambiguous")
        try require(app.buttons.matching(identifier: "p1-video-baseline-ready").count == 1 &&
                    baselineReady.exists && baselineReady.isEnabled && baselineReady.isHittable &&
                    baselineReady.identifier == "p1-video-baseline-ready", "baseline fixture control unavailable")
        try require(app.windows.count == 1 && app.windows.firstMatch.exists, "unique app window required")
        let copyFrame = copy.frame, markerFrame = marker.frame
        let baselineFrame = baselineReady.frame, windowFrame = app.windows.firstMatch.frame
        let control = try rectangle(copyFrame), liveMarker = try rectangle(markerFrame)
        let baseline = try rectangle(baselineFrame), window = try rectangle(windowFrame)
        try require([copyFrame, markerFrame, baselineFrame].allSatisfy { windowFrame.contains($0) },
                    "control, marker, or baseline is outside app window")
        var anchors = [[String: Any]](), anchorFrames = [CGRect]()
        for ordinal in 1...4 {
            let identifier = "p1-direct-anchor-\(ordinal)"
            let query = app.otherElements.matching(identifier: identifier)
            try require(query.count == 1, "each of four anchors must be unique and present")
            let element = query.element
            try require(element.exists && element.identifier == identifier, "wrong anchor identity")
            let frame = element.frame, values = try rectangle(frame)
            try require(windowFrame.contains(frame), "anchor outside app window")
            try require(!([copyFrame, markerFrame, baselineFrame] + anchorFrames).contains {
                $0.intersects(frame)
            }, "anchor AX frame overlaps another retained region or control")
            anchorFrames.append(frame)
            anchors.append(["identifier": identifier, "ordinal": ordinal, "frame": values])
        }
        var features = [[String: Any]](), featureFrames = [CGRect]()
        for ordinal in 1...4 {
            let identifier = "p1-direct-feature-\(ordinal)"
            let query = app.otherElements.matching(identifier: identifier)
            try require(query.count == 1, "each of four registration features must be unique and present")
            let element = query.element
            try require(element.exists && element.identifier == identifier, "wrong feature identity")
            let frame = element.frame, values = try rectangle(frame)
            try require(frame.width == 3 && frame.height == 3 && windowFrame.contains(frame),
                        "whole actual 3-by-3-point feature AX frame required inside app window")
            try require(!([copyFrame, markerFrame, baselineFrame] + anchorFrames + featureFrames).contains {
                $0.intersects(frame)
            }, "feature AX frame overlaps another retained region or control")
            let board = anchorFrames[ordinal - 1]
            let horizontal = (ordinal == 1 || ordinal == 3) ? frame.maxX < board.minX : frame.minX > board.maxX
            let vertical = ordinal <= 2 ? frame.maxY < board.minY : frame.minY > board.maxY
            try require(horizontal && vertical, "feature does not have source-defined outward-corner adjacency")
            featureFrames.append(frame)
            features.append(["identifier": identifier, "ordinal": ordinal, "frame": values])
        }
        try require(app.state == .runningForeground, "app left foreground while sampling geometry")
        return ["coordinateSpace": "XCTest-screen-points", "orientation": "portrait-up",
                "copyIdentifier": copy.identifier, "copyLabel": copy.label,
                "copyFrame": control, "markerIdentifier": marker.identifier, "markerFrame": liveMarker,
                "baselineIdentifier": baselineReady.identifier, "baselineFrame": baseline,
                "windowFrame": window, "anchors": anchors, "features": features,
                "registrationModel": "whole-source-view-to-observed-support-v1",
                "sourceLocalityEstablished": false]
    }

    private static func validateAcknowledgement(_ data: Data, session: String,
                                                 requestHash: String, simulatorUDID: String) throws -> ([String: Any], Data) {
        try require(data.count <= 8192, "acknowledgement exceeds transport cap")
        guard let row = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw P1CapabilityError("acknowledgement object required")
        }
        // Exact reserialization rejects duplicate keys, trailing bytes, unknown
        // fields, and noncanonical number/string encodings in the host message.
        try require(try capabilityJSON(row) == data, "noncanonical acknowledgement")
        try exactKeys(row, ["schema", "session", "geometryRequestSHA256", "captureReadyProof",
                            "captureReadyProofSHA256", "admissionEligible"])
        try require(row["schema"] as? String == "p1-direct-baseline-ack-v1" &&
                    row["session"] as? String == session &&
                    row["geometryRequestSHA256"] as? String == requestHash,
                    "wrong schema, session, or immutable geometry hash")
        try boolean(row["admissionEligible"], false)
        guard let proof = row["captureReadyProof"] as? [String: Any] else {
            throw P1CapabilityError("owned capture-ready proof object required")
        }
        try exactKeys(proof, ["schema", "session", "geometryRequestSHA256", "captureInstance",
            "simulatorUDID", "guiPID", "windowID", "helperPID", "helperSourceSHA256",
            "ownedDeviceReceiptSHA256", "ownedGUIReceiptSHA256", "windowBindingReceiptSHA256",
            "fourAnchorProofSHA256", "streamReadyReceiptSHA256", "firstCompleteFrameSHA256",
            "firstCompleteFrameIndex", "firstCompleteFrameDisplayTime", "captureStarted",
            "firstCompleteFramePresent", "guiLiveRegistered", "fourAnchorsDecoded",
            "geometryFrozen", "captureErrors", "ownershipErrors", "admissionEligible"])
        try require(proof["schema"] as? String == "p1-direct-owned-capture-ready-v1" &&
                    proof["session"] as? String == session &&
                    proof["geometryRequestSHA256"] as? String == requestHash,
                    "capture proof is not bound to this geometry request/session")
        guard let instance = proof["captureInstance"] as? String,
              matches(instance, "^[0-9a-f]{32}$"),
              let udid = proof["simulatorUDID"] as? String,
              matches(udid, "^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"),
              udid == simulatorUDID else {
            throw P1CapabilityError("capture instance and exact canonical simulator UUID required")
        }
        let guiPID = try integer(proof["guiPID"], 2), helperPID = try integer(proof["helperPID"], 2)
        try require(guiPID <= 2_147_483_647 && helperPID <= 2_147_483_647 && guiPID != helperPID,
                    "invalid or conflated host process identities")
        try require(try integer(proof["windowID"], 1) <= 4_294_967_295, "invalid window ID")
        _ = try integer(proof["firstCompleteFrameIndex"])
        // Decimal string preserves the full native UInt64 tick value. It is a
        // display timestamp, never a callback/startCapture or runner timestamp.
        guard let displayTime = proof["firstCompleteFrameDisplayTime"] as? String,
              matches(displayTime, "^[1-9][0-9]{0,19}$"), UInt64(displayTime) != nil else {
            throw P1CapabilityError("nonzero exact UInt64 displayTime decimal string required")
        }
        for key in ["helperSourceSHA256", "ownedDeviceReceiptSHA256", "ownedGUIReceiptSHA256",
                    "windowBindingReceiptSHA256", "fourAnchorProofSHA256", "streamReadyReceiptSHA256",
                    "firstCompleteFrameSHA256"] { _ = try sha(proof[key]) }
        for key in ["captureStarted", "firstCompleteFramePresent", "guiLiveRegistered",
                    "fourAnchorsDecoded", "geometryFrozen"] { try boolean(proof[key], true) }
        for key in ["captureErrors", "ownershipErrors"] {
            guard let errors = proof[key] as? [Any], errors.isEmpty else {
                throw P1CapabilityError("capture/ownership errors prohibit baseline release")
            }
        }
        try boolean(proof["admissionEligible"], false)
        let proofData = try capabilityJSON(proof)
        try require(try sha(row["captureReadyProofSHA256"]) == hash(proofData), "capture-ready proof hash mismatch")
        return (row, proofData)
    }

    @MainActor static func beforeBaseline(test: XCTestCase, app: XCUIApplication, scenario: String,
                                          session: String, methodStarted: Double,
                                          copy: XCUIElement, marker: XCUIElement,
                                          baselineReady: XCUIElement) -> Bool {
        var files: P1CapabilityFiles?, requestHash: String?, acknowledgementHash: String?
        var phase = "initializing"
        let entered = ProcessInfo.processInfo.systemUptime
        let deadline = min(entered + waitSeconds, methodStarted + methodSeconds)
        func inBudget() throws {
            let now = try capabilityNow()
            try require(entered.isFinite && methodStarted.isFinite && methodStarted > 0 &&
                        entered >= methodStarted && now >= entered && now < deadline,
                        "pre-baseline observer deadline exceeded; original tap not released")
        }
        func attachment(_ value: [String: Any], name: String) throws {
            let item = XCTAttachment(data: try capabilityJSON(value), uniformTypeIdentifier: "public.json")
            item.name = name; item.lifetime = .keepAlways; test.add(item)
        }
        do {
            try inBudget()
            try require(matches(session, "^[0-9a-f]{32}$") &&
                        ["timeout", "replacement", "dismissal"].contains(scenario), "unsupported observer session/scenario")
            guard let runnerBundle = Bundle.main.bundleIdentifier,
                  matches(runnerBundle, "^[A-Za-z0-9.-]{1,256}$") else {
                throw P1CapabilityError("runner bundle identity unavailable")
            }
            guard let simulatorUDID = ProcessInfo.processInfo.environment["SIMULATOR_UDID"],
                  matches(simulatorUDID, "^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$") else {
                throw P1CapabilityError("actual runner SIMULATOR_UDID required")
            }
            let channel = try P1CapabilityFiles(session: session); files = channel
            phase = "sampling-geometry"
            let before = try capabilityNow()
            let geometry = try snapshot(app, copy: copy, marker: marker, baselineReady: baselineReady)
            let after = try capabilityNow()
            let request: [String: Any] = ["schema": "p1-direct-baseline-geometry-v1", "session": session,
                "scenario": scenario, "runnerBundleIdentifier": runnerBundle, "simulatorUDID": simulatorUDID,
                "runnerPID": ProcessInfo.processInfo.processIdentifier, "geometry": geometry,
                "sampleBeforeUptime": before, "sampleAfterUptime": after,
                "observerEnteredUptime": entered, "methodStartedUptime": methodStarted,
                "deadlineUptime": deadline, "waitLimitSeconds": waitSeconds,
                "methodLimitSeconds": methodSeconds, "clock": "runner-ProcessInfo.systemUptime",
                "clockEquivalenceAssumed": false, "admissionEligible": false]
            let requestData = try capabilityJSON(request), digest = hash(requestData)
            try require(requestData.count <= 8192, "geometry request exceeds schema cap")
            requestHash = digest
            try channel.immutable("geometry.json", requestData)
            try inBudget()
            // Publication is atomic and occurs only after immutable geometry
            // bytes and their directory have been fsynced by the reused helper.
            try channel.publish("ready.json", capabilityJSON([
                "schema": "p1-direct-baseline-ready-v1", "session": session,
                "geometryFile": "geometry.json", "geometryRequestSHA256": digest,
                "acknowledgementFile": "request.json", "admissionEligible": false]))
            phase = "waiting-for-owned-capture-ready"
            while true {
                try inBudget()
                if let data = try channel.readRequest() {
                    acknowledgementHash = hash(data)
                    // Even a malformed acknowledgement is retained unchanged.
                    try channel.immutable("acknowledgement-received.json", data)
                    let (acknowledgement, proofData) = try validateAcknowledgement(data, session: session, requestHash: digest, simulatorUDID: simulatorUDID)
                    try inBudget()
                    try channel.immutable("capture-ready-proof.json", proofData)
                    phase = "rechecking-geometry"
                    let recheckBefore = try capabilityNow()
                    let latest = try snapshot(app, copy: copy, marker: marker, baselineReady: baselineReady)
                    let recheckAfter = try capabilityNow()
                    try require(try capabilityJSON(latest) == capabilityJSON(geometry),
                                "geometry or control identity changed while waiting for capture")
                    try inBudget()
                    let receipt: [String: Any] = ["schema": "p1-direct-baseline-observer-receipt-v1",
                        "session": session, "scenario": scenario, "result": "acknowledgement-validated",
                        "geometryRequestSHA256": digest, "acknowledgementSHA256": hash(data),
                        "captureReadyProofSHA256": acknowledgement["captureReadyProofSHA256"]!,
                        "observerEnteredUptime": entered, "deadlineUptime": deadline,
                        "recheckBeforeUptime": recheckBefore, "recheckAfterUptime": recheckAfter,
                        "validatedUptime": try capabilityNow(), "clock": "runner-ProcessInfo.systemUptime",
                        "clockEquivalenceAssumed": false, "nativeOwnershipVerifiedByRunner": false,
                        "baselineTapObserved": false, "admissionEligible": false]
                    phase = "persisting-validation-receipt"
                    try channel.immutable("observer-receipt.json", capabilityJSON(receipt))
                    try attachment(receipt, name: "video-\(scenario)-direct-baseline-observer")
                    // Durability and attachment costs are included. A durable
                    // validation receipt is not evidence that the tap occurred.
                    try inBudget()
                    return true
                }
                let remaining = deadline - (try capabilityNow())
                if remaining > 0 { Thread.sleep(forTimeInterval: min(0.05, remaining)) }
            }
        } catch {
            var failure: [String: Any] = ["schema": "p1-direct-baseline-observer-error-v1",
                "session": session, "scenario": scenario, "phase": phase,
                "error": String(describing: error), "observerEnteredUptime": entered,
                "failedUptime": ProcessInfo.processInfo.systemUptime,
                "baselineTapReleased": false, "admissionEligible": false]
            if let digest = requestHash { failure["geometryRequestSHA256"] = digest }
            if let digest = acknowledgementHash { failure["acknowledgementSHA256"] = digest }
            if let fileError = error as? P1RequestReadError { failure["requestFile"] = fileError.receipt }
            if let channel = files {
                do { try channel.immutable("observer-error.json", capabilityJSON(failure)) }
                catch { failure["errorReceiptPersistenceFailure"] = String(describing: error) }
            } else { failure["errorReceiptPersistenceFailure"] = "fresh runner directory unavailable" }
            do { try attachment(failure, name: "video-\(scenario)-direct-baseline-error") }
            catch { XCTFail("observer failure attachment could not be encoded: \(error)") }
            XCTFail("pre-baseline direct capture observer failed: \(failure)")
            return false
        }
    }
}
