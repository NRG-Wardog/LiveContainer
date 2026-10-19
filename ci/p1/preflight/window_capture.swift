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

final class Sink: NSObject, SCStreamOutput, SCStreamDelegate {
    let directory: URL
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
    init(directory: URL, pid: pid_t, executable: String) {
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
        guard records.count < 600 else { overflow += 1; failed("frame-record-limit"); return }
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
                let size = stride * height
                try require(copiedBytes <= 256 * 1024 * 1024 - size, "pixel-byte-limit")
                try require(CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "pixel-lock-failed")
                let data: Data
                do {
                    guard let address = CVPixelBufferGetBaseAddress(buffer) else { throw Failure("pixel-address-missing") }
                    data = Data(bytes: address, count: size)
                } catch { CVPixelBufferUnlockBaseAddress(buffer, .readOnly); throw error }
                try require(CVPixelBufferUnlockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "pixel-unlock-failed")
                guard let provider = CGDataProvider(data: data as CFData),
                      let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: stride, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedFirst.rawValue).union(.byteOrder32Little), provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else { throw Failure("pixel-image-failed") }
                let rawName = String(format: "frame-%04d.bgra", records.count)
                try data.write(to: directory.appendingPathComponent(rawName), options: .atomic)
                let name = String(format: "frame-%04d.png", records.count), path = directory.appendingPathComponent(name)
                guard let destination = CGImageDestinationCreateWithURL(path as CFURL, UTType.png.identifier as CFString, 1, nil) else { throw Failure("png-destination-failed") }
                CGImageDestinationAddImage(destination, image, nil)
                try require(CGImageDestinationFinalize(destination), "png-finalization-failed")
                row.merge(["newFrame": true, "displayTimeMach": display, "width": width, "height": height, "bytesPerRow": stride,
                           "contentRect": rect(content), "contentScale": scale.doubleValue, "scaleFactor": factor.doubleValue,
                           "copiedBytes": size, "rawPixels": rawName, "rawPixelSHA256": digest(data), "png": name, "pngSHA256": digest(try Data(contentsOf: path))]) { _, new in new }
                copiedBytes += size; lastDisplay = display; geometry = currentGeometry; complete += 1
            }
        } catch { let code = (error as? Failure)?.code ?? "frame-processing-error"; row["error"] = code; failed(code) }
        row["callbackAfterMach"] = mach_absolute_time(); records.append(row)
    }
    func result() -> [String: Any] {
        queue.sync { ["frames": records, "completeFrames": complete, "deliveredRecords": delivered, "overflowRecords": overflow, "copiedBytes": copiedBytes, "error": errorCode() as Any? ?? NSNull()] }
    }
}

