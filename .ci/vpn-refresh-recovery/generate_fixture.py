#!/usr/bin/env python3
"""Extract actual VPN retry policy and producer; generate only, never compile/run Swift."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, re, sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HOST = 'LiveContainer/LiveContainerSwiftUI/App/AppDelegate.swift'
MODEL = 'LiveContainer/SideStoreSupport/SideStore.swift'
PRODUCER = 'SideStore/SideStore/Core/Operations/PipelineExecutor.swift'
ERRORS = 'SideStore/SideStore/Core/Operations/Errors/OperationError.swift'
HELPER = 'LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py'
CLIENT = 'LiveContainer/SideStoreSupport/XPCClient.m'
SERVICE = 'SideStore/AltStore/AppDelegate.swift'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def generate(root, output):
    root, output = root.resolve(), output.resolve()
    spec = importlib.util.spec_from_file_location('vpn_wire_extract', root / HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    host = (root / HOST).read_text(); model = (root / MODEL).read_text()
    anchors = ['enum LiveContainerVPNRefreshRecoveryPolicy {',
               'final class LiveContainerVPNActivationWaiter {',
               'enum LiveContainerVPNReturnMarkerPolicy {']
    policy, waiter, marker = [helper.block(host, x) for x in anchors]
    attempt = helper.block(host, 'private static func performRefreshWithVPNRecovery(')
    preflight = helper.block(host, 'static func check(allowForegroundActivation:')
    settle = helper.block(host, 'static func settleAfterActivation()')
    enable = helper.block(host, 'static func enableInForeground(')
    assert 'let activationAttempted = try await LiveContainerNetworkPreflight.check(' in host
    assert 'hasBackgroundTask: task != nil, activationAlreadyAttempted: activationAttempted,' in host
    assert 'allowForegroundActivation: manual && source != "vpn_return" && task == nil' in host
    assert 'return activationAttempted' in preflight and 'activationAttempted = true' in preflight
    assert preflight.count('enableInForeground(') == 1
    assert 'Task.sleep(nanoseconds: 2_000_000_000)' in settle
    assert 'guard await wifiAvailable()' in settle and 'guard hasTunnelInterface()' in settle
    assert 'try Task.checkCancellation()' in settle
    assert 'LiveContainerVPNRefreshRecoveryPolicy.run(' in attempt
    assert 'defaults.removeObject(forKey: verificationKey)' in attempt
    assert 'defaults.string(forKey: uncertainMutationKey) == nil' in attempt
    assert 'performRefresh(runID: runID)' in attempt and 'verifyRefreshManifest(' in attempt
    assert 'UIApplication.shared.applicationState == .active' in enable
    assert 'localdevvpn://enable' in enable and '.now() + 30' in enable
    assert 'case .openFailed:' in enable and 'throw failure(3,' in enable
    assert 'case .timedOut:' in enable and 'throw failure(4,' in enable
    assert 'withTaskCancellationHandler' in enable
    assert 'native.code == 3 ? .unavailable' in host and 'native.code == 4 ? .timedOut' in host
    # Confirm same scheduler run may dispatch again without cached command replay.
    client_bytes = (root / CLIENT).read_bytes()
    assert hashlib.sha1(b'blob ' + str(len(client_bytes)).encode() + b'\0' + client_bytes).hexdigest() == 'ed031c9f09879ab81f5feeacb141c72ceb076a38'
    native_dispatch = helper.block(client_bytes.decode(), '- (void)refreshAllAppsWithIdentifier:')
    assert '[self performRefreshForRealWithIdentifier:identifier mangledTypeName:mangledTypeName server:handler.server];' in native_dispatch
    assert 'if (refreshRunID.length) [defaults setObject:refreshRunID' in native_dispatch
    assert 'let id = UUID().uuidString' in helper.block(model, 'public func request(operation:')
    service = (root / SERVICE).read_text()
    assert 'if let previous = completed[id]' in helper.block(service, 'private func receive(')
    assert 'record = nil' in helper.block(service, 'mutating func settleRefreshAdmission(')
    producer = helper.block((root / PRODUCER).read_text(), 'func lcRefreshFailureFacts(')
    errors = helper.block((root / ERRORS).read_text(), 'public enum OperationError:')
    cases = (HERE / 'cases.swift').read_text()
    names = re.findall(r'^        check\("([^"]+)"', cases, re.M)
    assert len(names) == len(set(names)) and len(names) >= 35
    swift = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    swift += helper.pure_model(model) + '\n' + errors + '\n' + producer + '\n'
    swift += policy + '\n@MainActor\n' + waiter + '\n' + marker + '\n' + cases
    output.mkdir(parents=True, exist_ok=True)
    (output / 'vpn-refresh-recovery.swift').write_text(swift)
    receipt = {'schema': 'vpn-refresh-recovery-sources-v1', 'status': 'STATIC_PASS_GENERATED_NOT_COMPILED_NOT_RUN',
        'input_root': str(root), 'inputs_sha256': {x: sha(root / x) for x in [HOST, MODEL, PRODUCER, ERRORS, HELPER, CLIENT, SERVICE]},
        'support_inputs_sha256': {},
        'fixture_inputs_sha256': {x: sha(HERE / x) for x in ['generate_fixture.py', 'cases.swift']},
        'generated_sha256': hashlib.sha256(swift.encode()).hexdigest(),
        'expected_case_names': names, 'expected_case_count': len(names),
        'extracted_blocks': anchors + ['func lcRefreshFailureFacts(', 'public enum OperationError:'],
        'swift_compiled': False, 'swift_executed': False, 'network_executed': False, 'native_provider_executed': False,
        'boundary_contract': 'Actual retry policy/orchestrator, producer, decoder, activation waiter, and return-marker policy. Injected attempt/activate/settle/prepare closures record calls or throw. UIApplication, NWPathMonitor, native transport, Keychain and provider are never executed. Wiring is source-asserted, not runtime-validated.',
        'limits': ['Generation/static checks only.', 'No device VPN activation or on-device readiness proof.']}
    (output / 'sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print('VPN_REFRESH_RECOVERY_STATIC_PASS_RUNTIME_NOT_RUN cases=' + str(generate(args.candidate_root, args.output)['expected_case_count']))
