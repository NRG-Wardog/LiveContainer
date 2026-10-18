import XCTest
import Foundation
import UIKit

// Strict geometry/action checks for the exact extracted production layout.
// Fixture status callbacks are synthetic and never contact a service.
final class P1RecoveryLayoutUITests: XCTestCase {
    private let kinds = ["operation", "direct", "refresh", "unreadable"]
    private var gestureOrdinal = 0
    private var callbackOrdinal = 0
    private var pendingActionCase: String?
    private var pendingActionMetrics: [String: Any]?

    @MainActor private func launch(_ kind: String, largest: Bool,
                                   landscape: Bool = false) -> XCUIApplication {
        continueAfterFailure = true
        callbackOrdinal = 0; pendingActionCase = nil; pendingActionMetrics = nil
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--recovery", "--production-shape", "--recovery-kind", kind]
            + (largest ? ["--largest"] : [])
        app.launch()
        // Request rotation only after an actual active portrait scene exists.
        // The fixture plist declares its supported orientations; XCTest never
        // writes an app orientation or relabels a portrait observation.
        _ = settleOrientation(app, landscape: false, name: "launch-portrait")
        if landscape {
            XCUIDevice.shared.orientation = .landscapeLeft
            _ = settleOrientation(app, landscape: true, name: "launch-landscape")
        }
        return app
    }

    private func rect(_ value: CGRect) -> [Any] {
        [value.minX, value.minY, value.width, value.height].map {
            $0.isFinite ? Double($0) as Any : "non-finite" as Any
        }
    }

