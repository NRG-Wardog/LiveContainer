"""Synthetic real-decoder -> broad region-correspondence geometry experiment.

No native run or unmeasured pixel-edge precision. The renderer below is an
explicit synthetic area-coverage model, not a claim about Apple's renderer.
"""
from fractions import Fraction as F
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
LOCAL = HERE.parent
PREFLIGHT = LOCAL.parent / "window-capture-candidate/ci/p1/preflight"
sys.path[:0] = [str(PREFLIGHT), str(LOCAL / "pixels"), str(LOCAL / "geometry")]
import direct_geometry as g
import registration
import window_bgra
import window_packet
import live_strip
import magenta_components

SESSION = "00112233445566778899aabbccddeeff"
WIDTH, HEIGHT = 574, 1316
APP = g.Box(0, 0, 402, 874)
AX_RECTS = ((8, 8, 114, 66), (280, 8, 114, 66),
            (8, 800, 114, 66), (280, 800, 114, 66))
FEATURE_RECTS = ((4, 4, 2, 2), (396, 4, 2, 2), (4, 868, 2, 2), (396, 868, 2, 2))
CONTROL = g.Box(96, 350, 306, 394)
MARKER = g.Box(105, 730, 297, 746)
SOURCES = (Path(__file__), Path(g.__file__), Path(registration.__file__),
           Path(window_bgra.__file__), Path(window_packet.__file__), Path(live_strip.__file__),
           Path(magenta_components.__file__))


def source_hashes():
    return {str(path.relative_to(LOCAL.parent)): sha256(path.read_bytes()).hexdigest() for path in SOURCES}


def outward(box):
    return [math.floor(box.left), math.floor(box.top), math.ceil(box.right), math.ceil(box.bottom)]


def q(value):
    value = F(value)
    return [value.numerator, value.denominator]


def interval(value):
    return {"lo": q(value.lo), "hi": q(value.hi)}


def box(value):
    return {key: q(getattr(value, key)) for key in ("left", "top", "right", "bottom")}


def paint_grid(data, stride, left, top, cell_x, cell_y, colors):
    rows, columns = len(colors), len(colors[0])
    right, bottom = left + columns * cell_x, top + rows * cell_y
    if not (0 <= left < right <= WIDTH and 0 <= top < bottom <= HEIGHT):
        raise ValueError("synthetic source clipped")
    for py in range(math.floor(top), math.ceil(bottom)):
        ys = range(max(0, math.floor((py - top) / cell_y)), min(rows - 1, math.floor((py + 1 - top) / cell_y)) + 1)
        for px in range(math.floor(left), math.ceil(right)):
            xs = range(max(0, math.floor((px - left) / cell_x)), min(columns - 1, math.floor((px + 1 - left) / cell_x)) + 1)
            values, area = [F(0), F(0), F(0)], F(0)
            for y in ys:
                dy = max(F(0), min(F(py + 1), top + (y + 1) * cell_y) - max(F(py), top + y * cell_y))
                for x in xs:
                    dx = max(F(0), min(F(px + 1), left + (x + 1) * cell_x) - max(F(px), left + x * cell_x))
                    weight = dx * dy
                    for channel in range(3):
                        values[channel] += colors[y][x][channel] * weight
                    area += weight
            offset = py * stride + px * 4
            data[offset:offset + 4] = bytes([round(v + 128 * (1 - area)) for v in values] + [255])


