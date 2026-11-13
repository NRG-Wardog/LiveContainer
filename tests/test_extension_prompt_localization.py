"""Production adapter regression coverage; native execution requires swiftc."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class ExtensionPromptLocalization(unittest.TestCase):
    def test_closed_owned_vocabulary(self):
        source = (ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift').read_text()
        for token in ['extensionFallbackReasons.contains($0)', 'counts[0] == counts[1]', 'identifier.utf8.count <= 255', '?? unavailableDetails(language: language, bundle: bundle)']:
            self.assertIn(token, source)

    @unittest.skipUnless(shutil.which('swiftc'), 'Swift compiler required; run on macOS CI')
    def test_actual_adapter(self):
        source = ROOT / 'LiveContainerSwiftUI/Utilities/V3Localization.swift'
        harness = r'''
import Foundation
let missing = "Some details are unavailable in the selected language."
let paragraph = "This version falls back as a group: all 5 extensions stay installed and use separate profiles. This fallback avoids 0 additional App IDs and may require up to 5 separate App IDs (some may already exist). No extension is removed and no required capability is discarded. Continue with separate provisioning?"
let prompt = "Extensions that could not qualify for ReuseMain:\n• com.example.widget: app groups differ; keychain groups differ\n\n" + paragraph
let offer = "com.example contains 5 extension(s). Experimental ReuseMain is for ordinary apps only, not host self-install or self-refresh. If all 5 extensions pass compatibility checks, ReuseMain may avoid up to 5 additional App IDs. If any extension fails, this version uses separate profiles for all 5 extensions, avoiding 0 additional App IDs. Existing App IDs may already be registered; these are estimates, not measured savings. Separate profiles require confirmation. Extension behavior still needs device validation. You can also register each extension or choose which to remove."
for language in V3AppLanguage.allCases {
    precondition(V3Localization.prose(offer, language: language).contains("these are estimates, not measured savings"))
    let title = V3Localization.prose("Separate Extension Profiles Required", language: language)
    let rendered = V3Localization.prose(prompt, language: language)
    precondition(title == "Experimental ReuseMain could not be used")
    precondition(rendered.contains("app groups differ; keychain groups differ"))
    precondition(rendered.contains("keeps all 5 extensions in this installation request"))
    precondition(rendered.contains("No extension is removed"))
    precondition(rendered.contains("Capability-preservation checks remain enabled"))
    precondition(rendered.contains("Signing and installation still have to complete and can fail"))
    precondition(rendered.contains("Cancel stops this installation request"))
}
precondition(V3Localization.prose(offer.replacingOccurrences(of: "up to 5", with: "up to 6"), language: .english) == missing)
precondition(V3Localization.prose(offer.replacingOccurrences(of: "com.example", with: "bad/id"), language: .english) == missing)
precondition(V3Localization.prose("provider secret error", language: .english) == missing)
precondition(V3Localization.prose("• com.example: arbitrary provider error", language: .english) == missing)
precondition(V3Localization.prose("• bad/id: app groups differ", language: .english) == missing)
precondition(V3Localization.prose(paragraph.replacingOccurrences(of: "up to 5", with: "up to 6"), language: .english) == missing)
precondition(V3Localization.prose("• com.example: app groups differ", language: .hebrew).contains("\u{2066}com.example\u{2069}"))
'''
        with tempfile.TemporaryDirectory() as directory:
            main = pathlib.Path(directory) / 'main.swift'
            main.write_text(harness)
            binary = pathlib.Path(directory) / 'test'
            subprocess.run(['swiftc', str(source), str(main), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

if __name__ == '__main__':
    unittest.main()
