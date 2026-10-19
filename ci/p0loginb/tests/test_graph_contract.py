"""Offline tests. Synthetic Git commits below are NOT proposed Phase B sources.

The known-source JSON fixture was derived from the actual four publication object
stores. Its future identities remain null. Temporary synthetic repositories test
the generic object-proof primitives without fabricating any publication evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import graph_contract as graph


def serialized(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def synthetic_lock(ak, *, origin='a' * 64):
    return serialized({'version': 3, 'originHash': origin, 'pins': [
        {'identity': 'anisettekit', 'kind': 'remoteSourceControl', 'location': graph.repository('AnisetteKit'), 'state': {'revision': ak}},
        {'identity': 'synthetic-dependency', 'kind': 'remoteSourceControl', 'location': 'https://github.com/example/synthetic.git', 'state': {'revision': '2' * 40, 'branch': 'main'}},
    ]})


class SyntheticGit:
    """A real, local-only Git object database with explicitly synthetic contents."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir()
        self.run('init', '--quiet')

    def run(self, *args, raw=None):
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_AUTHOR_NAME='Synthetic offline fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_NAME='Synthetic offline fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid', GIT_AUTHOR_DATE='2001-01-01T00:00:00Z', GIT_COMMITTER_DATE='2001-01-01T00:00:00Z', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(['git', '-C', str(self.path), '-c', 'core.hooksPath=' + os.devnull, *args], input=raw, env=env, stderr=subprocess.PIPE).decode().strip()

    def blob(self, raw):
        return self.run('hash-object', '-w', '--stdin', raw=raw)

    def commit(self, files, parents=(), message='SYNTHETIC OFFLINE FIXTURE'):
        self.run('read-tree', '--empty')
        for name, item in sorted(files.items()):
            mode, data = item if isinstance(item, tuple) else ('100644', item)
            oid = data if mode == '160000' else self.blob(data)
            self.run('update-index', '--add', '--cacheinfo', mode + ',' + oid + ',' + name)
        tree = self.run('write-tree')
        args = ['commit-tree', tree]
        for parent in parents:
            args += ['-p', parent]
        return self.run(*args, raw=(message + '\n').encode())