def render(*, scale=F(7, 5), tx=F(28, 5), ty=F(231, 5), tiny_features=False, strip=False, feature_rects=FEATURE_RECTS):
    """Exact-area synthetic grayscale rectangles rounded to 8-bit samples.

    The fixture packet uses 3-point cells in a 114x66 point view. Ground-truth
    transform is used only by this renderer and the diagnostic comparison;
    it is NEVER supplied to the interval adapter or geometry fitting.
    """
    stride = WIDTH * 4 + 16
    data = bytearray(bytes((128, 128, 128, 255)) * WIDTH + bytes(16)) * HEIGHT
    for ordinal, (ax, ay, aw, ah) in enumerate(AX_RECTS, 1):
        left, top, cell = tx + scale * ax, ty + scale * ay, scale * 3
        cells = window_packet.grid(window_packet.packet_bytes(SESSION, ordinal))
        paint_grid(data, stride, left, top, cell, cell, [[(v, v, v) for v in row] for row in cells])
    if tiny_features:
        for x, y, w, h in feature_rects:
            paint_grid(data, stride, tx + scale * x, ty + scale * y, scale * w, scale * h, [[(255, 0, 255)]])
    if strip:
        bits = [False, True, False, True] + [bool(456 >> bit & 1) for bit in range(16)] + [True, False, True, False]
        colors = [[(255, 255, 255) if bit else (0, 0, 0) for bit in bits]]
        paint_grid(data, stride, tx + scale * MARKER.left, ty + scale * MARKER.top, scale * 8, scale * 16, colors)
    return bytes(data), stride


def broad_anchors(decoded, *, mode="whole-support"):
    """Consume exact observed integers only; discard float board estimates.

    Assumption is explicit source-locality + one upright axis-aligned transform:
    the identified packet support corresponds to SOME point inside its measured
    source UIView. No nominal source edge or center is assigned to a pixel edge.
    """
    if mode not in ("whole-support", "one-observed-pixel"):
        raise ValueError("unknown synthetic correspondence mode")
    if decoded["session"] != SESSION or [a["anchor"] for a in decoded["anchors"]] != [1, 2, 3, 4]:
        raise ValueError("missing/mismatched actual decoded packets")
    anchors = []
    for row, source in zip(decoded["anchors"], AX_RECTS):
        left, top, right, bottom = row["observedDarkRingBounds"]
        if any(type(v) is not int for v in (left, top, right, bottom)):
            raise ValueError("integer observed support required")
        if not (0 <= left < right <= WIDTH and 0 <= top < bottom <= HEIGHT):
            raise ValueError("observed support clipped")
        x, y, width, height = source
        name = "anchor-" + str(row["anchor"])
        # These are the centers of actual retained integer-indexed pixels.
        # They are not estimates or error bounds for the underlying vector edge.
        px = g.Interval(F(2 * left + 1, 2), F(2 * right - 1, 2))
        py = g.Interval(F(2 * top + 1, 2), F(2 * bottom - 1, 2))
        if mode == "one-observed-pixel":
            px, py = g.Interval(px.lo, px.lo), g.Interval(py.lo, py.lo)
        anchors.append(g.Anchor(name, SESSION, g.Interval(x, x + width), g.Interval(y, y + height),
                                px, py, g.PixelRect(left, top, right - left, bottom - top), name))
    return tuple(anchors)


