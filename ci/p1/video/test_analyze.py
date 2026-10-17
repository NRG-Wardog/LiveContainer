import copy
import unittest
from analyze import inspect

class Analysis(unittest.TestCase):
    def fixture(self):
        # Host = PTS + 100; app = host + 10. The synthetic fixture is only
        # arithmetic test data, never native pixel evidence.
        exchanges=[dict(id=i,stage=s,hostBefore=100+t,hostAfter=100+t+.008,
            appReceive=110+t+.003,appSend=110+t+.004)
            for i,(s,t) in enumerate([(s,t+j*.05) for s,t in [('pre',.3),('mid',14.3),('post',16.3)] for j in range(8)])]
        markers=[dict(id=i+1,stage=s,hostBefore=100+t-.01,hostAfter=100+t+.01)
            for i,(s,t) in enumerate([(s,t+j*.15) for s,t in [('pre',.8),('mid',14.8),('post',16.8)] for j in range(3)])]
        frames=[];observations=[]
        for i in range(400):
            pts=i*.05
            marker=i+1
            frames.append(dict(index=i,pts=pts,endPTS=pts+.05,marker=marker))
            observations.append(dict(index=i,pts=pts,endPTS=pts+.05,label='Copied' if 2.05<=pts<4.15 else 'Copy Details'))
        calibration=dict(schema='p1-video-calibration-v1',exchanges=exchanges,markers=markers)
        decoded=dict(schema='p1-video-decoded-v1',admissionEligible=False,frames=frames,observations=observations,
            screenshots=[dict(id=r['id'],decodedMarker=round((r['hostBefore']-100+.01)/.05)+1) for r in markers],independentScreenshots=[dict(phase=p,label='Copy Details',decodedMarker=1 if p=='before' else 390) for p in ['before','after']])
        events=[dict(type='clipboard',ordinal=1,uptime=112,driver='normal-XCTest-tap',clipboardExact=True,payload='safe',expectedPayload='safe',shown=True,changeCount=1,generation=0)]
        events.insert(0,dict(type='start',uptime=109,schema='p1-video-events-v1',scenario='timeout',admissionEligible=False))
        events.insert(1,dict(type='baseline-ready',uptime=110.1,afterUptime=110.101,driver='normal-XCTest-fixture-ready-tap'))
        events.extend([dict(type='command',kind='ready',phase='ready',uptime=111.5,afterUptime=111.501),
            dict(type='window-end',uptime=124),dict(type='command',kind='mid',phase='calibrating-mid',uptime=124.1,afterUptime=124.101),
            dict(type='command',kind='third',phase='third-ready',uptime=125.5,afterUptime=125.501),dict(type='post-ready',uptime=126),
            dict(type='command',kind='post',phase='calibrating-post',uptime=126.1,afterUptime=126.101),
            dict(type='command',kind='finish',phase='finished',uptime=127.5,afterUptime=127.501)])
        commands=[];clock_index=0
        expected=['clock']*8+['ready','mid']+['clock']*8+['third','post']+['clock']*8+['finish']
        for identifier,kind in enumerate(expected,1):
            if kind=='clock':
                exchange=exchanges[clock_index];clock_index+=1;exchange['id']=identifier
                response={k:exchange[k] for k in ['id','appReceive','appSend']}
                hb,ha=exchange['hostBefore'],exchange['hostAfter']
            else:
                event=next(r for r in events if r.get('kind')==kind);event['id']=identifier
                response=dict(id=identifier,phase=event['phase'],appReceive=event['uptime'],appSend=event['afterUptime']+.001)
                hb,ha=event['uptime']-10-.002,event['afterUptime']-10+.003
            commands.append(dict(id=identifier,kind=kind,hostBefore=hb,hostAfter=ha,response=response))
        calibration['commands']=commands
        events.sort(key=lambda r:r['uptime'])
        for event in events:
            event.update(enqueuedUptime=event['uptime']+.001,journalStartUptime=event['uptime']+.002,priorWrites=[])
            if event['type']=='clipboard':event.update(callbackBeforeUptime=event['uptime'],callbackAfterUptime=event['uptime']+.0005)
        draws=[dict(id=i+1,tickBeforeUptime=110+i*.05-.021,tickAfterUptime=110+i*.05-.0205,
                    drawBeforeUptime=110+i*.05-.02,drawAfterUptime=110+i*.05-.0199,
                    enqueuedUptime=110+i*.05-.0198,journalStartUptime=110+i*.05-.0197,displayLinkTimestamp=110+i*.05-.03) for i in range(400)]
        writes=[dict(batch=i+1,beforeUptime=draws[min((i+1)*30,400)-1]['journalStartUptime']+.001,afterUptime=draws[min((i+1)*30,400)-1]['journalStartUptime']+.0011) for i in range(14)]
        strip=dict(draws=draws,complete=dict(schema='p1-strip-complete-v1',admissionEligible=False,drawCount=400,batches=14,
                   stoppedUptime=131,journalCompleteUptime=132,writeCosts=writes))
        return calibration,decoded,events,'timeout',dict(schema='p1-video-input-v1',scenario='timeout',baselineDriver='normal-XCTest-fixture-ready-tap',baselineBefore=9,baselineAfter=9.5,firstDriver='normal-XCTest-tap',firstBefore=10,firstAfter=11),strip
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
        args=self.fixture();next(r for r in args[2] if r['type']=='clipboard')['uptime']=130
        with self.assertRaises(ValueError):inspect(*args)
    def test_video_cadence_gap(self):
        args=self.fixture();del args[1]['frames'][50:55]
        with self.assertRaises(ValueError):inspect(*args)
    def test_reused_strip_id_cannot_gain_precision(self):
        args=self.fixture();args[1]['frames'][50]['marker']=1
        with self.assertRaises(ValueError):inspect(*args)
    def test_missing_protocol_boundary(self):
        args=self.fixture();args[2][:]=[r for r in args[2] if r['type']!='baseline-ready']
        with self.assertRaises(ValueError):inspect(*args)
    def test_missing_strip_receipt(self):
        args=list(self.fixture());args[-1]={}
        with self.assertRaises(ValueError):inspect(*args)
    def test_strip_cost_does_not_supply_label(self):
        args=self.fixture()
        for r in args[1]['observations']:r['label']='unknown'
        with self.assertRaises(ValueError):inspect(*args)
    def test_missing_actual_event(self):
        args=list(self.fixture());args[2]=[]
        with self.assertRaises(ValueError):inspect(*args)
    def test_duplicate_actual_event(self):
        args=self.fixture();args[2].append(copy.deepcopy(next(r for r in args[2] if r['type']=='clipboard')))
        with self.assertRaises(ValueError):inspect(*args)

