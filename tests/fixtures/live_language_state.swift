import Foundation

let bundle = Bundle(path: CommandLine.arguments[1])!
let defaults = V3Localization.hostDefaults
let saved = defaults.object(forKey: V3AppLanguage.storageKey)
let appleLanguages = defaults.object(forKey: "AppleLanguages") as? [String]
defer {
    if let saved { defaults.set(saved, forKey: V3AppLanguage.storageKey) }
    else { defaults.removeObject(forKey: V3AppLanguage.storageKey) }
}
V3AppLanguage.persist(.hebrew)
// Retain the same messages and semantic values throughout the process. A UI
// language change must not require fetching a new snapshot or replacing them.
let statusKey = "Checking"
let opaqueName = "השם שלי / My name / Имя"
let message = V3DisplayMessage.localized("Version %@", opaqueName)
let failure = V3DisplayMessage.raw("UNKNOWN_PROVIDER_CANARY").appendingDiagnostic("SS-LANG-1")
let originalMessage = message.original
let originalFailure = failure.original
var previous = ""
var transitions = 0
let languages: [V3AppLanguage] = [.hebrew, .english, .hebrew, .russian, .hebrew, .simplifiedChinese, .hebrew, .traditionalChinese, .english, .hebrew]
for language in languages {
    V3AppLanguage.persist(language)
    let selected = V3AppLanguage.selected
    precondition(selected == language)
    precondition(selected.isRightToLeft == (language == .hebrew))
    let expectedStatus = V3Localization.string(statusKey, language: selected, bundle: bundle)
    let status = V3Localization.prose(statusKey, language: selected, bundle: bundle)
    precondition(status == expectedStatus && !status.isEmpty)
    if !previous.isEmpty { precondition(status != previous, "retained stale presentation after switch") }
    previous = status
    let expectedMessage = String(format: V3Localization.string("Version %@", language: selected, bundle: bundle), locale: Locale(identifier: selected.rawValue), arguments: [opaqueName])
    precondition(message.rendered(language: selected, bundle: bundle) == expectedMessage)
    precondition(message.rendered(language: selected, bundle: bundle).contains(opaqueName), "user content changed")
    let renderedFailure = failure.rendered(language: selected, bundle: bundle)
    precondition(!renderedFailure.contains("UNKNOWN_PROVIDER_CANARY"))
    precondition(renderedFailure.contains("SS-LANG-1"))
    precondition(message.original == originalMessage && failure.original == originalFailure, "diagnostic snapshot changed")
    precondition(defaults.object(forKey: "AppleLanguages") as? [String] == appleLanguages, "global/guest preference changed")
    transitions += 1
}
precondition(transitions == 10)
print("LIVE_LANGUAGE_STATE_PASS: 10 same-session transitions, retained messages and opaque content")
