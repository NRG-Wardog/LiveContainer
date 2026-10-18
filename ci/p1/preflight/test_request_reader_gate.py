"""Portable extraction/raw-gate tests; native filesystem cases run on macOS CI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import request_reader_gate as gate

HERE = Path(__file__).resolve().parent
SOURCE = (HERE / 'runner_ui_tests.swift').read_text()


def positive():
    return dict(schema='p1-request-reader-regression-v1', passed=True, admissionEligible=False,
                uiExecuted=False, simulatorExecuted=False,
                cases=[dict(id=name, passed=True) for name in gate.CASES])


class ReaderGate(unittest.TestCase):
    def test_positive(self): self.assertEqual(gate.verify(positive()), positive())
    def test_missing_case(self):
        row=positive();row['cases'].pop()
        with self.assertRaises(ValueError):gate.verify(row)
    def test_duplicate(self):
        row=positive();row['cases'][1]=row['cases'][0]
        with self.assertRaises(ValueError):gate.verify(row)
    def test_reordered(self):
        row=positive();row['cases'].reverse()
        with self.assertRaises(ValueError):gate.verify(row)
    def test_false_case(self):
        row=positive();row['cases'][0]['passed']=False
        with self.assertRaises(ValueError):gate.verify(row)
    def test_integer_pass_not_boolean(self):
        row=positive();row['cases'][0]['passed']=1
        with self.assertRaises(ValueError):gate.verify(row)
    def test_failed_overall(self):
        row=positive();row['passed']=False
        with self.assertRaises(ValueError):gate.verify(row)
    def test_unexpected_error(self):
        row=positive();row['error']='partial'
        with self.assertRaises(ValueError):gate.verify(row)
    def test_scope(self):
        for key in ['admissionEligible','uiExecuted','simulatorExecuted']:
            with self.subTest(key=key):
                row=positive();row[key]=True
                with self.assertRaises(ValueError):gate.verify(row)
    def test_marker_identity(self):
        block=gate.extracted(SOURCE)
        self.assertEqual(SOURCE.count(block),1)
        self.assertTrue(block.startswith(gate.START) and block.endswith(gate.END))
    def test_marker_reject(self):
        for text in [SOURCE.replace(gate.START,''), SOURCE+gate.START, SOURCE.replace(gate.END,''), gate.END+gate.START]:
            with self.subTest(text=text[:40]),self.assertRaises(ValueError):gate.extracted(text)
    def test_actual_extraction_and_command_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();calls=[]
            def command(*args,**kwargs):
                calls.append((args,kwargs));return json.dumps(positive()) if len(calls)==3 else 'native Swift version'
            report=gate.run(command,root/'work',root/'output')
            self.assertTrue(report['passed']);self.assertEqual([c[1]['timeout'] for c in calls],[10,60,10])
            self.assertIn('P1_REQUEST_READER_REGRESSION',calls[1][0]);self.assertEqual(calls[2][0],(root/'work/request-reader-regression',))
            self.assertEqual((root/'output/runner-reader.swift').read_text(),gate.extracted(SOURCE))
            self.assertEqual(report['compiled_source_sha256'],gate.digest((root/'output/request-reader-regression.swift').read_bytes()))
    def test_compile_failure_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            def command(*args,**kwargs):raise RuntimeError('compile failure')
            with self.assertRaises(RuntimeError):gate.run(command,root/'work',root/'output')
            self.assertIs(json.loads((root/'output/result.json').read_text())['passed'],False)
    def test_raw_failure_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();row=positive();row['passed']=False
            def command(*args,**kwargs):return json.dumps(row)
            with self.assertRaises(ValueError):gate.run(command,root/'work',root/'output')
            self.assertEqual(json.loads((root/'output/native-report.json').read_text()),row)
            self.assertIs(json.loads((root/'output/result.json').read_text())['passed'],False)
    def test_fresh_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'work').mkdir()
            with self.assertRaises(ValueError):gate.run(None,root/'work',root/'output')
    def test_gate_precedes_source_and_simulator(self):
        source=(HERE/'capture.py').read_text().split('def execute(',1)[1]
        self.assertLess(source.index('request_reader_gate.run('),source.index('base.acquire('))
        self.assertLess(source.index('request_reader_gate.run('),source.index("'simctl'"))
    def test_test_hook_absent_from_actual_build_recipe(self):
        for path in [HERE/'capture.py',HERE.parent/'video/capture.py']:
            self.assertNotIn('P1_REQUEST_READER_REGRESSION',path.read_text())
        block=gate.extracted(SOURCE)
        self.assertEqual(block.count('#if P1_REQUEST_READER_REGRESSION'),3)
        self.assertEqual(block.count('#endif'),3)
    def test_discard_does_not_advance_protocol(self):
        read=SOURCE.split('    private var discardedRequests',1)[1].split('// fsync',1)[0]
        self.assertNotIn('previousID',read);self.assertNotIn('response',read)
        self.assertIn('discardedRequests <= 64',read);self.assertIn('return observation.data',read)
        poll=SOURCE.split('    private func poll()',1)[1].split('final class P1Screenshot',1)[0]
        self.assertLess(poll.index('guard let bytes'),poll.index('previousBytes = bytes; previousID = command.id'))
        self.assertIn('let deadline = try capabilityNow() + 180',SOURCE)
    def test_discard_type_size_guards_precede_unlink(self):
        block=gate.extracted(SOURCE)
        for guard in ['(info.st_mode & S_IFMT) == S_IFREG','info.st_size > 0 && info.st_size <= 8192','result == 0']:
            self.assertLess(block.index(guard),block.index('info.st_nlink == 0'))
        self.assertIn('guard info.st_nlink == 1',block)
    def test_closed_before_return_or_error(self):
        block=gate.extracted(SOURCE)
        self.assertLess(block.index('let closeResult = close(input)'),block.index('return (discarded ? nil'))
        self.assertIn('receipt["close"]',block);self.assertIn('receipt["primaryReason"]',block)
        self.assertIn('row["requestFile"] = typed.receipt',SOURCE)
    def test_native_inventory_anchored(self):
        text=(HERE/'request_reader_regression.swift').read_text()
        for name in gate.CASES:
            if not any(name.startswith(k+'-') for k in ['rename','unlink','hardlink']):self.assertIn('"'+name+'"',text)
        self.assertEqual(len(gate.CASES),21)

    def test_diagnostic_outside_exact_protocol_inventory(self):
        import test_capability as fixture
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();decoded,events,strip=fixture.fixture(root)
            (root/'raw-runner/reader-discard-001.json').write_text('{"schema":"p1-request-file-observation-v1","admissionEligible":false}')
            self.assertIn('"reader-discard-%03d.json"',SOURCE)
            self.assertTrue(fixture.analysis.inspect(root,fixture.SESSION,decoded,events,strip)['calibration_feasible'])
            (root/'raw-runner/request-discard-001.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'extra/missing durable channel rows'):
                fixture.analysis.inspect(root,fixture.SESSION,decoded,events,strip)
    def test_early_gate_failure_retains_harness_and_inputs(self):
        source=(HERE/'capture.py').read_text().split('def execute(',1)[1]
        self.assertLess(source.index('shutil.copytree(HERE'),source.index('request_reader_gate.run('))
        self.assertLess(source.index("shutil.copy2(inputs,output/'approved-inputs.json')"),source.index('request_reader_gate.run('))
