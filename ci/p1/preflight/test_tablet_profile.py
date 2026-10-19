import copy
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture
import fresh_device as fresh
import process_scope
from test_stall_fresh import raw,proof,DEVICE,SESSION,commandrow

KIND='com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M5-12GB'
def tablet_proof():
    p=proof();p.update(device_class='tablet',reference_device=fresh.TABLET_REFERENCE,device_type=KIND,preexisting=[fresh.boot.DEVICE,fresh.TABLET_REFERENCE]);return p

class Tablet(unittest.TestCase):
    def test_inventory_anchor_and_class(self):
        d=fresh.before(raw(fresh.TABLET_REFERENCE,kind=KIND),'tablet')
        self.assertEqual(d['device_type'],KIND);self.assertEqual(d['reference_device'],fresh.TABLET_REFERENCE)
        for args in [(raw(fresh.boot.DEVICE,kind=KIND),'tablet'),(raw(fresh.TABLET_REFERENCE,kind=fresh.TYPE),'tablet'),(raw(fresh.TABLET_REFERENCE,kind=KIND),'phone')]:
            with self.assertRaises(ValueError):fresh.before(*args)
        for k in ['watch','',None]:
            with self.assertRaises(ValueError):fresh.reference(k)
    def test_tablet_proof_drift_fails(self):
        p=tablet_proof();self.assertEqual(fresh.validate(p,SESSION,DEVICE),p)
        for key,value in [('device_class','phone'),('reference_device',fresh.boot.DEVICE),('device_type',fresh.TYPE),('preexisting',[fresh.boot.DEVICE]),('device',fresh.TABLET_REFERENCE),('runtime','bad')]:
            bad=copy.deepcopy(p);bad[key]=value
            with self.assertRaises(ValueError):fresh.validate(bad,SESSION,bad['device'])
    def test_tablet_ownership_survives_to_deletion(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            scope=process_scope.Scope(Path(tmp),phone_ui=True);p=tablet_proof()
            scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            self.assertTrue(fresh.begin_install(scope,DEVICE)['uninstalls_skipped'])
            with self.assertRaises(ValueError):fresh.begin_install(scope,DEVICE)
            scope.fixture_stopped(True)
            with self.assertRaises(RuntimeError):scope.close()
            command=mock.Mock(side_effect=[commandrow(),commandrow(),commandrow(absent=True)])
            self.assertTrue(fresh.cleanup(command,p,lambda:True)['deleted'])
            scope.fixture_deleted(True);scope.close()
    def test_exact_tablet_methods_and_unchanged_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'recovery';calls=[]
            def command(*args,**kwargs):
                calls.append((args,kwargs))
                if args[:4]==('xcrun','simctl','list','devices'):return json.dumps({'devices':{'runtime':[{'udid':DEVICE,'state':'Booted'}]}})
                if args[:2]==('xcodebuild','test-without-building'):(folder/'tests.xcresult').mkdir()
                return '{}'
            command.scope=mock.Mock()
            with mock.patch.object(capture,'stop_fixture',return_value=True),mock.patch.object(capture.base,'inventory'),mock.patch.object(capture.video.layout_exports,'verify_capabilities',return_value={}) as verify:
                result=capture.run_layout(command,Path('recipe'),DEVICE,'tablet',folder,lambda _:True)
            self.assertTrue(result['collection_complete']);self.assertFalse(result['full_matrix_complete']);self.assertFalse(result['admissionEligible'])
            args,kw=next(c for c in calls if c[0][0]=='xcodebuild')
            self.assertEqual(kw['timeout'],480);self.assertEqual(args[args.index('-maximum-test-execution-time-allowance')+1],'180')
            self.assertEqual([a.split('/')[-1] for a in args if str(a).startswith('-only-testing:')],['testCapabilityNestedTabSelection','testCapabilityNoBannerRotation'])
            self.assertEqual(verify.call_args.args[4],'tablet')
    def test_tablet_profile_cannot_select_other_routes(self):
        for key in ['full_recovery','default_tabs','calibration_only','install_diagnostic']:
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)
                with self.assertRaises(ValueError):capture.execute(p,p/'work',p/'out',p/'inputs','bad','tablet',**{key:True})
        source=inspect.getsource(capture.execute)
        self.assertIn('device_class=kind',source)
        self.assertIn("result['tablet_executed']=kind=='tablet'",source)

if __name__=='__main__':unittest.main()
