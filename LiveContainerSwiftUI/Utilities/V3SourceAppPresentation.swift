import Foundation

// Pure presentation policies shared by the source catalog and developer-data UI.
// Neither policy performs a portal request or changes installation/signing state.
enum V3SourceVersionPolicy {
    private struct Version {
        let core: [UInt64]
        let prerelease: [String]
        init?(_ raw: String) {
            let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !value.isEmpty, value.utf8.count <= 128 else { return nil }
            let buildParts = value.split(separator: "+", omittingEmptySubsequences: false)
            guard buildParts.count <= 2 else { return nil }
            if buildParts.count == 2 {
                guard buildParts[1].split(separator: ".", omittingEmptySubsequences: false).allSatisfy({
                    !$0.isEmpty && $0.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") })
                }) else { return nil }
            }
            let withoutBuild = buildParts[0]
            let parts = withoutBuild.split(separator: "-", maxSplits: 1, omittingEmptySubsequences: false)
            let numbers = parts[0].split(separator: ".", omittingEmptySubsequences: false)
            guard (1...3).contains(numbers.count), numbers.allSatisfy({ !$0.isEmpty && $0.allSatisfy({ $0.isASCII && $0.isNumber }) }) else { return nil }
            let parsed = numbers.compactMap { UInt64($0) }
            guard parsed.count == numbers.count else { return nil }
            core = parsed + Array(repeating: 0, count: 3 - parsed.count)
            prerelease = parts.count == 2 ? parts[1].split(separator: ".", omittingEmptySubsequences: false).map(String.init) : []
            guard prerelease.allSatisfy({ !$0.isEmpty && $0.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }) }) else { return nil }
            guard !prerelease.contains(where: { $0.count > 1 && $0.first == "0" && $0.allSatisfy(\.isNumber) }) else { return nil }
        }
    }

    // Unknown/non-numeric schemes are deliberately not advertised as upgrades.
    static func isUpgrade(installed: String, available: String) -> Bool {
        guard let old = Version(installed), let new = Version(available) else { return false }
        for (lhs, rhs) in zip(new.core, old.core) where lhs != rhs { return lhs > rhs }
        if new.prerelease.isEmpty { return !old.prerelease.isEmpty }
        if old.prerelease.isEmpty { return false }
        for (lhs, rhs) in zip(new.prerelease, old.prerelease) where lhs != rhs {
            let leftNumeric = lhs.allSatisfy(\.isNumber), rightNumeric = rhs.allSatisfy(\.isNumber)
            if leftNumeric && rightNumeric {
                let left = lhs.drop(while: { $0 == "0" }), right = rhs.drop(while: { $0 == "0" })
                if left.count != right.count { return left.count > right.count }
                if left != right { return left.lexicographicallyPrecedes(right) == false }
                continue
            }
            if leftNumeric { return false }
            if rightNumeric { return true }
            return lhs > rhs
        }
        return new.prerelease.count > old.prerelease.count
    }
}

struct V3DeveloperAppID: Identifiable {
    let id: String
    let name: String
    let bundleID: String
    let expirationDate: Date?

    init?(_ row: [String: Any]) {
        guard let identifier = row["identifier"] as? String, !identifier.isEmpty else { return nil }
        id = identifier
        name = row["name"] as? String ?? ""
        bundleID = row["bundleID"] as? String ?? ""
        // A missing date is unknown, not a fabricated seven-day lifetime or a
        // promise of an unlimited paid-account App ID.
        expirationDate = (row["expirationDate"] as? Date).flatMap {
            $0.timeIntervalSinceReferenceDate.isFinite ? $0 : nil
        }
    }

    func remainingSeconds(at now: Date) -> TimeInterval? {
        expirationDate.map { max(0, $0.timeIntervalSince(now)) }
    }
}
