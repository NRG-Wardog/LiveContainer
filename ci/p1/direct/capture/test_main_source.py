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

if __name__=='__main__':unittest.main()
