import unittest
from fractions import Fraction
from case_budget import construct

class Tests(unittest.TestCase):
    def sample(self):return dict(hostBeforeNs=1000,hostAfterNs=1001,machTicks=100000,timebaseNumer=125,timebaseDenom=3)
    def test_original_shared_reserve(self):
        r=construct(self.sample(),360_000_000_000)
        self.assertEqual(r['observationDeadlineMach'],99999+280_000_000_000*3//125)
        self.assertEqual(r['cleanupDeadlineMach'],99999+350_000_000_000*3//125)
    def test_scope_intersection(self):
        r=construct(self.sample(),200_000_000_000)
        self.assertEqual(r['effectiveCommandBudgetNs'],200_000_000_000)
        self.assertEqual(r['observationDeadlineMach'],99999+120_000_000_000*3//125)
    def test_expired_short_reversed_and_overflow(self):
        for budget in (0,80_000_000_000,True):
            with self.assertRaises(ValueError):construct(self.sample(),budget)
        for changes in ({'hostAfterNs':999},{'machTicks':1},{'machTicks':2**64-1},{'timebaseDenom':0}):
            sample=self.sample();sample.update(changes)
            with self.assertRaises(ValueError):construct(sample,360_000_000_000)
    def test_fractional_anchor_never_late(self):
        for width in (1,41,42,125,126):
            s=self.sample();s['hostAfterNs']=s['hostBeforeNs']+width
            r=construct(s,360_000_000_000)
            true=Fraction(s['machTicks'])-Fraction(width*3,125)+Fraction(280_000_000_000*3,125)
            self.assertLessEqual(r['observationDeadlineMach'],true)

if __name__=='__main__':unittest.main()
