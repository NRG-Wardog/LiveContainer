"""Static extraction, ownership, privacy and fail-closed checks. Never runs Swift."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--sources', type=Path, required=True)
p.add_argument('--sidesign-root', type=Path)
a = p.parse_args()
root = a.sources
ss = root/'SideStore'
lc = root/'LiveContainer'
sign = a.sidesign_root or ss/'Dependencies/SideSign'
here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wire_generator', here/'generate_wire_fixture.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
service = (ss/'AltStore/AppDelegate.swift').read_text()
host = (lc/'SideStoreSupport/SideStore.swift').read_text()
ui = (lc/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
with tempfile.TemporaryDirectory() as d:
    out=Path(d)
    subprocess.run([sys.executable, '-B', str(here/'generate_wire_fixture.py'), '--sources', str(root), '--sidesign-root', str(sign), '--output', str(out)], check=True)
    generated_service=(out/'service.swift').read_text(); generated_host=(out/'host.swift').read_text()
    for anchor in ['enum V3AuthDiagnosticExport {', 'enum V3ResponseEncoder {', 'public struct CombinedFailure:']:
        assert g.block(service, anchor) in generated_service, anchor
    for anchor in ['enum V3CatalogRequestContext {', 'public static func validatedSigningContext(', 'public static func decode(']:
        assert g.block(host, anchor) in generated_host, anchor
    for anchor in ['enum V3AuthFailureDiagnosticsPolicy {', 'static func failureDetails(from failure: [String: Any])', 'enum V3AuthTimeoutDiagnosticRetentionPolicy {']:
        assert g.block(ui, anchor) in generated_host, anchor
    assert g.block((sign/'Sources/Constants.swift').read_text(), 'public enum GrandSlam {') in generated_service
    assert g.block(service, 'public static func validatedEncodedSnapshot(') == g.block((sign/'Sources/Models/AuthenticationDiagnosticTrace.swift').read_text(), 'public static func validatedEncodedSnapshot(')
    for text in [generated_service, generated_host]:
        for forbidden in ['URLSession.shared', 'session.data(for:', 'SRPClient(', 'dlopen(', 'import AnisetteKit', 'import UIKit', 'import SideSign']:
            assert forbidden not in text, forbidden
    hashes=json.loads((out/'sources.json').read_text())['input_sha256']
    assert hashes['service'] == hashlib.sha256((ss/'AltStore/AppDelegate.swift').read_bytes()).hexdigest()
    assert 'generated_not_compiled' in (out/'sources.json').read_text()
# Only scoped lifecycle presentation updates; identity/retry actions unchanged.
assert 'twoFactorTransientStep = nil' in g.block(ui,'if ["completed", "authenticatedProvisioningIncomplete", "failed", "timedOut", "promptExpired", "cancelled"].contains(state) {')
for path in [sign/'Sources/Models/AnisetteData.swift']:
    if path.exists():
        text=path.read_text()
        if 'enum CodingKeys' in text:
            keys=g.block(text,'enum CodingKeys')
            for forbidden in ['auth_request_trace','auth_provider_observation','auth_header_provenance','diagnosticHeaderProvenance']:
                assert forbidden not in keys
# Bind every source-owned provisioning extension and all new causal/wire route coverage.
for anchor in ['public struct V3ProvisioningCauseDiagnostic {', 'struct V3ProvisioningCauseError:',
               'extension V3ProvisioningCauseDiagnostic {', 'struct V3AccountOperationError:']:
    assert g.block(service, anchor) == g.block(host, anchor), anchor
for anchor in ['func v3AccountOperationFailure(', 'func v3CaptureAuthFailure(', 'func v3AccountUnderlyingError(',
               'func v3OperationErrorGuidance(', 'func v3ClassifyAuthError(']:
    assert g.block(service, anchor) in generated_service, anchor
operation = (ss/'SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift').read_text()
assert g.block(operation, 'private func registerCurrentDevice(') in generated_service
assert operation[operation.index('// V3_PROVISIONING_CAUSE_PRODUCER_V1:'):] in generated_service
mapper = g.block(service, 'func v3AccountOperationFailure(')
assert mapper.index('v3ProvisioningCauseContext(error)') < mapper.index('v3AccountUnderlyingError(error)')
unwrap = g.block(service, 'func v3AccountUnderlyingError(')
assert 'V3ProvisioningCauseError' in unwrap
assert 'MinimuxerServiceError' not in unwrap and 'ALTWrappedError' not in unwrap
terminal = g.block(service, 'func v3CaptureAuthFailure(')
assert 'failure.code != .cancelled' in terminal
assert 'stage: failure.stage, code: failure.code' in terminal and 'retryable: failure.retryable, safeCause: failure.safeCause' in terminal
for required in ['device-registration-cause-cases-v1', 'registrationFixtureCases()', 'provisioning_widest_',
                 'provisioning_nonstring_', 'causeMutations', 'terminal primary classification/cancellation/transport policy unchanged',
                 'actual provisioning retry details retain safe cause']:
    assert required in generated_service, required
for key in ['operation_errors', 'portal_errors', 'portal_observers', 'anisette_errors', 'archive_errors',
            'remote_errors', 'minimuxer_mapping', 'registration_doubles', 'registration_cases']:
    assert key in hashes, key
assert 'SECRET_' in generated_host and 'V3AuthStore.failureDetails(from: failure)' in generated_host
# Legacy malformed non-optional context is rejected wholesale by the existing
# host validator. This finite exception asserts a stricter replacement context;
# every other wire vector still must preserve its original typed primary.
legacy_rejections = ['legacy_hostile_auth_response_shape_0', 'legacy_hostile_auth_response_shape_1', 'legacy_hostile_auth_response_shape_2', 'legacy_hostile_auth_response_mime_0', 'legacy_hostile_auth_response_mime_1', 'legacy_hostile_auth_response_mime_2', 'legacy_bad_http_0', 'legacy_bad_http_1', 'legacy_bad_http_2', 'legacy_bad_http_3', 'legacy_wrong_kind']
legacy_block = generated_host.split('let rejectedLegacyContextCases: Set<String> = [', 1)[1].split(']', 1)[0]
assert set(re.findall(r'"([^"\n]+)"', legacy_block)) == set(legacy_rejections)
assert 'fields == [V3AuthenticationDiagnostics.stateKey: "rejected"]' in generated_host
assert 'else if let typed = item["primaryTyped"] as? String, typed != "unknown"' in generated_host
assert 'fields["typed_error"] == typed, "\\(name): original typed primary retained"' in generated_host
assert 'rejectedLegacyContextCases.isSubset(of: seen)' in generated_host
print('WIRE_GENERATOR_STATIC_PASS source_owned_routes=8 privacy_guards=true swift_executed=false')

