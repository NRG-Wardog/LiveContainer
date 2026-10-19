import copy
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture
import process_scope

class Discovery(unittest.TestCase):
    def receipt(self,path):return dict(argv=['xcrun','simctl','get_app_container','device',capture.APP_ID,'data'],exit_code=0,stdout=str(path),stderr='',failure_type=None,primary_error=None,cleanup_errors=[],writer_settled=True,launch_receipt=dict(state='pre-exec-observed',closed=True,eof=True,exec_failure=None))
    def test_valid_path_and_exact_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=self.receipt(tmp);command=mock.Mock(return_value=row)
            self.assertEqual(capture.container(command,'device',capture.APP_ID),Path(tmp).resolve());self.assertTrue(command.call_args.kwargs['receipt'])
            row.update(exit_code=2,stdout='',failure_type='CalledProcessError',stderr='An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=2):\nThe operation couldn’t be completed. No such file or directory\nNo such file or directory\n')
            self.assertIsNone(capture.container(command,'device',capture.RUNNER_ID))
    def test_infrastructure_and_unknown_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for change in [dict(writer_settled=False),dict(cleanup_errors=[{'type':'PermissionError'}]),dict(failure_type='TimeoutExpired'),dict(exit_code=2,stderr='different',failure_type='CalledProcessError'),dict(launch_receipt={})]:
                with self.subTest(change=change),self.assertRaises(ValueError):capture.container(mock.Mock(return_value={**self.receipt(tmp),**change}),'device',capture.APP_ID)
    def test_cached_channel_identity_and_link_checks(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();session='a'*32;child=root/'Documents/p1-capability-app'/session;child.mkdir(parents=True)
            self.assertIsNone(capture.channel_at(root,capture.APP_ID,session))
            (child/'identity.json').write_text(json.dumps({'session':session,'bundleIdentifier':capture.APP_ID}))
            self.assertEqual(capture.channel_at(root,capture.APP_ID,session),child)
            (child/'identity.json').write_text(json.dumps({'session':'b'*32,'bundleIdentifier':capture.APP_ID}))
            with self.assertRaises(ValueError):capture.channel_at(root,capture.APP_ID,session)
    def test_test_start_precedes_current_container_discovery(self):
        source=inspect.getsource(capture.run_calibration)
        self.assertNotIn('app_container=container',source)
        self.assertIn("if not hint_observed and calibration_started(native_logs/'command-0001.stdout',startup_state):",source)
        self.assertIn('channel_at(containers[role],identifier,session)',source)
        self.assertIn('remaining=min(30,deadline-time.monotonic())',source)
        self.assertIn('channel_root(command,device,identifier,session)',source)
        self.assertIn('command.scope.remaining(180)',source)
        self.assertIn("native_command=process_scope.Commands(command.scope,native_logs)",source)
    def test_start_hint_exact_bounded_and_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stdout'
            self.assertFalse(capture.calibration_started(path,{}))
            marker="Test Case '-[P0SignInUITests."+capture.CLASS+' '+capture.METHOD+"]' started."
            for text in ['other test started',marker.replace('started.','passed.'),marker+' extra',marker]:
                path.write_text(text);self.assertFalse(capture.calibration_started(path,{}))
            path.write_text('prefix\n'+marker+'\n');self.assertTrue(capture.calibration_started(path,{}))
            path.write_text(marker+'\n'+marker+'\n')
            with self.assertRaises(ValueError):capture.calibration_started(path,{})
            path.write_bytes(b'x'*(4*1024*1024+1))
            with self.assertRaises(ValueError):capture.calibration_started(path,{})
            path.unlink();path.symlink_to(Path(tmp)/'missing')
            with self.assertRaises(OSError):capture.calibration_started(path,{})
    def test_log_replacement_shrink_fifo_and_deadline(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'stdout';path.write_text('prefix\n');state={}
            self.assertFalse(capture.calibration_started(path,state))
            path.write_text('x')
            with self.assertRaises(ValueError):capture.calibration_started(path,state)
            replacement=Path(tmp)/'replacement';replacement.write_text('prefix\n');replacement.replace(path)
            with self.assertRaises(ValueError):capture.calibration_started(path,state)
            path.unlink();os.mkfifo(path)
            with self.assertRaises(ValueError):capture.calibration_started(path,{})
            command=mock.Mock()
            for timeout in [0,-1,11]:
                with self.assertRaises(ValueError):capture.container(command,'device',capture.APP_ID,timeout=timeout)
            command.assert_not_called()
    def test_startup_allowance_and_historical_failure_retained(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);timing=root/'timing.json';row=self.receipt(root)
            row['wait_timing']={'command_started':1,'wait_finished':18}
            command=mock.Mock(return_value=row)
            self.assertEqual(capture.container(command,'device',capture.APP_ID,timeout=30,startup_timing=timing),root.resolve())
            self.assertEqual(command.call_args.kwargs['timeout'],30)
            self.assertTrue(json.loads(timing.read_text())['historical_10s_exceeded'])
            row.update(failure_type='TimeoutExpired',exit_code=-15)
            with self.assertRaises(ValueError):capture.container(command,'device',capture.APP_ID,timeout=30,startup_timing=timing)
            self.assertEqual(json.loads(timing.read_text())['failure_type'],'TimeoutExpired')
            with self.assertRaises(ValueError):capture.container(command,'device',capture.APP_ID,timeout=31,startup_timing=timing)
    def test_recovery_only_retained_completed_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=mock.Mock(pid=99,returncode=-15);owned=process_scope.OwnedProcess(raw)
            row=dict(pid=99,argv=['xcrun','simctl','get_app_container','device',capture.APP_ID,'data'],settled=False,reaped=True,exit_code=-15,cleanup_errors=[{'type':'PermissionError'}])
            for change in [dict(argv=['other']),dict(reaped=False),dict(exit_code=None)]:
                scope=mock.Mock(rows=[{**row,**change}],processes={99:owned});command=mock.Mock(scope=scope)
                with self.assertRaises(ValueError):capture.settle_discovery_observers(command,'device',Path(tmp))
                scope.settle.assert_not_called()
            scope=mock.Mock(rows=[copy.deepcopy(row)],processes={99:owned});scope.remaining.return_value=15
            scope.settle.side_effect=lambda p:scope.rows[0].update(settled=True)
            capture.settle_discovery_observers(mock.Mock(scope=scope),'device',Path(tmp))
            scope.settle.assert_called_once_with(owned);self.assertEqual(scope.rows[0]['cleanup_errors'],row['cleanup_errors'])
            self.assertTrue((Path(tmp)/'discovery-settlement-recovery.json').is_file())
    def test_expired_or_unknown_ownership_never_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=dict(pid=99,argv=['xcrun','simctl','get_app_container','device',capture.APP_ID,'data'],settled=False,reaped=True,exit_code=-15)
            for processes,reserve in [({},15),({99:process_scope.OwnedProcess(mock.Mock(pid=99,returncode=-15))},0)]:
                scope=mock.Mock(rows=[row],processes=processes);scope.remaining.return_value=reserve
                with self.assertRaises(ValueError):capture.settle_discovery_observers(mock.Mock(scope=scope),'device',Path(tmp))
                scope.settle.assert_not_called()

if __name__=='__main__':unittest.main()
