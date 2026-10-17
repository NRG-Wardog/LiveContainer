import XCTest
import Foundation
import UIKit

// Strict geometry/action checks for the exact extracted production layout.
// Fixture status callbacks are synthetic and never contact a service.
final class P1RecoveryLayoutUITests: XCTestCase {
    private let kinds = ["operation", "direct", "refresh", "unreadable"]
    private var gestureOrdinal = 0

    @MainActor private func launch(_ kind: String, largest: Bool,
                                   landscape: Bool = false) -> XCUIApplication {
        continueAfterFailure = true
        XCUIDevice.shared.orientation = landscape ? .landscapeLeft : .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--recovery", "--production-shape", "--recovery-kind", kind]
            + (largest ? ["--largest"] : [])
        app.launch()
        return app
    }

    private func rect(_ value: CGRect) -> [Any] {
        [value.minX, value.minY, value.width, value.height].map {
            $0.isFinite ? Double($0) as Any : "non-finite" as Any
        }
    }

    @MainActor private func observe(_ element: XCUIElement) -> [String: Any] {
        guard element.exists else { return ["exists": false] }
        return ["exists": true, "label": element.label, "hittable": element.isHittable,
                "frame": rect(element.frame), "accessibilityValue": element.value as? String ?? "",
                "identifier": element.identifier, "elementType": element.elementType.rawValue, "selected": element.isSelected]
    }

    private func attach(_ report: [String: Any], name: String) {
        let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        let item = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        item.name = name; item.lifetime = .keepAlways; add(item)
    }

    @MainActor private func screenshot(_ app: XCUIApplication, name: String) {
        let captured = XCUIScreen.main.screenshot()
        let item = XCTAttachment(screenshot: captured)
        item.name = name; item.lifetime = .keepAlways; add(item)
        let pixels = captured.image
        attach(["schema": "p1-layout-screen-v1", "case": name, "source": "XCUIScreen.main",
                "imageSize": [Double(pixels.size.width), Double(pixels.size.height)],
                "scale": Double(pixels.scale), "imageOrientation": pixels.imageOrientation.rawValue,
                "pixelWidth": pixels.cgImage?.width ?? 0, "pixelHeight": pixels.cgImage?.height ?? 0,
                "viewport": observe(app.windows.firstMatch), "metrics": metrics(app) as Any? ?? NSNull(),
                "admissionEligible": false], name: name + "-screen-receipt")
    }

    private func valid(_ frame: CGRect) -> Bool {
        !frame.isNull && !frame.isInfinite && frame.width > 0 && frame.height > 0
    }

    private func inside(_ inner: CGRect, _ outer: CGRect) -> Bool {
        valid(inner) && valid(outer) && outer.insetBy(dx: -1, dy: -1).contains(inner)
    }

    private func disjoint(_ a: CGRect, _ b: CGRect) -> Bool {
        let overlap = a.intersection(b)
        return overlap.isNull || overlap.width <= 1 || overlap.height <= 1
    }

    @MainActor private func tabCandidates(_ app: XCUIApplication) -> [[String: Any]] {
        ["Home", "Apps", "Sources", "Settings"].map { title in
            let found = app.descendants(matching: .any).matching(identifier: "p1-tab-" + title)
                .allElementsBoundByIndex.filter { $0.exists }
            return ["title": title, "identifier": "p1-tab-" + title, "candidates": found.map { observe($0) }]
        }
    }

    @MainActor private func tabs(_ app: XCUIApplication) -> [XCUIElement]? {
        // Stable fixture-only IDs annotate the existing labels without changing
        // adaptive controls. Never guess an iPad role or select the first match.
        var result: [XCUIElement] = []
        for title in ["Home", "Apps", "Sources", "Settings"] {
            let found = app.descendants(matching: .any).matching(identifier: "p1-tab-" + title)
                .allElementsBoundByIndex.filter { $0.exists && self.valid($0.frame) && $0.isHittable }
            guard found.count == 1 else { return nil }
            result.append(found[0])
        }
        return result
    }

    private func measuredRect(_ value: Any?) -> CGRect? {
        guard let values = value as? [Double], values.count == 4, values.allSatisfy({ $0.isFinite }) else { return nil }
        let frame = CGRect(x: values[0], y: values[1], width: values[2], height: values[3])
        return valid(frame) ? frame : nil
    }

