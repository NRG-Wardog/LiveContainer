import copy
import unittest
from analyze import inspect

class Analysis(unittest.TestCase):
    def fixture(self):
        # Host = PTS + 100; app = host + 10. The synthetic fixture is only
        # arithmetic test data, never native pixel evidence.
        exchanges=[dict(id=i,stage=s,hostBefore=100+t,hostAfter=100+t+.008,
            appReceive=110+t+.003,appSend=110+t+.004)
            for i,(s,t) in enumerate([(s,t+j*.05) for s,t in [('pre',0),('mid',6),('post',12)] for j in range(8)])]
        markers=[dict(id=i+1,stage=s,hostBefore=100+t-.01,hostAfter=100+t+.01)
            for i,(s,t) in enumerate([(s,t+j*.15) for s,t in [('pre',.5),('mid',6.5),('post',12.5)] for j in range(3)])]
        frames=[];observations=[]
        for i in range(280):
            pts=i*.05
            marker=next((r['id'] for r in markers if abs(pts-(r['hostBefore']-100+.01))<.01),None)
            frames.append(dict(index=i,pts=pts,endPTS=pts+.05,marker=marker))
            observations.append(dict(index=i,pts=pts,endPTS=pts+.05,label='Copied' if 2.05<=pts<4.15 else 'Copy Details'))
        calibration=dict(schema='p1-video-calibration-v1',exchanges=exchanges,markers=markers)
        decoded=dict(schema='p1-video-decoded-v1',admissionEligible=False,frames=frames,observations=observations,
            screenshots=[dict(id=r['id'],decodedMarker=r['id']) for r in markers],independentScreenshots=[dict(phase=p,label='Copy Details') for p in ['before','after']])
        events=[dict(type='clipboard',ordinal=1,uptime=112,driver='normal-XCTest-tap',clipboardExact=True,payload='safe',expectedPayload='safe',shown=True,changeCount=1,generation=0)]
        events.insert(0,dict(type='start',uptime=109,schema='p1-video-events-v1',scenario='timeout',admissionEligible=False))
        for event in events:
            event.update(enqueuedUptime=event['uptime']+.001,journalStartUptime=event['uptime']+.002,priorWrites=[])
            if event['type']=='clipboard':event.update(callbackBeforeUptime=event['uptime'],callbackAfterUptime=event['uptime']+.0005)
        return calibration,decoded,events,'timeout',dict(schema='p1-video-input-v1',scenario='timeout',firstDriver='normal-XCTest-tap',firstBefore=10,firstAfter=11)
    def test_full_conditional_analysis_never_admits(self):
        result=inspect(*self.fixture());self.assertTrue(result['conditional_feasibility']);self.assertFalse(result['admissionEligible']);self.assertFalse(result['production_ready'])
    def test_missing_screenshot(self):
        args=self.fixture();args[1]['screenshots'].pop()
        with self.assertRaises(ValueError):inspect(*args)
    def test_stale_screenshot(self):
        args=self.fixture();args[1]['screenshots'][0]['decodedMarker']=2
        with self.assertRaises(ValueError):inspect(*args)
    def test_missing_baseline_pixels(self):
        args=self.fixture()
        for f in args[1]['observations']:
            if f['pts']<2:f['label']='unknown'
        with self.assertRaisesRegex(ValueError,'pre-copy'):inspect(*args)
    def test_unknown_copied_pixels(self):
        args=self.fixture()
        for f in args[1]['observations']:
            if f['label']=='Copied':f['label']='unknown'
        with self.assertRaises(ValueError):inspect(*args)
    def test_late_copy_event_not_pixel_marker(self):
        args=self.fixture();args[2][1]['uptime']=120
        with self.assertRaises(ValueError):inspect(*args)
    def test_video_cadence_gap(self):
        args=self.fixture();del args[1]['frames'][50:55]
        with self.assertRaisesRegex(ValueError,'gap'):inspect(*args)
    def test_ambiguous_marker_cannot_gain_precision(self):
        args=self.fixture()
        for f in args[1]['frames']:
            if f['marker'] is None and f['index']%10==0:f['marker']=1
        # Independent markers can constrain one broad alternative; it remains
        # enclosed, rather than arbitrarily picking the first occurrence.
        result=inspect(*args);self.assertFalse(result['admissionEligible'])
    def test_missing_actual_event(self):
        args=list(self.fixture());args[2]=[]
        with self.assertRaises(ValueError):inspect(*args)
    def test_duplicate_actual_event(self):
        args=self.fixture();args[2].append(copy.deepcopy(args[2][1]))
        with self.assertRaises(ValueError):inspect(*args)

if __name__=='__main__':unittest.main()
