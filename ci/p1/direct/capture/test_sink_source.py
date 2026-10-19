import unittest
from pathlib import Path
import build_sink

HERE=Path(__file__).parent
class SinkTests(unittest.TestCase):
    def test_generated_bytes_and_bounded_no_png_path(self):
        source=build_sink.SOURCE.read_text()
        result=build_sink.build(source,(HERE/'source-sha256.txt').read_text().strip())
        self.assertEqual(result,(HERE/'direct_sink.swift').read_text())
        for token in ('CGImageDestination','CGDataProvider','UTType.png','read(contentsOf:'):
            self.assertNotIn(token,result)
        self.assertIn('records.count < 6000',result)
        self.assertNotIn('records.count < 12000',result)
        self.assertIn('3 * 1024 * 1024 * 1024 - size',result)
        for token in ('ownerValid()', 'display > 0 && display > lastDisplay',
                      'prior == currentGeometry','prior-frame-failure-latched',
                      'noncomplete-frame-status','frame-after-stopped','queue.sync'):
            self.assertIn(token,result)
    def test_source_drift_fails(self):
        with self.assertRaises(ValueError):build_sink.build(build_sink.SOURCE.read_text()+'\n',(HERE/'source-sha256.txt').read_text().strip())
    def test_exact_lossless_regions_and_full_context_are_distinct(self):
        source=(HERE/'roi_capture.swift').read_text()
        self.assertIn('base.advanced(by: row * plan.sourceStride + region.x * 4)',source)
        self.assertIn('region.width * 4',source)
        self.assertIn('byteCount <= 512 * 1024',source)
        self.assertNotIn('byteCount <= 256 * 1024',source)
        self.assertIn('"displayTimeEstablished": false',source)
        self.assertIn('CGPreflightScreenCaptureAccess()',source)
        self.assertNotIn('CGRequestScreenCaptureAccess',source)
        self.assertNotIn('SCContentFilter(display:',source)
    def test_record_and_raw_cap_checks_precede_copy_and_write(self):
        source=(HERE/'direct_sink.swift').read_text()
        cap=source.index('records.count < 6000')
        byte_cap=source.index('copiedBytes <= 3 * 1024 * 1024 * 1024 - size')
        copy=source.index('directCopyROIs(buffer, plan: plan)')
        write=source.index('try data.write(')
        self.assertLess(cap,byte_cap);self.assertLess(byte_cap,copy);self.assertLess(copy,write)
        self.assertIn('overflow += 1; failed("frame-record-limit"); return',source)

if __name__=='__main__':unittest.main()
