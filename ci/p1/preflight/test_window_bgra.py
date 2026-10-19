"""Synthetic raw rasters only; no ScreenCaptureKit/native execution."""
import hashlib
import math
import unittest
from unittest.mock import patch

import window_bgra as locator
from window_packet import grid, packet_bytes

SESSION = '00112233445566778899aabbccddeeff'
OTHER = 'ffeeddccbbaa99887766554433221100'


def raster(boards, width=None, height=None, padding=0):
    width = width or max(x + 38 * scale for x, y, scale, session, marker in boards) + 9
    height = height or max(y + 22 * scale for x, y, scale, session, marker in boards) + 11
    stride = width * 4 + padding
    data = bytearray(b'\x80\x80\x80\xff' * width + bytes(padding)) * height
    for left, top, scale, session, marker in boards:
        cells = grid(packet_bytes(session, marker))
        for y, row in enumerate(cells):
            for x, value in enumerate(row):
                color = bytes([value, value, value, 255])
                for dy in range(scale):
                    offset = (top + y * scale + dy) * stride + (left + x * scale) * 4
                    data[offset:offset + scale * 4] = color * scale
    return data, width, height, stride


def fractional_raster(left, top, sx, sy, session=SESSION, marker=23):
    """Exact area coverage of synthetic rectangles; decoder does no resampling."""
    width, height = math.ceil(left + 38 * sx) + 9, math.ceil(top + 22 * sy) + 11
    stride = width * 4 + 8
    data = bytearray(b'\x80\x80\x80\xff' * width + bytes(8)) * height
    cells = grid(packet_bytes(session, marker))
    for py in range(math.floor(top), math.ceil(top + 22 * sy)):
        for px in range(math.floor(left), math.ceil(left + 38 * sx)):
            value, area = 0.0, 0.0
            for y in range(max(0, math.floor((py - top) / sy)), min(21, math.floor((py + 1 - top) / sy)) + 1):
                dy = max(0.0, min(py + 1, top + (y + 1) * sy) - max(py, top + y * sy))
                for x in range(max(0, math.floor((px - left) / sx)), min(37, math.floor((px + 1 - left) / sx)) + 1):
                    dx = max(0.0, min(px + 1, left + (x + 1) * sx) - max(px, left + x * sx))
                    value += cells[y][x] * dx * dy
                    area += dx * dy
            level = min(255, max(0, round(value + 128 * (1 - area))))
            offset = py * stride + px * 4
            data[offset:offset + 4] = bytes([level, level, level, 255])
    return data, width, height, stride


