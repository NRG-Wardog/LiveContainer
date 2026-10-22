#!/usr/bin/env python3
"""Extract real pairing recovery, wire, snapshot application and display paths.
Only native pairing, the process transport, database and journal IO are doubles.
"""
import argparse
import hashlib
import importlib.util
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

CASE_NAMES = [
    "baseline-dispatched-snapshot-ack-stale-owner-reproduced",
    "exact-ack-plus-quiescent-snapshot-retires-owner",
    "ack-fail-retains-owner",
    "ack-cancel-retains-owner",
    "ack-cancelAfterResponse-retains-owner",
    "ack-wrongTarget-retains-owner",
    "ack-falseAck-retains-owner",
    "ack-epochChanged-retains-owner",
    "ack-serviceChanged-retains-owner",
    "failed-repeat-ack-retains-only-original-success-proof",
    "snapshot-missingAck-retains-owner",
    "snapshot-newerOwner-retains-owner",
    "snapshot-differentOperation-retains-owner",
    "snapshot-unreadable-retains-owner",
    "snapshot-activeMutation-retains-owner",
    "snapshot-busy-retains-owner",
    "snapshot-malformedDirect-retains-owner",
    "snapshot-postAckEpochChanged-retains-owner",
    "cleanup-uncertainty-retains-durable-and-host-owner",
    "wire-classify-copy-pairingUsePlaced",
    "wire-classify-copy-directRecoveryInspect",
    "wire-classify-copy-directRecoveryReconcile",
    "correlation-outer-no-request-context",
    "correlation-inner-no-request-context",
    "correlation-unallowlistedOperation-no-request-context",
    "finite-recovery-refusal-causes-preserve-journal",
    "localized-command-recovery-deferred-en",
    "localized-command-recovery-deferred-zh-Hans",
    "localized-command-recovery-deferred-zh-Hant",
    "localized-command-recovery-deferred-he",
    "certificate-import-safe-copy-and-stale-suffix"
]

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wire_fixture', HERE/'generate_wire_fixture.py')
wire_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire_fixture)
block = wire_fixture.block

def between(text, start, end):
    assert text.count(start) == 1, start
    at = text.index(start)
    return text[at:text.index(end, at)]

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

