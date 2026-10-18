#!/usr/bin/env python3
"""One same-runtime boot with minimal/full Python gate comparisons. No admission."""
import argparse
import os
from pathlib import Path
import re
import boot_diagnostic as boot
import capture
import process_scope
import probe_pair
import simulator_cleanup


def exact_xcode(raw):
    result=boot.tool_text(raw,'xcode')
    if raw.decode().strip()!='Xcode 26.4.1\nBuild version 17E202':raise ValueError('comparison Xcode drift')
    return result


def exact_runtime(raw):
    result=boot.exact_runtime(raw)
    if result['buildversion']!='23C54':raise ValueError('comparison runtime build drift')
    return result


def collect(host, inputs, approved, output):
    if output.exists(): raise ValueError('fresh diagnostic evidence directory required')
    output.mkdir(parents=True)
    logs=output/'commands';logs.mkdir()
    probes=output/'probes';probes.mkdir()
    scope=process_scope.Scope(output,stall_diagnostic=True)
    commands=boot.Commands(scope,logs)
    trivial=process_scope.Commands(scope,probes)
    sampler=probe_pair.Sampler();started=False;owned=False
    result={'schema':'p1-stall-isolation-v1','scope':'same-runtime-stall-diagnostic-only-no-admission',
            'device':boot.DEVICE,'runtime':boot.RUNTIME,
            'gate_implementations':{'full':'process_scope-entry-lean-launch_gate','minimal':'true-only-minimal_gate'},'observation_budget_seconds':360,
            'cleanup_deadline_seconds':480,'outer_budget_seconds':600,'cleanup_errors':[],
            'collection_complete':False,'admissionEligible':False,'production_ready':False,
            'app_build_executed':False,'app_install_executed':False,'ui_executed':False}
    def save():process_scope.atomic(output/'stall-result.json',result)
    def require(row):
        if not boot.clean(row):raise ValueError('diagnostic prerequisite failed')
        return row['data']
    try:
        result['provenance']=boot.retain_provenance(host,inputs,approved,output)
        require(commands.run('xcode-version',['xcodebuild','-version'],exact_xcode))
        require(commands.run('runtime',['xcrun','simctl','list','runtimes','--json'],exact_runtime))
        state=require(commands.run('before-state',['xcrun','simctl','list','devices','--json'],boot.exact_device))
        if state['devices'][boot.RUNTIME][0]['state']!='Shutdown':raise ValueError('initial Shutdown required')
        sampler.start();started=True
        result['before']=probe_pair.pair(trivial,'before-boot');save()
        # Preserve the same disposable runner UUID and initial-state ownership rule.
        # Persist ownership before boot, including if boot later times out.
        scope.fixture_identity(boot.DEVICE,True);owned=True
        result['boot']=commands.run('boot',['xcrun','simctl','boot',boot.DEVICE],boot.categorized_output,timeout=30)
        if boot.clean(result['boot']):
            if scope.remaining(120)!=120:raise TimeoutError('full unchanged readiness budget unavailable')
            result['bootstatus']=commands.run('bootstatus',['xcrun','simctl','bootstatus',boot.DEVICE,'-b'],boot.categorized_output,timeout=120)
        save()
        if not all(row.get('settled') is True for row in scope.rows):raise RuntimeError('boot child settlement unproved')
        result['after']=probe_pair.pair(trivial,'after-boot');save()
        result['observation_complete']=True
    except Exception as error:
        result['collector_error']=process_scope.error_info(error)
    finally:
        if started:
            try:
                result['sampler']=sampler.finish()
                if result['sampler']['error'] is not None:result['sampler_failed']=True
            except Exception as error:result['cleanup_errors'].append(process_scope.error_info(error))
        if owned:
            try:
                shutdown=simulator_cleanup.confirm_shutdown(commands,boot.DEVICE,True)
                process_scope.atomic(output/'owned-simulator-shutdown.json',shutdown)
                scope.fixture_stopped(shutdown['observed_shutdown'])
                if shutdown['command_failed']:scope.fixture_cleanup_failure()
                if not shutdown['observed_shutdown'] or shutdown['command_failed']:raise ValueError('diagnostic simulator cleanup failed')
            except Exception as error:result['cleanup_errors'].append(process_scope.error_info(error))
        try:scope.close()
        except Exception as error:result['cleanup_errors'].append(process_scope.error_info(error))
        result['collection_complete']=bool(result.get('observation_complete') and not result.get('collector_error') and not result['cleanup_errors'] and not result.get('sampler_failed'))
        save()
    return result['collection_complete']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--device-class',choices=['phone'],required=True)
    a=p.parse_args()
    if re.fullmatch('[0-9a-f]{32}',os.environ.get('P1_PROCESS_SCOPE_SESSION','')) is None:
        raise ValueError('existing outer watchdog session required')
    capture.validate(a.host_root,a.inputs,a.approved_inputs_sha256)
    if os.environ.get('ImageVersion')!='20261013.0424.1':raise ValueError('comparison runner image drift')
    with boot.sanitized_membership_diagnostics():
        return 0 if collect(a.host_root,a.inputs,a.approved_inputs_sha256,a.evidence) else 1

if __name__=='__main__':raise SystemExit(main())
