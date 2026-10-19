"""P0 login Phase A source identity; immutable trees and explicit finite deltas."""
import hashlib, json, os, re
from pathlib import Path
from source_primitives import git, entries, require, unique_pairs
OWNERS = ('AnisetteKit','SideSign','SideStore','LiveContainer')
BASIS = 'p0-login-trace-phase-a-v1'
SEAL_SHA = '0caa11b1135abbf9c3905c601d100475b91f8d011237033ab47d1f96fad116e8'
PUBLICATION_SHA = '9c0da8c5be4eb6ebac50a006225e371ed9a1a3008e5e79dd4e30d71a906eba5a'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def parse(raw): return json.loads(raw,object_pairs_hook=unique_pairs)
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def full_sha(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) and value!='0'*40,'full real Git object ID required')
    return value

def ordinary(root,relative):
    require(isinstance(relative,str) and relative and not Path(relative).is_absolute() and all(x not in ('','.','..','.git') for x in relative.split('/')),'unsafe relative path')
    p=Path(root)
    require(not p.is_symlink(),'linked input root')
    for part in relative.split('/'):
        p=p/part;require(not p.is_symlink(),'linked input path')
    require(p.is_file(),'missing file: '+str(p))
    return p

def snapshot(root,base,commit):
    full_sha(base);full_sha(commit)
    git(root,'merge-base','--is-ancestor',base,commit)
    old,new=entries(root,base),entries(root,commit)
    def row(value):
        if value is None:return None
        mode,kind,oid=value
        return dict(mode=mode,type=kind,git_object=oid,**({'sha256':sha(git(root,'cat-file','blob',oid))} if kind=='blob' else {}))
    return {'tree':git(root,'rev-parse',commit+'^{tree}').decode().strip(),'changes':{p:{'before':row(old.get(p)),'after':row(new.get(p))} for p in sorted(old.keys()|new.keys()) if old.get(p)!=new.get(p)}}

def pinned_documents(host):
    here=host/'ci/p0login'
    seal_raw=ordinary(here,'source-seal.json').read_bytes();publication_raw=ordinary(here,'publication-trees.json').read_bytes()
    require(sha(seal_raw)==SEAL_SHA and sha(publication_raw)==PUBLICATION_SHA,'source seal or publication tuples changed; independent reseal required')
    seal=parse(seal_raw);publication=parse(publication_raw);allow=parse(ordinary(here,'allowed-paths.json').read_bytes())
    require(set(seal['repositories'])==set(OWNERS)==set(publication['owners'])==set(allow),'exact four owner graph required')
    require(publication['candidate_seal_sha256']==SEAL_SHA,'publication source seal mismatch')
    for name in OWNERS:
        expected=sorted([r['path'] for r in seal['repositories'][name]['changes']]+(['Package.swift'] if name=='SideSign' else []))
        require(allow[name]==expected==publication['owners'][name]['changed_paths'],'frozen path allowlist drift: '+name)
    return seal,publication,allow

WORKFLOW_PATH = '.github/workflows/p0-login-trace-phase-a.yml'
def workflow_template(host,approved):
    raw=ordinary(host,WORKFLOW_PATH).read_text()
    matches=re.findall(r'(?m)^      APPROVED_P0LOGIN_INPUTS_SHA256: ([A-Z_]+|[0-9a-f]{64})$',raw)
    require(len(matches)==1 and matches[0] in ('REVIEW_REQUIRED',approved),'workflow approval differs from exact reviewed input')
    return raw.replace('      APPROVED_P0LOGIN_INPUTS_SHA256: '+matches[0], '      APPROVED_P0LOGIN_INPUTS_SHA256: REVIEW_REQUIRED').encode()

BUILD_WORKFLOW_PATH='.github/workflows/build.yml'
BUILD_GUARD="    if: github.ref != 'refs/heads/validation/p0-login-trace-phase-a'\n"
def ordinary_build_guard(host):
    after=ordinary(host,BUILD_WORKFLOW_PATH).read_bytes()
    needle=('  build:\n'+BUILD_GUARD).encode()
    require(after.count(needle)==1 and after.count(BUILD_GUARD.encode())==1,'exact dedicated-branch ordinary build guard required')
    before=after.replace(needle,b'  build:\n',1)
    return {'path':BUILD_WORKFLOW_PATH,'before_sha256':sha(before),'after_sha256':sha(after),'excluded_ref':'refs/heads/validation/p0-login-trace-phase-a','job':'build'}

