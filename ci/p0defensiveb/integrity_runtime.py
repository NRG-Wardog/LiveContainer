"""Later Apple-only genuine-source synthetic capture; importing never executes it.

This adds eight separate cases, never changes the exact38 consumer inventory, and
never admits Phase B. The caller must already have admitted the complete source
composition and completed the SideStore app resolver/build. Its libdeflate checkout
is rebuilt for the host offline; iOS output is not a host-linkable substitute.
Every launched command uses Gate.run and its retained process-group settlement.
"""
import math
import os
from pathlib import Path
import platform
import re
import stat
import sys

from inventory import parse, require, sha
from lifecycle import command_environment
from native_build import LOCK
from product_plan import SANDBOX
from consumer_contract import ordinary_bytes

SOURCE_COMMIT = 'aed9e5ff3fa9d8d88c51788e82af9d780a41cbb9'
SOURCE_TREE = 'e05139bb18388abbe659f99ae0391b80fc2d3ea0'
DEPENDENCY_COMMIT = 'da6c7dae03b78dc71af973664575e4209786fbfe'
DEPENDENCY_URL = 'https://github.com/SideStore/libdeflate'
SCHEMA = 'p0-library-integrity-runtime-v1'
MAX_FILES, MAX_SOURCE_BYTES, MAX_BUILD_BYTES = 4096, 64 * 1024 * 1024, 512 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
SOURCE_FILES = {
    '.ci/library-integrity/generate.py': ('0fdc81d168c4f8945ece72d9e1f09659b5b340dbdff8b44942546881829ae663', 5317),
    '.ci/library-integrity/BoundaryDoubles.swift': ('1fe6c58fbd11c633ea34edea4a52ff56ed197af1745df152f9153c9857155df9', 4044),
    '.ci/library-integrity/RuntimeTests.swift': ('5b1a498eec1131f2c1e483f1e94d17fc309bef5f70a35c1bc883447a6ad50683', 6592),
    '.ci/library-integrity/run-apple.sh': ('b936ed9d7cbd68bb523253348b395649aa6a5695d9af6645bd172e1f1089e1e2', 1790),
    '.ci/library-integrity/source-spans.json': ('98483ad836c48c4acb91cb891bb75d3e81f395aa3b7d7c8829c012957bd07aea', 2975),
    'Sources/Anisette/AnisetteDataManager.swift': ('6159f83d125b3b9a898754179e0168c061d44510ccd1e84a174fe77c83f3e5e5', 30132),
    'Sources/Archiver/Archive.swift': ('e58c6d0dc9933db8ba85a4871ffe3b6c5c3c532d852813185f3620c8b8b4db59', 25859),
    'Sources/Archiver/FileManagerZip.swift': ('c95b998f11f5b906d860876d3be3a409bf079dffdfb80c9ccdfaefabc32ba22f', 7356),
    'Sources/SideSign.swift': ('9c161cb2c609fb4d1c9d6272f96453c97d427834510ccfd8d54e87e16b5782f9', 2080),
}
GENERATED_FILES = {
    'Archive.swift': ('e58c6d0dc9933db8ba85a4871ffe3b6c5c3c532d852813185f3620c8b8b4db59', 25859),
    'BoundaryDoubles.swift': ('1fe6c58fbd11c633ea34edea4a52ff56ed197af1745df152f9153c9857155df9', 4044),
    'FixtureData.swift': ('862f06977671d91fe0005011adcd951f8283bca08b0dfb1db77143ee2b3d13a4', 1347),
    'ProductionDownload.swift': ('8d6ecf21d891db8458d1b45421c1a255120e6a8cea08bfb36bb7eb4c9d0bc7fc', 10455),
    'ProductionUnzip.swift': ('6730d327769742ee10bbaf122b58eea1a3502088a4f301df49120d653a387434', 2653),
    'RuntimeTests.swift': ('5b1a498eec1131f2c1e483f1e94d17fc309bef5f70a35c1bc883447a6ad50683', 6592),
    'generation-receipt.json': ('ff32354d6e841a15fd2a02442dd2564f1f6b3b1150126e81d43cda515e27b1bf', 4711),
}
CASE_IDS = (
    'matching-lowercase', 'matching-uppercase', 'absent-hash-compatibility',
    'empty-hash-compatibility', 'mismatch-empty-valid-hex-metadata and retry',
    'mismatch-existing-valid-hex-metadata and retry',
    'mismatch-empty-malformed-hex-metadata and retry',
    'mismatch-existing-valid-bad-metadata and retry',
)
SUMMARY = 'PASS: 8 genuine-source synthetic cases; no native provider or network'
RUNTIME_STDOUT = ('\n'.join('PASS: ' + case for case in CASE_IDS) + '\n' + SUMMARY + '\n').encode()
COMMAND_PARTS = {'command': '.command.json', 'stdout': '.log', 'stderr': '.stderr.log',
                 'exit_code': '.exit-code.txt', 'settlement': '.settlement.json'}
