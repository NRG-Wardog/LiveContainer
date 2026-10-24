private enum FixtureFailure: Error, CustomStringConvertible {
    case failed(String)
    var description: String {
        switch self { case .failed(let message): return message }
    }
}

private struct SnapshotNode: Equatable {
    let kind: String
    let permissions: Int
    let contents: Data
}

private struct CaseResult: Encodable {
    let name: String
    let passed: Bool
}

private struct RuntimeReport: Encodable {
    let schema = "install-chain-runtime-v1"
    let group = "cache"
    let cases: [CaseResult]
    let passed: Bool
    let native_signing_device_executed = false
    let failure_details: [String: String]
}

private final class CacheFixtureRunner {
    private let fm = FileManager.default
    private var results: [CaseResult] = []
    private var failures: [String: String] = [:]

    private func require(_ condition: Bool, _ message: String) throws {
        if !condition { throw FixtureFailure.failed(message) }
    }

    private func fingerprint(_ url: URL) throws -> String {
        guard let value = AppBundleFingerprint.compute(for: url) else {
            throw FixtureFailure.failed("A regular synthetic bundle was not fingerprintable")
        }
        return value
    }

    private func snapshot(_ root: URL) throws -> [String: SnapshotNode] {
        var nodes: [String: SnapshotNode] = [:]
        func visit(_ url: URL, _ relative: String) throws {
            let values = try url.resourceValues(forKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey])
            if values.isSymbolicLink == true {
                let target = try fm.destinationOfSymbolicLink(atPath: url.path)
                nodes[relative] = SnapshotNode(kind: "link", permissions: 0, contents: Data(target.utf8))
                return // Snapshot links without reading their destinations.
            }
            let attributes = try fm.attributesOfItem(atPath: url.path)
            let permissions = (attributes[.posixPermissions] as? NSNumber)?.intValue ?? -1
            if values.isDirectory == true {
                nodes[relative] = SnapshotNode(kind: "directory", permissions: permissions, contents: Data())
                for child in try fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil).sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                    try visit(child, relative + "/" + child.lastPathComponent)
                }
            } else if values.isRegularFile == true {
                nodes[relative] = SnapshotNode(kind: "file", permissions: permissions, contents: try Data(contentsOf: url))
            } else {
                throw FixtureFailure.failed("Unexpected fixture filesystem entry")
            }
        }
        try visit(root, ".")
        return nodes
    }

    private func inode(_ url: URL) throws -> UInt64 {
        let attributes = try fm.attributesOfItem(atPath: url.path)
        guard let number = attributes[.systemFileNumber] as? NSNumber else {
            throw FixtureFailure.failed("Filesystem did not expose the synthetic directory identity")
        }
        return number.uint64Value
    }

    private func noStagingRemains() throws {
        let paths = try snapshot(InstalledApp.appsDirectoryURL).keys
        try require(!paths.contains { path in
            path.split(separator: "/").contains { $0.hasPrefix(".preservation-") }
        }, "An unpublished preservation staging directory remained")
    }

    private func withFixture(_ body: (URL) throws -> Void) throws {
        let root = fm.temporaryDirectory.appendingPathComponent("install-chain-cache-" + UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: false)
        defer { try? fm.removeItem(at: root) } // Only the directory owned by this case.
        InstalledApp.appsDirectoryURL = root.appendingPathComponent("Apps", isDirectory: true)
        try fm.createDirectory(at: InstalledApp.appsDirectoryURL, withIntermediateDirectories: false)
        try body(root)
    }

    private func makeApp(_ root: URL, contents: String = "AAAA") throws -> URL {
        let app = root.appendingPathComponent("Input.app", isDirectory: true)
        try fm.createDirectory(at: app, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o755])
        let plist: [String: Any] = ["CFBundleIdentifier": "invalid.synthetic.cache-fixture", "CFBundleExecutable": "Payload.bin"]
        let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try data.write(to: app.appendingPathComponent("Info.plist"))
        try Data(contents.utf8).write(to: app.appendingPathComponent("Payload.bin"))
        try Data("synthetic-hidden-byte".utf8).write(to: app.appendingPathComponent(".fixture-marker"))
        for name in ["Info.plist", "Payload.bin", ".fixture-marker"] {
            try fm.setAttributes([.posixPermissions: 0o644], ofItemAtPath: app.appendingPathComponent(name).path)
        }
        return app
    }

    private func expectInvalidApp(_ body: () throws -> Void) throws {
        do {
            try body()
        } catch OperationError.invalidApp(reason: _) {
            return
        } catch {
            throw FixtureFailure.failed("Expected invalidApp, received a different error")
        }
        throw FixtureFailure.failed("Expected invalidApp, but caching succeeded")
    }

    private func expectAnyError(_ body: () throws -> Void) throws {
        do { try body() } catch { return }
        throw FixtureFailure.failed("Expected filesystem failure, but caching succeeded")
    }

    private func record(_ name: String, _ body: () throws -> Void) {
        do {
            try body()
            results.append(CaseResult(name: name, passed: true))
        } catch {
            results.append(CaseResult(name: name, passed: false))
            failures[name] = String(describing: error)
        }
    }

    func run() {
        record("new_cache_publishes_verified_payload") {
            try withFixture { root in
                let source = try makeApp(root)
                let before = try snapshot(source)
                let expected = try fingerprint(source)
                let result = try CacheAppOperation.cachePayload(for: source)
                try require(result.signature == expected, "Returned signature did not match the original content")
                try require(result.targetFileURL == InstalledApp.payloadURL(forSignature: expected), "Unexpected synthetic cache destination")
                try require(expected.hasPrefix("content-v1-"), "Content key version is missing")
                let originalAfter = try snapshot(source)
                let cachedAfter = try snapshot(result.targetFileURL)
                try require(originalAfter == before && cachedAfter == before, "Published content or original bytes changed")
                try noStagingRemains()
            }
        }
        record("identical_cache_reuses_existing_payload") {
            try withFixture { root in
                let source = try makeApp(root)
                let first = try CacheAppOperation.cachePayload(for: source)
                let original = try snapshot(source)
                let cached = try snapshot(first.targetFileURL)
                let firstIdentity = try inode(first.targetFileURL)
                let second = try CacheAppOperation.cachePayload(for: source)
                let secondIdentity = try inode(second.targetFileURL)
                let originalAfter = try snapshot(source)
                let cachedAfter = try snapshot(second.targetFileURL)
                try require(first.signature == second.signature && first.targetFileURL == second.targetFileURL, "Identical input changed the cache key")
                try require(firstIdentity == secondIdentity, "The existing cache directory was replaced")
                try require(originalAfter == original && cachedAfter == cached, "Idempotent caching modified content")
                try noStagingRemains()
            }
        }
        record("same_size_content_change_changes_key") {
            try withFixture { root in
                let source = try makeApp(root, contents: "AAAA")
                let first = try CacheAppOperation.cachePayload(for: source)
                let originalCache = try snapshot(first.targetFileURL)
                try Data("BBBB".utf8).write(to: source.appendingPathComponent("Payload.bin"))
                let changedSource = try snapshot(source)
                let second = try CacheAppOperation.cachePayload(for: source)
                try require(first.signature != second.signature && first.targetFileURL != second.targetFileURL, "Same-size byte changes reused the previous content key")
                let oldAfter = try snapshot(first.targetFileURL)
                let newAfter = try snapshot(second.targetFileURL)
                let sourceAfter = try snapshot(source)
                try require(oldAfter == originalCache, "Publishing a new content key modified the old cache")
                try require(newAfter == changedSource && sourceAfter == changedSource, "Changed content was not preserved exactly")
                try noStagingRemains()
            }
        }
        record("root_symlink_input_rejected_preserving_files") {
            try withFixture { root in
                let source = try makeApp(root)
                let link = root.appendingPathComponent("Linked.app")
                try fm.createSymbolicLink(at: link, withDestinationURL: source)
                let before = try snapshot(root)
                try expectInvalidApp { _ = try CacheAppOperation.cachePayload(for: link) }
                let after = try snapshot(root)
                try require(after == before, "Rejected root symlink modified synthetic input or cache")
                try noStagingRemains()
            }
        }
        record("nested_symlink_input_rejected_preserving_files") {
            try withFixture { root in
                let source = try makeApp(root)
                let sibling = root.appendingPathComponent("SyntheticSibling.txt")
                try Data("not-private-fixture-data".utf8).write(to: sibling)
                try fm.createSymbolicLink(at: source.appendingPathComponent("LinkedData"), withDestinationURL: sibling)
                let before = try snapshot(root)
                try expectInvalidApp { _ = try CacheAppOperation.cachePayload(for: source) }
                let after = try snapshot(root)
                try require(after == before, "Rejected nested symlink modified synthetic input or cache")
                try noStagingRemains()
            }
        }
        record("existing_key_conflict_preserves_original_bytes") {
            try withFixture { root in
                let source = try makeApp(root)
                let expected = try fingerprint(source)
                let target = InstalledApp.payloadURL(forSignature: expected)
                try fm.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
                try fm.copyItem(at: source, to: target)
                // Unequal length keeps this case independent from the same-size
                // content-hashing negative control.
                try Data("conflicting-payload-with-a-different-length".utf8).write(to: target.appendingPathComponent("Payload.bin"))
                let badFingerprint = try fingerprint(target)
                try require(badFingerprint != expected, "Conflict setup did not produce a different key")
                let before = try snapshot(root)
                try expectInvalidApp { _ = try CacheAppOperation.cachePayload(for: source) }
                let after = try snapshot(root)
                try require(after == before, "Existing conflicting cache or original input was replaced")
                try noStagingRemains()
            }
        }
        record("obstructed_destination_parent_preserves_files") {
            try withFixture { root in
                let source = try makeApp(root)
                let obstacle = InstalledApp.appsDirectoryURL.appendingPathComponent("Payloads")
                try Data("existing-synthetic-cache-obstruction".utf8).write(to: obstacle)
                let before = try snapshot(root)
                try expectAnyError { _ = try CacheAppOperation.cachePayload(for: source) }
                let after = try snapshot(root)
                try require(after == before, "Destination creation failure modified original or existing bytes")
                try noStagingRemains()
            }
        }

        let passed = results.count == 7 && results.allSatisfy { $0.passed }
        let report = RuntimeReport(cases: results, passed: passed, failure_details: failures)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        do {
            let data = try encoder.encode(report)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            // Keep an evidence record even if report serialization unexpectedly
            // fails. Never turn a failed test into a precondition crash.
            print("{\"schema\":\"install-chain-runtime-v1\",\"group\":\"cache\",\"cases\":[],\"passed\":false,\"native_signing_device_executed\":false}")
            exit(2)
        }
        exit(passed ? 0 : 1)
    }
}

@main
private enum CacheFixtureMain {
    static func main() {
        CacheFixtureRunner().run()
    }
}
