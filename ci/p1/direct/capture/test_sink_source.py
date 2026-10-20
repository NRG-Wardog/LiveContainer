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
        self.assertIn('delivered <= 6000',result)
        self.assertNotIn('delivered <= 12000',result)
        self.assertIn('3 * 1024 * 1024 * 1024 - size',result)
        for token in ('ownerValid()', 'display > 0 && display > lastDisplay',
                      'prior == currentGeometry','prior-frame-failure-latched',
                      'noncomplete-frame-status','frame-after-stopped','queue.sync'):
            self.assertIn(token,result)
    def test_bounded_persistence_and_drain_preserve_first_byte_readiness(self):
        source=(HERE/'direct_sink.swift').read_text()
        self.assertIn('guard pendingRecords < 2',source)
        self.assertIn('failed("persistence-backpressure")',source)
        self.assertLess(source.index('pendingRecords += 1'),source.index('directCopyROIs('))
        self.assertLess(source.index('captured.data = nil'),source.index('pendingRecords -= 1'))
        self.assertLess(source.index('row["callbackAfterMach"]'),source.index('persistence.async'))
        self.assertLess(source.index('persistence.async'),source.index('directROIManifest(plan, packed: data)'))
        self.assertLess(source.index('try data.write('),source.index('firstCompleteRecord = retained'))
        self.assertLess(source.index('records.append(retained)'),source.index('firstCompleteRecord = retained'))
        self.assertIn('retained["error"] = code; failed(code)',source)
        self.assertIn('queue.sync {}\n        return persistence.sync',source)
        self.assertNotIn('asyncAfter',source)
        self.assertNotIn('sample:',source[source.index('persistence.async'):])

    def test_source_drift_fails(self):
        with self.assertRaises(ValueError):build_sink.build(build_sink.SOURCE.read_text()+'\n',(HERE/'source-sha256.txt').read_text().strip())
    def test_exact_lossless_regions_and_full_context_are_distinct(self):
        source=(HERE/'roi_capture.swift').read_text()
        self.assertIn('base.advanced(by: row * plan.sourceStride + region.x * 4)',source)
        self.assertIn('region.width * 4',source)
        self.assertIn('byteCount <= 1024 * 1024',source)
        self.assertNotIn('byteCount <= 256 * 1024',source)
        self.assertIn('"displayTimeEstablished": false',source)
        self.assertIn('CGPreflightScreenCaptureAccess()',source)
        self.assertNotIn('CGRequestScreenCaptureAccess',source)
        self.assertNotIn('SCContentFilter(display:',source)
    def test_record_and_raw_cap_checks_precede_copy_and_write(self):
        source=(HERE/'direct_sink.swift').read_text()
        cap=source.index('delivered <= 6000')
        byte_cap=source.index('copiedBytes <= 3 * 1024 * 1024 * 1024 - size')
        copy=source.index('directCopyROIs(buffer, plan: plan,')
        write=source.index('try data.write(')
        self.assertLess(cap,byte_cap);self.assertLess(byte_cap,copy);self.assertLess(copy,write)
        self.assertIn('overflow += 1; failed("frame-record-limit"); return',source)



class FirstFailureSnapshotTests(unittest.TestCase):
    def test_first_failure_wins_with_timestamp_in_same_short_lock(self):
        source=(HERE/'direct_sink.swift').read_text()
        block=source[source.index('    func failed('):source.index('    func errorCode(')]
        self.assertIn('if failure == nil { failure = code; failureObservedMach = mach_absolute_time() }',block)
        self.assertEqual(source.count('failureObservedMach ='),1)
        self.assertEqual(source.count('failure = code'),1)
        self.assertLess(block.index('lock.lock()'),block.index('failureObservedMach ='))
        self.assertLess(block.index('failureObservedMach ='),block.index('lock.unlock()'))
        snapshot=block[block.index('func failureSnapshot'):]
        self.assertIn('lock.lock(); defer { lock.unlock() }',snapshot)
        self.assertIn('return ["code": directDiagnosticCode(code), "observedMach": observed]',snapshot)
        for token in ('.sync', '.async', 'write(', 'records', 'pendingRecords', 'ownerValid'):
            self.assertNotIn(token,snapshot)
        # Every original failure source still shares the same first-error latch.
        self.assertIn('failed("persistence-backpressure")',source)
        self.assertIn('failed("stream-stopped-with-error")',source)
        self.assertIn('retained["error"] = code; failed(code)',source)

if __name__=='__main__':unittest.main()
