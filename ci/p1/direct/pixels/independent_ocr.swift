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
var independent: [[String: Any]] = []
for (index,row) in (input["independentScreenshots"] as! [[String: Any]]).enumerated() {
    let url = URL(fileURLWithPath: row["path"] as! String)
    guard let source = CGImageSourceCreateWithURL(url as CFURL,nil), let image = CGImageSourceCreateImageAtIndex(source,0,nil) else { throw NSError(domain:"P1Video",code:4) }
    var result = try inspect(image,index:20001+index)
    result["phase"] = row["phase"]; result["path"] = row["path"]
    result["decodedMarker"] = markerID(image) as Any? ?? NSNull()
    independent.append(result)
}

let report: [String: Any] = ["schema": "p1-direct-independent-screenshots-v1",
    "independentScreenshots": independent, "admissionEligible": false,
    "scope": "original-independent-steady-state-pixels-only"]
try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]).write(to: URL(fileURLWithPath: args[3]), options: .atomic)
