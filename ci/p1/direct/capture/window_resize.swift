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

func directAXValue(_ element: AXUIElement, _ attribute: String) throws -> CFTypeRef {
    var value: CFTypeRef?
    try require(AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success,
                "owned-ax-attribute-unavailable")
    guard let value = value else { throw Failure("owned-ax-empty-attribute") }
    return value
}

func directAXChildren(_ element: AXUIElement) throws -> [AXUIElement] {
    guard let values = try directAXValue(element, kAXChildrenAttribute) as? [AXUIElement], values.count <= 128 else {
        throw Failure("owned-menu-children-unavailable-or-overflow")
    }
    return values
}

func directAXText(_ element: AXUIElement, _ attribute: String) throws -> String {
    guard let value = try directAXValue(element, attribute) as? String, value.utf8.count <= 256 else {
        throw Failure("owned-menu-text-invalid")
    }
    return value
}

func directAXOptionalTitle(_ element: AXUIElement) throws -> String {
    var value: CFTypeRef?
    let status = AXUIElementCopyAttributeValue(element, kAXTitleAttribute as CFString, &value)
    if status == .noValue || status == .attributeUnsupported { return "" }
    try require(status == .success, "owned-menu-title-unavailable")
    guard let title = value as? String, title.utf8.count <= 256 else { throw Failure("owned-menu-title-invalid") }
    return title
}

@MainActor func directResizeOwnedWindow(_ window: SCWindow, owner: DirectOwner,
    pid: pid_t, directory: URL, select: (CGWindowID?, String) async throws -> SCWindow) async throws -> SCWindow {
    var proof: [String: Any] = ["schema": "p1-direct-owned-window-resize-v1",
        "ownerPID": pid, "windowID": window.windowID, "beforeFrame": rect(window.frame),
        "requestedPreset": "Pixel Accurate", "permissionRequested": false,
        "sourceResolutionEstablished": false, "admissionEligible": false]
    let path = directory.appendingPathComponent("window-resize.json")
    let trusted = AXIsProcessTrusted()
    proof["existingAccessibilityTrust"] = trusted
    try write(proof, path)
    try require(trusted, "existing-accessibility-trust-absent")
    try require(owner.valid(), "resize-owner-changed")
    let app = AXUIElementCreateApplication(pid)
    try require(AXUIElementSetMessagingTimeout(app, 2) == .success, "owned-ax-timeout-unavailable")
    guard let windows = try directAXValue(app, kAXWindowsAttribute) as? [AXUIElement], windows.count == 1 else {
        throw Failure("ambiguous-owned-ax-window")
    }
    let target = windows[0]
    try require(AXUIElementSetMessagingTimeout(target, 2) == .success, "owned-window-ax-timeout-unavailable")
    var axPID: pid_t = 0
    try require(AXUIElementGetPid(target, &axPID) == .success && axPID == pid,
                "owned-ax-window-pid-mismatch")
    try require(try directAXRect(target) == window.frame, "owned-ax-window-frame-mismatch")
    func requireMainWindow() throws {
        guard let current = try directAXValue(app, kAXWindowsAttribute) as? [AXUIElement],
              current.count == 1, CFEqual(current[0], target) else {
            throw Failure("owned-window-set-changed")
        }
        for attribute in [kAXMainWindowAttribute, kAXFocusedWindowAttribute] {
            let value = try directAXValue(app, attribute)
            try require(CFGetTypeID(value) == AXUIElementGetTypeID() && CFEqual(value, target),
                        "owned-main-focused-window-mismatch")
        }
    }
    try requireMainWindow()
    let rawBar = try directAXValue(app, kAXMenuBarAttribute)
    try require(CFGetTypeID(rawBar) == AXUIElementGetTypeID(), "owned-menubar-type")
    let bar = rawBar as! AXUIElement
    let matching = try directAXChildren(bar).filter { try directAXOptionalTitle($0) == "Window" }
    proof["matchingWindowMenus"] = matching.count
    try write(proof, path)
    try require(matching.count == 1, "owned-window-menu-unavailable-or-ambiguous")
    let menus = try directAXChildren(matching[0]).filter { try directAXText($0, kAXRoleAttribute) == kAXMenuRole }
    try require(menus.count == 1, "owned-window-submenu-unavailable-or-ambiguous")
    let presets = try directAXChildren(menus[0]).filter { try directAXOptionalTitle($0) == "Pixel Accurate" }
    proof["matchingPixelAccurateItems"] = presets.count
    try write(proof, path)
    try require(presets.count == 1, "owned-pixel-accurate-unavailable-or-ambiguous")
    let preset = presets[0]
    try require(try directAXText(preset, kAXRoleAttribute) == kAXMenuItemRole, "owned-preset-role")
    let enabled = try directAXValue(preset, kAXEnabledAttribute)
    try require(CFGetTypeID(enabled) == CFBooleanGetTypeID() && CFBooleanGetValue((enabled as! CFBoolean)),
                "owned-preset-disabled")
    var actions: CFArray?
    try require(AXUIElementCopyActionNames(preset, &actions) == .success,
                "owned-preset-actions-unavailable")
    guard let names = actions as? [String], names.count <= 32,
          names.filter({ $0 == kAXPressAction }).count == 1 else {
        throw Failure("owned-preset-press-not-advertised")
    }
    var menuPID: pid_t = 0
    try require(AXUIElementGetPid(preset, &menuPID) == .success && menuPID == pid,
                "owned-preset-pid-mismatch")
    try require(owner.valid(), "resize-owner-changed")
    try requireMainWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-before-action")
    proof["mutationAttempted"] = true
    try write(proof, path)
    // One documented preset on the exact owned application's current window.
    // No global keystroke, activation, resize retry, or permission request.
    let actionStatus = AXUIElementPerformAction(preset, kAXPressAction as CFString)
    proof["actionAXError"] = actionStatus.rawValue
    try write(proof, path)
    try require(actionStatus == .success, "owned-pixel-accurate-action-failed")
    var prior: CGRect?
    while true {
        try require(owner.valid(), "resize-owner-changed")
        try requireMainWindow()
        let current = try await select(window.windowID, "resized")
        try require(current.frame.width <= 4096 && current.frame.height <= 4096,
                    "resized-source-window-outside-bounds")
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
