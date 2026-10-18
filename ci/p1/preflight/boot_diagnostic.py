#!/usr/bin/env python3
"""One bounded simulator boot observation. No build, installation, UI or admission."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import datetime as dt
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

import capture
import process_scope
import simulator_cleanup

DEVICE = 'B34C2F57-B98B-4C84-96E2-3170887BA2DB'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-26-2'
LOG_RECORD_LIMIT = 2048
OUTPUT_LIMIT = 256 * 1024  # Combined stdout/stderr, never stored unfiltered.
SERVICES = frozenset(['com.apple.CoreSimulator.CoreSimulatorService', 'CoreSimulatorService',
                     'Simulator', 'SimulatorTrampoline', 'SimulatorBridge', 'launchd_sim',
                     'simulatord', 'simdiskimaged'])
CATEGORIES = {
    'timeout': r'\b(timed? out|timeout)\b',
    'connection-invalidated': r'\b(connection invalidated|connection interrupted)\b',
    'failure': r'\b(failed|failure|error)\b',
    'boot': r'\b(boot|booting|booted)\b',
    'launchd': r'\blaunchd\b',
    'readiness': r'\b(ready|readiness)\b',
}


MEMBERSHIP_NAMES = SERVICES | frozenset(['python3', 'python3.11', 'python3.12', 'python3.13', 'python3.14',
                                       'Python', 'xcrun', 'simctl', 'xcodebuild', 'ps', 'log', 'df', 'vm_stat', 'sw_vers'])


def typed_error_fields(row):
    result = {'type': row['type'] if isinstance(row.get('type'), str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', row['type']) else 'Exception'}
    for key in ['errno', 'returncode']:
        if type(row.get(key)) is int: result[key] = row[key]
    if isinstance(row.get('timeout_seconds'), (int, float)) and 0 <= row['timeout_seconds'] <= 1200:
        result['timeout_seconds'] = row['timeout_seconds']
    return result


def redacted_membership(snapshot):
    # Presentation only: preserve group/membership identity, availability and
    # truncation from the reviewed collector; never infer absence from names.
    result = {key: snapshot[key] for key in ['available', 'pgid', 'truncated'] if key in snapshot}
    result['rows'] = []
    for row in snapshot.get('rows', []):
        item = {key: row[key] for key in ['pid', 'ppid', 'pgid', 'uid']}
        state = row.get('state', '')
        item['state'] = state if re.fullmatch(r'[RSDTtZXIWUE][<NLs+VX>]{0,7}', state) else 'unknown'
        name = row.get('comm', '').rsplit('/', 1)[-1]
        item['comm'] = name if name in MEMBERSHIP_NAMES else 'other-owned-process'
        result['rows'].append(item)
    for key in ['error', 'cleanup_error']:
        if isinstance(snapshot.get(key), dict): result[key] = typed_error_fields(snapshot[key])
    result['diagnostic_paths_redacted'] = True
    return result


@contextmanager
def sanitized_membership_diagnostics():
    original = process_scope.membership_snapshot
    def snapshot(group):
        try: return redacted_membership(original(group))
        except Exception:
            # Diagnostic failure cannot mask the original group operation or
            # invent an absence observation. No cleanup decision consumes this.
            return {'available': False, 'pgid': group, 'rows': [], 'truncated': True,
                    'redaction_failed': True, 'error': {'type': 'DiagnosticRedactionError'}}
    process_scope.membership_snapshot = snapshot
    try: yield
    finally: process_scope.membership_snapshot = original


def retain_provenance(host, inputs, approved, output):
    data = capture.validate(host, inputs, approved)
    raw = inputs.read_bytes()
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != approved:
        raise ValueError('approved input bytes changed')
    (output / 'approved-inputs.json').write_bytes(raw)
    total = 0
    for name, digest in sorted(data['adapter_files'].items()):
        source = capture.ordinary(host, name)
        if source.stat().st_size > 2 * 1024 * 1024: raise ValueError('provenance file size bound')
        raw = source.read_bytes(); total += len(raw)
        if total > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('provenance size or seal changed')
        target = output / 'harness' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    workflow = capture.ordinary(host, '.github/workflows/p1-native-candidate.yml').read_bytes()
    if len(workflow) > 65536 or workflow.count(approved.encode()) != 1:
        raise ValueError('workflow provenance seal differs')
    (output / 'workflow.yml').write_bytes(workflow)
    # Only fixed-format public Actions identity fields, never arbitrary env.
    patterns = {'GITHUB_SHA': r'[0-9a-f]{40}', 'GITHUB_RUN_ID': r'[0-9]{1,20}',
                'GITHUB_RUN_ATTEMPT': r'[0-9]{1,10}', 'GITHUB_REPOSITORY': r'NRG-Wardog/LiveContainer'}
    github = {}
    for key, pattern in patterns.items():
        value = os.environ.get(key, '')
        if not re.fullmatch(pattern, value): raise ValueError('invalid Actions provenance identity')
        github[key] = value
    result = {'schema': 'p1-boot-provenance-v1', 'approved_inputs_sha256': approved,
              'workflow_sha256': hashlib.sha256(workflow).hexdigest(), 'adapter_files': data['adapter_files'],
              'livecontainer': data['livecontainer'], 'builder': data['builder'], 'github': github,
              'production_sources_acquired_or_built': False, 'admissionEligible': False}
    process_scope.atomic(output / 'provenance.json', result)
    return result


def unique_json(raw):
    def unique(pairs):
        row = {}
        for key, value in pairs:
            if key in row: raise ValueError('duplicate diagnostic JSON key')
            row[key] = value
        return row
    return json.loads(raw, object_pairs_hook=unique)


def exact_device(raw):
    groups = unique_json(raw).get('devices')
    if not isinstance(groups, dict) or not all(isinstance(v, list) for v in groups.values()):
        raise ValueError('invalid device inventory')
    matches = [(runtime, row) for runtime, rows in groups.items() for row in rows
               if isinstance(row, dict) and row.get('udid', '').lower() == DEVICE.lower()]
    if len(matches) != 1: raise ValueError('exact diagnostic UUID unavailable')
    runtime, row = matches[0]
    if runtime != RUNTIME or row.get('state') not in ['Shutdown', 'Booted'] or row.get('isAvailable') is not True:
        raise ValueError('exact diagnostic runtime/state unavailable')
    # Names, paths, device errors and all unrelated devices are discarded.
    return {'devices': {RUNTIME: [{'udid': DEVICE, 'state': row['state'], 'isAvailable': True}]}}


def exact_runtime(raw):
    rows = unique_json(raw).get('runtimes')
    if not isinstance(rows, list): raise ValueError('invalid runtime inventory')
    matches = [r for r in rows if isinstance(r, dict) and r.get('identifier') == RUNTIME]
    if len(matches) != 1 or matches[0].get('isAvailable') is not True:
        raise ValueError('exact diagnostic runtime unavailable')
    row = matches[0]
    if row.get('version') != '26.2' or not re.fullmatch(r'[0-9A-Z]{3,16}', row.get('buildversion', '')):
        raise ValueError('invalid diagnostic runtime version')
    return {'identifier': RUNTIME, 'version': row['version'], 'buildversion': row['buildversion'], 'isAvailable': True}


HELP_REJECTION_REASONS = frozenset(['invalid-utf8', 'size-limit', 'missing-command-marker',
                                  'prefix-mismatch', 'control-character', 'sensitive-pattern'])


def tool_text(raw, kind):
    try: text = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        if kind not in ['xcode', 'os']: error._p1_help_reason = 'invalid-utf8'
        raise
    patterns = {
        'xcode': r'Xcode [0-9.]{1,20}\nBuild version [0-9]{1,3}[A-Z][0-9]{1,6}[a-z]?\n?',
        'os': r'ProductName:[ \t]{1,8}macOS\nProductVersion:[ \t]{1,8}[0-9.]{1,20}\nBuildVersion:[ \t]{1,8}[0-9]{1,3}[A-Z][0-9]{1,6}[a-z]?\n?',
    }
    if kind in patterns:
        if not re.fullmatch(patterns[kind], text): raise ValueError('unexpected tool version output')
    else:
        # Public vendor-generated usage text from the fixed help command only.
        # No command accepts user values, file paths or environment here.
        # Same predicates and first-failure order as the published guard. A
        # reason is a fixed category, never a fragment of rejected output.
        reason = None
        if len(raw) > 16384: reason = 'size-limit'
        elif 'bootstatus' not in text: reason = 'missing-command-marker'
        elif not text.startswith('Monitor'): reason = 'prefix-mismatch'
        elif any(ord(c) < 32 and c not in '\n\t\r' for c in text): reason = 'control-character'
        elif re.search(r'/Users/|/home/|://|(?i:token|password|secret)\s*[=:]', text): reason = 'sensitive-pattern'
        if reason is not None:
            error = ValueError('unexpected simctl usage output')
            error._p1_help_reason = reason
            raise error
    return {'exact_public_tool_output': text}


def vm_counters(raw):
    text = raw.decode('ascii', errors='strict'); lines = text.splitlines()
    first = re.fullmatch(r'Mach Virtual Memory Statistics: \(page size of (\d+) bytes\)', lines[0]) if lines else None
    if not first: raise ValueError('unexpected vm statistics')
    result = {'page_size_bytes': int(first[1])}
    keys = {'Pages free', 'Pages active', 'Pages inactive', 'Pages speculative', 'Pages wired down',
            'Pages occupied by compressor', 'Swapins', 'Swapouts'}
    for line in lines[1:]:
        match = re.fullmatch(r'([^:]+):[ \t]+([0-9]{1,20})\.', line)
        if match and match[1] in keys: result[match[1]] = int(match[2])
    if 'Pages free' not in result: raise ValueError('missing vm counter')
    return result


def disk_counters(raw):
    lines = raw.decode('utf-8', errors='strict').splitlines()
    if len(lines) != 2: raise ValueError('unexpected disk statistics')
    fields = lines[1].split()
    if len(fields) < 5 or not all(re.fullmatch(r'[0-9]{1,20}', v) for v in fields[1:4]):
        raise ValueError('invalid disk counters')
    return dict(zip(['blocks_1024', 'used_1024', 'available_1024'], map(int, fields[1:4])))


def service_processes(raw):
    rows = []; omitted = 0
    for line in raw.decode('utf-8', errors='replace').splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6: continue
        name = fields[5].rsplit('/', 1)[-1]
        if name not in SERVICES: continue
        if not re.fullmatch(r'[0-9]{1,10} [0-9]{1,10} [RSDTtZXIWUE][<NLs+VX>]{0,7} [0-9]{1,5}(?:\.[0-9]{1,3})? [0-9]{1,16}', ' '.join(fields[:5])):
            raise ValueError('invalid known service counters')
        if len(rows) == 32: omitted += 1; continue
        cpu = float(fields[3])
        if not 0 <= cpu <= 100000: raise ValueError('invalid service CPU counter')
        rows.append({'pid': int(fields[0]), 'ppid': int(fields[1]), 'state': fields[2],
                     'cpu_percent': cpu, 'rss_kib': int(fields[4]), 'service': name})
    return {'services': rows, 'omitted_known_service_rows': omitted, 'arguments_retained': False}


def categorized_output(raw):
    text = raw.decode('utf-8', errors='replace')
    return {'category_counts': {key: len(re.findall(pattern, text, re.I)) for key, pattern in CATEGORIES.items()},
            'messages_retained': False}


class LogRecordLimitExceeded(ValueError):
    pass


def service_log_counts(raw):
    counts = Counter(); accepted = 0; discarded = 0
    lines = raw.decode('utf-8', errors='strict').splitlines()
    if len(lines) > LOG_RECORD_LIMIT: raise LogRecordLimitExceeded('service log record limit exceeded')
    for line in lines:
        if not line.strip(): continue
        row = unique_json(line)
        if not isinstance(row, dict): raise ValueError('invalid service log row')
        name = str(row.get('processImagePath', '')).rsplit('/', 1)[-1]
        level = row.get('messageType')
        if name not in SERVICES or level not in ['Default', 'Info', 'Debug', 'Error', 'Fault']:
            discarded += 1; continue
        message = row.get('eventMessage')
        if not isinstance(message, str): raise ValueError('invalid service event')
        categories = [key for key, pattern in CATEGORIES.items() if re.search(pattern, message, re.I)] or ['other']
        for category in categories: counts[(name, level, category)] += 1
        accepted += 1
    return {'reducer_version': 'p1-service-categories-v1', 'record_limit': LOG_RECORD_LIMIT,
            'records_complete': True, 'records_truncated': False, 'events_counted': accepted, 'discarded_rows': discarded,
            'counts': [{'service': k[0], 'level': k[1], 'category': k[2], 'count': v} for k, v in sorted(counts.items())],
            'messages_retained': False, 'device_attribution': 'not-established'}


def bounded_capture(scope, argv, seconds, cleanup=False, error_sink=None):
    """Read only into bounded memory; register before exec and always settle."""
    limit = scope.remaining(seconds, cleanup)
    started = time.monotonic(); deadline = started + limit
    streams = [bytearray(), bytearray()]; pipes = []; process = None; primary = None; cleanup_errors = []
    complete = False; truncated = False; cleanup_exceptions = []
    timing = {'schema': 'p1-command-phase-timing-v1', 'clock': 'host-time-monotonic',
              'spawn': {'before': None, 'after': None, 'returned': False},
              'wait': {'before': None, 'after': None, 'returned': False},
              'settle': {'before': None, 'after': None, 'returned': False},
              'stdout': {'first_bytes_read': None, 'eof_read': None},
              'stderr': {'first_bytes_read': None, 'eof_read': None},
              'spawn_return_is_target_exec': False, 'primary_failure_phase': None}
    phase = 'pipe-setup'
    try:
        pipes = [os.pipe(), os.pipe()]
        phase = 'spawn'; timing['spawn']['before'] = time.monotonic()
        try:
            process = scope.spawn(argv, pipes[0][1], pipes[1][1], cleanup=cleanup)
            timing['spawn']['returned'] = True
        finally: timing['spawn']['after'] = time.monotonic()
        # For Scope this brackets registration and release issuance. It does
        # not observe the gate child's read, exec or target startup. Backstop
        # spawn returns its directly owned child, also without an exec receipt.
        for _, writer in pipes: os.close(writer)
        pipes = [(reader, None) for reader, _ in pipes]
        phase = 'pipe-read'
        with selectors.DefaultSelector() as selector:
            for index, (reader, _) in enumerate(pipes): selector.register(reader, selectors.EVENT_READ, index)
            while selector.get_map():
                left = deadline - time.monotonic()
                if left <= 0: raise subprocess.TimeoutExpired(argv, limit)
                for key, _ in selector.select(left):
                    count = min(65536, OUTPUT_LIMIT + 1 - sum(map(len, streams)))
                    before_read = time.monotonic()
                    chunk = os.read(key.fd, count)
                    read_bracket = [before_read, time.monotonic()]
                    stream_timing = timing['stdout' if key.data == 0 else 'stderr']
                    if not chunk:
                        stream_timing['eof_read'] = read_bracket
                        selector.unregister(key.fd); continue
                    if stream_timing['first_bytes_read'] is None:
                        stream_timing['first_bytes_read'] = read_bracket
                    streams[key.data].extend(chunk)
                    if sum(map(len, streams)) > OUTPUT_LIMIT:
                        truncated = True
                        raise ValueError('diagnostic output bound exceeded')
            complete = True
        phase = 'wait'; timing['wait']['before'] = time.monotonic()
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
            timing['wait']['returned'] = True
        finally: timing['wait']['after'] = time.monotonic()
        phase = 'exit-status'
        if process.returncode: raise subprocess.CalledProcessError(process.returncode, argv)
    except Exception as error:
        primary = error; timing['primary_failure_phase'] = phase
    finally:
        if process is not None:
            timing['settle']['before'] = time.monotonic()
            try:
                scope.settle(process); timing['settle']['returned'] = True
            except Exception as error:
                cleanup_errors.append(process_scope.error_info(error)); cleanup_exceptions.append(error)
            finally: timing['settle']['after'] = time.monotonic()
        for reader, writer in pipes:
            for descriptor in (reader, writer):
                if descriptor is not None:
                    try: os.close(descriptor)
                    except OSError: pass
    error = process_scope.error_info(primary)
    row = {'timeout_seconds': limit, 'host_start': started, 'host_end': time.monotonic(),
           'phase_timing': timing,
           'exit_code': process.returncode if process else None, 'primary_error': error, 'cleanup_errors': cleanup_errors,
           'failure_type': error['type'] if error else (cleanup_errors[0]['type'] if cleanup_errors else None),
           'output_byte_limit': OUTPUT_LIMIT, 'output_complete': complete, 'output_truncated': truncated,
           'stdout_bytes_observed': len(streams[0]), 'stderr_bytes_observed': len(streams[1]), 'admissionEligible': False}
    if error_sink is not None: error_sink(primary, cleanup_exceptions)
    return row, bytes(streams[0]), bytes(streams[1])


class Commands:
    def __init__(self, scope, root, error_sink=None):
        self.scope = scope; self.root = root; self.count = 0; self.failed = False; self.error_sink = error_sink
    def run(self, label, argv, parser, timeout=10, cleanup=False):
        self.count += 1
        row, out, err = bounded_capture(self.scope, argv, timeout, cleanup, error_sink=self.error_sink)
        row.update(label=label, argv=argv, data=None)
        if label == 'simctl-bootstatus-help':
            row['help_parser'] = {'version': 'p1-help-guard-v1', 'input_stream': 'stdout' if out else 'stderr',
                                  'outcome': 'not-run'}
        if label == 'service-log-categories':
            row.update(reducer_version='p1-service-categories-v1', record_limit=LOG_RECORD_LIMIT,
                       records_complete=False, records_truncated=False)
        # Parse only successful complete output. Failures retain typed status,
        # byte counts and no partial strings, messages or untrusted metadata.
        if row['failure_type'] is None:
            try:
                row['data'] = parser(out if out or label != 'simctl-bootstatus-help' else err)
                if label == 'simctl-bootstatus-help': row['help_parser']['outcome'] = 'accepted'
                if label == 'service-log-categories': row['records_complete'] = True
            except Exception as error:
                row['parse_error'] = process_scope.error_info(error); row['failure_type'] = type(error).__name__
                if label == 'simctl-bootstatus-help':
                    reason = getattr(error, '_p1_help_reason', None)
                    row['help_parser'].update(outcome='rejected', reason_code=reason if type(reason) is str and reason in HELP_REJECTION_REASONS else 'unclassified-parser-error')
                if self.error_sink is not None: self.error_sink(error, [])
                if label == 'service-log-categories': row['records_truncated'] = isinstance(error, LogRecordLimitExceeded)
        self.failed |= row['failure_type'] is not None
        process_scope.emit_diagnostic('boot-diagnostic-command', label=label, exit_code=row['exit_code'],
                                      primary_error=row['primary_error'], cleanup_errors=row['cleanup_errors'],
                                      failure_type=row['failure_type'], timeout_seconds=row['timeout_seconds'],
                                      **({'help_parser': row['help_parser']} if 'help_parser' in row else {}))
        try: process_scope.atomic(self.root / f'command-{self.count:03d}.json', row)
        except Exception as error:
            error._p1_command_receipt = row
            process_scope.emit_diagnostic('boot-diagnostic-receipt-write-failure', label=label,
                                          primary_error=row['primary_error'], write_error=process_scope.error_info(error))
            raise
        return row
    def __call__(self, *argv, timeout=15, cleanup=False, receipt=False):
        argv = list(argv)
        if argv == ['xcrun', 'simctl', 'list', 'devices', '--json']: parser = exact_device; label = 'shutdown-state'
        elif argv == ['xcrun', 'simctl', 'shutdown', DEVICE]: parser = categorized_output; label = 'shutdown'
        else: raise ValueError('unallowlisted cleanup command')
        row = self.run(label, argv, parser, timeout=timeout, cleanup=cleanup)
        return {**row, 'stdout': json.dumps(row['data']) if row['data'] is not None else '', 'stderr': ''}


class BackstopScope:
    """No new registry: retain the shared backstop's direct-child ownership."""
    def remaining(self, seconds, cleanup=False): return min(float(seconds), 15)
    def spawn(self, argv, stdout, stderr, cleanup=False):
        return process_scope.OwnedProcess.spawn(argv, stdout=stdout, stderr=stderr, start_new_session=True)
    def settle(self, child):
        if not process_scope.stop_group(child.pid, child):
            raise ValueError('simulator cleanup group did not settle')


