#!/usr/bin/env python3
"""Extract exact connection-evidence policy and failure decoder; never compile/run Swift."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, re, sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
UI = 'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'
MODEL = 'LiveContainer/SideStoreSupport/SideStore.swift'
MODEL_MIRROR = 'SideStore/AltStore/AppDelegate.swift'
HELPER = 'LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def host_activation_contract(model, helper):
    # Bind the exact failure declaration; unrelated evidence enums also expose message.
    model = helper.block(model, 'public struct CombinedFailure:')
    expected = '''private var localDevVPNActivationMessage: String? {
        guard operation == "refresh", stage == .network,
              safeCause == .localDevVPNUnavailable else { return nil }
        switch code {
        case .unavailable:
            return "LiveContainer could not open LocalDevVPN. Install/open it, enable the connection, then retry."
        case .timedOut:
            return "LocalDevVPN did not return before the activation wait ended. Return to LiveContainer and retry after enabling it."
        default: return nil
        }
    }'''
    assert helper.block(model, 'private var localDevVPNActivationMessage: String?') == expected
    message = helper.block(model, 'public var message: String {')
    call = 'if let activation = localDevVPNActivationMessage { return activation }'
    assert message.count(call) == 1
    assert message.index(call) < message.index('if code == .timedOut {')
    assert 'public var safeMessage: String { messageWithoutDiagnosticCode + "\\n" + diagnosticLabel }' in model
    without_code = helper.block(model, 'private var messageWithoutDiagnosticCode: String {')
    assert 'if operation == "refresh", safeCause == nil {' in without_code
    assert without_code.rstrip().endswith('return message\n    }')
    return expected

def generate(root, output):
    root, output = root.resolve(), output.resolve()
    spec = importlib.util.spec_from_file_location('setup_wire_extract', root / HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    ui = (root / UI).read_text(); model = (root / MODEL).read_text()
    mirror = (root / MODEL_MIRROR).read_text()
    activation = host_activation_contract(model, helper)
    unrelated = 'enum UnrelatedEvidence { public var message: String { "not a failure" } }\n'
    assert host_activation_contract(unrelated + model, helper) == activation
    assert host_activation_contract(mirror, helper) == activation
    mutations = {
        'operation': model.replace('guard operation == "refresh", stage == .network,', 'guard operation == "install", stage == .network,', 1),
        'stage': model.replace('guard operation == "refresh", stage == .network,', 'guard operation == "refresh", stage == .signing,', 1),
        'cause': model.replace('safeCause == .localDevVPNUnavailable else { return nil }', 'safeCause == .networkUnavailable else { return nil }', 1),
        'code': model.replace(activation, activation.replace('case .unavailable:', 'case .failed:', 1), 1),
        'raw_provider_copy': model.replace(activation, activation.replace('default: return nil', 'default: return signingContext["provider_message"]'), 1),
        'missing_override': model.replace('if let activation = localDevVPNActivationMessage { return activation }', '', 1),
        'generic_timeout_precedence': model.replace('if let activation = localDevVPNActivationMessage { return activation }', 'if code == .timedOut { return "generic timeout" }\n        if let activation = localDevVPNActivationMessage { return activation }', 1),
    }
    for name, mutated in mutations.items():
        assert mutated != model, name
        try:
            host_activation_contract(mutated, helper)
        except AssertionError:
            pass
        else:
            raise AssertionError('Host activation mutation was accepted: ' + name)
    anchors = ['struct V3SetupStepState:', 'enum V3SetupConnectionCopy:', 'enum V3SetupConnectionEvidencePolicy {', 'enum V3RefreshAllTerminalEvidencePolicy {']
    extracted = [helper.block(ui, anchor) for anchor in anchors]
    policy = extracted[2]
    assert 'CombinedFailure.decode(wire, expectedID: runID)' in policy
    assert 'failure.operation == "refresh", failure.code == .failed' in policy
    assert 'failure.sourceStep == .refreshReadiness' in policy
    assert '["invalidVPN", "noVPN"].contains(kind ?? "")' in policy
    assert 'V3RefreshAllTerminalEvidencePolicy.verifiedSummary(' in policy
    assert 'localizedDescription' not in policy and 'NSUnderlyingErrorKey' not in policy
    assert 'tunnelComplete: connectionVerified' in ui
    assert 'tunnelComplete: LiveContainerNetworkPreflight.hasTunnelInterface()' not in ui
    assert 'tunnelComplete: V3SetupConnectionEvidencePolicy.observe(' in ui
    assert 'private func coredeviceState() -> V3SetupStepState { setup.coreDevice }' in ui
    assert 'case "complete", "verified": return .green' in ui
    assert 'case "detected": return "Detected"' in ui
    assert 'case "notChecked": return "Not checked"' in ui
    assert 'V3SetupConnectionCopy(rawValue: state.detail)' in ui
    assert 'V3Localization.string(owned.rawValue' in ui
    assert 'testLedgerState = runState\n        refreshConnectionEvidence()' in ui
    assert 'Notification.Name(LiveContainerAutoRefreshScheduler.runStateChangedNotification)' in ui
    catalog = json.loads((root / 'LiveContainer/Resources/Localizable.xcstrings').read_text())
    for text in re.findall(r'case \w+ = "([^"]+)"', extracted[1]):
        assert catalog['strings'][text]['localizations']['en']['stringUnit']['value'] == text
    for text in re.findall(r'return "([^"]+)"', activation):
        for language in ['en', 'he', 'zh-Hans', 'zh-Hant', 'ru']:
            unit = catalog['strings'][text]['localizations'][language]['stringUnit']
            assert unit['state'] == 'translated' and unit['value']
            assert (unit['value'] == text) == (language == 'en')
    cases = (HERE / 'cases.swift').read_text()
    case_names = re.findall(r'^        check\("([^"]+)"', cases, re.M)
    assert len(case_names) == len(set(case_names)) == 25
    swift = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    swift += helper.pure_model(model) + '\n' + '\n\n'.join(extracted) + '\n' + cases
    output.mkdir(parents=True, exist_ok=True)
    (output / 'setup-connection.swift').write_text(swift)
    receipt = {'schema': 'setup-connection-sources-v1', 'status': 'STATIC_PASS_GENERATED_NOT_COMPILED_NOT_RUN',
        'input_root': str(root), 'inputs_sha256': {name: sha(root / name) for name in [UI, MODEL, MODEL_MIRROR, HELPER, 'LiveContainer/Resources/Localizable.xcstrings']},
        'fixture_inputs_sha256': {name: sha(HERE / name) for name in ['generate_fixture.py', 'cases.swift']},
        'generated_sha256': hashlib.sha256(swift.encode()).hexdigest(),
        'expected_case_names': case_names, 'expected_case_count': len(case_names),
        'host_activation_message_contract': 'exact_finite_guard_both_mirrors_before_generic_timeout',
        'host_activation_negative_static_mutations': sorted(mutations),
        'swift_compiled': False, 'swift_executed': False, 'network_executed': False, 'native_provider_executed': False,
        'limits': ['Generation/static checks only; not Swift compilation or runtime.',
            'Synthetic in-memory ledger/wire values; not device, VPN, provider, UI rendering, or pairing execution.']}
    (output / 'sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = generate(args.candidate_root, args.output)
    print('SETUP_CONNECTION_STATIC_PASS_RUNTIME_NOT_RUN cases=' + str(report['expected_case_count']))
