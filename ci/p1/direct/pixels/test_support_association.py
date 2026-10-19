"""Complete support association; synthetic pixels are never native acceptance."""
from copy import deepcopy
import unittest
import magenta_components as m


def raster(points,width=80,height=80):
    data=bytearray(bytes((128,128,128,255))*width*height)
    for x,y in points:data[(y*width+x)*4:(y*width+x)*4+4]=m.MAGENTA
    return bytes(data)


def fixture():
    points=[(x,y) for x in (3,4,5,73,74,75) for y in (3,6,73,76)]
    raw=raster(points);obs=m.locate_all(raw,80,80,320)
    boards=[dict(anchor=i,session='a'*32,observedDarkRingBounds=rect) for i,rect in enumerate(
        ([10,10,30,30],[50,10,70,30],[10,50,30,70],[50,50,70,70]),1)]
    return raw,obs,dict(frame=obs['frame'],anchors=boards)


class SupportTests(unittest.TestCase):
    def test_all_eight_components_and24pixels_retained_in_four_whole_hulls(self):
        raw,obs,packets=fixture();paired=m.pair_supports_to_packets(obs,packets)
        self.assertEqual(len(obs['components']),8)
        self.assertEqual([r['support']['bounds'] for r in paired],[[3,3,6,7],[73,3,76,7],[3,73,6,77],[73,73,76,77]])
        indices=[i for r in paired for i in r['support']['componentIndices']]
        self.assertEqual(sorted(indices),list(range(8)))
        self.assertEqual(sum(len(r['support']['pixels']) for r in paired),24)
        self.assertTrue(all(r['support']['missingPixelsFilled'] is False for r in paired))
        with self.assertRaises(ValueError):m.locate(raw,80,80,320)
    def test_second_eligible_board_rejects_without_nearest_choice(self):
        _,obs,packets=fixture();packets['anchors'][3]['observedDarkRingBounds']=[-20,-20,0,0]
        with self.assertRaisesRegex(ValueError,'ambiguous'):m.pair_supports_to_packets(obs,packets)
    def test_unmatched_fifth_group_or_interior_foreign_support_rejects(self):
        raw,_,packets=fixture()
        for x,y in ((40,40),(20,20)):
            changed=bytearray(raw);at=(y*80+x)*4;changed[at:at+4]=m.MAGENTA
            obs=m.locate_all(bytes(changed),80,80,320);p=deepcopy(packets);p['frame']=obs['frame']
            with self.assertRaisesRegex(ValueError,'unassigned'):m.pair_supports_to_packets(obs,p)
    def test_empty_group_and_oversized_combined_hull_reject(self):
        _,obs,packets=fixture();obs=deepcopy(obs)
        obs['components']=[c for c in obs['components'] if c['bounds'][0]<70]
        with self.assertRaisesRegex(ValueError,'missing'):m.pair_supports_to_packets(obs,packets)
        raw=raster([(2,2),(19,2)],40,40);obs=m.locate_all(raw,40,40,160)
        with self.assertRaisesRegex(ValueError,'16by16'):m.locate_packet_support(raw,40,40,160,1,[20,20,40,40])
    def test_roi_uses_every_component_and_exact_packet_adjacency(self):
        raw=raster([(3,3),(3,6)],40,40)
        obs=m.locate_packet_support(raw,40,40,160,1,[10,10,30,30])
        self.assertEqual(obs['support']['componentIndices'],[0,1])
        self.assertEqual(obs['support']['bounds'],[3,3,4,7])
        for ordinal in (2,3,4):
            with self.assertRaises(ValueError):m.locate_packet_support(raw,40,40,160,ordinal,[10,10,30,30])
        raw=raster([(3,3),(3,6),(20,20)],40,40)
        with self.assertRaisesRegex(ValueError,'foreign'):m.locate_packet_support(raw,40,40,160,1,[10,10,30,30])
    def test_exact_color_pixel_and_frame_caps_remain(self):
        raw=bytearray(raster([(3,3),(3,6)],40,40));raw[(4*40+3)*4:(4*40+3)*4+4]=bytes((255,1,255,255))
        obs=m.locate_all(bytes(raw),40,40,160)
        self.assertEqual(obs['qualifyingPixels'],2)
        with self.assertRaises(ValueError):m.locate_all(raster([(x,y) for x in range(20) for y in range(20)],40,40),40,40,160)

if __name__=='__main__':unittest.main()