class LocatorTests(unittest.TestCase):
    def test_fractional_scaling_translation_and_antialiased_edges(self):
        for left, top, sx, sy in ((13.25, 17.5, 6.25, 5.75), (5.4, 8.3, 6.37, 6.37),
                                  (7.7, 6.1, 7.4, 5.2), (3.6, 4.3, 4.2, 4.4)):
            with self.subTest(left=left, top=top, sx=sx, sy=sy):
                args = fractional_raster(left, top, sx, sy)
                self.assertTrue(any(value not in (0, 128, 255) for value in args[0]))
                result = locator.locate_bgra(*args, SESSION)
                self.assertEqual(result['marker'], 23)
                self.assertAlmostEqual(result['board']['cellXPixels'], sx, delta=.1)
                self.assertAlmostEqual(result['board']['cellYPixels'], sy, delta=.15)
                self.assertAlmostEqual(result['board']['left'], left, delta=1.5)
                self.assertAlmostEqual(result['board']['top'], top, delta=1.5)

    def test_translations_integer_scales_and_padding(self):
        for left, top, scale in ((0, 0, 4), (13, 17, 6), (19, 5, 8), (7, 11, 16)):
            args = raster([(left, top, scale, SESSION, 17)], padding=12)
            result = locator.locate_bgra(*args, SESSION)
            self.assertEqual(result['board']['left'], left)
            self.assertEqual(result['board']['top'], top)
            self.assertEqual(result['board']['cellXPixels'], scale)
            self.assertEqual(result['marker'], 17)
            self.assertEqual(result['frame']['sha256'], hashlib.sha256(args[0]).hexdigest())
            self.assertFalse(result['admissionEligible'])

    def test_wrong_nonce_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, 'session mismatch'):
            locator.locate_bgra(*raster([(3, 4, 6, OTHER, 1)]), SESSION)

    def test_multiple_expected_boards_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'found 2'):
            locator.locate_bgra(*raster([(2, 3, 6, SESSION, 1), (260, 3, 6, SESSION, 2)]), SESSION)

    def test_one_expected_and_one_other_board_are_still_ambiguous(self):
        with self.assertRaisesRegex(ValueError, 'found 2'):
            locator.locate_bgra(*raster([(2, 3, 6, SESSION, 1), (260, 3, 6, OTHER, 2)]), SESSION)

    def test_blank_frame_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'found 0'):
            locator.locate_bgra(bytes([255] * 128 * 128 * 4), 128, 128, 512, SESSION)

    def test_damaged_payload_pixel_is_rejected_without_averaging(self):
        data, w, h, stride = raster([(3, 4, 6, SESSION, 1)])
        index = (4 + 8 * 6 + 2) * stride + (3 + 5 * 6 + 2) * 4
        data[index:index + 4] = b'\x80\x80\x80\xff'
        with self.assertRaisesRegex(ValueError, 'nonuniform|unknown'):
            locator.locate_bgra(data, w, h, stride, SESSION)

    def test_transparent_payload_pixel_is_rejected(self):
        data, w, h, stride = raster([(3, 4, 6, SESSION, 1)])
        data[(4 + 8 * 6 + 2) * stride + (3 + 5 * 6 + 2) * 4 + 3] = 0
        with self.assertRaisesRegex(ValueError, 'transparent|nonuniform'):
            locator.locate_bgra(data, w, h, stride, SESSION)

    def test_damaged_registration_is_rejected(self):
        data, w, h, stride = raster([(3, 4, 6, SESSION, 1)])
        index = (4 + 10 * 6 + 2) * stride + (3 + 1 * 6 + 2) * 4
        data[index:index + 4] = b'\xff\xff\xff\xff'
        with self.assertRaisesRegex(ValueError, 'found 0'):
            locator.locate_bgra(data, w, h, stride, SESSION)

    def test_damaged_board_is_not_ignored_beside_good_board(self):
        data, w, h, stride = raster([(2, 3, 6, SESSION, 1), (260, 3, 6, OTHER, 2)])
        index = (3 + 8 * 6 + 2) * stride + (260 + 5 * 6 + 2) * 4
        data[index:index + 4] = b'\x80\x80\x80\xff'
        with self.assertRaisesRegex(ValueError, 'unknown|nonuniform'):
            locator.locate_bgra(data, w, h, stride, SESSION)

    def test_too_small_cell_size_rejected(self):
        with self.assertRaisesRegex(ValueError, 'found 0'):
            locator.locate_bgra(*raster([(2, 3, 1, SESSION, 1)]), SESSION)

    def test_non_board_black_line_is_not_enough(self):
        data, w, h, stride = raster([(5, 20, 4, SESSION, 1)], width=180, height=125)
        data[5 * stride + 4 * 4:5 * stride + (4 + 72) * 4] = b'\0\0\0\xff' * 72
        result = locator.locate_bgra(data, w, h, stride, SESSION)
        self.assertEqual(result['marker'], 1)

    def test_geometry_and_length_bounds(self):
        for w, h, stride, data in ((2049, 1, 8196, b''), (1, 2049, 4, b''),
                                  (1, 1, 16385, b''), (2, 1, 4, b''),
                                  (True, 1, 4, b''), (1.0, 1, 4, b''),
                                  (1, 1, 4, b'123'), (1, 1, 4, b'12345')):
            with self.subTest(w=w, h=h, stride=stride), self.assertRaises(ValueError):
                locator.locate_bgra(data, w, h, stride, SESSION)

    def test_bytes_budget_is_enforced_before_copy(self):
        with patch.object(locator, 'MAX_BYTES', 3), self.assertRaisesRegex(ValueError, 'byte budget'):
            locator.locate_bgra(b'1234', 1, 1, 4, SESSION)

    def test_noncontiguous_input_rejected(self):
        with self.assertRaisesRegex(ValueError, 'contiguity'):
            locator.locate_bgra(memoryview(b'12345678')[::2], 1, 1, 4, SESSION)

    def test_pixel_read_budget_fails_closed(self):
        with patch.object(locator, 'MAX_PIXEL_READS', 20), self.assertRaisesRegex(ValueError, 'inspection budget'):
            locator.locate_bgra(*raster([(0, 0, 4, SESSION, 1)]), SESSION)

    def test_candidate_budget_fails_closed(self):
        with patch.object(locator, 'MAX_CANDIDATES', 1), self.assertRaisesRegex(ValueError, 'candidate budget'):
            locator.locate_bgra(*raster([(2, 3, 6, SESSION, 1), (260, 3, 6, OTHER, 2)]), SESSION)


if __name__ == '__main__':
    unittest.main()
