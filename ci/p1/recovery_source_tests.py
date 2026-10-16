#!/usr/bin/env python3
"""Portable extraction checks; these are never reported as native UI evidence.

Run: python -B ci/p1/recovery_source_tests.py /path/to/V3UnifiedShell.swift
"""
from pathlib import Path
import hashlib
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
        template = Path(fixture.__file__).with_name('recovery_app.swift').read_text()
        marker = '__P1_RECOVERY_MODIFIER__'
        for bad in (template.replace(marker, ''), template + '\n' + marker):
            with patch.object(Path, 'read_text', return_value=bad):
                with self.assertRaisesRegex(ValueError, 'template marker'):
                    fixture.generate_recovery_source(self.source)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    # Retain source path for setUpClass while avoiding unittest argument parsing.
    unittest.main(argv=[sys.argv[0]], verbosity=2)
