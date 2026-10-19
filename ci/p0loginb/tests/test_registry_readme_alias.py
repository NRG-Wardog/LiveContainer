"""Official archive as data plus explicitly synthetic filesystem-alias fixtures.

No dependency source is imported, compiled, loaded or executed. On case-sensitive
hosts the positive alias fixture mocks only the filesystem path lookup boundary;
it is not evidence of the future macOS extraction directory's identity.
"""
from contextlib import contextmanager
import copy
import io
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import cargo_contract as c


class RegistryReadmeAliasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.raw = (HERE/'tests/fixtures/registry-readme-alias/nskeyedarchiver_converter-0.1.3.crate').read_bytes()
        self.assertEqual(c.sha(self.raw), c.README_ALIAS_ARCHIVE)
        self.assertEqual(len(self.raw), c.README_ALIAS_ARCHIVE_BYTES)
        self.home = self.base/'cargo-home'
        self.root = self.home/'registry/src/index/nskeyedarchiver_converter-0.1.3'
        self.root.mkdir(parents=True)
        self.archive = self.home/'registry/cache/index/nskeyedarchiver_converter-0.1.3.crate'
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(self.raw)
        self.files = {}
        with tarfile.open(fileobj=io.BytesIO(self.raw), mode='r:gz') as tar:
            for member in tar:
                self.assertTrue(member.isfile())
                prefix, relative = member.name.split('/', 1)
                self.assertEqual(prefix, 'nskeyedarchiver_converter-0.1.3')
                self.assertNotIn('..', Path(relative).parts)
                self.assertNotIn(relative, self.files)
                self.files[relative] = tar.extractfile(member).read()
        self.expected = {p: c.sha(raw) for p, raw in self.files.items()}
        self.actual = {p: h for p, h in self.expected.items() if p != 'README.MD'}
        for relative, raw in self.files.items():
            if relative != 'README.MD':
                path = self.root/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        (self.root/'.cargo-ok').write_text('{"v":1}')
        self.package = {'name': c.README_ALIAS_PACKAGE[0], 'version': c.README_ALIAS_PACKAGE[1],
                        'manifest_path': str(self.root/'Cargo.toml')}
        self.upper, self.lower = (self.root/p for p in c.README_ALIAS_PATHS)

    @contextmanager
    def synthetic_alias(self):
        original_stat, original_read = Path.stat, Path.read_bytes
        upper, lower = self.upper, self.lower
        def lookup_stat(path, **kwargs):
            return original_stat(lower if path == upper else path, **kwargs)
        def lookup_read(path):
            return original_read(lower if path == upper else path)
        with mock.patch.object(Path, 'stat', lookup_stat), mock.patch.object(Path, 'read_bytes', lookup_read):
            yield

    def probe(self, package=None, checksum=None, size=None, expected=None, actual=None):
        return c.registry_documentation_alias(self.package if package is None else package,
            c.README_ALIAS_ARCHIVE if checksum is None else checksum,
            c.README_ALIAS_ARCHIVE_BYTES if size is None else size, self.root,
            self.expected if expected is None else expected, self.actual if actual is None else actual)

    def test_official_archive_and_both_documentation_bytes_are_exact(self):
        self.assertEqual(len(self.expected), 11)
        self.assertEqual(c.inventory_digest(self.expected), 'c4ec405e9d04acfc75bd3b8e778fa845db7cabbf35bde38b71c8a6ebd347007e')
        self.assertEqual(self.files['README.MD'], self.files['README.md'])
        self.assertEqual(len(self.files['README.MD']), 2398)
        self.assertEqual(c.sha(self.files['README.MD']), c.README_ALIAS_CONTENT)

    def test_synthetic_alias_keeps_distinct_complete_inventories_and_identity(self):
        with self.synthetic_alias():
            proof = c.registry_source(self.package, self.home, c.README_ALIAS_ARCHIVE)
        self.assertEqual(proof['source_files'], self.actual)
        self.assertEqual(proof['archive_files'], self.expected)
        self.assertEqual(proof['source_inventory_relation'], 'VERIFIED_EXACT_DOCUMENTATION_FILESYSTEM_ALIAS')
        alias, = proof['documentation_aliases']
        self.assertTrue(alias['verified'] and alias['samefile'] and alias['ordinary_nonsymlink'])
        self.assertEqual(alias['archive_paths'], ['README.MD', 'README.md'])
        self.assertEqual(alias['enumerated_path'], 'README.md')
        s = self.lower.stat()
        self.assertEqual(alias['file_identity'], {'device': s.st_dev, 'inode': s.st_ino, 'bytes': 2398})
        self.assertEqual(alias['archive_inventory_sha256'], c.inventory_digest(self.expected))
        self.assertEqual(alias['actual_inventory_sha256'], c.inventory_digest(self.actual))
        self.assertEqual(set(proof['cargo_generated_files']), {'.cargo-ok'})

    def test_real_host_missing_spelling_requires_actual_samefile(self):
        # This assertion exercises the real host policy without skipped tests:
        # Linux usually rejects; a case-insensitive macOS fixture proves aliases.
        if self.upper.exists():
            self.assertTrue(self.upper.samefile(self.lower))
            proof = c.registry_source(self.package, self.home, c.README_ALIAS_ARCHIVE)
            self.assertTrue(proof['documentation_aliases'][0]['verified'])
        else:
            with self.assertRaises(c.RegistrySourceMismatch) as caught:
                c.registry_source(self.package, self.home, c.README_ALIAS_ARCHIVE)
            self.assertFalse(caught.exception.diagnostic['documentation_alias_probe']['verified'])
            self.assertEqual(caught.exception.diagnostic['missing'], {'README.MD': c.README_ALIAS_CONTENT})

    def test_forced_absent_alias_always_rejects_and_retains_diagnostics(self):
        original = c.ordinary
        def absent(path, **kwargs):
            if path == self.upper:
                raise ValueError('synthetic case-sensitive missing path')
            return original(path, **kwargs)
        with mock.patch.object(c, 'ordinary', absent):
            with self.assertRaises(c.RegistrySourceMismatch) as caught:
                c.registry_source(self.package, self.home, c.README_ALIAS_ARCHIVE)
        self.assertEqual(caught.exception.diagnostic['documentation_alias_probe']['failure'], 'FILESYSTEM_PROBE_FAILED')
        self.assertTrue(caught.exception.diagnostic['complete'])
        self.assertFalse(caught.exception.diagnostic['source_equality_passed'])

    def test_package_version_checksum_size_are_each_required(self):
        with self.synthetic_alias():
            for args in ({'package': dict(self.package, name='other')}, {'package': dict(self.package, version='0.1.4')},
                         {'checksum': '0'*64}, {'size': 13900}):
                self.assertIsNone(self.probe(**args))
        with mock.patch.object(c, 'registry_documentation_alias') as probe:
            with self.assertRaisesRegex(ValueError, 'archive differs'):
                c.registry_source(self.package, self.home, '0'*64)
            probe.assert_not_called()

    def test_unknown_missing_extra_changed_or_case_collisions_reject(self):
        variants = []
        for path in ('README.md', 'src/lib.rs'):
            actual = dict(self.actual); del actual[path]; variants.append(actual)
        for path in ('extra.rs', 'readme.md', 'SRC/lib.rs'):
            actual = dict(self.actual); actual[path] = c.README_ALIAS_CONTENT; variants.append(actual)
        actual = dict(self.actual); actual['src/lib.rs'] = '0'*64; variants.append(actual)
        actual = dict(self.expected); del actual['README.md']; variants.append(actual)  # reversed survivor
        with self.synthetic_alias():
            for actual in variants:
                self.assertIsNone(self.probe(actual=actual))
            nested = {'nested/'+p: h for p, h in self.expected.items()}
            self.assertIsNone(self.probe(expected=nested, actual={'nested/'+p: h for p, h in self.actual.items()}))

    def test_both_archived_content_digests_and_both_observed_contents_are_required(self):
        with self.synthetic_alias():
            for name in c.README_ALIAS_PATHS:
                expected = dict(self.expected); expected[name] = '0'*64
                self.assertIsNone(self.probe(expected=expected))
            original = Path.read_bytes
            for name in c.README_ALIAS_PATHS:
                def altered(path, target=self.root/name):
                    return b'wrong content' if path == target else original(path)
                with mock.patch.object(Path, 'read_bytes', altered):
                    report = self.probe()
                self.assertFalse(report['verified'])
                self.assertEqual(report['failure'], 'CONTENT_DIFFERS')

    def test_distinct_inode_and_false_samefile_reject(self):
        with self.synthetic_alias():
            original = Path.lstat
            def different(path):
                s = original(path)
                if path == self.upper:
                    return SimpleNamespace(**{k: getattr(s, k) + (1 if k == 'st_ino' else 0)
                        for k in ('st_dev','st_ino','st_size','st_mode','st_mtime_ns','st_ctime_ns')})
                return s
            with mock.patch.object(Path, 'lstat', different):
                self.assertEqual(self.probe()['failure'], 'FILE_IDENTITY_DIFFERS')
            with mock.patch.object(Path, 'samefile', return_value=False):
                self.assertEqual(self.probe()['failure'], 'FILE_IDENTITY_DIFFERS')

    def test_symlink_and_non_file_aliases_reject(self):
        outside = self.base/'outside-readme'; outside.write_bytes(self.files['README.md'])
        self.lower.unlink(); self.lower.symlink_to(outside)
        with self.synthetic_alias():
            self.assertEqual(self.probe()['failure'], 'FILESYSTEM_PROBE_FAILED')
        self.lower.unlink(); self.lower.mkdir()
        with self.synthetic_alias():
            self.assertEqual(self.probe()['failure'], 'FILESYSTEM_PROBE_FAILED')
        self.lower.rmdir(); self.lower.write_bytes(self.files['README.md'])
        linked = self.base/'linked-root'; linked.symlink_to(self.root, target_is_directory=True)
        report = c.registry_documentation_alias(self.package,c.README_ALIAS_ARCHIVE,13901,linked,self.expected,self.actual)
        self.assertEqual(report['failure'], 'FILESYSTEM_PROBE_FAILED')

    def test_two_enumerated_names_cannot_use_alias_exception(self):
        with self.synthetic_alias():
            self.assertIsNone(self.probe(actual=self.expected))  # ordinary exact-equality path
            original = Path.iterdir
            def extra_name(path):
                return iter([*original(path), self.upper]) if path == self.root else original(path)
            with mock.patch.object(Path, 'iterdir', extra_name):
                self.assertEqual(self.probe()['failure'], 'DIRECTORY_ENTRIES_DIFFER')

    def test_probe_rejects_identity_change_during_read(self):
        with self.synthetic_alias():
            original = Path.lstat
            original_read = Path.read_bytes
            read_started = False
            def reading(path):
                nonlocal read_started
                raw = original_read(path)
                if path in (self.upper,self.lower):
                    read_started = True
                return raw
            def changing(path):
                s = original(path)
                if read_started and path in (self.upper,self.lower):
                    return SimpleNamespace(**{k: getattr(s,k)+(1 if k=='st_ctime_ns' else 0)
                        for k in ('st_dev','st_ino','st_size','st_mode','st_mtime_ns','st_ctime_ns')})
                return s
            with mock.patch.object(Path,'lstat',changing), mock.patch.object(Path,'read_bytes',reading):
                self.assertEqual(self.probe()['failure'],'FILE_CHANGED_DURING_PROBE')

    def test_before_after_alias_identity_remains_part_of_proof(self):
        with self.synthetic_alias():
            before = c.registry_source(self.package,self.home,c.README_ALIAS_ARCHIVE)
            self.assertEqual(c.registry_source(self.package,self.home,c.README_ALIAS_ARCHIVE),before)
        changed = copy.deepcopy(before)
        changed['documentation_aliases'][0]['file_identity']['inode'] += 1
        self.assertNotEqual(changed,before)
        self.lower.write_bytes(b'mutated source')
        with self.synthetic_alias(), self.assertRaises(c.RegistrySourceMismatch):
            c.registry_source(self.package,self.home,c.README_ALIAS_ARCHIVE)


if __name__ == '__main__':
    unittest.main()
