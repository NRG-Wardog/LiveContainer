from hashlib import sha256
import json
from pathlib import Path
import re
import unittest

import build_candidate as build


class SourceDeltaTests(unittest.TestCase):
    def setUp(self):
        self.original, self.primitives = build.source_bytes()
        self.candidate = (build.HERE / "ui_tests.swift").read_text()
        self.observer = (build.HERE / "observer.swift").read_text()
        self.manifest = json.loads((build.HERE / "source-binding.json").read_text())

    def test_original_sources_remain_sealed(self):
        self.assertEqual(build.digest(self.original.encode()), build.ORIGINAL_SHA)
        self.assertEqual(build.digest((build.SOURCE / "preflight/runner_ui_tests.swift").read_bytes()), build.PREFLIGHT_SHA)

    def test_primitives_are_verbatim(self):
        embedded = self.candidate.split(build.PRIMITIVES_BEGIN, 1)[1].split(build.PRIMITIVES_END, 1)[0]
        self.assertEqual(embedded, self.primitives)
        self.assertEqual(build.digest(embedded.encode()), build.PRIMITIVES_SHA)

    def test_observer_is_the_exact_reviewable_standalone_source(self):
        embedded = self.candidate.split(build.OBSERVER_BEGIN, 1)[1].split(build.OBSERVER_END, 1)[0]
        self.assertEqual(embedded, self.observer)

    def test_only_documented_method_and_import_delta(self):
        restored = self.candidate.replace(build.PRIMITIVES_BEGIN + self.primitives + build.PRIMITIVES_END + "\n", "", 1)
        restored = restored.replace(build.OBSERVER_BEGIN + self.observer + build.OBSERVER_END + "\n", "", 1)
        restored = restored.replace(build.IMPORTS, "", 1)
        restored = restored.replace(build.START, "", 1).replace(build.DIRECT_LAUNCH, build.LAUNCH, 1)
        restored = restored.replace(build.HOOK, "", 1)
        self.assertEqual(restored.encode(), self.original.encode())

    def test_exact_original_suffix_from_baseline_tap(self):
        self.assertEqual(self.candidate.split(build.BASELINE, 1)[1], self.original.split(build.BASELINE, 1)[1])

    def test_guard_is_immediately_before_original_baseline_bracket(self):
        self.assertIn(build.HOOK + build.BASELINE, self.candidate)
        self.assertEqual(self.candidate.count(build.HOOK), 1)

    def test_original_three_test_entrypoints_unchanged(self):
        pattern = r'    @MainActor func testProbe.*?\n'
        self.assertEqual(re.findall(pattern, self.candidate), re.findall(pattern, self.original))

    def test_observer_has_no_production_input_or_screenshot_calls(self):
        # The existing before/after screenshot and all original taps remain in
        # the original method. The new observer only reads AX and its channel.
        for forbidden in (".tap(", ".press(", ".swipe", ".launch(", ".terminate(", ".screenshot(",
                          "CGRequestScreenCaptureAccess", "simctl", "Process()", "UIHostingController"):
            self.assertNotIn(forbidden, self.observer)

    def test_feature_geometry_is_actual_ax_and_not_source_nominal(self):
        self.assertIn('let identifier = "p1-direct-feature-\\(ordinal)"', self.observer)
        self.assertIn('let frame = element.frame, values = try rectangle(frame)', self.observer)
        self.assertIn('anchorFrames + featureFrames', self.observer)
        self.assertIn('"sourceLocalityEstablished": false', self.observer)
        self.assertIn('"features": features', self.observer)

    def test_ack_is_retained_before_validation_and_receipt_before_return(self):
        read = self.observer.index('if let data = try channel.readRequest()')
        retain = self.observer.index('channel.immutable("acknowledgement-received.json"', read)
        validate = self.observer.index('validateAcknowledgement(data,', retain)
        persist = self.observer.index('channel.immutable("observer-receipt.json"', validate)
        recheck = self.observer.index('try inBudget()', persist)
        release = self.observer.index('return true', recheck)
        self.assertLess(read, retain); self.assertLess(retain, validate)
        self.assertLess(persist, recheck); self.assertLess(recheck, release)

    def test_native_allowance_not_extended_and_wait_is_bounded(self):
        self.assertIn('static let waitSeconds = 120.0', self.observer)
        self.assertIn('static let methodSeconds = 240.0', self.observer)
        self.assertIn('min(entered + waitSeconds, methodStarted + methodSeconds)', self.observer)
        self.assertIn('now < deadline', self.observer)
        self.assertIn('Thread.sleep(forTimeInterval: min(0.05, remaining))', self.observer)

    def test_hash_manifest_matches_current_candidate(self):
        self.assertEqual(self.manifest["candidateSHA256"], build.digest(self.candidate.encode()))
        self.assertEqual(self.manifest["observerSHA256"], build.digest(self.observer.encode()))
        self.assertFalse(self.manifest["nativeCompiled"])
        self.assertFalse(self.manifest["nativeExecuted"])
        self.assertFalse(self.manifest["admissionEligible"])


if __name__ == "__main__":
    unittest.main()
