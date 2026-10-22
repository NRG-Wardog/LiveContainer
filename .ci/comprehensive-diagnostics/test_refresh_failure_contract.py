#!/usr/bin/env python3
"""Static extraction contract only; does not claim Swift execution."""
import argparse
import importlib.util
import json
import tempfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('refresh_generator',HERE/'generate_refresh_failure_fixture.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
p=argparse.ArgumentParser();p.add_argument('--sources',type=Path,required=True);a=p.parse_args()
with tempfile.TemporaryDirectory() as temporary:
    output=Path(temporary)
    receipt=g.generate(a.sources,output)
    generated=(output/'refresh-failure.swift').read_text()
    host=(a.sources/g.INPUT_PATHS['host']).read_text()
    scheduler=(a.sources/g.INPUT_PATHS['scheduler']).read_text()
    client=(a.sources/g.INPUT_PATHS['client']).read_text()
    ui=(a.sources/g.INPUT_PATHS['ui']).read_text()
    for text,anchor in [(host,'fileprivate func completedRefresh('),(host,'enum V3RefreshTerminalFailurePolicy {'),
                        (client,'func reportRefreshResult('),(client,'func reportStructuredRefreshFailure('),
                        (ui,'enum V3RefreshAllFailureDiagnostics {')]:
        assert g.block(text,anchor) in generated,anchor
    for anchor in ['private static func markFailed(','private static func terminalManifestSummary(',
                   'private static func saveRunRecord(','private static func endRun(']:
        assert g.block(scheduler,anchor).replace('private static','static',1) in generated,anchor
    for forbidden in ['PrivateIntentRunner.run(', 'URLSession.shared', 'import UIKit', 'import CoreData',
                      'SecItemCopyMatching(', 'dlopen(', 'installProvisioningProfiles(']:
        assert forbidden not in generated,forbidden
    preservation=g.block(host,'enum V3RefreshTerminalFailurePolicy {')
    for guard in ['outer.stage == .command', 'outer.code == .failed', 'outer.safeCause == nil',
                  'expectedRunID == runID, activeRunID == runID', 'activeRequestID == requestID',
                  'verification.count <= 262144', 'CombinedVerification.hasCompleteTerminalResults(',
                  'failure.operation == "refresh"', 'wire["correlationID"] as? String == runID']:
        assert guard in preservation,guard
    assert 'localizedDescription' not in preservation and 'entry["error"]' not in preservation
    assert receipt['status']=='generated_not_compiled' and receipt['swift_executed'] is False
    assert receipt['native_provider_executed'] is False and receipt['network_executed'] is False
    assert set(g.INPUT_PATHS).issubset(receipt['inputs_sha256'])
    assert set(g.FIXTURE_FILES).issubset(receipt['inputs_sha256'])
    assert len(g.CASE_NAMES)==len(set(g.CASE_NAMES))
    assert receipt['case_names']==g.CASE_NAMES
    assert json.loads((output/'sources.json').read_text())==receipt
print('PASS refresh_failure_static_extraction swift_executed=false')
