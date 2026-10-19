#!/usr/bin/env python3
"""Phase B exact-source unsigned capture. Execution requires independently approved input bytes."""
import argparse,hashlib,json,os,platform,time,sys
from pathlib import Path
from inventory import *
from lifecycle import CommandRunner
from native_build import NativeBuildMixin,LOCK
import source_primitives as primitives
import graph_contract
from prior_phase_a import verify_prior_capture

def detach_retrieval_environment():
    """Remove ephemeral tokens before any proof/build subprocess can inherit them."""
    token=os.environ.pop('GH_TOKEN',None);os.environ.pop('GITHUB_TOKEN',None)
    require(isinstance(token,str) and token,'ephemeral read-only retrieval token required')
    return {**os.environ,'GH_TOKEN':token}

def verify_host_overlay(host,data,raw,commit):
    require(git(host,'rev-list','--parents','-n','1',commit).decode().split()==[commit,SOURCE_LC],'host must be direct single-parent child of exact LC source')
    actual=snapshot(host,SOURCE_LC,commit)
    expected={**data['adapter_files'],'ci/p0loginb/inputs-phase-b.json':sha(raw),WORKFLOW_PATH:sha(ordinary(host,WORKFLOW_PATH).read_bytes()),BUILD_WORKFLOW_PATH:data['ordinary_build_guard']['after_sha256']}
    require(set(actual['changes'])==set(expected),'host overlay contains unknown or old-gate/workflow paths')
    for path,delta in actual['changes'].items():
        if path==BUILD_WORKFLOW_PATH:
            before=git(host,'show',SOURCE_LC+':'+path)
            require(before.count(b'  build:\n')==1 and ordinary(host,path).read_bytes()==before.replace(b'  build:\n',('  build:\n'+BUILD_GUARD).encode(),1),'ordinary workflow differs beyond exact Phase B job guard')
        else:require(delta['before'] is None,'new adapter unexpectedly replaces an existing file')
        require(delta['after']['mode']=='100644' and delta['after']['type']=='blob' and delta['after']['sha256']==expected[path],'host overlay bytes/mode differ')
    for path,(mode,kind,oid) in entries(host,commit).items():
        target=host/path
        if kind=='commit':
            require(not target.is_symlink() and (not target.exists() or target.is_dir() and not list(target.iterdir())),'capture host gitlinks must remain unpopulated');continue
        for parent in target.parents:
            if parent==host:break
            require(not parent.is_symlink(),'host source parent symlink')
        if mode=='120000':require(target.is_symlink(),'host symlink missing');content=os.fsencode(os.readlink(target))
        else:
            require(mode in ('100644','100755') and target.is_file() and not target.is_symlink(),'ordinary host tracked input required')
            require(('100755' if target.stat().st_mode&0o111 else '100644')==mode,'host mode changed');content=target.read_bytes()
        require(hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==oid,'host tracked input changed')
    require(not git(host,'status','--porcelain','--untracked-files=all').strip(),'host checkout dirty')
    require(not git(host,'ls-files','--others','--ignored','--exclude-standard','-z').strip(b'\0'),'ignored host compiler input')
    return {'commit':commit,'tree':actual['tree'],'single_parent':SOURCE_LC,'origin':primitives.verify_origin(host,'https://github.com/NRG-Wardog/LiveContainer.git',commit)}

