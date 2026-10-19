#!/usr/bin/env python3
"""C++ allocation successor normal-platform capture gate. Requires sealed inputs; never grants readiness.

No historical v2 registry or receipt is substituted. MacOS execution is explicit.
Outputs are evidence for independent review, not final integration acceptance.
"""
from __future__ import annotations
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import signal
import time
import subprocess
import sys
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prepare_candidate_inventory import BASES, BASELINE, LOCK, entries, full_sha, git, snapshot, unique, require
import source_primitives as primitives

BASIS = 'p0-cxx-allocation-v1'
FORK_URL = 'https://github.com/mahee96/unicorn/releases/download/2.1.4-multiarch/Unicorn.xcframework.zip'
FORK_SHA = '4f61907db6aafc56fb3e336b524d742342312f498bb40739f1da55fb4a24614a'
# Exact independently reviewed defensive source delta, not historical execution.
AK_COMMIT = '161435bcc0344e1a9853669455c1ca8d9dda2bf1'
AK_TREE = '0df50020ddd774a5b7ab941944501f1ecd591a4a'
AK_FILES = {'.ci/native-tests/CXX_ALLOCATION_REVIEW.md': '9fe95fc1f891f57127834eef438dc398ad23d347a8a14ff5fbc0cc5522fa414d', '.ci/native-tests/fixtures/cxx_allocation_hook_unit.cpp': '0614c634f0d8ca648bde35fde4d55ec07f657becb8b2a5cd1d78a92d7a0f1c62', '.ci/native-tests/fixtures/cxx_allocation_unit.cpp': 'cbbe243428144a0584593246a4d4b92d00ee9807cff457404d8d3a18d491680c', '.ci/native-tests/test_android_tls_runtime.py': '8703b29d5dfd0d2f8af0a4ae7ec48454dcf973b1d257a16b6bafe65b0e905c5f', '.ci/native-tests/test_constructor_diagnostics.py': '2d33180d03e77e45befb8cca18c08adf7f37698ced54164fc3a0583acd16100e', '.ci/native-tests/test_cxx_allocation.py': 'c0f2c97e40be67ac381792a9ebae60dbdb1363e0517741b1cbfa90f0d342d3d7', 'Native/Loader/cxx_allocation_runtime.h': 'b76bdc4043c497700f93aff5ad82968f7660ebb6720bb2c71ea5615000380a62', 'Native/Loader/elf_loader_emulator.cpp': '44a8b61dcf1d4d8d309f624c442c008278d33a68ccf14ec4dc9f4757d9cdce2a'}
HELPER_SOURCES = {'Native/Loader/elf_metadata_bounds.h': '7acd9287cc351b55141f40a0baecda9c3d3202a420cf4b7f0f2515572d877253', 'Native/anisette_base.h': '6c47c3fef881d99082d1eb7e687fc78de6339568118259884d2b8a0d6c6e8664', 'Native/include/anisette_core.h': 'ca1ea4005f77dcca17c68965ba2dd1f65596e282a57adb4277f1d90d8bd11f02', '.ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp': 'bb4e7ec60202f6576f8013d0925c69c6ca4d8fca6061d93b233587efdb35487a'}
HISTORICAL_CAPTURE = '6edd04bdeca008faf0f5e3c56d0ff42ac097e7d8'
METADATA_EXPECTED = {'schema': 1, 'checks': 713, 'failures': 0,
                     'guest_execution': False, 'proprietary_input': False}

SHA256 = re.compile('[0-9a-f]{64}')

def sha(data): return hashlib.sha256(data).hexdigest()
def dump(path, data): path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')
def parse(data): return json.loads(data, object_pairs_hook=unique)
def digest(value): require(isinstance(value,str) and SHA256.fullmatch(value) and value != '0'*64,'actual SHA256 required'); return value

def ordinary(root, relative):
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute(),'relative file required')
    require(all(p not in ('.','..','.git') for p in relative.split('/')), 'unsafe relative file')
    p=root
    require(not p.is_symlink(),'linked root')
    for piece in relative.split('/'):
        p=p/piece; require(not p.is_symlink(),'linked evidence/input path')
    require(p.is_file(),'missing file: '+str(p))
    return p

