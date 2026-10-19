"""Replay the frozen Apple diagnostic Python driver with memory-only I/O.

The original indexed archive is never extracted and no retained executable runs.
The four established host lanes retain their reviewed replay implementation.
"""
from collections.abc import Mapping
import json
from pathlib import Path, PurePosixPath
import re
import types
import phase_a_host_replay as h

DRIVER = 'run_diagnostic_checks.py'
DRIVER_SHA256 = '3abd372d6411e99b69e3eed80f431cf313da06ecada84705e1dfaf985162aefb'
MODULE_SHA256 = '6eb52cc4899326d4246ffc5d7bac18693d18a3ee036dfadbefa8ea2be59e0d85'
COUNTS = {'native_assertions': 1986, 'swift_boundary_checks': 154,
          'swift_decoder_variants': 2, 'guest_execution': False,
          'real_engine_starts': 0, 'apple_commoncrypto_validated': True}


class DiagnosticLane(h._Lane):
    def __init__(self, files, source_root, context, raw_record, module, headers):
        super().__init__(files, h.DRIVERS[0], source_root, context, raw_record)
        self.driver = DRIVER; self.label = 'run-diagnostic-checks'
        self.namespace = 'host-tests/' + self.label
        self.output = self.work + '/host-tests/' + self.label
        self.temporary = self.work + '/host-temporary/' + self.label
        self.environment['TMPDIR'] = self.temporary
        self.fs = h._VirtualFS(source_root, self.owner, (self.temporary, self.output), self.work)
        self.module = module; self.headers = headers; self.dependencies = []
        # The context must originate in retained outer dispatch, not a caller's
        # internally consistent result paths. Full replay also verifies that
        # dispatch's lifecycle, source tree, retained headers and output roots.
        outer_key = 'logs/host-' + self.label + '.command.json'
        h.require(outer_key in files, 'original diagnostic outer command missing')
        importer = module.run.__globals__['__builtins__']['__import__']
        host_tests = importer('host_tests', fromlist=('execution_command',))
        lifecycle = importer('lifecycle', fromlist=('command_environment',))
        logical = [context['python'], '-B', context['host'] + '/ci/p0defensive/run_host_test.py',
                   '--owner', self.owner, '--driver', DRIVER, '--output', self.output,
                   '--temporary', self.temporary, '--evidence', context['evidence'] + '/' + self.namespace,
                   '--unicorn-include', self.work + '/host-unicorn-headers']
        outer_argv = host_tests.execution_command(DRIVER, logical)
        h.exact(h.parse(files[outer_key]), {'argv': outer_argv, 'cwd': self.work,
            'environment': lifecycle.command_environment('host-' + self.label, outer_argv, context['environment'])},
            'diagnostic outer command/context differs')
        self.command_context = module.command_context(self.owner, self.work + '/host-unicorn-headers', self.output)
        self.plan = module.command_plan(self.command_context)
        h.exact(len(self.plan), 16, 'exact reviewed diagnostic command plan required')
        self.observed_results = []

    def dependency_file(self, raw, target, source):
        h.require(type(raw) is bytes and 0 < len(raw) <= 65536 and raw.endswith(b'\n'),
                  'bounded original compiler dependency file required')
        text = raw.decode('utf-8').replace('\\\n', '')
        h.require(text.startswith(target + ':') and text.count(':') == 1 and '\\' not in text and
                  all(ord(char) >= 32 or char in '\n\t' for char in text),
                  'compiler dependency rule target/encoding differs')
        names = text[len(target) + 1:].split()
        h.require(names and names[0] == source and len(names) == len(set(names)) and len(names) <= 256,
                  'compiler dependency source/count differs')
        rows = {}
        for name in names:
            h.absolute(name)
            if name == source or h.inside(name, self.owner):
                raw_input = self.fs.read(name)
            else:
                h.require(name in self.headers, 'dependency escaped retained source/generated/Unicorn headers')
                raw_input = self.headers[name]
            rows[name] = {'sha256': h.sha(raw_input), 'bytes': len(raw_input)}
        return rows

    def _compiled_products(self, before, after, argv):
        if argv[:2] != ['xcrun', 'clang++']:
            h.require(argv[0] == 'swiftc' and '-MMD' not in argv and '-MF' not in argv,
                      'unreviewed diagnostic compiler')
            return super()._compiled_products(before, after, argv)
        h.require(argv.count('-MMD') == argv.count('-MF') == 1 and argv.count('-o') == 1,
                  'exact diagnostic compiler dependency flags required')
        target = argv[-1]; dependency = argv[argv.index('-MF') + 1]
        h.require(dependency == target + '.d' and dependency not in before,
                  'fresh source-derived compiler dependency path required')
        record = after.get(dependency)
        h.require(record is not None and record[:2] == ('file', '0644'),
                  'ordinary original compiler dependency file required')
        rows = self.dependency_file(record[2], target, self.output + '/bounded-fault-apple.cpp')
        reduced = {name: value for name, value in after.items() if name != dependency}
        super()._compiled_products(before, reduced, argv)
        self.fs.nodes = after
        self.dependencies.append({'command': self.count, 'path': dependency,
                                  'sha256': h.sha(record[2]), 'inputs': rows})

    def run(self, *args, **kwargs):
        h.require(len(args) == 1 and type(args[0]) is list and args[0] and
                  set(kwargs) <= {'capture_output', 'text', 'timeout', 'env'} and
                  kwargs.get('capture_output') is True and kwargs.get('text') is True and
                  type(kwargs.get('timeout')) is int and kwargs['timeout'] == 120,
                  'unreviewed diagnostic subprocess shape')
        argv = [str(value) for value in args[0]]
        environment = kwargs.get('env') or self.environment
        h.require(type(environment) is dict and set(environment) <= set(h.SAFE_ENV) and
                  all(type(value) is str for value in environment.values()), 'diagnostic environment differs')
        self.count += 1; h.require(self.count <= 16, 'extra diagnostic command')
        dispatch = self.plan[self.count - 1]
        logical_argv = dispatch['logical_argv']
        compile_only = dispatch['label'] in ('swift-normal-compile', 'swift-optimized-compile')
        h.exact(dispatch['sandbox_policy'], 'apple_plugin_sandbox_compile' if compile_only else 'network_denied',
                'diagnostic fixed row sandbox policy differs')
        h.exact(argv, logical_argv if compile_only else [*self.module.SANDBOX, *logical_argv],
                'diagnostic exact dispatch prefix/policy differs')
        h.exact(argv, dispatch['argv'], 'diagnostic reviewed executed argv differs')
        prefix = f'{self.count:04d}'
        expected = {'argv': argv, 'cwd': self.work,
                    'environment': {key: environment[key] for key in h.SAFE_ENV if key in environment},
                    'returncode': None}
        h.exact(h.parse(self.read(prefix + '.command.json')), expected,
                'source-derived diagnostic command/argv/cwd/environment differs')
        h.exact(h.parse(self.read(prefix + '.result.json')), {**expected, 'returncode': 0},
                'original diagnostic command failed or differs')
        before = self.snapshot(self.count, 'before')
        h.exact(before, self.fs.nodes, 'diagnostic generated input/before tree differs')
        stdout = self.read(prefix + '.stdout'); stderr = self.read(prefix + '.stderr')
        h.require(stderr == b'', 'original diagnostic stderr is nonempty')
        after = self.snapshot(self.count, 'after')
        # Compiler-product classification uses logical argv only after proving
        # exact dispatch prefix and row policy above, never by stripping a prefix.
        if logical_argv[:2] == ['xcrun', 'clang++'] or logical_argv[0] == 'swiftc':
            h.require(stdout == b'', 'original diagnostic compiler stdout is nonempty')
            self._compiled_products(before, after, logical_argv)
        else:
            if logical_argv[:2] in (['xcrun', 'nm'], ['xcrun', 'otool']):
                h.require(len(logical_argv) == 4 and logical_argv[2] == ('-u' if logical_argv[1] == 'nm' else '-L'),
                          'unreviewed diagnostic static inspection')
                executable = logical_argv[-1]
            else:
                h.require(len(logical_argv) == 1, 'unreviewed diagnostic execution arguments')
                executable = logical_argv[0]
            h.require(before.get(executable, ())[:2] == ('file', '0755') and
                      any(row['path'] == executable for row in self.products),
                      'diagnostic inspection/runtime lacks exact retained compiler product')
            h.exact(after, before, 'diagnostic inspection/runtime mutated retained inputs')
        self.commands.append(expected)
        normalized = lambda raw: raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
        self.observed_results.append({**dispatch, 'returncode': 0, 'stdout': normalized(stdout), 'stderr': normalized(stderr)})
        return types.SimpleNamespace(returncode=0, stdout=normalized(stdout), stderr=normalized(stderr))

    def execute(self):
        module = self.module
        actual_owner = self.fs.source_root
        def selected_owner(owner):
            h.require(str(owner) == self.owner, 'diagnostic source root differs')
            return actual_owner
        def ordinary(owner, name):
            selected_owner(owner); h.relative(name)
            path = self.fs.Path(str(owner)) / name
            h.require(path.is_file(), 'missing verified diagnostic source input')
            return path
        def native_fixture(owner):
            local = selected_owner(owner)
            original = module.ordinary(local, '.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text()
            return module.adapt_native_fixture(original, Path(self.owner))
        globals_ = {**module.run.__globals__,
            'platform': types.SimpleNamespace(system=lambda: 'Darwin', machine=lambda: 'arm64'),
            'os': types.SimpleNamespace(environ=dict(self.environment)),
            'subprocess': types.SimpleNamespace(run=self.run),
            'source_closure': lambda owner: module.source_closure(selected_owner(owner)),
            'native_fixture': native_fixture,
            'swift_fixture': lambda owner: module.swift_fixture(selected_owner(owner)),
            'ordinary': ordinary}
        replay = types.FunctionType(module.run.__code__, globals_, module.run.__name__,
                                    module.run.__defaults__, module.run.__closure__)
        replay(self.fs.Path(self.owner), self.fs.Path(self.work + '/host-unicorn-headers'), self.fs.Path(self.output))

    def finish(self):
        h.exact(self.count, 16, 'exact diagnostic compile/run/inspection command count differs')
        final = self.tree(h.parse(self.read('final-output.json')), self.output, 'final-output')
        h.exact(final, {key: value for key, value in self.fs.nodes.items() if h.inside(key, self.output)},
                'diagnostic final generated/result/product tree differs')
        h.require({key for key in self.fs.nodes if h.inside(key, self.temporary)} == {self.temporary},
                  'diagnostic temporary tree unexpectedly populated')
        summary = {'format': 'p0defensive-raw-store-v1', 'hash': 'sha256',
                   'logical_files': self.logical_files, 'logical_bytes': self.logical_bytes,
                   'directories': self.directories, 'unique_blobs': len(self.blobs),
                   'limits': h.BOUNDS, 'nested_commands': self.count}
        h.exact(h.parse(self.read('retention-summary.json')), summary, 'diagnostic raw accounting differs')
        names = {'final-output.json', 'retention-summary.json'} | self.blobs
        for number in range(1, 17):
            names.update(f'{number:04d}' + suffix for suffix in
                         ('.command.json', '.result.json', '.stdout', '.stderr', '.before.json', '.after.json'))
        actual = {name[len(self.namespace) + 1:] for name in self.files if name.startswith(self.namespace + '/')}
        h.exact(actual, names, 'diagnostic nested original file closure differs')
        row = h.parse(self.fs.read(self.output + '/diagnostic-results.json'))
        h.exact(row['results'], self.observed_results, 'diagnostic result rows differ from observed raw streams/dispatch')
        counts = self.module.verify_result(row, self.command_context)
        h.exact(counts, COUNTS, 'diagnostic finite assertion counts differ')
        h.exact(h.parse(self.files['provenance/host-' + self.label + '.json']), counts,
                'diagnostic top-level result differs')
        h.require(self.files['logs/host-' + self.label + '.log'] == b'', 'diagnostic top-level stdout differs')
        return {**counts, 'nested_commands': 16, 'source_driver_sha256': DRIVER_SHA256,
                'diagnostic_module_sha256': MODULE_SHA256, 'products': self.products,
                'compiler_dependencies': self.dependencies, 'retention': summary,
                'command_sequence_sha256': h.sha(json.dumps(self.commands, sort_keys=True, separators=(',', ':')).encode())}


def verify_host_lanes(files, data, gate, roots, context, raw_record):
    h.exact(tuple(gate.host_tests.DRIVERS), (*h.DRIVERS, DRIVER), 'exact five diagnostic host lanes required')
    namespace = 'host-tests/run-diagnostic-checks/'
    class CoreFiles(Mapping):
        # Preserve lazy archive reads; filtering the fifth host namespace must
        # never eagerly decompress unrelated retained tool/SDK product bytes.
        def __iter__(self):
            return (name for name in files if not name.startswith(namespace))
        def __len__(self):
            return sum(1 for _ in self)
        def __getitem__(self, name):
            if name.startswith(namespace):
                raise KeyError(name)
            return files[name]
    core_files = CoreFiles()
    core_gate = types.SimpleNamespace(host_tests=types.SimpleNamespace(
        DRIVERS=h.DRIVERS, verify_result=gate.host_tests.verify_result))
    core = h.verify_host_lanes(core_files, data, core_gate, roots, context, raw_record)
    importer = gate.host_tests.verify_result.__globals__['__builtins__']['__import__']
    module = importer('diagnostic_checks', fromlist=('run',))
    h.require(h.sha(Path(module.__file__).read_bytes()) == MODULE_SHA256 and
              h.sha((Path(module.__file__).parent / DRIVER).read_bytes()) == DRIVER_SHA256,
              'frozen diagnostic generator/entry point differs')
    header_tree = h.parse(files['provenance/host-unicorn-headers.json'])['raw_tree']
    h.require(header_tree['source_path'] == context['work'] + '/host-unicorn-headers',
              'diagnostic retained header root differs')
    headers = {row['source_path']: raw_record(row) for row in header_tree['entries'] if row['kind'] == 'file'}
    lane = DiagnosticLane(files, roots['AnisetteKit'], context, raw_record, module, headers)
    lane.execute(); result = lane.finish()
    core['lanes'][lane.label] = result; core['nested_commands'] += result['nested_commands']
    core['bounded_diagnostic'] = COUNTS.copy()
    return core
