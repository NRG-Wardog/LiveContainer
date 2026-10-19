"""Original defensive diagnostic Phase A artifact replay against the frozen emitter."""
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import posixpath
import re
import stat
import zipfile
from phase_a_raw_replay import RawReplay,parse,sha,require,object_id,tree_object,safe_path

FALSE_SCOPE=('production_ready','build_admission','ipa_built','guest_execution','real_ADI_executed','live_provider_or_apple_requests','device_validation','app_typechecked')

def value(files,name):
    require(name in files,'missing original evidence: '+name)
    return parse(files[name])

def absolute(path):
    require(isinstance(path,str) and path.startswith('/') and '\\' not in path and '\0' not in path and all(p not in ('','.','..') for p in path.split('/')[1:]),'canonical absolute captured path required')
    return path

def inside(path,root):
    absolute(path);absolute(root);return path==root or path.startswith(root+'/')

def commit_identity(raw,commit,tree,parents=None):
    require(object_id('commit',raw)==commit,'original Git commit object changed')
    headers=raw.split(b'\n\n',1)[0].splitlines();trees=[line[5:].decode() for line in headers if line.startswith(b'tree ')]
    require(trees==[tree],'original Git commit tree differs')
    if parents is not None:require([line[7:].decode() for line in headers if line.startswith(b'parent ')]==parents,'original Git commit parent differs')

def listing_identity(raw,entries):
    require(not raw or raw.endswith(b'\0'),'truncated original Git listing')
    actual={}
    for row in filter(None,raw.split(b'\0')):
        header,name=row.split(b'\t',1);name=os.fsdecode(name);safe_path(name)
        require(name not in actual,'duplicate original Git listing path');actual[name]=tuple(header.decode().split())
    require(actual==entries,'original Git listing differs from raw tree')

def context_from_commands(files,gate,data):
    first=value(files,'logs/xcode-version.command.json');work=absolute(first['cwd'])
    roots={owner:work+'/sources/'+owner for owner in data['owners']}
    network=value(files,'logs/network-sandbox.command.json')['argv'];python=absolute(network[len(gate.SANDBOX)])
    label=gate.host_tests.DRIVERS[0].removesuffix('.py').replace('_','-')
    argv=value(files,'logs/host-'+label+'.command.json')['argv'];start=len(gate.SANDBOX)
    require(argv[start]==python and argv[start+1]=='-B','host Python launcher changed')
    wrapper=absolute(argv[start+2]);suffix='/ci/p0defensive/run_host_test.py'
    require(wrapper.endswith(suffix),'host adapter path differs');host=wrapper[:-len(suffix)];absolute(host)
    evidence=absolute(argv[argv.index('--evidence')+1]);suffix='/host-tests/'+label
    require(evidence.endswith(suffix),'host evidence path differs');evidence=evidence[:-len(suffix)]
    require(not any(inside(a,b) for a,b in ((host,work),(work,host),(host,evidence),(evidence,host),(work,evidence),(evidence,work))),'capture roots overlap')
    env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin:'+data['toolchain']['developer_dir']+'/Toolchains/XcodeDefault.xctoolchain/usr/bin','HOME':work+'/home','TMPDIR':work+'/tmp','DEVELOPER_DIR':data['toolchain']['developer_dir'],'PYTHONDONTWRITEBYTECODE':'1'}
    return {'work':work,'host':host,'evidence':evidence,'python':python,'environment':env,'roots':roots}

DIAGNOSTIC_TOOL_PROBES=('swift','swiftc','swift-frontend','swift-symbolgraph-extract','clang','clang++','ld','ar','dsymutil','git','xcodebuild','nm','otool')

def tool_probe_names(gate):
    # Exact tuple comes from the independently reviewed diagnostic emitter.
    values=[value for value in gate.Gate.tools.__code__.co_consts if isinstance(value,tuple) and value and value[0]=='swift']
    require(values==[DIAGNOSTIC_TOOL_PROBES],'unreviewed diagnostic tool-probe tuple')
    return DIAGNOSTIC_TOOL_PROBES

