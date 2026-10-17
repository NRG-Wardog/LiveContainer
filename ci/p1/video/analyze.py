"""Offline diagnostic analysis. Raw evidence remains authoritative; no admission."""
from __future__ import annotations
import json
from pathlib import Path
from intervals import mapping, frame_times, event_spacing, lifetime, require, finite, evidence_window
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


def strip_metrics(strip):
    require(isinstance(strip,dict) and isinstance(strip.get('complete'),dict),'missing strip receipt')
    complete=strip['complete'];rows=strip.get('draws')
    require(complete.get('schema')=='p1-strip-complete-v1' and complete.get('admissionEligible') is False and
        isinstance(rows,list) and 2<=len(rows)<18000 and type(complete.get('drawCount')) is int and complete['drawCount']==len(rows),'invalid strip completion')
    previous=-1;costs=[];ticks=[]
    for i,row in enumerate(rows,1):
        require(type(row.get('id')) is int and row['id']==i,'strip ID sequence gap/reuse')
        keys=['tickBeforeUptime','tickAfterUptime','drawBeforeUptime','drawAfterUptime','enqueuedUptime','journalStartUptime']
        values=[row.get(k) for k in keys]
        require(all(finite(v) and v>=0 for v in values) and values==sorted(values),'invalid strip draw/queue brackets')
        require(row['drawBeforeUptime']>=previous and finite(row.get('displayLinkTimestamp')) and row['displayLinkTimestamp']>=0,'strip clock reordered')
        previous=row['drawAfterUptime'];costs.append(row['drawAfterUptime']-row['drawBeforeUptime']);ticks.append(row['tickAfterUptime']-row['tickBeforeUptime'])
    require(finite(complete.get('stoppedUptime')) and finite(complete.get('journalCompleteUptime')) and
        previous<=complete['stoppedUptime']<=complete['journalCompleteUptime'],'strip stop clock differs')
    writes=complete.get('writeCosts');require(isinstance(writes,list) and type(complete.get('batches')) is int and
        complete['batches']==(len(rows)+29)//30 and len(writes)==complete['batches'],'strip write cost inventory differs')
    for i,row in enumerate(writes,1):
        require(type(row.get('batch')) is int and row['batch']==i and finite(row.get('beforeUptime')) and finite(row.get('afterUptime')) and
            row['beforeUptime']<=row['afterUptime']<=complete['journalCompleteUptime'],'invalid strip write cost')
    span=rows[-1]['drawAfterUptime']-rows[0]['drawBeforeUptime']
    require(span>0 and max(costs+ticks)<=.005 and (sum(costs)+sum(ticks))/span<=.10,'strip measured overhead exceeds fixed budget')
    return {r['id']:r for r in rows},{'drawCount':len(rows),'maxDrawSeconds':max(costs),'totalDrawSeconds':sum(costs),
        'maxTickSeconds':max(ticks),'totalTickSeconds':sum(ticks),'measuredCPUFraction':(sum(costs)+sum(ticks))/span,
        'maxBackgroundWriteSeconds':max(r['afterUptime']-r['beforeUptime'] for r in writes),
        'limit':'CPU draw/tick brackets exclude final receipt enqueue and compositor work; draw times never substitute for presentation timestamps.'}


def protocol_window(events):
    starts=[r for r in events if r.get('type')=='baseline-ready']
    ends=[r for r in events if r.get('type')=='command' and r.get('kind')=='finish']
    require(len(starts)==len(ends)==1,'missing/duplicate protocol evidence boundary')
    start,end=starts[0],ends[0]
    commands=[r for r in events if r.get('type')=='command']
    expected=[('ready','ready'),('mid','calibrating-mid'),('third','third-ready'),('post','calibrating-post'),('finish','finished')]
    require([(r.get('kind'),r.get('phase')) for r in commands]==expected,'protocol commands missing/reordered')
    prior=start['uptime']
    for row in commands:
        require(finite(row.get('uptime')) and finite(row.get('afterUptime')) and prior<row['uptime']<=row['afterUptime'],'invalid protocol command order')
        prior=row['afterUptime']
    windows=[r for r in events if r.get('type')=='window-end'];posts=[r for r in events if r.get('type')=='post-ready']
    require(len(windows)==len(posts)==1 and finite(windows[0].get('uptime')) and finite(posts[0].get('uptime')),'missing/duplicate settling event')
    require(commands[0]['afterUptime']<windows[0]['uptime']<commands[1]['uptime'] and
        commands[2]['afterUptime']<posts[0]['uptime']<commands[3]['uptime'],'settling event outside protocol phase')
    require(start.get('driver')=='normal-XCTest-fixture-ready-tap' and end.get('phase')=='finished','wrong protocol boundary driver/phase')
    require(finite(start.get('uptime')) and finite(start.get('afterUptime')) and finite(end.get('uptime')) and finite(end.get('afterUptime')) and
        start['uptime']<=start['afterUptime']<end['uptime']<=end['afterUptime'],'invalid protocol boundary clocks')
    stages={'pre':(start['afterUptime'],commands[0]['uptime']),
            'mid':(commands[1]['afterUptime'],commands[2]['uptime']),
            'post':(commands[3]['afterUptime'],commands[4]['uptime'])}
    return start['uptime'],end['afterUptime'],stages

def transport_bindings(calibration, events):
    """Bind all retained requests to their raw responses and app receipts.

    Host brackets are ordered only against host brackets. App response clocks
    are ordered only against app receipts; no clock-domain equivalence assumed.
    """
    commands=calibration.get('commands');exchanges=calibration.get('exchanges')
    expected=['clock']*8+['ready','mid']+['clock']*8+['third','post']+['clock']*8+['finish']
    require(isinstance(commands,list) and len(commands)==29 and isinstance(exchanges,list) and len(exchanges)==24,'missing transport request/response inventory')
    app_commands=[r for r in events if r.get('type')=='command']
    require(len(app_commands)==5,'missing app command binding')
    app_by_kind={r.get('kind'):r for r in app_commands}
    phases={'ready':'ready','mid':'calibrating-mid','third':'third-ready','post':'calibrating-post','finish':'finished'}
    clock_ids=[i for i,kind in enumerate(expected,1) if kind=='clock']
    require([r.get('id') for r in exchanges]==clock_ids and all(type(r.get('id')) is int for r in exchanges),'exchange request IDs differ')
    require([r.get('stage') for r in exchanges]==['pre']*8+['mid']*8+['post']*8,'exchange request stages differ')
    exchange_by_id={r['id']:r for r in exchanges};previous_host=0;previous_app=0
    for identifier,(row,kind) in enumerate(zip(commands,expected),1):
        require(set(row)=={'id','kind','hostBefore','hostAfter','response'} and type(row.get('id')) is int and row['id']==identifier and row.get('kind')==kind,'transport command identity/order differs')
        hb,ha=row['hostBefore'],row['hostAfter']
        require(finite(hb) and finite(ha) and 0<=previous_host<=hb<=ha,'transport host brackets reordered')
        previous_host=ha;response=row['response']
        require(isinstance(response,dict) and set(response)==({'id','appReceive','appSend'} if kind=='clock' else {'id','appReceive','appSend','phase'}),'transport response shape differs')
        require(type(response.get('id')) is int and response['id']==identifier,'transport response ID differs')
        ar,ass=response['appReceive'],response['appSend']
        require(finite(ar) and finite(ass) and 0<=previous_app<=ar<=ass,'transport app response clocks reordered')
        previous_app=ass
        if kind=='clock':
            exchange=exchange_by_id[identifier]
            require(set(exchange)=={'id','stage','hostBefore','hostAfter','appReceive','appSend'} and
                exchange['hostBefore']==hb and exchange['hostAfter']==ha and exchange['appReceive']==ar and exchange['appSend']==ass,'clock exchange differs from raw response')
        else:
            event=app_by_kind.get(kind,{})
            require(type(event.get('id')) is int and event['id']==identifier and event.get('phase')==phases[kind] and response['phase']==phases[kind],'app command/response identity differs')
            require(event.get('uptime')==ar and finite(event.get('afterUptime')) and ar<=event['afterUptime']<=ass,'app command/response clocks differ')
    return True


def inspect(calibration, decoded, events, scenario, controls, strip):
    input_receipt(controls,scenario)
    transport_bindings(calibration,events)
    costs=journal_metrics(events,scenario)
    draw_ids,draw_costs=strip_metrics(strip)
    window_start,window_end,stage_bounds=protocol_window(events)
    require(decoded.get('schema')=='p1-video-decoded-v1' and decoded.get('admissionEligible') is False,'wrong decode identity')
    require(calibration.get('schema')=='p1-video-calibration-v1','wrong calibration identity')
    independent=decoded.get('independentScreenshots')
    require(isinstance(independent,list) and len(independent)==2 and {r.get('phase') for r in independent}=={'before','after'} and all(r.get('label')=='Copy Details' for r in independent),'independent steady-state label pixels not recognized')
    require(all(type(r.get('decodedMarker')) is int and r['decodedMarker'] in draw_ids for r in independent),'independent screenshot has unjournaled strip ID')
    frames=decoded['frames']; require(frames,'missing decoded video')
    # Complete original decoded presentation timeline, not only OCR samples.
    frame_times(frames,(0,0),check_gaps=False)
    require(all(type(f.get('index')) is int and f['index']==i for i,f in enumerate(frames)),'raw video frame index differs')
    raw_by_id={f['index']:f for f in frames}
    raw_observations=decoded.get('observations')
    require(isinstance(raw_observations,list) and 2<=len(raw_observations)<=len(frames),'missing/unbounded OCR observations')
    previous_index=-1
    for row in raw_observations:
        index=row.get('index');require(type(index) is int and index in raw_by_id and index>previous_index,'duplicate/reordered OCR index')
        reference=raw_by_id[index]
        require(all(finite(row.get(k)) and row[k]==reference[k] for k in ['pts','endPTS']) and row.get('label') in ['Copied','Copy Details','unknown'],'OCR clock/label differs from raw frame')
        previous_index=index
    require(isinstance(decoded.get('screenshots'),list) and all(type(r.get('id')) is int for r in decoded['screenshots']),'invalid screenshot ordinal')
    screenshots={r['id']:r for r in decoded['screenshots']}
    require(len(screenshots)==9 and len(decoded['screenshots'])==9,'missing/duplicate independent calibration screenshot')
    require([r.get('id') for r in calibration['markers']]==list(range(1,10)) and
        [r.get('stage') for r in calibration['markers']]==['pre']*3+['mid']*3+['post']*3,'calibration marker stage order differs')
    markers=[];screenshot_ids=set()
    for row in calibration['markers']:
        observed=screenshots[row['id']]['decodedMarker']
        require(type(observed) is int and observed in draw_ids and observed not in screenshot_ids,'missing/reused/unjournaled screenshot strip ID')
        screenshot_ids.add(observed)
        matches=[[f['pts'],f['endPTS']] for f in frames if f.get('marker')==observed]
        markers.append(dict(row,matches=matches))
    independent_ids={r['phase']:r['decodedMarker'] for r in independent}
    require(independent_ids['before']<min(screenshot_ids) and independent_ids['after']>max(screenshot_ids),'independent screenshots do not bracket calibration')
    clock=mapping(calibration['exchanges'],markers)
    for row in calibration['exchanges']:
        lo,hi=stage_bounds[row['stage']]
        require(lo<=row['appReceive']<=row['appSend']<=hi,'clock exchange outside protocol stage')
    for row in calibration['markers']:
        lo,hi=stage_bounds[row['stage']]
        require(lo<=row['hostBefore']+clock['appMinusHost'][0] and row['hostAfter']+clock['appMinusHost'][1]<=hi,'screenshot uncertainty crosses protocol stage')
    offset=clock['appMinusVideoPTS']
    selected,pts_window=evidence_window(frames,offset,window_start,window_end)
    prior_id=0
    for row in selected:
        identifier=row.get('marker')
        require(type(identifier) is int and identifier in draw_ids and identifier>=prior_id,'unknown/reordered video strip ID in evidence window')
        prior_id=identifier
        require(row['endPTS']+offset[1]>=draw_ids[identifier]['drawBeforeUptime'],'video strip appears before possible draw')
    for row in calibration['markers']:
        observed=screenshots[row['id']]['decodedMarker']
        require(row['hostAfter']+clock['appMinusHost'][1]>=draw_ids[observed]['drawBeforeUptime'],'independent screenshot predates possible strip draw')
    actual=[r for r in events if r.get('type')=='clipboard']
    require(all(window_start<r['uptime']<window_end for r in actual),'actual input outside fixed evidence window')
    spacing=event_spacing(actual,scenario)
    observations=[r for r in decoded['observations'] if r['endPTS']>=pts_window[0] and r['pts']<=pts_window[1]]
    selected_ids={r['index'] for r in selected}
    require(all(r.get('index') in selected_ids for r in observations),'observation outside raw frame inventory')
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
        'observer_costs':costs,'strip_costs':draw_costs,'evidence_window':{'appBounds':[window_start,window_end],'possiblePTSBounds':pts_window,'frameCount':len(selected)},'clock':clock,'actual_overlap_spacing':spacing,'target_lifetime':timing,'third_lifetime':third,
        'limits':'Times are relative to pasteboard-notification receipt; delivery delay and stable-rate/continuous-timeline assumptions remain unproved; full native admission is closed.'}
