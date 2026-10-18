"""Exact created-device ownership for one same-runtime diagnostic."""
import json
import re
import time
import uuid
import boot_diagnostic as boot
import process_scope
import simulator_cleanup

TYPE='com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro'

def canonical(value):
    if not isinstance(value,str) or str(uuid.UUID(value))!=value.lower():raise ValueError('canonical device UUID required')
    return value.upper()

def inventory(raw):
    groups=boot.unique_json(raw).get('devices')
    if not isinstance(groups,dict) or not all(isinstance(rows,list) for rows in groups.values()):raise ValueError('invalid device inventory')
    result=[];seen=set()
    for runtime,rows in groups.items():
        for row in rows:
            if not isinstance(row,dict):raise ValueError('invalid device row')
            device=canonical(row.get('udid'))
            if device in seen:raise ValueError('duplicate device UUID')
            seen.add(device)
            result.append({'udid':device,'runtime':runtime,'state':row.get('state'),'isAvailable':row.get('isAvailable'),'deviceTypeIdentifier':row.get('deviceTypeIdentifier')})
    return result

def before(raw):
    rows=inventory(raw);original=[r for r in rows if r['udid']==boot.DEVICE]
    if len(original)!=1:raise ValueError('original comparison device identity drift')
    original=original[0];kind=original.get('deviceTypeIdentifier')
    if original['runtime']!=boot.RUNTIME or original['state']!='Shutdown' or original['isAvailable'] is not True or not isinstance(kind,str) or re.fullmatch(r'com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9-]{1,60}',kind) is None:raise ValueError('original comparison device identity drift')
    if any(r['state']=='Booted' for r in rows):raise ValueError('preexisting booted device')
    return {'preexisting':sorted(r['udid'] for r in rows),'runtime':boot.RUNTIME,'device_type':kind}

def available_type(kind):
    def parse(raw):
        rows=boot.unique_json(raw).get('devicetypes')
        if not isinstance(rows,list) or len([r for r in rows if isinstance(r,dict) and r.get('identifier')==kind])!=1:raise ValueError('comparison device type unavailable')
        return {'device_type':kind,'type_verified':True}
    return parse

def created_uuid(raw):
    text=raw.decode('ascii')
    if re.fullmatch(r'[A-Fa-f0-9-]{36}\n?',text) is None:raise ValueError('single complete create UUID required')
    return canonical(text.rstrip('\n'))

def validate(proof,session,device=None):
    if not isinstance(proof,dict) or proof.get('schema')!='p1-created-device-v1' or proof.get('session')!=session or re.fullmatch('[0-9a-f]{32}',session) is None:raise ValueError('created ownership session invalid')
    if proof.get('name')!='P1-stall-'+session or proof.get('runtime')!=boot.RUNTIME or not isinstance(proof.get('device_type'),str) or re.fullmatch(r'com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9-]{1,60}',proof.get('device_type','')) is None or proof.get('type_verified') is not True:raise ValueError('created ownership identity invalid')
    prior=proof.get('preexisting')
    if not isinstance(prior,list) or not prior or len(prior)!=len(set(prior)) or any(canonical(v)!=v for v in prior) or boot.DEVICE not in prior:raise ValueError('pre-create inventory invalid')
    if device is not None:
        if canonical(device)!=device or device in prior or device==boot.DEVICE or proof.get('device')!=device or proof.get('create_complete') is not True:raise ValueError('created UUID ownership unproved')
    return proof

def state_parser(device,allow_absent=False,kind=TYPE):
    def parse(raw):
        rows=inventory(raw);matches=[r for r in rows if r['udid']==device]
        if not matches and allow_absent:return {'devices':{boot.RUNTIME:[]}}
        if len(matches)!=1:raise ValueError('created device missing')
        row=matches[0]
        if row['runtime']!=boot.RUNTIME or row['deviceTypeIdentifier']!=kind or row['isAvailable'] is not True or row['state'] not in ('Shutdown','Booted'):raise ValueError('created device identity drift')
        return {'devices':{boot.RUNTIME:[{'udid':device,'state':row['state'],'isAvailable':True}]}}
    return parse

