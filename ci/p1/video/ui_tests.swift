import XCTest
import Foundation

final class P0SignInUITests: XCTestCase {
    private func attach(_ value: [String: Any], _ name: String) {
        let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .prettyPrinted])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    private func rect(_ frame: CGRect) -> [Double] { [frame.minX,frame.minY,frame.width,frame.height].map { Double($0) } }
    @MainActor private func screenshot(_ app: XCUIApplication, _ name: String) {
        let before = ProcessInfo.processInfo.systemUptime
        let item = XCTAttachment(screenshot: app.screenshot()); item.name = name; item.lifetime = .keepAlways; add(item)
        attach(["name": name, "beforeUptime": before, "afterUptime": ProcessInfo.processInfo.systemUptime,
                "clock": "XCTest-process-systemUptime; not assumed equal to app clock"], name + "-clock")
    }
    @MainActor private func phase(_ app: XCUIApplication, _ value: String, _ timeout: Double = 90) -> Bool {
        let predicate = NSPredicate(format: "label == %@", value)
        return XCTWaiter.wait(for: [XCTNSPredicateExpectation(predicate: predicate,
            object: app.staticTexts["p1-video-phase"])], timeout: timeout) == .completed
    }
    @MainActor private func pixel(_ scenario: String) {
        continueAfterFailure = false; XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication(); app.launchArguments = ["--scenario", scenario]; app.launch()
        let copy = app.buttons["signin.prompt.copy-details"]
        XCTAssertTrue(copy.waitForExistence(timeout: 10)); XCTAssertTrue(copy.isHittable)
        XCTAssertEqual(copy.label, "Copy Details")
        let marker = app.otherElements["p1-video-marker"]
        XCTAssertTrue(marker.exists)
        let copyFrame = copy.frame; let markerFrame = marker.frame; let windowFrame = app.windows.firstMatch.frame
        let target = copy.coordinate(withNormalizedOffset: CGVector(dx: .5, dy: .5))
        screenshot(app, "video-\(scenario)-before")
        attach(["schema": "p1-video-controls-v1", "scenario": scenario, "copyFrame": rect(copyFrame),
            "markerFrame": rect(markerFrame), "windowFrame": rect(windowFrame),
            "copyLabel": copy.label, "copyHittable": copy.isHittable], "video-\(scenario)-controls")
        XCTAssertTrue(phase(app, "ready"), "External pre-calibration did not finish")
        let firstBefore = ProcessInfo.processInfo.systemUptime
        copy.tap()
        let firstAfter = ProcessInfo.processInfo.systemUptime
        var input: [String: Any] = ["schema": "p1-video-input-v1", "scenario": scenario,
            "firstBefore": firstBefore, "firstAfter": firstAfter, "firstDriver": "normal-XCTest-tap"]
        if scenario != "timeout" {
            // Public normal physical input; no assumption about quiescence or
            // delivery time. Actual app events decide whether overlap occurred.
            input["secondDelayRequested"] = 1.10
            input["secondDelayBefore"] = ProcessInfo.processInfo.systemUptime
            Thread.sleep(forTimeInterval: 1.10)
            input["secondDelayAfter"] = ProcessInfo.processInfo.systemUptime
            input["secondBefore"] = ProcessInfo.processInfo.systemUptime
            target.tap()
            input["secondAfter"] = ProcessInfo.processInfo.systemUptime
            input["secondDriver"] = "experimental-XCTest-coordinate-tap"
        }
        if scenario != "timeout" {
            XCTAssertTrue(phase(app, "third-ready"), "Mid calibration did not finish")
            XCTAssertTrue(copy.exists && copy.isHittable)
            XCTAssertEqual(copy.label, "Copy Details")
            input["thirdHittable"] = copy.isHittable
            input["thirdLabelBefore"] = copy.label
            input["thirdBefore"] = ProcessInfo.processInfo.systemUptime
            copy.tap()
            input["thirdAfter"] = ProcessInfo.processInfo.systemUptime
            input["thirdDriver"] = "normal-XCTest-third-tap"
        }
        attach(input, "video-\(scenario)-input")
        XCTAssertTrue(phase(app, "finished"), "External post calibration did not finish")
        screenshot(app, "video-\(scenario)-after")
        XCTAssertTrue(copy.exists && copy.isHittable); XCTAssertEqual(copy.label, "Copy Details")
        attach(["schema": "p1-video-completion-v1", "scenario": scenario,
            "completed": true, "copyAfterLabel": copy.label, "copyAfterHittable": copy.isHittable,
            "admissionEligible": false], "video-\(scenario)-complete")
    }
    @MainActor func testProbeTimeoutPixels() { pixel("timeout") }
    @MainActor func testProbeReplacementPixels() { pixel("replacement") }
    @MainActor func testProbeDismissalPixels() { pixel("dismissal") }
    // __P1_RECOVERY_TEST_METHODS__
}
