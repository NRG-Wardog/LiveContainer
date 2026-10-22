"""Consolidated source-owned fake diagnostics; never links or executes native providers."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
STATUS = 'SOURCE_OWNED_FAKE_DIAGNOSTICS_PASS_NOT_RUNTIME_VALIDATION'
SUITES = ('legacy-response-core', 'auth-request', 'iloader-auth-parity', 'iloader-onboarding-scope', 'profile-provenance', 'wire-copy',
          'placed-pairing', 'deferred-device-setup')
COMMANDS = ('legacy-generate', 'legacy-compile', 'legacy-run',
            'auth-source', 'auth-generate', 'auth-compile', 'auth-run',
            'iloader-source', 'iloader-generate', 'iloader-compile', 'iloader-run',
            'onboarding-source', 'onboarding-generate', 'onboarding-compile', 'onboarding-run',
            'profile-source', 'profile-generate', 'profile-compile', 'profile-run',
            'wire-source', 'wire-generate', 'wire-service-compile', 'wire-host-compile',
            'wire-service-run', 'wire-host-run',
            'pairing-source', 'pairing-generate', 'pairing-compile', 'pairing-run',
            'deferred-source', 'deferred-generate', 'deferred-compile', 'deferred-run')
AUTH_FILES = ('CandidateAuthentication.swift', 'BaselineAuthentication.swift',
              'AuthenticationDiagnosticTrace.swift', 'Errors.swift', 'Types.swift',
              'BoundaryDoubles.swift', 'RuntimeTests.swift')
ILOADER_FILES = ('CandidateAuthentication.swift', 'AuthenticationDiagnosticTrace.swift',
                 'Errors.swift', 'Types.swift', 'BoundaryDoubles.swift',
                 'ILoaderRemoteAnisette.swift', 'RuntimeTests.swift')
ONBOARDING_FILES = ('CandidateOnboarding.swift', 'BoundaryDoubles.swift', 'RuntimeTests.swift')
ONBOARDING = 'SideStore/.ci/iloader-onboarding-scope'
REGISTRATION_SCHEMA = 'device-registration-cause-cases-v1'
ONBOARDING_REQUIRED_SOURCES = (
    'SideStore/AltStore/AppDelegate.swift',
    'SideStore/SideStore/Core/Auth/AuthManager.swift',
    'SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift',
    'SideStore/SideStore/Utils/concurrency/TaskChainCoalescer.swift',
    'SideStore/SideStore/Core/Anisette/AnisetteProvider.swift',
    'SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
    'SideSign/Sources/Anisette/ILoaderRemoteAnisette.swift',
)
SIGN = 'SideStore/Dependencies/SideSign'
AUTH = SIGN + '/.ci/auth-request-diagnostics'
ILOADER = SIGN + '/.ci/iloader-auth-parity'
ILOADER_OFFICIAL_REFERENCE = 'fc7a81a6de678aa707e05399ffafb8be0ad56921'
PROFILE = SIGN + '/.ci/profile-provenance'
WIRE = 'LiveContainer/.ci/comprehensive-diagnostics'
REQUIRED_INPUTS = {
    ONBOARDING + '/generate.py', ONBOARDING + '/test_source.py',
    'SideStore/SideStore/Core/Auth/AuthManager.swift',
    'SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift',
    'SideStore/SideStore/Utils/concurrency/TaskChainCoalescer.swift',
    AUTH + '/generate.py', AUTH + '/test_source.py',
    ILOADER + '/generate.py', ILOADER + '/test_source.py',
    SIGN + '/Sources/Anisette/ILoaderRemoteAnisette.swift',
    SIGN + '/Sources/DeveloperPortal/ILoaderAuthenticationPolicy.swift',
    'SideStore/SideStore/Core/Anisette/AnisetteProvider.swift',
    PROFILE + '/generate_fixture.py', PROFILE + '/check_sources.py',
    WIRE + '/generate_wire_fixture.py', WIRE + '/test_generator.py',
    SIGN + '/Sources/DeveloperPortal/Authentication.swift',
    SIGN + '/Sources/Models/AuthenticationDiagnosticTrace.swift',
    SIGN + '/Sources/Models/Errors.swift', SIGN + '/Sources/Constants.swift',
    SIGN + '/Sources/Models/AuthenticationHeaderProvenance.swift',
    SIGN + '/Sources/Anisette/AnisetteDataManager.swift',
    'SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
    'SideStore/AltStore/AppDelegate.swift',
    'LiveContainer/SideStoreSupport/SideStore.swift',
    'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
}

WIRE_INPUT_PATHS = {'service': 'SideStore/AltStore/AppDelegate.swift', 'host': 'LiveContainer/SideStoreSupport/SideStore.swift', 'ui': 'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift', 'operation': 'SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift', 'collector': 'SideStore/Dependencies/SideSign/Sources/Models/AuthenticationDiagnosticTrace.swift', 'provenance': 'SideStore/Dependencies/SideSign/Sources/Models/AuthenticationHeaderProvenance.swift', 'constants': 'SideStore/Dependencies/SideSign/Sources/Constants.swift', 'operation_errors': 'SideStore/SideStore/Core/Operations/Errors/OperationError.swift', 'portal_errors': 'SideStore/Dependencies/SideSign/Sources/Models/Errors.swift', 'portal_observers': 'SideStore/Dependencies/SideSign/Sources/DeveloperPortal/DeveloperPortalAPI.swift', 'anisette_errors': 'SideStore/Dependencies/SideSign/Sources/Anisette/AnisetteDataManager.swift', 'archive_errors': 'SideStore/Dependencies/SideSign/Sources/Archiver/Archive.swift', 'remote_errors': 'SideStore/Dependencies/SideSign/Sources/Anisette/ILoaderRemoteAnisette.swift', 'minimuxer_mapping': 'SideStore/SideStore/Core/DeviceApi/MinimuxerWrapper.swift', 'registration_doubles': 'SideStore/.ci/iloader-onboarding-scope/RegistrationDoubles.swift', 'registration_cases': 'SideStore/.ci/iloader-onboarding-scope/RegistrationCases.swift'}
REQUIRED_INPUTS.update(WIRE_INPUT_PATHS.values())

# These two source-owned fixtures exercise only the new setup paths. Existing
# auth/provenance/wire suites above remain single-run, not duplicated matrices.
SETUP_FIXTURES = {
    'placed-pairing': {
        'command': 'pairing', 'root': 'SideStore/.ci/placed-pairing',
        'generator': 'generate_fixture.py', 'source_test': 'test_source.py', 'output_arg': '--output',
        'files': ('Production.swift', 'Doubles.swift', 'RuntimeTests.swift'),
        'sources': ('SideStore/SideStore/Core/Pairing/PairingFileManager.swift',
                    'SideStore/AltStore/Core/Extensions/UserDefaults+AltStore.swift',
                    'SideStore/SideStore/AppBootManager.swift',
                    'SideStore/AltStore/AppDelegate.swift',
                    'LiveContainer/SideStoreSupport/SideStore.swift',
                    'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'),
    },
    'deferred-device-setup': {
        'command': 'deferred', 'root': 'SideStore/.ci/deferred-device-setup',
        'generator': 'generate.py', 'source_test': 'test_source.py', 'output_arg': '--output-dir',
        'files': ('CandidateDeferredSetup.swift', 'BoundaryDoubles.swift', 'RuntimeTests.swift'),
        'sources': ('SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
                    'SideStore/SideStore/Core/Pairing/PairingFileManager.swift',
                    'LiveContainer/SideStoreSupport/SideStore.swift',
                    'SideStore/AltStore/AppDelegate.swift',
                    'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'),
    },
}
for _spec in SETUP_FIXTURES.values():
    REQUIRED_INPUTS.update(_spec['sources'])
    REQUIRED_INPUTS.update(_spec['root'] + '/' + name for name in
                           (_spec['generator'], _spec['source_test']))


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def regular(root, relative):
    parts = PurePosixPath(relative).parts
    require(parts and not PurePosixPath(relative).is_absolute() and
            relative == '/'.join(parts) and all(p not in ('.', '..') for p in parts),
            'Unsafe relative path: ' + relative)
    path = root.joinpath(*parts)
    require(not root.is_symlink(), 'Symlinked input root')
    current = root
    for part in parts:
        current = current / part
        require(not current.is_symlink(), 'Symlink input: ' + str(current))
    require(path.is_file() and path.resolve().is_relative_to(root.resolve()),
            'Missing or escaping file: ' + str(path))
    return path


def load_contract(path):
    contract = json.loads(path.read_text())
    require(contract.get('schema') == 'comprehensive-diagnostics-source-contract-v1', 'Contract schema mismatch')
    require(contract.get('source_inputs_bound') is True, 'Source input hashes remain unbound')
    require(contract.get('schemas') == {'request': 'ar1', 'profile': 'hp2', 'provider': 'ap1'}, 'Diagnostic schema mismatch')
    inputs = contract.get('input_sha256')
    require(isinstance(inputs, dict) and REQUIRED_INPUTS <= set(inputs), 'Incomplete source input inventory')
    for name, value in inputs.items():
        require(isinstance(name, str) and isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value),
                'Malformed source hash')
    markers = contract.get('success_markers')
    require(isinstance(markers, dict) and set(markers) == {'legacy', 'auth', 'iloader', 'onboarding', 'profile', 'wire_service', 'wire_host', 'pairing', 'deferred'},
            'Incomplete marker contract')
    require(all(isinstance(v, str) and v and '\n' not in v and 'PENDING' not in v for v in markers.values()),
            'Unbound or malformed success marker')
    names = contract.get('onboarding_case_names')
    require(isinstance(names, list) and names and
            all(isinstance(name, str) and name and 'PENDING' not in name for name in names) and
            len(names) == len(set(names)), 'Unbound or malformed Onboarding case contract')
    names = contract.get('registration_case_names')
    require(isinstance(names, list) and names and
            all(isinstance(name, str) and name and 'PENDING' not in name for name in names) and
            len(names) == len(set(names)), 'Unbound or malformed Registration case contract')
    for suite in SETUP_FIXTURES:
        names = contract.get(suite + '_case_names')
        require(isinstance(names, list) and names and
                all(isinstance(name, str) and name and 'PENDING' not in name for name in names) and
                len(names) == len(set(names)), 'Unbound or malformed setup case contract: ' + suite)
    return contract


def source_inventory(root, contract):
    actual = {name: digest(regular(root, name).read_bytes()) for name in contract['input_sha256']}
    require(actual == contract['input_sha256'], 'Source input hash mismatch')
    # Hash all executable fixture inputs, not just selected known filenames.
    for folder in (AUTH, ILOADER, ONBOARDING, PROFILE, WIRE,
                   *(spec['root'] for spec in SETUP_FIXTURES.values())):
        directory = root / folder
        require(directory.is_dir() and not directory.is_symlink(), 'Missing source-owned fixture directory')
        for path in directory.rglob('*'):
            require(not path.is_symlink(), 'Symlink in source-owned fixture')
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                require(relative in actual, 'Unpinned fixture file: ' + relative)
    return actual


def artifact_inventory(root):
    found = {}
    require(root.is_dir() and not root.is_symlink(), 'Invalid evidence root')
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlinked retained artifact')
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == 'report.json':
            continue
        require(path.is_file(), 'Nonregular retained artifact')
        found[relative] = digest(path.read_bytes())
    return found


def require_marker(text, marker):
    require(text.splitlines().count(marker) == 1, 'Missing or duplicate exact success marker: ' + marker)


def exported_cases(path, schema, expected_count=None):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and value.get('schema') == schema, 'Case export schema mismatch')
    cases = value.get('cases')
    require(isinstance(cases, list) and len(cases) > 0, 'Empty or malformed case export')
    names = [row.get('name') for row in cases if isinstance(row, dict)]
    require(len(names) == len(cases) and all(isinstance(n, str) and n for n in names) and
            len(names) == len(set(names)), 'Case names are missing or duplicated')
    require(expected_count is None or len(cases) == expected_count, 'Case export count mismatch')
    return {'schema': schema, 'count': len(cases), 'sha256': digest(path.read_bytes()),
            'names': names, 'producer': value.get('producer')}


def iloader_exported_cases(path):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and value.get('schema') == 'iloader-auth-parity-cases-v1' and
            value.get('fake_only') is True, 'iLoader case export schema or fake-only flag differs')
    cases = value.get('cases')
    require(isinstance(cases, list) and cases and all(isinstance(name, str) and name for name in cases) and
            len(cases) == len(set(cases)), 'iLoader case names are empty, malformed or duplicated')
    return {'schema': value['schema'], 'count': len(cases), 'names': cases,
            'sha256': digest(path.read_bytes()), 'fake_only': True}


def onboarding_exported_cases(path, expected_names):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and value.get('schema') == 'iloader-onboarding-scope-cases-v1' and
            value.get('fake_only') is True, 'Onboarding case export schema or fake-only flag differs')
    cases = value.get('cases')
    require(isinstance(cases, list) and cases and all(isinstance(name, str) and name for name in cases) and
            len(cases) == len(set(cases)), 'Onboarding case names are empty, malformed or duplicated')
    require(sorted(cases) == sorted(expected_names), 'Onboarding case coverage differs from frozen source contract')
    return {'schema': value['schema'], 'count': len(cases), 'names': cases,
            'sha256': digest(path.read_bytes()), 'fake_only': True}


def registration_exported_cases(path, expected_names):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and value.get('schema') == REGISTRATION_SCHEMA and
            value.get('fake_only') is True, 'Registration case export schema or fake-only flag differs')
    export = exported_cases(path, REGISTRATION_SCHEMA)
    require(sorted(export['names']) == sorted(expected_names),
            'Registration case coverage differs from frozen source contract')
    export['fake_only'] = True
    return export


def setup_exported_cases(path, suite, expected_names):
    value = json.loads(path.read_text())
    require(isinstance(value, dict) and value.get('schema') == suite + '-cases-v1' and
            value.get('fake_only') is True, 'Setup case export schema or fake-only flag differs: ' + suite)
    cases = value.get('cases')
    require(isinstance(cases, list) and cases and all(isinstance(name, str) and name for name in cases) and
            len(cases) == len(set(cases)), 'Setup case names are empty, malformed or duplicated: ' + suite)
    require(sorted(cases) == sorted(expected_names), 'Setup case coverage differs: ' + suite)
    return {'schema': value['schema'], 'count': len(cases), 'names': cases,
            'sha256': digest(path.read_bytes()), 'fake_only': True}


def setup_extraction_receipt(output, contract, suite, spec):
    path = regular(output, suite + '/source-evidence.json')
    evidence = json.loads(path.read_text())
    require(evidence.get('schema') == suite + '-source-evidence-v1', 'Setup extraction schema differs: ' + suite)
    for key in ('network', 'native_provider', 'swift_executed'):
        require(evidence.get(key) is False, 'Forbidden setup generator execution claim: ' + suite + '/' + key)
    require(evidence.get('output_closure') == list(spec['files']), 'Setup generated-source closure differs: ' + suite)
    require(evidence.get('outputs') == {name: digest(regular(output, suite + '/' + name).read_bytes())
                                        for name in spec['files']}, 'Setup generated-source hashes differ: ' + suite)
    inputs = contract['input_sha256']
    used = evidence.get('inputs')
    required = set(spec['sources']) | {name for name in inputs if name.startswith(spec['root'] + '/')}
    require(isinstance(used, dict) and required <= set(used), 'Missing setup extraction input: ' + suite)
    for relative, value in used.items():
        require(isinstance(relative, str) and relative in inputs and
                isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) and
                value == inputs[relative], 'Setup extraction input hash differs: ' + suite)
    boundaries = evidence.get('boundary_replacements')
    require(isinstance(boundaries, list) and boundaries and
            all(isinstance(item, str) and item for item in boundaries) and
            len(boundaries) == len(set(boundaries)), 'Missing or duplicate setup boundary receipt: ' + suite)
    return {'path': path.relative_to(output).as_posix(), 'sha256': digest(path.read_bytes())}


def extraction_receipt(output, contract):
    """Require every generator's actual-source evidence, not just generated Swift."""
    manifests = {
        'legacy-response-core': 'legacy-response-core/fixture.sources.json',
        'auth-request': 'auth-request/source-evidence.json',
        'iloader-auth-parity': 'iloader-auth-parity/source-evidence.json',
        'iloader-onboarding-scope': 'iloader-onboarding-scope/source-evidence.json',
        'profile-provenance': 'profile-provenance/sources.json',
        'wire-copy': 'wire-copy/sources.json',
    }
    values = {name: json.loads(regular(output, path).read_text()) for name, path in manifests.items()}
    inputs = contract['input_sha256']
    legacy_paths = {'errors': SIGN + '/Sources/Models/Errors.swift',
                    'auth': SIGN + '/Sources/DeveloperPortal/Authentication.swift',
                    'store': 'SideStore/AltStore/AppDelegate.swift',
                    'host': 'LiveContainer/SideStoreSupport/SideStore.swift',
                    'shell': 'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'}
    require(values['legacy-response-core'].get('input_sha256') ==
            {key: inputs[path] for key, path in legacy_paths.items()}, 'Legacy extraction input evidence differs')
    auth = values['auth-request']
    require(auth.get('schema') == 'auth-request-source-evidence-v1', 'Auth extraction evidence schema differs')
    auth_inputs = auth.get('inputs', {})
    require({'Sources/DeveloperPortal/Authentication.swift', 'Sources/Models/AuthenticationDiagnosticTrace.swift',
             'Sources/Models/Errors.swift'} <= set(auth_inputs), 'Missing actual authentication source evidence')
    for relative, value in auth_inputs.items():
        require(inputs.get(SIGN + '/' + relative) == value, 'Auth extraction input hash differs: ' + relative)
    require(auth.get('outputs') == {name: digest(regular(output, 'auth-request/' + name).read_bytes())
                                   for name in AUTH_FILES}, 'Auth generated-source hashes differ')
    iloader = values['iloader-auth-parity']
    require(iloader.get('schema') == 'iloader-auth-parity-source-evidence-v1' and
            iloader.get('official_reference') == ILOADER_OFFICIAL_REFERENCE,
            'iLoader extraction schema or official source reference differs')
    require(iloader.get('baseline_commit') == auth.get('baseline_commit') and
            isinstance(iloader.get('baseline_commit'), str) and
            re.fullmatch('[0-9a-f]{40}', iloader['baseline_commit']), 'iLoader baseline reference differs')
    for key in ('network', 'native_provider', 'swift_executed'):
        require(iloader.get(key) is False, 'Forbidden iLoader generator execution claim: ' + key)
    require(iloader.get('output_closure') == list(ILOADER_FILES), 'iLoader generated-source closure differs')
    require(iloader.get('outputs') == {name: digest(regular(output, 'iloader-auth-parity/' + name).read_bytes())
                                      for name in ILOADER_FILES}, 'iLoader generated-source hashes differ')
    used = iloader.get('inputs', {})
    require(isinstance(used, dict) and set(auth_inputs) <= set(used) and
            {'Sources/Anisette/ILoaderRemoteAnisette.swift',
             'Sources/DeveloperPortal/ILoaderAuthenticationPolicy.swift',
             'SideStore/SideStore/Core/Anisette/AnisetteProvider.swift'} <= set(used),
            'Missing actual iLoader extraction inputs')
    for relative, value in used.items():
        name = relative if relative.startswith('SideStore/') else SIGN + '/' + relative
        require(inputs.get(name) == value, 'iLoader extraction input hash differs: ' + relative)
    require(all(used.get(relative[len(SIGN) + 1:]) == value for relative, value in inputs.items()
                if relative.startswith(ILOADER + '/')), 'Unrecorded iLoader fixture input')
    boundaries = iloader.get('boundary_replacements')
    require(isinstance(boundaries, list) and boundaries and
            all(isinstance(item, str) and item for item in boundaries) and
            len(boundaries) == len(set(boundaries)), 'Missing or duplicate iLoader boundary receipt')
    onboarding = values['iloader-onboarding-scope']
    require(onboarding.get('schema') == 'iloader-onboarding-scope-source-evidence-v1',
            'Onboarding extraction evidence schema differs')
    for key in ('network', 'native_provider', 'swift_executed'):
        require(onboarding.get(key) is False, 'Forbidden Onboarding generator execution claim: ' + key)
    require(onboarding.get('output_closure') == list(ONBOARDING_FILES), 'Onboarding generated-source closure differs')
    require(onboarding.get('outputs') == {name: digest(regular(output, 'iloader-onboarding-scope/' + name).read_bytes())
                                         for name in ONBOARDING_FILES}, 'Onboarding generated-source hashes differ')
    used = onboarding.get('inputs', {})
    require(isinstance(used, dict) and set(ONBOARDING_REQUIRED_SOURCES) <= set(used),
            'Missing actual queued onboarding extraction inputs')
    for relative, value in used.items():
        require(isinstance(relative, str) and relative.startswith(('SideStore/', 'SideSign/')),
                'Onboarding extraction input lacks repository prefix')
        name = 'SideStore/Dependencies/' + relative if relative.startswith('SideSign/') else relative
        require(name in inputs and isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) and
                inputs[name] == value, 'Onboarding extraction input hash differs: ' + relative)
    require(all(used.get(relative) == value for relative, value in inputs.items()
                if relative.startswith(ONBOARDING + '/')), 'Unrecorded Onboarding fixture input')
    boundaries = onboarding.get('boundary_replacements')
    require(isinstance(boundaries, list) and boundaries and
            all(isinstance(item, str) and item for item in boundaries) and
            len(boundaries) == len(set(boundaries)), 'Missing or duplicate Onboarding boundary receipt')
    profile = values['profile-provenance']
    used = profile.get('sources', {})
    require({'SideSign/Sources/Models/AuthenticationHeaderProvenance.swift',
             'SideSign/Sources/Anisette/AnisetteDataManager.swift'} <= set(used), 'Profile extraction evidence incomplete')
    for relative, row in used.items():
        if relative.startswith(('baseline/', 'fixture/')):
            continue  # Embedded baselines/templates are independently frozen in the full source contract.
        name = 'SideStore/Dependencies/' + relative if relative.startswith('SideSign/') else relative
        require(inputs.get(name) == row.get('sha256'), 'Profile extraction input hash differs: ' + relative)
    require(profile.get('generated_sha256') == digest(regular(output, 'profile-provenance/fixture.swift').read_bytes()),
            'Profile generated-source hash differs')
    wire_paths = WIRE_INPUT_PATHS
    require(values['wire-copy'].get('input_sha256') == {key: inputs[path] for key, path in wire_paths.items()},
            'Wire extraction input evidence differs')
    require(values['wire-copy'].get('generated_sha256') ==
            {name: digest(regular(output, 'wire-copy/' + name).read_bytes()) for name in ('service.swift','host.swift')},
            'Wire generated-source hashes differ')
    result = {name: {'path': path, 'sha256': digest(regular(output, path).read_bytes())}
              for name, path in manifests.items()}
    for suite, spec in SETUP_FIXTURES.items():
        result[suite] = setup_extraction_receipt(output, contract, suite, spec)
    return result


