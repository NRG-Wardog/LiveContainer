"""Bounded owned-window feasibility only; no P1 timing acceptance."""
import argparse
import hashlib
import json
import math
import stat
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid
import capture
import capture_prerequisites
import fresh_device
import process_scope

HERE=Path(__file__).resolve().parent
SIMULATOR='/Applications/Xcode_26.4.1.app/Contents/Developer/Applications/Simulator.app/Contents/MacOS/Simulator'

def require(value,message):
    if not value:raise ValueError(message)

class OwnedGUI:
    def __init__(self,scope,device,folder):
        fresh_device.validate(scope.fixture.get('owned_created'),scope.session,device)
        require(all(row.get('settled') is True for row in scope.rows),'pre-GUI writers unsettled')
        self.scope=scope;self.folder=folder;self.process=None;self.file=None;self.launch=None;self.stopped=False
        folder.mkdir();self.argv=[SIMULATOR,'-CurrentDeviceUDID',device]
        self.file=(folder/'gui.log').open('xb')
    def start(self):
        scope=self.scope
        try:
            timeout=scope.remaining(15);self.launch=process_scope.LaunchReceipt(1,time.monotonic()+timeout,timeout)
            self.process=scope.spawn(self.argv,self.file,launch=self.launch)
            while time.monotonic()<self.launch.deadline and not self.launch.row['eof']:
                self.launch.observe()
                require(self.process.poll() is None,'GUI exited before ownership observation')
                time.sleep(.02)
            self.launch.finish();self.launch.require()
            require(self.launch.row['exec_failure'] is None and self.launch.row['eof'],'GUI execution failed')
            self.live()
        finally:self.record()
    def live(self):
        require(self.process is not None and self.process.poll() is None,'registered GUI exited or delegated')
        require(self.scope.processes.get(self.process.pid) is self.process,'GUI ownership lost')
        row=[r for r in self.scope.rows if r['pid']==self.process.pid]
        require(len(row)==1 and row[0]['argv']==self.argv and row[0]['settled'] is False,'GUI registry mismatch')
    def record(self):
        process_scope.atomic(self.folder/'gui-owner.json',{'schema':'p1-owned-simulator-gui-v1','argv':self.argv,
            'pid':self.process.pid if self.process else None,'launch_receipt':self.launch.row if self.launch else None,
            'stopped':self.stopped,'admissionEligible':False})
    def stop(self):
        if self.stopped:return
        primary=None
        try:
            if self.process is not None:
                if self.process.signal_owned(signal.SIGTERM):self.process.wait(timeout=self.scope.remaining(10,cleanup=True))
        except Exception as error:primary=error
        finally:
            try:
                if self.process is not None:self.scope.settle(self.process)
                self.stopped=True
            except Exception as error:
                if primary is None:primary=error
            if self.file is not None:self.file.close()
            self.record()
        if primary is not None:raise primary

def startup_isolation(command,preflight,output):
    # One prospective startup observation; no retry and no timing admission.
    row=command(preflight,timeout=30,receipt=True)
    timing=row.get('wait_timing',{});start=timing.get('command_started');end=timing.get('wait_finished')
    elapsed=end-start if type(start) in (int,float) and type(end) in (int,float) and math.isfinite(start) and math.isfinite(end) and end>=start else None
    capture.write(output/'startup-isolation-timing.json',{'allowance_seconds':30,'historical_allowance_seconds':10,
        'wait_elapsed_seconds':elapsed,'historical_10s_exceeded':elapsed>10 if elapsed is not None else None,
        'exit_code':row.get('exit_code'),'failure_type':row.get('failure_type'),'cleanup_errors':row.get('cleanup_errors'),
        'wait_timing':timing,'launch_receipt':row.get('launch_receipt'),'infrastructure_only':True,'admissionEligible':False})
    launch=row.get('launch_receipt',{})
    require(row.get('writer_settled') is True and not row.get('cleanup_errors'),'isolation writer unsettled')
    require(launch.get('state')=='pre-exec-observed' and launch.get('closed') is True and launch.get('eof') is True and launch.get('exec_failure') is None,'isolation execution unknown')
    require(row.get('exit_code')==0 and row.get('failure_type') is None,'startup isolation command failed')
    check=json.loads(row.get('stdout',''))
    require(capture_prerequisites.validate_result(check) and check['screenCapturePreflight'] and check['simulatorProcessCount']==0 and check['simulatorOnScreenWindowCount']==0,'GUI isolation changed')
    return check

