import Foundation
import Vision
import ImageIO

// Offline OCR only. No expected feedback state or timing acceptance is inferred.
let arguments = CommandLine.arguments
precondition(arguments.count == 3, "vision.swift manifest.json output.json")
let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: arguments[1]))) as! [String]
var results: [[String: Any]] = []
for name in manifest {
    let url = URL(fileURLWithPath: name)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(url: url).perform([request])
    let source = CGImageSourceCreateWithURL(url as CFURL, nil)!
    let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil)! as NSDictionary
    let rows: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": text.string, "confidence": text.confidence,
                "boundingBox": [box.minX, box.minY, box.width, box.height]]
    }
    results.append(["path": name, "width": properties[kCGImagePropertyPixelWidth]!,
                    "height": properties[kCGImagePropertyPixelHeight]!, "observations": rows])
}
let data = try JSONSerialization.data(withJSONObject: ["schema": "p1-probe-ocr-v1",
    "diagnosticOnly": true, "admissionEligible": false, "frames": results], options: [.prettyPrinted, .sortedKeys])
try data.write(to: URL(fileURLWithPath: arguments[2]), options: .atomic)
