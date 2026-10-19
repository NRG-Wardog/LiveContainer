#!/usr/bin/env python3
"""Read immutable local Git objects. Output is a proposal, never approval or native evidence."""
import argparse,ast
from pathlib import Path
from inventory import *
def test_ids(raw,module):
    result=[]
    for cls in ast.parse(raw).body:
        if isinstance(cls,ast.ClassDef):
            for item in cls.body:
                if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef)) and item.name.startswith('test_'):
                    result.append(module+'.'+cls.name+'.'+item.name)
    require(result and len(result)==len(set(result)),'finite declared Python tests required')
    return sorted(result)
def prepare(host,trees):
    seal,pub,allow=pinned_documents(host);owners={}
    for name in OWNERS:
        row=pub['owners'][name];root=trees/name
        actual=snapshot(root,row['base'],row['commit'])
        require(actual['tree']==row['tree'] and set(actual['changes'])==set(allow[name]),'unexpected immutable source delta')
        owners[name]=dict(repository='https://github.com/NRG-Wardog/'+name+'.git',base=row['base'],commit=row['commit'],**actual)
    suites=[]
    for index,(owner,path) in enumerate(PYTHON_SUITE_PLAN):
        raw=git(trees/owner,'show',owners[owner]['commit']+':'+path).decode()
        suites.append(dict(id=f'{owner.lower()}-{Path(path).parent.name}-{index}'.replace('.',''),owner=owner,path=path,test_ids=test_ids(raw,Path(path).stem)))
    for owner,files in TEST_SOURCE_AUDIT.items():
        records=entries(trees/owner,owners[owner]['commit'])
        found={p:sha(git(trees/owner,'show',owners[owner]['commit']+':'+p)) for p in records if p.startswith('Tests/') and p.endswith('.swift')}
        require(found==files,'test initialization audit bytes differ')
    guard=ordinary_build_guard(host)
    require(guard['before_sha256']==sha(git(trees/'LiveContainer','show',owners['LiveContainer']['commit']+':'+BUILD_WORKFLOW_PATH)),'ordinary workflow changed beyond exact job guard')
    adapter={str(p.relative_to(host)):sha(p.read_bytes()) for p in (host/'ci/p0login').rglob('*') if p.is_file() and not p.is_symlink() and p.name!='inputs-phase-a.json' and '__pycache__' not in p.parts}
    return dict(schema_version=1,source_basis=BASIS,phase='phase-a',source_seal_sha256=SEAL_SHA,publication_sha256=PUBLICATION_SHA,owners=owners,adapter_files=adapter,python_suites=suites,toolchain=TOOLCHAIN,test_source_audit=TEST_SOURCE_AUDIT,ordinary_build_guard=guard,workflow_template_sha256=sha(workflow_template(host,sha(ordinary(host,'ci/p0login/inputs-phase-a.json').read_bytes()) if (host/'ci/p0login/inputs-phase-a.json').exists() else '0'*64)))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',required=True,type=Path);p.add_argument('--trees',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    value=prepare(a.host_root.resolve(),a.trees.resolve());dump(a.output,value)
    validate_inputs(a.output.read_bytes(),sha(a.output.read_bytes()),a.host_root.resolve())
    print('PROPOSED_INPUTS_SHA256='+sha(a.output.read_bytes()))
