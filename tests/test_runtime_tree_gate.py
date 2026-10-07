"""Adversarial parity regressions confined to disposable, independent copies."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from runtime_tree_gate import BoundGit, ParityError, UPSTREAM_COMMIT, verify_repository

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = 'LiveContainerSwiftUI/App/AppDelegate.swift'
EXTRA = 'LiveContainerSwiftUI/UnexpectedMigrationSource.swift'


class WholeTreeGateRegressionTests(unittest.TestCase):
    @contextmanager
    def checkout(self):
        with tempfile.TemporaryDirectory(prefix='lc-parity-regression-') as temporary:
            copy = Path(temporary) / 'checkout'
            # Do not share objects, indexes, refs, hardlinks or worktree pointers
            # with the maintained checkout. All adversarial mutations stay here.
            shutil.copytree(ROOT, copy, symlinks=True)
            yield copy

    def commit(self, root):
        git = BoundGit(root)
        git.run('add', '--all')
        git.run('-c', 'user.name=Parity Test', '-c', 'user.email=parity@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-m', 'Disposable adversarial test')

    def test_clean_disposable_copy_passes(self):
        with self.checkout() as root:
            report = verify_repository(root)
            self.assertEqual(report['product_entries'], 274)
            self.assertEqual(report['reviewed_additions'], 17)
            self.assertEqual(report['regular_files'], 289)

    def test_shallow_upstream_boundary_is_rejected(self):
        with self.checkout() as root:
            # Truncating at the selected base can still satisfy ordinary
            # ancestor/tree checks while discarding earlier upstream history.
            (root / '.git/shallow').write_text(UPSTREAM_COMMIT + '\n')
            with self.assertRaisesRegex(ParityError, 'Shallow history is not allowed'):
                verify_repository(root)

    def test_extra_untracked_runtime_source_is_rejected(self):
        with self.checkout() as root:
            (root / EXTRA).write_text('let unexpectedMigrationRuntime = 123\n')
            with self.assertRaisesRegex(ParityError, 'Filesystem inventory mismatch'):
                verify_repository(root)

    def test_new_tracked_runtime_source_is_rejected(self):
        with self.checkout() as root:
            (root / EXTRA).write_text('let unexpectedMigrationRuntime = 123\n')
            self.commit(root)
            with self.assertRaisesRegex(ParityError, 'Committed tree inventory mismatch'):
                verify_repository(root)

    def test_ignored_runtime_source_and_empty_directories_are_rejected(self):
        for include_file in (False, True):
            with self.subTest(include_file=include_file), self.checkout() as root:
                ignored = root / '.theos'
                ignored.mkdir()
                if include_file:
                    (ignored / 'Unexpected.swift').write_text('let ignoredRuntime = 1\n')
                with self.assertRaisesRegex(ParityError, 'Filesystem inventory mismatch'):
                    verify_repository(root)

    def test_case_collision_is_rejected(self):
        with self.checkout() as root:
            (root / 'SideStoreSupport/sidestore.swift').write_text('// collides on case-insensitive volumes\n')
            with self.assertRaisesRegex(ParityError, 'Case/Unicode-colliding path'):
                verify_repository(root)

    def test_runtime_file_mode_change_is_rejected(self):
        with self.checkout() as root:
            (root / RUNTIME).chmod(0o755)
            with self.assertRaisesRegex(ParityError, 'Filesystem type/mode mismatch'):
                verify_repository(root)

    def test_committed_runtime_mode_change_is_rejected(self):
        with self.checkout() as root:
            (root / RUNTIME).chmod(0o755)
            self.commit(root)
            with self.assertRaisesRegex(ParityError, 'Git mode/type mismatch'):
                verify_repository(root)

    def test_runtime_symlink_substitution_with_identical_bytes_is_rejected(self):
        with self.checkout() as root:
            file = root / RUNTIME
            donor = root.parent / 'identical-runtime.swift'
            donor.write_bytes(file.read_bytes())
            file.unlink()
            file.symlink_to(donor)
            with self.assertRaisesRegex(ParityError, 'Filesystem type/mode mismatch'):
                verify_repository(root)

    def test_committed_type_only_substitution_is_rejected(self):
        with self.checkout() as root:
            file = root / RUNTIME
            donor = root.parent / 'identical-runtime.swift'
            donor.write_bytes(file.read_bytes())
            file.unlink()
            file.symlink_to(donor)
            self.commit(root)
            with self.assertRaisesRegex(ParityError, 'Git mode/type mismatch'):
                verify_repository(root)

    def test_reviewed_metadata_symlink_substitution_is_rejected(self):
        with self.checkout() as root:
            file = root / 'RUNTIME_SOURCE_NOTICE.md'
            donor = root.parent / 'identical-notice.md'
            donor.write_bytes(file.read_bytes())
            file.unlink()
            file.symlink_to(donor)
            with self.assertRaisesRegex(ParityError, 'Filesystem type/mode mismatch'):
                verify_repository(root)

    def test_unexpected_directory_symlink_is_rejected_without_following_it(self):
        with self.checkout() as root:
            # The target need not be readable; inventory must reject the link
            # itself without walking outside the selected checkout.
            (root / 'LiveContainerSwiftUI/UnexpectedDirectory').symlink_to(root.parent / 'missing', target_is_directory=True)
            with self.assertRaisesRegex(ParityError, 'Filesystem inventory mismatch'):
                verify_repository(root)

    def test_hardlink_substitution_with_identical_bytes_is_rejected(self):
        with self.checkout() as root:
            file = root / RUNTIME
            donor = root.parent / 'identical-runtime.swift'
            donor.write_bytes(file.read_bytes())
            file.unlink()
            os.link(donor, file)
            with self.assertRaisesRegex(ParityError, 'Hard-linked file'):
                verify_repository(root)

    def test_missing_product_file_is_rejected(self):
        with self.checkout() as root:
            (root / RUNTIME).unlink()
            with self.assertRaisesRegex(ParityError, 'Filesystem inventory mismatch'):
                verify_repository(root)

    def test_dirty_worktree_source_is_rejected(self):
        with self.checkout() as root:
            file = root / RUNTIME
            file.write_bytes(file.read_bytes() + b'\n// unexpected source mutation\n')
            with self.assertRaisesRegex(ParityError, 'Dirty or substituted working file'):
                verify_repository(root)

    def test_dirty_index_is_rejected_even_with_clean_worktree_bytes(self):
        with self.checkout() as root:
            file = root / RUNTIME
            original = file.read_bytes()
            file.write_bytes(original + b'\n// staged source mutation\n')
            BoundGit(root).run('add', '--', RUNTIME)
            file.write_bytes(original)
            with self.assertRaisesRegex(ParityError, 'Dirty index'):
                verify_repository(root)

    def test_index_assume_unchanged_flag_is_rejected(self):
        with self.checkout() as root:
            BoundGit(root).run('update-index', '--assume-unchanged', '--', RUNTIME)
            with self.assertRaisesRegex(ParityError, 'Index hiding flag'):
                verify_repository(root)

    def test_inherited_git_overrides_cannot_redirect_validation(self):
        with self.checkout() as root:
            expected_head = BoundGit(root).run('rev-parse', 'HEAD').decode().strip()
            overrides = {
                'GIT_DIR': str(ROOT / '.git'), 'GIT_WORK_TREE': str(ROOT),
                'GIT_INDEX_FILE': str(ROOT / '.git/index'), 'GIT_COMMON_DIR': str(ROOT / '.git'),
                'GIT_OBJECT_DIRECTORY': str(root.parent / 'absent-objects'),
                'GIT_ALTERNATE_OBJECT_DIRECTORIES': str(root.parent / 'absent-alternates'),
                'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.bare', 'GIT_CONFIG_VALUE_0': 'true',
                'GIT_GRAFT_FILE': str(root.parent / 'absent-grafts'), 'GIT_NO_REPLACE_OBJECTS': '0',
                'GIT_REPLACE_REF_BASE': 'refs/test-replacements/',
            }
            with patch.dict(os.environ, overrides):
                self.assertEqual(verify_repository(root)['head'], expected_head)
                file = root / RUNTIME
                file.write_bytes(file.read_bytes() + b'\n// cannot hide behind the original clean checkout\n')
                with self.assertRaisesRegex(ParityError, 'Dirty or substituted working file'):
                    verify_repository(root)

    def test_local_core_worktree_override_cannot_redirect_validation(self):
        with self.checkout() as root:
            BoundGit(root).run('config', '--local', 'core.worktree', str(ROOT))
            verify_repository(root)
            (root / EXTRA).write_text('// cannot redirect filesystem scan\n')
            with self.assertRaisesRegex(ParityError, 'Filesystem inventory mismatch'):
                verify_repository(root)

    def test_git_replacement_and_graft_views_are_ignored(self):
        with self.checkout() as root:
            git = BoundGit(root)
            expected_head = git.run('rev-parse', 'HEAD').decode().strip()
            git.run('replace', UPSTREAM_COMMIT, expected_head)
            (root / '.git/info/grafts').write_text(UPSTREAM_COMMIT + '\n' + expected_head + '\n')
            self.assertEqual(verify_repository(root)['head'], expected_head)
            (root / EXTRA).write_text('// replacement/graft views cannot hide this\n')
            self.commit(root)
            with self.assertRaisesRegex(ParityError, 'Committed tree inventory mismatch'):
                verify_repository(root)


if __name__ == '__main__':
    unittest.main()
