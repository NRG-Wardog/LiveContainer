#!/usr/bin/env python3
"""Only six reviewed synthetic drivers. No wildcards or guest execution."""
import argparse, importlib.util, json, os, runpy, sys, tempfile, unittest
from pathlib import Path
from observe_host_subprocess import install
from source_primitives import require
DRIVERS=('test_memory_boundaries_host.py','test_vm_setup_host.py','test_elf_metadata_bounds.py','run_tests.py','run_diagnostic_checks.py','test_fault_aggregate_compatibility.py')
UNIT_METHODS=('test_fresh_provisioning_constructor_failure_is_correlated_and_redacted','test_actual_native_boundary_success_faults_and_concurrent_calls','test_normal_checked_staging_blocks_otp_and_preserves_previous_blob_on_every_io_failure','test_constructor_diagnostic_reaches_actual_json_boundary_and_preserves_poison','test_native_trace_is_bounded_and_can_be_disabled_without_changing_results','test_actual_loader_lifetime_and_read_only_callbacks','test_actual_consumer_hooks_observe_without_changing_results','test_actual_swift_consumer_decoder_rejects_private_or_malformed_values','test_swift_and_native_metadata_allowlists_are_identical')


AGGREGATE_DRIVER='test_fault_aggregate_compatibility.py'
AGGREGATE_METHODS=('test_warning_clean_legacy_and_explicit_aggregates',)

def unittest_contract(driver):
    require(driver in ('run_tests.py',AGGREGATE_DRIVER),'exact unittest driver required')
    return ('run_tests','MaintainedAnisetteNativeTests',UNIT_METHODS) if driver=='run_tests.py' else ('test_fault_aggregate_compatibility','FaultAggregateCompatibilityTests',AGGREGATE_METHODS)

def expected_test_ids(driver):
    name,klass,methods=unittest_contract(driver)
    return [name+'.'+klass+'.'+method for method in methods]

def verify_unittest_result(driver,row):
    expected=expected_test_ids(driver)
    require(set(row)=={'tests','failures','errors','skips','expected_failures','unexpected_successes','test_ids'},'exact unittest result schema required')
    require(type(row['tests']) is int and row['tests']==len(expected),'exact unittest count required')
    require(all(type(row[k]) is int and row[k]==0 for k in ('failures','errors','skips','expected_failures','unexpected_successes')),'all unittest cases must pass without skips')
    require(isinstance(row['test_ids'],list) and len(row['test_ids'])==len(expected) and set(row['test_ids'])==set(expected),'exact unittest IDs required')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('owner','output','temporary','evidence','unicorn-include'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--driver',choices=DRIVERS,required=True);a=p.parse_args()
    for name in ('output','temporary'):
        value=getattr(a,name);require(value.is_absolute() and not value.exists(),'fresh absolute '+name+' required');value.mkdir(parents=True)
    require(a.owner.is_absolute() and a.owner.is_dir() and not a.owner.is_symlink(),'ordinary owner required')
    script=(Path(__file__).resolve().parent/a.driver if a.driver=='run_diagnostic_checks.py' else a.owner/'.ci/native-tests'/a.driver);require(script.is_file() and not script.is_symlink(),'sealed exact host driver required')
    os.environ['TMPDIR']=str(a.temporary);tempfile.tempdir=str(a.temporary)
    store=install(a.evidence,a.temporary,a.output)
    if a.driver in ('run_tests.py',AGGREGATE_DRIVER):
        aggregate=a.driver==AGGREGATE_DRIVER
        if aggregate:
            from diagnostic_checks import source_closure
            before=source_closure(a.owner)
        name,klass,methods=unittest_contract(a.driver)
        spec=importlib.util.spec_from_file_location(name,script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        require(module.ROOT==a.owner,'host driver root changed')
        suite=unittest.TestLoader().loadTestsFromTestCase(getattr(module,klass))
        ids=[test.id() for test in suite];expected=expected_test_ids(a.driver)
        require(len(ids)==len(expected) and set(ids)==set(expected),'exact host unittest IDs required')
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        row=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),expected_failures=len(result.expectedFailures),unexpected_successes=len(result.unexpectedSuccesses),test_ids=ids)
        (a.output/'unittest-result.json').write_text(json.dumps(row,indent=2)+'\n')
        verify_unittest_result(a.driver,row)
        if aggregate:
            from aggregate_checks import verify_nested,verify_result
            require(before==source_closure(a.owner),'aggregate sources changed during execution')
            nested=verify_nested(a.evidence,a.owner,a.temporary,Path.cwd())
            (a.output/'aggregate-result.json').write_text(json.dumps(dict(schema=1,source_sha256=before,unittest=row,nested_commands=nested),indent=2)+'\n')
            verify_result(a.output,a.evidence,a.owner,a.temporary,Path.cwd())
    else:
        sys.argv=[str(script),'--output',str(a.output)]
        if a.driver=='run_diagnostic_checks.py':sys.argv+=['--owner',str(a.owner)]
        if a.driver=='test_elf_metadata_bounds.py':sys.argv+=['--disable-leak-sanitizer']
        else:sys.argv+=['--unicorn-include',str(a.unicorn_include)]
        runpy.run_path(str(script),run_name='__main__')
    (a.evidence/'final-output.json').write_text(json.dumps(store.retain_tree(a.output,label='final-output'),indent=2)+'\n')
    summary=store.summary();prior=json.loads((a.evidence/'retention-summary.json').read_text());summary['nested_commands']=prior['nested_commands']
    (a.evidence/'retention-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
if __name__=='__main__':main()
