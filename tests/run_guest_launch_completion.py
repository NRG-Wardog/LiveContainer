#!/usr/bin/env python3
"""Execute exact guest launch boundary methods under Foundation, not private UIKit.
The extension lookup is injected; scene display/process launch is NOT exercised.
"""
import argparse,hashlib,json,pathlib,platform,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def block(source, start):
    offset=source.index(start); a=source.index('{',offset); depth=1
    for i in range(a+1,len(source)):
        depth+=(source[i]=='{')-(source[i]=='}')
        if depth==0:return source[a+1:i]
    raise ValueError('unclosed source block')
def method(source,start):return start+' {'+block(source,start)+'}'
def main():
    p=argparse.ArgumentParser();p.add_argument('--require-native',action='store_true');p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    paths=['MultitaskSupport/AppSceneViewController.m','MultitaskSupport/DecoratedAppSceneViewController.m','tests/guest_launch_completion/fixture.m']
    source,decorated,fixture=[(ROOT/x).read_text() for x in paths]
    paths += ['tests/run_guest_launch_completion.py','LiveContainerSwiftUI/Models/LCAppModel.swift','LiveContainerSwiftUI/Views/AppList/LCAppBanner/LCAppBannerViewController.swift']
    model=(ROOT/paths[-2]).read_text();banner=(ROOT/paths[-1]).read_text()
    launch=model.split('func runApp(multitask:',1)[1].split('func forceResign()',1)[0]
    assert 'defer {' in launch
    assert 'isAppRunning = false' in launch.split('defer {',1)[1].split('try await signApp',1)[0]
    assert 'try await LCUtils.launchMultitaskGuestApp(appInfo.displayName(), diagnosticGeneration: guestDiagnosticGeneration)' in launch
    assert 'try await configuration.model.runApp(multitask: multitask)' in banner and 'showError(.preserving(error))' in banner
    lookup=method(source,'- (BOOL)lcPrepareGuestExtension')
    interruption=block(source,'[_extension setRequestInterruptionBlock:')
    cancellation=block(source,'[_extension setRequestCancellationBlock:')
    begin=block(source,'[_extension beginExtensionRequestWithInputItems:')
    settle=method(decorated,'- (void)lcCompleteLaunch:(AppSceneViewController *)controller error:(NSError *)error')
    assert 'if (![self lcPrepareGuestExtension]) return self;' in source
    assert 'if (self.isAppTerminationCleanUpCalled) return;' in block(source,'[_extension beginExtensionRequestWithInputItems:')
    assert 'dispatch_async(dispatch_get_main_queue()' in interruption
    generated=fixture.replace('@@LOOKUP@@',lookup).replace('@@INTERRUPTION@@',interruption).replace('@@SETTLE@@',settle).replace('@@CANCELLATION@@',cancellation).replace('@@BEGIN@@',begin)
    (a.output/'fixture.m').write_text(generated)
    report={'schema':'guest-launch-completion-v1','status':'STATIC_PASS_NATIVE_NOT_RUN','native_compiled':False,'native_executed':False,'source_sha256':{x:hashlib.sha256((ROOT/x).read_bytes()).hexdigest() for x in paths},'cases':['nil-extension-no-error','nil-extension-with-error','nonnull-extension-with-error','successful-lookup','wiring-before-failure','synchronous-interruption-before-wiring','duplicate-interruption','late-completion-after-cleanup','lookup-error-preserved-after-cleanup','cancellation-before-callback-wiring','late-begin-after-cleanup-no-registration','duplicate-terminal-signals'],'scope':'Exact production lookup, interruption/cancellation/begin callbacks and virtual completion methods. Fake extension and cleanup/delegate adapter. No UIKit, real process launch or native Swift scene registry execution.'}
    if platform.system()=='Darwin':
        exe=a.output/'fixture';command=['xcrun','clang','-fobjc-arc','-fblocks','-framework','Foundation',str(a.output/'fixture.m'),'-o',str(exe)]
        r=subprocess.run(command,text=True,capture_output=True);(a.output/'compile.log').write_text(r.stdout+r.stderr);r.check_returncode();report['native_compiled']=True
        r=subprocess.run([str(exe)],text=True,capture_output=True,timeout=30);(a.output/'runtime.log').write_text(r.stdout+r.stderr);r.check_returncode();assert 'GUEST_LAUNCH_COMPLETION_PASS' in r.stdout;report.update(status='PASS',native_executed=True)
        synchronous=interruption.replace('dispatch_async(dispatch_get_main_queue(), ^{\n            [weakSelf appTerminationCleanUp];\n        });', '[weakSelf appTerminationCleanUp];')
        assert synchronous != interruption
        mutations=[('nil-guard',generated.replace('if (!_extension || error)','if (error)',1),'FAIL: lookup result'),
                   ('synchronous-interruption',generated.replace(interruption,synchronous,1),'FAIL: synchronous interruption settled before constructor return')]
        report['counterfactuals']={}
        for name,mutant,expected in mutations:
            assert mutant != generated
            mutant_path=a.output/(name+'-counterfactual.m');mutant_path.write_text(mutant)
            mutant_exe=a.output/(name+'-counterfactual');mc=command.copy();mc[-3]=str(mutant_path);mc[-1]=str(mutant_exe)
            r=subprocess.run(mc,text=True,capture_output=True);(a.output/(name+'-compile.log')).write_text(r.stdout+r.stderr);r.check_returncode()
            r=subprocess.run([str(mutant_exe)],text=True,capture_output=True,timeout=30);(a.output/(name+'-runtime.log')).write_text(r.stdout+r.stderr)
            assert r.returncode != 0 and expected in r.stderr, name+' counterfactual was not rejected'
            report['counterfactuals'][name]={'rejected':True,'expected_failure':expected}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if a.require_native and not report['native_executed']:raise SystemExit('macOS Foundation compiler/runtime required; not qualified')
    print(json.dumps(report))
if __name__=='__main__':main()