class Gate(CommandRunner,NativeBuildMixin):
    def __init__(self,data,host,work,evidence,approved,raw,prior_receipts=None):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.approved=approved;self.raw=raw;self.prior_receipts=evidence/'prior-phase-a'
        self.roots={};self.children={};self.command_quiescence=[];self.observed_app_lock=None;self.stage='initialization'
        self.state={'status':'FAILED_OR_INCOMPLETE','phase':'phase-b','source_basis':BASIS,'production_ready':False,'guest_execution':False,'real_ADI_executed':False,'device_validation':False,'app_typechecked':False,'internal_sidebackup_archive_built':False,'distribution_ipa_built':False}
    def clone(self,label,row,root):
        require(not root.is_symlink() and (not root.exists() or not list(root.iterdir())),'fresh source destination required')
        self.run('clone-'+label,['git','clone','--no-checkout',row['repository'],root],cwd=self.work)
        self.run('fetch-'+label,['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']],cwd=self.work)
        self.run('checkout-'+label,['git','-C',root,'checkout','--detach',row['commit']],cwd=self.work)
        self.run('readonly-'+label,['git','-C',root,'config','remote.origin.pushurl','disabled://p0loginb-readonly'],cwd=self.work)
        require(git(root,'rev-parse','HEAD^{tree}').decode().strip()==row['tree'],'acquired source tree differs');primitives.verify_origin(root,row['repository'],row['commit'])
    def acquire_children(self,prefix,root,commit):
        for path,row in graph_contract.child_requirements(prefix,root,commit,self.data['graph']).items():
            relative=path[len(prefix)+1:];child=root/relative
            require(all(not p.is_symlink() for p in child.parents if p!=root and root in p.parents),'linked child destination parent')
            self.clone(path.replace('/','-').lower(),row,child);self.children[path]=child
            owner=graph_contract.OWNER_CHILDREN.get(path)
            if owner:self.roots[owner]=child
            self.acquire_children(path,child,row['commit'])
    def acquire(self):
        for owner,row in self.data['graph']['owners'].items():
            if owner in ('SideSign','minimuxer'):continue
            root=self.work/'sources'/owner;self.clone(owner.lower(),row,root);self.roots[owner]=root;self.acquire_children(owner,root,row['commit'])
        dump(self.evidence/'provenance/source-before.json',self.verify_working_sources())
    def verify_working_sources(self,after_build=False):
        locks={}
        if self.observed_app_lock is not None:locks={'SideStore':{LOCK:hashlib.sha1(b'blob '+str(len(self.observed_app_lock)).encode()+b'\0'+self.observed_app_lock).hexdigest()}}
        return graph_contract.verify_acquired_graph(self.data['graph'],self.roots,self.children,after_build=after_build,observed_locks=locks)
    def execute(self):
        # Reject unresolved inputs and absent exact workflow approval before side effects.
        validate_inputs(self.raw,self.host,self.approved,execution=True)
        retrieval_env=detach_retrieval_environment()
        require(platform.system()=='Darwin' and platform.machine()==TOOLCHAIN['architecture'],'actual reviewed macOS required')
        require(os.environ.get('DEVELOPER_DIR')==TOOLCHAIN['developer_dir'],'wrong Xcode selection')
        require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'isolated reviewed branch required')
        commit=full_sha(os.environ.get('GITHUB_SHA'));run=os.environ.get('GITHUB_RUN_ID','');attempt=os.environ.get('GITHUB_RUN_ATTEMPT','')
        require(run.isdigit() and attempt.isdigit() and int(run)>0 and int(attempt)>0,'actual run identity required')
        require(not self.work.exists() and not self.evidence.exists(),'fresh capture roots required')
        (self.work/'sources').mkdir(parents=True);(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        self.state.update(run={'repository':'NRG-Wardog/LiveContainer','run_id':int(run),'run_attempt':int(attempt),'host_commit':commit,'host_tree':git(self.host,'rev-parse','HEAD^{tree}').decode().strip()},approved_inputs_sha256=self.approved,source_seal_sha256=SEAL_SHA,graph=self.data['graph'])
        try:
            self.deadline=time.monotonic()+120*60
            self.stage='host-proof';dump(self.evidence/'provenance/host-overlay.json',verify_host_overlay(self.host,self.data,self.raw,commit))
            self.stage='self-contained-tests'
            self.run('self-contained-tests',[sys.executable,'-B',self.host/'ci/p0loginb/run_tests.py','--scope','self-contained','--result',self.evidence/'provenance/self-contained-tests.json'],cwd=self.work,timeout=300)
            self.stage='toolchain'
            require(self.run('xcode-version',['xcodebuild','-version'],cwd=self.work).strip()==TOOLCHAIN['xcode'],'Xcode version differs')
            stdout=self.run('swift-version',['swift','--version'],cwd=self.work,stdout_only=True);verify_swift_version(stdout,ordinary(self.evidence,'logs/swift-version.stderr.log').read_text())
            require(self.run('clang-version',['xcrun','clang++','--version'],cwd=self.work).splitlines()[0]==TOOLCHAIN['clang'],'clang version differs')
            self.run('uname',['uname','-a'],cwd=self.work)
            self.stage='acquire';self.acquire()
            self.stage='prior-phase-a'
            current={k:self.state['run'][k] for k in ('repository','run_id','run_attempt','host_commit')}
            helper=self.host/'ci/p0loginb/retrieve_prior.py';inputs=self.host/'ci/p0loginb/inputs-phase-b.json'
            self.run('retrieve-prior',[sys.executable,'-B',helper,'--inputs',inputs,'--output-dir',self.prior_receipts],cwd=self.work,timeout=660,env=retrieval_env)
            retrieval_env.clear()
            helper_raw=ordinary(self.prior_receipts,'retrieval-helper.json').read_bytes()
            dump(self.prior_receipts/'retrieval-receipts.json',{'schema_version':1,'current_run':current,'helper_report_sha256':sha(helper_raw),
                'outer_command':parse(ordinary(self.evidence,'logs/retrieve-prior.command.json').read_bytes()),
                'outer_settlement':parse(ordinary(self.evidence,'logs/retrieve-prior.settlement.json').read_bytes())})
            prior_adapter=self.host/'ci/p0loginb/prior_adapter'
            for name in ('upload-identity.json','independent-review.json','independent-descendant-clearance.json'):
                destination=self.prior_receipts/name;require(not destination.exists(),'fresh original review receipt required')
                destination.write_bytes(ordinary(prior_adapter,name).read_bytes())
            prior=verify_prior_capture(self.data['prior_phase_a'],self.prior_receipts,prior_adapter,self.roots,current,
                inputs_path=inputs,inputs_raw=self.raw,work_root=self.work)
            require(self.data['graph']['prior_artifact']==self.data['prior_phase_a']['expected'],'graph and authenticated prior tuple disagree')
            dump(self.evidence/'provenance/prior-phase-a.json',prior['report'])
            dump(self.evidence/'provenance/source-object-equivalence.json',graph_contract.verify_source_graph(self.roots,self.data['graph'],prior['lock_bytes'],terminal_lock_bytes=prior['lock_bytes']))
            self.stage='prerequisites';self.native_prerequisites()
            self.stage='native-transport';self.transport_build()
            self.stage='unsigned-app-builds';self.app_build()
            dump(self.evidence/'provenance/source-after.json',self.verify_working_sources(after_build=True));verify_host_overlay(self.host,self.data,self.raw,commit)
            require(getattr(self,'app_product_checks_complete',False),'complete actual product checks required')
            self.stage='captured';self.state.update(status='CAPTURED_FOR_INDEPENDENT_REVIEW',app_typechecked=True)
        except Exception as error:self.state['primary_error']=type(error).__name__+': '+str(error);raise
        finally:
            retrieval_env.clear()
            settled=bool(self.command_quiescence) and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in self.command_quiescence)
            self.state.update(writers_quiescent=settled,last_stage=self.stage)
            if not settled:self.state['status']='FAILED_UNSETTLED_WRITERS'
            if settled and 'SideStore' in self.roots:
                lock=self.roots['SideStore']/LOCK
                if lock.is_file() and not lock.is_symlink():(self.evidence/'provenance/SideStore.Package.resolved.final-observed').write_bytes(lock.read_bytes())
            dump(self.evidence/'provenance/result.json',self.state);dump(self.evidence/'provenance/owned-command-groups.json',self.command_quiescence);(self.evidence/'provenance/reviewed-inputs.json').write_bytes(self.raw)
            if settled:dump(self.evidence/'evidence-index.json',{str(p.relative_to(self.evidence)):sha(p.read_bytes()) for p in sorted(self.evidence.rglob('*')) if p.is_file() and p.name!='evidence-index.json'})

