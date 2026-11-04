"""Execute production policies and extracted prompt actions, never a routing replica.

The Foundation probe removes SwiftUI storage/access wrappers only. It executes
actual prompt properties, lifecycle bodies, button actions and disabled predicates.
This is not a SwiftUI render, accessibility or device-authentication test.
"""
import json
import pathlib
import plistlib
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = ROOT / "LiveContainerSwiftUI/Models/V3DiagnosticProviderSequence.swift"
SHELL = ROOT / "LiveContainerSwiftUI/Views/V3UnifiedShell.swift"
COPY_KEYS = {
    "Advanced diagnostics",
    "Diagnostic provider sequence is enabled.",
    "Remote Mac is selected automatically for normal sign-in.",
}
LANGUAGES = {"en", "he", "ru", "zh-Hans", "zh-Hant"}


def block(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def body(source, signature):
    result = block(source, signature)
    return result[result.index("{") + 1:-1]


def prompt_source():
    return block(SHELL.read_text(), "struct V3PromptSection: View {")


def prompt_probe():
    """Extract maintained code; fail if any requested source anchor disappears."""
    source = prompt_source()
    states = re.findall(r"^    @State private var .+$", source, re.M)
    assert len(states) == 8, states
    declarations = [line.replace("@State private ", "") for line in states]
    for signature in [
        "private var kind:", "private var offeredDiagnosticProviders:",
        "private var selectedDiagnosticProviders:", "private var usesRemoteMacAnisetteForSubmit:",
        "private var providerSelectionSummary:", "private var fieldDefs:",
        "private var options:", "private func loadFields(", "private func submit(",
        "private func respond(",
    ]:
        declarations.append(block(source, signature).replace("private ", "", 1))
    # UIKit work is unrelated to prompt/provider state. Strip exactly the two
    # async repair-URL launches, not any lifecycle state transitions.
    for signature, name in [(".onAppear {", "appear"),
                            ('.onChange(of: prompt["id"] as? String ?? "")', "promptChanged"),
                            (".onDisappear {", "disappear")]:
        action = body(source, signature)
        if name == "promptChanged":
            assert action.startswith(" _ in\n")
            action = action[len(" _ in"): ]
        if name != "disappear":
            repair = "Task { await loadRepairURL() }"
            assert action.count(repair) == 1
            action = action.replace(repair, "")
        declarations.append("func " + name + "() {" + action + "}")

    submit = block(source, 'if fieldDefs.count > 0 && options.isEmpty {')
    submit_disabled = re.search(r"\.disabled\(([^\n]+)\)", submit).group(1)
    submit_action = body(submit, 'Button("Submit")')
    declarations.append('func tapSubmit() { guard fieldDefs.count > 0 && options.isEmpty, !(' +
                        submit_disabled + ') else { return }; ' + submit_action + ' }')
    toggle = re.search(r'Toggle\("Try providers in order", isOn: \$(\w+)\)\s*\.disabled\(([^\n]+)\)', source)
    assert toggle
    declarations.append('func setDiagnosticToggle(_ value: Bool) { guard offeredDiagnosticProviders != nil, advancedDiagnosticsExpanded, !(' +
                        toggle[2] + ') else { return }; ' + toggle[1] + ' = value }')
    expansion = re.search(r'DisclosureGroup\("Advanced diagnostics", isExpanded: \$(\w+)\)', source)
    assert expansion
    declarations.append('func expandAdvanced(_ value: Bool) { guard offeredDiagnosticProviders != nil else { return }; ' + expansion[1] + ' = value }')
    controls = [
        ('moveEarlier(_ index: Int)', 'guard index > 0 else { return }'),
        ('moveLater(_ index: Int)', 'guard index + 1 < diagnosticProviderOrder.count else { return }'),
        ('removeProvider(_ raw: String)', 'guard diagnosticProviderOrder.count > 1 else { return }'),
        ('addProvider(_ provider: V3DiagnosticProvider)', 'guard !diagnosticProviderOrder.contains(provider.rawValue) else { return }'),
    ]
    for signature, anchor in controls:
        position = source.index(anchor)
        start = source.rfind('Button', 0, position)
        action = block(source[start:], source[start:position].split('{')[0])
        tail = source[start + len(action):]
        disabled = re.search(r"\.disabled\(([^\n]+)\)", tail).group(1)
        declarations.append('func ' + signature + ' { guard offeredDiagnosticProviders != nil, advancedDiagnosticsExpanded, diagnosticSequenceEnabled, !(' +
                            disabled + ') else { return }; ' + action[action.index('{') + 1:-1] + ' }')
    cancel = block(source, 'if showsCancellation, let onCancel {')
    cancel_action = body(cancel, 'Button(LocalizedStringKey(cancellationTitle), role: .cancel)')
    cancel_disabled = re.search(r"\.disabled\(([^\n]+)\)", cancel).group(1)
    declarations.append('func tapCancel() { if showsCancellation, let onCancel { guard !(' +
                        cancel_disabled + ') else { return }; ' + cancel_action + ' } }')
    return '''import Foundation
final class PromptProbe {
    var prompt: [String: Any] = [:]
    var isSubmitting = false
    var isSubmissionBlocked = false
    var initialCredentialDraftID: String? = nil
    var showsCancellation = true
    var cancellationDisabled = false
    var onCancel: (() -> Void)? = nil
    var answers: [[String: String]] = []
    func onAnswer(_ answer: [String: String]) { answers.append(answer) }
''' + "\n".join(declarations) + "\n}\n"


class ProviderSequenceTests(unittest.TestCase):
    def test_capability_gated_host_integration(self):
        source = prompt_source()
        self.assertIn('V3DiagnosticProviderPlan.offered(kind: kind,', source)
        self.assertIn('guard let plan = selectedDiagnosticProviders else { return }', source)
        self.assertIn('answer["diagnosticProviderOrder"] = plan.encoded', source)
        self.assertIn('} else if usesRemoteMacAnisetteForSubmit {', source)
        self.assertIn('@State private var diagnosticSequenceEnabled = false', source)
        self.assertIn('@State private var advancedDiagnosticsExpanded = false', source)
        offered = block(source, 'if offeredDiagnosticProviders != nil {')
        disclosure = block(offered, 'DisclosureGroup("Advanced diagnostics", isExpanded: $advancedDiagnosticsExpanded)')
        self.assertIn('Toggle("Try providers in order", isOn: $diagnosticSequenceEnabled)', disclosure)
        self.assertIn('if diagnosticSequenceEnabled {', disclosure)
        self.assertIn('ForEach(Array(diagnosticProviderOrder.enumerated()),', disclosure)
        summary = block(source, 'if let summary = providerSelectionSummary {')
        self.assertNotIn(summary, disclosure)
        self.assertLess(source.index(summary), source.index(offered))
        self.assertIn('V3LocalizedText(summary)', summary)
        # Expansion is presentation-only. There is no observer or route mutation.
        self.assertEqual(source.count('advancedDiagnosticsExpanded'), 4)
        for signature in ['private func submit(', 'private func respond(']:
            self.assertNotIn('advancedDiagnosticsExpanded', block(source, signature))
        for signature in ['private func loadFields(', '.onDisappear {']:
            reset = block(source, signature)
            self.assertIn('diagnosticSequenceEnabled = false', reset)
            self.assertIn('advancedDiagnosticsExpanded = false', reset)
        self.assertIn('onCancel()', block(source, 'if showsCancellation, let onCancel {'))
        self.assertIn('guard !isSubmitting else { return }', block(source, 'private func respond('))
        self.assertNotIn('authBegin', source)
        self.assertNotIn('UserDefaults', source)
        self.assertNotIn('onAnswer', block(source, '.onDisappear {'))

    def test_actual_prompt_extraction_is_complete(self):
        probe = prompt_probe()
        self.assertIn('func loadFields(', probe)
        self.assertIn('func promptChanged()', probe)
        self.assertIn('func disappear()', probe)
        self.assertIn('diagnosticProviderOrder.swapAt(index, index - 1)', probe)
        self.assertIn('guard !isSubmitting else { return }', probe)
        self.assertNotIn('Task {', probe)
        self.assertNotIn('@State', probe)

    def test_finite_copy_translations(self):
        source = prompt_source()
        summary = block(source, 'private var providerSelectionSummary:')
        owned = set(re.findall(r'return "([^"]+)"', summary))
        owned.update(re.findall(r'DisclosureGroup\("([^"]+)", isExpanded: \$advancedDiagnosticsExpanded\)', source))
        self.assertEqual(owned, COPY_KEYS)
        catalog = json.loads((ROOT / 'Resources/Localizable.xcstrings').read_text())['strings']
        for key in owned:
            translations = catalog[key]['localizations']
            self.assertEqual(set(translations), LANGUAGES)
            for language, row in translations.items():
                unit = row['stringUnit']
                self.assertEqual(unit['state'], 'translated')
                self.assertTrue(unit['value'].strip())
                if language == 'en': self.assertEqual(unit['value'], key)
                else: self.assertNotEqual(unit['value'], key)
                self.assertNotIn('\\(', unit['value'])

    def test_finite_initialization_rejection_copy(self):
        key = "Apple rejected provider initialization"
        catalog = json.loads((ROOT / 'Resources/Localizable.xcstrings').read_text())['strings']
        translations = catalog[key]['localizations']
        self.assertEqual(set(translations), LANGUAGES)
        for language, row in translations.items():
            self.assertEqual(row['stringUnit']['state'], 'translated')
            self.assertTrue(row['stringUnit']['value'].strip())
            if language == 'en': self.assertEqual(row['stringUnit']['value'], key)
            else: self.assertNotEqual(row['stringUnit']['value'], key)
        self.assertIn('Text(V3Localization.string(result.title))', SHELL.read_text())
        self.assertIn('case "providerRejectedInit": return "' + key + '"', POLICY.read_text())

    def test_production_policy(self):
        swift = shutil.which("swiftc")
        if not swift:
            self.skipTest("Swift compiler required; policy execution not performed")
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "provider-sequence"
            subprocess.run([swift, str(POLICY), str(ROOT / "tests/provider_sequence/main.swift"),
                            "-o", str(binary)], check=True, timeout=120)
            result = subprocess.run([str(binary)], check=True, text=True, capture_output=True, timeout=30)
            self.assertIn("checks passed", result.stdout)
            print(result.stdout.strip())

    def test_actual_prompt_actions_and_localization(self):
        swift = shutil.which("swiftc")
        if not swift:
            self.skipTest("Swift compiler required; prompt actions and native rendering NOT RUN")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            probe = root / 'PromptProbe.swift'
            probe.write_text(prompt_probe())
            main = root / 'main.swift'
            main.write_text((ROOT / 'tests/provider_sequence/prompt_main.swift').read_text())
            bundle = root / 'Prompt.bundle'
            bundle.mkdir()
            (bundle / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'test.synthetic.provider-prompt', 'CFBundleDevelopmentRegion': 'en'}))
            strings = json.loads((ROOT / 'Resources/Localizable.xcstrings').read_text())['strings']
            for language in LANGUAGES:
                folder = bundle / (language + '.lproj')
                folder.mkdir()
                values = {key: strings[key]['localizations'][language]['stringUnit']['value'] for key in COPY_KEYS}
                (folder / 'Localizable.strings').write_bytes(plistlib.dumps(values))
            expected = root / 'expected.json'
            expected.write_text(json.dumps({lang: {key: strings[key]['localizations'][lang]['stringUnit']['value']
                                                   for key in COPY_KEYS} for lang in LANGUAGES}, ensure_ascii=False))
            binary = root / 'prompt'
            result = subprocess.run([swift, str(POLICY), str(ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift'),
                                     str(probe), str(main), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary), str(bundle), str(expected)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PROMPT_PROVIDER_UI_POLICY_PASS', result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
