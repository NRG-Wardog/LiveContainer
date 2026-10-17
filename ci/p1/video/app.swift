import Foundation
import SwiftUI
import UIKit

// Fixture-owned transport only. It never reads or mutates production copied
// state, invokes a production action, or rasterizes the application window.
private final class P1VideoJournal {
    let root: URL
    private let queue = DispatchQueue(label: "p1.video.journal", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var sequence = 0
    private var previousRequest = 0
    private var costs: [[String: Any]] = []
    var request: (([String: Any]) -> Void)?
    init(scenario: String) throws {
        precondition(["timeout", "replacement", "dismissal"].contains(scenario))
        root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("p1-video/" + scenario, isDirectory: true)
        guard !FileManager.default.fileExists(atPath: root.path) else {
            throw NSError(domain: "P1Video", code: 1, userInfo: [NSLocalizedDescriptionKey: "fresh scenario required"])
        }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    }
    func append(_ row: [String: Any]) {
        let enqueued = ProcessInfo.processInfo.systemUptime
        queue.async {
            let before = ProcessInfo.processInfo.systemUptime
            var value = row; value["enqueuedUptime"] = enqueued
            value["journalStartUptime"] = before; value["priorWrites"] = self.costs
            do {
                let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
                self.sequence += 1
                try data.write(to: self.root.appendingPathComponent(String(format: "event-%03d.json", self.sequence)), options: .atomic)
                self.costs.append(["sequence": self.sequence, "beforeUptime": before,
                                   "afterUptime": ProcessInfo.processInfo.systemUptime])
            } catch {
                // Durable error marker, never a fabricated successful event.
                try? String(describing: error).write(to: self.root.appendingPathComponent("journal-error.txt"), atomically: true, encoding: .utf8)
            }
        }
    }
    func start() {
        let t = DispatchSource.makeTimerSource(queue: queue)
        // Polling is background-only; requests are absent during critical taps.
        t.schedule(deadline: .now(), repeating: .milliseconds(2), leeway: .milliseconds(1))
        t.setEventHandler { [weak self] in
            guard let self = self,
                  let data = try? Data(contentsOf: self.root.appendingPathComponent("request.json")),
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let id = value["id"] as? Int, id > self.previousRequest,
                  ["clock", "marker", "ready", "mid", "third", "post", "finish"].contains(value["kind"] as? String ?? "") else { return }
            let received = ProcessInfo.processInfo.systemUptime
            self.previousRequest = id
            if value["kind"] as? String == "clock" {
                let response: [String: Any] = ["id": id, "appReceive": received,
                    "appSend": ProcessInfo.processInfo.systemUptime]
                if let bytes = try? JSONSerialization.data(withJSONObject: response, options: [.sortedKeys]) {
                    try? bytes.write(to: self.root.appendingPathComponent("response.json"), options: .atomic)
                }
            } else {
                self.request?(value)
            }
        }
        timer = t; t.resume()
    }
    func respond(_ value: [String: Any]) {
        queue.async {
            if let bytes = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
                try? bytes.write(to: self.root.appendingPathComponent("response.json"), options: .atomic)
            }
        }
    }
}

@MainActor final class P1VideoProbe: ObservableObject {
    @Published var phase = "starting"
    @Published var marker = 0
    private var journal: P1VideoJournal?
    private var ordinal = 0
    private var scenario = ""
    private var context: (() -> (Int, Bool))?
    private var transition: (() -> Void)?
    private var reopen: (() -> Void)?
    private var now: Double { ProcessInfo.processInfo.systemUptime }

