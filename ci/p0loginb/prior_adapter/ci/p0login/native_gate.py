#!/usr/bin/env python3
"""Fresh P0 login Phase A capture only. Never publishes, runs guests or grants readiness."""
import argparse, hashlib, json, os, platform, re, shutil, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import source_primitives as primitives
from inventory import *
from lifecycle import CommandRunner
HERE=Path(__file__).resolve().parent
SANDBOX=['/usr/bin/sandbox-exec','-p','(version 1) (allow default) (deny network*)']
AK_METHODS=('testErrorMetadataNeverIncludesProviderStrings','testTerminalEventIsExactlyOnceAndDurationIsMonotonicBounded','testBoundsRetainFinalFailureAndMarkLoss','testNativeTimingIsStrictAndAtomic','testIndependentTaskLocalScopesDoNotBleed','testWrappersPreserveSuccessAndError')
SS_METHODS=('deviceInitializationAndFiltering','certificateRequestCSRGeneration','developerPortalSingleton','archiveStoreRoundtrip','archiveDeflateRoundtrip')
AK_IDS=tuple('AnisetteKitTests.LoginDiagnosticTraceTests/'+x for x in AK_METHODS)
SS_IDS=tuple('SideSignTests.SideSignTests/'+x+'()' for x in SS_METHODS)
AK_FILTER=r'^AnisetteKitTests\.LoginDiagnosticTraceTests/('+'|'.join(AK_METHODS)+r')$'
SS_FILTER=r'^SideSignTests\.SideSignTests/('+'|'.join(SS_METHODS)+r')\(\)(/|$)'

def check_lock(before,after,commit):
    old,new=parse(before),parse(after)
    op,np=primitives.pin_map(old),primitives.pin_map(new)
    require(op.keys()==np.keys() and 'anisettekit' in np,'package set drift')
    for name in op:
        if name!='anisettekit':require(op[name]==np[name],'unrelated pin drift: '+name)
    require(np['anisettekit']=={'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':commit}},'exact AnisetteKit pin required')
    require({k:v for k,v in old.items() if k not in ('pins','originHash')}=={k:v for k,v in new.items() if k not in ('pins','originHash')},'lock schema drift')
    require(isinstance(new.get('originHash'),str) and re.fullmatch('[0-9a-f]{64}',new['originHash']),'genuine SwiftPM originHash required')
    return {'sha256':sha(after),'originHash':new['originHash']}

def verify_swift_version(stdout,stderr):
    require(stdout==TOOLCHAIN['swift_stdout'],'reviewed Swift stdout version mismatch')
    require(stderr==TOOLCHAIN['swift_stderr'],'reviewed Swift driver stderr version mismatch')

def verify_discovery(text,expected):
    lines=[x for x in text.splitlines() if x.strip()]
    require(len(lines)==len(expected) and set(lines)==set(expected),'complete discovery differs; never widen a zero-test filter')
    return sorted(lines)

