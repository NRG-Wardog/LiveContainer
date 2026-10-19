"""Actual activation binding mutations; only pure schema validation may execute."""
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import execution_contract as e
from inventory import parse,sha
from prior_phase_a import REVIEWED_PRIOR_FILES
from activation_fixture import (HOST,copy_actual_host,no_execution,pending_host,
                                pending_workflow_bytes,validate_actual_outer)
from test_execution_contract import draft


class ActivationBindingTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.host=copy_actual_host(Path(temporary.name).resolve())
        self.raw=(self.host/e.INPUT_PATH).read_bytes();self.digest=sha(self.raw)
        self.workflow=self.host/e.WORKFLOW
        self.original_workflow=self.workflow.read_bytes()
        self.anchor=('      '+e.ANCHOR+': '+self.digest).encode()

    def validate(self,raw=None,approved=None):
        with no_execution():
            return e.validate_inputs(self.raw if raw is None else raw,self.host,
                                     self.digest if approved is None else approved,execution=True)

    def replace_anchor(self,new):
        self.assertEqual(self.original_workflow.count(self.anchor),1)
        self.workflow.write_bytes(self.original_workflow.replace(self.anchor,new,1))

    def test_actual_bound_input_and_exact_active_anchor_validate_without_execution(self):
        self.assertEqual(parse(self.raw)['status'],'BOUND_CAPTURE_PROPOSAL')
        self.assertEqual(self.original_workflow.count(self.anchor),1)
        self.assertEqual(self.validate(),parse(self.raw))
        actual,active=validate_actual_outer(self.host)
        self.assertTrue(active);self.assertEqual(actual,parse(self.raw))

    def test_pending_fixture_digest_never_grants_activation(self):
        import json
        with pending_host() as host:
            raw=json.dumps(draft(host),sort_keys=True).encode()
            self.assertIn((e.ANCHOR+': REVIEW_REQUIRED').encode(),pending_workflow_bytes())
            with no_execution(),self.assertRaisesRegex(ValueError,'remain pending'):
                e.validate_inputs(raw,host,sha(raw),execution=True)

    def test_wrong_actual_workflow_anchor_rejected(self):
        self.replace_anchor(('      '+e.ANCHOR+': '+'1'*64).encode())
        with self.assertRaises(ValueError):self.validate()

    def test_missing_actual_workflow_anchor_rejected(self):
        self.replace_anchor(b'      # required anchor removed')
        with self.assertRaises(ValueError):self.validate()

    def test_duplicate_actual_workflow_anchor_rejected(self):
        self.replace_anchor(self.anchor+b'\n'+self.anchor)
        with self.assertRaises(ValueError):self.validate()

    def test_pending_sentinel_cannot_replace_active_approval(self):
        self.replace_anchor(('      '+e.ANCHOR+': REVIEW_REQUIRED').encode())
        with self.assertRaisesRegex(ValueError,'activation approval'):self.validate()

    def test_wrong_or_missing_supplied_digest_rejected(self):
        for approved in ('1'*64,'REVIEW_REQUIRED',None):
            with self.subTest(approved=approved),no_execution(),self.assertRaises(ValueError):
                e.validate_inputs(self.raw,self.host,approved,execution=True)

    def test_altered_actual_input_bytes_rejected(self):
        changed=self.raw+b'\n'
        (self.host/e.INPUT_PATH).write_bytes(changed)
        with self.assertRaises(ValueError):self.validate(raw=changed)

    def test_omitted_retained_receipts_rejected(self):
        for name in (*e.RECEIPTS,*REVIEWED_PRIOR_FILES):
            path=self.host/e.ADAPTER/'reviewed'/name;original=path.read_bytes();path.unlink()
            try:
                with self.subTest(receipt=name),self.assertRaises(ValueError):self.validate()
            finally:path.write_bytes(original)

    def test_changed_retained_receipt_bytes_rejected(self):
        for name in (*e.RECEIPTS,*REVIEWED_PRIOR_FILES):
            path=self.host/e.ADAPTER/'reviewed'/name;original=path.read_bytes();path.write_bytes(original+b'\n')
            try:
                with self.subTest(receipt=name),self.assertRaises(ValueError):self.validate()
            finally:path.write_bytes(original)

    def test_wrong_actual_branch_bytes_rejected(self):
        before=('refs/heads/'+e.BRANCH).encode()
        self.assertIn(before,self.original_workflow)
        self.workflow.write_bytes(self.original_workflow.replace(before,b'refs/heads/unreviewed-branch'))
        with self.assertRaisesRegex(ValueError,'workflow bytes'):self.validate()

    def test_wrong_actual_workflow_input_path_rejected(self):
        before=e.INPUT_PATH.encode();self.assertIn(before,self.original_workflow)
        self.workflow.write_bytes(self.original_workflow.replace(before,b'ci/p0defensiveb/unreviewed-inputs.json'))
        with self.assertRaisesRegex(ValueError,'workflow bytes'):self.validate()


if __name__=='__main__':unittest.main()
