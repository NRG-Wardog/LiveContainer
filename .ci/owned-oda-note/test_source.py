import json, re, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class SourceNoticeTests(unittest.TestCase):
 def test_fixed_nonsecret_notes_localized_in_all_supported_languages(self):
  text=(ROOT/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()
  body=text.split('private var ownedODASourceNotice: String? {',1)[1].split('private var usesRemoteMacAnisetteForSubmit:',1)[0]
  notes=re.findall(r'return "([^"]+)"',body)
  self.assertEqual(len(notes),4)
  self.assertIn('default: return nil',body)
  catalog=json.loads((ROOT/'Resources/Localizable.xcstrings').read_text())['strings']
  for note in notes:
   self.assertNotIn('\\(',note)
   localizations=catalog[note]['localizations']
   self.assertEqual(set(localizations),{'en','he','zh-Hans','zh-Hant'})
   for entry in localizations.values():
    self.assertEqual(entry['stringUnit']['state'],'translated')
    self.assertTrue(entry['stringUnit']['value'].strip())
  self.assertIn('V3LocalizedText(notice)',text)
  self.assertIn('signin.diagnostic.on-device-source',text)
if __name__=='__main__':unittest.main()
