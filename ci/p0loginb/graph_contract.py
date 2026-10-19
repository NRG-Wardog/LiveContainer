"""New Phase B graph contract; no Phase A or historical gate is weakened.

Preparation records deliberately have a different kind and unresolved descendants.
Only authenticated Phase A lock bytes supplied by the caller may enter execution
proof. A structural validation is never evidence that an artifact was authenticated.
All Git deltas below are recomputed from objects, never from a caller's change list
or from dirty local preparation worktrees. The helpers perform no fetches or writes.
"""
from __future__ import annotations

import configparser
import copy
import hashlib
import json
from pathlib import Path
import re

import source_primitives as primitives

git, entries, require = primitives.git, primitives.entries, primitives.require
SOURCE_SEAL_SHA = '0caa11b1135abbf9c3905c601d100475b91f8d011237033ab47d1f96fad116e8'
SEAL_SHA = SOURCE_SEAL_SHA
PUBLICATION_SHA = '9c0da8c5be4eb6ebac50a006225e371ed9a1a3008e5e79dd4e30d71a906eba5a'
BASIS = 'p0-login-trace-phase-b-v1'
SOURCE_OWNERS = ('AnisetteKit', 'SideSign', 'SideStore', 'LiveContainer')
OWNERS = SOURCE_OWNERS + ('idevice', 'jktcp', 'minimuxer')
APP_LOCK = 'AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved'
SIGN_LINK = 'Dependencies/SideSign'
SOURCE_TUPLES = {
    'AnisetteKit': ('161435bcc0344e1a9853669455c1ca8d9dda2bf1', 'e6e9d4aac698de2a5219aaef02c9a417da45f4e9', '734664d759b9e99caa09089905e6a240b149548d'),
    'SideSign': ('c55f53ee6d3a65ab9b49d1528eb6c668fdde6c0e', '770b991b1dbc269ad19dd18b8b2e8252b665af9b', '2931630bc76fdbccd54a8829d078d54422e3483c'),
    'SideStore': ('59fa3b5cd8c9ea4a88716cbaaa08bacd9f22e218', '85bf45f65a9c2835c18d2c8e2e9c618177c95b54', '79d9ce079df8ca08f8d50d05afff50653f5493e6'),
    'LiveContainer': ('e22de6df412a0977f7430b2218960ca3ee9585d5', '545438e1f0a89fdef375f73273c5c9fc2735cbce', 'e8014dd771c25c4a05dc76ab0aa304a233642a83'),
}
NATIVE_TUPLES = {
    'idevice': ('803f9368e6b27a43d8a9f22dc0ec281c87883113', 'f5ac11668bae97e577e7c4fc098b5484df1c9af1'),
    'jktcp': ('32c0210f286b4fd16efe05be4f57167a9d94459b', 'e94eaefdcae5fe54a535186e36a0b2ebccc9bf13'),
    'minimuxer': ('efbcab05d7d636aa37c6bf6c7f364d122c5610f6', '30aa947645c5befb0c3210700095c8b039893d83'),
}
STATIC_CHILDREN = {
    'LiveContainer/OpenSSL': {'commit': '623c84da314e85363236507ca38a4bde65df21c3', 'tree': '21bc09387e7f91a46eb8bd26587ce1d052277801', 'declared_repository': 'https://github.com/krzyzanowskim/OpenSSL', 'repository': 'https://github.com/krzyzanowskim/OpenSSL'},
    'LiveContainer/litehook': {'commit': '8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55', 'tree': '62bc06a17a1c12d805aec1ada25910bfa9f89781', 'declared_repository': 'https://github.com/LiveContainer/litehook', 'repository': 'https://github.com/LiveContainerMirror/litehook.git'},
    'idevice/cpp/plist_ffi': {'commit': '66e6e6362b58bc361725c3e1b0a34af498aa2b3a', 'tree': '1dc97bcad12d41a13417ae05fbcdc4408c6df553', 'declared_repository': 'https://github.com/jkcoxson/plist_ffi.git', 'repository': 'https://github.com/jkcoxson/plist_ffi.git'},
}
OWNER_CHILDREN = {'SideStore/Dependencies/SideSign': 'SideSign', 'SideStore/Dependencies/minimuxer': 'minimuxer'}
GRAPH_KEYS = {'schema_version', 'kind', 'source_basis', 'source_seal_sha256', 'publication_sha256', 'owners', 'children', 'prior_artifact', 'final_sidesign', 'final_sidestore'}
OWNER_KEYS = {'repository', 'base', 'commit', 'tree', 'changes'}
PRIOR_KEYS = {'repository', 'run_id', 'run_attempt', 'host_commit', 'host_tree', 'artifact_id', 'artifact_sha256', 'artifact_size', 'lock_sha256', 'evidence_index_sha256'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    return json.loads(raw, object_pairs_hook=primitives.unique_pairs)


def full_sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value) and value != '0' * 40, 'actual full Git object ID required')
    return value


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) and value != '0' * 64, 'actual SHA256 required')
    return value


