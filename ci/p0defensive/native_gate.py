#!/usr/bin/env python3
"""Real-package, synthetic-test-only Phase A capture. Activation is separately reviewed."""
import argparse, hashlib, json, os, platform, re, shutil, sys, time, zipfile, stat
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import source_primitives as primitives
import capture_contract as contract
import host_tests
from inventory import *
from lifecycle import CommandRunner
from retention import RawStore
HERE=Path(__file__).resolve().parent
SANDBOX=contract.SANDBOX
LANES=('anisette-trace-regression','sidesign-core-regression')
# Gate.run's fixed PATH selects these Apple launchers before Xcode leaf tools.
LAUNCHER_PATHS=('/usr/bin/git','/usr/bin/xcrun','/usr/bin/sandbox-exec','/usr/bin/curl','/usr/bin/swift','/usr/bin/swiftc','/usr/bin/c++','/usr/bin/xcodebuild','/usr/bin/uname')


def check_lock(before,after,commit):
    old,new=parse(before),parse(after);op,np=primitives.pin_map(old),primitives.pin_map(new)
    require(op.keys()==np.keys() and 'anisettekit' in np,'package set drift')
    for name in op:
        if name!='anisettekit':require(op[name]==np[name],'unrelated pin drift: '+name)
    require(np['anisettekit']=={'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':commit}},'exact AnisetteKit pin required')
    require({k:v for k,v in old.items() if k not in ('pins','originHash')}=={k:v for k,v in new.items() if k not in ('pins','originHash')},'lock schema drift')
    require(isinstance(new.get('originHash'),str) and re.fullmatch('[0-9a-f]{64}',new['originHash']),'genuine SwiftPM originHash required')
    return {'sha256':sha(after),'originHash':new['originHash']}


def verify_native_logs(stdout,stderr,lane):
    raw=stdout+stderr
    require(not any(value in raw for value in (b'account@example.invalid',b'TOKEN-CANARY',b'PASSWORD-CANARY',b'BLOB-CANARY',b'SECRET',b'ORIGINAL')),'sensitive fixture appeared in successful native output')
    result=contract.verify_runtime(raw,lane)
    if lane=='anisette-trace-regression':
        text=raw.decode('utf-8');suites=list(re.finditer(r"Test Suite '([^']+)' (started|passed)",text))
        events=[match.groups() for match in suites]
        require(events==[('Selected tests','started'),('AnisetteKitPackageTests.xctest','started'),('LoginDiagnosticTraceTests','started'),('LoginDiagnosticTraceTests','passed'),('AnisetteKitPackageTests.xctest','passed'),('Selected tests','passed')],'unknown or unsettled XCTest suite')
        require(text.count('Test Suite ')==len(events),'unknown XCTest suite status')
        summaries=list(re.finditer(r'\bExecuted\b[^\r\n]*',text))
        require(len(summaries)==3,'exact three XCTest completion summaries required')
        for index,summary in enumerate(summaries):
            require(re.fullmatch(r'Executed 6 tests, with 0 failures \(0 unexpected\) in \d+(?:\.\d+)? \(\d+(?:\.\d+)?\) seconds',summary.group()) is not None,'unknown or malformed XCTest completion summary')
            require(suites[index+3].end()<summary.start(),'XCTest summary precedes its suite completion')
            if index<2:require(summary.end()<suites[index+4].start(),'XCTest summary escaped its completed suite')
        cases=list(re.finditer(r"Test Case '[^']+' (?:started|passed)",text))
        require(len(cases)==12 and all(suites[2].end()<case.start()<case.end()<suites[3].start() for case in cases),'XCTest case event escaped inner suite lifecycle')
    return result


