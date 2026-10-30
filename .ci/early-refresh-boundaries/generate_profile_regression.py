#!/usr/bin/env python3
"""Add-on to the existing early-refresh fixture. Source extraction only; never runs Swift."""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
EARLY_GENERATOR = 'LiveContainer/.ci/early-refresh-boundaries/generate_regression.py'
EARLY_DOUBLES = 'LiveContainer/.ci/early-refresh-boundaries/early_doubles.swift'
CASE_NAMES = ['missingTargetAppBundle', 'unknownTeamType', 'unresolvedAppGroupPlaceholder',
    'missingProgressWeight', 'invalidProgressReuse', 'missingPipelineStepMapping'] + [
    'unknown_local_' + str(i) for i in range(4)] + ['wrong_error_type', 'wrong_step', 'nonrefresh_scope'] + [
    'optional_wire_primary_preserved_' + str(i) for i in range(4)] + [
    'optional_wrong_scope_' + str(i) for i in range(3)] + ['vpn_noVPN', 'vpn_invalidVPN'] + [
    'vpn_wrong_scope_' + str(i) for i in range(3)]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def generate(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    early = load(root / EARLY_GENERATOR, 'profile_early')
    dependency = early.load_dependency(root); block = dependency.block
    swift = early.extract_chain(root, root, dependency)
    # Only the evidence storage surface is required by the real manifest producer.
    # Its methods are extracted verbatim; no synthetic acknowledged result exists.
    group_source = (root / early.SUPPORT_PATHS[8]).read_text()
    swift += block(group_source, 'struct V3OwnedTransportObservation {') + '\n'
    swift += 'final class RefreshGroup {\nprivate let lock = NSLock()\nprivate var verificationByApp: [String: V3RefreshVerification] = [:]\n'
    swift += 'private var transportObservation = V3OwnedTransportObservation()\n'
    for anchor in ['    func bindTransportObservation(', '    func recordTransportReady(', '    func transportObservationWire(']:
        swift += block(group_source, anchor) + '\n'
    for anchor in ['    func setVerification(', '    func verification(for ', '    func verificationSnapshot()']:
        swift += block(group_source, anchor) + '\n'
    swift += '}\n'
    # extract_chain includes the full production AppOperation declaration. Match
    # the existing early fixture's inert interfaces without importing its unused
    # readiness, provider, database, or mutation shells.
    old_protocol = 'protocol AppProtocol { var name: String { get } }'
    complete_protocol = 'protocol AppProtocol { var name: String { get }; var bundleIdentifier: String { get } }'
    assert swift.count(old_protocol) == 1
    swift = swift.replace(old_protocol, complete_protocol, 1)
    early_doubles = (root / EARLY_DOUBLES).read_text()
    app_operation_support = [block(early_doubles, anchor) for anchor in
        ['func logOperationSummary(', 'enum LoggedError {']]
    for declaration in app_operation_support:
        assert declaration not in swift
        swift += '\n' + declaration + '\n'
    # Expand only the inert portal enum so the exact outer catch can type-check.
    needle = 'case maximumAppIDLimitReached, provisioningProfileDoesNotExist, certificateDoesNotExist'
    assert swift.count(needle) == 1
    swift = swift.replace(needle, needle + '\n    case incorrectCredentials, appSpecificPasswordRequired, requiresTwoFactorAuthentication, incorrectVerificationCode, authenticationHandshakeFailed, invalidAnisetteData, tooManyAttempts, accountRepairRequired, invalid2FAResponse')
    pipeline = (root / early.INPUT_PATHS['pipeline']).read_text()
    boundary = block(block(pipeline, '    private func executeStep('), '        } catch {')
    swift += '''\nstruct FixtureSigningBundle { let appExtensions: [Int] = [] }
struct FixtureSigningCertificate { let serialNumber = "UNREACHABLE" }
struct FixtureSigningContext {
    let targetAppBundle: FixtureSigningBundle? = nil
    let targetSigningCertificate: FixtureSigningCertificate? = nil
}
func lcSigningHash(_ value: String) -> String { preconditionFailure("No certificate or identifiers may be hashed by this fixture") }
func fixturePipelineBoundary(_ error: Error, step: PipelineStep, appOperation: AppOperation) throws {
    let context = FixtureSigningContext()
    var result: Any?
    do { throw error }
'''
    # Keep the original catch byte-for-byte, including its brace prefix.
    # The original fragment begins with the do block's closing brace.
    swift = swift.removesuffix('    do { throw error }\n') + '    do { throw error\n' + boundary + '\n}\n'
    runner_path = 'SideStore/SideStore/Core/Operations/PipelineRunner.swift'
    swift += block((root / runner_path).read_text(), 'enum V3RefreshEarlyFailureBoundary {') + '\n'
    harness = (root / early.SUPPORT_PATHS[3]).read_text()
    helpers = harness.split('    static func main() async {', 1)[0]
    helpers = helpers.replace('@main\nstruct RefreshFailureCases {', 'enum ChainChecks {', 1) + '\n}\n'
    swift += helpers + (HERE / 'profile_cases.swift').read_text()
    checks = []
    def check(value, name):
        assert value, name; checks.append(name)
    check(complete_protocol in swift, 'complete inert AppProtocol interface')
    for declaration in app_operation_support:
        check(declaration in swift, 'existing inert AppOperation support ' + declaration.split('{', 1)[0].strip())
    check(block((root / early.INPUT_PATHS['app_operation']).read_text(), 'enum AppOperation:') in swift,
          'exact complete production AppOperation declaration')
    for anchor in ['public static func validatedWireSigningContext(', 'public static func validatedSigningContext(',
                   'public static func decode(', 'public static func capture(', 'private var localRefreshMessage:',
                   'private var localRefreshRecovery:']:
        host = (root / early.INPUT_PATHS['host']).read_text(); service = (root / early.INPUT_PATHS['service']).read_text()
        check(block(host, anchor) == block(service, anchor), 'mirrored ' + anchor)
        check(block(host, anchor) in swift, 'exact shared model ' + anchor)
    check(boundary in swift, 'exact existing PipelineExecutor catch body')
    check('lcRefreshFailureFacts(error, sourceStep: sourceStep)' in boundary, 'observed profile source gates classifier')
    check(block(pipeline, 'func lcRefreshFailureFacts(') in swift, 'exact typed classifier')
    check(swift.count('@main') == 1 and 'struct RefreshFailureCases' not in swift, 'no legacy case entrypoint')
    for anchor in ['func persistAutomaticRefreshVerification(', 'func reportStructuredRefreshFailure(', 'fileprivate func completedRefresh(', 'enum V3RefreshAllFailureDiagnostics {']:
        check(anchor in swift, 'existing chain ' + anchor)
    check('local_precondition=' in swift and 'optional_wire_primary_preserved' in swift, 'positive and negative Copy cases present')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'profile-preconditions.swift').write_text(swift)
    paths = set(early.INPUT_PATHS.values()) | {runner_path}
    inputs = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sorted(paths)}
    support_paths = set(early.SUPPORT_PATHS) | {EARLY_GENERATOR, EARLY_DOUBLES}
    support = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in sorted(support_paths)}
    fixture = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), HERE / 'profile_cases.swift', HERE / 'PROFILE-PRECONDITIONS.md']}
    receipt = {'schema': 'profile-preconditions-source-extraction-v1', 'status': 'STATIC_PASS_GENERATED_NOT_COMPILED_NOT_RUN',
        'checks': checks, 'check_count': len(checks), 'input_root': str(root), 'inputs_sha256': inputs,
        'support_inputs_sha256': support, 'fixture_inputs_sha256': fixture,
        'generated_sha256': hashlib.sha256(swift.encode()).hexdigest(),
        'swift_compiled': False, 'swift_executed': False, 'native_provider_executed': False, 'network_executed': False,
        'expected_case_count': len(CASE_NAMES), 'expected_case_names': CASE_NAMES,
        'limits': ['Synthetic typed errors reproduce the known local guard texts; the original guard methods are not executed.',
                   'Exact production catch, typed classifier, capture, manifest, IPC, ledger and Copy are source-extracted.',
                   'Hashing, app context, transport and persistence boundaries are inert.',
                   'Swift assertions require approved compilation/execution; generation is not a runtime or device result.']}
    (output / 'profile-sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('PROFILE_PRECONDITION_STATIC_PASS_GENERATED_NOT_COMPILED_NOT_RUN checks=' + str(len(checks)))
    return receipt

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-root', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); generate(a.candidate_root, a.output)
