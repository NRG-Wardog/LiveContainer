import unittest
from fractions import Fraction as F
import direct_clock as c

class ClockTests(unittest.TestCase):
    def row(self, n=1):
        return dict(hostBeforeNs=n*1000+10,hostAfterNs=n*1000+20,
                    machTicks=n*24,timebaseNumer=125,timebaseDenom=3)
    def rows(self):
        return [dict(self.row(i+1),phase=p,ordinal=j+1)
                for i,(p,j) in enumerate((p,j) for p in c.PHASES for j in range(8))]
    def test_exact_native_conversion(self):
        self.assertEqual(c.mach_bracket(self.row()),(10,20))
        row=self.row();row['machTicks']=1
        self.assertEqual(c.mach_bracket(row),(F(2905,3),F(2935,3)))
    def test_inventory_and_common_intersection(self):
        phases, common=c.phase_bridge(self.rows())
        self.assertEqual(common,(10,20));self.assertEqual(set(phases),set(c.PHASES))
        for alter in ('missing','duplicate','reorder','timebase'):
            rows=self.rows()
            if alter=='missing':rows.pop()
            elif alter=='duplicate':rows[1]['ordinal']=1
            elif alter=='reorder':rows[0],rows[1]=rows[1],rows[0]
            else:rows[-1]['timebaseNumer']=126
            with self.assertRaises(ValueError):c.phase_bridge(rows)
    def test_invalid_native_values(self):
        for key,value in [('machTicks',True),('machTicks',-1),('machTicks',1.5),
                          ('machTicks',2**64),('timebaseDenom',0),('timebaseNumer',2**32)]:
            row=self.row();row[key]=value
            with self.assertRaises(ValueError):c.mach_bracket(row)
    def test_round_outward_both_signs(self):
        self.assertEqual(c.outward_ns((F(-4,3),F(4,3))),(-2,2))
        self.assertEqual(c.outward_ns((F(-5,3),F(-4,3))),(-2,-1))
    def test_combined_stronger_limit(self):
        app={p:(0,20_000_000) for p in c.PHASES}
        host={p:(0,100_000_000) for p in c.PHASES}
        self.assertEqual(c.combine(app,host)[1],(0,120_000_000))
        host['mid']=(0,100_000_001)
        with self.assertRaises(ValueError):c.combine(app,host)
        host={p:(0,120_000_000) for p in c.PHASES}
        with self.assertRaises(ValueError):c.combine(app,host)
    def test_disjoint_phase_and_domain_rejected(self):
        app={p:(0,1) for p in c.PHASES};host={p:(0,1) for p in c.PHASES}
        app['post']=(3,4);host['post']=(-3,-2)
        with self.assertRaises(ValueError):c.combine(app,host)
    def test_positive_and_negative_offset_mapping(self):
        self.assertEqual(c.app_time_ns(24,125,3,(-20,-10)),(980,990))
    def test_causal_sampling_keeps_native_read_inside_bracket(self):
        order=[]
        host=iter([1000,1010])
        def monotonic():
            order.append('host');return next(host)
        def native():
            order.append('native');return 24,125,3
        row=c.sample('pre',1,native,monotonic)
        self.assertEqual(order,['host','native','host'])
        self.assertEqual(c.mach_bracket(row),(0,10))
    def test_phase_drift_and_host_reversal_fail(self):
        rows=self.rows();rows[-1]["hostBeforeNs"]+=100;rows[-1]["hostAfterNs"]+=100
        with self.assertRaises(ValueError):c.phase_bridge(rows)
        rows=self.rows();rows[1]["hostBeforeNs"]=rows[0]["hostBeforeNs"]
        with self.assertRaises(ValueError):c.phase_bridge(rows)
    def test_app_phase_limit(self):
        app={p:(0,20_000_001) for p in c.PHASES};host={p:(0,0) for p in c.PHASES}
        with self.assertRaises(ValueError):c.combine(app,host)
    def test_fractional_serialization_cannot_hide_excess_width(self):
        app={p:(0,0) for p in c.PHASES};host={p:(F(1,3),120_000_000+F(1,3)) for p in c.PHASES}
        with self.assertRaises(ValueError):c.combine(app,host)
        host={p:(F(1,3),119_999_999+F(1,3)) for p in c.PHASES}
        self.assertEqual(c.outward_ns(c.combine(app,host)[1]),(0,120_000_000))
    def test_final_mapped_fractional_boundary(self):
        with self.assertRaises(ValueError):c.app_time_ns(1,125,3,(0,120_000_000))
        self.assertEqual(c.outward_ns(c.app_time_ns(1,125,3,(0,119_999_999))),(41,120_000_041))
    def test_no_float_rounding(self):
        with self.assertRaises(ValueError):c.interval(0.0,1)
        with self.assertRaises(ValueError):c.intersection([])
        with self.assertRaises(ValueError):c.interval(2,1)

if __name__=='__main__':unittest.main()
