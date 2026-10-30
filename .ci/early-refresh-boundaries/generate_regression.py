#!/usr/bin/env python3
"""Portable actual-source early-refresh regression; generation never runs Swift."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

INPUT_PATHS = {
    'host': 'LiveContainer/SideStoreSupport/SideStore.swift',
    'service': 'SideStore/AltStore/AppDelegate.swift',
    'client': 'LiveContainer/SideStoreSupport/SideStoreClient.swift',
    'scheduler': 'LiveContainer/LiveContainerSwiftUI/App/AppDelegate.swift',
    'ui': 'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
    'producer': 'SideStore/SideStore/Core/Operations/StandaloneOperations/BackgroundRefreshAppsOperation.swift',
    'intent': 'SideStore/AltStore/Intents/App Intents/RefreshAllAppsIntent.swift',
    'manager': 'SideStore/AltStore/Managing Apps/AppManager.swift',
    'pipeline': 'SideStore/SideStore/Core/Operations/PipelineExecutor.swift',
    'pipeline_steps': 'SideStore/SideStore/Core/Operations/OperationStep.swift',
    'app_operation': 'SideStore/SideStore/Core/Operations/AppOperation.swift',
    'operation_error': 'SideStore/SideStore/Core/Operations/Errors/OperationError.swift',
    'error_title': 'SideStore/Shared/Extensions/NSError+AltStore.swift',
    'wrapped_error': 'SideStore/Shared/Errors/ALTWrappedError.swift',
}
SUPPORT_PATHS = [
    'LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py',
    'LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_doubles.swift',
    'LiveContainer/.ci/comprehensive-diagnostics/refresh_handler_doubles.swift',
    'LiveContainer/.ci/comprehensive-diagnostics/refresh_failure_harness.swift',
    'SideStore/tests/refresh_failure/pipeline_harness.swift',
    'SideStore/Dependencies/minimuxer/Sources/MinimuxerApi.swift',
    'SideStore/SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift',
    'SideStore/SideStore/Core/Certificates/OCSPValidator.swift',
    'SideStore/SideStore/Core/Operations/RefreshGroup.swift',
]

def load_dependency(support_root):
    path = support_root / SUPPORT_PATHS[0]
    spec = importlib.util.spec_from_file_location('early_refresh_wire_helpers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.INPUT_PATHS = INPUT_PATHS
    return module

def extract_chain(root, support_root, dependency):
    """Actual production from the variant root; inert/extraction support from candidate only."""
    block = dependency.block
    s = {name: (root / relative).read_text() for name, relative in INPUT_PATHS.items()}
    support = lambda relative: (support_root / relative).read_text()
    host, scheduler = s['host'], s['scheduler']
    for anchor in ['public enum SourceStep:', 'extension CombinedFailure.SourceStep {',
                   'public static func validatedSigningContext(', 'public static func capture(', 'public static func decode(']:
        assert block(host, anchor) == block(s['service'], anchor), anchor
    assert 'self.persistAutomaticRefreshVerification(results: results,' in s['producer']
    assert 'reportStructuredRefreshFailure(error, server: server)' in s['client']
    assert 'IntentError(V3HeadlessPairingFailure.tagIfInvalidPairing(error))' in s['intent']
    assert 'UIPasteboard.general.string = V3DiagnosticCopy.details(visibleMessage: message, technical: diagnostics)' in s['ui']
    swift = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    swift += support(SUPPORT_PATHS[1]) + '\n'
    swift += support(SUPPORT_PATHS[4]).split('struct RefreshFailureBoundaryHarness {', 1)[0] + '\n'
    swift += dependency.pure_model(host) + '\n'
    # Exact current observation/error declarations; parsing is deliberately unreachable
    # in these early-failure fixtures, so no profile bytes or success are fabricated.
    swift += '''struct FixtureProfileCertificate { let serialNumber: String; let data: Data }
struct ALTProvisioningProfile {
    let uuid: UUID; let data: Data; let bundleIdentifier: String; let teamIdentifier: String
    let expirationDate: Date; let certificates: [FixtureProfileCertificate]
    init(data: Data) throws { preconditionFailure("Early failure fixture must not parse provisioning data") }
}
'''
    swift += block(support(SUPPORT_PATHS[6]), 'struct V3RefreshVerification:') + '\n'
    swift += block(support(SUPPORT_PATHS[6]), 'struct V3RefreshSelectionFailure:') + '\n'
    swift += block(support(SUPPORT_PATHS[7]), 'public enum OCSPValidationError:') + '\n'
    steps = s['pipeline_steps']
    swift += '\nprotocol OperationStep: Equatable, Hashable {}\n'
    swift += steps[steps.index('enum PipelineStep:'):steps.index('    fileprivate static let stepMap:')] + '}\n'
    for anchor in ['enum V3RefreshFailureBoundary:', 'func lcRefreshFailureFacts(', 'func lcSafeSigningCause(', 'func lcStructuredSigningFailure(']:
        swift += block(s['pipeline'], anchor) + '\n'
    swift += block(s['app_operation'], 'enum AppOperation:') + '\n'
    swift += block(s['manager'], '    func getMappedError(') + '\n'
    swift += s['operation_error'] + '\n'
    swift += 'extension NSError {\n' + block(s['error_title'], '    var localizedFailure:') + '\n'
    swift += block(s['error_title'], '    func withLocalizedTitle(') + '\n}\n'
    swift += s['wrapped_error'].replace('@objc(ALTWrappedError)\n', '').replace('@objc ', '') + '\n'
    swift += block(host, 'enum V3RefreshTerminalFailurePolicy {') + '\n'
    swift += block(s['service'], 'enum V3HeadlessPairingFailure {') + '\n'
    swift += block(s['manager'], 'enum V3PersistedErrorSanitizer {') + '\n'
    swift += 'final class IntentError: NSError, @unchecked Sendable {\n'
    intent = block(s['intent'], 'class IntentError:')
    swift += block(intent, 'init(_ error: some Error)') + '\n' + block(intent, 'required init?(coder: NSCoder)') + '\n}\n'
    swift += 'final class ManifestProducer {\nlet installedApps: [InstalledApp]\nlet refreshIdentifier: String\ninit(apps: [InstalledApp], runID: String) { installedApps = apps; refreshIdentifier = runID }\nfunc debugLog(_ text: String) {}\nfunc automaticRefreshDefaults() throws -> UserDefaults { V3SharedAppGroup.defaults }\n'
    swift += block(s['producer'], 'private func persistAutomaticRefreshVerification(').replace('private func', 'func', 1) + '\n}\n'
    swift += 'final class SideStoreClient {\n' + block(s['client'], 'func reportRefreshResult(') + '\n'
    swift += block(s['client'], 'func reportStructuredRefreshFailure(') + '\n}\n'
    current = block(host, 'fileprivate func completedRefresh(')
    assert 'V3RefreshTerminalFailurePolicy.preservedFailure(' in current
    swift += 'final class CurrentHandler {\n' + support(SUPPORT_PATHS[2]) + '\n'
    swift += block(host, 'private func finishRefreshContinuation(') + '\n' + current + '\n}\n'
    swift += 'enum FixtureScheduler {\nstatic var defaults: UserDefaults { V3SharedAppGroup.defaults }\nstatic var activeRun: UUID?\nstatic let maximumRunLedgerEntries = 32\n'
    for key in ['runLedgerKey', 'activeRunKey', 'activeManualRequestKey', 'activeManualOriginKey', 'activeManualOriginRunKey', 'expectedRunKey', 'verificationKey', 'currentRunFailureKey', 'healthStateKey', 'lastErrorKey']:
        swift += next(line.strip() for line in scheduler.splitlines() if line.strip().startswith('static let ' + key + ' =')) + '\n'
    for anchor in ['private static func runLedger()', 'private static func saveRunRecord(', 'private static func terminalManifestSummary(', 'private static func endRun(', 'private static func structuredRefreshFailure(', 'private static func markFailed(']:
        swift += block(scheduler, anchor).replace('private static', 'static', 1) + '\n'
    swift += '''static func record(source: String, result: String, detail: String) {}
static func publishRunState(_ state: String, runID: String, requestID: String?, origin: String?) {}
static func notify(title: String, body: String, kind: String, runID: String, requestID: String?, origin: String?) {}
}\n'''
    swift += block(s['ui'], 'enum V3RefreshAllFailureDiagnostics {') + '\n'
    return swift

def verify_baseline(root):
    pins = json.loads((HERE / 'baseline-inputs.json').read_text())
    for item in pins['files']:
        path = root / item['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('Exact pinned baseline input missing or changed: ' + item['path'])
    return pins

EXTRA_INPUTS = {
    'runner': 'SideStore/SideStore/Core/Operations/PipelineRunner.swift',
    'preflight': 'SideStore/SideStore/Core/Operations/PipelineOperations/PreflightChecksOperation.swift',
    'auth': 'SideStore/SideStore/Core/Auth/AuthManager.swift',
    'group': 'SideStore/SideStore/Core/Operations/RefreshGroup.swift',
    'minimuxer': 'SideStore/SideStore/Core/DeviceApi/MinimuxerWrapper.swift',
    'bundle_ids': 'SideStore/Shared/Extensions/Bundle+AltStore.swift',
    'store_app': 'SideStore/AltStore/Core/Model/StoreApp.swift',
}

CASE_NAMES = [
    'readiness_not_started', 'readiness_no_device', 'readiness_no_connection', 'readiness_not_reachable',
    'readiness_no_vpn', 'readiness_invalid_vpn', 'readiness_pairing_not_loaded', 'readiness_invalid_parameters',
    'readiness_unknown_native', 'missing_team_host_filtered', 'missing_team_nonhost',
    'unknown_preflight_error_privacy', 'cancellation_identity', 'url_cancellation_identity', 'existing_pairing_evidence',
    'existing_structured_failure_identity', 'existing_nserror_markers', 'nonrefresh_batch_unchanged',
    'mixed_batch_unchanged', 'current_request_gate', 'current_run_gate', 'success_both_checks_retained',
    'cellular_existing_policy', 'cached_team_existing_policy',
]

def generate_variant(root, support_root, variant, output_root):
    root, output_root = Path(root).resolve(), Path(output_root).resolve()
    dependency = load_dependency(support_root)
    block = dependency.block
    read = lambda relative: (root / relative).read_text()
    ci = support_root / 'LiveContainer/.ci/comprehensive-diagnostics'
    original_prefix = extract_chain(root, support_root, dependency)
    old_harness = (ci / 'refresh_failure_harness.swift').read_text()
    common_assertions = old_harness.split('    static func main() async {', 1)[0]
    common_assertions = common_assertions.replace('@main\nstruct RefreshFailureCases {', 'enum ChainChecks {', 1) + '\n}\n'
    common_assertions = common_assertions.replace(block(common_assertions, '    static func producer('), '')
    # The unused rejection helper has a default closure in its signature. A
    # first-brace extractor would remove only that closure and leave `) async {`.
    # Remove its complete exact span up to the next known declaration instead.
    rejection_anchor = '    static func rejection('
    main_anchor = '    static func main() async {'
    assert old_harness.count(rejection_anchor) == old_harness.count(main_anchor) == 1
    rejection = old_harness[old_harness.index(rejection_anchor):old_harness.index(main_anchor)]
    assert common_assertions.count(rejection) == 1
    common_assertions = common_assertions.replace(rejection, '')
    source = dict((name, read(relative)) for name, relative in EXTRA_INPUTS.items())
    manager = read(dependency.INPUT_PATHS['manager'])
    producer = read(dependency.INPUT_PATHS['producer'])
    app_operation = read(dependency.INPUT_PATHS['app_operation'])
    prefix = original_prefix
    # Only in-memory shells are expanded; extracted production bodies are exact.
    prefix = prefix.replace('protocol AppProtocol { var name: String { get } }',
        'protocol AppProtocol { var name: String { get }; var bundleIdentifier: String { get } }')
    prefix = prefix.replace('class FixtureManagedObjectContext {', 'class FixtureManagedObjectContext: NSObject {')
    prefix = prefix.replace('enum MinimuxerError: Error { case invalidPairing(Int, String) }', '')
    prefix = prefix.replace(block(prefix, 'enum AppOperation:'), block(app_operation, 'enum AppOperation:'))
    prefix = prefix.replace('final class ManifestProducer {',
        'final class ManifestProducer {\nlet refreshGroupLock = NSLock()\nvar activeRefreshGroup: RefreshGroup?\nfunc setProgress(_ value: Int) {}\n')
    api = (support_root / SUPPORT_PATHS[5]).read_text()
    # Exact current public observation envelope; IO remains an inert double.
    api_types = '\n'.join(block(api, anchor) for anchor in [
        'public enum DeviceConnectionMode:', 'public enum MinimuxerOwnedReadinessTransient:',
        'public struct MinimuxerOwnedReadinessObservation'])
    swift = prefix + '\n' + api_types + '\n' + (HERE / 'early_doubles.swift').read_text()
    swift += '\nextension String {\n' + block(source['bundle_ids'], '    var isAltStoreAppID:') + '\n}\n'
    swift += '\nextension StoreApp {\n' + block(source['store_app'], '    static var altstoreAppID:') + '\n}\n'
    swift += '\n' + block(source['minimuxer'], 'public func isMinimuxerReady()')
    swift += '\nextension MinimuxerError {\n' + block(source['minimuxer'], '    var asOperationError:') + '\n}\n'
    swift += '\nfinal class AuthManager {\nstatic let shared = AuthManager()\nvar team: ALTTeam?\n'
    swift += block(source['auth'], '    public func getAuthenticatedTeam()') + '\n'
    swift += block(source['auth'], '    private func resolveActiveTeam()') + '\n}\n'
    swift += '\n' + block(source['preflight'], 'final class PreflightChecksOperation:') + '\n'
    if variant == 'candidate':
        swift += '\n' + block(source['group'], 'struct V3OwnedTransportObservation {') + '\n'
        swift += '\n' + block(source['runner'], 'private struct V3TransportObservationConfiguration:') + '\n'
    swift += '\n' + block(source['group'], 'final class RefreshGroup:') + '\n'
    if variant == 'candidate':
        swift += '\n' + block(source['runner'], 'enum V3RefreshEarlyFailureBoundary {') + '\n'
        for anchor in ['final class V3RefreshReadinessLifetime:', 'enum V3OwnedRefreshReadinessWait {']:
            swift += '\n' + block(source['runner'], anchor) + '\n'
    swift += '\nfinal class PipelineRunner {\nlet progress = FixtureProgressRegistry()\nlet context = FixtureRunnerContext()\n'
    swift += block(source['runner'], '    func perform(_ operations:') + '\n'
    if variant == 'candidate':
        swift += block(source['runner'], '    private func performUsingAdmittedRoute(') + '\n'
    swift += '''func performOperation(for operation: AppOperation, handler: PipelineExecutionHandler, group: RefreshGroup, operationsCount: Int = 1, refreshAdmission: (() throws -> Void)? = nil, readProfiles: (() async throws -> [Data])? = nil) async throws {
try refreshAdmission?()
// The only mutation boundary is deliberately inert. Early-failure tests
// assert zero visits; controls assert it is reached only after both checks.
FixtureVisits.mutation += 1
group.set(.success(operation.app as! InstalledApp), forAppWithBundleIdentifier: operation.bundleIdentifier)
}
}\n'''
    swift += '\nfinal class AppManager {\nstatic let shared = AppManager()\nvar pipelineRunner = PipelineRunner()\n'
    swift += '''func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler { PipelineExecutionHandler() }
func getValidDbContext(_ context: NSManagedObjectContext?) -> NSManagedObjectContext { context ?? NSManagedObjectContext() }
'''
    swift += block(manager, '    func refresh(_ installedApps:') + '\n}\n'
    completion = block(producer, '            group.completionHandler = { (results) in')
    swift += '''extension ManifestProducer {
func refreshThroughActualManager(_ apps: [InstalledApp]) async throws -> [String: Result<InstalledApp, Error>] {
    let group = RefreshGroup(dbContext: NSManagedObjectContext())
    let results: [String: Result<InstalledApp, Error>] = try await withCheckedThrowingContinuation { continuation in
        // Keep the extracted callback exact. A callback is not task completion:
        // the baseline runner can still own its transport lease afterward.
'''
    if variant == 'candidate':
        # The callback closes over the run captured before queueing in production.
        # Bind the actual group to that same immutable fixture run, not a fabricated success.
        swift = swift.replace('    let group = RefreshGroup(dbContext: NSManagedObjectContext())\n',
            '    let runID = refreshIdentifier\n    let group = RefreshGroup(dbContext: NSManagedObjectContext())\n    group.bindTransportObservation(to: runID)\n', 1)
    swift += completion + '\n'
    swift += '''            _ = AppManager.shared.refresh(apps, presentingViewController: nil, group: group)
    }
    // The continuation body returns only after refresh synchronously assigns
    // this same group's task, even if its detached callback resumes early.
    guard let activeTask = group.activeTask else { preconditionFailure("fixture refresh task was not assigned") }
    if let gate = minimuxer.core.releaseGate { await gate.callbackConsumed() }
    await activeTask.value
    return results
}
}\n'''
    swift += common_assertions + '\n'
    swift += 'let fixtureCandidate = ' + ('true' if variant == 'candidate' else 'false') + '\n'
    swift += (HERE / 'early_cases.swift').read_text()
    output = output_root / variant
    output.mkdir(parents=True, exist_ok=True)
    (output / 'early-refresh.swift').write_text(swift)
    paths = set(dependency.INPUT_PATHS.values()) | set(EXTRA_INPUTS.values())
    inputs = {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest() for relative in sorted(paths)}
    support_inputs = {relative: hashlib.sha256((support_root / relative).read_bytes()).hexdigest() for relative in SUPPORT_PATHS}
    fixture_inputs = {'LiveContainer/.ci/early-refresh-boundaries/' + name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                      for name in ['generate_regression.py', 'early_doubles.swift', 'early_cases.swift',
                                   'baseline-inputs.json', 'test_contract.py', 'README.md']}
    receipt = {'schema': 'early-refresh-source-extraction-v1', 'variant': variant,
               'expected_case_names': CASE_NAMES, 'expected_case_count': len(CASE_NAMES),
               'status': 'GENERATED_NOT_COMPILED_NOT_RUN', 'swift_executed': False,
               'native_provider_executed': False, 'network_executed': False,
               'inputs_sha256': inputs, 'support_inputs_sha256': support_inputs, 'fixture_inputs_sha256': fixture_inputs,
               'input_root': str(root), 'support_root': str(support_root), 'generated_sha256': hashlib.sha256(swift.encode()).hexdigest(),
               'actual_functions': ['AppManager.refresh', 'PipelineRunner.perform', 'PreflightChecksOperation.execute',
                 'AuthManager.getAuthenticatedTeam', 'AuthManager.resolveActiveTeam', 'RefreshGroup',
                 'isMinimuxerReady', 'MinimuxerError.asOperationError', 'BackgroundRefreshAppsOperation completion closure',
                 'persistAutomaticRefreshVerification', 'IntentError', 'reportStructuredRefreshFailure',
                 'completedRefresh', 'markFailed', 'V3RefreshAllFailureDiagnostics.text'],
               'admitted_route_body_extracted': variant == 'candidate',
               'inert_dependencies': ['remote identity lease admission; real implementation covered by identity suite', 'native core readiness result', 'DB activeTeam/transaction', 'UIKit lifecycle',
                 'app models', 'per-app mutation after both checks', 'memory-only defaults and callback transport'],
               'limits': ['Synthetic fixture; not device root-cause evidence.',
                 'Exact callback result is followed by awaiting the same group activeTask, including transport cleanup.',
                 'No source publication or provider, native-library, device, or auth execution.',
                 'Generation is not Swift compilation or execution. Runtime assertions require approved CI execution.']}
    (output / 'sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt

def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-root', type=Path, required=True, help='Integrated candidate root containing LiveContainer/ and SideStore/')
    p.add_argument('--baseline-root', type=Path, required=True, help='Exact pinned baseline root containing LiveContainer/ and SideStore/')
    p.add_argument('--output', type=Path, required=True, help='Isolated output directory')
    p.add_argument('--variants', choices=['baseline', 'candidate'], nargs='+', default=['baseline', 'candidate'])
    return p

def generate(candidate_root, baseline_root, output, variants=('baseline', 'candidate')):
    baseline_root, candidate_root, output = map(lambda p: Path(p).resolve(), (baseline_root, candidate_root, output))
    verify_baseline(baseline_root)
    receipts = {}
    for variant in variants:
        root = baseline_root if variant == 'baseline' else candidate_root
        receipts[variant] = generate_variant(root, candidate_root, variant, output)
    return receipts

def main():
    args = parser().parse_args()
    generate(args.candidate_root, args.baseline_root, args.output, args.variants)
    print('EARLY_REFRESH_FIXTURES_GENERATED_NOT_COMPILED_NOT_RUN')

if __name__ == '__main__': main()
