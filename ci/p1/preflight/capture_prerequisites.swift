// Read-only prerequisite inspection. Never requests permission or captures pixels.
import AppKit
import CoreGraphics
import Foundation
import ScreenCaptureKit

let permission = CGPreflightScreenCaptureAccess()
if !permission {
    let denied: [String: Any] = [
        "schema": "p1-capture-prerequisites-v1", "screenCapturePreflight": false,
        "enumerationAttempted": false, "permissionRequested": false,
        "pixelsCaptured": false, "environmentModified": false,
        "windowOwnershipEstablished": false, "timestampUnitsEstablished": false,
        "admissionEligible": false
    ]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: denied, options: [.sortedKeys]))
    FileHandle.standardOutput.write(Data([10]))
    exit(0)
}
let simulators = NSWorkspace.shared.runningApplications.filter { $0.bundleIdentifier == "com.apple.iphonesimulator" }
let pids = Set(simulators.map { $0.processIdentifier })
let windowList = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]
let windows = windowList ?? []
let ownedMetadata = windows.filter { row in
    guard let pid = row[kCGWindowOwnerPID as String] as? Int32 else { return false }
    return pids.contains(pid)
}
// The API may return titles/other metadata transiently. Do not read or emit them.
// No image buffers or audio are requested.
let result: [String: Any] = [
    "schema": "p1-capture-prerequisites-v1",
    "screenCapturePreflight": permission,
    "enumerationAttempted": true,
    "simulatorProcessCount": simulators.count,
    "simulatorOnScreenWindowCount": ownedMetadata.count,
    "windowEnumerationAvailable": windowList != nil,
    "permissionRequested": false,
    "pixelsCaptured": false,
    "environmentModified": false,
    "windowOwnershipEstablished": false,
    "timestampUnitsEstablished": false,
    "admissionEligible": false
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data([10]))
