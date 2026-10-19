"""One timeout-case sequencing contract; no concrete native backend or CLI.

Every backend operation below is mandatory. A reviewed adapter must reuse
preflight process_scope.Commands, OwnedGUI, fresh_device and exact-owned cleanup,
validate its retained native evidence, and enforce the supplied timeout inside
blocking operations. This module supplies ordering/budget/failure handling only;
receipt hashes and a mock backend do not establish ownership or admission.
"""
from dataclasses import dataclass
from hashlib import sha256
import ast
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from case_budget import construct
from protocol_driver import Driver

LOCAL = Path(__file__).resolve().parents[1]
SEALED = LOCAL.parent / 'window-capture-candidate/ci/p1'
HINT_SOURCE_SHA = 'b75440e19a8b507e0e17ae01f6f2bc3d7d4072384365af9e3582833fcc89101a'
UI_SOURCE_SHA = '9105711cd1b10860549025109bdc2087976d6661201ab44307e08473b7a7a783'
TEST_TARGET = 'P0SignInUITests/P0SignInUITests/testProbeTimeoutPixels'
# fresh_device.stop_owned/cleanup require every host writer settled first.
CLEANUP = ('settle_native', 'stop_helper', 'stop_gui', 'stop_fixture', 'cleanup_device', 'verify_cleanup')
CLEANUP_LIMITS = dict(settle_native=15, stop_helper=15, stop_gui=25,
                      stop_fixture=45, cleanup_device=75, verify_cleanup=10)