def ordered_commands(gate,data,context):
    """Literal frozen Gate.execute order, with argv delegated to its contracts."""
    work=context['work'];roots=context['roots'];rows=[]
    def add(label,argv,timeout=7200):rows.append((label,[str(x) for x in argv],timeout))
    for label,args in [('xcode-version',['xcodebuild','-version']),('swift-version',['swift','--version']),('clang-version',['xcrun','clang++','--version']),('uname',['uname','-a']),('macos-sdk',['xcrun','--sdk','macosx','--show-sdk-path'])]:add(label,args)
    for tool in tool_probe_names(gate):add('tool-'+tool.replace('+','x'),['xcrun','--find',tool])
    add('network-sandbox',[*gate.SANDBOX,context['python'],'-c','import socket,errno\ns=socket.socket()\ntry:s.connect(("192.0.2.1",443))\nexcept OSError as e:\n if e.errno not in (errno.EPERM,errno.EACCES):raise\nelse:raise SystemExit("network sandbox did not deny")'])
    for owner in gate.OWNERS:
        row=data['owners'][owner];root=roots[owner]
        for label,args in [('clone',['git','clone','--no-checkout',row['repository'],root]),('fetch',['git','-C',root,'fetch','--no-tags','--no-recurse-submodules','origin',row['commit']]),('checkout',['git','-C',root,'checkout','--detach',row['commit']]),('readonly',['git','-C',root,'config','remote.origin.pushurl','disabled://p0defensive-readonly'])]:add(label+'-'+owner.lower(),args)
    seen=set()
    for artifact in data['artifacts']:
        digest=artifact['sha256']
        if digest in seen:continue
        seen.add(digest);add('artifact-'+artifact['identity'],['/usr/bin/curl','--fail','--location','--proto','=https','--proto-redir','=https','--max-time','600','--output',work+'/archives/'+digest+'.zip',artifact['url'].split('#')[0]],660)
    for owner,label in [('SideSign','sidesign'),('AnisetteKit','anisette')]:
        base=['swift','package','--package-path',roots[owner],'--scratch-path',work+'/'+label+'-scratch','--disable-dependency-cache']
        add(label+'-resolve',base+['resolve']);add(label+'-frozen-resolve',base+['--force-resolved-versions','resolve'])
    paths={k:Path(v) for k,v in roots.items()}
    for lane,label in [('anisette-trace-regression','anisette'),('sidesign-core-regression','sidesign')]:add(label+'-build',gate.lane_commands(lane,paths,Path(work))['build'])
    for lane in gate.LANES:
        commands=gate.lane_commands(lane,paths,Path(work));add(lane+'-discover',commands['discover']);add(lane+'-tests',commands['execute'])
    for driver in gate.host_tests.DRIVERS:
        label=driver.removesuffix('.py').replace('_','-')
        logical=[context['python'],'-B',context['host']+'/ci/p0defensive/run_host_test.py','--owner',roots['AnisetteKit'],'--driver',driver,'--output',work+'/host-tests/'+label,'--temporary',work+'/host-temporary/'+label,'--evidence',context['evidence']+'/host-tests/'+label,'--unicorn-include',work+'/host-unicorn-headers']
        add('host-'+label,gate.host_tests.execution_command(driver,logical),1800)
    return rows

