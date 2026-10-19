"""Read-only Cargo/OpenSSL provenance checks for the exact Phase B source graph.

These helpers never resolve, compile, install or rewrite a lock. The caller owns
bounded commands and must retain their original stdout/stderr and command receipt.
Source tuples come from graph_contract; metadata must come from the real Cargo
command, both before and after building. Unit-test metadata is never evidence.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tomllib

from graph_contract import NATIVE_TUPLES
from source_primitives import entries, git, require, unique_pairs, verify_checkout

REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'
LOCAL_MANIFESTS = {
    'idevice-ffi': ('idevice', 'ffi/Cargo.toml', '0.1.0'),
    'idevice': ('idevice', 'idevice/Cargo.toml', '0.1.65'),
    'idevice-tools': ('idevice', 'tools/Cargo.toml', '0.1.65'),
    'idevice-test-harness': ('idevice', 'tests/Cargo.toml', '0.1.0'),
    'jktcp': ('jktcp', 'Cargo.toml', '0.1.6'),
}
# Retrieved read-only from the exact reviewed commits, not from a resolver run.
SOURCE_BLOBS = {
    'idevice': {
        'Cargo.toml': 'c2e80fb0f22f8f6f9faac1fcc6a86d73029dd1a9',
        'Cargo.lock': '2947e86979e8a017c4fcd0af28dffd3466d7cf96',
        'ffi/Cargo.toml': '8a522cebd04cfbdfc84a6c246df940d2c9fc5349',
        'idevice/Cargo.toml': 'bb3da835f6c68ebe31dc89666e609c4b74191094',
        'idevice/Cargo.lock': '352a0e2f71023a2b186effa50b2030d39438bd31',
        'tests/Cargo.toml': '218a034adae9ebe147febfd87e4611d6788f580d',
        'tools/Cargo.toml': '5cce187f7632c5c9a191f6712acf13c8bfe31891',
        'ffi/build.rs': '7eb82105def61b7fbf79675a11421e29e4adda3a',
        'ffi/plist.h': '7dc30692ac160cd142becf4b785a06074300eea0',
        'swift/include/module.modulemap': 'f5bd1109d4fd9343ef27b441965753064cddf8f6',
    },
    'jktcp': {
        'Cargo.toml': '216dba717bc397beb603a96ccd562b6912acbcc7',
        'Cargo.lock': 'e4c1525799b502e9409ea27aa5c6204ae710bb33',
    },
}
RUST_ENV = {'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_INSTALL_ROOT', 'RUSTUP_HOME', 'RUSTUP_TOOLCHAIN'}
REGISTRY_DIAGNOSTIC_MAX_FILES = 10000
REGISTRY_DIAGNOSTIC_MAX_PATH_BYTES = 1024
REGISTRY_DIAGNOSTIC_MAX_BYTES = 8 * 1024 * 1024
README_ALIAS_PACKAGE = ('nskeyedarchiver_converter', '0.1.3')
README_ALIAS_ARCHIVE = '36c53158d1bf37bbbdd165f5220fda8bb5757c89eb700107992152c64c6cad7e'
README_ALIAS_ARCHIVE_BYTES = 13901
README_ALIAS_CONTENT = '8f9d7995df53d0b3c75999fb5b253930513d761808f54f1b118c5c02cfee6f31'
README_ALIAS_CONTENT_BYTES = 2398
README_ALIAS_PATHS = ('README.MD', 'README.md')
PLIST_PACKAGE = ('plist_ffi', '0.1.6')
PLIST_PACKAGE_ID = REGISTRY + '#plist_ffi@0.1.6'
PLIST_ARCHIVE = '35ed070b06d9f2fdd7e816ef784fb07b09672f2acf37527f810dbedf450b7769'
PLIST_ARCHIVE_BYTES = 92451
PLIST_BUILD_SCRIPT = '3f113baab2c64102e29141a0e66743151aeaaee6404d64971bb5f664853b0819'
PLIST_SOURCE_INVENTORY = '05ab62152e8a519f8304838df72c6dca760804b212b8bda6b478ecad92c20f0d'
PLIST_GENERATED_SHA256 = '869710f970cde3b6dcb9f68d8c78b42d6717ade0a051e634fb6e12c8365d42f5'
PLIST_GENERATED_MAX_BYTES = 256 * 1024
PLIST_SNAPSHOT_KEY = 'plist_ffi/plist.h'


class RegistrySourceMismatch(ValueError):
    """The unchanged equality rejection, with bounded hash-only evidence."""
    def __init__(self, diagnostic):
        super().__init__('registry extracted source changed from locked archive')
        self.diagnostic = diagnostic


def inventory_digest(inventory):
    digest = hashlib.sha256()
    for part in json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True).iterencode(inventory):
        digest.update(part.encode('ascii'))
    return digest.hexdigest()


def registry_mismatch_diagnostic(package, checksum, archive_size, expected, actual, generated, alias_probe=None, generated_checkpoint=None):
    """Complete first-mismatch inventories or a fixed bound failure; no bytes.

    These are public dependency-relative names and SHA256 values, never source
    contents or host/authentication data. A bound failure contains no path list.
    Neither report changes which source inputs can pass the gate.
    """
    missing = set(expected) - set(actual)
    extra = set(actual) - set(expected)
    changed = {p for p in expected.keys() & actual.keys() if expected[p] != actual[p]}
    counts = {'expected': len(expected), 'actual': len(actual), 'generated': len(generated),
              'missing': len(missing), 'extra': len(extra), 'changed': len(changed)}
    result = {'schema_version': 1, 'status': 'REGISTRY_SOURCE_MISMATCH',
              'source_equality_passed': False, 'complete': False,
              'package': None, 'archive_sha256': checksum, 'archive_bytes': archive_size,
              'counts': counts, 'omitted_counts': dict(counts),
              'inventory_sha256': {'expected': inventory_digest(expected), 'actual': inventory_digest(actual),
                                   'cargo_generated': inventory_digest(generated)},
              'limits': {'files_per_inventory': REGISTRY_DIAGNOSTIC_MAX_FILES,
                         'path_utf8_bytes': REGISTRY_DIAGNOSTIC_MAX_PATH_BYTES,
                         'serialized_bytes': REGISTRY_DIAGNOSTIC_MAX_BYTES}}
    if alias_probe is not None:
        result['documentation_alias_probe'] = alias_probe
    if generated_checkpoint is not None:
        result['generated_output_checkpoint'] = generated_checkpoint
    identity = {key: package[key] for key in ('name', 'version')}
    try:
        identity_valid = all(isinstance(v, str) and len(v.encode('utf-8')) <= 128 for v in identity.values())
    except UnicodeError:
        identity_valid = False
    if not identity_valid:
        result['bound_failure'] = 'PACKAGE_IDENTITY_LIMIT'
        return result
    result['package'] = identity
    if any(len(i) > REGISTRY_DIAGNOSTIC_MAX_FILES for i in (expected, actual, generated)):
        result['bound_failure'] = 'FILE_COUNT_LIMIT'
        return result
    try:
        paths_valid = all(len(p.encode('utf-8')) <= REGISTRY_DIAGNOSTIC_MAX_PATH_BYTES for i in (expected, actual, generated) for p in i)
    except UnicodeError:
        paths_valid = False
    if not paths_valid:
        result['bound_failure'] = 'PATH_LENGTH_LIMIT'
        return result
    complete = dict(result, complete=True, omitted_counts={key: 0 for key in counts},
                    expected_files=expected, actual_files=actual, cargo_generated_files=generated,
                    missing={p: expected[p] for p in sorted(missing)},
                    extra={p: actual[p] for p in sorted(extra)},
                    changed={p: {'expected_sha256': expected[p], 'actual_sha256': actual[p]} for p in sorted(changed)})
    # Match the existing evidence writer's exact JSON serialization, including newline.
    if len((json.dumps(complete, indent=2, sort_keys=True) + '\n').encode('utf-8')) > REGISTRY_DIAGNOSTIC_MAX_BYTES:
        result['bound_failure'] = 'SERIALIZED_SIZE_LIMIT'
        return result
    return complete


def registry_documentation_alias(package, checksum, archive_size, root, expected, actual):
    """One checksum-bound documentation pair; no general case normalization.

    The archived names and enumerated names remain separate inventories. Only
    the real filesystem can prove that the absent directory-entry spelling is
    an alias for the surviving ordinary file. Missing files on a case-sensitive
    volume, links, distinct hardlink entries, or any unrelated delta reject.
    """
    if ((package['name'], package['version']) != README_ALIAS_PACKAGE
            or checksum != README_ALIAS_ARCHIVE or archive_size != README_ALIAS_ARCHIVE_BYTES
            or any(expected.get(p) != README_ALIAS_CONTENT for p in README_ALIAS_PATHS)
            or set(expected) - set(actual) != {'README.MD'}
            or actual != {p: h for p, h in expected.items() if p != 'README.MD'}):
        return None
    report = {'rule': 'PINNED_NSKEYEDARCHIVER_README_ALIAS_V1', 'verified': False,
              'archive_paths': list(README_ALIAS_PATHS), 'enumerated_path': 'README.md',
              'content_sha256': README_ALIAS_CONTENT, 'content_bytes': README_ALIAS_CONTENT_BYTES}
    def reject(reason):
        return dict(report, failure=reason)
    def identity(s):
        return (s.st_dev, s.st_ino, s.st_size)
    def stable(s):
        return identity(s) + (s.st_mode, s.st_mtime_ns, s.st_ctime_ns)
    try:
        paths = [ordinary(root / p) for p in README_ALIAS_PATHS]
        if sorted(p.name for p in root.iterdir() if p.name in README_ALIAS_PATHS) != ['README.md']:
            return reject('DIRECTORY_ENTRIES_DIFFER')
        before = [p.lstat() for p in paths]
        if not all(stat.S_ISREG(s.st_mode) and s.st_ino > 0 and s.st_size == README_ALIAS_CONTENT_BYTES for s in before):
            return reject('NOT_ORDINARY_PINNED_FILE')
        if identity(before[0]) != identity(before[1]) or not paths[0].samefile(paths[1]):
            return reject('FILE_IDENTITY_DIFFERS')
        if any(sha(p.read_bytes()) != README_ALIAS_CONTENT for p in paths):
            return reject('CONTENT_DIFFERS')
        after = [p.lstat() for p in paths]
        if [stable(s) for s in before] != [stable(s) for s in after]:
            return reject('FILE_CHANGED_DURING_PROBE')
        if sorted(p.name for p in root.iterdir() if p.name in README_ALIAS_PATHS) != ['README.md']:
            return reject('DIRECTORY_ENTRIES_DIFFER')
    except (OSError, ValueError):
        return reject('FILESYSTEM_PROBE_FAILED')
    return dict(report, verified=True, samefile=True, ordinary_nonsymlink=True,
                file_identity={'device': before[0].st_dev, 'inode': before[0].st_ino, 'bytes': before[0].st_size},
                archive_inventory_sha256=inventory_digest(expected), actual_inventory_sha256=inventory_digest(actual))


def plist_generated_state(present):
    return {'rule': 'PINNED_PLIST_FFI_GENERATED_HEADER_V1', 'present': present,
            'path': 'plist.h', 'expected_sha256': PLIST_GENERATED_SHA256,
            'archive_sha256': PLIST_ARCHIVE, 'producer_build_script_sha256': PLIST_BUILD_SCRIPT,
            'role': 'generated native compilation input; distinct from idevice/ffi/plist.h'}


def generated_header_snapshot(path):
    """One bounded ordinary-file byte snapshot for hash and evidence retention."""
    def identity(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_mtime_ns, s.st_ctime_ns)
    try:
        path = ordinary(path)
        before = path.lstat()
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= PLIST_GENERATED_MAX_BYTES,
                'generated header size/type differs')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            opened = os.fstat(descriptor)
            require(stat.S_ISREG(opened.st_mode) and 0 < opened.st_size <= PLIST_GENERATED_MAX_BYTES,
                    'opened generated header size/type differs')
            require(identity(opened) == identity(before), 'generated header substituted before read')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                raw = stream.read(PLIST_GENERATED_MAX_BYTES + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        require(len(raw) == before.st_size and identity(after) == identity(before) == identity(path.lstat()),
                'generated header changed during read')
    except (OSError, ValueError):
        raise RegistrySourceMismatch({'schema_version': 1, 'status': 'REGISTRY_GENERATED_ARTIFACT_REJECTED',
            'source_equality_passed': False, 'package': {'name': PLIST_PACKAGE[0], 'version': PLIST_PACKAGE[1]},
            'path': 'plist.h', 'reason': 'BOUNDED_ORDINARY_STABLE_SNAPSHOT_REQUIRED',
            'maximum_bytes': PLIST_GENERATED_MAX_BYTES}) from None
    return raw, {'bytes': len(raw), 'sha256': sha(raw),
                 'file_identity': {'device': before.st_dev, 'inode': before.st_ino}}


def verify_generated_build_receipt(command_raw, settlement_raw, exit_raw, expected_argv, expected_cwd):
    command, settled = parse(command_raw), parse(settlement_raw)
    require(command.get('argv') == list(map(str, expected_argv)) and command.get('cwd') == str(expected_cwd),
            'generated-header producer command/cwd differs')
    require(exit_raw == b'0\n' and all(type(settled.get(k)) is int and settled[k] == 0
                                     for k in ('returncode', 'terminationReturncode')),
            'successful generated-header producer required')
    group = settled.get('ownedProcessGroup', {})
    require(all(group.get(k) is True for k in ('leaderReaped', 'pipesJoined', 'quiescent', 'reapedBeforeSignals'))
            and group.get('signals') == [] and group.get('errors') == []
            and type(group.get('pgid')) is int and group['pgid'] > 0,
            'settled signal-free generated-header producer required')
    return {'label': 'idevice-build', 'command_sha256': sha(command_raw),
            'settlement_sha256': sha(settlement_raw), 'exit_code_sha256': sha(exit_raw),
            'pgid': group['pgid'], 'succeeded_and_quiescent': True}


def verify_generated_transition(before, after, build_execution):
    """One absent→present output transition; all immutable provenance is equal."""
    require(isinstance(build_execution, dict) and set(build_execution) == {
        'label','command_sha256','settlement_sha256','exit_code_sha256','pgid','succeeded_and_quiescent'}
        and build_execution['label'] == 'idevice-build' and build_execution['succeeded_and_quiescent'] is True
        and type(build_execution['pgid']) is int and build_execution['pgid'] > 0
        and all(re.fullmatch('[0-9a-f]{64}', build_execution[k]) for k in ('command_sha256','settlement_sha256','exit_code_sha256')),
        'actual owned producer receipt binding required')
    old = before['registry_packages'][PLIST_PACKAGE_ID]
    new = after['registry_packages'][PLIST_PACKAGE_ID]
    require(old.get('generated_output_state') == plist_generated_state(False)
            and 'plist.h' not in old['source_files'] and 'generated_artifacts' not in old and 'observed_files' not in old,
            'retained before proof must establish generated-header absence')
    require(new.get('generated_output_state') == plist_generated_state(True)
            and set(new.get('generated_artifacts', {})) == {'plist.h'}, 'exact generated-header after state required')
    artifact = new['generated_artifacts']['plist.h']
    require(set(artifact) == {'bytes','sha256','file_identity'} and artifact['sha256'] == PLIST_GENERATED_SHA256
            and type(artifact['bytes']) is int and 0 < artifact['bytes'] <= PLIST_GENERATED_MAX_BYTES
            and set(artifact['file_identity']) == {'device','inode'}
            and all(type(v) is int and v >= 0 for v in artifact['file_identity'].values())
            and artifact['file_identity']['inode'] > 0, 'generated header identity/hash differs')
    expected_package = dict(old, generated_output_state=plist_generated_state(True),
                            generated_artifacts={'plist.h': artifact},
                            observed_files={**old['source_files'], 'plist.h': PLIST_GENERATED_SHA256})
    expected_after = dict(before, registry_packages={**before['registry_packages'], PLIST_PACKAGE_ID: expected_package})
    require(after == expected_after, 'Cargo immutable source/provenance changed across generated-output transition')
    return {'schema_version': 1, 'status': 'EXACT_GENERATED_HEADER_TRANSITION_VERIFIED',
            'producer_package': PLIST_PACKAGE_ID, 'producer_execution': build_execution,
            'before': plist_generated_state(False), 'after': plist_generated_state(True),
            'immutable_source_inventory_sha256': inventory_digest(old['source_files']),
            'observed_after_inventory_sha256': inventory_digest(new['observed_files']),
            'generated_artifact': artifact}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs) if isinstance(raw, (str, bytes)) else raw


def ordinary(path, *, directory=False, missing=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute unambiguous Cargo path required')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'linked Cargo path: ' + str(part))
    if not missing:
        require(path.is_dir() if directory else path.is_file(), 'ordinary Cargo path absent: ' + str(path))
    return path


def validate_cargo_home(home, target, install_root, *, before_setup=False, cwd=None, env=None, rustup_home=None):
    """Reject reused roots before setup and all implicit config at each checkpoint.

    Call before creating any of the three roots, then before/after native commands.
    cwd must be the actual command cwd; --manifest-path does not change Cargo's
    hierarchical configuration lookup. The runner must construct a clean env.
    """
    paths = [ordinary(p, missing=True) for p in (home, target, install_root)]
    isolated = paths + ([ordinary(rustup_home, missing=True)] if rustup_home is not None else [])
    require(len(set(isolated)) == len(isolated) and all(a not in b.parents for a in isolated for b in isolated if a != b),
            'Cargo roots overlap')
    if before_setup:
        require(all(not p.exists() for p in isolated), 'fresh Cargo/Rustup home/target/install roots required')
    else:
        ordinary(paths[0], directory=True)
        for p in isolated[1:]:
            require(not p.exists() or p.is_dir(), 'Cargo storage must be a directory')
    checked = {paths[0] / name for name in ('config', 'config.toml')}
    if cwd is not None:
        cwd = ordinary(cwd, directory=True)
        checked.update(p / '.cargo' / name for p in (cwd, *cwd.parents) for name in ('config', 'config.toml'))
    for p in checked:
        ordinary(p, missing=True)
        require(not p.exists(), 'unreviewed Cargo config: ' + str(p))
    if env is not None:
        for key in env:
            require(not key.startswith(('CARGO_', 'RUST', 'SCCACHE_')) or key in RUST_ENV,
                    'unreviewed Cargo/Rust environment: ' + key)
        expected = dict(zip(('CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_INSTALL_ROOT'), map(str, paths)))
        require(rustup_home is not None, 'isolated RUSTUP_HOME required for native environment')
        expected['RUSTUP_HOME'] = str(rustup_home)
        require(all(env.get(k) == v for k, v in expected.items()), 'Cargo env storage differs')
        require(re.fullmatch(r'\d+\.\d+\.\d+-aarch64-apple-darwin', env.get('RUSTUP_TOOLCHAIN', '')),
                'exact Rust release/host required; no moving stable/nightly channel')
    return {'cargo_home': str(paths[0]), 'target_directory': str(paths[1]), 'install_root': str(paths[2]),
            'rustup_home': str(rustup_home) if rustup_home is not None else None,
            'implicit_configs_absent': sorted(map(str, checked)), 'fresh_checked': before_setup}


def source_inputs(roots):
    """Prove real checkout identities, native manifest/lock bytes and local edge."""
    result = {}
    for owner, files in SOURCE_BLOBS.items():
        root = ordinary(roots[owner], directory=True)
        for directory in (root, *(root / p for p in ('ffi', 'idevice', 'tests', 'tools') if owner == 'idevice'), *root.parents):
            for name in ('config', 'config.toml'):
                config = ordinary(directory / '.cargo' / name, missing=True)
                require(not config.exists(), 'unreviewed Cargo config in source ancestry: ' + str(config))
        commit, tree = NATIVE_TUPLES[owner]
        require(git(root, 'rev-parse', 'HEAD').decode().strip() == commit, 'wrong Cargo owner commit')
        require(git(root, 'rev-parse', 'HEAD^{tree}').decode().strip() == tree, 'wrong Cargo owner tree')
        checkout = verify_checkout(root, commit, owner=owner, after_build=True)
        records = entries(root, commit)
        observed = {}
        for name, blob in files.items():
            require(records.get(name) == ('100644', 'blob', blob), 'reviewed Cargo source blob differs: ' + name)
            raw = ordinary(root / name).read_bytes()
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob,
                    'Cargo input worktree changed: ' + name)
            observed[name] = {'git_blob': blob, 'sha256': sha(raw)}
        result[owner] = {'commit': commit, 'tree': tree, 'files': observed, 'checkout': checkout}
    core = tomllib.loads((Path(roots['idevice']) / 'idevice/Cargo.toml').read_text())
    require(core['dependencies']['jktcp'] == {'path': '../../jktcp', 'optional': True, 'default-features': False},
            'reviewed local jktcp declaration differs')
    require((Path(roots['idevice']) / 'idevice/../../jktcp').resolve() == Path(roots['jktcp']).resolve(),
            'actual local jktcp path resolves outside pinned owner')
    # All five local packages and only crates.io dependencies are lock-bound.
    lock = tomllib.loads((Path(roots['idevice']) / 'Cargo.lock').read_text())
    require(lock.get('version') == 4, 'unexpected Cargo lock schema')
    local = {(p['name'], p['version']) for p in lock['package'] if p.get('source') is None}
    require(local == {(k, v[2]) for k, v in LOCAL_MANIFESTS.items()}, 'Cargo local lock owner drift')
    for p in lock['package']:
        if p.get('source') is not None:
            require(p['source'] == REGISTRY and re.fullmatch('[0-9a-f]{64}', p.get('checksum', '')),
                    'unreviewed non-registry Cargo source or checksum')
    result['jktcp_lock_role'] = 'retained owner source only; idevice/Cargo.lock controls the transport workspace'
    result['nested_idevice_lock_role'] = 'retained tracked idevice/idevice/Cargo.lock is not the workspace resolver lock'
    return result


def registry_source(package, home, expected_checksum, *, phase='before', before=None, generated_snapshots=None):
    """Bind actual cached registry source bytes to the lock's crate archive hash."""
    manifest = ordinary(package['manifest_path'])
    home = ordinary(home, directory=True)
    root = manifest.parent
    require(root.parent.parent == home / 'registry/src', 'registry package escaped fresh Cargo home')
    dirname = package['name'] + '-' + package['version']
    require(root.name == dirname and manifest.name == 'Cargo.toml', 'registry package directory mismatch')
    archive = ordinary(home / 'registry/cache' / root.parent.name / (dirname + '.crate'))
    archive_raw = archive.read_bytes()
    require(sha(archive_raw) == expected_checksum, 'crate archive differs from reviewed lock')
    expected = {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as tar:
        for member in tar:
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and '..' not in name.parts and name.parts and name.parts[0] == dirname,
                    'unsafe registry archive member')
            if member.isdir():
                continue
            require(member.isfile() and len(name.parts) > 1, 'unsupported linked registry member')
            relative = '/'.join(name.parts[1:])
            require(relative not in expected, 'duplicate registry archive member')
            stream = tar.extractfile(member)
            require(stream is not None, 'unreadable registry member')
            expected[relative] = sha(stream.read())
    require(expected, 'empty registry archive')
    require(phase in ('before', 'after'), 'finite Cargo source checkpoint required')
    plist_producer = (package.get('source') == REGISTRY and (package['name'], package['version']) == PLIST_PACKAGE
                      and expected_checksum == PLIST_ARCHIVE and len(archive_raw) == PLIST_ARCHIVE_BYTES
                      and expected.get('build.rs') == PLIST_BUILD_SCRIPT
                      and inventory_digest(expected) == PLIST_SOURCE_INVENTORY)
    actual = {}
    extras = {}
    generated = None
    for path in sorted(root.rglob('*')):
        ordinary(path, missing=True)
        if path.is_dir():
            continue
        require(path.is_file(), 'special registry source entry')
        relative = str(path.relative_to(root))
        if plist_producer and relative == 'plist.h':
            raw, generated = generated_header_snapshot(path)
            digest = generated['sha256']
            if phase == 'after' and generated_snapshots is not None:
                require(PLIST_SNAPSHOT_KEY not in generated_snapshots, 'duplicate generated header snapshot')
                generated_snapshots[PLIST_SNAPSHOT_KEY] = raw
        else:
            digest = sha(path.read_bytes())
        if relative in ('.cargo-ok', '.cargo-checksum.json') and relative not in expected:
            extras[relative] = digest
            if relative == '.cargo-checksum.json':
                check = parse(path.read_bytes())
                require(check.get('package') == expected_checksum, 'Cargo checksum record differs')
        else:
            actual[relative] = digest
    proof = {'archive_sha256': expected_checksum, 'manifest_path': str(manifest),
             'source_files': actual, 'cargo_generated_files': extras}
    if plist_producer:
        if phase == 'before' and actual == expected:
            proof['generated_output_state'] = plist_generated_state(False)
            return proof
        if phase == 'after':
            require(isinstance(before, dict) and before.get('generated_output_state') == plist_generated_state(False)
                    and before.get('source_files') == expected and before.get('archive_sha256') == expected_checksum
                    and before.get('manifest_path') == str(manifest), 'exact absent-before producer proof required')
            if generated is not None and actual == {**expected, 'plist.h': PLIST_GENERATED_SHA256}:
                require(generated_snapshots is not None and PLIST_SNAPSHOT_KEY in generated_snapshots,
                        'generated header raw evidence snapshot required')
                proof.update(source_files=expected, observed_files=actual,
                             generated_artifacts={'plist.h': generated}, generated_output_state=plist_generated_state(True))
                return proof
        # Even identical source inventories fail after build if the mandatory
        # generated output is absent; a preexisting before header always fails.
        checkpoint = {'phase': phase, 'path': 'plist.h',
            'expected_present': phase == 'after', 'observed_present': 'plist.h' in actual,
            'expected_sha256': PLIST_GENERATED_SHA256}
        diagnostic = registry_mismatch_diagnostic(package, expected_checksum, len(archive_raw), expected, actual, extras,
                                                  generated_checkpoint=checkpoint)
        raise RegistrySourceMismatch(diagnostic)
    if actual != expected:
        alias = registry_documentation_alias(package, expected_checksum, len(archive_raw), root, expected, actual)
        if alias is None or alias['verified'] is not True:
            raise RegistrySourceMismatch(registry_mismatch_diagnostic(
                package, expected_checksum, len(archive_raw), expected, actual, extras, alias))
        proof.update(archive_files=expected, documentation_aliases=[alias],
                     source_inventory_relation='VERIFIED_EXACT_DOCUMENTATION_FILESYSTEM_ALIAS')
    return proof


