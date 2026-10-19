"""Known A+B source graph; future resolver/gitlink descendants are deliberately null.

No source acquisition, lock generation, publication, or native execution occurs here.
"""
import copy, configparser, re
import source_primitives as primitives
from inventory import full_sha, parse
from pathlib import Path
from inventory import git, entries, require, sha, snapshot

BASIS = 'defensive-diagnostic-phase-b-v1'
KNOWN = {
    'AnisetteKit': ('227dfd8c8456cd62e4ceff4971b17afb2003d7e8', '4d31646c46a7af3d911bb9d52eeffe9cbc26a3dd'),
    'SideSign': ('b28fb0b72937849d4428e9ae313209b606f859b4', '6ecab37d6f7d73763f50cc1f09ff1f93bd4ab9ee'),
    'SideStore': ('d507f9e417f12c262b4d7e717c84d4a244c8e625', '829d5e86ae2365b2870d268e77735f11f16944fb'),
    'LiveContainer': ('545438e1f0a89fdef375f73273c5c9fc2735cbce', 'e8014dd771c25c4a05dc76ab0aa304a233642a83'),
}
NATIVE_TUPLES = {
    'idevice': ('803f9368e6b27a43d8a9f22dc0ec281c87883113', 'f5ac11668bae97e577e7c4fc098b5484df1c9af1'),
    'jktcp': ('32c0210f286b4fd16efe05be4f57167a9d94459b', 'e94eaefdcae5fe54a535186e36a0b2ebccc9bf13'),
    'minimuxer': ('efbcab05d7d636aa37c6bf6c7f364d122c5610f6', '30aa947645c5befb0c3210700095c8b039893d83'),
}
STATIC_CHILDREN = {
    'LiveContainer/OpenSSL': ('623c84da314e85363236507ca38a4bde65df21c3', '21bc09387e7f91a46eb8bd26587ce1d052277801'),
    'LiveContainer/litehook': ('8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55', '62bc06a17a1c12d805aec1ada25910bfa9f89781'),
    'idevice/cpp/plist_ffi': ('66e6e6362b58bc361725c3e1b0a34af498aa2b3a', '1dc97bcad12d41a13417ae05fbcdc4408c6df553'),
}
OLD_SIGN = 'c733332b0d64022cd603ab9ac5de054413729aab'
OLD_AK = 'e6e9d4aac698de2a5219aaef02c9a417da45f4e9'
PRODUCER_PATHS = ('Native/Loader/adi_consumption_debug.h', 'Sources/AnisetteDataProvider.swift', 'Sources/LoginDiagnosticTrace.swift')


def source_objects(root, owner):
    commit, tree = KNOWN[owner]
    require(git(root, 'rev-parse', commit+'^{tree}').decode().strip() == tree, 'known source tree differs: '+owner)
    rows = entries(root, commit)
    result = {}
    for path, (mode, kind, oid) in rows.items():
        require(kind in ('blob', 'commit'), 'unknown source object')
        result[path] = {'mode': mode, 'type': kind, 'git_object': oid}
        if kind == 'blob':
            raw = git(root, 'cat-file', 'blob', oid)
            result[path].update(sha256=sha(raw), bytes=len(raw))
    return {'commit': commit, 'tree': tree, 'tracked': result}


PREVIOUS_AK = 'e72d04b84123823c93e9162daffa73b7afcfd2c9'
PREVIOUS_SIGN = 'a375e72d1ff39319c14d22ab98ddecd46c758783'
SWIFT_BEFORE_SHA256 = '9c55c035d640cae8c2b6ac173db9f118a4e49cce789c0dba24f4cffca58476de'
SWIFT_AFTER_SHA256 = '2b3913be77f019de3f0520e8ea8fcdad1a1b4a638c2493e84d063f07f813e855'
ADI_SPAN_MARKER = b'private enum TemporaryADIConsumptionTrace {'
DIAGNOSTIC_APPEND_MARKER = b'\n// Independent optional wire: v1 constructor reason/engine text stays unchanged.\n'
DIAGNOSTIC_RECEIPT_SHA256 = {'diagnostic-source-inventory.json': '7f8ae5ca1cdf06e5b5ee6ebb7e808fadafd6f23294d0768b9fa0b3d34f5cac23', 'AnisetteKit.diagnostic-publication-original.json': '1667e3e2799eaaeac095ab6f5052d8150413ba0c05ae7e2961799174723da11d', 'diagnostic-review-seal.json': '101025545b417c304ec192f5cf71599548270838b9c1ca804893a2aae439756c'}