def validate_inputs(raw, approved, host):
    require(sha(raw)==digest(approved),'independently approved input digest mismatch')
    data=parse(raw)
    require(set(data)=={'schema_version','source_basis','integration_baseline','phase','owners','adapter_files','contracts','test_suites','prior_sidesign','submodules','historical_basis'},'unexpected P0 input schema')
    require(data['schema_version']==1 and data['source_basis']==BASIS and data['integration_baseline']==BASELINE,'unsupported P0 source basis')
    require(data['phase'] in ('sidesign','sidestore','allocation'),'unsupported phase')
    expected={'AnisetteKit'} if data['phase']=='allocation' else {'AnisetteKit','SideSign'} if data['phase']=='sidesign' else set(BASES)
    require(set(data['owners'])==expected,'exact phase owner graph required')
    for name, row in data['owners'].items():
        require(set(row)=={'repository','commit','tree','changes'},'unexpected owner schema')
        require(row['repository']=='https://github.com/NRG-Wardog/'+name+'.git','unexpected repository')
        full_sha(row['commit']);full_sha(row['tree'])
        require(isinstance(row['changes'],dict),'full source delta required')
        if name in ('LiveContainer','minimuxer','idevice','jktcp'):
            require(row['commit']==BASES[name] and row['changes']=={},'unrelated host/transport drift')
        else: require(row['commit']!=BASES[name],'old runtime/dependency commit cannot replace P0')
        for path, change in row['changes'].items():
            require(not Path(path).is_absolute() and all(p not in ('.','..','.git') for p in path.split('/')),'unsafe delta path')
            require(set(change)=={'before','after'},'exact before/after rows required')
            for value in change.values():
                if value is None: continue
                require(value.get('type') in ('blob','commit'),'invalid delta entry')
                require(set(value)==({'mode','type','git_object','sha256'} if value['type']=='blob' else {'mode','type','git_object'}),'delta entry schema differs')
                full_sha(value['git_object'])
                if value['type']=='blob': digest(value['sha256'])
    historical=data['historical_basis']
    require(set(historical)=={'capture_commit','role','fresh_guest_execution','fingerprints_path','fingerprints_sha256'},'historical basis schema differs')
    require(historical['capture_commit']==HISTORICAL_CAPTURE and historical['role']=='historical-only' and historical['fresh_guest_execution'] is False,'historical evidence cannot claim current execution')
    require(historical['fingerprints_path']=='ci/p0cxx/historical-source-fingerprints.json','fixed fingerprint path required')
    require(sha(ordinary(host,historical['fingerprints_path']).read_bytes())==digest(historical['fingerprints_sha256']),'historical fingerprint inventory differs')
    require(data['owners']['AnisetteKit']['commit']==AK_COMMIT and data['owners']['AnisetteKit']['tree']==AK_TREE,'exact reviewed AnisetteKit commit/tree required')
    changes=data['owners']['AnisetteKit']['changes']
    require(AK_FILES and set(changes)==set(AK_FILES),'AK candidate must contain the exact reviewed eight-file C++ allocation delta')
    for path, expected_hash in AK_FILES.items():
        require(changes[path]['after']['sha256']==expected_hash,'AK candidate source differs: '+path)
    if data['phase']!='allocation':
        sign_changes=set(data['owners']['SideSign']['changes'])
        require(sign_changes=={'Package.swift'} if data['phase']=='sidesign' else sign_changes=={'Package.swift','Package.resolved'},'SideSign delta must remain manifest-only then genuine lock-only cascade')
    else:
        require(data['test_suites']==[] and data['submodules']=={},'allocation capture has no guest suites or children')
    if data['phase']=='sidestore':
        require(set(data['owners']['SideStore']['changes']) <= {'Dependencies/SideSign', LOCK} and 'Dependencies/SideSign' in data['owners']['SideStore']['changes'],'SideStore must remain dependency-only')
    require(set(data['adapter_files'])=={'ci/p0cxx/native_gate.py','ci/p0cxx/prepare_candidate_inventory.py','ci/p0cxx/run_unittest_suite.py','ci/p0cxx/source_primitives.py','ci/p0cxx/allocation_gate.py'},'exact adapter inventory required')
    for path, expected_hash in data['adapter_files'].items():
        require(sha(ordinary(host,path).read_bytes())==digest(expected_hash),'adapter file differs: '+path)
    require(isinstance(data['submodules'],dict),'reviewed full child URL graph required')
    for path,row in data['submodules'].items():
        require(not Path(path).is_absolute() and all(p not in ('.','..','.git') for p in path.split('/')),'unsafe child path')
        require(set(row)=={'repository','declared_repository','commit','tree'},'exact child identity required')
        for key in ('repository','declared_repository'):require(re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',row[key]),'unreviewed child protocol/host')
        full_sha(row['commit']);full_sha(row['tree'])
    tests=data['test_suites'];require(isinstance(tests,list),'test suites must be a list')
    seen=set(); executed_modules=set(); executed_test_ids=set()
    for row in tests:
        require(set(row)=={'id','owner','files','modules','expected_test_ids'},'unexpected test suite schema')
        require(isinstance(row['id'],str) and re.fullmatch('[a-z0-9_-]+',row['id']) and row['id'] not in seen,'duplicate/unsafe suite ID')
        seen.add(row['id']);require(row['owner'] in expected,'test owner outside phase')
        require(isinstance(row['expected_test_ids'],list) and row['expected_test_ids'] and all(isinstance(x,str) for x in row['expected_test_ids']) and len(row['expected_test_ids'])==len(set(row['expected_test_ids'])),'exact nonempty unique test IDs required')
        require(not (set(row['expected_test_ids']) & executed_test_ids),'duplicate canonical test IDs across suites');executed_test_ids.update(row['expected_test_ids'])
        require(isinstance(row['files'],dict) and row['files'],'sealed test source inventory required')
        require(isinstance(row['modules'],list) and row['modules'] and len(row['modules'])==len(set(row['modules'])),'unique modules required')
        require(all(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',x) for x in row['modules']),'simple test module names required')
        for path,h in row['files'].items(): require(sha(ordinary(host,path).read_bytes())==digest(h),'test source differs: '+path)
        for module in row['modules']:
            files=[h for path,h in row['files'].items() if Path(path).name==module+'.py']
            require(len(files)==1,'module must have exactly one sealed file')
            key=files[0];require(key not in executed_modules,'duplicate canonical suite module');executed_modules.add(key)
    if data['phase']=='sidestore':
        require({'SideStore','LiveContainer'} <= {x['owner'] for x in tests},'final SideStore and LC native regression suites required')
        require(isinstance(data['contracts'],dict) and set(data['contracts'])=={'registry','registry_sha256','validator','validator_sha256'},'P0 contract validator and registry required')
        for key in ('registry','validator'):
            require(sha(ordinary(host,data['contracts'][key]).read_bytes())==digest(data['contracts'][key+'_sha256']),'contract input differs')
        prior=data['prior_sidesign'];require(isinstance(prior,dict) and set(prior)=={'index_sha256','run_id','run_attempt','host_commit','artifact_id','artifact_sha256'},'new SideSign run/artifact evidence required');digest(prior['index_sha256']);digest(prior['artifact_sha256']);full_sha(prior['host_commit'])
        for key in ('run_id','run_attempt','artifact_id'):require(type(prior[key]) is int and prior[key]>0,'actual prior run/artifact identity required')
    else: require(data['contracts'] is None and data['prior_sidesign'] is None,'sidesign phase cannot claim inherited native readiness')
    return data


def verified_prior_github_identity(root, expected):
    require(root is not None, 'fresh workflow-fetched prior GitHub identity required')
    transport=parse(ordinary(root,'transport.json').read_bytes())
    require(transport=={'repository':os.environ.get('GITHUB_REPOSITORY'), 'run_id':os.environ.get('GITHUB_RUN_ID'), 'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'), 'host_commit':os.environ.get('GITHUB_SHA')}, 'prior identity transport belongs to a different capture')
    require(transport['repository']=='NRG-Wardog/LiveContainer' and all(transport.values()), 'missing current capture transport identity')
    run_raw=ordinary(root,'run.json').read_bytes(); artifact_raw=ordinary(root,'artifact.json').read_bytes()
    run=parse(run_raw); artifact=parse(artifact_raw)
    require(run.get('conclusion')=='success' and run.get('status')=='completed' and run.get('head_sha')==expected['host_commit'] and run.get('run_attempt')==expected['run_attempt'] and run.get('id')==expected['run_id'],'prior GitHub run identity/conclusion differs')
    require(artifact.get('id')==expected['artifact_id'] and artifact.get('expired') is False and artifact.get('digest')=='sha256:'+expected['artifact_sha256'] and artifact.get('workflow_run',{}).get('id')==expected['run_id'] and artifact.get('workflow_run',{}).get('head_sha')==expected['host_commit'],'prior GitHub artifact identity/digest differs')
    return {'run':run,'artifact':artifact,'transport':transport,'raw_sha256':{'run':sha(run_raw),'artifact':sha(artifact_raw)}}

def verify_sidesign_tests(text):
    text=re.sub(r"\x1b\[[0-9;]*m", "", text)
    expected={'deviceInitializationAndFiltering','certificateRequestCSRGeneration','developerPortalSingleton','archiveStoreRoundtrip','archiveDeflateRoundtrip'}
    matches=re.findall(r"Test ([A-Za-z0-9_]+)\(\) passed after",text)
    starts=re.findall(r"Test ([A-Za-z0-9_]+)\(\) started",text)
    summaries=re.findall(r"Test run with (\d+) tests(?: in \d+ suites?)? passed after",text)
    require(not re.search(r"(?:Test .*\b(?:failed|skipped)\b|\b[1-9][0-9]* (?:tests? )?(?:failed|skipped)\b)",text,re.I),'SideSign native test failure/skip observed')
    require(set(matches)==expected and len(matches)==len(expected) and set(starts)==expected and len(starts)==len(expected) and summaries==[str(len(expected))],'SideSign native tests missing/skipped/duplicated/unexpected')
    return {'scope':'sidesign','executed':len(matches),'tests':sorted(matches),'status':'CAPTURED_FOR_REVIEW'}

def verify_metadata_receipt(value):
    require(set(value)=={'schema','source_sha256','results','sanitizers','leak_sanitizer_enabled','guest_execution','device_validation','proprietary_input'},'metadata receipt schema differs')
    require(type(value['schema']) is int and value['schema']==1 and value['source_sha256']==HELPER_SOURCES,'metadata source identity differs')
    require(set(value['results'])=={'normal','optimized','sanitized'},'all three host metadata variants required')
    for result in value['results'].values():
        require(result==METADATA_EXPECTED and set(result)==set(METADATA_EXPECTED) and all(type(result[k]) is type(v) for k,v in METADATA_EXPECTED.items()),'metadata unit result failed or differs')
    require(value['sanitizers']==['address','undefined'] and value['leak_sanitizer_enabled'] is False,'exact macOS sanitizer configuration required')
    require(all(value[k] is False for k in ('guest_execution','device_validation','proprietary_input')),'host helper cannot claim guest/device/proprietary execution')
    return value

ANISETTE_BOUNDARY_CASES = [
    'test_actual_consumer_hooks_observe_without_changing_results',
    'test_actual_loader_lifetime_and_read_only_callbacks',
    'test_actual_native_boundary_success_faults_and_concurrent_calls',
    'test_actual_swift_consumer_decoder_rejects_private_or_malformed_values',
    'test_native_trace_is_bounded_and_can_be_disabled_without_changing_results',
    'test_normal_checked_staging_blocks_otp_and_preserves_previous_blob_on_every_io_failure',
    'test_swift_and_native_metadata_allowlists_are_identical',
    'test_constructor_diagnostic_reaches_actual_json_boundary_and_preserves_poison',
]
def verify_anisette_boundary_output(text):
    matches=re.findall(r'^('+'|'.join(ANISETTE_BOUNDARY_CASES)+r') \(__main__\.MaintainedAnisetteNativeTests\.\1\) \.\.\. ok$',text,re.M)
    require(len(matches)==len(ANISETTE_BOUNDARY_CASES) and set(matches)==set(ANISETTE_BOUNDARY_CASES),'native boundary case missing, duplicate, failed or skipped')
    require(re.findall(r'^Ran ([0-9]+) tests? in ',text,re.M)==[str(len(ANISETTE_BOUNDARY_CASES))] and re.findall(r'^OK.*$',text,re.M)==['OK'],'native boundary summary failed or skipped')
    return {'checks':len(matches),'failures':0,'skipped':0,'case_ids':sorted(matches),'ADI_executed':False,'device_validation':False}

def command_environment(name,args,env=None):
    env=dict(os.environ if env is None else env)
    env={k:v for k,v in env.items() if not k.startswith('GIT_')}
    # SwiftPM creates bounded local shared clones from its resolver mirror. Only
    # the fixed native package commands may use file transport; the source graph
    # and mirror chain are proved after resolution and before compilation.
    package_commands={'sidesign-resolve','sidesign-frozen-resolve','sidesign-build','sidesign-tests','sidestore-resolve','sidestore-frozen-resolve','sidestore-build','livecontainer-build'}
    package_tool=str(args[0]) in {'swift','xcodebuild','/usr/bin/sandbox-exec'}
    protocols='https:file' if name in package_commands and package_tool else 'https'
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_ALLOW_PROTOCOL=protocols,GIT_NO_REPLACE_OBJECTS='1',GIT_GRAFT_FILE=os.devnull,GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    return env

def finish_owned_child(process):
    """Signal only a retained, unreaped child identity. Never a reaped PGID."""
    state = {'pgid': process.pid, 'quiescent': False, 'pipesJoined': False,
             'signals': [], 'identityRetainedForSignals': False, 'reapedBeforeSignals': False,
             'postReapPolicy': 'read-only-group-disappearance', 'errors': []}
    result = {'ownedProcessGroup': state}
    try:
        # SIG_IGN/custom handlers could reap asynchronously and invalidate PID
        # reservation. This driver is single-threaded and owns all child waits.
        require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL, 'SIGCHLD identity reservation unavailable')
        if process.returncode is None:
            process.poll()  # Last possible reap before the nonzero-signal phase.
        state['reapedBeforeSignals'] = process.returncode is not None
        if process.returncode is None:
            require(os.getpgid(process.pid) == process.pid, 'Owned child process group differs')
            state['identityRetainedForSignals'] = True
            # No poll/wait/communicate is allowed between this reservation and
            # the last signal. An exited child remains an unreaped zombie, so
            # its PID/PGID cannot be reused by an unrelated process group.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                require(process.returncode is None and signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
                        'Owned child identity lost before signal')
                try:
                    os.killpg(process.pid, sig)
                    state['signals'].append(int(sig))
                except ProcessLookupError:
                    break
                if sig == signal.SIGTERM:
                    time.sleep(0.5)  # Bounded grace, deliberately without reaping.
    except Exception as error:
        state['errors'].append(type(error).__name__ + ': ' + str(error))
    # The signal phase has irrevocably ended. No nonzero signal below here,
    # even if a descendant retains pipes or a numeric group is reused.
    try:
        stdout, stderr = process.communicate(timeout=3)
        result.update(stdout=stdout, stderr=stderr)
        state['pipesJoined'] = True
    except Exception as error:
        state['errors'].append('Pipe join: ' + type(error).__name__)
        try:
            process.wait(timeout=1)
        except Exception as wait_error:
            state['errors'].append('Owned child reap: ' + type(wait_error).__name__)
    result['terminationReturncode'] = process.returncode
    state['leaderReaped'] = process.returncode is not None
    until = time.monotonic() + 1
    while True:
        try:
            os.killpg(process.pid, 0)  # Read-only observation, never ownership proof.
        except ProcessLookupError:
            state['quiescent'] = state['leaderReaped']
            break
        except OSError as error:
            state['errors'].append('Group observation: ' + type(error).__name__)
            break
        if time.monotonic() >= until:
            state['errors'].append('Surviving or reused group; no post-reap signal permitted')
            break
        time.sleep(0.05)
    if state['errors'] or not state['quiescent'] or not state['pipesJoined']:
        result['quiescenceError'] = 'Owned child cleanup/observation incomplete; fail closed'
    return result


