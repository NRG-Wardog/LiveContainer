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

class LaunchReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.logs=self.root/'commands';self.logs.mkdir()
        self.scope=process_scope.Scope(self.root);self.command=process_scope.Commands(self.scope,self.logs)
    def run_command(self,*args,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            result=self.command(*args,receipt=True,**kwargs)
        stored=json.loads((self.logs/'commands.jsonl').read_text().splitlines()[-1])
        self.assertEqual(result['launch_receipt'],stored['launch_receipt'])
        self.assertTrue(stored['launch_receipt']['closed'])
        return result
    def assert_settled(self):
        with contextlib.redirect_stdout(io.StringIO()):self.scope.close()
        self.assertTrue(all(r['settled'] and r['reaped'] for r in self.scope.rows))
        for row in self.scope.rows:
            with self.assertRaises(ChildProcessError):os.waitpid(row['pid'],os.WNOHANG)
    def observer(self):
        observer=process_scope.LaunchReceipt(1,time.monotonic()+5,5)
        reader,writer=os.pipe();os.set_blocking(reader,False);os.set_blocking(writer,False)
        observer.bind('a'*32,reader);observer.row['pid']=4321
        observer.row['popen']['before']=time.monotonic();observer.row['release']['before']=time.monotonic()
        self.addCleanup(observer.finish);self.addCleanup(lambda:self.close_fd(writer))
        return observer,writer
    @staticmethod
    def close_fd(fd):
        try:os.close(fd)
        except OSError:pass
    def frame(self,observer,**changes):
        fields=dict(magic=process_scope.LAUNCH_MAGIC,kind=1,pid=4321,pgid=4321,sid=4321,session=b'\xaa'*16,command=1,first_python=observer.row['popen']['before'],imports_complete=observer.row['popen']['before'],gate_enter=observer.row['release']['before'],gate_exit=observer.row['release']['before'],stamp=time.monotonic(),number=0)
        fields.update(changes)
        return process_scope.LAUNCH_RECORD.pack(*fields.values())
    def test_real_command_retains_ordered_parent_and_child_receipts(self):
        result=self.run_command(sys.executable,'-B','-c','print("ok")',timeout=3)
        self.assertEqual(result['stdout'],'ok\n');self.assertIsNone(result['failure_type'])
        row=result['launch_receipt'];self.assertEqual(row['state'],'pre-exec-observed');self.assertTrue(row['eof'])
        self.assertEqual(row['session'],self.scope.session);self.assertEqual(row['pid'],self.scope.rows[0]['pid'])
        self.assertFalse(row['target_execution_observed']);self.assertFalse(row['service_execution_observed'])
        popen,registration,release=(row[k] for k in ['popen','registration','release'])
        self.assertTrue(popen['returned']);self.assertTrue(registration['durable']);self.assertTrue(release['issued'])
        self.assertLessEqual(popen['before'],popen['after']);self.assertLessEqual(popen['after'],registration['before'])
        self.assertLessEqual(registration['before'],registration['after']);self.assertLessEqual(registration['after'],release['before'])
        self.assertLessEqual(release['before'],row['pre_exec']['child_monotonic']);self.assertLessEqual(row['pre_exec']['child_monotonic'],row['pre_exec']['observed_after'])
        self.assertLessEqual(row['pre_exec']['observed_after'],row['deadline']);self.assertIsNone(row['exec_failure'])
        self.assert_settled()
    def test_real_exec_failure_retains_errno_without_exception_text(self):
        secret=str(self.root/'private-missing-token')
        result=self.run_command(secret,timeout=3);row=result['launch_receipt']
        self.assertEqual(result['exit_code'],126);self.assertEqual(result['failure_type'],'CalledProcessError')
        self.assertEqual(row['exec_failure']['errno'],errno.ENOENT);self.assertEqual(row['state'],'pre-exec-observed')
        self.assertEqual(result['stderr'],'');self.assertNotIn(secret,json.dumps(row));self.assert_settled()
    def test_receipt_descriptor_is_closed_on_exec(self):
        script="import os;extra=[]\nfor fd in range(3,64):\n try:os.fstat(fd);extra.append(fd)\n except OSError:pass\nprint(extra)"
        result=self.run_command(sys.executable,'-B','-c',script,timeout=3)
        self.assertEqual(result['stdout'],'[]\n');self.assertIsNone(result['failure_type']);self.assert_settled()
    def test_delayed_registration_uses_original_deadline_without_release(self):
        original=self.scope.persist;target=self.root/'must-not-run';once=[True]
        def persist():
            if once[0]:once[0]=False;time.sleep(.08)
            original()
        with mock.patch.object(self.scope,'persist',side_effect=persist):
            result=self.run_command(sys.executable,'-B','-c',f'open({str(target)!r},"w").close()',timeout=.03)
        self.assertEqual(result['failure_type'],'TimeoutExpired');row=result['launch_receipt']
        self.assertTrue(row['registration']['durable']);self.assertGreater(row['registration']['after'],row['deadline'])
        self.assertFalse(row['release']['issued']);self.assertIsNone(row['pre_exec']);self.assertFalse(target.exists());self.assert_settled()
    def test_registration_failure_preserves_brackets_and_primary(self):
        primary=OSError(errno.ENOSPC,'private-path');original=self.scope.persist;once=[True]
        def persist():
            if once[0]:once[0]=False;raise primary
            original()
        with mock.patch.object(self.scope,'persist',side_effect=persist):result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.ENOSPC})
        row=result['launch_receipt'];self.assertIsNotNone(row['registration']['after']);self.assertFalse(row['registration']['durable'])
        self.assertFalse(row['release']['issued']);self.assertIsNone(row['pre_exec']);self.assertNotIn('private-path',json.dumps(row));self.assert_settled()
    def test_popen_failure_closes_every_pipe_and_preserves_primary(self):
        original=os.pipe;fds=[]
        def pipe():
            pair=original();fds.extend(pair);return pair
        with mock.patch.object(process_scope.os,'pipe',side_effect=pipe),mock.patch.object(process_scope.OwnedProcess,'spawn',side_effect=OSError(errno.EMFILE,'private-path')):
            result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.EMFILE});self.assertEqual(result['cleanup_errors'],[])
        row=result['launch_receipt'];self.assertIsNotNone(row['popen']['before']);self.assertIsNotNone(row['popen']['after']);self.assertFalse(row['popen']['returned'])
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertEqual(self.scope.rows,[]);self.assert_settled()
    def test_closed_reader_makes_child_fail_before_exec(self):
        observer=process_scope.LaunchReceipt(1,time.monotonic()+3,3);target=self.root/'must-not-run'
        original=self.scope.persist
        def persist():
            original();os.close(observer.fd);observer.fd=None
        with (self.root/'stdout').open('wb') as stream,mock.patch.object(self.scope,'persist',side_effect=persist):
            child=self.scope.spawn([sys.executable,'-B','-c',f'open({str(target)!r},"w").close()'],stream,launch=observer)
        child.wait(timeout=3);observer.finish()
        with contextlib.redirect_stdout(io.StringIO()):self.scope.settle(child)
        self.assertEqual(child.returncode,125);self.assertFalse(target.exists());self.assertEqual(observer.row['state'],'unknown');self.assert_settled()
    def test_malformed_identity_order_time_and_overflow_are_unknown(self):
        cases=[('magic',{'magic':b'junk'}),('pid',{'pid':99}),('pgid',{'pgid':99}),('sid',{'sid':99}),
               ('session',{'session':b'\xbb'*16}),('command',{'command':2}),('kind',{'kind':3}),
               ('errno-before-preexec',{'kind':2,'number':errno.ENOENT}),('preexec-errno',{'number':1}),
               ('nan',{'stamp':float('nan')}),('future',{'stamp':time.monotonic()+100}),('past',{'stamp':0})]
        for label,change in cases:
            with self.subTest(label=label):
                observer,writer=self.observer();os.write(writer,self.frame(observer,**change));os.close(writer);observer.finish()
                with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
                self.assertEqual(observer.row['state'],'unknown');self.assertTrue(observer.row['closed'])
        for label,payload in [('duplicate',None),('overflow',b'x'*(2*process_scope.LAUNCH_RECORD.size+1)),('partial',b'P1L1'),('missing',b'')]:
            with self.subTest(label=label):
                observer,writer=self.observer();payload=payload if payload is not None else self.frame(observer)*2
                os.write(writer,payload);os.close(writer);observer.finish()
                with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
                self.assertTrue(observer.row['closed'])
    def test_fragmented_receipt_is_bounded_and_valid_only_after_eof(self):
        observer,writer=self.observer();frame=self.frame(observer)
        os.write(writer,frame[:7]);observer.observe();self.assertIsNone(observer.row['pre_exec'])
        os.write(writer,frame[7:]);observer.observe();self.assertIsNotNone(observer.row['pre_exec'])
        with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
        os.close(writer);observer.finish();observer.require()
        self.assertEqual(len(observer.raw),process_scope.LAUNCH_RECORD.size)
    def test_late_observation_cannot_promote_prior_child_timestamp(self):
        observer,writer=self.observer();frame=self.frame(observer);observer.deadline=time.monotonic()-.001
        os.write(writer,frame);os.close(writer);observer.finish()
        self.assertEqual(observer.row['reason'],'late-observation')
        with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
    def test_unknown_writer_never_gets_an_extra_wait(self):
        observer,writer=self.observer();os.write(writer,self.frame(observer));start=time.monotonic();observer.finish()
        self.assertLess(time.monotonic()-start,.1);self.assertEqual(observer.row['reason'],'unresolved-writer')
        with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
        with self.assertRaises(OSError):os.fstat(observer.fd if observer.fd is not None else -1)
    def test_pre_exec_observation_survives_later_timeout_and_settlement(self):
        result=self.run_command(sys.executable,'-B','-c','import time;time.sleep(30)',timeout=.15)
        self.assertEqual(result['failure_type'],'TimeoutExpired');self.assertEqual(result['launch_receipt']['state'],'pre-exec-observed')
        self.assertEqual(result['cleanup_errors'],[]);self.assert_settled()
    def test_missing_receipt_with_optional_failure_retains_observer_cleanup_error(self):
        original=self.scope.spawn
        def spawn(*args,**kwargs):
            observer=kwargs.pop('launch');child=original(*args,**kwargs)
            observer.row['pid']=child.pid
            return child
        with mock.patch.object(self.scope,'spawn',side_effect=spawn):result=self.run_command('/bin/true',allow_failure=True,timeout=3)
        self.assertEqual(result['failure_type'],'LaunchReceiptError');self.assertEqual(result['cleanup_errors'],[{'type':'LaunchReceiptError'}])
        self.assertEqual(result['launch_receipt']['state'],'unknown');self.assert_settled()
    def test_unresolved_settlement_is_not_hidden_by_valid_launch_receipt(self):
        original=self.scope.settle
        with mock.patch.object(self.scope,'settle',side_effect=PermissionError(errno.EPERM,'unknown group')):
            result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['launch_receipt']['state'],'pre-exec-observed');self.assertEqual(result['failure_type'],'PermissionError')
        self.assertEqual(result['cleanup_errors'],[{'type':'PermissionError','errno':errno.EPERM}]);self.assertFalse(self.scope.rows[0]['settled'])
        with contextlib.redirect_stdout(io.StringIO()):original(self.scope.processes[self.scope.rows[0]['pid']])
        self.assert_settled()

    def test_child_death_before_release_preserves_release_failure(self):
        original=self.scope.persist
        def persist():
            original();child=next(iter(self.scope.processes.values()))
            child.signal_owned(signal.SIGKILL);child.wait(timeout=3)
        with mock.patch.object(self.scope,'persist',side_effect=persist):result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['failure_type'],'BrokenPipeError');row=result['launch_receipt']
        self.assertTrue(row['registration']['durable']);self.assertFalse(row['release']['issued'])
        self.assertIsNotNone(row['release']['after']);self.assertIsNone(row['pre_exec']);self.assert_settled()
    def child_substitution(self, body):
        original=process_scope.OwnedProcess.spawn
        def spawn(argv,**kwargs):
            script=f'import sys;sys.path.insert(0,{str(HERE)!r});import process_scope,os;'+body
            return original([sys.executable,'-B','-c',script,*argv[3:]],**kwargs)
        return mock.patch.object(process_scope.OwnedProcess,'spawn',side_effect=spawn)
    def test_child_death_after_release_before_preexec_is_unknown(self):
        with self.child_substitution('os.read(int(sys.argv[2]),1);os._exit(0)'):
            result=self.run_command('/bin/true',timeout=3)
        row=result['launch_receipt'];self.assertTrue(row['release']['issued']);self.assertTrue(row['eof'])
        self.assertEqual(row['reason'],'missing-pre-exec');self.assertEqual(result['failure_type'],'LaunchReceiptError');self.assert_settled()
    def test_child_death_after_preexec_never_claims_target_started(self):
        with self.child_substitution('process_scope.os.execvp=lambda *args:os._exit(7);process_scope.child_main(sys.argv[1:])'):
            result=self.run_command('/bin/true',timeout=3)
        row=result['launch_receipt'];self.assertEqual(row['state'],'pre-exec-observed')
        self.assertFalse(row['target_execution_observed']);self.assertIsNone(row['exec_failure'])
        self.assertEqual(result['exit_code'],7);self.assertEqual(result['failure_type'],'CalledProcessError');self.assert_settled()
    def test_nonblocking_child_pipe_failure_does_not_exec_or_retry(self):
        for result in [BlockingIOError(errno.EAGAIN,'full pipe'),1]:
            with self.subTest(result=result),mock.patch.object(process_scope.os,'read',return_value=b'G'),mock.patch.object(process_scope.os,'close'),mock.patch.object(process_scope.os,'set_inheritable'),mock.patch.object(process_scope.os,'write',side_effect=result if isinstance(result,Exception) else None,return_value=result) as write,mock.patch.object(process_scope.os,'execvp') as execute,mock.patch.object(process_scope.os,'_exit',side_effect=SystemExit(125)):
                with self.assertRaises(SystemExit) as raised:process_scope.child_main(['--child','41','--launch-receipt','42','a'*32,'1','/bin/true'])
                self.assertEqual(raised.exception.code,125);execute.assert_not_called();write.assert_called_once()
    def test_pipe_setup_failure_closes_first_pipe_without_child(self):
        original=os.pipe;first=original();calls=iter([first,OSError(errno.EMFILE,'descriptor limit')])
        def pipe():
            value=next(calls)
            if isinstance(value,Exception):raise value
            return value
        with mock.patch.object(process_scope.os,'pipe',side_effect=pipe),mock.patch.object(process_scope.OwnedProcess,'spawn') as spawn:
            result=self.run_command('/bin/true',timeout=3)
        spawn.assert_not_called();self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.EMFILE})
        for fd in first:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assert_settled()

    def test_time_between_remaining_and_start_does_not_extend_scope_deadline(self):
        self.scope.deadline=time.monotonic()+.20;original=self.scope.remaining;once=[True]
        def remaining(*args,**kwargs):
            value=original(*args,**kwargs)
            if once[0]:once[0]=False;time.sleep(.08)
            return value
        with mock.patch.object(self.scope,'remaining',side_effect=remaining):
            result=self.run_command(sys.executable,'-B','-c','import time;time.sleep(30)',timeout=3)
        self.assertEqual(result['launch_receipt']['deadline'],self.scope.deadline)
        self.assertEqual(result['failure_type'],'TimeoutExpired');self.assert_settled()
    def test_cleanup_retains_its_independent_existing_allowance(self):
        self.scope.deadline=time.monotonic()-10;self.scope.closing=True
        result=self.run_command('/bin/true',timeout=3,cleanup=True)
        self.assertIsNone(result['failure_type']);self.assertGreater(result['launch_receipt']['deadline'],self.scope.deadline);self.assert_settled()
    def test_unexpected_final_observer_failure_cannot_skip_settlement(self):
        original=process_scope.LaunchReceipt.finish
        def finish(observer):original(observer);raise ValueError('synthetic observer failure')
        with mock.patch.object(process_scope.LaunchReceipt,'finish',side_effect=finish,autospec=True):
            result=self.run_command(sys.executable,'-B','-c','import time;time.sleep(30)',timeout=.15)
        self.assertEqual(result['failure_type'],'TimeoutExpired');self.assertEqual(result['primary_error']['type'],'TimeoutExpired')
        self.assertEqual(result['cleanup_errors'],[{'type':'ValueError'}]);self.assert_settled()
    def test_unexpected_receipt_serialization_failure_preserves_timeout_after_settlement(self):
        original=json.dumps
        def dumps(row,*args,**kwargs):
            if isinstance(row,dict) and 'timeoutSeconds' in row:raise ValueError('synthetic serialization failure')
            return original(row,*args,**kwargs)
        with mock.patch.object(process_scope.json,'dumps',side_effect=dumps),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.TimeoutExpired):self.command(sys.executable,'-B','-c','import time;time.sleep(30)',timeout=.15)
        self.assertTrue(self.scope.rows[0]['launch_receipt']['closed']);self.assert_settled()

    def test_allowed_exec_failure_keeps_errno_and_cannot_satisfy_mandatory_command(self):
        result=self.run_command(str(self.root/'missing-optional'),allow_failure=True,timeout=3)
        self.assertEqual(result['failure_type'],'CalledProcessError');self.assertEqual(result['exit_code'],126)
        self.assertEqual(result['launch_receipt']['exec_failure']['errno'],errno.ENOENT)
        self.assertEqual(result['cleanup_errors'],[])
        capture.require(not result['cleanup_errors'] and all(r.get('settled') is True for r in self.scope.rows),'optional uninstall writer settlement unproved')
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(subprocess.CalledProcessError):
            self.command(str(self.root/'missing-mandatory-install'),timeout=3)
        rows=[json.loads(line) for line in (self.logs/'commands.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),2);self.assertFalse(rows[1]['allowed_failure'])
        self.assertEqual(rows[1]['launch_receipt']['exec_failure']['errno'],errno.ENOENT);self.assert_settled()
    def test_allowed_exec_failure_never_bypasses_uninstall_settlement_guard(self):
        with mock.patch.object(self.scope,'settle',side_effect=PermissionError(errno.EPERM,'unknown writer')):
            result=self.run_command(str(self.root/'missing-optional'),allow_failure=True,timeout=3)
        self.assertEqual(result['failure_type'],'CalledProcessError');self.assertEqual(result['launch_receipt']['exec_failure']['errno'],errno.ENOENT)
        with self.assertRaisesRegex(ValueError,'writer settlement unproved'):
            capture.require(not result['cleanup_errors'] and all(r.get('settled') is True for r in self.scope.rows),'optional uninstall writer settlement unproved')
        self.assertEqual(self.command.count,1);self.assert_settled()

    def test_reader_close_error_stays_unknown_and_never_claims_closed(self):
        observer,writer=self.observer();os.write(writer,self.frame(observer));os.close(writer);reader=observer.fd;original=os.close
        def close(fd):
            if fd==reader:raise OSError(errno.EIO,'close status unknown')
            original(fd)
        try:
            with mock.patch.object(process_scope.os,'close',side_effect=close):observer.finish()
            self.assertEqual(observer.row['state'],'unknown');self.assertEqual(observer.row['reason'],'close-error');self.assertFalse(observer.row['closed'])
            observer.finish();self.assertFalse(observer.row['closed'])
            with self.assertRaises(process_scope.LaunchReceiptError):observer.require()
        finally:original(reader)

    def test_parent_close_failures_retain_owned_child_and_settle_before_return(self):
        for which in [0,3,1]:  # Gate reader, receipt writer, released gate writer.
            with self.subTest(which=which):
                root=self.root/str(which);root.mkdir();logs=root/'commands';logs.mkdir();scope=process_scope.Scope(root);command=process_scope.Commands(scope,logs)
                pipe=os.pipe;close=os.close;fds=[];failed=[];closed=[]
                def make_pipe():
                    pair=pipe();fds.extend(pair);return pair
                def close_fd(fd):
                    if len(fds)>=4 and fd==fds[which] and not failed:
                        self.assertEqual(len(scope.processes),1);self.assertEqual(len(scope.rows),1)
                        failed.append(fd);close(fd);closed.append(fd)
                        raise OSError(errno.EIO,'synthetic parent close failure')
                    close(fd);closed.append(fd)
                with mock.patch.object(process_scope.os,'pipe',side_effect=make_pipe),mock.patch.object(process_scope.os,'close',side_effect=close_fd),contextlib.redirect_stdout(io.StringIO()):
                    result=command('/bin/true',timeout=3,receipt=True,allow_failure=True)
                self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.EIO})
                self.assertEqual(len(scope.rows),1);row=scope.rows[0]
                self.assertTrue(row['spawn_cleanup_settled']);self.assertTrue(row['reaped']);self.assertFalse(row['settled'])
                with self.assertRaises(ChildProcessError):os.waitpid(row['pid'],os.WNOHANG)
                self.assertEqual(closed.count(failed[0]),1)
                with self.assertRaisesRegex(ValueError,'writer settlement unproved'):
                    capture.require(not result['cleanup_errors'] and all(r.get('settled') is True for r in scope.rows),'optional uninstall writer settlement unproved')
                for fd in fds:
                    with self.assertRaises(OSError):os.fstat(fd)
                with contextlib.redirect_stdout(io.StringIO()):scope.close()
                self.assertTrue(scope.rows[0]['settled'])
    def test_finally_close_failure_never_masks_original_popen_error(self):
        pipe=os.pipe;close=os.close;fds=[];failed=[]
        def make_pipe():
            pair=pipe();fds.extend(pair);return pair
        def close_fd(fd):
            close(fd)
            if fds and fd==fds[0] and not failed:
                failed.append(fd);raise OSError(errno.EIO,'synthetic finally close failure')
        with mock.patch.object(process_scope.os,'pipe',side_effect=make_pipe),mock.patch.object(process_scope.os,'close',side_effect=close_fd),mock.patch.object(process_scope.OwnedProcess,'spawn',side_effect=OSError(errno.EMFILE,'original spawn failure')):
            result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.EMFILE});self.assertEqual(self.scope.rows,[])
        self.assertEqual(len(failed),1)
        for fd in fds:
            with self.assertRaises(OSError):os.fstat(fd)
        self.assert_settled()
    def test_registration_and_finally_close_errors_retain_primary_and_child(self):
        pipe=os.pipe;close=os.close;persist=self.scope.persist;fds=[];failed=[];once=[True]
        def make_pipe():
            pair=pipe();fds.extend(pair);return pair
        def close_fd(fd):
            close(fd)
            if len(fds)>=4 and fd==fds[1] and not failed:
                failed.append(fd);raise OSError(errno.EIO,'synthetic finally close failure')
        def persist_once():
            if once[0]:once[0]=False;raise OSError(errno.ENOSPC,'original registration failure')
            persist()
        with mock.patch.object(process_scope.os,'pipe',side_effect=make_pipe),mock.patch.object(process_scope.os,'close',side_effect=close_fd),mock.patch.object(self.scope,'persist',side_effect=persist_once):
            result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.ENOSPC})
        self.assertEqual(self.scope.rows[0]['cleanup_errors'],[{'type':'OSError','errno':errno.EIO}])
        self.assertTrue(self.scope.rows[0]['spawn_cleanup_settled']);self.assertTrue(self.scope.rows[0]['reaped']);self.assert_settled()
    def test_close_failure_with_unresolved_settlement_retains_child_for_final_cleanup(self):
        pipe=os.pipe;close=os.close;fds=[];failed=[]
        def make_pipe():
            pair=pipe();fds.extend(pair);return pair
        def close_fd(fd):
            close(fd)
            if len(fds)>=4 and fd==fds[0] and not failed:
                failed.append(fd);raise OSError(errno.EIO,'synthetic parent close failure')
        with mock.patch.object(process_scope.os,'pipe',side_effect=make_pipe),mock.patch.object(process_scope.os,'close',side_effect=close_fd),mock.patch.object(process_scope,'stop_group',return_value=False):
            result=self.run_command('/bin/true',timeout=3)
        self.assertEqual(result['primary_error'],{'type':'OSError','errno':errno.EIO})
        row=self.scope.rows[0];self.assertFalse(row['settled']);self.assertFalse(row['spawn_cleanup_settled'])
        self.assertEqual(row['cleanup_errors'],[{'type':'RuntimeError'}]);self.assertIn(row['pid'],self.scope.processes)
        self.assert_settled()
    def test_older_python_clock_fails_before_any_pipe_or_child(self):
        with mock.patch.object(process_scope.sys,'version_info',(3,9,99)),mock.patch.object(process_scope.os,'pipe') as pipe,mock.patch.object(process_scope.OwnedProcess,'spawn') as spawn:
            with self.assertRaisesRegex(ValueError,'shared host monotonic clock'):self.command('/bin/true',timeout=3)
        pipe.assert_not_called();spawn.assert_not_called();self.assert_settled()


