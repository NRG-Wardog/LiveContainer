import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import simctl_capture
from test_stall_fresh import proof,DEVICE,SESSION

class CaptureProbe(unittest.TestCase):
    def setup_command(self,root,mutate=None):
        p=proof();scope=SimpleNamespace(session=SESSION,fixture={'device':DEVICE,'deleted':False,'stopped':False,'owned_created':p},creation_intent={k:v for k,v in p.items() if k not in ('device','create_complete')})
        row={'exit_code':0,'primary_error':None,'cleanup_errors':[],'failure_type':None,'writer_settled':True,'launch_receipt':{'state':'pre-exec-observed','closed':True,'eof':True,'exec_failure':None},'wait_timing':{'command_started':100.,'wait_finished':100.2,'wait_returned':True}}
        if mutate:mutate(scope,row)
        calls=[]
        def command(*argv,**kwargs):
            calls.append((argv,kwargs));Path(argv[-1]).write_bytes(b'PNG');return row
        command.scope=scope
        return command,calls
    def test_full_interval_and_fixed_argv(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);command,calls=self.setup_command(root)
            r=simctl_capture.take(command,DEVICE,SESSION,root,'pre',1,lambda raw:raw==b'PNG')
            self.assertEqual((r['hostBefore'],r['hostAfter']),(100.,100.2));self.assertFalse(r['admissionEligible']);self.assertFalse(r['capture_timestamp_assumed'])
            self.assertEqual(calls[0][0][:-1],('xcrun','simctl','io',DEVICE,'screenshot','--type=png'));self.assertEqual(calls[0][1],{'timeout':10,'receipt':True})
            with self.assertRaises(ValueError):simctl_capture.take(command,DEVICE,SESSION,root,'pre',1,lambda raw:True)
            self.assertEqual(len(calls),1)
    def test_failed_unknown_or_unsettled_receipt_retained(self):
        for field,value in [('exit_code',1),('primary_error',{'type':'TimeoutExpired'}),('cleanup_errors',[{'type':'Error'}]),('writer_settled',False),('launch_receipt',{}),('launch_receipt',{'state':'unknown'})]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as t:
                root=Path(t);command,calls=self.setup_command(root,lambda scope,row:row.update({field:value}))
                with self.assertRaises(ValueError):simctl_capture.take(command,DEVICE,SESSION,root,'pre',1,lambda raw:True)
                self.assertEqual(json.loads((root/'capture-cli-pre-1.json').read_text())['command'][field],value)
    def test_invalid_png_or_interval_rejected(self):
        for mode in ['png','reverse','nan','not-returned']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                def change(scope,row):
                    if mode=='reverse':row['wait_timing']['wait_finished']=99
                    if mode=='nan':row['wait_timing']['wait_finished']=float('nan')
                    if mode=='not-returned':row['wait_timing']['wait_returned']=False
                root=Path(t);command,_=self.setup_command(root,change)
                with self.assertRaises(ValueError):simctl_capture.take(command,DEVICE,SESSION,root,'pre',1,lambda raw:mode!='png')
    def test_wrong_owned_identity_and_sample_rejected_before_command(self):
        for mode in ['wrong-device','wrong-session','stopped','deleted','intent','phase','ordinal']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as t:
                root=Path(t);command,calls=self.setup_command(root)
                if mode=='stopped':command.scope.fixture['stopped']=True
                if mode=='deleted':command.scope.fixture['deleted']=True
                if mode=='intent':command.scope.creation_intent['name']='different'
                with self.assertRaises(ValueError):simctl_capture.take(command,'wrong' if mode=='wrong-device' else DEVICE,'wrong' if mode=='wrong-session' else SESSION,root,'wrong' if mode=='phase' else 'pre',4 if mode=='ordinal' else 1,lambda raw:True)
                self.assertFalse(calls)
    def test_profile_is_diagnostic_and_all_samples_retained(self):
        source=(Path(__file__).parent/'capture.py').read_text()
        self.assertIn("require(len(probe_rows)==9,'all nine host samples required')",source)
        self.assertIn("result['collection_complete'] and result['calibration_feasible'] and not simctl_probe",source)
        self.assertIn("if simctl_probe:probe_rows.append(simctl_capture.take",source)
        self.assertIn("'timing_feasibility_established':False",source)
