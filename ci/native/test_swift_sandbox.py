#!/usr/bin/env python3
import copy
import errno
from pathlib import Path
import re
import unittest

import verify_network_sandbox as canary


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.control = {"child_executed": True, "operation": "connect", "connected": True, "errno": None}
        self.denied = {"child_executed": True, "operation": "connect", "connected": False, "errno": errno.EPERM}

    def test_only_explicit_permission_denial_with_positive_control_passes(self):
        for value in (errno.EPERM, errno.EACCES):
            canary.validate(self.control, {**self.denied, "errno": value})

    def test_refused_timeout_and_unknown_errors_do_not_prove_denial(self):
        for value in (errno.ECONNREFUSED, errno.ETIMEDOUT, None, 0):
            with self.subTest(errno=value), self.assertRaises(ValueError):
                canary.validate(self.control, {**self.denied, "errno": value})

    def test_missing_child_execution_wrong_operation_or_connected_child_fail(self):
        for changed in ({"child_executed": False}, {"operation": "socket"}, {"connected": True}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                canary.validate(self.control, {**self.denied, **changed})
        with self.assertRaises(ValueError): canary.validate(self.control, {})

    def test_failed_positive_control_never_passes(self):
        with self.assertRaises(ValueError): canary.validate(self.denied, self.denied)

    def test_both_filtered_test_commands_keep_outer_denial_and_disable_only_inner_sandbox(self):
        text = Path(__file__).with_name("run-native.sh").read_text()
        self.assertIn("/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)'", text)
        self.assertIn("export -f offline", text)
        self.assertIn('verify_network_sandbox.py" "$EVIDENCE/provenance/network-sandbox-proof.json"', text)
        commands = text.replace("\\\n", " ").splitlines()
        selected = [line for line in commands if "offline swift test " in line]
        self.assertEqual(len(selected), 2)
        for line in selected:
            self.assertIn("--disable-sandbox", line)
            self.assertIn("--skip-build", line)
            self.assertIn("--disable-automatic-resolution", line)
            self.assertIn("--filter", line)
        self.assertEqual(text.count("--disable-sandbox"), 2)
        self.assertLess(text.index("verify_network_sandbox.py"), text.index("PHASE=acquire-exact-owners"))
        self.assertIn("anisetteRequestHeadersCustomization|anisetteDataResponseStructure|anisetteHeadersDTORoundtrip", text)
        self.assertIn("deviceInitializationAndFiltering|certificateRequestCSRGeneration|developerPortalSingleton|archiveStoreRoundtrip|archiveDeflateRoundtrip", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
