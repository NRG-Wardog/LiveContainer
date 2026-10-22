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
        self.markers = {k: 'CONTROL_PASS_' + k for k in ('legacy','auth','profile','wire_service','wire_host')}
        for name in gate.REQUIRED_INPUTS:
            path = self.sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('source control double: ' + name)
        self.config = {'schema':'comprehensive-diagnostics-source-contract-v1',
            'source_inputs_bound':True, 'schemas':{'request':'ar1','profile':'hp2','provider':'ap1'},
            'input_sha256':{name:gate.digest((self.sources/name).read_bytes()) for name in sorted(gate.REQUIRED_INPUTS)},
            'success_markers':self.markers}
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
            gate.write_json(folder/'source-evidence.json', {'schema':'auth-request-source-evidence-v1',
                'inputs':{k:self.config['input_sha256'][gate.SIGN+'/'+k] for k in mappings},
                'outputs':{k:gate.digest((folder/k).read_bytes()) for k in gate.AUTH_FILES}})
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