def relative_path(value):
    require(isinstance(value, str) and value and not value.startswith('/') and all(part not in ('', '.', '..', '.git') for part in value.split('/')) and '\\' not in value and '\0' not in value, 'unsafe graph path')
    return value


def repository(owner):
    return 'https://github.com/NRG-Wardog/' + owner + '.git'


def pinned_documents(seal_raw=None, publication_raw=None):
    """Accept only exact reviewed bytes, including the corrected final seal."""
    here = Path(__file__).resolve().parent
    if seal_raw is None:
        seal_raw = (here / 'source-seal.json').read_bytes()
    if publication_raw is None:
        publication_raw = (here / 'publication-trees.json').read_bytes()
    require(sha(seal_raw) == SOURCE_SEAL_SHA and sha(publication_raw) == PUBLICATION_SHA, 'source seal/publication bytes differ')
    seal, publication = parse(seal_raw), parse(publication_raw)
    require(set(seal['repositories']) == set(publication['owners']) == set(SOURCE_OWNERS), 'exact four published source owners required')
    require(publication['candidate_seal_sha256'] == SOURCE_SEAL_SHA, 'publication source seal mismatch')
    require(sum(len(row['changes']) for row in seal['repositories'].values()) == 33, 'exact 33-path source seal required')
    for owner in SOURCE_OWNERS:
        row, source = publication['owners'][owner], seal['repositories'][owner]
        require(tuple(row[key] for key in ('base', 'commit', 'tree')) == SOURCE_TUPLES[owner], 'publication owner tuple mismatch')
        paths = sorted([item['path'] for item in source['changes']] + (['Package.swift'] if owner == 'SideSign' else []))
        require(paths == row['changed_paths'] and set(paths) == set(row['files']), 'publication source path mismatch')
        for item in source['changes']:
            require(row['files'][item['path']] == item['sha256'], 'publication/seal source bytes differ')
    return seal, publication


def source_path_allowlists(seal_raw=None, publication_raw=None):
    """Derive paths from hash-pinned publication bytes; no hand-maintained widening."""
    _, publication = pinned_documents(seal_raw, publication_raw)
    return {name: list(publication['owners'][name]['changed_paths']) for name in SOURCE_OWNERS}


def test_source_allowlists(seal_raw=None, publication_raw=None):
    _, publication = pinned_documents(seal_raw, publication_raw)
    return {name: {path: value for path, value in publication['owners'][name]['files'].items() if path.startswith(('.ci/', 'tests/', 'Tests/'))} for name in SOURCE_OWNERS}


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


def snapshot(root, base, commit, *, single_parent=False):
    """Full tracked before/after entries, backed by trusted Git objects."""
    full_sha(base)
    identity = commit_identity(root, commit)
    commit_identity(root, base)
    if single_parent:
        require(identity['parents'] == [base], 'descendant must have exactly the specified single parent')
    else:
        git(root, 'merge-base', '--is-ancestor', base, commit)
    old, new = entries(root, base), entries(root, commit)

    def record(item):
        if item is None:
            return None
        mode, kind, oid = item
        result = {'mode': mode, 'type': kind, 'git_object': full_sha(oid)}
        if kind == 'blob':
            result['sha256'] = sha(git(root, 'cat-file', 'blob', oid))
        return result

    return {'tree': identity['tree'], 'changes': {path: {'before': record(old.get(path)), 'after': record(new.get(path))} for path in sorted(old.keys() | new.keys()) if old.get(path) != new.get(path)}}


