"""Exact successor source and capture-only overlay seals. No approval is inferred."""
import hashlib,json,os,re,stat
from pathlib import Path
from source_primitives import require,unique_pairs,git,verify_checkout
HERE=Path(__file__).resolve().parent
BASIS='defensive-ab-linux-v1'
BRANCH='validation/p0-defensive-ab-linux'
HOST_BASE='545438e1f0a89fdef375f73273c5c9fc2735cbce'
HOST_TREE='e8014dd771c25c4a05dc76ab0aa304a233642a83'
WORKFLOW='.github/workflows/p0-defensive-ab-linux.yml'
BUILD='.github/workflows/build.yml'
BUILD_GUARD="    if: github.ref != 'refs/heads/"+BRANCH+"'\n"
SEAL_SHA='7e2975ef6924f3debe75ac7ef57b7a93edd4e3e365df11e2880553713ec513cb'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def parse(raw):return json.loads(raw,object_pairs_hook=unique_pairs)
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def ordinary(root,relative):
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute() and all(x not in ('','.','..','.git') for x in relative.split('/')),'unsafe relative path')
    p=Path(root);require(p.is_dir() and not p.is_symlink(),'ordinary root required')
    for part in relative.split('/'):
        p=p/part;require(not p.is_symlink(),'linked input path')
    require(stat.S_ISREG(p.lstat().st_mode) and p.stat().st_nlink==1,'ordinary unlinked regular file required: '+str(p))
    return p
def source_seal():
    raw=ordinary(HERE,'reviewed/source-seal.json').read_bytes()
    require(sha(raw)==SEAL_SHA,'exact successor source seal differs')
    return parse(raw)
def verify_source(root):
    seal=source_seal();root=Path(root)
    proof=verify_checkout(root,seal['commit'],owner='AnisetteKit',require_full_history=True)
    require(proof['tree']==seal['tree'],'exact successor tree differs')
    require(git(root,'show','-s','--format=%P',seal['commit']).decode().strip()==seal['parent'],'sole source parent differs')
    found={}
    for base,dirs,files in os.walk(root,followlinks=False):
        if Path(base)==root:dirs[:]=[d for d in dirs if d!='.git'];files=[f for f in files if f!='.git']
        for name in dirs:require(stat.S_ISDIR((Path(base)/name).lstat().st_mode),'linked/special source directory')
        for name in files:
            path=Path(base)/name;rel=str(path.relative_to(root));raw=ordinary(root,rel).read_bytes();s=path.stat()
            found[rel]={'mode':'100755' if s.st_mode&0o111 else '100644','git_object':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),'bytes':len(raw),'sha256':sha(raw)}
    require(found==seal['files'],'complete source byte inventory differs')
    return {'commit':seal['commit'],'tree':seal['tree'],'parent':seal['parent'],'files':found}
def workflow_bytes(host):
    raw=ordinary(host,WORKFLOW).read_bytes();text=raw.decode()
    values=re.findall(r'^      APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: ([A-Z_]+|[0-9a-f]{64})$',text,re.M)
    require(len(values)==1,'exactly one workflow anchor required')
    return text.replace('      APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: '+values[0],'      APPROVED_P0DEFENSIVE_LINUX_INPUTS_SHA256: REVIEW_REQUIRED').encode(),values[0]
def adapter_inventory(root):
    result={}
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:require(stat.S_ISDIR((Path(base)/name).lstat().st_mode),'special adapter directory')
        for name in files:
            path=Path(base)/name;rel=str(path.relative_to(root.parent.parent))
            ordinary(root.parent.parent,rel)
            if path!=root/'inputs-linux.json':result[rel]=sha(path.read_bytes())
    return result
