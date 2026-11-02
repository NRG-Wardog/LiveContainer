"""Actual SS error producer -> serialized wire -> actual LC decoder/policy.

No device/network operations. Native execution is mandatory when
V3_REQUIRE_SWIFT=1 or REQUIRE_SWIFT_REFRESH_FAILURE_TESTS=1.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SS = Path(os.environ.get('V3_SIDESTORE_SOURCE_ROOT', str(ROOT.parent / 'SideStore')))
if not SS.is_dir() and (ROOT.parent / 'SS').is_dir():
    SS = ROOT.parent / 'SS'
HERE = Path(__file__).resolve().parent


def generate_sources():
    contract = SS / 'tests/refresh_failure/test_contract.py'
    spec = importlib.util.spec_from_file_location('postdispatch_ss_contract', contract)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ss_app = (SS / 'AltStore/AppDelegate.swift').read_text()
    boundary, inputs = module.generate_source(SS)
    producer = module.common(ss_app) + boundary
    producer += '\n' + module.declaration(ss_app, 'enum V3HeadlessPairingFailure {')
    producer += '\n' + (SS / 'tests/refresh_failure/pipeline_harness.swift').read_text()
    producer += r'''
@main struct ExportPostDispatch {
 static func main() throws {
  let run = "11111111-1111-4111-8111-111111111111"
  var rows: [[String:Any]] = []
  for entry in preservationPostDispatchFixtureCases() {
   let failure = CombinedFailure.capture(entry.error, operation:"refresh", stage:.refreshVerification, id:run)
   precondition(failure.stage == .command && failure.code == .failed && failure.sourceStep == .refreshApplication)
   precondition(failure.signingContext["local_precondition"] == nil)
   var verification = V3RefreshVerification()
   verification.profileStore = entry.name.hasSuffix("unavailable") ? .unavailable : .mismatch
   rows.append(["name":entry.name, "failure":failure.wire, "verification":verification.wire])
  }
  precondition(rows.count == 2)
  let data = try JSONSerialization.data(withJSONObject:["schema":"ss-postdispatch-wire-v1","run_id":run,"rows":rows],options:[.sortedKeys])
  FileHandle.standardOutput.write(data)
 }
}
'''
    support_path = ROOT / 'SideStoreSupport/SideStore.swift'
    consumer = module.common(support_path.read_text()) + r'''
@main struct ConsumePostDispatch {
 static func main() throws {
  let input = try Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))
  let payload = try JSONSerialization.jsonObject(with:input) as! [String:Any]
  precondition(payload["schema"] as? String == "ss-postdispatch-wire-v1")
  let run = payload["run_id"] as! String
  let rows = payload["rows"] as! [[String:Any]]
  precondition(rows.count == 2)
  var passed: [String] = []
  for row in rows {
   let name = row["name"] as! String
   let wire = row["failure"] as! [String:Any]
   let failure = CombinedFailure.decode(wire,expectedID:run)!
   precondition(failure.stage == .command && failure.code == .failed && failure.sourceStep == .refreshApplication)
   precondition(failure.signingContext["local_precondition"] == nil)
   let verification = row["verification"] as! [String:Any]
   let evidence = V3RefreshProfileEvidence(verification)!
   precondition(evidence.installAcknowledged && evidence.mutationDispatched && evidence.renewal == "unknown")
   let expected: V3RefreshRenewalOutcome = name.hasSuffix("unavailable") ? .acknowledgedUnverified : .verificationFailed
   let manifest: [String:Any] = ["version":2,"schema":"LiveContainerRefreshManifestV2","run_id":run,
    "expected_ids":["com.fixture.preservation"],"requested_ids":["com.fixture.preservation"],"skipped_ids":[String](),
    "results":[["bundle_id":"com.fixture.preservation","success":false,"failure":wire,"verification":verification]]]
   precondition(V3RefreshEvidencePolicy.failurePresentation(manifest,runID:run,stage:failure.stage.rawValue,code:failure.code.rawValue) == expected)
   precondition(!V3RefreshEvidencePolicy.canClearUncertainty(manifest,runID:run))
   precondition(V3RefreshEvidencePolicy.failurePresentation(manifest,runID:run,stage:"persistence",code:"failed") == nil)
   precondition(V3RefreshEvidencePolicy.failurePresentation(manifest,runID:run,stage:"guestLaunch",code:"failed") == nil)
   precondition(CombinedFailure.decode(wire,expectedID:UUID().uuidString) == nil)
   passed.append(name)
  }
  let report: [String:Any] = ["schema":"ss-lc-postdispatch-wire-v1","status":"PASS","cases":passed,"device_executed":false,"network_executed":false]
  print(String(data:try JSONSerialization.data(withJSONObject:report,options:[.sortedKeys]),encoding:.utf8)!)
 }
}
'''
    inputs = list(inputs.values()) + [SS / 'tests/refresh_failure/pipeline_harness.swift', support_path, Path(__file__)]
    return producer, consumer, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}


class PostDispatchWireTests(unittest.TestCase):
    def test_actual_producer_and_consumer_source_closure(self):
        producer, consumer, inputs = generate_sources()
        self.assertIn('preservationPostDispatchFixtureCases()', producer)
        self.assertIn('getMappedError(for: .refresh(app), error: marked)', producer)
        self.assertIn('CombinedFailure.capture(entry.error', producer)
        self.assertIn('CombinedFailure.decode(wire,expectedID:run)', consumer)
        self.assertIn('V3RefreshEvidencePolicy.failurePresentation(manifest', consumer)
        self.assertIn('!V3RefreshEvidencePolicy.canClearUncertainty(manifest', consumer)
        self.assertNotIn('struct CombinedFailure {', consumer)
        self.assertTrue(inputs)

    def test_actual_two_executable_wire(self):
        swift = shutil.which('swiftc')
        if swift is None:
            if os.environ.get('V3_REQUIRE_SWIFT') == '1' or os.environ.get('REQUIRE_SWIFT_REFRESH_FAILURE_TESTS') == '1':
                self.fail('swiftc required: actual SS-to-LC post-dispatch wire NOT RUN')
            self.skipTest('swiftc unavailable: actual SS-to-LC wire NOT RUN')
        producer, consumer, inputs = generate_sources()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name, source in [('producer', producer), ('consumer', consumer)]:
                file = path / (name + '.swift'); file.write_text(source)
                result = subprocess.run([swift, '-parse-as-library', str(file), '-o', str(path / name)], capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(path / 'producer')], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wire = path / 'wire.json'; wire.write_text(result.stdout)
            result = subprocess.run([str(path / 'consumer'), str(wire)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['cases'], ['preservation-postdispatch-unavailable', 'preservation-postdispatch-mismatch'])
            self.assertEqual(report['status'], 'PASS')
            self.assertFalse(report['device_executed']); self.assertFalse(report['network_executed'])
            report['inputs'] = inputs
            print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
