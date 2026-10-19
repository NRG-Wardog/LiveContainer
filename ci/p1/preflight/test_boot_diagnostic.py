"""Portable boot-diagnostic safety regressions; no macOS readiness claim."""
import contextlib
import hashlib
import io
import json
import os
import errno
from pathlib import Path
import subprocess
import sys
import tempfile
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import boot_diagnostic as boot
import budget
import process_scope


def devices(state='Shutdown'):
    return {'devices': {boot.RUNTIME: [{'udid': boot.DEVICE, 'state': state, 'isAvailable': True,
                                      'name': 'private-name', 'dataPath': '/private/not-retained'}]}}


def receipt(data=None, failure=None, cleanup=False):
    return {'data': data, 'exit_code': -15 if failure else 0, 'failure_type': failure,
            'primary_error': {'type': failure, 'timeout_seconds': 120} if failure else None,
            'cleanup_errors': [{'type': 'PermissionError'}] if cleanup else [], 'timeout_seconds': 120}


class Reducers(unittest.TestCase):
    def test_device_allowlist_discards_names_paths_and_other_devices(self):
        data = devices(); data['devices']['unknown'] = [{'udid': 'other', 'dataPath': 'private'}]
        result = boot.exact_device(json.dumps(data))
        self.assertEqual(set(result['devices']), {boot.RUNTIME})
        self.assertEqual(set(result['devices'][boot.RUNTIME][0]), {'udid', 'state', 'isAvailable'})
    def test_missing_duplicate_wrong_runtime_unavailable_and_transitional_device_fail(self):
        values = [{'devices': {}}, devices(), devices(), devices(), devices('Booting')]
        values[1]['devices'][boot.RUNTIME] *= 2
        values[2]['devices']['wrong'] = values[2]['devices'].pop(boot.RUNTIME)
        values[3]['devices'][boot.RUNTIME][0]['isAvailable'] = False
        for data in values:
            with self.assertRaises(ValueError): boot.exact_device(json.dumps(data))
    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(ValueError): boot.unique_json('{"devices":{},"devices":{}}')
    def test_runtime_only_keeps_fixed_identity_and_valid_version(self):
        row = {'identifier': boot.RUNTIME, 'version': '26.2', 'buildversion': '23C54', 'isAvailable': True, 'path': 'private'}
        result = boot.exact_runtime(json.dumps({'runtimes': [row]}))
        self.assertNotIn('path', result)
        row['version'] = '26.4'
        with self.assertRaises(ValueError): boot.exact_runtime(json.dumps({'runtimes': [row]}))
    def test_exact_public_versions_and_help(self):
        for kind, data in [('xcode', b'Xcode 26.4.1\nBuild version 17E202\n'),
                           ('os', b'ProductName:\t\tmacOS\nProductVersion:\t\t26.6.2\nBuildVersion:\t\t25G83\n'),
                           ('help', b'Monitor the status of a device booting.\nUsage: simctl bootstatus <device> [-b]\n')]:
            self.assertEqual(boot.tool_text(data, kind)['exact_public_tool_output'].encode(), data)
    def test_unexpected_tool_output_is_rejected(self):
        for data in [b'private value', b'Monitor bootstatus /Users/private', b'Monitor bootstatus https://private',
                     b'Monitor bootstatus token=private', b'Monitor bootstatus\0']:
            with self.assertRaises(ValueError): boot.tool_text(data, 'help')
    def test_process_allowlist_excludes_unknown_names_and_all_arguments_paths(self):
        raw = b'1 0 S 0.0 200 /known/CoreSimulatorService\n2 1 S 0.1 500 /private/private-process\n'
        result = boot.service_processes(raw)
        self.assertEqual(len(result['services']), 1)
        self.assertEqual(result['services'][0]['service'], 'CoreSimulatorService')
        self.assertNotIn('private', json.dumps(result)); self.assertNotIn('/known/', json.dumps(result))
    def test_arbitrary_known_process_state_is_rejected(self):
        with self.assertRaises(ValueError): boot.service_processes(b'1 0 private 0.0 200 Simulator\n')
    def test_arbitrary_version_token_is_rejected(self):
        with self.assertRaises(ValueError): boot.tool_text(b'Xcode 26.4.1\nBuild version private\n', 'xcode')
    def test_process_rows_are_capped(self):
        result = boot.service_processes(b'1 0 S 0.0 200 Simulator\n' * 40)
        self.assertEqual(len(result['services']), 32); self.assertEqual(result['omitted_known_service_rows'], 8)
    def test_resource_numbers_only(self):
        result = boot.vm_counters(b'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 123.\nprivate: 99.\n')
        self.assertEqual(result, {'page_size_bytes': 16384, 'Pages free': 123})
        self.assertEqual(boot.disk_counters(b'header\n/private 100 20 80 20% /\n'), {'blocks_1024': 100, 'used_1024': 20, 'available_1024': 80})
    def test_log_counts_retain_no_messages_paths_ids_or_unknown_metadata(self):
        row = {'processImagePath': '/known/CoreSimulatorService', 'messageType': 'Error',
               'eventMessage': 'private@example.test token=private boot failed timeout', 'userID': 'private', 'processID': 123}
        result = boot.service_log_counts(json.dumps(row).encode())
        self.assertEqual(result['events_counted'], 1); self.assertEqual(len(result['counts']), 3)
        text = json.dumps(result)
        self.assertNotIn('private', text); self.assertNotIn('/known/', text); self.assertNotIn('processID', text)
        self.assertEqual(result['device_attribution'], 'not-established')
        self.assertTrue(result['records_complete']); self.assertFalse(result['records_truncated'])
    def test_log_unknown_service_and_severity_are_discarded(self):
        rows = [{'processImagePath': '/unknown', 'messageType': 'Error', 'eventMessage': 'failed'},
                {'processImagePath': '/Simulator', 'messageType': 'private', 'eventMessage': 'failed'}]
        result = boot.service_log_counts(('\n'.join(map(json.dumps, rows))).encode())
        self.assertEqual(result['events_counted'], 0); self.assertEqual(result['discarded_rows'], 2)
    def test_malformed_or_excess_log_records_fail(self):
        for data in [b'{"invalid', b'[]', b'{}\n' * (boot.LOG_RECORD_LIMIT + 1)]:
            with self.assertRaises(ValueError): boot.service_log_counts(data)


