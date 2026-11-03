import Foundation

var checks = 0
func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    precondition(condition(), message)
}
let automatic = "Remote Mac is selected automatically for normal sign-in."
let manual = "Diagnostic provider sequence is enabled."
let offeredOrder = ["onDevice", "remoteMac", "remoteServer"]
func credentials(_ id: String = "first", remote: String? = "submit-v2",
                 capability: String? = V3DiagnosticProviderPlan.capability,
                 providers: [String] = offeredOrder) -> [String: Any] {
    var value: [String: Any] = ["id": id, "kind": "credentials", "fields": [
        ["key": "appleID", "secure": "false", "value": ""],
        ["key": "password", "secure": "true", "value": ""]
    ], "diagnosticProviders": providers]
    value["remoteMacAnisette"] = remote
    value["diagnosticProviderSequence"] = capability
    return value
}
func makePrompt(_ value: [String: Any] = credentials()) -> PromptProbe {
    let prompt = PromptProbe()
    prompt.prompt = value
    prompt.appear()
    return prompt
}
func expectNormal(_ prompt: PromptProbe, _ message: String) {
    prompt.answers = []
    prompt.tapSubmit()
    expect(prompt.answers.count == 1, message + ": one answer")
    expect(prompt.answers[0] == ["appleID": "", "password": "", "choice": "", "anisetteProvider": "remoteMac"],
           message + ": exact default payload")
}

let first = makePrompt()
expect(!first.advancedDiagnosticsExpanded && !first.diagnosticSequenceEnabled, "initially collapsed, manual off")
expect(first.diagnosticProviderOrder == offeredOrder, "offered manual order is unchanged, even with onDevice first")
expect(first.providerSelectionSummary == automatic, "actual default is described")
expectNormal(first, "collapsed normal submit")
first.expandAdvanced(true)
expect(!first.diagnosticSequenceEnabled && first.providerSelectionSummary == automatic, "opening does not opt into manual diagnostics")
expectNormal(first, "expanded normal submit")
first.expandAdvanced(false)
expectNormal(first, "recollapsed normal submit")
first.setDiagnosticToggle(true)
expect(!first.diagnosticSequenceEnabled, "hidden control cannot be tapped")

first.expandAdvanced(true)
first.setDiagnosticToggle(true)
expect(first.providerSelectionSummary == manual, "explicit toggle changes visible mode")
expect(first.diagnosticProviderOrder == offeredOrder, "toggle preserves offered order")
first.moveEarlier(1)
expect(first.diagnosticProviderOrder == ["remoteMac", "onDevice", "remoteServer"], "actual earlier closure")
first.moveLater(0)
expect(first.diagnosticProviderOrder == offeredOrder, "actual later closure")
first.removeProvider("remoteServer")
expect(first.diagnosticProviderOrder == ["onDevice", "remoteMac"], "explicit subset")
first.removeProvider("remoteMac")
first.removeProvider("onDevice")
expect(first.diagnosticProviderOrder == ["onDevice"], "last provider cannot be removed")
first.addProvider(.remoteMac)
first.addProvider(.remoteMac)
expect(first.diagnosticProviderOrder == ["onDevice", "remoteMac"], "add does not duplicate provider")
first.expandAdvanced(false)
expect(first.diagnosticSequenceEnabled && first.providerSelectionSummary == manual, "collapse preserves explicit mode and visible warning")
first.answers = []
first.tapSubmit()
expect(first.answers == [["appleID": "", "password": "", "choice": "",
                          "diagnosticProviderSequence": V3DiagnosticProviderPlan.capability,
                          "diagnosticProviderOrder": "onDevice,remoteMac"]], "collapsed manual exact payload, no remoteMac override")
first.expandAdvanced(true)
first.setDiagnosticToggle(false)
expect(first.diagnosticProviderOrder == ["onDevice", "remoteMac"], "turning off preserves user order within prompt")
expect(first.providerSelectionSummary == automatic, "manual off restores accurate normal summary")
expectNormal(first, "toggle off returns to existing automatic default")

for submitting in [false, true] {
    let blocked = makePrompt()
    blocked.expandAdvanced(true)
    blocked.setDiagnosticToggle(true)
    let priorOrder = blocked.diagnosticProviderOrder
    blocked.isSubmitting = submitting
    blocked.isSubmissionBlocked = !submitting
    blocked.tapSubmit()
    blocked.setDiagnosticToggle(false)
    blocked.moveEarlier(1)
    blocked.moveLater(0)
    blocked.removeProvider("remoteMac")
    blocked.addProvider(.remoteMac)
    expect(blocked.answers.isEmpty, "disabled Submit never dispatches")
    expect(blocked.diagnosticSequenceEnabled && blocked.diagnosticProviderOrder == priorOrder, "disabled controls preserve manual choice/order")
    blocked.expandAdvanced(false)
    expect(blocked.diagnosticSequenceEnabled && blocked.providerSelectionSummary == manual, "collapse while disabled is presentation only")
}
let repeated = makePrompt()
repeated.tapSubmit()
repeated.isSubmitting = true // Parent admission owns this transition in production.
repeated.tapSubmit()
repeated.submit(choice: "") // respond also rejects programmatic repeats.
expect(repeated.answers.count == 1, "parent submission flag prevents subsequent dispatch")