SWIFT_INPUTS = ('ProductionDownload.swift', 'Archive.swift', 'ProductionUnzip.swift',
                'BoundaryDoubles.swift', 'FixtureData.swift', 'RuntimeTests.swift')
MODULE_MAP = b'module libdeflate { header "libdeflate.h" export * }\n'
NETWORK_PROBE = ('import errno,socket\ns=socket.socket(); e=s.connect_ex(("127.0.0.1",9)); s.close()\n'
                 'if e not in (errno.EPERM,errno.EACCES):raise SystemExit("network sandbox did not deny")')


def parse_runtime(stdout, stderr, exit_code):
    """Exact independently replayable ordered cases; summary alone proves nothing."""
    require(isinstance(stdout, bytes) and stdout == RUNTIME_STDOUT, 'exact eight ordered runtime case records required')
    require(stderr == b'' and exit_code == b'0\n', 'runtime stderr or nonzero/noncanonical exit code')
    return {'tests': 8, 'failures': 0, 'errors': 0, 'skipped': 0,
            'case_ids': list(CASE_IDS), 'successful_case_ids': list(CASE_IDS)}


def validate_command(raw, argv, cwd, environment, *, runtime=False, maximum_timeout=900):
    """Validate raw runner records, never an emitter's success Boolean."""
    require(set(raw) == set(COMMAND_PARTS), 'complete raw command record required')
    require(all(isinstance(value, bytes) and len(value) <= MAX_LOG_BYTES for value in raw.values()),
            'bounded raw command bytes required')
    command, settlement = parse(raw['command']), parse(raw['settlement'])
    require(command == {'argv': list(map(str, argv)), 'cwd': str(cwd), 'environment': environment},
            'runtime command/cwd/environment substitution')
    require(raw['exit_code'] == b'0\n' and type(settlement.get('returncode')) is int and settlement['returncode'] == 0,
            'successful actual command exit required')
    require(type(settlement.get('terminationReturncode')) is int and settlement['terminationReturncode'] == 0,
            'successful settled command exit required')
    require(not any(key in settlement for key in ('error', 'quiescenceError')),
            'command timeout or quiescence failure')
    timeout = settlement.get('timeout_seconds')
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= maximum_timeout,
            'bounded actual command timeout required')
    owned = settlement.get('ownedProcessGroup', {})
    require(type(owned.get('pgid')) is int and owned['pgid'] > 0 and
            all(owned.get(key) is True for key in ('quiescent', 'pipesJoined', 'leaderReaped')) and
            owned.get('errors') == [] and owned.get('signals') == [] and
            owned.get('postReapPolicy') == 'read-only-group-disappearance', 'owned command writers did not settle')
    return parse_runtime(raw['stdout'], raw['stderr'], raw['exit_code']) if runtime else None


def checked_files(root, expected, *, exact=False):
    root = Path(root)
    if exact:
        require(root.is_dir() and not root.is_symlink() and
                set(path.name for path in root.iterdir()) == set(expected), 'generated file closure differs')
    result = {}
    for name, (digest, length) in expected.items():
        raw = ordinary_bytes(root, name, limit=MAX_SOURCE_BYTES)
        require(len(raw) == length and sha(raw) == digest, 'frozen integrity source differs: ' + name)
        result[name] = raw
    return result


