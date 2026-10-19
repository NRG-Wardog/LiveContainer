import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import window_capture as w

class Frames(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name).resolve()
        self.rows=[]
        for i in range(2):
            raw=b'\x00\x00\x00\xff'*4;png=b'fixture-not-decoded-png'
            row={'index':i,'status':0,'statusName':'complete','newFrame':True,'displayTimeMach':100+i,'width':2,'height':2,'bytesPerRow':8,'contentRect':[0,0,2,2],
                'contentScale':1,'scaleFactor':1,'rawPixels':f'frame-{i:04d}.bgra','png':f'frame-{i:04d}.png','copiedBytes':len(raw),
                'rawPixelSHA256':hashlib.sha256(raw).hexdigest(),'pngSHA256':hashlib.sha256(png).hexdigest()}
            (self.folder/row['rawPixels']).write_bytes(raw);(self.folder/row['png']).write_bytes(png);self.rows.append(row)
        self.row={'schema':'p1-owned-window-acquisition-v1','ownerPID':123,'executable':w.SIMULATOR,'captureCompleted':True,'streamStopped':True,
            'startAttempted':True,'outputDetached':True,'windowRevalidationPassed':True,'admissionEligible':False,'calibrationFeasible':False,
            'feedbackLifetimeEstablished':False,'inputOverlapEstablished':False,'guestPresentationEquivalenceEstablished':False,'permissionRequested':False,
            'timebaseNumerator':125,'timebaseDenominator':3,'samples':{'frames':self.rows,'error':None,'overflowRecords':0,'deliveredRecords':2,'completeFrames':2,'copiedBytes':32}}
    def run_validation(self):
        (self.folder/'window-capture.json').write_text(json.dumps(self.row))
        with mock.patch('window_bgra.locate_bgra',create=True,side_effect=[{'marker':1,'session':'a'*32},{'marker':2,'session':'a'*32}]):
            return w.validate_frames(self.folder,123,'a'*32)
    def test_valid_exact_mapping(self):
        result=self.run_validation();self.assertTrue(result['ownedWindowTimestampAcquisitionEstablished']);self.assertFalse(result['admissionEligible'])
        self.assertEqual(result['frames'][0]['displayTimeNumerator'],12500)
        self.assertEqual(result['frames'][0]['displayTimeDenominator'],3_000_000_000)
    def test_owner_lifecycle_and_failure_negatives(self):
        for key,value in [('ownerPID',124),('executable','/tmp/Simulator'),('captureCompleted',False),('streamStopped',False),('outputDetached',False),('error','failed'),('permissionRequested',True),('timebaseNumerator',0),('timebaseDenominator',True)]:
            with self.subTest(key=key):
                prior=copy.deepcopy(self.row);self.row[key]=value
                with self.assertRaises(ValueError):self.run_validation()
                self.row=prior
    def test_sample_errors_cannot_be_filtered(self):
        for key,value in [('error','copy-failure'),('overflowRecords',1),('deliveredRecords',3),('completeFrames',1),('copiedBytes',31)]:
            with self.subTest(key=key):
                prior=copy.deepcopy(self.row);self.row['samples'][key]=value
                with self.assertRaises(ValueError):self.run_validation()
                self.row=prior
    def test_bad_frame_fails_whole_gate(self):
        for key,value in [('displayTimeMach',100),('displayTimeMach',True),('status',2),('newFrame',False),('width',True),('error','bad'),('rawPixels','../outside'),('rawPixelSHA256','0'*64),('contentScale',2)]:
            with self.subTest(key=key):
                prior=copy.deepcopy(self.row);self.row['samples']['frames'][1][key]=value
                with self.assertRaises(ValueError):self.run_validation()
                self.row=prior
    def test_nonvacuous_and_static_fail(self):
        self.row['samples']['frames']=[]
        with self.assertRaises(ValueError):self.run_validation()
    def test_idle_and_started_records_do_not_establish_frames(self):
        row={'index':2,'status':4,'statusName':'started','newFrame':False}
        self.row['samples']['frames'].append(row);self.row['samples']['deliveredRecords']=3
        with self.assertRaises(ValueError):self.run_validation()
    def test_frame_after_stopped_rejected(self):
        self.row['samples']['frames'][0].update(status=5,statusName='stopped',newFrame=False)
        with self.assertRaises(ValueError):self.run_validation()
    def test_static_and_wrong_nonce_decoder_failure(self):
        (self.folder/'window-capture.json').write_text(json.dumps(self.row))
        with mock.patch('window_bgra.locate_bgra',create=True,return_value={'marker':1,'session':'a'*32}):
            with self.assertRaises(ValueError):w.validate_frames(self.folder,123,'a'*32)
        with mock.patch('window_bgra.locate_bgra',create=True,side_effect=ValueError('wrong nonce')):
            with self.assertRaises(ValueError):w.validate_frames(self.folder,123,'a'*32)
    def test_real_bgra_decoder_end_to_end(self):
        from test_window_bgra import raster
        session='a'*32;total=0
        for index,row in enumerate(self.rows):
            raw,width,height,stride=raster([(9,11,5,session,index+1)])
            (self.folder/row['rawPixels']).write_bytes(raw)
            row.update(width=width,height=height,bytesPerRow=stride,contentRect=[0,0,width,height],
                copiedBytes=len(raw),rawPixelSHA256=hashlib.sha256(raw).hexdigest())
            total+=len(raw)
        self.row['samples']['copiedBytes']=total
        (self.folder/'window-capture.json').write_text(json.dumps(self.row))
        result=w.validate_frames(self.folder,123,session)
        self.assertEqual([r['marker'] for r in result['frames']],[1,2])
        self.assertTrue(all(r['session']==session for r in result['frames']))
        with self.assertRaises(ValueError):w.validate_frames(self.folder,123,'b'*32)
    def test_timeout_marker_blocks_success(self):
        (self.folder/'stage-timeout.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_validation()
    def test_linked_pixels_rejected(self):
        p=self.folder/'frame-0000.bgra';p.unlink();p.symlink_to(self.folder/'frame-0001.bgra')
        with self.assertRaises(ValueError):self.run_validation()

class Source(unittest.TestCase):
    def test_only_window_and_existing_permission(self):
        source=Path(w.__file__).with_suffix('.swift').read_text()
        self.assertIn('CGPreflightScreenCaptureAccess()',source);self.assertIn('SCContentFilter(desktopIndependentWindow: window)',source)
        for forbidden in ['CGRequestScreenCaptureAccess','SCContentSharingPicker','including:','excludingApplications:']:
            self.assertNotIn(forbidden,source)
        self.assertIn('configuration.capturesAudio = false',source);self.assertIn('configuration.captureMicrophone = false',source)
        self.assertIn('Data(bytes: address, count: size)',source);self.assertIn('removeStreamOutput',source)
    def test_success_after_drained_error_check(self):
        source=Path(w.__file__).with_suffix('.swift').read_text()
        self.assertEqual(source.count('sink.result()'),1)
        self.assertLess(source.index('let samples = sink.result()'),source.index('result["captureCompleted"] = result'))
        self.assertIn('samples["error"] is NSNull',source)
        self.assertIn('startAttempted && !stopConfirmed',source)
    def test_unchanged_budget_and_unique_route(self):
        source=Path(w.__file__).read_text()
        self.assertIn('Scope(output,phone_ui=True)',source)
        self.assertNotIn('run_calibration(',source);self.assertNotIn('run_layout(',source)
        self.assertIn("self.argv=[SIMULATOR,'-CurrentDeviceUDID',device]",source)
        self.assertIn('self.process.signal_owned(signal.SIGTERM)',source)
        self.assertIn('self.scope.settle(self.process)',source)

class Ownership(unittest.TestCase):
    def setup_gui(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);folder=Path(tmp.name).resolve()/'gui'
        scope=mock.Mock();scope.fixture={'owned_created':{}};scope.session='a'*32;scope.rows=[];scope.processes={};scope.remaining.return_value=10
        with mock.patch.object(w.fresh_device,'validate'):
            gui=w.OwnedGUI(scope,'00000000-0000-0000-0000-000000000001',folder)
        return gui,scope
    def test_partial_spawn_cleanup_still_available(self):
        gui,scope=self.setup_gui();scope.spawn.side_effect=OSError('spawn failed')
        with self.assertRaises(OSError):gui.start()
        gui.stop();self.assertTrue(gui.stopped);self.assertTrue(gui.file.closed)
        scope.settle.assert_not_called()
    def test_retained_process_and_exact_argv_required(self):
        gui,scope=self.setup_gui();process=mock.Mock();process.pid=123;process.poll.return_value=None
        gui.process=process;scope.processes[123]=process;scope.rows=[{'pid':123,'argv':gui.argv,'settled':False}]
        gui.live();scope.rows[0]['argv']=['other']
        with self.assertRaises(ValueError):gui.live()
        gui.stop();scope.settle.assert_called_once_with(process)
    def test_stop_timeout_remains_failed_after_settlement(self):
        gui,scope=self.setup_gui();process=mock.Mock();process.pid=123;process.signal_owned.return_value=True
        process.wait.side_effect=w.subprocess.TimeoutExpired(['owned'],10);gui.process=process
        with self.assertRaises(w.subprocess.TimeoutExpired):gui.stop()
        self.assertTrue(gui.stopped);scope.settle.assert_called_once_with(process);self.assertTrue(gui.file.closed)

class Readiness(unittest.TestCase):
    def test_exact_session_readiness_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();session='a'*32;folder=root/'Documents/p1-window'/session;folder.mkdir(parents=True)
            row={'schema':'p1-window-fixture-ready-v1','session':session,'marker':1,'drawBeforeUptime':1.0,'drawAfterUptime':1.1,
                'clock':'app-process-systemUptime','displayTimeEstablished':False,'admissionEligible':False}
            command=mock.Mock();command.scope.deadline=w.time.monotonic()+60
            path=folder/'ready.json';path.write_text(json.dumps(row))
            with mock.patch.object(w.capture,'container',return_value=root) as discovery:
                self.assertEqual(w.await_fixture_ready(command,'device',session,root),row)
                self.assertEqual(discovery.call_count,1)
            row['session']='b'*32;path.write_text(json.dumps(row))
            with mock.patch.object(w.capture,'container',return_value=root):
                with self.assertRaises(ValueError):w.await_fixture_ready(command,'device',session,root)
            row['session']=session;row['displayTimeEstablished']=True;path.write_text(json.dumps(row))
            with mock.patch.object(w.capture,'container',return_value=root):
                with self.assertRaises(ValueError):w.await_fixture_ready(command,'device',session,root)

if __name__=='__main__':unittest.main()

class StartupIsolation(unittest.TestCase):
    def row(self,elapsed=12):
        from test_capture_prerequisites import Prerequisites
        return {'exit_code':0,'failure_type':None,'cleanup_errors':[],'writer_settled':True,
            'launch_receipt':{'state':'pre-exec-observed','closed':True,'eof':True,'exec_failure':None},
            'wait_timing':{'command_started':1,'wait_finished':1+elapsed},'stdout':json.dumps(Prerequisites().result())}
    def invoke(self,row):
        with tempfile.TemporaryDirectory() as tmp:
            command=mock.Mock(return_value=row);folder=Path(tmp)
            try:return w.startup_isolation(command,Path('/exact/helper'),folder)
            finally:
                command.assert_called_once_with(Path('/exact/helper'),timeout=30,receipt=True)
                self.timing=json.loads((folder/'startup-isolation-timing.json').read_text())
    def test_clean_below_and_above_historical_bound(self):
        for seconds in (8,12,29):
            self.invoke(self.row(seconds));self.assertEqual(self.timing['historical_10s_exceeded'],seconds>10)
            self.assertFalse(self.timing['admissionEligible'])
    def test_timeout_unknown_and_unsettled_fail_with_metric(self):
        for key,value in [('failure_type','TimeoutExpired'),('exit_code',-15),('writer_settled',False),('cleanup_errors',[{'type':'Error'}]),('launch_receipt',{})]:
            row=self.row(30);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.invoke(row)
            self.assertTrue(self.timing['historical_10s_exceeded'])
    def test_permission_enumeration_or_existing_gui_fail(self):
        for key,value in [('screenCapturePreflight',False),('windowEnumerationAvailable',False),('simulatorProcessCount',1),('simulatorOnScreenWindowCount',1)]:
            row=self.row();check=json.loads(row['stdout']);check[key]=value;row['stdout']=json.dumps(check)
            with self.subTest(key=key),self.assertRaises(ValueError):self.invoke(row)
    def test_only_startup_allowance_changed_and_stage_receipts_fixed(self):
        source=(w.HERE/'window_capture.py').read_text()
        self.assertIn("check=json.loads(command(preflight,timeout=10))",source)
        self.assertIn("command(helper,str(gui.process.pid),SIMULATOR,frames,timeout=90)",source)
        text=(w.HERE/'capture_prerequisites.swift').read_text()
        stages=['helper-entered','preflight-returned','process-enumeration-returned','window-enumeration-returned']
        self.assertEqual([text.count('phase("'+x+'")') for x in stages],[1]*4)
        self.assertIn('FileHandle.standardError.write(data)',text)


class NativeBootstrap(unittest.TestCase):
    def test_appkit_initialized_on_main_actor_before_graphics(self):
        text=(w.HERE/'window_capture.swift').read_text()
        self.assertIn('@MainActor static func main() async',text)
        self.assertLess(text.index('deadline.arm(10, "appkit-initialization")'),text.index('_ = NSApplication.shared'))
        self.assertLess(text.index('_ = NSApplication.shared'),text.index('CGPreflightScreenCaptureAccess()'))
        self.assertIn('"phase": "appkit-initialized"',text)
        self.assertNotIn('activate(ignoringOtherApps:',text)
        self.assertNotIn('CGRequestScreenCaptureAccess',text)

class PostGUIState(unittest.TestCase):
    def setup_case(self,folder,state='Shutdown'):
        from test_stall_fresh import proof,DEVICE,SESSION
        import types
        p=proof();scope=types.SimpleNamespace(session=SESSION,creation_intent={k:v for k,v in p.items() if k not in ('device','create_complete')},
            fixture={'owned_created':p,'device':DEVICE,'owned_boot':True,'deleted':False},rows=[{'settled':True}],fixture_stopped=mock.Mock())
        gui=types.SimpleNamespace(scope=scope,stopped=True,process=object())
        inventory={'devices':{p['runtime']:[{'udid':DEVICE,'state':state,'isAvailable':True,'deviceTypeIdentifier':p['device_type']}]}}
        row={'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[],'writer_settled':True,'stdout':json.dumps(inventory),
             'launch_receipt':{'state':'pre-exec-observed','closed':True,'eof':True,'exec_failure':None}}
        command=mock.Mock(return_value=row);command.scope=scope
        return command,gui,DEVICE,row
    def test_shutdown_proof_and_booted_fallback(self):
        for state in ('Shutdown','Booted'):
            with tempfile.TemporaryDirectory() as tmp:
                c,g,d,r=self.setup_case(Path(tmp),state)
                self.assertEqual(w.observe_after_gui_stop(c,g,d,Path(tmp)),state)
                c.assert_called_once_with('xcrun','simctl','list','devices','--json',timeout=15,cleanup=True,receipt=True)
                if state=='Shutdown':c.scope.fixture_stopped.assert_called_once_with(True)
                else:c.scope.fixture_stopped.assert_not_called()
    def test_bad_ownership_or_unsettled_gui_blocks_query(self):
        for kind in ('session','intent','writers','gui','deleted'):
            with tempfile.TemporaryDirectory() as tmp:
                c,g,d,r=self.setup_case(Path(tmp))
                if kind=='session':c.scope.session='0'*32
                elif kind=='intent':c.scope.creation_intent['name']='wrong'
                elif kind=='writers':c.scope.rows[0]['settled']=False
                elif kind=='gui':g.stopped=False
                else:c.scope.fixture['deleted']=True
                with self.assertRaises(ValueError):w.observe_after_gui_stop(c,g,d,Path(tmp))
                c.assert_not_called();c.scope.fixture_stopped.assert_not_called()
    def test_failed_unknown_wrong_identity_queries_never_mark_stopped(self):
        for kind in ('timeout','launch','runtime','type','missing'):
            with tempfile.TemporaryDirectory() as tmp:
                c,g,d,r=self.setup_case(Path(tmp))
                if kind=='timeout':r['failure_type']='TimeoutExpired'
                elif kind=='launch':r['launch_receipt']={}
                else:
                    inv=json.loads(r['stdout']);key=next(iter(inv['devices']))
                    if kind=='runtime':inv['devices']['wrong']=inv['devices'].pop(key)
                    elif kind=='type':inv['devices'][key][0]['deviceTypeIdentifier']='wrong'
                    else:inv['devices'][key]=[]
                    r['stdout']=json.dumps(inv)
                with self.assertRaises(ValueError):w.observe_after_gui_stop(c,g,d,Path(tmp))
                c.scope.fixture_stopped.assert_not_called()
    def test_expired_cleanup_budget_remains_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,g,d,r=self.setup_case(Path(tmp));c.side_effect=TimeoutError('reserve exhausted')
            with self.assertRaises(TimeoutError):w.observe_after_gui_stop(c,g,d,Path(tmp))
            c.scope.fixture_stopped.assert_not_called()


class WindowBinding(unittest.TestCase):
    def test_revalidation_cannot_select_or_capture_a_different_window(self):
        text=(w.HERE/'window_capture.swift').read_text()
        self.assertIn('select(nil, phase: "initial")',text)
        self.assertIn('select(window.windowID, phase: "final")',text)
        self.assertIn('windows.count == 1, "ambiguous-owned-window"',text)
        self.assertIn('let matching = windows.filter { $0.windowID == expected }',text)
        self.assertIn('matching.count == 1, "original-owned-window-missing"',text)
        self.assertIn('after.windowID == window.windowID && after.frame == window.frame',text)
        self.assertEqual(text.count('SCContentFilter(desktopIndependentWindow: window)'),1)
    def test_census_is_bounded_owned_only_and_rejects_duplicates(self):
        text=(w.HERE/'window_capture.swift').read_text()
        self.assertIn('$0.owningApplication?.processID == pid && $0.isOnScreen',text)
        self.assertLess(text.index('windows.count <= 16'),text.index('let census:'))
        self.assertIn('Set(windows.map { $0.windowID }).count == windows.count',text)
        self.assertIn('windows.allSatisfy { valid($0.frame) }',text)
        self.assertNotIn('.title',text)


class FixtureLaunch(unittest.TestCase):
    def invoke(self,elapsed=40,change=None):
        row=StartupIsolation().row(elapsed);row['primary_error']=None
        if change:row.update(change)
        with tempfile.TemporaryDirectory() as tmp:
            c=mock.Mock(return_value=row);folder=Path(tmp)
            try:w.launch_fixture(c,'owned-device','a'*32,folder)
            finally:
                c.assert_called_once_with('xcrun','simctl','launch','owned-device',w.capture.APP_ID,'--window-capture-fixture','--session','a'*32,timeout=120,receipt=True)
                self.timing=json.loads((folder/'fixture-launch-timing.json').read_text())
    def test_completion_below_and_above_historical_threshold(self):
        for seconds in (11,40,119):
            self.invoke(seconds);self.assertEqual(self.timing['historical_30s_exceeded'],seconds>30);self.assertFalse(self.timing['admissionEligible'])
    def test_timeout_unknown_and_unsettled_fail_without_retry(self):
        for changes in ({'failure_type':'TimeoutExpired'},{'exit_code':-15},{'writer_settled':False},{'launch_receipt':{}},{'cleanup_errors':[{'type':'Error'}]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.invoke(120,changes)
            self.assertTrue(self.timing['historical_30s_exceeded'])

class DeferredWriter(unittest.TestCase):
    def fixture(self):
        from types import SimpleNamespace
        writer=mock.Mock();writer.pid=71;writer.poll.return_value=None
        launch={'eof':True,'exec_failure':None};writer.launch.row=launch
        row={'pid':71,'argv':['xcodebuild','test-without-building'],'settled':False,'launch_receipt':launch}
        gui=w.OwnedGUI.__new__(w.OwnedGUI);gui.active_writer=writer;gui.active_argv=tuple(row['argv'])
        gui.scope=SimpleNamespace(processes={71:writer},rows=[row])
        return gui,writer,row
    def test_only_exact_retained_live_writer_accepted(self):
        gui,writer,row=self.fixture();gui.validate_writers();writer.launch.require.assert_called_once()
    def test_default_still_rejects_any_unsettled_writer(self):
        gui,writer,row=self.fixture();gui.active_writer=None;gui.active_argv=None
        with self.assertRaises(ValueError):gui.validate_writers()
    def test_foreign_second_settled_or_wrong_argv_rejected(self):
        for kind in ('object','second','settled','unknown-settlement','argv','receipt','eof','exec','exit'):
            with self.subTest(kind=kind):
                gui,writer,row=self.fixture()
                if kind=='object':gui.scope.processes[71]=mock.Mock()
                if kind=='second':gui.scope.rows.append({'pid':72,'settled':False})
                if kind=='settled':row['settled']=True
                if kind=='unknown-settlement':row['settled']=None
                if kind=='argv':row['argv']=['foreign']
                if kind=='receipt':row['launch_receipt']=dict(writer.launch.row)
                if kind=='eof':writer.launch.row['eof']=False
                if kind=='exec':writer.launch.row['exec_failure']={'errno':2}
                if kind=='exit':writer.poll.return_value=0
                with self.assertRaises(ValueError):gui.validate_writers()
