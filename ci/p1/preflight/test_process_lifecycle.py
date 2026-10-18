"""Owned-child process and recorder regressions; no simulator is launched."""
import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import process_scope
spec=importlib.util.spec_from_file_location('lifecycle_capture',HERE/'capture.py')
capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)


def owned_mock(code=None):
    raw=mock.Mock(pid=4321,returncode=code,args=['fixture-child'])
    raw.poll.side_effect=lambda:raw.returncode
    return raw,process_scope.OwnedProcess(raw)


class OwnedLifecycleTests(unittest.TestCase):
    def test_nondefault_sigchld_blocks_owned_spawn(self):
        for handler in (signal.SIG_IGN, lambda *_: None):
            with self.subTest(handler=handler), mock.patch.object(process_scope.signal,'getsignal',return_value=handler), mock.patch.object(process_scope.subprocess,'Popen') as spawn:
                with self.assertRaises(ValueError):process_scope.OwnedProcess.spawn(['fixture-child'],start_new_session=True)
                spawn.assert_not_called()
                with tempfile.TemporaryDirectory() as tmp:
                    scope=process_scope.Scope(Path(tmp).resolve())
                    with mock.patch.object(process_scope.os,'pipe') as pipe, self.assertRaises(ValueError):scope.spawn(['fixture-child'],None)
                    pipe.assert_not_called();spawn.assert_not_called()

    def test_nondefault_sigchld_blocks_owned_signal(self):
        raw,child=owned_mock()
        for handler in (signal.SIG_IGN, lambda *_: None):
            with self.subTest(handler=handler), mock.patch.object(process_scope.signal,'getsignal',return_value=handler), mock.patch.object(process_scope.os,'killpg') as send:
                with self.assertRaises(ValueError):child.signal_owned(signal.SIGTERM)
                send.assert_not_called()
        raw.poll.assert_not_called()

    def test_real_timeout_then_cleanup_reaps_exact_child(self):
        raw=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],start_new_session=True)
        child=process_scope.OwnedProcess(raw)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):child.wait(timeout=.03)
            with contextlib.redirect_stdout(io.StringIO()):self.assertTrue(process_scope.stop_group(child.pid,child))
            self.assertIsNotNone(child.returncode)
            with self.assertRaises(ChildProcessError):os.waitpid(child.pid,os.WNOHANG)
        finally:
            if raw.poll() is None:raw.kill();raw.wait(timeout=3)

    def test_exited_child_is_reaped_before_any_group_probe(self):
        raw,child=owned_mock();events=[]
        def reap():events.append('reap');raw.returncode=0;return 0
        def probe(group,kind):
            self.assertEqual(group,child.pid);self.assertEqual(kind,0)
            self.assertEqual(events[0],'reap');self.assertEqual(raw.returncode,0)
            events.append('probe');raise ProcessLookupError(errno.ESRCH,'gone')
        raw.poll.side_effect=reap
        with mock.patch.object(process_scope.os,'killpg',side_effect=probe),contextlib.redirect_stdout(io.StringIO()):self.assertTrue(process_scope.stop_group(child.pid,child))
        raw.wait.assert_not_called();self.assertIn('probe',events)

    def test_reused_group_after_reap_is_never_signaled(self):
        raw,child=owned_mock(0)
        with mock.patch.object(process_scope.os,'killpg',return_value=None) as killpg,mock.patch.object(process_scope.time,'monotonic',side_effect=[0,9]),mock.patch.object(process_scope,'membership_snapshot',return_value={'available':False,'rows':[]}),contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(process_scope.stop_group(child.pid,child))
        self.assertTrue(killpg.called);self.assertTrue(all(call.args==(child.pid,0) for call in killpg.call_args_list))

    def test_unowned_numeric_group_is_read_only(self):
        with mock.patch.object(process_scope.os,'killpg',return_value=None) as killpg,mock.patch.object(process_scope.time,'monotonic',side_effect=[0,9]),mock.patch.object(process_scope,'membership_snapshot',return_value={'available':False,'rows':[]}),contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(process_scope.stop_group(4321))
        self.assertTrue(killpg.called);self.assertTrue(all(call.args==(4321,0) for call in killpg.call_args_list))

    def test_wrong_or_raw_child_cannot_authorize_signals(self):
        raw,child=owned_mock()
        with mock.patch.object(process_scope.os,'killpg') as killpg:
            for process,group in [(raw,4321),(child,1234)]:
                with self.subTest(group=group),self.assertRaises(ValueError):process_scope.stop_group(group,process)
        killpg.assert_not_called()

    def test_leader_reaped_between_check_and_signal_is_not_signaled(self):
        raw,child=owned_mock(0);raw.poll.side_effect=[None,0,0]
        with mock.patch.object(process_scope,'alive',side_effect=[True,False,False]),mock.patch.object(process_scope,'signal_group') as send,contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(process_scope.stop_group(child.pid,child))
        send.assert_not_called();self.assertEqual(raw.poll.call_count,3)

    def test_esrch_does_not_claim_signal_was_delivered(self):
        raw,child=owned_mock()
        with mock.patch.object(process_scope.os,'killpg',side_effect=ProcessLookupError(errno.ESRCH,'gone')) as killpg:self.assertFalse(child.signal_owned(signal.SIGINT))
        killpg.assert_called_once_with(child.pid,signal.SIGINT)

    def test_wait_reap_blocks_competing_signal_until_lock_released(self):
        raw,child=owned_mock();entered=threading.Event();release=threading.Event();started=threading.Event();results={};errors=[]
        def poll():
            entered.set()
            if not release.wait(3):raise RuntimeError('test release timeout')
            raw.returncode=0;return 0
        raw.poll.side_effect=poll
        def wait():
            try:results['wait']=child.wait(timeout=2)
            except BaseException as error:errors.append(error)
        def stop():
            started.set()
            try:results['stop']=process_scope.stop_group(child.pid,child)
            except BaseException as error:errors.append(error)
        waiter=threading.Thread(target=wait);stopper=threading.Thread(target=stop)
        with mock.patch.object(process_scope.os,'killpg',side_effect=ProcessLookupError(errno.ESRCH,'gone')) as killpg,contextlib.redirect_stdout(io.StringIO()):
            try:
                waiter.start();self.assertTrue(entered.wait(2));stopper.start();self.assertTrue(started.wait(2));time.sleep(.03)
                self.assertEqual(raw.poll.call_count,1);killpg.assert_not_called()
            finally:
                release.set();waiter.join(3)
                if stopper.ident is not None:stopper.join(3)
        self.assertFalse(waiter.is_alive());self.assertFalse(stopper.is_alive());self.assertEqual(errors,[]);self.assertEqual(results,{'wait':0,'stop':True})
        self.assertTrue(all(call.args==(child.pid,0) for call in killpg.call_args_list))

    def test_signal_blocks_competing_reap_until_lock_released(self):
        raw,child=owned_mock();entered=threading.Event();release=threading.Event();started=threading.Event();results={};errors=[]
        def signal_group(group,kind):
            entered.set()
            if not release.wait(3):raise RuntimeError('test release timeout')
            raw.returncode=-kind;return True
        def send():
            try:results['signal']=child.signal_owned(signal.SIGTERM)
            except BaseException as error:errors.append(error)
        def wait():
            started.set()
            try:results['wait']=child.wait(timeout=2)
            except BaseException as error:errors.append(error)
        sender=threading.Thread(target=send);waiter=threading.Thread(target=wait)
        with mock.patch.object(process_scope,'signal_group',side_effect=signal_group):
            try:
                sender.start();self.assertTrue(entered.wait(2));waiter.start();self.assertTrue(started.wait(2));time.sleep(.03);self.assertEqual(raw.poll.call_count,1)
            finally:
                release.set();sender.join(3)
                if waiter.ident is not None:waiter.join(3)
        self.assertFalse(sender.is_alive());self.assertFalse(waiter.is_alive());self.assertEqual(errors,[]);self.assertEqual(results,{'signal':True,'wait':-signal.SIGTERM})

    def test_wait_releases_lock_between_short_polls(self):
        raw,child=owned_mock();entered=threading.Event();results=[];errors=[]
        def wait():
            entered.set()
            try:results.append(child.wait(timeout=2))
            except BaseException as error:errors.append(error)
        waiter=threading.Thread(target=wait);waiter.start()
        try:
            self.assertTrue(entered.wait(1));time.sleep(.03);acquired=child.lock.acquire(timeout=.2);self.assertTrue(acquired)
            if acquired:raw.returncode=0;child.lock.release()
        finally:raw.returncode=0;waiter.join(3)
        self.assertFalse(waiter.is_alive());self.assertEqual(results,[0]);self.assertEqual(errors,[])

    def test_persistent_probe_eperm_stays_failure_after_reap_attempt(self):
        raw,child=owned_mock()
        with mock.patch.object(process_scope.os,'killpg',side_effect=PermissionError(errno.EPERM,'denied')) as killpg,mock.patch.object(process_scope,'membership_snapshot',return_value={'available':False,'rows':[]}),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(process_scope.GroupOperationError) as raised:process_scope.stop_group(child.pid,child)
        self.assertEqual(raised.exception.diagnostic['errno'],errno.EPERM);self.assertEqual(raised.exception.diagnostic['operation'],'probe');self.assertEqual(raised.exception.diagnostic['pgid'],child.pid)
        killpg.assert_called_once_with(child.pid,0);self.assertGreaterEqual(raw.poll.call_count,2)

    def test_real_surviving_descendant_rejects_without_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();ready=root/'ready';stop=root/'stop';done=root/'done';writer=root/'writer'
            script=f"import time;from pathlib import Path;f=open({str(writer)!r},'a');end=time.monotonic()+20;Path({str(ready)!r}).write_text('ready');\nwhile not Path({str(stop)!r}).exists() and time.monotonic()<end:f.write('x');f.flush();time.sleep(.005)\nf.close();Path({str(done)!r}).write_text('done')"
            launcher=f'import subprocess,sys;subprocess.Popen([sys.executable,"-B","-c",{script!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)'
            raw=subprocess.Popen([sys.executable,'-B','-c',launcher],start_new_session=True);child=process_scope.OwnedProcess(raw);original=os.killpg
            try:
                self.assertEqual(child.wait(timeout=3),0);deadline=time.monotonic()+3
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists())
                with mock.patch.object(process_scope.os,'killpg',side_effect=original) as killpg,contextlib.redirect_stdout(io.StringIO()):
                    try:self.assertFalse(process_scope.stop_group(child.pid,child))
                    except process_scope.GroupOperationError as error:
                        # Darwin may deny the read-only orphan-group probe. No
                        # other exception, errno, operation, or PGID is accepted.
                        self.assertEqual(error.diagnostic['errno'],errno.EPERM);self.assertEqual(error.diagnostic['operation'],'probe');self.assertEqual(error.diagnostic['pgid'],child.pid)
                self.assertTrue(killpg.called);self.assertTrue(all(call.args==(child.pid,0) for call in killpg.call_args_list))
                before=writer.stat().st_size;time.sleep(.03);self.assertGreater(writer.stat().st_size,before)
            finally:
                stop.write_text('stop');deadline=time.monotonic()+3
                while ready.exists() and not done.exists() and time.monotonic()<deadline:time.sleep(.01)
                if raw.poll() is None:raw.kill();raw.wait(timeout=3)
                if ready.exists():self.assertTrue(done.exists(),'fixture descendant failed its own sentinel cleanup')


