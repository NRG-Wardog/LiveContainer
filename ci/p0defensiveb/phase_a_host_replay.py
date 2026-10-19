"""Read-only replay of the four frozen defensive diagnostic host-observer lanes.

Only the hash-pinned, reviewed Python drivers are evaluated. Their filesystem,
temporary-directory, compiler discovery, environment and subprocess interfaces
are in-memory substitutes. No archive path is extracted, no compiler or retained
binary is run, and no source/work/evidence path is written. The caller must first
verify the archive identity, frozen adapter, original raw store and owner Git
source closure. This module is not a substitute for those admission checks.
"""
import argparse
import builtins
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import types
import unittest


DRIVERS = ('test_memory_boundaries_host.py', 'test_vm_setup_host.py',
           'test_elf_metadata_bounds.py', 'run_tests.py')
OWNER_COMMIT = '227dfd8c8456cd62e4ceff4971b17afb2003d7e8'
DRIVER_SHA256 = {
    'test_memory_boundaries_host.py': 'ed012b6a39481b8019509995dc19eac307852d173f6a31b1de118a50409c470d',
    'test_vm_setup_host.py': 'dfe5779e9a185ecb7fcc9e5c3987161e7525dd029863b59835f5ae3b7d4cf58f',
    'test_elf_metadata_bounds.py': '6a601417c24df2a267e3a782affcd1fefcd41b18301ed6073299be33e2b643ac',
    'run_tests.py': 'bef358632139cf3296715b8f3c98cdf385bdaa6f711ffb847d92504293cd8980',
}
UNIT_METHODS = (
    'test_fresh_provisioning_constructor_failure_is_correlated_and_redacted',
    'test_actual_native_boundary_success_faults_and_concurrent_calls',
    'test_normal_checked_staging_blocks_otp_and_preserves_previous_blob_on_every_io_failure',
    'test_constructor_diagnostic_reaches_actual_json_boundary_and_preserves_poison',
    'test_native_trace_is_bounded_and_can_be_disabled_without_changing_results',
    'test_actual_loader_lifetime_and_read_only_callbacks',
    'test_actual_consumer_hooks_observe_without_changing_results',
    'test_actual_swift_consumer_decoder_rejects_private_or_malformed_values',
    'test_swift_and_native_metadata_allowlists_are_identical',
)
SAFE_ENV = ('DEVELOPER_DIR', 'PATH', 'HOME', 'TMPDIR', 'ASAN_OPTIONS',
            'UBSAN_OPTIONS', 'PYTHONDONTWRITEBYTECODE')
BASE_ENV = {'DEVELOPER_DIR', 'PATH', 'HOME', 'TMPDIR', 'PYTHONDONTWRITEBYTECODE'}
BOUNDS = {'file_bytes': 536870912, 'total_bytes': 8589934592, 'files': 100000,
          'directories': 20000, 'path_bytes': 4096, 'depth': 128,
          'symlink_hops': 32, 'git_output_bytes': 33554432}
EXPECTED_COUNTS = {
    'test_memory_boundaries_host.py': {'assertions': 1209, 'guest_execution': False, 'engine_starts': 0},
    'test_vm_setup_host.py': {'assertions': 717, 'guest_execution': False, 'engine_starts': 0},
    'test_elf_metadata_bounds.py': {'assertions': 2139, 'guest_execution': False},
    'run_tests.py': {'tests': 9, 'skipped': 0},
}
RECORD_KEYS = {'path', 'kind', 'mode', 'label', 'source_path', 'length',
               'blob_path', 'sha256', 'git_blob_sha1', 'git_blob_sha256'}


def require(value, message):
    if not value:
        raise ValueError('Phase A host replay: ' + message)


def exact(actual, expected, message='exact value/type differs'):
    require(type(actual) is type(expected) and actual == expected, message)
    if isinstance(expected, dict):
        for key in expected:
            exact(actual[key], expected[key], message)
    elif isinstance(expected, (list, tuple)):
        for left, right in zip(actual, expected):
            exact(left, right, message)


