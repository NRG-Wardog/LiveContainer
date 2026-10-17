"""Nonce-bound calibration feasibility only; never feedback or UI admission.

Screenshot acquisition has its own runner clock, calibrated independently from
app time. All plausible video matches are enclosed. Draw brackets only constrain
causality; they are never compositor presentation timestamps.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'video'))
from intervals import require, finite, app_host, video_host, frame_times, evidence_window
from analyze import strip_metrics
from protocol import expected_app_requests, expected_runner_requests, parse, sha

PHASES={'ready':'ready','capability-mid':'calibrating-mid','third':'third-ready','capability-post':'calibrating-post','finish':'finished'}
RUNNER_ID='org.sidestore.fixture.p1video.uitests.xctrunner'


def rows_bound(document,root,session,role,complete_sha=None):
    require(document.get('schema')=='p1-capability-host-channel-v1' and document.get('session')==session and document.get('role')==role and document.get('admissionEligible') is False,'host channel identity differs')
    expected=expected_app_requests(session) if role=='app' else expected_runner_requests(session)
    if role=='runner':expected[-1].update(appStripCompleteSHA256=complete_sha,hostVerifiedStripComplete=True)
    rows=document.get('rows');require(isinstance(rows,list) and len(rows)==len(expected),'missing channel inventory')
    exchanges=[];previous_host=0;previous_remote=0
    for row,request in zip(rows,expected):
        require(set(row)=={'request','hostBefore','hostAfter','response'} and row['request']==request and type(row['request']['id']) is int,'request identity/order differs')
        if 'hostVerifiedStripComplete' in request:require(row['request'].get('hostVerifiedStripComplete') is True,'nonboolean verification acknowledgement')
        for key in ('id','ordinal'):
            if key in request:require(type(row['request'][key]) is int,'noninteger request identity')
        hb,ha=row['hostBefore'],row['hostAfter'];require(finite(hb) and finite(ha) and previous_host<=hb<=ha,'host bracket order differs');previous_host=ha
        response=row['response'];require(isinstance(response,dict) and type(response.get('id')) is int and response['id']==request['id'] and response.get('session')==session,'response identity differs')
        width=3 if role=='app' else 4
        require(parse(root/f'request-{request["id"]:0{width}d}.json')==request and parse(root/f'response-{request["id"]:0{width}d}.json')==response,'durable request/response differs')
        keys=('appReceive','appSend') if role=='app' else ('runnerReceive','runnerSend')
        received,sent=[response.get(k) for k in keys]
        require(finite(received) and finite(sent) and previous_remote<=received<=sent,'remote clock order differs');previous_remote=sent
        if role=='runner':
            require(response.get('schema')=='p1-capability-response-v1' and response.get('kind')==request['kind'] and response.get('runnerBundleIdentifier')==RUNNER_ID and response.get('clock')=='runner-ProcessInfo.systemUptime' and response.get('clockEquivalenceAssumed') is False and response.get('admissionEligible') is False,'runner response provenance differs')
            for key in ('phase','ordinal'):
                require(response.get(key)==request.get(key),'runner response stage differs')
        elif request['kind']!='clock':require(response.get('phase')==PHASES[request['kind']],'app command response differs')
        if request['kind']=='clock':exchanges.append({'id':request['id'],'stage':request['phase'],'hostBefore':hb,'hostAfter':ha,'appReceive':received,'appSend':sent})
    require(parse(root/'request.json')==expected[-1] and parse(root/'response.json')==rows[-1]['response'],'published final channel receipt differs')
    expected_names={f'{prefix}-{r["id"]:0{3 if role=="app" else 4}d}.json' for prefix in ['request','response'] for r in expected}
    actual_names={p.name for prefix in ['request-','response-'] for p in root.glob(prefix+'*.json')}
    require(expected_names==actual_names,'extra/missing durable channel rows')
    return rows,exchanges


def rectangle(row):
    require(isinstance(row,list) and len(row)==4 and all(finite(v) for v in row) and min(row[2:])>0,'invalid rectangle');return row


def capture_receipt(root,name,session,request_id,phase,ordinal):
    row=parse(root/(name+'.json'))
    require(row.get('schema')=='p1-capability-capture-v1' and row.get('session')==session and row.get('runnerBundleIdentifier')==RUNNER_ID and row.get('name')==name and type(row.get('requestId')) is int and row['requestId']==request_id and row.get('phase')==phase and type(row.get('ordinal')) is int and row['ordinal']==ordinal,'capture identity differs')
    require(row.get('clock')=='runner-ProcessInfo.systemUptime' and row.get('clockEquivalenceAssumed') is False and row.get('admissionEligible') is False and row.get('timingFeasibilityEstablished') is False,'capture clock/scope differs')
    clocks=[row.get(k) for k in ['acquisitionBefore','acquisitionAfter','encodingBefore','encodingAfter','attachmentBefore','attachmentAfter','pngWriteBefore','pngWriteAfter']]
    require(all(finite(v) and v>0 for v in clocks) and clocks==sorted(clocks) and clocks[0]<clocks[1],'capture work brackets invalid')
    png=root/(name+'.png');require(png.is_file() and not png.is_symlink() and type(row.get('pngBytes')) is int and row['pngBytes']==png.stat().st_size and row.get('pngSHA256')==sha(png),'capture PNG identity differs')
    require(row.get('copyBefore')==row.get('copyAfter'),'production control changed during capture')
    copy=row['copyBefore'];require(copy.get('identifier')=='signin.prompt.copy-details' and copy.get('label')=='Copy Details' and all(copy.get(k) is True for k in ['exists','enabled','hittable']) and type(copy.get('elementType')) is int,'actual production control unavailable')
    rect=rectangle(copy.get('frame'))
    for key in ['markerFrame','windowFrame']:
        require(row.get(key+'Before')==row.get(key+'After'),'geometry changed during capture');rectangle(row.get(key+'Before'))
    window=row['windowFrameBefore']
    for r in [rect,row['markerFrameBefore']]:require(r[0]>=window[0] and r[1]>=window[1] and r[0]+r[2]<=window[0]+window[2]+1 and r[1]+r[3]<=window[1]+window[3]+1,'capture ROI outside visible window')
    return row


def inspect(folder,session,decoded,events,strip):
    app,runner=folder/'raw-app',folder/'raw-runner'
    complete_sha=sha(app/'strip-complete.json')
    ar,ae=rows_bound(parse(folder/'app-channel.json'),app,session,'app')
    rr,re=rows_bound(parse(folder/'runner-channel.json'),runner,session,'runner',complete_sha)
    identity=parse(app/'identity.json');require(identity=={'schema':'p1-capability-app-v1','session':session,'bundleIdentifier':'org.sidestore.fixture.p1video','admissionEligible':False},'app launch identity differs')
    launch=parse(runner/'runner.json');require(launch.get('schema')=='p1-capability-runner-v1' and launch.get('session')==session and launch.get('runnerBundleIdentifier')==RUNNER_ID and launch.get('expectedRequests')==35 and launch.get('clockEquivalenceAssumed') is False,'runner launch identity differs')
    finish=parse(runner/'completion.json');require(finish.get('schema')=='p1-capability-complete-v1' and finish.get('session')==session and finish.get('appStripCompleteSHA256')==complete_sha and finish.get('hostVerifiedStripComplete') is True and finish.get('id')==35 and finite(finish.get('runnerAckUptime')) and rr[-1]['response']['runnerReceive']<=finish['runnerAckUptime']<=rr[-1]['response']['runnerSend'],'host verification acknowledgement missing')
    require(all(r.get('session')==session for r in events) and all(r.get('type')!='clipboard' for r in events),'wrong event session or unexpected production action')
    starts=[r for r in events if r.get('type')=='start'];ready=[r for r in events if r.get('type')=='baseline-ready'];commands=[r for r in events if r.get('type')=='command']
    require(len(starts)==len(ready)==1 and starts[0].get('scenario')=='capability' and ready[0].get('driver')=='normal-XCTest-fixture-ready-tap','baseline handshake differs')
    require([(r.get('kind'),r.get('phase')) for r in commands]==list(PHASES.items()),'app commands missing/reordered')
    for event,row in zip(commands,[r for r in ar if r['request']['kind']!='clock']):
        require(type(event.get('id')) is int and event['id']==row['request']['id'] and event.get('uptime')==row['response']['appReceive'] and finite(event.get('afterUptime')) and event['uptime']<=event['afterUptime']<=row['response']['appSend'],'app command clocks differ')
    for event in events:
        times=[event.get(k) for k in ['uptime','enqueuedUptime','journalStartUptime']];require(all(finite(v) for v in times) and times==sorted(times),'app event clock order differs')
    stages={'pre':(ready[0]['afterUptime'],commands[0]['uptime']),'mid':(commands[1]['afterUptime'],commands[2]['uptime']),'post':(commands[3]['afterUptime'],commands[4]['uptime'])}
    require(all(finite(v) for bounds in stages.values() for v in bounds) and all(a<b for a,b in stages.values()),'app phase boundaries invalid')
    app_offset=app_host(ae);runner_offset=app_host(re)
    for row in ae:
        low,high=stages[row['stage']];require(low<=row['appReceive']<=row['appSend']<=high,'app clock outside phase')
    draw_ids,costs=strip_metrics(strip)
    require(strip['complete']==parse(app/'strip-complete.json'),'strip completion differs from raw file')
    require(strip['complete'].get('session')==session and all(row.get('session')==session for row in strip['draws']),'strip session differs')
    require(decoded.get('schema')=='p1-calibration-decoded-v1' and decoded.get('admissionEligible') is False,'decoder scope differs')
    frames=decoded.get('frames');frame_times(frames,(0,0),check_gaps=False)
    require(all(type(f.get('index')) is int and f['index']==i for i,f in enumerate(frames)),'video frame identity differs')
    screenshots=decoded.get('screenshots');require(isinstance(screenshots,list) and len(screenshots)==9 and [r.get('id') for r in screenshots]==list(range(1,10)) and all(type(r['id']) is int for r in screenshots),'calibration pixel inventory differs')
    decode_input=parse(folder/'decode-input.json')
    require(isinstance(decode_input.get('screenshots'),list) and len(decode_input['screenshots'])==9 and [r.get('id') for r in decode_input['screenshots']]==list(range(1,10)),'decode input calibration inventory differs')
    require(isinstance(decode_input.get('independentScreenshots'),list) and len(decode_input['independentScreenshots'])==2 and [r.get('phase') for r in decode_input['independentScreenshots']]==['before','after'],'decode input independent inventory differs')
    capture_rows=[r for r in rr if r['request']['kind']=='capture'];markers=[];ids=set();receipts=[]
    for index,(transport,pixels) in enumerate(zip(capture_rows,screenshots),1):
        request,response=transport['request'],transport['response'];phase=request['phase'];ordinal=request['ordinal'];name=f'capture-{phase}-{ordinal}'
        require(response.get('png')==name+'.png' and response.get('receipt')==name+'.json','capture association differs')
        receipt=capture_receipt(runner,name,session,request['id'],phase,ordinal);receipts.append(receipt)
        specification=decode_input['screenshots'][index-1]
        require(type(specification.get('id')) is int and pixels.get('path')==specification.get('path') and Path(specification['path']).name==name+'.png' and Path(specification['path']).parent.name=='raw-runner' and pixels.get('pngSHA256')==receipt['pngSHA256'],'decoded calibration PNG association differs')
        require(response['runnerReceive']<=receipt['acquisitionBefore']<=receipt['pngWriteAfter']<=response['runnerSend'],'capture outside runner response')
        marker=pixels.get('decodedMarker');require(type(marker) is int and marker in draw_ids and marker not in ids and pixels.get('label')=='Copy Details','unknown/reused calibration pixels');ids.add(marker)
        hb=receipt['acquisitionBefore']-runner_offset[1];ha=receipt['acquisitionAfter']-runner_offset[0]
        require(stages[phase][0]<=hb+app_offset[0] and ha+app_offset[1]<=stages[phase][1],'screenshot uncertainty crosses phase')
        matches=[[f['pts'],f['endPTS']] for f in frames if f.get('marker')==marker]
        markers.append(dict(id=index,stage=phase,hostBefore=hb,hostAfter=ha,matches=matches))
        require(ha+app_offset[1]>=draw_ids[marker]['drawBeforeUptime'],'screenshot predates possible draw')
    host_video=video_host(markers);offset=(app_offset[0]+host_video[0],app_offset[1]+host_video[1])
    require(offset[1]-offset[0]<=.120,'combined app/video uncertainty exceeds fixed limit')
    before=capture_receipt(runner,'capture-baseline',session,0,'baseline',0);after=capture_receipt(runner,'capture-after',session,34,'after',0)
    after_response=rr[33]['response']
    require(after_response.get('png')=='capture-after.png' and after_response.get('receipt')=='capture-after.json' and after_response['runnerReceive']<=after['acquisitionBefore']<=after['pngWriteAfter']<=after_response['runnerSend'],'after capture/response association differs')
    ready_receipt=parse(runner/'ready.json');require(ready_receipt.get('session')==session and ready_receipt.get('baselineDriver')=='normal-XCTest-fixture-ready-tap' and finite(ready_receipt.get('baselineTapBefore')) and finite(ready_receipt.get('baselineTapAfter')) and before['pngWriteAfter']<=ready_receipt['baselineTapBefore']<=ready_receipt['baselineTapAfter']<=rr[0]['response']['runnerReceive'],'runner baseline readiness invalid')
    independent=decoded.get('independentScreenshots');require(isinstance(independent,list) and len(independent)==2 and [r.get('phase') for r in independent]==['before','after'] and all(r.get('label')=='Copy Details' and type(r.get('decodedMarker')) is int and r['decodedMarker'] in draw_ids for r in independent),'independent steady-state pixel identity missing')
    for pixels,specification,receipt in zip(independent,decode_input['independentScreenshots'],[before,after]):
        require(pixels.get('path')==specification.get('path') and Path(specification['path']).name==receipt['name']+'.png' and Path(specification['path']).parent.name=='raw-runner' and pixels.get('pngSHA256')==receipt['pngSHA256'],'decoded independent PNG association differs')
    require(ready_receipt['baselineTapBefore']+app_offset[0]-runner_offset[1]<=ready[0]['uptime']<=ready_receipt['baselineTapAfter']+app_offset[1]-runner_offset[0],'actual baseline tap and app ready event do not overlap')
    require(after['acquisitionBefore']+app_offset[0]-runner_offset[1]>=strip['complete']['stoppedUptime'],'after screenshot not conservatively beyond strip stop')
    require(independent[0]['decodedMarker']<min(ids) and independent[1]['decodedMarker']>max(ids),'independent pixels do not bracket calibration')
    for receipt in receipts+[before,after]:require(receipt['copyBefore']['frame']==before['copyBefore']['frame'] and receipt['markerFrameBefore']==before['markerFrameBefore'] and receipt['windowFrameBefore']==before['windowFrameBefore'],'ROI drift across calibration')
    witness_ids=ids|{r['decodedMarker'] for r in independent}
    witnesses=decoded.get('observations');require(isinstance(witnesses,list),'missing matching video pixel witnesses')
    expected_witnesses=[f for f in frames if f.get('marker') in witness_ids]
    require(len(witnesses)==len(expected_witnesses) and len(witnesses)>0,'missing/extra matching video pixel inventory')
    for observed,frame in zip(witnesses,expected_witnesses):
        require(type(observed.get('index')) is int and observed['index']==frame['index'] and observed.get('marker')==frame['marker'] and observed.get('pts')==frame['pts'] and observed.get('endPTS')==frame['endPTS'] and observed.get('label')=='Copy Details','video/screenshot pixel identity is unknown or differs')
    selected,pts=evidence_window(frames,offset,ready[0]['uptime'],commands[-1]['afterUptime'])
    previous=0
    for row in selected:
        marker=row.get('marker');require(type(marker) is int and marker in draw_ids and marker>=previous,'unknown/reordered strip pixels in fixed window');previous=marker
        require(row['endPTS']+offset[1]>=draw_ids[marker]['drawBeforeUptime'],'video marker predates possible draw')
    return {'schema':'p1-calibration-capability-result-v1','calibration_feasible':True,'admissionEligible':False,'feedback_lifetime_established':False,'input_overlap_established':False,'full_matrix_complete':False,
        'appMinusHost':app_offset,'runnerMinusHost':runner_offset,'hostMinusVideoPTS':host_video,'appMinusVideoPTS':offset,'strip_costs':costs,
        'acquisition_seconds':[r['acquisitionAfter']-r['acquisitionBefore'] for r in receipts],'possiblePTSWindow':pts,'window_frame_count':len(selected),
        'limits':'Conditional stable-unit-rate continuous clocks and actual matching pixel intervals; acquisition brackets do not independently prove compositor freshness. No clipboard notification, production timer, input overlap, or feedback lifetime claim.'}