    private func sameFrame(_ a: CGRect, _ b: CGRect) -> Bool {
        abs(a.minX - b.minX) <= 1 && abs(a.minY - b.minY) <= 1
            && abs(a.width - b.width) <= 1 && abs(a.height - b.height) <= 1
    }

    @MainActor private func metrics(_ app: XCUIApplication) -> [String: Any]? {
        let probe = app.descendants(matching: .any)["p1-layout-metrics"]
        guard probe.exists else { return nil }
        func readValue() -> [String: Any]? {
            guard let value = probe.value as? String, let data = value.data(using: .utf8),
                  let receipt = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
            return receipt
        }
        // Each actual app-side getter invocation increments its sequence. Two
        // distinct requests must produce increasing observations in the same
        // geometry context; app and runner uptime values are never compared.
        let requestStarted = ProcessInfo.processInfo.systemUptime
        guard let previous = readValue(), var receipt = readValue(),
              receipt["schema"] as? String == "p1-layout-metrics-v1",
              receipt["complete"] as? Bool == true, receipt["applicationActive"] as? Bool == true,
              previous["schema"] as? String == "p1-layout-metrics-v1",
              previous["complete"] as? Bool == true, previous["applicationActive"] as? Bool == true,
              let session = receipt["processSession"] as? String, !session.isEmpty,
              previous["processSession"] as? String == session,
              let windowID = receipt["windowObservationID"] as? String, !windowID.isEmpty,
              previous["windowObservationID"] as? String == windowID,
              previous["interfaceOrientation"] as? Int == receipt["interfaceOrientation"] as? Int,
              let first = previous["observationSequence"] as? Int,
              let second = receipt["observationSequence"] as? Int, first > 0, second > first,
              let firstWindow = measuredRect(previous["windowBounds"]),
              let secondWindow = measuredRect(receipt["windowBounds"]), sameFrame(firstWindow, secondWindow),
              let firstOffer = measuredRect(previous["offeredFrame"]),
              let secondOffer = measuredRect(receipt["offeredFrame"]), sameFrame(firstOffer, secondOffer),
              previous["selectedTab"] as? Int == receipt["selectedTab"] as? Int,
              let started = receipt["startedUptime"] as? Double,
              let finished = receipt["finishedUptime"] as? Double,
              started.isFinite, finished.isFinite, started <= finished else { return nil }
        receipt["causalPrevious"] = previous
        receipt["probeValueReadCount"] = 2
        receipt["runnerRequestBracket"] = [requestStarted, ProcessInfo.processInfo.systemUptime]
        return receipt
    }

    @MainActor private func recoveryViewport(_ app: XCUIApplication, receipt: [String: Any]) -> CGRect? {
        let region = app.scrollViews["v3.recovery.region"]
        guard region.exists, let offered = measuredRect(receipt["offeredFrame"]),
              let window = measuredRect(receipt["windowBounds"]),
              sameFrame(window, app.windows.firstMatch.frame), inside(offered, window),
              let size = receipt["offeredSize"] as? [Double], size.count == 2,
              abs(size[0] - Double(offered.width)) <= 1, abs(size[1] - Double(offered.height)) <= 1,
              let scrolls = receipt["scrollViews"] as? [[String: Any]] else { return nil }
        let matched = scrolls.filter { row in
            guard let view = row["view"] as? [String: Any], let frame = measuredRect(view["frame"]) else { return false }
            return sameFrame(frame, region.frame)
        }
        guard matched.count == 1, let row = matched.first,
              row["scrollEnabled"] as? Bool == true,
              let path = row["path"] as? String, path.hasPrefix("window/"),
              let ancestors = row["ancestors"] as? [[String: Any]], !ancestors.isEmpty,
              let clipped = measuredRect(row["clippedBounds"]),
              let safe = measuredRect(row["safeAreaFrame"]),
              let viewport = measuredRect(row["safeClippingViewport"]),
              inside(viewport, offered), inside(viewport, clipped), inside(viewport, safe),
              sameFrame(viewport, safe.intersection(clipped).intersection(offered)) else { return nil }
        return viewport
    }

