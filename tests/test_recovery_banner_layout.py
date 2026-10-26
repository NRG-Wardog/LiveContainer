"""Focused P1 source contracts, not execution of SwiftUI or remote UIKit."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SWIFTC = shutil.which("swiftc")


class RecoveryBannerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift").read_text()

    def modifier(self):
        return self.source.split("private struct V3RecoveryBannerLayout<Banner: View>", 1)[1].split(
            "struct V3UnifiedTabs: View", 1)[0]

    def test_banner_is_bounded_and_scrollable_without_rebuilding_navigation(self):
        modifier = self.modifier()
        self.assertIn("min(CGFloat(320), max(0, geometry.size.height) * 0.4)", modifier)
        self.assertIn("ScrollView(.vertical, showsIndicators: true)", modifier)
        self.assertIn(".frame(height: min(naturalHeight > 0 ? naturalHeight : limit, limit))", modifier)
        self.assertIn(".accessibilityIdentifier(\"v3.recovery.region\")", modifier)
        self.assertIn("guard measuredHeight.isFinite, measuredHeight >= 0 else { return }", modifier)
        self.assertIn("if !presented { naturalHeight = 0 }", modifier)
        self.assertEqual(modifier.count("content.frame("), 1)
        # Content is outside the banner conditional, never in two alternate branches.
        self.assertLess(modifier.index("if isPresented {"), modifier.index("content.frame("))
        self.assertIn("}\n                // The same content", modifier)
        self.assertNotIn("else {\n                    content", modifier)
        self.assertNotIn(".id(", modifier)

    def test_all_existing_recovery_states_keep_their_existing_actions(self):
        tabs = self.source.split("struct V3UnifiedTabs: View", 1)[1]
        presentation = tabs.split(".modifier(V3RecoveryBannerLayout(isPresented:", 1)[1].split(
            ") {", 1)[0]
        for condition in (
            "status.unresolvedOperationRecovery != nil",
            "status.unresolvedDirectRecovery != nil",
            "status.unresolvedRefreshRecoveryRunID != nil",
            "status.unresolvedRecoveryJournalUnreadable",
        ):
            self.assertIn(condition, presentation)
        banner = tabs.split(".modifier(V3RecoveryBannerLayout(isPresented:", 1)[1].split(
            ".fullScreenCover(item:", 1)[0]
        for action in (
            "status.resumeOperationRecovery()",
            "status.reconcileDurableOperationAfterDeviceCheck()",
            "status.inspectDirectRecovery()",
            "status.discardUnreadableRecoveryAfterDeviceCheck()",
        ):
            self.assertIn(action, banner)
        self.assertNotIn(".safeAreaInset(edge: .top, spacing: 0)", tabs)
        self.assertIn(".safeAreaInset(edge: .bottom)", tabs)

    def test_current_localization_and_stable_tab_identity_are_retained(self):
        shell = self.source.split("struct V3UnifiedShell: View", 1)[1].split(
            "private struct V3RecoveryBannerHeightKey", 1)[0]
        self.assertIn("@ObservedObject private var languageState = V3HostLanguageState.shared", shell)
        self.assertNotIn(".id(", shell)
        self.assertIn(".environment(\\.locale, Locale(identifier:", shell)
        self.assertIn(".environment(\\.layoutDirection,", shell)
        self.assertIn("TabView(selection: $sharedModel.selectedTab)", self.source)
        banner = self.source.split(".modifier(V3RecoveryBannerLayout(isPresented:", 1)[1].split(
            ".fullScreenCover(item:", 1)[0]
        self.assertIn("V3LocalizedText(\"A previous", banner)
        self.assertIn("V3LocalizedText(status.recoveryStorageTitle)", banner)
        self.assertIn("status.operationCoverDidDismiss()", self.source)

    @unittest.skipUnless(SWIFTC, "Swift compiler unavailable; scalar expressions not executed")
    def test_production_sizing_expressions_with_swift(self):
        modifier = self.modifier()
        limit = re.search(r"let limit = ([^\n]+)", modifier).group(1)
        height = re.search(r"\.frame\(height: (min\(naturalHeight[^\n]+)\)", modifier).group(1)
        # Compile the two actual production expressions. This is only the scalar
        # sizing calculation, not layout, hit testing, or SwiftUI state retention.
        fixture = "import Foundation\nfunc height(_ viewportHeight: CGFloat, _ naturalHeight: CGFloat) -> CGFloat {\n"
        fixture += "let limit = " + limit.replace("geometry.size.height", "viewportHeight") + "\n"
        fixture += "return " + height + "\n}\n"
        fixture += """
let cases: [(CGFloat, CGFloat, CGFloat)] = [
    (-10, 100, 0), (0, 100, 0), (100, 0, 40), (100, 20, 20),
    (100, 200, 40), (800, 0, 320), (800, 100, 100),
    (800, 1000, 320), (2000, 1000, 320)
]
for (viewport, natural, expected) in cases {
    precondition(height(viewport, natural) == expected)
}
print("RECOVERY_BANNER_SCALAR_PASS cases=9")
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "sizing.swift").write_text(fixture)
            compiled = subprocess.run([SWIFTC, str(path / "sizing.swift"), "-o", str(path / "sizing")],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(path / "sizing")], capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("RECOVERY_BANNER_SCALAR_PASS cases=9", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
