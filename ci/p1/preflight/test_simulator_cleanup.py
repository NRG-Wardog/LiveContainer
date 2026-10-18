"""Independent exact-device state proof never erases a shutdown command error."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import simulator_cleanup
DEVICE='12345678-1234-1234-1234-123456789abc'
OTHER='abcdefab-1234-1234-1234-123456789abc'


def receipt(code=0,stdout=''):
    return {'exit_code':code,'failure_type':None if code==0 else 'CalledProcessError','primary_error':None if code==0 else {'type':'CalledProcessError','returncode':code},'cleanup_errors':[],'stdout':stdout,'stderr':''}


def state(name,device=DEVICE):return receipt(stdout=json.dumps({'devices':{'runtime':[{'udid':device,'state':name}]}}))


class SimulatorCleanupTests(unittest.TestCase):
    def confirm(self,replies):
        command=mock.Mock(side_effect=replies)
        with contextlib.redirect_stdout(io.StringIO()):result=simulator_cleanup.confirm_shutdown(command,DEVICE,True)
        for call in command.call_args_list:self.assertEqual(call.kwargs,{'timeout':15,'cleanup':True,'receipt':True})
        self.assertFalse(result['admissionEligible']);return result,command

    def test_preexisting_shutdown_avoids_redundant_command(self):
        result,command=self.confirm([state('Shutdown')]);self.assertTrue(result['observed_shutdown']);self.assertFalse(result['command_failed'])
        command.assert_called_once_with('xcrun','simctl','list','devices','--json',timeout=15,cleanup=True,receipt=True)

    def test_booted_zero_shutdown_requires_fresh_shutdown_query(self):
        result,command=self.confirm([state('Booted'),receipt(),state('Shutdown')]);self.assertTrue(result['observed_shutdown']);self.assertFalse(result['command_failed'])
        self.assertEqual([r['phase'] for r in result['receipts']],['before','shutdown','after']);self.assertEqual(command.call_args_list[1].args,('xcrun','simctl','shutdown',DEVICE))

    def test_nonzero_shutdown_preserves_failure_after_observed_shutdown(self):
        for code in [149,1,9]:
            with self.subTest(code=code):
                result,_=self.confirm([state('Booted'),receipt(code),state('Shutdown')]);self.assertTrue(result['observed_shutdown']);self.assertTrue(result['command_failed']);self.assertEqual(result['receipts'][1]['command']['exit_code'],code)

    def test_zero_and_149_cannot_override_still_booted(self):
        for code in [0,149]:
            with self.subTest(code=code):
                result,_=self.confirm([state('Booted'),receipt(code),state('Booted')]);self.assertFalse(result['observed_shutdown'])
                if code:self.assertTrue(result['command_failed'])

    def test_query_failures_ignore_plausible_stdout(self):
        changes=[{'exit_code':149,'failure_type':'CalledProcessError'},{'failure_type':'TimeoutExpired'},{'primary_error':{'type':'TimeoutExpired'}},{'cleanup_errors':[{'type':'PermissionError','errno':1}]}]
        for change in changes:
            with self.subTest(change=change):
                row=state('Shutdown');row.update(change);result,command=self.confirm([row]);self.assertFalse(result['observed_shutdown']);self.assertTrue(result['command_failed']);self.assertEqual(command.call_count,1)
                self.assertIn('state_error',result['receipts'][0]);self.assertNotIn('observed_state',result['receipts'][0])

    def test_timeout_exception_is_retained(self):
        result,command=self.confirm([subprocess.TimeoutExpired('private-command',15)]);self.assertFalse(result['observed_shutdown']);self.assertTrue(result['command_failed']);self.assertEqual(command.call_count,1)
        self.assertEqual(result['receipts'][0]['command']['primary_error'],{'type':'TimeoutExpired','timeout_seconds':15});self.assertNotIn('private-command',json.dumps(result))

    def test_failed_fresh_query_does_not_prove_shutdown(self):
        for failure in [{'failure_type':'TimeoutExpired'},{'cleanup_errors':[{'type':'PermissionError','errno':1}]}]:
            with self.subTest(failure=failure):
                row=state('Shutdown');row.update(failure);result,_=self.confirm([state('Booted'),receipt(),row]);self.assertFalse(result['observed_shutdown']);self.assertTrue(result['command_failed'])

    def test_duplicate_missing_and_case_duplicate_uuid_rejected(self):
        item={'udid':DEVICE,'state':'Shutdown'}
        inventories=[{'one':[]},{'one':[{'udid':OTHER,'state':'Shutdown'}]},{'one':[item,item]}, {'one':[item,{'udid':DEVICE.upper(),'state':'Shutdown'}]},{'one':[item],'two':[item]}]
        for groups in inventories:
            with self.subTest(groups=groups),self.assertRaises(ValueError):simulator_cleanup.observed_state(receipt(stdout=json.dumps({'devices':groups})),DEVICE)

    def test_malformed_duplicate_and_wrong_shape_json_rejected(self):
        values=['not json','[]','null','{"devices":{},"devices":{}}','{"devices":{"runtime":[{"udid":"'+DEVICE+'","state":"Booted","state":"Shutdown"}]}}',json.dumps({'devices':[]}),json.dumps({'devices':{'runtime':{}}}),json.dumps({'devices':{'runtime':[{'state':'Shutdown'}]}})]
        for raw in values:
            with self.subTest(raw=raw),self.assertRaises(ValueError):simulator_cleanup.observed_state(receipt(stdout=raw),DEVICE)

    def test_wrong_states_and_oversized_query_rejected(self):
        for name in ['Booting','Shutting Down','shutdown','Unknown',None,False]:
            with self.subTest(state=name),self.assertRaises(ValueError):simulator_cleanup.observed_state(state(name),DEVICE)
        for raw in [None,b'{}','x'*(1024*1024+1)]:
            with self.subTest(type=type(raw).__name__),self.assertRaises(ValueError):simulator_cleanup.observed_state(receipt(stdout=raw),DEVICE)

    def test_unowned_invalid_or_noncanonical_uuid_never_calls_command(self):
        for device,owned in [(DEVICE,False),(DEVICE,1),(None,True),('device',True),(DEVICE.replace('-',''),True),(DEVICE+' ',True)]:
            command=mock.Mock()
            with self.subTest(device=device,owned=owned),self.assertRaises((ValueError,TypeError,AttributeError)):simulator_cleanup.confirm_shutdown(command,device,owned)
            command.assert_not_called()

    def test_uppercase_uuid_matches_same_exact_device(self):
        self.assertEqual(simulator_cleanup.observed_state(state('Shutdown',DEVICE.upper()),DEVICE),'Shutdown')

    def test_clean_command_requires_integer_zero_and_no_errors(self):
        self.assertTrue(simulator_cleanup.clean_command(receipt()))
        for change in [{'exit_code':False},{'exit_code':0.0},{'exit_code':'0'},{'exit_code':None},{'failure_type':'TimeoutExpired'},{'primary_error':{}},{'cleanup_errors':[{}]}]:
            row=receipt();row.update(change)
            with self.subTest(change=change):self.assertFalse(simulator_cleanup.clean_command(row))

if __name__=='__main__':unittest.main()
