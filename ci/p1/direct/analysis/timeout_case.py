"""Offline direct-window timeout predicates; upstream ownership is mandatory.

This one-case result never admits a physical-device result, the old guest-video
calibration, another scenario/device, or continuous visibility between samples.
"""
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import importlib.util,json,math,sys

LOCAL=Path(__file__).resolve().parents[1]
VIDEO=LOCAL.parent/'window-capture-candidate/ci/p1/video'
for folder in (VIDEO,LOCAL/'clock',LOCAL/'protocol',LOCAL/'fixture',LOCAL/'handoff'):
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
import bound_clocks,direct_coverage,transitions,lifetime,draw_receipts,handoff_contract,evidence_joins
ORIGINAL_SHA='7aac4a122f5f81b1a883f6e473fc4ecdb731b9fa71c73675429ff468655f0b04'
source=VIDEO/'analyze.py'
if sha256(source.read_bytes()).hexdigest()!=ORIGINAL_SHA:raise ValueError('maintained analysis source drift')
spec=importlib.util.spec_from_file_location('maintained_direct_timeout_analysis',source)
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)

def require(ok,message):
    if not ok:raise ValueError(message)

def envelope(value):
    low,high=bound_clocks.uptime(value)
    return low.numerator//low.denominator,-(-high.numerator//high.denominator)

def outward(interval):
    lo,hi=interval
    return lo.numerator//lo.denominator,-(-hi.numerator//hi.denominator)

def bind_transport(commands,clock_document,events,raw_receipts):
    expected=['clock']*8+['ready','mid']+['clock']*8+['third','post']+['clock']*8+['finish']
    require(type(commands) is list and len(commands)==29 and len(raw_receipts)==29,'complete29 requests')
    clocks=clock_document['appExchanges'];by_id={r['requestID']:r for r in clocks}
    app_commands={r.get('kind'):r for r in events if r.get('type')=='command'}
    previous_host=0;previous_app=0
    for identifier,(row,kind,raw) in enumerate(zip(commands,expected,raw_receipts),1):
        require(set(row)=={'id','kind','hostBeforeNs','hostAfterNs','response'} and type(row['id']) is int and row['id']==identifier and row['kind']==kind,'command identity')
        hb,ha=row['hostBeforeNs'],row['hostAfterNs']
        require(type(hb) is int and type(ha) is int and previous_host<=hb<=ha and ha-hb<=5_000_000_000,'host response bracket')
        previous_host=ha
        require(raw['requestBytes']==handoff_contract.canonical({'id':identifier,'kind':kind}) and raw['hostBeforeNs']==hb and raw['hostAfterNs']==ha and raw['errorType'] is None,'retained request receipt')
        response=handoff_contract.parse(raw['responseBytes'])
        require(response==row['response'] and set(response)==({'id','appReceive','appSend'}|({'phase'} if kind!='clock' else set())),'retained response')
        require(type(response['id']) is int and response['id']==identifier,'response identity')
        ar,ass=response['appReceive'],response['appSend']
        bound_clocks.uptime(ar);bound_clocks.uptime(ass)
        require(previous_app<=ar<=ass,'app response chronology');previous_app=ass
        if kind=='clock':
            exchange=by_id.get(identifier,{})
            require(exchange.get('hostBeforeNs')==hb and exchange.get('hostAfterNs')==ha and exchange.get('appReceive')==ar and exchange.get('appSend')==ass,'clock receipt binding')
        else:
            event=app_commands.get(kind,{})
            require(event.get('id')==identifier and event.get('phase')==response['phase'] and event.get('uptime')==ar and ar<=event.get('afterUptime',-1)<=ass,'app command binding')


def classify_ocr(row):
    observations=row.get('observations')
    require(type(observations) is list and len(observations)<=64,'bounded OCR observations')
    recognized=[]
    for observation in observations:
        require(type(observation) is dict and set(observation)=={'text','confidence','box'},'OCR observation schema')
        text=observation['text'];confidence=observation['confidence'];box=observation['box']
        require(type(text) is str and len(text)<=4096 and type(confidence) in (int,float) and math.isfinite(confidence) and 0<=confidence<=1,'OCR text/confidence')
        require(type(box) is list and len(box)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in box),'OCR box')
        if confidence>=.9:recognized.append(text)
    label=recognized[0] if len(recognized)==1 and recognized[0] in ('Copied','Copy Details') else 'unknown'
    require(row.get('label')==label,'OCR derived label mismatch')
    return label


