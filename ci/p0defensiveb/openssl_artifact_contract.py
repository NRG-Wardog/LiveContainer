"""Read-only SideStore OpenSSL source binding. Never loads a binary or Swift manifest.

The approved archive is hashed and parsed from ONE bounded immutable byte snapshot;
its ios-arm64 slice is compared with both the reviewed inventory and ordinary files
in the actual SwiftPM artifact path. Xcode's exact copy projection is retained with
no signing, stripping, normalization, extraction, or dependency execution here.

validate_source_proof checks a report's shape and invariant bindings. It is not an
attestation authenticator: callers must use this verifier's in-process result, not
accept an arbitrary external JSON document as evidence of filesystem observation.
"""
import copy
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import zipfile

import source_primitives as primitives

SOURCE_REPOSITORY = 'https://github.com/mahee96/RemotePairingKit.git'
SOURCE_COMMIT = 'e3f70d16c0c551540a533a39d540e78e5b0a60a8'
SOURCE_TREE = '007ba009bb6dbb4f2149da8e918a0dcd02b1a4e2'
MANIFEST_BLOB = '0176e1cd70b13481939eb282d081167a43a5bf17'
MANIFEST_SHA256 = '4ab6b23b6ef59fda4c5ae6001574362b697d4882d396de4bdd93231e9eeb2dab'
MANIFEST_BYTES = 1367
ARTIFACT_URL = 'https://github.com/krzyzanowskim/OpenSSL/releases/download/3.6.2000/OpenSSL.xcframework.zip#RemotePairingKit'
ARCHIVE_URL = ARTIFACT_URL.split('#', 1)[0]
ARCHIVE_SHA256 = '37846a8bd302cb2443eff47f1045ab844d0cd40bf82cc6159cfad9aa5c3eff9e'
ARCHIVE_BYTES = 45431584
REVIEWED_INVENTORY_SHA256 = '914acae691d22d94af6de528097ddce74e06920f9dfd66f4b0e375bfaafbc5e8'
REVIEWED_INVENTORY_PATH = Path(__file__).parent / 'tests/fixtures/sidestore-openssl-3.6.2000.inventory.json'
ARTIFACT_RELATIVE = 'artifacts/remotepairingkit/OpenSSL/OpenSSL.xcframework'
PACKAGE_RELATIVE = 'checkouts/RemotePairingKit'
ARCHIVE_PREFIX = 'OpenSSL.xcframework/'
SLICE_PREFIX = ARCHIVE_PREFIX + 'ios-arm64/'
FRAMEWORK_PREFIX = 'OpenSSL.framework/'
COPY_EXCLUSIONS = ('Headers', 'PrivateHeaders', 'Modules', '*.tbd', '.DS_Store', 'CVS', '.svn', '.git', '.hg')
PRODUCT_NAMES = {'OpenSSL', 'Info.plist', 'PrivacyInfo.xcprivacy', '_CodeSignature/CodeResources'}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_STATE_BYTES = 4 * 1024 * 1024
PROOF_KIND = 'sidestore-remotepairingkit-openssl-source-v1'


class OpenSSLArtifactError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        self.diagnostic = {'kind': 'sidestore-openssl-source-mismatch', 'reason': str(message)[:512],
                           'source_repository': SOURCE_REPOSITORY, 'source_commit': SOURCE_COMMIT,
                           'archive_sha256': ARCHIVE_SHA256, 'executed': False}


def _require(value, message):
    if not value:
        raise OpenSSLArtifactError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _description(raw):
    return {'bytes': len(raw), 'sha256': _sha(raw)}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(OpenSSLArtifactError('nonfinite JSON value')))
    except OpenSSLArtifactError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise OpenSSLArtifactError('invalid bounded JSON') from error


def _safe_name(name):
    _require(isinstance(name, str) and 0 < len(name) <= 1024 and
             not name.startswith('/') and '\\' not in name and '\0' not in name and
             all(part not in ('', '.', '..') for part in name.split('/')) and
             all(ord(char) >= 32 and ord(char) != 127 for char in name), 'unsafe artifact member path')
    return name


