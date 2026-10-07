#!/usr/bin/env python3
"""Standard-library regression tests for aggregate failure and interruption gates."""
import contextlib
import copy
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_pristine_gate as gate

ROOT = Path(__file__).resolve().parents[2]


class Harness:
    def __init__(self, root):
        self.root = root
        self.evidence = root / "evidence"
        self.calls, self.checked = [], []
        self.codes, self.results, self.verify_errors = {}, {}, {}
        self.missing, self.raise_for = set(), {}
        self.document = {"owners": {owner: {"source_commit": "a" * 40, "source_tree": "b" * 40}
                                    for owner in gate.OWNERS}}

    def runner(self, command, log):
        owner = log.stem.removeprefix("pristine-")
        self.calls.append(owner)
        if owner in self.raise_for:
            raise self.raise_for[owner]
        code = self.codes.get(owner, 0)
        if owner in gate.EXPECTED:
            count = gate.EXPECTED[owner]
            result = {"owner": owner, "expected": count, "executed": count, "skipped": [],
                      "failures": int(code != 0), "errors": 0, "status": "PASS" if code == 0 else "FAIL"}
            result.update(self.results.get(owner, {}))
            if owner not in self.missing:
                (self.evidence / "provenance" / ("pristine-" + owner + "-tests.json")).write_text(json.dumps(result))
            log.write_text("Synthetic gate fixture; no native execution.\n")
        else:
            result = {"owner": owner, "status": "exact_frozen_source_pass", "product_files_verified": 5,
                      "behavior_changes": [], "fork_commit": "a" * 40}
            result.update(self.results.get(owner, {}))
            log.write_text(json.dumps(result))
        return code

    def verify(self, source, commit, tree):
        self.checked.append(source.name)
        if source.name in self.verify_errors:
            raise self.verify_errors[source.name]

    def run(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return gate.run_gate(self.root / "sources", self.evidence, self.document, "fixture-digest",
                                 runner=self.runner, verify=self.verify)


class AggregateGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pristine-gate-fixture-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.h = Harness(self.root)

    def test_all_required_suites_and_all_seven_integrity_checks_pass(self):
        code, report = self.h.run()
        self.assertEqual(code, 0)
        self.assertEqual(self.h.calls, list(gate.SUITES))
        self.assertEqual(self.h.checked, list(gate.OWNERS))
        self.assertTrue(report["assembly_allowed"])

    def test_multiple_failures_do_not_hide_a_pass_or_later_suites(self):
        self.h.codes.update(LiveContainer=1, SideStore=2)
        code, report = self.h.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.h.calls, list(gate.SUITES))
        self.assertEqual([row["returncode"] for row in report["suites"]], [1, 2, 0, 0, 0, 0, 0])
        self.assertTrue(report["suites"][2]["passed"])
        self.assertEqual(self.h.checked, list(gate.OWNERS))
        self.assertFalse(report["assembly_allowed"])

    def test_zero_and_partial_native_counts_fail_even_with_exit_zero(self):
        for count in (0, gate.EXPECTED["SideStore"] - 1):
            with self.subTest(count=count):
                h = Harness(self.root / str(count))
                h.results["SideStore"] = {"executed": count}
                self.assertEqual(h.run()[0], 1)
                self.assertEqual(h.calls, list(gate.SUITES))

    def test_missing_native_report_cannot_reuse_stale_pass(self):
        old = self.h.evidence / "provenance/pristine-SideStore-tests.json"
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps({"status": "PASS", "executed": 46}))
        self.h.missing.add("SideStore")
        code, report = self.h.run()
        self.assertEqual(code, 1)
        self.assertIsNone(report["suites"][1]["result"])
        self.assertIn("result_error", report["suites"][1])

    def test_skipped_or_failed_native_result_cannot_pass_exit_zero(self):
        for changed in ({"skipped": [["test", "unavailable"]]}, {"failures": 1}, {"errors": 1}):
            self.h.results["LiveContainer"] = changed
            self.assertEqual(self.h.run()[0], 1)

    def test_zero_partial_duplicate_or_missing_suite_results_fail(self):
        _, report = self.h.run()
        for replacement in ([], report["suites"][:-1], report["suites"][:-1] + [report["suites"][0]]):
            changed = copy.deepcopy(report)
            changed["suites"] = replacement
            self.assertNotEqual(gate.gate_exit(changed), 0)
        changed = copy.deepcopy(report)
        changed["suites"][0]["result"] = None
        self.assertNotEqual(gate.gate_exit(changed), 0)

    def test_missing_or_failed_integrity_results_block_assembly(self):
        _, report = self.h.run()
        for replacement in ([], report["integrity"][:-1]):
            changed = copy.deepcopy(report)
            changed["integrity"] = replacement
            self.assertNotEqual(gate.gate_exit(changed), 0)
        self.h.verify_errors["AnisetteKit"] = ValueError("source mutation")
        code, report = self.h.run()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.h.checked), 14)
        self.assertEqual(next(r for r in report["integrity"] if r["owner"] == "AnisetteKit")["status"], "FAIL")

    def test_source_checks_run_after_a_failed_suite_and_check_every_owner(self):
        self.h.codes["SideStore"] = 1
        self.h.verify_errors["LiveContainer"] = ValueError("drift")
        code, report = self.h.run()
        self.assertEqual(code, 1)
        self.assertEqual(self.h.checked, list(gate.OWNERS))
        self.assertFalse(report["assembly_allowed"])

    def test_child_interrupt_exit_and_signal_statuses_never_allow_assembly(self):
        for raw, expected in ((130, 130), (143, 143), (-signal.SIGINT, 130), (-signal.SIGTERM, 143)):
            with self.subTest(raw=raw):
                h = Harness(self.root / str(raw))
                h.codes["LiveContainer"] = raw
                code, report = h.run()
                self.assertEqual(code, expected)
                self.assertEqual(report["suites"][0]["returncode"], raw)
                self.assertEqual(h.calls, ["LiveContainer"])
                self.assertTrue(all(r["state"] == "NOT_RUN" for r in report["suites"][1:]))
                self.assertEqual(h.checked, list(gate.OWNERS))
                self.assertFalse(report["assembly_allowed"])

    def test_parent_keyboard_interrupt_and_sigterm_are_failed_outcomes(self):
        for error, expected in ((KeyboardInterrupt(), 130), (gate.Interrupted(signal.SIGTERM), 143)):
            h = Harness(self.root / str(expected))
            h.raise_for["LiveContainer"] = error
            code, report = h.run()
            self.assertEqual(code, expected)
            self.assertEqual(h.checked, list(gate.OWNERS))
            self.assertFalse(report["assembly_allowed"])

    def test_interrupted_integrity_is_incomplete_and_blocks_assembly(self):
        self.h.verify_errors["LiveContainer"] = gate.Interrupted(signal.SIGTERM)
        code, report = self.h.run()
        self.assertEqual(code, 143)
        self.assertEqual(self.h.calls, list(gate.SUITES))
        self.assertTrue(any(r["status"] == "NOT_RUN" for r in report["integrity"]))
        self.assertFalse(report["assembly_allowed"])

    def test_runner_error_is_recorded_and_remaining_suites_still_run(self):
        self.h.raise_for["SideStore"] = OSError("fixture launch failure")
        code, report = self.h.run()
        self.assertEqual(code, 1)
        self.assertEqual(report["suites"][1]["state"], "FAILED_TO_RUN")
        self.assertEqual(self.h.calls, list(gate.SUITES))

    def test_parity_result_needs_count_identity_and_success(self):
        for changed in ({"product_files_verified": 0}, {"owner": "wrong"}, {"fork_commit": "b" * 40}):
            self.h.results["jktcp"] = changed
            self.assertEqual(self.h.run()[0], 1)

    def test_real_process_exit_codes_are_preserved(self):
        for expected in (0, 1, 130, 143):
            actual = gate.run_command([sys.executable, "-c", f"raise SystemExit({expected})"], self.root / f"exit-{expected}.log")
            self.assertEqual(actual, expected)

    def test_real_process_timeout_is_bounded_and_nonzero(self):
        with patch.object(gate, "SUITE_TIMEOUT_SECONDS", 0.05):
            actual = gate.run_command([sys.executable, "-c", "import time; time.sleep(30)"], self.root / "timeout.log")
        self.assertEqual(actual, 124)

    def test_shell_pipefail_prevents_assembly_after_failure_or_interruption(self):
        for code in (1, 130, 143):
            folder = self.root / ("shell-" + str(code))
            marker = self.root / ("assembly-started-" + str(code))
            result = subprocess.run(["bash", "-c", 'set -euo pipefail; "$1" -B "$2" --fixture-gate "$3" "$4" | tee "$5"; touch "$6"',
                "gate-shell-test", sys.executable, str(Path(__file__).resolve()), str(code), str(folder),
                str(self.root / ("shell-" + str(code) + ".log")), str(marker)], capture_output=True, text=True)
            self.assertEqual(result.returncode, code)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture-gate":
        h = Harness(Path(sys.argv[3]))
        h.codes["LiveContainer"] = int(sys.argv[2])
        raise SystemExit(h.run()[0])
    unittest.main(verbosity=2)
