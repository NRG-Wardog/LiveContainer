import copy
import json
from pathlib import Path
import tempfile
import unittest
import analyze
import capture
import intervals
import test_analyze as fixtures

class Strip(unittest.TestCase):
    def fixture(self):return fixtures.Analysis().fixture()[-1]
    def test_complete_cost_receipt(self):
        ids,cost=analyze.strip_metrics(self.fixture());self.assertEqual(len(ids),400);self.assertLess(cost['maxDrawSeconds'],.005)
    def test_missing_draw(self):
        r=self.fixture();del r['draws'][5]
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_reused_id(self):
        r=self.fixture();r['draws'][5]['id']=5
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_bool_id(self):
        r=self.fixture();r['draws'][0]['id']=True
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_invalid_bracket(self):
        r=self.fixture();r['draws'][2]['drawAfterUptime']=0
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_nonfinite_clock(self):
        r=self.fixture();r['draws'][2]['enqueuedUptime']=float('nan')
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_draw_cost_fails_closed(self):
        r=self.fixture();v=r['draws'][2];v['drawBeforeUptime']-=.006;v['tickBeforeUptime']-=.006;v['tickAfterUptime']-=.006
        with self.assertRaisesRegex(ValueError,'overhead'):analyze.strip_metrics(r)
    def test_missing_write_cost(self):
        r=self.fixture();r['complete']['writeCosts'].pop()
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_unfinished_strip(self):
        r=self.fixture();r['complete']['schema']='unfinished'
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_stop_precedes_draw(self):
        r=self.fixture();r['complete']['stoppedUptime']=0
        with self.assertRaises(ValueError):analyze.strip_metrics(r)
    def test_real_batch_reader(self):
        r=self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for i in range(14):
                rows=r['draws'][i*30:(i+1)*30]
                (root/f'strip-{i+1:04d}.json').write_text(json.dumps(dict(schema='p1-strip-batch-v1',batch=i+1,draws=rows,writeBeforeUptime=rows[-1]['journalStartUptime']+.001)))
            (root/'strip-complete.json').write_text(json.dumps(r['complete']))
            self.assertEqual(capture.read_strip(root),r)
            (root/'strip-0002.json').unlink()
            with self.assertRaises(ValueError):capture.read_strip(root)
    def test_partial_interior_batch_rejected(self):
        r=self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for i in range(14):
                rows=r['draws'][i*30:(i+1)*30]
                if i==1:rows.pop()
                (root/f'strip-{i+1:04d}.json').write_text(json.dumps(dict(schema='p1-strip-batch-v1',batch=i+1,draws=rows,writeBeforeUptime=132)))
            (root/'strip-complete.json').write_text(json.dumps(r['complete']))
            with self.assertRaisesRegex(ValueError,'partial interior'):capture.read_strip(root)
    def test_public_strip_uses_no_product_state(self):
        text=(Path(__file__).parent/'app.swift').read_text();strip=text.split('private final class P1ClockStripView: UIView',1)[1].split('@MainActor struct P1VideoPromptScreen',1)[0]
        for token in ['copied','UIPasteboard','V3PromptSection','drawHierarchy','pngData','accessibilityActivate']:
            self.assertNotIn(token,strip)
        self.assertIn('CADisplayLink',strip);self.assertIn('context.fill',strip)
        self.assertNotIn('@Published',strip)
    def test_handshake_precedes_first_copy(self):
        text=(Path(__file__).parent/'ui_tests.swift').read_text()
        self.assertLess(text.index('baselineReady.tap()'),text.index('copy.tap()'))
        text=(Path(__file__).parent/'capture.py').read_text()
        self.assertIn("channel.await_event('baseline-ready',90);channel.calibrate('pre')",text)
    def test_stimulus_thresholds_remain_separate(self):
        text=(Path(__file__).parent/'ui_tests.swift').read_text();self.assertIn('Thread.sleep(forTimeInterval: 0.90)',text)
        text=(Path(__file__).parent/'intervals.py').read_text();self.assertIn('.75 <= spacing < 2',text)

class ProtocolWindow(unittest.TestCase):
    def frames(self):return [dict(index=0,pts=0,endPTS=5)]+[dict(index=i+1,pts=5+i*.05,endPTS=5+(i+1)*.05) for i in range(50)]
    def test_fixed_window_excludes_unusable_launch_only(self):
        selected,bounds=intervals.evidence_window(self.frames(),(-.01,.01),5.2,7)
        self.assertTrue(all(r['pts']>=5 for r in selected));self.assertEqual(bounds,(5.19,7.01))
    def test_ambiguous_boundary_includes_old_gap(self):
        with self.assertRaises(ValueError):intervals.evidence_window(self.frames(),(-.3,.3),5.2,7)
    def test_interior_gap_never_trimmed(self):
        rows=self.frames();rows[10]['endPTS']=rows[14]['pts'];del rows[11:14]
        with self.assertRaises(ValueError):intervals.evidence_window(rows,(0,0),5.2,7)
    def test_missing_window_coverage(self):
        with self.assertRaises(ValueError):intervals.evidence_window(self.frames(),(0,0),5.2,10)
    def test_launch_pts_still_validated(self):
        rows=self.frames();rows[0]['pts']=float('nan')
        with self.assertRaises(ValueError):intervals.evidence_window(rows,(0,0),5.2,7)
    def test_nonfinite_boundary(self):
        with self.assertRaises(ValueError):intervals.evidence_window(self.frames(),(0,0),float('nan'),7)
    def test_discontinuous_raw_inventory(self):
        rows=self.frames();rows[0]['endPTS']=4
        with self.assertRaises(ValueError):intervals.evidence_window(rows,(0,0),5.2,7)

if __name__=='__main__':unittest.main()