    @MainActor private func retainLayoutFailure(_ app: XCUIApplication, reason: String) {
        gestureOrdinal += 1
        let name = "layout-observer-failure-\(gestureOrdinal)"
        screenshot(app, name: name)
        attach(["schema": "p1-layout-failure-v1", "case": name, "reason": reason,
                "rawProbe": observe(app.descendants(matching: .any)["p1-layout-metrics"]),
                "tabCandidates": tabCandidates(app), "hierarchy": app.debugDescription,
                "viewport": observe(app.windows.firstMatch), "admissionEligible": false], name: name + "-details")
    }

    @MainActor private func interiorDrag(_ app: XCUIApplication, element: XCUIElement, down: Bool) -> Bool {
        guard app.state == .runningForeground, element.exists,
              let receipt = metrics(app), let window = measuredRect(receipt["windowBounds"]),
              sameFrame(window, app.windows.firstMatch.frame),
              let offered = measuredRect(receipt["offeredFrame"]) else { retainLayoutFailure(app, reason: "Missing foreground drag geometry"); XCTFail("Missing foreground drag geometry"); return false }
        var visible = element.frame.intersection(window).intersection(offered)
        if element.identifier == "v3.recovery.region" {
            guard let measured = recoveryViewport(app, receipt: receipt) else { retainLayoutFailure(app, reason: "Ambiguous recovery clipping viewport"); XCTFail("Ambiguous recovery clipping viewport"); return false }
            visible = visible.intersection(measured)
        } else {
            for bar in app.navigationBars.allElementsBoundByIndex where bar.exists && bar.frame.intersects(visible) {
                let bottom = visible.maxY
                visible.origin.y = max(visible.minY, bar.frame.maxY)
                visible.size.height = bottom - visible.minY
            }
            for tab in tabs(app) ?? [] where tab.frame.minY > visible.midY && tab.frame.intersects(visible) {
                visible.size.height = min(visible.maxY, tab.frame.minY) - visible.minY
            }
        }
        let interior = visible.insetBy(dx: 12, dy: 12)
        guard valid(interior), interior.width >= 20, interior.height >= 24 else { retainLayoutFailure(app, reason: "No safe interior drag area"); XCTFail("No safe interior drag area"); return false }
        let start = CGPoint(x: interior.midX, y: interior.minY + interior.height * (down ? 0.25 : 0.75))
        let end = CGPoint(x: interior.midX, y: interior.minY + interior.height * (down ? 0.75 : 0.25))
        let base = app.windows.firstMatch.coordinate(withNormalizedOffset: .zero)
        gestureOrdinal += 1
        let name = "layout-interior-drag-\(gestureOrdinal)"
        attach(["schema": "p1-layout-drag-v1", "case": name,
                "element": observe(element), "metrics": receipt,
                "viewport": rect(window), "visibleBounds": rect(visible), "interiorBounds": rect(interior),
                "start": [Double(start.x), Double(start.y)], "end": [Double(end.x), Double(end.y)],
                "direction": down ? "down" : "up", "admissionEligible": false], name: name + "-input")
        base.withOffset(CGVector(dx: start.x - window.minX, dy: start.y - window.minY)).press(forDuration: 0.05,
            thenDragTo: base.withOffset(CGVector(dx: end.x - window.minX, dy: end.y - window.minY)))
        guard app.state == .runningForeground, let after = metrics(app),
              let afterWindow = measuredRect(after["windowBounds"]), sameFrame(window, afterWindow),
              sameFrame(window, app.windows.firstMatch.frame) else {
            screenshot(app, name: name + "-contaminated"); XCTFail("Drag left the foreground app or changed orientation"); return false
        }
        attach(["schema": "p1-layout-drag-after-v1", "case": name, "metrics": after,
                "viewport": observe(app.windows.firstMatch), "foreground": true,
                "admissionEligible": false], name: name + "-after")
        return true
    }

    private func productionIdentity(_ kind: String) -> String? {
        switch kind {
        case "operation": return "A previous install may still be running"
        case "direct": return "A previous certificate creation has an unresolved result"
        case "refresh": return "A previous refresh may still be running"
        case "unreadable": return "SideStore paused changes because its recovery record is malformed\nError ID: SS-STATUS-FIXTURE"
        default: return nil
        }
    }