def _ordinary(path, *, directory=False):
    path = Path(path)
    _require(path.is_absolute() and '..' not in path.parts, 'absolute unambiguous artifact path required')
    try:
        for parent in reversed(path.parents):
            _require(stat.S_ISDIR(parent.lstat().st_mode), 'artifact path has nonordinary parent')
        mode = path.lstat().st_mode
        _require(stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode),
                 'ordinary artifact directory required' if directory else 'ordinary artifact file required')
    except OSError as error:
        raise OpenSSLArtifactError('artifact path cannot be observed: ' + str(path)) from error
    return path


def _snapshot(path, limit):
    """One read supplies both parsing and hashes; detect checkpoint substitutions."""
    path = _ordinary(path)
    try:
        _require(all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_NONBLOCK', 'O_CLOEXEC')),
                 'safe ordinary-file open flags unavailable on this host')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                     before.st_size <= limit, 'bounded unaliased ordinary artifact required')
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = path.lstat()
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        _require(len(raw) == before.st_size and len(raw) <= limit and
                 all(getattr(before, key) == getattr(after, key) == getattr(current, key) for key in keys),
                 'artifact changed during byte observation')
        return raw
    except OSError as error:
        raise OpenSSLArtifactError('artifact read failed: ' + str(path)) from error


def snapshot_workspace_state(path):
    """Bound and freeze the actual state bytes before retention or JSON parsing."""
    return _snapshot(path, MAX_STATE_BYTES)


def _project(files):
    result = {}
    for name, description in sorted(files.items()):
        if not name.startswith(FRAMEWORK_PREFIX):
            continue
        relative = name[len(FRAMEWORK_PREFIX):]
        if not any(fnmatch.fnmatchcase(part, pattern) for part in relative.split('/') for pattern in COPY_EXCLUSIONS):
            result[relative] = copy.deepcopy(description)
    _require(set(result) == PRODUCT_NAMES, 'exact four-file Xcode copy projection required')
    return result


def _load_reviewed_inventory():
    # This is reviewed adapter data, not an input supplied by a build or archive.
    raw = _snapshot(REVIEWED_INVENTORY_PATH.absolute(), 128 * 1024)
    _require(_sha(raw) == REVIEWED_INVENTORY_SHA256, 'reviewed OpenSSL inventory changed')
    inventory = _json(raw)
    _require(inventory['schema'] == 'sidestore-openssl-reviewed-inventory-v1' and
             inventory['archive']['sha256'] == ARCHIVE_SHA256 and
             inventory['archive']['bytes'] == ARCHIVE_BYTES and
             len(inventory['slice_files']) == 152 and inventory['framework_file_count'] == 149 and
             _project(inventory['slice_files']) == inventory['expected_product_files'],
             'reviewed OpenSSL inventory identity differs')
    return inventory


REVIEWED_INVENTORY = _load_reviewed_inventory()
EXPECTED_PRODUCT_FILES = copy.deepcopy(REVIEWED_INVENTORY['expected_product_files'])


def _expected_ref():
    return {'identity': 'remotepairingkit', 'kind': 'remoteSourceControl',
            'location': SOURCE_REPOSITORY, 'name': 'RemotePairingKit'}


def _expected_dependency():
    return {'basedOn': None, 'packageRef': _expected_ref(),
            'state': {'checkoutState': {'branch': 'main', 'revision': SOURCE_COMMIT},
                      'name': 'sourceControlCheckout'}, 'subpath': 'RemotePairingKit'}


def _expected_artifact(packages_root):
    return {'kind': {'xcframework': {}}, 'packageRef': _expected_ref(),
            'path': str(Path(packages_root) / ARTIFACT_RELATIVE),
            'source': {'checksum': ARCHIVE_SHA256, 'type': 'remote', 'url': ARTIFACT_URL},
            'targetName': 'OpenSSL'}