class ManagedVideoLifecycleTests(unittest.TestCase):
    def test_preexisting_sigint_exit_is_not_requested_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'screen.mp4').write_bytes(b'fixture');process=mock.Mock(returncode=-signal.SIGINT);process.signal_owned.return_value=False
            scope=mock.Mock();scope.spawn.return_value=process;recorder=capture.ManagedVideo(scope,'fixture-device',root)
            with self.assertRaises(ValueError):recorder.stop()
            process.wait.assert_not_called();scope.settle.assert_called_once_with(process)
            row=json.loads((root/'recording-process.json').read_text());self.assertFalse(row['sigintSent']);self.assertEqual(row['exitCode'],-signal.SIGINT);self.assertTrue(recorder.stream.closed)

    def test_real_requested_owned_sigint_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'screen.mp4').write_bytes(b'fixture');raw=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(30)'],start_new_session=True,stderr=subprocess.DEVNULL);child=process_scope.OwnedProcess(raw)
            scope=mock.Mock();scope.spawn.return_value=child;scope.settle.side_effect=lambda process:process_scope.stop_group(process.pid,process);recorder=capture.ManagedVideo(scope,'fixture-device',root)
            try:
                with contextlib.redirect_stdout(io.StringIO()):recorder.stop()
                self.assertEqual(raw.returncode,-signal.SIGINT);row=json.loads((root/'recording-process.json').read_text());self.assertTrue(row['sigintSent']);self.assertFalse(row['forcedTermination']);self.assertIsNone(row['primary_error']);self.assertEqual(row['cleanup_errors'],[])
            finally:
                if raw.poll() is None:raw.kill();raw.wait(timeout=3)
                recorder.stream.close()

    def test_signal_and_settle_failure_preserve_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();primary=PermissionError(errno.EPERM,'denied');process=mock.Mock(returncode=None);process.signal_owned.side_effect=primary
            scope=mock.Mock();scope.spawn.return_value=process;scope.settle.side_effect=RuntimeError('settle failed');recorder=capture.ManagedVideo(scope,'fixture-device',root)
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(PermissionError) as raised:recorder.stop()
            self.assertIs(raised.exception,primary);row=json.loads((root/'recording-process.json').read_text());self.assertEqual(row['primary_error'],{'type':'PermissionError','errno':errno.EPERM});self.assertEqual(row['cleanup_errors'],[{'type':'RuntimeError'}]);self.assertTrue(recorder.stream.closed)

    def test_forced_stop_keeps_thirty_and_ten_second_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'screen.mp4').write_bytes(b'fixture');process=mock.Mock(returncode=-signal.SIGKILL);process.signal_owned.return_value=True;process.wait.side_effect=[subprocess.TimeoutExpired('recorder',30),-signal.SIGKILL]
            scope=mock.Mock();scope.spawn.return_value=process;recorder=capture.ManagedVideo(scope,'fixture-device',root)
            with self.assertRaises(ValueError):recorder.stop()
            self.assertEqual(process.wait.call_args_list,[mock.call(timeout=30),mock.call(timeout=10)]);self.assertEqual(process.signal_owned.call_args_list,[mock.call(signal.SIGINT),mock.call(signal.SIGKILL)])
            self.assertTrue(json.loads((root/'recording-process.json').read_text())['forcedTermination'])

if __name__=='__main__':unittest.main()
