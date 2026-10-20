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
    'LiveContainer': ('NRG-Wardog/LiveContainer', '47abe34894eb332a654d32f8e9322ce5eeac757a'),
    'SideStore': ('NRG-Wardog/SideStore', '24a07daf072b8b4cc8101a1275d368fd0968f10b'),
    'AnisetteKit': ('NRG-Wardog/AnisetteKit', '56f9aab3b2726821ed460e770c531e72a8233b8b'),
    'idevice': ('NRG-Wardog/idevice', '803f9368e6b27a43d8a9f22dc0ec281c87883113'),
    'jktcp': ('NRG-Wardog/jktcp', '32c0210f286b4fd16efe05be4f57167a9d94459b'),
    'SideStore/Dependencies/SideSign': ('NRG-Wardog/SideSign', '6e24a6f1389d102a64216b8c3d7344257baa28df'),
    'SideStore/Dependencies/minimuxer': ('NRG-Wardog/minimuxer', 'efbcab05d7d636aa37c6bf6c7f364d122c5610f6'),
    'LiveContainer/OpenSSL': ('krzyzanowskim/OpenSSL', '623c84da314e85363236507ca38a4bde65df21c3'),
    'LiveContainer/litehook': ('LiveContainerMirror/litehook', '8025e0c8ebdf5cdd1d2a4f45025813234bf9dc55'),
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
    for checkout in sorted(folder.iterdir()):
        if not checkout.is_dir():
            continue
        identity = checkout.name.lower()
        require(identity in expected, 'Unexpected resolved checkout: ' + identity)
        pin = expected[identity]
        require(git(checkout, 'rev-parse', 'HEAD') == pin['state']['revision'], 'Resolved revision differs: ' + identity)
        normalize = lambda value: value.removesuffix('.git').rstrip('/').lower()
        require(normalize(git(checkout, 'remote', 'get-url', 'origin')) == normalize(pin['location']),
                'Resolved remote differs: ' + identity)
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
