// Local native adapter support. Uses the source-bound P1RequestReader unchanged.
// Caller provides fresh parent-owned channel directories; no credential access.
import Foundation
import Darwin
import AppKit

struct DirectOwner {
    let pid: pid_t
    let executable: String
    func valid() -> Bool {
        guard let app = NSRunningApplication(processIdentifier: pid), !app.isTerminated,
              app.bundleIdentifier == "com.apple.iphonesimulator",
              app.executableURL?.resolvingSymlinksInPath().path == executable else { return false }
        return true
    }
}

final class DirectRequestChannel {
    private let descriptor: Int32
    private var seen: Data?
    init(_ root: URL) throws {
        descriptor = open(root.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK)
        try require(descriptor >= 0, "direct-channel-open-failed")
        var info = stat()
        guard fstat(descriptor, &info) == 0, (info.st_mode & S_IFMT) == S_IFDIR else {
            close(descriptor); throw Failure("direct-channel-not-directory")
        }
    }
    deinit { close(descriptor) }
    func readOnce() throws -> Data? {
        let observed = try P1RequestReader.read(directory: descriptor)
        try require(observed.discarded == nil, "direct-request-replaced-during-read")
        guard let data = observed.data else {
            try require(seen == nil, "direct-request-removed")
            return nil
        }
        if let previous = seen { try require(data == previous, "direct-request-changed") }
        seen = data
        return data
    }
}

func directObject(_ data: Data, keys: Set<String>) throws -> [String: Any] {
    try require(data.count <= 8192, "direct-request-size")
    guard let row = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw Failure("direct-request-not-object")
    }
    let canonical = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .withoutEscapingSlashes])
    try require(canonical == data && Set(row.keys) == keys, "direct-request-noncanonical-or-schema")
    return row
}

func directInteger(_ value: Any?, maximum: UInt64) throws -> Int {
    guard let number = value as? NSNumber, let integer = exactUnsigned(number), integer <= maximum else {
        throw Failure("direct-request-invalid-integer")
    }
    return Int(integer)
}

func directPlan(_ data: Data, session: String, window: CGWindowID,
                baselineWidth: Int, baselineHeight: Int, baselineStride: Int) throws -> DirectROIPlan {
    let row = try directObject(data, keys: ["schema", "session", "windowID", "geometrySHA256",
                                          "sourceWidth", "sourceHeight", "sourceStride", "regions"])
    try require(row["schema"] as? String == "p1-direct-roi-plan-v1" && row["session"] as? String == session,
                "direct-plan-session-schema")
    try require(try directInteger(row["windowID"], maximum: UInt64(UInt32.max)) == Int(window), "direct-plan-window")
    let width = try directInteger(row["sourceWidth"], maximum: 2048)
    let height = try directInteger(row["sourceHeight"], maximum: 2048)
    let stride = try directInteger(row["sourceStride"], maximum: 16384)
    try require(width == baselineWidth && height == baselineHeight && stride == baselineStride, "direct-plan-baseline-layout")
    guard let geometryHash = row["geometrySHA256"] as? String,
          let regions = row["regions"] as? [[String: Any]], regions.count == 6 else { throw Failure("direct-plan-regions") }
    let parsed: [DirectROI] = try regions.map { value in
        try require(Set(value.keys) == ["role", "x", "y", "width", "height"], "direct-plan-region-fields")
        guard let role = value["role"] as? String else { throw Failure("direct-plan-role") }
        return DirectROI(role: role, x: try directInteger(value["x"], maximum: 2048),
                         y: try directInteger(value["y"], maximum: 2048),
                         width: try directInteger(value["width"], maximum: 2048),
                         height: try directInteger(value["height"], maximum: 2048))
    }
    let plan = DirectROIPlan(session: session, sourceWidth: width, sourceHeight: height,
                             sourceStride: stride, regions: parsed, geometrySHA256: geometryHash)
    try plan.validate(); return plan
}

