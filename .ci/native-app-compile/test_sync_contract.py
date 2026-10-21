"""Offline positive/negative checks for additive sync gates; no target execution."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v = load('sync_verifier', HERE / 'verify_upstream_sync.py')
r = load('sync_recorder', HERE / 'record.py')


class ExactAncestryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.ci').mkdir()
        for name in ('source-parity.py', 'source-parity.json'):
            (self.root / '.ci' / name).write_text('synthetic')
        self.expected = copy.deepcopy(v.SPEC['native_sources']['idevice'])
        # Keep the original direct two-parent rejection tests even when the
        # currently pinned idevice is a separately tested exact follow-on.
        if 'merge_anchor' in self.expected:
            self.expected.update(self.expected.pop('merge_anchor'))
        self.expected['files_sha256'] = {p: v.sha(self.root / p) for p in self.expected['files_sha256']}
        self.actual = {
            ('rev-parse', 'HEAD'): self.expected['commit'],
            ('rev-parse', '--is-shallow-repository'): 'false',
            ('rev-parse', 'HEAD^{tree}'): self.expected['tree'],
            ('show', '-s', '--format=%P', 'HEAD'): ' '.join(self.expected['required_commit_parents']),
            ('merge-base', *self.expected['required_commit_parents']): self.expected['merge_base'],
        }
        for parent in self.expected['required_commit_parents']:
            self.actual[('merge-base', '--is-ancestor', parent, 'HEAD')] = ''
        self.mock = patch.object(v, 'git', lambda root, *args: self.actual[args])
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_exact_two_parent_ancestry(self):
        self.assertEqual(v.validate_ancestry(self.root, self.expected), self.expected['required_commit_parents'])

    def test_wrong_owner(self):
        self.actual[('rev-parse', 'HEAD')] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'commit differs'):
            v.validate_ancestry(self.root, self.expected)

    def test_shallow(self):
        self.actual[('rev-parse', '--is-shallow-repository')] = 'true'
        with self.assertRaisesRegex(RuntimeError, 'Shallow'):
            v.validate_ancestry(self.root, self.expected)

    def test_wrong_tree(self):
        self.actual[('rev-parse', 'HEAD^{tree}')] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'tree differs'):
            v.validate_ancestry(self.root, self.expected)

    def test_one_parent(self):
        self.actual[('show', '-s', '--format=%P', 'HEAD')] = self.expected['required_commit_parents'][0]
        with self.assertRaisesRegex(RuntimeError, 'Both exact ordered'):
            v.validate_ancestry(self.root, self.expected)

    def test_reordered_parents(self):
        self.actual[('show', '-s', '--format=%P', 'HEAD')] = ' '.join(reversed(self.expected['required_commit_parents']))
        with self.assertRaisesRegex(RuntimeError, 'Both exact ordered'):
            v.validate_ancestry(self.root, self.expected)

    def test_wrong_merge_base(self):
        self.actual[('merge-base', *self.expected['required_commit_parents'])] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'merge base differs'):
            v.validate_ancestry(self.root, self.expected)

    def test_changed_manifest(self):
        (self.root / '.ci/source-parity.json').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'hash differs'):
            v.validate_ancestry(self.root, self.expected)

    def test_changed_verifier(self):
        (self.root / '.ci/source-parity.py').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'hash differs'):
            v.validate_ancestry(self.root, self.expected)

    def test_linked_metadata(self):
        path = self.root / '.ci/source-parity.json'
        path.unlink()
        path.symlink_to(self.root / '.ci/source-parity.py')
        with self.assertRaisesRegex(RuntimeError, 'linked native metadata'):
            v.validate_ancestry(self.root, self.expected)


class FakeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sources = Path(self.temp.name) / 'sources'
        self.root = self.sources / 'SideStore/Dependencies/minimuxer'
        self.root.mkdir(parents=True)
        self.output = Path(self.temp.name) / 'evidence/fake.json'
        self.expected = copy.deepcopy(v.SPEC['minimuxer_fake_tests'])
        for name in self.expected['source_inputs']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic fixture')
            self.expected['source_inputs'][name] = v.sha(path)
        spec = dict(v.SPEC, minimuxer_fake_tests=self.expected)
        self.spec_patch = patch.object(v, 'SPEC', spec)
        self.spec_patch.start()
        self.addCleanup(self.spec_patch.stop)
        self.report = {'status': 'static_source_invariants_pass', 'native_or_device_execution': False,
                       'swift_smoke': 'source_owned_fake_tests_pass'}
        self.stdout = self.expected['success_line'] + '\n' + json.dumps(self.report, indent=2) + '\n'

    def run_fake(self, stdout=None, code=0):
        result = subprocess.CompletedProcess([], code, self.stdout if stdout is None else stdout)
        with patch.object(v.subprocess, 'run', return_value=result) as run:
            v.minimuxer_tests(self.sources, self.output, '/verified/swiftc')
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ['--swiftc', '/verified/swiftc'])
            self.assertTrue(command[2].endswith('/.ci/verify-upstream-sync.py'))

    def test_exact_fake_report(self):
        self.run_fake()
        report = json.loads(self.output.read_text())
        self.assertEqual(report['transport_cases'], 144)
        self.assertFalse(report['target_native_executed'])

    def test_compiler_warning_braces_not_mistaken_for_report(self):
        self.run_fake('warning: synthetic source { braces }\n' + self.stdout)

    def test_compiler_failure_does_not_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'compiler/harness failed'):
            self.run_fake(code=1)

    def test_missing_exact_totals_do_not_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'totals not observed'):
            self.run_fake(self.stdout.replace('transport_cases=144', 'transport_cases=143'))

    def test_wrong_report_does_not_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'report differs'):
            self.run_fake(self.stdout.replace('source_owned_fake_tests_pass', 'not_run'))

    def test_changed_source_stops_before_compiler(self):
        (self.root / '.ci/upstream-sync-smoke.swift').write_text('modified source')
        with patch.object(v.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'source inputs differ'):
                v.minimuxer_tests(self.sources, self.output, '/verified/swiftc')
            run.assert_not_called()


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.e = self.root / 'evidence'
        self.s = self.root / 'sources'
        self.e.mkdir()
        self.path = self.s / 'SideStore' / r.LOCKS['SideStore']
        self.path.parent.mkdir(parents=True)
        self.before = {'version': 3, 'originHash': 'a' * 64, 'pins': [
            {'identity': 'anisettekit', 'kind': 'remoteSourceControl',
             'location': 'https://github.com/NRG-Wardog/AnisetteKit',
             'state': {'revision': 'e6e9d4aac698de2a5219aaef02c9a417da45f4e9'}},
            {'identity': 'unrelated', 'kind': 'remoteSourceControl',
             'location': 'https://github.com/example/unrelated', 'state': {'revision': 'b' * 40}}]}
        self.after = copy.deepcopy(self.before)
        self.after['pins'][0]['state']['revision'] = r.OWNERS['AnisetteKit'][1]
        self.after['originHash'] = 'c' * 64
        self.patches = [patch.object(r, 'E', self.e), patch.object(r, 'S', self.s)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def seal(self):
        (self.e / 'SideStore.Package.resolved.before').write_text(json.dumps(self.before))
        self.path.write_text(json.dumps(self.after))
        r.seal_resolution()

    def test_exact_observed_transition(self):
        self.seal()
        report = json.loads((self.e / 'app-lock-transition.json').read_text())
        self.assertEqual(report['after_originHash'], 'c' * 64)
        self.assertEqual((self.e / 'SideStore.Package.resolved.after').read_bytes(), self.path.read_bytes())

    def test_other_pin_drift(self):
        self.after['pins'][1]['state']['revision'] = 'd' * 40
        with self.assertRaisesRegex(RuntimeError, 'beyond the exact'):
            self.seal()

    def test_wrong_ak_start(self):
        self.before['pins'][0]['state']['revision'] = 'd' * 40
        with self.assertRaisesRegex(RuntimeError, 'starting AK'):
            self.seal()

    def test_identity_drift(self):
        self.after['pins'][1]['identity'] = 'different'
        with self.assertRaisesRegex(RuntimeError, 'identity closure'):
            self.seal()

    def test_origin_drift(self):
        self.after['pins'][0]['location'] = 'https://github.com/other/AnisetteKit'
        with self.assertRaisesRegex(RuntimeError, 'beyond the exact'):
            self.seal()

    def test_duplicate_pin(self):
        self.after['pins'].append(self.after['pins'][0])
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            self.seal()

    def test_invalid_observed_origin_hash(self):
        self.after['originHash'] = 'fabricated'
        with self.assertRaisesRegex(RuntimeError, 'Invalid observed'):
            self.seal()

    def test_pending_pin_rejected_before_network(self):
        pins = dict(r.OWNERS)
        pins['SideStore'] = (pins['SideStore'][0], 'PENDING_REVIEWED_SIDESTORE_COMMIT')
        with patch.object(r, 'OWNERS', pins), patch.object(r.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'missing or invalid exact'):
                r.acquire()
            run.assert_not_called()


class ExactFollowupAncestryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.ci').mkdir()
        for name in ('source-parity.py', 'source-parity.json'):
            (self.root / '.ci' / name).write_text('synthetic')
        self.expected = copy.deepcopy(v.SPEC['native_sources']['SideStore/Dependencies/minimuxer'])
        self.expected['commit'] = 'a' * 40
        self.expected['tree'] = 'b' * 40
        self.expected['files_sha256'] = {p: v.sha(self.root / p) for p in self.expected['files_sha256']}
        self.anchor = self.expected['merge_anchor']
        self.actual = {
            ('rev-parse', 'HEAD'): self.expected['commit'],
            ('rev-parse', '--is-shallow-repository'): 'false',
            ('rev-parse', 'HEAD^{tree}'): self.expected['tree'],
            ('show', '-s', '--format=%P', 'HEAD'): self.anchor['commit'],
            ('rev-parse', self.anchor['commit'] + '^{tree}'): self.anchor['tree'],
            ('show', '-s', '--format=%P', self.anchor['commit']): ' '.join(self.anchor['required_commit_parents']),
            ('merge-base', '--is-ancestor', self.anchor['commit'], 'HEAD'): '',
            ('merge-base', *self.anchor['required_commit_parents']): self.anchor['merge_base'],
        }
        for parent in self.anchor['required_commit_parents']:
            self.actual[('merge-base', '--is-ancestor', parent, self.anchor['commit'])] = ''
        self.mock = patch.object(v, 'git', lambda root, *args: self.actual[args])
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_exact_child_and_original_two_parent_merge(self):
        self.assertEqual(v.validate_ancestry(self.root, self.expected), [self.anchor['commit']])
        # Both independently required ancestry proofs must fail closed.
        for failed in [
                ('merge-base', '--is-ancestor', self.anchor['commit'], 'HEAD'),
                ('merge-base', '--is-ancestor', self.anchor['required_commit_parents'][1], self.anchor['commit'])]:
            def git(root, *args):
                if args == failed:
                    raise subprocess.CalledProcessError(1, ['git', *args])
                return self.actual[args]
            with self.subTest(failed=failed), patch.object(v, 'git', git), self.assertRaises(subprocess.CalledProcessError):
                v.validate_ancestry(self.root, self.expected)

    def test_no_implicit_single_parent_fallback(self):
        self.expected.pop('merge_anchor')
        with self.assertRaisesRegex(RuntimeError, 'Both exact ordered'):
            v.validate_ancestry(self.root, self.expected)

    def test_wrong_direct_parent(self):
        self.actual[('show', '-s', '--format=%P', 'HEAD')] = 'c' * 40
        with self.assertRaisesRegex(RuntimeError, 'Exact direct'):
            v.validate_ancestry(self.root, self.expected)

    def test_extra_head_parent(self):
        self.actual[('show', '-s', '--format=%P', 'HEAD')] += ' ' + 'c' * 40
        with self.assertRaisesRegex(RuntimeError, 'Exact direct'):
            v.validate_ancestry(self.root, self.expected)

    def test_anchor_cannot_replace_current_commit(self):
        self.expected['commit'] = self.anchor['commit']
        self.actual[('rev-parse', 'HEAD')] = self.anchor['commit']
        with self.assertRaisesRegex(RuntimeError, 'Exact direct'):
            v.validate_ancestry(self.root, self.expected)

    def test_wrong_anchor_tree(self):
        self.actual[('rev-parse', self.anchor['commit'] + '^{tree}')] = 'c' * 40
        with self.assertRaisesRegex(RuntimeError, 'anchor tree'):
            v.validate_ancestry(self.root, self.expected)

    def test_missing_anchor_parent(self):
        self.actual[('show', '-s', '--format=%P', self.anchor['commit'])] = self.anchor['required_commit_parents'][0]
        with self.assertRaisesRegex(RuntimeError, 'Both exact ordered native merge-anchor'):
            v.validate_ancestry(self.root, self.expected)

    def test_reordered_anchor_parents(self):
        self.actual[('show', '-s', '--format=%P', self.anchor['commit'])] = ' '.join(reversed(self.anchor['required_commit_parents']))
        with self.assertRaisesRegex(RuntimeError, 'Both exact ordered native merge-anchor'):
            v.validate_ancestry(self.root, self.expected)

    def test_wrong_anchor_merge_base(self):
        self.actual[('merge-base', *self.anchor['required_commit_parents'])] = 'c' * 40
        with self.assertRaisesRegex(RuntimeError, 'anchor base'):
            v.validate_ancestry(self.root, self.expected)

    def test_inconsistent_top_level_merge_base(self):
        self.expected['merge_base'] = 'c' * 40
        with self.assertRaisesRegex(RuntimeError, 'anchor base'):
            v.validate_ancestry(self.root, self.expected)

    def test_anchor_schema_drift(self):
        self.anchor['allow_any_parent'] = True
        with self.assertRaisesRegex(RuntimeError, 'anchor schema'):
            v.validate_ancestry(self.root, self.expected)

    def test_non_exact_anchor_identity(self):
        self.anchor['tree'] = 'main'
        with self.assertRaisesRegex(RuntimeError, 'anchor identities'):
            v.validate_ancestry(self.root, self.expected)



    def test_source_parity_uses_original_upstream_parent(self):
        observed = {'status': 'exact_frozen_source_pass', 'fork_commit': self.expected['commit'],
                    'upstream_base': self.anchor['required_commit_parents'][1]}
        owner = 'SideStore/Dependencies/minimuxer'
        output = self.root / 'result.json'
        with patch.object(v, 'SPEC', {'native_sources': {owner: self.expected}}), \
             patch.object(v, 'validate_ancestry', return_value=[self.anchor['commit']]), \
             patch.object(v.subprocess, 'check_output', return_value=json.dumps(observed)):
            v.source_parity(self.root, output)
        self.assertEqual(json.loads(output.read_text())['owners'][owner]['merge_anchor'], self.anchor)

    def test_source_parity_rejects_anchor_as_upstream(self):
        observed = {'status': 'exact_frozen_source_pass', 'fork_commit': self.expected['commit'],
                    'upstream_base': self.anchor['commit']}
        with patch.object(v, 'SPEC', {'native_sources': {'mux': self.expected}}), \
             patch.object(v, 'validate_ancestry', return_value=[self.anchor['commit']]), \
             patch.object(v.subprocess, 'check_output', return_value=json.dumps(observed)):
            with self.assertRaisesRegex(RuntimeError, 'identity differs'):
                v.source_parity(self.root, self.root / 'result.json')


class ExactReviewedJktcpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'report.json'
        self.expected = copy.deepcopy(v.SPEC['native_sources']['jktcp'])
        self.expected['commit'] = 'd' * 40
        self.expected['tree'] = 'e' * 40
        self.report = dict(self.expected['verifier_report'], fork_commit=self.expected['commit'],
                           upstream_base=self.expected['required_commit_parents'][1],
                           merge_parents=self.expected['required_commit_parents'])

    def invoke(self, report, owner='jktcp', expected=None):
        expected = self.expected if expected is None else expected
        with patch.object(v, 'SPEC', {'native_sources': {owner: expected}}), \
             patch.object(v, 'validate_ancestry', return_value=expected['required_commit_parents']), \
             patch.object(v.subprocess, 'check_output', return_value=json.dumps(report)):
            v.source_parity(self.root, self.output)

    def test_exact_jktcp_report_admitted(self):
        self.invoke(self.report)
        self.assertEqual(json.loads(self.output.read_text())['owners']['jktcp']['parity_result'], self.report)

    def test_jktcp_report_drift_missing_extra_and_false_pass_types_rejected(self):
        changes = [('owner', 'idevice'), ('status', 'exact_frozen_source_pass'),
                   ('native_execution', True), ('native_execution', 0),
                   ('product_files_verified', 9), ('product_files_verified', 10.0),
                   ('metadata_files_verified', 3), ('behavior_changes', []),
                   ('fork_commit', 'f' * 40), ('upstream_base', 'f' * 40),
                   ('merge_parents', list(reversed(self.report['merge_parents']))),
                   ('unreviewed_extra_field', True)]
        for key, value in changes:
            report = dict(self.report, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaisesRegex(RuntimeError, 'jktcp verifier report'):
                self.invoke(report)
        report = dict(self.report)
        del report['native_execution']
        with self.assertRaisesRegex(RuntimeError, 'jktcp verifier report'):
            self.invoke(report)

    def test_original_owners_do_not_accept_jktcp_status(self):
        expected = copy.deepcopy(v.SPEC['native_sources']['idevice'])
        report = {'status': 'exact_reviewed_source_pass', 'fork_commit': expected['commit']}
        with self.assertRaisesRegex(RuntimeError, 'Frozen source verifier did not pass'):
            self.invoke(report, owner='idevice', expected=expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
