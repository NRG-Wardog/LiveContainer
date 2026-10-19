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
    try require(AXUIElementSetMessagingTimeout(element, 2) == .success, "owned-element-ax-timeout-unavailable")
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
    try require(AXUIElementSetMessagingTimeout(element, 2) == .success, "owned-element-ax-timeout-unavailable")
    var value: CFTypeRef?
    let status = AXUIElementCopyAttributeValue(element, kAXTitleAttribute as CFString, &value)
    if status == .noValue || status == .attributeUnsupported { return "" }
    try require(status == .success, "owned-menu-title-unavailable")
    guard let title = value as? String, title.utf8.count <= 256 else { throw Failure("owned-menu-title-invalid") }
    return title
}

func directEnabledSnapshot(_ element: AXUIElement, label: String,
                           proof: inout [String: Any], path: URL) throws -> Bool? {
    try require(AXUIElementSetMessagingTimeout(element, 2) == .success, "owned-element-ax-timeout-unavailable")
    var value: CFTypeRef?
    let status = AXUIElementCopyAttributeValue(element, kAXEnabledAttribute as CFString, &value)
    proof[label + "AXError"] = status.rawValue
    proof[label + "TypeID"] = value.map { CFGetTypeID($0) } ?? 0
    let booleanType = value.map { CFGetTypeID($0) == CFBooleanGetTypeID() } ?? false
    proof[label + "TypeIsBoolean"] = booleanType
    var result: Bool?
    if status == .success, booleanType, let value = value {
        result = CFBooleanGetValue((value as! CFBoolean))
        proof[label + "Boolean"] = result!
    }
    try write(proof, path)
    return result
}

func directRequirePress(_ element: AXUIElement, pid: pid_t) throws {
    try require(AXUIElementSetMessagingTimeout(element, 2) == .success, "owned-element-ax-timeout-unavailable")
    var actions: CFArray?
    try require(AXUIElementCopyActionNames(element, &actions) == .success,
                "owned-menu-actions-unavailable")
    guard let names = actions as? [String], names.count <= 32,
          names.filter({ $0 == kAXPressAction }).count == 1 else {
        throw Failure("owned-menu-press-not-advertised")
    }
    var sourcePID: pid_t = 0
    try require(AXUIElementGetPid(element, &sourcePID) == .success && sourcePID == pid,
                "owned-menu-action-pid-mismatch")
}

@MainActor func directActivateOwnedApplication(pid: pid_t, owner: DirectOwner,
    target: AXUIElement, window: SCWindow, proof: inout [String: Any], path: URL,
    validateWindow: () throws -> Void) throws -> NSRunningApplication {
    // A synchronous, bounded UI phase on the main thread. No async suspension
    // can change the run loop while refreshing AppKit's active-state cache.
    try require(Thread.isMainThread, "owned-activation-main-thread-required")
    guard let ownedApplication = NSRunningApplication(processIdentifier: pid) else {
        throw Failure("owned-application-unavailable")
    }
    proof["ownerActiveBefore"] = ownedApplication.isActive
    proof["activationAttempted"] = false
    try write(proof, path)
    if !ownedApplication.isActive {
        try require(owner.valid(), "activation-owner-changed")
        try validateWindow()
        proof["activationAttempted"] = true
        try write(proof, path)
        let accepted = ownedApplication.activate(options: [])
        proof["activationRequestAccepted"] = accepted
        try write(proof, path)
        try require(accepted, "owned-application-activation-rejected")
        while !ownedApplication.isActive {
            try require(owner.valid(), "activation-owner-changed")
            CFRunLoopRunInMode(CFRunLoopMode.defaultMode, 0.02, true)
        }
    }
    try require(owner.valid(), "activation-owner-changed")
    try validateWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-during-activation")
    proof["ownerActiveAfter"] = ownedApplication.isActive
    try write(proof, path)
    return ownedApplication
}

@MainActor func directResizeOwnedWindow(_ window: SCWindow, owner: DirectOwner,
    pid: pid_t, session: String, directory: URL, select: (CGWindowID?, String) async throws -> SCWindow) async throws -> SCWindow {
    try require(Thread.isMainThread, "owned-menu-main-thread-required")
    var proof: [String: Any] = ["schema": "p1-direct-owned-window-resize-v1",
        "session": session, "ownerPID": pid, "windowID": window.windowID, "beforeFrame": rect(window.frame),
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
    let ownedApplication = try directActivateOwnedApplication(pid: pid, owner: owner,
        target: target, window: window, proof: &proof, path: path, validateWindow: requireMainWindow)
    let rawBar = try directAXValue(app, kAXMenuBarAttribute)
    try require(CFGetTypeID(rawBar) == AXUIElementGetTypeID(), "owned-menubar-type")
    let bar = rawBar as! AXUIElement
    let matching = try directAXChildren(bar).filter { try directAXOptionalTitle($0) == "Window" }
    proof["matchingWindowMenus"] = matching.count
    try write(proof, path)
    try require(matching.count == 1, "owned-window-menu-unavailable-or-ambiguous")
    let menus = try directAXChildren(matching[0]).filter { try directAXText($0, kAXRoleAttribute) == kAXMenuRole }
    try require(menus.count == 1, "owned-window-submenu-unavailable-or-ambiguous")
    try require(try directAXText(matching[0], kAXRoleAttribute) == kAXMenuBarItemRole,
                "owned-window-menu-role")
    let presets = try directAXChildren(menus[0]).filter { try directAXOptionalTitle($0) == "Pixel Accurate" }
    proof["route"] = "direct-enabled-preset-item-v1"
    proof["menuOpenAttempted"] = false
    proof["menuNotificationEvidenceClaimed"] = false
    proof["matchingPixelAccurateItems"] = presets.count
    try write(proof, path)
    try require(presets.count == 1, "owned-pixel-accurate-unavailable-or-ambiguous")
    let preset = presets[0]
    try require(try directAXText(preset, kAXRoleAttribute) == kAXMenuItemRole, "owned-preset-role")
    let enabled = try directEnabledSnapshot(preset, label: "directPresetEnabled", proof: &proof, path: path)
    try require(enabled == true, "owned-preset-disabled-or-unknown")
    try directRequirePress(preset, pid: pid)
    try require(owner.valid(), "resize-owner-changed")
    try requireMainWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-before-action")
    try require(ownedApplication.isActive, "owned-application-inactive-before-preset")
    proof["mutationAttempted"] = true
    proof["presetAttemptMach"] = mach_absolute_time()
    try write(proof, path)
    // One advertised action on the already-enabled exact owned preset.
    // No menu-opening action, notification assumption, retry or global input.
    let actionStatus = AXUIElementPerformAction(preset, kAXPressAction as CFString)
    proof["actionAXError"] = actionStatus.rawValue
    try write(proof, path)
    try require(actionStatus == .success, "owned-pixel-accurate-action-failed")
    var prior: CGRect?
    while true {
        try require(owner.valid(), "resize-owner-changed")
        try requireMainWindow()
        let current = try await select(window.windowID, "resized")
        try require(owner.valid(), "resize-owner-changed-after-selection")
        try requireMainWindow()
        try require(current.frame.width <= 4096 && current.frame.height <= 4096,
                    "resized-source-window-outside-bounds")
        try require(ownedApplication.isActive, "owned-application-inactive-after-selection")
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
