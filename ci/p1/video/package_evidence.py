#!/usr/bin/env python3
"""Package diagnostic evidence as one deterministic ZIP and bounded byte parts.

The source must be quiescent. Files are streamed, never imported or executed.
ZIP members are inspected without extraction. Packaging success is transport
integrity only; the collector's outcome and its original receipts stay separate.
Manifest authenticity must come from the separately authenticated CI artifact.
Upload manifest.json and EACH part-NNN.bin as separate CI artifacts, using
compression-level: 0. Uploading the whole directory defeats the size bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zipfile

SCHEMA = 'p1-diagnostic-evidence-package-v1'
CHUNK_SIZE = 256 * 1024 * 1024
BLOCK_SIZE = 1024 * 1024
MAX_PARTS = 64
MAX_ENTRIES = 100000
MAX_MANIFEST_SIZE = 64 * 1024 * 1024
OUTCOMES = {'success', 'failure', 'cancelled', 'skipped', 'unknown'}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class PackagingError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PackagingError(message)


def integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def safe_name(name):
    require(isinstance(name, str) and 0 < len(name) <= 4096, 'invalid evidence member name')
    require(not any(ord(c) < 32 or ord(c) == 127 or c in '\\:' for c in name), 'unsafe evidence member name')
    require(all(p not in ('', '.', '..') for p in name.split('/')), 'escaped evidence member name')
    try:
        name.encode('utf-8')
    except UnicodeError as error:
        raise PackagingError('non-UTF8 evidence member name') from error
    return name


def safe_path(path, exists=True):
    """Reject symlinks in every supplied path component, including dangling ones."""
    path = Path(path)
    require('..' not in path.parts, 'parent traversal in filesystem path')
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            require(not exists, 'missing filesystem path')
            continue
        require(not stat.S_ISLNK(mode), 'linked filesystem path')
    if exists:
        require(path.exists(), 'missing filesystem path')
    return path


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def snapshot(root):
    """Inventory without following links or silently excluding hidden evidence."""
    require(stat.S_ISDIR(root.lstat().st_mode), 'evidence source is not a directory')
    result = {'': signature(root.lstat())}

    def visit(directory):
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            name = safe_name(path.relative_to(root).as_posix())
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
                    'linked or special evidence member')
            result[name] = signature(info)
            require(len(result) <= MAX_ENTRIES + 1, 'too many evidence members')
            if stat.S_ISDIR(info.st_mode):
                visit(path)
    visit(root)
    return dict(sorted(result.items()))


def open_regular(path):
    safe_path(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'non-regular evidence file')
        stream = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    return stream


def file_identity(path):
    whole = hashlib.sha256()
    count = 0
    with open_regular(path) as stream:
        before = signature(os.fstat(stream.fileno()))
        for block in iter(lambda: stream.read(BLOCK_SIZE), b''):
            whole.update(block)
            count += len(block)
        require(signature(os.fstat(stream.fileno())) == before and count == before[3],
                'file changed during reading')
    return count, whole.hexdigest()


def zip_info(name, directory=False):
    info = zipfile.ZipInfo(name + ('/' if directory else ''), ZIP_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = ((stat.S_IFDIR | 0o755) if directory else (stat.S_IFREG | 0o644)) << 16
    if directory:
        info.external_attr |= 0x10
    return info


class BoundedWriter:
    """Let ZipFile seek to rewrite headers, but never grow beyond the size cap."""
    def __init__(self, stream, maximum):
        self.stream = stream
        self.maximum = maximum

    def write(self, data):
        require(self.stream.tell() + len(data) <= self.maximum,
                'archive exceeds bounded part count')
        return self.stream.write(data)

    def tell(self):
        return self.stream.tell()

    def seek(self, *args):
        return self.stream.seek(*args)

    def flush(self):
        return self.stream.flush()


def create_archive(source, archive, maximum=CHUNK_SIZE * MAX_PARTS):
    before = snapshot(source)
    require(sum(row[3] for row in before.values() if stat.S_ISREG(row[2])) <= maximum,
            'archive exceeds bounded part count')
    entries = []
    with archive.open('xb') as stream, zipfile.ZipFile(
            BoundedWriter(stream, maximum), 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as target:
        for name, original in before.items():
            if not name:
                continue
            if stat.S_ISDIR(original[2]):
                target.writestr(zip_info(name, True), b'')
                entries.append({'path': name, 'kind': 'directory', 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()})
                continue
            size = 0
            digest = hashlib.sha256()
            with open_regular(source / name) as incoming, target.open(zip_info(name), 'w', force_zip64=True) as outgoing:
                require(signature(os.fstat(incoming.fileno())) == original, 'source changed before packaging')
                for block in iter(lambda: incoming.read(BLOCK_SIZE), b''):
                    outgoing.write(block)
                    digest.update(block)
                    size += len(block)
                require(signature(os.fstat(incoming.fileno())) == original and size == original[3],
                        'source changed during packaging')
            entries.append({'path': name, 'kind': 'file', 'size': size, 'sha256': digest.hexdigest()})
    require(snapshot(source) == before, 'source inventory changed during packaging')
    return entries


def validate_manifest(manifest):
    keys = {'schema', 'collection_outcome', 'transport_only', 'admission_eligible',
            'ui_success_claimed', 'archive', 'entries', 'parts', 'chunk_size', 'max_parts', 'reconstruction'}
    require(isinstance(manifest, dict) and set(manifest) == keys, 'unexpected manifest fields')
    require(manifest['schema'] == SCHEMA, 'wrong manifest schema')
    require(isinstance(manifest['collection_outcome'], str) and manifest['collection_outcome'] in OUTCOMES,
            'invalid collector outcome')
    require(manifest['transport_only'] is True and manifest['admission_eligible'] is False
            and manifest['ui_success_claimed'] is False, 'packaging cannot claim UI success or admission')
    require(integer(manifest['chunk_size'], 1, CHUNK_SIZE), 'unsafe chunk size')
    require(integer(manifest['max_parts'], 1, MAX_PARTS), 'unsafe part count bound')
    archive = manifest['archive']
    require(isinstance(archive, dict) and set(archive) == {'path', 'size', 'sha256', 'format'}, 'invalid archive identity')
    require(archive['path'] == 'evidence.zip' and archive['format'] == 'zip64-stored-fixed-metadata', 'wrong archive format')
    require(integer(archive['size'], 22, manifest['chunk_size'] * manifest['max_parts'])
            and valid_sha(archive['sha256']), 'invalid archive size or SHA256')
    entries = manifest['entries']
    require(isinstance(entries, list) and len(entries) <= MAX_ENTRIES, 'invalid member index')
    previous = ''
    known = {}
    for row in entries:
        require(isinstance(row, dict) and set(row) == {'path', 'kind', 'size', 'sha256'}, 'invalid member fields')
        name = safe_name(row['path'])
        require(name > previous, 'duplicate or reordered evidence member')
        previous = name
        require(row['kind'] in ('file', 'directory') and integer(row['size'], 0, archive['size']) and valid_sha(row['sha256']), 'invalid member identity')
        if row['kind'] == 'directory':
            require(row['size'] == 0 and row['sha256'] == hashlib.sha256(b'').hexdigest(), 'invalid directory identity')
        parent = name.rpartition('/')[0]
        require(not parent or known.get(parent) == 'directory', 'missing or non-directory parent member')
        known[name] = row['kind']
    parts = manifest['parts']
    count = (archive['size'] + manifest['chunk_size'] - 1) // manifest['chunk_size']
    require(isinstance(parts, list) and len(parts) == count, 'part count differs')
    offset = 0
    for number, row in enumerate(parts):
        require(isinstance(row, dict) and set(row) == {'ordinal', 'path', 'offset', 'size', 'sha256'}, 'invalid part fields')
        require(integer(row['ordinal']) and row['ordinal'] == number
                and row['path'] == f'part-{number:03d}.bin', 'part order or path differs')
        size = min(manifest['chunk_size'], archive['size'] - offset)
        require(integer(row['offset']) and row['offset'] == offset
                and integer(row['size'], 1) and row['size'] == size and valid_sha(row['sha256']), 'part boundaries or SHA256 differ')
        offset += size
    require(isinstance(manifest['reconstruction'], str), 'invalid reconstruction instructions')
    return manifest


def read_manifest(root):
    with open_regular(root / 'manifest.json') as stream:
        data = stream.read(MAX_MANIFEST_SIZE + 1)
    require(len(data) <= MAX_MANIFEST_SIZE, 'oversized manifest')
    return validate_manifest(json.loads(data, object_pairs_hook=unique))


def verify_archive(archive, manifest):
    """Validate original file identities by reading ZIP streams, never extracting."""
    require(file_identity(archive) == (manifest['archive']['size'], manifest['archive']['sha256']),
            'reconstructed archive identity differs')
    with zipfile.ZipFile(archive, 'r') as source:
        infos = source.infolist()
        require(len(infos) == len(manifest['entries']), 'ZIP member count differs')
        for info, row in zip(infos, manifest['entries']):
            expected = zip_info(row['path'], row['kind'] == 'directory')
            require(info.filename == expected.filename and info.orig_filename == expected.filename,
                    'ZIP member order or name differs')
            require(info.date_time == ZIP_TIME and info.create_system == 3
                    and info.external_attr == expected.external_attr
                    and info.compress_type == zipfile.ZIP_STORED and not info.flag_bits & 1
                    and not info.comment, 'ZIP metadata differs')
            require(info.file_size == row['size'], 'ZIP member size differs')
            whole = hashlib.sha256()
            count = 0
            with source.open(info) as stream:
                for block in iter(lambda: stream.read(BLOCK_SIZE), b''):
                    count += len(block)
                    require(count <= row['size'], 'oversized ZIP member')
                    whole.update(block)
            require(count == row['size'] and whole.hexdigest() == row['sha256'], 'ZIP member digest differs')
        require(not source.comment, 'unexpected ZIP comment')


def join_parts(root, manifest, destination):
    require({p.name for p in root.iterdir()} == {'manifest.json', *(r['path'] for r in manifest['parts'])},
            'unexpected or missing package member')
    whole = hashlib.sha256()
    total = 0
    with destination.open('xb') as outgoing:
        for row in manifest['parts']:
            digest = hashlib.sha256()
            count = 0
            with open_regular(root / row['path']) as incoming:
                before = signature(os.fstat(incoming.fileno()))
                require(before[3] == row['size'], 'part size differs')
                for block in iter(lambda: incoming.read(BLOCK_SIZE), b''):
                    count += len(block)
                    require(count <= row['size'], 'oversized part')
                    digest.update(block)
                    whole.update(block)
                    outgoing.write(block)
                require(signature(os.fstat(incoming.fileno())) == before, 'part changed while reading')
            require(count == row['size'] and digest.hexdigest() == row['sha256'], 'part digest differs')
            total += count
    require(total == manifest['archive']['size'] and whole.hexdigest() == manifest['archive']['sha256'],
            'reconstructed archive identity differs')


def verify_package(root, destination=None):
    root = safe_path(root)
    require(root.is_dir(), 'package is not a directory')
    manifest = read_manifest(root)
    if destination is not None:
        destination = safe_path(destination, exists=False)
        require(not destination.exists(), 'fresh reconstruction destination required')
        require(not destination.is_relative_to(root), 'reconstruction must be outside the package')
        require(destination.parent.is_dir(), 'reconstruction parent missing')
    # An invalid package never publishes a partly reconstructed destination.
    parent = destination.parent if destination is not None else root.parent
    with tempfile.TemporaryDirectory(prefix='.p1-reconstruct-', dir=parent) as temporary:
        archive = Path(temporary) / 'evidence.zip'
        join_parts(root, manifest, archive)
        verify_archive(archive, manifest)
        if destination is not None:
            # Hard-link publication is atomic and refuses to overwrite a raced/stale path.
            os.link(archive, destination)
    return manifest


def package(source, output, collection_outcome='unknown', chunk_size=CHUNK_SIZE, max_parts=MAX_PARTS):
    require(isinstance(collection_outcome, str) and collection_outcome in OUTCOMES, 'invalid collector outcome')
    require(integer(chunk_size, 1, CHUNK_SIZE), 'unsafe chunk size')
    require(integer(max_parts, 1, MAX_PARTS), 'unsafe part count bound')
    source = safe_path(source)
    output = safe_path(output, exists=False)
    require(source.is_dir(), 'evidence source is not a directory')
    require(not output.exists(), 'fresh package destination required')
    require(not output.is_relative_to(source), 'package destination is inside source')
    require(output.parent.is_dir(), 'package parent missing')
    # Preflight before creating an output. Never delete or modify source evidence.
    snapshot(source)
    output.mkdir()
    with tempfile.TemporaryDirectory(prefix='.p1-package-', dir=output.parent) as temporary:
        archive = Path(temporary) / 'evidence.zip'
        entries = create_archive(source, archive, chunk_size * max_parts)
        size, sha256 = file_identity(archive)
        require(size <= chunk_size * max_parts, 'archive exceeds bounded part count')
        parts = []
        offset = 0
        with archive.open('rb') as incoming:
            while offset < size:
                number = len(parts)
                name = f'part-{number:03d}.bin'
                count = min(chunk_size, size - offset)
                remaining = count
                digest = hashlib.sha256()
                with (output / name).open('xb') as outgoing:
                    while remaining:
                        block = incoming.read(min(BLOCK_SIZE, remaining))
                        require(block, 'short generated archive')
                        outgoing.write(block)
                        digest.update(block)
                        remaining -= len(block)
                parts.append({'ordinal': number, 'path': name, 'offset': offset, 'size': count, 'sha256': digest.hexdigest()})
                offset += count
            require(not incoming.read(1), 'generated archive size changed')
        manifest = {
            'schema': SCHEMA, 'collection_outcome': collection_outcome,
            'transport_only': True, 'admission_eligible': False, 'ui_success_claimed': False,
            'archive': {'path': 'evidence.zip', 'size': size, 'sha256': sha256, 'format': 'zip64-stored-fixed-metadata'},
            'entries': entries, 'parts': parts, 'chunk_size': chunk_size, 'max_parts': max_parts,
            'reconstruction': 'Place manifest.json and all parts in one fresh directory. Run this reviewed helper with reconstruct --package DIR --output NEW.zip. It verifies ordered parts, exact ZIP bytes and all original file hashes without extraction or execution.',
        }
        validate_manifest(manifest)
        encoded = (json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('utf-8')
        require(len(encoded) <= MAX_MANIFEST_SIZE, 'oversized manifest')
        # Verify the actual chunk reconstruction and all original file bytes before
        # the final manifest becomes the completion receipt. No UI result is inferred.
        provisional = output / 'manifest.json'
        with provisional.open('xb') as stream:
            stream.write(encoded)
        try:
            verify_package(output)
        except BaseException:
            provisional.unlink()
            raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    pack = subparsers.add_parser('pack')
    pack.add_argument('--source', type=Path, required=True)
    pack.add_argument('--output', type=Path, required=True)
    pack.add_argument('--collection-outcome', choices=sorted(OUTCOMES), default='unknown')
    pack.add_argument('--chunk-size', type=int, default=CHUNK_SIZE)
    pack.add_argument('--max-parts', type=int, default=MAX_PARTS)
    for command in ('verify', 'reconstruct'):
        child = subparsers.add_parser(command)
        child.add_argument('--package', type=Path, required=True)
        if command == 'reconstruct':
            child.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'pack':
            result = package(args.source, args.output, args.collection_outcome, args.chunk_size, args.max_parts)
        else:
            result = verify_package(args.package, getattr(args, 'output', None))
        print(json.dumps({'transport_verified': True, 'archive_sha256': result['archive']['sha256'],
                          'parts': len(result['parts']), 'collection_outcome': result['collection_outcome'],
                          'admission_eligible': False, 'ui_success_claimed': False}, sort_keys=True))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        # Evidence filenames and arbitrary decoder errors may contain private data.
        message = str(error) if isinstance(error, PackagingError) else type(error).__name__
        print('Evidence packaging failed: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