class DraftSchemaTests(unittest.TestCase):
    def setUp(self):
        self.draft = graph.parse((HERE / 'fixtures/known-source-draft-graph.json').read_bytes())

    def test_real_published_draft_has_seven_owners_and_unknown_descendants(self):
        self.assertEqual(set(graph.validate_graph(self.draft)), set(graph.OWNERS))
        self.assertEqual(len(self.draft['children']), 5)
        for name in ('SideSign', 'SideStore'):
            for key in ('commit', 'tree', 'changes'):
                self.assertIsNone(self.draft['owners'][name][key])
        for key in ('prior_artifact', 'final_sidesign', 'final_sidestore'):
            self.assertIsNone(self.draft[key])

    def test_draft_cannot_execute(self):
        with self.assertRaisesRegex(ValueError, 'not execution-ready'):
            graph.validate_graph(self.draft, execution=True)

    def test_relabelled_draft_cannot_execute(self):
        self.draft['kind'] = 'phase-b-graph-execution'
        with self.assertRaises(ValueError):
            graph.validate_graph(self.draft, execution=True)

    def test_unknown_kind_rejected(self):
        self.draft['kind'] = 'future-graph'
        with self.assertRaises(ValueError):
            graph.validate_graph(self.draft)

    def test_obsolete_seal_rejected(self):
        self.draft['source_seal_sha256'] = 'd0c3b10c5735965f7d4ccb8b90c258a7a6b72a1c3d28fd719eddb73c45cb2140'
        with self.assertRaises(ValueError):
            graph.validate_graph(self.draft)

    def test_unknown_keys_owners_children_and_urls_rejected(self):
        for mutation in ('graph-key', 'extra-owner', 'missing-owner', 'extra-child', 'missing-child', 'wrong-child-commit', 'wrong-child-tree', 'wrong-fetch-url', 'wrong-declared-url'):
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.draft)
                child = data['children']['LiveContainer/litehook']
                if mutation == 'graph-key': data['execution_ready'] = True
                elif mutation == 'extra-owner': data['owners']['unknown'] = {}
                elif mutation == 'missing-owner': del data['owners']['jktcp']
                elif mutation == 'extra-child': data['children']['LiveContainer/unknown'] = copy.deepcopy(child)
                elif mutation == 'missing-child': del data['children']['LiveContainer/OpenSSL']
                elif mutation == 'wrong-child-commit': child['commit'] = '1' * 40
                elif mutation == 'wrong-child-tree': child['tree'] = '1' * 40
                elif mutation == 'wrong-fetch-url': child['repository'] = child['declared_repository']
                elif mutation == 'wrong-declared-url': child['declared_repository'] = child['repository']
                with self.assertRaises(ValueError): graph.validate_graph(data)

    def test_no_invented_future_fields_in_draft(self):
        for key in ('prior_artifact', 'final_sidesign', 'final_sidestore'):
            data = copy.deepcopy(self.draft); data[key] = {'commit': '1' * 40}
            with self.assertRaises(ValueError): graph.validate_graph(data)
        self.draft['owners']['SideSign']['commit'] = '1' * 40
        with self.assertRaises(ValueError): graph.validate_graph(self.draft)

    def test_unchanged_ak_lc_native_tuples_not_overridable(self):
        for owner in ('AnisetteKit', 'LiveContainer', 'idevice', 'jktcp', 'minimuxer'):
            data = copy.deepcopy(self.draft); data['owners'][owner]['tree'] = '1' * 40
            with self.subTest(owner=owner), self.assertRaises(ValueError): graph.validate_graph(data)

    def test_source_paths_derive_from_exact_publication_bytes(self):
        _, publication = graph.pinned_documents()
        paths, tests = graph.source_path_allowlists(), graph.test_source_allowlists()
        for owner in graph.SOURCE_OWNERS:
            self.assertEqual(paths[owner], publication['owners'][owner]['changed_paths'])
            self.assertNotIn('Package.resolved', paths[owner])
            self.assertEqual(tests[owner], {path: value for path, value in publication['owners'][owner]['files'].items() if path.startswith(('.ci/', 'tests/', 'Tests/'))})

    def test_publication_bytes_modified_or_duplicate_keys_rejected(self):
        seal = (HERE.parent / 'source-seal.json').read_bytes()
        publication = (HERE.parent / 'publication-trees.json').read_bytes()
        with self.assertRaises(ValueError): graph.pinned_documents(seal, publication + b' ')
        with self.assertRaises(ValueError): graph.parse(b'{"key":1,"key":2}')

    def test_object_proof_cannot_admit_null_graph(self):
        with self.assertRaises(ValueError): graph.verify_source_graph({}, self.draft, None)


class SyntheticDescendantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='phase-b-SYNTHETIC-')
        self.addCleanup(self.temp.cleanup)
        self.repo = SyntheticGit(Path(self.temp.name) / 'synthetic')
        self.ak = '4' * 40  # A pin-value fixture only, never a proposed source commit.
        self.old = synthetic_lock('3' * 40)
        self.observed = synthetic_lock(self.ak, origin='b' * 64)
        self.basefiles = {'Package.resolved': self.old, 'Package.swift': b'// synthetic manifest\n', 'Sources/example.swift': b'// synthetic source\n'}
        self.base = self.repo.commit(self.basefiles)
        self.newfiles = dict(self.basefiles, **{'Package.resolved': self.observed})
        self.descendant = self.repo.commit(self.newfiles, [self.base])

    def prove_lock(self, commit=None, observed=None, terminal=None):
        observed = self.observed if observed is None else observed
        terminal = observed if terminal is None else terminal
        return graph.verify_lock_descendant(self.repo.path, self.base, commit or self.descendant, observed, terminal, anisette_commit=self.ak)

    def test_synthetic_real_objects_produce_exact_before_after(self):
        actual = self.prove_lock()
        self.assertEqual(set(actual['changes']), {'Package.resolved'})
        change = actual['changes']['Package.resolved']
        self.assertEqual(change['before']['sha256'], hashlib.sha256(self.old).hexdigest())
        self.assertEqual(change['after']['sha256'], hashlib.sha256(self.observed).hexdigest())
        self.assertEqual(change['after']['git_object'], self.repo.blob(self.observed))

    def test_unknown_commit_and_noncommit_objects_rejected(self):
        for oid in ('f' * 40, self.repo.blob(b'not a commit')):
            with self.subTest(oid=oid), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.prove_lock(oid)

    def test_extra_changed_path_rejected(self):
        files = dict(self.newfiles, **{'Sources/extra.swift': b'// hidden input\n'})
        with self.assertRaisesRegex(ValueError, 'extra or wrong'):
            self.prove_lock(self.repo.commit(files, [self.base]))

    def test_source_manifest_change_rejected(self):
        files = dict(self.newfiles, **{'Package.swift': b'// changed manifest\n'})
        with self.assertRaises(ValueError): self.prove_lock(self.repo.commit(files, [self.base]))

    def test_wrong_parent_root_and_merge_rejected(self):
        other = self.repo.commit(self.basefiles, message='SYNTHETIC other parent')
        for parents in ([], [other], [self.base, other], [self.descendant]):
            with self.subTest(parents=parents), self.assertRaisesRegex(ValueError, 'single parent'):
                self.prove_lock(self.repo.commit(self.newfiles, parents))

    def test_git_replace_cannot_forge_single_parent_proof(self):
        other = self.repo.commit(self.basefiles, message='SYNTHETIC unrelated parent')
        wrong = self.repo.commit(self.newfiles, [other])
        self.repo.run('replace', wrong, self.descendant)
        with self.assertRaisesRegex(ValueError, 'single parent'):
            self.prove_lock(wrong)

    def test_lock_mode_or_symlink_rejected(self):
        for mode in ('100755', '120000'):
            files = dict(self.newfiles, **{'Package.resolved': (mode, self.observed)})
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'mode/type'):
                self.prove_lock(self.repo.commit(files, [self.base]))

    def test_lock_deleted_rejected(self):
        files = dict(self.basefiles); del files['Package.resolved']
        with self.assertRaises(ValueError): self.prove_lock(self.repo.commit(files, [self.base]))

    def test_missing_terminal_or_different_terminal_rejected(self):
        for terminal in (None, b'changed'):
            with self.subTest(terminal=terminal), self.assertRaisesRegex(ValueError, 'terminal'):
                graph.verify_lock_descendant(self.repo.path, self.base, self.descendant, self.observed, terminal, anisette_commit=self.ak)

    def test_declared_lock_bytes_must_equal_git_blob(self):
        other = synthetic_lock(self.ak, origin='c' * 64)
        with self.assertRaisesRegex(ValueError, 'not authenticated observed'):
            self.prove_lock(observed=other)

    def test_non_ak_pin_new_pin_wrong_ak_or_schema_drift_rejected(self):
        for mutation in ('non-ak', 'new-pin', 'wrong-ak', 'missing-origin', 'version', 'duplicate-pin', 'ak-branch'):
            changed = graph.parse(self.observed)
            if mutation == 'non-ak': changed['pins'][1]['state']['revision'] = '5' * 40
            elif mutation == 'new-pin': changed['pins'].append({'identity': 'new', 'state': {'revision': '5' * 40}})
            elif mutation == 'wrong-ak': changed['pins'][0]['state']['revision'] = '5' * 40
            elif mutation == 'missing-origin': del changed['originHash']
            elif mutation == 'version': changed['version'] = 4
            elif mutation == 'duplicate-pin': changed['pins'].append(copy.deepcopy(changed['pins'][0]))
            elif mutation == 'ak-branch': changed['pins'][0]['state']['branch'] = 'main'
            raw = serialized(changed)
            files = dict(self.newfiles, **{'Package.resolved': raw})
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.prove_lock(self.repo.commit(files, [self.base]), observed=raw)

    def test_wrong_tree_rejected(self):
        with self.assertRaisesRegex(ValueError, 'tree differs'):
            graph.verify_lock_descendant(self.repo.path, self.base, self.descendant, self.observed, self.observed, expected_tree='1' * 40, anisette_commit=self.ak)

    def store(self, child):
        return {'Dependencies/SideSign': ('160000', child), graph.APP_LOCK: b'synthetic unchanged app lock\n', 'app.swift': b'// synthetic unchanged app\n'}

    def test_synthetic_exact_gitlink_descendant(self):
        base = self.repo.commit(self.store(self.base))
        final = self.repo.commit(self.store(self.descendant), [base])
        proof = graph.verify_gitlink_descendant(self.repo.path, base, final, self.base, self.descendant)
        self.assertEqual(set(proof['changes']), {graph.SIGN_LINK})
        self.assertEqual(proof['changes'][graph.SIGN_LINK]['after']['mode'], '160000')

    def test_wrong_gitlink_old_child_new_child_mode_extra_path_parent(self):
        base = self.repo.commit(self.store(self.base))
        for mutation in ('wrong-old', 'wrong-new', 'mode', 'extra-path', 'app-lock', 'parent'):
            files = self.store(self.descendant)
            if mutation == 'wrong-new': files[graph.SIGN_LINK] = ('160000', base)
            elif mutation == 'mode': files[graph.SIGN_LINK] = b'replacement regular file'
            elif mutation == 'extra-path': files['unexpected.swift'] = b'// bad\n'
            elif mutation == 'app-lock': files[graph.APP_LOCK] = b'fabricated app lock\n'
            final = self.repo.commit(files, [self.descendant if mutation == 'parent' else base])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                graph.verify_gitlink_descendant(self.repo.path, base, final, self.descendant if mutation == 'wrong-old' else self.base, self.descendant)


class SyntheticRecursiveGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='phase-b-SYNTHETIC-children-')
        self.addCleanup(self.temp.cleanup)
        self.repo = SyntheticGit(Path(self.temp.name) / 'synthetic')
        self.leaf = self.repo.commit({'README': b'SYNTHETIC leaf\n'})
        self.modules = b'[submodule "child"]\n path = child\n url = https://github.com/example/child.git\n'
        self.files = {'.gitmodules': self.modules, 'child': ('160000', self.leaf)}
        self.parent = self.repo.commit(self.files)
        self.graph = {'children': {'Synthetic/child': {'repository': 'https://github.com/example/child.git', 'declared_repository': 'https://github.com/example/child.git', 'commit': self.leaf, 'tree': graph.commit_identity(self.repo.path, self.leaf)['tree']}}}

    def test_actual_gitlink_and_committed_declared_url(self):
        self.assertEqual(graph.child_requirements('Synthetic', self.repo.path, self.parent, self.graph), self.graph['children'])
        self.assertEqual(graph.child_requirements('Synthetic/child', self.repo.path, self.leaf, self.graph), {})

    def test_extra_missing_and_wrong_child_rejected(self):
        for mutation in ('extra', 'missing', 'wrong-commit', 'wrong-url', 'wrong-path'):
            files = dict(self.files)
            if mutation == 'extra': files['hidden'] = ('160000', self.leaf)
            elif mutation == 'missing': del files['child']
            elif mutation == 'wrong-commit': files['child'] = ('160000', self.parent)
            elif mutation == 'wrong-url': files['.gitmodules'] = self.modules.replace(b'example/', b'other/')
            elif mutation == 'wrong-path': files['.gitmodules'] = self.modules.replace(b'path = child', b'path = ../escape')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                graph.child_requirements('Synthetic', self.repo.path, self.repo.commit(files), self.graph)

    def test_branch_following_or_unreviewed_options_rejected(self):
        for option in (b' branch = main\n', b' update = !evil\n', b' shallow = true\n'):
            files = dict(self.files, **{'.gitmodules': self.modules + option})
            with self.subTest(option=option), self.assertRaises(ValueError):
                graph.child_requirements('Synthetic', self.repo.path, self.repo.commit(files), self.graph)

    def test_unlisted_recursive_grandchild_rejected(self):
        self.graph['children']['Synthetic/child']['commit'] = self.parent
        with self.assertRaisesRegex(ValueError, 'missing/extra recursive'):
            graph.child_requirements('Synthetic/child', self.repo.path, self.parent, self.graph)

    def test_worktree_gitmodules_cannot_replace_committed_bytes(self):
        (self.repo.path / '.gitmodules').write_text('malicious untracked working copy\n')
        self.assertEqual(graph.child_requirements('Synthetic', self.repo.path, self.parent, self.graph), self.graph['children'])


if __name__ == '__main__':
    unittest.main()