def _tree_paths(root, *, limit, omit_git=False):
    """Bound discovery before retention; no directory-link following or traversal."""
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and root.resolve() == root, 'canonical capture directory required')
    files, total, count = [], 0, 0
    for folder, directories, names in os.walk(root, followlinks=False):
        relative = Path(folder).relative_to(root)
        require(len(relative.parts) <= 32, 'integrity tree depth exceeded')
        if omit_git and not relative.parts:
            directories[:] = [name for name in directories if name != '.git']
            names = [name for name in names if name != '.git']
        count += len(directories) + len(names)
        require(count <= MAX_FILES, 'integrity tree file count exceeded')
        for name in list(directories):
            path = Path(folder)/name
            if path.is_symlink():
                files.append(path); directories.remove(name)
        for name in names:
            path = Path(folder)/name
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode), 'ordinary integrity tree entries required')
            total += info.st_size
            require(total <= limit, 'integrity tree bytes exceeded')
            files.append(path)
    return sorted(files)


def locate_dependency(gate):
    """Find only the app's already-resolved exact dependency, never acquire one."""
    packages = gate.work/'sidestore-packages'
    require(packages.is_dir(), 'integrity sequencing: complete SideStore app resolution/build before this stage; libdeflate has not been acquired')
    require(packages.is_absolute() and packages.resolve() == packages, 'canonical app package root required')
    # Xcode's selected clonedSourcePackagesDirPath is fixed by app_commands.
    # Do not scan unrelated package/artifact trees to discover an alternate state.
    state_path = packages/'workspace-state.json'
    require(state_path.is_file() and not state_path.is_symlink(),
            'integrity sequencing: actual SideStore workspace-state.json must exist after app resolution/build')
    state_raw = ordinary_bytes(state_path.parent, state_path.name)
    lock_raw = ordinary_bytes(gate.roots['SideStore'], LOCK)
    pins = parse(lock_raw).get('pins', [])
    matching = [pin for pin in pins if pin.get('identity') == 'libdeflate']
    require(len(matching) == 1 and matching[0] == {
        'identity': 'libdeflate', 'kind': 'remoteSourceControl', 'location': DEPENDENCY_URL,
        'state': {'branch': 'master', 'revision': DEPENDENCY_COMMIT}}, 'exact genuine libdeflate lock pin required')
    dependencies = parse(state_raw)['object']['dependencies']
    matching = [dep for dep in dependencies if dep.get('packageRef', {}).get('identity', '').lower() == 'libdeflate']
    require(len(matching) == 1, 'one actual libdeflate checkout required')
    row = matching[0]; ref = row['packageRef']; subpath = row.get('subpath')
    require(ref.get('kind') == 'remoteSourceControl' and ref.get('location') == DEPENDENCY_URL and
            row.get('state', {}).get('name') == 'sourceControlCheckout' and
            row['state'].get('checkoutState', {}).get('revision') == DEPENDENCY_COMMIT,
            'libdeflate workspace-state source differs')
    require(isinstance(subpath, str) and re.fullmatch(r'[A-Za-z0-9_.-]+', subpath) and subpath not in ('.', '..'),
            'ordinary libdeflate checkout subpath required')
    checkout = state_path.parent/'checkouts'/subpath
    require(checkout.is_dir() and checkout.resolve() == checkout and checkout.parent.parent == packages,
            'libdeflate checkout escaped existing app package root')
    return checkout, {'workspace_state': state_raw, 'app_lock': lock_raw}


