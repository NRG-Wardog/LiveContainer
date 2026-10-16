#!/usr/bin/env python3
"""Canonical native suites: exact sealed IDs once; no skips or tolerated failures."""
import json
from pathlib import Path
import sys
import unittest
root=Path(sys.argv[1]);expected=json.loads(Path(sys.argv[2]).read_text());modules=sys.argv[3:]
if not isinstance(expected,list) or not expected or len(expected)!=len(set(expected)):
    raise SystemExit('nonempty unique expected test IDs required')
sys.path.insert(0,str(root))
suite=unittest.TestLoader().loadTestsFromNames(modules)
def flatten(items):
    for item in items:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item
ids=[test.id() for test in flatten(suite)]
if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise SystemExit('discovered tests differ from sealed expected IDs')
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'test_ids':ids}))
if not result.wasSuccessful() or result.skipped or result.expectedFailures or result.unexpectedSuccesses or result.testsRun!=len(ids):raise SystemExit(1)
