"""Source guard tests only; not a Swift compile or filesystem execution."""
from pathlib import Path
import unittest

class IOSourceTests(unittest.TestCase):
    def test_descriptor_bound_existing_reader_and_canonical_shape(self):
        source=Path(__file__).with_name('session_io.swift').read_text()
        for value in ('O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK','P1RequestReader.read(directory: descriptor)',
                      'observed.discarded == nil','data == previous','canonical == data && Set(row.keys) == keys',
                      'width == baselineWidth && height == baselineHeight && stride == baselineStride',
                      'try plan.validate()'):
            self.assertIn(value,source)
        self.assertNotIn('Data(contentsOf:',source)
        self.assertNotIn('Process()',source)



class DurablePrimaryFailureTests(unittest.TestCase):
    def test_exclusive_durable_atomic_publication_no_replacement(self):
        source=Path(__file__).with_name('session_io.swift').read_text()
        block=source[source.index('func directWritePrimaryFailure'):]
        for token in ('O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK', 'O_CREAT | O_EXCL | O_NOFOLLOW',
                      'bytes.count <= 4096', 'errno == EINTR', 'fsync(descriptor)',
                      'renameatx_np(', 'UInt32(RENAME_EXCL)', 'fsync(parent)'):
            self.assertIn(token,block)
        self.assertLess(block.index('fsync(descriptor)'),block.index('renameatx_np('))
        self.assertLess(block.index('renameatx_np('),block.index('fsync(parent)'))
        self.assertNotIn('linkat(parent, temporary, parent',block)
        self.assertNotIn('options: .atomic',block)
        self.assertNotIn('deadline.',block)
        self.assertIn('defer { close(descriptor); unlinkat(parent, temporary, 0) }',block)

    def test_only_bounded_identity_codes_and_timestamps_are_serialized(self):
        source=Path(__file__).with_name('session_io.swift').read_text()
        block=source[source.index('func directDiagnosticCode'):]
        for token in ('bytes.count <= 96', '(97...122).contains($0) || $0 == 45',
                      'session.utf8.count == 32', 'Set(value.keys)', 'Set(sink.keys)',
                      'ticks > 0 && ticks <= observed', 'is NSNull'):
            self.assertIn(token,block)
        for token in ('localizedDescription','String(describing:', 'debugDescription'):
            self.assertNotIn(token,block)
        self.assertLess(block.index('"primary-failure-binding"'),block.index('JSONSerialization.data'))

if __name__=='__main__':unittest.main()
