import XCTest
import Foundation
import CoreGraphics

// Included in the P1 test target after its shared P0SignInUITests declaration.
// Assertions are about an unchanged production modifier on a synthetic
// TabView containing navigation children, as in the production inset topology.
extension P0SignInUITests {
    @MainActor @objc func testP1RecoveryNavigationDefault() {
        p1CheckRecoveryNavigation(largest: false)
    }

    @MainActor @objc func testP1RecoveryNavigationLargest() {
        p1CheckRecoveryNavigation(largest: true)
    }

    @MainActor private func p1CheckRecoveryNavigation(largest: Bool) {
        let caseName = "recovery-navigation-" + (largest ? "largest" : "default")
        let scenarios: [(String, String, [String])] = [
            ("operation", "A previous install may still be running", [
                "Resume Status Check", "I checked; device operation has stopped"]),
            ("direct", "A previous certificate creation has an unresolved result", [
                "Inspect result", "I checked the account or device"]),
            ("refresh", "A previous refresh may still be running", [
                "I checked; refresh has stopped"]),
            ("unreadable", "SideStore paused changes because its recovery record is malformed\nError ID: SS-STATUS-FIXTURE", [
                "I checked; no SideStore operation is running", "Copy Diagnostics"])
        ]
        guard let noBannerControl = p1CheckRecoveryNoBanner(
            largest: largest, caseName: caseName,
            recoveryLabels: scenarios.flatMap { [$0.1] + $0.2 }) else { return }
        var measurements: [[String: Any]] = []
        for (kind, title, controls) in scenarios {
            let arguments = ["--recovery", "--recovery-kind", kind] + (largest ? ["--largest"] : [])
            let app = p1Launch(arguments)
            let heading = app.staticTexts[title]
            let headingReady = heading.waitForExistence(timeout: 5)
            let navigation = app.buttons["p1-recovery-navigation"]
            let content = app.staticTexts["p1-recovery-content"]
            let navigationReady = p1Wait({ navigation.exists && navigation.isHittable && content.exists })
            // Capture before guards/assertions, including a missing heading or
            // occluded navigation. Observations never assert a passing result.
            p1RecoveryCapture(app, name: "p1-\(caseName)-\(kind)", kind: kind,
                              largest: largest, heading: heading, controls: controls)
            guard headingReady else {
                XCTFail("Missing \(kind) recovery banner heading"); return
            }
            guard navigationReady else {
                XCTFail("Navigation is absent/occluded for \(kind), largest=\(largest)"); return
            }
            let bar = app.navigationBars["Recovery"]
            guard bar.exists else { XCTFail("Missing recovery navigation bar"); return }
            let viewport = app.windows.firstMatch.frame
            var envelope = heading.frame
            var buttonMeasurements: [[String: Any]] = []
            for label in controls {
                let button = app.buttons[label]
                guard button.exists else { XCTFail("Missing recovery control: \(label)"); return }
                envelope = envelope.union(button.frame)
                buttonMeasurements.append(["label": label, "frame": p1RecoveryFrame(button.frame),
                                           "hittable": button.isHittable])
            }
            let frames = [heading.frame, envelope, navigation.frame, bar.frame, content.frame, viewport]
            guard frames.allSatisfy({ frame in
                !frame.isEmpty && !frame.isNull && !frame.isInfinite &&
                    [frame.minX, frame.minY, frame.width, frame.height].allSatisfy { $0.isFinite }
            }) else {
                XCTFail("Empty/invalid recovery geometry for \(kind)"); return
            }
            // Geometry is measured from native accessibility frames. No IDs,
            // sizing modifiers, or geometry probes were added to production code.
            XCTAssertLessThanOrEqual(envelope.maxY, bar.frame.minY + 1,
                                     "Recovery content overlaps navigation for \(kind)")
            XCTAssertLessThanOrEqual(bar.frame.maxY, content.frame.minY + 1,
                                     "Synthetic content overlaps navigation for \(kind)")
            XCTAssertTrue(p1RecoveryContains(envelope, in: viewport), "Banner outside viewport for \(kind)")
            XCTAssertTrue(p1RecoveryContains(navigation.frame, in: viewport), "Navigation outside viewport for \(kind)")
            XCTAssertTrue(navigation.isHittable, "Navigation not hittable for \(kind)")
            let measured: [String: Any] = [
                "kind": kind, "largestDynamicType": largest,
                "bannerContentFrame": p1RecoveryFrame(envelope),
                "navigationFrame": p1RecoveryFrame(navigation.frame),
                "navigationBarFrame": p1RecoveryFrame(bar.frame),
                "contentFrame": p1RecoveryFrame(content.frame),
                "viewportFrame": p1RecoveryFrame(viewport),
                "navigationHittable": navigation.isHittable,
                "bannerControls": buttonMeasurements,
                "screenshot": "p1-\(caseName)-\(kind)"
            ]
            navigation.tap()
            guard app.staticTexts["p1-recovery-destination"].waitForExistence(timeout: 5) else {
                XCTFail("Navigation tap did not open destination for \(kind)"); return
            }
            let back = app.navigationBars["Details"].buttons.element(boundBy: 0)
            guard back.exists && back.isHittable else {
                XCTFail("Navigation back is unreachable for \(kind)"); return
            }
            back.tap()
            guard p1Wait({ heading.exists && navigation.exists && navigation.isHittable }) else {
                XCTFail("Navigation back did not restore fixture root for \(kind)"); return
            }
            measurements.append(measured.merging([
                "navigationOpenedDestination": true, "navigationBackRestoredRoot": true
            ]) { _, new in new })
        }
        p1Record(caseName, checks: [
            "recovery-no-banner-control",
            "recovery-all-four-branches-visible", "recovery-content-above-navigation",
            "recovery-navigation-hittable", "recovery-navigation-tap-opens-destination",
            "recovery-navigation-back-restores-root"
        ], observations: [
            "largestDynamicType": largest, "branches": measurements,
            "noBannerControl": noBannerControl,
            "containerTopology": "TabView>NavigationView",
            "scope": "exact production recovery modifier on a synthetic TabView with navigation children and status; no full-app/backend execution"
        ])
    }

