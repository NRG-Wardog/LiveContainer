"""Compile-only evidence recorder. Never grants production admission or runs app products."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
S = ROOT / 'sources'
E = ROOT / 'evidence'
TMP = Path(os.environ.get('RUNNER_TEMP', '/tmp'))
OWNERS = {
    'LiveContainer': ('NRG-Wardog/LiveContainer', '8193d7379c7cbdc420b02bc75d4e9e37c4823f17'),
    'SideStore': ('NRG-Wardog/SideStore', '825b3f888dfc7cd53e9f17039ffba75659f04ffc'),
    'AnisetteKit': ('NRG-Wardog/AnisetteKit', '26e101d72c2a4e0e70ee94342a775b20d6f7092b'),
    'idevice': ('NRG-Wardog/idevice', '774f02a6d29777c85400f4ba7fa69c12b4227fb3'),
    'jktcp': ('NRG-Wardog/jktcp', 'a46594f6af56b66b6d9342ed9f5ee6d1b7fb9cc9'),
    'SideStore/Dependencies/SideSign': ('NRG-Wardog/SideSign', '4e852649fada9851774a80e2639414d20f3efd72'),
    'SideStore/Dependencies/minimuxer': ('NRG-Wardog/minimuxer', '1d033920660c6f50b8f30c4c333f025867cd9e96'),
    'LiveContainer/OpenSSL': ('krzyzanowskim/OpenSSL', '623c84da314e85363236507ca38a4bde65df21c3'),
    'idevice/cpp/plist_ffi': ('jkcoxson/plist_ffi', '66e6e6362b58bc361725c3e1b0a34af498aa2b3a'),
    'LiveContainer/litehook': ('LiveContainerMirror/litehook', 'a7e9f599d7f0b3d77008ad62bf10cb10dab6eca9'),
}
LOCKS = {
    'SideStore': 'AltStore.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved',
    'SideStore/Dependencies/SideSign': 'Package.resolved',
}

def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def git(root, *args):
    return subprocess.check_output(['git', '--no-replace-objects', '-C', str(root), '-c',
                                   'core.hooksPath=/dev/null', *args]).decode().strip()


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(name, data):
    E.mkdir(exist_ok=True)
    (E / name).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def tracked(root):
    result = {}
    for row in git(root, 'ls-files', '--stage').splitlines():
        meta, name = row.split('\t', 1)
        mode, blob, stage = meta.split()
        require(stage == '0', 'Unmerged source: ' + name)
        p = root / name
        if mode == '160000':
            result[name] = {'gitlink': blob}
        elif p.is_symlink():
            result[name] = {'mode': mode, 'symlink': os.readlink(p)}
        else:
            require(p.is_file(), 'Missing compiler input: ' + str(p))
            result[name] = {'mode': mode, 'sha256': sha(p)}
    return result


def repos():
    roots = {name: S / name for name in OWNERS}
    for owner in ('LiveContainer', 'SideStore'):
        folder = TMP / ('native-' + owner) / 'SourcePackages/checkouts'
        if folder.exists():
            for p in sorted(folder.iterdir()):
                if p.is_dir():
                    roots['resolved/' + owner + '/' + p.name] = p
    return roots


def snapshot(label):
    result = {}
    for name, root in repos().items():
        head = git(root, 'rev-parse', 'HEAD')
        if name in OWNERS:
            require(head == OWNERS[name][1], 'Owner pin drift: ' + name)
        result[name] = {'commit': head, 'tree': git(root, 'rev-parse', 'HEAD^{tree}'),
                        'origin': git(root, 'remote', 'get-url', 'origin'), 'files': tracked(root)}
    # Include the staged, generated local binary/header inputs, not only tracked source.
    local = S / 'SideStore/Dependencies/minimuxer/DeviceGateway/LocalBinary/IDevice.xcframework'
    result['local-framework'] = {p.relative_to(local).as_posix(): sha(p)
                                 for p in sorted(local.rglob('*')) if p.is_file()}
    for owner in ('LiveContainer', 'SideStore'):
        folder = TMP / ('native-' + owner) / 'SourcePackages/artifacts'
        result['binary-artifacts/' + owner] = {p.relative_to(folder).as_posix(): sha(p)
            for p in sorted(folder.rglob('*')) if p.is_file()}
    write(label + '.json', result)


def acquire():
    # Retain requested identity even when cloning or closure validation fails.
    write('requested-graph.json', OWNERS)
    # Refuse incomplete reviewed pins before any acquisition/network operation.
    require(all(re.fullmatch(r'[0-9a-f]{40}', commit) for _, commit in OWNERS.values()),
            'Reviewed graph has missing or invalid exact commit pins')
    for name, (repo, commit) in OWNERS.items():
        root = S / name
        require(not root.exists() or (root.is_dir() and not list(root.iterdir())), 'Nonfresh checkout: ' + name)
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-checkout',
                        'https://github.com/' + repo + '.git', str(root)], check=True)
        git(root, 'fetch', '--no-tags', '--no-recurse-submodules', 'origin', commit)
        git(root, 'checkout', '--detach', commit)
        require(git(root, 'rev-parse', 'HEAD') == commit, 'Acquisition identity mismatch')
    # No recursive submodule discovery or branch substitution. Enforce complete gitlink closure.
    for name in OWNERS:
        for row in git(S / name, 'ls-files', '--stage').splitlines():
            meta, child = row.split('\t', 1)
            mode, oid, stage = meta.split()
            if mode == '160000':
                key = name + '/' + child
                require(key in OWNERS and OWNERS[key][1] == oid, 'Unexpected child gitlink: ' + key)
    project = (S / 'LiveContainer/LiveContainer.xcodeproj/project.pbxproj').read_text()
    require('XCRemoteSwiftPackageReference' not in project and
            re.search(r'packageReferences\s*=\s*\(\s*\);', project),
            'LiveContainer unexpectedly has remote package references')
    for owner, path in LOCKS.items():
        data = (S / owner / path).read_bytes()
        (E / (owner.replace('/', '_') + '.Package.resolved.before')).write_bytes(data)
    write('requested-graph.json', OWNERS)


def seal_resolution():
    before_raw = (E / 'SideStore.Package.resolved.before').read_bytes()
    path = S / 'SideStore' / LOCKS['SideStore']
    after_raw = path.read_bytes()
    (E / 'SideStore.Package.resolved.observed').write_bytes(after_raw)
    before, after = json.loads(before_raw), json.loads(after_raw)
    require(set(before) == set(after), 'Resolver changed top-level app-lock schema')
    for key in set(before) - {'pins', 'originHash'}:
        require(before[key] == after[key], 'Resolver changed app-lock field: ' + key)
    index = lambda value: {pin['identity']: pin for pin in value['pins']}
    old, new = index(before), index(after)
    require(len(old) == len(before['pins']) and len(new) == len(after['pins']), 'Duplicate package identities')
    require(set(old) == set(new), 'Resolver changed package identity closure')
    require(old['anisettekit']['state'] == {'revision': 'e6e9d4aac698de2a5219aaef02c9a417da45f4e9'},
            'Unexpected starting AK lock')
    expected = json.loads(json.dumps(old))
    expected['anisettekit']['state'] = {'revision': OWNERS['AnisetteKit'][1]}
    require(new == expected, 'Resolver changed pins beyond the exact AK revision transition')
    if 'originHash' in after:
        require(isinstance(after['originHash'], str) and re.fullmatch('[0-9a-f]{64}', after['originHash']),
                'Invalid observed resolver originHash')
    (E / 'SideStore.Package.resolved.after').write_bytes(after_raw)
    write('app-lock-transition.json', {'status': 'OBSERVED_RESOLVER_TRANSITION_REQUIRES_REVIEW',
          'source_commit': OWNERS['SideStore'][1], 'working_checkout_has_uncommitted_app_lock': True,
          'before_sha256': hashlib.sha256(before_raw).hexdigest(),
          'after_sha256': hashlib.sha256(after_raw).hexdigest(),
          'before_originHash': before.get('originHash'), 'after_originHash': after.get('originHash'),
          'only_pin_revision_changed': 'anisettekit', 'new_source_commit_published': False})


def https_origin(value):
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.netloc.lower() == 'github.com' and
            not parsed.query and not parsed.fragment and
            re.fullmatch(r'/[^/]+/[^/]+/?', parsed.path), 'Unexpected upstream origin format')
    return 'https://github.com' + parsed.path.rstrip('/').removesuffix('.git').lower()


def contained_directory(path, root):
    path, root = Path(path), Path(root).resolve(strict=True)
    require(path.is_absolute() and '..' not in path.parts, 'Noncanonical local repository path')
    # Reject symlink routing below the trusted canonical root before invoking Git.
    require(path.is_relative_to(root), 'Local repository path escapes resolver root')
    current = root
    for component in path.relative_to(root).parts:
        current = current / component
        require(not current.is_symlink(), 'Symlink in local repository path')
    require(path.is_dir() and path.resolve(strict=True).is_relative_to(root), 'Missing/outside repository')
    return path.resolve(strict=True)


def verify_origin_chain(checkout, cache_root, expected_url, revision, rows=None):
    from urllib.parse import urlsplit, unquote
    expected = https_origin(expected_url)
    checkout = Path(checkout)
    # Caller has checked checkout ancestry against canonical RUNNER_TEMP. Validate
    # its sibling cache before resolving it, so a cache symlink cannot redefine trust.
    require(Path(cache_root) == checkout.parent.parent / 'repositories', 'Unexpected cache root')
    cache_root = contained_directory(cache_root, checkout.parent.parent)
    current = contained_directory(checkout, checkout.parent)
    checkout_tree = git(current, 'rev-parse', revision + '^{tree}')
    visited = set()
    rows = [] if rows is None else rows
    for _ in range(4):
        require(current not in visited, 'Origin chain cycle')
        visited.add(current)
        gitdir = Path(git(current, 'rev-parse', '--absolute-git-dir'))
        contained_directory(gitdir, current)
        require(git(current, 'cat-file', '-t', revision) == 'commit' and
                git(current, 'rev-parse', revision + '^{tree}') == checkout_tree,
                'Origin cache commit/tree differs')
        origins = git(current, 'remote', 'get-url', '--all', 'origin').splitlines()
        require(len(origins) == 1 and 0 < len(origins[0]) < 4096, 'Ambiguous/missing origin')
        origin = origins[0]
        parsed = urlsplit(origin)
        require(not parsed.username and not parsed.password, 'Credential-bearing origin rejected')
        rows.append({'repository': str(current), 'origin': origin, 'tree': checkout_tree})
        if parsed.scheme == 'https':
            require(https_origin(origin) == expected, 'Resolved upstream differs from exact lock')
            return rows
        if parsed.scheme == 'file':
            require(not parsed.netloc and not parsed.query and not parsed.fragment,
                    'Nonlocal file URL rejected')
            target = Path(unquote(parsed.path))
        else:
            require(not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment,
                    'Unsupported local origin')
            target = Path(origin)
        current = contained_directory(target, cache_root)
        require(current != cache_root, 'Cache root is not a package repository')
    raise RuntimeError('Origin chain exceeds four repositories')


def verify_workspace_row(document, identity, checkout, pin):
    require(document.get('version') in (6, 7), 'Unsupported resolver state version')
    matches = [row for row in document['object']['dependencies']
               if row.get('packageRef', {}).get('identity') == identity]
    require(len(matches) == 1, 'Missing/duplicate resolver package row')
    row = matches[0]
    ref, state = row['packageRef'], row['state']
    require(ref.get('kind') == 'remoteSourceControl' and
            https_origin(ref['location']) == https_origin(pin['location']) and
            state.get('name') == 'sourceControlCheckout' and
            state.get('checkoutState', {}).get('revision') == pin['state']['revision'] and
            row.get('subpath') == checkout.name and row.get('basedOn') is None,
            'Resolver state does not bind exact lock and checkout')


def capture_resolution_inputs(folder):
    # Retain observations before any origin assertion; failure is not success evidence.
    from urllib.parse import urlsplit
    state = folder.parent / 'workspace-state.json'
    raw = state.read_bytes() if state.is_file() and not state.is_symlink() else None
    if raw is not None:
        (E / 'SideStore-workspace-state.json').write_bytes(raw)
    observations = {}
    for checkout in sorted(folder.iterdir()):
        if not checkout.is_dir():
            continue
        try:
            contained_directory(checkout, folder)
            origin = git(checkout, 'remote', 'get-url', '--all', 'origin')
            parsed = urlsplit(origin)
            observations[checkout.name] = {'origin': '[credential-bearing origin rejected]' if
                parsed.username or parsed.password else origin,
                'commit': git(checkout, 'rev-parse', 'HEAD')}
        except (RuntimeError, subprocess.CalledProcessError) as error:
            observations[checkout.name] = {'observation_error': type(error).__name__}
    write('resolved-origin-observations.json', observations)
    require(raw is not None, 'Missing/linked resolver state')
    return json.loads(raw)


def verify_resolved():
    lc_checkouts = TMP / 'native-LiveContainer/SourcePackages/checkouts'
    require(not lc_checkouts.exists() or not any(lc_checkouts.iterdir()),
            'Unexpected LiveContainer resolved checkout')
    for owner, path in LOCKS.items():
        current = (S / owner / path).read_bytes()
        require(current == (E / (owner.replace('/', '_') + '.Package.resolved.' + ('after' if owner == 'SideStore' else 'before'))).read_bytes(),
                'Frozen resolver lock changed: ' + owner)
    app_lock = json.loads((S / 'SideStore' / LOCKS['SideStore']).read_text())
    expected = {pin['identity'].lower(): pin for pin in app_lock['pins']}
    observed = {}
    folder = TMP / 'native-SideStore/SourcePackages/checkouts'
    contained_directory(folder, TMP.resolve(strict=True))
    state_document = capture_resolution_inputs(folder)
    origin_chains = {}
    for checkout in sorted(folder.iterdir()):
        if not checkout.is_dir():
            continue
        contained_directory(checkout, folder)
        identity = checkout.name.lower()
        require(identity in expected, 'Unexpected resolved checkout: ' + identity)
        pin = expected[identity]
        require(git(checkout, 'rev-parse', 'HEAD') == pin['state']['revision'], 'Resolved revision differs: ' + identity)
        verify_workspace_row(state_document, identity, checkout, pin)
        chain_observations = []
        try:
            origin_chains[identity] = verify_origin_chain(checkout, folder.parent / 'repositories',
                                                        pin['location'], pin['state']['revision'], chain_observations)
        except Exception as error:
            write('resolved-origin-chain-failure.json', {'identity': identity, 'error': str(error),
                                                       'observed_chain': chain_observations, 'completed_chains': origin_chains})
            raise
        write('resolved-origin-chains.json', origin_chains)
        require(not git(checkout, 'status', '--porcelain', '--untracked-files=no'), 'Dirty resolved source: ' + identity)
        observed[identity] = pin['state']['revision']
    require(set(observed) == set(expected), 'App lock/checkouts closure differs')
    write('actual-resolved-pins.json', observed)
    # Verify the actually compiled AK checkout, not merely a separately acquired matching repository.
    ak = TMP / 'native-SideStore/SourcePackages/checkouts/AnisetteKit'
    require(ak.is_dir(), 'Missing actual app-resolved AnisetteKit')
    require(git(ak, 'rev-parse', 'HEAD') == OWNERS['AnisetteKit'][1], 'Resolved AK revision mismatch')
    require(tracked(ak) == tracked(S / 'AnisetteKit'), 'Resolved AK input bytes mismatch')
    for owner in ('LiveContainer', 'SideStore'):
        state = TMP / ('native-' + owner) / 'SourcePackages/workspace-state.json'
        if state.exists():
            # Retain actual resolver provenance; review remains required, never infer native readiness.
            (E / (owner + '-workspace-state.json')).write_bytes(state.read_bytes())
    write('resolution-check.json', {'frozen_app_lock_unchanged': True, 'sidesign_committed_lock_unchanged': True,
          'actual_anisette_commit': git(ak, 'rev-parse', 'HEAD'),
          'actual_anisette_tree': git(ak, 'rev-parse', 'HEAD^{tree}')})


def receipt():
    outputs = {}
    for owner in ('LiveContainer', 'SideStore'):
        product = TMP / ('native-' + owner) / 'Build/Products/Release-iphoneos' / (owner + '.app')
        require((product / owner).is_file(), 'Expected native executable absent: ' + owner)
        require((E / (owner + '-build.exit-code.txt')).read_text().strip() == '0', 'Build did not pass')
        outputs[owner] = {p.relative_to(product).as_posix(): sha(p)
                          for p in sorted(product.rglob('*')) if p.is_file()}
    write('product-hashes.json', outputs)
    write('receipt.json', {'schema_version': 1, 'status': 'COMPILE_ONLY_PASS_REQUIRES_REVIEW',
          'workflow_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
          'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
          'run_url': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
          'requested_graph': OWNERS, 'native_builds': {'LiveContainer': 'PASS_UNSIGNED_RELEASE_IPHONEOS',
          'SideStore': 'PASS_UNSIGNED_RELEASE_IPHONEOS'}, 'compiler_input_bytes_unchanged': True,
          'working_sidestore_app_lock_differs_from_git': True, 'final_lock_only_child_compiled': False,
          'production_admission': False, 'combined_ipa_packaged': False, 'physical_device_execution': False,
          'authentication_executed': False, 'guest_binary_executed': False,
          'tests_executed': False, 'independent_review': 'pending',
          'evidence_sha256': {p.name: sha(p) for p in sorted(E.iterdir()) if p.is_file() and p.name != 'receipt.json'}})


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'snapshot':
        snapshot(sys.argv[2])
    elif action == 'acquire':
        acquire()
    elif action == 'seal-resolution':
        seal_resolution()
    elif action == 'verify-resolved':
        verify_resolved()
    elif action == 'receipt':
        receipt()
    else:
        raise ValueError('Unknown action')
