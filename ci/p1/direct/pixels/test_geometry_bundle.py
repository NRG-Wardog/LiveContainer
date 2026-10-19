"""Synthetic byte/geometry integration, not anchor decoding or native evidence."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'geometry'))
import direct_geometry as g
from test_direct_geometry import fixture
from roi_bytes import extract

class BundleTests(unittest.TestCase):
    def test_real_crop_bytes_bind_to_frozen_geometry(self):
        values=fixture();frozen=g.freeze(*values)
        raw=values[-1].bgra
        aliases={'control':'control','marker':'marker',**{f'anchor-{i}':f'a{i}' for i in range(1,5)}}
        boxes=dict(frozen.rois)
        regions={role:(boxes[name].x,boxes[name].y,boxes[name].width,boxes[name].height) for role,name in aliases.items()}
        crops,report=extract(raw,frozen.identity.width,frozen.identity.height,frozen.identity.width*4,
                             regions,session=frozen.identity.session,record=1)
        metadata={row['role']:row for row in report['crops']}
        bundle=tuple(g.Crop(name,boxes[name],crops[role],metadata[role]['sha256']) for role,name in aliases.items())
        proof=g.GeometryValidator(frozen).validate(1,frozen.identity,frozen.anchors,bundle)
        self.assertTrue(proof['primitiveValid']);self.assertFalse(proof['admissionEligible'])
        bad=list(bundle);first=bad[0];bad[0]=g.Crop(first.name,first.rect,b'x'+first.bgra[1:],first.sha256)
        with self.assertRaises(g.InvalidEvidence):g.GeometryValidator(frozen).validate(1,frozen.identity,frozen.anchors,tuple(bad))

if __name__=='__main__':unittest.main()
