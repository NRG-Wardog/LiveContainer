// Diagnostic-only: one explicitly owned Simulator window, never a display.
import AppKit
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import CryptoKit
import ImageIO
import UniformTypeIdentifiers
import Darwin

struct Failure: Error { let code: String; init(_ code: String) { self.code = code } }
func require(_ value: Bool, _ code: String) throws { if !value { throw Failure(code) } }
func exactUnsigned(_ number: NSNumber) -> UInt64? {
    guard CFGetTypeID(number) != CFBooleanGetTypeID(),
          number.stringValue.range(of: "^[0-9]+$", options: .regularExpression) != nil else { return nil }
    return UInt64(number.stringValue)
}
func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
func rect(_ value: CGRect) -> [Double] { [value.origin.x, value.origin.y, value.width, value.height].map(Double.init) }
func valid(_ value: CGRect) -> Bool { rect(value).allSatisfy { $0.isFinite } && value.width > 0 && value.height > 0 }
func write(_ value: [String: Any], _ path: URL) throws { try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(to: path, options: .atomic) }

// A hard process deadline also covers framework callbacks that ignore cancellation.
// The parent retains exact process ownership and independently bounds this helper.
final class StageDeadline {
    private let lock = NSLock()
    private var generation = 0
    let directory: URL
    init(_ directory: URL) { self.directory = directory }
    func arm(_ seconds: Double, _ phase: String) {
        lock.lock(); generation += 1; let current = generation; lock.unlock()
        DispatchQueue.global().asyncAfter(deadline: .now() + seconds) { [self] in
            lock.lock(); let expired = generation == current; lock.unlock()
            if expired {
                try? write(["schema": "p1-window-stage-timeout-v1", "phase": phase, "limitSeconds": seconds, "admissionEligible": false], directory.appendingPathComponent("stage-timeout.json"))
                exit(124)
            }
        }
    }
    func cancel() { lock.lock(); generation += 1; lock.unlock() }
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

// Local adapter draft. Requires the reviewed owned-window lifecycle and Failure,
// require, digest, rect and valid helpers. This file grants no admission itself.
import AppKit
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import CryptoKit

struct DirectROI {
    let role: String
    let x: Int, y: Int, width: Int, height: Int
    var byteCount: Int { width * height * 4 }
}

struct DirectROIPlan {
    let session: String
    let sourceWidth: Int, sourceHeight: Int, sourceStride: Int
    let regions: [DirectROI]
    let geometrySHA256: String
    var byteCount: Int { regions.reduce(0) { $0 + $1.byteCount } }
    func validate() throws {
        try require(session.utf8.count == 32 && session.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) },
                    "invalid-roi-session")
        try require(geometrySHA256.utf8.count == 64 && geometrySHA256.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) },
                    "invalid-geometry-hash")
        try require(sourceWidth > 0 && sourceWidth <= 2048 && sourceHeight > 0 && sourceHeight <= 2048 &&
                    sourceStride >= sourceWidth * 4 && sourceStride <= sourceWidth * 4 + 256 && sourceStride % 4 == 0, "invalid-roi-source")
        try require(regions.map { $0.role } == ["control", "marker", "anchor-1", "anchor-2", "anchor-3", "anchor-4"],
                    "invalid-roi-role-order")
        for region in regions {
            // All bounds precede arithmetic. Never clamp a clipped rectangle.
            try require(region.x >= 0 && region.y >= 0 && region.width > 0 && region.height > 0 &&
                        region.x <= sourceWidth && region.y <= sourceHeight &&
                        region.width <= sourceWidth - region.x && region.height <= sourceHeight - region.y,
                        "clipped-roi")
        }
        for (index, first) in regions.enumerated() {
            for second in regions.dropFirst(index + 1) {
                try require(max(first.x, second.x) >= min(first.x + first.width, second.x + second.width) ||
                            max(first.y, second.y) >= min(first.y + first.height, second.y + second.height),
                            "overlapping-rois")
            }
        }
        try require(byteCount <= 1024 * 1024, "roi-byte-limit")
    }
}

// One immutable packed byte sequence per sample. No image conversion, PNG
// encoder, OCR, normalization, resampling or pixel classification runs here.
func directCopyROIs(_ buffer: CVPixelBuffer, plan: DirectROIPlan) throws -> Data {
    try plan.validate()
    try require(CVPixelBufferGetWidth(buffer) == plan.sourceWidth &&
                CVPixelBufferGetHeight(buffer) == plan.sourceHeight &&
                CVPixelBufferGetBytesPerRow(buffer) == plan.sourceStride &&
                CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA,
                "roi-source-replacement")
    try require(CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "roi-lock-failed")
    var data = Data(capacity: plan.byteCount)
    do {
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw Failure("roi-address-missing") }
        for region in plan.regions {
            for row in region.y ..< region.y + region.height {
                let source = base.advanced(by: row * plan.sourceStride + region.x * 4)
                data.append(source.assumingMemoryBound(to: UInt8.self), count: region.width * 4)
            }
        }
    } catch {
        CVPixelBufferUnlockBaseAddress(buffer, .readOnly)
        throw error
    }
    try require(CVPixelBufferUnlockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "roi-unlock-failed")
    try require(data.count == plan.byteCount, "roi-copy-length")
    return data
}

