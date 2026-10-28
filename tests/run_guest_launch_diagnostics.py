#!/usr/bin/env python3
"""Execute exact memory-only diagnostics, completion classifier and Logs reload policy.
No guest launch, account data, database, service or UIKit presentation is executed.
"""
import argparse,hashlib,json,pathlib,platform,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
CASES=['not-started','reset-before-signing','fixed-token-allowlist','bounded-phases','stale-generation-rejected','terminal-immutable','error-classification','provider-data-redacted','completion-forwarded','copy-without-service','reload-before-service-guard','swift-overload-typecheck']
def section(source,start,end):
    assert source.count(start)==1 and source.count(end)==1
    return source.split(start,1)[1].split(end,1)[0]
def block(source,anchor):
    assert source.count(anchor)==1
    start=source.index(anchor);opening=source.index('{',start);depth=1
    for index in range(opening+1,len(source)):
        depth+=(source[index]=='{')-(source[index]=='}')
        if depth==0:return source[start:index+1]
    raise ValueError('Unclosed production block')
def execute(command,log,timeout=120):
    result=subprocess.run([str(x) for x in command],capture_output=True,text=True,timeout=timeout)
    log.write_text(result.stdout+result.stderr)
    if result.returncode:print(log.read_text()[-16000:])
    result.check_returncode();return result.stdout

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-native',action='store_true');parser.add_argument('--output',type=pathlib.Path,required=True);args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    paths=['LiveContainerSwiftUI/Utilities/LCUtils.m','LiveContainerSwiftUI/Utilities/LCUtils.h','LiveContainerSwiftUI/Models/LCAppModel.swift','LiveContainerSwiftUI/Views/V3UnifiedShell.swift','SideStoreSupport/SideStore.swift','tests/guest_launch_diagnostics/fixture.m','tests/run_guest_launch_diagnostics.py']
    m,h,model,ui,support,fixture,_=[(ROOT/p).read_text() for p in paths]
    storage=section(m,'// LC_GUEST_DIAGNOSTIC_STORAGE_BEGIN','// LC_GUEST_DIAGNOSTIC_STORAGE_END');methods=section(m,'// LC_GUEST_DIAGNOSTIC_METHODS_BEGIN','// LC_GUEST_DIAGNOSTIC_METHODS_END')
    finish=block(m,'void (^finish)(NSNumber *, NSError *) = ^(NSNumber *pid, NSError *error)');finish=finish[finish.index('{')+1:-1]
    generated=fixture.replace('@@STORAGE@@',storage).replace('@@METHODS@@',methods).replace('@@FINISH@@',finish);assert '@@' not in generated
    (out/'fixture.m').write_text(generated)
    run=block(model,'func runApp(multitask: Bool? = nil,');assert run.index('isAppRunning = true')<run.index('let guestDiagnosticGeneration')<run.index('try await signApp(force: false)')
    assert run.count('diagnosticGeneration: guestDiagnosticGeneration')==2 and 'phase: "signing_failed"' in run
    logs=block(ui,'struct V3LogsView: View {');reload=block(logs,'private func reload() async').replace('private func','func',1)
    assert reload.index('LCUtils.guestLaunchDiagnosticSnapshot()')<reload.index('guard V3OperationLogLoadPolicy.shouldRequestServiceLogs')
    assert 'V3OperationLogLoadPolicy.copyText(startup: startup, operations: tail)' in logs
    assert 'V3OperationLogLoadPolicy.canCopy(reloading: reloading, startup: startup, operations: tail)' in logs
    declarations='\n'.join(line for line in h.splitlines() if any(key in line for key in ['+ (void)launchMultitaskGuestApp:', '+ (NSUInteger)beginGuestLaunchDiagnostics','+ (void)recordGuestLaunchDiagnostic:', '+ (NSString *)guestLaunchDiagnosticSnapshot']))
    assert len(declarations.splitlines())==5
    header='#import <Foundation/Foundation.h>\n@interface LCUtils:NSObject\n'+declarations+'\n@end\n';(out/'ActualDeclarations.h').write_text(header)
    (out/'ActualDiagnostics.m').write_text('#import "ActualDeclarations.h"\n'+storage+'\n@implementation LCUtils\n'+methods+'\n@end\n')
    policy=block(support,'public enum V3OperationLogLoadPolicy {')
    swift='''import Foundation
@MainActor final class V3ServiceBridge {
 static let shared = V3ServiceBridge()
 var startupDiagnosticText = "safe_startup_fixture"
 var serviceReadyForOperationLogs = false
 var requests = 0
 func request(operation: String) async throws -> [String:Any] { precondition(operation == "logTail"); requests += 1; return ["tail":"safe_service_fixture"] }
}
enum V3FailureGuidance { static func message(_ error: Error)->String { "safe_failure" } }
'''+policy+'\n@MainActor final class LogsHarness { var startup="",tail="",message="";var reloading=false\n'+reload+'''\n}
@main struct CopyFixture {
 @MainActor static func main() async {
  let token = LCUtils.beginGuestLaunchDiagnostics()
  LCUtils.recordGuestLaunchDiagnostic(token, phase:"signing")
  let logs=LogsHarness();let service=V3ServiceBridge.shared
  await logs.reload()
  precondition(service.requests==0 && !logs.reloading && logs.tail.isEmpty)
  precondition(logs.startup.contains("guest_launch_phases=admitted,signing"))
  precondition(V3OperationLogLoadPolicy.canCopy(reloading:false,startup:logs.startup,operations:logs.tail))
  precondition(V3OperationLogLoadPolicy.copyText(startup:logs.startup,operations:logs.tail).contains("guest_launch_state=pending"))
  service.serviceReadyForOperationLogs=true;await logs.reload()
  precondition(service.requests==1 && logs.tail=="safe_service_fixture")
  let copy=V3OperationLogLoadPolicy.copyText(startup:logs.startup,operations:logs.tail)
  precondition(copy.contains("guest_launch_phases=admitted,signing") && copy.contains("safe_service_fixture"))
  print("GUEST_DIAGNOSTIC_COPY_PASS")
 }
}
''';(out/'CopyFixture.swift').write_text(swift)
    binding='''import Foundation
func diagnosticOverloads(_ multitask: Bool) async throws {
 let generation = multitask ? LCUtils.beginGuestLaunchDiagnostics() : 0
 LCUtils.recordGuestLaunchDiagnostic(generation, phase:"signing")
 let _: String = LCUtils.guestLaunchDiagnosticSnapshot()
 if #available(iOS 16.0, *) {
  LCUtils.launchMultitaskGuestApp("fixture", diagnosticGeneration:generation) { pidNumber,error in
   if error != nil { return };guard let pidNumber else { return };let _:Int=pidNumber.intValue
  }
  _ = try await LCUtils.launchMultitaskGuestApp("fixture", diagnosticGeneration:generation)
 }
}
''';(out/'Bindings.swift').write_text(binding)
    report={'schema':'guest-launch-diagnostics-v1','status':'STATIC_PASS_NATIVE_NOT_RUN','native_compiled':False,'native_executed':False,'ios_swift_typechecked':False,'copy_policy_executed':False,'cases':CASES,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},'scope':'Actual memory-only Objective-C methods and completion classifier; actual Swift log reload/copy policy with synthetic service. Exact LCUtils header method declarations projected into Foundation-only header for iOS15 Swift typecheck. No UIKit alert rendering, real guest or service execution.'}
    if platform.system()=='Darwin':
        execute(['xcrun','clang','-fobjc-arc','-fblocks','-framework','Foundation',out/'fixture.m','-o',out/'fixture'],out/'compile.log');report['native_compiled']=True
        assert 'GUEST_LAUNCH_DIAGNOSTICS_PASS' in execute([out/'fixture'],out/'runtime.log',30);report['native_executed']=True
        execute(['xcrun','clang','-fobjc-arc','-fblocks','-c',out/'ActualDiagnostics.m','-o',out/'diagnostics.o'],out/'copy-objc-compile.log')
        execute(['xcrun','swiftc','-parse-as-library','-import-objc-header',out/'ActualDeclarations.h',out/'CopyFixture.swift',out/'diagnostics.o','-o',out/'copy-fixture'],out/'copy-compile.log')
        assert 'GUEST_DIAGNOSTIC_COPY_PASS' in execute([out/'copy-fixture'],out/'copy-runtime.log',30);report['copy_policy_executed']=True
        sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
        execute(['xcrun','--sdk','iphoneos','swiftc','-typecheck','-sdk',sdk,'-target','arm64-apple-ios15.0','-import-objc-header',out/'ActualDeclarations.h',out/'Bindings.swift'],out/'ios-bindings.log');report['ios_swift_typechecked']=True;report['status']='PASS'
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    if args.require_native and report['status']!='PASS':raise SystemExit('macOS Objective-C/Swift and iOS SDK required; not qualified')
if __name__=='__main__':main()
