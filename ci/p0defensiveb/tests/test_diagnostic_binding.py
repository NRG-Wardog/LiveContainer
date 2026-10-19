"""Exact diagnostic emitter closure, never genuine runtime evidence."""
import copy,json,sys,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import prior_phase_a as p
import phase_a_evidence_replay as e
import phase_a_host_replay as h

class DiagnosticBindingTests(unittest.TestCase):
    def test_exact_diagnostic_sources_and_tool_closure(self):
        gate,data,_,closure=p._load_trusted_adapter(HERE/'prior_adapter')
        self.assertEqual(len(closure),63)
        self.assertEqual(data['owners']['AnisetteKit']['commit'],'227dfd8c8456cd62e4ceff4971b17afb2003d7e8')
        self.assertEqual(data['owners']['SideSign']['commit'],'b28fb0b72937849d4428e9ae313209b606f859b4')
        self.assertEqual(e.tool_probe_names(gate),e.DIAGNOSTIC_TOOL_PROBES)
        self.assertNotIn('swift-autolink-extract',e.tool_probe_names(gate))
        self.assertEqual(tuple(gate.host_tests.DRIVERS),(*h.DRIVERS,'run_diagnostic_checks.py'))
        self.assertEqual(h.EXPECTED_COUNTS['test_vm_setup_host.py']['assertions'],717)
    def test_old_or_expanded_tool_tuples_reject(self):
        for probes in (e.DIAGNOSTIC_TOOL_PROBES[:-2],(*e.DIAGNOSTIC_TOOL_PROBES,'curl'),('swift','swift-autolink-extract','xcodebuild')):
            namespace={};exec('class Gate:\n def tools(self):\n  for tool in '+repr(probes)+': pass\n',namespace)
            with self.subTest(probes=probes),self.assertRaises(ValueError):e.tool_probe_names(type('Emitter',(),{'Gate':namespace['Gate']}))
    def test_all_genuine_binding_fields_are_unset(self):
        prior=p.make_draft_prior()
        for key,value in prior['expected'].items():
            if key not in ('repository','host_tree'):self.assertIsNone(value)
        self.assertIsNone(prior['upload_identity_sha256']);self.assertIsNone(prior['independent_review'])
        with mock.patch.object(p,'_json_bytes',side_effect=AssertionError('pending must not read')):
            with self.assertRaisesRegex(ValueError,'unresolved'):p.verify_original_capture(prior,None,None,None)
            with self.assertRaisesRegex(ValueError,'unresolved'):p.verify_prior_capture(prior,None,None,None,None)
    def test_historical_basis_input_adapter_and_tree_never_relabel(self):
        changes={'source_basis':'defensive-ab-phase-a-v1','approved_inputs_sha256':'ec9087985ff9cc182c6b637c3ba79557ca0a8c8fe466acf834364c8ba9fe5a78','frozen_adapter_sha256':'a'*64}
        for key,value in changes.items():
            prior=p.make_draft_prior();prior[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):p.validate_prior_inputs(prior)
        prior=p.make_draft_prior();prior['expected']['host_tree']='dd121b25303fcf1bdc14013d8df088c7ca605ab8'
        with self.assertRaises(ValueError):p.validate_prior_inputs(prior)
    def test_emitter_original_review_or_freeze_byte_mutation_reject(self):
        original=p._json_bytes
        for target in ('emitter-freeze.json','emitter-independent-review.json'):
            def read(root,name):
                raw=original(root,name);return raw+b'\n' if name==target else raw
            with mock.patch.object(p,'_json_bytes',side_effect=read),self.subTest(target=target),self.assertRaisesRegex(ValueError,'reviewed diagnostic emitter changed'):p._load_trusted_adapter(HERE/'prior_adapter')

    def test_known_failed_run_never_becomes_a_successful_prior(self):
        prior=p.make_draft_prior();prior['expected']['run_id']=39300623354
        for execution in (False,True):
            with self.subTest(execution=execution),self.assertRaisesRegex(ValueError,'known failed diagnostic capture'):
                p.validate_prior_inputs(prior,execution=execution)

if __name__=='__main__':unittest.main()
