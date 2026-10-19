import unittest
from pathlib import Path
import render_fixture as r
ROOT=Path(__file__).resolve().parents[2]/'window-capture-candidate'

class FixtureTests(unittest.TestCase):
    def sources(self):
        return ((ROOT/'ci/p1/video/app.swift').read_text(),(ROOT/'ci/p1/preflight/window_fixture.swift').read_text(),Path(__file__).with_name('registration.swift').read_text())
    def test_only_explicit_fixture_delta(self):
        app,packet,overlay=self.sources();generated=r.render(app,packet,overlay)
        prefix=generated[:len(generated)-len('\n'+r.packet_enum(packet)+'\n'+overlay)]
        self.assertEqual(prefix.replace(r.METHOD,'').replace(r.OVERLAY,'').replace(r.START_HOOK,''),app)
        self.assertIn('.allowsHitTesting(false)',overlay)
        self.assertNotIn('CADisplayLink',overlay)
        self.assertNotIn('UIPasteboard',overlay)
    def test_generated_candidate_and_source_binding_are_current(self):
        import json
        app,packet,overlay=self.sources()
        generated=Path(__file__).with_name('app.swift').read_text()
        self.assertEqual(generated,r.render(app,packet,overlay))
        binding=json.loads(Path(__file__).with_name('source-binding.json').read_text())
        self.assertEqual(binding['candidateSHA256'],r.sha(generated))
        self.assertEqual(binding['registrationSourceSHA256'],r.sha(overlay))
        self.assertFalse(binding['nativeCompiled']);self.assertFalse(binding['nativeExecuted'])
        self.assertFalse(binding['admissionEligible'])

    def test_packet_enum_exact_reviewed_bytes(self):
        _,packet,_=self.sources();enum=r.packet_enum(packet)
        self.assertIn('full 128-bit nonce',enum)
        self.assertIn('checksum',enum)
    def test_source_drift_rejected(self):
        app,packet,overlay=self.sources()
        with self.assertRaises(ValueError):r.render(app+'\n',packet,overlay)
        with self.assertRaises(ValueError):r.render(app,packet+'\n',overlay)
    def test_four_static_identity_anchors_and_cost_receipts(self):
        overlay=self.sources()[2]
        self.assertIn('ForEach(1...4',overlay)
        self.assertIn('p1-direct-anchor-',overlay)
        self.assertIn('draws <= 64',overlay)
        self.assertIn('"beforeUptime":before',overlay)
        self.assertIn('"afterUptime":after',overlay)
        self.assertIn('"displayTimeEstablished":false',overlay)
    def test_four_isolated_features_and_source_locality(self):
        overlay=self.sources()[2]
        self.assertIn('p1-direct-feature-',overlay)
        self.assertIn('.frame(width:2,height:2)',overlay)
        self.assertIn('bounds.width == 2, bounds.height == 2',overlay)
        self.assertIn('UIColor(red:1,green:0,blue:1,alpha:1)',overlay)
        self.assertEqual(overlay.count('clipsToBounds = true'),2)
        self.assertEqual(overlay.count('"source":"packet", "anchor":ordinal'),2)
        self.assertEqual(overlay.count('"source":"feature", "anchor":ordinal'),2)
        self.assertIn('geometry.size.width-5',overlay)
        self.assertIn('geometry.size.height-5',overlay)
        self.assertIn('whole\n// actual AX rectangle',overlay)

    def test_flush_after_start_event_before_polling(self):
        app,packet,overlay=self.sources();generated=r.render(app,packet,overlay)
        start=generated.index('let journal = try P1VideoJournal')
        event=generated.index('journal.append(["type": "start"',start)
        attach=generated.index(r.START_HOOK,event)
        polling=generated.index(r.START_ANCHOR,attach)
        self.assertLess(start,event);self.assertLess(event,attach);self.assertLess(attach,polling)
        self.assertEqual(generated.count(r.START_HOOK),1)
        self.assertIn('directAnchorReceipts.append(row)',generated)
        self.assertNotIn('func directAnchorDraw(_ row: [String: Any]) { journal?.append(row) }',generated)
    def test_bounded_latched_buffer_and_flush_before_inventory(self):
        overlay=self.sources()[2]
        self.assertIn('private static let maxDrawRows = 520',overlay)
        self.assertIn('guard drawRows < Self.maxDrawRows',overlay)
        self.assertIn('guard !failed else { return }; failed = true',overlay)
        self.assertIn('guard sink == nil else { fail(',overlay)
        attach=overlay.split('func attach(',1)[1].split('private func initialInventoryIfReady',1)[0]
        self.assertLess(attach.index('for row in pending { value(row) }'),attach.index('initialInventoryIfReady()'))
        self.assertIn('firstDraws == Set(["packet", "feature"]',overlay)
        self.assertIn('"retainedEvidenceRequired":true',overlay)
    def test_success_and_error_draws_have_canonical_clock(self):
        overlay=self.sources()[2]
        receipts=overlay.split('receipt(["type":"direct-anchor-draw"')[1:]
        self.assertEqual(len(receipts),4)
        for receipt in receipts:
            row=receipt.split('])',1)[0]
            for field in ('"uptime":before','"clock":"app-ProcessInfo.systemUptime"',
                          '"timingMeaning":"fixture-draw-only"','"displayTimeEstablished":false',
                          '"admissionEligible":false'):
                self.assertIn(field,row)

if __name__=='__main__':unittest.main()
