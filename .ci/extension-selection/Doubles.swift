import Foundation
import CoreFoundation

// Only platform models, operation infrastructure and prompt transport are doubles.
// The policy, handler decision, operation and filesystem deletion are real source.
final class ALTApplication: Hashable, @unchecked Sendable {
    var isAltStoreApp = false
    let bundleIdentifier: String
    let fileURL: URL
    private let children: Set<ALTApplication>
    init(_ id: String, _ url: URL, children: Set<ALTApplication> = []) {
        bundleIdentifier = id; fileURL = url; self.children = children
    }
    var appExtensions: Set<ALTApplication> {
        Set(children.filter { FileManager.default.fileExists(atPath: $0.fileURL.path) })
    }
    static func ==(l: ALTApplication, r: ALTApplication) -> Bool { l.fileURL == r.fileURL }
    func hash(into h: inout Hasher) { h.combine(fileURL) }
}
extension Bundle {
    enum Info { static let activeBundleIdentifier = "example.fixture.host" }
}
enum OperationError: Error { case invalidParameters(String), cancelled }
struct OperationsLoggingControl { static func isLoggingEnabled<T>(for type: T.Type) -> Bool { false } }
func debugLog(_ value: String) {}
func verboseLog(_ value: String) {}
class BasePipelineOperation<C, R> {
    let context: C
    let progress = Progress(totalUnitCount: 100)
    init(context: C) throws { self.context = context }
    func execute(parentProgress: Progress?) async throws -> R { fatalError("abstract") }
    func executePreconditionCheck(parentProgress: Progress?) async throws {}
    func setProgress(_ value: Int64) { progress.completedUnitCount = value }
}
final class InstallAppOperationContext {
    // These existing cases never request replacement. Its source-owned suite
    // exercises that path; fail if this ordinary-path boundary is crossed.
    let legacyReplacementBinding: V3LegacyReplacementBinding? = nil
    func validateLegacyReplacementAdmission() async throws { fatalError("Unexpected replacement admission in ordinary fixture") }
    func validateLegacyReplacementBundle(_ app: ALTApplication, signed: Bool) throws { fatalError("Unexpected replacement bundle in ordinary fixture") }

    var targetAppBundle: ALTApplication?
    var useMainProfile = false
    var validatedReuseMain = false
    let handler: TestPipelineHandler
    init(_ app: ALTApplication, _ handler: TestHandler) { targetAppBundle = app; self.handler = TestPipelineHandler(handler) }
}
final class TestPipelineHandler {
    let extensionRemovalHandler: TestHandler
    init(_ h: TestHandler) { extensionRemovalHandler = h }
}
extension UserDefaults {
    var customizeAppExtensions: AppExtensionCustomization {
        get { AppExtensionCustomization(rawValue: string(forKey: "fixture.customize") ?? "prompt-user")! }
        set { set(newValue.rawValue, forKey: "fixture.customize") }
    }
}
