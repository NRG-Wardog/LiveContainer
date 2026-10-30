"""Actual composite source closure, with omission/replacement/duplicate controls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('vpn_composite_dependency', HERE / 'generate_fixture.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

class ClassifierDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = HERE.parents[2]
        helper_spec = importlib.util.spec_from_file_location('actual_wire_dependency', root / generator.HELPER)
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        source = root / 'SideStore/SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift'
        cls.declaration = helper.block(source.read_text(), 'struct V3RefreshSelectionFailure:')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            cls.receipt = generator.generate(root, output)
            cls.swift = (output / 'vpn-refresh-recovery.swift').read_text()

    def test_actual_dependency_is_present_once_and_hash_bound(self):
        generator.validate_classifier_dependency(self.swift, self.declaration)
        path = 'SideStore/SideStore/Core/Operations/PipelineOperations/RefreshAppOperation.swift'
        self.assertIn(path, self.receipt['transport_fixture_inputs_sha256'])

    def test_omitted_actual_dependency_fails(self):
        with self.assertRaises(AssertionError):
            generator.validate_classifier_dependency(self.swift.replace(self.declaration, '', 1), self.declaration)

    def test_replacement_double_fails(self):
        altered = self.swift.replace(self.declaration, 'struct V3RefreshSelectionFailure: Error {}', 1)
        with self.assertRaises(AssertionError):
            generator.validate_classifier_dependency(altered, self.declaration)

    def test_duplicate_dependency_fails(self):
        with self.assertRaises(AssertionError):
            generator.validate_classifier_dependency(self.swift + '\n' + self.declaration, self.declaration)

if __name__ == '__main__':
    unittest.main()