def diagnostic_source_review(source):
    """Same-tree source review keeps its original local commit label unchanged."""
    directory = Path(__file__).resolve().parent / 'prior_adapter/ci/p0defensive/reviewed'
    reviewed = {}
    for name, digest in DIAGNOSTIC_RECEIPT_SHA256.items():
        path = directory / name
        require(not path.is_symlink() and path.is_file(), 'ordinary diagnostic source receipt required')
        raw = path.read_bytes()
        require(sha(raw) == digest, 'diagnostic source receipt changed: ' + name)
        reviewed[name] = parse(raw)
    inventory = reviewed['diagnostic-source-inventory.json']
    publication = reviewed['AnisetteKit.diagnostic-publication-original.json']
    seal = reviewed['diagnostic-review-seal.json']
    require(inventory['commit'] == seal['commit'] == publication['reviewed_local_commit'] == 'e0267064280008cee34846a00eba1d7eb7aeba5c', 'original reviewed local source identity differs')
    require(inventory['tree'] == seal['tree'] == publication['tree'] == source['tree'] == KNOWN['AnisetteKit'][1], 'reviewed and published diagnostic trees differ')
    require(publication['commit'] == source['commit'] == KNOWN['AnisetteKit'][0] and publication['parent'] == seal['base_commit'] == PREVIOUS_AK, 'published diagnostic source tuple differs')
    require(inventory['files'] == source['tracked'], 'complete reviewed diagnostic source bytes differ')
    return {'reviewed_local_commit': inventory['commit'], 'published_commit': source['commit'], 'tree': source['tree'], 'receipt_sha256': dict(DIAGNOSTIC_RECEIPT_SHA256), 'complete_tracked_files': len(inventory['files'])}


def one_pin_edge(sign, before_commit, after_commit, before_ak, after_ak):
    require(git(sign, 'rev-list', '--parents', '-n', '1', after_commit).decode().split() == [after_commit, before_commit], 'SideSign manifest-only parent differs')
    delta = snapshot(sign, before_commit, after_commit)
    require(set(delta['changes']) == {'Package.swift'}, 'SideSign must remain manifest-only before genuine resolution')
    before = git(sign, 'show', before_commit + ':Package.swift')
    after = git(sign, 'show', after_commit + ':Package.swift')
    needle = ('revision: "' + before_ak + '"').encode()
    require(before.count(needle) == 1 and after == before.replace(needle, ('revision: "' + after_ak + '"').encode(), 1), 'manifest exceeds exact AK revision change')
    old_lock = git(sign, 'show', before_commit + ':Package.resolved')
    require(old_lock == git(sign, 'show', after_commit + ':Package.resolved'), 'fabricated SideSign input lock')
    return {'parent': before_commit, 'commit': after_commit, 'before_ak': before_ak, 'after_ak': after_ak, 'changed_paths': ['Package.swift'], 'unchanged_lock_sha256': sha(old_lock)}