def parse(raw):
    require(isinstance(raw, (bytes, str)) and len(raw) <= 64 * 1024 * 1024,
            'bounded original JSON required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('Phase A host replay: nonfinite JSON ' + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def absolute(value):
    require(type(value) is str and value.startswith('/') and '\\' not in value and
            '\0' not in value and len(value.encode()) <= BOUNDS['path_bytes'] and
            str(PurePosixPath(value)) == value and
            all(part not in ('.', '..', '') for part in value.split('/')[1:]),
            'noncanonical captured absolute path')
    return value


def relative(value):
    require(type(value) is str and value and not value.startswith('/') and
            '\\' not in value and '\0' not in value and
            len(value.encode()) <= BOUNDS['path_bytes'] and
            all(part not in ('', '.', '..') for part in value.split('/')) and
            len(value.split('/')) <= BOUNDS['depth'], 'unsafe retained relative path')
    return value


def inside(path, root):
    return path == root or path.startswith(root + '/')


def node(kind, mode, raw=None):
    return (kind, mode, raw)


class _VirtualFS:
    """A deliberately small Path implementation; all writes are memory-only."""
    def __init__(self, source_root, captured_source, owned_roots, cwd):
        self.source_root = Path(source_root)
        self.captured_source = absolute(captured_source)
        self.owned_roots = tuple(absolute(value) for value in owned_roots)
        self.cwd = absolute(cwd)
        self.nodes = {value: node('directory', '0755') for value in self.owned_roots}
        self.source_reads = {}
        fs = self

        class VirtualPath(PurePosixPath):
            def resolve(self, strict=False):
                return type(self)(fs.key(self))

            def absolute(self):
                return self.resolve()

            def read_bytes(self):
                return fs.read(self)

            def read_text(self, encoding=None, errors=None):
                require(encoding in (None, 'utf-8') and errors in (None, 'strict'),
                        'unexpected source text encoding')
                return fs.read(self).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')

            def write_bytes(self, raw):
                require(type(raw) is bytes, 'virtual write must be bytes')
                fs.write(self, raw)
                return len(raw)

            def write_text(self, text, encoding=None, errors=None, newline=None):
                require(type(text) is str and encoding in (None, 'utf-8') and
                        errors in (None, 'strict') and newline is None,
                        'unexpected generated text encoding')
                fs.write(self, text.encode('utf-8'))
                return len(text)

            def mkdir(self, mode=0o777, parents=False, exist_ok=False):
                fs.mkdir(self, mode, parents, exist_ok)

            def is_file(self):
                key = fs.key(self)
                return ((key in fs.nodes and fs.nodes[key][0] == 'file') or
                        (inside(key, fs.captured_source) and fs.source_path(key).is_file()))

            def is_dir(self):
                key = fs.key(self)
                return ((key in fs.nodes and fs.nodes[key][0] == 'directory') or
                        (inside(key, fs.captured_source) and fs.source_path(key).is_dir()))

            def exists(self):
                return self.is_file() or self.is_dir()

            def is_symlink(self):
                return False  # All local source reads and captured entries reject links.

        self.Path = VirtualPath

    def key(self, path):
        value = str(path)
        if not value.startswith('/'):
            value = self.cwd + '/' + value
        return absolute(value)

    def source_path(self, key):
        require(inside(key, self.captured_source), 'read escaped verified owner source')
        result = self.source_root
        require(not result.is_symlink(), 'linked owner source root')
        suffix = key[len(self.captured_source):].lstrip('/')
        for part in suffix.split('/') if suffix else ():
            require(part != '.git', 'driver read from Git internals')
            result = result / part
            require(not result.is_symlink(), 'linked owner compiler input')
        return result

    def read(self, path):
        key = self.key(path)
        if key in self.nodes:
            require(self.nodes[key][0] == 'file', 'virtual read is not an ordinary file')
            return self.nodes[key][2]
        target = self.source_path(key)
        require(target.is_file() and target.stat().st_size <= BOUNDS['git_output_bytes'],
                'missing/oversized verified owner input')
        raw = target.read_bytes()
        require(key not in self.source_reads or self.source_reads[key] == raw,
                'owner source changed during replay')
        self.source_reads[key] = raw
        return raw

    def writable(self, path):
        key = self.key(path)
        require(any(inside(key, root) for root in self.owned_roots),
                'driver write escaped virtual temporary/output roots')
        return key

    def write(self, path, raw):
        key = self.writable(path)
        require(len(raw) <= BOUNDS['file_bytes'] and
                self.nodes.get(str(PurePosixPath(key).parent), (None,))[0] == 'directory',
                'virtual generated file has no parent or exceeds bound')
        old = self.nodes.get(key)
        require(old is None or old[0] == 'file', 'virtual file replaced directory')
        self.nodes[key] = node('file', old[1] if old else '0644', raw)

    def mkdir(self, path, mode=0o777, parents=False, exist_ok=False):
        key = self.writable(path)
        require(mode in (0o777, 0o700), 'unreviewed virtual directory mode')
        if key in self.nodes:
            require(exist_ok and self.nodes[key][0] == 'directory', 'virtual directory already exists')
            return
        parent = str(PurePosixPath(key).parent)
        if parent not in self.nodes and parents:
            self.mkdir(parent, parents=True, exist_ok=True)
        require(self.nodes.get(parent, (None,))[0] == 'directory', 'virtual directory has no parent')
        self.nodes[key] = node('directory', '0700' if mode == 0o700 else '0755')

    def remove_tree(self, path):
        key = self.writable(path)
        require(key not in self.owned_roots, 'cannot remove a virtual owned root')
        for current in tuple(self.nodes):
            if inside(current, key):
                del self.nodes[current]


class _Lane:
    def __init__(self, files, driver, source_root, context, raw_record):
        require(driver in DRIVERS, 'unreviewed host driver')
        self.files, self.driver, self.raw_record = files, driver, raw_record
        self.label = driver.removesuffix('.py').replace('_', '-')
        self.namespace = 'host-tests/' + self.label
        self.work = absolute(context['work'])
        self.output = self.work + '/host-tests/' + self.label
        self.temporary = self.work + '/host-temporary/' + self.label
        self.owner = self.work + '/sources/AnisetteKit'
        self.environment = dict(context['environment'])
        require(set(self.environment) == BASE_ENV and all(type(v) is str for v in self.environment.values()),
                'captured base environment differs')
        self.environment['TMPDIR'] = self.temporary
        self.fs = _VirtualFS(source_root, self.owner, (self.temporary, self.output), self.work)
        self.count = 0
        self.logical_files = self.logical_bytes = self.directories = 0
        self.blobs = set()
        self.products = []
        self.commands = []
        self.printed = io.StringIO()
        self.unit_ids = []

    def read(self, name):
        key = self.namespace + '/' + relative(name)
        require(key in self.files, 'missing original nested file: ' + key)
        raw = self.files[key]
        require(type(raw) is bytes, 'nested file must contain original bytes: ' + key)
        return raw

    def tree(self, row, root, label):
        require(type(row) is dict and set(row) == {'kind', 'label', 'source_path', 'entries'} and
                row['kind'] == 'filesystem-tree' and row['source_path'] == root and
                row['label'] == label and type(row['entries']) is list and
                len(row['entries']) <= BOUNDS['files'] + BOUNDS['directories'],
                'retained host tree identity/schema differs')
        result = {}
        names = []
        seen = set()
        for item in row['entries']:
            require(type(item) is dict and type(item.get('path')) is str, 'malformed tree entry')
            name = item['path']
            if name:
                relative(name)
            require(name not in seen, 'duplicate retained host entry')
            seen.add(name)
            names.append(name)
            key = root + ('/' + name if name else '')
            mode = item.get('mode')
            require(type(mode) is str and re.fullmatch('0[0-7]{3}', mode), 'unsafe host file mode')
            if item.get('kind') == 'directory':
                require(set(item) == {'path', 'kind', 'mode'} and mode in ('0700', '0755'),
                        'unexpected retained directory metadata')
                result[key] = node('directory', mode)
                self.directories += 1
            else:
                require(set(item) == RECORD_KEYS and item['kind'] == 'file' and name and
                        item['source_path'] == key and item['label'] == label + ':' + name and
                        mode in ('0600', '0644', '0700', '0755'), 'unexpected retained file/link metadata')
                raw = self.raw_record(item, namespace=self.namespace)
                require(type(raw) is bytes, 'raw reader did not return original bytes')
                result[key] = node('file', mode, raw)
                self.logical_files += 1
                self.logical_bytes += len(raw)
                self.blobs.add(item['blob_path'])
        require(names == sorted(names, key=lambda name: name.encode('utf-8')) and
                '' in names and result[root][0] == 'directory', 'unsorted/missing retained tree root')
        for key in result:
            if key != root:
                require(result.get(str(PurePosixPath(key).parent), (None,))[0] == 'directory',
                        'retained file has missing/non-directory parent')
        require(self.logical_files <= BOUNDS['files'] and self.logical_bytes <= BOUNDS['total_bytes'] and
                self.directories <= BOUNDS['directories'], 'nested retention bound exceeded')
        return result

    def snapshot(self, number, phase):
        prefix = f'{number:04d}'
        value = parse(self.read(prefix + '.' + phase + '.json'))
        require(type(value) is dict and set(value) == {'temporary', 'output'}, 'host snapshot roots differ')
        result = {}
        for name, path in (('temporary', self.temporary), ('output', self.output)):
            result.update(self.tree(value[name], path, prefix + '/' + phase + '/' + name))
        return result

    def temporary_directory(self, suffix=None, prefix=None, dir=None, **kwargs):
        require(not kwargs and suffix in (None, '') and dir in (None, self.temporary),
                'unreviewed temporary-directory arguments')
        prefix = 'tmp' if prefix is None else prefix
        require(prefix in ('tmp', 'isolated-adi-build-', 'elf-metadata-unit-'), 'unreviewed temporary prefix')
        row = parse(self.read(f'{self.count + 1:04d}.before.json'))['temporary']
        candidates = []
        for item in row['entries']:
            name = item['path']
            if (item['kind'] == 'directory' and '/' not in name and
                    re.fullmatch(re.escape(prefix) + '[a-z0-9_]{8}', name) and
                    self.temporary + '/' + name not in self.fs.nodes):
                candidates.append(self.temporary + '/' + name)
        require(len(candidates) == 1, 'next recorded temporary directory is not uniquely source-derived')
        name = candidates[0]
        self.fs.mkdir(name, mode=0o700)
        fs = self.fs

        class TemporaryDirectory:
            def __init__(self):
                self.name = name
                self.closed = False

            def __enter__(self):
                return self.name

            def __exit__(self, *args):
                self.cleanup()

            def cleanup(self):
                if not self.closed:
                    fs.remove_tree(self.name)
                    self.closed = True
        return TemporaryDirectory()

    def _darwin_relocations(self, target):
        """Exact Apple clang 21 dSYM spelling, bound to retained tool observations."""
        developer = self.environment['DEVELOPER_DIR']
        expected_clang = (
            'Apple clang version 21.0.0 (clang-2100.0.123.102)\n'
            'Target: arm64-apple-darwin25.6.0\n'
            'Thread model: posix\n'
            'InstalledDir: ' + developer + '/Toolchains/XcodeDefault.xctoolchain/usr/bin\n')
        require(self.files.get('logs/clang-version.log') == expected_clang.encode() and
                self.files.get('logs/clang-version.stderr.log') == b'',
                'debug sidecar requires the captured Apple clang arm64 target')
        uname = self.files.get('logs/uname.log', b'')
        require(type(uname) is bytes and uname.startswith(b'Darwin ') and
                uname.endswith(b' arm64\n') and uname.count(b'\n') == 1 and
                self.files.get('logs/uname.stderr.log') == b'',
                'debug sidecar requires the captured Darwin arm64 host')
        require("'" not in target and '\n' not in target and '\r' not in target,
                'debug binary path cannot be represented by the exact retained YAML')
        path = target + '.dSYM/Contents/Resources/Relocations/aarch64/' + PurePosixPath(target).name + '.yml'
        raw = ("---\ntriple:          'arm64-apple-darwin'\n"
               "binary-path:     '" + target + "'\nrelocations:     []\n...\n").encode()
        return path, raw

    def _compiled_products(self, before, after, argv):
        require(argv.count('-o') == 1 and argv.index('-o') + 1 == len(argv) - 1,
                'reviewed compiler output flag/order differs')
        target = absolute(argv[-1])
        require(any(inside(target, root) for root in self.fs.owned_roots) and target not in before,
                'compiler output is not a fresh owned product')
        require(target in after and after[target][0] == 'file' and after[target][1] == '0755' and
                after[target][2], 'compiler product raw bytes/executable mode missing')
        allowed = {target}
        dsym = target + '.dSYM'
        require((dsym in after) == ('-g' in argv),
                'missing or unrequested source-derived compiler debug sidecar')
        if dsym in after:
            dwarf = dsym + '/Contents/Resources/DWARF/' + PurePosixPath(target).name
            sidecar_files = {dsym + '/Contents/Info.plist', dwarf}
            relocation, relocation_raw = self._darwin_relocations(target)
            require(after.get(relocation) == node('file', '0644', relocation_raw),
                    'exact source-derived Darwin relocation YAML differs')
            sidecar_files.add(relocation)
            allowed.update(sidecar_files)
            for filename in sidecar_files:
                require(filename in after and after[filename][0] == 'file' and
                        after[filename][1] == '0644' and after[filename][2],
                        'incomplete/unsafe compiler debug sidecar')
                parent = str(PurePosixPath(filename).parent)
                while inside(parent, dsym):
                    require(after.get(parent) == node('directory', '0755'), 'debug sidecar directory differs')
                    allowed.add(parent)
                    parent = str(PurePosixPath(parent).parent)
        require(set(after) == set(before) | allowed, 'extra/missing compiler-produced retained path')
        for key, value in before.items():
            exact(after[key], value, 'compiler mutated retained input or prior product')
        self.fs.nodes = after
        self.products.append({'command': self.count, 'path': target, 'sha256': sha(after[target][2]),
                              'bytes': len(after[target][2]),
                              'sidecar_files': sorted(p for p in allowed if p != target and after[p][0] == 'file')})

    def run(self, *args, **kwargs):
        require(len(args) == 1 and isinstance(args[0], (list, tuple)) and args[0] and
                set(kwargs) <= {'capture_output', 'text', 'timeout', 'env'} and
                kwargs.get('capture_output') is True and kwargs.get('text') is True and
                type(kwargs.get('timeout')) is int and 0 < kwargs['timeout'] <= 120,
                'unreviewed subprocess call shape')
        argv = [str(value) for value in args[0]]
        require(all(value and '\0' not in value for value in argv), 'invalid nested argv')
        environment = kwargs.get('env') or self.environment
        require(type(environment) is dict and set(environment) <= set(SAFE_ENV) and
                all(type(v) is str for v in environment.values()), 'unexpected nested environment')
        self.count += 1
        require(self.count <= 512, 'nested command bound exceeded')
        prefix = f'{self.count:04d}'
        expected = {'argv': argv, 'cwd': self.work,
                    'environment': {key: environment[key] for key in SAFE_ENV if key in environment},
                    'returncode': None}
        exact(parse(self.read(prefix + '.command.json')), expected, 'source-derived command/argv/cwd/environment differs')
        exact(parse(self.read(prefix + '.result.json')), {**expected, 'returncode': 0},
              'nested command failed, incomplete or result identity differs')
        before = self.snapshot(self.count, 'before')
        exact(before, self.fs.nodes, 'source-derived compiler input/before tree differs')
        stdout = self.read(prefix + '.stdout')
        stderr = self.read(prefix + '.stderr')
        if self.driver != 'run_tests.py':
            require(stderr == b'', 'original nested stderr is nonempty')
        after = self.snapshot(self.count, 'after')
        if argv[0] in ('c++', '/usr/bin/c++', '/usr/bin/swiftc'):
            if self.driver != 'run_tests.py':
                require(stdout == b'', 'original compiler stdout is nonempty')
            self._compiled_products(before, after, argv)
        else:
            require(argv[0] in before and before[argv[0]][0:2] == ('file', '0755'),
                    'runtime command lacks its exact retained compiled executable')
            require(any(product['path'] == argv[0] for product in self.products),
                    'runtime executable was not produced by this source-derived lane')
            exact(after, before, 'runtime mutated retained compiler inputs/products')
        self.commands.append(expected)
        text = stdout.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        error_text = stderr.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        return types.SimpleNamespace(args=argv, returncode=0, stdout=text, stderr=error_text)

    def execute(self):
        script = self.fs.Path(self.owner + '/.ci/native-tests/' + self.driver)
        raw = script.read_bytes()
        require(sha(raw) == DRIVER_SHA256[self.driver], 'owner driver differs from reviewed A+B source')
        argv = ['--output', self.output]
        argv += (['--disable-leak-sanitizer'] if self.driver == 'test_elf_metadata_bounds.py'
                 else ['--unicorn-include', self.work + '/host-unicorn-headers'])
        class Parser(argparse.ArgumentParser):
            def parse_args(self, args=None, namespace=None):
                require(args is None, 'unexpected explicit driver argv')
                return super().parse_args(argv, namespace)
        fake_argparse = types.SimpleNamespace(ArgumentParser=Parser)
        def which(command):
            require(command in ('c++', 'g++', 'swiftc'), 'unreviewed tool discovery')
            return '/usr/bin/' + command
        def copyfile(source, target):
            self.fs.Path(target).write_bytes(self.fs.Path(source).read_bytes())
            return target
        modules = {
            'argparse': fake_argparse, 'hashlib': hashlib, 'json': json, 're': re,
            'os': types.SimpleNamespace(environ=dict(self.environment)),
            'pathlib': types.SimpleNamespace(Path=self.fs.Path),
            'shutil': types.SimpleNamespace(which=which, copyfile=copyfile),
            'subprocess': types.SimpleNamespace(run=self.run),
            'tempfile': types.SimpleNamespace(TemporaryDirectory=self.temporary_directory),
            'unittest': unittest,
        }
        def importer(name, globals=None, locals=None, fromlist=(), level=0):
            require(level == 0 and name in modules, 'unreviewed Python driver import')
            return modules[name]
        safe_builtins = dict(vars(builtins))
        for name in ('open', 'eval', 'exec', 'compile', 'input', 'breakpoint', 'help', 'exit', 'quit'):
            safe_builtins.pop(name, None)
        safe_builtins['__import__'] = importer
        def printed(*values, **kwargs):
            require(set(kwargs) <= {'sep', 'end', 'flush'}, 'driver output redirected')
            builtins.print(*values, file=self.printed, **kwargs)
        safe_builtins['print'] = printed
        name = 'run_tests' if self.driver == 'run_tests.py' else '__main__'
        scope = {'__builtins__': safe_builtins, '__name__': name, '__file__': str(script)}
        # Only the fixed SHA256 above can reach this pure-Python evaluation.
        # optimize=0 preserves assertions even under the verifier's python -O.
        exec(compile(raw, str(script), 'exec', dont_inherit=True, optimize=0), scope)
        if self.driver == 'run_tests.py':
            require(str(scope['ROOT']) == self.owner, 'aggregate driver root changed')
            suite = unittest.TestLoader().loadTestsFromTestCase(scope['MaintainedAnisetteNativeTests'])
            self.unit_ids = [test.id() for test in suite]
            expected = sorted('run_tests.MaintainedAnisetteNativeTests.' + method for method in UNIT_METHODS)
            exact(self.unit_ids, expected, 'exact nine source-derived host test IDs required')
            result = unittest.TestResult()
            suite.run(result)
            require(result.wasSuccessful() and result.testsRun == 9 and not result.skipped and
                    not result.expectedFailures and not result.unexpectedSuccesses,
                    'original aggregate outputs failed sealed unittest assertions: ' +
                    repr(result.failures + result.errors))
            row = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                       skips=len(result.skipped), expected_failures=len(result.expectedFailures),
                       unexpected_successes=len(result.unexpectedSuccesses), test_ids=self.unit_ids)
            (self.fs.Path(self.output) / 'unittest-result.json').write_text(json.dumps(row, indent=2) + '\n')

    def finish(self, gate):
        require(self.count > 0, 'host driver made no observed commands')
        if self.driver != 'run_tests.py':
            require(self.count == 6, 'exact compile/run variant command count differs')
        final = self.tree(parse(self.read('final-output.json')), self.output, 'final-output')
        expected = {key: value for key, value in self.fs.nodes.items() if inside(key, self.output)}
        exact(final, expected, 'source-derived final output tree differs')
        require({key for key in self.fs.nodes if inside(key, self.temporary)} == {self.temporary},
                'source-derived temporary-directory cleanup incomplete')
        summary = {'format': 'p0defensive-raw-store-v1', 'hash': 'sha256',
                   'logical_files': self.logical_files, 'logical_bytes': self.logical_bytes,
                   'directories': self.directories, 'unique_blobs': len(self.blobs),
                   'limits': BOUNDS, 'nested_commands': self.count}
        exact(parse(self.read('retention-summary.json')), summary, 'nested retention accounting differs')
        expected_names = {'final-output.json', 'retention-summary.json'} | self.blobs
        for number in range(1, self.count + 1):
            expected_names.update(f'{number:04d}' + suffix for suffix in
                                  ('.command.json', '.result.json', '.stdout', '.stderr', '.before.json', '.after.json'))
        actual_names = {name[len(self.namespace) + 1:] for name in self.files if name.startswith(self.namespace + '/')}
        exact(actual_names, expected_names, 'extra/missing nested commands, raw blobs or retained files')
        # Reuse the frozen emitter's exact result predicates without touching any
        # recorded path. Its ordinary() helper is replaced in a private function
        # globals dictionary, never in the caller's modules.
        def ordinary(root, name):
            relative(name)
            path = self.fs.Path(root) / name
            require(path.is_file(), 'missing virtual result file')
            return path
        function = gate.host_tests.verify_result
        check = types.FunctionType(function.__code__, {**function.__globals__, 'ordinary': ordinary},
                                   function.__name__, function.__defaults__, function.__closure__)
        counts = check(self.driver, self.fs.Path(self.output))
        exact(counts, EXPECTED_COUNTS[self.driver], 'new diagnostic host result counts differ')
        provenance = 'provenance/host-' + self.label + '.json'
        require(provenance in self.files, 'missing original top-level host result')
        exact(parse(self.files[provenance]), counts, 'top-level host result contradicts replay')
        log = 'logs/host-' + self.label + '.log'
        require(log in self.files and self.files[log] == self.printed.getvalue().encode('utf-8'),
                'original top-level host stdout differs from sealed driver replay')
        return {**counts, 'nested_commands': self.count, 'source_driver_sha256': DRIVER_SHA256[self.driver],
                'command_sequence_sha256': sha(json.dumps(self.commands, sort_keys=True, separators=(',', ':')).encode()),
                'products': self.products, 'retention': summary,
                **({'test_ids': self.unit_ids} if self.unit_ids else {})}


