"""Portable synthetic verifier fixtures, never a replacement capture receipt.

The small source drivers below deliberately have separate test-only hashes.
Production accepts only the four reviewed A+B driver hashes. These tests create
original-format in-memory observer files without invoking any native subprocess.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import phase_a_host_replay as h


CONTEXT = {'work': '/capture/work', 'evidence': '/capture/evidence', 'host': '/capture/host',
           'python': '/usr/bin/python3',
           'environment': {'DEVELOPER_DIR': '/Applications/Xcode_26.4.1.app/Contents/Developer',
                           'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': '/capture/work/home',
                           'TMPDIR': '/capture/work/tmp', 'PYTHONDONTWRITEBYTECODE': '1'}}
DATA = {'owners': {'AnisetteKit': {'commit': h.OWNER_COMMIT}}}


def ordinary(root, name):
    return root / name


def verify_result(driver, output):
    if driver == 'run_tests.py':
        result = h.parse(ordinary(output, 'unittest-result.json').read_bytes())
        h.exact(result['tests'], 9)
        for key in ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes'):
            h.exact(result[key], 0)
        return {'tests': 9, 'skipped': 0}
    return h.parse(ordinary(output, 'result.json').read_bytes())


GATE = types.SimpleNamespace(host_tests=types.SimpleNamespace(DRIVERS=h.DRIVERS, verify_result=verify_result))

DEBUG_TOOL_LOGS = {
    'logs/clang-version.log': (
        b'Apple clang version 21.0.0 (clang-2100.0.123.102)\n'
        b'Target: arm64-apple-darwin25.6.0\nThread model: posix\n'
        b'InstalledDir: /Applications/Xcode_26.4.1.app/Contents/Developer/'
        b'Toolchains/XcodeDefault.xctoolchain/usr/bin\n'),
    'logs/clang-version.stderr.log': b'',
    'logs/uname.log': b'Darwin synthetic-host 25.6.0 Darwin Kernel Version fixture arm64\n',
    'logs/uname.stderr.log': b'',
}


def synthetic_debug_product(target):
    dsym = target + '.dSYM'
    result = {}
    for suffix in ('', '/Contents', '/Contents/Resources', '/Contents/Resources/DWARF',
                   '/Contents/Resources/Relocations', '/Contents/Resources/Relocations/aarch64'):
        result[dsym + suffix] = h.node('directory', '0755')
    for suffix in ('/Contents/Info.plist', '/Contents/Resources/DWARF/' + Path(target).name):
        result[dsym + suffix] = h.node('file', '0644', b'SYNTHETIC_DEBUG_SIDECAR')
    raw = ("---\ntriple:          'arm64-apple-darwin'\n"
           "binary-path:     '" + target + "'\nrelocations:     []\n...\n").encode()
    result[dsym + '/Contents/Resources/Relocations/aarch64/' + Path(target).name + '.yml'] = h.node('file', '0644', raw)
    return result


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def simple_source(driver):
    """Six compile/run commands, real source reads and generated-input retention."""
    temporary = driver == 'test_elf_metadata_bounds.py'
    return ('''
from pathlib import Path
import argparse, json, os, subprocess, tempfile, shutil
p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--unicorn-include', type=Path)
p.add_argument('--disable-leak-sanitizer', action='store_true')
a = p.parse_args()
ROOT = Path(__file__).resolve().parents[2]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=True)
source = (ROOT / 'fixture.cpp').read_text()
(out / 'source-copy.cpp').write_text(source)
def variants(build):
    rows = []
    for variant, flags in [('normal', []), ('optimized', ['-O2', '-DNDEBUG']),
                           ('sanitized', ['-O1', '-g', '-fsanitize=address,undefined'])]:
        binary = build / variant
        env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                   UBSAN_OPTIONS='halt_on_error=1')
        command = [shutil.which('c++'), '-std=c++17', *flags,
                   str(out / 'source-copy.cpp'), '-o', str(binary)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=120, env=env)
        if compiled.returncode or compiled.stderr: raise RuntimeError('compile failed')
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=120, env=env)
        if result.returncode or result.stderr: raise RuntimeError('run failed')
        if json.loads(result.stdout) != {'synthetic_success': True}: raise RuntimeError('bad output')
        rows.append({'variant': variant, 'stdout': result.stdout, 'command': command})
    (out / 'rows.json').write_text(json.dumps(rows, indent=2) + '\\n')
''' + ('''
with tempfile.TemporaryDirectory(prefix='elf-metadata-unit-') as temp:
    variants(Path(temp))
''' if temporary else 'variants(out)\n') +
            '(out / "result.json").write_text(json.dumps(' + repr(h.EXPECTED_COUNTS[driver]) + ') + "\\n")\n' +
            'print("SYNTHETIC_FIXTURE_ONLY")\n').encode()


def aggregate_source():
    source = '''
from pathlib import Path
import shutil, subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[2]
class MaintainedAnisetteNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='isolated-adi-build-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        shutil.copyfile(ROOT / 'fixture.cpp', cls.build / 'main.cpp')
        cls.executable = cls.build / 'native-test'
        result = subprocess.run([shutil.which('c++'), '-std=c++17', str(cls.build / 'main.cpp'),
            '-o', str(cls.executable)], capture_output=True, text=True, timeout=60)
        if result.returncode: raise RuntimeError(result.stderr)
        if b'SYNTHETIC_COMPILED_FIXTURE_ONLY' not in cls.executable.read_bytes():
            raise RuntimeError('retained binary marker missing')
'''
    for method in h.UNIT_METHODS:
        source += ('    def ' + method + '(self):\n'
                   '        result = subprocess.run([str(self.executable), "' + method + '"], '
                   'capture_output=True, text=True, timeout=10)\n'
                   '        self.assertEqual(result.returncode, 0)\n'
                   '        self.assertEqual(result.stdout, "SYNTHETIC_OK\\n")\n'
                   '        self.assertEqual(result.stderr, "SYNTHETIC_DIAGNOSTIC\\n")\n')
    return source.encode()


class FixtureRecorder(h._Lane):
    """Test-only record generation, entirely in memory, never native execution."""
    def temporary_directory(self, suffix=None, prefix=None, dir=None, **kwargs):
        path = self.temporary + '/' + (prefix or 'tmp') + 'abcdefgh'
        self.fs.mkdir(path, mode=0o700)
        fs = self.fs
        class Temp:
            name = path
            closed = False
            def cleanup(self):
                if not self.closed:
                    fs.remove_tree(path)
                    self.closed = True
            def __enter__(self):
                return self.name
            def __exit__(self, *args):
                self.cleanup()
        return Temp()

    def emit_tree(self, root, label):
        entries = []
        for path, (kind, mode, raw) in sorted(self.fs.nodes.items()):
            if not h.inside(path, root):
                continue
            name = path[len(root):].lstrip('/')
            item = {'path': name, 'kind': kind, 'mode': mode}
            if kind == 'directory':
                self.directories += 1
            else:
                digest = h.sha(raw)
                blob = 'blobs/sha256/' + digest[:2] + '/' + digest
                header = b'blob ' + str(len(raw)).encode() + b'\0'
                item.update(label=label + ':' + name, source_path=path, length=len(raw),
                            blob_path=blob, sha256=digest,
                            git_blob_sha1=hashlib.sha1(header + raw).hexdigest(),
                            git_blob_sha256=hashlib.sha256(header + raw).hexdigest())
                self.files[self.namespace + '/' + blob] = raw
                self.blobs.add(blob)
                self.logical_files += 1
                self.logical_bytes += len(raw)
            entries.append(item)
        return {'kind': 'filesystem-tree', 'source_path': root, 'label': label, 'entries': entries}

    def emit_snapshot(self, phase):
        label = f'{self.count:04d}'
        value = {name: self.emit_tree(root, label + '/' + phase + '/' + name)
                 for name, root in (('temporary', self.temporary), ('output', self.output))}
        self.files[self.namespace + '/' + label + '.' + phase + '.json'] = encode(value)

    def run(self, *args, **kwargs):
        self.count += 1
        argv = [str(value) for value in args[0]]
        environment = kwargs.get('env') or self.environment
        row = {'argv': argv, 'cwd': self.work,
               'environment': {key: environment[key] for key in h.SAFE_ENV if key in environment},
               'returncode': None}
        prefix = self.namespace + '/' + f'{self.count:04d}'
        self.files[prefix + '.command.json'] = encode(row)
        self.files[prefix + '.result.json'] = encode({**row, 'returncode': 0})
        self.emit_snapshot('before')
        if '-o' in argv:
            raw = b'SYNTHETIC_COMPILED_FIXTURE_ONLY:' + argv[-1].encode()
            self.fs.nodes[argv[-1]] = h.node('file', '0755', raw)
            if '-g' in argv:
                self.fs.nodes.update(synthetic_debug_product(argv[-1]))
            stdout = stderr = b''
        elif self.driver == 'run_tests.py':
            stdout, stderr = b'SYNTHETIC_OK\n', b'SYNTHETIC_DIAGNOSTIC\n'
        else:
            stdout, stderr = b'{"synthetic_success": true}\n', b''
        self.files[prefix + '.stdout'] = stdout
        self.files[prefix + '.stderr'] = stderr
        self.emit_snapshot('after')
        return types.SimpleNamespace(returncode=0, stdout=stdout.decode(), stderr=stderr.decode())

    def complete(self):
        self.files[self.namespace + '/final-output.json'] = encode(self.emit_tree(self.output, 'final-output'))
        self.files[self.namespace + '/retention-summary.json'] = encode({
            'format': 'p0defensive-raw-store-v1', 'hash': 'sha256',
            'logical_files': self.logical_files, 'logical_bytes': self.logical_bytes,
            'directories': self.directories, 'unique_blobs': len(self.blobs),
            'limits': h.BOUNDS, 'nested_commands': self.count})
        self.files['provenance/host-' + self.label + '.json'] = encode(h.EXPECTED_COUNTS[self.driver])
        self.files['logs/host-' + self.label + '.log'] = self.printed.getvalue().encode()


class HostReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='phase-a-offline-replay-unit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / '.ci/native-tests'
        scripts.mkdir(parents=True)
        (self.root / 'fixture.cpp').write_text('// Explicitly synthetic verifier test input.\n')
        self.sources = {driver: aggregate_source() if driver == 'run_tests.py' else simple_source(driver)
                        for driver in h.DRIVERS}
        self.hashes = {driver: h.sha(raw) for driver, raw in self.sources.items()}
        for driver, raw in self.sources.items():
            (scripts / driver).write_bytes(raw)
        self.patch = mock.patch.dict(h.DRIVER_SHA256, self.hashes)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.files = dict(DEBUG_TOOL_LOGS)
        for driver in h.DRIVERS:
            lane = FixtureRecorder(self.files, driver, self.root, CONTEXT, self.raw_record)
            lane.execute()
            lane.complete()

    def raw_record(self, record, namespace=''):
        raw = self.files[namespace + '/' + record['blob_path']]
        self.assertIs(type(record['length']), int)
        h.require(len(raw) == record['length'] and h.sha(raw) == record['sha256'], 'raw length/hash mismatch')
        h.require(record['blob_path'] == 'blobs/sha256/' + record['sha256'][:2] + '/' + record['sha256'],
                  'noncanonical raw blob path')
        header = b'blob ' + str(len(raw)).encode() + b'\0'
        h.require(hashlib.sha1(header + raw).hexdigest() == record['git_blob_sha1'] and
                  hashlib.sha256(header + raw).hexdigest() == record['git_blob_sha256'], 'raw Git object mismatch')
        return raw

    def verify(self, **kwargs):
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess must never run')):
            return h.verify_host_lanes(self.files, kwargs.get('data', DATA), kwargs.get('gate', GATE),
                                       {'AnisetteKit': self.root}, kwargs.get('context', CONTEXT), self.raw_record)

    def mutate_json(self, path, function):
        value = h.parse(self.files[path])
        function(value)
        self.files[path] = encode(value)

    def bad(self, function):
        saved = dict(self.files)
        try:
            function()
            with self.assertRaises((ValueError, KeyError, UnicodeError, AssertionError)):
                self.verify()
        finally:
            self.files = saved

    def test_four_lane_replay_exact_new_counts_without_any_subprocess(self):
        report = self.verify()
        self.assertEqual(report['status'], 'VERIFIED_ORIGINAL_HOST_REPLAY')
        self.assertEqual((report['memory_assertions'], report['setup_assertions'], report['metadata_assertions'],
                          report['aggregate_tests']), (1209, 717, 2139, 9))
        self.assertEqual(report['nested_commands'], 28)  # Synthetic fixture; never an asserted production count.
        self.assertEqual(report['lanes']['run-tests']['nested_commands'], 10)
        self.assertFalse(report['native_execution_performed'])
        self.assertFalse(report['archive_extracted'])
        self.assertFalse(report['source_mutated'])
        self.assertEqual(len(report['lanes']['run-tests']['test_ids']), 9)
        for name, raw in self.sources.items():
            self.assertEqual((self.root / '.ci/native-tests' / name).read_bytes(), raw)

    def test_requires_all_four_exact_lanes_and_published_new_owner(self):
        for driver in h.DRIVERS:
            namespace = 'host-tests/' + driver.removesuffix('.py').replace('_', '-') + '/'
            self.bad(lambda: [self.files.pop(name) for name in list(self.files) if name.startswith(namespace)])
        self.bad(lambda: self.files.__setitem__('host-tests/unreviewed/0001.stdout', b''))
        self.bad(lambda: self.files.__setitem__('host-tests/foreign', b''))
        with self.assertRaises(ValueError):
            self.verify(data={'owners': {'AnisetteKit': {'commit': 'a' * 40}}})

    def test_source_hash_pin_precedes_python_execution(self):
        path = self.root / '.ci/native-tests' / h.DRIVERS[0]
        path.write_bytes(path.read_bytes() + b'\nraise RuntimeError("unreviewed source executed")\n')
        with self.assertRaisesRegex(ValueError, 'owner driver differs'):
            self.verify()

    def test_every_numbered_command_and_stream_is_required(self):
        prefix = 'host-tests/test-memory-boundaries-host/'
        for suffix in ('.command.json', '.result.json', '.before.json', '.after.json', '.stdout', '.stderr'):
            for number in (1, 2, 6):
                with self.subTest(suffix=suffix, number=number):
                    self.bad(lambda: self.files.pop(prefix + f'{number:04d}' + suffix))
        self.bad(lambda: self.files.__setitem__(prefix + '0007.command.json', self.files[prefix + '0001.command.json']))
        self.bad(lambda: self.files.__setitem__(prefix + '0000.stderr', b''))

    def test_argv_order_cwd_and_environment_are_source_derived(self):
        key = 'host-tests/test-vm-setup-host/0001.command.json'
        mutations = [lambda row: row['argv'].reverse(),
                     lambda row: row['argv'].append('--unreviewed'),
                     lambda row: row.__setitem__('cwd', '/other'),
                     lambda row: row['environment'].__setitem__('PATH', '/attacker/bin'),
                     lambda row: row['environment'].__setitem__('TMPDIR', '/tmp'),
                     lambda row: row['environment'].__setitem__('ASAN_OPTIONS', 'detect_leaks=1'),
                     lambda row: row['environment'].__setitem__('DYLD_INSERT_LIBRARIES', '/evil'),
                     lambda row: row.__setitem__('returncode', 0),
                     lambda row: row.__setitem__('extra', True)]
        for mutate in mutations:
            self.bad(lambda: self.mutate_json(key, mutate))

    def test_result_must_be_settled_zero_integer_and_same_identity(self):
        key = 'host-tests/test-memory-boundaries-host/0002.result.json'
        for value in (False, None, 1, -9, '0'):
            self.bad(lambda: self.mutate_json(key, lambda row: row.__setitem__('returncode', value)))
        self.bad(lambda: self.mutate_json(key, lambda row: row.__setitem__('error', 'TimeoutExpired')))
        self.bad(lambda: self.mutate_json(key, lambda row: row['argv'].append('unreviewed')))

    def test_source_generated_before_inputs_cannot_be_replaced(self):
        key = 'host-tests/test-memory-boundaries-host/0001.before.json'
        for field, value in (('source_path', '/wrong/source-copy.cpp'), ('label', 'wrong'),
                             ('mode', '0755'), ('path', '../escape.cpp'), ('kind', 'symlink')):
            self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'][1].__setitem__(field, value)))
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'].pop()))

    def test_before_and_after_tree_closure_and_continuity(self):
        before = 'host-tests/test-memory-boundaries-host/0002.before.json'
        after = 'host-tests/test-memory-boundaries-host/0002.after.json'
        self.bad(lambda: self.mutate_json(before, lambda row: row['output']['entries'].reverse()))
        self.bad(lambda: self.mutate_json(after, lambda row: row['output']['entries'].pop()))
        self.bad(lambda: self.mutate_json(after, lambda row: row['output']['entries'].append(
            {'path': 'unreviewed', 'kind': 'directory', 'mode': '0755'})))
        self.bad(lambda: self.mutate_json(before, lambda row: row['output']['entries'].append(row['output']['entries'][0])))
        self.bad(lambda: self.mutate_json(after, lambda row: row['output']['entries'][1].__setitem__('mode', '0644')))

    def test_compiler_product_must_be_fresh_retained_and_executable(self):
        key = 'host-tests/test-memory-boundaries-host/0001.after.json'
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'].pop(1)))
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'][1].__setitem__('mode', '0644')))
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'].append(
            {'path': 'unrequested.dSYM', 'kind': 'directory', 'mode': '0755'})))

    def test_original_raw_bytes_hashes_lengths_and_blob_closure(self):
        namespace = 'host-tests/test-memory-boundaries-host/'
        blob = next(name for name in self.files if name.startswith(namespace + 'blobs/'))
        self.bad(lambda: self.files.__setitem__(blob, b'REPLACED'))
        self.bad(lambda: self.files.pop(blob))
        self.bad(lambda: self.files.__setitem__(namespace + 'blobs/sha256/00/' + '0' * 64, b'extra'))
        key = namespace + '0001.before.json'
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'][1].__setitem__('length', 1)))
        self.bad(lambda: self.mutate_json(key, lambda row: row['output']['entries'][1].__setitem__('git_blob_sha1', '0' * 40)))

    def test_original_stdout_stderr_and_unittest_assertions_are_replayed(self):
        key = 'host-tests/test-memory-boundaries-host/0002.stdout'
        self.bad(lambda: self.files.__setitem__(key, b'{"synthetic_success": false}\n'))
        self.bad(lambda: self.files.__setitem__('host-tests/test-vm-setup-host/0001.stderr', b'diagnostic'))
        self.bad(lambda: self.files.__setitem__('host-tests/run-tests/0002.stdout', b'WRONG\n'))
        self.bad(lambda: self.files.__setitem__('host-tests/run-tests/0002.stderr', b'WRONG\n'))
        self.bad(lambda: self.files.__setitem__('logs/host-test-memory-boundaries-host.log', b'forged stdout'))

    def test_final_files_and_nested_accounting_are_recomputed(self):
        key = 'host-tests/test-memory-boundaries-host/final-output.json'
        self.bad(lambda: self.mutate_json(key, lambda row: row['entries'].pop()))
        self.bad(lambda: self.mutate_json(key, lambda row: row.__setitem__('source_path', '/other')))
        summary = 'host-tests/test-memory-boundaries-host/retention-summary.json'
        for field in ('logical_files', 'logical_bytes', 'directories', 'unique_blobs', 'nested_commands'):
            self.bad(lambda: self.mutate_json(summary, lambda row: row.__setitem__(field, row[field] + 1)))
        self.bad(lambda: self.mutate_json(summary, lambda row: row['limits'].__setitem__('files', 999999)))
        self.bad(lambda: self.mutate_json('provenance/host-test-memory-boundaries-host.json',
                                         lambda row: row.__setitem__('assertions', 208)))

    def test_temporary_directory_name_scope_and_generated_inputs_are_bound(self):
        key = 'host-tests/test-elf-metadata-bounds/0001.before.json'
        self.bad(lambda: self.mutate_json(key, lambda row: row['temporary']['entries'][1].__setitem__('path', '../escape')))
        self.bad(lambda: self.mutate_json(key, lambda row: row['temporary']['entries'][1].__setitem__('path', 'tmpabcdefgh')))
        self.bad(lambda: self.mutate_json(key, lambda row: row['temporary']['entries'][1].__setitem__('mode', '0755')))

    def test_json_duplicate_nonfinite_and_boolean_count_rejection(self):
        key = 'host-tests/test-memory-boundaries-host/0001.command.json'
        self.bad(lambda: self.files.__setitem__(key, b'{"argv":[],"argv":[]}'))
        self.bad(lambda: self.files.__setitem__(key, b'{"x":NaN}'))
        self.bad(lambda: self.mutate_json('provenance/host-test-memory-boundaries-host.json',
                                         lambda row: row.__setitem__('engine_starts', False)))

    def test_virtual_filesystem_denies_real_writes_and_unapproved_source_reads(self):
        fs = h._VirtualFS(self.root, '/captured/source', ('/owned/out', '/owned/tmp'), '/owned')
        for path in ('/captured/source/fixture.cpp', '/etc/passwd', '/owned/out/../escape'):
            with self.assertRaises(ValueError):
                fs.Path(path).write_text('must not be written')
        with self.assertRaises(ValueError):
            fs.Path('/etc/passwd').read_bytes()
        with self.assertRaises(ValueError):
            fs.Path('/captured/source/.git/config').read_bytes()
        self.assertEqual(fs.Path('/captured/source/fixture.cpp').read_bytes(),
                         (self.root / 'fixture.cpp').read_bytes())

    def test_original_crlf_streams_use_exact_observer_text_normalization(self):
        for key in ('host-tests/test-memory-boundaries-host/0002.stdout',
                    'host-tests/run-tests/0002.stderr'):
            self.files[key] = self.files[key].replace(b'\n', b'\r\n')
        self.assertEqual(self.verify()['aggregate_tests'], 9)

    def debug_fixture(self):
        lane = h._Lane(self.files, h.DRIVERS[0], self.root, CONTEXT, self.raw_record)
        lane.count = 1
        self.files.update(DEBUG_TOOL_LOGS)
        before = dict(lane.fs.nodes)
        target = lane.output + '/memory-sanitized'
        dsym = target + '.dSYM'
        after = {**before, target: h.node('file', '0755', b'SYNTHETIC_PRODUCT')}
        after.update(synthetic_debug_product(target))
        relocation = dsym + '/Contents/Resources/Relocations/aarch64/memory-sanitized.yml'
        return lane, before, after, ['/usr/bin/c++', '-g', '-o', target], relocation

    def test_darwin_debug_sidecars_have_exact_source_derived_product_closure(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        lane._compiled_products(before, after, argv)
        self.assertEqual(len(lane.products[0]['sidecar_files']), 3)
        self.assertIn(relocation, lane.products[0]['sidecar_files'])
        for bad, command in (({**after, argv[-1] + '.dSYM/extra': h.node('file', '0644', b'extra')}, argv),
                             ({key: value for key, value in after.items() if not key.endswith('Info.plist')}, argv),
                             (after, ['/usr/bin/c++', '-o', argv[-1]]),
                             ({**after, argv[-1]: h.node('file', '0644', b'product')}, argv)):
            with self.assertRaises(ValueError):
                lane._compiled_products(before, bad, command)

    def test_complete_dsym_tree_cannot_be_deleted_from_sanitized_debug_lane(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        without = {key: value for key, value in after.items() if '.dSYM' not in key}
        with self.assertRaisesRegex(ValueError, 'missing or unrequested'):
            lane._compiled_products(before, without, argv)

    def test_dsym_relocation_aliases_and_arbitrary_architectures_are_rejected(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        for spelling in ('arm64', 'x86_64', 'aarch64-extra', '../aarch64'):
            alias = {key.replace('/Relocations/aarch64', '/Relocations/' + spelling): value
                     for key, value in after.items()}
            for bad in (alias, {**after, **alias}):
                with self.subTest(spelling=spelling), self.assertRaises(ValueError):
                    lane._compiled_products(before, bad, argv)

    def test_dsym_relocation_is_single_required_ordinary_file(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        for bad in ({key: value for key, value in after.items() if key != relocation},
                    {**after, relocation: h.node('symlink', '0644', b'target')},
                    {**after, relocation: h.node('file', '0755', after[relocation][2])},
                    {**after, relocation + '.extra': after[relocation]}):
            with self.assertRaises(ValueError):
                lane._compiled_products(before, bad, argv)

    def test_dsym_relocation_yaml_triple_binary_and_empty_list_are_exact(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        raw = after[relocation][2]
        for bad in (raw.replace(b'arm64-apple-darwin', b'aarch64-apple-darwin'),
                    raw.replace(b'arm64-apple-darwin', b'x86_64-apple-darwin'),
                    raw.replace(argv[-1].encode(), b'/different/binary'),
                    raw.replace(b'[]', b'[foreign]'), raw + b'triple: duplicated\n',
                    raw.replace(b'\n', b'\r\n'), b''):
            with self.assertRaises(ValueError):
                lane._compiled_products(before, {**after, relocation: h.node('file', '0644', bad)}, argv)

    def test_dsym_requires_matching_captured_clang_and_host_target(self):
        lane, before, after, argv, relocation = self.debug_fixture()
        for name, bad in (
                ('logs/clang-version.log', self.files['logs/clang-version.log'].replace(b'arm64', b'x86_64')),
                ('logs/clang-version.log', self.files['logs/clang-version.log'].replace(b'25.6.0', b'26.0.0')),
                ('logs/clang-version.log', self.files['logs/clang-version.log'].replace(b'21.0.0', b'22.0.0')),
                ('logs/clang-version.stderr.log', b'diagnostic'),
                ('logs/uname.log', self.files['logs/uname.log'].replace(b'arm64', b'x86_64')),
                ('logs/uname.log', b'Linux fake arm64\n'),
                ('logs/uname.stderr.log', b'diagnostic')):
            original = self.files[name]
            try:
                self.files[name] = bad
                with self.subTest(name=name), self.assertRaises(ValueError):
                    lane._compiled_products(before, after, argv)
                del self.files[name]
                with self.assertRaises(ValueError):
                    lane._compiled_products(before, after, argv)
            finally:
                self.files[name] = original

    def test_aggregate_test_id_inventory_cannot_skip_or_replace_any_case(self):
        path = self.root / '.ci/native-tests/run_tests.py'
        altered = self.sources['run_tests.py'].replace(h.UNIT_METHODS[0].encode(), b'test_unreviewed_replacement')
        path.write_bytes(altered)
        with mock.patch.dict(h.DRIVER_SHA256, {'run_tests.py': h.sha(altered)}):
            with self.assertRaisesRegex(ValueError, 'exact nine source-derived host test IDs'):
                self.verify()

    def test_virtual_driver_imports_do_not_expose_network_or_process_modules(self):
        driver = h.DRIVERS[0]
        path = self.root / '.ci/native-tests' / driver
        altered = b'import socket\n' + self.sources[driver]
        path.write_bytes(altered)
        with mock.patch.dict(h.DRIVER_SHA256, {driver: h.sha(altered)}):
            with self.assertRaisesRegex(ValueError, 'unreviewed Python driver import'):
                self.verify()

    def test_owner_source_symlinks_and_changes_during_replay_are_rejected(self):
        fs = h._VirtualFS(self.root, '/captured/source', ('/owned/out', '/owned/tmp'), '/owned')
        path = fs.Path('/captured/source/fixture.cpp')
        original = path.read_bytes()
        (self.root / 'fixture.cpp').write_bytes(original + b'// changed\n')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            path.read_bytes()
        (self.root / 'fixture.cpp').unlink()
        (self.root / 'fixture.cpp').symlink_to(self.root / '.ci/native-tests/run_tests.py')
        with self.assertRaisesRegex(ValueError, 'linked owner'):
            path.read_bytes()


if __name__ == '__main__':
    unittest.main()
