"""Finite Phase B preparation contract. Pending objects never authorize execution."""
import copy, json
from pathlib import Path
from inventory import parse, sha, ordinary, require, TOOLCHAIN
from graph_contract import BASIS, KNOWN, draft_graph

BRANCH = 'validation/p0-defensive-diagnostic-phase-b'
WORKFLOW = '.github/workflows/p0-defensive-diagnostic-phase-b.yml'
INPUTS = 'ci/p0defensiveb/inputs-phase-b.pending.json'
ADAPTER = 'ci/p0defensiveb'
ANCHOR = 'APPROVED_P0DEFENSIVEB_INPUTS_SHA256'
STATUS = 'PREPARATION_ONLY_PENDING_GENUINE_PHASE_A'
PENDING = {
    'phase_a': {'approved_inputs_sha256':None,'approved_overlay_sha256':None,'approved_verifier_sha256':None,
        'repository':'NRG-Wardog/LiveContainer','run_id':None,'run_attempt':None,'host_commit':None,'host_tree':None,
        'artifact_id':None,'artifact_sha256':None,'artifact_size':None,'evidence_index_sha256':None,
        'upload_identity_sha256':None,'independent_review_sha256':None,'independent_review_source':None,
        'observed_sidesign_lock_sha256':None,'terminal_sidesign_lock_sha256':None},
    'SideSign': {'parent':KNOWN['SideSign'][0],'commit':None,'tree':None,'lock_blob':None,'lock_sha256':None,
        'authenticated_readback_sha256':None,'independent_lock_child_review_sha256':None},
    'SideSign_integrity_source': {'parent':None,'commit':None,'tree':None,'retained_lock_sha256':None,
        'authenticated_readback_sha256':None,'independent_source_child_review_sha256':None},
    'SideStore': {'parent':KNOWN['SideStore'][0],'commit':None,'tree':None,'sidesign_gitlink':None,
        'authenticated_readback_sha256':None,'independent_gitlink_review_sha256':None},
    'post_phase_b_SideStore_app_lock_child': {'tested_gitlink_commit':None,'parent':None,'commit':None,'tree':None,
        'observed_lock_sha256':None,'terminal_lock_sha256':None,'lock_blob':None,
        'compiled_final_commit':False,'independent_equivalence_review_sha256':None},
    'source_specific_prior_replay': {'adapter_files':None,'replay_report_sha256':None,'independent_review_sha256':None},
    'phase_b_execution_review':None,
}
COMMAND_ORDER = ['verify-host-and-complete-source-graph','self-contained-adapter-tests','capture-toolchain',
    'authenticated-current-run-phase-a-retrieval','independent-phase-a-command-source-replay',
    'verify-resolver-lock-and-integrity-source-and-gitlink-descendants','native-prerequisites','frozen-native-transport-build',
    'network-denied-exact38-consumer-tests','unsigned-sidestore-build','unsigned-livecontainer-build','network-denied-genuine-source-integrity-exact8',
    'inspect-products-and-internal-sidebackup','compiled-localization-plural-permission-checks',
    'terminal-source-lock-toolchain-provenance','settled-writers-evidence-index']
CLAIMS = {'production_ready':False,'real_ADI_executed':False,'guest_execution':False,'device_validation':False,
    'real_provider_contacted':False,'credential_access':False,'distribution_ipa_built':False,'app_typechecked':False}


def adapter_files(host):
    root = Path(host)/ADAPTER; out = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'linked adapter path')
        if path.is_file() and '__pycache__' not in path.parts and str(path.relative_to(host)) != INPUTS:
            out[str(path.relative_to(host))] = sha(path.read_bytes())
    return out


def workflow_contract(host):
    raw = ordinary(host,WORKFLOW).read_bytes()
    require(raw.count(('      '+ANCHOR+': REVIEW_REQUIRED\n').encode()) == 1, 'preparation workflow must remain REVIEW_REQUIRED')
    require(INPUTS.encode() in raw, 'workflow must consume explicitly pending input path')
    require(b'contents: read\n' in raw and b'actions: read\n' in raw and b'persist-credentials: false\n' in raw, 'read-only capture workflow required')
    build = ordinary(host,'.github/workflows/build.yml').read_bytes()
    guard = ("    if: github.ref != 'refs/heads/"+BRANCH+"'\n").encode()
    require(build.count(b'  build:\n'+guard) == 1 and build.count(guard) == 1, 'exact isolated ordinary-build exclusion required')
    before = build.replace(b'  build:\n'+guard,b'  build:\n',1)
    require(sha(before) == '794d75f941bb6e7ca430a7c0ca05d6899f05ec65786cd81142a459974c62acb4', 'ordinary workflow baseline drift')
    return {'workflow_sha256':sha(raw),'ordinary_build_before_sha256':sha(before),'ordinary_build_after_sha256':sha(build)}


def validate_pending(data,host):
    require(set(data) == {'schema_version','basis','status','bindings','graph','toolchain','command_order','consumer_tests','compiled_resources','claims','adapter_files','workflow','source_observation'}, 'pending input schema differs')
    require(type(data['schema_version']) is int and data['schema_version']==1 and data['basis']==BASIS and data['status']==STATUS, 'only pending preparation is implemented')
    require(data['bindings']==PENDING, 'future capture identities/locks/reviews must remain unresolved in this preparation')
    require(data['graph']==draft_graph() and data['toolchain']==TOOLCHAIN and data['command_order']==COMMAND_ORDER, 'known graph/toolchain/plan changed')
    require(data['consumer_tests']=={'owners':['SideStore','LiveContainer'],'suite_counts':{'init_diagnostics':5,'adi_consumption':6,'login_trace':8},'total':38,'failures':0,'errors':0,'skipped':0}, 'finite consumer inventory changed')
    require(data['compiled_resources']=={'catalog_keys':2088,'plural_language_rows':24,'permission_languages':7,'permission_purpose_keys':32,'runtime_plural_selection':False}, 'resource coverage changed')
    require(data['claims']==CLAIMS, 'preparation cannot claim executed evidence')
    require(data['adapter_files']==adapter_files(host) and data['workflow']==workflow_contract(host), 'adapter or workflow bytes changed; regenerate preparation inventory')
    require(isinstance(data['source_observation'],dict) and set(data['source_observation'])=={'sha256','file'}, 'known-source observation reference required')
    require(data['source_observation']['file']=='known-source-observation.json' and data['source_observation']['sha256']==sha(ordinary(Path(host)/ADAPTER,'known-source-observation.json').read_bytes()), 'source observation bytes changed')
    return data


def execute_barrier(data):
    # Deliberately unconditional. Supplying plausible hashes/booleans cannot invent
    # the source-specific replay adapter or convert the pending plan into approval.
    raise ValueError('Phase B execution is unavailable in this preparation: genuine independently reviewed A+B Phase A evidence, published lock-only SideSign intermediate and reviewed lock-preserving integrity source child, gitlink-only SideStore child, source-specific prior replay, and final input/overlay review are still required')
