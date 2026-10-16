"""Fail-closed P1 capture configuration tests; never substitutes for macOS/UI."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HOST = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('p1_capture', HOST / 'ci/p1/native_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CaptureGateTests(unittest.TestCase):
    def setUp(self):
        self.raw = (HOST / 'ci/p1/inputs.json').read_bytes()
        self.data = json.loads(self.raw)
        self.approved = gate.p0.sha(self.raw)

    def validate(self, data):
        raw = json.dumps(data).encode()
        return gate.validate(raw, gate.p0.sha(raw), HOST)

    def test_exact_sealed_inputs(self):
        self.assertEqual(gate.validate(self.raw, self.approved, HOST), self.data)

    def test_rejects_unapproved_digest(self):
        with self.assertRaisesRegex(ValueError, 'unreviewed input'):
            gate.validate(self.raw, 'f' * 64, HOST)

    def test_rejects_extra_schema_field(self):
        self.data['allow_old_ui'] = True
        with self.assertRaises(ValueError): self.validate(self.data)

    def test_rejects_duplicate_json_key(self):
        raw = b'{"schema_version":1,"schema_version":1}'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            gate.validate(raw, gate.p0.sha(raw), HOST)

    def test_rejects_p0_instead_of_p1(self):
        self.data['livecontainer']['commit'] = gate.PARENT
        with self.assertRaisesRegex(ValueError, 'exact P1'): self.validate(self.data)

    def test_rejects_p2_or_unrelated_delta(self):
        self.data['livecontainer']['changes']['Localizable.xcstrings'] = {}
        with self.assertRaisesRegex(ValueError, 'delta differs'): self.validate(self.data)

    def test_rejects_source_hash_drift(self):
        self.data['livecontainer']['changes'][gate.SHELL]['after']['sha256'] = 'f' * 64
        with self.assertRaises(ValueError): self.validate(self.data)

    def test_rejects_builder_drift(self):
        self.data['builder']['commit'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'renderer'): self.validate(self.data)

    def test_rejects_historical_render_baseline_drift(self):
        for key in self.data['render_baseline']:
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                data['render_baseline'][key] = 'unreviewed'
                with self.assertRaisesRegex(ValueError, 'historical rendering baseline'): self.validate(data)

    def test_verifies_actual_render_baseline_object(self):
        row = dict(gate.RENDER_BASELINE, sha256=gate.p0.sha(b'fixture bytes'))
        record = ('100644', 'blob', row['blob'])
        with patch.object(gate, 'git', side_effect=[row['commit'].encode(), row['tree'].encode(), b'fixture bytes']), \
             patch.object(gate.p0.primitives, 'entries', return_value={row['path']: record}):
            self.assertEqual(gate.verify_render_baseline(HOST, row), row)

    def test_rejects_actual_render_baseline_tree_drift(self):
        row = gate.RENDER_BASELINE
        with patch.object(gate, 'git', side_effect=[row['commit'].encode(), b'wrong tree']):
            with self.assertRaisesRegex(ValueError, 'commit/tree differs'): gate.verify_render_baseline(HOST, row)

    def test_rejects_actual_render_baseline_missing_or_changed_blob(self):
        row = gate.RENDER_BASELINE
        for records in ({}, {row['path']: ('120000', 'blob', row['blob'])}):
            with self.subTest(records=records), \
                 patch.object(gate, 'git', side_effect=[row['commit'].encode(), row['tree'].encode()]), \
                 patch.object(gate.p0.primitives, 'entries', return_value=records):
                with self.assertRaisesRegex(ValueError, 'grid blob differs'): gate.verify_render_baseline(HOST, row)

    def test_rejects_actual_render_baseline_bytes_drift(self):
        row = gate.RENDER_BASELINE
        record = ('100644', 'blob', row['blob'])
        with patch.object(gate, 'git', side_effect=[row['commit'].encode(), row['tree'].encode(), b'altered']), \
             patch.object(gate.p0.primitives, 'entries', return_value={row['path']: record}):
            with self.assertRaisesRegex(ValueError, 'grid bytes differ'): gate.verify_render_baseline(HOST, row)

    def test_rejects_child_pin_drift(self):
        self.data['submodules']['LiveContainer/litehook']['commit'] = 'f' * 40
        with self.assertRaisesRegex(ValueError, 'child pins'): self.validate(self.data)

    def test_rejects_p0_review_drift(self):
        self.data['inherited_p0_review_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'inheritance'): self.validate(self.data)

    def test_rejects_missing_adapter(self):
        self.data['adapter_files'].pop('ci/p0/source_primitives.py')
        with self.assertRaisesRegex(ValueError, 'inventory'): self.validate(self.data)

    def test_rejects_altered_adapter(self):
        self.data['adapter_files']['ci/p1/native_gate.py'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'altered adapter'): self.validate(self.data)

    def test_rejects_missing_or_duplicate_test(self):
        for ids in [self.data['expected_test_ids'][:-1], [self.data['expected_test_ids'][0]] * 8]:
            data = copy.deepcopy(self.data)
            data['expected_test_ids'] = ids
            with self.assertRaisesRegex(ValueError, 'cleanup8'): self.validate(data)

    def test_rejects_linux_native_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = gate.Capture(self.data, self.raw, self.approved, HOST, Path(tmp) / 'work', Path(tmp) / 'evidence')
            with patch.object(gate.platform, 'system', return_value='Linux'):
                with self.assertRaisesRegex(ValueError, 'macOS'): capture.execute()
            self.assertFalse((Path(tmp) / 'evidence').exists())

    def test_recovery_extraction_receives_exact_single_source_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = gate.Capture(self.data, self.raw, self.approved, HOST, Path(tmp) / 'work', Path(tmp) / 'evidence')
            with patch.object(capture, 'run', side_effect=RuntimeError('stop before native')) as run:
                with self.assertRaisesRegex(RuntimeError, 'stop before native'): capture.targeted_behavior()
            self.assertEqual(run.call_args.args, ('p1-recovery-extraction-tests',
                [gate.sys.executable, '-B', HOST / 'ci/p1/recovery_source_tests.py', capture.live / gate.SHELL]))

    def test_preserves_curated_ui_evidence_without_build_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = gate.Capture(self.data, self.raw, self.approved, HOST, root / 'work', root / 'evidence')
            source = capture.results / 'layout-evidence'
            for path in ['rendering-verification.json', 'p0-signin/phone-attachments/image.png',
                         'p0-build/DerivedData/file.json', 'corrected/Fixture.app/Info.plist']:
                target = source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('fixture bytes')
            capture.preserve_rendering()
            actual = {str(p.relative_to(capture.evidence)) for p in capture.evidence.rglob('*') if p.is_file()}
            self.assertEqual(actual, {'layout-evidence/rendering-verification.json',
                                     'layout-evidence/p0-signin/phone-attachments/image.png'})


if __name__ == '__main__': unittest.main()