def producer_proof(ak):
    proof = {}
    for path in PRODUCER_PATHS:
        old = git(ak, 'show', OLD_AK + ':' + path)
        previous = git(ak, 'show', PREVIOUS_AK + ':' + path)
        new = git(ak, 'show', KNOWN['AnisetteKit'][0] + ':' + path)
        require(old == previous, 'historical producer parity changed: ' + path)
        if path != 'Sources/AnisetteDataProvider.swift':
            require(old == new, 'consumer producer changed: ' + path)
            proof[path] = {'before_sha256': sha(old), 'after_sha256': sha(new), 'byte_identical': True}
            continue
        require(sha(old) == SWIFT_BEFORE_SHA256 and sha(new) == SWIFT_AFTER_SHA256, 'exact reviewed diagnostic Swift source hashes differ')
        require(old.count(ADI_SPAN_MARKER) == new.count(ADI_SPAN_MARKER) == 1, 'unique ADI span marker required')
        start_old = old.index(ADI_SPAN_MARKER); start_new = new.index(ADI_SPAN_MARKER)
        span = old[start_old:]; end_new = start_new + len(span)
        require(new[start_new:end_new] == span, 'ADI consumer span changed')
        require(new[end_new:].startswith(DIAGNOSTIC_APPEND_MARKER), 'exact appended diagnostic boundary differs')
        proof[path] = {'before_sha256': sha(old), 'after_sha256': sha(new), 'byte_identical': False,
            'diagnostic_extension_reviewed': True, 'adi_span_byte_identical': True,
            'adi_span_sha256': sha(span), 'adi_span_bytes': len(span), 'before_adi_span_start': start_old,
            'after_adi_span_start': start_new, 'after_adi_span_end': end_new,
            'appended_diagnostic_marker_sha256': sha(DIAGNOSTIC_APPEND_MARKER)}
    return proof


def observe_known_sources(roots):
    require(set(roots) == set(KNOWN), 'exact four known source roots required')
    result = {owner: source_objects(roots[owner], owner) for owner in KNOWN}
    sign = roots['SideSign']; ak = roots['AnisetteKit']
    require(git(ak, 'rev-list', '--parents', '-n', '1', KNOWN['AnisetteKit'][0]).decode().split() == [KNOWN['AnisetteKit'][0], PREVIOUS_AK], 'published diagnostic AK parent differs')
    ancestry = [one_pin_edge(sign, OLD_SIGN, PREVIOUS_SIGN, OLD_AK, PREVIOUS_AK),
                one_pin_edge(sign, PREVIOUS_SIGN, KNOWN['SideSign'][0], PREVIOUS_AK, KNOWN['AnisetteKit'][0])]
    require(result['SideStore']['tracked']['Dependencies/SideSign'] == {'mode':'160000','type':'commit','git_object':OLD_SIGN}, 'baseline SideStore gitlink differs')
    review = diagnostic_source_review(result['AnisetteKit'])
    return {'owners': result, 'producer_parity': producer_proof(ak), 'diagnostic_source_review': review,
            'manifest_one_pin_ancestry': ancestry, 'reserve_source_override': None}


def draft_graph():
    owners = {name:{'repository':'https://github.com/NRG-Wardog/'+name+'.git','commit':commit,'tree':tree} for name,(commit,tree) in {**KNOWN,**NATIVE_TUPLES}.items()}
    for name in ('SideSign','SideStore'):
        owners[name] = {'repository':owners[name]['repository'], 'base':owners[name]['commit'], 'base_tree':owners[name]['tree'], 'commit':None, 'tree':None}
    return {'kind':'PENDING_GENUINE_PHASE_A_AND_DESCENDANTS', 'owners':owners,
            'children':{**{path:{key:row[key] for key in ('commit','tree')} for path,row in STATIC_CHILDREN.items()},
                'SideStore/Dependencies/minimuxer':{'commit':NATIVE_TUPLES['minimuxer'][0],'tree':NATIVE_TUPLES['minimuxer'][1]},
                'SideStore/Dependencies/SideSign':{'commit':None,'tree':None}},
            'SideSign_lock_sha256':None, 'SideStore_app_lock_after_sha256':None}

