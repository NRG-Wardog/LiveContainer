#!/usr/bin/env python3
"""Run applicable maintained SideStore tests; retain exact superseded assertions."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import unittest

from prove_graph import git, require


# These four are still executed unchanged on the exact accepted historical tree.
# Their candidate requirements are checked by the named strict diagnostic gates.
SUPERSEDED = {
    "SourceContracts.test_whole_owner_tree_exact_hashes_modes_and_inventory":
        "diagnostic SideStore dependency basis and source-proof-before/after-build",
    "SourceContracts.test_exact_ancestry_gitlinks_clean_tree_and_tracked_inventory":
        "diagnostic owner-proof plus actual source/child Git identities before and after native work",
    "SourceContracts.test_app_delegate_review_slices_preserve_every_final_byte":
        "immutable diagnostic contracts/delta and focused-native-verification.json for the changed observer",
    "SourceContracts.test_pinned_package_resolution_and_valid_plist":
        "diagnostic owner lock proof and real Xcode resolver proof preserving nine unrelated pins; plist checked here",
}


def select_suite(module, historical=False):
    complete = unittest.defaultTestLoader.loadTestsFromModule(module)
    tests = [test for group in complete for test in group]
    require(len(tests) == 46, "Unexpected frozen SideStore test inventory")
    superseded = {test.id().split(".", 1)[1] for test in tests} & set(SUPERSEDED)
    require(superseded == set(SUPERSEDED), "Superseded historical assertion inventory changed")
    selected = [test for test in tests if (test.id().split(".", 1)[1] in SUPERSEDED) == historical]
    require(len(selected) == (4 if historical else 42), "Unexpected selected SideStore test inventory")
    return unittest.TestSuite(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=("candidate", "historical"))
    parser.add_argument("root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    report = args.report.resolve()
    os.chdir(root)
    spec = importlib.util.spec_from_file_location("diagnostic_runtime_tests", root / "tests/runtime_source/test_runtime_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    historical = args.scope == "historical"
    expected = 4 if historical else 42
    suite = select_suite(module, historical)
    # Preserve the valid Info.plist assertion from the replaced old-pin test.
    if not historical:
        module.plistlib.loads((root / "AltStore/Info.plist").read_bytes())
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = (result.wasSuccessful() and result.testsRun == expected and not result.skipped and
              not result.expectedFailures and not result.unexpectedSuccesses)
    report.write_text(json.dumps({"owner": "SideStore",
        "scope": "historical_baseline_only" if historical else "applicable_current_diagnostic_source_tests",
        "tested_commit": git(root, "rev-parse", "HEAD"), "tested_tree": git(root, "rev-parse", "HEAD^{tree}"),
        "expected": expected, "executed": result.testsRun, "superseded_candidate_assertions": SUPERSEDED,
        "candidate_coverage": not historical,
        "skipped": [(str(test), why) for test, why in result.skipped],
        "failures": len(result.failures), "errors": len(result.errors),
        "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
        "status": "PASS" if passed else "FAIL"}, indent=2) + "\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