class RawBindings(unittest.TestCase):
    def fixture(self):return Analysis().fixture()
    def rejects(self,args):
        with self.assertRaises(ValueError):inspect(*args)
    def test_changed_observation_pts(self):
        a=self.fixture();a[1]['observations'][30]['pts']+=.001;self.rejects(a)
    def test_changed_observation_end(self):
        a=self.fixture();a[1]['observations'][30]['endPTS']+=.001;self.rejects(a)
    def test_duplicate_observation_index(self):
        a=self.fixture();a[1]['observations'][30]['index']=29;self.rejects(a)
    def test_bool_raw_index(self):
        a=self.fixture();a[1]['frames'][0]['index']=False;self.rejects(a)
    def test_independent_screenshot_without_strip_receipt(self):
        a=self.fixture();a[1]['independentScreenshots'][0]['decodedMarker']=9999;self.rejects(a)
    def test_stale_after_screenshot(self):
        a=self.fixture();a[1]['independentScreenshots'][1]['decodedMarker']=1;self.rejects(a)
    def test_missing_ready_command(self):
        a=self.fixture();a[2][:]=[r for r in a[2] if r.get('kind')!='ready'];self.rejects(a)
    def test_wrong_phase(self):
        a=self.fixture();next(r for r in a[2] if r.get('kind')=='mid')['phase']='ready';self.rejects(a)
    def test_duplicate_window_end(self):
        a=self.fixture();a[2].append(copy.deepcopy(next(r for r in a[2] if r['type']=='window-end')));self.rejects(a)
    def test_wrong_stage_order(self):
        a=self.fixture();a[0]['markers'][0]['stage']='mid';self.rejects(a)
    def test_bool_screenshot_ordinal(self):
        a=self.fixture();a[1]['screenshots'][0]['id']=True;self.rejects(a)
    def test_screenshot_crosses_protocol_boundary(self):
        a=self.fixture();next(r for r in a[2] if r.get('kind')=='ready')['uptime']=110.7;self.rejects(a)
    def test_clock_crosses_protocol_boundary(self):
        a=self.fixture();next(r for r in a[2] if r['type']=='baseline-ready')['afterUptime']=110.5;self.rejects(a)
    def test_unjournaled_pixel_id(self):
        a=self.fixture();a[1]['frames'][30]['marker']=9999;self.rejects(a)
    def test_draw_times_do_not_override_wide_screenshot_uncertainty(self):
        a=self.fixture()
        for r in a[0]['markers']:r['hostBefore']-=.15;r['hostAfter']+=.15
        self.rejects(a)