    @MainActor private func observe(_ element: XCUIElement) -> [String: Any] {
        guard element.exists else { return ["exists": false] }
        do {
            // One fresh immutable attribute set per call. Live interactability
            // and identity remain separate observations; nothing survives an action.
            let snapshot = try element.snapshot()
            let identifier = element.identifier
            let type = element.elementType
            let hittable = element.isHittable
            guard snapshot.identifier == identifier, snapshot.elementType == type else {
                XCTFail("Accessibility observation identity changed")
                return ["exists": true, "observationError": "identity-changed"]
            }
            return ["exists": true, "label": snapshot.label, "hittable": hittable,
                    "frame": rect(snapshot.frame), "accessibilityValue": snapshot.value as? String ?? "",
                    "identifier": snapshot.identifier, "elementType": snapshot.elementType.rawValue,
                    "selected": snapshot.isSelected]
        } catch {
            XCTFail("Accessibility snapshot observation failed")
            return ["exists": true, "observationError": "snapshot-failed"]
        }
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

    private let tabTitles = ["Home", "Apps", "Sources", "Settings"]

    @MainActor private func structuralTabSnapshot(_ app: XCUIApplication, root: any XCUIElementSnapshot) -> (inventory: [[String: Any]], controls: [XCUIElement]?, observations: [[String: Any]]) {
        typealias Node = (path: [Int], ancestors: [[String: Any]], snapshot: any XCUIElementSnapshot)
        var nodes: [Node] = []
        var count = 0
        @MainActor func attributes(_ node: any XCUIElementSnapshot, path: [Int]) -> [String: Any] {
            ["path": path, "identifier": node.identifier, "label": node.label,
             "elementType": node.elementType.rawValue, "frame": rect(node.frame), "selected": node.isSelected]
        }
        @MainActor func visit(_ node: any XCUIElementSnapshot, path: [Int], ancestors: [[String: Any]]) {
            count += 1
            guard count <= 4096 else { return }
            nodes.append((path, ancestors, node))
            for (index, child) in node.children.enumerated() {
                visit(child, path: path + [index], ancestors: ancestors + [attributes(node, path: path)])
            }
        }
        @MainActor func live(_ path: [Int]) -> XCUIElement {
            var element: XCUIElement = app
            for index in path { element = element.children(matching: .any).element(boundBy: index) }
            return element
        }
        @MainActor func agrees(_ snapshot: any XCUIElementSnapshot, _ observed: [String: Any]) -> Bool {
            observed["exists"] as? Bool == true && observed["hittable"] as? Bool == true
                && observed["identifier"] as? String == snapshot.identifier
                && observed["label"] as? String == snapshot.label
                && observed["elementType"] as? UInt == snapshot.elementType.rawValue
                && observed["selected"] as? Bool == snapshot.isSelected
                && measuredRect(observed["frame"]).map({ sameFrame($0, snapshot.frame) }) == true
        }
        visit(root, path: [], ancestors: [])
        let bars = nodes.filter { $0.snapshot.elementType == .tabBar }
        guard count <= 4096, bars.count == 1, app.tabBars.count == 1, let bar = bars.first else { return ([], nil, []) }
        let buttons = nodes.filter { $0.snapshot.elementType == .button && $0.path.count > bar.path.count && $0.path.starts(with: bar.path) }
        let actualBar = live(bar.path)
        let barObserved = observe(actualBar)
        let viewport = app.windows.firstMatch.frame
        guard buttons.count == 4, actualBar.descendants(matching: .button).count == 4,
              buttons.map({ $0.snapshot.label }) == tabTitles,
              buttons.allSatisfy({ $0.snapshot.identifier.isEmpty && inside($0.snapshot.frame, viewport) }),
              buttons.filter({ $0.snapshot.isSelected }).count == 1,
              agrees(bar.snapshot, barObserved), inside(bar.snapshot.frame, viewport) else { return ([], nil, []) }
        let barProof: [String: Any] = ["path": bar.path, "ancestors": bar.ancestors,
                                     "snapshot": attributes(bar.snapshot, path: bar.path), "observed": barObserved]
        var inventory: [[String: Any]] = []
        var controls: [XCUIElement] = []
        var observations: [[String: Any]] = []
        var complete = true
        for (index, node) in buttons.enumerated() {
            let identifier = "p1-tab-" + tabTitles[index]
            let queryCount = app.descendants(matching: .any).matching(identifier: identifier).count
            let element = live(node.path)
            let observed = observe(element)
            if queryCount != 0 || !agrees(node.snapshot, observed) { complete = false }
            inventory.append(["title": tabTitles[index], "identifier": identifier,
                              "resolution": "unique-native-tabbar-v1", "barQueryCount": 1, "buttonQueryCount": 4,
                              "tabBar": barProof, "viewport": rect(viewport),
                              "candidates": [["path": node.path, "ancestors": node.ancestors,
                                              "snapshot": attributes(node.snapshot, path: node.path), "observed": observed]],
                              "queryCount": queryCount, "selectedPath": node.path,
                              "snapshotComplete": true, "snapshotNodeCount": count])
            controls.append(element); observations.append(observed)
        }
        return (inventory, complete ? controls : nil, complete ? observations : [])
    }

    @MainActor private func tabSnapshot(_ app: XCUIApplication) -> (inventory: [[String: Any]], controls: [XCUIElement]?, observations: [[String: Any]]) {
        guard let root = try? app.snapshot() else { return ([], nil, []) }
        var nodes: [(path: [Int], ancestors: [[String: Any]], snapshot: any XCUIElementSnapshot)] = []
        var count = 0
        @MainActor func attributes(_ node: any XCUIElementSnapshot, path: [Int]) -> [String: Any] {
            ["path": path, "identifier": node.identifier, "label": node.label,
             "elementType": node.elementType.rawValue, "frame": rect(node.frame), "selected": node.isSelected]
        }
        @MainActor func visit(_ node: any XCUIElementSnapshot, path: [Int], ancestors: [[String: Any]]) {
            count += 1
            guard count <= 4096 else { return }
            if tabTitles.map({ "p1-tab-" + $0 }).contains(node.identifier) {
                nodes.append((path, ancestors, node))
            }
            for (index, child) in node.children.enumerated() {
                visit(child, path: path + [index], ancestors: ancestors + [attributes(node, path: path)])
            }
        }
        visit(root, path: [], ancestors: [])
        if nodes.isEmpty { return structuralTabSnapshot(app, root: root) }
        var inventory: [[String: Any]] = []
        var controls: [XCUIElement] = []
        var selectedObservations: [[String: Any]] = []
        var complete = count <= 4096
        for title in tabTitles {
            let identifier = "p1-tab-" + title
            let candidates = nodes.filter { $0.snapshot.identifier == identifier }
            var rows: [[String: Any]] = []
            var live: [XCUIElement] = []
            for candidate in candidates {
                var element: XCUIElement = app
                for index in candidate.path { element = element.children(matching: .any).element(boundBy: index) }
                let observed = observe(element)
                let snapshot = attributes(candidate.snapshot, path: candidate.path)
                rows.append(["path": candidate.path, "ancestors": candidate.ancestors,
                             "snapshot": snapshot, "observed": observed])
                live.append(element)
                // Validate the just-retained live observation rather than issuing
                // the same synchronous AX queries again. No cross-action cache.
                if observed["exists"] as? Bool != true || observed["hittable"] as? Bool != true
                    || observed["identifier"] as? String != identifier
                    || observed["label"] as? String != candidate.snapshot.label
                    || observed["selected"] as? Bool != candidate.snapshot.isSelected
                    || observed["elementType"] as? UInt != candidate.snapshot.elementType.rawValue
                    || measuredRect(observed["frame"]).map({ sameFrame($0, candidate.snapshot.frame) }) != true { complete = false }
            }
            let queryCount = app.descendants(matching: .any).matching(identifier: identifier).count
            if queryCount != candidates.count || candidates.isEmpty || candidates.contains(where: { $0.snapshot.label != title || $0.snapshot.elementType != .button }) { complete = false }
            let leaves = candidates.indices.filter { index in
                !candidates.indices.contains { other in
                    candidates[other].path.count > candidates[index].path.count
                        && candidates[other].path.starts(with: candidates[index].path)
                }
            }
            var selectedPath: Any = NSNull()
            if leaves.count == 1, let leaf = leaves.first {
                let chosen = candidates[leaf]
                let chain = candidates.allSatisfy {
                    chosen.path.starts(with: $0.path) && $0.snapshot.label == chosen.snapshot.label
                        && $0.snapshot.isSelected == chosen.snapshot.isSelected
                        && $0.snapshot.elementType == chosen.snapshot.elementType
                        && sameFrame($0.snapshot.frame, chosen.snapshot.frame)
                }
                if chain {
                    controls.append(live[leaf]); selectedPath = chosen.path
                    if let observation = rows[leaf]["observed"] as? [String: Any] { selectedObservations.append(observation) }
                    else { complete = false }
                }
                else { complete = false }
            } else { complete = false }
            inventory.append(["title": title, "identifier": identifier, "candidates": rows,
                              "queryCount": queryCount, "selectedPath": selectedPath,
                              "snapshotComplete": count <= 4096, "snapshotNodeCount": count])
        }
        let accepted = complete && controls.count == 4 && selectedObservations.count == 4
        return (inventory, accepted ? controls : nil, accepted ? selectedObservations : [])
    }

    @MainActor private func tabCandidates(_ app: XCUIApplication) -> [[String: Any]] {
        tabSnapshot(app).inventory
    }

    @MainActor private func tabs(_ app: XCUIApplication) -> [XCUIElement]? {
        // A unique structural leaf is required, never equal-frame deduplication.
        tabSnapshot(app).controls
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
              previous["recoveryKind"] as? String == receipt["recoveryKind"] as? String,
              previous["largestText"] as? Bool == receipt["largestText"] as? Bool,
              let started = receipt["startedUptime"] as? Double,
              let finished = receipt["finishedUptime"] as? Double,
              started.isFinite, finished.isFinite, started <= finished else { return nil }
        receipt["causalPrevious"] = previous
        receipt["probeValueReadCount"] = 2
        receipt["runnerRequestBracket"] = [requestStarted, ProcessInfo.processInfo.systemUptime]
        return receipt
    }

    @MainActor private func settleOrientation(_ app: XCUIApplication, landscape: Bool, name: String) -> Bool {
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if app.state == .runningForeground, let receipt = metrics(app),
               let window = measuredRect(receipt["windowBounds"]), sameFrame(window, app.windows.firstMatch.frame),
               let orientation = receipt["interfaceOrientation"] as? Int,
               (landscape ? [3, 4].contains(orientation) && window.width > window.height
                          : orientation == 1 && window.height > window.width) { return true }
            Thread.sleep(forTimeInterval: 0.1)
        }
        retainLayoutFailure(app, reason: "Actual native orientation did not settle: " + name)
        XCTFail("Actual native orientation did not settle: " + name)
        return false
    }

