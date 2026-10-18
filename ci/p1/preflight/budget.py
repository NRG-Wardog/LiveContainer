#!/usr/bin/env python3
"""Outer backstop plus tracked-session quiescence before evidence indexing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import re
import subprocess
import time
import uuid
import process_scope
import simulator_cleanup


def verify_quiescence(evidence,session,force=False,command_factory=None):
    path=evidence/'process-registry.json'
    if not path.is_file() or path.is_symlink():raise ValueError('process registry absent; evidence transport unsafe')
    registry=json.loads(path.read_text());groups=registry.get('groups')
    if registry.get('schema')!='p1-capability-process-scope-v1' or registry.get('session')!=session or not isinstance(groups,list):raise ValueError('wrong process registry identity')
    incomplete=registry.get('closing') is not True or any(g.get('settled') is not True for g in groups) or (registry.get('fixture') is not None and registry['fixture'].get('stopped') is not True)
    pids=set()
    for row in groups:
        pid=row.get('pid')
        if type(pid) is not int or pid<=1 or row.get('pgid')!=pid or pid in pids:raise ValueError('invalid process registry group')
        pids.add(pid)
        if row.get('settled') is not True:
            if not force or not process_scope.stop_group(pid):
                process_scope.emit_diagnostic('writer-group-unsettled',pgid=pid,operation='stop_group' if force else 'verify',result=False)
                raise ValueError('writer group quiescence unproved')
            row['settled']=True;row['outerAbsenceVerified']=True
    fixture=registry.get('fixture')
    if force and incomplete and fixture is not None:
        device=fixture.get('device')
        if not isinstance(device,str) or re.fullmatch('[A-Fa-f0-9-]{36}',device) is None or fixture.get('bundle_ids')!=['org.sidestore.fixture.p1video','org.sidestore.fixture.p1video.uitests.xctrunner']:raise ValueError('invalid fixture cleanup identity')
        # Only an exclusively booted disposable simulator can be conclusively
        # shut down by the backstop. Otherwise fail without racing live writers.
        if fixture.get('owned_boot') is not True:raise ValueError('backstop cannot establish cleanup of pre-existing simulator')
        errors=[];unsettled=[];count=0
        def command(*argv,timeout=15,cleanup=False,receipt=False):
            nonlocal count
            count+=1;primary=None;cleanup_error=None
            prefix=f'backstop-simulator-{count:02d}'
            with (evidence/(prefix+'.stdout')).open('wb') as out,(evidence/(prefix+'.stderr')).open('wb') as err:
                child=process_scope.OwnedProcess.spawn(argv,stdout=out,stderr=err,start_new_session=True)
                try:child.wait(timeout=timeout)
                except Exception as error:primary=error
                finally:
                    try:
                        if not process_scope.stop_group(child.pid,child):raise ValueError('simulator cleanup group did not settle')
                    except Exception as error:cleanup_error=error
            if cleanup_error is not None:unsettled.append(cleanup_error)
            if primary is not None:
                primary._p1_cleanup_diagnostics=[failure_info(cleanup_error)] if cleanup_error else []
                errors.append(primary)
            elif cleanup_error is not None:errors.append(cleanup_error)
            failed=primary or cleanup_error
            if failed is None and child.returncode!=0:failed=subprocess.CalledProcessError(child.returncode,argv)
            row={'exit_code':child.returncode,'failure_type':type(failed).__name__ if failed else None,
                'primary_error':failure_info(primary) if primary else None,'cleanup_errors':[failure_info(cleanup_error)] if cleanup_error else [],
                'stdout':(evidence/(prefix+'.stdout')).read_text(errors='replace'),'stderr':(evidence/(prefix+'.stderr')).read_text(errors='replace')}
            process_scope.emit_diagnostic('backstop-simulator-cleanup',pgid=child.pid,exit_code=child.returncode,
                primary_error=row['primary_error'],cleanup_errors=row['cleanup_errors'])
            return row
        if command_factory is not None:command=command_factory(evidence,errors,unsettled,SanitizedCommandError)
        shutdown=simulator_cleanup.confirm_shutdown(command,device,True)
        process_scope.atomic(evidence/'backstop-simulator-shutdown.json',shutdown)
        # A later simulator-state observation never settles an earlier host
        # writer. Preserve its primary timeout alongside unresolved cleanup.
        if unsettled:raise errors[0] if errors else unsettled[0]
        if not shutdown['observed_shutdown']:
            if errors:raise errors[0]
            raise ValueError('simulator shutdown not confirmed')
        registry['backstop_fixture_shutdown']=True;registry['fixture']['stopped']=True
        registry['backstop_cleanup_command_failed']=shutdown['command_failed']
    process_scope.atomic(path,registry)
    process_scope.atomic(evidence/'quiescence.json',{'schema':'p1-capability-quiescence-v1','session':session,'quiescent':True,'groups':len(groups),'outerVerified':True,'admissionEligible':False})


def index(evidence):
    files={}
    for path in sorted(evidence.rglob('*')):
        if path.is_symlink():raise ValueError('linked partial evidence')
        if path.is_file() and path.name!='evidence-index.json':
            h=hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
            files[str(path.relative_to(evidence))]=h.hexdigest()
    process_scope.atomic(evidence/'evidence-index.json',{'schema':'p1-diagnostic-evidence-index-v1','files':files})


REASONS={
 'process registry absent; evidence transport unsafe','wrong process registry identity','invalid process registry group',
 'writer group quiescence unproved','invalid fixture cleanup identity','backstop cannot establish cleanup of pre-existing simulator',
 'simulator cleanup group did not settle','simulator shutdown not confirmed','collector group did not settle',
 'packaging blocked: quiescence unproved','packaging blocked: writer registry incomplete','linked partial evidence',
}


class SanitizedCommandError(Exception):
    """A fixed public message with an independently retained typed failure."""
    def __init__(self,error):
        super().__init__('bounded simulator observer failed')
        self.diagnostic=process_scope.error_info(error)


def failure_info(error):
    if isinstance(error,SanitizedCommandError):return dict(error.diagnostic)
    row=process_scope.error_info(error)
    # Only fixed harness reasons may reach stdout; arbitrary exception args,
    # subprocess argv and environmental values are intentionally omitted.
    if str(error) in REASONS:row['reason']=str(error)
    return row


def phase_summaries(evidence):
    """Read only a bounded regular summary, never the mutable payload tree.

    These diagnostic flags are not authenticated evidence and cannot grant a
    pass. Reading failure must never mask the original collector/gate error.
    """
    import stat
    path=evidence/'capability-result.json';fd=None
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or meta.st_size>65536:raise ValueError('unsafe diagnostic summary')
        with os.fdopen(fd,'rb') as f:fd=None;raw=f.read(65537)
        if len(raw)>65536:raise ValueError('oversized diagnostic summary')
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError('invalid diagnostic summary')
        for phase,row in [('collector',result),('calibration',result.get('calibration')),('recovery',result.get('recovery'))]:
            if not isinstance(row,dict):continue
            fields={key:row[key] for key in ['collection_complete','capabilities_passed','calibration_feasible','full_matrix_complete'] if type(row.get(key)) is bool}
            if isinstance(row.get('errors'),list):fields['error_count']=len(row['errors'])
            process_scope.emit_diagnostic('retained-phase-summary',component=phase,unverified_summary=True,**fields)
    except Exception as error:process_scope.emit_diagnostic('phase-summary-unavailable',error=process_scope.error_info(error))
    finally:
        if fd is not None:os.close(fd)


def run(argv,evidence,seconds=1200,command_factory=None,stall_diagnostic=False):
    if seconds!=(600 if stall_diagnostic else 1200):raise ValueError('fixed reviewed outer collector budget required')
    before=time.monotonic();process=None;session=uuid.uuid4().hex;phase='collector-spawn';primary=None;cleanup_errors=[]
    outcome={'schema':'p1-capability-outer-budget-v1','session':session,'budget_seconds':seconds,'timed_out':False,'transport_safe':False,'admissionEligible':False};code=1
    try:
        environment=os.environ.copy();environment['P1_PROCESS_SCOPE_SESSION']=session
        process=process_scope.OwnedProcess.spawn(argv,start_new_session=True,env=environment);phase='collector-wait'
        try:code=process.wait(timeout=seconds)
        except subprocess.TimeoutExpired as error:
            primary=error;outcome['timed_out']=True;code=124;phase='collector-timeout-cleanup'
            try:
                if not process_scope.stop_group(process.pid,process):raise RuntimeError('collector group did not settle')
            except Exception as cleanup:cleanup_errors.append(failure_info(cleanup));raise
        except BaseException as error:
            primary=error;phase='collector-error-cleanup'
            try:process_scope.stop_group(process.pid,process)
            except Exception as cleanup:cleanup_errors.append(failure_info(cleanup))
            raise
        phase='collector-disappearance'
        if not process_scope.stop_group(process.pid,process):raise RuntimeError('collector group did not settle')
        phase='verify-quiescence'
        if command_factory is None:verify_quiescence(evidence,session,force=True)
        else:verify_quiescence(evidence,session,force=True,command_factory=command_factory)
        outcome['transport_safe']=True
        if json.loads((evidence/'process-registry.json').read_text()).get('backstop_cleanup_command_failed') is True:
            code=1;outcome['cleanup_command_failed']=True
    except Exception as error:
        if primary is None:primary=error
        elif error is not primary and not cleanup_errors:cleanup_errors.append(failure_info(error))
        cleanup_errors.extend(getattr(error,'_p1_cleanup_diagnostics',[]))
        outcome['error']=str(primary);code=1
    finally:
        outcome.update(exit_code=code,elapsed_seconds=time.monotonic()-before,phase=phase,primary_error=failure_info(primary) if primary else None,cleanup_errors=cleanup_errors)
        # This console record exists even when writing or packaging the mutable
        # payload is forbidden. It is diagnostic metadata, never a pass receipt.
        process_scope.emit_diagnostic('outer-budget-result',session=session,collector_phase=phase,exit_code=code,timed_out=outcome['timed_out'],
            transport_safe=outcome['transport_safe'],primary_error=outcome['primary_error'],cleanup_errors=cleanup_errors)
        phase_summaries(evidence)
        evidence.mkdir(parents=True,exist_ok=True)
        try:process_scope.atomic(evidence/'outer-budget.json',outcome)
        except Exception as error:
            process_scope.emit_diagnostic('outer-result-write-failure',error=failure_info(error));raise
        if outcome['transport_safe']:
            try:index(evidence)
            except Exception as error:
                process_scope.emit_diagnostic('evidence-index-failure',error=failure_info(error));raise
    return code


def check_package(evidence):
    try:
        row=json.loads((evidence/'outer-budget.json').read_text());q=json.loads((evidence/'quiescence.json').read_text())
        if row.get('transport_safe') is not True or q.get('quiescent') is not True or q.get('outerVerified') is not True or row.get('session')!=q.get('session'):raise ValueError('packaging blocked: quiescence unproved')
        registry=json.loads((evidence/'process-registry.json').read_text())
        if registry.get('session')!=row['session'] or not all(g.get('settled') is True for g in registry.get('groups',[])) or (registry.get('fixture') is not None and registry['fixture'].get('stopped') is not True):raise ValueError('packaging blocked: writer registry incomplete')
    except Exception as error:
        process_scope.emit_diagnostic('package-gate-failure',error=failure_info(error));raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--check-package',action='store_true');p.add_argument('--boot-diagnostic',action='store_true');p.add_argument('--stall-diagnostic',action='store_true');p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.check_package:check_package(a.evidence)
    else:
        if not a.command or a.command[0]!='--':p.error('explicit -- command required')
        if a.stall_diagnostic:
            if a.boot_diagnostic or len(a.command)<4 or Path(a.command[3]).resolve()!=Path(__file__).with_name('stall_diagnostic.py').resolve():p.error('exact stall collector required')
            import boot_diagnostic
            with boot_diagnostic.sanitized_membership_diagnostics():
                raise SystemExit(run(a.command[1:],a.evidence,seconds=600,command_factory=boot_diagnostic.backstop_commands,stall_diagnostic=True))
        if a.boot_diagnostic:
            import boot_diagnostic
            with boot_diagnostic.sanitized_membership_diagnostics():
                raise SystemExit(run(a.command[1:],a.evidence,command_factory=boot_diagnostic.backstop_commands))
        raise SystemExit(run(a.command[1:],a.evidence))
