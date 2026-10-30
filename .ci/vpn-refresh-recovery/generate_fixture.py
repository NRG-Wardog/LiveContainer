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
RUNNER = 'SideStore/SideStore/Core/Operations/PipelineRunner.swift'
TRANSPORT_FIXTURE = 'SideStore/tests/vpn_transport_recovery/generate_fixture.py'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def validate_current_cold_guard(text, pinned_guard, block):
    guard = block(text, pinned_guard['anchor'])
    assert hashlib.sha256(guard.encode()).hexdigest() == pinned_guard['sha256'], 'Current cold peer guard changed'
    observation = block(text, 'private func readinessObservation(')
    assert guard in observation, 'Cold peer guard detached from actual observation'
    forwarding = block(text, 'func isReady(withNetworkCheck:')
    assert hashlib.sha256(forwarding.encode()).hexdigest() == pinned_guard['forwarding_sha256'], 'Ordinary readiness forwarding changed'
    return guard

def verify_cold_guard_negative_controls(text, pinned_guard, block):
    validate_current_cold_guard(text, pinned_guard, block)
    for old, new in [
        ('VPN tunnel iface is up but tunnel peer IP is not yet reachable', 'unclassified peer failure'),
        ('owned: false).result', 'owned: true).result'),
        ('private func readinessObservation(', 'private func detachedReadinessObservation('),
    ]:
        assert old in text
        mutated = text.replace(old, new, 1)
        try:
            validate_current_cold_guard(mutated, pinned_guard, block)
        except (AssertionError, ValueError):
            continue
        raise AssertionError('Cold guard negative control was accepted: ' + old)

def validate_classifier_dependency(swift, declaration):
    # The composite disables the transport generator's classifier, then includes
    # the actual classifier itself. Its production dependency must accompany it.
    assert swift.count(declaration) == 1, 'Actual selection failure dependency missing or duplicated'
    assert swift.count('struct V3RefreshSelectionFailure:') == 1, 'Selection failure dependency replaced or duplicated'
    assert 'error as? V3RefreshSelectionFailure' in swift, 'Actual selection classifier dependency changed'