def await_fixture_ready(command,device,session,output):
    # One exact APP_ID discovery after launch, then ordinary bounded file polling.
    root=capture.container(command,device,capture.APP_ID,timeout=30,startup_timing=output/'fixture-startup-discovery.json')
    require(root is not None,'fixture data container unavailable')
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root and not root.is_symlink(),'untrusted fixture container root')
    relative='Documents/p1-window/'+session+'/ready.json'
    deadline=min(command.scope.deadline,time.monotonic()+10)
    while time.monotonic()<deadline:
        path=root/relative
        if path.exists() or path.is_symlink():
            raw=bounded_file(root,relative,4096);row=json.loads(raw)
            require(set(row)=={'schema','session','marker','drawBeforeUptime','drawAfterUptime','clock','displayTimeEstablished','admissionEligible'},'unexpected readiness fields')
            require(row.get('schema')=='p1-window-fixture-ready-v1' and row.get('session')==session and type(row.get('marker')) is int and row['marker']==1,'fixture readiness identity mismatch')
            require(row['clock']=='app-process-systemUptime' and row['displayTimeEstablished'] is False and row['admissionEligible'] is False,'readiness scope differs')
            before=row.get('drawBeforeUptime');after=row.get('drawAfterUptime')
            require(type(before) in (int,float) and type(after) in (int,float) and math.isfinite(before) and math.isfinite(after) and 0<=before<=after,'invalid readiness draw bracket')
            capture.write(output/'fixture-readiness.json',row);return row
        time.sleep(min(.1,max(0,deadline-time.monotonic())))
    raise TimeoutError('fixture first-draw readiness missing')


def prepare(source,builder,build,output):
    import window_fixture_route
    project,renderer=capture.prepare(source,builder,build,output)
    app=build/'Sources/p0_signin_app.swift';text=app.read_text();original=(HERE/'app.swift').read_text()
    require(text.count(original)==1,'fixture replacement boundary differs')
    replacement=window_fixture_route.proposed_source(original)+'\n'+(HERE/'window_fixture.swift').read_text()
    app.write_text(text.replace(original,replacement))
    shutil.copy2(app,output/'sources/p0_signin_app.swift')
    identity=capture.parse(output/'source-identity.json')
    identity.update(scope='owned window nonce fixture only; no production UI acceptance',generated_sources_sha256={p.name:capture.sha(p) for p in sorted((build/'Sources').iterdir()) if p.is_file()})
    capture.write(output/'source-identity.json',identity)
    return project,renderer

def bounded_file(folder,name,limit):
    path=capture.ordinary(folder,name)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'pixel file bound exceeded')
        with os.fdopen(fd,'rb') as stream:
            fd=None;data=stream.read(limit+1)
        require(len(data)<=limit,'pixel file grew beyond bound');return data
    finally:
        if fd is not None:os.close(fd)


