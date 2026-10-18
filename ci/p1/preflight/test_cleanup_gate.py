import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import cleanup_gate


class CleanupGateTests(unittest.TestCase):
    def run_gate(self, suite, platform='darwin'):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        output = Path(temporary.name).resolve() / 'gate'
        with mock.patch.object(cleanup_gate.sys, 'platform', platform), mock.patch.object(unittest.defaultTestLoader, 'loadTestsFromNames', return_value=suite):
            passed = cleanup_gate.execute(output)
        return passed, json.loads((output / 'result.json').read_text()), output
    def test_zero_skip_success_has_only_cleanup_scope(self):
        class Good(unittest.TestCase):
            def runTest(self): self.assertTrue(True)
        passed, row, output = self.run_gate(unittest.TestSuite([Good()]))
        self.assertTrue(passed); self.assertEqual(row['tests'], 1)
        self.assertEqual(row['cases'][0]['outcome'], 'passed')
        for key in ['admissionEligible', 'production_ready', 'ui_executed', 'simulator_executed', 'host_built']: self.assertIs(row[key], False)
        self.assertTrue((output / 'tests.log').is_file())
    def test_skip_fails_and_is_retained(self):
        class Skip(unittest.TestCase):
            def runTest(self): self.skipTest('synthetic')
        passed, row, _ = self.run_gate(unittest.TestSuite([Skip()]))
        self.assertFalse(passed); self.assertEqual(row['skipped'], 1)
    def test_failure_is_retained(self):
        class Fail(unittest.TestCase):
            def runTest(self): self.fail('synthetic')
        passed, row, _ = self.run_gate(unittest.TestSuite([Fail()]))
        self.assertFalse(passed); self.assertEqual(row['cases'][0]['outcome'], 'failed')
    def test_non_macos_cannot_claim_native_result(self):
        passed, row, _ = self.run_gate(unittest.TestSuite(), 'linux')
        self.assertFalse(passed); self.assertEqual(row['error']['type'], 'ValueError')
    def test_empty_suite_fails(self):
        passed, row, _ = self.run_gate(unittest.TestSuite())
        self.assertFalse(passed); self.assertEqual(row['tests'], 0)
    def test_duplicate_test_ids_fail(self):
        class Good(unittest.TestCase):
            def runTest(self): pass
        passed, row, _ = self.run_gate(unittest.TestSuite([Good(), Good()]))
        self.assertFalse(passed); self.assertEqual(row['tests'], 2)
    def test_fresh_output_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'fresh'): cleanup_gate.execute(Path(temporary).resolve())


if __name__ == '__main__': unittest.main()
