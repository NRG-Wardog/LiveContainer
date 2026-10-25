#!/usr/bin/env python3
"""Fail-closed source ownership and generation checks; never compiles or runs Swift."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--sources', type=Path, required=True)
a = p.parse_args()
here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pairing_generator', here/'generate_pairing_recovery_fixture.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
root = a.sources
host = (root/'LiveContainer/SideStoreSupport/SideStore.swift').read_text()
service = (root/'SideStore/AltStore/AppDelegate.swift').read_text()
ui = (root/'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
with tempfile.TemporaryDirectory() as d:
    out = Path(d)
    manifest = g.generate(root, out)
    fixture = (out/'fixture.swift').read_text()
    for source, anchors in [(host, ['enum V3CatalogRequestContext {', 'enum V3WireContract {']),
                            (service, ['private enum V3DirectMutationRecoveryLifecycle {', 'enum V3ResponseEncoder {']),
                            (ui, ['struct V3HostDirectRecoveryRecord:', 'enum V3DirectRecoveryHostPolicy {'])]:
        for anchor in anchors: assert g.block(source, anchor) in fixture, anchor
    assert g.block(ui, 'private func applyFullRecoveryEvidence(').replace('private func ', 'func ', 1) in fixture
    assert g.block(ui, 'enum V3PlacedPairingPresentation {') in fixture
    placement = g.block(ui, '    private func usePlacedPairing()')
    assert 'messageSeverity = presentation.severity' in placement
    assert 'pairingFailure = failure' in placement
    assert 'V3PlacedPairingPresentation.result' in placement
    assert 'messageSeverity == .success ? .green' in ui
    certificate_ui = g.block(ui, 'struct V3CertificatesView: View {')
    assert 'diagnosticFailure = error as? CombinedFailure' in certificate_ui
    assert 'visibleMessage: message, technical: failure.technicalDetails' in certificate_ui
    assert certificate_ui.count('presentCertificateFailure(error)') == 4

    assert 'guard !Task.isCancelled,' in fixture
    assert 'withUnsafeCurrentTask { $0?.cancel() }' in fixture
    assert manifest['baseline_store_sha256'] == '7f2e5adb99e4e990513152d59c2e7e931d871e4e3c5bbc9f32344a180b4ac19a'
    assert len(g.CASE_NAMES) == len(set(g.CASE_NAMES)) == 32
    assert len(manifest['input_sha256']) == 6 and len(manifest['fixture_inputs']) == 4
    assert len(manifest['output_sha256']) == 7
    for name, digest in manifest['output_sha256'].items():
        assert hashlib.sha256((out/name).read_bytes()).hexdigest() == digest, name
    for name, digest in manifest['fixture_inputs'].items():
        assert hashlib.sha256((here/name).read_bytes()).hexdigest() == digest, name
    assert not (out/'cases.json').exists() and manifest['status'] == 'generated_not_compiled'
    for token in ['URLSession.shared', 'session.data(for:', 'import UIKit', 'import Minimuxer', 'dlopen(']:
        assert token not in fixture, token
    assert 'certificate_import_step=' in fixture and 'SECRET_PAIRING_CONTENT_OR_ACCOUNT_CANARY' in fixture
    assert 'PAIRING_RECOVERY_BOUNDARY_PASS' in fixture and 'pairing-recovery-cases-v1' in fixture
# Mirrored finite causes, not arbitrary strings or journal contents.
for token in ['directRecoveryRecordMissing','directRecoveryTargetMismatch','directRecoveryModeInvalid','directRecoveryPhaseNotEligible']:
    assert token in g.block(host, 'public struct CombinedFailure:')
    assert token in g.block(service, 'public struct CombinedFailure:')
assert g.block(host, 'public enum SafeCause:') == g.block(service, 'public enum SafeCause:')
# Full status ticket/service generation authority remains before recovery application.
accept = g.block(ui, '    func accept(_ snapshot:')
assert accept.index('statusReplyMayApply(snapshot)') < accept.index('applyFullRecoveryEvidence(snapshot)')
assert '@Published private(set) var unresolvedDirectRecovery: V3HostDirectRecoveryRecord?' in ui
catalog = json.loads((root/'LiveContainer/Resources/Localizable.xcstrings').read_text())['strings']
for key in ['command','pairingUsePlaced','placed pairing activation',
            'Apple ID signed in. Add pairing before refreshing or installing apps.',
            'Checking the saved provisioning state before another attempt.']:
    for language in ['en','he','zh-Hans','zh-Hant','ru']:
        assert catalog[key]['localizations'][language]['stringUnit']['value']
print('PAIRING_RECOVERY_STATIC_PASS source_owned=true swift_executed=false')
