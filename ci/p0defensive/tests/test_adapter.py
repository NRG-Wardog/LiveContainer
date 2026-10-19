"""Portable/mutation checks only. No Swift execution or synthetic native admission."""
import copy, hashlib, json, os, re, shutil, stat, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_gate as gate
import capture_contract as contract
from inventory import *
from lifecycle import command_environment
from prepare_inputs import prepare

class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live_host=HERE.parents[1];cls.raw=(HERE/'inputs-phase-a.json').read_bytes();cls.data=parse(cls.raw)
        cls.fixture=tempfile.TemporaryDirectory();cls.host=Path(cls.fixture.name).resolve()/'host'
        shutil.copytree(HERE,cls.host/'ci/p0defensive')
        (cls.host/WORKFLOW_PATH).parent.mkdir(parents=True)
        template,_=workflow_template(cls.live_host,sha(cls.raw))
        (cls.host/WORKFLOW_PATH).write_bytes(template)
        shutil.copyfile(cls.live_host/BUILD_WORKFLOW_PATH,cls.host/BUILD_WORKFLOW_PATH)
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    def test_inputs_validate_only_for_local_review(self):
        data,blockers=validate_inputs(self.raw,self.host)
        self.assertEqual(data['basis'],BASIS)
        self.assertIn('capture host parent and ordinary build guard pending',blockers) if data['host'] is None else None
    def test_final_exact_package_tuples_and_capture_only_baseline_host(self):
        data,blockers=validate_inputs(self.raw,self.host)
        self.assertEqual(blockers,[name+' publication tuple pending' for name in OWNERS if data['owners'][name]['commit'] is None])
        self.assertEqual(data['owners']['AnisetteKit']['reviewed_tree'],'4d31646c46a7af3d911bb9d52eeffe9cbc26a3dd')
        self.assertEqual(data['owners']['SideSign']['base'],'a375e72d1ff39319c14d22ab98ddecd46c758783')
        self.assertEqual(data['owners']['SideSign']['reviewed_tree'],'7cf5311daf9e25cb356f9d63736422111afe740d')
        self.assertEqual(data['host']['base'],HOST_BASE)
        self.assertEqual(data['host']['tree'],HOST_TREE)
        runner=gate.Gate(data,self.host,Path('/local-only-unused-work'),Path('/local-only-unused-evidence'),None,self.raw)
        self.assertFalse(runner.state['app_typechecked'])
        self.assertEqual(runner.state['capture_host_role'],'historical-LiveContainer-capture-only-not-compiled')
    def test_ordinary_build_delta_is_one_exact_branch_exclusion(self):
        before=(HERE/'reviewed/capture-host-build.before.yml').read_bytes()
        after=(self.host/BUILD_WORKFLOW_PATH).read_bytes()
        self.assertEqual(before.count(b'  build:\n'),1)
        self.assertEqual(after,before.replace(b'  build:\n',('  build:\n'+BUILD_GUARD).encode(),1))
        self.assertEqual(sha(before),self.data['host']['ordinary_build_before_sha256'])
        self.assertEqual(sha(after),self.data['host']['ordinary_build_after_sha256'])
        self.assertEqual(after.count(BUILD_GUARD.encode()),1)
    def test_live_workflow_is_exact_dormant_or_reviewed_activated_form(self):
        data,blockers=validate_inputs(self.raw,self.live_host,sha(self.raw))
        self.assertEqual(blockers,[name+' publication tuple pending' for name in OWNERS if data['owners'][name]['commit'] is None])
        _,anchor=workflow_template(self.live_host,sha(self.raw))
        self.assertIn(anchor,('REVIEW_REQUIRED',sha(self.raw)))
    def test_matching_activated_fixture_validates_without_running_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Path(tmp).resolve()/'activated';shutil.copytree(self.host,host)
            path=host/WORKFLOW_PATH
            path.write_bytes(path.read_bytes().replace(b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED',('APPROVED_P0DEFENSIVE_INPUTS_SHA256: '+sha(self.raw)).encode()))
            if any(row['commit'] is None for row in self.data['owners'].values()):
                with self.assertRaisesRegex(ValueError,'publication tuple pending'):validate_inputs(self.raw,host,sha(self.raw),execute=True)
                return
            data,blockers=validate_inputs(self.raw,host,sha(self.raw),execute=True)
            self.assertEqual(blockers,[name+' publication tuple pending' for name in OWNERS if data['owners'][name]['commit'] is None])
            with self.assertRaises(ValueError):validate_inputs(self.raw,host,'0'*64,execute=True)
    def test_complete_portable_suite_accepts_activated_workflow_fixture(self):
        if os.environ.get('P0DEFENSIVE_ACTIVATION_SUITE_CHILD')=='1':
            self.assertEqual(workflow_template(self.live_host,sha(self.raw))[1],sha(self.raw))
            return
        with tempfile.TemporaryDirectory() as tmp:
            host=Path(tmp).resolve()/'activated';shutil.copytree(self.host,host)
            path=host/WORKFLOW_PATH
            path.write_bytes(path.read_bytes().replace(b'APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED',('APPROVED_P0DEFENSIVE_INPUTS_SHA256: '+sha(self.raw)).encode()))
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',P0DEFENSIVE_ACTIVATION_SUITE_CHILD='1')
            args=[sys.executable,*(['-O'] if sys.flags.optimize else []),'-B','-m','unittest','discover','-s',str(host/'ci/p0defensive/tests'),'-v']
            result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('\nOK\n',result.stderr)
            self.assertNotIn('skipped=',result.stderr)
    def test_no_hash_can_activate_review_required_workflow(self):
        for approved in (None,'REVIEW_REQUIRED','0'*64,sha(self.raw)):
            with self.assertRaises(ValueError):validate_inputs(self.raw,self.host,approved,execute=True)
    def test_owner_scope_identity_test_counts_toolchain_and_retention_mutations_reject(self):
        changes=[lambda d:d.update(schema=True),lambda d:d.update(phase='phase-b'),lambda d:d['owners'].update(SideStore={}),lambda d:d['owners']['AnisetteKit'].update(commit='1'*40),lambda d:d['owners']['AnisetteKit'].update(parents=[]),lambda d:d['test_source_audit']['AnisetteKit'].clear(),lambda d:d['command_counts'].update(selected_tests=0),lambda d:d['command_counts'].update(filtered_test_execution=5),lambda d:d['toolchain'].update(architecture='x86_64'),lambda d:d['retention_bounds'].update(file_bytes=999999999),lambda d:d['adapter_files'].clear(),lambda d:d['artifacts'][0].update(sha256='0'*64)]
        for mutation in changes:
            with self.subTest(mutation=mutation):
                bad=copy.deepcopy(self.data);mutation(bad)
                with self.assertRaises((ValueError,KeyError,TypeError)):validate_inputs(json.dumps(bad).encode(),self.host)
    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):parse(b'{"schema":1,"schema":1}')
    def test_workflow_hash_normalizes_only_exact_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Path(tmp);p=host/WORKFLOW_PATH;p.parent.mkdir(parents=True)
            original=(self.host/WORKFLOW_PATH).read_text();p.write_text(original)
            expected,_=workflow_template(host)
            p.write_text(original.replace('APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED','APPROVED_P0DEFENSIVE_INPUTS_SHA256: '+sha(self.raw)))
            self.assertEqual(workflow_template(host,sha(self.raw))[0],expected)
            with self.assertRaises(ValueError):workflow_template(host,'0'*64)
    def test_live_command_arrays_match_exact_proposal(self):
        roots={owner:Path('/exact/sources')/owner for owner in OWNERS};work=Path('/fresh/work')
        for lane in gate.LANES:
            c=gate.lane_commands(lane,roots,work)
            self.assertEqual(c['execute'][:3],contract.SANDBOX)
            self.assertEqual(c['execute'][-2:],['--filter',contract.exact_filter(lane)])
            self.assertEqual(c['discover'].count('--filter'),0)
            self.assertEqual(c['execute'].count('--filter'),1)
            self.assertNotIn(contract.UNSAFE,c['execute'][-1])
    def test_only_safe_command_labels_receive_local_mirror_protocol(self):
        for lane in gate.LANES:
            for suffix in ('-discover','-tests'):
                env=command_environment(lane+suffix,['/usr/bin/sandbox-exec'])
                self.assertEqual(env['GIT_ALLOW_PROTOCOL'],'https:file')
        self.assertEqual(command_environment('injected',['swift'])['GIT_ALLOW_PROTOCOL'],'https')
    def test_fixed_path_launchers_are_retained_alongside_xcode_leaf_tools(self):
        self.assertEqual(gate.LAUNCHER_PATHS,('/usr/bin/git','/usr/bin/xcrun','/usr/bin/sandbox-exec','/usr/bin/curl','/usr/bin/swift','/usr/bin/swiftc','/usr/bin/c++','/usr/bin/xcodebuild','/usr/bin/uname'))
        import inspect
        self.assertIn('for path in (*LAUNCHER_PATHS,sys.executable):',inspect.getsource(gate.Gate.tools))
        self.assertIn("['xcrun','--find',tool]",inspect.getsource(gate.Gate.tools))
    def test_tool_inventory_matches_native_macos_linker_pipeline(self):
        # Xcode 26.4.1 has no swift-autolink-extract utility; this is not a
        # required Darwin linker stage. Keep every actual selected tool bound.
        import ast, inspect, textwrap
        tree=ast.parse(textwrap.dedent(inspect.getsource(gate.Gate.tools)))
        loops=[node for node in ast.walk(tree) if isinstance(node,ast.For) and isinstance(node.target,ast.Name) and node.target.id=='tool']
        self.assertEqual(len(loops),1)
        self.assertEqual(ast.literal_eval(loops[0].iter),('swift','swiftc','swift-frontend','swift-symbolgraph-extract','clang','clang++','ld','ar','dsymutil','git','xcodebuild','nm','otool'))
        self.assertIn("self.store.retain_executable(path,label='tools/'+tool",inspect.getsource(gate.Gate.tools))
    def test_environment_excludes_tokens_proxies_and_loader_injection(self):
        env=command_environment('sidesign-build',['swift'],dict(PATH='/bin',HOME='/fresh',GITHUB_TOKEN='secret',AWS_SECRET_ACCESS_KEY='secret',HTTP_PROXY='bad',DYLD_INSERT_LIBRARIES='bad',SWIFTPM_CUSTOM_LIBRARIES='bad',GIT_CONFIG_COUNT='1'))
        self.assertNotIn('GITHUB_TOKEN',env);self.assertNotIn('AWS_SECRET_ACCESS_KEY',env);self.assertNotIn('HTTP_PROXY',env);self.assertNotIn('DYLD_INSERT_LIBRARIES',env);self.assertNotIn('SWIFTPM_CUSTOM_LIBRARIES',env)
        self.assertEqual(env['GIT_CONFIG_GLOBAL'],os.devnull)
    def test_unrelated_pin_schema_origin_and_ak_drift_reject(self):
        before={'version':3,'originHash':'a'*64,'pins':[{'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':'1'*40}},{'identity':'other','kind':'remoteSourceControl','location':'https://github.com/known/other.git','state':{'revision':'2'*40}}]}
        after=copy.deepcopy(before);after['pins'][0]['state']={'revision':'3'*40};after['originHash']='b'*64
        gate.check_lock(json.dumps(before).encode(),json.dumps(after).encode(),'3'*40)
        changes=[lambda d:d['pins'][1]['state'].update(revision='4'*40),lambda d:d['pins'].append(d['pins'][0]),lambda d:d['pins'].pop(),lambda d:d['pins'][0].update(location='file:///fake'),lambda d:d.update(version=2),lambda d:d.pop('originHash'),lambda d:d['pins'][0]['state'].update(branch='main')]
        for mutation in changes:
            bad=copy.deepcopy(after);mutation(bad)
            with self.assertRaises((ValueError,KeyError)):gate.check_lock(json.dumps(before).encode(),json.dumps(bad).encode(),'3'*40)
    def test_artifact_zip_exact_bytes_modes_symlinks_and_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=root/'Native.xcframework';bundle.mkdir();(bundle/'binary').write_bytes(b'raw actual synthetic bytes');(bundle/'binary').chmod(0o755);(bundle/'alias').symlink_to('binary')
            archive=root/'archive.zip'
            with zipfile.ZipFile(archive,'w') as z:
                info=zipfile.ZipInfo('Native.xcframework/binary');info.external_attr=(stat.S_IFREG|0o755)<<16;z.writestr(info,b'raw actual synthetic bytes')
                info=zipfile.ZipInfo('Native.xcframework/alias');info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,b'binary')
            self.assertEqual(gate.check_artifact_archive(archive,bundle,bundle.name)['files'],2)
            (bundle/'binary').write_bytes(b'drift')
            with self.assertRaises(ValueError):gate.check_artifact_archive(archive,bundle,bundle.name)
    def test_artifact_extra_member_and_path_traversal_reject(self):
        for name in ('../escape','/escape','Other.xcframework/file'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);bundle=root/'Native.xcframework';bundle.mkdir();archive=root/'archive.zip'
                with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'bad')
                with self.assertRaises(ValueError):gate.check_artifact_archive(archive,bundle,bundle.name)
    def test_transport_exact_index_rejects_modified_missing_extra_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dump(root/'provenance/result.json',{'writers_quiescent':True,'status':'SYNTHETIC_TRANSPORT_ONLY'})
            dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}]);dump(root/'provenance/reviewed-inputs.json',{})
            index={str(p.relative_to(root)):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()};dump(root/'evidence-index.json',index)
            self.assertEqual(gate.verify_transport(root)['capture_status'],'SYNTHETIC_TRANSPORT_ONLY')
            (root/'extra').write_bytes(b'extra')
            with self.assertRaises(ValueError):gate.verify_transport(root)
            (root/'extra').unlink();(root/'link').symlink_to(root/'provenance/result.json')
            with self.assertRaises(ValueError):gate.verify_transport(root)
            (root/'link').unlink();(root/'provenance/reviewed-inputs.json').write_text('drift')
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_transport_indexes_nested_index_names_and_rejects_special_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();dump(root/'provenance/result.json',{'writers_quiescent':True,'status':'SYNTHETIC_TRANSPORT_ONLY'})
            dump(root/'provenance/owned-command-groups.json',[{'quiescent':True,'pipesJoined':True,'leaderReaped':True,'errors':[]}]);dump(root/'provenance/reviewed-inputs.json',{})
            dump(root/'evidence-index.json',gate.evidence_index(root))
            self.assertEqual(gate.verify_transport(root)['capture_status'],'SYNTHETIC_TRANSPORT_ONLY')
            dump(root/'provenance/evidence-index.json',{'unexpected':True})
            self.assertIn('provenance/evidence-index.json',gate.evidence_index(root))
            with self.assertRaises(ValueError):gate.verify_transport(root)
            (root/'provenance/evidence-index.json').unlink();os.mkfifo(root/'pipe')
            with self.assertRaisesRegex(ValueError,'special'):gate.evidence_index(root)
            with self.assertRaisesRegex(ValueError,'special'):gate.verify_transport(root)
    def test_workflow_dedicated_readonly_guarded_upload(self):
        text=(self.host/WORKFLOW_PATH).read_text()
        for value in ('contents: read','actions: read','persist-credentials: false',"github.ref == 'refs/heads/"+BRANCH+"'",'APPROVED_P0DEFENSIVE_INPUTS_SHA256: REVIEW_REQUIRED','steps.transport.outputs.settled','if-no-files-found: error'):
            self.assertIn(value,text)
        self.assertNotIn('secrets.',text);self.assertNotIn('pull_request',text)
    def test_genuine_historical_xctest_format_is_not_new_defensive_evidence(self):
        root=HERE/'tests/fixtures/historical-login-only'
        stdout=(root/'interleaved-xctest.stdout.txt').read_bytes();stderr=(root/'interleaved-xctest.stderr.txt').read_bytes()
        self.assertEqual(gate.verify_native_logs(stdout,stderr,'anisette-trace-regression')['executed'],6)
        for injected in (b"\nTest Suite 'Unknown' started.",b"\nTest Suite 'Selected tests' skipped."):
            with self.assertRaises(ValueError):gate.verify_native_logs(stdout+injected,stderr,'anisette-trace-regression')
    def test_genuine_xctest_summary_count_format_and_suite_binding(self):
        root=HERE/'tests/fixtures/historical-login-only'
        stdout=(root/'interleaved-xctest.stdout.txt').read_bytes();stderr=(root/'interleaved-xctest.stderr.txt').read_bytes()
        for extra in (b'Executed malformed tests, with unknown failures',b'Executed 6 tests, with 0 failures (0 unexpected)'):
            with self.assertRaises(ValueError):gate.verify_native_logs(stdout+b'\n'+extra,stderr,'anisette-trace-regression')
        first_summary=re.search(rb'(?m)^.*Executed[^\r\n]*\n',stdout).group()
        before_suites=first_summary+stdout.replace(first_summary,b'',1)
        with self.assertRaises(ValueError):gate.verify_native_logs(before_suites,stderr,'anisette-trace-regression')
        first_case=re.search(rb'(?m)^Test Case[^\r\n]* started\.\n',stdout).group()
        before_suites=first_case+stdout.replace(first_case,b'',1)
        with self.assertRaises(ValueError):gate.verify_native_logs(before_suites,stderr,'anisette-trace-regression')
        suite_end=b"Test Suite 'LoginDiagnosticTraceTests' passed"
        shifted=stdout.replace(first_summary,b'',1).replace(suite_end,first_summary+suite_end,1)
        with self.assertRaises(ValueError):gate.verify_native_logs(shifted,stderr,'anisette-trace-regression')
    def test_successful_log_privacy_canaries_reject(self):
        for canary in (b'account@example.invalid',b'TOKEN-CANARY',b'PASSWORD-CANARY',b'BLOB-CANARY',b'SECRET',b'ORIGINAL'):
            with self.assertRaisesRegex(ValueError,'sensitive fixture'):gate.verify_native_logs(canary,b'','anisette-trace-regression')
    def test_source_primitives_and_settlement_algorithm_unchanged(self):
        self.assertEqual((HERE/'source_primitives.py').read_bytes(),(HERE/'reviewed/prior-source_primitives.py').read_bytes())
        old=(HERE/'reviewed/prior-lifecycle.py').read_text();new=(HERE/'lifecycle.py').read_text()
        self.assertEqual(old[old.index('def finish_owned_child'):old.index('class CommandRunner')],new[new.index('def finish_owned_child'):new.index('class CommandRunner')])
    def test_host_worktree_rejects_changed_and_ignored_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            def gitrun(*args):
                return subprocess.check_output(['git','-C',str(root),'-c','core.hooksPath='+os.devnull,'-c','user.name=Local fixture','-c','user.email=fixture@example.invalid',*args],stderr=subprocess.DEVNULL)
            gitrun('init','-q');(root/'source.swift').write_bytes(b'// local source fixture');(root/'.gitignore').write_text('ignored.swift\n')
            gitrun('add','.');gitrun('commit','-qm','local fixture');commit=gitrun('rev-parse','HEAD').decode().strip()
            self.assertEqual(gate.verify_host_worktree(root,commit)['tracked_entries'],2)
            (root/'ignored.swift').write_bytes(b'// hidden compiler input')
            with self.assertRaisesRegex(ValueError,'ignored'):gate.verify_host_worktree(root,commit)
            (root/'ignored.swift').unlink();(root/'source.swift').write_bytes(b'// modified')
            with self.assertRaisesRegex(ValueError,'bytes changed'):gate.verify_host_worktree(root,commit)
    def test_missing_actual_file_or_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'file').write_bytes(b'x');(root/'link').symlink_to(root/'file')
            for path in ('missing','link','../file','/file','.git/config'):
                with self.assertRaises(ValueError):ordinary(root,path)

if __name__=='__main__':unittest.main(verbosity=2)