class BoundedProcesses(unittest.TestCase):
    def run_child(self, source, seconds=2):
        with tempfile.TemporaryDirectory() as tmp:
            scope = process_scope.Scope(Path(tmp))
            row, out, err = boot.bounded_capture(scope, [sys.executable, '-B', '-c', source], seconds)
            scope.close()
            self.assertTrue(all(r['settled'] for r in scope.rows))
            return row, out, err
    def test_complete_output_and_nonzero_status_have_separate_typed_receipts(self):
        row, out, err = self.run_child('print("safe"); raise SystemExit(3)')
        self.assertEqual(row['primary_error'], {'type': 'CalledProcessError', 'returncode': 3})
        self.assertTrue(row['output_complete']); self.assertFalse(row['output_truncated'])
        self.assertNotIn('safe', json.dumps(row))
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'exit-status')
        self.assertTrue(row['phase_timing']['wait']['returned']); self.assertTrue(row['phase_timing']['settle']['returned'])
    def test_timeout_retains_primary_and_settles_owned_group(self):
        row, out, err = self.run_child('import time; time.sleep(60)', .05)
        self.assertEqual(row['primary_error']['type'], 'TimeoutExpired')
        self.assertEqual(row['timeout_seconds'], .05); self.assertEqual(row['cleanup_errors'], [])
        self.assertFalse(row['output_complete'])
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'pipe-read')
        self.assertIsNone(row['phase_timing']['wait']['before']); self.assertTrue(row['phase_timing']['settle']['returned'])
    def test_combined_output_cap_stops_writer_and_never_serializes_raw_bytes(self):
        row, out, err = self.run_child('import os,time; os.write(1,b"private"*100000); time.sleep(60)')
        self.assertTrue(row['output_truncated']); self.assertFalse(row['output_complete'])
        self.assertLessEqual(len(out) + len(err), boot.OUTPUT_LIMIT + 1)
        self.assertNotIn('private', json.dumps(row)); self.assertEqual(row['primary_error']['type'], 'ValueError')
    def test_command_failure_does_not_run_parser_or_persist_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            row = receipt(failure='TimeoutExpired'); row['stdout_bytes_observed'] = 7
            with patch.object(boot, 'bounded_capture', return_value=(row, b'private', b'private')):
                result = command.run('known', ['known'], lambda b: self.fail('failure must not parse'))
            self.assertNotIn('private', (root / 'command-001.json').read_text())
            self.assertEqual(result['primary_error']['type'], 'TimeoutExpired')
            scope.close()
    def test_parser_exception_text_never_reaches_retained_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            def invalid(raw): raise ValueError('private parser detail')
            with patch.object(boot, 'bounded_capture', return_value=(receipt(), b'private', b'private')):
                result = command.run('known', ['known'], invalid)
            self.assertEqual(result['parse_error'], {'type': 'ValueError'})
            self.assertNotIn('private', (root / 'command-001.json').read_text())
            scope.close()
    def test_fixed_help_can_use_stderr_without_exposing_other_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            help_text = b'Monitor bootstatus\nUsage: simctl bootstatus <device> [-b]\n'
            with patch.object(boot, 'bounded_capture', return_value=(receipt(), b'', help_text)):
                row = command.run('simctl-bootstatus-help', ['xcrun', 'simctl', 'help', 'bootstatus'], lambda b: boot.tool_text(b, 'help'))
            self.assertEqual(row['data']['exact_public_tool_output'].encode(), help_text)
            scope.close()
    def test_cleanup_exception_does_not_replace_primary_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope = process_scope.Scope(Path(tmp)); original = scope.settle
            def settled_then_error(process):
                original(process)
                raise PermissionError(1, 'private cleanup detail')
            with patch.object(scope, 'settle', settled_then_error):
                row, out, err = boot.bounded_capture(scope, [sys.executable, '-B', '-c', 'import time; time.sleep(60)'], .05)
            self.assertEqual(row['primary_error']['type'], 'TimeoutExpired')
            self.assertEqual(row['cleanup_errors'], [{'type': 'PermissionError', 'errno': 1}])
            self.assertNotIn('private', json.dumps(row)); scope.close()
    def test_failed_log_reducer_retains_limit_and_incomplete_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            with patch.object(boot, 'bounded_capture', return_value=(receipt(), b'{}\n' * (boot.LOG_RECORD_LIMIT + 1), b'')):
                row = command.run('service-log-categories', ['/usr/bin/log', 'show'], boot.service_log_counts)
            self.assertEqual(row['record_limit'], 2048); self.assertFalse(row['records_complete'])
            self.assertTrue(row['records_truncated']); self.assertEqual(row['parse_error']['type'], 'LogRecordLimitExceeded')
            self.assertIsNone(row['data']); scope.close()
    def test_receipt_write_error_keeps_original_typed_failure_without_raw_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root); console = io.StringIO()
            row = receipt(failure='TimeoutExpired')
            with patch.object(boot, 'bounded_capture', return_value=(row, b'PRIVATE_SENTINEL', b'')), patch.object(process_scope, 'atomic', side_effect=OSError(errno.ENOSPC, 'PRIVATE_SENTINEL')), contextlib.redirect_stdout(console):
                with self.assertRaises(OSError) as error: command.run('bootstatus', ['known'], boot.categorized_output)
            self.assertEqual(error.exception._p1_command_receipt['primary_error']['type'], 'TimeoutExpired')
            self.assertNotIn('PRIVATE_SENTINEL', console.getvalue())
            self.assertIn('boot-diagnostic-receipt-write-failure', console.getvalue()); scope.close()
    def test_unsettled_diagnostic_blocks_index_even_with_independent_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {'schema': 'p1-capability-process-scope-v1', 'session': 'test', 'closing': True,
                        'groups': [{'pid': 765432, 'pgid': 765432, 'settled': False}],
                        'fixture': {'device': boot.DEVICE, 'owned_boot': True, 'stopped': True}}
            process_scope.atomic(root / 'process-registry.json', registry)
            with patch.object(process_scope, 'stop_group', return_value=False):
                with self.assertRaises(ValueError): budget.verify_quiescence(root, 'test', force=True)
            self.assertFalse((root / 'evidence-index.json').exists())


