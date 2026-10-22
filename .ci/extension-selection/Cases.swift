
@main struct ExtensionSelectionCases {
    static var passedCases: [String] = []
    static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }
    static func run(_ name: String, localIDs: [String]?, targetIDs: [String] = ["required", "widget", "share"],
                    choice: String = "selected", selected: Set<String> = ["remove:example.app.widget"],
                    preset: AppExtensionCustomization = .promptUser, expected: Set<String>,
                    expectedPrompts: Int = 1, mainProfile: Bool = false, shouldCancel: Bool = false) async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let children = try Set(targetIDs.map { id -> ALTApplication in
            let url = dir.appendingPathComponent("PlugIns/\(id).appex")
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            return ALTApplication("example.app.\(id)", url)
        })
        let app = ALTApplication("example.app", dir, children: children)
        let local = localIDs.map { ids in Set(ids.map { ALTApplication("example.app.\($0)", dir.appendingPathComponent("old/\($0)")) }) }
        let handler = TestHandler()
        handler.answer = choice == "selected"
            ? V3MultiSelectPromptAnswerPolicy.selectedMembersAnswer(kind: "extensions", selectedIDs: selected, fields: [:])
            : V3MultiSelectPromptAnswerPolicy.actionAnswer(choice, fields: ["ids":"remove:example.app.required"])
        let context = InstallAppOperationContext(app, handler)
        UserDefaults.standard.customizeAppExtensions = preset
        let operation = try RemoveAppExtensionsOperation(context: context, localAppExtensions: local)
        do {
            _ = try await operation.execute(parentProgress: nil)
            require(!shouldCancel, "\(name): accepted invalid/cancelled answer")
        } catch {
            guard shouldCancel else { throw error }
        }
        require(handler.prompts == expectedPrompts, "\(name): prompt count")
        require(Set(app.appExtensions.map { $0.bundleIdentifier }) == Set(expected.map { "example.app.\($0)" }), "\(name): retained extension set")
        require(context.useMainProfile == mainProfile, "\(name): profile route")
        if expectedPrompts > 0 {
            let members = handler.offered.compactMap { $0["id"] }.filter { V3MultiSelectPromptAnswerPolicy.isMemberOption(kind: "extensions", optionID: $0) }
            require(Set(members) == Set(targetIDs.map { "remove:example.app.\($0)" }), "\(name): every target extension offered")
            require(handler.offered.contains { $0["id"] == "keepAllMainProfile" }, "main profile option missing")
        }
        passedCases.append(name)
        print("PASS \(name)")
    }
    static func main() async throws {
        guard CommandLine.arguments.count == 2 else {
            fatalError("Usage: fixture /path/to/cases.json")
        }
        let casesURL = URL(fileURLWithPath: CommandLine.arguments[1])
        // Never leave a stale success receipt after this invocation fails.
        if FileManager.default.fileExists(atPath: casesURL.path) {
            try FileManager.default.removeItem(at: casesURL)
        }
        defer { UserDefaults.standard.removeObject(forKey: "fixture.customize") }
        let all: Set<String> = ["required", "widget", "share"]
        let kept: Set<String> = ["required", "share"]
        try await run("fresh-nil-local-empty-excess-prompts-and-selects", localIDs: nil, expected: kept)
        try await run("fresh-target-also-passed-as-local-empty-excess", localIDs: Array(all), expected: kept)
        try await run("reinstall-matching-extensions", localIDs: Array(all), expected: kept)
        try await run("update-matching-extensions", localIDs: Array(all), expected: kept)
        try await run("update-added-extension-reviews-all", localIDs: ["required"], expected: kept)
        try await run("update-no-previous-extensions", localIDs: [], expected: kept)
        try await run("remove-multiple-keeps-required", localIDs: nil, selected: ["remove:example.app.widget", "remove:example.app.share"], expected: ["required"])
        try await run("keep-all-register-individually", localIDs: nil, choice: "keepAll", expected: all)
        try await run("keep-all-main-profile", localIDs: nil, choice: "keepAllMainProfile", expected: all, mainProfile: true)
        try await run("remove-all-explicit", localIDs: nil, choice: "removeAll", expected: [])
        try await run("cancel-no-files-removed", localIDs: nil, choice: "cancel", expected: all, shouldCancel: true)
        try await run("unknown-selection-no-files-removed", localIDs: nil, selected: ["remove:other.app.extension"], expected: all, shouldCancel: true)
        try await run("empty-selection-no-files-removed", localIDs: nil, selected: [], expected: all, shouldCancel: true)
        try await run("no-extensions-no-prompt", localIDs: nil, targetIDs: [], expected: [], expectedPrompts: 0)
        try await run("preset-keep-no-prompt", localIDs: nil, preset: .keepAll, expected: all, expectedPrompts: 0)
        try await run("preset-main-profile-no-prompt", localIDs: nil, preset: .useMainProfile, expected: all, expectedPrompts: 0, mainProfile: true)
        try await run("preset-remove-no-prompt", localIDs: nil, preset: .removeAll, expected: [], expectedPrompts: 0)
        require(passedCases.count == 17 && Set(passedCases).count == 17, "case count mismatch")
        let receipt: [String: Any] = ["schema": 1, "passed_cases": passedCases,
                                    "count": passedCases.count,
                                    "native_signing_device_install": "not-run"]
        try JSONSerialization.data(withJSONObject: receipt, options: [.prettyPrinted, .sortedKeys])
            .write(to: casesURL, options: .atomic)
        print("PASS 17 source-path extension-selection cases; platform models and prompt transport are doubles. No signing or device install performed.")
    }
}
