"""Source-derived, memory-only diagnostic replay fixtures.

Compiler products, static-tool output and runtime streams are explicitly
synthetic. The trusted frozen generator and real reviewed AK source bytes drive
all sixteen command records; no compiler, native executable or network runs.
"""
import copy
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnostic_host_replay as diagnostic
import phase_a_host_replay as h
import prior_phase_a
from test_phase_a_host_replay import (CONTEXT, DEBUG_TOOL_LOGS, FixtureRecorder,
                                     encode, synthetic_debug_product)

ROOT = HERE / 'tests/fixtures/diagnostic-source'
NAMESPACE = 'host-tests/run-diagnostic-checks'
OUTPUT = CONTEXT['work'] + '/host-tests/run-diagnostic-checks'
OWNER = CONTEXT['work'] + '/sources/AnisetteKit'
HEADER = CONTEXT['work'] + '/host-unicorn-headers/unicorn/unicorn.h'
HEADERS = {HEADER: b'/* SYNTHETIC RETAINED HEADER FOR OFFLINE VERIFIER TESTS */\n'}
SWIFT_COMPLETION = b'BOUNDED_FAULT_SWIFT_DECODER_PASS\nBOUNDED_FAULT_SWIFT_BOUNDARIES_PASS:77\n'


def raw_reader(files):
    def read(record, namespace=''):
        path = namespace + '/' + record['blob_path'] if namespace else record['blob_path']
        raw = files[path]
        h.require(type(record['length']) is int and len(raw) == record['length'] and
                  h.sha(raw) == record['sha256'], 'raw length/hash mismatch')
        h.require(record['blob_path'] == 'blobs/sha256/' + record['sha256'][:2] + '/' + record['sha256'],
                  'noncanonical raw blob path')
        header = b'blob ' + str(len(raw)).encode() + b'\0'
        h.require(hashlib.sha1(header + raw).hexdigest() == record['git_blob_sha1'] and
                  hashlib.sha256(header + raw).hexdigest() == record['git_blob_sha256'],
                  'raw Git object mismatch')
        return raw
    return read


def outer_command(gate, context=CONTEXT):
    label = 'host-run-diagnostic-checks'
    work = context['work']
    logical = [context['python'], '-B', context['host'] + '/ci/p0defensive/run_host_test.py',
               '--owner', work + '/sources/AnisetteKit', '--driver', diagnostic.DRIVER,
               '--output', work + '/host-tests/run-diagnostic-checks',
               '--temporary', work + '/host-temporary/run-diagnostic-checks',
               '--evidence', context['evidence'] + '/host-tests/run-diagnostic-checks',
               '--unicorn-include', work + '/host-unicorn-headers']
    argv = gate.host_tests.execution_command(diagnostic.DRIVER, logical)
    return encode({'argv': argv, 'cwd': work, 'environment':
        gate._private_modules['lifecycle'].command_environment(label, argv, context['environment'])})


