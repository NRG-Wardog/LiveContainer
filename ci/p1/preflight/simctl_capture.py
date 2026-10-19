"""Diagnostic public screenshot backend. No capture-time estimate or UI admission."""
import hashlib
import json
import math
import fresh_device
import simulator_cleanup

def take(command,device,session,folder,phase,ordinal,valid_png):
    if phase not in ('pre','mid','post') or type(ordinal) is not int or ordinal not in (1,2,3):raise ValueError('fixed capture sample required')
    scope=command.scope;fixture=scope.fixture
    if not isinstance(fixture,dict) or fixture.get('device')!=device or fixture.get('deleted') is not False or fixture.get('stopped') is not False:raise ValueError('active owned fixture required')
    proof=fixture.get('owned_created');fresh_device.validate(proof,scope.session,device);fresh_device.validate(scope.creation_intent,scope.session)
    if any(proof.get(k)!=v for k,v in scope.creation_intent.items()) or not isinstance(session,str) or len(session)!=32 or any(c not in '0123456789abcdef' for c in session):raise ValueError('capture identity invalid')
    if not folder.is_dir() or folder.is_symlink():raise ValueError('owned capture directory required')
    name=f'capture-cli-{phase}-{ordinal}';png=folder/(name+'.png');receipt_path=folder/(name+'.json')
    if png.exists() or png.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():raise ValueError('capture destination reused')
    row=command('xcrun','simctl','io',device,'screenshot','--type=png',png,timeout=10,receipt=True)
    report={'schema':'p1-simctl-capture-probe-v1','session':session,'device':device,'phase':phase,'ordinal':ordinal,'name':name,'png':png.name,'command':row,'admissionEligible':False,'capture_timestamp_assumed':False}
    receipt_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    if not simulator_cleanup.clean_command(row) or row.get('writer_settled') is not True:raise ValueError('capture command failed or unsettled')
    launch=row.get('launch_receipt',{})
    if launch.get('state')!='pre-exec-observed' or launch.get('closed') is not True or launch.get('eof') is not True or launch.get('exec_failure') is not None:raise ValueError('capture launch unknown')
    timing=row.get('wait_timing',{});before=timing.get('command_started');after=timing.get('wait_finished')
    if not all(type(v) in (int,float) and math.isfinite(v) for v in (before,after)) or not before<after or timing.get('wait_returned') is not True:raise ValueError('capture host bracket unproved')
    if not png.is_file() or png.is_symlink():raise ValueError('capture PNG absent or linked')
    raw=png.read_bytes()
    if not valid_png(raw):raise ValueError('capture PNG invalid')
    report.update(hostBefore=before,hostAfter=after,host_clock='time.monotonic',pngSHA256=hashlib.sha256(raw).hexdigest(),pngBytes=len(raw),all_command_overhead_retained=True)
    receipt_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report