def validate_inputs(raw,approved,host):
    require(isinstance(approved,str) and re.fullmatch('[0-9a-f]{64}',approved) and sha(raw)==approved,'independently reviewed input hash required')
    data=parse(raw)
    require(set(data)=={'schema_version','source_basis','phase','source_seal_sha256','publication_sha256','owners','adapter_files','python_suites','toolchain','test_source_audit','workflow_template_sha256','ordinary_build_guard'},'unexpected Phase A input schema')
    require(data['schema_version']==1 and data['source_basis']==BASIS and data['phase']=='phase-a','Phase B requires a future genuine lock artifact; not accepted here')
    require(data['source_seal_sha256']==SEAL_SHA and data['publication_sha256']==PUBLICATION_SHA,'input seal differs')
    seal,publication,allow=pinned_documents(host)
    require(set(data['owners'])==set(OWNERS),'exact four owners required')
    for name,row in data['owners'].items():
        require(set(row)=={'repository','base','commit','tree','changes'},'unexpected owner fields')
        require(row['repository']=='https://github.com/NRG-Wardog/'+name+'.git','wrong source repository')
        pub=publication['owners'][name]
        for key in ('base','commit','tree'):require(full_sha(row[key])==pub[key],'wrong exact owner '+key)
        require(set(row['changes'])==set(allow[name]),'unapproved changed path')
        for path,delta in row['changes'].items():
            require(set(delta)=={'before','after'},'invalid source delta')
            require(delta['after']['type']=='blob' and delta['after']['mode'] in ('100644','100755'),'source delta must be regular file')
            require(delta['after']['sha256']==pub['files'][path],'publication bytes differ')
            if path!='Package.swift' or name!='SideSign':
                source_row=next(r for r in seal['repositories'][name]['changes'] if r['path']==path)
                require(delta['after']['sha256']==source_row['sha256'],'source seal file differs')
        require('Package.resolved' not in row['changes'],'Phase A input cannot supply fabricated resolver lock')
    actual={str(p.relative_to(host)):sha(p.read_bytes()) for p in (host/'ci/p0login').rglob('*') if p.is_file() and not p.is_symlink() and p.name!='inputs-phase-a.json' and '__pycache__' not in p.parts}
    require(data['adapter_files']==actual,'exact adapter inventory mismatch')
    require(data['workflow_template_sha256']==sha(workflow_template(host,approved)),'reviewed workflow template differs')
    require(data['ordinary_build_guard']==ordinary_build_guard(host),'ordinary build guard differs from separately reviewed delta')
    require(data['toolchain']==TOOLCHAIN,'toolchain contract differs')
    require(isinstance(data['python_suites'],list) and data['python_suites'],'fixed Python suites required')
    require([(r['owner'],r['path']) for r in data['python_suites']]==PYTHON_SUITE_PLAN,'unreviewed host suite scope')
    for r in data['python_suites']:
        require(set(r)=={'id','owner','path','test_ids'} and re.fullmatch('[a-z0-9_-]+',r['id']),'suite schema mismatch')
        require(r['test_ids'] and len(r['test_ids'])==len(set(r['test_ids'])) and all(re.fullmatch('[A-Za-z_][A-Za-z0-9_.]+',x) for x in r['test_ids']),'exact finite test IDs required')
    require(len({r['id'] for r in data['python_suites']})==len(data['python_suites']),'duplicate suite ID')
    require(data['test_source_audit']==TEST_SOURCE_AUDIT,'test module initialization audit differs')
    return data

TOOLCHAIN={'developer_dir':'/Applications/Xcode_26.4.1.app/Contents/Developer','architecture':'arm64','xcode':'Xcode 26.4.1\nBuild version 17E202','swift_stdout':'Apple Swift version 6.3.1 (swiftlang-6.3.1.1.2 clang-2100.0.123.102)\nTarget: arm64-apple-macosx26.0\n','swift_stderr':'swift-driver version: 1.148.6 ','clang':'Apple clang version 21.0.0 (clang-2100.0.123.102)','expected_only_reference':'Exact Swift stdout/stderr from failed Phase A run39209074594 artifact49f293de4c3b1c184610986f7097d10160af7970aee7bbdfb5c2e8af867740ef; Xcode/clang versions unchanged; no validation result inherited'}
# Reviewed source bytes are populated from the exact sealed tree by the input generator.
# Literal hashes here are an independent audit anchor, never discovery-time trust.
TEST_SOURCE_AUDIT = {'AnisetteKit': {'Tests/AnisetteKitTests/AnisetteKitTests.swift': '3a3b13ad711b4e4bb8e5b552f4ccc4b06bafd5b29455cd05e4d5e6b09feb0561', 'Tests/AnisetteKitTests/LoginDiagnosticTraceTests.swift': '0a04f3657123356af34ad0c51a50291b1d494dd50376478684aa066996790bbf'}, 'SideSign': {'Tests/SideSignTests/SideSignTests.swift': '511c3fe77e5b4e5e8903ada85e8b2ee4b17f08016cf6ac8db90446158bcd0ad6'}}
PYTHON_SUITE_PLAN = [('AnisetteKit','.ci/native-tests/run_tests.py'),('SideSign','.ci/test_login_trace_source.py')] + [(owner,'tests/'+suite+'/test_contract.py') for owner in ('SideStore','LiveContainer') for suite in ('login_trace','init_diagnostics','adi_consumption')]