def source_proof(root,row,observed_lock=None):
    require(git(root,'rev-parse','HEAD').decode().strip()==row['commit'],'owner HEAD mismatch')
    require(git(root,'rev-list','--parents','-n','1',row['commit']).decode().split()==[row['commit'],*row['parents']],'owner parent mismatch')
    require(git(root,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'owner full tree mismatch')
    require(git(root,'rev-parse','--is-shallow-repository').strip()==b'false','shallow owner checkout')
    records=entries(root,row['commit'])
    for name,(mode,kind,oid) in records.items():
        require(kind=='blob' and mode in ('100644','100755','120000'),'unexpected owner gitlink or mode')
        target=root/name
        for parent in target.parents:
            if parent==root:break
            require(not parent.is_symlink(),'linked source parent')
        if mode=='120000':
            require(target.is_symlink(),'tracked symlink changed');content=os.fsencode(os.readlink(target))
        else:
            require(target.is_file() and not target.is_symlink(),'ordinary source file required')
            require(('100755' if target.stat().st_mode&0o111 else '100644')==mode,'source mode drift');content=target.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        require(actual==oid or (name=='Package.resolved' and observed_lock is not None and content==observed_lock),'source bytes changed: '+name)
    extras=git(root,'ls-files','--others','--exclude-standard','-z').split(b'\0')+git(root,'ls-files','--others','--ignored','--exclude-standard','-z').split(b'\0')
    for raw in filter(None,extras):
        name=os.fsdecode(raw)
        require(name=='Package.resolved' and observed_lock is not None and ordinary(root,name).read_bytes()==observed_lock,'unexpected untracked compiler input: '+name)
    require(not git(root,'diff','--cached','--name-only'),'source index changed')
    return {'commit':row['commit'],'tree':row['tree'],'parents':row['parents'],'tracked_entries':len(records),'status':git(root,'status','--porcelain','--untracked-files=all').decode(),'origin':primitives.verify_origin(root,row['repository'],row['commit'])}



def verify_host_worktree(root,commit):
    """Retain the predecessor's complete host checkout/ignored-input guard."""
    records=entries(root,commit)
    for name,(mode,kind,oid) in records.items():
        path=root/name
        for parent in path.parents:
            if parent==root:break
            require(not parent.is_symlink(),'linked host source parent')
        if kind=='commit':
            require(mode=='160000' and not path.is_symlink() and (not path.exists() or (path.is_dir() and not list(path.iterdir()))),'Phase A host gitlinks must remain unpopulated')
            continue
        require(kind=='blob','unexpected host Git object')
        if mode=='120000':
            require(path.is_symlink(),'tracked host link changed');raw=os.fsencode(os.readlink(path))
        else:
            require(mode in ('100644','100755') and path.is_file() and not path.is_symlink(),'host ordinary file changed')
            require(('100755' if path.stat().st_mode&0o111 else '100644')==mode,'host source mode changed');raw=path.read_bytes()
        require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==oid,'host source bytes changed: '+name)
    for options in (('--others','--exclude-standard'),('--others','--ignored','--exclude-standard')):
        require(not git(root,'ls-files',*options,'-z'),'untracked or ignored host compiler input')
    require(not git(root,'diff','--cached','--name-only'),'host source index changed')
    require(not git(root,'status','--porcelain','--untracked-files=all'),'capture host dirty')
    return {'tracked_entries':len(records),'unpopulated_gitlinks':{name:oid for name,(mode,kind,oid) in records.items() if kind=='commit'}}


def verify_sealed_delta(root,row,name,seal,ak):
    actual=snapshot(root,row['base'],row['commit'])
    expected={r['path']:r for r in seal['owners'][name]['changes']}
    require(set(actual['changes'])==set(expected)|({'Package.swift'} if name=='SideSign' else set()),'unreviewed owner source delta')
    for path,source in expected.items():
        for side in ('before','after'):
            value=actual['changes'][path][side];sealed=source[side]
            if sealed is None:require(value is None,'unexpected before blob');continue
            require(value is not None and value['type']=='blob' and all(value[k]==sealed[k] for k in ('mode','git_object','sha256')),'reviewed source file changed: '+path)
    require(git(root,'rev-parse',row['base']+'^{tree}').decode().strip()==seal['owners'][name]['base_tree'],'base tree changed')
    if name=='SideSign':
        before=git(root,'show',row['base']+':Package.swift');after=ordinary(root,'Package.swift').read_bytes();delta=row['manifest_delta']
        old=('revision: "'+delta['old_ak']+'"').encode();new=('revision: "'+ak+'"').encode()
        require(before.count(old)==1 and after==before.replace(old,new,1),'manifest changed beyond exact AK revision')
        require(sha(before)==delta['before_sha256'] and sha(after)==delta['after_sha256'],'manifest byte anchor mismatch')
        lock_before=git(root,'show',row['base']+':Package.resolved')
        require(ordinary(root,'Package.resolved').read_bytes()==lock_before,'Phase A input may not supply a fabricated lock')
    return actual


