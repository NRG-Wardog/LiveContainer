"""Bounded upright fractional-scale BGRA8 locator. No image/native dependency."""
import hashlib
import math

from window_packet import COLUMNS, ROWS, decode_samples, nonce_bytes

MAX_DIMENSION = 2048
MAX_STRIDE = 16384
MAX_BYTES = 32 * 1024 * 1024
MAX_CANDIDATES = 64
MAX_PIXEL_READS = 16 * 1024 * 1024
MIN_CELL_PIXELS = 4


class _Pixels:
    def __init__(self, data, width, height, stride):
        if any(type(value) is not int for value in (width, height, stride)):
            raise ValueError('integer frame geometry required')
        if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
            raise ValueError('frame dimensions outside bounds')
        if not width * 4 <= stride <= MAX_STRIDE:
            raise ValueError('frame stride outside bounds')
        if stride * height > MAX_BYTES:
            raise ValueError('frame byte budget exceeded')
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError('raw BGRA bytes required')
        view = memoryview(data)
        if not view.c_contiguous or view.nbytes != stride * height:
            raise ValueError('BGRA byte count or contiguity differs')
        self.data = bytes(view)  # Immutable snapshot; metadata/hash use these exact bytes.
        self.width, self.height, self.stride = width, height, stride
        self.reads = 0

    def classify(self, x, y):
        self.reads += 1
        if self.reads > MAX_PIXEL_READS:
            raise ValueError('pixel inspection budget exceeded')
        offset = y * self.stride + x * 4
        b, g, r, a = self.data[offset:offset + 4]
        if a != 255:
            return None
        if max(b, g, r) <= 48:
            return 0
        if min(b, g, r) >= 207:
            return 255
        return None


def _cell(pixels, left, top, cell_x, cell_y):
    # Read existing pixel centers in the middle 40% only. Edge grayscale is
    # excluded geometrically, never averaged, interpolated, or guessed.
    x0, x1 = math.ceil(left + .3 * cell_x - .5), math.floor(left + .7 * cell_x - .5)
    y0, y1 = math.ceil(top + .3 * cell_y - .5), math.floor(top + .7 * cell_y - .5)
    if x0 > x1 or y0 > y1 or x0 < 0 or y0 < 0 or x1 >= pixels.width or y1 >= pixels.height:
        raise ValueError('no complete central pixel interior')
    value = pixels.classify(x0, y0)
    if value is None:
        raise ValueError('unknown/transparent board pixels')
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if pixels.classify(x, y) != value:
                raise ValueError('nonuniform board cell pixels')
    return value


def _geometry_candidates(pixels):
    candidates = set()
    def end_run(start, end, y):
        if start is None:
            return
        run_width = end - start
        if run_width < 36 * MIN_CELL_PIXELS:
            return
        cell_x = run_width / 36
        anchor_x = math.floor(start + cell_x / 2)
        # First row of the top registration band. The nonce is not consulted.
        if y == 0 or pixels.classify(anchor_x, y - 1) == 0:
            return
        bottom = y
        while bottom < pixels.height and pixels.classify(anchor_x, bottom) == 0:
            bottom += 1
        cell_y = (bottom - y) / 20
        if cell_y < MIN_CELL_PIXELS:
            return
        left, top = start - cell_x, y - cell_y
        if left < 0 or top < 0 or left + COLUMNS * cell_x > pixels.width or top + ROWS * cell_y > pixels.height:
            return
        candidates.add((start, y, end, bottom))
        if len(candidates) > MAX_CANDIDATES:
            raise ValueError('registration candidate budget exceeded')
    for y in range(pixels.height):
        start = None
        for x in range(pixels.width):
            if pixels.classify(x, y) == 0:
                if start is None:
                    start = x
            elif start is not None:
                end_run(start, x, y)
                start = None
        end_run(start, pixels.width, y)
    return sorted(candidates)


def _sample_board(pixels, left, top, cell_x, cell_y):
    cells = [[None] * COLUMNS for _ in range(ROWS)]
    # First validate complete quiet/registration/inner rings. An ordinary black
    # line is not treated as a board merely because its width is divisible by 36.
    for y in range(ROWS):
        for x in range(COLUMNS):
            if 3 <= x <= 34 and 3 <= y <= 18:
                continue
            black = (1 <= x <= 36 and y in (1, 20)) or (1 <= y <= 20 and x in (1, 36))
            try:
                value = _cell(pixels, left + x * cell_x, top + y * cell_y, cell_x, cell_y)
            except ValueError as error:
                if str(error) == 'pixel inspection budget exceeded':
                    raise
                return None
            if value != (0 if black else 255):
                return None
            cells[y][x] = value
    # A fully registered board with invalid payload is an explicit failure,
    # never ignored in favor of another board carrying an expected nonce.
    for y in range(3, 19):
        for x in range(3, 35):
            cells[y][x] = _cell(pixels, left + x * cell_x, top + y * cell_y, cell_x, cell_y)
    return cells


def locate_bgra(data, width, height, stride, expected_session):
    nonce_bytes(expected_session)
    pixels = _Pixels(data, width, height, stride)
    candidates = _geometry_candidates(pixels)
    boards = []
    for ring_left, ring_top, ring_right, ring_bottom in candidates:
        cell_x, cell_y = (ring_right - ring_left) / 36, (ring_bottom - ring_top) / 20
        left, top = ring_left - cell_x, ring_top - cell_y
        cells = _sample_board(pixels, left, top, cell_x, cell_y)
        if cells is None:
            continue
        decoded = decode_samples(cells)  # Validate independently of expected nonce.
        boards.append((left, top, cell_x, cell_y, [ring_left, ring_top, ring_right, ring_bottom], decoded))
    if len(boards) != 1:
        raise ValueError('expected exactly one valid board; found ' + str(len(boards)))
    left, top, cell_x, cell_y, ring, decoded = boards[0]
    if decoded['session'] != expected_session:
        raise ValueError('session mismatch')
    return {**decoded, 'schema': 'p1-window-fixture-pixel-correspondence-v1',
            'sessionPixelCorrespondence': True,
            'board': {'left': left, 'top': top, 'cellXPixels': cell_x, 'cellYPixels': cell_y,
                      'width': COLUMNS * cell_x, 'height': ROWS * cell_y,
                      'observedDarkRingBounds': ring, 'centralSampleFraction': [.3, .7],
                      'columns': COLUMNS, 'rows': ROWS},
            'frame': {'format': 'BGRA8', 'width': width, 'height': height,
                      'stride': stride, 'bytes': len(pixels.data),
                      'sha256': hashlib.sha256(pixels.data).hexdigest()},
            'candidateCount': len(candidates), 'pixelReads': pixels.reads}