def verify_host_lanes(files, data, gate, roots, context, raw_record):
    """Replay original bytes from an indexed archive; return only verified facts.

    ``files`` is an evidence-root-relative Mapping[str, bytes]. ``roots`` holds
    already-verified, read-only local source repositories. ``context`` contains
    the original absolute work/evidence/host/python paths and base environment.
    ``raw_record(record, namespace=...)`` must validate and return original blob
    bytes, including declared length, SHA256 and Git blob identities. Top-level
    command lifecycle, stderr/settlement, header provenance and package lanes
    remain the caller's responsibility.
    """
    require(tuple(gate.host_tests.DRIVERS) == DRIVERS, 'frozen host driver inventory differs')
    require(data['owners']['AnisetteKit']['commit'] == OWNER_COMMIT,
            'host replay requires the frozen new diagnostic owner')
    require(set(context) >= {'work', 'evidence', 'host', 'python', 'environment'}, 'capture context incomplete')
    for key in ('work', 'evidence', 'host', 'python'):
        absolute(context[key])
    prefixes = {name.split('/')[1] for name in files if name.startswith('host-tests/') and len(name.split('/')) >= 3}
    labels = {driver.removesuffix('.py').replace('_', '-') for driver in DRIVERS}
    exact(prefixes, labels, 'exact four original host lanes required')
    require(all(len(name.split('/')) >= 3 for name in files if name.startswith('host-tests/')),
            'unexpected file at host-lane root')
    result = {}
    for driver in DRIVERS:
        lane = _Lane(files, driver, roots['AnisetteKit'], context, raw_record)
        try:
            lane.execute()
        except (Exception, SystemExit) as error:
            raise ValueError('Phase A host replay: sealed driver replay failed: ' + driver + ': ' + str(error)) from error
        result[lane.label] = lane.finish(gate)
    return {'status': 'VERIFIED_ORIGINAL_HOST_REPLAY', 'lanes': result,
            'memory_assertions': 1209, 'setup_assertions': 717, 'metadata_assertions': 2139,
            'aggregate_tests': 9, 'nested_commands': sum(row['nested_commands'] for row in result.values()),
            'native_execution_performed': False, 'archive_extracted': False, 'source_mutated': False}