def replay_commands(files,gate,data,context):
    rows=ordered_commands(gate,data,context);groups=value(files,'provenance/owned-command-groups.json')
    require(isinstance(groups,list) and [g.get('label') for g in groups]==[r[0] for r in rows],'original owned command order/count differs')
    expected_files=set();lifecycle=gate._private_modules['lifecycle'];reports=[]
    for (label,args,cap),group in zip(rows,groups):
        for suffix in ('.command.json','.log','.stderr.log','.exit-code.txt','.settlement.json'):expected_files.add('logs/'+label+suffix)
        env=lifecycle.command_environment(label,args,context['environment'])
        argv=['git','--no-replace-objects','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args[1:]] if args[0]=='git' else args
        command=value(files,'logs/'+label+'.command.json')
        require(command=={'argv':argv,'cwd':context['work'],'environment':env},'original command argv/cwd/environment differs: '+label)
        settled=value(files,'logs/'+label+'.settlement.json');require(set(settled)=={'returncode','timeout_seconds','ownedProcessGroup','terminationReturncode'},'failed or expanded original command settlement')
        require(type(settled['returncode']) is int and settled['returncode']==0 and type(settled['terminationReturncode']) is int and settled['terminationReturncode']==0,'original command did not exit zero')
        timeout=settled['timeout_seconds'];require(type(timeout) in (int,float) and 0<timeout<=cap,'original command timeout invalid')
        expected_group={k:v for k,v in group.items() if k!='label'}
        require(settled['ownedProcessGroup']==expected_group,'owned command/group settlement mismatch')
        require(set(expected_group)=={'pgid','quiescent','pipesJoined','signals','identityRetainedForSignals','reapedBeforeSignals','postReapPolicy','errors','leaderReaped'},'unexpected owned settlement shape')
        require(type(group['pgid']) is int and group['pgid']>0 and all(group[k] is True for k in ('quiescent','pipesJoined','leaderReaped','reapedBeforeSignals')) and group['identityRetainedForSignals'] is False and group['signals']==[] and group['errors']==[] and group['postReapPolicy']=='read-only-group-disappearance','original writer group unsettled or signaled')
        require(files['logs/'+label+'.exit-code.txt']==b'0\n','original command exit bytes differ')
        reports.append({'label':label,'command_sha256':sha(files['logs/'+label+'.command.json']),'stdout_sha256':sha(files['logs/'+label+'.log']),'stderr_sha256':sha(files['logs/'+label+'.stderr.log']),'settlement_sha256':sha(files['logs/'+label+'.settlement.json'])})
    require({n for n in files if n.startswith('logs/')}==expected_files,'extra/missing top-level command evidence')
    return reports

def replay_sources(files,gate,data,roots,context,raw):
    phases=['before','after-resolve','after-anisette-build','after-sidesign-build']+['after-host-'+d.removesuffix('.py').replace('_','-') for d in gate.host_tests.DRIVERS]+['terminal']
    source_records={};after=files['provenance/SideSign.Package.resolved.after']
    for owner,row in data['owners'].items():
        root=Path(roots[owner]);require(root.is_dir() and not root.is_symlink(),'original source object root unavailable')
        require(gate.git(root,'rev-parse',row['commit']+'^{tree}').decode().strip()==row['tree'],'local sealed source tree differs')
        require(gate.git(root,'rev-list','--parents','-n','1',row['commit']).decode().split()==[row['commit'],*row['parents']],'local sealed source parents differ')
        entries=gate.entries(root,row['commit']);source_records[owner]=entries
        for phase in phases:
            report=value(files,'provenance/source-'+phase+'.json');require(set(report)==set(data['owners']),'source owner closure differs')
            proof=report[owner]
            expected_keys={'commit','tree','parents','tracked_entries','status','origin','raw_tree','raw_identity_objects'}|({'actual_lock'} if owner=='SideSign' else set())
            require(set(proof)==expected_keys,'source proof fields differ')
            require(all(proof[k]==row[k] for k in ('commit','tree','parents')) and type(proof['tracked_entries']) is int and proof['tracked_entries']==len(entries),'source tuple/count differs')
            require(proof['origin']=={'kind':'direct','repository':row['repository']},'source origin differs')
            require(proof['status']==(' M Package.resolved\n' if owner=='SideSign' and phase!='before' else ''),'source working state differs')
            tree=proof['raw_tree'];require(tree['source_path']==context['roots'][owner] and tree['commit']==row['commit'] and tree['tree']==row['tree'],'source raw tree identity differs')
            require(raw.tree(tree)==entries,'raw source inventory differs from exact sealed Git objects')
            for record in tree['entries']:
                require(raw.raw_record(record)==gate.git(root,'cat-file','blob',record['git_blob_oid']),'source retained bytes differ from exact Git blob')
            identities=proof['raw_identity_objects'];require(set(identities)=={rev+'/'+kind for rev in (row['base'],row['commit']) for kind in ('commit','tree-listing')},'source identity object closure differs')
            for rev in (row['base'],row['commit']):
                for kind,args in [('commit',('cat-file','commit',rev)),('tree-listing',('ls-tree','-rz',rev))]:require(raw.raw_record(identities[rev+'/'+kind])==gate.git(root,*args),'source identity original bytes differ')
            if owner=='SideSign':require(raw.raw_record(proof['actual_lock'])==(files['provenance/SideSign.Package.resolved.before'] if phase=='before' else after),'source observed lock differs')
        actual=gate.snapshot(root,row['base'],row['commit']);delta=value(files,'provenance/source-delta-'+owner+'.json')
        require(delta['tree']==actual['tree'] and set(delta['changes'])==set(actual['changes']),'source delta inventory differs')
        for name,change in actual['changes'].items():
            for side,expected in change.items():
                observed=delta['changes'][name][side]
                if expected is None:require(observed is None,'source delta before unexpectedly exists');continue
                require({k:v for k,v in observed.items() if k!='raw_blob'}==expected,'source delta Git identities differ')
                require(raw.raw_record(observed['raw_blob'])==gate.git(root,'cat-file','blob',expected['git_object']),'source delta original raw bytes differ')
        for name,audit in data['test_source_audit'][owner].items():
            content=gate.git(root,'show',row['commit']+':'+name);require(sha(content)==audit['sha256'] and len(content)==audit['bytes'],'frozen finite test source differs')
    return {owner:len(entries) for owner,entries in source_records.items()}

def replay_host(files,gate,data,roots,identity,context,raw,closure):
    from prior_phase_a import HOST_PARENT,HOST_PARENT_TREE,HOST_TREE,OVERLAY_BASIS,OVERLAY_TREE
    proof=value(files,'provenance/host-overlay.json');require(set(proof)=={'commit','base','overlay_basis','tree','origin','changes','raw_files','worktree'},'host overlay schema differs')
    require(data['host']['base']==HOST_PARENT and data['host']['tree']==HOST_PARENT_TREE and identity['host_tree']==HOST_TREE and proof['overlay_basis']==OVERLAY_BASIS,'host direct parent/overlay basis differs')
    require(proof['commit']==identity['host_commit'] and proof['tree']==identity['host_tree'] and proof['base']==data['host']['base'] and proof['origin']=={'kind':'direct','repository':data['host']['repository']},'host overlay identity differs')
    expected={name:content for name,content in closure.items()}
    workflow=gate.WORKFLOW_PATH;expected[workflow]=expected[workflow].replace(b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED',b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: '+sha(files['provenance/reviewed-inputs.json']).encode())
    require(set(proof['raw_files'])==set(expected) and set(proof['changes'])==set(expected),'host overlay changed path set differs')
    base=gate.entries(Path(roots['LiveContainer']),OVERLAY_BASIS);require(tree_object(base)[0]==OVERLAY_TREE,'capture host overlay baseline source tree differs')
    actual=dict(base)
    for name,content in expected.items():
        require(raw.raw_record(proof['raw_files'][name])==content and proof['raw_files'][name].get('source_path')==context['host']+'/'+name,'original host overlay bytes/path differ')
        delta=proof['changes'][name];after={'mode':'100644','type':'blob','git_object':object_id('blob',content),'sha256':sha(content)}
        require(delta['after']==after,'host overlay changed blob differs')
        if name==gate.BUILD_WORKFLOW_PATH:
            before=gate.git(Path(roots['LiveContainer']),'show',OVERLAY_BASIS+':'+name)
            require(delta['before']=={'mode':'100644','type':'blob','git_object':object_id('blob',before),'sha256':sha(before)},'host guarded workflow before differs')
        else:require(delta['before'] is None and name not in base,'host adapter replaced source')
        actual[name]=('100644','blob',after['git_object'])
    require(tree_object(actual)[0]==identity['host_tree'],'reconstructed activated host tree differs')
    require(proof['worktree']=={'tracked_entries':len(actual),'unpopulated_gitlinks':{p:oid for p,(mode,kind,oid) in actual.items() if kind=='commit'}},'host inventory/gitlink closure differs')

def replay_lock(files,gate,data,roots,raw):
    before,after,terminal=(files['provenance/SideSign.Package.resolved.'+stage] for stage in ('before','after','terminal-observed'))
    original=gate.git(Path(roots['SideSign']),'show',data['owners']['SideSign']['commit']+':Package.resolved')
    require(before==original and after==terminal,'genuine original/observed/terminal SideSign lock differs')
    checked=gate.check_lock(before,after,data['owners']['AnisetteKit']['commit']);require(value(files,'provenance/resolved-lock.json')==checked,'resolved lock summary differs')
    for owner in data['owners']:
        row=value(files,'provenance/'+owner+'-lock-before.json')
        require(set(row)=={'present','record'},'lock-before schema differs')
        if owner=='AnisetteKit':
            require(row=={'present':False,'record':None},'dependency-free AK gained a lock')
            require(not any(n.startswith('provenance/AnisetteKit.Package.resolved.') for n in files),'unexpected original AK lock')
        else:require(row['present'] is True and raw.raw_record(row['record'])==before,'original before-lock raw bytes absent')
    return after

def archive_members(blob,bundle):
    """Pinned framework ZIP raw entries; no extraction or executable loading."""
    result={};total=0;seen=set()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        rows=archive.infolist();require(len(rows)<=100000,'pinned binary archive entry bound')
        for item in rows:
            require(item.orig_filename==item.filename,'NUL-truncated pinned archive name');name=item.filename.rstrip('/');safe_path(name)
            require(name not in seen,'duplicate pinned archive path');seen.add(name)
            require(not item.flag_bits&1 and item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),'invalid pinned archive encoding')
            if item.is_dir():continue
            require(name.startswith(bundle+'/'),'unexpected pinned archive root')
            name=name[len(bundle)+1:];require(item.file_size<=512*1024**2,'pinned member limit');total+=item.file_size;require(total<=4*1024**3,'pinned expansion limit')
            content=archive.read(item);require(len(content)==item.file_size,'pinned member length differs');mode=item.external_attr>>16
            if stat.S_ISLNK(mode):require(len(content)<=4096,'pinned link too long');row={'sha256':sha(content),'length':len(content),'kind':'symlink'}
            else:
                require(stat.S_IFMT(mode) in (0,stat.S_IFREG),'pinned special file');row={'sha256':sha(content),'length':len(content),'kind':'file','executable':bool(mode&0o111)}
            result[name]=row
    return {'archive_sha256':sha(blob),'files':len(result),'expanded_bytes':total,'members':result}

