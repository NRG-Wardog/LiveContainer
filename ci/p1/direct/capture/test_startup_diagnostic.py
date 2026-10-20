"""Portable source guards and a deterministic telemetry interleaving model.
These do not execute Swift, native APIs or establish performance equivalence.
"""
import copy
import itertools
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).parent
SINK = (HERE / 'direct_sink.swift').read_text()
ROI = (HERE / 'roi_capture.swift').read_text()
MAIN = (HERE / 'direct_main.swift').read_text()
IO = (HERE / 'session_io.swift').read_text()
STAGES = re.findall(r'\b\w+\b', ROI.split('enum DirectStartupStage: Int, CaseIterable {', 1)[1].split('}', 1)[0].replace('case', ''))


class Model:
    """Atomic operations represent the existing admission lock, not a Swift mock."""
    def __init__(self):
        self.pending = self.admitted = self.released = 0
        self.live = [-1, -1]
        self.rows = {}
        self.frozen = None

    def arrive(self, index):
        accepted = self.pending < 2
        if index < 8:
            self.rows[index] = {'index': index, 'admitted': accepted, 'pendingAtArrival': self.pending, 'stages': ['callbackEntry']}
        if not accepted:
            if self.frozen is None:
                self.frozen = copy.deepcopy((index, self.pending, self.admitted, self.released, self.live, self.rows))
            return False
        self.pending += 1
        self.admitted += 1
        self.live[self.live.index(-1)] = index
        return True

    def mark(self, index, stage):
        if index < 8:
            self.rows[index]['stages'].append(stage)

    def release(self, index):
        self.mark(index, 'writerEnd')
        # Payload clearing is a source-guard obligation, not modeled bytes.
        self.pending -= 1
        self.released += 1
        self.live[self.live.index(index)] = -1
        self.mark(index, 'reservationReleased')
        assert self.pending == self.admitted - self.released


class StartupModelTests(unittest.TestCase):
    def test_overflow_at_every_writer_stage_freezes_and_does_not_reserve(self):
        for stage in STAGES[STAGES.index('writerBegin'):]:
            m = Model()
            self.assertTrue(m.arrive(0))
            m.mark(0, stage)
            self.assertTrue(m.arrive(1))
            self.assertFalse(m.arrive(2))
            frozen = copy.deepcopy(m.frozen)
            self.assertEqual(frozen[1:5], (2, 2, 0, [0, 1]))
            self.assertIn(stage, frozen[5][0]['stages'])
            m.release(0); m.release(1)
            m.arrive(3); m.arrive(4); self.assertFalse(m.arrive(5))
            self.assertEqual(m.frozen, frozen)

    def test_release_overflow_race_is_consistent_before_or_after(self):
        for release_first in (False, True):
            m = Model(); m.arrive(0); m.arrive(1)
            if release_first:
                m.release(0)
                self.assertTrue(m.arrive(2)); self.assertIsNone(m.frozen)
            else:
                self.assertFalse(m.arrive(2)); m.release(0)
                self.assertEqual(m.frozen[1], 2)
                self.assertEqual(m.pending, 1)

    def test_empty_payload_and_exception_paths_release_once(self):
        for failure_stage in STAGES:
            for has_payload in (False, True):
                m = Model(); m.arrive(0); m.mark(0, failure_stage)
                # The native single defer has the same release for both paths.
                m.release(0)
                self.assertEqual((m.pending, m.admitted, m.released), (0, 1, 1))
                self.assertEqual(m.live, [-1, -1])

    def test_startup_cap_live_slot_reuse_and_later_overflow(self):
        m = Model()
        for index in range(100):
            self.assertTrue(m.arrive(index)); m.mark(index, 'writerBegin'); m.release(index)
        self.assertEqual(len(m.rows), 8)
        self.assertTrue(m.arrive(100)); self.assertTrue(m.arrive(101)); self.assertFalse(m.arrive(102))
        self.assertEqual(m.frozen[4], [100, 101])
        self.assertEqual(len(m.frozen[5]), 8)
        self.assertNotIn(100, m.rows)  # Later stage history explicitly unavailable.

    def test_reservation_conservation_all_small_interleavings(self):
        for operations in itertools.product('AR', repeat=10):
            m = Model(); index = 0
            for operation in operations:
                if operation == 'A':
                    m.arrive(index); index += 1
                elif m.pending:
                    m.release(next(value for value in m.live if value != -1))
                self.assertEqual(m.pending, m.admitted - m.released)
                self.assertIn(m.pending, (0, 1, 2))
            while m.pending:
                m.release(next(value for value in m.live if value != -1))
            self.assertEqual(m.admitted, m.released)