def backstop_commands(evidence, errors, unsettled, wrap_error):
    def error_sink(primary, cleanup):
        wrapped = [wrap_error(error) for error in cleanup]
        unsettled.extend(wrapped)
        if primary is not None:
            error = wrap_error(primary)
            error._p1_cleanup_diagnostics = [dict(item.diagnostic) for item in wrapped]
            errors.append(error)
        elif wrapped: errors.append(wrapped[0])
    root = evidence / 'bounded-backstop'; root.mkdir(exist_ok=False)
    return Commands(BackstopScope(), root, error_sink=error_sink)


def clean(row): return simulator_cleanup.clean_command(row)


def execute(host, inputs, approved, output):
    with sanitized_membership_diagnostics():
        return collect(host, inputs, approved, output)


def collect(host, inputs, approved, output):
    if output.exists(): raise ValueError('fresh diagnostic evidence directory required')
    output.mkdir(parents=True); logs = output / 'commands'; logs.mkdir()
    scope = process_scope.Scope(output); command = Commands(scope, logs); owned = False
    result = {'schema': 'p1-boot-diagnostic-v1', 'scope': 'boot-only-no-admission', 'device': DEVICE, 'runtime': RUNTIME,
              'approved_inputs_sha256': approved, 'bootstatus_deadline_seconds': 120, 'bootstatus': None, 'primary_error': None, 'cleanup_errors': [],
              'diagnostic_complete': False, 'readiness_observed': False, 'collection_complete': False,
              'capabilities_passed': False, 'admissionEligible': False, 'production_ready': False,
              'app_build_executed': False, 'app_install_executed': False, 'ui_executed': False}
    def save(): process_scope.atomic(output / 'capability-result.json', result)
    def require_clean(row):
        if not clean(row): raise ValueError('diagnostic prerequisite failed')
        return row['data']
    def resources(phase):
        command.run(phase + '-vm', ['/usr/bin/vm_stat'], vm_counters)
        command.run(phase + '-services', ['/bin/ps', '-axo', 'pid=,ppid=,state=,%cpu=,rss=,comm='], service_processes)
    try:
        result['provenance'] = retain_provenance(host, inputs, approved, output)
        command.run('xcode-version', ['xcodebuild', '-version'], lambda b: tool_text(b, 'xcode'))
        command.run('os-version', ['/usr/bin/sw_vers'], lambda b: tool_text(b, 'os'))
        command.run('simctl-bootstatus-help', ['xcrun', 'simctl', 'help', 'bootstatus'], lambda b: tool_text(b, 'help'))
        require_clean(command.run('runtime', ['xcrun', 'simctl', 'list', 'runtimes', '--json'], exact_runtime))
        data = require_clean(command.run('before-state', ['xcrun', 'simctl', 'list', 'devices', '--json'], exact_device))
        if data['devices'][RUNTIME][0]['state'] != 'Shutdown': raise ValueError('diagnostic requires initially Shutdown device')
        resources('before')
        command.run('disk', ['/bin/df', '-k', '/'], disk_counters)
        # Initial Shutdown plus this disposable runner's exact UUID establishes
        # ownership before a boot command that may time out after starting boot.
        scope.fixture_identity(DEVICE, True); owned = True
        wall_start = dt.datetime.now(dt.timezone.utc)
        boot = command.run('boot', ['xcrun', 'simctl', 'boot', DEVICE], categorized_output, timeout=30)
        result['boot'] = boot
        if clean(boot):
            if scope.remaining(120) != 120: raise ValueError('full unchanged readiness budget unavailable')
            result['bootstatus'] = command.run('bootstatus', ['xcrun', 'simctl', 'bootstatus', DEVICE, '-b'], categorized_output, timeout=120)
            result['readiness_observed'] = clean(result['bootstatus'])
            result['primary_error'] = result['bootstatus']['primary_error']
        else: result['primary_error'] = boot['primary_error']
        wall_end = dt.datetime.now(dt.timezone.utc)
        save()  # Preserve readiness independently before any later probe.
        if all(row['settled'] for row in scope.rows):
            command.run('after-state', ['xcrun', 'simctl', 'list', 'devices', '--json'], exact_device)
            resources('after')
            # Match known service executables only, never user data or arbitrary
            # environment. Keep category counts only; no event text reaches disk.
            query_start = wall_start.replace(microsecond=0)
            query_end = wall_end.replace(microsecond=0) + dt.timedelta(seconds=1)
            window = (query_end - query_start).total_seconds()
            result['service_log_window_seconds'] = window
            if not 0 <= window <= 180: raise ValueError('service log window exceeds fixed bound')
            predicate = ' OR '.join('process == "' + name + '"' for name in sorted(SERVICES))
            fmt = lambda t: t.strftime('%Y-%m-%d %H:%M:%S+0000')
            command.run('service-log-categories', ['/usr/bin/log', 'show', '--style', 'ndjson', '--start', fmt(query_start),
                        '--end', fmt(query_end), '--predicate', predicate, '--info'], service_log_counts)
        result['diagnostic_complete'] = not command.failed
    except Exception as error:
        failed = getattr(error, '_p1_command_receipt', None)
        if isinstance(failed, dict) and failed.get('label') in ['boot', 'bootstatus']:
            result[failed['label']] = failed
            result['primary_error'] = failed['primary_error']
        result['collector_error'] = process_scope.error_info(error)
    finally:
        if owned:
            try:
                shutdown = simulator_cleanup.confirm_shutdown(command, DEVICE, True)
                process_scope.atomic(output / 'owned-simulator-shutdown.json', shutdown)
                scope.fixture_stopped(shutdown['observed_shutdown'])
                if shutdown['command_failed']: scope.fixture_cleanup_failure()
                if not shutdown['observed_shutdown'] or shutdown['command_failed']:
                    raise ValueError('diagnostic simulator cleanup failed')
            except Exception as error: result['cleanup_errors'].append(process_scope.error_info(error))
        try: scope.close()
        except Exception as error: result['cleanup_errors'].append(process_scope.error_info(error))
        result['collection_complete'] = bool(result['diagnostic_complete'] and not result['cleanup_errors'] and not result.get('collector_error'))
        save()
    return result['collection_complete'] and result['readiness_observed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True); parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--approved-inputs-sha256', required=True); parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--device-class', choices=['phone'], required=True)
    args = parser.parse_args()
    capture.validate(args.host_root, args.inputs, args.approved_inputs_sha256)
    raise SystemExit(0 if execute(args.host_root, args.inputs, args.approved_inputs_sha256, args.evidence) else 1)
