"""Offline adversarial checks. Synthetic reports are parser fixtures, never native evidence."""
import copy, hashlib, json, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import native_gate as gate
from inventory import *
from lifecycle import finish_owned_child, CommandRunner

class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host=HERE.parents[1];cls.raw=(HERE/'inputs-phase-a.json').read_bytes();cls.data=parse(cls.raw)
    def validate(self,data):
        raw=json.dumps(data).encode();return validate_inputs(raw,sha(raw),self.host)
    def test_exact_inputs_pass_without_execution(self):
        self.assertEqual(validate_inputs(self.raw,sha(self.raw),self.host)['phase'],'phase-a')
    def test_seal_owner_scope_and_phase_mutations_reject(self):
        mutations=[lambda d:d.update(phase='phase-b'),lambda d:d.update(source_seal_sha256='0'*64),lambda d:d['owners']['SideSign'].update(commit='1'*40),lambda d:d['owners']['SideStore']['changes'].update({'Unexpected.swift':{}}),lambda d:d['python_suites'][0].update(path='Tests/online.py'),lambda d:d.update(test_source_audit={}),lambda d:d['adapter_files'].pop(next(iter(d['adapter_files'])))]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                d=copy.deepcopy(self.data);mutation(d)
                with self.assertRaises((ValueError,KeyError,TypeError)):self.validate(d)
    def test_unrelated_pin_and_fake_ak_resolution_reject(self):
        before={'version':3,'originHash':'a'*64,'pins':[{'identity':'anisettekit','kind':'remoteSourceControl','location':'https://github.com/NRG-Wardog/AnisetteKit.git','state':{'revision':'1'*40}},{'identity':'other','state':{'revision':'2'*40}}]}
        after=copy.deepcopy(before);after['pins'][0]['state']={'revision':'3'*40};after['originHash']='b'*64
        gate.check_lock(json.dumps(before).encode(),json.dumps(after).encode(),'3'*40)
        for mutate in (lambda d:d['pins'][1]['state'].update(revision='4'*40),lambda d:d['pins'].append({'identity':'new'}),lambda d:d['pins'][0].update(location='file:///tmp/fake'),lambda d:d.pop('originHash')):
            d=copy.deepcopy(after);mutate(d)
            with self.assertRaises(ValueError):gate.check_lock(json.dumps(before).encode(),json.dumps(d).encode(),'3'*40)
    def test_swift_version_requires_exact_independent_decoded_streams(self):
        stdout='Apple Swift version 6.3.1 (swiftlang-6.3.1.1.2 clang-2100.0.123.102)\nTarget: arm64-apple-macosx26.0\n'
        stderr='swift-driver version: 1.148.6 '
        gate.verify_swift_version(stdout,stderr)
        for out,err in ((stderr,stdout),('',stderr),(stdout,''),(stdout+'extra',stderr),(stdout,stderr+'extra'),(stdout.rstrip(),stderr),(stdout,stderr+'\n'),(stderr+stdout,''),(stdout+stderr,''),(stdout.replace('6.3.1','6.3.2'),stderr),(stdout,stderr.replace('1.148.6','1.148.7'))):
            with self.assertRaises(ValueError):gate.verify_swift_version(out,err)
    def test_discovery_is_exact_finite_and_rejects_noise(self):
        gate.verify_discovery('\n'.join(gate.AK_IDS),gate.AK_IDS)
        for bad in ('','\n'.join(gate.AK_IDS[:-1]),'\n'.join(gate.AK_IDS+(gate.AK_IDS[0],)),'\n'.join(gate.AK_IDS)+'\nother/unicorn',' '+gate.AK_IDS[0]+'\n'+'\n'.join(gate.AK_IDS[1:])):
            with self.assertRaises(ValueError):gate.verify_discovery(bad,gate.AK_IDS)
    def xctest_output(self):
        lines=['[LOGIN_TRACE] stage=authSession outcome=failed reason=rejected']
        for method in gate.AK_METHODS:
            for event in ('started','passed'):lines.append(f"Test Case '-[AnisetteKitTests.LoginDiagnosticTraceTests {method}]' {event} (0.001 seconds).")
        lines.extend(['Executed 6 tests, with 0 failures (0 unexpected) in 0.1 seconds']*2)
        return '\n'.join(lines)
    def test_xctest_terminal_output_allows_finite_failed_trace(self):
        self.assertEqual(gate.verify_swift_tests(self.xctest_output(),'AnisetteKit')['executed'],6)
    def test_xctest_canary_extra_missing_skip_and_swift_testing_reject(self):
        good=self.xctest_output()
        variants=[good+'\n'+canary for canary in ('account@example.invalid','TOKEN-CANARY','PASSWORD-CANARY','BLOB-CANARY','SECRET','ORIGINAL')]+[good+'\nTest run with 0 tests passed after 0.1 seconds',good.replace(" passed (0.001 seconds)."," skipped (0.001 seconds).",1),good.replace('Executed 6 tests','Executed 5 tests'),good+"\nTest Case 'unknown' started",good+'\nunicornAnisetteProvisioningAndHeaders']
        for text in variants:
            with self.assertRaises(ValueError):gate.verify_swift_tests(text,'AnisetteKit')
    def recorded_xctest_output(self):
        root=HERE/'tests/fixtures';manifest=parse((root/'interleaved-xctest.provenance.json').read_bytes())
        self.assertEqual(manifest['source_archive_sha256'],'927b5b8beaaa9511331c80af008532fba66a9a615fa02750a971d25a4d9ce30f')
        values=[]
        for name in ('interleaved-xctest.stdout.txt','interleaved-xctest.stderr.txt'):
            raw=(root/name).read_bytes();row=manifest['members'][name]
            self.assertEqual(sha(raw),row['sha256']);self.assertEqual(len(raw),row['bytes']);values.append(raw.decode())
        return ''.join(values)
    def test_interleaved_recorded_xctest_events_are_hash_bound_and_accepted(self):
        text=self.recorded_xctest_output()
        self.assertEqual(text.count('Test Case '),12)
        self.assertEqual(len(__import__('re').findall(r'^Test Case ',text,__import__('re').M)),11)
        self.assertIn('outcome=stTest Case ',text)
        self.assertEqual(gate.verify_swift_tests(text,'AnisetteKit')['test_ids'],sorted(gate.AK_IDS))
    def test_interleaved_unknown_malformed_failure_duplicate_missing_events_reject(self):
        good=self.recorded_xctest_output();identity='-[AnisetteKitTests.LoginDiagnosticTraceTests '+gate.AK_METHODS[0]+']'
        started="Test Case '"+identity+"' started."
        passed=__import__('re').search(r"Test Case '[^']+' passed \([^\n]+",good).group(0)
        for bad in (good+"Test Case 'unknown' started.",good+"Test Case 'broken event' finished.",
                    good+'Test Case malformed',good+started,good+passed,good.replace(started,'',1),
                    good.replace(passed,'',1),good+"Test Case 'unknown' failed.",
                    good+"Test Case 'unknown' skipped.",good+"Test Case 'unknown' cancelled.",
                    good+'unicornAnisetteProvisioningAndHeaders'):
            with self.assertRaises(ValueError):gate.verify_swift_tests(bad,'AnisetteKit')
    def test_swift_testing_exact_suite_cases_and_summary(self):
        lines=['Suite "SideSign Core Tests" started']
        for name in gate.SS_METHODS:lines.extend([f'Test {name}() started',f'Test {name}() passed after 0.1 seconds'])
        lines+=['Suite "SideSign Core Tests" passed after 0.2 seconds','Test run with 5 tests in 1 suite passed after 0.2 seconds']
        good='\n'.join(lines);self.assertEqual(gate.verify_swift_tests(good,'SideSign')['executed'],5)
        for bad in (good.replace('5 tests','0 tests'),good+'\nTest unknown() passed after 0.1 seconds',good.replace('SideSign Core Tests','Other tests'),good+'\nTest wrong() cancelled',good+'\nTest \"unrecognized display name\" started'):
            with self.assertRaises(ValueError):gate.verify_swift_tests(bad,'SideSign')
    def test_owned_process_settles_without_post_reap_signals(self):
        child=subprocess.Popen([sys.executable,'-c','print("fixture")'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        child.communicate(timeout=3)
        result=finish_owned_child(child);state=result['ownedProcessGroup']
        self.assertTrue(state['quiescent']);self.assertTrue(state['reapedBeforeSignals']);self.assertEqual(state['signals'],[])
    def test_owned_running_process_is_terminated_before_reap(self):
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        result=finish_owned_child(child);state=result['ownedProcessGroup']
        self.assertTrue(state['identityRetainedForSignals']);self.assertTrue(state['quiescent']);self.assertTrue(state['signals'])
    def test_transport_rejects_missing_index_and_unsettled_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);dump(root/'provenance/result.json',{'writers_quiescent':False})
            with self.assertRaises(ValueError):gate.verify_transport(root)
    def test_sentinel_or_wrong_approval_rejects(self):
        for approval in ('REVIEW_REQUIRED','0'*64):
            with self.assertRaises(ValueError):validate_inputs(self.raw,approval,self.host)
    def test_workflow_template_only_normalizes_exact_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            host=Path(directory);path=host/WORKFLOW_PATH;path.parent.mkdir(parents=True)
            original=ordinary(self.host,WORKFLOW_PATH).read_text()
            path.write_text(original.replace('APPROVED_P0LOGIN_INPUTS_SHA256: REVIEW_REQUIRED','APPROVED_P0LOGIN_INPUTS_SHA256: '+sha(self.raw)))
            self.assertEqual(workflow_template(host,sha(self.raw)),workflow_template(self.host,sha(self.raw)))
            path.write_text(path.read_text().replace(sha(self.raw),'0'*64))
            with self.assertRaises(ValueError):workflow_template(host,sha(self.raw))
    def test_command_streams_separate_and_stdout_discovery_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=CommandRunner();runner.evidence=Path(directory);(runner.evidence/'logs').mkdir();runner.command_quiescence=[]
            argv=[sys.executable,'-c','import sys;print("stdout");print("stderr",file=sys.stderr)']
            self.assertEqual(runner.run('stdout-only',argv,stdout_only=True),'stdout\n')
            self.assertEqual((runner.evidence/'logs/stdout-only.stderr.log').read_text(),'stderr\n')
            self.assertEqual(runner.run('both-streams',argv),'stdout\nstderr\n')
    def test_metadata_types_counts_sources_and_variants_are_exact(self):
        report=dict(schema=1,source_sha256={p:'1'*64 for p in ('Native/Loader/elf_metadata_bounds.h','Native/anisette_base.h','Native/include/anisette_core.h','.ci/native-tests/fixtures/elf_metadata_bounds_unit.cpp')},results={k:copy.deepcopy(gate.METADATA_EXPECTED) for k in ('normal','optimized','sanitized')},sanitizers=['address','undefined'],leak_sanitizer_enabled=False,guest_execution=False,device_validation=False,proprietary_input=False)
        gate.verify_metadata_report(report)
        for mutate in (lambda d:d['results']['normal'].update(checks=712),lambda d:d['results']['normal'].update(guest_execution=0),lambda d:d.update(leak_sanitizer_enabled=0),lambda d:d['results'].pop('sanitized'),lambda d:d.update(unexpected=True),lambda d:d['source_sha256'].update({'unreviewed.h':'2'*64})):
            bad=copy.deepcopy(report);mutate(bad)
            with self.assertRaises(ValueError):gate.verify_metadata_report(bad)
    def test_deadline_and_timeout_cannot_become_success(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=CommandRunner();runner.evidence=Path(directory);(runner.evidence/'logs').mkdir();runner.command_quiescence=[]
            runner.deadline=time.monotonic()-1
            with self.assertRaises(ValueError):runner.run('expired',[sys.executable,'-c','pass'])
            runner.deadline=time.monotonic()+5
            with self.assertRaises(subprocess.TimeoutExpired):runner.run('timeout',[sys.executable,'-c','import time;time.sleep(30)'],timeout=0.05)
            receipt=parse((runner.evidence/'logs/timeout.settlement.json').read_bytes())
            self.assertNotEqual((runner.evidence/'logs/timeout.exit-code.txt').read_text(),'0\n')
            self.assertTrue(receipt['ownedProcessGroup']['quiescent']);self.assertTrue(receipt['ownedProcessGroup']['identityRetainedForSignals'])
    def test_nested_start_failure_is_observed_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'probe.py';script.write_text('import subprocess\nsubprocess.run(["/no-such-p0login-fixture-executable"])\n')
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',P0LOGIN_NESTED_COMMANDS=str(root/'observed'))
            result=subprocess.run([sys.executable,'-B',str(HERE/'run_observed_script.py'),str(script)],env=env,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(parse((root/'observed/0001.command.json').read_bytes())['argv'],['/no-such-p0login-fixture-executable'])
            self.assertEqual(parse((root/'observed/0001.result.json').read_bytes())['error'],'FileNotFoundError')
    def test_ordinary_build_guard_is_one_exact_branch_only(self):
        original=ordinary(self.host,BUILD_WORKFLOW_PATH).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            host=Path(directory);path=host/BUILD_WORKFLOW_PATH;path.parent.mkdir(parents=True)
            path.write_bytes(original)
            self.assertEqual(ordinary_build_guard(host),self.data['ordinary_build_guard'])
            for bad in (original.replace(BUILD_GUARD.encode(),b''),original.replace(BUILD_GUARD.encode(),(BUILD_GUARD*2).encode()),original.replace(b'validation/p0-login-trace-phase-a',b'validation/other')):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):ordinary_build_guard(host)
            path.write_bytes(original.replace(b'name: Xcode - Build',b'name: Altered old workflow'))
            self.assertNotEqual(ordinary_build_guard(host),self.data['ordinary_build_guard'])
    def test_suite_owner_selectors_never_alias_and_inherited_values_are_cleared(self):
        roots={name:Path('/synthetic')/name for name in OWNERS}
        inherited={key:'/incorrect/inherited' for key in gate.SUITE_SELECTORS}
        inherited.update(INIT_DIAGNOSTICS_PEER_ROOT='/incorrect/peer',P0LOGIN_EXPECTED_OWNER_ROOT='/incorrect/owner')
        for owner in ('SideStore','LiveContainer'):
            env=gate.suite_environment(owner,roots,Path('/records'),inherited)
            selected=env.get('SIDE_STORE_TEST_SOURCE') or env.get('MAINTAINED_LIVE_CONTAINER_TEST_SOURCE') or env.get('LIVE_CONTAINER_TEST_SOURCE')
            peer=roots['LiveContainer' if owner=='SideStore' else 'SideStore']
            self.assertEqual(selected,str(roots[owner]));self.assertEqual(env['INIT_DIAGNOSTICS_PEER_ROOT'],str(peer))
            self.assertEqual(env['P0LOGIN_EXPECTED_OWNER_ROOT'],selected)
            if owner=='LiveContainer':self.assertNotIn('SIDE_STORE_TEST_SOURCE',env)
            else:self.assertNotIn('LIVE_CONTAINER_TEST_SOURCE',env);self.assertNotIn('MAINTAINED_LIVE_CONTAINER_TEST_SOURCE',env)
        env=gate.suite_environment('AnisetteKit',roots,Path('/records'),inherited)
        self.assertFalse(set(gate.SUITE_SELECTORS)&set(env));self.assertNotIn('P0LOGIN_EXPECTED_OWNER_ROOT',env)
    def test_suite_runner_checks_actual_module_owner_peer_and_producer_before_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'LiveContainer';peer=base/'SideStore';producer=base/'AnisetteKit';suite=root/'tests/probe';suite.mkdir(parents=True);peer.mkdir();producer.mkdir()
            source='from pathlib import Path\nimport unittest\nROOT=Path('+repr(str(root))+')\nPEER=Path('+repr(str(peer))+')\nPRODUCER=Path('+repr(str(producer))+')\nclass Probe(unittest.TestCase):\n def test_case(self): pass\n'
            module=suite/'test_probe.py';module.write_text(source)
            expected=base/'ids.json';expected.write_text('["test_probe.Probe.test_case"]')
            roots={'LiveContainer':root,'SideStore':peer,'AnisetteKit':producer}
            env=gate.suite_environment('LiveContainer',roots,base/'correct-records',os.environ)
            args=[sys.executable,'-B',str(HERE/'run_unittest_suite.py'),str(suite),str(expected),'test_probe']
            good=subprocess.run(args,env=env,text=True,capture_output=True)
            self.assertEqual(good.returncode,0,good.stdout+good.stderr)
            self.assertEqual(parse(good.stdout.splitlines()[-1])['source_roots']['test_probe']['ROOT'],str(root.resolve()))
            module.write_text(source.replace('ROOT=Path('+repr(str(root))+')','ROOT=Path('+repr(str(peer))+')'))
            env['P0LOGIN_NESTED_COMMANDS']=str(base/'wrong-records')
            bad=subprocess.run(args,env=env,text=True,capture_output=True)
            self.assertNotEqual(bad.returncode,0);self.assertIn('ROOT aliases or differs',bad.stderr);self.assertNotIn('Ran 1 test',bad.stderr)
    def test_workflow_is_dedicated_branch_readonly_and_fail_closed(self):
        text=(self.host/'.github/workflows/p0-login-trace-phase-a.yml').read_text()
        self.assertIn('workflow_dispatch:',text);self.assertIn('  push:\n    branches:\n      - validation/p0-login-trace-phase-a\n',text)
        self.assertEqual(text.count('  push:'),1)
        self.assertEqual(ordinary_build_guard(self.host),self.data['ordinary_build_guard'])
        self.assertEqual(sha(workflow_template(self.host,sha(self.raw))),self.data['workflow_template_sha256'])
        self.assertIn("github.ref == 'refs/heads/validation/p0-login-trace-phase-a'",text)
        self.assertIn('persist-credentials: false',text)
        self.assertIn('steps.transport.outputs.settled',text)
        self.assertNotIn('ci/p0cxx/native_gate.py',text)
if __name__=='__main__':unittest.main(verbosity=2)
