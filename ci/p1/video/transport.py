"""Bounded external recording and fixture-owned file calibration transport."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def require(ok, message):
    if not ok: raise ValueError(message)


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, allow_nan=False)+'\n')
    temporary.replace(path)


class Channel:
    def __init__(self, root, output, device, command):
        require(root.is_dir() and not root.is_symlink(), 'missing/linked fixture channel')
        self.root, self.output, self.device, self.command = root.resolve(), output, device, command
        self.sequence = 0; self.exchanges = []; self.markers = []; self.commands = []
    def persist(self):
        atomic(self.output / 'calibration.json', {'schema':'p1-video-calibration-v1',
            'exchanges':self.exchanges,'markers':self.markers,'commands':self.commands,
            'clock':'host time.monotonic versus fixture ProcessInfo.systemUptime',
            'admissionEligible':False})
    def request(self, kind, **extra):
        self.sequence += 1
        request = dict(id=self.sequence, kind=kind, **extra)
        before = time.monotonic(); atomic(self.root/'request.json',request)
        deadline = before+5
        response = None
        while time.monotonic()<deadline:
            try:
                require(not (self.root/'response.json').is_symlink(),'linked response')
                value=json.loads((self.root/'response.json').read_text())
                if value.get('id')==self.sequence: response=value; break
            except (FileNotFoundError,json.JSONDecodeError): pass
            time.sleep(.001)
        after=time.monotonic()
        row={'id':self.sequence,'kind':kind,'hostBefore':before,'hostAfter':after,'response':response}
        self.commands.append(row); self.persist()
        require(response is not None,'fixture request timed out: '+kind)
        return row
    def calibrate(self, stage):
        require(stage in ['pre','mid','post'],'invalid calibration stage')
        for _ in range(8):
            row=self.request('clock'); response=row['response']
            self.exchanges.append({'id':row['id'],'stage':stage,'hostBefore':row['hostBefore'],
                'hostAfter':row['hostAfter'],'appReceive':response['appReceive'],'appSend':response['appSend']})
        for _ in range(3):
            marker=len(self.markers)+1
            row=self.request('marker',marker=marker)
            require(row['response'].get('marker')==marker,'marker acknowledgement mismatch')
            name=f'marker-{marker:03d}.png'
            before=time.monotonic()
            self.command('xcrun','simctl','io',self.device,'screenshot',self.output/name,timeout=20)
            after=time.monotonic()
            self.markers.append({'id':marker,'stage':stage,'hostBefore':before,'hostAfter':after,
                'screenshot':name,'markerCommandID':row['id']})
            self.persist()
        self.persist()
    def events(self):
        result=[]
        for p in sorted(self.root.glob('event-*.json')):
            require(not p.is_symlink(),'linked event')
            result.append(json.loads(p.read_text()))
        return result
    def await_event(self, kind, timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            rows=self.events()
            if any(r.get('type')==kind for r in rows): return rows
            if (self.root/'journal-error.txt').exists(): raise ValueError('fixture journal failed')
            time.sleep(.05)
        raise ValueError('fixture event timed out: '+kind)


class Video:
    def __init__(self, device, output):
        self.output=output
        self.stream=(output/'recording.log').open('wb')
        self.argv=['xcrun','simctl','io',device,'recordVideo','--codec=h264',str(output/'screen.mp4')]
        self.started=time.monotonic()
        self.process=subprocess.Popen(self.argv,stdout=self.stream,stderr=subprocess.STDOUT,start_new_session=True)
        self.stopped=False
    def stop(self):
        if self.stopped: return
        self.stopped=True; forced=False; sigint_sent=False; stop_requested=time.monotonic()
        if self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGINT);sigint_sent=True
            try:self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                forced=True;os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=10)
        self.stream.close()
        atomic(self.output/'recording-process.json',{'argv':self.argv,'hostStart':self.started,
            'hostEnd':time.monotonic(),'exitCode':self.process.returncode,'forcedTermination':forced,
            'stopRequested':True,'stopRequestedHostUptime':stop_requested,'sigintSent':sigint_sent,
            'clock':'host time.monotonic; process start is NOT video PTS zero','admissionEligible':False})
        require(not forced and (self.process.returncode==0 or (sigint_sent and self.process.returncode==-signal.SIGINT)) and (self.output/'screen.mp4').is_file(),
                'video did not finalize with normal exit or the requested SIGINT')