def validate_inputs(raw,host,approved=None,execute=False):
    data=parse(raw);seal=source_seal()
    require(set(data)=={'schema','basis','host','source_seal_sha256','adapter_files','workflow_template_sha256','drivers','retained_patterns_status'},'exact Linux input schema required')
    require(type(data['schema']) is int and data['schema']==1 and data['basis']==BASIS,'successor source basis differs')
    require(data['source_seal_sha256']==SEAL_SHA,'source seal binding differs')
    require(data['host']=={'base':HOST_BASE,'tree':HOST_TREE,'branch':BRANCH,'build_guard':BUILD_GUARD},'capture host identity differs')
    require(data['retained_patterns_status']=='PENDING_INDEPENDENT_CAPTURE_REVIEW','retained pattern approval overclaim')
    require(data['drivers']==['test_vm_setup_host.py','test_memory_boundaries_host.py','test_cxx_allocation.py','test_elf_metadata_bounds.py'],'exact finite Linux drivers required')
    root=host/'ci/p0defensive_linux'
    require(adapter_inventory(root)==data['adapter_files'],'complete adapter inventory differs')
    for rel,h in data['adapter_files'].items():require(sha(ordinary(host,rel).read_bytes())==h,'adapter bytes differ: '+rel)
    before=ordinary(root,'reviewed/capture-host-build.before.yml').read_bytes()
    require(before.count(b'  build:\n')==1,'host build job differs')
    require(ordinary(host,BUILD).read_bytes()==before.replace(b'  build:\n',b'  build:\n'+BUILD_GUARD.encode()),'only exact one-line ordinary-build exclusion allowed')
    workflow,anchor=workflow_bytes(host);require(sha(workflow)==data['workflow_template_sha256'],'workflow template differs')
    require(anchor in ('REVIEW_REQUIRED',sha(raw)),'workflow activation digest differs')
    if execute:
        require(approved==sha(raw) and re.fullmatch('[0-9a-f]{64}',approved or '') and anchor==approved,'REVIEW_REQUIRED: exact independent capture review and workflow activation required')
    return data

HOST_GITLINKS={'OpenSSL':'623c84da314e85363236507ca38a4bde65df21c3','litehook':'8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55'}
def verify_capture_host_checkout(root,commit):
    """Prove the full capture host; unused exact product Gitlinks stay absent.

    This intentionally does not change the full recursive Anisette source gate.
    The Linux lane executes adapter files only and never compiles a host product.
    """
    from source_primitives import entries
    require(git(root,'rev-parse','HEAD').decode().strip()==commit,'capture host HEAD differs')
    require(git(root,'rev-parse','--is-shallow-repository').strip()==b'false','shallow capture host')
    records=entries(root);links={name:oid for name,(mode,kind,oid) in records.items() if mode=='160000'}
    require(links==HOST_GITLINKS,'exact unused capture-host Gitlinks differ')
    for name,(mode,kind,oid) in records.items():
        path=root/name
        for parent in path.parents:
            if parent==root:break
            require(not parent.is_symlink(),'linked capture-host ancestor')
        if mode=='160000':
            require(kind=='commit' and not path.is_symlink() and (not path.exists() or (path.is_dir() and not list(path.iterdir()))),'unused host Gitlink unexpectedly materialized')
            continue
        require(kind=='blob','unsupported capture-host object')
        if mode=='120000':
            require(path.is_symlink(),'missing capture-host symlink');raw=os.fsencode(os.readlink(path))
        else:
            raw=ordinary(root,name).read_bytes();require(('100755' if path.stat().st_mode&0o111 else '100644')==mode,'capture-host file mode differs')
        require(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==oid,'capture-host working bytes differ')
    for flags in [('--others','--exclude-standard'),('--others','--ignored','--exclude-standard')]:
        require(not git(root,'ls-files',*flags,'-z'),'unexpected untracked/ignored capture-host input')
    require(not git(root,'diff','--cached','--name-only'),'capture-host index changed')
    return {'commit':commit,'tracked_entries':len(records),'gitlinks':links,'gitlinks_materialized':False}
