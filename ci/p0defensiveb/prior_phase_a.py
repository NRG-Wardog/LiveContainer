"""Frozen defensive diagnostic Phase A prerequisite; read-only replay, never admission.

Unknown run, artifact, lock and original review bindings remain null. No old
login artifact or independently authored review is relabelled as new evidence.
"""
import builtins
import hashlib
import json
import re
import sys
import types
from pathlib import Path
from phase_a_raw_replay import ArchiveFiles,parse,sha,require

REPOSITORY='NRG-Wardog/LiveContainer'
PHASE_B_REF='refs/heads/validation/p0-defensive-diagnostic-phase-b'
BASIS='defensive-diagnostic-phase-a-swift-split-v1'
INPUT_SHA256='1f129661ec646e3a7781bbca795603fe908d2ab72ecfd0d06affead097f8c62c'
FROZEN_ADAPTER_SHA256='ed9b9bf8c963b2447c3b28b434c9c8a4d5be41a3e2bf076260a8701642ccff6b'
HOST_TREE='3b3ff76bec2d99729a34f4c484e90d624ff9de46'
HOST_PARENT='1f1230372551c4aa0a4f39d93f58be76a8ee163d'
HOST_PARENT_TREE='32ef2a048de23323fae43d8765e119e80379d3cd'
OVERLAY_BASIS='545438e1f0a89fdef375f73273c5c9fc2735cbce'
OVERLAY_TREE='e8014dd771c25c4a05dc76ab0aa304a233642a83'
PHASE_A_BRANCH='validation/p0-defensive-diagnostic-phase-a-swift-split'
EMITTER_FREEZE_SHA256='7fc229ae6a4d201de39c78920fd4941fe8d978e36339d796e7fd91e741bca165'
EMITTER_REVIEW_SHA256='0260ab10a9ddb5584515a997dce06ccc240210a906772fe87a41014eb495db5a'
KNOWN_FAILED_RUN_IDS=frozenset((39300623354,))
EXPECTED_KEYS=frozenset(('repository','run_id','run_attempt','host_commit','host_tree','artifact_id','artifact_sha256','artifact_size','lock_sha256','evidence_index_sha256'))
RECEIPT_FILES={'run_api':'run-api.json','artifact_api':'artifact-api.json','commit_api':'commit-api.json','archive':'artifact.zip'}
ORIGINAL_API_FILES={'run_api':'original-run-api.json','artifact_api':'original-artifact-api.json','commit_api':'original-commit-api.json'}
ORIGINAL_LISTING_FILE='original-artifact-list-api.json'
REVIEWED_PRIOR_FILES=('upload-identity.json','independent-review.json',*ORIGINAL_API_FILES.values(),ORIGINAL_LISTING_FILE)

REVIEW_CHECKS=frozenset(('authenticated_original_capture','ordered_argv_cwd_environment','owned_writer_settlement','source_origin_full_tree','resolved_package_sources','binary_archive_raw_members','tool_sdk_compiler_product_bytes','finite_test_execution','genuine_observed_terminal_lock','complete_raw_evidence_index'))
MAX_JSON=64*1024**2

def _digest(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) and value!='0'*64,'full nonzero SHA256 required');return value

def _git_sha(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) and value!='0'*40,'full nonzero Git SHA required');return value

def _positive(value):
    require(type(value) is int and value>0,'actual positive integer required');return value

def _ordinary(root,relative):
    from phase_a_raw_replay import safe_path
    root=Path(root);safe_path(relative)
    require(root.is_dir() and all(not p.is_symlink() for p in (root,*root.parents)),'ordinary input root required')
    path=root
    for part in relative.split('/'):
        path=path/part;require(not path.is_symlink(),'linked input path')
    require(path.is_file(),'missing ordinary input: '+relative);return path

def _json_bytes(root,relative):
    import retrieve_prior
    return retrieve_prior.read_ordinary(_ordinary(root,relative).absolute(),MAX_JSON)

def make_draft_prior():
    expected={key:None for key in sorted(EXPECTED_KEYS)}
    expected.update(repository=REPOSITORY,host_tree=HOST_TREE)
    return {'schema_version':1,'source_basis':BASIS,'phase':'phase-a',
        'approved_inputs_sha256':INPUT_SHA256,'frozen_adapter_sha256':FROZEN_ADAPTER_SHA256,
        'upload_identity_sha256':None,'independent_review':None,'expected':expected}

