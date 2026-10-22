"""Static extraction, ownership, privacy and fail-closed checks. Never runs Swift."""
import argparse
import hashlib
import importlib.util
import json
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
print('WIRE_GENERATOR_STATIC_PASS source_owned_routes=6 privacy_guards=true swift_executed=false')

