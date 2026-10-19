"""Offline geometry/retention primitives; never native or feedback acceptance.

Coordinates/recognition are supplied by a separately reviewed pixel decoder.
This module checks their retained-byte binding and consistency; it cannot prove
that supplied anchor coordinates or labels were actually decoded from pixels.
No native API, filesystem, clock calibration, or production action is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, product
import re


class InvalidEvidence(ValueError):
    pass


def require(value, message):
    if not value:
        raise InvalidEvidence(message)


def integer(value, low=0, high=None):
    require(type(value) is int and value >= low and (high is None or value <= high),
            "invalid bounded integer")
    return value


def rational(value):
    require(type(value) in (int, Fraction), "exact integer/Fraction required")
    return Fraction(value)


def session(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value), "invalid session")
    return value


def digest(value):
    require(type(value) is bytes, "immutable bytes required")
    return sha256(value).hexdigest()


@dataclass(frozen=True)
class Interval:
    lo: Fraction
    hi: Fraction

    def __post_init__(self):
        object.__setattr__(self, "lo", rational(self.lo))
        object.__setattr__(self, "hi", rational(self.hi))
        require(self.lo <= self.hi, "reversed interval")

    @property
    def midpoint(self):
        return (self.lo + self.hi) / 2


@dataclass(frozen=True)
class Box:
    left: Fraction
    top: Fraction
    right: Fraction
    bottom: Fraction

    def __post_init__(self):
        for name in ("left", "top", "right", "bottom"):
            object.__setattr__(self, name, rational(getattr(self, name)))
        require(self.left < self.right and self.top < self.bottom, "empty/reversed box")

    def contains(self, other):
        return (self.left <= other.left and self.top <= other.top and
                self.right >= other.right and self.bottom >= other.bottom)


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        integer(self.x); integer(self.y)
        integer(self.width, 1); integer(self.height, 1)

    @property
    def box(self):
        return Box(self.x, self.y, self.x + self.width, self.y + self.height)

    @property
    def byte_count(self):
        return self.width * self.height * 4


@dataclass(frozen=True)
class RasterIdentity:
    """Screenshot raster binding only; no unavailable SCStream metadata."""
    session: str
    owner_pid: int
    window_id: int
    width: int
    height: int
    app_viewport: Box
    orientation: str = "portrait-up"

    def __post_init__(self):
        session(self.session); integer(self.owner_pid, 2); integer(self.window_id, 1)
        integer(self.width, 1, 2048); integer(self.height, 1, 2048)
        require(type(self.app_viewport) is Box and self.orientation == "portrait-up",
                "typed upright provisional raster identity required")


@dataclass(frozen=True)
class Identity:
    session: str
    owner_pid: int
    window_id: int
    width: int
    height: int
    app_viewport: Box
    content_rect: Box
    content_scale: Fraction
    scale_factor: Fraction
    orientation: str = "portrait-up"

    def __post_init__(self):
        session(self.session); integer(self.owner_pid, 2); integer(self.window_id, 1)
        integer(self.width, 1, 2048); integer(self.height, 1, 2048)
        require(self.orientation == "portrait-up", "unverified/unsupported orientation")
        for name in ("app_viewport", "content_rect"):
            require(type(getattr(self, name)) is Box, "typed geometry required")
        for name in ("content_scale", "scale_factor"):
            value = rational(getattr(self, name))
            require(value > 0, "invalid content scale")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Anchor:
    name: str
    session: str
    app_x: Interval
    app_y: Interval
    pixel_x: Interval
    pixel_y: Interval
    footprint: PixelRect
    roi: str

    def __post_init__(self):
        require(type(self.name) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name),
                "invalid anchor ID")
        session(self.session)
        require(type(self.roi) is str and self.roi, "anchor ROI required")
        require(all(type(v) is Interval for v in
                    (self.app_x, self.app_y, self.pixel_x, self.pixel_y)),
                "typed anchor intervals required")
        require(type(self.footprint) is PixelRect, "anchor footprint required")
        b = self.footprint.box
        require(b.left <= self.pixel_x.lo <= self.pixel_x.hi <= b.right and
                b.top <= self.pixel_y.lo <= self.pixel_y.hi <= b.bottom,
                "anchor coordinate outside retained footprint")


@dataclass(frozen=True)
class Region:
    name: str
    app_box: Box
    role: str

    def __post_init__(self):
        require(type(self.name) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.name),
                "invalid region ID")
        require(type(self.app_box) is Box, "typed region box required")
        require(self.role in ("control", "marker", "anchor"), "invalid region role")


@dataclass(frozen=True)
class Crop:
    name: str
    rect: PixelRect
    bgra: bytes
    sha256: str

    def verify(self):
        require(type(self.rect) is PixelRect and type(self.bgra) is bytes,
                "immutable tightly packed BGRA required")
        require(len(self.bgra) == self.rect.byte_count and digest(self.bgra) == self.sha256,
                "crop byte count/hash mismatch")


def _dedupe(points):
    result = []
    for point in points:
        if point not in result:
            result.append(point)
    return tuple(result)


def _clip(polygon, a, b, c):
    """Intersect a convex (scale, translation) region with a*s+b*t <= c."""
    require(polygon, "empty transform region")
    output = []
    for previous, current in zip(polygon[-1:] + polygon[:-1], polygon):
        dp = a * previous[0] + b * previous[1] - c
        dc = a * current[0] + b * current[1] - c
        if (dp <= 0) != (dc <= 0):
            ratio = dp / (dp - dc)
            output.append(tuple(p + ratio * (q - p) for p, q in zip(previous, current)))
        if dc <= 0:
            output.append(current)
    result = _dedupe(output)
    require(result, "no common frozen transform; geometry drift/incompatibility")
    return result


def _constrain(polygon, observations):
    for app, pixel in observations:
        polygon = _clip(polygon, -app.hi, -1, -pixel.lo)
        polygon = _clip(polygon, app.lo, 1, pixel.hi)
    return polygon


def _fit_axis(observations):
    """Exact feasible region, retaining scale/translation correlation.

    For positive scale, an anchor is compatible precisely when
    pixel.lo - scale*app.hi <= translation <= pixel.hi - scale*app.lo.
    All lower/upper pairs first bound scale; half-plane clipping then preserves
    the joint constraints instead of independently intersecting marginals.
    """
    lower, upper = [], []
    for (ai, pi), (aj, pj) in product(observations, repeat=2):
        coefficient, rhs = aj.lo - ai.hi, pj.hi - pi.lo
        if coefficient > 0:
            upper.append(rhs / coefficient)
        elif coefficient < 0:
            lower.append(rhs / coefficient)
        else:
            require(rhs >= 0, "contradictory coincident anchors")
    require(lower and upper, "anchors do not bound scale")
    low, high = max(lower), min(upper)
    require(0 < low <= high, "nonpositive, reflected or unresolved scale")
    tlo = min(p.lo - s * a.hi for a, p in observations for s in (low, high))
    thi = max(p.hi - s * a.lo for a, p in observations for s in (low, high))
    require(tlo <= thi, "unbounded translation")
    return _constrain(_dedupe(((low, tlo), (high, tlo), (high, thi), (low, thi))), observations)


def _map(polygon, coordinate):
    return Interval(min(s * coordinate.lo + t for s, t in polygon),
                    max(s * coordinate.hi + t for s, t in polygon))


def _anchor_index(anchors, expected_session):
    require(type(anchors) is tuple and 4 <= len(anchors) <= 16, "bounded immutable anchor inventory required")
    require(all(type(a) is Anchor for a in anchors), "typed anchors required")
    result = {a.name: a for a in anchors}
    require(len(result) == len(anchors), "duplicate anchor")
    require(all(a.session == expected_session for a in anchors), "wrong anchor session")
    return result


def _observations(anchors, axis):
    return [(getattr(a, "app_" + axis), getattr(a, "pixel_" + axis)) for a in anchors]


def _floor(value):
    return value.numerator // value.denominator


def _ceil(value):
    return -((-value.numerator) // value.denominator)


def _overlaps(a, b):
    return max(a.left, b.left) < min(a.right, b.right) and max(a.top, b.top) < min(a.bottom, b.bottom)


def _robust_noncollinear(anchors):
    # The signed area is multi-affine in these six coordinates, so its extrema
    # on their interval box occur at corners. Nominal midpoint separation alone
    # must not conceal possible collinearity under measurement uncertainty.
    for triple in combinations(anchors, 3):
        bounds = [(value.lo, value.hi) for a in triple for value in (a.app_x, a.app_y)]
        areas = [(bx-ax)*(cy-ay) - (by-ay)*(cx-ax)
                 for ax, ay, bx, by, cx, cy in product(*bounds)]
        if min(areas) > 0 or max(areas) < 0:
            return True
    return False


@dataclass(frozen=True)
class FrozenGeometry:
    identity: Identity
    anchors: tuple[Anchor, ...]
    fit_ids: tuple[str, ...]
    validation_ids: tuple[str, ...]
    regions: tuple[Region, ...]
    rois: tuple[tuple[str, PixelRect], ...]
    x_region: tuple
    y_region: tuple
    derived_viewport: Box
    baseline_sha256: str


@dataclass(frozen=True)
class FrozenRasterGeometry(FrozenGeometry):
    """Provisional fit/ROIs only. GeometryValidator rejects this exact type."""
    identity: RasterIdentity


def freeze(identity, anchors, fit_ids, validation_ids, regions, full_context, *, padding=1):
    require(type(identity) is Identity, "final native identity required")
    return _freeze(identity, anchors, fit_ids, validation_ids, regions, full_context, padding=padding)


def freeze_raster(identity, anchors, fit_ids, validation_ids, regions, full_context, *, padding=1):
    require(type(identity) is RasterIdentity, "provisional raster identity required")
    return _freeze(identity, anchors, fit_ids, validation_ids, regions, full_context, padding=padding)


def _freeze(identity, anchors, fit_ids, validation_ids, regions, full_context, *, padding):
    """One exact fit implementation; no fabricated native metadata/defaults.

    Validation anchors never derive/narrow the frozen crop bounds. Provisional
    raster geometry is a distinct type and cannot enter GeometryValidator.
    """
    require(type(identity) in (Identity, RasterIdentity) and type(full_context) is Crop, "typed baseline required")
    full_context.verify()
    require(full_context.rect == PixelRect(0, 0, identity.width, identity.height),
            "baseline is not a retained full-context source frame")
    inventory = _anchor_index(anchors, identity.session)
    require(type(fit_ids) is tuple and 3 <= len(fit_ids) <= 15 and
            type(validation_ids) is tuple and 1 <= len(validation_ids) <= 13,
            "declared fit and independent validation anchors required")
    require(len(set(fit_ids + validation_ids)) == len(fit_ids + validation_ids) and
            set(fit_ids + validation_ids) == set(inventory), "anchor split differs/overlaps")
    fit = [inventory[name] for name in fit_ids]
    # This intentionally rejects collinear nominal registration, even though
    # one diagonal pair could algebraically identify an axis-aligned transform.
    require(_robust_noncollinear(fit), "collinear/uncertain registration anchors")
    xp, yp = (_fit_axis(_observations(fit, axis)) for axis in ("x", "y"))
    validation = [inventory[name] for name in validation_ids]
    _constrain(xp, _observations(validation, "x"))
    _constrain(yp, _observations(validation, "y"))
    # AX app bounds and SCK contentRect are not independently measured guest
    # pixel edges. Project the complete app viewport conservatively from the FIT
    # region only, and check containment in actual BGRA bounds. Never tune this
    # projection/ROI with the independent validation anchor or contentRect.
    av = identity.app_viewport
    vx = _map(xp, Interval(av.left, av.right))
    vy = _map(yp, Interval(av.top, av.bottom))
    derived_viewport = Box(vx.lo, vy.lo, vx.hi, vy.hi)
    require(Box(0, 0, identity.width, identity.height).contains(derived_viewport),
            "derived app viewport may clip outside BGRA frame")
    require(type(regions) is tuple and 2 <= len(regions) <= 16 and
            all(type(r) is Region for r in regions), "bounded immutable regions required")
    require(len({r.name for r in regions}) == len(regions), "duplicate region")
    require(sum(r.role == "control" for r in regions) == 1 and
            sum(r.role == "marker" for r in regions) == 1, "one full control and marker region required")
    integer(padding, 0, 16)
    rois = {}
    region_by_name = {r.name: r for r in regions}
    for region in regions:
        require(av.contains(region.app_box), "region outside measured app viewport")
        r = region.app_box
        x, y = _map(xp, Interval(r.left, r.right)), _map(yp, Interval(r.top, r.bottom))
        left, top, right, bottom = _floor(x.lo)-padding, _floor(y.lo)-padding, _ceil(x.hi)+padding, _ceil(y.hi)+padding
        require(0 <= left < right <= identity.width and 0 <= top < bottom <= identity.height,
                "outward crop would clip; no clamping allowed")
        rois[region.name] = PixelRect(left, top, right-left, bottom-top)
    for anchor in anchors:
        require(anchor.roi in rois and rois[anchor.roi].box.contains(anchor.footprint.box),
                "registration/validation anchor not retained in frozen ROI")
        region = region_by_name[anchor.roi]
        require(region.role == "anchor", "fiducial needs its independently retained anchor region")
        require(region.app_box.left <= anchor.app_x.lo <= anchor.app_x.hi <= region.app_box.right and
                region.app_box.top <= anchor.app_y.lo <= anchor.app_y.hi <= region.app_box.bottom,
                "anchor app coordinate outside retained measured rectangle")
        for protected in regions:
            if protected.role in ("control", "marker"):
                require(not _overlaps(region.app_box, protected.app_box) and
                        not _overlaps(anchor.footprint.box, rois[protected.name].box),
                        "fiducial intersects protected production control/live strip")
    require(len({a.roi for a in anchors}) == len(anchors), "distinct fiducial regions required")
    require(all(not _overlaps(a.footprint.box, b.footprint.box) for a, b in combinations(anchors, 2)),
            "ambiguous overlapping fiducials")
    result_type = FrozenGeometry if type(identity) is Identity else FrozenRasterGeometry
    return result_type(identity, anchors, fit_ids, validation_ids, regions,
                          tuple(sorted(rois.items())), xp, yp, derived_viewport, full_context.sha256)


class GeometryPromotion:
    """One-shot join of provisional raster geometry to actual stream metadata.

    It does not infer native metadata: the caller supplies a source-bound actual
    Identity and re-decoded same-frame anchors/crops. No fit/crop recalculation.
    Any failed attempt latches closed; a second promotion always fails.
    """
    def __init__(self, provisional):
        require(type(provisional) is FrozenRasterGeometry, "provisional raster geometry required")
        self._provisional = provisional
        self._state = "pending"
        self._validator = None

    @property
    def state(self):
        return self._state

    @property
    def validator(self):
        require(self._state == "promoted", "validated stream identity not available")
        return self._validator

    def promote(self, index, identity, anchors, crops):
        require(self.state == "pending", "promotion already consumed or failed")
        try:
            p = self._provisional
            require(type(identity) is Identity, "actual complete-stream identity required")
            keys = ("session", "owner_pid", "window_id", "width", "height", "app_viewport", "orientation")
            require(all(getattr(identity, key) == getattr(p.identity, key) for key in keys),
                    "stream/raster identity mismatch")
            final = FrozenGeometry(identity, p.anchors, p.fit_ids, p.validation_ids, p.regions,
                                   p.rois, p.x_region, p.y_region, p.derived_viewport, p.baseline_sha256)
            validator = GeometryValidator(final)
            validator.validate(index, identity, anchors, crops)
            self._validator = validator
            self._state = "promoted"
            return final
        except Exception:
            self._state = "failed"
            raise


class GeometryValidator:
    """Reject drift incompatible with one common transform across all frames.

    Validation accumulates joint constraints but never refits/moves/narrows the
    frozen crop bounds. Motion inside measurement uncertainty is not detectable.
    Any failed validation latches this validator closed.
    """
    def __init__(self, frozen):
        require(type(frozen) is FrozenGeometry, "frozen geometry required")
        self.frozen = frozen
        self.x, self.y = frozen.x_region, frozen.y_region
        # Validation constraints accumulate jointly from the baseline; the
        # app-viewport projection remains fit-derived containment only.
        self.x = _constrain(self.x, _observations(frozen.anchors, "x"))
        self.y = _constrain(self.y, _observations(frozen.anchors, "y"))
        self.last_index = -1
        self.failed = False

    def validate(self, index, identity, anchors, crops):
        require(not self.failed, "prior geometry failure latched")
        try:
            integer(index)
            # Delivered-status indices can have gaps between complete samples.
            require(index > self.last_index, "reordered/reused complete sample")
            require(type(identity) is Identity and identity == self.frozen.identity,
                    "owner/window/viewport/scale/session changed")
            observed = _anchor_index(anchors, identity.session)
            baseline = {a.name: a for a in self.frozen.anchors}
            require(set(observed) == set(baseline), "anchor inventory changed")
            require(type(crops) is tuple and all(type(c) is Crop for c in crops), "immutable crop bundle required")
            by_name = {c.name: c for c in crops}
            require(len(by_name) == len(crops) and set(by_name) == dict(self.frozen.rois).keys(),
                    "missing/extra/duplicate same-frame crop")
            for name, rect in self.frozen.rois:
                crop = by_name[name]; crop.verify()
                require(crop.rect == rect, "frozen crop moved/resized")
            for name, anchor in observed.items():
                old = baseline[name]
                require((anchor.app_x, anchor.app_y, anchor.roi) == (old.app_x, old.app_y, old.roi),
                        "app registration geometry changed")
                require(anchor.footprint == old.footprint, "fiducial footprint moved/resized")
                require(by_name[anchor.roi].rect.box.contains(anchor.footprint.box),
                        "anchor footprint clipped/unretained")
            x = _constrain(self.x, _observations(anchors, "x"))
            y = _constrain(self.y, _observations(anchors, "y"))
            self.x, self.y, self.last_index = x, y, index
            # Bind sample index, exact geometry and every crop hash. Pixel
            # provenance/decoding remains the explicitly separate prerequisite.
            binding = repr((index, identity, anchors,
                            tuple((c.name, c.rect, c.sha256) for c in crops))).encode("utf-8")
            projection = self.frozen.derived_viewport
            return {"schema": "p1-direct-geometry-primitive-v2", "sampleIndex": index,
                    "bundleSHA256": digest(binding), "primitiveValid": True,
                    "viewportProof": "fit-derived-containment-in-BGRA-frame",
                    "derivedViewportBounds": tuple((v.numerator, v.denominator) for v in
                                                   (projection.left, projection.top, projection.right, projection.bottom)),
                    "admissionEligible": False}
        except Exception:
            self.failed = True
            raise


def observation_role(label, *, scenario, verified_expected_absence=False, in_copied_chain=False):
    """Classify upstream pixel observations; this does not verify that decoder.

    verified_expected_absence must be supplied only after independent retained
    pixels AND actual dismissal/identity/ordering receipts have been checked.
    Absence is never inferred from blank/unrecognized pixels here.
    """
    require(scenario in ("timeout", "replacement", "dismissal"), "unknown scenario")
    require(type(verified_expected_absence) is bool and type(in_copied_chain) is bool,
            "explicit boolean context required")
    require(label in ("Copy Details", "Copied", "expected-absent"), "unknown/ambiguous label")
    if label == "expected-absent":
        require(scenario == "dismissal" and verified_expected_absence, "unverified/unexpected absence")
    else:
        require(not verified_expected_absence, "positive label conflicts with absence proof")
    if in_copied_chain:
        require(label == "Copied", "non-Copied observation inside claimed chain")
    return {"state": label, "resetWitness": label == "Copy Details",
            "copiedWitness": label == "Copied", "admissionEligible": False}


GIB = 1024 ** 3


@dataclass(frozen=True)
class RetentionPlan:
    record_limit: int
    roi_bytes_per_record: int
    metadata_bytes_per_record: int
    context_bytes: int
    journal_bytes: int
    ancillary_bytes: int
    archive_overhead_bytes: int
    temporary_bytes: int
    case_inclusive_limit: int
    peak_disk_limit: int
    case_count: int = 1
    archive_limit: int = 4 * GIB
    raw_limit: int = 3 * GIB

    def bounds(self):
        for name in self.__dataclass_fields__:
            integer(getattr(self, name))
        integer(self.record_limit, 1, 6000)
        integer(self.roi_bytes_per_record, 1, 1024 * 1024)
        integer(self.metadata_bytes_per_record, 1)
        require(self.case_count == 1, "only one case per package is supported")
        require(self.archive_limit <= 4 * GIB and self.case_inclusive_limit <= self.archive_limit,
                "existing 16-part archive ceiling exceeded")
        integer(self.raw_limit, 1, 3 * GIB)
        # The cumulative ceiling is enforced independently before every record.
        raw = min(self.record_limit * self.roi_bytes_per_record, self.raw_limit)
        evidence = (raw + self.record_limit * self.metadata_bytes_per_record
                    + self.context_bytes + self.journal_bytes + self.ancillary_bytes)
        archive = evidence + self.archive_overhead_bytes
        peak = evidence + archive * 2 + self.temporary_bytes
        require(archive <= self.case_inclusive_limit, "inclusive case/archive plan does not fit")
        require(peak <= self.peak_disk_limit, "source/archive/parts/temp peak does not fit")
        return {"rawBytes": raw, "rawByteLimit": self.raw_limit,
                "evidenceBytes": evidence, "archiveBytes": archive,
                "partBytes": archive, "peakDiskBytes": peak, "admissionEligible": False}


class RetentionLedger:
    """Inclusive one-case byte accounting. Any overflow latches failure.

    Archive overhead must be independently bounded by the producer, including
    ZIP inventory, metadata and part-manifest bytes. No compression is assumed.
    Actual producer filesystem inventory/cleanup is outside this primitive.
    """
    def __init__(self, plan):
        require(type(plan) is RetentionPlan, "retention plan required")
        self.plan = plan; self.bounds = plan.bounds()
        self.records = 0; self.raw = 0; self.metadata = 0
        self.fixed = {k: 0 for k in ("context", "journal", "ancillary")}
        self.failed = False

    def record(self, raw_payloads, metadata):
        require(not self.failed, "prior retention failure latched")
        try:
            require(type(raw_payloads) is tuple and all(type(v) is bytes for v in raw_payloads)
                    and type(metadata) is bytes and metadata, "immutable raw/metadata bytes required")
            size = sum(len(v) for v in raw_payloads)
            require(self.records < self.plan.record_limit, "record ceiling exceeded")
            require(size <= self.plan.roi_bytes_per_record and
                    len(metadata) <= self.plan.metadata_bytes_per_record, "per-record byte ceiling exceeded")
            require(self.raw <= self.plan.raw_limit - size, "cumulative raw pixel ceiling exceeded")
            self.records += 1; self.raw += size; self.metadata += len(metadata)
        except Exception:
            self.failed = True; raise
    def fixed_bytes(self, category, payload):
        require(not self.failed, "prior retention failure latched")
        try:
            require(category in self.fixed and type(payload) is bytes, "unknown/unbounded fixed bytes")
            total = self.fixed[category] + len(payload)
            require(total <= getattr(self.plan, category + "_bytes"), "fixed byte ceiling exceeded")
            self.fixed[category] = total
        except Exception:
            self.failed = True; raise
    def verify_archive_size(self, actual_archive_bytes):
        require(not self.failed, "prior retention failure latched")
        try:
            integer(actual_archive_bytes)
            evidence = self.raw + self.metadata + sum(self.fixed.values())
            require(evidence <= actual_archive_bytes <= evidence + self.plan.archive_overhead_bytes,
                    "stored-archive size/overhead differs")
            require(actual_archive_bytes <= self.plan.case_inclusive_limit, "inclusive archive overflow")
            return {"schema": "p1-direct-retention-primitive-v1", "records": self.records,
                    "evidenceBytes": evidence, "archiveBytes": actual_archive_bytes,
                    "plannedPeakDiskBytes": self.bounds["peakDiskBytes"], "admissionEligible": False}
        except Exception:
            self.failed = True; raise


def check_geometry_plan(frozen, plan):
    """Preflight measured crop geometry against the declared one-case budget."""
    require(type(frozen) is FrozenGeometry and type(plan) is RetentionPlan,
            "typed frozen geometry and retention plan required")
    bounds = plan.bounds()
    actual = sum(rect.byte_count for _, rect in frozen.rois)
    require(actual <= plan.roi_bytes_per_record, "measured ROI geometry exceeds planned per-frame bytes")
    return {"measuredROIPerFrameBytes": actual, **bounds}
