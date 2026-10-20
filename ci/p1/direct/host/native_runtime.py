"""Concrete retained native operations for the single timeout observer case.

This module uses the existing process/device owners. Final pixel/OCR analysis
is deliberately after writer settlement; case sequencing alone grants nothing.
"""
from pathlib import Path
from hashlib import sha256
import json,os,shutil,time
from functools import wraps
from fixture_channel import Directory,FixtureChannel,canonical,parse,require
from native_case import Evidence
from native_process import RetainedCommand,clean
from native_channels import Channels
from protocol_driver import Driver
from journal import Journal
import runner_recipe,artifact_budget
from helper_sample import Experiment

def bounded_preparation(method):
    @wraps(method)
    def wrapped(self,context,timeout):
        original=self.scope.deadline
        self.scope.deadline=min(original,time.monotonic()+timeout)
        if method.__name__=='start_capture_gui' and 'budget' in context:
            budget=context['budget'];end=budget['startSample']['hostBeforeNs']+budget['effectiveCommandBudgetNs']-80_000_000_000
            self.scope.deadline=min(self.scope.deadline,end/1e9)
        try:
            self.scope.persist()
            return method(self,context,timeout)
        finally:
            self.scope.deadline=original
            self.scope.persist()
    return wrapped

def bounded_cleanup(method):
    @wraps(method)
    def wrapped(self,context,timeout):
        require(type(timeout) in (int,float) and timeout>0,'cleanup stage allowance')
        original=self.scope.cleanup_deadline
        require(type(original) in (int,float),'explicit original cleanup reserve required')
        cutoff=min(original,time.monotonic()+timeout)
        if method.__name__ in ('stop_fixture','cleanup_device'):
            prior=getattr(self,'device_cleanup_deadline',None)
            if prior is None:self.device_cleanup_deadline=min(original,time.monotonic()+120)
            cutoff=min(cutoff,self.device_cleanup_deadline)
            if 'deviceCleanupDeadlineNs' in context:cutoff=min(cutoff,context['deviceCleanupDeadlineNs']/1e9)
            require(cutoff>time.monotonic(),'shared device cleanup reserve exhausted')
        self.scope.cleanup_deadline=cutoff
        try:return method(self,context,timeout)
        finally:self.scope.cleanup_deadline=original
    return wrapped