class TransportBindings(unittest.TestCase):
    def fixture(self):return Analysis().fixture()
    def rejects(self,args):
        with self.assertRaises(ValueError):inspect(*args)
    def test_missing_commands(self):
        a=self.fixture();del a[0]['commands'];self.rejects(a)
    def test_missing_request(self):
        a=self.fixture();a[0]['commands'].pop();self.rejects(a)
    def test_duplicate_request(self):
        a=self.fixture();a[0]['commands'][5]=copy.deepcopy(a[0]['commands'][4]);self.rejects(a)
    def test_reordered_requests(self):
        a=self.fixture();a[0]['commands'][8:10]=reversed(a[0]['commands'][8:10]);self.rejects(a)
    def test_request_kind_changed(self):
        a=self.fixture();a[0]['commands'][8]['kind']='clock';self.rejects(a)
    def test_boolean_request_id(self):
        a=self.fixture();a[0]['commands'][0]['id']=True;self.rejects(a)
    def test_response_missing(self):
        a=self.fixture();a[0]['commands'][0]['response']=None;self.rejects(a)
    def test_response_id_changed(self):
        a=self.fixture();a[0]['commands'][0]['response']['id']=2;self.rejects(a)
    def test_boolean_response_id(self):
        a=self.fixture();a[0]['commands'][0]['response']['id']=True;self.rejects(a)
    def test_response_clock_changed(self):
        a=self.fixture();a[0]['commands'][0]['response']['appSend']+=.001;self.rejects(a)
    def test_response_phase_changed(self):
        a=self.fixture();a[0]['commands'][8]['response']['phase']='finished';self.rejects(a)
    def test_response_unexpected_fields(self):
        a=self.fixture();a[0]['commands'][0]['response']['phase']='ready';self.rejects(a)
    def test_response_nonfinite(self):
        a=self.fixture();a[0]['commands'][8]['response']['appSend']=float('nan');self.rejects(a)
    def test_host_clock_reordered(self):
        a=self.fixture();a[0]['commands'][1]['hostBefore']=a[0]['commands'][0]['hostBefore'];self.rejects(a)
    def test_exchange_id_changed(self):
        a=self.fixture();a[0]['exchanges'][0]['id']=0;self.rejects(a)
    def test_exchange_boolean_id(self):
        a=self.fixture();a[0]['exchanges'][0]['id']=True;self.rejects(a)
    def test_exchange_host_time_changed(self):
        a=self.fixture();a[0]['exchanges'][0]['hostAfter']+=.001;self.rejects(a)
    def test_app_command_id_changed(self):
        a=self.fixture();next(r for r in a[2] if r.get('kind')=='ready')['id']=10;self.rejects(a)
    def test_app_command_receive_changed(self):
        a=self.fixture();next(r for r in a[2] if r.get('kind')=='ready')['uptime']+=.0001;self.rejects(a)
    def test_app_command_after_response(self):
        a=self.fixture();next(r for r in a[2] if r.get('kind')=='ready')['afterUptime']+=.1;self.rejects(a)

if __name__=='__main__':unittest.main()
