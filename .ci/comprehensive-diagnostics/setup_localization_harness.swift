// Native, Foundation-only tests of the complete production renderer.
// Generated fixture appends this harness to the actual V3Localization.swift.
@main
struct SetupLocalizationHarness {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let expected = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("expected.json"))) as! [String: [String: String]]
        func bundle(_ name: String) -> Bundle {
            guard let result = Bundle(path: root.appendingPathComponent(name + ".bundle").path) else {
                fatalError("Missing test bundle: " + name)
            }
            return result
        }
        var cases: [String] = []
        func check(_ condition: Bool, _ name: String) {
            precondition(condition, name)
            precondition(!cases.contains(name), "Duplicate case: " + name)
            cases.append(name)
        }
        let complete = bundle("complete")
        for language in V3AppLanguage.allCases {
            let code = language.rawValue
            for key in expected[code]!.keys.sorted() {
                check(V3DisplayMessage.raw(key).rendered(language: language, bundle: complete) == expected[code]![key]!, "actual-source-copy-" + code + "-" + key)
            }
            for title in V3SetupTitle.allCases {
                check(title.localized(language: language, bundle: complete) == expected[code]![title.rawValue]!, "actual-typed-title-" + code + "-" + title.rawValue)
                for variant in ["missing_locale", "missing_title_entries", "empty_title_entries"] {
                    check(title.localized(language: language, bundle: bundle(variant)) == expected["en"]![title.rawValue]!, "owned-title-english-fallback-" + variant + "-" + code + "-" + title.rawValue)
                }
                for variant in ["empty_all_titles", "empty_bundle"] {
                    check(title.localized(language: language, bundle: bundle(variant)) == title.rawValue, "owned-title-source-fallback-" + variant + "-" + code + "-" + title.rawValue)
                }
            }
            for state in ["selected", "available", "reset", "missing", "changed", "invalid", "unknown"] {
                let key = V3PairingSelectionPresentation.detail(connected: true, observed: true, selection: state)
                check(V3DisplayMessage.raw(key).rendered(language: language, bundle: complete) == expected[code]![key]!, "actual-pairing-selection-producer-" + code + "-" + state)
            }
            for (connected, observed, name) in [(false, true, "disconnected"), (true, false, "unobserved")] {
                let key = V3PairingSelectionPresentation.detail(connected: connected, observed: observed, selection: "selected")
                check(V3DisplayMessage.raw(key).rendered(language: language, bundle: complete) == expected[code]![key]!, "actual-pairing-unconfirmed-producer-" + code + "-" + name)
            }
            for outcome in ["adoptedReady", "adoptedConnectionNotReady"] {
                let key = V3PlacedPairingPresentation.result(outcome).message
                check(V3DisplayMessage.raw(key).rendered(language: language, bundle: complete) == expected[code]![key]!, "actual-pairing-live-result-producer-" + code + "-" + outcome)
            }
            let unknown = "SECRET_PAIRING_OR_PROVIDER_CANARY password=UNKNOWN_PASSWORD_CANARY"
            let untrustedSelection = V3PairingSelectionPresentation.detail(connected: true, observed: true, selection: unknown)
            check(!untrustedSelection.contains("CANARY") && !V3PairingSelectionPresentation.isSaved(connected: true, observed: true, selection: unknown), "unknown-pairing-selection-stays-finite-" + code)
            let original = V3DisplayMessage.raw(unknown)
            let unavailable = V3Localization.prose("Some details are unavailable in the selected language.", language: language, bundle: complete)
            check(original.rendered(language: language, bundle: complete) == unavailable, "unknown-provider-fails-closed-" + code)
            check(original.original == unknown, "original-error-copy-unmodified-" + code)
            check(V3SetupTitle(rawValue: unknown) == nil, "unknown-provider-cannot-be-title-" + code)
            check(V3SetupTitle(rawValue: "Wi-Fi " + unknown) == nil, "prefix-cannot-grant-owned-title-" + code)
            for variant in ["missing_locale", "missing_title_entries", "empty_title_entries", "empty_all_titles", "empty_bundle"] {
                let rendered = original.rendered(language: language, bundle: bundle(variant))
                check(!rendered.contains("CANARY") && !rendered.isEmpty, "unknown-provider-fails-closed-" + variant + "-" + code)
            }
            let withDiagnostic = V3DisplayMessage.raw(unknown).appendingDiagnostic("SS-NET-D096")
            let renderedDiagnostic = withDiagnostic.rendered(language: language, bundle: complete)
            check(renderedDiagnostic.contains("SS-NET-D096") && !renderedDiagnostic.contains("CANARY"), "diagnostic-id-preserved-without-provider-secret-" + code)
            check(withDiagnostic.original == unknown + "\nError ID: SS-NET-D096", "diagnostic-original-unmodified-" + code)
            let fallbackBody = V3DisplayMessage.raw("Wi-Fi available").rendered(language: language, bundle: bundle("missing_locale"))
            check(language == .english ? fallbackBody == "Wi-Fi available" : fallbackBody == unavailable, "dynamic-detail-keeps-strict-locale-policy-" + code)
            let deadline = "2026-10-22 18:00"
            for (frequency, label) in [("interval", "Every six hours"), ("daily", "Daily"), ("weekly", "Weekly")] {
                let source = "Scheduled refresh enabled (" + frequency + "), next expected " + deadline
                let wanted = String(format: expected[code]!["Scheduled refresh enabled (%@), next expected %@"]!, locale: Locale(identifier: code), arguments: [expected[code]![label]!, deadline])
                check(V3DisplayMessage.raw(source).rendered(language: language, bundle: complete) == wanted, "actual-schedule-format-" + code + "-" + frequency)
            }
            if FileManager.default.fileExists(atPath: root.appendingPathComponent("baseline.bundle").path) {
                let missingKeys = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("baseline_missing_keys.json"))) as! [String]
                let baseline = bundle("baseline")
                guard let path = baseline.path(forResource: code, ofType: "lproj"), let selected = Bundle(path: path) else {
                    fatalError("Missing baseline locale: " + code)
                }
                let missing = "__SETUP_BASELINE_MISSING__"
                for key in missingKeys {
                    let exact = selected.localizedString(forKey: key, value: missing, table: nil)
                    let wanted: String
                    switch key {
                    case "Refresh is still being checked. Tunnel readiness is not verified.",
                         "Refresh verified; CoreDevice transport was not independently recorded.":
                        // Missing exact copy can still match the unchanged, reviewed
                        // "Refresh %@" format. Pin only these two known collisions;
                        // do not mistake that inherited fallback for a translated key.
                        let format = selected.localizedString(forKey: "Refresh %@", value: missing, table: nil)
                        precondition(format != missing && !format.isEmpty, "Missing baseline Refresh format: " + code)
                        wanted = String(format: format, locale: Locale(identifier: code), arguments: [String(key.dropFirst("Refresh ".count))])
                        precondition(language == .english || wanted != expected[code]![key]!, "Baseline format must not stand in for the translated copy: " + code + "-" + key)
                    default:
                        wanted = unavailable
                    }
                    check(exact == missing && V3DisplayMessage.raw(key).rendered(language: language, bundle: baseline) == wanted, "baseline-reproduces-missing-owned-copy-" + code + "-" + key)
                }
            }
        }
        let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("sources.json"))) as! [String: Any]
        precondition(cases.count == manifest["expected_native_case_count"] as! Int, "Native case count must match the source-derived manifest")
        precondition(Set(cases) == Set(manifest["expected_case_names"] as! [String]), "Native case names must exactly match the source-derived manifest")
        let report: [String: Any] = ["schema": "setup-localization-cases-v1", "status": "pass", "case_count": cases.count, "cases": cases,
            "scope": "Actual production Foundation renderer and generated catalog bundles; no SwiftUI rendering or device execution."]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: root.appendingPathComponent("cases.json"))
        print("SETUP_LOCALIZATION_RENDERER_PASS cases=\(cases.count)")
    }
}
