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
        guard draws <= 64, bounds.width == 2, bounds.height == 2,
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
    var body: some View {
        GeometryReader { geometry in
            if let configuration = P1DirectRegistrationConfiguration(ProcessInfo.processInfo.arguments),
               geometry.size.width >= 244, geometry.size.height >= 148 {
                ForEach(1...4, id: \.self) { value in
                    P1DirectAnchor(configuration:configuration,ordinal:UInt32(value),receipt:receipt)
                        .frame(width:114,height:66)
                        .position(x:(value == 1 || value == 3) ? 65 : geometry.size.width-65,
                                  y:value <= 2 ? 41 : geometry.size.height-41)
                    P1DirectFeature(configuration:configuration,ordinal:UInt32(value),receipt:receipt)
                        .frame(width:2,height:2)
                        .position(x:(value == 1 || value == 3) ? 5 : geometry.size.width-5,
                                  y:value <= 2 ? 5 : geometry.size.height-5)
                }
            } else {
                Color.red.accessibilityIdentifier("p1-direct-registration-error")
            }
        }.allowsHitTesting(false)
    }
}
