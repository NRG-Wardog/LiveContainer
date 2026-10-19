import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import artifact_budget as b
class Tests(unittest.TestCase):
    def test_linked_temp_ancestor_requires_resolved_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();real=root/'real';real.mkdir();(real/'evidence').mkdir()
            (real/'evidence/a').write_bytes(b'abc');(root/'alias').symlink_to(real,target_is_directory=True)
            unresolved=root/'alias/evidence'
            with self.assertRaisesRegex(ValueError,'ordinary evidence root'):b.inventory(unresolved)
            self.assertEqual(b.inventory(unresolved.resolve())['evidenceBytes'],3)
    def test_all_files_included(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();(p/'a').write_bytes(b'abc');(p/'nested').mkdir();(p/'nested/b').write_bytes(b'de')
            self.assertEqual(b.inventory(p)['evidenceBytes'],5)
    def test_link_and_hardlink_reject(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();(p/'a').write_bytes(b'1');(p/'link').symlink_to(p/'a')
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
            self.assertEqual(r['combinedROIPerRecord'],b.MIB)
            self.assertEqual(r['rawByteLimit'],3*b.GIB)
            self.assertEqual(r['plannedRawBytes'],min(6000*b.MIB,3*b.GIB))
            self.assertEqual(r['plannedEvidenceBytes'],3*b.GIB+6000*8192+64*b.MIB+64*b.MIB+512*b.MIB)
            self.assertEqual(r['plannedArchiveBytes'],r['plannedEvidenceBytes']+128*b.MIB)
    def test_exact_peak_free_bytes_and_one_byte_less(self):
        with patch.object(b.shutil,'disk_usage',return_value=type('D',(),{'free':100*b.GIB})()):
            required=b.preflight(Path('/tmp'))['plannedPeakAdditionalBytes']
        with patch.object(b.shutil,'disk_usage',return_value=type('D',(),{'free':required})()):
            self.assertEqual(b.preflight(Path('/tmp'))['observedFreeBytes'],required)
        with patch.object(b.shutil,'disk_usage',return_value=type('D',(),{'free':required-1})()):
            with self.assertRaisesRegex(ValueError,'insufficient conservative'):b.preflight(Path('/tmp'))

if __name__=='__main__':unittest.main()