def verify_transport(root):
    result=parse(ordinary(root,'provenance/result.json').read_bytes());groups=parse(ordinary(root,'provenance/owned-command-groups.json').read_bytes())
    require(result.get('writers_quiescent') is True and groups and all(r.get('quiescent') is True and r.get('pipesJoined') is True and r.get('leaderReaped') is True and not r.get('errors') for r in groups),'unsettled evidence writers')
    index=parse(ordinary(root,'evidence-index.json').read_bytes());actual={}
    for p in root.rglob('*'):
        require(not p.is_symlink(),'linked evidence')
        if p.is_file() and p.name!='evidence-index.json':actual[str(p.relative_to(root))]=sha(p.read_bytes())
    require(index==actual,'evidence index changed');return {'status':'TRANSPORT_INDEX_CHECK_ONLY','capture_status':result['status']}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('inputs','host-root'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('work','evidence'):p.add_argument('--'+name,type=Path)
    p.add_argument('--approved-inputs-sha256');p.add_argument('--execute',action='store_true');p.add_argument('--check-transport',action='store_true');a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.host_root,a.approved_inputs_sha256)
        if a.execute:
            require(not a.check_transport and all((a.work,a.evidence)),'execution requires exact capture paths')
            Gate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),a.approved_inputs_sha256,raw).execute()
        elif a.check_transport:require(a.evidence is not None,'evidence required');print(json.dumps(verify_transport(a.evidence)))
        else:print(json.dumps({'status':data['status'],'execution_approval':'EXACT_REVIEWED_WORKFLOW_DIGEST_REQUIRED','native_execution':False,'production_ready':False}))
    except Exception as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
