import Foundation
import SwiftUI
import UIKit

// Diagnostic observer only. It never reads or sets production copied state.
// drawHierarchy is a view snapshot, not proof of compositor freshness.
@MainActor final class P1PixelProbe: ObservableObject {
    @Published var state = "idle"
    private var timer: Timer?
    private var directory: URL?
    private var scenario = ""
    private var started = 0.0
    private var frames: [[String: Any]] = []
    private var events: [[String: Any]] = []
    private var transitions: [[String: Any]] = []
    private var journals: [[String: Any]] = []
    private var errors: [String] = []
    private var finished = false
    private var context: (() -> (Int, Bool))?
    private var transition: (() -> Void)?
    private var reopen: (() -> Void)?
    private var now: Double { ProcessInfo.processInfo.systemUptime }

    func arm(scenario: String, context: @escaping () -> (Int, Bool),
             transition: @escaping () -> Void, reopen: @escaping () -> Void) {
        guard state == "idle", ["timeout", "replacement", "dismissal"].contains(scenario) else { return }
        self.scenario = scenario; self.context = context
        self.transition = transition; self.reopen = reopen
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("p1-pixel-probe", isDirectory: true)
        let target = root.appendingPathComponent(scenario, isDirectory: true)
        do {
            // An old run must never contribute PNGs to a new trace/OCR pass.
            guard !FileManager.default.fileExists(atPath: target.path) else {
                throw NSError(domain: "P1Probe", code: 1, userInfo: [NSLocalizedDescriptionKey: "scenario already exists"])
            }
            try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
            directory = target; started = now; state = "recording"
            checkpoint(reason: "armed")
            tick()
            guard state == "recording" else { return }
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.tick() }
            }
        } catch { fail(String(describing: error)) }
    }

    func clipboard(value: String, expected: String, changeCount: Int) {
        guard state == "recording", let context = context else { return }
        let snapshot = context()
        let ordinal = events.count + 1
        events.append(["ordinal": ordinal, "uptime": now, "payload": value,
            "expectedPayload": expected, "clipboardExact": value == expected,
            "changeCount": changeCount, "generation": snapshot.0, "shown": snapshot.1,
            "driver": ordinal == 1 ? "normal-XCTest-tap" : "experimental-XCTest-coordinate-tap"])
        // This synchronous write can delay the production action after clipboard
        // assignment. Its cost is retained; nominal timer duration is not proof.
        checkpoint(reason: "clipboard-event-\(ordinal)")
        guard ordinal == 1 && scenario != "timeout" else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { [weak self] in
            guard let self = self, self.state == "recording" else { return }
            self.transition?()
            self.recordTransition(self.scenario == "replacement" ? "replace" : "dismiss")
        }
        if scenario == "dismissal" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.05) { [weak self] in
                guard let self = self, self.state == "recording" else { return }
                self.reopen?(); self.recordTransition("reopen")
            }
        }
    }

    private func recordTransition(_ kind: String) {
        let snapshot = context?() ?? (-1, false)
        transitions.append(["kind": kind, "uptime": now, "generation": snapshot.0, "shown": snapshot.1])
        checkpoint(reason: "transition-" + kind)
    }

    private func tick() {
        guard state == "recording", let directory = directory else { return }
        let tickStart = now
        if frames.count >= 120 || tickStart - started >= 12 ||
            (events.last?["uptime"] as? Double).map({ tickStart - $0 >= 4.5 }) == true {
            finish(); return
        }
        do {
            let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
                .flatMap { $0.windows }.filter { $0.isKeyWindow && !$0.isHidden && $0.alpha > 0 }
            guard windows.count == 1, let window = windows.first else {
                throw NSError(domain: "P1Probe", code: 2, userInfo: [NSLocalizedDescriptionKey: "ambiguous visible key window"])
            }
            let bounds = window.bounds
            guard !bounds.isEmpty && !bounds.isInfinite && !bounds.isNull else {
                throw NSError(domain: "P1Probe", code: 3)
            }
            let format = UIGraphicsImageRendererFormat()
            format.scale = window.screen.scale; format.opaque = true
            let renderer = UIGraphicsImageRenderer(bounds: bounds, format: format)
            var rendered = false
            let before = now
            let image = renderer.image { _ in
                rendered = window.drawHierarchy(in: bounds, afterScreenUpdates: false)
            }
            let after = now
            guard let png = image.pngData() else { throw NSError(domain: "P1Probe", code: 4) }
            let name = String(format: "frame-%03d.png", frames.count)
            try png.write(to: directory.appendingPathComponent(name), options: .atomic)
            let snapshot = context?() ?? (-1, false)
            frames.append(["file": name, "beforeUptime": before, "afterUptime": after,
                "tickStartUptime": tickStart, "tickEndUptime": now, "drawHierarchyReturned": rendered,
                "widthPoints": bounds.width, "heightPoints": bounds.height, "scale": format.scale,
                "generation": snapshot.0, "shown": snapshot.1])
            checkpoint(reason: "frame")
        } catch { fail(String(describing: error)) }
    }

    private func checkpoint(reason: String) {
        guard let directory = directory else { return }
        let before = now
        let trace: [String: Any] = ["schema": "p1-pixel-probe-v1", "scenario": scenario,
            "clock": "ProcessInfo.systemUptime", "captureFinished": finished,
            "captureStartUptime": started, "checkpointUptime": before,
            "requestedIntervalSeconds": 0.1, "maximumFrames": 120, "maximumSeconds": 12,
            "capture": "drawHierarchy-afterScreenUpdates-false", "frames": frames,
            "events": events, "transitions": transitions, "errors": errors,
            "priorJournalWrites": journals,
            "journalAccounting": "Current atomic write appears only in a later checkpoint; final write follows the capture window.",
            "freshness": "Uptime brackets bound capture work, not compositor freshness.",
            "admissionEligible": false]
        do {
            let data = try JSONSerialization.data(withJSONObject: trace, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: directory.appendingPathComponent("trace.json"), options: .atomic)
            journals.append(["reason": reason, "beforeUptime": before, "afterUptime": now])
        } catch {
            errors.append("journal: \(error)"); timer?.invalidate(); state = "failed"
        }
    }
    private func finish() {
        timer?.invalidate(); timer = nil; finished = true
        checkpoint(reason: "finished")
        if state != "failed" { state = "finished" }
    }
    private func fail(_ error: String) {
        errors.append(error); timer?.invalidate(); timer = nil
        finished = false; state = "failed"; checkpoint(reason: "failed")
    }
}

