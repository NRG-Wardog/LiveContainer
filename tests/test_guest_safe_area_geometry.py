"""Issue 47 hardening checks; not a substitute for remote UIKit/device tests."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")


class GuestSafeAreaGeometryTests(unittest.TestCase):
    @unittest.skipUnless(CC, "C compiler unavailable")
    def test_production_geometry_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "guest_safe_area_geometry"
            compiled = subprocess.run([
                CC, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                "-I", str(ROOT), str(ROOT / "tests/fixtures/guest_safe_area_geometry.c"),
                "-o", str(binary),
            ], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("GUEST_SAFE_AREA_GEOMETRY_PASS valid_cases=384", executed.stdout)

    def test_hook_preserves_original_update_before_optional_override(self):
        source = (ROOT / "MultitaskSupport/UIKitHooks.m").read_text()
        wrapper = source.split("id wrappedBlock = ^", 1)[1].split(
            "[self hook__performUpdateWithoutActivation:wrappedBlock]", 1)[0]
        ordered = [
            "updateBlock(settings, context);",
            "UIView *container = view.superview;",
            "if (!container || !view.window) return;",
            "UIEdgeInsets orig = container.safeAreaInsets;",
            "if (!LCGuestSafeAreaInsetsAreValid(source)) return;",
            "source.top = 0;",
            "if (!LCGuestScaleSafeAreaInsets(source, scale, &scaled)) return;",
            "UIEdgeInsets insets = UIEdgeInsetsMake(scaled.top, scaled.left, scaled.bottom, scaled.right);",
            "settings.safeAreaEdgeInsets = insets;",
        ]
        offsets = [wrapper.index(step) for step in ordered]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(wrapper.count("updateBlock(settings, context);"), 1)
        # Existing orientation policy and older-OS setter remain unchanged.
        self.assertIn("LCHasRemoteSheetProviderSelector && UIInterfaceOrientationIsLandscape(settings.interfaceOrientation)", wrapper)
        self.assertIn("settings.safeAreaInsetsPortrait = LCUIEdgeInsetsRotateToOrientation(insets, settings.interfaceOrientation);", wrapper)
        self.assertIn("settings.safeAreaInsetsPortrait = insets;", wrapper)

    def test_remote_sheet_bypass_stays_before_geometry_override(self):
        source = (ROOT / "MultitaskSupport/UIKitHooks.m").read_text()
        bypass = source.index("if(LCHasRemoteSheetProviderSelector && self.ui_viewServiceComponent)")
        forward = source.index("[self hook__performUpdateWithoutActivation:updateBlock];", bypass)
        self.assertLess(forward, source.index("_UISceneHostingController *controller = self.delegate;"))
        self.assertEqual(source[forward:].split("}", 1)[0].count("return;"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