class PhaseReceipts(unittest.TestCase):
    def simulated(self, spawn_delay=4, wait_error=False, settle_error=False, spawn_error=False, empty=False):
        now = [100.0]; waits = []
        child = Mock(returncode=0)
        def spawn(argv, stdout, stderr, cleanup=False):
            now[0] += spawn_delay
            if spawn_error: raise OSError(errno.EACCES, 'PRIVATE_SENTINEL')
            if not empty:
                os.write(stdout, b'PRIVATE_SENTINEL output'); os.write(stderr, b'PRIVATE_SENTINEL error')
            return child
        def wait(timeout):
            waits.append(timeout); now[0] += 2
            if wait_error: raise subprocess.TimeoutExpired(['PRIVATE_SENTINEL'], timeout)
            return 0
        def settle(process):
            self.assertIs(process, child); now[0] += 7
            if settle_error: raise PermissionError(errno.EPERM, 'PRIVATE_SENTINEL')
        child.wait.side_effect = wait
        scope = Mock(); scope.remaining.return_value = 120; scope.spawn.side_effect = spawn; scope.settle.side_effect = settle
        with patch.object(boot.time, 'monotonic', side_effect=lambda: now[0]):
            row, out, err = boot.bounded_capture(scope, ['known'], 120)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(row))
        self.assertFalse(row['phase_timing']['spawn_return_is_target_exec'])
        self.assertEqual(row['timeout_seconds'], 120)
        return row, waits, scope
    def test_separate_spawn_read_wait_and_settle_brackets_do_not_reset_deadline(self):
        row, waits, scope = self.simulated()
        timing = row['phase_timing']
        self.assertEqual(timing['spawn'], {'before': 100, 'after': 104, 'returned': True})
        self.assertEqual(timing['wait'], {'before': 104, 'after': 106, 'returned': True})
        self.assertEqual(timing['settle'], {'before': 106, 'after': 113, 'returned': True})
        for stream in ['stdout', 'stderr']:
            self.assertEqual(timing[stream]['first_bytes_read'], [104, 104])
            self.assertEqual(timing[stream]['eof_read'], [104, 104])
        self.assertEqual(waits, [116]); self.assertEqual(row['host_end'] - row['host_start'], 13)
        self.assertIsNone(timing['primary_failure_phase'])
    def test_empty_streams_have_eof_but_no_invented_first_bytes(self):
        row, _, _ = self.simulated(empty=True)
        for stream in ['stdout', 'stderr']:
            self.assertIsNone(row['phase_timing'][stream]['first_bytes_read'])
            self.assertEqual(row['phase_timing'][stream]['eof_read'], [104, 104])
    def test_late_spawn_return_does_not_gain_a_fresh_wait_budget(self):
        row, waits, scope = self.simulated(spawn_delay=121)
        self.assertEqual(row['primary_error'], {'type': 'TimeoutExpired', 'timeout_seconds': 120})
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'pipe-read')
        self.assertEqual(row['phase_timing']['spawn']['after'], 221)
        self.assertEqual(row['phase_timing']['wait'], {'before': None, 'after': None, 'returned': False})
        self.assertEqual(waits, []); scope.settle.assert_called_once()
        for stream in ['stdout', 'stderr']:
            self.assertIsNone(row['phase_timing'][stream]['first_bytes_read'])
            self.assertIsNone(row['phase_timing'][stream]['eof_read'])
    def test_spawn_failure_has_closed_call_bracket_without_fake_return_or_settlement(self):
        row, waits, scope = self.simulated(spawn_error=True)
        self.assertEqual(row['phase_timing']['spawn'], {'before': 100, 'after': 104, 'returned': False})
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'spawn')
        self.assertEqual(row['phase_timing']['settle'], {'before': None, 'after': None, 'returned': False})
        self.assertEqual(row['primary_error'], {'type': 'PermissionError', 'errno': errno.EACCES})
        self.assertEqual(waits, []); scope.settle.assert_not_called()
    def test_wait_timeout_keeps_wait_bracket_and_separate_successful_settlement(self):
        row, waits, scope = self.simulated(wait_error=True)
        self.assertEqual(row['phase_timing']['wait'], {'before': 104, 'after': 106, 'returned': False})
        self.assertTrue(row['phase_timing']['settle']['returned'])
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'wait')
        self.assertEqual(row['primary_error'], {'type': 'TimeoutExpired', 'timeout_seconds': 116})
        self.assertEqual(row['cleanup_errors'], [])
    def test_cleanup_error_does_not_relabel_primary_wait_timeout(self):
        row, _, _ = self.simulated(wait_error=True, settle_error=True)
        self.assertEqual(row['phase_timing']['primary_failure_phase'], 'wait')
        self.assertEqual(row['phase_timing']['settle'], {'before': 106, 'after': 113, 'returned': False})
        self.assertEqual(row['primary_error']['type'], 'TimeoutExpired')
        self.assertEqual(row['cleanup_errors'], [{'type': 'PermissionError', 'errno': errno.EPERM}])
    def test_settle_only_error_does_not_create_a_primary_failure(self):
        row, _, _ = self.simulated(settle_error=True)
        self.assertIsNone(row['primary_error']); self.assertIsNone(row['phase_timing']['primary_failure_phase'])
        self.assertTrue(row['phase_timing']['wait']['returned']); self.assertFalse(row['phase_timing']['settle']['returned'])


