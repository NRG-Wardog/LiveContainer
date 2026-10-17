import XCTest
import Foundation
import CoreFoundation
import CryptoKit
import Darwin

// Calibration-only transport. No production state, action, timer, or private
// XCTest API is used. A successful test is NOT evidence of timing feasibility.
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
    private func checkRegular(_ descriptor: Int32, maximum: Int) throws -> Int {
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_nlink == 1, info.st_size > 0, info.st_size <= maximum else {
            throw P1CapabilityError("linked, nonregular, empty, or oversized channel file")
        }
        return Int(info.st_size)
    }
    func readRequest() throws -> Data? {
        let input = openat(fd, "request.json", O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard input >= 0 else {
            if errno == ENOENT { return nil }
            throw P1CapabilityError("cannot open request safely")
        }
        defer { close(input) }
        let count = try checkRegular(input, maximum: 8192)
        var bytes = Data(count: count)
        try bytes.withUnsafeMutableBytes { buffer in
            var offset = 0
            while offset < count {
                let result = Darwin.read(input, buffer.baseAddress!.advanced(by: offset), count - offset)
                if result < 0 && errno == EINTR { continue }
                guard result > 0 else { throw P1CapabilityError("short request read") }
                offset += result
            }
        }
        var extra: UInt8 = 0
        guard Darwin.read(input, &extra, 1) == 0,
              try checkRegular(input, maximum: 8192) == count else {
            throw P1CapabilityError("request changed during read")
        }
        return bytes
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

private struct P1CapabilityCommand: Sendable {
    let id: Int
    let kind: String
    let phase: String
    let ordinal: Int
    var name: String {
        if kind == "baseline" { return "capture-baseline" }
        if kind == "after" { return "capture-after" }
        return "capture-\(phase)-\(ordinal)"
    }
}

private struct P1CapabilityCapture: @unchecked Sendable {
    let command: P1CapabilityCommand
    let png: Data
    var receipt: [String: Any]
}

private struct P1CapabilityStatus: Sendable {
    let complete: Bool
    let failure: String?
}

private final class P1CapabilityChannel: @unchecked Sendable {
    private let files: P1CapabilityFiles
    private let session: String
    private let bundleIdentifier: String
    private let queue = DispatchQueue(label: "p1.capability.runner", qos: .userInitiated)
    private var timer: DispatchSourceTimer?
    private var previousID = 0
    private var previousBytes: Data?
    private var pending = false
    private var completed = false
    private var failure: String?
    private let capture: @MainActor @Sendable (P1CapabilityCommand) throws -> P1CapabilityCapture

    init(session: String, capture: @escaping @MainActor @Sendable (P1CapabilityCommand) throws -> P1CapabilityCapture) throws {
        guard let identifier = Bundle.main.bundleIdentifier, !identifier.isEmpty, identifier.count <= 256 else {
            throw P1CapabilityError("runner Bundle.main.bundleIdentifier unavailable")
        }
        self.session = session; bundleIdentifier = identifier; self.capture = capture
        files = try P1CapabilityFiles(session: session)
        try files.publish("runner.json", capabilityJSON([
            "schema": "p1-capability-runner-v1", "session": session,
            "runnerBundleIdentifier": identifier, "clock": "runner-ProcessInfo.systemUptime",
            "requestSchema": "p1-capability-request-v1", "expectedRequests": 35,
            "clocksPerPhase": 8, "capturesPerPhase": 3, "timeoutSeconds": 180,
            "createdUptime": try capabilityNow(), "admissionEligible": false,
            "clockEquivalenceAssumed": false
        ]))
    }
    private func saveCapture(_ capture: P1CapabilityCapture) throws -> [String: Any] {
        var receipt = capture.receipt
        let pngName = capture.command.name + ".png", receiptName = capture.command.name + ".json"
        receipt["pngSHA256"] = SHA256.hash(data: capture.png).map { String(format: "%02x", $0) }.joined()
        receipt["pngBytes"] = capture.png.count
        receipt["pngWriteBefore"] = try capabilityNow()
        try files.immutable(pngName, capture.png)
        receipt["pngWriteAfter"] = try capabilityNow()
        // Receipt publication is intentionally outside both screenshot and PNG
        // encoding brackets; neither is advertised as screenshot latency.
        try files.immutable(receiptName, capabilityJSON(receipt))
        return ["png": pngName, "receipt": receiptName]
    }
    func saveBaseline(_ capture: P1CapabilityCapture) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do { _ = try self.saveCapture(capture); continuation.resume() }
                catch { self.fail(error); continuation.resume(throwing: error) }
            }
        }
    }
    func start(_ ready: [String: Any]) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                do {
                    var row = ready
                    row["schema"] = "p1-capability-ready-v1"; row["session"] = self.session
                    row["runnerBundleIdentifier"] = self.bundleIdentifier
                    row["png"] = "capture-baseline.png"; row["receipt"] = "capture-baseline.json"
                    row["admissionEligible"] = false
                    try self.files.publish("ready.json", capabilityJSON(row))
                    let timer = DispatchSource.makeTimerSource(queue: self.queue)
                    timer.schedule(deadline: .now(), repeating: .milliseconds(2), leeway: .milliseconds(1))
                    timer.setEventHandler { [weak self] in self?.poll() }
                    self.timer = timer; timer.resume(); continuation.resume()
                } catch { self.fail(error); continuation.resume(throwing: error) }
            }
        }
    }
    func status() async -> P1CapabilityStatus {
        await withCheckedContinuation { continuation in
            queue.async { continuation.resume(returning: P1CapabilityStatus(complete: self.completed, failure: self.failure)) }
        }
    }
    func stopWithError(_ text: String) async {
        await withCheckedContinuation { continuation in
            queue.async { self.fail(P1CapabilityError(text)); continuation.resume() }
        }
    }
    private func fail(_ error: Error) {
        guard failure == nil else { return }
        failure = String(describing: error); timer?.cancel(); timer = nil
        if let data = try? capabilityJSON(["schema": "p1-capability-error-v1", "session": session,
            "previousID": previousID, "error": failure!, "admissionEligible": false]) {
            try? files.immutable("error.json", data)
        }
    }
    private func parse(_ data: Data) throws -> ([String: Any], P1CapabilityCommand) {
        guard let row = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              try capabilityJSON(row) == data,
              row["schema"] as? String == "p1-capability-request-v1",
              row["session"] as? String == session,
              let number = row["id"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue == Double(number.intValue), number.intValue == previousID + 1,
              (1...35).contains(number.intValue), let kind = row["kind"] as? String else {
            throw P1CapabilityError("noncanonical, stale, wrong-session, or nonsequential request")
        }
        let id = number.intValue
        var keys: Set<String> = ["schema", "session", "id", "kind"]
        var phase = "after", ordinal = 0
        if id <= 33 {
            phase = ["pre", "mid", "post"][(id - 1) / 11]
            let position = (id - 1) % 11
            keys.insert("phase")
            guard row["phase"] as? String == phase else { throw P1CapabilityError("wrong calibration phase") }
            if position < 8 {
                guard kind == "clock" else { throw P1CapabilityError("eight clock probes required before phase captures") }
            } else {
                ordinal = position - 7; keys.insert("ordinal")
                guard kind == "capture", let value = row["ordinal"] as? NSNumber,
                      CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue == Double(ordinal) else {
                    throw P1CapabilityError("three ordered captures required per phase")
                }
            }
        } else if id == 34 {
            guard kind == "after" else { throw P1CapabilityError("independent after screenshot required") }
        } else {
            keys.formUnion(["appStripCompleteSHA256", "hostVerifiedStripComplete"])
            guard kind == "complete", let hash = row["appStripCompleteSHA256"] as? String,
                  hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
                  let verified = row["hostVerifiedStripComplete"] as? NSNumber,
                  CFGetTypeID(verified) == CFBooleanGetTypeID(), verified.boolValue else {
                throw P1CapabilityError("verified app strip-complete SHA256 acknowledgement required")
            }
        }
        guard Set(row.keys) == keys else { throw P1CapabilityError("unexpected or missing request fields") }
        return (row, P1CapabilityCommand(id: id, kind: kind, phase: phase, ordinal: ordinal))
    }
    private func publish(_ command: P1CapabilityCommand, received: Double, extra: [String: Any] = [:]) throws {
        var response: [String: Any] = ["schema": "p1-capability-response-v1", "session": session,
            "runnerBundleIdentifier": bundleIdentifier, "id": command.id, "kind": command.kind,
            "runnerReceive": received, "runnerSend": try capabilityNow(),
            "clock": "runner-ProcessInfo.systemUptime", "clockEquivalenceAssumed": false,
            "admissionEligible": false]
        if command.id <= 33 { response["phase"] = command.phase }
        if command.kind == "capture" { response["ordinal"] = command.ordinal }
        for (key, value) in extra { response[key] = value }
        let data = try capabilityJSON(response)
        // runnerSend is a timestamp before the durable write/publication; the
        // host receive bound includes those costs. It is not a socket send time.
        try files.immutable(String(format: "response-%04d.json", command.id), data)
        try files.publish("response.json", data)
    }
    private func poll() {
        guard !pending, !completed, failure == nil else { return }
        do {
            guard let bytes = try files.readRequest(), bytes != previousBytes else { return }
            let received = try capabilityNow()
            let (row, command) = try parse(bytes)
            // Every request, including the final acknowledgement, is retained.
            try files.immutable(String(format: "request-%04d.json", command.id), bytes)
            previousBytes = bytes; previousID = command.id
            if command.kind == "clock" {
                try publish(command, received: received)
            } else if command.kind == "complete" {
                var completion = row
                completion["schema"] = "p1-capability-complete-v1"
                completion["runnerBundleIdentifier"] = bundleIdentifier
                completion["runnerAckUptime"] = try capabilityNow()
                completion["admissionEligible"] = false
                completion["hashVerificationBy"] = "host; runner does not read app container"
                try files.publish("completion.json", capabilityJSON(completion))
                try publish(command, received: received, extra: ["completion": "completion.json"])
                completed = true; timer?.cancel(); timer = nil
            } else {
                pending = true
                Task { @MainActor in
                    do {
                        let capture = try self.capture(command)
                        self.queue.async {
                            guard self.failure == nil else { return }
                            do {
                                let extra = try self.saveCapture(capture)
                                try self.publish(command, received: received, extra: extra)
                                self.pending = false
                            } catch { self.fail(error) }
                        }
                    } catch { self.queue.async { self.fail(error) } }
                }
            }
        } catch { fail(error) }
    }
}