OPERATIONS = ('prepare', 'launch_native', 'await_started', 'discover_app', 'discover_runner',
              'await_geometry', 'start_helper', 'register_baseline', 'publish_roi', 'await_first',
              'promote_first', 'publish_ack', 'await_native_result', 'await_strip_complete',
              'send_stop', 'settle_helper', 'validate_collection') + CLEANUP


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def timeout_started(path, state):
    """Source-bound adaptation of the maintained bounded startup hint reader.

    Only CLASS/METHOD globals change. The log must remain the retained stdout
    of this owned command. This returns a hint, never container/readiness proof.
    """
    source = (SEALED / 'preflight/capture.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'calibration_started')
    block = ast.get_source_segment(source, node)
    require(sha256(block.encode()).hexdigest() == HINT_SOURCE_SHA and
            sha256((SEALED / 'video/ui_tests.swift').read_bytes()).hexdigest() == UI_SOURCE_SHA,
            'reviewed startup hint/source drift')
    namespace = dict(os=os, stat=stat, require=require, CLASS='P0SignInUITests', METHOD='testProbeTimeoutPixels')
    exec(compile(block, '<source-bound-timeout-start-hint>', 'exec'), namespace)
    return namespace['calibration_started'](path, state)


def native_argv(prepared):
    """No retry, extra method, command allowance, or test-timeout expansion."""
    require(type(prepared) is dict and set(prepared) == {'device', 'xctestrun', 'resultBundle'}, 'exact prepared target')
    require(type(prepared['device']) is str and re.fullmatch(r'[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}', prepared['device']), 'exact owned device UUID')
    for key in ('xctestrun', 'resultBundle'):
        require(type(prepared[key]) is str and Path(prepared[key]).is_absolute(), 'absolute prepared paths')
    return ('xcodebuild', 'test-without-building', '-xctestrun', prepared['xctestrun'],
            '-destination', 'id=' + prepared['device'], '-resultBundlePath', prepared['resultBundle'],
            '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1',
            '-test-timeouts-enabled', 'YES', '-default-test-execution-time-allowance', '240',
            '-maximum-test-execution-time-allowance', '240', '-only-testing:' + TEST_TARGET)


@dataclass(frozen=True)
class Evidence:
    """Exact retained receipt bytes plus an adapter-validated in-process value.

    Raw receipts may use existing schemas. validate_stage must bind those bytes
    to value, session, dependencies, source/owners, and the named stage. It must
    reject booleans/hash-shaped assertions unsupported by actual retained data.
    """
    raw: bytes
    value: object


class Case:
    """Single-use, one-case sequencer with mandatory injected native adapters.

    Backend named operations take (context, timeout=seconds) and return Evidence.
    Additional mandatory methods:
      remaining(maximum, cleanup=False): existing Scope.remaining result;
      start_sample(context): retained in-process host/Mach bracket;
      checkpoint(context): raise on owned writer/capture/budget failure;
      validate_stage(name, evidence, context): reject unproven stage semantics;
      make_driver(context, checkpoint, remaining): an unstarted exact Driver;
        wire remaining into BOTH FixtureChannel and Journal blocking waits;
      retain(name, raw): durably retain exact stage evidence bytes;
      persist(raw): durable sequence snapshot write, raising on failure.

    prepare must register resources before risky creation so cleanup still works
    if it raises before returning. Cleanup hooks are idempotent but ownership-
    checked, never broad process/device cleanup. No backend is provided here.
    """
    def __init__(self, session, backend, *, now_ns=time.monotonic_ns):
        require(type(session) is str and re.fullmatch('[0-9a-f]{32}', session), 'fresh session')
        for name in OPERATIONS + ('remaining', 'start_sample', 'checkpoint', 'validate_stage', 'make_driver', 'retain', 'persist'):
            require(callable(getattr(backend, name, None)), 'missing required adapter: ' + name)
        self.backend = backend
        self.now = now_ns
        self.context = {'session': session, 'scenario': 'timeout', 'testTarget': TEST_TARGET, 'evidence': {}}
        self.started = False
        self.completed = False
        self.failed = False
        self.errors = []
        self.receipts = []
        self.budget = None

    def snapshot(self):
        return {'schema': 'p1-direct-case-sequence-v1', 'session': self.context['session'],
                'scenario': 'timeout', 'testTarget': TEST_TARGET, 'stages': list(self.receipts),
                'errors': list(self.errors), 'budget': self.budget, 'sequenceCompleted': self.completed,
                'failed': self.failed, 'nativeBackendProvidedByCaller': True,
                'scope': 'case-ordering-only', 'admissionEligible': False}

    def _persist(self):
        self.backend.persist(canonical(self.snapshot()))

    def _remaining(self, maximum, *, cleanup=False, case_bound=True):
        value = self.backend.remaining(maximum, cleanup=cleanup)
        require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum,
                'invalid remaining Scope budget')
        if self.budget is not None and case_bound:
            start = self.budget['startSample']['hostBeforeNs']
            reserve = 0 if cleanup else 80_000_000_000
            end = start + self.budget['effectiveCommandBudgetNs'] - reserve
            value = min(value, (end - self.now()) / 1_000_000_000)
        require(value > 0, 'absolute case budget exhausted')
        return value

    def _checkpoint(self):
        self._remaining(360)
        self.backend.checkpoint(self.context)

    def _stage(self, name, maximum, *, cleanup=False, case_bound=True):
        # Cleanup does not call live-stream checkpoints, which legitimately fail
        # after native completion. It still gets the parent Scope deadline.
        self.context['stage'] = name
        if not cleanup:
            self.backend.checkpoint(self.context)
        allowance = self._remaining(maximum, cleanup=cleanup, case_bound=case_bound)
        before = self.now()
        result = getattr(self.backend, name)(self.context, timeout=allowance)
        after = self.now()
        require(type(result) is Evidence and type(result.raw) is bytes and 0 < len(result.raw) <= 32 * 1024 * 1024,
                'retained stage evidence required: ' + name)
        # Retain the returned bytes before semantic validation, including failures.
        self.context['evidence'][name] = result
        self.receipts.append({'stage': name, 'beforeNs': before, 'afterNs': after,
                              'allowanceSeconds': allowance, 'receiptSHA256': sha256(result.raw).hexdigest(),
                              'receiptBytes': len(result.raw), 'cleanup': cleanup})
        self.backend.retain(name, result.raw)
        self._persist()
        require(type(before) is int and type(after) is int and before <= after and
                after - before <= int(allowance * 1_000_000_000), 'stage exceeded retained allowance: ' + name)
        self._remaining(360, cleanup=cleanup, case_bound=case_bound)
        self.backend.validate_stage(name, result, self.context)
        return result.value

    def run(self):
        require(not self.started, 'case is single-use')
        self.started = True
        primary = None
        try:
            prepared = self._stage('prepare', 360)
            self.context['argv'] = native_argv(prepared)
            sample_before = self.now()
            sample = self.backend.start_sample(self.context)
            sample_after = self.now()
            require(type(sample) is dict and type(sample.get('hostBeforeNs')) is int and
                    type(sample.get('hostAfterNs')) is int and
                    sample_before <= sample['hostBeforeNs'] <= sample['hostAfterNs'] <= sample_after,
                    'start sample outside actual host call bracket')
            self.budget = construct(sample, int(self._remaining(360) * 1_000_000_000))
            self.context['budget'] = self.budget
            self.context['nativeCommandTimeoutSeconds'] = 360
            self.context['nativeMethodTimeoutSeconds'] = 240
            self._persist()
            self._stage('launch_native', 15)
            # Startup shares the original absolute observation deadline; no separate
            # 90-second cutoff cancels an otherwise live runner installation.
            self._stage('await_started', 360)
            # Exactly one bounded container lookup per role, only after the hint.
            self._stage('discover_app', 30)
            self._stage('discover_runner', 30)
            self._stage('await_geometry', 30)
            self._stage('start_helper', 30)
            self._stage('register_baseline', 30)
            self._stage('publish_roi', 5)
            self._stage('await_first', 15)
            self._stage('promote_first', 15)
            self._stage('publish_ack', 5)
            driver = self.backend.make_driver(self.context, self._checkpoint, self._remaining)
            require(type(driver) is Driver and not driver.started and not driver.failed and
                    type(driver.identity) is dict and driver.identity.get('session') == self.context['session'] and
                    driver.identity.get('simulatorUDID') == prepared['device'], 'original session-bound driver required')
            # Require the collector to use this shared checkpoint, not an unbounded
            # callback hidden in otherwise valid driver construction.
            require(driver.checkpoint == self._checkpoint, 'driver must use shared case checkpoint')
            protocol = driver.run()
            require(protocol['protocolComplete'] is True and protocol['failed'] is False and
                    len(protocol['commands']) == 29, 'original protocol incomplete')
            self.context['protocol'] = protocol
            self._stage('await_native_result', 60)
            self._stage('await_strip_complete', 10)
            # Both completion proofs precede stop; a finish response alone never
            # establishes the visible tail. Final offline coverage remains mandatory.
            self._stage('send_stop', 5)
            self._stage('settle_helper', 70, cleanup=True)
            self._stage('validate_collection', 10, cleanup=True)
        except BaseException as error:
            primary = error
            self.failed = True
            self.errors.append({'stage': 'case', 'type': type(error).__name__, 'message': str(error)})
        finally:
            # No failure skips a later cleanup action, including receipt-write,
            # setup, termination, and earlier-cleanup failures. Cleanup uses the
            # existing Scope cleanup reserve after an expired command, never a
            # restarted XCTest/helper budget. Backend registries
            # own partial resources even when an operation returned no receipt.
            for name in CLEANUP:
                try:
                    self._stage(name, CLEANUP_LIMITS[name], cleanup=True, case_bound=False)
                except BaseException as error:
                    self.failed = True
                    self.errors.append({'stage': name, 'type': type(error).__name__, 'message': str(error)})
                    if primary is None:
                        primary = error
            self.completed = primary is None and not self.failed
            try:
                self._persist()
            except BaseException as error:
                self.completed = False
                self.failed = True
                if primary is None:
                    primary = error
            if primary is not None:
                raise primary
        return self.snapshot()