func directROIManifest(_ plan: DirectROIPlan, packed: Data) throws -> [[String: Any]] {
    try plan.validate()
    try require(packed.count == plan.byteCount, "roi-manifest-length")
    var offset = 0
    return plan.regions.map { region in
        let size = region.byteCount
        defer { offset += size }
        return ["role": region.role, "rectangle": [region.x, region.y, region.width, region.height],
                "offset": offset, "bytes": size, "stride": region.width * 4,
                "sha256": digest(packed.subdata(in: offset ..< offset + size))]
    }
}

// A single full-context frame is only registration evidence. The exact same
// immutable single-window filter/configuration must later feed the stream.
// Caller owns a separately bounded stage deadline and revalidates owner/window
// before and after this call. No capture timestamp or duration is inferred.
@MainActor func directRegistrationFrame(filter: SCContentFilter,
                                        configuration: SCStreamConfiguration) async throws -> (Data, [String: Any]) {
    try require(CGPreflightScreenCaptureAccess(), "existing-permission-absent")
    let sample = try await SCScreenshotManager.captureSampleBuffer(contentFilter: filter, configuration: configuration)
    try require(sample.isValid, "registration-sample-invalid")
    guard let buffer = CMSampleBufferGetImageBuffer(sample) else { throw Failure("registration-image-missing") }
    let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
    let stride = CVPixelBufferGetBytesPerRow(buffer)
    try require(width > 0 && width <= 2048 && height > 0 && height <= 2048 &&
                stride >= width * 4 && stride <= width * 4 + 256 && stride % 4 == 0 &&
                CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA,
                "registration-pixel-layout")
    try require(CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "registration-lock-failed")
    let data: Data
    do {
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw Failure("registration-address-missing") }
        data = Data(bytes: base, count: stride * height)
    } catch { CVPixelBufferUnlockBaseAddress(buffer, .readOnly); throw error }
    try require(CVPixelBufferUnlockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "registration-unlock-failed")
    return (data, ["schema": "p1-direct-registration-buffer-v1", "format": "BGRA8",
                   "width": width, "height": height, "stride": stride, "bytes": data.count,
                   "sha256": digest(data), "displayTimeEstablished": false, "admissionEligible": false])
}


// Local native adapter support. Uses the source-bound P1RequestReader unchanged.
// Caller provides fresh parent-owned channel directories; no credential access.
import Foundation
import Darwin
import AppKit

struct DirectOwner {
    let pid: pid_t
    let executable: String
    func valid() -> Bool {
        guard let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated,
              app.bundleIdentifier == "com.apple.iphonesimulator",
              app.executableURL?.resolvingSymlinksInPath().path == executable else { return false }
        return true
    }
}

final class DirectRequestChannel {
    private let descriptor: Int32
    private var seen: Data?
    init(_ root: URL) throws {
        descriptor = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK)
        try require(descriptor >= 0, "direct-channel-open-failed")
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFDIR else {
            close(descriptor); throw Failure("direct-channel-not-directory")
        }
    }
    deinit { close(descriptor) }
    func readOnce() throws -> Data? {
        let observed = try P1RequestReader.read(directory: descriptor)
        try require(observed.discarded == nil, "direct-request-replaced-during-read")
        guard let data = observed.data else {
            try require(seen == nil, "direct-request-removed")
            return nil
        }
        if let previous = seen { try require(data == previous, "direct-request-changed") }
        seen = data
        return data
    }
}

func directObject(_ data: Data, keys: Set<String>) throws -> [String: Any] {
    try require(data.count <= 8192, "direct-request-size")
    guard let row = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw Failure("direct-request-not-object")
    }
    let canonical = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .withoutEscapingSlashes])
    try require(canonical == data && Set(row.keys) == keys, "direct-request-noncanonical-or-schema")
    return row
}

func directInteger(_ value: Any?, maximum: UInt64) throws -> Int {
    guard let number = value as? NSNumber, let integer = exactUnsigned(number), integer <= maximum else {
        throw Failure("direct-request-invalid-integer")
    }
    return Int(integer)
}

