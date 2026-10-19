from pathlib import Path
import unittest
import build_main

HERE=Path(__file__).parent
class ResizeSourceTests(unittest.TestCase):
    def test_existing_trust_and_exact_owner_precede_single_action(self):
        source=(HERE/'window_resize.swift').read_text()
        mutation=source.index('AXUIElementPerformAction(')
        for token in ('AXIsProcessTrusted()', 'try require(trusted,', 'windows.count == 1',
                      'AXUIElementGetPid(target, &axPID)', 'axPID == pid',
                      'directAXRect(target) == window.frame', 'try requireMainWindow()',
                      'matching.count == 1', 'menus.count == 1', 'presets.count == 1',
                      'CFBooleanGetValue', 'try require(owner.valid(),'):
            self.assertLess(source.index(token),mutation)
        self.assertEqual(source.count('AXUIElementPerformAction('),1)
        for forbidden in ('AXIsProcessTrustedWithOptions','AXMakeProcessTrusted','AXUIElementCreateSystemWide',
                          'CGRequestScreenCaptureAccess','AXUIElementSetAttributeValue(', 'CGEventPost'):
            self.assertNotIn(forbidden,source)
        self.assertIn('[kAXMainWindowAttribute, kAXFocusedWindowAttribute]',source)
        self.assertIn('CFEqual(value, target)',source)
        self.assertIn('"Pixel Accurate"',source)
        self.assertIn('values.count <= 128',source)
    def test_same_window_settlement_and_source_pixels_remain_required(self):
        source=(HERE/'window_resize.swift').read_text()
        for token in ('select(window.windowID, "resized")','current.frame == prior',
                      'current.frame == axFrame','current.frame.width <= 4096','current.frame.height <= 4096',
                      '"sourceResolutionEstablished": false','AXUIElementSetMessagingTimeout(target, 2)'):
            self.assertIn(token,source)
    def test_bounded_action_precedes_immutable_filter_with_downscale_only(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        self.assertLess(source.index('deadline.arm(15, "owned-window-resize")'),source.index('directResizeOwnedWindow('))
        self.assertLess(source.index('directResizeOwnedWindow('),source.index('SCContentFilter(desktopIndependentWindow: window)'))
        self.assertIn('min(1.0, min(1000.0 / pixelWidth, 1600.0 / pixelHeight))',source)
        self.assertIn('configuration.ignoreGlobalClipSingleWindow = true',source)
        self.assertIn('configuration.preservesAspectRatio = true',source)
        self.assertIn('Double(content.width) * scale',source)
        self.assertEqual(source.count('desktopIndependentWindow:'),1)

    def test_actual_binary_readonly_preflight_precedes_build_and_boot(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        mode=source[source.index('if args.count == 2'):source.index('guard args.count == 7')]
        self.assertIn('AXIsProcessTrusted()',mode)
        self.assertNotIn('AXUIElement',mode)
        self.assertIn('"permissionRequested": false',mode)
        entry=(HERE.parent/'entry.py').read_text()
        self.assertLess(entry.index("command(helper,'--check-existing-accessibility',timeout=10)"),entry.index('capture.base.acquire(builder'))
        self.assertLess(entry.index("capture.write(output/'accessibility-prerequisite.json'"),entry.index("require(set(accessibility)"))

if __name__=='__main__':unittest.main()
