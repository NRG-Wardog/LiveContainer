import Foundation
import AVFoundation
import CoreImage
import CoreMedia
import Vision
import ImageIO
import UniformTypeIdentifiers

// Offline decoding of actual externally recorded video. All presentation times
// and all marker matches are retained. No expected timer state supplies labels.
let args = CommandLine.arguments
precondition(args.count == 4, "decode input.json output-directory output.json")
let input = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[1]))) as! [String: Any]
let output = URL(fileURLWithPath: args[2], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: false)
let marker = input["markerRectPixels"] as! [Double]
let copy = input["copyRectPixels"] as! [Double]
let expectedSize = input["pixelSize"] as! [Int]
let crop = CGRect(x: copy[0], y: copy[1], width: copy[2], height: copy[3]).integral
let ci = CIContext(options: [.cacheIntermediates: false])
func save(_ image: CGImage, _ name: String) throws {
    let url = output.appendingPathComponent(name)
    guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else { throw NSError(domain: "P1Video", code: 1) }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else { throw NSError(domain: "P1Video", code: 2) }
}
func markerBits(width w: Int, height h: Int, pixel: (Int, Int) -> [UInt8]) -> Int? {
    var bits: [Bool] = []
    for cell in 0..<24 {
        let x = Int(marker[0] + marker[2] * (Double(cell)+0.5)/24)
        let y = Int(marker[1] + marker[3]/2)
        guard x >= 0 && y >= 0 && x < w && y < h else { return nil }
        let channels = pixel(x,y)
        if channels.allSatisfy({$0 < 50}) { bits.append(false) }
        else if channels.allSatisfy({$0 > 205}) { bits.append(true) }
        else { return nil }
    }
    guard Array(bits[0..<4]) == [false,true,false,true], Array(bits[20..<24]) == [true,false,true,false] else { return nil }
    return (0..<16).reduce(0) { $0 | (bits[$1+4] ? 1 << $1 : 0) }
}
func markerID(_ image: CGImage) -> Int? {
    let w = image.width, h = image.height
    var pixels = [UInt8](repeating: 0, count: w*h*4)
    guard let context = CGContext(data: &pixels, width: w, height: h, bitsPerComponent: 8,
            bytesPerRow: w*4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    context.draw(image, in: CGRect(x: 0, y: 0, width: CGFloat(w), height: CGFloat(h)))
    return markerBits(width:w,height:h) { x,y in
        let i=(y*w+x)*4;return [pixels[i],pixels[i+1],pixels[i+2]]
    }
}
func markerID(_ buffer: CVPixelBuffer) -> Int? {
    guard CVPixelBufferGetPixelFormatType(buffer) == kCVPixelFormatType_32BGRA else { return nil }
    CVPixelBufferLockBaseAddress(buffer,.readOnly)
    defer { CVPixelBufferUnlockBaseAddress(buffer,.readOnly) }
    guard let base=CVPixelBufferGetBaseAddress(buffer)?.assumingMemoryBound(to:UInt8.self) else { return nil }
    let stride=CVPixelBufferGetBytesPerRow(buffer)
    return markerBits(width:CVPixelBufferGetWidth(buffer),height:CVPixelBufferGetHeight(buffer)) { x,y in
        let i=y*stride+x*4;return [base[i],base[i+1],base[i+2]]
    }
}
func inspect(_ image: CGImage, index: Int) throws -> [String: Any] {
    guard image.width == expectedSize[0] && image.height == expectedSize[1],
          CGRect(x:0,y:0,width:CGFloat(image.width),height:CGFloat(image.height)).contains(crop),
          let cropped = image.cropping(to: crop) else { throw NSError(domain: "P1Video", code: 3) }
    let request = VNRecognizeTextRequest(); request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]; request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: cropped).perform([request])
    let observations: [[String: Any]] = (request.results ?? []).compactMap { row in
        guard let text = row.topCandidates(1).first else { return nil }
        return ["text": text.string, "confidence": text.confidence,
                "box": [row.boundingBox.minX,row.boundingBox.minY,row.boundingBox.width,row.boundingBox.height]]
    }
    let recognized = observations.filter { ($0["confidence"] as? Float ?? 0) >= 0.9 }
        .compactMap { $0["text"] as? String }
    let label = recognized.count == 1 && ["Copied", "Copy Details"].contains(recognized[0]) ? recognized[0] : "unknown"
    let name = String(format: "label-%05d.png", index)
    try save(cropped, name)
    return ["label": label, "observations": observations, "cropFile": name]
}
var screenshots: [[String: Any]] = []
for row in input["screenshots"] as! [[String: Any]] {
    let url = URL(fileURLWithPath: row["path"] as! String)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil), let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
          image.width == expectedSize[0], image.height == expectedSize[1] else { throw NSError(domain:"P1Video",code:4) }
    screenshots.append(["id": row["id"]!, "path": row["path"]!, "decodedMarker": markerID(image) as Any? ?? NSNull()])
}
var independent: [[String: Any]] = []
for (index,row) in (input["independentScreenshots"] as! [[String: Any]]).enumerated() {
    let url = URL(fileURLWithPath: row["path"] as! String)
    guard let source = CGImageSourceCreateWithURL(url as CFURL,nil), let image = CGImageSourceCreateImageAtIndex(source,0,nil) else { throw NSError(domain:"P1Video",code:4) }
    var result = try inspect(image,index:20001+index)
    result["phase"] = row["phase"]; result["path"] = row["path"]
    independent.append(result)
}
let asset = AVURLAsset(url: URL(fileURLWithPath: input["video"] as! String))
guard let track = asset.tracks(withMediaType: .video).first else { throw NSError(domain:"P1Video",code:5) }
guard track.preferredTransform == .identity else { throw NSError(domain:"P1Video",code:6,userInfo:[NSLocalizedDescriptionKey:"unexpected video transform"] ) }
let reader = try AVAssetReader(asset: asset)
let trackOutput = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA])
trackOutput.alwaysCopiesSampleData = false
reader.add(trackOutput); guard reader.startReading() else { throw reader.error! }
var frames: [[String: Any]] = []; var observations: [[String: Any]] = []
var previousPTS: Double?; var lastSample = -Double.infinity
var previousLabel = ""; var index = 0
while let sample = trackOutput.copyNextSampleBuffer() {
    try autoreleasepool {
        let time = CMSampleBufferGetPresentationTimeStamp(sample)
        let pts = CMTimeGetSeconds(time)
        guard pts.isFinite, previousPTS.map({pts > $0}) ?? true, index < 18000,
              let buffer = CMSampleBufferGetImageBuffer(sample) else { throw NSError(domain:"P1Video",code:7) }
        if !frames.isEmpty { frames[frames.count-1]["endPTS"] = pts }
        if !observations.isEmpty && observations.last?["endPTS"] == nil { observations[observations.count-1]["endPTS"] = pts }
        guard CVPixelBufferGetWidth(buffer) == expectedSize[0], CVPixelBufferGetHeight(buffer) == expectedSize[1] else { throw NSError(domain:"P1Video",code:8) }
        let id = markerID(buffer)
        frames.append(["index":index,"pts":pts,"ptsValue":time.value,"ptsTimescale":time.timescale,"marker":id as Any? ?? NSNull()])
        if pts - lastSample >= 0.045 {
            let frame = CIImage(cvPixelBuffer: buffer)
            guard let image = ci.createCGImage(frame, from: frame.extent) else { throw NSError(domain:"P1Video",code:8) }
            var row = try inspect(image,index:index); row["index"] = index; row["pts"] = pts
            let label = row["label"] as! String
            if label != previousLabel || observations.isEmpty {
                let name = String(format:"full-%05d.png",index); try save(image,name); row["fullFrameFile"] = name
                previousLabel = label
            }
            observations.append(row); lastSample = pts
        }
        previousPTS = pts; index += 1
    }
}
guard reader.status == .completed else { throw reader.error ?? NSError(domain:"P1Video",code:9) }
// The last frame has no following presentation timestamp: it supplies neither
// calibration nor timing evidence. Raw video retains it for inspection.
if !frames.isEmpty { frames.removeLast() }
observations.removeAll { $0["endPTS"] == nil }
let report: [String: Any] = ["schema":"p1-video-decoded-v1","frames":frames,"observations":observations,
    "screenshots":screenshots,"independentScreenshots":independent,"pixelSize":expectedSize,"admissionEligible":false,
    "sampling":"actual presentation timestamps; OCR at most ~22 Hz; every video frame indexed"]
try JSONSerialization.data(withJSONObject:report,options:[.sortedKeys,.prettyPrinted]).write(to:URL(fileURLWithPath:args[3]),options:.atomic)