@MainActor struct P1ProbePromptScreen: View {
    @State private var generation = 0
    @State private var shown = true
    @State private var submitting = false
    @StateObject private var probe = P1PixelProbe()
    private var scenario: String {
        let a = ProcessInfo.processInfo.arguments
        guard let i = a.firstIndex(of: "--scenario"), i + 1 < a.count else { return "timeout" }
        return a[i + 1]
    }
    private var diagnostic: String { "p1-safe-diagnostic-\(generation)" }
    private var prompt: [String: Any] {
        ["id": "p1-probe-\(generation)", "kind": "credentials", "title": "P1 Credentials",
         "fields": [["key": "appleID", "label": "Apple ID", "secure": "false", "value": ""],
                    ["key": "password", "label": "Password", "secure": "true"]]]
    }
    var body: some View {
        NavigationView {
            Form {
                if shown {
                    V3PromptSection(prompt: prompt, isSubmitting: $submitting,
                        previousFailureMessage: "P1 synthetic failure", previousFailureDetails: diagnostic,
                        onCancel: { shown = false }) { _ in }
                } else { Text("Prompt dismissed").accessibilityIdentifier("p1-probe-dismissed") }
            }.navigationTitle("P1 pixel probe")
            .safeAreaInset(edge: .bottom) {
                HStack {
                    Button("Begin capture") {
                        probe.arm(scenario: scenario, context: { (generation, shown) }, transition: {
                            if scenario == "replacement" { generation += 1 } else { shown = false }
                        }, reopen: { shown = true })
                    }.accessibilityIdentifier("p1-probe-arm").disabled(probe.state != "idle")
                    Text(probe.state).accessibilityIdentifier("p1-probe-state")
                }.padding(8).background(Color(.systemBackground))
            }
        }.navigationViewStyle(.stack)
        .onReceive(NotificationCenter.default.publisher(for: UIPasteboard.changedNotification)) { _ in
            probe.clipboard(value: UIPasteboard.general.string ?? "", expected: diagnostic,
                            changeCount: UIPasteboard.general.changeCount)
        }
    }
}

@main @MainActor struct P1DiagnosticApp: App {
    init() { UIPasteboard.general.string = "" }
    var body: some Scene {
        WindowGroup {
            Group {
                if ProcessInfo.processInfo.arguments.contains("--recovery") { P1ProbeRecoveryScreen() }
                else { P1ProbePromptScreen() }
            }.environment(\.sizeCategory, ProcessInfo.processInfo.arguments.contains("--largest")
                ? .accessibilityExtraExtraExtraLarge : .large)
        }
    }
}
