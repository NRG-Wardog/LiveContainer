"""Offline command-shape and fail-closed tests; no native tool is invoked."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_gate as gate
import native_build as build
from inventory import *
from lifecycle import command_environment
class DraftGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host=HERE.parents[1];cls.raw=(HERE/'inputs-phase-b.json').read_bytes();cls.data=parse(cls.raw)
    def test_bound_proposal_validates_but_exact_review_sentinel_blocks_execution(self):
        validate_inputs(self.raw,self.host)
        with self.assertRaisesRegex(ValueError,'execution blocked'):validate_inputs(self.raw,self.host,sha(self.raw),execution=True)
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);obj=gate.Gate(self.data,self.host,root/'work',root/'evidence',sha(self.raw),self.raw,root/'prior')
            with mock.patch.object(obj,'run',side_effect=AssertionError('native command forbidden')):
                with self.assertRaises(ValueError):obj.execute()
            self.assertFalse((root/'work').exists());self.assertFalse((root/'evidence').exists())
    def test_readiness_toggle_and_source_mutations_do_not_enable_execution(self):
        for change in (lambda d:d.update(status='READY'),lambda d:d.update(execution_review=True),lambda d:d.update(source_seal_sha256='0'*64),lambda d:d['graph'].update(kind='phase-b-graph-execution'),lambda d:d['prior_phase_a']['expected'].update(run_id=39210026679)):
            data=copy.deepcopy(self.data);change(data)
            with self.assertRaises((ValueError,KeyError,TypeError)):validate_inputs(json.dumps(data).encode(),self.host,execution=True)
    def test_exact_phase_b_guard_preserves_other_workflow_bytes(self):
        value=ordinary_build_guard(self.host);self.assertEqual(value['excluded_ref'],'refs/heads/validation/p0-login-trace-phase-b')
        self.assertEqual(value['before_sha256'],'794d75f941bb6e7ca430a7c0ca05d6899f05ec65786cd81142a459974c62acb4')
        text=(self.host/BUILD_WORKFLOW_PATH).read_text();self.assertEqual(text.count(BUILD_GUARD),1);self.assertNotIn('validation/p0-login-trace-phase-a',text)
    def test_unsigned_build_command_shapes_are_exact_and_frozen(self):
        roots={owner:Path('/synthetic')/owner for owner in ('SideStore','LiveContainer')};commands=build.app_commands(roots,Path('/fresh'))
        self.assertEqual([name for name,args in commands],['sidestore-resolve','sidestore-frozen-resolve','sidestore-build','livecontainer-build'])
        self.assertIn('-onlyUsePackageVersionsFromResolvedFile',commands[1][1])
        self.assertIn('-onlyUsePackageVersionsFromResolvedFile',commands[2][1]);self.assertIn('-disableAutomaticPackageResolution',commands[2][1])
        for name,args in commands[2:]:
            self.assertEqual(args[-len(build.SETTINGS):],build.SETTINGS)
            self.assertEqual(args[-1],'build');self.assertNotIn('archive',args);self.assertIn('CODE_SIGNING_ALLOWED=NO',args)
        self.assertNotEqual(commands[2][1][commands[2][1].index('-derivedDataPath')+1],commands[3][1][commands[3][1].index('-derivedDataPath')+1])
    def test_file_transport_is_only_for_finite_package_commands(self):
        for label in ('sidestore-resolve','sidestore-frozen-resolve','sidestore-build','livecontainer-build'):
            self.assertEqual(command_environment(label,['xcodebuild'],{})['GIT_ALLOW_PROTOCOL'],'https:file')
            self.assertEqual(command_environment(label,['git'],{})['GIT_ALLOW_PROTOCOL'],'https')
        self.assertEqual(command_environment('arbitrary',['xcodebuild'],{})['GIT_ALLOW_PROTOCOL'],'https')
    def test_decoded_swift_streams_are_separate_and_exact(self):
        verify_swift_version(TOOLCHAIN['swift_stdout'],TOOLCHAIN['swift_stderr'])
        for a,b in ((TOOLCHAIN['swift_stderr'],TOOLCHAIN['swift_stdout']),(TOOLCHAIN['swift_stdout'],''),(TOOLCHAIN['swift_stdout'].rstrip(),TOOLCHAIN['swift_stderr'])):
            with self.assertRaises(ValueError):verify_swift_version(a,b)
    def test_observed_app_lock_rejects_pin_and_origin_drift(self):
        commit='a'*40;before={'version':3,'originHash':'b'*64,'pins':[{'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':'c'*40}},{'identity':'other','state':{'revision':'d'*40}}]};after=copy.deepcopy(before);after['pins'][0]['state']={'revision':commit}
        check_lock(json.dumps(before).encode(),json.dumps(after).encode(),commit)
        for mutate in (lambda d:d['pins'][1]['state'].update(revision='e'*40),lambda d:d.pop('originHash'),lambda d:d['pins'][0]['state'].update(branch='main')):
            bad=copy.deepcopy(after);mutate(bad)
            with self.assertRaises(ValueError):check_lock(json.dumps(before).encode(),json.dumps(bad).encode(),commit)
    def test_product_inventory_detects_mutation_and_escape(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'product';root.mkdir();(root/'binary').write_bytes(b'synthetic');before=build.file_inventory(root);(root/'binary').write_bytes(b'changed');self.assertNotEqual(before,build.file_inventory(root));(root/'escape').symlink_to('/tmp')
            with self.assertRaises(ValueError):build.file_inventory(root)
    def test_failed_evidence_remains_failed_and_unsettled_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);dump(root/'provenance/result.json',{'writers_quiescent':True,'status':'FAILED_OR_INCOMPLETE'});dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}]);dump(root/'evidence-index.json',{str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()})
            self.assertEqual(gate.verify_transport(root)['capture_status'],'FAILED_OR_INCOMPLETE')
            dump(root/'provenance/result.json',{'writers_quiescent':False,'status':'FAILED_UNSETTLED_WRITERS'})
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_token_is_exclusive_to_fixed_retrieval_lane(self):
        env={'GH_TOKEN':'synthetic-secret','GITHUB_TOKEN':'second-secret'}
        for name in ('sidestore-build','idevice-build','arbitrary'):
            result=command_environment(name,['tool'],env);self.assertNotIn('GH_TOKEN',result);self.assertNotIn('GITHUB_TOKEN',result)
        result=command_environment('retrieve-prior',['tool'],env);self.assertEqual(result['GH_TOKEN'],'synthetic-secret');self.assertNotIn('GITHUB_TOKEN',result)
    def test_parent_scope_removes_tokens_from_direct_git_reads(self):
        import source_primitives as primitives
        with tempfile.TemporaryDirectory() as t,mock.patch.dict(os.environ,{'GH_TOKEN':'synthetic-secret','GITHUB_TOKEN':'other-secret'}):
            only=gate.detach_retrieval_environment()
            self.assertEqual(only['GH_TOKEN'],'synthetic-secret');self.assertNotIn('GITHUB_TOKEN',only)
            self.assertNotIn('GH_TOKEN',os.environ);self.assertNotIn('GITHUB_TOKEN',os.environ)
            with mock.patch.object(primitives.subprocess,'check_output',return_value=b'') as read:
                primitives.git(Path(t).resolve(),'rev-parse','HEAD')
            self.assertNotIn('GH_TOKEN',read.call_args.kwargs['env']);self.assertNotIn('GITHUB_TOKEN',read.call_args.kwargs['env'])
            only.clear()
    def test_workflow_remains_review_required_with_only_exact_branch(self):
        text=(self.host/WORKFLOW_PATH).read_text();self.assertIn('APPROVED_P0LOGINB_INPUTS_SHA256: REVIEW_REQUIRED',text);self.assertIn('      - validation/p0-login-trace-phase-b\n',text);self.assertIn('persist-credentials: false',text);self.assertNotIn('ci/p0cxx/',text)
if __name__=='__main__':unittest.main(verbosity=2)