def _workspace(raw, packages_root):
    _require(isinstance(raw, (str, bytes)), 'actual raw workspace-state snapshot required')
    _require(0 < len(raw) <= MAX_STATE_BYTES, 'bounded workspace-state snapshot required')
    if isinstance(raw, str):
        try:
            raw = raw.encode('utf-8')
        except UnicodeError as error:
            raise OpenSSLArtifactError('workspace-state text is not valid UTF-8') from error
    _require(0 < len(raw) <= MAX_STATE_BYTES, 'bounded workspace-state snapshot required')
    state = _json(raw)
    _require(isinstance(state, dict) and isinstance(state.get('object'), dict), 'workspace-state object missing')
    obj = state['object']
    _require(isinstance(obj.get('dependencies'), list) and isinstance(obj.get('artifacts'), list) and
             len(obj['dependencies']) <= 4096 and len(obj['artifacts']) <= 4096,
             'bounded actual dependencies and binary artifact rows required')
    for family in ('dependencies', 'artifacts'):
        _require(all(isinstance(row, dict) and isinstance(row.get('packageRef'), dict)
                     for row in obj[family]), 'malformed actual workspace row')
    dependencies = [row for row in obj['dependencies'] if row['packageRef'].get('identity') == 'remotepairingkit']
    artifacts = [row for row in obj['artifacts'] if row['packageRef'].get('identity') == 'remotepairingkit']
    expected = _expected_artifact(packages_root)
    _require(dependencies == [_expected_dependency()], 'actual RemotePairingKit source row differs')
    _require(artifacts == [expected], 'actual RemotePairingKit OpenSSL binary artifact row differs')
    _require(sum(row.get('path') == expected['path'] for row in obj['artifacts']) == 1,
             'artifact path is aliased by another workspace row')
    return {**_description(raw), 'packages_root': str(packages_root),
            'dependency': dependencies[0], 'artifact': artifacts[0]}


def _archive_inventory(raw):
    """Read the already-hashed snapshot only; never extract archive members."""
    reviewed = REVIEWED_INVENTORY
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_ARCHIVE_BYTES, 'bounded archive snapshot required')
    _require(_description(raw) == {'bytes': ARCHIVE_BYTES, 'sha256': ARCHIVE_SHA256},
             'exact reviewed OpenSSL archive bytes required')
    files, directories, metadata, links, roots, names = {}, [], {}, {}, set(), set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            _require(0 < len(members) <= MAX_MEMBERS, 'archive member count exceeded')
            for member in members:
                name = member.filename[:-1] if member.is_dir() else member.filename
                _safe_name(name)
                _require(name not in names and member.orig_filename == member.filename,
                         'duplicate or truncated archive member')
                names.add(name)
                _require(member.filename == ARCHIVE_PREFIX or member.filename.startswith(ARCHIVE_PREFIX),
                         'archive member outside exact XCFramework')
                mode = member.external_attr >> 16
                _require(member.create_system == 3 and not member.flag_bits & 1 and
                         member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and
                         0 <= member.file_size <= MAX_MEMBER_BYTES and
                         0 <= member.compress_size <= MAX_ARCHIVE_BYTES,
                         'unsupported, encrypted, or oversized archive member')
                _require(stat.S_ISDIR(mode) if member.is_dir() else stat.S_ISREG(mode) or stat.S_ISLNK(mode),
                         'archive member has unsupported file type')
                _require(not mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX), 'archive special mode forbidden')
                total += member.file_size
                _require(total <= MAX_EXPANDED_BYTES, 'archive expansion limit exceeded')
                if member.filename != ARCHIVE_PREFIX:
                    roots.add(member.filename[len(ARCHIVE_PREFIX):].split('/')[0])
                if member.is_dir():
                    _require(member.file_size == 0, 'archive directory has payload')
                    if member.filename.startswith(SLICE_PREFIX) and member.filename != SLICE_PREFIX:
                        directories.append(member.filename[len(SLICE_PREFIX):-1])
                    continue
                selected = member.filename.startswith(SLICE_PREFIX)
                is_metadata = member.filename == ARCHIVE_PREFIX + 'Info.plist' or member.filename.startswith(ARCHIVE_PREFIX + '_CodeSignature/')
                if selected or is_metadata:
                    _require(stat.S_ISREG(mode), 'selected OpenSSL slice and metadata must be ordinary files')
                    content = archive.read(member)
                    _require(len(content) == member.file_size, 'archive selected member length differs')
                    if selected:
                        files[member.filename[len(SLICE_PREFIX):]] = _description(content)
                    else:
                        metadata[member.filename[len(ARCHIVE_PREFIX):]] = _description(content)
                elif stat.S_ISLNK(mode):
                    _require(member.file_size <= 1024 and member.filename in reviewed['other_slice_links'],
                             'unreviewed archive symlink')
                    target = archive.read(member).decode('utf-8')
                    _safe_name(target)
                    links[member.filename] = target
            _require(sorted(roots) == reviewed['archive_root_names'], 'unknown archive slice or root member')
            _require(links == reviewed['other_slice_links'], 'archive nonselected slice symlinks differ')
            _require(len(members) == reviewed['archive']['member_count'] and
                     total == reviewed['archive']['expanded_bytes'], 'reviewed complete archive size inventory differs')
            _require(files == reviewed['slice_files'] and sorted(directories) == reviewed['slice_directories'],
                     'reviewed ios-arm64 ordinary-file inventory differs')
            _require(metadata == reviewed['xcframework_metadata_files'], 'reviewed XCFramework metadata differs')
            libraries = plistlib.loads(archive.read(ARCHIVE_PREFIX + 'Info.plist'))
            _require(libraries.get('CFBundlePackageType') == 'XFWK' and libraries.get('XCFrameworkFormatVersion') == '1.0' and
                     libraries.get('AvailableLibraries') == reviewed['xcframework_libraries'],
                     'reviewed XCFramework slice selection differs')
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, plistlib.InvalidFileException, KeyError) as error:
        raise OpenSSLArtifactError('invalid OpenSSL archive structure') from error
    return {'files': dict(sorted(files.items())), 'directories': sorted(directories),
            'xcframework_metadata_files': dict(sorted(metadata.items())),
            'member_count': len(members), 'expanded_bytes': total}