def replay_resolution(files,gate,data,context,raw,lock):
    pins=gate.primitives.pin_map(parse(lock));graphs={};archives={}
    for artifact in data['artifacts']:
        digest=artifact['sha256']
        if digest not in archives:
            blob=raw.raw_record(value(files,'provenance/archives/'+digest+'.json'));require(sha(blob)==digest,'pinned original dependency ZIP differs')
            archives[digest]=archive_members(blob,artifact['bundle'])
    for phase in ('after-resolve','after-build','terminal'):
        for owner,label in [('AnisetteKit','anisette'),('SideSign','sidesign')]:
            prefix='provenance/'+phase+'/'+owner+'/'
            scratch=context['work']+'/'+label+'-scratch';state_record=value(files,prefix+'workspace-state.json');require(state_record.get('source_path')==scratch+'/workspace-state.json','raw workspace-state path differs')
            state=parse(raw.raw_record(state_record));obj=state['object'];deps=obj['dependencies'];graph=value(files,prefix+'resolved-graph.json');require(set(graph)=={'packages','artifacts'},'resolved graph fields differ')
            expected=pins if owner=='SideSign' else {};require(isinstance(deps,list) and len(deps)==len(expected) and set(graph['packages'])==set(expected),'resolved dependency closure differs')
            seen=set()
            for dep in deps:
                ref=dep['packageRef'];name=ref['identity'].lower();require(name in expected and name not in seen,'unexpected duplicate resolved package');seen.add(name);pin=expected[name]
                require(ref['kind']=='remoteSourceControl' and ref['location']==pin['location'] and dep['state']['name']=='sourceControlCheckout' and dep['state']['checkoutState']['revision']==pin['state']['revision'],'original resolved pin differs')
                subpath=safe_path(dep['subpath']);checkout=scratch+'/checkouts/'+subpath;proof=graph['packages'][name]
                require(set(proof)=={'commit','tree','tracked_entries','submodules','origin','raw_tree','raw_commit','raw_listing'},'resolved package proof shape differs')
                require(proof['commit']==pin['state']['revision'] and proof['submodules']==[],'resolved package commit/submodules differ')
                tree=proof['raw_tree'];require(tree['source_path']==checkout and tree['commit']==proof['commit'] and tree['tree']==proof['tree'],'resolved raw package identity differs')
                entries=raw.tree(tree);require(type(proof['tracked_entries']) is int and proof['tracked_entries']==len(entries),'resolved source inventory count differs')
                commit_identity(raw.raw_record(proof['raw_commit']),proof['commit'],proof['tree']);listing_identity(raw.raw_record(proof['raw_listing']),entries)
                origin=proof['origin'];require(origin.get('repository')==pin['location'],'resolved origin repository differs')
                if origin.get('kind')=='direct':require(origin=={'kind':'direct','repository':pin['location']},'direct origin shape differs')
                else:
                    require(set(origin)=={'kind','repository','mirror','commit','tree'} and origin['kind']=='swiftpm-local-mirror' and origin['commit']==proof['commit'] and origin['tree']==proof['tree'] and PurePosixPath(absolute(origin['mirror'])).parent==PurePosixPath(scratch+'/repositories'),'resolved local mirror identity differs')
                if name=='anisettekit':require(proof['tree']==data['owners']['AnisetteKit']['tree'],'resolved AK full source tree differs')
                if name in graphs:require(graphs[name]==proof['tree'],'resolved package source tree drift')
                graphs[name]=proof['tree']
            artifacts=[a for a in data['artifacts'] if owner=='SideSign' or a['identity']=='anisettekit'];actual=obj['artifacts'];require(len(actual)==len(artifacts)==len(graph['artifacts']),'resolved binary artifact closure differs');seen=set()
            for item,proof in zip(actual,graph['artifacts']):
                identity=item['packageRef']['identity'].lower();target=item['targetName'];key=(identity,target);require(key not in seen,'duplicate binary artifact');seen.add(key)
                matches=[a for a in artifacts if (a['identity'],a['target'])==key];require(len(matches)==1,'unknown binary artifact');expected_artifact=matches[0]
                require(item['source']=={'checksum':expected_artifact['sha256'],'type':'remote','url':expected_artifact['url']},'resolved binary URL/checksum differs')
                require(set(proof)=={'identity','target','comparison','raw_tree'} and (proof['identity'],proof['target'])==key,'binary artifact proof identity differs')
                path=absolute(item['path']);require(inside(path,scratch+'/artifacts') and path!=scratch+'/artifacts','binary artifact path escaped scratch')
                comparison=archives[expected_artifact['sha256']];require(proof['comparison']==comparison,'binary artifact original ZIP comparison differs')
                tree=proof['raw_tree'];require(tree['source_path']==path,'binary artifact retained source path differs');entries=raw.tree(tree);members={p:r for p,r in entries.items() if r['kind']!='directory'}
                require(set(members)==set(comparison['members']),'binary raw file set differs')
                for path,row in members.items():
                    expected_member=comparison['members'][path];require(all(row[k]==expected_member[k] for k in ('sha256','length','kind')),'binary original raw member differs')
                    if row['kind']=='file':require(bool(int(row['mode'],8)&0o111)==expected_member['executable'],'binary member mode differs')
    return graphs

