from dataclasses import FrozenInstanceError, replace
import unittest
import direct_geometry as g
from test_direct_geometry import fixture, crop


class RasterPromotionTests(unittest.TestCase):
    def setUp(self):
        values=fixture();self.final_identity=values[0]
        i=values[0];values[0]=g.RasterIdentity(i.session,i.owner_pid,i.window_id,i.width,i.height,i.app_viewport)
        self.provisional=g.freeze_raster(*values)
        self.crops=tuple(crop(name,rect) for name,rect in self.provisional.rois)

    def test_no_content_placeholders_and_validator_rejects_provisional(self):
        for field in ('content_rect','content_scale','scale_factor'):
            self.assertFalse(hasattr(self.provisional.identity,field))
        with self.assertRaises(g.InvalidEvidence):g.GeometryValidator(self.provisional)
        with self.assertRaises(g.InvalidEvidence):g.freeze(self.provisional.identity,*fixture()[1:])

    def test_promotes_once_without_fit_or_roi_mutation(self):
        join=g.GeometryPromotion(self.provisional)
        final=join.promote(0,self.final_identity,self.provisional.anchors,self.crops)
        self.assertIs(type(final),g.FrozenGeometry)
        for field in ('anchors','fit_ids','validation_ids','regions','rois','x_region','y_region','derived_viewport','baseline_sha256'):
            self.assertEqual(getattr(final,field),getattr(self.provisional,field))
        self.assertEqual(final.identity,self.final_identity)
        with self.assertRaises(g.InvalidEvidence):join.promote(1,self.final_identity,self.provisional.anchors,self.crops)
        with self.assertRaises(FrozenInstanceError):final.identity=self.provisional.identity
        with self.assertRaises(FrozenInstanceError):self.provisional.rois=()

    def test_wrong_first_identity_latches_closed(self):
        join=g.GeometryPromotion(self.provisional)
        with self.assertRaisesRegex(g.InvalidEvidence,'identity mismatch'):
            join.promote(0,replace(self.final_identity,window_id=999),self.provisional.anchors,self.crops)
        self.assertEqual(join.state,'failed')
        with self.assertRaises(g.InvalidEvidence):join.promote(0,self.final_identity,self.provisional.anchors,self.crops)

    def test_first_crop_or_anchor_change_rejects(self):
        altered=list(self.crops);first=altered[0]
        altered[0]=g.Crop(first.name,first.rect,b'x'+first.bgra[1:],first.sha256)
        with self.assertRaises(g.InvalidEvidence):
            g.GeometryPromotion(self.provisional).promote(0,self.final_identity,self.provisional.anchors,tuple(altered))
        anchors=list(self.provisional.anchors);a=anchors[0]
        anchors[0]=replace(a,footprint=g.PixelRect(a.footprint.x,a.footprint.y,a.footprint.width+1,a.footprint.height))
        with self.assertRaises(g.InvalidEvidence):
            g.GeometryPromotion(self.provisional).promote(0,self.final_identity,tuple(anchors),self.crops)

if __name__=='__main__':unittest.main()
