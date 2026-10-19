// Resize only the already-owned Simulator window before immutable registration.
// Existing accessibility trust is required; this helper never requests it.
import ApplicationServices

func directAXRect(_ element: AXUIElement) throws -> CGRect {
    var position: CFTypeRef?, size: CFTypeRef?
    try require(AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success &&
                AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success,
                "owned-window-ax-geometry-unavailable")
    guard let p = position, let s = size,
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else {
        throw Failure("owned-window-ax-geometry-type")
    }
    var point = CGPoint.zero, dimensions = CGSize.zero
    try require(AXValueGetValue(p as! AXValue, .cgPoint, &point) &&
                AXValueGetValue(s as! AXValue, .cgSize, &dimensions), "owned-window-ax-geometry-value")
    let frame = CGRect(origin: point, size: dimensions)
    try require(valid(frame), "owned-window-ax-invalid-frame")
    return frame
}

@MainActor func directResizeOwnedWindow(_ window: SCWindow, owner: DirectOwner,
    pid: pid_t, directory: URL, select: (CGWindowID?, String) async throws -> SCWindow) async throws -> SCWindow {
    var proof: [String: Any] = ["schema": "p1-direct-owned-window-resize-v1",
        "ownerPID": pid, "windowID": window.windowID, "beforeFrame": rect(window.frame),
        "requestedSize": [700, 1550], "permissionRequested": false,
        "sourceResolutionEstablished": false, "admissionEligible": false]
    let path = directory.appendingPathComponent("window-resize.json")
    let trusted = AXIsProcessTrusted()
    proof["existingAccessibilityTrust"] = trusted
    try write(proof, path)
    try require(trusted, "existing-accessibility-trust-absent")
    try require(owner.valid(), "resize-owner-changed")
    let app = AXUIElementCreateApplication(pid)
    try require(AXUIElementSetMessagingTimeout(app, 2) == .success, "owned-ax-timeout-unavailable")
    var value: CFTypeRef?
    try require(AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &value) == .success,
                "owned-ax-windows-unavailable")
    guard let windows = value as? [AXUIElement], windows.count == 1 else {
        throw Failure("ambiguous-owned-ax-window")
    }
    let target = windows[0]
    try require(AXUIElementSetMessagingTimeout(target, 2) == .success, "owned-window-ax-timeout-unavailable")
    var axPID: pid_t = 0
    try require(AXUIElementGetPid(target, &axPID) == .success && axPID == pid,
                "owned-ax-window-pid-mismatch")
    try require(try directAXRect(target) == window.frame, "owned-ax-window-frame-mismatch")
    var settable = DarwinBoolean(false)
    try require(AXUIElementIsAttributeSettable(target, kAXSizeAttribute as CFString, &settable) == .success &&
                settable.boolValue, "owned-window-size-not-settable")
    try require(owner.valid(), "resize-owner-changed")
    var requested = CGSize(width: 700, height: 1550)
    if window.frame.size == requested {
        proof["mutationAttempted"] = false
        proof["alreadyRequestedSize"] = true
        proof["afterFrame"] = rect(window.frame)
        proof["sameOwnedWindowSettled"] = true
        try write(proof, path)
        return window
    }
    guard let sizeValue = AXValueCreate(.cgSize, &requested) else { throw Failure("owned-window-size-value") }
    proof["mutationAttempted"] = true
    try write(proof, path)
    try require(AXUIElementSetAttributeValue(target, kAXSizeAttribute as CFString, sizeValue) == .success,
                "owned-window-resize-failed")
    var prior: CGRect?
    // The caller's unchanged observation deadline independently bounds this
    // loop and all AX/ScreenCaptureKit callbacks. No resize retry is performed.
    while true {
        try require(owner.valid(), "resize-owner-changed")
        let current = try await select(window.windowID, "resized")
        try require(current.frame.width <= 2048 && current.frame.height <= 2048,
                    "resized-window-outside-bounds")
        let axFrame = try directAXRect(target)
        if current.frame == prior && current.frame == axFrame && current.frame != window.frame {
            proof["afterFrame"] = rect(current.frame)
            proof["sameOwnedWindowSettled"] = true
            try write(proof, path)
            return current
        }
        prior = current.frame
        try await Task.sleep(nanoseconds: 100_000_000)
    }
}