def verify_swift_tests(text,owner):
    require('unicornAnisetteProvisioningAndHeaders' not in text,'unsafe test appeared in execution')
    require(not any(canary in text for canary in ('account@example.invalid','TOKEN-CANARY','PASSWORD-CANARY','BLOB-CANARY','SECRET','ORIGINAL')),'sensitive fixture appeared in successful runtime stdout/stderr')
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    require(not re.search(r'(?:Test (?:Case )?.*\b(?:failed|skipped|cancelled|canceled)\b|\b[1-9][0-9]* (?:tests? )?(?:failed|skipped|cancelled|canceled)\b)',text,re.I),'test failure/skip/cancellation observed')
    if owner=='SideSign':
        suites=re.findall(r'Suite "([^"]+)" (started|passed)',text)
        require(suites==[('SideSign Core Tests','started'),('SideSign Core Tests','passed')],'exact Swift Testing suite required')
        runtime_events=re.findall(r'\bTest (?!run\b)(.+?) (started|passed after)',text)
        require(len(runtime_events)==10 and all(name in {method+'()' for method in SS_METHODS} for name,event in runtime_events),'unrecognized Swift Testing event')
        started=re.findall(r'Test ([A-Za-z0-9_]+)\(\) started',text)
        passed=re.findall(r'Test ([A-Za-z0-9_]+)\(\) passed after',text)
        summaries=re.findall(r'Test run with (\d+) tests(?: in \d+ suites?)? passed after',text)
        require(set(started)==set(passed)==set(SS_METHODS) and len(started)==len(passed)==5 and summaries==['5'],'exact five Swift Testing cases required')
        require('Test Case ' not in text,'unexpected XCTest execution')
        return {'test_ids':sorted(SS_IDS),'executed':5,'failed':0,'skipped':0}
    events=re.findall(r"Test Case '([^']+)' (started|passed)",text)
    require(text.count('Test Case ')==len(events),'unrecognized XCTest event')
    def canonical(value):
        match=re.fullmatch(r'-\[AnisetteKitTests\.LoginDiagnosticTraceTests (test[A-Za-z0-9_]+)\]',value)
        if match:return match.group(1)
        match=re.fullmatch(r'(?:AnisetteKitTests\.)?LoginDiagnosticTraceTests\.(test[A-Za-z0-9_]+)',value)
        require(match is not None,'unexpected XCTest identity')
        return match.group(1)
    starts=[canonical(n) for n,state in events if state=='started'];passed=[canonical(n) for n,state in events if state=='passed']
    require(set(starts)==set(passed)==set(AK_METHODS) and len(starts)==len(passed)==6,'exact six XCTest cases required')
    summaries=re.findall(r'Executed (\d+) tests?, with (\d+) failures? \((\d+) unexpected\)',text)
    require(summaries and all(x==('6','0','0') for x in summaries),'XCTest completion summary mismatch')
    require('Test run' not in text and 'Testing Library' not in text,'Swift Testing must be disabled for AnisetteKit')
    return {'test_ids':sorted(AK_IDS),'executed':6,'failed':0,'skipped':0}

SUITE_SELECTORS=('SIDE_STORE_TEST_SOURCE','LIVE_CONTAINER_TEST_SOURCE','MAINTAINED_LIVE_CONTAINER_TEST_SOURCE','ANISETTE_KIT_TEST_SOURCE')
SUITE_PREFIXES=('LOGIN_TRACE','INIT_DIAGNOSTICS','ADI_CONSUMPTION')
def suite_environment(owner,roots,nested,base=None):
    env=dict(os.environ if base is None else base)
    for key in (*SUITE_SELECTORS,*(p+s for p in SUITE_PREFIXES for s in ('_PEER_ROOT','_PRODUCER_ROOT')),'P0LOGIN_EXPECTED_OWNER_ROOT','P0LOGIN_EXPECTED_PEER_ROOT','P0LOGIN_EXPECTED_PRODUCER_ROOT'):
        env.pop(key,None)
    env.update(PYTHONDONTWRITEBYTECODE='1',P0LOGIN_NESTED_COMMANDS=str(nested))
    if owner in ('SideStore','LiveContainer'):
        root=roots[owner];peer=roots['LiveContainer' if owner=='SideStore' else 'SideStore'];producer=roots['AnisetteKit']
        require(root.resolve()!=peer.resolve(),'independent owner and peer checkouts required')
        for prefix in SUITE_PREFIXES:env.update({prefix+'_PEER_ROOT':str(peer),prefix+'_PRODUCER_ROOT':str(producer)})
        if owner=='SideStore':env['SIDE_STORE_TEST_SOURCE']=str(root)
        else:env.update(LIVE_CONTAINER_TEST_SOURCE=str(root),MAINTAINED_LIVE_CONTAINER_TEST_SOURCE=str(root))
        env.update(ANISETTE_KIT_TEST_SOURCE=str(producer),P0LOGIN_EXPECTED_OWNER_ROOT=str(root),P0LOGIN_EXPECTED_PEER_ROOT=str(peer),P0LOGIN_EXPECTED_PRODUCER_ROOT=str(producer))
    return env

