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
        result = CFBooleanGetValue(value as! CFBoolean)
        proof[label + "Boolean"] = result!
    }
    try write(proof, path)
    return result
}

// This observer exists only during one owned menu sequence, before capture.
final class DirectMenuEvents {
    let menu: AXUIElement
    let pid: pid_t
    let session: String
    var openAttempt: UInt64 = 0
    var presetAttempt: UInt64 = 0
    var opened: UInt64 = 0
    var closed: UInt64 = 0
    var error: String?
    init(menu: AXUIElement, pid: pid_t, session: String) {
        self.menu = menu; self.pid = pid; self.session = session
    }
    func receive(_ element: AXUIElement, notification: String) {
        guard AXUIElementSetMessagingTimeout(element, 2) == .success else { error = "menu-notification-timeout-setting"; return }
        var sourcePID: pid_t = 0
        guard CFEqual(element, menu), AXUIElementGetPid(element, &sourcePID) == .success,
              sourcePID == pid else { error = "menu-notification-identity"; return }
        let now = mach_absolute_time()
        if notification == kAXMenuOpenedNotification {
            guard openAttempt > 0, now >= openAttempt, opened == 0, closed == 0 else {
                error = "menu-open-notification-order"; return
            }
            opened = now
        } else if notification == kAXMenuClosedNotification {
            guard opened > 0, presetAttempt >= opened, now >= presetAttempt, closed == 0 else {
                error = "menu-close-notification-order"; return
            }
            closed = now
        } else { error = "menu-notification-kind" }
    }
    func waitFor(_ opening: Bool) throws {
        // Called synchronously on the same run loop used for registration.
        // The existing independent 15-second stage watchdog bounds this wait.
        while (opening ? opened == 0 : closed == 0) {
            if let error = error { throw Failure(error) }
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.02, true)
        }
        if let error = error { throw Failure(error) }
    }
}