def published_owner_rows(source_roots, seal_raw=None, publication_raw=None):
    _, publication = pinned_documents(seal_raw, publication_raw)
    result = {}
    for name in SOURCE_OWNERS:
        row = publication['owners'][name]
        actual = snapshot(source_roots[name], row['base'], row['commit'], single_parent=True)
        require(actual['tree'] == row['tree'] and set(actual['changes']) == set(row['changed_paths']), 'published source object delta differs: ' + name)
        for path, change in actual['changes'].items():
            after = change['after']
            require(after is not None and after['type'] == 'blob' and after['mode'] in ('100644', '100755') and after['sha256'] == row['files'][path], 'published source bytes/mode differ: ' + path)
        result[name] = {'repository': repository(name), 'base': row['base'], 'commit': row['commit'], **actual}
    for name, (commit, tree) in NATIVE_TUPLES.items():
        result[name] = {'repository': repository(name), 'base': commit, 'commit': commit, 'tree': tree, 'changes': {}}
    return result


def expected_children(owners):
    result = copy.deepcopy(STATIC_CHILDREN)
    for path, owner in OWNER_CHILDREN.items():
        row = owners[owner]
        result[path] = {key: row[key] for key in ('repository', 'commit', 'tree')}
        result[path]['declared_repository'] = row['repository']
    return result


def make_draft_graph(source_roots=None, seal_raw=None, publication_raw=None):
    """Local preparation only; never creates a commit or resolver lock."""
    if source_roots is None:
        tree_root = Path(__file__).resolve().parents[3] / 'trees'
        source_roots = {name: tree_root / name for name in SOURCE_OWNERS}
    owners = published_owner_rows(source_roots, seal_raw, publication_raw)
    for name in ('SideSign', 'SideStore'):
        owners[name] = {'repository': repository(name), 'base': SOURCE_TUPLES[name][1], 'commit': None, 'tree': None, 'changes': None}
    result = {'schema_version': 1, 'kind': 'phase-b-graph-draft', 'source_basis': BASIS, 'source_seal_sha256': SOURCE_SEAL_SHA, 'publication_sha256': PUBLICATION_SHA, 'owners': owners, 'children': expected_children(owners), 'prior_artifact': None, 'final_sidesign': None, 'final_sidestore': None}
    validate_graph(result)
    return result


def _validate_entry(value):
    if value is None:
        return
    require(isinstance(value, dict) and value.get('type') in ('blob', 'commit'), 'invalid tracked snapshot entry')
    require(set(value) == ({'mode', 'type', 'git_object', 'sha256'} if value['type'] == 'blob' else {'mode', 'type', 'git_object'}), 'unexpected snapshot fields')
    full_sha(value['git_object'])
    if value['type'] == 'blob':
        require(value['mode'] in ('100644', '100755', '120000'), 'invalid blob mode')
        digest(value['sha256'])
    else:
        require(value['mode'] == '160000', 'commit entry must be a gitlink')