def validate_prior_inputs(prior,execution=False):
    require(isinstance(prior,dict) and set(prior)==set(make_draft_prior()),'unexpected defensive Phase A prior schema')
    require(type(prior['schema_version']) is int and prior['schema_version']==1 and prior['source_basis']==BASIS and prior['phase']=='phase-a','wrong prior source basis or phase')
    require(prior['approved_inputs_sha256']==INPUT_SHA256 and prior['frozen_adapter_sha256']==FROZEN_ADAPTER_SHA256,'frozen defensive Phase A closure differs')
    expected=prior['expected'];require(isinstance(expected,dict) and set(expected)==EXPECTED_KEYS,'exact prior capture tuple required')
    for key,value in expected.items():
        if value is None:continue
        if key=='repository':require(value==REPOSITORY,'wrong prior repository')
        elif key in ('run_id','run_attempt','artifact_id','artifact_size'):_positive(value)
        elif key in ('host_commit','host_tree'):_git_sha(value)
        else:_digest(value)
    require(expected['host_tree'] in (None,HOST_TREE),'prior host tree differs from frozen activation')
    require(expected['run_id'] not in KNOWN_FAILED_RUN_IDS,'known failed diagnostic capture cannot be relabelled as success')
    if expected['artifact_size'] is not None:require(expected['artifact_size']<=ArchiveFilesLimit(),'archive exceeds fixed retrieval bound')
    if prior['upload_identity_sha256'] is not None:_digest(prior['upload_identity_sha256'])
    review=prior['independent_review']
    if review is not None:
        require(isinstance(review,dict) and set(review)=={'receipt_sha256','reviewer'},'exact independent review digest and identity required');_digest(review['receipt_sha256'])
        require(isinstance(review['reviewer'],str) and 0<len(review['reviewer'])<=200 and review['reviewer'].strip()==review['reviewer'],'independent reviewer identity required')
    pending=[key for key,value in expected.items() if value is None]
    if execution:
        require(not pending,'successful defensive Phase A run/artifact/lock tuple remains unresolved')
        require(prior['upload_identity_sha256'] is not None,'original upload identity binding unresolved')
        require(review is not None,'original independent replay receipt binding unresolved')
    return {'status':'DRAFT_PRIOR_UNRESOLVED' if pending or review is None or prior['upload_identity_sha256'] is None else 'PRIOR_BINDINGS_STRUCTURALLY_VALID','pending':pending,'execution_admitted':False}

def ArchiveFilesLimit():
    from phase_a_raw_replay import MAX_ARCHIVE
    return MAX_ARCHIVE

