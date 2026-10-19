"""Synthetic cross-module resource bounds, never measured native viability."""
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "geometry"))
import direct_geometry as geometry
from roi_bytes import extract


class RetentionContractTests(unittest.TestCase):
    def test_python_and_swift_agree_on_local_caps(self):
        self.assertEqual(inspect.signature(extract).parameters["max_bytes"].default, 1024*1024)
        plan = geometry.RetentionPlan(6000, 1024*1024, 4096, 16*1024**2,
                                      16*1024**2, 32*1024**2, 64*1024**2,
                                      128*1024**2, 4*1024**3, 12*1024**3)
        bounds = plan.bounds()
        self.assertLess(bounds["archiveBytes"], 4*1024**3)
        self.assertIn('byteCount <= 1024 * 1024', (ROOT/'capture/roi_capture.swift').read_text())
        self.assertIn('delivered <= 6000', (ROOT/'capture/direct_sink.swift').read_text())
        self.assertIn('copiedBytes <= 3 * 1024 * 1024 * 1024 - size',
                      (ROOT/'capture/direct_sink.swift').read_text())

    def test_board_lower_bound_and_enforced_cumulative_successor(self):
        minimum_boards = 4 * (38*4) * (22*4) * 4
        self.assertEqual(minimum_boards, 214016)
        self.assertEqual(1024*1024-minimum_boards, 834560)
        self.assertGreater(6000*1024*1024, 3*1024**3)
        self.assertEqual(min(6000*1024*1024,3*1024**3), 3*1024**3)


if __name__ == '__main__':
    unittest.main()
