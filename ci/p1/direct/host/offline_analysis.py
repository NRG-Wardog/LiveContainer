"""Concrete, post-settlement timeout evidence replay and retained Swift decoding.

No CLI, native invocation on import, permission request, or admission path.
The real Runtime supplies the existing Scope/Commands and owned capture binding.
"""
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import ast
import importlib.util
import math
import os
import re
import sys
from fixture_channel import Directory,parse,canonical,require
from native_process import clean

LOCAL=Path(__file__).resolve().parents[1]
for path in (LOCAL/'analysis',LOCAL/'pixels'):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
import timeout_case,evidence_joins,packed_frames,registration_bridge as bridge
import build_independent_ocr
CONTROL_SHA='b7c2b1574323621d981f2984a6ffcb568dea116e251007118154a5119489d8cc'
INDEPENDENT_SHA='820bd947cd3b2ac43ef3078f620634f4199846a732c8165d046a14cf04a80592'
VIDEO_CAPTURE_SHA='4f2d23438100bf2baa0805623fbb534e72588798d34d6c7245754786694b802d'


def read(path,limit=32*1024*1024):
    path=Path(path)
    require(path.is_absolute() and path.parent.resolve()==path.parent,'canonical retained parent')
    directory=Directory(path.parent)
    try:
        raw=directory.read(path.name,limit);require(raw is not None,'missing retained evidence: '+path.name)
        return raw
    finally:directory.close()


def write(path,raw):
    require(type(raw) is bytes and raw,'nonempty retained bytes')
    with Path(path).open('xb') as file:file.write(raw);file.flush();os.fsync(file.fileno())


def json_value(value):
    if type(value) is Fraction:return {'numerator':value.numerator,'denominator':value.denominator}
    if type(value) is dict:return {k:json_value(v) for k,v in value.items()}
    if type(value) in (tuple,list):return [json_value(v) for v in value]
    return value


def source_guard(runtime):
    require(Path(runtime.local).resolve()==LOCAL,'wrong running local source root')
    control=LOCAL/'pixels/control_ocr.swift';independent=LOCAL/'pixels/independent_ocr.swift'
    require(sha256(read(control)).hexdigest()==CONTROL_SHA,'control decoder source drift')
    require(sha256(read(independent)).hexdigest()==INDEPENDENT_SHA and
            read(independent)==build_independent_ocr.build().encode(),'independent decoder source drift')
    require(Path(runtime.video.__file__).resolve()==timeout_case.VIDEO/'capture.py' and
            sha256(read(Path(runtime.video.__file__).resolve())).hexdigest()==VIDEO_CAPTURE_SHA,'maintained video export source drift')
    return {'control':control,'independent':independent}


def settled(runtime,context):
    require(context.get('session')==runtime.session and context.get('scenario')=='timeout','one timeout session')
    sequence=parse(read(runtime.output/'case-sequence.json'))
    require(sequence.get('session')==runtime.session and sequence.get('sequenceCompleted') is True and
            sequence.get('failed') is False and sequence.get('errors')==[],'successful settled case sequence required')
    require(not runtime.scope.closing and runtime.scope.rows and all(r.get('settled') is True for r in runtime.scope.rows),'all owned writers must settle before analysis')
    fixture=runtime.scope.fixture
    require(type(fixture) is dict and fixture.get('stopped') is True and fixture.get('deleted') is True and
            fixture.get('owned_created',{}).get('device')==runtime.device and not fixture.get('cleanup_command_failed'),'owned device cleanup required')
    proof=context['evidence']['verify_cleanup']
    require(read(runtime.output/'receipts/verify_cleanup.json')==proof.raw and proof.value.get('allWritersSettled') is True,'retained final cleanup proof')
    protocol=context['protocol']
    require(read(runtime.output/'protocol.json') and parse(read(runtime.output/'protocol.json'))==protocol and
            protocol.get('protocolComplete') is True and protocol.get('failed') is False,'retained complete protocol')
    clean(runtime.native_receipt,context['argv'])
    clean(runtime.helper.row,runtime.helper.argv)
    require(read(runtime.output/'receipts/native-command.json')==canonical(runtime.native_receipt),'retained native result receipt')
    return protocol


