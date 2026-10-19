"""Exact retained lifecycle adversarial tests; local Python fixtures only."""
import copy,hashlib,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_gate as gate
from inventory import *
from lifecycle import finish_owned_child,CommandRunner
class LifecycleTests(unittest.TestCase):
    def test_owned_process_settles_without_post_reap_signals(self):
        child=subprocess.Popen([sys.executable,'-c','print("fixture")'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        child.communicate(timeout=3)
        result=finish_owned_child(child);state=result['ownedProcessGroup']
        self.assertTrue(state['quiescent']);self.assertTrue(state['reapedBeforeSignals']);self.assertEqual(state['signals'],[])
    def test_owned_running_process_is_terminated_before_reap(self):
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        result=finish_owned_child(child);state=result['ownedProcessGroup']
        self.assertTrue(state['identityRetainedForSignals']);self.assertTrue(state['quiescent']);self.assertTrue(state['signals'])
    def test_transport_rejects_missing_index_and_unsettled_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);dump(root/'provenance/result.json',{'writers_quiescent':False})
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_command_streams_separate_and_stdout_discovery_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=CommandRunner();runner.evidence=Path(directory);(runner.evidence/'logs').mkdir();runner.command_quiescence=[]
            argv=[sys.executable,'-c','import sys;print("stdout");print("stderr",file=sys.stderr)']
            self.assertEqual(runner.run('stdout-only',argv,stdout_only=True),'stdout\n')
            self.assertEqual((runner.evidence/'logs/stdout-only.stderr.log').read_text(),'stderr\n')
            self.assertEqual(runner.run('both-streams',argv),'stdout\nstderr\n')
    def test_deadline_and_timeout_cannot_become_success(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=CommandRunner();runner.evidence=Path(directory);(runner.evidence/'logs').mkdir();runner.command_quiescence=[]
            runner.deadline=time.monotonic()-1
            with self.assertRaises(ValueError):runner.run('expired',[sys.executable,'-c','pass'])
            runner.deadline=time.monotonic()+5
            with self.assertRaises(subprocess.TimeoutExpired):runner.run('timeout',[sys.executable,'-c','import time;time.sleep(30)'],timeout=0.05)
            receipt=parse((runner.evidence/'logs/timeout.settlement.json').read_bytes())
            self.assertNotEqual((runner.evidence/'logs/timeout.exit-code.txt').read_text(),'0\n')
            self.assertTrue(receipt['ownedProcessGroup']['quiescent']);self.assertTrue(receipt['ownedProcessGroup']['identityRetainedForSignals'])

