import contextlib, errno, io, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
import process_scope
class LaunchReceiptTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.logs = self.root / 'commands'
        self.logs.mkdir()
        self.scope = process_scope.Scope(self.root)
        self.command = process_scope.Commands(self.scope, self.logs)

    def run_command(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.command(*args, receipt=True, **kwargs)
        stored = json.loads((self.logs / 'commands.jsonl').read_text().splitlines()[-1])
        self.assertEqual(result['launch_receipt'], stored['launch_receipt'])
        self.assertTrue(stored['launch_receipt']['closed'])
        return result

    def assert_settled(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.scope.close()
        self.assertTrue(all((r['settled'] and r['reaped'] for r in self.scope.rows)))
        for row in self.scope.rows:
            with self.assertRaises(ChildProcessError):
                os.waitpid(row['pid'], os.WNOHANG)

    def observer(self):
        observer = process_scope.LaunchReceipt(1, time.monotonic() + 5, 5)
        reader, writer = os.pipe()
        os.set_blocking(reader, False)
        os.set_blocking(writer, False)
        observer.bind('a' * 32, reader)
        observer.row['pid'] = 4321
        observer.row['popen']['before'] = time.monotonic()
        observer.row['release']['before'] = time.monotonic()
        self.addCleanup(observer.finish)
        self.addCleanup(lambda: self.close_fd(writer))
        return (observer, writer)

    @staticmethod
    def close_fd(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def frame(self, observer, **changes):
        fields = dict(magic=process_scope.LAUNCH_MAGIC, kind=1, pid=4321, pgid=4321, sid=4321, session=b'\xaa' * 16, command=1, first_python=observer.row['popen']['before'], imports_complete=observer.row['popen']['before'], gate_enter=observer.row['release']['before'], gate_exit=observer.row['release']['before'], stamp=time.monotonic(), number=0)
        fields.update(changes)
        return process_scope.LAUNCH_RECORD.pack(*fields.values())

    def test_real_command_retains_ordered_parent_and_child_receipts(self):
        result = self.run_command(sys.executable, '-B', '-c', 'print("ok")', timeout=3)
        self.assertEqual(result['stdout'], 'ok\n')
        self.assertIsNone(result['failure_type'])
        row = result['launch_receipt']
        self.assertEqual(row['state'], 'pre-exec-observed')
        self.assertTrue(row['eof'])
        self.assertEqual(row['session'], self.scope.session)
        self.assertEqual(row['pid'], self.scope.rows[0]['pid'])
        self.assertFalse(row['target_execution_observed'])
        self.assertFalse(row['service_execution_observed'])
        popen, registration, release = (row[k] for k in ['popen', 'registration', 'release'])
        self.assertTrue(popen['returned'])
        self.assertTrue(registration['durable'])
        self.assertTrue(release['issued'])
        self.assertLessEqual(popen['before'], popen['after'])
        self.assertLessEqual(popen['after'], registration['before'])
        self.assertLessEqual(registration['before'], registration['after'])
        self.assertLessEqual(registration['after'], release['before'])
        self.assertLessEqual(release['before'], row['pre_exec']['child_monotonic'])
        self.assertLessEqual(row['pre_exec']['child_monotonic'], row['pre_exec']['observed_after'])
        self.assertLessEqual(row['pre_exec']['observed_after'], row['deadline'])
        self.assertIsNone(row['exec_failure'])
        self.assert_settled()

    def test_real_exec_failure_retains_errno_without_exception_text(self):
        secret = str(self.root / 'private-missing-token')
        result = self.run_command(secret, timeout=3)
        row = result['launch_receipt']
        self.assertEqual(result['exit_code'], 126)
        self.assertEqual(result['failure_type'], 'CalledProcessError')
        self.assertEqual(row['exec_failure']['errno'], errno.ENOENT)
        self.assertEqual(row['state'], 'pre-exec-observed')
        self.assertEqual(result['stderr'], '')
        self.assertNotIn(secret, json.dumps(row))
        self.assert_settled()

    def test_closed_reader_makes_child_fail_before_exec(self):
        observer = process_scope.LaunchReceipt(1, time.monotonic() + 3, 3)
        target = self.root / 'must-not-run'
        original = self.scope.persist

        def persist():
            original()
            os.close(observer.fd)
            observer.fd = None
        with (self.root / 'stdout').open('wb') as stream, mock.patch.object(self.scope, 'persist', side_effect=persist):
            child = self.scope.spawn([sys.executable, '-B', '-c', f'open({str(target)!r},"w").close()'], stream, launch=observer)
        child.wait(timeout=3)
        observer.finish()
        with contextlib.redirect_stdout(io.StringIO()):
            self.scope.settle(child)
        self.assertEqual(child.returncode, 125)
        self.assertFalse(target.exists())
        self.assertEqual(observer.row['state'], 'unknown')
        self.assert_settled()

    def test_malformed_identity_order_time_and_overflow_are_unknown(self):
        cases = [('magic', {'magic': b'junk'}), ('pid', {'pid': 99}), ('pgid', {'pgid': 99}), ('sid', {'sid': 99}), ('session', {'session': b'\xbb' * 16}), ('command', {'command': 2}), ('kind', {'kind': 3}), ('errno-before-preexec', {'kind': 2, 'number': errno.ENOENT}), ('preexec-errno', {'number': 1}), ('nan', {'stamp': float('nan')}), ('future', {'stamp': time.monotonic() + 100}), ('past', {'stamp': 0}), ('nan-stage',{'first_python':float('nan')}), ('stage-order',{'imports_complete':0}), ('gate-before-release',{'gate_exit':0})]
        for label, change in cases:
            with self.subTest(label=label):
                observer, writer = self.observer()
                os.write(writer, self.frame(observer, **change))
                os.close(writer)
                observer.finish()
                with self.assertRaises(process_scope.LaunchReceiptError):
                    observer.require()
                self.assertEqual(observer.row['state'], 'unknown')
                self.assertTrue(observer.row['closed'])
        for label, payload in [('duplicate', None), ('overflow', b'x' * (2 * process_scope.LAUNCH_RECORD.size + 1)), ('partial', b'P1L1'), ('missing', b'')]:
            with self.subTest(label=label):
                observer, writer = self.observer()
                payload = payload if payload is not None else self.frame(observer) * 2
                os.write(writer, payload)
                os.close(writer)
                observer.finish()
                with self.assertRaises(process_scope.LaunchReceiptError):
                    observer.require()
                self.assertTrue(observer.row['closed'])

    def test_fragmented_receipt_is_bounded_and_valid_only_after_eof(self):
        observer, writer = self.observer()
        frame = self.frame(observer)
        os.write(writer, frame[:7])
        observer.observe()
        self.assertIsNone(observer.row['pre_exec'])
        os.write(writer, frame[7:])
        observer.observe()
        self.assertIsNotNone(observer.row['pre_exec'])
        with self.assertRaises(process_scope.LaunchReceiptError):
            observer.require()
        os.close(writer)
        observer.finish()
        observer.require()
        self.assertEqual(len(observer.raw), process_scope.LAUNCH_RECORD.size)

    def test_pre_exec_observation_survives_later_timeout_and_settlement(self):
        result = self.run_command(sys.executable, '-B', '-c', 'import time;time.sleep(30)', timeout=0.15)
        self.assertEqual(result['failure_type'], 'TimeoutExpired')
        self.assertEqual(result['launch_receipt']['state'], 'pre-exec-observed')
        self.assertEqual(result['cleanup_errors'], [])
        self.assert_settled()

    def test_missing_receipt_with_optional_failure_retains_observer_cleanup_error(self):
        original = self.scope.spawn

        def spawn(*args, **kwargs):
            observer = kwargs.pop('launch')
            child = original(*args, **kwargs)
            observer.row['pid'] = child.pid
            return child
        with mock.patch.object(self.scope, 'spawn', side_effect=spawn):
            result = self.run_command('/bin/true', allow_failure=True, timeout=3)
        self.assertEqual(result['failure_type'], 'LaunchReceiptError')
        self.assertEqual(result['cleanup_errors'], [{'type': 'LaunchReceiptError'}])
        self.assertEqual(result['launch_receipt']['state'], 'unknown')
        self.assert_settled()

    def test_unresolved_settlement_is_not_hidden_by_valid_launch_receipt(self):
        original = self.scope.settle
        with mock.patch.object(self.scope, 'settle', side_effect=PermissionError(errno.EPERM, 'unknown group')):
            result = self.run_command('/bin/true', timeout=3)
        self.assertEqual(result['launch_receipt']['state'], 'pre-exec-observed')
        self.assertEqual(result['failure_type'], 'PermissionError')
        self.assertEqual(result['cleanup_errors'], [{'type': 'PermissionError', 'errno': errno.EPERM}])
        self.assertFalse(self.scope.rows[0]['settled'])
        with contextlib.redirect_stdout(io.StringIO()):
            original(self.scope.processes[self.scope.rows[0]['pid']])
        self.assert_settled()

    def test_gate_exit_before_release_rejected_with_other_stages_ordered(self):
        o,w=self.observer();start=o.row['popen']['before'];o.row['release']['before']=start+0.00001
        os.write(w,self.frame(o,first_python=start,imports_complete=start,gate_enter=start,gate_exit=start))
        os.close(w);o.finish()
        self.assertEqual(o.row['reason'],'gate-exited-before-release')
        with self.assertRaises(process_scope.LaunchReceiptError):o.require()

    def test_exec_failure_cannot_change_captured_stages(self):
        o,w=self.observer();first=self.frame(o);decoded=list(process_scope.LAUNCH_RECORD.unpack(first))
        decoded[1]=2;decoded[-1]=errno.ENOENT
        decoded[8]=(decoded[8]+decoded[9])/2  # imports complete shifts, still ordered
        if decoded[8]==process_scope.LAUNCH_RECORD.unpack(first)[8]:
            self.fail('test needs distinct bootstrap and release times')
        decoded[-2]=time.monotonic()
        os.write(w,first+process_scope.LAUNCH_RECORD.pack(*decoded));os.close(w);o.finish()
        self.assertEqual(o.row['reason'],'stage-drift')
        with self.assertRaises(process_scope.LaunchReceiptError):o.require()
