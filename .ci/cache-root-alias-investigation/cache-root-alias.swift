// Test-only exact-source cache root alias investigation. No production edits.
// Current SideStore: 62803a976507b469371158cadb941c1fe6cb5e04
// Original SideStore: ee3cc16a67f9fed766f79a0ed70938f0f8ad5a07
// Final25 source fixture SHA256: 09a5eb6ee65582db30657c9a6cde9bbb9c242bc0c271ee8b9d8a81435e519d5e
// Exact production Apps getter SHA256: fb14b82e792fda1c5ce5a60e806d453425d10c9b0148b2f606fc474bd159dee5
// SHA256 AltStore/Core/Model/InstalledApp.swift: 728fcd4e0708d632317e0f786bf63165490cf3203ec2fcbf91b609c9f205ad05
// SHA256 AltStore/Extensions/FileManager+URLs.swift: 14c835a0a4d49069baa17b2dcfd3e489879c8880385748aa00acf27c22177bf0
// SHA256 SideStore/Core/Operations/PipelineOperations/CacheAppOperation.swift: c64a34702920a946be4995be713f8c02f929fffcbfc4a196a245be2610b4417b
// SHA256 SideStore/Utils/common/AppBundleFingerprint.swift: 8340287850ef442e63c4d93665ad65e64997914d81c983ccd5aede146bcc7fa2
// SHA256 tests/cache_compatibility/OriginalAppBundleFingerprint.swift: 215f5c16cd4d2a5ecddd8a1983e22e3a9851908159b1fb272260c1eb8cfed2e6
// SHA256 tests/cache_compatibility/OriginalCacheAppOperation.swift: c1b7b1b0c3a08f1c5501461561a299b5dc1570e54c241c3c847c64c992b418da
import Foundation
import CryptoKit
import Darwin
// Inert boundary only: no CoreData, app group, credentials, device or network provider.
enum OperationError: Error, Equatable { case invalidApp(reason: String) }
func debugLog(_ message: String) {}
enum SideStore { static func debugLog(_ message: String) {} }
enum FixtureBoundary {
    static var baseDirectoryURL = URL(fileURLWithPath: "/unused-fixture-base")
}
extension FileManager {
    var altstoreSharedDirectory: URL? { FixtureBoundary.baseDirectoryURL }
    var applicationSupportDirectory: URL { FixtureBoundary.baseDirectoryURL }
}
class InstalledApp {
    class var appsDirectoryURL: URL {
        let baseDirectory = FileManager.default.altstoreSharedDirectory ?? FileManager.default.applicationSupportDirectory
        let appsDirectoryURL = baseDirectory.appendingPathComponent("Apps")
        
        do { try FileManager.default.createDirectory(at: appsDirectoryURL, withIntermediateDirectories: true, attributes: nil) }
        catch { debugLog("Creating App Directory Error: \(error)") }
        return appsDirectoryURL
    }
    class func payloadDirectoryURL(forSignature signature: String) -> URL {
        return InstalledApp.appsDirectoryURL.appendingPathComponent("Payloads").appendingPathComponent(signature)
    }
    class func payloadURL(forSignature signature: String) -> URL {
        return self.payloadDirectoryURL(forSignature: signature).appendingPathComponent("App.app")
    }
}

extension FileManager {
    func copyItem(at sourceURL: URL, to destinationURL: URL, shouldReplace: Bool) throws {
        let destinationExists = self.fileExists(atPath: destinationURL.path)
        if !shouldReplace || !destinationExists {
            let parentDirectory = destinationURL.deletingLastPathComponent()
            if !self.fileExists(atPath: parentDirectory.path) {
                try self.createDirectory(at: parentDirectory, withIntermediateDirectories: true, attributes: nil)
            }
            try self.copyItem(at: sourceURL, to: destinationURL)
            return
        }

        let temporaryDirectory = try self.url(for: .itemReplacementDirectory, in: .userDomainMask, appropriateFor: destinationURL, create: true)
        let temporaryURL = temporaryDirectory.appendingPathComponent(UUID().uuidString)
        
        let removeDirectory = {
            do {
                try self.removeItem(at: temporaryDirectory)
            } catch {
                debugLog("[FileManager+URLs] Error removing temporary directory: \(error)")
            }
        }

        do {
            try self.copyItem(at: sourceURL, to: temporaryURL)
            _ = try self.replaceItemAt(destinationURL, withItemAt: temporaryURL, backupItemName: nil, options: [])
            removeDirectory()
        } catch {
            removeDirectory()
            throw error
        }
    }
}

