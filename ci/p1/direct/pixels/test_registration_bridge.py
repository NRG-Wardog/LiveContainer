"""Actual synthetic raster -> real decoders -> exact conditional geometry."""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

import registration_bridge as bridge
sys.path.insert(0, str(bridge.LOCAL / 'registration-experiment'))
import explore as e
FEATURES3 = tuple((Fraction(x)-Fraction(1,2),Fraction(y)-Fraction(1,2),3,3) for x,y,_,_ in e.FEATURE_RECTS)
from test_handoff_contract import request as basic_request
from test_draw_receipts import events as draw_events


def request():
    row = basic_request()
    row['session'] = e.SESSION
    geometry = row['geometry']
    geometry['windowFrame'] = [0,0,402,874]
    geometry['copyFrame'] = [96,350,210,44]
    geometry['markerFrame'] = [105,730,192,16]
    geometry['baselineFrame'] = [100,750,192,30]
    for a, rectangle in zip(geometry['anchors'], e.AX_RECTS): a['frame'] = list(rectangle)
    for a, rectangle in zip(geometry['features'], FEATURES3): a['frame'] = [float(v) if isinstance(v,Fraction) else v for v in rectangle]
    return row


def event_files():
    rows = draw_events()
    for row in rows:
        if 'session' in row: row['session'] = e.SESSION
    return tuple((f'event-{i:03d}.json', bridge.handoff.canonical(row)) for i,row in enumerate(rows,1))


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw, cls.stride = e.render(tiny_features=True, strip=True, feature_rects=FEATURES3)
        cls.identity = bridge.g.RasterIdentity(e.SESSION,101,99,e.WIDTH,e.HEIGHT,e.APP)
        cls.request_bytes = bridge.handoff.canonical(request())
        cls.events = event_files()

    def run_bridge(self, **changes):
        values = dict(request_bytes=self.request_bytes, raw=self.raw, width=e.WIDTH, height=e.HEIGHT,
                      stride=self.stride, identity=self.identity, expected_frame_sha256=sha256(self.raw).hexdigest(),
                      event_files=self.events, expected_source_hashes=bridge.source_hashes())
        values.update(changes)
        return bridge.freeze_registration(**values)

    def test_actual_retained_bytes_produce_six_frozen_rois(self):
        result = self.run_bridge(); proof = json.loads(result.proof_bytes)
        self.assertEqual(proof['sameSampleROIs']['copiedBytes'], 430336)
        self.assertEqual(proof['liveMarker']['marker'], 456)
        self.assertEqual(proof['fitAnchors'], ['anchor-1','anchor-2','anchor-3'])
        self.assertEqual(proof['independentHoldout'], ['anchor-4'])
        self.assertEqual(proof['drawReceipts']['drawPrerequisite']['drawReceiptCount'], 8)
        self.assertEqual(proof['geometryRequestSHA256'], sha256(self.request_bytes).hexdigest())
        self.assertEqual(proof['baselineFrameSHA256'], sha256(self.raw).hexdigest())
        self.assertEqual(proof['sourceHashes'], bridge.source_hashes())
        self.assertEqual(len(result.crops), 6)
        for crop in result.crops: crop.verify()
        self.assertEqual([p['marker'] for p in proof['retainedROIPackets']], [1,2,3,4])
        for key in ('sourceLocalityEstablished','nativeRenderingModelEstablished','nativeOwnershipEstablished',
                    'displayTimeEstablished','nativeCompiled','nativeExecuted','admissionEligible'):
            self.assertIs(proof[key], False)
        self.assertEqual(result.proof_sha256, sha256(result.proof_bytes).hexdigest())
        plan = json.loads(result.plan_bytes)
        self.assertEqual(tuple(r['role'] for r in plan['regions']), bridge.roi_bytes.ROLES)
        self.assertEqual(plan['geometrySHA256'], sha256(self.request_bytes).hexdigest())
        self.assertEqual(proof['roiPlanSHA256'], sha256(result.plan_bytes).hexdigest())
        self.assertEqual(proof['roiPlan'], plan)

    def test_foreign_retained_bytes_or_source_hashes_rejected(self):
        with self.assertRaisesRegex(ValueError,'frame hash'):
            self.run_bridge(raw=b'x'+self.raw[1:])
        changed = bridge.source_hashes(); changed[next(iter(changed))] = '0'*64
        with self.assertRaisesRegex(ValueError,'source binding'):
            self.run_bridge(expected_source_hashes=changed)
        with self.assertRaisesRegex(ValueError,'frame hash'):
            self.run_bridge(raw=bytearray(self.raw))

    def test_wrong_nonce_in_immutable_request_rejected(self):
        row = request(); row['session'] = 'f'*32
        identity = bridge.g.RasterIdentity('f'*32,101,99,e.WIDTH,e.HEIGHT,e.APP)
        events=[]
        for name,raw in self.events:
            event=json.loads(raw)
            if 'session' in event:event['session']='f'*32
            events.append((name,bridge.handoff.canonical(event)))
        with self.assertRaisesRegex(ValueError,'foreign registered session'):
            self.run_bridge(request_bytes=bridge.handoff.canonical(row), identity=identity, event_files=tuple(events))

    def test_missing_resized_overlapping_feature_or_geometry_rejected(self):
        for mutation in (lambda g:g['features'].pop(),
                         lambda g:g['features'][0]['frame'].__setitem__(2,2),
                         lambda g:g['features'][0].__setitem__('frame',[100,750,3,3]),
                         lambda g:g.__setitem__('sourceLocalityEstablished',True),
                         lambda g:g.__setitem__('windowFrame',[0,0,402,875])):
            row=request();mutation(row['geometry'])
            with self.assertRaises(ValueError):self.run_bridge(request_bytes=bridge.handoff.canonical(row))

    def test_fourth_actual_feature_moved_rejects_without_refit(self):
        raw,stride=e.render(tiny_features=True,strip=True,feature_rects=FEATURES3[:3]+((Fraction(791,2),Fraction(1759,2),3,3),))
        with self.assertRaisesRegex(ValueError,'no common frozen transform'):
            self.run_bridge(raw=raw,stride=stride,expected_frame_sha256=sha256(raw).hexdigest())

    def test_retained_fragmented_two_point_support_remains_rejected(self):
        # Exact local support extracted from run39299912951 baseline SHA
        # b8fe446592dbcd4a9ff60a86cc9efa9867511b1dce623ed6aa358e3472d703ba.
        # No tolerance or connectivity repair is applied to that failed frame.
        w,h=20,12;data=bytearray(bytes((240,240,240,255))*w*h)
        for x,y in ((2,1),(2,3),(15,1),(15,3),(2,9),(3,9),(2,10),(3,10),
                    (15,9),(16,9),(15,10),(16,10)):
            at=(y*w+x)*4;data[at:at+4]=bridge.magenta_components.MAGENTA
        for x in (2,15):
            at=(2*w+x)*4;data[at:at+4]=bytes((255,1,255,255))
        with self.assertRaisesRegex(ValueError,'more than four magenta'):
            bridge.magenta_components.locate(bytes(data),w,h,w*4)

    def test_foreign_actual_magenta_component_rejected(self):
        changed=bytearray(self.raw);at=500*self.stride+300*4;changed[at:at+4]=bridge.magenta_components.MAGENTA
        raw=bytes(changed)
        with self.assertRaisesRegex(ValueError,'four magenta'):
            self.run_bridge(raw=raw,expected_frame_sha256=sha256(raw).hexdigest())

    def test_full_baseline_control_envelope_protected(self):
        row=request();row['geometry']['baselineFrame']=[8,779,114,20]
        # AX rectangles do not overlap, but uncertainty + fixed retention
        # padding makes the complete projected envelope unsafe. Never clamp.
        with self.assertRaisesRegex(ValueError,'baseline control envelope'):
            self.run_bridge(request_bytes=bridge.handoff.canonical(row))

    def test_eight_draw_sources_and_contiguous_exact_bytes_required(self):
        for files in (self.events[:-1], self.events[:5]+self.events[6:],
                      tuple(reversed(self.events)), list(self.events)):
            with self.assertRaises(ValueError):self.run_bridge(event_files=files)
        rows=list(self.events);name,raw=rows[1];event=json.loads(raw);event['source']='foreign'
        rows[1]=(name,bridge.handoff.canonical(event))
        with self.assertRaisesRegex(ValueError,'source'):self.run_bridge(event_files=tuple(rows))
        rows=list(self.events);name,raw=rows[1];rows[1]=(name,raw[:-1]+b',"source":"packet"}')
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_bridge(event_files=tuple(rows))

    def test_exact_binary_ax_values_never_rounded_to_ideal_point(self):
        rectangle=bridge.exact_rect([0.1,0.2,2,2])
        self.assertEqual(rectangle.left,Fraction.from_float(0.1))
        self.assertNotEqual(rectangle.left,Fraction(1,10))

    def test_single_retained_roi_component_mode_is_strict(self):
        raw=bytes((128,128,128,255))*100
        changed=bytearray(raw);changed[44*4:44*4+4]=bridge.magenta_components.MAGENTA
        result=bridge.magenta_components.locate_one(bytes(changed),10,10,40)
        self.assertEqual(result['components'][0]['bounds'],[4,4,5,5])
        changed[88*4:88*4+4]=bridge.magenta_components.MAGENTA
        with self.assertRaises(ValueError):bridge.magenta_components.locate_one(bytes(changed),10,10,40)
        with self.assertRaises(ValueError):bridge.magenta_components.locate(bytes(changed),10,10,40)

    def stream_frame(self, baseline):
        plan=json.loads(baseline.plan_bytes);by_name={crop.name:crop for crop in baseline.crops}
        packed=b'';regions=[]
        for r in plan['regions']:
            crop=by_name[r['role']]
            regions.append(dict(role=r['role'],rectangle=[r['x'],r['y'],r['width'],r['height']],
                                offset=len(packed),bytes=len(crop.bgra),stride=r['width']*4,sha256=crop.sha256))
            packed+=crop.bgra
        row=dict(index=2,callbackBeforeMach=200,callbackAfterMach=210,status=0,statusName='complete',
                 ptsValue=1,ptsTimescale=60,ptsFlags=1,newFrame=True,session=e.SESSION,
                 geometrySHA256=plan['geometrySHA256'],displayTimeMach=100,
                 width=e.WIDTH,height=e.HEIGHT,bytesPerRow=self.stride,
                 contentRect=[3.25,4.5,560,1240],contentScale=1.25,scaleFactor=2,
                 packedPixels='frame-00002.rois.bgra',packedPixelSHA256=sha256(packed).hexdigest(),
                 copiedBytes=len(packed),regions=regions)
        return row,packed

    def test_two_phase_native_metadata_join_is_one_shot_and_immutable(self):
        baseline=self.run_bridge()
        self.assertIs(type(baseline.frozen),bridge.g.FrozenRasterGeometry)
        for field in ('content_rect','content_scale','scale_factor'):
            self.assertFalse(hasattr(baseline.frozen.identity,field))
        with self.assertRaises(ValueError):bridge.g.GeometryValidator(baseline.frozen)
        row,packed=self.stream_frame(baseline);manifest=bridge.handoff.canonical(row)
        join=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256)
        final=join.promote(manifest,packed,expected_manifest_sha256=sha256(manifest).hexdigest(),timebase=(1,1))
        proof=json.loads(final.proof_bytes)
        self.assertEqual(final.frozen.identity.content_rect,bridge.exact_rect(row['contentRect']))
        self.assertEqual(final.frozen.identity.content_scale,Fraction(5,4))
        self.assertEqual(final.frozen.identity.scale_factor,2)
        for field in ('rois','x_region','y_region','anchors','baseline_sha256'):
            self.assertEqual(getattr(final.frozen,field),getattr(baseline.frozen,field))
        self.assertEqual(proof['provisionalBaselineProofSHA256'],baseline.proof_sha256)
        self.assertEqual(proof['firstCompleteManifestSHA256'],sha256(manifest).hexdigest())
        self.assertEqual(proof['firstCompletePackedSHA256'],sha256(packed).hexdigest())
        self.assertEqual(final.validator.last_index,2)
        self.assertFalse(proof['admissionEligible']);self.assertFalse(proof['allDeliveredRecordsEstablished'])
        self.assertTrue(proof['finalReplayStartsAtFirstComplete'])
        with self.assertRaises(ValueError):join.promote(manifest,packed,expected_manifest_sha256=sha256(manifest).hexdigest(),timebase=(1,1))
        with self.assertRaises(AttributeError):join.state='pending'
        with self.assertRaises(AttributeError):final.frozen.identity=baseline.frozen.identity

    def test_missing_or_changed_first_stream_metadata_latches_failure(self):
        baseline=self.run_bridge();row,packed=self.stream_frame(baseline)
        for key in ('contentRect','contentScale','scaleFactor'):
            changed=deepcopy(row);del changed[key];manifest=bridge.handoff.canonical(changed)
            join=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256)
            with self.assertRaises(ValueError):join.promote(manifest,packed,expected_manifest_sha256=sha256(manifest).hexdigest(),timebase=(1,1))
            self.assertEqual(join.state,'failed')
            correct=bridge.handoff.canonical(row)
            with self.assertRaises(ValueError):join.promote(correct,packed,expected_manifest_sha256=sha256(correct).hexdigest(),timebase=(1,1))
        join=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256)
        manifest=bridge.handoff.canonical(row)
        with self.assertRaises(ValueError):join.promote(manifest,packed,expected_manifest_sha256='0'*64,timebase=(1,1))

    def test_changed_actual_first_feature_support_rejects_after_valid_hashes(self):
        baseline=self.run_bridge();row,packed=self.stream_frame(baseline)
        changed=bytearray(packed);region=row['regions'][2]
        # Remove the first full opaque magenta column from one actual ROI.
        start=region['offset'];w=region['rectangle'][2];h=region['rectangle'][3]
        data=bytes(changed[start:start+region['bytes']])
        component=bridge.magenta_components.locate_one(data,w,h,w*4)['components'][0]
        left=component['bounds'][0]
        for x,y in component['pixels']:
            if x==left:
                at=start+(y*w+x)*4;changed[at:at+4]=bytes((128,128,128,255))
        packed=bytes(changed);region['sha256']=sha256(packed[start:start+region['bytes']]).hexdigest()
        row['packedPixelSHA256']=sha256(packed).hexdigest();manifest=bridge.handoff.canonical(row)
        join=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256)
        with self.assertRaisesRegex(ValueError,'footprint moved'):
            join.promote(manifest,packed,expected_manifest_sha256=sha256(manifest).hexdigest(),timebase=(1,1))
        self.assertEqual(join.state,'failed')

    def test_all_complete_rows_redecode_real_retained_crops_and_latch_failure(self):
        baseline=self.run_bridge();row,packed=self.stream_frame(baseline)
        manifest=bridge.handoff.canonical(row)
        final=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=baseline.proof_sha256).promote(
            manifest,packed,expected_manifest_sha256=sha256(manifest).hexdigest(),timebase=(1,1))
        plan=json.loads(baseline.plan_bytes)
        verified=bridge.packed_frames.inspect_first(row,plan,timebase=(1,1),load=lambda _:packed)
        replay=bridge.g.GeometryValidator(final.frozen)
        first=bridge.validate_complete_frame(final,verified,validator=replay)
        self.assertEqual(first['nativeIndex'],2);self.assertEqual(first['actualMarker'],456)
        self.assertFalse(first['fullFrameReconstructed']);self.assertFalse(first['admissionEligible'])
        # Render a later actual source strip with marker457 through the same
        # explicit area-coverage model, then retain its real six crop bytes.
        data=bytearray(self.raw);marker=457
        bits=[False,True,False,True]+[bool(marker>>i&1) for i in range(16)]+[True,False,True,False]
        colors=[[(255,255,255) if bit else (0,0,0) for bit in bits]]
        e.paint_grid(data,self.stride,e.F(28,5)+e.F(7,5)*105,e.F(231,5)+e.F(7,5)*730,
                     e.F(7,5)*8,e.F(7,5)*16,colors)
        rectangles={r['role']:(r['x'],r['y'],r['width'],r['height']) for r in plan['regions']}
        crop_bytes,_=bridge.roi_bytes.extract(bytes(data),e.WIDTH,e.HEIGHT,self.stride,rectangles,session=e.SESSION,record=2)
        later_packed=b''.join(crop_bytes[role] for role in bridge.roi_bytes.ROLES)
        later_row=deepcopy(row);later_row.update(index=3,displayTimeMach=110,callbackBeforeMach=220,callbackAfterMach=230,
                                                ptsValue=2,packedPixels='frame-00003.rois.bgra',packedPixelSHA256=sha256(later_packed).hexdigest())
        for region in later_row['regions']:region['sha256']=sha256(crop_bytes[region['role']]).hexdigest()
        later=bridge.packed_frames.inspect_first(later_row,plan,timebase=(1,1),load=lambda _:later_packed)
        next_proof=bridge.validate_complete_frame(final,later,validator=replay)
        self.assertEqual(next_proof['nativeIndex'],3);self.assertEqual(next_proof['actualMarker'],457)
        self.assertNotEqual(next_proof['packedPixelSHA256'],first['packedPixelSHA256'])
        skipped=bridge.g.GeometryValidator(final.frozen)
        with self.assertRaisesRegex(ValueError,'restart'):
            bridge.validate_complete_frame(final,later,validator=skipped)
        self.assertTrue(skipped.failed)
        mutated=deepcopy(later);mutated['index']=4
        mutated['crops']['marker']=b'x'+mutated['crops']['marker'][1:]
        with self.assertRaisesRegex(ValueError,'packed crop bytes mutated'):
            bridge.validate_complete_frame(final,mutated,validator=replay)
        self.assertTrue(replay.failed)
        with self.assertRaises(ValueError):bridge.validate_complete_frame(final,later,validator=replay)


if __name__=='__main__':unittest.main()