class Gate:
    def __init__(self,data,host,work,evidence,approved):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved
        self.sources=work/'sources';self.results=work/'results';self.roots={};self.children={};self.observed_locks={};self.stage='initialization'
        self.command_quiescence=[]
        self.state={'status':'FAILED_OR_INCOMPLETE','source_basis':BASIS,'phase':data['phase'],'production_ready':False,'ipa_built':False,'guest_execution':False,'ADI_executed':False,'device_validation':False}
    def run(self,name,args,*,cwd=None,env=None,strict_stderr=False,timeout=7200):
        require(re.fullmatch('[a-z0-9_-]+',name),'unsafe log name')
        env=command_environment(name,args,env)
        if str(args[0])=='git':args=['git','--no-replace-objects','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*args[1:]]
        args=[str(a) for a in args]
        log=self.evidence/'logs'/name;require(not log.with_suffix('.log').exists(),'duplicate execution ID: '+name)
        dump(log.with_suffix('.command.json'),{'argv':args,'cwd':str(cwd) if cwd else None})
        receipt={'returncode':None,'stdout':'','stderr':'','timeout_seconds':timeout}
        process=None;primary=None
        try:
            require(signal.getsignal(signal.SIGCHLD)==signal.SIG_DFL,'SIGCHLD identity reservation unavailable')
            process=subprocess.Popen(args,cwd=cwd,env=env,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if strict_stderr else subprocess.STDOUT,text=True,start_new_session=True)
            stdout,stderr=process.communicate(timeout=timeout)
            receipt.update(returncode=process.returncode,stdout=stdout or '',stderr=stderr or '')
        except Exception as error:
            primary=error;receipt['error']=type(error).__name__+': '+str(error)
            if isinstance(error,subprocess.TimeoutExpired):
                decode=lambda value:value.decode(errors='replace') if isinstance(value,bytes) else value or ''
                receipt.update(stdout=decode(error.stdout),stderr=decode(error.stderr))
        finally:
            if process is not None:
                settled=finish_owned_child(process)
                receipt.update({k:v for k,v in settled.items() if k not in ('stdout','stderr')})
                if 'stdout' in settled:receipt['stdout']=settled['stdout'] or ''
                if 'stderr' in settled:receipt['stderr']=settled['stderr'] or ''
                self.command_quiescence.append({'label':name,**settled['ownedProcessGroup']})
            log.with_suffix('.log').write_text(receipt['stdout'])
            if strict_stderr:log.with_suffix('.stderr.log').write_text(receipt['stderr'])
            # A cleanup exit code must never turn a primary timeout into success.
            code=receipt['returncode'] if receipt['returncode'] is not None else 124 if isinstance(primary,subprocess.TimeoutExpired) else 125
            log.with_suffix('.exit-code.txt').write_text(str(code)+'\n')
            dump(log.with_suffix('.settlement.json'),{k:v for k,v in receipt.items() if k not in ('stdout','stderr')})
        if primary is not None:raise primary
        require(not receipt.get('quiescenceError'),'command writers did not settle: '+name)
        require(receipt['returncode']==0,'command failed: '+name+' (see captured log)')
        require(not strict_stderr or not receipt['stderr'],'unexpected runtime stderr: '+name)
        return receipt['stdout']
    def retain_available_locks(self):
        records={}
        for name,relative in (('SideSign','Package.resolved'),('SideStore',LOCK)):
            if name not in self.roots:continue
            try:
                raw=ordinary(self.roots[name],relative).read_bytes()
                target='provenance/'+name+'.Package.resolved.final-observed'
                (self.evidence/target).write_bytes(raw)
                records[name]={'path':target,'sha256':sha(raw),'status':'OBSERVED_BYTES_ONLY'}
            except (OSError,ValueError) as error:
                records[name]={'status':'UNAVAILABLE','error':type(error).__name__}
        dump(self.evidence/'provenance/final-observed-locks.json',records)
    def source_proof(self,after_resolution=False):
        result={}
        for name,root in self.roots.items():
            row=self.data['owners'][name];actual=snapshot(root,BASES[name],row['commit'])
            require(actual['tree']==row['tree'] and actual['changes']==row['changes'],name+': exact source inventory differs')
            result[name]=primitives.verify_checkout(root,row['commit'],owner=name,after_build=after_resolution,require_full_history=True,observed_lock=self.observed_locks.get(name) if after_resolution else None)
            result[name]['origin']=primitives.verify_origin(root,row['repository'],row['commit'])
        for path,row in self.children.items():
            child=self.sources/path
            require(git(child,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'child tree changed')
            primitives.verify_origin(child,row['repository'],row['commit'])
        return result
    def clone(self,name,row,root):
        require(not root.is_symlink() and (not root.exists() or not list(root.iterdir())),'source acquisition target not fresh')
        self.run('fetch-'+name,['git','clone','--no-checkout',row['repository'],root])
        self.run('fetch-exact-'+name,['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']])
        self.run('checkout-'+name,['git','-C',root,'checkout','--detach',row['commit']])
        self.run('disable-push-'+name,['git','-C',root,'config','remote.origin.pushurl','disabled://p0-capture-readonly'])
        require(git(root,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'acquired source tree mismatch')
        primitives.verify_origin(root,row['repository'],row['commit'])
    def acquire_children(self,prefix,root):
        links={path:item['git_object'] for path,item in entries(root,git(root,'rev-parse','HEAD').decode().strip()).items() if item['type']=='commit'}
        if not links:return
        modules=configparser.ConfigParser(interpolation=None);modules.read(root/'.gitmodules')
        for relative,commit in sorted(links.items()):
            require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,'unsafe source child path')
            path=prefix+'/'+relative;sections=[dict(modules[section]) for section in modules.sections() if modules[section].get('path')==relative]
            require(len(sections)==1 and set(sections[0])=={'path','url'},'unreviewed child URL/branch configuration')
            known={'SideStore/Dependencies/SideSign':'SideSign','SideStore/Dependencies/minimuxer':'minimuxer'}
            if path in known:
                owner=known[path];row=dict(self.data['owners'][owner]);row['declared_repository']=row['repository']
            else:
                require(path in self.data['submodules'],'unreviewed source child: '+path)
                row=self.data['submodules'][path]
            require(sections[0]['url']==row['declared_repository'] and commit==row['commit'],'child declared URL/commit differs before acquisition')
            child=root/relative
            require(all(not parent.is_symlink() for parent in child.parents if parent!=root and root in parent.parents),'linked child parent')
            self.clone(path.replace('/','-').lower(),row,child)
            self.children[path]=row
            if path in known:self.roots[known[path]]=child
            self.acquire_children(path,child)
    def acquire(self):
        self.stage='fetch'
        for name,row in self.data['owners'].items():
            if name in ('SideSign','minimuxer') and self.data['phase']=='sidestore':continue
            root=self.sources/name;self.clone(name.lower(),row,root);self.roots[name]=root
            self.acquire_children(name,root)
        known={'SideStore/Dependencies/SideSign','SideStore/Dependencies/minimuxer'}
        require(set(self.children)-known==set(self.data['submodules']),'reviewed child graph inventory differs')
        dump(self.evidence/'provenance/source-before.json',self.source_proof())
        self.historical_fingerprints()
        if self.data['phase']=='allocation':return
        ak=self.data['owners']['AnisetteKit']['commit'];manifest=(self.roots['SideSign']/'Package.swift').read_text()
        require(re.search(r'\.package\(url:\s*"https://github.com/NRG-Wardog/AnisetteKit.git",\s*revision:\s*"'+ak+r'"\)',manifest),'SideSign manifest candidate pin differs')
        package=(self.roots['AnisetteKit']/'Package.swift').read_text()
        require(FORK_URL+'#AnisetteKit' in package and FORK_SHA in package,'actual app engine source/checksum changed')
    def historical_fingerprints(self):
        historical=self.data['historical_basis']
        raw=ordinary(self.host,historical['fingerprints_path']).read_bytes()
        require(sha(raw)==historical['fingerprints_sha256'],'historical fingerprint inventory changed')
        value=parse(raw);root=self.roots['AnisetteKit']
        require(value['historical_source']==BASES['AnisetteKit'] and value['current_source']==AK_COMMIT and value['fresh_guest_execution'] is False and value['full_loader_changed'] is True,'fingerprint source/coverage identity differs')
        for path,expected in value['unchanged_files'].items():
            before=git(root,'show',value['historical_source']+':'+path)
            after=ordinary(root,path).read_bytes()
            require(before==after and sha(after)==digest(expected),'historical file no longer identical: '+path)
        for path,functions in value['unchanged_function_definitions'].items():
            before=git(root,'show',value['historical_source']+':'+path)
            after=ordinary(root,path).read_bytes()
            for signature,row in functions.items():
                size=row['bytes'];old_offset=row['historical_offset'];new_offset=row['current_offset']
                require(all(type(n) is int and n>=0 for n in (size,old_offset,new_offset)) and size>0,'invalid fingerprint region')
                require(before.index(signature.encode())==old_offset and after.index(signature.encode())==new_offset,'fingerprint declaration offset differs')
                old=before[old_offset:old_offset+size];new=after[new_offset:new_offset+size]
                require(len(old)==size and old==new and sha(new)==digest(row['sha256']),'historical function no longer identical: '+signature)
        (self.evidence/'provenance/historical-source-fingerprints.json').write_bytes(raw)
        dump(self.evidence/'provenance/historical-source-comparison.json',{'status':'BYTE_IDENTITY_VERIFIED_ONLY','fingerprints_sha256':sha(raw),'historical_source':BASES['AnisetteKit'],'current_source':AK_COMMIT,'fresh_guest_execution':False,'full_loader_changed':True})
    def check_lock(self,before,after):
        old=parse(before);new=parse(after)
        def pins(lock):
            require(type(lock.get('version')) is int and isinstance(lock.get('pins'),list),'unknown lock schema')
            result={}
            for p in lock['pins']:
                identity=p.get('identity');require(isinstance(identity,str) and identity not in result,'duplicate/invalid package pin');result[identity]=p
            return result
        op,np=pins(old),pins(new)
        require(op.keys()==np.keys() and 'anisettekit' in np,'package set drift')
        for name in op:
            if name!='anisettekit': require(op[name]==np[name],'unrelated package pin drift: '+name)
        ak=np['anisettekit'];require(ak.get('location')=='https://github.com/NRG-Wardog/AnisetteKit.git','unreviewed AK origin')
        require(ak.get('state')=={'revision':self.data['owners']['AnisetteKit']['commit']},'resolver AK state differs')
        require(set(old)-{'pins','originHash'}==set(new)-{'pins','originHash'},'lock schema drift')
        for key in set(old)-{'pins','originHash'}: require(old[key]==new[key],'lock metadata drift')
        return {'sha256':sha(after),'origin_hash':{'present':'originHash' in new,'value':new.get('originHash')}}
    def resolved_ak(self,root):
        states=list(root.rglob('workspace-state.json'));require(len(states)==1,'exact real SwiftPM workspace state required')
        active='SideSign' if self.data['phase']=='sidesign' else 'SideStore'
        lock=self.roots[active]/('Package.resolved' if active=='SideSign' else LOCK)
        local={} if active=='SideSign' else {'sidesign':self.roots['SideSign'],'minimuxer':self.roots['minimuxer'],'common':self.roots['minimuxer']/'Common','devicegateway':self.roots['minimuxer']/'DeviceGateway'}
        proof=primitives.verify_resolution(self.roots,states[0],lock,local)
        dump(self.evidence/'provenance/resolved-package-graph.json',proof)
        matches=[p for p in root.rglob('AnisetteKit') if p.is_dir() and (p/'.git').exists()]
        require(len(matches)==1,'exactly one resolver AK checkout required')
        ak=matches[0];row=self.data['owners']['AnisetteKit']
        require(git(ak,'rev-parse','HEAD').decode().strip()==row['commit'] and git(ak,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'resolved AK identity differs')
        require(entries(ak,row['commit'])==entries(self.roots['AnisetteKit'],row['commit']),'resolved AK tree inventory differs')
        require(git(ak,'status','--porcelain','--untracked-files=all').strip()==b'','resolved AK checkout dirty')
        for path,item in entries(ak,row['commit']).items():
            if item['type']=='blob' and item['mode']!='120000': require(sha((ak/path).read_bytes())==item['sha256'],'resolved AK bytes differ')
        dump(self.evidence/'provenance/resolved-anisette.json',{'commit':row['commit'],'tree':row['tree'],'source_sha256':AK_FILES})
    def metadata_units(self):
        self.stage='host-only-elf-metadata-units'
        output=self.evidence/'metadata-units'
        self.run('elf-metadata-units',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-B',self.roots['AnisetteKit']/'.ci/native-tests/test_elf_metadata_bounds.py','--output',output,'--disable-leak-sanitizer'])
        receipt=verify_metadata_receipt(parse(ordinary(output,'result.json').read_bytes()))
        for variant in ('normal','optimized','sanitized'):
            for phase in ('compile','run'):
                label=variant+'-'+phase
                require(ordinary(output,label+'.exit-code.txt').read_text()=='0\n' and ordinary(output,label+'.stderr').read_bytes()==b'', 'metadata command failure/stderr')
            require(parse(ordinary(output,variant+'-run.stdout').read_bytes())==METADATA_EXPECTED,'metadata raw output differs')
        dump(self.evidence/'provenance/elf-metadata-bounds.json',dict(receipt,status='CAPTURED_FOR_REVIEW',source_owner=AK_COMMIT,source_tree=AK_TREE))
    def suites(self):
        for row in self.data['test_suites']:
            self.stage='suite-'+row['id'];suite=self.results/('tests-'+row['id']);suite.mkdir()
            for path,expected in row['files'].items():
                target=suite/Path(path).name;require(not target.exists(),'colliding suite filenames')
                shutil.copyfile(ordinary(self.host,path),target)
            require(all((suite/(module+'.py')).is_file() for module in row['modules']),'missing suite module')
            env=dict(os.environ,ANISETTE_KIT_TEST_SOURCE=str(self.roots.get('AnisetteKit','')),SIDE_STORE_TEST_SOURCE=str(self.roots.get('SideStore','')),SIDESIGN_TEST_SOURCE=str(self.roots.get('SideSign','')),LIVE_CONTAINER_TEST_SOURCE=str(self.roots.get('LiveContainer','')),MAINTAINED_LIVE_CONTAINER_TEST_SOURCE=str(self.roots.get('LiveContainer','')),V3_PENDING_HOST_SOURCE=str(self.roots['LiveContainer']/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift') if 'LiveContainer' in self.roots else '',PYTHONDONTWRITEBYTECODE='1')
            expected_path=suite/'expected-test-ids.json';require(not expected_path.exists(),'test suite collides with expected-ID metadata');dump(expected_path,row['expected_test_ids'])
            source_suites={'initializer-diagnostics':'init_diagnostics','adi-consumption':'adi_consumption'}
            if row['id'] in source_suites:
                require(row['owner']=='LiveContainer' and row['modules']==['test_contract'],'consumer suite identity differs')
                owner_suite=self.roots['LiveContainer']/'tests'/source_suites[row['id']]
                for path,expected in row['files'].items():
                    require(sha(ordinary(owner_suite,Path(path).name).read_bytes())==expected,'maintained consumer suite differs from sealed runner copy')
                suite=owner_suite
                env.update(ADI_CONSUMPTION_PEER_ROOT=str(self.roots['SideStore']),ADI_CONSUMPTION_PRODUCER_ROOT=str(self.roots['AnisetteKit']))
            output=self.run('suite-'+row['id'],['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-B',HERE/'run_unittest_suite.py',suite,expected_path,*row['modules']],env=env)
            result=parse(output.splitlines()[-1])
            require(set(result)=={'tests','failures','errors','skips','expected_failures','unexpected_successes','test_ids'} and result['tests']==len(row['expected_test_ids']) and sorted(result['test_ids'])==sorted(row['expected_test_ids']) and all(type(result[k]) is int and result[k]==0 for k in ('failures','errors','skips','expected_failures','unexpected_successes')),'actual suite report differs from sealed contract')
            dump(self.evidence/('provenance/suites/'+row['id']+'.json'),result)
    def sidesign(self):
        self.stage='sidesign-real-resolution';root=self.roots['SideSign'];scratch=self.results/'sidesign';lock=root/'Package.resolved';before=lock.read_bytes()
        (self.evidence/'provenance/Package.resolved.before').write_bytes(before)
        base=['swift','package','--package-path',root,'--scratch-path',scratch]
        self.run('sidesign-resolve',[*base,'resolve']);after=lock.read_bytes()
        (self.evidence/'provenance/Package.resolved.after').write_bytes(after)
        observed=self.check_lock(before,after)
        self.observed_locks['SideSign']={'Package.resolved':hashlib.sha1(b'blob '+str(len(after)).encode()+b'\0'+after).hexdigest()}
        (self.evidence/'provenance/Package.resolved.after').write_bytes(after)
        self.run('sidesign-frozen-resolve',[*base,'--force-resolved-versions','resolve']);require(lock.read_bytes()==after,'frozen resolution changed lock')
        self.resolved_ak(scratch)
        self.metadata_units()
        # Production C/Swift wrappers with host VM and I/O doubles only.
        # The linked uc_emu_start in this suite is a finite host stub, not Unicorn.
        boundary=self.run('anisette-native-boundary',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-B',self.roots['AnisetteKit']/'.ci/native-tests/run_tests.py'])
        dump(self.evidence/'provenance/anisette-native-boundary.json',verify_anisette_boundary_output(boundary))
        self.suites()
        self.stage='sidesign-compile-tests'
        self.run('sidesign-build',['swift','build','--package-path',root,'--scratch-path',scratch,'--force-resolved-versions','--build-tests','-v'])
        output=self.run('sidesign-tests',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)','swift','test','--package-path',root,'--scratch-path',scratch,'--force-resolved-versions','--skip-build','--disable-sandbox','--filter','deviceInitializationAndFiltering|certificateRequestCSRGeneration|developerPortalSingleton|archiveStoreRoundtrip|archiveDeflateRoundtrip'])
        dump(self.evidence/'provenance/sidesign-selected-tests.json',verify_sidesign_tests(output))
        require(lock.read_bytes()==after,'build/tests changed lock');self.resolved_ak(scratch)
        self.state['lock']=observed
    def prior_sidesign(self,root):
        require(root is not None,'sidestore phase requires preserved SideSign evidence directory')
        expected=self.data['prior_sidesign']
        identity=verified_prior_github_identity(self.prior_github_identity, expected)
        dump(self.evidence/'provenance/prior-github-identity.json',identity)
        require(root is not None,'sidestore phase requires preserved SideSign evidence directory')
        index_raw=ordinary(root,'evidence-index.json').read_bytes()
        require(sha(index_raw)==self.data['prior_sidesign']['index_sha256'],'prior evidence index mismatch')
        index=parse(index_raw);require(isinstance(index,dict),'malformed prior index')
        for path,h in index.items(): require(sha(ordinary(root,path).read_bytes())==digest(h),'prior evidence hash differs: '+path)
        required={'provenance/result.json','provenance/approved-inputs.json','provenance/Package.resolved.before','provenance/Package.resolved.after','provenance/elf-metadata-bounds.json','metadata-units/result.json','logs/elf-metadata-units.exit-code.txt','logs/sidesign-build.exit-code.txt','logs/sidesign-tests.exit-code.txt','logs/sidesign-tests.log','provenance/source-after.json','provenance/sidesign-selected-tests.json'}
        required.update({'provenance/anisette-native-boundary.json','logs/anisette-native-boundary.log','logs/anisette-native-boundary.exit-code.txt'})
        for variant in ('normal','optimized','sanitized'):
            required.update('metadata-units/'+variant+'-'+phase+ext for phase in ('compile','run') for ext in ('.command.json','.stdout','.stderr','.exit-code.txt'))
        require(required <= index.keys(),'incomplete prior defensive source evidence')
        result=parse((root/'provenance/result.json').read_bytes());inputs=parse((root/'provenance/approved-inputs.json').read_bytes())
        require(result.get('run',{}).get('url')=='https://github.com/NRG-Wardog/LiveContainer/actions/runs/'+str(expected['run_id']) and result.get('run',{}).get('attempt')==expected['run_attempt'] and result.get('run',{}).get('host_commit')==expected['host_commit'],'prior capture run binding differs')
        require(result.get('status')=='CAPTURED_FOR_REVIEW' and result.get('phase')=='sidesign' and result.get('source_basis')==BASIS,'old/incomplete phase receipt')
        require(all(result.get(k) is False for k in ('guest_execution','ADI_executed','device_validation','production_ready','ipa_built')),'prior receipt overclaims runtime readiness')
        require(sha((root/'provenance/approved-inputs.json').read_bytes())==result.get('approved_inputs_sha256'),'prior approved input identity differs')
        require(inputs['owners']['AnisetteKit']==self.data['owners']['AnisetteKit'],'metadata helper tested a different AK source tuple')
        for name in ('elf-metadata-units','sidesign-build','sidesign-tests'):
            require((root/('logs/'+name+'.exit-code.txt')).read_text()=='0\n','prior command failed')
        verify_sidesign_tests((root/'logs/sidesign-tests.log').read_text())
        require((root/'logs/anisette-native-boundary.exit-code.txt').read_text()=='0\n','prior host boundary failed')
        require(parse((root/'provenance/anisette-native-boundary.json').read_bytes())==verify_anisette_boundary_output((root/'logs/anisette-native-boundary.log').read_text()),'prior host boundary receipt differs')
        receipt=verify_metadata_receipt(parse((root/'metadata-units/result.json').read_bytes()))
        require(parse((root/'provenance/elf-metadata-bounds.json').read_bytes())==dict(receipt,status='CAPTURED_FOR_REVIEW',source_owner=AK_COMMIT,source_tree=AK_TREE),'prior metadata receipt differs')
        for variant in ('normal','optimized','sanitized'):
            for phase in ('compile','run'):
                label=variant+'-'+phase
                require((root/('metadata-units/'+label+'.exit-code.txt')).read_text()=='0\n' and (root/('metadata-units/'+label+'.stderr')).read_bytes()==b'','prior metadata command failed')
            require(parse((root/('metadata-units/'+variant+'-run.stdout')).read_bytes())==METADATA_EXPECTED,'prior metadata raw output differs')
        before=inputs['owners']['SideSign']['commit'];after=self.data['owners']['SideSign']['commit'];ss=self.roots['SideSign']
        delta=snapshot(ss,before,after)['changes']
        require(set(delta)<= {'Package.resolved'},'SideSign runtime changed after native test')
        captured=(root/'provenance/Package.resolved.after').read_bytes()
        require((ss/'Package.resolved').read_bytes()==captured,'SideSign final lock is not observed output')
        self.check_lock(captured,captured)
        dump(self.evidence/'provenance/prior-sidesign-link.json',{'index_sha256':sha(index_raw),'tested_commit':before,'final_commit':after,'lock_only_descendant':True,'host_metadata_units_reused_for_exact_unchanged_AK':True,'guest_execution':False,'prior_run':result['run']})
    def sidestore(self,prior):
        self.prior_sidesign(prior);self.suites();self.stage='contracts'
        c=self.data['contracts']
        self.run('p0-contracts',[sys.executable,'-B',ordinary(self.host,c['validator']),'--registry',ordinary(self.host,c['registry']),'--registry-sha256',c['registry_sha256'],*[a for name,root in self.roots.items() for a in ('--owner',name+'='+str(root))]])
        self.stage='transport-build';idevice=self.roots['idevice'];m=self.roots['minimuxer'];cargo=self.results/'cargo-target'
        self.run('rust-target',['rustup','target','add','aarch64-apple-ios'])
        bindgen=self.run('bindgen-version',['bindgen','--version']).strip();require(bindgen=='bindgen 0.72.1','preinstall reviewed bindgen-cli 0.72.1')
        env=dict(os.environ,CARGO_TARGET_DIR=str(cargo),IPHONEOS_DEPLOYMENT_TARGET='15.0',BINDGEN_EXTRA_CLANG_ARGS='--sysroot='+self.run('iphoneos-sdk-path',['xcrun','--sdk','iphoneos','--show-sdk-path']).strip())
        self.run('idevice-fetch',['cargo','fetch','--locked','--manifest-path',idevice/'ffi/Cargo.toml'],env=env)
        self.run('idevice-build',['cargo','build','--frozen','--release','--target','aarch64-apple-ios','--features','obfuscate','--manifest-path',idevice/'ffi/Cargo.toml','--verbose'],env=env)
        lib=cargo/'aarch64-apple-ios/release/libidevice_ffi.a';require(lib.is_file(),'transport library absent')
        shutil.copyfile(idevice/'ffi/idevice.h',idevice/'swift/include/idevice.h')
        xc=idevice/'swift/IDevice.xcframework'
        self.run('idevice-xcframework',['xcodebuild','-create-xcframework','-library',lib,'-headers',idevice/'swift/include','-output',xc])
        (m/'DeviceGateway/LocalBinary').mkdir(parents=True,exist_ok=True)
        shutil.copytree(xc,m/'DeviceGateway/LocalBinary/IDevice.xcframework')
        framework={str(p.relative_to(xc)):sha(p.read_bytes()) for p in xc.rglob('*') if p.is_file()}
        for path,h in framework.items(): require(sha((m/'DeviceGateway/LocalBinary/IDevice.xcframework'/path).read_bytes())==h,'staged transport differs')
        dump(self.evidence/'provenance/transport.json',{'archive_sha256':sha(lib.read_bytes()),'xcframework':framework})
        self.stage='sidestore-real-resolution';ss=self.roots['SideStore'];lock=ss/LOCK;before=lock.read_bytes();packages=self.results/'sidestore-packages'
        (self.evidence/'provenance/Package.resolved.before').write_bytes(before)
        base=['-project',ss/'AltStore.xcodeproj','-scheme','SideStore','-clonedSourcePackagesDirPath',packages,'-derivedDataPath',self.results/'sidestore-derived','-disablePackageRepositoryCache']
        self.run('sidestore-resolve',['xcodebuild','-resolvePackageDependencies',*base]);after=lock.read_bytes()
        (self.evidence/'provenance/Package.resolved.after').write_bytes(after)
        observed=self.check_lock(before,after)
        self.observed_locks['SideStore']={LOCK:hashlib.sha1(b'blob '+str(len(after)).encode()+b'\0'+after).hexdigest()}
        (self.evidence/'provenance/Package.resolved.after').write_bytes(after)
        self.run('sidestore-frozen-resolve',['xcodebuild','-resolvePackageDependencies',*base,'-onlyUsePackageVersionsFromResolvedFile']);require(lock.read_bytes()==after,'frozen Xcode resolution changed lock')
        self.resolved_ak(packages)
        dump(self.evidence/'provenance/source-after-resolution.json',self.source_proof(True))
        self.stage='unsigned-iphoneos-build'
        settings=['-sdk','iphoneos','-configuration','Release','-destination','generic/platform=iOS','CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','CODE_SIGN_IDENTITY=','DEVELOPMENT_TEAM=','build']
        self.run('sidestore-build',['xcodebuild',*base,'-onlyUsePackageVersionsFromResolvedFile','-disableAutomaticPackageResolution',*settings])
        self.run('livecontainer-build',['xcodebuild','-project',self.roots['LiveContainer']/'LiveContainer.xcodeproj','-scheme','LiveContainer','-derivedDataPath',self.results/'livecontainer-derived',*settings])
        require(lock.read_bytes()==after,'native builds changed app lock');self.resolved_ak(packages)
        for path,h in framework.items(): require(sha((m/'DeviceGateway/LocalBinary/IDevice.xcframework'/path).read_bytes())==h,'transport changed during native build')
        binaries={}
        for owner,folder in [('SideStore','sidestore-derived'),('LiveContainer','livecontainer-derived')]:
            app=self.results/folder/'Build/Products/Release-iphoneos'/ (owner+'.app')
            require(app.is_dir(),owner+' unsigned app absent')
            binaries[owner]={str(p.relative_to(app)):sha(p.read_bytes()) for p in app.rglob('*') if p.is_file() and not p.is_symlink()}
        dump(self.evidence/'provenance/unsigned-products.json',binaries);self.state['lock']=observed
    def execute(self,prior):
        require(self.data['phase'] in ('sidesign','sidestore'),'allocation capture requires the dedicated Linux gate')
        require(platform.system()=='Darwin','native execution requires actual macOS; never substitute Linux receipts')
        require(not self.work.exists() and not self.evidence.exists(),'fresh work/evidence directories required')
        self.sources.mkdir(parents=True);self.results.mkdir();(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        # Runner identity cannot be passed as an invented input.
        repo=os.environ.get('GITHUB_REPOSITORY');full_sha(os.environ.get('GITHUB_SHA'))
        run_id=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(repo=='NRG-Wardog/LiveContainer' and run_id.isdigit() and attempt.isdigit() and int(attempt)>0,'actual GitHub validation run identity required')
        require(git(self.host,'rev-parse','HEAD').decode().strip()==os.environ['GITHUB_SHA'],'validation host checkout differs from runner SHA')
        require(os.environ.get('GITHUB_REF')=='refs/heads/validation/p0-cxx-allocation','isolated validation branch required')
        self.state.update(historical_basis=self.data['historical_basis'],approved_inputs_sha256=self.approved,owners=self.data['owners'],run={'url':'https://github.com/'+repo+'/actions/runs/'+run_id,'attempt':int(attempt),'host_commit':os.environ['GITHUB_SHA'],'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()})
        try:
            self.stage='toolchain'
            xcode=self.run('xcode-version',['xcodebuild','-version']);require('Xcode 26.4.1' in xcode,'unreviewed Xcode version')
            self.run('swift-version',['swift','--version']);self.run('clang-version',['xcrun','clang++','--version'])
            self.run('network-sandbox',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-c','import socket; s=socket.socket();\ntry: s.connect(("1.1.1.1",443))\nexcept OSError: pass\nelse: raise SystemExit("network sandbox did not deny")'])
            self.acquire()
            if self.data['phase']=='sidesign': self.sidesign()
            else: self.sidestore(prior)
            dump(self.evidence/'provenance/source-after.json',self.source_proof(True))
            self.stage='captured';self.state['status']='CAPTURED_FOR_REVIEW'
        except Exception as error:
            self.state['primary_error']=type(error).__name__+': '+str(error)
            raise
        finally:
            settled=all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in self.command_quiescence)
            self.state['writers_quiescent']=settled
            self.state['last_stage']=self.stage
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            retention_errors=[]
            if settled:
                try:self.retain_available_locks()
                except Exception as error:retention_errors.append('lock retention: '+type(error).__name__)
            else:retention_errors.append('evidence index withheld: unsettled or unknown command writers')
            self.state['retention_errors']=retention_errors
            if retention_errors and settled:self.state['status']='FAILED_RETENTION'
            dump(self.evidence/'provenance/result.json',self.state)
            dump(self.evidence/'provenance/owned-command-groups.json',self.command_quiescence)
            (self.evidence/'provenance/approved-inputs.json').write_bytes(self.input_bytes)
            # Never authenticate a capture while unknown descendants may write it.
            if settled and not retention_errors:
                index={str(p.relative_to(self.evidence)):sha(p.read_bytes()) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}
                dump(self.evidence/'evidence-index.json',index)

def verify_transport(root):
    require(root is not None,'evidence path required')
    result=parse(ordinary(root,'provenance/result.json').read_bytes())
    require(result.get('writers_quiescent') is True and result.get('retention_errors')==[],'evidence writers unsettled or retention incomplete')
    groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(isinstance(groups,list) and all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in groups),'owned command writer receipt incomplete')
    index=parse(ordinary(root,'evidence-index.json').read_bytes())
    require(isinstance(index,dict) and {'provenance/result.json','provenance/owned-command-groups.json'}<=set(index),'evidence index incomplete')
    observed={}
    for path in root.rglob('*'):
        require(not path.is_symlink(),'linked evidence path')
        if path.is_file() and path.name!='evidence-index.json':
            relative=str(path.relative_to(root));observed[relative]=sha(ordinary(root,relative).read_bytes())
    require(index==observed,'evidence changed before transport')
    return {'status':'QUIESCENT_INDEX_VERIFIED','indexed_files':len(index)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True)
    p.add_argument('--host-root',type=Path,default=HERE.parents[1]);p.add_argument('--work',type=Path)
    p.add_argument('--evidence',type=Path);p.add_argument('--prior-sidesign-evidence',type=Path)
    p.add_argument('--prior-github-identity',type=Path)
    p.add_argument('--prior-archive',type=Path);p.add_argument('--unpack-prior-to',type=Path)
    p.add_argument('--check-transport',action='store_true',help='Read-only evidence quiescence/index check before artifact upload')
    p.add_argument('--execute',action='store_true',help='Explicitly execute macOS native capture, never publish or approve it')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.approved_inputs_sha256,a.host_root)
        if a.check_transport:
            require(not a.execute and a.evidence is not None,'transport check requires evidence and forbids execution')
            print(json.dumps(verify_transport(a.evidence)));return
        if a.prior_archive is not None or a.unpack_prior_to is not None:
            require(not a.execute and a.prior_archive is not None and a.unpack_prior_to is not None and data['phase']=='sidestore','prior extraction needs both paths and sidestore inputs')
            require(not a.unpack_prior_to.exists() and not a.unpack_prior_to.is_symlink(),'prior output must be fresh')
            require(sha(a.prior_archive.read_bytes())==data['prior_sidesign']['artifact_sha256'],'downloaded prior artifact digest mismatch')
            with zipfile.ZipFile(a.prior_archive) as archive:
                for info in archive.infolist():
                    require(not info.filename.startswith('/') and '..' not in Path(info.filename).parts and ((info.external_attr>>16)&0o170000)!=0o120000,'unsafe prior artifact entry')
                archive.extractall(a.unpack_prior_to)
            print(json.dumps({'status':'PRIOR_ARTIFACT_BYTES_VERIFIED','native_execution':False}));return
        if not a.execute:
            print(json.dumps({'status':'SEALED_INPUTS_VALID','native_execution':False,'production_ready':False,'phase':data['phase']}));return
        require(a.work is not None and a.evidence is not None,'fresh --work and --evidence required')
        gate=Gate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256);gate.input_bytes=raw;gate.prior_github_identity=a.prior_github_identity;gate.execute(a.prior_sidesign_evidence)
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as error: p.exit(2,'BLOCKED: '+str(error)+'\n')

if __name__=='__main__': main()
