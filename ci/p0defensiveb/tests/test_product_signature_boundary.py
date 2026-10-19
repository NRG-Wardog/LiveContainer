"""Offline synthetic product-boundary tests; no native/dependency execution.

The positive signature fixture below is deliberately synthetic. Its binary hash,
product inventory and source-proof validator are patched together in a local
context. Passing these tests is not evidence that a genuine RemotePairingKit
binary, source checkout or code signature was verified or executed.
"""
import contextlib
import hashlib
import json
from pathlib import Path
import plistlib
import stat
import struct
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import macho_contract as m


PINNED_REMOTE_PAIRING_BINARY_SHA256 = '355ff3a21cb4eb8ef86bfba202414de1a9070b3ddf8703d03cedfcacbe9e5431'
OPENSSL_BUNDLE = 'Frameworks/OpenSSL.framework'
DIAGNOSTIC_LIMIT = 8 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def synthetic_binary(*, filetype=2, signed=False):
    """Construct parser bytes only, not a runnable or authentically signed image."""
    command_bytes = 72 + 24 + (24 if filetype == 2 else 0) + (16 if signed else 0)
    end = 32 + command_bytes
    length = end + 32
    segment = struct.pack('<2I16s4Q4I', 0x19, 72, b'__TEXT', 0x100000000,
                          length, 0, length, 5, 5, 0, 0)
    version = struct.pack('<6I', 0x32, 24, 2, 15 << 16, 26 << 16, 0)
    main = struct.pack('<2I2Q', 0x80000028, 24, end, 0) if filetype == 2 else b''
    signature = struct.pack('<4I', 0x1d, 16, end + 16, 16) if signed else b''
    header = struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, filetype,
                         2 + (filetype == 2) + signed, command_bytes, 0, 0)
    return header + segment + version + main + signature + b'\0' * 32


def unsigned_files():
    return {'Info.plist': plistlib.dumps({'CFBundleExecutable': 'Synthetic'}),
            'Synthetic': synthetic_binary()}


def file_inventory(files):
    return {name: {'sha256': sha(raw), 'bytes': len(raw)}
            for name, raw in sorted(files.items())}


class ProductSignatureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.app = self.base / 'Synthetic.app'
        self.app.mkdir()

    def write_files(self, files, root=None):
        root = root or self.app
        for relative, raw in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        return root

    def finite_json(self, report):
        raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        self.assertLessEqual(len(raw), DIAGNOSTIC_LIMIT)
        return raw.decode()

    def reject_app(self, files, *, owner='SideStore', **kwargs):
        self.write_files(files)
        inventories = []
        with self.assertRaises(m.ProductValidationError) as caught:
            m.inspect_app(self.app, owner=owner, on_inventory=inventories.append, **kwargs)
        report = caught.exception.diagnostic
        self.assert_failed_inventory(report, files, owner=owner)
        self.assertEqual(len(inventories), 1)
        self.finite_json(inventories[0])
        self.assertEqual(inventories[0]['status'], 'PRODUCT_HASH_INVENTORY_CAPTURED')
        self.assertTrue(inventories[0]['snapshot_complete'])
        self.assertEqual(report['inventory_sha256'], inventories[0]['inventory_sha256'])
        self.assertEqual(report['inventory'], inventories[0]['inventory'])
        return report, inventories[0]

    def make_ipa(self, members, *, path=None):
        path = path or self.base / 'internal.ipa'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'w') as archive:
                for name, raw in members:
                    archive.writestr(name, raw)
        return path

    def app_members(self, files=None):
        return [('Payload/Synthetic.app/' + name, raw)
                for name, raw in (files or unsigned_files()).items()]

    @contextlib.contextmanager
    def synthetic_source_authorization(self, *, bundle=OPENSSL_BUNDLE):
        # Explicitly scoped test doubles: this is NOT a genuine source proof.
        import openssl_artifact_contract as source
        framework = {'Info.plist': plistlib.dumps({'CFBundleExecutable': 'OpenSSL'}),
                     'OpenSSL': synthetic_binary(filetype=6, signed=True),
                     'PrivacyInfo.xcprivacy': plistlib.dumps({'SyntheticFixtureOnly': True}),
                     '_CodeSignature/CodeResources': b'SYNTHETIC-SIGNATURE-CONTENT-CANARY'}
        expected = file_inventory(framework)
        proof = {'fixture_only': True, 'expected_product_files': expected}
        files = unsigned_files()
        files.update({bundle + '/' + name: raw for name, raw in framework.items()})
        with mock.patch.object(source, 'EXPECTED_PRODUCT_FILES', expected), \
                mock.patch.object(source, 'validate_source_proof', return_value=proof) as validate, \
                mock.patch.object(m, 'SIDESTORE_OPENSSL_BINARY_SHA', sha(framework['OpenSSL'])):
            yield files, proof, validate

    def assert_failed_inventory(self, report, files, *, owner='SideStore'):
        self.assertEqual(report['status'], 'PRODUCT_STATIC_VALIDATION_FAILED')
        self.assertEqual(report['owner'], owner)
        self.assertFalse(report['executed'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['omitted_files'], 0)
        self.assertEqual(report['file_count'], len(files))
        self.assertEqual(report['inventory'], file_inventory(files))
        self.finite_json(report)

    def test_inventory_is_complete_hash_only_deterministic_and_finite(self):
        files = {'z': b'PRIVATE-CONTENT-CANARY', 'a': b'other'}
        context = {'stage': 'bundle', 'bundle': '', 'executable': 'z', 'executable_path': 'z'}
        report = m.product_inventory(files, 'SideStore', context=context)
        self.assertTrue(report['complete'])
        self.assertFalse(report['executed'])
        self.assertEqual(report['status'], 'PRODUCT_HASH_INVENTORY_CAPTURED')
        self.assertEqual(report['owner'], 'SideStore')
        self.assertEqual(report['inventory'], file_inventory(files))
        self.assertEqual(report['file_count'], 2)
        self.assertEqual(report['total_bytes'], sum(map(len, files.values())))
        self.assertEqual(report['omitted_files'], 0)
        self.assertEqual(report['executable'], file_inventory(files)['z'])
        canonical = json.dumps(file_inventory(files), sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True).encode('ascii')
        self.assertEqual(report['inventory_sha256'], sha(canonical))
        self.assertEqual(report, m.product_inventory(dict(reversed(list(files.items()))),
                                                     'SideStore', context=context))
        self.assertNotIn('PRIVATE-CONTENT-CANARY', self.finite_json(report))

    def test_inventory_count_and_path_bounds_preserve_failure_with_fixed_omission(self):
        cases = [({str(index): b'' for index in range(20001)}, 'FILE_COUNT_LIMIT'),
                 ({'x' * 1025: b'private'}, 'PATH_LENGTH_LIMIT')]
        for files, bound in cases:
            with self.subTest(bound=bound):
                report = m.product_inventory(files, 'SideStore',
                    status='PRODUCT_STATIC_VALIDATION_FAILED', reason='original validation failure')
                self.assertFalse(report['complete'])
                self.assertEqual(report['status'], 'PRODUCT_STATIC_VALIDATION_FAILED')
                self.assertEqual(report['bound_failure'], bound)
                self.assertEqual(report['omitted_files'], len(files))
                self.assertEqual(report['file_count'], len(files))
                self.assertNotIn('inventory', report)
                self.assertNotIn('signature_resources', report)
                self.finite_json(report)

    def test_inventory_serialized_bound_keeps_failure_and_digest(self):
        files = {str(index) + 'x' * 900: b'' for index in range(9000)}
        report = m.product_inventory(files, 'SideStore', status='PRODUCT_STATIC_VALIDATION_FAILED')
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'PRODUCT_STATIC_VALIDATION_FAILED')
        self.assertEqual(report['bound_failure'], 'SERIALIZED_SIZE_LIMIT')
        self.assertEqual(report['file_count'], 9000)
        self.assertEqual(report['omitted_files'], 9000)
        self.assertRegex(report['inventory_sha256'], r'^[a-f0-9]{64}$')
        self.assertNotIn('inventory', report)
        self.finite_json(report)

    def test_untrusted_diagnostic_metadata_cannot_escape_serialized_limit(self):
        for kwargs in ({'context': {'x' * (DIAGNOSTIC_LIMIT + 1): 'value'}},
                       {'context': {str(index): 'x' * 1024 for index in range(9000)}},
                       {'reason': 'x' * (DIAGNOSTIC_LIMIT + 1)}):
            with self.subTest(metadata=next(iter(kwargs))):
                report = m.product_inventory({'a': b'private'}, 'SideStore',
                    status='PRODUCT_STATIC_VALIDATION_FAILED', **kwargs)
                self.assertEqual(report['status'], 'PRODUCT_STATIC_VALIDATION_FAILED')
                self.finite_json(report)
        self.finite_json(m.product_inventory({'a': b'private'}, 'SideStore',
                                            context={'stage': float('nan'), 'bundle': float('inf')}))
        for status in ('PASSED', 'unbounded-' + 'x' * (DIAGNOSTIC_LIMIT + 1)):
            with self.assertRaises(ValueError):
                m.product_inventory({'a': b'private'}, 'SideStore', status=status)

    def test_synthetic_exact_source_bound_framework_is_only_metadata_tolerated(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            result = m._inspect_files(files, root_bundle='', owner='SideStore',
                                      sidestore_openssl_proof=proof)
            validate.assert_called_once_with(proof)
            binary = result['binaries'][OPENSSL_BUNDLE + '/OpenSSL']
            self.assertFalse(binary['unsigned'])
            self.assertFalse(binary['executed'])
            self.assertEqual(binary['signature_kind'], 'PINNED_PREEXISTING_METADATA_NOT_VALIDATED')
            self.assertEqual(result['inventory'], file_inventory(files))
            self.assertEqual(result['preexisting_signature_resources'], {
                OPENSSL_BUNDLE + '/_CodeSignature/CodeResources':
                sha(files[OPENSSL_BUNDLE + '/_CodeSignature/CodeResources'])})
            self.assertTrue(result['binaries']['Synthetic']['unsigned'])

    def test_legacy_prebuilt_switch_is_not_an_escape_for_other_owners(self):
        for owner in ('SideStore', 'SideBackup'):
            with self.subTest(owner=owner), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner=owner,
                        allow_pinned_prebuilt=True, sidestore_openssl_proof=proof)
                self.assert_failed_inventory(caught.exception.diagnostic, files, owner=owner)
                validate.assert_not_called()

    def test_livecontainer_legacy_pinned_framework_behavior_is_preserved(self):
        # These patches validate the old API's policy shape, not genuine binaries.
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            with mock.patch.object(m, 'OPENSSL_BINARY_SHA', sha(files[OPENSSL_BUNDLE + '/OpenSSL'])), \
                    mock.patch.object(m, 'OPENSSL_RESOURCES_SHA',
                        sha(files[OPENSSL_BUNDLE + '/_CodeSignature/CodeResources'])):
                result = m._inspect_files(files, root_bundle='', owner='LiveContainer',
                                          allow_pinned_prebuilt=True)
            validate.assert_not_called()
            self.assertFalse(result['binaries'][OPENSSL_BUNDLE + '/OpenSSL']['unsigned'])
            self.assertFalse(result['executed'])

    def test_source_inventory_cannot_substitute_for_exact_pinned_binary_hash(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            with mock.patch.object(m, 'SIDESTORE_OPENSSL_BINARY_SHA', '0' * 64):
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
            validate.assert_called_once_with(proof)
            self.assert_failed_inventory(caught.exception.diagnostic, files)
            self.assertIn('pinned SideStore OpenSSL binary bytes differ', caught.exception.diagnostic['reason'])

    def test_pinned_synthetic_hash_without_source_proof_is_rejected(self):
        for allow in (False, True):
            with self.subTest(allow=allow), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore', allow_pinned_prebuilt=allow)
                validate.assert_not_called()
                self.assert_failed_inventory(caught.exception.diagnostic, files)

    def test_rejected_source_proof_does_not_enable_signature(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            validate.side_effect = ValueError('synthetic source proof rejection')
            with self.assertRaises(m.ProductValidationError) as caught:
                m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
            validate.assert_called_once_with(proof)
            self.assert_failed_inventory(caught.exception.diagnostic, files)
            self.assertIn('synthetic source proof rejection', caught.exception.diagnostic['reason'])

    def test_owner_scope_is_exact_even_with_validated_source_proof(self):
        for owner in (None, 'LiveContainer', 'SideBackup'):
            with self.subTest(owner=owner), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner=owner,
                        sidestore_openssl_proof=proof)
                validate.assert_not_called()
                self.assert_failed_inventory(caught.exception.diagnostic, files, owner=owner)

    def test_framework_path_scope_is_exact_not_a_suffix_match(self):
        for bundle in ('OpenSSL.framework', 'Other/OpenSSL.framework',
                       'Frameworks/Nested/OpenSSL.framework', 'Frameworks/Other.framework'):
            with self.subTest(bundle=bundle), self.synthetic_source_authorization(bundle=bundle) as inputs:
                files, proof, validate = inputs
                # Keep the required exact-path copy so this reaches the separate
                # wrong-path signature check instead of the missing-copy guard.
                files.update({OPENSSL_BUNDLE + name[len(bundle):]: raw
                              for name, raw in list(files.items()) if name.startswith(bundle + '/')})
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore',
                        sidestore_openssl_proof=proof)
                report = caught.exception.diagnostic
                self.assert_failed_inventory(report, files)
                self.assertEqual(report['context']['bundle'], bundle)
                self.assertIn('unexpectedly has signature resources', report['reason'])
                self.assertEqual(validate.call_count, int(OPENSSL_BUNDLE < bundle))

    def test_source_proof_requires_the_copied_framework_to_exist(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            files = {name: raw for name, raw in files.items()
                     if not name.startswith(OPENSSL_BUNDLE + '/')}
            report, inventory = self.reject_app(files, sidestore_openssl_proof=proof)
            validate.assert_not_called()
            self.assertEqual(report['context'], {'stage': 'product', 'bundle': ''})
            self.assertEqual(report['reason'], 'verified SideStore OpenSSL copied framework is mandatory')
            self.assertEqual(report['inventory_sha256'], inventory['inventory_sha256'])

    def test_source_proof_cannot_be_applied_to_a_nonroot_product(self):
        for bundle in ('Payload/Synthetic.app', 'Embedded.app'):
            with self.subTest(root=bundle), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                files = {bundle + '/' + name: raw for name, raw in files.items()}
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle=bundle, owner='SideStore',
                                     sidestore_openssl_proof=proof)
                validate.assert_not_called()
                report = caught.exception.diagnostic
                self.assert_failed_inventory(report, files)
                self.assertEqual(report['context'], {'stage': 'product', 'bundle': bundle})
                self.assertEqual(report['reason'], 'SideStore source proof is owner/root scoped')

    def test_all_four_copied_framework_files_are_hash_and_size_bound(self):
        for relative in ('OpenSSL', 'Info.plist', 'PrivacyInfo.xcprivacy', '_CodeSignature/CodeResources'):
            with self.subTest(file=relative), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                path = OPENSSL_BUNDLE + '/' + relative
                files[path] += b'changed product bytes'
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
                report = caught.exception.diagnostic
                self.assert_failed_inventory(report, files)
                self.assertIn(sha(files[path]), self.finite_json(report))

    def test_additional_signature_resources_and_framework_files_are_rejected(self):
        for relative in ('_CodeSignature/Extra', 'unreviewed-resource'):
            with self.subTest(file=relative), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                path = OPENSSL_BUNDLE + '/' + relative
                files[path] = b'EXTRA-CONTENT-CANARY'
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
                report = caught.exception.diagnostic
                self.assert_failed_inventory(report, files)
                self.assertIn(path, self.finite_json(report))
                self.assertNotIn('EXTRA-CONTENT-CANARY', self.finite_json(report))
                if relative.startswith('_CodeSignature/'):
                    self.assertEqual(report['signature_resources'][path], file_inventory(files)[path])

    def test_missing_copied_framework_file_is_rejected(self):
        for relative in ('OpenSSL', 'Info.plist', 'PrivacyInfo.xcprivacy', '_CodeSignature/CodeResources'):
            with self.subTest(file=relative), self.synthetic_source_authorization() as inputs:
                files, proof, validate = inputs
                del files[OPENSSL_BUNDLE + '/' + relative]
                with self.assertRaises(m.ProductValidationError) as caught:
                    m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
                self.assert_failed_inventory(caught.exception.diagnostic, files)

    def test_mocked_validator_does_not_replace_exact_expected_product_binding(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            proof['expected_product_files'] = dict(proof['expected_product_files'])
            proof['expected_product_files']['OpenSSL'] = {'sha256': '0' * 64, 'bytes': 1}
            with self.assertRaises(m.ProductValidationError) as caught:
                m._inspect_files(files, root_bundle='', owner='SideStore', sidestore_openssl_proof=proof)
            validate.assert_called_once_with(proof)
            self.assert_failed_inventory(caught.exception.diagnostic, files)

    def test_same_signed_framework_is_never_allowed_in_internal_ipa(self):
        with self.synthetic_source_authorization() as inputs:
            files, proof, validate = inputs
            path = self.make_ipa(self.app_members(files))
            inventories = []
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_internal_ipa(path, on_inventory=inventories.append)
            validate.assert_not_called()
            report = caught.exception.diagnostic
            self.assert_failed_inventory(report, dict(self.app_members(files)), owner='SideBackup')
            self.assertEqual(len(inventories), 1)
            self.assertEqual(report['inventory'], inventories[0]['inventory'])
            self.assertEqual(report['inventory_sha256'], inventories[0]['inventory_sha256'])

    def test_pinned_binary_constant_names_reviewed_remote_pairing_bytes(self):
        self.assertEqual(m.SIDESTORE_OPENSSL_BINARY_SHA, PINNED_REMOTE_PAIRING_BINARY_SHA256)
        self.assertNotEqual(sha(synthetic_binary(filetype=6, signed=True)), m.SIDESTORE_OPENSSL_BINARY_SHA)

    def test_unsigned_app_and_framework_remain_static_products(self):
        files = unsigned_files()
        files.update({'Frameworks/New.framework/Info.plist':
                      plistlib.dumps({'CFBundleExecutable': 'New'}),
                      'Frameworks/New.framework/New': synthetic_binary(filetype=6)})
        self.write_files(files)
        inventories = []
        result = m.inspect_app(self.app, owner='SideStore', on_inventory=inventories.append)
        self.assertEqual(len(inventories), 1)
        self.assertFalse(result['executed'])
        self.assertTrue(result['unsigned'])
        self.assertEqual(result['product']['inventory'], file_inventory(files))
        self.assertTrue(all(not value['executed'] and value['unsigned']
                            for value in result['product']['binaries'].values()))

    def test_signature_on_new_main_executable_is_always_rejected(self):
        files = unsigned_files()
        files['Synthetic'] = synthetic_binary(signed=True)
        report, inventory = self.reject_app(files)
        encoded = self.finite_json(report)
        for retained in ('SideStore', 'Synthetic', sha(files['Synthetic'])):
            self.assertIn(retained, encoded)
        self.assertNotIn('PASSED', encoded)
        self.assertEqual(report['context'], {'stage': 'bundle', 'bundle': '',
            'executable': 'Synthetic', 'executable_path': 'Synthetic'})
        self.assertEqual(report['executable'], file_inventory(files)['Synthetic'])

    def test_signature_resources_on_new_main_bundle_are_rejected_and_named(self):
        files = unsigned_files()
        files['_CodeSignature/CodeResources'] = b'SIGNATURE-CONTENT-CANARY'
        report, inventory = self.reject_app(files)
        encoded = self.finite_json(report)
        self.assertIn('_CodeSignature/CodeResources', encoded)
        self.assertIn(sha(files['Synthetic']), encoded)
        self.assertNotIn('SIGNATURE-CONTENT-CANARY', encoded)
        self.assertEqual(report['signature_resources'], {
            '_CodeSignature/CodeResources': file_inventory(files)['_CodeSignature/CodeResources']})

    def test_signature_on_new_embedded_framework_is_rejected(self):
        files = unsigned_files()
        files.update({'Frameworks/New.framework/Info.plist':
                      plistlib.dumps({'CFBundleExecutable': 'New'}),
                      'Frameworks/New.framework/New': synthetic_binary(filetype=6, signed=True)})
        report, inventory = self.reject_app(files)
        encoded = self.finite_json(report)
        self.assertIn('Frameworks/New.framework', encoded)
        self.assertEqual(report['context']['bundle'], 'Frameworks/New.framework')
        self.assertEqual(report['context']['executable'], 'New')
        self.assertIn(sha(files['Frameworks/New.framework/New']), encoded)

    def test_signature_on_unselected_dylib_is_rejected(self):
        files = unsigned_files()
        files['Frameworks/extra.dylib'] = synthetic_binary(filetype=6, signed=True)
        report, inventory = self.reject_app(files)
        encoded = self.finite_json(report)
        self.assertIn('Frameworks/extra.dylib', encoded)
        self.assertEqual(report['context']['stage'], 'unselected-member')
        self.assertEqual(report['context']['executable_path'], 'Frameworks/extra.dylib')
        self.assertIn(sha(files['Frameworks/extra.dylib']), encoded)

    def test_invalid_info_plist_is_typed_and_preserves_original_inventory(self):
        for raw in (b'not a plist', plistlib.dumps([]), plistlib.dumps({'CFBundleExecutable': '../escape'})):
            with self.subTest(raw=raw):
                files = unsigned_files()
                files['Info.plist'] = raw
                report, inventory = self.reject_app(files)
                self.assertIn(sha(raw), self.finite_json(report))
                self.assertIn(sha(files['Synthetic']), self.finite_json(inventory))

    def test_missing_actual_info_plist_executable_remains_a_failure(self):
        files = {'Info.plist': plistlib.dumps({'CFBundleExecutable': 'Absent'}),
                 'Synthetic': synthetic_binary()}
        report, inventory = self.reject_app(files)
        encoded = self.finite_json(report)
        self.assertIn('Absent', encoded)
        self.assertIn('Synthetic', self.finite_json(inventory))

    def test_extra_malformed_dylib_and_unknown_macho_are_rejected(self):
        for raw in (b'not Mach-O', synthetic_binary(filetype=1), synthetic_binary()[:15]):
            with self.subTest(raw=raw):
                files = unsigned_files()
                files['extra.dylib'] = raw
                report, inventory = self.reject_app(files)
                self.assertIn('extra.dylib', self.finite_json(report))
                self.assertIn(sha(raw), self.finite_json(inventory))

    def test_incomplete_inventory_is_captured_before_bound_failure(self):
        files = {str(index): b'' for index in range(20001)}
        inventories = []
        with mock.patch.object(m, '_ordinary_files', return_value=files), \
                mock.patch.object(m, '_inspect_files', side_effect=AssertionError('static check ran')):
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_app(self.app, owner='SideStore', on_inventory=inventories.append)
        self.assertEqual(len(inventories), 1)
        self.assertFalse(inventories[0]['complete'])
        self.assertEqual(inventories[0]['bound_failure'], 'FILE_COUNT_LIMIT')
        report = caught.exception.diagnostic
        self.assertEqual(report['status'], 'PRODUCT_STATIC_VALIDATION_FAILED')
        self.assertEqual(report['inventory_sha256'], inventories[0]['inventory_sha256'])
        self.assertFalse(report['complete'])
        self.finite_json(report)

    def test_inventory_callback_precedes_static_validation(self):
        files = unsigned_files()
        self.write_files(files)
        events = []
        original = m._inspect_files

        def check(*args, **kwargs):
            events.append('static-check')
            return original(*args, **kwargs)

        with mock.patch.object(m, '_inspect_files', side_effect=check):
            m.inspect_app(self.app, owner='SideStore',
                          on_inventory=lambda value: events.append('inventory'))
        self.assertEqual(events, ['inventory', 'static-check'])

    def test_rejected_product_uses_single_snapshot_even_if_callback_replaces_files(self):
        files = unsigned_files()
        files['Synthetic'] = synthetic_binary(signed=True)
        self.write_files(files)
        reads = []
        snapshots = []
        original_read = Path.read_bytes

        def read_once(path):
            reads.append(path)
            return original_read(path)

        def replace_after_inventory(value):
            snapshots.append(value)
            (self.app / 'Synthetic').write_bytes(synthetic_binary())
            (self.app / 'Info.plist').write_bytes(b'replaced after snapshot')

        with mock.patch.object(Path, 'read_bytes', read_once):
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_app(self.app, owner='SideStore', on_inventory=replace_after_inventory)
        self.assertCountEqual(reads, [self.app / name for name in files])
        self.assertEqual(len(reads), len(files))
        self.assertIn(sha(files['Synthetic']), self.finite_json(snapshots[0]))
        self.assertIn(sha(files['Synthetic']), self.finite_json(caught.exception.diagnostic))
        self.assertNotIn(sha(synthetic_binary()), self.finite_json(caught.exception.diagnostic))

    def test_successful_product_uses_snapshot_when_callback_replaces_binary(self):
        files = unsigned_files()
        self.write_files(files)

        def replace_after_inventory(value):
            (self.app / 'Synthetic').write_bytes(synthetic_binary(signed=True))

        result = m.inspect_app(self.app, owner='SideStore', on_inventory=replace_after_inventory)
        self.assertEqual(result['sha256'], sha(files['Synthetic']))
        self.assertTrue(result['unsigned'])

    def test_symlink_member_is_typed_and_never_read(self):
        self.write_files(unsigned_files())
        outside = self.base / 'outside'
        outside.write_bytes(b'SYMLINK-CONTENT-CANARY')
        (self.app / 'linked').symlink_to(outside)
        reads = []
        original_read = Path.read_bytes

        def track(path):
            reads.append(path)
            return original_read(path)

        with mock.patch.object(Path, 'read_bytes', track):
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_app(self.app, owner='SideStore')
        self.assertNotIn(outside, reads)
        self.assertNotIn(self.app / 'linked', reads)
        report = caught.exception.diagnostic
        self.assertNotIn('SYMLINK-CONTENT-CANARY', self.finite_json(report))
        self.assertFalse(report['complete'])
        self.assertFalse(report['snapshot_complete'])
        self.assertTrue(report['unobserved_files_unknown'])
        self.assertEqual(report['inventory'], file_inventory(unsigned_files()))
        self.assertEqual(report['context']['member'], 'linked')

    def test_symlink_app_root_is_typed_and_never_traversed(self):
        self.write_files(unsigned_files())
        link = self.base / 'linked.app'
        link.symlink_to(self.app, target_is_directory=True)
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('symlink read')):
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_app(link, owner='SideStore')
        self.finite_json(caught.exception.diagnostic)
        self.assertFalse(caught.exception.diagnostic['snapshot_complete'])
        self.assertFalse(caught.exception.diagnostic['complete'])

    def test_internal_ipa_is_snapshot_only_and_never_extracted(self):
        path = self.make_ipa(self.app_members())
        original = path.read_bytes()
        inventories = []
        reads = []
        original_read = Path.read_bytes

        def track(p):
            reads.append(p)
            return original_read(p)

        def replace_after_inventory(value):
            inventories.append(value)
            path.write_bytes(b'replacement is not a ZIP')

        with mock.patch.object(Path, 'read_bytes', track):
            result = m.inspect_internal_ipa(path, on_inventory=replace_after_inventory)
        self.assertEqual(reads, [path])
        self.assertEqual(len(inventories), 1)
        self.assertEqual(result['sha256'], sha(original))
        self.assertFalse(result['executed'])
        self.assertFalse(result['distributed'])
        self.assertFalse((self.base / 'Payload').exists())
        self.assertIn('SideBackup', self.finite_json(inventories[0]))

    def test_internal_ipa_static_failure_retains_inventory_and_owner(self):
        files = unsigned_files()
        files['Synthetic'] = synthetic_binary(signed=True)
        path = self.make_ipa(self.app_members(files))
        inventories = []
        with self.assertRaises(m.ProductValidationError) as caught:
            m.inspect_internal_ipa(path, on_inventory=inventories.append)
        self.assertEqual(len(inventories), 1)
        encoded = self.finite_json(caught.exception.diagnostic)
        for value in ('SideBackup', 'Payload/Synthetic.app', 'Synthetic', sha(files['Synthetic'])):
            self.assertIn(value, encoded)
        self.assertNotIn('PASSED', encoded)

    def test_invalid_ipa_container_is_typed_without_extraction(self):
        path = self.base / 'invalid.ipa'
        path.write_bytes(b'not a ZIP archive')
        with self.assertRaises(m.ProductValidationError) as caught:
            m.inspect_internal_ipa(path)
        self.assertIn('SideBackup', self.finite_json(caught.exception.diagnostic))
        self.assertFalse(caught.exception.diagnostic['complete'])
        self.assertFalse(caught.exception.diagnostic['snapshot_complete'])
        self.assertTrue(caught.exception.diagnostic['unobserved_files_unknown'])
        self.assertFalse((self.base / 'Payload').exists())

    def test_unsafe_duplicate_and_symlink_ipa_members_are_typed_failures(self):
        linked = zipfile.ZipInfo('Payload/Synthetic.app/link')
        linked.create_system = 3
        linked.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [self.app_members() + [('../escape', b'x')],
                 self.app_members() + [('Payload/Synthetic.app/Synthetic', b'duplicate')],
                 self.app_members() + [(linked, b'../../outside')],
                 [('Payload/A.app/Info.plist', b'x'), ('Payload/B.app/Info.plist', b'y')]]
        for index, members in enumerate(cases):
            with self.subTest(names=[str(name) for name, _ in members]):
                path = self.make_ipa(members)
                with self.assertRaises(m.ProductValidationError) as caught:
                    m.inspect_internal_ipa(path)
                encoded = self.finite_json(caught.exception.diagnostic)
                self.assertIn('SideBackup', encoded)
                self.assertNotIn('PASSED', encoded)
                self.assertEqual(caught.exception.diagnostic['snapshot_complete'], index == 3)
                if index < 3:
                    self.assertFalse(caught.exception.diagnostic['complete'])
                    self.assertEqual(caught.exception.diagnostic['inventory'],
                                     file_inventory(dict(self.app_members())))
        self.assertFalse((self.base / 'escape').exists())
        self.assertFalse((self.base / 'Payload').exists())

    def test_symlink_internal_ipa_is_typed_without_reading(self):
        path = self.make_ipa(self.app_members())
        link = self.base / 'linked.ipa'
        link.symlink_to(path)
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('symlink read')):
            with self.assertRaises(m.ProductValidationError) as caught:
                m.inspect_internal_ipa(link)
        self.assertIn('SideBackup', self.finite_json(caught.exception.diagnostic))


if __name__ == '__main__':
    unittest.main(verbosity=2)