@main struct Main {
    @MainActor static func main() async {
        let args = CommandLine.arguments
        guard args.count == 4, let pid = Int32(args[1]), pid > 1 else { exit(2) }
        let executable = args[2], directory = URL(fileURLWithPath: args[3], isDirectory: true)
        var result: [String: Any] = ["schema": "p1-owned-window-acquisition-v1", "admissionEligible": false,
            "calibrationFeasible": false, "feedbackLifetimeEstablished": false, "inputOverlapEstablished": false,
            "guestPresentationEquivalenceEstablished": false, "permissionRequested": false, "captureCompleted": false]
        let deadline = StageDeadline(directory)
        let sink = Sink(directory: directory, pid: pid, executable: executable)
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
            try require(CGPreflightScreenCaptureAccess(), "existing-permission-absent")
            try require(executable == "/Applications/Xcode_26.4.1.app/Contents/Developer/Applications/Simulator.app/Contents/MacOS/Simulator" && sink.ownerValid(), "unverified-gui-owner")
            func select(_ expected: CGWindowID?, phase: String) async throws -> SCWindow {
                let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
                let windows = content.windows.filter { $0.owningApplication?.processID == pid && $0.isOnScreen }
                try require(windows.count <= 16, "owned-window-census-overflow")
                let census: [[String: Any]] = windows.map { ["windowID": $0.windowID, "frame": rect($0.frame)] }
                try write(["schema": "p1-owned-window-census-v1", "ownerPID": pid, "phase": phase,
                           "count": windows.count, "windows": census, "admissionEligible": false],
                          directory.appendingPathComponent("window-census-" + phase + ".json"))
                try require(sink.ownerValid(), "unverified-gui-owner")
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
            let window = try await select(nil, phase: "initial"); deadline.cancel()
            var timebase = mach_timebase_info_data_t()
            try require(mach_timebase_info(&timebase) == KERN_SUCCESS && timebase.numer > 0 && timebase.denom > 0, "invalid-mach-timebase")
            result["windowID"] = window.windowID; result["ownerPID"] = pid; result["executable"] = executable
            result["windowFrame"] = rect(window.frame); result["timebaseNumerator"] = timebase.numer; result["timebaseDenominator"] = timebase.denom
            let configuration = SCStreamConfiguration()
            try require(window.frame.width <= 2048 && window.frame.height <= 2048, "window-dimensions-outside-bound")
            configuration.width = Int(window.frame.width.rounded(.up)); configuration.height = Int(window.frame.height.rounded(.up))
            try require(configuration.width > 0 && configuration.width <= 2048 && configuration.height > 0 && configuration.height <= 2048, "window-dimensions-outside-bound")
            configuration.pixelFormat = kCVPixelFormatType_32BGRA
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 10)
            configuration.queueDepth = 3; configuration.showsCursor = false; configuration.capturesAudio = false
            configuration.captureMicrophone = false
            let capture = SCStream(filter: SCContentFilter(desktopIndependentWindow: window), configuration: configuration, delegate: sink)
            stream = capture
            try capture.addStreamOutput(sink, type: .screen, sampleHandlerQueue: sink.queue)
            deadline.arm(15, "stream-start")
            startAttempted = true
            try await capture.startCapture(); started = true; deadline.cancel()
            result["captureStartedMach"] = mach_absolute_time()
            deadline.arm(12, "stream-observation")
            try await Task.sleep(nanoseconds: 10_000_000_000); deadline.cancel()
            deadline.arm(10, "stream-stop")
            try await capture.stopCapture(); started = false; stopConfirmed = true; deadline.cancel()
            result["captureStoppedMach"] = mach_absolute_time()
            deadline.arm(15, "window-revalidation")
            let after = try await select(window.windowID, phase: "final"); deadline.cancel()
            try require(sink.ownerValid() && after.windowID == window.windowID && after.frame == window.frame, "window-binding-changed")
            result["windowRevalidationPassed"] = true
        } catch { result["error"] = (error as? Failure)?.code ?? "native-capture-error" }
        if startAttempted && !stopConfirmed, let capture = stream {
            do { deadline.arm(10, "recovery-stream-stop"); try await capture.stopCapture(); started = false; stopConfirmed = true; deadline.cancel() }
            catch { result["stopError"] = "stream-stop-unconfirmed" }
        }
        result["streamStopped"] = stopConfirmed
        result["startAttempted"] = startAttempted
        result["streamNeverStarted"] = !startAttempted
        if stopConfirmed, let capture = stream {
            deadline.arm(10, "stream-output-detach")
            do { try capture.removeStreamOutput(sink, type: .screen); result["outputDetached"] = true; deadline.cancel() }
            catch { result["detachError"] = "stream-output-detach-failed" }
        }
        deadline.arm(10, "frame-queue-drain")
        let samples = sink.result(); deadline.cancel(); result["samples"] = samples
        result["captureCompleted"] = result["windowRevalidationPassed"] as? Bool == true &&
            result["outputDetached"] as? Bool == true && stopConfirmed && result["error"] == nil &&
            result["stopError"] == nil && result["detachError"] == nil && samples["error"] is NSNull &&
            (samples["overflowRecords"] as? Int) == 0 && (samples["completeFrames"] as? Int ?? 0) >= 2
        do { try write(result, directory.appendingPathComponent("window-capture.json")) }
        catch { exit(3) }
        exit(result["captureCompleted"] as? Bool == true && stopConfirmed ? 0 : 1)
    }
}
