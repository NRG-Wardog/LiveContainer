"""Conservative diagnostic clock arithmetic. No result grants UI admission.

All mappings are conditional on continuous clocks with a stable unit rate during
one short scenario. Calibration constrains offsets; it does not prove that model
or an arbitrary compositor delay. Alternatives are enclosed, never intersected.
"""
from __future__ import annotations
import math

APP_OFFSET_MAX_WIDTH = .020
VIDEO_OFFSET_MAX_WIDTH = .120
FRAME_GAP_MAX = .120
STAGES = {'pre', 'mid', 'post'}


def require(ok, reason):
    if not ok: raise ValueError(reason)


def finite(value): return type(value) in (int, float) and math.isfinite(value)

def interval(lo, hi):
    require(finite(lo) and finite(hi) and lo <= hi, 'invalid interval')
    return (float(lo), float(hi))


def hull(alternatives):
    require(bool(alternatives), 'no plausible matches')
    rows = [interval(*row) for row in alternatives]
    return min(r[0] for r in rows), max(r[1] for r in rows)


def intersection(independent):
    require(bool(independent), 'no independent constraints')
    rows = [interval(*row) for row in independent]
    return interval(max(r[0] for r in rows), min(r[1] for r in rows))


def bounded(rows, width):
    result = intersection(rows)
    require(result[1] - result[0] <= width, 'calibration uncertainty exceeds fixed limit')
    return result


def app_host(rows):
    require(isinstance(rows, list) and len(rows) == 24 and all(sum(r.get('stage') == s for r in rows) == 8 for s in STAGES), 'missing app clock calibration stages')
    offsets = []
    ids = set()
    for row in rows:
        require(row['id'] not in ids, 'duplicate exchange ID'); ids.add(row['id'])
        hb, ar, ass, ha = [row[k] for k in ['hostBefore', 'appReceive', 'appSend', 'hostAfter']]
        require(all(finite(v) for v in [hb, ar, ass, ha]) and hb <= ha and ar <= ass, 'invalid exchange ordering')
        offsets.append(interval(ass - ha, ar - hb))
    # Every stage must independently be narrow, then all stages must agree.
    for stage in STAGES:
        bounded([off for row, off in zip(rows, offsets) if row['stage'] == stage], APP_OFFSET_MAX_WIDTH)
    return bounded(offsets, APP_OFFSET_MAX_WIDTH)


def video_host(rows):
    require(isinstance(rows, list) and len(rows) == 9 and all(sum(r.get('stage') == s for r in rows) == 3 for s in STAGES), 'missing video calibration stages')
    offsets = []; ids = set()
    for row in rows:
        require(row['id'] not in ids, 'reused visual marker ID'); ids.add(row['id'])
        hb, ha = interval(row['hostBefore'], row['hostAfter'])
        # A repeated/ambiguous pixel match enlarges this observation. Only
        # independent screenshots supply constraints that may be intersected.
        first, last = hull(row['matches'])
        offsets.append(interval(hb - last, ha - first))
    for stage in STAGES:
        bounded([off for row, off in zip(rows, offsets) if row['stage'] == stage], VIDEO_OFFSET_MAX_WIDTH)
    return bounded(offsets, VIDEO_OFFSET_MAX_WIDTH)


def mapping(exchanges, markers):
    ah = app_host(exchanges); hv = video_host(markers)
    return {'appMinusHost': ah, 'hostMinusVideoPTS': hv,
            'appMinusVideoPTS': (ah[0] + hv[0], ah[1] + hv[1]),
            'conditionalModel': 'continuous timelines, stable unit rate; no claim of arbitrary compositor freshness',
            'admissionEligible': False}


def frame_times(frames, offset):
    require(isinstance(frames, list) and 2 <= len(frames) <= 18000, 'missing/unbounded video frames')
    last = None; result = []
    for frame in frames:
        pts, end = interval(frame['pts'], frame['endPTS'])
        require(end > pts, 'zero/negative video frame duration')
        require(last is None or pts > last, 'duplicate/reordered presentation timestamps')
        if last is not None: require(pts - last <= FRAME_GAP_MAX, 'video presentation gap exceeds fixed limit')
        last = pts
        result.append((pts + offset[0], end + offset[1]))
    return result


def event_spacing(events, scenario):
    required = 1 if scenario == 'timeout' else 3
    require(len(events) == required, 'missing/extra actual clipboard event')
    previous = -math.inf; changes = set()
    for index, event in enumerate(events, 1):
        require(type(event['ordinal']) is int and type(event['generation']) is int and event['ordinal'] == index and finite(event['uptime']) and event['uptime'] > previous, 'invalid actual event ordinal/clock')
        previous = event['uptime']
        require(event['clipboardExact'] is True and event['payload'] == event['expectedPayload'] and event['shown'] is True, 'copy payload/context not proven')
        require(type(event['changeCount']) is int and event['changeCount'] not in changes, 'reused pasteboard event'); changes.add(event['changeCount'])
    require(events[0]['driver'] == 'normal-XCTest-tap', 'first input must be ordinary tap')
    if scenario != 'timeout':
        spacing = events[1]['uptime'] - events[0]['uptime']
        require(.75 <= spacing < 2, 'actual second input missed overlap window')
        require(events[1]['driver'] == 'experimental-XCTest-coordinate-tap', 'second overlap driver mismatch')
        require(events[2]['driver'] == 'normal-XCTest-third-tap' and events[2]['uptime'] - events[1]['uptime'] >= 5, 'third ordinary tap not separated')
        require([e['generation'] for e in events] == ([0, 1, 1] if scenario == 'replacement' else [0, 0, 0]), 'replacement/reopen identity mismatch')
        return spacing
    return None


def lifetime(frames, offset, event, old_event=None):
    """Diagnostic sufficient observations; unknown/ambiguous labels fail closed.

    Label values must be produced from the recorded production-control pixels.
    Fixture event markers are never label evidence. Retain every raw frame.
    """
    times = frame_times(frames, offset)
    target = event + 1.5
    if old_event is not None: target = max(target, old_event + 2.25)
    copied = [i for i, (f, t) in enumerate(zip(frames, times)) if f['label'] == 'Copied' and t[0] >= event and t[1] < event + 5]
    require(copied, 'no actual Copied pixels after event')
    first = copied[0]
    witnesses = [i for i in copied if times[i][0] >= target]
    require(witnesses, 'no conservative minimum-lifetime/old-deadline witness')
    witness = witnesses[0]
    require(all(f['label'] == 'Copied' for f in frames[first:witness + 1]), 'unknown/reset pixels inside claimed copied interval')
    reset = next((i for i in range(witness + 1, len(frames)) if frames[i]['label'] == 'Copy Details' and times[i][0] > times[witness][1]), None)
    require(reset is not None and times[reset][1] - event < 5, 'expiry is not conservatively below five seconds')
    require(all(f['label'] in ['Copied', 'Copy Details'] for f in frames[witness:reset + 1]), 'unknown pixels before expiry')
    return {'firstCopiedBounds': times[first], 'lifetimeWitnessBounds': times[witness],
            'resetBounds': times[reset], 'minimumLifetimeSeconds': times[witness][0] - event,
            'expiryUpperSeconds': times[reset][1] - event, 'conditionalOnly': True, 'admissionEligible': False}