// Shared absolute limits anchored by the parent before the original XCTest
// command. Stage allowances cannot restart or extend this one-case budget.
final class DirectDeadline {
    private let stage: StageDeadline
    private let directory: URL
    private let observation: UInt64
    private let cleanup: UInt64
    private let numerator: UInt32
    private let denominator: UInt32
    private var cleanupMode = false
    private var ordinal = 0
    private var armedCutoff: UInt64?
    init(_ directory: URL, observation: UInt64, cleanup: UInt64) {
        self.directory = directory; self.stage = StageDeadline(directory)
        self.observation = observation; self.cleanup = cleanup
        var basis = mach_timebase_info_data_t()
        guard mach_timebase_info(&basis) == KERN_SUCCESS && basis.numer > 0 && basis.denom > 0,
              mach_absolute_time() < observation && observation < cleanup else { exit(2) }
        numerator = basis.numer; denominator = basis.denom
        // This separate terminal watchdog is never canceled with a stage.
        let terminal = seconds(until: cleanup)
        DispatchQueue.global().asyncAfter(deadline: .now() + terminal) { [directory] in
            try? write(["schema": "p1-direct-absolute-timeout-v1", "phase": "cleanup-cutoff",
                        "admissionEligible": false], directory.appendingPathComponent("absolute-timeout.json"))
            exit(124)
        }
    }
    private func seconds(until end: UInt64) -> Double {
        let now = mach_absolute_time()
        guard now < end else { return 0 }
        let value = Double(end - now) * Double(numerator) / Double(denominator) / 1_000_000_000
        return max(0, value.nextDown)
    }
    func beginCleanup() { cleanupMode = true }
    func arm(_ maximum: Double, _ phase: String) {
        let cutoff = cleanupMode ? cleanup : observation
        let remaining = seconds(until: cutoff)
        let allowance = min(maximum, remaining)
        guard maximum.isFinite && maximum > 0 && maximum <= 360 && maximum.rounded() == maximum else { exit(2) }
        let product = (UInt64(maximum) * 1_000_000_000).multipliedFullWidth(by: UInt64(denominator))
        let ticks = product.high < UInt64(numerator) ? UInt64(numerator).dividingFullWidth(product).quotient : UInt64.max
        let (candidate, overflow) = mach_absolute_time().addingReportingOverflow(ticks)
        let stageCutoff = min(cutoff, overflow ? UInt64.max : candidate)
        armedCutoff = stageCutoff
        ordinal += 1
        guard maximum.isFinite && maximum > 0 && allowance > 0 && ordinal <= 64 else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": phase,
                        "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
        do {
            try write(["schema": "p1-direct-stage-budget-v1", "phase": phase,
                       "ordinal": ordinal, "maximumSeconds": maximum, "actualAllowanceSeconds": allowance,
                       "absoluteCutoffMach": cutoff, "stageCutoffMach": stageCutoff, "cleanup": cleanupMode, "admissionEligible": false],
                      directory.appendingPathComponent(String(format: "stage-budget-%03d.json", ordinal)))
        } catch { exit(3) }
        // Recompute after receipt I/O so it cannot extend the absolute cutoff.
        stage.arm(min(allowance, seconds(until: stageCutoff)), phase)
    }
    func checkFinal() {
        guard mach_absolute_time() < cleanup else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": "final-result", "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
    }
    func cancel() {
        let limit = armedCutoff ?? (cleanupMode ? cleanup : observation)
        guard mach_absolute_time() < limit else {
            try? write(["schema": "p1-direct-budget-exhausted-v1", "phase": "stage-completion", "admissionEligible": false], directory.appendingPathComponent("budget-exhausted.json"))
            exit(124)
        }
        stage.cancel(); armedCutoff = nil
    }
}

