#!/usr/bin/env python3
"""Local-only finite defensive A+B capture contract. Emits plans or checks inert logs.
No subprocess, network, publication, workflow, or native execution entry point.
A successful check is not authentication or capture approval.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
MAX_LOG_BYTES = 4 * 1024 * 1024
SANDBOX = ['/usr/bin/sandbox-exec', '-p', '(version 1) (allow default) (deny network*)']
UNSAFE = 'unicornAnisetteProvisioningAndHeaders'
SS_CORE = ('deviceInitializationAndFiltering','certificateRequestCSRGeneration','developerPortalSingleton',
           'archiveStoreRoundtrip','archiveDeflateRoundtrip')
AK_TRACE = ('testBoundsRetainFinalFailureAndMarkLoss','testErrorMetadataNeverIncludesProviderStrings',
            'testIndependentTaskLocalScopesDoNotBleed','testNativeTimingIsStrictAndAtomic',
            'testTerminalEventIsExactlyOnceAndDurationIsMonotonicBounded','testWrappersPreserveSuccessAndError')
SUITES = {'SideSignTests':'SideSign Core Tests'}
LANES = {'anisette-trace-regression': ('AnisetteKit', {'LoginDiagnosticTraceTests':AK_TRACE}),
         'sidesign-core-regression': ('SideSign', {'SideSignTests':SS_CORE})}
XCTEST_SUITES = ('Selected tests','AnisetteKitPackageTests.xctest','LoginDiagnosticTraceTests')
DURATION = r'[0-9]+(?:\.[0-9]+)?'
TIMESTAMP = r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}'

def require(ok, message):
    if not ok: raise ValueError(message)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def lane_data(lane):
    require(lane in LANES, 'unknown finite lane')
    return LANES[lane]
def test_ids(owner, groups, xctest=False):
    return sorted(owner+'Tests.'+cls+'/'+method+('' if xctest else '()')
                  for cls,methods in groups.items() for method in methods)
def selected_ids(lane):
    owner,groups = lane_data(lane)
    return test_ids(owner, groups, lane=='anisette-trace-regression')
def discovered_ids(lane):
    # Each complete listing is restricted to its enabled framework. AK's
    # unrelated Swift Testing cases are neither discovered nor executed here.
    return selected_ids(lane)
def exact_filter(lane):
    suffix = r'$' if lane=='anisette-trace-regression' else r'(/|$)'
    return '^('+'|'.join(re.escape(i) for i in selected_ids(lane))+')'+suffix

def bounded_text(raw):
    require(isinstance(raw,bytes) and len(raw)<=MAX_LOG_BYTES, 'bounded raw log bytes required')
    text=raw.decode('utf-8',errors='strict')
    require('\x00' not in text, 'NUL in log')
    return text

def verify_discovery(raw,lane):
    lines=[line for line in bounded_text(raw).splitlines() if line.strip()]
    expected=discovered_ids(lane)
    require(len(lines)==len(expected) and set(lines)==set(expected), 'complete exact discovery differs; never widen a filter')
    return {'status':'LOCAL_RAW_LOG_CHECK_ONLY','discovered_test_ids':sorted(lines),
            'selected_test_ids':selected_ids(lane),'raw_sha256':sha(raw)}

def runtime_rows(text):
    """Keep every result-like row, including malformed ones, for full matching.

    Genuine captured output can concatenate a case event onto a partial trace
    write. Locate that event without requiring a line boundary; its entire
    remaining row must still match. A second event or trailing junk rejects.
    """
    marker = re.compile(r'Test[ \t]*(?:Case|Suite)|Executed|\b(?:Test|Suite)\b',re.I)
    return [line[match.start():] for line in text.splitlines()
            if (match := marker.search(line)) is not None]


def verify_xctest_runtime(text, expected_methods):
    require('Test run' not in text and 'Testing Library' not in text,
            'Swift Testing unexpectedly enabled')
    rows=runtime_rows(text); events=[]
    for row in rows:
        suite=re.fullmatch(r"Test Suite '([^']+)' (started|passed) at ("+TIMESTAMP+r")\.",row)
        case=re.fullmatch(r"Test Case '([^']+)' (started\.|passed \("+DURATION+r" seconds\)\.)",row)
        summary=re.fullmatch(r'Executed 6 tests, with 0 failures \(0 unexpected\) in '+DURATION+r' \('+DURATION+r'\) seconds',row)
        require(sum(match is not None for match in (suite,case,summary))==1,
                'unknown or malformed XCTest result row')
        if suite:
            # Syntax alone must not accept an impossible native timestamp.
            datetime.strptime(suite[3],'%Y-%m-%d %H:%M:%S.%f')
            events.append(('suite',suite[1],suite[2]))
        elif case:
            identity=case[1]
            name=re.fullmatch(r'-\[AnisetteKitTests\.LoginDiagnosticTraceTests (test\w+)\]',identity)
            if name is None:
                name=re.fullmatch(r'(?:AnisetteKitTests\.)?LoginDiagnosticTraceTests\.(test\w+)',identity)
            require(name is not None,'unknown XCTest identity')
            events.append(('case',name[1],'started' if case[2]=='started.' else 'passed',identity))
        else:events.append(('summary',))
    # Exactly three nested suites, six complete cases, and one summary directly
    # after each suite's completion. Diagnostic rows do not affect this order.
    require(len(events)==3+2*len(expected_methods)+6,'exact XCTest lifecycle required')
    require(events[:3]==[('suite',suite,'started') for suite in XCTEST_SUITES],
            'XCTest suite opening order differs')
    closing=[]
    for suite in reversed(XCTEST_SUITES):
        closing.extend([('suite',suite,'passed'),('summary',)])
    require(events[-6:]==closing,'exact three XCTest suite completion summaries required')
    case_events=events[3:-6]
    require(all(event[0]=='case' for event in case_events),'XCTest case escaped its suite lifecycle')
    seen=set()
    for start,passed in zip(case_events[::2],case_events[1::2]):
        require(start[2]=='started' and passed[2]=='passed' and start[1]==passed[1]
                and start[3]==passed[3],'XCTest case completion ordering differs')
        require(start[1] in expected_methods and start[1] not in seen,
                'exact once-only XCTest IDs required')
        seen.add(start[1])
    require(seen==expected_methods,'complete exact XCTest IDs required')


def verify_swift_testing_runtime(text, groups, expected_methods):
    rows=runtime_rows(text); events=[]
    for row in rows:
        suite=re.fullmatch(r'Suite "([^"]+)" (started\.|passed after '+DURATION+r' seconds?\.)',row)
        case=re.fullmatch(r'Test ([A-Za-z_][A-Za-z_0-9]*)\(\) (started\.|passed after '+DURATION+r' seconds?\.)',row)
        summary=re.fullmatch(r'Test run with ([0-9]+) tests(?: in ([0-9]+) suites?)? passed after '+DURATION+r' seconds?\.',row)
        opening=row=='Test run started.'
        require(sum(match is not None for match in (suite,case,summary))+opening==1,
                'unknown or malformed Swift Testing result row')
        if suite:events.append(('suite',suite[1],'started' if suite[2]=='started.' else 'passed'))
        elif case:events.append(('case',case[1],'started' if case[2]=='started.' else 'passed'))
        elif summary:
            require(summary[1]==str(len(expected_methods)),'exact final test count required')
            require(summary[2] is None or summary[2]==str(len(groups)),'wrong final suite count')
            events.append(('summary',))
        else:events.append(('opening',))
    if events and events[0]==('opening',):events=events[1:]
    require(len(events)==2*len(expected_methods)+2*len(groups)+1,
            'exact Swift Testing lifecycle required')
    require(events[-1:]==[('summary',)],'exact final Swift Testing summary required')
    expected_suites={SUITES[group]:set(methods) for group,methods in groups.items()}
    active_suites=set(); completed_suites=set(); starts=set(); passes=set()
    for event in events[:-1]:
        require(event[0] in ('suite','case'),'extra or misplaced run-level row')
        kind,name,state=event
        if kind=='suite':
            require(name in expected_suites,'unexpected Swift Testing suite')
            if state=='started':
                require(name not in active_suites|completed_suites,'duplicate Swift Testing suite')
                active_suites.add(name)
            else:
                require(name in active_suites and expected_suites[name]<=passes,
                        'unsettled Swift Testing suite')
                active_suites.remove(name);completed_suites.add(name)
        else:
            require(name in expected_methods,'unexpected Swift Testing identity')
            require(any(name in expected_suites[suite] for suite in active_suites),
                    'Swift Testing case escaped its suite lifecycle')
            if state=='started':
                require(name not in starts,'duplicate Swift Testing start')
                starts.add(name)
            else:
                require(name in starts and name not in passes,'Swift Testing pass before start or duplicate')
                passes.add(name)
    require(not active_suites and completed_suites==set(expected_suites)
            and starts==passes==expected_methods,'complete exact Swift Testing lifecycle required')


def verify_runtime(raw,lane):
    _,groups=lane_data(lane)
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',bounded_text(raw))
    require(UNSAFE not in text, 'unsafe online/guest test appeared in runtime')
    require(not re.search(r'(?:Test (?:Case )?.*\b(?:failed|skipped|cancelled|canceled)\b|\b[1-9][0-9]* (?:tests? )?(?:failed|skipped|cancelled|canceled)\b|Issue recorded|recorded an issue)',text,re.I),
            'runtime failure, cancellation, issue, or skip')
    expected=selected_ids(lane); expected_methods={m for ms in groups.values() for m in ms}
    require(len(expected_methods)==len(expected),'ambiguous runtime method names')
    if lane=='anisette-trace-regression':verify_xctest_runtime(text,expected_methods)
    else:verify_swift_testing_runtime(text,groups,expected_methods)
    return {'status':'LOCAL_RAW_LOG_CHECK_ONLY','test_ids':expected,'executed':len(expected),
            'failed':0,'skipped':0,'raw_sha256':sha(raw),'authenticated_capture':False}

def verify_test_sources(root,owner,inventory):
    require(owner in ('AnisetteKit','SideSign'),'unknown owner')
    require(root.is_dir() and not root.is_symlink(),'ordinary owner root required')
    expected=inventory['swift_files'][owner]
    paths={str(p.relative_to(root)) for p in (root/'Tests').rglob('*.swift')}
    require(paths==set(expected),'complete test-file inventory changed')
    for rel,row in expected.items():
        p=root/rel
        require(not p.is_symlink() and p.is_file(),'ordinary audited test file required')
        for parent in p.parents:
            if parent==root:break
            require(not parent.is_symlink(),'linked test ancestor')
        raw=p.read_bytes()
        require(len(raw)==row['bytes'] and sha(raw)==row['sha256'],'audited test bytes changed: '+rel)
    return {'owner':owner,'audited_test_files':len(expected),'status':'SOURCE_HASH_CHECK_ONLY'}

def expected_commands(lane):
    owner,_=lane_data(lane); root='/REVIEWED/SOURCES/'+owner; scratch='/FRESH/WORK/'+owner+'-scratch'
    opts=['--package-path',root,'--scratch-path',scratch,'--force-resolved-versions','--disable-dependency-cache']
    framework=['--enable-xctest','--disable-swift-testing'] if lane=='anisette-trace-regression' else ['--disable-xctest','--enable-swift-testing']
    commands={
        'build':['swift','build',*opts,'--build-tests','-v'],
        'discover':[*SANDBOX,'swift','test','list',*opts,'--skip-build','--disable-sandbox',*framework],
        'execute':[*SANDBOX,'swift','test',*opts,'--skip-build','--disable-sandbox',*framework,'--filter',exact_filter(lane)]}
    return commands

def proposed_commands(lane):
    commands=expected_commands(lane)
    validate_commands(lane,commands)
    return {'status':'NON_EXECUTABLE_PROPOSAL','approval_anchor':None,'commands':commands,
            'discovery_test_ids':discovered_ids(lane),'selected_test_ids':selected_ids(lane)}

def validate_commands(lane,commands):
    require(commands==expected_commands(lane),'exact finite command arrays required')
    require(set(commands)=={'build','discover','execute'},'unexpected command stage')
    for kind in ['discover','execute']:
        cmd=commands[kind]
        require(cmd[:len(SANDBOX)]==SANDBOX,'network denial missing')
        require('--skip-build' in cmd and '--force-resolved-versions' in cmd,'frozen built package required')
        require(cmd.count('--filter')==(kind=='execute'),'explicit execution filter; unfiltered discovery only')
        require(('--enable-xctest' in cmd)==(lane=='anisette-trace-regression'),'wrong framework enabled')
        require(('--disable-swift-testing' in cmd)==(lane=='anisette-trace-regression'),'wrong framework disabled')
        require(('--enable-swift-testing' in cmd)==(lane=='sidesign-core-regression'),'wrong framework enabled')
        require(('--disable-xctest' in cmd)==(lane=='sidesign-core-regression'),'wrong framework disabled')
    execution=commands['execute']
    require(execution[-2:]==['--filter',exact_filter(lane)],'execution filter differs')
    for candidate in discovered_ids(lane):
        matches=bool(re.search(execution[-1],candidate))
        require(matches==(candidate in selected_ids(lane)),'filter selects unexpected discovered test')
    require(not re.search(execution[-1],'AnisetteKitTests.AnisetteKitTests/'+UNSAFE+'()'),'unsafe filter')

def refuse_execution():
    raise ValueError('LOCAL_ONLY: no reviewed activation, final source graph, or execution entry point; approval_anchor is None')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lane',choices=sorted(LANES)); p.add_argument('--print-command-plan',action='store_true')
    p.add_argument('--discovery-log',type=Path);p.add_argument('--runtime-log',type=Path)
    p.add_argument('--execute',action='store_true',help='Always refuses; local-only scaffold')
    a=p.parse_args()
    try:
        if a.execute:refuse_execution()
        require(a.lane is not None,'explicit finite lane required')
        require(sum([a.print_command_plan,a.discovery_log is not None,a.runtime_log is not None])==1,'one check or plan required')
        if a.print_command_plan:result=proposed_commands(a.lane)
        else:
            path=a.discovery_log or a.runtime_log
            require(path.is_file() and not path.is_symlink() and path.stat().st_size<=MAX_LOG_BYTES,'bounded ordinary log required')
            result=(verify_discovery if a.discovery_log else verify_runtime)(path.read_bytes(),a.lane)
        print(json.dumps(result,indent=2,sort_keys=True))
    except (ValueError,UnicodeError,KeyError) as e:p.exit(2,'BLOCKED: '+str(e)+'\n')
if __name__=='__main__':main()