func directPlan(_ data: Data, session: String, window: CGWindowID,
                baselineWidth: Int, baselineHeight: Int, baselineStride: Int) throws -> DirectROIPlan {
    let row = try directObject(data, keys: ["schema", "session", "windowID", "geometrySHA256",
                                          "sourceWidth", "sourceHeight", "sourceStride", "regions"])
    try require(row["schema"] as? String == "p1-direct-roi-plan-v1" && row["session"] as? String == session,
                "direct-plan-session-schema")
    try require(try directInteger(row["windowID"], maximum: UInt64(UInt32.max)) == Int(window), "direct-plan-window")
    let width = try directInteger(row["sourceWidth"], maximum: 2048)
    let height = try directInteger(row["sourceHeight"], maximum: 2048)
    let stride = try directInteger(row["sourceStride"], maximum: 16384)
    try require(width == baselineWidth && height == baselineHeight && stride == baselineStride, "direct-plan-baseline-layout")
    guard let geometryHash = row["geometrySHA256"] as? String,
          let regions = row["regions"] as? [[String: Any]], regions.count == 6 else { throw Failure("direct-plan-regions") }
    let parsed: [DirectROI] = try regions.map { value in
        try require(Set(value.keys) == ["role", "x", "y", "width", "height"], "direct-plan-region-fields")
        guard let role = value["role"] as? String else { throw Failure("direct-plan-role") }
        return DirectROI(role: role, x: try directInteger(value["x"], maximum: 2048),
                         y: try directInteger(value["y"], maximum: 2048),
                         width: try directInteger(value["width"], maximum: 2048),
                         height: try directInteger(value["height"], maximum: 2048))
    }
    let plan = DirectROIPlan(session: session, sourceWidth: width, sourceHeight: height,
                             sourceStride: stride, regions: parsed, geometrySHA256: geometryHash)
    try plan.validate(); return plan
}

// Shared absolute limits anchored by the parent before the original XCTest
// command. Stage allowances cannot restart or extend this one-case budget.
final class DirectDeadline {
    private let stage: StageDeadline
    private let directory: URL
    private let observation: UInt64
    private let cleanup: UInt64
    private let numerator: UInt32
    private let denominator: UInt32
    private var cleanupMode = false
    private var ordinal = 0
    private var armedCutoff: UInt64?
    init(_ directory: URL, observation: UInt64, cleanup: UInt64) {
        self.directory = directory; self.stage = StageDeadline(directory)
        self.observation = observation; self.cleanup = cleanup
        var basis = mach_timebase_info_data_t()
        guard mach_timebase_info(&basis) == KERN_SUCCESS && basis.numer > 0 && basis.denom > 0,
              mach_absolute_time() < observation && observation < cleanup else { exit(2) }
        numerator = basis.numer; denominator = basis.denom
        // This separate terminal watchdog is never canceled with a stage.
        let terminal = seconds(until: cleanup)
        DispatchQueue.global().asyncAfter(deadline: .now() + terminal) { [directory] in
            try? write(["schema": "p1-direct-absolute-timeout-v1", "phase": "cleanup-cutoff",
                        "admissionEligible": false], directory.appendingPathComponent("absolute-timeout.json"))
            exit(124)
        }
    }
    private func seconds(until end: UInt64) -> Double {
        let now = mach_absolute_time()
        guard now < end else { return 0 }
        let value = Double(end - now) * Double(numerator) / Double(denominator) / 1_000_000_000
        return max(0, value.nextDown)
    }
    func beginCleanup() { cleanupMode = true }
    func arm(_ maximum: Double, _ phase: String) {
        let cutoff = cleanupMode ? cleanup : observation
        let remaining = seconds(until: cutoff)
        let allowance = min(maximum, remaining)
        guard maximum.isFinite && maximum > 0 && maximum <= 360 && maximum.rounded() == maximum else { exit(2) }
        let product = (UInt64(maximum) * 1_000_000_000).multipliedFullWidth(by: UInt64(denominator))
        let ticks = product.high < UInt64(numerator) ? UInt64(numerator).dividingFullWidth(product).quotient : UInt64.max
        let (candidate, overflow) = mach_absolute_time().addingReportingOverflow(ticks)
        let stageCutoff = min(cutoff, overflow ? UInt64.max : candidate)
        armedCutoff = stageCutoff
        ordinal += 1
        guard maximum.isFinite && maximum > 0 && allowance > 0 && ordinal <= 64 else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": phase,
                        "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
        do {
            try write(["schema": "p1-direct-stage-budget-v1", "phase": phase,
                       "ordinal": ordinal, "maximumSeconds": maximum, "actualAllowanceSeconds": allowance,
                       "absoluteCutoffMach": cutoff, "stageCutoffMach": stageCutoff, "cleanup": cleanupMode, "admissionEligible": false],
                      directory.appendingPathComponent(String(format: "stage-budget-%03d.json", ordinal)))
        } catch { exit(3) }
        // Recompute after receipt I/O so it cannot extend the absolute cutoff.
        stage.arm(min(allowance, seconds(until: stageCutoff)), phase)
    }
    func checkFinal() {
        guard mach_absolute_time() < cleanup else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": "final-result", "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
    }
    func cancel() {
        let limit = armedCutoff ?? (cleanupMode ? cleanup : observation)
        guard mach_absolute_time() < limit else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": "stage-completion", "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
        stage.cancel(); armedCutoff = nil
    }
}


