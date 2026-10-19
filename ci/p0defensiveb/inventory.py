"""Preparation utilities; no prior login capture grants A+B execution admission."""
import hashlib,json,os,re
from pathlib import Path
from source_primitives import git,entries,require,unique_pairs
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
