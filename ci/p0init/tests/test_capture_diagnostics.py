"""Read-only evidence-parser rejection tests for the focused diagnostic lane."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('p0_constructor_capture', ROOT/'native_gate.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
class CaptureDiagnostics(unittest.TestCase):
    def report(self):
        return {'schema':1,'checks':2105,'failures':0,'skipped':0,'case_ids':list(gate.CONSTRUCTOR_CASE_IDS),'ADI_executed':False,'device_validation':False}
    def reject(self,value):
        with self.assertRaises((ValueError,TypeError)):
            gate.verify_constructor_output(json.dumps(value))
    def test_exact_success(self):
        report=self.report(); self.assertEqual(gate.verify_constructor_output(json.dumps(report)),report)
    def test_native83_requires_exact_success(self):
        gate.verify_native83_output('PASS 83 full-production-loader synthetic checks; no ADI executed\n')
        for text in ('PASS 82 full-production-loader synthetic checks; no ADI executed\n','PASS 83 full-production-loader synthetic checks; no ADI executed\nextra','AddressSanitizer: failure\n'):
            with self.assertRaises(ValueError): gate.verify_native83_output(text)
    def test_missing_duplicate_reordered_cases(self):
        for cases in ([],gate.CONSTRUCTOR_CASE_IDS[:-1],gate.CONSTRUCTOR_CASE_IDS+[gate.CONSTRUCTOR_CASE_IDS[0]],list(reversed(gate.CONSTRUCTOR_CASE_IDS))):
            report=self.report();report['case_ids']=cases;self.reject(report)
    def test_no_false_device_or_adi_success(self):
        for key in ('ADI_executed','device_validation'):
            for value in (True,0,'false',None):
                report=self.report();report[key]=value;self.reject(report)
    def test_failed_skipped_or_empty_execution_rejected(self):
        for key,values in {'checks':[0,-1,False,'2105',37,2104,2106],'failures':[1,True,'0'],'skipped':[1,True,'0']}.items():
            for value in values:
                report=self.report();report[key]=value;self.reject(report)
    def test_wrong_schema_and_extra_fields_rejected(self):
        for key in list(self.report()):
            report=self.report();del report[key];self.reject(report)
        report=self.report();report['raw_error']='private';self.reject(report)
        for value in (2,True,'1'):
            report=self.report();report['schema']=value;self.reject(report)
    def test_exact_boundary_suite(self):
        text='\n'.join(f'{name} (__main__.MaintainedAnisetteNativeTests.{name}) ... ok' for name in gate.ANISETTE_BOUNDARY_CASES)+'\nRan 8 tests in 1.0s\nOK\n'
        self.assertEqual(gate.verify_anisette_boundary_output(text)['checks'],8)
        for bad in (text.replace(' ... ok',' ... skipped',1), text.replace('Ran 8','Ran 7'), text.replace('OK\n','OK (skipped=1)\n'), text+text):
            with self.assertRaises(ValueError):gate.verify_anisette_boundary_output(bad)
    def test_duplicate_json_and_sanitizer_output_rejected(self):
        text=json.dumps(self.report())
        with self.assertRaises(ValueError):gate.verify_constructor_output(text.replace('"schema": 1','"schema": 1, "schema": 1'))
        for marker in ('runtime error:','AddressSanitizer','UndefinedBehaviorSanitizer','LeakSanitizer'):
            with self.assertRaises(ValueError):gate.verify_constructor_output(text+'\n'+marker)
if __name__=='__main__': unittest.main()