def _load_trusted_adapter(prior_adapter):
    """Authenticate the entire closure before compilation, with private imports."""
    host=Path(prior_adapter).absolute()
    manifest_raw=_json_bytes(host,'frozen-closure.json');require(sha(manifest_raw)==FROZEN_ADAPTER_SHA256,'frozen adapter inventory changed')
    manifest=parse(manifest_raw);closure={}
    for name,digest in manifest.items():
        raw=_json_bytes(host,name);require(sha(raw)==_digest(digest),'frozen adapter bytes changed: '+name);closure[name]=raw
    actual=set()
    for path in host.rglob('*'):
        require(not path.is_symlink(),'linked frozen adapter member')
        if path.is_file():actual.add(path.relative_to(host).as_posix())
    require(actual==set(manifest)|{'frozen-closure.json'},'extra or missing frozen closure member')
    raw=closure['ci/p0defensive/inputs-phase-a.json'];require(sha(raw)==INPUT_SHA256,'frozen Phase A input changed')
    modules={};sys_copy=types.ModuleType('sys');sys_copy.__dict__.update(vars(sys));sys_copy.path=list(sys.path);sys_copy.dont_write_bytecode=True
    original_import=builtins.__import__
    names={Path(name).stem for name in closure if name.startswith('ci/p0defensive/') and name.count('/')==2 and name.endswith('.py')}
    def private_import(name,globals=None,locals=None,fromlist=(),level=0):
        if level==0 and name=='sys':return sys_copy
        if level==0 and name in names:return load(name)
        return original_import(name,globals,locals,fromlist,level)
    def load(name):
        if name in modules:return modules[name]
        module=types.ModuleType('_p0defensive_prior_'+name);path=host/'ci/p0defensive'/(name+'.py')
        module.__file__=str(path);module.__builtins__=dict(vars(builtins),__import__=private_import);modules[name]=module
        exec(compile(closure['ci/p0defensive/'+name+'.py'],str(path),'exec',dont_inherit=True),module.__dict__);return module
    gate=load('native_gate');data,blockers=gate.validate_inputs(raw,host,INPUT_SHA256,execute=False)
    require(not blockers,'frozen Phase A source identities incomplete')
    gate._private_modules=modules
    review_raw=_json_bytes(Path(__file__).resolve().parent,'emitter-independent-review.json')
    freeze_raw=_json_bytes(Path(__file__).resolve().parent,'emitter-freeze.json')
    require(sha(review_raw)==EMITTER_REVIEW_SHA256 and sha(freeze_raw)==EMITTER_FREEZE_SHA256,'exact independently reviewed diagnostic emitter changed')
    review=parse(review_raw);freeze=parse(freeze_raw)
    require(set(review)=={'status','payload_sha256','freeze_sha256','parent','base_tree','activated_tree','files','changed_paths','adapter_seals','independent_tests','scope','limitations','external_mutations'},'diagnostic emitter review schema differs')
    require(review['status']=='CLEARED_FOR_EXACT_CAPTURE_ONLY' and review['freeze_sha256']==EMITTER_FREEZE_SHA256 and review['activated_tree']==HOST_TREE and review['parent']==HOST_PARENT and review['base_tree']==HOST_PARENT_TREE and review['external_mutations'] is False,'diagnostic emitter review identity differs')
    require(freeze['input_sha256']==INPUT_SHA256 and freeze['base']==HOST_PARENT and freeze['base_tree']==HOST_PARENT_TREE and freeze['expected_activated_tree']==HOST_TREE and freeze['branch']==PHASE_A_BRANCH and freeze['payload_sha256']==review['payload_sha256'],'diagnostic emitter freeze tuple differs')
    require(review['changed_paths']==len(freeze['changed_paths'])==20 and review['adapter_seals']==len(data['adapter_files'])==60 and review['independent_tests']=={'normal':143,'optimized':143,'failures':0,'skips':0},'diagnostic emitter review coverage differs')
    require({row['path']:row['sha256'] for row in freeze['files']}==manifest and len(freeze['files'])==review['files']==len(manifest)==63,'diagnostic emitter full closure differs')
    require(data['host']['base']==HOST_PARENT and data['host']['tree']==HOST_PARENT_TREE and gate.HOST_PRODUCT_BASE==OVERLAY_BASIS and gate.HOST_PRODUCT_TREE==OVERLAY_TREE,'diagnostic direct parent/overlay basis differs')
    for row in freeze['files']:
        content=closure[row['path']]
        require(('100755' if _ordinary(host,row['path']).stat().st_mode&0o111 else '100644')==row['mode'],'diagnostic emitter local file mode differs')
        require(len(content)==row['bytes'] and row['mode']=='100644' and hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()==row['git_blob'],'diagnostic emitter raw file identity differs')
    return gate,data,raw,closure

