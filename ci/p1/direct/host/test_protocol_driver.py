import unittest
from protocol_driver import Driver

class Tests(unittest.TestCase):
    def make(self, mutate=None, stop=None):
        self.calls=[];self.saved=[];self.checks=0
        phases={'ready':'ready','mid':'calibrating-mid','third':'third-ready','post':'calibrating-post','finish':'finished'}
        def exchange(n,kind):
            self.calls.append((n,kind))
            response={'id':n,'appReceive':n,'appSend':n}
            if kind!='clock':response['phase']=phases[kind]
            row={'id':n,'kind':kind,'hostBeforeNs':n*10,'hostAfterNs':n*10+1,'response':response}
            if mutate:mutate(row)
            return row
        def check():
            self.checks+=1
            if stop and self.checks>=stop:raise ValueError('owned capture failed')
        return Driver(identity={},exchange=exchange,await_event=lambda kind,t:{'type':kind},
                      sample_mach=lambda phase,n:{'phase':phase,'ordinal':n},checkpoint=check,persist=self.saved.append)
    def test_original_inventory(self):
        driver=self.make();result=driver.run()
        expected=['clock']*8+['ready','mid']+['clock']*8+['third','post']+['clock']*8+['finish']
        self.assertEqual(self.calls,list(enumerate(expected,1)))
        self.assertEqual([r['requestID'] for r in result['clockDocument']['appExchanges']],list(range(1,9))+list(range(11,19))+list(range(21,29)))
        self.assertTrue(result['protocolComplete']);self.assertFalse(result['admissionEligible'])
        with self.assertRaises(ValueError):driver.run()
    def test_unknown_fields_retained_failed(self):
        driver=self.make(lambda r:r['response'].update(foreign=True))
        with self.assertRaises(ValueError):driver.run()
        self.assertTrue(self.saved[-1]['failed']);self.assertIn('foreign',self.saved[-1]['commands'][0]['response'])
    def test_wrong_phase_stops_before_actions(self):
        driver=self.make(lambda r:r['response'].update(phase='active') if r['kind']=='ready' else None)
        with self.assertRaises(ValueError):driver.run()
        self.assertEqual(len(self.calls),9);self.assertFalse(driver.finished)
    def test_timeout_is_not_retried(self):
        driver=self.make(lambda r:r.update(hostAfterNs=r['hostBeforeNs']+5_000_000_001))
        with self.assertRaises(ValueError):driver.run()
        self.assertEqual(len(self.calls),1)
    def test_capture_failure_prevents_remaining_commands(self):
        driver=self.make(stop=15)
        with self.assertRaises(ValueError):driver.run()
        self.assertTrue(driver.failed);self.assertLess(len(self.calls),29)
    def test_boolean_identity_rejected(self):
        driver=self.make(lambda r:r['response'].update(id=True))
        with self.assertRaises(ValueError):driver.run()
    def test_snapshot_is_immutable_copy(self):
        driver=self.make();result=driver.run();result['commands'][0]['response']['id']=999
        self.assertEqual(driver.commands[0]['response']['id'],1)

if __name__=='__main__':unittest.main()
