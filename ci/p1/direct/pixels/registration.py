"""Four retained registration boards, using the reviewed bounded BGRA decoder.

This adapter establishes pixel correspondence only. It does not establish
ownership, physical presentation, clock mapping, or feedback acceptance.
"""
import hashlib
from pathlib import Path
import window_bgra as decoder
import window_packet as packet_decoder

DECODER_SHA256 = '2d2444483d448161e1df2952cc0104e32eabf2b7f13f6b05b61994ade0ec39df'
PACKET_SHA256 = '9d4a52640b38df1e557924067c3d8f673d747e8bfa46671b7d7d4f915bc4b08b'


def locate_registration(data, width, height, stride, session):
    if hashlib.sha256(Path(decoder.__file__).read_bytes()).hexdigest() != DECODER_SHA256:
        raise ValueError('reviewed decoder source drift')
    if hashlib.sha256(Path(packet_decoder.__file__).read_bytes()).hexdigest() != PACKET_SHA256:
        raise ValueError('reviewed packet source drift')
    decoder.nonce_bytes(session)
    pixels = decoder._Pixels(data, width, height, stride)
    candidates = decoder._geometry_candidates(pixels)
    boards = {}
    for left, top, right, bottom in candidates:
        sx, sy = (right-left)/36, (bottom-top)/20
        x, y = left-sx, top-sy
        cells = decoder._sample_board(pixels, x, y, sx, sy)
        if cells is None:
            continue
        packet = decoder.decode_samples(cells)
        if packet['session'] != session:
            raise ValueError('foreign registered session')
        ordinal = packet['marker']
        if ordinal not in (1, 2, 3, 4) or ordinal in boards:
            raise ValueError('unexpected or duplicate registration ordinal')
        boards[ordinal] = {
            'anchor': ordinal, 'session': session,
            'observedDarkRingBounds': [left, top, right, bottom],
            'board': {'left': x, 'top': y, 'width': 38*sx, 'height': 22*sy,
                      'cellXPixels': sx, 'cellYPixels': sy},
        }
    if set(boards) != {1, 2, 3, 4}:
        raise ValueError('all four registration boards required')
    # Reject overlaps explicitly, including quiet zones. Do not select a subset.
    rows = [boards[i] for i in (1, 2, 3, 4)]
    for i, first in enumerate(rows):
        a = first['board']
        for second in rows[i+1:]:
            b = second['board']
            if (max(a['left'], b['left']) < min(a['left']+a['width'], b['left']+b['width'])
                and max(a['top'], b['top']) < min(a['top']+a['height'], b['top']+b['height'])):
                raise ValueError('registration boards overlap')
    return {'schema': 'p1-direct-four-anchor-pixels-v1', 'session': session,
            'anchors': rows, 'candidateCount': len(candidates), 'pixelReads': pixels.reads,
            'frame': {'format': 'BGRA8', 'width': width, 'height': height, 'stride': stride,
                      'bytes': len(pixels.data), 'sha256': hashlib.sha256(pixels.data).hexdigest()},
            'decoderSha256': DECODER_SHA256, 'packetSha256': PACKET_SHA256,
            'geometryIntervalsEstablished': False, 'admissionEligible': False}
