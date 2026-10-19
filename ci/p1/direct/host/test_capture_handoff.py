"""Local descriptor/raster integration, never native capture or P1 evidence.

The real reviewed Scope, OwnedGUI, OwnedProcess, LaunchReceipt, Commands,
RetainedCommand, Directory, Journal and registration bridge all execute. Only
subprocess.Popen is replaced: its in-memory children consume the real launch
pipe and emit synthetic fixed-format receipt bytes. No application, compiler,
simulator or native helper executes. A test-only executable byte sentinel and
explicit synthetic raster model stand in for native compiler/capture output.
There are no ownership/decoder/source-validation monkeypatches. Process cleanup
may probe the impossible synthetic PID with signal 0; it never sends a signal.
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import os
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import capture_handoff as handoff
import case_budget
import native_process
import native_case
from native_channels import Channels
from fixture_channel import Directory, canonical, parse
from journal import Journal

LOCAL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(LOCAL / 'pixels'), str(handoff.PREFLIGHT)]
import registration_bridge as bridge
import test_registration_bridge as raster_fixtures
import window_capture

PS = window_capture.process_scope
# Deterministically render actual BGRA bytes; no retained binary fixture is needed.
RAW, STRIDE = raster_fixtures.e.render(tiny_features=True, strip=True)
WIDTH, HEIGHT = raster_fixtures.e.WIDTH, raster_fixtures.e.HEIGHT
RAW_SHA256 = 'e46ecacc4069cf0dd077819e5b8a76c3cdefba8799062e9984975122718063c2'
PACKED_SHA256 = '4c4b3b5f85bbc7cecae537a484e434b9a01e259e75a59b5af74cb7f8f537e24f'
REGIONS_SHA256 = '32cdbaa39505bc6c53c14a0487f7d7967e073a865d2296cf3cc069d82a145268'
SESSION = raster_fixtures.e.SESSION
WINDOW_ID = 99


class InMemoryPopen:
    """Models only Popen/launch-gate transport; does not run child code."""
    next_pid = 1_000_000_000

    def __init__(self, args, *, stdout, stderr, start_new_session, pass_fds):
        if not start_new_session or len(pass_fds) != 2:
            raise AssertionError('test children require the unchanged owned launch gate')
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.args = args
        self.returncode = None
        self.exit_requested = False
        self.gate_fd = os.dup(pass_fds[0])
        self.receipt_fd = os.dup(pass_fds[1])
        self.first_python = time.monotonic()
        offset = args.index('--launch-receipt')
        self.session = bytes.fromhex(args[offset + 2])
        self.command = int(args[offset + 3])
        self.target = args[offset + 4:]
        self.auto_exit = self.target[:2] == ['xcrun', 'swiftc']
        self.emitted = False

    def poll(self):
        if not self.emitted:
            if os.read(self.gate_fd, 1) != b'G':
                raise AssertionError('parent did not release the original launch gate')
            stamp = time.monotonic()
            record = PS.LAUNCH_RECORD.pack(PS.LAUNCH_MAGIC, 1, self.pid, self.pid, self.pid,
                self.session, self.command, self.first_python, self.first_python,
                self.first_python, stamp, stamp, 0)
            if os.write(self.receipt_fd, record) != len(record):
                raise AssertionError('synthetic launch record short write')
            os.close(self.receipt_fd); self.receipt_fd = None
            os.close(self.gate_fd); self.gate_fd = None
            self.emitted = True
        if self.auto_exit or self.exit_requested:
            self.returncode = 0
        return self.returncode

    def close_fds(self):
        for name in ('gate_fd', 'receipt_fd'):
            descriptor = getattr(self, name)
            if descriptor is not None:
                os.close(descriptor); setattr(self, name, None)


class LocalCase:
    """Creates real original class instances and only local descriptor files."""
    def __init__(self, *, construct=True, request_mutator=None, budget_mutator=None):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.children = []
        self.helper = None
        self.native = None
        self.handoff = None
        self.directories = []
        self.retained = {}
        self.raw_command_receipts = []
        self.stack.enter_context(patch.object(PS.subprocess, 'Popen', side_effect=self.popen))
        try:
            scope_root = self.root / 'scope'; scope_root.mkdir()
            self.scope = PS.Scope(scope_root, phone_ui=True)
            self.request = raster_fixtures.request()
            self.request['runnerBundleIdentifier'] = 'org.sidestore.fixture.p1video.uitests.xctrunner'
            if request_mutator is not None:
                request_mutator(self.request)
            self.request_bytes = canonical(self.request)
            self.device = self.request['simulatorUDID']
            fresh = window_capture.fresh_device
            intent = dict(schema='p1-created-device-v1', session=self.scope.session,
                name='P1-stall-' + self.scope.session, runtime=fresh.boot.RUNTIME,
                device_type=fresh.TYPE, type_verified=True, preexisting=[fresh.reference('phone')])
            self.scope.begin_creation(intent)
            self.scope.fixture_created(dict(intent, device=self.device, create_complete=True))
            self.binary = self.root / 'synthetic-helper'
            self.binary.write_bytes(b'LOCAL TEST ONLY: no native executable was produced\n')
            self.binary.chmod(0o700)
            command_root = self.root / 'compile-command'; command_root.mkdir()
            self.compile_argv = ['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library',
                str(LOCAL / 'capture/direct_capture.swift'), '-o', str(self.binary)]
            self.source_before_compile = sha256((LOCAL/'capture/direct_capture.swift').read_bytes()).hexdigest()
            self.compile_receipt = PS.Commands(self.scope, command_root)(*self.compile_argv,
                timeout=60, receipt=True)
            self.compile_bytes = canonical(self.compile_receipt)
            self.compiled = handoff.bind_compilation(LOCAL / 'capture/direct_capture.swift',
                self.binary, self.compile_bytes, scope=self.scope,
                expected_source_sha256=self.source_before_compile)
            self.frame_path = self.root / 'frames'
            self.target = handoff.prepare_capture_target(self.frame_path)
            self.track_target()
            self.gui = window_capture.OwnedGUI(self.scope, self.device, self.root / 'gui')
            self.gui.start()
            start = time.monotonic_ns()
            self.budget = case_budget.construct(dict(hostBeforeNs=start, hostAfterNs=start,
                machTicks=start, timebaseNumer=1, timebaseDenom=1), 360_000_000_000)
            if budget_mutator is not None:
                budget_mutator(self.budget)
            helper_argv = [str(self.binary), str(self.gui.process.pid), window_capture.SIMULATOR,
                str(self.frame_path), SESSION, str(self.budget['observationDeadlineMach']),
                str(self.budget['cleanupDeadlineMach'])]
            self.helper = native_process.RetainedCommand(self.scope, PS.Commands,
                self.root / 'helper-command', helper_argv, timeout=120,
                retain=self.raw_command_receipts.append)
            self.helper.start()
            deadline = time.monotonic() + 2
            while self.helper.process is None and not self.helper.finished.is_set() and time.monotonic() < deadline:
                time.sleep(.001)
            if self.helper.process is None:
                raise AssertionError('in-memory owned helper was not registered')
            self.container_roots = {'app': self.root/'app-container', 'runner': self.root/'runner-container'}
            runner_path = self.container_roots['runner']/'Documents/p1-capability'/SESSION
            journal_path = self.container_roots['app']/'Documents/p1-video/timeout'
            runner_path.mkdir(parents=True); journal_path.mkdir(parents=True)
            (runner_path/'geometry.json').write_bytes(self.request_bytes)
            ready = dict(schema='p1-direct-baseline-ready-v1', session=SESSION,
                geometryFile='geometry.json', acknowledgementFile='request.json', admissionEligible=False,
                geometryRequestSHA256=sha256(self.request_bytes).hexdigest())
            (runner_path/'ready.json').write_bytes(canonical(ready))
            for name, raw in raster_fixtures.event_files():
                (journal_path/name).write_bytes(raw)
            native_argv = native_case.native_argv(dict(device=self.device,
                xctestrun=str(self.root/'synthetic.xctestrun'), resultBundle=str(self.root/'synthetic.xcresult')))
            self.native = native_process.RetainedCommand(self.scope, PS.Commands,
                self.root/'native-command', native_argv, timeout=120, retain=self.raw_command_receipts.append)
            self.native.start()
            discovery_root = self.root/'discovery-command'; discovery_root.mkdir()
            self.channel_retained = {}
            self.channels = Channels(PS.Commands(self.scope, discovery_root), self.native,
                device=self.device, session=SESSION, app_id='org.sidestore.fixture.p1video',
                runner_id=self.request['runnerBundleIdentifier'],
                retain=lambda name,raw:self.channel_retained.__setitem__(name,raw), remaining=self.scope.remaining)
            self.channels.started(2)
            self.channels.discover('app',2); self.channels.discover('runner',2)
            self.channels.geometry(2,bridge.handoff.validate_request)
            self.runner = self.channels.directories['runner']
            self.directories.extend(self.channels.directories.values())
            self.journal_retained = []
            self.journal = Journal(self.channels.directories['app'], checkpoint=lambda: None,
                remaining=self.scope.remaining, retain=self.journal_retained.append)
            if construct:
                self.construct()
        except BaseException:
            self.close()
            raise

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def popen(self, *args, **kwargs):
        child = InMemoryPopen(*args, **kwargs)
        self.children.append(child)
        if child.target[:3] == ['xcrun','simctl','get_app_container']:
            role = 'runner' if child.target[4].endswith('.xctrunner') else 'app'
            kwargs['stdout'].write((str(self.container_roots[role])+'\n').encode()); kwargs['stdout'].flush()
            child.auto_exit = True
        elif child.target[:2] == ['xcodebuild','test-without-building']:
            kwargs['stdout'].write(b"Test Case '-[P0SignInUITests.P0SignInUITests testProbeTimeoutPixels]' started.\n")
            kwargs['stdout'].flush()
        return child

    def directory(self, path):
        directory = Directory(path); self.directories.append(directory)
        return directory

    def track_target(self):
        for value in vars(self.target).values():
            if type(value) is Directory:
                self.directories.append(value)

    def retain(self, name, raw):
        if name in self.retained:
            raise AssertionError('retention callback must be one-shot')
        self.retained[name] = raw

    def construct(self, **changes):
        arguments = dict(scope=self.scope, gui=self.gui, helper=self.helper,
            compiled=self.compiled, target=self.target, frame_path=self.frame_path,
            geometry_request_bytes=self.request_bytes, runner_directory=self.runner,
            journal=self.journal, channels=self.channels, budget=self.budget, bridge=bridge, window_capture=window_capture,
            remaining=self.scope.remaining, retain=self.retain,
            expected_bridge_sources=bridge.source_hashes(), expected_host_sources=handoff.source_hashes())
        arguments.update(changes)
        self.handoff = handoff.CaptureHandoff(**arguments)
        return self.handoff

    def write(self, name, value):
        raw = value if type(value) is bytes else canonical(value)
        (self.frame_path / name).write_bytes(raw)
        return raw

    def census(self, phase):
        return dict(schema='p1-owned-window-census-v1', ownerPID=self.gui.process.pid,
            phase=phase, count=1, windows=[dict(windowID=WINDOW_ID, frame=[0, 0, 402, 874])],
            admissionEligible=False)

    def baseline_files(self):
        self.write('window-census-initial.json', self.census('initial'))
        self.write('baseline.bgra', RAW)
        self.write('baseline.json', dict(schema='p1-direct-registration-buffer-v1', format='BGRA8',
            width=WIDTH, height=HEIGHT, stride=STRIDE, bytes=len(RAW), sha256=sha256(RAW).hexdigest(),
            displayTimeEstablished=False, admissionEligible=False, windowID=WINDOW_ID, session=SESSION))

    def register(self):
        self.baseline_files()
        return self.handoff.register_baseline(3)

    def publish(self):
        self.register(); return self.handoff.publish_roi(3)

    def first_files(self):
        baseline = self.handoff.baseline
        by_name = {crop.name: crop for crop in baseline.crops}
        packed = b''; regions = []
        for region in parse(baseline.plan_bytes)['regions']:
            crop = by_name[region['role']]
            regions.append(dict(role=region['role'], rectangle=[region[k] for k in ('x','y','width','height')],
                offset=len(packed), bytes=len(crop.bgra), stride=region['width'] * 4, sha256=crop.sha256))
            packed += crop.bgra
        anchor = self.budget['startSample']['machTicks']
        manifest = dict(index=2, callbackBeforeMach=anchor+200, callbackAfterMach=anchor+210, status=0,
            statusName='complete', ptsValue=1, ptsTimescale=60, ptsFlags=1, newFrame=True,
            session=SESSION, geometrySHA256=sha256(self.request_bytes).hexdigest(), displayTimeMach=anchor+100,
            width=WIDTH, height=HEIGHT, bytesPerRow=STRIDE, contentRect=[3.25,4.5,560,1240],
            contentScale=1.25, scaleFactor=2, packedPixels='frame-00002.rois.bgra',
            packedPixelSHA256=sha256(packed).hexdigest(), copiedBytes=len(packed), regions=regions)
        self.write('frame-00002.rois.bgra', packed)
        self.write('first-complete.json', manifest)
        self.write('accepted-roi-plan.json', baseline.plan_bytes)
        self.write('window-census-registered.json', self.census('registered'))
        ready = dict(schema='p1-direct-stream-ready-v1', session=SESSION, ownerPID=self.gui.process.pid,
            windowID=WINDOW_ID, executable=window_capture.SIMULATOR, windowFrame=[0,0,402,874],
            geometrySHA256=sha256(self.request_bytes).hexdigest(), timebaseNumerator=1, timebaseDenominator=1,
            startCaptureReturnedMach=anchor+50, startCaptureReturned=True,
            presentationLowerBoundEstablished=False, admissionEligible=False)
        self.write('stream-ready.json', ready)
        return manifest, packed, ready

    def first(self):
        self.publish(); self.first_files(); return self.handoff.await_first(3)

    def promote(self):
        self.first(); return self.handoff.promote_first(3)

    def close(self):
        for child in self.children:
            child.exit_requested = True
        for command in (self.helper,self.native):
            if command is not None and command.thread is not None:
                command.finished.wait(3)
                command.thread.join(3)
                if command.thread.is_alive():
                    raise AssertionError('test owned command thread did not finish')
        if self.handoff is not None:
            self.handoff.close()
        for directory in self.directories:
            directory.close()
        if hasattr(self, 'gui') and self.gui.file is not None:
            self.gui.file.close()
        for child in self.children:
            child.close_fds()
        self.stack.close()


class CaptureTargetTests(unittest.TestCase):
    def test_fresh_target_prepares_three_descriptor_bound_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); path = root / 'fresh'
            target = handoff.prepare_capture_target(path)
            try:
                self.assertEqual(sorted(p.name for p in path.iterdir()), ['roi-channel', 'stop-channel'])
                self.assertTrue((path / 'roi-channel').is_dir())
                self.assertTrue((path / 'stop-channel').is_dir())
                directories = [v for v in vars(target).values() if type(v) is Directory]
                self.assertEqual({d.path for d in directories}, {root,path,path/'roi-channel',path/'stop-channel'})
                for directory in directories:
                    directory.check()
                proof = parse(target.proof_bytes)
                self.assertFalse(proof['admissionEligible'])
                self.assertEqual(proof['path'], str(path))
                with self.assertRaises((ValueError,FileExistsError)): handoff.prepare_capture_target(path)
            finally:
                for value in vars(target).values():
                    if type(value) is Directory: value.close()

    def test_existing_file_symlink_and_noncanonical_parent_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'file').write_bytes(b'occupied')
            (root / 'dangling').symlink_to(root / 'missing')
            (root / 'alias').symlink_to(root, target_is_directory=True)
            for path in (root/'file', root/'dangling', root/'alias'/'fresh', root/'..'/root.name/'fresh'):
                with self.subTest(path=path), self.assertRaises((ValueError,FileExistsError)):
                    handoff.prepare_capture_target(path)


class CaptureHandoffTests(unittest.TestCase):
    def assert_failed(self, case):
        self.assertTrue(case.handoff.failed)
        self.assertIsNone(case.runner.read('request.json'))
        with self.assertRaises(ValueError): case.handoff.publish_ack(1)

    def test_original_compile_allowance_binary64_boundary_and_exact_owned_limit(self):
        # Real original LaunchReceipt objects; no process is needed to exercise
        # this pure clock arithmetic. The actual Commands expression is reused.
        started=math.nextafter(131020.0,-math.inf)
        deadline=started+60
        self.assertGreater(deadline-started,60)
        launch=PS.LaunchReceipt(1,deadline,60)
        receipt={'wait_timing':{'command_started':started},'launch_receipt':{'deadline':deadline}}
        value=handoff._compile_allowance(receipt,launch)
        self.assertEqual(value['configuredTimeoutSeconds'],60)
        self.assertEqual(value['recordedDeadlineHostMonotonic'],deadline)
        # A shorter Scope cap is valid; a larger configured timeout never is,
        # even if its effective deadline happens to be capped below60 seconds.
        capped=PS.LaunchReceipt(1,started+30,60)
        short={'wait_timing':{'command_started':started},'launch_receipt':{'deadline':started+30}}
        self.assertEqual(handoff._compile_allowance(short,capped)['configuredTimeoutSeconds'],60)
        for bad in (PS.LaunchReceipt(1,started+30,math.nextafter(60,math.inf)),
                    PS.LaunchReceipt(1,started+30,61),PS.LaunchReceipt(1,started+31,60)):
            with self.assertRaisesRegex(ValueError,'compile allowance'):
                handoff._compile_allowance(short,bad)
        too_late=math.nextafter(deadline,math.inf)
        late={'wait_timing':{'command_started':started},'launch_receipt':{'deadline':too_late}}
        with self.assertRaisesRegex(ValueError,'compile allowance'):
            handoff._compile_allowance(late,PS.LaunchReceipt(1,too_late,60))

    def test_original_compile_receipt_and_exact_source_binding(self):
        with LocalCase() as case:
            self.assertNotIn('timeoutSeconds', case.compile_receipt)
            self.assertEqual(case.compiled.compile_receipt_bytes, case.compile_bytes)
            proof = parse(case.compiled.proof_bytes)
            self.assertEqual(proof['argv'], case.compile_argv)
            self.assertEqual(proof['binarySHA256'], sha256(case.binary.read_bytes()).hexdigest())
            self.assertFalse(proof['admissionEligible'])
            self.assertIs(type(case.scope), PS.Scope)
            self.assertIs(type(case.gui), window_capture.OwnedGUI)
            self.assertIs(type(case.gui.process), PS.OwnedProcess)
            self.assertIs(type(case.helper), native_process.RetainedCommand)
            self.assertIs(type(case.helper.process.launch), PS.LaunchReceipt)
            altered = deepcopy(case.compile_receipt); altered['argv'][-1] += '-foreign'
            with self.assertRaises(ValueError):
                handoff.bind_compilation(LOCAL/'capture/direct_capture.swift', case.binary, canonical(altered), scope=case.scope, expected_source_sha256=case.compiled.source_sha256)
            with self.assertRaises(ValueError):
                handoff.bind_compilation(case.binary, case.binary, case.compile_bytes, scope=case.scope, expected_source_sha256=case.compiled.source_sha256)
            case.binary.chmod(0o600)
            with self.assertRaises(ValueError):
                handoff.bind_compilation(LOCAL/'capture/direct_capture.swift', case.binary, case.compile_bytes, scope=case.scope, expected_source_sha256=case.compiled.source_sha256)

    def test_full_real_raster_descriptor_chain_and_single_use_stages(self):
        with LocalCase() as case:
            h = case.handoff
            baseline = case.register()
            self.assertEqual(parse(baseline)['liveMarker']['marker'], 456)
            self.assertEqual(sha256(RAW).hexdigest(), RAW_SHA256)
            self.assertEqual(sha256(canonical(parse(h.baseline.plan_bytes)['regions'])).hexdigest(), REGIONS_SHA256)
            plan = h.publish_roi(3)
            self.assertEqual((case.frame_path/'roi-channel/request.json').read_bytes(), plan)
            manifest, packed, _ = case.first_files()
            self.assertEqual(sha256(packed).hexdigest(), PACKED_SHA256)
            first = h.await_first(3)
            self.assertEqual(parse(first), manifest)
            promoted = h.promote_first(3)
            self.assertEqual(parse(promoted)['firstCompletePackedSHA256'], sha256(packed).hexdigest())
            ack = h.publish_ack(3)
            self.assertEqual(case.runner.read('request.json'), ack)
            checked = bridge.handoff.validate_ack(ack, case.request_bytes)
            self.assertTrue(checked['bindingOnly'])
            self.assertFalse(checked['nativeOwnershipVerified'])
            self.assertFalse(checked['admissionEligible'])
            self.assertEqual(h.state, 'acknowledged')
            self.assertFalse(h.failed)
            self.assertEqual(case.retained['capture-baseline.bgra'], RAW)
            self.assertEqual(case.retained['capture-frame-00002.rois.bgra'], packed)
            self.assertEqual(len(case.journal_retained), len(raster_fixtures.event_files()))
            with self.assertRaises(ValueError): h.publish_ack(1)
            self.assertEqual(case.runner.read('request.json'), ack)

    def test_out_of_order_and_repeated_stages_latch(self):
        for method in ('publish_roi','await_first','promote_first','publish_ack'):
            with self.subTest(method=method), LocalCase() as case:
                with self.assertRaises(ValueError): getattr(case.handoff,method)(1)
                self.assert_failed(case)
        for stage, repeat in (('register','register_baseline'),('publish','publish_roi'),('first','await_first'),('promote','promote_first')):
            with self.subTest(repeat=repeat), LocalCase() as case:
                getattr(case,stage)()
                with self.assertRaises(ValueError): getattr(case.handoff,repeat)(1)
                self.assert_failed(case)

    def test_constructor_rejects_wrong_argv_scope_source_maps_and_budget(self):
        changes = (
            ('helper argv', lambda c: setattr(c.helper, 'argv', c.helper.argv + ('foreign',))),
            ('GUI argv', lambda c: c.gui.argv.append('foreign')),
            ('helper scope', lambda c: setattr(c.helper, 'scope', object())),
            ('budget', lambda c: c.budget.__setitem__('cleanupReserveNs', 1)),
        )
        for label, mutate in changes:
            with self.subTest(label=label), LocalCase(construct=False) as case:
                mutate(case)
                with self.assertRaises(ValueError): case.construct()
        with LocalCase(construct=False) as case:
            wrong = handoff.source_hashes(); wrong[next(iter(wrong))] = '0'*64
            with self.assertRaisesRegex(ValueError, 'source expectation'):
                case.construct(expected_host_sources=wrong)
            wrong = bridge.source_hashes(); wrong[next(iter(wrong))] = '0'*64
            with self.assertRaisesRegex(ValueError, 'bridge sources'):
                case.construct(expected_bridge_sources=wrong)

    def test_compilation_original_owner_and_precompile_hash_binding(self):
        with LocalCase() as case:
            def bind(raw=None, **changes):
                args = dict(scope=case.scope, expected_source_sha256=case.compiled.source_sha256)
                args.update(changes)
                return handoff.bind_compilation(LOCAL/'capture/direct_capture.swift', case.binary,
                    case.compile_bytes if raw is None else raw, **args)
            with self.assertRaisesRegex(ValueError, 'precompile expectation'):
                bind(expected_source_sha256='0'*64)
            altered = deepcopy(case.compile_receipt)
            altered['launch_receipt']['pid'] = case.gui.process.pid
            with self.assertRaisesRegex(ValueError, 'settled owned command'):
                bind(canonical(altered))
            altered = deepcopy(case.compile_receipt)
            altered['wait_timing']['command_started'] = altered['launch_receipt']['deadline']-61
            with self.assertRaisesRegex(ValueError, 'compile allowance'):
                bind(canonical(altered))
            process = case.scope.processes.pop(case.compiled.process.pid)
            with self.assertRaisesRegex(ValueError, 'settled owned command'):
                bind()
            case.scope.processes[process.pid] = process

    def test_prelaunch_compilation_and_target_chronology_required(self):
        for name in ('compiled','target'):
            with self.subTest(name=name), LocalCase(construct=False) as case:
                later = time.monotonic_ns()+10_000_000_000
                if name == 'compiled':
                    case.compiled = replace(case.compiled, observed_after_ns=later)
                else:
                    case.target = replace(case.target, observed_absent_ns=later)
                case.construct(); case.baseline_files()
                with self.assertRaisesRegex(ValueError, 'bound before launch'):
                    case.handoff.register_baseline(1)
                self.assert_failed(case)

    def test_original_native_channel_owner_registry_and_discovery_receipts(self):
        changes = (
            ('native owner', lambda c: c.scope.processes.pop(c.native.process.pid)),
            ('native session', lambda c: c.native.process.launch.row.__setitem__('session','f'*32)),
            ('native registry', lambda c: next(r for r in c.scope.rows if r['pid']==c.native.process.pid)['argv'].append('foreign')),
            ('native settled', lambda c: next(r for r in c.scope.rows if r['pid']==c.native.process.pid).__setitem__('settled',True)),
            ('channel session', lambda c: setattr(c.channels,'session','f'*32)),
            ('foreign descriptor', lambda c: c.channels.directories.__setitem__('runner',c.journal.directory)),
            ('container stdout', lambda c: c.channels.receipts['runner'].__setitem__('stdout',str(c.root))),
            ('container owner', lambda c: c.channels.receipts['runner']['launch_receipt'].__setitem__('pid',c.gui.process.pid)),
            ('container argv', lambda c: c.channels.receipts['runner']['argv'].append('foreign')),
            ('ready bytes', lambda c: setattr(c.channels,'ready_bytes',c.channels.ready_bytes+b' ')),
        )
        for label, mutate in changes:
            with self.subTest(label=label), LocalCase() as case:
                case.baseline_files(); mutate(case)
                with self.assertRaises(ValueError): case.handoff.register_baseline(1)
                self.assert_failed(case)

    def test_stale_runner_ack_rejected(self):
        with LocalCase(construct=False) as case:
            case.runner.publish('request.json', b'{"stale":true}')
            with self.assertRaisesRegex(ValueError, 'ack already exists'): case.construct()

    def test_owner_session_registry_and_lifecycle_loss_fail_closed(self):
        changes = (
            ('GUI owner', lambda c: c.scope.processes.pop(c.gui.process.pid)),
            ('helper owner', lambda c: c.scope.processes.pop(c.helper.process.pid)),
            ('helper registry', lambda c: next(r for r in c.scope.rows if r['pid']==c.helper.process.pid)['argv'].append('foreign')),
            ('GUI registry', lambda c: next(r for r in c.scope.rows if r['pid']==c.gui.process.pid).__setitem__('settled', True)),
            ('launch session', lambda c: c.helper.process.launch.row.__setitem__('session', 'f'*32)),
            ('created session', lambda c: c.scope.fixture['owned_created'].__setitem__('session', 'f'*32)),
            ('creation intent', lambda c: c.scope.creation_intent.__setitem__('name', 'foreign')),
            ('deleted fixture', lambda c: c.scope.fixture.__setitem__('deleted', True)),
            ('cleanup failure', lambda c: c.scope.fixture.__setitem__('cleanup_command_failed', True)),
            ('GUI exited', lambda c: setattr(c.gui.process._process, 'exit_requested', True)),
        )
        for label, mutate in changes:
            with self.subTest(label=label), LocalCase() as case:
                case.baseline_files(); mutate(case)
                with self.assertRaises(ValueError): case.handoff.register_baseline(1)
                self.assert_failed(case)

    def test_compiled_binary_mutation_rejected_before_read_or_ack(self):
        with LocalCase() as case:
            case.baseline_files(); case.binary.write_bytes(b'changed executable bytes')
            with self.assertRaisesRegex(ValueError, 'compiled helper/source changed'):
                case.handoff.register_baseline(3)
            self.assert_failed(case)

    def test_initial_census_and_baseline_identity_fail_closed(self):
        changes = (
            ('owner', 'window-census-initial.json', lambda r: r.__setitem__('ownerPID', 12)),
            ('ambiguous census', 'window-census-initial.json', lambda r: (r.__setitem__('count',2),r['windows'].append(dict(windowID=100,frame=[0,0,402,874])))),
            ('session', 'baseline.json', lambda r: r.__setitem__('session', 'f'*32)),
            ('window', 'baseline.json', lambda r: r.__setitem__('windowID', 100)),
            ('hash', 'baseline.json', lambda r: r.__setitem__('sha256', '0'*64)),
            ('native admission', 'baseline.json', lambda r: r.__setitem__('admissionEligible', True)),
        )
        for label, name, mutate in changes:
            with self.subTest(label=label), LocalCase() as case:
                case.baseline_files(); row=parse((case.frame_path/name).read_bytes()); mutate(row); case.write(name,row)
                with self.assertRaises(ValueError): case.handoff.register_baseline(3)
                self.assert_failed(case)

    def test_retained_byte_mutations_prevent_roi_or_ack(self):
        for name in ('baseline.bgra', 'baseline.json', 'window-census-initial.json'):
            with self.subTest(name=name), LocalCase() as case:
                case.register(); old=(case.frame_path/name).read_bytes(); case.write(name,b'x'+old[1:])
                with self.assertRaisesRegex(ValueError, 'removed or mutated'): case.handoff.publish_roi(1)
                self.assert_failed(case)
        with LocalCase() as case:
            case.promote(); (case.runner.path/'geometry.json').write_bytes(case.request_bytes+b' ')
            with self.assertRaisesRegex(ValueError, 'geometry bytes changed'): case.handoff.publish_ack(1)
            self.assert_failed(case)
        with LocalCase() as case:
            case.promote(); name='frame-00002.rois.bgra'; raw=(case.frame_path/name).read_bytes(); case.write(name,b'x'+raw[1:])
            with self.assertRaisesRegex(ValueError, 'removed or mutated'): case.handoff.publish_ack(1)
            self.assert_failed(case)

    def test_first_stream_owner_session_timebase_census_and_plan_fail_closed(self):
        changes = (
            ('owner', 'stream-ready.json', lambda r: r.__setitem__('ownerPID', 12)),
            ('session', 'stream-ready.json', lambda r: r.__setitem__('session', 'f'*32)),
            ('argv executable', 'stream-ready.json', lambda r: r.__setitem__('executable', '/foreign')),
            ('timebase', 'stream-ready.json', lambda r: r.__setitem__('timebaseNumerator', 2)),
            ('geometry hash', 'stream-ready.json', lambda r: r.__setitem__('geometrySHA256', '0'*64)),
            ('window', 'window-census-registered.json', lambda r: r['windows'][0].__setitem__('windowID', 100)),
            ('frame', 'window-census-registered.json', lambda r: r['windows'][0]['frame'].__setitem__(2, 403)),
            ('accepted plan', 'accepted-roi-plan.json', lambda r: r.__setitem__('session', 'f'*32)),
            ('first hash', 'first-complete.json', lambda r: r.__setitem__('packedPixelSHA256', '0'*64)),
        )
        for label, name, mutate in changes:
            with self.subTest(label=label), LocalCase() as case:
                case.publish(); case.first_files(); row=parse((case.frame_path/name).read_bytes()); mutate(row); case.write(name,row)
                with self.assertRaises(ValueError): case.handoff.await_first(2)
                self.assert_failed(case)

    def test_missing_first_complete_or_pixels_never_acknowledges(self):
        for name in ('first-complete.json', 'frame-00002.rois.bgra'):
            with self.subTest(name=name), LocalCase() as case:
                case.publish(); case.first_files(); (case.frame_path/name).unlink()
                with self.assertRaises(ValueError): case.handoff.await_first(.03)
                self.assert_failed(case)

    def test_native_failure_and_budget_exhaustion_latch_failure(self):
        for name in ('stage-timeout.json', 'window-capture.json'):
            with self.subTest(name=name), LocalCase() as case:
                case.register(); case.write(name, dict(error='synthetic native stop'))
                with self.assertRaisesRegex(ValueError, 'ended or reported failure'): case.handoff.publish_roi(1)
                self.assert_failed(case)
        for value in (0, -1, float('inf'), float('nan'), 121, True):
            with self.subTest(allowance=value), LocalCase() as case:
                case.baseline_files(); case.handoff.remaining=lambda maximum, value=value: value
                with self.assertRaises((ValueError,OverflowError)): case.handoff.register_baseline(1)
                self.assertIsNone(case.runner.read('request.json'))
                with self.assertRaises(ValueError): case.handoff.register_baseline(1)
        with LocalCase() as case:
            case.baseline_files(); case.handoff.deadline_ns=time.monotonic_ns()-1
            with self.assertRaisesRegex(ValueError, 'deadline'): case.handoff.register_baseline(1)
            self.assert_failed(case)

    def test_lost_descriptor_directory_and_gui_receipt_block_ack(self):
        with LocalCase() as case:
            case.promote(); path=case.frame_path/'roi-channel'; path.rename(case.frame_path/'old-roi'); path.mkdir()
            with self.assertRaisesRegex(ValueError, 'directory replaced'): case.handoff.publish_ack(1)
            self.assert_failed(case)
        with LocalCase() as case:
            case.promote(); path=case.gui.folder/'gui-owner.json'; row=parse(path.read_bytes()); row['pid']+=1; path.write_bytes(canonical(row))
            with self.assertRaisesRegex(ValueError, 'GUI owner binding differs'): case.handoff.publish_ack(1)
            self.assert_failed(case)


if __name__ == '__main__':
    unittest.main()