    func start(_ scenario: String, context: @escaping () -> (Int, Bool),
               transition: @escaping () -> Void, reopen: @escaping () -> Void) {
        guard journal == nil else { return }
        self.scenario = scenario; self.context = context
        self.transition = transition; self.reopen = reopen
        do {
            let journal = try P1VideoJournal(scenario: scenario); self.journal = journal
            journal.request = { [weak self] value in
                Task { @MainActor in self?.receive(value) }
            }
            phase = "calibrating-pre"
            journal.append(["type": "start", "uptime": now, "scenario": scenario,
                "schema": "p1-video-events-v1", "admissionEligible": false])
            journal.start()
        } catch { phase = "failed" }
    }
    private func receive(_ row: [String: Any]) {
        guard let id = row["id"] as? Int, let kind = row["kind"] as? String else { return }
        let before = now
        switch kind {
        case "marker":
            guard let value = row["marker"] as? Int, value > 0 && value < 65536,
                  phase.hasPrefix("calibrating-") else { return }
            marker = value
        case "ready": guard phase == "calibrating-pre" else { return }; phase = "ready"
        case "mid": guard phase == "awaiting-mid" else { return }; phase = "calibrating-mid"
        case "third": guard phase == "calibrating-mid" else { return }; phase = "third-ready"
        case "post": guard phase == "awaiting-post" else { return }; phase = "calibrating-post"
        case "finish": guard phase == "calibrating-post" else { return }; phase = "finished"
        default: return
        }
        journal?.append(["type": "command", "id": id, "kind": kind, "uptime": before,
                         "afterUptime": now, "phase": phase, "marker": marker])
        journal?.respond(["id": id, "phase": phase, "marker": marker,
                           "appReceive": before, "appSend": now])
    }
    func clipboard(_ value: String, expected: String, changeCount: Int) {
        guard ["ready", "active", "third-ready"].contains(phase), let context = context else { return }
        let before = now; let snapshot = context(); ordinal += 1
        let driver = phase == "third-ready" ? "normal-XCTest-third-tap" : ordinal == 1 ? "normal-XCTest-tap" : "experimental-XCTest-coordinate-tap"
        let eventOrdinal = ordinal
        defer {
            journal?.append(["type": "clipboard", "ordinal": eventOrdinal, "uptime": before,
                "payload": value == expected ? value : "[redacted-unexpected-pasteboard]",
                "expectedPayload": expected, "clipboardExact": value == expected,
                "changeCount": changeCount, "generation": snapshot.0, "shown": snapshot.1,
                "driver": driver, "callbackBeforeUptime": before, "callbackAfterUptime": now])
        }
        phase = "active"
        if ordinal == 1 {
            if scenario != "timeout" {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.75) { [weak self] in
                    guard let self = self else { return }
                    self.transition?(); self.record(self.scenario == "replacement" ? "replace" : "dismiss")
                }
                if scenario == "dismissal" {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.05) { [weak self] in
                        guard let self = self else { return }; self.reopen?(); self.record("reopen")
                    }
                }
            }
            // Long enough for a missed second tap to be recorded as a miss.
            // Increasing this window never changes the <2 s overlap threshold.
            DispatchQueue.main.asyncAfter(deadline: .now() + 12) { [weak self] in
                self?.phase = "awaiting-mid"
                self?.journal?.append(["type": "window-end", "uptime": self?.now ?? 0])
            }
        } else if driver == "normal-XCTest-third-tap" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 5.25) { [weak self] in self?.phase = "awaiting-post"
                self?.journal?.append(["type": "post-ready", "uptime": self?.now ?? 0])
            }
        }
    }
    private func record(_ kind: String) {
        let snapshot = context?() ?? (-1, false)
        journal?.append(["type": "transition", "kind": kind, "uptime": now,
                          "generation": snapshot.0, "shown": snapshot.1])
    }
    func markerGeometry(_ rect: CGRect) {
        let screen = UIScreen.main
        journal?.append(["type": "marker-geometry", "uptime": now,
            "rect": [rect.minX, rect.minY, rect.width, rect.height],
            "screenPoints": [screen.bounds.width, screen.bounds.height], "scale": screen.scale])
    }
    // A timeout scenario has no third tap. The host requests a post window only
    // after its mid-calibration; this fixture control does not copy anything.
    func timeoutPost() {
        if scenario == "timeout" && phase == "third-ready" {
            phase = "awaiting-post"; journal?.append(["type": "post-ready", "uptime": now])
        }
    }
}

private struct P1VideoMarker: View {
    let value: Int
    private var bits: [Bool] {
        [false, true, false, true] + (0..<16).map { (value >> $0) & 1 == 1 } + [true, false, true, false]
    }
    var body: some View {
        HStack(spacing: 0) {
            ForEach(0..<24, id: \.self) { index in
                Rectangle().fill(bits[index] ? Color.white : Color.black).frame(width: 8, height: 16)
            }
        }.frame(width: 192, height: 16).accessibilityElement(children: .ignore)
            .accessibilityLabel("Calibration marker").accessibilityIdentifier("p1-video-marker")
    }
}

@MainActor struct P1VideoPromptScreen: View {
    @State private var generation = 0
    @State private var shown = true
    @State private var submitting = false
    @StateObject private var probe = P1VideoProbe()
    private var scenario: String {
        let a = ProcessInfo.processInfo.arguments
        guard let i = a.firstIndex(of: "--scenario"), i + 1 < a.count else { return "timeout" }; return a[i + 1]
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
            }.navigationTitle("P1 video probe")
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 4) {
                    P1VideoMarker(value: probe.marker)
                        .background(GeometryReader { geometry in
                            Color.clear.onAppear { probe.markerGeometry(geometry.frame(in: .global)) }
                                .onChange(of: probe.phase) { phase in
                                    if phase == "calibrating-pre" { probe.markerGeometry(geometry.frame(in: .global)) }
                                }
                        })
                    Text(probe.phase).accessibilityIdentifier("p1-video-phase")
                }.padding(4).background(Color(.systemBackground))
            }
        }.navigationViewStyle(.stack)
        .onAppear {
            probe.start(scenario, context: { (generation, shown) }, transition: {
                if scenario == "replacement" { generation += 1 } else { shown = false }
            }, reopen: { shown = true })
        }
        .onChange(of: probe.phase) { _ in probe.timeoutPost() }
        .onReceive(NotificationCenter.default.publisher(for: UIPasteboard.changedNotification)) { _ in
            probe.clipboard(UIPasteboard.general.string ?? "", expected: diagnostic,
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
                else { P1VideoPromptScreen() }
            }.environment(\.sizeCategory, ProcessInfo.processInfo.arguments.contains("--largest")
                ? .accessibilityExtraExtraExtraLarge : .large)
        }
    }
}
