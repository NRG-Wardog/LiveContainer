import SwiftUI
import UIKit

// V3_LIVE_HOST_LANGUAGE_BEGIN
/// One synchronous host-owned presentation state. AppStorage instances alone do
/// not make imperative UIKit chrome or eager String values observable.
@MainActor
final class V3HostLanguageState: ObservableObject {
    static let shared = V3HostLanguageState(defaults: V3Localization.hostDefaults)
    @Published private(set) var selected: V3AppLanguage
    private let defaults: UserDefaults
    private var observer: NSObjectProtocol?

    init(defaults: UserDefaults) {
        self.defaults = defaults
        selected = V3AppLanguage.resolve(defaults.string(forKey: V3AppLanguage.storageKey))
        observer = NotificationCenter.default.addObserver(forName: UserDefaults.didChangeNotification,
            object: defaults, queue: .main) { [weak self] _ in
            Task { @MainActor [weak self] in self?.reloadPersistedSelection() }
        }
    }
    deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }

    func select(_ language: V3AppLanguage) {
        defaults.set(language.rawValue, forKey: V3AppLanguage.storageKey)
        publish(language)
    }
    private func reloadPersistedSelection() {
        publish(V3AppLanguage.resolve(defaults.string(forKey: V3AppLanguage.storageKey)))
    }
    private func publish(_ language: V3AppLanguage) {
        guard selected != language else { return }
        selected = language
        NotificationCenter.default.post(name: Notification.Name("V3HostLanguageDidChange"), object: defaults)
    }
}

/// Updates existing UIKit containers in this host's hosting-controller subtree.
/// Never changes appearance proxies, application windows, or guest controllers.
struct V3HostLanguageUIKitBridge: UIViewControllerRepresentable {
    let language: V3AppLanguage
    func makeUIViewController(context: Context) -> Controller { Controller(language: language) }
    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.language = language
        controller.refreshHostChrome()
        // Navigation/tab containers may finish their UIKit update after ours.
        DispatchQueue.main.async { [weak controller] in controller?.refreshHostChrome() }
    }
    final class Controller: UIViewController {
        var language: V3AppLanguage
        private let ownedChrome = NSHashTable<UIView>.weakObjects()
        init(language: V3AppLanguage) { self.language = language; super.init(nibName: nil, bundle: nil) }
        required init?(coder: NSCoder) { nil }
        override func loadView() { view = UIView(); view.isUserInteractionEnabled = false }
        override func viewDidAppear(_ animated: Bool) { super.viewDidAppear(animated); refreshHostChrome() }
        func refreshHostChrome() {
            guard let host = parent, host.viewIfLoaded != nil else { return }
            let direction: UISemanticContentAttribute = language.isRightToLeft ? .forceRightToLeft : .forceLeftToRight
            func containsGuestController(_ controller: UIViewController) -> Bool {
                if controller is AppSceneViewController || controller is DecoratedAppSceneViewController { return true }
                return controller.children.contains(where: containsGuestController)
            }
            func updateChrome(_ view: UIView) {
                // Virtual guest windows can be nested below the main hosting
                // view. Do not change their inherited root or any guest chrome.
                if view is VirtualWindowsHostView { return }
                if let owner = view.next as? UIViewController,
                   owner is AppSceneViewController || owner is DecoratedAppSceneViewController { return }
                // Do not recursively force text fields or diagnostic text whose
                // explicit LTR semantics must survive Hebrew presentation.
                if view is UINavigationBar || view is UITabBar || view is UISearchBar ||
                    view is UISegmentedControl || view is UITableView || view is UICollectionView {
                    // Host navigation chrome must track the selected language,
                    // including an RTL override left by UIKit before we attached.
                    // Other controls can have purpose-specific LTR semantics.
                    let hostNavigationChrome = view is UINavigationBar || view is UITabBar
                    if hostNavigationChrome || view.semanticContentAttribute == .unspecified || ownedChrome.contains(view) {
                        ownedChrome.add(view)
                        view.semanticContentAttribute = direction
                        view.setNeedsLayout()
                    }
                }
                for child in view.subviews { updateChrome(child) }
            }
            updateChrome(host.view)
            host.view.setNeedsLayout()
            // A SwiftUI sheet owns a separate controller view, not a subview of
            // the presenting host. Restrict traversal to this presentation chain
            // in the same window. Managed alerts retain their own input-preserving
            // localization lifecycle; never rebuild or dismiss them here.
            var presented = host.presentedViewController
            while let controller = presented {
                guard !(controller is UIAlertController), !containsGuestController(controller) else { break }
                if let view = controller.viewIfLoaded,
                   let window = host.view.window, view.window === window {
                    updateChrome(view)
                    view.setNeedsLayout()
                }
                presented = controller.presentedViewController
            }
        }
    }
}
// V3_LIVE_HOST_LANGUAGE_END

struct V3LanguageSettingsSection: View {
    @ObservedObject private var languageState = V3HostLanguageState.shared
    var body: some View {
        Section {
            Picker("Language", selection: Binding(
                get: { languageState.selected.rawValue },
                set: { languageState.select(V3AppLanguage.resolve($0)) }
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