//
//  AppBundleFingerprint.swift
//  SideStore
//
//  Content identity for preservation-mode shared payload caching.
//

import Foundation
import CryptoKit

public enum AppBundleFingerprint {
    // Distinguish these keys from upstream's old filename/size-only hashes.
    public static let contentVersionPrefix = "content-v1-"

    public static func compute(for bundleURL: URL) -> String? {
        do {
            let values = try bundleURL.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
            guard values.isDirectory == true, values.isSymbolicLink != true else { return nil }
            let digest = try contentDigest(for: bundleURL)
            return contentVersionPrefix + digest.map { String(format: "%02x", $0) }.joined()
        } catch {
            return nil
        }
    }

    private enum FingerprintError: Error { case unsupportedEntry }

    private static func contentDigest(for url: URL) throws -> Data {
        let fm = FileManager.default
        let values = try url.resourceValues(forKeys: [.isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey])
        // Do not follow links outside the bundle or silently omit unreadable
        // entries. Preserve such bundles for explicit compatibility review.
        guard values.isSymbolicLink != true else { throw FingerprintError.unsupportedEntry }
        var hasher = SHA256()
        let attributes = try fm.attributesOfItem(atPath: url.path)
        let permissions = (attributes[.posixPermissions] as? NSNumber)?.uint32Value ?? 0
        hasher.update(data: Data("SideStore-content-v1\nmode:\(permissions)\n".utf8))
        if values.isDirectory == true {
            hasher.update(data: Data("directory\n".utf8))
            // Hidden files, signatures and profiles are part of the exact
            // payload identity; no filename/size shortcut or omission is safe.
            let children = try fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil, options: [])
                .sorted { $0.lastPathComponent < $1.lastPathComponent }
            for child in children {
                let name = Data(child.lastPathComponent.utf8)
                hasher.update(data: Data("\(name.count):".utf8))
                hasher.update(data: name)
                hasher.update(data: try contentDigest(for: child))
            }
        } else if values.isRegularFile == true {
            hasher.update(data: Data("file\n".utf8))
            let file = try FileHandle(forReadingFrom: url)
            defer { try? file.close() }
            while let chunk = try file.read(upToCount: 1_048_576), !chunk.isEmpty {
                hasher.update(data: chunk)
            }
        } else {
            throw FingerprintError.unsupportedEntry
        }
        return Data(hasher.finalize())
    }

    // ORIGINAL_CACHE_COMPATIBILITY_BEGIN
    // Compatibility experiment: upstream filename/size deduplication, not an
    // integrity proof. Use only for cachePayload; host self-refresh must keep
    // using the strict content-based compute(for:) above.
    public static func computeOriginalCacheKey(for bundleURL: URL) -> String? {
        func merkleNode(for url: URL) -> Data? {
            autoreleasepool {
                guard let contents = try? FileManager.default.contentsOfDirectory(
                    at: url,
                    includingPropertiesForKeys: [.isDirectoryKey, .fileSizeKey],
                    options: [.skipsHiddenFiles]
                ) else { return nil }

                var childEntries: [(name: String, hash: Data)] = []

                for itemURL in contents {
                    let name = itemURL.lastPathComponent

                    if name == "__MACOSX" || name == ".DS_Store" ||
                       name == "_CodeSignature" || name == "embedded.mobileprovision" {
                        continue
                    }

                    let isDir = (try? itemURL.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true
                    if isDir {
                        if let subfolderHash = merkleNode(for: itemURL) {
                            childEntries.append((name: name, hash: subfolderHash))
                        }
                    } else {
                        let size = (try? itemURL.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0
                        let leafHash = SHA256.hash(data: "\(name)|\(size)\n".data(using: .utf8)!)
                        childEntries.append((name: name, hash: Data(leafHash)))
                    }
                }

                childEntries.sort { $0.name < $1.name }

                var nodeHasher = SHA256()
                for child in childEntries {
                    nodeHasher.update(data: child.name.data(using: .utf8)!)
                    nodeHasher.update(data: child.hash)
                }
                return Data(nodeHasher.finalize())
            }
        }

        guard let rootDigest = merkleNode(for: bundleURL) else { return nil }
        return rootDigest.map { String(format: "%02x", $0) }.joined()
    }
    // ORIGINAL_CACHE_COMPATIBILITY_END
}


//
//  AppBundleFingerprint.swift
//  SideStore
//
//  Created by Magesh K on 14/9/26.
//  Copyright © 2026 SideStore. All rights reserved.
//

import Foundation
import CryptoKit

public enum OriginalAppBundleFingerprint {
    public static func compute(for bundleURL: URL) -> String? {
        func merkleNode(for url: URL) -> Data? {
            autoreleasepool {
                guard let contents = try? FileManager.default.contentsOfDirectory(
                    at: url,
                    includingPropertiesForKeys: [.isDirectoryKey, .fileSizeKey],
                    options: [.skipsHiddenFiles]
                ) else { return nil }

                var childEntries: [(name: String, hash: Data)] = []

                for itemURL in contents {
                    let name = itemURL.lastPathComponent

                    if name == "__MACOSX" || name == ".DS_Store" ||
                       name == "_CodeSignature" || name == "embedded.mobileprovision" {
                        continue
                    }

                    let isDir = (try? itemURL.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true
                    if isDir {
                        if let subfolderHash = merkleNode(for: itemURL) {
                            childEntries.append((name: name, hash: subfolderHash))
                        }
                    } else {
                        let size = (try? itemURL.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0
                        let leafHash = SHA256.hash(data: "\(name)|\(size)\n".data(using: .utf8)!)
                        childEntries.append((name: name, hash: Data(leafHash)))
                    }
                }

                childEntries.sort { $0.name < $1.name }

                var nodeHasher = SHA256()
                for child in childEntries {
                    nodeHasher.update(data: child.name.data(using: .utf8)!)
                    nodeHasher.update(data: child.hash)
                }
                return Data(nodeHasher.finalize())
            }
        }

        guard let rootDigest = merkleNode(for: bundleURL) else { return nil }
        return rootDigest.map { String(format: "%02x", $0) }.joined()
    }
}


enum CacheAppOperation {
    @discardableResult
    static func cachePayload(for bundleURL: URL) throws -> (signature: String, targetFileURL: URL) {
        guard let signature = AppBundleFingerprint.computeOriginalCacheKey(for: bundleURL) else {
            throw OperationError.invalidApp(reason: "Failed to compute app bundle fingerprint for '\(bundleURL.lastPathComponent)'")
        }

        let targetFileURL = InstalledApp.payloadURL(forSignature: signature)
        // Retain containment and no-overwrite copy boundaries while restoring
        // upstream cache key/reuse behavior. Caches are not reset or pruned.
        // Resolving a nonexistent App.app may leave an existing symlink ancestor
        // unresolved. Inspect only the three cache components below Apps, in
        // order, without following their final entry (including dangling links).
        let cachePathComponents = [
            targetFileURL.deletingLastPathComponent().deletingLastPathComponent(),
            targetFileURL.deletingLastPathComponent(),
            targetFileURL
        ]
        for componentURL in cachePathComponents {
            var fileStatus = stat()
            let status = componentURL.path.withCString { lstat($0, &fileStatus) }
            if status == 0 {
                guard (fileStatus.st_mode & mode_t(S_IFMT)) != mode_t(S_IFLNK) else {
                    throw OperationError.invalidApp(reason: "The cache destination contains a symbolic link. Existing caches were preserved.")
                }
            } else {
                let errorCode = errno
                guard errorCode == ENOENT else {
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(errorCode), userInfo: nil)
                }
            }
        }
        let rootPath = InstalledApp.appsDirectoryURL.resolvingSymlinksInPath().standardizedFileURL.path + "/"
        guard targetFileURL.resolvingSymlinksInPath().standardizedFileURL.path.hasPrefix(rootPath) else {
            throw OperationError.invalidApp(reason: "The cache destination is outside the app cache. Existing caches were preserved.")
        }
        if !FileManager.default.fileExists(atPath: targetFileURL.path) {
            let parentDir = targetFileURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: parentDir, withIntermediateDirectories: true, attributes: nil)
            try FileManager.default.copyItem(at: bundleURL, to: targetFileURL, shouldReplace: false)
        } else {
        }

        return (signature, targetFileURL)
    }
}

enum OriginalCacheAppOperation {
    @discardableResult
    static func cachePayload(for bundleURL: URL) throws -> (signature: String, targetFileURL: URL) {
        guard let signature = OriginalAppBundleFingerprint.compute(for: bundleURL) else {
            throw OperationError.invalidApp(reason: "Failed to compute app bundle fingerprint for '\(bundleURL.lastPathComponent)'")
        }

        let targetFileURL = InstalledApp.payloadURL(forSignature: signature)
        if !FileManager.default.fileExists(atPath: targetFileURL.path) {
            let parentDir = targetFileURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: parentDir, withIntermediateDirectories: true, attributes: nil)
            SideStore.debugLog("[CacheAppOperation] Caching app bundle for signature \(signature) to \(targetFileURL.path)")
            try FileManager.default.copyItem(at: bundleURL, to: targetFileURL, shouldReplace: true)
        } else {
            SideStore.debugLog("[CacheAppOperation] Payload already cached for signature \(signature), skipping copy.")
        }

        return (signature, targetFileURL)
    }
}