// Resize only the already-owned Simulator window before immutable registration.
// Existing accessibility trust is required; this helper never requests it.
import ApplicationServices

func directAXRect(_ element: AXUIElement) throws -> CGRect {
    var position: CFTypeRef?, size: CFTypeRef?
    try require(AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success &&
                AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success,
                "owned-window-ax-geometry-unavailable")
    guard let p = position, let s = size,
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else {
        throw Failure("owned-window-ax-geometry-type")
    }
    var point = CGPoint.zero, dimensions = CGSize.zero
    try require(AXValueGetValue(p as! AXValue, .cgPoint, &point) &&
                AXValueGetValue(s as! AXValue, .cgSize, &dimensions), "owned-window-ax-geometry-value")
    let frame = CGRect(origin: point, size: dimensions)
    try require(valid(frame), "owned-window-ax-invalid-frame")
    return frame
}

@MainActor func directResizeOwnedWindow(_ window: SCWindow, owner: DirectOwner,
    pid: pid_t, directory: URL, select: (CGWindowID?, String) async throws -> SCWindow) async throws -> SCWindow {
    var proof: [String: Any] = ["schema": "p1-direct-owned-window-resize-v1",
        "ownerPID": pid, "windowID": window.windowID, "beforeFrame": rect(window.frame),
        "requestedSize": [700, 1550], "permissionRequested": false,
        "sourceResolutionEstablished": false, "admissionEligible": false]
    let path = directory.appendingPathComponent("window-resize.json")
    let trusted = AXIsProcessTrusted()
    proof["existingAccessibilityTrust"] = trusted
    try write(proof, path)
    try require(trusted, "existing-accessibility-trust-absent")
    try require(owner.valid(), "resize-owner-changed")
    let app = AXUIElementCreateApplication(pid)
    try require(AXUIElementSetMessagingTimeout(app, 2) == .success, "owned-ax-timeout-unavailable")
    var value: CFTypeRef?
    try require(AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &value) == .success,
                "owned-ax-windows-unavailable")
    guard let windows = value as? [AXUIElement], windows.count == 1 else {
        throw Failure("ambiguous-owned-ax-window")
    }
    let target = windows[0]
    try require(AXUIElementSetMessagingTimeout(target, 2) == .success, "owned-window-ax-timeout-unavailable")
    var axPID: pid_t = 0
    try require(AXUIElementGetPid(target, &axPID) == .success && axPID == pid,
                "owned-ax-window-pid-mismatch")
    try require(try directAXRect(target) == window.frame, "owned-ax-window-frame-mismatch")
    var settable = DarwinBoolean(false)
    try require(AXUIElementIsAttributeSettable(target, kAXSizeAttribute as CFString, &settable) == .success &&
                settable.boolValue, "owned-window-size-not-settable")
    try require(owner.valid(), "resize-owner-changed")
    var requested = CGSize(width: 700, height: 1550)
    if window.frame.size == requested {
        proof["mutationAttempted"] = false
        proof["alreadyRequestedSize"] = true
        proof["afterFrame"] = rect(window.frame)
        proof["sameOwnedWindowSettled"] = true
        try write(proof, path)
        return window
    }
    guard let sizeValue = AXValueCreate(.cgSize, &requested) else { throw Failure("owned-window-size-value") }
    proof["mutationAttempted"] = true
    try write(proof, path)
    try require(AXUIElementSetAttributeValue(target, kAXSizeAttribute as CFString, sizeValue) == .success,
                "owned-window-resize-failed")
    var prior: CGRect?
    // The caller's unchanged observation deadline independently bounds this
    // loop and all AX/ScreenCaptureKit callbacks. No resize retry is performed.
    while true {
        try require(owner.valid(), "resize-owner-changed")
        let current = try await select(window.windowID, "resized")
        try require(current.frame.width <= 2048 && current.frame.height <= 2048,
                    "resized-window-outside-bounds")
        let axFrame = try directAXRect(target)
        if current.frame == prior && current.frame == axFrame && current.frame != window.frame {
            proof["afterFrame"] = rect(current.frame)
            proof["sameOwnedWindowSettled"] = true
            try write(proof, path)
            return current
        }
        prior = current.frame
        try await Task.sleep(nanoseconds: 100_000_000)
    }
}


