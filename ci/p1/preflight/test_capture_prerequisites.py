import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture_prerequisites as p
import process_scope
import budget

class Prerequisites(unittest.TestCase):
    def result(self):return {'schema':'p1-capture-prerequisites-v1','screenCapturePreflight':True,'enumerationAttempted':True,'windowEnumerationAvailable':True,'simulatorProcessCount':0,'simulatorOnScreenWindowCount':0,'permissionRequested':False,'pixelsCaptured':False,'environmentModified':False,'windowOwnershipEstablished':False,'timestampUnitsEstablished':False,'admissionEligible':False}
    def test_permission_denial_and_unavailable_are_stops(self):
        row=self.result();self.assertTrue(p.validate_result(row));row['windowEnumerationAvailable']=False;self.assertFalse(p.validate_result(row))
        row=self.result();row.update(screenCapturePreflight=False,enumerationAttempted=False)
        with self.assertRaises(ValueError):p.validate_result(row)
        for k in ['windowEnumerationAvailable','simulatorProcessCount','simulatorOnScreenWindowCount']:row.pop(k)
        self.assertFalse(p.validate_result(row))
    def test_missing_or_forged_fields_rejected(self):
        for key,value in [('pixelsCaptured',True),('permissionRequested',True),('admissionEligible',True),('timestampUnitsEstablished',True),('simulatorProcessCount',-1),('screenCapturePreflight',1)]:
            row=self.result();row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):p.validate_result(row)
    def test_helper_returns_before_enumeration_and_never_requests_capture(self):
        text=(p.HERE/'capture_prerequisites.swift').read_text();self.assertLess(text.index('exit(0)'),text.index('NSWorkspace.shared'))
        for name in ['CGRequestScreenCaptureAccess','SCShareableContent','startCapture','SCContentSharingPicker','kCGWindowName']:self.assertNotIn(name,text)
    def test_header_is_bounded_pinned_and_units_not_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sdk=root/'MacOSX.sdk';header=sdk/'System/Library/Frameworks/ScreenCaptureKit.framework/Headers/SCStream.h';header.parent.mkdir(parents=True);header.write_text('/* native units unknown */\nextern const SCStreamFrameInfo SCStreamFrameInfoDisplayTime;')
            with mock.patch.object(p,'SDK_ROOT',root):
                r=p.header_excerpt(str(sdk));self.assertFalse(r['timestampUnitsEstablished']);self.assertTrue(r['unitsRequireReview'])
                header.write_text('missing')
                with self.assertRaises(ValueError):p.header_excerpt(str(sdk))
                with self.assertRaises(ValueError):p.header_excerpt('/tmp/not-the-pinned-sdk')
    def test_profile_deadlines_and_mutual_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(process_scope.time,'monotonic',return_value=100):
            s=process_scope.Scope(Path(tmp),capture_prerequisites=True);self.assertEqual(s.deadline,160);self.assertEqual(s.cleanup_deadline,190);s.close()
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):process_scope.Scope(Path(tmp),capture_prerequisites=True,phone_ui=True)
        with self.assertRaises(ValueError):budget.run([],Path('/unused'),seconds=120,capture_prerequisites=True,full_recovery=True)
        with self.assertRaises(ValueError):budget.run([],Path('/unused'),seconds=120)