def _extracted_inventory(artifact_root):
    """Inspect actual selected filesystem slice, rejecting even excluded extra files."""
    reviewed = REVIEWED_INVENTORY
    _ordinary(artifact_root, directory=True)
    _require(sorted(path.name for path in artifact_root.iterdir()) == reviewed['archive_root_names'],
             'unknown extracted XCFramework slice or root member')
    for name in reviewed['archive_root_names']:
        _ordinary(artifact_root / name, directory=name != 'Info.plist')
    signatures = artifact_root / '_CodeSignature'
    _require(sorted(path.name for path in signatures.iterdir()) ==
             sorted(name.split('/')[1] for name in reviewed['xcframework_metadata_files'] if name.startswith('_CodeSignature/')),
             'extra extracted XCFramework signature metadata')
    metadata = {name: _description(_snapshot(artifact_root / name, MAX_MEMBER_BYTES))
                for name in reviewed['xcframework_metadata_files']}
    _require(metadata == reviewed['xcframework_metadata_files'], 'extracted XCFramework metadata changed')
    slice_root = _ordinary(artifact_root / 'ios-arm64', directory=True)
    files, directories = {}, []
    count = total = 0
    for parent, children, leaves in os.walk(slice_root, followlinks=False):
        for name in sorted(children + leaves):
            path = Path(parent) / name
            relative = path.relative_to(slice_root).as_posix()
            _safe_name(relative)
            count += 1
            _require(count <= MAX_MEMBERS, 'extracted slice entry limit exceeded')
            if name in children:
                _ordinary(path, directory=True)
                directories.append(relative)
            else:
                content = _snapshot(path, MAX_MEMBER_BYTES)
                total += len(content)
                _require(total <= MAX_EXPANDED_BYTES, 'extracted slice byte limit exceeded')
                files[relative] = _description(content)
    _require(files == reviewed['slice_files'] and sorted(directories) == reviewed['slice_directories'],
             'actual extracted ios-arm64 inventory differs from reviewed archive')
    return {'files': dict(sorted(files.items())), 'directories': sorted(directories),
            'xcframework_metadata_files': metadata}