class Runner:
    def __init__(self, output):
        self.output = output
        self.commands = []

    def command(self, name, arguments, marker=None):
        require(name in COMMANDS and name not in [row['name'] for row in self.commands], 'Unexpected or repeated command')
        row = {'name': name, 'argv': [str(arg) for arg in arguments], 'exit_code': None}
        self.commands.append(row)
        log = self.output / ('commands/' + name + '.log')
        log.parent.mkdir(exist_ok=True)
        try:
            result = subprocess.run(row['argv'], cwd=self.output, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=300)
            data = result.stdout
            row['exit_code'] = result.returncode
        except subprocess.TimeoutExpired as error:
            data = (error.stdout or b'') + b'\nCOMMAND_TIMEOUT\n'
            row['timed_out'] = True
        except OSError as error:
            data = str(error).encode()
            row['launch_error'] = type(error).__name__
        log.write_bytes(data)
        row.update(stdout_sha256=digest(data), log=log.relative_to(self.output).as_posix())
        require(row['exit_code'] == 0, 'Command failed: ' + name + ', exit=' + str(row['exit_code']))
        text = data.decode('utf-8', errors='replace')
        if marker is not None:
            require_marker(text, marker)
            row['success_marker'] = marker
        return text


def verify_receipt(path, contract_path=None):
    contract_path = contract_path or HERE / 'comprehensive-diagnostics-contract.json'
    contract = load_contract(contract_path)
    report = json.loads(path.read_text())
    require(report.get('status') == STATUS and report.get('suites') == list(SUITES), 'Consolidated suite did not pass')
    require(report.get('contract_sha256') == digest(contract_path.read_bytes()), 'Receipt source contract differs')
    require(report.get('source_inputs_before') == contract['input_sha256'] and
            report.get('source_inputs_after') == contract['input_sha256'] and
            report.get('source_input_bytes_unchanged') is True, 'Input immutability receipt missing')
    for key in ('live_authentication_executed', 'guest_binary_executed', 'native_provider_executed', 'native_linked_tests_executed'):
        require(report.get(key) is False, 'Forbidden execution in receipt: ' + key)
    require(report.get('source_owned_fake_authentication_executed') is True, 'Source-owned fake authentication did not run')
    require(report.get('extraction_manifests') == extraction_receipt(path.parent, contract), 'Extraction evidence receipt differs')
    require(report.get('generated_swift_sha256') == {p.relative_to(path.parent).as_posix(): digest(p.read_bytes())
            for p in sorted(path.parent.rglob('*.swift')) if p.is_file()}, 'Generated Swift receipt differs')
    commands = report.get('commands', [])
    require([row.get('name') for row in commands] == list(COMMANDS) and
            all(row.get('exit_code') == 0 for row in commands), 'Incomplete successful command receipt')
    outputs = report.get('artifact_sha256')
    require(isinstance(outputs, dict) and outputs and artifact_inventory(path.parent) == outputs,
            'Retained evidence missing or changed')
    for row in commands:
        logfile = regular(path.parent, row['log'])
        require(digest(logfile.read_bytes()) == row['stdout_sha256'], 'Command log hash mismatch')
    marks = contract['success_markers']
    by_name = {row['name']: row for row in commands}
    for name, key in (('legacy-run','legacy'),('auth-run','auth'),('iloader-run','iloader'),
                      ('onboarding-run','onboarding'),('profile-run','profile'),
                      ('wire-service-run','wire_service'),('wire-host-run','wire_host'),
                      ('pairing-run','pairing'),('deferred-run','deferred')):
        row = by_name[name]
        require(row.get('success_marker') == marks[key], 'Success-marker receipt differs')
        require_marker(regular(path.parent, row['log']).read_text(), marks[key])
    for owner, schema, count in (('auth-request','auth-request-cases-v1',None),
                                 ('profile-provenance','profile-provenance-cases-v1',12)):
        export = exported_cases(regular(path.parent, owner + '/cases.json'), schema, count)
        require(report.get('producer_exports', {}).get(owner) == export, 'Producer case receipt mismatch')
        marker = f"WIRE_IMPORTED_CASES schema={schema} producer_cases={export['count']} wire_cases={2 * export['count']}"
        require_marker(regular(path.parent, by_name['wire-service-run']['log']).read_text(), marker)
    registration = registration_exported_cases(
        regular(path.parent, 'iloader-onboarding-scope/registration-cases.json'), contract['registration_case_names'])
    require(report.get('producer_exports', {}).get('device-registration') == registration,
            'Registration producer case receipt mismatch')
    require(set(report.get('producer_exports', {})) == {'auth-request', 'profile-provenance', 'device-registration'},
            'Producer export closure differs')
    marker = f"WIRE_IMPORTED_CASES schema={registration['schema']} producer_cases={registration['count']} wire_cases={2 * registration['count']}"
    require_marker(regular(path.parent, by_name['wire-service-run']['log']).read_text(), marker)
    export = iloader_exported_cases(regular(path.parent, 'iloader-auth-parity/cases.json'))
    require(report.get('fixture_exports', {}).get('iloader-auth-parity') == export, 'iLoader fixture case receipt mismatch')
    onboarding_export = onboarding_exported_cases(regular(path.parent, 'iloader-onboarding-scope/cases.json'), contract['onboarding_case_names'])
    require(report.get('fixture_exports', {}).get('iloader-onboarding-scope') == onboarding_export,
            'Onboarding fixture case receipt mismatch')
    expected_exports = {'iloader-auth-parity': export, 'iloader-onboarding-scope': onboarding_export}
    for suite in SETUP_FIXTURES:
        expected_exports[suite] = setup_exported_cases(
            regular(path.parent, suite + '/cases.json'), suite, contract[suite + '_case_names'])
    require(report.get('fixture_exports') == expected_exports, 'Setup fixture case receipt mismatch')
    return report