class HelpReasonReceipts(unittest.TestCase):
    CASES = [
        (b'\xffPRIVATE_SENTINEL', 'invalid-utf8', 'UnicodeDecodeError'),
        (b'Monitor bootstatus ' + b'x' * 16384, 'size-limit', 'ValueError'),
        (b'Monitor PRIVATE_SENTINEL', 'missing-command-marker', 'ValueError'),
        (b'PRIVATE_SENTINEL bootstatus', 'prefix-mismatch', 'ValueError'),
        (b'Monitor bootstatus\x00PRIVATE_SENTINEL', 'control-character', 'ValueError'),
        (b'Monitor bootstatus token=PRIVATE_SENTINEL', 'sensitive-pattern', 'ValueError'),
    ]
    def test_each_fixed_predicate_reason_retains_original_exception_type_and_no_raw_text(self):
        for raw, reason, kind in self.CASES:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root); console = io.StringIO()
                with patch.object(boot, 'bounded_capture', return_value=(receipt(), b'', raw)), contextlib.redirect_stdout(console):
                    row = command.run('simctl-bootstatus-help', ['xcrun', 'simctl', 'help', 'bootstatus'], lambda b: boot.tool_text(b, 'help'))
                self.assertEqual(row['failure_type'], kind); self.assertIsNone(row['data'])
                self.assertEqual(row['help_parser'], {'version': 'p1-help-guard-v1', 'input_stream': 'stderr', 'outcome': 'rejected', 'reason_code': reason})
                self.assertNotIn('PRIVATE_SENTINEL', (root / 'command-001.json').read_text() + console.getvalue())
                self.assertIn(reason, console.getvalue()); scope.close()
    def test_guard_order_and_boundary_are_unchanged(self):
        raw = b'wrong-prefix token=PRIVATE_SENTINEL'
        with self.assertRaises(ValueError) as error: boot.tool_text(raw, 'help')
        self.assertEqual(error.exception._p1_help_reason, 'missing-command-marker')
        accepted = b'Monitor bootstatus ' + b'x' * (16384 - len(b'Monitor bootstatus '))
        self.assertEqual(len(accepted), 16384)
        self.assertEqual(boot.tool_text(accepted, 'help')['exact_public_tool_output'].encode(), accepted)
        for path in [b'/Users/', b'/home/', b'https://', b'PASSWORD:', b'SeCrEt =']:
            with self.assertRaises(ValueError) as error: boot.tool_text(b'Monitor bootstatus ' + path + b'PRIVATE_SENTINEL', 'help')
            self.assertEqual(error.exception._p1_help_reason, 'sensitive-pattern')
    def test_accepted_stdout_still_takes_precedence_over_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            raw = b'Monitor bootstatus\n'
            with patch.object(boot, 'bounded_capture', return_value=(receipt(), raw, b'PRIVATE_SENTINEL')):
                row = command.run('simctl-bootstatus-help', ['known'], lambda b: boot.tool_text(b, 'help'))
            self.assertEqual(row['help_parser']['input_stream'], 'stdout'); self.assertEqual(row['help_parser']['outcome'], 'accepted')
            self.assertEqual(row['data']['exact_public_tool_output'].encode(), raw)
            self.assertNotIn('PRIVATE_SENTINEL', (root / 'command-001.json').read_text()); scope.close()
    def test_failed_command_does_not_claim_a_help_predicate_was_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
            with patch.object(boot, 'bounded_capture', return_value=(receipt(failure='TimeoutExpired'), b'', b'PRIVATE_SENTINEL')):
                row = command.run('simctl-bootstatus-help', ['known'], lambda b: self.fail('parser must not run'))
            self.assertEqual(row['help_parser']['outcome'], 'not-run'); self.assertNotIn('reason_code', row['help_parser'])
            self.assertNotIn('PRIVATE_SENTINEL', (root / 'command-001.json').read_text()); scope.close()
    def test_unrecognized_reason_attribute_is_not_retained(self):
        for reason in ['PRIVATE_SENTINEL', ['PRIVATE_SENTINEL']]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); scope = process_scope.Scope(root); command = boot.Commands(scope, root)
                def invalid(raw):
                    error = ValueError('PRIVATE_SENTINEL'); error._p1_help_reason = reason; raise error
                with patch.object(boot, 'bounded_capture', return_value=(receipt(), b'', b'PRIVATE_SENTINEL')):
                    row = command.run('simctl-bootstatus-help', ['known'], invalid)
                self.assertEqual(row['help_parser']['reason_code'], 'unclassified-parser-error')
                self.assertNotIn('PRIVATE_SENTINEL', (root / 'command-001.json').read_text()); scope.close()