func directMenuCallback(_ observer: AXObserver, _ element: AXUIElement,
                        _ notification: CFString, _ context: UnsafeMutableRawPointer?) {
    guard let context = context else { return }
    Unmanaged<DirectMenuEvents>.fromOpaque(context).takeUnretainedValue()
        .receive(element, notification: notification as String)
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

@MainActor func directResizeOwnedWindow(_ window: SCWindow, owner: DirectOwner,
    pid: pid_t, session: String, directory: URL, select: (CGWindowID?, String) async throws -> SCWindow) async throws -> SCWindow {
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
    guard let ownedApplication = NSRunningApplication(processIdentifier: pid) else {
        throw Failure("owned-application-unavailable")
    }
    proof["ownerActiveBefore"] = ownedApplication.isActive
    proof["activationAttempted"] = false
    try write(proof, path)
    if !ownedApplication.isActive {
        try require(owner.valid(), "activation-owner-changed")
        try requireMainWindow()
        proof["activationAttempted"] = true
        try write(proof, path)
        let accepted = ownedApplication.activate(options: [])
        proof["activationRequestAccepted"] = accepted
        try write(proof, path)
        try require(accepted, "owned-application-activation-rejected")
        while !ownedApplication.isActive {
            try require(owner.valid(), "activation-owner-changed")
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.02, true)
        }
    }
    try require(owner.valid(), "activation-owner-changed")
    try requireMainWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-during-activation")
    proof["ownerActiveAfter"] = ownedApplication.isActive
    try write(proof, path)
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
    let beforePresets = try directAXChildren(menus[0]).filter { try directAXOptionalTitle($0) == "Pixel Accurate" }
    try require(beforePresets.count == 1, "owned-pixel-accurate-unavailable-or-ambiguous")
    _ = try directEnabledSnapshot(beforePresets[0], label: "preOpenPresetEnabled", proof: &proof, path: path)
    try require(try directEnabledSnapshot(matching[0], label: "windowMenuEnabled", proof: &proof, path: path) == true,
                "owned-window-menu-disabled-or-unknown")
    let menu = menus[0]
    let events = DirectMenuEvents(menu: menu, pid: pid, session: session)
    var observer: AXObserver?
    try require(AXObserverCreate(pid, directMenuCallback, &observer) == .success,
                "owned-menu-observer-unavailable")
    guard let observer = observer else { throw Failure("owned-menu-observer-empty") }
    let loop = CFRunLoopGetCurrent()
    let source = AXObserverGetRunLoopSource(observer)
    let context = Unmanaged.passUnretained(events).toOpaque()
    var registered: [String] = []
    defer {
        for notification in registered {
            AXObserverRemoveNotification(observer, menu, notification as CFString)
        }
        CFRunLoopRemoveSource(loop, source, kCFRunLoopDefaultMode)
        withExtendedLifetime(events) {}
    }
    for notification in [kAXMenuOpenedNotification, kAXMenuClosedNotification] {
        let status = AXObserverAddNotification(observer, menu, notification as CFString, context)
        proof[notification == kAXMenuOpenedNotification ? "openNotificationAXError" : "closeNotificationAXError"] = status.rawValue
        try write(proof, path)
        try require(status == .success, "owned-menu-notification-unavailable")
        registered.append(notification)
    }
    CFRunLoopAddSource(loop, source, kCFRunLoopDefaultMode)
    try directRequirePress(matching[0], pid: pid)
    try require(owner.valid(), "resize-owner-changed")
    try requireMainWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-before-open")
    try require(ownedApplication.isActive, "owned-application-inactive-before-menu")
    events.openAttempt = mach_absolute_time()
    proof["menuOpenAttemptMach"] = events.openAttempt
    try write(proof, path)
    let openStatus = AXUIElementPerformAction(matching[0], kAXPressAction as CFString)
    proof["menuOpenAXError"] = openStatus.rawValue
    try write(proof, path)
    try require(openStatus == .success, "owned-window-menu-open-failed")
    try events.waitFor(true)
    proof["ownerActiveAfterMenuOpen"] = ownedApplication.isActive
    proof["menuOpenedObservedMach"] = events.opened
    try write(proof, path)
    try requireMainWindow()
    let refreshedMenus = try directAXChildren(matching[0]).filter { try directAXText($0, kAXRoleAttribute) == kAXMenuRole }
    try require(refreshedMenus.count == 1 && CFEqual(refreshedMenus[0], menu), "owned-open-menu-replaced")
    let presets = try directAXChildren(menus[0]).filter { try directAXOptionalTitle($0) == "Pixel Accurate" }
    proof["matchingPixelAccurateItems"] = presets.count
    try write(proof, path)
    try require(presets.count == 1, "owned-pixel-accurate-unavailable-or-ambiguous")
    let preset = presets[0]
    try require(try directAXText(preset, kAXRoleAttribute) == kAXMenuItemRole, "owned-preset-role")
    let enabled = try directEnabledSnapshot(preset, label: "postOpenPresetEnabled", proof: &proof, path: path)
    try require(enabled == true, "owned-preset-disabled-or-unknown-after-open")
    try directRequirePress(preset, pid: pid)
    try require(owner.valid(), "resize-owner-changed")
    try requireMainWindow()
    try require(try directAXRect(target) == window.frame, "owned-window-changed-before-action")
    proof["mutationAttempted"] = true
    try write(proof, path)
    // One documented preset on the exact owned application's current window.
    // No global keystroke, resize retry, or permission request.
    try require(ownedApplication.isActive, "owned-application-inactive-before-preset")
    events.presetAttempt = mach_absolute_time()
    proof["presetAttemptMach"] = events.presetAttempt
    try write(proof, path)
    let actionStatus = AXUIElementPerformAction(preset, kAXPressAction as CFString)
    proof["actionAXError"] = actionStatus.rawValue
    try write(proof, path)
    try require(actionStatus == .success, "owned-pixel-accurate-action-failed")
    try events.waitFor(false)
    proof["menuClosedObservedMach"] = events.closed
    proof["menuClosureObserved"] = true
    try write(proof, path)
    var prior: CGRect?
    while true {
        if let error = events.error { throw Failure(error) }
        try require(owner.valid(), "resize-owner-changed")
        try requireMainWindow()
        let current = try await select(window.windowID, "resized")
        if let error = events.error { throw Failure(error) }
        try require(owner.valid(), "resize-owner-changed-after-selection")
        try requireMainWindow()
        try require(current.frame.width <= 4096 && current.frame.height <= 4096,
                    "resized-source-window-outside-bounds")
        let axFrame = try directAXRect(target)
        if let error = events.error { throw Failure(error) }
        if current.frame == prior && current.frame == axFrame && current.frame != window.frame {
            proof["afterFrame"] = rect(current.frame)
            proof["sameOwnedWindowSettled"] = true
            try write(proof, path)
            if let error = events.error { throw Failure(error) }
            return current
        }
        prior = current.frame
        try await Task.sleep(nanoseconds: 100_000_000)
    }
}
