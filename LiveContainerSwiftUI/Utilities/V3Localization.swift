import Foundation

enum V3AppLanguage: String, CaseIterable, Identifiable {
    case english = "en", simplifiedChinese = "zh-Hans", traditionalChinese = "zh-Hant", hebrew = "he"
    static let storageKey = "V3AppLanguage"
    var id: String { rawValue }
    var isRightToLeft: Bool { self == .hebrew }
    var nativeName: String {
        switch self {
        case .english: return "English"
        case .simplifiedChinese: return "简体中文"
        case .traditionalChinese: return "繁體中文"
        case .hebrew: return "עברית"
        }
    }
    static func resolve(_ raw: String?) -> Self {
        guard let raw else { return .english }
        let components = raw.replacingOccurrences(of: "_", with: "-").lowercased().split(separator: "-")
        guard let language = components.first else { return .english }
        switch language {
        case "he": return .hebrew
        case "zh":
            // Read the script/region subtag before extensions or private-use data.
            // An explicit script wins over any following region.
            switch components.dropFirst().first {
            case "hant": return .traditionalChinese
            case "hans": return .simplifiedChinese
            case "tw", "hk", "mo": return .traditionalChinese
            default: return .simplifiedChinese
            }
        default: return .english
        }
    }
    static var selected: Self { resolve(V3Localization.hostDefaults.string(forKey: storageKey)) }
    static func persist(_ value: Self) { V3Localization.hostDefaults.set(value.rawValue, forKey: storageKey) }
}

// V3_SETUP_TITLE_LOCALIZATION_V1: only these compile-time-owned row titles may
// fall back to English/source copy. Dynamic details and provider errors remain
// on V3Localization.prose's fail-closed path, including in the setup assistant.
enum V3SetupTitle: String, CaseIterable {
    case appRunning = "App Running"
    case developerMode = "Developer Mode"
    case pairingFile = "Pairing File"
    case appleID = "Apple ID"
    case jitless = "JIT-Less"
    case wifi = "Wi-Fi"
    case vpnTunnel = "VPN Tunnel"
    case coreDevice = "CoreDevice"
    case backgroundRefresh = "Background App Refresh"
    case schedule = "Schedule"
    case installedHostSigning = "Installed Host Signing"
    case testRefresh = "Test Refresh"

    func localized(language: V3AppLanguage = .selected,
                   bundle: Bundle = V3Localization.hostBundle) -> String {
        let value = V3Localization.string(rawValue, language: language, bundle: bundle)
        if !value.isEmpty { return value }
        // A malformed empty translation must not erase the owned row title.
        let english = V3Localization.string(rawValue, language: .english, bundle: bundle)
        return english.isEmpty ? rawValue : english
    }
}

enum V3Localization {
    // LiveContainerMain captures these objects before any guest swaps Foundation
    // defaults/bundle. Standalone fixtures have no selectors and use their own domain.
    static let hostDefaults: UserDefaults = retainedHostObject("lcUserDefaults") { UserDefaults.standard }
    static let hostBundle: Bundle = retainedHostObject("lcMainBundle") { Bundle.main }
    private static func retainedHostObject<T: AnyObject>(_ name: String, fixtureFallback: () -> T) -> T {
        #if canImport(ObjectiveC)
        let selector = NSSelectorFromString(name)
        if UserDefaults.responds(to: selector) {
            guard let retained = UserDefaults.perform(selector)?.takeUnretainedValue() as? T else {
                preconditionFailure("Captured host localization context is unavailable")
            }
            return retained
        }
        #endif
        return fixtureFallback()
    }

