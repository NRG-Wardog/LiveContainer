import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

import package_evidence as packaging


class Packaging(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'evidence'
        self.source.mkdir()
        (self.source / 'raw').mkdir()
        (self.source / 'empty-directory').mkdir()
        (self.source / 'raw/video.mp4').write_bytes(bytes(range(256)) * 3)
        (self.source / 'raw/events.json').write_bytes(b'{"failed":true}\n')
        (self.source / '.hidden-receipt').write_bytes(b'preserve hidden files\x00\xff')
        (self.source / 'empty-file').touch()
        (self.source / 'unicode-\u05e2\u05d1\u05e8\u05d9\u05ea.txt').write_bytes(b'UTF8 member name')
        self.output = self.root / 'parts'

    def pack(self, **kwargs):
        return packaging.package(self.source, self.output, chunk_size=256, **kwargs)

    def manifest(self):
        return json.loads((self.output / 'manifest.json').read_text())

    def save(self, manifest):
        (self.output / 'manifest.json').write_text(json.dumps(manifest))

    def reject(self, manifest, pattern=None):
        self.save(manifest)
        context = self.assertRaisesRegex(ValueError, pattern) if pattern else self.assertRaises(ValueError)
        with context:
            packaging.verify_package(self.output)

    def replace_archive(self, data, manifest):
        for part in manifest['parts']:
            (self.output / part['path']).unlink()
        manifest['archive']['size'] = len(data)
        manifest['archive']['sha256'] = hashlib.sha256(data).hexdigest()
        manifest['parts'] = []
        for ordinal, offset in enumerate(range(0, len(data), manifest['chunk_size'])):
            part = data[offset:offset + manifest['chunk_size']]
            name = f'part-{ordinal:03d}.bin'
            (self.output / name).write_bytes(part)
            manifest['parts'].append({'ordinal': ordinal, 'offset': offset, 'path': name,
                                      'size': len(part), 'sha256': hashlib.sha256(part).hexdigest()})
        self.save(manifest)

    def test_all_bytes_hidden_files_empty_files_directories_and_hashes_preserved(self):
        manifest = self.pack(collection_outcome='failure')
        reconstructed = self.root / 'reconstructed.zip'
        self.assertEqual(packaging.verify_package(self.output, reconstructed), manifest)
        self.assertEqual(packaging.file_identity(reconstructed),
                         (manifest['archive']['size'], manifest['archive']['sha256']))
        joined = b''.join((self.output / row['path']).read_bytes() for row in manifest['parts'])
        self.assertEqual(reconstructed.read_bytes(), joined)
        expected = {p.relative_to(self.source).as_posix() for p in self.source.rglob('*')}
        self.assertEqual({row['path'] for row in manifest['entries']}, expected)
        with zipfile.ZipFile(reconstructed) as archive:
            self.assertEqual(len(archive.infolist()), len(expected))
            for row in manifest['entries']:
                original = self.source / row['path']
                data = original.read_bytes() if original.is_file() else b''
                self.assertEqual(row['sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual(row['size'], len(data))
                self.assertEqual(archive.read(row['path'] + ('/' if row['kind'] == 'directory' else '')), data)
        offset = 0
        for ordinal, row in enumerate(manifest['parts']):
            self.assertEqual(row['ordinal'], ordinal)
            self.assertEqual(row['offset'], offset)
            self.assertLessEqual(row['size'], 256)
            self.assertEqual(packaging.file_identity(self.output / row['path']), (row['size'], row['sha256']))
            offset += row['size']
        self.assertEqual(offset, manifest['archive']['size'])
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {'manifest.json', *(row['path'] for row in manifest['parts'])})
        self.assertFalse(any(p.name.startswith('.p1-') for p in self.root.iterdir()))

    def test_zip_and_manifest_deterministic_across_modes_mtimes_and_source_order(self):
        first = self.pack(collection_outcome='failure')
        first_parts = [(self.output / row['path']).read_bytes() for row in first['parts']]
        for path in self.source.rglob('*'):
            os.utime(path, (1000000000, 1000000000))
            if path.is_file():
                path.chmod(0o700)
        second_output = self.root / 'other-parts'
        second = packaging.package(self.source, second_output, 'failure', 256)
        self.assertEqual(first, second)
        self.assertEqual(first_parts, [(second_output / row['path']).read_bytes() for row in second['parts']])
        self.assertEqual((self.output / 'manifest.json').read_bytes(), (second_output / 'manifest.json').read_bytes())

    def test_every_collection_outcome_remains_transport_only(self):
        for outcome in sorted(packaging.OUTCOMES):
            with self.subTest(outcome=outcome):
                manifest = packaging.package(self.source, self.root / outcome, outcome)
                self.assertEqual(manifest['collection_outcome'], outcome)
                self.assertIs(manifest['transport_only'], True)
                self.assertIs(manifest['admission_eligible'], False)
                self.assertIs(manifest['ui_success_claimed'], False)

    def test_empty_failed_run_has_valid_empty_zip_and_no_success_claim(self):
        empty = self.root / 'empty'
        empty.mkdir()
        manifest = packaging.package(empty, self.output, 'failure', 256)
        self.assertEqual(manifest['entries'], [])
        self.assertEqual(manifest['archive']['size'], 22)
        self.assertEqual(len(manifest['parts']), 1)
        self.assertFalse(manifest['admission_eligible'])
        packaging.verify_package(self.output)

    def test_partial_failed_run_retains_original_failure_receipt(self):
        receipt = b'{"collection_complete":false,"admissionEligible":false,"errors":["XCTest timeout"]}'
        (self.source / 'report.json').write_bytes(receipt)
        manifest = self.pack(collection_outcome='failure')
        row = next(row for row in manifest['entries'] if row['path'] == 'report.json')
        self.assertEqual(row['sha256'], hashlib.sha256(receipt).hexdigest())
        self.assertEqual((self.source / 'report.json').read_bytes(), receipt)

    def test_source_code_is_only_bytes_never_executed_or_extracted(self):
        marker = self.root / 'executed'
        script = "from pathlib import Path\nPath(%r).write_text('unsafe')\n" % str(marker)
        (self.source / 'setup.py').write_text(script)
        self.pack()
        packaging.verify_package(self.output, self.root / 'archive.zip')
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / 'setup.py').exists())

    def test_source_symlinks_are_rejected_without_output(self):
        for name, target in [('file-link', self.source / 'raw/events.json'),
                             ('directory-link', self.source / 'raw'),
                             ('dangling-link', self.root / 'absent')]:
            with self.subTest(name=name):
                link = self.source / name
                link.symlink_to(target)
                with self.assertRaisesRegex(ValueError, 'linked or special'):
                    self.pack()
                self.assertFalse(self.output.exists())
                link.unlink()

    def test_source_root_or_ancestor_symlink_is_rejected(self):
        link = self.root / 'source-link'
        link.symlink_to(self.source, target_is_directory=True)
        for source in (link, link / 'raw'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'linked'):
                packaging.package(source, self.output)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO not available')
    def test_special_file_is_rejected_without_blocking(self):
        os.mkfifo(self.source / 'fifo')
        with self.assertRaisesRegex(ValueError, 'special'):
            self.pack()
        self.assertFalse(self.output.exists())

    def test_escaped_filesystem_names_are_rejected(self):
        for name in ('..\\outside', 'C:drive', 'bad\nname'):
            with self.subTest(name=name):
                path = self.source / name
                path.write_bytes(b'unsafe name')
                with self.assertRaisesRegex(ValueError, 'unsafe'):
                    self.pack()
                self.assertFalse(self.output.exists())
                path.unlink()

    def test_safe_member_names_reject_escape_absolute_empty_and_control(self):
        for name in ('../outside', '/absolute', 'a/../b', 'a//b', './a', 'a/', '', 'a\\b', 'C:/drive', 'a\x00b', 'a\x7fb'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                packaging.safe_name(name)

    def test_stale_destination_is_never_reused_or_deleted(self):
        self.output.mkdir()
        marker = self.output / 'retained'
        marker.write_bytes(b'existing evidence')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.pack()
        self.assertEqual(marker.read_bytes(), b'existing evidence')
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_empty_existing_destination_is_still_stale(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.pack()

    def test_output_symlink_and_linked_ancestor_are_rejected(self):
        self.output.symlink_to(self.root / 'absent')
        with self.assertRaisesRegex(ValueError, 'linked'):
            self.pack()
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        self.output.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            packaging.package(self.source, self.output / 'new')

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inside source'):
            packaging.package(self.source, self.source / 'new')
        self.assertFalse((self.source / 'new').exists())

    def test_parent_traversal_filesystem_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'parent traversal'):
            packaging.package(self.source / 'raw/..', self.output)

    def test_source_mutation_before_file_read_is_rejected(self):
        original_open = packaging.open_regular
        changed = False
        def mutate(path):
            nonlocal changed
            if Path(path).is_relative_to(self.source) and not changed:
                Path(path).write_bytes(b'changed during packaging')
                changed = True
            return original_open(path)
        with patch.object(packaging, 'open_regular', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.pack()
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_source_inventory_mutation_is_rejected(self):
        original_snapshot = packaging.snapshot
        calls = 0
        def mutate(path):
            nonlocal calls
            calls += 1
            if calls == 3:
                (self.source / 'late-file').write_bytes(b'late')
            return original_snapshot(path)
        with patch.object(packaging, 'snapshot', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'inventory changed'):
                self.pack()
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_default_bound_is_256_mib_and_maximum_64_parts(self):
        self.assertEqual(packaging.CHUNK_SIZE, 256 * 1024 * 1024)
        self.assertEqual(packaging.MAX_PARTS, 64)
        for chunk_size in (0, -1, True, packaging.CHUNK_SIZE + 1):
            with self.subTest(chunk_size=chunk_size), self.assertRaisesRegex(ValueError, 'chunk size'):
                packaging.package(self.source, self.output, chunk_size=chunk_size)
        for max_parts in (0, -1, True, 65):
            with self.subTest(max_parts=max_parts), self.assertRaisesRegex(ValueError, 'part count'):
                packaging.package(self.source, self.output, max_parts=max_parts)

    def test_exceeded_part_count_fails_without_truncation_or_manifest(self):
        before = {p: p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'exceeds bounded part count'):
            packaging.package(self.source, self.output, chunk_size=256, max_parts=1)
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_archive_overhead_cannot_exceed_size_bound(self):
        empty = self.root / 'empty-source'
        empty.mkdir()
        (empty / 'file').write_bytes(b'one')
        archive = self.root / 'bounded.zip'
        with self.assertRaisesRegex(ValueError, 'exceeds bounded part count'):
            packaging.create_archive(empty, archive, maximum=64)
        self.assertLessEqual(archive.stat().st_size, 64)

    def test_reordered_duplicate_and_missing_parts_rejected(self):
        original = self.pack()
        variants = []
        row = copy.deepcopy(original)
        row['parts'].reverse()
        variants.append(row)
        row = copy.deepcopy(original)
        row['parts'][1] = row['parts'][0]
        variants.append(row)
        row = copy.deepcopy(original)
        row['parts'].pop()
        variants.append(row)
        for manifest in variants:
            with self.subTest(parts=manifest['parts']):
                self.reject(manifest)

    def test_part_escape_offset_size_boolean_and_sha_rejected(self):
        original = self.pack()
        for key, value in [('path', '../outside'), ('offset', 1), ('ordinal', True),
                           ('size', True), ('size', 0), ('sha256', 'invalid')]:
            with self.subTest(key=key, value=value):
                manifest = copy.deepcopy(original)
                manifest['parts'][0][key] = value
                self.reject(manifest)

    def test_changed_chunk_rejected_and_no_reconstruction_published(self):
        manifest = self.pack()
        path = self.output / manifest['parts'][0]['path']
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        reconstructed = self.root / 'bad.zip'
        with self.assertRaisesRegex(ValueError, 'part digest'):
            packaging.verify_package(self.output, reconstructed)
        self.assertFalse(reconstructed.exists())

    def test_truncated_or_extended_chunk_rejected(self):
        manifest = self.pack()
        path = self.output / manifest['parts'][0]['path']
        original = path.read_bytes()
        for data in (original[:-1], original + b'extra'):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'part size'):
                    packaging.verify_package(self.output)

    def test_whole_zip_hash_checked_even_if_part_hash_is_forged(self):
        manifest = self.pack()
        path = self.output / manifest['parts'][0]['path']
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        manifest['parts'][0]['sha256'] = hashlib.sha256(data).hexdigest()
        self.reject(manifest, 'archive identity')

    def test_missing_extra_and_linked_chunk_rejected(self):
        manifest = self.pack()
        path = self.output / manifest['parts'][0]['path']
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing package member'):
            packaging.verify_package(self.output)
        external = self.root / 'external-part'
        external.write_bytes(original)
        path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'linked'):
            packaging.verify_package(self.output)
        path.unlink()
        path.write_bytes(original)
        (self.output / 'stale-part.bin').write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            packaging.verify_package(self.output)

    def test_linked_manifest_or_package_root_rejected(self):
        self.pack()
        manifest = self.output / 'manifest.json'
        external = self.root / 'manifest'
        manifest.rename(external)
        manifest.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'linked'):
            packaging.verify_package(self.output)
        link = self.root / 'parts-link'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked'):
            packaging.verify_package(link)

    def test_duplicate_json_keys_rejected(self):
        self.pack()
        path = self.output / 'manifest.json'
        data = path.read_text()
        path.write_text('{"schema":"wrong",' + data[1:])
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            packaging.verify_package(self.output)

    def test_duplicate_reordered_escaped_and_missing_parent_file_index_rejected(self):
        original = self.pack()
        variants = []
        row = copy.deepcopy(original)
        row['entries'][1] = row['entries'][0]
        variants.append(row)
        row = copy.deepcopy(original)
        row['entries'].reverse()
        variants.append(row)
        row = copy.deepcopy(original)
        row['entries'][0]['path'] = '../escape'
        variants.append(row)
        row = copy.deepcopy(original)
        row['entries'] = [entry for entry in row['entries'] if entry['path'] != 'raw']
        variants.append(row)
        for manifest in variants:
            with self.subTest(entries=manifest['entries']):
                self.reject(manifest)

    def test_original_file_hash_checked_after_part_and_archive_integrity(self):
        manifest = self.pack()
        manifest['entries'][0]['sha256'] = '0' * 64
        self.reject(manifest, 'ZIP member digest')

    def test_missing_or_additional_zip_members_rejected_even_with_valid_archive_hash(self):
        manifest = self.pack()
        original = b''.join((self.output / row['path']).read_bytes() for row in manifest['parts'])
        replacement = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(replacement, 'w') as target:
            for info in source.infolist()[1:]:
                target.writestr(info, source.read(info))
        self.replace_archive(replacement.getvalue(), manifest)
        with self.assertRaisesRegex(ValueError, 'ZIP member count'):
            packaging.verify_package(self.output)

    def test_symlink_duplicate_and_escaped_zip_members_rejected_without_extraction(self):
        original_manifest = self.pack()
        original = b''.join((self.output / row['path']).read_bytes() for row in original_manifest['parts'])
        for mutation in ('symlink', 'escape', 'duplicate'):
            with self.subTest(mutation=mutation):
                replacement = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(replacement, 'w') as target:
                    for number, info in enumerate(source.infolist()):
                        data = source.read(info)
                        if number == 0 and mutation == 'symlink':
                            info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        if number == 0 and mutation == 'escape':
                            info.filename = '../escaped'
                        if number == 1 and mutation == 'duplicate':
                            info.filename = source.infolist()[0].filename
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            target.writestr(info, data)
                manifest = copy.deepcopy(original_manifest)
                self.replace_archive(replacement.getvalue(), manifest)
                with self.assertRaises(ValueError):
                    packaging.verify_package(self.output)
                self.assertFalse((self.root / 'escaped').exists())
                # Restore original part set before the next malicious variant.
                self.replace_archive(original, copy.deepcopy(original_manifest))

    def test_manifest_cannot_claim_admission_or_ui_success(self):
        original = self.pack()
        for key, value in [('transport_only', False), ('admission_eligible', True), ('ui_success_claimed', True)]:
            with self.subTest(key=key):
                manifest = copy.deepcopy(original)
                manifest[key] = value
                self.reject(manifest, 'cannot claim')

    def test_existing_reconstruction_destination_is_not_overwritten(self):
        self.pack()
        reconstructed = self.root / 'old.zip'
        reconstructed.write_bytes(b'old evidence')
        with self.assertRaisesRegex(ValueError, 'fresh reconstruction'):
            packaging.verify_package(self.output, reconstructed)
        self.assertEqual(reconstructed.read_bytes(), b'old evidence')

    def test_reconstruction_inside_package_is_rejected(self):
        self.pack()
        with self.assertRaisesRegex(ValueError, 'outside the package'):
            packaging.verify_package(self.output, self.output / 'new.zip')

    def test_reconstruction_symlink_and_dangling_link_are_rejected(self):
        self.pack()
        for target in (self.root / 'absent', self.source / 'empty-file'):
            link = self.root / 'output.zip'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'linked'):
                packaging.verify_package(self.output, link)
            link.unlink()

    def test_failed_post_pack_verification_removes_completion_manifest(self):
        with patch.object(packaging, 'verify_package', side_effect=packaging.PackagingError('fixture failure')):
            with self.assertRaisesRegex(ValueError, 'fixture failure'):
                self.pack()
        self.assertFalse((self.output / 'manifest.json').exists())
        self.assertTrue((self.source / 'raw/video.mp4').exists())

    def test_cli_pack_verify_reconstruct_and_failure(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            self.assertEqual(packaging.main(['pack', '--source', str(self.source), '--output', str(self.output),
                                             '--collection-outcome', 'failure', '--max-parts', '16']), 0)
            response = json.loads(stdout.getvalue())
        self.assertTrue(response['transport_verified'])
        self.assertFalse(response['ui_success_claimed'])
        self.assertFalse(response['admission_eligible'])
        self.assertEqual(response['collection_outcome'], 'failure')
        with patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(packaging.main(['verify', '--package', str(self.output)]), 0)
            self.assertEqual(packaging.main(['reconstruct', '--package', str(self.output),
                                             '--output', str(self.root / 'cli.zip')]), 0)
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertEqual(packaging.main(['pack', '--source', str(self.source), '--output', str(self.output)]), 1)
        self.assertIn('fresh package destination', stderr.getvalue())
        self.assertNotIn(str(self.source), stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
