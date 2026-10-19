"""Offline hash-only mismatch fixtures; no Cargo, dependency or app execution."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cargo_contract as c
import native_build as native


class RegistryDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'cargo-home'
        self.root = self.home / 'registry/src/index/fake-1.0.0'
        self.root.mkdir(parents=True)
        self.archive = self.home / 'registry/cache/index/fake-1.0.0.crate'
        self.archive.parent.mkdir(parents=True)
        self.package = {'name': 'fake', 'version': '1.0.0', 'manifest_path': str(self.root / 'Cargo.toml')}
        self.files = {'Cargo.toml': b'[package]\nname="fake"\nversion="1.0.0"\n',
                      'src/lib.rs': b'// SOURCE-CONTENT-CANARY\n', 'README': b'retained\n'}
        self.write_fixture()

    def write_fixture(self):
        with tarfile.open(self.archive, 'w:gz') as tar:
            for relative, raw in self.files.items():
                member = tarfile.TarInfo('fake-1.0.0/' + relative)
                member.size = len(raw)
                tar.addfile(member, io.BytesIO(raw))
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        (self.root / '.cargo-ok').write_text('{"v":1}')
        self.checksum = c.sha(self.archive.read_bytes())

    def mismatch_report(self):
        with self.assertRaises(c.RegistrySourceMismatch) as caught:
            c.registry_source(self.package, self.home, self.checksum)
        self.assertEqual(str(caught.exception), 'registry extracted source changed from locked archive')
        return caught.exception.diagnostic

    def test_success_shape_and_generated_file_policy_are_identical(self):
        result = c.registry_source(self.package, self.home, self.checksum)
        self.assertEqual(result, {'archive_sha256': self.checksum,
            'manifest_path': self.package['manifest_path'],
            'source_files': {p: c.sha(raw) for p, raw in self.files.items()},
            'cargo_generated_files': {'.cargo-ok': c.sha(b'{"v":1}')}})

    def test_missing_extra_changed_inventories_are_complete_hash_only(self):
        (self.root / 'README').unlink()
        (self.root / 'new-file').write_bytes(b'EXTRA-CONTENT-CANARY')
        (self.root / 'src/lib.rs').write_bytes(b'CHANGED-CONTENT-CANARY')
        report = self.mismatch_report()
        self.assertTrue(report['complete'])
        self.assertFalse(report['source_equality_passed'])
        self.assertEqual(report['package'], {'name': 'fake', 'version': '1.0.0'})
        self.assertEqual(report['archive_sha256'], self.checksum)
        self.assertEqual(report['archive_bytes'], self.archive.stat().st_size)
        self.assertEqual(report['missing'], {'README': c.sha(self.files['README'])})
        self.assertEqual(report['extra'], {'new-file': c.sha(b'EXTRA-CONTENT-CANARY')})
        self.assertEqual(report['changed'], {'src/lib.rs': {
            'expected_sha256': c.sha(self.files['src/lib.rs']), 'actual_sha256': c.sha(b'CHANGED-CONTENT-CANARY')}})
        self.assertEqual(report['counts'], {'expected': 3, 'actual': 3, 'generated': 1, 'missing': 1, 'extra': 1, 'changed': 1})
        self.assertTrue(all(v == 0 for v in report['omitted_counts'].values()))
        for name, files in (('expected', report['expected_files']), ('actual', report['actual_files'])):
            canonical = json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
            self.assertEqual(report['inventory_sha256'][name], hashlib.sha256(canonical).hexdigest())
        raw = json.dumps(report, indent=2, sort_keys=True) + '\n'
        self.assertLessEqual(len(raw.encode()), c.REGISTRY_DIAGNOSTIC_MAX_BYTES)
        for forbidden in ('SOURCE-CONTENT-CANARY', 'EXTRA-CONTENT-CANARY', 'CHANGED-CONTENT-CANARY', str(self.base)):
            self.assertNotIn(forbidden, raw)

    def test_archived_cargo_marker_is_still_rejected_when_cargo_replaces_it(self):
        self.files['.cargo-ok'] = b'archived-marker-bytes'
        self.write_fixture()
        report = self.mismatch_report()
        self.assertEqual(report['changed']['.cargo-ok']['expected_sha256'], c.sha(b'archived-marker-bytes'))
        self.assertEqual(report['changed']['.cargo-ok']['actual_sha256'], c.sha(b'{"v":1}'))

    def test_count_and_path_bounds_emit_fixed_failure_with_omitted_counts(self):
        for expected, reason in (({str(n): 'a'*64 for n in range(c.REGISTRY_DIAGNOSTIC_MAX_FILES+1)}, 'FILE_COUNT_LIMIT'),
                                 ({'x'*(c.REGISTRY_DIAGNOSTIC_MAX_PATH_BYTES+1): 'b'*64}, 'PATH_LENGTH_LIMIT'),
                                 ({'invalid-utf8-\udcff': 'c'*64}, 'PATH_LENGTH_LIMIT')):
            report = c.registry_mismatch_diagnostic(self.package, self.checksum, 1, expected, {}, {})
            self.assertFalse(report['complete'])
            self.assertFalse(report['source_equality_passed'])
            self.assertEqual(report['bound_failure'], reason)
            self.assertEqual(report['omitted_counts']['expected'], len(expected))
            self.assertNotIn('expected_files', report)
            self.assertLess(len(json.dumps(report).encode()), c.REGISTRY_DIAGNOSTIC_MAX_BYTES)

    def test_serialized_size_bound_and_identity_bound_remain_failed(self):
        # All file counts and path lengths are individually allowed; aggregate
        # repeated public names exceed the real 8 MiB serialized-report ceiling.
        expected = {str(n) + 'x'*500: 'a'*64 for n in range(9000)}
        report = c.registry_mismatch_diagnostic(self.package, self.checksum, 1, expected, {}, {})
        self.assertEqual(report['bound_failure'], 'SERIALIZED_SIZE_LIMIT')
        self.assertFalse(report['complete'])
        self.assertNotIn('missing', report)
        self.assertEqual(report['omitted_counts']['missing'], 9000)
        package = dict(self.package, name='x'*129)
        report = c.registry_mismatch_diagnostic(package, self.checksum, 1, {'a': 'b'*64}, {}, {})
        self.assertEqual(report['bound_failure'], 'PACKAGE_IDENTITY_LIMIT')
        self.assertIsNone(report['package'])

    def test_archive_hash_failure_precedes_diagnostic_and_link_policy_unchanged(self):
        with self.assertRaisesRegex(ValueError, 'archive differs') as caught:
            c.registry_source(self.package, self.home, '0'*64)
        self.assertNotIsInstance(caught.exception, c.RegistrySourceMismatch)
        (self.root/'linked').symlink_to(self.root/'README')
        with self.assertRaisesRegex(ValueError, 'linked') as caught:
            c.registry_source(self.package, self.home, self.checksum)
        self.assertNotIsInstance(caught.exception, c.RegistrySourceMismatch)

    def test_archive_parser_uses_same_bytes_that_passed_checksum(self):
        original = Path.read_bytes
        def replacing(path):
            raw = original(path)
            if path == self.archive:
                self.archive.write_bytes(b'replacement is not a gzip archive')
            return raw
        with mock.patch.object(Path, 'read_bytes', replacing):
            result = c.registry_source(self.package, self.home, self.checksum)
        self.assertEqual(result['source_files'], {p: c.sha(raw) for p, raw in self.files.items()})

    def test_native_checkpoint_persists_first_mismatch_then_rethrows(self):
        (self.root/'README').unlink()
        try:
            c.registry_source(self.package, self.home, self.checksum)
        except c.RegistrySourceMismatch as error:
            mismatch = error
        class Candidate(native.NativeBuildMixin):
            def check_cargo_storage(self): pass
            def native_run(self, *args, **kwargs): return '{"synthetic_metadata":true}'
        candidate = Candidate()
        candidate.work = self.base
        candidate.evidence = self.base/'evidence'
        (candidate.evidence/'provenance').mkdir(parents=True)
        candidate.rustup = self.base/'rustup'
        candidate.roots = {'idevice': self.base/'idevice'}
        candidate.native_env = {}
        for when in ('before', 'after'):
            with mock.patch.object(c, 'verify_cargo_metadata', side_effect=mismatch) as check:
                with self.assertRaises(c.RegistrySourceMismatch) as caught:
                    candidate.capture_cargo_metadata(when)
            self.assertIs(caught.exception, mismatch)
            check.assert_called_once()
            path = candidate.evidence/('provenance/cargo-registry-mismatch-'+when+'.json')
            self.assertEqual(json.loads(path.read_bytes()), mismatch.diagnostic)
            self.assertFalse((candidate.evidence/('provenance/cargo-resolved-'+when+'.json')).exists())
        self.assertFalse(hasattr(candidate, 'app_product_checks_complete'))


if __name__ == '__main__':
    unittest.main()