def generate(root, output):
    root, output = root.resolve(), output.resolve()
    spec = importlib.util.spec_from_file_location('vpn_wire_extract', root / HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    host = (root / HOST).read_text(); model = (root / MODEL).read_text()
    transport_spec = importlib.util.spec_from_file_location('vpn_transport_extract', root / TRANSPORT_FIXTURE)
    transport_helper = importlib.util.module_from_spec(transport_spec); transport_spec.loader.exec_module(transport_helper)
    transport_source, transport_inputs = transport_helper.generate_source(root, include_operation_classifier=False)
    runner = (root / RUNNER).read_text()
    early_capture = helper.block(runner, 'enum V3RefreshEarlyFailureBoundary {')
    owned_wait = helper.block(runner, 'enum V3OwnedRefreshReadinessWait {')
    structured_capture = helper.block((root / PRODUCER).read_text(), 'func lcStructuredSigningFailure(')
    assert 'V3RefreshEarlyFailureBoundary.readiness.preserving(' in runner
    assert 'if error is CancellationError { throw error }' in runner
    assert 'if let native = error as? MinimuxerError { typedError = native.asOperationError }' in runner
    assert 'else { typedError = error }' in runner
    assert 'V3HeadlessPairingFailure.tagIfInvalidPairing(typedError), operations: operations)' in runner
    assert 'group.context.error = opError' in runner

    anchors = ['enum LiveContainerVPNRefreshRecoveryPolicy {',
               'final class LiveContainerVPNActivationWaiter {',
               'enum LiveContainerVPNReturnMarkerPolicy {']
    policy, waiter, marker = [helper.block(host, x) for x in anchors]
    attempt = helper.block(host, 'private static func performRefreshWithVPNRecovery(')
    preflight = helper.block(host, 'static func check(allowForegroundActivation:')
    settle = helper.block(host, 'static func settleAfterActivation(')
    enable = helper.block(host, 'static func enableInForeground(')
    assert 'let activationAttempted = try await LiveContainerNetworkPreflight.check(' in host
    assert 'hasBackgroundTask: task != nil, activationAlreadyAttempted: activationAttempted,' in host
    assert 'allowForegroundActivation: manual && source != "vpn_return" && task == nil' in host
    assert 'return activationAttempted' in preflight and 'activationAttempted = true' in preflight
    assert preflight.count('enableInForeground(') == 1
    assert 'LiveContainerVPNPostActivationPolicy.wait(' in settle
    assert 'now: { ProcessInfo.processInfo.systemUptime }' in settle
    assert 'ownsRun: ownsRun' in settle
    assert settle.count('NWPathMonitor(requiredInterfaceType: .wifi)') == 1
    assert 'defer { monitor.pathUpdateHandler = nil; monitor.cancel() }' in settle
    assert 'Task.sleep(nanoseconds: 2_000_000_000)' not in settle
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
    selection_failure = helper.block(transport_inputs['selection'].read_text(), 'struct V3RefreshSelectionFailure:')
    # Cross-layer classifier must remain exact; no broad noDevice matching.
    cold_source = json.loads((HERE / 'cold-peer-source.json').read_text())
    cold_message = cold_source['exact_local_noDevice_message']
    assert cold_message.endswith('Cause: DeviceEndpointNotInitialized')
    assert 'message == ' + json.dumps(cold_message, ensure_ascii=False) in producer
    assert 'facts["refresh_readiness_reason"] = "peerAddressUnavailable"' in producer
    for anchor in ['public struct CombinedFailure:', 'public struct V3RefreshProfileEvidence {', 'public enum CombinedVerification {']:
        assert helper.block(service, anchor) == helper.block(model, anchor), anchor

    original = (HERE / 'OriginalRefreshReadinessFacts.swift').read_text()
    assert hashlib.sha256(original.encode()).hexdigest() == cold_source['baseline_classifier_source']['extracted_sha256']
    assert 'peerAddressUnavailable' not in original
    original = original.replace('func lcRefreshFailureFacts(', 'func lcRefreshFailureFactsBeforeColdVPN(', 1)
    # Full native checkouts bind the guard to the actual dependency source.
    # Sparse offline generation retains an explicit pinned provenance receipt.
    dependency = root / 'SideStore/Dependencies/minimuxer'
    live_guard_inputs = {}
    if dependency.is_dir():
        for path, expected in cold_source['source_files'].items():
            actual = sha(dependency / path)
            pinned_guard = cold_source.get('candidate_guard_blocks', {}).get(path)
            if pinned_guard:
                # Historical baseline bytes stay immutable. The reviewed current
                # guard wraps the same failure in an owned-readiness observation.
                # Bind its actual body and ordinary isReady forwarding, not a copy.
                verify_cold_guard_negative_controls((dependency / path).read_text(), pinned_guard, helper.block)
            else:
                assert actual == expected['sha256'], 'Cold VPN guard dependency changed: ' + path
            live_guard_inputs[path] = actual
    cold_constant = 'let coldVPNPeerGuardMessage = ' + json.dumps(cold_message, ensure_ascii=False) + '\n'

    errors = helper.block((root / ERRORS).read_text(), 'public enum OperationError:')
    cases = (HERE / 'cases.swift').read_text()
    names = re.findall(r'^        check\("([^"]+)"', cases, re.M)
    assert len(names) == len(set(names)) and len(names) >= 35
    swift = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    platform = (HERE / 'PlatformDoubles.swift').read_text()
    keys = ['activeRunKey', 'expectedRunKey', 'activeManualRequestKey', 'verificationKey',
            'hostHandoffKey', 'uncertainMutationKey', 'hostVerifiedKey', 'runLedgerKey']
    declarations = []
    for key in keys:
        found = re.findall(r'^    static let ' + key + r' = .*$', host, re.M)
        assert len(found) == 1, key
        declarations += found
    scheduler_blocks = [helper.block(host, x) for x in [
        'private static func runLedger()', 'private static func ownsNetworkPreflight(', 'private static func performRefreshWithVPNRecovery(',
        'private static func verifyRefreshManifest(']]
    platform = platform.replace('// ACTUAL_SCHEDULER_KEYS', '\n'.join(declarations))
    platform = platform.replace('// ACTUAL_SCHEDULER_METHODS', '\n'.join(scheduler_blocks))
    network_preflight = helper.block(host, 'enum LiveContainerNetworkPreflight {')
    activation_state = helper.block(host, 'final class LiveContainerVPNActivationState {')
    # Transparent observation of the production observer's original assignment.
    # No fixture code sets leftHost; only its actual didEnterBackground handler
    # can acknowledge the fake application's return event. All decisions and
    # the preflight/activation method bodies remain byte-exact source extracts.
    observed_storage = 'var leftHost = false { didSet { FixtureLifecycle.observedLeftHost(leftHost) } }'
    assert activation_state.count('var leftHost = false') == 1
    instrumented_state = activation_state.replace('var leftHost = false', observed_storage, 1)
    assert instrumented_state.replace(observed_storage, 'var leftHost = false', 1) == activation_state

    swift += helper.pure_model(model) + '\n' + errors + '\n' + selection_failure + '\n' + producer + '\n'
    swift += 'func debugLog(_ text: String) {}\nfunc verboseLog(_ text: String) {}\n'
    swift += transport_source + '\n' + owned_wait + '\n' + early_capture + '\n' + structured_capture + '\n'
    observation_policy = helper.block(host, 'enum LiveContainerVPNPostActivationPolicy {')
    observation_owner = helper.block(host, 'enum LiveContainerVPNPostActivationOwnership {')
    observation_state = helper.block(host, 'final class LiveContainerVPNPathObservation {')
    swift += observation_policy + '\n' + observation_owner + '\n@MainActor\n' + observation_state + '\n'
    swift += platform + '\n' + original + '\n' + cold_constant + policy + '\n@MainActor\n' + waiter
    swift += '\n@MainActor\n' + instrumented_state + '\n' + marker + '\n@MainActor\n' + network_preflight + '\n' + cases

    validate_classifier_dependency(swift, selection_failure)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'vpn-refresh-recovery.swift').write_text(swift)
    receipt = {'schema': 'vpn-refresh-recovery-sources-v1', 'status': 'STATIC_PASS_GENERATED_NOT_COMPILED_NOT_RUN',
        'input_root': str(root), 'inputs_sha256': {x: sha(root / x) for x in [HOST, MODEL, PRODUCER, ERRORS, HELPER, CLIENT, SERVICE, RUNNER, TRANSPORT_FIXTURE]},
        'support_inputs_sha256': live_guard_inputs,
        'transport_fixture_inputs_sha256': {str(path.relative_to(root)): sha(path) for path in transport_inputs.values()},
        'cold_guard_provenance': 'actual_current_guard_and_forwarding_with_historical_baseline' if live_guard_inputs else 'pinned_source_receipt_sparse_generation',
        'fixture_inputs_sha256': {x: sha(HERE / x) for x in ['generate_fixture.py', 'cases.swift', 'OriginalRefreshReadinessFacts.swift', 'cold-peer-source.json', 'PlatformDoubles.swift']},
        'generated_sha256': hashlib.sha256(swift.encode()).hexdigest(),
        'expected_case_names': names, 'expected_case_count': len(names),
        'extracted_blocks': anchors + ['enum LiveContainerVPNPostActivationPolicy {', 'enum LiveContainerVPNPostActivationOwnership {', 'final class LiveContainerVPNPathObservation {', 'private static func ownsNetworkPreflight(', 'enum LiveContainerNetworkPreflight {', 'private static func performRefreshWithVPNRecovery(', 'private static func verifyRefreshManifest(', 'enum V3OwnedRefreshReadinessWait {', 'enum V3RefreshEarlyFailureBoundary {', 'func lcStructuredSigningFailure(', 'func lcRefreshFailureFacts(', 'public enum OperationError:'],
        'baseline_classifier_sha256': cold_source['baseline_classifier_source']['extracted_sha256'],
        'fixture_observation_hook': {'source': HOST, 'anchor': 'final class LiveContainerVPNActivationState {',
            'original_sha256': hashlib.sha256(activation_state.encode()).hexdigest(),
            'instrumented_sha256': hashlib.sha256(instrumented_state.encode()).hexdigest(),
            'exact_insertion_count': 1,
            'description': 'Observation-only didSet on leftHost awaits the original background observer assignment before injecting active; no fixture writes leftHost and no production decision or method body changes.'},
        'swift_compiled': False, 'swift_executed': False, 'network_executed': False, 'native_provider_executed': False,
        'boundary_contract': 'Actual interface scanner/transport selection/unavailable producer/error mapper, readiness capture, binary-plist per-app sanitizer/decoder, host preflight/activation and scheduler methods. Frozen exact old producer is the negative control. Only OS interfaces, Wi-Fi observations, UIApplication lifecycle/open completion, preferences and external refresh completion are doubles. The existing 72 policy cases remain. Real UIKit/NWPathMonitor, native transport, Keychain and provider are never executed.',
        'limits': ['Generation/static checks only.', 'No device VPN activation or on-device readiness proof.']}
    (output / 'sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print('VPN_REFRESH_RECOVERY_STATIC_PASS_RUNTIME_NOT_RUN cases=' + str(generate(args.candidate_root, args.output)['expected_case_count']))
