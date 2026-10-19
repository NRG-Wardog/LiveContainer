#!/usr/bin/env python3
"""Bounded Linux-only successor of the reviewed p0cxx allocation capture.

The old generic source constants are not imported or weakened. The original
allocation command/result checks remain exact in allocation_contract.py; full
successor commit/tree/parent/blob and header seals are enforced by inventory.
Local replay is never an authenticated workflow capture or readiness evidence.
"""
import argparse,json,os,platform,re,shutil,subprocess,sys,time
from pathlib import Path
from inventory import *
from source_primitives import verify_origin
from lifecycle import CommandRunner
from retention import RawStore
from evidence import safe_index,settled,verify_transport
from host_contract import DRIVERS,extract_headers,header_proof,verify_result

def linux_sandbox():
    uid,gid=os.getuid(),os.getgid()
    require(uid>0 and gid>0,'non-root capture runner UID/GID required')
    path=os.environ.get('PATH','');home=os.environ.get('HOME','')
    require(path and Path(home).is_absolute(),'actual runner PATH/HOME required')
    return ['sudo','-n','/usr/bin/unshare','--net','--','/usr/bin/setpriv',
            '--reuid='+str(uid),'--regid='+str(gid),'--clear-groups',
            '--inh-caps=-all','--ambient-caps=-all','--bounding-set=-all','--no-new-privs','--',
            '/usr/bin/env','-i','PATH='+path,'HOME='+home,'PYTHONDONTWRITEBYTECODE=1', 'LANG=C.UTF-8']

def namespace_probe(uid,gid,compiler):
    return ('import os,json,shutil,socket\n'
            'def check(ok,message):\n'
            ' if not ok: raise SystemExit(message)\n'
            'expected='+repr({'uid':uid,'gid':gid,'compiler':str(compiler)})+'; '
            'actual={"uid":os.getuid(),"gid":os.getgid(),"compiler":shutil.which("c++")}; '
            'check(actual==expected, "sandbox identity/compiler differs"); '
            'check(os.getgroups()==[], "sandbox supplementary groups retained"); '
            'status=open("/proc/self/status").read(); '
            'check(all(int(line.split()[1],16)==0 for line in status.splitlines() if line.startswith(("CapInh:","CapPrm:","CapEff:","CapBnd:","CapAmb:"))), "sandbox capabilities retained"); '
            's=socket.socket(); s.settimeout(1);\n'
            'try: s.connect(("1.1.1.1",443))\n'
            'except OSError: pass\n'
            'else: raise SystemExit("network sandbox did not deny")\n'
            'actual.update(pid=os.getpid(),pgid=os.getpgid(0),sid=os.getsid(0)); print(json.dumps(actual,sort_keys=True))')

def verify_host(host,data):
    actual=os.environ.get('GITHUB_SHA','');require(re.fullmatch('[0-9a-f]{40}',actual),'actual runner commit required')
    require(git(host,'rev-parse','HEAD').decode().strip()==actual,'host checkout differs from runner')
    require(git(host,'show','-s','--format=%P','HEAD').decode().strip()==HOST_BASE,'capture overlay must have exact sole host parent')
    require(git(host,'rev-parse',HOST_BASE+'^{tree}').decode().strip()==HOST_TREE,'capture base tree differs')
    verify_capture_host_checkout(host,actual)
    expected=set(data['adapter_files'])|{'ci/p0defensive_linux/inputs-linux.json',BUILD,WORKFLOW}
    changed=set(git(host,'diff','--name-only',HOST_BASE,'HEAD').decode().splitlines())
    require(changed==expected,'capture-only host delta differs')
    require(git(host,'show',HOST_BASE+':'+BUILD)==ordinary(HERE,'reviewed/capture-host-build.before.yml').read_bytes(),'ordinary-build base bytes differ')
    return {'commit':actual,'tree':git(host,'rev-parse','HEAD^{tree}').decode().strip(),'parent':HOST_BASE}