def validate_source_proof(proof):
    """Require this contract's exact report; see module-level trust limitation."""
    _require(isinstance(proof, dict), 'SideStore OpenSSL source proof required')
    try:
        _require(set(proof) == {'kind', 'package', 'manifest', 'workspace', 'archive', 'artifact_path',
                               'slice', 'archive_slice_inventory', 'extracted_slice_inventory',
                               'archive_slice_directories', 'extracted_slice_directories',
                               'archive_xcframework_metadata', 'extracted_xcframework_metadata',
                               'expected_product_files', 'copy_exclusions', 'normalization', 'executed', 'archive_extracted'},
                 'unexpected or incomplete OpenSSL proof fields')
        _require(proof['kind'] == PROOF_KIND and proof['executed'] is False and
                 proof['archive_extracted'] is False and proof['normalization'] == 'none' and
                 proof['copy_exclusions'] == list(COPY_EXCLUSIONS), 'OpenSSL proof policy differs')
        package = proof['package']
        _require(package['commit'] == SOURCE_COMMIT and package['tree'] == SOURCE_TREE and
                 package['origin']['repository'] == SOURCE_REPOSITORY and
                 package['origin']['kind'] in ('direct', 'swiftpm-local-mirror'), 'OpenSSL source tuple differs')
        packages_root = Path(proof['workspace']['packages_root'])
        _require(packages_root.is_absolute() and '..' not in packages_root.parts and
                 package['path'] == str(packages_root / PACKAGE_RELATIVE) and
                 proof['artifact_path'] == str(packages_root / ARTIFACT_RELATIVE), 'OpenSSL source path binding differs')
        if package['origin']['kind'] == 'swiftpm-local-mirror':
            _require(package['origin']['commit'] == SOURCE_COMMIT and package['origin']['tree'] == SOURCE_TREE and
                     Path(package['origin']['mirror']).parent == packages_root / 'repositories', 'OpenSSL mirror binding differs')
        _require(proof['manifest'] == {'path': 'Package.swift', 'git_blob': MANIFEST_BLOB,
                                      'bytes': MANIFEST_BYTES, 'sha256': MANIFEST_SHA256}, 'OpenSSL manifest binding differs')
        workspace = proof['workspace']
        _require(workspace['dependency'] == _expected_dependency() and
                 workspace['artifact'] == _expected_artifact(packages_root) and
                 type(workspace['bytes']) is int and 0 < workspace['bytes'] <= MAX_STATE_BYTES and
                 isinstance(workspace['sha256'], str) and len(workspace['sha256']) == 64 and
                 all(char in '0123456789abcdef' for char in workspace['sha256']), 'OpenSSL workspace binding differs')
        archive = proof['archive']
        _require({key: archive[key] for key in REVIEWED_INVENTORY['archive']} == REVIEWED_INVENTORY['archive'] and
                 Path(archive['path']).is_absolute(), 'OpenSSL archive binding differs')
        _require(proof['slice'] == {'identifier': 'ios-arm64', 'platform': 'ios', 'architectures': ['arm64'],
                                   'framework_path': 'ios-arm64/OpenSSL.framework', 'framework_file_count': 149,
                                   'slice_file_count': 152}, 'OpenSSL slice binding differs')
        for key in ('archive_slice_inventory', 'extracted_slice_inventory'):
            _require(proof[key] == REVIEWED_INVENTORY['slice_files'], 'OpenSSL source slice inventory differs')
        for key in ('archive_slice_directories', 'extracted_slice_directories'):
            _require(proof[key] == REVIEWED_INVENTORY['slice_directories'], 'OpenSSL source slice directories differ')
        for key in ('archive_xcframework_metadata', 'extracted_xcframework_metadata'):
            _require(proof[key] == REVIEWED_INVENTORY['xcframework_metadata_files'], 'OpenSSL XCFramework metadata differs')
        _require(proof['expected_product_files'] == EXPECTED_PRODUCT_FILES == _project(proof['archive_slice_inventory']),
                 'OpenSSL exact copied file inventory differs')
    except (KeyError, TypeError, AttributeError) as error:
        raise OpenSSLArtifactError('incomplete OpenSSL source proof') from error
    return proof


