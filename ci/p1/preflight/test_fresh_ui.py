import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import capture
import process_scope
import fresh_device as fresh
from test_stall_fresh import proof,DEVICE,SESSION

class FreshUI(unittest.TestCase):
    def test_ui_cleanup_reserve_is_bounded_without_increasing_observation(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(process_scope.time,'monotonic',return_value=100):
            scope=process_scope.Scope(Path(tmp),phone_ui=True)
            self.assertEqual(scope.deadline,1120);self.assertEqual(scope.cleanup_deadline,1240)
            with mock.patch.object(process_scope.time,'monotonic',return_value=1241):
                with self.assertRaises(TimeoutError):scope.remaining(15,cleanup=True)
    def test_unknown_creation_and_postcreate_inventory_failure_preserve_obligation(self):
        for fail in ('create','created-state'):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION,'ImageVersion':'20261013.0424.1'}):
                root=Path(tmp);scope=process_scope.Scope(root,phone_ui=True)
                values={'xcode-version':{'exact_public_tool_output':'Xcode 26.4.1\nBuild version 17E202'},'runtime':{'buildversion':'23C54'},'before-state':{'preexisting':[fresh.boot.DEVICE],'runtime':fresh.boot.RUNTIME,'device_type':fresh.TYPE},'device-type':{'device_type':fresh.TYPE,'type_verified':True},'create':DEVICE}
                def run(label,*args,**kwargs):
                    return {'exit_code':0,'failure_type':'ValueError' if label==fail else None,'primary_error':None,'cleanup_errors':[],'data':values.get(label)}
                with mock.patch.object(fresh.boot,'Commands') as commands:
                    commands.return_value.run.side_effect=run
                    with self.assertRaises(ValueError):fresh.create_for_ui(scope,root/'create')
                self.assertIsNotNone(scope.creation_intent)
                if fail=='create':self.assertIsNone(scope.fixture)
                else:self.assertEqual(scope.fixture['device'],DEVICE);self.assertFalse(scope.fixture['deleted'])
                with self.assertRaises(RuntimeError):scope.close()
    def test_creation_preserves_intent_before_command_and_ownership_before_state(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION,'ImageVersion':'20261013.0424.1'}):
            root=Path(tmp);scope=process_scope.Scope(root);seen=[]
            def run(label,argv,parser,timeout=10):
                seen.append((label,argv,timeout))
                values={'xcode-version':{'exact_public_tool_output':'Xcode 26.4.1\nBuild version 17E202'},'runtime':{'buildversion':'23C54'},'before-state':{'preexisting':[fresh.boot.DEVICE],'runtime':fresh.boot.RUNTIME,'device_type':fresh.TYPE},'device-type':{'device_type':fresh.TYPE,'type_verified':True},'create':DEVICE,'created-state':{'devices':{fresh.boot.RUNTIME:[{'state':'Shutdown'}]}}}
                if label=='create':self.assertIsNotNone(json.loads(scope.path.read_text())['creation_intent'])
                if label=='created-state':self.assertEqual(json.loads(scope.path.read_text())['fixture']['device'],DEVICE)
                return {'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[],'data':values[label]}
            with mock.patch.object(fresh.boot,'Commands') as commands:
                commands.return_value.run.side_effect=run
                p=fresh.create_for_ui(scope,root/'create')
            self.assertEqual(p['device'],DEVICE);self.assertEqual(seen[-2][2],30)
            self.assertFalse(any('boot' in argv for _,argv,_ in seen))
    def test_finalization_recovers_created_device_before_execute_received_uuid(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope=process_scope.Scope(root);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            command=mock.Mock();command.scope=scope;result={'errors':['inventory failed'],'capabilities_passed':False,'collection_complete':False}
            with mock.patch.object(capture,'stop_fixture',return_value=True),mock.patch.object(fresh,'Commands'),mock.patch.object(fresh,'cleanup',return_value={'observed_shutdown':True,'deleted':True,'command_failed':False}) as cleanup:
                capture.finalize(root,result,command,scope,None,False)
            cleanup.assert_called_once();self.assertTrue(scope.fixture['deleted']);self.assertTrue(scope.fixture['stopped']);self.assertFalse(result['capabilities_passed'])
    def test_failed_deletion_cannot_pass_ui(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope=process_scope.Scope(root);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            command=mock.Mock();command.scope=scope;result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            with mock.patch.object(capture,'stop_fixture',return_value=True),mock.patch.object(fresh,'Commands'),mock.patch.object(fresh,'cleanup',return_value={'observed_shutdown':True,'deleted':False,'command_failed':True}):
                capture.finalize(root,result,command,scope,DEVICE,True)
            self.assertFalse(result['capabilities_passed']);self.assertFalse(result['collection_complete']);self.assertFalse(scope.fixture['deleted'])
    def test_terminate_timeout_remains_failure_after_clean_owned_deletion(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope=process_scope.Scope(root,phone_ui=True);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            command=mock.Mock(side_effect=[subprocess.TimeoutExpired('terminate',15),{'exit_code':0,'failure_type':None}]);command.scope=scope
            result={'errors':[],'capabilities_passed':True,'collection_complete':True}
            with mock.patch.object(capture.simulator_cleanup,'confirm_shutdown',return_value={'observed_shutdown':True,'command_failed':False}),mock.patch.object(fresh,'Commands'),mock.patch.object(fresh,'cleanup',return_value={'observed_shutdown':True,'deleted':True,'command_failed':False}):
                capture.finalize(root,result,command,scope,DEVICE,True)
            self.assertTrue(scope.fixture['deleted']);self.assertTrue(scope.fixture['cleanup_command_failed']);self.assertFalse(result['capabilities_passed']);self.assertFalse(result['collection_complete'])
    def test_expected_missing_app_does_not_latch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            scope=process_scope.Scope(Path(tmp));scope.fixture_identity(DEVICE,True)
            rows=[]
            for identifier in [capture.APP_ID,capture.RUNNER_ID]:
                text=(f'An error was encountered processing the command (domain=NSPOSIXErrorDomain, code=3):\nSimulator device failed to terminate {identifier}.\nfound nothing to terminate\nUnderlying error (domain=NSPOSIXErrorDomain, code=3):\n\tThe request to terminate "{identifier}" failed. found nothing to terminate\n\tfound nothing to terminate\n')
                rows.append({'exit_code':3,'failure_type':'CalledProcessError','stdout':'','stderr':text})
            command=mock.Mock(side_effect=rows);command.scope=scope
            self.assertTrue(capture.stop_fixture(command,DEVICE,Path(tmp)))
            self.assertFalse(scope.fixture.get('cleanup_command_failed',False));scope.close()
    def test_fresh_install_skips_once_and_persists_before_return(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope=process_scope.Scope(root);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            command=mock.Mock();command.scope=scope
            result=capture.prepare_install(command,DEVICE)
            self.assertTrue(result['uninstalls_skipped']);command.assert_not_called()
            self.assertTrue(json.loads(scope.path.read_text())['fixture']['installation_attempted'])
            with self.assertRaises(ValueError):capture.prepare_install(command,DEVICE)
    def test_fresh_install_rejects_unknown_wrong_or_unsettled_ownership(self):
        for kind in ('session','device','intent','unsettled','missing-attempt','deleted'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
                scope=process_scope.Scope(Path(tmp));p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
                if kind=='session':scope.fixture['owned_created']['session']='b'*32
                if kind=='device':scope.fixture['device']=fresh.boot.DEVICE
                if kind=='intent':scope.creation_intent=None
                if kind=='unsettled':scope.rows.append({'settled':False})
                if kind=='missing-attempt':scope.fixture.pop('installation_attempted')
                if kind=='deleted':scope.fixture['deleted']=True
                with self.assertRaises(ValueError):fresh.begin_install(scope,DEVICE)
    def test_fresh_install_persist_failure_cannot_return_exemption(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            scope=process_scope.Scope(Path(tmp));p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            with mock.patch.object(scope,'persist',side_effect=OSError('write')):
                with self.assertRaises(OSError):fresh.begin_install(scope,DEVICE)
            self.assertTrue(scope.fixture['installation_attempted'])
            with self.assertRaises(ValueError):fresh.begin_install(scope,DEVICE)
    def test_original_ui_assertions_and_deadlines_retained(self):
        text=Path(capture.__file__).read_text()
        self.assertNotIn('runner.available_devices()',text)
        self.assertIn('fresh_device.create_for_ui',text)
        for token in ('timeout=360','timeout=2400 if full_recovery else 480','timeout=120','timeout=30',"'optional uninstall writer settlement unproved'","'source drift'"):
            self.assertIn(token,text)

if __name__=='__main__':unittest.main()

class CreatedShutdownFirst(unittest.TestCase):
    def setup_scope(self,root):
        scope=process_scope.Scope(root,phone_ui=True);p=proof();scope.session=SESSION
        scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
        return scope,p
    def state(self,p,state='Shutdown'):
        return {'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[],
                'stdout':json.dumps({'devices':{fresh.boot.RUNTIME:[{'udid':DEVICE,'state':state,'isAvailable':True,'deviceTypeIdentifier':p['device_type']}]}})}
    def test_shutdown_allowance_is_exact_owned_and_reserve_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope,p=self.setup_scope(root)
            argv=['xcrun','simctl','shutdown',DEVICE]
            self.assertEqual(scope.owned_shutdown_remaining(argv,60),30)
            self.assertEqual(scope.remaining(60,cleanup=True),15)
            for bad in [['xcrun','simctl','shutdown',fresh.boot.DEVICE],['xcrun','simctl','delete',DEVICE],['xcrun','simctl','shutdown','all']]:
                with self.assertRaises(ValueError):scope.owned_shutdown_remaining(bad,30)
            with mock.patch.object(process_scope.time,'monotonic',return_value=scope.cleanup_deadline-5):self.assertEqual(scope.owned_shutdown_remaining(argv,30),5)
            with mock.patch.object(process_scope.time,'monotonic',return_value=scope.cleanup_deadline+1):
                with self.assertRaises(TimeoutError):scope.owned_shutdown_remaining(argv,30)
            scope.fixture=None
            with self.assertRaises(ValueError):scope.owned_shutdown_remaining(argv,30)
    def test_shutdown_override_rejects_non_cleanup_before_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope,p=self.setup_scope(root);command=process_scope.Commands(scope,root)
            with self.assertRaises(ValueError):command('xcrun','simctl','shutdown',DEVICE,timeout=30,owned_shutdown=True)
            self.assertFalse(scope.rows)
    def test_exact_created_shutdown_first_and_reuse_proven_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope,p=self.setup_scope(root)
            command=mock.Mock(side_effect=[{'exit_code':0,'failure_type':None},self.state(p)]);command.scope=scope
            self.assertTrue(capture.stop_fixture(command,DEVICE,root));self.assertTrue(capture.stop_fixture(command,DEVICE,root))
            self.assertEqual(len(command.call_args_list),2)
            self.assertEqual(command.call_args_list[0],mock.call('xcrun','simctl','shutdown',DEVICE,timeout=30,cleanup=True,receipt=True,owned_shutdown=True))
            self.assertEqual(command.call_args_list[1],mock.call('xcrun','simctl','list','devices','--json',timeout=15,cleanup=True,receipt=True))
            self.assertTrue(scope.fixture['stopped']);self.assertFalse(scope.fixture.get('cleanup_command_failed',False))
    def test_reject_unowned_wrong_intent_unsettled_deleted(self):
        for kind in ('device','intent','unsettled','deleted'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);scope,p=self.setup_scope(root);command=mock.Mock();command.scope=scope
                if kind=='device':scope.fixture['device']=fresh.boot.DEVICE
                if kind=='intent':scope.creation_intent=None
                if kind=='unsettled':scope.rows=[{'settled':False}]
                if kind=='deleted':scope.fixture['deleted']=True
                with self.assertRaises(ValueError):capture.stop_fixture(command,DEVICE,root)
                command.assert_not_called()
    def test_failed_shutdown_retained_after_fresh_shutdown_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scope,p=self.setup_scope(root)
            command=mock.Mock(side_effect=[{'exit_code':-15,'failure_type':'TimeoutExpired','primary_error':{'type':'TimeoutExpired'}},self.state(p)]);command.scope=scope
            self.assertTrue(capture.stop_fixture(command,DEVICE,root));self.assertTrue(scope.fixture['cleanup_command_failed'])
    def test_state_ambiguity_and_expired_reserve_fail_closed(self):
        for kind in ('booted','wrong-runtime','timeout'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);scope,p=self.setup_scope(root);state=self.state(p,'Booted' if kind=='booted' else 'Shutdown')
                if kind=='wrong-runtime':state['stdout']=state['stdout'].replace(fresh.boot.RUNTIME,'wrong-runtime')
                command=mock.Mock(side_effect=TimeoutError('cleanup reserve exhausted') if kind=='timeout' else [{'exit_code':0,'failure_type':None},state]);command.scope=scope
                with self.assertRaises((ValueError,TimeoutError)):capture.stop_fixture(command,DEVICE,root)
                self.assertFalse(scope.fixture['stopped']);self.assertTrue(scope.fixture['cleanup_command_failed'])

class DirectCleanupAttempt(unittest.TestCase):
    def scope(self,root):
        scope=process_scope.Scope(root,phone_ui=True);p=proof()
        scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
        return scope,p
    def test_persist_failure_prevents_submission_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope,p=self.scope(root);scope.cleanup_deadline=fresh.time.monotonic()+120
            command=mock.Mock();command.scope=scope
            with mock.patch.object(scope,'persist',side_effect=OSError('test')):
                with self.assertRaises(OSError):fresh.stop_owned(command,DEVICE,root,direct_deadline=True)
            command.assert_not_called()
            with self.assertRaisesRegex(ValueError,'already attempted'):fresh.begin_shutdown_attempt(scope,DEVICE)
    def test_durable_marker_blocks_collector_and_backstop_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope,p=self.scope(root);fresh.begin_shutdown_attempt(scope,DEVICE)
            saved=json.loads(scope.path.read_text())
            local=fresh.Commands(scope,root/'local',p)
            outer=fresh.backstop(root,[],[],lambda e:e,p,saved['fixture'],saved['creation_intent'])
            for command in (local,outer):
                with mock.patch.object(command,'run') as run:
                    with self.assertRaisesRegex(ValueError,'already attempted'):command('xcrun','simctl','shutdown',DEVICE)
                    run.assert_not_called()
            for value in (True,None,{},dict(saved['fixture']['direct_shutdown_attempt'],device=fresh.boot.DEVICE)):
                scope.fixture['direct_shutdown_attempt']=value
                with self.assertRaises(ValueError):local('xcrun','simctl','list','devices','--json')
    def test_expired_reserve_prevents_attempt(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope,p=self.scope(root);scope.cleanup_deadline=fresh.time.monotonic()+59
            command=mock.Mock();command.scope=scope
            with self.assertRaises(TimeoutError):fresh.stop_owned(command,DEVICE,root,direct_deadline=True)
            command.assert_not_called();self.assertNotIn('direct_shutdown_attempt',scope.fixture)
    def test_attempt_allows_only_fresh_shutdown_deletion_and_retains_failure(self):
        for state in ('Booted','Shutdown','Booting'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
                root=Path(tmp);scope,p=self.scope(root);fresh.begin_shutdown_attempt(scope,DEVICE);scope.fixture_cleanup_failure()
                command=fresh.Commands(scope,root/'cleanup',p);seen=[]
                def run(label,argv,parser,timeout,cleanup):
                    seen.append(label)
                    data={'devices':{fresh.boot.RUNTIME:[] if 'created-delete' in seen else [{'udid':DEVICE,'state':state,'isAvailable':True,'deviceTypeIdentifier':p['device_type']}]}}
                    try:parsed=parser(json.dumps(data).encode())
                    except ValueError:return {'data':None,'exit_code':0,'failure_type':'ValueError','primary_error':None,'cleanup_errors':[]}
                    return {'data':parsed,'exit_code':0,'failure_type':None,'primary_error':None,'cleanup_errors':[]}
                with mock.patch.object(command,'run',side_effect=run):result=fresh.cleanup(command,p,lambda:True)
                self.assertNotIn('created-shutdown',seen)
                self.assertEqual(result['deleted'],state=='Shutdown')
                self.assertTrue(scope.fixture['cleanup_command_failed'])
    def test_single_shutdown_reserves_four_proofs_and_retains_timeout(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(tmp);scope,p=self.scope(root);scope.cleanup_deadline=220
            calls=[]
            def command(*argv,**kwargs):
                calls.append((argv,kwargs))
                if 'shutdown' in argv:
                    persisted=json.loads(scope.path.read_text())
                    self.assertTrue(fresh.shutdown_attempt(persisted['fixture'],p,persisted['creation_intent'],SESSION))
                    self.assertEqual(kwargs['timeout'],60)
                    return {'exit_code':-15,'failure_type':'TimeoutExpired','cleanup_errors':[]}
                return {'exit_code':0,'failure_type':None,'stdout':json.dumps({'devices':{fresh.boot.RUNTIME:[{'udid':DEVICE,'state':'Shutdown','isAvailable':True,'deviceTypeIdentifier':p['device_type']}]}})}
            command.scope=scope
            with mock.patch.object(fresh.time,'monotonic',return_value=100):
                self.assertTrue(fresh.stop_owned(command,DEVICE,root,direct_deadline=True))
            self.assertEqual(len(calls),2);self.assertTrue(scope.fixture['cleanup_command_failed'])
