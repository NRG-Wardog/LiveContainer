"""Portable source contracts only; these do not compile/run XCTest or prove timing.

The independently reviewed host protocol tests cover its request generation and
receipt validation. These guards keep the runner's critical source boundaries
visible without substituting a Python model for native execution.
"""
from pathlib import Path
import re
import unittest


HERE = Path(__file__).resolve().parent
SOURCE = (HERE / "runner_ui_tests.swift").read_text(encoding="utf-8")


def between(start, end):
    return SOURCE.split(start, 1)[1].split(end, 1)[0]


class RunnerSourceContracts(unittest.TestCase):
    def test_separate_async_main_actor_entry(self):
        self.assertIn("final class P1ScreenshotCapabilityUITests: XCTestCase", SOURCE)
        self.assertIn("@MainActor func testScreenshotCalibrationCapability() async throws", SOURCE)
        self.assertEqual(re.findall(r"func (test\w+)\(", SOURCE), ["testScreenshotCalibrationCapability"])
        self.assertNotIn("P0SignInUITests", SOURCE)

    def test_session_is_required_and_bound_to_launch(self):
        self.assertIn('environment["P1_CAPABILITY_SESSION"]', SOURCE)
        self.assertGreaterEqual(SOURCE.count('"^[0-9a-f]{32}$"'), 2)
        self.assertIn('app.launchArguments = ["--scenario", "capability", "--session", session]', SOURCE)
        self.assertIn('row["session"] as? String == session', SOURCE)
        self.assertIn('"session": session', SOURCE)

    def test_manifest_identifies_actual_runner_bundle(self):
        self.assertIn("guard let identifier = Bundle.main.bundleIdentifier", SOURCE)
        manifest = between('try files.publish("runner.json"', "private func saveCapture")
        self.assertIn('"runnerBundleIdentifier": identifier', manifest)
        self.assertNotRegex(manifest, r"com\.[a-zA-Z]")
        for key, value in [("expectedRequests", 35), ("clocksPerPhase", 8), ("capturesPerPhase", 3)]:
            self.assertIn(f'"{key}": {value}', manifest)

    def test_channel_requires_fresh_real_session_directory(self):
        self.assertIn('mkdirat(parentFD, session, 0o700) == 0', SOURCE)
        self.assertIn('"fresh session directory required"', SOURCE)
        self.assertIn('openat(parentFD, session, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)', SOURCE)
        self.assertIn('open(documents.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)', SOURCE)
        self.assertNotIn("removeItem", SOURCE)

    def test_files_use_descriptor_relative_no_follow_and_no_clobber(self):
        self.assertIn('openat(directory, "request.json", O_RDONLY | O_NOFOLLOW | O_NONBLOCK)', SOURCE)
        self.assertIn("O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW", SOURCE)
        self.assertIn("info.st_nlink == 1", SOURCE)
        self.assertIn("(info.st_mode & S_IFMT) == S_IFREG", SOURCE)
        self.assertIn("AT_SYMLINK_NOFOLLOW", SOURCE)
        self.assertIn('!name.contains("..")', SOURCE)

    def test_requests_are_bounded_and_canonical(self):
        self.assertIn("info.st_size > 0 && info.st_size <= 8192", SOURCE)
        self.assertIn("try capabilityJSON(row) == data", SOURCE)
        self.assertIn("[.sortedKeys, .withoutEscapingSlashes]", SOURCE)
        self.assertIn("guard Set(row.keys) == keys", SOURCE)
        self.assertIn("CFGetTypeID(number) != CFBooleanGetTypeID()", SOURCE)
        self.assertIn("number.doubleValue == Double(number.intValue)", SOURCE)

    def test_exact_sequential_ids_and_unchanged_request_polling(self):
        self.assertIn("number.intValue == previousID + 1", SOURCE)
        self.assertIn("(1...35).contains(number.intValue)", SOURCE)
        self.assertIn("bytes != previousBytes", SOURCE)
        self.assertIn("previousBytes = bytes; previousID = command.id", SOURCE)
        self.assertNotIn("id > previousID", SOURCE)

    def test_phase_order_requires_eight_clocks_then_three_captures(self):
        parse = between("private func parse(", "private func publish(")
        self.assertIn('phase = ["pre", "mid", "post"][(id - 1) / 11]', parse)
        self.assertIn("let position = (id - 1) % 11", parse)
        self.assertIn("if position < 8", parse)
        self.assertIn('guard kind == "clock"', parse)
        self.assertIn("ordinal = position - 7", parse)
        self.assertIn('guard kind == "capture"', parse)
        self.assertIn('row["phase"] as? String == phase', parse)
        self.assertIn("value.doubleValue == Double(ordinal)", parse)
        self.assertIn("CFGetTypeID(value) != CFBooleanGetTypeID()", parse)

    def test_after_screenshot_precedes_explicit_hash_ack(self):
        parse = between("private func parse(", "private func publish(")
        self.assertIn("else if id == 34", parse)
        self.assertIn('guard kind == "after"', parse)
        self.assertIn('guard kind == "complete"', parse)
        self.assertIn('row["appStripCompleteSHA256"] as? String', parse)
        self.assertIn('"^[0-9a-f]{64}$"', parse)
        self.assertIn('row["hostVerifiedStripComplete"] as? NSNumber', parse)
        self.assertIn("CFGetTypeID(verified) == CFBooleanGetTypeID(), verified.boolValue", parse)

    def test_raw_request_retained_before_any_response(self):
        poll = between("private func poll()", "final class P1ScreenshotCapabilityUITests")
        self.assertLess(poll.index('"request-%04d.json"'), poll.index('if command.kind == "clock"'))
        self.assertIn("bytes)", poll)

    def test_response_is_durable_before_atomic_publication(self):
        publish = between("private func publish(_ command", "private func poll()")
        self.assertLess(publish.index('"response-%04d.json"'), publish.index('files.publish("response.json", data)'))
        self.assertIn('"runnerReceive": received, "runnerSend": try capabilityNow()', publish)
        immutable = between("func immutable(", "func publish(_ name")
        self.assertIn("fsync(output) == 0, fsync(fd) == 0", immutable)
        publication = between("func publish(_ name", "private struct P1CapabilityCommand")
        self.assertLess(publication.index("try immutable(temporary, data)"), publication.index("renameat("))
        self.assertIn("fsync(fd) == 0", publication)

    def test_complete_is_retained_before_test_can_return(self):
        poll = between("private func poll()", "final class P1ScreenshotCapabilityUITests")
        self.assertLess(poll.index('files.publish("completion.json"'), poll.index("completed = true"))
        self.assertLess(poll.index('extra: ["completion": "completion.json"]'), poll.index("completed = true"))
        self.assertIn('"host; runner does not read app container"', poll)
        test = SOURCE.split("func testScreenshotCalibrationCapability()", 1)[1]
        self.assertIn("if state.complete { return }", test)
        self.assertEqual(len(re.findall(r"\breturn\b", test)), 1)

    def test_finite_clock_and_bounded_async_wait(self):
        self.assertIn("value.isFinite && value > 0", SOURCE)
        self.assertIn("let deadline = try capabilityNow() + 180", SOURCE)
        self.assertIn("while try capabilityNow() < deadline", SOURCE)
        self.assertIn("try await Task.sleep(nanoseconds: 50_000_000)", SOURCE)
        self.assertIn("host completion acknowledgement not received within 180 seconds", SOURCE)
        self.assertNotIn("Thread.sleep", SOURCE)
        self.assertNotIn("XCTWaiter", SOURCE)

    def test_clock_requests_stay_on_background_queue(self):
        self.assertIn('DispatchQueue(label: "p1.capability.runner"', SOURCE)
        self.assertIn("DispatchSource.makeTimerSource(queue: self.queue)", SOURCE)
        poll = between("private func poll()", "final class P1ScreenshotCapabilityUITests")
        clock_branch = poll.split('if command.kind == "clock"', 1)[1].split('else if', 1)[0]
        self.assertIn("try publish(command, received: received)", clock_branch)
        self.assertNotIn("MainActor", clock_branch)
        self.assertNotIn("capture(", clock_branch)
        self.assertIn("Task { @MainActor in", poll)

    def test_acquisition_bracket_contains_only_public_screenshot(self):
        self.assertEqual(SOURCE.count("app.screenshot()"), 1)
        bracket = between("let acquisitionBefore = try capabilityNow()", "let acquisitionAfter = try capabilityNow()")
        self.assertEqual(bracket.strip(), "let screenshot = app.screenshot()")
        encoding = between("let encodingBefore = try capabilityNow()", "let encodingAfter = try capabilityNow()")
        self.assertEqual(encoding.strip(), "let png = screenshot.pngRepresentation")
        self.assertNotIn("XCTAttachment(screenshot:", SOURCE)

    def test_original_png_has_separate_attachment_and_durable_write(self):
        self.assertIn('XCTAttachment(data: png, uniformTypeIdentifier: "public.png")', SOURCE)
        self.assertIn("attachment.lifetime = .keepAlways", SOURCE)
        self.assertIn("try files.immutable(pngName, capture.png)", SOURCE)
        self.assertIn("SHA256.hash(data: capture.png)", SOURCE)
        self.assertIn("png.count <= 32 * 1024 * 1024", SOURCE)
        for prefix in ["acquisition", "encoding", "attachment", "pngWrite"]:
            self.assertIn(f'"{prefix}Before"', SOURCE)
            self.assertIn(f'"{prefix}After"', SOURCE)

    def test_before_after_copy_identity_and_real_geometry_retained(self):
        for text in ['query.count == 1', 'copy.isEnabled', 'copy.isHittable', 'copy.label == "Copy Details"',
                     'copy.identifier == "signin.prompt.copy-details"', '"selected": copy.isSelected',
                     '"elementType": copy.elementType.rawValue', '"value": value', '"frame": try rectangle(copy.frame)']:
            self.assertIn(text, SOURCE)
        for key in ["copyBefore", "copyAfter", "markerFrameBefore", "markerFrameAfter", "windowFrameBefore", "windowFrameAfter"]:
            self.assertIn(f'"{key}"', SOURCE)
        self.assertIn("value.allSatisfy({ $0.isFinite })", SOURCE)
        self.assertIn("frame.width > 0, frame.height > 0", SOURCE)

    def test_independent_baseline_is_saved_before_physical_fixture_tap(self):
        test = SOURCE.split("func testScreenshotCalibrationCapability()", 1)[1]
        self.assertLess(test.index("let before = try copyIdentity(app)"), test.index('kind: "baseline"'))
        self.assertLess(test.index("try await channel.saveBaseline(baseline)"), test.index("ready.tap()"))
        self.assertLess(test.index("ready.tap()"), test.index("try await channel.start("))
        self.assertEqual(re.findall(r"\b\w+\.tap\(\)", SOURCE), ["ready.tap()"])
        self.assertIn('ready.label == "Baseline ready"', SOURCE)
        self.assertIn('row["png"] = "capture-baseline.png"', SOURCE)
        self.assertIn('row["receipt"] = "capture-baseline.json"', SOURCE)

    def test_failures_are_retained_and_never_made_successful(self):
        self.assertIn('files.immutable("error.json", data)', SOURCE)
        self.assertIn("if let failure = state.failure { throw P1CapabilityError(failure) }", SOURCE)
        self.assertIn("await channel.stopWithError(String(describing: error))", SOURCE)
        self.assertIn("guard self.failure == nil else { return }", SOURCE)
        self.assertEqual(SOURCE.count("completed = true"), 1)

    def test_no_production_state_private_api_or_timing_claim(self):
        for forbidden in ["copiedGeneration", "copiedUntil", "copyDetails(", "UIPasteboard", "XCUIDevice.shared.perform",
                          "performSelector", "NSSelectorFromString", "value(forKey:", "XCEventGenerator",
                          "XCUIScreen", "UIGraphics", "layer.render", "drawHierarchy", "usleep(", "sleep(forTimeInterval"]:
            self.assertNotIn(forbidden, SOURCE)
        self.assertIn('"clockEquivalenceAssumed": false', SOURCE)
        self.assertIn('"admissionEligible": false', SOURCE)
        self.assertIn('"timingFeasibilityEstablished": false', SOURCE)
        self.assertNotIn('"admissionEligible": true', SOURCE)
        self.assertNotIn("appReceive", SOURCE)

    def test_swift_fraction_literals_have_leading_zero(self):
        self.assertEqual(re.findall(r"(?<![\w.])\.[0-9]+", SOURCE), [])


if __name__ == "__main__":
    unittest.main()
