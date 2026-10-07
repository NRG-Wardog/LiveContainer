#!/usr/bin/env python3
"""Run the existing frozen owner tests; skipped or absent tests cannot pass."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

EXPECTED = {"LiveContainer": 41, "SideStore": 46, "AnisetteKit": 5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", choices=EXPECTED)
    parser.add_argument("root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    report = args.report.resolve()
    os.chdir(root)
    if args.owner == "AnisetteKit":
        spec = importlib.util.spec_from_file_location("owner_native_tests", root / ".ci/native-tests/run_tests.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    else:
        path = root / ("tests" if args.owner == "LiveContainer" else "tests/runtime_source")
        sys.path.insert(0, str(path))
        suite = unittest.defaultTestLoader.discover(str(path))
    count = suite.countTestCases()
    if count != EXPECTED[args.owner]:
        raise ValueError(f"Unexpected frozen suite inventory: {count} != {EXPECTED[args.owner]}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and not result.skipped and result.testsRun == count
    report.write_text(json.dumps({"owner": args.owner, "expected": count,
        "executed": result.testsRun, "skipped": [(str(t), why) for t, why in result.skipped],
        "failures": len(result.failures), "errors": len(result.errors),
        "status": "PASS" if passed else "FAIL"}, indent=2) + "\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