final class P1ScreenshotCapabilityUITests: XCTestCase {
    @MainActor private func rectangle(_ frame: CGRect) throws -> [Double] {
        let value = [frame.minX, frame.minY, frame.width, frame.height].map { Double($0) }
        guard value.allSatisfy({ $0.isFinite }), frame.width > 0, frame.height > 0 else {
            throw P1CapabilityError("invalid accessibility geometry")
        }
        return value
    }
    @MainActor private func copyIdentity(_ app: XCUIApplication) throws -> [String: Any] {
        let query = app.buttons.matching(identifier: "signin.prompt.copy-details")
        guard query.count == 1 else { throw P1CapabilityError("Copy Details control is missing or ambiguous") }
        let copy = query.element
        guard copy.exists, copy.isEnabled, copy.isHittable,
              copy.identifier == "signin.prompt.copy-details", copy.label == "Copy Details" else {
            throw P1CapabilityError("Copy Details is not in its steady state")
        }
        let value: Any = copy.value ?? NSNull()
        guard value is NSNull || value is String || value is NSNumber else {
            throw P1CapabilityError("unsupported accessibility value type")
        }
        return ["identifier": copy.identifier, "label": copy.label, "value": value,
            "exists": copy.exists, "enabled": copy.isEnabled, "hittable": copy.isHittable,
            "selected": copy.isSelected, "elementType": copy.elementType.rawValue, "frame": try rectangle(copy.frame)]
    }
    @MainActor private func capture(_ app: XCUIApplication, session: String,
                                   command: P1CapabilityCommand) throws -> P1CapabilityCapture {
        let copyBefore = try copyIdentity(app)
        let marker = app.otherElements["p1-video-marker"]
        guard marker.exists else { throw P1CapabilityError("calibration marker missing") }
        let markerBefore = try rectangle(marker.frame)
        let windowBefore = try rectangle(app.windows.firstMatch.frame)
        // Only the public screenshot acquisition is inside this bracket.
        let acquisitionBefore = try capabilityNow()
        let screenshot = app.screenshot()
        let acquisitionAfter = try capabilityNow()
        let encodingBefore = try capabilityNow()
        let png = screenshot.pngRepresentation
        let encodingAfter = try capabilityNow()
        guard !png.isEmpty && png.count <= 32 * 1024 * 1024 else { throw P1CapabilityError("invalid screenshot size") }
        let copyAfter = try copyIdentity(app)
        let markerAfter = try rectangle(marker.frame)
        let windowAfter = try rectangle(app.windows.firstMatch.frame)
        let attachmentBefore = try capabilityNow()
        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = command.name; attachment.lifetime = .keepAlways; add(attachment)
        let attachmentAfter = try capabilityNow()
        let receipt: [String: Any] = ["schema": "p1-capability-capture-v1", "session": session,
            "runnerBundleIdentifier": Bundle.main.bundleIdentifier!, "requestId": command.id,
            "name": command.name, "phase": command.phase, "ordinal": command.ordinal,
            "clock": "runner-ProcessInfo.systemUptime", "clockEquivalenceAssumed": false,
            "acquisitionBefore": acquisitionBefore, "acquisitionAfter": acquisitionAfter,
            "encodingBefore": encodingBefore, "encodingAfter": encodingAfter,
            "attachmentBefore": attachmentBefore, "attachmentAfter": attachmentAfter,
            "copyBefore": copyBefore, "copyAfter": copyAfter,
            "markerFrameBefore": markerBefore, "markerFrameAfter": markerAfter,
            "windowFrameBefore": windowBefore, "windowFrameAfter": windowAfter,
            "admissionEligible": false, "timingFeasibilityEstablished": false]
        return P1CapabilityCapture(command: command, png: png, receipt: receipt)
    }
    @MainActor func testScreenshotCalibrationCapability() async throws {
        continueAfterFailure = false
        guard let session = ProcessInfo.processInfo.environment["P1_CAPABILITY_SESSION"],
              session.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil else {
            throw P1CapabilityError("fresh P1_CAPABILITY_SESSION required")
        }
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--scenario", "capability", "--session", session]
        app.launch()
        guard app.buttons["signin.prompt.copy-details"].waitForExistence(timeout: 15) else {
            throw P1CapabilityError("actual-source Copy Details control did not appear")
        }
        let channel = try P1CapabilityChannel(session: session) { [self] command in
            try capture(app, session: session, command: command)
        }
        do {
            let before = try copyIdentity(app)
            let baseline = try capture(app, session: session,
                command: P1CapabilityCommand(id: 0, kind: "baseline", phase: "baseline", ordinal: 0))
            try await channel.saveBaseline(baseline)
            let ready = app.buttons["p1-video-baseline-ready"]
            guard ready.exists, ready.isEnabled, ready.isHittable, ready.label == "Baseline ready" else {
                throw P1CapabilityError("separate Baseline ready fixture control unavailable")
            }
            let baselineTapBefore = try capabilityNow()
            ready.tap()
            let baselineTapAfter = try capabilityNow()
            let after = try copyIdentity(app)
            try await channel.start(["baselineTapBefore": baselineTapBefore, "baselineTapAfter": baselineTapAfter,
                "baselineDriver": "normal-XCTest-fixture-ready-tap", "copyBefore": before, "copyAfter": after])
            let deadline = try capabilityNow() + 180
            while try capabilityNow() < deadline {
                let state = await channel.status()
                if let failure = state.failure { throw P1CapabilityError(failure) }
                if state.complete { return }
                // Async polling releases the main actor for screenshot requests.
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            throw P1CapabilityError("host completion acknowledgement not received within 180 seconds")
        } catch {
            await channel.stopWithError(String(describing: error))
            throw error
        }
    }
}
