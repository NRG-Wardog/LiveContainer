"""Actual synthetic tiny-feature pixels -> broad exact intervals -> ROI trial."""
from fractions import Fraction as F
from hashlib import sha256
from pathlib import Path
import json
import math

import explore as e
import whole_strip
import inset_strip


def trial(*, scale=F(7, 5), tx=F(28, 5), ty=F(231, 5), rendered_feature_rects=e.FEATURE_RECTS):
    raw, stride = e.render(scale=scale, tx=tx, ty=ty, tiny_features=True, strip=True, feature_rects=rendered_feature_rects)
    packets = e.registration.locate_registration(raw, e.WIDTH, e.HEIGHT, stride, e.SESSION)
    components = e.magenta_components.locate(raw, e.WIDTH, e.HEIGHT, stride)
    paired = e.magenta_components.pair_to_packets(components, packets)
    anchors, regions = [], [e.g.Region("control", e.CONTROL, "control"), e.g.Region("marker", e.MARKER, "marker")]
    for row, feature, board in zip(paired, e.FEATURE_RECTS, e.AX_RECTS):
        x, y, w, h = feature
        left, top, right, bottom = row["component"]["bounds"]
        name = "anchor-" + str(row["anchor"])
        anchors.append(e.g.Anchor(name, e.SESSION, e.g.Interval(x, x + w), e.g.Interval(y, y + h),
                                  e.g.Interval(left, right), e.g.Interval(top, bottom),
                                  e.g.PixelRect(left, top, right - left, bottom - top), name))
        bx, by, bw, bh = board
        regions.append(e.g.Region(name, e.g.Box(min(x, bx), min(y, by), max(x + w, bx + bw), max(y + h, by + bh)), "anchor"))
    anchors, regions = tuple(anchors), tuple(regions)
    fit, holdout = anchors[:3], anchors[3:]
    xp = e.g._fit_axis(e.g._observations(fit, "x")); yp = e.g._fit_axis(e.g._observations(fit, "y"))
    e.g._constrain(xp, e.g._observations(holdout, "x")); e.g._constrain(yp, e.g._observations(holdout, "y"))
    vx, vy = e.g._map(xp, e.g.Interval(0, 402)), e.g._map(yp, e.g.Interval(0, 874))
    viewport = e.g.Box(vx.lo, vy.lo, vx.hi, vy.hi)
    packed = b"".join(raw[y * stride:y * stride + e.WIDTH * 4] for y in range(e.HEIGHT))
    baseline = e.g.Crop("full", e.g.PixelRect(0, 0, e.WIDTH, e.HEIGHT), packed, sha256(packed).hexdigest())
    identity = e.g.Identity(e.SESSION, 101, 99, e.WIDTH, e.HEIGHT, e.APP, e.g.Box(0, 0, e.WIDTH, e.HEIGHT), 1, 1)
    freeze_error = None
    try:
        frozen = e.g.freeze(identity, anchors, tuple(a.name for a in fit), tuple(a.name for a in holdout), regions, baseline)
    except e.g.InvalidEvidence as error:
        frozen = None; freeze_error = str(error)
    # Continue arithmetic diagnostics on failure, never continue native input or
    # reclassify a failed freeze as accepted evidence.
    roi_rows = []
    for region in regions:
        r = region.app_box
        px, py = e.g._map(xp, e.g.Interval(r.left, r.right)), e.g._map(yp, e.g.Interval(r.top, r.bottom))
        l, t, right, bottom = math.floor(px.lo) - 1, math.floor(py.lo) - 1, math.ceil(px.hi) + 1, math.ceil(py.hi) + 1
        roi_rows.append(dict(role=region.name, rectangle=[l, t, right - l, bottom - t], bytes=(right - l) * (bottom - t) * 4))
    marker = next(row for row in roi_rows if row["role"] == "marker")["rectangle"]
    interior_diagnostics = []
    for cell in range(24):
        low = F(105) + 8 * (F(cell) + F(3, 10))
        high = F(105) + 8 * (F(cell) + F(7, 10))
        left = max(s * low + t for s, t in xp)
        right = min(s * high + t for s, t in xp)
        interior_diagnostics.append(dict(cell=cell, commonLeft=e.q(left), commonRight=e.q(right),
                                         commonWidth=e.q(right - left),
                                         wholePixelCount=max(0, math.floor(right) - math.ceil(left))))
    strip_error, decoded_strip, cells = None, None, None
    try:
        cells = inset_strip.cell_interiors((105, 730, 192, 16), xp, yp, tuple(marker))
        x, y, w, h = marker
        if min(x, y) < 0 or x + w > e.WIDTH or y + h > e.HEIGHT:
            raise ValueError("diagnostic marker crop clipped")
        marker_bytes = b"".join(raw[row * stride + x * 4:row * stride + (x + w) * 4] for row in range(y, y + h))
        decoded_strip = e.live_strip.decode(marker_bytes, w, h, cells)
    except ValueError as error:
        strip_error = str(error)
    whole_error, whole_decoded, whole_cells = None, None, None
    try:
        whole_cells = whole_strip.cell_interiors((105, 730, 192, 16), xp, yp, tuple(marker))
        x, y, w, h = marker
        if min(x, y) < 0 or x + w > e.WIDTH or y + h > e.HEIGHT:
            raise ValueError("diagnostic whole-cell marker crop clipped")
        whole_bytes = b"".join(raw[row * stride + x * 4:row * stride + (x + w) * 4] for row in range(y, y + h))
        whole_decoded = e.live_strip.decode(whole_bytes, w, h, whole_cells)
    except ValueError as error:
        whole_error = str(error)
    total = sum(row["bytes"] for row in roi_rows)
    report = dict(schema="p1-synthetic-tiny-feature-interval-v1", session=e.SESSION,
                  sourceLocalityAssumed=True, nativeRenderingModelEstablished=False,
                  sourceFeatureAXRectangles=[list(r) for r in e.FEATURE_RECTS],
                  pairing="fixed outward-corner adjacency; never fit-selected",
                  packets=packets, componentObservation=components, pairedComponents=list(paired),
                  fitAnchors=[a.name for a in fit], independentHoldout=[a.name for a in holdout],
                  pixelIntervalMeaning="complete actual qualifying pixel support, not estimated ideal edges",
                  anchorIntervals=[dict(name=a.name, appX=e.interval(a.app_x), appY=e.interval(a.app_y),
                                        pixelX=e.interval(a.pixel_x), pixelY=e.interval(a.pixel_y)) for a in anchors],
                  fitDerivedViewport=e.box(viewport), viewportOutwardPixels=e.outward(viewport),
                  geometryFreezeSucceeded=frozen is not None, geometryFailure=freeze_error,
                  diagnosticROIs=roi_rows, diagnosticROIBytes=total,
                  exceedsSuperseded256KiB=total > 256 * 1024,
                  fitsCurrent512KiB=total <= 512 * 1024, recordCap=6000,
                  stripCellXInteriorDiagnostics=interior_diagnostics,
                  stripInteriorsFound=cells is not None, stripFailure=strip_error, stripDecoded=decoded_strip,
                  wholeCellExperiment=dict(interiorsFound=whole_cells is not None, failure=whole_error,
                                           decoded=whole_decoded, cells=whole_cells,
                                           sourceSHA256=sha256(Path(whole_strip.__file__).read_bytes()).hexdigest(),
                                           admissionEligible=False),
                  syntheticTransform=dict(scale=e.q(scale), tx=e.q(tx), ty=e.q(ty)),
                  sourceHashes=e.source_hashes(), experimentSHA256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  nativeCompiled=False, nativeExecuted=False, admissionEligible=False)
    return raw, report


if __name__ == "__main__":
    raw, report = trial()
    (e.HERE / "tiny-feature-frame.bgra").write_bytes(raw)
    (e.HERE / "tiny-feature-result.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("components:", [r["bounds"] for r in report["componentObservation"]["components"]])
    print("viewport:", report["viewportOutwardPixels"], "freeze:", report["geometryFailure"] or "passed")
    print("ROI bytes:", report["diagnosticROIBytes"], "fits current 512KiB:", report["fitsCurrent512KiB"])
    print("strip:", report["stripFailure"] or report["stripDecoded"]["marker"], "admissionEligible=false")
    whole = report["wholeCellExperiment"]
    print("whole-cell strip:", whole["failure"] or whole["decoded"]["marker"], "admissionEligible=false")
