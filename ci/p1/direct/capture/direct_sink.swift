// Generated from the exact reviewed owned-window Sink. Local draft.
final class DirectPendingPixels {
    var data: Data?
    init(_ data: Data?) { self.data = data }
}

final class DirectSink: NSObject, SCStreamOutput, SCStreamDelegate {
    let directory: URL
    let plan: DirectROIPlan
    let expectedPID: pid_t
    let executable: String
    let queue = DispatchQueue(label: "p1.owned.window.frames")
    private let lock = NSLock()
    private var failure: String?
    private var failureObservedMach: UInt64?
    private var records: [[String: Any]] = []
    private var copiedBytes = 0
    private let persistence = DispatchQueue(label: "p1.owned.window.persistence")
    private var pendingRecords = 0
    private static let startupLimit = 8
    private var startupRecords = (0..<8).map { DirectStartupRecord(index: $0, admitted: false, pendingAtArrival: 0) }
    private var startupOverflow: DirectStartupOverflow?
    private var startupAdmitted = 0
    private var startupReleased = 0
    private var startupInFlight = [-1, -1]
    private func startupMark(_ index: Int, _ stage: DirectStartupStage, at tick: UInt64? = nil) {
        guard index < Self.startupLimit else { return }
        let markStart = mach_absolute_time()
        let observed = tick ?? markStart
        lock.lock(); defer { lock.unlock() }
        // Each callback creates its own bounded record before any stage marks.
        guard index < startupRecords.count else { return }
        startupRecords[index].ticks[stage.rawValue] = observed
        startupRecords[index].traceMarkCount += 1
        startupRecords[index].traceMarkCostMach += mach_absolute_time() - markStart
    }
    func startupSnapshot() -> [String: Any] {
        lock.lock()
        let rows = startupRecords, firstOverflow = startupOverflow
        let admitted = startupAdmitted, released = startupReleased
        let inFlight = startupInFlight, pending = pendingRecords
        let observed = mach_absolute_time()
        lock.unlock()
        // Serialization/all dictionary construction is outside the admission lock.
        return ["schema": "p1-direct-startup-persistence-v1", "session": plan.session,
                "observedMach": observed, "recordLimit": Self.startupLimit,
                "stageNames": DirectStartupStage.allCases.map { String(describing: $0) },
                "missingMilestone": 0, "records": rows.filter { $0.ticks[DirectStartupStage.callbackEntry.rawValue] > 0 }.map { $0.json() },
                "firstOverflow": firstOverflow.map { $0.json() } as Any? ?? NSNull(),
                "admitted": admitted, "released": released, "pending": pending,
                "inFlight": inFlight, "admissionEligible": false]
    }
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
    func failed(_ code: String) {
        lock.lock()
        if failure == nil { failure = code; failureObservedMach = mach_absolute_time() }
        lock.unlock()
    }
    func failureSnapshot() -> [String: Any]? {
        lock.lock(); defer { lock.unlock() }
        guard let code = failure, let observed = failureObservedMach else { return nil }
        return ["code": directDiagnosticCode(code), "observedMach": observed]
    }
    func errorCode() -> String? { lock.lock(); defer { lock.unlock() }; return failure }
    func stream(_ stream: SCStream, didStopWithError error: Error) { failed("stream-stopped-with-error") }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { failed("unexpected-output-type"); return }
        let callbackBefore = mach_absolute_time()
        delivered += 1
        guard delivered <= 6000 else { overflow += 1; failed("frame-record-limit"); return }
        lock.lock()
        let startupIndex = delivered - 1
        if startupIndex < Self.startupLimit {
            startupRecords[startupIndex].admitted = pendingRecords < 2
            startupRecords[startupIndex].pendingAtArrival = pendingRecords
            startupRecords[startupIndex].ticks[DirectStartupStage.callbackEntry.rawValue] = callbackBefore
        }
        guard pendingRecords < 2 else {
            if startupOverflow == nil {
                startupOverflow = DirectStartupOverflow(index: startupIndex, observedMach: mach_absolute_time(),
                    pending: pendingRecords, admitted: startupAdmitted, released: startupReleased,
                    inFlight: startupInFlight, records: startupRecords)
            }
            lock.unlock(); overflow += 1; failed("persistence-backpressure"); return
        }
        pendingRecords += 1
        startupAdmitted += 1
        if let slot = startupInFlight.firstIndex(of: -1) { startupInFlight[slot] = delivered - 1 }
        lock.unlock()
        // Each reserved record can own at most the existing 1 MiB ROI plan.
        var payload: Data?
        var row: [String: Any] = ["index": delivered - 1, "callbackBeforeMach": callbackBefore]
        do {
            startupMark(startupIndex, .ownerBegin)
            try require(ownerValid(), "owner-changed")
            startupMark(startupIndex, .ownerEnd)
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
                startupMark(startupIndex, .metadataEnd)
                startupMark(startupIndex, .copyBegin)
                let data = try directCopyROIs(buffer, plan: plan, diagnostic: startupIndex < Self.startupLimit ? { [self] stage in startupMark(startupIndex, stage) } : nil)
                startupMark(startupIndex, .copyEnd)
                payload = data
                let rawName = String(format: "frame-%05d.rois.bgra", delivered - 1)
                row.merge(["newFrame": true, "session": plan.session,
                           "geometrySHA256": plan.geometrySHA256, "displayTimeMach": display,
                           "width": width, "height": height, "bytesPerRow": stride,
                           "contentRect": rect(content), "contentScale": scale.doubleValue,
                           "scaleFactor": factor.doubleValue, "copiedBytes": size,
                           "packedPixels": rawName]) { _, new in new }
                copiedBytes += size; lastDisplay = display; geometry = currentGeometry; complete += 1
            }
        } catch { let code = (error as? Failure)?.code ?? "frame-processing-error"; row["error"] = code; failed(code) }
        // This bracket covers synchronous validation and immutable pixel copying.
        // Dispatch submission and persistence have no presentation-time meaning.
        row["callbackAfterMach"] = mach_absolute_time()
        startupMark(startupIndex, .callbackEnd, at: row["callbackAfterMach"] as? UInt64)
        let capturedRow = row, captured = DirectPendingPixels(payload)
        payload = nil
        startupMark(startupIndex, .enqueueBefore)
        persistence.async { [self] in
            startupMark(startupIndex, .writerBegin)
            var retained = capturedRow
            defer {
                startupMark(startupIndex, .writerEnd)
                captured.data = nil
                lock.lock()
                pendingRecords -= 1
                startupReleased += 1
                if let slot = startupInFlight.firstIndex(of: startupIndex) { startupInFlight[slot] = -1 }
                if startupIndex < Self.startupLimit {
                    startupRecords[startupIndex].ticks[DirectStartupStage.reservationReleased.rawValue] = mach_absolute_time()
                }
                lock.unlock()
            }
            do {
                if let data = captured.data {
                    try require(errorCode() == nil, "prior-persistence-failure-latched")
                    startupMark(startupIndex, .writerOwnerBegin)
                    try require(ownerValid(), "persistence-owner-changed")
                    startupMark(startupIndex, .writerOwnerEnd)
                    startupMark(startupIndex, .regionHashBegin)
                    let regions = try directROIManifest(plan, packed: data)
                    startupMark(startupIndex, .regionHashEnd)
                    guard let name = retained["packedPixels"] as? String else { throw Failure("persistence-filename-missing") }
                    startupMark(startupIndex, .writeBegin)
                    try data.write(to: directory.appendingPathComponent(name), options: .atomic)
                    startupMark(startupIndex, .writeEnd)
                    startupMark(startupIndex, .packedHashBegin)
                    retained["packedPixelSHA256"] = digest(data)
                    startupMark(startupIndex, .packedHashEnd)
                    retained["regions"] = regions
                }
            } catch {
                let code = (error as? Failure)?.code ?? "frame-persistence-error"
                retained["error"] = code; failed(code)
            }
            records.append(retained)
            if retained["statusName"] as? String == "complete" && retained["error"] == nil && errorCode() == nil {
                lock.lock(); if firstCompleteRecord == nil { firstCompleteRecord = retained }; lock.unlock()
            }
        }
        startupMark(startupIndex, .enqueueAfter)
    }
    func firstComplete() -> [String: Any]? {
        lock.lock(); defer { lock.unlock() }; return firstCompleteRecord
    }
    func result() -> [String: Any] {
        queue.sync {}
        return persistence.sync { ["frames": records, "completeFrames": complete, "deliveredRecords": delivered, "overflowRecords": overflow, "copiedBytes": copiedBytes, "error": errorCode() as Any? ?? NSNull()] }
    }
}
