"""Synthetic sequencing tests only: no native backend/process/UI is executed."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import native_case as n
from protocol_driver import Driver

SESSION='a'*32
DEVICE='01234567-89AB-CDEF-0123-456789ABCDEF'

class Backend:
    def __init__(self, fail=None, cleanup_fail=None):
        self.calls=[];self.receipts=[];self.saved=[];self.failure=fail;self.cleanup_fail=cleanup_fail;self.tick=1_000_000_000
        for name in n.OPERATIONS:
            setattr(self,name,self.handler(name))
    def now(self):self.tick+=1000;return self.tick
    def remaining(self,maximum,cleanup=False):return maximum
    def checkpoint(self,context):pass
    def retain(self,name,raw):self.receipts.append((name,raw))
    def persist(self,raw):self.saved.append(raw)
    def validate_stage(self,name,evidence,context):
        if evidence.raw!=n.canonical({'stage':name,'session':SESSION}):raise ValueError('unbound receipt')
    def handler(self,name):
        def invoke(context,timeout):
            self.calls.append((name,timeout))
            if name in (self.failure,self.cleanup_fail):raise ValueError('synthetic failure '+name)
            value={'device':DEVICE,'xctestrun':'/owned/one.xctestrun','resultBundle':'/owned/result.xcresult'} if name=='prepare' else {'stage':name}
            return n.Evidence(n.canonical({'stage':name,'session':SESSION}),value)
        return invoke
    def start_sample(self,context):
        return dict(hostBeforeNs=self.now(),hostAfterNs=self.now(),machTicks=self.now(),timebaseNumer=1,timebaseDenom=1)
    def make_driver(self,context,checkpoint,remaining):
        phases={'ready':'ready','mid':'calibrating-mid','third':'third-ready','post':'calibrating-post','finish':'finished'}
        def exchange(i,kind):
            response={'id':i,'appReceive':i,'appSend':i}
            if kind!='clock':response['phase']=phases[kind]
            return dict(id=i,kind=kind,hostBeforeNs=i*10,hostAfterNs=i*10+1,response=response)
        return Driver(identity={'session':SESSION,'simulatorUDID':DEVICE},exchange=exchange,
                      await_event=lambda kind,timeout:{'type':kind},sample_mach=lambda phase,i:{'phase':phase,'ordinal':i},
                      checkpoint=checkpoint,persist=lambda value:None)

class CaseTests(unittest.TestCase):
    def test_original_one_method_and_command_allowances(self):
        b=Backend();case=n.Case(SESSION,b,now_ns=b.now);result=case.run()
        self.assertTrue(result['sequenceCompleted']);self.assertFalse(result['admissionEligible'])
        argv=case.context['argv'];self.assertEqual([v for v in argv if v.startswith('-only-testing:')],['-only-testing:'+n.TEST_TARGET])
        self.assertEqual(argv.count('240'),2);self.assertEqual(case.context['nativeCommandTimeoutSeconds'],360)
        calls=[name for name,_ in b.calls]
        self.assertLess(calls.index('await_started'),calls.index('discover_app'))
        self.assertEqual(calls.count('discover_app'),1);self.assertEqual(calls.count('discover_runner'),1)
        self.assertLess(calls.index('promote_first'),calls.index('publish_ack'))
        self.assertLess(calls.index('await_native_result'),calls.index('send_stop'))
        self.assertLess(calls.index('await_strip_complete'),calls.index('send_stop'))
        self.assertEqual(calls[-6:],list(n.CLEANUP));self.assertEqual(len(case.context['protocol']['commands']),29)
        with self.assertRaises(ValueError):case.run()
    def test_startup_uses_shared_observation_deadline_without_reset(self):
        b=Backend();original=b.await_started
        def delayed(context,timeout):
            self.assertGreater(timeout,90);self.assertLessEqual(timeout,280)
            result=original(context,timeout);b.tick+=120_000_000_000;return result
        b.await_started=delayed;case=n.Case(SESSION,b,now_ns=b.now);result=case.run()
        self.assertTrue(result['sequenceCompleted'])
        self.assertEqual(case.budget['effectiveCommandBudgetNs'],360_000_000_000)
        self.assertEqual(case.budget['cleanupReserveNs'],70_000_000_000)
        self.assertEqual(case.budget['nativeMethodAllowanceSeconds'],240)
        self.assertLess(case._remaining(360),160)

    def test_every_main_stage_failure_runs_all_cleanup(self):
        for failure in n.OPERATIONS[:-len(n.CLEANUP)]:
            with self.subTest(failure=failure):
                b=Backend(fail=failure);case=n.Case(SESSION,b,now_ns=b.now)
                with self.assertRaises(ValueError):case.run()
                self.assertEqual([name for name,_ in b.calls][-6:],list(n.CLEANUP))
                self.assertTrue(case.failed);self.assertFalse(case.completed)
                if failure in ('register_baseline','await_first','promote_first'):
                    self.assertNotIn('publish_ack',[name for name,_ in b.calls])
    def test_each_cleanup_failure_keeps_later_cleanup(self):
        for failure in n.CLEANUP:
            b=Backend(cleanup_fail=failure);case=n.Case(SESSION,b,now_ns=b.now)
            with self.assertRaises(ValueError):case.run()
            self.assertEqual([name for name,_ in b.calls][-6:],list(n.CLEANUP));self.assertFalse(case.completed)
    def test_persistence_failure_still_attempts_every_cleanup(self):
        b=Backend()
        def fail(raw):raise OSError('receipt storage failed')
        b.persist=fail;case=n.Case(SESSION,b,now_ns=b.now)
        with self.assertRaises(OSError):case.run()
        self.assertEqual([name for name,_ in b.calls][-6:],list(n.CLEANUP))
    def test_timeout_cannot_reset_on_next_stage_but_cleanup_uses_scope(self):
        b=Backend();original=b.await_started
        def late(context,timeout):
            result=original(context,timeout);b.tick+=400_000_000_000;return result
        b.await_started=late;case=n.Case(SESSION,b,now_ns=b.now)
        with self.assertRaises(ValueError):case.run()
        calls=[name for name,_ in b.calls];self.assertNotIn('discover_app',calls);self.assertEqual(calls[-6:],list(n.CLEANUP))
    def test_incomplete_adapters_and_unproven_receipt_reject(self):
        with self.assertRaises(ValueError):n.Case(SESSION,object())
        b=Backend();b.register_baseline=lambda context,timeout:n.Evidence(b'foreign',{})
        case=n.Case(SESSION,b,now_ns=b.now)
        with self.assertRaises(ValueError):case.run()
        self.assertNotIn('publish_ack',[name for name,_ in b.calls])
    def test_exact_hint_wrong_method_duplicate_shrink_and_source_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'stdout';state={}
            self.assertFalse(n.timeout_started(p,state))
            marker=b"Test Case '-[P0SignInUITests.P0SignInUITests testProbeTimeoutPixels]' started.\n"
            p.write_bytes(marker);self.assertTrue(n.timeout_started(p,state))
            p.write_bytes(marker+marker)
            with self.assertRaises(ValueError):n.timeout_started(p,state)
            p.write_bytes(b'')
            with self.assertRaises(ValueError):n.timeout_started(p,state)
            p.write_bytes(marker.replace(b'testProbeTimeoutPixels',b'testProbeReplacementPixels'))
            self.assertFalse(n.timeout_started(p,{}))
            with patch.object(n,'HINT_SOURCE_SHA','0'*64),self.assertRaises(ValueError):n.timeout_started(p,{})
    def test_future_start_sample_cannot_extend_command_budget(self):
        b=Backend();sample=b.start_sample
        def future(context):
            row=sample(context);row['hostAfterNs']+=1_000_000_000;return row
        b.start_sample=future;case=n.Case(SESSION,b,now_ns=b.now)
        with self.assertRaises(ValueError):case.run()
        self.assertNotIn('launch_native',[name for name,_ in b.calls])
        self.assertEqual([name for name,_ in b.calls][-6:],list(n.CLEANUP))

    def test_wrong_driver_checkpoint_fails_before_commands(self):
        b=Backend();factory=b.make_driver
        b.make_driver=lambda context,checkpoint,remaining:factory(context,lambda:None,remaining)
        case=n.Case(SESSION,b,now_ns=b.now)
        with self.assertRaises(ValueError):case.run()
        self.assertFalse(case.completed)

if __name__=='__main__':unittest.main()
