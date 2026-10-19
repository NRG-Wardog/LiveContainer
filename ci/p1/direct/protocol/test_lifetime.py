import unittest
from lifetime import lifetime, overlap, reset_between

class LifetimeTests(unittest.TestCase):
    def rows(self):
        return [dict(appNs=(n,n+10),label=label) for n,label in [(1_100_000_000,'Copied'),(2_600_000_000,'Copied'),(3_100_000_000,'Copy Details')]]
    def test_original_lifetime_predicates(self):
        self.assertEqual(lifetime(self.rows(),(1_000_000_000,1_000_000_010))['witness'],1)
    def test_receipt_uncertainty_not_midpoint(self):
        with self.assertRaises(ValueError):lifetime(self.rows(),(1_000_000_000,1_100_000_001))
    def test_expected_absence_cannot_witness_or_bridge(self):
        rows=self.rows();rows.insert(1,dict(appNs=(2_000_000_000,2_000_000_010),label='expected-dismissal-absence'))
        with self.assertRaises(ValueError):lifetime(rows,(1_000_000_000,1_000_000_010))
        self.assertFalse(reset_between([dict(appNs=(2,3),label='expected-dismissal-absence')],(0,1),(4,5)))
    def test_old_deadline_and_expiry_are_conservative(self):
        with self.assertRaises(ValueError):lifetime(self.rows(),(1_000_000_000,1_000_000_010),old_event=(500_000_000,500_000_010))
        rows=self.rows();rows[-1]['appNs']=(5_999_999_990,6_000_000_000)
        with self.assertRaises(ValueError):lifetime(rows,(1_000_000_000,1_000_000_010))
    def test_unknown_pixels_not_silently_discarded(self):
        rows=self.rows();rows.insert(0,dict(appNs=(1,2),label="unknown"))
        with self.assertRaises(ValueError):lifetime(rows,(1_000_000_000,1_000_000_010))
    def test_actual_overlap_and_third_spacing(self):
        self.assertEqual(overlap((0,10),(800_000_000,800_000_010),(6_000_000_000,6_000_000_010)),(799_999_990,800_000_010))
        with self.assertRaises(ValueError):overlap((0,10),(750_000_000,2_000_000_000),(8_000_000_000,8_000_000_010))
        with self.assertRaises(ValueError):overlap((0,10),(800_000_000,800_000_010),(5_800_000_000,5_800_000_010))

if __name__=='__main__':unittest.main()
