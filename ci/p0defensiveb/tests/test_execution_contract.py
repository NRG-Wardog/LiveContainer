"""Portable admission and complete pending machinery tests; no native execution."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import execution_contract as e,graph_contract as g,native_gate as n,lifecycle
from prior_phase_a import make_draft_prior
from inventory import TOOLCHAIN,sha
from retention import BOUNDS
sys.path.insert(0,str(HERE/'tests'))
from activation_fixture import make_pending_host


def draft(host):
    return {'schema_version':2,'basis':g.BASIS,'phase':'phase-b','status':'PENDING_GENUINE_CAPTURE_BINDINGS','execution_review':None,
        'graph':g.execution_draft_graph(),'prior_phase_a':make_draft_prior(),'descendants':e.descendants_draft(),
        'toolchain':TOOLCHAIN,'retention_bounds':BOUNDS,'adapter_files':e.files(host),'workflow':e.workflow(host)[0],
        'claims':e.CLAIMS,'compiled_final_commit':False}


class ExecutionContractTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.host=make_pending_host(Path(temporary.name).resolve());self.data=draft(self.host)
    def raw(self,data=None):return json.dumps(self.data if data is None else data,sort_keys=True).encode()
    def test_complete_pending_schema_validates(self):self.assertEqual(e.validate_inputs(self.raw(),self.host),self.data)
    def test_pending_execution_rejects_before_any_side_effect(self):
        gate=n.Gate(self.data,self.host,Path('/nonexistent-work'),Path('/nonexistent-evidence'),'REVIEW_REQUIRED',self.raw())
        with mock.patch.object(Path,'mkdir') as mkdir,mock.patch('subprocess.Popen') as popen,mock.patch.object(n,'detach_retrieval_environment') as token:
            with self.assertRaisesRegex(ValueError,'remain pending'):gate.execute()
        mkdir.assert_not_called();popen.assert_not_called();token.assert_not_called()
    def test_json_cannot_grant_execution_approval(self):
        self.data['execution_review']={'approved':True}
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_bound_status_cannot_invent_unknown_tuple(self):
        self.data['status']='BOUND_CAPTURE_PROPOSAL'
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_adapter_mutation_rejected(self):
        self.data['adapter_files']['ci/p0defensiveb/native_gate.py']='1'*64
        with self.assertRaisesRegex(ValueError,'adapter bytes'):e.validate_inputs(self.raw(),self.host)
    def test_pending_descendant_invention_rejected(self):
        self.data['descendants']['SideSign']['commit']='1'*40
        with self.assertRaisesRegex(ValueError,'pending input cannot fabricate'):e.validate_inputs(self.raw(),self.host)
    def test_pending_lock_invention_rejected(self):
        self.data['graph']['lock_sha256']='1'*64
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_false_compiled_final_commit_is_mandatory(self):
        self.data['compiled_final_commit']=True
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_boolean_schema_version_is_not_integer(self):
        self.data['schema_version']=True
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_unknown_input_field_rejected(self):
        self.data['approve']=True
        with self.assertRaises(ValueError):e.validate_inputs(self.raw(),self.host)
    def test_missing_or_extra_owner_rejected(self):
        for kind in ('missing','extra'):
            value=g.execution_draft_graph()
            if kind=='missing':value['owners'].pop('jktcp')
            else:value['owners']['other']=value['owners']['jktcp']
            with self.assertRaises(ValueError):g.validate_graph(value)
    def test_child_origin_drift_rejected(self):
        self.data['graph']['children']['LiveContainer/litehook']['repository']='https://invalid.example/other'
        with self.assertRaises(ValueError):g.validate_graph(self.data['graph'])
    def test_exact_known_source_tuples_and_no_override(self):
        value=g.execution_draft_graph();self.assertEqual(len(value['owners']),7);self.assertEqual(len(value['children']),5)
        self.assertEqual(value['owners']['LiveContainer']['commit'],g.KNOWN['LiveContainer'][0]);self.assertNotIn('override',json.dumps(value))
    def test_global_environment_does_not_reach_build(self):
        env=lifecycle.command_environment('sidestore-build',['xcodebuild'],{'GH_TOKEN':'synthetic','GITHUB_TOKEN':'synthetic','AWS_SECRET_ACCESS_KEY':'synthetic','DYLD_INSERT_LIBRARIES':'x','PATH':'/usr/bin','HOME':'/owned','DEVELOPER_DIR':TOOLCHAIN['developer_dir']})
        self.assertFalse(set(env)&{'GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','DYLD_INSERT_LIBRARIES'});self.assertEqual(env['GIT_ALLOW_PROTOCOL'],'https:file')
    def test_only_retrieval_gets_ephemeral_token(self):
        value={'GH_TOKEN':'synthetic','PATH':'/usr/bin','GITHUB_RUN_ID':'7'}
        self.assertEqual(lifecycle.command_environment('retrieve-prior',['python3'],value)['GH_TOKEN'],'synthetic')
        self.assertNotIn('GH_TOKEN',lifecycle.FIXED_ENV)
        self.assertNotIn('GH_TOKEN',lifecycle.command_environment('clone-test',['git'],value))
    def test_retrieval_context_is_logged_without_credentials(self):
        env=n.isolated_environment(Path('/owned'))|{key:'actual' for key in ('GITHUB_REPOSITORY','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REF')}|{'GH_TOKEN':'synthetic'}
        actual=lifecycle.command_environment('retrieve-prior',['python3'],env)
        logged={k:actual[k] for k in lifecycle.FIXED_ENV if k in actual}
        self.assertNotIn('GH_TOKEN',logged);self.assertEqual(logged['GITHUB_RUN_ID'],'actual');self.assertEqual(logged['HOME'],'/owned/home')
    def test_pending_digest_never_activates_workflow(self):
        raw=self.raw()
        with self.assertRaises(ValueError):e.validate_inputs(raw,self.host,sha(raw),execution=True)
    def test_unsupported_macos_autolink_probe_is_absent(self):
        import inspect
        self.assertNotIn('swift-autolink-extract',inspect.getsource(n.CaptureRetentionMixin.capture_toolchain))
    def test_complete_gate_contains_all_proven_product_stages(self):
        self.assertTrue(issubclass(n.Gate,n.NativeBuildMixin));self.assertTrue(issubclass(n.Gate,n.CaptureRetentionMixin))
        for name in ('acquire','run_consumers','verify_resources','retain_prior_originals','resolved_app_graph','capture_cargo_metadata'):
            self.assertTrue(callable(getattr(n.Gate,name)))

if __name__=='__main__':unittest.main()
