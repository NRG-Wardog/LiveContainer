import XCTest
import Foundation

final class P0SignInUITests: XCTestCase {
    @MainActor private func launch(_ arguments: [String]) -> XCUIApplication {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication(); app.launchArguments = arguments; app.launch(); return app
    }
    private func attach(_ object: [String: Any], name: String) {
        let data = try! JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        let item = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        item.name = name; item.lifetime = .keepAlways; add(item)
    }
    @MainActor private func screenshot(_ app: XCUIApplication, name: String) {
        let before = ProcessInfo.processInfo.systemUptime
        let item = XCTAttachment(screenshot: app.screenshot())
        let after = ProcessInfo.processInfo.systemUptime
        item.name = name; item.lifetime = .keepAlways; add(item)
        attach(["schema": "p1-probe-independent-screenshot-v1", "name": name,
                "beforeUptime": before, "afterUptime": after,
                "clock": "XCTest-process-ProcessInfo.systemUptime",
                "scope": "independent XCTest screenshot; cross-process clock/freshness not assumed"], name: name + "-clock")
    }
    private func frame(_ value: CGRect) -> [Any] {
        [value.minX, value.minY, value.width, value.height].map { $0.isFinite ? Double($0) as Any : "non-finite" as Any }
    }
    @MainActor private func observe(_ element: XCUIElement) -> [String: Any] {
        var result: [String: Any] = ["exists": element.exists]
        if element.exists {
            result["label"] = element.label; result["hittable"] = element.isHittable
            result["frame"] = frame(element.frame)
        }
        return result
    }
    @MainActor private func pixel(_ scenario: String) {
        let app = launch(["--scenario", scenario])
        let copy = app.buttons["signin.prompt.copy-details"]
        let ready = copy.waitForExistence(timeout: 10)
        screenshot(app, name: "probe-\(scenario)-before")
        let initial = observe(copy)
        attach(["schema": "p1-probe-copy-control-v1", "scenario": scenario, "initial": initial], name: "probe-\(scenario)-control")
        guard ready && copy.isHittable else { XCTFail("Actual production Copy control unavailable"); return }
        XCTAssertEqual(copy.label, "Copy Details")
        let target = copy.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        let arm = app.buttons["p1-probe-arm"]
        XCTAssertTrue(arm.isHittable); arm.tap()
        // Ordinary first element tap. XCTest idling may hide transient labels;
        // it does not determine the raw PNG observer's result.
        let firstBefore = ProcessInfo.processInfo.systemUptime
        copy.tap()
        let firstAfter = ProcessInfo.processInfo.systemUptime
        var input: [String: Any] = ["schema": "p1-probe-input-v1", "scenario": scenario,
            "firstDriver": "normal-XCTest-tap", "firstBeforeUptime": firstBefore, "firstAfterUptime": firstAfter]
        if scenario != "timeout" {
            // Capability experiment, not a proven replacement hit. Ordinals,
            // context and exact clipboard payload reveal what actually happened.
            input["secondDriver"] = "experimental-XCTest-coordinate-tap"
            input["secondBeforeUptime"] = ProcessInfo.processInfo.systemUptime
            target.tap()
            input["secondAfterUptime"] = ProcessInfo.processInfo.systemUptime
        }
        attach(input, name: "probe-\(scenario)-input")
        let state = app.staticTexts["p1-probe-state"]
        let predicate = NSPredicate(format: "label == 'finished' OR label == 'failed'")
        let wait = XCTNSPredicateExpectation(predicate: predicate, object: state)
        let done = XCTWaiter.wait(for: [wait], timeout: 18) == .completed
        screenshot(app, name: "probe-\(scenario)-after")
        attach(["schema": "p1-probe-completion-v1", "scenario": scenario,
                "waitCompleted": done, "status": observe(state), "copyAfter": observe(copy),
                "admissionEligible": false], name: "probe-\(scenario)-completion")
        XCTAssertTrue(done, "Capture did not finish within its bounded window")
        XCTAssertEqual(state.label, "finished", "Capture failed; retained journal is incomplete")
    }
    @MainActor func testProbeTimeoutPixels() { pixel("timeout") }
    @MainActor func testProbeReplacementPixels() { pixel("replacement") }
    @MainActor func testProbeDismissalPixels() { pixel("dismissal") }

    @MainActor func testProbeRecoveryTopology() {
        var controlFailures: [String] = []
        for production in [false, true] {
            for largest in [false, true] {
                for kind in ["none", "operation"] {
                    let shape = production ? "production-list" : "synthetic-vstack"
                    let name = "probe-recovery-\(shape)-\(largest ? "largest" : "default")-\(kind)"
                    let args = ["--recovery", "--recovery-kind", kind] +
                        (production ? ["--production-shape"] : []) + (largest ? ["--largest"] : [])
                    let app = launch(args)
                    let navigation = app.buttons["p1-recovery-navigation"]
                    _ = navigation.waitForExistence(timeout: 4)
                    let content = app.staticTexts["p1-recovery-content"]
                    let bar = app.navigationBars[production ? "Home" : "Recovery"]
                    let heading = app.staticTexts["A previous install may still be running"]
                    let resume = app.buttons["Resume Status Check"]
                    let reconcile = app.buttons["I checked; device operation has stopped"]
                    screenshot(app, name: name)
                    var report: [String: Any] = ["schema": "p1-probe-topology-v1", "shape": shape,
                        "kind": kind, "largestDynamicType": largest, "screenshot": name,
                        "containerTopology": "TabView>NavigationView", "fullApplication": false,
                        "navigation": observe(navigation), "navigationBar": observe(bar),
                        "content": observe(content), "heading": observe(heading),
                        "resume": observe(resume), "reconcile": observe(reconcile),
                        "tabs": observe(app.tabBars.firstMatch), "viewport": observe(app.windows.firstMatch),
                        "admissionEligible": false]
                    if heading.exists && resume.exists && reconcile.exists && bar.exists {
                        let envelope = heading.frame.union(resume.frame).union(reconcile.frame)
                        report["bannerEnvelope"] = frame(envelope)
                        report["bannerAboveNavigation"] = envelope.maxY <= bar.frame.minY + 1
                    }
                    if content.exists && bar.exists { report["contentBelowNavigation"] = bar.frame.maxY <= content.frame.minY + 1 }
                    var opened = false; var returned = false
                    if navigation.exists && navigation.isHittable {
                        navigation.tap()
                        opened = app.staticTexts["p1-recovery-destination"].waitForExistence(timeout: 4)
                        if opened {
                            let back = app.navigationBars["Details"].buttons.element(boundBy: 0)
                            if back.exists && back.isHittable {
                                back.tap(); returned = navigation.waitForExistence(timeout: 4) && navigation.isHittable
                            }
                        }
                    }
                    report["navigationOpenedDestination"] = opened
                    report["navigationBackRestoredRoot"] = returned
                    attach(report, name: name + "-observation")
                    if kind == "none" && (!opened || !returned || heading.exists) { controlFailures.append(name) }
                    app.terminate()
                }
            }
        }
        XCTAssertTrue(controlFailures.isEmpty, "Unusable no-banner controls: \(controlFailures)")
    }
}
