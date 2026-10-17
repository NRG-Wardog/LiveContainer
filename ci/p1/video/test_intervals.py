import copy
import unittest
from intervals import *

class Intervals(unittest.TestCase):
    def exchanges(self):
        return [dict(id=n, stage=s, hostBefore=100+n, appReceive=110+n+.003,
                     appSend=110+n+.004, hostAfter=100+n+.008)
                for n, s in enumerate(['pre']*8+['mid']*8+['post']*8)]
    def markers(self):
        return [dict(id=n+1, stage=s, hostBefore=100+n, hostAfter=100+n+.02,
                     matches=[[n-.02,n+.02]]) for n,s in enumerate(['pre']*3+['mid']*3+['post']*3)]
    def test_causal_clock_interval(self): self.assertAlmostEqual(app_host(self.exchanges())[0],9.996);self.assertAlmostEqual(app_host(self.exchanges())[1],10.003)
    def test_hull_encloses_disjoint_alternatives(self): self.assertEqual(hull([(1,2),(4,5)]),(1,5))
    def test_empty_intersection_rejected(self):
        with self.assertRaises(ValueError): intersection([(1,2),(3,4)])
    def test_nonfinite(self):
        with self.assertRaises(ValueError): interval(0,math.nan)
    def test_bool_not_clock(self):
        with self.assertRaises(ValueError): interval(False,1)
    def test_missing_clock_stage(self):
        with self.assertRaises(ValueError): app_host(self.exchanges()[:6])
    def test_clock_drift_rejected(self):
        x=self.exchanges();x[-1]['appReceive']+=.1;x[-1]['appSend']+=.1
        with self.assertRaises(ValueError): app_host(x)
    def test_wide_clock_rejected(self):
        x=self.exchanges()
        for r in x:r['hostAfter']+=1
        with self.assertRaises(ValueError): app_host(x)
    def test_duplicate_exchange(self):
        x=self.exchanges();x[-1]['id']=0
        with self.assertRaises(ValueError): app_host(x)
    def test_video_offset(self):
        lo,hi=video_host(self.markers());self.assertAlmostEqual(lo,99.98);self.assertAlmostEqual(hi,100.04)
    def test_alternative_video_matches_widen_not_shrink(self):
        x=self.markers()
        for r in x:r['matches'].append([r['matches'][0][0]-1,r['matches'][0][1]-1])
        with self.assertRaises(ValueError): video_host(x)
    def test_duplicate_marker(self):
        x=self.markers();x[-1]['id']=1
        with self.assertRaises(ValueError): video_host(x)
    def test_missing_marker_stage(self):
        with self.assertRaises(ValueError): video_host(self.markers()[:6])
    def test_no_match(self):
        x=self.markers();x[0]['matches']=[]
        with self.assertRaises(ValueError): video_host(x)
    def test_mapping_never_admits(self): self.assertFalse(mapping(self.exchanges(),self.markers())['admissionEligible'])
    def frames(self):
        return [dict(pts=i/20,endPTS=(i+1)/20,label='Copied' if i<40 else 'Copy Details') for i in range(90)]
    def test_lifetime_bounds(self):
        r=lifetime(self.frames(),(-.02,.02),-.1);self.assertGreaterEqual(r['minimumLifetimeSeconds'],1.5);self.assertFalse(r['admissionEligible'])
    def test_premature_expiry(self):
        x=self.frames()
        for f in x[20:]:f['label']='Copy Details'
        with self.assertRaises(ValueError):lifetime(x,(0,0),0)
    def test_unknown_middle_frame(self):
        x=self.frames();x[10]['label']='unknown'
        with self.assertRaises(ValueError):lifetime(x,(0,0),0)
    def test_missing_expiry(self):
        x=self.frames()
        for f in x:f['label']='Copied'
        with self.assertRaises(ValueError):lifetime(x,(0,0),0)
    def test_old_deadline_not_reached(self):
        with self.assertRaises(ValueError):lifetime(self.frames(),(0,0),0,old_event=-.1)
    def test_old_deadline_witness(self): self.assertGreaterEqual(lifetime(self.frames(),(0,0),0,old_event=-.8)['minimumLifetimeSeconds'],1.5)
    def test_uncertainty_cannot_supply_witness(self):
        with self.assertRaises(ValueError):lifetime(self.frames(),(-1,1),0)
    def test_duplicate_pts(self):
        x=self.frames();x[2]['pts']=x[1]['pts']
        with self.assertRaises(ValueError):frame_times(x,(0,0))
    def test_frame_gap(self):
        x=self.frames();del x[4:8]
        with self.assertRaises(ValueError):frame_times(x,(0,0))
    def events(self,scenario='replacement'):
        return [dict(ordinal=i+1,uptime=t,driver=d,clipboardExact=True,payload='safe',expectedPayload='safe',shown=True,changeCount=i,generation=g)
          for i,(t,d,g) in enumerate([(1,'normal-XCTest-tap',0),(2,'experimental-XCTest-coordinate-tap',1 if scenario=='replacement' else 0),(8,'normal-XCTest-third-tap',1 if scenario=='replacement' else 0)])]
    def test_real_spacing(self): self.assertEqual(event_spacing(self.events(),'replacement'),1)
    def test_same_identity_reopen(self): self.assertEqual(event_spacing(self.events('dismissal'),'dismissal'),1)
    def test_missed_window(self):
        x=self.events();x[1]['uptime']=3.1
        with self.assertRaises(ValueError):event_spacing(x,'replacement')
    def test_early_second(self):
        x=self.events();x[1]['uptime']=1.5
        with self.assertRaises(ValueError):event_spacing(x,'replacement')
    def test_third_cannot_replace_second(self):
        with self.assertRaises(ValueError):event_spacing(self.events()[::2],'replacement')
    def test_wrong_generation(self):
        with self.assertRaises(ValueError):event_spacing(self.events('dismissal'),'replacement')
    def test_reused_pasteboard(self):
        x=self.events();x[1]['changeCount']=0
        with self.assertRaises(ValueError):event_spacing(x,'replacement')
    def test_physical_third_required(self):
        x=self.events();x[2]['driver']='assisted'
        with self.assertRaises(ValueError):event_spacing(x,'replacement')
    def test_payload_mismatch(self):
        x=self.events();x[1]['payload']='wrong'
        with self.assertRaises(ValueError):event_spacing(x,'replacement')

if __name__=='__main__':unittest.main()
