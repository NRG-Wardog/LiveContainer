#!/usr/bin/env python3
"""Canonical native suites: exact sealed IDs once; no skips or tolerated failures."""
import json
import os
from pathlib import Path
from observe_subprocess import install
install(Path(os.environ["P0LOGIN_NESTED_COMMANDS"]))
import sys
import unittest
root=Path(sys.argv[1]);expected=json.loads(Path(sys.argv[2]).read_text());modules=sys.argv[3:]
if not isinstance(expected,list) or not expected or len(expected)!=len(set(expected)):
    raise SystemExit('nonempty unique expected test IDs required')
sys.path.insert(0,str(root))
suite=unittest.TestLoader().loadTestsFromNames(modules)
source_roots={}
for name in modules:
    module=sys.modules.get(name)
    if module is None or Path(module.__file__).resolve()!=(root/(name+'.py')).resolve():
        raise SystemExit('test module source is not the exact selected owner suite')
    if os.environ.get('P0LOGIN_EXPECTED_OWNER_ROOT'):
        source_roots[name]={}
        for attribute,selector in (('ROOT','OWNER'),('PEER','PEER'),('PRODUCER','PRODUCER')):
            expected_root=Path(os.environ['P0LOGIN_EXPECTED_'+selector+'_ROOT']).resolve()
            actual_root=getattr(module,attribute,None)
            if actual_root is None or Path(actual_root).resolve()!=expected_root:
                raise SystemExit('test '+attribute+' aliases or differs from independently selected source')
            source_roots[name][attribute]=str(expected_root)
        if source_roots[name]['ROOT']==source_roots[name]['PEER']:
            raise SystemExit('owner and peer must be independent source checkouts')
def flatten(items):
    for item in items:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item
ids=[test.id() for test in flatten(suite)]
if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise SystemExit('discovered tests differ from sealed expected IDs')
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses),'test_ids':ids,'source_roots':source_roots}))
if not result.wasSuccessful() or result.skipped or result.expectedFailures or result.unexpectedSuccesses or result.testsRun!=len(ids):raise SystemExit(1)
