import SwiftUI

struct V3LanguageSettingsSection: View {
    @AppStorage(V3AppLanguage.storageKey, store: V3Localization.hostDefaults) private var selection = V3AppLanguage.english.rawValue
    var body: some View {
        Section {
            Picker("Language", selection: Binding(
                get: { V3AppLanguage.resolve(selection).rawValue },
                set: { selection = V3AppLanguage.resolve($0).rawValue }
            )) {
                ForEach(V3AppLanguage.allCases) { language in
                    Text(verbatim: language.nativeName).tag(language.rawValue)
                }
            }
            .accessibilityIdentifier("settings.language")
        } header: { Text("Language") }
    }
}

struct V3LocalizedText: View {
    @Environment(\.locale) private var locale
    let value: V3DisplayMessage
    init(_ value: String) { self.value = .raw(value) }
    init(_ value: V3DisplayMessage) { self.value = value }
    var body: some View {
        Text(verbatim: value.rendered(language: .resolve(locale.identifier)))
    }
}

struct V3LocalizedLabel: View {
    @Environment(\.locale) private var locale
    let title: String
    let systemImage: String
    init(_ title: String, systemImage: String) { self.title = title; self.systemImage = systemImage }
    var body: some View {
        Label { Text(verbatim: V3Localization.prose(title, language: .resolve(locale.identifier))) }
        icon: { Image(systemName: systemImage) }
    }
}
