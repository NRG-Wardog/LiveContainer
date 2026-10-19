from pathlib import Path
import unittest
import build_main

HERE=Path(__file__).parent
class ResizeSourceTests(unittest.TestCase):
    def test_existing_trust_and_exact_owner_precede_mutation(self):
        source=(HERE/'window_resize.swift').read_text()
        mutation=source.index('AXUIElementSetAttributeValue(')
        for token in ('AXIsProcessTrusted()', 'try require(trusted,', 'windows.count == 1',
                      'AXUIElementGetPid(target, &axPID)', 'axPID == pid',
                      'directAXRect(target) == window.frame', 'settable.boolValue',
                      'try require(owner.valid(),'):
            self.assertLess(source.index(token),mutation)
        self.assertEqual(source.count('AXUIElementSetAttributeValue('),1)
        for forbidden in ('AXIsProcessTrustedWithOptions','AXMakeProcessTrusted','AXUIElementCreateSystemWide',
                          'CGRequestScreenCaptureAccess','kAXTitleAttribute','kAXPositionAttribute as CFString, sizeValue'):
            self.assertNotIn(forbidden,source)
    def test_same_window_settlement_and_source_pixels_remain_required(self):
        source=(HERE/'window_resize.swift').read_text()
        for token in ('select(window.windowID, "resized")','current.frame == prior',
                      'current.frame == axFrame','current.frame != window.frame',
                      'current.frame.width <= 2048','current.frame.height <= 2048',
                      '"sourceResolutionEstablished": false','AXUIElementSetMessagingTimeout(target, 2)'):
            self.assertIn(token,source)
        self.assertIn('CGSize(width: 700, height: 1550)',source)
    def test_bounded_resize_precedes_immutable_filter(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        self.assertLess(source.index('deadline.arm(15, "owned-window-resize")'),source.index('directResizeOwnedWindow('))
        self.assertLess(source.index('directResizeOwnedWindow('),source.index('SCContentFilter(desktopIndependentWindow: window)'))
        self.assertIn('configuration.width = Int(pixelWidth.rounded(.up))',source)
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