def diagnose(raw, stride, decoded, mode, truth):
    anchors = broad_anchors(decoded, mode=mode)
    fit, holdout = anchors[:3], anchors[3:]
    xp, yp = g._fit_axis(g._observations(fit, "x")), g._fit_axis(g._observations(fit, "y"))
    g._constrain(xp, g._observations(holdout, "x"))
    g._constrain(yp, g._observations(holdout, "y"))
    vx, vy = g._map(xp, g.Interval(0, 402)), g._map(yp, g.Interval(0, 874))
    derived = g.Box(vx.lo, vy.lo, vx.hi, vy.hi)
    cx, cy = g._map(xp, g.Interval(CONTROL.left, CONTROL.right)), g._map(yp, g.Interval(CONTROL.top, CONTROL.bottom))
    control = g.Box(cx.lo, cy.lo, cx.hi, cy.hi)
    regions = (g.Region("control", CONTROL, "control"), g.Region("marker", MARKER, "marker")) + tuple(
        g.Region("anchor-" + str(n), g.Box(x, y, x + w, y + h), "anchor")
        for n, (x, y, w, h) in enumerate(AX_RECTS, 1))
    # Geometry's Crop is packed BGRA. Keep its baseline hash bound to the exact
    # source bytes by separately retaining both the strided original and pack.
    packed = b"".join(raw[y * stride:y * stride + WIDTH * 4] for y in range(HEIGHT))
    full = g.Crop("full", g.PixelRect(0, 0, WIDTH, HEIGHT), packed, sha256(packed).hexdigest())
    identity = g.Identity(SESSION, 101, 99, WIDTH, HEIGHT, APP, g.Box(0, 0, WIDTH, HEIGHT), 1, 1)
    failure = None
    frozen = None
    try:
        frozen = g.freeze(identity, anchors, tuple(a.name for a in fit), tuple(a.name for a in holdout), regions, full)
    except g.InvalidEvidence as error:
        failure = str(error)
    # Arithmetic sanity only: the renderer truth must lie in the conservative
    # feasible set. This is not used to narrow or rescue any bound.
    scale, tx, ty = truth
    true_control = g.Box(scale * CONTROL.left + tx, scale * CONTROL.top + ty,
                         scale * CONTROL.right + tx, scale * CONTROL.bottom + ty)
    if not control.contains(true_control):
        raise ValueError("synthetic truth escaped interval envelope")
    return dict(schema="p1-synthetic-registration-interval-experiment-v1", mode=mode,
                sourceLocalityAssumed=True, nativeRenderingModelEstablished=False,
                fitAnchors=[a.name for a in fit], independentHoldout=[a.name for a in holdout],
                anchorIntervals=[dict(name=a.name, appX=interval(a.app_x), appY=interval(a.app_y),
                                      pixelX=interval(a.pixel_x), pixelY=interval(a.pixel_y)) for a in anchors],
                scaleX=interval(g.Interval(min(s for s, _ in xp), max(s for s, _ in xp))),
                scaleY=interval(g.Interval(min(s for s, _ in yp), max(s for s, _ in yp))),
                fitDerivedViewport=box(derived), viewportOutwardPixels=outward(derived),
                viewportFits=g.Box(0, 0, WIDTH, HEIGHT).contains(derived),
                fullControlEnvelope=box(control), controlOutwardPixels=outward(control),
                syntheticTrueControl=box(true_control), syntheticTruthContained=True,
                geometryFreezeSucceeded=frozen is not None, geometryFailure=failure,
                baselinePackedSHA256=full.sha256, admissionEligible=False)


def experiment():
    sources = source_hashes()
    scale, tx, ty = F(7, 5), F(28, 5), F(231, 5)
    raw, stride = render(scale=scale, tx=tx, ty=ty)
    decoded = registration.locate_registration(raw, WIDTH, HEIGHT, stride, SESSION)
    reports = [diagnose(raw, stride, decoded, mode, (scale, tx, ty))
               for mode in ("whole-support", "one-observed-pixel")]
    if source_hashes() != sources:
        raise ValueError("dependency source changed during experiment")
    output = dict(schema="p1-synthetic-registration-interval-study-v1", appSize=[402, 874], frameSize=[WIDTH, HEIGHT],
                  session=SESSION, sourceAXRectangles=[list(v) for v in AX_RECTS],
                  syntheticRenderer="exact area coverage of axis-aligned source cells; grayscale round-to-nearest-even",
                  syntheticTransform=dict(scale=q(scale), tx=q(tx), ty=q(ty)),
                  decodedPixels=decoded, results=reports, sourceHashes=sources,
                  nativeCompiled=False, nativeExecuted=False, admissionEligible=False)
    return raw, output


if __name__ == "__main__":
    raw, report = experiment()
    (HERE / "synthetic-frame.bgra").write_bytes(raw)
    (HERE / "result.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    for row in report["results"]:
        print(row["mode"], "viewport", row["viewportOutwardPixels"], "control", row["controlOutwardPixels"],
              "freeze:", row["geometryFailure"] or "passed", "admissionEligible=false")
