"""Narrow Phase A package capture identity. No build admission or release authority."""
import hashlib, json, os, re
from pathlib import Path
from source_primitives import git, entries, require, unique_pairs
BASIS='defensive-ab-phase-a-v1'
OWNERS=('AnisetteKit','SideSign')
SEAL_SHA='4227944ac9904238faff32c0daa74ae74f370cd23f28145eb4052845c3baf07e'
WORKFLOW_PATH='.github/workflows/p0-defensive-ab-phase-a.yml'
BRANCH='validation/p0-defensive-ab-phase-a'
HOST_BASE='545438e1f0a89fdef375f73273c5c9fc2735cbce'
HOST_TREE='e8014dd771c25c4a05dc76ab0aa304a233642a83'
BUILD_WORKFLOW_PATH='.github/workflows/build.yml'
BUILD_GUARD="    if: github.ref != 'refs/heads/validation/p0-defensive-ab-phase-a'\n"
TOOLCHAIN={'developer_dir':'/Applications/Xcode_26.4.1.app/Contents/Developer','architecture':'arm64','xcode':'Xcode 26.4.1\nBuild version 17E202','swift_stdout':'Apple Swift version 6.3.1 (swiftlang-6.3.1.1.2 clang-2100.0.123.102)\nTarget: arm64-apple-macosx26.0\n','swift_stderr':'swift-driver version: 1.148.6 ','clang':'Apple clang version 21.0.0 (clang-2100.0.123.102)'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return json.loads(raw,object_pairs_hook=unique_pairs)
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def full_sha(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) and value!='0'*40,'full real Git object ID required')
    return value

def ordinary(root,relative):
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute() and all(x not in ('','.','..','.git') for x in relative.split('/')),'unsafe relative path')
    p=Path(root);require(not p.is_symlink(),'linked input root')
    for part in relative.split('/'):
        p=p/part;require(not p.is_symlink(),'linked input path')
    require(p.is_file(),'missing file: '+str(p))
    return p

def snapshot(root,base,commit):
    full_sha(base);full_sha(commit);git(root,'merge-base','--is-ancestor',base,commit)
    old,new=entries(root,base),entries(root,commit)
    def row(value):
        if value is None:return None
        mode,kind,oid=value
        return dict(mode=mode,type=kind,git_object=oid,**({'sha256':sha(git(root,'cat-file','blob',oid))} if kind=='blob' else {}))
    return {'tree':git(root,'rev-parse',commit+'^{tree}').decode().strip(),'changes':{p:{'before':row(old.get(p)),'after':row(new.get(p))} for p in sorted(old.keys()|new.keys()) if old.get(p)!=new.get(p)}}

def workflow_template(host,approved=None):
    raw=ordinary(host,WORKFLOW_PATH).read_text()
    values=re.findall(r'(?m)^      APPROVED_P0DEFENSIVE_INPUTS_SHA256: ([A-Z_]+|[0-9a-f]{64})$',raw)
    require(len(values)==1 and values[0] in ('REVIEW_REQUIRED',approved),'workflow activation differs from reviewed input')
    return raw.replace('      APPROVED_P0DEFENSIVE_INPUTS_SHA256: '+values[0], '      APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED').encode(),values[0]

