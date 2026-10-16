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
    @MainActor func p1Copy(_ app: XCUIApplication) -> XCUIElement {
        let copy = app.buttons["signin.prompt.copy-details"]
        XCTAssertTrue(copy.waitForExistence(timeout: 10))
        if !copy.isHittable { app.swipeDown() }
        XCTAssertTrue(copy.isHittable)
        XCTAssertEqual(copy.label, "Copy Details")
        copy.tap()
        XCTAssertTrue(p1Wait({ copy.label == "Copied" }, timeout: 1), "Actual P1 copy action did not show feedback")
        XCTAssertEqual(app.staticTexts["p1-clipboard-state"].label, "exact-safe-diagnostic")
        return copy
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
    @MainActor func p1Lifetime(_ app: XCUIApplication, copy: XCUIElement) -> [String: Any] {
        let started = Double(app.staticTexts["p1-last-copy-time"].label) ?? 0
        XCTAssertGreaterThan(started, 0)
        // Observation stays outside production code. Missing the finite window
        // is an inconclusive test failure, never an inferred timer pass.
        while Date().timeIntervalSince1970 - started < 1.5 { Thread.sleep(forTimeInterval: 0.01) }
        let samplingStarted = Date().timeIntervalSince1970 - started
        XCTAssertEqual(copy.label, "Copied", "New feedback expired before its own minimum lifetime")
        let sampled = Date().timeIntervalSince1970 - started
        XCTAssertGreaterThanOrEqual(samplingStarted, 1.5)
        XCTAssertLessThan(sampled, 3, "Accessibility observation missed the feedback window")
        XCTAssertTrue(p1Wait({ copy.label == "Copy Details" }, timeout: 5), "P1 feedback did not expire")
        let expiry = Date().timeIntervalSince1970 - started
        XCTAssertGreaterThanOrEqual(expiry, 1.5)
        XCTAssertLessThan(expiry, 5)
        return ["minimumLifetimeSeconds": samplingStarted, "feedbackObservedSeconds": sampled,
                "observedExpirySeconds": expiry]
    }
    @MainActor func p1Overlap(_ app: XCUIApplication) -> Double {
        XCTAssertEqual(app.staticTexts["p1-copy-count"].label, "2")
        let first = Double(app.staticTexts["p1-first-copy-time"].label) ?? 0
        let last = Double(app.staticTexts["p1-last-copy-time"].label) ?? 0
        let interval = last - first
        XCTAssertGreaterThanOrEqual(interval, 0.75, "New copy must place its minimum-lifetime sample beyond the old deadline")
        XCTAssertLessThan(interval, 2, "New copy missed the old task lifetime; stale-timer overlap was not exercised")
        return interval
    }
    @MainActor func testP1FeedbackTimeout() {
        let app = p1Launch()
        XCTAssertTrue(app.staticTexts["p1-ready"].waitForExistence(timeout: 10))
        let copy = p1Copy(app)
        let timing = p1Lifetime(app, copy: copy)
        p1Record("feedback-timeout", checks: ["copied-label", "safe-clipboard", "minimum-feedback-lifetime", "feedback-timeout"],
                 observations: timing)
    }
    @MainActor func testP1PromptReplacement() {
        let app = p1Launch(["--replace-on-copy"])
        p1Fill(app)
        _ = p1Copy(app)
        XCTAssertTrue(p1Wait({ app.staticTexts["p1-generation"].label == "1" }))
        let copy = p1Copy(app)
        let timing = p1Lifetime(app, copy: copy)
        let overlap = p1Overlap(app)
        let transitionDelay = Double(app.staticTexts["p1-transition-delay"].label) ?? -1
        XCTAssertGreaterThan(transitionDelay, 0)
        XCTAssertLessThan(transitionDelay, 2)
        p1Submit(app)
        XCTAssertEqual(app.staticTexts["p1-fields-state"].label, "empty", "Synthetic credentials crossed prompt identity")
        p1Record("prompt-replacement", checks: ["copied-label", "replacement-clears-feedback", "replacement-clears-fields",
            "replacement-safe-clipboard", "replacement-feedback-timeout", "replacement-during-feedback",
            "replacement-minimum-lifetime", "replacement-old-timer-overlap"], observations: timing.merging([
                "transitionDelaySeconds": transitionDelay, "copyEventSpacingSeconds": overlap
            ]) { _, new in new })
    }
    @MainActor func testP1DismissReopen() {
        let app = p1Launch(["--dismiss-on-copy"])
        p1Fill(app)
        _ = p1Copy(app)
        XCTAssertTrue(app.staticTexts["p1-dismissed"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.buttons["signin.prompt.copy-details"].exists)
        app.buttons["p1-toggle"].tap()
        let copy = p1Copy(app)
        let timing = p1Lifetime(app, copy: copy)
        let overlap = p1Overlap(app)
        let transitionDelay = Double(app.staticTexts["p1-transition-delay"].label) ?? -1
        XCTAssertGreaterThan(transitionDelay, 0)
        XCTAssertLessThan(transitionDelay, 2)
        p1Submit(app)
        XCTAssertEqual(app.staticTexts["p1-fields-state"].label, "empty", "Dismissed prompt retained synthetic credentials")
        p1Record("dismiss-reopen", checks: ["copied-label", "dismiss-removes-prompt", "reopen-clears-feedback",
            "reopen-clears-fields", "reopen-safe-clipboard", "reopen-feedback-timeout", "dismiss-during-feedback",
            "reopen-minimum-lifetime", "reopen-old-timer-overlap"], observations: timing.merging([
                "transitionDelaySeconds": transitionDelay, "copyEventSpacingSeconds": overlap
            ]) { _, new in new })
    }
}
