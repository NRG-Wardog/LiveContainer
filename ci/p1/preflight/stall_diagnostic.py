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
import fresh_device


def exact_xcode(raw):
    result=boot.tool_text(raw,'xcode')
    if raw.decode().strip()!='Xcode 26.4.1\nBuild version 17E202':raise ValueError('comparison Xcode drift')
    return result


def exact_runtime(raw):
    result=boot.exact_runtime(raw)
    if result['buildversion']!='23C54':raise ValueError('comparison runtime build drift')
    return result


def probe_failed(pair):
    probes=pair.get('probes') if isinstance(pair,dict) else None
    if not isinstance(probes,list) or len(probes)!=2 or {p.get('mode') for p in probes}!={'full','minimal'}:return True
    for row in probes:
        launch=row.get('launch_receipt') or {}
        if type(row.get('exit_code')) is not int or row['exit_code']!=0 or row.get('failure') is not None or row.get('cleanup_errors') or launch.get('state')!='pre-exec-observed' or launch.get('exec_failure') is not None or launch.get('closed') is not True or launch.get('eof') is not True:return True
    return False

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
            'device':None,'comparison_device':boot.DEVICE,'device_policy':'fresh-created-same-type-runtime','runtime':boot.RUNTIME,
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
        state=require(commands.run('before-state',['xcrun','simctl','list','devices','--json'],fresh_device.before))
        verified=require(commands.run('device-type',['xcrun','simctl','list','devicetypes','--json'],fresh_device.available_type(state['device_type'])))
        proof={'schema':'p1-created-device-v1','session':scope.session,'name':'P1-stall-'+scope.session,**state,**verified}
        sampler.start();started=True
        result['before']=probe_pair.pair(trivial,'before-boot');save()
        scope.begin_creation(proof)
        device=require(commands.run('create',['xcrun','simctl','create',proof['name'],proof['device_type'],boot.RUNTIME],fresh_device.created_uuid,timeout=30))
        proof.update(device=device,create_complete=True)
        fresh_device.validate(proof,scope.session,device)
        # Persist the complete create receipt before any boot or verification.
        # A later inventory failure still leaves an exact owned deletion target.
        scope.fixture_created(proof);owned=True
        commands=fresh_device.Commands(scope,logs,proof);commands.count=5
        state=require(commands.run('created-state',['xcrun','simctl','list','devices','--json'],fresh_device.state_parser(device,kind=proof['device_type'])))
        if state['devices'][boot.RUNTIME][0]['state']!='Shutdown':raise ValueError('fresh initial Shutdown required')
        result['device']=device;result['created_proof']=proof;save()
        result['boot']=commands.run('boot',['xcrun','simctl','boot',device],boot.categorized_output,timeout=30)
        if boot.clean(result['boot']):
            if scope.remaining(120)!=120:raise TimeoutError('full unchanged readiness budget unavailable')
            result['bootstatus']=commands.run('bootstatus',['xcrun','simctl','bootstatus',device,'-b'],boot.categorized_output,timeout=120)
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
                shutdown=fresh_device.cleanup(commands,proof,lambda:all(r.get('settled') is True for r in scope.rows))
                process_scope.atomic(output/'owned-simulator-shutdown.json',shutdown)
                scope.fixture_stopped(shutdown['observed_shutdown'] or shutdown['deleted'])
                scope.fixture_deleted(shutdown['deleted'])
                if shutdown['command_failed']:scope.fixture_cleanup_failure()
                if not shutdown['deleted'] or shutdown['command_failed']:raise ValueError('diagnostic simulator cleanup failed')
            except Exception as error:result['cleanup_errors'].append(process_scope.error_info(error))
        try:scope.close()
        except Exception as error:result['cleanup_errors'].append(process_scope.error_info(error))
        result['collection_complete']=bool(result.get('observation_complete') and not result.get('collector_error') and not result['cleanup_errors'] and not result.get('sampler_failed'))
        result['primary_command_failed']=any(not boot.clean(result[key]) for key in ('boot','bootstatus') if key in result) or any(probe_failed(result.get(key)) for key in ('before','after'))
        save()
    return result['collection_complete'] and not result['primary_command_failed']


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
