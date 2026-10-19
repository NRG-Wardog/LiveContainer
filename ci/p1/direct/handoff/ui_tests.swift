import XCTest
import Foundation
import CoreFoundation
import CryptoKit
import Darwin

// P1_DIRECT_REUSED_PRIMITIVES_BEGIN
private struct P1CapabilityError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

private func capabilityNow() throws -> Double {
    let value = ProcessInfo.processInfo.systemUptime
    guard value.isFinite && value > 0 else { throw P1CapabilityError("invalid runner clock") }
    return value
}

private func capabilityJSON(_ value: [String: Any]) throws -> Data {
    guard JSONSerialization.isValidJSONObject(value) else { throw P1CapabilityError("invalid JSON") }
    return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
}

// P1_REQUEST_READER_BEGIN
// Extracted verbatim for the macOS filesystem regression. No UI or clock code.
private struct P1RequestReadError: Error, CustomStringConvertible {
    let receipt: [String: Any]
    var description: String { "request file failure: " + (receipt["reason"] as? String ?? "unknown") }
}
private enum P1RequestReader {
#if P1_REQUEST_READER_REGRESSION
    // Absent from the XCTest build. Enables deterministic atomic-replace races.
    static var checkpoint: ((String, Int32) throws -> Void)?
#endif
    static func inspect(_ input: Int32, stage: String, receipt: inout [String: Any]) throws -> Int? {
        var info = stat()
        let result = fstat(input, &info), savedErrno = errno
        var row: [String: Any] = ["stage": stage, "result": result,
            "errno": result == 0 ? 0 : savedErrno, "descriptor": input]
        if result == 0 {
            row["mode"] = UInt32(info.st_mode); row["type"] = UInt32(info.st_mode & S_IFMT)
            row["links"] = UInt64(info.st_nlink); row["size"] = Int64(info.st_size)
            row["device"] = Int64(info.st_dev); row["inode"] = UInt64(info.st_ino)
        }
        receipt[stage] = row
        func reject(_ reason: String) throws -> Int? {
            receipt["reason"] = reason; throw P1RequestReadError(receipt: receipt)
        }
        guard result == 0 else { return try reject("fstat failed") }
        guard (info.st_mode & S_IFMT) == S_IFREG else { return try reject("nonregular request") }
        guard info.st_size > 0 && info.st_size <= 8192 else { return try reject("invalid request size") }
        // Atomic replacement can unlink an opened old inode. Discard its bytes;
        // only the next normal poll may open and validate the current pathname.
        if info.st_nlink == 0 { receipt["reason"] = "unlinked prior request discarded"; return nil }
        guard info.st_nlink == 1 else { return try reject("multiply linked request") }
        return Int(info.st_size)
    }
    static func read(directory: Int32) throws -> (data: Data?, discarded: [String: Any]?) {
        var receipt: [String: Any] = ["schema": "p1-request-file-observation-v1", "admissionEligible": false]
        let input = openat(directory, "request.json", O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        let openErrno = errno
        guard input >= 0 else {
            if openErrno == ENOENT { return (nil, nil) }
            receipt["reason"] = "safe open failed"; receipt["operation"] = "openat"; receipt["errno"] = openErrno
            throw P1RequestReadError(receipt: receipt)
        }
        var bytes: Data?, discarded = false, failure: P1RequestReadError?
        do {
#if P1_REQUEST_READER_REGRESSION
            try checkpoint?("before", input)
#endif
            if let count = try inspect(input, stage: "before", receipt: &receipt) {
                var value = Data(count: count)
                try value.withUnsafeMutableBytes { buffer in
                    var offset = 0
                    while offset < count {
                        let result = Darwin.read(input, buffer.baseAddress!.advanced(by: offset), count - offset)
                        if result < 0 && errno == EINTR { continue }
                        guard result > 0 else {
                            receipt["reason"] = "short or failed request read"; receipt["readResult"] = result
                            receipt["errno"] = result < 0 ? errno : 0; throw P1RequestReadError(receipt: receipt)
                        }
                        offset += result
                    }
                }
                var extra: UInt8 = 0
                var extraResult: Int
                repeat { extraResult = Darwin.read(input, &extra, 1) } while extraResult < 0 && errno == EINTR
                receipt["extraReadResult"] = extraResult; receipt["extraReadErrno"] = extraResult < 0 ? errno : 0
                guard extraResult >= 0 else {
                    receipt["reason"] = "extra request read failed"; throw P1RequestReadError(receipt: receipt)
                }
#if P1_REQUEST_READER_REGRESSION
                try checkpoint?("after", input)
#endif
                if let finalCount = try inspect(input, stage: "after", receipt: &receipt) {
                    guard extraResult == 0 && finalCount == count else {
                        receipt["reason"] = "request changed during read"; throw P1RequestReadError(receipt: receipt)
                    }
                    bytes = value
                } else { discarded = true }
            } else { discarded = true }
        } catch let error as P1RequestReadError { failure = error }
          catch { receipt["reason"] = "regression checkpoint failed"; failure = P1RequestReadError(receipt: receipt) }
        let closeResult = close(input), closeErrno = errno
        receipt = failure?.receipt ?? receipt
        receipt["close"] = ["result": closeResult, "errno": closeResult == 0 ? 0 : closeErrno]
        if closeResult != 0 {
            if failure != nil { receipt["primaryReason"] = receipt["reason"] }
            receipt["reason"] = "request descriptor close failed"
            throw P1RequestReadError(receipt: receipt)
        }
        if failure != nil { throw P1RequestReadError(receipt: receipt) }
        return (discarded ? nil : bytes, discarded ? receipt : nil)
    }
}
// P1_REQUEST_READER_END

// Keep the fresh directory open and address every file relative to that fd.
// O_NOFOLLOW, single-link regular files, exclusive immutable journals, and
// atomic publication prevent a stale/symlinked channel from being accepted.
private final class P1CapabilityFiles: @unchecked Sendable {
    let root: URL
    private let fd: Int32
    init(session: String) throws {
        guard session.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil else {
            throw P1CapabilityError("P1_CAPABILITY_SESSION must be 32 lowercase hex characters")
        }
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let documentsFD = open(documents.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard documentsFD >= 0 else { throw P1CapabilityError("cannot open real Documents directory") }
        defer { close(documentsFD) }
        if mkdirat(documentsFD, "p1-capability", 0o700) != 0 && errno != EEXIST {
            throw P1CapabilityError("cannot create channel parent")
        }
        let parentFD = openat(documentsFD, "p1-capability", O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard parentFD >= 0 else { throw P1CapabilityError("linked or invalid channel parent") }
        defer { close(parentFD) }
        guard mkdirat(parentFD, session, 0o700) == 0 else {
            throw P1CapabilityError("fresh session directory required")
        }
        let opened = openat(parentFD, session, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard opened >= 0 else { throw P1CapabilityError("cannot open fresh channel") }
        fd = opened
        root = documents.appendingPathComponent("p1-capability", isDirectory: true)
            .appendingPathComponent(session, isDirectory: true)
    }
    deinit { close(fd) }
    private func safeName(_ name: String) throws {
        guard name.range(of: "^[a-zA-Z0-9][a-zA-Z0-9.-]{0,100}$", options: .regularExpression) != nil,
              !name.contains("..") else { throw P1CapabilityError("unsafe channel filename") }
    }
    private var discardedRequests = 0
    func readRequest() throws -> Data? {
        let observation = try P1RequestReader.read(directory: fd)
        if var row = observation.discarded {
            discardedRequests += 1
            guard discardedRequests <= 64 else { throw P1CapabilityError("request replacement discard limit exceeded") }
            row["ordinal"] = discardedRequests
            try immutable(String(format: "reader-discard-%03d.json", discardedRequests), capabilityJSON(row))
        }
        return observation.data
    }
    // fsync must succeed BEFORE a response can be published. Fail closed if
    // this simulator/filesystem cannot provide the requested durability.
    func immutable(_ name: String, _ data: Data) throws {
        try safeName(name)
        guard !data.isEmpty && data.count <= 32 * 1024 * 1024 else {
            throw P1CapabilityError("invalid output size")
        }
        let output = openat(fd, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard output >= 0 else { throw P1CapabilityError("immutable output already exists or cannot be opened: \(name)") }
        defer { close(output) }
        try data.withUnsafeBytes { buffer in
            var offset = 0
            while offset < data.count {
                let result = Darwin.write(output, buffer.baseAddress!.advanced(by: offset), data.count - offset)
                if result < 0 && errno == EINTR { continue }
                guard result > 0 else { throw P1CapabilityError("output write failed: \(name)") }
                offset += result
            }
        }
        guard fsync(output) == 0, fsync(fd) == 0 else { throw P1CapabilityError("output durability failed: \(name)") }
    }
    func publish(_ name: String, _ data: Data) throws {
        try safeName(name)
        var existing = stat()
        if fstatat(fd, name, &existing, AT_SYMLINK_NOFOLLOW) == 0 {
            guard (existing.st_mode & S_IFMT) == S_IFREG, existing.st_nlink == 1 else {
                throw P1CapabilityError("linked or nonregular publication target")
            }
        } else if errno != ENOENT { throw P1CapabilityError("cannot inspect publication target") }
        let temporary = "publish-" + UUID().uuidString.lowercased() + ".tmp"
        try immutable(temporary, data)
        guard renameat(fd, temporary, fd, name) == 0, fsync(fd) == 0 else {
            throw P1CapabilityError("atomic publication failed")
        }
    }
}

// P1_DIRECT_REUSED_PRIMITIVES_END

// P1_DIRECT_OBSERVER_BEGIN
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
            try require(frame.width == 2 && frame.height == 2 && windowFrame.contains(frame),
                        "whole actual 2-by-2-point feature AX frame required inside app window")
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
// P1_DIRECT_OBSERVER_END

final class P0SignInUITests: XCTestCase {
    private func attach(_ value: [String: Any], _ name: String) {
        let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .prettyPrinted])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    private func rect(_ frame: CGRect) -> [Double] { [frame.minX,frame.minY,frame.width,frame.height].map { Double($0) } }
    @MainActor private func screenshot(_ app: XCUIApplication, _ name: String) {
        let before = ProcessInfo.processInfo.systemUptime
        let item = XCTAttachment(screenshot: app.screenshot()); item.name = name; item.lifetime = .keepAlways; add(item)
        attach(["name": name, "beforeUptime": before, "afterUptime": ProcessInfo.processInfo.systemUptime,
                "clock": "XCTest-process-systemUptime; not assumed equal to app clock"], name + "-clock")
    }
    @MainActor private func phase(_ app: XCUIApplication, _ value: String, _ timeout: Double = 90) -> Bool {
        let predicate = NSPredicate(format: "label == %@", value)
        return XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: predicate,
            object: app.staticTexts["p1-video-phase"])], timeout: timeout) == .completed
    }
    @MainActor private func pixel(_ scenario: String) {
        let directMethodStarted = ProcessInfo.processInfo.systemUptime
        guard let directSession = P1DirectHandoff.sessionOrFail() else { return }
        continueAfterFailure = false; XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication(); app.launchArguments = ["--scenario", scenario, "--session", directSession]; app.launch()
        let copy = app.buttons["signin.prompt.copy-details"]
        XCTAssertTrue(copy.waitForExistence(timeout: 10)); XCTAssertTrue(copy.isHittable)
        XCTAssertEqual(copy.label, "Copy Details")
        let marker = app.otherElements["p1-video-marker"]
        XCTAssertTrue(marker.exists)
        let copyFrame = copy.frame; let markerFrame = marker.frame; let windowFrame = app.windows.firstMatch.frame
        let target = copy.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        screenshot(app, "video-\(scenario)-before")
        attach(["schema": "p1-video-controls-v1", "scenario": scenario, "copyFrame": rect(copyFrame),
            "markerFrame": rect(markerFrame), "windowFrame": rect(windowFrame),
            "copyLabel": copy.label, "copyHittable": copy.isHittable], "video-\(scenario)-controls")
        let baselineReady = app.buttons["p1-video-baseline-ready"]
        XCTAssertTrue(baselineReady.exists && baselineReady.isHittable)
        guard P1DirectHandoff.beforeBaseline(test: self, app: app, scenario: scenario,
            session: directSession, methodStarted: directMethodStarted,
            copy: copy, marker: marker, baselineReady: baselineReady) else { return }
        let baselineBefore = ProcessInfo.processInfo.systemUptime; baselineReady.tap()
        let baselineAfter = ProcessInfo.processInfo.systemUptime
        XCTAssertTrue(phase(app, "ready"), "External pre-calibration did not finish")
        let firstBefore = ProcessInfo.processInfo.systemUptime
        copy.tap()
        let firstAfter = ProcessInfo.processInfo.systemUptime
        var input: [String: Any] = ["schema": "p1-video-input-v1", "scenario": scenario,
            "firstBefore": firstBefore, "firstAfter": firstAfter, "firstDriver": "normal-XCTest-tap",
            "baselineBefore": baselineBefore, "baselineAfter": baselineAfter,
            "baselineDriver": "normal-XCTest-fixture-ready-tap"]
        if scenario != "timeout" {
            // Public normal physical input; no assumption about quiescence or
            // delivery time. Actual app events decide whether overlap occurred.
            input["secondDelayRequested"] = 0.90
            input["secondDelayBefore"] = ProcessInfo.processInfo.systemUptime
            Thread.sleep(forTimeInterval: 0.90)
            input["secondDelayAfter"] = ProcessInfo.processInfo.systemUptime
            input["secondBefore"] = ProcessInfo.processInfo.systemUptime
            target.tap()
            input["secondAfter"] = ProcessInfo.processInfo.systemUptime
            input["secondDriver"] = "experimental-XCTest-coordinate-tap"
        }
        if scenario != "timeout" {
            XCTAssertTrue(phase(app, "third-ready"), "Mid calibration did not finish")
            XCTAssertTrue(copy.exists && copy.isHittable)
            XCTAssertEqual(copy.label, "Copy Details")
            input["thirdHittable"] = copy.isHittable
            input["thirdLabelBefore"] = copy.label
            input["thirdBefore"] = ProcessInfo.processInfo.systemUptime
            copy.tap()
            input["thirdAfter"] = ProcessInfo.processInfo.systemUptime
            input["thirdDriver"] = "normal-XCTest-third-tap"
        }
        attach(input, "video-\(scenario)-input")
        XCTAssertTrue(phase(app, "finished"), "External post calibration did not finish")
        screenshot(app, "video-\(scenario)-after")
        XCTAssertTrue(copy.exists && copy.isHittable); XCTAssertEqual(copy.label, "Copy Details")
        attach(["schema": "p1-video-completion-v1", "scenario": scenario,
            "completed": true, "copyAfterLabel": copy.label, "copyAfterHittable": copy.isHittable,
            "admissionEligible": false], "video-\(scenario)-complete")
    }
    @MainActor func testProbeTimeoutPixels() { pixel("timeout") }
    @MainActor func testProbeReplacementPixels() { pixel("replacement") }
    @MainActor func testProbeDismissalPixels() { pixel("dismissal") }
    // __P1_RECOVERY_TEST_METHODS__
}
