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
    let copy_observations: [String: [String: String]]
}

private final class CacheFixtureRunner {
    private let fm = FileManager.default
    private var results: [CaseResult] = []
    private var failures: [String: String] = [:]
    private var observations: [String: [String: String]] = [:]
    private var currentCase = ""

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
        currentCase = name
        do {
            try body()
            results.append(CaseResult(name: name, passed: true))
        } catch {
            results.append(CaseResult(name: name, passed: false))
            failures[name] = String(describing: error)
        }
    }

    private func withUmask(_ mask: mode_t, _ body: () throws -> Void) rethrows {
        let previous = umask(mask)
        defer { umask(previous) }
        try body()
    }

    // ASCII hex keys preserve the raw filename bytes, avoiding Swift String's
    // canonical-equivalence comparison concealing NFC/NFD changes in snapshots.
    private func rawNameModes(_ root: URL) throws -> [String: String] {
        var rows: [String: String] = [:]
        func visit(_ url: URL, _ relativeHex: String) throws {
            let attributes = try fm.attributesOfItem(atPath: url.path)
            let mode = (attributes[.posixPermissions] as? NSNumber)?.intValue ?? -1
            let values = try url.resourceValues(forKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey])
            try require(values.isSymbolicLink != true, "The mode/name fixture unexpectedly contains a link")
            rows[relativeHex] = String(format: "%04o", mode)
            if values.isDirectory == true {
                for child in try fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil, options: []) {
                    let nameHex = child.lastPathComponent.utf8.map { String(format: "%02x", $0) }.joined()
                    try visit(child, relativeHex + "/" + nameHex)
                }
            }
        }
        try visit(root, ".")
        return rows
    }

    private func encodedMap(_ value: [String: String]) throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return String(decoding: try encoder.encode(value), as: UTF8.self)
    }

    private func verifyRealCopyAndCache(_ source: URL, _ root: URL) throws {
        let before = try snapshot(source)
        let beforeNamesModes = try rawNameModes(source)
        let expected = try fingerprint(source)
        let probe = root.appendingPathComponent("CopyProbe.app", isDirectory: true)
        // Observe FileManager independently, but do not substitute it for the
        // real production cache's own copy/verification/publication path.
        try fm.copyItem(at: source, to: probe)
        let probeNamesModes = try rawNameModes(probe)
        let probeKey = AppBundleFingerprint.compute(for: probe)
        var detail: [String: String] = [
            "source_key": expected,
            "copy_key": probeKey ?? "nil",
            "source_raw_name_hex_to_mode": try encodedMap(beforeNamesModes),
            "copy_raw_name_hex_to_mode": try encodedMap(probeNamesModes),
        ]
        var cacheError: Error?
        var result: (signature: String, targetFileURL: URL)?
        do { result = try CacheAppOperation.cachePayload(for: source) }
        catch { cacheError = error; detail["cache_error"] = String(describing: error) }
        detail["source_key_after_cache"] = AppBundleFingerprint.compute(for: source) ?? "nil"
        if let result = result {
            detail["cache_key"] = result.signature
            detail["cache_raw_name_hex_to_mode"] = try encodedMap(rawNameModes(result.targetFileURL))
        }
        observations[currentCase] = detail
        let sourceAfter = try snapshot(source)
        let sourceNamesAfter = try rawNameModes(source)
        try require(sourceAfter == before, "Copy/cache modified original contents or permissions")
        try require(sourceNamesAfter == beforeNamesModes, "Copy/cache changed source raw filename bytes")
        try noStagingRemains()
        if let cacheError = cacheError { throw cacheError }
        try require(probeKey == expected, "Real Foundation copy changed fingerprint; see exact copy observations")
        let probeSnapshot = try snapshot(probe)
        try require(probeSnapshot == before && probeNamesModes == beforeNamesModes, "Real Foundation copy changed bytes, modes, or raw filenames")
        guard let cached = result else { throw FixtureFailure.failed("Missing successful cache result") }
        let cachedKey = try fingerprint(cached.targetFileURL)
        let cachedSnapshot = try snapshot(cached.targetFileURL)
        let cachedNamesModes = try rawNameModes(cached.targetFileURL)
        try require(cached.signature == expected && cachedKey == expected, "Published cache key differs")
        try require(cachedSnapshot == before && cachedNamesModes == beforeNamesModes, "Published cache did not retain exact source")
        let firstIdentity = try inode(cached.targetFileURL)
        let second = try CacheAppOperation.cachePayload(for: source)
        try require(second.signature == expected && second.targetFileURL == cached.targetFileURL, "Repeated source did not reuse its cache key")
        let secondIdentity = try inode(second.targetFileURL)
        let sourceAfterRepeat = try snapshot(source)
        let cacheAfterRepeat = try snapshot(second.targetFileURL)
        try require(secondIdentity == firstIdentity, "Repeated cache replaced its existing payload")
        try require(sourceAfterRepeat == before && cacheAfterRepeat == before, "Repeated cache modified payload")
        try noStagingRemains()
    }

    private func exerciseModes(_ directoryMode: Int, mask: mode_t) throws {
        try withUmask(mask) {
            try withFixture { root in
                let source = try makeApp(root)
                let nested = source.appendingPathComponent("ModeDirectory", isDirectory: true)
                try fm.createDirectory(at: nested, withIntermediateDirectories: false)
                for mode in [0o444, 0o555, 0o644, 0o755] {
                    for prefix in ["file-", ".hidden-"] {
                        let file = nested.appendingPathComponent(prefix + String(format: "%04o", mode))
                        try Data("synthetic-mode-data".utf8).write(to: file)
                        try fm.setAttributes([.posixPermissions: mode], ofItemAtPath: file.path)
                        let attributes = try fm.attributesOfItem(atPath: file.path)
                        try require((attributes[.posixPermissions] as? NSNumber)?.intValue == mode, "File mode setup differs")
                    }
                }
                // Explicit post-creation permissions prevent the setup umask
                // itself from silently weakening the intended test matrix.
                for directory in [nested, source] {
                    try fm.setAttributes([.posixPermissions: directoryMode], ofItemAtPath: directory.path)
                    let attributes = try fm.attributesOfItem(atPath: directory.path)
                    try require((attributes[.posixPermissions] as? NSNumber)?.intValue == directoryMode, "Directory mode setup differs")
                }
                try verifyRealCopyAndCache(source, root)
            }
        }
    }

    private func exerciseUnicode(_ name: String) throws {
        try withFixture { root in
            let source = try makeApp(root)
            // Each normalization form gets its own case/directory. Never try to
            // create canonically equivalent siblings on an insensitive volume.
            let nested = source.appendingPathComponent(name + "-directory", isDirectory: true)
            try fm.createDirectory(at: nested, withIntermediateDirectories: false)
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: nested.path)
            for prefix in ["", ".hidden-"] {
                let file = nested.appendingPathComponent(prefix + name + ".txt")
                try Data("synthetic-unicode-data".utf8).write(to: file)
                try fm.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
            }
            try verifyRealCopyAndCache(source, root)
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

        record("copy_modes_umask_022_directories_777") {
            try exerciseModes(0o777, mask: 0o022)
        }
        record("copy_modes_umask_022_directories_755") {
            try exerciseModes(0o755, mask: 0o022)
        }
        record("copy_modes_umask_022_directories_700") {
            try exerciseModes(0o700, mask: 0o022)
        }
        record("copy_modes_umask_077_directories_777") {
            try exerciseModes(0o777, mask: 0o077)
        }
        record("copy_modes_umask_077_directories_755") {
            try exerciseModes(0o755, mask: 0o077)
        }
        record("copy_modes_umask_077_directories_700") {
            try exerciseModes(0o700, mask: 0o077)
        }
        record("copy_modes_umask_000_directories_777") {
            try exerciseModes(0o777, mask: 0o000)
        }
        record("copy_modes_umask_000_directories_755") {
            try exerciseModes(0o755, mask: 0o000)
        }
        record("copy_modes_umask_000_directories_700") {
            try exerciseModes(0o700, mask: 0o000)
        }
        record("composed_unicode_names_copy_preserves_identity") {
            try exerciseUnicode("caf\u{00E9}")
        }
        record("decomposed_unicode_names_copy_preserves_identity") {
            try exerciseUnicode("cafe\u{0301}")
        }
        record("permission_change_publishes_new_key_preserving_previous_cache") {
            try withFixture { root in
                let source = try makeApp(root)
                let first = try CacheAppOperation.cachePayload(for: source)
                let originalCache = try snapshot(first.targetFileURL)
                try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: source.path)
                try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: source.appendingPathComponent("Payload.bin").path)
                let modified = try snapshot(source)
                let expected = try fingerprint(source)
                let second = try CacheAppOperation.cachePayload(for: source)
                try require(first.signature != second.signature && second.signature == expected, "Permission-only update reused previous key")
                let previousAfter = try snapshot(first.targetFileURL)
                let newAfter = try snapshot(second.targetFileURL)
                let sourceAfter = try snapshot(source)
                try require(previousAfter == originalCache, "Permission update changed previous cache")
                try require(newAfter == modified && sourceAfter == modified, "Permission update was not copied exactly")
                let secondIdentity = try inode(second.targetFileURL)
                let repeated = try CacheAppOperation.cachePayload(for: source)
                let repeatedIdentity = try inode(repeated.targetFileURL)
                try require(repeated.signature == second.signature && repeatedIdentity == secondIdentity, "Repeated modified source did not reuse new cache")
                try noStagingRemains()
            }
        }
        record("hidden_file_content_change_publishes_new_key") {
            try withFixture { root in
                let source = try makeApp(root)
                let first = try CacheAppOperation.cachePayload(for: source)
                let originalCache = try snapshot(first.targetFileURL)
                // Unequal length leaves the pre-existing same-size negative
                // control targeted solely at its original named case.
                try Data("synthetic-hidden-byte-with-legitimate-update".utf8).write(to: source.appendingPathComponent(".fixture-marker"))
                let modified = try snapshot(source)
                let second = try CacheAppOperation.cachePayload(for: source)
                try require(first.signature != second.signature, "Hidden-file update reused previous key")
                let previousAfter = try snapshot(first.targetFileURL)
                let newAfter = try snapshot(second.targetFileURL)
                let sourceAfter = try snapshot(source)
                try require(previousAfter == originalCache, "Hidden-file update changed previous cache")
                try require(newAfter == modified && sourceAfter == modified, "Hidden-file update was not preserved")
                try noStagingRemains()
            }
        }

        let passed = results.count == 20 && results.allSatisfy { $0.passed }
        let report = RuntimeReport(cases: results, passed: passed, failure_details: failures, copy_observations: observations)
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
