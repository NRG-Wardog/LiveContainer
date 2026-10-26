"""Source wiring guards; actual live UIKit/SwiftUI transitions run in simulator CI."""
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]

class LiveHostLanguageWiringTests(unittest.TestCase):
    def test_selector_and_root_share_synchronous_state_without_reset(self):
        source = (ROOT / 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift').read_text()
        shell = (ROOT / 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text().split('struct V3UnifiedShell: View {', 1)[1].split('// A TabView', 1)[0]
        self.assertIn('languageState.select(V3AppLanguage.resolve($0))', source)
        self.assertIn('defaults.set(language.rawValue, forKey: V3AppLanguage.storageKey)\n        publish(language)', source)
        self.assertIn('@ObservedObject private var languageState = V3HostLanguageState.shared', shell)
        self.assertIn('V3HostLanguageUIKitBridge(language: languageState.selected)', shell)
        self.assertNotIn('.id(', shell)
        self.assertNotIn('@AppStorage', shell)

    def test_host_domain_cannot_be_replaced_with_guest_or_system_preferences(self):
        source = (ROOT / 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift').read_text()
        def check(value):
            block = value.split('// V3_LIVE_HOST_LANGUAGE_BEGIN', 1)[1].split('// V3_LIVE_HOST_LANGUAGE_END', 1)[0]
            assert 'static let shared = V3HostLanguageState(defaults: V3Localization.hostDefaults)' in block
            assert 'UserDefaults.standard' not in block and 'AppleLanguages' not in block
        check(source)
        for replacement in ['UserDefaults.standard', 'UserDefaults(suiteName: "AppleLanguages")!']:
            with self.assertRaises(AssertionError):
                check(source.replace('defaults: V3Localization.hostDefaults', 'defaults: ' + replacement))

    def test_each_native_banner_observes_explicit_changes(self):
        source = (ROOT / 'LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBannerView.swift').read_text()
        for name in ['LCAppBannerRootView', 'LCAppBannerRunControl']:
            block = source.split('final class ' + name, 1)[1].split('final class ', 1)[0]
            self.assertIn('explicitLanguageObserver = NotificationCenter.default.addObserver', block)
            self.assertIn('V3HostLanguageDidChange', block)
            self.assertIn('self.refreshLocalizedLabels()', block)

    def test_legacy_owned_views_observe_locale_without_replacing_state(self):
        views = {'Views/Settings/LCMultiLCManagementView.swift': 'LCMultiLCManagementView', 'Views/Settings/LCMultitaskSettingView.swift': 'LCMultitaskSettingView', 'Views/AppList/LCDownloadView.swift': 'DownloadAlert', 'Views/Settings/DataManagement/LCStorageManagementSections.swift': 'LCAppStorageDetailView', 'Views/Settings/DataManagement/LCStorageManagementView.swift': 'LCStorageManagementView', 'Views/AppList/AppSettings/LCSelectContainerView.swift': 'LCSelectContainerView', 'Views/AppList/Sorting/LCCustomSortView.swift': 'LCCustomSortView'}
        for path, name in views.items():
            block = (ROOT / 'LiveContainerSwiftUI' / path).read_text().split('struct ' + name, 1)[1].split('\nstruct ', 1)[0]
            self.assertIn('@Environment(\\.locale) private var selectedDisplayLocale', block, name)
            self.assertIn('var body: some View {\n        let _ = selectedDisplayLocale.identifier', block, name)

    def test_bridge_is_host_scoped_and_preserves_explicit_direction(self):
        source = (ROOT / 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift').read_text()
        bridge = source.split('struct V3HostLanguageUIKitBridge', 1)[1].split('// V3_LIVE_HOST_LANGUAGE_END', 1)[0]
        self.assertIn('if view is VirtualWindowsHostView { return }', bridge)
        self.assertIn('var presented = host.presentedViewController', bridge)
        self.assertIn('view.window === window', bridge)
        self.assertIn('guard !(controller is UIAlertController), !containsGuestController(controller) else { break }', bridge)
        self.assertIn('controller is AppSceneViewController || controller is DecoratedAppSceneViewController', bridge)
        self.assertIn('let hostNavigationChrome = view is UINavigationBar || view is UITabBar', bridge)
        self.assertIn('if hostNavigationChrome || view.semanticContentAttribute == .unspecified || ownedChrome.contains(view)', bridge)
        for forbidden in ['UIApplication.shared', '.appearance()', 'host.view.semanticContentAttribute', 'AppleLanguages', '.rootViewController =']:
            self.assertNotIn(forbidden, bridge)

    def test_existing_native_presentations_receive_explicit_and_defaults_updates(self):
        files = ['LiveContainerSwiftUI/Utilities/ViewExtensions.swift',
                 'LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBannerView.swift',
                 'MultitaskSupport/DecoratedAppSceneViewController.m']
        for path in files:
            source = (ROOT / path).read_text()
            self.assertIn('V3HostLanguageDidChange', source, path)
            self.assertTrue('UserDefaults.didChangeNotification' in source or 'NSUserDefaultsDidChangeNotification' in source)
        alerts = (ROOT / files[0]).read_text()
        self.assertIn('V3AppLanguage.selected != renderedLanguage', alerts)
        self.assertIn('let fields = previous.textFields?.map { TextFieldSnapshot($0) } ?? []', alerts)

if __name__ == '__main__': unittest.main()
