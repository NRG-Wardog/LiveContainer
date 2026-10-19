import unittest
import direct_coverage as c

class CoverageTests(unittest.TestCase):
    def rows(self):
        return [dict(ordinal=i+1,status='complete',displayTicks=(i+1)*100_000_000,
                     timebaseNumer=1,timebaseDenom=1) for i in range(5)]
    def test_full_uncertain_boundary_coverage(self):
        value=c.coverage(self.rows(),(-1_000_000,1_000_000),(150_000_000,160_000_000),(440_000_000,450_000_000))
        self.assertEqual((value['firstRecord'],value['lastRecord']),(1,5))
        self.assertFalse(value['admissionEligible'])
    def test_late_callback_or_persistence_cannot_move_observation_or_fill_stale_gap(self):
        rows=self.rows();bounds=((0,0),(150_000_000,160_000_000),(440_000_000,450_000_000))
        expected=c.coverage(rows,*bounds)
        for row in rows:
            row.update(callbackBeforeMach=9_000_000_000,callbackAfterMach=9_200_000_000,
                       persistenceFinishedMach=10_000_000_000,historical5msExceeded=True)
        self.assertEqual(c.coverage(rows,*bounds),expected)
        rows[2]['displayTicks']=rows[1]['displayTicks']
        with self.assertRaisesRegex(ValueError,'nonmonotonic'):
            c.coverage(rows,*bounds)
        rows=self.rows();rows[2]['displayTicks']+=21_000_000
        rows[2]['callbackAfterMach']=301_000_000
        with self.assertRaisesRegex(ValueError,'gap exceeds 120 ms'):
            c.coverage(rows,*bounds)

    def test_idle_cannot_repair_gap(self):
        rows=self.rows();rows[2]['status']='idle'
        with self.assertRaises(ValueError):c.coverage(rows,(0,0),(150_000_000,160_000_000),(440_000_000,450_000_000))
    def test_boundary_not_point_midpoint(self):
        with self.assertRaises(ValueError):c.coverage(self.rows(),(-10_000_000,10_000_000),(95_000_000,105_000_000),(440_000_000,450_000_000))
    def test_unknown_bad_outside_window_still_rejected(self):
        rows=self.rows();rows[0]['status']='unknown'
        with self.assertRaises(ValueError):c.coverage(rows,(0,0),(250_000_000,260_000_000),(340_000_000,350_000_000))
    def test_duplicate_timestamp_and_inventory_rejected(self):
        for key,value in [('displayTicks',100_000_000),('ordinal',1)]:
            rows=self.rows();rows[1][key]=value
            with self.assertRaises(ValueError):c.coverage(rows,(0,0),(150_000_000,160_000_000),(440_000_000,450_000_000))
    def test_gap_exact_limit_and_one_ns_over(self):
        rows=self.rows()
        for i,row in enumerate(rows):row["displayTicks"]=(i+1)*120_000_000
        c.coverage(rows,(0,0),(150_000_000,160_000_000),(550_000_000,560_000_000))
        rows[2]["displayTicks"]+=1
        with self.assertRaises(ValueError):c.coverage(rows,(0,0),(150_000_000,160_000_000),(550_000_000,560_000_000))
    def test_no_assumed_persistence_past_last_sample(self):
        with self.assertRaises(ValueError):c.coverage(self.rows(),(0,0),(150_000_000,160_000_000),(500_000_001,510_000_000))

if __name__=='__main__':unittest.main()
