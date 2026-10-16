import Foundation
import SwiftUI
import UIKit

// Fixture-only observer of the existing rendered production accessibility tree.
// It never reads/writes production @State, invokes copyDiagnostic, or changes a timer.
@MainActor final class P1FeedbackObserver: ObservableObject {
    @Published private(set) var reportJSON = ""
    private var timer: Timer?
    private var origin = 0.0
    private var ordinal = 0
    private var scenario = "feedback-timeout"
    private var phase = ""
    private var events: [[String: Any]] = []
    private var samples: [[String: Any]] = []
    private var transitions: [[String: Any]] = []
    private var activations: [[String: Any]] = []
    private var didTransition = false
    private var didReopen = false
    private var didActivate = false
    private var context: () -> (Int, Bool) = { (0, true) }
    private var transition: () -> Void = {}
    private var reopen: () -> Void = {}

    func copyEvent(value: String, expected: String, changeCount: Int,
                   context: @escaping () -> (Int, Bool), transition: @escaping () -> Void,
                   reopen: @escaping () -> Void) {
        let now = ProcessInfo.processInfo.systemUptime
        ordinal += 1
        if timer == nil {
            origin = now
            let args = ProcessInfo.processInfo.arguments
            scenario = args.contains("--replace-on-copy") ? "prompt-replacement"
                : args.contains("--dismiss-on-copy") ? "dismiss-reopen" : "feedback-timeout"
            phase = ordinal == 1 ? "overlap" : "normal-xctest-tap"
            self.context = context; self.transition = transition; self.reopen = reopen
            events = []; samples = []; transitions = []; activations = []
            didTransition = false; didReopen = false; didActivate = false
            reportJSON = ""
            timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.tick() }
            }
        }
        let state = context()
        events.append(["ordinal": ordinal, "time": now - origin, "generation": state.0,
                       "shown": state.1, "clipboardExact": value == expected,
                       "changeCount": changeCount,
                       "driver": ordinal == 2 && phase == "overlap" ? "public-accessibilityActivate" : "XCTest-tap"])
    }

    private func copyElements() -> ([NSObject], Bool) {
        var matches: [NSObject] = [], visited = Set<ObjectIdentifier>()
        var exhausted = false
        func walk(_ object: NSObject, depth: Int) {
            guard depth <= 40, visited.count < 2048 else { exhausted = true; return }
            guard visited.insert(ObjectIdentifier(object)).inserted else { return }
            if let view = object as? UIView, view.isHidden || view.alpha <= 0.01 { return }
            if (object as? UIAccessibilityIdentification)?.accessibilityIdentifier == "signin.prompt.copy-details" {
                matches.append(object)
            }
            if let children = object.accessibilityElements {
                if children.count > 512 { exhausted = true; return }
                for child in children { if let child = child as? NSObject { walk(child, depth: depth + 1) } }
            } else {
                let count = object.accessibilityElementCount()
                if count != NSNotFound && count > 0 {
                    guard count <= 512 else { exhausted = true; return }
                    for index in 0..<count {
                        if let child = object.accessibilityElement(at: index) as? NSObject { walk(child, depth: depth + 1) }
                    }
                }
            }
            if let view = object as? UIView {
                for child in view.subviews { walk(child, depth: depth + 1) }
            }
        }
        for scene in UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }) {
            for window in scene.windows where !window.isHidden { walk(window, depth: 0) }
        }
        return (matches, exhausted)
    }

    private func tick() {
        guard timer != nil else { return }
        let now = ProcessInfo.processInfo.systemUptime - origin
        let state = context()
        let (elements, exhausted) = copyElements()
        let element = elements.count == 1 ? elements[0] : nil
        let frame = element?.accessibilityFrame ?? .zero
        let viewport = UIScreen.main.bounds
        samples.append(["time": now, "generation": state.0, "shown": state.1,
                        "matchCount": elements.count, "traversalExhausted": exhausted,
                        "identifier": "signin.prompt.copy-details",
                        "label": element?.accessibilityLabel ?? "",
                        "frame": [Double(frame.minX), Double(frame.minY), Double(frame.width), Double(frame.height)],
                        "viewport": [Double(viewport.minX), Double(viewport.minY), Double(viewport.width), Double(viewport.height)]])
        if phase == "overlap" && scenario != "feedback-timeout" {
            if !didTransition && now >= 0.75 {
                didTransition = true
                transitions.append(["kind": scenario == "prompt-replacement" ? "replace" : "dismiss", "time": now])
                transition()
            }
            if scenario == "dismiss-reopen" && didTransition && !didReopen && now >= 0.9 {
                // The previous tick must have observed real element absence.
                if samples.contains(where: { ($0["shown"] as? Bool) == false && ($0["matchCount"] as? Int) == 0 }) {
                    didReopen = true
                    transitions.append(["kind": "reopen", "time": now])
                    reopen()
                }
            }
            if didTransition && !didActivate && now >= 1.05 && now < 2 && state.1 &&
                element?.accessibilityLabel == "Copy Details" && !exhausted {
                didActivate = true
                let requested = ProcessInfo.processInfo.systemUptime - origin
                let before = element!.accessibilityLabel ?? ""
                let success = element!.accessibilityActivate()
                activations.append(["time": requested, "success": success,
                                    "identifier": "signin.prompt.copy-details", "labelBefore": before])
            }
        }
        let expected = phase == "overlap" && scenario != "feedback-timeout" ? 2 : 1
        let lastEvent = events.last?["time"] as? Double ?? 0
        if (events.count == expected && now - lastEvent >= 3) || now >= 7 || samples.count >= 160 {
            finish(now)
        }
    }

    private func finish(_ elapsed: Double) {
        timer?.invalidate(); timer = nil
        let report: [String: Any] = ["schema": "p1-passive-ax-trace-v1", "scenario": scenario,
            "phase": phase, "duration": elapsed, "sampleIntervalSeconds": 0.05,
            "source": "public UIKit accessibility tree; production identifier/label/frame",
            "events": events, "samples": samples, "transitions": transitions, "activations": activations]
        do {
            let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
            reportJSON = String(decoding: data, as: UTF8.self)
        } catch { reportJSON = "invalid-observation-json" }
    }
}