def replay_tools_products(files,gate,data,context,raw):
    def output(label):return files['logs/'+label+'.log'].decode('utf-8')
    def stderr(label):return files['logs/'+label+'.stderr.log'].decode('utf-8')
    tc=data['toolchain'];require((output('xcode-version')+stderr('xcode-version')).strip()==tc['xcode'],'original Xcode output differs')
    require(output('swift-version')==tc['swift_stdout'] and stderr('swift-version')==tc['swift_stderr'],'original Swift streams differ')
    require((output('clang-version')+stderr('clang-version')).splitlines()[0]==tc['clang'],'original Clang output differs')
    tools=value(files,'provenance/tool-identities.json');expected={*tool_probe_names(gate),*gate.LAUNCHER_PATHS,context['python']}
    require(set(tools)==expected,'toolchain executable raw closure differs')
    for name,record in tools.items():
        requested=name if name.startswith('/') else output('tool-'+name.replace('+','x')).strip();absolute(requested)
        require(record.get('kind')=='executable' and record.get('requested_path')==requested and int(record['mode'],8)&0o111,'tool raw identity/path/mode differs')
        resolved=absolute(record['resolved_path']);require(record.get('source_path')==resolved,'tool resolved path differs')
        permitted=[tc['developer_dir'],'/usr/bin']+([str(PurePosixPath(resolved).parent)] if name==context['python'] else [])
        require(any(inside(resolved,p) for p in permitted),'tool escaped approved installation roots')
        current=requested
        chain=record.get('symlink_chain');require(isinstance(chain,list) and len(chain)<=data['retention_bounds']['symlink_hops'],'tool link chain bound')
        for link in chain:
            source=absolute(link['source_path']);target=os.fsdecode(raw.raw_record(link));require(current==source or current.startswith(source+'/'),'tool link outside actual resolution chain')
            current=posixpath.normpath(posixpath.join(posixpath.dirname(source),target)+current[len(source):]);absolute(current)
        require(current==resolved,'tool literal link chain does not resolve to raw executable');raw.raw_record(record)
    sdk=output('macos-sdk').strip();require(inside(sdk,tc['developer_dir']),'SDK output escaped Xcode')
    sdk_record=value(files,'provenance/macos-sdk-raw.json');require(inside(sdk_record['source_path'],tc['developer_dir']),'SDK raw tree outside Xcode');raw.tree(sdk_record)
    for phase in ('before-tests','terminal'):
        for owner,label in [('AnisetteKit','anisette'),('SideSign','sidesign')]:
            product=value(files,'provenance/'+phase+'/'+owner+'/generated-inputs-and-products.json')
            require(isinstance(product,dict) and product and 'workspace-state.json' in product,'generated compiler input/product inventory missing')
            require(not set(product)&{'repositories','checkouts','artifacts'},'generated compiler tree crossed separately bound source closure')
            scratch=context['work']+'/'+label+'-scratch'
            for name,record in product.items():
                require(safe_path(name)==name and '/' not in name,'generated root child path differs')
                if record.get('kind')=='symlink':
                    target=os.fsdecode(raw.raw_record(record));require(record.get('target')==target and inside(record['resolved_path'],scratch),'generated scratch link escaped')
                else:
                    require(record.get('source_path')==scratch+'/'+name,'generated compiler source path differs')
                    if record.get('kind')=='filesystem-tree':raw.tree(record)
                    else:raw.raw_record(record)
    headers=value(files,'provenance/host-unicorn-headers.json');require(set(headers)=={'archive_sha256','headers_sha256','raw_tree','engine_linked','engine_executed'} and headers['engine_linked'] is False and headers['engine_executed'] is False,'host engine header scope differs')
    artifact=next(a for a in data['artifacts'] if a['identity']=='anisettekit');require(headers['archive_sha256']==artifact['sha256'],'host headers wrong archive')
    tree=raw.tree(headers['raw_tree']);require(headers['raw_tree']['source_path']==context['work']+'/host-unicorn-headers','host header tree path differs')
    retained={name.removeprefix('unicorn/'):r for name,r in tree.items() if r['kind']!='directory'}
    require(all(name.startswith('unicorn/') for name,r in tree.items() if r['kind']!='directory') and set(retained)==set(headers['headers_sha256']),'host retained header set differs')
    blob=raw.raw_record(value(files,'provenance/archives/'+artifact['sha256']+'.json'));original={}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for info in archive.infolist():
            parts=PurePosixPath(info.filename).parts
            if len(parts)>1 and parts[-2]=='unicorn' and parts[-1].endswith('.h'):
                require(not stat.S_ISLNK(info.external_attr>>16) and info.file_size<1024**2,'unsafe original header');content=archive.read(info)
                require(parts[-1] not in original or original[parts[-1]]==content,'header slices differ');original[parts[-1]]=content
    require({'unicorn.h','arm64.h','platform.h'}<=set(original) and set(original)==set(retained),'original host header closure differs')
    for name,content in original.items():require(raw.raw_record(retained[name])==content and sha(content)==headers['headers_sha256'][name],'host header original bytes differ')
    return len(tools)

