"""Pure local schema/state oracle. It is not a host ownership or pixel verifier.

The future native producer must resolve and validate all proof hashes against
retained bytes and live registered owners before publishing an acknowledgement.
No simulator, capture API, filesystem transport, or external state is used here.
"""
from copy import deepcopy
from hashlib import sha256
import json
import math
import re

SESSION = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
UDID = re.compile(r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\Z")
MAX_INTEGER = (1 << 53) - 1
CLOCK = "runner-ProcessInfo.systemUptime"
REQUEST_KEYS = {"schema", "session", "scenario", "runnerBundleIdentifier", "runnerPID", "simulatorUDID", "geometry",
                "sampleBeforeUptime", "sampleAfterUptime", "observerEnteredUptime", "methodStartedUptime",
                "deadlineUptime", "waitLimitSeconds", "methodLimitSeconds", "clock",
                "clockEquivalenceAssumed", "admissionEligible"}
GEOMETRY_KEYS = {"coordinateSpace", "orientation", "copyIdentifier", "copyLabel", "copyFrame",
                 "markerIdentifier", "markerFrame", "baselineIdentifier", "baselineFrame", "windowFrame", "anchors",
                 "features", "registrationModel", "sourceLocalityEstablished"}
PROOF_HASH_KEYS = {"helperSourceSHA256", "ownedDeviceReceiptSHA256", "ownedGUIReceiptSHA256",
                   "windowBindingReceiptSHA256", "fourAnchorProofSHA256", "streamReadyReceiptSHA256",
                   "firstCompleteFrameSHA256"}
PROOF_TRUE_KEYS = {"captureStarted", "firstCompleteFramePresent", "guiLiveRegistered",
                   "fourAnchorsDecoded", "geometryFrozen"}
PROOF_KEYS = PROOF_HASH_KEYS | PROOF_TRUE_KEYS | {
    "schema", "session", "geometryRequestSHA256", "captureInstance", "simulatorUDID", "guiPID", "windowID",
    "helperPID", "firstCompleteFrameIndex", "firstCompleteFrameDisplayTime", "captureErrors", "ownershipErrors",
    "admissionEligible"}
ACK_KEYS = {"schema", "session", "geometryRequestSHA256", "captureReadyProof", "captureReadyProofSHA256", "admissionEligible"}


class InvalidHandoff(ValueError):
    pass


def require(value, reason):
    if not value:
        raise InvalidHandoff(reason)


def digest(data):
    require(type(data) is bytes, "immutable raw bytes required")
    return sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object_pairs(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def parse(data, *, strict_canonical=False):
    require(type(data) is bytes and 0 < len(data) <= 8192, "bounded immutable JSON bytes required")
    try:
        row = json.loads(data.decode("utf-8"), object_pairs_hook=_object_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(InvalidHandoff("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InvalidHandoff("invalid or duplicate JSON") from error
    require(type(row) is dict, "JSON object required")
    if strict_canonical:
        require(canonical(row) == data, "noncanonical acknowledgement")
    return row


def exact(row, keys):
    require(type(row) is dict and set(row) == keys, "unexpected or missing fields")


def string(value, pattern):
    require(type(value) is str and pattern.fullmatch(value) is not None, "invalid string identity")
    return value


def integer(value, minimum=0, maximum=MAX_INTEGER):
    require(type(value) is int and minimum <= value <= maximum, "bounded exact integer required")
    return value


def number(value):
    require(type(value) in (int, float) and -MAX_INTEGER <= value <= MAX_INTEGER and math.isfinite(value),
            "bounded finite number required")
    return value


def rect(value):
    require(type(value) is list and len(value) == 4, "rectangle [x,y,width,height] required")
    values = [number(v) for v in value]
    require(all(abs(v) <= 65536 for v in values) and values[2] > 0 and values[3] > 0, "invalid geometry")
    return values


def contains(outer, inner):
    x, y, w, h = outer
    a, b, c, d = inner
    return x <= a and y <= b and a + c <= x + w and b + d <= y + h


def intersects(first, second):
    x, y, w, h = first
    a, b, c, d = second
    return max(x, a) < min(x + w, a + c) and max(y, b) < min(y + h, b + d)


def validate_geometry(geometry):
    exact(geometry, GEOMETRY_KEYS)
    for key, expected in {"coordinateSpace": "XCTest-screen-points", "orientation": "portrait-up",
                          "copyIdentifier": "signin.prompt.copy-details", "copyLabel": "Copy Details",
                          "markerIdentifier": "p1-video-marker", "baselineIdentifier": "p1-video-baseline-ready"}.items():
        require(geometry[key] == expected, "wrong geometry identity or orientation")
    require(geometry["registrationModel"] == "whole-source-view-to-observed-support-v1" and
            geometry["sourceLocalityEstablished"] is False, "source locality is an external premise")
    window = rect(geometry["windowFrame"])
    occupied = [rect(geometry[k]) for k in ("copyFrame", "markerFrame", "baselineFrame")]
    require(all(contains(window, frame) for frame in occupied), "control or marker outside window")
    anchors = geometry["anchors"]
    require(type(anchors) is list and len(anchors) == 4, "four anchors required")
    for ordinal, anchor in enumerate(anchors, 1):
        exact(anchor, {"identifier", "ordinal", "frame"})
        require(anchor["identifier"] == f"p1-direct-anchor-{ordinal}" and
                integer(anchor["ordinal"], 1, 4) == ordinal, "four ordered distinct anchors required")
        frame = rect(anchor["frame"])
        require(contains(window, frame), "anchor outside window")
        require(not any(intersects(other, frame) for other in occupied), "anchor overlaps another region")
        occupied.append(frame)
    features = geometry["features"]
    require(type(features) is list and len(features) == 4, "four features required")
    for ordinal, feature in enumerate(features, 1):
        exact(feature, {"identifier", "ordinal", "frame"})
        require(feature["identifier"] == f"p1-direct-feature-{ordinal}" and
                integer(feature["ordinal"], 1, 4) == ordinal, "four ordered distinct features required")
        frame = rect(feature["frame"])
        require(frame[2:] == [3, 3] and contains(window, frame), "whole 3-by-3-point feature required inside window")
        require(not any(intersects(other, frame) for other in occupied), "feature overlaps another region")
        bx, by, bw, bh = anchors[ordinal - 1]["frame"]
        x, y, w, h = frame
        require((x + w < bx if ordinal in (1, 3) else x > bx + bw) and
                (y + h < by if ordinal <= 2 else y > by + bh), "wrong source-defined outward adjacency")
        occupied.append(frame)
    return deepcopy(geometry)


def validate_request(data):
    # Swift JSONSerialization's finite-double formatting differs from Python's.
    # Hash the exact bytes from the pinned runner producer, never a re-encoding.
    row = parse(data)
    exact(row, REQUEST_KEYS)
    require(row["schema"] == "p1-direct-baseline-geometry-v1", "wrong request schema")
    string(row["session"], SESSION)
    require(row["scenario"] in ("timeout", "replacement", "dismissal"), "unsupported scenario")
    string(row["runnerBundleIdentifier"], re.compile(r"[A-Za-z0-9.-]{1,256}\Z"))
    integer(row["runnerPID"], 2, 2_147_483_647)
    string(row["simulatorUDID"], UDID)
    validate_geometry(row["geometry"])
    times = {k: number(row[k]) for k in ("sampleBeforeUptime", "sampleAfterUptime", "observerEnteredUptime",
                                        "methodStartedUptime", "deadlineUptime")}
    require(0 < times["methodStartedUptime"] <= times["observerEnteredUptime"] <= times["sampleBeforeUptime"] <=
            times["sampleAfterUptime"] < times["deadlineUptime"], "invalid sampling/deadline order")
    require(type(row["waitLimitSeconds"]) in (int, float) and row["waitLimitSeconds"] == 120 and
            type(row["methodLimitSeconds"]) in (int, float) and row["methodLimitSeconds"] == 240,
            "observer cannot extend fixed allowances")
    require(times["deadlineUptime"] == min(times["observerEnteredUptime"] + 120, times["methodStartedUptime"] + 240),
            "deadline does not fit existing method budget")
    require(row["clock"] == CLOCK and row["clockEquivalenceAssumed"] is False and row["admissionEligible"] is False,
            "wrong clock or unsupported admission claim")
    return row


def validate_proof(proof, session, request_hash, simulator_udid):
    exact(proof, PROOF_KEYS)
    require(proof["schema"] == "p1-direct-owned-capture-ready-v1" and proof["session"] == session and
            proof["geometryRequestSHA256"] == request_hash, "wrong proof schema/session/request")
    string(proof["captureInstance"], SESSION)
    string(proof["simulatorUDID"], UDID)
    require(proof["simulatorUDID"] == simulator_udid, "wrong exact simulator UUID")
    integer(proof["guiPID"], 2, 2_147_483_647)
    integer(proof["helperPID"], 2, 2_147_483_647)
    require(proof["guiPID"] != proof["helperPID"], "conflated host process identities")
    integer(proof["windowID"], 1, (1 << 32) - 1)
    integer(proof["firstCompleteFrameIndex"])
    ticks = string(proof["firstCompleteFrameDisplayTime"], re.compile(r"[1-9][0-9]{0,19}\Z"))
    require(int(ticks) <= (1 << 64) - 1, "displayTime overflow")
    for key in PROOF_HASH_KEYS:
        string(proof[key], SHA)
    for key in PROOF_TRUE_KEYS:
        require(proof[key] is True, "capture is not ready")
    for key in ("captureErrors", "ownershipErrors"):
        require(type(proof[key]) is list and not proof[key], "capture/ownership errors")
    require(proof["admissionEligible"] is False, "proof cannot grant admission")


def validate_ack(data, request_data):
    request = validate_request(request_data)
    row = parse(data, strict_canonical=True)
    exact(row, ACK_KEYS)
    request_hash = digest(request_data)
    require(row["schema"] == "p1-direct-baseline-ack-v1" and row["session"] == request["session"] and
            row["geometryRequestSHA256"] == request_hash, "wrong acknowledgement schema/session/request")
    require(row["admissionEligible"] is False, "acknowledgement cannot grant admission")
    proof = row["captureReadyProof"]
    validate_proof(proof, request["session"], request_hash, request["simulatorUDID"])
    require(string(row["captureReadyProofSHA256"], SHA) == digest(canonical(proof)), "proof hash mismatch")
    return dict(acknowledgement=row, acknowledgementSHA256=digest(data), proofBytes=canonical(proof),
                bindingOnly=True, nativeOwnershipVerified=False, admissionEligible=False)


class HandoffState:
    """Deterministic oracle; injected times/writer are synthetic, never evidence."""

    def __init__(self, request_data):
        self.request = validate_request(request_data)
        self.request_data = bytes(request_data)
        self.deadline = self.request["deadlineUptime"]
        self.last_time = self.request["sampleAfterUptime"]
        self.state = "waiting"
        self.failure = None
        self.ack_bytes = self.proof_bytes = self.receipt_bytes = None

    def fail(self, reason):
        self.state = "failed"
        self.failure = self.failure or reason
        raise InvalidHandoff(self.failure)

    def check_time(self, now):
        if self.state == "failed":
            raise InvalidHandoff(self.failure)
        try:
            number(now)
            require(self.last_time <= now < self.deadline, "deadline exceeded or clock regressed")
        except InvalidHandoff as error:
            self.fail(str(error))
        self.last_time = now

    def poll(self, now, ack_bytes=None):
        self.check_time(now)
        if self.state != "waiting":
            self.fail("duplicate or out-of-order acknowledgement")
        if ack_bytes is None:
            return "waiting"
        try:
            validated = validate_ack(ack_bytes, self.request_data)
        except InvalidHandoff as error:
            self.fail(str(error))
        self.ack_bytes, self.proof_bytes = bytes(ack_bytes), validated["proofBytes"]
        self.state = "acknowledgement-validated"
        return self.state

    def recheck(self, now, geometry):
        self.check_time(now)
        if self.state != "acknowledgement-validated":
            self.fail("geometry recheck before acknowledgement")
        try:
            validate_geometry(geometry)
            require(canonical(geometry) == canonical(self.request["geometry"]), "geometry changed during wait")
        except InvalidHandoff as error:
            self.fail(str(error))
        self.state = "geometry-rechecked"

    def persist(self, now, writer):
        self.check_time(now)
        if self.state != "geometry-rechecked":
            self.fail("receipt before geometry recheck")
        receipt = dict(schema="p1-direct-baseline-observer-receipt-v1", session=self.request["session"],
                       result="acknowledgement-validated", geometryRequestSHA256=digest(self.request_data),
                       acknowledgementSHA256=digest(self.ack_bytes), captureReadyProofSHA256=digest(self.proof_bytes),
                       nativeOwnershipVerifiedByRunner=False, baselineTapObserved=False, admissionEligible=False)
        self.receipt_bytes = canonical(receipt)
        try:
            # The real Swift transport has durable immutable journal writes.
            # In this oracle writer success is injected and proves no fsync.
            writer(self.receipt_bytes)
        except Exception as error:
            self.fail("receipt persistence failed: " + str(error))
        self.state = "receipt-persisted"

    def release(self, now):
        self.check_time(now)
        if self.state != "receipt-persisted":
            self.fail("original tap cannot be released before durable receipt")
        self.state = "released"
        return True
