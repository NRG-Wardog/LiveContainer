import XCTest
import Foundation

final class P0SignInUITests: XCTestCase {
    @MainActor func p1Launch(_ arguments: [String] = []) -> XCUIApplication {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = arguments
        app.launch()
        return app
    }
    @MainActor func p1Wait(_ predicate: @escaping () -> Bool, timeout: TimeInterval = 5) -> Bool {
        if predicate() { return true }
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in predicate() }, object: nil)
        return XCTWaiter.wait(for: [expectation], timeout: timeout) == .completed
    }
    @MainActor func p1Record(_ name: String, checks: [String], observations: [String: Any] = [:]) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "p1-" + name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let report: [String: Any] = ["schema": "p1-behavior-case-v1", "case": name,
            "checks": checks, "observations": observations, "passed": true,
            "screenshot": screenshot.name,
            "testFailureCount": testRun?.failureCount ?? -1]
        let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = "p1-" + name + "-report"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    @MainActor func p1CopyTap(_ app: XCUIApplication) {
        let copy = app.buttons["signin.prompt.copy-details"]
        XCTAssertTrue(copy.waitForExistence(timeout: 10))
        if !copy.isHittable { app.swipeDown() }
        XCTAssertTrue(copy.isHittable)
        XCTAssertEqual(copy.label, "Copy Details")
        // Transient feedback is observed passively inside the app while XCTest
        // waits for idling after this genuine UI tap. Never infer it from pasteboard.
        copy.tap()
    }
    @MainActor func p1Fill(_ app: XCUIApplication) {
        XCTAssertTrue(app.staticTexts["p1-ready"].waitForExistence(timeout: 10))
        for (field, text) in [(app.textFields["Apple ID"], "p1-user@example.invalid"),
                              (app.secureTextFields["Password"], "p1-synthetic-password")] {
            if !field.isHittable { app.swipeUp() }
            XCTAssertTrue(field.isHittable)
            field.tap(); field.typeText(text)
            app.buttons["p1-hide-keyboard"].tap()
            XCTAssertTrue(p1Wait({ app.keyboards.count == 0 }))
        }
        p1Submit(app)
        XCTAssertEqual(app.staticTexts["p1-fields-state"].label, "synthetic-filled")
    }
    @MainActor func p1Submit(_ app: XCUIApplication) {
        let submit = app.buttons["Submit"]
        if !submit.isHittable { app.swipeUp() }
        XCTAssertTrue(submit.isHittable)
        submit.tap()
    }
    @MainActor func p1Trace(_ app: XCUIApplication, phase: String, ordinals: [Int]) -> [String: Any] {
        let value = app.staticTexts["p1-observation-report"]
        var trace: [String: Any] = [:]
        let ready = p1Wait({
            guard let raw = value.value as? String, let data = raw.data(using: .utf8),
                  let candidate = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let events = candidate["events"] as? [[String: Any]] else { return false }
            trace = candidate
            return candidate["phase"] as? String == phase && events.compactMap({ $0["ordinal"] as? Int }) == ordinals
        }, timeout: 12)
        let attachment = XCTAttachment(data: try! JSONSerialization.data(withJSONObject: trace,
            options: [.prettyPrinted, .sortedKeys]), uniformTypeIdentifier: "public.json")
        attachment.name = "p1-passive-" + phase
        attachment.lifetime = .keepAlways
        add(attachment)
        XCTAssertTrue(ready, "Missing complete passive production-label observation")
        XCTAssertEqual(trace["schema"] as? String, "p1-passive-ax-trace-v1")
        let events = trace["events"] as? [[String: Any]] ?? []
        XCTAssertEqual(events.count, ordinals.count)
        XCTAssertTrue(events.allSatisfy { $0["clipboardExact"] as? Bool == true })
        let changes = events.compactMap { $0["changeCount"] as? Int }
        XCTAssertEqual(Set(changes).count, events.count)
        return trace
    }
    @MainActor func p1Timing(_ trace: [String: Any], overlap: Bool) -> [String: Any] {
        let events = trace["events"] as? [[String: Any]] ?? []
        let samples = trace["samples"] as? [[String: Any]] ?? []
        XCTAssertGreaterThan(samples.count, 10); XCTAssertLessThanOrEqual(samples.count, 160)
        XCTAssertFalse(samples.contains { $0["traversalExhausted"] as? Bool != false })
        func time(_ item: [String: Any]) -> Double { item["time"] as? Double ?? -1 }
        func label(_ item: [String: Any], _ expected: String) -> Bool {
            guard item["identifier"] as? String == "signin.prompt.copy-details",
                  item["matchCount"] as? Int == 1, item["label"] as? String == expected,
                  let frame = item["frame"] as? [Double], frame.count == 4,
                  frame.allSatisfy({ $0.isFinite }), frame[2] > 0, frame[3] > 0,
                  let viewport = item["viewport"] as? [Double], viewport.count == 4,
                  viewport.allSatisfy({ $0.isFinite }), viewport[2] > 0, viewport[3] > 0 else { return false }
            return frame[0] >= viewport[0] - 1 && frame[1] >= viewport[1] - 1 &&
                frame[0] + frame[2] <= viewport[0] + viewport[2] + 1 &&
                frame[1] + frame[3] <= viewport[1] + viewport[3] + 1
        }
        let start = events.last.map(time) ?? -1
        XCTAssertGreaterThanOrEqual(start, 0)
        let copied = samples.filter { label($0, "Copied") && time($0) >= start }
        let late = copied.first { time($0) - start >= 1.5 && time($0) - start < 3 }
        XCTAssertNotNil(late, "Actual rendered feedback lacks its own minimum lifetime")
        let lastCopied = late.map(time) ?? -1
        let expiry = samples.first { label($0, "Copy Details") && time($0) > lastCopied && time($0) - start < 5 }
        XCTAssertNotNil(expiry, "Actual feedback expiry was not observed")
        var result: [String: Any] = ["minimumLifetimeSeconds": lastCopied - start,
            "feedbackObservedSeconds": lastCopied - start, "observedExpirySeconds": (expiry.map(time) ?? -1) - start,
            "passiveTrace": trace]
        if overlap {
            XCTAssertEqual(events.count, 2)
            XCTAssertEqual(events.first?["driver"] as? String, "XCTest-tap")
            XCTAssertEqual(events.last?["driver"] as? String, "public-accessibilityActivate")
            let spacing = start - (events.first.map(time) ?? -1)
            XCTAssertGreaterThanOrEqual(spacing, 0.75); XCTAssertLessThan(spacing, 2)
            XCTAssertGreaterThanOrEqual(lastCopied - (events.first.map(time) ?? -1), 2.25)
            let transitions = trace["transitions"] as? [[String: Any]] ?? []
            let transition = transitions.first.map(time) ?? -1
            XCTAssertGreaterThan(transition, 0); XCTAssertLessThan(transition, 2)
            XCTAssertTrue(samples.contains { label($0, "Copied") && time($0) < transition })
            XCTAssertTrue(samples.contains { label($0, "Copy Details") && time($0) >= transition && time($0) < start })
            let activations = trace["activations"] as? [[String: Any]] ?? []
            XCTAssertEqual(activations.count, 1)
            XCTAssertEqual(activations.first?["success"] as? Bool, true)
            if trace["scenario"] as? String == "dismiss-reopen" {
                XCTAssertTrue(samples.contains { $0["shown"] as? Bool == false && $0["matchCount"] as? Int == 0 })
            }
            result["transitionDelaySeconds"] = transition
            result["copyEventSpacingSeconds"] = spacing
        } else {
            XCTAssertEqual(events.count, 1)
            XCTAssertEqual(events.first?["driver"] as? String, "XCTest-tap")
        }
        return result
    }
    @MainActor func testP1FeedbackTimeout() {
        let app = p1Launch()
        XCTAssertTrue(app.staticTexts["p1-ready"].waitForExistence(timeout: 10))
        p1CopyTap(app)
        let trace = p1Trace(app, phase: "overlap", ordinals: [1])
        let timing = p1Timing(trace, overlap: false)
        p1Record("feedback-timeout", checks: ["copied-label", "safe-clipboard", "minimum-feedback-lifetime", "feedback-timeout"],
                 observations: timing)
    }
    @MainActor func p1Lifecycle(_ name: String, argument: String, checks: [String]) {
        let app = p1Launch([argument])
        p1Fill(app)
        p1CopyTap(app)
        let trace = p1Trace(app, phase: "overlap", ordinals: [1, 2])
        var timing = p1Timing(trace, overlap: true)
        p1Submit(app)
        XCTAssertEqual(app.staticTexts["p1-fields-state"].label, "empty", "Synthetic credentials survived prompt lifecycle")
        // Separate physical-interaction coverage on the replacement/reopened UI.
        // This third event must never satisfy the first/second overlap proof.
        p1CopyTap(app)
        let normal = p1Trace(app, phase: "normal-xctest-tap", ordinals: [3])
        timing["normalTapObservation"] = p1Timing(normal, overlap: false)
        timing["inputDrivers"] = ["XCTest-tap", "public-accessibilityActivate", "XCTest-tap"]
        p1Record(name, checks: checks + ["normal-replacement-copy-hittable-and-tapped"], observations: timing)
    }
    @MainActor func testP1PromptReplacement() {
        p1Lifecycle("prompt-replacement", argument: "--replace-on-copy", checks: ["copied-label",
            "replacement-clears-feedback", "replacement-clears-fields", "replacement-safe-clipboard",
            "replacement-feedback-timeout", "replacement-during-feedback", "replacement-minimum-lifetime",
            "replacement-old-timer-overlap"])
    }
    @MainActor func testP1DismissReopen() {
        p1Lifecycle("dismiss-reopen", argument: "--dismiss-on-copy", checks: ["copied-label",
            "dismiss-removes-prompt", "reopen-clears-feedback", "reopen-clears-fields", "reopen-safe-clipboard",
            "reopen-feedback-timeout", "dismiss-during-feedback", "reopen-minimum-lifetime", "reopen-old-timer-overlap"])
    }
}
