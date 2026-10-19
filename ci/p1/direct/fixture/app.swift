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
    private var stripRows: [[String: Any]] = []
    private var stripBatch = 0
    private var stripCount = 0
    private var stripWriteCosts: [[String: Any]] = []
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
    // Small immutable draw receipts are batched on the background queue. This
    // avoids a main-thread file write and quadratic prior-write inventories.
    func stripDraw(_ row: [String: Any]) {
        let enqueued = ProcessInfo.processInfo.systemUptime
        queue.async {
            var value = row; value["enqueuedUptime"] = enqueued
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
                "batches": self.stripBatch, "stoppedUptime": uptime, "writeCosts": self.stripWriteCosts,
                "journalCompleteUptime": ProcessInfo.processInfo.systemUptime, "admissionEligible": false]
            if let bytes = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) {
                try? bytes.write(to: self.root.appendingPathComponent("strip-complete.json"), options: .atomic)
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
                  ["clock", "ready", "mid", "third", "post", "finish"].contains(value["kind"] as? String ?? "") else { return }
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
            directAnchorReceipts.attach(journal.append)
            journal.start()
        } catch { phase = "failed" }
    }
    private func receive(_ row: [String: Any]) {
        guard let id = row["id"] as? Int, let kind = row["kind"] as? String else { return }
        let before = now
        switch kind {
        case "ready": guard phase == "calibrating-pre" else { return }; phase = "ready"
        case "mid": guard phase == "awaiting-mid" else { return }; phase = "calibrating-mid"
        case "third": guard phase == "calibrating-mid" else { return }; phase = "third-ready"
        case "post": guard phase == "awaiting-post" else { return }; phase = "calibrating-post"
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
    private let directAnchorReceipts = P1DirectAnchorReceiptBuffer()
    func directAnchorDraw(_ row: [String: Any]) { directAnchorReceipts.append(row) }
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
        .overlay(P1DirectRegistrationOverlay(receipt: probe.directAnchorDraw))
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

enum P1WindowCapturePacket {
    static let columns = 38
    static let rows = 22
    static let maximumMarker: UInt32 = 3600

    // CRC-32/ISO-HDLC, polynomial 0x04C11DB7 reflected as 0xEDB88320.
    static func checksum(_ bytes: [UInt8]) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for byte in bytes {
            crc ^= UInt32(byte)
            for _ in 0..<8 {
                crc = (crc >> 1) ^ ((crc & 1) == 1 ? 0xEDB88320 : 0)
            }
        }
        return crc ^ 0xFFFFFFFF
    }

    static func bytes(nonce: [UInt8], marker: UInt32) -> [UInt8] {
        precondition(nonce.count == 16 && marker > 0 && marker <= maximumMarker)
        // P1WC + v1 + full 128-bit nonce + big-endian marker + reserved + CRC.
        var packet: [UInt8] = [0x50, 0x31, 0x57, 0x43, 0x01] + nonce
        packet += [24, 16, 8, 0].map { UInt8(truncatingIfNeeded: marker >> $0) }
        packet += [0, 0, 0]
        let crc = checksum(packet)
        packet += [24, 16, 8, 0].map { UInt8(truncatingIfNeeded: crc >> $0) }
        precondition(packet.count == 32)
        return packet
    }
}

// Fixture-only static registration. Pixels prove session correspondence only.
// Native compilation and placement remain unverified in this local draft.
// Retain draws that precede the screen's onAppear/probe.start. MainActor serializes
// append/attach. At most 520 draw rows plus one reserved failure row can wait;
// overflow is a terminal error, never an eligible truncated receipt stream.
@MainActor private final class P1DirectAnchorReceiptBuffer {
    private static let maxDrawRows = 520 // Eight views: 64 draws plus terminal draw 65.
    private var pending = [[String: Any]]()
    private var sink: (([String: Any]) -> Void)?
    private var drawRows = 0
    private var failed = false
    private var initialInventorySent = false
    private var session: String?
    private var nextDraw = [String: Int]()
    private var firstDraws = Set<String>()

    private func emit(_ row: [String: Any]) {
        if let sink = sink { sink(row) } else { pending.append(row) }
    }
    private func fail(_ reason: String) {
        guard !failed else { return }; failed = true
        emit(["type":"direct-anchor-receipt-error", "schema":"p1-direct-anchor-receipt-error-v1",
              "session":session ?? "unavailable", "uptime":ProcessInfo.processInfo.systemUptime,
              "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
              "displayTimeEstablished":false, "admissionEligible":false, "error":reason,
              "laterDrawReceiptsSuppressed":true])
    }
    func append(_ row: [String: Any]) {
        guard !failed else { return }
        guard drawRows < Self.maxDrawRows else { fail("anchor-receipt-cap-exceeded"); return }
        drawRows += 1; emit(row)
        guard row["error"] == nil,
              let value = row["session"] as? String,
              let ordinal = row["anchor"] as? UInt32, (1...4).contains(ordinal),
              let source = row["source"] as? String, ["packet", "feature"].contains(source),
              let draw = row["draw"] as? Int, (1...64).contains(draw),
              draw == (nextDraw["\(source)-\(ordinal)"] ?? 1),
              session == nil || session == value else {
            fail("invalid-anchor-receipt-sequence"); return
        }
        session = value; nextDraw["\(source)-\(ordinal)"] = draw + 1
        if draw == 1 { firstDraws.insert("\(source)-\(ordinal)") }
        initialInventoryIfReady()
    }
    func attach(_ value: @escaping ([String: Any]) -> Void) {
        guard sink == nil else { fail("duplicate-anchor-journal-attachment"); return }
        sink = value
        for row in pending { value(row) }
        pending.removeAll(keepingCapacity: false)
        initialInventoryIfReady()
    }
    private func initialInventoryIfReady() {
        guard !failed, !initialInventorySent, let sink = sink, let session = session,
              firstDraws == Set(["packet", "feature"].flatMap { source in (1...4).map { "\(source)-\($0)" } }) else { return }
        initialInventorySent = true
        // append() has enqueued all eight source-tagged rows on the journal's serial queue.
        // This is NOT durability or presentation proof: the host must retrieve
        // this event and each of the eight earlier draw=1 rows before release.
        sink(["type":"direct-anchor-initial-draws", "schema":"p1-direct-anchor-initial-draws-v1",
              "session":session,
              "firstDrawSources":["packet", "feature"].flatMap { source in
                  (1...4).map { ["source":source, "anchor":$0] as [String:Any] }
              }, "initialDrawsEnqueued":true,
              "retainedEvidenceRequired":true, "uptime":ProcessInfo.processInfo.systemUptime,
              "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
              "displayTimeEstablished":false, "admissionEligible":false])
    }
}

private struct P1DirectRegistrationConfiguration {
    let session: String
    let nonce: [UInt8]
    init?(_ arguments: [String]) {
        guard arguments.filter({ $0 == "--session" }).count == 1,
              let at = arguments.firstIndex(of: "--session"), at + 1 < arguments.count else { return nil }
        let value = arguments[at + 1], bytes = Array(value.utf8)
        guard bytes.count == 32, bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        func digit(_ byte: UInt8) -> UInt8 { byte < 58 ? byte - 48 : byte - 87 }
        session = value
        nonce = stride(from: 0, to: 32, by: 2).map { digit(bytes[$0]) * 16 + digit(bytes[$0 + 1]) }
    }
}

@MainActor private final class P1DirectAnchorView: UIView {
    private let configuration: P1DirectRegistrationConfiguration
    private let ordinal: UInt32
    private let receipt: ([String: Any]) -> Void
    private var draws = 0
    private var failed = false
    init(configuration: P1DirectRegistrationConfiguration, ordinal: UInt32,
         receipt: @escaping ([String: Any]) -> Void) {
        self.configuration = configuration; self.ordinal = ordinal; self.receipt = receipt
        super.init(frame: .zero)
        isOpaque = true; backgroundColor = .white; contentMode = .redraw; clipsToBounds = true
        isAccessibilityElement = true
        accessibilityIdentifier = "p1-direct-anchor-\(ordinal)"
        accessibilityLabel = "Direct measurement registration \(ordinal)"
        isUserInteractionEnabled = false
    }
    required init?(coder: NSCoder) { fatalError("fixture-only initializer") }
    override func draw(_ rect: CGRect) {
        guard !failed else { return }
        let before = ProcessInfo.processInfo.systemUptime
        draws += 1
        guard draws <= 64, bounds.width == 114, bounds.height == 66,
              let context = UIGraphicsGetCurrentContext() else {
            failed = true
            receipt(["type":"direct-anchor-draw", "session":configuration.session,
                     "schema":"p1-direct-anchor-draw-v1", "uptime":before,
                     "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
                     "displayTimeEstablished":false, "admissionEligible":false,
                     "source":"packet", "anchor":ordinal, "draw":draws, "error":"invalid-anchor-draw",
                     "beforeUptime":before, "afterUptime":ProcessInfo.processInfo.systemUptime])
            return
        }
        context.setShouldAntialias(false)
        context.setFillColor(UIColor.white.cgColor); context.fill(bounds)
        let packet = P1WindowCapturePacket.bytes(nonce: configuration.nonce, marker: ordinal)
        func fill(_ x: Int, _ y: Int, _ width: Int, _ height: Int, white: Bool) {
            context.setFillColor((white ? UIColor.white : UIColor.black).cgColor)
            context.fill(CGRect(x:CGFloat(x*3),y:CGFloat(y*3),width:CGFloat(width*3),height:CGFloat(height*3)))
        }
        fill(1,1,36,20,white:false); fill(2,2,34,18,white:true)
        for bitIndex in 0..<256 {
            let bit = (packet[bitIndex/8] >> (7-bitIndex%8)) & 1 == 1
            let cell = bitIndex*2
            fill(3+cell%32,3+cell/32,1,1,white:bit)
            fill(4+cell%32,3+cell/32,1,1,white:!bit)
        }
        let after = ProcessInfo.processInfo.systemUptime
        receipt(["type":"direct-anchor-draw", "session":configuration.session,
                 "schema":"p1-direct-anchor-draw-v1", "uptime":before,
                 "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
                 "admissionEligible":false,
                 "source":"packet", "anchor":ordinal, "draw":draws, "beforeUptime":before,
                 "afterUptime":after, "displayTimeEstablished":false])
    }
}

@MainActor private struct P1DirectAnchor: UIViewRepresentable {
    let configuration: P1DirectRegistrationConfiguration
    let ordinal: UInt32
    let receipt: ([String: Any]) -> Void
    func makeUIView(context: Context) -> P1DirectAnchorView {
        P1DirectAnchorView(configuration:configuration,ordinal:ordinal,receipt:receipt)
    }
    func updateUIView(_ view: P1DirectAnchorView, context: Context) {}
}

// Explicit source-locality premise for the host interval adapter: qualifying
// magenta belongs exclusively to this source-bound, clipped UIView. Its whole
// actual AX rectangle is measured; no ideal pixel edge or center is asserted.
// UIKit/compositor filtering behavior still requires native validation.
@MainActor private final class P1DirectFeatureView: UIView {
    private let configuration: P1DirectRegistrationConfiguration
    private let ordinal: UInt32
    private let receipt: ([String: Any]) -> Void
    private var draws = 0
    private var failed = false
    init(configuration: P1DirectRegistrationConfiguration, ordinal: UInt32,
         receipt: @escaping ([String: Any]) -> Void) {
        self.configuration = configuration; self.ordinal = ordinal; self.receipt = receipt
        super.init(frame: .zero)
        isOpaque = true; backgroundColor = .clear; contentMode = .redraw; clipsToBounds = true
        isAccessibilityElement = true
        accessibilityIdentifier = "p1-direct-feature-\(ordinal)"
        accessibilityLabel = "Direct measurement registration feature \(ordinal)"
        isUserInteractionEnabled = false
    }
    required init?(coder: NSCoder) { fatalError("fixture-only initializer") }
    override func draw(_ rect: CGRect) {
        guard !failed else { return }
        let before = ProcessInfo.processInfo.systemUptime
        draws += 1
        guard draws <= 64, bounds.width == 3, bounds.height == 3,
              let context = UIGraphicsGetCurrentContext() else {
            failed = true
            receipt(["type":"direct-anchor-draw", "session":configuration.session,
                     "schema":"p1-direct-anchor-draw-v1", "uptime":before,
                     "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
                     "displayTimeEstablished":false, "admissionEligible":false,
                     "source":"feature", "anchor":ordinal, "draw":draws, "error":"invalid-feature-draw",
                     "beforeUptime":before, "afterUptime":ProcessInfo.processInfo.systemUptime])
            return
        }
        context.setShouldAntialias(false)
        context.setFillColor(UIColor(red:1,green:0,blue:1,alpha:1).cgColor)
        context.fill(bounds)
        let after = ProcessInfo.processInfo.systemUptime
        receipt(["type":"direct-anchor-draw", "session":configuration.session,
                 "schema":"p1-direct-anchor-draw-v1", "uptime":before,
                 "clock":"app-ProcessInfo.systemUptime", "timingMeaning":"fixture-draw-only",
                 "displayTimeEstablished":false, "admissionEligible":false,
                 "source":"feature", "anchor":ordinal, "draw":draws,
                 "beforeUptime":before, "afterUptime":after])
    }
}

@MainActor private struct P1DirectFeature: UIViewRepresentable {
    let configuration: P1DirectRegistrationConfiguration
    let ordinal: UInt32
    let receipt: ([String: Any]) -> Void
    func makeUIView(context: Context) -> P1DirectFeatureView {
        P1DirectFeatureView(configuration:configuration,ordinal:ordinal,receipt:receipt)
    }
    func updateUIView(_ view: P1DirectFeatureView, context: Context) {}
}

@MainActor private struct P1DirectRegistrationOverlay: View {
    let receipt: ([String: Any]) -> Void
    // Fixed observer-only lift: native run 39262135354 exposed marker overlap.
    // Move each bottom packet and its feature together; never move production UI.
    private static let bottomRegistrationLift: CGFloat = 96
    var body: some View {
        GeometryReader { geometry in
            if let configuration = P1DirectRegistrationConfiguration(ProcessInfo.processInfo.arguments),
               geometry.size.width >= 244, geometry.size.height >= 148 + Self.bottomRegistrationLift {
                ForEach(1...4, id: \.self) { value in
                    P1DirectAnchor(configuration:configuration,ordinal:UInt32(value),receipt:receipt)
                        .frame(width:114,height:66)
                        .position(x:(value == 1 || value == 3) ? 65 : geometry.size.width-65,
                                  y:value <= 2 ? 41 : geometry.size.height-41-Self.bottomRegistrationLift)
                    P1DirectFeature(configuration:configuration,ordinal:UInt32(value),receipt:receipt)
                        .frame(width:3,height:3)
                        .position(x:(value == 1 || value == 3) ? 4.5 : geometry.size.width-4.5,
                                  y:value <= 2 ? 4.5 : geometry.size.height-4.5-Self.bottomRegistrationLift)
                }
            } else {
                Color.red.accessibilityIdentifier("p1-direct-registration-error")
            }
        }.allowsHitTesting(false)
    }
}
