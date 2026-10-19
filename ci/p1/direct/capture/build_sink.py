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
    return '// Generated from the exact reviewed owned-window Sink. Local draft.\n'+source


if __name__=='__main__':
    source=SOURCE.read_text()
    expected=Path(__file__).with_name('source-sha256.txt').read_text().strip()
    Path(__file__).with_name('direct_sink.swift').write_text(build(source,expected))