STATIC_CHILDREN = {
    'LiveContainer/OpenSSL': {'commit': '623c84da314e85363236507ca38a4bde65df21c3', 'tree': '21bc09387e7f91a46eb8bd26587ce1d052277801', 'declared_repository': 'https://github.com/krzyzanowskim/OpenSSL', 'repository': 'https://github.com/krzyzanowskim/OpenSSL'},
    'LiveContainer/litehook': {'commit': '8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55', 'tree': '62bc06a17a1c12d805aec1ada25910bfa9f89781', 'declared_repository': 'https://github.com/LiveContainer/litehook', 'repository': 'https://github.com/LiveContainerMirror/litehook.git'},
    'idevice/cpp/plist_ffi': {'commit': '66e6e6362b58bc361725c3e1b0a34af498aa2b3a', 'tree': '1dc97bcad12d41a13417ae05fbcdc4408c6df553', 'declared_repository': 'https://github.com/jkcoxson/plist_ffi.git', 'repository': 'https://github.com/jkcoxson/plist_ffi.git'},
}

OWNER_CHILDREN = {'SideStore/Dependencies/SideSign': 'SideSign', 'SideStore/Dependencies/minimuxer': 'minimuxer'}

def relative_path(value):
    require(isinstance(value, str) and value and not value.startswith('/') and all(part not in ('', '.', '..', '.git') for part in value.split('/')) and '\\' not in value and '\0' not in value, 'unsafe graph path')
    return value

def commit_identity(root, commit):
    full_sha(commit)
    require(git(root, 'cat-file', '-t', commit).strip() == b'commit', 'graph object is not a commit')
    header = git(root, 'cat-file', 'commit', commit).split(b'\n\n', 1)[0].splitlines()
    parents = [line[7:].decode('ascii') for line in header if line.startswith(b'parent ')]
    trees = [line[5:].decode('ascii') for line in header if line.startswith(b'tree ')]
    require(len(trees) == 1, 'commit has no unique tree')
    full_sha(trees[0])
    for parent in parents:
        full_sha(parent)
    return {'commit': commit, 'tree': trees[0], 'parents': parents}

def child_requirements(prefix, root, commit, graph):
    """Immediate child requirements checked against parent objects before cloning.

    Read committed .gitmodules, not mutable disk text. Dormant reviewed declarations
    (LC's fishhook) are not additional gitlinks; all declared options are still
    constrained to path/url. The immutable parent tree seals their exact contents.
    """
    relative_path(prefix)
    full_sha(commit)
    records = entries(root, commit)
    links = {path: oid for path, (mode, kind, oid) in records.items() if mode == '160000' and kind == 'commit'}
    require(all((mode == '160000') == (kind == 'commit') for mode, kind, oid in records.values()), 'invalid source gitlink mode/type')
    expected = {path: row for path, row in graph['children'].items() if path.startswith(prefix + '/') and not any(path.startswith(other + '/') for other in graph['children'] if other != path and other.startswith(prefix + '/'))}
    require({prefix + '/' + path for path in links} == set(expected), 'missing/extra recursive child in actual parent tree: ' + prefix)
    if not links:
        return {}
    require('.gitmodules' in records and records['.gitmodules'][:2] == ('100644', 'blob'), 'ordinary committed .gitmodules required')
    modules = configparser.ConfigParser(interpolation=None, strict=True)
    modules.read_string(git(root, 'cat-file', 'blob', records['.gitmodules'][2]).decode('utf-8'))
    require(not modules.defaults(), 'gitmodules default options forbidden')
    declared = {}
    for section in modules.sections():
        values = dict(modules[section])
        require(re.fullmatch(r'submodule "[^"\n]+"', section) and set(values) == {'path', 'url'}, 'unreviewed child branch/configuration')
        path = relative_path(values['path'])
        require(path not in declared, 'duplicate declared child path')
        declared[path] = values['url']
    for path, commit in links.items():
        relative_path(path)
        row = expected[prefix + '/' + path]
        require(declared.get(path) == row['declared_repository'] and commit == row['commit'], 'child declared repository/commit mismatch')
    return copy.deepcopy(expected)

