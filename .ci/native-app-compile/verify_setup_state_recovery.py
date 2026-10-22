"""Additional source-owned setup regressions. No app, provider, network or device execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from verify_comprehensive_diagnostics import regular, require, digest, write_json, artifact_inventory, require_marker

HERE = Path(__file__).resolve().parent
STATUS = 'SETUP_STATE_SOURCE_FIXTURES_PASS_NOT_DEVICE_VALIDATION'
BASELINE_OWNERS = {
    'LiveContainer': {'commit': 'cb21f150e8907d2f8ed1bc7658342bac3fbb9926',
                      'tree': '2d96ff02b99d4d4a52650582500ab1124486f6ef'},
    'SideStore/Dependencies/SideSign': {'commit': 'd05efa30f37bad7c7ddaa50186fc1ac8ba703eca',
        'tree': 'f3af3a9045733d8002465142cad20cf71a7e1076'},
    'SideStore': {'commit': '638fa62ce2a540efe6c92dd20c282c32ddc0b2e6',
                  'tree': '99d6650e20b29b5c061b2c1ea04f746b51417537'},
}
SUITES = ('setup-localization', 'early-refresh-boundaries', 'certificate-portal-evidence', 'remote-identity-reuse')
LOCALIZATION = 'LiveContainer/.ci/comprehensive-diagnostics'
EARLY = 'LiveContainer/.ci/early-refresh-boundaries'
PORTAL = 'LiveContainer/.ci/certificate-portal-evidence'
IDENTITY = 'SideStore/.ci/remote-identity-reuse'
IDENTITY_CASE_COUNT = 55
IDENTITY_SOURCE_WIRING = ('signin_returns_actual_attempt_handoff', 'signin_credential_transactions_record_selected_route', 'both_verified_terminal_paths_commit_identity', 'full_terminal_commit_precedes_journal_persist', 'headless_admission_captured_before_driver', 'profile_coalescers_use_scoped_admission', 'app_id_coalescer_uses_scoped_admission', 'portal_transport_checks_scoped_context', 'outer_sync_app_ids_captures_before_detached', 'outer_refresh_captures_before_detached', 'outer_background_refresh_captures_before_detached', 'background_callback_installed_before_enqueue_and_cancellation_checked', 'app_manager_completion_after_successful_admission_scope', 'pipeline_completion_after_successful_admission_scope', 'heavy_pipeline_does_not_publish_terminal_callback')
IDENTITY_SWIFT = ('CandidateCore.swift', 'BoundaryDoubles.swift', 'CoreCases.swift',
                  'CandidateRuntime.swift', 'RuntimeDoubles.swift', 'RuntimeCases.swift')
LOCALIZATION_INPUTS = {
    'ui': 'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
    'localization': 'LiveContainer/LiveContainerSwiftUI/Utilities/V3Localization.swift',
    'catalog': 'LiveContainer/Resources/Localizable.xcstrings',
    'display': 'LiveContainer/LiveContainerSwiftUI/Utilities/V3LanguageSettings.swift',
    'identity_diagnostics': 'LiveContainer/SideStoreSupport/SideStore.swift',
}
LOCALIZATION_FILES = ('generate_setup_localization_fixture.py', 'setup_localization_harness.swift',
                      'test_setup_localization_contract.py')
COMMANDS = ('delivered-baseline-extract', 'localization-source', 'early-source', 'portal-source',
            'identity-controls', 'identity-source',
            'localization-compile', 'early-baseline-compile', 'early-candidate-compile',
            'portal-baseline-compile', 'portal-baseline-host-compile',
            'portal-candidate-compile', 'portal-candidate-host-compile', 'identity-compile',
            'localization-run', 'early-baseline-run', 'early-candidate-run',
            'portal-baseline-run', 'portal-baseline-host-run',
            'portal-candidate-run', 'portal-candidate-host-run', 'identity-run')
COMPILE_COMMANDS = tuple(name for name in COMMANDS if name.endswith('-compile'))


SUITE_INPUTS = {'early-refresh-boundaries': {'production': ['LiveContainer/LiveContainerSwiftUI/App/AppDelegate.swift',
                                             'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
                                             'LiveContainer/SideStoreSupport/SideStore.swift',
                                             'LiveContainer/SideStoreSupport/SideStoreClient.swift',
                                             'SideStore/AltStore/AppDelegate.swift',
                                             'SideStore/AltStore/Core/Model/StoreApp.swift',
                                             'SideStore/AltStore/Intents/App '
                                             'Intents/RefreshAllAppsIntent.swift',
                                             'SideStore/AltStore/Managing Apps/AppManager.swift',
                                             'SideStore/Shared/Errors/ALTWrappedError.swift',
                                             'SideStore/Shared/Extensions/Bundle+AltStore.swift',
                                             'SideStore/Shared/Extensions/NSError+AltStore.swift',
                                             'SideStore/SideStore/Core/Auth/AuthManager.swift',
                                             'SideStore/SideStore/Core/DeviceApi/MinimuxerWrapper.swift',
                                             'SideStore/SideStore/Core/Operations/AppOperation.swift',
                                             'SideStore/SideStore/Core/Operations/Errors/OperationError.swift',
                                             'SideStore/SideStore/Core/Operations/OperationStep.swift',
                                             'SideStore/SideStore/Core/Operations/PipelineExecutor.swift',
                                             'SideStore/SideStore/Core/Operations/PipelineOperations/PreflightChecksOperation.swift',
                                             'SideStore/SideStore/Core/Operations/PipelineRunner.swift',
                                             'SideStore/SideStore/Core/Operations/RefreshGroup.swift',
                                             'SideStore/SideStore/Core/Operations/StandaloneOperations/BackgroundRefreshAppsOperation.swift'],
                              'support': ['LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py',
                                          'LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_doubles.swift',
                                          'LiveContainer/.ci/comprehensive-diagnostics/refresh_handler_doubles.swift',
                                          'LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_harness.swift',
                                          'SideStore/tests/refresh_failure/pipeline_harness.swift'],
                              'fixture': ['LiveContainer/.ci/early-refresh-boundaries/generate_regression.py',
                                          'LiveContainer/.ci/early-refresh-boundaries/early_doubles.swift',
                                          'LiveContainer/.ci/early-refresh-boundaries/early_cases.swift',
                                          'LiveContainer/.ci/early-refresh-boundaries/baseline-inputs.json',
                                           'LiveContainer/.ci/early-refresh-boundaries/test_contract.py',
                                           'LiveContainer/.ci/early-refresh-boundaries/README.md']},
 'certificate-portal-evidence': {'production': ['SideStore/AltStore/AppDelegate.swift',
                                                'LiveContainer/SideStoreSupport/SideStore.swift',
                                                'SideStore/SideStore/Core/Operations/PipelineExecutor.swift',
                                                'SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift',
                                                'SideStore/SideStore/Core/Operations/Errors/OperationError.swift',
                                                'SideStore/Shared/Errors/ALTWrappedError.swift',
                                                'SideStore/Dependencies/SideSign/Sources/DeveloperPortal/DeveloperPortalAPI.swift',
                                                'SideStore/Dependencies/SideSign/Sources/DeveloperPortal/Certificates.swift',
                                                'SideStore/Dependencies/SideSign/Sources/Models/DeveloperPortalResponses.swift',
                                                'SideStore/Dependencies/SideSign/Sources/Models/X509Certificate.swift',
                                                'SideStore/Dependencies/SideSign/Sources/Models/Errors.swift',
                                                'SideStore/Dependencies/SideSign/Sources/Constants.swift',
                                                'SideStore/Dependencies/SideSign/Sources/SideSign.swift'],
                                 'support': ['LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py',
                                             'LiveContainer/.ci/certificate-portal-evidence/generate_regression.py',
                                             'LiveContainer/.ci/certificate-portal-evidence/portal_doubles.swift',
                                             'LiveContainer/.ci/certificate-portal-evidence/service_cases.swift',
                                             'LiveContainer/.ci/certificate-portal-evidence/host_cases.swift']}}

SUITE_INPUTS['remote-identity-reuse'] = {'production': ['SideStore/AltStore/AppDelegate.swift',
                'SideStore/AltStore/Managing Apps/AppManager.swift',
                'SideStore/SideStore/Core/Operations/StandaloneOperations/BackgroundRefreshAppsOperation.swift',
                'SideStore/AltStore/Core/Components/Keychain.swift',
                'SideStore/Dependencies/SideSign/Sources/Anisette/ILoaderRemoteAnisette.swift',
                'SideStore/Dependencies/SideSign/Sources/DeveloperPortal/DeveloperPortalAPI.swift',
                'SideStore/SideStore/Core/Anisette/AnisetteProvider.swift',
                'SideStore/SideStore/Core/Auth/AuthManager.swift',
                'SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift',
                'SideStore/SideStore/Core/Operations/PipelineOperations/FetchProvisioningProfilesOperation.swift',
                'SideStore/SideStore/Core/Operations/PipelineRunner.swift',
                'SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
                'SideStore/SideStore/Core/Operations/StandaloneOperations/SyncAppIDsOperation.swift',
                'SideStore/SideStore/Utils/concurrency/TaskChainCoalescer.swift'],
 'support': ['SideStore/.ci/remote-identity-reuse/generate_fixture.py',
             'SideStore/.ci/remote-identity-reuse/BoundaryDoubles.swift',
             'SideStore/.ci/remote-identity-reuse/CoreCases.swift',
             'SideStore/.ci/remote-identity-reuse/RuntimeDoubles.swift',
             'SideStore/.ci/remote-identity-reuse/RuntimeCases.swift',
             'SideStore/.ci/remote-identity-reuse/run.sh',
             'SideStore/.ci/remote-identity-reuse/README.md',
             'SideStore/.ci/remote-identity-reuse/test_generator.py']}

def load_contract(path):
    value = json.loads(path.read_text())
    require(value.get('schema') == 'setup-state-recovery-contract-v1', 'Setup contract schema differs')
    require(value.get('source_inputs_bound') is True, 'Setup source hashes remain unbound')
    require(value.get('suites') == list(SUITES), 'Setup suite closure differs')
    require(value.get('delivered_baseline', {}).get('owners') == BASELINE_OWNERS,
            'Setup delivered baseline commit/tree differs')
    required = set(LOCALIZATION_INPUTS.values()) | {LOCALIZATION + '/' + f for f in LOCALIZATION_FILES}
    required |= {EARLY + '/test_contract.py', PORTAL + '/test_generator.py'}
    for spec in SUITE_INPUTS.values():
        for paths in spec.values():
            required.update(paths)
    require(value.get('suite_inputs') == SUITE_INPUTS, 'Setup exact source path closure differs')
    for key in ('input_sha256',):
        hashes = value.get(key)
        require(isinstance(hashes, dict) and required <= set(hashes), 'Incomplete setup source hashes')
        require(all(isinstance(k, str) and isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                    for k, v in hashes.items()), 'Malformed setup source hashes')
    baseline = value['delivered_baseline'].get('input_sha256')
    require(isinstance(baseline, dict) and set(LOCALIZATION_INPUTS.values()).union(*(set(v['production']) for v in SUITE_INPUTS.values())) == set(baseline),
            'Incomplete delivered baseline source hashes')
    require(all(isinstance(k, str) and k.split('/', 1)[0] in BASELINE_OWNERS and
                isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for k, v in baseline.items()),
            'Malformed delivered baseline source hashes')
    for suite, count in [('setup-localization', 1076), ('early-refresh-boundaries', 24),
                         ('certificate-portal-evidence', 19), ('remote-identity-reuse', IDENTITY_CASE_COUNT)]:
        names = value.get('case_names', {}).get(suite)
        require(isinstance(names, list) and len(names) == count and len(set(names)) == count and
                all(isinstance(n, str) and n for n in names), 'Invalid exact case closure: ' + suite)
    return value


def inventory(sources, contract):
    actual = {p: digest(regular(sources, p).read_bytes()) for p in contract['input_sha256']}
    require(actual == contract['input_sha256'], 'Setup candidate source hashes differ')
    for folder in (EARLY, PORTAL, IDENTITY):
        root = sources / folder
        require(root.is_dir() and not root.is_symlink(), 'Missing setup fixture package')
        for p in root.rglob('*'):
            require(not p.is_symlink(), 'Symlink setup fixture input')
            if p.is_file():
                require(p.relative_to(sources).as_posix() in actual, 'Unpinned setup fixture input')
    return actual


def extract_baseline(sources, contract, output, receipt):
    """Same pinned local-object pattern as extract_deferred_baseline; never fetch."""
    baseline = contract['delivered_baseline']
    require(not sources.is_symlink(), 'Symlink setup source root')
    sources = sources.resolve(strict=True)
    require(not output.exists() and not output.is_symlink() and
            not receipt.exists() and not receipt.is_symlink(), 'Fresh baseline output required')
    require(not output.resolve().is_relative_to(sources), 'Baseline output inside source inputs')
    environment = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                       GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1',
                       GIT_NO_LAZY_FETCH='1', GIT_ALLOW_PROTOCOL='')
    def git(owner, *arguments):
        checkout = sources / owner
        require(checkout.is_dir() and not checkout.is_symlink() and (checkout / '.git').exists(),
                'Missing exact local Git checkout')
        result = subprocess.run(['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null',
                                '-C', str(checkout), *arguments], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                                env=environment, timeout=60)
        return result.stdout
    for owner, value in baseline['owners'].items():
        commit = value['commit']
        require(git(owner, 'cat-file', '-t', commit).decode().strip() == 'commit', 'Delivered commit absent')
        require(git(owner, 'rev-parse', commit + '^{tree}').decode().strip() == value['tree'],
                'Delivered source tree differs')
    contents = {}
    for name, expected in baseline['input_sha256'].items():
        owner = next((o for o in sorted(BASELINE_OWNERS, key=len, reverse=True) if name.startswith(o + '/')), None)
        require(owner is not None, 'Unknown baseline owner')
        relative = name[len(owner) + 1:]
        # Reject unsafe paths before requesting an object or creating output.
        require(relative and not relative.startswith('/') and '..' not in Path(relative).parts and
                name == Path(name).as_posix(), 'Unsafe baseline relative path')
        raw = git(owner, 'show', baseline['owners'][owner]['commit'] + ':' + relative)
        require(digest(raw) == expected, 'Delivered baseline source bytes differ: ' + name)
        contents[name] = raw
    output.mkdir(parents=True)
    for name, raw in contents.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        require(digest(regular(output, name).read_bytes()) == baseline['input_sha256'][name],
                'Delivered baseline changed during extraction')
    write_json(receipt, {'schema': 'setup-delivered-baseline-v1', 'origin': 'exact-local-git-objects',
                        **baseline, 'network': False, 'target_execution': False})


def baseline_receipt(output, contract):
    value = json.loads(regular(output, 'delivered-baseline.json').read_text())
    expected = {'schema': 'setup-delivered-baseline-v1', 'origin': 'exact-local-git-objects',
                **contract['delivered_baseline'], 'network': False, 'target_execution': False}
    require(value == expected, 'Delivered baseline extraction receipt differs')
    actual = {name: digest(regular(output / 'delivered-baseline', name).read_bytes())
              for name in contract['delivered_baseline']['input_sha256']}
    require(actual == contract['delivered_baseline']['input_sha256'], 'Retained delivered baseline changed')
    return value


def exact_cases(path, schema, expected, **attributes):
    value = json.loads(path.read_text())
    require(value.get('schema') == schema and value.get('status') == 'pass', 'Fixture runtime did not pass')
    require(value.get('case_count') == len(expected) and isinstance(value.get('cases'), list) and len(set(value['cases'])) == len(expected) and
            sorted(value['cases']) == sorted(expected),
            'Fixture case closure differs')
    require(all(value.get(k) == v and type(value.get(k)) is type(v) for k, v in attributes.items()),
            'Fixture runtime boundary differs')
    return value


def localization_extraction(output, contract):
    root = output / 'setup-localization'
    value = json.loads(regular(root, 'sources.json').read_text())
    require(value.get('schema') == 'setup-localization-sources-v1' and
            value.get('status') == 'generated_not_compiled', 'Localization extraction status differs')
    require(value.get('source_sha256') == {k: contract['input_sha256'][p] for k, p in LOCALIZATION_INPUTS.items()},
            'Localization current-source extraction differs')
    require(value.get('baseline_sha256') == {k: contract['delivered_baseline']['input_sha256'][p]
                                           for k, p in LOCALIZATION_INPUTS.items()},
            'Localization baseline-source extraction differs')
    require(value.get('fixture_inputs') == {n: contract['input_sha256'][LOCALIZATION + '/' + n]
                                          for n in LOCALIZATION_FILES}, 'Localization fixture hashes differ')
    require(value.get('key_count') == 157 and value.get('localized_value_count') == 628 and
            value.get('expected_native_case_count') == 1076 and
            value.get('expected_case_names') == contract['case_names']['setup-localization'],
            'Localization exact case contract differs')
    hashes = value.get('output_sha256')
    require(isinstance(hashes, dict) and 'fixture.swift' in hashes and 'baseline_missing_keys.json' in hashes,
            'Localization generated closure absent')
    require({n: digest(regular(root, n).read_bytes()) for n in hashes} == hashes,
            'Localization generated bytes differ')
    require(set(root.glob('*.swift')) == {root / 'fixture.swift'}, 'Unexpected localization generated Swift')
    static = json.loads(regular(root, 'static-contract.json').read_text())
    require(static.get('schema') == 'setup-localization-static-contract-v1' and static.get('status') == 'pass' and
            static.get('candidate_key_coverage') == 'pass' and static.get('baseline_key_coverage') == 'fail_as_expected' and
            len(static.get('baseline_missing', [])) == 52 and
            static.get('missing_translation_mutation_cases') == 628 and
            isinstance(static.get('identity_diagnostic_keys'), list) and
            len(set(static['identity_diagnostic_keys'])) == len(static['identity_diagnostic_keys']) == 6 and
            static.get('source_sha256') == value['source_sha256'] and
            static.get('baseline_sha256') == value['baseline_sha256'],
            'Localization static/negative-control receipt differs')
    return value


class Runner:
    def __init__(self, output):
        self.output, self.commands = output, []
    def command(self, name, argv, marker=None, *, collect_compile_failure=False):
        require(name in COMMANDS and name not in [r['name'] for r in self.commands], 'Unexpected/repeated setup command')
        require(not collect_compile_failure or (name in COMPILE_COMMANDS and marker is None),
                'Only setup compile commands may collect failures')
        row = {'name': name, 'argv': list(map(str, argv)), 'exit_code': None}
        self.commands.append(row)
        log = self.output / ('commands/' + name + '.log')
        log.parent.mkdir(exist_ok=True)
        try:
            result = subprocess.run(row['argv'], cwd=self.output, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=300)
            data, row['exit_code'] = result.stdout, result.returncode
        except subprocess.TimeoutExpired as error:
            data = (error.stdout or b'') + b'\nCOMMAND_TIMEOUT\n'
            row['timed_out'] = True
        except OSError as error:
            data = str(error).encode()
            row['launch_error'] = type(error).__name__
        log.write_bytes(data)
        row.update(log=log.relative_to(self.output).as_posix(), stdout_sha256=digest(data))
        if not collect_compile_failure:
            require(type(row['exit_code']) is int and row['exit_code'] == 0, 'Setup command failed: ' + name)
        if marker:
            require_marker(data.decode('utf-8', errors='replace'), marker)
            row['success_marker'] = marker
        return row


def variant_extraction(output, contract, suite, variant):
    root = output / suite / variant
    value = json.loads(regular(root, 'sources.json').read_text())
    schemas = {'early-refresh-boundaries': 'early-refresh-source-extraction-v1',
               'certificate-portal-evidence': 'certificate-portal-evidence-sources-v2'}
    require(value.get('schema') == schemas[suite] and value.get('variant') == variant and
            value.get('status') == 'GENERATED_NOT_COMPILED_NOT_RUN', 'Variant extraction identity differs')
    for key in ('swift_executed', 'native_provider_executed', 'network_executed'):
        require(value.get(key) is False, 'Unbounded fixture generation: ' + key)
    names = contract['case_names'][suite]
    require(value.get('expected_case_names') == names and value.get('expected_case_count') == len(names),
            'Variant extraction case closure differs')
    spec = SUITE_INPUTS[suite]
    production = contract['delivered_baseline']['input_sha256'] if variant == 'baseline' else contract['input_sha256']
    require(value.get('inputs_sha256') == {p: production[p] for p in spec['production']},
            'Variant actual-source inputs differ')
    require(value.get('support_inputs_sha256') == {p: contract['input_sha256'][p] for p in spec['support']},
            'Variant candidate support inputs differ')
    if suite == 'early-refresh-boundaries':
        require(value.get('admitted_route_body_extracted') is (variant == 'candidate'),
                'Early-refresh admitted-route helper extraction differs')
        require(value.get('fixture_inputs_sha256') == {p: contract['input_sha256'][p] for p in spec['fixture']},
                'Early-refresh fixture inputs differ')
        hashes = {'early-refresh.swift': value.get('generated_sha256')}
    else:
        hashes = value.get('generated_sha256')
        require(isinstance(hashes, dict) and set(hashes) == {'host.swift', 'service.swift'},
                'Portal exact generated closure differs')
    require({p.name for p in root.glob('*.swift')} == set(hashes), 'Unexpected generated Swift file')
    require({p: digest(regular(root, p).read_bytes()) for p in hashes} == hashes,
            'Variant generated source bytes differ')
    return value



def identity_extraction(output, contract):
    root = output / 'remote-identity-reuse'
    value = json.loads(regular(root, 'source-evidence.json').read_text())
    require(value.get('schema') == 'remote-identity-reuse-source-evidence-v1' and
            value.get('status') == 'GENERATED_NOT_COMPILED_NOT_RUN', 'Identity source extraction status differs')
    for key in ('swift_executed', 'network_executed', 'native_provider_executed', 'native_keychain_executed'):
        require(value.get(key) is False, 'Unbounded identity generation: ' + key)
    spec = SUITE_INPUTS['remote-identity-reuse']
    for key, paths, inventory in (
        ('inputs_sha256', spec['production'], contract['input_sha256']),
        ('baseline_inputs_sha256', spec['production'], contract['delivered_baseline']['input_sha256']),
        ('support_inputs_sha256', spec['support'], contract['input_sha256'])):
        require(value.get(key) == {p: inventory[p] for p in paths}, 'Identity actual-source input closure differs: ' + key)
    require(value.get('expected_case_names') == contract['case_names']['remote-identity-reuse'],
            'Identity source-owned expected cases differ')
    hashes = value.get('outputs_sha256')
    require(isinstance(hashes, dict) and set(hashes) == set(IDENTITY_SWIFT) and
            {p.name for p in root.glob('*.swift')} == set(IDENTITY_SWIFT), 'Identity generated Swift closure differs')
    require({p: digest(regular(root, p).read_bytes()) for p in hashes} == hashes,
            'Identity generated source bytes differ')
    require(value.get('baseline_source_gaps') == {'protected_identity_record_absent': True,
            'protected_identity_adapter_absent': True, 'attempt_identity_only': True},
            'Delivered baseline identity negative controls differ')
    require(value.get('candidate_source_wiring') == {name: True for name in IDENTITY_SOURCE_WIRING},
            'Identity exact source-wiring controls differ')
    spans = value.get('production_extracts')
    require(isinstance(spans, list) and len(spans) > 0 and all(
        isinstance(row, dict) and row.get('source') in spec['production'] and
        isinstance(row.get('anchor'), str) and row['anchor'] and
        type(row.get('first_line')) is int and row['first_line'] > 0 and
        isinstance(row.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', row['sha256']) for row in spans),
        'Identity production extraction receipts differ')
    return value


def all_evidence(output, contract):
    evidence = {'baseline': baseline_receipt(output, contract),
                'localization': localization_extraction(output, contract), 'variants': {}, 'cases': {}}
    evidence['cases']['setup-localization'] = exact_cases(
        regular(output, 'setup-localization/cases.json'), 'setup-localization-cases-v1',
        contract['case_names']['setup-localization'])
    early_static = json.loads(regular(output, 'early-refresh-boundaries/contract.json').read_text())
    require(early_static.get('schema') == 'early-refresh-portable-contract-v1' and
            early_static.get('status') == 'STATIC_PASS_RUNTIME_NOT_RUN' and
            early_static.get('check_count') == len(early_static.get('checks', [])) == 102 and
            early_static.get('expected_generic_baseline_cases') == 12 and
            early_static.get('variants') == ['baseline', 'candidate'] and
            early_static.get('swift_compiled') is False and early_static.get('swift_executed') is False,
            'Early-refresh static controls differ')
    portal_static = json.loads(regular(output, 'certificate-portal-evidence/static-controls.json').read_text())
    require(portal_static.get('schema') == 'portal-portability-controls-v1' and portal_static.get('status') == 'pass' and
            portal_static.get('check_count') == len(portal_static.get('checks', [])) == 6 and
            portal_static.get('swift_executed') is False and portal_static.get('network_executed') is False,
            'Portal static controls differ')
    evidence['static_controls'] = {'early': early_static, 'portal': portal_static}
    for suite in ('early-refresh-boundaries', 'certificate-portal-evidence'):
        for variant in ('baseline', 'candidate'):
            key = suite + '/' + variant
            evidence['variants'][key] = variant_extraction(output, contract, suite, variant)
            if suite == 'early-refresh-boundaries':
                evidence['cases'][key] = exact_cases(regular(output, key + '/cases.json'),
                    'early-refresh-cases-v1', contract['case_names'][suite], variant=variant,
                    network_executed=False, native_provider_executed=False)
            else:
                evidence['cases'][key] = exact_cases(regular(output, key + '/results.json'),
                    'portal-evidence-runtime-v1', contract['case_names'][suite], candidate=variant == 'candidate',
                    fake_only=True, network_executed=False, native_provider_executed=False)
    evidence['identity'] = identity_extraction(output, contract)
    evidence['cases']['remote-identity-reuse'] = exact_cases(
        regular(output, 'remote-identity-reuse/cases.json'), 'remote-identity-reuse-cases-v1',
        contract['case_names']['remote-identity-reuse'], fake_only=True,
        network_executed=False, native_provider_executed=False, native_keychain_executed=False)
    return evidence


def markers():
    result = {'localization-run': 'SETUP_LOCALIZATION_RENDERER_PASS cases=1076',
              'identity-controls': 'OK',
              'identity-run': 'REMOTE_IDENTITY_REUSE_RUNTIME_PASS cases=' + str(IDENTITY_CASE_COUNT)}
    for variant in ('baseline', 'candidate'):
        result['early-' + variant + '-run'] = 'PASS early_refresh_actual_appmanager_pipeline_source_chain cases=24'
        result['portal-' + variant + '-run'] = 'PASS portal_service_' + variant + ' cases=19'
        result['portal-' + variant + '-host-run'] = 'PASS portal_json_ipc_copy cases=19'
    return result


def verify_receipt(path, contract_path=None):
    contract_path = contract_path or HERE / 'setup-state-recovery-contract.json'
    contract = load_contract(contract_path)
    report = json.loads(path.read_text())
    require(report.get('schema') == 'setup-state-recovery-run-v1' and report.get('status') == STATUS and
            report.get('suites') == list(SUITES), 'Setup-state fixtures did not pass')
    require(report.get('contract_sha256') == digest(contract_path.read_bytes()), 'Setup contract receipt differs')
    require(report.get('source_inputs_before') == contract['input_sha256'] and
            report.get('source_inputs_after') == contract['input_sha256'] and
            report.get('source_input_bytes_unchanged') is True, 'Setup input immutability missing')
    for key in ('network_executed', 'native_provider_executed', 'native_keychain_executed', 'app_executed', 'device_executed'):
        require(report.get(key) is False, 'Forbidden setup execution claim: ' + key)
    require(report.get('source_owned_fixtures_executed') is True, 'Setup source fixtures did not execute')
    commands = report.get('commands', [])
    require([r.get('name') for r in commands] == list(COMMANDS), 'Missing or repeated setup command')
    for row in commands:
        require(type(row.get('exit_code')) is int and row['exit_code'] == 0 and
                not row.get('timed_out') and not row.get('launch_error'), 'Setup command did not pass')
        if row['name'].endswith('-compile'):
            args = row.get('argv', [])
            expected = ['-swift-version', '5', '-parse-as-library']
            if row['name'].startswith('portal-') and '-host-' not in row['name']:
                expected += ['-module-name', 'SideSign']
            if row['name'] == 'identity-compile':
                expected += ['-framework', 'Security']
                require(len(args) == 1 + len(expected) + len(IDENTITY_SWIFT) + 2 and
                        args[1:1 + len(expected)] == expected and args[-2] == '-o' and
                        [Path(p).name for p in args[1 + len(expected):-2]] == list(IDENTITY_SWIFT),
                        'Identity compile-only argument closure differs')
            else:
                require(len(args) == len(expected) + 4 and args[1:1 + len(expected)] == expected and
                        args[-2] == '-o' and args[-3].endswith('.swift'),
                        'Compile-only source fixture argument closure differs')
        log = regular(path.parent, row['log']).read_bytes()
        require(digest(log) == row.get('stdout_sha256'), 'Setup command log changed')
        if row['name'] in markers():
            marker = markers()[row['name']]
            require(row.get('success_marker') == marker, 'Setup marker receipt differs')
            require_marker(log.decode('utf-8', errors='replace'), marker)
    require(report.get('evidence') == all_evidence(path.parent, contract), 'Setup evidence receipt differs')
    require(report.get('artifact_sha256') == artifact_inventory(path.parent), 'Setup retained artifact changed')
    return report


def run(sources, swiftc, output, contract_path=None):
    contract_path = contract_path or HERE / 'setup-state-recovery-contract.json'
    contract = load_contract(contract_path)
    require(not sources.is_symlink(), 'Symlink setup source root')
    sources = sources.resolve(strict=True)
    before = inventory(sources, contract)
    require(not output.exists() and not output.is_symlink() and
            not output.resolve().is_relative_to(sources), 'Setup output must be fresh and outside sources')
    require(swiftc.is_file(), 'Missing Swift compiler')
    swiftc = swiftc.resolve()
    output.mkdir(parents=True)
    output = output.resolve()
    runner = Runner(output)
    report = {'schema': 'setup-state-recovery-run-v1', 'status': 'FAILED', 'suites': [],
              'contract_sha256': digest(contract_path.read_bytes()), 'source_inputs_before': before,
              'source_inputs_after': {}, 'source_input_bytes_unchanged': False,
              'network_executed': False, 'native_provider_executed': False,
              'app_executed': False, 'device_executed': False, 'native_keychain_executed': False,
              'source_owned_fixtures_executed': False,
              'commands': runner.commands}
    def python(relative):
        require(relative in before, 'Setup command source not bound')
        return [sys.executable, '-B', regular(sources, relative)]
    def compile(name, file, binary, module=None):
        require(file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(output),
                'Unsafe generated setup source')
        args = [swiftc, '-swift-version', '5', '-parse-as-library']
        if module:
            require(module == 'SideSign', 'Unexpected setup fixture module')
            args += ['-module-name', module]
        runner.command(name, args + [file, '-o', binary], collect_compile_failure=True)
    try:
        baseline = output / 'delivered-baseline'
        runner.command('delivered-baseline-extract', [sys.executable, '-B', Path(__file__).resolve(),
            'extract-baseline', '--sources', sources, '--contract', contract_path, '--output', baseline,
            '--receipt', output / 'delivered-baseline.json'])
        baseline_receipt(output, contract)
        localization = output / 'setup-localization'
        runner.command('localization-source', python(LOCALIZATION + '/test_setup_localization_contract.py') +
            ['--candidate-root', sources / 'LiveContainer', '--baseline-root', baseline / 'LiveContainer',
             '--output', localization])
        localization_extraction(output, contract)
        early = output / 'early-refresh-boundaries'
        runner.command('early-source', python(EARLY + '/test_contract.py') +
            ['--candidate-root', sources, '--baseline-root', baseline, '--output', early])
        for variant in ('baseline', 'candidate'):
            variant_extraction(output, contract, 'early-refresh-boundaries', variant)
        portal = output / 'certificate-portal-evidence'
        runner.command('portal-source', python(PORTAL + '/test_generator.py') +
            ['--candidate-root', sources, '--baseline-root', baseline, '--output', portal])
        for variant in ('baseline', 'candidate'):
            variant_extraction(output, contract, 'certificate-portal-evidence', variant)
        identity = output / 'remote-identity-reuse'
        runner.command('identity-controls', python(IDENTITY + '/test_generator.py'), markers()['identity-controls'])
        runner.command('identity-source', python(IDENTITY + '/generate_fixture.py') +
            ['--candidate-root', sources, '--baseline-root', baseline, '--output', identity])
        identity_extraction(output, contract)
        identity_files = [regular(identity, name) for name in IDENTITY_SWIFT]

        # The four families are independent until runtime. Compile each closure once,
        # retaining every compiler failure; no fixture may run until all eight pass.
        compile('localization-compile', localization / 'fixture.swift', localization / 'fixture')
        for variant in ('baseline', 'candidate'):
            folder = early / variant
            compile('early-' + variant + '-compile', folder / 'early-refresh.swift', folder / 'fixture')
        for variant in ('baseline', 'candidate'):
            folder = portal / variant
            prefix = 'portal-' + variant
            compile(prefix + '-compile', folder / 'service.swift', folder / 'service', module='SideSign')
            compile(prefix + '-host-compile', folder / 'host.swift', folder / 'host')
        runner.command('identity-compile', [swiftc, '-swift-version', '5', '-parse-as-library',
            '-framework', 'Security', *identity_files, '-o', identity / 'fixture'], collect_compile_failure=True)
        compiled = [row for row in runner.commands if row['name'] in COMPILE_COMMANDS]
        require([row['name'] for row in compiled] == list(COMPILE_COMMANDS), 'Setup compile closure differs')
        failed = [row['name'] for row in compiled if type(row['exit_code']) is not int or
                  row['exit_code'] != 0 or row.get('timed_out') or row.get('launch_error')]
        require(not failed, 'Setup compile commands failed: ' + ', '.join(failed))

        runner.command('localization-run', [localization / 'fixture', localization], markers()['localization-run'])
        for variant in ('baseline', 'candidate'):
            folder = early / variant
            name = 'early-' + variant + '-run'
            runner.command(name, [folder / 'fixture', folder / 'cases.json'], markers()[name])
        for variant in ('baseline', 'candidate'):
            folder = portal / variant
            prefix = 'portal-' + variant
            runner.command(prefix + '-run', [folder / 'service', folder / 'cases.plist'], markers()[prefix + '-run'])
            runner.command(prefix + '-host-run', [folder / 'host', folder / 'cases.plist', folder / 'results.json'],
                           markers()[prefix + '-host-run'])
        runner.command('identity-run', [identity / 'fixture', '--cases-output', identity / 'cases.json'],
                       markers()['identity-run'])
        report['evidence'] = all_evidence(output, contract)
        require([r['name'] for r in runner.commands] == list(COMMANDS), 'Setup command order differs')
        report['source_inputs_after'] = inventory(sources, contract)
        require(report['source_inputs_after'] == before, 'Setup fixtures changed source inputs')
        report.update(source_input_bytes_unchanged=True, source_owned_fixtures_executed=True,
                      suites=list(SUITES), status=STATUS)
    except Exception as error:
        report['failure'] = str(error)
        raise
    finally:
        report['artifact_sha256'] = artifact_inventory(output)
        write_json(output / 'report.json', report)
    return verify_receipt(output / 'report.json', contract_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'extract-baseline', 'verify'])
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--swiftc', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--contract', type=Path, default=HERE / 'setup-state-recovery-contract.json')
    args = parser.parse_args()
    if args.action == 'extract-baseline':
        extract_baseline(args.sources, load_contract(args.contract), args.output, args.receipt)
        print('EXACT_DELIVERED_SETUP_BASELINE_EXTRACTED_NO_NETWORK')
    elif args.action == 'verify':
        verify_receipt(args.receipt, args.contract)
        print(STATUS)
    else:
        run(args.sources, args.swiftc, args.output, args.contract)
        print(STATUS)


if __name__ == '__main__':
    main()