// Generated from the exact reviewed owned-window Sink. Local draft.
final class DirectSink: NSObject, SCStreamOutput, SCStreamDelegate {
    let directory: URL
    let plan: DirectROIPlan
    let expectedPID: pid_t
    let executable: String
    let queue = DispatchQueue(label: "p1.owned.window.frames")
    private let lock = NSLock()
    private var failure: String?
    private var records: [[String: Any]] = []
    private var copiedBytes = 0
    private var lastDisplay: UInt64 = 0
    private var geometry: [Double]?
    private var complete = 0
    private var startedFrameSeen = false
    private var stoppedFrameSeen = false
    private var delivered = 0
    private var overflow = 0
    private var firstCompleteRecord: [String: Any]?
    init(directory: URL, pid: pid_t, executable: String, plan: DirectROIPlan) throws {
        try plan.validate()
        self.plan = plan
        self.directory = directory; self.expectedPID = pid; self.executable = executable
    }
    func ownerValid() -> Bool {
        guard let app = NSRunningApplication(processIdentifier: expectedPID), !app.isTerminated,
              app.bundleIdentifier == "com.apple.iphonesimulator",
              app.executableURL?.resolvingSymlinksInPath().path == executable else { return false }
        return true
    }
    func failed(_ code: String) { lock.lock(); if failure == nil { failure = code }; lock.unlock() }
    func errorCode() -> String? { lock.lock(); defer { lock.unlock() }; return failure }
    func stream(_ stream: SCStream, didStopWithError error: Error) { failed("stream-stopped-with-error") }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { failed("unexpected-output-type"); return }
        let callbackBefore = mach_absolute_time()
        delivered += 1
        guard records.count < 6000 else { overflow += 1; failed("frame-record-limit"); return }
        var row: [String: Any] = ["index": records.count, "callbackBeforeMach": callbackBefore]
        do {
            try require(ownerValid(), "owner-changed")
            try require(sample.isValid, "invalid-sample")
            guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
                  attachments.count == 1, let statusNumber = attachments[0][.status] as? NSNumber,
                  let statusValue = exactUnsigned(statusNumber), statusValue <= UInt64(Int.max),
                  let status = SCFrameStatus(rawValue: Int(statusValue)) else { throw Failure("missing-or-unknown-status") }
            row["status"] = status.rawValue
            if errorCode() != nil { throw Failure("prior-frame-failure-latched") }
            let pts = CMSampleBufferGetPresentationTimeStamp(sample)
            row["ptsValue"] = pts.value; row["ptsTimescale"] = pts.timescale; row["ptsFlags"] = pts.flags.rawValue
            try require(!stoppedFrameSeen, "frame-after-stopped")
            if status == .started {
                try require(!startedFrameSeen && complete == 0, "misordered-started-frame")
                startedFrameSeen = true; row["statusName"] = "started"; row["newFrame"] = false
            } else if status == .stopped {
                stoppedFrameSeen = true; row["statusName"] = "stopped"; row["newFrame"] = false
            } else if status == .idle {
                row["statusName"] = "idle"; row["newFrame"] = false
            } else {
                try require(status == .complete, "noncomplete-frame-status")
                row["statusName"] = "complete"
                let info = attachments[0]
                guard let number = info[.displayTime] as? NSNumber,
                      let contentDictionary = info[.contentRect] as? [String: Any],
                      let content = CGRect(dictionaryRepresentation: contentDictionary as CFDictionary),
                      let scale = info[.contentScale] as? NSNumber,
                      let factor = info[.scaleFactor] as? NSNumber,
                      let buffer = CMSampleBufferGetImageBuffer(sample) else { throw Failure("incomplete-frame-metadata") }
                guard let display = exactUnsigned(number) else { throw Failure("invalid-display-time-type") }
                try require(display > 0 && display > lastDisplay, "display-time-regression")
                try require(pts.isNumeric && valid(content) && scale.doubleValue.isFinite && scale.doubleValue > 0 && factor.doubleValue.isFinite && factor.doubleValue > 0, "invalid-frame-geometry")
                let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer), stride = CVPixelBufferGetBytesPerRow(buffer)
                try require(width > 0 && width <= 2048 && height > 0 && height <= 2048 && stride >= width * 4 && stride <= 16384 && CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA, "invalid-pixel-layout")
                let currentGeometry = [Double(width), Double(height), Double(stride)] + rect(content) + [scale.doubleValue, factor.doubleValue]
                if let prior = geometry { try require(prior == currentGeometry, "geometry-replacement") }
                let size = plan.byteCount
                try require(copiedBytes <= 3 * 1024 * 1024 * 1024 - size, "pixel-byte-limit")
                let data = try directCopyROIs(buffer, plan: plan)
                let regions = try directROIManifest(plan, packed: data)
                let rawName = String(format: "frame-%05d.rois.bgra", records.count)
                try data.write(to: directory.appendingPathComponent(rawName), options: .atomic)
                row.merge(["newFrame": true, "session": plan.session,
                           "geometrySHA256": plan.geometrySHA256, "displayTimeMach": display,
                           "width": width, "height": height, "bytesPerRow": stride,
                           "contentRect": rect(content), "contentScale": scale.doubleValue,
                           "scaleFactor": factor.doubleValue, "copiedBytes": size,
                           "packedPixels": rawName, "packedPixelSHA256": digest(data),
                           "regions": regions]) { _, new in new }
                copiedBytes += size; lastDisplay = display; geometry = currentGeometry; complete += 1
            }
        } catch { let code = (error as? Failure)?.code ?? "frame-processing-error"; row["error"] = code; failed(code) }
        row["callbackAfterMach"] = mach_absolute_time(); records.append(row)
        if row["statusName"] as? String == "complete" && row["error"] == nil {
            lock.lock(); if firstCompleteRecord == nil { firstCompleteRecord = row }; lock.unlock()
        }
    }
    func firstComplete() -> [String: Any]? {
        lock.lock(); defer { lock.unlock() }; return firstCompleteRecord
    }
    func result() -> [String: Any] {
        queue.sync { ["frames": records, "completeFrames": complete, "deliveredRecords": delivered, "overflowRecords": overflow, "copiedBytes": copiedBytes, "error": errorCode() as Any? ?? NSNull()] }
    }
}


