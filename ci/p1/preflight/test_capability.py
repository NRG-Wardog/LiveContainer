import copy
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
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.decoded,self.events,self.strip=fixture(self.root)
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
            p=Path(tmp)/'x';p.write_text('{"id":1,"id":1}')
            with self.assertRaises(ValueError):protocol.parse(p)
    def test_linked_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x';p.write_text('{}');q=Path(tmp)/'q';q.symlink_to(p)
            with self.assertRaises(ValueError):protocol.parse(q)
    def test_stale_channel_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'request.json').write_text('{}')
            with self.assertRaises(ValueError):protocol.Channel(root,SESSION,'runner',root/'out')
    def test_protocol_canonical_without_newline(self):self.assertEqual(protocol.canonical({'kind':'clock','id':1}),b'{"id":1,"kind":"clock"}')
    def test_runner_recipe_injects_only_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);products=root/'products';info=products/'Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist';info.parent.mkdir(parents=True);info.write_bytes(plistlib.dumps({'CFBundleIdentifier':analysis.RUNNER_ID}))
            candidate=products/'a.xctestrun';candidate.write_bytes(plistlib.dumps({'Tests':{'TestBundlePath':'P0SignInUITests.xctest','IsUITestBundle':True}}));out=root/'out';out.mkdir()
            p=capture.configure_runner(candidate,products,SESSION,out);self.assertEqual(plistlib.loads(p.read_bytes())['Tests']['EnvironmentVariables']['P1_CAPABILITY_SESSION'],SESSION)
    def test_runner_recipe_rejects_wrong_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);info=root/'Debug-iphonesimulator/P0SignInUITests-Runner.app/Info.plist';info.parent.mkdir(parents=True);info.write_bytes(plistlib.dumps({'CFBundleIdentifier':'other'}))
            with self.assertRaises(ValueError):capture.configure_runner(root/'a',root,SESSION,root)
    def test_budget_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'evidence'
            script=f'import sys;sys.path.insert(0,{str(HERE)!r});from pathlib import Path;import process_scope;p=Path({str(out)!r});p.mkdir();s=process_scope.Scope(p);s.close();raise SystemExit(7)'
            self.assertEqual(budget.run([sys.executable,'-B','-c',script],out),7)
            self.assertEqual(protocol.parse(out/'outer-budget.json')['exit_code'],7);self.assertIn('outer-budget.json',protocol.parse(out/'evidence-index.json')['files'])
    def test_budget_timeout_reaps_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            process=mock.Mock();process.pid=123;process.wait.side_effect=budget.subprocess.TimeoutExpired('x',1200)
            with mock.patch.object(budget.subprocess,'Popen',return_value=process),mock.patch.object(process_scope,'stop_group',return_value=True) as stop, mock.patch.object(budget,'verify_quiescence'):
                self.assertEqual(budget.run(['x'],Path(tmp)/'e'),124);stop.assert_called_once_with(123,process)
    def test_fixed_outer_budget(self):
        with self.assertRaises(ValueError):budget.run([],Path('/tmp/no'),seconds=1)

