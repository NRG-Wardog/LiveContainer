"""Concrete live owned-helper prerequisites for one pre-baseline handoff.

No native execution occurs on import. All byte/schema checks are prerequisites,
not native source-locality, presentation, final collection, or P1 admission.
Only original owned process/launch objects authorize live reads/publication.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import math
import os
import stat
import time
import uuid

import case_budget
import native_process
import native_channels
import native_case
from fixture_channel import Directory, canonical, parse, require
from journal import Journal

LOCAL=Path(__file__).resolve().parents[1]
PREFLIGHT=LOCAL.parent/'window-capture-candidate/ci/p1/preflight'
PINNED={
    'window_capture.py':'c8363863260846117925ece24261906689a79bf97e7bf562986deecdc391c42e',
    'process_scope.py':'c13e02ee01b7429dc4f1c2026316f71cef6ac7728531ca62a64cfc3fbdf8b623',
    'fresh_device.py':'238bbc1d51792053cb1f3686cf03f52462412ead5b9e3b285f3e515183fd18d7',
    'launch_gate.py':'b3aa49fae2fd162437bc46e16550877e79642c04a929a715f5c2ebe1651469db',
    'minimal_gate.py':'4220957d328181502e574bf24002d25044b22f71166a64cde606a946522a61d8'}
SOURCES=(Path(__file__),Path(native_process.__file__),LOCAL/'host/fixture_channel.py',LOCAL/'host/journal.py',
         Path(case_budget.__file__),Path(native_channels.__file__),Path(native_case.__file__),*(PREFLIGHT/name for name in PINNED),
         *(LOCAL/'capture'/name for name in ('direct_capture.swift','assembly-binding.json','assemble.py',
             'build_main.py','build_sink.py','direct_main.swift','direct_sink.swift','roi_capture.swift','session_io.swift','window_resize.swift')))


def source_hashes():
    return {str(path.relative_to(LOCAL.parent)):sha256(path.read_bytes()).hexdigest() for path in SOURCES}


def exact(value,keys):
    require(type(value) is dict and set(value)==set(keys),'unexpected or missing native evidence fields')
    return value


def integer(value,lo=0,hi=2**64-1):
    require(type(value) is int and lo<=value<=hi,'bounded exact native integer')
    return value


def rectangle(value):
    require(type(value) is list and len(value)==4 and all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=65536 for v in value)
            and value[2]>0 and value[3]>0,'bounded nonempty native window rectangle')
    return value


def read_path(path,limit):
    path=Path(path)
    require(path.is_absolute() and path.parent.resolve()==path.parent,'canonical evidence parent required')
    directory=Directory(path.parent)
    try:
        raw=directory.read(path.name,limit);require(raw is not None,'required evidence file missing');return raw
    finally:directory.close()


@dataclass(frozen=True)
class CompiledHelper:
    scope: object
    process: object
    source_path: Path
    binary_path: Path
    source_sha256: str
    binary_sha256: str
    compile_receipt_bytes: bytes
    proof_bytes: bytes
    observed_after_ns: int


def _compile_allowance(receipt,launch):
    """Validate the original owned limit without subtracting rounded clocks.

    Commands computes min(started + limit, scope.deadline). Across a binary64
    exponent boundary, subtracting started from that rounded sum can exceed
    limit by one input ULP. The original LaunchReceipt retains limit directly;
    use it, and the producer's same addition, with no tolerance or extra time.
    """
    started=receipt.get('wait_timing',{}).get('command_started')
    deadline=receipt['launch_receipt'].get('deadline');limit=launch.timeout
    require(all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (started,deadline,limit,launch.deadline)) and
            limit<=60 and deadline==launch.deadline and started<deadline<=started+limit,
            'bounded original compile allowance')
    return dict(configuredTimeoutSeconds=limit,recordedStartedHostMonotonic=started,recordedDeadlineHostMonotonic=deadline)


def bind_compilation(source_path,binary_path,compile_receipt_bytes,*,scope,expected_source_sha256):
    """Call after the actual retained swiftc receipt, before starting the helper."""
    source=Path(source_path);binary=Path(binary_path)
    require(source==LOCAL/'capture/direct_capture.swift','exact assembled helper source required')
    require(type(compile_receipt_bytes) is bytes and 0<len(compile_receipt_bytes)<=1024*1024,'bounded exact compile receipt bytes')
    argv=['xcrun','swiftc','-swift-version','5','-parse-as-library',str(source),'-o',str(binary)]
    receipt=native_process.clean(parse(compile_receipt_bytes),argv)
    pid=integer(receipt['launch_receipt'].get('pid'),2,2**31-1)
    process=scope.processes.get(pid);rows=[row for row in scope.rows if row['pid']==pid]
    require(process is not None and process.pid==pid and process.poll()==0 and len(rows)==1 and
            rows[0]['argv']==argv and rows[0]['settled'] is True and process.launch.row==receipt['launch_receipt'],
            'compile receipt is not the exact settled owned command')
    # The exact owned LaunchReceipt retains the configured timeout even
    # though Commands(receipt=True) omits commands.jsonl's timeoutSeconds.
    allowance=_compile_allowance(receipt,process.launch)
    source_raw=read_path(source,1024*1024);binary_raw=read_path(binary,128*1024*1024)
    require(type(expected_source_sha256) is str and sha256(source_raw).hexdigest()==expected_source_sha256,
            'helper source changed from precompile expectation')
    assembly=parse(read_path(LOCAL/'capture/assembly-binding.json',65536))
    require(assembly.get('schema')=='p1-direct-capture-local-assembly-v1' and
            assembly.get('assembledSHA256')==sha256(source_raw).hexdigest() and assembly.get('admissionEligible') is False,
            'assembled helper source binding differs')
    info=os.stat(binary,follow_symlinks=False)
    require(stat.S_ISREG(info.st_mode) and info.st_mode&0o111,'compiled helper is not executable')
    after=time.monotonic_ns()
    proof=canonical(dict(schema='p1-direct-helper-compilation-binding-v1',argv=argv,
        compileReceiptSHA256=sha256(compile_receipt_bytes).hexdigest(),sourceSHA256=sha256(source_raw).hexdigest(),
        binarySHA256=sha256(binary_raw).hexdigest(),compileAllowance=allowance,observedAfterHostNs=after,admissionEligible=False))
    return CompiledHelper(scope,process,source,binary,sha256(source_raw).hexdigest(),sha256(binary_raw).hexdigest(),compile_receipt_bytes,proof,after)


@dataclass(frozen=True)
class CaptureTarget:
    path: Path
    parent: Directory
    frames: Directory
    roi_channel: Directory
    stop_channel: Directory
    observed_absent_ns: int
    proof_bytes: bytes


def prepare_capture_target(frame_path):
    """Create only the fresh, descriptor-bound helper directories before launch.

    Native Swift opens these directories; it does not create them. Exclusive
    mkdir and an empty inventory bind all three identities before any helper
    process exists. Failed setup is retained on disk for caller diagnostics.
    """
    path=Path(frame_path)
    require(path.is_absolute() and path.name not in ('','.','..'),'absolute fresh capture target')
    parent=Directory(path.parent);opened=[parent]
    try:
        parent.check();os.mkdir(path.name,0o700,dir_fd=parent.fd);os.fsync(parent.fd)
        frames=Directory(path);opened.append(frames)
        require(os.listdir(frames.fd)==[],'new capture directory is not empty')
        for name in ('roi-channel','stop-channel'):os.mkdir(name,0o700,dir_fd=frames.fd)
        os.fsync(frames.fd)
        roi=Directory(path/'roi-channel');opened.append(roi)
        stop=Directory(path/'stop-channel');opened.append(stop)
        require(set(os.listdir(frames.fd))=={'roi-channel','stop-channel'} and
                os.listdir(roi.fd)==[] and os.listdir(stop.fd)==[],'new capture target inventory changed')
        now=time.monotonic_ns()
        for directory in opened:directory.check()
        proof=canonical(dict(schema='p1-direct-capture-target-v1',path=str(path),parentIdentity=list(parent.identity),
            frameIdentity=list(frames.identity),roiChannelIdentity=list(roi.identity),stopChannelIdentity=list(stop.identity),
            freshEmptyInventoryObservedHostNs=now,admissionEligible=False))
        return CaptureTarget(path,parent,frames,roi,stop,now,proof)
    except BaseException:
        for directory in opened:directory.close()
        raise


class CaptureHandoff:
    """Single freeze, one ROI publication, one promotion, one runner ack.

    retain(name,raw) must durably retain exact bytes, including BGRA payloads.
    remaining(maximum) uses the existing shared scope/case budget. Constructor
    does not wait for a just-started helper; register_baseline polls its original
    launch receipt within its stage/120-second/shared observation deadline.
    """
    def __init__(self,*,scope,gui,helper,compiled,target,frame_path,geometry_request_bytes,runner_directory,journal,channels,
                 budget,bridge,window_capture,remaining,retain,expected_bridge_sources,expected_host_sources):
        require(type(compiled) is CompiledHelper and type(target) is CaptureTarget,'owned prelaunch artifact/target required')
        require(type(helper) is native_process.RetainedCommand and helper.scope is scope,'original retained helper in same Scope required')
        require(Path(window_capture.__file__).resolve()==PREFLIGHT/'window_capture.py','exact reviewed GUI module required')
        require(compiled.scope is scope and type(compiled.process) is window_capture.process_scope.OwnedProcess and
                scope.processes.get(compiled.process.pid) is compiled.process,'same-Scope compiled helper owner required')
        require(type(gui) is window_capture.OwnedGUI and gui.scope is scope and type(scope) is window_capture.process_scope.Scope,
                'original registered GUI and Scope types required')
        require(type(runner_directory) is Directory and type(journal) is Journal and type(journal.directory) is Directory,
                'descriptor-bound runner and journal required')
        require(type(expected_host_sources) is dict and expected_host_sources==source_hashes(),'host source expectation changed')
        for name,digest in PINNED.items():require(sha256((PREFLIGHT/name).read_bytes()).hexdigest()==digest,'reviewed ownership primitive drift')
        require(Path(window_capture.process_scope.__file__).resolve()==PREFLIGHT/'process_scope.py' and
                Path(window_capture.fresh_device.__file__).resolve()==PREFLIGHT/'fresh_device.py','foreign ownership module origin')
        require(Path(bridge.__file__).resolve()==LOCAL/'pixels/registration_bridge.py' and
                type(expected_bridge_sources) is dict and expected_bridge_sources==bridge.source_hashes(),'exact retained-byte bridge sources required')
        self.scope=scope;self.gui=gui;self.helper=helper;self.compiled=compiled;self.target=target;self.window=window_capture
        self.bridge=bridge;self.remaining=remaining;self.retain_callback=retain;self.host_sources=dict(expected_host_sources)
        self.bridge_sources=dict(expected_bridge_sources);self.budget=parse(canonical(budget))
        require(self.budget==case_budget.construct(self.budget['startSample'],self.budget['scopeRemainingNs']),'altered shared case budget')
        self.geometry_request_bytes=geometry_request_bytes;self.request=bridge.handoff.validate_request(geometry_request_bytes)
        self.session=self.request['session'];self.device=self.request['simulatorUDID'];self.frame_path=Path(frame_path)
        require(self.request['scenario']=='timeout' and self.frame_path==target.path,'single timeout/fresh capture target binding')
        self.channels=channels;self.runner=runner_directory;self.journal=journal;self.frames=target.frames;self.roi_channel=target.roi_channel;self.stop_channel=target.stop_channel;self.gui_directory=None
        self.baseline=None;self.binding=None;self.plan=None;self.timebase=None;self.expected_geometry=None
        self.stream_ready_bytes=None;self.first_complete_bytes=None;self.first_packed_bytes=None
        self.receipts={};self.immutable={};self.state='new';self.failed=False;self.capture_instance=uuid.uuid4().hex
        self.started_ns=time.monotonic_ns()
        self.deadline_ns=min(self.started_ns+120_000_000_000,self.budget['startSample']['hostBeforeNs']+
                             self.budget['effectiveCommandBudgetNs']-80_000_000_000)
        self.helper_argv=(str(compiled.binary_path),str(gui.process.pid),window_capture.SIMULATOR,str(self.frame_path),self.session,
                          str(self.budget['observationDeadlineMach']),str(self.budget['cleanupDeadlineMach']))
        require(helper.argv==self.helper_argv,'exact owned helper argv required')
        require(gui.argv==[window_capture.SIMULATOR,'-CurrentDeviceUDID',self.device],'exact GUI/device argv required')
        self._channels()
        require(self.runner.read('request.json') is None,'runner ack already exists')
        self._verify_artifacts();self._retain('helper-compilation',compiled.proof_bytes)
        self._retain('helper-compile-command',compiled.compile_receipt_bytes);self._retain('capture-target',target.proof_bytes)
        self._retain('capture-geometry-request',geometry_request_bytes)
        self._retain('capture-host-source-map',canonical(self.host_sources));self._retain('capture-bridge-source-map',canonical(self.bridge_sources))

    def _retain(self,name,raw):
        require(type(raw) is bytes and len(raw)>0,'immutable retained bytes required')
        if name in self.receipts:require(self.receipts[name]==raw,'retained handoff evidence changed');return
        self.retain_callback(name,raw);self.receipts[name]=raw

    def _verify_artifacts(self):
        require(source_hashes()==self.host_sources and self.bridge.source_hashes()==self.bridge_sources,'handoff source drift')
        require(sha256(read_path(self.compiled.source_path,1024*1024)).hexdigest()==self.compiled.source_sha256 and
                sha256(read_path(self.compiled.binary_path,128*1024*1024)).hexdigest()==self.compiled.binary_sha256,
                'compiled helper/source changed after prelaunch binding')

    def _launch(self,process):
        require(type(process) is self.window.process_scope.OwnedProcess and self.scope.processes.get(process.pid) is process,
                'original live registered process required')
        launch=process.launch
        require(type(launch) is self.window.process_scope.LaunchReceipt,'original launch receipt required')
        # Original wait() observes under this lock as well. EOF permits its
        # idempotent finalization now; eventual Commands settlement reuses it.
        with process.lock:
            launch.observe()
            if not launch.row['eof']:return False
            launch.finish();launch.require();row=launch.row
            require(row['exec_failure'] is None and row['pid']==process.pid and row['session']==self.scope.session and
                    row['registration']['durable'] is True and row['release']['issued'] is True and
                    row['popen']['returned'] is True and row['pre_exec'] is not None,'exact successful live launch binding')
            return parse(canonical(row))

    def _channels(self):
        channels=self.channels
        require(type(channels) is native_channels.Channels and type(channels.native) is native_process.RetainedCommand and
                channels.native.scope is self.scope and type(channels.command) is self.window.process_scope.Commands and
                channels.command.scope is self.scope,'original same-Scope native container collector required')
        channels.native.live()
        require(channels.session==self.session and channels.device==self.device and channels.identifiers=={
                'app':'org.sidestore.fixture.p1video','runner':'org.sidestore.fixture.p1video.uitests.xctrunner'} and
                self.request['runnerBundleIdentifier']==channels.identifiers['runner'] and channels.hint is not None,
                'native session/device/bundle/start binding')
        require(channels.directories=={'runner':self.runner,'app':self.journal.directory} and
                channels.geometry_bytes==self.geometry_request_bytes and set(channels.roots)=={'app','runner'} and
                channels.attempted=={'app','runner'},'exact discovered descriptor/geometry binding')
        argv=channels.native.argv
        native=channels.native.process
        require(type(native) is self.window.process_scope.OwnedProcess and
                self.scope.processes.get(native.pid) is native and type(native.launch) is self.window.process_scope.LaunchReceipt and
                native.launch.row['session']==self.scope.session and native.launch.row['pid']==native.pid,
                'original same-session native XCTest owner required')
        native_rows=[row for row in self.scope.rows if row['pid']==native.pid]
        require(len(native_rows)==1 and native_rows[0]['argv']==list(argv) and native_rows[0]['settled'] is False,
                'native XCTest registry changed')
        require(len(argv)>7 and argv==native_case.native_argv(dict(device=self.device,xctestrun=argv[3],resultBundle=argv[7])),
                'original one-method XCTest argv required')
        for role in ('app','runner'):
            root=channels.roots[role];require(type(root) is type(Path()) and root.is_absolute() and root.resolve()==root,'exact canonical container root')
            receipt=channels.receipts[role]
            command_argv=['xcrun','simctl','get_app_container',self.device,channels.identifiers[role],'data']
            native_process.clean(receipt,command_argv)
            lookup_pid=integer(receipt['launch_receipt'].get('pid'),2,2**31-1)
            lookup=self.scope.processes.get(lookup_pid);lookup_rows=[row for row in self.scope.rows if row['pid']==lookup_pid]
            require(type(lookup) is self.window.process_scope.OwnedProcess and type(lookup.launch) is self.window.process_scope.LaunchReceipt and
                    lookup.poll()==0 and len(lookup_rows)==1 and lookup_rows[0]['argv']==command_argv and lookup_rows[0]['settled'] is True and
                    lookup.launch.row==receipt['launch_receipt'] and lookup.launch.row['session']==self.scope.session,
                    'container result is not the exact settled owned lookup')
            require(type(receipt.get('stdout')) is str and receipt['stdout'].strip()==str(root),'retained container result differs')
            suffix=Path('Documents/p1-capability')/self.session if role=='runner' else Path('Documents/p1-video/timeout')
            require(channels.directories[role].path==root/suffix,'foreign session container directory')
            channels.directories[role].check()
            self._retain('capture-'+role+'-container-command',canonical(receipt))
        ready=exact(parse(channels.ready_bytes),('schema','session','geometryFile','acknowledgementFile','admissionEligible','geometryRequestSHA256'))
        require(ready==dict(schema='p1-direct-baseline-ready-v1',session=self.session,geometryFile='geometry.json',
            acknowledgementFile='request.json',admissionEligible=False,geometryRequestSHA256=sha256(self.geometry_request_bytes).hexdigest()) and
            self.runner.read('ready.json',8192)==channels.ready_bytes and self.runner.read('geometry.json',8192)==self.geometry_request_bytes,
            'retained runner ready/request bytes changed')
        self._retain('capture-observer-ready',channels.ready_bytes)

    def _owners(self):
        self._channels();self.target.parent.check();self.target.frames.check();self.target.roi_channel.check();self.target.stop_channel.check();self.gui.live();self.helper.live()
        fixture=self.scope.fixture or {};fresh=self.window.fresh_device
        fresh.validate(fixture.get('owned_created'),self.scope.session,self.device)
        fresh.validate(self.scope.creation_intent,self.scope.session)
        require(all(fixture['owned_created'].get(k)==v for k,v in self.scope.creation_intent.items()) and
                fixture.get('device')==self.device and fixture.get('owned_boot') is True and
                fixture.get('deleted') is False and fixture.get('stopped') is False and
                not fixture.get('cleanup_command_failed'),'created device lifecycle unavailable')
        if self.helper.process is None:return False
        require(self.helper.process is not self.gui.process,'conflated GUI/helper owner')
        require(self.channels.native.process is not None,'native XCTest process ownership absent')
        native_launch=self._launch(self.channels.native.process)
        gui_launch=self._launch(self.gui.process);helper_launch=self._launch(self.helper.process)
        if not gui_launch or not helper_launch or not native_launch:return False
        native_rows=[row for row in self.scope.rows if row['pid']==self.channels.native.process.pid]
        require(len(native_rows)==1 and native_rows[0]['argv']==list(self.channels.native.argv) and native_rows[0]['settled'] is False,
                'native XCTest registry changed')
        rows=[row for row in self.scope.rows if row['pid']==self.helper.process.pid]
        require(len(rows)==1 and rows[0]['argv']==list(self.helper_argv) and rows[0]['settled'] is False,'helper registry mismatch')
        launch_ns=int(helper_launch['popen']['before']*1_000_000_000)
        require(max(self.compiled.observed_after_ns,self.target.observed_absent_ns)<=launch_ns,'artifact/target was not bound before launch')
        require(self.helper.process.poll() is None and self.gui.process.poll() is None,'owner exited during prerequisite')
        return dict(gui=gui_launch,helper=helper_launch,native=native_launch,device=parse(canonical(fixture['owned_created'])))

    def _checkpoint(self,deadline):
        require(not self.failed and time.monotonic_ns()<min(deadline,self.deadline_ns),'capture handoff deadline or prior failure')
        allowance=self.remaining(120);require(type(allowance) in (int,float) and math.isfinite(allowance) and 0<allowance<=120,'bounded remaining case allowance')
        owners=self._owners()
        require(self.stop_channel.read('request.json',8192) is None,'helper stop requested before acknowledgement')
        if self.frames is not None:
            self.frames.check()
            for name in ('stage-timeout.json','window-capture.json'):
                require(self.frames.read(name,32*1024*1024) is None,'helper ended or reported failure before acknowledgement')
        return owners

    def _deadline(self,timeout):
        require(type(timeout) in (int,float) and math.isfinite(timeout) and 0<timeout<=120,'bounded handoff stage timeout')
        remaining=self.remaining(timeout)
        require(type(remaining) in (int,float) and math.isfinite(remaining) and 0<remaining<=timeout,'bounded remaining stage allowance')
        return min(self.deadline_ns,time.monotonic_ns()+int(remaining*1e9))

    def _enter(self,expected,state,timeout):
        try:
            require(self.state==expected and not self.failed,'single ordered capture handoff stage: '+expected)
            deadline=self._deadline(timeout);self.state=state;return deadline
        except BaseException:self.failed=True;raise

    def _read(self,directory,name,limit=65536):
        raw=directory.read(name,limit)
        if raw is None:return None
        key=(str(directory.path),name)
        if key in self.immutable:require(raw==self.immutable[key][2],'helper immutable evidence changed')
        else:
            self._retain('capture-'+name,raw);self.immutable[key]=(directory,limit,raw)
        return raw

    def _verify_immutable(self):
        for (_,name),(directory,limit,raw) in self.immutable.items():
            require(directory.read(name,limit)==raw,'retained capture evidence removed or mutated')
        require(self.runner.read('geometry.json',8192)==self.geometry_request_bytes,'runner geometry bytes changed')

    def _census(self,raw,phase,expected=None):
        row=exact(parse(raw),('schema','ownerPID','phase','count','windows','admissionEligible'))
        require(row['schema']=='p1-owned-window-census-v1' and row['ownerPID']==self.gui.process.pid and
                row['phase']==phase and row['admissionEligible'] is False,'owned window census identity')
        integer(row['ownerPID'],2,2**31-1);integer(row['count'],1,16)
        require(type(row['windows']) is list and len(row['windows'])==row['count'],'window census count')
        ids=[]
        for window in row['windows']:
            exact(window,('windowID','frame'));ids.append(integer(window['windowID'],1,2**32-1));rectangle(window['frame'])
        require(len(set(ids))==len(ids),'duplicate window ID')
        if expected is None:require(len(ids)==1,'ambiguous initial owned window');return row['windows'][0]
        found=[w for w in row['windows'] if w['windowID']==expected['windowID']]
        require(found==[expected],'registered window/frame changed');return found[0]

    def register_baseline(self,timeout):
        deadline=self._enter('new','registering',timeout)
        try:
            while True:
                owners=self._checkpoint(deadline)
                if not owners:time.sleep(.02);continue
                if self.frames is None:
                    try:self.frames=Directory(self.frame_path)
                    except FileNotFoundError:time.sleep(.02);continue
                census=self._read(self.frames,'window-census-initial.json')
                metadata=self._read(self.frames,'baseline.json')
                rows=self.journal.events()
                if census is not None and metadata is not None and any(r['type']=='direct-anchor-initial-draws' for r in rows):break
                time.sleep(.02)
            self.window_identity=self._census(census,'initial')
            row=exact(parse(metadata),('schema','format','width','height','stride','bytes','sha256','displayTimeEstablished','admissionEligible','windowID','session'))
            require(row['schema']=='p1-direct-registration-buffer-v1' and row['format']=='BGRA8' and row['session']==self.session and
                    type(row['windowID']) is int and row['windowID']==self.window_identity['windowID'] and
                    row['displayTimeEstablished'] is False and row['admissionEligible'] is False,'baseline raster binding')
            width=integer(row['width'],1,2048);height=integer(row['height'],1,2048);stride=integer(row['stride'],4*width,4*width+256)
            require(stride%4==0 and type(row['bytes']) is int and row['bytes']==stride*height,'baseline storage shape')
            raw=self._read(self.frames,'baseline.bgra',stride*height)
            require(raw is not None and len(raw)==row['bytes'] and sha256(raw).hexdigest()==row['sha256'],'baseline bytes/hash')
            identity=self.bridge.g.RasterIdentity(self.session,self.gui.process.pid,row['windowID'],width,height,
                                                  self.bridge.exact_rect(self.request['geometry']['windowFrame']))
            self.baseline=self.bridge.freeze_registration(self.geometry_request_bytes,raw,width,height,stride,identity=identity,
                expected_frame_sha256=row['sha256'],event_files=tuple((f'event-{i:03d}.json',value) for i,value in enumerate(self.journal.raw,1)),
                expected_source_hashes=self.bridge_sources)
            self.plan=parse(self.baseline.plan_bytes)
            self._retain('capture-baseline-proof',self.baseline.proof_bytes);self._retain('capture-roi-plan',self.baseline.plan_bytes)
            self._verify_artifacts();self._verify_immutable();require(self._checkpoint(deadline),'helper launch unresolved')
            self.state='registered';return self.baseline.proof_bytes
        except BaseException:self.failed=True;raise

    def publish_roi(self,timeout):
        deadline=self._enter('registered','publishing',timeout)
        try:
            while self.roi_channel is None:
                require(self._checkpoint(deadline),'helper owner unresolved')
                try:self.roi_channel=Directory(self.frame_path/'roi-channel')
                except FileNotFoundError:time.sleep(.02)
            require(self.roi_channel.read('request.json') is None,'ROI request already exists')
            self._verify_immutable();require(self._checkpoint(deadline),'helper owner unresolved')
            self.roi_channel.publish('request.json',self.baseline.plan_bytes)
            self._read(self.roi_channel,'request.json',8192)
            require(self._checkpoint(deadline),'helper owner unresolved')
            self.state='published';return self.baseline.plan_bytes
        except BaseException:self.failed=True;raise

    def await_first(self,timeout):
        deadline=self._enter('published','awaiting',timeout)
        try:
            while True:
                require(self._checkpoint(deadline),'helper owner unresolved')
                ready=self._read(self.frames,'stream-ready.json');first=self._read(self.frames,'first-complete.json')
                registered=self._read(self.frames,'window-census-registered.json');accepted=self._read(self.frames,'accepted-roi-plan.json',8192)
                if all(raw is not None for raw in (ready,first,registered,accepted)):break
                time.sleep(.02)
            require(accepted==self.baseline.plan_bytes,'native accepted plan differs')
            self._census(registered,'registered',self.window_identity)
            row=exact(parse(ready),('schema','session','ownerPID','windowID','executable','windowFrame','geometrySHA256',
                      'timebaseNumerator','timebaseDenominator','startCaptureReturnedMach','startCaptureReturned',
                      'presentationLowerBoundEstablished','admissionEligible'))
            require(row['schema']=='p1-direct-stream-ready-v1' and row['session']==self.session and
                    type(row['ownerPID']) is int and row['ownerPID']==self.gui.process.pid and
                    type(row['windowID']) is int and row['windowID']==self.window_identity['windowID'] and
                    row['executable']==self.window.SIMULATOR and rectangle(row['windowFrame'])==self.window_identity['frame'] and
                    row['geometrySHA256']==sha256(self.geometry_request_bytes).hexdigest() and row['startCaptureReturned'] is True and
                    row['presentationLowerBoundEstablished'] is False and row['admissionEligible'] is False,'stream start/owner/request binding')
            self.timebase=(integer(row['timebaseNumerator'],1,2**32-1),integer(row['timebaseDenominator'],1,2**32-1))
            require(self.timebase==(self.budget['startSample']['timebaseNumer'],self.budget['startSample']['timebaseDenom']),
                    'native Mach timebase differs from owned budget sample')
            integer(row['startCaptureReturnedMach'],self.budget['startSample']['machTicks'],self.budget['observationDeadlineMach']-1)
            manifest=parse(first);index=integer(manifest.get('index'),0,5999)
            packed=self._read(self.frames,f'frame-{index:05d}.rois.bgra',1024*1024)
            require(packed is not None,'first complete packed pixels absent')
            self.bridge.packed_frames.inspect_first(manifest,self.plan,timebase=self.timebase,
                load=lambda name:packed if name==f'frame-{index:05d}.rois.bgra' else None)
            self.stream_ready_bytes=ready;self.first_complete_bytes=first;self.first_packed_bytes=packed
            self._verify_immutable();require(self._checkpoint(deadline),'helper owner unresolved')
            self.state='first';return first
        except BaseException:self.failed=True;raise

    def promote_first(self,timeout):
        deadline=self._enter('first','promoting',timeout)
        try:
            require(self._checkpoint(deadline),'helper owner unresolved');self._verify_artifacts();self._verify_immutable()
            self.binding=self.bridge.RegistrationJoin(self.baseline,expected_baseline_proof_sha256=self.baseline.proof_sha256).promote(
                self.first_complete_bytes,self.first_packed_bytes,expected_manifest_sha256=sha256(self.first_complete_bytes).hexdigest(),timebase=self.timebase)
            metadata=parse(self.binding.proof_bytes)['nativeStreamMetadata']
            self.expected_geometry=(metadata['contentRect'],metadata['contentScale'],metadata['scaleFactor'])
            self._retain('capture-first-binding',self.binding.proof_bytes)
            require(self._checkpoint(deadline),'helper owner unresolved');self.state='promoted';return self.binding.proof_bytes
        except BaseException:self.failed=True;raise

    def publish_ack(self,timeout):
        deadline=self._enter('promoted','acknowledging',timeout)
        try:
            self._verify_artifacts();self._verify_immutable();owners=self._checkpoint(deadline);require(owners,'helper owner unresolved')
            self.journal.events();self.bridge.retained_events(tuple((f'event-{i:03d}.json',v) for i,v in enumerate(self.journal.raw,1)),self.session)
            if self.gui_directory is None:self.gui_directory=Directory(Path(self.gui.folder))
            gui_raw=self._read(self.gui_directory,'gui-owner.json')
            gui=exact(parse(gui_raw),('schema','argv','pid','launch_receipt','stopped','admissionEligible'))
            require(gui==dict(schema='p1-owned-simulator-gui-v1',argv=self.gui.argv,pid=self.gui.process.pid,
                    launch_receipt=owners['gui'],stopped=False,admissionEligible=False),'retained live GUI owner binding differs')
            device_raw=canonical(owners['device']);self._retain('capture-owned-device',device_raw)
            owner_raw=canonical(dict(schema='p1-direct-live-window-binding-v1',session=self.session,simulatorUDID=self.device,
                initialCensusSHA256=sha256(self.receipts['capture-window-census-initial.json']).hexdigest(),
                registeredCensusSHA256=sha256(self.receipts['capture-window-census-registered.json']).hexdigest(),
                helperCompilationSHA256=sha256(self.compiled.proof_bytes).hexdigest(),helperLaunch=owners['helper'],nativeLaunch=owners['native'],
                appContainerCommandSHA256=sha256(self.receipts['capture-app-container-command']).hexdigest(),
                runnerContainerCommandSHA256=sha256(self.receipts['capture-runner-container-command']).hexdigest(),
                guiLaunch=owners['gui'],window=self.window_identity,hostSourceHashes=self.host_sources,admissionEligible=False))
            self._retain('capture-live-window-binding',owner_raw)
            manifest=parse(self.first_complete_bytes)
            first_raw=canonical(dict(schema='p1-direct-first-complete-retained-v1',session=self.session,
                manifestSHA256=sha256(self.first_complete_bytes).hexdigest(),packedPixelSHA256=sha256(self.first_packed_bytes).hexdigest(),
                bindingProofSHA256=self.binding.proof_sha256,index=manifest['index'],displayTimeMach=str(manifest['displayTimeMach']),
                helperReportedFirstComplete=True,allDeliveredRecordsEstablished=False,admissionEligible=False))
            self._retain('capture-first-complete-retained',first_raw)
            proof=dict(schema='p1-direct-owned-capture-ready-v1',session=self.session,geometryRequestSHA256=sha256(self.geometry_request_bytes).hexdigest(),
                captureInstance=self.capture_instance,simulatorUDID=self.device,guiPID=self.gui.process.pid,windowID=self.window_identity['windowID'],
                helperPID=self.helper.process.pid,helperSourceSHA256=self.compiled.source_sha256,
                ownedDeviceReceiptSHA256=sha256(device_raw).hexdigest(),ownedGUIReceiptSHA256=sha256(gui_raw).hexdigest(),
                windowBindingReceiptSHA256=sha256(owner_raw).hexdigest(),fourAnchorProofSHA256=self.binding.proof_sha256,
                streamReadyReceiptSHA256=sha256(self.stream_ready_bytes).hexdigest(),firstCompleteFrameSHA256=sha256(first_raw).hexdigest(),
                firstCompleteFrameIndex=manifest['index'],firstCompleteFrameDisplayTime=str(manifest['displayTimeMach']),
                captureStarted=True,firstCompleteFramePresent=True,guiLiveRegistered=True,fourAnchorsDecoded=True,geometryFrozen=True,
                captureErrors=[],ownershipErrors=[],admissionEligible=False)
            ack=canonical(dict(schema='p1-direct-baseline-ack-v1',session=self.session,geometryRequestSHA256=proof['geometryRequestSHA256'],
                captureReadyProof=proof,captureReadyProofSHA256=sha256(canonical(proof)).hexdigest(),admissionEligible=False))
            self.bridge.handoff.validate_ack(ack,self.geometry_request_bytes)
            self._retain('capture-ready-proof',canonical(proof));self._retain('capture-ack',ack)
            require(self.runner.read('request.json') is None,'runner acknowledgement already published')
            self._verify_immutable();require(self._checkpoint(deadline),'live owners lost before ack')
            self.runner.publish('request.json',ack)
            require(self._checkpoint(deadline),'live owners lost at ack publication')
            self.state='acknowledged';return ack
        except BaseException:self.failed=True;raise

    def close(self):
        for directory in (self.frames,self.roi_channel,self.stop_channel,self.gui_directory,self.target.parent):
            if directory is not None:directory.close()