def transport_feature_graph(packages, nodes, local):
    """Inspect the finite ffi normal/build closure, excluding dev-only edges.

    Metadata is the real --filter-platform aarch64-apple-ios result. Packages in
    Cargo.lock or the metadata package inventory are not necessarily active. A
    reachable OpenSSL dependency needs separate host/target classification and
    target-compatible library evidence; this lane has not approved either.
    """
    for name in ('idevice-ffi', 'idevice'):
        features = set(nodes[local[name]].get('features', []))
        require({'aws-lc', 'obfuscate'} <= features and 'openssl' not in features,
                'ffi transport requires aws-lc/obfuscate and no openssl feature')
    seen, pending, edges = set(), [local['idevice-ffi']], []
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        require(identifier in nodes and identifier in packages, 'active Cargo transport node missing')
        seen.add(identifier)
        require(packages[identifier]['name'] not in ('openssl', 'openssl-sys', 'tokio-openssl'),
                'active OpenSSL transport edge requires explicit host/target classification')
        node = nodes[identifier]
        for dependency in node.get('deps', []):
            kinds = dependency.get('dep_kinds')
            require(isinstance(kinds, list) and kinds and all(isinstance(k, dict) and {'kind','target'} <= set(k) and k['kind'] in (None, 'build', 'dev') for k in kinds),
                    'missing/unclassified active Cargo dependency kind')
            active = [kind for kind in kinds if kind.get('kind') != 'dev']
            if not active:
                continue
            target = dependency['pkg']
            require(target in nodes and target in packages, 'active Cargo dependency target missing')
            edges.append({'from': identifier, 'to': target, 'name': dependency['name'], 'dep_kinds': active})
            pending.append(target)
    names = {packages[identifier]['name'] for identifier in seen}
    require({'idevice-ffi', 'idevice', 'jktcp', 'aws-lc-rs', 'aws-lc-sys'} <= names,
            'expected local transport/aws-lc dependency closure missing')
    return {'root': local['idevice-ffi'], 'closure': 'normal-and-build; dev-only edges excluded',
            'required_features': ['aws-lc', 'obfuscate'], 'active_openssl': False,
            'packages': [{'id': identifier, 'name': packages[identifier]['name'], 'version': packages[identifier]['version'],
                          'source': packages[identifier].get('source')} for identifier in sorted(seen)],
            'edges': sorted(edges, key=lambda edge: (edge['from'], edge['to'], edge['name']))}


