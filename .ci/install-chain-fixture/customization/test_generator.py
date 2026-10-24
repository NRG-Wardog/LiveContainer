#!/usr/bin/env python3
"""Source-only generator checks. Never launches Swift, binaries, networking, or devices."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("customization_generator", HERE / "generate.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


class GeneratorTests(unittest.TestCase):
    root = None
    preferences_source = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="customization-source-only-")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "Fixture.swift"
        self.manifest = gen.generate(self.root, self.output, self.preferences_source)
        self.generated = self.output.read_text()
        source_root = self.root
        if (source_root / "SideStore" / next(iter(gen.PINS))).is_file():
            source_root /= "SideStore"
        self.source_root = source_root

    def test_entire_operation_is_exact_except_explicit_receiver_substitution(self):
        path = next(iter(gen.PINS))
        original = gen.block((self.source_root / path).read_text(), "final class UserCustomizationOperation:")
        actual = gen.block(self.generated, "final class UserCustomizationOperation:")
        self.assertEqual(actual, original.replace("UserDefaults.standard", "testDefaults"))
        self.assertEqual(original.count("UserDefaults.standard"), 9)

    def test_actual_protocol_and_entire_default_extension_are_preserved(self):
        original = (self.source_root / "SideStore/Core/Operations/PipelineExecutionHandler.swift").read_text()
        for declaration in ("protocol UserCustomizationHandler:", "extension UserCustomizationHandler {",
                            "enum ProfileCustomizationChoice:", "enum AppGroupResolution:"):
            self.assertEqual(gen.block(self.generated, declaration), gen.block(original, declaration))
        extension = gen.block(self.generated, "extension UserCustomizationHandler {")
        self.assertEqual(extension.count("throw OperationError.invalidParameters("), 6)

    def test_exact_native_preference_properties_and_false_registration(self):
        path = self.preferences_source or self.source_root / "AltStore/Core/Extensions/UserDefaults+AltStore.swift"
        original = path.read_text()
        for key in gen.KEYS:
            self.assertIn(gen.block(original, f"@objc var {key}: Bool").replace("@objc ", "", 1), self.generated)
            self.assertIn(f'"{key}": false,', self.generated)
        self.assertIn('UserDefaults(suiteName: testSuiteName)!', self.generated)
        self.assertIn('testDefaults.persistentDomain(forName: testSuiteName)', self.generated)

    def test_ordered_case_manifest_and_runtime_schema(self):
        self.assertEqual(len(gen.CASE_NAMES), 17)
        self.assertEqual(len(set(gen.CASE_NAMES)), 17)
        cases = (HERE / "Cases.swift").read_text()
        names = re.findall(r'await run\("([^"\n]+)"\)', cases)
        dynamic = 'persisted_true_\\(key)_survives_registration_and_reaches_actual_default'
        position = names.index(dynamic)
        names[position:position + 1] = gen.CASE_NAMES[3:7]
        self.assertEqual(names, list(gen.CASE_NAMES))
        self.assertIn('schema: "install-chain-runtime-v1", group: "customization"', self.generated)
        self.assertIn('native_signing_device_executed: false', self.generated)
        self.assertEqual(self.manifest['case_names'], names)

    def test_drop_persisted_true_negative_is_single_mutation(self):
        output = self.output.with_name("NegativeDropPersistedTrue.swift")
        manifest = gen.generate(self.root, output, self.preferences_source, "drop-persisted-true")
        self.assertEqual(output.read_text(), self.generated.replace("// MUTATION_POINT_DROP_PERSISTED_TRUE", "testDefaults.removeObject(forKey: key)"))
        self.assertEqual(manifest['negative_control']['intended_failing_cases'], list(gen.CASE_NAMES[3:9]))

    def test_bypass_info_plist_negative_is_single_actual_branch_mutation(self):
        output = self.output.with_name("NegativeBypassInfoPlist.swift")
        manifest = gen.generate(self.root, output, self.preferences_source, "bypass-info-plist")
        self.assertEqual(output.read_text(), self.generated.replace("if testDefaults.customizeInfoPlist {", "if false && testDefaults.customizeInfoPlist {"))
        self.assertEqual(manifest['negative_control']['intended_failing_cases'], [gen.CASE_NAMES[3]])

    def test_source_hash_drift_is_rejected(self):
        source = self.source_root / next(iter(gen.PINS))
        with self.assertRaisesRegex(ValueError, "Source blob mismatch"):
            gen.checked(source, "0" * 40)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--preferences-source', type=Path)
    args, rest = parser.parse_known_args()
    GeneratorTests.root = args.root
    GeneratorTests.preferences_source = args.preferences_source
    unittest.main(argv=[__file__] + rest)
