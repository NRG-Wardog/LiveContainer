// Proposed fixture-only view. Not yet integrated or compiled on an Apple SDK.
// The pixel packet establishes session correspondence, never presentation time.
import Foundation
import SwiftUI
import UIKit
import Darwin

struct P1WindowCaptureConfiguration {
    let session: String
    let nonce: [UInt8]

    static func isRequested(_ arguments: [String]) -> Bool {
        arguments.contains("--window-capture-fixture")
    }

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == "--window-capture-fixture" }).count == 1,
              arguments.filter({ $0 == "--session" }).count == 1,
              !arguments.contains("--recovery"), !arguments.contains("--scenario"),
              let index = arguments.firstIndex(of: "--session"), index + 1 < arguments.count else { return nil }
        let session = arguments[index + 1]
        guard session.utf8.count == 32,
              session.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        let hex = Array(session.utf8)
        func digit(_ byte: UInt8) -> UInt8 { byte < 58 ? byte - 48 : byte - 87 }
        self.session = session
        self.nonce = stride(from: 0, to: 32, by: 2).map { (digit(hex[$0]) << 4) | digit(hex[$0 + 1]) }
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

private enum P1WindowCaptureReady {
    static func publish(session: String, marker: UInt32, before: Double, after: Double) {
        do {
            func check(_ success: Bool) throws {
                if !success { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
            }
            let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("p1-window", isDirectory: true)
            let madeRoot = mkdir(root.path, 0o700)
            try check(madeRoot == 0 || errno == EEXIST)
            let parent = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
            try check(parent >= 0)
            defer { _ = close(parent) }
            // A reused session must fail; the private new directory has one writer.
            try check(mkdirat(parent, session, 0o700) == 0)
            let directory = openat(parent, session, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
            try check(directory >= 0)
            defer { _ = close(directory) }
            var file = openat(directory, ".ready.tmp", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
            try check(file >= 0)
            defer { if file >= 0 { _ = close(file) } }
            let row: [String: Any] = ["schema": "p1-window-fixture-ready-v1", "session": session,
                "marker": marker, "drawBeforeUptime": before, "drawAfterUptime": after,
                "clock": "app-process-systemUptime", "displayTimeEstablished": false,
                "admissionEligible": false]
            let data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            try data.withUnsafeBytes { buffer in
                var offset = 0
                while offset < buffer.count {
                    let count = Darwin.write(file, buffer.baseAddress!.advanced(by: offset), buffer.count - offset)
                    if count < 0 && errno == EINTR { continue }
                    try check(count > 0)
                    offset += count
                }
            }
            try check(fsync(file) == 0)
            let closed = close(file); file = -1
            try check(closed == 0)
            // Atomic publication inside the exclusively created session directory.
            try check(renameat(directory, ".ready.tmp", directory, "ready.json") == 0)
        } catch {
            print("p1-window-fixture-readiness-failed: \(error)")
        }
    }
}

@MainActor private final class P1WindowCaptureBoard: UIView {
    private let nonce: [UInt8]
    private let session: String
    private var link: CADisplayLink?
    private var marker: UInt32 = 0
    private var startedAt: Double?
    private var running = false
    private var terminal = false
    private var readinessAttempted = false

    init(session: String, nonce: [UInt8]) {
        self.session = session
        self.nonce = nonce
        super.init(frame: .zero)
        isOpaque = true
        backgroundColor = .white
        contentMode = .redraw
        isAccessibilityElement = true
        accessibilityIdentifier = "p1-window-capture-board"
        accessibilityLabel = "Session pixel correspondence fixture"
    }
    required init?(coder: NSCoder) { fatalError("fixture-only initializer") }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window == nil { if startedAt != nil { stop() } }
        else if !running && !terminal {
            startedAt = ProcessInfo.processInfo.systemUptime
            running = true
            let timer = CADisplayLink(target: self, selector: #selector(tick(_:)))
            timer.preferredFrameRateRange = CAFrameRateRange(minimum: 30, maximum: 30, preferred: 30)
            timer.add(to: .main, forMode: .common)
            link = timer
            setNeedsDisplay()
        }
    }

    func stop() {
        running = false
        terminal = true
        link?.invalidate()
        link = nil
        setNeedsDisplay()
    }

    @objc private func tick(_ timer: CADisplayLink) {
        guard let start = startedAt, ProcessInfo.processInfo.systemUptime - start < 120,
              marker < P1WindowCapturePacket.maximumMarker else { stop(); return }
        setNeedsDisplay()
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        let drawBefore = ProcessInfo.processInfo.systemUptime
        context.setShouldAntialias(false)
        context.setFillColor(UIColor.white.cgColor)
        context.fill(bounds)
        let cell = floor(min(bounds.width / 38, bounds.height / 22))
        guard running, cell >= 6, marker < P1WindowCapturePacket.maximumMarker else { return }
        marker += 1 // Actual draw ordinal; neither elapsed time nor a presented-frame count.
        let packet = P1WindowCapturePacket.bytes(nonce: nonce, marker: marker)
        let left = floor((bounds.width - cell * 38) / 2)
        let top = floor((bounds.height - cell * 22) / 2)
        func fill(_ x: Int, _ y: Int, _ width: Int, _ height: Int, white: Bool) {
            context.setFillColor((white ? UIColor.white : UIColor.black).cgColor)
            context.fill(CGRect(x: left + CGFloat(x) * cell, y: top + CGFloat(y) * cell,
                                width: CGFloat(width) * cell, height: CGFloat(height) * cell))
        }
        // White quiet zone, black registration ring, white inner ring.
        fill(1, 1, 36, 20, white: false)
        fill(2, 2, 34, 18, white: true)
        // Each data bit has its complement immediately to its right.
        for bitIndex in 0..<256 {
            let bit = (packet[bitIndex / 8] >> (7 - bitIndex % 8)) & 1 == 1
            let cellIndex = bitIndex * 2
            fill(3 + cellIndex % 32, 3 + cellIndex / 32, 1, 1, white: bit)
            fill(4 + cellIndex % 32, 3 + cellIndex / 32, 1, 1, white: !bit)
        }
        let drawAfter = ProcessInfo.processInfo.systemUptime
        if !readinessAttempted {
            readinessAttempted = true
            let currentSession = session, firstMarker = marker
            // The next main-queue block runs after this draw call returns.
            // This is draw readiness, never evidence of compositor presentation.
            DispatchQueue.main.async {
                DispatchQueue.global(qos: .utility).async {
                    P1WindowCaptureReady.publish(session: currentSession, marker: firstMarker,
                        before: drawBefore, after: drawAfter)
                }
            }
        }
    }
}

@MainActor private struct P1WindowCaptureMarker: UIViewRepresentable {
    let session: String
    let nonce: [UInt8]
    func makeUIView(context: Context) -> P1WindowCaptureBoard { P1WindowCaptureBoard(session: session, nonce: nonce) }
    func updateUIView(_ view: P1WindowCaptureBoard, context: Context) {}
    static func dismantleUIView(_ view: P1WindowCaptureBoard, coordinator: ()) { view.stop() }
}

@MainActor struct P1WindowCaptureFixtureScreen: View {
    private let configuration = P1WindowCaptureConfiguration(arguments: ProcessInfo.processInfo.arguments)
    var body: some View {
        VStack(spacing: 12) {
            Text("P1 window capture fixture").font(.headline)
            if let configuration {
                Text(configuration.session).font(.system(size: 12, design: .monospaced))
                    .accessibilityIdentifier("p1-window-capture-session")
                P1WindowCaptureMarker(session: configuration.session, nonce: configuration.nonce)
                    .frame(width: 304, height: 176)
                Text("Session/pixel correspondence only. No feedback timing acceptance.")
                    .font(.footnote).multilineTextAlignment(.center)
            } else {
                Text("Window fixture unavailable: invalid or conflicting launch arguments.")
                    .accessibilityIdentifier("p1-window-capture-invalid")
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
        .foregroundColor(.black)
        .environment(\.sizeCategory, .large)
    }
}
