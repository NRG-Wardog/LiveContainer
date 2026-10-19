"""Complete capture schema. Null true identities prevent all execution side effects."""
import json,re
from pathlib import Path
from inventory import parse,sha,ordinary,require,TOOLCHAIN,full_sha
from capture_contract import BRANCH,WORKFLOW,ADAPTER,ANCHOR,COMMAND_ORDER,CLAIMS
from graph_contract import BASIS,KNOWN,validate_graph,execution_draft_graph
from retention import BOUNDS

INPUT_PATH='ci/p0defensiveb/inputs-phase-b.pending.json'
RECEIPTS=('SideSign-lock.publication.json','SideSign.publication.json','SideStore.publication.json','independent-descendant-clearance.json','independent-integrity-source-clearance.json')
DESCENDANTS=('SideSign_lock','SideSign','SideStore')


def files(host):
    out={}
    for p in sorted((host/ADAPTER).rglob('*')):
        require(not p.is_symlink(),'linked adapter file')
        if p.is_file() and '__pycache__' not in p.parts and str(p.relative_to(host))!=INPUT_PATH:
            out[str(p.relative_to(host))]=sha(p.read_bytes())
    return out


def workflow(host,approved=None):
    raw=ordinary(host,WORKFLOW).read_text()
    values=re.findall(r'(?m)^      '+ANCHOR+r': ([A-Z_]+|[0-9a-f]{64})$',raw)
    require(len(values)==1 and values[0] in ('REVIEW_REQUIRED',approved),'workflow activation anchor differs')
    template=raw.replace('      '+ANCHOR+': '+values[0],'      '+ANCHOR+': REVIEW_REQUIRED').encode()
    build=ordinary(host,'.github/workflows/build.yml').read_bytes();guard=("    if: github.ref != 'refs/heads/"+BRANCH+"'\n").encode()
    require(build.count(b'  build:\n'+guard)==1 and build.count(guard)==1,'exact build guard required')
    original=build.replace(b'  build:\n'+guard,b'  build:\n',1)
    require(sha(original)=='794d75f941bb6e7ca430a7c0ca05d6899f05ec65786cd81142a459974c62acb4','ordinary workflow changed beyond guard')
    return {'template_sha256':sha(template),'build_before_sha256':sha(original),'build_after_sha256':sha(build)},values[0]


def descendants_draft():
    return {'SideSign_lock':{'commit':None,'tree':None},'SideSign':{'commit':None,'tree':None},'SideStore':{'commit':None,'tree':None},
            'receipt_sha256':{name:None for name in RECEIPTS}}


