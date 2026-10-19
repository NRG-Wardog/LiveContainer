"""Regression from run39262135354: real AX bounds, synthetic placement math.

The screenshot is a3x XCTest app attachment, not SCStream metadata. Only the
three queried anchors/controls are actual AX evidence; feature/fourth positions
below are explicit source-model predictions. No native rerun or admission.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
LOCAL=HERE.parent
FIXTURE=json.loads((HERE/'native-layout-39262135354.json').read_text())
INSERT='''    // Fixed observer-only lift: native run 39262135354 exposed marker overlap.
    // Move each bottom packet and its feature together; never move production UI.
    private static let bottomRegistrationLift: CGFloat = 96
'''
OLD_OVERLAY_SHA='ff37193436047741d1de3ba11631303923918a13745cf0f0a9fd15df342a3daf'


def overlap(a,b):
    return max(a[0],b[0])<min(a[0]+a[2],b[0]+b[2]) and max(a[1],b[1])<min(a[1]+a[3],b[1]+b[3])


def envelope(a,b):
    x=min(a[0],b[0]);y=min(a[1],b[1])
    return [x,y,max(a[0]+a[2],b[0]+b[2])-x,max(a[1]+a[3],b[1]+b[3])-y]


def modeled(lift):
    x,y=FIXTURE['sourceModel']['geometryOrigin'];w,h=FIXTURE['sourceModel']['geometrySize']
    boards=[[x+8,y+8,114,66],[x+w-122,y+8,114,66],
            [x+8,y+h-74-lift,114,66],[x+w-122,y+h-74-lift,114,66]]
    features=[[x+3,y+3,3,3],[x+w-6,y+3,3,3],
              [x+3,y+h-6-lift,3,3],[x+w-6,y+h-6-lift,3,3]]
    return boards,features


class NativeLayoutTests(unittest.TestCase):
    def test_retained_ax_and_screenshot_scale_are_not_conflated(self):
        self.assertEqual(FIXTURE['actualAX']['windowFrame'],[0,0,402,874])
        self.assertEqual(FIXTURE['actualAX']['copyFrame'],[16,312.33333333333337,370,73.999999999999943])
        self.assertEqual(FIXTURE['actualAX']['markerFrame'],[105,771.33333333333337,192,16])
        self.assertEqual(FIXTURE['screenshot']['pixels'],[1206,2622])
        self.assertEqual(FIXTURE['screenshot']['attachmentScale'],3)
        self.assertFalse(FIXTURE['screenshot']['screenCaptureKitScaleEstablished'])
        self.assertFalse(FIXTURE['sourceModel']['anchor4AXMeasured'])
        self.assertFalse(FIXTURE['sourceModel']['featureAXMeasured'])
        self.assertFalse(FIXTURE['admissionEligible'])
        self.assertEqual(modeled(0)[0][:3],FIXTURE['actualAX']['queriedAnchors'])

    def test_reproduces_native_marker_overlap_and_rejects_board_only_fix(self):
        boards,features=modeled(0);marker=FIXTURE['actualAX']['markerFrame']
        self.assertTrue(overlap(boards[2],marker))
        self.assertEqual(min(boards[2][0]+114,marker[0]+192)-max(boards[2][0],marker[0]),17)
        self.assertEqual(min(boards[2][1]+66,marker[1]+16)-max(boards[2][1],marker[1]),16)
        #64pt clears the board alone, but its actual retained feature envelope
        #still reaches y772 and intersects the unchanged marker at771.333pt.
        boards,features=modeled(64)
        self.assertFalse(overlap(boards[2],marker))
        self.assertTrue(overlap(envelope(boards[2],features[2]),marker))
        boards,features=modeled(0);boards[2][1]-=96
        self.assertTrue(overlap(envelope(boards[2],features[2]),marker))

    def test_fixed96pt_pair_lift_preserves_whole_regions_and_adjacency(self):
        boards,features=modeled(96);ax=FIXTURE['actualAX'];window=ax['windowFrame']
        protected=[ax[k] for k in ('copyFrame','markerFrame','baselineFrame')]
        groups=[envelope(a,b) for a,b in zip(boards,features)]
        for index,(board,feature,group) in enumerate(zip(boards,features,groups)):
            self.assertTrue(all(not overlap(group,other) for other in protected+groups[:index]))
            self.assertTrue(window[0]<=group[0] and window[1]<=group[1] and
                            group[0]+group[2]<=window[2] and group[1]+group[3]<=window[3])
            self.assertTrue(feature[0]+3<board[0] if index%2==0 else feature[0]>board[0]+114)
            self.assertTrue(feature[1]+3<board[1] if index<2 else feature[1]>board[1]+66)
        self.assertEqual(boards[2],[8,670,114,66]);self.assertEqual(features[2],[3,738,3,3])
        self.assertAlmostEqual(ax['markerFrame'][1]-(groups[2][1]+groups[2][3]),30.33333333333337)

    def test_integer_origin_and_failure_geometry_are_explicit(self):
        _,features=modeled(96)
        for frame in features:
            self.assertTrue(all(float(value).is_integer() for value in frame))
        observer=(LOCAL/'handoff/observer.swift').read_text()
        self.assertIn('frame.width == 3 && frame.height == 3 && windowFrame.contains(frame)',observer)
        self.assertIn('sampledFrame=\\(values); sampledWindow=\\(window)',observer)

    def test_only_declared_overlay_placement_source_delta(self):
        source=(HERE/'registration.swift').read_text()
        self.assertEqual(source.count(INSERT),1)
        self.assertEqual(source.count('geometry.size.height >= 148 + Self.bottomRegistrationLift'),1)
        for value in (41,4.5):self.assertEqual(source.count(f'geometry.size.height-{value}-Self.bottomRegistrationLift'),1)
        original=source.replace(INSERT,'').replace('geometry.size.height >= 148 + Self.bottomRegistrationLift','geometry.size.height >= 148')
        for value in (41,4.5):original=original.replace(f'geometry.size.height-{value}-Self.bottomRegistrationLift',f'geometry.size.height-{value}')
        original=original.replace('? 4.5 : geometry.size.width-4.5','? 5 : geometry.size.width-5').replace('? 4.5 : geometry.size.height-4.5','? 5 : geometry.size.height-5')
        original=original.replace('bounds.width == 3, bounds.height == 3','bounds.width == 2, bounds.height == 2').replace('.frame(width:3,height:3)','.frame(width:2,height:2)')
        self.assertEqual(sha256(original.encode()).hexdigest(),OLD_OVERLAY_SHA)
        observer=(LOCAL/'handoff/observer.swift').read_text()
        self.assertIn('[copyFrame, markerFrame, baselineFrame] + anchorFrames',observer)
        self.assertIn('$0.intersects(frame)',observer)

    def test_actual_sized_control_fits_one_mib_successor_at_representative_scale(self):
        # Synthetic upright1.4x area-coverage model only. The actual SCS scale
        #is not established by the3x XCTest screenshot. No native admission.
        sys.path[:0]=[str(LOCAL/'pixels'),str(LOCAL.parent/'window-capture-candidate/ci/p1/preflight')]
        import test_registration_bridge as t
        b=t.bridge;e=t.e;boards,features=modeled(96);row=t.request();geometry=row['geometry']
        for key in ('windowFrame','copyFrame','markerFrame','baselineFrame'):geometry[key]=deepcopy(FIXTURE['actualAX'][key])
        for item,rect in zip(geometry['anchors'],boards):item['frame']=rect
        for item,rect in zip(geometry['features'],features):item['frame']=rect
        with patch.multiple(e,AX_RECTS=tuple(map(tuple,boards)),MARKER=b.exact_rect(geometry['markerFrame'])):
            raw,stride=e.render(tiny_features=True,strip=True,feature_rects=features)
        observed={};original=b.roi_bytes.extract
        def inspect(*args,**kwargs):
            observed['plan']=deepcopy(args[4]);return original(*args,**kwargs)
        with patch.object(b.roi_bytes,'extract',side_effect=inspect):
            result=b.freeze_registration(b.handoff.canonical(row),raw,e.WIDTH,e.HEIGHT,stride,
                identity=b.g.RasterIdentity(e.SESSION,101,99,e.WIDTH,e.HEIGHT,e.APP),
                expected_frame_sha256=sha256(raw).hexdigest(),event_files=t.event_files(),expected_source_hashes=b.source_hashes())
        proof=json.loads(result.proof_bytes)
        self.assertFalse(proof['admissionEligible'])
        self.assertEqual(proof['liveMarker']['marker'],456)
        self.assertEqual(proof['independentHoldout'],['anchor-4'])
        regions=list(observed['plan'].values())
        for i,region in enumerate(regions):self.assertTrue(all(not overlap(region,other) for other in regions[:i]))
        self.assertGreater(sum(w*h*4 for _,_,w,h in regions),512*1024)
        self.assertLessEqual(sum(w*h*4 for _,_,w,h in regions),1024*1024)

    def test_actual_ax_at_larger_source_scales_and_one_mib_rejection(self):
        # Exact area-coverage renderer only; these are source scales, never an
        # assumed Simulator outer-window size or native filtering guarantee.
        from fractions import Fraction as F
        import math
        sys.path[:0]=[str(LOCAL/'pixels'),str(LOCAL.parent/'window-capture-candidate/ci/p1/preflight')]
        import test_registration_bridge as t
        b=t.bridge;e=t.e;boards,features=modeled(96)
        row=t.request();geometry=row['geometry']
        for key in ('windowFrame','copyFrame','markerFrame','baselineFrame'):geometry[key]=deepcopy(FIXTURE['actualAX'][key])
        for item,rect in zip(geometry['anchors'],boards):item['frame']=rect
        for item,rect in zip(geometry['features'],features):item['frame']=rect
        for scale in (F(3,2),F(8,5),F(9,5),F(41,20)):
            with self.subTest(scale=str(scale)):
                width=math.ceil(402*scale)+64;height=math.ceil(874*scale)+128
                self.assertLessEqual(height,2048)
                with patch.multiple(e,WIDTH=width,HEIGHT=height,AX_RECTS=tuple(map(tuple,boards)),MARKER=b.exact_rect(geometry['markerFrame'])):
                    raw,stride=e.render(scale=scale,tx=F(32),ty=F(96),tiny_features=True,strip=True,feature_rects=features)
                def freeze():
                    return b.freeze_registration(b.handoff.canonical(row),raw,width,height,stride,
                        identity=b.g.RasterIdentity(e.SESSION,101,99,width,height,e.APP),
                        expected_frame_sha256=sha256(raw).hexdigest(),event_files=t.event_files(),expected_source_hashes=b.source_hashes())
                if scale==F(41,20):
                    with self.assertRaisesRegex(ValueError,'ROI byte ceiling exceeded'):freeze()
                    continue
                result=freeze();proof=json.loads(result.proof_bytes)
                self.assertLessEqual(proof['sameSampleROIs']['copiedBytes'],1024*1024)
                self.assertGreater(proof['sameSampleROIs']['copiedBytes'],512*1024)
                self.assertEqual(proof['liveMarker']['marker'],456)
                self.assertEqual(proof['independentHoldout'],['anchor-4'])
                self.assertFalse(proof['admissionEligible'])
                for axis,translation in (('x',F(32)),('y',F(96))):
                    for app,pixel in b.g._observations(result.frozen.anchors,axis):
                        self.assertLessEqual(pixel.lo-scale*app.hi,translation)
                        self.assertLessEqual(translation,pixel.hi-scale*app.lo)
                crop=dict(result.frozen.rois)['marker'];marker=tuple(F(v) for v in geometry['markerFrame'])
                cells=b.live_strip.cell_interiors(marker,result.frozen.x_region,result.frozen.y_region,(crop.x,crop.y,crop.width,crop.height))
                for index,(x0,y0,x1,y1) in enumerate(cells):
                    left,top,mw,mh=marker
                    self.assertLessEqual(F(32)+scale*(left+mw*F(index,24)),crop.x+x0)
                    self.assertLessEqual(crop.x+x1,F(32)+scale*(left+mw*F(index+1,24)))
                    self.assertLessEqual(F(96)+scale*top,crop.y+y0)
                    self.assertLessEqual(crop.y+y1,F(96)+scale*(top+mh))

if __name__=='__main__':unittest.main()
