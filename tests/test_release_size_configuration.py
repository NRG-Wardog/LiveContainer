"""Build-setting scope checks, not a native compiler or size-regression benchmark."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = (ROOT / 'LiveContainer.xcodeproj/project.pbxproj').read_text()


def object_block(identifier, project=PROJECT):
    match = re.search(r'^\t\t' + re.escape(identifier) + r' /\*[^\n]+\*/ = \{\n(.*?)^\t\t\};', project, re.M | re.S)
    if not match:
        raise AssertionError('Xcode object not found: ' + identifier)
    return match.group(1)


def configuration(target, name, project=PROJECT):
    match = re.search(r'^\t\t([0-9A-F]{24}) /\* Build configuration list for PBXNativeTarget "' + re.escape(target) + r'" \*/ = \{', project, re.M)
    if not match:
        raise AssertionError('Target configuration list not found: ' + target)
    config_list = object_block(match.group(1), project)
    config = re.search(r'([0-9A-F]{24}) /\* ' + re.escape(name) + r' \*/', config_list)
    if not config:
        raise AssertionError('Named target configuration not found')
    return object_block(config.group(1), project)


EXPECTED_SIZE_TARGETS = {'LiveContainerSwiftUI', 'SideStoreSupport'}
SIZE_SETTING = 'SWIFT_OPTIMIZATION_LEVEL = "-Osize";'


def validate_size_scope(project=PROJECT):
    # Inspect actual target/configuration ownership, not merely a global count.
    lists = re.findall(r'^\t\t([0-9A-F]{24}) /\* Build configuration list for PBXNativeTarget "([^"\n]+)" \*/ = \{', project, re.M)
    actual = set()
    for identifier, target in lists:
        configs = re.findall(r'([0-9A-F]{24}) /\* ([^*\n]+) \*/', object_block(identifier, project))
        for config_id, mode in configs:
            block = object_block(config_id, project)
            if SIZE_SETTING in block:
                assert block.count(SIZE_SETTING) == 1, 'Duplicate size setting'
                assert (target, mode) not in actual, 'Duplicate target configuration'
                actual.add((target, mode))
    expected = {(target, 'Release') for target in EXPECTED_SIZE_TARGETS}
    assert actual == expected, 'Unexpected size-optimized target/configuration scope'
    # Reject settings hidden at project level or in unowned configuration objects.
    assert project.count(SIZE_SETTING) == len(actual), 'Unowned size optimization setting'
    return actual


def validate_release_coverage_scope(project=PROJECT):
    debug = object_block('17DCE9D42C7067ED00731D42', project)
    release = object_block('17DCE9D52C7067ED00731D42', project)
    assert 'ENABLE_CODE_COVERAGE = NO;' in release, 'Release compiler coverage enabled'
    assert 'CLANG_COVERAGE_MAPPING = NO;' in release, 'Release mapping coverage enabled'
    assert 'CLANG_COVERAGE_MAPPING' not in debug, 'Debug coverage changed'
    assert project.count('CLANG_COVERAGE_MAPPING') == 1, 'Unexpected mapping override scope'


class ReleaseSizeConfigurationTests(unittest.TestCase):
    def test_only_reviewed_release_targets_select_size_optimization(self):
        release = configuration('LiveContainerSwiftUI', 'Release')
        self.assertIn('SWIFT_OPTIMIZATION_LEVEL = "-Osize";', release)
        self.assertNotIn('SWIFT_OPTIMIZATION_LEVEL', configuration('LiveContainerSwiftUI', 'Debug'))
        self.assertEqual(validate_size_scope(), {(target, 'Release') for target in EXPECTED_SIZE_TARGETS})
        self.assertIn(SIZE_SETTING, configuration('SideStoreSupport', 'Release'))
        self.assertNotIn('SWIFT_OPTIMIZATION_LEVEL', configuration('SideStoreSupport', 'Debug'))
        self.assertNotIn('DEAD_CODE_STRIPPING', release)
        self.assertNotIn('STRIP_STYLE', release)
        self.assertNotIn('EXPORTED_SYMBOLS_FILE', release)

    def test_same_count_wrong_target_or_debug_cannot_replace_approved_release(self):
        release = configuration('SideStoreSupport', 'Release')
        without = PROJECT.replace(release, release.replace(SIZE_SETTING, ''))
        self.assertNotEqual(without, PROJECT)
        for target, mode in [('LiveProcess', 'Release'), ('SideStoreSupport', 'Debug')]:
            block = configuration(target, mode, without)
            mutated = without.replace(block, block.replace('buildSettings = {', 'buildSettings = {\n\t\t\t\t' + SIZE_SETTING, 1))
            self.assertEqual(mutated.count(SIZE_SETTING), 2)
            with self.subTest(target=target, mode=mode), self.assertRaisesRegex(AssertionError, 'scope'):
                validate_size_scope(mutated)

    def test_project_default_cannot_add_unowned_size_setting(self):
        block = object_block('17DCE9D52C7067ED00731D42')
        mutated = PROJECT.replace(block, block.replace('buildSettings = {', 'buildSettings = {\n\t\t\t\t' + SIZE_SETTING, 1))
        with self.assertRaisesRegex(AssertionError, 'Unowned'):
            validate_size_scope(mutated)

    def test_coverage_mapping_is_disabled_only_for_release(self):
        validate_release_coverage_scope()

    def test_mapping_yes_or_debug_override_is_rejected(self):
        with self.assertRaises(AssertionError):
            validate_release_coverage_scope(PROJECT.replace('CLANG_COVERAGE_MAPPING = NO;', 'CLANG_COVERAGE_MAPPING = YES;'))
        debug = object_block('17DCE9D42C7067ED00731D42')
        changed = PROJECT.replace(debug, debug.replace('buildSettings = {', 'buildSettings = {\nCLANG_COVERAGE_MAPPING = NO;', 1))
        with self.assertRaises(AssertionError):
            validate_release_coverage_scope(changed)

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