class CollectorRoutes(unittest.TestCase):
    def run_route(self, failure=None, optional_failure=False, initial='Shutdown', boot_failure=False):
        calls = []
        def run(command, label, argv, parser, timeout=10, cleanup=False):
            calls.append((label, argv, timeout, cleanup))
            state = initial if label == 'before-state' else ('Shutdown' if label == 'shutdown-state' else 'Booted')
            data = devices(state) if label in ['before-state', 'after-state', 'shutdown-state'] else {}
            row = receipt(data, failure if label == 'bootstatus' else ('TimeoutExpired' if boot_failure and label == 'boot' else None))
            if optional_failure and label == 'after-vm': row = receipt(failure='ValueError')
            command.failed |= row['failure_type'] is not None
            return row
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            with patch.object(boot.Commands, 'run', run), patch.object(boot, 'retain_provenance', return_value={'verified': True}):
                passed = boot.execute(root, root, 'a' * 64, root)
            result = json.loads((root / 'capability-result.json').read_text())
        return passed, result, calls
    def test_success_is_diagnostic_only_with_exact_deadlines_and_no_app_commands(self):
        passed, result, calls = self.run_route()
        self.assertTrue(passed); self.assertTrue(result['readiness_observed'])
        self.assertFalse(result['capabilities_passed']); self.assertFalse(result['admissionEligible'])
        self.assertEqual([c[2] for c in calls if c[0] == 'bootstatus'], [120])
        self.assertEqual([c[2] for c in calls if c[0] == 'boot'], [30])
        self.assertEqual(len([c for c in calls if c[2] == 10]), 12)
        self.assertLessEqual(len(calls), 17)
        self.assertFalse(any(x in str(calls) for x in ['install', 'uninstall', 'test-without-building', 'build-for-testing']))
        log = next(c for c in calls if c[0] == 'service-log-categories')
        self.assertIn('--start', log[1]); self.assertIn('--end', log[1]); self.assertIn('--predicate', log[1])
        self.assertLessEqual(result['service_log_window_seconds'], 180)
    def test_readiness_timeout_survives_later_diagnostic_failure_and_shutdown(self):
        passed, result, calls = self.run_route('TimeoutExpired', optional_failure=True)
        self.assertFalse(passed); self.assertFalse(result['readiness_observed'])
        self.assertEqual(result['primary_error'], {'type': 'TimeoutExpired', 'timeout_seconds': 120})
        self.assertIn('shutdown-state', [c[0] for c in calls]); self.assertFalse(result['diagnostic_complete'])
    def test_preexisting_booted_device_is_not_claimed_or_mutated(self):
        passed, result, calls = self.run_route(initial='Booted')
        self.assertFalse(passed)
        self.assertFalse(any(c[0] in ['boot', 'bootstatus', 'shutdown', 'shutdown-state'] for c in calls))
    def test_boot_timeout_preserves_failure_and_skips_readiness_but_cleans_up(self):
        passed, result, calls = self.run_route(boot_failure=True)
        self.assertFalse(passed); self.assertIsNone(result['bootstatus'])
        self.assertEqual(result['primary_error']['type'], 'TimeoutExpired')
        self.assertIn('shutdown-state', [c[0] for c in calls])
    def test_workflow_probe_route_and_unchanged_outer_budget(self):
        workflow = (Path(__file__).resolve().parents[3] / '.github/workflows/p1-native-candidate.yml').read_text()
        block = workflow.split('      - name: Validate one bounded direct timeout case', 1)[1].split('      - name: Package', 1)[0]
        self.assertIn('direct/entry.py', block); self.assertIn('preflight/budget.py --evidence', block); self.assertNotIn('--capture-prerequisites',block)
        self.assertNotIn('--execute', block);self.assertNotIn('--calibration-only',block);self.assertNotIn('--simctl-capture-probe',block); self.assertNotIn('--install-completion-diagnostic',block); self.assertIn('timeout-minutes: 22', block); self.assertEqual(block.count('--full-recovery'),0)
        self.assertNotIn('boot_diagnostic.py', block); self.assertNotIn('--boot-diagnostic', workflow)