def _validate_api(raw,upload_raw,expected,archive):
    import retrieve_prior
    for key in ('run_api','artifact_api','commit_api'):retrieve_prior.validate_api_body(key,raw[key],expected)
    run,artifact,commit=(parse(raw[k]) for k in ('run_api','artifact_api','commit_api'));upload=parse(upload_raw)
    rid=expected['run_id'];attempt=expected['run_attempt'];head=expected['host_commit'];aid=expected['artifact_id']
    require(run.get('head_branch')==PHASE_A_BRANCH and run.get('event') in ('push','workflow_dispatch') and run.get('path','').split('@',1)[0]=='.github/workflows/p0-defensive-diagnostic-phase-a.yml','wrong prior workflow origin')
    require(run.get('html_url')==f'https://github.com/{REPOSITORY}/actions/runs/{rid}','wrong official prior run URL')
    require(artifact.get('name')==f'p0-defensive-diagnostic-phase-a-{head}-{rid}-{attempt}' and artifact['workflow_run'].get('head_branch')==PHASE_A_BRANCH,'artifact does not bind exact run attempt/head')
    require([p['sha'] for p in commit['parents']]==[HOST_PARENT] and expected['host_tree']==HOST_TREE,'prior host parent/tree differs')
    require(archive['sha256']==expected['artifact_sha256'] and archive['bytes']==expected['artifact_size'],'original archive digest/length differs')
    wanted={'GITHUB_REPOSITORY':REPOSITORY,'GITHUB_SHA':head,'GITHUB_RUN_ID':str(rid),'GITHUB_RUN_ATTEMPT':str(attempt),'CAPTURE_ARTIFACT_ID':str(aid),'CAPTURE_ARTIFACT_DIGEST':'sha256:'+expected['artifact_sha256'],'CAPTURE_ARTIFACT_URL':f'https://github.com/{REPOSITORY}/actions/runs/{rid}/artifacts/{aid}'}
    require(isinstance(upload,dict) and set(upload)==set(wanted),'unexpected original upload identity schema')
    # actions/upload-artifact supplies an unprefixed hexadecimal digest.
    require(upload.get('CAPTURE_ARTIFACT_DIGEST') in (expected['artifact_sha256'],wanted['CAPTURE_ARTIFACT_DIGEST']),'original upload digest differs')
    require(all(upload[k]==v for k,v in wanted.items() if k!='CAPTURE_ARTIFACT_DIGEST'),'original upload identity differs')
    return {'repository':REPOSITORY,'run_id':rid,'run_attempt':attempt,'host_commit':head,'host_tree':HOST_TREE,'artifact_id':aid,'artifact_sha256':expected['artifact_sha256']}

def original_api_bytes(prior,receipts,review_raw):
    """Read the unchanged independently reviewed API observations, never fresh GETs."""
    binding=prior['independent_review']
    require(binding is not None and sha(review_raw)==binding['receipt_sha256'],'original independent review bytes changed')
    review=parse(review_raw)
    for key in ('source_basis','expected','approved_inputs_sha256','frozen_adapter_sha256'):
        require(json.dumps(review.get(key),sort_keys=True)==json.dumps(prior[key],sort_keys=True),'original API review covers another capture')
    hashes=review.get('original_receipt_sha256')
    require(isinstance(hashes,dict) and set(hashes)=={'run_api','artifact_api','commit_api','artifact_list_api','archive','upload_identity'},'exact original receipt hash map required')
    for digest in hashes.values():_digest(digest)
    require(hashes['archive']==prior['expected']['artifact_sha256'] and hashes['upload_identity']==prior['upload_identity_sha256'],'original archive/upload review binding differs')
    originals={key:_json_bytes(receipts,name) for key,name in ORIGINAL_API_FILES.items()}
    originals['artifact_list_api']=_json_bytes(receipts,ORIGINAL_LISTING_FILE)
    require(all(sha(value)==hashes[key] for key,value in originals.items()),'original reviewed API bytes changed')
    return originals


def validate_reviewed_original_api(prior,reviewed):
    review_raw=_json_bytes(reviewed,'independent-review.json')
    originals=original_api_bytes(prior,reviewed,review_raw)
    upload_raw=_json_bytes(reviewed,'upload-identity.json')
    require(sha(upload_raw)==prior['upload_identity_sha256'],'original upload identity binding differs')
    _validate_api(originals,upload_raw,prior['expected'],{'sha256':prior['expected']['artifact_sha256'],'bytes':prior['expected']['artifact_size']})
    validate_original_artifact_listing(originals,prior['expected'])
    return originals


