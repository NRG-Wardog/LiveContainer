from pathlib import Path
import unittest
import build_main

HERE=Path(__file__).parent
class MainSourceTests(unittest.TestCase):
    def test_generated_lifecycle_preserves_stop_cleanup_and_scope(self):
        source=build_main.build(build_main.SOURCE.read_text(),(HERE/'source-sha256.txt').read_text().strip())
        self.assertEqual(source,(HERE/'direct_main.swift').read_text())
        for token in ('CGPreflightScreenCaptureAccess()', 'startAttempted = true',
                      'recovery-stream-stop','frame-queue-drain','stream-output-detach',
                      'final-context-owner-changed','plan.geometrySHA256',
                      'let filter = SCContentFilter(desktopIndependentWindow: window)',
                      'SCStream(filter: filter,','deadline.arm(240, "direct-protocol-observation")'):
            self.assertIn(token,source)
        self.assertNotIn('CGRequestScreenCaptureAccess',source)
        self.assertNotIn('SCContentFilter(display:',source)
        self.assertEqual(source.count('desktopIndependentWindow:'),1)
    def test_drift_fails(self):
        with self.assertRaises(ValueError):build_main.build(build_main.SOURCE.read_text()+'\n',(HERE/'source-sha256.txt').read_text().strip())


    def test_initial_zero_windows_waits_only_inside_original_bound(self):
        source=(HERE/'direct_main.swift').read_text()
        start=source.index('deadline.arm(15, "window-enumeration")')
        end=source.index('deadline.arm(15, "owned-window-resize")')
        block=source[start:end]
        self.assertIn('for _ in 0..<150',block)
        self.assertIn('catch let failure as Failure where failure.code == "owned-window-not-ready"',block)
        self.assertIn('Task.sleep(nanoseconds: 100_000_000)',block)
        self.assertIn('try require(owner.valid(), "unverified-gui-owner")',block)
        self.assertEqual(block.count('deadline.arm('),1)
        self.assertLess(block.index('guard let originalWindow'),block.index('deadline.cancel()'))
        self.assertIn('window-census-initial-attempt-',source)
        self.assertIn('try require(initialAttempt < 150,',source)
        self.assertIn('try require(windows.count == 1, "ambiguous-owned-window")',source)
        self.assertIn('try require(!windows.isEmpty, "owned-window-not-ready")',source)
        self.assertNotIn('catch {',block)

if __name__=='__main__':unittest.main()
