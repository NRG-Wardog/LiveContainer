"""Strict frozen-source checkpoint for this explicitly bound, pristine checkout.

Read-only. Do not use Git status/ignore rules as a filesystem inventory. Runtime
expectations come from immutable historical objects, not editable working files.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import unicodedata

UPSTREAM_COMMIT = '12377cf3b91d51739a33f14a302e5f522b238593'
FROZEN_MANIFEST_COMMIT = '6f5452fa51a4aea2103fc86d3b855bd110ec6f25'
FROZEN_MANIFEST_PATH = 'docs/migration/source-parity.json'
FROZEN_MANIFEST_SHA256 = '9754db15588b8e729362a3e03558933b94a884f28038a5cc39eb128731b43359'
INVENTORY_PATH = 'docs/migration/repository-inventory.json'
# Exact reviewed additions, never a directory/prefix/glob exemption. The frozen
# manifest above remains immutable even though later gate/docs changes are allowed.
REVIEWED_ADDITIONS = (
    'LICENSES/sidestore-auto-refresh-MIT.txt',
    'RUNTIME_SOURCE_NOTICE.md',
    'docs/migration/PATCH_TO_SOURCE.md',
    'docs/migration/RUNTIME_SOURCE_MIGRATION.md',
    'docs/migration/preparation-sidecars/combined-service-startup.json',
    'docs/migration/preparation-sidecars/lc-app-layout.json',
    'docs/migration/preparation-sidecars/v3-command-patch.json',
    'docs/migration/repository-inventory.json',
    'docs/migration/source-components.json',
    'docs/migration/source-parity.json',
    'tests/README.md',
    'tests/fixtures/app_group_identity.c',
    'tests/fixtures/cf_bundle_runtime.c',
    'tests/fixtures/cf_bundle_scan.c',
    'tests/runtime_tree_gate.py',
    'tests/test_runtime_source.py',
    'tests/test_runtime_tree_gate.py',
)


class ParityError(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise ParityError(message)


def sanitized_git_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_NO_REPLACE_OBJECTS='1',
               GIT_GRAFT_FILE=os.devnull, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1')
    return env


class BoundGit:
    def __init__(self, root):
        path = Path(root).absolute()
        require(path.is_dir() and not path.is_symlink(), 'Worktree root must be a real directory')
        self.root = path.resolve(strict=True)
        git_dir = self.root / '.git'
        require(git_dir.is_dir() and not git_dir.is_symlink(),
                'Checkpoint requires a real local .git directory, not a link or external worktree pointer')
        self.git = shutil.which('git', path=os.defpath)
        require(self.git is not None, 'Git executable unavailable')

    def run(self, *args, input=None):
        command = [self.git, '--no-replace-objects',
                   '--git-dir=' + str(self.root / '.git'), '--work-tree=' + str(self.root),
                   '-c', 'core.bare=false', '-c', 'core.filemode=true',
                   '-c', 'core.ignoreCase=false', '-c', 'core.fsmonitor=false',
                   '-c', 'core.untrackedCache=false', '-c', 'core.hooksPath=' + os.devnull,
                   *args]
        result = subprocess.run(command, cwd=self.root, env=sanitized_git_environment(),
                                input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        require(result.returncode == 0,
                'Bound Git failed for ' + repr(args) + ': ' + result.stderr.decode(errors='replace'))
        return result.stdout


@dataclass(frozen=True)
class Entry:
    mode: str
    kind: str
    oid: str


def read_tree(git, revision):
    entries = {}
    for raw in git.run('ls-tree', '-r', '-z', revision).split(b'\0'):
        if not raw:
            continue
        header, raw_path = raw.split(b'\t', 1)
        mode, kind, oid = header.decode('ascii').split(' ')
        path = raw_path.decode('utf-8')
        require(path not in entries, 'Duplicate Git tree entry: ' + path)
        entries[path] = Entry(mode, kind, oid)
    return entries


def product_expectations(git):
    manifest_bytes = git.run('show', FROZEN_MANIFEST_COMMIT + ':' + FROZEN_MANIFEST_PATH)
    require(hashlib.sha256(manifest_bytes).hexdigest() == FROZEN_MANIFEST_SHA256,
            'Frozen manifest object does not match its pinned digest')
    manifest = json.loads(manifest_bytes)
    require(manifest['upstream_commit'] == UPSTREAM_COMMIT, 'Unexpected manifest upstream identity')
    entries = read_tree(git, UPSTREAM_COMMIT)
    expected = {}
    for path, entry in entries.items():
        require(entry.mode in ('100644', '100755', '160000'), 'Unreviewed upstream type: ' + path)
        expected[path] = {'git_mode': entry.mode, 'kind': entry.kind,
                          'upstream_object': entry.oid,
                          'sha256': hashlib.sha256(git.run('cat-file', 'blob', entry.oid)).hexdigest()
                          if entry.kind == 'blob' else None}
    for record in manifest['files']:
        path = record['path']
        require(record['mode'] == '0o644', 'Unexpected frozen runtime mode: ' + path)
        expected[path] = {'git_mode': '100644', 'kind': 'blob',
                          'upstream_object': None, 'sha256': record['old_generated_sha256']}
    require(not set(expected).intersection(REVIEWED_ADDITIONS), 'Reviewed addition overlaps product inventory')
    return expected


def expected_inventory(git):
    products = product_expectations(git)
    return {
        'schema_version': 1,
        'upstream_commit': UPSTREAM_COMMIT,
        'frozen_manifest_commit': FROZEN_MANIFEST_COMMIT,
        'frozen_manifest_sha256': FROZEN_MANIFEST_SHA256,
        'policy': 'Exact tree and real filesystem inventory. No ignored/untracked extras. '
                  'All reviewed additions must be regular mode-0644 files matching HEAD and index. '
                  'Directory mode is 0755. Gitlink directories remain empty and unpopulated. '
                  'Only the real root .git administrative directory is excluded from source scanning.',
        'products': [{'path': path, **record} for path, record in sorted(products.items())],
        'reviewed_additions': [{'path': path, 'git_mode': '100644', 'filesystem_mode': '0o644',
                                'kind': 'regular', 'content_authority': 'committed HEAD and identical stage-0 index'}
                               for path in REVIEWED_ADDITIONS],
    }


def read_regular_file(path, expected_mode):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), 'Expected regular file, found substituted type: ' + str(path))
    require(stat.S_IMODE(before.st_mode) == expected_mode, 'Filesystem mode mismatch: ' + str(path))
    require(before.st_nlink == 1, 'Hard-linked file is not an independent checkout entry: ' + str(path))
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink) ==
                (before.st_dev, before.st_ino, before.st_mode, before.st_nlink),
                'File changed during parity observation: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            contents = handle.read()
    finally:
        os.close(fd)
    after = path.lstat()
    require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode, after.st_nlink) ==
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode, before.st_nlink),
            'File changed during parity observation: ' + str(path))
    return contents


def filesystem_inventory(root):
    found = {}
    folded = {'.git': '.git'}
    def walk(directory, prefix=''):
        with os.scandir(directory) as entries:
            for item in entries:
                path = prefix + item.name
                if path == '.git':
                    require(item.is_dir(follow_symlinks=False), 'Root .git must remain a real directory')
                    continue
                key = unicodedata.normalize('NFC', path).casefold()
                require(key not in folded, 'Case/Unicode-colliding path: ' + path + ' versus ' + folded.get(key, ''))
                folded[key] = path
                mode = item.stat(follow_symlinks=False).st_mode
                kind = 'directory' if stat.S_ISDIR(mode) else 'regular' if stat.S_ISREG(mode) else 'symlink' if stat.S_ISLNK(mode) else 'special'
                found[path] = (kind, stat.S_IMODE(mode))
                if kind == 'directory':
                    walk(item.path, path + '/')
    walk(root)
    return found


def verify_repository(root):
    git = BoundGit(root)
    require(git.run('rev-parse', '--is-shallow-repository').strip() == b'false',
            'Shallow history is not allowed at the source-ownership checkpoint')
    head = git.run('rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    git.run('merge-base', '--is-ancestor', UPSTREAM_COMMIT, head)
    products = product_expectations(git)
    head_tree = read_tree(git, head)
    allowed = set(products) | set(REVIEWED_ADDITIONS)
    require(set(head_tree) == allowed,
            'Committed tree inventory mismatch; extra=' + repr(sorted(set(head_tree) - allowed)) +
            '; missing=' + repr(sorted(allowed - set(head_tree))))
    index = {}
    for raw in git.run('ls-files', '--stage', '-z').split(b'\0'):
        if not raw:
            continue
        header, raw_path = raw.split(b'\t', 1)
        mode, oid, stage = header.decode().split(' ')
        path = raw_path.decode()
        require(stage == '0' and path not in index, 'Unmerged or duplicate index entry: ' + path)
        index[path] = (mode, oid)
    require(index == {path: (entry.mode, entry.oid) for path, entry in head_tree.items()},
            'Dirty index differs from committed HEAD (including additions, removals or type/mode changes)')
    for raw in git.run('ls-files', '-v', '-z').split(b'\0'):
        if raw:
            require(raw[:2] == b'H ', 'Index hiding flag is not allowed: ' + raw.decode(errors='replace'))
    expected_fs = {}
    head_contents = {}
    for path, entry in head_tree.items():
        product = products.get(path)
        expected_mode = product['git_mode'] if product else '100644'
        require(entry.mode == expected_mode, 'Git mode/type mismatch: ' + path)
        require(entry.kind == ('commit' if expected_mode == '160000' else 'blob'), 'Git entry type mismatch: ' + path)
        if product and product['upstream_object'] is not None:
            require(entry.oid == product['upstream_object'], 'Unchanged upstream object was modified: ' + path)
        if entry.kind == 'blob':
            data = git.run('cat-file', 'blob', entry.oid)
            if product:
                require(hashlib.sha256(data).hexdigest() == product['sha256'], 'Committed product content changed: ' + path)
            head_contents[path] = data
            expected_fs[path] = ('regular', 0o755 if entry.mode == '100755' else 0o644)
        else:
            expected_fs[path] = ('directory', 0o755)
        parent = Path(path).parent
        while str(parent) != '.':
            expected_fs[str(parent)] = ('directory', 0o755)
            parent = parent.parent
    actual_fs = filesystem_inventory(git.root)
    require(set(actual_fs) == set(expected_fs),
            'Filesystem inventory mismatch; extra=' + repr(sorted(set(actual_fs) - set(expected_fs))) +
            '; missing=' + repr(sorted(set(expected_fs) - set(actual_fs))))
    for path, expected in expected_fs.items():
        require(actual_fs[path] == expected, 'Filesystem type/mode mismatch: ' + path)
    for path, expected in head_contents.items():
        contents = read_regular_file(git.root / path, expected_fs[path][1])
        require(contents == expected, 'Dirty or substituted working file: ' + path)
    require(hashlib.sha256(head_contents[FROZEN_MANIFEST_PATH]).hexdigest() == FROZEN_MANIFEST_SHA256,
            'Frozen parity manifest was changed')
    require(json.loads(head_contents[INVENTORY_PATH]) == expected_inventory(git),
            'Repository inventory metadata differs from exact reviewed inventory')
    require(git.run('rev-parse', '--verify', 'HEAD^{commit}').decode().strip() == head,
            'HEAD changed during parity observation')
    return {'head': head, 'product_entries': len(products), 'reviewed_additions': len(REVIEWED_ADDITIONS),
            'regular_files': len(head_contents), 'gitlinks': sum(x.kind == 'commit' for x in head_tree.values()),
            'directory_entries': sum(kind == 'directory' for kind, mode in expected_fs.values())}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('worktree', type=Path, help='Explicit pristine checkout root')
    args = parser.parse_args()
    try:
        print(json.dumps(verify_repository(args.worktree), indent=2))
    except (ParityError, OSError, ValueError, KeyError) as error:
        parser.exit(1, 'PARITY FAILURE: ' + str(error) + '\n')