def verify_acquired_graph(graph, roots, children, *, after_build=False, observed_locks=None):
    """Prove complete populated recursion, origins, trees, bytes and owner aliases.

    roots and children map approved names/paths to actual checkout Paths. Only the
    SideStore resolver lock may differ after resolution; the unchanged primitives
    enforce the finite generated-output exceptions. No source overlay is admitted.
    """
    owners = validate_graph(graph, execution=True)
    require(set(roots) == set(OWNERS) and set(children) == set(graph['children']), 'acquired graph has missing/extra owners or children')
    observed_locks = {} if observed_locks is None else observed_locks
    require(set(observed_locks) <= {'SideStore'} and (after_build or not observed_locks), 'unapproved mutable owner lock')
    report = {'owners': {}, 'children': {}}
    for name, row in owners.items():
        root = Path(roots[name])
        require(not root.is_symlink(), 'linked owner root')
        prefix = next((path for path, owner in OWNER_CHILDREN.items() if owner == name), name)
        child_requirements(prefix, root, row['commit'], graph)
        proof = primitives.verify_checkout(root, row['commit'], owner=name, after_build=after_build, require_full_history=True, observed_lock=observed_locks.get(name))
        require(proof['tree'] == row['tree'], 'acquired owner tree differs')
        proof['origin'] = primitives.verify_origin(root, row['repository'], row['commit'])
        report['owners'][name] = proof
    for path, row in graph['children'].items():
        child = Path(children[path])
        owner, relative = path.split('/', 1)
        require(not child.is_symlink() and child.resolve(strict=True) == (Path(roots[owner]) / relative).resolve(strict=True), 'child is not in exact owner location')
        if path in OWNER_CHILDREN:
            require(child.resolve(strict=True) == Path(roots[OWNER_CHILDREN[path]]).resolve(strict=True), 'nested child and named owner disagree')
        child_requirements(path, child, row['commit'], graph)
        require(commit_identity(child, row['commit'])['tree'] == row['tree'], 'acquired child tree differs')
        proof = primitives.verify_checkout(child, row['commit'], owner=OWNER_CHILDREN.get(path, 'dependency'), after_build=after_build)
        proof['origin'] = primitives.verify_origin(child, row['repository'], row['commit'])
        report['children'][path] = proof
    return report

OWNERS=tuple(KNOWN)+tuple(NATIVE_TUPLES)
OWNER_KEYS={"repository","base","commit","tree","changes"}

def expected_children(owners):
    result=copy.deepcopy(STATIC_CHILDREN)
    for path,owner in OWNER_CHILDREN.items():
        row=owners[owner];result[path]={key:row[key] for key in ('repository','commit','tree')}
        result[path]['declared_repository']=row['repository']
    return result


def execution_draft_graph():
    owners={}
    for name,(commit,tree) in {**KNOWN,**NATIVE_TUPLES}.items():
        owners[name]={'repository':'https://github.com/NRG-Wardog/'+name+'.git','base':commit,'commit':commit,'tree':tree,'changes':{}}
    for name in ('SideSign','SideStore'):owners[name].update(commit=None,tree=None,changes=None)
    from integrity_source import pending_edges
    return {'kind':'PENDING_GENUINE_PHASE_A_AND_DESCENDANTS','owners':owners,'children':expected_children(owners),'lock_sha256':None,'sidesign_edges':pending_edges()}


