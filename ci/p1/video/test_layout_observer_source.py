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


class TargetDragSearchRegression(unittest.TestCase):
    """Evaluate the exact Swift arithmetic; synthetic loss is not native proof."""

    @classmethod
    def setUpClass(cls):
        search = UI.split('private func seekTarget(', 1)[1].split('private func productionIdentity(', 1)[0]
        cls.search = search
        # The strict expression shape binds this model to the actual input recipe.
        # Capture every numeric parameter instead of maintaining another policy.
        pattern = (r'distance = min\(max\(distance, ([\d.]+)\), max\(([\d.]+), '
                   r'\(viewport.height - ([\d.]+)\) \* '
                   r'\(reversals > 0 \? ([\d.]+) : ([\d.]+)\)\)\)')
        matches = re.findall(pattern, search)
        if len(matches) != 1:
            raise AssertionError('The exact bounded Swift search expression changed')
        cls.floor, cls.minimum_cap, cls.inset, cls.reversed_fraction, cls.fraction = map(float, matches[0])

    def distance(self, requested, viewport_height, reversals=0):
        fraction = self.reversed_fraction if reversals > 0 else self.fraction
        return min(max(requested, self.floor), max(self.minimum_cap, (viewport_height-self.inset)*fraction))

    def test_retained_residual_no_longer_requests_ineffective_ten_points(self):
        viewport_height = 152 + 2/3
        target_y, target_height = 114 + 2/3, 51 + 1/3
        visible = viewport_height-target_y
        self.assertAlmostEqual(visible, 38)
        requested = target_y-(viewport_height-44)+4
        self.assertAlmostEqual(requested, 10)
        travel = self.distance(requested, viewport_height)
        self.assertEqual(travel, 24)
        # Model only the observed approximate input deficit; do not claim UIKit
        # guarantees this behavior. The native tap and callback remain required.
        modeled_old_offset = max(0, requested-10)
        modeled_new_offset = max(0, travel-10)
        self.assertAlmostEqual(modeled_old_offset, 0)
        self.assertGreaterEqual(min(target_height, visible+modeled_new_offset), 44)

    def test_cap_wins_in_tiny_eligible_viewport(self):
        for height in [48, 49, 60, 70]:
            for reversals in [0, 1, 4]:
                travel = self.distance(10, height, reversals)
                fraction = self.reversed_fraction if reversals else self.fraction
                cap = max(8, (height-24)*fraction)
                self.assertLessEqual(travel, cap)
                self.assertLess(travel, 24)
                self.assertLessEqual(travel, (height-24)*0.6)

    def test_direction_reversal_retains_smaller_cap(self):
        height = 152+2/3
        self.assertAlmostEqual(self.distance(1000, height), (height-24)*0.45)
        self.assertAlmostEqual(self.distance(1000, height, 1), (height-24)*0.25)
        self.assertEqual(self.distance(10, height, 1), 24)
        self.assertIn('if let previous = previousDown, previous != down { reversals += 1 }', self.search)

    def test_floor_cannot_exceed_existing_safe_interior_recipe(self):
        for height in range(48, 401):
            for requested in [0, 1, 10, 12, 24, 50, 1000]:
                for reversals in [0, 1]:
                    self.assertLessEqual(self.distance(requested, height, reversals), (height-24)*0.6)
        self.assertIn('interior.height >= 24', UI)
        self.assertIn('min(max(8, distance ?? interior.height * 0.45), interior.height * 0.6)', UI)

    def test_persistent_zero_progress_still_stops(self):
        self.assertIn('for attempt in 0..<12', self.search)
        self.assertIn('abs(offset[1] - previous) <= 0.5 { stalled += 1 } else { stalled = 0 }', self.search)
        self.assertIn('if stalled >= 2 { break }', self.search)
        self.assertLess(self.search.index('if stalled >= 2 { break }'), self.search.index('distance = min(max(distance, 24)'))
        self.assertIn('Target cannot be safely reached by bounded physical dragging:', self.search)

    def test_target_acceptance_and_progress_evidence_remain_strict(self):
        for text in ['visible.width >= min(44, target.frame.width)',
                     'visible.height >= min(44, target.frame.height)', 'target.isHittable',
                     'disjoint(visible, $0.frame)']:
            self.assertIn(text, self.search)
        for text in ['"offsetDelta": afterOffset[1] - beforeOffset[1]',
                     '"progress": abs(afterOffset[1] - beforeOffset[1]) > 0.5',
                     '"driver": "ordinary-XCTest-controlled-coordinate-drag"']:
            self.assertIn(text, UI)

if __name__=='__main__':unittest.main()
