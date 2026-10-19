"""Portable preparation checks; never compile an app or contact a provider."""
import copy, hashlib, importlib.util, json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import capture_contract as c
import graph_contract as g
import native_build as n
import product_plan as p
from inventory import parse, check_lock
sys.path.insert(0,str(HERE/'tests'))
from activation_fixture import pending_workflow_bytes, pending_host, validate_actual_outer


class PreparationTests(unittest.TestCase):
    def test_future_run_artifact_ids_are_unresolved(self):
        value=c.PENDING['phase_a']
        for name in ('run_id','run_attempt','host_commit','host_tree','artifact_id','artifact_sha256','artifact_size','evidence_index_sha256'):
            self.assertIsNone(value[name])
    def test_future_lock_and_gitlink_objects_are_unresolved(self):
        for owner in ('SideSign','SideStore'):
            self.assertIsNone(c.PENDING[owner]['commit']);self.assertIsNone(c.PENDING[owner]['tree'])
        self.assertIsNone(c.PENDING['SideSign']['lock_sha256']);self.assertIsNone(c.PENDING['SideStore']['sidesign_gitlink'])
    def test_exact_manifest_and_store_bases(self):
        self.assertEqual(c.PENDING['SideSign']['parent'],'b28fb0b72937849d4428e9ae313209b606f859b4')
        self.assertEqual(c.PENDING['SideStore']['parent'],'d507f9e417f12c262b4d7e717c84d4a244c8e625')
    def test_exact_ak_and_lc_product_source(self):
        graph=g.draft_graph()['owners']
        self.assertEqual(graph['AnisetteKit']['commit'],'227dfd8c8456cd62e4ceff4971b17afb2003d7e8')
        self.assertEqual(graph['LiveContainer']['commit'],'545438e1f0a89fdef375f73273c5c9fc2735cbce')
    def test_seven_owners_and_five_children(self):
        graph=g.draft_graph();self.assertEqual(len(graph['owners']),7);self.assertEqual(len(graph['children']),5)
    def test_prior_review_never_inferred_from_legacy_receipts(self):
        self.assertIsNone(c.PENDING['phase_a']['independent_review_sha256'])
        self.assertIsNone(c.PENDING['source_specific_prior_replay']['adapter_files'])
    def test_execution_refused_for_empty_or_plausible_inputs(self):
        for data in ({},{'status':'BOUND_CAPTURE_PROPOSAL'},{'reviewed':True,'artifact_id':1}):
            with self.assertRaisesRegex(ValueError,'genuine independently reviewed'):c.execute_barrier(data)
    def test_barrier_has_no_subprocess_or_filesystem_side_effects(self):
        with mock.patch('subprocess.Popen') as run,mock.patch.object(Path,'mkdir') as create:
            with self.assertRaises(ValueError):c.execute_barrier(c.PENDING)
        run.assert_not_called();create.assert_not_called()
    def test_pending_workflow_has_sentinel(self):
        raw=pending_workflow_bytes().decode()
        self.assertIn(c.ANCHOR+': REVIEW_REQUIRED',raw);self.assertIn(c.INPUTS,raw)
        # Verify the real outer input/workflow binding independently of this fixture.
        actual,active=validate_actual_outer(HERE.parents[1])
        self.assertIn(actual['status'],('PENDING_GENUINE_CAPTURE_BINDINGS','BOUND_CAPTURE_PROPOSAL'))
    def test_readonly_workflow_and_isolated_ref(self):
        raw=(HERE.parents[1]/c.WORKFLOW).read_text()
        self.assertIn('contents: read',raw);self.assertIn('actions: read',raw)
        self.assertIn('refs/heads/'+c.BRANCH,raw);self.assertIn('persist-credentials: false',raw)
    def test_ordinary_build_guard_only(self):
        with pending_host() as host:proof=c.workflow_contract(host)
        self.assertEqual(proof['ordinary_build_before_sha256'],'794d75f941bb6e7ca430a7c0ca05d6899f05ec65786cd81142a459974c62acb4')
        validate_actual_outer(HERE.parents[1])
    def test_all_preparation_claims_remain_false(self):
        self.assertTrue(c.CLAIMS);self.assertTrue(all(value is False for value in c.CLAIMS.values()))
    def test_two_full_unsigned_device_builds(self):
        commands=p.contract()['commands'];builds=[row for row in commands if row['label'].endswith('-build')]
        self.assertEqual(len(builds),2)
        for row in builds:
            self.assertEqual(row['argv'][0],'xcodebuild');self.assertEqual(row['argv'][-1],'build')
            for value in ('iphoneos','Release','generic/platform=iOS','CODE_SIGNING_ALLOWED=NO','CODE_SIGNING_REQUIRED=NO','CODE_SIGN_IDENTITY=','DEVELOPMENT_TEAM='):
                self.assertIn(value,row['argv'])
    def test_no_distribution_archive_or_signing_command(self):
        for row in p.contract()['commands']:
            self.assertFalse({'archive','-exportArchive','codesign','--sign'} & set(row['argv']))
    def test_exact_resolve_frozen_repeat_then_build(self):
        commands=[r for r in p.contract()['commands'] if r['label'].startswith('sidestore-')]
        self.assertEqual([r['label'] for r in commands],['sidestore-resolve','sidestore-frozen-resolve','sidestore-build'])
        self.assertIn('-onlyUsePackageVersionsFromResolvedFile',commands[1]['argv'])
        self.assertIn('-disableAutomaticPackageResolution',commands[2]['argv'])
    def test_independent_derived_directories(self):
        commands=p.contract()['commands'];builds={r['label']:r for r in commands if r['label'].endswith('-build')}
        values=[]
        for row in builds.values():values.append(row['argv'][row['argv'].index('-derivedDataPath')+1])
        self.assertEqual(len(set(values)),2)
    def test_consumer_sandbox_and_probe(self):
        commands=p.contract()['commands'];self.assertEqual(commands[0]['label'],'consumer-network-denial-probe')
        self.assertEqual(commands[1]['label'],'consumer-exact38')
        for row in commands[:2]:self.assertEqual(row['argv'][:3],['/usr/bin/sandbox-exec','-p',p.SANDBOX])
    def test_consumer_observer_and_temporary_are_required_in_plan(self):
        argv=p.contract()['commands'][1]['argv']
        self.assertIn('--observer-dir',argv);self.assertIn('--temporary',argv)
    def test_consumer_count_and_no_skip_contract(self):
        plan=p.contract();self.assertEqual(plan['consumer_tests'],38);self.assertEqual(plan['consumer_skips_permitted'],0)
    def test_retention_raw_graph_and_terminal_locks(self):
        self.assertIn('raw-stdout-stderr',p.RETENTION['consumer_nested_each_command'])
        self.assertIn('SideSign-lock',p.RETENTION['terminal']);self.assertIn('SideStore-lock',p.RETENTION['terminal'])
        self.assertIn('compiler-generated-derived-data-inputs',p.RETENTION['before_after_app_build'])
    def test_no_reserve_source_override(self):
        self.assertNotIn('reserve',json.dumps(g.draft_graph()).lower())
        argv=p.contract()['commands'][1]['argv'];self.assertNotIn('--source-override',argv)
    def test_complete_execution_integration_pending_binding(self):
        self.assertEqual(p.contract()['missing_execution_integration'],[])
        self.assertEqual(len(p.contract()['pending_authentic_bindings']),4)
    def test_zero_or_short_git_sha_rejected(self):
        from inventory import full_sha
        for value in ('0'*40,'123','x'*40,None):
            with self.assertRaises(ValueError):full_sha(value)
    def test_duplicate_input_keys_rejected(self):
        with self.assertRaises(ValueError):parse(b'{"artifact_id":1,"artifact_id":2}')
    def test_non_ak_package_pin_drift_rejected(self):
        base={'version':3,'originHash':'a'*64,'pins':[{'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':g.OLD_AK}},{'identity':'other','state':{'revision':'b'*40}}]}
        new=copy.deepcopy(base);new['pins'][0]['state']['revision']=g.KNOWN['AnisetteKit'][0]
        check_lock(json.dumps(base).encode(),json.dumps(new).encode(),g.KNOWN['AnisetteKit'][0])
        new['pins'][1]['state']['revision']='c'*40
        with self.assertRaises(ValueError):check_lock(json.dumps(base).encode(),json.dumps(new).encode(),g.KNOWN['AnisetteKit'][0])


if __name__=='__main__':unittest.main()