def replay_tests(files,gate,data):
    reports={}
    for lane in gate.LANES:
        discovery=gate.contract.verify_discovery(files['logs/'+lane+'-discover.log'],lane)
        require(value(files,'provenance/'+lane+'-discovery.json')==discovery,'original finite discovery differs')
        runtime=gate.verify_native_logs(files['logs/'+lane+'-tests.log'],files['logs/'+lane+'-tests.stderr.log'],lane)
        require(value(files,'provenance/'+lane+'-tests.json')==runtime,'original finite test execution differs');reports[lane]=runtime
    return reports

def required_metadata(gate,data):
    names={'reviewed-inputs','result','owned-command-groups','retention-summary','host-overlay','source-delta-AnisetteKit','source-delta-SideSign','SideSign-lock-before','AnisetteKit-lock-before','resolved-lock','tool-identities','macos-sdk-raw','host-unicorn-headers'}
    phases=['before','after-resolve','after-anisette-build','after-sidesign-build','terminal']
    for driver in gate.host_tests.DRIVERS:
        label=driver.removesuffix('.py').replace('_','-');names.add('host-'+label);phases.append('after-host-'+label)
    names.update('source-'+phase for phase in phases)
    for lane in gate.LANES:
        for kind in ('discovery','tests'):names.add(lane+'-'+kind)
    for phase in ('after-resolve','after-build','terminal'):
        for owner in data['owners']:
            for kind in ('workspace-state','resolved-graph'):names.add(phase+'/'+owner+'/'+kind)
    for phase in ('before-tests','terminal'):
        for owner in data['owners']:names.add(phase+'/'+owner+'/generated-inputs-and-products')
    names.update('archives/'+row['sha256'] for row in data['artifacts'])
    paths={'provenance/'+name+'.json' for name in names}
    paths.update('provenance/SideSign.Package.resolved.'+stage for stage in ('before','after','terminal-observed'))
    return paths

