import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import raw_view as v
import retrieve as r


class RawViewTests(unittest.TestCase):
    def archive(self, root, entries):
        source = root / 'archive.zip'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in entries:
                    archive.writestr(name, raw)
        raw = source.read_bytes()
        return source, len(raw), hashlib.sha256(raw).hexdigest()

    def run_view(self, root, entries):
        source, size, digest = self.archive(root, entries)
        return v.view(source, root / 'view', size, digest)

    def test_raw_bytes_fixed_and_bounded_nested_names_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            entries = [('provenance/result.json', b'{"status":"failed"}'),
                       ('logs/consumer-exact38.stderr.log', b'error\xff\x00'),
                       ('consumer-nested/0128.stderr', b'last stderr'),
                       ('consumer-nested/0128.result.json', b'{"returncode":1}'),
                       ('consumer-nested/0129.stderr', b'outside fixed allowlist'),
                       ('consumer-nested/0000.stderr', b'outside fixed allowlist'),
                       ('consumer-nested/1.stderr', b'outside fixed allowlist'),
                       ('unrelated.py', b'raise RuntimeError("never execute")')]
            receipt = self.run_view(root, entries)
            self.assertEqual(receipt['status'], 'DIAGNOSTIC_DATA_ONLY')
            self.assertFalse(receipt['complete_evidence_validation'])
            self.assertFalse(receipt['artifact_code_executed'])
            self.assertIn('result.json', receipt['missing_fixed_members'])
            self.assertIn('provenance/consumer-tests.json', receipt['missing_fixed_members'])
            self.assertEqual(len(receipt['members']), 4)
            original = dict(entries)
            for row in receipt['members']:
                raw = (root / 'view' / row['file']).read_bytes()
                self.assertEqual(raw, original[row['member']])
                self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertRegex(row['file'], r'^raw-\d{3}\.bin$')
            self.assertEqual(receipt['raw_bytes'], sum(row['bytes'] for row in receipt['members']))
            self.assertEqual({p.parent for p in (root / 'view').iterdir()}, {root / 'view'})

    def test_whole_hash_checked_before_opening_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'archive.zip'; source.write_bytes(b'not a ZIP')
            with patch.object(v.zipfile, 'ZipFile') as opener:
                with self.assertRaisesRegex(ValueError, 'byte identity'):
                    v.view(source, root / 'view', 9, '0' * 64)
                opener.assert_not_called()
            self.assertFalse((root / 'view').exists())

    def test_unsafe_paths_duplicate_symlink_and_special_rejected(self):
        for name in ('../escape', '/absolute', 'a/../b', 'a//b', './a', 'C:/a', 'a\\b', 'a\x00b', 'a\nb'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                source, size, digest = self.archive(root, [(name, b'x')])
                # zipfile truncates NUL when creating; inject it into both filename headers.
                if '\x00' in name:
                    source.unlink(); source, size, digest = self.archive(root, [('aXb', b'x')])
                    raw=source.read_bytes().replace(b'aXb', b'a\x00b');source.write_bytes(raw)
                    size=len(raw);digest=hashlib.sha256(raw).hexdigest()
                with self.assertRaisesRegex(ValueError, 'unsafe archive member'):
                    v.view(source, root / 'view', size, digest)
        for entries in ([('a', b'one'), ('a', b'two')], [('a/', b''), ('a', b'file')]):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    self.run_view(Path(tmp).resolve(), entries)
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                item = zipfile.ZipInfo('logs/consumer-exact38.stderr.log')
                item.create_system = 3; item.external_attr = (kind | 0o777) << 16
                with self.assertRaisesRegex(ValueError, 'linked or special'):
                    self.run_view(Path(tmp).resolve(), [(item, b'payload')])

    def test_member_aggregate_count_and_compression_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'member byte bound'):
                self.run_view(Path(tmp).resolve(), [('logs/consumer-exact38.exit-code.txt', b'x' * 1025)])
        with tempfile.TemporaryDirectory() as tmp, patch.object(v, 'MAX_VIEW_BYTES', 3):
            with self.assertRaisesRegex(ValueError, 'aggregate'):
                self.run_view(Path(tmp).resolve(), [('result.json', b'xx'), ('provenance/result.json', b'xx')])
        with tempfile.TemporaryDirectory() as tmp, patch.object(v, 'MAX_MEMBERS', 1):
            with self.assertRaisesRegex(ValueError, 'member count'):
                self.run_view(Path(tmp).resolve(), [('a', b''), ('b', b'')])
        with tempfile.TemporaryDirectory() as tmp:
            item = zipfile.ZipInfo('result.json'); item.compress_type = zipfile.ZIP_BZIP2
            with self.assertRaisesRegex(ValueError, 'ordinary unencrypted'):
                self.run_view(Path(tmp).resolve(), [(item, b'{}')])

    def test_corrupt_truncated_and_changed_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'archive.zip'; source.write_bytes(b'not zip')
            with self.assertRaises(zipfile.BadZipFile):
                v.view(source, root / 'view', 7, hashlib.sha256(b'not zip').hexdigest())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve();source, size, digest = self.archive(root, [('result.json', b'{}')])
            original_open = v.zipfile.ZipFile.open
            def mutated(archive, *args, **kwargs):
                os.utime(source, ns=(1, 1))
                return original_open(archive, *args, **kwargs)
            with patch.object(v.zipfile.ZipFile, 'open', mutated):
                with self.assertRaisesRegex(ValueError, 'changed during view'):
                    v.view(source, root / 'view', size, digest)
            self.assertFalse((root / 'view/raw-view-manifest.json').exists())

    def test_archive_alias_and_existing_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source, size, digest = self.archive(root, [('result.json', b'{}')])
            alias = root / 'alias'; alias.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'ordinary exact archive'):
                v.view(alias, root / 'view', size, digest)
            os.link(source, root / 'hardlink')
            with self.assertRaisesRegex(ValueError, 'ordinary exact archive'):
                v.view(source, root / 'view', size, digest)
            output = root / 'exists'; output.mkdir()
            with self.assertRaisesRegex(ValueError, 'fresh canonical'):
                v.view(source, output, size, digest)

    def test_six_part_bound_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'original'; raw = bytes(range(46)); source.write_bytes(raw)
            rows = r.split(source, root / 'parts', len(raw), hashlib.sha256(raw).hexdigest(), 8)
            self.assertEqual([row['bytes'] for row in rows], [8, 8, 8, 8, 8, 6])
            self.assertEqual(b''.join((root / 'parts' / row['name']).read_bytes() for row in rows), raw)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'original'; raw = bytes(range(49)); source.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'part bounds'):
                r.split(source, root / 'parts', len(raw), hashlib.sha256(raw).hexdigest(), 8)

    def test_fixed_limits_and_early_view_workflow_order(self):
        self.assertEqual((v.MAX_VIEW_BYTES, len(v.FIXED), len(v.ALLOWED)), (64 * 1024 * 1024, 10, 522))
        root = Path(__file__).resolve().parents[3]
        workflow = (root / '.github/workflows/p0-defensive-diagnostic-phase-b-transport.yml').read_text()
        self.assertLess(workflow.index('run: python3 -B ci/p0transport/retrieve.py'), workflow.index('run: python3 -B ci/p0transport/raw_view.py'))
        self.assertLess(workflow.index('name: original-12219284081-raw-diagnostic-view'), workflow.index('name: original-12219284081-part-00'))
        self.assertIn('timeout-minutes: 15', workflow)
        self.assertEqual(workflow.count('GH_TOKEN:'), 1)
        self.assertNotIn('extractall', Path(v.__file__).read_text())

if __name__ == '__main__':
    unittest.main()
