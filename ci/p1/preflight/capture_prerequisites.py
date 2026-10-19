"""Read-only screen-capture prerequisites. Never requests access or pixels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import shutil
import sys
import capture
import process_scope

HERE=Path(__file__).resolve().parent
SDK_ROOT=Path('/Applications/Xcode_26.4.1.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs')

def header_excerpt(sdk):
    path=Path(sdk)
    if not path.is_absolute() or not path.resolve().is_relative_to(SDK_ROOT.resolve()):raise ValueError('untrusted SDK path')
    path=path/'System/Library/Frameworks/ScreenCaptureKit.framework/Headers/SCStream.h'
    resolved=path.resolve()
    if not resolved.is_relative_to(SDK_ROOT.resolve()):raise ValueError('header escapes pinned SDK')
    fd=os.open(resolved,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size>2*1024*1024:raise ValueError('invalid SDK header')
        with os.fdopen(fd,'rb') as stream:fd=None;raw=stream.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('SDK header too large')
    finally:
        if fd is not None:os.close(fd)
    text=raw.decode('utf8');needle='SCStreamFrameInfoDisplayTime';positions=[];start=0
    while True:
        i=text.find(needle,start)
        if i<0:break
        positions.append(i);start=i+len(needle)
    if not positions or len(positions)>8:raise ValueError('SDK display time declaration ambiguous')
    excerpts=[text[max(0,i-1500):min(len(text),i+300)] for i in positions]
    return {'sdk':str(Path(sdk)),'headerSHA256':hashlib.sha256(raw).hexdigest(),'excerpts':excerpts,'unitsRequireReview':True,'timestampUnitsEstablished':False}

def validate_result(row):
    fixed={'schema':'p1-capture-prerequisites-v1','permissionRequested':False,'pixelsCaptured':False,'environmentModified':False,'windowOwnershipEstablished':False,'timestampUnitsEstablished':False,'admissionEligible':False}
    if not isinstance(row,dict) or any(row.get(k)!=v or (type(v) is bool and type(row.get(k)) is not bool) for k,v in fixed.items()):raise ValueError('invalid prerequisite result')
    if type(row.get('screenCapturePreflight')) is not bool:raise ValueError('missing permission result')
    if not row['screenCapturePreflight']:
        if row.get('enumerationAttempted') is not False or any(k in row for k in ('simulatorProcessCount','simulatorOnScreenWindowCount','windowEnumerationAvailable')):raise ValueError('enumeration after denied permission')
        return False
    if row.get('enumerationAttempted') is not True or type(row.get('windowEnumerationAvailable')) is not bool:raise ValueError('enumeration state absent')
    if any(type(row.get(k)) is not int or row[k]<0 for k in ('simulatorProcessCount','simulatorOnScreenWindowCount')):raise ValueError('invalid diagnostic count')
    return row['windowEnumerationAvailable']

def execute(host,inputs,approved,output):
    capture.validate(host,inputs,approved)
    if json.loads(inputs.read_text())['scope']!='capture-prerequisites-only-no-admission':raise ValueError('wrong prerequisite scope')
    if output.exists():raise ValueError('fresh prerequisite evidence required')
    output.mkdir(parents=True);scope=process_scope.Scope(output,capture_prerequisites=True);logs=output/'commands';logs.mkdir();command=process_scope.Commands(scope,logs)
    result={'schema':'p1-capture-prerequisite-collection-v1','admissionEligible':False,'collection_complete':False,'errors':[],'permissionChanged':False,'pixelsCaptured':False}
    try:
        shutil.copytree(HERE,output/'harness',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(inputs,output/'approved-inputs.json')
        result['workflowSHA256']=capture.sha(host/'.github/workflows/p1-native-candidate.yml')
        result['github']={k:os.environ.get(k) for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY')}
        if os.environ.get('ImageVersion')!='20261013.0424.1':raise ValueError('pinned image differs')
        version=command('xcodebuild','-version',timeout=5).strip()
        if version!='Xcode 26.4.1\nBuild version 17E202':raise ValueError('pinned Xcode differs')
        result['xcodeVersion']=version
        sdk=command('xcrun','--sdk','macosx','--show-sdk-path',timeout=10).strip()
        result['header']=json.loads(command(sys.executable,'-B',HERE/'capture_prerequisites.py','--header-only',sdk,timeout=5))
        process_scope.atomic(output/'sdk-displaytime.json',result['header'])
        binary=output/'capture-prerequisites'
        command('xcrun','swiftc',HERE/'capture_prerequisites.swift','-o',binary,timeout=30)
        row=json.loads(command(binary,timeout=10));result['prerequisites']=row
        result['existingAccessAndEnumeration']=validate_result(row)
        result['collection_complete']=True
        result['helperSHA256']=capture.sha(HERE/'capture_prerequisites.swift')
        result['approvedInputsSHA256']=approved
    except Exception as error:result['errors'].append(process_scope.error_info(error))
    finally:
        try:scope.close()
        except Exception as error:result['errors'].append(process_scope.error_info(error));result['collection_complete']=False
        process_scope.atomic(output/'capture-prerequisite-result.json',result)
    return result['collection_complete'] and result.get('existingAccessAndEnumeration') is True and not result['errors']

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--header-only':
        print(json.dumps(header_excerpt(sys.argv[2]),sort_keys=True));raise SystemExit(0)
    p=argparse.ArgumentParser();p.add_argument('--host-root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--approved-inputs-sha256',required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    raise SystemExit(0 if execute(a.host_root.resolve(),a.inputs,a.approved_inputs_sha256,a.evidence) else 1)