def validate_original_artifact_listing(originals,expected):
    """The selected object is derived from this complete original listing, not an HTTP body."""
    listing=parse(originals['artifact_list_api'])
    require(isinstance(listing,dict) and set(listing)=={'total_count','artifacts'},'exact original artifact listing schema required')
    count=listing['total_count'];artifacts=listing['artifacts']
    require(type(count) is int and count>0 and isinstance(artifacts,list) and len(artifacts)==count,'complete original artifact listing required')
    ids=[]
    for artifact in artifacts:
        require(isinstance(artifact,dict) and type(artifact.get('id')) is int and artifact['id']>0,'original listing artifact ID required')
        ids.append(artifact['id'])
    require(len(set(ids))==len(ids) and ids.count(expected['artifact_id'])==1,'unique original artifact selection required')
    selected=artifacts[ids.index(expected['artifact_id'])]
    primary=f"p0-defensive-diagnostic-phase-a-{expected['host_commit']}-{expected['run_id']}-{expected['run_attempt']}"
    require(selected.get('name')==primary and sum(item.get('name')==primary for item in artifacts)==1,'unique original primary artifact name required')
    require(json.dumps(selected,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(parse(originals['artifact_api']),sort_keys=True,separators=(',',':'),allow_nan=False),'selected original artifact object differs from authenticated listing')
    return {'kind':'SELECTED_FROM_AUTHENTICATED_RUN_ARTIFACT_LIST','artifact_list_sha256':sha(originals['artifact_list_api']),'selected_artifact_sha256':sha(originals['artifact_api']),'artifact_id':expected['artifact_id']}


def validate_fresh_api(originals,fresh,upload_raw,expected,archive_identity):
    """No normalization of originals: compare independently valid identity-bearing JSON."""
    import datetime
    require(set(originals)==set(ORIGINAL_API_FILES)|{'artifact_list_api'} and set(fresh)==set(ORIGINAL_API_FILES),'exact original and fresh API body sets required')
    validate_original_artifact_listing(originals,expected)
    original_identity=_validate_api(originals,upload_raw,expected,archive_identity)
    require(_validate_api(fresh,upload_raw,expected,archive_identity)==original_identity,'fresh and original capture identities differ')
    differences={}
    for key in ORIGINAL_API_FILES:
        before=parse(originals[key]);after=parse(fresh[key]);changed=[]
        if key in ('run_api','artifact_api'):
            field='updated_at'
            require((field in before)==(field in after),'classified timestamp presence differs')
            if field in before:
                for value in (before[field],after[field]):
                    require(isinstance(value,str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z',value),'invalid classified UTC timestamp')
                    datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
                if before[field]!=after[field]:changed.append(field)
                del before[field];del after[field]
        require(json.dumps(before,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(after,sort_keys=True,separators=(',',':'),allow_nan=False),'unclassified fresh API response difference: '+key)
        differences[key]={'original_sha256':sha(originals[key]),'fresh_sha256':sha(fresh[key]),'classified_metadata_differences':changed}
    return {'status':'EXACT_CAPTURE_IDENTITY_WITH_CLASSIFIED_METADATA_ONLY','api_bodies':differences}


def _validate_independent_review(raw,prior,receipt_hashes,replay_report):
    binding=prior['independent_review'];require(sha(raw)==binding['receipt_sha256'],'original independent review bytes changed')
    value=parse(raw)
    keys={'schema_version','status','reviewer','source_basis','expected','approved_inputs_sha256','frozen_adapter_sha256','original_receipt_sha256','replay_report_sha256','checks','scope'}
    require(isinstance(value,dict) and set(value)==keys,'unexpected original defensive diagnostic independent review schema')
    require(type(value['schema_version']) is int and value['schema_version']==1 and value['status']=='INDEPENDENT_DEFENSIVE_DIAGNOSTIC_PHASE_A_REVIEW_PASSED','independent original Phase A review did not pass')
    for key in ('source_basis','expected','approved_inputs_sha256','frozen_adapter_sha256'):require(json.dumps(value[key],sort_keys=True)==json.dumps(prior[key],sort_keys=True),'independent review covers another source/capture')
    require(value['reviewer']==binding['reviewer'],'independent reviewer identity changed')
    require(value['original_receipt_sha256']==receipt_hashes,'independent review does not bind genuine original transport bytes')
    require(value['replay_report_sha256']==sha(json.dumps(replay_report,sort_keys=True,separators=(',',':'),allow_nan=False).encode()),'independent actual replay report differs')
    require(isinstance(value['checks'],dict) and set(value['checks'])==REVIEW_CHECKS and all(v is True for v in value['checks'].values()),'independent replay checks incomplete')
    require(value['scope']=={'execution_admitted':False,'production_ready':False,'guest_execution':False,'live_provider_or_apple_requests':False,'compiled_final_lock_child':False},'independent review expanded capture scope')
    return value

def _replay_original(files,prior,raw,upload_raw,prior_adapter,roots):
    from phase_a_evidence_replay import verify_evidence
    gate,data,input_raw,closure=_load_trusted_adapter(prior_adapter)
    identity=_validate_api(raw,upload_raw,prior['expected'],files.identity)
    artifact_provenance=validate_original_artifact_listing(raw,prior['expected'])
    replay=verify_evidence(files,gate,data,input_raw,identity,roots,closure)
    require(replay['report']['evidence_index_sha256']==prior['expected']['evidence_index_sha256'] and sha(replay['lock_bytes'])==prior['expected']['lock_sha256'],'independently supplied original index/lock differs')
    replay['report']['artifact_original_provenance']=artifact_provenance
    hashes={key:sha(content) for key,content in raw.items()};hashes.update(archive=files.identity['sha256'],upload_identity=sha(upload_raw))
    return replay,hashes

def verify_original_capture(prior,receipts,prior_adapter,roots):
    """Replay original Phase A bytes before Phase B exists, without self-attesting.

    The returned report is exactly the stable report bound by an independently
    authored review's replay_report_sha256. No current-run identity, pathname,
    token, retrieval receipt or independent-review file is consulted. This pure
    local replay does not establish the original transport's authentication;
    the independent reviewer must authenticate that transport separately.
    """
    validate_prior_inputs(prior,execution=False)
    require(all(value is not None for value in prior['expected'].values()),'actual original capture tuple remains unresolved')
    require(prior['upload_identity_sha256'] is not None,'original upload identity binding unresolved')
    raw={key:_json_bytes(receipts,name) for key,name in RECEIPT_FILES.items() if key!='archive'}
    raw['artifact_list_api']=_json_bytes(receipts,'artifact-list-api.json')
    upload_raw=_json_bytes(receipts,'upload-identity.json');require(sha(upload_raw)==prior['upload_identity_sha256'],'original upload identity binding differs')
    with ArchiveFiles(_ordinary(receipts,'artifact.zip')) as files:
        replay,hashes=_replay_original(files,prior,raw,upload_raw,prior_adapter,roots)
        replay['original_receipt_sha256']=hashes
        replay['replay_report_sha256']=sha(json.dumps(replay['report'],sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        return replay

def verify_prior_capture(prior,receipts,prior_adapter,roots,current,inputs_path=None,inputs_raw=None,work_root=None):
    """Return genuine lock bytes only after original and current-run evidence replay."""
    validate_prior_inputs(prior,execution=True)
    require(isinstance(inputs_raw,bytes) and inputs_path is not None and work_root is not None,'current input bytes/path/work binding required')
    require(parse(inputs_raw).get('prior_phase_a')==prior,'current input prior binding differs')
    require(_json_bytes(Path(inputs_path).parent,Path(inputs_path).name)==inputs_raw,'current input file changed')
    raw={key:_json_bytes(receipts,name) for key,name in RECEIPT_FILES.items() if key!='archive'}
    upload_raw=_json_bytes(receipts,'upload-identity.json');require(sha(upload_raw)==prior['upload_identity_sha256'],'original upload identity binding differs')
    review_raw=_json_bytes(receipts,'independent-review.json');require(sha(review_raw)==prior['independent_review']['receipt_sha256'],'original review receipt binding differs')
    from phase_a_transport_replay import _validate_current_transport
    with ArchiveFiles(_ordinary(receipts,'artifact.zip')) as files:
        identities={key:{'sha256':sha(value),'bytes':len(value)} for key,value in raw.items()};identities['archive']={k:files.identity[k] for k in ('sha256','bytes')}
        transport_hash=_validate_current_transport(current,parse(_json_bytes(receipts,'retrieval-receipts.json')),identities,prior['expected'],helper_raw=_json_bytes(receipts,'retrieval-helper.json'),inputs_path=inputs_path,inputs_raw=inputs_raw,work_root=work_root,receipts_dir=receipts)
        originals=original_api_bytes(prior,receipts,review_raw)
        fresh_comparison=validate_fresh_api(originals,raw,upload_raw,prior['expected'],files.identity)
        replay,hashes=_replay_original(files,prior,originals,upload_raw,prior_adapter,roots)
        review=_validate_independent_review(review_raw,prior,hashes,replay['report'])
        replay['report'].update(current_api_comparison=fresh_comparison,current_api_sha256={key:sha(value) for key,value in raw.items()},independent_review_sha256=sha(review_raw),independent_reviewer=review['reviewer'],original_receipt_sha256=hashes,current_run=dict(current),current_retrieval_receipts_sha256=transport_hash,execution_admitted=False,prerequisite_scope='EXACT_DEFENSIVE_PHASE_B_LOCK_INPUT_ONLY')
        return replay