class Commands(boot.Commands):
    def __init__(self,scope,root,proof,error_sink=None):
        self.proof=validate(proof,proof.get('session'),proof.get('device'));self.device=proof['device']
        super().__init__(scope,root,error_sink)
    def __call__(self,*argv,timeout=15,cleanup=False,receipt=False):
        argv=list(argv)
        if argv==['xcrun','simctl','list','devices','--json']:parser=state_parser(self.device,True,self.proof['device_type']);label='created-state'
        elif argv==['xcrun','simctl','shutdown',self.device]:parser=boot.categorized_output;label='created-shutdown'
        elif argv==['xcrun','simctl','delete',self.device]:parser=boot.categorized_output;label='created-delete'
        else:raise ValueError('unallowlisted created cleanup command')
        row=self.run(label,argv,parser,timeout,cleanup)
        return {**row,'stdout':json.dumps(row['data']) if row['data'] is not None else '', 'stderr':''}

def cleanup(command,proof,settled):
    device=proof.get('device');validate(proof,proof.get('session'),device)
    if settled() is not True:raise ValueError('created cleanup writers unsettled')
    result=simulator_cleanup.confirm_shutdown(command,device,True)
    result['deleted']=False
    first=result['receipts'][0]['command']
    if simulator_cleanup.clean_command(first) and first.get('data')=={'devices':{boot.RUNTIME:[]}} and settled() is True:
        result.update(deleted=True,observed_absence=True)
        return result
    if not result['observed_shutdown'] or settled() is not True:return result
    # A state proof never discharges an unsettled host writer.
    row=command('xcrun','simctl','delete',device,timeout=15,cleanup=True,receipt=True)
    result['receipts'].append({'phase':'delete','command':row})
    if not simulator_cleanup.clean_command(row):result['command_failed']=True
    if settled() is not True:return result
    row=command('xcrun','simctl','list','devices','--json',timeout=15,cleanup=True,receipt=True)
    result['receipts'].append({'phase':'deleted-state','command':row})
    if not simulator_cleanup.clean_command(row):result['command_failed']=True
    else:
        data=boot.unique_json(row['stdout'])
        result['deleted']=data=={'devices':{boot.RUNTIME:[]}} and settled() is True
    return result

def backstop(evidence,errors,unsettled,wrap_error,proof):
    validate(proof,proof.get('session'),proof.get('device'))
    deadline=time.monotonic()+120
    class Scope(boot.BackstopScope):
        def remaining(self,seconds,cleanup=False):
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError('created backstop reserve exhausted')
            return min(float(seconds),15,left)
    def sink(primary,cleanup):
        wrapped=[wrap_error(e) for e in cleanup];unsettled.extend(wrapped)
        if primary is not None:errors.append(wrap_error(primary))
        elif wrapped:errors.append(wrapped[0])
    root=evidence/'bounded-created-backstop';root.mkdir(exist_ok=False)
    return Commands(Scope(),root,proof,sink)

def create_for_ui(scope,root):
    """Use the reviewed same-image/type/runtime creation route for phone UI."""
    import os
    if os.environ.get('ImageVersion')!='20261013.0424.1':raise ValueError('comparison runner image drift')
    root.mkdir(exist_ok=False);commands=boot.Commands(scope,root)
    def require(row):
        if not boot.clean(row):raise ValueError('fresh UI prerequisite failed')
        return row['data']
    version=require(commands.run('xcode-version',['xcodebuild','-version'],lambda raw:boot.tool_text(raw,'xcode')))
    if version['exact_public_tool_output'].strip()!='Xcode 26.4.1\nBuild version 17E202':raise ValueError('comparison Xcode drift')
    runtime=require(commands.run('runtime',['xcrun','simctl','list','runtimes','--json'],boot.exact_runtime))
    if runtime['buildversion']!='23C54':raise ValueError('comparison runtime build drift')
    state=require(commands.run('before-state',['xcrun','simctl','list','devices','--json'],before))
    verified=require(commands.run('device-type',['xcrun','simctl','list','devicetypes','--json'],available_type(state['device_type'])))
    proof={'schema':'p1-created-device-v1','session':scope.session,'name':'P1-stall-'+scope.session,**state,**verified}
    scope.begin_creation(proof)
    device=require(commands.run('create',['xcrun','simctl','create',proof['name'],proof['device_type'],boot.RUNTIME],created_uuid,timeout=30))
    proof.update(device=device,create_complete=True);validate(proof,scope.session,device)
    scope.fixture_created(proof)
    state=require(commands.run('created-state',['xcrun','simctl','list','devices','--json'],state_parser(device,kind=proof['device_type'])))
    if state['devices'][boot.RUNTIME][0]['state']!='Shutdown':raise ValueError('fresh initial Shutdown required')
    return proof