// One paired scenario: an explicitly owned alias ABOVE an existing Apps root,
// with no Payloads or target yet. This is not an iOS/device or race test.
enum ProbeFailure: Error { case invalidSetup(String) }
let fm = FileManager.default
func require(_ condition: Bool, _ message: String) throws {
    if !condition { throw ProbeFailure.invalidSetup(message) }
}
func canonicalPath(_ url: URL) -> String {
    url.resolvingSymlinksInPath().standardizedFileURL.path
}
func observeComponents(_ target: URL) -> [[String: Any]] {
    let components = [target.deletingLastPathComponent().deletingLastPathComponent(), target.deletingLastPathComponent(), target]
    return components.map { url in
        var info = stat()
        let rc = url.path.withCString { lstat($0, &info) }
        let code = rc == 0 ? 0 : errno
        return ["path": url.path, "return_code": Int(rc), "errno": Int(code),
                "symbolic_link": rc == 0 && (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFLNK)]
    }
}
func runProbe(_ source: URL, _ owner: URL, original: Bool) throws -> [String: Any] {
    let label = original ? "original" : "current"
    let realBase = owner.appendingPathComponent(label + "-real")
    let aliasBase = owner.appendingPathComponent(label + "-alias")
    try fm.createDirectory(at: realBase, withIntermediateDirectories: false)
    try fm.createSymbolicLink(at: aliasBase, withDestinationURL: realBase)
    FixtureBoundary.baseDirectoryURL = aliasBase
    // This is the EXACT production getter, including its createDirectory call.
    let apps = InstalledApp.appsDirectoryURL
    guard let key = OriginalAppBundleFingerprint.compute(for: source) else {
        throw ProbeFailure.invalidSetup("Synthetic original key unavailable")
    }
    let target = InstalledApp.payloadURL(forSignature: key)
    let payloads = apps.appendingPathComponent("Payloads")
    let rootLexical = apps.standardizedFileURL.path
    let rootCanonical = canonicalPath(apps)
    let targetResolvedBefore = canonicalPath(target)
    let sourceBefore = AppBundleFingerprint.compute(for: source)
    try require(sourceBefore != nil, "Synthetic source unavailable")
    try require(fm.fileExists(atPath: apps.path), "Production getter did not create Apps")
    try require(rootLexical != rootCanonical, "Trusted ancestor alias was not exercised")
    try require(!fm.fileExists(atPath: payloads.path), "Payloads already exists")
    try require(!fm.fileExists(atPath: target.path), "Target already exists")
    let components = observeComponents(target)
    try require(components.allSatisfy { ($0["return_code"] as? Int) == -1 && ($0["errno"] as? Int) == Int(ENOENT) }, "Synthetic missing descendants do not yield ENOENT")
    var result: [String: Any] = [
        "implementation": label, "root_lexical": rootLexical, "root_canonical": rootCanonical,
        "target_lexical_before": target.standardizedFileURL.path,
        "target_resolved_before": targetResolvedBefore,
        "canonical_prefix_check_before": targetResolvedBefore.hasPrefix(rootCanonical + "/"),
        "apps_exists_before": true, "payloads_exists_before": false, "target_exists_before": false,
        "cache_component_observations_before": components,
    ]
    do {
        let value: (signature: String, targetFileURL: URL)
        if original { value = try OriginalCacheAppOperation.cachePayload(for: source) }
        else { value = try CacheAppOperation.cachePayload(for: source) }
        result["cache_outcome"] = "success"
        result["returned_signature_matches_original"] = value.signature == key
        result["returned_target_canonical"] = canonicalPath(value.targetFileURL)
        result["copy_bytes_match"] = try Data(contentsOf: value.targetFileURL.appendingPathComponent("Executable")) == Data("ABCD".utf8)
        result["copy_strict_fingerprint_matches"] = AppBundleFingerprint.compute(for: value.targetFileURL) == sourceBefore
        result["returned_target_inside_real_apps"] = canonicalPath(value.targetFileURL).hasPrefix(canonicalPath(realBase.appendingPathComponent("Apps")) + "/")
    } catch let error as OperationError {
        result["cache_outcome"] = "operation_error"
        if case .invalidApp(let reason) = error {
            result["operation_error_reason"] = reason
            result["canonical_root_guard_rejected"] = reason == "The cache destination is outside the app cache. Existing caches were preserved."
        }
    } catch {
        let value = error as NSError
        result["cache_outcome"] = "other_error"
        result["error_domain"] = value.domain
        result["error_code"] = value.code
    }
    result["target_exists_after"] = fm.fileExists(atPath: target.path)
    result["payloads_exists_after"] = fm.fileExists(atPath: payloads.path)
    result["source_unchanged"] = AppBundleFingerprint.compute(for: source) == sourceBefore
    return result
}
func copySucceeded(_ value: [String: Any]) -> Bool {
    value["cache_outcome"] as? String == "success"
        && value["returned_signature_matches_original"] as? Bool == true
        && value["copy_bytes_match"] as? Bool == true
        && value["copy_strict_fingerprint_matches"] as? Bool == true
        && value["returned_target_inside_real_apps"] as? Bool == true
        && value["source_unchanged"] as? Bool == true
}
let owner = fm.temporaryDirectory.appendingPathComponent("cache-root-alias-probe-" + UUID().uuidString)
var report: [String: Any] = ["schema": "cache-root-alias-reproduction-v1", "status": "harness_failure",
                           "fake_only": true, "foundation_crypto_real": true,
                           "network_executed": false, "native_provider_executed": false,
                           "scenario_count": 1, "production_modified": false]
