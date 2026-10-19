// Offline classification of retained control pixels only. No expected app state
// supplies a label. Unknown OCR stays unknown; it is never dismissal evidence.
import Foundation
import CoreGraphics
import CoreFoundation
import ImageIO
import Vision
import CryptoKit
import Darwin

struct DecodeFailure: Error { let reason: String }
func require(_ ok: Bool, _ reason: String) throws { if !ok { throw DecodeFailure(reason: reason) } }
func integer(_ value: Any?, maximum: Int) throws -> Int {
    guard let number = value as? NSNumber,
          CFGetTypeID(number) != CFBooleanGetTypeID(),
          let result = Int(number.stringValue), result >= 0, result <= maximum else {
        throw DecodeFailure(reason: "bounded exact integer")
    }
    return result
}
func read(_ root: URL, _ name: String, maximum: Int) throws -> Data {
    try require(!name.isEmpty && !name.contains("/") && name != "." && name != "..", "leaf path")
    let fd = open(root.appendingPathComponent(name).path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
    try require(fd >= 0, "open retained file")
    defer { close(fd) }
    var before = stat()
    try require(fstat(fd, &before) == 0 && (before.st_mode & S_IFMT) == S_IFREG && before.st_nlink == 1 && before.st_size > 0 && before.st_size <= maximum, "bounded retained regular file")
    var bytes = [UInt8](repeating: 0, count: Int(before.st_size))
    let count = bytes.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress, $0.count) }
    var after = stat()
    try require(count == bytes.count && fstat(fd, &after) == 0 && before.st_dev == after.st_dev &&
                before.st_ino == after.st_ino && before.st_size == after.st_size &&
                before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec &&
                before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec && before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec,
                "retained bytes changed or short read")
    return Data(bytes)
}
func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
func inspect(_ raw: Data, width: Int, height: Int) throws -> [String: Any] {
    try require(width > 0 && height > 0 && raw.count == width * height * 4, "control pixel layout")
    try require(stride(from: 3, to: raw.count, by: 4).allSatisfy { raw[$0] == 255 }, "nonopaque control pixel")
    guard let provider = CGDataProvider(data: raw as CFData),
          let space = CGColorSpace(name: CGColorSpace.sRGB),
          let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                              bytesPerRow: width * 4, space: space,
                              bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedFirst.rawValue).union(.byteOrder32Little),
                              provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else {
        throw DecodeFailure(reason: "control image unavailable")
    }
    let request = VNRecognizeTextRequest(); request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]; request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image, orientation: .up).perform([request])
    let observations: [[String: Any]] = (request.results ?? []).compactMap { row in
        guard let text = row.topCandidates(1).first else { return nil }
        return ["text": text.string, "confidence": text.confidence,
                "box": [row.boundingBox.minX,row.boundingBox.minY,row.boundingBox.width,row.boundingBox.height]]
    }
    let recognized = observations.filter { ($0["confidence"] as? Float ?? 0) >= 0.9 }
        .compactMap { $0["text"] as? String }
    let label = recognized.count == 1 && ["Copied", "Copy Details"].contains(recognized[0]) ? recognized[0] : "unknown"
    return ["label": label, "observations": observations, "controlSHA256": hash(raw),
            "pixelSize": [width, height], "resampled": false, "absenceEstablished": false]
}

let args = CommandLine.arguments
try require(args.count == 4, "input directory output")
let inputURL = URL(fileURLWithPath: args[1]), root = URL(fileURLWithPath: args[2], isDirectory: true)
try require(root.standardizedFileURL == root.resolvingSymlinksInPath(), "canonical retained root")
let inputBytes = try read(inputURL.deletingLastPathComponent(), inputURL.lastPathComponent, maximum: 8 * 1024 * 1024)
guard let input = try JSONSerialization.jsonObject(with: inputBytes) as? [String: Any],
      Set(input.keys) == ["schema", "session", "frames"], input["schema"] as? String == "p1-direct-control-ocr-input-v1",
      let session = input["session"] as? String,
      let frames = input["frames"] as? [[String: Any]] else { throw DecodeFailure(reason: "input schema") }
let canonicalInput = try JSONSerialization.data(withJSONObject: input, options: [.sortedKeys, .withoutEscapingSlashes])
try require(canonicalInput == inputBytes, "canonical unique OCR manifest")
try require(session.utf8.count == 32 && session.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) } && !frames.isEmpty && frames.count <= 6000, "session/frame inventory")
var results: [[String: Any]] = []; var previous = 0; var totalPackedBytes = 0
for frame in frames {
    try autoreleasepool {
        try require(Set(frame.keys) == ["record", "file", "packedSHA256", "offset", "width", "height", "controlSHA256"], "frame schema")
        let record = try integer(frame["record"], maximum: 6000)
        let offset = try integer(frame["offset"], maximum: 1024 * 1024)
        let width = try integer(frame["width"], maximum: 2048), height = try integer(frame["height"], maximum: 2048)
        try require(record > previous && width > 0 && height > 0, "ordered frame/layout")
        guard let name = frame["file"] as? String else { throw DecodeFailure(reason: "frame name") }
        try require(name == String(format: "frame-%05d.rois.bgra", record - 1), "exact frame filename")
        let packed = try read(root, name, maximum: 1024 * 1024)
        try require(totalPackedBytes <= 3 * 1024 * 1024 * 1024 - packed.count, "cumulative packed-byte limit")
        totalPackedBytes += packed.count
        try require(hash(packed) == frame["packedSHA256"] as? String && offset <= packed.count && width * height * 4 <= packed.count - offset, "packed pixel binding")
        let control = packed.subdata(in: offset..<(offset + width * height * 4))
        try require(hash(control) == frame["controlSHA256"] as? String, "control pixel binding")
        var result = try inspect(control, width: width, height: height)
        result["record"] = record; result["file"] = name; result["packedSHA256"] = hash(packed)
        results.append(result); previous = record
    }
}
let output: [String: Any] = ["schema": "p1-direct-control-ocr-v1", "session": session,
    "inputSHA256": hash(inputBytes), "frames": results, "admissionEligible": false,
    "scope": "offline-retained-control-labels-only", "allFramesClassified": results.count == frames.count]
try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]).write(to: URL(fileURLWithPath: args[3]), options: .atomic)