def validate_graph(graph,execution=False):
    require(isinstance(graph,dict) and set(graph)=={'kind','owners','children','lock_sha256','sidesign_edges'},'exact executable graph schema required')
    draft=graph['kind']=='PENDING_GENUINE_PHASE_A_AND_DESCENDANTS'
    require(draft or graph['kind']=='BOUND_EXACT_SOURCE_GRAPH','unknown graph status')
    require(not execution or not draft,'complete actual graph required')
    owners=graph['owners'];require(set(owners)==set(OWNERS),'exact seven owner graph required')
    for name,row in owners.items():
        require(isinstance(row,dict) and set(row)==OWNER_KEYS and row['repository']=='https://github.com/NRG-Wardog/'+name+'.git','owner schema/repository differs')
        base,tree=({**KNOWN,**NATIVE_TUPLES})[name];require(row['base']==base,'owner baseline differs')
        if name in ('SideSign','SideStore'):
            if draft:
                require(row['commit'] is row['tree'] is row['changes'] is None,'pending graph cannot invent descendants');continue
            full_sha(row['commit']);full_sha(row['tree']);require(row['commit']!=base,'actual new descendant required')
            if name=='SideSign':
                require(isinstance(row['changes'],dict),'actual SideSign combined changes required')
            else:
                require(row['changes']=={'Dependencies/SideSign':{'before':{'mode':'160000','type':'commit','git_object':OLD_SIGN},'after':{'mode':'160000','type':'commit','git_object':owners['SideSign']['commit']}}},'exact SideStore gitlink delta required')
        else:require(row['commit']==base and row['tree']==tree and row['changes']=={},'known immutable source owner differs')
    require(graph['children']==expected_children(owners),'exact five recursive children required')
    if draft:require(graph['lock_sha256'] is None,'pending graph cannot invent lock')
    else:require(isinstance(graph['lock_sha256'],str) and re.fullmatch('[0-9a-f]{64}',graph['lock_sha256']) and graph['lock_sha256']!='0'*64,'actual lock digest required')
    from integrity_source import validate_edges
    validate_edges(graph['sidesign_edges'],owners['SideSign'],graph['lock_sha256'],draft=draft)
    return owners


def complete_graph(roots,bindings,observed,terminal):
    from descendant_contract import sidesign_child,sidesign_integrity_child,sidestore_capture_input
    from integrity_source import edge_record
    require(set(bindings)=={'SideSign_lock','SideSign','SideStore'},'exact resolver, source, and gitlink descendant bindings required')
    for row in bindings.values():require(set(row)=={'commit','tree'},'descendant tuple schema differs')
    lock=bindings['SideSign_lock'];sign=bindings['SideSign'];store=bindings['SideStore']
    first=sidesign_child(roots['SideSign'],lock['commit'],lock['tree'],observed,terminal)
    source=sidesign_integrity_child(roots['SideSign'],lock['commit'],sign['commit'],sign['tree'],observed,terminal)
    second=sidestore_capture_input(roots['SideStore'],store['commit'],store['tree'],sign['commit'])
    graph=execution_draft_graph();graph.update(kind='BOUND_EXACT_SOURCE_GRAPH',lock_sha256=sha(observed))
    graph['sidesign_edges']={'resolver_lock':edge_record(first),'integrity_source':edge_record(source)}
    graph['owners']['SideSign'].update(**sign,changes={**first['changes'],**source['changes']})
    graph['owners']['SideStore'].update(**store,changes=second['changes'])
    graph['children']=expected_children(graph['owners']);validate_graph(graph,execution=True)
    return graph


def verify_source_graph(roots,graph,observed,*,terminal_lock_bytes):
    validate_graph(graph,execution=True)
    require(set(roots)==set(OWNERS),'all actual source roots required')
    bindings={owner:{key:graph['owners'][owner][key] for key in ('commit','tree')} for owner in ('SideSign','SideStore')}
    bindings['SideSign_lock']={key:graph['sidesign_edges']['resolver_lock'][key] for key in ('commit','tree')}
    require(complete_graph(roots,bindings,observed,terminal_lock_bytes)==graph,'actual descendant graph differs')
    result={}
    for owner,row in graph['owners'].items():
        actual=snapshot(roots[owner],row['base'],row['commit'])
        require(actual=={'tree':row['tree'],'changes':row['changes']},'actual owner objects differ: '+owner)
        result[owner]={'commit':row['commit'],**actual}
    result['SideSign_edges']=copy.deepcopy(graph['sidesign_edges'])
    return result
