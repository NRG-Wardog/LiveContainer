#!/usr/bin/env python3
"""Offline transport/schema precheck only; independent command/source replay is required.
Never downloads, executes archive code, extracts, grants admission or promotes.
"""
import argparse, hashlib, importlib, io, json, re, stat, sys, zipfile
from pathlib import Path, PurePosixPath
sys.dont_write_bytecode=True
REPOSITORY='NRG-Wardog/LiveContainer'
BRANCH='validation/p0-login-trace-phase-a'
WORKFLOW='.github/workflows/p0-login-trace-phase-a.yml'
MAX_ARCHIVE=512*1024*1024
MAX_MEMBER=64*1024*1024
MAX_MEMBERS=20000

def require(value,message):
    if not value:raise ValueError(message)
def unique(pairs):
    value={}
    for key,item in pairs:
        require(key not in value,'duplicate JSON key');value[key]=item
    return value
def parse(raw):return json.loads(raw,object_pairs_hook=unique)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):
    require(isinstance(value,str),'digest must be text')
    value=value.removeprefix('sha256:')
    require(re.fullmatch('[0-9a-f]{64}',value),'full SHA256 required')
    return value
def integer(value):
    require(type(value) is int and value>0,'positive actual API integer required');return value
def git_sha(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) and value!='0'*40,'full Git SHA required');return value
def safe_path(name):
    require(isinstance(name,str) and name and '\\' not in name and '\0' not in name and ':' not in name and not name.startswith('/'),'unsafe archive/input path')
    require(all(part not in ('','.','..') for part in name.split('/')),'noncanonical archive/input path')
    return name
def ordinary(root,name):
    p=root
    for part in safe_path(name).split('/'):
        p=p/part;require(not p.is_symlink(),'linked local input')
    require(p.is_file(),'missing local input');return p

def read_archive(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=MAX_ARCHIVE,'ordinary bounded ZIP required')
    raw=path.read_bytes();files={};seen=set();total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        rows=archive.infolist();require(0<len(rows)<=MAX_MEMBERS,'archive entry count exceeded')
        for info in rows:
            require(info.orig_filename==info.filename,'archive NUL-truncated name')
            name=info.filename[:-1] if info.is_dir() else info.filename;safe_path(name)
            require(name.casefold() not in seen,'duplicate or case-alias archive path');seen.add(name.casefold())
            require(not info.flag_bits&1,'encrypted archive entry')
            require(info.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED),'unsupported archive compression')
            require(info.file_size<=max(info.compress_size,1)*1000,'archive compression ratio exceeded')
            kind=stat.S_IFMT(info.external_attr>>16)
            require(kind in ((0,stat.S_IFDIR) if info.is_dir() else (0,stat.S_IFREG)),'archive link/device entry forbidden')
            if info.is_dir():continue
            require(info.file_size<=MAX_MEMBER,'archive member too large');total+=info.file_size
            require(total<=MAX_ARCHIVE,'expanded archive exceeds bound')
            content=archive.read(info);require(len(content)==info.file_size,'archive length mismatch');files[name]=content
    for name in files:
        require(not any('/'.join(name.split('/')[:n]) in files for n in range(1,len(name.split('/')))),'archive file/directory collision')
    prefix=''
    if 'evidence-index.json' not in files:
        prefix='p0login-evidence/'
        require(files and all(n.startswith(prefix) for n in files),'unexpected artifact root')
        files={n[len(prefix):]:v for n,v in files.items()}
    require('evidence-index.json' in files,'missing evidence index')
    require(all(PurePosixPath(name).name!='evidence-index.json' or name=='evidence-index.json' for name in files),'alternate nested evidence index')
    return files,{'sha256':sha(raw),'bytes':len(raw),'files':len(files),'stripped_prefix':prefix}

