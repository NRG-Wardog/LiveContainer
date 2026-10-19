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

if __name__=='__main__':unittest.main()
