"""Compile and execute source-owned cold VPN observation policy; no actual VPN/device access."""
from pathlib import Path
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOST = ROOT / 'LiveContainerSwiftUI/App/AppDelegate.swift'
def source():
    text=HOST.read_text()
    begin='// V3_COLD_VPN_OBSERVATION_BEGIN\n'; end='// V3_COLD_VPN_OBSERVATION_END'
    assert text.count(begin)==text.count(end)==1
    return text.split(begin,1)[1].split(end,1)[0]

class ColdVPNObservationTests(unittest.TestCase):
    def test_policy_is_read_only_and_production_observation_is_owned(self):
        owned=source();text=HOST.read_text()
        for forbidden in ['UIApplication.shared.open', 'performRefresh(', 'refreshAllApps(', 'Date()', 'ContinuousClock']:
            self.assertNotIn(forbidden,owned)
        settle=text.split('static func settleAfterActivation(',1)[1].split('\n    static func check(',1)[0]
        self.assertEqual(settle.count('NWPathMonitor(requiredInterfaceType: .wifi)'),1)
        self.assertIn('defer { monitor.pathUpdateHandler = nil; monitor.cancel() }',settle)
        self.assertIn('now: { ProcessInfo.processInfo.systemUptime }',settle)
        self.assertIn('ownsRun: ownsRun',settle)
        self.assertNotIn('Task.sleep(nanoseconds: 2_000_000_000)',settle)
        self.assertIn('!activationAlreadyAttempted, activeRunID == runID',text)
        self.assertIn('requestID: correlatedRequestID, ownsNetworkRun: ownsNetworkRun)',text)
        self.assertIn('source: source, gateFinished: gate.isFinished)',text)
        self.assertIn('guard ownsNetworkRun() else { throw CancellationError() }',text)

    def test_ios15_actual_policy_and_monitor_adapter_typecheck(self):
        if platform.system() != 'Darwin' or shutil.which('xcrun') is None:
            if os.environ.get('REQUIRE_SWIFT_COLD_VPN_TESTS') == '1':
                self.fail('Mandatory Apple SDK iOS15 policy/monitor compile unavailable')
            self.skipTest('Apple SDK unavailable; iOS15 policy/monitor not checked')
        text=HOST.read_text()
        start=text.index('    static func settleAfterActivation(')
        end=text.index('{',start)+1;depth=1
        while depth:
            depth += (text[end]=='{')-(text[end]=='}');end+=1
        settle=text[start:end]
        # Only OS-effect return values outside the extracted adapter are stubs.
        # Actual NWPathMonitor/UIKit/monotonic-clock calls are typechecked by SDK.
        fixture='import Foundation\nimport UIKit\nimport Network\n'+source()+"\n@MainActor enum AvailabilityAdapter {\n"+settle+"\nstatic func hasTunnelInterface() -> Bool { false }\nstatic func failure(_ code: Int, _ message: String) -> NSError { NSError(domain: \"fixture\", code: code) }\n}\n"
        sdk=subprocess.check_output(['xcrun','--sdk','iphonesimulator','--show-sdk-path'],text=True).strip()
        architecture=platform.machine();self.assertIn(architecture,['arm64','x86_64'])
        with tempfile.TemporaryDirectory(prefix='cold-vpn-ios15-') as temp:
            path=Path(temp).resolve()/'Availability.swift';path.write_text(fixture)
            result=subprocess.run(['xcrun','--sdk','iphonesimulator','swiftc','-swift-version','5',
                '-typecheck','-parse-as-library','-sdk',sdk,'-target',architecture+'-apple-ios15.0-simulator',str(path)],
                capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        evidence=os.environ.get('COLD_VPN_EVIDENCE_DIR')
        if evidence:
            directory=Path(evidence).resolve();directory.mkdir(parents=True,exist_ok=True)
            (directory/'host-observation-ios15.json').write_text(json.dumps({
                'status':'PASS_TYPECHECK_ONLY','deployment_target':'iOS15.0-simulator',
                'source_sha256':hashlib.sha256(HOST.read_bytes()).hexdigest(),
                'extracted_compile_source_sha256':hashlib.sha256(fixture.encode()).hexdigest(),
                'network_executed':False,'device_executed':False},indent=2)+'\n')

    def test_actual_policy_virtual_timeline_and_owner_mutations(self):
        compiler=shutil.which('swiftc')
        if not compiler:
            if os.environ.get('REQUIRE_SWIFT_COLD_VPN_TESTS')=='1': self.fail('Mandatory Swift compiler unavailable')
            self.skipTest('Swift unavailable; source-owned timeline not executed')
        cases=(HERE/'cases.swift').read_text()
        expected=re.findall(r'check\("([^\"]+)"',cases)
        self.assertEqual(len(expected),len(set(expected)))
        with tempfile.TemporaryDirectory(prefix='cold-vpn-observation-') as temp:
            root=Path(temp).resolve()
            swift=root/'ColdVPN.swift';swift.write_text('import Foundation\n'+source()+'\n'+cases)
            binary=root/'cold-vpn';result=root/'result.json'
            compiled=subprocess.run([compiler,'-swift-version','5','-parse-as-library',str(swift),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            ran=subprocess.run([str(binary),str(result)],capture_output=True,text=True,timeout=30)
            self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
            report=json.loads(result.read_text());self.assertEqual(report['cases'],expected)
            self.assertEqual(report['status'],'PASS')
            report['source_sha256']=hashlib.sha256(HOST.read_bytes()).hexdigest()
            report['generated_sha256']=hashlib.sha256(swift.read_bytes()).hexdigest()
            evidence=os.environ.get('COLD_VPN_EVIDENCE_DIR')
            if evidence:
                directory=Path(evidence).resolve();directory.mkdir(parents=True,exist_ok=True)
                (directory/'host-observation.json').write_text(json.dumps(report,indent=2)+'\n')
            print(ran.stdout.strip())

if __name__=='__main__':unittest.main(verbosity=2)