def journal_and_transport(runtime):
    root=runtime.output/'app-journal'
    require(root.resolve()==root and root.is_dir() and not root.is_symlink(),'canonical retained final journal')
    names=sorted(p.name for p in root.iterdir())
    require(1<=len(names)<=801 and all(re.fullmatch(r'(event-[0-9]{3}|strip-[0-9]{4}|strip-complete)\.json',n) for n in names),'exact retained final journal members')
    raw={name:read(root/name,256*1024) for name in names}
    events=runtime.video.read_events(root);strip=runtime.video.read_strip(root)
    require(events==runtime.final_journal['events'] and strip==runtime.final_journal['strip'] and
            tuple(raw[n] for n in names if n.startswith('event-'))==runtime.final_journal['eventBytes'],'actual journal bytes differ from final owned receipt')
    for index,row in enumerate(runtime.transport,1):
        encoded=dict(row)
        for key,value in list(encoded.items()):
            if type(value) is bytes:encoded[key]={'hex':value.hex(),'sha256':sha256(value).hexdigest()}
        require(read(runtime.output/'receipts'/('exchange-%03d.json'%index))==canonical(encoded),'actual retained request/response receipt differs')
        require(row.get('directoryIdentity')==runtime.channels.directories['app'].identity,'raw transport container directory differs')
    identity={'session':runtime.session,'simulatorUDID':runtime.device,'hostPID':os.getpid(),
              'appContainerReceiptSHA256':sha256(canonical(runtime.channels.receipts['app'])).hexdigest(),
              'sourceSHA256':runtime.video.SOURCE_SHA}
    require(read(runtime.output/'receipts/app-container-receipt.json')==canonical(runtime.channels.receipts['app']),'retained discovered app container receipt differs')
    return events,strip,identity,{str(root/n):sha256(data).hexdigest() for n,data in raw.items()}


class Commands:
    """Retain each existing Commands receipt and its exact raw stdout/stderr."""
    def __init__(self,runtime,folder):
        self.runtime=runtime;self.folder=folder;folder.mkdir()
        self.commands=runtime.ps.Commands(runtime.scope,folder);self.rows=[]
    def __call__(self,*argv,timeout=300):
        allowance=self.runtime.remaining(min(timeout,600))
        require(type(allowance) in (int,float) and math.isfinite(allowance) and 0<allowance<=min(timeout,600),'original remaining offline deadline')
        row=self.commands(*argv,timeout=allowance,receipt=True)
        self.rows.append(row)
        # Retain even nonzero/timeout/unknown-launch results before checking.
        self.runtime.retain('offline-command-%03d'%len(self.rows),canonical(row))
        clean(row,argv)
        identifier=row.get('command_id');require(type(identifier) is str and re.fullmatch('command-[0-9]{4}',identifier),'retained command log identity')
        out=log_bytes(self.folder/(identifier+'.stdout'))
        err_path=self.folder/(identifier+'.stderr')
        # Empty command logs are legitimate. Open via bounded descriptor reader
        # separately because Directory.read intentionally rejects empty evidence.
        for path,expected in ((self.folder/(identifier+'.stdout'),row['stdout']),(err_path,row['stderr'])):
            raw=log_bytes(path)
            require(raw.decode(errors='replace')==expected,'receipt/log byte mismatch')
        self.runtime.remaining(1)
        return out.decode(errors='strict')
    def stdout(self,argv):
        rows=[r for r in self.rows if r['argv']==list(map(str,argv))]
        require(len(rows)==1,'one exact export command receipt')
        return log_bytes(self.folder/(rows[0]['command_id']+'.stdout'))


def log_bytes(path):
    # Source-owned Commands creates these exact regular files; detect replacement,
    # symlinks, short reads and unbounded output, while permitting empty logs.
    import stat
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=32*1024*1024,'bounded ordinary command log')
        data=b''
        while len(data)<=before.st_size:
            part=os.read(fd,min(65536,before.st_size+1-len(data)))
            if not part:break
            data+=part
        after=os.fstat(fd)
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) and len(data)==before.st_size,'command log changed during read')
        return data
    finally:os.close(fd)


