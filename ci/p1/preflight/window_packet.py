"""Portable packet/grid reference, not a full-image locator or capture verifier."""
import re
import zlib

ROWS, COLUMNS = 22, 38
MAXIMUM_MARKER = 3600


def nonce_bytes(session):
    if not isinstance(session, str) or re.fullmatch('[0-9a-f]{32}', session) is None:
        raise ValueError('exact lowercase 128-bit session required')
    return bytes.fromhex(session)


def packet_bytes(session, marker):
    nonce = nonce_bytes(session)
    if type(marker) is not int or not 1 <= marker <= MAXIMUM_MARKER:
        raise ValueError('invalid marker')
    prefix = b'P1WC\x01' + nonce + marker.to_bytes(4, 'big') + b'\0\0\0'
    return prefix + zlib.crc32(prefix).to_bytes(4, 'big')


def grid(packet):
    if len(packet) != 32:
        raise ValueError('invalid packet length')
    cells = [[255 for _ in range(COLUMNS)] for _ in range(ROWS)]
    for y in range(1, 21):
        for x in range(1, 37):
            if y in (1, 20) or x in (1, 36):
                cells[y][x] = 0
    for bit_index in range(256):
        bit = (packet[bit_index // 8] >> (7 - bit_index % 8)) & 1
        x, y = 3 + (2 * bit_index) % 32, 3 + (2 * bit_index) // 32
        cells[y][x:x + 2] = [255 * bit, 255 * (1 - bit)]
    return cells


def decode_samples(cells, expected_session=None):
    expected = nonce_bytes(expected_session) if expected_session is not None else None
    if len(cells) != ROWS or any(len(row) != COLUMNS for row in cells):
        raise ValueError('incomplete board geometry')
    def bit(value):
        if type(value) not in (int, float) or not 0 <= value <= 255:
            raise ValueError('invalid sample')
        if value <= 48:
            return 0
        if value >= 207:
            return 1
        raise ValueError('ambiguous sample')
    values = [[bit(value) for value in row] for row in cells]
    for y in range(ROWS):
        for x in range(COLUMNS):
            if 3 <= x <= 34 and 3 <= y <= 18:
                continue
            black = (1 <= x <= 36 and y in (1, 20)) or (1 <= y <= 20 and x in (1, 36))
            if values[y][x] != int(not black):
                raise ValueError('registration/quiet-zone mismatch')
    raw = bytearray(32)
    for bit_index in range(256):
        x, y = 3 + (2 * bit_index) % 32, 3 + (2 * bit_index) // 32
        first, second = values[y][x:x + 2]
        if first == second:
            raise ValueError('invalid complementary bit pair')
        raw[bit_index // 8] |= first << (7 - bit_index % 8)
    if raw[:5] != b'P1WC\x01' or raw[25:28] != b'\0\0\0':
        raise ValueError('packet identity/version/reserved mismatch')
    if zlib.crc32(raw[:28]) != int.from_bytes(raw[28:], 'big'):
        raise ValueError('packet checksum mismatch')
    if expected is not None and raw[5:21] != expected:
        raise ValueError('session mismatch')
    marker = int.from_bytes(raw[21:25], 'big')
    if not 1 <= marker <= MAXIMUM_MARKER:
        raise ValueError('marker outside fixture bounds')
    return {'session': raw[5:21].hex(), 'marker': marker, 'packet_hex': raw.hex(),
            'admissionEligible': False, 'feedback_lifetime_established': False,
            'input_overlap_established': False, 'timestampUnitsEstablished': False}