    // Host preference only. Never changes AppleLanguages or a guest's defaults.
    static func string(_ key: String, language: V3AppLanguage = .selected, bundle: Bundle = V3Localization.hostBundle) -> String {
        for code in [language.rawValue, "en"] {
            guard let path = bundle.path(forResource: code, ofType: "lproj"), let localized = Bundle(path: path) else { continue }
            let missing = "__V3_MISSING_LOCALIZATION__"
            let value = localized.localizedString(forKey: key, value: missing, table: nil)
            if value != missing { return value }
        }
        return key
    }
    static func date(_ value: Date, date: Date.FormatStyle.DateStyle, time: Date.FormatStyle.TimeStyle,
                     language: V3AppLanguage = .selected) -> String {
        value.formatted(Date.FormatStyle(date: date, time: time,
            locale: Locale(identifier: language.rawValue), calendar: .autoupdatingCurrent,
            timeZone: .autoupdatingCurrent))
    }
    static func legacyDate(_ value: Date, dateStyle: DateFormatter.Style, timeStyle: DateFormatter.Style,
                           language: V3AppLanguage = .selected) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: language.rawValue)
        formatter.calendar = .autoupdatingCurrent
        formatter.timeZone = .autoupdatingCurrent
        formatter.dateStyle = dateStyle
        formatter.timeStyle = timeStyle
        return formatter.string(from: value)
    }
    static func weekdayName(_ day: Int, language: V3AppLanguage = .selected) -> String {
        var calendar = Calendar.autoupdatingCurrent
        calendar.locale = Locale(identifier: language.rawValue)
        let symbols = calendar.weekdaySymbols
        guard symbols.indices.contains(day - 1) else { return "" }
        return symbols[day - 1]
    }
    static func format(_ key: String, _ arguments: String..., language: V3AppLanguage = .selected) -> String {
        String(format: string(key, language: language), locale: Locale(identifier: language.rawValue), arguments: arguments)
    }
    static func text(_ value: String, language: V3AppLanguage = .selected, bundle: Bundle = V3Localization.hostBundle) -> String {
        let marker = "\nError ID: "
        if let range = value.range(of: marker) {
            let message = String(value[..<range.lowerBound])
            let diagnostic = String(value[range.upperBound...])
            let identifier = language.isRightToLeft ? "\u{2066}\(diagnostic)\u{2069}" : diagnostic
            return text(message, language: language, bundle: bundle) + "\n" + string("Error ID:", language: language, bundle: bundle) + " " + identifier
        }
        let exact = string(value, language: language, bundle: bundle)
        if exact != value { return exact }
        return dynamicText(value, language: language, bundle: bundle, depth: 0)
    }
    /// App-owned prose only. Unknown provider text never becomes English UI copy.
    /// The caller retains the original error/diagnostic for copying and inspection.
    static func prose(_ value: String, language: V3AppLanguage = .selected, bundle: Bundle = V3Localization.hostBundle) -> String {
        translatedProse(value, language: language, bundle: bundle, depth: 0)
            ?? unavailableDetails(language: language, bundle: bundle)
    }
    private static func selectedString(_ key: String, language: V3AppLanguage, bundle: Bundle) -> String? {
        guard let path = bundle.path(forResource: language.rawValue, ofType: "lproj"),
              let selected = Bundle(path: path) else { return nil }
        let missing = "__V3_MISSING_PROSE__"
        let value = selected.localizedString(forKey: key, value: missing, table: nil)
        return value == missing || value.isEmpty ? nil : value
    }
    private static func unavailableDetails(language: V3AppLanguage, bundle: Bundle) -> String {
        let key = "Some details are unavailable in the selected language."
        if let value = selectedString(key, language: language, bundle: bundle) { return value }
        // Fail closed even if a bundle is missing; native admission still rejects it.
        switch language {
        case .english: return key
        case .hebrew: return "פרטים מסוימים אינם זמינים בשפה שנבחרה."
        case .simplifiedChinese: return "部分详细信息未提供所选语言的版本。"
        case .traditionalChinese: return "部分詳細資訊未提供所選語言的版本。"
        }
    }
    // Exact pinned TeamType, CodeSignValidationReason and certificate-state tokens.
    private static let displayAliases: [String: String] = [
        "organization": "Organization",
        "individual": "Individual",
        "free": "Free",
        "unknown": "Unknown",
        "valid": "Valid",
        "revoked": "Revoked",
        "expired": "Expired",
        "freeAccountLimitRevoked": "Certificate revoked under free-account limit",
        "differentTeam": "Different developer team",
        "differentAccount": "Different Apple ID",
        "privateKeyLost": "Private key missing",
        "externalSigner": "Different external signing certificate",
        "missingProfile": "Missing or invalid provisioning profile",
        "missingCertificate": "Signing certificate unavailable",
    ]
    private static func translatedProse(_ value: String, language: V3AppLanguage, bundle: Bundle, depth: Int) -> String? {
        if value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return value }
        guard depth < 8 else { return nil }
        let displayKey = displayAliases[value] ?? value
        if let exact = selectedString(displayKey, language: language, bundle: bundle) { return exact }
        let marker = "\nError ID: "
        if let range = value.range(of: marker, options: .backwards) {
            let suffix = String(value[range.upperBound...])
            let identifier = String(suffix.prefix { !$0.isWhitespace })
            if identifier.range(of: "^[A-Za-z0-9][A-Za-z0-9._:-]*$", options: .regularExpression) != nil {
                let message = translatedProse(String(value[..<range.lowerBound]), language: language, bundle: bundle, depth: depth + 1)
                    ?? unavailableDetails(language: language, bundle: bundle)
                let label = selectedString("Error ID:", language: language, bundle: bundle)
                    ?? ["en": "Error ID:", "he": "מזהה שגיאה:", "zh-Hans": "错误 ID：", "zh-Hant": "錯誤 ID："][language.rawValue]!
                let isolated = language.isRightToLeft ? "\u{2066}\(identifier)\u{2069}" : identifier
                let remainder = String(suffix.dropFirst(identifier.count)).trimmingCharacters(in: .whitespacesAndNewlines)
                return message + "\n" + label + " " + isolated
                    + (remainder.isEmpty ? "" : "\n" + (translatedProse(remainder, language: language, bundle: bundle, depth: depth + 1)
                        ?? unavailableDetails(language: language, bundle: bundle)))
            }
        }

        for format in displayFormats {
            guard let regex = format.regex,
                  let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
                  let localized = selectedString(format.key, language: language, bundle: bundle) else { continue }
            var arguments: [CVarArg] = []
            for index in format.localizeArguments.indices {
                guard let range = Range(match.range(at: index + 1), in: value) else { return nil }
                let raw = String(value[range])
                if format.integerArguments[index] {
                    guard let number = Int64(raw) else { return nil }
                    arguments.append(number)
                } else if format.localizeArguments[index] {
                    let displayKey = ["interval": "Every six hours", "daily": "Daily", "weekly": "Weekly"][raw] ?? raw
                    guard let translated = translatedProse(displayKey, language: language, bundle: bundle, depth: depth + 1) else { return nil }
                    arguments.append(translated)
                } else {
                    // Only reviewed opaque names, paths, addresses and IDs use this branch.
                    arguments.append(raw)
                }
            }
            return String(format: localized, locale: Locale(identifier: language.rawValue), arguments: arguments)
        }
        if value.contains("\n") {
            let parts = value.components(separatedBy: "\n")
            var localized: [String] = []
            for part in parts {
                localized.append(translatedProse(part, language: language, bundle: bundle, depth: depth + 1)
                    ?? unavailableDetails(language: language, bundle: bundle))
            }
            return localized.joined(separator: "\n")
        }
        return nil
    }

}