var resultCode: Int32 = 2
do {
    try require(CommandLine.arguments.count == 2, "Usage: probe output.json")
    try fm.createDirectory(at: owner, withIntermediateDirectories: false)
    defer { try? fm.removeItem(at: owner) } // Only this invocation's synthetic tree.
    let source = owner.appendingPathComponent("Source.app")
    try fm.createDirectory(at: source, withIntermediateDirectories: false)
    try Data("ABCD".utf8).write(to: source.appendingPathComponent("Executable"))
    try Data("synthetic-info".utf8).write(to: source.appendingPathComponent("Info.plist"))
    let original = try runProbe(source, owner, original: true)
    let current = try runProbe(source, owner, original: false)
    report["original"] = original
    report["current"] = current
    if !copySucceeded(original) {
        report["status"] = "inconclusive_original_failed"
    } else if copySucceeded(current) {
        report["status"] = "not_reproduced"
        resultCode = 0
    } else if current["canonical_root_guard_rejected"] as? Bool == true
                && current["canonical_prefix_check_before"] as? Bool == false
                && current["target_exists_after"] as? Bool == false
                && current["payloads_exists_after"] as? Bool == false
                && current["source_unchanged"] as? Bool == true {
        report["status"] = "reproduced_false_rejection"
        resultCode = 0
    } else {
        report["status"] = "inconclusive_current_failed"
    }
} catch { report["harness_failure"] = String(describing: error) }
do {
    let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    if CommandLine.arguments.count == 2 { try data.write(to: URL(fileURLWithPath: CommandLine.arguments[1])) }
} catch { resultCode = 2 }
print("CACHE_ROOT_ALIAS_REPRO_RESULT " + (report["status"] as? String ?? "harness_failure"))
exit(resultCode)