def validate_graph(graph, execution=False):
    """Validate structure only. Execution still requires prior and object proofs."""
    require(isinstance(graph, dict) and set(graph) == GRAPH_KEYS, 'unexpected Phase B graph schema')
    require(type(graph['schema_version']) is int and graph['schema_version'] == 1 and graph['source_basis'] == BASIS, 'unsupported Phase B graph basis')
    require(graph['source_seal_sha256'] == SOURCE_SEAL_SHA and graph['publication_sha256'] == PUBLICATION_SHA, 'wrong final source seal/publication')
    require(graph['kind'] in ('phase-b-graph-draft', 'phase-b-graph-execution'), 'unknown graph kind')
    draft = graph['kind'] == 'phase-b-graph-draft'
    require(not execution or not draft, 'draft graph is not execution-ready')
    owners = graph['owners']
    require(isinstance(owners, dict) and set(owners) == set(OWNERS), 'exact seven owners required')
    _, publication = pinned_documents()
    for name, row in owners.items():
        require(isinstance(row, dict) and set(row) == OWNER_KEYS and row['repository'] == repository(name), 'unexpected owner fields/repository')
        expected_base = SOURCE_TUPLES[name][1 if name in ('SideSign', 'SideStore') else 0] if name in SOURCE_TUPLES else NATIVE_TUPLES[name][0]
        require(row['base'] == expected_base, 'wrong fixed owner base: ' + name)
        if draft and name in ('SideSign', 'SideStore'):
            require(row['commit'] is row['tree'] is row['changes'] is None, 'draft cannot invent descendant identity or changes')
            continue
        full_sha(row['commit']); full_sha(row['tree'])
        require(isinstance(row['changes'], dict), 'actual tracked snapshots required')
        for path, change in row['changes'].items():
            relative_path(path)
            require(isinstance(change, dict) and set(change) == {'before', 'after'} and change['before'] != change['after'], 'invalid tracked delta')
            _validate_entry(change['before']); _validate_entry(change['after'])
        if name in NATIVE_TUPLES:
            require((row['commit'], row['tree']) == NATIVE_TUPLES[name] and not row['changes'], 'unchanged native owner drift')
        elif name in ('AnisetteKit', 'LiveContainer'):
            require((row['commit'], row['tree']) == SOURCE_TUPLES[name][1:], 'unchanged published AK/LC drift')
            pub = publication['owners'][name]
            require(set(row['changes']) == set(pub['changed_paths']), 'published source allowlist drift')
            for path, change in row['changes'].items():
                after = change['after']
                require(after and after['type'] == 'blob' and after['mode'] in ('100644', '100755') and after['sha256'] == pub['files'][path], 'published source snapshot drift')
        elif name == 'SideSign':
            require(row['commit'] != row['base'] and set(row['changes']) == {'Package.resolved'}, 'SideSign must be a real lock-only descendant')
            change = row['changes']['Package.resolved']
            require(all(item and item['mode'] == '100644' and item['type'] == 'blob' for item in change.values()), 'SideSign lock mode/type differs')
        else:
            require(row['commit'] != row['base'] and set(row['changes']) == {SIGN_LINK}, 'SideStore must be a real gitlink-only descendant')
            before, after = row['changes'][SIGN_LINK]['before'], row['changes'][SIGN_LINK]['after']
            require(before == {'mode': '160000', 'type': 'commit', 'git_object': SOURCE_TUPLES['SideSign'][0]} and after == {'mode': '160000', 'type': 'commit', 'git_object': owners['SideSign']['commit']}, 'SideStore exact before/after SideSign gitlink differs')
    require(graph['children'] == expected_children(owners), 'exact recursive child URL/commit/tree graph differs')
    if draft:
        require(graph['prior_artifact'] is graph['final_sidesign'] is graph['final_sidestore'] is None, 'draft cannot supply unverified future evidence')
    else:
        prior = graph['prior_artifact']
        require(isinstance(prior, dict) and set(prior) == PRIOR_KEYS, 'exact authenticated prior Phase A identity tuple required before execution')
        require(prior['repository'] == 'NRG-Wardog/LiveContainer', 'wrong prior Phase A repository')
        for key in ('run_id', 'run_attempt', 'artifact_id', 'artifact_size'):
            require(type(prior[key]) is int and prior[key] > 0, 'real prior artifact/run integer required')
        for key in ('host_commit', 'host_tree'):
            full_sha(prior[key])
        for key in ('artifact_sha256', 'lock_sha256', 'evidence_index_sha256'):
            digest(prior[key])
        sign = owners['SideSign']
        require(graph['final_sidesign'] == {'commit': sign['commit'], 'tree': sign['tree'], 'lock_sha256': sign['changes']['Package.resolved']['after']['sha256']}, 'final SideSign tuple differs')
        require(prior['lock_sha256'] == graph['final_sidesign']['lock_sha256'], 'prior artifact lock is not final SideSign lock')
        store = owners['SideStore']
        require(graph['final_sidestore'] == {'commit': store['commit'], 'tree': store['tree']}, 'final SideStore app-input tuple differs')
    return owners


