"""Read-only exact host overlay and corrected dispatch tests; no capture is invented."""
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import prior_phase_a as p
import phase_a_evidence_replay as e
from test_phase_a_host_replay import CONTEXT, encode


class SwiftSplitBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate, cls.data, cls.input_raw, cls.closure = p._load_trusted_adapter(HERE / 'prior_adapter')
        fixture = HERE / 'tests/fixtures/lc-overlay-basis'
        listing = (fixture / 'ls-tree.raw').read_bytes()
        original_build = (fixture / 'build.before.yml').read_bytes()
        cls.base_entries = {}
        for entry in listing.split(b'\0'):
            if not entry: continue
            header, name = entry.split(b'\t', 1)
            mode, kind, oid = header.decode('ascii').split()
            cls.base_entries[name.decode('utf-8')] = (mode, kind, oid)
        if e.sha(listing) != '3656ddb63fddc260504336f84b91d153baf0def23f381af832e311bcb68675e0' or e.sha(original_build) != '794d75f941bb6e7ca430a7c0ca05d6899f05ec65786cd81142a459974c62acb4':
            raise ValueError('sealed genuine LC source fixture changed')
        if e.tree_object(cls.base_entries)[0] != p.OVERLAY_TREE:
            raise ValueError('fixture does not reconstruct exact genuine LC tree')
        if cls.base_entries['.github/workflows/build.yml'] != ('100644', 'blob', e.object_id('blob', original_build)):
            raise ValueError('genuine original workflow blob differs')
        cls.roots = {'LiveContainer': '/sealed-read-only-fixture/LiveContainer'}
        def entries(root, commit):
            if str(root) != cls.roots['LiveContainer'] or commit != p.OVERLAY_BASIS:
                raise ValueError('unexpected immutable LC tree fixture request')
            return dict(cls.base_entries)
        def git(root, *args):
            if str(root) != cls.roots['LiveContainer'] or args != ('show', p.OVERLAY_BASIS + ':.github/workflows/build.yml'):
                raise ValueError('unexpected immutable LC blob fixture request')
            return original_build
        for name, implementation in (('entries', entries), ('git', git)):
            patcher = mock.patch.object(cls.gate, name, side_effect=implementation)
            patcher.start(); cls.addClassCleanup(patcher.stop)

    def context(self):
        return {**CONTEXT, 'roots': {owner: CONTEXT['work'] + '/sources/' + owner for owner in self.data['owners']}}

    def host_fixture(self):
        gate = self.gate
        root = Path(self.roots['LiveContainer'])
        base = gate.entries(root, p.OVERLAY_BASIS)
        self.assertEqual(e.tree_object(base)[0], p.OVERLAY_TREE)
        expected = dict(self.closure)
        expected[gate.WORKFLOW_PATH] = expected[gate.WORKFLOW_PATH].replace(
            b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED',
            b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: ' + p.INPUT_SHA256.encode())
        actual = dict(base); changes = {}; records = {}; contents = {}
        for name, content in expected.items():
            after = {'mode': '100644', 'type': 'blob', 'git_object': e.object_id('blob', content), 'sha256': e.sha(content)}
            before = None
            if name == gate.BUILD_WORKFLOW_PATH:
                raw = gate.git(root, 'show', p.OVERLAY_BASIS + ':' + name)
                before = {'mode': '100644', 'type': 'blob', 'git_object': e.object_id('blob', raw), 'sha256': e.sha(raw)}
            changes[name] = {'before': before, 'after': after}
            records[name] = {'source_path': CONTEXT['host'] + '/' + name, 'test_key': name}
            contents[name] = content
            actual[name] = ('100644', 'blob', after['git_object'])
        self.assertEqual(e.tree_object(actual)[0], p.HOST_TREE)
        proof = {'commit': 'a' * 40, 'base': p.HOST_PARENT, 'overlay_basis': p.OVERLAY_BASIS,
                 'tree': p.HOST_TREE, 'origin': {'kind': 'direct', 'repository': self.data['host']['repository']},
                 'changes': changes, 'raw_files': records, 'worktree': {
                     'tracked_entries': len(actual), 'unpopulated_gitlinks': {
                         name: oid for name, (mode, kind, oid) in actual.items() if kind == 'commit'}}}
        raw = types.SimpleNamespace(raw_record=lambda row: contents[row['test_key']])
        return proof, raw

    def replay_host(self, proof, raw, data=None, identity=None):
        files = {'provenance/host-overlay.json': encode(proof), 'provenance/reviewed-inputs.json': self.input_raw}
        return e.replay_host(files, self.gate, data or self.data, self.roots,
                             identity or {'host_commit': 'a' * 40, 'host_tree': p.HOST_TREE},
                             self.context(), raw, self.closure)

    def test_cumulative_overlay_reconstructs_exact_new_tree_from_historical_basis(self):
        proof, raw = self.host_fixture()
        with mock.patch.object(self.gate, 'entries', wraps=self.gate.entries) as entries:
            self.replay_host(proof, raw)
        self.assertEqual(entries.call_args.args[1], p.OVERLAY_BASIS)
        self.assertEqual(len(proof['changes']), 63)
        self.assertNotEqual(p.HOST_PARENT, p.OVERLAY_BASIS)
        self.assertNotEqual(p.HOST_PARENT_TREE, p.OVERLAY_TREE)

    def test_direct_parent_overlay_basis_and_parent_tree_cannot_be_interchanged(self):
        original, raw = self.host_fixture()
        for field, wrong in (('base', p.OVERLAY_BASIS), ('overlay_basis', p.HOST_PARENT), ('tree', p.HOST_PARENT_TREE)):
            proof = copy.deepcopy(original); proof[field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.replay_host(proof, raw)
        data = copy.deepcopy(self.data); data['host']['tree'] = p.OVERLAY_TREE
        with self.assertRaisesRegex(ValueError, 'direct parent/overlay basis'):
            self.replay_host(original, raw, data=data)

    def test_host_overlay_schema_and_full_cumulative_inventory_are_exact(self):
        original, raw = self.host_fixture()
        for kind in ('missing_basis', 'extra_field', 'partial_changes', 'partial_raw'):
            proof = copy.deepcopy(original)
            if kind == 'missing_basis': del proof['overlay_basis']
            elif kind == 'extra_field': proof['unexpected'] = True
            elif kind == 'partial_changes': proof['changes'].pop('ci/p0defensive/diagnostic_checks.py')
            else: proof['raw_files'].pop('ci/p0defensive/diagnostic_checks.py')
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.replay_host(proof, raw)

    def test_source_derived_outer_split_preserves_forty_four_commands_five_lanes(self):
        rows = e.ordered_commands(self.gate, self.data, self.context())
        self.assertEqual(len(rows), 44)
        hosts = [(label, argv) for label, argv, _ in rows if label.startswith('host-')]
        self.assertEqual(len(hosts), 5)
        for label, argv in hosts:
            if label == 'host-run-diagnostic-checks':
                self.assertEqual(argv[:2], [CONTEXT['python'], '-B'])
            else:
                self.assertEqual(argv[:len(self.gate.SANDBOX)], self.gate.SANDBOX)

    def test_independent_review_schema_freeze_and_all_sixty_three_files_match(self):
        review = json.loads((HERE / 'emitter-independent-review.json').read_bytes())
        freeze = json.loads((HERE / 'emitter-freeze.json').read_bytes())
        self.assertEqual(review['status'], 'CLEARED_FOR_EXACT_CAPTURE_ONLY')
        self.assertEqual(review['files'], 63)
        self.assertEqual(review['changed_paths'], 20)
        self.assertEqual(review['independent_tests'], {'normal': 143, 'optimized': 143, 'failures': 0, 'skips': 0})
        self.assertEqual({row['path']: row['sha256'] for row in freeze['files']},
                         {name: e.sha(raw) for name, raw in self.closure.items()})
        self.assertEqual(self.data['basis'], p.BASIS)
        self.assertEqual(self.data['host']['base'], p.HOST_PARENT)
        self.assertEqual(self.data['host']['tree'], p.HOST_PARENT_TREE)

    def test_source_graph_tests_and_adi_header_remain_original_bytes(self):
        fixture = HERE / 'tests/fixtures/diagnostic-prior-preservation'
        old = json.loads((fixture / 'inputs-phase-a.json').read_bytes())
        for key in ('owners', 'artifacts', 'command_counts', 'test_source_audit', 'source_seal_sha256', 'toolchain', 'retention_bounds'):
            self.assertEqual(self.data[key], old[key], key)
        reviewed = json.loads((fixture / 'reviewed-sha256.json').read_bytes())
        actual = {Path(name).name: e.sha(raw) for name, raw in self.closure.items()
                  if name.startswith('ci/p0defensive/reviewed/')}
        self.assertEqual(actual, reviewed)
        self.assertEqual(self.data['owners']['AnisetteKit']['commit'], '227dfd8c8456cd62e4ceff4971b17afb2003d7e8')
        self.assertEqual(self.data['owners']['SideSign']['commit'], 'b28fb0b72937849d4428e9ae313209b606f859b4')



if __name__ == '__main__':
    unittest.main()
