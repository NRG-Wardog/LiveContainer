#!/usr/bin/env python3
"""Separate P0 capture gate. Requires sealed actual inputs; never grants readiness.

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
import subprocess
import sys
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prepare_candidate_inventory import BASES, BASELINE, LOCK, entries, full_sha, git, snapshot, unique, require
import source_primitives as primitives

BASIS = 'p0-constructor-diagnostics-v1'
FORK_URL = 'https://github.com/mahee96/unicorn/releases/download/2.1.4-multiarch/Unicorn.xcframework.zip'
FORK_SHA = '4f61907db6aafc56fb3e336b524d742342312f498bb40739f1da55fb4a24614a'
# Filled only from the independently reviewed diagnostic owner source manifest.
AK_FILES = {'.ci/native-tests/CONSTRUCTOR_DIAGNOSTICS.md': '09621ed49485a11bed5f10645012afd03c1e88aacee677edb9c4859a05a5c76c', '.ci/native-tests/README.md': '47136a886873602382791feeb8090a1666139711479a0df50e739fe6c213e2c1', '.ci/native-tests/fixtures/constructor_diagnostics.cpp': 'c9e1018a438679080a38d1c2c8feeefbc66e3f3f4bc84347f97059b5aeca40b1', '.ci/native-tests/fixtures/isolated_anisette_core_harness.cpp': 'd80a994d24446f9cba39b0c46936ac050c0a0f1d503294293f45ed8cdd9e3c12', '.ci/native-tests/fixtures/isolated_anisette_loader_harness.cpp': '053efa1197760643af52976e868287ad83508195ddf75629add99b83ca7c0347', '.ci/native-tests/fixtures/isolated_anisette_vm_double.h': 'b749e0bfef24f37927d92d551ac6ab475aef2ac1769d0a20361d08b950f70641', '.ci/native-tests/run_tests.py': '3728a41f67529f1c73222739008cba2c2d4ad4e1a818184f8103cac602e80014', '.ci/native-tests/test_constructor_diagnostics.py': '62e9c5585d4846aa114975b33af1c06abc79fd1f86421824e1dfb329ab1a981b', '.ci/native-tests/test_constructor_diagnostics_driver.py': '1301567d4036731ff328898043601ff74f2acebb3f1c55847fc5ddfa2100c09c', 'Native/Loader/elf_loader_emulator.cpp': '661a28cab7bf0258e388be2ff8cba98c869f202791699d6697c0f8277971e2db', 'Native/Loader/elf_loader_emulator.h': '67e4ebfa530d39451169bae486facc57926a8e78a6cd833a6425628c457d5267', 'Native/Loader/vm_initialization_diagnostics.h': '023b34540c9fb31fcb6059fea3236eb411fc52d0438025dbe9d72e88c9337e5c', 'Native/anisette_core_uc.cpp': '5251cf75e1944be12d7e8bc72de2a9ab6d9e3438671251e2a0918751d91b3a76'}

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
    require(set(data)=={'schema_version','source_basis','integration_baseline','phase','owners','adapter_files','contracts','test_suites','prior_sidesign','submodules'},'unexpected P0 input schema')
    require(data['schema_version']==1 and data['source_basis']==BASIS and data['integration_baseline']==BASELINE,'unsupported P0 source basis')
    require(data['phase'] in ('sidesign','sidestore'),'unsupported phase')
    expected={'AnisetteKit','SideSign'} if data['phase']=='sidesign' else set(BASES)
    require(set(data['owners'])==expected,'exact phase owner graph required')
    for name, row in data['owners'].items():
        require(set(row)=={'repository','commit','tree','changes'},'unexpected owner schema')
        require(row['repository']=='https://github.com/NRG-Wardog/'+name+'.git','unexpected repository')
        full_sha(row['commit']);full_sha(row['tree'])
        require(isinstance(row['changes'],dict),'full source delta required')
        if name in ('minimuxer','idevice','jktcp'):
            require(row['commit']==BASES[name] and row['changes']=={},'unrelated transport drift')
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
    changes=data['owners']['AnisetteKit']['changes']
    require(AK_FILES and set(changes)==set(AK_FILES),'AK candidate must contain the exact reviewed diagnostic delta')
    for path, expected_hash in AK_FILES.items():
        require(changes[path]['after']['sha256']==expected_hash,'AK candidate source differs: '+path)
    require(set(data['adapter_files'])=={'ci/p0init/native_gate.py','ci/p0init/prepare_candidate_inventory.py','ci/p0init/run_unittest_suite.py','ci/p0init/source_primitives.py'},'exact adapter inventory required')
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

def verify_native83_output(text):
    require(not re.search(r'(?:runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|LeakSanitizer)',text,re.I),'sanitizer diagnostic in canonical native fixture')
    require(text=='PASS 83 full-production-loader synthetic checks; no ADI executed\n','canonical 83-check stdout differs')

CONSTRUCTOR_CASE_IDS = ['normal_nonzero_w0', 'normal_error_shaped_w0', 'protected_access', 'unsupported_interrupt', 'abnormal_stop', 'dt_init_failure', 'dt_init_array_first_failure', 'dt_init_array_second_failure', 'array_entry_read_first', 'array_entry_read_second', 'invalid_vm', 'poisoned_vm', 'caller_snapshot_independence', 'serialization_bounds', 'serialization_privacy']

def verify_constructor_output(text):
    require(not re.search(r'(?:runtime error:|AddressSanitizer|UndefinedBehaviorSanitizer|LeakSanitizer)',text,re.I),'sanitizer diagnostic in constructor fixture')
    result = parse(text)
    require(set(result)=={'schema','checks','failures','skipped','case_ids','ADI_executed','device_validation'},'constructor diagnostic report schema differs')
    require(type(result['schema']) is int and result['schema']==1 and type(result['checks']) is int and result['checks']==2105 and type(result['failures']) is int and result['failures']==0 and type(result['skipped']) is int and result['skipped']==0,'constructor fixture failed or skipped')
    require(result['case_ids']==CONSTRUCTOR_CASE_IDS,'exact constructor diagnostic cases required')
    require(result['ADI_executed'] is False and result['device_validation'] is False,'synthetic constructor fixture cannot claim device/ADI validation')
    return result

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

class Gate:
    def __init__(self,data,host,work,evidence,approved):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved
        self.sources=work/'sources';self.results=work/'results';self.roots={};self.children={};self.observed_locks={};self.stage='initialization'
        self.state={'status':'FAILED_OR_INCOMPLETE','source_basis':BASIS,'phase':data['phase'],'production_ready':False,'ipa_built':False,'ADI_executed':False,'device_validation':False}
    def run(self,name,args,*,cwd=None,env=None,strict_stderr=False):
        require(re.fullmatch('[a-z0-9_-]+',name),'unsafe log name')
        env=command_environment(name,args,env)
        if str(args[0])=='git':args=['git','--no-replace-objects','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*args[1:]]
        log=self.evidence/'logs'/name;require(not log.with_suffix('.log').exists(),'duplicate execution ID: '+name)
        dump(log.with_suffix('.command.json'),{'argv':[str(a) for a in args],'cwd':str(cwd) if cwd else None})
        with log.with_suffix('.log').open('wb') as output:
            process=subprocess.run([str(a) for a in args],cwd=cwd,env=env,stdout=output,stderr=subprocess.PIPE if strict_stderr else subprocess.STDOUT,timeout=7200)
        if strict_stderr:log.with_suffix('.stderr.log').write_bytes(process.stderr or b'')
        log.with_suffix('.exit-code.txt').write_text(str(process.returncode)+'\n')
        require(process.returncode==0,'command failed: '+name+' (see captured log)')
        require(not strict_stderr or not process.stderr,'unexpected runtime stderr: '+name)
        return log.with_suffix('.log').read_text(errors='replace')
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
        ak=self.data['owners']['AnisetteKit']['commit'];manifest=(self.roots['SideSign']/'Package.swift').read_text()
        require(re.search(r'\.package\(url:\s*"https://github.com/NRG-Wardog/AnisetteKit.git",\s*revision:\s*"'+ak+r'"\)',manifest),'SideSign manifest candidate pin differs')
        package=(self.roots['AnisetteKit']/'Package.swift').read_text()
        require(FORK_URL+'#AnisetteKit' in package and FORK_SHA in package,'actual app engine source/checksum changed')
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
    def native83(self):
        self.stage='canonical-native-fork83'
        archive=self.results/'Unicorn.xcframework.zip'
        with urllib.request.urlopen(FORK_URL,timeout=180) as response,archive.open('wb') as output: shutil.copyfileobj(response,output)
        require(sha(archive.read_bytes())==FORK_SHA,'Unicorn archive checksum mismatch')
        # Known hash is necessary, but still reject archive traversal before ditto.
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                require(not entry.filename.startswith('/') and '..' not in Path(entry.filename).parts,'unsafe engine archive path')
        extracted=self.results/'unicorn';extracted.mkdir()
        self.run('unicorn-extract',['ditto','-x','-k',archive,extracted])
        xcs=list(extracted.rglob('Unicorn.xcframework'));require(len(xcs)==1,'ambiguous engine xcframework')
        xc=xcs[0];info=plistlib.loads((xc/'Info.plist').read_bytes());arch=platform.machine()
        slices=[x for x in info['AvailableLibraries'] if x.get('SupportedPlatform')=='macos' and arch in x.get('SupportedArchitectures',[]) and not x.get('SupportedPlatformVariant')]
        require(len(slices)==1,'exact host architecture macOS fork slice unavailable')
        selected=slices[0];base=xc/selected['LibraryIdentifier'];library=base/selected['LibraryPath']
        if library.suffix=='.framework':
            binary=library/library.stem;headers=library/'Headers';link=[str(binary),'-Wl,-rpath,'+str(base)]
        else:
            binary=library;headers=base/selected['HeadersPath'];link=[str(binary)]
        require(binary.is_file() and headers.is_dir(),'engine library/headers absent')
        ak=self.roots['AnisetteKit'];exe=self.results/'native-fork83'
        args=['xcrun','clang++','-std=c++17','-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined','-fno-sanitize-recover=all']
        args+=['-I'+str(p) for p in (headers,ak/'Native',ak/'Native/include',ak/'Native/Loader')]
        args+=[ak/'Native/Loader/elf_loader_emulator.cpp',ak/'.ci/native-tests/fixtures/android_tls_constructor.cpp',*link,'-o',exe]
        self.run('native-fork83-compile',args)
        stdout=self.run('native-fork83-run',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',exe],env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1',ASAN_OPTIONS='halt_on_error=1'),strict_stderr=True)
        verify_native83_output(stdout)
        dump(self.evidence/'provenance/native-fork83.json',{'status':'CAPTURED_FOR_REVIEW','checks':83,'ADI_executed':False,'ios_execution':False,'source_sha256':AK_FILES,'archive_url':FORK_URL,'archive_sha256':FORK_SHA,'slice':selected,'library_sha256':sha(binary.read_bytes()),'header_sha256':{str(p.relative_to(headers)):sha(p.read_bytes()) for p in headers.rglob('*') if p.is_file()},'sanitizers':['address','undefined'],'host_arch':arch})
        self.constructor_diagnostics(headers,link,binary)
    def constructor_diagnostics(self, headers, link, binary):
        self.stage='constructor-diagnostics'
        ak=self.roots['AnisetteKit'];exe=self.results/'constructor-diagnostics'
        args=['xcrun','clang++','-std=c++17','-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined','-fno-sanitize-recover=all']
        args+=['-I'+str(p) for p in (headers,ak/'Native',ak/'Native/include',ak/'Native/Loader')]
        args+=[ak/'Native/Loader/elf_loader_emulator.cpp',ak/'.ci/native-tests/fixtures/constructor_diagnostics.cpp',*link,'-o',exe]
        self.run('constructor-diagnostics-compile',args)
        stdout=self.run('constructor-diagnostics-run',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',exe],env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1',ASAN_OPTIONS='halt_on_error=1'),strict_stderr=True)
        result=verify_constructor_output(stdout)
        dump(self.evidence/'provenance/constructor-diagnostics.json',dict(result,status='CAPTURED_FOR_REVIEW',source_owner=self.data['owners']['AnisetteKit']['commit'],source_sha256=AK_FILES,engine_archive_sha256=FORK_SHA,library_sha256=sha(binary.read_bytes()),sanitizers=['address','undefined']))
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
        self.run('sidesign-resolve',[*base,'resolve']);after=lock.read_bytes();observed=self.check_lock(before,after)
        self.observed_locks['SideSign']={'Package.resolved':hashlib.sha1(b'blob '+str(len(after)).encode()+b'\0'+after).hexdigest()}
        (self.evidence/'provenance/Package.resolved.after').write_bytes(after)
        self.run('sidesign-frozen-resolve',[*base,'--force-resolved-versions','resolve']);require(lock.read_bytes()==after,'frozen resolution changed lock')
        self.resolved_ak(scratch)
        self.native83()
        self.run('constructor-driver-tests',['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)',sys.executable,'-B',self.roots['AnisetteKit']/'.ci/native-tests/test_constructor_diagnostics_driver.py'])
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
        required={'provenance/result.json','provenance/approved-inputs.json','provenance/Package.resolved.after','provenance/native-fork83.json','logs/native-fork83-run.log','logs/native-fork83-run.stderr.log','logs/native-fork83-run.exit-code.txt','logs/sidesign-build.exit-code.txt','logs/sidesign-tests.exit-code.txt','logs/sidesign-tests.log','provenance/source-after.json','provenance/sidesign-selected-tests.json'}
        required.update({'provenance/anisette-native-boundary.json','logs/anisette-native-boundary.log','logs/anisette-native-boundary.exit-code.txt','provenance/constructor-diagnostics.json','logs/constructor-diagnostics-run.log','logs/constructor-diagnostics-run.stderr.log','logs/constructor-diagnostics-run.exit-code.txt'})
        require(required <= index.keys(),'incomplete prior native evidence')
        result=parse((root/'provenance/result.json').read_bytes());inputs=parse((root/'provenance/approved-inputs.json').read_bytes())
        require(result.get('run',{}).get('url')=='https://github.com/NRG-Wardog/LiveContainer/actions/runs/'+str(expected['run_id']) and result.get('run',{}).get('attempt')==expected['run_attempt'] and result.get('run',{}).get('host_commit')==expected['host_commit'],'prior capture run binding differs')
        require(result.get('status')=='CAPTURED_FOR_REVIEW' and result.get('phase')=='sidesign' and result.get('source_basis')==BASIS,'old/incomplete phase receipt')
        require(sha((root/'provenance/approved-inputs.json').read_bytes())==result.get('approved_inputs_sha256'),'prior approved input identity differs')
        require(inputs['owners']['AnisetteKit']==self.data['owners']['AnisetteKit'],'native83 tested a different AK source tuple')
        for name in ('native-fork83-run','sidesign-build','sidesign-tests'):
            require((root/('logs/'+name+'.exit-code.txt')).read_text()=='0\n','prior command failed')
        verify_sidesign_tests((root/'logs/sidesign-tests.log').read_text())
        native=parse((root/'provenance/native-fork83.json').read_bytes())
        require((root/'logs/native-fork83-run.stderr.log').read_bytes()==b'','prior native83 stderr was not empty')
        verify_native83_output((root/'logs/native-fork83-run.log').read_text())
        require(native.get('checks')==83 and native.get('archive_sha256')==FORK_SHA and native.get('source_sha256')==AK_FILES,'prior canonical fork evidence differs')
        require((root/'logs/constructor-diagnostics-run.exit-code.txt').read_text()=='0\n' and (root/'logs/constructor-diagnostics-run.stderr.log').read_bytes()==b'','prior constructor diagnostic execution failed')
        constructor=verify_constructor_output((root/'logs/constructor-diagnostics-run.log').read_text())
        observed=parse((root/'provenance/constructor-diagnostics.json').read_bytes())
        require(all(observed.get(k)==v for k,v in constructor.items()) and observed.get('source_owner')==self.data['owners']['AnisetteKit']['commit'] and observed.get('source_sha256')==AK_FILES and observed.get('engine_archive_sha256')==FORK_SHA,'prior constructor diagnostic source/engine differs')
        require((root/'logs/anisette-native-boundary.exit-code.txt').read_text()=='0\n','prior native boundary execution failed')
        require(parse((root/'provenance/anisette-native-boundary.json').read_bytes())==verify_anisette_boundary_output((root/'logs/anisette-native-boundary.log').read_text()),'prior native boundary report differs')
        before=inputs['owners']['SideSign']['commit'];after=self.data['owners']['SideSign']['commit'];ss=self.roots['SideSign']
        delta=snapshot(ss,before,after)['changes']
        require(set(delta)<= {'Package.resolved'},'SideSign runtime changed after native test')
        captured=(root/'provenance/Package.resolved.after').read_bytes()
        require((ss/'Package.resolved').read_bytes()==captured,'SideSign final lock is not observed output')
        self.check_lock(captured,captured)
        dump(self.evidence/'provenance/prior-sidesign-link.json',{'index_sha256':sha(index_raw),'tested_commit':before,'final_commit':after,'lock_only_descendant':True,'native83_reused_for_exact_unchanged_AK':True,'prior_run':result['run']})
    def sidestore(self,prior):
        self.prior_sidesign(prior);self.suites();self.stage='contracts'
        c=self.data['contracts']
        self.run('p0-contracts',[sys.executable,'-B',ordinary(self.host,c['validator']),'--registry',ordinary(self.host,c['registry']),'--registry-sha256',c['registry_sha256'],*[a for name,root in self.roots.items() for a in ('--owner',name+'='+str(root))]])
        self.stage='transport-build';idevice=self.roots['idevice'];m=self.roots['minimuxer'];cargo=self.results/'cargo-target'
        self.run('rust-target',['rustup','target','add','aarch64-apple-ios'])
        bindgen=subprocess.check_output(['bindgen','--version'],text=True).strip();require(bindgen=='bindgen 0.72.1','preinstall reviewed bindgen-cli 0.72.1')
        env=dict(os.environ,CARGO_TARGET_DIR=str(cargo),IPHONEOS_DEPLOYMENT_TARGET='15.0',BINDGEN_EXTRA_CLANG_ARGS='--sysroot='+subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip())
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
        self.run('sidestore-resolve',['xcodebuild','-resolvePackageDependencies',*base]);after=lock.read_bytes();observed=self.check_lock(before,after)
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
        require(platform.system()=='Darwin','native execution requires actual macOS; never substitute Linux receipts')
        require(not self.work.exists() and not self.evidence.exists(),'fresh work/evidence directories required')
        self.sources.mkdir(parents=True);self.results.mkdir();(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        # Runner identity cannot be passed as an invented input.
        repo=os.environ.get('GITHUB_REPOSITORY');full_sha(os.environ.get('GITHUB_SHA'))
        run_id=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(repo=='NRG-Wardog/LiveContainer' and run_id.isdigit() and attempt.isdigit() and int(attempt)>0,'actual GitHub validation run identity required')
        require(git(self.host,'rev-parse','HEAD').decode().strip()==os.environ['GITHUB_SHA'],'validation host checkout differs from runner SHA')
        self.state.update(approved_inputs_sha256=self.approved,owners=self.data['owners'],run={'url':'https://github.com/'+repo+'/actions/runs/'+run_id,'attempt':int(attempt),'host_commit':os.environ['GITHUB_SHA'],'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()})
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
        finally:
            self.state['last_stage']=self.stage;dump(self.evidence/'provenance/result.json',self.state)
            # Include exact approved bytes, not reserialized input bytes.
            (self.evidence/'provenance/approved-inputs.json').write_bytes(self.input_bytes)
            index={str(p.relative_to(self.evidence)):sha(p.read_bytes()) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}
            dump(self.evidence/'evidence-index.json',index)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True)
    p.add_argument('--host-root',type=Path,default=HERE.parents[1]);p.add_argument('--work',type=Path)
    p.add_argument('--evidence',type=Path);p.add_argument('--prior-sidesign-evidence',type=Path)
    p.add_argument('--prior-github-identity',type=Path)
    p.add_argument('--prior-archive',type=Path);p.add_argument('--unpack-prior-to',type=Path)
    p.add_argument('--execute',action='store_true',help='Explicitly execute macOS native capture, never publish or approve it')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.approved_inputs_sha256,a.host_root)
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
