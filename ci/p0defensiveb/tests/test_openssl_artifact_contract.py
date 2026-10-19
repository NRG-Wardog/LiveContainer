"""Offline source-boundary tests. Synthetic ZIP bytes never represent a native build.

Only explicit unittest patches replace the synthetic source commit/tree and archive
byte expectations. The public production verifier has no override parameter, env
switch, download, extraction, signing, or native execution path. Package.swift and
its blob identity remain the real reviewed manifest even in synthetic positives.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import openssl_artifact_contract as contract
import source_primitives as primitives

OFFICIAL_REVIEW = copy.deepcopy(contract.REVIEWED_INVENTORY)
OFFICIAL_PRODUCT = copy.deepcopy(contract.EXPECTED_PRODUCT_FILES)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def description(raw):
    return {'bytes': len(raw), 'sha256': sha(raw)}


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='Synthetic Test', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
               GIT_COMMITTER_NAME='Synthetic Test', GIT_COMMITTER_EMAIL='synthetic@example.invalid')
    return subprocess.check_output(['git', '-C', str(root), '-c', 'core.hooksPath=' + os.devnull, *args],
                                   env=env, stderr=subprocess.PIPE).decode().strip()


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw, mode in entries:
            member = zipfile.ZipInfo(name)
            member.create_system = 3
            member.external_attr = mode << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, raw)
    return stream.getvalue()


class ReviewedIdentityTests(unittest.TestCase):
    def test_immutable_official_manifest_identity(self):
        raw = (HERE / 'tests/fixtures/RemotePairingKit.Package.swift').read_bytes()
        self.assertEqual(len(raw), 1367)
        self.assertEqual(sha(raw), '4ab6b23b6ef59fda4c5ae6001574362b697d4882d396de4bdd93231e9eeb2dab')
        self.assertEqual(hashlib.sha1(b'blob 1367\0' + raw).hexdigest(), '0176e1cd70b13481939eb282d081167a43a5bf17')
        self.assertEqual(contract.SOURCE_COMMIT, 'e3f70d16c0c551540a533a39d540e78e5b0a60a8')
        self.assertEqual(contract.SOURCE_TREE, '007ba009bb6dbb4f2149da8e918a0dcd02b1a4e2')
        self.assertIn(contract.ARTIFACT_URL.encode(), raw)
        self.assertIn(contract.ARCHIVE_SHA256.encode(), raw)

    def test_immutable_official_inventory_and_exact_copy(self):
        raw = contract.REVIEWED_INVENTORY_PATH.read_bytes()
        self.assertEqual(sha(raw), '914acae691d22d94af6de528097ddce74e06920f9dfd66f4b0e375bfaafbc5e8')
        self.assertEqual(contract.ARCHIVE_BYTES, 45431584)
        self.assertEqual(contract.ARCHIVE_SHA256, '37846a8bd302cb2443eff47f1045ab844d0cd40bf82cc6159cfad9aa5c3eff9e')
        self.assertEqual(OFFICIAL_REVIEW['archive']['member_count'], 1679)
        self.assertEqual(OFFICIAL_REVIEW['archive']['expanded_bytes'], 126591016)
        self.assertEqual(len(OFFICIAL_REVIEW['slice_files']), 152)
        self.assertEqual(OFFICIAL_REVIEW['framework_file_count'], 149)
        self.assertEqual(set(OFFICIAL_PRODUCT), {'OpenSSL', 'Info.plist', 'PrivacyInfo.xcprivacy', '_CodeSignature/CodeResources'})
        self.assertEqual(OFFICIAL_PRODUCT['OpenSSL'], {'bytes': 5113136, 'sha256': '355ff3a21cb4eb8ef86bfba202414de1a9070b3ddf8703d03cedfcacbe9e5431'})
        self.assertEqual(OFFICIAL_PRODUCT['_CodeSignature/CodeResources'], {'bytes': 33644, 'sha256': '36939ffaffe0975d13c057afaf9b51f43487f7229890f17a861fb0bdcdc6e3e3'})
        self.assertEqual(contract._project(OFFICIAL_REVIEW['slice_files']), OFFICIAL_PRODUCT)
        self.assertEqual(contract._load_reviewed_inventory(), OFFICIAL_REVIEW)

    def test_historical_workspace_schema_is_bound_but_never_current_evidence(self):
        fixture = HERE / 'tests/fixtures/historical-39167906885.workspace-state.json'
        identity = json.loads((HERE / 'tests/fixtures/historical-39167906885.workspace-state.identity.json').read_bytes())
        self.assertEqual(identity, {
            'artifact_id': 12152932040, 'artifact_zip_bytes': 26321838,
            'artifact_zip_sha256': 'ffa758e74d0fb40460c0ca4a7c7dd223e527b4ceaee5a36aa87ddbf5483fe5b9',
            'host_commit': '083b0f425549f987081005a97cacba814f456e11',
            'member': 'dependencies/workspace-state.json', 'member_bytes': 12910,
            'member_sha256': '8689c8fccf3f9a1381be2462096af1e85f793678d0c296e12a6ac88b6b5a4275',
            'purpose': 'Historical raw SwiftPM schema fixture only; never current-run source observation',
            'run_id': 39167906885})
        raw = fixture.read_bytes()
        self.assertEqual(description(raw), {'bytes': identity['member_bytes'], 'sha256': identity['member_sha256']})
        historical_root = Path('/Users/runner/work/_temp/embedded-sidestore-derived-data/SourcePackages')
        observed_schema = contract._workspace(raw, historical_root)
        self.assertEqual(observed_schema['dependency'], contract._expected_dependency())
        self.assertEqual(observed_schema['artifact'], contract._expected_artifact(historical_root))
        self.assertNotIn('kind', observed_schema)  # This is never a valid source proof.
        with self.assertRaises(contract.OpenSSLArtifactError):
            contract.validate_source_proof(observed_schema)

    def test_public_api_has_no_expected_identity_override(self):
        import inspect
        self.assertEqual(list(inspect.signature(contract.verify_sidestore_openssl).parameters),
                         ['package_root', 'package_record', 'workspace_state_raw', 'packages_root', 'archive_path'])
        self.assertNotIn('#', contract.ARCHIVE_URL)


class SyntheticBindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.packages = self.root / 'packages'
        self.package = self.packages / contract.PACKAGE_RELATIVE
        self.package.mkdir(parents=True)
        manifest = (HERE / 'tests/fixtures/RemotePairingKit.Package.swift').read_bytes()
        (self.package / 'Package.swift').write_bytes(manifest)
        git(self.package, 'init', '-b', 'main')
        git(self.package, 'remote', 'add', 'origin', contract.SOURCE_REPOSITORY)
        git(self.package, 'add', 'Package.swift')
        git(self.package, 'commit', '-m', 'Synthetic static fixture only')
        commit = git(self.package, 'rev-parse', 'HEAD')
        tree = git(self.package, 'rev-parse', 'HEAD^{tree}')
        self.review = copy.deepcopy(OFFICIAL_REVIEW)
        self.slice_contents = {name: ('synthetic inert fixture: ' + name).encode()
                               for name in self.review['slice_files']}
        self.metadata_contents = {name: ('synthetic metadata: ' + name).encode()
                                  for name in self.review['xcframework_metadata_files']}
        self.metadata_contents['Info.plist'] = plistlib.dumps({
            'CFBundlePackageType': 'XFWK', 'XCFrameworkFormatVersion': '1.0',
            'AvailableLibraries': self.review['xcframework_libraries']})
        self.review['slice_files'] = {name: description(raw) for name, raw in self.slice_contents.items()}
        self.review['xcframework_metadata_files'] = {name: description(raw) for name, raw in self.metadata_contents.items()}
        self.review['expected_product_files'] = contract._project(self.review['slice_files'])
        directories = {contract.ARCHIVE_PREFIX}
        directories.update(contract.ARCHIVE_PREFIX + name + '/' for name in self.review['archive_root_names'] if name != 'Info.plist')
        directories.update(contract.SLICE_PREFIX + name + '/' for name in self.review['slice_directories'])
        self.entries = [(name, b'', stat.S_IFDIR | 0o755) for name in sorted(directories)]
        self.entries += [(contract.SLICE_PREFIX + name, raw, stat.S_IFREG | 0o644) for name, raw in self.slice_contents.items()]
        self.entries += [(contract.ARCHIVE_PREFIX + name, raw, stat.S_IFREG | 0o644) for name, raw in self.metadata_contents.items()]
        self.entries += [(name, target.encode(), stat.S_IFLNK | 0o755) for name, target in self.review['other_slice_links'].items()]
        self.archive = self.root / 'synthetic.zip'
        raw = zip_bytes(self.entries)
        self.archive.write_bytes(raw)
        self.review['archive'] = {**description(raw), 'member_count': len(self.entries),
                                  'expanded_bytes': sum(len(row[1]) for row in self.entries)}
        patcher = mock.patch.multiple(contract, SOURCE_COMMIT=commit, SOURCE_TREE=tree,
                                      ARCHIVE_SHA256=sha(raw), ARCHIVE_BYTES=len(raw),
                                      REVIEWED_INVENTORY=self.review,
                                      EXPECTED_PRODUCT_FILES=self.review['expected_product_files'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.artifact = self.packages / contract.ARTIFACT_RELATIVE
        self.artifact.mkdir(parents=True)
        for name in self.review['archive_root_names']:
            if name != 'Info.plist':
                (self.artifact / name).mkdir()
        for name in self.review['slice_directories']:
            (self.artifact / 'ios-arm64' / name).mkdir(parents=True, exist_ok=True)
        for name, content in self.slice_contents.items():
            (self.artifact / 'ios-arm64' / name).write_bytes(content)
        for name, content in self.metadata_contents.items():
            (self.artifact / name).write_bytes(content)
        self.state = {'object': {'dependencies': [contract._expected_dependency()],
                                 'artifacts': [contract._expected_artifact(self.packages)]}, 'version': 6}
        self.record = primitives.verify_checkout(self.package, commit, owner='remotepairingkit')
        self.record['origin'] = primitives.verify_origin(self.package, contract.SOURCE_REPOSITORY, commit,
                                                        resolver_root=self.packages)

    def verify(self, **changes):
        arguments = {'package_root': self.package, 'package_record': self.record,
                     'workspace_state_raw': json.dumps(self.state).encode(),
                     'packages_root': self.packages, 'archive_path': self.archive}
        arguments.update(changes)
        return contract.verify_sidestore_openssl(**arguments)

    def mutated_archive(self, entries, expected_digest=True):
        raw = zip_bytes(entries)
        if expected_digest:
            # Narrowly bypass ONLY the full archive byte identity in malformed
            # structure tests, so rejection must come from a deeper boundary.
            with mock.patch.multiple(contract, ARCHIVE_SHA256=sha(raw), ARCHIVE_BYTES=len(raw)):
                return contract._archive_inventory(raw)
        return contract._archive_inventory(raw)

    def test_positive_synthetic_sources_produce_complete_separate_inventories(self):
        proof = self.verify()
        self.assertIs(contract.validate_source_proof(proof), proof)
        self.assertEqual(proof['archive_slice_inventory'], self.review['slice_files'])
        self.assertEqual(proof['extracted_slice_inventory'], self.review['slice_files'])
        self.assertIsNot(proof['archive_slice_inventory'], proof['extracted_slice_inventory'])
        self.assertEqual(proof['expected_product_files'], self.review['expected_product_files'])
        self.assertEqual(proof['workspace']['sha256'], sha(json.dumps(self.state).encode()))
        self.assertEqual(proof['normalization'], 'none')
        self.assertFalse(proof['executed'])
        self.assertFalse(proof['archive_extracted'])
        self.assertFalse((self.root / 'OpenSSL.xcframework').exists())
        json.dumps(proof)

    def test_archive_uses_same_single_snapshot_for_hash_and_parser(self):
        original = contract._snapshot
        calls = []
        def observe(path, limit):
            raw = original(path, limit)
            if Path(path) == self.archive:
                calls.append(path)
                # The observed snapshot is already frozen; later pathname bytes
                # must neither silently feed the parser nor be extracted.
                self.archive.write_bytes(b'substituted after snapshot')
            return raw
        with mock.patch.object(contract, '_snapshot', side_effect=observe):
            proof = self.verify()
        self.assertEqual(len(calls), 1)
        self.assertEqual(proof['archive']['sha256'], contract.ARCHIVE_SHA256)

    def test_actual_checkout_commit_tree_origin_and_manifest_are_rechecked(self):
        for field in ('commit', 'tree'):
            bad = copy.deepcopy(self.record)
            bad[field] = '0' * 40
            with self.subTest(field=field), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(package_record=bad)
        git(self.package, 'remote', 'set-url', 'origin', 'https://example.invalid/substitute.git')
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()
        git(self.package, 'remote', 'set-url', 'origin', contract.SOURCE_REPOSITORY)
        (self.package / 'Package.swift').write_bytes(b'// modified manifest')
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()

    def test_unknown_checkout_file_and_package_symlink_reject(self):
        extra = self.package / 'hidden.swift'
        extra.write_text('inert')
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()
        extra.unlink()
        link = self.root / 'package-alias'
        link.symlink_to(self.package, target_is_directory=True)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify(package_root=link)

    def test_workspace_source_url_checksum_target_path_and_identity_reject(self):
        for field, value in (('targetName', 'Other'), ('path', str(self.root / 'elsewhere')),
                             ('kind', {'unknown': {}}), ('source', {'type': 'local'}),
                             ('packageRef', {**contract._expected_ref(), 'identity': 'codesignkit'})):
            state = copy.deepcopy(self.state)
            state['object']['artifacts'][0][field] = value
            with self.subTest(field=field), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(workspace_state_raw=json.dumps(state))
        for field, value in (('url', contract.ARCHIVE_URL + '#CodeSignKit'), ('checksum', '0' * 64), ('type', 'local')):
            state = copy.deepcopy(self.state)
            state['object']['artifacts'][0]['source'][field] = value
            with self.subTest(field=field), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(workspace_state_raw=json.dumps(state))

    def test_workspace_dependency_tuple_and_duplicate_rows_reject(self):
        for key, value in (('basedOn', {}), ('subpath', '../RemotePairingKit'),
                           ('state', {'name': 'sourceControlCheckout', 'checkoutState': {'revision': '0' * 40}})):
            state = copy.deepcopy(self.state)
            state['object']['dependencies'][0][key] = value
            with self.subTest(key=key), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(workspace_state_raw=json.dumps(state))
        for family in ('dependencies', 'artifacts'):
            state = copy.deepcopy(self.state)
            state['object'][family].append(copy.deepcopy(state['object'][family][0]))
            with self.subTest(family=family), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(workspace_state_raw=json.dumps(state))
        state = copy.deepcopy(self.state)
        alias = copy.deepcopy(state['object']['artifacts'][0])
        alias['packageRef']['identity'] = 'codesignkit'
        state['object']['artifacts'].append(alias)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify(workspace_state_raw=json.dumps(state))

    def test_workspace_duplicate_json_and_nonraw_values_reject(self):
        for raw in ('{"object": {}, "object": {}}', b'\xff', b'{', '[' * 2000 + ']' * 2000, '\ud800', json.dumps(self.state).replace('null', 'NaN'), self.state):
            with self.subTest(raw=str(raw)[:30]), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify(workspace_state_raw=raw)

    def test_workspace_snapshot_bounds_symlinks_and_midread_mutation(self):
        state_path = self.packages / 'workspace-state.json'
        raw = json.dumps(self.state).encode()
        state_path.write_bytes(raw)
        self.assertEqual(contract.snapshot_workspace_state(state_path), raw)
        with mock.patch.object(contract, 'MAX_STATE_BYTES', 4):
            with self.assertRaises(contract.OpenSSLArtifactError):
                contract.snapshot_workspace_state(state_path)
        link = self.root / 'state-alias.json'
        link.symlink_to(state_path)
        with self.assertRaises(contract.OpenSSLArtifactError):
            contract.snapshot_workspace_state(link)
        original = os.fstat
        calls = []
        def changed_stat(fd):
            result = original(fd)
            calls.append(fd)
            if len(calls) == 1:
                state_path.write_bytes(raw + b'changed')
            return result
        with mock.patch.object(os, 'fstat', side_effect=changed_stat):
            with self.assertRaisesRegex(contract.OpenSSLArtifactError, 'changed during byte observation'):
                contract.snapshot_workspace_state(state_path)

    def test_safe_open_flags_are_required_not_silently_weakened(self):
        state_path = self.packages / 'workspace-state.json'
        state_path.write_bytes(json.dumps(self.state).encode())
        real_open = os.open
        observed_flags = []
        def opening(path, flags):
            observed_flags.append(flags)
            return real_open(path, flags)
        with mock.patch.object(os, 'open', side_effect=opening):
            contract.snapshot_workspace_state(state_path)
        self.assertEqual(observed_flags, [os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC])
        original = os.O_NOFOLLOW
        try:
            del os.O_NOFOLLOW
            with self.assertRaisesRegex(contract.OpenSSLArtifactError, 'flags unavailable'):
                contract.snapshot_workspace_state(state_path)
        finally:
            os.O_NOFOLLOW = original

    def test_archive_full_digest_changed_bytes_and_oversize_reject(self):
        self.archive.write_bytes(self.archive.read_bytes() + b'changed')
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()
        with mock.patch.object(contract, 'MAX_ARCHIVE_BYTES', 4):
            with self.assertRaises(contract.OpenSSLArtifactError):
                self.verify()

    def test_archive_and_artifact_symlink_or_hardlink_reject(self):
        link = self.root / 'archive-alias.zip'
        link.symlink_to(self.archive)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify(archive_path=link)
        hardlink = self.root / 'archive-hardlink.zip'
        os.link(self.archive, hardlink)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()
        hardlink.unlink()
        source = self.artifact / 'ios-arm64/OpenSSL.framework/OpenSSL'
        raw = source.read_bytes()
        source.unlink()
        outside = self.root / 'outside'
        outside.write_bytes(raw)
        source.symlink_to(outside)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()

    def test_extracted_unknown_slice_extra_signature_extra_header_and_byte_mutation_reject(self):
        for relative in ('unknown-platform/unknown', 'ios-arm64/OpenSSL.framework/_CodeSignature/Extra',
                         'ios-arm64/OpenSSL.framework/Headers/extra.h'):
            path = self.artifact / relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'extra')
            with self.subTest(relative=relative), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify()
            path.unlink()
            if relative.startswith('unknown-platform/'):
                path.parent.rmdir()
        for relative in ('ios-arm64/OpenSSL.framework/OpenSSL', 'ios-arm64/OpenSSL.framework/Info.plist',
                         'ios-arm64/OpenSSL.framework/PrivacyInfo.xcprivacy',
                         'ios-arm64/OpenSSL.framework/_CodeSignature/CodeResources',
                         'ios-arm64/OpenSSL.framework/Headers/ssl.h',
                         'ios-arm64/dSYMs/OpenSSL.framework.dSYM/Contents/Info.plist',
                         '_CodeSignature/CodeSignature', 'Info.plist'):
            path = self.artifact / relative
            raw = path.read_bytes()
            path.write_bytes(raw + b'mutation')
            with self.subTest(relative=relative), self.assertRaises(contract.OpenSSLArtifactError):
                self.verify()
            path.write_bytes(raw)

    def test_extracted_extra_directory_or_missing_excluded_file_reject(self):
        path = self.artifact / 'ios-arm64/OpenSSL.framework/Headers/unknown-directory'
        path.mkdir()
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()
        path.rmdir()
        (self.artifact / 'ios-arm64/OpenSSL.framework/Headers/ssl.h').unlink()
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.verify()

    def test_archive_unsafe_duplicate_unknown_or_special_members_reject_after_hash_override(self):
        for name, mode in (('../escape', stat.S_IFREG | 0o644),
                           ('/absolute', stat.S_IFREG | 0o644),
                           (contract.SLICE_PREFIX + 'OpenSSL.framework/../escape', stat.S_IFREG | 0o644),
                           (contract.SLICE_PREFIX + 'OpenSSL.framework\\escape', stat.S_IFREG | 0o644),
                           (contract.SLICE_PREFIX + 'fifo', stat.S_IFIFO | 0o644),
                           (contract.ARCHIVE_PREFIX + 'unknown-platform/file', stat.S_IFREG | 0o644),
                           (contract.SLICE_PREFIX + 'OpenSSL.framework/_CodeSignature/Extra', stat.S_IFREG | 0o644)):
            with self.subTest(name=name), self.assertRaises(contract.OpenSSLArtifactError):
                self.mutated_archive(self.entries + [(name, b'x', mode)])
        with self.assertWarns(UserWarning):
            with self.assertRaises(contract.OpenSSLArtifactError):
                self.mutated_archive(self.entries + [self.entries[0]])

    def test_archive_selected_symlink_and_unknown_other_symlink_reject_after_hash_override(self):
        changed = [(name, b'Elsewhere' if name.endswith('/OpenSSL.framework/OpenSSL') else raw,
                    stat.S_IFLNK | 0o755 if name.endswith('/OpenSSL.framework/OpenSSL') else mode)
                   for name, raw, mode in self.entries]
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.mutated_archive(changed)
        with self.assertRaises(contract.OpenSSLArtifactError):
            self.mutated_archive(self.entries + [(contract.ARCHIVE_PREFIX + 'macos-arm64_x86_64/extra-link', b'A', stat.S_IFLNK | 0o755)])

    def test_archive_slice_modified_or_missing_file_reject_after_hash_override(self):
        for target in ('OpenSSL.framework/Headers/ssl.h', 'OpenSSL.framework/OpenSSL',
                       'OpenSSL.framework/_CodeSignature/CodeResources'):
            name = contract.SLICE_PREFIX + target
            changed = [(key, raw + b'changed' if key == name else raw, mode) for key, raw, mode in self.entries]
            with self.subTest(target=target), self.assertRaises(contract.OpenSSLArtifactError):
                self.mutated_archive(changed)
            missing = [row for row in self.entries if row[0] != name]
            with self.subTest(missing=target), self.assertRaises(contract.OpenSSLArtifactError):
                self.mutated_archive(missing)

    def test_bounded_archive_member_count_and_expansion(self):
        for key, value in (('MAX_MEMBERS', 1), ('MAX_MEMBER_BYTES', 8), ('MAX_EXPANDED_BYTES', 8)):
            with self.subTest(key=key), mock.patch.object(contract, key, value), self.assertRaises(contract.OpenSSLArtifactError):
                contract._archive_inventory(self.archive.read_bytes())

    def test_proof_validator_rejects_changed_bindings_inventory_and_policy(self):
        proof = self.verify()
        for key, value in (('kind', 'generic'), ('executed', True), ('archive_extracted', True),
                           ('normalization', 'bitcode-strip'), ('copy_exclusions', []),
                           ('expected_product_files', {}), ('archive_slice_inventory', {}),
                           ('extracted_slice_inventory', {}), ('archive_slice_directories', []),
                           ('extracted_xcframework_metadata', {}), ('artifact_path', '/tmp/other')):
            mutated = copy.deepcopy(proof)
            mutated[key] = value
            with self.subTest(key=key), self.assertRaises(contract.OpenSSLArtifactError):
                contract.validate_source_proof(mutated)
        for section, key, value in (('manifest', 'git_blob', '0' * 40), ('package', 'tree', '0' * 40),
                                    ('archive', 'sha256', '0' * 64), ('slice', 'identifier', 'ios-simulator'),
                                    ('workspace', 'artifact', {})):
            mutated = copy.deepcopy(proof)
            mutated[section][key] = value
            with self.subTest(section=section), self.assertRaises(contract.OpenSSLArtifactError):
                contract.validate_source_proof(mutated)
        for value in (None, {}, {'kind': contract.PROOF_KIND}):
            with self.assertRaises(contract.OpenSSLArtifactError):
                contract.validate_source_proof(value)

    def test_failure_has_bounded_structured_diagnostic(self):
        error = contract.OpenSSLArtifactError('x' * 1000)
        self.assertEqual(len(error.diagnostic['reason']), 512)
        self.assertFalse(error.diagnostic['executed'])
        self.assertEqual(error.diagnostic['kind'], 'sidestore-openssl-source-mismatch')
        json.dumps(error.diagnostic)


if __name__ == '__main__':
    unittest.main(verbosity=2)
