"""Build-setting scope checks, not a native compiler or size-regression benchmark."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = (ROOT / 'LiveContainer.xcodeproj/project.pbxproj').read_text()


def object_block(identifier):
    match = re.search(r'^\t\t' + re.escape(identifier) + r' /\*[^\n]+\*/ = \{\n(.*?)^\t\t\};', PROJECT, re.M | re.S)
    if not match:
        raise AssertionError('Xcode object not found: ' + identifier)
    return match.group(1)


def configuration(target, name):
    match = re.search(r'^\t\t([0-9A-F]{24}) /\* Build configuration list for PBXNativeTarget "' + re.escape(target) + r'" \*/ = \{', PROJECT, re.M)
    if not match:
        raise AssertionError('Target configuration list not found: ' + target)
    config_list = object_block(match.group(1))
    config = re.search(r'([0-9A-F]{24}) /\* ' + re.escape(name) + r' \*/', config_list)
    if not config:
        raise AssertionError('Named target configuration not found')
    return object_block(config.group(1))


class ReleaseSizeConfigurationTests(unittest.TestCase):
    def test_only_swiftui_release_selects_size_optimization(self):
        release = configuration('LiveContainerSwiftUI', 'Release')
        self.assertIn('SWIFT_OPTIMIZATION_LEVEL = "-Osize";', release)
        self.assertNotIn('SWIFT_OPTIMIZATION_LEVEL', configuration('LiveContainerSwiftUI', 'Debug'))
        self.assertEqual(PROJECT.count('SWIFT_OPTIMIZATION_LEVEL = "-Osize";'), 1)
        self.assertNotIn('DEAD_CODE_STRIPPING', release)
        self.assertNotIn('STRIP_STYLE', release)
        self.assertNotIn('EXPORTED_SYMBOLS_FILE', release)

    def test_guest_dynamic_symbol_retention_is_preserved(self):
        for mode in ('Debug', 'Release'):
            with self.subTest(mode=mode):
                process = configuration('LiveProcess', mode)
                self.assertIn('DEAD_CODE_STRIPPING = NO;', process)
                self.assertIn('STRIP_STYLE = debugging;', process)
                shared = configuration('LiveContainerShared', mode)
                self.assertIn('STRIP_STYLE = debugging;', shared)

    def test_project_debug_and_release_diagnostics_are_preserved(self):
        # Project defaults continue to provide Debug -Onone and Release dSYM.
        self.assertIn('SWIFT_OPTIMIZATION_LEVEL = "-Onone";', object_block('17DCE9D42C7067ED00731D42'))
        self.assertIn('DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";', object_block('17DCE9D52C7067ED00731D42'))
        self.assertIn('COPY_PHASE_STRIP = NO;', object_block('17DCE9D52C7067ED00731D42'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
