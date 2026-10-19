"""Retained bytes -> source-locality-conditional exact registration and six ROIs.

No ownership/presentation admission. The caller must bind the source-hash map
from its owned launch, retain all input bytes, prove the actual AX/source-view
locality and upright affine rendering/filtering premise, and supply the complete
owned journal prefix. Source/color/adjacency alone cannot prove those premises.
"""
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
LOCAL = HERE.parent
PREFLIGHT = LOCAL.parent / 'window-capture-candidate/ci/p1/preflight'
for path in (PREFLIGHT, LOCAL / 'geometry', LOCAL / 'handoff', LOCAL / 'fixture'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
import direct_geometry as g
import handoff_contract as handoff
import draw_receipts
import registration
import magenta_components
import roi_bytes
import live_strip
import packed_frames

SOURCES = (Path(__file__), Path(g.__file__), Path(handoff.__file__), Path(draw_receipts.__file__),
           Path(registration.__file__), Path(magenta_components.__file__), Path(roi_bytes.__file__),
           Path(live_strip.__file__), Path(packed_frames.__file__), Path(registration.decoder.__file__),
           Path(registration.packet_decoder.__file__), LOCAL / 'fixture/registration.swift',
           LOCAL / 'fixture/render_fixture.py', LOCAL / 'handoff/observer.swift',
           LOCAL / 'handoff/build_candidate.py', LOCAL / 'handoff/ui_tests.swift',
           LOCAL / 'fixture/app.swift', PREFLIGHT / 'window_fixture.swift',
           PREFLIGHT / 'runner_ui_tests.swift', PREFLIGHT.parent / 'video/app.swift',
           PREFLIGHT.parent / 'video/ui_tests.swift')


def source_hashes():
    return {str(path.relative_to(LOCAL.parent)): sha256(path.read_bytes()).hexdigest() for path in SOURCES}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact_rect(values):
    # JSON round-trips the measured Double. Preserve that exact binary value;
    # never round to a nominal decimal, integer, ideal edge, or center.
    x, y, width, height = (Fraction(v) for v in values)
    return g.Box(x, y, x + width, y + height)


def q(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def box(value):
    return [q(getattr(value, name)) for name in ('left', 'top', 'right', 'bottom')]


def interval(value):
    return [q(value.lo), q(value.hi)]


def retained_events(files, session):
    require(type(files) is tuple and 1 <= len(files) <= 1024, 'bounded immutable ordered event-file inventory required')
    rows, inventory, total = [], [], 0
    for index, item in enumerate(files, 1):
        require(type(item) is tuple and len(item) == 2, 'event filename/bytes pair required')
        name, raw = item
        require(name == f'event-{index:03d}.json' and type(raw) is bytes and 0 < len(raw) <= 131072,
                'contiguous original bounded event bytes required')
        total += len(raw)
        require(total <= 32 * 1024 * 1024, 'retained event byte ceiling')
        try:
            row = json.loads(raw.decode('utf-8'), object_pairs_hook=handoff._object_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite event JSON')))
        except (UnicodeError, RecursionError, OverflowError) as error:
            raise ValueError('invalid event JSON') from error
        require(type(row) is dict, 'event JSON object required')
        rows.append(row)
        inventory.append(dict(name=name, bytes=len(raw), sha256=sha256(raw).hexdigest()))
    proof = draw_receipts.validate_initial_draw_receipts(rows, session)
    # Hash actual ordered leaf bytes individually, not a host reserialization.
    return dict(files=inventory, drawPrerequisite=proof,
                orderedInventorySHA256=sha256(handoff.canonical(inventory)).hexdigest(),
                collectorOwnershipVerified=False, completePrefixVerifiedByAdapter=False)


@dataclass(frozen=True)
class RegistrationResult:
    frozen: g.FrozenRasterGeometry
    crops: tuple
    proof_bytes: bytes
    plan_bytes: bytes

    @property
    def proof_sha256(self):
        return sha256(self.proof_bytes).hexdigest()


def freeze_registration(request_bytes, raw, width, height, stride, *, identity,
                        expected_frame_sha256, event_files, expected_source_hashes):
    """Single full-frame registration; no transform selection, retries, or refit.

    identity is caller-supplied raster ownership binding without SCStream metadata, not verified
    by this function. Returned proof remains explicitly conditional/ineligible.
    Event files must be the actual contiguous event-001.json... owned prefix.
    """
    sources = source_hashes()
    require(type(expected_source_hashes) is dict and expected_source_hashes == sources,
            'source binding differs from owned launch expectation')
    request = handoff.validate_request(request_bytes)
    session, geometry = request['session'], request['geometry']
    require(type(identity) is g.RasterIdentity and identity.session == session and
            (identity.width, identity.height) == (width, height) and
            identity.app_viewport == exact_rect(geometry['windowFrame']),
            'native metadata/session/app viewport differs from immutable request')
    require(type(raw) is bytes and type(expected_frame_sha256) is str and
            handoff.SHA.fullmatch(expected_frame_sha256) is not None and
            sha256(raw).hexdigest() == expected_frame_sha256, 'retained baseline frame hash mismatch')
    draws = retained_events(event_files, session)
    packets = registration.locate_registration(raw, width, height, stride, session)
    components = magenta_components.locate(raw, width, height, stride)
    paired = magenta_components.pair_to_packets(components, packets)
    anchors, regions = [], [g.Region('control', exact_rect(geometry['copyFrame']), 'control'),
                            g.Region('marker', exact_rect(geometry['markerFrame']), 'marker')]
    for packet, feature, measured_board in zip(paired, geometry['features'], geometry['anchors']):
        ordinal = packet['anchor']
        require(ordinal == feature['ordinal'] == measured_board['ordinal'], 'source ordinal mismatch')
        source, board = exact_rect(feature['frame']), exact_rect(measured_board['frame'])
        left, top, right, bottom = packet['component']['bounds']
        name = f'anchor-{ordinal}'
        anchors.append(g.Anchor(name, session, g.Interval(source.left, source.right),
                                g.Interval(source.top, source.bottom), g.Interval(left, right),
                                g.Interval(top, bottom), g.PixelRect(left, top, right-left, bottom-top), name))
        # Retain the whole measured packet+feature envelope, not only the dots.
        regions.append(g.Region(name, g.Box(min(source.left, board.left), min(source.top, board.top),
                                            max(source.right, board.right), max(source.bottom, board.bottom)), 'anchor'))
    anchors, regions = tuple(anchors), tuple(regions)
    packed = b''.join(raw[y*stride:y*stride+width*4] for y in range(height))
    full = g.Crop('baseline', g.PixelRect(0, 0, width, height), packed, sha256(packed).hexdigest())
    frozen = g.freeze_raster(identity, anchors, ('anchor-1', 'anchor-2', 'anchor-3'), ('anchor-4',), regions, full)
    by_name = dict(frozen.rois)
    plan = {name: (by_name[name].x, by_name[name].y, by_name[name].width, by_name[name].height)
            for name in roi_bytes.ROLES}
    wire_plan = dict(schema='p1-direct-roi-plan-v1', session=session, windowID=identity.window_id,
                     geometrySHA256=sha256(request_bytes).hexdigest(), sourceWidth=width,
                     sourceHeight=height, sourceStride=stride,
                     regions=[dict(role=name, x=plan[name][0], y=plan[name][1], width=plan[name][2], height=plan[name][3])
                              for name in roi_bytes.ROLES])
    plan_bytes = handoff.canonical(wire_plan)
    crops, crop_proof = roi_bytes.extract(raw, width, height, stride, plan, session=session, record=1)
    retained_packets = []
    for ordinal in range(1, 5):
        name = f'anchor-{ordinal}'
        x, y, w, h = plan[name]
        observed = registration.decoder.locate_bgra(crops[name], w, h, w*4, session)
        require(observed['marker'] == ordinal, 'retained anchor ROI ordinal differs')
        a, b, c, d = observed['board']['observedDarkRingBounds']
        require([a+x, b+y, c+x, d+y] == packets['anchors'][ordinal-1]['observedDarkRingBounds'],
                'retained anchor ROI pixel support differs from full registration')
        retained_packets.append(observed)
    metadata = {row['role']: row for row in crop_proof['crops']}
    bundles = tuple(g.Crop(name, rect, crops[name], metadata[name]['sha256']) for name, rect in frozen.rois)
    for crop in bundles: crop.verify()
    # The baseline-ready control is not a retained timing ROI, but its complete
    # feasible envelope is protected from every board+feature retained region.
    baseline = exact_rect(geometry['baselineFrame'])
    bx = g._map(frozen.x_region, g.Interval(baseline.left, baseline.right))
    by = g._map(frozen.y_region, g.Interval(baseline.top, baseline.bottom))
    baseline_envelope = g.Box(bx.lo, by.lo, bx.hi, by.hi)
    for name, rectangle in frozen.rois:
        if name.startswith('anchor-'):
            require(not g._overlaps(rectangle.box, baseline_envelope), 'registration ROI overlaps complete baseline control envelope')
    marker = geometry['markerFrame']
    marker_values = tuple(Fraction(v) for v in marker)
    cells = live_strip.cell_interiors(marker_values, frozen.x_region, frozen.y_region, plan['marker'])
    decoded_strip = live_strip.decode(crops['marker'], plan['marker'][2], plan['marker'][3], cells)
    proof = dict(schema='p1-direct-retained-registration-bridge-v1', session=session,
                 geometryRequestSHA256=sha256(request_bytes).hexdigest(),
                 baselineFrameSHA256=expected_frame_sha256, packedBaselineSHA256=full.sha256,
                 sourceHashes=sources, drawReceipts=draws, packets=packets,
                 componentObservation=components, pairedComponents=list(paired),
                 identity=dict(ownerPID=identity.owner_pid, windowID=identity.window_id,
                               frameDimensions=[width,height], appViewport=box(identity.app_viewport), orientation=identity.orientation),
                 fitAnchors=list(frozen.fit_ids), independentHoldout=list(frozen.validation_ids),
                 anchors=[dict(name=a.name, appX=interval(a.app_x), appY=interval(a.app_y),
                               pixelX=interval(a.pixel_x), pixelY=interval(a.pixel_y)) for a in anchors],
                 xFeasibleVertices=[[q(s),q(t)] for s,t in frozen.x_region],
                 yFeasibleVertices=[[q(s),q(t)] for s,t in frozen.y_region],
                 derivedViewport=box(frozen.derived_viewport), baselineControlEnvelope=box(baseline_envelope),
                 sameSampleROIs=crop_proof, retainedROIPackets=retained_packets, liveMarker=decoded_strip,
                 roiPlanSHA256=sha256(plan_bytes).hexdigest(), roiPlan=wire_plan,
                 baselinePurpose='provisional-geometry-only-registration', nativeStreamMetadataEstablished=False, roiCopyRecordMeaning='local extraction ordinal, not native frame index',
                 sourceLocalityPremise='exclusive source-owned clipped UIView; whole actual AX rectangle',
                 renderingPremise='single upright positive axis-aligned affine transform; native filtering validated separately',
                 sourceLocalityEstablished=False, nativeRenderingModelEstablished=False,
                 nativeOwnershipEstablished=False, displayTimeEstablished=False,
                 nativeCompiled=False, nativeExecuted=False, admissionEligible=False)
    require(source_hashes() == sources, 'source changed during registration')
    return RegistrationResult(frozen, bundles, handoff.canonical(proof), plan_bytes)


@dataclass(frozen=True)
class StreamBindingResult:
    frozen: g.FrozenGeometry
    crops: tuple
    observed_anchors: tuple
    validator: g.GeometryValidator
    proof_bytes: bytes

    @property
    def proof_sha256(self):
        return sha256(self.proof_bytes).hexdigest()


class RegistrationJoin:
    """Consume exactly one actual first-complete stream frame, never refit.

    The caller must prove this is the owned helper's actual first complete row,
    retain all leading delivered records for final replay, and bind its native
    timebase. Single-row validation cannot establish full stream census/coverage.
    """
    def __init__(self, baseline, *, expected_baseline_proof_sha256):
        require(type(baseline) is RegistrationResult and
                baseline.proof_sha256 == expected_baseline_proof_sha256,
                'exact provisional baseline proof binding required')
        self._baseline = baseline
        self._promotion = g.GeometryPromotion(baseline.frozen)
        self._state = 'pending'

    @property
    def state(self):
        return self._state

    def promote(self, manifest_bytes, packed_bytes, *, expected_manifest_sha256, timebase):
        require(self._state == 'pending', 'registration promotion already consumed or failed')
        try:
            baseline = self._baseline
            baseline_proof = json.loads(baseline.proof_bytes)
            require(source_hashes() == baseline_proof['sourceHashes'], 'source changed since provisional freeze')
            require(type(manifest_bytes) is bytes and 0 < len(manifest_bytes) <= 65536 and
                    sha256(manifest_bytes).hexdigest() == expected_manifest_sha256,
                    'exact retained first-complete manifest hash required')
            row = json.loads(manifest_bytes.decode('utf-8'), object_pairs_hook=handoff._object_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite manifest')))
            require(type(row) is dict and type(packed_bytes) is bytes, 'actual manifest object and packed bytes required')
            plan = json.loads(baseline.plan_bytes)
            def load(name):
                require(name == row.get('packedPixels'), 'unexpected retained packed frame lookup')
                return packed_bytes
            inspected = packed_frames.inspect_first(row, plan, timebase=timebase, load=load)
            rect, scale, factor = inspected['sourceGeometry']
            old = baseline.frozen.identity
            identity = g.Identity(old.session, old.owner_pid, old.window_id, old.width, old.height,
                                  old.app_viewport, exact_rect(rect), Fraction(scale), Fraction(factor), old.orientation)
            anchors, crop_rows, observed = [], [], []
            by_roi = dict(baseline.frozen.rois)
            baseline_anchors = {a.name:a for a in baseline.frozen.anchors}
            for ordinal in range(1, 5):
                name = f'anchor-{ordinal}'; rectangle = by_roi[name]
                data = inspected['crops'][name]
                packet = registration.decoder.locate_bgra(data, rectangle.width, rectangle.height, rectangle.width*4, old.session)
                require(packet['marker'] == ordinal, 'first complete ROI ordinal differs')
                require(packet['board']['observedDarkRingBounds'] ==
                        baseline_proof['retainedROIPackets'][ordinal-1]['board']['observedDarkRingBounds'],
                        'first complete retained packet support changed')
                component_observation = magenta_components.locate_one(data, rectangle.width, rectangle.height, rectangle.width*4)
                require(component_observation['frame']['sha256'] == packet['frame']['sha256'], 'first complete packet/component bytes differ')
                component = component_observation['components'][0]
                require(magenta_components.adjacent(ordinal, component['bounds'], packet['board']['observedDarkRingBounds']),
                        'first complete feature source adjacency changed')
                left, top, right, bottom = component['bounds']
                left += rectangle.x; right += rectangle.x; top += rectangle.y; bottom += rectangle.y
                prior = baseline_anchors[name]
                anchors.append(g.Anchor(name, old.session, prior.app_x, prior.app_y, g.Interval(left,right),
                                        g.Interval(top,bottom), g.PixelRect(left,top,right-left,bottom-top), name))
                observed.append(dict(role=name, packet=packet, componentObservation=component_observation))
            anchors = tuple(anchors)
            for name, rectangle in baseline.frozen.rois:
                data = inspected['crops'][name]
                crop_rows.append(g.Crop(name,rectangle,data,sha256(data).hexdigest()))
            crops = tuple(crop_rows)
            # Metadata enters only here, from the actual source-bound complete
            # stream row. The existing frozen fit/ROIs are copied unchanged.
            final = self._promotion.promote(inspected['index'], identity, anchors, crops)
            marker = next(r.app_box for r in final.regions if r.name == 'marker')
            mr = by_roi['marker']
            cells = live_strip.cell_interiors((marker.left,marker.top,marker.right-marker.left,marker.bottom-marker.top),
                                             final.x_region,final.y_region,(mr.x,mr.y,mr.width,mr.height))
            strip = live_strip.decode(inspected['crops']['marker'],mr.width,mr.height,cells)
            proof = dict(schema='p1-direct-first-complete-geometry-binding-v1', session=old.session,
                         provisionalBaselineProofSHA256=baseline.proof_sha256,
                         geometryRequestSHA256=baseline_proof['geometryRequestSHA256'],
                         geometrySHA256Meaning='exact immutable AX-request bytes only; not pixel geometry proof',
                         roiPlanSHA256=sha256(baseline.plan_bytes).hexdigest(),
                         firstCompleteManifestSHA256=expected_manifest_sha256,
                         firstCompletePackedSHA256=sha256(packed_bytes).hexdigest(),
                         firstCompleteIndex=inspected['index'], displayTimeMach=str(inspected['displayTicks']),
                         timebaseNumer=inspected['timebaseNumer'],timebaseDenom=inspected['timebaseDenom'],
                         nativeStreamMetadata=dict(contentRect=rect,contentScale=scale,scaleFactor=factor),
                         nativeStreamMetadataBound=True, sourceHashes=baseline_proof['sourceHashes'],
                         retainedAnchors=observed, liveMarker=strip,
                         unchangedFitAndROIs=True, promotedOnce=True, finalReplayStartsAtFirstComplete=True,
                         sourceLocalityEstablished=False,nativeRenderingModelEstablished=False,
                         nativeOwnershipEstablished=False,actualFirstCompleteEstablishedByAdapter=False,
                         allDeliveredRecordsEstablished=False,displayTimeEstablished=False,admissionEligible=False)
            require(source_hashes() == baseline_proof['sourceHashes'], 'source changed during first-complete promotion')
            self._state = 'promoted'
            return StreamBindingResult(final,crops,anchors,self._promotion.validator,handoff.canonical(proof))
        except Exception:
            self._state = 'failed'
            raise


def validate_complete_frame(binding, verified, *, validator):
    """Replay one packed_frames-verified complete row using real retained crops.

    Use binding.validator to continue after its already validated first row. For
    final replay, use a fresh GeometryValidator(binding.frozen), starting again
    at the bound first complete row; all delivered status/clock records remain
    the separate packed_frames/coverage validator's responsibility. No synthetic
    reconstruction of omitted full-frame pixels is performed.
    """
    require(type(binding) is StreamBindingResult and type(validator) is g.GeometryValidator and
            validator.frozen == binding.frozen, 'promoted binding and matching validator required')
    try:
        require(not validator.failed, 'prior complete-frame failure latched')
        proof = json.loads(binding.proof_bytes)
        require(source_hashes() == proof['sourceHashes'], 'source changed after first-complete binding')
        require(type(verified) is dict and verified.get('status') == 'complete' and verified.get('newFrame') is True,
                'verified complete retained row required')
        if validator.last_index == -1:
            require(verified.get('index') == proof['firstCompleteIndex'] and
                    verified.get('packedSHA256') == proof['firstCompletePackedSHA256'] and
                    str(verified.get('displayTicks')) == proof['displayTimeMach'] and
                    verified.get('timebaseNumer') == proof['timebaseNumer'] and
                    verified.get('timebaseDenom') == proof['timebaseDenom'],
                    'final replay must restart at the bound first complete frame')
        old = binding.frozen.identity
        rect, scale, factor = verified['sourceGeometry']
        require(type(rect) is list and len(rect) == 4 and
                all(type(v) in (int,float) and math.isfinite(v) for v in rect) and
                all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (scale,factor)),
                'verified native stream metadata mutated')
        identity = g.Identity(old.session,old.owner_pid,old.window_id,old.width,old.height,old.app_viewport,
                              exact_rect(rect),Fraction(scale),Fraction(factor),old.orientation)
        require(identity == old, 'actual stream geometry changed after promotion')
        data_by_role = verified['crops']; manifest = verified['regions']
        require(type(data_by_role) is dict and set(data_by_role) == set(roi_bytes.ROLES) and
                type(manifest) is list and tuple(r.get('role') for r in manifest) == roi_bytes.ROLES,
                'six verified retained crops required in fixed role order')
        by_roi = dict(binding.frozen.rois)
        metadata = {r['role']:r for r in manifest}
        packed = b''.join(data_by_role[role] for role in roi_bytes.ROLES)
        require(sha256(packed).hexdigest() == verified['packedSHA256'], 'verified packed crop bytes mutated')
        crops = tuple(g.Crop(role,by_roi[role],data_by_role[role],metadata[role]['sha256']) for role in roi_bytes.ROLES)
        for crop in crops:
            crop.verify()
            require(metadata[crop.name]['rectangle'] == [crop.rect.x,crop.rect.y,crop.rect.width,crop.rect.height],
                    'verified retained rectangle changed')
        anchors, observations = [], []
        initial = {a.name:a for a in binding.frozen.anchors}
        for ordinal in range(1,5):
            role = f'anchor-{ordinal}'; rectangle=by_roi[role]; data=data_by_role[role]
            packet=registration.decoder.locate_bgra(data,rectangle.width,rectangle.height,rectangle.width*4,old.session)
            require(packet['marker'] == ordinal, 'complete-frame nonce/ordinal mismatch')
            prior_packet=proof['retainedAnchors'][ordinal-1]['packet']
            require(packet['board']['observedDarkRingBounds'] == prior_packet['board']['observedDarkRingBounds'],
                    'complete-frame packet support moved')
            observed=magenta_components.locate_one(data,rectangle.width,rectangle.height,rectangle.width*4)
            require(observed['frame']['sha256'] == packet['frame']['sha256'], 'complete-frame packet/component byte mismatch')
            component=observed['components'][0]
            require(magenta_components.adjacent(ordinal,component['bounds'],packet['board']['observedDarkRingBounds']),
                    'complete-frame source adjacency changed')
            l,t,r,b=component['bounds'];l+=rectangle.x;r+=rectangle.x;t+=rectangle.y;b+=rectangle.y
            prior=initial[role]
            anchors.append(g.Anchor(role,old.session,prior.app_x,prior.app_y,g.Interval(l,r),g.Interval(t,b),
                                    g.PixelRect(l,t,r-l,b-t),role))
            observations.append(dict(role=role,packet=packet,componentObservation=observed))
        geometry_proof=validator.validate(verified['index'],identity,tuple(anchors),crops)
        marker=next(r.app_box for r in binding.frozen.regions if r.name=='marker');mr=by_roi['marker']
        cells=live_strip.cell_interiors((marker.left,marker.top,marker.right-marker.left,marker.bottom-marker.top),
                                       binding.frozen.x_region,binding.frozen.y_region,(mr.x,mr.y,mr.width,mr.height))
        strip=live_strip.decode(data_by_role['marker'],mr.width,mr.height,cells)
        require(source_hashes() == proof['sourceHashes'], 'source changed during complete-frame validation')
        return dict(schema='p1-direct-complete-crop-geometry-v1',session=old.session,nativeIndex=verified['index'],
                    streamBindingProofSHA256=binding.proof_sha256,packedPixelSHA256=verified['packedSHA256'],
                    displayTimeMach=str(verified['displayTicks']),geometryProof=geometry_proof,retainedAnchors=observations,
                    actualMarker=strip['marker'],liveMarker=strip,fullFrameReconstructed=False,
                    sourceLocalityEstablished=False,allDeliveredRecordsEstablished=False,admissionEligible=False)
    except Exception:
        validator.failed = True
        raise
