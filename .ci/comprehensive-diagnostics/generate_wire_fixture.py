#!/usr/bin/env python3
"""Extract real Foundation-only service -> nested IPC -> UI copy paths. Never performs authentication."""
import argparse, hashlib, json, re, shutil, subprocess
from pathlib import Path

def block(source, anchor):
    if source.count(anchor) != 1: raise ValueError(f'Nonunique anchor {anchor!r}: {source.count(anchor)}')
    start=source.index(anchor); end=source.index('{',start)+1; depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}'); end+=1
    return source[start:end]

def pure_model(source):
    start=source.index('public struct CombinedRefreshTargetPlan:')
    last=block(source,'public enum V3DiagnosticPresentation {')
    return source[start:source.index(last,start)+len(last)]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['sources','sidestore-root','livecontainer-root','sidesign-root','output','auth-cases','profile-cases']:
        p.add_argument('--'+name,type=Path,required=name=='output')
    p.add_argument('--run',action='store_true'); a=p.parse_args()
    ss=a.sidestore_root or a.sources/'SideStore'; lc=a.livecontainer_root or a.sources/'LiveContainer'
    sign=a.sidesign_root or ss/'Dependencies/SideSign'
    paths={'service':ss/'AltStore/AppDelegate.swift','host':lc/'SideStoreSupport/SideStore.swift',
           'ui':lc/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
           'operation':ss/'SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
           'collector':sign/'Sources/Models/AuthenticationDiagnosticTrace.swift',
           'provenance':sign/'Sources/Models/AuthenticationHeaderProvenance.swift','constants':sign/'Sources/Constants.swift'}
    s={k:v.read_text() for k,v in paths.items()}
    finish=block(s['service'],'private func finish(id: String, response: [String: Any]) -> Bool')
    previous=block(s['service'],'func handleSignInResult(')
    assert 'V3AuthDiagnosticExport.terminal(' in finish and 'authenticationDiagnosticTrace.snapshot()' in finish
    assert 'V3AuthDiagnosticExport.previousFailure(' in previous and 'authenticationDiagnosticTrace.snapshot()' in previous
    assert 'AuthenticationDiagnosticTrace.current ?? AuthenticationDiagnosticTrace()' in s['operation']
    assert 'AuthenticationDiagnosticTrace.$current.withValue' in s['operation']
    assert 'UIPasteboard.general.string = V3AuthStore.failureDetails(from: failure)' in s['ui']
    for anchor in ['public struct V3AuthenticationRequestSnapshot {','public struct V3AuthenticationHeaderProvenance {',
                   'public struct V3AuthenticationProviderObservation {','public enum V3AuthenticationDiagnostics {',
                   'public static func validatedSigningContext(']:
        assert block(s['service'],anchor)==block(s['host'],anchor),anchor
    assert block(s['service'],'public static func validatedEncodedSnapshot(')==block(s['collector'],'public static func validatedEncodedSnapshot(')
    for owner in ['service','host']:
        assert block(s[owner],'enum V3AuthFailureDiagnosticsPolicy {')==block(s['ui'],'enum V3AuthFailureDiagnosticsPolicy {')
    prelude='import Foundation\nimport CoreFoundation\n#if canImport(FoundationNetworking)\nimport FoundationNetworking\n#endif\n'
    wire=block(s['host'],'enum V3WireContract {')
    limit=re.findall(r'    static let responseLimit = [0-9_]+',wire); assert len(limit)==1
    primitive='enum V3WireContract {\n'+limit[0]+'\n'+block(wire,'static func strictBool(')+'\n'+block(wire,'static func strictInt(')+'\n}\n'
    service=prelude+pure_model(s['service'])+'\n'+primitive
    for anchor in ['enum V3AuthFailureDiagnosticsPolicy {','enum V3ResponseClassifier {','struct V3EncodedServiceResponse {','enum V3ResponseEncoder {']:
        service+=block(s['service'],anchor)+'\n'
    # Actual public constants are extracted, never substituted or used for requests.
    service+='enum Constants {\n'+block(s['constants'],'public enum GrandSlam {')+'\n}\n'
    here=Path(__file__).resolve().parent
    service+=(here/'service_harness.swift').read_text()
    host=prelude+pure_model(s['host'])+'\n'+primitive+block(s['host'],'enum V3CatalogRequestContext {')+'\n'
    for anchor in ['enum V3AuthFailureDiagnosticsPolicy {','enum V3AuthTimeoutDiagnosticRetentionPolicy {']:
        host+=block(s['ui'],anchor)+'\n'
    host+='enum V3ServiceBridge {\n'+block(wire,'static func strictBool(')+'\n'+block(wire,'static func strictInt(')+'\n}\n'
    copy=block(s['ui'],'static func failureDetails(from failure: [String: Any])')
    assert 'V3AuthFailureDiagnosticsPolicy.render(' in copy
    host+='enum V3AuthStore {\n'+copy+'\n}\n'
    terminal=block(s['ui'],'if ["completed", "authenticatedProvisioningIncomplete", "failed", "timedOut", "promptExpired", "cancelled"].contains(state) {')
    assert 'twoFactorTransientStep = nil' in terminal
    host+='\nfunc applyActualTerminalPresentation(state: String, transient: String?) -> (String?, Bool) {\nvar twoFactorTransientStep = transient\nvar provisioningRetryBlockedByActiveSession = true\nstruct Attempt { mutating func clear() {} }; var currentAttemptFailure = Attempt()\n'+terminal+'\nreturn (twoFactorTransientStep, provisioningRetryBlockedByActiveSession)\n}\n'
    host+=(here/'host_harness.swift').read_text()
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'service.swift').write_text(service); (a.output/'host.swift').write_text(host)
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'input_sha256':{k:digest(v) for k,v in paths.items()},'generated_sha256':{n:digest(a.output/n) for n in ['service.swift','host.swift']},
              'status':'generated_not_compiled','routes':['actual service previousFailure','actual service terminal','actual binary plist encoder',
              'actual host nested result classifier','actual CombinedFailure.decode','actual UI render and copy body']}
    (a.output/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if a.run:
        swift=shutil.which('swiftc')
        if not swift: raise SystemExit('Swift unavailable; compile and execution NOT RUN')
        if not a.auth_cases or not a.profile_cases: raise SystemExit('--run requires both producer exports')
        for name in ['service','host']: subprocess.run([swift,'-swift-version','5',str(a.output/(name+'.swift')),'-o',str(a.output/name)],check=True)
        fixture=a.output/'wire-cases.plist'
        subprocess.run([str(a.output/'service'),str(fixture),str(a.auth_cases),str(a.profile_cases)],check=True)
        subprocess.run([str(a.output/'host'),str(fixture)],check=True)
        manifest['status']='fake_service_host_copy_passed'; (a.output/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('WIRE_FIXTURE_COMPILED_AND_EXECUTED' if a.run else 'WIRE_FIXTURE_GENERATED')
if __name__=='__main__': main()
