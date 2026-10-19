"""Generate local direct-capture lifecycle from the sealed reviewed lifecycle.

This is an uncompiled integration draft, not permission to run it.
"""
from pathlib import Path
import hashlib
from build_sink import SOURCE,replace_once

HERE=Path(__file__).parent


def build(source,expected_sha):
    if hashlib.sha256(source.encode()).hexdigest()!=expected_sha:raise ValueError('lifecycle source drift')
    source=source[source.index('@main struct Main'):]
    source=replace_once(source,'        let args = CommandLine.arguments', '''        let args = CommandLine.arguments
        if args.count == 2 && args[1] == "--check-existing-accessibility" {
            let proof: [String: Any] = ["schema": "p1-direct-accessibility-prerequisite-v1",
                "existingAccessibilityTrust": AXIsProcessTrusted(), "permissionRequested": false,
                "windowsEnumerated": false, "pixelsCaptured": false, "admissionEligible": false]
            guard let bytes = try? JSONSerialization.data(withJSONObject: proof, options: [.sortedKeys]) else { exit(2) }
            FileHandle.standardOutput.write(bytes)
            return
        }''')
    source=replace_once(source,'args.count == 4','args.count == 7')
    source=replace_once(source,'let executable = args[2], directory = URL(fileURLWithPath: args[3], isDirectory: true)',
        'let executable = args[2], directory = URL(fileURLWithPath: args[3], isDirectory: true)\n        let session = args[4]\n        guard let observationDeadline = UInt64(args[5]), let cleanupDeadline = UInt64(args[6]) else { exit(2) }')
    source=replace_once(source, 'let deadline = StageDeadline(directory)', 'let deadline = DirectDeadline(directory, observation: observationDeadline, cleanup: cleanupDeadline)')
    source=source.replace('p1-owned-window-acquisition-v1','p1-direct-owned-window-collection-v1')
    source=replace_once(source,'let sink = Sink(directory: directory, pid: pid, executable: executable)',
        'let owner = DirectOwner(pid: pid, executable: executable)\n        var sink: DirectSink?')
    source=source.replace('sink.ownerValid()','owner.valid()')
    source=replace_once(source, '            func select(_ expected: CGWindowID?, phase: String) async throws -> SCWindow {',
        '            var initialAttempt = 0\n            func select(_ expected: CGWindowID?, phase: String) async throws -> SCWindow {')
    source=replace_once(source, '                try require(windows.count == 1, "ambiguous-owned-window")', '''                if phase == "initial" {
                    try require(initialAttempt < 150, "initial-window-attempt-limit")
                    try write(["schema": "p1-owned-window-census-v1", "ownerPID": pid, "phase": phase,
                               "count": windows.count, "windows": census, "admissionEligible": false],
                              directory.appendingPathComponent("window-census-initial-attempt-" + String(initialAttempt) + ".json"))
                    initialAttempt += 1
                    try require(!windows.isEmpty, "owned-window-not-ready")
                }
                try require(windows.count == 1, "ambiguous-owned-window")''')
    source=replace_once(source,'let window = try await select(nil, phase: "initial"); deadline.cancel()',
        '''var readyWindow: SCWindow?
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
            deadline.cancel()''')
    source=replace_once(source,'            try require(CGPreflightScreenCaptureAccess(),',
        '            try require(session.utf8.count == 32 && session.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }, "invalid-direct-session")\n            result["session"] = session\n            try require(CGPreflightScreenCaptureAccess(),')
    start=source.index('            let configuration = SCStreamConfiguration()')
    end=source.index('            configuration.pixelFormat',start)
    source=source[:start]+'''            let filter = SCContentFilter(desktopIndependentWindow: window)
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
'''+source[end:]
    source=replace_once(source,'CMTime(value: 1, timescale: 10)','CMTime(value: 1, timescale: 30)')
    source=replace_once(source,'            let capture = SCStream(filter: SCContentFilter(desktopIndependentWindow: window), configuration: configuration, delegate: sink)', '''            deadline.arm(15, "baseline-full-context")
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
            let capture = SCStream(filter: filter, configuration: configuration, delegate: activeSink)''')
    source=replace_once(source,'capture.addStreamOutput(sink, type: .screen, sampleHandlerQueue: sink.queue)',
        'capture.addStreamOutput(activeSink, type: .screen, sampleHandlerQueue: activeSink.queue)')
    source=replace_once(source,'''            deadline.arm(12, "stream-observation")
            try await Task.sleep(nanoseconds: 10_000_000_000); deadline.cancel()''','''            deadline.arm(240, "direct-protocol-observation")
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
            deadline.cancel()''')
    source=replace_once(source,'            result["windowRevalidationPassed"] = true','''            result["windowRevalidationPassed"] = true
            deadline.arm(15, "final-full-context")
            let (final, finalMetadata) = try await directRegistrationFrame(filter: filter, configuration: configuration)
            try require(finalMetadata["width"] as? Int == bw && finalMetadata["height"] as? Int == bh && finalMetadata["stride"] as? Int == bs, "final-context-layout-changed")
            try final.write(to: directory.appendingPathComponent("final.bgra"), options: .atomic)
            try write(finalMetadata.merging(["windowID": window.windowID, "session": session]) { _, new in new }, directory.appendingPathComponent("final.json"))
            let finalWindow = try await select(window.windowID, phase: "after-final-context")
            try require(finalWindow.frame == window.frame && owner.valid(), "final-context-owner-changed")
            result["finalContextRetained"] = true
            deadline.cancel()''')
    source=replace_once(source, '            deadline.arm(10, "stream-stop")', '            deadline.beginCleanup()\n            deadline.arm(10, "stream-stop")')
    source=replace_once(source, '        if startAttempted && !stopConfirmed, let capture = stream {', '        deadline.beginCleanup()\n        if startAttempted && !stopConfirmed, let capture = stream {')
    source=source.replace('if stopConfirmed, let capture = stream {','if stopConfirmed, let capture = stream, let sink = sink {')
    source=replace_once(source,'let samples = sink.result();','let samples = sink?.result() ?? ["error": "stream-never-created", "completeFrames": 0];')
    source=replace_once(source,'result["outputDetached"] as? Bool == true && stopConfirmed',
        'result["outputDetached"] as? Bool == true && result["finalContextRetained"] as? Bool == true && stopConfirmed')
    source=replace_once(source, '        do { try write(result,', '        deadline.checkFinal()\n        do { try write(result,')
    source=replace_once(source, '        exit(result["captureCompleted"]', '        deadline.checkFinal()\n        exit(result["captureCompleted"]')
    source=replace_once(source, '            result["captureStartedMach"] = mach_absolute_time()', '''            result["captureStartedMach"] = mach_absolute_time()
            try write(["schema": "p1-direct-stream-ready-v1", "session": session,
                       "ownerPID": pid, "windowID": window.windowID, "executable": executable,
                       "windowFrame": rect(window.frame), "geometrySHA256": plan.geometrySHA256,
                       "timebaseNumerator": timebase.numer, "timebaseDenominator": timebase.denom,
                       "startCaptureReturnedMach": result["captureStartedMach"]!,
                       "startCaptureReturned": true, "presentationLowerBoundEstablished": false,
                       "admissionEligible": false], directory.appendingPathComponent("stream-ready.json"))''')
    return '// Local uncompiled direct lifecycle adapter. Source-bound, no admission.\n'+source

if __name__=='__main__':
    (HERE/'direct_main.swift').write_text(build(SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip()))