def independent_input(events,controls,screenshots,png_bytes):
    """Preserve maintained independent XCTest screenshot coordinate semantics."""
    geometry=[r for r in events if r.get('type')=='marker-geometry'];require(geometry,'missing original marker geometry')
    row=geometry[-1];rect=row.get('rect');points=row.get('screenPoints');scale=row.get('scale')
    require(type(rect) is list and len(rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect) and min(rect[2:])>0,'original marker rectangle')
    require(type(points) is list and len(points)==2 and all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in points+[scale]),'original screenshot screen/scale geometry')
    require(all(abs(a-b)<=1 for a,b in zip(rect,controls['markerFrame'])),'original marker differs from independent XCTest geometry')
    require(controls.get('copyHittable') is True and controls.get('copyLabel')=='Copy Details','original production Copy unavailable')
    size=[round(v*scale) for v in points]
    import struct
    for phase in ('before','after'):
        raw=png_bytes[phase]
        require(evidence_joins.valid_png(raw) and list(struct.unpack('>II',raw[16:24]))==size,'actual PNG dimensions differ from original measured screen scale')
    return {'markerRectPixels':[v*scale for v in rect],
            'copyRectPixels':[v*scale for v in controls['copyFrame']], 'pixelSize':size,
            'independentScreenshots':[{'phase':phase,'path':str(screenshots[phase])} for phase in ('before','after')]}


def frame_inventory(directory,records):
    directory.check()
    actual={name for name in os.listdir(directory.fd) if name.startswith('frame-')}
    expected={row['packedPixels'] for row in records if row['newFrame']}
    require(actual==expected,'retained frame-file census differs from all delivered complete records')


def replay_frames(binding,records,folder,remaining):
    """Fresh final replay, beginning at the exact bound first complete sample."""
    validator=bridge.g.GeometryValidator(binding.frozen);proofs=[];folder.mkdir()
    for row in records:
        remaining(1)
        if row['newFrame']:
            proof=bridge.validate_complete_frame(binding,row,validator=validator)
            write(folder/('frame-%05d.json'%row['index']),canonical(proof));proofs.append(proof)
    return proofs


def final_context(directory,plan,session):
    raw=directory.read('final.json',65536);require(raw is not None,'final full-context metadata missing')
    row=parse(raw)
    require(type(row) is dict and set(row)=={'schema','format','width','height','stride','bytes','sha256','displayTimeEstablished','admissionEligible','windowID','session'},'final full-context schema')
    require(row['schema']=='p1-direct-registration-buffer-v1' and row['format']=='BGRA8' and row['session']==session and
            type(row['windowID']) is int and row['windowID']==plan['windowID'] and row['displayTimeEstablished'] is False and
            row['admissionEligible'] is False,'final full-context identity')
    require(all(type(row[k]) is int for k in ('width','height','stride','bytes')) and
            [row['width'],row['height'],row['stride']]==[plan['sourceWidth'],plan['sourceHeight'],plan['sourceStride']] and
            row['bytes']==row['stride']*row['height'],'final full-context layout')
    pixels=directory.read('final.bgra',32*1024*1024)
    require(type(pixels) is bytes and len(pixels)==row['bytes'] and sha256(pixels).hexdigest()==row['sha256'],'actual final full-context BGRA/hash')
    return {'metadataSHA256':sha256(raw).hexdigest(),'pixelsSHA256':row['sha256'],'bytes':len(pixels),
            'presentationTimeEstablished':False,'admissionEligible':False}


def decoder(command,runtime,folder,name,source,input_bytes,input_root,observed_inputs):
    input_file=folder/(name+'-input.json');output_file=folder/(name+'-output.json')
    write(input_file,input_bytes)
    source_bytes=read(source);input_hashes={str(p):sha256(read(p,32*1024*1024)).hexdigest() for p in observed_inputs}
    args=['swift',source,input_file,input_root,output_file]
    status={'schema':'p1-direct-offline-decoder-execution-v1','name':name,'sourceSHA256':sha256(source_bytes).hexdigest(),
            'inputSHA256':sha256(input_bytes).hexdigest(),'observedInputSHA256':input_hashes,'outputSHA256':None,
            'commandReceiptSHA256':None,'completed':False,'admissionEligible':False}
    try:
        command(*args,timeout=600)
        status['commandReceiptSHA256']=sha256(canonical(command.rows[-1])).hexdigest()
        require(read(source)==source_bytes and read(input_file)==input_bytes,'decoder source/input changed during execution')
        require({str(p):sha256(read(p,32*1024*1024)).hexdigest() for p in observed_inputs}==input_hashes,'decoder pixel input changed during execution')
        output=read(output_file,32*1024*1024);status['outputSHA256']=sha256(output).hexdigest()
        value=parse(output);status['completed']=True
        return value
    except BaseException as error:
        status['error']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:runtime.retain('offline-'+name+'-decoder',canonical(status))


