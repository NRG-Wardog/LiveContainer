import hashlib
import os
from pathlib import Path
import unittest
import extract

class Extraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(Path(os.environ['MAINTAINED_LIVE_CONTAINER_TEST_SOURCE'])/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
    def test_exact_hash(self):self.assertEqual(hashlib.sha256(self.source.encode()).hexdigest(),extract.SOURCE_SHA256)
    def test_all_fragments_verbatim(self):
        rows=extract.fragments(self.source);self.assertEqual(len(rows),7)
        for value in rows.values():self.assertIn(value,self.source)
    def test_generic_helper_is_complete(self):
        row=extract.fragments(self.source)['V3RecoveryBannerLayout'];self.assertTrue(row.startswith('private struct V3RecoveryBannerLayout<Banner: View>'));self.assertTrue(row.endswith('}\n'));self.assertIn('content.frame(',row)
    def test_drift_rejected(self):
        with self.assertRaises(ValueError):extract.fragments(self.source+'\n')
    def test_duplicate_marker_rejected(self):
        template=(Path(__file__).parent/'recovery.swift').read_text()
        with self.assertRaises(ValueError):extract.render(self.source,template+'__P1_RECOVERY_MODIFIER__')
    def test_generated_contains_exact_wrapper(self):
        template=(Path(__file__).parent/'recovery.swift').read_text();result=extract.render(self.source,template)
        self.assertIn(extract.fragments(self.source)['recovery-modifier'].rstrip('\n'),result)
        self.assertNotIn('__P1_RECOVERY_',result)

if __name__=='__main__':unittest.main()