def validate_descendants(data,host,graph,execution=False):
    from integrity_source import PATCH_REVIEW_SHA256
    require(set(data)==set(descendants_draft()),'exact descendant bindings required')
    for owner in DESCENDANTS:
        require(set(data[owner])=={'commit','tree'},'descendant tuple schema differs')
        row=graph['sidesign_edges']['resolver_lock'] if owner=='SideSign_lock' else graph['owners'][owner]
        for name,value in data[owner].items():
            if value is not None:full_sha(value)
            if execution:require(value==row[name],'descendant and graph tuples differ')
    receipts=data['receipt_sha256'];require(set(receipts)==set(RECEIPTS),'exact original descendant receipts required')
    for name,value in receipts.items():
        if value is not None:require(re.fullmatch('[0-9a-f]{64}',value) and value!='0'*64,'actual descendant receipt digest required')
        if execution:require(value is not None and sha(ordinary(host/ADAPTER/'reviewed',name).read_bytes())==value,'original descendant receipt bytes differ')
    if not execution:return
    # Each edge has its own original publication readback and true sole parent.
    for owner,filename in (('SideSign_lock','SideSign-lock.publication.json'),('SideSign','SideSign.publication.json'),('SideStore','SideStore.publication.json')):
        raw=parse(ordinary(host/ADAPTER/'reviewed',filename).read_bytes())
        require(set(raw)=={'repository','commit','tree','ref'},'publication readback schema differs')
        repository='SideSign' if owner=='SideSign_lock' else owner
        row=graph['sidesign_edges']['resolver_lock'] if owner=='SideSign_lock' else graph['owners'][owner]
        parent=graph['sidesign_edges']['integrity_source']['parent'] if owner=='SideSign' else row.get('parent',row.get('base'))
        commit=raw['commit'];tree=raw['tree'];ref=raw['ref']
        require(raw['repository']=='NRG-Wardog/'+repository and commit['sha']==row['commit'] and commit['tree']['sha']==row['tree'] and [v['sha'] for v in commit['parents']]==[parent], 'publication commit/parent/tree differs')
        require(tree['sha']==row['tree'] and tree['truncated'] is False and ref['object']['sha']==row['commit'],'publication tree/ref differs')
    review=parse(ordinary(host/ADAPTER/'reviewed','independent-descendant-clearance.json').read_bytes())
    require(set(review)=={'schema_version','scope','phase_a_artifact_sha256','SideSign_lock','SideSign','SideStore','compiled_final_commit','phase_b_execution_approved'},'descendant review schema differs')
    require(type(review['schema_version']) is int and review['schema_version']==1 and review['scope']=='DEFENSIVE_AB_SOURCE_ONLY_DESCENDANT_EQUIVALENCE' and review['compiled_final_commit'] is False and review['phase_b_execution_approved'] is False,'descendant review scope differs')
    for owner in DESCENDANTS:require(review[owner]==data[owner],'descendant review tuple differs')
    source=parse(ordinary(host/ADAPTER/'reviewed','independent-integrity-source-clearance.json').read_bytes())
    require(set(source)=={'schema_version','scope','patch_review_sha256','SideSign_lock','SideSign','lock_sha256','compiled_final_commit','phase_b_execution_approved'},'integrity source clearance schema differs')
    require(type(source['schema_version']) is int and source['schema_version']==1 and source['scope']=='EXACT_LOCK_PRESERVING_INTEGRITY_SOURCE_CHILD' and source['patch_review_sha256']==PATCH_REVIEW_SHA256,'independent integrity source scope differs')
    require(source['SideSign_lock']==data['SideSign_lock'] and source['SideSign']==data['SideSign'] and source['lock_sha256']==graph['lock_sha256'],'independent integrity source lineage differs')
    require(source['compiled_final_commit'] is False and source['phase_b_execution_approved'] is False,'source review cannot grant runtime or execution approval')


def validate_inputs(raw,host,approved=None,execution=False):
    from prior_phase_a import validate_prior_inputs,validate_reviewed_original_api
    data=parse(raw)
    require(set(data)=={'schema_version','basis','phase','status','execution_review','graph','prior_phase_a','descendants','toolchain','retention_bounds','adapter_files','workflow','claims','compiled_final_commit'},'complete Phase B input schema differs')
    require(type(data['schema_version']) is int and data['schema_version']==2 and data['basis']==BASIS and data['phase']=='phase-b','exact Phase B identity required')
    require(data['status'] in ('PENDING_GENUINE_CAPTURE_BINDINGS','BOUND_CAPTURE_PROPOSAL') and data['execution_review'] is None,'JSON cannot grant execution approval')
    bound=data['status']=='BOUND_CAPTURE_PROPOSAL'
    require(data['toolchain']==TOOLCHAIN and data['retention_bounds']==BOUNDS and data['claims']==CLAIMS and data['compiled_final_commit'] is False,'capture scope or toolchain differs')
    validate_graph(data['graph'],execution=bound);validate_prior_inputs(data['prior_phase_a'],execution=bound)
    validate_descendants(data['descendants'],host,data['graph'],execution=bound)
    require(data['adapter_files']==files(host),'actual adapter bytes differ')
    wf,anchor=workflow(host,sha(raw));require(wf==data['workflow'],'workflow bytes differ')
    if bound:
        validate_reviewed_original_api(data['prior_phase_a'],host/ADAPTER/'reviewed')
        require(data['graph']['lock_sha256']==data['prior_phase_a']['expected']['lock_sha256'],'Phase A/SideSign lock differs')
        receipt=parse(ordinary(host/ADAPTER/'reviewed','independent-descendant-clearance.json').read_bytes())
        require(receipt['phase_a_artifact_sha256']==data['prior_phase_a']['expected']['artifact_sha256'],'descendant review covers another capture')
    else:
        require(data['graph']==execution_draft_graph() and data['descendants']==descendants_draft(),'pending input cannot fabricate future children')
    if approved is not None and approved!='REVIEW_REQUIRED':require(approved==sha(raw),'supplied approved digest differs')
    if execution:
        require(bound,'Phase B execution blocked: genuine Phase A and published descendant bindings remain pending')
        require(approved==sha(raw) and anchor==sha(raw),'exact independent input/workflow activation approval required')
    return data
