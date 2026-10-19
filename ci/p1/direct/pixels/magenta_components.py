"""Bounded exact-color component observations, not source authentication.

The caller must establish the explicitly stated source-locality premise: these
isolated pixels are rendered exclusively by the corresponding source-owned
UIView whose whole AX rectangle is measured. Matching packets and adjacency do
not cryptographically authenticate a same-colored component on their own.
"""
from hashlib import sha256

MAGENTA = bytes((255, 0, 255, 255))  # BGRA8, opaque, no tolerance/normalization.


def _locate(data, width, height, stride, expected_components):
    if type(expected_components) is not int or expected_components not in (1, 4):
        raise ValueError("one retained-ROI or four full-frame components required")
    if type(data) is not bytes or any(type(v) is not int for v in (width, height, stride)):
        raise ValueError("immutable bytes and exact integer dimensions required")
    if not (1 <= width <= 2048 and 1 <= height <= 2048 and width * 4 <= stride <= width * 4 + 256
            and stride % 4 == 0 and len(data) == stride * height):
        raise ValueError("bounded complete BGRA frame required")
    points = set()
    for y in range(height):
        for x in range(width):
            at = y * stride + x * 4
            if data[at:at + 4] == MAGENTA:
                points.add((x, y))
                if len(points) > 256:
                    raise ValueError("more than 256 qualifying magenta pixels")
    remaining = set(points)
    components = []
    while remaining:
        if len(components) == expected_components:
            raise ValueError("more than four magenta components")
        seed = min(remaining, key=lambda point: (point[1], point[0]))
        queue = [seed]; remaining.remove(seed); found = []
        while queue:
            x, y = queue.pop(); found.append((x, y))
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in remaining:
                    remaining.remove(point); queue.append(point)
        left, right = min(x for x, _ in found), max(x for x, _ in found) + 1
        top, bottom = min(y for _, y in found), max(y for _, y in found) + 1
        if right - left > 16 or bottom - top > 16:
            raise ValueError("magenta component exceeds 16 by 16 pixels")
        # Retain the actual support, not an ideal geometric center or edge.
        components.append(dict(bounds=[left, top, right, bottom],
                               pixels=[list(point) for point in sorted(found, key=lambda p: (p[1], p[0]))]))
    if len(components) != expected_components:
        raise ValueError("exactly four isolated magenta components required")
    return dict(schema="p1-direct-magenta-components-v1", components=components,
                qualifyingPixels=len(points), connectivity=4,
                frame=dict(width=width, height=height, stride=stride, bytes=len(data), sha256=sha256(data).hexdigest()),
                sourceLocalityEstablished=False, nativeOwnershipEstablished=False, admissionEligible=False)


def locate(data, width, height, stride):
    return _locate(data, width, height, stride, 4)


def locate_one(data, width, height, stride):
    """One actual retained anchor ROI; same bounds and exact pixel algorithm."""
    return _locate(data, width, height, stride, 1)


def adjacent(ordinal, component_bounds, board_bounds):
    left, top, right, bottom = board_bounds
    a, b, c, d = component_bounds
    horizontal = (c <= left and left - a <= right - left) if ordinal in (1, 3) else (
        a >= right and c - right <= right - left)
    vertical = (d <= top and top - b <= bottom - top) if ordinal in (1, 2) else (
        b >= bottom and d - bottom <= bottom - top)
    return horizontal and vertical


def pair_to_packets(observation, packets):
    """Fixed outward-corner adjacency; no fit, nearest-neighbor or retries.

    Sources 1/2 have a target above the packet; 3/4 below. Sources 1/3 place it
    left, 2/4 right. Each gap must be smaller than one observed packet-ring span
    on the corresponding axis. This is an explicit coarse association gate,
    never a pixel-edge precision statement or a native renderer model.
    """
    if observation["frame"] != packets["frame"]:
        # Packet frame metadata has the additional explicit pixel-format key.
        if {k: packets["frame"].get(k) for k in observation["frame"]} != observation["frame"]:
            raise ValueError("packet/component source bytes differ")
    boards = packets["anchors"]
    if [row["anchor"] for row in boards] != [1, 2, 3, 4]:
        raise ValueError("four ordered decoded nonce/ordinal boards required")
    components = observation["components"]
    if len(components) != 4:
        raise ValueError("four component inventory required")
    used, paired = set(), []
    for board in boards:
        ordinal = board["anchor"]
        left, top, right, bottom = board["observedDarkRingBounds"]
        matches = []
        for index, component in enumerate(components):
            if adjacent(ordinal, component["bounds"], [left, top, right, bottom]):
                matches.append(index)
        if len(matches) != 1 or matches[0] in used:
            raise ValueError("missing, foreign, or ambiguous source-relative component adjacency")
        index = matches[0]; used.add(index)
        paired.append(dict(anchor=ordinal, session=board["session"], component=components[index]))
    if len(used) != 4:
        raise ValueError("unassigned magenta component")
    return tuple(paired)
