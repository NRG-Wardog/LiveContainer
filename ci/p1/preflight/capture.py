#!/usr/bin/env python3
"""Short isolated screenshot calibration and recovery capability collection."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys
import signal
import subprocess
import time
import uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(1,str(HERE.parent/'video'))
import protocol
import analyze_capability as analysis
import process_scope
import simulator_cleanup
spec=importlib.util.spec_from_file_location('prior_video_capture',HERE.parent/'video/capture.py');video=importlib.util.module_from_spec(spec);spec.loader.exec_module(video)
base=video.base
require,sha,write,parse,ordinary=video.require,video.sha,video.write,video.parse,video.ordinary
SOURCE,BUILDER,SOURCE_SHA,APP_ID=video.SOURCE,video.BUILDER,video.SOURCE_SHA,video.APP_ID
METHOD='testScreenshotCalibrationCapability'
CLASS='P1ScreenshotCapabilityUITests'
RUNNER_ID=analysis.RUNNER_ID
# Fixed list, independent of the supplied manifest. Updated only by reviewed source.
ADAPTERS=set(video.ADAPTERS)|{'ci/p1/video/test_layout_capabilities.py'}|{'ci/p1/preflight/'+name for name in ['app.swift','runner_ui_tests.swift','decode.swift','protocol.py','analyze_capability.py','capture.py','budget.py','process_scope.py','README.md','test_runner_source.py','test_capability.py','test_process_lifecycle.py','test_simulator_cleanup.py','simulator_cleanup.py','cleanup_gate.py','test_cleanup_gate.py']}


def validate(host,inputs,approved):
    require(host.is_dir() and not host.is_symlink(),'linked/missing host root');host=host.resolve()
    require(re.fullmatch('[0-9a-f]{64}',approved or '') and sha(inputs)==approved,'unreviewed inputs')
    data=parse(inputs)
    require(set(data)=={'schema','scope','livecontainer','builder','source_sha256','adapter_files'},'unexpected input fields')
    require(data['schema']=='p1-short-capability-inputs-v1' and data['scope']=='cleanup-regression-only-no-admission','wrong capability scope')
    require(data['livecontainer']==SOURCE and data['builder']==BUILDER and data['source_sha256']==SOURCE_SHA,'wrong source pin')
    require(set(data['adapter_files'])==ADAPTERS,'wrong adapter inventory')
    for path,digest in data['adapter_files'].items():require(sha(ordinary(host,path))==digest,'adapter drift: '+path)
    return data


def prepare(source,builder,build,output):
    project,renderer=video.prepare(source,builder,build,output)
    target=build/'Sources'
    original=(HERE.parent/'video/app.swift').read_text();replacement=(HERE/'app.swift').read_text()
    app=target/'p0_signin_app.swift';text=app.read_text();require(text.count(original)==1,'original fixture boundary differs');app.write_text(text.replace(original,replacement))
    tests=target/'p0_signin_ui_tests.swift';tests.write_text(tests.read_text()+'\n'+(HERE/'runner_ui_tests.swift').read_text())
    info=plistlib.loads((project/'Info.plist').read_bytes())
    orientations=['UIInterfaceOrientationPortrait','UIInterfaceOrientationPortraitUpsideDown','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight']
    info['UISupportedInterfaceOrientations']=orientations;info['UISupportedInterfaceOrientations~ipad']=orientations
    (project/'Info.plist').write_bytes(plistlib.dumps(info))
    for name in ['p0_signin_app.swift','p0_signin_ui_tests.swift']:shutil.copy2(target/name,output/'sources'/name)
    shutil.copy2(project/'Info.plist',output/'project/Info.plist')
    identity=parse(output/'source-identity.json');identity['generated_sources_sha256']={p.name:sha(p) for p in sorted(target.iterdir()) if p.is_file()}
    identity['scope']='short calibration and recovery capabilities only';identity['full_matrix_complete']=False
    write(output/'source-identity.json',identity)
    return project,renderer


def configure_runner(candidate,products,session,output):
    runners=list(products.glob('Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist'))
    require(len(runners)==1,'missing/ambiguous built runner Info.plist')
    runner_info=plistlib.loads(runners[0].read_bytes());require(runner_info.get('CFBundleIdentifier')==RUNNER_ID,'built runner identifier outside allowlist')
    shutil.copy2(runners[0],output/'runner-Info.plist')
    value=plistlib.loads(candidate.read_bytes());count=0
    def inject(node):
        nonlocal count
        if isinstance(node,dict):
            if 'TestBundlePath' in node:
                require(node.get('IsUITestBundle') is True and 'P0SignInUITests' in node['TestBundlePath'],'unexpected test bundle recipe')
                env=node.setdefault('EnvironmentVariables',{});require('P1_CAPABILITY_SESSION' not in env,'stale runner session');env['P1_CAPABILITY_SESSION']=session;count+=1
            for child in node.values():inject(child)
        elif isinstance(node,list):
            for child in node:inject(child)
    inject(value);require(count==1,'ambiguous runner target')
    target=candidate.with_name('Capability.xctestrun');target.write_bytes(plistlib.dumps(value));shutil.copy2(candidate,output/'original.xctestrun');shutil.copy2(target,output/'capability.xctestrun')
    write(output/'launch-identity.json',{'session':session,'app':APP_ID,'runner':RUNNER_ID,'original_sha256':sha(candidate),'modified_sha256':sha(target),'admissionEligible':False})
    return target


def container(command,device,bundle):
    require(bundle in [APP_ID,RUNNER_ID],'unallowlisted container discovery')
    result=command('xcrun','simctl','get_app_container',device,bundle,'data',allow_failure=True,timeout=10)
    if not result or not result.startswith('/'):return None
    root=Path(result)
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),'invalid simulator data container')
    return root.resolve()


def channel_root(command,device,bundle,session):
    root=container(command,device,bundle)
    if root is None:return None
    child=root/'Documents'/('p1-capability-app' if bundle==APP_ID else 'p1-capability')/session
    if not child.exists():return None
    for path in [root/'Documents',child.parent,child]:require(path.is_dir() and not path.is_symlink(),'linked channel ancestor')
    require(child.resolve().is_relative_to(root),'escaped simulator channel')
    identity_path=child/('identity.json' if bundle==APP_ID else 'runner.json')
    if not identity_path.exists():return None
    identity=protocol.parse(identity_path)
    require(identity.get('session')==session and identity.get('bundleIdentifier' if bundle==APP_ID else 'runnerBundleIdentifier')==bundle,'stale/wrong launch channel')
    return child


def copy_channel(root,target):
    if root is None or not root.is_dir() or target.exists():return
    # No symlinks or unexpected filesystem nodes are copied into evidence.
    base.inventory(root);shutil.copytree(root,target)


def events_at(root,session):
    files=sorted(root.glob('event-*.json'));require(0<len(files)<=100,'missing/unbounded app events')
    rows=[]
    for i,p in enumerate(files,1):
        require(p.name==f'event-{i:03d}.json','app event sequence differs');r=protocol.parse(p);require(r.get('session')==session,'app event nonce differs');rows.append(r)
    require(not (root/'journal-error.txt').exists(),'app journal reported failure')
    return rows


def await_file(path,timeout,future=None,remaining=None):
    if remaining is not None:timeout=remaining(timeout)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if path.is_file():return protocol.parse(path)
        if future is not None and future.done():future.result();raise ValueError('XCTest ended before durable handshake')
        time.sleep(.02)
    raise ValueError('durable handshake deadline: '+path.name)


def export_case(command,bundle,folder,device,session,valid_png):
    directory=folder/'attachments';command('xcrun','xcresulttool','export','attachments','--path',bundle,'--output-path',directory,timeout=60)
    summary=json.loads(command('xcrun','xcresulttool','get','test-results','summary','--path',bundle,timeout=30))
    tests=json.loads(command('xcrun','xcresulttool','get','test-results','tests','--path',bundle,timeout=30))
    write(folder/'xctest-summary.json',summary);write(folder/'xctest-tests.json',tests);base.inventory(directory)
    return verify_exports(directory,summary,tests,folder/'raw-runner',device,session,valid_png)


def verify_exports(directory,summary,tests,runner,device,session,valid_png):
    keys=['passedTests','failedTests','skippedTests','totalTestCount','expectedFailures']
    require(summary.get('result')=='Passed' and all(type(summary.get(k)) is int for k in keys) and [summary[k] for k in keys]==[1,0,0,1,0],'exact one passed zero-skipped capability method required')
    configs=summary.get('devicesAndConfigurations');require(isinstance(configs,list) and len(configs)==1 and configs[0].get('device',{}).get('deviceId')==device,'wrong XCTest device')
    expected=CLASS+'/'+METHOD+'()';url='test://com.apple.xcode/P0SignIn/P0SignInUITests/'+CLASS+'/'+METHOD
    leaves=list(video.exports.leaves(tests));require(len(leaves)==1 and leaves[0].get('nodeIdentifier') in [expected,expected[:-2]] and leaves[0].get('result')=='Passed','wrong XCTest method')
    if 'nodeIdentifierURL' in leaves[0]:require(leaves[0]['nodeIdentifierURL']==url,'wrong XCTest target')
    manifest=parse(ordinary(directory,'manifest.json'));require(isinstance(manifest,list) and len(manifest)==1 and manifest[0].get('testIdentifier')==expected and manifest[0].get('testIdentifierURL')==url,'wrong attachment method association')
    files=set();names={}
    for row in manifest[0].get('attachments',[]):
        require(row.get('deviceId')==device,'attachment device differs');path=ordinary(directory,row.get('exportedFileName'));name=row.get('suggestedHumanReadableName',row.get('attachmentName'))
        require(path.name not in files and isinstance(name,str) and name not in names,'duplicate attachment file/name');files.add(path.name);names[name]=path
    required=['capture-baseline']+[f'capture-{phase}-{i}' for phase in ['pre','mid','post'] for i in range(1,4)]+['capture-after'];result={}
    for name in required:
        candidates=[p for n,p in names.items() if n==name or n.startswith(name+'_')];require(len(candidates)==1,'missing/duplicate screenshot association: '+name)
        p=candidates[0];require(valid_png(p.read_bytes()) and sha(p)==sha(ordinary(runner,name+'.png')),'XCTest and runner PNG differ')
        require(protocol.parse(runner/(name+'.json')).get('session')==session,'capture nonce differs');result[name]=p.name
    return result


def stopped_response(receipt,identifier):
    if receipt.get('cleanup_errors'):return False
    if receipt.get('exit_code')==0 and receipt.get('failure_type') is None:return True
    expected=(f'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\n'
        f'Simulator device failed to terminate {identifier}.\nfound nothing to terminate\n'
        f'Underlying error (domain=NSPOSIXErrorDomain, code=3):\n'
        f'\tThe request to terminate "{identifier}" failed. found nothing to terminate\n\tfound nothing to terminate')
    return receipt.get('exit_code')==3 and receipt.get('failure_type')=='CalledProcessError' and receipt.get('stdout','').strip()=='' and receipt.get('stderr','').strip()==expected


def stop_fixture(command,device,folder):
    receipts=[];ok=True
    for identifier in [APP_ID,RUNNER_ID]:
        try:
            row=command('xcrun','simctl','terminate',device,identifier,timeout=15,cleanup=True,receipt=True)
            row['classified_stopped']=stopped_response(row,identifier);ok=ok and row['classified_stopped'];receipts.append(row)
        except Exception as error:ok=False;receipts.append({'bundle_id':identifier,'error':str(error),'classified_stopped':False})
    if not ok and command.scope.fixture and command.scope.fixture['owned_boot']:
        row=simulator_cleanup.confirm_shutdown(command,device,True)
        receipts.append(row);ok=row['observed_shutdown']
        if row['command_failed']:command.scope.fixture_cleanup_failure()
    command.scope.fixture_stopped(ok)
    path=folder/'fixture-termination.json';prior=parse(path) if path.exists() else []
    prior.append({'device':device,'receipts':receipts,'stopped':ok,'admissionEligible':False});write(path,prior)
    return ok


class ManagedVideo(video.transport.Video):
    def __init__(self,scope,device,output):
        self.scope=scope;self.output=output;self.stream=(output/'recording.log').open('wb')
        self.argv=['xcrun','simctl','io',device,'recordVideo','--codec=h264',str(output/'screen.mp4')]
        self.started=time.monotonic();self.process=scope.spawn(self.argv,self.stream);self.stopped=False
    def stop(self):
        if self.stopped:return
        self.stopped=True;forced=False;sigint_sent=False;requested=time.monotonic();primary=None;cleanup_errors=[]
        try:
            sigint_sent=self.process.signal_owned(signal.SIGINT)
            if sigint_sent:
                try:self.process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    forced=True;self.process.signal_owned(signal.SIGKILL);self.process.wait(timeout=10)
        except Exception as error:primary=error
        finally:
            try:self.scope.settle(self.process)
            except Exception as error:cleanup_errors.append(error)
            try:self.stream.close()
            except Exception as error:cleanup_errors.append(error)
            row={'argv':self.argv,'hostStart':self.started,'hostEnd':time.monotonic(),'exitCode':self.process.returncode,'forcedTermination':forced,
                'stopRequested':True,'stopRequestedHostUptime':requested,'sigintSent':sigint_sent,
                'clock':'host time.monotonic; process start is NOT video PTS zero','admissionEligible':False,
                'primary_error':process_scope.error_info(primary),'cleanup_errors':[process_scope.error_info(e) for e in cleanup_errors]}
            try:write(self.output/'recording-process.json',row)
            except Exception as error:cleanup_errors.append(error)
        if primary is not None:
            process_scope.emit_diagnostic('recorder-stop-failure',primary_error=process_scope.error_info(primary),cleanup_errors=[process_scope.error_info(e) for e in cleanup_errors]);raise primary
        if cleanup_errors:raise cleanup_errors[0]
        require(not forced and (self.process.returncode==0 or (sigint_sent and self.process.returncode==-signal.SIGINT)) and (self.output/'screen.mp4').is_file(),'video did not finalize with normal exit or the requested SIGINT')


def run_calibration(command,candidate,device,session,folder,valid_png):
    folder.mkdir();report={'scope':'calibration-capability-only','collection_complete':False,'calibration_feasible':False,'admissionEligible':False,'errors':[]};roots={};recorder=None;future=None;fixture_stopped=False
    try:
        command.scope.fixture_stopped(False)
        recorder=ManagedVideo(command.scope,device,folder)
        with ThreadPoolExecutor(max_workers=1) as pool:
            bundle=folder/'tests.xcresult'
            future=pool.submit(command,'xcodebuild','test-without-building','-xctestrun',candidate,'-destination','id='+device,'-resultBundlePath',bundle,
                '-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1','-test-timeouts-enabled','YES','-default-test-execution-time-allowance','240','-maximum-test-execution-time-allowance','240',
                '-only-testing:P0SignInUITests/'+CLASS+'/'+METHOD,timeout=360)
            try:
                deadline=time.monotonic()+command.scope.remaining(180)
                while time.monotonic()<deadline:
                    for role,identifier in [('app',APP_ID),('runner',RUNNER_ID)]:
                        if role not in roots:
                            value=channel_root(command,device,identifier,session)
                            if value is not None:roots[role]=value
                    if len(roots)==2 and (roots['runner']/'ready.json').is_file():break
                    if future.done():future.result();raise ValueError('XCTest ended before channels ready')
                    time.sleep(.25)
                require(len(roots)==2,'fresh app/runner channels unavailable')
                ready=await_file(roots['runner']/'ready.json',5,future,command.scope.remaining);require(ready.get('session')==session,'wrong ready nonce')
                require(any(r.get('type')=='baseline-ready' for r in events_at(roots['app'],session)),'app baseline-ready not durable')
                app=protocol.Channel(roots['app'],session,'app',folder/'app-channel.json',command.scope.remaining);runner=protocol.Channel(roots['runner'],session,'runner',folder/'runner-channel.json',command.scope.remaining)
                for phase in ['pre','mid','post']:
                    if phase!='pre':app.request('capability-'+phase)
                    for _ in range(8):app.request('clock',phase=phase)
                    for _ in range(8):runner.request('clock',phase=phase)
                    for ordinal in range(1,4):runner.request('capture',phase=phase,ordinal=ordinal,timeout=30)
                    app.request({'pre':'ready','mid':'third','post':'finish'}[phase])
                await_file(roots['app']/'strip-complete.json',10,future,command.scope.remaining)
                strip=video.read_strip(roots['app']);require(strip['complete'].get('session')==session and all(r.get('session')==session for r in strip['draws']),'wrong completed strip session')
                runner.request('after',timeout=30)
                runner.request('complete',appStripCompleteSHA256=sha(roots['app']/'strip-complete.json'),hostVerifiedStripComplete=True)
                future.result(timeout=command.scope.remaining(60))
            except Exception as error:
                report['errors'].append('protocol: '+str(error));process_scope.emit_diagnostic('calibration-protocol-failure',error=process_scope.error_info(error))
                if not future.done():command('xcrun','simctl','terminate',device,APP_ID,allow_failure=True,timeout=10,cleanup=True)
        # Stop only these disposable fixture processes before reading channels.
        fixture_stopped=stop_fixture(command,device,folder)
        require(fixture_stopped,'fixture termination not proven')
        for role in ['app','runner']:copy_channel(roots.get(role),folder/('raw-'+role))
        recorder.stop();recorder=None
        exports=export_case(command,bundle,folder,device,session,valid_png);write(folder/'export-verification.json',exports)
        events=events_at(folder/'raw-app',session);strip=video.read_strip(folder/'raw-app');write(folder/'strip-journal.json',strip)
        captures=[analysis.capture_receipt(folder/'raw-runner',f'capture-{phase}-{i}',session,(p*11)+8+i,phase,i) for p,phase in enumerate(['pre','mid','post']) for i in range(1,4)]
        geometry=[r for r in events if r.get('type')=='marker-geometry'];require(geometry,'missing actual marker geometry')
        g=geometry[-1];rect,points,scale=g['rect'],g['screenPoints'],g['scale']
        require(len(rect)==4 and len(points)==2 and all(base.number(v) and v>0 for v in points+[scale]),'invalid actual geometry')
        require(all(abs(a-b)<=1 for a,b in zip(rect,captures[0]['markerFrameBefore'])),'app marker differs from XCTest')
        decode_input={'video':str(folder/'screen.mp4'),'markerRectPixels':[v*scale for v in rect],'copyRectPixels':[v*scale for v in captures[0]['copyBefore']['frame']],
            'pixelSize':[round(v*scale) for v in points],
            'screenshots':[{'id':i,'path':str(folder/'raw-runner'/(r['name']+'.png'))} for i,r in enumerate(captures,1)],
            'independentScreenshots':[{'phase':phase,'path':str(folder/'raw-runner'/('capture-'+name+'.png'))} for phase,name in [('before','baseline'),('after','after')]]}
        write(folder/'decode-input.json',decode_input)
        command('swift',HERE/'decode.swift',folder/'decode-input.json',folder/'decoded-frames',folder/'decoded.json',timeout=180)
        report['collection_complete']=not report['errors']
        try:report['analysis']=analysis.inspect(folder,session,parse(folder/'decoded.json'),events,strip);report['calibration_feasible']=True
        except Exception as error:report['feasibility_failure']=str(error);process_scope.emit_diagnostic('calibration-feasibility-failure',error=process_scope.error_info(error))
    except Exception as error:report['errors'].append(str(error));process_scope.emit_diagnostic('phase-collection-failure',scope=report['scope'],error=process_scope.error_info(error))
    finally:
        if not fixture_stopped:
            try:fixture_stopped=stop_fixture(command,device,folder)
            except Exception as error:report['errors'].append('fixture cleanup: '+str(error))
        if not fixture_stopped:report['errors'].append('partial channels not copied: simulator writer quiescence unproved')
        for role,identifier in [('app',APP_ID),('runner',RUNNER_ID)]:
            try:
                if fixture_stopped:
                    if role not in roots:roots[role]=channel_root(command,device,identifier,session)
                    copy_channel(roots.get(role),folder/('raw-'+role))
            except Exception as error:report['errors'].append('partial '+role+': '+str(error))
        if recorder is not None:
            try:recorder.stop()
            except Exception as error:report['errors'].append('recording: '+str(error))
        report['collection_complete']=report['collection_complete'] and not report['errors']
        report['calibration_feasible']=report['calibration_feasible'] and report['collection_complete']
        write(folder/'collection-report.json',report)
    return report


def run_layout(command,candidate,device,kind,folder,valid_png):
    folder.mkdir();report={'scope':'recovery-capability-only','collection_complete':False,'full_matrix_complete':False,'admissionEligible':False,'errors':[]};bundle=folder/'tests.xcresult'
    try:
        state=json.loads(command('xcrun','simctl','list','devices','--json'))
        if not any(d['udid']==device and d['state']=='Booted' for group in state['devices'].values() for d in group):command('xcrun','simctl','boot',device)
        command('xcrun','simctl','bootstatus',device,'-b',timeout=120)
        command.scope.fixture_stopped(False)
        methods=video.layout_exports.CAPABILITY_METHODS[kind]
        try:command('xcodebuild','test-without-building','-xctestrun',candidate,'-destination','id='+device,'-resultBundlePath',bundle,'-parallel-testing-enabled','NO',
            '-maximum-concurrent-test-simulator-destinations','1','-test-timeouts-enabled','YES','-default-test-execution-time-allowance','180','-maximum-test-execution-time-allowance','180',
            *['-only-testing:P0SignInUITests/P1RecoveryLayoutUITests/'+m for m in methods],timeout=480)
        except Exception as error:report['errors'].append('XCTest: '+str(error))
        require(stop_fixture(command,device,folder),'recovery simulator writer quiescence unproved')
        if bundle.exists():
            directory=folder/'attachments';command('xcrun','xcresulttool','export','attachments','--path',bundle,'--output-path',directory,timeout=60)
            summary=json.loads(command('xcrun','xcresulttool','get','test-results','summary','--path',bundle,timeout=30));tests=json.loads(command('xcrun','xcresulttool','get','test-results','tests','--path',bundle,timeout=30))
            write(folder/'xctest-summary.json',summary);write(folder/'xctest-tests.json',tests);base.inventory(directory)
            report['validation']=video.layout_exports.verify_capabilities(directory,summary,tests,device,kind,parse,ordinary,valid_png)
            report['collection_complete']=not report['errors']
    except Exception as error:report['errors'].append(str(error));process_scope.emit_diagnostic('phase-collection-failure',scope=report['scope'],error=process_scope.error_info(error))
    finally:write(folder/'collection-report.json',report)
    return report


def finalize(output,result,command,scope,device,booted_here):
    if command is not None and device is not None:
        try:
            require(stop_fixture(command,device,output),'final simulator writer quiescence unproved')
        except Exception as error:result['errors'].append('fixture cleanup: '+str(error));result['capabilities_passed']=False;result['collection_complete']=False
        if booted_here:
            try:
                shutdown=simulator_cleanup.confirm_shutdown(command,device,True);write(output/'owned-simulator-shutdown.json',shutdown)
                scope.fixture_stopped(shutdown['observed_shutdown'])
                if shutdown['command_failed']:scope.fixture_cleanup_failure()
                require(shutdown['observed_shutdown'] and not shutdown['command_failed'],'owned simulator shutdown/state command failed')
            except Exception as error:result['errors'].append('cleanup: '+str(error));result['capabilities_passed']=False;result['collection_complete']=False
        if scope is not None and scope.fixture and scope.fixture.get('cleanup_command_failed'):
            result['errors'].append('simulator cleanup command failure retained');result['capabilities_passed']=False;result['collection_complete']=False
    if scope is not None:
        try:scope.close()
        except Exception as error:result['errors'].append('quiescence: '+str(error));result['capabilities_passed']=False;result['collection_complete']=False
    write(output/'capability-result.json',result)
    # Outer budget owner verifies group quiescence again before indexing.


def execute(host,work,output,inputs,approved,kind):
    require(kind in ['phone','tablet'] and not work.exists() and not output.exists(),'fresh paths and exact device class required');work.mkdir(parents=True);output.mkdir(parents=True)
    result={'schema':'p1-short-capability-collection-v1','scope':'calibration-and-recovery-capabilities-only','admission_eligible':False,'production_ready':False,'full_native_lane_executed':False,'full_matrix_complete':False,
        'source':SOURCE,'source_sha256':SOURCE_SHA,'approved_inputs_sha256':approved,'device_class':kind,'collection_complete':False,'capabilities_passed':False,'errors':[],
        'github':{k:os.environ.get(k) for k in ['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY']}}
    command=None;scope=None;booted_here=False;device=None
    try:
        logs=output/'commands';logs.mkdir();scope=process_scope.Scope(output);command=process_scope.Commands(scope,logs);builder,live=work/'builder',work/'LiveContainer';base.acquire(builder,BUILDER,command);base.acquire(live,SOURCE,command)
        runner=base.module('capability_commands',builder/'scripts/run_issue25_rendering.py');runner.COMMAND_LOG=logs/'bounded-commands.jsonl';runner.capture=command.bytes
        shutil.copytree(HERE,output/'harness',ignore=shutil.ignore_patterns('__pycache__'));shutil.copy2(inputs,output/'approved-inputs.json')
        write(output/'source-before.json',{'LiveContainer':base.checkout_proof(live,SOURCE,command),'builder':base.checkout_proof(builder,BUILDER,command)})
        write(output/'validation-host.json',{'commit':command('git','-C',host,'rev-parse','HEAD'),'tree':command('git','-C',host,'rev-parse','HEAD^{tree}'),'workflow_sha256':sha(host/'.github/workflows/p1-native-candidate.yml')})
        write(output/'toolchain.json',{'xcodebuild':command('xcodebuild','-version'),'swift':command('swift','--version'),'simulators':json.loads(command('xcrun','simctl','list','--json'))})
        project,renderer=prepare(live/base.SHELL,builder,work/'build',output)
        command('env','MAINTAINED_LIVE_CONTAINER_TEST_SOURCE='+str(live),'P1_FROZEN_BUILDER_TEST_SOURCE='+str(builder),'python3','-B','-m','unittest','discover','-s',HERE,'-p','test_capability.py','-k','test_exact_generated_source','-v',timeout=60)
        command('xcodebuild','build-for-testing','-project',project,'-scheme','P0SignIn','-sdk','iphonesimulator','-destination','generic/platform=iOS Simulator','-derivedDataPath',work/'build/DerivedData','-jobs','2','CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO',timeout=360)
        products=work/'build/DerivedData/Build/Products';candidates=list(products.glob('*.xctestrun'));require(len(candidates)==1,'ambiguous test recipe')
        apps=list(products.glob('Debug-iphonesimulator/P0SignIn.app'));require(len(apps)==1,'ambiguous fixture app');shutil.copy2(apps[0]/'Info.plist',output/'app-Info.plist')
        session=uuid.uuid4().hex;candidate=configure_runner(candidates[0],products,session,output)
        devices=[d for d in runner.available_devices() if d[0]==kind];require(len(devices)==1,'exact selected device class unavailable');_,device,runtime=devices[0];write(output/'selected-device.json',{'device_class':kind,'simulator_udid':device,'runtime':runtime})
        state=json.loads(command('xcrun','simctl','list','devices','--json'));booted=any(d['udid']==device and d['state']=='Booted' for group in state['devices'].values() for d in group)
        if not booted:command('xcrun','simctl','boot',device);booted_here=True
        scope.fixture_identity(device,booted_here)
        command('xcrun','simctl','bootstatus',device,'-b',timeout=120)
        for identifier in [APP_ID,RUNNER_ID]:command('xcrun','simctl','uninstall',device,identifier,allow_failure=True,timeout=15)
        command('xcrun','simctl','install',device,apps[0],timeout=30)
        result['calibration']=run_calibration(command,candidate,device,session,output/'calibration',renderer.valid_png)
        result['recovery']=run_layout(command,candidate,device,kind,output/'recovery',renderer.valid_png)
        write(output/'source-after.json',{'LiveContainer':base.checkout_proof(live,SOURCE,command),'builder':base.checkout_proof(builder,BUILDER,command)})
        require(parse(output/'source-before.json')==parse(output/'source-after.json') and sha(live/base.SHELL)==SOURCE_SHA,'source drift')
        result['collection_complete']=result['calibration']['collection_complete'] and result['recovery']['collection_complete']
        result['capabilities_passed']=result['collection_complete'] and result['calibration']['calibration_feasible']
    except Exception as error:result['errors'].append(str(error));process_scope.emit_diagnostic('collector-failure',error=process_scope.error_info(error))
    finally:finalize(output,result,command,scope,device,booted_here)
    return result['capabilities_passed']

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True)
    p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--device-class',choices=['phone','tablet']);p.add_argument('--execute',action='store_true');a=p.parse_args()
    validate(a.host_root,a.inputs,a.approved_inputs_sha256)
    if a.execute:
        require(False,'UI execution disabled in cleanup-only checkpoint')
        require(a.work is not None and a.evidence is not None and a.device_class is not None,'execution paths/class required')
        sys.exit(0 if execute(a.host_root.resolve(),a.work,a.evidence,a.inputs,a.approved_inputs_sha256,a.device_class) else 1)
