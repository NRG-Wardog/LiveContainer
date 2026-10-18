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
    def test_app_identity_precedes_runner_discovery(self):
        source=inspect.getsource(capture.run_calibration)
        self.assertLess(source.index('app_container=container'),source.index('pool.submit'))
        self.assertIn("if 'app' in roots and 'runner' not in roots:",source)
        self.assertIn('channel_at(app_container,APP_ID,session)',source)
        self.assertIn('command.scope.remaining(180)',source)
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
