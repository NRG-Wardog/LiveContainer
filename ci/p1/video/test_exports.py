import copy
import json
from pathlib import Path
import tempfile
import unittest
import exports
import capture

class ExportValidation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.scenario='replacement';self.device='fixture-UDID'
        self.summary=dict(result='Passed',passedTests=1,failedTests=0,skippedTests=0,totalTestCount=1,expectedFailures=0,devicesAndConfigurations=[{'device':{'deviceId':self.device}}])
        method=exports.METHODS[self.scenario];self.identifier='P0SignInUITests/'+method+'()';self.url='test://com.apple.xcode/P0SignIn/P0SignInUITests/P0SignInUITests/'+method
        self.tests={'testNodes':[{'nodeType':'Test Case','nodeIdentifier':self.identifier,'nodeIdentifierURL':self.url,'result':'Passed'}]}
        self.controls=dict(schema='p1-video-controls-v1',scenario=self.scenario,copyFrame=[10,10,100,30],markerFrame=[20,170,192,16],windowFrame=[0,0,300,200],copyLabel='Copy Details',copyHittable=True)
        self.inputs=dict(schema='p1-video-input-v1',scenario=self.scenario,firstBefore=1,firstAfter=2,firstDriver='normal-XCTest-tap',secondDelayRequested=1.10,secondDelayBefore=2.01,secondDelayAfter=3.12,secondBefore=3.13,secondAfter=4,secondDriver='experimental-XCTest-coordinate-tap',thirdBefore=15,thirdAfter=16,thirdDriver='normal-XCTest-third-tap',thirdHittable=True,thirdLabelBefore='Copy Details')
        self.complete=dict(schema='p1-video-completion-v1',scenario=self.scenario,completed=True,copyAfterLabel='Copy Details',copyAfterHittable=True,admissionEligible=False)
        rows=[]
        for name,data in [('controls',self.controls),('input',self.inputs),('complete',self.complete),('before',b'PNG1'),('after',b'PNG2')]:
            filename=name+('.png' if isinstance(data,bytes) else '.json')
            if isinstance(data,bytes):(self.root/filename).write_bytes(data)
            else:(self.root/filename).write_text(json.dumps(data))
            rows.append(dict(deviceId=self.device,exportedFileName=filename,suggestedHumanReadableName=f'video-{self.scenario}-{name}_0_file'+Path(filename).suffix))
        self.manifest=[dict(testIdentifier=self.identifier,testIdentifierURL=self.url,attachments=rows)];self.save()
    def save(self):
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'input.json').write_text(json.dumps(self.inputs))
    def verify(self):
        self.save();return exports.verify(self.root,self.summary,self.tests,self.scenario,self.device,capture.parse,capture.ordinary,lambda b:b.startswith(b'PNG'))
    def test_exact_associated_exports(self):self.assertEqual(self.verify()[1],self.inputs)
    def test_boolean_count(self):
        self.summary['passedTests']=True
        with self.assertRaises(ValueError):self.verify()
    def test_skipped(self):
        self.summary['skippedTests']=1
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_method(self):
        self.tests['testNodes'][0]['nodeIdentifier']='Other/test()'
        with self.assertRaises(ValueError):self.verify()
    def test_failed_method(self):
        self.tests['testNodes'][0]['result']='Failed'
        with self.assertRaises(ValueError):self.verify()
    def test_extra_method(self):
        self.tests['testNodes'].append(copy.deepcopy(self.tests['testNodes'][0]))
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_target_url(self):
        self.tests['testNodes'][0]['nodeIdentifierURL']='test://wrong'
        with self.assertRaises(ValueError):self.verify()
    def test_manifest_wrong_method(self):
        self.manifest[0]['testIdentifier']='Other/test()'
        with self.assertRaises(ValueError):self.verify()
    def test_manifest_wrong_target(self):
        self.manifest[0]['testIdentifierURL']='wrong'
        with self.assertRaises(ValueError):self.verify()
    def test_other_device(self):
        self.manifest[0]['attachments'][0]['deviceId']='other'
        with self.assertRaises(ValueError):self.verify()
    def test_summary_other_device(self):
        self.summary['devicesAndConfigurations'][0]['device']['deviceId']='other'
        with self.assertRaises(ValueError):self.verify()
    def test_duplicate_attachment(self):
        self.manifest[0]['attachments'].append(copy.deepcopy(self.manifest[0]['attachments'][0]))
        with self.assertRaises(ValueError):self.verify()
    def test_reused_file(self):
        self.manifest[0]['attachments'][-1]['exportedFileName']='before.png'
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_driver(self):
        self.inputs['secondDriver']='assisted'
        with self.assertRaises(ValueError):self.verify()
    def test_wrong_input_scenario(self):
        self.inputs['scenario']='timeout'
        with self.assertRaises(ValueError):self.verify()
    def test_nonfinite_input(self):
        self.inputs['firstBefore']=float('nan')
        with self.assertRaises(ValueError):self.verify()
    def test_disordered_input(self):
        self.inputs['secondBefore']=1
        with self.assertRaises(ValueError):self.verify()
    def test_no_ordinary_third(self):
        self.inputs['thirdHittable']=False
        with self.assertRaises(ValueError):self.verify()
    def test_extra_timeout_input(self):
        self.inputs['scenario']='timeout'
        with self.assertRaises(ValueError):exports.input_receipt(self.inputs,'timeout')
    def test_missing_sleep_receipt(self):
        del self.inputs['secondDelayBefore']
        with self.assertRaises(ValueError):self.verify()
    def test_changed_sleep(self):
        self.inputs['secondDelayRequested']=.1
        with self.assertRaises(ValueError):self.verify()
    def test_escaped_attachment(self):
        self.manifest[0]['attachments'][0]['exportedFileName']='../outside'
        with self.assertRaises(ValueError):self.verify()

if __name__=='__main__':unittest.main()