class StartupSourceTests(unittest.TestCase):
    def test_fixed_shape_and_worst_case_serialized_bound(self):
        self.assertEqual(len(STAGES), 24)
        self.assertIn('private static let startupLimit = 8', SINK)
        self.assertIn('private var startupRecords = (0..<8).map', SINK)
        self.assertNotIn('startupRecords.append', SINK)
        maximum = 2**64 - 1
        rows = [dict(index=5999, admitted=False, pendingAtArrival=2,
                     milestonesMach=[maximum]*len(STAGES), traceMarkCount=maximum,
                     traceMarkCostMach=maximum) for _ in range(8)]
        for index, row in enumerate(rows):
            stages = list(range(3)) if index < 3 else []
            if index < 2: stages += list(range(3, 6))
            row['cpuIntervals'] = [dict(stage=stage, begin=[maximum]*4+[4],
                                       end=[maximum]*4+[4], sameThreadPair=False,
                                       cpuDeltaNanoseconds=maximum) for stage in stages]
        value = dict(schema='p1-direct-startup-persistence-v2', session='f'*32,
                     observedMach=maximum, recordLimit=8, stageNames=STAGES,
                     cpuStageNames=['bufferLock','destinationAllocation','rowCopy','regionHash','atomicWrite','packedHash'],
                     cpuSampleFields=['wallBeforeMach','wallAfterMach','threadID','cpuNanoseconds','status'],
                     cpuLimits=dict(callbackRecords=3,writerRecords=2,maximumEndpointReads=30),
                     missingMilestone=0, records=rows,
                     firstOverflow=dict(index=5999, observedMach=maximum, pending=2,
                                        admitted=6000, released=6000, inFlight=[5998,5999], records=rows),
                     admitted=6000, released=6000, pending=2, inFlight=[5998,5999], admissionEligible=False)
        self.assertLess(len(json.dumps(value, separators=(',', ':')).encode()), 32768)
        self.assertIn('bytes.count <= 32768', IO)

    def test_overflow_snapshot_inside_original_admission_lock(self):
        block = SINK[SINK.index('        lock.lock()\n        let startupIndex'):SINK.index('        // Each reserved record')]
        self.assertLess(block.index('startupOverflow = DirectStartupOverflow'), block.index('lock.unlock()'))
        self.assertIn('guard pendingRecords < 2', block)
        self.assertIn('lock.unlock(); overflow += 1; failed("persistence-backpressure"); return', block)
        self.assertIn('pendingRecords += 1', block)
        self.assertEqual(SINK.count('pendingRecords += 1'), 1)
        self.assertEqual(SINK.count('pendingRecords -= 1'), 1)
        self.assertLess(SINK.index('captured.data = nil'), SINK.index('pendingRecords -= 1'))

    def test_snapshot_does_not_drain_or_read_queue_owned_counters(self):
        block = SINK[SINK.index('    func startupSnapshot()'):SINK.index('    private var lastDisplay')]
        for token in ('.sync', '.async', 'ownerValid', 'write(', 'delivered', 'copiedBytes', 'completeFrames'):
            self.assertNotIn(token, block)
        self.assertLess(block.index('lock.unlock()'), block.index('return ['))
        self.assertLess(block.index('lock.unlock()'), block.index('.json()'))

    def test_stage_marking_is_bounded_no_io_and_cost_is_not_subtracted(self):
        block = SINK[SINK.index('    private func startupMark'):SINK.index('    func startupSnapshot')]
        self.assertLess(block.index('guard index < Self.startupLimit'), block.index('mach_absolute_time()'))
        for token in ('write(', 'digest(', '.sync', '.async', 'JSONSerialization', 'ownerValid'):
            self.assertNotIn(token, block)
        self.assertIn('traceMarkCostMach += mach_absolute_time() - markStart', block)
        self.assertEqual(SINK.count('row["callbackAfterMach"] = mach_absolute_time()'), 1)
        self.assertLess(SINK.index('row["callbackAfterMach"] ='), SINK.index('.enqueueBefore)'))
        self.assertLess(SINK.index('.enqueueBefore)'), SINK.index('persistence.async'))
        self.assertGreater(SINK.index('.enqueueAfter)'), SINK.index('records.append(retained)'))
        self.assertIn('display > 0 && display > lastDisplay', SINK)
        self.assertIn('configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)', MAIN)
        self.assertIn('configuration.queueDepth = 3', MAIN)

    def test_primary_first_sidecar_exclusive_no_added_sync_no_sample_fields(self):
        catch = MAIN[MAIN.index('let originalCode'):MAIN.index('if startAttempted && !stopConfirmed')]
        self.assertLess(catch.index('directWritePrimaryFailure'), catch.index('startupSnapshot()'))
        self.assertLess(catch.index('startupSnapshot()'), catch.index('directWriteStartupDiagnostic'))
        self.assertNotIn('result["error"] =', catch[catch.index('directWriteStartupDiagnostic'):])
        sidecar = IO[IO.index('func directWriteStartupDiagnostic'):]
        for token in ('O_EXCL', 'O_NOFOLLOW', 'RENAME_EXCL', '32768', 'startup-persistence.json'):
            self.assertIn(token, sidecar)
        self.assertNotIn('fsync', sidecar)
        self.assertNotIn('startup', SINK[SINK.index('    func result()'):])
        self.assertIn('result["startupPersistenceDiagnostic"] = sink.startupSnapshot()', MAIN)

    def test_explicit_work_stage_boundaries(self):
        for before, work, after in (
            ('.writerOwnerBegin)', 'try require(ownerValid(), "persistence-owner-changed")', '.writerOwnerEnd)'),
            ('.regionHashBegin)', 'let regions = try directROIManifest', '.regionHashEnd)'),
            ('.writeBegin)', 'try data.write(', '.writeEnd)'),
            ('.packedHashBegin)', 'retained["packedPixelSHA256"] = digest(data)', '.packedHashEnd)'),
        ):
            self.assertLess(SINK.index(before), SINK.index(work))
            self.assertLess(SINK.index(work), SINK.index(after))
        copy = ROI[ROI.index('func directCopyROIs'):ROI.index('func directROIManifest')]
        self.assertLess(copy.index('.bufferLockBegin'), copy.index('CVPixelBufferLockBaseAddress'))
        self.assertLess(copy.index('CVPixelBufferLockBaseAddress'), copy.index('.bufferLockEnd'))
        self.assertLess(copy.index('.rowCopyEnd'), copy.index('"roi-unlock-failed"'))
        self.assertLess(copy.index('"roi-unlock-failed"'), copy.index('.bufferUnlockEnd'))



