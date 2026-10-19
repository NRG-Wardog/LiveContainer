#!/usr/bin/env python3
"""Exact-source unsigned Phase B capture, gated by authentic inputs and review."""
import argparse,hashlib,json,os,platform,sys,time
from pathlib import Path
from inventory import *
from execution_contract import validate_inputs,INPUT_PATH,ADAPTER,WORKFLOW,BRANCH,CLAIMS
from graph_contract import BASIS,KNOWN
import graph_contract,source_primitives as primitives
from lifecycle import CommandRunner
from native_build import NativeBuildMixin,LOCK
from capture_retention import CaptureRetentionMixin
from retention import RawStore,BOUNDS
from prior_phase_a import verify_prior_capture,REVIEWED_PRIOR_FILES

SOURCE_LC=KNOWN['LiveContainer'][0]
FIXED_PATH='/opt/homebrew/bin:/Users/runner/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin'


def isolated_environment(work):
    env={'PATH':FIXED_PATH,'HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),
         'DEVELOPER_DIR':TOOLCHAIN['developer_dir'],'PYTHONDONTWRITEBYTECODE':'1','LANG':'en_US.UTF-8','LC_ALL':'en_US.UTF-8'}
    return env


def detach_retrieval_environment(base):
    token=os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
    require(isinstance(token,str) and token,'ephemeral read-only retrieval token required')
    return {**base,**{key:os.environ[key] for key in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REF')},'GH_TOKEN':token}


def verify_host_overlay(host,data,raw,commit):
    require(git(host,'rev-parse','HEAD').decode().strip()==commit,'actual host HEAD differs')
    require(git(host,'rev-list','--parents','-n','1',commit).decode().split()==[commit,SOURCE_LC],'host must be sole-parent child of exact LC source')
    actual=snapshot(host,SOURCE_LC,commit)
    expected={**data['adapter_files'],INPUT_PATH:sha(raw),WORKFLOW:sha(ordinary(host,WORKFLOW).read_bytes()),'.github/workflows/build.yml':data['workflow']['build_after_sha256']}
    require(set(actual['changes'])==set(expected),'host overlay has missing or unreviewed paths')
    for path,delta in actual['changes'].items():
        if path=='.github/workflows/build.yml':require(delta['before']['sha256']==data['workflow']['build_before_sha256'],'build guard baseline differs')
        else:require(delta['before'] is None,'adapter unexpectedly replaces source')
        require(delta['after']['mode']=='100644' and delta['after']['type']=='blob' and delta['after']['sha256']==expected[path],'host overlay mode/bytes differ')
    for path,(mode,kind,oid) in entries(host,commit).items():
        target=host/path
        if kind=='commit':
            require(not target.is_symlink() and (not target.exists() or target.is_dir() and not list(target.iterdir())),'capture host gitlinks must remain unpopulated');continue
        for parent in target.parents:
            if parent==host:break
            require(not parent.is_symlink(),'host input parent symlink')
        if mode=='120000':require(target.is_symlink(),'host symlink missing');content=os.fsencode(os.readlink(target))
        else:
            require(mode in ('100644','100755') and target.is_file() and not target.is_symlink(),'ordinary tracked host source required')
            require(('100755' if target.stat().st_mode&0o111 else '100644')==mode,'host input mode differs');content=target.read_bytes()
        require(hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==oid,'host tracked bytes differ')
    require(not git(host,'status','--porcelain','--untracked-files=all').strip(),'dirty host checkout')
    require(not git(host,'ls-files','--others','--ignored','--exclude-standard','-z').strip(b'\0'),'ignored host compiler input')
    return {'commit':commit,'tree':actual['tree'],'single_parent':SOURCE_LC,'origin':primitives.verify_origin(host,'https://github.com/NRG-Wardog/LiveContainer.git',commit)}


def tool_identity(record):
    return {key:record[key] for key in ('requested_path','resolved_path','sha256','mode')}|{'symlinks':[{key:row[key] for key in ('source_path','target','sha256','mode')} for row in record['symlink_chain']]}


class Gate(CaptureRetentionMixin,NativeBuildMixin,CommandRunner):
    def __init__(self,data,host,work,evidence,approved,raw):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved;self.raw=raw
        self.prior_receipts=evidence/'prior-phase-a';self.roots={};self.children={};self.command_quiescence=[]
        self.observed_app_lock=None;self.stage='initialization';self.app_graph_counter=0;self.nested_budget_merged=False
        self.base_env=isolated_environment(work)
        self.state={'status':'FAILED_OR_INCOMPLETE','phase':'phase-b','source_basis':BASIS,'compiled_final_commit':False,'internal_sidebackup_archive_built':False,'new_app_executables_unsigned':False,'inherited_prebuilt_signatures_separately_inventoried':False,**CLAIMS}
    def run(self,name,args,**kwargs):
        kwargs.setdefault('env',self.base_env)
        builds=('idevice-build','sidestore-build','livecontainer-build')
        if name in builds:self.capture_generated('before-'+name)
        result=CommandRunner.run(self,name,args,**kwargs)
        if name in builds:self.capture_generated('after-'+name)
        if name=='sidestore-frozen-resolve':
            lock=ordinary(self.roots['SideStore'],LOCK).read_bytes()
            require(lock==self.observed_app_lock,'frozen app lock differs')
            (self.evidence/'provenance/SideStore.Package.resolved.frozen-observed').write_bytes(lock)
        return result
    def clone(self,label,row,root):
        require(not root.is_symlink() and (not root.exists() or not list(root.iterdir())),'fresh source destination required')
        self.run('clone-'+label,['git','clone','--no-checkout',row['repository'],root],cwd=self.work)
        self.run('fetch-'+label,['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']],cwd=self.work)
        self.run('checkout-'+label,['git','-C',root,'checkout','--detach',row['commit']],cwd=self.work)
        self.run('readonly-'+label,['git','-C',root,'config','remote.origin.pushurl','disabled://p0defensiveb-readonly'],cwd=self.work)
        require(git(root,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'acquired source tree differs')
        primitives.verify_origin(root,row['repository'],row['commit'])
    def acquire_children(self,prefix,root,commit):
        for path,row in graph_contract.child_requirements(prefix,root,commit,self.data['graph']).items():
            relative=path[len(prefix)+1:];child=root/relative
            require(all(not p.is_symlink() for p in child.parents if p!=root and root in p.parents),'linked child destination parent')
            self.clone(path.replace('/','-').replace('_','-').lower(),row,child);self.children[path]=child
            owner=graph_contract.OWNER_CHILDREN.get(path)
            if owner:self.roots[owner]=child
            self.acquire_children(path,child,row['commit'])
    def acquire(self):
        for owner,row in self.data['graph']['owners'].items():
            if owner in ('SideSign','minimuxer'):continue
            root=self.work/'sources'/owner;self.clone(owner.lower(),row,root);self.roots[owner]=root;self.acquire_children(owner,root,row['commit'])
        self.retained_sources('before')
    def verify_working_sources(self,after_build=False):
        locks={}
        if self.observed_app_lock is not None:locks={'SideStore':{LOCK:hashlib.sha1(b'blob '+str(len(self.observed_app_lock)).encode()+b'\0'+self.observed_app_lock).hexdigest()}}
        return graph_contract.verify_acquired_graph(self.data['graph'],self.roots,self.children,after_build=after_build,observed_locks=locks)
    def capture_cargo_metadata(self,when,before=None):
        proof=NativeBuildMixin.capture_cargo_metadata(self,when,before)
        self.capture_cargo_raw('cargo-'+when);return proof
    def resolved_app_graph(self):
        result=NativeBuildMixin.resolved_app_graph(self);self.app_graph_counter+=1
        self.retained_app_dependencies('app-resolved-'+str(self.app_graph_counter),result);return result
    def retain_prior_originals(self):
        config=self.prior_receipts/'gh-config'
        require(not config.is_symlink() and config.is_dir() and not any(config.iterdir()),'empty ordinary prior gh-config directory required')
        rows={}
        for path in sorted(self.prior_receipts.iterdir()):
            if path.name=='gh-config':continue
            require(path.is_file() and not path.is_symlink(),'ordinary original prior receipt required')
            length=path.stat().st_size
            if path.name=='artifact.zip':
                from phase_a_raw_replay import MAX_ARCHIVE
                require(length<=MAX_ARCHIVE,'prior archive ceiling exceeded')
                self.merge_nested_budget({'logical_files':1,'logical_bytes':length,'directories':0})
                digest=hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
                rows[path.name]={'original_raw_path':str(path.relative_to(self.evidence)),'length':length,'sha256':digest.hexdigest()}
            else:rows[path.name]=self.store.retain_file(path,label='prior-original/'+path.name)
        return rows
    def run_consumers(self):
        from product_plan import fixed_commands
        from consumer_contract import validate_results
        budget={'files':BOUNDS['files']-self.store.file_count,'total_bytes':BOUNDS['total_bytes']-self.store.total_bytes,'directories':BOUNDS['directories']-self.store.directory_count}
        self.save('consumer-budget',budget)
        commands=fixed_commands(self.host/ADAPTER,self.roots,self.work,self.evidence,sys.executable)
        for row in commands[:2]:self.run(row['label'],row['argv'],cwd=Path(row['cwd']),timeout=row['timeout_seconds'])
        receipt=parse(ordinary(self.evidence,'provenance/consumer-tests.json').read_bytes())
        require(receipt['status']=='passed' and receipt['sources_before']==receipt['sources_after'],'exact consumer source/results failure')
        require(validate_results(receipt['owners'])==receipt['totals'],'consumer totals differ')
        summary=parse(ordinary(self.evidence,'consumer-nested/retention-summary.json').read_bytes())
        require(receipt['nested_capture']=={'directory':str(self.evidence/'consumer-nested'),**summary},'consumer nested summary differs')
        require(summary['limits']==BOUNDS and summary['effective_limits']==budget,'consumer aggregate remaining budget differs')
        self.merge_consumer_retention();self.state['consumer_tests']=receipt['totals']
    def merge_consumer_retention(self):
        path=self.evidence/'consumer-nested/retention-summary.json'
        if path.exists() and not self.nested_budget_merged:
            self.merge_nested_budget(parse(ordinary(path.parent,path.name).read_bytes()));self.nested_budget_merged=True
    def app_build(self):
        # Existing full production builds and product checks remain intact. The
        # synthetic integrity fixture uses only the already resolved dependency.
        NativeBuildMixin.app_build(self)
        self.stage='library-integrity-exact8'
        from integrity_runtime import run_integrity,CASE_IDS
        report=run_integrity(self)
        expected=self.data['graph']['owners']['SideSign']
        require(report['status']=='CAPTURED_FOR_INDEPENDENT_REVIEW' and
                (report['source_commit'],report['source_tree'])==(expected['commit'],expected['tree']),
                'integrity runtime must bind actual compiled SideSign source child')
        require(report['results']=={'tests':8,'failures':0,'errors':0,'skipped':0,
                'case_ids':list(CASE_IDS),'successful_case_ids':list(CASE_IDS)},'complete exact8 integrity runtime required')
        self.state['library_integrity_tests']=report['results']
    def verify_resources(self):
        import resource_contract as resources
        app=self.work/'livecontainer-derived/Build/Products/Release-iphoneos/LiveContainer.app'
        report=resources.verify_app(app,self.roots['LiveContainer']);report['raw_files']={}
        for path in resources.RESOURCE_NAMES:
            record=self.store.retain_file(ordinary(app,path),label='compiled-resources/'+path)
            require(record['sha256']==report['compiledResourceFiles'][path]['sha256'] and record['length']==report['compiledResourceFiles'][path]['bytes'],'compiled resource changed during retention')
            report['raw_files'][path]=record
        self.save('compiled-resources',report);self.state['compiled_resources']={'catalog_keys':2088,'plural_language_rows':24,'permission_languages':7,'permission_keys':32,'runtime_plural_selection':False}
    def verify_terminal_products(self):
        from macho_contract import capture_app_inventory
        rows={}
        for owner,folder in (('SideStore','sidestore-derived'),('LiveContainer','livecontainer-derived')):
            app=self.work/folder/'Build/Products/Release-iphoneos'/(owner+'.app')
            actual=capture_app_inventory(app,owner)
            original=parse(ordinary(self.evidence,'provenance/product-inventory-'+owner+'.json').read_bytes())
            require(actual==original and actual['complete'],'terminal product bytes/modes differ')
            rows[owner]=actual
        self.save('terminal/product-inventories',rows)
    def verify_tool_stability(self,before,after):
        require(set(before)<=set(after),'terminal tool identity missing')
        require({k:tool_identity(v) for k,v in before.items()}=={k:tool_identity(after[k]) for k in before},'actual compiler/launcher bytes or links changed')
    def execute(self):
        # All unresolved/approval checks occur before mkdir, subprocess, token use.
        validate_inputs(self.raw,self.host,self.approved,execution=True)
        require(platform.system()=='Darwin' and platform.machine()==TOOLCHAIN['architecture'],'reviewed actual macOS arm64 required')
        require(os.environ.get('DEVELOPER_DIR')==TOOLCHAIN['developer_dir'],'wrong selected Xcode')
        require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'isolated reviewed branch required')
        commit=full_sha(os.environ.get('GITHUB_SHA'));run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(run.isdigit() and attempt.isdigit() and int(run)>0 and int(attempt)>0,'actual run identity required')
        require(not self.work.exists() and not self.evidence.exists() and self.host not in self.work.parents and self.host not in self.evidence.parents and self.work not in self.evidence.parents and self.evidence not in self.work.parents and self.work!=self.evidence,'fresh independent capture roots required')
        retrieval_env=detach_retrieval_environment(self.base_env)
        (self.work/'sources').mkdir(parents=True);(self.work/'home').mkdir();(self.work/'tmp').mkdir()
        (self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        self.store=RawStore(self.evidence);self.deadline=time.monotonic()+7200;primary=None
        self.state.update(run={'repository':'NRG-Wardog/LiveContainer','run_id':int(run),'run_attempt':int(attempt),'host_commit':commit,'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()},approved_inputs_sha256=self.approved,graph=self.data['graph'])
        try:
            self.stage='host-proof';self.save('host-overlay',verify_host_overlay(self.host,self.data,self.raw,commit))
            self.stage='self-contained-tests'
            self.run('self-contained-tests',[sys.executable,'-B',self.host/ADAPTER/'run_tests.py','--result',self.evidence/'provenance/self-contained-tests.json'],cwd=self.work,timeout=600)
            self.stage='toolchain'
            require(self.run('xcode-version',['xcodebuild','-version'],cwd=self.work).strip()==TOOLCHAIN['xcode'],'Xcode identity differs')
            stdout=self.run('swift-version',['swift','--version'],cwd=self.work,stdout_only=True);verify_swift_version(stdout,ordinary(self.evidence,'logs/swift-version.stderr.log').read_text())
            require(self.run('clang-version',['xcrun','clang++','--version'],cwd=self.work).splitlines()[0]==TOOLCHAIN['clang'],'clang identity differs')
            self.run('uname',['uname','-a'],cwd=self.work)
            self.tools_before=self.capture_toolchain('before',include_sdk=True)
            self.stage='acquire';self.acquire()
            self.stage='prior-phase-a';current={key:self.state['run'][key] for key in ('repository','run_id','run_attempt','host_commit')}
            self.run('retrieve-prior',[sys.executable,'-B',self.host/ADAPTER/'retrieve_prior.py','--inputs',self.host/INPUT_PATH,'--output-dir',self.prior_receipts],cwd=self.work,timeout=1800,env=retrieval_env);retrieval_env.clear()
            helper_raw=ordinary(self.prior_receipts,'retrieval-helper.json').read_bytes()
            dump(self.prior_receipts/'retrieval-receipts.json',{'schema_version':1,'current_run':current,'helper_report_sha256':sha(helper_raw),'outer_command':parse(ordinary(self.evidence,'logs/retrieve-prior.command.json').read_bytes()),'outer_settlement':parse(ordinary(self.evidence,'logs/retrieve-prior.settlement.json').read_bytes())})
            for name in REVIEWED_PRIOR_FILES:
                target=self.prior_receipts/name;require(not target.exists(),'fresh original prior receipt required');target.write_bytes(ordinary(self.host/ADAPTER/'reviewed',name).read_bytes())
            prior=verify_prior_capture(self.data['prior_phase_a'],self.prior_receipts,self.host/ADAPTER/'prior_adapter',self.roots,current,inputs_path=self.host/INPUT_PATH,inputs_raw=self.raw,work_root=self.work)
            self.save('prior-phase-a',prior['report']);self.save('source-object-equivalence',graph_contract.verify_source_graph(self.roots,self.data['graph'],prior['lock_bytes'],terminal_lock_bytes=prior['lock_bytes']))
            self.save('prior-authenticated-raw',self.retain_prior_originals())
            self.stage='consumer-exact38';self.run_consumers();self.retained_sources('after-consumers')
            self.stage='native-prerequisites';self.native_prerequisites();self.tools_native=self.capture_toolchain('native-before')
            self.verify_tool_stability(self.tools_before,self.tools_native);self.capture_native_inputs('native-before')
            self.stage='native-transport';self.transport_build();self.retained_sources('after-transport',after_build=True)
            self.stage='unsigned-app-builds';self.app_build();self.verify_resources()
            self.retained_sources('after',after_build=True);verify_host_overlay(self.host,self.data,self.raw,commit)
            require(getattr(self,'app_product_checks_complete',False),'complete actual product checks required')
            self.stage='captured';self.state.update(status='CAPTURED_FOR_INDEPENDENT_REVIEW',app_typechecked=True)
        except Exception as error:
            primary=error;self.state['primary_error']=type(error).__name__+': '+str(error)
        finally:
            retrieval_env.clear()
            settled=bool(self.command_quiescence) and all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in self.command_quiescence)
            self.state.update(writers_quiescent=settled,last_stage=self.stage)
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            if settled:
                try:
                    self.merge_consumer_retention()
                    for owner,relative in (('SideSign','Package.resolved'),('SideStore',LOCK)):
                        if owner in self.roots:
                            raw=ordinary(self.roots[owner],relative).read_bytes()
                            (self.evidence/('provenance/'+owner+'.Package.resolved.terminal-observed')).write_bytes(raw)
                            self.save('terminal/'+owner+'-lock',self.store.retain_bytes(raw,label='terminal/'+owner+'/lock'))
                            if owner=='SideStore' and self.observed_app_lock is not None:require(raw==self.observed_app_lock,'terminal app lock drift')
                    if set(self.roots)==set(graph_contract.OWNERS):self.retained_sources('terminal',after_build=hasattr(self,'native_env'))
                    self.capture_generated('terminal')
                    if getattr(self,'app_product_checks_complete',False):self.verify_terminal_products()
                    if hasattr(self,'tools_before'):
                        terminal=self.capture_toolchain('terminal',include_sdk=True);self.verify_tool_stability(getattr(self,'tools_native',self.tools_before),terminal)
                    if hasattr(self,'tools_native'):self.capture_native_inputs('terminal')
                    if self.observed_app_lock is not None:self.resolved_app_graph()
                    self.save('retention-summary',{**self.store.summary(),'aggregate_logical_usage_includes_nested':True,'unique_blobs_scope':'primary_blobs_namespace_only','consumer_budget_merged':self.nested_budget_merged})
                except Exception as error:
                    self.state['terminal_error']=type(error).__name__+': '+str(error);self.state['status']='FAILED_TERMINAL_RETENTION_OR_IDENTITY'
                    if primary is None:primary=error
            # Terminal tool commands also own writers, so re-evaluate settlement.
            settled=bool(self.command_quiescence) and all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in self.command_quiescence)
            self.state['writers_quiescent']=settled
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            if self.state['status']!='CAPTURED_FOR_INDEPENDENT_REVIEW':self.state['app_typechecked']=False
            self.save('result',self.state);self.save('owned-command-groups',self.command_quiescence)
            (self.evidence/'provenance/reviewed-inputs.json').write_bytes(self.raw)
            if settled:dump(self.evidence/'evidence-index.json',evidence_inventory(self.evidence))
        if primary is not None:raise primary
        require(self.state['status']=='CAPTURED_FOR_INDEPENDENT_REVIEW','capture did not complete')


def evidence_inventory(root):
    result={};total=0;directories=0
    for path in root.rglob('*'):
        require(not path.is_symlink(),'linked evidence path')
        if path.is_dir():directories+=1;require(directories<=BOUNDS['directories'],'evidence directory ceiling exceeded')
        elif path.is_file() and path!=root/'evidence-index.json':
            limit=8*1024**3 if path==root/'prior-phase-a/artifact.zip' else BOUNDS['file_bytes']
            require(path.stat().st_size<=limit,'evidence file ceiling exceeded')
            total+=path.stat().st_size;require(total<=BOUNDS['total_bytes'] and len(result)<BOUNDS['files'],'aggregate evidence ceiling exceeded')
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
            result[str(path.relative_to(root))]=digest.hexdigest()
        else:require(path.is_file(),'special evidence file')
    return dict(sorted(result.items()))


def verify_transport(root):
    result=parse(ordinary(root,'provenance/result.json').read_bytes());groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(result.get('compiled_final_commit') is False and result.get('writers_quiescent') is True and groups and all(row.get('quiescent') is True and row.get('pipesJoined') is True and row.get('leaderReaped') is True and not row.get('errors') for row in groups),'unsettled evidence writers or unsupported final-commit claim')
    require(parse(ordinary(root,'evidence-index.json').read_bytes())==evidence_inventory(root),'evidence index differs')
    return {'status':'TRANSPORT_INDEX_CHECK_ONLY','capture_status':result['status'],'compiled_final_commit':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('inputs','host-root'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('work','evidence'):p.add_argument('--'+name,type=Path)
    p.add_argument('--approved-inputs-sha256');p.add_argument('--execute',action='store_true');p.add_argument('--check-transport',action='store_true');a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.host_root,a.approved_inputs_sha256)
        if a.execute:
            require(not a.check_transport and a.work is not None and a.evidence is not None,'exact separate capture paths required')
            Gate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256,raw).execute()
        elif a.check_transport:require(a.evidence is not None,'evidence root required');print(json.dumps(verify_transport(a.evidence)))
        else:print(json.dumps({'status':data['status'],'execution_approval':'EXACT_INDEPENDENT_WORKFLOW_DIGEST_REQUIRED','native_execution':False,'compiled_final_commit':False}))
    except Exception as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
