"""Portable source guards only; native layout and scrolling proof are required."""
import hashlib
import os
from pathlib import Path
import unittest

ROOT = Path(os.environ["MAINTAINED_LIVE_CONTAINER_TEST_SOURCE"])
SOURCE = (ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift").read_text()
BASE_SHA256 = "3c40aab6667431d0ecb502d49a38416b9e76250ddf6e66dc1037e60d4594e0be"
START = "// A TabView's UIKit navigation children can ignore a top safe-area inset. Give\n"
TABS = "struct V3UnifiedTabs: View {\n"
OLD = "        .safeAreaInset(edge: .top, spacing: 0) {\n"
NEW = """        .modifier(V3RecoveryBannerLayout(isPresented:
            status.unresolvedOperationRecovery != nil || status.unresolvedDirectRecovery != nil ||
            status.unresolvedRefreshRecoveryRunID != nil || status.unresolvedRecoveryJournalUnreadable) {
"""
END = "        .fullScreenCover(item: $status.presentation, onDismiss: {"
LAYOUT = SOURCE[SOURCE.index(START):SOURCE.index(TABS)]


class RecoveryLayoutSourceTests(unittest.TestCase):
    def test_exact_change_is_only_the_layout_wrapper(self):
        self.assertEqual(SOURCE.count(START), 1)
        self.assertEqual(SOURCE.count(NEW), 1)
        restored = SOURCE.replace(LAYOUT, "", 1).replace(NEW, OLD, 1)
        self.assertEqual(restored.count("        })\n" + END), 1)
        restored = restored.replace("        })\n" + END, "        }\n" + END, 1)
        self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), BASE_SHA256)

    def test_natural_height_is_measured_inside_unconstrained_scroll_content(self):
        self.assertIn("banner\n                            .fixedSize(horizontal: false, vertical: true)", LAYOUT)
        measured = LAYOUT.index("value: bannerGeometry.size.height")
        capped = LAYOUT.index(".frame(height: min(naturalHeight")
        self.assertLess(LAYOUT.index("ScrollView(.vertical"), measured)
        self.assertLess(measured, capped)

    def test_cap_leaves_most_of_safe_area_viewport_for_content(self):
        self.assertIn("min(CGFloat(320), max(0, geometry.size.height) * 0.4)", LAYOUT)
        self.assertNotIn("ignoresSafeArea", LAYOUT)
        self.assertNotIn("UIScreen.main.bounds", LAYOUT)

    def test_content_is_structurally_stable_and_fills_remaining_space(self):
        self.assertEqual(LAYOUT.count("content.frame(maxWidth: .infinity, maxHeight: .infinity)"), 1)
        self.assertIn("VStack(spacing: 0)", LAYOUT)
        self.assertNotIn("else {", LAYOUT[:LAYOUT.index(".onPreferenceChange")])
        self.assertNotIn(".id(", LAYOUT)

    def test_measurement_updates_do_not_accept_invalid_heights(self):
        self.assertIn("guard measuredHeight.isFinite, measuredHeight >= 0 else { return }", LAYOUT)
        self.assertIn("if naturalHeight != measuredHeight { naturalHeight = measuredHeight }", LAYOUT)

    def test_absence_resets_the_previous_measurement(self):
        self.assertIn(".onChange(of: isPresented) { presented in\n                if !presented { naturalHeight = 0 }", LAYOUT)

    def test_recovery_scroll_hit_region_is_bounded(self):
        self.assertIn(".contentShape(Rectangle())\n                    .clipped()", LAYOUT)
        self.assertIn('.accessibilityIdentifier("v3.recovery.region")', LAYOUT)

    def test_all_original_recovery_branches_drive_presence(self):
        for key in ["unresolvedOperationRecovery", "unresolvedDirectRecovery", "unresolvedRefreshRecoveryRunID", "unresolvedRecoveryJournalUnreadable"]:
            self.assertIn("status." + key, NEW)

    def test_ios15_compatible_structure_without_newer_layout_apis(self):
        self.assertNotIn("ViewThatFits", LAYOUT)
        self.assertNotIn("AnyLayout", LAYOUT)
        self.assertNotIn("safeAreaPadding", LAYOUT)


if __name__ == "__main__":
    unittest.main()