def lane_commands(lane,roots,work):
    commands=contract.expected_commands(lane);owner,_=contract.lane_data(lane)
    replacements={'/REVIEWED/SOURCES/'+owner:str(roots[owner]),'/FRESH/WORK/'+owner+'-scratch':str(work/('anisette-scratch' if owner=='AnisetteKit' else 'sidesign-scratch'))}
    result={key:[replacements.get(value,value) for value in args] for key,args in commands.items()}
    # Round-trip to the literal reviewed command contract, including argv order.
    reverse={value:key for key,value in replacements.items()}
    contract.validate_commands(lane,{key:[reverse.get(value,value) for value in args] for key,args in result.items()})
    return result


def file_sha(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def check_artifact_archive(archive,bundle_root,bundle):
    """Prove every actual extracted framework byte/mode against the pinned raw ZIP."""
    require(bundle_root.name==bundle and bundle_root.is_dir() and not bundle_root.is_symlink(),'artifact root mismatch')
    expected={};total=0;members={}
    with zipfile.ZipFile(archive) as z:
        require(len(z.infolist())<=100000,'artifact archive entry bound')
        for info in z.infolist():
            name=info.filename
            require(not name.startswith('/') and all(p not in ('','..','.') for p in name.rstrip('/').split('/')),'unsafe archive path')
            if info.is_dir():continue
            require(name.startswith(bundle+'/'),'unexpected artifact archive member')
            relative=name[len(bundle)+1:];require(relative not in expected,'duplicate archive member')
            require(info.file_size<=512*1024*1024,'artifact member too large');total+=info.file_size
            require(total<=4*1024*1024*1024,'artifact expansion bound')
            expected[relative]=info
        actual={str(p.relative_to(bundle_root)):p for p in bundle_root.rglob('*') if p.is_symlink() or p.is_file()}
        require(set(actual)==set(expected),'artifact extraction file inventory mismatch')
        for relative,info in expected.items():
            p=actual[relative];mode=info.external_attr>>16
            for parent in p.parents:
                if parent==bundle_root:break
                require(not parent.is_symlink(),'linked artifact parent')
            if stat.S_ISLNK(mode):
                require(info.file_size<=4096,'artifact link target too large');raw=z.read(info)
                require(p.is_symlink() and os.fsencode(os.readlink(p))==raw,'artifact symlink mismatch')
                require(p.resolve(strict=True).is_relative_to(bundle_root.resolve()),'artifact symlink escape')
                members[relative]={'sha256':sha(raw),'length':len(raw),'kind':'symlink'}
            else:
                require(stat.S_IFMT(mode) in (0,stat.S_IFREG),'unexpected archive special file')
                require(not p.is_symlink() and p.is_file() and p.stat().st_size==info.file_size,'artifact extraction length mismatch')
                digest=hashlib.sha256();length=0
                with z.open(info) as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):
                        length+=len(chunk);require(length<=info.file_size,'artifact expansion length mismatch');digest.update(chunk)
                require(length==info.file_size and file_sha(p)==digest.hexdigest(),'artifact extraction bytes mismatch')
                require(bool(p.stat().st_mode&0o111)==bool(mode&0o111),'artifact executable mode mismatch')
                members[relative]={'sha256':digest.hexdigest(),'length':length,'kind':'file','executable':bool(mode&0o111)}
    return {'archive_sha256':file_sha(archive),'files':len(expected),'expanded_bytes':total,'members':members}