def run(sources, swiftc, output, contract_path=None):
    contract_path = contract_path or HERE / 'comprehensive-diagnostics-contract.json'
    contract = load_contract(contract_path)
    require(not sources.is_symlink(), 'Symlink source root')
    sources = sources.resolve(strict=True)
    before = source_inventory(sources, contract)
    require(not output.exists() and not output.is_symlink(), 'Output must be fresh')
    require(not output.resolve().is_relative_to(sources), 'Output must not be inside source inputs')
    require(swiftc.is_file(), 'Missing Swift compiler')
    swiftc = swiftc.resolve()
    output.mkdir(parents=True)
    output = output.resolve()
    runner = Runner(output)
    report = {'schema': 'comprehensive-diagnostics-run-v1', 'status': 'FAILED', 'suites': [],
              'contract_sha256': digest(contract_path.read_bytes()), 'source_inputs_before': before,
              'source_inputs_after': {}, 'source_input_bytes_unchanged': False,
              'live_authentication_executed': False, 'guest_binary_executed': False,
              'native_provider_executed': False, 'native_linked_tests_executed': False,
              'source_owned_fake_authentication_executed': False, 'producer_exports': {}, 'fixture_exports': {},
              'commands': runner.commands}
    for directory in SUITES:
        (output / directory).mkdir()
    def source(name):
        require(name in before, 'Command input is not frozen: ' + name)
        return regular(sources, name)
    def python(name):
        return [sys.executable, '-B', source(name)]
    def compile_fixture(name, files, binary, library=False):
        for file in files:
            require(file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(output),
                    'Missing or unsafe generated Swift input: ' + str(file))
        argv = [swiftc, '-swift-version', '5'] + (['-parse-as-library'] if library else [])
        runner.command(name, argv + files + ['-o', binary])
    try:
        marks = contract['success_markers']
        legacy = output / 'legacy-response-core'
        legacy_generator = HERE / 'test_auth_response_contract.py'
        runner.command('legacy-generate', [sys.executable, '-B', legacy_generator,
            '--errors', source(SIGN + '/Sources/Models/Errors.swift'),
            '--auth', source(SIGN + '/Sources/DeveloperPortal/Authentication.swift'),
            '--store', source('SideStore/AltStore/AppDelegate.swift'),
            '--host', source('LiveContainer/SideStoreSupport/SideStore.swift'),
            '--shell', source('LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'),
            '--output', legacy / 'fixture.swift'])
        compile_fixture('legacy-compile', [legacy / 'fixture.swift'], legacy / 'fixture')
        runner.command('legacy-run', [legacy / 'fixture'], marks['legacy'])
        report['suites'].append('legacy-response-core')
        auth = output / 'auth-request'
        runner.command('auth-source', python(AUTH + '/test_source.py'))
        runner.command('auth-generate', python(AUTH + '/generate.py') + ['--output-dir', auth])
        require({p.name for p in auth.glob('*.swift')} == set(AUTH_FILES), 'Auth seven-file Swift closure differs')
        compile_fixture('auth-compile', [auth / name for name in AUTH_FILES], auth / 'fixture', library=True)
        runner.command('auth-run', [auth / 'fixture', auth / 'cases.json'], marks['auth'])
        report['source_owned_fake_authentication_executed'] = True
        report['producer_exports']['auth-request'] = exported_cases(auth / 'cases.json', 'auth-request-cases-v1')
        report['suites'].append('auth-request')
        iloader = output / 'iloader-auth-parity'
        runner.command('iloader-source', python(ILOADER + '/test_source.py') + ['--sidestore-root', sources / 'SideStore'])
        runner.command('iloader-generate', python(ILOADER + '/generate.py') +
                       ['--output-dir', iloader, '--sidestore-root', sources / 'SideStore'])
        require({p.name for p in iloader.glob('*.swift')} == set(ILOADER_FILES), 'iLoader seven-file Swift closure differs')
        compile_fixture('iloader-compile', [iloader / name for name in ILOADER_FILES], iloader / 'fixture', library=True)
        runner.command('iloader-run', [iloader / 'fixture', iloader / 'cases.json'], marks['iloader'])
        report['fixture_exports']['iloader-auth-parity'] = iloader_exported_cases(iloader / 'cases.json')
        report['suites'].append('iloader-auth-parity')
        onboarding = output / 'iloader-onboarding-scope'
        onboarding_roots = ['--sidesign-root', sources / SIGN, '--sidestore-root', sources / 'SideStore']
        runner.command('onboarding-source', python(ONBOARDING + '/test_source.py') + onboarding_roots)
        runner.command('onboarding-generate', python(ONBOARDING + '/generate.py') +
                       ['--output-dir', onboarding] + onboarding_roots)
        require({p.name for p in onboarding.glob('*.swift')} == set(ONBOARDING_FILES), 'Onboarding three-file Swift closure differs')
        compile_fixture('onboarding-compile', [onboarding / name for name in ONBOARDING_FILES], onboarding / 'fixture', library=True)
        runner.command('onboarding-run', [onboarding / 'fixture', onboarding / 'cases.json'], marks['onboarding'])
        report['fixture_exports']['iloader-onboarding-scope'] = onboarding_exported_cases(onboarding / 'cases.json', contract['onboarding_case_names'])
        report['producer_exports']['device-registration'] = registration_exported_cases(
            onboarding / 'registration-cases.json', contract['registration_case_names'])
        report['suites'].append('iloader-onboarding-scope')
        profile = output / 'profile-provenance'
        runner.command('profile-source', python(PROFILE + '/check_sources.py') + [
            '--sources', sources, '--report', profile / 'static.json'])
        runner.command('profile-generate', python(PROFILE + '/generate_fixture.py') + [
            '--sources', sources, '--output', profile / 'fixture.swift', '--manifest', profile / 'sources.json'])
        compile_fixture('profile-compile', [profile / 'fixture.swift'], profile / 'fixture', library=True)
        runner.command('profile-run', [profile / 'fixture', profile / 'cases.json'], marks['profile'])
        report['producer_exports']['profile-provenance'] = exported_cases(profile / 'cases.json', 'profile-provenance-cases-v1', 12)
        report['suites'].append('profile-provenance')
        wire = output / 'wire-copy'
        runner.command('wire-source', python(WIRE + '/test_generator.py') + ['--sources', sources])
        runner.command('wire-generate', python(WIRE + '/generate_wire_fixture.py') + ['--sources', sources, '--output', wire])
        compile_fixture('wire-service-compile', [wire / 'service.swift'], wire / 'service')
        compile_fixture('wire-host-compile', [wire / 'host.swift'], wire / 'host')
        transferred = wire / 'wire-cases.plist'
        service_log = runner.command('wire-service-run', [wire / 'service', transferred,
                    auth / 'cases.json', profile / 'cases.json', onboarding / 'registration-cases.json'], marks['wire_service'])
        for export in report['producer_exports'].values():
            require_marker(service_log, f"WIRE_IMPORTED_CASES schema={export['schema']} producer_cases={export['count']} wire_cases={2 * export['count']}")
        runner.command('wire-host-run', [wire / 'host', transferred], marks['wire_host'])
        report['suites'].append('wire-copy')
        for suite, spec in SETUP_FIXTURES.items():
            folder = output / suite
            prefix = spec['command']
            runner.command(prefix + '-source', python(spec['root'] + '/' + spec['source_test']) +
                           ['--sources', sources])
            runner.command(prefix + '-generate', python(spec['root'] + '/' + spec['generator']) +
                           ['--sources', sources, spec['output_arg'], folder])
            require({p.name for p in folder.glob('*.swift')} == set(spec['files']),
                    'Setup generated Swift closure differs: ' + suite)
            # Verify input hashes, the generator's claimed side-effect boundaries,
            # and the exact generated-file closure before executing any fixture.
            setup_extraction_receipt(output, contract, suite, spec)
            compile_fixture(prefix + '-compile', [folder / name for name in spec['files']],
                            folder / 'fixture', library=True)
            runner.command(prefix + '-run', [folder / 'fixture', folder / 'cases.json'], marks[prefix])
            report['fixture_exports'][suite] = setup_exported_cases(
                folder / 'cases.json', suite, contract[suite + '_case_names'])
            report['suites'].append(suite)
        require([row['name'] for row in runner.commands] == list(COMMANDS), 'Command sequence differs')
        report['source_inputs_after'] = source_inventory(sources, contract)
        require(report['source_inputs_after'] == before, 'Fixture mutated source inputs')
        report['source_input_bytes_unchanged'] = True
        report['extraction_manifests'] = extraction_receipt(output, contract)
        report['status'] = STATUS
    except Exception as error:
        report['failure'] = str(error)
        raise
    finally:
        report['generated_swift_sha256'] = {p.relative_to(output).as_posix(): digest(p.read_bytes())
            for p in sorted(output.rglob('*.swift')) if p.is_file()}
        report['artifact_sha256'] = artifact_inventory(output)
        write_json(output / 'report.json', report)
    verify_receipt(output / 'report.json', contract_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--swiftc', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.sources, args.swiftc, args.output)
    print(json.dumps({'status': report['status'], 'suites': report['suites'],
                      'producer_case_counts': {k: v['count'] for k, v in report['producer_exports'].items()}}, sort_keys=True))


if __name__ == '__main__':
    main()