// Local uncompiled direct lifecycle adapter. Source-bound, no admission.
@main struct Main {
    @MainActor static func main() async {
        let args = CommandLine.arguments
        if args.count == 2 && args[1] == "--check-existing-accessibility" {
            let proof: [String: Any] = ["schema": "p1-direct-accessibility-prerequisite-v1",
                "existingAccessibilityTrust": AXIsProcessTrusted(), "permissionRequested": false,
                "windowsEnumerated": false, "pixelsCaptured": false, "admissionEligible": false]
            guard let bytes = try? JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys]) else { exit(2) }
            FileHandle.standardOutput.write(bytes)
            return
        }
        guard args.count == 7, let pid = Int32(args[1]), pid > 1 else { exit(2) }
        let executable = args[2], directory = URL(fileURLWithPath: args[3], isDirectory: true)
        let session = args[4]
        guard let observationDeadline = UInt64(args[5]), let cleanupDeadline = UInt64(args[6]) else { exit(2) }
        var result: [String: Any] = ["schema": "p1-direct-owned-window-collection-v1", "admissionEligible": false,
            "calibrationFeasible": false, "feedbackLifetimeEstablished": false, "inputOverlapEstablished": false,
            "guestPresentationEquivalenceEstablished": false, "permissionRequested": false, "captureCompleted": false]
        let deadline = DirectDeadline(directory, observation: observationDeadline, cleanup: cleanupDeadline)
        let owner = DirectOwner(pid: pid, executable: executable)
        var sink: DirectSink?
        var stream: SCStream?
        var started = false
        var startAttempted = false
        var stopConfirmed = false
        do {
            deadline.arm(10, "appkit-initialization")
            try write(["schema": "p1-window-bootstrap-v1", "phase": "before-appkit", "admissionEligible": false], directory.appendingPathComponent("bootstrap.json"))
            _ = NSApplication.shared
            try write(["schema": "p1-window-bootstrap-v1", "phase": "appkit-initialized", "admissionEligible": false], directory.appendingPathComponent("bootstrap.json"))
            deadline.cancel()
            try require(session.utf8.count == 32 && session.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }, "invalid-direct-session")
            result["session"] = session
            try require(CGPreflightScreenCaptureAccess(), "existing-permission-absent")
            try require(executable == "/Applications/Xcode_26.4.1.app/Contents/Developer/Applications/Simulator.app/Contents/MacOS/Simulator" && owner.valid(), "unverified-gui-owner")
            func select(_ expected: CGWindowID?, phase: String) async throws -> SCWindow {
                let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
                let windows = content.windows.filter { $0.owningApplication?.processID == pid && $0.isOnScreen }
                try require(windows.count <= 16, "owned-window-census-overflow")
                let census: [[String: Any]] = windows.map { ["windowID": $0.windowID, "frame": rect($0.frame)] }
                try write(["schema": "p1-owned-window-census-v1", "ownerPID": pid, "phase": phase,
                           "count": windows.count, "windows": census, "admissionEligible": false],
                          directory.appendingPathComponent("window-census-" + phase + ".json"))
                try require(owner.valid(), "unverified-gui-owner")
                try require(windows.allSatisfy { valid($0.frame) } && Set(windows.map { $0.windowID }).count == windows.count, "invalid-owned-window-census")
                if let expected = expected {
                    let matching = windows.filter { $0.windowID == expected }
                    try require(matching.count == 1, "original-owned-window-missing")
                    return matching[0]
                }
                try require(windows.count == 1, "ambiguous-owned-window")
                return windows[0]
            }
            deadline.arm(15, "window-enumeration")
            let originalWindow = try await select(nil, phase: "initial"); deadline.cancel()
            deadline.arm(15, "owned-window-resize")
            let window = try await directResizeOwnedWindow(originalWindow, owner: owner, pid: pid,
                directory: directory, select: { id, phase in try await select(id, phase: phase) })
            deadline.cancel()
            var timebase = mach_timebase_info_data_t()
            try require(mach_timebase_info(&timebase) == KERN_SUCCESS && timebase.numer > 0 && timebase.denom > 0, "invalid-mach-timebase")
            result["windowID"] = window.windowID; result["ownerPID"] = pid; result["executable"] = executable
            result["windowFrame"] = rect(window.frame); result["timebaseNumerator"] = timebase.numer; result["timebaseDenominator"] = timebase.denom
            let filter = SCContentFilter(desktopIndependentWindow: window)
            let configuration = SCStreamConfiguration()
            let scale = Double(filter.pointPixelScale), content = filter.contentRect
            try require(scale.isFinite && scale > 0 && scale <= 4 && valid(content), "invalid-filter-scale")
            let pixelWidth = Double(content.width) * scale, pixelHeight = Double(content.height) * scale
            try require(pixelWidth > 0 && pixelWidth <= 2048 && pixelHeight > 0 && pixelHeight <= 2048, "bounded-native-filter-pixels")
            configuration.width = Int(pixelWidth.rounded(.up)); configuration.height = Int(pixelHeight.rounded(.up))
            result["filterContentRect"] = rect(content); result["filterPointPixelScale"] = scale
            result["configuredPixelSize"] = [configuration.width, configuration.height]
            configuration.pixelFormat = kCVPixelFormatType_32BGRA
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
            configuration.queueDepth = 3; configuration.showsCursor = false; configuration.capturesAudio = false
            configuration.captureMicrophone = false
            deadline.arm(15, "baseline-full-context")
            let (baseline, baselineMetadata) = try await directRegistrationFrame(filter: filter, configuration: configuration)
            try baseline.write(to: directory.appendingPathComponent("baseline.bgra"), options: .atomic)
            try write(baselineMetadata.merging(["windowID": window.windowID, "session": session]) { _, new in new }, directory.appendingPathComponent("baseline.json"))
            deadline.cancel()
            deadline.arm(80, "roi-plan-handoff")
            let planChannel = try DirectRequestChannel(directory.appendingPathComponent("roi-channel"))
            var planBytes: Data?
            while planBytes == nil {
                try require(owner.valid(), "owner-changed-during-registration")
                planBytes = try planChannel.readOnce()
                if planBytes == nil { try await Task.sleep(nanoseconds: 50_000_000) }
            }
            guard let bytes = planBytes,
                  let bw = baselineMetadata["width"] as? Int, let bh = baselineMetadata["height"] as? Int,
                  let bs = baselineMetadata["stride"] as? Int else { throw Failure("baseline-layout-unavailable") }
            let plan = try directPlan(bytes, session: session, window: window.windowID, baselineWidth: bw, baselineHeight: bh, baselineStride: bs)
            try bytes.write(to: directory.appendingPathComponent("accepted-roi-plan.json"), options: .atomic)
            let registeredWindow = try await select(window.windowID, phase: "registered")
            try require(registeredWindow.frame == window.frame && owner.valid(), "registration-window-changed")
            deadline.cancel()
            let activeSink = try DirectSink(directory: directory, pid: pid, executable: executable, plan: plan)
            sink = activeSink
            let capture = SCStream(filter: filter, configuration: configuration, delegate: activeSink)
            stream = capture
            try capture.addStreamOutput(activeSink, type: .screen, sampleHandlerQueue: activeSink.queue)
            deadline.arm(15, "stream-start")
            startAttempted = true
            try await capture.startCapture(); started = true; deadline.cancel()
            result["captureStartedMach"] = mach_absolute_time()
            try write(["schema": "p1-direct-stream-ready-v1", "session": session,
                       "ownerPID": pid, "windowID": window.windowID, "executable": executable,
                       "windowFrame": rect(window.frame), "geometrySHA256": plan.geometrySHA256,
                       "timebaseNumerator": timebase.numer, "timebaseDenominator": timebase.denom,
                       "startCaptureReturnedMach": result["captureStartedMach"]!,
                       "startCaptureReturned": true, "presentationLowerBoundEstablished": false,
                       "admissionEligible": false], directory.appendingPathComponent("stream-ready.json"))
            deadline.arm(240, "direct-protocol-observation")
            let stopChannel = try DirectRequestChannel(directory.appendingPathComponent("stop-channel"))
            var firstPublished = false
            while true {
                try require(owner.valid() && activeSink.errorCode() == nil, "direct-capture-owner-or-frame-failure")
                if !firstPublished, let first = activeSink.firstComplete() {
                    let before = mach_absolute_time()
                    try write(first, directory.appendingPathComponent("first-complete.json"))
                    try write(["beforeMach": before, "afterMach": mach_absolute_time(), "admissionEligible": false], directory.appendingPathComponent("first-publish-cost.json"))
                    firstPublished = true
                }
                if let stop = try stopChannel.readOnce() {
                    let row = try directObject(stop, keys: ["schema", "session", "geometrySHA256", "kind"])
                    try require(row["schema"] as? String == "p1-direct-stop-v1" && row["session"] as? String == session &&
                                row["geometrySHA256"] as? String == plan.geometrySHA256 && row["kind"] as? String == "protocol-finished", "direct-stop-binding")
                    try require(firstPublished, "stop-before-complete-frame")
                    try stop.write(to: directory.appendingPathComponent("accepted-stop.json"), options: .atomic)
                    break
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            deadline.cancel()
            deadline.beginCleanup()
            deadline.arm(10, "stream-stop")
            try await capture.stopCapture(); started = false; stopConfirmed = true; deadline.cancel()
            result["captureStoppedMach"] = mach_absolute_time()
            deadline.arm(15, "window-revalidation")
            let after = try await select(window.windowID, phase: "final"); deadline.cancel()
            try require(owner.valid() && after.windowID == window.windowID && after.frame == window.frame, "window-binding-changed")
            result["windowRevalidationPassed"] = true
            deadline.arm(15, "final-full-context")
            let (final, finalMetadata) = try await directRegistrationFrame(filter: filter, configuration: configuration)
            try require(finalMetadata["width"] as? Int == bw && finalMetadata["height"] as? Int == bh && finalMetadata["stride"] as? Int == bs, "final-context-layout-changed")
            try final.write(to: directory.appendingPathComponent("final.bgra"), options: .atomic)
            try write(finalMetadata.merging(["windowID": window.windowID, "session": session]) { _, new in new }, directory.appendingPathComponent("final.json"))
            let finalWindow = try await select(window.windowID, phase: "after-final-context")
            try require(finalWindow.frame == window.frame && owner.valid(), "final-context-owner-changed")
            result["finalContextRetained"] = true
            deadline.cancel()
        } catch { result["error"] = (error as? Failure)?.code ?? "native-capture-error" }
        deadline.beginCleanup()
        if startAttempted && !stopConfirmed, let capture = stream {
            do { deadline.arm(10, "recovery-stream-stop"); try await capture.stopCapture(); started = false; stopConfirmed = true; deadline.cancel() }
            catch { result["stopError"] = "stream-stop-unconfirmed" }
        }
        result["streamStopped"] = stopConfirmed
        result["startAttempted"] = startAttempted
        result["streamNeverStarted"] = !startAttempted
        if stopConfirmed, let capture = stream, let sink = sink {
            deadline.arm(10, "stream-output-detach")
            do { try capture.removeStreamOutput(sink, type: .screen); result["outputDetached"] = true; deadline.cancel() }
            catch { result["detachError"] = "stream-output-detach-failed" }
        }
        deadline.arm(10, "frame-queue-drain")
        let samples = sink?.result() ?? ["error": "stream-never-created", "completeFrames": 0]; deadline.cancel(); result["samples"] = samples
        result["captureCompleted"] = result["windowRevalidationPassed"] as? Bool == true &&
            result["outputDetached"] as? Bool == true && result["finalContextRetained"] as? Bool == true && stopConfirmed && result["error"] == nil &&
            result["stopError"] == nil && result["detachError"] == nil && samples["error"] is NSNull &&
            (samples["overflowRecords"] as? Int) == 0 && (samples["completeFrames"] as? Int ?? 0) >= 2
        deadline.checkFinal()
        do { try write(result, directory.appendingPathComponent("window-capture.json")) }
        catch { exit(3) }
        deadline.checkFinal()
        exit(result["captureCompleted"] as? Bool == true && stopConfirmed ? 0 : 1)
    }
}