def check_lock(before, after, *, anisette_commit=SOURCE_TUPLES['AnisetteKit'][1]):
    old, new = parse(before), parse(after)
    require(isinstance(old, dict) and isinstance(new, dict), 'invalid lock object')
    for lock in (old, new):
        require(type(lock.get('version')) is int and isinstance(lock.get('pins'), list), 'unknown lock schema')
    op, np = primitives.pin_map(old), primitives.pin_map(new)
    require(op.keys() == np.keys() and 'anisettekit' in np, 'package identity set drift')
    for identity in op:
        if identity != 'anisettekit':
            require(op[identity] == np[identity], 'unrelated pin drift: ' + identity)
    require(np['anisettekit'] == {'identity': 'anisettekit', 'kind': 'remoteSourceControl', 'location': repository('AnisetteKit'), 'state': {'revision': full_sha(anisette_commit)}}, 'exact AnisetteKit pin required')
    require({k: v for k, v in old.items() if k not in ('pins', 'originHash')} == {k: v for k, v in new.items() if k not in ('pins', 'originHash')}, 'lock metadata/schema drift')
    digest(new.get('originHash'))
    return {'sha256': sha(after), 'originHash': new['originHash']}


def verify_lock_descendant(root, base, commit, observed, terminal, *, path='Package.resolved', expected_tree=None, anisette_commit=SOURCE_TUPLES['AnisetteKit'][1]):
    """Low-level proof also supports explicitly synthetic offline fixture commits."""
    require(isinstance(observed, bytes) and observed and isinstance(terminal, bytes) and observed == terminal, 'authenticated observed/frozen terminal lock bytes required')
    actual = snapshot(root, base, commit, single_parent=True)
    require(set(actual['changes']) == {path}, 'lock descendant changed an extra or wrong tracked path')
    change = actual['changes'][path]
    require(all(item and item['type'] == 'blob' and item['mode'] == '100644' for item in change.values()), 'lock descendant changed mode/type')
    require(expected_tree is None or actual['tree'] == full_sha(expected_tree), 'lock descendant tree differs')
    require(git(root, 'cat-file', 'blob', change['after']['git_object']) == observed, 'descendant lock is not authenticated observed bytes')
    before = git(root, 'cat-file', 'blob', change['before']['git_object'])
    check_lock(before, observed, anisette_commit=anisette_commit)
    return actual


def verify_gitlink_descendant(root, base, commit, old_child, new_child, *, expected_tree=None):
    actual = snapshot(root, base, commit, single_parent=True)
    require(set(actual['changes']) == {SIGN_LINK}, 'SideStore descendant changed an extra or wrong tracked path')
    require(actual['changes'][SIGN_LINK] == {'before': {'mode': '160000', 'type': 'commit', 'git_object': full_sha(old_child)}, 'after': {'mode': '160000', 'type': 'commit', 'git_object': full_sha(new_child)}}, 'SideStore exact gitlink mode/target differs')
    require(expected_tree is None or actual['tree'] == full_sha(expected_tree), 'SideStore descendant tree differs')
    return actual


def verify_source_graph(roots, graph, captured_lock_bytes, *, terminal_lock_bytes=None):
    """Call only after authenticating prior evidence; checks all seven object stores."""
    owners = validate_graph(graph, execution=True)
    require(set(roots) == set(OWNERS), 'exact seven acquired source roots required')
    published = published_owner_rows(roots)
    report = {}
    for name, row in owners.items():
        root = roots[name]
        if name == 'SideSign':
            actual = verify_lock_descendant(root, row['base'], row['commit'], captured_lock_bytes, terminal_lock_bytes, expected_tree=row['tree'])
        elif name == 'SideStore':
            actual = verify_gitlink_descendant(root, row['base'], row['commit'], SOURCE_TUPLES['SideSign'][0], owners['SideSign']['commit'], expected_tree=row['tree'])
        else:
            actual = snapshot(root, row['base'], row['commit'], single_parent=name in SOURCE_TUPLES)
            require(row == published[name], 'known owner is not exact published/native source')
        require(actual == {'tree': row['tree'], 'changes': row['changes']}, 'reported before/after snapshot does not match actual Git objects: ' + name)
        report[name] = {'commit': row['commit'], **actual}
    return report


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


def verify_final_app_lock_descendant(root, tested_commit, final_commit, observed, terminal, *, expected_tree=None):
    """Post-capture equivalence proof; does not claim final_commit was compiled."""
    actual = verify_lock_descendant(root, tested_commit, final_commit, observed, terminal, path=APP_LOCK, expected_tree=expected_tree)
    return {'tested_commit': tested_commit, 'final_commit': final_commit, 'final_tree': actual['tree'], 'lock_sha256': sha(observed), 'changes': actual['changes'], 'compiled_final_commit': False, 'equivalence': 'all tracked inputs identical except exact observed app lock'}
