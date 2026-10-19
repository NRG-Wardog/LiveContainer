"""Bounded diagnostic data view of the already transported, exact failed ZIP."""
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile
import retrieve as r

MIB = 1024 * 1024
MAX_VIEW_BYTES = 64 * MIB
MAX_MEMBERS = 600000
FIXED = {
    'result.json': MIB,
    'provenance/result.json': MIB,
    'evidence-index.json': 16 * MIB,
    'logs/consumer-exact38.command.json': MIB,
    'logs/consumer-exact38.log': 16 * MIB,
    'logs/consumer-exact38.stderr.log': 16 * MIB,
    'logs/consumer-exact38.exit-code.txt': 1024,
    'logs/consumer-exact38.settlement.json': MIB,
    'provenance/consumer-tests.json': 4 * MIB,
    'consumer-nested/retention-summary.json': MIB,
}
ALLOWED = {**FIXED, **{
    'consumer-nested/' + str(n).zfill(4) + '.' + suffix: cap
    for n in range(1, 129)
    for suffix, cap in [('command.json', 65536), ('result.json', 65536),
                        ('stdout', 16 * MIB), ('stderr', 16 * MIB)]
}}


def identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def view(source, output, expected_size=r.SIZE, expected_digest=r.DIGEST):
    r.require(not output.exists() and not output.is_symlink() and output.parent.resolve() == output.parent,
              'fresh canonical view directory required')
    before = source.lstat()
    r.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == expected_size,
              'ordinary exact archive required')
    with source.open('rb') as stream:
        r.require(identity(os.fstat(stream.fileno())) == identity(before), 'archive changed before view')
        digest = hashlib.sha256(); count = 0
        for chunk in iter(lambda: stream.read(MIB), b''):
            count += len(chunk)
            r.require(count <= expected_size, 'view archive exceeded exact size')
            digest.update(chunk)
        r.require(count == expected_size and digest.hexdigest() == expected_digest,
                  'view original archive byte identity differs')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            members = archive.infolist()
            r.require(len(members) <= MAX_MEMBERS, 'archive member count bound')
            seen = set(); selected = {}; total = 0
            for member in members:
                name = member.filename
                canonical = name[:-1] if member.is_dir() else name
                r.require(member.orig_filename == name and canonical and len(name) <= 4096 and
                          '\\' not in name and ':' not in name and
                          all(ord(c) >= 32 and ord(c) != 127 for c in name) and
                          all(p not in ('', '.', '..') for p in canonical.split('/')),
                          'unsafe archive member path')
                r.require(canonical not in seen, 'duplicate archive member path')
                seen.add(canonical)
                mode = (member.external_attr >> 16) & 0xffff
                kind = stat.S_IFMT(mode)
                r.require(kind in (0, stat.S_IFDIR if member.is_dir() else stat.S_IFREG),
                          'linked or special archive member')
                if name not in ALLOWED:
                    continue
                r.require(not member.is_dir() and not member.flag_bits & 1 and
                          member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                          'ordinary unencrypted diagnostic member required')
                r.require(0 <= member.file_size <= ALLOWED[name], 'diagnostic member byte bound')
                total += member.file_size
                r.require(total <= MAX_VIEW_BYTES, 'aggregate diagnostic view byte bound')
                selected[name] = member
            output.mkdir(); rows = []
            for name, member in sorted(selected.items()):
                with archive.open(member, 'r') as entry:
                    raw = entry.read(ALLOWED[name] + 1)
                r.require(len(raw) == member.file_size and len(raw) <= ALLOWED[name],
                          'diagnostic member actual byte bound')
                # Never derive a filesystem path from a ZIP member name.
                target = 'raw-' + str(len(rows)).zfill(3) + '.bin'
                with (output / target).open('xb') as destination:
                    destination.write(raw)
                rows.append({'member': name, 'file': target, 'bytes': len(raw),
                             'sha256': hashlib.sha256(raw).hexdigest()})
        r.require(identity(os.fstat(stream.fileno())) == identity(before) and
                  identity(source.lstat()) == identity(before), 'archive changed during view')
    receipt = {
        'schema': 'p0-failed-capture-raw-view-v1', 'status': 'DIAGNOSTIC_DATA_ONLY',
        'original_run': r.RUN, 'original_attempt': r.ATTEMPT, 'original_artifact': r.ARTIFACT,
        'original_bytes': expected_size, 'original_sha256': expected_digest,
        'whole_archive_verified_before_open': True, 'archive_opened_for_data_only': True,
        'artifact_code_executed': False, 'tests_or_builds_repeated': False,
        'member_paths_used_as_output_paths': False, 'maximum_view_bytes': MAX_VIEW_BYTES,
        'raw_bytes': total, 'members': rows,
        'missing_fixed_members': sorted(set(FIXED) - set(selected)),
        'nested_counter_bound': 128, 'nested_members_present': sorted(set(selected) - set(FIXED)),
        'complete_evidence_validation': False,
    }
    (output / 'raw-view-manifest.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    return receipt


def main():
    r.require(os.environ.get('GITHUB_REPOSITORY') == r.REPOSITORY and
              os.environ.get('GITHUB_REF') == 'refs/heads/validation/p0-defensive-diagnostic-phase-b-transport',
              'exact retrieval-only branch required')
    receipt = view(Path.cwd() / 'original-artifact.zip', Path.cwd() / 'raw-view')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
