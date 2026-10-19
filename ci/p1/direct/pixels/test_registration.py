import hashlib
import unittest
from unittest.mock import patch
from registration import locate_registration
from test_window_bgra import raster, SESSION, OTHER


def boards():
    return [(4,4,4,SESSION,1), (180,4,4,SESSION,2),
            (4,110,4,SESSION,3), (180,110,4,SESSION,4)]


class RegistrationTests(unittest.TestCase):
    def test_four_same_frame_boards_bind_order_and_hash(self):
        args=raster(boards(),padding=12)
        row=locate_registration(*args,SESSION)
        self.assertEqual([v['anchor'] for v in row['anchors']],[1,2,3,4])
        self.assertEqual(row['frame']['sha256'],hashlib.sha256(args[0]).hexdigest())
        self.assertFalse(row['admissionEligible'])

    def test_missing_or_extra_board_fails(self):
        for rows in (boards()[:-1],boards()+[(360,4,4,SESSION,5)]):
            with self.assertRaises(ValueError):locate_registration(*raster(rows),SESSION)

    def test_foreign_board_is_not_ignored(self):
        rows=boards();rows[3]=(180,110,4,OTHER,4)
        with self.assertRaisesRegex(ValueError,'foreign'):locate_registration(*raster(rows),SESSION)

    def test_duplicate_ordinal_fails(self):
        rows=boards();rows[3]=(180,110,4,SESSION,3)
        with self.assertRaisesRegex(ValueError,'duplicate'):locate_registration(*raster(rows),SESSION)

    def test_invalid_payload_is_not_ignored(self):
        data,w,h,stride=raster(boards())
        at=(110+8*4+1)*stride+(180+5*4+1)*4
        data[at:at+4]=b'\x80\x80\x80\xff'
        with self.assertRaises(ValueError):locate_registration(data,w,h,stride,SESSION)

    def test_small_cells_do_not_establish_correspondence(self):
        rows=[(x,y,3,s,m) for x,y,scale,s,m in boards()]
        with self.assertRaises(ValueError):locate_registration(*raster(rows),SESSION)

    def test_source_drift_rejected(self):
        with patch('registration.DECODER_SHA256','0'*64),self.assertRaisesRegex(ValueError,'source drift'):
            locate_registration(*raster(boards()),SESSION)

    def test_packet_source_drift_rejected(self):
        with patch('registration.PACKET_SHA256','0'*64),self.assertRaisesRegex(ValueError,'packet source drift'):
            locate_registration(*raster(boards()),SESSION)


if __name__=='__main__':unittest.main()