    @MainActor private func p1CheckRecoveryNoBanner(
        largest: Bool, caseName: String, recoveryLabels: [String]
    ) -> [String: Any]? {
        let app = p1Launch(["--recovery", "--recovery-kind", "none"] + (largest ? ["--largest"] : []))
        let navigation = app.buttons["p1-recovery-navigation"]
        let content = app.staticTexts["p1-recovery-content"]
        let navigationReady = p1Wait({ navigation.exists && navigation.isHittable && content.exists })
        let screenshotName = "p1-\(caseName)-no-banner"
        p1RecoveryCapture(app, name: screenshotName, kind: "none", largest: largest,
                          heading: nil, controls: recoveryLabels)
        guard navigationReady else {
            XCTFail("No-banner control navigation is absent/occluded, largest=\(largest)"); return nil
        }
        let bannerAbsent = recoveryLabels.allSatisfy {
            !app.staticTexts[$0].exists && !app.buttons[$0].exists
        }
        XCTAssertTrue(bannerAbsent, "No-banner control unexpectedly contains recovery content")
        let bar = app.navigationBars["Recovery"]
        guard bar.exists else { XCTFail("No-banner control is missing its navigation bar"); return nil }
        let viewport = app.windows.firstMatch.frame
        let frames = [navigation.frame, bar.frame, content.frame, viewport]
        guard frames.allSatisfy({ frame in
            !frame.isEmpty && !frame.isNull && !frame.isInfinite &&
                [frame.minX, frame.minY, frame.width, frame.height].allSatisfy { $0.isFinite }
        }) else {
            XCTFail("Empty/invalid no-banner control geometry"); return nil
        }
        XCTAssertLessThanOrEqual(bar.frame.maxY, content.frame.minY + 1,
                                 "No-banner content overlaps navigation")
        XCTAssertTrue(p1RecoveryContains(navigation.frame, in: viewport), "No-banner navigation outside viewport")
        XCTAssertTrue(p1RecoveryContains(bar.frame, in: viewport), "No-banner navigation bar outside viewport")
        XCTAssertTrue(p1RecoveryContains(content.frame, in: viewport), "No-banner content outside viewport")
        XCTAssertTrue(navigation.isHittable, "No-banner navigation not hittable")
        let measured: [String: Any] = [
            "kind": "none", "largestDynamicType": largest, "recoveryBannerAbsent": bannerAbsent,
            "navigationFrame": p1RecoveryFrame(navigation.frame),
            "navigationBarFrame": p1RecoveryFrame(bar.frame),
            "contentFrame": p1RecoveryFrame(content.frame),
            "viewportFrame": p1RecoveryFrame(viewport),
            "navigationHittable": navigation.isHittable, "screenshot": screenshotName
        ]
        navigation.tap()
        guard app.staticTexts["p1-recovery-destination"].waitForExistence(timeout: 5) else {
            XCTFail("No-banner navigation tap did not open destination"); return nil
        }
        let back = app.navigationBars["Details"].buttons.element(boundBy: 0)
        guard back.exists && back.isHittable else {
            XCTFail("No-banner navigation back is unreachable"); return nil
        }
        back.tap()
        guard p1Wait({ content.exists && navigation.exists && navigation.isHittable }) else {
            XCTFail("No-banner navigation back did not restore fixture root"); return nil
        }
        return measured.merging([
            "navigationOpenedDestination": true, "navigationBackRestoredRoot": true
        ]) { _, new in new }
    }

