"""Host-only adapter tests. Never import or execute the maintained Swift/C++ suites."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import consumer_contract as c
import run_consumer_tests as entry


def passing():
    return {owner: {group: {'status': 'passed', 'tests': len(ids), 'failures': 0, 'errors': 0,
            'skipped': 0, 'expected_failures': 0, 'unexpected_successes': 0,
            'test_ids': list(ids), 'successful_test_ids': list(ids)} for group, ids in c.SUITE_IDS.items()}
            for owner in ('SideStore', 'LiveContainer')}


class ConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_exact_fixed_38_ids(self):
        self.assertEqual({key: len(value) for key, value in c.SUITE_IDS.items()},
                         {'init_diagnostics': 5, 'adi_consumption': 6, 'login_trace': 8})
        self.assertEqual(c.validate_results(passing())['tests'], 38)
        for ids in c.SUITE_IDS.values():
            self.assertEqual(list(ids), sorted(set(ids)))
        self.assertEqual(len(c.SOURCE_SHA256['SideStore']), 18)
        self.assertEqual(len(c.SOURCE_SHA256['LiveContainer']), 16)
        self.assertEqual(len(c.SOURCE_SHA256['AnisetteKit']), 4)

    def test_missing_duplicate_extra_reordered_or_unexecuted_id_fails(self):
        for field in ('test_ids', 'successful_test_ids'):
            for change in ('missing', 'extra', 'duplicate', 'reorder'):
                value = passing(); ids = value['SideStore']['login_trace'][field]
                if change == 'missing': ids.pop()
                if change == 'extra': ids.append('unreviewed.test')
                if change == 'duplicate': ids[-1] = ids[0]
                if change == 'reorder': ids.reverse()
                with self.subTest(field=field, change=change), self.assertRaises(ValueError):
                    c.validate_results(value)

    def test_every_nonpass_outcome_fails(self):
        for field in ('tests', 'failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes'):
            for bad in (1, True, None):
                value = passing(); value['LiveContainer']['adi_consumption'][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    c.validate_results(value)

    def test_exact_owner_and_suite_closure_required(self):
        values = [passing(), passing(), passing(), passing()]
        values[0].pop('SideStore'); values[1]['foreign'] = {}
        values[2]['LiveContainer'].pop('login_trace'); values[3]['SideStore']['unreviewed'] = {}
        for value in values:
            with self.assertRaises(ValueError): c.validate_results(value)

    def test_missing_tool_is_failure_not_skip(self):
        with mock.patch.object(c.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'tool unavailable'):
                c.require_tools()

    def test_ambient_source_overrides_are_removed_and_restored(self):
        ambient = {key: '/foreign/' + key for key in c.ROOT_ENV}
        with mock.patch.dict(os.environ, ambient):
            old = sys.dont_write_bytecode
            with c.consumer_environment(Path('/ss'), Path('/lc'), Path('/ak'), 'SideStore'):
                self.assertNotIn('LIVE_CONTAINER_TEST_SOURCE', os.environ)
                self.assertEqual(os.environ['SIDE_STORE_TEST_SOURCE'], '/ss')
                self.assertEqual(os.environ['LOGIN_TRACE_PEER_ROOT'], '/lc')
                self.assertTrue(sys.dont_write_bytecode)
            self.assertEqual({key: os.environ[key] for key in ambient}, ambient)
            self.assertEqual(sys.dont_write_bytecode, old)
            with c.consumer_environment(Path('/lc'), Path('/ss'), Path('/ak'), 'LiveContainer'):
                self.assertNotIn('SIDE_STORE_TEST_SOURCE', os.environ)
                self.assertEqual(os.environ['LIVE_CONTAINER_TEST_SOURCE'], '/lc')

    def test_regular_source_bytes_are_bounded_and_no_follow(self):
        (self.root/'file').write_bytes(b'abc')
        self.assertEqual(c.ordinary_bytes(self.root, 'file'), b'abc')
        (self.root/'link').symlink_to(self.root/'file')
        for name in ('link', '../file', '/file', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError): c.ordinary_bytes(self.root, name)
        with self.assertRaises(ValueError): c.ordinary_bytes(self.root, 'file', limit=2)

    def source_context(self, heads=None):
        roots = {key: self.root/key for key in c.SOURCE_BASELINES}
        for root in roots.values(): root.mkdir(exist_ok=True)
        hashes = {owner: {'source': hashlib.sha256(b'sealed').hexdigest()} for owner in roots}
        identities = {root: {'commit': (heads or {}).get(owner, c.SOURCE_BASELINES[owner]), 'tree': 'a'*40}
                      for owner, root in roots.items()}
        return roots, hashes, identities

    def test_source_slice_allows_separately_admitted_sidestore_child(self):
        roots, hashes, identities = self.source_context({'SideStore': 'b'*40})
        with mock.patch.object(c, 'SOURCE_SHA256', hashes), mock.patch.object(c, 'git_identity', side_effect=identities.__getitem__), mock.patch.object(c, 'ordinary_bytes', return_value=b'sealed'):
            receipt = c.verify_sources(roots)
        self.assertEqual(receipt['SideStore']['commit'], 'b'*40)
        self.assertEqual(receipt['SideStore']['source_baseline'], c.SOURCE_BASELINES['SideStore'])

    def test_source_slice_rejects_old_producer_or_changed_bytes(self):
        for changed in ('producer', 'bytes'):
            roots, hashes, identities = self.source_context({'AnisetteKit': 'b'*40} if changed == 'producer' else None)
            with mock.patch.object(c, 'SOURCE_SHA256', hashes), mock.patch.object(c, 'git_identity', side_effect=identities.__getitem__), mock.patch.object(c, 'ordinary_bytes', return_value=b'altered' if changed == 'bytes' else b'sealed'):
                with self.assertRaises(ValueError): c.verify_sources(roots)

    def fake_module(self, group, roots, *, extra=False, skip=False):
        clsname = c.SUITE_IDS[group][0].split('.')[1]
        def body(case):
            if skip: case.skipTest('synthetic adapter skip')
        attrs = {name.split('.')[-1]: body for name in c.SUITE_IDS[group]}
        if extra: attrs['test_unapproved'] = body
        attrs['__module__'] = 'test_contract'
        module = types.ModuleType('test_contract')
        setattr(module, clsname, type(clsname, (unittest.TestCase,), attrs))
        module.ROOT, module.PEER, module.PRODUCER = roots
        return module

    def run_fake(self, *, extra=False, skip=False):
        roots = [self.root/name for name in ('ss', 'lc', 'ak')]
        module = self.fake_module('init_diagnostics', roots, extra=extra, skip=skip)
        spec = types.SimpleNamespace(loader=mock.Mock())
        with mock.patch.object(c.importlib.util, 'spec_from_file_location', return_value=spec), mock.patch.object(c.importlib.util, 'module_from_spec', return_value=module):
            return c.run_suite(*roots, 'SideStore', 'init_diagnostics', stream=io.StringIO())

    def test_fixed_loader_records_started_and_successful_ids(self):
        sentinel = object()
        with mock.patch.dict(sys.modules, {'test_contract': sentinel}):
            row = self.run_fake()
            self.assertIs(sys.modules['test_contract'], sentinel)
        self.assertEqual(row['status'], 'passed')
        self.assertEqual(row['test_ids'], list(c.SUITE_IDS['init_diagnostics']))
        self.assertEqual(row['test_ids'], row['successful_test_ids'])

    def test_fixed_loader_rejects_extra_discovery_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'discovery'): self.run_fake(extra=True)

    def test_unittest_skip_never_becomes_pass(self):
        row = self.run_fake(skip=True)
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['skipped'], 5)
        self.assertEqual(row['successful_test_ids'], [])

    def test_wrapper_has_only_required_fixed_arguments(self):
        argv = ['run_consumer_tests.py']
        for name in ('root', 'peer', 'producer', 'output', 'observer-dir', 'temporary','remaining-budget-json'):
            argv += ['--'+name, '/synthetic/'+name]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(entry, 'run_all') as run, mock.patch.object(Path,'read_bytes',return_value=b'{"files":1,"total_bytes":2,"directories":3}'):
            entry.main()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(run.call_args.args), 6)
        self.assertEqual(run.call_args.kwargs['budget'],{'files':1,'total_bytes':2,'directories':3})


class ConsumerObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = {'swiftc': '/synthetic/swiftc', 'c++': '/synthetic/c++'}
        self.observer = c.ConsumerObserver(self.root/'evidence', self.root/'temporary', self.tools)

    def test_rejects_shell_detach_unknown_option_timeout_and_program(self):
        bad = [{'shell': True}, {'start_new_session': True}, {'process_group': 1}, {'preexec_fn': lambda: None},
               {'timeout': 181}, {'timeout': float('nan')}, {'timeout': 0}, {'encoding': 'utf-8'},
               {'capture_output': False}, {'stdout': subprocess.DEVNULL}]
        for change in bad:
            kwargs = dict(capture_output=True, timeout=180); kwargs.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.observer.command((['/synthetic/swiftc', 'input'],), kwargs)
        with self.assertRaises(ValueError):
            self.observer.command((['/unapproved/program'],), {'capture_output': True, 'timeout': 1})

    def test_binary_raw_streams_and_generated_bytes_retained(self):
        source = self.observer.temporary/'input.swift'; source.write_bytes(b'synthetic source')
        def fake(*args, **kwargs):
            self.assertIs(kwargs['text'], False)
            (self.observer.temporary/'program').write_bytes(b'synthetic product')
            return subprocess.CompletedProcess(args[0], 0, b'\xff\r\n', b'\x80stderr')
        with mock.patch.object(subprocess, 'run', side_effect=fake):
            with self.observer:
                value = subprocess.run(['/synthetic/swiftc', str(source)], capture_output=True, timeout=180)
        self.assertEqual(value.stdout, b'\xff\r\n')
        self.assertEqual((self.observer.root/'0001.stdout').read_bytes(), b'\xff\r\n')
        self.assertEqual((self.observer.root/'0001.stderr').read_bytes(), b'\x80stderr')
        before = json.loads((self.observer.root/'0001.before.json').read_text())['temporary']
        after = json.loads((self.observer.root/'0001.after.json').read_text())['temporary']
        self.assertEqual({row['path'] for row in before['entries']}, {'', 'input.swift'})
        self.assertEqual({row['path'] for row in after['entries']}, {'', 'input.swift', 'program'})
        for row in after['entries']:
            if row['kind'] == 'file':
                self.assertEqual(hashlib.sha256((self.observer.root/row['blob_path']).read_bytes()).hexdigest(), row['sha256'])

    def test_check_output_text_form_keeps_raw_bytes(self):
        def fake(*args, **kwargs):
            self.assertEqual(kwargs['stderr'], subprocess.PIPE)
            return subprocess.CompletedProcess(args[0], 0, b'hello\r\n', b'notice')
        with mock.patch.object(subprocess, 'run', side_effect=fake):
            with self.observer:
                value = subprocess.check_output(['/synthetic/c++'], text=True, timeout=10)
        self.assertEqual(value, 'hello\n')
        self.assertEqual((self.observer.root/'0001.stdout').read_bytes(), b'hello\r\n')

    def test_nested_failure_and_raw_output_retained(self):
        error = subprocess.CalledProcessError(2, ['/synthetic/c++'], output=b'\xfffailure', stderr=b'diagnostic')
        with mock.patch.object(subprocess, 'run', side_effect=error):
            with self.observer:
                with self.assertRaises(subprocess.CalledProcessError):
                    subprocess.run(['/synthetic/c++'], capture_output=True, check=True, timeout=60)
        self.assertEqual((self.observer.root/'0001.stdout').read_bytes(), b'\xfffailure')
        self.assertEqual(json.loads((self.observer.root/'0001.result.json').read_text())['returncode'], 2)

    def test_no_reuse_of_evidence_or_overlapping_roots(self):
        with self.assertRaises(ValueError): c.ConsumerObserver(self.observer.root, self.root/'fresh', self.tools)
        with self.assertRaises(ValueError): c.ConsumerObserver(self.root/'new', self.root/'new'/'temp', self.tools)

    def test_restores_temp_and_subprocess_after_error(self):
        original = subprocess.run; tempdir = tempfile.tempdir; old = os.environ.get('TMPDIR')
        with self.assertRaises(RuntimeError):
            with self.observer: raise RuntimeError('synthetic')
        self.assertIs(subprocess.run, original)
        self.assertEqual(tempfile.tempdir, tempdir)
        self.assertEqual(os.environ.get('TMPDIR'), old)


if __name__ == '__main__':
    unittest.main(verbosity=2)
