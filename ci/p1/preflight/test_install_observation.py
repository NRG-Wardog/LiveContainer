import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture
import process_scope
import test_capability

class InstallObservation(unittest.TestCase):
    def receipt(self,seconds=24):
        return {'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[],'writer_settled':True,
                'wait_timing':{'command_started':100,'wait_started':104,'wait_finished':100+seconds,'wait_returned':True,'settlement_finished':105+seconds},
                'launch_receipt':{'state':'pre-exec-observed','closed':True,'eof':True,'exec_failure':None}}
    def observe(self,receipt):
        with tempfile.TemporaryDirectory() as tmp:
            command=mock.Mock(return_value=receipt)
            row=capture.observe_install(command,'exact-device',Path('/fixture.app'),Path(tmp))
            command.assert_called_once_with('xcrun','simctl','install','exact-device',Path('/fixture.app'),timeout=120,receipt=True)
            self.assertEqual(row,json.loads((Path(tmp)/'install-observation.json').read_text()))
            self.assertFalse(row['admissionEligible']);self.assertFalse(row['ui_executed'])
            return row
    def test_completion_below30_and_above30_preserve_threshold(self):
        for seconds in (24,31,119):
            with self.subTest(seconds=seconds):
                row=self.observe(self.receipt(seconds));self.assertTrue(row['installation_completed'])
                self.assertEqual(row['original_30_exceeded'],seconds>30)
                self.assertEqual(row['command_through_wait_seconds'],seconds)
    def test_timeout_and_unknown_receipt_and_cleanup_fail_closed(self):
        for change in ({'exit_code':-15,'failure_type':'TimeoutExpired','primary_error':{'type':'TimeoutExpired'}},
                       {'launch_receipt':{'state':'unknown'}},{'writer_settled':False},
                       {'cleanup_errors':[{'type':'PermissionError'}]},{'wait_timing':{}}):
            with self.subTest(change=change):
                receipt=self.receipt(120);receipt.update(change)
                self.assertFalse(self.observe(receipt)['installation_completed'])
    def test_execute_never_runs_ui_and_retains_threshold_and_cleanup_failure(self):
        for complete,exceeded,cleanup in ((True,False,False),(True,True,False),(False,True,False),(True,False,True)):
            with self.subTest(complete=complete,exceeded=exceeded,cleanup=cleanup):
                case=test_capability.PhoneOnlyRoutingTests();case.setUp()
                try:
                    passed,row,command=case.execute_phone(cleanup_failure=cleanup,install_observation={'installation_completed':complete,'original_30_exceeded':exceeded,'diagnostic_complete':True})
                    self.assertEqual(passed,complete and not exceeded and not cleanup)
                    self.assertFalse(row['capabilities_passed']);self.assertFalse(row['collection_complete']);self.assertFalse(row['ui_executed'])
                    self.assertFalse(any('test-without-building' in c.args for c in command.call_args_list))
                finally:case.doCleanups()
    def test_wait_timing_records_actual_wait_separate_from_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=process_scope.Scope(root);logs=root/'commands';logs.mkdir()
            row=process_scope.Commands(scope,logs)('/usr/bin/true',timeout=10,receipt=True)
            t=row['wait_timing'];self.assertTrue(t['wait_returned']);self.assertLessEqual(t['command_started'],t['wait_started']);self.assertLessEqual(t['wait_started'],t['wait_finished']);self.assertLessEqual(t['wait_finished'],t['settlement_finished']);scope.close()

if __name__=='__main__':unittest.main()
