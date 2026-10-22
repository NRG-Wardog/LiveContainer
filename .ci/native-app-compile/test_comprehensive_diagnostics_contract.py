"""Control/receipt guards only: subprocess doubles, no Swift/native/provider execution."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('comprehensive', HERE / 'verify_comprehensive_diagnostics.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS may expose the same temporary directory via /var and /private/var.
        # Match the runner's canonical paths without relaxing evidence comparisons.
        self.root = Path(self.temp.name).resolve()
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        self.output = self.root / 'evidence'
        self.swiftc = self.root / 'swiftc-control-double'
        self.swiftc.write_text('Never executed\n')
        self.contract = self.root / 'contract.json'
        self.markers = {k: 'CONTROL_PASS_' + k for k in ('legacy','auth','iloader','onboarding','profile','wire_service','wire_host')}
        for name in gate.REQUIRED_INPUTS:
            path = self.sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('source control double: ' + name)
        self.config = {'schema':'comprehensive-diagnostics-source-contract-v1',
            'source_inputs_bound':True, 'schemas':{'request':'ar1','profile':'hp2','provider':'ap1'},
            'input_sha256':{name:gate.digest((self.sources/name).read_bytes()) for name in sorted(gate.REQUIRED_INPUTS)},
            'success_markers':self.markers, 'onboarding_case_names':['control-case-a']}
        self.save_contract()
        self.calls = []

    def save_contract(self):
        gate.write_json(self.contract, self.config)

    def control_process(self, argv, **kwargs):
        name = gate.COMMANDS[len(self.calls)]
        self.calls.append((name, argv))
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'], '1')
        data = b'control double\n'
        if name == 'legacy-generate':
            Path(argv[-1]).write_text('// generated control double')
            mappings = {'errors': gate.SIGN+'/Sources/Models/Errors.swift', 'auth': gate.SIGN+'/Sources/DeveloperPortal/Authentication.swift',
                        'store':'SideStore/AltStore/AppDelegate.swift', 'host':'LiveContainer/SideStoreSupport/SideStore.swift',
                        'shell':'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift'}
            gate.write_json(Path(argv[-1]).with_suffix('.sources.json'), {'input_sha256':{k:self.config['input_sha256'][v] for k,v in mappings.items()}})
        elif name == 'auth-generate':
            folder = Path(argv[-1])
            for file in gate.AUTH_FILES:
                (folder / file).write_text('// generated control double')
            mappings = ['Sources/DeveloperPortal/Authentication.swift','Sources/Models/AuthenticationDiagnosticTrace.swift','Sources/Models/Errors.swift']
            gate.write_json(folder/'source-evidence.json', {'schema':'auth-request-source-evidence-v1','baseline_commit':'9' * 40,
                'inputs':{k:self.config['input_sha256'][gate.SIGN+'/'+k] for k in mappings},
                'outputs':{k:gate.digest((folder/k).read_bytes()) for k in gate.AUTH_FILES}})
        elif name == 'iloader-generate':
            folder = Path(argv[argv.index('--output-dir') + 1])
            self.assertEqual(Path(argv[argv.index('--sidestore-root') + 1]), self.sources / 'SideStore')
            for file in gate.ILOADER_FILES:
                (folder / file).write_text('// generated control double')
            mappings = ['Sources/DeveloperPortal/Authentication.swift','Sources/Models/AuthenticationDiagnosticTrace.swift',
                        'Sources/Models/Errors.swift','Sources/Anisette/ILoaderRemoteAnisette.swift',
                        'Sources/DeveloperPortal/ILoaderAuthenticationPolicy.swift',
                        '.ci/iloader-auth-parity/generate.py','.ci/iloader-auth-parity/test_source.py']
            inputs = {k:self.config['input_sha256'][gate.SIGN + '/' + k] for k in mappings}
            factory = 'SideStore/SideStore/Core/Anisette/AnisetteProvider.swift'
            inputs[factory] = self.config['input_sha256'][factory]
            gate.write_json(folder / 'source-evidence.json', {
                'schema':'iloader-auth-parity-source-evidence-v1', 'official_reference':gate.ILOADER_OFFICIAL_REFERENCE,
                'baseline_commit':'9' * 40, 'inputs':inputs,
                'outputs':{k:gate.digest((folder / k).read_bytes()) for k in gate.ILOADER_FILES},
                'output_closure':list(gate.ILOADER_FILES), 'boundary_replacements':['control double boundary'],
                'network':False, 'native_provider':False, 'swift_executed':False})
        elif name == 'onboarding-generate':
            folder = Path(argv[argv.index('--output-dir') + 1])
            self.assertEqual(Path(argv[argv.index('--sidesign-root') + 1]), self.sources / gate.SIGN)
            self.assertEqual(Path(argv[argv.index('--sidestore-root') + 1]), self.sources / 'SideStore')
            for file in gate.ONBOARDING_FILES:
                (folder / file).write_text('// generated control double')
            used = {}
            for relative in gate.ONBOARDING_REQUIRED_SOURCES:
                key = 'SideStore/Dependencies/' + relative if relative.startswith('SideSign/') else relative
                used[relative] = self.config['input_sha256'][key]
            used.update({k:v for k,v in self.config['input_sha256'].items() if k.startswith(gate.ONBOARDING + '/')})
            gate.write_json(folder / 'source-evidence.json', {
                'schema':'iloader-onboarding-scope-source-evidence-v1', 'inputs':used,
                'outputs':{k:gate.digest((folder / k).read_bytes()) for k in gate.ONBOARDING_FILES},
                'output_closure':list(gate.ONBOARDING_FILES), 'boundary_replacements':['control double boundary'],
                'network':False, 'native_provider':False, 'swift_executed':False})
        elif name == 'profile-generate':
            Path(argv[argv.index('--output')+1]).write_text('// generated control double')
            mappings = ['Sources/Models/AuthenticationHeaderProvenance.swift','Sources/Anisette/AnisetteDataManager.swift']
            gate.write_json(Path(argv[-1]), {'sources':{'SideSign/'+k:{'sha256':self.config['input_sha256'][gate.SIGN+'/'+k]} for k in mappings},
                'generated_sha256':gate.digest(Path(argv[argv.index('--output')+1]).read_bytes())})
        elif name == 'wire-generate':
            for file in ('service.swift','host.swift'):
                (Path(argv[-1])/file).write_text('// generated control double')
            mappings = {'service':'SideStore/AltStore/AppDelegate.swift', 'host':'LiveContainer/SideStoreSupport/SideStore.swift',
                'ui':'LiveContainer/LiveContainerSwiftUI/Views/V3UnifiedShell.swift',
                'operation':'SideStore/SideStore/Core/Operations/StandaloneOperations/SignInOperation.swift',
                'collector':gate.SIGN+'/Sources/Models/AuthenticationDiagnosticTrace.swift',
                'provenance':gate.SIGN+'/Sources/Models/AuthenticationHeaderProvenance.swift',
                'constants':gate.SIGN+'/Sources/Constants.swift'}
            gate.write_json(Path(argv[-1])/'sources.json', {'input_sha256':{k:self.config['input_sha256'][v] for k,v in mappings.items()},
                'generated_sha256':{k:gate.digest((Path(argv[-1])/k).read_bytes()) for k in ('service.swift','host.swift')}})
        elif name.endswith('-compile'):
            Path(argv[-1]).write_bytes(b'not an executable; control double only')
        elif name == 'auth-run':
            gate.write_json(Path(argv[-1]), {'schema':'auth-request-cases-v1','producer':'control-only',
                                          'cases':[{'name':'case-a'}]})
            data = (self.markers['auth'] + '\n').encode()
        elif name == 'iloader-run':
            gate.write_json(Path(argv[-1]), {'schema':'iloader-auth-parity-cases-v1','fake_only':True,
                                          'cases':['control-case-a']})
            data = (self.markers['iloader'] + '\n').encode()
        elif name == 'onboarding-run':
            gate.write_json(Path(argv[-1]), {'schema':'iloader-onboarding-scope-cases-v1','fake_only':True,
                                          'cases':['control-case-a']})
            data = (self.markers['onboarding'] + '\n').encode()
        elif name == 'profile-run':
            gate.write_json(Path(argv[-1]), {'schema':'profile-provenance-cases-v1','producer':'control-only',
                                          'cases':[{'name':str(n)} for n in range(12)]})
            data = (self.markers['profile'] + '\n').encode()
        elif name == 'wire-service-run':
            self.assertEqual(Path(argv[2]), self.output/'auth-request/cases.json')
            self.assertEqual(Path(argv[3]), self.output/'profile-provenance/cases.json')
            Path(argv[1]).write_bytes(b'control-only wire output')
            data = ('WIRE_IMPORTED_CASES schema=auth-request-cases-v1 producer_cases=1 wire_cases=2\n'
                    'WIRE_IMPORTED_CASES schema=profile-provenance-cases-v1 producer_cases=12 wire_cases=24\n'
                    + self.markers['wire_service'] + '\n').encode()
        elif name == 'wire-host-run':
            self.assertEqual(Path(argv[1]), self.output/'wire-copy/wire-cases.plist')
            data = (self.markers['wire_host'] + '\n').encode()
        elif name == 'legacy-run':
            data = (self.markers['legacy'] + '\n').encode()
        return subprocess.CompletedProcess(argv, 0, data)

    def run_control(self, process=None):
        with patch.object(gate.subprocess, 'run', side_effect=process or self.control_process):
            return gate.run(self.sources, self.swiftc, self.output, self.contract)

    def test_unbound_contract_rejected(self):
        self.config['source_inputs_bound'] = False
        self.save_contract()
        with self.assertRaisesRegex(ValueError, 'unbound'):
            gate.load_contract(self.contract)

    def test_missing_required_input_rejected(self):
        self.config['input_sha256'].pop(next(iter(self.config['input_sha256'])))
        self.save_contract()
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            gate.load_contract(self.contract)

    def test_bad_sha_rejected(self):
        self.config['input_sha256'][next(iter(self.config['input_sha256']))] = 'PENDING'
        self.save_contract()
        with self.assertRaisesRegex(ValueError, 'Malformed'):
            gate.load_contract(self.contract)

    def test_unbound_success_marker_rejected(self):
        self.config['success_markers']['profile'] = 'PENDING'
        self.save_contract()
        with self.assertRaisesRegex(ValueError, 'Unbound'):
            gate.load_contract(self.contract)

    def test_wrong_schema_rejected(self):
        self.config['schemas']['profile'] = 'hp1'
        self.save_contract()
        with self.assertRaisesRegex(ValueError, 'schema'):
            gate.load_contract(self.contract)

    def test_path_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            gate.regular(self.sources, '../contract.json')

    def test_symlink_rejected(self):
        target = self.sources/'link'
        target.symlink_to(self.contract)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            gate.regular(self.sources, 'link')

    def test_missing_source_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            gate.regular(self.sources, 'missing')

    def test_source_byte_drift_rejected(self):
        (self.sources / next(iter(gate.REQUIRED_INPUTS))).write_text('drift')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            gate.source_inventory(self.sources, self.config)

    def test_extra_fixture_file_rejected(self):
        (self.sources / gate.AUTH / 'extra.py').write_text('unreviewed')
        with self.assertRaisesRegex(ValueError, 'Unpinned'):
            gate.source_inventory(self.sources, self.config)

    def test_missing_marker_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
            gate.require_marker('anything\n', 'PASS')

    def test_duplicate_marker_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
            gate.require_marker('PASS\nPASS\n', 'PASS')

    def test_marker_requires_exact_line(self):
        with self.assertRaises(ValueError):
            gate.require_marker('prefix PASS\n', 'PASS')
        gate.require_marker('PASS\n', 'PASS')

    def test_case_count_and_duplicate_name_rejected(self):
        path = self.root/'cases.json'
        gate.write_json(path, {'schema':'x','cases':[{'name':'a'},{'name':'a'}]})
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            gate.exported_cases(path,'x')
        gate.write_json(path, {'schema':'x','cases':[{'name':'a'}]})
        with self.assertRaisesRegex(ValueError, 'count'):
            gate.exported_cases(path,'x',12)

    def test_case_schema_rejected(self):
        path = self.root/'cases.json'
        gate.write_json(path, {'schema':'wrong','cases':[{'name':'a'}]})
        with self.assertRaisesRegex(ValueError, 'schema'):
            gate.exported_cases(path,'expected')

    def test_fresh_output_required(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.run_control()
        self.assertFalse(self.calls)

    def test_complete_control_order_and_case_interchange(self):
        report = self.run_control()
        self.assertEqual([name for name,_ in self.calls], list(gate.COMMANDS))
        self.assertEqual(report['status'], gate.STATUS)
        self.assertEqual([name for name,_ in self.calls].count('iloader-run'), 1)
        self.assertEqual(set(report['producer_exports']), {'auth-request', 'profile-provenance'})
        self.assertEqual(set(report['fixture_exports']), {'iloader-auth-parity', 'iloader-onboarding-scope'})
        self.assertEqual([name for name,_ in self.calls].count('onboarding-run'), 1)
        self.assertTrue(report['source_owned_fake_authentication_executed'])
        self.assertFalse(report['live_authentication_executed'])
        self.assertEqual(gate.verify_receipt(self.output/'report.json',self.contract), report)
        for name, argv in self.calls:
            if name.endswith('-compile'):
                self.assertNotIn('-L',argv)
                self.assertNotIn('-lAnisetteKit',argv)
                self.assertNotIn('-framework',argv)

    def test_symlink_backed_temp_root_preserves_exact_case_paths(self):
        alias = self.root / 'temp-root-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        # Force the macOS-style alias on every platform, then exercise the same
        # setup and all command/receipt assertions rather than weakening equality.
        with patch.object(tempfile, 'tempdir', str(alias)):
            probe = Controls('test_complete_control_order_and_case_interchange')
            try:
                probe.setUp()
                self.assertNotEqual(Path(probe.temp.name), Path(probe.temp.name).resolve())
                probe.test_complete_control_order_and_case_interchange()
                self.assertEqual(probe.root, Path(probe.temp.name).resolve())
                self.assertEqual(probe.output, probe.root / 'evidence')
            finally:
                probe.doCleanups()

    def test_actual_failure_exit_code_retained(self):
        def fail(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 7, b'actual failure\n')
        with self.assertRaisesRegex(ValueError, 'exit=7'):
            self.run_control(fail)
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(report['commands'][0]['exit_code'],7)
        self.assertEqual(report['status'],'FAILED')

    def test_missing_generated_swift_stops_before_compile(self):
        def missing(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'auth-generate':
                (self.output/'auth-request/RuntimeTests.swift').unlink()
            return result
        with self.assertRaisesRegex(ValueError, 'seven-file'):
            self.run_control(missing)
        self.assertNotIn('auth-compile',[name for name,_ in self.calls])

    def test_mutated_source_fails_final_immutability(self):
        def mutate(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'wire-host-run':
                (self.sources/gate.AUTH/'generate.py').write_text('changed')
            return result
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.run_control(mutate)
        self.assertEqual(json.loads((self.output/'report.json').read_text())['status'],'FAILED')

    def test_tampered_artifact_receipt_rejected(self):
        self.run_control()
        (self.output/'wire-copy/host.swift').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'hashes|receipt|evidence'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_missing_command_receipt_rejected(self):
        report = self.run_control()
        report['commands'].pop()
        gate.write_json(self.output/'report.json',report)
        with self.assertRaisesRegex(ValueError, 'command receipt'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_false_native_execution_receipt_rejected(self):
        report = self.run_control()
        report['guest_binary_executed'] = True
        gate.write_json(self.output/'report.json',report)
        with self.assertRaisesRegex(ValueError, 'Forbidden'):
            gate.verify_receipt(self.output/'report.json',self.contract)


    def test_missing_extraction_manifest_rejected(self):
        self.run_control()
        (self.output/'auth-request/source-evidence.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_extraction_source_hash_mismatch_rejected(self):
        self.run_control()
        path = self.output/'wire-copy/sources.json'
        value = json.loads(path.read_text())
        value['input_sha256']['collector'] = '0' * 64
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError, 'Wire extraction input evidence'):
            gate.extraction_receipt(self.output,self.config)

    def test_generated_source_hash_mismatch_rejected(self):
        self.run_control()
        (self.output/'auth-request/Errors.swift').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Auth generated-source hashes'):
            gate.extraction_receipt(self.output,self.config)



    def test_iloader_source_arguments_are_explicit(self):
        self.run_control()
        argv = dict(self.calls)['iloader-source']
        self.assertEqual(Path(argv[argv.index('--sidestore-root') + 1]), self.sources / 'SideStore')

    def test_iloader_missing_generated_swift_stops_before_compile(self):
        def missing(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'iloader-generate':
                (self.output/'iloader-auth-parity/ILoaderRemoteAnisette.swift').unlink()
            return result
        with self.assertRaisesRegex(ValueError, 'iLoader seven-file'):
            self.run_control(missing)
        self.assertNotIn('iloader-compile', [name for name,_ in self.calls])

    def test_iloader_extra_generated_swift_stops_before_compile(self):
        def extra(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'iloader-generate':
                (self.output/'iloader-auth-parity/Unexpected.swift').write_text('// unapproved')
            return result
        with self.assertRaisesRegex(ValueError, 'iLoader seven-file'):
            self.run_control(extra)

    def test_iloader_missing_or_duplicate_marker_rejected(self):
        for text in ('wrong', 'CONTROL_PASS_iloader\nCONTROL_PASS_iloader'):
            with self.subTest(text=text):
                probe = Controls('test_complete_control_order_and_case_interchange')
                try:
                    probe.setUp()
                    def bad(argv, **kwargs):
                        result = probe.control_process(argv, **kwargs)
                        if probe.calls[-1][0] == 'iloader-run':
                            return subprocess.CompletedProcess(argv, 0, (text + '\n').encode())
                        return result
                    with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
                        probe.run_control(bad)
                finally:
                    probe.doCleanups()

    def test_iloader_nonzero_exit_is_retained(self):
        def fail(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'iloader-run':
                return subprocess.CompletedProcess(argv, 9, b'fake failure\n')
            return result
        with self.assertRaisesRegex(ValueError, 'exit=9'):
            self.run_control(fail)
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['commands'][-1]['name'], 'iloader-run')
        self.assertEqual(report['commands'][-1]['exit_code'], 9)

    def test_iloader_unpinned_fixture_rejected(self):
        (self.sources / gate.ILOADER / 'extra.py').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'Unpinned'):
            self.run_control()
        self.assertFalse(self.calls)

    def test_iloader_case_export_guards(self):
        path = self.root/'iloader-cases.json'
        valid = {'schema':'iloader-auth-parity-cases-v1','fake_only':True,'cases':['a']}
        for key,value in [('schema','wrong'),('fake_only',False),('cases',[]),('cases',['a','a']),('cases',[{'name':'a'}])]:
            bad = {**valid,key:value}
            gate.write_json(path,bad)
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                gate.iloader_exported_cases(path)

    def test_iloader_missing_manifest_rejected(self):
        self.run_control()
        (self.output/'iloader-auth-parity/source-evidence.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_iloader_wrong_extracted_source_rejected(self):
        self.run_control()
        path = self.output/'iloader-auth-parity/source-evidence.json'
        value = json.loads(path.read_text())
        value['inputs']['Sources/Anisette/ILoaderRemoteAnisette.swift'] = '0'*64
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError, 'iLoader extraction input hash'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_iloader_generator_execution_claim_rejected(self):
        self.run_control()
        path = self.output/'iloader-auth-parity/source-evidence.json'
        value = json.loads(path.read_text()); value['network'] = True; gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError, 'Forbidden iLoader'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_iloader_missing_or_repeated_command_receipt_rejected(self):
        original = self.run_control()
        for duplicate in (False,True):
            report = copy.deepcopy(original)
            i = next(i for i,row in enumerate(report['commands']) if row['name']=='iloader-run')
            if duplicate: report['commands'].insert(i,copy.deepcopy(report['commands'][i]))
            else: report['commands'].pop(i)
            gate.write_json(self.output/'report.json',report)
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'command receipt'):
                gate.verify_receipt(self.output/'report.json',self.contract)

    def test_iloader_export_receipt_tamper_rejected(self):
        report = self.run_control()
        report['fixture_exports']['iloader-auth-parity']['count'] += 1
        gate.write_json(self.output/'report.json',report)
        with self.assertRaisesRegex(ValueError, 'iLoader fixture case receipt'):
            gate.verify_receipt(self.output/'report.json',self.contract)


    def test_onboarding_source_arguments_are_explicit(self):
        self.run_control()
        argv = dict(self.calls)['onboarding-source']
        self.assertEqual(Path(argv[argv.index('--sidestore-root') + 1]), self.sources / 'SideStore')
        self.assertEqual(Path(argv[argv.index('--sidesign-root') + 1]), self.sources / gate.SIGN)

    def test_onboarding_missing_generated_swift_stops_before_compile(self):
        def missing(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'onboarding-generate':
                (self.output/'iloader-onboarding-scope/CandidateOnboarding.swift').unlink()
            return result
        with self.assertRaisesRegex(ValueError, 'Onboarding three-file'):
            self.run_control(missing)
        self.assertNotIn('onboarding-compile', [name for name,_ in self.calls])

    def test_onboarding_extra_generated_swift_stops_before_compile(self):
        def extra(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'onboarding-generate':
                (self.output/'iloader-onboarding-scope/Unexpected.swift').write_text('// unapproved')
            return result
        with self.assertRaisesRegex(ValueError, 'Onboarding three-file'):
            self.run_control(extra)

    def test_onboarding_missing_or_duplicate_marker_rejected(self):
        for text in ('wrong', 'CONTROL_PASS_onboarding\nCONTROL_PASS_onboarding'):
            with self.subTest(text=text):
                probe = Controls('test_complete_control_order_and_case_interchange')
                try:
                    probe.setUp()
                    def bad(argv, **kwargs):
                        result = probe.control_process(argv, **kwargs)
                        if probe.calls[-1][0] == 'onboarding-run':
                            return subprocess.CompletedProcess(argv, 0, (text + '\n').encode())
                        return result
                    with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
                        probe.run_control(bad)
                finally:
                    probe.doCleanups()

    def test_onboarding_nonzero_exit_is_retained(self):
        def fail(argv, **kwargs):
            result = self.control_process(argv, **kwargs)
            if self.calls[-1][0] == 'onboarding-run':
                return subprocess.CompletedProcess(argv, 9, b'fake failure\n')
            return result
        with self.assertRaisesRegex(ValueError, 'exit=9'):
            self.run_control(fail)
        report = json.loads((self.output/'report.json').read_text())
        self.assertEqual(report['status'], 'FAILED')
        self.assertEqual(report['commands'][-1]['name'], 'onboarding-run')
        self.assertEqual(report['commands'][-1]['exit_code'], 9)

    def test_onboarding_unpinned_fixture_rejected(self):
        (self.sources / gate.ONBOARDING / 'extra.py').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'Unpinned'):
            self.run_control()
        self.assertFalse(self.calls)

    def test_onboarding_case_export_guards(self):
        path = self.root/'onboarding-cases.json'
        valid = {'schema':'iloader-onboarding-scope-cases-v1','fake_only':True,'cases':['a']}
        for key,value in [('schema','wrong'),('fake_only',False),('cases',[]),('cases',['a','a']),('cases',[{'name':'a'}])]:
            bad = {**valid,key:value}
            gate.write_json(path,bad)
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                gate.onboarding_exported_cases(path, self.config['onboarding_case_names'])

    def test_onboarding_missing_manifest_rejected(self):
        self.run_control()
        (self.output/'iloader-onboarding-scope/source-evidence.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_onboarding_wrong_extracted_source_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        value = json.loads(path.read_text())
        value['inputs']['SideSign/Sources/Anisette/ILoaderRemoteAnisette.swift'] = '0'*64
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError, 'Onboarding extraction input hash'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_onboarding_generator_execution_claim_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        value = json.loads(path.read_text()); value['network'] = True; gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError, 'Forbidden Onboarding'):
            gate.verify_receipt(self.output/'report.json',self.contract)

    def test_onboarding_missing_or_repeated_command_receipt_rejected(self):
        original = self.run_control()
        for duplicate in (False,True):
            report = copy.deepcopy(original)
            i = next(i for i,row in enumerate(report['commands']) if row['name']=='onboarding-run')
            if duplicate: report['commands'].insert(i,copy.deepcopy(report['commands'][i]))
            else: report['commands'].pop(i)
            gate.write_json(self.output/'report.json',report)
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'command receipt'):
                gate.verify_receipt(self.output/'report.json',self.contract)

    def test_onboarding_export_receipt_tamper_rejected(self):
        report = self.run_control()
        report['fixture_exports']['iloader-onboarding-scope']['count'] += 1
        gate.write_json(self.output/'report.json',report)
        with self.assertRaisesRegex(ValueError, 'Onboarding fixture case receipt'):
            gate.verify_receipt(self.output/'report.json',self.contract)


    def test_onboarding_unbound_case_contract_stops_before_execution(self):
        for names in (None, [], ['a', 'a'], ['__PENDING_CASES__']):
            with self.subTest(names=names):
                self.config['onboarding_case_names'] = names
                self.save_contract()
                with self.assertRaisesRegex(ValueError, 'Onboarding case contract'):
                    self.run_control()
                self.assertFalse(self.calls)

    def test_onboarding_missing_expected_case_stops_before_following_suite(self):
        base = self.control_process
        def bad(argv, **kwargs):
            result = base(argv, **kwargs)
            if self.calls[-1][0] == 'onboarding-run':
                gate.write_json(Path(argv[-1]), {'schema':'iloader-onboarding-scope-cases-v1',
                                                'fake_only':True, 'cases':['unreviewed-replacement']})
            return result
        with self.assertRaisesRegex(ValueError, 'Onboarding case coverage'):
            self.run_control(bad)
        self.assertEqual(self.calls[-1][0], 'onboarding-run')
        self.assertEqual(json.loads((self.output/'report.json').read_text())['status'], 'FAILED')

    def test_onboarding_missing_proxy_or_fixture_input_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        original = json.loads(path.read_text())
        for key, error in [('SideStore/SideStore/Core/Auth/DeveloperPortalProxy.swift', 'queued onboarding'),
                           (gate.ONBOARDING + '/generate.py', 'Unrecorded Onboarding')]:
            with self.subTest(key=key):
                value = copy.deepcopy(original); del value['inputs'][key]; gate.write_json(path,value)
                with self.assertRaisesRegex(ValueError,error):
                    gate.extraction_receipt(self.output,self.config)

    def test_onboarding_output_hash_and_closure_mismatch_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        original = json.loads(path.read_text())
        value = copy.deepcopy(original); value['outputs']['CandidateOnboarding.swift'] = '0' * 64
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError,'Onboarding generated-source hashes'):
            gate.extraction_receipt(self.output,self.config)
        value = copy.deepcopy(original); value['output_closure'].pop(); gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError,'Onboarding generated-source closure'):
            gate.extraction_receipt(self.output,self.config)

    def test_onboarding_boundary_receipt_empty_or_duplicated_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        original = json.loads(path.read_text())
        for boundaries in ([], ['same', 'same'], [None]):
            with self.subTest(boundaries=boundaries):
                value = copy.deepcopy(original); value['boundary_replacements'] = boundaries
                gate.write_json(path,value)
                with self.assertRaisesRegex(ValueError,'Onboarding boundary receipt'):
                    gate.extraction_receipt(self.output,self.config)

    def test_onboarding_unqualified_source_input_rejected(self):
        self.run_control()
        path = self.output/'iloader-onboarding-scope/source-evidence.json'
        value = json.loads(path.read_text()); value['inputs']['unqualified.swift'] = '0' * 64
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError,'repository prefix'):
            gate.extraction_receipt(self.output,self.config)
        del value['inputs']['unqualified.swift']
        value['inputs']['SideStore/unpinned.swift'] = None
        gate.write_json(path,value)
        with self.assertRaisesRegex(ValueError,'Onboarding extraction input hash'):
            gate.extraction_receipt(self.output,self.config)


if __name__ == '__main__':
    unittest.main(verbosity=2)