def verify_dependency_working_tree(checkout, tree):
    require(tree.get('commit') == DEPENDENCY_COMMIT and re.fullmatch('[a-f0-9]{40}', tree.get('tree', '')),
            'retained libdeflate identity differs')
    entries = tree.get('entries', [])
    require(0 < len(entries) <= MAX_FILES and len({row['path'] for row in entries}) == len(entries), 'bounded unique libdeflate sources required')
    actual = _tree_paths(checkout, limit=MAX_SOURCE_BYTES, omit_git=True)
    require({str(path.relative_to(checkout)) for path in actual} == {row['path'] for row in entries},
            'libdeflate working tree has extra/missing compiler inputs')
    for row in entries:
        name = row['path']; path = checkout/name
        require(isinstance(name, str) and name and all(part not in ('', '.', '..') for part in name.split('/')) and not Path(name).is_absolute(),
                'safe libdeflate source path required')
        if row['git_mode'] == '120000':
            require(path.is_symlink() and path.resolve().is_relative_to(checkout), 'libdeflate source link escapes checkout')
            raw = os.fsencode(os.readlink(path))
        else:
            require(row['git_mode'] in ('100644', '100755'), 'no dependency gitlinks/special objects')
            raw = ordinary_bytes(checkout, name, limit=MAX_SOURCE_BYTES)
            require(('100755' if path.stat().st_mode & 0o111 else '100644') == row['git_mode'], 'libdeflate mode differs')
        require(len(raw) == row['length'] and sha(raw) == row['sha256'], 'libdeflate compiler input differs from retained commit')
    return tree['tree']


def dependency_objects(scratch):
    paths = _tree_paths(scratch, limit=MAX_BUILD_BYTES)
    objects = [path for path in paths if path.suffix == '.o' and 'libdeflate.build' in path.parts]
    require(1 <= len(objects) <= 128 and all(not path.is_symlink() and path.stat().st_size > 0 for path in objects),
            'genuine host libdeflate target objects required; app iOS output cannot substitute')
    require(all('release' in path.relative_to(scratch).parts for path in objects), 'host release objects required')
    return objects


def compile_command(generated, archive):
    return ['xcrun', 'swiftc', '-swift-version', '6', '-parse-as-library', '-O',
            '-module-name', 'SideSignLibraryIntegrityFixture', '-I', generated/'libdeflate-module',
            *[generated/name for name in SWIFT_INPUTS], archive, '-o', generated/'library-integrity-tests']


