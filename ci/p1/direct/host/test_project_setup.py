"""Pure-local project preparation checks; no native commands or network.

All mutable inputs and generated projects are temporary copies. The preserved
prepare implementation and production extractor run for real on their text.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import FrozenInstanceError
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

import project_setup as setup


LOCAL = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('P1_PROJECT_SOURCE', str(
    LOCAL.parents[1] / 'p1-native-validation/source/LiveContainerSwiftUI/Views/V3UnifiedShell.swift')))
BUILDER = Path(os.environ.get('P1_PROJECT_BUILDER', str(
    LOCAL.parents[1] / 'p1-native-validation/builder')))
VIDEO = Path(os.environ.get('P1_PROJECT_VIDEO', str(
    LOCAL.parent / 'window-capture-candidate/ci/p1/video')))
PREFLIGHT = Path(os.environ.get('P1_PROJECT_PREFLIGHT', str(VIDEO.parent / 'preflight')))


def load_adapter(path):
    spec = importlib.util.spec_from_file_location('isolated_project_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


class ProjectPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # These tripwires apply during imports, generation, and rejection cases.
        self.stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
        for target in ('subprocess.Popen', 'subprocess.run', 'subprocess.check_call',
                       'subprocess.check_output', 'os.system', 'socket.create_connection',
                       'socket.socket.connect', 'socket.socket.connect_ex'):
            self.stack.enter_context(patch(target, side_effect=AssertionError(
                'native/process/network operation forbidden in project preparation tests')))
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix='p1-project-setup-'))).resolve()
        # Deliberately unrelated ancestry, names, and directory depths. Only
        # video's required probe sibling is retained in the relocated archive.
        self.video = self.root / 'sealed-archive/deep/video'
        self.preflight = self.root / 'independent-preflight'
        self.local = self.root / 'relocated-local'
        self.builder = self.root / 'builder'
        self.source = self.root / 'production/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
        for name in setup.VIDEO_FILES:
            copy_file(VIDEO / name, self.video / name)
        copy_file(VIDEO.parent / 'probe/capture.py', self.video.parent / 'probe/capture.py')
        for name in ('runner_ui_tests.swift', 'window_fixture.swift'):
            copy_file(PREFLIGHT / name, self.preflight / name)
        for name in setup.LOCAL_FILES:
            copy_file(LOCAL / name, self.local / name)
        copy_file(SOURCE, self.source)
        support = SOURCE.parents[2] / 'SideStoreSupport/SideStore.swift'
        if support.exists():
            copy_file(support, self.source.parents[2] / 'SideStoreSupport/SideStore.swift')
        for name in ('scripts/run_p0_signin_rendering.py', 'tests/fixtures/p0_signin_app.swift'):
            copy_file(BUILDER / name, self.builder / name)
        for name in ('scripts/templates', 'tests/fixtures/p0_signin_project'):
            shutil.copytree(BUILDER / name, self.builder / name)
        self.adapter = load_adapter(self.local / 'host/project_setup.py')
        self.build = self.root / 'fresh-build'
        self.output = self.root / 'fresh-output'

    def arguments(self):
        return dict(video_dir=self.video, preflight_dir=self.preflight, local_dir=self.local)

    def hashes(self):
        return self.adapter.source_hashes(self.source, self.builder, **self.arguments())

    def prepare(self, expected=None, **overrides):
        arguments = self.arguments()
        arguments.update(expected_sources=self.hashes() if expected is None else expected)
        arguments.update(overrides)
        return self.adapter.prepare(self.source, self.builder, self.build, self.output, **arguments)

    def reject(self, message, expected=None):
        with self.assertRaisesRegex(ValueError, message):
            self.prepare(expected)
        self.assertFalse((self.output / 'direct-project-preparation.json').exists())

    def rebind_candidate(self, folder):
        candidate = self.local / folder / ('app.swift' if folder == 'fixture' else 'ui_tests.swift')
        binding_path = self.local / folder / 'source-binding.json'
        binding = json.loads(binding_path.read_text())
        binding['candidateSHA256'] = setup.digest(candidate)
        binding_path.write_text(json.dumps(binding))

    def test_real_prepare_exactly_replaces_two_fragments_and_preserves_all_other_sources(self):
        expected = self.hashes()
        result = self.prepare(expected)
        baseline_build = self.root / 'baseline-build'
        baseline_output = self.root / 'baseline-output'
        baseline_output.mkdir()
        with self.adapter._video_module(self.video) as legacy:
            legacy.prepare(self.source, self.builder, baseline_build, baseline_output)
        before = {p.name: p.read_bytes() for p in (baseline_build / 'Sources').iterdir()}
        after = {p.name: p.read_bytes() for p in (self.build / 'Sources').iterdir()}
        self.assertEqual(set(before), set(after))
        changed = {name for name in before if before[name] != after[name]}
        self.assertEqual(changed, {'p0_signin_app.swift', 'p0_signin_ui_tests.swift'})
        for name, original, candidate in (
            ('p0_signin_app.swift', self.video / 'app.swift', self.local / 'fixture/app.swift'),
            ('p0_signin_ui_tests.swift', self.video / 'ui_tests.swift', self.local / 'handoff/ui_tests.swift'),
        ):
            old, new = original.read_bytes(), candidate.read_bytes()
            self.assertEqual(before[name].count(old), 1)
            self.assertEqual(after[name].count(new), 1)
            self.assertEqual(after[name].replace(new, old, 1), before[name])
        self.assertTrue(after['p0_signin_ui_tests.swift'].endswith(
            b'\n' + (self.video / 'recovery_ui_tests.swift').read_bytes()))
        self.assertEqual({p.name: p.read_bytes() for p in (self.output / 'sources').iterdir()}, after)
        self.assertEqual((self.output / 'preserved-source-identity.json').read_bytes(),
                         (baseline_output / 'source-identity.json').read_bytes())
        self.assertEqual(result.project, self.build / 'P0SignIn.xcodeproj')
        self.assertTrue(result.project.is_dir())
        self.assertEqual(Path(result.renderer.__file__), self.builder / 'scripts/run_p0_signin_rendering.py')
        self.assertEqual(self.hashes(), expected)

    def test_identity_and_receipt_are_canonical_honest_and_bound_to_actual_generated_bytes(self):
        result = self.prepare()
        identity = json.loads(result.source_identity_bytes)
        receipt = json.loads(result.receipt_bytes)
        self.assertEqual(result.source_identity_bytes, self.adapter.canonical(identity))
        self.assertEqual(result.receipt_bytes, self.adapter.canonical(receipt))
        self.assertEqual((self.output / 'source-identity.json').read_bytes(), result.source_identity_bytes)
        self.assertEqual((self.output / 'direct-project-preparation.json').read_bytes(), result.receipt_bytes)
        self.assertEqual(identity['generated_sources_sha256'], {
            p.name: setup.digest(p) for p in (self.build / 'Sources').iterdir() if p.is_file()})
        self.assertEqual(identity['preserved_source_identity_sha256'],
                         setup.digest(self.output / 'preserved-source-identity.json'))
        self.assertEqual(receipt['sourceIdentitySHA256'], sha256(result.source_identity_bytes).hexdigest())
        self.assertEqual(receipt['sourceHashes'], self.hashes())
        self.assertEqual(receipt['originalVideoPrepareSHA256'], setup.PREPARE_SHA256)
        self.assertEqual(receipt['replacedFragments'], ['video/app.swift', 'video/ui_tests.swift'])
        self.assertIs(identity['observer_instrumented'], True)
        self.assertIs(identity['production_source_instrumented'], False)
        self.assertIs(identity['full_matrix_complete'], False)
        self.assertIn('Test-only observer instrumentation', identity['instrumentation'])
        self.assertIn('no native execution', identity['scope'])
        for document in (identity, receipt):
            for flag in ('nativeCompiled', 'nativeExecuted', 'admissionEligible'):
                self.assertIs(document[flag], False)
        with self.assertRaises(FrozenInstanceError):
            result.project = self.root / 'other'

    def test_explicit_staged_paths_work_without_original_workspace_ancestry(self):
        self.assertFalse((self.local.parent / 'window-capture-candidate').exists())
        self.assertNotEqual(self.preflight.parent, self.video.parent)
        result = self.prepare()
        self.assertTrue(result.project.is_dir())
        self.assertFalse(any(self.root.rglob('__pycache__')))

    def test_hash_inventory_is_sorted_complete_and_relative(self):
        observed = self.hashes()
        self.assertEqual(list(observed), sorted(observed))
        for name in setup.VIDEO_FILES:
            self.assertEqual(observed['video/' + name], setup.digest(self.video / name))
        for name in setup.LOCAL_FILES:
            self.assertEqual(observed['local/' + name], setup.digest(self.local / name))
        for name in ('probe/capture.py', 'preflight/window_fixture.swift',
                     'preflight/runner_ui_tests.swift', 'production/V3UnifiedShell.swift',
                     'builder/scripts/run_p0_signin_rendering.py'):
            self.assertIn(name, observed)
        self.assertTrue(all(not Path(name).is_absolute() and len(value) == 64
                            for name, value in observed.items()))

    def test_stale_expected_source_map_rejects_before_creating_paths(self):
        expected = self.hashes()
        self.source.write_text(self.source.read_text() + '\n// staged drift\n')
        self.reject('owned expected source binding differs', expected)
        self.assertFalse(self.build.exists())
        self.assertFalse(self.output.exists())

    def test_expected_source_map_must_be_exact_plain_dict(self):
        class Map(dict):
            pass
        valid = self.hashes()
        for expected in ({}, dict(valid, unexpected='0' * 64), Map(valid)):
            with self.subTest(kind=type(expected).__name__, count=len(expected)):
                self.reject('owned expected source binding differs', expected)

    def test_reapproved_source_drift_is_still_rejected_by_preserved_prepare(self):
        self.source.write_text(self.source.read_text() + '\n// staged drift\n')
        self.reject('actual source hash differs')

    def test_reapproved_video_capture_drift_is_still_rejected(self):
        path = self.video / 'capture.py'
        path.write_text(path.read_text() + '\n# staged drift\n')
        self.reject('reviewed video capture source drift')
        self.assertFalse(self.output.exists())

    def test_source_changed_during_real_generation_is_rejected_without_final_receipt(self):
        original = self.adapter._video_module
        @contextmanager
        def mutate_after_prepare(video):
            with original(video) as legacy:
                real_prepare = legacy.prepare
                def prepare_then_mutate(*args):
                    result = real_prepare(*args)
                    self.source.write_text(self.source.read_text() + '\n// concurrent staged change\n')
                    return result
                legacy.prepare = prepare_then_mutate
                yield legacy
        with patch.object(self.adapter, '_video_module', mutate_after_prepare):
            self.reject('input source changed during project preparation')

    def test_existing_file_or_directory_paths_are_rejected_without_overwrite(self):
        for target, kind in ((self.build, 'directory'), (self.output, 'file')):
            with self.subTest(path=target.name):
                if kind == 'directory':
                    target.mkdir()
                else:
                    target.write_text('sentinel')
                self.reject('fresh canonical preparation directory required')
                if kind == 'directory':
                    self.assertEqual(list(target.iterdir()), [])
                    target.rmdir()
                else:
                    self.assertEqual(target.read_text(), 'sentinel')
                    target.unlink()

    def test_equal_preparation_paths_are_rejected(self):
        self.output = self.build
        self.reject('preparation paths must be separate')
        self.assertFalse(self.build.exists())

    def test_relative_noncanonical_missing_parent_and_nested_paths_are_rejected(self):
        original = self.build
        directory = self.root / 'existing'
        directory.mkdir()
        paths = (Path('relative-build'), directory / '..' / 'build',
                 self.root / 'missing-parent/build', self.output / 'nested-build')
        for path in paths:
            with self.subTest(path=str(path)):
                self.build = path
                self.reject('fresh canonical preparation directory required')
                self.assertFalse(self.output.exists())
        self.build = original

    def test_dangling_output_symlink_is_rejected(self):
        self.output.symlink_to(self.root / 'absent')
        self.reject('fresh canonical preparation directory required')
        self.assertTrue(self.output.is_symlink())
        self.assertFalse((self.root / 'absent').exists())

    def test_input_symlink_is_rejected(self):
        linked = self.root / 'linked-source.swift'
        linked.symlink_to(self.source)
        self.source = linked
        self.reject('canonical unlinked input path required')

    def test_linked_builder_inventory_member_is_rejected(self):
        (self.builder / 'scripts/templates/linked.swift').symlink_to(self.source)
        self.reject('linked builder member')

    def test_missing_explicit_preflight_does_not_fall_back_to_sibling(self):
        self.preflight = self.root / 'absent-preflight'
        self.reject('missing source-bound input')

    def test_missing_preserved_probe_sibling_is_rejected(self):
        (self.video.parent / 'probe/capture.py').unlink()
        self.reject('missing source-bound input')

    def test_supplied_local_directory_must_own_executing_adapter(self):
        with self.assertRaisesRegex(ValueError, 'running project adapter differs'):
            self.adapter.source_hashes(self.source, self.builder, video_dir=self.video,
                                       preflight_dir=self.preflight, local_dir=LOCAL)

    def test_generated_app_drift_is_rejected_even_with_updated_candidate_binding(self):
        path = self.local / 'fixture/app.swift'
        path.write_text(path.read_text() + '\n// unexpected fixture edit\n')
        self.rebind_candidate('fixture')
        self.reject('generated fixture source differs')
        self.assertFalse(self.output.exists())

    def test_generated_ui_reconstruction_rejects_changed_original_actions(self):
        path = self.local / 'handoff/ui_tests.swift'
        text = path.read_text()
        anchor = 'baselineReady.tap()'
        self.assertEqual(text.count(anchor), 1)
        path.write_text(text.replace(anchor, 'baselineReady.doubleTap()', 1))
        self.rebind_candidate('handoff')
        self.reject('original production actions/delays/source do not reconstruct')

    def test_generated_ui_reconstruction_rejects_duplicate_instrumentation_boundary(self):
        observer = self.adapter._module('test_observer_generator', self.local / 'handoff/build_candidate.py')
        path = self.local / 'handoff/ui_tests.swift'
        path.write_text(path.read_text() + observer.START)
        self.rebind_candidate('handoff')
        self.reject('observer source reconstruction boundary differs')

    def test_ambiguous_original_fixture_fragment_in_builder_is_rejected(self):
        path = self.builder / 'tests/fixtures/p0_signin_app.swift'
        path.write_text(path.read_text() + '\n' + (self.video / 'app.swift').read_text())
        self.reject('original video fixture boundary differs')

    def test_ambiguous_original_builder_entry_point_is_rejected(self):
        path = self.builder / 'tests/fixtures/p0_signin_app.swift'
        path.write_text(path.read_text() + '\n@main @MainActor struct P0SignInApp: App\n')
        self.reject('baseline entry point drift')

    def test_generated_candidate_hash_and_false_native_flags_are_required(self):
        for folder in ('fixture', 'handoff'):
            path = self.local / folder / 'source-binding.json'
            original = path.read_text()
            for field, value in (('candidateSHA256', '0' * 64), ('nativeCompiled', True),
                                 ('nativeExecuted', True), ('admissionEligible', True)):
                with self.subTest(folder=folder, field=field):
                    binding = json.loads(original)
                    binding[field] = value
                    path.write_text(json.dumps(binding))
                    self.reject('unbound generated candidate')
                    path.write_text(original)

    def test_sealed_preflight_drift_is_rejected(self):
        path = self.preflight / 'runner_ui_tests.swift'
        path.write_text(path.read_text() + '\n// staged preflight drift\n')
        self.reject('sealed observer source differs')

    def test_import_state_is_restored_after_success_and_exception(self):
        path_before = list(sys.path)
        bytecode_before = sys.dont_write_bytecode
        with ExitStack() as stack:
            sentinels = {}
            for name in setup.IMPORT_NAMES:
                sentinel = ModuleType(name)
                sentinel.__file__ = str(self.root / 'wrong-import' / (name + '.py'))
                sentinels[name] = sentinel
            stack.enter_context(patch.dict(sys.modules, sentinels))
            for fail in (False, True):
                with self.subTest(fail=fail):
                    try:
                        with self.adapter._video_module(self.video) as legacy:
                            self.assertEqual(Path(legacy.__file__), self.video / 'capture.py')
                            for name, sentinel in sentinels.items():
                                self.assertIsNot(sys.modules[name], sentinel)
                                self.assertEqual(Path(sys.modules[name].__file__), self.video / (name + '.py'))
                            if fail:
                                raise RuntimeError('deliberate test exception')
                    except RuntimeError as error:
                        self.assertTrue(fail)
                        self.assertEqual(str(error), 'deliberate test exception')
                    self.assertEqual(sys.path, path_before)
                    self.assertEqual(sys.dont_write_bytecode, bytecode_before)
                    for name, sentinel in sentinels.items():
                        self.assertIs(sys.modules[name], sentinel)


if __name__ == '__main__':
    unittest.main()
