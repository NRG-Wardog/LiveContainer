// Calibration-only fixture. Production prompt is extracted separately, unchanged.
import Foundation
import SwiftUI
import UIKit
import CoreFoundation

// Fixture-owned transport only. It never reads or mutates production copied
// state, invokes a production action, or rasterizes the application window.
private final class P1VideoJournal {
    let root: URL
    private let queue = DispatchQueue(label: "p1.video.journal", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var sequence = 0
    private var previousRequest = 0
    private let session: String
    private var pending: [String: Any]?
    private var costs: [[String: Any]] = []
    private var stripRows: [[String: Any]] = []
    private var stripBatch = 0
    private var stripCount = 0
    private var stripWriteCosts: [[String: Any]] = []
    var request: (([String: Any]) -> Void)?
    init(scenario: String) throws {
        precondition(scenario == "capability")
        let args = ProcessInfo.processInfo.arguments
        guard let at = args.firstIndex(of: "--session"), at + 1 < args.count,
              args[at + 1].range(of: "^[a-f0-9]{32}$", options: .regularExpression) != nil else {
            throw NSError(domain: "P1Capability", code: 1)
        }
        session = args[at + 1]
        root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("p1-capability-app/" + session, isDirectory: true)
        guard !FileManager.default.fileExists(atPath: root.path) else {
            throw NSError(domain: "P1Video", code: 1, userInfo: [NSLocalizedDescriptionKey: "fresh scenario required"])
        }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let identity: [String: Any] = ["schema": "p1-capability-app-v1", "session": session,
            "bundleIdentifier": Bundle.main.bundleIdentifier ?? "", "admissionEligible": false]
        try JSONSerialization.data(withJSONObject: identity, options: [.sortedKeys])
            .write(to: root.appendingPathComponent("identity.json"), options: .atomic)
    }
    func append(_ row: [String: Any]) {
        let enqueued = ProcessInfo.processInfo.systemUptime
        queue.async {
            let before = ProcessInfo.processInfo.systemUptime
            var value = row; value["session"] = self.session; value["enqueuedUptime"] = enqueued
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
    // Small immutable draw receipts are batched on the background queue. This
    // avoids a main-thread file write and quadratic prior-write inventories.
    func stripDraw(_ row: [String: Any]) {
        let enqueued = ProcessInfo.processInfo.systemUptime
        queue.async {
            var value = row; value["session"] = self.session; value["enqueuedUptime"] = enqueued
            value["journalStartUptime"] = ProcessInfo.processInfo.systemUptime
            self.stripRows.append(value); self.stripCount += 1
            if self.stripRows.count == 30 { self.flushStrip() }
        }
    }
    private func flushStrip() {
        guard !stripRows.isEmpty else { return }
        let before = ProcessInfo.processInfo.systemUptime
        stripBatch += 1
        do {
            let value: [String: Any] = ["schema": "p1-strip-batch-v1", "batch": stripBatch,
                "writeBeforeUptime": before, "draws": stripRows]
            let bytes = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            try bytes.write(to: root.appendingPathComponent(String(format: "strip-%04d.json", stripBatch)), options: .atomic)
            stripWriteCosts.append(["batch": stripBatch, "beforeUptime": before,
                                    "afterUptime": ProcessInfo.processInfo.systemUptime])
            stripRows.removeAll(keepingCapacity: true)
        } catch {
            try? "strip journal failure".write(to: root.appendingPathComponent("journal-error.txt"), atomically: true, encoding: .utf8)
        }
    }
    func stripStopped(_ uptime: Double) {
        queue.async {
            self.flushStrip()
            let value: [String: Any] = ["schema": "p1-strip-complete-v1", "drawCount": self.stripCount,
                "session": self.session, "batches": self.stripBatch, "stoppedUptime": uptime, "writeCosts": self.stripWriteCosts,
                "journalCompleteUptime": ProcessInfo.processInfo.systemUptime, "admissionEligible": false]
            if let bytes = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
                try? bytes.write(to: self.root.appendingPathComponent("strip-complete.json"), options: .atomic)
            }
        }
    }
    private func fail(_ reason: String) {
        try? reason.write(to: root.appendingPathComponent("journal-error.txt"), atomically: true, encoding: .utf8)
    }
    private func commitResponse(_ response: [String: Any]) {
        guard let request = pending, let id = request["id"] as? Int,
              response["id"] as? Int == id else { fail("response without exact pending request"); return }
        var value = response; value["session"] = session
        do {
            let requestURL = root.appendingPathComponent(String(format: "request-%03d.json", id))
            let responseURL = root.appendingPathComponent(String(format: "response-%03d.json", id))
            guard !FileManager.default.fileExists(atPath: requestURL.path),
                  !FileManager.default.fileExists(atPath: responseURL.path) else { fail("stale durable request"); return }
            try JSONSerialization.data(withJSONObject: request, options: [.sortedKeys]).write(to: requestURL, options: .atomic)
            let bytes = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            try bytes.write(to: responseURL, options: .atomic)
            // The published response is an acknowledgement of these durable bytes.
            try bytes.write(to: root.appendingPathComponent("response.json"), options: .atomic)
            pending = nil
        } catch { fail("durable response write failed") }
    }
    func start() {
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now(), repeating: .milliseconds(2), leeway: .milliseconds(1))
        t.setEventHandler { [weak self] in
            guard let self = self else { return }
            let url = self.root.appendingPathComponent("request.json")
            guard let data = try? Data(contentsOf: url),
                  let row = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let number = row["id"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue == Double(number.intValue) else { return }
            let id = number.intValue
            if id == self.previousRequest { return }
            guard data.count <= 8192,
                  (try? JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .withoutEscapingSlashes])) == data,
                  id == self.previousRequest + 1, id <= 29, self.pending == nil,
                  row["session"] as? String == self.session,
                  let kind = row["kind"] as? String,
                  ["clock", "ready", "capability-mid", "third", "capability-post", "finish"].contains(kind),
                  (try? url.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) != true else {
                self.fail("request session, sequence or kind differs"); return
            }
            let expectedKind: String
            let expectedPhase: String?
            if (1...8).contains(id) { expectedKind = "clock"; expectedPhase = "pre" }
            else if (11...18).contains(id) { expectedKind = "clock"; expectedPhase = "mid" }
            else if (21...28).contains(id) { expectedKind = "clock"; expectedPhase = "post" }
            else { expectedKind = [9: "ready", 10: "capability-mid", 19: "third", 20: "capability-post", 29: "finish"][id] ?? "invalid"; expectedPhase = nil }
            let expectedKeys: Set<String> = expectedPhase == nil ? ["id", "kind", "session"] : ["id", "kind", "session", "phase"]
            guard kind == expectedKind, row["phase"] as? String == expectedPhase,
                  Set(row.keys) == expectedKeys else { self.fail("request protocol order differs"); return }
            let received = ProcessInfo.processInfo.systemUptime
            self.previousRequest = id; self.pending = row
            if kind == "clock" {
                self.commitResponse(["id": id, "appReceive": received,
                                     "appSend": ProcessInfo.processInfo.systemUptime])
            } else { self.request?(row) }
        }
        timer = t; t.resume()
    }
    func respond(_ value: [String: Any]) { queue.async { self.commitResponse(value) } }

}

