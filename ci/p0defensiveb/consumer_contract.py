"""Exact maintained consumer tests; source equivalence is not full graph admission.

The only runtime programs are bounded synthetic C++ header fixtures and Swift
parser/wire/host-render harnesses. The enclosing capture must deny network access
and own the process group. No provider, credentials, guest or native engine runs.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

SCHEMA = 'p0-defensive-ab-consumers-v1'
SOURCE_BASELINES = {
    'SideStore': 'd507f9e417f12c262b4d7e717c84d4a244c8e625',
    'LiveContainer': '545438e1f0a89fdef375f73273c5c9fc2735cbce',
    'AnisetteKit': '227dfd8c8456cd62e4ceff4971b17afb2003d7e8',
}
SUITE_IDS = {
    'init_diagnostics': tuple('test_contract.InitializerDiagnosticContract.' + name for name in (
        'test_actual_swift_parser_service_wire_and_host_copy',
        'test_bounded_primary_only_contract_and_no_recovery_mutation',
        'test_real_native_producer_fixture',
        'test_shared_capture_validation_and_copy_contracts_match',
        'test_trace_disabled_preserves_constructor_evidence')),
    'adi_consumption': tuple('test_contract.ConsumerContractTests.' + name for name in (
        'test_disabled_trace_preserves_classification_and_drops_diagnostics',
        'test_legacy_comparison_is_read_only_snapshot_bound_and_failure_scoped',
        'test_native_pipeline_wire_copy_and_importing_host',
        'test_real_cpp_producer_descriptor_and_pinned_schema',
        'test_shared_parser_and_schema_are_exact_across_owners',
        'test_wire_and_render_use_real_finite_contract')),
    'login_trace': tuple('test_contract.LoginTraceContract.' + name for name in (
        'test_finite_parser_and_existing_limits',
        'test_operation_ownership_and_fail_closed_paths',
        'test_parser_render_and_validator_match',
        'test_producer_stage_range_and_generated_correlation',
        'test_real_swift_parser_and_wire',
        'test_real_swift_timeout_host_retention_and_copy',
        'test_timeout_adds_diagnostics_without_changing_terminal_policy',
        'test_timeout_host_retention_is_diagnostic_only')),
}
ROOT_ENV = ('SIDE_STORE_TEST_SOURCE', 'LIVE_CONTAINER_TEST_SOURCE',
            'MAINTAINED_LIVE_CONTAINER_TEST_SOURCE', 'ANISETTE_KIT_TEST_SOURCE',
            'INIT_DIAGNOSTICS_PEER_ROOT', 'INIT_DIAGNOSTICS_PRODUCER_ROOT',
            'ADI_CONSUMPTION_PEER_ROOT', 'ADI_CONSUMPTION_PRODUCER_ROOT',
            'LOGIN_TRACE_PEER_ROOT', 'LOGIN_TRACE_PRODUCER_ROOT')
MAX_SOURCE_BYTES = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def ordinary_bytes(root, name, limit=MAX_SOURCE_BYTES):
    root = Path(root)
    require(root.is_absolute() and root.is_dir() and root.resolve() == root,
            'canonical ordinary source root required')
    require(isinstance(name, str) and name and not name.startswith('/') and
            all(part not in ('', '.', '..') for part in name.split('/')), 'unsafe source-relative name')
    path = root
    for part in name.split('/'):
        path /= part
        require(not path.is_symlink(), 'source symlink forbidden: ' + name)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'missing or oversized ordinary source: ' + name)
    raw = path.read_bytes()
    after = path.stat()
    signature = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    require(signature(before) == signature(after) and len(raw) == before.st_size,
            'source mutated during read: ' + name)
    return raw


def git_identity(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_NO_REPLACE_OBJECTS='1', GIT_GRAFT_FILE=os.devnull,
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    command = ['git', '--no-replace-objects', '-c', 'core.hooksPath=' + os.devnull,
               '-c', 'core.fsmonitor=false', '-C', str(root), 'rev-parse', 'HEAD', 'HEAD^{tree}']
    value = subprocess.check_output(command, env=env, stderr=subprocess.PIPE, timeout=15).decode('ascii').splitlines()
    require(len(value) == 2 and all(re.fullmatch('[0-9a-f]{40}', row) for row in value), 'ordinary Git identity required')
    return {'commit': value[0], 'tree': value[1]}


def verify_sources(roots):
    require(set(roots) == set(SOURCE_BASELINES), 'exact consumer owner roots required')
    require(len(set(roots.values())) == 3, 'owner roots must be distinct')
    result = {}
    for owner, baseline in SOURCE_BASELINES.items():
        root = Path(roots[owner])
        require(root.is_absolute() and root.resolve(strict=True) == root, 'canonical owner root required')
        identity = git_identity(root)
        # SideStore may be a separately admitted gitlink-only child of d507.
        # The enclosing graph gate, not this source-slice check, admits that child.
        if owner != 'SideStore':
            require(identity['commit'] == baseline, 'wrong exact ' + owner + ' checkout')
        files = {}
        for name, expected in SOURCE_SHA256[owner].items():
            raw = ordinary_bytes(root, name)
            actual = hashlib.sha256(raw).hexdigest()
            require(actual == expected, 'consumer source drift: ' + owner + '/' + name)
            files[name] = {'sha256': actual, 'bytes': len(raw)}
        result[owner] = {'root': str(root), **identity, 'source_baseline': baseline, 'files': files}
    return result


def require_tools():
    result = {}
    for name in ('swiftc', 'c++', 'git'):
        path = shutil.which(name)
        require(path is not None and Path(path).is_file() and os.access(path, os.X_OK),
                'required consumer tool unavailable: ' + name)
        result[name] = str(Path(path).absolute())
    return result


@contextmanager
def consumer_environment(root, peer, producer, owner):
    previous = {key: os.environ.get(key) for key in (*ROOT_ENV, 'PYTHONDONTWRITEBYTECODE')}
    old_bytecode = sys.dont_write_bytecode
    try:
        for key in ROOT_ENV:
            os.environ.pop(key, None)
        os.environ['SIDE_STORE_TEST_SOURCE' if owner == 'SideStore' else 'LIVE_CONTAINER_TEST_SOURCE'] = str(root)
        for prefix in ('INIT_DIAGNOSTICS', 'ADI_CONSUMPTION', 'LOGIN_TRACE'):
            os.environ[prefix + '_PEER_ROOT'] = str(peer)
            os.environ[prefix + '_PRODUCER_ROOT'] = str(producer)
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        sys.dont_write_bytecode = True
        yield
    finally:
        sys.dont_write_bytecode = old_bytecode
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


class ExactResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids = []
        self.success_ids = []

    def startTest(self, test):
        self.started_ids.append(test.id())
        super().startTest(test)

    def addSuccess(self, test):
        self.success_ids.append(test.id())
        super().addSuccess(test)


def result_record(result, expected):
    row = {'tests': result.testsRun, 'failures': len(result.failures),
           'errors': len(result.errors), 'skipped': len(result.skipped),
           'expected_failures': len(result.expectedFailures),
           'unexpected_successes': len(result.unexpectedSuccesses),
           'test_ids': list(result.started_ids), 'successful_test_ids': list(result.success_ids)}
    row['status'] = 'passed' if (
        result.wasSuccessful() and row['tests'] == len(expected) and
        row['test_ids'] == list(expected) and row['successful_test_ids'] == list(expected) and
        not any(row[key] for key in ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes'))
    ) else 'failed'
    return row


def run_suite(root, peer, producer, owner, group, *, stream=None):
    require(group in SUITE_IDS and owner in ('SideStore', 'LiveContainer'), 'fixed consumer suite required')
    script = root / 'tests' / group / 'test_contract.py'
    previous = sys.modules.pop('test_contract', None)
    try:
        with consumer_environment(root, peer, producer, owner):
            spec = importlib.util.spec_from_file_location('test_contract', script)
            require(spec is not None and spec.loader is not None, 'fixed test import unavailable')
            module = importlib.util.module_from_spec(spec)
            sys.modules['test_contract'] = module
            spec.loader.exec_module(module)
            require(Path(module.ROOT) == root and Path(module.PEER) == peer and Path(module.PRODUCER) == producer,
                    'consumer root selection differs')
            suite = unittest.TestLoader().loadTestsFromModule(module)
            expected = SUITE_IDS[group]
            require([test.id() for test in flatten(suite)] == list(expected), 'exact consumer discovery IDs differ')
            result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=ExactResult).run(suite)
            return result_record(result, expected)
    finally:
        sys.modules.pop('test_contract', None)
        if previous is not None:
            sys.modules['test_contract'] = previous


def validate_results(owners):
    require(set(owners) == {'SideStore', 'LiveContainer'}, 'both consumer owners required')
    for owner, suites in owners.items():
        require(set(suites) == set(SUITE_IDS), 'exact consumer suites required: ' + owner)
        for group, expected in SUITE_IDS.items():
            row = suites[group]
            require(row.get('status') == 'passed' and type(row.get('tests')) is int and row['tests'] == len(expected),
                    'consumer count or status differs: ' + owner + '/' + group)
            require(row.get('test_ids') == list(expected) and row.get('successful_test_ids') == list(expected),
                    'consumer executed IDs differ: ' + owner + '/' + group)
            require(all(type(row.get(key)) is int and row[key] == 0 for key in
                        ('failures', 'errors', 'skipped', 'expected_failures', 'unexpected_successes')),
                    'consumer failure, error or skip: ' + owner + '/' + group)
    return {'tests': 38, 'failures': 0, 'errors': 0, 'skipped': 0,
            'expected_failures': 0, 'unexpected_successes': 0}


# Exact source slices read by the maintained tests, not mutable caller inputs.
SOURCE_SHA256 = {'SideStore': {'AltStore/AppDelegate.swift': '73fb0db0bca4188b346be0429bcdac19df7fdb963c21f649e3bff73d523ace21',
               'AltStore/Core/Components/Keychain.swift': '81c362a03323ca9c658a34b5b2883b2af3bacc81d8be079c04a0dfcdf3bf8584',
               'SideStore/Core/Anisette/OnDeviceAnisetteManager.swift': '376b4f306fafc0a2ab26564abde0237e0daec253dd0bc35ef7c2ee9fc92d48b9',
               'SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift': '44a6744a62f2602d1511a13e49b79f4a402916aec13c74aa22c47584d3dddd7f',
               'docs/debug-adi-consumption/contract-v2.json': 'a4ac915cedf8c67179a184e8ea926968a439ae6c5e7bec6e18f58a5bd162b5ed',
               'tests/adi_consumption/external_error_doubles.swift': '9c8a2ab61a318a6e1bbee4e25d0908f4501b55a194f35e9e11b15a82204f3f93',
               'tests/adi_consumption/legacy_comparison_harness.swift': 'f6247675e12c3d52a0f56d58e353f604af177e17a2f5ebadb901c73b1fdffc1e',
               'tests/adi_consumption/pipeline_harness.swift': '4d8c636ce292b55899ab377e6ffaec6ceb5a403850a14e38af8c1d72e5414df9',
               'tests/adi_consumption/test_contract.py': 'b03830d266d17a0ae46c5c0dda22dad80fb20a5dbde4baa496894d862b87a382',
               'tests/init_diagnostics/README.md': 'ac387746654346f54e4625f032c7f13c6d5ee6e86e01f6874b2fba3955458f01',
               'tests/init_diagnostics/host_harness.swift': '0fb86b7bf3dfe4677292971c41d7d226c4cb6c1395035612b101948f5e8004a9',
               'tests/init_diagnostics/native_fixture.cpp': 'b1dfcd27822ee7e4ec9c203b956b25d8fdd8ed6afe961ad12547ffe4244187a0',
               'tests/init_diagnostics/pipeline_harness.swift': 'b1a46066f24a9cda5654e74aaa789b1f5d775da7cc6fbbf6f30c7febfa5039ae',
               'tests/init_diagnostics/test_contract.py': '0cd8d339e7629ef07a2b743193ff193eb64722432ad50d70d5cb359597f50196',
               'tests/login_trace/README.md': 'd1dabfb89f126827972ae0581c0effb30abee68b379088a66ac81ad03690ca7e',
               'tests/login_trace/host_harness.swift': '5dd5ea6613dd6aaf0e489a235e9ffb54a4631fadaa9cc1cbc0c86b04a3a2d263',
               'tests/login_trace/test_contract.py': '6c2fa4889943c60cf304f9e969d4a40d403b983e779515d93220070d98a8035f',
               'tests/login_trace/timeout_host_harness.swift': 'd66fbc1f00b9ddc1a796533a5ef4971184ef4f4f26151666c6e1fc5f5c4b9eb3'},
 'LiveContainer': {'LiveContainerSwiftUI/Views/V3UnifiedShell.swift': '406d1d7b5502dccfa2cd37afa75e4903611c1d42ffd5235190c08804d64dd56e',
                   'SideStoreSupport/SideStore.swift': 'b097483d27d3ab395fc82a68c9392b51bdceb4df23ebcda981bc2d9e68198aae',
                   'docs/debug-adi-consumption/contract-v2.json': 'a4ac915cedf8c67179a184e8ea926968a439ae6c5e7bec6e18f58a5bd162b5ed',
                   'tests/adi_consumption/external_error_doubles.swift': '9c8a2ab61a318a6e1bbee4e25d0908f4501b55a194f35e9e11b15a82204f3f93',
                   'tests/adi_consumption/legacy_comparison_harness.swift': 'f6247675e12c3d52a0f56d58e353f604af177e17a2f5ebadb901c73b1fdffc1e',
                   'tests/adi_consumption/pipeline_harness.swift': '4d8c636ce292b55899ab377e6ffaec6ceb5a403850a14e38af8c1d72e5414df9',
                   'tests/adi_consumption/test_contract.py': 'b03830d266d17a0ae46c5c0dda22dad80fb20a5dbde4baa496894d862b87a382',
                   'tests/init_diagnostics/README.md': 'ac387746654346f54e4625f032c7f13c6d5ee6e86e01f6874b2fba3955458f01',
                   'tests/init_diagnostics/host_harness.swift': '0fb86b7bf3dfe4677292971c41d7d226c4cb6c1395035612b101948f5e8004a9',
                   'tests/init_diagnostics/native_fixture.cpp': 'b1dfcd27822ee7e4ec9c203b956b25d8fdd8ed6afe961ad12547ffe4244187a0',
                   'tests/init_diagnostics/pipeline_harness.swift': 'b1a46066f24a9cda5654e74aaa789b1f5d775da7cc6fbbf6f30c7febfa5039ae',
                   'tests/init_diagnostics/test_contract.py': '0cd8d339e7629ef07a2b743193ff193eb64722432ad50d70d5cb359597f50196',
                   'tests/login_trace/README.md': 'd1dabfb89f126827972ae0581c0effb30abee68b379088a66ac81ad03690ca7e',
                   'tests/login_trace/host_harness.swift': '5dd5ea6613dd6aaf0e489a235e9ffb54a4631fadaa9cc1cbc0c86b04a3a2d263',
                   'tests/login_trace/test_contract.py': '6c2fa4889943c60cf304f9e969d4a40d403b983e779515d93220070d98a8035f',
                   'tests/login_trace/timeout_host_harness.swift': 'd66fbc1f00b9ddc1a796533a5ef4971184ef4f4f26151666c6e1fc5f5c4b9eb3'},
 'AnisetteKit': {'Native/Loader/adi_consumption_debug.h': '077b377c87b201893f83afbff5a4dd37e01354253f08045a3831adcb50022346',
                 'Native/Loader/vm_initialization_diagnostics.h': '0fbe1ac033f2d2dbe7f3c5fbd0cade277f8e7eb51529264dfec3ca75279ba862',
                 'Sources/AnisetteDataProvider.swift': '2b3913be77f019de3f0520e8ea8fcdad1a1b4a638c2493e84d063f07f813e855',
                 'Sources/LoginDiagnosticTrace.swift': 'bd86c77eb520cf0721cfbbdb1e9100261bd53324ef0f912713873357fc76ae2e'}}


class ConsumerObserver:
    """Capture only the three sealed consumers' finite subprocess.run forms.

    check_output delegates to run and is observed too. Both binary and text
    callers retain the raw pre-decode streams. Nested programs inherit the outer
    capture's process group; cleanup and network denial belong to that wrapper.
    """
    MAX_COMMANDS = 128
    MAX_TIMEOUT = 180
    ENV_KEYS = ('DEVELOPER_DIR', 'PATH', 'HOME', 'TMPDIR', 'ASAN_OPTIONS', 'UBSAN_OPTIONS',
                'PYTHONDONTWRITEBYTECODE', 'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH', *ROOT_ENV)

    def __init__(self, evidence, temporary, tools, *, budget=None):
        from retention import RawStore
        self.root = Path(evidence)
        self.temporary = Path(temporary)
        require(self.root.is_absolute() and self.temporary.is_absolute(), 'absolute observation paths required')
        require(not self.root.exists() and not self.temporary.exists(), 'fresh observation paths required')
        require(self.root != self.temporary and self.root not in self.temporary.parents and
                self.temporary not in self.root.parents, 'observation paths must not overlap')
        self.root.mkdir(parents=True)
        self.temporary.mkdir(parents=True)
        require(self.root.resolve() == self.root and self.temporary.resolve() == self.temporary,
                'canonical observation paths required')
        self.store = RawStore(self.root,budget=budget)
        self.tools = {str(Path(tools[name]).absolute()) for name in ('swiftc', 'c++')}
        self.counter = 0
        self.original = None

    def snapshot(self, prefix, phase):
        value = self.store.retain_tree(self.temporary, label=prefix.name + '/' + phase + '/temporary')
        dump(prefix.with_suffix('.' + phase + '.json'), {'temporary': value})

    def command(self, args, kwargs):
        require(len(args) == 1 and isinstance(args[0], (list, tuple)) and 0 < len(args[0]) <= 128,
                'nested consumer argv must be one bounded list')
        argv = args[0]
        require(all(isinstance(value, (str, os.PathLike)) and len(os.fspath(value)) <= 4096 for value in argv),
                'nested consumer argv item differs')
        allowed = {'capture_output', 'timeout', 'text', 'check', 'stdout', 'stderr', 'env'}
        require(set(kwargs) <= allowed, 'unreviewed consumer subprocess option')
        require(type(kwargs.get('timeout')) in (int, float) and 0 < kwargs['timeout'] <= self.MAX_TIMEOUT,
                'bounded consumer timeout required')
        require(type(kwargs.get('check', False)) is bool and type(kwargs.get('text', False)) is bool,
                'ordinary consumer result mode required')
        if kwargs.get('capture_output') is True:
            require('stdout' not in kwargs and 'stderr' not in kwargs, 'ambiguous nested stream capture')
        else:
            require('capture_output' not in kwargs and kwargs.get('stdout') == subprocess.PIPE and
                    kwargs.get('stderr') in (None, subprocess.PIPE), 'unreviewed nested stream mode')
        path = Path(argv[0])
        require(path.is_absolute(), 'absolute nested executable required')
        if str(path) not in self.tools:
            require(self.temporary in path.parents and path.resolve(strict=True) == path and
                    path.is_file() and os.access(path, os.X_OK), 'nested executable outside generated fixture tree')
        env = kwargs.get('env', os.environ)
        require(isinstance(env, (dict, os._Environ)), 'ordinary nested environment required')
        return [os.fspath(value) for value in argv], env

    def recorded(self, *args, **kwargs):
        argv, env = self.command(args, kwargs)
        self.counter += 1
        require(self.counter <= self.MAX_COMMANDS, 'consumer nested command bound exceeded')
        prefix = self.root / f'{self.counter:04d}'
        record = {'argv': argv, 'cwd': str(Path.cwd()), 'timeout_seconds': kwargs['timeout'],
                  'text_requested': kwargs.get('text', False),
                  'environment': {key: env[key] for key in self.ENV_KEYS if key in env},
                  'returncode': None, 'status': 'started'}
        dump(prefix.with_suffix('.command.json'), record)
        self.snapshot(prefix, 'before')
        stdout = stderr = b''
        binary = dict(kwargs)
        binary.pop('capture_output', None)
        binary.update(text=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            result = self.original(*args, **binary)
            stdout, stderr = result.stdout or b'', result.stderr or b''
            record.update(returncode=result.returncode, status='completed')
            if kwargs.get('text', False):
                decode = lambda raw: raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
                result.stdout, result.stderr = decode(stdout), decode(stderr)
            return result
        except BaseException as error:
            stdout, stderr = getattr(error, 'stdout', None) or stdout, getattr(error, 'stderr', None) or stderr
            record.update(returncode=getattr(error, 'returncode', None), status='failed', error=type(error).__name__)
            raise
        finally:
            require(isinstance(stdout, bytes) and isinstance(stderr, bytes), 'nested streams must be raw bytes')
            require(len(stdout) <= 16 * 1024 * 1024 and len(stderr) <= 16 * 1024 * 1024,
                    'nested stream byte bound exceeded')
            prefix.with_suffix('.stdout').write_bytes(stdout)
            prefix.with_suffix('.stderr').write_bytes(stderr)
            record['stdout'] = self.store.retain_bytes(stdout, label=prefix.name + '/stdout')
            record['stderr'] = self.store.retain_bytes(stderr, label=prefix.name + '/stderr')
            self.snapshot(prefix, 'after')
            dump(prefix.with_suffix('.result.json'), record)
            dump(self.root / 'retention-summary.json', self.summary())

    def summary(self):
        return {**self.store.summary(), 'nested_commands': self.counter,
                'maximum_nested_commands': self.MAX_COMMANDS, 'maximum_timeout_seconds': self.MAX_TIMEOUT,
                'raw_before_decode': True, 'temporary_inputs_and_outputs_retained': True}

    def __enter__(self):
        self.old_tmp = os.environ.get('TMPDIR')
        self.old_tempdir = tempfile.tempdir
        os.environ['TMPDIR'] = str(self.temporary)
        tempfile.tempdir = str(self.temporary)
        self.original = subprocess.run
        subprocess.run = self.recorded
        return self

    def __exit__(self, kind, value, traceback):
        subprocess.run = self.original
        tempfile.tempdir = self.old_tempdir
        if self.old_tmp is None:
            os.environ.pop('TMPDIR', None)
        else:
            os.environ['TMPDIR'] = self.old_tmp
        dump(self.root / 'retention-summary.json', self.summary())


def run_all(root, peer, producer, output, observer_dir, temporary, *, stream=None,budget=None):
    roots = {'SideStore': Path(root), 'LiveContainer': Path(peer), 'AnisetteKit': Path(producer)}
    output = Path(output)
    require(output.is_absolute() and not output.exists(), 'fresh absolute consumer receipt required')
    require(all(output != path and path not in output.parents for path in roots.values()),
            'receipt must be outside source checkouts')
    for generated in (Path(observer_dir), Path(temporary)):
        require(generated.is_absolute() and all(
            generated != source and source not in generated.parents and generated not in source.parents
            for source in roots.values()), 'generated capture paths must not overlap source checkouts')
    output.parent.mkdir(parents=True, exist_ok=True)
    require(output.parent.resolve() == output.parent, 'canonical receipt path required')
    receipt = {'schema': SCHEMA, 'status': 'failed', 'owners': {},
               'scope': 'Synthetic host-only parser, wire, diagnostics and importing-renderer tests; no provider, credentials, native engine, guest, device or successful login execution',
               'source_graph_admission': 'required separately by enclosing capture',
               'network_denial': 'required separately by enclosing capture'}
    try:
        tools = require_tools()
        receipt['tools'] = tools
        receipt['sources_before'] = verify_sources(roots)
        observer = ConsumerObserver(observer_dir, temporary, tools,budget=budget)
        with observer:
            for owner, other in (('SideStore', 'LiveContainer'), ('LiveContainer', 'SideStore')):
                receipt['owners'][owner] = {}
                for group in SUITE_IDS:
                    receipt['owners'][owner][group] = run_suite(roots[owner], roots[other], roots['AnisetteKit'],
                                                               owner, group, stream=stream)
                    dump(output, receipt)
        receipt['nested_capture'] = {'directory': str(observer.root), **observer.summary()}
        receipt['sources_after'] = verify_sources(roots)
        require(receipt['sources_after'] == receipt['sources_before'], 'consumer sources mutated during execution')
        receipt['totals'] = validate_results(receipt['owners'])
        require(observer.counter > 0, 'missing nested consumer executions')
        receipt['status'] = 'passed'
    except BaseException as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        dump(output, receipt)
    return receipt