    @MainActor private func p1RecoveryCapture(
        _ app: XCUIApplication, name: String, kind: String, largest: Bool,
        heading: XCUIElement?, controls: [String]
    ) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        var elements: [(String, XCUIElement)] = [
            ("navigation", app.buttons["p1-recovery-navigation"]),
            ("navigationBar", app.navigationBars["Recovery"]),
            ("content", app.staticTexts["p1-recovery-content"]),
            ("viewport", app.windows.firstMatch)
        ]
        if let heading = heading { elements.append(("heading", heading)) }
        for label in controls {
            elements.append(("button: " + label, app.buttons[label]))
            elements.append(("text: " + label, app.staticTexts[label]))
        }
        var native: [[String: Any]] = []
        for (label, element) in elements {
            var observation: [String: Any] = ["label": label, "exists": element.exists]
            if element.exists {
                observation["hittable"] = element.isHittable
                let frame = element.frame
                // Non-finite frames must fail acceptance, but remain serializable
                // in failure diagnostics rather than preventing attachment export.
                observation["frame"] = p1RecoveryFrame(frame).map { $0.isFinite ? $0 as Any : "non-finite" as Any }
            }
            native.append(observation)
        }
        let diagnostic: [String: Any] = [
            "schema": "p1-recovery-observation-v1", "kind": kind,
            "largestDynamicType": largest, "screenshot": name, "elements": native,
            "scope": "pre-assertion native observations; not a passing case report"
        ]
        let data = try! JSONSerialization.data(withJSONObject: diagnostic, options: [.prettyPrinted, .sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name + "-observation"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func p1RecoveryFrame(_ frame: CGRect) -> [Double] {
        [Double(frame.minX), Double(frame.minY), Double(frame.width), Double(frame.height)]
    }

    private func p1RecoveryContains(_ frame: CGRect, in viewport: CGRect) -> Bool {
        frame.minX >= viewport.minX - 1 && frame.maxX <= viewport.maxX + 1 &&
            frame.minY >= viewport.minY - 1 && frame.maxY <= viewport.maxY + 1
    }
}
