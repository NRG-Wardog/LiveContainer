import copy
import unittest
import bound_clocks as b

IDENTITY={'session':'a'*32,'simulatorUDID':'11111111-1111-1111-1111-111111111111','hostPID':123,
          'appContainerReceiptSHA256':'b'*64,'sourceSHA256':'c'*64}

def document():
    apps=[];mach=[]
    for p,(phase,start) in enumerate(zip(('pre','mid','post'),(1,11,21))):
        for i in range(8):
            ns=10**9*(10+p*10)+i*1000000
            apps.append(dict(phase=phase,ordinal=i+1,requestID=start+i,hostBeforeNs=ns,hostAfterNs=ns+100000,
                             appReceive=(ns+10000)/1e9,appSend=(ns+20000)/1e9))
            mach.append(dict(phase=phase,ordinal=i+1,hostBeforeNs=ns-1000,hostAfterNs=ns,
                             machTicks=ns-500,timebaseNumer=1,timebaseDenom=1))
    return dict(schema='p1-direct-bound-clocks-v1',identity=copy.deepcopy(IDENTITY),appExchanges=apps,
                machExchanges=mach,model='scenario-wide-constant-offset-and-unit-rate-conditional',admissionEligible=False)

class BoundTests(unittest.TestCase):
    def test_complete_conditional_scenario(self):
        result=b.inspect(document(),IDENTITY)
        self.assertTrue(result['scenarioBoundaryMappingConditional'])
        self.assertFalse(result['unsampledDriftExcluded'])
        self.assertFalse(result['admissionEligible'])
    def test_identity_schema_and_model_fail_closed(self):
        for mutate in (lambda d:d['identity'].update(session='d'*32),lambda d:d.update(extra=True),
                       lambda d:d.update(model='no-extrapolation-proven'),lambda d:d.update(admissionEligible=True)):
            d=document();mutate(d)
            with self.assertRaises(ValueError):b.inspect(d,IDENTITY)
    def test_missing_or_foreign_samples_reject(self):
        for mutate in (lambda d:d['appExchanges'].pop(),lambda d:d['machExchanges'][0].update(extra=1),
                       lambda d:d['appExchanges'][8].update(requestID=10),lambda d:d['appExchanges'][0].update(ordinal=True)):
            d=document();mutate(d)
            with self.assertRaises(ValueError):b.inspect(d,IDENTITY)
    def test_serialized_whole_double_and_bool(self):
        self.assertEqual(b.uptime(10),b.uptime(10.0))
        for value in (True,2**53+1):
            with self.assertRaises(ValueError):b.uptime(value)
    def test_reverse_response_and_host_intervals_reject(self):
        for mutate in (lambda d:d['appExchanges'][0].update(appSend=0.),
                       lambda d:d['appExchanges'][1].update(hostBeforeNs=0),
                       lambda d:d['appExchanges'][0].update(appReceive=float('nan'))):
            d=document();mutate(d)
            with self.assertRaises(ValueError):b.inspect(d,IDENTITY)

if __name__=='__main__':unittest.main()