def run(runtime,context):
    """Execute only after Case.run succeeded and every capture writer settled."""
    folder=Path(runtime.output)/'offline-analysis';folder.mkdir()
    report={'schema':'p1-direct-offline-analysis-v1','session':runtime.session,'completed':False,'admissionEligible':False,'stage':'preconditions'}
    frames=None
    try:
        protocol=settled(runtime,context);sources=source_guard(runtime);runtime.remaining(1)
        events,strip,identity,journal_hashes=journal_and_transport(runtime)
        capture=runtime.capture_binding
        require(capture.state=='acknowledged' and capture.failed is False,'successful owned baseline acknowledgement required')
        capture._verify_artifacts()
        for name,raw in capture.receipts.items():require(read(runtime.output/'receipts'/(name+'.json'),32*1024*1024)==raw,'retained capture proof/input differs')
        require(canonical(capture.plan)==capture.baseline.plan_bytes and read(capture.frames.path/'accepted-roi-plan.json')==capture.baseline.plan_bytes,'actual accepted fixed plan differs')
        require(type(capture.baseline) is bridge.RegistrationResult and type(capture.binding) is bridge.StreamBindingResult,'actual baseline and stream binding objects')
        require(read(capture.frames.path/'first-complete.json')==capture.first_complete_bytes,'retained actual first-complete receipt')
        baseline_proof=parse(capture.baseline.proof_bytes)
        event_files=tuple((item['name'],runtime.final_journal['eventBytes'][i]) for i,item in enumerate(baseline_proof['drawReceipts']['files']))
        baseline_raw=read(capture.frames.path/'baseline.bgra',32*1024*1024)
        baseline_identity=capture.baseline.frozen.identity
        baseline=bridge.freeze_registration(capture.geometry_request_bytes,baseline_raw,baseline_identity.width,baseline_identity.height,
                capture.plan['sourceStride'],identity=baseline_identity,expected_frame_sha256=baseline_proof['baselineFrameSHA256'],
                event_files=event_files,expected_source_hashes=capture.bridge_sources)
        require(baseline.proof_bytes==capture.baseline.proof_bytes,'reconstructed baseline byte proof differs')
        replay_binding=bridge.RegistrationJoin(baseline,expected_baseline_proof_sha256=capture.baseline.proof_sha256).promote(
            capture.first_complete_bytes,capture.first_packed_bytes,expected_manifest_sha256=sha256(capture.first_complete_bytes).hexdigest(),timebase=capture.timebase)
        require(replay_binding.proof_bytes==capture.binding.proof_bytes,'reconstructed stream binding differs')
        frames=Directory(capture.frames.path)
        require(frames.identity==capture.frames.identity,'retained capture directory replaced')
        result_raw=frames.read('window-capture.json',32*1024*1024);require(result_raw is not None,'retained final helper result')
        result=parse(result_raw)
        require(read(runtime.output/'receipts/validate_collection.json',32*1024*1024)==result_raw,'retained validated helper result differs')
        require(result.get('session')==runtime.session and all(result.get(k) is True for k in
                ('captureCompleted','streamStopped','outputDetached','finalContextRetained','windowRevalidationPassed')) and
                not any(k in result for k in ('error','stopError','detachError')),'complete owned helper result')
        expected=parse(replay_binding.proof_bytes)['nativeStreamMetadata']
        geometry=(expected['contentRect'],expected['contentScale'],expected['scaleFactor'])
        records=packed_frames.inspect(result['samples'],capture.plan,timebase=capture.timebase,
                                      load=lambda name:frames.read(name,1024*1024),expected_geometry=geometry)
        frame_inventory(frames,records)
        report['finalContext']=final_context(frames,capture.plan,runtime.session)
        for phase in ('final','after-final-context'):
            raw=frames.read('window-census-'+phase+'.json',65536);require(raw is not None,'final owned window census missing')
            capture._census(raw,phase,capture.window_identity)
        report['stage']='registration-replay'
        proofs=replay_frames(replay_binding,records,folder/'frame-geometry',runtime.remaining)
        # The actual-byte replay has completed. Retain hashes/manifests, release
        # crop payloads before native decoding; final bytes are rehashed below.
        for row in records:row.pop('crops',None)
        command=Commands(runtime,folder/'commands');report['stage']='xcresult-export'
        bundle=Path(context['evidence']['prepare'].value['resultBundle'])
        export_folder=folder/'xcresult';export_folder.mkdir()
        controls,inputs,screenshots=runtime.video.export_case(command,bundle,export_folder,'timeout',runtime.device,evidence_joins.valid_png)
        attachments=export_folder/'attachments';manifest_raw=read(attachments/'manifest.json',8*1024*1024);manifest=parse(manifest_raw)
        files={r['exportedFileName']:read(attachments/r['exportedFileName']) for r in manifest[0]['attachments']}
        exports={'summaryBytes':command.stdout(['xcrun','xcresulttool','get','test-results','summary','--path',bundle]),
                 'testsBytes':command.stdout(['xcrun','xcresulttool','get','test-results','tests','--path',bundle]),
                 'manifestBytes':manifest_raw,'files':files}
        exported=evidence_joins.screenshot_exports(exports,runtime.device,inputs)
        report['stage']='control-ocr'
        ocr_input=evidence_joins.ocr_manifest(records,runtime.session)
        packed_paths=[frames.path/r['packedPixels'] for r in records if r['newFrame']]
        ocr=decoder(command,runtime,folder,'control',sources['control'],ocr_input,frames.path,packed_paths)
        report['stage']='independent-ocr'
        pngs={phase:files[exported[phase]['exportedFileName']] for phase in ('before','after')}
        independent_manifest=independent_input(events,controls,screenshots,pngs)
        independent=decoder(command,runtime,folder,'independent',sources['independent'],canonical(independent_manifest),
                            folder/'independent-crops',[Path(screenshots[p]) for p in ('before','after')])
        require(type(independent) is dict and independent.get('schema')=='p1-direct-independent-screenshots-v1' and
                independent.get('admissionEligible') is False,'independent decoder output schema')
        rows=independent['independentScreenshots']
        require(type(rows) is list and [r.get('phase') for r in rows]==['before','after'],'all independent decoded rows')
        enriched=[]
        for row in rows:
            phase=row['phase'];require(row.get('path')==screenshots[phase],'independent decoder actual path')
            require(not set(row)&set(exported[phase]),'decoder claims host byte-binding fields')
            enriched.append(dict(row,**exported[phase]))
        require(final_context(frames,capture.plan,runtime.session)==report['finalContext'],'final full-context changed during decoding')
        frame_inventory(frames,records)
        require(source_guard(runtime)==sources,'source changed during offline decoding')
        for phase in ('before','after'):require(read(Path(screenshots[phase]))==pngs[phase],'retained PNG changed after decode')
        require(frames.read('window-capture.json',32*1024*1024)==result_raw,'helper result changed during analysis')
        # Rehash every actual byte without making a second all-crop allocation.
        for row in records:
            runtime.remaining(1)
            if row['newFrame']:
                require(sha256(frames.read(row['packedPixels'],1024*1024)).hexdigest()==row['packedSHA256'],'retained frame bytes changed after replay')
        require({p:sha256(read(Path(p),256*1024)).hexdigest() for p in journal_hashes}==journal_hashes,'journal changed during offline decoding')
        report['stage']='conditional-timeout-analysis'
        analysis=timeout_case.inspect(clock_document=protocol['clockDocument'],expected_identity=identity,
                commands=protocol['commands'],raw_receipts=runtime.transport,events=events,
                strip=strip,controls=inputs,records=records,marker_proofs=proofs,
                ocr_input_bytes=ocr_input,ocr_result=ocr,independent=enriched,stream_binding_hash=replay_binding.proof_sha256,
                screenshot_exports=exports)
        runtime.remaining(1);require(all(r.get('settled') is True for r in runtime.scope.rows),'offline writers remain unsettled')
        report.update(completed=True,stage='complete',conditionalTimeoutResult=json_value(analysis),
                      streamBindingProofSHA256=replay_binding.proof_sha256,helperResultSHA256=sha256(result_raw).hexdigest())
        return report
    except BaseException as error:
        report['error']={'type':type(error).__name__,'message':str(error)}
        raise
    finally:
        if frames is not None:frames.close()
        runtime.ps.atomic(folder/'result.json',report)
