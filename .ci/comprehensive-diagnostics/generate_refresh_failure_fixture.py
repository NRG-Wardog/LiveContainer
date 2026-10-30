#!/usr/bin/env python3
"""Extract the actual refresh manifest -> AppIntent -> callback -> ledger -> Copy path.
Only app data, OS transport/notifications and shared-defaults IO are doubled.
No app, private AppIntents runner, device, provider, credential or native vendor library runs.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

CASE_NAMES = ['delivered_generic_wrapper_reproduced', 'actual_manifest_callback_ledger_copy', 'copy_kind_omission_reproduced', 'copy_structured_snapshot_preserved', 'source_certificateSelection', 'source_refreshMetadataCache', 'source_provisioningProfileInstallation', 'source_refreshRecordUpdate', 'source_refreshApplication', 'certificate_authenticate', 'certificate_accountLookup', 'certificate_fetchCertificate', 'finite_boundary_invariants', 'invalid_refresh_failure_kind', 'missing_payload', 'invalid_plist', 'oversized_payload', 'stale_manifest', 'incomplete_manifest', 'duplicate_target', 'malformed_boolean', 'wrong_failure_run', 'wrong_failure_operation', 'invalid_failure', 'missing_failure_no_raw_fallback', 'contradictory_handoff', 'wrong_active_run', 'wrong_expected_run', 'wrong_active_request', 'missing_ledger', 'terminal_ledger', 'concrete_transport_retained', 'untyped_outer_retained', 'wrong_callback_run_ignored', 'wrong_launch_ignored', 'secret_canary_and_copy_identity']
SUCCESS_MARKER = "PASS refresh_failure_actual_source_chain"

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
    'group': 'SideStore/SideStore/Core/Operations/RefreshGroup.swift',
    'ocsp': 'SideStore/SideStore/Core/Certificates/OCSPValidator.swift',
    'refresh_operation': 'SideStore/SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift',
    'operation_error': 'SideStore/SideStore/Core/Operations/Errors/OperationError.swift',
    'error_title': 'SideStore/Shared/Extensions/NSError+AltStore.swift',
    'wrapped_error': 'SideStore/Shared/Errors/ALTWrappedError.swift',
    'refresh_contract': 'SideStore/tests/refresh_failure/test_contract.py',
    'refresh_boundary_assertions': 'SideStore/tests/refresh_failure/boundary_assertions.swift',
    'refresh_boundary_cases': 'SideStore/tests/refresh_failure/boundary_cases.swift',
    'certificate_boundary_cases': 'SideStore/tests/refresh_failure/certificate_cases.swift',
    'service_boundary_doubles': 'SideStore/tests/refresh_failure/pipeline_harness.swift',
}
FIXTURE_FILES = ['generate_refresh_failure_fixture.py', 'generate_wire_fixture.py',
    'refresh_completed_baseline.swift', 'refresh_copy_baseline.swift', 'refresh_failure_doubles.swift',
    'refresh_handler_doubles.swift', 'refresh_failure_harness.swift', 'test_refresh_failure_contract.py']

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wire_fixture', HERE/'generate_wire_fixture.py')
wire_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire_fixture)
block = wire_fixture.block


def generate(root, output):
    paths = {name: root/path for name,path in INPUT_PATHS.items()}
    s = {name: path.read_text() for name, path in paths.items()}
    host, scheduler = s['host'], s['scheduler']
    boundary_spec = importlib.util.spec_from_file_location('refresh_boundary_contract', paths['refresh_contract'])
    boundary_module = importlib.util.module_from_spec(boundary_spec)
    boundary_spec.loader.exec_module(boundary_module)
    boundary_source, boundary_paths = boundary_module.generate_source(root/'SideStore')
    assert set(boundary_paths.values()).issubset(set(paths.values())), 'Unreceipted service source dependency'

    before = (HERE/'refresh_completed_baseline.swift').read_text().rstrip()
    assert hashlib.sha256(before.encode()).hexdigest() == 'f730e5fd206bfbc38dea6d452d2b79d3bf8fbc2ffb05bb970d1e495607275a46', 'Delivered callback negative control changed'
    before_copy = (HERE/'refresh_copy_baseline.swift').read_text().rstrip()
    assert hashlib.sha256(before_copy.encode()).hexdigest() == 'ee1156e3c033017895aabb3c946088061e1e2d977c178d509dbbdda55cfc6002', 'First CI Copy renderer negative control changed'
    current = block(host, 'fileprivate func completedRefresh(')
    assert 'V3RefreshTerminalFailurePolicy.preservedFailure(' in current
    assert 'defaults.set(preserved.manifest' in current
    assert 'launchID == id, refreshContinuation != nil, refreshRunID == runID' in current
    # Pin the real integration call sites, not just isolated helper behavior.
    assert 'self.persistAutomaticRefreshVerification(results: results,' in s['producer']
    assert 'reportStructuredRefreshFailure(error, server: server)' in s['client']
    assert 'throw intentError' in s['intent'] and 'IntentError(V3HeadlessPairingFailure.tagIfInvalidPairing(error))' in s['intent']
    assert 'let failure = structuredRefreshFailure(error, runID: runID.uuidString)' in scheduler
    assert 'failure: failure, message: safeMessage)' in scheduler
    assert 'UIPasteboard.general.string = V3DiagnosticCopy.details(visibleMessage: message, technical: diagnostics)' in s['ui']
    # The producer and consumer must agree on the exact finite model.
    for anchor in ['public enum SourceStep:', 'extension CombinedFailure.SourceStep {', 'public static func validatedSigningContext(', 'public static func capture(', 'public static func decode(']:
        assert block(host, anchor) == block(s['service'], anchor), anchor
    prelude = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    swift = prelude + (HERE/'refresh_failure_doubles.swift').read_text() + '\n'
    swift += s['service_boundary_doubles'].split('struct RefreshFailureBoundaryHarness {', 1)[0] + '\n'
    swift += wire_fixture.pure_model(host) + '\n'
    swift += boundary_source + '\n'
    # Exact profile-evidence implementation plus inert, forbidden parsing boundary.
    swift += '''struct FixtureProfileCertificate { let serialNumber: String; let data: Data }
struct ALTProvisioningProfile {
    let uuid: UUID; let data: Data; let bundleIdentifier: String; let teamIdentifier: String
    let expirationDate: Date; let certificates: [FixtureProfileCertificate]
    init(data: Data) throws { preconditionFailure("Failure fixture must not parse provisioning data") }
}
'''
    swift += block(s['refresh_operation'], 'struct V3RefreshVerification:') + '\n'
    swift += block(s['ocsp'], 'public enum OCSPValidationError:') + '\n'
    swift += block(s['group'], 'struct V3OwnedTransportObservation {') + '\n'
    swift += 'final class RefreshGroup {\nprivate let lock = NSLock()\nprivate var verificationByApp: [String: V3RefreshVerification] = [:]\n'
    swift += 'private var transportObservation = V3OwnedTransportObservation()\n'
    for anchor in ['    func bindTransportObservation(', '    func recordTransportReady(', '    func transportObservationWire(']:
        swift += block(s['group'], anchor) + '\n'
    for anchor in ['    func setVerification(', '    func verification(for ', '    func verificationSnapshot()']:
        swift += block(s['group'], anchor) + '\n'
    swift += '}\n'
    swift += block(host, 'enum V3RefreshTerminalFailurePolicy {') + '\n'
    swift += block(s['service'], 'enum V3HeadlessPairingFailure {') + '\n'
    swift += block(s['manager'], 'enum V3PersistedErrorSanitizer {') + '\n'
    swift += 'final class IntentError: NSError, @unchecked Sendable {\n'
    intent_class = block(s['intent'], 'class IntentError:')
    swift += block(intent_class, 'init(_ error: some Error)') + '\n'
    swift += block(intent_class, 'required init?(coder: NSCoder)') + '\n}\n'
    swift += 'final class ManifestProducer {\nlet installedApps: [InstalledApp]\nlet refreshIdentifier: String\ninit(apps: [InstalledApp], runID: String) { installedApps = apps; refreshIdentifier = runID }\nfunc debugLog(_ text: String) {}\nfunc automaticRefreshDefaults() throws -> UserDefaults { V3SharedAppGroup.defaults }\n'
    swift += block(s['producer'], 'private func persistAutomaticRefreshVerification(').replace('private func', 'func', 1) + '\n}\n'
    swift += 'final class SideStoreClient {\n' + block(s['client'], 'func reportRefreshResult(') + '\n'
    swift += block(s['client'], 'func reportStructuredRefreshFailure(') + '\n}\n'
    for name, callback in [('CurrentHandler', current), ('DeliveredHandler', before)]:
        swift += 'final class '+name+' {\n' + (HERE/'refresh_handler_doubles.swift').read_text() + '\n'
        swift += block(host, 'private func finishRefreshContinuation(') + '\n' + callback + '\n}\n'
    swift += 'enum FixtureScheduler {\nstatic var defaults: UserDefaults { V3SharedAppGroup.defaults }\nstatic var activeRun: UUID?\nstatic let maximumRunLedgerEntries = 32\n'
    for key in ['runLedgerKey', 'activeRunKey', 'activeManualRequestKey', 'activeManualOriginKey', 'activeManualOriginRunKey', 'expectedRunKey', 'verificationKey', 'currentRunFailureKey', 'healthStateKey', 'lastErrorKey']:
        line = next(line.strip() for line in scheduler.splitlines() if line.strip().startswith('static let '+key+' ='))
        swift += line + '\n'
    for anchor in ['private static func runLedger()', 'private static func saveRunRecord(', 'private static func terminalManifestSummary(', 'private static func endRun(', 'private static func structuredRefreshFailure(', 'private static func markFailed(']:
        swift += block(scheduler, anchor).replace('private static', 'static', 1) + '\n'
    swift += '''static func record(source: String, result: String, detail: String) {}
static func publishRunState(_ state: String, runID: String, requestID: String?, origin: String?) {}
static func notify(title: String, body: String, kind: String, runID: String, requestID: String?, origin: String?) {}
}\n'''
    swift += before_copy.replace('enum V3RefreshAllFailureDiagnostics {', 'enum BeforeKindRefreshDiagnostics {', 1) + '\n'
    swift += block(s['ui'], 'enum V3RefreshAllFailureDiagnostics {') + '\n'
    swift += (HERE/'refresh_failure_harness.swift').read_text()
    output.mkdir(parents=True, exist_ok=True)
    (output/'refresh-failure.swift').write_text(swift)
    inputs = dict(paths)
    inputs.update({name: HERE/name for name in FIXTURE_FILES})
    receipt = {'schema':'refresh-failure-sources-v1', 'case_names':CASE_NAMES, 'status':'generated_not_compiled', 'native_provider_executed':False, 'network_executed':False, 'swift_executed':False, 'inputs_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in inputs.items()},
               'generated_sha256':hashlib.sha256(swift.encode()).hexdigest(),
               'boundaries':['actual finite refresh boundary annotations and native OperationError classifier','actual AppManager mapper and NSError localized-title wrapper','actual certificate portal read routes with inert provider calls','actual manifest producer','actual IntentError sanitizer constructor','actual service callback plist export','delivered and current completion callback','actual terminal ledger persistence and compaction','first CI and current refresh Copy Diagnostics renderers'],
               'limits':['Synthetic finite errors and in-memory app/defaults/transport boundaries only. No private runner, device, provider, native library or credential execution.','Generation is not Swift compilation or execution.']}
    (output/'sources.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run',action='store_true')
    args=p.parse_args()
    receipt=generate(args.sources,args.output)
    if args.run:
        compiler=shutil.which('swiftc')
        if not compiler: raise SystemExit('Swift unavailable: generated, compile and execution NOT RUN')
        subprocess.run([compiler,'-swift-version','5','-parse-as-library',str(args.output/'refresh-failure.swift'),'-o',str(args.output/'refresh-failure')],check=True)
        subprocess.run([str(args.output/'refresh-failure'), str(args.output/'cases.json')],check=True)
        receipt['status']='actual_source_fake_boundaries_passed'
        receipt['swift_executed']=True
        (args.output/'sources.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('REFRESH_FAILURE_FIXTURE_EXECUTED' if args.run else 'REFRESH_FAILURE_FIXTURE_GENERATED_NOT_COMPILED')

if __name__ == '__main__': main()
