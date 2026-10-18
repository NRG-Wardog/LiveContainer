"""Local decision-test primitive; no simulator/remote execution entrypoint.
A coordinator supplies existing Scope/Commands and calls once before and after
one same-runtime boot. This module cannot boot, install, change or run an app.
"""
import os
import resource
import subprocess
import threading
import time
import process_scope


class Sampler:
    """Prestarted in-process numeric sampler, no subprocess/argv/env/log access."""
    def __init__(self):
        self.stop_event=threading.Event();self.rows=[];self.thread=None;self.error=None;self.terminal=False
    def start(self):
        if self.thread is not None:raise ValueError('one sampler only')
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
    def _run(self):
        try:self._sample()
        except Exception as error:self.error={"type":type(error).__name__}
        finally:self.terminal=True
    def _sample(self):
        end=time.monotonic()+240
        while len(self.rows)<240 and time.monotonic()<end and not self.stop_event.is_set():
            now=time.monotonic();usage=resource.getrusage(resource.RUSAGE_SELF)
            self.rows.append({'monotonic':now,'loadavg':list(os.getloadavg()),
                              'self_user_seconds':usage.ru_utime,'self_system_seconds':usage.ru_stime,
                              'self_maxrss_native_units':usage.ru_maxrss})
            self.stop_event.wait(1)
    def finish(self):
        self.stop_event.set()
        if self.thread is None:raise ValueError('sampler not started')
        self.thread.join(timeout=2)
        if self.thread.is_alive():raise RuntimeError('sampler unjoined; no stable result')
        return {'rows':list(self.rows),'terminal':self.terminal,'error':self.error,'sample_count':len(self.rows)}


def pair(command,phase):
    if phase not in ('before-boot','after-boot'):raise ValueError('fixed phase required')
    results=[]
    for mode in (['minimal','full'] if phase=='before-boot' else ['full','minimal']):
        original=command.scope.gate_mode
        command.scope.gate_mode=mode
        try:row=command('/usr/bin/true',timeout=10,receipt=True)
        finally:command.scope.gate_mode=original
        if not all(r.get('settled') is True for r in command.scope.rows):
            raise RuntimeError('probe settlement unproved')
        probe={'mode':mode,'command_id':row['command_id'],
               'evidence_receipt_file':'probes/commands.jsonl','exit_code':row['exit_code'],'failure':row['primary_error'],
               'cleanup_errors':row['cleanup_errors'],'launch_receipt':row['launch_receipt']}
        # Fixed diagnostic metadata survives a later quiescence/package refusal.
        # This record cannot grant admission or prove target execution.
        process_scope.emit_diagnostic('stall-probe',observation_phase=phase,**probe)
        results.append(probe)
    return {'phase':phase,'probes':results,'admissionEligible':False}