class Provenance(unittest.TestCase):
    def test_exact_approved_bytes_pins_and_allowlisted_run_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); host = root / 'host'; out = root / 'out'; host.mkdir(); out.mkdir()
            path = host / 'adapter.py'; path.write_bytes(b'# exact reviewed source\n')
            data = {'adapter_files': {'adapter.py': hashlib.sha256(path.read_bytes()).hexdigest()},
                    'livecontainer': {'commit': 'a' * 40}, 'builder': {'commit': 'b' * 40}}
            inputs = root / 'inputs.json'; inputs.write_text(json.dumps(data)); approved = hashlib.sha256(inputs.read_bytes()).hexdigest()
            workflow = host / '.github/workflows/p1-native-candidate.yml'; workflow.parent.mkdir(parents=True)
            workflow.write_text('seal: ' + approved + '\n')
            environment = {'GITHUB_SHA': 'c' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                           'GITHUB_REPOSITORY': 'NRG-Wardog/LiveContainer', 'PRIVATE_ENV': 'not-retained'}
            with patch.object(boot.capture, 'validate', return_value=data), patch.dict(os.environ, environment):
                row = boot.retain_provenance(host, inputs, approved, out)
            self.assertEqual((out / 'approved-inputs.json').read_bytes(), inputs.read_bytes())
            self.assertEqual((out / 'harness/adapter.py').read_bytes(), path.read_bytes())
            self.assertEqual((out / 'workflow.yml').read_bytes(), workflow.read_bytes())
            self.assertEqual(row['builder'], data['builder']); self.assertNotIn('PRIVATE_ENV', str(row))
            self.assertEqual(row['github']['GITHUB_SHA'], 'c' * 40)
    def test_failed_provenance_prevents_every_diagnostic_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'evidence'
            with patch.object(boot, 'retain_provenance', side_effect=ValueError('fixed provenance failure')), patch.object(boot.Commands, 'run') as run:
                self.assertFalse(boot.execute(root, root, 'a' * 64, root))
            run.assert_not_called()