class LinuxGate(CommandRunner):
    def __init__(self,data,host,work,evidence,raw):
        self.data=data;self.host=host;self.work=work;self.evidence=evidence;self.raw=raw;self.command_quiescence=[]
        self.deadline=time.monotonic()+1500
    def capture(self,source=None,archive=None,local=False):
        require(platform.system()=='Linux','actual Linux host required')
        require(not self.work.exists() and not self.work.is_symlink() and not self.evidence.exists() and not self.evidence.is_symlink(),'fresh work/evidence required')
        self.work.mkdir(parents=True);(self.evidence/'logs').mkdir(parents=True);(self.evidence/'provenance').mkdir()
        store=RawStore(self.evidence);seal=source_seal();stage='identity'
        state={'status':'FAILED_OR_INCOMPLETE','basis':BASIS,'authenticated_capture':not local,'guest_execution':False,'engine_linked':False,'engine_executed':False,'proprietary_input':False,'device_validation':False,'production_ready':False,'ipa_built':False,'retention_errors':[],'local_only':local,'approval_anchor':'REVIEW_REQUIRED' if local else sha(self.raw)}
        try:
            if local:
                require(source is not None and archive is not None,'local source and existing archive required')
                state['origin']='LOCAL_REPLAY_ONLY; no fresh authenticated fetch';sandbox=[]
            else:
                require(os.environ.get('GITHUB_REPOSITORY')=='NRG-Wardog/LiveContainer' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'exact isolated GitHub workflow identity required')
                for k in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT'):require(os.environ.get(k,'').isdigit() and int(os.environ[k])>0,'positive actual run identity required')
                state['host']=verify_host(self.host,self.data);state['run']={'id':int(os.environ['GITHUB_RUN_ID']),'attempt':int(os.environ['GITHUB_RUN_ATTEMPT']),'url':'https://github.com/NRG-Wardog/LiveContainer/actions/runs/'+os.environ['GITHUB_RUN_ID']}
                source=self.work/'AnisetteKit';archive=self.work/'Unicorn.xcframework.zip'
                self.run('source-clone',['git','clone','--no-checkout',seal['repository'],source],timeout=300)
                self.run('source-fetch',['git','-C',source,'fetch','--no-tags','--no-recurse-submodules','origin',seal['commit']],timeout=300)
                self.run('source-checkout',['git','-C',source,'checkout','--detach',seal['commit']])
                verify_origin(source,seal['repository'],seal['commit'])
                self.run('source-disable-push',['git','-C',source,'config','remote.origin.pushurl','disabled://p0-capture-readonly'])
                self.run('header-archive-download',['curl','--fail','--location','--proto','=https','--proto-redir','=https','--output',archive,seal['archive_url']],timeout=300)
                sandbox=linux_sandbox()
            state['network_denial']='NOT_ESTABLISHED_LOCAL_REPLAY' if local else 'LINUX_NETWORK_NAMESPACE'
            source=source.resolve();archive=archive.resolve();stage='source-and-header-binding'
            dump(self.evidence/'provenance/source-before.json',verify_source(source))
            dump(self.evidence/'provenance/source-raw.json',store.retain_git_tree(source,seal['commit'],label='exact-reviewed-source'))
            # Complete committed source and exact binary archive are retained. Only
            # twelve sealed headers are extracted; no engine payload is run/linked.
            raw_archive=store.retain_file(archive,label='pinned-unicorn-header-archive')
            headers=self.work/'headers';extract_headers(archive,headers)
            dump(self.evidence/'provenance/header-archive.json',{'url':seal['archive_url'],'sha256':seal['archive_sha256'],'raw':raw_archive,'headers':header_proof(headers),'engine_linked':False,'engine_executed':False})
            dump(self.evidence/'provenance/headers-raw.json',store.retain_tree(headers,label='exact-12-headers'))
            stage='toolchain';compiler=Path(shutil.which('c++') or '');require(compiler.is_absolute(),'C++ compiler required')
            if not local:
                probe=self.run('network-sandbox',[*sandbox,sys.executable,'-c',namespace_probe(os.getuid(),os.getgid(),compiler)],strict_stderr=True)
                identity=parse(probe)
                require(set(identity)=={'uid','gid','compiler','pid','pgid','sid'} and {k:identity[k] for k in ('uid','gid','compiler')}=={'uid':os.getuid(),'gid':os.getgid(),'compiler':str(compiler)},'actual sandbox payload identity/compiler proof differs')
                require(all(type(identity[k]) is int and identity[k]>0 for k in ('pid','pgid','sid')) and identity['pgid']==identity['sid']==self.command_quiescence[-1]['pgid'],'namespace payload escaped the owned outer process group/session')
                state['sandbox_probe_identity']=identity
                state['payload_identity']={'uid':os.getuid(),'gid':os.getgid(),'supplementary_groups':[],'capabilities':'all zero','compiler':str(compiler)}
            tools={}
            for name,path in [('cxx',compiler),('python',Path(sys.executable)),('assembler',Path(shutil.which('as') or '')),('linker',Path(shutil.which('ld') or ''))]:
                require(path.is_absolute(),'required native tool missing');tools[name]=store.retain_executable(path,label=name,approved_roots=[Path('/usr'),Path('/opt')])
            self.run('compiler-version',[str(compiler),'--version']);self.run('python-version',[sys.executable,'--version'])
            cc1=self.run('compiler-frontend',[str(compiler),'-print-prog-name=cc1plus'],strict_stderr=True).strip();require(Path(cc1).is_absolute(),'compiler frontend path missing')
            tools['cc1plus']=store.retain_executable(Path(cc1),label='cc1plus',approved_roots=[Path('/usr'),Path('/opt')])
            dump(self.evidence/'provenance/tools-raw.json',tools)
            results={}
            for driver in DRIVERS:
                validate_inputs(self.raw,self.host)
                label=driver.removesuffix('.py').replace('_','-');stage=label
                output=self.work/'output'/label;temporary=self.work/'temporary'/label;nested=self.evidence/'nested'/label
                args=[*sandbox,sys.executable,'-B',str(HERE/'run_host_test.py'),'--owner',str(source),'--driver',driver,'--output',str(output),'--temporary',str(temporary),'--evidence',str(nested),'--unicorn-include',str(headers),'--compiler',str(compiler),'--expected-uid',str(os.getuid()),'--expected-gid',str(os.getgid())]
                self.run(label,args,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),strict_stderr=True,timeout=900)
                results[driver]=verify_result(driver,output,nested,source,headers,temporary,compiler)
                dump(self.evidence/'provenance'/('final-output-'+label+'.json'),store.retain_tree(output,label=label+'-final-output'))
                header_proof(headers);verify_source(source)
            require(sum(row['checks'] for row in results.values())==4290,'full fixed assertion total differs')
            state['results']=results;state['checks']=4290;stage='captured'
            dump(self.evidence/'provenance/source-after.json',verify_source(source));state['status']='LOCAL_HOST_REPLAY_FOR_REVIEW' if local else 'CAPTURED_FOR_INDEPENDENT_REVIEW'
        except BaseException as error:
            state['primary_error']=type(error).__name__+': '+str(error);raise
        finally:
            state['last_stage']=stage;state['writers_quiescent']=settled(self.command_quiescence)
            if not state['writers_quiescent']:state['retention_errors'].append('unsettled or unknown command writers; no index')
            dump(self.evidence/'provenance/owned-command-groups.json',self.command_quiescence)
            dump(self.evidence/'provenance/retention-summary.json',store.summary())
            (self.evidence/'provenance/inputs-linux.json').write_bytes(self.raw)
            # Retain the exact entire adapter and provenance used by this capture.
            try:
                validate_inputs(self.raw,self.host)
                dump(self.evidence/'provenance/adapter-raw.json',store.retain_tree(HERE,label='capture-adapter'))
            except BaseException as error:state['retention_errors'].append('adapter retention: '+str(error))
            if state['retention_errors']:state['status']='FAILED_RETENTION_OR_SETTLEMENT'
            dump(self.evidence/'provenance/result.json',state)
            if state['writers_quiescent'] and not state['retention_errors']:
                dump(self.evidence/'evidence-index.json',safe_index(self.evidence))
                verify_transport(self.evidence)
            if state['retention_errors'] and 'primary_error' not in state:raise ValueError('retention/settlement incomplete')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,default=HERE/'inputs-linux.json');p.add_argument('--host-root',type=Path,default=HERE.parents[1]);p.add_argument('--approved-inputs-sha256')
    p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--source',type=Path);p.add_argument('--archive',type=Path)
    group=p.add_mutually_exclusive_group();group.add_argument('--execute',action='store_true');group.add_argument('--local-host-replay',action='store_true');group.add_argument('--check-transport',action='store_true')
    a=p.parse_args()
    try:
        raw=a.inputs.read_bytes();data=validate_inputs(raw,a.host_root,a.approved_inputs_sha256,execute=a.execute)
        if a.check_transport:print(json.dumps(verify_transport(a.evidence)));return
        if not a.execute and not a.local_host_replay:print(json.dumps({'status':'LOCAL_PROPOSAL_VALID','approval_anchor':'REVIEW_REQUIRED','native_execution':False,'production_ready':False}));return
        require(a.work is not None and a.evidence is not None,'fresh work/evidence paths required')
        LinuxGate(data,a.host_root.resolve(),a.work.resolve(),a.evidence.resolve(),raw).capture(source=a.source,archive=a.archive,local=a.local_host_replay)
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as error:p.exit(2,'BLOCKED: '+str(error)+'\n')
if __name__=='__main__':main()
