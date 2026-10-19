import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import artifact_budget as b
class Tests(unittest.TestCase):
    def test_all_files_included(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'abc');(p/'nested').mkdir();(p/'nested/b').write_bytes(b'de')
            self.assertEqual(b.inventory(p)['evidenceBytes'],5)
    def test_link_and_hardlink_reject(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'a').write_bytes(b'1');(p/'link').symlink_to(p/'a')
            with self.assertRaises(ValueError):b.inventory(p)
            (p/'link').unlink();os.link(p/'a',p/'b')
            with self.assertRaises(ValueError):b.inventory(p)
    def test_free_space_failure(self):
        with patch.object(b.shutil,'disk_usage',return_value=type('D',(),{'free':1})()):
            with self.assertRaises(ValueError):b.preflight(Path('/tmp'))
    def test_full_uncompressed_peak(self):
        with patch.object(b.shutil,'disk_usage',return_value=type('D',(),{'free':100*b.GIB})()):
            r=b.preflight(Path('/tmp'));self.assertLessEqual(r['plannedArchiveBytes'],4*b.GIB)
            self.assertGreater(r['plannedPeakAdditionalBytes'],3*r['plannedEvidenceBytes'])
if __name__=='__main__':unittest.main()
