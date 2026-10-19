"""Local source-bound adapter; no native compilation or capture is performed."""
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]/'window-capture-candidate'
SOURCE=ROOT/'ci/p1/preflight/window_capture.swift'


def replace_once(source, old, new):
    if source.count(old)!=1:raise ValueError('ambiguous reviewed sink anchor')
    return source.replace(old,new)


def build(source, expected_sha):
    if hashlib.sha256(source.encode()).hexdigest()!=expected_sha:raise ValueError('owned-window source drift')
    source=source[source.index('final class Sink:'):source.index('\n@main struct Main')]
    source=source.replace('final class Sink:', 'final class DirectSink:',1)
    source=replace_once(source,'    let directory: URL','    let directory: URL\n    let plan: DirectROIPlan')
    source=replace_once(source,'init(directory: URL, pid: pid_t, executable: String) {','init(directory: URL, pid: pid_t, executable: String, plan: DirectROIPlan) throws {\n        try plan.validate()\n        self.plan = plan')
    source=replace_once(source,'records.count < 600','records.count < 6000')
    source=replace_once(source,'    private var overflow = 0','    private var overflow = 0\n    private var firstCompleteRecord: [String: Any]?')
    source=replace_once(source,'    func result() -> [String: Any] {','    func firstComplete() -> [String: Any]? {\n        lock.lock(); defer { lock.unlock() }; return firstCompleteRecord\n    }\n    func result() -> [String: Any] {')
    source=replace_once(source,'row["callbackAfterMach"] = mach_absolute_time(); records.append(row)', 'row["callbackAfterMach"] = mach_absolute_time(); records.append(row)\n        if row["statusName"] as? String == "complete" && row["error"] == nil {\n            lock.lock(); if firstCompleteRecord == nil { firstCompleteRecord = row }; lock.unlock()\n        }')

    start=source.index('                let size = stride * height')
    end=source.index('                copiedBytes += size;',start)
    source=source[:start]+'''                let size = plan.byteCount
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
'''+source[end:]
    source=replace_once(source,'final class DirectSink:', 'final class DirectPendingPixels {\n    var data: Data?\n    init(_ data: Data?) { self.data = data }\n}\n\nfinal class DirectSink:')
    source=replace_once(source,'    private var copiedBytes = 0', '    private var copiedBytes = 0\n    private let persistence = DispatchQueue(label: "p1.owned.window.persistence")\n    private var pendingRecords = 0')
    source=replace_once(source,'        delivered += 1\n        guard records.count < 6000 else { overflow += 1; failed("frame-record-limit"); return }\n        var row: [String: Any] = ["index": records.count, "callbackBeforeMach": callbackBefore]',
        '        delivered += 1\n        guard delivered <= 6000 else { overflow += 1; failed("frame-record-limit"); return }\n        lock.lock()\n        guard pendingRecords < 2 else { lock.unlock(); overflow += 1; failed("persistence-backpressure"); return }\n        pendingRecords += 1; lock.unlock()\n        // Each reserved record can own at most the existing 1 MiB ROI plan.\n        var payload: Data?\n        var row: [String: Any] = ["index": delivered - 1, "callbackBeforeMach": callbackBefore]')
    source=replace_once(source,'                let regions = try directROIManifest(plan, packed: data)\n                let rawName = String(format: "frame-%05d.rois.bgra", records.count)\n                try data.write(to: directory.appendingPathComponent(rawName), options: .atomic)',
        '                payload = data\n                let rawName = String(format: "frame-%05d.rois.bgra", delivered - 1)')
    source=replace_once(source,'"packedPixels": rawName, "packedPixelSHA256": digest(data),\n                           "regions": regions]', '"packedPixels": rawName]')
    source=replace_once(source,
        '        row["callbackAfterMach"] = mach_absolute_time(); records.append(row)\n        if row["statusName"] as? String == "complete" && row["error"] == nil {\n            lock.lock(); if firstCompleteRecord == nil { firstCompleteRecord = row }; lock.unlock()\n        }',
        '''        // This bracket covers synchronous validation and immutable pixel copying.
        // Dispatch submission and persistence have no presentation-time meaning.
        row["callbackAfterMach"] = mach_absolute_time()
        let capturedRow = row, captured = DirectPendingPixels(payload)
        payload = nil
        persistence.async { [self] in
            var retained = capturedRow
            defer { captured.data = nil; lock.lock(); pendingRecords -= 1; lock.unlock() }
            do {
                if let data = captured.data {
                    try require(errorCode() == nil, "prior-persistence-failure-latched")
                    try require(ownerValid(), "persistence-owner-changed")
                    let regions = try directROIManifest(plan, packed: data)
                    guard let name = retained["packedPixels"] as? String else { throw Failure("persistence-filename-missing") }
                    try data.write(to: directory.appendingPathComponent(name), options: .atomic)
                    retained["packedPixelSHA256"] = digest(data)
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
        }''')
    source=replace_once(source,'        queue.sync { ["frames": records,', '        queue.sync {}\n        return persistence.sync { ["frames": records,')
    source=replace_once(source, '    private var failure: String?', '    private var failure: String?\n    private var failureObservedMach: UInt64?')
    source=replace_once(source,
        '    func failed(_ code: String) { lock.lock(); if failure == nil { failure = code }; lock.unlock() }',
        '    func failed(_ code: String) {\n        lock.lock()\n        if failure == nil { failure = code; failureObservedMach = mach_absolute_time() }\n        lock.unlock()\n    }\n    func failureSnapshot() -> [String: Any]? {\n        lock.lock(); defer { lock.unlock() }\n        guard let code = failure, let observed = failureObservedMach else { return nil }\n        return ["code": directDiagnosticCode(code), "observedMach": observed]\n    }')
    source=replace_once(source, '    private var pendingRecords = 0', '    private var pendingRecords = 0\n    private static let startupLimit = 8\n    private var startupRecords = (0..<8).map { DirectStartupRecord(index: $0, admitted: false, pendingAtArrival: 0) }\n    private var startupOverflow: DirectStartupOverflow?\n    private var startupAdmitted = 0\n    private var startupReleased = 0\n    private var startupInFlight = [-1, -1]\n    private func startupMark(_ index: Int, _ stage: DirectStartupStage, at tick: UInt64? = nil) {\n        guard index < Self.startupLimit else { return }\n        let markStart = mach_absolute_time()\n        let observed = tick ?? markStart\n        lock.lock(); defer { lock.unlock() }\n        // Each callback creates its own bounded record before any stage marks.\n        guard index < startupRecords.count else { return }\n        startupRecords[index].ticks[stage.rawValue] = observed\n        startupRecords[index].traceMarkCount += 1\n        startupRecords[index].traceMarkCostMach += mach_absolute_time() - markStart\n    }\n    func startupSnapshot() -> [String: Any] {\n        lock.lock()\n        let rows = startupRecords, firstOverflow = startupOverflow\n        let admitted = startupAdmitted, released = startupReleased\n        let inFlight = startupInFlight, pending = pendingRecords\n        let observed = mach_absolute_time()\n        lock.unlock()\n        // Serialization/all dictionary construction is outside the admission lock.\n        return ["schema": "p1-direct-startup-persistence-v1", "session": plan.session,\n                "observedMach": observed, "recordLimit": Self.startupLimit,\n                "stageNames": DirectStartupStage.allCases.map { String(describing: $0) },\n                "missingMilestone": 0, "records": rows.filter { $0.ticks[DirectStartupStage.callbackEntry.rawValue] > 0 }.map { $0.json() },\n                "firstOverflow": firstOverflow.map { $0.json() } as Any? ?? NSNull(),\n                "admitted": admitted, "released": released, "pending": pending,\n                "inFlight": inFlight, "admissionEligible": false]\n    }')
    source=replace_once(source, '        pendingRecords += 1; lock.unlock()', '        pendingRecords += 1\n        startupAdmitted += 1\n        if let slot = startupInFlight.firstIndex(of: -1) { startupInFlight[slot] = delivered - 1 }\n        lock.unlock()')
    source=replace_once(source, '        guard pendingRecords < 2 else { lock.unlock(); overflow += 1; failed("persistence-backpressure"); return }', '        let startupIndex = delivered - 1\n        if startupIndex < Self.startupLimit {\n            startupRecords[startupIndex].admitted = pendingRecords < 2\n            startupRecords[startupIndex].pendingAtArrival = pendingRecords\n            startupRecords[startupIndex].ticks[DirectStartupStage.callbackEntry.rawValue] = callbackBefore\n        }\n        guard pendingRecords < 2 else {\n            if startupOverflow == nil {\n                startupOverflow = DirectStartupOverflow(index: startupIndex, observedMach: mach_absolute_time(),\n                    pending: pendingRecords, admitted: startupAdmitted, released: startupReleased,\n                    inFlight: startupInFlight, records: startupRecords)\n            }\n            lock.unlock(); overflow += 1; failed("persistence-backpressure"); return\n        }')
    source=replace_once(source, '            try require(ownerValid(), "owner-changed")', '            startupMark(startupIndex, .ownerBegin)\n            try require(ownerValid(), "owner-changed")\n            startupMark(startupIndex, .ownerEnd)')
    source=replace_once(source, '                let data = try directCopyROIs(buffer, plan: plan)', '                startupMark(startupIndex, .metadataEnd)\n                startupMark(startupIndex, .copyBegin)\n                let data = try directCopyROIs(buffer, plan: plan, diagnostic: startupIndex < Self.startupLimit ? { [self] stage in startupMark(startupIndex, stage) } : nil)\n                startupMark(startupIndex, .copyEnd)')
    source=replace_once(source, '        let capturedRow = row, captured = DirectPendingPixels(payload)', '        startupMark(startupIndex, .callbackEnd, at: row["callbackAfterMach"] as? UInt64)\n        let capturedRow = row, captured = DirectPendingPixels(payload)')
    source=replace_once(source, '        persistence.async { [self] in', '        startupMark(startupIndex, .enqueueBefore)\n        persistence.async { [self] in\n            startupMark(startupIndex, .writerBegin)')
    source=replace_once(source, '            defer { captured.data = nil; lock.lock(); pendingRecords -= 1; lock.unlock() }', '            defer {\n                startupMark(startupIndex, .writerEnd)\n                captured.data = nil\n                lock.lock()\n                pendingRecords -= 1\n                startupReleased += 1\n                if let slot = startupInFlight.firstIndex(of: startupIndex) { startupInFlight[slot] = -1 }\n                if startupIndex < Self.startupLimit {\n                    startupRecords[startupIndex].ticks[DirectStartupStage.reservationReleased.rawValue] = mach_absolute_time()\n                }\n                lock.unlock()\n            }')
    source=replace_once(source, '                    try require(ownerValid(), "persistence-owner-changed")', '                    startupMark(startupIndex, .writerOwnerBegin)\n                    try require(ownerValid(), "persistence-owner-changed")\n                    startupMark(startupIndex, .writerOwnerEnd)')
    source=replace_once(source, '                    let regions = try directROIManifest(plan, packed: data)', '                    startupMark(startupIndex, .regionHashBegin)\n                    let regions = try directROIManifest(plan, packed: data)\n                    startupMark(startupIndex, .regionHashEnd)')
    source=replace_once(source, '                    try data.write(to: directory.appendingPathComponent(name), options: .atomic)', '                    startupMark(startupIndex, .writeBegin)\n                    try data.write(to: directory.appendingPathComponent(name), options: .atomic)\n                    startupMark(startupIndex, .writeEnd)')
    source=replace_once(source, '                    retained["packedPixelSHA256"] = digest(data)', '                    startupMark(startupIndex, .packedHashBegin)\n                    retained["packedPixelSHA256"] = digest(data)\n                    startupMark(startupIndex, .packedHashEnd)')
    source=replace_once(source, '        }\n    }\n    func firstComplete()', '        }\n        startupMark(startupIndex, .enqueueAfter)\n    }\n    func firstComplete()')
    return '// Generated from the exact reviewed owned-window Sink. Local draft.\n'+source


if __name__=='__main__':
    source=SOURCE.read_text()
    expected=Path(__file__).with_name('source-sha256.txt').read_text().strip()
    Path(__file__).with_name('direct_sink.swift').write_text(build(source,expected))