METADATA_EXPECTED={'schema':1,'checks':713,'failures':0,'guest_execution':False,'proprietary_input':False}
def verify_metadata_report(report):
    require(set(report)=={'schema','source_sha256','results','sanitizers','leak_sanitizer_enabled','guest_execution','device_validation','proprietary_input'},'metadata report schema differs')
    require(type(report['schema']) is int and report['schema']==1,'metadata schema differs')
    require(set(report['results'])=={'normal','optimized','sanitized'},'metadata variants differ')
    for value in report['results'].values():
        require(value==METADATA_EXPECTED and all(type(value[k]) is type(v) for k,v in METADATA_EXPECTED.items()),'metadata checks/types differ')
    require(report['sanitizers']==['address','undefined'] and report['leak_sanitizer_enabled'] is False,'metadata sanitizer contract mismatch')
    require(all(report[k] is False for k in ('guest_execution','device_validation','proprietary_input')),'metadata execution overclaim')
    require(set(report['source_sha256'])=={'Native/Loader/elf_metadata_bounds.h','Native/anisette_base.h','Native/include/anisette_core.h','.ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp'},'metadata source closure differs')
    require(all(re.fullmatch('[0-9a-f]{64}',x) for x in report['source_sha256'].values()),'metadata source digest format differs')
    return report

def source_proof(root,row,observed_lock=None):
    require(git(root,'rev-parse','HEAD').decode().strip()==row['commit'],'owner HEAD mismatch')
    require(git(root,'rev-parse','--is-shallow-repository').strip()==b'false','shallow owner checkout')
    require(snapshot(root,row['base'],row['commit'])=={'tree':row['tree'],'changes':row['changes']},'frozen source delta mismatch')
    records=entries(root,row['commit']);children={}
    for name,(mode,kind,oid) in records.items():
        if kind=='commit':
            children[name]=oid
            child=root/name
            require(not child.is_symlink() and (not child.exists() or (child.is_dir() and not list(child.iterdir()))),'Phase A may not substitute/populate app child graph')
            continue
        target=root/name
        for parent in target.parents:
            if parent==root:break
            require(not parent.is_symlink(),'linked source parent')
        if mode=='120000':
            require(target.is_symlink(),'tracked symlink changed');content=os.fsencode(os.readlink(target))
        else:
            require(mode in ('100644','100755') and target.is_file() and not target.is_symlink(),'ordinary source file required')
            require(('100755' if target.stat().st_mode&0o111 else '100644')==mode,'source file mode drift');content=target.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        require(actual==oid or (name=='Package.resolved' and observed_lock is not None and content==observed_lock),'source bytes changed: '+name)
    extras=git(root,'ls-files','--others','--exclude-standard','-z').split(b'\0')+git(root,'ls-files','--others','--ignored','--exclude-standard','-z').split(b'\0')
    for raw in filter(None,extras):
        name=os.fsdecode(raw)
        require(name=='Package.resolved' and observed_lock is not None and ordinary(root,name).read_bytes()==observed_lock,'unexpected untracked compiler input: '+name)
    require(not git(root,'diff','--cached','--name-only'),'source index changed')
    return {'commit':row['commit'],'tree':row['tree'],'tracked_entries':len(records),'gitlinks_unpopulated':children,'status':git(root,'status','--porcelain','--untracked-files=all').decode()}