class MembershipPrivacy(unittest.TestCase):
    def test_group_error_emit_and_registry_are_redacted_before_retention(self):
        snapshot = {'available': False, 'pgid': 4321, 'truncated': True,
                    'rows': [{'pid': 4321, 'ppid': 1, 'pgid': 4321, 'uid': 501, 'state': 'S',
                              'comm': '/PRIVATE_SENTINEL/Simulator'}],
                    'error': {'type': 'OSError', 'errno': 1, 'message': 'PRIVATE_SENTINEL'}}
        console = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scope = process_scope.Scope(root)
            scope.rows.append({'pid': 4321, 'pgid': 4321, 'settled': False}); child = Mock(pid=4321, returncode=0)
            with patch.object(process_scope, 'membership_snapshot', return_value=snapshot) as original:
                with boot.sanitized_membership_diagnostics(), contextlib.redirect_stdout(console):
                    error = process_scope.GroupOperationError('probe', 4321, PermissionError(1, 'PRIVATE_SENTINEL'))
                    with patch.object(process_scope, 'stop_group', side_effect=error):
                        with self.assertRaises(process_scope.GroupOperationError): scope.settle(child)
                self.assertIs(process_scope.membership_snapshot, original)
            retained = ''.join(p.read_text() for p in root.rglob('*') if p.is_file()) + console.getvalue()
            self.assertNotIn('PRIVATE_SENTINEL', retained)
            observed = error.diagnostic['membership']
            self.assertIs(observed['available'], False); self.assertIs(observed['truncated'], True)
            self.assertEqual(observed['pgid'], 4321); self.assertEqual(observed['rows'][0]['pid'], 4321)
            self.assertEqual(observed['rows'][0]['comm'], 'Simulator')
            self.assertFalse(json.loads((root / 'process-registry.json').read_text())['groups'][0]['settled'])
    def test_redaction_failure_does_not_mask_original_group_error_or_claim_absence(self):
        console = io.StringIO()
        with patch.object(process_scope, 'membership_snapshot', return_value={'rows': ['malformed']}) as original:
            with boot.sanitized_membership_diagnostics(), contextlib.redirect_stdout(console):
                error = process_scope.GroupOperationError('probe', 4321, PermissionError(1, 'PRIVATE_SENTINEL'))
            self.assertIs(process_scope.membership_snapshot, original)
        self.assertEqual(error.diagnostic['type'], 'PermissionError'); self.assertEqual(error.diagnostic['errno'], 1)
        self.assertIs(error.diagnostic['membership']['available'], False)
        self.assertIs(error.diagnostic['membership']['redaction_failed'], True)
        self.assertEqual(error.diagnostic['membership']['pgid'], 4321)
        self.assertNotIn('PRIVATE_SENTINEL', console.getvalue())
    def test_context_restores_original_snapshot_after_exception(self):
        original = process_scope.membership_snapshot
        with self.assertRaises(ValueError):
            with boot.sanitized_membership_diagnostics(): raise ValueError('synthetic body failure')
        self.assertIs(process_scope.membership_snapshot, original)
    def test_unknown_process_names_and_nested_error_text_are_not_retained(self):
        row = {'available': True, 'pgid': 2, 'truncated': False, 'rows': [
            {'pid': 2, 'ppid': 1, 'pgid': 2, 'uid': 1, 'state': 'S', 'comm': '/PRIVATE_SENTINEL/private-name'}],
            'cleanup_error': {'type': 'TimeoutExpired', 'timeout_seconds': 1, 'argv': 'PRIVATE_SENTINEL'}}
        result = boot.redacted_membership(row)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result)); self.assertNotIn('private-name', json.dumps(result))
        self.assertEqual(result['rows'][0]['comm'], 'other-owned-process')
        self.assertEqual(result['cleanup_error'], {'type': 'TimeoutExpired', 'timeout_seconds': 1})