@MainActor final class P1VideoProbe: ObservableObject {
    @Published var phase = "starting"
    @Published var stripRunning = false
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
            phase = "waiting-baseline"; stripRunning = true
            journal.append(["type": "start", "uptime": now, "scenario": scenario,
                "schema": "p1-video-events-v1", "admissionEligible": false])
            journal.start()
        } catch { phase = "failed" }
    }
    private func receive(_ row: [String: Any]) {
        guard let id = row["id"] as? Int, let kind = row["kind"] as? String else { return }
        let before = now
        switch kind {
        case "ready": guard phase == "calibrating-pre" else { return }; phase = "ready"
        case "capability-mid": guard scenario == "capability" && phase == "ready" else { return }; phase = "calibrating-mid"
        case "third": guard phase == "calibrating-mid" else { return }; phase = "third-ready"
        case "capability-post": guard scenario == "capability" && phase == "third-ready" else { return }; phase = "calibrating-post"
        case "finish":
            guard phase == "calibrating-post" else { return }; phase = "finished"
            // Keep continuous pixels past the predetermined evidence boundary.
            // This never extends or changes a production feedback timer.
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in self?.stripRunning = false }
        default: return
        }
        journal?.append(["type": "command", "id": id, "kind": kind, "uptime": before,
                         "afterUptime": now, "phase": phase])
        journal?.respond(["id": id, "phase": phase,
                           "appReceive": before, "appSend": now])
    }
    func baselineReady() {
        guard phase == "waiting-baseline" else { return }
        let before = now; phase = "calibrating-pre"
        journal?.append(["type": "baseline-ready", "uptime": before, "afterUptime": now,
                          "driver": "normal-XCTest-fixture-ready-tap"])
    }
    func stripDraw(_ row: [String: Any]) { journal?.stripDraw(row) }
    func stripStopped(_ uptime: Double) { journal?.stripStopped(uptime) }
    func clipboard(_ value: String, expected: String, changeCount: Int) {
        guard scenario != "capability", ["ready", "active", "third-ready"].contains(phase), let context = context else { return }
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

// The strip changes only its own UIKit pixels. No SwiftUI body/state update is
// performed per frame, and neither production label nor timer state is read.
@MainActor private final class P1ClockStripView: UIView {
    var receipt: (([String: Any]) -> Void)?
    var stopped: ((Double) -> Void)?
    private var link: CADisplayLink?
    private var running = false
    private var identifier = 0
    private var tickBefore = 0.0
    private var tickAfter = 0.0
    private var displayTimestamp = 0.0
    override init(frame: CGRect) {
        super.init(frame: frame); isOpaque = true; backgroundColor = .black
        isAccessibilityElement = true; accessibilityLabel = "Calibration clock strip"
        accessibilityIdentifier = "p1-video-marker"
    }
    required init?(coder: NSCoder) { fatalError("fixture-only initializer") }
    func setRunning(_ active: Bool) {
        guard active != running else { return }; running = active
        if active {
            tickBefore = ProcessInfo.processInfo.systemUptime; tickAfter = tickBefore
            let value = CADisplayLink(target: self, selector: #selector(tick(_:)))
            value.preferredFrameRateRange = CAFrameRateRange(minimum: 30, maximum: 30, preferred: 30)
            value.add(to: .main, forMode: .common); link = value
        } else {
            link?.invalidate(); link = nil; stopped?(ProcessInfo.processInfo.systemUptime)
        }
    }
    @objc private func tick(_ sender: CADisplayLink) {
        tickBefore = ProcessInfo.processInfo.systemUptime
        displayTimestamp = sender.timestamp // diagnostic scheduler metadata only
        setNeedsDisplay()
        tickAfter = ProcessInfo.processInfo.systemUptime
    }
    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let before = ProcessInfo.processInfo.systemUptime
        if running { identifier += 1 }
        guard identifier < 18000 else { setRunning(false); return }
        let bits = [false, true, false, true] + (0..<16).map { (identifier >> $0) & 1 == 1 } + [true, false, true, false]
        for index in 0..<24 {
            context.setFillColor((bits[index] ? UIColor.white : UIColor.black).cgColor)
            context.fill(CGRect(x: CGFloat(index) * bounds.width / 24, y: 0, width: bounds.width / 24, height: bounds.height))
        }
        let after = ProcessInfo.processInfo.systemUptime
        if running {
            receipt?(["id": identifier, "drawBeforeUptime": before, "drawAfterUptime": after,
                "tickBeforeUptime": tickBefore, "tickAfterUptime": tickAfter,
                "displayLinkTimestamp": displayTimestamp])
        }
    }
}
@MainActor private struct P1VideoMarker: UIViewRepresentable {
    let running: Bool
    let receipt: ([String: Any]) -> Void
    let stopped: (Double) -> Void
    func makeUIView(context: Context) -> P1ClockStripView { P1ClockStripView(frame: .zero) }
    func updateUIView(_ view: P1ClockStripView, context: Context) {
        view.receipt = receipt; view.stopped = stopped; view.setRunning(running)
    }
    static func dismantleUIView(_ view: P1ClockStripView, coordinator: ()) { view.setRunning(false) }
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
                    P1VideoMarker(running: probe.stripRunning, receipt: probe.stripDraw, stopped: probe.stripStopped)
                        .frame(width: 192, height: 16)
                        .background(GeometryReader { geometry in
                            Color.clear.onAppear { probe.markerGeometry(geometry.frame(in: .global)) }
                                .onChange(of: probe.phase) { phase in
                                    if phase == "calibrating-pre" { probe.markerGeometry(geometry.frame(in: .global)) }
                                }
                        })
                    Text(probe.phase).accessibilityIdentifier("p1-video-phase")
                    Button("Baseline ready", action: probe.baselineReady)
                        .accessibilityIdentifier("p1-video-baseline-ready")
                        .disabled(probe.phase != "waiting-baseline")
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