def verify_cargo_metadata(metadata, roots, home, target, *, phase='before', before=None, generated_snapshots=None):
    """Validate real --locked --offline, ios-filtered obfuscate metadata output.

    Cargo metadata documents all workspace packages. The real build remains the
    ffi manifest's default package selection; these data do not claim tools/tests
    were compiled. The caller must require this proof unchanged after the build.
    """
    source_proof = source_inputs(roots)
    require(phase in ('before', 'after') and (phase == 'before' and before is None or phase == 'after' and isinstance(before, dict)),
            'explicit Cargo before/after checkpoint and prior proof required')
    data = parse(metadata)
    require(data.get('version') == 1, 'Cargo metadata format differs')
    require(Path(data.get('workspace_root', '')) == Path(roots['idevice']), 'wrong Cargo workspace root')
    require(Path(data.get('target_directory', '')) == Path(target), 'wrong Cargo target directory')
    lock = tomllib.loads((Path(roots['idevice']) / 'Cargo.lock').read_text())
    locked = {}
    for package in lock['package']:
        key = (package['name'], package['version'], package.get('source'))
        require(key not in locked, 'duplicate Cargo lock identity')
        locked[key] = package
    packages, local, registry, identities = {}, {}, {}, set()
    for package in data.get('packages', []):
        identifier = package['id']
        require(identifier not in packages, 'duplicate Cargo metadata ID')
        key = (package['name'], package['version'], package.get('source'))
        require(key in locked and key not in identities, 'resolved Cargo package absent from reviewed lock or duplicated')
        identities.add(key)
        packages[identifier] = package
        if package.get('source') is None:
            require(package['name'] in LOCAL_MANIFESTS and package['name'] not in local, 'extra local Cargo package')
            owner, path, version = LOCAL_MANIFESTS[package['name']]
            require(package['version'] == version and Path(package['manifest_path']) == Path(roots[owner]) / path,
                    'resolved local Cargo manifest escaped exact owner')
            local[package['name']] = identifier
        else:
            require(package['source'] == REGISTRY, 'unreviewed registry or Git Cargo source')
            registry[identifier] = registry_source(package, home, locked[key]['checksum'], phase=phase,
                before=before['registry_packages'].get(identifier) if before is not None else None,
                generated_snapshots=generated_snapshots)
    require(set(local) == set(LOCAL_MANIFESTS), 'missing local Cargo workspace package')
    workspace = data.get('workspace_members', [])
    require(len(workspace) == 4 and set(workspace) == {local[n] for n in LOCAL_MANIFESTS if n != 'jktcp'},
            'Cargo workspace member drift')
    resolve = data.get('resolve')
    require(isinstance(resolve, dict), 'Cargo resolve graph missing; --no-deps is forbidden')
    require(resolve.get('root') == local['idevice-ffi'], 'metadata must select the actual ffi manifest')
    nodes = {}
    for node in resolve.get('nodes', []):
        require(node['id'] in packages and node['id'] not in nodes, 'invalid/duplicate resolved node')
        require(all(dep in packages for dep in node.get('dependencies', [])), 'dangling resolved Cargo edge')
        require(all(dep['pkg'] in packages for dep in node.get('deps', [])), 'dangling detailed Cargo edge')
        require(set(node.get('dependencies', [])) == {dep['pkg'] for dep in node.get('deps', [])},
                'Cargo simple/detailed dependency edges disagree')
        nodes[node['id']] = node
    require(set(local.values()) <= set(nodes), 'local Cargo resolution node missing')
    for source, destination in (('idevice-ffi', 'idevice'), ('idevice', 'jktcp')):
        node = nodes[local[source]]
        require(local[destination] in node.get('dependencies', []), 'resolved local Cargo edge missing')
        require(any(d['name'] == destination.replace('-', '_') and d['pkg'] == local[destination]
                    for d in node.get('deps', [])), 'resolved local Cargo dependency name differs')
    transport = transport_feature_graph(packages, nodes, local)
    return {'source_inputs': source_proof, 'local_packages': local, 'registry_packages': registry,
            'transport_features': transport,
            'metadata_sha256': sha(metadata.encode() if isinstance(metadata, str) else metadata)
            if isinstance(metadata, (str, bytes)) else sha(json.dumps(metadata, sort_keys=True).encode()),
            'workspace_root': data['workspace_root'], 'target_directory': data['target_directory']}