    @MainActor private func measuredScroll(_ app: XCUIApplication, element: XCUIElement,
                                           receipt: [String: Any]) -> [String: Any]? {
        guard element.exists, let offered = measuredRect(receipt["offeredFrame"]),
              let window = measuredRect(receipt["windowBounds"]),
              sameFrame(window, app.windows.firstMatch.frame), inside(offered, window),
              let size = receipt["offeredSize"] as? [Double], size.count == 2,
              abs(size[0] - Double(offered.width)) <= 1, abs(size[1] - Double(offered.height)) <= 1,
              let scrolls = receipt["scrollViews"] as? [[String: Any]] else { return nil }
        let elementFrame = element.frame
        let matched = scrolls.filter { row in
            guard let view = row["view"] as? [String: Any], let frame = measuredRect(view["frame"]) else { return false }
            return sameFrame(frame, elementFrame)
        }
        guard matched.count == 1, let row = matched.first,
              row["scrollEnabled"] as? Bool == true,
              let path = row["path"] as? String, path.hasPrefix("window/"),
              let ancestors = row["ancestors"] as? [[String: Any]], !ancestors.isEmpty,
              let clipped = measuredRect(row["clippedBounds"]),
              let safe = measuredRect(row["safeAreaFrame"]),
              let viewport = measuredRect(row["safeClippingViewport"]),
              let offset = row["contentOffset"] as? [Double], offset.count == 2, offset.allSatisfy({ $0.isFinite }),
              inside(viewport, offered), inside(viewport, clipped), inside(viewport, safe),
              sameFrame(viewport, safe.intersection(clipped).intersection(offered)) else { return nil }
        return row
    }