class ForcedBackstop(unittest.TestCase):
    def exercise(self, kind='success', unsettled=False, engine=budget):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); session = 'b' * 32
            registry = {'schema': 'p1-capability-process-scope-v1', 'session': session, 'closing': False, 'groups': [],
                        'fixture': {'device': boot.DEVICE, 'owned_boot': True, 'stopped': False,
                                    'bundle_ids': ['org.sidestore.fixture.p1video', 'org.sidestore.fixture.p1video.uitests.xctrunner']}}
            process_scope.atomic(root / 'process-registry.json', registry)
            queue = [(6000, 0, None), (6001, 0, 'Booted'), (6002, None if kind == 'timeout' else (149 if kind == 'nonzero' else 0), None), (6003, 0, 'Shutdown')]
            primary = subprocess.TimeoutExpired(['PRIVATE_SENTINEL'], 15)
            def launch(argv, **kwargs):
                pid, code, state = queue.pop(0)
                if pid != 6000:
                    raw = json.dumps(devices(state)).encode() if state else b'PRIVATE_SENTINEL raw stderr'
                    descriptor = kwargs['stdout'] if state else kwargs['stderr']
                    os.write(descriptor, raw)
                raw = Mock(pid=pid, returncode=code, args=argv); raw.poll.return_value = code
                if pid == 6002 and kind == 'timeout': raw.poll.side_effect = primary
                return raw
            snapshot = {'available': True, 'pgid': 6002, 'rows': [{'pid': 6002, 'ppid': 1, 'pgid': 6002, 'uid': 1, 'state': 'S', 'comm': '/PRIVATE_SENTINEL/simctl'}], 'truncated': False}
            def stop(group, child=None):
                self.assertIsInstance(child, process_scope.OwnedProcess)
                if group == 6002 and unsettled:
                    raise process_scope.GroupOperationError('probe', group, PermissionError(errno.EPERM, 'PRIVATE_SENTINEL'))
                return True
            console = io.StringIO()
            with patch.object(budget.uuid, 'uuid4', return_value=Mock(hex=session)), patch.object(budget.subprocess, 'Popen', side_effect=launch), patch.object(process_scope, 'stop_group', side_effect=stop), patch.object(process_scope, 'membership_snapshot', return_value=snapshot), boot.sanitized_membership_diagnostics(), contextlib.redirect_stdout(console):
                code = engine.run(['fixture-command'], root, command_factory=boot.backstop_commands)
            self.assertEqual(queue, [])
            retained = ''.join(p.read_text() for p in root.rglob('*') if p.is_file()) + console.getvalue()
            self.assertNotIn('PRIVATE_SENTINEL', retained); self.assertNotIn('private-name', retained)
            self.assertNotIn('/private/not-retained', retained); self.assertFalse(list(root.rglob('*.stdout')))
            self.assertFalse(list(root.rglob('*.stderr')))
            shutdown = json.loads((root / 'backstop-simulator-shutdown.json').read_text())
            self.assertTrue(shutdown['observed_shutdown'])
            result = json.loads((root / 'outer-budget.json').read_text())
            self.assertEqual(result['transport_safe'], not unsettled)
            self.assertEqual(json.loads((root / 'process-registry.json').read_text())['session'], session)
            if unsettled:
                self.assertEqual(code, 1); self.assertFalse((root / 'evidence-index.json').exists())
                with self.assertRaises((ValueError, FileNotFoundError)): budget.check_package(root)
                self.assertEqual(result['primary_error']['type'], 'TimeoutExpired' if kind == 'timeout' else 'CalledProcessError')
                self.assertEqual(result['cleanup_errors'][0]['membership']['rows'][0]['comm'], 'simctl')
            else:
                budget.check_package(root); self.assertTrue((root / 'evidence-index.json').is_file())
                self.assertEqual(code, 0 if kind == 'success' else 1)
            command = shutdown['receipts'][1]['command']
            if kind == 'timeout': self.assertEqual(command['primary_error'], {'type': 'TimeoutExpired', 'timeout_seconds': 15})
            if kind == 'nonzero': self.assertEqual(command['primary_error'], {'type': 'CalledProcessError', 'returncode': 149})
    def test_script_loaded_budget_preserves_typed_wrapped_failure(self):
        engine = SimpleNamespace(**runpy.run_path(str(Path(budget.__file__)), run_name='isolated_budget_module'))
        self.exercise('timeout', True, engine=engine)
    def test_successful_backstop_retains_only_sanitized_evidence(self): self.exercise()
    def test_settled_nonzero_then_shutdown_keeps_failed_transport(self): self.exercise('nonzero')
    def test_settled_timeout_then_shutdown_keeps_failed_transport(self): self.exercise('timeout')
    def test_unsettled_nonzero_then_shutdown_cannot_package(self): self.exercise('nonzero', True)
    def test_unsettled_timeout_then_shutdown_cannot_package(self): self.exercise('timeout', True)


if __name__ == '__main__': unittest.main()
