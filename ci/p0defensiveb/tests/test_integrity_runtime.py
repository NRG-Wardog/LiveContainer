"""Host-only synthetic/mocked capture and raw-parser mutations; no Swift executes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import integrity_runtime as c
from lifecycle import command_environment, FIXED_ENV
from retention import RawStore


def json_bytes(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def settlement():
    return {'returncode': 0, 'terminationReturncode': 0, 'timeout_seconds': 120,
            'ownedProcessGroup': {'pgid': 123, 'quiescent': True, 'pipesJoined': True,
                                 'leaderReaped': True, 'errors': [], 'signals': [],
                                 'postReapPolicy': 'read-only-group-disappearance'}}


def command_raw(argv=None, cwd='/work', env=None):
    return {'command': json_bytes({'argv': argv or ['/binary'], 'cwd': cwd, 'environment': env or {}}),
            'stdout': c.RUNTIME_STDOUT, 'stderr': b'', 'exit_code': b'0\n',
            'settlement': json_bytes(settlement())}


class IntegrityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_frozen_eight_case_identity_and_raw_success(self):
        result = c.parse_runtime(c.RUNTIME_STDOUT, b'', b'0\n')
        self.assertEqual(result['tests'], 8)
        self.assertEqual(len(set(c.CASE_IDS)), 8)
        self.assertEqual(result['case_ids'], result['successful_case_ids'])
        self.assertEqual(c.SOURCE_COMMIT, 'aed9e5ff3fa9d8d88c51788e82af9d780a41cbb9')
        self.assertEqual(c.SOURCE_TREE, 'e05139bb18388abbe659f99ae0391b80fc2d3ea0')
        self.assertEqual(len(c.SOURCE_FILES), 9)
        self.assertEqual(len(c.GENERATED_FILES), 7)

    def test_summary_only_missing_duplicate_extra_reordered_cases_fail(self):
        lines = c.RUNTIME_STDOUT.splitlines(keepends=True)
        mutations = [lines[-1:], lines[:-2]+lines[-1:], [lines[0]]+lines,
                     list(reversed(lines[:-1]))+lines[-1:], lines+[b'PASS: extra\n'],
                     lines[:-1], [b'PASS: forged\n']+lines[1:]]
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                c.parse_runtime(b''.join(changed), b'', b'0\n')

    def test_noncanonical_runtime_streams_fail(self):
        for stdout, stderr, code in [(c.RUNTIME_STDOUT.rstrip(), b'', b'0\n'),
                (c.RUNTIME_STDOUT.replace(b'\n', b'\r\n'), b'', b'0\n'),
                (c.RUNTIME_STDOUT, b'warning', b'0\n'), (c.RUNTIME_STDOUT, b'', b'1\n'),
                (c.RUNTIME_STDOUT, b'', b'00\n'), (c.RUNTIME_STDOUT, b'', b'0')]:
            with self.subTest(code=code, stderr=stderr), self.assertRaises(ValueError):
                c.parse_runtime(stdout, stderr, code)

    def test_raw_command_validates_complete_success(self):
        result = c.validate_command(command_raw(), ['/binary'], '/work', {}, runtime=True)
        self.assertEqual(result['tests'], 8)

    def test_missing_and_extra_raw_command_parts_fail(self):
        for key in c.COMMAND_PARTS:
            row = command_raw(); row.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})
        row = command_raw(); row['status'] = b'passed'
        with self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})

    def test_command_argv_cwd_environment_mutations_fail(self):
        for key, value in [('argv', ['/foreign']), ('cwd', '/elsewhere'), ('environment', {'DYLD_INSERT_LIBRARIES': '/evil'})]:
            row = command_raw(); command = json.loads(row['command']); command[key] = value; row['command'] = json_bytes(command)
            with self.subTest(key=key), self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})

    def test_exit_timeout_and_forged_success_flags_fail(self):
        for key, value in [('returncode', True), ('returncode', 1), ('terminationReturncode', None),
                ('terminationReturncode', 9), ('error', 'TimeoutExpired'), ('quiescenceError', ''),
                ('timeout_seconds', True), ('timeout_seconds', 0), ('timeout_seconds', 901), ('timeout_seconds', float('nan'))]:
            row = command_raw(); item = settlement(); item[key] = value; row['settlement'] = json_bytes(item)
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})

    def test_unsettled_owned_group_and_signal_termination_fail(self):
        for key, value in [('quiescent', False), ('pipesJoined', False), ('leaderReaped', False),
                ('errors', ['surviving child']), ('signals', [15]), ('pgid', True), ('pgid', 0),
                ('postReapPolicy', 'signal-reused-pgid')]:
            row = command_raw(); item = settlement(); item['ownedProcessGroup'][key] = value; row['settlement'] = json_bytes(item)
            with self.subTest(key=key), self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})

    def test_duplicate_json_and_oversized_raw_records_fail(self):
        row = command_raw(); row['command'] = b'{"argv":[],"argv":["/binary"],"cwd":"/work","environment":{}}'
        with self.assertRaises(ValueError): c.validate_command(row, ['/binary'], '/work', {})
        row = command_raw()
        with mock.patch.object(c, 'MAX_LOG_BYTES', 8), self.assertRaises(ValueError):
            c.validate_command(row, ['/binary'], '/work', {})

    def test_checked_source_hash_length_and_no_follow(self):
        (self.root/'source').write_bytes(b'exact')
        expected = {'source': (c.sha(b'exact'), 5)}
        self.assertEqual(c.checked_files(self.root, expected), {'source': b'exact'})
        (self.root/'source').write_bytes(b'wrong')
        with self.assertRaises(ValueError): c.checked_files(self.root, expected)
        (self.root/'source').unlink(); (self.root/'source').symlink_to(self.root/'missing')
        with self.assertRaises(ValueError): c.checked_files(self.root, expected)

    def test_generated_file_closure_rejects_extra_outputs(self):
        (self.root/'source').write_bytes(b'exact'); (self.root/'unexpected').write_bytes(b'extra')
        with self.assertRaises(ValueError): c.checked_files(self.root, {'source': (c.sha(b'exact'), 5)}, exact=True)

    def test_bounded_tree_rejects_oversize_and_special_files(self):
        (self.root/'big').write_bytes(b'1234')
        with self.assertRaises(ValueError): c._tree_paths(self.root, limit=3)
        with mock.patch.object(c, 'MAX_FILES', 0), self.assertRaises(ValueError): c._tree_paths(self.root, limit=20)
        (self.root/'big').unlink(); os.mkfifo(self.root/'fifo')
        with self.assertRaises(ValueError): c._tree_paths(self.root, limit=20)

    def dependency_setup(self, commit=None):
        work = self.root/'work'; work.mkdir(exist_ok=True)
        packages = work/'sidestore-packages'; packages.mkdir(exist_ok=True)
        checkout = packages/'checkouts/libdeflate'; checkout.mkdir(parents=True, exist_ok=True)
        sidestore = self.root/'SideStore'; (sidestore/c.LOCK).parent.mkdir(parents=True, exist_ok=True)
        revision = commit or c.DEPENDENCY_COMMIT
        pin = {'identity': 'libdeflate', 'kind': 'remoteSourceControl', 'location': c.DEPENDENCY_URL,
               'state': {'branch': 'master', 'revision': revision}}
        dep = {'packageRef': {'identity': 'libdeflate', 'kind': 'remoteSourceControl', 'location': c.DEPENDENCY_URL},
               'subpath': 'libdeflate', 'state': {'name': 'sourceControlCheckout', 'checkoutState': {'revision': revision}}}
        (sidestore/c.LOCK).write_bytes(json_bytes({'pins': [pin]}))
        (packages/'workspace-state.json').write_bytes(json_bytes({'object': {'dependencies': [dep]}}))
        return types.SimpleNamespace(work=work, roots={'SideStore': sidestore}), checkout, dep

    def test_locate_requires_post_app_build_existing_dependency(self):
        gate = types.SimpleNamespace(work=self.root, roots={})
        with self.assertRaisesRegex(ValueError, 'sequencing'): c.locate_dependency(gate)
        gate, checkout, _ = self.dependency_setup()
        self.assertEqual(c.locate_dependency(gate)[0], checkout)

    def test_wrong_missing_or_duplicate_lock_pin_fails(self):
        gate, _, _ = self.dependency_setup()
        path = gate.roots['SideStore']/c.LOCK
        original = json.loads(path.read_bytes())
        values = [copy.deepcopy(original) for _ in range(3)]
        values[0]['pins'][0]['state']['revision'] = '0'*40
        values[1]['pins'] = []
        values[2]['pins'] *= 2
        for value in values:
            path.write_bytes(json_bytes(value))
            with self.assertRaises(ValueError): c.locate_dependency(gate)

    def test_workspace_identity_origin_subpath_mutations_fail(self):
        gate, _, dep = self.dependency_setup()
        values = [copy.deepcopy(dep) for _ in range(4)]
        values[0]['subpath'] = '../other'
        values[1]['packageRef']['location'] += '.forged'
        values[2]['state']['checkoutState']['revision'] = '0'*40
        values[3]['packageRef']['kind'] = 'fileSystem'
        for value in values:
            (gate.work/'sidestore-packages/workspace-state.json').write_bytes(json_bytes({'object': {'dependencies': [value]}}))
            with self.assertRaises(ValueError): c.locate_dependency(gate)

    def dependency_tree(self):
        checkout = self.root/'checkout'; checkout.mkdir(exist_ok=True)
        raw = b'original source'; (checkout/'file.c').write_bytes(raw)
        tree = {'commit': c.DEPENDENCY_COMMIT, 'tree': 'b'*40,
                'entries': [{'path': 'file.c', 'git_mode': '100644', 'sha256': c.sha(raw), 'length': len(raw)}]}
        return checkout, tree

    def test_dependency_working_source_is_bound_to_retained_commit(self):
        checkout, tree = self.dependency_tree()
        self.assertEqual(c.verify_dependency_working_tree(checkout, tree), 'b'*40)
        (checkout/'file.c').write_bytes(b'mutated source')
        with self.assertRaises(ValueError): c.verify_dependency_working_tree(checkout, tree)

    def test_dependency_ignored_extra_source_and_mode_drift_fail(self):
        checkout, tree = self.dependency_tree()
        (checkout/'untracked.h').write_bytes(b'extra')
        with self.assertRaises(ValueError): c.verify_dependency_working_tree(checkout, tree)
        (checkout/'untracked.h').unlink(); (checkout/'file.c').chmod(0o755)
        with self.assertRaises(ValueError): c.verify_dependency_working_tree(checkout, tree)

    def test_dependency_escaping_symlink_fails(self):
        checkout, tree = self.dependency_tree()
        (checkout/'file.c').unlink(); (checkout/'file.c').symlink_to('/etc/hosts')
        tree['entries'][0].update(git_mode='120000', sha256=c.sha(b'/etc/hosts'), length=10)
        with self.assertRaises(ValueError): c.verify_dependency_working_tree(checkout, tree)

    def test_dependency_objects_require_release_target_and_are_bounded(self):
        scratch = self.root/'build'; folder = scratch/'arm64-apple-macosx/release/libdeflate.build'; folder.mkdir(parents=True)
        (folder/'deflate.c.o').write_bytes(b'object')
        self.assertEqual(c.dependency_objects(scratch), [folder/'deflate.c.o'])
        (folder/'deflate.c.o').unlink()
        with self.assertRaises(ValueError): c.dependency_objects(scratch)
        debug = scratch/'debug/libdeflate.build'; debug.mkdir(parents=True)
        (debug/'wrong.o').write_bytes(b'object')
        with self.assertRaises(ValueError): c.dependency_objects(scratch)

    def test_compile_command_uses_exact_genuine_source_and_one_archive(self):
        command = list(map(str, c.compile_command(Path('/generated'), Path('/host/libdeflate.a'))))
        self.assertEqual(command[:3], ['xcrun', 'swiftc', '-swift-version'])
        self.assertEqual([Path(arg).name for arg in command if arg.endswith('.swift')], list(c.SWIFT_INPUTS))
        self.assertEqual([arg for arg in command if arg.endswith('.a')], ['/host/libdeflate.a'])
        self.assertNotIn('AnisetteKit', ' '.join(command))

    def test_non_apple_fails_before_source_reads_or_subprocess(self):
        gate = mock.Mock()
        with mock.patch.object(c.platform, 'system', return_value='Linux'), self.assertRaisesRegex(ValueError, 'not executed'):
            c.run_integrity(gate)
        gate.run.assert_not_called(); gate.save.assert_not_called()

    def fake_capture(self, failure=None, mutation=None):
        """All native commands are simulated writes. No subprocess is launched."""
        commit_raw = b'tree ' + b'b'*40 + b'\nauthor fixture <fixture@example.test> 0 +0000\n\nsynthetic\n'
        commit = hashlib.sha1(b'commit '+str(len(commit_raw)).encode()+b'\0'+commit_raw).hexdigest()
        gate, checkout, _ = self.dependency_setup(commit)
        sidesign = self.root/'SideSign'; sidesign.mkdir(); (sidesign/'source').write_bytes(b'frozen-source')
        gate.roots['SideSign'] = sidesign
        gate.evidence = self.root/'evidence'; (gate.evidence/'logs').mkdir(parents=True)
        gate.base_env = {'PATH': '/usr/bin:/bin', 'HOME': str(gate.work/'home'), 'TMPDIR': str(gate.work/'tmp')}
        gate.store = RawStore(gate.evidence); gate.saved = {}; gate.calls = []
        files = {'Package.swift': b'// synthetic manifest', 'libdeflate.h': b'// synthetic header', 'deflate.c': b'// synthetic C'}
        tree = {'commit': commit, 'tree': 'b'*40, 'entries': []}
        for name, raw in files.items():
            (checkout/name).write_bytes(raw)
            tree['entries'].append({'path': name, 'git_mode': '100644', 'sha256': c.sha(raw), 'length': len(raw)})
        gate.store.retain_git_tree = mock.Mock(return_value=tree)
        sources = {'source': (c.sha(b'frozen-source'), 13)}
        generated = {name: ('// mocked '+name+'\n').encode() for name in (*c.SWIFT_INPUTS, 'generation-receipt.json')}
        expected = {name: (c.sha(raw), len(raw)) for name, raw in generated.items()}

        def run(label, argv, *, cwd, env, timeout, stdout_only):
            self.assertEqual(argv[:3], ['/usr/bin/sandbox-exec', '-p', c.SANDBOX])
            gate.calls.append((label, argv)); stdout = b''; stderr = b''; code = b'0\n'; settled = settlement()
            settled['timeout_seconds'] = timeout
            if label in ('integrity-libdeflate-identity', 'integrity-libdeflate-identity-after', 'integrity-source-identity', 'integrity-source-identity-after'):
                stdout = (commit+'\n'+'b'*40+'\n').encode()
            elif label == 'integrity-libdeflate-commit': stdout = commit_raw
            elif label == 'integrity-libdeflate-manifest':
                stdout = json_bytes({'dependencies': [], 'targets': [{'name': 'libdeflate', 'type': 'regular', 'dependencies': []}]})
            elif label == 'integrity-libdeflate-build':
                path = cwd/'libdeflate-build/arm64-apple-macosx/release/libdeflate.build'; path.mkdir(parents=True)
                (path/'deflate.c.o').write_bytes(b'mocked object')
            elif label == 'integrity-libdeflate-archive': (cwd/'libdeflate.a').write_bytes(b'!<arch>\nmocked archive')
            elif label == 'integrity-generate':
                path = cwd/'generated'; path.mkdir()
                for name, raw in generated.items(): (path/name).write_bytes(raw)
            elif label == 'integrity-compile':
                path = cwd/'generated/library-integrity-tests'; path.write_bytes(b'mocked executable never run'); path.chmod(0o755)
            elif label == 'integrity-runtime':
                stdout = c.RUNTIME_STDOUT if mutation != 'summary-only' else (c.SUMMARY+'\n').encode()
                if mutation == 'source-drift': (sidesign/'source').write_bytes(b'mutated')
            if label == failure:
                code = b'7\n'; settled.update(returncode=7, terminationReturncode=7); stderr = b'mocked failure'
            environment = command_environment(label, argv, env)
            raw = {'command': json_bytes({'argv': argv, 'cwd': str(cwd), 'environment': {k: environment[k] for k in FIXED_ENV if k in environment}}),
                   'stdout': stdout, 'stderr': stderr, 'exit_code': code, 'settlement': json_bytes(settled)}
            for part, suffix in c.COMMAND_PARTS.items(): (gate.evidence/'logs'/(label+suffix)).write_bytes(raw[part])
            if label == failure: raise ValueError('mocked command failure')
            return stdout.decode()
        gate.run = run
        gate.save = lambda label, value: gate.saved.update({label: copy.deepcopy(value)})
        patches = [mock.patch.object(c.platform, 'system', return_value='Darwin'),
                   mock.patch.object(c.platform, 'machine', return_value='arm64'),
                   mock.patch.object(c, 'SOURCE_FILES', sources), mock.patch.object(c, 'GENERATED_FILES', expected),
                   mock.patch.object(c, 'DEPENDENCY_COMMIT', commit)]
        return gate, patches

    def run_fake(self, **options):
        from contextlib import ExitStack
        gate, patches = self.fake_capture(**options)
        with ExitStack() as stack:
            for patch in patches: stack.enter_context(patch)
            try: result = c.run_integrity(gate)
            except Exception as error: return gate, error
            return gate, result

    def test_mocked_end_to_end_retains_raw_sources_commands_dependency_and_eight_cases(self):
        gate, result = self.run_fake()
        if isinstance(result, Exception): raise result
        self.assertEqual(result['status'], 'CAPTURED_FOR_INDEPENDENT_REVIEW')
        self.assertEqual(result['results']['tests'], 8)
        self.assertEqual(gate.saved['library-integrity'], result)
        self.assertEqual(len(result['commands']), 12)
        self.assertEqual(set(result['raw']), {'frozen-source', 'dependency-binding', 'dependency_source',
            'dependency_build', 'dependency_archive', 'generated-source', 'compiler-module', 'fixture_binary', 'fixture_binary_after',
            'dependency-working-before', 'dependency-working-after', 'frozen-source-after', 'generated-source-after',
            'dependency_archive_after', 'compiler-module-after'})
        for entry in result['commands'].values():
            self.assertEqual(set(entry['raw']), set(c.COMMAND_PARTS))
            for record in entry['raw'].values(): self.assertTrue((gate.evidence/record['blob_path']).is_file())
        build = dict(gate.calls)['integrity-libdeflate-build']
        for flag in ('--disable-automatic-resolution', '--skip-update', '--scratch-path'): self.assertIn(flag, build)
        self.assertFalse(any('resolve' == word or 'curl' == word or 'clone' == word for _, argv in gate.calls for word in argv))

    def test_mocked_compile_failure_retains_raw_receipts_and_never_runs_fixture(self):
        gate, result = self.run_fake(failure='integrity-compile')
        self.assertIsInstance(result, ValueError)
        report = gate.saved['library-integrity']
        self.assertEqual(report['status'], 'FAILED_OR_INCOMPLETE')
        self.assertEqual(set(report['commands']['integrity-compile']['raw']), set(c.COMMAND_PARTS))
        self.assertNotIn('integrity-runtime', report['commands'])
        self.assertNotIn('results', report)

    def test_mocked_runtime_summary_only_fails_without_success_claim(self):
        gate, result = self.run_fake(mutation='summary-only')
        self.assertIsInstance(result, ValueError)
        self.assertEqual(gate.saved['library-integrity']['status'], 'FAILED_OR_INCOMPLETE')
        self.assertNotIn('results', gate.saved['library-integrity'])

    def test_mocked_terminal_source_drift_rejects_eight_printed_passes(self):
        gate, result = self.run_fake(mutation='source-drift')
        self.assertIsInstance(result, ValueError)
        self.assertEqual(gate.saved['library-integrity']['status'], 'FAILED_OR_INCOMPLETE')
        self.assertEqual(gate.saved['library-integrity']['results']['tests'], 8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
