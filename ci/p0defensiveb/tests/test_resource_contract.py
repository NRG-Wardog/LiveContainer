"""Pure host resource fixtures; no product build, Swift, native engine or network."""
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import resource_contract as r


class ResourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract, cls.translations = r.frozen_contract()
        cls.catalog = {'strings': {key: {} for key in cls.translations['translations']['en']}}
        for key in cls.contract['compound_plural_keys']: cls.catalog['strings'][key] = {}
        for key in cls.contract['plural_keys']:
            cls.catalog['strings'][key] = {'localizations': {language: {'variations': {'plural': {
                category: {'stringUnit': {'value': value}} for category, value in cls.contract['simple_plurals'][language][key].items()}}}
                for language in r.LANGUAGES}}
        cls.catalog_bytes = json.dumps(cls.catalog).encode()

    def setUp(self):
        self.files = {}
        for language in r.LANGUAGES:
            self.files[language+'.lproj/Localizable.strings'] = copy.deepcopy(self.translations['translations'][language])
            plurals = copy.deepcopy(self.translations['compoundPlurals'][language])
            for key in self.contract['plural_keys']:
                plurals[key] = {'NSStringLocalizedFormatKey': '%#@count@',
                                'count': {'NSStringFormatSpecTypeKey': 'NSStringPluralRuleType',
                                          'NSStringFormatValueTypeKey': 'lld', **self.contract['simple_plurals'][language][key]}}
            self.files[language+'.lproj/Localizable.stringsdict'] = plurals
        for language in r.PERMISSION_LANGUAGES:
            self.files[language+'.lproj/InfoPlist.strings'] = {'CFBundleName': 'LiveContainer',
                **{key: self.contract['permission_expected'][language] for key in self.contract['permission_purpose_keys']}}

    def verify(self):
        blobs = {name: plistlib.dumps(value) for name, value in self.files.items()}
        with mock.patch.object(r, 'frozen_contract', return_value=(self.contract, self.translations)), mock.patch.object(r, 'ordinary_bytes', return_value=self.catalog_bytes), mock.patch.object(r, 'CATALOG_SHA256', hashlib.sha256(self.catalog_bytes).hexdigest()):
            return r.verify_compiled_resources(blobs.__getitem__, blobs, Path('/synthetic/livecontainer'))

    def test_full_current_contract_is_2088_keys_and_24_plural_rows(self):
        receipt = self.verify()
        self.assertEqual(receipt['localization']['coverage']['catalogKeys'], 2088)
        self.assertEqual(receipt['exactPluralValues']['checkedLanguageRows'], 24)
        self.assertFalse(receipt['exactPluralValues']['runtimePluralSelection'])
        self.assertEqual(len(receipt['compiledResourceFiles']), 15)
        self.assertEqual(len(self.contract['permission_purpose_keys']), 32)
        self.assertEqual(len(self.contract['permission_languages']), 7)

    def test_missing_resource_fails(self):
        del self.files['he.lproj/InfoPlist.strings']
        with self.assertRaisesRegex(ValueError, 'missing'): self.verify()

    def test_altered_scalar_and_wrong_language_fail(self):
        key = next(iter(self.translations['translations']['zh-Hans']))
        self.files['zh-Hans.lproj/Localizable.strings'][key] = 'wrong language'
        with self.assertRaisesRegex(ValueError, 'scalar'): self.verify()

    def test_compound_scalar_duplicate_and_argument_change_fail(self):
        key = self.contract['compound_plural_keys'][0]
        self.files['en.lproj/Localizable.strings'][key] = 'duplicate'
        with self.assertRaisesRegex(ValueError, 'duplicated'): self.verify()
        del self.files['en.lproj/Localizable.strings'][key]
        self.files['en.lproj/Localizable.stringsdict'][key]['NSStringLocalizedFormatKey'] = '%1$#@arg1@'
        with self.assertRaisesRegex(ValueError, 'compound'): self.verify()

    def test_all_24_simple_plural_values_checked(self):
        for language in r.LANGUAGES:
            for key in self.contract['plural_keys']:
                row = self.files[language+'.lproj/Localizable.stringsdict'][key]['count']
                original = row['other']; row['other'] = 'wrong %lld'
                with self.subTest(language=language, key=key), self.assertRaisesRegex(ValueError, 'categories/text'):
                    self.verify()
                row['other'] = original

    def test_outer_position_extra_argument_and_wrong_type_fail(self):
        key = self.contract['plural_keys'][0]
        row = self.files['en.lproj/Localizable.stringsdict'][key]
        for fmt in ('%2$#@count@', '%#@count@ %lld', '%#@count@ %#@count@', '%n'):
            row['NSStringLocalizedFormatKey'] = fmt
            with self.subTest(fmt=fmt), self.assertRaises(ValueError): self.verify()
        row['NSStringLocalizedFormatKey'] = '%#@count@'; row['count']['NSStringFormatValueTypeKey'] = 'd'
        with self.assertRaisesRegex(ValueError, 'rule type'): self.verify()

    def test_permission_aliases_and_exact_key_inventory_checked(self):
        name = 'zh_HK.lproj/InfoPlist.strings'; key = self.contract['permission_purpose_keys'][0]
        self.files[name][key] = self.contract['permission_expected']['en']
        with self.assertRaisesRegex(ValueError, 'permission'): self.verify()
        self.files[name][key] = self.contract['permission_expected']['zh_HK']
        self.files[name]['NSLocationTemporaryUsageDescriptionDictionary'] = 'invented scalar'
        with self.assertRaisesRegex(ValueError, 'permission'): self.verify()

    def test_source_catalog_must_match_pinned_current_bytes(self):
        with mock.patch.object(r, 'ordinary_bytes', return_value=b'{}'), mock.patch.object(r, 'frozen_contract', return_value=(self.contract, self.translations)):
            with self.assertRaisesRegex(ValueError, 'source differs'):
                r.verify_compiled_resources(lambda name: b'', set(self.files), Path('/synthetic'))

    def test_frozen_fixture_hash_tampering_rejected(self):
        with mock.patch.object(r, 'CONTRACT_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'contract changed'): r.frozen_contract()

    def test_unsafe_format_tokens_rejected(self):
        for value in ('%n', '%2$lld', '%*lld', '%lld %lld', '%@', '%d'):
            with self.subTest(value=value), self.assertRaises(ValueError): r.check_format(value, 1)
        r.check_format('%% %1$lld', 1)
        r.check_format('literal %%', 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
