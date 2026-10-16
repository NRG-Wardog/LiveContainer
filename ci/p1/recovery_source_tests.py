#!/usr/bin/env python3
"""Portable extraction checks; these are never reported as native UI evidence.

Run: python -B ci/p1/recovery_source_tests.py /path/to/V3UnifiedShell.swift
"""
from pathlib import Path
import hashlib
import re
import sys
import unittest
from unittest.mock import patch

import recovery_source as fixture


class RecoverySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(sys.argv[1]).read_text()
        cls.fragments = fixture.recovery_fragments(cls.source)
        cls.generated = fixture.generate_recovery_source(cls.source)
        cls.template = Path(fixture.__file__).with_name('recovery_app.swift').read_text()
        cls.ui = Path(fixture.__file__).with_name('recovery_ui_tests.swift').read_text()

    def test_frozen_full_source(self):
        self.assertEqual(hashlib.sha256(self.source.encode()).hexdigest(), fixture.SOURCE_SHA256)

    def test_every_production_fragment_is_inserted_verbatim(self):
        self.assertEqual(len(self.fragments), 5)
        for name, value in self.fragments.items():
            with self.subTest(fragment=name):
                self.assertIn(value, self.source)
                self.assertIn(value.rstrip('\n'), self.generated)

    def test_modifier_is_whole_uninstrumented_inset(self):
        modifier = self.fragments['recovery-modifier']
        self.assertTrue(modifier.startswith(fixture.MODIFIER_START))
        self.assertTrue(modifier.endswith('        }\n'))
        self.assertEqual(modifier.count('status.unresolvedOperationRecovery'), 1)
        self.assertEqual(modifier.count('status.unresolvedDirectRecovery'), 1)
        self.assertEqual(modifier.count('status.unresolvedRefreshRecoveryRunID'), 1)
        self.assertEqual(modifier.count('status.unresolvedRecoveryJournalUnreadable'), 1)
        self.assertNotIn('p1-', modifier)
        self.assertNotIn('GeometryReader', modifier)

    def test_source_drift_fails_closed(self):
        for altered in (self.source + '\n', self.source.replace(
                '.safeAreaInset(edge: .top, spacing: 0)', '.overlay(alignment: .top)', 1)):
            with self.assertRaisesRegex(ValueError, 'exact frozen P1'):
                fixture.generate_recovery_source(altered)

    def test_no_markers_main_or_fixed_width_in_generated_fixture(self):
        self.assertNotIn('__P1_RECOVERY_', self.generated)
        self.assertNotIn('@main', self.generated)
        self.assertNotIn('.frame(width:', self.generated)
        self.assertIn('struct P1RecoveryScreen: View', self.generated)

    def test_missing_or_duplicate_template_marker_fails_closed(self):
        marker = '__P1_RECOVERY_MODIFIER__'
        for bad in (self.template.replace(marker, ''), self.template + '\n' + marker):
            with patch.object(Path, 'read_text', return_value=bad):
                with self.assertRaisesRegex(ValueError, 'template marker'):
                    fixture.generate_recovery_source(self.source)

    def test_recovery_modifier_wraps_tabview_not_navigationview(self):
        screen = fixture._declaration(self.template, '@MainActor struct P1RecoveryScreen')
        # This intentionally locks the synthetic container boundary. Production
        # uses TabView -> navigation children; the old direct-NavigationView host
        # is a different safe-area propagation path and must not return silently.
        self.assertIn('TabView(selection: $sharedModel.selectedTab)', self.source)
        tabs = re.search(r'        TabView\(selection: \$selectedTab\) \{\n(.*?)\n'
                         r'        }\n__P1_RECOVERY_MODIFIER__\n    }\n}', screen, re.S)
        self.assertIsNotNone(tabs)
        self.assertNotRegex(screen, re.compile(r'^\s*NavigationView\s*\{', re.M), msg=screen)
        self.assertEqual(re.findall(r'\.tag\((\d)\)', tabs.group(1)), ['0', '1', '2', '3'])
        self.assertEqual(re.findall(r'Label\("([^"]+)"', tabs.group(1)),
                         ['Home', 'Apps', 'Sources', 'Settings'])
        self.assertIn('P1RecoveryNavigationRoot()', tabs.group(1))
        self.assertEqual(tabs.group(1).count('P1RecoveryPlaceholderTab('), 3)
        for declaration in ('P1RecoveryNavigationRoot', 'P1RecoveryPlaceholderTab'):
            child = fixture._declaration(self.template, '@MainActor private struct ' + declaration)
            self.assertIn('NavigationView {', child)
            self.assertIn('.navigationViewStyle(StackNavigationViewStyle())', child)
            self.assertNotIn('__P1_RECOVERY_MODIFIER__', child)
        # No fixed sizes, ignored safe areas, or Dynamic Type caps may paper over
        # native occlusion. The production inset bytes are already checked above.
        for workaround in ('.frame(height:', '.frame(width:', '.ignoresSafeArea',
                           '.edgesIgnoringSafeArea', '.dynamicTypeSize', '.minimumScaleFactor'):
            self.assertNotIn(workaround, self.template)

    def test_no_banner_control_uses_same_container_and_unmodified_inset(self):
        self.assertIn('["none", "operation", "direct", "refresh", "unreadable"].contains(kind)', self.template)
        status = fixture._declaration(self.template, '@MainActor private final class P1RecoveryStatus')
        for kind in ('operation', 'direct', 'refresh', 'unreadable'):
            self.assertIn('kind == "' + kind + '"', status)
        self.assertNotIn('kind == "none"', status)
        self.assertEqual(self.template.count('__P1_RECOVERY_MODIFIER__'), 1)
        self.assertIn('["--recovery", "--recovery-kind", "none"]', self.ui)
        self.assertIn('"recoveryBannerAbsent": bannerAbsent', self.ui)
        self.assertIn('!app.staticTexts[$0].exists && !app.buttons[$0].exists', self.ui)
        self.assertIn('"noBannerControl": noBannerControl', self.ui)
        self.assertIn('"recovery-no-banner-control"', self.ui)

    def test_native_assertions_and_case_identity_remain_strict(self):
        self.assertEqual(re.findall(r'@objc func (test\w+)\(', self.ui),
                         ['testP1RecoveryNavigationDefault', 'testP1RecoveryNavigationLargest'])
        for kind in ('operation', 'direct', 'refresh', 'unreadable'):
            self.assertIn('("' + kind + '",', self.ui)
        for call in ('p1CheckRecoveryNavigation(largest: false)', 'p1CheckRecoveryNavigation(largest: true)',
                     'XCTAssertLessThanOrEqual(envelope.maxY, bar.frame.minY + 1,',
                     'XCTAssertLessThanOrEqual(bar.frame.maxY, content.frame.minY + 1,',
                     'XCTAssertTrue(p1RecoveryContains(envelope, in: viewport)',
                     'XCTAssertTrue(p1RecoveryContains(navigation.frame, in: viewport)',
                     'XCTAssertTrue(navigation.isHittable',
                     'guard back.exists && back.isHittable else',
                     '"navigationOpenedDestination": true, "navigationBackRestoredRoot": true'):
            self.assertIn(call, self.ui)
        self.assertEqual(self.ui.count('navigation.tap()'), 2)
        self.assertEqual(self.ui.count('back.tap()'), 2)
        self.assertNotIn('XCTSkip', self.ui)
        self.assertNotIn('continueAfterFailure = true', self.ui)

    def test_failure_evidence_precedes_acceptance_guards(self):
        branch = self.ui[self.ui.index('for (kind, title, controls) in scenarios {'):]
        self.assertLess(branch.index('p1RecoveryCapture('), branch.index('guard headingReady else'))
        self.assertLess(branch.index('p1RecoveryCapture('), branch.index('guard navigationReady else'))
        self.assertIn('"schema": "p1-recovery-observation-v1"', self.ui)
        self.assertIn('"scope": "pre-assertion native observations; not a passing case report"', self.ui)
        self.assertIn('screenshot.lifetime = .keepAlways', self.ui)
        self.assertIn('attachment.lifetime = .keepAlways', self.ui)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    # Retain source path for setUpClass while avoiding unittest argument parsing.
    unittest.main(argv=[sys.argv[0]], verbosity=2)