class Gate(CommandRunner):
    def __init__(self,data,host,work,evidence,approved,raw):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved;self.raw=raw
        self.command_quiescence=[];self.roots={};self.locks={};self.stage='initialization'
        self.state=dict(status='FAILED_OR_INCOMPLETE',source_basis=BASIS,phase='phase-a',production_ready=False,ipa_built=False,guest_execution=False,real_ADI_executed=False,host_boundary_mode='finite_API_doubles',device_validation=False,app_typechecked=False,linux_allocator_capture='SEPARATE_NOT_RUN_OR_REUSED_HERE')
    def all_sources(self):
        return {name:dict(source_proof(root,self.data['owners'][name],self.locks.get(name)),origin=primitives.verify_origin(root,self.data['owners'][name]['repository'],self.data['owners'][name]['commit'])) for name,root in self.roots.items()}
    def host_proof(self,commit):
        base=self.data['owners']['LiveContainer']['commit']
        parents=git(self.host,'rev-list','--parents','-n','1',commit).decode().split()
        require(parents==[commit,base],'capture host must be a direct single-parent child of exact LC source')
        actual=snapshot(self.host,base,commit)
        expected={**self.data['adapter_files'],'ci/p0login/inputs-phase-a.json':sha(self.raw),WORKFLOW_PATH:sha(ordinary(self.host,WORKFLOW_PATH).read_bytes()),BUILD_WORKFLOW_PATH:self.data['ordinary_build_guard']['after_sha256']}
        require(set(actual['changes'])==set(expected),'host overlay changed an old gate/workflow or unreviewed path')
        for path,delta in actual['changes'].items():
            if path==BUILD_WORKFLOW_PATH:
                require(delta['before']['mode']=='100644' and delta['before']['type']=='blob' and delta['before']['sha256']==self.data['ordinary_build_guard']['before_sha256'],'ordinary workflow before bytes differ')
                before=git(self.host,'show',base+':'+BUILD_WORKFLOW_PATH)
                require(before.count(b'  build:\n')==1 and ordinary(self.host,path).read_bytes()==before.replace(b'  build:\n',('  build:\n'+BUILD_GUARD).encode(),1),'ordinary workflow changed beyond exact job guard')
            else:require(delta['before'] is None,'capture adapter unexpectedly replaces old file')
            require(delta['after']['type']=='blob' and delta['after']['mode']=='100644' and delta['after']['sha256']==expected[path],'host overlay is not exact reviewed adapter/guard bytes')
        row=dict(commit=commit,base=base,tree=actual['tree'],changes=actual['changes'])
        proof=source_proof(self.host,row)
        proof['origin']=primitives.verify_origin(self.host,'https://github.com/NRG-Wardog/LiveContainer.git',commit)
        dump(self.evidence/'provenance/host-overlay.json',proof)
    def acquire(self):
        for name in OWNERS:
            row=self.data['owners'][name];root=self.work/'sources'/name
            self.run('clone-'+name.lower(),['git','clone','--no-checkout',row['repository'],root])
            self.run('fetch-'+name.lower(),['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']])
            self.run('checkout-'+name.lower(),['git','-C',root,'checkout','--detach',row['commit']])
            self.run('readonly-'+name.lower(),['git','-C',root,'config','remote.origin.pushurl','disabled://p0login-readonly'])
            self.roots[name]=root
        dump(self.evidence/'provenance/source-before.json',self.all_sources())
        ss=self.roots['SideSign'];ak=self.data['owners']['AnisetteKit']['commit']
        before=git(ss,'show',self.data['owners']['SideSign']['base']+':Package.swift').decode()
        old='revision: "'+self.data['owners']['AnisetteKit']['base']+'"'
        require(before.count(old)==1 and ordinary(ss,'Package.swift').read_text()==before.replace(old,'revision: "'+ak+'"'),'SideSign manifest changed beyond exact AK pin')
        for owner,files in self.data['test_source_audit'].items():
            found={str(p.relative_to(self.roots[owner])):sha(p.read_bytes()) for p in (self.roots[owner]/'Tests').rglob('*.swift')}
            require(found==files,'reviewed test initialization source changed')
    def resolve_sidesign(self):
        root=self.roots['SideSign'];scratch=self.work/'sidesign-scratch';lock=root/'Package.resolved'
        before=lock.read_bytes();(self.evidence/'provenance/SideSign.Package.resolved.before').write_bytes(before)
        base=['swift','package','--package-path',root,'--scratch-path',scratch,'--disable-dependency-cache']
        self.run('sidesign-resolve',[*base,'resolve'])
        after=lock.read_bytes();self.locks['SideSign']=after
        (self.evidence/'provenance/SideSign.Package.resolved.after').write_bytes(after)
        self.state['resolved_lock']=check_lock(before,after,self.data['owners']['AnisetteKit']['commit'])
        self.run('sidesign-frozen-resolve',[*base,'--force-resolved-versions','resolve'])
        require(lock.read_bytes()==after,'strict frozen repeat changed actual lock')
        self.verify_resolved(scratch)
    def verify_resolved(self,scratch):
        states=list(scratch.rglob('workspace-state.json'));require(len(states)==1,'exact real SwiftPM workspace state required')
        graph=primitives.verify_resolution(self.roots,states[0],self.roots['SideSign']/'Package.resolved',{})
        ak=graph['anisettekit'];row=self.data['owners']['AnisetteKit']
        require(ak['commit']==row['commit'] and ak['tree']==row['tree'],'resolved exact AK tree mismatch')
        dump(self.evidence/'provenance/resolved-packages.json',graph)
    def compile_swift(self):
        ak=self.roots['AnisetteKit']
        self.run('trace-strict-typecheck',['xcrun','swiftc','-swift-version','6','-strict-concurrency=complete','-typecheck','-module-name','LoginTraceHost',ak/'Sources/AnisetteError.swift',ak/'Sources/LoginDiagnosticTrace.swift'])
        for name,row in self.data['owners'].items():
            for index,path in enumerate(sorted(row['changes'])):
                if path.endswith('.swift'):
                    self.run('parse-'+name.lower()+'-'+str(index),['xcrun','swiftc','-frontend','-parse',ordinary(self.roots[name],path)])
    def swift_tests(self,owner):
        label='anisette' if owner=='AnisetteKit' else 'sidesign';root=self.roots[owner];scratch=self.work/(label+'-scratch')
        if owner=='AnisetteKit':
            self.run('anisette-resolve',['swift','package','--package-path',root,'--scratch-path',scratch,'--disable-dependency-cache','resolve'])
            lock=root/'Package.resolved'
            if lock.exists():self.locks[owner]=lock.read_bytes();(self.evidence/'provenance/AnisetteKit.Package.resolved.observed').write_bytes(self.locks[owner])
            self.run('anisette-frozen-resolve',['swift','package','--package-path',root,'--scratch-path',scratch,'--disable-dependency-cache','--force-resolved-versions','resolve'])
            require((lock.read_bytes() if lock.exists() else None)==self.locks.get(owner),'AK frozen resolve changed lock')
        opts=['--package-path',root,'--scratch-path',scratch,'--force-resolved-versions','--disable-dependency-cache']
        self.run(label+'-build',['swift','build',*opts,'--build-tests','-v'])
        frameworks=['--enable-xctest','--disable-swift-testing'] if owner=='AnisetteKit' else ['--disable-xctest','--enable-swift-testing']
        discovery=self.run(label+'-discover',[*SANDBOX,'swift','test','list',*opts,'--skip-build','--disable-sandbox',*frameworks],stdout_only=True)
        expected=AK_IDS if owner=='AnisetteKit' else SS_IDS
        dump(self.evidence/('provenance/'+label+'-discovery.json'),verify_discovery(discovery,expected))
        output=self.run(label+'-tests',[*SANDBOX,'swift','test',*opts,'--skip-build','--disable-sandbox',*frameworks,'--filter',AK_FILTER if owner=='AnisetteKit' else SS_FILTER])
        dump(self.evidence/('provenance/'+label+'-tests.json'),verify_swift_tests(output,owner))
        lock=root/'Package.resolved'
        require((lock.read_bytes() if lock.exists() else None)==self.locks.get(owner),'Swift build/test changed resolver lock')
    def python_suites(self):
        for row in self.data['python_suites']:
            root=self.roots[row['owner']];suite=ordinary(root,row['path']).parent
            expected=self.work/(row['id']+'-ids.json');dump(expected,row['test_ids'])
            env=suite_environment(row['owner'],self.roots,self.evidence/'nested-commands'/row['id'])
            output=self.run('suite-'+row['id'],[*SANDBOX,sys.executable,'-B',HERE/'run_unittest_suite.py',suite,expected,Path(row['path']).stem],env=env,stdout_only=True,timeout=1800)
            report=parse(output.splitlines()[-1])
            require(report['tests']==len(row['test_ids']) and sorted(report['test_ids'])==sorted(row['test_ids']) and all(report[k]==0 for k in ('failures','errors','skips','expected_failures','unexpected_successes')),'finite Python suite failed or skipped')
            dump(self.evidence/('provenance/suites/'+row['id']+'.json'),report)
    def metadata_units(self):
        output=self.evidence/'metadata-units'
        self.run('metadata-units', [*SANDBOX,sys.executable,'-B',HERE/'run_observed_script.py',self.roots['AnisetteKit']/'.ci/native-tests/test_elf_metadata_bounds.py','--output',output,'--disable-leak-sanitizer'],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',P0LOGIN_NESTED_COMMANDS=str(self.evidence/'nested-commands/metadata-units')))
        report=verify_metadata_report(parse(ordinary(output,'result.json').read_bytes()))
        for path,digest in report['source_sha256'].items():require(sha(ordinary(self.roots['AnisetteKit'],path).read_bytes())==digest,'metadata production source hash differs')
        for variant in report['results']:
            raw=parse(ordinary(output,variant+'-run.stdout').read_bytes())
            require(raw==METADATA_EXPECTED and all(type(raw[k]) is type(v) for k,v in METADATA_EXPECTED.items()),'metadata raw output differs')
            for phase in ('compile','run'):
                require(ordinary(output,variant+'-'+phase+'.exit-code.txt').read_text()=='0\n' and ordinary(output,variant+'-'+phase+'.stderr').read_bytes()==b'','metadata command failed or emitted stderr')
        dump(self.evidence/'provenance/elf-metadata-bounds.json',dict(report,source_owner=self.data['owners']['AnisetteKit']['commit'],source_tree=self.data['owners']['AnisetteKit']['tree']))
    def execute(self):
        require(platform.system()=='Darwin' and platform.machine()==TOOLCHAIN['architecture'],'actual reviewed macOS architecture required')
        require(os.environ.get('DEVELOPER_DIR')==TOOLCHAIN['developer_dir'],'reviewed Xcode selection required')
        require(not self.work.exists() and not self.evidence.exists(),'fresh isolated work/evidence paths required')
        require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/validation/p0-login-trace-phase-a','dedicated capture branch required')
        commit=full_sha(os.environ.get('GITHUB_SHA'));require(git(self.host,'rev-parse','HEAD').decode().strip()==commit,'actual host commit mismatch')
        run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','');require(run.isdigit() and attempt.isdigit() and int(run)>0 and int(attempt)>0,'actual GitHub run identity required')
        (self.work/'sources').mkdir(parents=True);(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        self.state.update(approved_inputs_sha256=self.approved,source_seal_sha256=SEAL_SHA,owners=self.data['owners'],run={'repository':'NRG-Wardog/LiveContainer','run_id':int(run),'run_attempt':int(attempt),'host_commit':commit,'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()})
        try:
            self.deadline=time.monotonic()+120*60
            self.stage='host-proof';self.host_proof(commit)
            self.stage='toolchain'
            require(self.run('xcode-version',['xcodebuild','-version']).strip()==TOOLCHAIN['xcode'],'reviewed xcode version mismatch')
            swift_stdout=self.run('swift-version',['swift','--version'],stdout_only=True)
            verify_swift_version(swift_stdout,ordinary(self.evidence,'logs/swift-version.stderr.log').read_text())
            require(self.run('clang-version',['xcrun','clang++','--version']).splitlines()[0]==TOOLCHAIN['clang'],'reviewed clang version mismatch')
            self.run('uname',['uname','-a']);self.run('macos-sdk',['xcrun','--sdk','macosx','--show-sdk-path']);self.run('iphoneos-sdk',['xcrun','--sdk','iphoneos','--show-sdk-path'])
            self.run('network-sandbox', [*SANDBOX,sys.executable,'-c','import socket,errno\ns=socket.socket()\ntry:s.connect(("1.1.1.1",443))\nexcept OSError as e:\n if e.errno not in (errno.EPERM,errno.EACCES):raise\nelse:raise SystemExit("network sandbox did not deny")'])
            self.stage='acquire';self.acquire()
            self.stage='resolve';self.resolve_sidesign()
            self.stage='swift-source';self.compile_swift()
            self.stage='safe-host-tests';self.metadata_units();self.python_suites()
            self.stage='anisette-swift';self.swift_tests('AnisetteKit')
            self.stage='sidesign-swift';self.swift_tests('SideSign')
            self.verify_resolved(self.work/'sidesign-scratch')
            self.host_proof(commit)
            dump(self.evidence/'provenance/source-after.json',self.all_sources())
            self.state['status']='CAPTURED_FOR_REVIEW';self.stage='captured'
        except Exception as error:
            self.state['primary_error']=type(error).__name__+': '+str(error);raise
        finally:
            settled=bool(self.command_quiescence) and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in self.command_quiescence)
            self.state.update(writers_quiescent=settled,last_stage=self.stage)
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            if settled:
                for owner,root in self.roots.items():
                    p=root/'Package.resolved'
                    if p.is_file() and not p.is_symlink():(self.evidence/('provenance/'+owner+'.Package.resolved.final-observed')).write_bytes(p.read_bytes())
            dump(self.evidence/'provenance/result.json',self.state);dump(self.evidence/'provenance/owned-command-groups.json',self.command_quiescence)
            (self.evidence/'provenance/reviewed-inputs.json').write_bytes(self.raw)
            if settled:
                index={str(p.relative_to(self.evidence)):sha(p.read_bytes()) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}
                dump(self.evidence/'evidence-index.json',index)

def verify_transport(root):
    result=parse(ordinary(root,'provenance/result.json').read_bytes());require(result.get('writers_quiescent') is True,'writers not settled')
    groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(groups and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in groups),'owned writer receipts incomplete')
    index=parse(ordinary(root,'evidence-index.json').read_bytes());actual={}
    for path in root.rglob('*'):
        require(not path.is_symlink(),'linked evidence')
        if path.is_file() and path.name!='evidence-index.json':actual[str(path.relative_to(root))]=sha(path.read_bytes())
    require(index==actual and {'provenance/result.json','provenance/reviewed-inputs.json','provenance/owned-command-groups.json'}<=set(index),'immutable evidence index mismatch')
    return {'status':'QUIESCENT_INDEX_VERIFIED','files':len(index),'capture_status':result['status']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',required=True,type=Path);p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--host-root',required=True,type=Path);p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--execute',action='store_true');p.add_argument('--check-transport',action='store_true')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.approved_inputs_sha256,a.host_root)
        if a.check_transport:
            require(not a.execute and a.evidence is not None,'transport requires evidence and no execution');print(json.dumps(verify_transport(a.evidence)));return
        if not a.execute:print(json.dumps({'status':'SEALED_INPUTS_VALID_FOR_REVIEW','native_execution':False,'production_ready':False}));return
        require(a.work is not None and a.evidence is not None,'fresh work and evidence required')
        Gate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256,raw).execute()
    except Exception as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