def load_adapter(host,approved):
    raw=ordinary(host,'ci/p0login/inputs-phase-a.json').read_bytes();require(sha(raw)==digest(approved),'approved input bytes differ')
    data=parse(raw);expected=data['adapter_files']
    require(isinstance(expected,dict) and expected,'missing reviewed adapter inventory')
    for name,value in expected.items():
        require(name.startswith('ci/p0login/'),'adapter escaped frozen namespace')
        require(sha(ordinary(host,name).read_bytes())==digest(value),'frozen adapter bytes changed')
    sys.path.insert(0,str(host/'ci/p0login'))
    gate=importlib.import_module('native_gate')
    gate.validate_inputs(raw,approved,host)
    return gate,data,raw

def verify_api(run,artifact,commit,upload,overlay,archive):
    rid=integer(run['id']);attempt=integer(run['run_attempt']);head=git_sha(run['head_sha'])
    require(run['repository']['full_name']==REPOSITORY and run['head_branch']==BRANCH,'wrong API repository/branch')
    require(run['status']=='completed' and run['event'] in ('push','workflow_dispatch'),'actual terminal capture run required')
    require(run['path'].split('@',1)[0]==WORKFLOW,'wrong API workflow')
    require(run['html_url']==f'https://github.com/{REPOSITORY}/actions/runs/{rid}','wrong run API URL')
    aid=integer(artifact['id']);require(artifact['expired'] is False,'artifact expired')
    require(artifact['url']==f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{aid}','wrong artifact API endpoint')
    require(artifact['name']==f'p0-login-trace-phase-a-{head}-{rid}-{attempt}','artifact name does not bind run/attempt/head')
    require(artifact['workflow_run']['id']==rid and artifact['workflow_run']['head_sha']==head and artifact['workflow_run']['head_branch']==BRANCH,'artifact workflow-run mismatch')
    require(integer(artifact['size_in_bytes'])==archive['bytes'] and digest(artifact['digest'])==archive['sha256'],'downloaded ZIP differs from artifact API digest/size')
    require(git_sha(commit['sha'])==head and [p['sha'] for p in commit['parents']]==[overlay['required_single_parent']],'host commit/parent differs')
    tree=commit.get('tree') or commit['commit']['tree'];tree=git_sha(tree['sha'])
    require(tree==overlay['prospective_approved_host_tree'],'host tree differs from exact reviewed approved-field-only overlay')
    expected={'GITHUB_REPOSITORY':REPOSITORY,'GITHUB_SHA':head,'GITHUB_RUN_ID':str(rid),'GITHUB_RUN_ATTEMPT':str(attempt),'CAPTURE_ARTIFACT_ID':str(aid),'CAPTURE_ARTIFACT_URL':f'https://github.com/{REPOSITORY}/actions/runs/{rid}/artifacts/{aid}'}
    require(all(upload.get(k)==v for k,v in expected.items()),'actual upload-action identity differs')
    require(digest(upload['CAPTURE_ARTIFACT_DIGEST'])==archive['sha256'],'upload-action digest differs from downloaded ZIP')
    return {'repository':REPOSITORY,'run_id':rid,'run_attempt':attempt,'host_commit':head,'host_tree':tree,'artifact_id':aid,'artifact_sha256':archive['sha256'],'workflow_conclusion':run['conclusion'],'run_url':run['html_url']}

def verify_toolchain_output(files,gate,data):
    # Logs contain decoded text from the unchanged text-mode capture. Do not
    # merge Swift stdout/stderr or strip either independently expected stream.
    def output(label,stream='log'):return files['logs/'+label+'.'+stream].decode()
    require((output('xcode-version')+output('xcode-version','stderr.log')).strip()==data['toolchain']['xcode'],'actual Xcode output differs')
    require('swift_stdout' in data['toolchain'] and 'swift_stderr' in data['toolchain'],'retry stream-specific toolchain contract required')
    gate.verify_swift_version(output('swift-version'),output('swift-version','stderr.log'))
    require((output('clang-version')+output('clang-version','stderr.log')).splitlines()[0]==data['toolchain']['clang'],'actual clang output differs')

def evidence(files,gate,data,input_raw,identity,source_objects):
    def raw(path):require(path in files,'missing required evidence: '+path);return files[path]
    def value(path):return parse(raw(path))
    index=value('evidence-index.json');require(isinstance(index,dict) and index=={p:sha(b) for p,b in files.items() if p!='evidence-index.json'},'evidence index does not exactly bind every artifact file')
    require(raw('provenance/reviewed-inputs.json')==input_raw,'artifact reviewed inputs differ')
    result=value('provenance/result.json');status=result['status']
    require(status in ('CAPTURED_FOR_REVIEW','FAILED_OR_INCOMPLETE','FAILED_UNSETTLED_WRITERS'),'unknown capture status')
    require(result['source_basis']==data['source_basis'] and result['phase']=='phase-a','wrong capture source basis/phase')
    require(result['source_seal_sha256']==data['source_seal_sha256'] and result['approved_inputs_sha256']==sha(input_raw) and result['owners']==data['owners'],'captured source tuples/input differ')
    require(result['run']=={k:identity[k] for k in ('repository','run_id','run_attempt','host_commit','host_tree')},'API and captured run identity differ')
    for key in ('production_ready','ipa_built','guest_execution','real_ADI_executed','device_validation','app_typechecked'):
        require(result.get(key) is False,'capture contains unexpected execution/admission claim')
    require(result['writers_quiescent'] is True,'capture writers not settled')
    groups=value('provenance/owned-command-groups.json');require(isinstance(groups,list) and groups,'missing command groups')
    labels=[]
    for group in groups:
        label=group['label'];require(re.fullmatch('[a-z0-9_-]+',label),'unsafe command label');labels.append(label)
        require(all(group.get(k) is True for k in ('quiescent','pipesJoined','leaderReaped')) and not group.get('errors'),'unsettled command writer')
        require(group.get('postReapPolicy')=='read-only-group-disappearance','unexpected process ownership policy')
        require(not(group.get('reapedBeforeSignals') and group.get('signals')),'post-reap signal reported')
        settlement=value('logs/'+label+'.settlement.json')
        require(settlement['ownedProcessGroup']=={k:v for k,v in group.items() if k!='label'},'command/group settlement differs')
        command=value('logs/'+label+'.command.json');require(command['argv'] and isinstance(command['cwd'],str) and command['cwd'],'missing actual command argv/cwd')
        raw('logs/'+label+'.log');raw('logs/'+label+'.stderr.log');code=raw('logs/'+label+'.exit-code.txt')
        require(re.fullmatch(rb'-?[0-9]+\n',code),'invalid command exit receipt')
        if status=='CAPTURED_FOR_REVIEW':require(code==b'0\n' and settlement['returncode']==0 and not settlement.get('error') and not settlement.get('quiescenceError'),'completed capture contains command failure')
    require(len(labels)==len(set(labels)),'duplicate command execution identity')
    require(set(labels)=={p[len('logs/'):-len('.command.json')] for p in files if p.startswith('logs/') and p.endswith('.command.json')},'command receipts and ownership records differ')
    for phase in ('before','after'):
        path='provenance/source-'+phase+'.json'
        if path not in files:
            require(status!='CAPTURED_FOR_REVIEW','complete capture lacks source proof');continue
        proof=value(path);require(set(proof)==set(data['owners']),'source proof omitted/added owner')
        for owner,row in data['owners'].items():
            require(proof[owner]['commit']==row['commit'] and proof[owner]['tree']==row['tree'],'source proof tuple differs')
            require(proof[owner]['origin']['repository']==row['repository'] and proof[owner]['origin']['kind']=='direct','source proof origin differs')
            require(type(proof[owner]['tracked_entries']) is int and proof[owner]['tracked_entries']>0,'source proof lacks tracked inventory')
    lock_info={'present':False,'valid_for_review':False}
    before_name='provenance/SideSign.Package.resolved.before';after_name='provenance/SideSign.Package.resolved.after'
    if before_name in files:
        owner=data['owners']['SideSign'];baseline=gate.git(source_objects/'SideSign','show',owner['commit']+':Package.resolved')
        require(raw(before_name)==baseline,'captured original lock differs from exact source commit')
    if after_name in files:
        lock_info.update(present=True,member=after_name,sha256=sha(raw(after_name)),bytes=len(raw(after_name)))
        try:
            require(before_name in files,'observed after lock lacks original lock')
            checked=gate.check_lock(raw(before_name),raw(after_name),data['owners']['AnisetteKit']['commit'])
            if status=='CAPTURED_FOR_REVIEW':
                require(raw('provenance/SideSign.Package.resolved.final-observed')==raw(after_name),'final lock differs from resolver after bytes')
                require(result['resolved_lock']==checked,'captured lock summary differs')
            lock_info.update(valid_for_review=True,originHash=checked['originHash'])
        except (ValueError,KeyError,TypeError) as error:
            lock_info['validation_error']=str(error)
            if status=='CAPTURED_FOR_REVIEW':raise
    if status=='CAPTURED_FOR_REVIEW':
        require(result.get('last_stage')=='captured' and not result.get('primary_error') and lock_info['valid_for_review'],'incomplete capture mislabeled complete')
        needed={'xcode-version','swift-version','clang-version','uname','macos-sdk','iphoneos-sdk','network-sandbox','sidesign-resolve','sidesign-frozen-resolve','trace-strict-typecheck','metadata-units','anisette-resolve','anisette-frozen-resolve','anisette-build','anisette-discover','anisette-tests','sidesign-build','sidesign-discover','sidesign-tests'}
        needed.update('suite-'+row['id'] for row in data['python_suites'])
        needed.update('parse-'+owner.lower()+'-'+str(i) for owner,row in data['owners'].items() for i,path in enumerate(sorted(row['changes'])) if path.endswith('.swift'))
        require(needed<=set(labels),'complete capture omitted required commands')
        host=value('provenance/host-overlay.json')
        require(host['commit']==identity['host_commit'] and host['tree']==identity['host_tree'] and host['status']=='','host source proof differs')
        require(host['origin']=={'kind':'direct','repository':'https://github.com/'+REPOSITORY+'.git'},'host source origin differs')
        verify_toolchain_output(files,gate,data)
        commands={p[:-len('.command.json')] for p in files if p.startswith('nested-commands/') and p.endswith('.command.json')}
        results={p[:-len('.result.json')] for p in files if p.startswith('nested-commands/') and p.endswith('.result.json')}
        require(commands and commands==results,'nested command attempt/result receipts incomplete')
        for path in commands:
            attempted=value(path+'.command.json');observed=value(path+'.result.json')
            require(observed['argv']==attempted['argv'] and observed['cwd']==attempted['cwd'] and type(observed['returncode']) is int,'nested command identity/completion differs')
        for owner,label,ids in (('AnisetteKit','anisette',gate.AK_IDS),('SideSign','sidesign',gate.SS_IDS)):
            discovery=raw('logs/'+label+'-discover.log').decode();require(value('provenance/'+label+'-discovery.json')==gate.verify_discovery(discovery,ids),'discovery receipt differs from raw output')
            output=raw('logs/'+label+'-tests.log').decode()+raw('logs/'+label+'-tests.stderr.log').decode()
            require(value('provenance/'+label+'-tests.json')==gate.verify_swift_tests(output,owner),'Swift runtime receipt differs from raw output')
        roots={owner:Path(value('logs/clone-'+owner.lower()+'.command.json')['argv'][-1]) for owner in data['owners']}
        for row in data['python_suites']:
            report=value('provenance/suites/'+row['id']+'.json')
            require(report==parse(raw('logs/suite-'+row['id']+'.log').decode().splitlines()[-1]),'Python suite report differs from raw stdout')
            require(report['tests']==len(row['test_ids']) and sorted(report['test_ids'])==sorted(row['test_ids']) and all(report[k]==0 for k in ('failures','errors','skips','expected_failures','unexpected_successes')),'Python executed IDs/counts/failures differ')
            if row['owner'] in ('SideStore','LiveContainer'):
                peer='LiveContainer' if row['owner']=='SideStore' else 'SideStore'
                expected={Path(row['path']).stem:{'ROOT':str(roots[row['owner']]),'PEER':str(roots[peer]),'PRODUCER':str(roots['AnisetteKit'])}}
                require(report['source_roots']==expected,'Python owner/peer roots differ')
        report=gate.verify_metadata_report(value('metadata-units/result.json'))
        for variant in report['results']:
            require(value('metadata-units/'+variant+'-run.stdout')==gate.METADATA_EXPECTED,'metadata raw result differs')
            for phase in ('compile','run'):
                require(raw('metadata-units/'+variant+'-'+phase+'.exit-code.txt')==b'0\n' and raw('metadata-units/'+variant+'-'+phase+'.stderr')==b'','metadata compile/run failed')
        graph=value('provenance/resolved-packages.json');pins=gate.primitives.pin_map(parse(raw(after_name)))
        require(set(graph)==set(pins),'resolved dependency set differs')
        for name,pin in pins.items():require(graph[name]['commit']==pin['state']['revision'],'resolved dependency revision differs')
        require(graph['anisettekit']['tree']==data['owners']['AnisetteKit']['tree'],'resolved Anisette source tree differs')
    return {'verification_scope':'TRANSPORT_AND_SCHEMA_PRECHECK_ONLY','independent_command_source_replay_performed':False,'admission_granted':False,'capture_status':status,'capture_primary_error':result.get('primary_error'),'capture_last_stage':result.get('last_stage'),'workflow_conclusion':identity['workflow_conclusion'],'complete_capture':status=='CAPTURED_FOR_REVIEW','successful_workflow':identity['workflow_conclusion']=='success','observed_sidesign_lock':lock_info,'evidence_index_sha256':sha(raw('evidence-index.json')),'quiescent_commands':len(labels),'source_seal_sha256':data['source_seal_sha256'],'production_ready':False,'promotion_performed':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','run-api-json','artifact-api-json','commit-api-json','upload-identity-json','overlay-manifest','host-root','source-objects'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--approved-overlay-sha256',required=True);p.add_argument('--report',type=Path)
    a=p.parse_args()
    try:
        gate,data,input_raw=load_adapter(a.host_root.resolve(),a.approved_inputs_sha256)
        overlay_raw=a.overlay_manifest.read_bytes();require(sha(overlay_raw)==digest(a.approved_overlay_sha256),'independently approved overlay inventory differs')
        overlay=parse(overlay_raw);require(overlay['input_sha256']==sha(input_raw),'overlay input hash differs')
        require(overlay['required_single_parent']==data['owners']['LiveContainer']['commit'] and overlay['parent_tree']==data['owners']['LiveContainer']['tree'],'overlay source parent differs')
        files,archive=read_archive(a.archive)
        identity=verify_api(parse(a.run_api_json.read_bytes()),parse(a.artifact_api_json.read_bytes()),parse(a.commit_api_json.read_bytes()),parse(a.upload_identity_json.read_bytes()),overlay,archive)
        report=evidence(files,gate,data,input_raw,identity,a.source_objects.resolve())
        report.update(transport=identity,archive=archive,input_sha256=sha(input_raw),overlay_manifest_sha256=sha(a.overlay_manifest.read_bytes()),api_receipt_sha256={name:sha(getattr(a,name).read_bytes()) for name in ('run_api_json','artifact_api_json','commit_api_json','upload_identity_json')})
        report['verification_status']='TRANSPORT_SCHEMA_PRECHECK_COMPLETE_REQUIRES_INDEPENDENT_REPLAY' if report['complete_capture'] and report['successful_workflow'] else 'FAILED_OR_INCOMPLETE_CAPTURE_PRESERVED'
        output=json.dumps(report,indent=2,sort_keys=True)+'\n'
        if a.report:
            with a.report.open('x') as file:file.write(output)
        print(output,end='')
        return 0 if report['verification_status']=='TRANSPORT_SCHEMA_PRECHECK_COMPLETE_REQUIRES_INDEPENDENT_REPLAY' else 3
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile) as error:
        p.exit(2,'REJECTED: '+str(error)+'\n')
if __name__=='__main__':raise SystemExit(main())
