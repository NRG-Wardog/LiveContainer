"""Compile actual live-language source for the app's iOS15 minimum, not just iOS16 UI fixtures."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / 'LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift'
LOCALIZATION = ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift'
GUEST_TYPES = {'AppSceneViewController':'UIViewController',
               'DecoratedAppSceneViewController':'UIViewController',
               'VirtualWindowsHostView':'UIView'}

class LiveLanguageAvailabilityTests(unittest.TestCase):
    def test_availability_doubles_match_production_headers(self):
        for name in GUEST_TYPES:
            header = (ROOT / 'MultitaskSupport' / (name + '.h')).read_text()
            self.assertRegex(header, r'API_AVAILABLE\(ios\(16\.0\)\)\s*@interface\s+' + name + r'\b')
        source = SETTINGS.read_text()
        self.assertEqual(source.count('if #available(iOS 16.0, *) {'), 2)
        self.assertNotIn('@available(iOS 16', source)
        self.assertIn('updateChrome(host.view)', source)

    def test_actual_source_typechecks_at_ios15_and_unguarded_mutation_fails(self):
        if platform.system() != 'Darwin' or shutil.which('xcrun') is None:
            if os.environ.get('REQUIRE_IOS_AVAILABILITY_TESTS') == '1':
                self.fail('Mandatory Apple SDK iOS15 compile unavailable')
            self.skipTest('Apple SDK unavailable; iOS15 native availability not checked')
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'], text=True).strip()
        architecture = platform.machine()
        self.assertIn(architecture, ['arm64', 'x86_64'])
        with tempfile.TemporaryDirectory(prefix='live-language-ios15-') as temporary:
            directory = Path(temporary).resolve()
            doubles = directory / 'GuestAvailability.swift'
            doubles.write_text('import UIKit\n' + ''.join(
                '@available(iOS 16.0, *)\nclass ' + name + ': ' + parent + ' {}\n'
                for name, parent in GUEST_TYPES.items()))
            def compile_settings(settings):
                return subprocess.run(['xcrun', '--sdk', 'iphonesimulator', 'swiftc',
                    '-swift-version', '5', '-typecheck', '-parse-as-library', '-sdk', sdk,
                    '-target', architecture + '-apple-ios15.0-simulator',
                    str(LOCALIZATION), str(settings), str(doubles)],
                    capture_output=True, text=True, timeout=180)
            actual = compile_settings(SETTINGS)
            self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
            mutant = directory / 'UnguardedLanguageSettings.swift'
            original = SETTINGS.read_text()
            changed = original.replace('if #available(iOS 16.0, *) {', 'if true {')
            self.assertNotEqual(original, changed)
            mutant.write_text(changed)
            rejected = compile_settings(mutant)
            self.assertNotEqual(rejected.returncode, 0, 'Unguarded iOS16 guest types escaped iOS15 compile')
            self.assertRegex(rejected.stderr, r'only available in iOS 16(?:\.0)? or newer')
            self.assertTrue(any(name in rejected.stderr for name in GUEST_TYPES), rejected.stderr)

if __name__ == '__main__': unittest.main(verbosity=2)
