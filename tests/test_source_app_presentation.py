"""Catalog/App ID production policies. UIKit and device acceptance remain separate."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SWIFT = shutil.which("swiftc")


class SourceAppPresentationTests(unittest.TestCase):
    @unittest.skipUnless(SWIFT, "Swift compiler unavailable")
    def test_production_policies(self):
        with tempfile.TemporaryDirectory() as temp:
            main = Path(temp) / "main.swift"
            main.write_text((ROOT / "tests/fixtures/source_app_presentation.swift").read_text())
            binary = Path(temp) / "policies"
            build = subprocess.run([SWIFT, str(ROOT / "LiveContainerSwiftUI/Utilities/V3SourceAppPresentation.swift"), str(main), "-o", str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("SOURCE_APP_PRESENTATION_PASS", run.stdout)

    def test_appid_dates_survive_host_bridge(self):
        source = (ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift").read_text()
        self.assertIn('@State private var appIDs: [V3DeveloperAppID]', source)
        self.assertIn('compactMap(V3DeveloperAppID.init)', source)
        self.assertNotIn('appIDs = strings(', source)
        self.assertIn('TimelineView(.periodic(from: .now, by: 1))', source)
        self.assertIn('Expiration unavailable', source)
        self.assertIn('Expired. Reload Developer Data to check slot availability.', source)

    def test_guest_update_uses_confirmed_existing_install_route(self):
        source = (ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift").read_text()
        catalog = source.split('struct V3CatalogView: View {', 1)[1].split('struct V3', 1)[0]
        self.assertIn('bundleIdentifier() == app.bundleID', catalog)
        self.assertIn('V3SourceVersionPolicy.isUpgrade', catalog)
        self.assertIn('Update LiveContainer Guest', catalog)
        self.assertIn('link.host = "install"', catalog)
        self.assertIn('URLQueryItem(name: "url", value: app.downloadURL)', catalog)
        self.assertNotIn('sharedModel.hiddenApps', catalog)
        installer = (ROOT / 'LiveContainerSwiftUI/Views/AppList/LCAppListView.swift').read_text()
        self.assertIn('await installReplaceAlert.open()', installer)
        self.assertIn('app.appInfo.bundleIdentifier()! == newAppInfo.bundleIdentifier()', installer)


if __name__ == '__main__':
    unittest.main(verbosity=2)