class SealsAndExports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def sealed(self):
        host=self.root/'host';host.mkdir();original=HERE.parents[2]
        for relative in capture.ADAPTERS:
            target=host/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/relative,target)
        data=dict(schema='p1-short-capability-inputs-v1',scope='calibration-and-recovery-capabilities-only-no-admission',livecontainer=capture.SOURCE,builder=capture.BUILDER,source_sha256=capture.SOURCE_SHA,adapter_files={n:capture.sha(host/n) for n in capture.ADAPTERS})
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
            root=Path(tmp);channel=protocol.Channel(root,SESSION,'runner',root/'host.json');errors=[]
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
            root=Path(tmp);logs=root/'logs';logs.mkdir();scope=process_scope.Scope(root);scope.deadline=time.monotonic()+.15;command=process_scope.Commands(scope,logs);target=root/'writer'
            script="import time;f=open(%r,'a');\nwhile True:f.write('x');f.flush();time.sleep(.005)" % str(target)
            with self.assertRaises(Exception):command(sys.executable,'-B','-c',script,timeout=10)
            scope.close();self.assertTrue(protocol.parse(root/'quiescence.json')['quiescent'])
            before=target.read_bytes();time.sleep(.05);self.assertEqual(target.read_bytes(),before)
    def test_exec_cannot_start_before_durable_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=process_scope.Scope(root);target=root/'started';original=scope.persist;seen=[]
            def persist():
                seen.append(target.exists());time.sleep(.03);self.assertFalse(target.exists());original()
            with (root/'stdout').open('wb') as f,mock.patch.object(scope,'persist',side_effect=persist):
                process=scope.spawn([sys.executable,'-B','-c',f"open({str(target)!r},'w').write('x')"],f)
            process.wait(timeout=2);scope.settle(process);scope.close();self.assertEqual(seen,[False]);self.assertTrue(target.exists())
    def test_failed_registry_write_never_executes_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=process_scope.Scope(root);target=root/'started'
            with (root/'stdout').open('wb') as f,mock.patch.object(scope,'persist',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):scope.spawn([sys.executable,'-B','-c',f"open({str(target)!r},'w').write('x')"],f)
            time.sleep(.03);self.assertFalse(target.exists());scope.close()
    def test_outer_timeout_stops_detached_writer_before_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'e';ready=Path(tmp)/'ready';writer=root/'active-writer'
            script=f"import sys,time;sys.path.insert(0,{str(HERE)!r});from pathlib import Path;import process_scope;r=Path({str(root)!r});r.mkdir();s=process_scope.Scope(r);f=(r/'child.log').open('wb');p=s.spawn([sys.executable,'-B','-c',\"import time;f=open({str(writer)!r},'a');\\nwhile True:f.write('x');f.flush();time.sleep(.005)\"],f);Path({str(ready)!r}).write_text('ready');time.sleep(60)"
            original_popen=budget.subprocess.Popen;original_index=budget.index;indexed=[]
            def launch(*args,**kwargs):
                p=original_popen(*args,**kwargs);real_wait=p.wait;first=[True]
                def wait(timeout=None):
                    if first[0]:
                        first[0]=False;deadline=time.monotonic()+3
                        while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                        self.assertTrue(ready.exists());time.sleep(.05);raise budget.subprocess.TimeoutExpired('collector',1200)
                    return real_wait(timeout=timeout)
                p.wait=wait;return p
            def index(path):
                self.assertTrue(protocol.parse(path/'quiescence.json')['quiescent']);before=writer.read_bytes();time.sleep(.03);self.assertEqual(writer.read_bytes(),before);indexed.append(True);original_index(path)
            with mock.patch.object(budget.subprocess,'Popen',side_effect=launch),mock.patch.object(budget,'index',side_effect=index):
                self.assertEqual(budget.run([sys.executable,'-B','-c',script],root),124)
            self.assertEqual(indexed,[True]);self.assertTrue(protocol.parse(root/'outer-budget.json')['transport_safe'])
    def test_crashed_collector_stops_registered_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'e';writer=root/'active-writer'
            script=f"import sys,time;sys.path.insert(0,{str(HERE)!r});from pathlib import Path;import process_scope;r=Path({str(root)!r});r.mkdir();s=process_scope.Scope(r);f=(r/'child.log').open('wb');s.spawn([sys.executable,'-B','-c',\"import time;f=open({str(writer)!r},'a');\\nwhile True:f.write('x');f.flush();time.sleep(.005)\"],f);time.sleep(.1);raise SystemExit(9)"
            self.assertEqual(budget.run([sys.executable,'-B','-c',script],root),9)
            before=writer.read_bytes();time.sleep(.03);self.assertEqual(writer.read_bytes(),before)
            self.assertTrue(protocol.parse(root/'outer-budget.json')['transport_safe']);budget.check_package(root)
    def test_missing_registry_blocks_index_and_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'e'
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
            scope=mock.Mock();scope.fixture={'owned_boot':True};command=mock.Mock();command.scope=scope
            command.side_effect=[dict(exit_code=1),dict(exit_code=1),dict(exit_code=0,failure_type=None)]
            self.assertTrue(capture.stop_fixture(command,'device',Path(tmp)));scope.fixture_stopped.assert_called_once_with(True)
            self.assertEqual(command.call_args_list[-1].args,('xcrun','simctl','shutdown','device'))
    def test_unowned_simulator_unknown_cleanup_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=mock.Mock();scope.fixture={'owned_boot':False};command=mock.Mock(return_value={'exit_code':1});command.scope=scope
            self.assertFalse(capture.stop_fixture(command,'device',Path(tmp)));self.assertEqual(command.call_count,2)
    def test_channel_shared_deadline_prevents_new_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remaining=mock.Mock(side_effect=TimeoutError('deadline'));channel=protocol.Channel(root,SESSION,'runner',root/'out',remaining)
            with self.assertRaises(TimeoutError):channel.request('clock',phase='pre')
            self.assertFalse((root/'request.json').exists());remaining.assert_called_once_with(20)
    def test_file_wait_shared_deadline(self):
        remaining=mock.Mock(side_effect=TimeoutError('deadline'))
        with self.assertRaises(TimeoutError):capture.await_file(Path('/tmp/no-channel-file'),10,remaining=remaining)
        remaining.assert_called_once_with(10)
    def test_scope_close_rejects_live_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=process_scope.Scope(Path(tmp));scope.fixture_identity('device',False)
            with self.assertRaises(RuntimeError):scope.close()
            self.assertFalse(protocol.parse(Path(tmp)/'quiescence.json')['quiescent'])
    def test_execute_cleanup_guard_retains_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope=mock.Mock();command=mock.Mock(side_effect=RuntimeError('command failure'));command.scope=scope
            result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            with mock.patch.object(capture,'stop_fixture',side_effect=RuntimeError('termination failed')):
                capture.finalize(root,result,command,scope,'device',True)
            scope.close.assert_called_once();self.assertFalse(result['capabilities_passed']);self.assertTrue((root/'capability-result.json').exists())
    def test_quiescence_failure_retains_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=mock.Mock();scope.close.side_effect=RuntimeError('still writing');result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            capture.finalize(Path(tmp),result,None,scope,None,False)
            self.assertFalse(result['collection_complete']);self.assertIn('quiescence: still writing',result['errors']);self.assertTrue((Path(tmp)/'capability-result.json').exists())

if __name__=='__main__':unittest.main()
