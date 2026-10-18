import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import boot_diagnostic as boot
import fresh_device as fresh
import process_scope
import budget

DEVICE='11111111-2222-4333-8444-555555555555'
SESSION='a'*32

def proof():return {'schema':'p1-created-device-v1','session':SESSION,'name':'P1-stall-'+SESSION,'runtime':boot.RUNTIME,'device_type':fresh.TYPE,'type_verified':True,'preexisting':[boot.DEVICE],'device':DEVICE,'create_complete':True}
def raw(device=DEVICE,state='Shutdown',runtime=boot.RUNTIME,kind=fresh.TYPE):return json.dumps({'devices':{runtime:[{'udid':device,'state':state,'isAvailable':True,'deviceTypeIdentifier':kind}]}}).encode()
def commandrow(state='Shutdown',absent=False):
    data={'devices':{boot.RUNTIME:[] if absent else [{'udid':DEVICE,'state':state}]}}
    return {'exit_code':0,'primary_error':None,'cleanup_errors':[],'failure_type':None,'writer_settled':True,'stdout':json.dumps(data),'data':data}

class FreshTests(unittest.TestCase):
    def test_probe_failure_remains_failed_diagnostic(self):
        import stall_diagnostic as stall
        pair={'probes':[{'mode':mode,'exit_code':0,'failure':None,'cleanup_errors':[],'launch_receipt':{'state':'pre-exec-observed','exec_failure':None,'closed':True,'eof':True}} for mode in ('full','minimal')]}
        self.assertFalse(stall.probe_failed(pair))
        for key,value in [('exit_code',1),('failure',{'type':'TimeoutExpired'}),('cleanup_errors',[{'type':'LaunchReceiptError'}]),('launch_receipt',{'state':'unknown'})]:
            bad=copy.deepcopy(pair);bad['probes'][0][key]=value
            self.assertTrue(stall.probe_failed(bad))
        self.assertTrue(stall.probe_failed(None));self.assertTrue(stall.probe_failed({'probes':[]}))
    def test_type_is_derived_and_available(self):
        kind='com.apple.CoreSimulator.SimDeviceType.iPhone-16'
        self.assertEqual(fresh.before(raw(boot.DEVICE,kind=kind))['device_type'],kind)
        self.assertTrue(fresh.available_type(kind)(json.dumps({'devicetypes':[{'identifier':kind}]}).encode())['type_verified'])
        with self.assertRaises(ValueError):fresh.available_type(kind)(b'{"devicetypes":[]}')
    def test_uuid_strict(self):
        self.assertEqual(fresh.created_uuid((DEVICE+'\n').encode()),DEVICE)
        for v in ('',DEVICE+'\n'+DEVICE,DEVICE+' x',' '+DEVICE,DEVICE+'\n\n'):
            with self.subTest(v=v),self.assertRaises(ValueError):fresh.created_uuid(v.encode())
    def test_before_exact_type_runtime_and_shutdown(self):
        self.assertEqual(fresh.before(raw(boot.DEVICE))['device_type'],fresh.TYPE)
        for kwargs in ({'state':'Booted'},{'runtime':'wrong'},{'kind':'wrong'}):
            with self.assertRaises(ValueError):fresh.before(raw(boot.DEVICE,**kwargs))
    def test_wrong_identity_rejected(self):
        for field,value in [('device',boot.DEVICE),('runtime','bad'),('device_type','bad'),('session','b'*32),('create_complete',False),('preexisting',[boot.DEVICE,DEVICE])]:
            p=proof();p[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):fresh.validate(p,SESSION,p['device'])
    def test_dynamic_inventory_rejects_drift(self):
        for kw in ({'runtime':'wrong'},{'kind':'wrong'},{'device':boot.DEVICE}):
            with self.assertRaises(ValueError):fresh.state_parser(DEVICE)(raw(**kw))
        duplicate=json.loads(raw());duplicate['devices'][boot.RUNTIME]*=2
        with self.assertRaises(ValueError):fresh.state_parser(DEVICE)(json.dumps(duplicate).encode())
    def test_intent_before_creation_and_persistence_failure(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            scope=process_scope.Scope(Path(t),stall_diagnostic=True);p=proof();intent={k:v for k,v in p.items() if k not in ('device','create_complete')}
            scope.begin_creation(intent)
            with self.assertRaises(RuntimeError):scope.close()
            with mock.patch.object(scope,'persist',side_effect=OSError('write')):
                with self.assertRaises(OSError):scope.fixture_created(p)
            saved=json.loads(scope.path.read_text());self.assertIsNone(saved['fixture'])
    def test_scope_requires_deletion(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            scope=process_scope.Scope(Path(t),stall_diagnostic=True);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p);scope.fixture_stopped(True)
            with self.assertRaises(RuntimeError):scope.close()
            scope.fixture_deleted(True);scope.close()
    def test_cleanup_shutdown_delete_absence(self):
        command=mock.Mock(side_effect=[commandrow(),commandrow(),commandrow(absent=True)])
        result=fresh.cleanup(command,proof(),lambda:True)
        self.assertTrue(result['deleted']);self.assertFalse(result['command_failed'])
        self.assertEqual(command.call_args_list[1].args,('xcrun','simctl','delete',DEVICE))
    def test_unsettled_no_commands(self):
        command=mock.Mock()
        with self.assertRaises(ValueError):fresh.cleanup(command,proof(),lambda:False)
        command.assert_not_called()
    def test_unsettled_after_query_no_delete(self):
        command=mock.Mock(return_value=commandrow());states=iter([True,False])
        self.assertFalse(fresh.cleanup(command,proof(),lambda:next(states))['deleted']);self.assertEqual(command.call_count,1)
    def test_failed_state_no_delete(self):
        row=commandrow();row.update(exit_code=1,failure_type='CalledProcessError')
        command=mock.Mock(return_value=row)
        self.assertFalse(fresh.cleanup(command,proof(),lambda:True)['deleted']);self.assertEqual(command.call_count,1)
    def test_timeout_preserved_on_recovery(self):
        row=commandrow();row.update(exit_code=None,primary_error={'type':'TimeoutExpired'},failure_type='TimeoutExpired')
        command=mock.Mock(side_effect=[row,commandrow(),commandrow(),commandrow(),commandrow(absent=True)])
        result=fresh.cleanup(command,proof(),lambda:True);self.assertTrue(result['deleted']);self.assertTrue(result['command_failed'])
    def test_delete_failure_retained_even_if_absent(self):
        failed=commandrow();failed.update(exit_code=1,failure_type='CalledProcessError')
        result=fresh.cleanup(mock.Mock(side_effect=[commandrow(),failed,commandrow(absent=True)]),proof(),lambda:True)
        self.assertTrue(result['deleted']);self.assertTrue(result['command_failed'])
    def test_delete_remaining_blocks(self):
        result=fresh.cleanup(mock.Mock(side_effect=[commandrow(),commandrow(),commandrow()]),proof(),lambda:True)
        self.assertFalse(result['deleted'])
    def test_prior_deleted_recovers_fresh_absence(self):
        command=mock.Mock(return_value=commandrow(absent=True));result=fresh.cleanup(command,proof(),lambda:True)
        self.assertTrue(result['deleted']);self.assertTrue(result['observed_absence']);self.assertFalse(result['observed_shutdown']);self.assertEqual(command.call_count,1)
    def test_commands_allowlist(self):
        with tempfile.TemporaryDirectory() as t:
            cmd=fresh.Commands(mock.Mock(),Path(t),proof())
            for argv in [('xcrun','simctl','delete',boot.DEVICE),('xcrun','simctl','shutdown','all')]:
                with self.assertRaises(ValueError):cmd(*argv)
    def test_unknown_creation_backstop_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);process_scope.atomic(p/'process-registry.json',{'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':True,'groups':[],'fixture':None,'creation_intent':proof()})
            with self.assertRaises(ValueError):budget.verify_quiescence(p,SESSION,force=True)
    def test_outer_created_cleanup(self):
        with tempfile.TemporaryDirectory() as t,mock.patch.dict('os.environ',{'P1_PROCESS_SCOPE_SESSION':SESSION}):
            root=Path(t);scope=process_scope.Scope(root,stall_diagnostic=True);p=proof();scope.begin_creation({k:v for k,v in p.items() if k not in ('device','create_complete')});scope.fixture_created(p)
            command=mock.Mock(side_effect=[commandrow(),commandrow(),commandrow(absent=True)])
            with mock.patch.object(fresh,'backstop',return_value=command):budget.verify_quiescence(root,SESSION,force=True)
            self.assertTrue(json.loads(scope.path.read_text())['fixture']['deleted'])
    def test_outer_forged_original_blocked(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=proof();p['device']=boot.DEVICE
            process_scope.atomic(root/'process-registry.json',{'schema':'p1-capability-process-scope-v1','session':SESSION,'closing':False,'groups':[],'fixture':{'device':boot.DEVICE,'owned_created':p},'creation_intent':p})
            with self.assertRaises(ValueError):budget.verify_quiescence(root,SESSION,force=True)
    def test_expired_cleanup_reserve(self):
        with tempfile.TemporaryDirectory() as t:
            scope=process_scope.Scope(Path(t),stall_diagnostic=True);scope.cleanup_deadline=0
            cmd=fresh.Commands(scope,Path(t),proof())
            result=fresh.cleanup(cmd,proof(),lambda:True)
            self.assertFalse(result['deleted']);self.assertTrue(result['command_failed'])

if __name__=='__main__':unittest.main()