// Explicit reviewed display formats. Opaque arguments are inserted unchanged.
// This adapter never rewrites the underlying error, clipboard or protocol payload.
extension V3Localization {
    private struct DisplayFormat {
        let key: String
        let regex: NSRegularExpression?
        let localizeArguments: [Bool]
        let integerArguments: [Bool]
    }
    private static let displayFormats: [DisplayFormat] = [
        DisplayFormat(key: "Scheduled refresh enabled (%@), next expected %@", regex: try? NSRegularExpression(pattern: "^Scheduled refresh enabled \\((.+?)\\), next expected (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true, false], integerArguments: [false, false]),
        DisplayFormat(key: "A network connection was unavailable during %@.", regex: try? NSRegularExpression(pattern: "^A\\ network\\ connection\\ was\\ unavailable\\ during\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "A previous %@ has an unresolved result", regex: try? NSRegularExpression(pattern: "^A\\ previous\\ (.+?)\\ has\\ an\\ unresolved\\ result$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "A previous %@ may still be running", regex: try? NSRegularExpression(pattern: "^A\\ previous\\ (.+?)\\ may\\ still\\ be\\ running$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Apple's developer service reported an error %@.", regex: try? NSRegularExpression(pattern: "^Apple's\\ developer\\ service\\ reported\\ an\\ error\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Auto Refresh: %@", regex: try? NSRegularExpression(pattern: "^Auto\\ Refresh:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Cannot move directory %@ inside itself at %@", regex: try? NSRegularExpression(pattern: "^Cannot\\ move\\ directory\\ (.+?)\\ inside\\ itself\\ at\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false], integerArguments: [false, false]),
        DisplayFormat(key: "Check %@/mount_status for mounting status.", regex: try? NSRegularExpression(pattern: "^Check\\ (.+?)/mount_status\\ for\\ mounting\\ status\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Contacting JitStreamer-EB server at %@...", regex: try? NSRegularExpression(pattern: "^Contacting\\ JitStreamer\\-EB\\ server\\ at\\ (.+?)\\.\\.\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Contacting SideJITServer at %@...", regex: try? NSRegularExpression(pattern: "^Contacting\\ SideJITServer\\ at\\ (.+?)\\.\\.\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Destination already exists: %@. Delete or rename this file/folder to continue.", regex: try? NSRegularExpression(pattern: "^Destination\\ already\\ exists:\\ (.+?)\\.\\ Delete\\ or\\ rename\\ this\\ file/folder\\ to\\ continue\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Destination parent directory does not exist: %@", regex: try? NSRegularExpression(pattern: "^Destination\\ parent\\ directory\\ does\\ not\\ exist:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Destination parent is not a directory: %@", regex: try? NSRegularExpression(pattern: "^Destination\\ parent\\ is\\ not\\ a\\ directory:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Destination parent is not writable: %@", regex: try? NSRegularExpression(pattern: "^Destination\\ parent\\ is\\ not\\ writable:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Duplicate destination URL in move list: %@", regex: try? NSRegularExpression(pattern: "^Duplicate\\ destination\\ URL\\ in\\ move\\ list:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Duplicate source URL in move list: %@", regex: try? NSRegularExpression(pattern: "^Duplicate\\ source\\ URL\\ in\\ move\\ list:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Error ID: %@", regex: try? NSRegularExpression(pattern: "^Error ID: ([A-Za-z0-9][A-Za-z0-9._:-]*)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Failed to contact JitStreamer-EB server: %@", regex: try? NSRegularExpression(pattern: "^Failed\\ to\\ contact\\ JitStreamer\\-EB\\ server:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Failed to contact SideJITServer: %@", regex: try? NSRegularExpression(pattern: "^Failed\\ to\\ contact\\ SideJITServer:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Failed to move %@ to %@. %@", regex: try? NSRegularExpression(pattern: "^Failed\\ to\\ move\\ (.+?)\\ to\\ (.+?)\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false, true], integerArguments: [false, false, false]),
        DisplayFormat(key: "Failed to read file: %@", regex: try? NSRegularExpression(pattern: "^Failed\\ to\\ read\\ file:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Failed to resolve shared IPA bookmark: %@", regex: try? NSRegularExpression(pattern: "^Failed\\ to\\ resolve\\ shared\\ IPA\\ bookmark:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "HTTP Error: %@", regex: try? NSRegularExpression(pattern: "^HTTP\\ Error:\\ (\\d+)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "HTTP %@", regex: try? NSRegularExpression(pattern: "^HTTP\\ (\\d+)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Imported account for %@. Sign in with its Apple password to finish.", regex: try? NSRegularExpression(pattern: "^Imported\\ account\\ for\\ (.+?)\\.\\ Sign\\ in\\ with\\ its\\ Apple\\ password\\ to\\ finish\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Network error during the %@ operation.", regex: try? NSRegularExpression(pattern: "^Network\\ error\\ during\\ the\\ (.+?)\\ operation\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "On This Device (%@)", regex: try? NSRegularExpression(pattern: "^On\\ This\\ Device\\ \\((\\d+)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Protection: %@", regex: try? NSRegularExpression(pattern: "^Protection:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Provisioning Profiles (%@)", regex: try? NSRegularExpression(pattern: "^Provisioning\\ Profiles\\ \\((\\d+)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Reachable (HTTP %@).", regex: try? NSRegularExpression(pattern: "^Reachable\\ \\(HTTP\\ (\\d+)\\)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Recover %@", regex: try? NSRegularExpression(pattern: "^Recover\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Refresh completed for the verified app targets; %lld running app(s) were skipped.", regex: try? NSRegularExpression(pattern: "^Refresh\\ completed\\ for\\ the\\ verified\\ app\\ targets;\\ (\\d+)\\ running\\ app\\(s\\)\\ were\\ skipped\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [true]),
        DisplayFormat(key: "Refresh completed. Results for this run were verified; %lld running app(s) were skipped.", regex: try? NSRegularExpression(pattern: "^Refresh\\ completed\\.\\ Results\\ for\\ this\\ run\\ were\\ verified;\\ (\\d+)\\ running\\ app\\(s\\)\\ were\\ skipped\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [true]),
        DisplayFormat(key: "Refresh failed during %@, but no safe underlying cause was available.", regex: try? NSRegularExpression(pattern: "^Refresh\\ failed\\ during\\ (.+?),\\ but\\ no\\ safe\\ underlying\\ cause\\ was\\ available\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Refresh: %@", regex: try? NSRegularExpression(pattern: "^Refresh:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Scheduled refresh enabled (%@)", regex: try? NSRegularExpression(pattern: "^Scheduled\\ refresh\\ enabled\\ \\((.+?)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Servers (%@)", regex: try? NSRegularExpression(pattern: "^Servers\\ \\((\\d+)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "SideStore could not %@ in time while %@.", regex: try? NSRegularExpression(pattern: "^SideStore\\ could\\ not\\ (.+?)\\ in\\ time\\ while\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true, true], integerArguments: [false, false]),
        DisplayFormat(key: "SideStore could not start or complete the requested %@ action.", regex: try? NSRegularExpression(pattern: "^SideStore\\ could\\ not\\ start\\ or\\ complete\\ the\\ requested\\ (.+?)\\ action\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "SideStore could not start or complete the requested %@ action. The exact underlying cause could not be safely identified.", regex: try? NSRegularExpression(pattern: "^SideStore\\ could\\ not\\ start\\ or\\ complete\\ the\\ requested\\ (.+?)\\ action\\.\\ The\\ exact\\ underlying\\ cause\\ could\\ not\\ be\\ safely\\ identified\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "SideStore refresh intent type was not found: %@", regex: try? NSRegularExpression(pattern: "^SideStore\\ refresh\\ intent\\ type\\ was\\ not\\ found:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "SideStore type is not an AppIntent: %@", regex: try? NSRegularExpression(pattern: "^SideStore\\ type\\ is\\ not\\ an\\ AppIntent:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Source URL is invalid: %@", regex: try? NSRegularExpression(pattern: "^Source\\ URL\\ is\\ invalid:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Source and destination are the same: %@", regex: try? NSRegularExpression(pattern: "^Source\\ and\\ destination\\ are\\ the\\ same:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Source does not exist: %@", regex: try? NSRegularExpression(pattern: "^Source\\ does\\ not\\ exist:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Source is not reachable: %@. %@", regex: try? NSRegularExpression(pattern: "^Source\\ is\\ not\\ reachable:\\ (.+?)\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, true], integerArguments: [false, false]),
        DisplayFormat(key: "Source parent is not writable: : %@", regex: try? NSRegularExpression(pattern: "^Source\\ parent\\ is\\ not\\ writable:\\ :\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Sources (%@)", regex: try? NSRegularExpression(pattern: "^Sources\\ \\((\\d+)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "The %@ request was cancelled. Its result may need reconciliation.", regex: try? NSRegularExpression(pattern: "^The\\ (.+?)\\ request\\ was\\ cancelled\\.\\ Its\\ result\\ may\\ need\\ reconciliation\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The network connection was lost during %@.", regex: try? NSRegularExpression(pattern: "^The\\ network\\ connection\\ was\\ lost\\ during\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The network request timed out during %@.", regex: try? NSRegularExpression(pattern: "^The\\ network\\ request\\ timed\\ out\\ during\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The operation could not start. %@", regex: try? NSRegularExpression(pattern: "^The\\ operation\\ could\\ not\\ start\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The retry could not be confirmed as started. The previous operation may still be active. Previous attempt: %@", regex: try? NSRegularExpression(pattern: "^The\\ retry\\ could\\ not\\ be\\ confirmed\\ as\\ started\\.\\ The\\ previous\\ operation\\ may\\ still\\ be\\ active\\.\\ Previous\\ attempt:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The retry could not start because another SideStore operation is still active. Previous attempt: %@", regex: try? NSRegularExpression(pattern: "^The\\ retry\\ could\\ not\\ start\\ because\\ another\\ SideStore\\ operation\\ is\\ still\\ active\\.\\ Previous\\ attempt:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The retry could not start, so the app operation did not run. Previous attempt: %@", regex: try? NSRegularExpression(pattern: "^The\\ retry\\ could\\ not\\ start,\\ so\\ the\\ app\\ operation\\ did\\ not\\ run\\.\\ Previous\\ attempt:\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The retry could not start. %@", regex: try? NSRegularExpression(pattern: "^The\\ retry\\ could\\ not\\ start\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The sign-in attempt could not be confirmed. SideStore confirms no account is currently signed in. %@", regex: try? NSRegularExpression(pattern: "^The\\ sign\\-in\\ attempt\\ could\\ not\\ be\\ confirmed\\.\\ SideStore\\ confirms\\ no\\ account\\ is\\ currently\\ signed\\ in\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The sign-in attempt could not be confirmed. SideStore could not confirm whether sign-in completed. %@", regex: try? NSRegularExpression(pattern: "^The\\ sign\\-in\\ attempt\\ could\\ not\\ be\\ confirmed\\.\\ SideStore\\ could\\ not\\ confirm\\ whether\\ sign\\-in\\ completed\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The sign-in attempt could not be confirmed. SideStore currently reports an account as signed in. %@", regex: try? NSRegularExpression(pattern: "^The\\ sign\\-in\\ attempt\\ could\\ not\\ be\\ confirmed\\.\\ SideStore\\ currently\\ reports\\ an\\ account\\ as\\ signed\\ in\\.\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "Unknown (last known: %@)", regex: try? NSRegularExpression(pattern: "^Unknown\\ \\(last\\ known:\\ (.+?)\\)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "What happened: SideStore could not reach the configured Anisette server.\nWhat you can do: Check its address and your network, then try again. This does not show that LocalDevVPN is unavailable.\n%@", regex: try? NSRegularExpression(pattern: "^What\\ happened:\\ SideStore\\ could\\ not\\ reach\\ the\\ configured\\ Anisette\\ server\\.\\\nWhat\\ you\\ can\\ do:\\ Check\\ its\\ address\\ and\\ your\\ network,\\ then\\ try\\ again\\.\\ This\\ does\\ not\\ show\\ that\\ LocalDevVPN\\ is\\ unavailable\\.\\\n(.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "What happened: The Anisette Servers request was cancelled.\nWhat you can do: Reopen Anisette Servers to check the current state before trying again.\n%@", regex: try? NSRegularExpression(pattern: "^What\\ happened:\\ The\\ Anisette\\ Servers\\ request\\ was\\ cancelled\\.\\\nWhat\\ you\\ can\\ do:\\ Reopen\\ Anisette\\ Servers\\ to\\ check\\ the\\ current\\ state\\ before\\ trying\\ again\\.\\\n(.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "\"%@\" is not added. Add it, then the operation retries automatically.", regex: try? NSRegularExpression(pattern: "^\"(.+?)\"\\ is\\ not\\ added\\.\\ Add\\ it,\\ then\\ the\\ operation\\ retries\\ automatically\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "%lld selected", regex: try? NSRegularExpression(pattern: "^(\\d+)\\ selected$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [true]),
        DisplayFormat(key: "%lld apps", regex: try? NSRegularExpression(pattern: "^(\\d+)\\ apps$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [true]),
        DisplayFormat(key: "Install %@", regex: try? NSRegularExpression(pattern: "^Install\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Update %@", regex: try? NSRegularExpression(pattern: "^Update\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Back up %@", regex: try? NSRegularExpression(pattern: "^Back\\ up\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Restore %@", regex: try? NSRegularExpression(pattern: "^Restore\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Enable JIT for %@", regex: try? NSRegularExpression(pattern: "^Enable\\ JIT\\ for\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Remove %@ from library and erase its backups", regex: try? NSRegularExpression(pattern: "^Remove\\ (.+?)\\ from\\ library\\ and\\ erase\\ its\\ backups$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Delete %@ and erase its data and backups", regex: try? NSRegularExpression(pattern: "^Delete\\ (.+?)\\ and\\ erase\\ its\\ data\\ and\\ backups$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Refresh %@", regex: try? NSRegularExpression(pattern: "^Refresh\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "%@ completed successfully.", regex: try? NSRegularExpression(pattern: "^(.+?)\\ completed\\ successfully\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The portal holds certificates that block provisioning for a %@ team. Keep the existing certificates or revoke the selected ones.", regex: try? NSRegularExpression(pattern: "^The\\ portal\\ holds\\ certificates\\ that\\ block\\ provisioning\\ for\\ a\\ (.+?)\\ team\\.\\ Keep\\ the\\ existing\\ certificates\\ or\\ revoke\\ the\\ selected\\ ones\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The installed LiveContainer app needs to be refreshed with the active signing certificate (%@). Finish sign-in, then run Refresh All or Test Refresh in Setup Assistant. Sign-in alone does not re-sign the installed app.", regex: try? NSRegularExpression(pattern: "^The\\ installed\\ LiveContainer\\ app\\ needs\\ to\\ be\\ refreshed\\ with\\ the\\ active\\ signing\\ certificate\\ \\((.+?)\\)\\.\\ Finish\\ sign\\-in,\\ then\\ run\\ Refresh\\ All\\ or\\ Test\\ Refresh\\ in\\ Setup\\ Assistant\\.\\ Sign\\-in\\ alone\\ does\\ not\\ re\\-sign\\ the\\ installed\\ app\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [true], integerArguments: [false]),
        DisplayFormat(key: "The app reports %@ but the active signing identity expects %@. Proceed anyway?", regex: try? NSRegularExpression(pattern: "^The\\ app\\ reports\\ (.+?)\\ but\\ the\\ active\\ signing\\ identity\\ expects\\ (.+?)\\.\\ Proceed\\ anyway\\?$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false], integerArguments: [false, false]),
        DisplayFormat(key: "%@ requests %lld permission(s):\n%@", regex: try? NSRegularExpression(pattern: "^(.+?)\\ requests\\ ([0-9]+)\\ permission\\(s\\):\\\n(.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false, false], integerArguments: [false, true, false]),
        DisplayFormat(key: "%@ contains %lld extension(s). Keep them using the main app's profile or register an App ID for each, or choose which to remove.", regex: try? NSRegularExpression(pattern: "^(.+?)\\ contains\\ ([0-9]+)\\ extension\\(s\\)\\.\\ Keep\\ them\\ using\\ the\\ main\\ app's\\ profile\\ or\\ register\\ an\\ App\\ ID\\ for\\ each,\\ or\\ choose\\ which\\ to\\ remove\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false], integerArguments: [false, true]),
        DisplayFormat(key: "Remove %@", regex: try? NSRegularExpression(pattern: "^Remove\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Download %@ %@", regex: try? NSRegularExpression(pattern: "^Download\\ (.+?)\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false], integerArguments: [false, false]),
        DisplayFormat(key: "The app group %@ does not match the expected %@.", regex: try? NSRegularExpression(pattern: "^The\\ app\\ group\\ (.+?)\\ does\\ not\\ match\\ the\\ expected\\ (.+?)\\.$", options: [.dotMatchesLineSeparators]), localizeArguments: [false, false], integerArguments: [false, false]),
        DisplayFormat(key: "Use %@", regex: try? NSRegularExpression(pattern: "^Use\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Keep %@", regex: try? NSRegularExpression(pattern: "^Keep\\ (.+?)$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
        DisplayFormat(key: "Would you like to add the source \"%@\"?", regex: try? NSRegularExpression(pattern: "^Would\\ you\\ like\\ to\\ add\\ the\\ source\\ \"(.+?)\"\\?$", options: [.dotMatchesLineSeparators]), localizeArguments: [false], integerArguments: [false]),
    ]
    private static func dynamicText(_ value: String, language: V3AppLanguage, bundle: Bundle, depth: Int) -> String {
        guard depth < 3 else { return value }
        for format in displayFormats {
            guard let regex = format.regex, let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)) else { continue }
            let localized = string(format.key, language: language, bundle: bundle)
            guard localized != format.key else { continue }
            var arguments: [CVarArg] = []
            for index in format.localizeArguments.indices {
                guard let range = Range(match.range(at: index + 1), in: value) else { return value }
                let raw = String(value[range])
                if format.integerArguments[index] {
                    guard let count = Int64(raw) else { return value }
                    arguments.append(count)
                    continue
                }
                let argument: String
                if format.localizeArguments[index] {
                    let displayKey = ["interval": "Every six hours", "daily": "Daily", "weekly": "Weekly"][raw] ?? raw
                    let translated = string(displayKey, language: language, bundle: bundle)
                    argument = translated == displayKey ? dynamicText(displayKey, language: language, bundle: bundle, depth: depth + 1) : translated
                } else { argument = raw }
                arguments.append(argument)
            }
            return String(format: localized, locale: Locale(identifier: language.rawValue), arguments: arguments)
        }
        return value
    }
}


/// Deferred, app-authored presentation with a separate immutable diagnostic snapshot.
/// Locale changes never rewrite the underlying error or an already-captured copy payload.
struct V3DisplayMessage: LocalizedError, @unchecked Sendable {
    var errorDescription: String? { original }
    static func preserving(_ error: Error) -> Self {
        (error as? Self) ?? .raw(error.localizedDescription)
    }
    private enum Piece {
        case raw(String)
        case localized(String, [CVarArg])
        case diagnostic(String)
    }
    let original: String
    private let pieces: [Piece]
    static func raw(_ value: String) -> Self { Self(original: value, pieces: [.raw(value)]) }
    /// Arguments are opaque names/paths/numbers. Compose error prose as a .raw piece instead.
    static func localized(_ key: String, _ arguments: CVarArg...) -> Self {
        let format = V3Localization.string(key)
        let original = arguments.isEmpty ? format : String(format: format,
            locale: Locale(identifier: V3AppLanguage.selected.rawValue), arguments: arguments)
        return Self(original: original, pieces: [.localized(key, arguments)])
    }
    static func + (lhs: Self, rhs: Self) -> Self {
        Self(original: lhs.original + rhs.original, pieces: lhs.pieces + rhs.pieces)
    }
    func appendingDiagnostic(_ identifier: String) -> Self {
        Self(original: original + "\nError ID: " + identifier, pieces: pieces + [.diagnostic(identifier)])
    }
    func rendered(language: V3AppLanguage = .selected, bundle: Bundle = V3Localization.hostBundle) -> String {
        pieces.map { piece in
            switch piece {
            case .raw(let value): return V3Localization.prose(value, language: language, bundle: bundle)
            case .localized(let key, let arguments):
                let format = V3Localization.prose(key, language: language, bundle: bundle)
                return arguments.isEmpty ? format : String(format: format,
                    locale: Locale(identifier: language.rawValue), arguments: arguments)
            case .diagnostic(let identifier):
                return V3Localization.prose("\nError ID: " + identifier, language: language, bundle: bundle)
            }
        }.joined()
    }
}
