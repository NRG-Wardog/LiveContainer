"""Exact Phase B input inventory. Workflow digest substitution is the review boundary."""
import hashlib,json,os,re
from pathlib import Path
from source_primitives import git,entries,require,unique_pairs
BASIS='p0-login-trace-phase-b-v1'
BRANCH='validation/p0-login-trace-phase-b'
WORKFLOW_PATH='.github/workflows/p0-login-trace-phase-b.yml'
BUILD_WORKFLOW_PATH='.github/workflows/build.yml'
BUILD_GUARD="    if: github.ref != 'refs/heads/validation/p0-login-trace-phase-b'\n"
SEAL_SHA='0caa11b1135abbf9c3905c601d100475b91f8d011237033ab47d1f96fad116e8'
PUBLICATION_SHA='9c0da8c5be4eb6ebac50a006225e371ed9a1a3008e5e79dd4e30d71a906eba5a'
SOURCE_LC='545438e1f0a89fdef375f73273c5c9fc2735cbce'
TOOLCHAIN={'developer_dir':'/Applications/Xcode_26.4.1.app/Contents/Developer','architecture':'arm64','xcode':'Xcode 26.4.1\nBuild version 17E202','swift_stdout':'Apple Swift version 6.3.1 (swiftlang-6.3.1.1.2 clang-2100.0.123.102)\nTarget: arm64-apple-macosx26.0\n','swift_stderr':'swift-driver version: 1.148.6 ','clang':'Apple clang version 21.0.0 (clang-2100.0.123.102)','bindgen':'bindgen 0.72.1'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return json.loads(raw,object_pairs_hook=unique_pairs)
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def full_sha(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) and value!='0'*40,'full actual Git SHA required');return value
def ordinary(root,path):
    require(isinstance(path,str) and path and not Path(path).is_absolute() and all(p not in ('','.','..','.git') for p in path.split('/')),'unsafe path')
    target=Path(root);require(not target.is_symlink(),'linked root')
    for part in path.split('/'):
        target=target/part;require(not target.is_symlink(),'linked file path')
    require(target.is_file(),'ordinary file required: '+path);return target
def snapshot(root,base,commit):
    full_sha(base);full_sha(commit);git(root,'merge-base','--is-ancestor',base,commit);before,after=entries(root,base),entries(root,commit)
    def row(entry):
        if entry is None:return None
        mode,kind,oid=entry;return dict(mode=mode,type=kind,git_object=oid,**({'sha256':sha(git(root,'cat-file','blob',oid))} if kind=='blob' else {}))
    return {'tree':git(root,'rev-parse',commit+'^{tree}').decode().strip(),'changes':{p:{'before':row(before.get(p)),'after':row(after.get(p))} for p in sorted(before.keys()|after.keys()) if before.get(p)!=after.get(p)}}
def verify_swift_version(stdout,stderr):
    require(stdout==TOOLCHAIN['swift_stdout'] and stderr==TOOLCHAIN['swift_stderr'],'exact separately decoded Swift streams differ')
def check_lock(before,after,commit):
    from source_primitives import pin_map
    old,new=parse(before),parse(after);a,b=pin_map(old),pin_map(new)
    require(a.keys()==b.keys() and 'anisettekit' in b,'package identity drift')
    require(all(a[k]==b[k] for k in a if k!='anisettekit'),'non-AnisetteKit pin drift')
    require(b['anisettekit']=={'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':full_sha(commit)}},'exact AK pin required')
    require({k:v for k,v in old.items() if k not in ('pins','originHash')}=={k:v for k,v in new.items() if k not in ('pins','originHash')},'lock schema drift')
    require(isinstance(new.get('originHash'),str) and re.fullmatch('[0-9a-f]{64}',new['originHash']),'genuine originHash required')
    return {'sha256':sha(after),'originHash':new['originHash']}
def workflow_template(host,approved):
    text=ordinary(host,WORKFLOW_PATH).read_text();values=re.findall(r'(?m)^      APPROVED_P0LOGINB_INPUTS_SHA256: ([A-Z_]+|[0-9a-f]{64})$',text)
    require(len(values)==1 and values[0] in ('REVIEW_REQUIRED',approved),'invalid exact workflow approval field')
    return text.replace('      APPROVED_P0LOGINB_INPUTS_SHA256: '+values[0],'      APPROVED_P0LOGINB_INPUTS_SHA256: REVIEW_REQUIRED').encode()
def ordinary_build_guard(host):
    after=ordinary(host,BUILD_WORKFLOW_PATH).read_bytes();needle=('  build:\n'+BUILD_GUARD).encode()
    require(after.count(needle)==1 and after.count(BUILD_GUARD.encode())==1,'exact Phase B build-job guard required')
    return {'path':BUILD_WORKFLOW_PATH,'before_sha256':sha(after.replace(needle,b'  build:\n',1)),'after_sha256':sha(after),'excluded_ref':'refs/heads/'+BRANCH,'job':'build'}
def adapter_inventory(host):
    return {str(p.relative_to(host)):sha(p.read_bytes()) for p in sorted((host/'ci/p0loginb').rglob('*')) if p.is_file() and not p.is_symlink() and p.name!='inputs-phase-b.json' and '__pycache__' not in p.parts}
def validate_inputs(raw,host,approved=None,*,execution=False):
    from graph_contract import validate_graph
    from prior_phase_a import validate_prior_inputs
    data=parse(raw)
    require(set(data)=={'schema_version','source_basis','phase','status','execution_review','source_seal_sha256','publication_sha256','graph','prior_phase_a','adapter_files','toolchain','ordinary_build_guard','workflow_template_sha256'},'Phase B schema differs')
    require(data['schema_version']==1 and data['source_basis']==BASIS and data['phase']=='phase-b','wrong Phase B identity')
    require(data['status'] in ('PREPARATION_ONLY','BOUND_CAPTURE_PROPOSAL') and data['execution_review'] is None,'no synthetic approval field is accepted')
    require(data['source_seal_sha256']==SEAL_SHA and data['publication_sha256']==PUBLICATION_SHA,'stale source seal/publication')
    require(sha(ordinary(host,'ci/p0loginb/source-seal.json').read_bytes())==SEAL_SHA and sha(ordinary(host,'ci/p0loginb/publication-trees.json').read_bytes())==PUBLICATION_SHA,'changed source documents')
    require(data['adapter_files']==adapter_inventory(host),'draft adapter inventory changed')
    require(data['toolchain']==TOOLCHAIN,'unreviewed toolchain')
    require(data['ordinary_build_guard']==ordinary_build_guard(host),'ordinary build guard differs')
    require(data['workflow_template_sha256']==sha(workflow_template(host,sha(raw))),'workflow changed')
    validate_graph(data['graph'],execution=data['status']=='BOUND_CAPTURE_PROPOSAL');validate_prior_inputs(data['prior_phase_a'],execution=data['status']=='BOUND_CAPTURE_PROPOSAL')
    if execution:
        require(data['status']=='BOUND_CAPTURE_PROPOSAL','Phase B execution blocked: unresolved inputs')
        require(approved==sha(raw),'Phase B execution blocked: exact independent input approval is absent')
        require(('      APPROVED_P0LOGINB_INPUTS_SHA256: '+sha(raw)+'\n') in ordinary(host,WORKFLOW_PATH).read_text(),'Phase B execution blocked: workflow remains REVIEW_REQUIRED')
        require(data['graph']['prior_artifact']==data['prior_phase_a']['expected'],'source/prior capture tuples differ')
    if approved is not None:require(approved==sha(raw),'actual input digest differs')
    return data