def validate_frames(folder,expected_pid,session):
    import window_bgra
    report=capture.parse(folder/'window-capture.json')
    require(report.get('schema')=='p1-owned-window-acquisition-v1' and report.get('ownerPID')==expected_pid and report.get('executable')==SIMULATOR,'capture owner mismatch')
    for key in ('captureCompleted','streamStopped','startAttempted','outputDetached','windowRevalidationPassed'):require(report.get(key) is True,'capture lifecycle incomplete')
    for key in ('error','stopError','detachError'):require(key not in report,'capture failure retained')
    for key in ('admissionEligible','calibrationFeasible','feedbackLifetimeEstablished','inputOverlapEstablished','guestPresentationEquivalenceEstablished','permissionRequested'):require(report.get(key) is False,'scope changed')
    require(not (folder/'stage-timeout.json').exists(),'native stage timed out')
    numer=report.get('timebaseNumerator');denom=report.get('timebaseDenominator')
    require(type(numer) is int and 0<numer<2**32 and type(denom) is int and 0<denom<2**32,'invalid timebase')
    samples=report.get('samples',{});rows=samples.get('frames')
    require(isinstance(rows,list) and 2<=len(rows)<=600 and samples.get('error') is None and samples.get('overflowRecords')==0 and samples.get('deliveredRecords')==len(rows),'incomplete frame census')
    decoded=[];last=0;geometry=None;total=0;last_marker=0;started_seen=False;stopped_seen=False
    for index,row in enumerate(rows):
        require(row.get('index')==index and 'error' not in row,'failed frame or index drift')
        require(not stopped_seen,'frame after stopped')
        name=row.get('statusName')
        if name in ('started','stopped','idle'):
            require(row.get('newFrame') is False,'lifecycle record used as new frame')
            require(row.get('status')=={'idle':1,'started':4,'stopped':5}[name],'status name/value differs')
            if name=='started':require(not started_seen and not decoded,'misordered started frame');started_seen=True
            if name=='stopped':stopped_seen=True
            continue
        require(name=='complete' and row.get('status')==0 and row.get('newFrame') is True,'unsupported frame status')
        ticks=row.get('displayTimeMach');require(type(ticks) is int and last<ticks<2**64,'invalid timestamp ordering');last=ticks
        width,height,stride=(row.get(k) for k in ('width','height','bytesPerRow'))
        require(all(type(x) is int for x in (width,height,stride)) and 0<width<=2048 and 0<height<=2048 and width*4<=stride<=16384,'invalid pixel geometry')
        rect=row.get('contentRect');scale=row.get('contentScale');factor=row.get('scaleFactor')
        require(isinstance(rect,list) and len(rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect) and rect[2]>0 and rect[3]>0,'invalid content rectangle')
        require(all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (scale,factor)),'invalid scale')
        current=(width,height,stride,rect,scale,factor)
        require(geometry is None or current==geometry,'frame geometry changed');geometry=current
        require(row.get('rawPixels')==f'frame-{index:04d}.bgra' and row.get('png')==f'frame-{index:04d}.png','unexpected pixel path')
        raw=bounded_file(folder,row['rawPixels'],32*1024*1024);png=bounded_file(folder,row['png'],32*1024*1024)
        require(len(raw)==stride*height==row.get('copiedBytes') and hashlib.sha256(raw).hexdigest()==row.get('rawPixelSHA256') and hashlib.sha256(png).hexdigest()==row.get('pngSHA256'),'pixel hash/layout mismatch')
        total+=len(raw);require(total<=256*1024*1024,'pixel ceiling exceeded')
        value=window_bgra.locate_bgra(raw,width,height,stride,session)
        require(value['marker']>=last_marker,'visual marker regressed');last_marker=value['marker']
        decoded.append({'index':index,'displayTimeMach':ticks,'displayTimeNumerator':ticks*numer,'displayTimeDenominator':denom*1_000_000_000,**value})
    require(len(decoded)>=2 and samples.get('completeFrames')==len(decoded) and samples.get('copiedBytes')==total,'complete-frame census mismatch')
    require(decoded[-1]['marker']>decoded[0]['marker'],'static-only nonce frames')
    return {'schema':'p1-owned-window-pixel-proof-v1','frames':decoded,'ownedWindowTimestampAcquisitionEstablished':True,
        'calibrationFeasible':False,'feedbackLifetimeEstablished':False,'inputOverlapEstablished':False,'admissionEligible':False}

