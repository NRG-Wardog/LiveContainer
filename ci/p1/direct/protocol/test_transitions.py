import unittest
from copy import deepcopy
from transitions import validate, uptime_interval_ns

class TransitionTests(unittest.TestCase):
    def fixture(self,scenario):
        rows=[]
        for i in range(1,4 if scenario!='timeout' else 2):
            generation=int(scenario=='replacement' and i>1)
            rows.append(dict(ordinal=i,clipboardExact=True,shown=True,generation=generation,
                changeCount=i,payload=f'diagnostic-{generation}',expectedPayload=f'diagnostic-{generation}',
                receiptNs=(i*1_000_000_000,i*1_000_000_000),driver=['normal-XCTest-tap','experimental-XCTest-coordinate-tap','normal-XCTest-third-tap'][i-1]))
        events=[] if scenario=='timeout' else [dict(kind='replace',generation=1,shown=True,receiptNs=(1_500_000_000,1_500_000_000))] if scenario=='replacement' else [dict(kind='dismiss',generation=0,shown=False,receiptNs=(1_400_000_000,1_400_000_000)),dict(kind='reopen',generation=0,shown=True,receiptNs=(1_600_000_000,1_600_000_000))]
        return rows,events
    def test_native_double_envelope_is_conservative(self):
        low,high=uptime_interval_ns(1.0)
        self.assertLess(low,1_000_000_000);self.assertGreater(high,1_000_000_000)
        for value in (True,1,-1.0,float("nan"),float("inf")):
            with self.assertRaises(ValueError):uptime_interval_ns(value)
    def test_uncertain_transition_cannot_claim_order(self):
        rows,events=self.fixture("dismissal");events[1]["receiptNs"]=(1_600_000_000,2_000_000_000)
        with self.assertRaises(ValueError):validate("dismissal",rows,events)
    def test_original_scenarios(self):
        for scenario in ('timeout','replacement','dismissal'):
            self.assertFalse(validate(scenario,*self.fixture(scenario))['admissionEligible'])
    def test_missing_extra_reordered_transition(self):
        rows,events=self.fixture('dismissal')
        for changed in (events[:1],events+events[:1],list(reversed(events))):
            with self.assertRaises(ValueError):validate('dismissal',rows,changed)
    def test_wrong_transition_context(self):
        rows,events=self.fixture('dismissal')
        for key,value in [('shown',True),('generation',1),('receiptNs',(2_100_000_000,2_100_000_000))]:
            changed=deepcopy(events);changed[0][key]=value
            with self.assertRaises(ValueError):validate('dismissal',rows,changed)
    def test_nonzero_initial_overlap_generation_rejected(self):
        rows,events=self.fixture("replacement")
        for row in rows+events:row["generation"]+=5
        with self.assertRaises(ValueError):validate("replacement",rows,events)
    def test_scheduled_intent_cannot_replace_receipt(self):
        rows,events=self.fixture('replacement');events[0].pop('receiptNs')
        with self.assertRaises(ValueError):validate('replacement',rows,events)
    def test_distinct_real_events_and_identity_required(self):
        for key,value in [('changeCount',1),('driver','normal-XCTest-tap'),('generation',0),('clipboardExact',False)]:
            rows,events=self.fixture('replacement');rows[1][key]=value
            with self.assertRaises(ValueError):validate('replacement',rows,events)

if __name__=='__main__':unittest.main()
