import Foundation
import Darwin

// Only the unavailable app-model/error boundary is inert. Foundation copying,
// content fingerprinting, publication, and preservation checks are real.
enum OperationError: Error {
    case invalidApp(reason: String)
}

enum InstalledApp {
    // Each case replaces this before invoking production code. This synthetic
    // location is not the app's CoreData storage or a user's existing cache.
    static var appsDirectoryURL = FileManager.default.temporaryDirectory

    static func payloadURL(forSignature signature: String) -> URL {
        appsDirectoryURL
            .appendingPathComponent("Payloads", isDirectory: true)
            .appendingPathComponent(signature, isDirectory: true)
            .appendingPathComponent("App.app", isDirectory: true)
    }
}
