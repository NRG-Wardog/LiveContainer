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
            var initialAttempt = 0
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
                if phase == "initial" {
                    try require(initialAttempt < 150, "initial-window-attempt-limit")
                    try write(["schema": "p1-owned-window-census-v1", "ownerPID": pid, "phase": phase,
                               "count": windows.count, "windows": census, "admissionEligible": false],
                              directory.appendingPathComponent("window-census-initial-attempt-" + String(initialAttempt) + ".json"))
                    initialAttempt += 1
                    try require(!windows.isEmpty, "owned-window-not-ready")
                }
                try require(windows.count == 1, "ambiguous-owned-window")
                return windows[0]
            }
            deadline.arm(15, "window-enumeration")
            var readyWindow: SCWindow?
            for _ in 0..<150 {
                do { readyWindow = try await select(nil, phase: "initial"); break }
                catch let failure as Failure where failure.code == "owned-window-not-ready" {
                    try require(owner.valid(), "unverified-gui-owner")
                    try await Task.sleep(nanoseconds: 100_000_000)
                }
            }
            guard let originalWindow = readyWindow else { throw Failure("owned-window-readiness-exhausted") }
            deadline.cancel()
            deadline.arm(15, "owned-window-resize")
            let window = try await directResizeOwnedWindow(originalWindow, owner: owner, pid: pid,
                session: session, directory: directory, select: { id, phase in try await select(id, phase: phase) })
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
            try require(pixelWidth > 0 && pixelWidth <= 16384 && pixelHeight > 0 && pixelHeight <= 16384, "bounded-native-filter-pixels")
            let reduction = min(1.0, min(1000.0 / pixelWidth, 1600.0 / pixelHeight))
            configuration.width = Int((pixelWidth * reduction).rounded(.down))
            configuration.height = Int((pixelHeight * reduction).rounded(.down))
            try require(configuration.width > 0 && configuration.height > 0, "invalid-downscaled-raster")
            configuration.scalesToFit = true
            configuration.preservesAspectRatio = true
            configuration.ignoreGlobalClipSingleWindow = true
            result["nativeFilterPixelSize"] = [pixelWidth, pixelHeight]
            result["captureReductionFactor"] = reduction
            result["outputUpscaled"] = false
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
