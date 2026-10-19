"""Historical XCTest and synthetic Swift Testing mutations; never execute Swift."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('capture_contract',HERE/'capture_contract.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
AK='anisette-trace-regression'
SS='sidesign-core-regression'
HISTORICAL=HERE/'tests/fixtures/historical-login-only/interleaved-xctest.stdout.txt'


def runtime(lane):
    if lane==AK:return HISTORICAL.read_bytes()
    _,groups=c.lane_data(lane);lines=[]
    for group,methods in groups.items():
        lines.append('◇ Suite "'+c.SUITES[group]+'" started.')
        for method in methods:
            lines.extend(['◇ Test '+method+'() started.','✔ Test '+method+'() passed after 0.001 seconds.'])
        lines.append('✔ Suite "'+c.SUITES[group]+'" passed after 0.001 seconds.')
    lines.append('✔ Test run with '+str(len(c.selected_ids(lane)))+' tests in '+str(len(groups))+' suites passed after 0.1 seconds.')
    return '\n'.join(lines).encode()


def xctest_rows():
    return c.runtime_rows(runtime(AK).decode())


def encoded_rows(rows):return '\n'.join(rows).encode()


class ContractMutations(unittest.TestCase):
    def reject(self,raw,lane):
        with self.assertRaises(ValueError):c.verify_runtime(raw,lane)

    def test_exact_two_lanes_accept_local_logs(self):
        self.assertEqual(set(c.LANES),{AK,SS})
        for lane in c.LANES:
            with self.subTest(lane=lane):
                discovery='\n'.join(c.discovered_ids(lane)).encode()
                self.assertEqual(c.verify_discovery(discovery,lane)['selected_test_ids'],c.selected_ids(lane))
                result=c.verify_runtime(runtime(lane),lane)
                self.assertEqual(result['executed'],len(c.selected_ids(lane)))
                self.assertFalse(result['authenticated_capture'])
                self.assertEqual(result['raw_sha256'],c.sha(runtime(lane)))

    def test_expected_counts_and_complete_framework_discovery(self):
        self.assertEqual({l:len(c.selected_ids(l)) for l in c.LANES},{AK:6,SS:5})
        for lane in c.LANES:
            self.assertEqual(c.discovered_ids(lane),c.selected_ids(lane))
            self.assertFalse(any(c.UNSAFE in case for case in c.discovered_ids(lane)))
        self.assertTrue(all(not case.endswith('()') for case in c.discovered_ids(AK)))
        self.assertTrue(all(case.endswith('()') for case in c.discovered_ids(SS)))

    def test_unsafe_discovery_is_outside_both_framework_lanes(self):
        for lane in c.LANES:
            rows=c.discovered_ids(lane)+['AnisetteKitTests.AnisetteKitTests/'+c.UNSAFE+'()']
            with self.assertRaises(ValueError):c.verify_discovery(encoded_rows(rows),lane)

    def test_exact_filter_accepts_only_reviewed_runtime_location_suffix(self):
        for lane in c.LANES:
            expression=c.exact_filter(lane)
            for case in c.selected_ids(lane):
                self.assertRegex(case,expression)
                if lane==SS:self.assertRegex(case+'/Source.swift:12:3',expression)
                else:self.assertNotRegex(case+'/Source.swift:12:3',expression)
                self.assertNotRegex(case+'Anything',expression)
                self.assertNotRegex('Injected'+case,expression)

    def test_missing_extra_duplicate_or_whitespace_discovery_rejects(self):
        for lane in c.LANES:
            ids=c.discovered_ids(lane)
            for rows in [ids[:-1],ids+['Injected.Tests/test()'],ids+[ids[0]],[' '+ids[0]]+ids[1:]]:
                with self.subTest(lane=lane,rows=rows):
                    with self.assertRaises(ValueError):c.verify_discovery(encoded_rows(rows),lane)

    def test_zero_test_and_empty_discovery_reject(self):
        for lane in c.LANES:
            with self.assertRaises(ValueError):c.verify_discovery(b'',lane)
            self.reject(b'Test run with 0 tests passed after 0 seconds.',lane)

    def test_missing_case_rejects(self):
        for lane in c.LANES:
            raw=runtime(lane);method=next(iter(c.lane_data(lane)[1].values()))[0]
            bad=b'\n'.join(line for line in raw.splitlines() if method.encode() not in line)
            self.reject(bad,lane)

    def test_extra_and_duplicate_runtime_case_rejects(self):
        for lane in c.LANES:
            for extra in [runtime(lane).splitlines()[0],'◇ Test onlineProvider() started.'.encode(),
                          '✔ Test onlineProvider() passed after 0.1 seconds.'.encode()]:
                self.reject(runtime(lane)+b'\n'+extra,lane)

    def test_failure_skip_cancel_or_issue_rejects(self):
        for lane in c.LANES:
            for suffix in [b'\nTest injected() failed.',b'\nTest injected() skipped.',b'\nTest injected() cancelled.',
                           b'\nTest injected() canceled.',b'\nIssue recorded',b'\nrecorded an issue',b'\n1 test failed']:
                with self.subTest(lane=lane,suffix=suffix):self.reject(runtime(lane)+suffix,lane)

    def test_unsafe_runtime_name_rejects_even_in_noise(self):
        for lane in c.LANES:self.reject(runtime(lane)+b'\n'+c.UNSAFE.encode(),lane)

    def test_wrong_summary_count_rejects(self):
        self.reject(runtime(AK).replace(b'Executed 6',b'Executed 99'),AK)
        self.reject(runtime(SS).replace(b'with 5 tests',b'with 99 tests'),SS)

    def test_xctest_cannot_leak_into_swift_testing_lane(self):
        self.reject(runtime(SS)+b'\n'+runtime(AK),SS)
        self.reject(runtime(SS)+b'\nExecuted malformed row',SS)

    def test_swift_testing_cannot_leak_into_xctest_lane(self):
        self.reject(runtime(AK)+b'\n'+runtime(SS),AK)
        self.reject(runtime(AK)+b'\nTesting Library Version: 6.0',AK)

    def test_diagnostic_outcome_failed_is_not_test_failure(self):
        for lane in c.LANES:
            raw=runtime(lane)+b'\nlogin_stage outcome=failed reason=cancelled'
            self.assertEqual(c.verify_runtime(raw,lane)['executed'],len(c.selected_ids(lane)))

    def test_log_bounds_encoding_nul_reject(self):
        for lane in c.LANES:
            for raw in [b'x'*(c.MAX_LOG_BYTES+1),b'\xff',runtime(lane)+b'\0']:
                with self.assertRaises((ValueError,UnicodeError)):c.verify_runtime(raw,lane)

    def test_historical_interleaved_xctest_is_accepted_without_changing_bytes(self):
        raw=HISTORICAL.read_bytes()
        self.assertIn(b'outcome=stTest Case ',raw)
        self.assertIn(b'\narted reason=none',raw)
        self.assertEqual(c.verify_runtime(raw,AK)['executed'],6)
        self.assertEqual(c.verify_runtime(raw,AK)['raw_sha256'],c.sha(raw))
        self.assertEqual(len(xctest_rows()),21)

    def test_ansi_and_crlf_preserve_real_xctest_contract(self):
        raw=runtime(AK).replace(b'Test Case ',b'\x1b[32mTest Case ').replace(b'\n',b'\x1b[0m\r\n')
        self.assertEqual(c.verify_runtime(raw,AK)['executed'],6)

    def test_complete_dotted_xctest_id_form(self):
        raw=re.sub(rb'-\[AnisetteKitTests\.LoginDiagnosticTraceTests (test\w+)\]',
                   rb'AnisetteKitTests.LoginDiagnosticTraceTests.\1',runtime(AK))
        self.assertEqual(c.verify_runtime(raw,AK)['executed'],6)

    def test_xctest_requires_all_three_suites_and_three_summaries(self):
        rows=xctest_rows()
        for index,row in enumerate(rows):
            if row.startswith(('Test Suite ','Executed ')):
                for mutation in ('delete','duplicate'):
                    changed=rows[:index]+([] if mutation=='delete' else [row,row])+rows[index+1:]
                    with self.subTest(index=index,mutation=mutation):self.reject(encoded_rows(changed),AK)
        # The old parser accepted bare cases plus just one matching count.
        bare=[row for row in rows if row.startswith('Test Case ')]+[rows[-1]]
        self.reject(encoded_rows(bare),AK)

    def test_xctest_rejects_every_adjacent_lifecycle_transposition(self):
        rows=xctest_rows()
        for index in range(len(rows)-1):
            changed=rows.copy();changed[index],changed[index+1]=changed[index+1],changed[index]
            with self.subTest(index=index):self.reject(encoded_rows(changed),AK)

    def test_xctest_all_summary_rows_fully_match(self):
        rows=xctest_rows();summary=rows[-1]
        malformed=[
            'Executed 6 tests, with 0 failures (0 unexpected)',
            'Executed 6 tests, with 0 failures (0 unexpected) in NaN (0.020) seconds',
            'Executed 6 tests, with 0 failures (0 unexpected) in -1 (0.020) seconds',
            'Executed 6 tests, with 0 failures (0 unexpected) in 0.009 (0.020) seconds garbage',
            'Executed malformed', 'Executed', 'Executed 0 tests, with 0 failures (0 unexpected) in 0 (0) seconds',
            summary.replace('0 failures','1 failures'),summary.replace('0 unexpected','1 unexpected'),
            summary.replace('6 tests','06 tests'),summary.replace('seconds','seconds.'),
        ]
        for bad in malformed:
            for index in (16,18,20):
                changed=rows.copy();changed[index]=bad
                with self.subTest(bad=bad,index=index):self.reject(encoded_rows(changed),AK)
            self.reject(runtime(AK)+b'\n'+bad.encode(),AK)
        self.reject(runtime(AK)+b'\n'+summary.encode(),AK)
        self.reject(runtime(AK)+b'\n'+summary.encode()+b' '+summary.encode(),AK)

    def test_malformed_event_markers_cannot_hide_as_noise(self):
        for lane in c.LANES:
            for row in ('Executed6 tests', 'EXECUTED malformed', 'TestCase malformed',
                        'TestSuite malformed', 'TEST CASE malformed', 'suite ignored'):
                with self.subTest(lane=lane,row=row):self.reject(runtime(lane)+b'\n'+row.encode(),lane)

    def test_xctest_suite_rows_fully_match(self):
        rows=xctest_rows()
        for index in (0,1,2,15,17,19):
            original=rows[index]
            malformed=[original+' junk',original[:-1],original.replace(' at ',' '),
                       original.replace('2026-10-19','2026-99-19'),original.replace('06:30:39','66:30:39'),
                       original.replace('started','ignored').replace('passed','ignored'),
                       original.replace("'",'"'),"Test Suite 'Unknown' started at 2026-10-19 06:30:39.710.",
                       "Test Suite", "Test Suite 'Broken"]
            for bad in malformed:
                changed=rows.copy();changed[index]=bad
                with self.subTest(index=index,bad=bad):self.reject(encoded_rows(changed),AK)
        for extra in (rows[0],"Test Suite 'Injected' ignored.","Test Suite",'Suite "Injected" started.'):
            self.reject(runtime(AK)+b'\n'+extra.encode(),AK)

    def test_xctest_case_rows_fully_match_even_when_interleaved(self):
        raw=runtime(AK)
        start="Test Case '-[AnisetteKitTests.LoginDiagnosticTraceTests "+c.AK_TRACE[0]+"]' started."
        passed=start.replace('started.','passed (0.006 seconds).')
        malformed=[passed+' junk',passed.replace('passed (0.006 seconds).','passed'),
                   passed.replace('0.006','nan'),passed.replace('0.006','-0.001'),
                   passed.replace('seconds','second'),passed.replace('passed','ignored'),
                   passed.replace('AnisetteKitTests.','Injected.'),passed.replace(c.AK_TRACE[0],'testUnreviewed'),
                   passed.replace("'",'"'),passed.replace('Test Case','Test  Case'),
                   start.replace('started.','started'),start+' junk',"Test Case",'Test unknown ignored.']
        for bad in malformed:
            target=start if bad.startswith(start[:-1]) else passed
            with self.subTest(bad=bad):self.reject(raw.replace(target.encode(),bad.encode(),1),AK)
        for bad in (start,passed,"Test Case 'Injected' ignored."):
            self.reject(raw+b'\n'+bad.encode(),AK)

    def test_xctest_duplicate_method_and_mixed_identity_reject(self):
        raw=runtime(AK)
        self.reject(raw.replace(c.AK_TRACE[1].encode(),c.AK_TRACE[0].encode()),AK)
        old='-[AnisetteKitTests.LoginDiagnosticTraceTests '+c.AK_TRACE[0]+']'
        new='AnisetteKitTests.LoginDiagnosticTraceTests.'+c.AK_TRACE[0]
        self.reject(raw.replace(old.encode(),new.encode(),1),AK)

    def test_xctest_case_pairs_may_use_another_serial_order(self):
        rows=xctest_rows();pairs=[rows[index:index+2] for index in range(3,15,2)]
        changed=rows[:3]+[row for pair in reversed(pairs) for row in pair]+rows[-6:]
        self.assertEqual(c.verify_runtime(encoded_rows(changed),AK)['executed'],6)

    def test_swift_testing_unknown_suite_or_status_rejects(self):
        for extra in [b'Suite "Injected" started.',b'Suite "Injected" passed after 1 second.',
                      b'Suite "Injected" ignored.',b'Test injected() ignored.',b'Test injected() started.']:
            self.reject(runtime(SS)+b'\n'+extra,SS)

    def test_swift_testing_all_test_and_suite_rows_fully_match(self):
        lines=runtime(SS).decode().splitlines()
        for index in range(len(lines)-1):
            original=lines[index]
            for bad in (original+' junk',original[:-1],original.replace('started.','started garbage.').replace('passed after','passed before')):
                changed=lines.copy();changed[index]=bad
                with self.subTest(index=index,bad=bad):self.reject(encoded_rows(changed),SS)
        for bad in ('Test malformed() started','Suite "SideSign Core Tests" passed after nonsense',
                    'Test deviceInitializationAndFiltering() passed after NaN seconds.'):
            self.reject(runtime(SS)+b'\n'+bad.encode(),SS)

    def test_swift_testing_unknown_extra_or_malformed_run_rows_reject(self):
        for extra in (b'Test run aborted.',b'Test run with 0 tests passed.',
                      b'Test run with malformed counts completed.',b'Test run started.'):
            self.reject(runtime(SS)+b'\n'+extra,SS)
        original=runtime(SS).splitlines()[-1]
        for bad in (original+b' junk',original[:-1],original.replace(b'0.1',b'NaN')):
            self.reject(runtime(SS).replace(original,bad),SS)

    def test_optional_finite_run_opening_precedes_suites(self):
        good='◇ Test run started.\n'.encode()+runtime(SS)
        self.assertEqual(c.verify_runtime(good,SS)['executed'],5)
        self.reject(b'Test run started.\n'+good,SS)
        lines=runtime(SS).splitlines();lines.insert(1,b'Test run started.')
        self.reject(b'\n'.join(lines),SS)

    def test_swift_testing_missing_or_duplicate_summary_rejects(self):
        lines=runtime(SS).splitlines()
        for value in [b'\n'.join(lines[:-1]),runtime(SS)+b'\n'+lines[-1]]:self.reject(value,SS)

    def test_swift_testing_summary_before_cases_rejects(self):
        lines=runtime(SS).splitlines()
        self.reject(b'\n'.join([lines[-1]]+lines[:-1]),SS)

    def test_swift_testing_suite_pass_before_cases_rejects(self):
        lines=runtime(SS).splitlines();lines.insert(1,lines.pop(-2))
        self.reject(b'\n'.join(lines),SS)

    def test_swift_testing_wrong_summary_suite_count_rejects(self):
        self.reject(runtime(SS).replace(b'in 1 suites',b'in 9 suites'),SS)
        self.assertEqual(c.verify_runtime(runtime(SS).replace(b' in 1 suites',b''),SS)['executed'],5)

    def test_swift_testing_case_pass_before_start_rejects(self):
        lines=runtime(SS).splitlines();lines[1],lines[2]=lines[2],lines[1]
        self.reject(b'\n'.join(lines),SS)

    def test_swift_testing_parallel_case_lifecycles_remain_valid(self):
        lines=runtime(SS).splitlines()
        parallel=[lines[0]]+lines[1:-2:2]+list(reversed(lines[2:-2:2]))+lines[-2:]
        self.assertEqual(c.verify_runtime(b'\n'.join(parallel),SS)['executed'],5)

    def test_exact_commands_validate_without_running(self):
        for lane in c.LANES:
            commands=c.proposed_commands(lane)['commands'];c.validate_commands(lane,commands)
            for stage in ('discover','execute'):
                cmd=commands[stage]
                enabled,disabled=(('--enable-xctest','--disable-swift-testing') if lane==AK
                                  else ('--enable-swift-testing','--disable-xctest'))
                self.assertIn(enabled,cmd);self.assertIn(disabled,cmd)
                self.assertEqual(cmd.count('--filter'),int(stage=='execute'))
                self.assertEqual(cmd[:len(c.SANDBOX)],c.SANDBOX)
            self.assertEqual(commands['discover'][len(c.SANDBOX):len(c.SANDBOX)+3],['swift','test','list'])

    def test_unfiltered_run_and_broad_filter_reject(self):
        for lane in c.LANES:
            for suffix in [[],['--filter','.*'],['--filter','AnisetteKitTests']]:
                commands=copy.deepcopy(c.expected_commands(lane));commands['execute']=commands['execute'][:-2]+suffix
                with self.assertRaises(ValueError):c.validate_commands(lane,commands)

    def test_network_sandbox_removal_rejects(self):
        for lane in c.LANES:
            for stage in ('discover','execute'):
                commands=c.expected_commands(lane);commands[stage]=commands[stage][len(c.SANDBOX):]
                with self.assertRaises(ValueError):c.validate_commands(lane,commands)

    def test_every_complementary_framework_flag_is_required(self):
        for lane in c.LANES:
            for stage in ('discover','execute'):
                flags=('--enable-xctest','--disable-swift-testing') if lane==AK else ('--disable-xctest','--enable-swift-testing')
                for flag in flags:
                    commands=c.expected_commands(lane);commands[stage].remove(flag)
                    with self.subTest(lane=lane,stage=stage,flag=flag):
                        with self.assertRaises(ValueError):c.validate_commands(lane,commands)

    def test_extra_cli_flags_shell_or_stage_reject(self):
        for lane in c.LANES:
            for mutation in ['extra','shell','stage','path']:
                commands=c.expected_commands(lane)
                if mutation=='extra':commands['execute']+=['--skip','.*']
                if mutation=='shell':commands['execute']=['sh','-c','swift test']
                if mutation=='stage':commands['upload']=['curl','https://example.invalid']
                if mutation=='path':commands['build'][3]='/unreviewed'
                with self.assertRaises(ValueError):c.validate_commands(lane,commands)

    def test_execution_is_unconditionally_disabled(self):
        with self.assertRaisesRegex(ValueError,'LOCAL_ONLY'):c.refuse_execution()

    def test_unknown_and_removed_lanes_reject(self):
        for lane in ('all-tests','anisette-reserve','sidesign-reserve'):
            with self.assertRaises(ValueError):c.proposed_commands(lane)

    def test_frozen_complete_test_source_inventory_matches(self):
        inventory=json.loads((HERE/'reviewed/inventory.proposed.json').read_text())
        for owner in ['AnisetteKit','SideSign']:
            result=c.verify_test_sources(HERE/'tests/fixtures'/owner,owner,inventory)
            self.assertEqual(result['audited_test_files'],len(inventory['swift_files'][owner]))

    def test_test_source_change_missing_extra_or_link_reject(self):
        inventory=json.loads((HERE/'reviewed/inventory.proposed.json').read_text());owner='AnisetteKit'
        for mutation in ['changed','missing','extra','link']:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)/owner
                shutil.copytree(HERE/'tests/fixtures'/owner/'Tests',root/'Tests')
                path=root/'Tests/AnisetteKitTests/LoginDiagnosticTraceTests.swift'
                if mutation=='changed':path.write_bytes(path.read_bytes()+b'// drift')
                if mutation=='missing':path.unlink()
                if mutation=='extra':(path.parent/'Extra.swift').write_text('import Testing')
                if mutation=='link':
                    original=path.read_bytes();path.unlink();target=Path(temp)/'target';target.write_bytes(original);path.symlink_to(target)
                with self.assertRaises(ValueError):c.verify_test_sources(root,owner,inventory)

    def test_observed_enabled_framework_source_ids_equal_discovery(self):
        inventory=json.loads((HERE/'reviewed/inventory.proposed.json').read_text())
        for owner,lane in [('AnisetteKit',AK),('SideSign',SS)]:
            observed={i for row in inventory['swift_files'][owner].values() for i in row['test_ids']}
            if owner=='AnisetteKit':observed={i for i in observed if not i.endswith('()')}
            self.assertEqual(observed,set(c.discovered_ids(lane)))


if __name__=='__main__':unittest.main(verbosity=2)