def run_integrity(gate):
    """Capture a later authorized Apple run; no invocation or admission at import."""
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'actual Apple arm64 required; runtime not executed')
    work = gate.work/'library-integrity'
    require(not work.exists() and not work.is_symlink(), 'fresh integrity work root required')
    source = Path(gate.roots['SideSign'])
    source_bytes = checked_files(source, SOURCE_FILES)
    checkout, dependency_inputs = locate_dependency(gate)
    report = {'schema': SCHEMA, 'status': 'FAILED_OR_INCOMPLETE', 'source_commit': None,
              'source_tree': None, 'patch_commit': SOURCE_COMMIT, 'patch_tree': SOURCE_TREE, 'commands': {}, 'raw': {}, 'case_ids': list(CASE_IDS),
              'boundaries': ['synthetic inert ZIP entries', 'inert provider constructor/existence double',
                             'deny-only URLSession double', 'Apple CryptoKit substituted for import Crypto'],
              'network_allowed': False, 'native_provider_executed': False, 'guest_executed': False}
    work.mkdir(); generated = work/'generated'; scratch = work/'libdeflate-build'

    def retain_bytes_map(name, values):
        records = {key: gate.store.retain_bytes(value, label='library-integrity/'+name+'/'+key) for key, value in values.items()}
        report['raw'][name] = records
        return records

    def run(name, argv, *, timeout=600, runtime=False):
        label = 'integrity-'+name
        wrapped = ['/usr/bin/sandbox-exec', '-p', SANDBOX, *map(str, argv)]
        entry = {'argv': wrapped, 'cwd': str(work), 'timeout_seconds': timeout, 'raw': {}}
        report['commands'][label] = entry
        raw = {}
        try:
            gate.run(label, wrapped, cwd=work, env=gate.base_env, timeout=timeout, stdout_only=True)
        finally:
            for part, suffix in COMMAND_PARTS.items():
                path = gate.evidence/'logs'/(label+suffix)
                if path.exists():
                    raw[part] = ordinary_bytes(path.parent, path.name, limit=MAX_LOG_BYTES)
                    entry['raw'][part] = gate.store.retain_bytes(raw[part], label='library-integrity/commands/'+label+'/'+part)
        environment = command_environment(label, wrapped, gate.base_env)
        from lifecycle import FIXED_ENV
        environment = {key: environment[key] for key in FIXED_ENV if key in environment}
        result = validate_command(raw, wrapped, work, environment, runtime=runtime, maximum_timeout=timeout)
        return result if runtime else raw['stdout']

    def working_dependency(phase, tree):
        verify_dependency_working_tree(checkout, tree)
        records = {}
        for row in tree['entries']:
            name = row['path']; path = checkout/name
            raw = os.fsencode(os.readlink(path)) if row['git_mode'] == '120000' else ordinary_bytes(checkout, name, limit=MAX_SOURCE_BYTES)
            require(len(raw) == row['length'] and sha(raw) == row['sha256'], 'dependency changed while retaining working compiler inputs')
            records[name] = gate.store.retain_bytes(raw, label='library-integrity/dependency-working-'+phase+'/'+name, mode=row['git_mode'])
        report['raw']['dependency-working-'+phase] = records

    try:
        retain_bytes_map('frozen-source', source_bytes)
        retain_bytes_map('dependency-binding', dependency_inputs)
        run('network-denial-probe', [sys.executable, '-c', NETWORK_PROBE], timeout=120)
        source_git = ['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-C', source]
        source_identity = run('source-identity', [*source_git, 'rev-parse', 'HEAD', 'HEAD^{tree}'], timeout=120).decode('ascii').splitlines()
        require(len(source_identity) == 2 and all(re.fullmatch('[a-f0-9]{40}', value) for value in source_identity),
                'actual SideSign source identity required')
        report.update(source_commit=source_identity[0], source_tree=source_identity[1])
        git = ['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-C', checkout]
        identity = run('libdeflate-identity', [*git, 'rev-parse', 'HEAD', 'HEAD^{tree}'], timeout=120).decode('ascii').splitlines()
        require(len(identity) == 2 and identity[0] == DEPENDENCY_COMMIT and re.fullmatch('[a-f0-9]{40}', identity[1]),
                'actual dependency commit/tree differs')
        commit_raw = run('libdeflate-commit', [*git, 'cat-file', 'commit', DEPENDENCY_COMMIT], timeout=120)
        import hashlib
        require(hashlib.sha1(b'commit ' + str(len(commit_raw)).encode() + b'\0' + commit_raw).hexdigest() == DEPENDENCY_COMMIT and
                commit_raw.startswith(('tree ' + identity[1] + '\n').encode()), 'dependency commit object/tree mismatch')
        tree = gate.store.retain_git_tree(checkout, DEPENDENCY_COMMIT, label='library-integrity/libdeflate-source')
        require(tree['tree'] == identity[1], 'dependency retained tree differs from actual Git identity')
        report['raw']['dependency_source'] = tree
        working_dependency('before', tree)
        report['dependency'] = {'commit': DEPENDENCY_COMMIT, 'tree': verify_dependency_working_tree(checkout, tree),
                                'repository': DEPENDENCY_URL, 'checkout': str(checkout)}
        # dump-package runs the already acquired, hash-bound manifest locally.
        # The package must be dependency-free; neither command may acquire sources.
        manifest = parse(run('libdeflate-manifest', ['swift', 'package', '--package-path', checkout,
            '--scratch-path', scratch, 'dump-package']))
        targets = [target for target in manifest.get('targets', []) if target.get('name') == 'libdeflate']
        require(manifest.get('dependencies') == [] and len(targets) == 1 and targets[0].get('type') == 'regular' and
                targets[0].get('dependencies') == [] and not targets[0].get('pluginUsages'),
                'existing libdeflate package must be an ordinary dependency-free C target')
        verify_dependency_working_tree(checkout, tree)
        run('libdeflate-build', ['swift', 'build', '--package-path', checkout, '--scratch-path', scratch,
            '--configuration', 'release', '--target', 'libdeflate', '--disable-automatic-resolution', '--skip-update',
            '--jobs', '2', '--verbose'], timeout=900)
        verify_dependency_working_tree(checkout, tree)
        objects = dependency_objects(scratch)
        report['raw']['dependency_build'] = gate.store.retain_tree(scratch, label='library-integrity/libdeflate-build')
        report['dependency']['object_paths'] = [str(path) for path in objects]
        archive = work/'libdeflate.a'
        run('libdeflate-archive', ['xcrun', 'ar', 'rcs', archive, *objects])
        require(ordinary_bytes(work, archive.name, limit=MAX_BUILD_BYTES).startswith(b'!<arch>\n'), 'genuine static archive output required')
        report['raw']['dependency_archive'] = gate.store.retain_file(archive, label='library-integrity/libdeflate.a')
        run('generate', [sys.executable, '-B', source/'.ci/library-integrity/generate.py', generated])
        generated_bytes = checked_files(generated, GENERATED_FILES, exact=True)
        retain_bytes_map('generated-source', generated_bytes)
        headers = [checkout/row['path'] for row in tree['entries'] if Path(row['path']).name == 'libdeflate.h']
        require(headers, 'genuine libdeflate public header unavailable in acquired source')
        header_bytes = [ordinary_bytes(checkout, str(path.resolve().relative_to(checkout)), limit=MAX_SOURCE_BYTES) for path in headers]
        require(all(value == header_bytes[0] for value in header_bytes), 'ambiguous libdeflate public header bytes')
        module = generated/'libdeflate-module'; module.mkdir()
        (module/'libdeflate.h').write_bytes(header_bytes[0]); (module/'module.modulemap').write_bytes(MODULE_MAP)
        report['dependency']['header_paths'] = list(map(str, headers))
        retain_bytes_map('compiler-module', {'libdeflate.h': header_bytes[0], 'module.modulemap': MODULE_MAP})
        run('compile', compile_command(generated, archive), timeout=600)
        binary = generated/'library-integrity-tests'
        require(binary.is_file() and not binary.is_symlink() and binary.stat().st_mode & 0o111, 'actual executable fixture output required')
        require(binary.stat().st_size <= MAX_BUILD_BYTES, 'bounded fixture executable required')
        report['raw']['fixture_binary'] = gate.store.retain_file(binary, label='library-integrity/fixture-binary-before')
        before = report['raw']['fixture_binary']['sha256']
        report['results'] = run('runtime', [binary], timeout=120, runtime=True)
        report['raw']['fixture_binary_after'] = gate.store.retain_file(binary, label='library-integrity/fixture-binary-after')
        require(report['raw']['fixture_binary_after']['sha256'] == before, 'fixture executable changed during execution')
        terminal_source = checked_files(source, SOURCE_FILES); terminal_generated = checked_files(generated, GENERATED_FILES)
        require(terminal_source == source_bytes and terminal_generated == generated_bytes, 'source changed during integrity fixture capture')
        retain_bytes_map('frozen-source-after', terminal_source)
        retain_bytes_map('generated-source-after', terminal_generated)
        working_dependency('after', tree)
        require(run('source-identity-after', [*source_git, 'rev-parse', 'HEAD', 'HEAD^{tree}'], timeout=120).decode('ascii').splitlines() == source_identity,
                'actual SideSign identity changed during fixture capture')
        require(run('libdeflate-identity-after', [*git, 'rev-parse', 'HEAD', 'HEAD^{tree}'], timeout=120).decode('ascii').splitlines() == identity,
                'dependency commit/tree changed during fixture capture')
        require(ordinary_bytes(module, 'libdeflate.h') == header_bytes[0] and ordinary_bytes(module, 'module.modulemap') == MODULE_MAP,
                'libdeflate compiler module changed')
        report['raw']['dependency_archive_after'] = gate.store.retain_file(archive, label='library-integrity/libdeflate.a-after')
        require(report['raw']['dependency_archive_after']['sha256'] == report['raw']['dependency_archive']['sha256'],
                'libdeflate archive changed during capture')
        retain_bytes_map('compiler-module-after', {'libdeflate.h': ordinary_bytes(module, 'libdeflate.h'),
                                                'module.modulemap': ordinary_bytes(module, 'module.modulemap')})
        report['status'] = 'CAPTURED_FOR_INDEPENDENT_REVIEW'
        return report
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        gate.save('library-integrity', report)