def cpu_pair(first, last):
    """Deterministic mirror of the Swift optional-pair predicate, not native execution."""
    if first is None or last is None:
        return None
    before, after, thread, cpu, status = first
    before2, after2, thread2, cpu2, status2 = last
    if status or status2 or thread <= 0 or thread != thread2:
        return None
    if not before <= after <= before2 <= after2 or cpu > cpu2:
        return None
    return cpu2 - cpu


def cpu_conversion(thread_ok, thread, clock_ok, seconds, nanoseconds):
    if not thread_ok or thread == 0: return (1, 0)
    if not clock_ok: return (2, 0)
    if seconds < 0 or not 0 <= nanoseconds < 1_000_000_000: return (3, 0)
    total = seconds * 1_000_000_000 + nanoseconds
    if total > 2**64 - 1: return (4, 0)
    return (0, total)


class ThreadCPUModelTests(unittest.TestCase):
    def test_same_thread_valid_zero_is_distinct_from_unavailable(self):
        a = [10, 11, 9, 100, 0]
        self.assertEqual(cpu_pair(a, [20, 21, 9, 100, 0]), 0)
        self.assertEqual(cpu_pair(a, [20, 21, 9, 105, 0]), 5)
        for b in (None, [20,21,10,105,0], [20,21,9,99,0], [20,21,9,105,2],
                  [9,21,9,105,0], [20,19,9,105,0]):
            self.assertIsNone(cpu_pair(a, b))
        self.assertIsNone(cpu_pair(None, a))
        self.assertIsNone(cpu_pair([10,11,0,100,0], [20,21,0,105,0]))
        self.assertIsNone(cpu_pair([10,9,9,100,0], [20,21,9,105,0]))

    def test_checked_timespec_and_optional_status(self):
        self.assertEqual(cpu_conversion(True,9,True,0,0), (0,0))
        self.assertEqual(cpu_conversion(False,0,True,1,1), (1,0))
        self.assertEqual(cpu_conversion(True,9,False,1,1), (2,0))
        for seconds, nanos in [(-1,0),(0,-1),(0,1_000_000_000)]:
            self.assertEqual(cpu_conversion(True,9,True,seconds,nanos), (3,0))
        self.assertEqual(cpu_conversion(True,9,True,2**63-1,0), (4,0))
        limit=2**64-1
        self.assertEqual(cpu_conversion(True,9,True,limit//10**9,limit%10**9),(0,limit))
        self.assertEqual(cpu_conversion(True,9,True,limit//10**9,limit%10**9+1),(4,0))

    def test_fixed_eligibility_endpoint_bound(self):
        reads=0
        for index in range(6000):
            for stage in range(6):
                if index < (3 if stage <= 2 else 2): reads += 2
        self.assertEqual(reads,30)


class ThreadCPUSourceTests(unittest.TestCase):
    def test_optional_sampler_preserves_errno_and_never_fails_capture(self):
        block=ROI[ROI.index('struct DirectCPUSample {'):ROI.index('struct DirectCPUInterval {')]
        self.assertIn('let savedErrno = errno',block)
        self.assertIn('defer { errno = savedErrno }',block)
        self.assertIn('pthread_threadid_np(nil, &thread)',block)
        self.assertIn('clock_gettime(CLOCK_THREAD_CPUTIME_ID, &value)',block)
        self.assertIn('clockResult != 0',block)
        self.assertIn('value.tv_nsec >= 1_000_000_000',block)
        self.assertIn('multipliedReportingOverflow',block)
        self.assertIn('addingReportingOverflow',block)
        for token in ('throw ', 'try ', 'failed(', 'require(', 'lock.lock', '.write(', 'while ', 'for '):
            self.assertNotIn(token,block)

    def test_same_thread_pairs_only_after_complete_acquisition(self):
        block=ROI[ROI.index('struct DirectCPUInterval {'):ROI.index('struct DirectStartupRecord {')]
        for token in ('first.status == 0 && last.status == 0',
                      'first.threadID > 0 && first.threadID == last.threadID',
                      'first.wallAfterMach <= last.wallBeforeMach',
                      'first.cpuNanoseconds <= last.cpuNanoseconds',
                      'delta as Any? ?? NSNull()'):
            self.assertIn(token,block)
        begin=SINK[SINK.index('    private func startupCPUBegin'):SINK.index('    private func startupCPUPublish')]
        end=SINK[SINK.index('    private func startupCPUEnd'):SINK.index('    func startupSnapshot')]
        publish=SINK[SINK.index('    private func startupCPUPublish'):SINK.index('    private func startupCPUEnd')]
        self.assertLess(begin.index('guard index'),begin.index('DirectCPUSample.capture()'))
        self.assertLess(end.index('DirectCPUSample.capture()'),end.index('startupCPUPublish('))
        self.assertNotIn('lock.lock()',begin+end)
        self.assertNotIn('DirectCPUSample.capture()',publish)
        self.assertEqual(publish.count('lock.lock()'),1)
        self.assertIn(' ? 3 : 2',begin)
        self.assertIn('cpuDiagnostic: startupIndex < 3 ?',SINK)

    def test_split_allocation_and_row_loop_no_copy_refactor(self):
        block=ROI[ROI.index('func directCopyROIs'):ROI.index('func directROIManifest')]
        self.assertEqual(block.count('var data = Data(capacity: plan.byteCount)'),1)
        self.assertEqual(block.count('data.append(source.assumingMemoryBound'),1)
        self.assertIn('for region in plan.regions',block)
        self.assertIn('for row in region.y ..< region.y + region.height',block)
        self.assertIn('count: region.width * 4',block)
        self.assertLess(block.index('let allocationCPU'),block.index('var data = Data('))
        self.assertLess(block.index('var data = Data('),block.index('cpuDiagnostic?(.destinationAllocation'))
        self.assertLess(block.index('guard let base'),block.index('let copyCPU'))
        self.assertLess(block.index('let copyCPU'),block.index('for region'))
        self.assertLess(block.index('data.append('),block.index('cpuDiagnostic?(.rowCopy'))
        self.assertNotIn('memcpy(',block)
        self.assertNotIn('withUnsafeMutableBytes',block)

    def test_cpu_endpoints_surround_original_writer_work_without_lock(self):
        for stage,work in [('regionHash','let regions = try directROIManifest'),
                           ('atomicWrite','try data.write('),
                           ('packedHash','retained["packedPixelSHA256"] = digest(data)')]:
            start=SINK.index(f'let {stage}CPU = startupCPUBegin')
            end=SINK.index(f'startupCPUEnd(startupIndex, .{stage}')
            self.assertLess(start,SINK.index(work))
            self.assertLess(SINK.index(work),end)
            between=SINK[start:end]
            self.assertNotIn('lock.lock()',between)
            self.assertNotIn('startupMark(',between)
        self.assertIn('bytes.count <= 32768',IO)
        self.assertNotIn('CLOCK_PROCESS_CPUTIME_ID',SINK+ROI)

if __name__ == '__main__':
    unittest.main()
