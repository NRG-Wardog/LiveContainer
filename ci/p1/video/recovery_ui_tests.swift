import XCTest
import Foundation

// Strict geometry/action checks for the exact extracted production layout.
// Fixture status callbacks are synthetic and never contact a service.
final class P1RecoveryLayoutUITests: XCTestCase {
    private let kinds = ["operation", "direct", "refresh", "unreadable"]

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
                "frame": rect(element.frame), "accessibilityValue": element.value as? String ?? ""]
    }

    private func attach(_ report: [String: Any], name: String) {
        let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        let item = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        item.name = name; item.lifetime = .keepAlways; add(item)
    }

    @MainActor private func screenshot(_ app: XCUIApplication, name: String) {
        let item = XCTAttachment(screenshot: app.screenshot())
        item.name = name; item.lifetime = .keepAlways; add(item)
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

    @MainActor private func tabs(_ app: XCUIApplication) -> [XCUIElement]? {
        // iPad places these controls above the content and exposes no tabBars.
        // Resolve the real labelled buttons, rejecting absent/ambiguous matches.
        var result: [XCUIElement] = []
        for title in ["Home", "Apps", "Sources", "Settings"] {
            let found = app.buttons.matching(NSPredicate(format: "label == %@", title))
                .allElementsBoundByIndex.filter { $0.exists && self.valid($0.frame) }
            if found.count == 1 { result.append(found[0]); continue }
            // A pushed Home destination also has a Home back button. Only the
            // selected Home tab may resolve that otherwise ambiguous label.
            let selected = found.filter { $0.isSelected }
            guard title == "Home", selected.count == 1 else { return nil }
            result.append(selected[0])
        }
        return result
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

    @MainActor private func geometryReady(_ app: XCUIApplication, banner: Bool,
                                          title: String) -> Bool {
        let window = app.windows.firstMatch
        let bar = app.navigationBars[title]
        let region = app.scrollViews["v3.recovery.region"]
        guard window.exists, bar.exists, let actualTabs = tabs(app),
              region.exists == banner else { return false }
        let viewport = window.frame
        let navigation = title == "Home" ? app.buttons["p1-recovery-navigation"] : bar.buttons.element(boundBy: 0)
        guard navigation.exists, navigation.isHittable, inside(navigation.frame, viewport),
              inside(bar.frame, viewport), actualTabs.allSatisfy({ $0.isHittable && inside($0.frame, viewport) }) else { return false }
        if banner {
            guard inside(region.frame, viewport),
                  region.frame.height <= min(320, viewport.height * 0.4) + 1,
                  region.frame.maxY <= bar.frame.minY + 1,
                  disjoint(region.frame, navigation.frame),
                  actualTabs.allSatisfy({ disjoint(region.frame, $0.frame) }) else { return false }
        }
        if title == "Home" {
            let content = app.staticTexts["p1-recovery-content"]
            guard content.exists, valid(content.frame),
                  bar.frame.maxY <= content.frame.minY + 1,
                  content.frame.intersection(viewport).height >= 1 else { return false }
        }
        return true
    }

    @MainActor @discardableResult private func checkGeometry(_ app: XCUIApplication,
        banner: Bool, title: String = "Home", expectedKind: String? = nil,
        expectedLargest: Bool? = nil, expectedLandscape: Bool? = nil, name: String) -> Bool {
        if expectedKind != nil {
            // Expose passive fixture state and the actual production banner
            // identity before taking the branch-bound geometry observation.
            if title == "Details" {
                let list = app.descendants(matching: .any)["p1-fixture-details-list"]
                if list.exists { for _ in 0..<4 { list.swipeDown() } }
            }
            if banner {
                let region = app.scrollViews["v3.recovery.region"]
                if region.exists { for _ in 0..<4 { region.swipeDown() } }
            }
        }
        let sizeReceipt = title == "Details" ? app.staticTexts["p1-recovery-current-kind"] : app.staticTexts["p1-recovery-content"]
        // Bounded settling for preference measurements, rotation and text changes.
        let deadline = Date().addingTimeInterval(8)
        var ready = false
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
            if kindMatches && sizeMatches && orientationMatches && geometryReady(app, banner: banner, title: title) { ready = true; break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        screenshot(app, name: name)
        attach(["schema": "p1-layout-observation-v1", "case": name,
                "bannerExpected": banner, "navigationTitle": title, "geometryPassed": ready,
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
        XCTAssertTrue(ready, "Recovery must not cover visible navigation, content or tabs: \(name)")
        return ready
    }

    @MainActor private func tapRecovery(_ app: XCUIApplication, label: String, name: String) -> Bool {
        let region = app.scrollViews["v3.recovery.region"]
        let button = app.buttons[label]
        guard region.exists else { XCTFail("Missing recovery scroll region"); return false }
        // Reset to the beginning, then use actual scrolling until a valid tap
        // target is visible. A tall accessible control can span multiple pages.
        for _ in 0..<4 { region.swipeDown() }
        for attempt in 0..<12 {
            if button.exists {
                let visible = button.frame.intersection(region.frame).intersection(app.windows.firstMatch.frame)
                if valid(visible), visible.width >= min(44, button.frame.width),
                   visible.height >= min(44, button.frame.height), button.isHittable {
                    screenshot(app, name: name + "-visible")
                    attach(["schema": "p1-layout-action-v1", "case": name, "label": label,
                            "scrollAttempts": attempt, "button": observe(button),
                            "visibleIntersection": rect(visible), "region": observe(region),
                            "driver": "ordinary-XCTest-visible-coordinate-tap", "admissionEligible": false],
                           name: name + "-input")
                    let box = button.frame
                    button.coordinate(withNormalizedOffset: CGVector(
                        dx: (visible.midX - box.minX) / box.width,
                        dy: (visible.midY - box.minY) / box.height)).tap()
                    return true
                }
            }
            region.swipeUp()
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
            guard details.exists else { break }; details.swipeUp()
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
        if list.exists { for _ in 0..<4 { list.swipeDown() } }
        for _ in 0..<8 {
            if button.exists && button.isHittable { button.tap(); return true }
            guard list.exists else { break }; list.swipeUp()
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
        guard let returnTabs = tabs(app) else { XCTFail("Missing actual tab controls"); return }
        returnTabs[0].tap()
        XCTAssertTrue(app.navigationBars["Details"].waitForExistence(timeout: 5), "Tab switch lost pushed navigation")
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
