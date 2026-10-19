"""Strict retained ROI/record binding. No pixel geometry or OCR inference here."""
from fractions import Fraction
from hashlib import sha256
import math
import re
from copy import deepcopy

ROLES=('control','marker','anchor-1','anchor-2','anchor-3','anchor-4')

def require(ok,message):
    if not ok:raise ValueError(message)

def integer(value,minimum=0,maximum=2**64-1):
    require(type(value) is int and minimum<=value<=maximum,'bounded record integer');return value

def _inspect(samples,plan,*,timebase,load,expected_geometry,single=False):
    require(type(samples) is dict and set(samples)=={'frames','completeFrames','deliveredRecords','overflowRecords','copiedBytes','error'},'exact sample inventory')
    require(samples['error'] is None and type(samples['overflowRecords']) is int and samples['overflowRecords']==0,'sample failure/overflow')
    require(single or (type(expected_geometry) is tuple and len(expected_geometry)==3),'final stream geometry required')
    if not single:
        reference_rect,reference_scale,reference_factor=expected_geometry
        require(type(reference_rect) is list and len(reference_rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in reference_rect) and reference_rect[2]>0 and reference_rect[3]>0,'reference content rectangle')
        require(all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (reference_scale,reference_factor)),'reference content scales')
    rows=samples['frames'];require(type(rows) is list and 1<=len(rows)<=6000,'bounded all-record inventory')
    require(integer(samples['deliveredRecords'])==len(rows),'delivered record mismatch')
    require(not single or (len(rows)==1 and rows[0].get('statusName')=='complete'),'one complete prerequisite row required')
    numer,denom=timebase;integer(numer,1,2**32-1);integer(denom,1,2**32-1)
    require(type(plan) is dict and set(plan)=={'schema','session','windowID','geometrySHA256','sourceWidth','sourceHeight','sourceStride','regions'},'exact plan')
    require(plan['schema']=='p1-direct-roi-plan-v1','plan schema')
    for key in ('session','geometrySHA256'):
        require(type(plan[key]) is str and re.fullmatch('[0-9a-f]{'+str(32 if key=='session' else 64)+'}',plan[key]) is not None,'plan identity')
    integer(plan['windowID'],1,2**32-1)
    width=integer(plan['sourceWidth'],1,2048);height=integer(plan['sourceHeight'],1,2048);stride=integer(plan['sourceStride'],width*4,width*4+256)
    require(stride%4==0,'plan stride')
    regions=plan['regions'];require(type(regions) is list and len(regions)==6,'six regions')
    require(tuple(r.get('role') for r in regions)==ROLES,'fixed region roles')
    expected=[];offset=0
    for region in regions:
        require(set(region)=={'role','x','y','width','height'},'exact plan region')
        x=integer(region['x']);y=integer(region['y']);w=integer(region['width'],1,2048);h=integer(region['height'],1,2048)
        require(x+w<=plan['sourceWidth'] and y+h<=plan['sourceHeight'],'plan bounds')
        for old in expected:
            ox,oy,ow,oh=old['rectangle']
            require(not (x<ox+ow and ox<x+w and y<oy+oh and oy<y+h),'overlapping plan regions')
        expected.append({'role':region['role'],'rectangle':[x,y,w,h],'offset':offset,'bytes':w*h*4,'stride':w*4})
        offset+=w*h*4
    require(offset<=512*1024,'combined ROI budget')
    result=[];complete=0;total=0;previous_callback=None;previous_display=None;geometry=None;started=False;stopped=False
    for ordinal,row in enumerate(rows):
        index=integer(row.get('index'),0,5999) if single else ordinal
        require(type(row) is dict and 'error' not in row and integer(row.get('index'))==index,'record sequence/error')
        before=integer(row.get('callbackBeforeMach'),1);after=integer(row.get('callbackAfterMach'),1)
        require(before<=after and (previous_callback is None or previous_callback<=before),'callback chronology')
        require(Fraction((after-before)*numer,denom)<=5_000_000,'measured callback exceeds5ms')
        previous_callback=after
        base_fields={'index','callbackBeforeMach','callbackAfterMach','status','statusName','newFrame','ptsValue','ptsTimescale','ptsFlags'}
        complete_fields={'session','geometrySHA256','displayTimeMach','width','height','bytesPerRow','contentRect','contentScale','scaleFactor','copiedBytes','packedPixels','packedPixelSHA256','regions'}
        require(set(row)==base_fields|(complete_fields if row.get('statusName')=='complete' else set()),'exact native row schema')
        require(type(row['ptsValue']) is int and -(2**63)<=row['ptsValue']<2**63,'PTS value')
        require(type(row['ptsTimescale']) is int and -(2**31)<=row['ptsTimescale']<2**31,'PTS timescale')
        flags=integer(row['ptsFlags'],0,2**32-1)
        if row.get('statusName')=='complete':require(row['ptsTimescale']>0 and flags&1 and flags&28==0,'numeric PTS flags')
        name=row.get('statusName');require(not stopped and name in ('started','stopped','idle','complete'),'unknown/poststop status')
        # Public SCFrameStatus raw values: complete0, idle1, blank2, suspended3,
        # started4, stopped5. Unknown/blank/suspended never bridge coverage.
        require(type(row.get('status')) is int and row['status']=={'complete':0,'idle':1,'started':4,'stopped':5}[name],'status correspondence')
        if name!='complete':
            require(row.get('newFrame') is False,'noncomplete claims new pixels')
            if name=='started':require(not started and complete==0,'started chronology');started=True
            if name=='stopped':stopped=True
            result.append({'index':index,'status':name,'newFrame':False});continue
        require(row.get('newFrame') is True and row.get('session')==plan['session'] and row.get('geometrySHA256')==plan['geometrySHA256'],'frame plan/session binding')
        display=integer(row.get('displayTimeMach'),1)
        require(previous_display is None or previous_display<display,'display chronology');previous_display=display
        require([row.get('width'),row.get('height'),row.get('bytesPerRow')]==[plan['sourceWidth'],plan['sourceHeight'],plan['sourceStride']],'frame layout differs')
        rect=row.get('contentRect');scale=row.get('contentScale');factor=row.get('scaleFactor')
        require(type(rect) is list and len(rect)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect) and rect[2]>0 and rect[3]>0,'content rectangle')
        require(all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (scale,factor)),'content scale')
        require(all(type(row.get(k)) is int for k in ('width','height','bytesPerRow')),'exact frame dimensions')
        current=(rect,scale,factor)
        if geometry is not None:require(current==geometry,'frame geometry replacement')
        if not single:require(current==expected_geometry,'initial geometry differs from finalized identity')
        geometry=deepcopy(current)
        filename=f'frame-{index:05d}.rois.bgra';require(row.get('packedPixels')==filename,'packed filename')
        raw=load(filename)
        require(type(raw) is bytes and len(raw)==offset and sha256(raw).hexdigest()==row.get('packedPixelSHA256'),'retained packed bytes/hash')
        require(integer(row.get('copiedBytes'))==offset,'copied-byte receipt')
        actual=row.get('regions');require(type(actual) is list and len(actual)==6,'complete region manifest')
        crops={}
        for measured,wanted in zip(actual,expected):
            require(type(measured) is dict and set(measured)==set(wanted)|{'sha256'},'exact region manifest')
            require(type(measured['rectangle']) is list and len(measured['rectangle'])==4 and all(type(v) is int for v in measured['rectangle']),'exact rectangle integers')
            require(all(type(measured[k]) is int for k in ('offset','bytes','stride')),'exact region integers')
            require(all(measured[k]==v for k,v in wanted.items()),'region plan mismatch')
            crop=raw[wanted['offset']:wanted['offset']+wanted['bytes']]
            require(sha256(crop).hexdigest()==measured['sha256'],'region hash')
            crops[wanted['role']]=crop
        total+=len(raw);complete+=1
        require(total<=3*1024**3,'aggregate raw limit')
        result.append({'index':index,'status':name,'newFrame':True,'displayTicks':display,
                       'timebaseNumer':numer,'timebaseDenom':denom,'crops':crops,'regions':deepcopy(actual),
                       'packedPixels':filename,'packedSHA256':sha256(raw).hexdigest(),
                       'sourceGeometry':deepcopy(current),'callbackBeforeMach':before,'callbackAfterMach':after})
    require(integer(samples['completeFrames'])==complete and complete>=(1 if single else 2),'complete record count')
    require(integer(samples['copiedBytes'])==total,'total bytes mismatch')
    return result