    @MainActor private func geometryFailures(_ app: XCUIApplication, banner: Bool,
                                             title: String, receipt: [String: Any]?) -> [String] {
        var failures: [String] = []
        let window = app.windows.firstMatch
        let bar = app.navigationBars[title]
        let region = app.scrollViews["v3.recovery.region"]
        guard window.exists, bar.exists else { return ["window-or-navigation-absent"] }
        let viewport = window.frame
        let navigation = title == "Home" ? app.buttons["p1-recovery-navigation"] : bar.buttons.element(boundBy: 0)
        if !navigation.exists || !navigation.isHittable || !inside(navigation.frame, viewport) { failures.append("navigation-unavailable") }
        if !inside(bar.frame, viewport) { failures.append("navigation-outside-viewport") }
        let actualTabs = tabs(app)
        if actualTabs == nil { failures.append("ambiguous-or-unavailable-tabs") }
        if !(actualTabs ?? []).allSatisfy({ $0.isHittable && inside($0.frame, viewport) }) { failures.append("tabs-outside-viewport") }
        if region.exists != banner { failures.append("wrong-banner-presence") }
        if let receipt = receipt, let measuredWindow = measuredRect(receipt["windowBounds"]),
           sameFrame(viewport, measuredWindow), receipt["selectedTab"] as? Int == 0 {
            if banner && region.exists {
                if !inside(region.frame, viewport) { failures.append("AX-region-outside-window") }
                if region.frame.maxY > bar.frame.minY + 1 { failures.append("AX-region-overlaps-navigation-bar") }
                if !disjoint(region.frame, navigation.frame) { failures.append("AX-region-overlaps-navigation-action") }
                if !(actualTabs ?? []).allSatisfy({ disjoint(region.frame, $0.frame) }) { failures.append("AX-region-overlaps-tabs") }
                if let measured = recoveryViewport(app, receipt: receipt),
                   let offeredSize = receipt["offeredSize"] as? [Double], offeredSize.count == 2 {
                    if measured.height > CGFloat(min(320, offeredSize[1] * 0.4) + 1) { failures.append("measured-safe-viewport-exceeds-cap") }
                } else { failures.append("ambiguous-or-invalid-clipping-viewport") }
            }
        } else { failures.append("missing-or-inconsistent-layout-receipt") }
        if title == "Home" {
            let content = app.staticTexts["p1-recovery-content"]
            if !content.exists || !valid(content.frame) || bar.frame.maxY > content.frame.minY + 1
                || content.frame.intersection(viewport).height < 1 { failures.append("content-hidden-by-navigation") }
        }
        return failures
    }

