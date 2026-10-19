"""Read-only official archive tests and explicitly synthetic output transitions.

The failed capture retained the generated header's SHA256, not its raw bytes.
Every positive generated-output test therefore patches that expectation to the
hash of controlled synthetic bytes. None asserts possession or reproduction of
the actual generated header. Dependency members are parsed only as inert data;
no dependency source, build script, Cargo command or native program is executed.
"""
import copy
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import cargo_contract as c
import native_build as native


class PlistGeneratedOutputTests(unittest.TestCase):
    SYNTHETIC_HEADER = b'/* Controlled synthetic test header, not captured output. */\nvoid fixture_only(void);\n'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.raw = (HERE / 'tests/fixtures/plist-generated-header/plist_ffi-0.1.6.crate').read_bytes()
        self.home = self.base / 'cargo-home'
        self.root = self.home / 'registry/src/index/plist_ffi-0.1.6'
        self.root.mkdir(parents=True)
        archive = self.home / 'registry/cache/index/plist_ffi-0.1.6.crate'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(self.raw)
        self.files = {}
        # Validate every member before constructing a destination. In particular,
        # do not use extract()/extractall() or preserve archive permissions.
        with tarfile.open(fileobj=io.BytesIO(self.raw), mode='r:gz') as tar:
            for member in tar:
                name = PurePosixPath(member.name)
                self.assertFalse(name.is_absolute())
                self.assertNotIn('..', name.parts)
                self.assertEqual(str(name), member.name)
                self.assertGreater(len(name.parts), 1)
                self.assertEqual(name.parts[0], 'plist_ffi-0.1.6')
                self.assertTrue(member.isfile())
                relative = '/'.join(name.parts[1:])
                self.assertNotIn(relative, self.files)
                stream = tar.extractfile(member)
                self.assertIsNotNone(stream)
                self.files[relative] = stream.read()
        for relative, raw in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.expected = {path: c.sha(raw) for path, raw in self.files.items()}
        (self.root / '.cargo-ok').write_bytes(b'{"v":1}')
        (self.root / '.cargo-checksum.json').write_text(json.dumps({'package': c.PLIST_ARCHIVE}))
        self.package = {'name': 'plist_ffi', 'version': '0.1.6', 'source': c.REGISTRY,
                        'manifest_path': str(self.root / 'Cargo.toml')}
        self.header = self.root / 'plist.h'

    def synthetic_hash(self):
        return mock.patch.object(c, 'PLIST_GENERATED_SHA256', c.sha(self.SYNTHETIC_HEADER))

    def before(self):
        return c.registry_source(self.package, self.home, c.PLIST_ARCHIVE, phase='before')

    def after(self, before, snapshots):
        return c.registry_source(self.package, self.home, c.PLIST_ARCHIVE,
                                 phase='after', before=before, generated_snapshots=snapshots)

    def whole_proof(self, package):
        # This is synthetic surrounding provenance, not real Cargo metadata.
        return {'source_inputs': {'idevice': {'commit': '1' * 40}},
                'local_packages': {'idevice-ffi': 'synthetic-local-id'},
                'registry_packages': {c.PLIST_PACKAGE_ID: package,
                                      'synthetic-other': {'source_files': {'src.rs': '2' * 64}}},
                'transport_features': {'active_openssl': False},
                'metadata_sha256': '3' * 64,
                'workspace_root': str(self.base / 'idevice'),
                'target_directory': str(self.base / 'cargo-target')}

    def receipt_inputs(self):
        argv = [self.base / 'rustup', 'run', 'synthetic-fixed-toolchain', 'cargo', 'build', '--frozen']
        command = {'argv': list(map(str, argv)), 'cwd': str(self.base)}
        settled = {'returncode': 0, 'terminationReturncode': 0,
                   'ownedProcessGroup': {'pgid': 12345, 'leaderReaped': True,
                                         'pipesJoined': True, 'quiescent': True,
                                         'reapedBeforeSignals': True, 'signals': [], 'errors': []}}
        return argv, command, settled

    def execution(self):
        argv, command, settled = self.receipt_inputs()
        return c.verify_generated_build_receipt(json.dumps(command).encode(),
            json.dumps(settled).encode(), b'0\n', argv, self.base)

    def synthetic_transition(self):
        before = self.whole_proof(self.before())
        self.header.write_bytes(self.SYNTHETIC_HEADER)
        after = self.whole_proof(self.after(before['registry_packages'][c.PLIST_PACKAGE_ID], {}))
        return before, after, self.execution()

    def test_official_archive_and_captured_hash_constants_are_exact(self):
        self.assertEqual(len(self.raw), 92451)
        self.assertEqual(c.PLIST_ARCHIVE_BYTES, 92451)
        self.assertEqual(c.sha(self.raw), '35ed070b06d9f2fdd7e816ef784fb07b09672f2acf37527f810dbedf450b7769')
        self.assertEqual(c.PLIST_ARCHIVE, c.sha(self.raw))
        self.assertEqual(len(self.expected), 148)
        self.assertNotIn('plist.h', self.expected)
        self.assertIn('cpp/include/plist/plist.h', self.expected)
        self.assertEqual(self.expected['build.rs'], '3f113baab2c64102e29141a0e66743151aeaaee6404d64971bb5f664853b0819')
        self.assertEqual(c.PLIST_BUILD_SCRIPT, self.expected['build.rs'])
        self.assertEqual(c.inventory_digest(self.expected), '05ab62152e8a519f8304838df72c6dca760804b212b8bda6b478ecad92c20f0d')
        self.assertEqual(c.PLIST_SOURCE_INVENTORY, c.inventory_digest(self.expected))
        self.assertEqual(c.PLIST_GENERATED_SHA256, '869710f970cde3b6dcb9f68d8c78b42d6717ade0a051e634fb6e12c8365d42f5')
        self.assertNotEqual(c.PLIST_GENERATED_SHA256, c.sha(self.SYNTHETIC_HEADER))
        self.assertEqual(c.PLIST_GENERATED_MAX_BYTES, 256 * 1024)
        fixture = HERE / 'tests/fixtures/plist-generated-header'
        identity = json.loads((fixture / 'capture-identity.json').read_bytes())
        captured_raw = (fixture / 'cargo-registry-mismatch-after.json').read_bytes()
        self.assertEqual(identity['run_id'], 39220303168)
        self.assertEqual(identity['artifact_zip_sha256'], 'a0a78380aab0bae83cac295b15bb023da31e714f7c2bc71329c6fc86ba6fa7cf')
        self.assertEqual(identity['member'], 'provenance/cargo-registry-mismatch-after.json')
        self.assertEqual(identity['member_sha256'], 'f34c9ca92fc41580163f3427d7af9c24b5644409b7b7e4c3fc02e6b3800ed786')
        self.assertEqual(c.sha(captured_raw), identity['member_sha256'])
        captured = json.loads(captured_raw)
        self.assertEqual(captured['expected_files'], self.expected)
        self.assertEqual(captured['actual_files'], {**self.expected, 'plist.h': c.PLIST_GENERATED_SHA256})
        self.assertEqual(captured['extra'], {'plist.h': c.PLIST_GENERATED_SHA256})
        self.assertEqual(captured['missing'], {})
        self.assertEqual(captured['changed'], {})
        self.assertFalse(captured['source_equality_passed'])

    def test_before_requires_absence_and_retains_all_148_original_hashes(self):
        proof = self.before()
        self.assertEqual(proof['source_files'], self.expected)
        self.assertEqual(proof['generated_output_state'], c.plist_generated_state(False))
        self.assertNotIn('generated_artifacts', proof)
        self.assertNotIn('observed_files', proof)
        self.assertEqual(set(proof['cargo_generated_files']), {'.cargo-ok', '.cargo-checksum.json'})
        self.assertFalse(self.header.exists())

    def test_preexisting_header_rejects_even_when_its_hash_matches(self):
        self.header.write_bytes(self.SYNTHETIC_HEADER)
        with self.synthetic_hash(), self.assertRaises(c.RegistrySourceMismatch) as caught:
            self.before()
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic['extra'], {'plist.h': c.sha(self.SYNTHETIC_HEADER)})
        self.assertEqual(diagnostic['generated_output_checkpoint']['phase'], 'before')
        self.assertFalse(diagnostic['source_equality_passed'])

    def test_synthetic_after_preserves_sources_and_snapshot_after_path_replacement(self):
        with self.synthetic_hash():
            before = self.before()
            self.header.write_bytes(self.SYNTHETIC_HEADER)
            original = self.header.stat()
            snapshots = {}
            after = self.after(before, snapshots)
        self.assertEqual(after['source_files'], self.expected)
        self.assertEqual(after['observed_files'], {**self.expected, 'plist.h': c.sha(self.SYNTHETIC_HEADER)})
        self.assertEqual(len(after['observed_files']), 149)
        self.assertEqual(after['cargo_generated_files'], before['cargo_generated_files'])
        artifact = after['generated_artifacts']['plist.h']
        self.assertEqual(artifact, {'bytes': len(self.SYNTHETIC_HEADER), 'sha256': c.sha(self.SYNTHETIC_HEADER),
                                  'file_identity': {'device': original.st_dev, 'inode': original.st_ino}})
        replacement = self.base / 'replacement-header'
        replacement.write_bytes(b'different later bytes')
        replacement.replace(self.header)
        self.assertEqual(snapshots, {c.PLIST_SNAPSHOT_KEY: self.SYNTHETIC_HEADER})
        self.assertEqual(c.sha(snapshots[c.PLIST_SNAPSHOT_KEY]), artifact['sha256'])
        self.assertNotEqual(self.header.stat().st_ino, artifact['file_identity']['inode'])

    def test_after_requires_exact_before_proof_and_raw_evidence_collector(self):
        with self.synthetic_hash():
            before = self.before()
            self.header.write_bytes(self.SYNTHETIC_HEADER)
            invalid = [None, {}, dict(before, generated_output_state=c.plist_generated_state(True)),
                       dict(before, source_files={}), dict(before, archive_sha256='0' * 64),
                       dict(before, manifest_path=str(self.base / 'elsewhere/Cargo.toml'))]
            for prior in invalid:
                with self.subTest(prior=prior), self.assertRaises(ValueError):
                    self.after(prior, {})
            for source in (None, 'registry+https://unreviewed.invalid/index', 'git+https://unreviewed.invalid/plist'):
                snapshots = {}
                with self.subTest(source=source), self.assertRaises(c.RegistrySourceMismatch):
                    c.registry_source(dict(self.package, source=source), self.home, c.PLIST_ARCHIVE,
                                      phase='after', before=before, generated_snapshots=snapshots)
                self.assertEqual(snapshots, {})
            with self.assertRaisesRegex(ValueError, 'raw evidence snapshot required'):
                self.after(before, None)
            with self.assertRaisesRegex(ValueError, 'duplicate generated header snapshot'):
                self.after(before, {c.PLIST_SNAPSHOT_KEY: b'old snapshot'})
            with self.assertRaisesRegex(ValueError, 'finite Cargo source checkpoint'):
                c.registry_source(self.package, self.home, c.PLIST_ARCHIVE, phase='other')

    def test_missing_wrong_hash_empty_and_oversized_after_outputs_reject(self):
        with self.synthetic_hash():
            before = self.before()
            for raw in (None, b'wrong generated content', b'', b'x' * (c.PLIST_GENERATED_MAX_BYTES + 1)):
                with self.subTest(size=None if raw is None else len(raw)):
                    if self.header.exists():
                        self.header.unlink()
                    if raw is not None:
                        self.header.write_bytes(raw)
                    snapshots = {}
                    with self.assertRaises(c.RegistrySourceMismatch) as caught:
                        self.after(before, snapshots)
                    self.assertFalse(caught.exception.diagnostic['source_equality_passed'])
                    if raw == b'wrong generated content':
                        self.assertEqual(snapshots[c.PLIST_SNAPSHOT_KEY], raw)
                    else:
                        self.assertEqual(snapshots, {})

    def test_each_of_the_148_original_files_remains_immutable(self):
        with self.synthetic_hash():
            before = self.before()
            self.header.write_bytes(self.SYNTHETIC_HEADER)
            for relative, original in self.files.items():
                path = self.root / relative
                for mode in ('changed', 'missing'):
                    with self.subTest(path=relative, mode=mode):
                        if mode == 'changed':
                            path.write_bytes(original + b'\nsynthetic mutation\n')
                        else:
                            path.unlink()
                        try:
                            with self.assertRaises(ValueError):
                                self.after(before, {})
                        finally:
                            path.write_bytes(original)

    def test_extra_header_spellings_hardlink_alias_and_symlinks_reject(self):
        with self.synthetic_hash():
            before = self.before()
            # A case spelling must itself be rejected, even on a case-insensitive
            # host where two differently cased directory entries cannot coexist.
            for relative in ('Plist.h', 'PLIST.H', 'nested/plist.h'):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.SYNTHETIC_HEADER)
                try:
                    with self.subTest(path=relative), self.assertRaises(ValueError):
                        self.after(before, {})
                finally:
                    path.unlink()
            self.header.write_bytes(self.SYNTHETIC_HEADER)
            extra = self.root / 'plist-copy.h'
            extra.hardlink_to(self.header)
            with self.assertRaises(c.RegistrySourceMismatch):
                self.after(before, {})
            extra.unlink()
            extra.symlink_to(self.header)
            with self.assertRaises(ValueError):
                self.after(before, {})
            extra.unlink()
            self.header.unlink()
            outside = self.base / 'outside-header'
            outside.write_bytes(self.SYNTHETIC_HEADER)
            self.header.symlink_to(outside)
            with self.assertRaises(ValueError):
                self.after(before, {})
            with self.assertRaises(c.RegistrySourceMismatch):
                c.generated_header_snapshot(self.header)

    def test_snapshot_rejects_file_identity_changes_before_or_during_read(self):
        self.header.write_bytes(self.SYNTHETIC_HEADER)
        original_fstat = c.os.fstat
        for changed_call in (1, 2):
            calls = []
            def changing(fd):
                observed = original_fstat(fd)
                calls.append(fd)
                if len(calls) != changed_call:
                    return observed
                return SimpleNamespace(**{key: getattr(observed, key) + (1 if key == 'st_ctime_ns' else 0)
                    for key in ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_mtime_ns', 'st_ctime_ns')})
            with self.subTest(changed_call=changed_call), mock.patch.object(c.os, 'fstat', changing):
                with self.assertRaises(c.RegistrySourceMismatch) as caught:
                    c.generated_header_snapshot(self.header)
            self.assertEqual(caught.exception.diagnostic['reason'], 'BOUNDED_ORDINARY_STABLE_SNAPSHOT_REQUIRED')

    def test_snapshot_rejects_symlink_replacement_at_open_boundary(self):
        self.header.write_bytes(self.SYNTHETIC_HEADER)
        outside = self.base / 'outside-header'
        outside.write_bytes(self.SYNTHETIC_HEADER)
        original_open = os.open
        def replace_at_open(path, flags, *args, **kwargs):
            self.assertEqual(Path(path), self.header)
            self.assertTrue(flags & os.O_NOFOLLOW)
            self.assertTrue(flags & os.O_NONBLOCK)
            self.assertTrue(flags & os.O_CLOEXEC)
            self.header.unlink()
            self.header.symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)
        with mock.patch.object(c.os, 'open', side_effect=replace_at_open) as opened:
            with mock.patch.object(c.os, 'fdopen') as reader:
                with self.assertRaises(c.RegistrySourceMismatch):
                    c.generated_header_snapshot(self.header)
                reader.assert_not_called()
            opened.assert_called_once()
        self.assertEqual(outside.read_bytes(), self.SYNTHETIC_HEADER)

    def test_snapshot_rejects_fifo_replacement_without_open_or_read_blocking(self):
        self.header.write_bytes(self.SYNTHETIC_HEADER)
        original_open = os.open
        descriptors = []
        def replace_at_open(path, flags, *args, **kwargs):
            self.assertEqual(Path(path), self.header)
            # Assert nonblocking before opening any FIFO. The mocked fdopen
            # boundary below also prevents a FIFO read if validation regresses.
            self.assertTrue(flags & os.O_NONBLOCK)
            self.header.unlink()
            os.mkfifo(self.header)
            descriptor = original_open(path, flags, *args, **kwargs)
            descriptors.append(descriptor)
            return descriptor
        with mock.patch.object(c.os, 'open', side_effect=replace_at_open):
            with mock.patch.object(c.os, 'fdopen', side_effect=AssertionError('FIFO must never be read')) as reader:
                with self.assertRaises(c.RegistrySourceMismatch):
                    c.generated_header_snapshot(self.header)
                reader.assert_not_called()
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])  # Rejection must also close the descriptor.

    def test_snapshot_rejects_growth_at_open_and_after_open_before_bounded_read(self):
        original_open, original_fdopen = os.open, os.fdopen
        for boundary in ('open', 'read'):
            self.header.write_bytes(self.SYNTHETIC_HEADER)
            read_sizes = []
            def grow():
                self.header.write_bytes(b'x' * (c.PLIST_GENERATED_MAX_BYTES + 1))
            def open_boundary(path, flags, *args, **kwargs):
                self.assertEqual(Path(path), self.header)
                if boundary == 'open':
                    grow()
                return original_open(path, flags, *args, **kwargs)
            def read_boundary(descriptor, *args, **kwargs):
                self.assertEqual(boundary, 'read', 'oversized opened file must reject before reading')
                grow()
                stream = original_fdopen(descriptor, *args, **kwargs)
                class BoundedReadProbe:
                    def __enter__(self):
                        stream.__enter__()
                        return self
                    def read(self, size):
                        read_sizes.append(size)
                        return stream.read(size)
                    def __exit__(self, *exc):
                        return stream.__exit__(*exc)
                return BoundedReadProbe()
            with self.subTest(boundary=boundary), mock.patch.object(c.os, 'open', side_effect=open_boundary):
                with mock.patch.object(c.os, 'fdopen', side_effect=read_boundary):
                    with self.assertRaises(c.RegistrySourceMismatch):
                        c.generated_header_snapshot(self.header)
            self.assertEqual(read_sizes, [] if boundary == 'open' else [c.PLIST_GENERATED_MAX_BYTES + 1])

    def test_generated_checkpoint_enrichment_is_included_in_diagnostic_size_limit(self):
        def serialized_size(value):
            return len((json.dumps(value, indent=2, sort_keys=True) + '\n').encode('utf-8'))
        with self.synthetic_hash():
            before = self.before()
            wrong = b'synthetic incorrect output'
            self.header.write_bytes(wrong)
            actual = {**self.expected, 'plist.h': c.sha(wrong)}
            baseline = c.registry_mismatch_diagnostic(self.package, c.PLIST_ARCHIVE,
                len(self.raw), self.expected, actual, before['cargo_generated_files'])
            self.assertTrue(baseline['complete'])
            limit = serialized_size(baseline) + 16
            with mock.patch.object(c, 'REGISTRY_DIAGNOSTIC_MAX_BYTES', limit):
                without_checkpoint = c.registry_mismatch_diagnostic(self.package, c.PLIST_ARCHIVE,
                    len(self.raw), self.expected, actual, before['cargo_generated_files'])
                self.assertTrue(without_checkpoint['complete'])
                self.assertLessEqual(serialized_size(without_checkpoint), limit)
                with self.assertRaises(c.RegistrySourceMismatch) as caught:
                    self.after(before, {})
            diagnostic = caught.exception.diagnostic
            self.assertFalse(diagnostic['complete'])
            self.assertEqual(diagnostic['bound_failure'], 'SERIALIZED_SIZE_LIMIT')
            self.assertEqual(diagnostic['counts']['expected'], 148)
            self.assertEqual(diagnostic['counts']['actual'], 149)
            self.assertNotIn('actual_files', diagnostic)
            self.assertNotIn('expected_files', diagnostic)
            self.assertEqual(diagnostic['generated_output_checkpoint'], {
                'phase': 'after', 'path': 'plist.h', 'expected_present': True,
                'observed_present': True, 'expected_sha256': c.sha(self.SYNTHETIC_HEADER)})
            self.assertLessEqual(serialized_size(diagnostic), limit)

    def test_synthetic_transition_binds_exact_before_after_and_owned_receipt(self):
        with self.synthetic_hash():
            before, after, execution = self.synthetic_transition()
            untouched = copy.deepcopy((before, after, execution))
            proof = c.verify_generated_transition(before, after, execution)
        self.assertEqual((before, after, execution), untouched)
        self.assertEqual(proof['status'], 'EXACT_GENERATED_HEADER_TRANSITION_VERIFIED')
        self.assertEqual(proof['producer_execution'], execution)
        self.assertEqual(proof['generated_artifact'], after['registry_packages'][c.PLIST_PACKAGE_ID]['generated_artifacts']['plist.h'])
        self.assertEqual(proof['immutable_source_inventory_sha256'], c.inventory_digest(self.expected))
        self.assertEqual(proof['observed_after_inventory_sha256'], c.inventory_digest({**self.expected, 'plist.h': c.sha(self.SYNTHETIC_HEADER)}))

    def test_transition_rejects_every_other_provenance_change(self):
        with self.synthetic_hash():
            before, after, execution = self.synthetic_transition()
            paths = [('source_inputs',), ('local_packages',), ('transport_features',),
                     ('metadata_sha256',), ('workspace_root',), ('target_directory',),
                     ('registry_packages', 'synthetic-other'),
                     ('registry_packages', c.PLIST_PACKAGE_ID, 'archive_sha256'),
                     ('registry_packages', c.PLIST_PACKAGE_ID, 'manifest_path'),
                     ('registry_packages', c.PLIST_PACKAGE_ID, 'cargo_generated_files'),
                     ('registry_packages', c.PLIST_PACKAGE_ID, 'source_files'),
                     ('registry_packages', c.PLIST_PACKAGE_ID, 'observed_files')]
            for path in paths:
                altered = copy.deepcopy(after)
                target = altered
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = 'different provenance'
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'immutable source/provenance changed'):
                    c.verify_generated_transition(before, altered, execution)
            for altered in (dict(after, extra='unreviewed'), {k: v for k, v in after.items() if k != 'metadata_sha256'}):
                with self.assertRaises(ValueError):
                    c.verify_generated_transition(before, altered, execution)

    def test_transition_rejects_invalid_states_artifacts_and_unbound_execution(self):
        with self.synthetic_hash():
            before, after, execution = self.synthetic_transition()
            for field, value in (('generated_output_state', c.plist_generated_state(True)),
                                 ('generated_artifacts', {}), ('observed_files', {}),
                                 ('source_files', {**self.expected, 'plist.h': c.sha(self.SYNTHETIC_HEADER)})):
                altered = copy.deepcopy(before)
                altered['registry_packages'][c.PLIST_PACKAGE_ID][field] = value
                with self.subTest(before_field=field), self.assertRaises(ValueError):
                    c.verify_generated_transition(altered, after, execution)
            for field, value in (('sha256', '0' * 64), ('bytes', 0), ('bytes', False),
                                 ('bytes', c.PLIST_GENERATED_MAX_BYTES + 1),
                                 ('file_identity', {'device': 0, 'inode': False}),
                                 ('file_identity', {'device': -1, 'inode': 1}),
                                 ('file_identity', {'device': 0, 'inode': 1, 'extra': 1}),
                                 ('extra', 'unreviewed')):
                altered = copy.deepcopy(after)
                altered['registry_packages'][c.PLIST_PACKAGE_ID]['generated_artifacts']['plist.h'][field] = value
                with self.subTest(artifact_field=field, value=value), self.assertRaises(ValueError):
                    c.verify_generated_transition(before, altered, execution)
            for field, value in (('generated_output_state', c.plist_generated_state(False)),
                                 ('generated_artifacts', {}),
                                 ('generated_artifacts', {'plist.h': {}, 'extra.h': {}})):
                altered = copy.deepcopy(after)
                altered['registry_packages'][c.PLIST_PACKAGE_ID][field] = value
                with self.subTest(after_field=field), self.assertRaises(ValueError):
                    c.verify_generated_transition(before, altered, execution)
            for altered_execution in (None, {}, dict(execution, succeeded_and_quiescent=False),
                                      dict(execution, pgid=False), dict(execution, label='other-build'),
                                      dict(execution, command_sha256='not-a-hash'), dict(execution, extra=True)):
                with self.subTest(execution=altered_execution), self.assertRaises(ValueError):
                    c.verify_generated_transition(before, after, altered_execution)

    def test_successful_quiescent_receipt_binds_original_bytes_argv_and_cwd(self):
        argv, command, settled = self.receipt_inputs()
        command_raw = json.dumps(command, indent=2).encode()
        settled_raw = json.dumps(settled, indent=2).encode()
        proof = c.verify_generated_build_receipt(command_raw, settled_raw, b'0\n', argv, self.base)
        self.assertEqual(proof, {'label': 'idevice-build', 'command_sha256': c.sha(command_raw),
                                'settlement_sha256': c.sha(settled_raw), 'exit_code_sha256': c.sha(b'0\n'),
                                'pgid': 12345, 'succeeded_and_quiescent': True})

    def test_failed_nonquiescent_boolean_codes_or_wrong_command_receipts_reject(self):
        argv, command, settled = self.receipt_inputs()
        cases = []
        for exit_raw in (b'1\n', b'0', b'False\n'):
            cases.append((command, settled, exit_raw))
        for key in ('returncode', 'terminationReturncode'):
            for value in (1, -9, False, '0'):
                cases.append((command, dict(settled, **{key: value}), b'0\n'))
        for key in ('leaderReaped', 'pipesJoined', 'quiescent', 'reapedBeforeSignals'):
            for value in (False, 1, None):
                altered = copy.deepcopy(settled)
                altered['ownedProcessGroup'][key] = value
                cases.append((command, altered, b'0\n'))
        for key, value in (('signals', ['TERM']), ('errors', ['unreaped']), ('pgid', 0), ('pgid', False)):
            altered = copy.deepcopy(settled)
            altered['ownedProcessGroup'][key] = value
            cases.append((command, altered, b'0\n'))
        cases.extend([(dict(command, argv=command['argv'] + ['--unreviewed']), settled, b'0\n'),
                      (dict(command, cwd=str(self.base / 'elsewhere')), settled, b'0\n')])
        for index, (observed_command, observed_settled, exit_raw) in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ValueError):
                c.verify_generated_build_receipt(json.dumps(observed_command).encode(),
                    json.dumps(observed_settled).encode(), exit_raw, argv, self.base)

    def test_native_failure_retains_same_raw_snapshot_without_rereading_replaced_path(self):
        with self.synthetic_hash():
            before = self.before()
            for index, error in enumerate((c.RegistrySourceMismatch({'status': 'SYNTHETIC_LATER_MISMATCH'}),
                                           ValueError('synthetic later metadata rejection'))):
                self.header.write_bytes(self.SYNTHETIC_HEADER)
                candidate = native.NativeBuildMixin()
                candidate.work = self.base
                candidate.evidence = self.base / ('evidence-' + str(index))
                (candidate.evidence / 'provenance').mkdir(parents=True)
                candidate.roots = {'idevice': self.base / 'idevice'}
                candidate.rustup = self.base / 'never-executed-rustup'
                candidate.native_env = {}
                candidate.check_cargo_storage = mock.Mock()
                candidate.native_run = mock.Mock(return_value='{"synthetic":true}\n')
                def reject_after_snapshot(*args, **kwargs):
                    self.after(before, kwargs['generated_snapshots'])
                    replacement = self.base / 'later-header'
                    replacement.write_bytes(b'later source bytes must not be retained')
                    replacement.replace(self.header)
                    raise error
                with mock.patch.object(c, 'verify_cargo_metadata', side_effect=reject_after_snapshot):
                    with self.assertRaises(type(error)) as caught:
                        candidate.capture_cargo_metadata('after', self.whole_proof(before))
                self.assertIs(caught.exception, error)
                evidence = candidate.evidence / 'provenance'
                self.assertEqual((evidence / 'plist_ffi.generated.plist.h').read_bytes(), self.SYNTHETIC_HEADER)
                self.assertNotEqual(self.header.read_bytes(), self.SYNTHETIC_HEADER)
                self.assertEqual((evidence / 'Cargo.metadata.after.json').read_text(), '{"synthetic":true}\n')
                self.assertFalse((evidence / 'cargo-resolved-after.json').exists())
                self.assertEqual((evidence / 'cargo-registry-mismatch-after.json').exists(),
                                 isinstance(error, c.RegistrySourceMismatch))
                candidate.native_run.assert_called_once()
                self.assertEqual(candidate.native_run.call_args.args[0], 'cargo-metadata-after')


if __name__ == '__main__':
    unittest.main(verbosity=2)