def inspect(*,clock_document,expected_identity,commands,raw_receipts,events,strip,controls,
            records,marker_proofs,ocr_input_bytes,ocr_result,independent,stream_binding_hash,screenshot_exports):
    clock=bound_clocks.inspect(clock_document,expected_identity)
    bind_transport(commands,clock_document,events,raw_receipts)
    original.input_receipt(controls,'timeout')
    costs=original.journal_metrics(events,'timeout')
    draw_ids,strip_costs=original.strip_metrics(strip)
    anchors=draw_receipts.validate_initial_draw_receipts(events,expected_identity['session'])
    require(anchors['drawMaxSeconds']<=.005,'registration draw exceeds5ms')
    span=strip['draws'][-1]['drawAfterUptime']-strip['draws'][0]['drawBeforeUptime']
    require((anchors['drawTotalSeconds']+strip_costs['totalDrawSeconds']+strip_costs['totalTickSeconds'])/span<=.10,'combined measured observer work exceeds10percent')
    start,end,phases=original.protocol_window(events)
    for row in clock_document['appExchanges']:
        lo,hi=phases[row['phase']]
        require(lo<=row['appReceive']<=row['appSend']<=hi,'clock sample outside protocol phase')
    coverage_rows=[]
    for row in records:
        item=dict(row);item['ordinal']=row['index']+1;coverage_rows.append(item)
    covered=direct_coverage.coverage(coverage_rows,clock['commonAppMinusMach'],envelope(start),envelope(end))
    require(type(ocr_input_bytes) is bytes and ocr_result.get('schema')=='p1-direct-control-ocr-v1' and ocr_result.get('session')==expected_identity['session'] and ocr_result.get('inputSHA256')==sha256(ocr_input_bytes).hexdigest() and ocr_result.get('admissionEligible') is False and ocr_result.get('allFramesClassified') is True,'OCR retained input/result identity')
    require(ocr_input_bytes==evidence_joins.ocr_manifest(records,expected_identity['session']),'OCR manifest differs from all fixed control frames')
    complete=[r for r in records if r['newFrame']]
    require(type(ocr_result.get('frames')) is list and len(ocr_result['frames'])==len(complete) and len(marker_proofs)==len(complete),'all complete OCR/marker records')
    observed={}
    for frame,ocr,marker in zip(complete,ocr_result['frames'],marker_proofs):
        control=frame['regions'][0]
        require(type(ocr.get('record')) is int and ocr.get('record')==frame['index']+1 and ocr.get('file')==frame['packedPixels'] and ocr.get('packedSHA256')==frame['packedSHA256'] and ocr.get('controlSHA256')==control['sha256'] and ocr.get('pixelSize')==control['rectangle'][2:] and ocr.get('resampled') is False and ocr.get('absenceEstablished') is False,'OCR actual control binding')
        require(marker.get('schema')=='p1-direct-complete-crop-geometry-v1' and type(marker.get('nativeIndex')) is int and marker.get('nativeIndex')==frame['index'] and marker.get('session')==expected_identity['session'] and marker.get('packedPixelSHA256')==frame['packedSHA256'] and marker.get('displayTimeMach')==str(frame['displayTicks']) and marker.get('streamBindingProofSHA256')==stream_binding_hash and marker.get('geometryProof',{}).get('primitiveValid') is True and marker.get('admissionEligible') is False,'per-frame pixel geometry binding')
        observed[frame['index']+1]={'label':classify_ocr(ocr),'marker':marker['actualMarker']}
    selected=[];previous_marker=0
    for timed in covered['observations']:
        row=observed[timed['record']];marker=row['marker']
        require(type(marker) is int and marker in draw_ids and marker>=previous_marker,'actual marker inventory/order');previous_marker=marker
        require(timed['appNs'][1]>=bound_clocks.uptime(draw_ids[marker]['drawBeforeUptime'])[0],'pixels predate possible draw')
        require(row['label'] in ('Copied','Copy Details'),'unknown label inside fixed evidence window')
        selected.append({'label':row['label'],'appNs':outward(timed['appNs']),'record':timed['record']})
    actual=[]
    for row in events:
        if row.get('type')=='clipboard':
            require(start<row['uptime']<end,'clipboard outside evidence window')
            actual.append(dict(row,receiptNs=envelope(row['uptime'])))
    transitions.validate('timeout',actual,[r for r in events if r.get('type')=='transition'])
    require(any(r['label']=='Copy Details' and r['appNs'][1]<actual[0]['receiptNs'][0] for r in selected),'pre-copy label missing')
    require(type(independent) is list and len(independent)==2 and {r.get('phase') for r in independent}=={'before','after'},'independent screenshots missing')
    exported=evidence_joins.screenshot_exports(screenshot_exports,expected_identity['simulatorUDID'],controls)
    for row in independent:
        require(all(row.get(k)==v for k,v in exported[row['phase']].items()),'independent actual PNG binding')
        require(classify_ocr(row)=='Copy Details' and type(row.get('decodedMarker')) is int and row['decodedMarker'] in draw_ids,'independent steady-state pixels')
    before=next(r for r in independent if r['phase']=='before');after=next(r for r in independent if r['phase']=='after')
    # These ordinal relations bind independent screenshots to real captured
    # calibration-phase pixels. Draw receipts never timestamp screenshots.
    phase_markers=[]
    for phase,(lo,hi) in phases.items():
        lower=bound_clocks.uptime(lo)[1]
        upper=bound_clocks.uptime(hi)[0]
        witnesses=[observed[r['record']]['marker'] for r in covered['observations']
                   if lower<=r['appNs'][0] and r['appNs'][1]<=upper]
        require(witnesses,'no conservative pixel witness in calibration phase: '+phase)
        phase_markers.extend(witnesses)
    require(before['decodedMarker']<min(phase_markers) and after['decodedMarker']>max(phase_markers),'independent screenshots do not bracket calibration-phase pixels')
    timing=lifetime.lifetime(selected,actual[0]['receiptNs'])
    return {'schema':'p1-direct-timeout-conditional-v1','conditionalTimeoutEvidence':True,
            'clock':clock,'coverage':covered,'lifetime':timing,'observerCosts':costs,
            'stripCosts':strip_costs,'registrationCosts':anchors,'admissionEligible':False,
            'fullP1Established':False,'inputOverlapEstablished':False,'oldVideoCalibrationEstablished':False,
            'limits':'Receipt-relative sampled WindowServer labels; source-locality and stable-rate assumptions remain conditional. No continuous visibility or physical-device presentation claim.'}