    @MainActor @discardableResult private func checkGeometry(_ app: XCUIApplication,
        banner: Bool, title: String = "Home", expectedKind: String? = nil,
        expectedLargest: Bool? = nil, expectedLandscape: Bool? = nil, name: String) -> Bool {
        if expectedKind != nil {
            // Expose passive fixture state and the actual production banner
            // identity before taking the branch-bound geometry observation.
            if title == "Details" {
                let list = app.descendants(matching: .any)["p1-fixture-details-list"]
                if list.exists { for _ in 0..<4 { guard interiorDrag(app, element: list, down: true) else { return false } } }
            }
            if banner {
                let region = app.scrollViews["v3.recovery.region"]
                if region.exists { for _ in 0..<4 { guard interiorDrag(app, element: region, down: true) else { return false } } }
            }
        }
        let sizeReceipt = title == "Details" ? app.staticTexts["p1-recovery-current-kind"] : app.staticTexts["p1-recovery-content"]
        // Bounded settling for preference measurements, rotation and text changes.
        let deadline = Date().addingTimeInterval(8)
        var ready = false
        var measured: [String: Any]?
        var failures: [String] = []
        while Date() < deadline {
            let kindMatches = expectedKind.map { kind in
                let passive = title != "Details" || (app.staticTexts["p1-recovery-current-kind"].exists
                    && app.staticTexts["p1-recovery-current-kind"].label == kind)
                let identity = productionIdentity(kind).map { app.staticTexts[$0].exists } ?? !banner
                return passive && identity
            } ?? true
            let sizeMatches = expectedLargest.map { largest in
                sizeReceipt.exists && (sizeReceipt.value as? String) == (largest ? "sizeCategory=AX5" : "sizeCategory=default")
            } ?? true
            let orientationMatches = expectedLandscape.map { landscape in
                let frame = app.windows.firstMatch.frame
                return valid(frame) && (landscape ? frame.width > frame.height : frame.height > frame.width)
            } ?? true
            measured = metrics(app)
            failures = geometryFailures(app, banner: banner, title: title, receipt: measured)
            if !kindMatches { failures.append("kind-or-production-identity-mismatch") }
            if !sizeMatches { failures.append("actual-inherited-size-mismatch") }
            if !orientationMatches { failures.append("actual-viewport-orientation-mismatch") }
            if failures.isEmpty { ready = true; break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        screenshot(app, name: name)
        attach(["schema": "p1-layout-observation-v1", "case": name,
                "bannerExpected": banner, "navigationTitle": title, "geometryPassed": ready,
                "predicateFailures": failures, "layoutMetrics": measured as Any? ?? NSNull(),
                "tabCandidates": tabCandidates(app), "screenshotSource": "XCUIScreen.main",
                "region": observe(app.scrollViews["v3.recovery.region"]),
                "navigationBar": observe(app.navigationBars[title]),
                "navigationAction": observe(title == "Home" ? app.buttons["p1-recovery-navigation"] : app.navigationBars[title].buttons.element(boundBy: 0)),
                "expectedKind": expectedKind as Any? ?? NSNull(),
                "expectedLargest": expectedLargest as Any? ?? NSNull(),
                "expectedLandscape": expectedLandscape as Any? ?? NSNull(),
                "inheritedSizeCategory": observe(sizeReceipt),
                "passiveCurrentKind": observe(app.staticTexts["p1-recovery-current-kind"]),
                "expectedProductionIdentity": expectedKind.flatMap { productionIdentity($0) } as Any? ?? NSNull(),
                "productionIdentity": expectedKind.flatMap { productionIdentity($0) }.map { observe(app.staticTexts[$0]) } as Any? ?? NSNull(),
                "content": observe(app.staticTexts["p1-recovery-content"]),
                "tabs": (tabs(app) ?? []).map { observe($0) },
                "viewport": observe(app.windows.firstMatch),
                "admissionEligible": false], name: name + "-geometry")
        if !ready { retainLayoutFailure(app, reason: failures.joined(separator: ", ")) }
        XCTAssertTrue(ready, "Recovery geometry failed: \(name): \(failures.joined(separator: ", "))")
        return ready
    }

    @MainActor private func tapRecovery(_ app: XCUIApplication, label: String, name: String) -> Bool {
        let region = app.scrollViews["v3.recovery.region"]
        let button = app.buttons[label]
        guard region.exists else { XCTFail("Missing recovery scroll region"); return false }
        // Reset to the beginning, then use actual scrolling until a valid tap
        // target is visible. A tall accessible control can span multiple pages.
        for _ in 0..<4 { guard interiorDrag(app, element: region, down: true) else { return false } }
        for attempt in 0..<12 {
            if button.exists {
                guard let receipt = metrics(app), let clippedViewport = recoveryViewport(app, receipt: receipt) else {
                    XCTFail("Missing measured clipping viewport for recovery input"); return false
                }
                let visible = button.frame.intersection(clippedViewport).intersection(app.windows.firstMatch.frame)
                if valid(visible), visible.width >= min(44, button.frame.width),
                   visible.height >= min(44, button.frame.height), button.isHittable {
                    screenshot(app, name: name + "-visible")
                    attach(["schema": "p1-layout-action-v1", "case": name, "label": label,
                            "scrollAttempts": attempt, "button": observe(button),
                            "visibleIntersection": rect(visible), "region": observe(region),
                            "layoutMetrics": receipt, "clippingViewport": rect(clippedViewport),
                            "driver": "ordinary-XCTest-visible-coordinate-tap", "admissionEligible": false],
                           name: name + "-input")
                    let box = button.frame
                    button.coordinate(withNormalizedOffset: CGVector(
                        dx: (visible.midX - box.minX) / box.width,
                        dy: (visible.midY - box.minY) / box.height)).tap()
                    return true
                }
            }
            guard interiorDrag(app, element: region, down: false) else { return false }
            guard checkGeometry(app, banner: true, name: name + "-scroll-\(attempt)") else { return false }
        }
        screenshot(app, name: name + "-unreachable")
        XCTFail("Recovery control cannot be reached by scrolling: \(label)")
        return false
    }

    @MainActor private func openDetails(_ app: XCUIApplication) -> Bool {
        let open = app.buttons["p1-recovery-navigation"]
        guard open.exists && open.isHittable else { XCTFail("Navigation action unavailable"); return false }
        open.tap()
        let arrived = app.staticTexts["p1-recovery-destination"].waitForExistence(timeout: 5)
        XCTAssertTrue(arrived, "Navigation did not open the destination")
        return arrived
    }

    @MainActor private func backHome(_ app: XCUIApplication) -> Bool {
        let back = app.navigationBars["Details"].buttons.element(boundBy: 0)
        guard back.exists && back.isHittable else { XCTFail("Back action unavailable"); return false }
        back.tap()
        let returned = app.buttons["p1-recovery-navigation"].waitForExistence(timeout: 5)
        XCTAssertTrue(returned, "Back did not restore the original navigation root")
        return returned
    }

    @MainActor private func proveCallback(_ app: XCUIApplication, expected: String, name: String) -> Bool {
        guard openDetails(app) else { return false }
        let value = app.staticTexts["p1-recovery-last-action"]
        let details = app.descendants(matching: .any)["p1-fixture-details-list"]
        for _ in 0..<8 {
            if value.exists { break }
            guard details.exists else { break }; guard interiorDrag(app, element: details, down: false) else { return false }
        }
        let appeared = value.waitForExistence(timeout: 5)
        screenshot(app, name: name + "-callback")
        attach(["schema": "p1-layout-callback-v1", "case": name, "expected": expected,
                "actual": observe(value), "admissionEligible": false], name: name + "-callback-value")
        XCTAssertTrue(appeared && value.label.hasPrefix(expected + ":"), "Wrong or absent synthetic callback")
        return appeared && value.label.hasPrefix(expected + ":") && backHome(app)
    }

    @MainActor private func action(_ app: XCUIApplication, label: String, confirm: String? = nil,
                                   expected: String, name: String) -> Bool {
        guard tapRecovery(app, label: label, name: name) else { return false }
        if let confirm = confirm {
            let choice = app.buttons[confirm]
            let appeared = choice.waitForExistence(timeout: 5)
            screenshot(app, name: name + "-confirmation")
            guard appeared && choice.isHittable else { XCTFail("Confirmation action unavailable"); return false }
            choice.tap()
        }
        guard proveCallback(app, expected: expected, name: name) else { return false }
        return checkGeometry(app, banner: true, name: name + "-after")
    }

    @MainActor private func exercise(_ kind: String, largest: Bool, landscape: Bool = false) {
        let name = "layout-\(kind)-\(largest ? "AX5" : "default")-\(landscape ? "landscape" : "portrait")"
        let app = launch(kind, largest: largest, landscape: landscape)
        defer { app.terminate() }
        guard checkGeometry(app, banner: kind != "none", expectedKind: kind, expectedLargest: largest, expectedLandscape: landscape, name: name) else { return }
        if kind == "none" { if openDetails(app) { _ = backHome(app) }; return }
        switch kind {
        case "operation":
            guard action(app, label: "Resume Status Check", expected: "resume-operation", name: name + "-resume") else { return }
            _ = action(app, label: "I checked; device operation has stopped", confirm: "I checked; clear the recovery hold",
                       expected: "reconcile-operation", name: name + "-confirm")
        case "direct":
            guard action(app, label: "Inspect result", expected: "inspect-direct", name: name + "-inspect") else { return }
            _ = action(app, label: "I checked the account or device", confirm: "Confirm after checking",
                       expected: "reconcile-direct", name: name + "-confirm")
        case "refresh":
            _ = action(app, label: "I checked; refresh has stopped", confirm: "I checked; clear the refresh hold",
                       expected: "reconcile-refresh", name: name + "-confirm")
        case "unreadable":
            guard action(app, label: "Copy Diagnostics", expected: "copy-diagnostics-exact", name: name + "-copy") else { return }
            _ = action(app, label: "I checked; no SideStore operation is running", confirm: "Clear after device check",
                       expected: "discard-unreadable", name: name + "-confirm")
        default: XCTFail("Unknown recovery branch")
        }
    }

    @MainActor func testRecoveryBranchesDefault() {
        for kind in ["none"] + kinds { exercise(kind, largest: false) }
    }
    @MainActor func testRecoveryBranchesLargest() {
        for kind in ["none"] + kinds { exercise(kind, largest: true) }
    }
    @MainActor func testRecoveryCompactLandscape() {
        for kind in ["none"] + kinds { exercise(kind, largest: true, landscape: true) }
    }

    @MainActor private func fixtureTap(_ app: XCUIApplication, id: String) -> Bool {
        let list = app.descendants(matching: .any)["p1-fixture-details-list"]
        let button = app.buttons[id]
        if list.exists { for _ in 0..<4 { guard interiorDrag(app, element: list, down: true) else { return false } } }
        for _ in 0..<8 {
            if button.exists && button.isHittable { button.tap(); return true }
            guard list.exists else { break }; guard interiorDrag(app, element: list, down: false) else { return false }
        }
        XCTFail("Fixture control unavailable: \(id)"); return false
    }

    @MainActor func testRecoveryStateAndSizeTransitions() {
        let app = launch("none", largest: false)
        defer { XCUIDevice.shared.orientation = .portrait; app.terminate() }
        guard checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false, expectedLandscape: false, name: "transition-initial"), openDetails(app),
              fixtureTap(app, id: "p1-fixture-show-recovery"),
              checkGeometry(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: false, expectedLandscape: false, name: "transition-shown") else { return }
        guard let actualTabs = tabs(app) else { XCTFail("Missing actual tab controls"); return }
        actualTabs[1].tap()
        XCTAssertTrue(app.staticTexts["Synthetic Apps content"].waitForExistence(timeout: 5))
        screenshot(app, name: "transition-apps-tab")
        let appsReceipt = metrics(app)
        attach(["schema": "p1-layout-tab-selection-v1", "case": "transition-apps-tab",
                "expectedTab": 1, "actual": appsReceipt as Any? ?? NSNull(),
                "control": observe(actualTabs[1]), "content": observe(app.staticTexts["Synthetic Apps content"]), "driver": "ordinary-XCTest-tap",
                "admissionEligible": false], name: "transition-apps-tab-selection")
        guard appsReceipt?["selectedTab"] as? Int == 1 else { XCTFail("Actual Apps tab selection did not change"); return }
        guard let returnTabs = tabs(app) else { XCTFail("Missing actual tab controls"); return }
        returnTabs[0].tap()
        XCTAssertTrue(app.navigationBars["Details"].waitForExistence(timeout: 5), "Tab switch lost pushed navigation")
        screenshot(app, name: "transition-home-tab")
        let homeReceipt = metrics(app)
        attach(["schema": "p1-layout-tab-selection-v1", "case": "transition-home-tab",
                "expectedTab": 0, "actual": homeReceipt as Any? ?? NSNull(),
                "control": observe(returnTabs[0]), "content": observe(app.staticTexts["p1-recovery-destination"]), "driver": "ordinary-XCTest-tap",
                "admissionEligible": false], name: "transition-home-tab-selection")
        guard homeReceipt?["selectedTab"] as? Int == 0 else { XCTFail("Actual Home tab selection did not change"); return }
        guard fixtureTap(app, id: "p1-fixture-largest"),
              checkGeometry(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: true, expectedLandscape: false, name: "transition-largest") else { return }
        XCUIDevice.shared.orientation = .landscapeLeft
        guard checkGeometry(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: true, expectedLandscape: true, name: "transition-rotated") else { return }
        // Change natural banner height without replacing the TabView or its
        // pushed destination. Every branch must settle within the same cap.
        for kind in ["direct", "refresh", "unreadable", "operation"] {
            guard fixtureTap(app, id: "p1-fixture-next-recovery"),
                  checkGeometry(app, banner: true, title: "Details", expectedKind: kind, expectedLargest: true, expectedLandscape: true, name: "transition-kind-" + kind) else { return }
        }
        XCUIDevice.shared.orientation = .portrait
        guard checkGeometry(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: true, expectedLandscape: false, name: "transition-portrait"),
              fixtureTap(app, id: "p1-fixture-standard"),
              checkGeometry(app, banner: true, title: "Details", expectedKind: "operation", expectedLargest: false, expectedLandscape: false, name: "transition-standard-with-banner"),
              fixtureTap(app, id: "p1-fixture-clear-recovery"),
              checkGeometry(app, banner: false, title: "Details", expectedKind: "none", expectedLargest: false, expectedLandscape: false, name: "transition-cleared") else { return }
        _ = backHome(app)
        _ = checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false, expectedLandscape: false, name: "transition-final-root")
    }
}