def execute(host,work,output,inputs,approved):
    capture.validate(host,inputs,approved)
    require(capture.parse(inputs)['scope']=='owned-window-acquisition-only-no-admission','wrong sealed scope')
    require(not work.exists() and not output.exists(),'fresh paths required');work.mkdir(parents=True);output.mkdir(parents=True)
    scope=process_scope.Scope(output,phone_ui=True);logs=output/'commands';logs.mkdir();command=process_scope.Commands(scope,logs)
    result={'schema':'p1-owned-window-collection-v1','scope':'owned-window-acquisition-only','collection_complete':False,'capabilities_passed':False,
        'ownedWindowTimestampAcquisitionEstablished':False,'calibration_feasible':False,'feedback_lifetime_established':False,'input_overlap_established':False,'admissionEligible':False,'errors':[]}
    gui=None;device=None;booted=False
    try:
        shutil.copytree(HERE,output/'harness',ignore=shutil.ignore_patterns('__pycache__'));shutil.copy2(inputs,output/'approved-inputs.json')
        result['github']={k:os.environ.get(k) for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY')}
        result['workflowSHA256']=capture.sha(host/'.github/workflows/p1-native-candidate.yml')
        require(os.environ.get('ImageVersion')=='20261013.0424.1','pinned image differs')
        version=command('xcodebuild','-version',timeout=5);require(version.strip()=='Xcode 26.4.1\nBuild version 17E202','pinned Xcode differs');result['xcodeVersion']=version
        sdk=command('xcrun','--sdk','macosx','--show-sdk-path',timeout=10).strip()
        header=json.loads(command(os.sys.executable,'-B',HERE/'capture_prerequisites.py','--header-only',sdk,timeout=5))
        require(header['headerSHA256']=='025ce72289d842191571495dfc98ba1f5fec0c00b77ed598ab7cc765a649e9aa','reviewed SDK header differs');result['sdk']=header
        preflight=work/'capture-prerequisites';helper=work/'window-capture'
        command('xcrun','swiftc',HERE/'capture_prerequisites.swift','-o',preflight,timeout=30)
        check=json.loads(command(preflight,timeout=10));result['prerequisites']=check
        require(capture_prerequisites.validate_result(check) and check['screenCapturePreflight'] and check['simulatorProcessCount']==0 and check['simulatorOnScreenWindowCount']==0,'existing permission or isolated GUI prerequisite absent')
        command('xcrun','swiftc','-swift-version','5','-parse-as-library',HERE/'window_capture.swift','-o',helper,timeout=60)
        builder=work/'builder';live=work/'LiveContainer';capture.base.acquire(builder,capture.BUILDER,command);capture.base.acquire(live,capture.SOURCE,command)
        capture.write(output/'source-before.json',{'LiveContainer':capture.base.checkout_proof(live,capture.SOURCE,command),'builder':capture.base.checkout_proof(builder,capture.BUILDER,command)})
        project,_=prepare(live/capture.base.SHELL,builder,work/'build',output)
        command('xcodebuild','build-for-testing','-project',project,'-scheme','P0SignIn','-sdk','iphonesimulator','-destination','generic/platform=iOS Simulator','-derivedDataPath',work/'build/DerivedData','-jobs','2','CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO',timeout=360)
        apps=list((work/'build/DerivedData/Build/Products').glob('Debug-iphonesimulator/P0SignIn.app'));require(len(apps)==1,'ambiguous fixture app')
        proof=fresh_device.create_for_ui(scope,output/'created-device',device_class='phone');device=proof['device'];booted=True
        command('xcrun','simctl','boot',device,timeout=30);command('xcrun','simctl','bootstatus',device,'-b',timeout=120)
        capture.write(output/'install-preparation.json',capture.prepare_install(command,device))
        command('xcrun','simctl','install',device,apps[0],timeout=120)
        # Recheck immediately before creating GUI ownership; no unrelated GUI is accepted.
        result['startupPrerequisites']=startup_isolation(command,preflight,output)
        gui=OwnedGUI(scope,device,output/'gui');gui.start()
        session=uuid.uuid4().hex;result['visualSession']=session
        command('xcrun','simctl','launch',device,capture.APP_ID,'--window-capture-fixture','--session',session,timeout=30)
        await_fixture_ready(command,device,session,output)
        gui.live();frames=output/'window-frames';frames.mkdir()
        command(helper,str(gui.process.pid),SIMULATOR,frames,timeout=90)
        gui.live();proof=validate_frames(frames,gui.process.pid,session);capture.write(output/'pixel-proof.json',proof)
        capture.write(output/'source-after.json',{'LiveContainer':capture.base.checkout_proof(live,capture.SOURCE,command),'builder':capture.base.checkout_proof(builder,capture.BUILDER,command)})
        require(capture.parse(output/'source-before.json')==capture.parse(output/'source-after.json'),'source drift')
        result['collection_complete']=True;result['ownedWindowTimestampAcquisitionEstablished']=True
    except Exception as error:result['errors'].append(process_scope.error_info(error))
    finally:
        if gui is not None:
            try:gui.stop()
            except Exception as error:result['errors'].append(process_scope.error_info(error));result['collection_complete']=False
        capture.finalize(output,result,command,scope,device,booted)
        result['ownedWindowTimestampAcquisitionEstablished']=result['ownedWindowTimestampAcquisitionEstablished'] and result['collection_complete'] and not result['errors']
        capture.write(output/'capability-result.json',result)
        capture.write(output/'window-acquisition-result.json',result)
    return result['ownedWindowTimestampAcquisitionEstablished']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--host-root',type=Path,required=True);p.add_argument('--work',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True);a=p.parse_args()
    raise SystemExit(0 if execute(a.host_root.resolve(),a.work,a.evidence,a.inputs,a.approved_inputs_sha256) else 1)
