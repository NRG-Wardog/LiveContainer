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


def verify_quiescence(evidence,session,force=False):
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
            if not force or not process_scope.stop_group(pid):raise ValueError('writer group quiescence unproved')
            row['settled']=True;row['outerForcedCleanup']=True
    fixture=registry.get('fixture')
    if force and incomplete and fixture is not None:
        device=fixture.get('device')
        if not isinstance(device,str) or re.fullmatch('[A-Fa-f0-9-]{36}',device) is None or fixture.get('bundle_ids')!=['org.sidestore.fixture.p1video','org.sidestore.fixture.p1video.uitests.xctrunner']:raise ValueError('invalid fixture cleanup identity')
        # Only an exclusively booted disposable simulator can be conclusively
        # shut down by the backstop. Otherwise fail without racing live writers.
        if fixture.get('owned_boot') is not True:raise ValueError('backstop cannot establish cleanup of pre-existing simulator')
        with (evidence/'backstop-simulator-cleanup.log').open('wb') as log:
            cleanup=subprocess.Popen(['xcrun','simctl','shutdown',device],stdout=log,stderr=log,start_new_session=True)
            try:cleanup.wait(timeout=20)
            finally:
                if not process_scope.stop_group(cleanup.pid,cleanup):raise ValueError('simulator cleanup group did not settle')
            if cleanup.returncode!=0:raise ValueError('simulator shutdown not confirmed')
        registry['backstop_fixture_shutdown']=True;registry['fixture']['stopped']=True
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


def run(argv,evidence,seconds=1200):
    if seconds!=1200:raise ValueError('reviewed 20-minute outer collector budget required')
    before=time.monotonic();process=None;session=uuid.uuid4().hex
    outcome={'schema':'p1-capability-outer-budget-v1','session':session,'budget_seconds':seconds,'timed_out':False,'transport_safe':False,'admissionEligible':False};code=1
    try:
        environment=os.environ.copy();environment['P1_PROCESS_SCOPE_SESSION']=session
        process=subprocess.Popen(argv,start_new_session=True,env=environment)
        try:code=process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            outcome['timed_out']=True
            if not process_scope.stop_group(process.pid,process):raise RuntimeError('collector group did not settle')
            code=124
        except BaseException:
            process_scope.stop_group(process.pid,process);raise
        verify_quiescence(evidence,session,force=True)
        outcome['transport_safe']=True
    except Exception as error:outcome['error']=str(error);code=1
    finally:
        outcome['exit_code']=code;outcome['elapsed_seconds']=time.monotonic()-before
        evidence.mkdir(parents=True,exist_ok=True);process_scope.atomic(evidence/'outer-budget.json',outcome)
        if outcome['transport_safe']:index(evidence)
    return code


def check_package(evidence):
    row=json.loads((evidence/'outer-budget.json').read_text());q=json.loads((evidence/'quiescence.json').read_text())
    if row.get('transport_safe') is not True or q.get('quiescent') is not True or q.get('outerVerified') is not True or row.get('session')!=q.get('session'):raise ValueError('packaging blocked: quiescence unproved')
    registry=json.loads((evidence/'process-registry.json').read_text())
    if registry.get('session')!=row['session'] or not all(g.get('settled') is True for g in registry.get('groups',[])) or (registry.get('fixture') is not None and registry['fixture'].get('stopped') is not True):raise ValueError('packaging blocked: writer registry incomplete')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--check-package',action='store_true');p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.check_package:check_package(a.evidence)
    else:
        if not a.command or a.command[0]!='--':p.error('explicit -- command required')
        raise SystemExit(run(a.command[1:],a.evidence))
