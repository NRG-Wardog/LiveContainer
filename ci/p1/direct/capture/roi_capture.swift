// Local adapter draft. Requires the reviewed owned-window lifecycle and Failure,
// require, digest, rect and valid helpers. This file grants no admission itself.
import AppKit
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import CryptoKit

// Diagnostic-only startup trace. Fixed numeric storage, no pixels or framework text.
// All mutation/snapshot copying is protected by the sink's existing admission lock.
enum DirectStartupStage: Int, CaseIterable {
    case callbackEntry, ownerBegin, ownerEnd, metadataEnd, copyBegin
    case bufferLockBegin, bufferLockEnd, rowCopyEnd, bufferUnlockEnd, copyEnd
    case callbackEnd, enqueueBefore, enqueueAfter, writerBegin, writerOwnerBegin, writerOwnerEnd
    case regionHashBegin, regionHashEnd, writeBegin, writeEnd, packedHashBegin, packedHashEnd
    case writerEnd, reservationReleased
}
struct DirectStartupRecord {
    let index: Int
    var admitted: Bool
    var pendingAtArrival: Int
    var traceMarkCount = 0
    var traceMarkCostMach: UInt64 = 0
    var ticks = [UInt64](repeating: 0, count: DirectStartupStage.allCases.count)
    func json() -> [String: Any] {
        return ["index": index, "admitted": admitted, "pendingAtArrival": pendingAtArrival,
                "milestonesMach": ticks, "traceMarkCount": traceMarkCount,
                "traceMarkCostMach": traceMarkCostMach]
    }
}
struct DirectStartupOverflow {
    let index: Int
    let observedMach: UInt64
    let pending: Int
    let admitted: Int
    let released: Int
    let inFlight: [Int]
    let records: [DirectStartupRecord]
    func json() -> [String: Any] {
        return ["index": index, "observedMach": observedMach, "pending": pending,
                "admitted": admitted, "released": released, "inFlight": inFlight,
                "records": records.filter { $0.ticks[DirectStartupStage.callbackEntry.rawValue] > 0 }.map { $0.json() }]
    }
}

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
func directCopyROIs(_ buffer: CVPixelBuffer, plan: DirectROIPlan, diagnostic: ((DirectStartupStage) -> Void)? = nil) throws -> Data {
    try plan.validate()
    try require(CVPixelBufferGetWidth(buffer) == plan.sourceWidth &&
                CVPixelBufferGetHeight(buffer) == plan.sourceHeight &&
                CVPixelBufferGetBytesPerRow(buffer) == plan.sourceStride &&
                CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA,
                "roi-source-replacement")
    diagnostic?(.bufferLockBegin)
    try require(CVPixelBufferLockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "roi-lock-failed")
    diagnostic?(.bufferLockEnd)
    var data = Data(capacity: plan.byteCount)
    do {
        guard let base = CVPixelBufferGetBaseAddress(buffer) else { throw Failure("roi-address-missing") }
        for region in plan.regions {
            for row in region.y ..< region.y + region.height {
                let source = base.advanced(by: row * plan.sourceStride + region.x * 4)
                data.append(source.assumingMemoryBound(to: UInt8.self), count: region.width * 4)
            }
        }
        diagnostic?(.rowCopyEnd)
    } catch {
        CVPixelBufferUnlockBaseAddress(buffer, .readOnly)
        throw error
    }
    try require(CVPixelBufferUnlockBaseAddress(buffer, .readOnly) == kCVReturnSuccess, "roi-unlock-failed")
    diagnostic?(.bufferUnlockEnd)
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
