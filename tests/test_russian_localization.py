"""Russian candidate contract. Does not rewrite historical four-language baselines."""
import copy
import json
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'Resources/Localizable.xcstrings'
# Brand names, technical tokens and format-only strings intentionally stay unchanged.
OPAQUE = {' · v', '%@ %@', '%@ (%@)', '%@ - %@', '%@, %@', 'Apple ID',
          'CoreDevice', 'CoreDevice: ', 'Filza', 'HTTP %@', 'LiveContainer + SideStore',
          'PID: %d', 'Twitter', 'Wi-Fi', 'Wi-Fi: ', 'WireGuard EMP', 'iOS: ',
          'lc.settings.JitUDID'}
PRINTF = re.compile(r'%(?:\d+\$)?[-+#0 ]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|ll|[hlLzjtq])?[@diuoxXfFeEgGaAcCsSp%]')


def units(entry):
    if 'stringUnit' in entry:
        yield entry['stringUnit']
    for value in entry.get('variations', {}).values():
        for child in value.values():
            yield from units(child)


def validate_substitutions(english, russian, key):
    expected = english.get('substitutions', {})
    actual = russian.get('substitutions', {})
    assert set(actual) == set(expected), (key, 'substitution names')
    assert re.findall(r'%#@[^@]+@', english.get('stringUnit', {}).get('value', '')) == re.findall(r'%#@[^@]+@', russian.get('stringUnit', {}).get('value', '')), (key, 'substitution references')
    for name, original in expected.items():
        translated = actual[name]
        assert translated['argNum'] == original['argNum'], (key, name)
        assert translated['formatSpecifier'] == original['formatSpecifier'], (key, name)
        assert set(translated['variations']['plural']) == {'one', 'few', 'many', 'other'}, (key, name)
        for category, leaf in translated['variations']['plural'].items():
            unit = leaf['stringUnit']
            assert unit['state'] == 'translated' and unit['value'], (key, name, category)
            assert unit['value'].count('%arg') == 1, (key, name, category)


def validate(strings):
    for key, row in strings.items():
        en = row['localizations']['en']
        ru = row['localizations'].get('ru')
        assert ru is not None, (key, 'missing Russian')
        validate_substitutions(en, ru, key)
        reference = list(units(en))
        localized = list(units(ru))
        assert reference and localized, (key, 'empty translation structure')
        if 'variations' in en:
            assert set(ru['variations']['plural']) == {'one', 'few', 'many', 'other'}, key
        else:
            assert 'stringUnit' in ru, key
        for unit in localized:
            value = unit['value']
            assert unit['state'] == 'translated' and value, key
            source = reference[0]['value']
            assert PRINTF.findall(source) == PRINTF.findall(value), (key, 'format mismatch')
            assert source.count('\n') == value.count('\n'), (key, 'newline mismatch')
            assert re.match(r'^\s*', source)[0] == re.match(r'^\s*', value)[0], (key, 'leading space')
            assert re.search(r'\s*$', source)[0] == re.search(r'\s*$', value)[0], (key, 'trailing space')
            assert source != value or key in OPAQUE, (key, 'English fallback')
            assert not any(c in value for c in '\u202a\u202b\u202d\u202e\u2066\u2067\u2068\u2069'), (key, 'unexpected bidi control')


class RussianLocalizationTests(unittest.TestCase):
    def test_full_catalog_and_placeholder_contract(self):
        strings = json.loads(CATALOG.read_text())['strings']
        self.assertGreaterEqual(len(strings), 2154)
        validate(strings)

    def test_missing_copied_and_corrupt_formats_are_rejected(self):
        original = json.loads(CATALOG.read_text())['strings']
        for mutate in [
            lambda row: row['localizations'].pop('ru'),
            lambda row: row['localizations'].__setitem__('ru', copy.deepcopy(row['localizations']['en'])),
            lambda row: row['localizations']['ru']['stringUnit'].__setitem__('value', 'Версия %d'),
        ]:
            row = copy.deepcopy(original['Version %@'])
            mutate(row)
            with self.assertRaises(AssertionError):
                validate({'Version %@': row})
        row = copy.deepcopy(original['%lld apps'])
        del row['localizations']['ru']['variations']['plural']['few']
        with self.assertRaises(AssertionError):
            validate({'%lld apps': row})
        key = 'lc.settings.moveDanglingFolderComplete %lld %lld'
        row = copy.deepcopy(original[key])
        row['localizations']['ru']['substitutions']['arg1']['argNum'] = 2
        with self.assertRaises(AssertionError):
            validate({key: row})

    def test_native_and_swift_host_language_agree(self):
        swift = (ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift').read_text()
        objc = (ROOT / 'LiveContainer/Localization.m').read_text()
        self.assertIn('russian = "ru"', swift)
        self.assertIn('case "ru": return .russian', swift)
        self.assertIn('case .russian: return "Русский"', swift)
        self.assertIn('var isRightToLeft: Bool { self == .hebrew }', swift)
        self.assertIn('if ([language isEqualToString:@"ru"]) return @"ru";', objc)
        picker = (ROOT / 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift').read_text()
        self.assertIn('static let shared = V3HostLanguageState(defaults: V3Localization.hostDefaults)', picker)
        self.assertIn('@ObservedObject private var languageState = V3HostLanguageState.shared', picker)
        self.assertIn('languageState.select(V3AppLanguage.resolve($0))', picker)
        self.assertIn('ForEach(V3AppLanguage.allCases)', picker)
        shell = (ROOT / 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
        self.assertIn('.environment(\\.layoutDirection, languageState.selected.isRightToLeft ? .rightToLeft : .leftToRight)', shell)

    def test_system_permission_localization_is_packaged(self):
        english = (ROOT / 'Resources/en.lproj/InfoPlist.strings').read_text()
        russian = (ROOT / 'Resources/ru.lproj/InfoPlist.strings').read_text()
        keys = lambda source: set(re.findall(r'^"([^"]+)"\s*=', source, re.M))
        self.assertEqual(keys(english), keys(russian))
        self.assertNotIn('The guest app is requesting', russian)
        project = (ROOT / 'LiveContainer.xcodeproj/project.pbxproj').read_text()
        self.assertIn('path = "Resources/ru.lproj/InfoPlist.strings"', project)
        self.assertIn('children = (A17ECAFE2DCA00000000F00D /* ru */,', project)

    @unittest.skipUnless(shutil.which('swiftc'), 'Swift compiler unavailable; native Russian renderer not run')
    def test_actual_runtime_persistence_ltr_and_russian_rendering(self):
        strings = json.loads(CATALOG.read_text())['strings']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / 'Russian.bundle'
            bundle.mkdir()
            (bundle/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'test.synthetic.russian', 'CFBundleDevelopmentRegion':'en'}))
            for locale in ['en', 'ru']:
                directory = bundle / (locale + '.lproj')
                directory.mkdir()
                values = {k:r['localizations'][locale]['stringUnit']['value'] for k,r in strings.items() if 'stringUnit' in r['localizations'][locale]}
                if locale == 'en':
                    values['RUSSIAN_TEST_ENGLISH_ONLY'] = 'English fixture fallback'
                (directory/'Localizable.strings').write_bytes(plistlib.dumps(values))
            main = root/'main.swift'
            main.write_text((ROOT/'tests/fixtures/russian_localization.swift').read_text())
            binary = root/'test'
            result = subprocess.run([shutil.which('swiftc'), str(ROOT/'LiveContainerSwiftUI/Utilities/V3Localization.swift'), str(main), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary), str(bundle)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('RUSSIAN_RUNTIME_PASS', result.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