def verify_sidestore_openssl(package_root, package_record, workspace_state_raw, packages_root, archive_path):
    """Return JSON proof from current checkout/state/archive/extracted observations.

    package_record is verify_resolution(...)["remotepairingkit"]. It is re-observed
    and compared; a stale/historical caller record cannot establish current inputs.
    archive_path must be supplied by the owned acquisition lifecycle. No downloads
    or extraction occur here; no test-only override is accepted by this public API.
    """
    packages_root = _ordinary(packages_root, directory=True)
    package_root = _ordinary(package_root, directory=True)
    _require(package_root == packages_root / PACKAGE_RELATIVE, 'exact RemotePairingKit checkout path required')
    _ordinary(package_root / '.git', directory=True)
    workspace = _workspace(workspace_state_raw, packages_root)
    try:
        actual = primitives.verify_checkout(package_root, SOURCE_COMMIT, owner='remotepairingkit')
        actual['origin'] = primitives.verify_origin(package_root, SOURCE_REPOSITORY, SOURCE_COMMIT,
                                                    resolver_root=packages_root)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise OpenSSLArtifactError('actual RemotePairingKit checkout or origin differs') from error
    _require(actual == package_record and actual['tree'] == SOURCE_TREE, 'actual source record or tree differs')
    manifest = _snapshot(package_root / 'Package.swift', 64 * 1024)
    blob = hashlib.sha1(b'blob ' + str(len(manifest)).encode() + b'\0' + manifest).hexdigest()
    _require(blob == MANIFEST_BLOB and _description(manifest) == {'bytes': MANIFEST_BYTES, 'sha256': MANIFEST_SHA256},
             'actual Package.swift manifest blob differs')
    _require(primitives.git(package_root, 'rev-parse', 'HEAD:Package.swift').decode().strip() == MANIFEST_BLOB,
             'source tree manifest object differs')
    archive_raw = _snapshot(archive_path, MAX_ARCHIVE_BYTES)
    archive = _archive_inventory(archive_raw)
    artifact_root = packages_root / ARTIFACT_RELATIVE
    extracted = _extracted_inventory(artifact_root)
    _require(archive['files'] == extracted['files'] and archive['directories'] == extracted['directories'] and
             archive['xcframework_metadata_files'] == extracted['xcframework_metadata_files'],
             'extracted source does not match reviewed archive snapshot')
    proof = {'kind': PROOF_KIND, 'package': {**actual, 'path': str(package_root)},
             'manifest': {'path': 'Package.swift', 'git_blob': blob, **_description(manifest)},
             'workspace': workspace,
             'archive': {'path': str(archive_path), **_description(archive_raw),
                         'member_count': archive['member_count'], 'expanded_bytes': archive['expanded_bytes']},
             'artifact_path': str(artifact_root),
             'slice': {'identifier': 'ios-arm64', 'platform': 'ios', 'architectures': ['arm64'],
                       'framework_path': 'ios-arm64/OpenSSL.framework', 'framework_file_count': 149, 'slice_file_count': 152},
             'archive_slice_inventory': archive['files'], 'extracted_slice_inventory': extracted['files'],
             'archive_slice_directories': archive['directories'], 'extracted_slice_directories': extracted['directories'],
             'archive_xcframework_metadata': archive['xcframework_metadata_files'],
             'extracted_xcframework_metadata': extracted['xcframework_metadata_files'],
             'expected_product_files': _project(archive['files']), 'copy_exclusions': list(COPY_EXCLUSIONS),
             'normalization': 'none', 'executed': False, 'archive_extracted': False}
    return validate_source_proof(proof)
