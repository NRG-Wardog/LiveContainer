#!/usr/bin/env python3
"""External video and reviewed-layout diagnostic; no admission-shaped success."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys
import time
import threading

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import extract
import transport
import analyze
import exports
import layout_exports

spec=importlib.util.spec_from_file_location('preserved_probe',HERE.parent/'probe/capture.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
require,sha,write,parse,ordinary=base.require,base.sha,base.write,base.parse,base.ordinary
# Independently reviewed and published by the production source owner.
SOURCE={'repository':base.SOURCE['repository'],'commit':'bd5d9d87af76bfce0553d358bb3c6d45cbbc806a','tree':'4a84f4115cb0d95aa71c0be97d9ce4fdfb553fbc'}
SOURCE_SHA=extract.SOURCE_SHA256
BUILDER=base.BUILDER
APP_ID='org.sidestore.fixture.p1video'
METHODS={'timeout':'testProbeTimeoutPixels','replacement':'testProbeReplacementPixels','dismissal':'testProbeDismissalPixels'}
ADAPTERS={'ci/p0/source_primitives.py', 'ci/p1/video/analyze.py', 'ci/p1/video/test_intervals.py', 'ci/p1/video/capture.py', 'ci/p1/video/recovery_ui_tests.swift', 'ci/p1/video/intervals.py', 'ci/p1/video/test_v3_signin_screen_cleanup.py', 'ci/p1/video/test_capture.py', 'ci/p1/video/recovery.swift', 'ci/p1/video/ui_tests.swift', 'ci/p1/video/transport.py', 'ci/p1/video/host_build.py', 'ci/p1/video/test_host_build.py', 'ci/p1/video/app.swift', 'prepare_candidate_inventory.py', 'ci/p1/video/README.md', 'ci/p1/video/test_recovery_layout_source.py', 'ci/p1/video/exports.py', 'ci/p1/video/extract.py', 'ci/p0/native_gate.py', 'ci/p1/video/test_analyze.py', 'ci/p1/video/layout_exports.py', 'ci/p1/video/test_exports.py', 'ci/p1/video/test_extract.py', 'ci/p1/video/test_layout_exports.py', 'ci/p1/video/test_transport.py', 'ci/p1/video/decode.swift', 'ci/p0/inputs-sidestore.json', 'ci/p1/native_gate.py', 'ci/p1/probe/capture.py'}


def validate(host,inputs,approved):
    require(host.is_dir() and not host.is_symlink(),'linked/missing host root');host=host.resolve()
    require(re.fullmatch('[0-9a-f]{64}',approved or '') and sha(inputs)==approved,'unreviewed inputs')
    data=parse(inputs)
    require(set(data)=={'schema','scope','livecontainer','builder','source_sha256','adapter_files'},'unexpected input fields')
    require(data['schema']=='p1-external-video-inputs-v1' and data['scope']=='diagnostic-only-no-admission','wrong diagnostic identity')
    require(isinstance(SOURCE['commit'],str) and re.fullmatch('[0-9a-f]{40}',SOURCE['commit']),'source owner has not published a verified commit')
    require(data['livecontainer']==SOURCE and data['builder']==BUILDER and data['source_sha256']==SOURCE_SHA,'wrong source pin')
    require(set(data['adapter_files'])==ADAPTERS,'wrong sealed adapter inventory')
    for path,digest in data['adapter_files'].items():require(sha(ordinary(host,path))==digest,'adapter drift: '+path)
    return data


class Commands(base.Commands):
    def __init__(self,output):super().__init__(output);self.lock=threading.Lock()
    def __call__(self,*args,**kwargs):
        # A single XCTest command runs on the worker while simctl screenshots
        # execute on the driver thread. Give each its own retained command slot.
        with self.lock:
            self.count+=1;number=self.count
        child=base.Commands(self.output);child.renderer=self.renderer;child.count=number*1000
        return child(*args,**kwargs)


def prepare(source,builder,build,output):
    require(sha(source)==SOURCE_SHA,'actual source hash differs')
    renderer=base.module('video_signin_renderer',builder/'scripts/run_p0_signin_rendering.py')
    sources,hashes=renderer.extract_sources(source,builder/'scripts/templates')
    app=(builder/'tests/fixtures/p0_signin_app.swift').read_text()
    marker='@main @MainActor struct P0SignInApp: App';require(app.count(marker)==1,'baseline entry point drift')
    app=app.replace(marker,'@MainActor struct P0SignInApp: App')
    fragments=extract.fragments(source.read_text())
    recovery=extract.render(source.read_text(),(HERE/'recovery.swift').read_text())
    sources['p0_signin_app.swift']=app+'\n'+(HERE/'app.swift').read_text()+'\n'+recovery
    sources['p0_signin_ui_tests.swift']=(HERE/'ui_tests.swift').read_text()+'\n'+(HERE/'recovery_ui_tests.swift').read_text()
    target=build/'Sources';target.mkdir(parents=True)
    for name,text in sources.items():(target/name).write_text(text);hashes[name]=sha(target/name)
    project=build/'P0SignIn.xcodeproj';shutil.copytree(builder/'tests/fixtures/p0_signin_project',project)
    info=plistlib.loads((project/'Info.plist').read_bytes());info['LCBuilderCommit']=BUILDER['commit'];(project/'Info.plist').write_bytes(plistlib.dumps(info))
    pbx=project/'project.pbxproj';pbx.write_text(pbx.read_text().replace('org.sidestore.fixture.p0signin',APP_ID))
    shutil.copytree(target,output/'sources');shutil.copytree(project,output/'project')
    write(output/'source-identity.json',{'source':SOURCE,'source_sha256':SOURCE_SHA,'builder':BUILDER,
        'generated_sources_sha256':hashes,'fragments_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in fragments.items()},
        'instrumentation':'No production instrumentation; exact prompt and recovery helper/wrapper extraction',
        'scope':'synthetic lifecycle/status; diagnostic only','admissionEligible':False})
    return project,renderer


def read_events(root):
    require(root.is_dir() and not root.is_symlink(),'missing/linked raw events')
    files=sorted(root.glob('event-*.json'));require(0<len(files)<=200,'missing/unbounded events')
    rows=[]
    for i,path in enumerate(files,1):
        require(path.name==f'event-{i:03d}.json' and not path.is_symlink(),'stale/missing/linked journal event')
        rows.append(parse(path))
    require(not (root/'journal-error.txt').exists(),'journal reported failure')
    require({p.name for p in root.iterdir()}<={p.name for p in files}|{'request.json','response.json'},'unexpected raw journal member')
    return rows


def export_case(command,bundle,folder,scenario,device,valid_png):
    directory=folder/'attachments'
    command('xcrun','xcresulttool','export','attachments','--path',bundle,'--output-path',directory,timeout=120)
    summary=json.loads(command('xcrun','xcresulttool','get','test-results','summary','--path',bundle))
    tests=json.loads(command('xcrun','xcresulttool','get','test-results','tests','--path',bundle))
    write(folder/'xctest-summary.json',summary);write(folder/'xctest-tests.json',tests)
    base.inventory(directory)
    controls,inputs,names=exports.verify(directory,summary,tests,scenario,device,parse,ordinary,valid_png)
    write(folder/'export-verification.json',{'controls':controls,'input':inputs,'screenshots':names,'admissionEligible':False})
    return controls,inputs,names


def run_case(command,candidate,device,scenario,folder,valid_png):
    report={'scenario':scenario,'collection_complete':False,'conditional_feasibility':False,'admissionEligible':False,'errors':[]}
    folder.mkdir();video=None;future=None;root=None
    try:
        video=transport.Video(device,folder)
        with ThreadPoolExecutor(max_workers=1) as pool:
            bundle=folder/'tests.xcresult'
            future=pool.submit(command,'xcodebuild','test-without-building','-xctestrun',candidate,
                '-destination','id='+device,'-resultBundlePath',bundle,'-parallel-testing-enabled','NO',
                '-maximum-concurrent-test-simulator-destinations','1','-test-timeouts-enabled','YES',
                '-default-test-execution-time-allowance','240','-maximum-test-execution-time-allowance','240',
                '-only-testing:P0SignInUITests/P0SignInUITests/'+METHODS[scenario],timeout=360)
            root=None;deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                if future.done():future.result();raise ValueError('XCTest ended before fixture channel existed')
                container=Path(command('xcrun','simctl','get_app_container',device,APP_ID,'data',allow_failure=True))
                candidate_root=container/'Documents/p1-video'/scenario
                if candidate_root.is_dir():root=candidate_root;break
                time.sleep(.5)
            require(root is not None,'fixture channel was never created')
            channel=transport.Channel(root,folder,device,command)
            try:
                channel.await_event('start',10);channel.calibrate('pre');channel.request('ready')
                channel.await_event('window-end');channel.request('mid');channel.calibrate('mid');channel.request('third')
                channel.await_event('post-ready');channel.request('post');channel.calibrate('post');channel.request('finish')
                future.result(timeout=60)
            except Exception as error:report['errors'].append('interaction/calibration: '+str(error))
            finally:
                # A failed protocol must not leave an unrelated long-running
                # fixture interaction. Terminate only this disposable app.
                if report['errors'] and not future.done():
                    command('xcrun','simctl','terminate',device,APP_ID,allow_failure=True)
        if root is not None and root.exists():shutil.copytree(root,folder/'raw-events')
        video.stop();video=None
        controls,inputs,screenshots=export_case(command,bundle,folder,scenario,device,valid_png)
        events=read_events(folder/'raw-events')
        geometry=[r for r in events if r.get('type')=='marker-geometry'];require(geometry,'missing marker geometry')
        rect=geometry[-1]['rect'];points=geometry[-1]['screenPoints'];scale=geometry[-1]['scale']
        require(len(rect)==4 and len(points)==2 and all(base.number(v) and v>0 for v in points+[scale]),'invalid geometry')
        require(all(abs(a-b)<=1 for a,b in zip(rect,controls['markerFrame'])),'fixture marker differs from independent XCTest geometry')
        require(controls['copyHittable'] is True and controls['copyLabel']=='Copy Details','production Copy control unavailable')
        calibration=parse(folder/'calibration.json')
        decode_input={'video':str(folder/'screen.mp4'),'markerRectPixels':[v*scale for v in rect],
            'copyRectPixels':[v*scale for v in controls['copyFrame']],'pixelSize':[round(v*scale) for v in points],
            'screenshots':[{'id':r['id'],'path':str(folder/r['screenshot'])} for r in calibration['markers']],
            'independentScreenshots':[{'phase':phase,'path':path} for phase,path in screenshots.items()]}
        write(folder/'decode-input.json',decode_input)
        command('swift',HERE/'decode.swift',folder/'decode-input.json',folder/'decoded-frames',folder/'decoded.json',timeout=600)
        report['collection_complete']=not report['errors']
        try:
            report['feasibility']=analyze.inspect(calibration,parse(folder/'decoded.json'),events,scenario,inputs)
            report['conditional_feasibility']=True
        except Exception as error:report['feasibility_failure']=str(error)
    except Exception as error:report['errors'].append(str(error))
    finally:
        if not (folder/'raw-events').exists():
            try:
                container=Path(command('xcrun','simctl','get_app_container',device,APP_ID,'data'))
                partial=container/'Documents/p1-video'/scenario
                if partial.is_dir():shutil.copytree(partial,folder/'raw-events')
            except Exception as error:report['errors'].append('partial journal recovery: '+str(error))
        if video is not None:
            try:video.stop()
            except Exception as error:report['errors'].append('video finalization: '+str(error))
        write(folder/'collection-report.json',report)
    return report


def run_layout(command,candidate,device,folder,valid_png):
    folder.mkdir();report={'collection_complete':False,'admissionEligible':False,'errors':[]}
    bundle=folder/'tests.xcresult'
    try:
        try:
            command('xcodebuild','test-without-building','-xctestrun',candidate,'-destination','id='+device,
                '-resultBundlePath',bundle,'-parallel-testing-enabled','NO','-maximum-concurrent-test-simulator-destinations','1',
                '-test-timeouts-enabled','YES','-default-test-execution-time-allowance','600','-maximum-test-execution-time-allowance','600',
                *['-only-testing:P0SignInUITests/P1RecoveryLayoutUITests/'+m for m in layout_exports.METHODS],timeout=2400)
        except Exception as error:report['errors'].append('XCTest: '+str(error))
        if bundle.exists():
            directory=folder/'attachments'
            command('xcrun','xcresulttool','export','attachments','--path',bundle,'--output-path',directory,timeout=120)
            summary=json.loads(command('xcrun','xcresulttool','get','test-results','summary','--path',bundle))
            tests=json.loads(command('xcrun','xcresulttool','get','test-results','tests','--path',bundle))
            write(folder/'xctest-summary.json',summary);write(folder/'xctest-tests.json',tests);base.inventory(directory)
            report['validation']=layout_exports.verify(directory,summary,tests,device,parse,ordinary,valid_png)
            report['collection_complete']=not report['errors']
    except Exception as error:report['errors'].append(str(error))
    finally:write(folder/'collection-report.json',report)
    return report


def execute(host,work,output,inputs,approved):
    require(not work.exists() and not output.exists(),'fresh work/evidence required');work.mkdir(parents=True);output.mkdir(parents=True)
    result={'schema':'p1-video-diagnostic-collection-v1','admission_eligible':False,'production_ready':False,
        'full_native_lane_executed':False,'diagnostic_collection_complete':False,'conditional_feasibility':False,
        'source':SOURCE,'source_sha256':SOURCE_SHA,'approved_inputs_sha256':approved,'reports':[],'errors':[],
        'github':{k:os.environ.get(k) for k in ['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY']}}
    try:
        logs=output/'commands';logs.mkdir();bootstrap=base.bootstrap_commands(logs)
        builder,live=work/'builder',work/'LiveContainer';base.acquire(builder,BUILDER,bootstrap);base.acquire(live,SOURCE,bootstrap)
        runner=base.module('video_commands',builder/'scripts/run_issue25_rendering.py');runner.COMMAND_LOG=logs/'bounded-commands.jsonl'
        command=Commands(logs);command.renderer=runner
        shutil.copytree(HERE,output/'harness',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(inputs,output/'approved-inputs.json')
        write(output/'source-before.json',{'LiveContainer':base.checkout_proof(live,SOURCE,command),'builder':base.checkout_proof(builder,BUILDER,command)})
        write(output/'validation-host.json',{'commit':command('git','-C',host,'rev-parse','HEAD'),'tree':command('git','-C',host,'rev-parse','HEAD^{tree}'),'workflow_sha256':sha(host/'.github/workflows/p1-native-candidate.yml')})
        write(output/'toolchain.json',{'xcodebuild':command('xcodebuild','-version'),'swift':command('swift','--version'),
            'simulators':json.loads(command('xcrun','simctl','list','--json')),
            'recordVideo_help':command('xcrun','simctl','io','help',allow_failure=True)})
        project,renderer=prepare(live/base.SHELL,builder,work/'build',output)
        environment=os.environ.copy();environment['MAINTAINED_LIVE_CONTAINER_TEST_SOURCE']=str(live);environment['V3_P1_REQUIRED']='1'
        # Executed through env so the exact source path is retained in command log.
        command('env','MAINTAINED_LIVE_CONTAINER_TEST_SOURCE='+str(live),'P1_FROZEN_BUILDER_TEST_SOURCE='+str(builder),'V3_P1_REQUIRED=1',
            'python3','-B','-m','unittest','discover','-s',HERE,'-p','test_*.py','-v',timeout=120)
        command('xcodebuild','build-for-testing','-project',project,'-scheme','P0SignIn','-sdk','iphonesimulator',
            '-destination','generic/platform=iOS Simulator','-derivedDataPath',work/'build/DerivedData','-jobs','2',
            'CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO',timeout=600)
        products=work/'build/DerivedData/Build/Products';candidates=list(products.glob('*.xctestrun'));require(len(candidates)==1,'ambiguous xctestrun')
        apps=list(products.glob('Debug-iphonesimulator/P0SignIn.app'));require(len(apps)==1,'ambiguous fixture app')
        devices=runner.available_devices();require(len(devices)==2 and {d[0] for d in devices}=={'phone','tablet'},'exact device matrix required')
        write(output/'selected-devices.json',devices)
        for kind,device,runtime in devices:
            report={'device_class':kind,'simulator_udid':device,'runtime':runtime,'cases':[],'errors':[],'collection_complete':False};result['reports'].append(report)
            folder=output/kind;folder.mkdir();booted_here=False
            try:
                state=json.loads(command('xcrun','simctl','list','devices','--json'))
                booted=any(d['udid']==device and d['state']=='Booted' for group in state['devices'].values() for d in group)
                if not booted:command('xcrun','simctl','boot',device);booted_here=True
                command('xcrun','simctl','bootstatus',device,'-b',timeout=600)
                command('xcrun','simctl','uninstall',device,APP_ID,allow_failure=True)
                command('xcrun','simctl','install',device,apps[0])
                for scenario in METHODS:
                    report['cases'].append(run_case(command,candidates[0],device,scenario,folder/scenario,renderer.valid_png))
                report['layout']=run_layout(command,candidates[0],device,folder/'layout',renderer.valid_png)
                report['collection_complete']=all(r['collection_complete'] for r in report['cases']) and report['layout']['collection_complete']
            except Exception as error:report['errors'].append(str(error))
            finally:
                write(folder/'collection-report.json',report)
                if booted_here:command('xcrun','simctl','shutdown',device,allow_failure=True)
        write(output/'source-after.json',{'LiveContainer':base.checkout_proof(live,SOURCE,command),'builder':base.checkout_proof(builder,BUILDER,command)})
        require(sha(live/base.SHELL)==SOURCE_SHA,'source drift during capture')
        result['diagnostic_collection_complete']=len(result['reports'])==2 and all(r['collection_complete'] for r in result['reports'])
        result['conditional_feasibility']=result['diagnostic_collection_complete'] and all(c['conditional_feasibility'] for r in result['reports'] for c in r['cases'])
    except Exception as error:result['errors'].append(str(error))
    finally:
        write(output/'diagnostic-result.json',result)
        write(output/'evidence-index.json',{'schema':'p1-diagnostic-evidence-index-v1','files':{str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file() and p.name!='evidence-index.json'}})
    return result['diagnostic_collection_complete']

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--host-root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--work',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--execute',action='store_true')
    a=p.parse_args();validate(a.host_root,a.inputs,a.approved_inputs_sha256)
    if a.execute:
        require(a.work is not None and a.evidence is not None,'execution paths required')
        sys.exit(0 if execute(a.host_root.resolve(),a.work,a.evidence,a.inputs,a.approved_inputs_sha256) else 1)
