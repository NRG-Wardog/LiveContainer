"""Strict raw XCTest/attachment association validation for one diagnostic case."""
import math
from pathlib import Path

METHODS={'timeout':'testProbeTimeoutPixels','replacement':'testProbeReplacementPixels','dismissal':'testProbeDismissalPixels'}

def require(ok,message):
    if not ok:raise ValueError(message)
def finite(v):return type(v) in (int,float) and math.isfinite(v)

def frame(row):
    require(isinstance(row,list) and len(row)==4 and all(finite(v) for v in row) and row[2]>0 and row[3]>0,'invalid control geometry')
    return row

def input_receipt(row,scenario):
    require(row.get('schema')=='p1-video-input-v1' and row.get('scenario')==scenario,'input identity mismatch')
    keys=['firstBefore','firstAfter'];drivers={'firstDriver':'normal-XCTest-tap'}
    if scenario!='timeout':
        keys+=['secondDelayBefore','secondDelayAfter','secondBefore','secondAfter','thirdBefore','thirdAfter'];drivers.update(secondDriver='experimental-XCTest-coordinate-tap',thirdDriver='normal-XCTest-third-tap')
        require(row.get('secondDelayRequested')==1.10,'changed second-input schedule')
        require(row.get('thirdHittable') is True and row.get('thirdLabelBefore')=='Copy Details','ordinary third tap unavailable')
    else:require(not any(k.startswith(('second','third')) for k in row),'timeout has extra input')
    require(all(row.get(k)==v for k,v in drivers.items()),'input driver mismatch')
    values=[row.get(k) for k in keys]
    require(all(finite(v) and v>0 for v in values) and values==sorted(values),'input clocks invalid/out of order')
    require(all(row[keys[i]]<row[keys[i+1]] for i in range(0,len(keys),2)),'zero-duration input')
    return row

def leaves(value):
    if isinstance(value,dict):
        if value.get('nodeType')=='Test Case':yield value
        for child in value.values():yield from leaves(child)
    elif isinstance(value,list):
        for child in value:yield from leaves(child)

def verify(root,summary,tests,scenario,device,parse,ordinary,valid_png):
    require(scenario in METHODS,'wrong case')
    fields=['passedTests','failedTests','skippedTests','totalTestCount','expectedFailures']
    require(summary.get('result')=='Passed' and all(type(summary.get(k)) is int for k in fields) and
        [summary[k] for k in fields]==[1,0,0,1,0],'one passed/zero skipped test required')
    config=summary.get('devicesAndConfigurations');require(isinstance(config,list) and len(config)==1 and config[0].get('device',{}).get('deviceId')==device,'wrong XCTest simulator')
    expected='P0SignInUITests/'+METHODS[scenario]+'()'
    url='test://com.apple.xcode/P0SignIn/P0SignInUITests/P0SignInUITests/'+METHODS[scenario]
    cases=list(leaves(tests))
    require(len(cases)==1 and cases[0].get('nodeIdentifier') in [expected,expected[:-2]] and cases[0].get('result')=='Passed','wrong/missing raw XCTest method')
    if 'nodeIdentifierURL' in cases[0]:require(cases[0]['nodeIdentifierURL']==url,'wrong raw XCTest target URL')
    manifest=parse(ordinary(root,'manifest.json'))
    require(isinstance(manifest,list) and len(manifest)==1 and manifest[0].get('testIdentifier')==expected and manifest[0].get('testIdentifierURL')==url,'attachment test association mismatch')
    attachments=manifest[0].get('attachments');require(isinstance(attachments,list) and attachments,'missing attachment list')
    by_name={};files=set()
    for row in attachments:
        require(row.get('deviceId')==device,'attachment simulator mismatch')
        path=ordinary(root,row.get('exportedFileName'))
        require(path.name not in files,'reused exported attachment');files.add(path.name)
        name=row.get('suggestedHumanReadableName',row.get('attachmentName'))
        require(isinstance(name,str) and name not in by_name,'missing/duplicate attachment name')
        by_name[name]=(path,row)
    def attachment(name):
        matches=[(p,r) for n,(p,r) in by_name.items() if n==name or n.startswith(name+'_')]
        require(len(matches)==1,'missing/duplicate associated attachment: '+name);return matches[0][0]
    def report(name,schema):
        value=parse(attachment(f'video-{scenario}-'+name))
        require(value.get('schema')==schema and value.get('scenario')==scenario,'wrong associated report identity');return value
    controls=report('controls','p1-video-controls-v1');inputs=input_receipt(report('input','p1-video-input-v1'),scenario)
    complete=report('complete','p1-video-completion-v1')
    require(complete.get('completed') is True and complete.get('admissionEligible') is False and complete.get('copyAfterLabel')=='Copy Details' and complete.get('copyAfterHittable') is True,'incomplete fixture test')
    window=frame(controls.get('windowFrame'))
    for key in ['copyFrame','markerFrame']:
        r=frame(controls.get(key));require(r[0]>=window[0] and r[1]>=window[1] and r[0]+r[2]<=window[0]+window[2]+1 and r[1]+r[3]<=window[1]+window[3]+1,'control outside viewport')
    require(controls.get('copyHittable') is True and controls.get('copyLabel')=='Copy Details','initial control unavailable')
    screenshots={}
    for phase in ['before','after']:
        p=attachment(f'video-{scenario}-{phase}');require(valid_png(p.read_bytes()),'invalid independent screenshot');screenshots[phase]=str(p)
    require(screenshots['before']!=screenshots['after'],'reused independent screenshot')
    return controls,inputs,screenshots
