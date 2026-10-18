import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import process_scope
import simulator_cleanup
from test_simulator_cleanup import state,receipt,DEVICE

HERE=Path(__file__).resolve().parent
class LeanBootstrap(unittest.TestCase):
    def test_child_protocol_is_structurally_identical(self):
        def fn(path):return next(x for x in ast.parse(path.read_text()).body if isinstance(x,ast.FunctionDef) and x.name=='child_main')
        self.assertEqual(ast.dump(fn(HERE/'process_scope.py')),ast.dump(fn(HERE/'launch_gate.py')))
    def test_real_lean_entry_retains_receipt_and_writer_settlement(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);logs=root/'commands';logs.mkdir();scope=process_scope.Scope(root)
            command=process_scope.Commands(scope,logs)
            row=command('/usr/bin/true',timeout=3,receipt=True)
            self.assertTrue(row['writer_settled']);self.assertIsNone(row['failure_type'])
            self.assertEqual(row['launch_receipt']['state'],'pre-exec-observed')
            scope.close()

class SafeTimeoutRecovery(unittest.TestCase):
    def timed_out(self,settled=True):
        r=receipt();r.update(exit_code=-15,failure_type='TimeoutExpired',primary_error={'type':'TimeoutExpired','timeout_seconds':15},writer_settled=settled)
        return r
    def confirm(self,rows):
        command=mock.Mock(side_effect=rows)
        with contextlib.redirect_stdout(io.StringIO()):result=simulator_cleanup.confirm_shutdown(command,DEVICE,True)
        return result,command
    def test_settled_timeout_recovers_shutdown_but_retains_failure(self):
        first=self.timed_out();result,command=self.confirm([first,receipt(),state('Shutdown')])
        self.assertTrue(result['observed_shutdown']);self.assertTrue(result['command_failed'])
        self.assertEqual(result['receipts'][0]['command']['primary_error'],first['primary_error'])
        self.assertEqual(command.call_args_list[1].args,('xcrun','simctl','shutdown',DEVICE))
        self.assertTrue(all(c.kwargs['timeout']==15 and c.kwargs['cleanup'] for c in command.call_args_list))
    def test_unknown_or_unsettled_writer_never_authorizes_recovery(self):
        for settled in [False,None]:
            result,command=self.confirm([self.timed_out(settled)])
            self.assertFalse(result['observed_shutdown']);self.assertEqual(command.call_count,1)
    def test_malformed_state_is_not_timeout_recovery(self):
        r=receipt();r.update(stdout='{}',writer_settled=True)
        result,command=self.confirm([r]);self.assertFalse(result['observed_shutdown']);self.assertEqual(command.call_count,1)
    def test_shutdown_failure_and_ambiguous_after_remain_failures(self):
        result,_=self.confirm([self.timed_out(),receipt(149),state('Shutdown')])
        self.assertTrue(result['observed_shutdown']);self.assertTrue(result['command_failed'])
        result,_=self.confirm([self.timed_out(),receipt(),state('Booted')]);self.assertFalse(result['observed_shutdown'])
    def test_expired_cleanup_reserve_never_becomes_success(self):
        result,command=self.confirm([self.timed_out(),TimeoutError('reserve'),TimeoutError('reserve')])
        self.assertFalse(result['observed_shutdown']);self.assertTrue(result['command_failed'])
    def test_unowned_or_invalid_uuid_rejected_before_command(self):
        for device,owned in [(DEVICE,False),('invalid',True)]:
            command=mock.Mock()
            with self.assertRaises(ValueError):simulator_cleanup.confirm_shutdown(command,device,owned)
            command.assert_not_called()