// Bounded diagnostic codes only: never serialize framework descriptions or memory.
func directDiagnosticCode(_ value: String) -> String {
    let bytes = value.utf8
    guard !bytes.isEmpty && bytes.count <= 96 && bytes.allSatisfy({ (97...122).contains($0) || $0 == 45 }) else {
        return "native-capture-error"
    }
    return value
}

// Publish once, without replacing any existing evidence, and fsync both payload
// and parent directory. Existing stage and terminal watchdogs remain armed.
func directWritePrimaryFailure(_ value: [String: Any], directory: URL) throws {
    try require(Set(value.keys) == ["schema", "session", "observedMach", "errorCode", "sinkFailure", "admissionEligible"], "primary-failure-fields")
    guard value["schema"] as? String == "p1-direct-primary-failure-v1",
          value["admissionEligible"] as? Bool == false,
          let session = value["session"] as? String, session.utf8.count == 32,
          session.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
          let code = value["errorCode"] as? String, directDiagnosticCode(code) == code,
          let observed = value["observedMach"] as? UInt64, observed > 0 else { throw Failure("primary-failure-binding") }
    if let sink = value["sinkFailure"] as? [String: Any] {
        guard Set(sink.keys) == ["code", "observedMach"], let code = sink["code"] as? String,
              directDiagnosticCode(code) == code, let ticks = sink["observedMach"] as? UInt64,
              ticks > 0 && ticks <= observed else { throw Failure("primary-failure-sink") }
    } else { try require(value["sinkFailure"] is NSNull, "primary-failure-sink") }
    let bytes = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    try require(!bytes.isEmpty && bytes.count <= 4096, "primary-failure-size")
    let parent = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK)
    try require(parent >= 0, "primary-failure-directory")
    defer { close(parent) }
    let temporary = "primary-failure.pending"
    let descriptor = openat(parent, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_NONBLOCK, 0o600)
    try require(descriptor >= 0, "primary-failure-open")
    defer { close(descriptor); unlinkat(parent, temporary, 0) }
    try bytes.withUnsafeBytes { raw in
        guard let base = raw.baseAddress else { throw Failure("primary-failure-empty") }
        var offset = 0
        while offset < raw.count {
            let count = Darwin.write(descriptor, base.advanced(by: offset), raw.count - offset)
            if count < 0 && errno == EINTR { continue }
            try require(count > 0, "primary-failure-write")
            offset += count
        }
    }
    try require(fsync(descriptor) == 0, "primary-failure-sync")
    // Exclusive atomic rename preserves the host single-link file invariant.
    try require(renameatx_np(parent, temporary, parent, "primary-failure.json", UInt32(RENAME_EXCL)) == 0, "primary-failure-publish")
    try require(fsync(parent) == 0, "primary-failure-directory-sync")
}

// Best-effort diagnostic sidecar only. No queue drain, no admission significance.
// Primary publication has already been attempted; watchdogs stay armed.
func directWriteStartupDiagnostic(_ value: [String: Any], directory: URL) throws {
    let bytes = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    try require(!bytes.isEmpty && bytes.count <= 32768, "startup-diagnostic-size")
    let parent = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK)
    try require(parent >= 0, "startup-diagnostic-directory")
    defer { close(parent) }
    let temporary = "startup-persistence.pending"
    let descriptor = openat(parent, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_NONBLOCK, 0o600)
    try require(descriptor >= 0, "startup-diagnostic-open")
    defer { close(descriptor); unlinkat(parent, temporary, 0) }
    try bytes.withUnsafeBytes { raw in
        guard let base = raw.baseAddress else { throw Failure("startup-diagnostic-empty") }
        var offset = 0
        while offset < raw.count {
            let count = Darwin.write(descriptor, base.advanced(by: offset), raw.count - offset)
            if count < 0 && errno == EINTR { continue }
            try require(count > 0, "startup-diagnostic-write")
            offset += count
        }
    }
    try require(renameatx_np(parent, temporary, parent, "startup-persistence.json", UInt32(RENAME_EXCL)) == 0, "startup-diagnostic-publish")
}
