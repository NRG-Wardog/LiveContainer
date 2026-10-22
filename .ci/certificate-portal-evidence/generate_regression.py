#!/usr/bin/env python3
"""Generate bounded actual-source certificate portal JSON -> IPC -> Copy fixtures.

Generation is not compilation/execution. The consolidated gate compiles and runs each variant.
Only the dispatcher, account/model state, and row formatting are inert doubles.
"""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = 'LiveContainer/.ci/certificate-portal-evidence'
SIGN = 'SideStore/Dependencies/SideSign'
INPUT_PATHS = {
    'service': 'SideStore/AltStore/AppDelegate.swift',
    'host': 'LiveContainer/SideStoreSupport/SideStore.swift',
    'pipeline': 'SideStore/SideStore/Core/Operations/PipelineExecutor.swift',
    'proxy': 'SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift',
    'operation_error': 'SideStore/SideStore/Core/Operations/Errors/OperationError.swift',
    'wrapped_error': 'SideStore/Shared/Errors/ALTWrappedError.swift',
    'portal': SIGN + '/Sources/DeveloperPortal/DeveloperPortalAPI.swift',
    'certificates': SIGN + '/Sources/DeveloperPortal/Certificates.swift',
    'responses': SIGN + '/Sources/Models/DeveloperPortalResponses.swift',
    'certificate_model': SIGN + '/Sources/Models/X509Certificate.swift',
    'errors': SIGN + '/Sources/Models/Errors.swift',
    'constants': SIGN + '/Sources/Constants.swift',
    'data_helpers': SIGN + '/Sources/SideSign.swift',
}
SUPPORT_PATHS = {
    'wire_generator': 'LiveContainer/.ci/comprehensive-diagnostics/generate_wire_fixture.py',
    'generator': PACKAGE + '/generate_regression.py',
    'doubles': PACKAGE + '/portal_doubles.swift',
    'service_cases': PACKAGE + '/service_cases.swift',
    'host_cases': PACKAGE + '/host_cases.swift',
}
CASE_NAMES = sorted(['known_entity_422', 'known_forbidden_403', 'unknown_code_redacted',
    'plausible_unknown_code_redacted', 'missing_code', 'no_http_response', 'first_error_only',
    'numeric_result_preserved', 'empty_body_preserved', 'invalid_json_redacted', 'paid_endpoint',
    'success_unchanged', 'network_primary_preserved', 'parallel_0', 'parallel_1',
    'remoteIdentityInvalidRecord', 'remoteIdentityStorageUnverified',
    'remoteIdentityStateChanged', 'remoteIdentityManualSignInRequired'])
PRELUDE = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read(root, relative):
    path = root / relative
    assert not root.is_symlink() and path.is_file()
    current = root
    for component in Path(relative).parts:
        current /= component
        assert not current.is_symlink(), relative
    return path.read_bytes()


def validate_service_dependencies(swift, diagnostic_policy, block):
    assert swift.count('enum V3AuthFailureDiagnosticsPolicy {') == 1 and diagnostic_policy in swift, \
        'Actual authentication diagnostic policy missing from service closure'
    assert swift.count('struct FixtureRemoteAuthenticationContext {') == 1, \
        'Inert remote context interface missing from service closure'
    context = block(swift, 'struct FixtureRemoteAuthenticationContext {')
    assert 'let session = FakeDispatcher()' in context and 'func checkActive() throws {}' in context and \
        'URLSession' not in context, 'Inert remote context interface missing from service closure'
    assert swift.count('enum ILoaderRemoteAuthentication {') == 1, \
        'Nil-only remote route missing from service closure'
    route = block(swift, 'enum ILoaderRemoteAuthentication {')
    assert 'static var current: FixtureRemoteAuthenticationContext? { nil }' in route, \
        'Nil-only remote route missing from service closure'


