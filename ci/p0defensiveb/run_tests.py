#!/usr/bin/env python3
"""Exact portable adapter lane. This never invokes the 38 genuine consumers."""
import argparse, hashlib, importlib.util, json, sys, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
EXPECTED={'test_cargo_contract.py':15,'test_consumer_contract.py':19,'test_descendant_contract.py':8,
    'test_macho_contract.py':10,'test_native_tool_identity.py':10,'test_openssl_artifact_contract.py':23,
    'test_plist_generated_output.py':19,'test_preparation.py':25,'test_product_capture_integration.py':7,
    'test_product_signature_boundary.py':39,'test_registry_diagnostics.py':8,'test_registry_readme_alias.py':12,
    'test_resource_contract.py':10,'test_execution_contract.py':19,'test_capture_retention.py':16,
    'test_gate_orchestration.py':5,'test_prior_phase_a.py':23,'test_retrieve_prior.py':21,
    'test_phase_a_host_replay.py':25,'test_phase_a_api_binding.py':17,'test_phase_a_filesystem_paths.py':6, 'test_diagnostic_binding.py':6, 'test_diagnostic_host_replay.py':45,
    'test_swift_split_binding.py':6, 'test_diagnostic_source_proof.py':10, 'test_integrity_source.py':46, 'test_integrity_runtime.py':25, 'test_activation_binding.py':12}


def require(value,message):
    if not value:raise ValueError(message)


def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from flatten(item)
        else:yield item


def run(output):
    require(not output.exists() and not output.is_symlink(),'fresh adapter test receipt required')
    require({p.name for p in (HERE/'tests').glob('test_*.py')}==set(EXPECTED),'exact finite adapter test files required')
    suite=unittest.TestSuite();ids=[];sources={}
    for name,count in EXPECTED.items():
        path=HERE/'tests'/name;raw=path.read_bytes();sources[name]=hashlib.sha256(raw).hexdigest()
        spec=importlib.util.spec_from_file_location(path.stem,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        selected=unittest.TestLoader().loadTestsFromModule(module);selected_ids=[test.id() for test in flatten(selected)]
        require(len(selected_ids)==count and len(set(selected_ids))==count,'finite test ID inventory differs: '+name)
        ids+=selected_ids;suite.addTests(selected)
    require(len(ids)==len(set(ids))==487,'exact487 adapter tests required')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    counts={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'expected_failures':len(result.expectedFailures),'unexpected_successes':len(result.unexpectedSuccesses)}
    success=result.wasSuccessful() and counts['tests']==487 and all(value==0 for key,value in counts.items() if key!='tests')
    report={'schema_version':1,'scope':'HOST_ONLY_ADAPTER_TESTS','status':'PASSED' if success else 'FAILED',**counts,
        'test_ids':ids,'sources_sha256':sources,'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'optimized':bool(sys.flags.optimize),'genuine_consumer_tests_executed':False,'native_capture_evidence':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:f.write(json.dumps(report,indent=2,sort_keys=True)+'\n')
    require(success,'finite adapter tests failed or skipped')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--result',type=Path,required=True);a=p.parse_args()
    try:run(a.result)
    except Exception as error:p.exit(2,'TESTS_FAILED: '+str(error)+'\n')
