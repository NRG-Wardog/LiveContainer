"""Actual one-shot simulator discovery and descriptor-bound observer channels.

Caller supplies the retained, live XCTest command and existing Scope Commands.
No container PID inference, retries, screenshots or permission changes occur.
"""
from hashlib import sha256
from pathlib import Path
import time
from fixture_channel import Directory,parse,canonical,require
from native_process import clean
from native_case import timeout_started


class Channels:
    def __init__(self,command,native,*,device,session,app_id,runner_id,retain,remaining):
        self.command=command;self.native=native;self.device=device;self.session=session
        self.identifiers={'app':app_id,'runner':runner_id};self.retain=retain;self.remaining=remaining
        self.roots={};self.receipts={};self.attempted=set();self.directories={};self.hint=None
    def started(self,timeout):
        deadline=time.monotonic()+self.remaining(timeout);state={}
        while time.monotonic()<deadline:
            self.native.live()
            if timeout_started(self.native.folder/'command-0001.stdout',state):
                self.hint={'schema':'p1-direct-native-start-hint-v1','session':self.session,
                           'path':str(self.native.folder/'command-0001.stdout'),
                           'hostMonotonicNs':time.monotonic_ns(),'readinessEstablished':False}
                self.retain('startup-hint',canonical(self.hint));return self.hint
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        raise TimeoutError('original timeout method startup hint missing')
    def discover(self,role,timeout):
        require(role in self.identifiers and self.hint is not None and role not in self.attempted,'one post-hint lookup per role')
        self.attempted.add(role);self.native.live()
        argv=['xcrun','simctl','get_app_container',self.device,self.identifiers[role],'data']
        row=self.command(*argv,timeout=min(30,self.remaining(timeout)),receipt=True)
        self.receipts[role]=row;self.retain(role+'-container-receipt',canonical(row));clean(row,argv)
        text=row.get('stdout');require(type(text) is str and '\n' not in text.strip() and text.strip(),'single container path')
        root=Path(text.strip());require(root.is_absolute() and root.resolve()==root and root.is_dir() and not root.is_symlink(),'canonical discovered container')
        self.native.live();self.roots[role]=root
        return {'role':role,'session':self.session,'device':self.device,'bundle':self.identifiers[role],
                'root':str(root),'commandReceiptSHA256':sha256(canonical(row)).hexdigest()}
    def geometry(self,timeout,validate_request):
        require(set(self.roots)=={'app','runner'},'both exact container roles required')
        paths={'runner':self.roots['runner']/'Documents/p1-capability'/self.session,
               'app':self.roots['app']/'Documents/p1-video/timeout'}
        deadline=time.monotonic()+self.remaining(timeout)
        while time.monotonic()<deadline:
            self.native.live()
            for role,path in paths.items():
                if role not in self.directories and (path.exists() or path.is_symlink()):
                    require(path.resolve()==path and path.is_dir() and not path.is_symlink(),'linked channel path')
                    self.directories[role]=Directory(path)
            if 'runner' in self.directories:
                failure_raw=self.directories['runner'].read('observer-error.json',32768)
                if failure_raw is not None:
                    # Preserve the actual native failure before rejecting it;
                    # it must never be hidden by a later geometry timeout.
                    self.retain('observer-error',failure_raw)
                    failure=parse(failure_raw)
                    require(type(failure) is dict and failure.get('schema')=='p1-direct-baseline-observer-error-v1' and
                            failure.get('session')==self.session and failure.get('scenario')=='timeout' and
                            failure.get('baselineTapReleased') is False and failure.get('admissionEligible') is False and
                            type(failure.get('phase')) is str and type(failure.get('error')) is str,
                            'foreign or malformed native observer failure')
                    raise RuntimeError('native observer rejected baseline: '+failure['error'])
            if set(self.directories)=={'app','runner'}:
                runner=self.directories['runner'];raw=runner.read('ready.json',8192)
                if raw is not None:
                    ready=parse(raw)
                    expected={'schema':'p1-direct-baseline-ready-v1','session':self.session,'geometryFile':'geometry.json',
                              'acknowledgementFile':'request.json','admissionEligible':False}
                    require(type(ready) is dict and set(ready)==set(expected)|{'geometryRequestSHA256'} and
                            all(type(ready[k]) is type(v) and ready[k]==v for k,v in expected.items()),'exact observer readiness')
                    geometry=runner.read('geometry.json',8192);require(geometry is not None and sha256(geometry).hexdigest()==ready['geometryRequestSHA256'],'immutable geometry hash')
                    request=validate_request(geometry)
                    require(request['session']==self.session and request['simulatorUDID']==self.device and
                            request['runnerBundleIdentifier']==self.identifiers['runner'] and request['scenario']=='timeout','observer launch identity mismatch')
                    require(runner.read('request.json') is None and runner.read('capture-ready-proof.json') is None,'stale observer acknowledgement')
                    app=self.directories['app'];require(app.read('request.json') is None and app.read('response.json') is None,'stale fixture exchange')
                    self.retain('observer-ready',raw);self.retain('observer-geometry',geometry)
                    self.geometry_bytes=geometry;self.ready_bytes=raw
                    return request
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        raise TimeoutError('session-bound observer geometry unavailable')
    def close(self):
        for directory in self.directories.values():directory.close()