for missing in [Optional<String>.none, "submit-v1", "unknown"] {
    let legacy = makePrompt(credentials(remote: missing, capability: nil))
    expect(!legacy.usesRemoteMacAnisetteForSubmit && legacy.providerSelectionSummary == nil, "legacy route makes no automatic Remote Mac claim")
    legacy.expandAdvanced(true)
    expect(!legacy.advancedDiagnosticsExpanded, "no offered capability means no advanced control")
    legacy.tapSubmit()
    expect(legacy.answers == [["appleID": "", "password": "", "choice": ""]], "legacy payload untouched")
}
for capability in [Optional<String>.none, "isolated-signin-sequence-v2"] {
    let normalOnly = makePrompt(credentials(capability: capability))
    expect(normalOnly.offeredDiagnosticProviders == nil, "exact diagnostic capability required")
    expect(normalOnly.providerSelectionSummary == automatic, "normal default does not depend on diagnostic capability")
    expectNormal(normalOnly, "submit-v2 without diagnostic offer")
}
let nonCredentials = makePrompt(["id": "two-factor", "kind": "twoFactor", "remoteMacAnisette": "submit-v2",
                                "diagnosticProviderSequence": V3DiagnosticProviderPlan.capability,
                                "diagnosticProviders": offeredOrder])
expect(nonCredentials.providerSelectionSummary == nil && nonCredentials.offeredDiagnosticProviders == nil, "no provider claim on other prompt kinds")
for invalidOrder in [[], ["remoteMac", "remoteMac"], ["unknown"]] {
    let malformed = makePrompt()
    malformed.diagnosticSequenceEnabled = true
    malformed.diagnosticProviderOrder = invalidOrder
    malformed.tapSubmit()
    expect(malformed.answers.isEmpty, "malformed explicit sequence does not fall back silently")
}
let limited = makePrompt(credentials(providers: ["remoteMac"]))
limited.diagnosticSequenceEnabled = true
limited.diagnosticProviderOrder = ["onDevice"]
limited.tapSubmit()
expect(limited.answers.isEmpty, "unoffered explicit provider rejected")

let replacement = makePrompt()
replacement.expandAdvanced(true)
replacement.setDiagnosticToggle(true)
replacement.fields = ["appleID": "synthetic@example.invalid", "password": "synthetic-placeholder"]
replacement.prompt = credentials("replacement", providers: ["remoteMac"])
replacement.promptChanged()
expect(!replacement.advancedDiagnosticsExpanded && !replacement.diagnosticSequenceEnabled, "prompt replacement resets both independent flags")
expect(replacement.diagnosticProviderOrder == ["remoteMac"] && replacement.loadedPromptID == "replacement", "replacement gets only new offered order")
expect(replacement.fields == ["appleID": "", "password": ""], "unrelated new prompt gets no credential draft")
expect(replacement.providerSelectionSummary == automatic && replacement.answers.isEmpty, "prompt replacement does not dispatch")
let draft = makePrompt(credentials("local-draft"))
draft.initialCredentialDraftID = "local-draft"
draft.fields = ["appleID": "synthetic@example.invalid", "password": "synthetic-placeholder"]
draft.expandAdvanced(true)
draft.setDiagnosticToggle(true)
draft.prompt = credentials("canonical")
draft.promptChanged()
expect(draft.fields == ["appleID": "synthetic@example.invalid", "password": "synthetic-placeholder"], "existing one-time local credential draft preservation")
expect(!draft.diagnosticSequenceEnabled && !draft.advancedDiagnosticsExpanded, "preserving credential draft never preserves diagnostics consent")
expect(draft.providerSelectionSummary == automatic && !automatic.contains("synthetic"), "summary contains no credential material")

let dismissed = makePrompt()
var cancelCount = 0
dismissed.onCancel = { cancelCount += 1 }
dismissed.expandAdvanced(true)
dismissed.setDiagnosticToggle(true)
dismissed.isSubmissionBlocked = true
dismissed.tapCancel()
expect(cancelCount == 1 && dismissed.answers.isEmpty, "cancel remains independent from disabled submission and sends no credential answer")
dismissed.cancellationDisabled = true
dismissed.tapCancel()
expect(cancelCount == 1, "cancellation's own disabled state remains honored")
dismissed.fields = ["appleID": "synthetic@example.invalid", "password": "synthetic-placeholder"]
dismissed.copiedDiagnostic = "synthetic detail"
dismissed.repairURL = URL(string: "https://example.invalid")
dismissed.selected = ["synthetic"]
dismissed.disappear() // Cancel/Back dismissal shares this actual production lifecycle.
expect(dismissed.fields.isEmpty && dismissed.selected.isEmpty && dismissed.repairURL == nil && dismissed.loadedPromptID == nil && dismissed.copiedDiagnostic == nil, "dismissal clears prompt-local draft and details")
expect(dismissed.diagnosticProviderOrder.isEmpty && !dismissed.diagnosticSequenceEnabled && !dismissed.advancedDiagnosticsExpanded, "dismissal resets diagnostics without starting anything")
expect(dismissed.answers.isEmpty && cancelCount == 1, "Back/disappear does not submit or repeat cancellation")
dismissed.isSubmissionBlocked = false
dismissed.appear()
expectNormal(dismissed, "reopened presentation returns to default")

let bundle = Bundle(path: CommandLine.arguments[1])!
let expected = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[2]))) as! [String: [String: String]]
expect(expected.count == 5, "five supported languages")
for (language, entries) in expected {
    expect(entries.count == 3, "exact three-copy scope")
    for (key, value) in entries {
        expect(V3Localization.prose(key, language: V3AppLanguage.resolve(language), bundle: bundle) == value,
               "actual native localized prompt copy: " + language + " / " + key)
    }
}
print("PROMPT_PROVIDER_UI_POLICY_PASS checks=\(checks) localized_values=15 swiftui_rendered=false device_authentication=false")