def generate(root, out):
    paths = {
        'host': root/'LiveContainer/SideStoreSupport/SideStore.swift',
        'service': root/'SideStore/AltStore/AppDelegate.swift',
        'ui': root/'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
        'localization': root/'LiveContainer/LiveContainerSwiftUI/Utilities/V3Localization.swift',
        'settings': root/'LiveContainer/LiveContainerSwiftUI/Views/Settings/LCSettingsView.swift',
        'catalog': root/'LiveContainer/Resources/Localizable.xcstrings',
    }
    s = {k:p.read_text() for k,p in paths.items()}
    host, service, ui = s['host'], s['service'], s['ui']
    out.mkdir(parents=True, exist_ok=True)
    prelude = 'import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    fixture = prelude + wire_fixture.pure_model(host) + '\n'
    for anchor in ['public struct V3AuthServiceSnapshot', 'enum V3WireContract {',
                   'enum V3CatalogRequestContext {']:
        fixture += block(host, anchor) + '\n'
    fixture += block(service, 'enum V3WireContract {').replace('V3WireContract', 'ServiceWireContract') + '\n'
    for anchor in ['enum V3ResponseClassifier {', 'struct V3EncodedServiceResponse {', 'enum V3ResponseEncoder {']:
        fixture += block(service, anchor) + '\n'
    for anchor in ['struct V3HostDirectRecoveryRecord:', 'enum V3DirectRecoveryPostcondition:',
                   'enum V3DirectRecoveryHostPolicy {', 'enum V3DirectRecoveryPresentationPolicy {']:
        fixture += block(ui, anchor) + '\n'
    fixture += s['localization'] + '\n'
    fixture += block(s['settings'], 'enum V3CertificateImportFailureDetails {') + '\n'
    fixture += block(service, 'private enum V3DirectMutationRecoveryLifecycle {') + '\n'
    full_apply = block(ui, 'private func applyFullRecoveryEvidence(')
    retirement = between(full_apply, '        // The mutation\'s own snapshot', '        unresolvedRecoveryJournalUnreadable = unreadable')
    baseline_apply = full_apply.replace(retirement, '')
    # Frozen old store body: the negative control is the exact delivered method,
    # not a second hand-written Boolean approximation of its behavior.
    assert digest(baseline_apply) == '7f2e5adb99e4e990513152d59c2e7e931d871e4e3c5bbc9f32344a180b4ac19a'
    actual_ack = between(host, '    private var acknowledgedDirectRecovery:', '\n\n    public func statusReplyMayApply(')
    pairing_case = between(service, '        case "pairingUsePlaced":\n            let outcome = try await V3BackendCommands', '        case "settingsGet":')
    reconcile_case = between(service, '        case "directRecoveryReconcile":\n            let acknowledgesTerminal', '        case "refreshAdmissionBegin":')
    owner_admission = between(service, '        let directRecoveryControl = directRecoveryRecord?.requestID == target', '        if operation == "directRecoveryReconcile", let directRecoveryRecord,')
    prepared_request = between(host, '        var message: [String: Any] = ["version": 1, "id": id, "operation": operation,', '        let response: Data\n')
    assert 'V3WireContract.encodeRequest(message)' in prepared_request
    assert 'try await V3ServiceBridge.shared.request(operation: "pairingUsePlaced")' in block(ui, '    private func usePlacedPairing()')
    assert 'status.finishDirectMutation(ticket: ticket, reply: result, requestReload: true)' in block(ui, '    private func usePlacedPairing()')
    assert 'V3ServiceBridge.shared.statusReplyMayApply(snapshot)' in block(ui, '    func accept(_ snapshot:')
    assert 'technical: status.issue?.technicalDetails ?? status.error ?? ""' in ui
    suffix = 'provisioningMessage += "\\nChecking the saved provisioning state before another attempt."'
    assert suffix in ui
    fixture += '\nfunc appendActualProvisioningSuffix(_ supplied: String) -> String {\nvar provisioningMessage = supplied\n' + suffix + '\nreturn provisioningMessage\n}\n'
    harness = (HERE/'pairing_recovery_harness.swift').read_text()
    replacements = {
        '// EXPECTED_CASE_NAMES_INSERT': json.dumps(CASE_NAMES),
        '// ACTUAL_ACK_INSERT': actual_ack,
        '// ACTUAL_FULL_SNAPSHOT_INSERT': full_apply.replace('private func ', 'func ', 1),
        '// BASELINE_FULL_SNAPSHOT_INSERT': baseline_apply.replace('private func applyFullRecoveryEvidence', 'func applyBaselineFullRecoveryEvidence', 1),
        '// ACTUAL_PAIRING_DISPATCH_INSERT': pairing_case,
        '// ACTUAL_RECONCILE_DISPATCH_INSERT': reconcile_case,
        '// ACTUAL_OWNER_ADMISSION_INSERT': owner_admission,
        '// ACTUAL_SAFE_RECOVERY_INSERT': block(service, 'private func safeDirectRecovery(').replace('private func ', 'func ', 1),
        '// ACTUAL_INSPECT_INSERT': block(service, 'private func directRecoveryInspection(').replace('private func ', 'func ', 1),
        '// ACTUAL_REQUEST_ENCODE_INSERT': prepared_request,
    }
    for marker, value in replacements.items():
        assert harness.count(marker) == 1, marker
        harness = harness.replace(marker, value)
    fixture += harness
    forbidden = ['URLSession.shared', 'import UIKit', 'import Minimuxer', 'dlopen(', 'SRPClient(']
    for token in forbidden:
        assert token not in fixture, token
    (out/'fixture.swift').write_text(fixture)
    bundle = out/'TestLocalization.bundle'
    bundle.mkdir(exist_ok=True)
    (bundle/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'test.synthetic.pairing-recovery', 'CFBundleDevelopmentRegion':'en', 'CFBundlePackageType':'BNDL'}))
    strings = json.loads(s['catalog'])['strings']
    for language in ['en', 'he', 'zh-Hans', 'zh-Hant']:
        localized = {key:row['localizations'][language]['stringUnit']['value'] for key,row in strings.items()
                     if language in row.get('localizations', {}) and 'stringUnit' in row['localizations'][language]}
        directory = bundle/(language+'.lproj')
        directory.mkdir(exist_ok=True)
        (directory/'Localizable.strings').write_bytes(plistlib.dumps(localized))
    manifest = {
        'status':'generated_not_compiled',
        'input_sha256':{key:hashlib.sha256(path.read_bytes()).hexdigest() for key,path in paths.items()},
        'fixture_sha256':digest(fixture), 'baseline_store_sha256':digest(baseline_apply),
        'fixture_inputs':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in [
            'generate_pairing_recovery_fixture.py', 'pairing_recovery_harness.swift',
            'test_pairing_recovery_contract.py', 'generate_wire_fixture.py']},
        'output_sha256':{str(path.relative_to(out)):hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in [out/'fixture.swift', bundle/'Info.plist'] +
                         [bundle/(lang+'.lproj')/'Localizable.strings' for lang in ['en','he','zh-Hans','zh-Hant']]},
        'schema':'pairing-recovery-sources-v1', 'case_names':CASE_NAMES,
        'owned_paths':['actual mutation dispatch lifecycle', 'actual pairing dispatcher snapshot ordering',
                       'actual direct recovery ACK', 'actual full snapshot recovery application',
                       'actual host/service binary request serialization', 'actual service reply encoder',
                       'actual host classifier and diagnostic copy', 'actual localized renderer',
                       'actual certificate-import safe diagnostic helper'],
        'doubles':['native pairing result', 'XPC delivery', 'journal IO', 'unrelated database snapshot fields',
                   'status-ticket admission boundary (production guard statically asserted)'],
    }
    (out/'sources.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='store_true')
    a = p.parse_args()
    manifest = generate(a.sources, a.output)
    if a.run:
        swift = shutil.which('swiftc')
        if not swift:
            raise SystemExit('Swift unavailable; compile and execution NOT RUN')
        subprocess.run([swift, '-swift-version', '5', '-parse-as-library', str(a.output/'fixture.swift'), '-o', str(a.output/'fixture')], check=True)
        subprocess.run([str(a.output/'fixture'), str(a.output/'TestLocalization.bundle'), str(a.output/'cases.json')], check=True)
        manifest['status'] = 'synthetic_boundary_executed_pass'
        (a.output/'sources.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('PAIRING_RECOVERY_EXECUTED' if a.run else 'PAIRING_RECOVERY_GENERATED_NOT_COMPILED')

if __name__ == '__main__':
    main()
