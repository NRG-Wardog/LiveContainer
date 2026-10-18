import copy
import contextlib
import errno
import io
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import os
import re
import shutil
import threading
import time
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import protocol
import analyze_capability as analysis
spec=importlib.util.spec_from_file_location('short_capability_capture',HERE/'capture.py');capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
import budget
import process_scope
SESSION='a'*32


def put(path,value):path.write_text(json.dumps(value,sort_keys=True,allow_nan=False))


def fixture(root):
    app=root/'raw-app';runner=root/'raw-runner';app.mkdir();runner.mkdir()
    put(app/'identity.json',dict(schema='p1-capability-app-v1',session=SESSION,bundleIdentifier=capture.APP_ID,admissionEligible=False))
    put(runner/'runner.json',dict(schema='p1-capability-runner-v1',session=SESSION,runnerBundleIdentifier=analysis.RUNNER_ID,expectedRequests=35,clockEquivalenceAssumed=False))
    app_times=[100.1+i*.08 for i in range(8)]+[102,103]+[103.1+i*.08 for i in range(8)]+[105,106]+[106.1+i*.08 for i in range(8)]+[108]
    app_rows=[];events=[]
    def event(event_type,uptime,**extra):return dict(type=event_type,session=SESSION,uptime=uptime,enqueuedUptime=uptime+.003,journalStartUptime=uptime+.004,**extra)
    events=[event('start',1099,scenario='capability'),event('baseline-ready',1100,afterUptime=1100.001,driver='normal-XCTest-fixture-ready-tap')]
    for request,h in zip(protocol.expected_app_requests(SESSION),app_times):
        response=dict(id=request['id'],session=SESSION,appReceive=h+1000+.001,appSend=h+1000+.002)
        if request['kind']!='clock':
            response['phase']=analysis.PHASES[request['kind']]
            events.append(event('command',response['appReceive'],afterUptime=response['appSend'],id=request['id'],kind=request['kind'],phase=response['phase']))
        app_rows.append(dict(request=request,hostBefore=h,hostAfter=h+.003,response=response))
        put(app/f'request-{request["id"]:03d}.json',request);put(app/f'response-{request["id"]:03d}.json',response)
    put(app/'request.json',app_rows[-1]['request']);put(app/'response.json',app_rows[-1]['response'])
    put(root/'app-channel.json',dict(schema='p1-capability-host-channel-v1',session=SESSION,role='app',rows=app_rows,admissionEligible=False))
    frames=[];draws=[]
    for i in range(502):
        h=99+i*.02
        frames.append(dict(index=i,pts=i*.02,endPTS=(i+1)*.02,marker=i+1))
        draws.append(dict(id=i+1,session=SESSION,tickBeforeUptime=h+1000-.002,tickAfterUptime=h+1000-.0018,drawBeforeUptime=h+1000-.0015,drawAfterUptime=h+1000-.0013,enqueuedUptime=h+1000-.001,journalStartUptime=h+1000-.0009,displayLinkTimestamp=h+1000-.002))
    writes=[dict(batch=i+1,beforeUptime=1109.025,afterUptime=1109.026) for i in range((len(draws)+29)//30)]
    complete=dict(schema='p1-strip-complete-v1',session=SESSION,drawCount=len(draws),batches=len(writes),stoppedUptime=1109.02,journalCompleteUptime=1109.03,writeCosts=writes,admissionEligible=False)
    for i in range(502,550):frames.append(dict(index=i,pts=i*.02,endPTS=(i+1)*.02,marker=502))
    put(app/'strip-complete.json',complete);complete_sha=protocol.sha(app/'strip-complete.json')
    strip=dict(complete=complete,draws=draws)
    copy_identity=dict(identifier='signin.prompt.copy-details',label='Copy Details',value='',exists=True,enabled=True,hittable=True,elementType=9,frame=[10,100,200,44])
    def receipt(name,request_id,phase,ordinal,h):
        png=b'PNG-'+name.encode();(runner/(name+'.png')).write_bytes(png)
        row=dict(schema='p1-capability-capture-v1',session=SESSION,runnerBundleIdentifier=analysis.RUNNER_ID,requestId=request_id,name=name,phase=phase,ordinal=ordinal,
            clock='runner-ProcessInfo.systemUptime',clockEquivalenceAssumed=False,acquisitionBefore=h+2000,acquisitionAfter=h+2000+.003,encodingBefore=h+2000+.004,encodingAfter=h+2000+.005,
            attachmentBefore=h+2000+.006,attachmentAfter=h+2000+.007,pngWriteBefore=h+2000+.008,pngWriteAfter=h+2000+.009,
            copyBefore=copy_identity,copyAfter=copy_identity,markerFrameBefore=[0,0,240,16],markerFrameAfter=[0,0,240,16],windowFrameBefore=[0,0,390,844],windowFrameAfter=[0,0,390,844],
            pngSHA256=hashlib.sha256(png).hexdigest(),pngBytes=len(png),admissionEligible=False,timingFeasibilityEstablished=False)
        put(runner/(name+'.json'),row);return row
    receipt('capture-baseline',0,'baseline',0,99.8)
    put(runner/'ready.json',dict(session=SESSION,baselineDriver='normal-XCTest-fixture-ready-tap',baselineTapBefore=2099.9,baselineTapAfter=2100.05))
    requests=protocol.expected_runner_requests(SESSION);requests[-1].update(appStripCompleteSHA256=complete_sha,hostVerifiedStripComplete=True)
    rows=[];screens=[]
    for request in requests:
        i=request['id'];phase=request.get('phase');kind=request['kind']
        if i<=33:
            start={'pre':100,'mid':103,'post':106}[phase]
            h=start+.8+((i-1)%11)*.01 if kind=='clock' else start+1.1+(request['ordinal']-1)*.2
        else:h=109.1 if i==34 else 110.1
        response=dict(schema='p1-capability-response-v1',session=SESSION,runnerBundleIdentifier=analysis.RUNNER_ID,id=i,kind=kind,
            runnerReceive=h+2000-.001,runnerSend=h+2000+.010,clock='runner-ProcessInfo.systemUptime',clockEquivalenceAssumed=False,admissionEligible=False)
        if phase is not None:response['phase']=phase
        if kind=='capture':
            response['ordinal']=request['ordinal'];name=f'capture-{phase}-{request["ordinal"]}'
            receipt(name,i,phase,request['ordinal'],h);response.update(png=name+'.png',receipt=name+'.json')
            marker=round((h-99)/.02)+1;screens.append(dict(id=len(screens)+1,decodedMarker=marker,label='Copy Details'))
        elif kind=='after':receipt('capture-after',34,'after',0,h);response.update(png='capture-after.png',receipt='capture-after.json')
        elif kind=='complete':
            response['completion']='completion.json'
            put(runner/'completion.json',dict(schema='p1-capability-complete-v1',session=SESSION,appStripCompleteSHA256=complete_sha,hostVerifiedStripComplete=True,id=35,runnerAckUptime=h+2000,admissionEligible=False))
        if kind=='clock':response['runnerSend']=h+2000+.001
        rows.append(dict(request=request,hostBefore=h-.002,hostAfter=h+(.002 if kind=='clock' else .011),response=response))
        put(runner/f'request-{i:04d}.json',request);put(runner/f'response-{i:04d}.json',response)
    put(runner/'request.json',rows[-1]['request']);put(runner/'response.json',rows[-1]['response'])
    put(root/'runner-channel.json',dict(schema='p1-capability-host-channel-v1',session=SESSION,role='runner',rows=rows,admissionEligible=False))
    decoded=dict(schema='p1-calibration-decoded-v1',admissionEligible=False,frames=frames,screenshots=screens,observations=[],independentScreenshots=[dict(phase='before',decodedMarker=41,label='Copy Details'),dict(phase='after',decodedMarker=502,label='Copy Details')])
    decode_input={'screenshots':[],'independentScreenshots':[]}
    for index,row in enumerate(decoded['screenshots']):
        phase=['pre','mid','post'][index//3];name=f'capture-{phase}-{index%3+1}.png';row['path']=str(runner/name);row['pngSHA256']=protocol.sha(runner/name);decode_input['screenshots'].append({'id':index+1,'path':row['path']})
    for row,name in zip(decoded['independentScreenshots'],['capture-baseline.png','capture-after.png']):
        row['path']=str(runner/name);row['pngSHA256']=protocol.sha(runner/name);decode_input['independentScreenshots'].append({'phase':row['phase'],'path':row['path']})
    put(root/'decode-input.json',decode_input)
    witness_ids={r['decodedMarker'] for r in decoded['screenshots']+decoded['independentScreenshots']}
    decoded['observations']=[dict(f,label='Copy Details') for f in frames if f['marker'] in witness_ids]
    return decoded,events,strip


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.decoded,self.events,self.strip=fixture(self.root)
    def inspect(self):return analysis.inspect(self.root,SESSION,self.decoded,self.events,self.strip)
    def change_json(self,name,fn):
        path=self.root/name;value=protocol.parse(path);fn(value);put(path,value)
    def reject(self,fn):
        fn()
        with self.assertRaises((ValueError,KeyError,TypeError)):self.inspect()
    def test_positive_separate_clock_calibration(self):
        row=self.inspect();self.assertTrue(row['calibration_feasible']);self.assertFalse(row['admissionEligible']);self.assertFalse(row['feedback_lifetime_established']);self.assertFalse(row['input_overlap_established'])
        self.assertLess(row['appMinusVideoPTS'][1]-row['appMinusVideoPTS'][0],.120)
        self.assertGreater(row['runnerMinusHost'][0],1999)
    def test_missing_runner_row(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'].pop()))
    def test_duplicate_runner_row(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'].insert(0,r['rows'][0])))
    def test_reordered_runner_rows(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'].reverse()))
    def test_changed_response(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'][0]['response'].update(runnerSend=0)))
    def test_changed_exchange_id(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'][0]['request'].update(id=2)))
    def test_boolean_id(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r['rows'][0]['request'].update(id=True)))
    def test_wrong_nonce(self):self.reject(lambda:self.change_json('runner-channel.json',lambda r:r.update(session='b'*32)))
    def test_missing_durable_row(self):self.reject(lambda:(self.root/'raw-runner/request-0001.json').unlink())
    def test_mutated_durable_response(self):self.reject(lambda:self.change_json('raw-runner/response-0001.json',lambda r:r.update(id=9)))
    def test_extra_durable_row(self):self.reject(lambda:put(self.root/'raw-runner/request-0036.json',{}))
    def test_unacknowledged_completion(self):self.reject(lambda:self.change_json('raw-runner/completion.json',lambda r:r.update(hostVerifiedStripComplete=False)))
    def test_wrong_completion_hash(self):self.reject(lambda:self.change_json('raw-runner/completion.json',lambda r:r.update(appStripCompleteSHA256='0'*64)))
    def test_wrong_bundle(self):self.reject(lambda:self.change_json('raw-runner/runner.json',lambda r:r.update(runnerBundleIdentifier='other')))
    def test_clock_equivalence_claim(self):self.reject(lambda:self.change_json('raw-runner/capture-pre-1.json',lambda r:r.update(clockEquivalenceAssumed=True)))
    def test_capture_png_drift(self):self.reject(lambda:(self.root/'raw-runner/capture-pre-1.png').write_bytes(b'changed'))
    def test_capture_encoding_inside_acquisition(self):self.reject(lambda:self.change_json('raw-runner/capture-pre-1.json',lambda r:r.update(encodingBefore=r['acquisitionBefore'])))
    def test_capture_label_changed(self):self.reject(lambda:self.change_json('raw-runner/capture-pre-1.json',lambda r:r['copyAfter'].update(label='Copied')))
    def test_wrong_decoded_png_path(self):self.reject(lambda:self.decoded['screenshots'][0].update(path='/other.png'))
    def test_wrong_decoded_png_hash(self):self.reject(lambda:self.decoded['screenshots'][0].update(pngSHA256='0'*64))
    def test_wrong_independent_png_hash(self):self.reject(lambda:self.decoded['independentScreenshots'][1].update(pngSHA256='0'*64))
    def test_wrong_decode_input_path(self):self.reject(lambda:self.change_json('decode-input.json',lambda r:r['screenshots'][0].update(path='/other.png')))
    def test_wrong_after_acquisition(self):self.reject(lambda:self.change_json('raw-runner/capture-after.json',lambda r:r.update(acquisitionBefore=1)))
    def test_missing_video_pixel_witness(self):self.reject(lambda:self.decoded['observations'].pop())
    def test_unknown_video_pixel_witness(self):self.reject(lambda:self.decoded['observations'][0].update(label='unknown'))
    def test_missing_pixel_label(self):self.reject(lambda:self.decoded['screenshots'][0].update(label='unknown'))
    def test_reused_marker_id(self):self.reject(lambda:self.decoded['screenshots'][1].update(decodedMarker=self.decoded['screenshots'][0]['decodedMarker']))
    def test_unknown_video_marker_in_window(self):self.reject(lambda:self.decoded['frames'][200].update(marker=None))
    def test_reordered_pts(self):self.reject(lambda:self.decoded['frames'][200].update(pts=0))
    def test_oversized_frame_gap(self):self.reject(lambda:self.decoded['frames'][200].update(endPTS=20))
    def test_missing_baseline(self):self.reject(lambda:self.events.pop(1))
    def test_unexpected_copy_action(self):self.reject(lambda:self.events.append(dict(type='clipboard',session=SESSION)))
    def test_wrong_strip_session(self):self.reject(lambda:self.strip['draws'][0].update(session='b'*32))
    def test_expensive_strip(self):self.reject(lambda:self.strip['draws'][100].update(drawBeforeUptime=self.strip['draws'][100]['drawAfterUptime']-.006))
    def test_stale_after_pixels(self):self.reject(lambda:self.decoded['independentScreenshots'][1].update(decodedMarker=1))
    def test_missing_app_transport(self):self.reject(lambda:self.change_json('app-channel.json',lambda r:r['rows'].pop()))
    def test_cross_domain_times_not_assumed_equal(self):
        result=self.inspect();self.assertGreater(result['runnerMinusHost'][0]-result['appMinusHost'][0],999)


class BoundaryTests(unittest.TestCase):
    def test_protocol_inventory(self):
        self.assertEqual(len(protocol.expected_app_requests(SESSION)),29);self.assertEqual(len(protocol.expected_runner_requests(SESSION)),35)
    def test_duplicate_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()/'x';p.write_text('{"id":1,"id":1}')
            with self.assertRaises(ValueError):protocol.parse(p)
    def test_linked_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()/'x';p.write_text('{}');q=Path(tmp).resolve()/'q';q.symlink_to(p)
            with self.assertRaises(ValueError):protocol.parse(q)
    def test_stale_channel_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'request.json').write_text('{}')
            with self.assertRaises(ValueError):protocol.Channel(root,SESSION,'runner',root/'out')
    def test_protocol_canonical_without_newline(self):self.assertEqual(protocol.canonical({'kind':'clock','id':1}),b'{"id":1,"kind":"clock"}')
    def test_runner_recipe_injects_only_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();products=root/'products';info=products/'Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist';info.parent.mkdir(parents=True);info.write_bytes(plistlib.dumps({'CFBundleIdentifier':analysis.RUNNER_ID}))
            candidate=products/'a.xctestrun';candidate.write_bytes(plistlib.dumps({'Tests':{'TestBundlePath':'P0SignInUITests.xctest','IsUITestBundle':True}}));out=root/'out';out.mkdir()
            p=capture.configure_runner(candidate,products,SESSION,out);self.assertEqual(plistlib.loads(p.read_bytes())['Tests']['EnvironmentVariables']['P1_CAPABILITY_SESSION'],SESSION)
    def test_runner_recipe_rejects_wrong_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();info=root/'Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist';info.parent.mkdir(parents=True);info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'other'}))
            with self.assertRaises(ValueError):capture.configure_runner(root/'a',root,SESSION,root)
    def test_budget_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp).resolve()/'evidence'
            script=f'import sys;sys.path.insert(0,{str(HERE)!r});from pathlib import Path;import process_scope;p=Path({str(out)!r});p.mkdir();s=process_scope.Scope(p);s.close();raise SystemExit(7)'
            self.assertEqual(budget.run([sys.executable,'-B','-c',script],out),7)
            self.assertEqual(protocol.parse(out/'outer-budget.json')['exit_code'],7);self.assertIn('outer-budget.json',protocol.parse(out/'evidence-index.json')['files'])
    def test_budget_timeout_reaps_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            process=mock.Mock(pid=123,returncode=None);process.poll.side_effect=budget.subprocess.TimeoutExpired('x',1200);(Path(tmp).resolve()/'e').mkdir();put(Path(tmp).resolve()/'e/process-registry.json',{})
            with mock.patch.object(budget.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'stop_group',return_value=True) as stop, mock.patch.object(budget,'verify_quiescence'):
                self.assertEqual(budget.run(['x'],Path(tmp).resolve()/'e'),124);self.assertTrue(stop.called);self.assertEqual(stop.call_args.args[0],123);self.assertIs(stop.call_args.args[1]._process,process)
    def test_fixed_outer_budget(self):
        with self.assertRaises(ValueError):budget.run([],Path('/tmp/no'),seconds=1)

class SealsAndExports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
    def sealed(self):
        host=self.root/'host';host.mkdir();original=HERE.parents[2]
        for relative in capture.ADAPTERS:
            target=host/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/relative,target)
        data=dict(schema='p1-short-capability-inputs-v1',scope='phone-recovery-capability-only-no-admission',livecontainer=capture.SOURCE,builder=capture.BUILDER,source_sha256=capture.SOURCE_SHA,adapter_files={n:capture.sha(host/n) for n in capture.ADAPTERS})
        path=host/'inputs.json';put(path,data);return host,path,data
    def test_real_seal(self):
        host,path,data=self.sealed();self.assertEqual(capture.validate(host,path,capture.sha(path)),data)
    def test_unapproved_seal(self):
        host,path,data=self.sealed()
        with self.assertRaises(ValueError):capture.validate(host,path,'0'*64)
    def test_changed_adapter_seal(self):
        host,path,data=self.sealed();(host/'ci/p1/preflight/app.swift').write_text('changed')
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def test_wrong_scope_seal(self):
        host,path,data=self.sealed();data['scope']='full';put(path,data)
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def test_wrong_pin_seal(self):
        host,path,data=self.sealed();data['livecontainer']=dict(data['livecontainer'],commit='0'*40);put(path,data)
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def test_missing_inventory_seal(self):
        host,path,data=self.sealed();data['adapter_files'].pop('ci/p1/preflight/app.swift');put(path,data)
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def test_linked_adapter_seal(self):
        host,path,data=self.sealed();p=host/'ci/p1/preflight/app.swift';p.unlink();p.symlink_to(HERE/'app.swift')
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def test_linked_host_seal(self):
        host,path,data=self.sealed();link=self.root/'link';link.symlink_to(host)
        with self.assertRaises(ValueError):capture.validate(link,path,capture.sha(path))
    def test_duplicate_key_seal(self):
        host,path,data=self.sealed();path.write_text(path.read_text()[:-1]+',"schema":"p1-short-capability-inputs-v1"}')
        with self.assertRaises(ValueError):capture.validate(host,path,capture.sha(path))
    def exports(self):
        decoded,events,strip=fixture(self.root);root=self.root/'attachments';root.mkdir()
        expected=capture.CLASS+'/'+capture.METHOD+'()';url='test://com.apple.xcode/P0SignIn/P0SignInUITests/'+capture.CLASS+'/'+capture.METHOD
        summary=dict(result='Passed',passedTests=1,failedTests=0,skippedTests=0,totalTestCount=1,expectedFailures=0,devicesAndConfigurations=[{'device':{'deviceId':'device'}}]);tests={'nodeType':'Test Case','nodeIdentifier':expected,'result':'Passed','nodeIdentifierURL':url}
        attachments=[]
        for p in sorted((self.root/'raw-runner').glob('*.png')):
            shutil.copy2(p,root/p.name);attachments.append(dict(deviceId='device',exportedFileName=p.name,suggestedHumanReadableName=p.stem))
        manifest=[dict(testIdentifier=expected,testIdentifierURL=url,attachments=attachments)];put(root/'manifest.json',manifest)
        return root,summary,tests,manifest
    def verify(self,root,summary,tests):return capture.verify_exports(root,summary,tests,self.root/'raw-runner','device',SESSION,lambda data:data.startswith(b'PNG-'))
    def test_exact_raw_export(self):
        root,summary,tests,_=self.exports();self.assertEqual(len(self.verify(root,summary,tests)),11)
    def test_wrong_export_method(self):
        root,summary,tests,_=self.exports();tests['nodeIdentifier']='other'
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_skipped_export(self):
        root,summary,tests,_=self.exports();summary['skippedTests']=1
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_boolean_export_count(self):
        root,summary,tests,_=self.exports();summary['passedTests']=True
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_wrong_attachment_device(self):
        root,summary,tests,m=self.exports();m[0]['attachments'][0]['deviceId']='other';put(root/'manifest.json',m)
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_wrong_attachment_method(self):
        root,summary,tests,m=self.exports();m[0]['testIdentifier']='other';put(root/'manifest.json',m)
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_duplicate_attachment(self):
        root,summary,tests,m=self.exports();m[0]['attachments'].append(m[0]['attachments'][0]);put(root/'manifest.json',m)
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_missing_attachment(self):
        root,summary,tests,m=self.exports();m[0]['attachments'].pop();put(root/'manifest.json',m)
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_changed_attachment_bytes(self):
        root,summary,tests,m=self.exports();(root/m[0]['attachments'][0]['exportedFileName']).write_bytes(b'PNG-changed')
        with self.assertRaises(ValueError):self.verify(root,summary,tests)
    def test_exact_generated_source(self):
        source=os.environ.get('MAINTAINED_LIVE_CONTAINER_TEST_SOURCE');builder=os.environ.get('P1_FROZEN_BUILDER_TEST_SOURCE')
        if not source or not builder:
            # The workflow runs this source-dependent contract after acquisition;
            # portable API/negative checks do not silently claim its execution.
            self.skipTest('exact source/builder environment required')
        output=self.root/'output';output.mkdir();project,_=capture.prepare(Path(source)/capture.base.SHELL,Path(builder),self.root/'build',output)
        generated=(output/'sources/p0_signin_app.swift').read_text();self.assertEqual(generated.count('@main'),1)
        for fragment in capture.video.extract.fragments((Path(source)/capture.base.SHELL).read_text()).values():self.assertIn(fragment.rstrip('\n'),generated)
        for p in (output/'sources').glob('*.swift'):self.assertEqual(re.findall(r'(?<![\w.])\.[0-9]+',p.read_text()),[],str(p))
        info=plistlib.loads((project/'Info.plist').read_bytes());self.assertEqual(info['UISupportedInterfaceOrientations'],info['UISupportedInterfaceOrientations~ipad']);self.assertEqual(len(info['UISupportedInterfaceOrientations~ipad']),4)
        self.assertIn((HERE/'runner_ui_tests.swift').read_text(),(output/'sources/p0_signin_ui_tests.swift').read_text())


class LiveChannelTests(unittest.TestCase):
    def exercise(self,mode):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();channel=protocol.Channel(root,SESSION,'runner',root/'host.json');errors=[]
            def worker():
                try:
                    deadline=time.monotonic()+1
                    while not (root/'request.json').exists() and time.monotonic()<deadline:time.sleep(.001)
                    request=protocol.parse(root/'request.json');response=dict(session=SESSION,id=1)
                    if mode=='nonce':response['session']='b'*32
                    if mode=='boolean':response['id']=True
                    if mode!='missing':
                        protocol.atomic(root/'request-0001.json',request);protocol.atomic(root/'response-0001.json',response)
                    protocol.atomic(root/'response.json',response)
                except Exception as e:errors.append(e)
            thread=threading.Thread(target=worker);thread.start()
            try:
                if mode=='valid':self.assertEqual(channel.request('clock',phase='pre',timeout=.5)['id'],1)
                else:
                    with self.assertRaises(ValueError):channel.request('clock',phase='pre',timeout=.5)
            finally:thread.join()
            self.assertFalse(errors);self.assertEqual(len(protocol.parse(root/'host.json')['rows']),1)
    def test_real_durable_exchange(self):self.exercise('valid')
    def test_response_before_durable_rows(self):self.exercise('missing')
    def test_wrong_session_response(self):self.exercise('nonce')
    def test_boolean_response_id(self):self.exercise('boolean')

class ProcessQuiescenceTests(unittest.TestCase):
    def test_internal_deadline_reaps_separate_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();logs=root/'logs';logs.mkdir();scope=process_scope.Scope(root);scope.deadline=time.monotonic()+.15;command=process_scope.Commands(scope,logs);target=root/'writer'
            script="import time;f=open(%r,'a');\nwhile True:f.write('x');f.flush();time.sleep(.005)" % str(target)
            with self.assertRaises(Exception):command(sys.executable,'-B','-c',script,timeout=10)
            scope.close();self.assertTrue(protocol.parse(root/'quiescence.json')['quiescent'])
            before=target.read_bytes();time.sleep(.05);self.assertEqual(target.read_bytes(),before)
    def test_exec_cannot_start_before_durable_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();scope=process_scope.Scope(root);target=root/'started';original=scope.persist;seen=[]
            def persist():
                seen.append(target.exists());time.sleep(.03);self.assertFalse(target.exists());original()
            with (root/'stdout').open('wb') as f,mock.patch.object(scope,'persist',side_effect=persist):
                process=scope.spawn([sys.executable,'-B','-c',f"open({str(target)!r},'w').write('x')"],f)
            process.wait(timeout=2);scope.settle(process);scope.close();self.assertEqual(seen,[False]);self.assertTrue(target.exists())
    def test_failed_registry_write_never_executes_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();scope=process_scope.Scope(root);target=root/'started'
            with (root/'stdout').open('wb') as f,mock.patch.object(scope,'persist',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):scope.spawn([sys.executable,'-B','-c',f"open({str(target)!r},'w').write('x')"],f)
            time.sleep(.03);self.assertFalse(target.exists());scope.close()
    def orphaned_writer_case(self,timed_out):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'e';ready=Path(tmp).resolve()/'ready';stop=Path(tmp).resolve()/'stop';done=Path(tmp).resolve()/'done';writer=root/'active-writer'
            # The fixture cooperatively cleans its orphan with a sentinel and
            # self-expiry. Tests do not signal recycled numeric identities.
            writer_script=f"import time;from pathlib import Path;f=open({str(writer)!r},'a');end=time.monotonic()+20;Path({str(ready)!r}).write_text('ready');\nwhile not Path({str(stop)!r}).exists() and time.monotonic()<end:f.write('x');f.flush();time.sleep(.005)\nf.close();Path({str(done)!r}).write_text('done')"
            script=f"import sys,time;sys.path.insert(0,{str(HERE)!r});from pathlib import Path;import process_scope;r=Path({str(root)!r});r.mkdir();s=process_scope.Scope(r);f=(r/'child.log').open('wb');s.spawn([sys.executable,'-B','-c',{writer_script!r}],f);\nwhile not Path({str(ready)!r}).exists():time.sleep(.005)\n"+('time.sleep(60)' if timed_out else 'raise SystemExit(9)')
            original_wait=process_scope.OwnedProcess.wait;first=[timed_out]
            def wait(child,timeout=None):
                if first[0]:
                    first[0]=False;deadline=time.monotonic()+3
                    while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue(ready.exists());raise budget.subprocess.TimeoutExpired('collector',1200)
                return original_wait(child,timeout)
            try:
                with mock.patch.object(process_scope.OwnedProcess,'wait',wait),mock.patch.object(budget,'index') as index:self.assertEqual(budget.run([sys.executable,'-B','-c',script],root),1)
                index.assert_not_called();self.assertFalse((root/'evidence-index.json').exists());outcome=protocol.parse(root/'outer-budget.json');self.assertFalse(outcome['transport_safe'])
                before=writer.stat().st_size;time.sleep(.03);self.assertGreater(writer.stat().st_size,before)
                with self.assertRaises((ValueError,FileNotFoundError)):budget.check_package(root)
                if timed_out:self.assertEqual(outcome['primary_error']['type'],'TimeoutExpired')
            finally:
                stop.write_text('stop');deadline=time.monotonic()+3
                while ready.exists() and not done.exists() and time.monotonic()<deadline:time.sleep(.01)
                if ready.exists():self.assertTrue(done.exists(),'fixture writer failed its sentinel cleanup')
    def test_outer_timeout_rejects_unowned_detached_writer_before_index(self):self.orphaned_writer_case(True)
    def test_crashed_collector_rejects_unowned_registered_writer(self):self.orphaned_writer_case(False)
    def test_missing_registry_blocks_index_and_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'e'
            self.assertEqual(budget.run([sys.executable,'-c','raise SystemExit(0)'],root),1)
            self.assertFalse((root/'evidence-index.json').exists())
            with self.assertRaises((ValueError,FileNotFoundError)):budget.check_package(root)

class CleanupAndDeadlineTests(unittest.TestCase):
    def test_observed_exact_already_stopped_receipt(self):
        identifier=capture.APP_ID
        text=(f'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\nSimulator device failed to terminate {identifier}.\nfound nothing to terminate\nUnderlying error (domain=NSPOSIXErrorDomain, code=3):\n\tThe request to terminate "{identifier}" failed. found nothing to terminate\n\tfound nothing to terminate\n')
        row=dict(exit_code=3,failure_type='CalledProcessError',stdout='',stderr=text)
        self.assertTrue(capture.stopped_response(row,identifier));self.assertFalse(capture.stopped_response(row,capture.RUNNER_ID))
        row['stderr']+='uncertain';self.assertFalse(capture.stopped_response(row,identifier))
    def test_unknown_termination_is_not_stopped(self):
        for row in [dict(exit_code=None),dict(exit_code=1,failure_type='CalledProcessError'),dict(exit_code=0,failure_type='TimeoutExpired')]:self.assertFalse(capture.stopped_response(row,capture.APP_ID))
    def test_termination_failure_uses_owned_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            device='12345678-1234-1234-1234-123456789abc';scope=mock.Mock();scope.fixture={'owned_boot':True};command=mock.Mock();command.scope=scope
            state=lambda name:dict(exit_code=0,failure_type=None,stdout=json.dumps({'devices':{'runtime':[{'udid':device,'state':name}]}}))
            command.side_effect=[dict(exit_code=1),dict(exit_code=1),state('Booted'),dict(exit_code=0,failure_type=None),state('Shutdown')]
            self.assertTrue(capture.stop_fixture(command,device,Path(tmp).resolve()));scope.fixture_stopped.assert_called_once_with(True);scope.fixture_cleanup_failure.assert_not_called()
            self.assertEqual(command.call_args_list[3].args,('xcrun','simctl','shutdown',device));self.assertEqual(command.call_args_list[4].args,('xcrun','simctl','list','devices','--json'))
    def test_unowned_simulator_unknown_cleanup_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=mock.Mock();scope.fixture={'owned_boot':False};command=mock.Mock(return_value={'exit_code':1});command.scope=scope
            self.assertFalse(capture.stop_fixture(command,'device',Path(tmp).resolve()));self.assertEqual(command.call_count,2)
    def test_channel_shared_deadline_prevents_new_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();remaining=mock.Mock(side_effect=TimeoutError('deadline'));channel=protocol.Channel(root,SESSION,'runner',root/'out',remaining)
            with self.assertRaises(TimeoutError):channel.request('clock',phase='pre')
            self.assertFalse((root/'request.json').exists());remaining.assert_called_once_with(20)
    def test_file_wait_shared_deadline(self):
        remaining=mock.Mock(side_effect=TimeoutError('deadline'))
        with self.assertRaises(TimeoutError):capture.await_file(Path('/tmp/no-channel-file'),10,remaining=remaining)
        remaining.assert_called_once_with(10)
    def test_scope_close_rejects_live_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=process_scope.Scope(Path(tmp).resolve());scope.fixture_identity('device',False)
            with self.assertRaises(RuntimeError):scope.close()
            self.assertFalse(protocol.parse(Path(tmp).resolve()/'quiescence.json')['quiescent'])
    def test_execute_cleanup_guard_retains_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();scope=mock.Mock();command=mock.Mock(side_effect=RuntimeError('command failure'));command.scope=scope
            result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            with mock.patch.object(capture,'stop_fixture',side_effect=RuntimeError('termination failed')):
                capture.finalize(root,result,command,scope,'device',True)
            scope.close.assert_called_once();self.assertFalse(result['capabilities_passed']);self.assertTrue((root/'capability-result.json').exists())
    def test_quiescence_failure_retains_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=mock.Mock();scope.close.side_effect=RuntimeError('still writing');result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            capture.finalize(Path(tmp).resolve(),result,None,scope,None,False)
            self.assertFalse(result['collection_complete']);self.assertIn('quiescence: still writing',result['errors']);self.assertTrue((Path(tmp).resolve()/'capability-result.json').exists())

class FailureDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.command_count=0
    def diagnostics(self,text):
        prefix='P1_CAPABILITY_DIAGNOSTIC '
        rows=[json.loads(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
        for row in rows:
            self.assertEqual(row['schema'],'p1-capability-console-diagnostic-v1');self.assertIs(row['admissionEligible'],False)
        return rows
    def group_error(self,operation='SIGTERM',pgid=4321):
        snapshot={'available':True,'pgid':pgid,'rows':[{'pid':pgid,'ppid':2,'pgid':pgid,'uid':501,'state':'S','comm':'fixture'}],'truncated':False}
        with mock.patch.object(process_scope,'membership_snapshot',return_value=snapshot),mock.patch.object(process_scope,'emit_diagnostic'):
            return process_scope.GroupOperationError(operation,pgid,PermissionError(errno.EPERM,'private exception detail'))
    def command_result(self,primary=None,cleanup=None,receipt=False,allow_failure=False,returncode=0,spawn_error=None):
        self.command_count+=1;logs=self.root/str(self.command_count);logs.mkdir()
        process=mock.Mock(pid=4321,returncode=returncode);process.wait.side_effect=primary
        scope=mock.Mock();scope.remaining.return_value=7.5;scope.spawn.return_value=process
        scope.spawn.side_effect=spawn_error;scope.settle.side_effect=cleanup
        command=process_scope.Commands(scope,logs);console=io.StringIO();result=None;raised=None
        with contextlib.redirect_stdout(console):
            try:result=command('fixture-command',timeout=30,receipt=receipt,allow_failure=allow_failure)
            except Exception as error:raised=error
        rows=[json.loads(line) for line in (logs/'commands.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),1)
        return result,raised,rows[0],self.diagnostics(console.getvalue()),scope
    def test_command_cleanup_does_not_mask_primary_exception(self):
        primary=process_scope.subprocess.TimeoutExpired(['private-argv'],7.5);cleanup=self.group_error()
        _,raised,row,diagnostics,scope=self.command_result(primary,cleanup)
        self.assertIs(raised,primary);self.assertEqual(row['error'],str(primary));scope.settle.assert_called_once()
        self.assertEqual(row['primary_error'],{'type':'TimeoutExpired','timeout_seconds':7.5})
        self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic])
        self.assertEqual(diagnostics[0]['phase'],'command-failure');self.assertEqual(diagnostics[0]['primary_error'],row['primary_error'])
        self.assertEqual(diagnostics[0]['cleanup_errors'],row['cleanup_errors']);self.assertNotIn('private-',json.dumps(diagnostics))
    def test_command_receipt_retains_primary_and_cleanup(self):
        primary=PermissionError(errno.EPERM,'wait denied');cleanup=self.group_error('probe')
        receipt,raised,row,diagnostics,_=self.command_result(primary,cleanup,receipt=True)
        self.assertIsNone(raised);self.assertEqual(receipt['failure_type'],'PermissionError')
        self.assertEqual(receipt['primary_error'],{'type':'PermissionError','errno':errno.EPERM})
        self.assertEqual(receipt['cleanup_errors'],[cleanup.diagnostic])
        self.assertEqual(receipt['primary_error'],row['primary_error']);self.assertEqual(receipt['cleanup_errors'],row['cleanup_errors'])
        self.assertEqual(diagnostics[0]['pgid'],4321)
    def test_command_primary_only_has_empty_cleanup(self):
        primary=RuntimeError('primary wait failed')
        _,raised,row,_,_=self.command_result(primary)
        self.assertIs(raised,primary);self.assertEqual(row['primary_error'],{'type':'RuntimeError'});self.assertEqual(row['cleanup_errors'],[])
    def test_command_nonzero_exit_retains_returncode(self):
        receipt,raised,row,_,_=self.command_result(returncode=23,receipt=True)
        self.assertIsNone(raised);self.assertEqual(receipt['failure_type'],'CalledProcessError')
        self.assertEqual(row['primary_error'],{'type':'CalledProcessError','returncode':23});self.assertEqual(row['cleanup_errors'],[])
    def test_command_cleanup_only_is_failure(self):
        cleanup=self.group_error('wait')
        _,raised,row,_,_=self.command_result(cleanup=cleanup)
        self.assertIs(raised,cleanup);self.assertIsNone(row['primary_error']);self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic])
        receipt,raised,row,_,_=self.command_result(cleanup=cleanup,receipt=True)
        self.assertIsNone(raised);self.assertEqual(receipt['failure_type'],'GroupOperationError');self.assertEqual(receipt['cleanup_errors'],row['cleanup_errors'])
    def test_command_success_has_no_failure_diagnostics(self):
        receipt,raised,row,diagnostics,_=self.command_result(receipt=True)
        self.assertIsNone(raised);self.assertIsNone(receipt['failure_type']);self.assertIsNone(receipt['primary_error']);self.assertEqual(receipt['cleanup_errors'],[])
        self.assertIsNone(row['error']);self.assertIsNone(row['primary_error']);self.assertEqual(row['cleanup_errors'],[]);self.assertEqual(diagnostics,[])
    def test_allowed_failure_still_retains_both_errors(self):
        primary=process_scope.subprocess.TimeoutExpired('private-command',7.5);cleanup=self.group_error()
        result,raised,row,diagnostics,_=self.command_result(primary,cleanup,allow_failure=True)
        self.assertEqual(result,'');self.assertIsNone(raised);self.assertTrue(row['allowed_failure'])
        self.assertEqual(row['primary_error']['type'],'TimeoutExpired');self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic]);self.assertEqual(len(diagnostics),1)
    def test_command_spawn_failure_does_not_invent_cleanup(self):
        primary=FileNotFoundError(errno.ENOENT,'missing private path')
        _,raised,row,diagnostics,scope=self.command_result(spawn_error=primary)
        self.assertIs(raised,primary);scope.settle.assert_not_called();self.assertIsNone(row['exit_code']);self.assertIsNone(diagnostics[0]['pgid'])
        self.assertEqual(row['primary_error'],{'type':'FileNotFoundError','errno':errno.ENOENT});self.assertEqual(row['cleanup_errors'],[])
    def test_eperm_probe_never_means_group_absent(self):
        console=io.StringIO();snapshot={'available':False,'pgid':4321,'rows':[],'truncated':False}
        with mock.patch.object(process_scope.os,'killpg',side_effect=PermissionError(errno.EPERM,'denied')) as killpg,mock.patch.object(process_scope,'membership_snapshot',return_value=snapshot),contextlib.redirect_stdout(console):
            with self.assertRaises(process_scope.GroupOperationError) as raised:process_scope.stop_group(4321)
        killpg.assert_called_once_with(4321,0)
        self.assertEqual(raised.exception.errno,errno.EPERM);self.assertEqual(raised.exception.diagnostic,{'type':'PermissionError','errno':errno.EPERM,'operation':'probe','pgid':4321,'membership':snapshot})
        self.assertEqual(self.diagnostics(console.getvalue())[0]['phase'],'process-group-failure')
    def test_eperm_signals_preserve_operation(self):
        for operation in ['SIGTERM','SIGKILL']:
            with self.subTest(operation=operation):
                raw=mock.Mock(pid=4321,returncode=None);raw.poll.return_value=None;child=process_scope.OwnedProcess(raw);calls=[];console=io.StringIO()
                def killpg(group,kind):
                    calls.append((group,kind))
                    if kind==getattr(process_scope.signal,operation):raise PermissionError(errno.EPERM,'denied')
                with mock.patch.object(process_scope,'alive',return_value=True),mock.patch.object(child,'wait',side_effect=process_scope.subprocess.TimeoutExpired('fixture',2)),mock.patch.object(process_scope.os,'killpg',side_effect=killpg),mock.patch.object(process_scope,'membership_snapshot',return_value={'available':False,'rows':[]}),contextlib.redirect_stdout(console):
                    with self.assertRaises(process_scope.GroupOperationError) as raised:process_scope.stop_group(child.pid,child)
                self.assertEqual(raised.exception.diagnostic['operation'],operation);self.assertEqual(raised.exception.diagnostic['errno'],errno.EPERM);self.assertEqual(calls[-1],(child.pid,getattr(process_scope.signal,operation)))
                self.assertEqual(len([r for r in self.diagnostics(console.getvalue()) if r['phase']=='process-group-failure']),1)
    def test_eperm_wait_preserves_operation(self):
        raw=mock.Mock(pid=4321,returncode=None);raw.poll.side_effect=PermissionError(errno.EPERM,'wait denied');child=process_scope.OwnedProcess(raw)
        with mock.patch.object(process_scope,'membership_snapshot',return_value={'available':False,'rows':[]}),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(process_scope.GroupOperationError) as raised:process_scope.stop_group(child.pid,child)
        self.assertEqual(raw.poll.call_count,2);self.assertEqual(raised.exception.diagnostic['operation'],'wait');self.assertEqual(raised.exception.diagnostic['errno'],errno.EPERM)
    def test_esrch_still_means_group_absent(self):
        with mock.patch.object(process_scope.os,'killpg',side_effect=ProcessLookupError(errno.ESRCH,'gone')),mock.patch.object(process_scope,'membership_snapshot') as snapshot:
            self.assertFalse(process_scope.alive(4321));self.assertTrue(process_scope.stop_group(4321));snapshot.assert_not_called()
    def test_membership_snapshot_is_bounded_and_sanitized(self):
        process=mock.Mock(returncode=0);process.poll.return_value=0
        payload=('invalid row\n999 1 999 501 S other-group\n'+''.join(f'{pid} 2 4321 501 {"S"*20} /fixture/\x1b'+('x'*200)+'\n' for pid in range(100,135))).encode()
        with mock.patch.object(process_scope.subprocess,'Popen',return_value=process) as popen,mock.patch.object(process_scope.select,'select',return_value=([process.stdout],[],[])),mock.patch.object(process_scope.os,'read',side_effect=[payload,b'']):
            row=process_scope.membership_snapshot(4321)
        self.assertTrue(row['available']);self.assertTrue(row['truncated']);self.assertEqual(len(row['rows']),32)
        for member in row['rows']:
            self.assertEqual(set(member),{'pid','ppid','pgid','uid','state','comm'});self.assertEqual(member['pgid'],4321)
            self.assertLessEqual(len(member['state']),16);self.assertLessEqual(len(member['comm']),160);self.assertNotIn('\x1b',member['comm'])
        self.assertEqual(popen.call_args.args[0],['/bin/ps','-axo','pid=,ppid=,pgid=,uid=,state=,comm=']);process.stdout.close.assert_called_once()
    def test_membership_snapshot_output_limit_fails_closed(self):
        process=mock.Mock(returncode=0);process.poll.return_value=None
        with mock.patch.object(process_scope.subprocess,'Popen',return_value=process),mock.patch.object(process_scope.select,'select',return_value=([process.stdout],[],[])),mock.patch.object(process_scope.os,'read',return_value=b'x'*(256*1024+1)):
            row=process_scope.membership_snapshot(4321)
        self.assertFalse(row['available']);self.assertEqual(row['error'],{'type':'ValueError'});self.assertEqual(row['rows'],[]);process.kill.assert_called_once();process.wait.assert_called_once_with(timeout=1)
    def test_membership_snapshot_timeout_reaps_reader(self):
        process=mock.Mock(returncode=0);process.poll.return_value=None
        with mock.patch.object(process_scope.subprocess,'Popen',return_value=process),mock.patch.object(process_scope.select,'select',return_value=([],[],[])):
            row=process_scope.membership_snapshot(4321)
        self.assertFalse(row['available']);self.assertEqual(row['error'],{'type':'TimeoutError'});process.kill.assert_called_once();process.wait.assert_called_once_with(timeout=1)
    def test_error_info_omits_private_exception_text(self):
        for error in [ValueError('private-token'),PermissionError(errno.EPERM,'private-token'),process_scope.subprocess.CalledProcessError(3,['private-token']),process_scope.subprocess.TimeoutExpired(['private-token'],10)]:
            with self.subTest(error=type(error).__name__):self.assertNotIn('private-token',json.dumps(process_scope.error_info(error)))
        self.assertEqual(process_scope.error_info(process_scope.subprocess.TimeoutExpired('private-token',float('inf'))),{'type':'TimeoutExpired'})
    def test_budget_wait_failure_and_cleanup_failure_are_both_retained(self):
        for primary in [PermissionError(errno.EPERM,'wait denied'),process_scope.subprocess.TimeoutExpired('private-command',1200)]:
            with self.subTest(primary=type(primary).__name__):
                root=self.root/type(primary).__name__;process=mock.Mock(pid=4321,returncode=None);process.poll.side_effect=primary;cleanup=self.group_error();console=io.StringIO()
                with mock.patch.object(budget.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'stop_group',side_effect=cleanup),mock.patch.object(budget,'verify_quiescence') as verify,mock.patch.object(budget,'index') as index,contextlib.redirect_stdout(console):
                    self.assertEqual(budget.run(['fixture-command'],root),1)
                verify.assert_not_called();index.assert_not_called();self.assertFalse((root/'evidence-index.json').exists())
                row=protocol.parse(root/'outer-budget.json');self.assertFalse(row['transport_safe']);self.assertEqual(row['error'],str(primary));self.assertEqual(row['primary_error'],process_scope.error_info(primary));self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic])
                diagnostic=next(r for r in self.diagnostics(console.getvalue()) if r['phase']=='outer-budget-result')
                self.assertEqual(diagnostic['primary_error'],row['primary_error']);self.assertEqual(diagnostic['cleanup_errors'],row['cleanup_errors']);self.assertFalse(diagnostic['transport_safe'])
                self.assertEqual(diagnostic['collector_phase'],'collector-timeout-cleanup' if isinstance(primary,process_scope.subprocess.TimeoutExpired) else 'collector-error-cleanup')
    def test_unowned_fixture_rejection_logs_exact_reason_before_result_write(self):
        root=self.root/'e';root.mkdir();reason='backstop cannot establish cleanup of pre-existing simulator'
        put(root/'process-registry.json',{'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':False,'groups':[],
            'fixture':{'device':'12345678-1234-1234-1234-123456789abc','owned_boot':False,'stopped':False,'bundle_ids':[capture.APP_ID,capture.RUNNER_ID]}})
        process=mock.Mock(pid=4321,returncode=0);process.poll.return_value=0;console=io.StringIO();original_atomic=process_scope.atomic
        def write(path,value):
            if path.name=='outer-budget.json':
                diagnostic=next(r for r in self.diagnostics(console.getvalue()) if r['phase']=='outer-budget-result')
                self.assertEqual(diagnostic['primary_error'],{'type':'ValueError','reason':reason});self.assertEqual(diagnostic['collector_phase'],'verify-quiescence')
            original_atomic(path,value)
        with mock.patch.object(budget.uuid,'uuid4',return_value=mock.Mock(hex=SESSION)),mock.patch.object(budget.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'atomic',side_effect=write),mock.patch.object(budget,'index') as index,contextlib.redirect_stdout(console):
            self.assertEqual(budget.run(['fixture-command'],root),1)
        index.assert_not_called();self.assertFalse((root/'evidence-index.json').exists());self.assertFalse((root/'quiescence.json').exists())
        outcome=protocol.parse(root/'outer-budget.json');self.assertFalse(outcome['transport_safe']);self.assertEqual(outcome['primary_error']['reason'],reason)
    def test_package_rejections_log_exact_reason_before_raising(self):
        for incomplete in ['quiescence','registry']:
            with self.subTest(incomplete=incomplete):
                put(self.root/'outer-budget.json',{'transport_safe':incomplete!='quiescence','session':SESSION})
                put(self.root/'quiescence.json',{'quiescent':True,'outerVerified':True,'session':SESSION})
                put(self.root/'process-registry.json',{'session':SESSION,'groups':[{'settled':False}]})
                reason='packaging blocked: '+('quiescence unproved' if incomplete=='quiescence' else 'writer registry incomplete');console=io.StringIO()
                with contextlib.redirect_stdout(console):
                    try:budget.check_package(self.root)
                    except ValueError as error:
                        self.assertEqual(str(error),reason)
                        self.assertEqual(self.diagnostics(console.getvalue()),[{'schema':'p1-capability-console-diagnostic-v1','phase':'package-gate-failure','admissionEligible':False,'error':{'type':'ValueError','reason':reason}}])
                    else:self.fail('unknown quiescence allowed packaging')
    def test_package_missing_metadata_logs_errno_without_path(self):
        console=io.StringIO()
        with contextlib.redirect_stdout(console),self.assertRaises(FileNotFoundError):budget.check_package(self.root)
        diagnostic=self.diagnostics(console.getvalue())[0];self.assertEqual(diagnostic['phase'],'package-gate-failure');self.assertEqual(diagnostic['error'],{'type':'FileNotFoundError','errno':errno.ENOENT});self.assertNotIn(str(self.root),console.getvalue())
    def test_cleanup_failure_rejects_zero_and_already_stopped_receipts(self):
        identifier=capture.APP_ID;cleanup=self.group_error().diagnostic
        text=(f'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\nSimulator device failed to terminate {identifier}.\nfound nothing to terminate\nUnderlying error (domain=NSPOSIXErrorDomain, code=3):\n\tThe request to terminate "{identifier}" failed. found nothing to terminate\n\tfound nothing to terminate\n')
        for row in [dict(exit_code=0,failure_type=None),dict(exit_code=3,failure_type='CalledProcessError',stdout='',stderr=text)]:
            self.assertTrue(capture.stopped_response(row,identifier));row['cleanup_errors']=[cleanup];self.assertFalse(capture.stopped_response(row,identifier))
    def test_spawn_registration_cleanup_cannot_mask_persist_error(self):
        scope=process_scope.Scope(self.root);process=mock.Mock(pid=4321,returncode=None)
        primary=OSError(errno.ENOSPC,'registry full');cleanup=self.group_error();console=io.StringIO()
        with (self.root/'stdout').open('wb') as out,mock.patch.object(scope,'persist',side_effect=primary),mock.patch.object(process_scope.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'stop_group',side_effect=cleanup),mock.patch.object(process_scope.os,'write') as release,contextlib.redirect_stdout(console):
            with self.assertRaises(OSError) as raised:scope.spawn(['fixture-command'],out)
        self.assertIs(raised.exception,primary);release.assert_not_called();self.assertFalse(scope.rows[0]['settled'])
        self.assertEqual(scope.rows[0]['primary_error'],{'type':'OSError','errno':errno.ENOSPC});self.assertEqual(scope.rows[0]['cleanup_errors'],[cleanup.diagnostic])
        diagnostics=self.diagnostics(console.getvalue());self.assertEqual([r['phase'] for r in diagnostics],['spawn-registration-failure','spawn-cleanup-failure'])
        self.assertEqual(diagnostics[0]['primary_error'],scope.rows[0]['primary_error']);self.assertEqual(diagnostics[1]['cleanup_error'],cleanup.diagnostic)
    def test_backstop_wait_and_cleanup_failures_reach_outer_receipt(self):
        root=self.root/'e';root.mkdir();registry={'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':False,'groups':[],
            'fixture':{'device':'12345678-1234-1234-1234-123456789abc','owned_boot':True,'stopped':False,'bundle_ids':[capture.APP_ID,capture.RUNNER_ID]}}
        put(root/'process-registry.json',registry)
        primary=process_scope.subprocess.TimeoutExpired('private-simulator-command',20);cleanup=self.group_error()
        simulator=mock.Mock(pid=4321,returncode=None);simulator.poll.side_effect=primary;console=io.StringIO()
        with mock.patch.object(budget.subprocess,'Popen',return_value=simulator),mock.patch.object(process_scope,'stop_group',side_effect=cleanup),contextlib.redirect_stdout(console):
            with self.assertRaises(process_scope.subprocess.TimeoutExpired) as raised:budget.verify_quiescence(root,SESSION,force=True)
        self.assertIs(raised.exception,primary);self.assertEqual(primary._p1_cleanup_diagnostics,[cleanup.diagnostic])
        self.assertFalse((root/'quiescence.json').exists());self.assertFalse(protocol.parse(root/'process-registry.json')['fixture']['stopped'])
        diagnostic=self.diagnostics(console.getvalue())[0];self.assertEqual(diagnostic['phase'],'backstop-simulator-cleanup');self.assertEqual(diagnostic['primary_error'],{'type':'TimeoutExpired','timeout_seconds':20});self.assertEqual(diagnostic['cleanup_errors'],[cleanup.diagnostic])
        collector=mock.Mock(pid=1234,returncode=0);collector.poll.return_value=0;console=io.StringIO()
        with mock.patch.object(budget.uuid,'uuid4',return_value=mock.Mock(hex=SESSION)),mock.patch.object(budget.subprocess,'Popen',side_effect=[collector,simulator]),mock.patch.object(process_scope,'stop_group',side_effect=[True,cleanup]),mock.patch.object(budget,'index') as index,contextlib.redirect_stdout(console):
            self.assertEqual(budget.run(['fixture-command'],root),1)
        index.assert_not_called();row=protocol.parse(root/'outer-budget.json')
        self.assertFalse(row['transport_safe']);self.assertEqual(row['error'],str(primary));self.assertEqual(row['primary_error'],diagnostic['primary_error']);self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic])
        phases=[r['phase'] for r in self.diagnostics(console.getvalue())];self.assertLess(phases.index('backstop-simulator-cleanup'),phases.index('outer-budget-result'))
    def test_command_receipt_write_failure_logs_then_preserves_primary(self):
        logs=self.root/'logs';logs.mkdir();primary=process_scope.subprocess.TimeoutExpired('private-command',7.5)
        process=mock.Mock(pid=4321,returncode=None);process.wait.side_effect=primary
        scope=mock.Mock();scope.remaining.return_value=7.5;scope.spawn.return_value=process;command=process_scope.Commands(scope,logs)
        console=io.StringIO();original_open=Path.open;events=[]
        def open_file(path,*args,**kwargs):
            if path.name=='commands.jsonl':
                events.extend(r['phase'] for r in self.diagnostics(console.getvalue()))
                raise PermissionError(errno.EACCES,'private-log-path')
            return original_open(path,*args,**kwargs)
        with mock.patch.object(Path,'open',open_file),contextlib.redirect_stdout(console):
            with self.assertRaises(process_scope.subprocess.TimeoutExpired) as raised:command('fixture-command')
        self.assertIs(raised.exception,primary);self.assertEqual(events,['command-failure']);self.assertFalse((logs/'commands.jsonl').exists())
        diagnostics=self.diagnostics(console.getvalue());self.assertEqual([r['phase'] for r in diagnostics],['command-failure','command-receipt-write-failure'])
        self.assertEqual(diagnostics[1]['error'],{'type':'PermissionError','errno':errno.EACCES});self.assertEqual(diagnostics[1]['primary_error'],{'type':'TimeoutExpired','timeout_seconds':7.5});self.assertNotIn('private-',json.dumps(diagnostics))
    def test_console_diagnostic_is_bounded(self):
        console=io.StringIO()
        with contextlib.redirect_stdout(console):process_scope.emit_diagnostic('command-failure',detail='x'*40000)
        row=self.diagnostics(console.getvalue())[0];self.assertTrue(row['diagnostic_truncated']);self.assertNotIn('detail',row);self.assertLess(len(console.getvalue()),32768)
    def test_console_write_failure_does_not_raise(self):
        with mock.patch('builtins.print',side_effect=OSError(errno.EPIPE,'closed pipe')):process_scope.emit_diagnostic('command-failure',primary_error={'type':'TimeoutExpired'})
    def test_phase_summary_fifo_is_rejected_without_blocking(self):
        path=self.root/'capability-result.json';os.mkfifo(path);original_open=os.open;flags_seen=[];console=io.StringIO()
        def open_summary(path,flags,*args,**kwargs):
            flags_seen.append(flags)
            if not flags&os.O_NONBLOCK:raise AssertionError('FIFO diagnostic open would block')
            return original_open(path,flags,*args,**kwargs)
        with mock.patch.object(budget.os,'open',side_effect=open_summary),contextlib.redirect_stdout(console):budget.phase_summaries(self.root)
        self.assertEqual(len(flags_seen),1);self.assertTrue(flags_seen[0]&os.O_NONBLOCK)
        self.assertEqual(self.diagnostics(console.getvalue())[0]['phase'],'phase-summary-unavailable')
    def test_phase_summary_never_prints_arbitrary_payload(self):
        put(self.root/'capability-result.json',{'collection_complete':False,'capabilities_passed':False,'errors':['private-token'],'argv':['private-token'],'environment':{'secret':'private-token'},
            'calibration':{'calibration_feasible':True,'errors':['private-token']},'recovery':{'full_matrix_complete':False,'errors':['private-token'],'collection_complete':'private-token'}})
        console=io.StringIO()
        with contextlib.redirect_stdout(console):budget.phase_summaries(self.root)
        rows=self.diagnostics(console.getvalue());self.assertEqual([r['component'] for r in rows],['collector','calibration','recovery'])
        self.assertNotIn('private-token',console.getvalue());self.assertNotIn('argv',console.getvalue());self.assertNotIn('environment',console.getvalue())
        for row in rows:self.assertTrue(row['unverified_summary']);self.assertEqual(row['error_count'],1)
        self.assertIs(rows[0]['collection_complete'],False);self.assertIs(rows[1]['calibration_feasible'],True);self.assertNotIn('collection_complete',rows[2])
    def test_phase_summary_oversized_file_is_rejected(self):
        (self.root/'capability-result.json').write_text('{"errors":["'+'private-token'*6000+'"]}');console=io.StringIO()
        with contextlib.redirect_stdout(console):budget.phase_summaries(self.root)
        self.assertEqual(self.diagnostics(console.getvalue())[0]['phase'],'phase-summary-unavailable');self.assertNotIn('private-token',console.getvalue())
    def test_false_stop_reports_wait_and_disappearance_pgid(self):
        snapshot={'available':True,'pgid':4321,'rows':[],'truncated':False}
        for operation in ['wait','disappearance']:
            with self.subTest(operation=operation):
                raw=mock.Mock(pid=4321,returncode=None);raw.poll.return_value=None;child=process_scope.OwnedProcess(raw);console=io.StringIO()
                with mock.patch.object(process_scope,'alive',return_value=True),mock.patch.object(process_scope,'signal_group'),mock.patch.object(child,'wait',side_effect=process_scope.subprocess.TimeoutExpired('fixture',5)),mock.patch.object(process_scope.time,'monotonic',side_effect=[0,9]),mock.patch.object(process_scope,'membership_snapshot',return_value=snapshot),contextlib.redirect_stdout(console):self.assertFalse(process_scope.stop_group(child.pid,child if operation=='wait' else None))
                diagnostic=next(r for r in self.diagnostics(console.getvalue()) if r['phase']=='process-group-unsettled')
                self.assertEqual(diagnostic['pgid'],child.pid);self.assertEqual(diagnostic['operation'],operation);self.assertIs(diagnostic['result'],False);self.assertEqual(diagnostic['membership'],snapshot)
    def test_false_settle_retains_pgid_and_unsettled_registry(self):
        scope=process_scope.Scope(self.root);process=mock.Mock(pid=4321,returncode=0);scope.rows.append({'pid':4321,'pgid':4321,'settled':False});console=io.StringIO()
        with mock.patch.object(process_scope,'stop_group',return_value=False),contextlib.redirect_stdout(console):
            with self.assertRaisesRegex(RuntimeError,'child group did not become quiescent'):scope.settle(process)
        diagnostic=self.diagnostics(console.getvalue())[0];self.assertEqual(diagnostic['phase'],'process-group-unsettled');self.assertEqual(diagnostic['operation'],'settle');self.assertEqual(diagnostic['pgid'],4321);self.assertIs(diagnostic['result'],False)
        self.assertFalse(protocol.parse(self.root/'process-registry.json')['groups'][0]['settled'])
    def test_false_writer_stop_logs_pgid_and_blocks_index(self):
        root=self.root/'e';root.mkdir();put(root/'process-registry.json',{'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':False,'groups':[{'pid':4321,'pgid':4321,'settled':False}]})
        process=mock.Mock(pid=1234,returncode=0);process.poll.return_value=0;console=io.StringIO()
        with mock.patch.object(budget.uuid,'uuid4',return_value=mock.Mock(hex=SESSION)),mock.patch.object(budget.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'stop_group',side_effect=[True,False]) as stop,mock.patch.object(budget,'index') as index,contextlib.redirect_stdout(console):
            self.assertEqual(budget.run(['fixture-command'],root),1)
        self.assertEqual(len(stop.call_args_list),2);self.assertEqual(stop.call_args_list[0].args[0],1234);self.assertIsInstance(stop.call_args_list[0].args[1],process_scope.OwnedProcess);self.assertEqual(stop.call_args_list[1].args,(4321,));index.assert_not_called();self.assertFalse((root/'evidence-index.json').exists());self.assertFalse((root/'quiescence.json').exists())
        diagnostics=self.diagnostics(console.getvalue());group=next(r for r in diagnostics if r['phase']=='writer-group-unsettled')
        self.assertEqual(group['pgid'],4321);self.assertEqual(group['operation'],'stop_group');self.assertIs(group['result'],False)
        outcome=protocol.parse(root/'outer-budget.json');self.assertFalse(outcome['transport_safe']);self.assertEqual(outcome['primary_error'],{'type':'ValueError','reason':'writer group quiescence unproved'})
        self.assertLess([r['phase'] for r in diagnostics].index('writer-group-unsettled'),[r['phase'] for r in diagnostics].index('outer-budget-result'))
    def test_normal_collector_exit_requires_group_disappearance(self):
        root=self.root/'e';raw=mock.Mock(pid=1234,returncode=0);raw.poll.return_value=0
        with mock.patch.object(budget.subprocess,'Popen',return_value=raw),mock.patch.object(process_scope,'stop_group',return_value=False) as stop,mock.patch.object(budget,'verify_quiescence') as verify,mock.patch.object(budget,'index') as index,contextlib.redirect_stdout(io.StringIO()):self.assertEqual(budget.run(['fixture-command'],root),1)
        verify.assert_not_called();index.assert_not_called();self.assertEqual(stop.call_args.args[0],raw.pid);self.assertIs(stop.call_args.args[1]._process,raw)
        row=protocol.parse(root/'outer-budget.json');self.assertFalse(row['transport_safe']);self.assertEqual(row['phase'],'collector-disappearance');self.assertFalse((root/'evidence-index.json').exists())
    def shutdown_transport_case(self,unsettled=False,timed_out=False):
        root=self.root/'e';root.mkdir();device='12345678-1234-1234-1234-123456789abc';shutdown_pid=6002
        put(root/'process-registry.json',{'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':False,'groups':[],
            'fixture':{'device':device,'owned_boot':True,'stopped':False,'bundle_ids':[capture.APP_ID,capture.RUNNER_ID]}})
        primary=process_scope.subprocess.TimeoutExpired('private-shutdown-command',15) if timed_out else None
        cleanup=self.group_error('probe',shutdown_pid);replies=[(6000,0,None),(6001,0,'Booted'),(shutdown_pid,None if timed_out else 149,None),(6003,0,'Shutdown')];console=io.StringIO()
        def launch(argv,**kwargs):
            pid,code,state=replies.pop(0)
            if state is not None:kwargs['stdout'].write(json.dumps({'devices':{'runtime':[{'udid':device,'state':state}]}}).encode());kwargs['stdout'].flush()
            raw=mock.Mock(pid=pid,returncode=code,args=argv);raw.poll.return_value=code
            if pid==shutdown_pid and primary is not None:raw.poll.side_effect=primary
            return raw
        def settle(group,child):
            self.assertIsInstance(child,process_scope.OwnedProcess);self.assertEqual(group,child.pid)
            if unsettled and group==shutdown_pid:raise cleanup
            return True
        original_index=budget.index
        with mock.patch.object(budget.uuid,'uuid4',return_value=mock.Mock(hex=SESSION)),mock.patch.object(budget.subprocess,'Popen',side_effect=launch),mock.patch.object(process_scope,'stop_group',side_effect=settle) as stop,mock.patch.object(budget,'index',wraps=original_index) as index,contextlib.redirect_stdout(console):
            self.assertEqual(budget.run(['fixture-command'],root),1)
            if unsettled:
                with self.assertRaises((ValueError,FileNotFoundError)):budget.check_package(root)
            else:budget.check_package(root)
        self.assertEqual(replies,[]);self.assertEqual([call.args[0] for call in stop.call_args_list],[6000,6001,shutdown_pid,6003])
        shutdown=protocol.parse(root/'backstop-simulator-shutdown.json');self.assertTrue(shutdown['observed_shutdown']);self.assertTrue(shutdown['command_failed']);self.assertFalse(shutdown['admissionEligible'])
        self.assertEqual([r.get('observed_state') for r in shutdown['receipts']],['Booted',None,'Shutdown'])
        receipt=shutdown['receipts'][1]['command'];self.assertEqual(receipt['exit_code'],None if timed_out else 149);self.assertEqual(receipt['primary_error'],process_scope.error_info(primary));self.assertEqual(receipt['cleanup_errors'],[cleanup.diagnostic] if unsettled else [])
        outcome=protocol.parse(root/'outer-budget.json');self.assertEqual(outcome['exit_code'],1);self.assertEqual(outcome['transport_safe'],not unsettled)
        if unsettled:
            index.assert_not_called();self.assertFalse((root/'quiescence.json').exists());self.assertFalse((root/'evidence-index.json').exists());self.assertFalse(protocol.parse(root/'process-registry.json')['fixture']['stopped'])
            self.assertEqual(outcome['primary_error'],process_scope.error_info(primary) if primary else cleanup.diagnostic);self.assertEqual(outcome['cleanup_errors'],[cleanup.diagnostic] if primary else [])
            if primary:self.assertEqual(outcome['error'],str(primary))
            diagnostics=self.diagnostics(console.getvalue());row=next(r for r in diagnostics if r['phase']=='backstop-simulator-cleanup' and r['pgid']==shutdown_pid)
            self.assertEqual(row['cleanup_errors'],[cleanup.diagnostic]);outer=next(r for r in diagnostics if r['phase']=='outer-budget-result');self.assertFalse(outer['transport_safe']);self.assertEqual(outer['primary_error'],outcome['primary_error']);self.assertEqual(outer['cleanup_errors'],outcome['cleanup_errors'])
        else:
            index.assert_called_once_with(root);self.assertTrue(outcome['cleanup_command_failed']);self.assertTrue((root/'evidence-index.json').exists())
        self.assertNotIn('private-shutdown-command',console.getvalue())
    def test_settled_149_then_shutdown_allows_only_failed_diagnostic_transport(self):self.shutdown_transport_case()
    def test_unsettled_149_then_shutdown_never_allows_transport(self):self.shutdown_transport_case(unsettled=True)
    def test_timeout_primary_survives_unsettled_cleanup_and_later_shutdown(self):self.shutdown_transport_case(unsettled=True,timed_out=True)
    def test_shutdown_149_failure_survives_later_clean_state_in_collection(self):
        device='12345678-1234-1234-1234-123456789abc';scope=process_scope.Scope(self.root);scope.fixture_identity(device,True);command=mock.Mock();command.scope=scope
        state=lambda name:dict(exit_code=0,failure_type=None,stdout=json.dumps({'devices':{'runtime':[{'udid':device,'state':name}]}}))
        command.side_effect=[dict(exit_code=1),dict(exit_code=1),state('Booted'),dict(exit_code=149,failure_type='CalledProcessError'),state('Shutdown'),state('Shutdown')]
        result={'errors':[],'capabilities_passed':True,'collection_complete':True}
        with contextlib.redirect_stdout(io.StringIO()):capture.finalize(self.root,result,command,scope,device,True)
        self.assertFalse(result['collection_complete']);self.assertFalse(result['capabilities_passed']);self.assertIn('simulator cleanup command failure retained',result['errors'])
        self.assertTrue(protocol.parse(self.root/'quiescence.json')['quiescent']);self.assertTrue(protocol.parse(self.root/'process-registry.json')['fixture']['cleanup_command_failed'])


class PhoneOnlyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
    def execute_phone(self,recovery_passed=True,cleanup_failure=False,source_drift=False):
        from types import SimpleNamespace
        host=HERE.parents[2];work=self.root/'work';output=self.root/'evidence';inputs=self.root/'inputs.json';inputs.write_text('{}')
        device='12345678-1234-1234-1234-123456789abc';scope=mock.Mock();scope.fixture=None
        if cleanup_failure:scope.close.side_effect=ValueError('unsettled fixture writer')
        def command_result(*args,**kwargs):
            if args[:3]==('xcrun','simctl','list'):return json.dumps({'devices':{'runtime':[{'udid':device,'state':'Booted'}]}})
            return 'synthetic command result'
        command=mock.Mock(side_effect=command_result);command.scope=scope
        renderer=SimpleNamespace(valid_png=lambda raw:True)
        def prepare(source,builder,build,out):
            products=build/'DerivedData/Build/Products';products.mkdir(parents=True)
            (products/'Fixture.xctestrun').write_bytes(plistlib.dumps({}))
            app=products/'Debug-iphonesimulator/P0SignIn.app';app.mkdir(parents=True)
            (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':capture.APP_ID}))
            project=build/'Fixture.xcodeproj';project.mkdir();return project,renderer
        actual_sha=capture.sha
        def sha(path):
            if str(path).endswith(capture.base.SHELL):return '0'*64 if source_drift else capture.SOURCE_SHA
            return actual_sha(path)
        recovery={'scope':'recovery-capability-only','collection_complete':recovery_passed,'errors':[] if recovery_passed else ['test failure'],'full_matrix_complete':False,'admissionEligible':False}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(capture.process_scope,'Scope',return_value=scope))
            stack.enter_context(mock.patch.object(capture.process_scope,'Commands',return_value=command))
            native=stack.enter_context(mock.patch.object(capture.request_reader_gate,'run',return_value={'passed':True,'case_ids':['native-gate']}))
            acquire=stack.enter_context(mock.patch.object(capture.base,'acquire'))
            stack.enter_context(mock.patch.object(capture.base,'module',return_value=SimpleNamespace(available_devices=lambda:[('phone',device,'runtime')])))
            stack.enter_context(mock.patch.object(capture.base,'checkout_proof',return_value={'immutable':'proof'}))
            stack.enter_context(mock.patch.object(capture,'prepare',side_effect=prepare))
            stack.enter_context(mock.patch.object(capture,'configure_runner',side_effect=lambda candidate,*args:candidate))
            stack.enter_context(mock.patch.object(capture,'sha',side_effect=sha))
            calibration=stack.enter_context(mock.patch.object(capture,'run_calibration',side_effect=AssertionError('calibration must not run')))
            layout=stack.enter_context(mock.patch.object(capture,'run_layout',return_value=recovery))
            stop=stack.enter_context(mock.patch.object(capture,'stop_fixture',return_value=True))
            with contextlib.redirect_stdout(io.StringIO()):passed=capture.execute(host,work,output,inputs,'a'*64,'phone')
        native.assert_called_once();acquire.assert_any_call(work/'LiveContainer',capture.SOURCE,command)
        calibration.assert_not_called();layout.assert_called_once_with(command,work/'build/DerivedData/Build/Products/Fixture.xctestrun',device,'phone',output/'recovery',renderer.valid_png)
        scope.close.assert_called_once();stop.assert_called_once();self.assertFalse((output/'calibration').exists())
        return passed,protocol.parse(output/'capability-result.json'),command
    def test_actual_execute_routes_only_phone_recovery(self):
        passed,row,command=self.execute_phone();self.assertTrue(passed);self.assertTrue(row['capabilities_passed']);self.assertTrue(row['collection_complete'])
        self.assertEqual(row['schema'],'p1-phone-recovery-collection-v1');self.assertEqual(row['scope'],'phone-recovery-capability-only')
        self.assertEqual(row['device_class'],'phone');self.assertNotIn('calibration',row)
        for key in ['calibration_executed','tablet_executed','feedback_lifetime_established','input_overlap_established','admission_eligible','production_ready','full_matrix_complete','full_native_lane_executed']:self.assertIs(row[key],False)
        self.assertIs(row['prior_context']['used_for_current_pass'],False)
        boot=[c for c in command.call_args_list if c.args[:3]==('xcrun','simctl','bootstatus')];self.assertEqual(len(boot),1);self.assertEqual(boot[0].kwargs['timeout'],120)
    def test_failed_recovery_stays_failed(self):
        passed,row,_=self.execute_phone(recovery_passed=False);self.assertFalse(passed);self.assertFalse(row['collection_complete']);self.assertFalse(row['capabilities_passed'])
    def test_cleanup_failure_cannot_make_phone_pass(self):
        passed,row,_=self.execute_phone(cleanup_failure=True);self.assertFalse(passed);self.assertFalse(row['collection_complete']);self.assertTrue(row['errors'])
    def test_source_drift_cannot_make_phone_pass(self):
        passed,row,_=self.execute_phone(source_drift=True);self.assertFalse(passed);self.assertIn('source drift',row['errors'])
    def test_tablet_rejected_before_any_work(self):
        with mock.patch.object(capture.process_scope,'Scope') as scope:
            with self.assertRaisesRegex(ValueError,'phone-only'):capture.execute(self.root,self.root/'work',self.root/'evidence',self.root/'inputs','a'*64,'tablet')
            scope.assert_not_called();self.assertFalse((self.root/'work').exists());self.assertFalse((self.root/'evidence').exists())
    def test_old_combined_input_scope_rejected(self):
        helper=SealsAndExports();helper.root=self.root;host,path,data=helper.sealed();data['scope']='calibration-and-recovery-capabilities-only-no-admission';put(path,data)
        with self.assertRaisesRegex(ValueError,'wrong capability scope'):capture.validate(host,path,capture.sha(path))
    def test_workflow_only_phone_and_preserved_budgets(self):
        import yaml
        row=yaml.safe_load((HERE.parents[2]/'.github/workflows/p1-native-candidate.yml').read_text());jobs=row['jobs'];self.assertEqual(len(jobs),1)
        job=next(iter(jobs.values()));self.assertEqual(job['strategy']['matrix']['device'],['phone']);self.assertEqual(job['timeout-minutes'],35)
        step=next(s for s in job['steps'] if s.get('id')=='collect');self.assertEqual(step['timeout-minutes'],22);self.assertIn('preflight/budget.py',step['run'])
        self.assertIn("--device-class '${{ matrix.device }}'",step['run']);self.assertNotIn('native_gate.py',step['run'])
    def test_cli_rejects_tablet(self):
        import subprocess
        reply=subprocess.run([sys.executable,'-B',str(HERE/'capture.py'),'--device-class','tablet'],text=True,capture_output=True,timeout=20)
        self.assertNotEqual(reply.returncode,0);self.assertIn("invalid choice: 'tablet'",reply.stderr)

if __name__=='__main__':unittest.main()