def verify_bindgen_install(install_root, version_output):
    root = ordinary(install_root, directory=True)
    require(version_output.strip() == 'bindgen 0.72.1', 'exact bindgen 0.72.1 required')
    binary = ordinary(root / 'bin/bindgen')
    receipt = ordinary(root / '.crates2.json')
    installed = parse(receipt.read_bytes()).get('installs', {})
    key = 'bindgen-cli 0.72.1 (' + REGISTRY + ')'
    require(set(installed) == {key} and installed[key].get('bins') == ['bindgen'], 'fresh exact bindgen installation differs')
    return {'version': version_output.strip(), 'binary': str(binary), 'binary_sha256': sha(binary.read_bytes()),
            'cargo_install_receipt_sha256': sha(receipt.read_bytes()), 'cargo_install': installed[key]}


def verify_openssl_provenance(brew_info_json, prefix, version_output, *, expected_version=None):
    """Record actual installed Homebrew OpenSSL, with an optional reviewed pin."""
    info = parse(brew_info_json)
    formulae = info.get('formulae', [])
    require(len(formulae) == 1 and formulae[0].get('name') == 'openssl@3', 'one actual openssl@3 formula required')
    formula = formulae[0]
    installed = formula.get('installed', [])
    require(len(installed) == 1 and installed[0].get('version'), 'unambiguous installed OpenSSL version required')
    version = installed[0]['version']
    if expected_version is not None:
        require(version == expected_version, 'installed OpenSSL differs from reviewed version')
    require(re.fullmatch(r'3\.\d+\.\d+(?:_\d+)?', version), 'OpenSSL 3 formula version differs')
    require(version_output.splitlines() and version_output.splitlines()[0].startswith('OpenSSL ' + version.split('_')[0] + ' '),
            'actual OpenSSL executable version differs from brew receipt')
    # `brew --prefix` normally returns an opt symlink; bind its actual Cellar target.
    prefix = Path(str(prefix).strip())
    require(prefix.is_absolute() and '..' not in prefix.parts, 'actual absolute OpenSSL prefix required')
    real = prefix.resolve(strict=True)
    require(real.name == version and real.parent.name == 'openssl@3' and real.parent.parent.name == 'Cellar',
            'OpenSSL prefix is not the installed Cellar version')
    binary = ordinary(real / 'bin/openssl')
    return {'formula': 'openssl@3', 'installed_version': version, 'prefix': str(prefix), 'real_prefix': str(real),
            'binary_sha256': sha(binary.read_bytes()), 'version_output': version_output,
            'brew_info_sha256': sha(brew_info_json.encode() if isinstance(brew_info_json, str) else brew_info_json)
            if isinstance(brew_info_json, (str, bytes)) else sha(json.dumps(info, sort_keys=True).encode()),
            'installed': installed[0]}
