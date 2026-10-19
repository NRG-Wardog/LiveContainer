import unittest
from fractions import Fraction
import live_strip as s


def raster(marker):
    bits=[False,True,False,True]+[bool(marker>>i&1) for i in range(16)]+[True,False,True,False]
    row=b''.join(bytes([255 if bit else 0]*3+[255])*8 for bit in bits)
    return row*16

class StripTests(unittest.TestCase):
    def cells(self):return s.cell_interiors((0,0,192,16),((1,0),),((1,0),),(0,0,192,16))
    def test_actual_pixel_marker(self):
        for marker in (1,456,17999):self.assertEqual(s.decode(raster(marker),192,16,self.cells())['marker'],marker)
    def test_unknown_and_nonuniform_pixels_fail(self):
        for color in (b'\x80\x80\x80\xff',b'\xff\xff\xff\x00',b'\xff'*4):
            data=bytearray(raster(1));x,y,_,_=self.cells()[0];at=(y*192+x)*4;data[at:at+4]=color
            with self.assertRaises(ValueError):s.decode(bytes(data),192,16,self.cells())
    def test_uncertainty_cannot_be_collapsed_to_midpoint(self):
        with self.assertRaisesRegex(ValueError,'unresolved'):
            s.cell_interiors((0,0,192,16),((1,0),(1,10)),((1,0),),(0,0,192,16))
    def test_fractional_bounds_use_whole_pixel_support(self):
        rows=s.cell_interiors((0,0,192,16),((1,Fraction(1,10)),),((1,0),),(0,0,193,16))
        self.assertEqual(rows[0],(1,0,8,16))
    def test_invalid_marker_or_truncation_rejects(self):
        for marker in (0,18000):
            with self.assertRaises(ValueError):s.decode(raster(marker),192,16,self.cells())
        with self.assertRaises(ValueError):s.decode(raster(1)[:-1],192,16,self.cells())
    def test_strip_bytes_respect_revised_combined_frame_ceiling(self):
        row=raster(1)[:192*4]+bytes((1024-192)*4)
        self.assertEqual(s.decode(row*256,1024,256,self.cells())['marker'],1)
        with self.assertRaisesRegex(ValueError,'retained immutable strip bytes'):
            s.decode(row*257,1024,257,self.cells())

if __name__=='__main__':unittest.main()