    @MainActor private func recoveryViewport(_ app: XCUIApplication, receipt: [String: Any]) -> CGRect? {
        guard let row = measuredScroll(app, element: app.scrollViews["v3.recovery.region"], receipt: receipt) else { return nil }
        return measuredRect(row["safeClippingViewport"])
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

    @MainActor private func interiorDrag(_ app: XCUIApplication, element: XCUIElement, down: Bool,
                                        distance: CGFloat? = nil, target: XCUIElement? = nil,
                                        search: String? = nil, attempt: Int? = nil) -> Bool {
        guard app.state == .runningForeground, element.exists,
              let receipt = metrics(app), let window = measuredRect(receipt["windowBounds"]),
              sameFrame(window, app.windows.firstMatch.frame),
              let scroll = measuredScroll(app, element: element, receipt: receipt),
              let visible = measuredRect(scroll["safeClippingViewport"]),
              let beforeOffset = scroll["contentOffset"] as? [Double] else {
            retainLayoutFailure(app, reason: "Missing unique foreground scroll geometry")
            XCTFail("Missing unique foreground scroll geometry"); return false
        }
        let interior = visible.insetBy(dx: 12, dy: 12)
        guard valid(interior), interior.width >= 20, interior.height >= 24,
              let actualTabs = tabs(app),
              actualTabs.allSatisfy({ disjoint(interior, $0.frame) }),
              app.navigationBars.allElementsBoundByIndex.filter({ $0.exists }).allSatisfy({ disjoint(interior, $0.frame) }) else {
            retainLayoutFailure(app, reason: "No navigation-free safe interior drag area")
            XCTFail("No navigation-free safe interior drag area"); return false
        }
        let travel = min(max(8, distance ?? interior.height * 0.45), interior.height * 0.6)
        let start = CGPoint(x: interior.midX, y: interior.midY + (down ? -travel : travel) / 2)
        let end = CGPoint(x: interior.midX, y: interior.midY + (down ? travel : -travel) / 2)
        let base = app.windows.firstMatch.coordinate(withNormalizedOffset: .zero)
        gestureOrdinal += 1
        let name = "layout-interior-drag-\(gestureOrdinal)"
        attach(["schema": "p1-layout-drag-v1", "case": name,
                "element": observe(element), "metrics": receipt, "scrollPath": scroll["path"] ?? NSNull(),
                "offsetBefore": beforeOffset, "target": target.map { observe($0) } as Any? ?? NSNull(),
                "search": search as Any? ?? NSNull(), "attempt": attempt as Any? ?? NSNull(),
                "viewport": rect(window), "visibleBounds": rect(visible), "interiorBounds": rect(interior),
                "start": [Double(start.x), Double(start.y)], "end": [Double(end.x), Double(end.y)],
                "navigationBars": app.navigationBars.allElementsBoundByIndex.filter { $0.exists }.map { observe($0) },
                "tabs": actualTabs.map { observe($0) }, "direction": down ? "down" : "up",
                "driver": "ordinary-XCTest-controlled-coordinate-drag", "velocity": 80.0,
                "pressDuration": 0.05, "holdDuration": 0.2, "admissionEligible": false], name: name + "-input")
        base.withOffset(CGVector(dx: start.x - window.minX, dy: start.y - window.minY)).press(forDuration: 0.05,
            thenDragTo: base.withOffset(CGVector(dx: end.x - window.minX, dy: end.y - window.minY)),
            withVelocity: XCUIGestureVelocity(rawValue: 80), thenHoldForDuration: 0.2)
        guard app.state == .runningForeground, let after = metrics(app),
              let afterWindow = measuredRect(after["windowBounds"]), sameFrame(window, afterWindow),
              sameFrame(window, app.windows.firstMatch.frame),
              after["processSession"] as? String == receipt["processSession"] as? String,
              after["windowObservationID"] as? String == receipt["windowObservationID"] as? String,
              after["interfaceOrientation"] as? Int == receipt["interfaceOrientation"] as? Int,
              let afterScroll = measuredScroll(app, element: element, receipt: after),
              afterScroll["path"] as? String == scroll["path"] as? String,
              let afterOffset = afterScroll["contentOffset"] as? [Double] else {
            retainLayoutFailure(app, reason: "Drag changed scene, orientation, or scroll correspondence")
            XCTFail("Drag changed scene, orientation, or scroll correspondence"); return false
        }
        attach(["schema": "p1-layout-drag-after-v1", "case": name, "metrics": after,
                "viewport": observe(app.windows.firstMatch), "foreground": true,
                "scrollPath": afterScroll["path"] ?? NSNull(), "offsetAfter": afterOffset,
                "offsetDelta": afterOffset[1] - beforeOffset[1],
                "progress": abs(afterOffset[1] - beforeOffset[1]) > 0.5,
                "target": target.map { observe($0) } as Any? ?? NSNull(),
                "admissionEligible": false], name: name + "-after")
        return true
    }

    @MainActor private func seekTarget(_ app: XCUIApplication, element: XCUIElement,
                                      target: XCUIElement, name: String, initialDown: Bool = false) -> (CGRect, [String: Any], Int)? {
        var previousOffset: Double?
        var previousDown: Bool?
        var stalled = 0
        var reversals = 0
        for attempt in 0..<12 {
            guard let receipt = metrics(app), let row = measuredScroll(app, element: element, receipt: receipt),
                  let viewport = measuredRect(row["safeClippingViewport"]),
                  let offset = row["contentOffset"] as? [Double] else { break }
            let observation = observe(target)
            attach(["schema": "p1-layout-target-v1", "case": name + "-target-\(attempt)",
                    "search": name, "attempt": attempt, "target": observation,
                    "element": observe(element), "layoutMetrics": receipt, "scrollPath": row["path"] ?? NSNull(),
                    "clippingViewport": rect(viewport), "offset": offset, "admissionEligible": false],
                   name: name + "-target-\(attempt)")
            let targetFrame = observation["exists"] as? Bool == true ? measuredRect(observation["frame"]) : nil
            if let frame = targetFrame, valid(frame) {
                let visible = frame.intersection(viewport).intersection(app.windows.firstMatch.frame)
                if valid(visible), visible.width >= min(44, frame.width),
                   visible.height >= min(44, frame.height), observation["hittable"] as? Bool == true,
                   let actualTabs = tabs(app), actualTabs.allSatisfy({ disjoint(visible, $0.frame) }),
                   app.navigationBars.allElementsBoundByIndex.filter({ $0.exists }).allSatisfy({ disjoint(visible, $0.frame) }) {
                    return (visible, receipt, attempt)
                }
            }
            if let previous = previousOffset, abs(offset[1] - previous) <= 0.5 { stalled += 1 } else { stalled = 0 }
            var down = previousDown ?? initialDown
            var distance = max(8, (viewport.height - 24) * 0.45)
            if let frame = targetFrame, valid(frame) {
                let needed = min(44, frame.height)
                // Move the nearest sufficient 44pt slice into the clipping window.
                if frame.maxY < viewport.minY + needed { down = true; distance = viewport.minY + needed - frame.maxY + 4 }
                else if frame.minY > viewport.maxY - needed { down = false; distance = frame.minY - (viewport.maxY - needed) + 4 }
                else { down = frame.midY < viewport.midY; distance = 12 }
            } else if stalled > 0 { down.toggle() }
            if stalled >= 2 { break }
            if let previous = previousDown, previous != down { reversals += 1 }
            // The retained phone search stalled on two 10pt inputs with no offset
            // change. Try a 24pt ordinary gesture floor, then apply the unchanged
            // safe-interior/reversal cap. This is a search heuristic, not a
            // measured UIKit threshold or permission to accept a clipped target.
            distance = min(max(distance, 24), max(8, (viewport.height - 24) * (reversals > 0 ? 0.25 : 0.45)))
            previousOffset = offset[1]; previousDown = down
            guard interiorDrag(app, element: element, down: down, distance: distance,
                               target: target, search: name, attempt: attempt) else { return nil }
        }
        screenshot(app, name: name + "-unreachable")
        attach(["schema": "p1-layout-target-failure-v1", "case": name, "target": observe(target),
                "element": observe(element), "layoutMetrics": metrics(app) as Any? ?? NSNull(),
                "hierarchy": app.debugDescription, "admissionEligible": false], name: name + "-unreachable-details")
        XCTFail("Target cannot be safely reached by bounded physical dragging: " + name)
        return nil
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
        let navigationExists = navigation.exists
        let navigationFrame = navigationExists ? navigation.frame : .null
        let barFrame = bar.frame
        let regionExists = region.exists
        let regionFrame = regionExists ? region.frame : .null
        if !navigationExists || !navigation.isHittable || !inside(navigationFrame, viewport) { failures.append("navigation-unavailable") }
        if !inside(barFrame, viewport) { failures.append("navigation-outside-viewport") }
        let actualTabs = tabs(app)
        if actualTabs == nil { failures.append("ambiguous-or-unavailable-tabs") }
        let tabFrames = (actualTabs ?? []).map { $0.frame }
        if !(actualTabs ?? []).allSatisfy({ $0.isHittable }) || !tabFrames.allSatisfy({ inside($0, viewport) }) { failures.append("tabs-outside-viewport") }
        if regionExists != banner { failures.append("wrong-banner-presence") }
        if let receipt = receipt, let measuredWindow = measuredRect(receipt["windowBounds"]),
           sameFrame(viewport, measuredWindow), receipt["selectedTab"] as? Int == 0 {
            if banner && regionExists {
                if !inside(regionFrame, viewport) { failures.append("AX-region-outside-window") }
                if regionFrame.maxY > barFrame.minY + 1 { failures.append("AX-region-overlaps-navigation-bar") }
                if !disjoint(regionFrame, navigationFrame) { failures.append("AX-region-overlaps-navigation-action") }
                if !tabFrames.allSatisfy({ disjoint(regionFrame, $0) }) { failures.append("AX-region-overlaps-tabs") }
                if let measured = recoveryViewport(app, receipt: receipt),
                   let offeredSize = receipt["offeredSize"] as? [Double], offeredSize.count == 2 {
                    if measured.height > CGFloat(min(320, offeredSize[1] * 0.4) + 1) { failures.append("measured-safe-viewport-exceeds-cap") }
                } else { failures.append("ambiguous-or-invalid-clipping-viewport") }
            }
        } else { failures.append("missing-or-inconsistent-layout-receipt") }
        if title == "Home" {
            let content = app.staticTexts["p1-recovery-content"]
            let contentExists = content.exists
            let contentFrame = contentExists ? content.frame : .null
            if !contentExists || !valid(contentFrame) || barFrame.maxY > contentFrame.minY + 1
                || contentFrame.intersection(viewport).height < 1 { failures.append("content-hidden-by-navigation") }
        }
        return failures
    }

    @MainActor @discardableResult private func checkGeometry(_ app: XCUIApplication,
        banner: Bool, title: String = "Home", expectedKind: String? = nil,
        expectedLargest: Bool? = nil, expectedLandscape: Bool? = nil, name: String) -> Bool {
        if expectedKind != nil {
            if title == "Details" {
                let list = app.descendants(matching: .any)["p1-fixture-details-list"]
                let kind = app.staticTexts["p1-recovery-current-kind"]
                if !kind.exists { guard seekTarget(app, element: list, target: kind, name: name + "-kind", initialDown: true) != nil else { return false } }
            }
            if banner, let kind = expectedKind, let identity = productionIdentity(kind) {
                let text = app.staticTexts[identity]
                if !text.exists { guard seekTarget(app, element: app.scrollViews["v3.recovery.region"], target: text, name: name + "-identity", initialDown: true) != nil else { return false } }
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
                guard let actual = metrics(app), let orientation = actual["interfaceOrientation"] as? Int else { return false }
                return valid(frame) && (landscape ? frame.width > frame.height && [3, 4].contains(orientation)
                    : frame.height > frame.width && orientation == 1)
            } ?? true
            measured = metrics(app)
            failures = geometryFailures(app, banner: banner, title: title, receipt: measured)
            if let kind = expectedKind, measured?["recoveryKind"] as? String != kind { failures.append("measured-kind-mismatch") }
            if let largest = expectedLargest, measured?["largestText"] as? Bool != largest { failures.append("measured-size-mismatch") }
            if !kindMatches { failures.append("kind-or-production-identity-mismatch") }
            if !sizeMatches { failures.append("actual-inherited-size-mismatch") }
            if !orientationMatches { failures.append("actual-viewport-orientation-mismatch") }
            if failures.isEmpty { ready = true; break }
            Thread.sleep(forTimeInterval: 0.1)
        }
        screenshot(app, name: name)
        let attachmentTabs = tabSnapshot(app)
        attach(["schema": "p1-layout-observation-v1", "case": name,
                "bannerExpected": banner, "navigationTitle": title, "geometryPassed": ready,
                "predicateFailures": failures, "layoutMetrics": measured as Any? ?? NSNull(),
                "tabCandidates": attachmentTabs.inventory, "screenshotSource": "XCUIScreen.main",
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
                "tabs": attachmentTabs.observations,
                "viewport": observe(app.windows.firstMatch),
                "admissionEligible": false], name: name + "-geometry")
        if !ready { retainLayoutFailure(app, reason: failures.joined(separator: ", ")) }
        XCTAssertTrue(ready, "Recovery geometry failed: \(name): \(failures.joined(separator: ", "))")
        return ready
    }

    @MainActor private func tapRecovery(_ app: XCUIApplication, label: String, name: String) -> Bool {
        let region = app.scrollViews["v3.recovery.region"]
        let button = app.buttons[label]
        guard region.exists, let (visible, receipt, attempt) = seekTarget(app, element: region, target: button, name: name),
              let clippedViewport = recoveryViewport(app, receipt: receipt), pendingActionCase == nil else { return false }
        screenshot(app, name: name + "-visible")
        attach(["schema": "p1-layout-action-v1", "case": name, "label": label,
                "scrollAttempts": attempt, "button": observe(button),
                "visibleIntersection": rect(visible), "region": observe(region),
                "layoutMetrics": receipt, "clippingViewport": rect(clippedViewport),
                "priorCallbackCounter": callbackOrdinal, "expectedCallbackCounter": callbackOrdinal + 1,
                "driver": "ordinary-XCTest-visible-coordinate-tap", "admissionEligible": false], name: name + "-input")
        pendingActionCase = name; pendingActionMetrics = receipt
        let box = button.frame
        button.coordinate(withNormalizedOffset: CGVector(
            dx: (visible.midX - box.minX) / box.width,
            dy: (visible.midY - box.minY) / box.height)).tap()
        return true
    }

    @MainActor private func openDetails(_ app: XCUIApplication) -> Bool {
        let open = app.buttons["p1-recovery-navigation"]
        guard open.exists && open.isHittable, let before = metrics(app) else {
            XCTFail("Navigation action unavailable"); return false
        }
        open.tap()
        // The actual pushed container proves arrival; a lazy offscreen Text row
        // is not a prerequisite for beginning a bounded fixture-control search.
        let bar = app.navigationBars["Details"]
        let arrived = bar.waitForExistence(timeout: 5)
        let lists = app.descendants(matching: .any).matching(identifier: "p1-fixture-details-list")
        let back = bar.buttons.element(boundBy: 0)
        guard arrived, lists.count == 1, lists.element(boundBy: 0).exists,
              back.exists && back.isHittable, app.state == .runningForeground,
              let after = metrics(app),
              let priorSequence = before["observationSequence"] as? Int,
              let sequence = after["observationSequence"] as? Int, sequence > priorSequence,
              let oldWindow = measuredRect(before["windowBounds"]),
              let window = measuredRect(after["windowBounds"]), sameFrame(oldWindow, window),
              let session = before["processSession"] as? String, after["processSession"] as? String == session,
              let windowID = before["windowObservationID"] as? String, after["windowObservationID"] as? String == windowID,
              let orientation = before["interfaceOrientation"] as? Int, after["interfaceOrientation"] as? Int == orientation,
              let tab = before["selectedTab"] as? Int, after["selectedTab"] as? Int == tab,
              let kind = before["recoveryKind"] as? String, after["recoveryKind"] as? String == kind,
              let largest = before["largestText"] as? Bool, after["largestText"] as? Bool == largest else {
            retainLayoutFailure(app, reason: "Navigation did not open the same-session Details container")
            XCTFail("Navigation did not open the same-session Details container"); return false
        }
        return true
    }

    @MainActor private func backHome(_ app: XCUIApplication) -> Bool {
        let back = app.navigationBars["Details"].buttons.element(boundBy: 0)
        guard back.exists && back.isHittable else { XCTFail("Back action unavailable"); return false }
        back.tap()
        let returned = app.buttons["p1-recovery-navigation"].waitForExistence(timeout: 5)
        XCTAssertTrue(returned, "Back did not restore the original navigation root")
        return returned
    }

    @MainActor private func observeCallback(_ app: XCUIApplication, expectedLabel: String,
                                            name: String, before: [String: Any]) -> ([String: Any], [String: Any], Int)? {
        // This fixture receipt is passive. Actual buttons still use seekTarget's
        // visible 44pt slice and ordinary tap. Stop once the exact label exists.
        let value = app.staticTexts["p1-recovery-last-action"]
        let details = app.descendants(matching: .any)["p1-fixture-details-list"]
        var previousOffset: Double?
        var stalled = 0
        for attempt in 0..<12 {
            guard app.state == .runningForeground, let receipt = metrics(app),
                  let beforeSequence = before["observationSequence"] as? Int,
                  let sequence = receipt["observationSequence"] as? Int, sequence > beforeSequence,
                  let oldWindow = measuredRect(before["windowBounds"]),
                  let window = measuredRect(receipt["windowBounds"]), sameFrame(oldWindow, window),
                  let row = measuredScroll(app, element: details, receipt: receipt),
                  let offset = row["contentOffset"] as? [Double],
                  let session = before["processSession"] as? String, receipt["processSession"] as? String == session,
                  let windowID = before["windowObservationID"] as? String, receipt["windowObservationID"] as? String == windowID,
                  let orientation = before["interfaceOrientation"] as? Int, receipt["interfaceOrientation"] as? Int == orientation,
                  let tab = before["selectedTab"] as? Int, receipt["selectedTab"] as? Int == tab,
                  let kind = before["recoveryKind"] as? String, receipt["recoveryKind"] as? String == kind,
                  let largest = before["largestText"] as? Bool, receipt["largestText"] as? Bool == largest else { break }
            let count = app.staticTexts.matching(identifier: "p1-recovery-last-action").count
            let observed = count == 1 ? observe(value) : ["exists": false]
            attach(["schema": "p1-layout-observer-v1", "case": name + "-observation-\(attempt)",
                    "search": name, "attempt": attempt, "expectedLabel": expectedLabel,
                    "queryCount": count, "target": observed, "element": observe(details),
                    "actionBefore": before, "layoutMetrics": receipt, "scrollPath": row["path"] ?? NSNull(),
                    "clippingViewport": row["safeClippingViewport"] ?? NSNull(), "offset": offset,
                    "admissionEligible": false], name: name + "-observation-\(attempt)")
            guard count <= 1 else { break }
            if observed["exists"] as? Bool == true {
                guard observed["identifier"] as? String == "p1-recovery-last-action",
                      observed["label"] as? String == expectedLabel else { break }
                return (observed, receipt, attempt)
            }
            if let previous = previousOffset, abs(offset[1] - previous) <= 0.5 { stalled += 1 } else { stalled = 0 }
            if stalled >= 2 { break }
            previousOffset = offset[1]
            guard interiorDrag(app, element: details, down: false, target: value,
                               search: name, attempt: attempt) else { return nil }
        }
        retainLayoutFailure(app, reason: "Exact current-action callback receipt not observed")
        XCTFail("Exact current-action callback receipt not observed")
        return nil
    }

    @MainActor private func proveCallback(_ app: XCUIApplication, expected: String, name: String) -> Bool {
        guard pendingActionCase == name, let before = pendingActionMetrics, openDetails(app),
              let (observed, receipt, attempt) = observeCallback(app, expectedLabel: expected + ":\(callbackOrdinal + 1)",
                                                               name: name + "-callback-observer", before: before) else { return false }
        screenshot(app, name: name + "-callback")
        attach(["schema": "p1-layout-callback-v1", "case": name, "expected": expected,
                "actual": observed, "actionBefore": before, "layoutMetrics": receipt,
                "priorCallbackCounter": callbackOrdinal, "expectedCallbackCounter": callbackOrdinal + 1,
                "observerSearch": name + "-callback-observer", "observerAttempts": attempt,
                "admissionEligible": false], name: name + "-callback-value")
        callbackOrdinal += 1; pendingActionCase = nil; pendingActionMetrics = nil
        return backHome(app)
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
        if name.hasPrefix("capability-targets-") {
            return checkGeometry(app, banner: true, expectedKind: "operation", expectedLargest: true,
                                 expectedLandscape: true, name: name + "-after")
        }
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
        gestureOrdinal += 1
        let searchName = id + "-search-\(gestureOrdinal)"
        guard list.exists, let (visible, receipt, attempt) = seekTarget(app, element: list, target: button, name: searchName),
              let row = measuredScroll(app, element: list, receipt: receipt) else { return false }
        gestureOrdinal += 1
        let name = "fixture-input-\(gestureOrdinal)"
        screenshot(app, name: name)
        attach(["schema": "p1-layout-fixture-input-v1", "case": name, "identifier": id,
                "scrollAttempts": attempt, "search": searchName, "button": observe(button), "element": observe(list),
                "visibleIntersection": rect(visible), "clippingViewport": row["safeClippingViewport"] ?? NSNull(),
                "layoutMetrics": receipt, "navigationBars": app.navigationBars.allElementsBoundByIndex.filter { $0.exists }.map { observe($0) },
                "tabs": (tabs(app) ?? []).map { observe($0) }, "driver": "ordinary-XCTest-visible-coordinate-tap",
                "admissionEligible": false], name: name + "-receipt")
        let box = button.frame
        button.coordinate(withNormalizedOffset: CGVector(dx: (visible.midX - box.minX) / box.width,
                                                        dy: (visible.midY - box.minY) / box.height)).tap()
        return true
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

    // Short capability checks are dispatched separately. They cannot replace
    // any method or criterion in the complete four-method acceptance matrix.
    @MainActor func testCapabilityNestedTabSelection() {
        let app = launch("none", largest: false)
        defer { app.terminate() }
        guard checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                            expectedLandscape: false, name: "capability-tabs-initial"), openDetails(app),
              let initial = tabs(app) else { return }
        let before = metrics(app)
        let inventory = tabCandidates(app)
        let appsControlBefore = observe(initial[1])
        initial[1].tap()
        guard app.staticTexts["Synthetic Apps content"].waitForExistence(timeout: 5) else { XCTFail("Apps content absent"); return }
        let apps = metrics(app)
        screenshot(app, name: "capability-tabs-apps")
        attach(["schema": "p1-layout-tab-selection-v1", "case": "capability-tabs-apps", "expectedTab": 1,
                "before": before as Any? ?? NSNull(), "actual": apps as Any? ?? NSNull(),
                "tabCandidates": inventory, "controlBefore": appsControlBefore, "control": observe(initial[1]),
                "content": observe(app.staticTexts["Synthetic Apps content"]), "driver": "ordinary-XCTest-tap",
                "admissionEligible": false], name: "capability-tabs-apps-selection")
        guard apps?["selectedTab"] as? Int == 1, let returning = tabs(app) else { XCTFail("Actual Apps selection failed"); return }
        let returnInventory = tabCandidates(app)
        let homeControlBefore = observe(returning[0])
        returning[0].tap()
        guard app.navigationBars["Details"].waitForExistence(timeout: 5) else { XCTFail("Tab switch lost Details"); return }
        let home = metrics(app)
        screenshot(app, name: "capability-tabs-home")
        attach(["schema": "p1-layout-tab-selection-v1", "case": "capability-tabs-home", "expectedTab": 0,
                "before": apps as Any? ?? NSNull(), "actual": home as Any? ?? NSNull(),
                "tabCandidates": returnInventory, "controlBefore": homeControlBefore, "control": observe(returning[0]),
                "content": observe(app.staticTexts["p1-recovery-destination"]), "driver": "ordinary-XCTest-tap",
                "admissionEligible": false], name: "capability-tabs-home-selection")
        guard home?["selectedTab"] as? Int == 0 else { XCTFail("Actual Home selection failed"); return }
        _ = checkGeometry(app, banner: false, title: "Details", expectedKind: "none", expectedLargest: false,
                          expectedLandscape: false, name: "capability-tabs-returned")
    }

    @MainActor func testCapabilityNoBannerRotation() {
        let app = launch("none", largest: false)
        defer { XCUIDevice.shared.orientation = .portrait; app.terminate() }
        guard checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                            expectedLandscape: false, name: "capability-rotation-portrait") else { return }
        XCUIDevice.shared.orientation = .landscapeLeft
        guard settleOrientation(app, landscape: true, name: "capability-rotation-landscape"),
              checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                            expectedLandscape: true, name: "capability-rotation-landscape") else { return }
        XCUIDevice.shared.orientation = .portrait
        guard settleOrientation(app, landscape: false, name: "capability-rotation-returned") else { return }
        _ = checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                          expectedLandscape: false, name: "capability-rotation-returned")
    }

    @MainActor func testCapabilityIdentifierFreeTabs() {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["--recovery", "--production-shape", "--recovery-kind", "none", "--identifier-free-tabs"]
        app.launch()
        defer { app.terminate() }
        guard settleOrientation(app, landscape: false, name: "identifier-free-portrait") else { return }
        _ = checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                          expectedLandscape: false, name: "capability-default-tabs")
    }

    @MainActor func testCapabilityNoBannerDefault() {
        let app = launch("none", largest: false)
        defer { app.terminate() }
        _ = checkGeometry(app, banner: false, expectedKind: "none", expectedLargest: false,
                          expectedLandscape: false, name: "capability-default-tabs")
    }

    @MainActor func testCapabilityLandscapeTargets() {
        let app = launch("operation", largest: true, landscape: true)
        defer { XCUIDevice.shared.orientation = .portrait; app.terminate() }
        guard checkGeometry(app, banner: true, expectedKind: "operation", expectedLargest: true,
                            expectedLandscape: true, name: "capability-targets-initial"),
              action(app, label: "Resume Status Check", expected: "resume-operation", name: "capability-targets-resume"),
              openDetails(app), fixtureTap(app, id: "p1-fixture-next-recovery") else { return }
        _ = checkGeometry(app, banner: true, title: "Details", expectedKind: "direct", expectedLargest: true,
                          expectedLandscape: true, name: "capability-targets-next")
    }
}