def generate_variant(root, support_root, output, variant, wire):
    block = wire.block
    source_bytes = {key: read(root, path) for key, path in INPUT_PATHS.items()}
    support_bytes = {key: read(support_root, path) for key, path in SUPPORT_PATHS.items()}
    sources = {key: raw.decode() for key, raw in {**source_bytes, **support_bytes}.items()}
    service, host = sources['service'], sources['host']
    portal = block(service, '    static func portalCertificates()')
    for anchor in ['public enum SourceStep:', 'public static func validatedSigningContext(',
                   'public static func capture(', 'public static func decode(', 'public enum V3DiagnosticCopy {']:
        assert block(host, anchor) == block(service, anchor), anchor
    contract = block(host, 'enum V3WireContract {')
    limit = re.findall(r'    static let responseLimit = [0-9_]+', contract)
    operations = re.search(r'    static let operations: Set<String> = \[.*?\]', contract, re.S)
    assert len(limit) == 1 and operations
    primitive = 'enum V3WireContract {\n' + limit[0] + '\n' + operations.group(0) + '\n'
    primitive += block(contract, 'static func strictBool(') + '\n' + block(contract, 'static func strictInt(') + '\n}\n'
    shared = PRELUDE + wire.pure_model(service) + '\n' + primitive
    common = shared + sources['doubles'] + '\n'
    for anchor in ['public enum DeveloperPortalError:', 'public struct AuthenticationResponseContext:', 'public enum ServerError:']:
        common += block(sources['errors'], anchor) + '\n'
    common += 'enum Constants {\nstatic let defaultAccountRepairMessage = "Synthetic account repair message"\n'
    common += block(sources['constants'], 'public enum DeveloperServices {') + '\n'
    common += block(block(sources['constants'], 'public enum Constants {'), '\n    public enum URLs {') + '\n}\n'
    for anchor in ['public enum DeveloperPortalResultCodes {', 'public enum HTTPStatusCodes {']:
        common += block(sources['constants'], anchor) + '\n'
    common += 'extension Data {\n' + block(sources['data_helpers'], 'func hexEncodedString()') + '\n}\n'
    common += 'extension X509Certificate {\n' + block(sources['certificate_model'], '    enum CertificateEndpoint:') + '\n}\n'
    for anchor in ['struct EmptyResponse:', 'struct DeveloperPortalStatusResponse:',
                   'struct CertificatesResponseDeveloperServices2:', 'struct CertificatesResponseDeveloperPortal:']:
        common += block(sources['responses'], anchor) + '\n'
    common += block(sources['portal'], 'public enum SideSignPortalDiagnostics {') + '\n'
    common += 'extension DeveloperPortal {\n' + block(sources['portal'], '    func sendServicesRequest<T: Decodable>') + '\n'
    common += block(sources['certificates'], '    func fetchCertificates(for team: Team, session: Session)') + '\n}\n'
    common += 'extension DeveloperPortalProxy {\n' + block(sources['proxy'], '    private func awaitBound<T>') + '\n'
    common += block(sources['proxy'], '    public func fetchCertificates(team: ALTTeam? = nil)') + '\n}\n'
    for anchor in ['private final class LCSigningHTTPObservation:', 'func lcSafeSigningCause(',
                   'func lcStructuredSigningFailure(', 'func lcPortalSigningRequest<T>']:
        common += block(sources['pipeline'], anchor) + '\n'
    common += block(sources['operation_error'], 'public enum OperationError:') + '\n'
    common += sources['wrapped_error'].replace('@objc(ALTWrappedError)\n', '').replace('@objc ', '') + '\n'
    common += block(service, 'enum V3HeadlessPairingFailure {') + '\n'
    for anchor in ['enum V3AuthFailureDiagnosticsPolicy {', 'enum V3ResponseClassifier {',
                   'struct V3EncodedServiceResponse {', 'enum V3ResponseEncoder {']:
        common += block(service, anchor) + '\n'
    # Extract exact selected dispatcher branch and generic failure-capture leaf.
    case_start = service.index('        case "certPortalList":')
    case_end = service.index('        case "certRevoke":', case_start)
    case = service[case_start:case_end]
    capture = '''                    response["failure"] = CombinedFailure.capture(
                        V3HeadlessPairingFailure.tagIfInvalidPairing(error),
                        operation: operation, stage: stage, id: id).wire'''
    assert service.count(capture) == 1
    dispatcher = '@MainActor final class FixtureCommandDispatcher {\n'
    dispatcher += block(service, '    private func accountScopedRead(') + '\n'
    dispatcher += 'func run(_ operation: String) async throws -> [String: Any] { switch operation {\n' + case
    dispatcher += 'default: preconditionFailure("Only certPortalList is in fixture scope")\n} }\n'
    dispatcher += '''func reply(id: String) async -> Data {
let operation = "certPortalList"
let stage = CombinedFailure.Stage.signing
var response: [String: Any] = ["version": 1, "id": id]
do { response["result"] = try await run(operation); response["ok"] = true }
catch {
response["error"] = error is CancellationError ? "cancelled" : "operationFailed"
'''
    dispatcher += capture + '\n}\nreturn V3ResponseEncoder.encode(response, operation: operation, limit: V3WireContract.responseLimit)\n}\n}\n'
    swift = common + '\n@MainActor enum V3BackendCommands {\n'
    swift += block(service, '    enum V3CertificatePortalReadBoundary {') + '\n' + portal + '\n'
    swift += 'static func certificateRow(_ certificate: X509Certificate, activeSerial: String?) -> [String: Any] { ["active": certificate.serialNumber == activeSerial] }\n}\n'
    swift += dispatcher + '\nlet fixtureCandidate = ' + ('true' if variant == 'candidate' else 'false') + '\n'
    swift += sources['service_cases']
    validate_service_dependencies(swift, block(service, 'enum V3AuthFailureDiagnosticsPolicy {'), block)
    target = output
    target.mkdir(parents=True, exist_ok=True)
    (target / 'service.swift').write_text(swift)
    host_swift = PRELUDE + wire.pure_model(host) + '\n' + primitive
    host_swift += block(host, 'enum V3CatalogRequestContext {') + '\n' + sources['host_cases']
    output.mkdir(parents=True, exist_ok=True)
    (target / 'host.swift').write_text(host_swift)
    receipt = {
        'schema': 'certificate-portal-evidence-sources-v2', 'variant': variant,
        'status': 'GENERATED_NOT_COMPILED_NOT_RUN', 'swift_executed': False,
        'network_executed': False, 'native_provider_executed': False,
        'expected_case_names': CASE_NAMES, 'expected_case_count': len(CASE_NAMES),
        'inputs_sha256': {INPUT_PATHS[key]: digest(raw) for key, raw in source_bytes.items()},
        'support_inputs_sha256': {SUPPORT_PATHS[key]: digest(raw) for key, raw in support_bytes.items()},
        'generated_sha256': {name: digest((target / name).read_bytes()) for name in ('service.swift', 'host.swift')},
        'actual_source': ['SideSign.sendServicesRequest full body and JSON status models',
            'SideSign.fetchCertificates full body and endpoint constants', 'DeveloperPortalProxy.fetchCertificates and awaitBound bodies',
            'V3BackendCommands.portalCertificates and V3CertificatePortalReadBoundary',
            'certPortalList dispatcher branch and accountScopedRead full body',
            'generic service CombinedFailure.capture leaf', 'LCSigningHTTPObservation and lcPortalSigningRequest',
            'V3ResponseEncoder binary plist serialization', 'host V3CatalogRequestContext.classifyReply',
            'CombinedFailure capture, decode, technicalDetails and V3DiagnosticCopy.details'],
        'inert_boundaries': ['fake dispatcher returns invented JSON/HTTP/error values, never URLSession',
            'account/team/session state, generation guards, certificate storage and X509 parsing model shells',
            'remote identity admission and task-local context shells; actual bodies covered by remote-identity-reuse suite',
            'success certificate row formatter, command scheduler and generic reply assembly'],
    }
    (target / 'sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def generate(candidate, baseline, output):
    generator = candidate / SUPPORT_PATHS['wire_generator']
    spec = importlib.util.spec_from_file_location('portal_wire_fixture', generator)
    wire = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wire)
    before = wire.block(read(baseline, INPUT_PATHS['service']).decode(), '    static func portalCertificates()')
    after = wire.block(read(candidate, INPUT_PATHS['service']).decode(), '    static func portalCertificates()')
    needle = '            try await DeveloperPortalProxy.shared.fetchCertificates(team: team)'
    replacement = '            // Observe only finite portal response evidence for this read command.\n            // Raw provider detail/title and certificate identity never enter IPC.\n            try await lcPortalSigningRequest(sourceStep: "fetchCertificate", facts: [:]) {\n                try await DeveloperPortalProxy.shared.fetchCertificates(team: team)\n            }'
    assert before.count(needle) == 1 and after == before.replace(needle, replacement), 'Portal read method diff changed'
    results = {}
    for variant, root in [('baseline', baseline), ('candidate', candidate)]:
        results[variant] = generate_variant(root, candidate, output / variant, variant, wire)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    generate(args.candidate_root, args.baseline_root, args.output)
    print('PORTAL_SOURCE_VARIANTS_GENERATED_NOT_COMPILED_NOT_RUN')


if __name__ == '__main__':
    main()
