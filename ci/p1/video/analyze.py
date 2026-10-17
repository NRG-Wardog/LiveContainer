"""Offline diagnostic analysis. Raw evidence remains authoritative; no admission."""
from __future__ import annotations
import json
from pathlib import Path
from intervals import mapping, frame_times, event_spacing, lifetime, require, finite
from exports import input_receipt


def journal_metrics(events,scenario):
    starts=[r for r in events if r.get('type')=='start']
    require(len(starts)==1 and starts[0].get('scenario')==scenario and starts[0].get('schema')=='p1-video-events-v1' and starts[0].get('admissionEligible') is False,'wrong event journal identity')
    writes={};callbacks=[]
    for event in events:
        times=[event.get(k) for k in ['uptime','enqueuedUptime','journalStartUptime']]
        require(all(finite(v) for v in times) and times==sorted(times),'invalid journal clock brackets')
        for cost in event.get('priorWrites',[]):
            sequence=cost.get('sequence');before=cost.get('beforeUptime');after=cost.get('afterUptime')
            require(type(sequence) is int and sequence>0 and finite(before) and finite(after) and before<=after<=event['journalStartUptime'],'invalid journal write cost')
            require(sequence not in writes or writes[sequence]==cost,'inconsistent prior write cost');writes[sequence]=cost
        if event.get('type')=='clipboard':
            before,after=event.get('callbackBeforeUptime'),event.get('callbackAfterUptime')
            require(before==event['uptime'] and finite(after) and before<=after<=event['enqueuedUptime'],'invalid clipboard callback cost')
            callbacks.append(after-before)
    require(set(writes)==set(range(1,len(writes)+1)),'journal cost sequence gap')
    require(callbacks and max(callbacks)<=.005,'clipboard in-method bracket exceeded fixed 5 ms budget')
    return {'callbackMaxSeconds':max(callbacks),'callbackTotalSeconds':sum(callbacks),
        'backgroundWriteMaxSeconds':max((r['afterUptime']-r['beforeUptime'] for r in writes.values()),default=0),
        'backgroundWriteTotalSeconds':sum(r['afterUptime']-r['beforeUptime'] for r in writes.values()),
        'limit':'Final enqueue is outside the in-method callback bracket; last journal write has no later cost receipt; notification delivery latency and indirect perturbation remain unknown.'}

def inspect(calibration, decoded, events, scenario, controls):
    input_receipt(controls,scenario)
    costs=journal_metrics(events,scenario)
    require(decoded.get('schema')=='p1-video-decoded-v1' and decoded.get('admissionEligible') is False,'wrong decode identity')
    require(calibration.get('schema')=='p1-video-calibration-v1','wrong calibration identity')
    independent=decoded.get('independentScreenshots')
    require(isinstance(independent,list) and len(independent)==2 and {r.get('phase') for r in independent}=={'before','after'} and all(r.get('label')=='Copy Details' for r in independent),'independent steady-state label pixels not recognized')
    frames=decoded['frames']; require(frames,'missing decoded video')
    # Complete original decoded presentation timeline, not only OCR samples.
    frame_times(frames,(0,0))
    screenshots={r['id']:r for r in decoded['screenshots']}
    require(len(screenshots)==9 and len(decoded['screenshots'])==9,'missing/duplicate independent calibration screenshot')
    markers=[]
    for row in calibration['markers']:
        require(screenshots[row['id']]['decodedMarker']==row['id'],'screenshot did not observe requested marker')
        matches=[[f['pts'],f['endPTS']] for f in frames if f.get('marker')==row['id']]
        markers.append(dict(row,matches=matches))
    clock=mapping(calibration['exchanges'],markers)
    actual=[r for r in events if r.get('type')=='clipboard']
    spacing=event_spacing(actual,scenario)
    observations=decoded['observations']; offset=clock['appMinusVideoPTS']
    target=actual[0] if scenario=='timeout' else actual[1]
    # Baseline pixels before the actual first event are independently required.
    mapped=frame_times(observations,offset)
    require(any(f['label']=='Copy Details' and t[1]<actual[0]['uptime'] for f,t in zip(observations,mapped)),'no recognizable pre-copy pixels')
    if scenario!='timeout':
        require(any(f['label']=='Copy Details' and t[0]>actual[0]['uptime'] and t[1]<actual[1]['uptime'] for f,t in zip(observations,mapped)),'replacement/reopen reset pixels not observed before actual second event')
        require(controls.get('thirdHittable') is True and controls.get('thirdLabelBefore')=='Copy Details' and
            controls.get('thirdDriver')=='normal-XCTest-third-tap','separate ordinary third input unavailable')
    timing=lifetime(observations,offset,target['uptime'],actual[0]['uptime'] if scenario!='timeout' else None)
    third=None
    if scenario!='timeout': third=lifetime(observations,offset,actual[2]['uptime'])
    return {'schema':'p1-video-conditional-feasibility-v1','scenario':scenario,
        'conditional_feasibility':True,'admissionEligible':False,'production_ready':False,
        'observer_costs':costs,'clock':clock,'actual_overlap_spacing':spacing,'target_lifetime':timing,'third_lifetime':third,
        'limits':'Times are relative to pasteboard-notification receipt; delivery delay and stable-rate/continuous-timeline assumptions remain unproved; full native admission is closed.'}
