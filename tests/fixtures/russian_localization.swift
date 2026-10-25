import Foundation

for raw in ["ru", "ru-RU", "ru_BY", "RU", "ru-Cyrl-RU"] {
    precondition(V3AppLanguage.resolve(raw) == .russian, raw)
}
precondition(V3AppLanguage.resolve("fr") == .english)
precondition(V3AppLanguage.russian.nativeName == "Русский")
precondition(!V3AppLanguage.russian.isRightToLeft)
precondition(V3AppLanguage.hebrew.isRightToLeft)
let defaults = V3Localization.hostDefaults
let original = defaults.object(forKey: V3AppLanguage.storageKey)
let appleLanguages = defaults.object(forKey: "AppleLanguages") as? [String]
defer {
    if let original { defaults.set(original, forKey: V3AppLanguage.storageKey) }
    else { defaults.removeObject(forKey: V3AppLanguage.storageKey) }
}
for language in [V3AppLanguage.hebrew, .russian, .english, .russian] {
    V3AppLanguage.persist(language)
    precondition(V3AppLanguage.selected == language)
    precondition(defaults.string(forKey: V3AppLanguage.storageKey) == language.rawValue)
    precondition(defaults.object(forKey: "AppleLanguages") as? [String] == appleLanguages)
}
let bundle = Bundle(path: CommandLine.arguments[1])!
precondition(V3Localization.string("Language", language: .russian, bundle: bundle) == "Язык")
precondition(V3Localization.string("Refresh All", language: .russian, bundle: bundle) == "Обновить все подписи")
let message = V3DisplayMessage.raw("UNKNOWN_PROVIDER_CANARY password=SECRET_CANARY").appendingDiagnostic("SS-TEST-1")
let rendered = message.rendered(language: .russian, bundle: bundle)
precondition(rendered == "Некоторые сведения недоступны на выбранном языке.\nID ошибки: SS-TEST-1", rendered)
precondition(!rendered.contains("CANARY"))
precondition(message.original.contains("SECRET_CANARY"))
precondition(V3Localization.string("RUSSIAN_TEST_ENGLISH_ONLY", language: .russian, bundle: bundle) == "English fixture fallback")
precondition(V3Localization.string("RUSSIAN_TEST_UNKNOWN_KEY", language: .russian, bundle: bundle) == "RUSSIAN_TEST_UNKNOWN_KEY")
let emptyURL = URL(fileURLWithPath: CommandLine.arguments[1]).deletingLastPathComponent().appendingPathComponent("Empty.bundle")
try FileManager.default.createDirectory(at: emptyURL, withIntermediateDirectories: true)
let empty = Bundle(url: emptyURL)!
precondition(V3Localization.prose("UNKNOWN_PROVIDER_CANARY", language: .russian, bundle: empty) == "Некоторые сведения недоступны на выбранном языке.")
precondition(!V3Localization.weekdayName(2, language: .russian).isEmpty)
precondition(V3Localization.weekdayName(2, language: .russian) != V3Localization.weekdayName(2, language: .english))
print("RUSSIAN_RUNTIME_PASS")