class Gate(CommandRunner):
    def __init__(self,data,host,work,evidence,approved,raw):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved;self.raw=raw
        self.command_quiescence=[];self.roots={};self.locks={};self.stage='initialization';self.store=None;self.artifact_archives={};self.counts={key:0 for key in data['command_counts']}
        self.state=dict(status='FAILED_OR_INCOMPLETE',source_basis=BASIS,phase='phase-a',production_ready=False,build_admission=False,ipa_built=False,guest_execution=False,real_ADI_executed=False,live_provider_or_apple_requests=False,device_validation=False,app_typechecked=False,compiled_identity='source-parent-plus-genuine-observed-lock; future-lock-child-not-directly-compiled',capture_host_role='historical-LiveContainer-capture-only-not-compiled')
    def run(self,name,args,**kw):
        # No ambient tokens, credentials, proxy, DYLD, package overrides, or caches.
        kw['env']=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin:'+TOOLCHAIN['developer_dir']+'/Toolchains/XcodeDefault.xctoolchain/usr/bin',HOME=str(self.work/'home'),TMPDIR=str(self.work/'tmp'),DEVELOPER_DIR=TOOLCHAIN['developer_dir'],PYTHONDONTWRITEBYTECODE='1')
        kw.setdefault('cwd',self.work)
        return super().run(name,args,**kw)
    def save(self,label,value):dump(self.evidence/('provenance/'+label+'.json'),value)
    def retain(self,label,path):
        record=self.store.retain_file(path,label=label);self.save(label,record);return record
    def all_sources(self,phase):
        report={}
        for name,root in self.roots.items():
            row=self.data['owners'][name];proof=source_proof(root,row,self.locks.get(name))
            proof['raw_tree']=self.store.retain_git_tree(root,row['commit'],label=phase+'/'+name)
            proof['raw_identity_objects']={}
            for revision in (row['base'],row['commit']):
                for kind,content in [('commit',git(root,'cat-file','commit',revision)),('tree-listing',git(root,'ls-tree','-rz',revision))]:
                    proof['raw_identity_objects'][revision+'/'+kind]=self.store.retain_bytes(content,label=phase+'/'+name+'/'+revision+'/'+kind)
            if (root/'Package.resolved').exists():proof['actual_lock']=self.store.retain_file(root/'Package.resolved',label=phase+'/'+name+'/Package.resolved')
            report[name]=proof
        self.save('source-'+phase,report);return report
    def host_proof(self,commit):
        row=self.data['host'];base=row['base']
        require(git(self.host,'rev-list','--parents','-n','1',commit).decode().split()==[commit,base],'capture host must be direct single-parent exact source child')
        require(git(self.host,'rev-parse',base+'^{tree}').decode().strip()==row['tree'],'capture base tree mismatch')
        actual=snapshot(self.host,base,commit)
        expected={**self.data['adapter_files'],'ci/p0defensive/inputs-phase-a.json':sha(self.raw),WORKFLOW_PATH:sha(ordinary(self.host,WORKFLOW_PATH).read_bytes()),BUILD_WORKFLOW_PATH:row['ordinary_build_after_sha256']}
        require(set(actual['changes'])==set(expected),'host overlay includes unreviewed paths')
        for path,delta in actual['changes'].items():
            if path==BUILD_WORKFLOW_PATH:require(delta['before']['sha256']==row['ordinary_build_before_sha256'] and delta['before']['mode']=='100644','ordinary build baseline changed')
            else:require(delta['before'] is None,'adapter replaced an old file')
            require(delta['after']['mode']=='100644' and delta['after']['type']=='blob' and delta['after']['sha256']==expected[path],'host adapter bytes changed')
        host_worktree=verify_host_worktree(self.host,commit)
        raw_files={path:self.store.retain_file(ordinary(self.host,path),label='capture-host/'+path) for path in expected}
        self.save('host-overlay',dict(commit=commit,base=base,tree=actual['tree'],origin=primitives.verify_origin(self.host,row['repository'],commit),changes=actual['changes'],raw_files=raw_files,worktree=host_worktree))
    def acquire(self):
        seal=parse(ordinary(HERE,'reviewed/defensive-source-seal.json').read_bytes())
        for name in OWNERS:
            row=self.data['owners'][name];root=self.work/'sources'/name
            for label,args in [('clone',['git','clone','--no-checkout',row['repository'],root]),('fetch',['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']]),('checkout',['git','-C',root,'checkout','--detach',row['commit']]),('readonly',['git','-C',root,'config','remote.origin.pushurl','disabled://p0defensive-readonly'])]:
                self.run(label+'-'+name.lower(),args);self.counts['owner_acquisition']+=1
            self.roots[name]=root
            delta=verify_sealed_delta(root,row,name,seal,self.data['owners']['AnisetteKit']['commit'])
            for path,change in delta['changes'].items():
                for side,value in change.items():
                    if value is not None and value['type']=='blob':value['raw_blob']=self.store.retain_bytes(git(root,'cat-file','blob',value['git_object']),label='source-delta/'+name+'/'+path+'/'+side,mode=value['mode'])
            self.save('source-delta-'+name,delta)
            contract.verify_test_sources(root,name,{'swift_files':self.data['test_source_audit']})
        self.all_sources('before')
    def fetch_artifacts(self):
        for artifact in self.data['artifacts']:
            digest=artifact['sha256']
            if digest in self.artifact_archives:continue
            target=self.work/'archives'/(digest+'.zip');target.parent.mkdir(exist_ok=True)
            self.run('artifact-'+artifact['identity'],['/usr/bin/curl','--fail','--location','--proto','=https','--proto-redir','=https','--max-time','600','--output',target,artifact['url'].split('#')[0]],timeout=660)
            require(target.stat().st_size<=512*1024*1024 and file_sha(target)==digest,'pinned artifact archive checksum mismatch')
            self.artifact_archives[digest]=target;self.retain('archives/'+digest,target)
    def resolve(self,owner):
        label='anisette' if owner=='AnisetteKit' else 'sidesign';root=self.roots[owner];scratch=self.work/(label+'-scratch');lock=root/'Package.resolved'
        before=lock.read_bytes() if lock.exists() else None
        self.save(owner+'-lock-before',{'present':before is not None,'record':self.store.retain_bytes(before,label=owner+'/Package.resolved.before') if before is not None else None})
        if before is not None:(self.evidence/('provenance/'+owner+'.Package.resolved.before')).write_bytes(before)
        base=['swift','package','--package-path',root,'--scratch-path',scratch,'--disable-dependency-cache']
        self.run(label+'-resolve',[*base,'resolve']);self.counts['package_resolve']+=1
        after=lock.read_bytes() if lock.exists() else None
        if after is not None:
            self.locks[owner]=after;(self.evidence/('provenance/'+owner+'.Package.resolved.after')).write_bytes(after)
        if owner=='SideSign':self.save('resolved-lock',check_lock(before,after,self.data['owners']['AnisetteKit']['commit']))
        else:require(before is None and after is None,'dependency-free AK must not acquire a lock')
        self.run(label+'-frozen-resolve',[*base,'--force-resolved-versions','resolve']);self.counts['package_resolve']+=1
        require((lock.read_bytes() if lock.exists() else None)==after,'frozen resolve changed lock')
        self.verify_resolved(owner,'after-resolve')
    def verify_resolved(self,owner,phase):
        label='anisette' if owner=='AnisetteKit' else 'sidesign';scratch=self.work/(label+'-scratch');state=scratch/'workspace-state.json'
        require(state.is_file() and not state.is_symlink(),'genuine SwiftPM workspace state required')
        raw=ordinary(scratch,'workspace-state.json').read_bytes();document=parse(raw);obj=document['object']
        self.retain(phase+'/'+owner+'/workspace-state',state)
        graph={}
        if owner=='SideSign':
            graph=primitives.verify_resolution(self.roots,state,self.roots[owner]/'Package.resolved',{})
            ak=graph['anisettekit'];expected=self.data['owners']['AnisetteKit'];require(ak['commit']==expected['commit'] and ak['tree']==expected['tree'],'resolved AK full tree differs')
            for dep in obj['dependencies']:
                ref=dep['packageRef'];identity=ref['identity'].lower();checkout=scratch/'checkouts'/dep['subpath']
                require(git(checkout,'rev-parse','--is-shallow-repository').strip()==b'false','shallow resolved checkout')
                graph[identity]['raw_tree']=self.store.retain_git_tree(checkout,graph[identity]['commit'],label=phase+'/'+owner+'/checkouts/'+identity)
                graph[identity]['raw_commit']=self.store.retain_bytes(git(checkout,'cat-file','commit',graph[identity]['commit']),label=phase+'/'+owner+'/checkouts/'+identity+'/commit')
                graph[identity]['raw_listing']=self.store.retain_bytes(git(checkout,'ls-tree','-rz',graph[identity]['commit']),label=phase+'/'+owner+'/checkouts/'+identity+'/tree-listing')
        else:require(obj['dependencies']==[],'AK gained dependencies')
        expected_artifacts=[r for r in self.data['artifacts'] if owner=='SideSign' or r['identity']=='anisettekit']
        artifacts=obj['artifacts'];require(len(artifacts)==len(expected_artifacts),'binary artifact set differs')
        seen=set();proof=[]
        for artifact in artifacts:
            identity=artifact['packageRef']['identity'].lower();target=artifact['targetName'];key=(identity,target)
            require(key not in seen,'duplicate artifact');seen.add(key)
            matches=[r for r in expected_artifacts if (r['identity'],r['target'])==key];require(len(matches)==1,'unexpected binary artifact')
            expected=matches[0];require(artifact['source']=={'checksum':expected['sha256'],'type':'remote','url':expected['url']},'artifact URL/checksum differs')
            root=Path(artifact['path']);require(root.is_absolute() and root.resolve().is_relative_to((scratch/'artifacts').resolve()),'artifact escaped scratch root')
            comparison=check_artifact_archive(self.artifact_archives[expected['sha256']],root,expected['bundle'])
            retained=self.store.retain_tree(root,label=phase+'/'+owner+'/artifacts/'+identity)
            retained_files={r['path']:r for r in retained['entries'] if r['kind']!='directory'}
            require(set(retained_files)==set(comparison['members']),'retained artifact inventory drift')
            for name,expected_member in comparison['members'].items():
                item=retained_files[name]
                require(all(item[k]==expected_member[k] for k in ('sha256','length','kind')),'retained artifact differs from archive')
                if item['kind']=='file':require(bool(int(item['mode'],8)&0o111)==expected_member['executable'],'retained artifact mode differs')
            proof.append(dict(identity=identity,target=target,comparison=comparison,raw_tree=retained))
        self.save(phase+'/'+owner+'/resolved-graph',dict(packages=graph,artifacts=proof))
    def build(self,owner):
        lane='anisette-trace-regression' if owner=='AnisetteKit' else 'sidesign-core-regression';label='anisette' if owner=='AnisetteKit' else 'sidesign'
        self.run(label+'-build',lane_commands(lane,self.roots,self.work)['build']);self.counts['package_build']+=1
        self.all_sources('after-'+label+'-build');self.verify_resolved(owner,'after-build')
    def tests(self,lane):
        owner,_=contract.lane_data(lane);commands=lane_commands(lane,self.roots,self.work)
        contract.verify_test_sources(self.roots[owner],owner,{'swift_files':self.data['test_source_audit']})
        self.run(lane+'-discover',commands['discover'],stdout_only=True);self.counts['test_discovery']+=1
        self.save(lane+'-discovery',contract.verify_discovery(ordinary(self.evidence,'logs/'+lane+'-discover.log').read_bytes(),lane))
        self.run(lane+'-tests',commands['execute']);self.counts['filtered_test_execution']+=1
        # Preserve streams exactly. The parser consumes their established stdout+stderr order;
        # genuine capture format remains subject to separate independent review.
        stdout=ordinary(self.evidence,'logs/'+lane+'-tests.log').read_bytes();stderr=ordinary(self.evidence,'logs/'+lane+'-tests.stderr.log').read_bytes()
        result=verify_native_logs(stdout,stderr,lane);self.counts['selected_tests']+=result['executed'];self.save(lane+'-tests',result)
    def host_tests(self):
        owner=self.roots['AnisetteKit'];include=self.work/'host-unicorn-headers'
        artifact=next(row for row in self.data['artifacts'] if row['identity']=='anisettekit')
        hashes=host_tests.extract_headers(self.artifact_archives[artifact['sha256']],include,artifact['sha256'])
        self.save('host-unicorn-headers',dict(archive_sha256=artifact['sha256'],headers_sha256=hashes,raw_tree=self.store.retain_tree(include,label='host-unicorn-headers'),engine_linked=False,engine_executed=False))
        for (label,argv),driver in zip(host_tests.commands(HERE,owner,self.work,self.evidence,sys.executable,include),host_tests.DRIVERS):
            self.run('host-'+label,[*SANDBOX,*argv],timeout=1800)
            result=host_tests.verify_result(driver,self.work/'host-tests'/label)
            summary=parse(ordinary(self.evidence,'host-tests/'+label+'/retention-summary.json').read_bytes())
            # Nested observers have independent immutable blob namespaces, but share
            # the capture's aggregate byte/file/directory ceilings.
            from retention import BOUNDS
            require(self.store.file_count+summary['logical_files']<=BOUNDS['files'] and self.store.total_bytes+summary['logical_bytes']<=BOUNDS['total_bytes'] and self.store.directory_count+summary['directories']<=BOUNDS['directories'],'aggregate host retention ceiling exceeded')
            self.store.file_count+=summary['logical_files'];self.store.total_bytes+=summary['logical_bytes'];self.store.directory_count+=summary['directories']
            self.save('host-'+label,result);self.counts['synthetic_host_suites']+=1
            self.all_sources('after-host-'+label)
        require(hashes=={p.name:file_sha(p) for p in (include/'unicorn').iterdir()},'host header bytes changed')

    def capture_build_inputs(self,phase):
        # Retain all generated compiler inputs and outputs before ephemeral work can vanish.
        # Source checkouts/artifacts were separately authenticated above. Repositories
        # (Git object caches) are not compiler inputs; every other scratch entry is kept.
        for owner,label in [('AnisetteKit','anisette'),('SideSign','sidesign')]:
            scratch=self.work/(label+'-scratch');rows={}
            if not scratch.exists():continue
            for child in sorted(scratch.iterdir()):
                if child.name in ('repositories','checkouts','artifacts'):continue
                if child.is_symlink():
                    before=child.lstat();target=os.fsencode(os.readlink(child));resolved=child.resolve(strict=True)
                    require(stat.S_ISLNK(before.st_mode) and len(target)<=4096 and resolved.is_relative_to(scratch.resolve()),'generated scratch symlink escaped')
                    record=self.store.retain_bytes(target,label=phase+'/'+owner+'/scratch/'+child.name,mode='120000')
                    after=child.lstat();identity=lambda st:(st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
                    require(identity(before)==identity(after) and os.fsencode(os.readlink(child))==target and child.resolve(strict=True)==resolved,'generated scratch symlink mutated')
                    rows[child.name]=dict(record,kind='symlink',target=os.fsdecode(target),resolved_path=str(resolved))
                else:
                    rows[child.name]=self.store.retain_tree(child,label=phase+'/'+owner+'/scratch/'+child.name) if child.is_dir() else self.store.retain_file(child,label=phase+'/'+owner+'/scratch/'+child.name)
            self.save(phase+'/'+owner+'/generated-inputs-and-products',rows)
    def tools(self):
        require(self.run('xcode-version',['xcodebuild','-version']).strip()==TOOLCHAIN['xcode'],'Xcode version mismatch')
        out=self.run('swift-version',['swift','--version'],stdout_only=True);err=ordinary(self.evidence,'logs/swift-version.stderr.log').read_text()
        require(out==TOOLCHAIN['swift_stdout'] and err==TOOLCHAIN['swift_stderr'],'exact Swift stream version mismatch')
        require(self.run('clang-version',['xcrun','clang++','--version']).splitlines()[0]==TOOLCHAIN['clang'],'clang version mismatch')
        self.run('uname',['uname','-a']);sdk=Path(self.run('macos-sdk',['xcrun','--sdk','macosx','--show-sdk-path'],stdout_only=True).strip())
        require(sdk.resolve().is_relative_to(Path(TOOLCHAIN['developer_dir']).resolve()),'SDK outside reviewed Xcode')
        self.save('macos-sdk-raw',self.store.retain_tree(sdk.resolve(strict=True),label='macos-sdk'))
        identities={}
        for tool in ('swift','swiftc','swift-frontend','swift-symbolgraph-extract','clang','clang++','ld','ar','dsymutil','git','xcodebuild'):
            path=Path(self.run('tool-'+tool.replace('+','x'),['xcrun','--find',tool],stdout_only=True).strip())
            identities[tool]=self.store.retain_executable(path,label='tools/'+tool,approved_roots=[Path(TOOLCHAIN['developer_dir']),Path('/usr/bin')])
        for path in (*LAUNCHER_PATHS,sys.executable):
            identities[path]=self.store.retain_executable(Path(path),label='tools/'+Path(path).name,approved_roots=[Path('/usr/bin'),Path(TOOLCHAIN['developer_dir']),Path(sys.executable).resolve(strict=True).parent])
        self.save('tool-identities',identities)
        self.run('network-sandbox',[*SANDBOX,sys.executable,'-c','import socket,errno\ns=socket.socket()\ntry:s.connect(("192.0.2.1",443))\nexcept OSError as e:\n if e.errno not in (errno.EPERM,errno.EACCES):raise\nelse:raise SystemExit("network sandbox did not deny")'])
    def execute(self):
        require(platform.system()=='Darwin' and platform.machine()==TOOLCHAIN['architecture'],'reviewed macOS arm64 required')
        require(os.environ.get('DEVELOPER_DIR')==TOOLCHAIN['developer_dir'],'reviewed Xcode selection required')
        require(not self.work.exists() and not self.evidence.exists(),'fresh isolated work/evidence required')
        require(not self.work.is_relative_to(self.host) and not self.evidence.is_relative_to(self.host) and not self.evidence.is_relative_to(self.work) and not self.work.is_relative_to(self.evidence),'independent work/evidence/host required')
        require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'dedicated capture branch required')
        commit=full_sha(os.environ.get('GITHUB_SHA'));require(git(self.host,'rev-parse','HEAD').decode().strip()==commit,'actual host commit mismatch')
        run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','');require(run.isdigit() and attempt.isdigit() and int(run)>0 and int(attempt)>0,'actual GitHub run identity required')
        for path in ('sources','home','tmp'):(self.work/path).mkdir(parents=True)
        (self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir();self.store=RawStore(self.evidence)
        self.state.update(approved_inputs_sha256=self.approved,source_seal_sha256=SEAL_SHA,owners=self.data['owners'],run={'repository':'NRG-Wardog/LiveContainer','run_id':int(run),'run_attempt':int(attempt),'host_commit':commit,'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()})
        try:
            self.deadline=time.monotonic()+120*60
            self.stage='host-proof';self.host_proof(commit)
            self.stage='toolchain';self.tools()
            self.stage='acquire';self.acquire();self.fetch_artifacts()
            self.stage='resolve';self.resolve('SideSign');self.resolve('AnisetteKit');self.all_sources('after-resolve')
            self.stage='real-package-build';self.build('AnisetteKit');self.build('SideSign');self.capture_build_inputs('before-tests')
            self.stage='finite-safe-tests'
            for lane in LANES:self.tests(lane)
            self.stage='synthetic-host-tests';self.host_tests()
            self.stage='terminal-proof'
            for owner in OWNERS:
                lock=self.roots[owner]/'Package.resolved';require((lock.read_bytes() if lock.exists() else None)==self.locks.get(owner),'build/test changed actual lock')
                self.verify_resolved(owner,'terminal')
            self.all_sources('terminal');self.capture_build_inputs('terminal');self.host_proof(commit)
            require(self.counts==self.data['command_counts'],'finite command/executed test counts mismatch')
            self.state['status']='CAPTURED_FOR_INDEPENDENT_REVIEW';self.stage='captured'
        except Exception as error:
            self.state['primary_error']=type(error).__name__+': '+str(error);raise
        finally:
            settled=bool(self.command_quiescence) and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in self.command_quiescence)
            self.state.update(writers_quiescent=settled,last_stage=self.stage,command_counts=self.counts)
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            if settled:
                # Retain genuine terminal locks even after resolver/build/parser failure.
                for owner,root in self.roots.items():
                    lock=root/'Package.resolved'
                    if lock.is_file() and not lock.is_symlink():(self.evidence/('provenance/'+owner+'.Package.resolved.terminal-observed')).write_bytes(lock.read_bytes())
                if self.stage!='captured':
                    try:self.capture_build_inputs('failed-terminal-observed')
                    except Exception as retention_error:self.state['terminal_retention_error']=type(retention_error).__name__+': '+str(retention_error)
            self.save('result',self.state);self.save('owned-command-groups',self.command_quiescence)
            (self.evidence/'provenance/reviewed-inputs.json').write_bytes(self.raw)
            self.save('retention-summary',self.store.summary())
            if settled:
                index=evidence_index(self.evidence)
                dump(self.evidence/'evidence-index.json',index)



def evidence_index(root):
    """Index every ordinary evidence file; only the exact root index is exempt."""
    root=Path(root);require(root.is_dir() and not root.is_symlink(),'ordinary evidence root required')
    result={}
    for path in sorted(root.rglob('*')):
        mode=path.lstat().st_mode
        require(not stat.S_ISLNK(mode),'linked evidence')
        require(stat.S_ISREG(mode) or stat.S_ISDIR(mode),'special evidence entry')
        if stat.S_ISREG(mode) and path!=root/'evidence-index.json':
            result[str(path.relative_to(root))]=file_sha(path)
    return result


def verify_transport(root):
    result=parse(ordinary(root,'provenance/result.json').read_bytes());require(result.get('writers_quiescent') is True,'writers not settled')
    groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(groups and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in groups),'owned writer receipts incomplete')
    index=parse(ordinary(root,'evidence-index.json').read_bytes());actual=evidence_index(root)
    require(index==actual and {'provenance/result.json','provenance/reviewed-inputs.json','provenance/owned-command-groups.json'}<=set(index),'immutable evidence index mismatch')
    return {'status':'QUIESCENT_INDEX_VERIFIED','files':len(index),'capture_status':result['status']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inputs',required=True,type=Path);p.add_argument('--approved-inputs-sha256');p.add_argument('--host-root',required=True,type=Path);p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--execute',action='store_true');p.add_argument('--check-transport',action='store_true')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data,blockers=validate_inputs(raw,a.host_root,a.approved_inputs_sha256,execute=a.execute)
        if a.check_transport:
            require(not a.execute and a.evidence is not None,'transport requires evidence and no execution');print(json.dumps(verify_transport(a.evidence)));return
        if not a.execute:print(json.dumps({'status':'LOCAL_SOURCE_VALID_FOR_REVIEW','native_execution':False,'production_ready':False,'activation_blockers':blockers+['Independent adapter/workflow/input review and activation anchor required']}));return
        require(a.work is not None and a.evidence is not None,'fresh work and evidence required')
        Gate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256,raw).execute()
    except Exception as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