def validate_inputs(raw,host,approved=None,execute=False):
    data=parse(raw);here=host/'ci/p0defensive'
    require(set(data)=={'schema','basis','phase','source_seal_sha256','owners','host','adapter_files','workflow_template_sha256','toolchain','test_source_audit','artifacts','command_counts','retention_bounds'},'unexpected input schema')
    require(type(data['schema']) is int and data['schema']==1 and data['basis']==BASIS and data['phase']=='phase-a','wrong capture scope')
    seal_raw=ordinary(here,'reviewed/defensive-source-seal.json').read_bytes()
    require(sha(seal_raw)==data['source_seal_sha256']==SEAL_SHA,'source seal changed')
    require(data['toolchain']==TOOLCHAIN,'toolchain changed')
    actual={str(p.relative_to(host)):sha(p.read_bytes()) for p in (host/'ci/p0defensive').rglob('*') if p.is_file() and not p.is_symlink() and p.name!='inputs-phase-a.json' and '__pycache__' not in p.parts}
    require(actual==data['adapter_files'],'exact adapter inventory changed')
    template,anchor=workflow_template(host,approved)
    require(sha(template)==data['workflow_template_sha256'],'workflow template changed')
    proposal=parse(ordinary(here,'reviewed/inventory.proposed.json').read_bytes())
    require(data['test_source_audit']==proposal['swift_files'],'test-source audit changed')
    require(data['command_counts']=={'owner_acquisition':8,'package_resolve':4,'package_build':2,'test_discovery':2,'filtered_test_execution':2,'selected_tests':11,'synthetic_host_suites':4},'finite command counts changed')
    from retention import BOUNDS
    require(data['retention_bounds']==BOUNDS,'raw retention bounds changed')
    seal=parse(seal_raw)['owners'];require(set(data['owners'])==set(OWNERS),'two actual packages required')
    publication=parse(ordinary(here,'publication.json').read_bytes())
    require(data['owners']==publication['owners'] and data['host']==publication['host'],'exact publication tuple changed')
    blockers=[]
    for name,row in data['owners'].items():
        require(set(row)=={'repository','commit','tree','parents','base','reviewed_tree','manifest_delta'},'owner schema changed')
        require(row['repository']=='https://github.com/NRG-Wardog/'+name+'.git','wrong repository')
        require(row['base']==seal[name]['base_commit'] and row['reviewed_tree']==seal[name]['tree'],'reviewed source anchor changed')
        if row['commit'] is None:blockers.append(name+' publication tuple pending');continue
        for key in ('commit','tree','base'):full_sha(row[key])
        require(row['parents']==[row['base']],'published source must be sole-parent reviewed-base child')
        receipt=parse(ordinary(here,'reviewed/'+name+'.connector-publication-receipt.json').read_bytes())
        observed=receipt['readback']['commit'];ref=receipt['readback']['ref'];tree=receipt['readback']['tree']
        require(observed['sha']==row['commit'] and observed['tree']['sha']==row['tree'] and [p['sha'] for p in observed['parents']]==row['parents'],'published owner readback tuple differs')
        require(ref['object']['sha']==row['commit'] and tree['sha']==row['tree'] and tree['truncated'] is False,'published owner ref/tree readback differs')
        if name=='AnisetteKit':require(row['tree']==row['reviewed_tree'] and row['manifest_delta'] is None,'AK publication not tree-equivalent')
        else:
            manifest_review=parse(ordinary(here,'reviewed/SideSign.manifest-pin-review.json').read_bytes())
            require(row['tree']==manifest_review['published_reconstruction_required_tree'] and row['base']==manifest_review['published_reconstruction_required_sole_parent'],'SideSign manifest-review tree/parent mismatch')
            delta=row['manifest_delta'];require(set(delta)=={'before_sha256','after_sha256','old_ak','new_ak'},'manifest delta schema')
            require(delta['before_sha256']==manifest_review['before_manifest_sha256'] and delta['after_sha256']==manifest_review['after_manifest_sha256'],'SideSign reviewed manifest bytes mismatch')
            require(delta['old_ak']==seal['AnisetteKit']['base_commit'] and delta['new_ak']==data['owners']['AnisetteKit']['commit'],'manifest revision relation changed')
    require(data['artifacts']==parse(ordinary(here,'reviewed/artifacts.json').read_bytes()),'binary artifact allowlist changed')
    if data['host'] is None:blockers.append('capture host parent and ordinary build guard pending')
    else:
        h=data['host'];require(set(h)=={'repository','base','tree','ordinary_build_before_sha256','ordinary_build_after_sha256'},'capture host schema')
        require(h['repository']=='https://github.com/NRG-Wardog/LiveContainer.git','wrong capture host repository')
        require(full_sha(h['base'])==HOST_BASE and full_sha(h['tree'])==HOST_TREE,'capture-only baseline host tuple differs')
        require(sha(ordinary(here,'reviewed/capture-host-build.before.yml').read_bytes())==h['ordinary_build_before_sha256'],'capture-host original workflow bytes differ')
        guarded=ordinary(host,BUILD_WORKFLOW_PATH).read_bytes()
        require(sha(guarded)==h['ordinary_build_after_sha256'],'ordinary build guard bytes differ')
        needle=('  build:\n'+BUILD_GUARD).encode()
        require(guarded.count(needle)==1 and guarded.count(BUILD_GUARD.encode())==1 and sha(guarded.replace(needle,b'  build:\n',1))==h['ordinary_build_before_sha256'],'only exact ordinary build guard permitted')
    if execute:
        require(not blockers,'; '.join(blockers))
        require(isinstance(approved,str) and re.fullmatch('[0-9a-f]{64}',approved) and sha(raw)==approved and anchor==approved,'independently reviewed workflow activation hash required')
    return data,blockers
