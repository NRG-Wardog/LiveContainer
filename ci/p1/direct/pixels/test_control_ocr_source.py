import unittest
from pathlib import Path
import hashlib

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=ROOT.parent/'window-capture-candidate/ci/p1/video/decode.swift'

class Tests(unittest.TestCase):
    def test_original_recognition_predicate_retained(self):
        old=ORIGINAL.read_text();new=(ROOT/'pixels/control_ocr.swift').read_text()
        start='    let observations: [[String: Any]]'
        end='    let name = String(format:'
        block=old[old.index(start):old.index(end)]
        self.assertIn(block,new)
        self.assertIn('request.recognitionLanguages = ["en-US"]; request.usesLanguageCorrection = false',new)
        self.assertIn('request.recognitionLevel = .accurate',new)
    def test_actual_pixel_binding_and_unknown_not_absence(self):
        new=(ROOT/'pixels/control_ocr.swift').read_text()
        for text in ('hash(packed) == frame["packedSHA256"]','hash(control) == frame["controlSHA256"]',
                     '"absenceEstablished": false','shouldInterpolate: false','"record"] = record',
                     'frame-%05d.rois.bgra','record - 1','O_NOFOLLOW | O_NONBLOCK'):
            self.assertIn(text,new)
        self.assertNotIn('"expectedLabel"',new)

if __name__=='__main__':unittest.main()
