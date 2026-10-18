import hashlib
from pathlib import Path
import re
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'video/recovery_ui_tests.swift'
class QueryReuse(unittest.TestCase):
    def setUp(self):self.text=SOURCE.read_text()
    def block(self,start,end):
        first=self.text.index(start);return self.text[first:self.text.index(end,first)]
    def test_original_phone_sequence_and_fresh_metrics_unchanged(self):
        for start,end,sha in [('    @MainActor private func metrics','    @MainActor private func settleOrientation','da8ce5bf2ea70739ca647d357ac440ac9db618c4cb89a9468cf9902e23dd4489'),('    @MainActor func testCapabilityLandscapeTargets','\n}','183550db8bfadf3c9069be064fd335a53f1889e0f7b0cade70f5ec83c478a59d')]:
            self.assertEqual(hashlib.sha256(self.block(start,end).encode()).hexdigest(),sha)
    def test_geometry_predicates_retained_and_frames_local(self):
        body=self.block('    @MainActor private func geometryFailures','    @MainActor @discardableResult')
        expected=['navigation-unavailable','navigation-outside-viewport','ambiguous-or-unavailable-tabs','tabs-outside-viewport','wrong-banner-presence','AX-region-outside-window','AX-region-overlaps-navigation-bar','AX-region-overlaps-navigation-action','AX-region-overlaps-tabs','measured-safe-viewport-exceeds-cap','ambiguous-or-invalid-clipping-viewport','missing-or-inconsistent-layout-receipt','content-hidden-by-navigation']
        self.assertEqual(re.findall(r'failures.append\("([^"]+)"\)',body),expected)
        for frame in ['region.frame','bar.frame','navigation.frame','content.frame']:self.assertEqual(body.count(frame),1)
        self.assertIn('navigation.isHittable',body);self.assertIn('$0.isHittable',body)
    def test_target_observation_is_new_each_attempt_before_drag(self):
        body=self.block('    @MainActor private func seekTarget','    private func productionIdentity')
        self.assertLess(body.index('for attempt in 0..<12'),body.index('let observation = observe(target)'))
        self.assertLess(body.index('let targetFrame ='),body.index('guard interiorDrag'))
        self.assertNotIn('target.frame',body);self.assertNotIn('target.exists',body)
        for token in ['stalled >= 2','reversals > 0 ? 0.25 : 0.45','max(distance, 24)','observation["hittable"] as? Bool == true']:self.assertIn(token,body)
    def test_attachment_reuses_one_validated_snapshot_only(self):
        body=self.block('    @MainActor @discardableResult private func checkGeometry','    @MainActor private func tapRecovery')
        self.assertEqual(body.count('let attachmentTabs = tabSnapshot(app)'),1)
        self.assertLess(body.index('screenshot(app, name: name)'),body.index('let attachmentTabs'))
        self.assertIn('"tabCandidates": attachmentTabs.inventory',body);self.assertIn('"tabs": attachmentTabs.observations',body)
        self.assertNotIn('tabCandidates(app)',body);self.assertNotIn('tabs(app)',body)
        snapshot=self.block('    @MainActor private func tabSnapshot','    @MainActor private func tabCandidates')
        for token in ['queryCount != candidates.count','leaves.count == 1','chosen.path.starts(with:','observe(element)','selectedObservations.count == 4']:self.assertIn(token,snapshot)
    def test_scroll_frame_measured_once_outside_filter(self):
        body=self.block('    @MainActor private func measuredScroll','    @MainActor private func recoveryViewport')
        self.assertEqual(body.count('element.frame'),1);self.assertLess(body.index('let elementFrame'),body.index('scrolls.filter'))

if __name__=='__main__':unittest.main()
