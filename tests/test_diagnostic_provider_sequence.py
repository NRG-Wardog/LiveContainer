"""Execute production Foundation policy; distinguish missing Swift from success."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = ROOT / "LiveContainerSwiftUI/Models/V3DiagnosticProviderSequence.swift"
SHELL = ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift"


class ProviderSequenceTests(unittest.TestCase):
    def test_capability_gated_host_integration(self):
        source = SHELL.read_text()
        self.assertIn('V3DiagnosticProviderPlan.offered(kind: kind,', source)
        self.assertIn('if offeredDiagnosticProviders != nil {', source)
        self.assertIn('guard let plan = selectedDiagnosticProviders else { return }', source)
        self.assertIn('answer["diagnosticProviderOrder"] = plan.encoded', source)
        self.assertIn('} else if usesRemoteMacAnisetteForSubmit {', source)
        self.assertIn('diagnosticSequenceEnabled = false', source)

    def test_production_policy(self):
        swift = shutil.which("swiftc")
        if not swift:
            self.skipTest("Swift compiler required; policy execution not performed")
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "provider-sequence"
            subprocess.run([swift, str(POLICY), str(ROOT / "tests/provider_sequence/main.swift"),
                            "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
            self.assertIn("checks passed", result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
