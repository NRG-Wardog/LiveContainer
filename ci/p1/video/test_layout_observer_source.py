"""Portable contracts for the passive layout harness, not native proof."""
import hashlib
import os
from pathlib import Path
import re
import unittest
import extract

HERE=Path(__file__).parent
FIXTURE=(HERE/'recovery.swift').read_text()
UI=(HERE/'recovery_ui_tests.swift').read_text()
SOURCE=(Path(os.environ['MAINTAINED_LIVE_CONTAINER_TEST_SOURCE'])/'LiveContainerSwiftUI/Views/V3UnifiedShell.swift').read_text()

class LayoutObserverSource(unittest.TestCase):
    def test_production_fragments_remain_exact(self):
        rendered=extract.render(SOURCE,FIXTURE)
        for fragment in extract.fragments(SOURCE).values():self.assertIn(fragment.rstrip('\n'),rendered)
        self.assertEqual(hashlib.sha256(SOURCE.encode()).hexdigest(),extract.SOURCE_SHA256)
    def test_probe_is_outside_exact_modifier(self):
        self.assertLess(FIXTURE.index('__P1_RECOVERY_MODIFIER__'),FIXTURE.index('.background(GeometryReader { offered in'))
        self.assertIn('offered.frame(in: .global)',FIXTURE)
        self.assertIn('offeredSize: offered.size',FIXTURE)
    def test_probe_does_not_change_hit_testing_or_scroll_state(self):
        self.assertIn('isUserInteractionEnabled = false',FIXTURE)
        self.assertIn('.frame(width: 1, height: 1).allowsHitTesting(false)',FIXTURE)
        for forbidden in ['setContentOffset','contentInset =','scrollRectToVisible','isScrollEnabled =','safeAreaInsets =']:
            self.assertNotIn(forbidden,FIXTURE)
    def test_measured_clipping_ancestry_and_native_coordinates(self):
        for text in ['scroll.safeAreaLayoutGuide.layoutFrame','scroll.safeAreaInsets','ancestor.clipsToBounds',
                     'ancestor.convert(ancestor.bounds, to: window)','"localToWindow"','"localSafeAreaFrame"',
                     'safe.intersection(clipped).intersection(offeredFrame)']:
            self.assertIn(text,FIXTURE)
    def test_no_content_size_cap_or_guessed_insets(self):
        self.assertNotIn('contentSize',FIXTURE)
        self.assertIn('CGFloat(min(320, offeredSize[1] * 0.4) + 1)',UI)
        self.assertNotIn('viewport.height * 0.4',UI)
    def test_unique_correspondence_is_required(self):
        self.assertIn('matched.count == 1',UI)
        self.assertIn('sameFrame(frame, element.frame)',UI)
        self.assertIn('sameFrame(viewport, safe.intersection(clipped).intersection(offered))',UI)
    def test_clock_domains_are_not_subtracted(self):
        self.assertNotIn('systemUptime - finished',UI)
        self.assertNotIn('finished <= ProcessInfo.processInfo.systemUptime',UI)
        self.assertIn('second > first',UI)
        self.assertIn('receipt["causalPrevious"] = previous',UI)
        self.assertIn('receipt["runnerRequestBracket"]',UI)
    def test_getter_receipts_bind_session_window_and_context(self):
        for key in ['processSession','windowObservationID','interfaceOrientation','selectedTab','offeredFrame']:
            self.assertIn('previous["'+key+'"]',UI)
        self.assertIn('observationSequence += 1',FIXTURE)
    def test_existing_labels_receive_only_ids(self):
        for title,symbol in [('Home','house.fill'),('Apps','square.stack.3d.up.fill'),('Sources','books.vertical'),('Settings','gearshape.fill')]:
            self.assertIn('Label("'+title+'", systemImage: "'+symbol+'").accessibilityIdentifier("p1-tab-'+title+'")',FIXTURE)
        self.assertIn('leaves.count == 1',UI)
        self.assertIn('chosen.path.starts(with: $0.path)',UI)
        self.assertIn('app.snapshot()',UI)
        self.assertIn('actualTabs[1].tap()',UI)
        self.assertIn('returnTabs[0].tap()',UI)
        self.assertIn('Actual Apps tab selection did not change',UI)
    def test_no_generic_edge_swipes_remain(self):
        self.assertNotIn('.swipeDown()',UI);self.assertNotIn('.swipeUp()',UI)
        self.assertIn('visible.insetBy(dx: 12, dy: 12)',UI)
        self.assertIn('press(forDuration: 0.05,',UI)
        self.assertIn('app.state == .runningForeground',UI)
    def test_pixels_cover_screen_and_preserve_orientation(self):
        self.assertIn('XCUIScreen.main.screenshot()',UI)
        self.assertNotIn('app.screenshot()',UI)
        for key in ['imageOrientation','pixelWidth','pixelHeight','tabCandidates','predicateFailures']:
            self.assertIn('"'+key+'"',UI)
    def test_failed_observers_leave_diagnostics(self):
        self.assertIn('retainLayoutFailure',UI)
        self.assertIn('"hierarchy": app.debugDescription',UI)
        self.assertIn('"rawProbe": observe(',UI)
    def test_all_original_cases_and_actions_remain(self):
        for method in ['testRecoveryBranchesDefault','testRecoveryBranchesLargest','testRecoveryCompactLandscape','testRecoveryStateAndSizeTransitions']:
            self.assertIn('func '+method+'()',UI)
        for text in ['Resume Status Check','Inspect result','Copy Diagnostics','transition-largest','transition-standard-with-banner','transition-kind-']:
            self.assertIn(text,UI)
    def test_swift_fraction_literals_have_leading_zero(self):
        self.assertNotRegex(FIXTURE+UI,r'(?<![A-Za-z0-9_])\.\d+')

if __name__=='__main__':unittest.main()
