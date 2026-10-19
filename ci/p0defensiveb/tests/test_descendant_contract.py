"""Synthetic object seam tests only; no new source child or lock is produced."""
import copy,json,sys,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import descendant_contract as d


class DescendantContractTests(unittest.TestCase):
    def test_three_actual_app_lock_checkpoints_must_agree(self):
        with self.assertRaises(ValueError):d.sidestore_final_app_lock_child(None,'a'*40,'b'*40,'c'*40,b'a',b'b',b'a')
    def test_final_child_explicitly_not_directly_compiled(self):
        with mock.patch.object(d,'observed_lock_child',return_value={'compiled_final_commit':False}) as inner:
            value=d.sidestore_final_app_lock_child(None,'a'*40,'b'*40,'c'*40,b'raw',b'raw',b'raw')
        self.assertIs(value['compiled_final_commit'],False);self.assertEqual(value['tested_commit'],'a'*40)
        self.assertEqual(inner.call_args.args[-1],d.APP_LOCK)
    def test_sidesign_child_parent_is_published_manifest_only(self):
        with mock.patch.object(d,'observed_lock_child',return_value={'compiled_final_commit':False}) as inner:
            d.sidesign_child(None,'a'*40,'b'*40,b'raw',b'raw')
        self.assertEqual(inner.call_args.args[1],'b28fb0b72937849d4428e9ae313209b606f859b4')
        self.assertEqual(inner.call_args.args[-1],'Package.resolved')
    def test_direct_child_requires_exact_single_parent(self):
        with mock.patch.object(d,'git',return_value=('b'*40+' '+'a'*40+' '+'d'*40).encode()):
            with self.assertRaises(ValueError):d.direct(None,'a'*40,'b'*40,'c'*40)
    def test_direct_child_requires_exact_tree(self):
        with mock.patch.object(d,'git',return_value=('b'*40+' '+'a'*40).encode()),mock.patch.object(d,'snapshot',return_value={'tree':'d'*40}):
            with self.assertRaises(ValueError):d.direct(None,'a'*40,'b'*40,'c'*40)
    def test_pending_or_oversized_lock_rejected_before_objects(self):
        with mock.patch.object(d,'direct') as read:
            for raw in (None,b'',b'x'*(16*1024*1024+1)):
                with self.assertRaises(ValueError):d.observed_lock_child(None,None,None,None,raw,raw,'Package.resolved')
        read.assert_not_called()
    def test_store_capture_input_has_only_gitlink_delta(self):
        changes={'Dependencies/SideSign':{'before':{'mode':'160000','type':'commit','git_object':d.OLD_SIGN},'after':{'mode':'160000','type':'commit','git_object':'a'*40}}}
        with mock.patch.object(d,'direct',return_value={'changes':changes}):
            value=d.sidestore_capture_input(None,'b'*40,'c'*40,'a'*40)
        self.assertIs(value['app_lock_input_unchanged'],True);self.assertEqual(value['phase_b_tested_gitlink_commit'],'b'*40)
    def test_store_capture_input_rejects_extra_app_lock_delta(self):
        with mock.patch.object(d,'direct',return_value={'changes':{d.APP_LOCK:{}}}):
            with self.assertRaises(ValueError):d.sidestore_capture_input(None,'b'*40,'c'*40,'a'*40)


if __name__=='__main__':unittest.main()