class Runtime:
    def __init__(self,*,scope,process_scope,capture,window_capture,fresh_device,project_setup,
                 video,local,work,output,source,builder,helper,session,clock,bridge,handoff):
        self.scope=scope;self.ps=process_scope;self.capture=capture;self.window=window_capture
        self.fresh=fresh_device;self.project_setup=project_setup;self.video=video;self.local=Path(local)
        self.work=Path(work);self.output=Path(output);self.source=Path(source);self.builder=Path(builder)
        self.helper_binary=Path(helper);self.session=session;self.clock=clock;self.bridge=bridge;self.handoff=handoff
        logs=self.output/'commands';logs.mkdir();self.command=self.ps.Commands(scope,logs)
        self.device=None;self.gui=None;self.native=None;self.helper=None;self.channels=None;self.journal=None
        self.capture_binding=None;self._evidence={};self.native_receipt=None
        self.clock_reader=clock.darwin_reader();self.transport=[];self.sampler=None
    def prepare_sample(self):
        self.sampler=Experiment(self.scope,self.ps,self.output,self.session,self.compiled.binary_sha256,self.compiled.binary_path)
        self.sampler.preflight()
        self.retain('helper-sample-preflight',canonical(self.sampler.row))
    def finish_sample(self,timeout):
        sampler=getattr(self,'sampler',None)
        if sampler is not None:return sampler.finish(timeout)
    def remaining(self,maximum,cleanup=False):
        if not cleanup:return self.scope.remaining(maximum)
        # A stage can contain several independently bounded Commands. Do not
        # mistake the ordinary per-command15s cap for its aggregate allowance.
        # Every actual command still uses unchanged Scope.remaining/owned cap.
        deadline=self.scope.cleanup_deadline
        require(type(deadline) in (int,float),'explicit cleanup deadline')
        left=deadline-time.monotonic();require(left>0,'cleanup reserve exhausted')
        return min(maximum,left)
    def retain(self,name,raw):
        require(type(name) is str and '/' not in name and type(raw) is bytes,'retained stage leaf/bytes')
        folder=self.output/'receipts';folder.mkdir(exist_ok=True)
        path=folder/(name+'.json')
        if path.exists():require(path.read_bytes()==raw,'immutable receipt changed');return
        with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    def persist(self,raw):self.ps.atomic(self.output/'case-sequence.json',parse(raw))
    def evidence(self,name,value,raw=None):
        raw=canonical(value) if raw is None else raw
        result=Evidence(raw,value);self._evidence[name]=result;return result
    def validate_stage(self,name,result,context):
        require(self._evidence.get(name) is result and context['session']==self.session,'foreign stage evidence')
        require((self.output/'receipts'/(name+'.json')).read_bytes()==result.raw,'stage retention mismatch')
    def checkpoint(self,context):
        if self.gui is not None:self.gui.live()
        # Completed native/helper commands are checked by their designated
        # completion stages; early completion must fail observation stages.
        stage=context.get('stage')
        if self.native is not None and stage not in ('await_native_result','await_strip_complete','send_stop','settle_helper','validate_collection'):
            self.native.live()
        if self.helper is not None and stage not in ('settle_helper','validate_collection'):
            self.helper.live()
    def start_sample(self,context):
        before=time.monotonic_ns();ticks,numer,denom=self.clock_reader();after=time.monotonic_ns()
        return dict(hostBeforeNs=before,hostAfterNs=after,machTicks=ticks,timebaseNumer=numer,timebaseDenom=denom)
    def prepare_service(self,name,*args):
        historical={'boot':30,'bootstatus':120,'install':120}
        require(name in historical and args[:3]==('xcrun','simctl',name),'exact preparation service')
        allowance=self.remaining(360)
        row=self.command(*args,timeout=allowance,receipt=True)
        timing=row.get('wait_timing',{});start=timing.get('command_started');end=timing.get('wait_finished')
        elapsed=end-start if type(start) in (int,float) and type(end) in (int,float) and end>=start else None
        self.retain('preparation-'+name,canonical({'schema':'p1-shared-preparation-service-v1',
            'session':self.session,'absoluteDeadline':self.scope.deadline,'allowanceSeconds':allowance,
            'historicalAllowanceSeconds':historical[name],'waitElapsedSeconds':elapsed,
            'historicalAllowanceExceeded':elapsed>historical[name] if elapsed is not None else None,
            'receipt':row,'infrastructureOnly':True,'admissionEligible':False}))
        return clean(row,args)
    @bounded_preparation
    def prepare(self,context,timeout):
        started=time.monotonic()
        def left(cap):
            value=min(cap,timeout-(time.monotonic()-started),self.remaining(cap));require(value>0,'preparation deadline');return value
        prepared=self.project_setup.prepare(self.source,self.builder,self.work/'build',self.output/'preparation',
                    video_dir=Path(self.video.__file__).parent,preflight_dir=Path(self.capture.__file__).parent,
                    local_dir=self.local,expected_sources=self.project_setup.source_hashes(self.source,self.builder,
                        video_dir=Path(self.video.__file__).parent,preflight_dir=Path(self.capture.__file__).parent,local_dir=self.local))
        self.command('xcodebuild','build-for-testing','-project',prepared.project,'-scheme','P0SignIn','-sdk','iphonesimulator',
                     '-destination','generic/platform=iOS Simulator','-derivedDataPath',self.work/'build/DerivedData','-jobs','2',
                     'CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO',timeout=left(360))
        products=self.work/'build/DerivedData/Build/Products'
        apps=list(products.glob('Debug-iphonesimulator/P0SignIn.app'));recipes=list(products.glob('*.xctestrun'))
        runners=list(products.glob('Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist'))
        require(len(apps)==len(recipes)==len(runners)==1,'unique built fixture/runner/recipe')
        raw,receipt=runner_recipe.configure(recipes[0].read_bytes(),runners[0].read_bytes(),self.session,self.capture.RUNNER_ID)
        target=products/'DirectTimeout.xctestrun';target.write_bytes(raw);self.retain('runner-recipe',receipt)
        # create_for_ui durably persists creation intent and exact new UUID
        # before boot; cleanup consults Scope even if this helper raises.
        proof=self.fresh.create_for_ui(self.scope,self.output/'created-device',device_class='phone')
        self.device=proof['device']
        self.prepare_service('boot','xcrun','simctl','boot',self.device)
        self.prepare_service('bootstatus','xcrun','simctl','bootstatus',self.device,'-b')
        self.retain('install-preparation',canonical(self.capture.prepare_install(self.command,self.device)))
        self.prepare_service('install','xcrun','simctl','install',self.device,apps[0])
        self.retain('inclusive-storage-plan',canonical(artifact_budget.preflight(self.output)))
        return self.evidence('prepare',dict(device=self.device,xctestrun=str(target.resolve()),resultBundle=str((self.output/'tests.xcresult').resolve())))
    def launch_native(self,context,timeout):
        self.scope.fixture_stopped(False)
        duration=min(360,self.remaining(360),(context['budget']['startSample']['hostBeforeNs']+context['budget']['effectiveCommandBudgetNs']-time.monotonic_ns())/1e9)
        require(duration>0,'native shared command deadline')
        self.native=RetainedCommand(self.scope,self.ps.Commands,self.output/'xctest-command',context['argv'],timeout=duration,
                                    retain=lambda raw:self.retain('native-command',raw));self.native.start()
        self.channels=Channels(self.command,self.native,device=self.device,session=self.session,app_id=self.video.APP_ID,
                               runner_id=self.capture.RUNNER_ID,retain=self.retain,remaining=lambda cap:self.observation_remaining(context,cap))
        return self.evidence('launch_native',{'argv':list(context['argv']),'timeoutSeconds':duration,'session':self.session})
    def await_started(self,context,timeout):return self.evidence('await_started',self.channels.started(timeout))
    @bounded_preparation
    def start_capture_gui(self,context,timeout):
        hint=self.channels.hint
        require(hint is not None,'method hint before capture GUI')
        self.native.live()
        # Fresh isolation is deliberately after startup discovery and geometry.
        # The one retained XCTest writer is the only permitted live predecessor.
        self.window.startup_isolation(self.command,self.work/'capture-prerequisites',self.output)
        self.native.live();process=self.native.process
        require(self.native.scope is self.scope and process is not None and
                tuple(context['argv'])==self.native.argv,'exact native GUI predecessor')
        with process.lock:
            self.native.live()
            require(process.poll() is None,'native exited before launch receipt handoff')
            require(process.launch is not None,'native launch receipt missing')
            process.launch.finish();process.launch.require()
        self.gui=self.window.OwnedGUI(self.scope,self.device,self.output/'gui',
                                     active_writer=process,active_argv=self.native.argv)
        self.gui.start();self.native.live()
        self.retain('deferred-gui-start',canonical({'schema':'p1-pre-capture-gui-start-v1',
            'session':self.session,'device':self.device,'nativePID':process.pid,
            'nativeArgv':list(self.native.argv),'nativeLaunch':process.launch.row,
            'hint':hint,'guiPID':self.gui.process.pid,'admissionEligible':False}))
    def discover_app(self,context,timeout):return self.evidence('discover_app',self.channels.discover('app',timeout))
    def discover_runner(self,context,timeout):return self.evidence('discover_runner',self.channels.discover('runner',timeout))
    def observation_remaining(self,context,maximum):
        budget=context['budget'];end=budget['startSample']['hostBeforeNs']+budget['effectiveCommandBudgetNs']-80_000_000_000
        value=min(self.remaining(maximum),(end-time.monotonic_ns())/1e9)
        require(value>0,'shared observation deadline');return value
    def retain_journal(self,row):
        folder=self.output/'app-journal';folder.mkdir(exist_ok=True);path=folder/row['file']
        if path.exists():require(path.read_bytes()==row['bytes'],'retained journal changed')
        else:
            with path.open('xb') as f:f.write(row['bytes']);f.flush();os.fsync(f.fileno())
    def await_geometry(self,context,timeout):
        request=self.channels.geometry(timeout,self.handoff.validate_request)
        self.journal=Journal(self.channels.directories['app'],checkpoint=lambda:self.checkpoint(context),
            remaining=lambda cap:self.observation_remaining(context,cap),retain=self.retain_journal)
        return self.evidence('await_geometry',request)
    def start_helper(self,context,timeout):
        self.start_capture_gui(context,self.observation_remaining(context,timeout))
        frame_path=(self.output/'direct-frames').resolve()
        self.capture_target=self.capture_module.prepare_capture_target(frame_path)
        self.host_capture_sources=self.capture_module.source_hashes();self.bridge_sources=self.bridge.source_hashes()
        self.retain('host-capture-sources',canonical(self.host_capture_sources));self.retain('bridge-sources',canonical(self.bridge_sources))
        budget=context['budget'];duration=min(360,self.remaining(360),
            (budget['startSample']['hostBeforeNs']+budget['effectiveCommandBudgetNs']-time.monotonic_ns())/1e9)
        argv=[str(self.helper_binary),str(self.gui.process.pid),self.window.SIMULATOR,str(frame_path),self.session,
              str(budget['observationDeadlineMach']),str(budget['cleanupDeadlineMach'])]
        self.helper=RetainedCommand(self.scope,self.ps.Commands,self.output/'helper-command',argv,timeout=duration,
                                   retain=lambda raw:self.retain('helper-command',raw));self.helper.start()
        self.capture_binding=self.capture_module.CaptureHandoff(scope=self.scope,gui=self.gui,helper=self.helper,
            compiled=self.compiled,target=self.capture_target,frame_path=frame_path,channels=self.channels,
            geometry_request_bytes=self.channels.geometry_bytes,runner_directory=self.channels.directories['runner'],journal=self.journal,
            budget=budget,bridge=self.bridge,window_capture=self.window,
            remaining=lambda cap:self.observation_remaining(context,cap),retain=self.retain,
            expected_bridge_sources=self.bridge_sources,expected_host_sources=self.host_capture_sources)
        return self.evidence('start_helper',{'argv':argv,'timeoutSeconds':duration,'session':self.session})
    def register_baseline(self,context,timeout):
        raw=self.capture_binding.register_baseline(timeout);return self.evidence('register_baseline',parse(raw),raw)
    def publish_roi(self,context,timeout):
        if self.sampler is not None:
            self.sampler.start(self.helper,deadline=time.monotonic()+self.observation_remaining(context,8))
        raw=self.capture_binding.publish_roi(timeout);return self.evidence('publish_roi',parse(raw),raw)
    def await_first(self,context,timeout):
        raw=self.capture_binding.await_first(timeout);return self.evidence('await_first',parse(raw),raw)
    def promote_first(self,context,timeout):
        raw=self.capture_binding.promote_first(timeout);return self.evidence('promote_first',parse(raw),raw)
    def publish_ack(self,context,timeout):
        raw=self.capture_binding.publish_ack(timeout);return self.evidence('publish_ack',parse(raw),raw)
    def send_stop(self,context,timeout):
        require(self.native_receipt is not None and self.final_journal is not None,'native and strip completion before stop')
        row={'schema':'p1-direct-stop-v1','session':self.session,
             'geometrySHA256':sha256(self.channels.geometry_bytes).hexdigest(),'kind':'protocol-finished'}
        self.capture_target.stop_channel.publish('request.json',canonical(row));return self.evidence('send_stop',row)
    @bounded_cleanup
    def settle_helper(self,context,timeout):
        receipt=self.helper.result(timeout);return self.evidence('settle_helper',receipt)
    @bounded_cleanup
    def validate_collection(self,context,timeout):
        frames=self.capture_binding.frames;raw=frames.read('window-capture.json',32*1024*1024)
        require(raw is not None,'helper final result missing');row=parse(raw)
        require(row.get('session')==self.session and all(row.get(k) is True for k in
            ('captureCompleted','streamStopped','outputDetached','finalContextRetained','windowRevalidationPassed')) and
            not any(k in row for k in ('error','stopError','detachError')),'capture failed final settlement')
        require(row.get('ownerPID')==self.gui.process.pid and row.get('windowID')==self.capture_binding.window_identity['windowID'],
                'final capture owner/window binding')
        # Full census, pixels, source/clock/geometry and OCR replay occur only
        # after exact owned resource cleanup; this is collection hygiene.
        return self.evidence('validate_collection',row,raw)
    def make_driver(self,context,checkpoint,remaining):
        directory=self.channels.directories['app']
        def retain_transport(row):
            self.transport.append(row)
            raw=dict(row)
            for key,value in list(raw.items()):
                if type(value) is bytes:raw[key]={'hex':value.hex(),'sha256':sha256(value).hexdigest()}
            self.retain('exchange-%03d'%row['id'],canonical(raw))
        channel=FixtureChannel(directory,checkpoint=checkpoint,remaining=remaining,retain=retain_transport)
        require(self.journal is not None,'registration journal must be reused')
        self.journal.checkpoint=checkpoint;self.journal.remaining=remaining
        identity={'session':self.session,'simulatorUDID':self.device,'hostPID':os.getpid(),
                  'appContainerReceiptSHA256':sha256(canonical(self.channels.receipts['app'])).hexdigest(),
                  'sourceSHA256':self.video.SOURCE_SHA}
        return Driver(identity=identity,exchange=channel.exchange,await_event=self.journal.await_event,
                      sample_mach=lambda phase,ordinal:self.clock.sample(phase,ordinal,self.clock_reader,time.monotonic_ns),
                      checkpoint=checkpoint,persist=lambda row:self.ps.atomic(self.output/'protocol.json',row))
    def await_native_result(self,context,timeout):
        self.protocol=context['protocol']
        self.native_receipt=self.native.result(timeout);return self.evidence('await_native_result',self.native_receipt)
    def await_strip_complete(self,context,timeout):
        require(self.native_receipt is not None,'native writer must settle before final journal')
        self.final_journal=self.journal.finalized()
        return self.evidence('await_strip_complete',self.final_journal['strip']['complete'])
    @bounded_cleanup
    def settle_native(self,context,timeout):
        return self.evidence('settle_native',self.native.stop(timeout) if self.native else {'started':False,'settled':True})
    @bounded_cleanup
    def stop_helper(self,context,timeout):
        deadline=min(time.monotonic()+timeout,self.scope.cleanup_deadline);diagnostic_error=None
        try:self.finish_sample(min(3,max(0,deadline-time.monotonic())))
        except Exception as error:diagnostic_error=error
        # An optional diagnostic failure must never skip original helper cleanup.
        result=self.helper.stop(max(0,deadline-time.monotonic())) if self.helper else {'started':False,'settled':True}
        if diagnostic_error is not None:raise diagnostic_error
        return self.evidence('stop_helper',result)
    @bounded_cleanup
    def stop_gui(self,context,timeout):
        if self.gui is not None:self.gui.stop()
        return self.evidence('stop_gui',{'guiStarted':self.gui is not None,'settled':self.gui is None or self.gui.stopped})
    @bounded_cleanup
    def stop_fixture(self,context,timeout):
        proof=(self.scope.fixture or {}).get('owned_created')
        if proof is not None:
            self.device=proof['device']
            if self.gui is not None and self.gui.stopped:self.window.observe_after_gui_stop(self.command,self.gui,self.device,self.output)
            if not self.scope.fixture.get('stopped'):self.fresh.stop_owned(self.command,self.device,self.output,direct_deadline=True)
        return self.evidence('stop_fixture',dict(self.scope.fixture or {}))
    @bounded_cleanup
    def cleanup_device(self,context,timeout):
        proof=(self.scope.fixture or {}).get('owned_created')
        if proof is not None:
            folder=self.output/'created-cleanup';folder.mkdir()
            command=self.fresh.Commands(self.scope,folder,proof)
            result=self.fresh.cleanup(command,proof,lambda:all(r.get('settled') is True for r in self.scope.rows))
            self.scope.fixture_deleted(result['deleted'])
            self.scope.fixture_stopped(result['observed_shutdown'] or result.get('deleted') is True)
            self.retain('owned-simulator-shutdown',canonical(result))
            if result['command_failed']:self.scope.fixture_cleanup_failure()
            require(result.get('deleted') is True and not result['command_failed'],'exact-created cleanup failed')
        return self.evidence('cleanup_device',dict(self.scope.fixture or {}))
    @bounded_cleanup
    def verify_cleanup(self,context,timeout):
        sampler=getattr(self,'sampler',None)
        require(sampler is None or sampler.thread is None or not sampler.thread.is_alive(),'diagnostic writer remains')
        require(all(r.get('settled') is True for r in self.scope.rows),'owned host writers remain')
        fixture=self.scope.fixture or {}
        if fixture.get('owned_created') is not None:require(fixture.get('deleted') is True,'created device deletion unproved')
        require(not fixture.get('cleanup_command_failed'),'cleanup failure remains latched')
        require(self.scope.creation_intent is None or fixture.get('owned_created') is not None,'unknown create outcome remains unresolved')
        if self.capture_binding is not None:self.capture_binding.close()
        elif hasattr(self,'capture_target'):
            for name in ('frames','roi_channel','stop_channel','parent'):getattr(self.capture_target,name).close()
        if self.channels is not None:self.channels.close()
        return self.evidence('verify_cleanup',{'allWritersSettled':True,'fixture':dict(fixture),'admissionEligible':False})