class DiagnosticFixtureRecorder(diagnostic.DiagnosticLane):
    """Use the established observer-format writer, but never invoke a process."""
    emit_tree = FixtureRecorder.emit_tree
    emit_snapshot = FixtureRecorder.emit_snapshot

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
        # Fixture generation classifies only the exact source-derived logical row.
        dispatch = self.module.command_plan(self.command_context)[self.count - 1]
        h.exact(argv, dispatch['argv'])
        argv = dispatch['logical_argv']
        if '-o' in argv:
            target = argv[-1]
            self.fs.nodes[target] = h.node('file', '0755',
                b'SYNTHETIC_DIAGNOSTIC_COMPILER_PRODUCT:' + target.encode())
            if '-g' in argv:
                self.fs.nodes.update(synthetic_debug_product(target))
            if argv[:2] == ['xcrun', 'clang++']:
                dependencies = (self.output + '/bounded-fault-apple.cpp',
                                self.owner + '/Native/Loader/elf_loader_emulator.cpp', HEADER)
                self.fs.nodes[target + '.d'] = h.node('file', '0644',
                    (target + ': ' + ' \\\n  '.join(dependencies) + '\n').encode())
            stdout = b''
        elif argv[:2] == ['xcrun', 'nm']:
            stdout = b'                 U _CC_SHA256_Init\n                 U _CC_SHA256_Update\n                 U _CC_SHA256_Final\n'
        elif argv[:2] == ['xcrun', 'otool']:
            stdout = (argv[-1] + ':\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1351.0.0)\n').encode()
        elif Path(argv[0]).name.startswith('swift-boundaries-'):
            stdout = SWIFT_COMPLETION
        else:
            stdout = encode(self.module.NATIVE_EXPECTED)
        stdout = getattr(self, 'stdout_overrides', {}).get(self.count, stdout)
        self.files[prefix + '.stdout'] = stdout
        self.files[prefix + '.stderr'] = b''
        self.emit_snapshot('after')
        return types.SimpleNamespace(returncode=0, stdout=stdout.decode(), stderr='')

    def complete(self):
        self.files[self.namespace + '/final-output.json'] = encode(self.emit_tree(self.output, 'final-output'))
        self.files[self.namespace + '/retention-summary.json'] = encode({
            'format': 'p0defensive-raw-store-v1', 'hash': 'sha256',
            'logical_files': self.logical_files, 'logical_bytes': self.logical_bytes,
            'directories': self.directories, 'unique_blobs': len(self.blobs),
            'limits': h.BOUNDS, 'nested_commands': self.count})
        self.files['provenance/host-' + self.label + '.json'] = encode(diagnostic.COUNTS)
        self.files['logs/host-' + self.label + '.log'] = b''


class DiagnosticHostReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate, cls.data, _, _ = prior_phase_a._load_trusted_adapter(HERE / 'prior_adapter')
        importer = cls.gate.host_tests.verify_result.__globals__['__builtins__']['__import__']
        cls.module = importer('diagnostic_checks', fromlist=('run',))
        if not ROOT.is_dir():
            raise RuntimeError('the explicit reviewed diagnostic AK source root is required')
        cls.original = dict(DEBUG_TOOL_LOGS)
        cls.original['logs/host-run-diagnostic-checks.command.json'] = outer_command(cls.gate)
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess is forbidden')):
            recorder = DiagnosticFixtureRecorder(cls.original, ROOT, CONTEXT,
                                                 raw_reader(cls.original), cls.module, HEADERS)
            recorder.execute()
            recorder.complete()
        cls.expected_generated = {name: recorder.fs.read(OUTPUT + '/' + name)
                                  for name in ('bounded-fault-apple.cpp', 'main.swift')}

    def setUp(self):
        self.files = dict(self.original)

    def verify(self):
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess is forbidden')):
            lane = diagnostic.DiagnosticLane(self.files, ROOT, CONTEXT,
                                             raw_reader(self.files), self.module, HEADERS)
            lane.execute()
            return lane.finish()

    def mutate_json(self, name, change):
        key = NAMESPACE + '/' + name
        value = h.parse(self.files[key])
        change(value)
        self.files[key] = encode(value)

    def record(self, name, path, root='output'):
        value = h.parse(self.files[NAMESPACE + '/' + name])
        tree = value if name == 'final-output.json' else value[root]
        return next(row for row in tree['entries'] if row['path'] == path)

    def replace_record(self, name, path, raw, mode=None):
        """Rehash a deliberate byte mutation, so semantic checks must reject it."""
        def change(value):
            tree = value if name == 'final-output.json' else value['output']
            row = next(row for row in tree['entries'] if row['path'] == path)
            digest = h.sha(raw)
            header = b'blob ' + str(len(raw)).encode() + b'\0'
            row.update(length=len(raw), sha256=digest,
                       blob_path='blobs/sha256/' + digest[:2] + '/' + digest,
                       git_blob_sha1=hashlib.sha1(header + raw).hexdigest(),
                       git_blob_sha256=hashlib.sha256(header + raw).hexdigest())
            if mode is not None:
                row['mode'] = mode
            self.files[NAMESPACE + '/' + row['blob_path']] = raw
        self.mutate_json(name, change)

    def remove_record(self, name, path, recursive=False):
        def change(value):
            tree = value if name == 'final-output.json' else value['output']
            tree['entries'] = [row for row in tree['entries'] if row['path'] != path and
                               not (recursive and row['path'].startswith(path + '/'))]
        self.mutate_json(name, change)

    def mutate_stdout_coherently(self, number, raw):
        """Retain changed command output in every later generated result snapshot."""
        files = dict(DEBUG_TOOL_LOGS)
        files['logs/host-run-diagnostic-checks.command.json'] = outer_command(self.gate)
        recorder = DiagnosticFixtureRecorder(files, ROOT, CONTEXT, raw_reader(files), self.module, HEADERS)
        recorder.stdout_overrides = {number: raw}
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess is forbidden')):
            # The genuine frozen driver's final semantic verifier must reject
            # this fixture; all original-format intermediate records still exist.
            with self.assertRaises(ValueError):
                recorder.execute()
            self.assertEqual(recorder.count, 16)
            recorder.complete()
        self.files = files

    def reject(self, change, message=None):
        original = self.files
        self.files = dict(self.original)
        try:
            change()
            if message:
                with self.assertRaisesRegex((ValueError, KeyError, AssertionError), message):
                    self.verify()
            else:
                with self.assertRaises((ValueError, KeyError, UnicodeError, AssertionError)):
                    self.verify()
        finally:
            self.files = original

    def verify_wrapper(self, gate=None, header_root=None):
        """Isolate only the four already-tested core lanes at the wrapper boundary."""
        files = dict(self.files)
        raw = HEADERS[HEADER]
        digest = h.sha(raw)
        git_header = b'blob ' + str(len(raw)).encode() + b'\0'
        record = dict(kind='file', source_path=HEADER, length=len(raw), sha256=digest,
                      blob_path='blobs/sha256/' + digest[:2] + '/' + digest,
                      git_blob_sha1=hashlib.sha1(git_header + raw).hexdigest(),
                      git_blob_sha256=hashlib.sha256(git_header + raw).hexdigest())
        files[record['blob_path']] = raw
        files['provenance/host-unicorn-headers.json'] = encode({'raw_tree': {
            'source_path': header_root or CONTEXT['work'] + '/host-unicorn-headers',
            'entries': [record]}})
        core_result = {'lanes': {}, 'nested_commands': 148}
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess is forbidden')), \
             mock.patch.object(h, 'verify_host_lanes', return_value=core_result) as core:
            result = diagnostic.verify_host_lanes(files, self.data, gate or self.gate,
                        {'AnisetteKit': ROOT}, CONTEXT, raw_reader(files))
            core_files = core.call_args.args[0]
            self.assertFalse(any(name.startswith(NAMESPACE + '/') for name in core_files))
        return result

    def test_public_wrapper_adds_real_diagnostic_lane_to_core_boundary(self):
        result = self.verify_wrapper()
        self.assertEqual(result['nested_commands'], 164)
        self.assertEqual(result['bounded_diagnostic'], diagnostic.COUNTS)
        self.assertEqual(result['lanes']['run-diagnostic-checks']['nested_commands'], 16)

    def test_public_wrapper_requires_exact_five_driver_inventory(self):
        gate = types.SimpleNamespace(host_tests=types.SimpleNamespace(DRIVERS=h.DRIVERS))
        with self.assertRaisesRegex(ValueError, 'exact five diagnostic host lanes'):
            self.verify_wrapper(gate=gate)

    def test_public_wrapper_requires_retained_header_root(self):
        with self.assertRaisesRegex(ValueError, 'retained header root differs'):
            self.verify_wrapper(header_root='/unreviewed/headers')

    def test_public_wrapper_checks_actual_frozen_module_hash(self):
        with mock.patch.object(diagnostic, 'MODULE_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'frozen diagnostic generator/entry point differs'):
                self.verify_wrapper()

    def test_real_frozen_generator_replays_sixteen_commands_without_processes(self):
        result = self.verify()
        self.assertEqual(result['nested_commands'], 16)
        self.assertEqual({key: result[key] for key in diagnostic.COUNTS}, diagnostic.COUNTS)
        self.assertEqual(len(result['products']), 5)
        self.assertEqual([row['command'] for row in result['products']], [1, 5, 9, 13, 15])
        self.assertEqual([row['command'] for row in result['compiler_dependencies']], [1, 5, 9])
        for row in result['compiler_dependencies']:
            self.assertEqual(set(row['inputs']), {OUTPUT + '/bounded-fault-apple.cpp',
                              OWNER + '/Native/Loader/elf_loader_emulator.cpp', HEADER})
            self.assertEqual(row['inputs'][HEADER]['sha256'], h.sha(HEADERS[HEADER]))
        self.assertEqual(len(result['products'][2]['sidecar_files']), 3)
        self.assertEqual(h.sha(Path(self.module.__file__).read_bytes()), diagnostic.MODULE_SHA256)

    def test_generated_native_bytes_bound_to_actual_source(self):
        raw = self.expected_generated['bounded-fault-apple.cpp'] + b'\n// tampered generated native code\n'
        self.reject(lambda: self.replace_record('0001.before.json', 'bounded-fault-apple.cpp', raw),
                    'generated input/before tree')

    def test_generated_swift_bytes_bound_to_actual_source(self):
        raw = self.expected_generated['main.swift'] + b'\n// tampered generated Swift code\n'
        self.reject(lambda: self.replace_record('0001.before.json', 'main.swift', raw),
                    'generated input/before tree')

    def test_generated_fixture_receipt_cannot_be_rewritten(self):
        self.reject(lambda: self.replace_record('0001.before.json', 'native-fixture.json', b'{}\n'),
                    'generated input/before tree')

    def test_dependency_target_must_equal_exact_product(self):
        raw = (OUTPUT + '/different-target: ' + OUTPUT + '/bounded-fault-apple.cpp\n').encode()
        self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal.d', raw),
                    'dependency rule target')

    def test_dependency_first_source_must_be_generated_native_fixture(self):
        raw = (OUTPUT + '/bounded-fault-normal: ' + OWNER + '/Native/Loader/elf_loader_emulator.cpp\n').encode()
        self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal.d', raw),
                    'dependency source')

    def test_dependency_paths_cannot_escape_or_alias_verified_roots(self):
        for suffix in ('/tmp/unretained.h', OWNER + '/../escape.h', 'relative.h',
                       HEADER + '/../unicorn.h', OWNER + '/missing-source.h'):
            with self.subTest(path=suffix):
                raw = (OUTPUT + '/bounded-fault-normal: ' + OUTPUT + '/bounded-fault-apple.cpp ' + suffix + '\n').encode()
                self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal.d', raw))

    def test_dependency_duplicates_encoding_and_bounds_rejected(self):
        target = OUTPUT + '/bounded-fault-normal'
        source = OUTPUT + '/bounded-fault-apple.cpp'
        for raw in ((target + ': ' + source + ' ' + source + '\n').encode(),
                    (target + ': ' + source).encode(),
                    (target + ': ' + source + '\x00\n').encode(),
                    (target + ': ' + source + ' extra:rule\n').encode(),
                    b'x' * 65537 + b'\n'):
            with self.subTest(raw=raw[:100]):
                self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal.d', raw))

    def test_dependency_file_omission_is_rejected(self):
        self.reject(lambda: self.remove_record('0001.after.json', 'bounded-fault-normal.d'),
                    'dependency file required')

    def test_dependency_blob_and_identity_hashes_are_verified(self):
        record = self.record('0001.after.json', 'bounded-fault-normal.d')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/' + record['blob_path'], b'changed'),
                    'raw length/hash mismatch')
        for key in ('sha256', 'git_blob_sha1', 'git_blob_sha256'):
            with self.subTest(key=key):
                def mutate(value):
                    row = next(r for r in value['output']['entries'] if r['path'] == 'bounded-fault-normal.d')
                    row[key] = '0' * len(row[key])
                self.reject(lambda: self.mutate_json('0001.after.json', mutate))

    def test_dependency_file_must_be_ordinary_nonexecutable(self):
        raw = raw_reader(self.files)(self.record('0001.after.json', 'bounded-fault-normal.d'), NAMESPACE)
        self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal.d', raw, '0755'),
                    'ordinary original compiler dependency')

    def test_extra_compiler_output_is_rejected(self):
        def extra(value):
            row = copy.deepcopy(next(r for r in value['output']['entries'] if r['path'] == 'bounded-fault-normal.d'))
            row.update(path='unexpected.d', source_path=OUTPUT + '/unexpected.d', label='0001/after/output:unexpected.d')
            value['output']['entries'].append(row)
            value['output']['entries'].sort(key=lambda r: r['path'])
        self.reject(lambda: self.mutate_json('0001.after.json', extra), 'extra/missing compiler-produced')

    def test_command_argv_cwd_and_order_are_exact(self):
        for key, value in (('argv', ['true']), ('cwd', '/elsewhere')):
            with self.subTest(field=key):
                self.reject(lambda: self.mutate_json('0001.command.json', lambda row: row.__setitem__(key, value)),
                            'command/argv/cwd/environment')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/0001.command.json',
                                                 self.files[NAMESPACE + '/0002.command.json']),
                    'command/argv/cwd/environment')

    def test_sanitizer_environment_must_be_exact(self):
        for key, value in (('ASAN_OPTIONS', 'detect_leaks=1'), ('UBSAN_OPTIONS', 'halt_on_error=0'),
                           ('LD_PRELOAD', '/tmp/inject.so')):
            with self.subTest(key=key):
                self.reject(lambda: self.mutate_json('0002.command.json',
                    lambda row: row['environment'].__setitem__(key, value)), 'command/argv/cwd/environment')

    def test_failed_command_and_nonempty_stderr_rejected(self):
        self.reject(lambda: self.mutate_json('0001.result.json', lambda row: row.__setitem__('returncode', 1)),
                    'command failed')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/0002.stderr', b'unexpected warning\n'),
                    'stderr is nonempty')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/0001.stdout', b'compiler output\n'),
                    'compiler stdout')

    def test_native_assertion_counts_and_types_are_exact(self):
        for key, value in (('checks', 661), ('checks', '662'), ('failures', 1), ('failures', False),
                           ('synthetic_api_starts', 4)):
            with self.subTest(key=key, value=value):
                bad = {**self.module.NATIVE_EXPECTED, key: value}
                self.reject(lambda: self.mutate_stdout_coherently(2, encode(bad)),
                            'native runtime differs')

    def test_native_guest_engine_and_proprietary_scope_rejected(self):
        for key, value in (('guest_execution', True), ('real_engine_starts', 1),
                           ('real_engine_starts', False), ('proprietary_input', True)):
            with self.subTest(key=key):
                bad = {**self.module.NATIVE_EXPECTED, key: value}
                self.reject(lambda: self.mutate_stdout_coherently(6, encode(bad)),
                            'native runtime differs')

    def test_each_native_variant_requires_its_runtime_assertions(self):
        for number in (2, 6, 10):
            with self.subTest(command=number):
                self.reject(lambda: self.mutate_stdout_coherently(number, b'{}\n'),
                            'native runtime differs')

    def test_nm_requires_all_real_commoncrypto_symbols(self):
        for symbol in (b'_CC_SHA256_Init', b'_CC_SHA256_Update', b'_CC_SHA256_Final'):
            with self.subTest(symbol=symbol):
                raw = self.original[NAMESPACE + '/0003.stdout'].replace(symbol, symbol + b'_fake')
                self.reject(lambda: self.mutate_stdout_coherently(3, raw),
                            'CommonCrypto symbol reference missing')

    def test_nm_rejects_real_unicorn_engine_reference(self):
        for number in (3, 7, 11):
            with self.subTest(command=number):
                raw = self.original[NAMESPACE + f'/{number:04d}.stdout'] + b'                 U _uc_emu_start\n'
                self.reject(lambda: self.mutate_stdout_coherently(number, raw),
                            'real engine reference')

    def test_otool_requires_system_and_rejects_forbidden_linkage(self):
        for raw in (b'no dylibs\n', b'/usr/lib/libSystem.B.dylib\nlibunicorn.dylib\n',
                    b'/usr/lib/libSystem.B.dylib\nlibcrypto.dylib\n',
                    b'/usr/lib/libSystem.B.dylib\nLIBSSL.dylib\n'):
            with self.subTest(raw=raw):
                self.reject(lambda: self.mutate_stdout_coherently(4, raw),
                            'unexpected native diagnostic linkage')

    def test_swift_requires_exact_completion_both_variants(self):
        for number in (14, 16):
            for raw in (b'', SWIFT_COMPLETION.replace(b':77', b':76'),
                        SWIFT_COMPLETION.splitlines(keepends=True)[0], SWIFT_COMPLETION + b'extra\n'):
                with self.subTest(command=number, output=raw):
                    self.reject(lambda: self.mutate_stdout_coherently(number, raw),
                                'exact Swift decoder/boundary')

    def test_native_and_swift_products_cannot_be_omitted(self):
        for number, path in ((1, 'bounded-fault-normal'), (13, 'swift-boundaries-normal')):
            with self.subTest(product=path):
                self.reject(lambda: self.remove_record(f'{number:04d}.after.json', path),
                            'compiler product raw bytes/executable mode missing')

    def test_compiler_product_mode_and_empty_bytes_rejected(self):
        for raw, mode in ((b'', '0755'), (b'product', '0644')):
            with self.subTest(mode=mode, raw=raw):
                self.reject(lambda: self.replace_record('0001.after.json', 'bounded-fault-normal', raw, mode),
                            'compiler product raw bytes/executable mode missing')

    def test_sanitized_dsym_closure_is_mandatory(self):
        dsym = 'bounded-fault-sanitized.dSYM'
        self.reject(lambda: self.remove_record('0009.after.json', dsym, recursive=True),
                    'missing or unrequested source-derived compiler debug sidecar')
        for suffix in ('/Contents/Info.plist', '/Contents/Resources/DWARF/bounded-fault-sanitized',
                       '/Contents/Resources/Relocations/aarch64/bounded-fault-sanitized.yml'):
            with self.subTest(path=suffix):
                self.reject(lambda: self.remove_record('0009.after.json', dsym + suffix))

    def test_dsym_relocation_yaml_is_exact(self):
        path = 'bounded-fault-sanitized.dSYM/Contents/Resources/Relocations/aarch64/bounded-fault-sanitized.yml'
        self.reject(lambda: self.replace_record('0009.after.json', path, b'---\nrelocations: [tampered]\n'),
                    'Darwin relocation YAML differs')

    def test_runtime_cannot_change_existing_product(self):
        self.reject(lambda: self.replace_record('0002.after.json', 'bounded-fault-normal', b'changed binary', '0755'),
                    'runtime mutated retained inputs')

    def test_final_tree_product_and_generated_result_must_match(self):
        self.reject(lambda: self.remove_record('final-output.json', 'swift-boundaries-optimized'),
                    'final generated/result/product tree differs')
        self.reject(lambda: self.replace_record('final-output.json', 'diagnostic-results.json', b'{}\n'),
                    'final generated/result/product tree differs')

    def test_command_file_and_blob_closure_cannot_gain_or_lose_members(self):
        self.reject(lambda: self.files.pop(NAMESPACE + '/0016.result.json'), 'missing original nested file')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/0017.command.json', b'{}\n'),
                    'nested original file closure differs')
        self.reject(lambda: self.files.__setitem__(NAMESPACE + '/blobs/sha256/00/' + '0' * 64, b'junk'),
                    'nested original file closure differs')

    def test_raw_retention_and_top_level_counts_must_match(self):
        self.reject(lambda: self.mutate_json('retention-summary.json', lambda row: row.__setitem__('nested_commands', 15)),
                    'raw accounting differs')
        self.reject(lambda: self.files.__setitem__('provenance/host-run-diagnostic-checks.json',
                    encode({**diagnostic.COUNTS, 'native_assertions': 1985})), 'top-level result differs')
        self.reject(lambda: self.files.__setitem__('logs/host-run-diagnostic-checks.log', b'fabricated success\n'),
                    'top-level stdout differs')


    def diagnostic_row(self):
        record = self.record('final-output.json', 'diagnostic-results.json')
        return h.parse(raw_reader(self.files)(record, NAMESPACE))

    def test_reviewed_split_has_two_ordinary_compiles_and_fourteen_sandboxed_rows(self):
        row = self.diagnostic_row()
        context = {'owner': OWNER, 'include': CONTEXT['work'] + '/host-unicorn-headers', 'output': OUTPUT}
        self.assertEqual(row['command_context'], context)
        plan = self.module.command_plan(context)
        self.assertEqual(len(plan), 16)
        for number, (expected, result) in enumerate(zip(plan, row['results']), 1):
            with self.subTest(number=number):
                compile_only = number in (13, 15)
                self.assertEqual(expected['sandbox_policy'], 'apple_plugin_sandbox_compile' if compile_only else 'network_denied')
                self.assertEqual(expected['argv'], expected['logical_argv'] if compile_only else [*self.module.SANDBOX, *expected['logical_argv']])
                for field, value in expected.items():
                    self.assertEqual(result[field], value)
                for suffix in ('.command.json', '.result.json'):
                    self.assertEqual(h.parse(self.files[NAMESPACE + f'/{number:04d}' + suffix])['argv'], expected['argv'])
                self.assertEqual(result['stdout'], self.files[NAMESPACE + f'/{number:04d}.stdout'].decode())
                self.assertEqual(result['stderr'], self.files[NAMESPACE + f'/{number:04d}.stderr'].decode())
        self.assertEqual(self.module.verify_result(row, context), diagnostic.COUNTS)
        self.verify()

    def test_raw_command_and_result_policy_substitution_rejected_for_all_sixteen_rows(self):
        plan = self.module.command_plan(self.diagnostic_row()['command_context'])
        for number, dispatch in enumerate(plan, 1):
            # Both raw receipts can agree with one another and still be wrong.
            substituted = ([*self.module.SANDBOX, *dispatch['logical_argv']] if number in (13, 15)
                           else dispatch['logical_argv'])
            def mutate():
                for suffix in ('.command.json', '.result.json'):
                    self.mutate_json(f'{number:04d}' + suffix, lambda row: row.__setitem__('argv', substituted))
            with self.subTest(number=number):
                self.reject(mutate, 'command/argv/cwd/environment')

    def test_raw_result_argv_substitution_cannot_hide_behind_valid_command(self):
        for number in (1, 2, 3, 4, 13, 14, 15, 16):
            with self.subTest(number=number):
                self.reject(lambda: self.mutate_json(f'{number:04d}.result.json',
                    lambda row: row.__setitem__('argv', ['true'])), 'command failed or differs')

    def test_result_row_policy_logical_executed_order_count_and_schema_are_exact(self):
        original = self.diagnostic_row()
        changes = [lambda row: row['results'][0].__setitem__('sandbox_policy', 'apple_plugin_sandbox_compile'),
                   lambda row: row['results'][12].__setitem__('sandbox_policy', 'network_denied'),
                   lambda row: row['results'][1].__setitem__('logical_argv', ['true']),
                   lambda row: row['results'][1].__setitem__('argv', row['results'][1]['logical_argv']),
                   lambda row: row['results'][0].__setitem__('extra', True),
                   lambda row: row['results'].reverse(), lambda row: row['results'].pop(),
                   lambda row: row['results'].append(copy.deepcopy(row['results'][-1]))]
        for change in changes:
            candidate = copy.deepcopy(original); change(candidate)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.module.verify_result(candidate, original['command_context'])

    def test_internally_consistent_result_roots_cannot_replace_trusted_outer_context(self):
        candidate = self.diagnostic_row()
        trusted = candidate['command_context']
        wrong = {key: value.replace('/capture/work', '/different/work') for key, value in trusted.items()}
        candidate['command_context'] = wrong
        original_cpp = self.module.ordinary(ROOT, '.ci/native-tests/fixtures/bounded_fault_host.cpp').read_text()
        candidate['native_fixture'] = self.module.adapt_native_fixture(original_cpp, Path(wrong['owner']))[1]
        for result, dispatch in zip(candidate['results'], self.module.command_plan(wrong)):
            result.update(dispatch)
        with self.assertRaisesRegex(ValueError, 'context differs from trusted outer paths'):
            self.module.verify_result(candidate, trusted)

    def test_caller_context_cannot_substitute_for_actual_outer_command(self):
        wrong = {**CONTEXT, 'work': '/different/work'}
        with self.assertRaisesRegex(ValueError, 'outer command/context differs'):
            diagnostic.DiagnosticLane(self.files, ROOT, wrong, raw_reader(self.files), self.module, HEADERS)

    def test_outer_owner_include_output_flags_are_independently_bound(self):
        key = 'logs/host-run-diagnostic-checks.command.json'
        for flag in ('--owner', '--unicorn-include', '--output', '--temporary', '--evidence', '--driver'):
            def mutate():
                row = h.parse(self.files[key]); row['argv'][row['argv'].index(flag) + 1] = '/unreviewed/root'
                self.files[key] = encode(row)
            with self.subTest(flag=flag):
                self.reject(mutate, 'outer command/context differs')

    def test_outer_supervisor_requires_ordinary_exact_dispatch_and_original_receipt(self):
        key = 'logs/host-run-diagnostic-checks.command.json'
        def wrap():
            row = h.parse(self.files[key]); row['argv'] = [*self.module.SANDBOX, *row['argv']]
            self.files[key] = encode(row)
        self.reject(wrap, 'outer command/context differs')
        self.reject(lambda: self.files.pop(key), 'outer command missing')

    def test_final_result_bytes_cannot_replace_observed_raw_streams(self):
        row = self.diagnostic_row()
        for field, value in (('stdout', '{}\n'), ('stderr', 'warning\n'), ('returncode', 1)):
            def mutate():
                changed = copy.deepcopy(row); changed['results'][1][field] = value
                self.replace_record('final-output.json', 'diagnostic-results.json', encode(changed))
            with self.subTest(field=field):
                self.reject(mutate, 'final generated/result/product tree differs')

    def test_diagnostic_result_join_rejects_observed_row_substitution(self):
        with mock.patch('subprocess.run', side_effect=AssertionError('native subprocess is forbidden')):
            lane = diagnostic.DiagnosticLane(self.files, ROOT, CONTEXT, raw_reader(self.files), self.module, HEADERS)
            lane.execute()
            lane.observed_results[0] = {**lane.observed_results[0], 'returncode': False}
            with self.assertRaisesRegex(ValueError, 'result rows differ from observed'):
                lane.finish()

    def test_raw_crlf_streams_preserve_observer_text_normalization(self):
        key = NAMESPACE + '/0002.stdout'
        self.files[key] = self.files[key].replace(b'\n', b'\r\n')
        self.assertEqual(self.verify()['native_assertions'], 1986)


if __name__ == '__main__':
    unittest.main()
