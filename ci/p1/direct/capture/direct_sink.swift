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