def inspect(samples,plan,*,timebase,load,expected_geometry):
    return _inspect(samples,plan,timebase=timebase,load=load,expected_geometry=expected_geometry)


def inspect_first(row,plan,*,timebase,load):
    """Verify one raw prerequisite receipt; never assert the complete census.

    Caller retains the exact manifest bytes/hash and proves it is the helper's
    actual first complete record. Final inspect() still verifies every delivered
    row, its index/order, total count, and immutable promoted stream geometry.
    """
    require(type(row) is dict and row.get('statusName')=='complete','first complete prerequisite')
    sample={'frames':[row],'completeFrames':1,'deliveredRecords':1,'overflowRecords':0,
            'copiedBytes':row.get('copiedBytes'),'error':None}
    result=_inspect(sample,plan,timebase=timebase,load=load,expected_geometry=None,single=True)[0]
    result['scope']='single-complete-retained-prerequisite-only'
    result['allDeliveredRecordsEstablished']=False
    result['admissionEligible']=False
    return result


def ocr_input(samples,plan,*,timebase,load,expected_geometry):
    """Build OCR input only from the validated fixed control ROI manifest."""
    import json
    records=inspect(samples,plan,timebase=timebase,load=load,expected_geometry=expected_geometry)
    frames=[]
    for row in records:
        if not row['newFrame']:continue
        control=row['regions'][0]
        require(control['role']=='control','fixed control region')
        frames.append({'record':row['index']+1,'file':row['packedPixels'],
                       'packedSHA256':row['packedSHA256'],'offset':control['offset'],
                       'width':control['rectangle'][2],'height':control['rectangle'][3],
                       'controlSHA256':control['sha256']})
    document={'schema':'p1-direct-control-ocr-input-v1','session':plan['session'],'frames':frames}
    return json.dumps(document,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
