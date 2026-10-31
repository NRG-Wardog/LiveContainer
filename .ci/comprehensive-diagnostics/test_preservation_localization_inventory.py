"""Exact preservation copy successor, including negative source/locale controls."""
from pathlib import Path
import importlib.util
import json
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('setup_inventory', HERE / 'generate_setup_localization_fixture.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

class PreservationLocalizationInventory(unittest.TestCase):
    def test_reviewed_formatter_transition(self):
        source = g.read_sources(ROOT)
        self.assertEqual(g.local_refresh_keys(source), g.CURRENT_LOCAL_REFRESH_KEYS)
        self.assertEqual(len(g.BASELINE_LOCAL_REFRESH_KEYS), 34)
        self.assertEqual(len(g.CURRENT_LOCAL_REFRESH_KEYS), 44)
        self.assertEqual(len(g.PRESERVATION_LOCALIZATION_KEYS), 13)
        self.assertEqual(g.CURRENT_LOCAL_REFRESH_KEYS - g.BASELINE_LOCAL_REFRESH_KEYS,
                         g.PRESERVATION_DIAGNOSTIC_KEYS | set(g.LOCAL_REFRESH_REPLACEMENTS.values()))
        self.assertEqual(g.BASELINE_LOCAL_REFRESH_KEYS - g.CURRENT_LOCAL_REFRESH_KEYS,
                         set(g.LOCAL_REFRESH_REPLACEMENTS))

    def test_arbitrary_or_missing_copy_is_rejected(self):
        source = g.read_sources(ROOT)
        for key in g.CURRENT_LOCAL_REFRESH_KEYS:
            changed = dict(source)
            changed['identity_diagnostics'] = source['identity_diagnostics'].replace(key, 'Unexpected diagnostic copy', 1)
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError, 'Exact finite'):
                g.local_refresh_keys(changed)

    def test_new_copy_owned_by_actual_producers(self):
        source = g.read_sources(ROOT)
        outcomes = g.block(source['identity_diagnostics'], 'public enum V3RefreshRenewalOutcome:')
        for key in g.PRESERVATION_OUTCOME_KEYS:
            self.assertIn('return "' + key + '"', outcomes)
        messages = g.block(source['identity_diagnostics'], 'private var localRefreshMessage:')
        for key in g.PRESERVATION_DIAGNOSTIC_KEYS | set(g.LOCAL_REFRESH_REPLACEMENTS.values()):
            self.assertIn('return "' + key + '"', messages)

    def test_all_new_locales_and_historical_copy_retained(self):
        catalog = json.loads(g.read_sources(ROOT)['catalog'])['strings']
        self.assertFalse(g.catalog_missing(g.PRESERVATION_LOCALIZATION_KEYS | set(g.LOCAL_REFRESH_REPLACEMENTS), catalog))
        for key in g.PRESERVATION_LOCALIZATION_KEYS:
            for language in g.LANGUAGES:
                changed = json.loads(json.dumps(catalog))
                del changed[key]['localizations'][language]
                with self.subTest(key=key, language=language):
                    self.assertIn({'key': key, 'language': language}, g.catalog_missing(g.PRESERVATION_LOCALIZATION_KEYS, changed))

if __name__ == '__main__':
    unittest.main()