if __name__=='__main__':unittest.main()

class ReceiptFinalizationLock(unittest.TestCase):
    def test_timeout_finalization_waits_for_retained_owner_handoff(self):
        import threading
        from types import SimpleNamespace
        import process_scope as ps
        waited=threading.Event();finished=threading.Event();lock=threading.RLock();result=[]
        process=SimpleNamespace(pid=12345,returncode=None,lock=lock)
        def wait(timeout):
            waited.set();raise subprocess.TimeoutExpired(['synthetic'],timeout)
        process.wait=wait
        class Receipt:
            def __init__(self,*args):self.row={};self.deadline=args[1]
            def finish(self):finished.set()
            def require(self):pass
        scope=SimpleNamespace(deadline=time.monotonic()+10,remaining=lambda cap,cleanup=False:cap,
                              spawn=lambda *a,**k:process,settle=lambda p:None)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ps,'LaunchReceipt',Receipt):
            command=ps.Commands(scope,Path(tmp).resolve())
            with lock:
                thread=threading.Thread(target=lambda:result.append(command('synthetic',timeout=1,receipt=True)))
                thread.start();observed_wait=waited.wait(1)
                raced=finished.wait(.05)
            thread.join(2);self.assertFalse(thread.is_alive());self.assertTrue(finished.is_set())
            self.assertTrue(observed_wait);self.assertFalse(raced,'timeout finalizer raced retained owner lock')
        self.assertEqual(result[0]['failure_type'],'TimeoutExpired');self.assertTrue(result[0]['writer_settled'])
