"""Bounded synthetic raw retention and immutable settled transport tests."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
from capture_retention import CaptureRetentionMixin
from retention import RawStore,BOUNDS,RetentionError
from native_gate import evidence_inventory,verify_transport,tool_identity
from inventory import dump


class RetentionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.gate=CaptureRetentionMixin();self.gate.store=RawStore(self.root/'capture')
    def test_nested_budget_adds_all_logical_counts(self):
        self.gate.merge_nested_budget({'logical_files':3,'logical_bytes':91,'directories':4})
        self.assertEqual((self.gate.store.file_count,self.gate.store.total_bytes,self.gate.store.directory_count),(3,91,4))
    def test_nested_budget_failure_is_atomic(self):
        self.gate.store.total_bytes=BOUNDS['total_bytes']-2
        with self.assertRaises(ValueError):self.gate.merge_nested_budget({'logical_files':1,'logical_bytes':3,'directories':1})
        self.assertEqual(self.gate.store.file_count,0);self.assertEqual(self.gate.store.directory_count,0)
    def test_boolean_or_negative_budget_rejected(self):
        for bad in (True,-1,1.5,None):
            with self.assertRaises(ValueError):self.gate.merge_nested_budget({'logical_files':bad,'logical_bytes':0,'directories':0})
    def test_all_independent_ceilings_enforced(self):
        for key,limit in (('logical_files','files'),('logical_bytes','total_bytes'),('directories','directories')):
            value={'logical_files':0,'logical_bytes':0,'directories':0};value[key]=BOUNDS[limit]+1
            with self.assertRaises(ValueError):self.gate.merge_nested_budget(value)
    def test_exact_remaining_budget_allows_boundary(self):
        store=RawStore(self.root/'nested',budget={'files':1,'total_bytes':2,'directories':0})
        store.retain_bytes(b'ab',label='synthetic')
        with self.assertRaises(RetentionError):store.retain_bytes(b'',label='over-file-ceiling')
        self.assertEqual(store.summary()['effective_limits'],{'files':1,'total_bytes':2,'directories':0})
    def test_remaining_budget_byte_ceiling_applies_before_blob_write(self):
        store=RawStore(self.root/'nested',budget={'files':2,'total_bytes':1,'directories':0})
        with self.assertRaises(RetentionError):store.retain_bytes(b'ab',label='synthetic')
        self.assertEqual(store.file_count,0);self.assertFalse(list((store.root/'blobs/sha256').iterdir()))
    def test_remaining_directory_budget_blocks_tree_capture(self):
        source=self.root/'source';source.mkdir()
        store=RawStore(self.root/'nested',budget={'files':1,'total_bytes':1,'directories':0})
        with self.assertRaises(RetentionError):store.retain_tree(source,label='synthetic')
        self.assertEqual(store.directory_count,0)
    def test_invalid_remaining_budget_rejects_before_directory(self):
        path=self.root/'bad'
        with self.assertRaises(RetentionError):RawStore(path,budget={'files':True,'total_bytes':1,'directories':0})
        self.assertFalse(path.exists())
    def test_raw_bytes_are_retained_exactly(self):
        raw=b'\x00\xff\r\n';record=self.gate.store.retain_bytes(raw,label='synthetic')
        self.assertEqual((self.gate.store.root/record['blob_path']).read_bytes(),raw)
    def test_evidence_index_includes_nested_index(self):
        root=self.root/'evidence';(root/'nested').mkdir(parents=True);(root/'nested/evidence-index.json').write_text('{}')
        self.assertIn('nested/evidence-index.json',evidence_inventory(root))
    def test_evidence_alias_rejected(self):
        root=self.root/'evidence';root.mkdir();(root/'linked').symlink_to(self.root/'capture')
        with self.assertRaises(ValueError):evidence_inventory(root)
    def fixture(self,status='CAPTURED_FOR_INDEPENDENT_REVIEW'):
        root=self.root/'evidence';root.mkdir()
        dump(root/'provenance/result.json',{'status':status,'writers_quiescent':True,'compiled_final_commit':False})
        dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}])
        dump(root/'evidence-index.json',evidence_inventory(root));return root
    def test_settled_failure_can_transport_without_success_claim(self):
        value=verify_transport(self.fixture('FAILED_TERMINAL_RETENTION_OR_IDENTITY'))
        self.assertEqual(value['status'],'TRANSPORT_INDEX_CHECK_ONLY');self.assertEqual(value['capture_status'],'FAILED_TERMINAL_RETENTION_OR_IDENTITY')
    def test_mutation_after_index_rejected(self):
        root=self.fixture();(root/'new').write_bytes(b'mutation')
        with self.assertRaises(ValueError):verify_transport(root)
    def test_unsettled_writer_rejected_even_if_index_matches(self):
        root=self.fixture();dump(root/'provenance/owned-command-groups.json',[{'quiescent':False}]);dump(root/'evidence-index.json',evidence_inventory(root))
        with self.assertRaises(ValueError):verify_transport(root)
    def test_tool_identity_ignores_checkpoint_label_not_bytes(self):
        base={'requested_path':'/tool','resolved_path':'/real','sha256':'1'*64,'mode':'0755','symlink_chain':[],'label':'before'}
        other={**base,'label':'terminal'};self.assertEqual(tool_identity(base),tool_identity(other));other['sha256']='2'*64;self.assertNotEqual(tool_identity(base),tool_identity(other))

    def test_swiftc_launcher_retained_at_all_three_tool_checkpoints(self):
        from unittest import mock
        gate=self.gate;gate.work=self.root;gate.base_env={'PATH':'/usr/bin:/bin'}
        gate.run=lambda name,args,**kwargs: '/usr/bin/'+args[-1]+'\n'
        gate.save=mock.Mock()
        def retain(path,**kwargs):return {'requested_path':str(path),'label':kwargs['label']}
        with mock.patch('capture_retention.shutil.which',side_effect=lambda name,**kwargs:'/usr/bin/'+name),mock.patch.object(gate.store,'retain_executable',side_effect=retain):
            for phase in ('before','after','terminal'):
                result=gate.capture_toolchain(phase)
                self.assertEqual(result['launcher-swiftc']['requested_path'],'/usr/bin/swiftc')
                self.assertEqual(result['swiftc']['requested_path'],'/usr/bin/swiftc')
                self.assertEqual(result['launcher-swiftc']['label'],phase+'/launchers/swiftc')
                self.assertNotIn('swift-autolink-extract',result)

if __name__=='__main__':unittest.main()