def verify_evidence(files,gate,data,input_raw,identity,roots,closure):
    metadata={n for n in files if n.startswith('provenance/')}
    require(metadata==required_metadata(gate,data),'unexpected/missing source-specific original provenance member')
    require(all(n=='evidence-index.json' or n.startswith(('provenance/','logs/','host-tests/','blobs/')) for n in files),'unexpected original archive member namespace')
    index=value(files,'evidence-index.json');require(isinstance(index,dict) and set(index)==set(files)-{'evidence-index.json'},'complete original evidence index path set differs')
    for name,digest in index.items():require(sha(files[name])==digest,'original indexed evidence bytes differ: '+name)
    require(files['provenance/reviewed-inputs.json']==input_raw,'original reviewed Phase A input bytes differ')
    result=value(files,'provenance/result.json');require(result.get('status')=='CAPTURED_FOR_INDEPENDENT_REVIEW' and result.get('last_stage')=='captured' and result.get('writers_quiescent') is True,'failed or incomplete Phase A evidence')
    require(not any(key in result for key in ('primary_error','terminal_retention_error')),'failed original capture contains errors')
    require(result.get('source_basis')==data['basis'] and result.get('phase')=='phase-a' and result.get('approved_inputs_sha256')==sha(input_raw) and result.get('source_seal_sha256')==data['source_seal_sha256'] and result.get('owners')==data['owners'],'original source/input basis differs')
    require(result.get('run')=={k:identity[k] for k in ('repository','run_id','run_attempt','host_commit','host_tree')},'original result/run tuple differs')
    require(all(result.get(key) is False for key in FALSE_SCOPE),'original capture scope expanded')
    require(result.get('compiled_identity')=='source-parent-plus-genuine-observed-lock; future-lock-child-not-directly-compiled' and result.get('capture_host_role')=='historical-LiveContainer-capture-only-not-compiled','original source-plus-lock identity differs')
    require(result.get('command_counts')==data['command_counts'],'original finite counts differ')
    raw=RawReplay(files,data['retention_bounds'])
    for name in files:
        if name.endswith('.json') and name!='evidence-index.json':
            namespace='/'.join(name.split('/')[:2]) if name.startswith('host-tests/') else ''
            raw.scan(value(files,name),namespace)
    context=context_from_commands(files,gate,data)
    commands=replay_commands(files,gate,data,context)
    lock=replay_lock(files,gate,data,roots,raw)
    sources=replay_sources(files,gate,data,roots,context,raw)
    replay_host(files,gate,data,roots,identity,context,raw,closure)
    graphs=replay_resolution(files,gate,data,context,raw,lock)
    tools=replay_tools_products(files,gate,data,context,raw)
    tests=replay_tests(files,gate,data)
    from diagnostic_host_replay import verify_host_lanes
    host=verify_host_lanes(files,data,gate,roots,context,raw.raw_record)
    require(host['nested_commands']==164,'new source-specific nested command closure differs')
    ids=host['lanes']['run-tests']['test_ids']
    expected_lines=''.join(test.rsplit('.',1)[1]+' ('+test+') ... ok\n' for test in ids)
    original_stderr=files['logs/host-run-tests.stderr.log'].decode('utf-8')
    pattern=re.escape(expected_lines+'\n'+'-'*70+'\nRan 9 tests in ')+r'[0-9]+(?:\.[0-9]+)?s\n\nOK\n'
    require(re.fullmatch(pattern,original_stderr) is not None,'original aggregate unittest completion stream differs')
    for driver in gate.host_tests.DRIVERS:
        if driver!='run_tests.py':
            label=driver.removesuffix('.py').replace('_','-');require(files['logs/host-'+label+'.stderr.log']==b'','original synthetic host driver emitted unexpected diagnostics')
    summary=value(files,'provenance/retention-summary.json')
    require(set(summary)=={'format','hash','logical_files','logical_bytes','directories','unique_blobs','limits'} and summary['format']=='p0defensive-raw-store-v1' and summary['hash']=='sha256' and summary['limits']==data['retention_bounds'],'original raw retention summary differs')
    for field,bound in [('logical_files','files'),('logical_bytes','total_bytes'),('directories','directories')]:require(type(summary[field]) is int and 0<summary[field]<=data['retention_bounds'][bound],'original aggregate retention bounds exceeded')
    require(type(summary['unique_blobs']) is int and summary['unique_blobs']==len([n for n in files if n.startswith('blobs/')]),'root retained unique blob count differs')
    raw_report=raw.finish()
    require(summary['logical_files']>=raw_report['unique_raw_blobs'] and summary['logical_bytes']>=raw_report['unique_raw_bytes'],'aggregate retention consumption smaller than retained bytes')
    return {'lock_bytes':lock,'report':{'schema_version':1,'source_basis':data['basis'],'capture_status':result['status'],'complete_capture':True,'successful_workflow':True,'original_command_source_replay_performed':True,'execution_admitted':False,'production_ready':False,'compiled_final_lock_child':False,'approved_inputs_sha256':sha(input_raw),'evidence_index_sha256':sha(files['evidence-index.json']),'indexed_files':len(index),'ordered_commands':commands,'source_tracked_entries':sources,'resolved_dependency_trees':graphs,'tool_identities':tools,'swift_tests':tests,'host_tests':host,'raw_retention':raw_report,'lock_sha256':sha(lock)}}
