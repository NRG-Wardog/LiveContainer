import XCTest
import Foundation
import CoreGraphics

// Included in the P1 test target after its shared P0SignInUITests declaration.
// Assertions are about an unchanged production modifier on a synthetic root.
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
        var measurements: [[String: Any]] = []
        for (kind, title, controls) in scenarios {
            let arguments = ["--recovery", "--recovery-kind", kind] + (largest ? ["--largest"] : [])
            let app = p1Launch(arguments)
            let heading = app.staticTexts[title]
            guard heading.waitForExistence(timeout: 5) else {
                XCTFail("Missing \(kind) recovery banner heading"); return
            }
            let navigation = app.buttons["p1-recovery-navigation"]
            let content = app.staticTexts["p1-recovery-content"]
            let navigationReady = p1Wait({ navigation.exists && navigation.isHittable && content.exists })
            // Retain the problematic state even when the strict AX5/navigation
            // checks fail; an attachment is not itself a passing UI assertion.
            let attachment = XCTAttachment(screenshot: app.screenshot())
            attachment.name = "p1-\(caseName)-\(kind)"
            attachment.lifetime = .keepAlways
            add(attachment)
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
            "recovery-all-four-branches-visible", "recovery-content-above-navigation",
            "recovery-navigation-hittable", "recovery-navigation-tap-opens-destination",
            "recovery-navigation-back-restores-root"
        ], observations: [
            "largestDynamicType": largest, "branches": measurements,
            "scope": "exact production recovery modifier with synthetic status and navigation container; no backend execution"
        ])
    }

    private func p1RecoveryFrame(_ frame: CGRect) -> [Double] {
        [Double(frame.minX), Double(frame.minY), Double(frame.width), Double(frame.height)]
    }

    private func p1RecoveryContains(_ frame: CGRect, in viewport: CGRect) -> Bool {
        frame.minX >= viewport.minX - 1 && frame.maxX <= viewport.maxX + 1 &&
            frame.minY >= viewport.minY - 1 && frame.maxY <= viewport.maxY + 1
    }
}
