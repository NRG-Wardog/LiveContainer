"""Live-session presentation regression; native renderer test requires swiftc.
The Foundation fixture does not claim UIKit/SwiftUI rendering validation.
"""
import json
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / 'LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
VIEWS = ('V3SourcesView', 'V3CatalogView', 'V3DeveloperServicesView', 'V3AnisetteView')


def view_source(source, name):
    # Views are top-level declarations, while nested functions are indented.
    start = source.index('struct ' + name + ': View {')
    following = re.search(r'^}', source[start:], re.M)
    assert following
    return source[start:start + following.end()]


def check_live_wiring(source):
    for name in VIEWS:
        view = view_source(source, name)
        assert '@Environment(\\.locale) private var displayLocale' in view, name
        calls = [line for line in view.splitlines() if 'V3Localization.' in line]
        assert calls, name
        for line in calls:
            assert 'language: .resolve(displayLocale.identifier)' in line, (name, line)
        # Language changes invalidate presentation, never the data-loading task.
        assert '.id(displayLocale' not in view, name
        assert '.onChange(of: displayLocale' not in view, name


# Recognize each actual call independently: an inner date(language:) does not
# supply a locale to the outer format call. These reviewed calls use ordinary
# Swift strings; quoted parentheses are not call nesting.
def localization_calls(source):
    for match in re.finditer(r'V3Localization\.(?:string|text|prose|format|date|legacyDate|weekdayName)\(', source):
        index = match.end()
        depth, quoted, escaped = 1, False, False
        top = []
        while depth:
            char = source[index]
            if escaped:
                escaped = False
            elif quoted and char == "\\":
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                if char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                elif depth == 1:
                    top.append(char)
            index += 1
        yield source[match.start():index], ''.join(top)


def check_all_view_calls(source):
    count = 0
    for match in re.finditer(r'^(?:private )?struct (\w+)[^\n]*: View[^\n]*\{', source, re.M):
        name = match.group(1)
        # Current shell declarations are ordinary top-level structs.
        start = match.start()
        close = re.search(r'^}', source[start:], re.M)
        assert close
        view = source[start:start + close.end()]
        for call, arguments in localization_calls(view):
            assert re.search(r'language:\s*(?:V3AppLanguage)?\.resolve\((?:dateLocale|displayLocale)\.identifier\)', call), (name, call)
            assert 'language:' in arguments, (name, 'only nested locale argument', call)
            assert '@Environment(\\.locale)' in view, name
            count += 1
    assert count >= 35, count


class LiveLanguageStateTests(unittest.TestCase):
    def test_eager_presentation_observes_live_locale(self):
        check_live_wiring(SHELL.read_text())

    def test_removed_locale_dependency_and_implicit_lookup_are_rejected(self):
        source = SHELL.read_text()
        for old, new in [
            ('@Environment(\\.locale) private var displayLocale', 'private var displayLocale = Locale(identifier: "he")'),
            ('V3Localization.text("Sources (\\(status.sources.count))", language: .resolve(displayLocale.identifier))', 'V3Localization.text("Sources (\\(status.sources.count))")'),
        ]:
            target = view_source(source, 'V3SourcesView')
            self.assertIn(old, target)
            with self.assertRaises(AssertionError):
                check_live_wiring(source.replace(target, target.replace(old, new, 1), 1))

    def test_every_eager_view_call_has_its_own_observed_locale(self):
        check_all_view_calls(SHELL.read_text())

    def test_nested_date_locale_cannot_mask_missing_outer_locale(self):
        source = SHELL.read_text()
        old = 'V3Localization.format("Updated %@", V3Localization.date(updatedAt, date: .omitted, time: .standard, language: V3AppLanguage.resolve(dateLocale.identifier)), language: .resolve(dateLocale.identifier))'
        new = 'V3Localization.format("Updated %@", V3Localization.date(updatedAt, date: .omitted, time: .standard, language: V3AppLanguage.resolve(dateLocale.identifier)))'
        self.assertIn(old, source)
        with self.assertRaises(AssertionError):
            check_all_view_calls(source.replace(old, new, 1))

    @unittest.skipUnless(shutil.which('swiftc'), 'Swift compiler unavailable; same-session renderer not executed')
    def test_same_message_and_semantic_values_across_live_transitions(self):
        catalog = json.loads((ROOT / 'Resources/Localizable.xcstrings').read_text())['strings']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            bundle = root / 'LiveSwitch.bundle'
            bundle.mkdir()
            (bundle / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'test.synthetic.live-switch', 'CFBundleDevelopmentRegion': 'en'}))
            for language in ['en', 'he', 'ru', 'zh-Hans', 'zh-Hant']:
                directory = bundle / (language + '.lproj')
                directory.mkdir()
                values = {key: row['localizations'][language]['stringUnit']['value']
                          for key, row in catalog.items()
                          if 'stringUnit' in row['localizations'][language]}
                (directory / 'Localizable.strings').write_bytes(plistlib.dumps(values))
            main = root / 'main.swift'
            main.write_text((ROOT / 'tests/fixtures/live_language_state.swift').read_text())
            binary = root / 'test'
            compiled = subprocess.run([shutil.which('swiftc'), str(ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift'), str(main), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(binary), str(bundle)], capture_output=True, text=True, timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertIn('LIVE_LANGUAGE_STATE_PASS', executed.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
